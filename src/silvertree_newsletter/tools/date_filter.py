"""Date filtering utilities for news items."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from silvertree_newsletter.models.schemas import NewsItem

logger = logging.getLogger(__name__)


def filter_recent_items(
    items: list[NewsItem],
    lookback_days: int,
    keep_undated: bool,
    max_age_days: int | None = None,
    now: datetime | None = None,
) -> list[NewsItem]:
    """Filter items to a lookback window, optionally keeping undated items.

    Args:
        items: List of news items to filter
        lookback_days: Primary lookback window in days
        keep_undated: Whether to keep items without a published date
        max_age_days: Hard cutoff - reject anything older than this (optional)
        now: Reference time for filtering (defaults to current UTC time)
    """
    if now is None:
        now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=lookback_days)
    hard_cutoff = now - timedelta(days=max_age_days) if max_age_days else None

    filtered: list[NewsItem] = []
    undated_count = 0
    too_old_count = 0

    for item in items:
        if item.published_date is None:
            undated_count += 1
            if keep_undated:
                filtered.append(item)
            continue

        # Check hard cutoff first (if set)
        if hard_cutoff and item.published_date < hard_cutoff:
            too_old_count += 1
            continue

        if item.published_date >= cutoff:
            filtered.append(item)

    if undated_count > 0:
        logger.info(
            "Date filter: rejected %d undated items (keep_undated=%s)",
            undated_count if not keep_undated else 0,
            keep_undated,
        )
    if too_old_count > 0:
        logger.info(
            "Date filter: rejected %d items older than %d days",
            too_old_count,
            max_age_days,
        )

    return filtered
