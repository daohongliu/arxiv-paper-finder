from __future__ import annotations

from .config import ChinaFilterConfig


def author_flags(author_entries: list[dict]) -> list[bool]:
    return [e.get("mainland_china") == "yes" for e in author_entries]


def passes_china_filter(
    author_entries: list[dict], cfg: ChinaFilterConfig
) -> tuple[bool, str]:
    flags = author_flags(author_entries)
    n = len(flags)
    count = sum(flags)
    if n == 0:
        return False, "no authors extracted"
    fraction = count / n
    reason: list[str] = [f"{count}/{n} mainland-affiliated authors ({fraction:.0%})"]

    if cfg.min_count >= 1 and count >= cfg.min_count and fraction >= cfg.min_fraction:
        return True, "; ".join(reason)

    if cfg.anchor_rule:
        last_n = (
            cfg.anchor_last_n_small
            if n <= cfg.anchor_small_author_cutoff
            else cfg.anchor_last_n_large
        )
        anchors = flags[-last_n:] if last_n > 0 else []
        if any(anchors):
            reason.append(f"anchor author among last {last_n} is mainland-affiliated")
            return True, "; ".join(reason)

    return False, "; ".join(reason)
