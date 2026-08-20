from __future__ import annotations

import time
from pathlib import Path

import httpx
import pymupdf

from .db import pdf_cache_dir

_USER_AGENT = "arxiv-paper-finder/0.1 (research dataset tool)"


def pdf_path(arxiv_id: str) -> Path:
    return pdf_cache_dir() / f"{arxiv_id.replace('/', '_')}.pdf"


def ensure_pdf(arxiv_id: str, pdf_url: str, retries: int = 3) -> Path:
    path = pdf_path(arxiv_id)
    if path.exists() and path.stat().st_size > 0:
        return path
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            with httpx.Client(
                timeout=120.0, follow_redirects=True, headers={"User-Agent": _USER_AGENT}
            ) as client:
                resp = client.get(pdf_url)
                resp.raise_for_status()
                content = resp.content
            if len(content) < 1024 or not content.startswith(b"%PDF"):
                raise ValueError(f"response does not look like a PDF ({len(content)} bytes)")
            tmp = path.with_suffix(".part")
            tmp.write_bytes(content)
            tmp.replace(path)
            return path
        except (httpx.HTTPError, ValueError, OSError) as exc:
            last_err = exc
            if attempt < retries - 1:
                time.sleep(3.0 * (attempt + 1))
    raise RuntimeError(f"failed to download PDF for {arxiv_id}: {last_err}")


def open_pdf(path: Path) -> pymupdf.Document:
    return pymupdf.open(path)


def first_page_text(path: Path, max_chars: int) -> str:
    with open_pdf(path) as doc:
        if doc.page_count == 0:
            return ""
        text = doc[0].get_text("text")
    return text[:max_chars]


def full_text(path: Path, page_limit: int, max_chars: int) -> str:
    with open_pdf(path) as doc:
        parts: list[str] = []
        total = 0
        for i in range(min(doc.page_count, page_limit)):
            text = doc[i].get_text("text")
            parts.append(text)
            total += len(text)
            if total >= max_chars:
                break
    return "\n".join(parts)[:max_chars]


def first_page_png(path: Path, zoom: float = 2.0) -> bytes:
    with open_pdf(path) as doc:
        if doc.page_count == 0:
            raise ValueError("empty PDF")
        page = doc[0]
        pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom))
        return pix.tobytes("png")
