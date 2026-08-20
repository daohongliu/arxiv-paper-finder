from __future__ import annotations

import base64
import json
import sqlite3
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any

from . import db, pdf
from .classify import decide, parse_screen_result
from .config import AppConfig
from .fetch import ProgressCb, fetch_papers
from .filters import passes_china_filter
from .llm import LLMClient, LLMError, build_client, extract_json, render_prompt

DownloadFn = Callable[[str, str], Any]


def store_papers(conn: sqlite3.Connection, papers: list[dict[str, Any]]) -> int:
    added = 0
    for p in papers:
        row = conn.execute(
            "SELECT id, version, queries_json FROM papers WHERE arxiv_id = ?",
            (p["arxiv_id"],),
        ).fetchone()
        queries = set(p.get("queries", []))
        if row is None:
            conn.execute(
                """INSERT INTO papers (arxiv_id, version, title, abstract, authors_json,
                   primary_category, categories_json, submitted, updated, abs_url, pdf_url,
                   comments, queries_json, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'fetched')""",
                (
                    p["arxiv_id"],
                    p["version"],
                    p["title"],
                    p["abstract"],
                    json.dumps(p["authors_json"]),
                    p["primary_category"],
                    json.dumps(p["categories"]),
                    p["submitted"],
                    p["updated"],
                    p["abs_url"],
                    p["pdf_url"],
                    p.get("comments", ""),
                    json.dumps(sorted(queries)),
                ),
            )
            added += 1
        else:
            merged = set(json.loads(row["queries_json"])) | queries
            updates: dict[str, Any] = {"queries_json": json.dumps(sorted(merged))}
            if p["version"] > row["version"]:
                updates.update(
                    {
                        "version": p["version"],
                        "title": p["title"],
                        "abstract": p["abstract"],
                        "authors_json": json.dumps(p["authors_json"]),
                        "updated": p["updated"],
                        "pdf_url": p["pdf_url"],
                    }
                )
            sets = ", ".join(f"{k} = ?" for k in updates)
            conn.execute(
                f"UPDATE papers SET {sets} WHERE id = ?",
                (*updates.values(), row["id"]),
            )
    conn.commit()
    return added


def run_fetch(
    conn: sqlite3.Connection,
    cfg: AppConfig,
    date_from: datetime,
    date_to: datetime,
    progress: ProgressCb | None = None,
) -> dict[str, Any]:
    papers = fetch_papers(cfg.search, date_from, date_to, progress)
    added = store_papers(conn, papers)
    return {"fetched": len(papers), "new": added}


