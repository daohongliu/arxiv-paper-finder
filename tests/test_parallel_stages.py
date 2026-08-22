from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pymupdf
import pytest

from arxiv_finder import db, pdf, stages
from arxiv_finder.config import AppConfig

AFF_JSON = json.dumps(
    {
        "authors": [
            {"name": "A", "affiliation_raw": "MIT", "institution": "MIT",
             "country": "USA", "mainland_china": "no"},
            {"name": "B", "affiliation_raw": "Tsinghua University",
             "institution": "Tsinghua University", "country": "China",
             "mainland_china": "yes"},
        ],
        "notes": "",
    }
)

SCREEN_INCLUDE = json.dumps(
    {"is_frontier_ai_safety": True, "confidence": 0.9, "category": "alignment",
     "subcategory": None, "rationale": "safety"}
)

SCREEN_ESCALATE = json.dumps(
    {"is_frontier_ai_safety": True, "confidence": 0.2, "category": "alignment",
     "subcategory": None, "rationale": "unsure"}
)

SCREEN_FULLTEXT_INCLUDE = json.dumps(
    {"is_frontier_ai_safety": True, "confidence": 0.95, "category": "robustness",
     "subcategory": None, "rationale": "safety"}
)


class StubLLM:
    def __init__(self, payloads: list[str], sleep: float = 0.05) -> None:
        self.payloads = payloads
        self.sleep = sleep
        self.call_count = 0
        self.active = 0
        self.peak = 0
        self._lock = threading.Lock()

    def complete(self, model, messages, **kwargs):
        with self._lock:
            idx = self.call_count
            self.call_count += 1
            self.active += 1
            self.peak = max(self.peak, self.active)
        time.sleep(self.sleep)
        with self._lock:
            self.active -= 1
        text = self.payloads[idx] if idx < len(self.payloads) else self.payloads[-1]
        return {"text": text, "input_tokens": 10, "output_tokens": 20, "latency_ms": 5}


def _insert_papers(conn, n: int, status: str = "fetched") -> None:
    for i in range(n):
        conn.execute(
            """INSERT INTO papers (arxiv_id, title, abstract, authors_json, categories_json,
               submitted, updated, abs_url, pdf_url, queries_json, status)
               VALUES (?, ?, 'abs', '["A","B"]', '["cs.AI"]', '2025-04-01T00:00:00Z', '',
                       '', ?, '[]', ?)""",
            (f"2504.{i:05d}", f"paper {i}", f"https://arxiv.org/pdf/2504.{i:05d}v1", status),
        )
    conn.commit()


def _fake_pdf() -> bytes:
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "A Paper\nAuthor One, Author Two\nTsinghua University, MIT")
    data = doc.tobytes()
    doc.close()
    return data


@pytest.fixture()
def pdf_bytes():
    return _fake_pdf()


def test_run_affiliations_parallel(conn, tmp_path, pdf_bytes, monkeypatch):
    db.seed_prompt(conn, "affiliations", "extract {{paper_text}} {{author_names}}")
    pid, text = db.get_prompt(conn, "affiliations")
    cfg = AppConfig()
    cfg.extraction.concurrency = 8
    cfg.extraction.pdf_concurrency = 8
    _insert_papers(conn, 12)

    files: dict[str, Path] = {}

    def fake_download(arxiv_id: str, url: str) -> Path:
        p = tmp_path / f"{arxiv_id}.pdf"
        p.write_bytes(pdf_bytes)
        files[arxiv_id] = p
        return p

    stub = StubLLM([AFF_JSON])
    events: list[str] = []
    stats = stages.run_affiliations(
        conn, cfg, pid, text, client=stub, download_fn=fake_download,
        progress=lambda d, t, c: events.append(c),
    )
    assert stats["ok"] == 12 and stats["failed"] == 0
    assert stub.peak >= 2, f"expected parallel LLM calls, peak={stub.peak}"
    rows = conn.execute("SELECT status, china_flag FROM papers").fetchall()
    assert all(r["status"] == "affiliated" and r["china_flag"] == 1 for r in rows)
    assert conn.execute("SELECT COUNT(*) AS n FROM affiliations").fetchone()["n"] == 12
    assert conn.execute("SELECT COUNT(*) AS n FROM llm_calls").fetchone()["n"] == 12
    assert events


