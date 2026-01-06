"""Fetch and extract readable text from source URLs."""

from __future__ import annotations

import asyncio
import html as html_lib
import logging
import re
import time
from dataclasses import dataclass, field

import httpx

logger = logging.getLogger(__name__)


class AsyncRateLimiter:
    """Simple async rate limiter using a minimum interval between requests."""

    def __init__(self, requests_per_minute: int) -> None:
        self.min_interval = 60.0 / requests_per_minute if requests_per_minute else 0.0
        self._lock = asyncio.Lock()
        self._last_request = 0.0

    async def wait(self) -> None:
        if self.min_interval <= 0:
            return
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_request
            if elapsed < self.min_interval:
                await asyncio.sleep(self.min_interval - elapsed)
            self._last_request = time.monotonic()


@dataclass
class ContentFetcher:
    """Fetch full-text content from web sources with light extraction."""

    timeout_seconds: float = 20.0
    max_chars: int = 4000
    min_chars: int = 200
    requests_per_minute: int = 60
    max_concurrency: int = 6
    user_agent: str = "SilverTreeNewsletterBot/1.0"
    _limiter: AsyncRateLimiter = field(init=False)
    _semaphore: asyncio.Semaphore = field(init=False)

    def __post_init__(self) -> None:
        self._limiter = AsyncRateLimiter(self.requests_per_minute)
        self._semaphore = asyncio.Semaphore(self.max_concurrency)

    async def fetch_many(self, items: list[tuple[str, str]]) -> tuple[dict[str, str], list[str]]:
        """Fetch text for (item_id, url) tuples."""
        if not items:
            return {}, []

        headers = {
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml",
        }

        results: dict[str, str] = {}
        errors: list[str] = []

        async with httpx.AsyncClient(timeout=self.timeout_seconds, headers=headers, follow_redirects=True) as client:
            tasks = [
                asyncio.create_task(self._fetch_one(item_id, url, client))
                for item_id, url in items
            ]

            for task in asyncio.as_completed(tasks):
                item_id, text, error = await task
                if text:
                    results[item_id] = text
                if error:
                    errors.append(error)

        return results, errors

    async def _fetch_one(
        self,
        item_id: str,
        url: str,
        client: httpx.AsyncClient,
    ) -> tuple[str, str | None, str | None]:
        async with self._semaphore:
            await self._limiter.wait()

            try:
                response = await client.get(url)
                response.raise_for_status()
            except Exception as exc:
                logger.debug(f"Content fetch failed for {url}: {exc}")
                return item_id, None, f"{url}: {exc}"

            content_type = response.headers.get("content-type", "")
            if "text/html" not in content_type and "text/" not in content_type:
                return item_id, None, f"{url}: unsupported content type {content_type}"

            text = _extract_text(response.text)
            if not text or len(text) < self.min_chars:
                return item_id, None, f"{url}: extracted text too short"

            if len(text) > self.max_chars:
                text = text[: self.max_chars]

            return item_id, text, None


def _extract_text(html: str) -> str:
    cleaned = re.sub(r"(?is)<(script|style|noscript|header|footer|nav).*?>.*?</\1>", " ", html)

    candidate = None
    for tag in ("article", "main"):
        match = re.search(rf"(?is)<{tag}[^>]*>(.*?)</{tag}>", cleaned)
        if match:
            candidate = match.group(1)
            break

    content = candidate or cleaned
    content = re.sub(r"(?is)<[^>]+>", " ", content)
    content = html_lib.unescape(content)
    content = re.sub(r"\s+", " ", content)
    return content.strip()
