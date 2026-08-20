from __future__ import annotations

import csv

from arxiv_finder import db, evalgt


def test_normalize_id():
    assert evalgt.normalize_id("2304.12345") == "2304.12345"
    assert evalgt.normalize_id("https://arxiv.org/abs/2304.12345v2") == "2304.12345"
    assert evalgt.normalize_id("garbage") is None


def test_normalize_gt_label():
    assert evalgt.normalize_gt_label("Alignment") == ("alignment", None)
    assert evalgt.normalize_gt_label("Robustness") == ("robustness", None)
    assert evalgt.normalize_gt_label("Systemic Safety") == ("systemic_safety", None)
    assert evalgt.normalize_gt_label("Monitoring (interpretability)") == (
        "monitoring",
        "interpretability",
    )
    assert evalgt.normalize_gt_label("Monitoring (evaluations)") == (
        "monitoring",
        "evaluations",
    )
    assert evalgt.normalize_gt_label("Monitoring (other)") == ("monitoring", "other")
    assert evalgt.normalize_gt_label("Monitoring") == ("monitoring", None)


def test_load_ground_truth_csv(tmp_path):
    p = tmp_path / "gt.csv"
    with p.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["arxiv_id", "category"])
        w.writerow(["2304.12345", "Alignment"])
        w.writerow(["https://arxiv.org/abs/2305.00001v1", "Monitoring (interpretability)"])
        w.writerow(["junk-row", "Alignment"])
    gt = evalgt.load_ground_truth(p)
    assert len(gt) == 2
    assert gt[0]["arxiv_id"] == "2304.12345"
    assert gt[1]["category"] == "monitoring"
    assert gt[1]["subcategory"] == "interpretability"


def test_evaluate_funnel(conn):
    db.seed_config(conn, "{}")
    conn.execute(
        """INSERT INTO papers (arxiv_id, title, abstract, authors_json, categories_json,
           submitted, updated, abs_url, pdf_url, queries_json, status, category, subcategory)
           VALUES ('1', 'a', 'x', '[]', '[]', '', '', '', '', '[]', 'screened_included',
                   'alignment', NULL)"""
    )
    conn.execute(
        """INSERT INTO papers (arxiv_id, title, abstract, authors_json, categories_json,
           submitted, updated, abs_url, pdf_url, queries_json, status)
           VALUES ('2', 'b', 'x', '[]', '[]', '', '', '', '', '[]', 'filtered_out')"""
    )
    conn.commit()
    gt = [
        {"arxiv_id": "1", "category": "alignment", "subcategory": None},
        {"arxiv_id": "2", "category": "robustness", "subcategory": None},
        {"arxiv_id": "3", "category": "alignment", "subcategory": None},
    ]
    report = evalgt.evaluate(conn, gt)
    assert report["total_gt"] == 3
    assert report["included"] == 1
    assert report["dropped_at"]["filtered_out"] == ["2"]
    assert report["dropped_at"]["not_fetched"] == ["3"]
    assert report["category_accuracy"] == 1.0