def test_run_affiliations_download_failure(conn, tmp_path, monkeypatch):
    db.seed_prompt(conn, "affiliations", "x")
    pid, text = db.get_prompt(conn, "affiliations")
    cfg = AppConfig()
    _insert_papers(conn, 2)

    def failing_download(arxiv_id: str, url: str):
        raise RuntimeError("boom")

    stub = StubLLM([AFF_JSON])
    stats = stages.run_affiliations(conn, cfg, pid, text, client=stub,
                                    download_fn=failing_download)
    assert stats["failed"] == 2 and stats["ok"] == 0
    rows = conn.execute("SELECT status FROM papers").fetchall()
    assert all(r["status"] == "unresolved" for r in rows)
    retried = stages.run_affiliations(conn, cfg, pid, text, retry_failed=True,
                                      client=stub, download_fn=failing_download)
    assert retried["failed"] == 2


def test_run_affiliations_withdrawn_is_dropped(conn):
    db.seed_prompt(conn, "affiliations", "x")
    pid, text = db.get_prompt(conn, "affiliations")
    cfg = AppConfig()
    _insert_papers(conn, 2)

    def withdrawn_download(arxiv_id: str, url: str):
        raise pdf.PDFNotFoundError("HTTP 404: withdrawn")

    stub = StubLLM([AFF_JSON])
    stats = stages.run_affiliations(conn, cfg, pid, text, client=stub,
                                    download_fn=withdrawn_download)
    assert stats["failed"] == 2 and stats["ok"] == 0
    rows = conn.execute("SELECT status FROM papers").fetchall()
    assert all(r["status"] == "withdrawn" for r in rows)
    # Withdrawn papers are permanently dropped: a retry pass must not pick them up.
    retried = stages.run_affiliations(conn, cfg, pid, text, retry_failed=True,
                                      client=stub, download_fn=withdrawn_download)
    assert retried["processed"] == 0


def test_run_screen_parallel(conn):
    db.seed_prompt(conn, "screen", "{{title}} {{abstract}} {{categories}} {{extra}}")
    pid, text = db.get_prompt(conn, "screen")
    cfg = AppConfig()
    cfg.screen.concurrency = 8
    _insert_papers(conn, 10, status="affiliated")
    stub = StubLLM([SCREEN_INCLUDE])
    stats = stages.run_screen(conn, cfg, pid, text, client=stub)
    assert stats["included"] == 10 and stats["failed"] == 0
    assert stub.peak >= 2
    rows = conn.execute("SELECT status, category FROM papers").fetchall()
    assert all(r["status"] == "screened_included" and r["category"] == "alignment"
               for r in rows)


def test_run_screen_no_escalation_auto_excludes(conn, tmp_path, pdf_bytes, monkeypatch):
    monkeypatch.setenv("ARXIV_FINDER_DATA", str(tmp_path / "data"))
    db.seed_prompt(conn, "screen", "{{title}} {{abstract}} {{categories}} {{extra}}")
    pid, text = db.get_prompt(conn, "screen")
    cfg = AppConfig()
    cfg.screen.concurrency = 4
    _insert_papers(conn, 1, status="affiliated")
    cache_path = pdf.pdf_path("2504.00000")
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_bytes(pdf_bytes)
    stub = StubLLM([SCREEN_ESCALATE, SCREEN_FULLTEXT_INCLUDE])
    stats = stages.run_screen(conn, cfg, pid, text, client=stub)
    assert stats["escalated"] == 0
    assert stats["excluded"] == 1
    assert stub.call_count == 1
    row = conn.execute("SELECT status, category FROM papers").fetchone()
    assert row["status"] == "screened_excluded"
    assert row["category"] is None
    stages_seen = {r["stage"] for r in conn.execute("SELECT stage FROM llm_calls")}
    assert stages_seen == {"screen"}


def test_run_screen_llm_error_marks_error(conn):
    db.seed_prompt(conn, "screen", "x {{title}} {{abstract}} {{categories}} {{extra}}")
    pid, text = db.get_prompt(conn, "screen")
    cfg = AppConfig()
    _insert_papers(conn, 1, status="affiliated")
    stub = StubLLM(["not json at all"])
    stats = stages.run_screen(conn, cfg, pid, text, client=stub)
    assert stats["failed"] == 1
    assert conn.execute("SELECT status FROM papers").fetchone()["status"] == "screen_error"


def test_run_screen_retry_includes_screen_error(conn):
    db.seed_prompt(conn, "screen", "x {{title}} {{abstract}} {{categories}} {{extra}}")
    pid, text = db.get_prompt(conn, "screen")
    cfg = AppConfig()
    _insert_papers(conn, 1, status="screen_error")
    good = json.dumps(
        {"is_frontier_ai_safety": True, "confidence": 0.9, "category": "alignment",
         "subcategory": None, "rationale": "safety"}
    )
    stub = StubLLM([good])
    stages.run_screen(conn, cfg, pid, text, retry_review=True, client=stub)
    assert conn.execute("SELECT status FROM papers").fetchone()["status"] == "screened_included"


