from __future__ import annotations

import asyncio

import httpx
import pytest

from arxiv_finder import db
from arxiv_finder.config import AppConfig
from arxiv_finder.web.app import create_app


def _seed(conn):
    db.seed_config(conn, AppConfig().model_dump_json())
    db.seed_prompt(conn, "affiliations", "x")
    db.seed_prompt(conn, "screen", "x")
    for i in range(20):
        conn.execute(
            """INSERT INTO papers (arxiv_id, title, abstract, authors_json, categories_json,
               submitted, updated, abs_url, pdf_url, queries_json, status)
               VALUES (?, ?, 'abs', '[]', '["cs.AI"]', '2025-04-01T00:00:00Z',
                       '', '', '', '[]', 'fetched')""",
            (f"2504.{i:05d}", f"paper {i}"),
        )
    conn.commit()


@pytest.mark.anyio
async def test_concurrent_papers_requests(tmp_path, monkeypatch):
    monkeypatch.setenv("ARXIV_FINDER_DB", str(tmp_path / "c.db"))
    conn = db.connect()
    db.init_db(conn)
    _seed(conn)

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        results = await asyncio.gather(
            *(
                client.get("/api/papers", params={"status": "fetched", "page": 1, "page_size": 5})
                for _ in range(12)
            ),
            client.get("/api/stats"),
            client.get("/api/papers", params={"status": "unresolved", "page": 1, "page_size": 200}),
        )
    assert all(r.status_code == 200 for r in results), [r.status_code for r in results]
    assert results[0].json()["total"] == 20
