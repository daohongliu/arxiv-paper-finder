from __future__ import annotations

import csv
import io
import json
import sqlite3
from pathlib import Path
from typing import TextIO

TARGET_COLUMNS = [
    "Reviewed",
    "Title",
    "Title URL",
    "Research direction",
    "Date",
    "Institution 1",
    "Institution 2",
    "Other institutions",
    "Anchor author 1",
    "Anchor author 2",
    "Anchor author 3",
    "Anchor author 4",
    "Anchor author 5",
]

DIRECTION_LABELS = {
    "alignment": "Alignment",
    "robustness": "Robustness",
    "systemic_safety": "Systemic Safety",
    "survey": "Survey or Position Paper",
}
MONITORING_LABELS = {
    "evaluations": "Monitoring (evaluations)",
    "interpretability": "Monitoring (interpretability)",
    "other": "Monitoring (other)",
}


def direction_label(category: str | None, subcategory: str | None) -> str:
    if category == "monitoring":
        return MONITORING_LABELS.get(subcategory or "other", "Monitoring (other)")
    return DIRECTION_LABELS.get(category or "", "")


def format_export_date(iso_ts: str) -> str:
    return f"{iso_ts[:10]} 00:00:00"


def institutions_in_order(aff_entries: list[dict]) -> list[str]:
    seen: list[str] = []
    for e in aff_entries:
        inst = (e.get("institution") or "").strip()
        if inst and inst not in seen:
            seen.append(inst)
    return seen


def export_dataset(conn: sqlite3.Connection, out_path: Path) -> int:
    rows = conn.execute(
        """SELECT p.*, a.authors_json AS aff_json, a.method AS aff_method
           FROM papers p LEFT JOIN affiliations a ON a.paper_id = p.id
           WHERE p.status = 'screened_included'
           ORDER BY p.submitted"""
    ).fetchall()
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "arxiv_id",
                "submitted",
                "title",
                "abs_url",
                "authors",
                "category",
                "subcategory",
                "confidence",
                "mainland_authors",
                "mainland_institutions",
                "rationale",
                "queries_matched",
            ]
        )
        for r in rows:
            authors = json.loads(r["authors_json"])
            aff = json.loads(r["aff_json"]) if r["aff_json"] else []
            mainland_names = [e.get("name", "") for e in aff if e.get("mainland_china") == "yes"]
            mainland_insts = sorted(
                {e.get("institution", "") for e in aff if e.get("mainland_china") == "yes"} - {""}
            )
            writer.writerow(
                [
                    r["arxiv_id"],
                    r["submitted"],
                    r["title"],
                    r["abs_url"],
                    "; ".join(authors),
                    r["category"],
                    r["subcategory"],
                    f"{r['confidence']:.2f}" if r["confidence"] is not None else "",
                    "; ".join(mainland_names),
                    "; ".join(mainland_insts),
                    r["rationale"],
                    "; ".join(json.loads(r["queries_json"])),
                ]
            )
    return len(rows)


def export_dataset_target(
    conn: sqlite3.Connection,
    out: TextIO,
    date_from: str | None = None,
    date_to: str | None = None,
) -> int:
    where = ["p.status = 'screened_included'"]
    args: list[str] = []
    if date_from:
        where.append("substr(p.submitted, 1, 10) >= ?")
        args.append(date_from[:10])
    if date_to:
        where.append("substr(p.submitted, 1, 10) <= ?")
        args.append(date_to[:10])
    rows = conn.execute(
        f"""SELECT p.title, p.abs_url, p.submitted, p.category, p.subcategory,
               p.authors_json, a.authors_json AS aff_json
            FROM papers p LEFT JOIN affiliations a ON a.paper_id = p.id
            WHERE {' AND '.join(where)}
            ORDER BY p.submitted""",
        args,
    ).fetchall()

    writer = csv.writer(out)
    writer.writerow(TARGET_COLUMNS)
    for r in rows:
        authors: list[str] = json.loads(r["authors_json"])
        aff: list[dict] = json.loads(r["aff_json"]) if r["aff_json"] else []
        insts = institutions_in_order(aff)
        anchors = authors[-5:]
        row = [
            "",
            r["title"],
            r["abs_url"],
            direction_label(r["category"], r["subcategory"]),
            format_export_date(r["submitted"]),
            insts[0] if len(insts) > 0 else "",
            insts[1] if len(insts) > 1 else "",
            "\n".join(insts[2:]),
        ]
        row.extend(anchors)
        row.extend([""] * (5 - len(anchors)))
        writer.writerow(row)
    return len(rows)


def export_dataset_target_to_string(
    conn: sqlite3.Connection, date_from: str | None, date_to: str | None
) -> tuple[str, int]:
    buf = io.StringIO()
    n = export_dataset_target(conn, buf, date_from, date_to)
    return buf.getvalue(), n


def export_review_queue(conn: sqlite3.Connection, out_path: Path) -> int:
    rows = conn.execute(
        """SELECT p.*, a.authors_json AS aff_json
           FROM papers p LEFT JOIN affiliations a ON a.paper_id = p.id
           WHERE p.status IN ('needs_review', 'unresolved', 'screen_error')
           ORDER BY p.submitted"""
    ).fetchall()
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            ["arxiv_id", "status", "submitted", "title", "abs_url", "authors", "abstract",
             "affiliations_json", "confidence", "rationale"]
        )
        for r in rows:
            writer.writerow(
                [
                    r["arxiv_id"],
                    r["status"],
                    r["submitted"],
                    r["title"],
                    r["abs_url"],
                    "; ".join(json.loads(r["authors_json"])),
                    r["abstract"],
                    r["aff_json"] or "",
                    r["confidence"] if r["confidence"] is not None else "",
                    r["rationale"] or "",
                ]
            )
    return len(rows)
