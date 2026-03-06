"""Classe base para todos os coletores."""
import asyncio
import httpx
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import AsyncIterator
import logging

logger = logging.getLogger(__name__)


@dataclass
class RawArticle:
    source: str
    source_type: str          # 'fato_relevante' | 'news' | 'social' | 'betting'
    url: str
    title: str
    content: str
    published_at: datetime
    company_ticker: str | None = None
    company_name: str | None = None
    raw_metadata: dict = field(default_factory=dict)
    collected_at: datetime = field(default_factory=datetime.utcnow)


class BaseCollector(ABC):
    """Coletor base com rate limiting e retry automático."""

    def __init__(self, rate_limit_rps: float = 1.0):
        self._delay = 1.0 / rate_limit_rps
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self):
        self._client = httpx.AsyncClient(
            timeout=30,
            headers={"User-Agent": "CorporateIntelMonitor/1.0 (research)"},
            follow_redirects=True,
        )
        return self

    async def __aexit__(self, *args):
        if self._client:
            await self._client.aclose()

    async def _get(self, url: str, **kwargs) -> httpx.Response:
        if self._client is None:
            raise RuntimeError("HTTP client not initialized. Use 'async with' for collectors.")

        await asyncio.sleep(self._delay)
        for attempt in range(3):
            try:
                resp = await self._client.get(url, **kwargs)
                resp.raise_for_status()
                return resp
            except httpx.HTTPStatusError as e:
                status = e.response.status_code
                if status in {429, 500, 502, 503, 504}:
                    retry_after = e.response.headers.get("Retry-After")
                    try:
                        backoff = float(retry_after) if retry_after else (2 ** attempt * 2)
                    except ValueError:
                        backoff = 2 ** attempt * 2
                    await asyncio.sleep(backoff)
                else:
                    raise
            except (httpx.TimeoutException, httpx.TransportError):
                if attempt == 2:
                    raise
                await asyncio.sleep(2 ** attempt)
        raise RuntimeError(f"Failed after 3 attempts: {url}")

    @abstractmethod
    async def collect(self, ticker: str) -> AsyncIterator[RawArticle]:
        ...
