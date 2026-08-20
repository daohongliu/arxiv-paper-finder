from __future__ import annotations

from fastapi.testclient import TestClient

from arxiv_finder import db, pdf
from arxiv_finder.config import AppConfig
from arxiv_finder.web.app import create_app


def _seed(conn):
    db.seed_config(conn, AppConfig().model_dump_json())
    db.seed_prompt(conn, "affiliations", "x")
    db.seed_prompt(conn, "screen", "x")


def _paper(conn, arxiv_id: str) -> int:
    cur = conn.execute(
        """INSERT INTO papers (arxiv_id, title, abstract, authors_json, categories_json,
           submitted, updated, abs_url, pdf_url, queries_json, status)
           VALUES (?, ?, 'abs', '["A"]', '["cs.AI"]', '2025-04-01T00:00:00Z', '', '', '', '[]',
                   'affiliated')""",
        (arxiv_id, f"title {arxiv_id}"),
    )
    return int(cur.lastrowid or 0)


def test_pdf_cached_flag_and_delete(conn, tmp_path, monkeypatch):
    monkeypatch.setenv("ARXIV_FINDER_DATA", str(tmp_path))
    monkeypatch.setenv("ARXIV_FINDER_DB", str(tmp_path / "test.db"))
    _seed(conn)
    pid = _paper(conn, "2504.00001")
    conn.execute(
        "INSERT INTO affiliations (paper_id, model, method, status, authors_json, created_at) "
        "VALUES (?, 'm', 'text', 'ok', '[]', ?)",
        (pid, db.now_iso()),
    )
    conn.execute(
        "INSERT INTO labels (paper_id, arxiv_id, source, included, created_at) "
        "VALUES (?, '2504.00001', 'manual', 1, ?)",
        (pid, db.now_iso()),
    )
    conn.commit()
    path = pdf.pdf_path("2504.00001")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"%PDF-1.4 fake")

    client = TestClient(create_app())

    r = client.get("/api/papers")
    assert r.json()["items"][0]["pdf_cached"] is True

    r = client.get(f"/api/papers/{pid}")
    assert r.json()["pdf_cached"] is True

    r = client.delete(f"/api/papers/{pid}")
    assert r.status_code == 200 and r.json()["pdf_removed"] is True
    assert not path.exists()
    assert conn.execute("SELECT COUNT(*) AS n FROM papers").fetchone()["n"] == 0
    assert conn.execute("SELECT COUNT(*) AS n FROM affiliations").fetchone()["n"] == 0
    assert conn.execute("SELECT COUNT(*) AS n FROM labels").fetchone()["n"] == 0

    assert client.delete(f"/api/papers/{pid}").status_code == 404


def test_pdf_cached_false_and_delete_without_file(conn, tmp_path, monkeypatch):
    monkeypatch.setenv("ARXIV_FINDER_DATA", str(tmp_path))
    monkeypatch.setenv("ARXIV_FINDER_DB", str(tmp_path / "test.db"))
    _seed(conn)
    pid = _paper(conn, "2504.00002")
    conn.commit()

    client = TestClient(create_app())
    assert client.get("/api/papers").json()["items"][0]["pdf_cached"] is False
    r = client.delete(f"/api/papers/{pid}")
    assert r.status_code == 200 and r.json()["pdf_removed"] is False


def test_bulk_delete(conn, tmp_path, monkeypatch):
    monkeypatch.setenv("ARXIV_FINDER_DATA", str(tmp_path))
    monkeypatch.setenv("ARXIV_FINDER_DB", str(tmp_path / "test.db"))
    _seed(conn)
    p1 = _paper(conn, "2504.10001")
    p2 = _paper(conn, "2504.10002")
    conn.commit()
    for aid in ("2504.10001", "2504.10002"):
        path = pdf.pdf_path(aid)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"%PDF-1.4 fake")

    client = TestClient(create_app())
    r = client.post("/api/papers/bulk-delete", json={"ids": [p1, p2, 99999]})
    assert r.status_code == 200
    body = r.json()
    assert body["deleted"] == 2 and body["pdfs_removed"] == 2
    assert conn.execute("SELECT COUNT(*) AS n FROM papers").fetchone()["n"] == 0

    r = client.post("/api/papers/bulk-delete", json={"ids": []})
    assert r.status_code == 400