ALL_UNCLEAR_JSON = json.dumps(
    {
        "authors": [
            {"name": "A One", "institution": "", "country": "unclear", "mainland_china": "unclear"},
            {"name": "B Two", "institution": "", "country": "unclear", "mainland_china": "unclear"},
        ]
    }
)

LIKELY_YES_JSON = json.dumps(
    {
        "likely_mainland_china": "yes",
        "authors": [
            {"name": "A One", "institution": "", "country": "unclear", "mainland_china": "unclear"},
            {"name": "B Two", "institution": "", "country": "unclear", "mainland_china": "unclear"},
        ],
    }
)

LIKELY_NO_JSON = json.dumps(
    {
        "likely_mainland_china": "no",
        "authors": [
            {"name": "John Smith", "institution": "MIT", "country": "USA", "mainland_china": "no"},
            {"name": "Anna Novak", "institution": "Oxford", "country": "UK", "mainland_china": "no"},
        ],
    }
)


def test_run_affiliations_all_unclear_keeps_for_recall(conn, tmp_path, pdf_bytes, monkeypatch):
    monkeypatch.setenv("ARXIV_FINDER_DATA", str(tmp_path))
    db.seed_prompt(conn, "affiliations", "extract {{paper_text}} {{author_names}}")
    pid, text = db.get_prompt(conn, "affiliations")
    cfg = AppConfig()
    _insert_papers(conn, 1)

    def fake_download(arxiv_id: str, url: str) -> Path:
        p = tmp_path / f"{arxiv_id}.pdf"
        p.write_bytes(pdf_bytes)
        return p

    stub = StubLLM([ALL_UNCLEAR_JSON])
    stats = stages.run_affiliations(conn, cfg, pid, text, client=stub,
                                    download_fn=fake_download)
    assert stats["ok"] == 1
    row = conn.execute("SELECT status, china_flag FROM papers").fetchone()
    assert row["status"] == "affiliated"
    assert row["china_flag"] == 1


def test_run_affiliations_likely_mainland_promotes(conn, tmp_path, pdf_bytes, monkeypatch):
    monkeypatch.setenv("ARXIV_FINDER_DATA", str(tmp_path))
    db.seed_prompt(conn, "affiliations", "extract {{paper_text}} {{author_names}}")
    pid, text = db.get_prompt(conn, "affiliations")
    cfg = AppConfig()
    _insert_papers(conn, 1)

    def fake_download(arxiv_id: str, url: str) -> Path:
        p = tmp_path / f"{arxiv_id}.pdf"
        p.write_bytes(pdf_bytes)
        return p

    stub = StubLLM([LIKELY_YES_JSON])
    stats = stages.run_affiliations(conn, cfg, pid, text, client=stub,
                                    download_fn=fake_download)
    assert stats["ok"] == 1
    row = conn.execute("SELECT status, china_flag FROM papers").fetchone()
    assert row["status"] == "affiliated"
    assert row["china_flag"] == 1
    aff = conn.execute("SELECT likely_mainland_china FROM affiliations").fetchone()
    assert aff["likely_mainland_china"] == "yes"


def test_run_affiliations_likely_no_excludes(conn, tmp_path, pdf_bytes, monkeypatch):
    monkeypatch.setenv("ARXIV_FINDER_DATA", str(tmp_path))
    db.seed_prompt(conn, "affiliations", "extract {{paper_text}} {{author_names}}")
    pid, text = db.get_prompt(conn, "affiliations")
    cfg = AppConfig()
    _insert_papers(conn, 1)

    def fake_download(arxiv_id: str, url: str) -> Path:
        p = tmp_path / f"{arxiv_id}.pdf"
        p.write_bytes(pdf_bytes)
        return p

    stub = StubLLM([LIKELY_NO_JSON])
    stats = stages.run_affiliations(conn, cfg, pid, text, client=stub,
                                    download_fn=fake_download)
    assert stats["ok"] == 1
    row = conn.execute("SELECT status, china_flag FROM papers").fetchone()
    assert row["status"] == "filtered_out"
    assert row["china_flag"] == 0
    aff = conn.execute("SELECT likely_mainland_china FROM affiliations").fetchone()
    assert aff["likely_mainland_china"] == "no"
