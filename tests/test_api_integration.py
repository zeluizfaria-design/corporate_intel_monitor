"""Integration tests for FastAPI endpoints using a temporary DuckDB database."""

import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from fastapi.testclient import TestClient

import api.main as api_main
import main as main_module
from collectors.base_collector import RawArticle
from storage.database import Database


class _NoopMaterialFactsRouter:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def collect(self, ticker: str, days_back: int = 30, **kwargs):
        if False:
            yield


class _NoopNewsCollector:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def collect(self, ticker: str):
        if False:
            yield


class _NoopBRInsiderCollector:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def collect(self, ticker: str, days_back: int = 30):
        if False:
            yield


class _HealthySocialCollector:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def collect(self, ticker: str):
        now = datetime.now(UTC)
        yield RawArticle(
            source="social/healthy",
            source_type="social",
            url=f"https://example.com/social/{ticker}",
            title=f"{ticker} healthy social signal",
            content="Collector available",
            published_at=now,
            company_ticker=ticker.upper(),
        )


class _FailingSocialCollector:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def collect(self, ticker: str):
        raise RuntimeError("simulated collector outage")
        if False:
            yield


class _HealthyBettingCollector:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def collect(self, ticker: str):
        now = datetime.now(UTC)
        yield RawArticle(
            source="betting/healthy",
            source_type="betting",
            url=f"https://example.com/betting/{ticker}",
            title=f"{ticker} healthy betting signal",
            content="Collector available",
            published_at=now,
            company_ticker=ticker.upper(),
        )


class _FailingBettingCollector:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def collect(self, ticker: str):
        raise RuntimeError("simulated betting collector outage")
        if False:
            yield


class _NoopSentimentAnalyzer:
    pass


class ApiIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp_root = Path("tests/.tmp")
        tmp_root.mkdir(parents=True, exist_ok=True)
        db_path = tmp_root / f"integration_{uuid4().hex}.duckdb"
        self.db_path = db_path
        self.test_db = Database(path=db_path)
        api_main._db = self.test_db
        api_main._collection_jobs.clear()
        self.client = TestClient(api_main.app)
        self._seed_articles()

    def tearDown(self) -> None:
        api_main._collection_jobs.clear()
        self.test_db._conn.close()
        if self.db_path.exists():
            self.db_path.unlink()

    def _seed_articles(self) -> None:
        now = datetime.now(UTC)

        self.test_db.upsert(
            {
                "id": f"article-{uuid4()}",
                "source": "reuters",
                "source_type": "news",
                "url": f"https://example.com/news/{uuid4()}",
                "title": "Earnings beat expectations",
                "content": "Quarterly results with positive surprise.",
                "published_at": now,
                "collected_at": now,
                "company_ticker": "NVDA",
                "company_name": "NVIDIA",
                "sentiment_label": "POSITIVE",
                "sentiment_score": 0.82,
                "sentiment_compound": 0.73,
                "event_type": "earnings",
                "raw_metadata": "{}",
            }
        )

        self.test_db.upsert(
            {
                "id": f"article-{uuid4()}",
                "source": "stocktwits/main",
                "source_type": "social",
                "url": f"https://example.com/social/{uuid4()}",
                "title": "Retail sentiment improving",
                "content": "Community sentiment trending positive.",
                "published_at": now,
                "collected_at": now,
                "company_ticker": "NVDA",
                "company_name": "NVIDIA",
                "sentiment_label": "NEUTRAL",
                "sentiment_score": 0.55,
                "sentiment_compound": 0.15,
                "event_type": "outro",
                "raw_metadata": "{}",
            }
        )

    def test_health(self) -> None:
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "ok")
        self.assertIn("timestamp", payload)

    def test_articles_and_summary(self) -> None:
        response = self.client.get("/articles/NVDA?days=7")
        self.assertEqual(response.status_code, 200)
        articles = response.json()
        self.assertEqual(len(articles), 2)

        summary = self.client.get("/articles/NVDA/summary?days=7")
        self.assertEqual(summary.status_code, 200)
        payload = summary.json()
        self.assertEqual(payload["ticker"], "NVDA")
        self.assertEqual(payload["total_articles"], 2)
        self.assertEqual(payload["sentiment"]["POSITIVE"], 1)

    def test_source_type_filter(self) -> None:
        response = self.client.get("/articles/NVDA?days=7&source_type=social")
        self.assertEqual(response.status_code, 200)
        articles = response.json()
        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0]["source_type"], "social")

    def test_social_endpoints(self) -> None:
        status = self.client.get("/social/sources")
        self.assertEqual(status.status_code, 200)
        sources = status.json()
        self.assertTrue(any(item["source"] == "stocktwits" for item in sources))

        summary = self.client.get("/social/NVDA/summary?days=7")
        self.assertEqual(summary.status_code, 200)
        payload = summary.json()
        self.assertEqual(payload["ticker"], "NVDA")
        self.assertEqual(payload["total_social_articles"], 1)
        self.assertIn("stocktwits", payload["sources"])

    def test_watchlist_crud(self) -> None:
        create = self.client.post("/watchlist", json={"ticker": "TSLA"})
        self.assertEqual(create.status_code, 200)

        duplicate = self.client.post("/watchlist", json={"ticker": "TSLA"})
        self.assertEqual(duplicate.status_code, 400)

        listed = self.client.get("/watchlist")
        self.assertEqual(listed.status_code, 200)
        tickers = {item["ticker"] for item in listed.json()}
        self.assertIn("TSLA", tickers)

        remove = self.client.delete("/watchlist/TSLA")
        self.assertEqual(remove.status_code, 200)

    def test_export_csv(self) -> None:
        response = self.client.get("/export/NVDA?days=7")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/csv", response.headers.get("content-type", ""))
        self.assertIn("id,source,source_type", response.text)

    def test_collect_job_status(self) -> None:
        with patch(
            "api.main._get_run_collection",
            return_value=AsyncMock(
                return_value={
                    "ticker": "NVDA",
                    "days_back": 7,
                    "saved_articles": 2,
                    "collector_failures": [],
                }
            ),
        ):
            start = self.client.post("/collect", json={"ticker": "NVDA", "days_back": 7})

        self.assertEqual(start.status_code, 200)
        payload = start.json()
        self.assertEqual(payload["status"], "started")
        self.assertEqual(payload["ticker"], "NVDA")
        self.assertIn("job_id", payload)

        status = self.client.get(f"/collect/{payload['job_id']}")
        self.assertEqual(status.status_code, 200)
        job = status.json()
        self.assertEqual(job["status"], "completed")
        self.assertEqual(job["ticker"], "NVDA")
        self.assertEqual(job["summary"]["saved_articles"], 2)

    def test_collect_job_status_completed_with_partial_failures(self) -> None:
        with patch(
            "api.main._get_run_collection",
            return_value=AsyncMock(
                return_value={
                    "ticker": "NVDA",
                    "days_back": 7,
                    "saved_articles": 2,
                    "collector_failures": [{"collector": "StockTwitsCollector", "error": "403 Forbidden"}],
                }
            ),
        ):
            start = self.client.post("/collect", json={"ticker": "NVDA", "days_back": 7})

        self.assertEqual(start.status_code, 200)
        payload = start.json()
        self.assertIn("job_id", payload)

        status = self.client.get(f"/collect/{payload['job_id']}")
        self.assertEqual(status.status_code, 200)
        job = status.json()
        self.assertEqual(job["status"], "completed")
        self.assertEqual(len(job["summary"]["collector_failures"]), 1)
        self.assertEqual(job["summary"]["collector_failures"][0]["collector"], "StockTwitsCollector")

    def test_collect_job_status_failed(self) -> None:
        with patch(
            "api.main._get_run_collection",
            return_value=AsyncMock(side_effect=RuntimeError("collector exploded")),
        ):
            start = self.client.post("/collect", json={"ticker": "NVDA", "days_back": 7})

        self.assertEqual(start.status_code, 200)
        payload = start.json()
        self.assertIn("job_id", payload)

        status = self.client.get(f"/collect/{payload['job_id']}")
        self.assertEqual(status.status_code, 200)
        job = status.json()
        self.assertEqual(job["status"], "failed")
        self.assertEqual(job["ticker"], "NVDA")
        self.assertEqual(job["error"], "collector exploded")

    def test_collect_job_not_found(self) -> None:
        status = self.client.get("/collect/job-does-not-exist")
        self.assertEqual(status.status_code, 404)
        self.assertIn("not found", status.json()["detail"].lower())

    def test_collect_trigger_cleans_stale_finished_jobs(self) -> None:
        stale_time = (datetime.now(UTC).replace(microsecond=0)).isoformat()
        api_main._collection_jobs["old-job"] = {
            "job_id": "old-job",
            "status": "failed",
            "ticker": "NVDA",
            "days_back": 7,
            "queued_at": "2026-01-01T00:00:00+00:00",
            "started_at": "2026-01-01T00:00:01+00:00",
            "finished_at": "2026-01-01T00:00:02+00:00",
            "error": "timeout",
            "summary": None,
        }
        api_main._collection_jobs["recent-job"] = {
            "job_id": "recent-job",
            "status": "running",
            "ticker": "NVDA",
            "days_back": 7,
            "queued_at": stale_time,
            "started_at": stale_time,
            "finished_at": None,
            "error": None,
            "summary": None,
        }

        with patch(
            "api.main._get_run_collection",
            return_value=AsyncMock(
                return_value={
                    "ticker": "NVDA",
                    "days_back": 7,
                    "saved_articles": 2,
                    "collector_failures": [],
                }
            ),
        ):
            response = self.client.post("/collect", json={"ticker": "NVDA", "days_back": 7})

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("old-job", api_main._collection_jobs)
        self.assertIn("recent-job", api_main._collection_jobs)

    def test_collect_job_status_completed_with_real_partial_collector_outage(self) -> None:
        with (
            patch("api.main._get_run_collection", return_value=main_module.run_collection),
            patch("main.MaterialFactsRouter", return_value=_NoopMaterialFactsRouter()),
            patch("main.NewsCollector", return_value=_NoopNewsCollector()),
            patch(
                "main.build_social_collectors",
                return_value=[_HealthySocialCollector(), _FailingSocialCollector()],
            ),
            patch("main.build_betting_collectors", return_value=[]),
            patch("main.CVMInsiderCollector", return_value=_NoopBRInsiderCollector()),
            patch("main.SentimentAnalyzer", return_value=_NoopSentimentAnalyzer()),
            patch("main.detect_market", return_value="BR"),
            patch("main._save", return_value=True),
        ):
            start = self.client.post("/collect", json={"ticker": "PETR4", "days_back": 7})

        self.assertEqual(start.status_code, 200)
        payload = start.json()
        self.assertIn("job_id", payload)

        status = self.client.get(f"/collect/{payload['job_id']}")
        self.assertEqual(status.status_code, 200)
        job = status.json()
        self.assertEqual(job["status"], "completed")
        self.assertEqual(job["summary"]["saved_articles"], 1)
        self.assertEqual(len(job["summary"]["collector_failures"]), 1)
        self.assertEqual(
            job["summary"]["collector_failures"][0]["collector"],
            "_FailingSocialCollector",
        )
        self.assertIn(
            "simulated collector outage",
            job["summary"]["collector_failures"][0]["error"],
        )

    def test_collect_job_status_completed_with_real_partial_betting_outage(self) -> None:
        with (
            patch("api.main._get_run_collection", return_value=main_module.run_collection),
            patch("main.MaterialFactsRouter", return_value=_NoopMaterialFactsRouter()),
            patch("main.NewsCollector", return_value=_NoopNewsCollector()),
            patch("main.build_social_collectors", return_value=[]),
            patch(
                "main.build_betting_collectors",
                return_value=[_HealthyBettingCollector(), _FailingBettingCollector()],
            ),
            patch("main.CVMInsiderCollector", return_value=_NoopBRInsiderCollector()),
            patch("main.SentimentAnalyzer", return_value=_NoopSentimentAnalyzer()),
            patch("main.detect_market", return_value="BR"),
            patch("main._save", return_value=True),
        ):
            start = self.client.post("/collect", json={"ticker": "PETR4", "days_back": 7})

        self.assertEqual(start.status_code, 200)
        payload = start.json()
        self.assertIn("job_id", payload)

        status = self.client.get(f"/collect/{payload['job_id']}")
        self.assertEqual(status.status_code, 200)
        job = status.json()
        self.assertEqual(job["status"], "completed")
        self.assertEqual(job["summary"]["saved_articles"], 1)
        self.assertEqual(len(job["summary"]["collector_failures"]), 1)
        self.assertEqual(
            job["summary"]["collector_failures"][0]["collector"],
            "_FailingBettingCollector",
        )
        self.assertIn(
            "simulated betting collector outage",
            job["summary"]["collector_failures"][0]["error"],
        )

    def test_collect_job_status_completed_with_multiple_partial_outages(self) -> None:
        with (
            patch("api.main._get_run_collection", return_value=main_module.run_collection),
            patch("main.MaterialFactsRouter", return_value=_NoopMaterialFactsRouter()),
            patch("main.NewsCollector", return_value=_NoopNewsCollector()),
            patch(
                "main.build_social_collectors",
                return_value=[_HealthySocialCollector(), _FailingSocialCollector()],
            ),
            patch(
                "main.build_betting_collectors",
                return_value=[_HealthyBettingCollector(), _FailingBettingCollector()],
            ),
            patch("main.CVMInsiderCollector", return_value=_NoopBRInsiderCollector()),
            patch("main.SentimentAnalyzer", return_value=_NoopSentimentAnalyzer()),
            patch("main.detect_market", return_value="BR"),
            patch("main._save", return_value=True),
        ):
            start = self.client.post("/collect", json={"ticker": "PETR4", "days_back": 7})

        self.assertEqual(start.status_code, 200)
        payload = start.json()
        self.assertIn("job_id", payload)

        status = self.client.get(f"/collect/{payload['job_id']}")
        self.assertEqual(status.status_code, 200)
        job = status.json()
        self.assertEqual(job["status"], "completed")
        self.assertEqual(job["summary"]["saved_articles"], 2)
        self.assertEqual(len(job["summary"]["collector_failures"]), 2)

        failures = {entry["collector"]: entry["error"] for entry in job["summary"]["collector_failures"]}
        self.assertIn("_FailingSocialCollector", failures)
        self.assertIn("_FailingBettingCollector", failures)
        self.assertIn("simulated collector outage", failures["_FailingSocialCollector"])
        self.assertIn("simulated betting collector outage", failures["_FailingBettingCollector"])

    def test_collect_job_status_completed_with_total_secondary_outage(self) -> None:
        with (
            patch("api.main._get_run_collection", return_value=main_module.run_collection),
            patch("main.MaterialFactsRouter", return_value=_NoopMaterialFactsRouter()),
            patch("main.NewsCollector", return_value=_NoopNewsCollector()),
            patch("main.build_social_collectors", return_value=[_FailingSocialCollector()]),
            patch("main.build_betting_collectors", return_value=[_FailingBettingCollector()]),
            patch("main.CVMInsiderCollector", return_value=_NoopBRInsiderCollector()),
            patch("main.SentimentAnalyzer", return_value=_NoopSentimentAnalyzer()),
            patch("main.detect_market", return_value="BR"),
            patch("main._save", return_value=True),
        ):
            start = self.client.post("/collect", json={"ticker": "PETR4", "days_back": 7})

        self.assertEqual(start.status_code, 200)
        payload = start.json()
        self.assertIn("job_id", payload)

        status = self.client.get(f"/collect/{payload['job_id']}")
        self.assertEqual(status.status_code, 200)
        job = status.json()
        self.assertEqual(job["status"], "completed")
        self.assertEqual(job["summary"]["saved_articles"], 0)
        self.assertEqual(len(job["summary"]["collector_failures"]), 2)

        failures = {entry["collector"]: entry["error"] for entry in job["summary"]["collector_failures"]}
        self.assertIn("_FailingSocialCollector", failures)
        self.assertIn("_FailingBettingCollector", failures)


if __name__ == "__main__":
    unittest.main()
