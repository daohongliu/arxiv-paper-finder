from __future__ import annotations

from fastapi.testclient import TestClient

from arxiv_finder import db
from arxiv_finder.config import AppConfig
from arxiv_finder.web.app import create_app


def _seed(conn):
    db.seed_config(conn, AppConfig().model_dump_json())
    db.seed_prompt(conn, "affiliations", "extraction prompt")
    db.seed_prompt(conn, "screen", "screen prompt")


def _insert(conn, arxiv_id, status, category=None):
    conn.execute(
        """INSERT INTO papers (arxiv_id, title, abstract, authors_json, categories_json,
           submitted, updated, abs_url, pdf_url, queries_json, status, category)
           VALUES (?, 't', 'a', '[]', '["cs.AI"]', '2025-04-01T00:00:00Z', '', 'u', 'p',
                   '[]', ?, ?)""",
        (arxiv_id, status, category),
    )
    conn.commit()


def test_import_persists_and_filters(conn, tmp_path, monkeypatch):
    _seed(conn)
    monkeypatch.setenv("ARXIV_FINDER_DB", str(tmp_path / "test.db"))
    monkeypatch.setenv("ARXIV_FINDER_DATA", str(tmp_path / "data"))

    # one in GT + included, one in GT but excluded, one not in GT but included
    _insert(conn, "2504.00001", "screened_included", "alignment")
    _insert(conn, "2504.00002", "screened_excluded", None)
    _insert(conn, "2504.00003", "screened_included", "robustness")

    client = TestClient(create_app())
    csv_content = "arxiv_id,category\n2504.00001,Alignment\n2504.00002,Robustness\n"
    r = client.post(
        "/api/labels/import", files={"file": ("gt.csv", csv_content.encode(), "text/csv")}
    )
    assert r.status_code == 200
    assert r.json()["gt_rows_imported"] == 2
    assert conn.execute("SELECT COUNT(*) AS n FROM ground_truth").fetchone()["n"] == 2

    # in GT
    r = client.get("/api/papers", params={"gt": "true"})
    body = r.json()
    assert body["total"] == 2
    assert {i["arxiv_id"] for i in body["items"]} == {"2504.00001", "2504.00002"}
    assert all(i["in_gt"] for i in body["items"])

    # in GT + included
    r = client.get("/api/papers", params={"gt": "true", "included": "true"})
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["arxiv_id"] == "2504.00001"
    assert body["items"][0]["gt_category"] == "alignment"

    # in GT + not included
    r = client.get("/api/papers", params={"gt": "true", "included": "false"})
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["arxiv_id"] == "2504.00002"

    # not in GT
    r = client.get("/api/papers", params={"gt": "false"})
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["arxiv_id"] == "2504.00003"
    assert body["items"][0]["in_gt"] is False

    # not in GT + included
    r = client.get("/api/papers", params={"gt": "false", "included": "true"})
    assert r.json()["total"] == 1
    assert r.json()["items"][0]["arxiv_id"] == "2504.00003"

    # stats matrix
    gt = client.get("/api/stats").json()["ground_truth"]
    assert gt["total"] == 2
    assert gt["matrix"] == {
        "in_gt_included": 1,
        "in_gt_not_included": 1,
        "not_in_gt_included": 1,
        "not_in_gt_not_included": 0,
    }


def test_paper_detail_gt_fields(conn, tmp_path, monkeypatch):
    _seed(conn)
    monkeypatch.setenv("ARXIV_FINDER_DB", str(tmp_path / "test.db"))
    monkeypatch.setenv("ARXIV_FINDER_DATA", str(tmp_path / "data"))
    _insert(conn, "2504.00001", "screened_included", "alignment")
    conn.execute(
        """INSERT INTO ground_truth (arxiv_id, category, subcategory, imported_at)
           VALUES ('2504.00001', 'monitoring', 'evaluations', '2025-04-01T00:00:00Z')"""
    )
    conn.commit()

    paper_id = conn.execute(
        "SELECT id FROM papers WHERE arxiv_id = '2504.00001'"
    ).fetchone()["id"]
    client = TestClient(create_app())
    d = client.get(f"/api/papers/{paper_id}").json()
    assert d["in_gt"] is True
    assert d["gt_category"] == "monitoring"
    assert d["gt_subcategory"] == "evaluations"
