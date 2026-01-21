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

from silvertree_newsletter.models.schemas import (
    NewsItem,
    SearchContextSize,
    SearchQuery,
    UserLocation,
)
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
    recency_filter: str | None = "day"  # Client-level default, query-level takes precedence
    lookback_days: int = 7
    keep_undated: bool = False  # Reject items without dates by default
    max_age_days: int | None = 14  # Hard cutoff for old articles
    requests_per_minute: int = 50  # Tier 0/1 default
    max_retries: int = 6  # More retries with exponential backoff (1s, 2s, 4s, 8s, 16s, 32s)
    base_delay: float = 1.2  # Delay between requests (60/50 = 1.2s for 50 RPM)
    # New Perplexity API features
    search_context_size: SearchContextSize = SearchContextSize.MEDIUM
    default_location: UserLocation | None = None
    domain_denylist: list[str] | None = None  # Default domains to exclude
    use_date_filters: bool = True  # Enable search_after_date filters
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
            domain_filter: Optional override for domain filter (query.domain_filter takes precedence)
        """
        query_text = query.query_text

        # Build domain filter: query-level > parameter > client default denylist
        effective_domain_filter: list[str] = []
        if query.domain_filter:
            effective_domain_filter.extend(query.domain_filter)
        elif domain_filter:
            effective_domain_filter.extend(domain_filter)

        # Add denylist domains with "-" prefix
        denylist = query.domain_denylist or self.domain_denylist
        if denylist:
            for domain in denylist:
                denied = f"-{domain}" if not domain.startswith("-") else domain
                if denied not in effective_domain_filter:
                    effective_domain_filter.append(denied)

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

        # Date filters logic: Specific dates take precedence over recency
        has_date_filters = self.use_date_filters and (
            query.search_after_date or query.search_before_date
        )

        # Only apply recency filter if no specific date filters are used
        if not has_date_filters:
            recency = query.recency_filter if query.recency_filter else self.recency_filter
            if recency:
                payload["search_recency_filter"] = recency

        if effective_domain_filter:
            payload["search_domain_filter"] = effective_domain_filter

        # Add date filters if enabled
        if self.use_date_filters:
            if query.search_after_date:
                payload["search_after_date_filter"] = query.search_after_date
            if query.search_before_date:
                payload["search_before_date_filter"] = query.search_before_date

        # Build web_search_options
        web_search_options: dict[str, Any] = {}

        # Search context size: query-level > client-level
        context_size = query.search_context_size or self.search_context_size
        if context_size:
            web_search_options["search_context_size"] = context_size.value

        # User location: query-level > client-level default
        location = query.user_location or self.default_location
        if location:
            loc_dict: dict[str, Any] = {"country": location.country}
            if location.region:
                loc_dict["region"] = location.region
            if location.city:
                loc_dict["city"] = location.city
            if location.latitude is not None:
                loc_dict["latitude"] = location.latitude
            if location.longitude is not None:
                loc_dict["longitude"] = location.longitude
            web_search_options["user_location"] = loc_dict

        if web_search_options:
            payload["web_search_options"] = web_search_options

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
                    return filter_recent_items(
                        items, self.lookback_days, self.keep_undated, self.max_age_days
                    )

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
        max_concurrent: int = 10,
    ) -> list[tuple[SearchQuery, list[NewsItem], str | None]]:
        """Execute multiple searches in parallel with rate limiting.

        Args:
            queries: List of search queries to execute
            on_progress: Optional callback(completed, total) for progress updates
            max_concurrent: Maximum number of concurrent requests (default: 10)

        Returns:
            List of (query, results) tuples in original order
        """
        results: list[tuple[SearchQuery, list[NewsItem], str | None] | None] = [None] * len(queries)
        total = len(queries)
        completed = 0

        # Semaphore to limit concurrent requests
        semaphore = asyncio.Semaphore(max_concurrent)

        async def search_with_semaphore(index: int, query: SearchQuery):
            nonlocal completed
            async with semaphore:
                try:
                    items = await self.search(query)
                    results[index] = (query, items, None)
                except Exception as e:
                    logger.error(f"Search failed for query {query.id}: {e}")
                    results[index] = (query, [], str(e))

                completed += 1
                if on_progress:
                    on_progress(completed, total)

        # Execute all searches in parallel with semaphore control
        await asyncio.gather(
            *[search_with_semaphore(i, query) for i, query in enumerate(queries)],
            return_exceptions=True
        )

        return [r for r in results if r is not None]

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
