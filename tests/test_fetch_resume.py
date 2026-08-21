from __future__ import annotations

import httpx

from arxiv_finder import db, jobs
from arxiv_finder.config import AppConfig, SearchClause, SearchConfig
from arxiv_finder.fetch import fetch_papers


def _cfg_two_clauses() -> SearchConfig:
    return SearchConfig(
        clauses=[
            SearchClause(name="a", query="all:safety"),
            SearchClause(name="b", query="all:robustness"),
        ],
        min_interval_sec=0.0,
    )


def test_fetch_papers_start_unit_skips(monkeypatch):
    calls: list[str] = []

    def fake_slice(client, base_url, query, page_size, throttle, max_retries=8,
                   max_results=None):
        calls.append(query)
        return ([], 0)

    import arxiv_finder.fetch as fmod

    monkeypatch.setattr(fmod, "fetch_slice", fake_slice)
    from datetime import datetime

    # 2 clauses x 1 slice-month (single-month window) = 2 units; start_unit=3 skips all
    fetch_papers(_cfg_two_clauses(), datetime(2025, 4, 1), datetime(2025, 4, 2),
                 start_unit=3)
    assert calls == []

    calls.clear()
    fetch_papers(_cfg_two_clauses(), datetime(2025, 4, 1), datetime(2025, 4, 2),
                 start_unit=1)
    assert len(calls) == 1  # only the 2nd unit ran


def test_fetch_resumes_after_rate_limit_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("ARXIV_FINDER_DATA", str(tmp_path))
    conn = db.connect()
    db.init_db(conn)
    db.seed_config(conn, AppConfig().model_dump_json())
    db.seed_prompt(conn, "affiliations", "x")
    db.seed_prompt(conn, "screen", "x")

    import arxiv_finder.fetch as fmod

    state = {"fail_on_call": 3, "calls": 0}

    def fake_slice(client, base_url, query, page_size, throttle, max_retries=8,
                   max_results=None):
        state["calls"] += 1
        if state["calls"] == state["fail_on_call"]:
            raise httpx.HTTPError("simulated rate-limit death")
        n = state["calls"]
        paper = {
            "arxiv_id": f"2504.{n:05d}",
            "version": 1,
            "title": f"paper {n}",
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
        return ([paper], 1)

    monkeypatch.setattr(fmod, "fetch_slice", fake_slice)
    monkeypatch.setattr(
        "arxiv_finder.pdf.ensure_pdf", lambda aid, url: tmp_path / f"{aid}.pdf"
    )

    from arxiv_finder import worker

    job_id = jobs.enqueue_job(
        conn, "fetch",
        {"date_from": "2025-04-01T00:00:00", "date_to": "2025-04-02T00:00:00"},
    )
    row = jobs.claim_next_job(conn)
    worker._execute(conn, row)
    r = conn.execute("SELECT status, error FROM jobs WHERE id=?", (job_id,)).fetchone()
    assert r["status"] == "failed"
    assert state["calls"] == 3  # died on the 3rd unit

    # simulate user pressing Resume
    assert jobs.resume_job(conn, job_id)
    row = jobs.claim_next_job(conn)
    state["fail_on_call"] = -1  # no more failures
    worker._execute(conn, row)
    r = conn.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()
    assert r["status"] == "done"
    
    n_clauses = len(AppConfig().search.clauses)
    # units 1-2 NOT re-fetched: only units 3..n ran on resume (50 units)
    assert state["calls"] == 3 + (n_clauses - 2)
    log = conn.execute("SELECT log_tail FROM jobs WHERE id=?", (job_id,)).fetchone()["log_tail"]
    assert f"resume: fetch continues from unit 2/{n_clauses}" in log
    # Run 1 failed before storing papers; Run 2 successfully stored the 50 resumed papers
    assert conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0] == (n_clauses - 2)
