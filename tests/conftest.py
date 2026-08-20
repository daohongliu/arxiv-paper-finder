from __future__ import annotations

import sqlite3

import pytest

from arxiv_finder import db


@pytest.fixture()
def conn(tmp_path) -> sqlite3.Connection:
    c = db.connect(tmp_path / "test.db")
    db.init_db(c)
    return c
