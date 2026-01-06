"""Perplexity Sonar search client with rate limiting.

Rate limits (sonar model):
- Tier 0-1: 50 RPM
- Tier 2: 500 RPM
- Tier 3+: 1000+ RPM

Best practices from Perplexity docs:
- Respect rate-limit headers
- Implement exponential backoff on 429
- Use caching for repeated queries
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlparse

import httpx

from silvertree_newsletter.models.schemas import NewsItem, SearchQuery
from silvertree_newsletter.tools.date_filter import filter_recent_items

logger = logging.getLogger(__name__)


@dataclass
class PerplexityClient:
    """Perplexity API client with rate limiting and exponential backoff.

    Implements Perplexity best practices:
    - Rate limiting to stay within RPM limits
    - Exponential backoff on 429 errors
    - Respects rate-limit headers from responses
    """

    api_key: str
    model: str = "sonar"
    timeout_seconds: float = 30.0
    max_items: int = 8
    recency_filter: str | None = "week"
    lookback_days: int = 7
    keep_undated: bool = True
    requests_per_minute: int = 50  # Tier 0/1 default
    max_retries: int = 3
    base_delay: float = 1.2  # Delay between requests (60/50 = 1.2s for 50 RPM)
    _last_request_time: float = field(init=False, default=0.0)

    def __post_init__(self) -> None:
        if self.requests_per_minute > 0:
            self.base_delay = max(self.base_delay, 60.0 / self.requests_per_minute)

    async def _wait_for_rate_limit(self) -> None:
        """Wait to respect rate limit between requests."""
        import time

        now = time.monotonic()
        elapsed = now - self._last_request_time
        if elapsed < self.base_delay:
            await asyncio.sleep(self.base_delay - elapsed)
        self._last_request_time = time.monotonic()

    async def search(
        self,
        query: SearchQuery,
        domain_filter: list[str] | None = None,
    ) -> list[NewsItem]:
        """Execute a search with rate limiting and exponential backoff.

        Args:
            query: The search query to execute
            domain_filter: Optional list of domains to restrict results to
        """
        query_text = query.query_text
        if query_text.startswith("site:"):
            parts = query_text.split(" ", 1)
            if len(parts) > 1:
                domain = parts[0].replace("site:", "")
                query_text = parts[1]
                if domain_filter is None:
                    domain_filter = [domain]
                elif domain not in domain_filter:
                    domain_filter = [domain] + domain_filter

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": "Provide recent news with citations for each claim.",
                },
                {"role": "user", "content": query_text},
            ],
            "temperature": 0.2,
        }
        if self.recency_filter:
            payload["search_recency_filter"] = self.recency_filter
        payload["return_citations"] = True

        if domain_filter:
            payload["search_domain_filter"] = domain_filter

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        # Rate limiting and retry with exponential backoff
        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            await self._wait_for_rate_limit()

            try:
                async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                    response = await client.post(
                        "https://api.perplexity.ai/chat/completions",
                        json=payload,
                        headers=headers,
                    )

                    # Check for rate limit from headers
                    if response.status_code == 429:
                        retry_after = response.headers.get("retry-after")
                        wait_time = float(retry_after) if retry_after else (2 ** attempt)
                        logger.warning(
                            f"Rate limited (429), waiting {wait_time}s (attempt {attempt + 1})"
                        )
                        await asyncio.sleep(wait_time)
                        continue

                    response.raise_for_status()
                    data = response.json()

                    items = self._extract_items(data, query)
                    return filter_recent_items(items, self.lookback_days, self.keep_undated)

            except httpx.HTTPStatusError as e:
                last_error = e
                if e.response.status_code == 429:
                    wait_time = 2 ** attempt
                    logger.warning(f"Rate limit error, backing off {wait_time}s")
                    await asyncio.sleep(wait_time)
                elif e.response.status_code in (401, 403):
                    # Auth errors - don't retry
                    raise
                else:
                    # Other errors - retry with backoff
                    wait_time = 2 ** attempt
                    logger.warning(f"HTTP error {e.response.status_code}, retrying in {wait_time}s")
                    await asyncio.sleep(wait_time)

            except (httpx.TimeoutException, httpx.ConnectError) as e:
                last_error = e
                wait_time = 2 ** attempt
                logger.warning(f"Connection error, retrying in {wait_time}s: {e}")
                await asyncio.sleep(wait_time)

        # All retries exhausted
        if last_error:
            raise last_error
        return []

    async def search_batch(
        self,
        queries: list[SearchQuery],
        on_progress: Any | None = None,
    ) -> list[tuple[SearchQuery, list[NewsItem], str | None]]:
        """Execute multiple searches sequentially with rate limiting.

        Args:
            queries: List of search queries to execute
            on_progress: Optional callback(completed, total) for progress updates

        Returns:
            List of (query, results) tuples
        """
        results: list[tuple[SearchQuery, list[NewsItem], str | None]] = []
        total = len(queries)

        for i, query in enumerate(queries):
            try:
                items = await self.search(query)
                results.append((query, items, None))
            except Exception as e:
                logger.error(f"Search failed for query {query.id}: {e}")
                results.append((query, [], str(e)))

            if on_progress:
                on_progress(i + 1, total)

        return results

    def _extract_items(self, data: dict[str, Any], query: SearchQuery) -> list[NewsItem]:
        results: list[NewsItem] = []
        related = [query.related_company] if query.related_company else []
        search_results = data.get("search_results") or []

        if search_results:
            for result in search_results[: self.max_items]:
                url = (result.get("url") or result.get("link") or "").strip()
                if not url:
                    continue
                title = (result.get("title") or result.get("name") or url).strip()
                summary = (
                    result.get("snippet")
                    or result.get("description")
                    or "Summary unavailable."
                )
                published_date = _parse_datetime(
                    result.get("published_date")
                    or result.get("published_at")
                    or result.get("date")
                )
                source_name = result.get("source") or _domain_from_url(url)
                results.append(
                    NewsItem(
                        id=_hash_url(url),
                        title=title,
                        summary=summary,
                        source=source_name or "perplexity",
                        source_url=url,
                        published_date=published_date,
                        related_companies=related,
                    )
                )
            return results

        citations = data.get("citations") or []
        content = (
            (data.get("choices") or [{}])[0]
            .get("message", {})
            .get("content", "")
            .strip()
        )
        summary = content or "Summary unavailable."

        for url in citations[: self.max_items]:
            if not isinstance(url, str):
                continue
            cleaned = url.strip()
            if not cleaned:
                continue
            results.append(
                NewsItem(
                    id=_hash_url(cleaned),
                    title=_domain_from_url(cleaned) or cleaned,
                    summary=summary,
                    source=_domain_from_url(cleaned) or "perplexity",
                    source_url=cleaned,
                    published_date=None,
                    related_companies=related,
                )
            )

        return results


def _hash_url(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def _domain_from_url(url: str) -> str:
    try:
        return urlparse(url).netloc
    except ValueError:
        return ""


def _parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
            return _ensure_utc(dt)
        except ValueError:
            pass
        try:
            dt = parsedate_to_datetime(text)
            return _ensure_utc(dt)
        except (TypeError, ValueError):
            return None
    return None


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
