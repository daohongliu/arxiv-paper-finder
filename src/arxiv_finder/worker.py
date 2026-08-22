from __future__ import annotations

import contextlib
import json
import sqlite3
import time
import traceback
from datetime import datetime

from . import db, jobs, stages
from .config import AppConfig


class _Halted(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


_KIND_LABELS = {
    "pipeline": "full pipeline (search → download → analyze)",
    "collect": "search + download",
    "analyze": "analysis (affiliations + screening)",
    "fetch": "search only",
    "affiliations": "affiliations",
    "screen": "screening",
}


def run_worker(poll_sec: float = 2.0, once: bool = False) -> None:
    conn = db.connect()
    db.init_db(conn)
    requeued = jobs.requeue_stale_running(conn)
    if requeued:
        print(f"requeued {requeued} job(s) left 'running' by a previous worker")
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
            jobs.append_log(conn, job_id, f"({done}/{total}) {current}")

        def phase_progress(label: str):
            def cb(done: int, total: int, current: str) -> None:
                jobs.update_progress(conn, job_id, done, total, f"[{label}] {current}")
                jobs.append_log(conn, job_id, f"({done}/{total}) {current}")

            return cb

        def should_stop() -> bool:
            return jobs.halt_status(conn, job_id) is not None

        def check_halt() -> None:
            reason = jobs.halt_status(conn, job_id)
            if reason:
                raise _Halted(reason)

        model_override = params.get("model")
        if model_override:
            cfg.models.extraction = model_override
            cfg.models.screen_cheap = model_override
            cfg.models.screen_strong = model_override
        kind = row["kind"]
        jobs.append_log(
            conn, job_id, f"Starting job: {_KIND_LABELS.get(kind, kind)}."
        )

        def run_collect(with_download: bool = True) -> dict:
            results: dict = {}
            phase = jobs.get_phase(conn, job_id)
            if phase in ("search_done", "download_done"):
                jobs.append_log(
                    conn, job_id, "Search already completed in a previous run; skipping."
                )
            else:
                date_from = datetime.fromisoformat(params["date_from"])
                date_to = datetime.fromisoformat(params["date_to"])
                from .fetch import month_slices

                months = month_slices(date_from, date_to)
                total_units = len(months) * len(cfg.search.clauses)
                jobs.append_log(
                    conn, job_id,
                    f"Searching arXiv: {len(cfg.search.clauses)} search terms across "
                    f"{len(months)} month(s).",
                )
                sig = f"{params['date_from']}|{params['date_to']}|{len(cfg.search.clauses)}"
                ckpt = jobs.get_progress(conn, job_id)
                start_unit = ckpt.get("fetch_units", 0) if ckpt.get("param_sig") == sig else 0
                if start_unit:
                    jobs.append_log(
                        conn, job_id,
                        f"Resuming search from step {start_unit} of {total_units}.",
                    )

                def fetch_progress(unit: int, total: int, current: str) -> None:
                    jobs.update_progress(
                        conn, job_id, unit, total, f"[Search] {current}",
                        extra={"fetch_units": unit, "param_sig": sig},
                    )
                    jobs.append_log(conn, job_id, f"({unit}/{total}) {current}")

                results["fetch"] = stages.run_fetch(
                    conn, cfg, date_from, date_to, fetch_progress, should_stop,
                    start_unit=start_unit,
                )
                check_halt()
                jobs.set_phase(conn, job_id, "search_done")
            if not with_download:
                return results
            if phase == "download_done":
                jobs.append_log(
                    conn, job_id, "Download already completed in a previous run; skipping."
                )
            else:
                jobs.append_log(conn, job_id, "Downloading PDFs for newly found papers.")
                results["download"] = stages.run_download(
                    conn, cfg, progress=phase_progress("Download"), should_stop=should_stop
                )
                check_halt()
                jobs.set_phase(conn, job_id, "download_done")
            return results

        def run_analyze(retry: bool = False) -> dict:
            jobs.append_log(conn, job_id, "Reading papers to identify author affiliations.")
            pid_aff, text_aff = prompts.get(
                "affiliations", db.get_prompt(conn, "affiliations")
            )
            aff_result = stages.run_affiliations(
                conn, cfg, pid_aff, text_aff,
                retry_failed=retry,
                progress=phase_progress("Affiliations"), should_stop=should_stop,
            )
            check_halt()
            jobs.append_log(conn, job_id, "Screening papers for frontier AI-safety relevance.")
            pid_scr, text_scr = prompts.get("screen", db.get_prompt(conn, "screen"))
            screen_result = stages.run_screen(
                conn, cfg, pid_scr, text_scr,
                progress=phase_progress("Screening"), should_stop=should_stop,
            )
            check_halt()
            return {"affiliations": aff_result, "screen": screen_result}

        if kind == "collect":
            result = run_collect(with_download=True)
        elif kind == "fetch":
            result = run_collect(with_download=False)
        elif kind == "analyze":
            result = run_analyze(retry=params.get("retry", False))
        elif kind == "pipeline":
            result = {**run_collect(with_download=True), **run_analyze(retry=True)}
        elif kind == "affiliations":
            jobs.append_log(conn, job_id, "Reading papers to identify author affiliations.")
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
            check_halt()
        elif kind == "screen":
            jobs.append_log(conn, job_id, "Screening papers for frontier AI-safety relevance.")
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
            check_halt()
        else:
            raise ValueError(f"unknown job kind {kind}")
        jobs.finish_job(conn, job_id, result)
    except _Halted as halted:
        jobs.append_log(conn, job_id, f"Job {halted.reason} by the user.")
    except Exception as exc:
        traceback.print_exc()
        with contextlib.suppress(Exception):
            jobs.fail_job(conn, job_id, str(exc))
