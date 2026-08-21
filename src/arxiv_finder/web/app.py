from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from fastapi import Depends, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ValidationError, field_validator

from .. import db, evalgt, jobs
from .. import pdf as pdf_mod
from ..config import AppConfig
from .deps import current_cfg, get_conn, json_field, parse_date_range

_JOB_KINDS = jobs.JOB_KINDS

FRONTEND_DIST = Path(__file__).resolve().parents[3] / "frontend" / "dist"


class JobCreate(BaseModel):
    kind: str
    params: dict

    @field_validator("kind")
    @classmethod
    def _kind(cls, v: str) -> str:
        if v not in _JOB_KINDS:
            raise ValueError(f"kind must be one of {_JOB_KINDS}")
        return v


class ReviewBody(BaseModel):
    included: bool
    category: str | None = None
    subcategory: str | None = None
    note: str = ""


class BulkReviewBody(BaseModel):
    ids: list[int]
    included: bool
    category: str | None = None
    subcategory: str | None = None
    note: str = ""


class BulkDeleteBody(BaseModel):
    ids: list[int]


_MAX_UPLOADS = 20


def _rotate_uploads(directory: Path) -> None:
    """Keep the newest N gt_upload files; delete older ones to avoid unbounded growth."""
    uploads = sorted(
        directory.glob("gt_upload_*"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for p in uploads[_MAX_UPLOADS:]:
        p.unlink(missing_ok=True)


def _delete_paper(conn: sqlite3.Connection, paper_id: int, arxiv_id: str) -> bool:
    conn.execute("DELETE FROM affiliations WHERE paper_id = ?", (paper_id,))
    conn.execute("DELETE FROM llm_calls WHERE paper_id = ?", (paper_id,))
    conn.execute("DELETE FROM labels WHERE arxiv_id = ?", (arxiv_id,))
    conn.execute("DELETE FROM papers WHERE id = ?", (paper_id,))
    conn.commit()
    path = pdf_mod.pdf_path(arxiv_id)
    removed = path.exists()
    if removed:
        path.unlink()
    return removed


REVIEW_CATEGORIES = ("alignment", "robustness", "monitoring", "systemic_safety", "survey")


def _apply_review(
    conn: sqlite3.Connection,
    paper_id: int,
    arxiv_id: str,
    included: bool,
    category: str | None,
    subcategory: str | None,
    note: str,
) -> str:
    status = "screened_included" if included else "screened_excluded"
    conn.execute(
        """UPDATE papers SET status = ?, category = ?, subcategory = ?, rationale = ?
           WHERE id = ?""",
        (
            status,
            category if included else None,
            subcategory if included else None,
            f"manual review: {note}" if note else "manual review",
            paper_id,
        ),
    )
    conn.execute(
        """INSERT INTO labels (paper_id, arxiv_id, source, included, category,
           subcategory, note, created_at) VALUES (?, ?, 'manual', ?, ?, ?, ?, ?)""",
        (
            paper_id,
            arxiv_id,
            1 if included else 0,
            category,
            subcategory,
            note,
            db.now_iso(),
        ),
    )
    conn.commit()
    return status


class ConfigSave(BaseModel):
    config: dict
    note: str = ""


class PromptSave(BaseModel):
    text: str


def create_app() -> FastAPI:
    app = FastAPI(title="arXiv Paper Finder")
    app.add_middleware(
        CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
    )

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True}

    app.include_router(_papers_router(), prefix="/api")
    app.include_router(_jobs_router(), prefix="/api")
    app.include_router(_config_router(), prefix="/api")
    app.include_router(_prompts_router(), prefix="/api")
    app.include_router(_stats_router(), prefix="/api")
    app.include_router(_labels_router(), prefix="/api")

    if FRONTEND_DIST.exists():
        from fastapi.responses import FileResponse

        assets_dir = FRONTEND_DIST / "assets"
        if assets_dir.exists():
            app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

        index_file = FRONTEND_DIST / "index.html"

        @app.get("/{full_path:path}", include_in_schema=False)
        def spa_fallback(full_path: str):
            if full_path.startswith("api/"):
                raise HTTPException(404, "not found")
            return FileResponse(index_file)

    return app


def _papers_router():
    from fastapi import APIRouter

    router = APIRouter(tags=["papers"])

    @router.get("/papers")
    def list_papers(
        conn: sqlite3.Connection = Depends(get_conn),
        status: str | None = Query(None),
        category: str | None = Query(None),
        subcategory: str | None = Query(None),
        china: bool | None = Query(None),
        q: str | None = Query(None),
        date_from: str | None = Query(None),
        date_to: str | None = Query(None),
        min_conf: float | None = Query(None),
        max_conf: float | None = Query(None),
        page: int = Query(1, ge=1),
        page_size: int = Query(50, ge=1, le=500),
    ) -> dict:
        where = []
        args: list = []
        if status:
            where.append("status = ?")
            args.append(status)
        if category:
            where.append("category = ?")
            args.append(category)
        if subcategory:
            where.append("subcategory = ?")
            args.append(subcategory)
        if china is not None:
            where.append("china_flag = ?")
            args.append(1 if china else 0)
        if q:
            where.append("(title LIKE ? OR abstract LIKE ? OR arxiv_id LIKE ?)")
            like = f"%{q}%"
            args.extend([like, like, like])
        if date_from:
            where.append("submitted >= ?")
            args.append(date_from)
        if date_to:
            where.append("submitted <= ?")
            args.append(date_to + "T23:59:59")
        if min_conf is not None:
            where.append("confidence >= ?")
            args.append(min_conf)
        if max_conf is not None:
            where.append("confidence <= ?")
            args.append(max_conf)
        where_sql = f"WHERE {' AND '.join(where)}" if where else ""
        total = conn.execute(f"SELECT COUNT(*) AS n FROM papers {where_sql}", args).fetchone()["n"]
        rows = conn.execute(
            f"""SELECT id, arxiv_id, title, submitted, status, category, subcategory,
                confidence, china_flag, primary_category, queries_json, abs_url
                FROM papers {where_sql} ORDER BY submitted DESC
                LIMIT ? OFFSET ?""",
            (*args, page_size, (page - 1) * page_size),
        ).fetchall()
        items = []
        for r in rows:
            d = dict(r)
            d["queries"] = json_field(r, "queries_json") or []
            d["pdf_cached"] = pdf_mod.pdf_path(r["arxiv_id"]).exists()
            items.append(d)
        return {"total": total, "page": page, "page_size": page_size, "items": items}

    @router.get("/papers/{paper_id}")
    def paper_detail(paper_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
        row = conn.execute("SELECT * FROM papers WHERE id = ?", (paper_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "paper not found")
        d = dict(row)
        d["authors"] = json_field(row, "authors_json") or []
        d["categories"] = json_field(row, "categories_json") or []
        d["queries"] = json_field(row, "queries_json") or []
        d["pdf_cached"] = pdf_mod.pdf_path(row["arxiv_id"]).exists()
        aff = conn.execute(
            "SELECT * FROM affiliations WHERE paper_id = ?", (paper_id,)
        ).fetchone()
        if aff is not None:
            d["affiliations"] = {
                "model": aff["model"],
                "method": aff["method"],
                "status": aff["status"],
                "authors": json_field(aff, "authors_json") or [],
                "likely_mainland_china": aff["likely_mainland_china"],
                "error": aff["error"],
                "created_at": aff["created_at"],
            }
        else:
            d["affiliations"] = None
        calls = conn.execute(
            """SELECT stage, model, request_summary, response_text, input_tokens,
               output_tokens, latency_ms, created_at
               FROM llm_calls WHERE paper_id = ? ORDER BY id""",
            (paper_id,),
        ).fetchall()
        d["llm_calls"] = [dict(c) for c in calls]
        labels = conn.execute(
            "SELECT source, included, category, subcategory, note, created_at FROM labels "
            "WHERE arxiv_id = ? ORDER BY id DESC",
            (row["arxiv_id"],),
        ).fetchall()
        d["labels"] = [dict(lbl) for lbl in labels]
        return d

    @router.post("/papers/{paper_id}/review")
    def review_paper(
        paper_id: int, body: ReviewBody, conn: sqlite3.Connection = Depends(get_conn)
    ) -> dict:
        row = conn.execute("SELECT id, arxiv_id FROM papers WHERE id = ?", (paper_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "paper not found")
        if body.included and body.category not in REVIEW_CATEGORIES:
            raise HTTPException(400, "valid category required when including")
        status = _apply_review(
            conn, paper_id, row["arxiv_id"], body.included,
            body.category, body.subcategory, body.note,
        )
        return {"ok": True, "status": status}

    @router.post("/papers/bulk-review")
    def bulk_review(body: BulkReviewBody, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
        if not body.ids:
            raise HTTPException(400, "no paper ids provided")
        if body.included and body.category not in REVIEW_CATEGORIES:
            raise HTTPException(400, "valid category required when including")
        updated = 0
        for paper_id in body.ids:
            row = conn.execute(
                "SELECT id, arxiv_id FROM papers WHERE id = ?", (paper_id,)
            ).fetchone()
            if row is None:
                continue
            _apply_review(
                conn, paper_id, row["arxiv_id"], body.included,
                body.category, body.subcategory, body.note,
            )
            updated += 1
        return {"ok": True, "updated": updated}

    @router.delete("/papers/{paper_id}")
    def delete_paper(paper_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
        row = conn.execute("SELECT id, arxiv_id FROM papers WHERE id = ?", (paper_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "paper not found")
        pdf_removed = _delete_paper(conn, row["id"], row["arxiv_id"])
        return {"ok": True, "pdf_removed": pdf_removed}

    @router.post("/papers/bulk-delete")
    def bulk_delete(body: BulkDeleteBody, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
        if not body.ids:
            raise HTTPException(400, "no paper ids provided")
        deleted = 0
        pdfs_removed = 0
        for paper_id in body.ids:
            row = conn.execute(
                "SELECT id, arxiv_id FROM papers WHERE id = ?", (paper_id,)
            ).fetchone()
            if row is None:
                continue
            if _delete_paper(conn, row["id"], row["arxiv_id"]):
                pdfs_removed += 1
            deleted += 1
        return {"ok": True, "deleted": deleted, "pdfs_removed": pdfs_removed}

    @router.get("/export")
    def export_csv(
        conn: sqlite3.Connection = Depends(get_conn),
        date_from: str | None = Query(None),
        date_to: str | None = Query(None),
    ):
        from fastapi.responses import Response

        from .. import export as export_mod

        content, n = export_mod.export_dataset_target_to_string(conn, date_from, date_to)
        tag_from = (date_from or "all")[:10]
        tag_to = (date_to or "all")[:10]
        filename = f"papers_{tag_from}_{tag_to}.csv"
        return Response(
            content=content,
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"',
                     "X-Exported-Rows": str(n)},
        )

    return router


def _jobs_router():
    from fastapi import APIRouter

    router = APIRouter(tags=["jobs"])

    @router.get("/jobs")
    def list_jobs(conn: sqlite3.Connection = Depends(get_conn)) -> dict:
        rows = conn.execute("SELECT * FROM jobs ORDER BY id DESC LIMIT 100").fetchall()
        items = []
        for r in rows:
            d = dict(r)
            d["params"] = json_field(r, "params_json")
            d["progress"] = json_field(r, "progress_json")
            items.append(d)
        return {"items": items}

    @router.post("/jobs", status_code=201)
    def create_job(body: JobCreate, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
        raw = body.params
        if body.kind in ("fetch", "pipeline", "collect"):
            if not raw.get("date_from") or not raw.get("date_to"):
                raise HTTPException(400, "date_from and date_to are required")
            df, dt = parse_date_range(str(raw["date_from"]), str(raw["date_to"]))
            params: dict = {"date_from": df.isoformat(), "date_to": dt.isoformat()}
            if body.kind == "pipeline" and raw.get("model"):
                params["model"] = str(raw["model"])
        else:
            params = {}
            if raw.get("limit") is not None:
                try:
                    params["limit"] = int(raw["limit"])
                except (TypeError, ValueError) as exc:
                    raise HTTPException(400, "limit must be an integer") from exc
            if raw.get("retry"):
                params["retry"] = True
        job_id = jobs.enqueue_job(conn, body.kind, params)
        return {"job_id": job_id}

    @router.get("/models")
    def list_models(conn: sqlite3.Connection = Depends(get_conn)) -> dict:
        from ..llm import LLMError, build_client

        _, cfg = current_cfg(conn)
        try:
            client = build_client(
                cfg.llm.base_url, cfg.llm.api_key_env, cfg.llm.timeout_sec, 1
            )
            models = client.list_models()
        except LLMError as exc:
            raise HTTPException(502, str(exc)) from exc
        return {"models": models}

    @router.get("/jobs/{job_id}")
    def job_detail(job_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "job not found")
        d = dict(row)
        d["params"] = json_field(row, "params_json")
        d["progress"] = json_field(row, "progress_json")
        return d

    @router.post("/jobs/{job_id}/cancel")
    def cancel(job_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
        ok = jobs.cancel_job(conn, job_id)
        if not ok:
            raise HTTPException(400, "job is not cancellable")
        return {"ok": True}

    @router.post("/jobs/{job_id}/pause")
    def pause(job_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
        ok = jobs.pause_job(conn, job_id)
        if not ok:
            raise HTTPException(400, "job is not pausable")
        return {"ok": True}

    @router.post("/jobs/{job_id}/resume")
    def resume(job_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
        ok = jobs.resume_job(conn, job_id)
        if not ok:
            raise HTTPException(400, "job is not resumable")
        return {"ok": True}

    return router


def _config_router():
    from fastapi import APIRouter

    router = APIRouter(tags=["config"])

    @router.get("/config")
    def get_config(conn: sqlite3.Connection = Depends(get_conn)) -> dict:
        version_id, cfg = current_cfg(conn)
        return {"version_id": version_id, "config": cfg.model_dump()}

    @router.put("/config")
    def save_config(body: ConfigSave, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
        try:
            cfg = AppConfig.model_validate(body.config)
        except ValidationError as exc:
            raise HTTPException(422, {"errors": json.loads(exc.json())}) from exc
        cur = conn.execute(
            "INSERT INTO config_versions (created_at, config_json, note) VALUES (?, ?, ?)",
            (db.now_iso(), cfg.model_dump_json(), body.note or "edited via UI"),
        )
        conn.commit()
        return {"version_id": cur.lastrowid}

    @router.get("/config/versions")
    def config_versions(conn: sqlite3.Connection = Depends(get_conn)) -> dict:
        rows = conn.execute(
            "SELECT id, created_at, note FROM config_versions ORDER BY id DESC"
        ).fetchall()
        return {"items": [dict(r) for r in rows]}

    @router.get("/config/versions/{version_id}")
    def config_version(version_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
        row = conn.execute(
            "SELECT * FROM config_versions WHERE id = ?", (version_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(404, "version not found")
        return {"version_id": row["id"], "created_at": row["created_at"],
                "note": row["note"], "config": json.loads(row["config_json"])}

    @router.post("/config/rollback/{version_id}")
    def rollback(version_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
        row = conn.execute(
            "SELECT config_json FROM config_versions WHERE id = ?", (version_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(404, "version not found")
        cur = conn.execute(
            "INSERT INTO config_versions (created_at, config_json, note) VALUES (?, ?, ?)",
            (db.now_iso(), row["config_json"], f"rollback to version {version_id}"),
        )
        conn.commit()
        return {"version_id": cur.lastrowid}

    return router


def _prompts_router():
    from fastapi import APIRouter

    router = APIRouter(tags=["prompts"])

    @router.get("/prompts")
    def list_prompts(conn: sqlite3.Connection = Depends(get_conn)) -> dict:
        rows = conn.execute(
            """SELECT name, MAX(version) AS version FROM prompt_versions
               GROUP BY name ORDER BY name"""
        ).fetchall()
        items = []
        for r in rows:
            latest = conn.execute(
                "SELECT id, text, created_at FROM prompt_versions WHERE name = ? AND version = ?",
                (r["name"], r["version"]),
            ).fetchone()
            items.append(
                {
                    "name": r["name"],
                    "version": r["version"],
                    "version_id": latest["id"],
                    "text": latest["text"],
                    "created_at": latest["created_at"],
                }
            )
        return {"items": items}

    @router.get("/prompts/{name}/versions")
    def prompt_versions(name: str, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
        rows = conn.execute(
            "SELECT id, version, created_at FROM prompt_versions WHERE name = ? ORDER BY version DESC",
            (name,),
        ).fetchall()
        if not rows:
            raise HTTPException(404, "prompt not found")
        return {"name": name, "items": [dict(r) for r in rows]}

    @router.get("/prompts/{name}/versions/{version_id}")
    def prompt_version(name: str, version_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
        row = conn.execute(
            "SELECT id, name, version, text, created_at FROM prompt_versions WHERE id = ? AND name = ?",
            (version_id, name),
        ).fetchone()
        if row is None:
            raise HTTPException(404, "prompt version not found")
        return dict(row)

    @router.post("/prompts/{name}/rollback/{version_id}")
    def rollback_prompt(name: str, version_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
        row = conn.execute(
            "SELECT text FROM prompt_versions WHERE id = ? AND name = ?", (version_id, name)
        ).fetchone()
        if row is None:
            raise HTTPException(404, "prompt version not found")
        version_id_new = db.seed_prompt(conn, name, row["text"])
        return {"version_id": version_id_new}

    @router.put("/prompts/{name}")
    def save_prompt(name: str, body: PromptSave, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
        if not body.text.strip():
            raise HTTPException(400, "prompt text must not be empty")
        existing = conn.execute(
            "SELECT COUNT(*) AS n FROM prompt_versions WHERE name = ?", (name,)
        ).fetchone()
        if not existing["n"]:
            raise HTTPException(404, "prompt not found")
        version_id = db.seed_prompt(conn, name, body.text)
        return {"version_id": version_id}

    return router


def _stats_router():
    from fastapi import APIRouter

    router = APIRouter(tags=["stats"])

    @router.get("/stats")
    def stats(conn: sqlite3.Connection = Depends(get_conn)) -> dict:
        by_status = {
            r["status"]: r["n"]
            for r in conn.execute(
                "SELECT status, COUNT(*) AS n FROM papers GROUP BY status"
            ).fetchall()
        }
        total = sum(by_status.values())
        cats = conn.execute(
            """SELECT category, subcategory, COUNT(*) AS n FROM papers
               WHERE status = 'screened_included'
               GROUP BY category, subcategory"""
        ).fetchall()
        monthly = conn.execute(
            """SELECT substr(submitted, 1, 7) AS month, COUNT(*) AS n FROM papers
               WHERE status = 'screened_included' GROUP BY month ORDER BY month"""
        ).fetchall()
        tokens = conn.execute(
            """SELECT COALESCE(SUM(input_tokens),0) AS tin, COALESCE(SUM(output_tokens),0) AS tout,
               COUNT(*) AS calls FROM llm_calls"""
        ).fetchone()
        active_jobs = conn.execute(
            "SELECT COUNT(*) AS n FROM jobs WHERE status IN ('queued', 'running')"
        ).fetchone()["n"]
        return {
            "papers_total": total,
            "by_status": by_status,
            "by_category": [dict(r) for r in cats],
            "included_monthly": [dict(r) for r in monthly],
            "llm": {"calls": tokens["calls"], "input_tokens": tokens["tin"],
                    "output_tokens": tokens["tout"]},
            "active_jobs": active_jobs,
        }

    return router


def _labels_router():
    from fastapi import APIRouter

    router = APIRouter(tags=["eval"])

    @router.post("/labels/import")
    def import_labels(file: UploadFile = File(...), conn: sqlite3.Connection = Depends(get_conn)) -> dict:
        content = file.file.read()
        suffix = Path(file.filename or "gt.csv").suffix.lower()
        if suffix not in (".csv", ".jsonl"):
            raise HTTPException(400, "only .csv or .jsonl supported")
        tmp = db.data_dir() / f"gt_upload_{db.now_iso().replace(':', '')}{suffix}"
        tmp.write_bytes(content)
        _rotate_uploads(db.data_dir())
        try:
            gt = evalgt.load_ground_truth(tmp)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        if not gt:
            raise HTTPException(400, "no parsable rows found")
        report = evalgt.evaluate(conn, gt)
        report.pop("included_details", None)
        report["saved_to"] = str(tmp)
        report["rows_parsed"] = len(gt)
        return report

    return router
