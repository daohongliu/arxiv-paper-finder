from __future__ import annotations

import json
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

SCHEMA = """
CREATE TABLE IF NOT EXISTS papers (
  id INTEGER PRIMARY KEY,
  arxiv_id TEXT NOT NULL UNIQUE,
  version INTEGER NOT NULL DEFAULT 1,
  title TEXT NOT NULL,
  abstract TEXT NOT NULL,
  authors_json TEXT NOT NULL,
  primary_category TEXT,
  categories_json TEXT NOT NULL,
  submitted TEXT NOT NULL,
  updated TEXT NOT NULL,
  abs_url TEXT NOT NULL,
  pdf_url TEXT NOT NULL,
  comments TEXT,
  queries_json TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'fetched',
  china_flag INTEGER NOT NULL DEFAULT 0,
  category TEXT,
  subcategory TEXT,
  confidence REAL,
  rationale TEXT
);
CREATE INDEX IF NOT EXISTS idx_papers_status ON papers(status);
CREATE INDEX IF NOT EXISTS idx_papers_submitted ON papers(submitted);

CREATE TABLE IF NOT EXISTS affiliations (
  id INTEGER PRIMARY KEY,
  paper_id INTEGER NOT NULL UNIQUE REFERENCES papers(id),
  prompt_version_id INTEGER,
  model TEXT NOT NULL,
  method TEXT NOT NULL,
  status TEXT NOT NULL,
  authors_json TEXT NOT NULL,
  error TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS config_versions (
  id INTEGER PRIMARY KEY,
  created_at TEXT NOT NULL,
  config_json TEXT NOT NULL,
  note TEXT
);

CREATE TABLE IF NOT EXISTS prompt_versions (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  version INTEGER NOT NULL,
  text TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(name, version)
);

CREATE TABLE IF NOT EXISTS llm_calls (
  id INTEGER PRIMARY KEY,
  paper_id INTEGER,
  stage TEXT NOT NULL,
  model TEXT NOT NULL,
  prompt_version_id INTEGER,
  request_summary TEXT,
  response_text TEXT NOT NULL,
  input_tokens INTEGER,
  output_tokens INTEGER,
  latency_ms INTEGER,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS labels (
  id INTEGER PRIMARY KEY,
  paper_id INTEGER NOT NULL,
  arxiv_id TEXT NOT NULL,
  source TEXT NOT NULL,
  included INTEGER NOT NULL,
  category TEXT,
  subcategory TEXT,
  note TEXT,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_labels_arxiv_id ON labels(arxiv_id);

CREATE TABLE IF NOT EXISTS jobs (
  id INTEGER PRIMARY KEY,
  kind TEXT NOT NULL,
  params_json TEXT NOT NULL,
  config_version_id INTEGER,
  prompts_json TEXT,
  status TEXT NOT NULL DEFAULT 'queued',
  progress_json TEXT,
  log_tail TEXT,
  created_at TEXT NOT NULL,
  started_at TEXT,
  finished_at TEXT,
  error TEXT
);
"""


def data_dir() -> Path:
    d = Path(os.environ.get("ARXIV_FINDER_DATA", "data"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def db_path() -> Path:
    return Path(os.environ.get("ARXIV_FINDER_DB", str(data_dir() / "finder.db")))


def pdf_cache_dir() -> Path:
    d = data_dir() / "pdfs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def connect(path: Path | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(path or db_path(), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def seed_config(conn: sqlite3.Connection, config_json: str, note: str = "seed") -> int:
    row = conn.execute("SELECT COUNT(*) AS n FROM config_versions").fetchone()
    if row and row["n"] > 0:
        raise RuntimeError("config already seeded")
    cur = conn.execute(
        "INSERT INTO config_versions (created_at, config_json, note) VALUES (?, ?, ?)",
        (now_iso(), config_json, note),
    )
    conn.commit()
    return int(cur.lastrowid or 0)


def current_config(conn: sqlite3.Connection) -> tuple[int, dict]:
    row = conn.execute(
        "SELECT id, config_json FROM config_versions ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if row is None:
        raise RuntimeError("no config in database; run `arxiv-finder init`")
    return int(row["id"]), json.loads(row["config_json"])


def seed_prompt(conn: sqlite3.Connection, name: str, text: str) -> int:
    row = conn.execute(
        "SELECT MAX(version) AS v FROM prompt_versions WHERE name = ?", (name,)
    ).fetchone()
    version = (row["v"] or 0) + 1 if row and row["v"] else 1
    cur = conn.execute(
        "INSERT INTO prompt_versions (name, version, text, created_at) VALUES (?, ?, ?, ?)",
        (name, version, text, now_iso()),
    )
    conn.commit()
    return int(cur.lastrowid or 0)


def get_prompt(conn: sqlite3.Connection, name: str) -> tuple[int, str]:
    row = conn.execute(
        "SELECT id, text FROM prompt_versions WHERE name = ? ORDER BY version DESC LIMIT 1",
        (name,),
    ).fetchone()
    if row is None:
        raise RuntimeError(f"prompt {name!r} not found; run `arxiv-finder init`")
    return int(row["id"]), row["text"]
