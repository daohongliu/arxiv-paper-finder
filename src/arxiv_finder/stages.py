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
from .names import any_plausible_chinese_author

DownloadFn = Callable[[str, str], Any]


def store_papers(conn: sqlite3.Connection, papers: list[dict[str, Any]]) -> dict[str, int]:
    added = 0
    name_filtered = 0
    for p in papers:
        row = conn.execute(
            "SELECT id, version, queries_json, status FROM papers WHERE arxiv_id = ?",
            (p["arxiv_id"],),
        ).fetchone()
        queries = set(p.get("queries", []))
        if row is None:
            if any_plausible_chinese_author(p["authors_json"]):
                status = "fetched"
            else:
                status = "filtered_out"
                name_filtered += 1
            conn.execute(
                """INSERT INTO papers (arxiv_id, version, title, abstract, authors_json,
                   primary_category, categories_json, submitted, updated, abs_url, pdf_url,
                   comments, queries_json, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                    status,
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
                # A new version can add a Chinese author; a paper we previously
                # name-filtered should then be promoted so it isn't lost forever.
                if row["status"] == "filtered_out" and any_plausible_chinese_author(
                    p["authors_json"]
                ):
                    updates["status"] = "fetched"
            sets = ", ".join(f"{k} = ?" for k in updates)
            conn.execute(
                f"UPDATE papers SET {sets} WHERE id = ?",
                (*updates.values(), row["id"]),
            )
    conn.commit()
    return {"added": added, "name_filtered": name_filtered}


def run_fetch(
    conn: sqlite3.Connection,
    cfg: AppConfig,
    date_from: datetime,
    date_to: datetime,
    progress: ProgressCb | None = None,
    should_stop: Callable[[], bool] | None = None,
    start_unit: int = 0,
    unit_done: Callable[[int], None] | None = None,
) -> dict[str, Any]:
    papers = fetch_papers(
        cfg.search, date_from, date_to, progress, should_stop,
        start_unit=start_unit, unit_done=unit_done,
    )
    stored = store_papers(conn, papers)
    return {"fetched": len(papers), "new": stored["added"],
            "name_filtered": stored["name_filtered"]}


def _chunks(seq: list[Any], size: int) -> list[list[Any]]:
    return [seq[i : i + size] for i in range(0, len(seq), max(1, size))]


def run_download(
    conn: sqlite3.Connection,
    cfg: AppConfig,
    progress: ProgressCb | None = None,
    should_stop: Callable[[], bool] | None = None,
    download_fn: DownloadFn | None = None,
) -> dict[str, int]:
    rows = conn.execute(
        "SELECT arxiv_id, pdf_url FROM papers WHERE status = 'fetched' ORDER BY submitted"
    ).fetchall()
    todo = [dict(r) for r in rows if not pdf.pdf_path(r["arxiv_id"]).exists()]
    stats = {"missing": len(todo), "downloaded": 0, "failed": 0}
    if not todo:
        return stats
    download = download_fn or pdf.ensure_pdf
    chunk_size = max(1, cfg.extraction.pdf_concurrency) * 2
    done = 0
    for batch in _chunks(todo, chunk_size):
        if should_stop and should_stop():
            break
        with ThreadPoolExecutor(max_workers=max(1, cfg.extraction.pdf_concurrency)) as pool:
            futures = {pool.submit(download, p["arxiv_id"], p["pdf_url"]): p for p in batch}
            for fut in as_completed(futures):
                paper = futures[fut]
                done += 1
                if progress:
                    progress(done, len(todo), f"Downloading PDF for {paper['arxiv_id']}")
                try:
                    fut.result()
                    stats["downloaded"] += 1
                except Exception:
                    stats["failed"] += 1
    return stats


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
    return {"authors": authors, "likely": str(parsed.get("likely_mainland_china") or "").lower(),
            "method": method, "response": response, "text_chars": len(first_text)}


def _mark_unresolved(conn: sqlite3.Connection, paper: dict[str, Any], cfg: AppConfig, err: str) -> None:
    conn.execute("DELETE FROM affiliations WHERE paper_id = ?", (paper["id"],))
    conn.execute("UPDATE papers SET status = 'unresolved' WHERE id = ?", (paper["id"],))
    conn.execute(
        """INSERT INTO affiliations (paper_id, model, method, status, authors_json,
           error, created_at) VALUES (?, ?, 'text', 'error', '[]', ?, ?)""",
        (paper["id"], cfg.models.extraction, err[:1000], db.now_iso()),
    )
    conn.commit()


def _mark_withdrawn(conn: sqlite3.Connection, paper: dict[str, Any], cfg: AppConfig, err: str) -> None:
    """Permanently drop a paper whose PDF is unavailable (withdrawn/removed).

    Unlike ``unresolved`` (retried on the next retry pass), ``withdrawn`` papers are
    excluded from the pipeline for good: no amount of retrying will produce a PDF.
    """
    conn.execute("DELETE FROM affiliations WHERE paper_id = ?", (paper["id"],))
    conn.execute(
        "UPDATE papers SET status = 'withdrawn', china_flag = 0 WHERE id = ?", (paper["id"],)
    )
    conn.execute(
        """INSERT INTO affiliations (paper_id, model, method, status, authors_json,
           error, created_at) VALUES (?, ?, 'text', 'error', '[]', ?, ?)""",
        (paper["id"], cfg.models.extraction, err[:1000], db.now_iso()),
    )
    conn.commit()


def _apply_affiliation(
    conn: sqlite3.Connection,
    paper: dict[str, Any],
    cfg: AppConfig,
    prompt_version_id: int,
    out: dict[str, Any],
) -> str:
    """Persist one affiliation-extraction result and re-derive the paper's status.

    Shared by the batch ``run_affiliations`` and the single-paper ``affiliate_one``.
    """
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
           authors_json, likely_mainland_china, created_at)
           VALUES (?, ?, ?, ?, 'ok', ?, ?, ?)""",
        (
            paper["id"],
            prompt_version_id,
            cfg.models.extraction,
            out["method"],
            json.dumps(out["authors"]),
            out.get("likely") or "",
            db.now_iso(),
        ),
    )
    ok, reason = passes_china_filter(out["authors"], cfg.china_filter)
    likely = (out.get("likely") or "").strip().lower()
    if ok:
        new_status = "affiliated"
    elif likely == "no":
        new_status = "filtered_out"
        reason = f"{reason}; paper-level verdict: no mainland involvement"
    else:
        # Recall-oriented keep: the model either judged the paper plausibly
        # mainland ("yes") or couldn't rule it out ("unclear"/missing). Only
        # an explicit "no" excludes; uncertainty keeps the paper so it is
        # never silently dropped before screening.
        ok = True
        new_status = "affiliated"
        reason = f"{reason}; paper-level verdict: {likely or 'unclear'} → keep for recall"
    conn.execute(
        "UPDATE papers SET status = ?, china_flag = ? WHERE id = ?",
        (new_status, 1 if ok else 0, paper["id"]),
    )
    conn.commit()
    return f"{new_status} ({reason})"


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
    chunk_size = max(1, cfg.extraction.pdf_concurrency) * 2
    downloaded = 0
    for batch in _chunks(rows, chunk_size):
        if should_stop and should_stop():
            stopped = True
            break
        with ThreadPoolExecutor(max_workers=max(1, cfg.extraction.pdf_concurrency)) as pool:
            futures = {pool.submit(download, p["arxiv_id"], p["pdf_url"]): p for p in batch}
            for fut in as_completed(futures):
                paper = futures[fut]
                downloaded += 1
                if should_stop and should_stop():
                    stopped = True
                if progress:
                    progress(downloaded, 2 * len(rows), f"Downloading PDF for {paper['arxiv_id']}")
                try:
                    paths[paper["id"]] = fut.result()
                except pdf.PDFNotFoundError as exc:
                    stats["processed"] += 1
                    stats["failed"] += 1
                    _mark_withdrawn(conn, paper, cfg, f"withdrawn/unavailable: {exc}")
                except Exception as exc:
                    stats["processed"] += 1
                    stats["failed"] += 1
                    _mark_unresolved(conn, paper, cfg, f"download failed: {exc}")

    pending = [p for p in rows if p["id"] in paths]

    extract_chunk = max(1, cfg.extraction.concurrency) * 2
    extracted = 0
    for batch in _chunks(pending, extract_chunk):
        if should_stop and should_stop():
            stopped = True
            break
        with ThreadPoolExecutor(max_workers=max(1, cfg.extraction.concurrency)) as pool:
            futures2 = {
                pool.submit(_extraction_task, client, cfg, prompt_text, p, paths[p["id"]]): p
                for p in batch
            }
            for fut in as_completed(futures2):
                paper = futures2[fut]
                extracted += 1
                if progress:
                    progress(
                        len(rows) + extracted,
                        2 * len(rows),
                        f"Identifying affiliations for {paper['arxiv_id']}",
                    )
                stats["processed"] += 1
                try:
                    out = fut.result()
                    detail = _apply_affiliation(conn, paper, cfg, prompt_version_id, out)
                    stats["ok"] += 1
                    if progress:
                        verdict = (
                            "kept for screening"
                            if detail.startswith("affiliated")
                            else "skipped (no China affiliation)"
                        )
                        progress(
                            len(rows) + extracted, 2 * len(rows),
                            f"{paper['arxiv_id']}: {verdict}",
                        )
                except Exception as exc:
                    stats["failed"] += 1
                    _mark_unresolved(conn, paper, cfg, f"extraction failed: {exc}")
                if should_stop and should_stop():
                    stopped = True

    if stopped:
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
    included = status == "screened_included"
    conn.execute(
        """UPDATE papers SET status = ?, category = ?, subcategory = ?,
           confidence = ?, rationale = ? WHERE id = ?""",
        (
            status,
            result.category if included else None,
            result.subcategory if included else None,
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
    statuses = (
        "('affiliated')"
        if not retry_review
        else "('affiliated', 'needs_review', 'screen_error')"
    )
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
        chunk_size = max(1, cfg.screen.concurrency) * 2
        processed = 0
        for batch in _chunks(papers, chunk_size):
            if should_stop and should_stop():
                break
            with ThreadPoolExecutor(max_workers=max(1, cfg.screen.concurrency)) as pool:
                futures = {
                    pool.submit(_screen_task, client, cfg, prompt_text, p, fulltext): p
                    for p in batch
                }
                for fut in as_completed(futures):
                    paper = futures[fut]
                    processed += 1
                    stats["processed"] += 1 if not fulltext else 0
                    try:
                        out = fut.result()
                        status = _apply_screen(conn, paper, cfg, prompt_version_id, out)
                        if status == "screened_included":
                            stats["included"] += 1
                            verdict = "included in dataset"
                        elif status == "screened_excluded":
                            stats["excluded"] += 1
                            verdict = "excluded"
                        else:
                            stats["review"] += 1
                            verdict = "flagged for human review"
                        if progress:
                            progress(
                                offset + processed, offset + len(papers),
                                f"{paper['arxiv_id']}: {verdict}",
                            )
                    except Exception:
                        stats["failed"] += 1
                        conn.execute(
                            "UPDATE papers SET status = 'screen_error' WHERE id = ?",
                            (paper["id"],),
                        )
                        conn.commit()
                        if progress:
                            progress(
                                offset + processed, offset + len(papers),
                                f"{paper['arxiv_id']}: failed to classify",
                            )
                    if should_stop and should_stop():
                        break

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


def affiliate_one(
    conn: sqlite3.Connection,
    cfg: AppConfig,
    paper_id: int,
    prompt_version_id: int,
    prompt_text: str,
    client: LLMClient | None = None,
    download_fn: DownloadFn | None = None,
) -> dict[str, Any]:
    """Run the affiliations stage on a single paper, regardless of its current status."""
    row = conn.execute("SELECT * FROM papers WHERE id = ?", (paper_id,)).fetchone()
    if row is None:
        raise KeyError(f"paper {paper_id} not found")
    paper = dict(row)
    client = client or build_client(
        cfg.llm.base_url, cfg.llm.api_key_env, cfg.llm.timeout_sec, cfg.llm.max_retries
    )
    download = download_fn or pdf.ensure_pdf
    try:
        path = download(paper["arxiv_id"], paper["pdf_url"])
    except pdf.PDFNotFoundError as exc:
        _mark_withdrawn(conn, paper, cfg, f"withdrawn/unavailable: {exc}")
        return {"status": "withdrawn", "error": str(exc), "detail": str(exc)}
    except Exception as exc:
        _mark_unresolved(conn, paper, cfg, f"download failed: {exc}")
        return {"status": "unresolved", "error": str(exc), "detail": str(exc)}
    try:
        out = _extraction_task(client, cfg, prompt_text, paper, path)
    except Exception as exc:
        _mark_unresolved(conn, paper, cfg, f"extraction failed: {exc}")
        return {"status": "unresolved", "error": str(exc), "detail": str(exc)}
    detail = _apply_affiliation(conn, paper, cfg, prompt_version_id, out)
    new = conn.execute(
        "SELECT status, china_flag FROM papers WHERE id = ?", (paper_id,)
    ).fetchone()
    return {
        "status": new["status"],
        "china_flag": new["china_flag"],
        "detail": detail,
        "likely_mainland_china": out.get("likely") or "",
        "method": out["method"],
    }


def screen_one(
    conn: sqlite3.Connection,
    cfg: AppConfig,
    paper_id: int,
    prompt_version_id: int,
    prompt_text: str,
    client: LLMClient | None = None,
) -> dict[str, Any]:
    """Run the screening stage on a single paper, regardless of its current status.

    Mirrors the batch ``run_screen``: a low-confidence result is escalated to a
    full-text screen before a final ``needs_review`` is settled on.
    """
    row = conn.execute("SELECT * FROM papers WHERE id = ?", (paper_id,)).fetchone()
    if row is None:
        raise KeyError(f"paper {paper_id} not found")
    paper = dict(row)
    client = client or build_client(
        cfg.llm.base_url, cfg.llm.api_key_env, cfg.llm.timeout_sec, cfg.llm.max_retries
    )
    try:
        out = _screen_task(client, cfg, prompt_text, paper, fulltext=False)
    except Exception as exc:
        conn.execute(
            "UPDATE papers SET status = 'screen_error' WHERE id = ?", (paper_id,)
        )
        conn.commit()
        return {"status": "screen_error", "error": str(exc), "escalated": False}
    status = _apply_screen(conn, paper, cfg, prompt_version_id, out)
    escalated = False
    if status == "needs_review":
        try:
            out2 = _screen_task(client, cfg, prompt_text, paper, fulltext=True)
            status = _apply_screen(conn, paper, cfg, prompt_version_id, out2)
            escalated = True
        except Exception as exc:
            # Leave the paper at needs_review for human review; the full-text
            # escalation (which needs a cached/downloadable PDF) failed.
            return {"status": status, "error": f"full-text escalation failed: {exc}",
                    "escalated": False}
    return {"status": status, "escalated": escalated}
