from __future__ import annotations

import csv
import io
import json

from fastapi.testclient import TestClient

from arxiv_finder import db
from arxiv_finder.config import AppConfig
from arxiv_finder.export import TARGET_COLUMNS, direction_label, export_dataset_target
from arxiv_finder.web.app import create_app

EXPECTED_HEADER = [
    "Reviewed", "Title", "Title URL", "Research direction", "Date",
    "Institution 1", "Institution 2", "Other institutions",
    "Anchor author 1", "Anchor author 2", "Anchor author 3",
    "Anchor author 4", "Anchor author 5",
]


def _insert_paper(conn, arxiv_id: str, status: str, submitted: str,
                  category=None, subcategory=None, authors=None) -> int:
    cur = conn.execute(
        """INSERT INTO papers (arxiv_id, title, abstract, authors_json, categories_json,
           submitted, updated, abs_url, pdf_url, queries_json, status, category, subcategory)
           VALUES (?, ?, 'abs', ?, '["cs.AI"]', ?, '', ?, '', '[]', ?, ?, ?)""",
        (
            arxiv_id, f"title {arxiv_id}", json.dumps(authors or ["A One", "B Two"]),
            submitted, f"https://arxiv.org/abs/{arxiv_id}", status, category, subcategory,
        ),
    )
    return int(cur.lastrowid or 0)


def _insert_affiliations(conn, paper_id: int, entries: list[dict]) -> None:
    conn.execute(
        """INSERT INTO affiliations (paper_id, model, method, status, authors_json, created_at)
           VALUES (?, 'm', 'text', 'ok', ?, ?)""",
        (paper_id, json.dumps(entries), db.now_iso()),
    )


def test_target_columns_match_user_format():
    assert TARGET_COLUMNS == EXPECTED_HEADER


def test_direction_label_mapping():
    assert direction_label("alignment", None) == "Alignment"
    assert direction_label("robustness", None) == "Robustness"
    assert direction_label("systemic_safety", None) == "Systemic Safety"
    assert direction_label("monitoring", "evaluations") == "Monitoring (evaluations)"
    assert direction_label("monitoring", "interpretability") == "Monitoring (interpretability)"
    assert direction_label("monitoring", None) == "Monitoring (other)"
    assert direction_label("survey", None) == "Survey or Position Paper"


def test_export_target_rows(conn):
    pid = _insert_paper(
        conn, "2504.00001", "screened_included", "2025-04-01T05:58:14Z",
        category="monitoring", subcategory="evaluations",
        authors=["A One", "B Two", "C Three", "D Four", "E Five", "F Six", "G Seven"],
    )
    _insert_affiliations(conn, pid, [
        {"name": "A One", "institution": "Tsinghua University", "mainland_china": "yes"},
        {"name": "B Two", "institution": "Peking University", "mainland_china": "yes"},
        {"name": "C Three", "institution": "MIT", "mainland_china": "no"},
        {"name": "D Four", "institution": "Tsinghua University", "mainland_china": "yes"},
    ])
    _insert_paper(conn, "2504.00002", "screened_excluded", "2025-04-02T00:00:00Z")
    _insert_paper(conn, "2504.00003", "screened_included", "2025-05-10T00:00:00Z",
                  category="survey")
    conn.commit()

    buf = io.StringIO()
    n = export_dataset_target(conn, buf)
    assert n == 2
    rows = list(csv.reader(io.StringIO(buf.getvalue())))
    assert rows[0] == EXPECTED_HEADER
    r = rows[1]
    assert r[0] == ""
    assert r[1] == "title 2504.00001"
    assert r[2] == "https://arxiv.org/abs/2504.00001"
    assert r[3] == "Monitoring (evaluations)"
    assert r[4] == "2025-04-01 00:00:00"
    assert r[5] == "Tsinghua University"
    assert r[6] == "Peking University"
    assert r[7] == "MIT"
    assert r[8:13] == ["C Three", "D Four", "E Five", "F Six", "G Seven"]
    assert rows[2][3] == "Survey or Position Paper"


def test_export_target_date_filter(conn):
    _insert_paper(conn, "2504.00001", "screened_included", "2025-04-01T00:00:00Z",
                  category="alignment")
    _insert_paper(conn, "2504.00002", "screened_included", "2025-06-15T00:00:00Z",
                  category="alignment")
    conn.commit()
    buf = io.StringIO()
    n = export_dataset_target(conn, buf, date_from="2025-05-01", date_to="2025-07-01")
    assert n == 1
    rows = list(csv.reader(io.StringIO(buf.getvalue())))
    assert rows[1][1] == "title 2504.00002"


def test_api_bulk_review_and_export(conn, tmp_path, monkeypatch):
    monkeypatch.setenv("ARXIV_FINDER_DB", str(tmp_path / "test.db"))
    db.seed_config(conn, AppConfig().model_dump_json())
    db.seed_prompt(conn, "affiliations", "x")
    db.seed_prompt(conn, "screen", "x")
    p1 = _insert_paper(conn, "2504.10001", "needs_review", "2025-04-01T00:00:00Z")
    p2 = _insert_paper(conn, "2504.10002", "affiliated", "2025-04-02T00:00:00Z")
    p3 = _insert_paper(conn, "2504.10003", "fetched", "2025-04-03T00:00:00Z")
    conn.commit()

    client = TestClient(create_app())

    r = client.post("/api/papers/bulk-review", json={"ids": [p1, p2], "included": True,
                                                     "category": "alignment"})
    assert r.status_code == 200 and r.json()["updated"] == 2
    statuses = {row["arxiv_id"]: row["status"]
                for row in conn.execute("SELECT arxiv_id, status FROM papers")}
    assert statuses["2504.10001"] == "screened_included"
    assert statuses["2504.10002"] == "screened_included"
    assert statuses["2504.10003"] == "fetched"
    labels = conn.execute("SELECT COUNT(*) AS n FROM labels WHERE source = 'manual'").fetchone()
    assert labels["n"] == 2

    r = client.post("/api/papers/bulk-review", json={"ids": [p3], "included": True,
                                                     "category": "ethics"})
    assert r.status_code == 400

    r = client.post("/api/papers/bulk-review", json={"ids": [p3], "included": False})
    assert r.status_code == 200
    assert conn.execute("SELECT status FROM papers WHERE id = ?", (p3,)).fetchone()[0] == \
        "screened_excluded"

    r = client.get("/api/export", params={"date_from": "2025-04-01", "date_to": "2025-04-30"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert r.headers["x-exported-rows"] == "2"
    lines = r.text.splitlines()
    assert lines[0] == ",".join(EXPECTED_HEADER)
    assert len(lines) == 3

    r = client.get("/api/export", params={"date_from": "2026-01-01"})
    assert r.headers["x-exported-rows"] == "0"
