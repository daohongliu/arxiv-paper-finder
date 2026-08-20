from __future__ import annotations

import json

from fastapi.testclient import TestClient

from arxiv_finder import db, jobs
from arxiv_finder.web.app import create_app


def _seed(conn):
    from arxiv_finder.config import AppConfig

    db.seed_config(conn, AppConfig().model_dump_json())
    db.seed_prompt(conn, "affiliations", "extraction prompt")
    db.seed_prompt(conn, "screen", "screen prompt")


def test_job_lifecycle(conn):
    _seed(conn)
    job_id = jobs.enqueue_job(conn, "fetch", {"date_from": "2025-04-01T00:00:00",
                                              "date_to": "2025-04-30T00:00:00"})
    row = jobs.claim_next_job(conn)
    assert row is not None and row["id"] == job_id and row["status"] == "running"
    assert jobs.claim_next_job(conn) is None
    jobs.update_progress(conn, job_id, 3, 10, "slice")
    jobs.append_log(conn, job_id, "hello")
    jobs.finish_job(conn, job_id, {"ok": 1})
    final = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    assert final["status"] == "done"
    assert json.loads(final["progress_json"])["done"] == 3
    assert "hello" in final["log_tail"]


def test_job_snapshot(conn):
    _seed(conn)
    job_id = jobs.enqueue_job(conn, "screen", {})
    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    config, prompts = jobs.job_snapshot(conn, row)
    assert config["search"]["page_size"] == 200
    assert prompts["screen"][1] == "screen prompt"


def test_cancel(conn):
    _seed(conn)
    job_id = jobs.enqueue_job(conn, "fetch", {"date_from": "a", "date_to": "b"})
    assert jobs.cancel_job(conn, job_id)
    assert jobs.claim_next_job(conn) is None
    assert not jobs.cancel_job(conn, job_id)


def test_api_flow(conn, tmp_path, monkeypatch):
    _seed(conn)
    monkeypatch.setenv("ARXIV_FINDER_DB", str(tmp_path / "test.db"))

    app = create_app()
    client = TestClient(app)

    r = client.get("/api/health")
    assert r.json()["ok"]

    r = client.get("/api/config")
    assert r.status_code == 200
    assert r.json()["config"]["search"]["page_size"] == 200

    cfg = r.json()["config"]
    cfg["china_filter"]["min_count"] = 2
    r = client.put("/api/config", json={"config": cfg, "note": "test"})
    assert r.status_code == 200
    r = client.get("/api/config")
    assert r.json()["config"]["china_filter"]["min_count"] == 2
    assert r.json()["version_id"] == 2

    bad = dict(cfg)
    bad["screen"] = {**cfg["screen"], "escalate_below": 0.1, "review_below": 0.9}
    r = client.put("/api/config", json={"config": bad})
    assert r.status_code == 422

    versions = client.get("/api/config/versions").json()["items"]
    assert len(versions) == 2

    r = client.post("/api/config/rollback/1")
    assert r.status_code == 200
    assert client.get("/api/config").json()["config"]["china_filter"]["min_count"] == 1

    r = client.get("/api/prompts")
    items = r.json()["items"]
    assert {p["name"] for p in items} == {"affiliations", "screen"}

    r = client.put("/api/prompts/screen", json={"text": "new screen prompt"})
    assert r.status_code == 200
    prompts = client.get("/api/prompts").json()["items"]
    screen = next(p for p in prompts if p["name"] == "screen")
    assert screen["text"] == "new screen prompt"
    assert screen["version"] == 2

    r = client.post("/api/jobs", json={"kind": "bad"})
    assert r.status_code == 422
    r = client.post(
        "/api/jobs",
        json={"kind": "fetch", "params": {"date_from": "2025-05-01", "date_to": "2025-04-01"}},
    )
    assert r.status_code == 400
    r = client.post(
        "/api/jobs",
        json={"kind": "fetch", "params": {"date_from": "2025-04-01", "date_to": "2025-04-30"}},
    )
    assert r.status_code == 201
    job_id = r.json()["job_id"]
    r = client.get(f"/api/jobs/{job_id}")
    assert r.json()["status"] == "queued"
    assert client.post(f"/api/jobs/{job_id}/cancel").json()["ok"]

    conn.execute(
        """INSERT INTO papers (arxiv_id, title, abstract, authors_json, categories_json,
           submitted, updated, abs_url, pdf_url, queries_json, status, category,
           subcategory, confidence)
           VALUES ('2504.99999', 'Safety Paper', 'abs', '["A"]', '["cs.AI"]',
                   '2025-04-10T00:00:00Z', '', 'u', 'p', '["safety_phrases"]',
                   'screened_included', 'alignment', NULL, 0.93)"""
    )
    conn.commit()

    r = client.get("/api/papers", params={"status": "screened_included"})
    assert r.json()["total"] == 1
    item = r.json()["items"][0]
    paper_id = item["id"]

    r = client.get(f"/api/papers/{paper_id}")
    assert r.json()["title"] == "Safety Paper"
    assert r.json()["affiliations"] is None

    r = client.post(
        f"/api/papers/{paper_id}/review",
        json={"included": True, "category": "robustness", "subcategory": None, "note": "fix"},
    )
    assert r.json()["status"] == "screened_included"
    row = conn.execute("SELECT category FROM papers WHERE id = ?", (paper_id,)).fetchone()
    assert row["category"] == "robustness"

    r = client.post(f"/api/papers/{paper_id}/review", json={"included": True})
    assert r.status_code == 400

    stats = client.get("/api/stats").json()
    assert stats["papers_total"] == 1
    assert stats["by_status"]["screened_included"] == 1


def test_api_gt_import(conn, tmp_path, monkeypatch):
    _seed(conn)
    monkeypatch.setenv("ARXIV_FINDER_DB", str(tmp_path / "test.db"))
    conn.execute(
        """INSERT INTO papers (arxiv_id, title, abstract, authors_json, categories_json,
           submitted, updated, abs_url, pdf_url, queries_json, status, category)
           VALUES ('2504.00042', 'GT Paper', 'abs', '[]', '[]', '', '', '', '', '[]',
                   'screened_included', 'alignment')"""
    )
    conn.commit()
    app = create_app()
    client = TestClient(app)
    csv_content = "arxiv_id,category\n2504.00042,Alignment\n2504.00043,Robustness\n"
    r = client.post(
        "/api/labels/import",
        files={"file": ("gt.csv", csv_content.encode(), "text/csv")},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total_gt"] == 2
    assert body["included"] == 1
    assert body["recovery"] == 0.5
