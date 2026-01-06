"""Date filtering utilities for news items."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from silvertree_newsletter.models.schemas import NewsItem


def filter_recent_items(
    items: list[NewsItem],
    lookback_days: int,
    keep_undated: bool,
    now: datetime | None = None,
) -> list[NewsItem]:
    """Filter items to a lookback window, optionally keeping undated items."""
    if now is None:
        now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=lookback_days)

    filtered: list[NewsItem] = []
    for item in items:
        if item.published_date is None:
            if keep_undated:
                filtered.append(item)
            continue
        if item.published_date >= cutoff:
            filtered.append(item)

    return filtered
