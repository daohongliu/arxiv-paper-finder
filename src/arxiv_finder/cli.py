from __future__ import annotations

import importlib.resources
import json
import sqlite3
from datetime import date, datetime
from datetime import time as dtime
from pathlib import Path

import typer
import yaml

from . import db, evalgt, export, jobs, stages, worker
from .config import AppConfig

app = typer.Typer(help="arXiv frontier AI-safety paper finder", no_args_is_help=True)


def _get_conn() -> sqlite3.Connection:
    conn = db.connect()
    db.init_db(conn)
    return conn


def _date_arg(value: str, end_of_day: bool = False) -> datetime:
    d = date.fromisoformat(value)
    return datetime.combine(d, dtime.max if end_of_day else dtime.min)


@app.command()
def init(config_file: Path | None = typer.Option(None, help="YAML config to seed with")) -> None:
    """Create the database and seed config + prompts."""
    conn = _get_conn()
    row = conn.execute("SELECT COUNT(*) AS n FROM config_versions").fetchone()
    if row and row["n"] == 0:
        if config_file is not None:
            cfg = AppConfig.model_validate(yaml.safe_load(config_file.read_text()))
        else:
            cfg = AppConfig()
        db.seed_config(conn, cfg.model_dump_json())
        typer.echo(f"seeded config (version 1), db at {db.db_path()}")
    else:
        typer.echo("config already present")
    prompts_dir = importlib.resources.files("arxiv_finder") / "prompts"
    for name in ("affiliations", "screen"):
        path = prompts_dir / f"{name}.md"
        text = path.read_text(encoding="utf-8")
        existing = conn.execute(
            "SELECT COUNT(*) AS n FROM prompt_versions WHERE name = ?", (name,)
        ).fetchone()
        if existing and existing["n"]:
            latest = conn.execute(
                "SELECT text FROM prompt_versions WHERE name = ? ORDER BY version DESC LIMIT 1",
                (name,),
            ).fetchone()
            if latest and latest["text"] != text:
                db.seed_prompt(conn, name, text)
                typer.echo(f"prompt {name}: new version seeded from package file")
            else:
                typer.echo(f"prompt {name}: up to date")
        else:
            db.seed_prompt(conn, name, text)
            typer.echo(f"prompt {name}: seeded")


def _direct_or_enqueue(conn: sqlite3.Connection, enqueue: bool, kind: str, params: dict) -> None:
    if enqueue:
        job_id = jobs.enqueue_job(conn, kind, params)
        typer.echo(f"queued job {job_id} ({kind}); start `arxiv-finder worker` to run it")
        return
    config_version_id, config_json = db.current_config(conn)
    cfg = AppConfig.model_validate(config_json)
    if kind == "fetch":
        result = stages.run_fetch(
            conn, cfg,
            datetime.fromisoformat(params["date_from"]),
            datetime.fromisoformat(params["date_to"]),
            progress=lambda d, t, c: typer.echo(f"[{d}/{t}] {c}"),
        )
    elif kind == "affiliations":
        pid, text = db.get_prompt(conn, "affiliations")
        result = stages.run_affiliations(
            conn, cfg, pid, text,
            limit=params.get("limit"),
            retry_failed=params.get("retry", False),
            progress=lambda d, t, c: typer.echo(f"[{d}/{t}] {c}"),
        )
    elif kind == "screen":
        pid, text = db.get_prompt(conn, "screen")
        result = stages.run_screen(
            conn, cfg, pid, text,
            limit=params.get("limit"),
            retry_review=params.get("retry", False),
            progress=lambda d, t, c: typer.echo(f"[{d}/{t}] {c}"),
        )
    else:
        raise ValueError(kind)
    typer.echo(json.dumps(result, indent=2))


@app.command()
def fetch(
    date_from: str = typer.Option(..., "--from", help="YYYY-MM-DD"),
    date_to: str = typer.Option(..., "--to", help="YYYY-MM-DD"),
    enqueue: bool = typer.Option(False, help="enqueue as background job instead"),
) -> None:
    """Fetch papers from arXiv for a date range."""
    df, dt = _date_arg(date_from), _date_arg(date_to, end_of_day=True)
    if df >= dt:
        raise typer.BadParameter("--from must be before --to")
    conn = _get_conn()
    _direct_or_enqueue(
        conn, enqueue, "fetch",
        {"date_from": df.isoformat(), "date_to": dt.isoformat()},
    )


@app.command()
def affiliations(
    limit: int | None = typer.Option(None),
    retry: bool = typer.Option(False, help="retry previously failed/unresolved"),
    enqueue: bool = typer.Option(False),
) -> None:
    """Extract author affiliations from PDFs and apply the China filter."""
    conn = _get_conn()
    _direct_or_enqueue(conn, enqueue, "affiliations", {"limit": limit, "retry": retry})


@app.command()
def screen(
    limit: int | None = typer.Option(None),
    retry: bool = typer.Option(False, help="retry needs_review papers"),
    enqueue: bool = typer.Option(False),
) -> None:
    """LLM frontier-AI-safety screening and categorization."""
    conn = _get_conn()
    _direct_or_enqueue(conn, enqueue, "screen", {"limit": limit, "retry": retry})


@app.command(name="export")
def export_cmd(
    out: Path = typer.Option(Path("dataset.csv"), help="output CSV path"),
    date_from: str | None = typer.Option(None, "--from", help="YYYY-MM-DD"),
    date_to: str | None = typer.Option(None, "--to", help="YYYY-MM-DD"),
    detailed: bool = typer.Option(
        False, help="use the detailed internal format instead of the target dataset format"
    ),
) -> None:
    """Export included papers as CSV (default: the target dataset format)."""
    conn = _get_conn()
    if detailed:
        n = export.export_dataset(conn, out)
    else:
        with out.open("w", newline="", encoding="utf-8") as f:
            n = export.export_dataset_target(conn, f, date_from, date_to)
    typer.echo(f"wrote {n} papers to {out}")


