"""RSS feed collector for news sources.

Collects from:
- GP Bullhound (M&A/tech deals)
- Sector-specific feeds (Finextra, Utility Dive, etc.)
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import feedparser
import httpx

from silvertree_newsletter.models.schemas import NewsItem

logger = logging.getLogger(__name__)

# Key RSS feeds for PE/M&A monitoring
RSS_FEEDS = {
    # M&A and PE focused - GP Bullhound RSS is inactive, use Perplexity search instead
    # "gp_bullhound": "https://www.gpbullhound.com/feed/",

    # FinTech / RegTech (for Fenergo)
    "finextra": "https://www.finextra.com/rss/headlines.aspx",
    "finextra_regulation": "https://www.finextra.com/rss/channel.aspx?channel=regulation",

    # General Tech M&A
    "techcrunch": "https://techcrunch.com/feed/",

    # Energy / Utilities (for Tally Group, Agility CIS)
    "utility_dive": "https://www.utilitydive.com/feeds/news/",

    # EdTech (for Thesis)
    "higher_ed_dive": "https://www.higheredive.com/feeds/news/",

    # MarTech (for SALESmanago)
    "martech": "https://martech.org/feed/",

    # Enterprise Software (for Orbus Software)
    "cio": "https://www.cio.com/feed/",
}


@dataclass
class RSSCollector:
    """Collects news from RSS feeds."""

    timeout_seconds: float = 30.0
    lookback_days: int = 7
    max_items_per_feed: int = 50
    _http_client: httpx.AsyncClient | None = field(init=False, default=None)

    async def collect_feed(self, feed_name: str, feed_url: str) -> list[NewsItem]:
        """Collect items from a single RSS feed."""
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.get(feed_url, follow_redirects=True)
                response.raise_for_status()
                content = response.text
        except Exception as e:
            logger.warning(f"Failed to fetch {feed_name}: {e}")
            return []

        try:
            feed = feedparser.parse(content)
        except Exception as e:
            logger.warning(f"Failed to parse {feed_name}: {e}")
            return []

        items: list[NewsItem] = []
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.lookback_days)

        for entry in feed.entries[:self.max_items_per_feed]:
            published = self._parse_date(entry)

            # Skip items older than lookback period (if date available)
            if published and published < cutoff:
                continue

            url = entry.get("link", "")
            if not url:
                continue

            title = entry.get("title", "").strip()
            summary = self._extract_summary(entry)

            items.append(NewsItem(
                id=self._hash_url(url),
                title=title or url,
                summary=summary,
                source=feed_name,
                source_url=url,
                published_date=published,
                related_companies=[],  # Will be filled by LLM relevance check
            ))

        logger.info(f"Collected {len(items)} items from {feed_name}")
        return items

    async def collect_all(
        self,
        feeds: dict[str, str] | None = None,
    ) -> dict[str, list[NewsItem]]:
        """Collect from all configured RSS feeds."""
        feeds = feeds or RSS_FEEDS
        results: dict[str, list[NewsItem]] = {}

        for feed_name, feed_url in feeds.items():
            items = await self.collect_feed(feed_name, feed_url)
            results[feed_name] = items

        total = sum(len(items) for items in results.values())
        logger.info(f"Collected {total} total items from {len(feeds)} feeds")
        return results

    async def collect_gp_bullhound(self) -> list[NewsItem]:
        """Collect specifically from GP Bullhound feed."""
        feed_url = RSS_FEEDS.get("gp_bullhound")
        if not feed_url:
            return []
        return await self.collect_feed("gp_bullhound", feed_url)

    def _parse_date(self, entry: Any) -> datetime | None:
        """Parse publication date from feed entry."""
        # Try published_parsed first
        if hasattr(entry, "published_parsed") and entry.published_parsed:
            try:
                return datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
            except (TypeError, ValueError):
                pass

        # Try updated_parsed
        if hasattr(entry, "updated_parsed") and entry.updated_parsed:
            try:
                return datetime(*entry.updated_parsed[:6], tzinfo=timezone.utc)
            except (TypeError, ValueError):
                pass

        return None

    def _extract_summary(self, entry: Any) -> str:
        """Extract summary/description from feed entry."""
        # Try summary first
        if hasattr(entry, "summary") and entry.summary:
            return self._clean_html(entry.summary)[:500]

        # Try description
        if hasattr(entry, "description") and entry.description:
            return self._clean_html(entry.description)[:500]

        # Try content
        if hasattr(entry, "content") and entry.content:
            for content in entry.content:
                if content.get("value"):
                    return self._clean_html(content["value"])[:500]

        return "No summary available."

    def _clean_html(self, text: str) -> str:
        """Basic HTML tag removal."""
        import re
        clean = re.sub(r"<[^>]+>", " ", text)
        clean = re.sub(r"\s+", " ", clean)
        return clean.strip()

    def _hash_url(self, url: str) -> str:
        return hashlib.sha256(url.encode("utf-8")).hexdigest()
