from __future__ import annotations

import json

from arxiv_finder import db, jobs, worker
from arxiv_finder.config import AppConfig

AFF_JSON = json.dumps(
    {
        "authors": [
            {
                "name": "Wei Zhang",
                "institution": "Tsinghua University",
                "country": "China",
                "mainland_china": "yes",
            }
        ]
    }
)

SCREEN_JSON = json.dumps(
    {
        "is_frontier_ai_safety": True,
        "confidence": 0.9,
        "category": "alignment",
        "subcategory": None,
        "rationale": "safety",
    }
)


class StubLLM:
    """Routes by prompt content so the parallel calls stay deterministic."""

    def complete(self, model, messages, **kwargs):
        content = messages[0]["content"]
        if isinstance(content, list):
            content = " ".join(
                str(c.get("text", "")) for c in content if isinstance(c, dict)
            )
        if "EXTRACT" in content:
            return {"text": AFF_JSON, "input_tokens": 1, "output_tokens": 1,
                    "latency_ms": 1}
        return {"text": SCREEN_JSON, "input_tokens": 1, "output_tokens": 1,
                "latency_ms": 1}


def _paper(n: int) -> dict:
    return {
        "arxiv_id": f"2504.{n:05d}",
        "version": 1,
        "title": f"Safety Paper {n}",
        "abstract": "abs",
        "authors_json": ["Wei Zhang"],
        "primary_category": "cs.AI",
        "categories": ["cs.AI"],
        "submitted": "2025-04-01T00:00:00Z",
        "updated": "2025-04-01T00:00:00Z",
        "abs_url": "",
        "pdf_url": f"https://arxiv.org/pdf/2504.{n:05d}v1",
        "comments": "",
    }


def test_pipeline_end_to_end(conn, tmp_path, monkeypatch):
    """A full pipeline job (fetch → download → affiliations → screen) reaches
    done and both papers land in screened_included with calls logged."""
    monkeypatch.setenv("ARXIV_FINDER_DATA", str(tmp_path / "data"))
    db.seed_config(conn, AppConfig().model_dump_json())
    db.seed_prompt(conn, "affiliations", "EXTRACT {{paper_text}} {{author_names}}")
    db.seed_prompt(conn, "screen", "SCREEN {{title}} {{abstract}} {{categories}} {{extra}}")

    import arxiv_finder.fetch as fmod
    import arxiv_finder.pdf as pmod
    import arxiv_finder.stages as smod

    monkeypatch.setattr(
        fmod,
        "fetch_slice",
        lambda client, base_url, query, page_size, throttle, max_retries=8,
        max_results=None: ([_paper(1), _paper(2)], 2),
    )
    monkeypatch.setattr(
        pmod, "ensure_pdf", lambda aid, url: tmp_path / "data" / "pdfs" / f"{aid}.pdf"
    )
    monkeypatch.setattr(pmod, "first_page_text", lambda path, max_chars: "x" * 300)
    monkeypatch.setattr(
        smod,
        "build_client",
        lambda base_url, api_key_env, timeout_sec, max_retries: StubLLM(),
    )

    job_id = jobs.enqueue_job(
        conn,
        "pipeline",
        {"date_from": "2025-04-01T00:00:00", "date_to": "2025-04-30T23:59:59"},
    )
    row = jobs.claim_next_job(conn)
    worker._execute(conn, row)

    final = conn.execute("SELECT status, error FROM jobs WHERE id = ?", (job_id,)).fetchone()
    assert final["status"] == "done", final["error"]

    papers = conn.execute(
        "SELECT arxiv_id, status, category FROM papers ORDER BY arxiv_id"
    ).fetchall()
    assert [(p["arxiv_id"], p["status"]) for p in papers] == [
        ("2504.00001", "screened_included"),
        ("2504.00002", "screened_included"),
    ]
    assert all(p["category"] == "alignment" for p in papers)
    assert conn.execute("SELECT COUNT(*) AS n FROM llm_calls").fetchone()["n"] == 4


def test_worker_requeues_stale_running_jobs(conn):
    db.seed_config(conn, AppConfig().model_dump_json())
    db.seed_prompt(conn, "affiliations", "x")
    db.seed_prompt(conn, "screen", "x")
    job_id = jobs.enqueue_job(conn, "fetch", {"date_from": "a", "date_to": "b"})
    conn.execute("UPDATE jobs SET status = 'running' WHERE id = ?", (job_id,))
    conn.commit()

    assert jobs.requeue_stale_running(conn) == 1
    row = conn.execute("SELECT status FROM jobs WHERE id = ?", (job_id,)).fetchone()
    assert row["status"] == "queued"
