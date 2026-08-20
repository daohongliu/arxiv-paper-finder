from __future__ import annotations

from datetime import datetime

from arxiv_finder.fetch import (
    _entry_to_paper,
    build_query,
    month_slices,
    parse_arxiv_id,
)


def test_parse_arxiv_id_new_style():
    assert parse_arxiv_id("2304.12345") == ("2304.12345", 1)
    assert parse_arxiv_id("2304.12345v3") == ("2304.12345", 3)
    assert parse_arxiv_id("https://arxiv.org/abs/2304.12345v2") == ("2304.12345", 2)
    assert parse_arxiv_id("https://arxiv.org/pdf/2504.14668v1") == ("2504.14668", 1)


def test_parse_arxiv_id_old_style():
    assert parse_arxiv_id("cs/0501001") == ("cs/0501001", 1)
    assert parse_arxiv_id("hep-th/9901001v2") == ("hep-th/9901001", 2)


def test_parse_arxiv_id_invalid():
    assert parse_arxiv_id("not-a-paper") is None
    assert parse_arxiv_id("") is None


def test_month_slices_single_month():
    start = datetime(2025, 4, 10)
    end = datetime(2025, 4, 25)
    slices = month_slices(start, end)
    assert len(slices) == 1
    assert slices[0][0] == start
    assert slices[0][1] == end


def test_month_slices_multiple():
    start = datetime(2025, 1, 15)
    end = datetime(2025, 3, 10)
    slices = month_slices(start, end)
    assert len(slices) == 3
    assert slices[0][0] == datetime(2025, 1, 15)
    assert slices[0][1].month == 1 and slices[0][1].day == 31
    assert slices[1][0] == datetime(2025, 2, 1)
    assert slices[1][1].month == 2 and slices[1][1].day == 28
    assert slices[2][0] == datetime(2025, 3, 1)
    assert slices[2][1] == end


def test_month_slices_full_range():
    slices = month_slices(datetime(2023, 4, 1), datetime(2026, 4, 30))
    assert len(slices) == 37


def test_build_query():
    q = build_query('all:"AI safety"', datetime(2025, 4, 1), datetime(2025, 4, 30, 23, 59))
    assert q == '(all:"AI safety") AND submittedDate:[202504010000 TO 202504302359]'


def test_build_query_parenthesizes_or_group():
    q = build_query('all:"a" OR all:"b"', datetime(2025, 4, 1), datetime(2025, 4, 2))
    assert q.startswith('(') and q.endswith("]")
    assert q == '(all:"a" OR all:"b") AND submittedDate:[202504010000 TO 202504020000]'


ENTRY = {
    "id": "http://arxiv.org/abs/2504.14668v1",
    "title": "  A   Paper About\n AI Safety  ",
    "summary": "An abstract.\n  With newlines.",
    "published": "2025-04-20T16:18:06Z",
    "updated": "2025-04-20T16:18:06Z",
    "tags": [{"term": "cs.DC"}, {"term": "cs.AI"}],
    "arxiv_primary_category": {"term": "cs.DC"},
    "authors": [{"name": "Alice Zhang"}, {"name": "Bob Li"}],
    "links": [
        {"href": "https://arxiv.org/abs/2504.14668v1", "title": ""},
        {"href": "https://arxiv.org/pdf/2504.14668v1", "title": "pdf",
         "type": "application/pdf"},
    ],
    "arxiv_comment": "14 pages",
}


def test_entry_to_paper():
    p = _entry_to_paper(type("E", (), {"get": lambda self, k, d=None: ENTRY.get(k, d)})())
    assert p["arxiv_id"] == "2504.14668"
    assert p["version"] == 1
    assert p["title"] == "A Paper About AI Safety"
    assert p["authors_json"] == ["Alice Zhang", "Bob Li"]
    assert p["primary_category"] == "cs.DC"
    assert p["categories"] == ["cs.DC", "cs.AI"]
    assert p["pdf_url"] == "https://arxiv.org/pdf/2504.14668v1"
    assert p["abs_url"] == "https://arxiv.org/abs/2504.14668v1"
