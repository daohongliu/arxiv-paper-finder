from __future__ import annotations

import csv
import json
import re
import sqlite3
from pathlib import Path
from typing import Any

from .fetch import parse_arxiv_id

_ID_HEADERS = (
    "arxiv_id",
    "arxivid",
    "arxiv id",
    "id",
    "paper_id",
    "paper id",
    "paper",
    "title url",
    "url",
    "link",
)
_CAT_HEADERS = ("category", "direction", "label", "class", "type", "research direction")


def normalize_id(raw: str) -> str | None:
    parsed = parse_arxiv_id(raw.strip())
    return parsed[0] if parsed else None


def normalize_gt_label(raw: str) -> tuple[str, str | None]:
    s = re.sub(r"\s+", " ", raw.strip().lower())
    if s.startswith("alignment"):
        return "alignment", None
    if s.startswith("robustness"):
        return "robustness", None
    if "systemic" in s:
        return "systemic_safety", None
    if "interp" in s:
        return "monitoring", "interpretability"
    if "eval" in s:
        return "monitoring", "evaluations"
    if s.startswith("monitoring"):
        sub = None
        if "other" in s:
            sub = "other"
        return "monitoring", sub
    return "", None


def load_ground_truth(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if path.suffix.lower() == ".jsonl":
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                obj = json.loads(line)
                rows.append(obj)
        id_key = next((k for k in rows[0] if k.lower() in _ID_HEADERS), None) if rows else None
        cat_key = next((k for k in rows[0] if k.lower() in _CAT_HEADERS), None) if rows else None
    else:
        with path.open(encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            fieldmap = {h: (h or "").strip().lower() for h in (reader.fieldnames or [])}
            id_key = next((h for h, low in fieldmap.items() if low in _ID_HEADERS), None)
            cat_key = next((h for h, low in fieldmap.items() if low in _CAT_HEADERS), None)
            for row in reader:
                rows.append(row)
    if not id_key:
        raise ValueError(f"could not find an arXiv-ID column in {path}")
    out = []
    for row in rows:
        raw_id = str(row.get(id_key, "")).strip()
        aid = normalize_id(raw_id)
        if not aid:
            continue
        raw_cat = str(row.get(cat_key, "")).strip() if cat_key else ""
        cat, sub = normalize_gt_label(raw_cat) if raw_cat else ("", None)
        out.append({"arxiv_id": aid, "category": cat, "subcategory": sub, "raw": row})
    return out


def evaluate(conn: sqlite3.Connection, gt: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(gt)
    dropped_at: dict[str, list[str]] = {
        "not_fetched": [],
        "filtered_out": [],
        "unresolved": [],
        "screened_excluded": [],
        "needs_review": [],
        "other": [],
    }
    included: list[dict[str, Any]] = []
    by_id = {
        r["arxiv_id"]: r
        for r in conn.execute("SELECT arxiv_id, status, category, subcategory FROM papers").fetchall()
    }
    for item in gt:
        row = by_id.get(item["arxiv_id"])
        if row is None:
            dropped_at["not_fetched"].append(item["arxiv_id"])
            continue
        status = row["status"]
        if status == "screened_included":
            included.append({**item, "pipeline_category": row["category"],
                             "pipeline_subcategory": row["subcategory"]})
        elif status in ("filtered_out",):
            dropped_at["filtered_out"].append(item["arxiv_id"])
        elif status in ("unresolved", "screen_error"):
            dropped_at["unresolved"].append(item["arxiv_id"])
        elif status == "screened_excluded":
            dropped_at["screened_excluded"].append(item["arxiv_id"])
        elif status == "needs_review":
            dropped_at["needs_review"].append(item["arxiv_id"])
        else:
            dropped_at["other"].append(item["arxiv_id"])

    category_matrix: dict[str, dict[str, int]] = {}
    category_matches = 0
    labeled = [x for x in included if x["category"]]
    for item in labeled:
        gt_cat = item["category"]
        pl_cat = item["pipeline_category"] or ""
        if gt_cat == pl_cat:
            category_matches += 1
            if gt_cat == "monitoring" and item["subcategory"]:
                pass
        category_matrix.setdefault(gt_cat, {})
        category_matrix[gt_cat][pl_cat or "(none)"] = (
            category_matrix[gt_cat].get(pl_cat or "(none)", 0) + 1
        )

    return {
        "total_gt": total,
        "included": len(included),
        "recovery": len(included) / total if total else 0.0,
        "dropped_at": {k: v for k, v in dropped_at.items() if v},
        "category_accuracy": category_matches / len(labeled) if labeled else None,
        "category_matrix": category_matrix,
        "included_details": included,
    }
