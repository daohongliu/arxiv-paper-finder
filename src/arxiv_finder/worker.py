from __future__ import annotations

import contextlib
import json
import sqlite3
import time
import traceback
from datetime import datetime

from . import db, jobs, stages
from .config import AppConfig


class _Cancelled(Exception):
    pass


def run_worker(poll_sec: float = 2.0, once: bool = False) -> None:
    conn = db.connect()
    db.init_db(conn)
    while True:
        row = jobs.claim_next_job(conn)
        if row is None:
            if once:
                return
            time.sleep(poll_sec)
            continue
        _execute(conn, row)
        if once:
            return


def _execute(conn: sqlite3.Connection, row: sqlite3.Row) -> None:
    job_id = row["id"]
    params: dict = json.loads(row["params_json"])
    try:
        config_json, prompts = jobs.job_snapshot(conn, row)
        cfg = AppConfig.model_validate(config_json)
        result: dict

        def progress(done: int, total: int, current: str) -> None:
            jobs.update_progress(conn, job_id, done, total, current)
            jobs.append_log(conn, job_id, f"[{done}/{total}] {current}")

        should_stop = lambda: jobs.is_cancelled(conn, job_id)  # noqa: E731
        model_override = params.get("model")
        if model_override:
            cfg.models.extraction = model_override
            cfg.models.screen_cheap = model_override
            cfg.models.screen_strong = model_override
        kind = row["kind"]
        if kind == "pipeline":
            date_from = datetime.fromisoformat(params["date_from"])
            date_to = datetime.fromisoformat(params["date_to"])

            def phase_progress(label: str):
                def cb(done: int, total: int, current: str) -> None:
                    jobs.update_progress(conn, job_id, done, total, f"[{label}] {current}")
                    jobs.append_log(conn, job_id, f"[{label} {done}/{total}] {current}")

                return cb

            fetch_result = stages.run_fetch(
                conn, cfg, date_from, date_to, phase_progress("fetch")
            )
            if should_stop():
                raise _Cancelled()
            pid_aff, text_aff = prompts.get(
                "affiliations", db.get_prompt(conn, "affiliations")
            )
            aff_result = stages.run_affiliations(
                conn, cfg, pid_aff, text_aff,
                progress=phase_progress("affiliations"), should_stop=should_stop,
            )
            if should_stop():
                raise _Cancelled()
            pid_scr, text_scr = prompts.get("screen", db.get_prompt(conn, "screen"))
            screen_result = stages.run_screen(
                conn, cfg, pid_scr, text_scr,
                progress=phase_progress("screen"), should_stop=should_stop,
            )
            result = {"fetch": fetch_result, "affiliations": aff_result, "screen": screen_result}
        elif kind == "fetch":
            date_from = datetime.fromisoformat(params["date_from"])
            date_to = datetime.fromisoformat(params["date_to"])
            result = stages.run_fetch(conn, cfg, date_from, date_to, progress)
        elif kind == "affiliations":
            pid, text = prompts.get("affiliations", db.get_prompt(conn, "affiliations"))
            result = stages.run_affiliations(
                conn,
                cfg,
                pid,
                text,
                limit=params.get("limit"),
                retry_failed=params.get("retry", False),
                progress=progress,
                should_stop=should_stop,
            )
        elif kind == "screen":
            pid, text = prompts.get("screen", db.get_prompt(conn, "screen"))
            result = stages.run_screen(
                conn,
                cfg,
                pid,
                text,
                limit=params.get("limit"),
                retry_review=params.get("retry", False),
                progress=progress,
                should_stop=should_stop,
            )
        else:
            raise ValueError(f"unknown job kind {kind}")
        if jobs.is_cancelled(conn, job_id):
            jobs.append_log(conn, job_id, "cancelled by user")
        else:
            jobs.finish_job(conn, job_id, result)
    except _Cancelled:
        jobs.append_log(conn, job_id, "cancelled by user")
    except Exception as exc:
        traceback.print_exc()
        with contextlib.suppress(Exception):
            jobs.fail_job(conn, job_id, str(exc))