def _log_call(
    conn: sqlite3.Connection,
    paper_id: int | None,
    stage: str,
    model: str,
    prompt_version_id: int | None,
    request_summary: str,
    response: dict[str, Any],
) -> None:
    conn.execute(
        """INSERT INTO llm_calls (paper_id, stage, model, prompt_version_id,
           request_summary, response_text, input_tokens, output_tokens, latency_ms, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            paper_id,
            stage,
            model,
            prompt_version_id,
            request_summary[:2000],
            response["text"],
            response.get("input_tokens"),
            response.get("output_tokens"),
            response.get("latency_ms"),
            db.now_iso(),
        ),
    )


def _extraction_task(
    client: LLMClient,
    cfg: AppConfig,
    prompt_text: str,
    paper: dict[str, Any],
    path: Any,
) -> dict[str, Any]:
    first_text = pdf.first_page_text(path, cfg.extraction.max_first_page_chars)
    method = "text"
    author_names = json.loads(paper["authors_json"])
    if len(first_text.strip()) < cfg.extraction.min_text_chars and cfg.extraction.vision_fallback:
        method = "vision"
    if method == "vision":
        png = pdf.first_page_png(path)
        b64 = base64.b64encode(png).decode()
        rendered = render_prompt(
            prompt_text,
            {
                "paper_text": "(see attached image of the paper's first page)",
                "author_names": "; ".join(author_names),
            },
        )
        messages: list[dict[str, Any]] = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": rendered},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{b64}"},
                    },
                ],
            }
        ]
    else:
        rendered = render_prompt(
            prompt_text,
            {"paper_text": first_text, "author_names": "; ".join(author_names)},
        )
        messages = [{"role": "user", "content": rendered}]
    response = client.complete(cfg.models.extraction, messages)
    parsed = extract_json(response["text"])
    authors = parsed.get("authors")
    if not isinstance(authors, list):
        raise ValueError("model output missing 'authors' list")
    return {"authors": authors, "method": method, "response": response,
            "text_chars": len(first_text)}


def _mark_unresolved(conn: sqlite3.Connection, paper: dict[str, Any], cfg: AppConfig, err: str) -> None:
    conn.execute("DELETE FROM affiliations WHERE paper_id = ?", (paper["id"],))
    conn.execute("UPDATE papers SET status = 'unresolved' WHERE id = ?", (paper["id"],))
    conn.execute(
        """INSERT INTO affiliations (paper_id, model, method, status, authors_json,
           error, created_at) VALUES (?, ?, 'text', 'error', '[]', ?, ?)""",
        (paper["id"], cfg.models.extraction, err[:1000], db.now_iso()),
    )
    conn.commit()


def run_affiliations(
    conn: sqlite3.Connection,
    cfg: AppConfig,
    prompt_version_id: int,
    prompt_text: str,
    limit: int | None = None,
    retry_failed: bool = False,
    progress: ProgressCb | None = None,
    should_stop: Callable[[], bool] | None = None,
    client: LLMClient | None = None,
    download_fn: DownloadFn | None = None,
) -> dict[str, int]:
    statuses = "('fetched')" if not retry_failed else "('fetched', 'unresolved')"
    rows = [
        dict(r)
        for r in conn.execute(
            f"SELECT * FROM papers WHERE status IN {statuses} ORDER BY submitted LIMIT ?",
            (limit if limit is not None else -1,),
        ).fetchall()
    ]
    if not rows:
        return {"processed": 0, "ok": 0, "failed": 0}
    client = client or build_client(
        cfg.llm.base_url, cfg.llm.api_key_env, cfg.llm.timeout_sec, cfg.llm.max_retries
    )
    download = download_fn or pdf.ensure_pdf
    stats = {"processed": 0, "ok": 0, "failed": 0}
    stopped = False

    paths: dict[int, Any] = {}
    with ThreadPoolExecutor(max_workers=max(1, cfg.extraction.pdf_concurrency)) as pool:
        futures = {pool.submit(download, p["arxiv_id"], p["pdf_url"]): p for p in rows}
        for i, fut in enumerate(as_completed(futures), 1):
            paper = futures[fut]
            if should_stop and should_stop():
                stopped = True
            if progress:
                progress(i, 2 * len(rows), f"download {paper['arxiv_id']}")
            try:
                paths[paper["id"]] = fut.result()
            except Exception as exc:
                stats["processed"] += 1
                stats["failed"] += 1
                _mark_unresolved(conn, paper, cfg, f"download failed: {exc}")

    pending = [p for p in rows if p["id"] in paths]

    def apply_result(paper: dict[str, Any], out: dict[str, Any]) -> str:
        _log_call(
            conn,
            paper["id"],
            f"affiliations:{out['method']}",
            cfg.models.extraction,
            prompt_version_id,
            f"{paper['arxiv_id']} ({out['method']}, {out['text_chars']} chars)",
            out["response"],
        )
        conn.execute("DELETE FROM affiliations WHERE paper_id = ?", (paper["id"],))
        conn.execute(
            """INSERT INTO affiliations (paper_id, prompt_version_id, model, method, status,
               authors_json, created_at) VALUES (?, ?, ?, ?, 'ok', ?, ?)""",
            (
                paper["id"],
                prompt_version_id,
                cfg.models.extraction,
                out["method"],
                json.dumps(out["authors"]),
                db.now_iso(),
            ),
        )
        ok, reason = passes_china_filter(out["authors"], cfg.china_filter)
        new_status = "affiliated" if ok else "filtered_out"
        conn.execute(
            "UPDATE papers SET status = ?, china_flag = ? WHERE id = ?",
            (new_status, 1 if ok else 0, paper["id"]),
        )
        conn.commit()
        return f"{new_status} ({reason})"

    with ThreadPoolExecutor(max_workers=max(1, cfg.extraction.concurrency)) as pool:
        futures2 = {
            pool.submit(_extraction_task, client, cfg, prompt_text, p, paths[p["id"]]): p
            for p in pending
        }
        for i, fut in enumerate(as_completed(futures2), 1):
            paper = futures2[fut]
            if progress:
                progress(
                    len(rows) + i,
                    2 * len(rows),
                    f"extract {paper['arxiv_id']}",
                )
            stats["processed"] += 1
            try:
                out = fut.result()
                detail = apply_result(paper, out)
                stats["ok"] += 1
                if progress:
                    progress(2 * len(rows), 2 * len(rows), f"{paper['arxiv_id']}: {detail}")
            except Exception as exc:
                stats["failed"] += 1
                _mark_unresolved(conn, paper, cfg, f"extraction failed: {exc}")
            if should_stop and should_stop():
                stopped = True

    if stopped and should_stop and should_stop():
        stats["cancelled"] = 1
    return stats


def _screen_task(
    client: LLMClient,
    cfg: AppConfig,
    prompt_text: str,
    paper: dict[str, Any],
    fulltext: bool,
) -> dict[str, Any]:
    extra = ""
    stage = "screen"
    if fulltext:
        path = pdf.ensure_pdf(paper["arxiv_id"], paper["pdf_url"])
        text = pdf.full_text(path, cfg.screen.fulltext_page_limit, cfg.screen.fulltext_max_chars)
        extra = (
            f"\nFull text (first {cfg.screen.fulltext_page_limit} pages):\n"
            f"<<<\n{text}\n>>>\n"
        )
        stage = "screen_fulltext"
    rendered = render_prompt(
        prompt_text,
        {
            "title": paper["title"],
            "abstract": paper["abstract"],
            "categories": ", ".join(json.loads(paper["categories_json"])),
            "extra": extra,
        },
    )
    model = cfg.models.screen_strong if fulltext else cfg.models.screen_cheap
    response = client.complete(model, [{"role": "user", "content": rendered}])
    result = parse_screen_result(extract_json(response["text"]))
    calls = [(stage, response)]
    n_judges = 2 if cfg.screen.double_judge and not fulltext else 1
    for _ in range(n_judges - 1):
        try:
            response2 = client.complete(model, [{"role": "user", "content": rendered}])
            calls.append((stage + ":judge2", response2))
            raw2 = extract_json(response2["text"])
            r2 = parse_screen_result(raw2)
            if r2.is_frontier_ai_safety != result.is_frontier_ai_safety:
                result.confidence = min(result.confidence, r2.confidence) * 0.8
        except (ValueError, LLMError):
            result.confidence *= 0.8
    return {"result": result, "calls": calls, "fulltext": fulltext, "model": model}


def _apply_screen(
    conn: sqlite3.Connection,
    paper: dict[str, Any],
    cfg: AppConfig,
    prompt_version_id: int,
    out: dict[str, Any],
) -> str:
    for stage, response in out["calls"]:
        _log_call(
            conn,
            paper["id"],
            stage,
            out["model"],
            prompt_version_id,
            f"{paper['arxiv_id']} fulltext={out['fulltext']}",
            response,
        )
    result = out["result"]
    status, action = decide(
        result, cfg.screen.escalate_below, cfg.screen.review_below, out["fulltext"]
    )
    conn.execute(
        """UPDATE papers SET status = ?, category = ?, subcategory = ?,
           confidence = ?, rationale = ? WHERE id = ?""",
        (
            status,
            result.category if result.is_frontier_ai_safety else None,
            result.subcategory if result.is_frontier_ai_safety else None,
            result.confidence,
            result.rationale,
            paper["id"],
        ),
    )
    conn.commit()
    return status


def run_screen(
    conn: sqlite3.Connection,
    cfg: AppConfig,
    prompt_version_id: int,
    prompt_text: str,
    limit: int | None = None,
    retry_review: bool = False,
    progress: ProgressCb | None = None,
    should_stop: Callable[[], bool] | None = None,
    client: LLMClient | None = None,
) -> dict[str, int]:
    statuses = "('affiliated')" if not retry_review else "('affiliated', 'needs_review')"
    rows = [
        dict(r)
        for r in conn.execute(
            f"SELECT * FROM papers WHERE status IN {statuses} ORDER BY submitted LIMIT ?",
            (limit if limit is not None else -1,),
        ).fetchall()
    ]
    if not rows:
        return {"processed": 0, "included": 0, "excluded": 0, "review": 0, "failed": 0,
                "escalated": 0}
    client = client or build_client(
        cfg.llm.base_url, cfg.llm.api_key_env, cfg.llm.timeout_sec, cfg.llm.max_retries
    )
    stats = {"processed": 0, "included": 0, "excluded": 0, "review": 0, "failed": 0,
             "escalated": 0}

    def run_round(papers: list[dict[str, Any]], fulltext: bool, offset: int) -> None:
        with ThreadPoolExecutor(max_workers=max(1, cfg.screen.concurrency)) as pool:
            futures = {
                pool.submit(_screen_task, client, cfg, prompt_text, p, fulltext): p
                for p in papers
            }
            for i, fut in enumerate(as_completed(futures), 1):
                paper = futures[fut]
                if progress:
                    progress(offset + i, offset + len(papers), f"screen {paper['arxiv_id']}")
                stats["processed"] += 1 if not fulltext else 0
                try:
                    out = fut.result()
                    status = _apply_screen(conn, paper, cfg, prompt_version_id, out)
                    if status == "screened_included":
                        stats["included"] += 1
                    elif status == "screened_excluded":
                        stats["excluded"] += 1
                    else:
                        stats["review"] += 1
                except Exception:
                    stats["failed"] += 1
                    conn.execute(
                        "UPDATE papers SET status = 'screen_error' WHERE id = ?",
                        (paper["id"],),
                    )
                    conn.commit()

    run_round(rows, fulltext=False, offset=0)
    if should_stop and should_stop():
        return stats
    escalated = [
        dict(r)
        for r in conn.execute(
            "SELECT * FROM papers WHERE id IN ("
            + ",".join(str(p["id"]) for p in rows)
            + ") AND status = 'needs_review'"
        ).fetchall()
    ]
    stats["escalated"] = len(escalated)
    if escalated:
        run_round(escalated, fulltext=True, offset=len(rows))
        still_review = conn.execute(
            "SELECT COUNT(*) AS n FROM papers WHERE id IN ("
            + ",".join(str(p["id"]) for p in escalated)
            + ") AND status = 'needs_review'"
        ).fetchone()["n"]
        stats["review"] = still_review + (stats["review"] - len(escalated))
    return stats
