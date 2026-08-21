from __future__ import annotations

import json
import sqlite3

from . import db

JOB_KINDS = ("pipeline", "collect", "analyze", "fetch", "affiliations", "screen")
PROMPTS_BY_KIND = {
    "pipeline": ["affiliations", "screen"],
    "collect": [],
    "analyze": ["affiliations", "screen"],
    "fetch": [],
    "affiliations": ["affiliations"],
    "screen": ["screen"],
}
_LOG_LIMIT = 400


def enqueue_job(
    conn: sqlite3.Connection, kind: str, params: dict, config_version_id: int | None = None
) -> int:
    if kind not in JOB_KINDS:
        raise ValueError(f"unknown job kind: {kind}")
    if config_version_id is None:
        config_version_id, _ = db.current_config(conn)
    prompt_versions = {}
    for name in PROMPTS_BY_KIND[kind]:
        pid, _ = db.get_prompt(conn, name)
        prompt_versions[name] = pid
    cur = conn.execute(
        """INSERT INTO jobs (kind, params_json, config_version_id, prompts_json, status, created_at)
           VALUES (?, ?, ?, ?, 'queued', ?)""",
        (
            kind,
            json.dumps(params),
            config_version_id,
            json.dumps(prompt_versions),
            db.now_iso(),
        ),
    )
    conn.commit()
    return int(cur.lastrowid or 0)


def claim_next_job(conn: sqlite3.Connection) -> sqlite3.Row | None:
    row = conn.execute(
        "SELECT * FROM jobs WHERE status = 'queued' ORDER BY id LIMIT 1"
    ).fetchone()
    if row is None:
        return None
    cur = conn.execute(
        "UPDATE jobs SET status = 'running', started_at = ? WHERE id = ? AND status = 'queued'",
        (db.now_iso(), row["id"]),
    )
    conn.commit()
    if cur.rowcount == 0:
        return None
    return conn.execute("SELECT * FROM jobs WHERE id = ?", (row["id"],)).fetchone()


def update_progress(
    conn: sqlite3.Connection,
    job_id: int,
    done: int,
    total: int,
    current: str,
    extra: dict | None = None,
) -> None:
    existing = get_progress(conn, job_id)
    payload: dict = {"done": done, "total": total, "current": current}
    if existing:
        if "phase" in existing:
            payload["phase"] = existing["phase"]
        for k in ("fetch_units", "param_sig"):
            if k in existing:
                payload[k] = existing[k]
    if extra:
        payload.update(extra)
    conn.execute(
        "UPDATE jobs SET progress_json = ? WHERE id = ?",
        (json.dumps(payload), job_id),
    )
    conn.commit()


def get_progress(conn: sqlite3.Connection, job_id: int) -> dict:
    row = conn.execute("SELECT progress_json FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if row and row["progress_json"]:
        try:
            return json.loads(row["progress_json"])
        except json.JSONDecodeError:
            return {}
    return {}


def append_log(conn: sqlite3.Connection, job_id: int, line: str) -> None:
    row = conn.execute("SELECT log_tail FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if row is None:
        return
    lines = (row["log_tail"] or "").splitlines()
    lines.append(f"{db.now_iso()} {line}")
    conn.execute(
        "UPDATE jobs SET log_tail = ? WHERE id = ?",
        ("\n".join(lines[-_LOG_LIMIT:]), job_id),
    )
    conn.commit()


def finish_job(conn: sqlite3.Connection, job_id: int, result: dict) -> None:
    append_log(conn, job_id, f"done: {json.dumps(result)}")
    conn.execute(
        "UPDATE jobs SET status = 'done', finished_at = ? WHERE id = ?",
        (db.now_iso(), job_id),
    )
    conn.commit()


def fail_job(conn: sqlite3.Connection, job_id: int, error: str) -> None:
    append_log(conn, job_id, f"failed: {error}")
    conn.execute(
        "UPDATE jobs SET status = 'failed', finished_at = ?, error = ? WHERE id = ?",
        (db.now_iso(), error[:2000], job_id),
    )
    conn.commit()


def cancel_job(conn: sqlite3.Connection, job_id: int) -> bool:
    cur = conn.execute(
        "UPDATE jobs SET status = 'cancelled', finished_at = ? "
        "WHERE id = ? AND status IN ('queued', 'running', 'paused')",
        (db.now_iso(), job_id),
    )
    conn.commit()
    return cur.rowcount > 0


def pause_job(conn: sqlite3.Connection, job_id: int) -> bool:
    cur = conn.execute(
        "UPDATE jobs SET status = 'paused' WHERE id = ? AND status IN ('queued', 'running')",
        (job_id,),
    )
    conn.commit()
    return cur.rowcount > 0


def resume_job(conn: sqlite3.Connection, job_id: int) -> bool:
    cur = conn.execute(
        "UPDATE jobs SET status = 'queued', finished_at = NULL, error = NULL "
        "WHERE id = ? AND status IN ('paused', 'failed', 'cancelled', 'running')",
        (job_id,),
    )
    conn.commit()
    return cur.rowcount > 0


def halt_status(conn: sqlite3.Connection, job_id: int) -> str | None:
    row = conn.execute("SELECT status FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if row is None:
        return "cancelled"
    return row["status"] if row["status"] in ("cancelled", "paused") else None


def set_phase(conn: sqlite3.Connection, job_id: int, phase: str) -> None:
    row = conn.execute("SELECT progress_json FROM jobs WHERE id = ?", (job_id,)).fetchone()
    p = json.loads(row["progress_json"]) if row and row["progress_json"] else {}
    p["phase"] = phase
    conn.execute(
        "UPDATE jobs SET progress_json = ? WHERE id = ?", (json.dumps(p), job_id)
    )
    conn.commit()


def get_phase(conn: sqlite3.Connection, job_id: int) -> str | None:
    row = conn.execute("SELECT progress_json FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if row and row["progress_json"]:
        return json.loads(row["progress_json"]).get("phase")
    return None


def is_cancelled(conn: sqlite3.Connection, job_id: int) -> bool:
    row = conn.execute("SELECT status FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return row is None or row["status"] == "cancelled"


def job_snapshot(conn: sqlite3.Connection, row: sqlite3.Row) -> tuple[dict, dict]:
    cfg_row = conn.execute(
        "SELECT config_json FROM config_versions WHERE id = ?", (row["config_version_id"],)
    ).fetchone()
    config = json.loads(cfg_row["config_json"])
    prompts: dict[str, tuple[int, str]] = {}
    for name, pid in json.loads(row["prompts_json"] or "{}").items():
        p = conn.execute("SELECT text FROM prompt_versions WHERE id = ?", (pid,)).fetchone()
        if p:
            prompts[name] = (pid, p["text"])
    return config, prompts
