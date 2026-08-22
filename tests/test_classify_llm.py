from __future__ import annotations

import pytest

from arxiv_finder.classify import decide, parse_screen_result
from arxiv_finder.llm import extract_json, render_prompt


def test_parse_screen_result_minimal():
    r = parse_screen_result(
        {"is_frontier_ai_safety": True, "confidence": 0.9,
         "category": "alignment", "subcategory": None, "rationale": "x"}
    )
    assert r.is_frontier_ai_safety
    assert r.category == "alignment"


def test_parse_normalizes_empty_strings():
    r = parse_screen_result(
        {"is_frontier_ai_safety": False, "confidence": 1.5,
         "category": "none", "subcategory": ""}
    )
    assert r.category is None
    assert r.subcategory is None
    assert r.confidence == 1.0


def test_parse_monitoring_defaults_subcategory():
    r = parse_screen_result(
        {"is_frontier_ai_safety": True, "confidence": 0.8, "category": "monitoring"}
    )
    assert r.subcategory == "other"


def test_parse_rejects_bad_category():
    with pytest.raises(ValueError):
        parse_screen_result(
            {"is_frontier_ai_safety": True, "confidence": 0.8, "category": "ethics"}
        )


def test_decide_included():
    r = parse_screen_result({"is_frontier_ai_safety": True, "confidence": 0.9})
    assert decide(r, 0.6, 0.5, escalated=False) == ("screened_included", "included")


def test_decide_excluded():
    r = parse_screen_result({"is_frontier_ai_safety": False, "confidence": 0.9})
    assert decide(r, 0.6, 0.5, escalated=False) == ("screened_excluded", "excluded")


def test_decide_auto_excludes_when_unsure():
    r = parse_screen_result({"is_frontier_ai_safety": True, "confidence": 0.4})
    status, action = decide(r, 0.6, 0.5, escalated=False)
    assert (status, action) == ("screened_excluded", "excluded")


def test_decide_after_escalation_review():
    r = parse_screen_result({"is_frontier_ai_safety": True, "confidence": 0.45})
    status, action = decide(r, 0.6, 0.5, escalated=True)
    assert (status, action) == ("needs_review", "human_review")
    r_ok = parse_screen_result({"is_frontier_ai_safety": True, "confidence": 0.55})
    assert decide(r_ok, 0.6, 0.5, escalated=True)[0] == "screened_included"


def test_extract_json_plain():
    assert extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_fenced():
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_extract_json_with_prose():
    text = 'Here you go: {"a": {"b": "c}d"}} done'
    assert extract_json(text) == {"a": {"b": "c}d"}}


def test_extract_json_invalid():
    with pytest.raises(ValueError):
        extract_json("no json here")


def test_render_prompt():
    out = render_prompt("Title: {{title}}\n{{extra}}", {"title": "T", "extra": ""})
    assert out == "Title: T\n"
