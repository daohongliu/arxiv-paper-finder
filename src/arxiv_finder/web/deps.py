from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from datetime import time as dtime

from fastapi import HTTPException

from .. import db
from ..config import AppConfig


def get_conn() -> sqlite3.Connection:
    conn = db.connect()
    db.init_db(conn)
    return conn


def parse_date_range(date_from: str, date_to: str) -> tuple[datetime, datetime]:
    try:
        df = datetime.combine(datetime.fromisoformat(date_from).date(), dtime.min)
        dt = datetime.combine(datetime.fromisoformat(date_to).date(), dtime.max)
    except ValueError as exc:
        raise HTTPException(400, f"invalid date: {exc}") from exc
    if df >= dt:
        raise HTTPException(400, "date_from must be before date_to")
    return df, dt


def row_to_dict(row: sqlite3.Row, extra: dict | None = None) -> dict:
    d = dict(row)
    if extra:
        d.update(extra)
    return d


def json_field(row: sqlite3.Row, key: str):
    try:
        return json.loads(row[key])
    except (KeyError, TypeError, json.JSONDecodeError):
        return None


def current_cfg(conn: sqlite3.Connection) -> tuple[int, AppConfig]:
    version_id, raw = db.current_config(conn)
    return version_id, AppConfig.model_validate(raw)
