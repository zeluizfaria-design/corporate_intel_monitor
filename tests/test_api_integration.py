"""Integration tests for FastAPI endpoints using a temporary DuckDB database."""

import unittest
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

import api.main as api_main
from storage.database import Database


class ApiIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp_root = Path("tests/.tmp")
        tmp_root.mkdir(parents=True, exist_ok=True)
        db_path = tmp_root / f"integration_{uuid4().hex}.duckdb"
        self.db_path = db_path
        self.test_db = Database(path=db_path)
        api_main._db = self.test_db
        self.client = TestClient(api_main.app)
        self._seed_articles()

    def tearDown(self) -> None:
        self.test_db._conn.close()
        if self.db_path.exists():
            self.db_path.unlink()

    def _seed_articles(self) -> None:
        now = datetime.utcnow()

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


if __name__ == "__main__":
    unittest.main()
