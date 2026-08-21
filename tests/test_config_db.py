from __future__ import annotations

import json

import pytest

from arxiv_finder import db, stages
from arxiv_finder.config import AppConfig


def test_default_config_valid():
    cfg = AppConfig()
    assert len(cfg.search.clauses) == 52
    names = [c.name for c in cfg.search.clauses]
    assert "safety_phrases" in names


def test_config_rejects_duplicate_clauses():
    raw = AppConfig().model_dump()
    raw["search"]["clauses"].append(raw["search"]["clauses"][0])
    with pytest.raises(ValueError):
        AppConfig.model_validate(raw)


def test_config_rejects_bad_thresholds():
    raw = AppConfig().model_dump()
    raw["screen"]["review_below"] = 0.9
    raw["screen"]["escalate_below"] = 0.6
    with pytest.raises(ValueError):
        AppConfig.model_validate(raw)


def test_config_roundtrip_json():
    cfg = AppConfig()
    loaded = AppConfig.model_validate_json(cfg.model_dump_json())
    assert loaded == cfg


def test_seed_and_current_config(conn):
    cfg = AppConfig()
    db.seed_config(conn, cfg.model_dump_json())
    version_id, raw = db.current_config(conn)
    assert version_id == 1
    assert raw["search"]["page_size"] == 250
    with pytest.raises(RuntimeError):
        db.seed_config(conn, cfg.model_dump_json())


def test_prompt_versioning(conn):
    db.seed_prompt(conn, "screen", "v1 text")
    pid, text = db.get_prompt(conn, "screen")
    assert text == "v1 text"
    db.seed_prompt(conn, "screen", "v2 text")
    pid2, text2 = db.get_prompt(conn, "screen")
    assert text2 == "v2 text"
    assert pid2 != pid


PAPER = {
    "arxiv_id": "2504.00001",
    "version": 1,
    "title": "Test Paper",
    "abstract": "An abstract",
    "authors_json": ["Wei Zhang", "Li Liu"],
    "primary_category": "cs.AI",
    "categories": ["cs.AI"],
    "submitted": "2025-04-01T00:00:00Z",
    "updated": "2025-04-01T00:00:00Z",
    "abs_url": "https://arxiv.org/abs/2504.00001v1",
    "pdf_url": "https://arxiv.org/pdf/2504.00001v1",
    "queries": ["safety_phrases"],
}


def test_init_db_migrates_likely_mainland_column(tmp_path):
    c = db.connect(tmp_path / "legacy.db")
    c.executescript(
        """CREATE TABLE affiliations (
             id INTEGER PRIMARY KEY,
             paper_id INTEGER NOT NULL UNIQUE,
             prompt_version_id INTEGER,
             model TEXT NOT NULL,
             method TEXT NOT NULL,
             status TEXT NOT NULL,
             authors_json TEXT NOT NULL,
             error TEXT,
             created_at TEXT NOT NULL
           );"""
    )
    c.commit()
    db.init_db(c)
    cols = {r["name"] for r in c.execute("PRAGMA table_info(affiliations)")}
    assert "likely_mainland_china" in cols


def test_store_papers_insert_and_merge(conn):
    res = stages.store_papers(conn, [PAPER])
    assert res["added"] == 1
    assert res["name_filtered"] == 0
    assert conn.execute("SELECT status FROM papers").fetchone()[0] == "fetched"
    again = dict(PAPER)
    again["queries"] = ["robustness_ai"]
    res2 = stages.store_papers(conn, [again])
    assert res2["added"] == 0
    row = conn.execute("SELECT queries_json, version FROM papers").fetchone()
    assert set(json.loads(row["queries_json"])) == {"safety_phrases", "robustness_ai"}
    newer = dict(PAPER, version=2, title="Test Paper v2")
    stages.store_papers(conn, [newer])
    row = conn.execute("SELECT title, version FROM papers").fetchone()
    assert row["title"] == "Test Paper v2"
    assert row["version"] == 2


def test_store_papers_name_filter(conn):
    western = dict(PAPER, arxiv_id="2504.00002", authors_json=["John Smith", "Anna Novak"])
    res = stages.store_papers(conn, [western])
    assert res["added"] == 1
    assert res["name_filtered"] == 1
    assert conn.execute(
        "SELECT status FROM papers WHERE arxiv_id='2504.00002'"
    ).fetchone()[0] == "filtered_out"
