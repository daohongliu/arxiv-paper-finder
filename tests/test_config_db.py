from __future__ import annotations

import json

import pytest

from arxiv_finder import db, stages
from arxiv_finder.config import AppConfig


def test_default_config_valid():
    cfg = AppConfig()
    assert len(cfg.search.clauses) == 7
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
    assert raw["search"]["page_size"] == 200
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
    "authors_json": ["A", "B"],
    "primary_category": "cs.AI",
    "categories": ["cs.AI"],
    "submitted": "2025-04-01T00:00:00Z",
    "updated": "2025-04-01T00:00:00Z",
    "abs_url": "https://arxiv.org/abs/2504.00001v1",
    "pdf_url": "https://arxiv.org/pdf/2504.00001v1",
    "queries": ["safety_phrases"],
}


def test_store_papers_insert_and_merge(conn):
    added = stages.store_papers(conn, [PAPER])
    assert added == 1
    again = dict(PAPER)
    again["queries"] = ["robustness_ai"]
    added2 = stages.store_papers(conn, [again])
    assert added2 == 0
    row = conn.execute("SELECT queries_json, version FROM papers").fetchone()
    assert set(json.loads(row["queries_json"])) == {"safety_phrases", "robustness_ai"}
    newer = dict(PAPER, version=2, title="Test Paper v2")
    stages.store_papers(conn, [newer])
    row = conn.execute("SELECT title, version FROM papers").fetchone()
    assert row["title"] == "Test Paper v2"
    assert row["version"] == 2
