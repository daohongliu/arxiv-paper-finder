from __future__ import annotations

from arxiv_finder.config import ChinaFilterConfig
from arxiv_finder.filters import passes_china_filter


def entry(mainland: str | None) -> dict:
    return {"mainland_china": mainland}


def test_default_rule_any_mainland_passes():
    cfg = ChinaFilterConfig()
    ok, _ = passes_china_filter([entry("no"), entry("yes"), entry("no")], cfg)
    assert ok


def test_default_rule_no_mainland_fails():
    cfg = ChinaFilterConfig()
    ok, _ = passes_china_filter([entry("no"), entry("unclear")], cfg)
    assert not ok


def test_empty_fails():
    ok, reason = passes_china_filter([], ChinaFilterConfig())
    assert not ok
    assert "no authors" in reason


def test_fraction_rule():
    cfg = ChinaFilterConfig(min_count=2, min_fraction=1 / 3)
    authors = [entry("yes"), entry("no")] + [entry("no")] * 8
    ok, _ = passes_china_filter(authors, cfg)
    assert not ok
    authors2 = [entry("yes"), entry("yes")] + [entry("no")] * 4
    ok2, _ = passes_china_filter(authors2, cfg)
    assert ok2


def test_anchor_rule():
    cfg = ChinaFilterConfig(min_count=99, anchor_rule=True)
    authors = [entry("no"), entry("no"), entry("yes")]
    ok, reason = passes_china_filter(authors, cfg)
    assert ok
    assert "anchor" in reason


def test_anchor_rule_large_paper_uses_last_3():
    cfg = ChinaFilterConfig(min_count=99, anchor_rule=True)
    authors = [entry("no")] * 5 + [entry("no"), entry("no"), entry("yes")]
    ok, _ = passes_china_filter(authors, cfg)
    assert ok
    authors_miss = [entry("yes")] + [entry("no")] * 7
    ok2, _ = passes_china_filter(authors_miss, cfg)
    assert not ok2
