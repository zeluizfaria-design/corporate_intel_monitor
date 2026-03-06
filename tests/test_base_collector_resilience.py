"""Unit tests for retry/backoff behavior in BaseCollector._get."""

import unittest
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import httpx

from collectors.base_collector import BaseCollector, RawArticle


class _DummyCollector(BaseCollector):
    async def collect(self, ticker: str):
        if False:
            yield RawArticle(
                source="dummy",
                source_type="news",
                url="https://example.com",
                title="dummy",
                content="dummy",
                published_at=datetime.now(UTC),
            )


class BaseCollectorResilienceTests(unittest.IsolatedAsyncioTestCase):
    async def test_requires_async_context(self):
        collector = _DummyCollector(rate_limit_rps=1000)
        with self.assertRaises(RuntimeError):
            await collector._get("https://example.com")

    async def test_retries_429_then_succeeds(self):
        collector = _DummyCollector(rate_limit_rps=1000)
        req = httpx.Request("GET", "https://example.com")
        ok = httpx.Response(200, request=req, text="ok")
        too_many = httpx.Response(429, request=req, headers={"Retry-After": "0"})

        async with collector:
            collector._client.get = AsyncMock(
                side_effect=[
                    httpx.HTTPStatusError("429", request=req, response=too_many),
                    ok,
                ]
            )
            with patch("collectors.base_collector.asyncio.sleep", new=AsyncMock()):
                response = await collector._get("https://example.com")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(collector._client.get.await_count, 2)

    async def test_retries_timeout_then_succeeds(self):
        collector = _DummyCollector(rate_limit_rps=1000)
        req = httpx.Request("GET", "https://example.com")
        ok = httpx.Response(200, request=req, text="ok")

        async with collector:
            collector._client.get = AsyncMock(
                side_effect=[
                    httpx.TimeoutException("timeout"),
                    ok,
                ]
            )
            with patch("collectors.base_collector.asyncio.sleep", new=AsyncMock()):
                response = await collector._get("https://example.com")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(collector._client.get.await_count, 2)

    async def test_does_not_retry_404(self):
        collector = _DummyCollector(rate_limit_rps=1000)
        req = httpx.Request("GET", "https://example.com")
        not_found = httpx.Response(404, request=req)

        async with collector:
            collector._client.get = AsyncMock(
                side_effect=httpx.HTTPStatusError("404", request=req, response=not_found)
            )
            with patch("collectors.base_collector.asyncio.sleep", new=AsyncMock()):
                with self.assertRaises(httpx.HTTPStatusError):
                    await collector._get("https://example.com")

        self.assertEqual(collector._client.get.await_count, 1)

    async def test_raises_after_three_retryable_http_errors(self):
        collector = _DummyCollector(rate_limit_rps=1000)
        req = httpx.Request("GET", "https://example.com")
        unavailable = httpx.Response(503, request=req)

        async with collector:
            collector._client.get = AsyncMock(
                side_effect=httpx.HTTPStatusError("503", request=req, response=unavailable)
            )
            with patch("collectors.base_collector.asyncio.sleep", new=AsyncMock()):
                with self.assertRaises(RuntimeError):
                    await collector._get("https://example.com")

        self.assertEqual(collector._client.get.await_count, 3)


if __name__ == "__main__":
    unittest.main()
