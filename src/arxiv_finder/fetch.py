from __future__ import annotations

import re
import time
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

import feedparser
import httpx

from .config import SearchConfig

_ARXIV_ID_VERSION_RE = re.compile(r"(\d{4}\.\d{4,5})(?:v(\d+))?$")
_OLD_ID_RE = re.compile(r"([a-z-]+(?:\.[A-Z]{2})?/\d{7})(?:v(\d+))?$")

ProgressCb = Callable[[int, int, str], None]


def parse_arxiv_id(abs_or_pdf_url_or_id: str) -> tuple[str, int] | None:
    s = abs_or_pdf_url_or_id.strip()
    s = re.sub(r"^https?://arxiv\.org/(?:abs|pdf)/", "", s)
    s = s.split("?")[0].rstrip("/")
    for pattern in (_ARXIV_ID_VERSION_RE, _OLD_ID_RE):
        m = pattern.fullmatch(s)
        if m:
            return m.group(1), int(m.group(2) or 1)
    return None


class Throttle:
    def __init__(self, min_interval_sec: float) -> None:
        self.min_interval = min_interval_sec
        self._last: float = 0.0

    def wait(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self._last = time.monotonic()


def month_slices(start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
    slices: list[tuple[datetime, datetime]] = []
    cur = start
    while cur <= end:
        nxt_month = (cur.replace(day=28) + timedelta(days=4)).replace(day=1)
        slice_end = min(nxt_month - timedelta(microseconds=1), end)
        slices.append((cur, slice_end))
        cur = nxt_month
    return slices


def _date_window(start: datetime, end: datetime) -> str:
    return f"[{start.strftime('%Y%m%d%H%M')} TO {end.strftime('%Y%m%d%H%M')}]"


def build_query(clause_query: str, start: datetime, end: datetime) -> str:
    return f"({clause_query}) AND submittedDate:{_date_window(start, end)}"


def _retry_after_sec(resp: httpx.Response) -> float:
    """Parse a ``Retry-After`` header value in seconds (0.0 if absent/invalid)."""
    hdr = resp.headers.get("Retry-After")
    if not hdr:
        return 0.0
    try:
        return float(hdr)
    except (TypeError, ValueError):
        return 0.0


def fetch_slice(
    client: httpx.Client,
    base_url: str,
    query: str,
    page_size: int,
    throttle: Throttle,
    max_retries: int = 8,
    max_results: int | None = None,
) -> tuple[list[dict[str, Any]], int]:
    entries: list[dict[str, Any]] = []
    start_idx = 0
    total: int | None = None
    while True:
        throttle.wait()
        params: dict[str, str | int] = {
            "search_query": query,
            "start": start_idx,
            "max_results": page_size,
            "sortBy": "submittedDate",
            "sortOrder": "ascending",
        }
        text = ""
        retry_after = 0.0
        for attempt in range(max_retries):
            try:
                resp = client.get(base_url, params=params)
                if resp.status_code == 429:
                    retry_after = _retry_after_sec(resp)
                    raise httpx.HTTPStatusError(
                        "rate limited", request=resp.request, response=resp
                    )
                resp.raise_for_status()
                text = resp.text
                break
            except httpx.HTTPError:
                if attempt == max_retries - 1:
                    raise
                backoff = min(120.0, 10.0 * (attempt + 1))
                # Honor arXiv's Retry-After hint (when present) so we don't
                # retry sooner than the server asked; still capped at 120s.
                time.sleep(min(120.0, max(backoff, retry_after)))
        feed = feedparser.parse(text)
        if total is None:
            total = int(getattr(feed.feed, "opensearch_totalresults", 0) or 0)
        batch = feed.entries
        for e in batch:
            entries.append(_entry_to_paper(e))
        start_idx += len(batch)
        if max_results is not None and len(entries) >= max_results:
            break
        if not batch or start_idx >= (total or 0):
            break
    return entries, total or 0


def _entry_to_paper(e: Any) -> dict[str, Any]:
    arxiv_id_url = e.get("id", "")
    parsed = parse_arxiv_id(arxiv_id_url)
    arxiv_id, version = parsed if parsed else (arxiv_id_url, 1)
    tags = e.get("tags", [])
    categories = [t.get("term", "") for t in tags if t.get("term")]
    primary = e.get("arxiv_primary_category", {}).get("term") or (categories[0] if categories else "")
    authors = [a.get("name", "") for a in e.get("authors", [])]
    links = e.get("links", [])
    pdf_url = ""
    for link in links:
        if link.get("title") == "pdf" or (link.get("type") == "application/pdf"):
            pdf_url = link.get("href", "")
    if not pdf_url:
        pdf_url = f"https://arxiv.org/pdf/{arxiv_id}v{version}"
    return {
        "arxiv_id": arxiv_id,
        "version": version,
        "title": re.sub(r"\s+", " ", e.get("title", "")).strip(),
        "abstract": re.sub(r"\s+", " ", e.get("summary", "")).strip(),
        "authors_json": authors,
        "primary_category": primary,
        "categories": categories,
        "submitted": e.get("published", ""),
        "updated": e.get("updated", ""),
        "abs_url": f"https://arxiv.org/abs/{arxiv_id}v{version}",
        "pdf_url": pdf_url,
        "comments": e.get("arxiv_comment", ""),
    }


def fetch_papers(
    cfg: SearchConfig,
    start: datetime,
    end: datetime,
    progress: ProgressCb | None = None,
    should_stop: Callable[[], bool] | None = None,
    start_unit: int = 0,
    unit_done: Callable[[int], None] | None = None,
) -> list[dict[str, Any]]:
    throttle = Throttle(cfg.min_interval_sec)
    results: dict[str, dict[str, Any]] = {}
    query_hits: dict[str, set[str]] = {}
    start_date = start.strftime("%Y-%m-%d")
    end_date = end.strftime("%Y-%m-%d")
    slices = month_slices(start, end)
    total_units = len(slices) * len(cfg.clauses)
    unit = 0
    stopped = False
    with httpx.Client(timeout=60.0) as client:
        for s_start, s_end in slices:
            if stopped:
                break
            for clause in cfg.clauses:
                unit += 1
                if should_stop and should_stop():
                    stopped = True
                    break
                if unit <= start_unit:
                    continue
                query = build_query(clause.query, s_start, s_end)
                entries, total = fetch_slice(
                    client, cfg.arxiv_base_url, query, cfg.page_size, throttle,
                    max_results=cfg.max_slice_results,
                )
                kept = 0
                for paper in entries:
                    pub = paper["submitted"][:10]
                    if not (start_date <= pub <= end_date):
                        continue
                    kept += 1
                    aid = paper["arxiv_id"]
                    query_hits.setdefault(aid, set()).add(clause.name)
                    if aid not in results or paper["version"] > results[aid]["version"]:
                        results[aid] = paper
                if progress:
                    note = ""
                    if len(entries) >= cfg.max_slice_results and total > len(entries):
                        note = f" (showing first {cfg.max_slice_results} of {total})"
                    month = s_start.strftime("%b %Y")
                    msg = f"Searched \"{clause.name}\" for {month}: found {kept} papers{note}"
                    progress(unit, total_units, msg)
                if unit_done:
                    unit_done(unit)
    out = []
    for aid, paper in results.items():
        paper["queries"] = sorted(query_hits.get(aid, set()))
        out.append(paper)
    return out