@app.command()
def review_export(out: Path = typer.Option(Path("review_queue.csv"))) -> None:
    """Export the human review queue."""
    conn = _get_conn()
    n = export.export_review_queue(conn, out)
    typer.echo(f"wrote {n} papers to {out}")


@app.command()
def eval(
    gt: Path = typer.Option(..., help="ground truth CSV/JSONL with arXiv IDs + categories"),
    out: Path | None = typer.Option(None, help="write full report JSON"),
) -> None:
    """Evaluate pipeline against a human-labeled dataset."""
    conn = _get_conn()
    ground = evalgt.load_ground_truth(gt)
    report = evalgt.evaluate(conn, ground)
    typer.echo(f"ground truth papers: {report['total_gt']}")
    typer.echo(f"included by pipeline: {report['included']} (recovery {report['recovery']:.1%})")
    for stage, ids in report["dropped_at"].items():
        typer.echo(f"  dropped at {stage}: {len(ids)}")
    if report["category_accuracy"] is not None:
        typer.echo(f"category accuracy (among included+labeled): {report['category_accuracy']:.1%}")
    if out:
        out.write_text(json.dumps(report, indent=2), encoding="utf-8")
        typer.echo(f"full report written to {out}")


@app.command(name="pdf-cache")
def pdf_cache_cmd(
    missing: bool = typer.Option(
        False, help="print 'arxiv_id<TAB>pdf_url' for papers whose PDF is not cached"
    ),
    download: Path | None = typer.Option(
        None, help="download PDFs listed in FILE (lines: arxiv_id<TAB>pdf_url) into the cache"
    ),
    concurrency: int = typer.Option(4, help="parallel downloads for --download"),
) -> None:
    """Inspect/fill the PDF cache (for moving downloads to a machine with arXiv access)."""
    from . import pdf

    if download is not None:
        from concurrent.futures import ThreadPoolExecutor, as_completed

        entries: list[tuple[str, str]] = []
        for line in download.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) != 2:
                continue
            entries.append((parts[0], parts[1]))
        todo = [(aid, url) for aid, url in entries if not pdf.pdf_path(aid).exists()]
        typer.echo(f"{len(entries)} listed, {len(todo)} missing locally")
        done = 0
        failed: list[str] = []

        def fetch_one(aid: str, url: str) -> str:
            try:
                pdf.ensure_pdf(aid, url)
                return ""
            except Exception as exc:
                return f"{aid}: {exc}"

        with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
            futures = {pool.submit(fetch_one, aid, url): aid for aid, url in todo}
            for fut in as_completed(futures):
                done += 1
                err = fut.result()
                if err:
                    failed.append(err)
                if done % 25 == 0 or done == len(todo):
                    typer.echo(f"  {done}/{len(todo)} downloaded")
        if failed:
            typer.echo(f"{len(failed)} failed:")
            for line in failed[:20]:
                typer.echo(f"  {line}")
        return

    if missing:
        conn = _get_conn()
        rows = conn.execute("SELECT arxiv_id, pdf_url FROM papers ORDER BY submitted").fetchall()
        n = 0
        for r in rows:
            if not pdf.pdf_path(r["arxiv_id"]).exists():
                typer.echo(f"{r['arxiv_id']}\t{r['pdf_url']}")
                n += 1
        typer.echo(f"# {n} missing", err=True)
        return

    typer.echo("nothing to do: use --missing or --download FILE")


@app.command()
def stats() -> None:
    """Print funnel statistics."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT status, COUNT(*) AS n FROM papers GROUP BY status ORDER BY n DESC"
    ).fetchall()
    total = sum(r["n"] for r in rows)
    typer.echo(f"papers total: {total}")
    for r in rows:
        typer.echo(f"  {r['status']}: {r['n']}")
    cats = conn.execute(
        "SELECT category, subcategory, COUNT(*) AS n FROM papers "
        "WHERE status = 'screened_included' GROUP BY category, subcategory ORDER BY n DESC"
    ).fetchall()
    calls = conn.execute(
        """SELECT stage, COUNT(*) AS n, COALESCE(SUM(input_tokens), 0) AS tin,
           COALESCE(SUM(output_tokens), 0) AS tout FROM llm_calls GROUP BY stage"""
    ).fetchall()
    if cats:
        typer.echo("included by category:")
        for c in cats:
            typer.echo(f"  {c['category']}/{c['subcategory'] or '-'}: {c['n']}")
    if calls:
        typer.echo("llm calls:")
        for c in calls:
            typer.echo(f"  {c['stage']}: {c['n']} calls, {c['tin']} in / {c['tout']} out tokens")


@app.command(name="worker")
def worker_cmd(once: bool = typer.Option(False, help="process at most one job, then exit")) -> None:
    """Run the background job worker."""
    worker.run_worker(once=once)


@app.command()
def serve(host: str = "127.0.0.1", port: int = 8000) -> None:
    """Run the web API + UI."""
    import uvicorn

    from .web.app import create_app

    if host not in ("127.0.0.1", "localhost", "::1"):
        typer.echo(
            f"WARNING: serving on non-loopback host {host!r} exposes the API "
            "(job control, data deletion, paid LLM spend) with no authentication. "
            "Prefer a localhost host or add an auth layer.",
            err=True,
        )
    uvicorn.run(create_app(), host=host, port=port)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
