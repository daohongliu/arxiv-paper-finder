from __future__ import annotations

import json
import threading

import pymupdf
import pytest

from arxiv_finder import db, pdf, stages
from arxiv_finder.config import AppConfig

AFF_JSON = json.dumps(
    {
        "likely_mainland_china": "yes",
        "authors": [
            {"name": "A One", "institution": "Tsinghua University", "country": "China",
             "mainland_china": "yes"},
            {"name": "B Two", "institution": "MIT", "country": "USA",
             "mainland_china": "no"},
        ],
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
    def __init__(self, payloads: list[str]) -> None:
        self.payloads = payloads
        self.call_count = 0
        self._lock = threading.Lock()

    def complete(self, model, messages, **kwargs):
        with self._lock:
            idx = self.call_count
            self.call_count += 1
        text = self.payloads[idx] if idx < len(self.payloads) else self.payloads[-1]
        return {"text": text, "input_tokens": 10, "output_tokens": 20, "latency_ms": 5}


def _fake_pdf() -> bytes:
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "A Paper\nAuthor One, Author Two\nTsinghua University")
    data = doc.tobytes()
    doc.close()
    return data


def _insert_paper(conn, status: str = "fetched") -> int:
    cur = conn.execute(
        """INSERT INTO papers (arxiv_id, title, abstract, authors_json, categories_json,
           submitted, updated, abs_url, pdf_url, queries_json, status)
           VALUES ('2504.99999', 'Safety Paper', 'abs', '["A","B"]', '["cs.AI"]',
                   '2025-04-01T00:00:00Z', '', 'u',
                   'https://arxiv.org/pdf/2504.99999v1', '[]', ?)""",
        (status,),
    )
    conn.commit()
    return int(cur.lastrowid or 0)


@pytest.fixture()
def pdf_bytes():
    return _fake_pdf()


def test_affiliate_one_success(conn, tmp_path, pdf_bytes):
    db.seed_prompt(conn, "affiliations", "extract {{paper_text}} {{author_names}}")
    pid, text = db.get_prompt(conn, "affiliations")
    cfg = AppConfig()
    paper_id = _insert_paper(conn)

    def fake_download(arxiv_id, url):
        p = tmp_path / f"{arxiv_id}.pdf"
        p.write_bytes(pdf_bytes)
        return p

    result = stages.affiliate_one(conn, cfg, paper_id, pid, text,
                                  client=StubLLM([AFF_JSON]), download_fn=fake_download)
    assert result["status"] == "affiliated"
    assert result["china_flag"] == 1
    assert result["likely_mainland_china"] == "yes"
    assert conn.execute("SELECT COUNT(*) AS n FROM affiliations").fetchone()["n"] == 1
    assert conn.execute("SELECT COUNT(*) AS n FROM llm_calls").fetchone()["n"] == 1


def test_affiliate_one_missing_paper(conn):
    db.seed_prompt(conn, "affiliations", "x")
    pid, text = db.get_prompt(conn, "affiliations")
    with pytest.raises(KeyError):
        stages.affiliate_one(conn, AppConfig(), 999, pid, text, client=StubLLM([AFF_JSON]))


def test_affiliate_one_download_failure(conn):
    db.seed_prompt(conn, "affiliations", "x")
    pid, text = db.get_prompt(conn, "affiliations")
    paper_id = _insert_paper(conn)

    def failing(arxiv_id, url):
        raise RuntimeError("boom")

    result = stages.affiliate_one(conn, AppConfig(), paper_id, pid, text,
                                  client=StubLLM([AFF_JSON]), download_fn=failing)
    assert result["status"] == "unresolved"
    status = conn.execute("SELECT status FROM papers WHERE id = ?", (paper_id,)).fetchone()["status"]
    assert status == "unresolved"


def test_affiliate_one_withdrawn(conn):
    db.seed_prompt(conn, "affiliations", "x")
    pid, text = db.get_prompt(conn, "affiliations")
    paper_id = _insert_paper(conn)

    def withdrawn(arxiv_id, url):
        raise pdf.PDFNotFoundError("HTTP 404")

    result = stages.affiliate_one(conn, AppConfig(), paper_id, pid, text,
                                  client=StubLLM([AFF_JSON]), download_fn=withdrawn)
    assert result["status"] == "withdrawn"
    status = conn.execute("SELECT status FROM papers WHERE id = ?", (paper_id,)).fetchone()["status"]
    assert status == "withdrawn"


def test_screen_one_include(conn):
    db.seed_prompt(conn, "screen", "{{title}} {{abstract}} {{categories}} {{extra}}")
    pid, text = db.get_prompt(conn, "screen")
    paper_id = _insert_paper(conn, status="affiliated")
    result = stages.screen_one(conn, AppConfig(), paper_id, pid, text,
                               client=StubLLM([SCREEN_INCLUDE]))
    assert result["status"] == "screened_included"
    assert result["escalated"] is False
    row = conn.execute("SELECT status, category FROM papers WHERE id = ?", (paper_id,)).fetchone()
    assert row["status"] == "screened_included"
    assert row["category"] == "alignment"


def test_screen_one_no_escalation_auto_excludes(conn, tmp_path, pdf_bytes, monkeypatch):
    monkeypatch.setenv("ARXIV_FINDER_DATA", str(tmp_path / "data"))
    db.seed_prompt(conn, "screen", "{{title}} {{abstract}} {{categories}} {{extra}}")
    pid, text = db.get_prompt(conn, "screen")
    paper_id = _insert_paper(conn, status="affiliated")
    cache = pdf.pdf_path("2504.99999")
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_bytes(pdf_bytes)
    stub = StubLLM([SCREEN_ESCALATE, SCREEN_FULLTEXT_INCLUDE])
    result = stages.screen_one(conn, AppConfig(), paper_id, pid, text, client=stub)
    assert result["status"] == "screened_excluded"
    assert result["escalated"] is False
    assert stub.call_count == 1
    row = conn.execute("SELECT status, category FROM papers WHERE id = ?", (paper_id,)).fetchone()
    assert row["status"] == "screened_excluded"
    assert row["category"] is None


def test_screen_one_llm_error(conn):
    db.seed_prompt(conn, "screen", "x {{title}} {{abstract}} {{categories}} {{extra}}")
    pid, text = db.get_prompt(conn, "screen")
    paper_id = _insert_paper(conn, status="affiliated")
    result = stages.screen_one(conn, AppConfig(), paper_id, pid, text,
                               client=StubLLM(["not json"]))
    assert result["status"] == "screen_error"
    status = conn.execute("SELECT status FROM papers WHERE id = ?", (paper_id,)).fetchone()["status"]
    assert status == "screen_error"


def _seed(conn):
    db.seed_config(conn, AppConfig().model_dump_json())
    db.seed_prompt(conn, "affiliations", "extraction prompt")
    db.seed_prompt(conn, "screen", "screen prompt")


def test_api_single_paper_endpoints(conn, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from arxiv_finder.web.app import create_app

    _seed(conn)
    monkeypatch.setenv("ARXIV_FINDER_DB", str(tmp_path / "test.db"))
    monkeypatch.setenv("ARXIV_FINDER_DATA", str(tmp_path / "data"))
    paper_id = _insert_paper(conn)

    def fake_affiliate(conn, cfg, pid, prompt_version_id, prompt_text, **kw):
        return {"status": "affiliated", "china_flag": 1, "detail": "ok",
                "likely_mainland_china": "yes", "method": "text"}

    def fake_screen(conn, cfg, pid, prompt_version_id, prompt_text, **kw):
        return {"status": "screened_included", "escalated": False}

    monkeypatch.setattr("arxiv_finder.stages.affiliate_one", fake_affiliate)
    monkeypatch.setattr("arxiv_finder.stages.screen_one", fake_screen)

    client = TestClient(create_app())

    r = client.post("/api/papers/999/affiliate")
    assert r.status_code == 404

    r = client.post(f"/api/papers/{paper_id}/affiliate")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and body["status"] == "affiliated"

    r = client.post(f"/api/papers/{paper_id}/screen")
    assert r.status_code == 200
    assert r.json()["status"] == "screened_included"
