"""Tests for API background task resilience, logging, and job retention."""

import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import api.main as api_main


class ApiBackgroundTaskTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        api_main._collection_jobs.clear()

    def tearDown(self) -> None:
        api_main._collection_jobs.clear()

    async def test_run_collection_bg_logs_summary_on_success(self) -> None:
        api_main._collection_jobs["job-1"] = {
            "job_id": "job-1",
            "status": "queued",
            "ticker": "NVDA",
            "days_back": 7,
            "queued_at": "2026-03-06T00:00:00+00:00",
            "started_at": None,
            "finished_at": None,
            "error": None,
            "summary": None,
        }
        mock_logger = MagicMock()
        with (
            patch(
                "api.main._get_run_collection",
                return_value=AsyncMock(
                    return_value={
                        "ticker": "NVDA",
                        "days_back": 7,
                        "saved_articles": 3,
                        "collector_failures": [{"collector": "XCollector", "error": "boom"}],
                    }
                ),
            ),
            patch("api.main.logging.getLogger", return_value=mock_logger),
        ):
            await api_main._run_collection_bg("job-1", "nvda", 7)

        mock_logger.info.assert_called_once()
        info_args = mock_logger.info.call_args[0]
        self.assertIn("NVDA", info_args)
        self.assertEqual(api_main._collection_jobs["job-1"]["status"], "completed")
        self.assertIsNotNone(api_main._collection_jobs["job-1"]["started_at"])
        self.assertIsNotNone(api_main._collection_jobs["job-1"]["finished_at"])
        self.assertIsNotNone(api_main._collection_jobs["job-1"]["summary"])

    async def test_run_collection_bg_logs_exception_on_failure(self) -> None:
        api_main._collection_jobs["job-2"] = {
            "job_id": "job-2",
            "status": "queued",
            "ticker": "NVDA",
            "days_back": 7,
            "queued_at": "2026-03-06T00:00:00+00:00",
            "started_at": None,
            "finished_at": None,
            "error": None,
            "summary": None,
        }
        mock_logger = MagicMock()
        with (
            patch(
                "api.main._get_run_collection",
                return_value=AsyncMock(side_effect=RuntimeError("boom")),
            ),
            patch("api.main.logging.getLogger", return_value=mock_logger),
        ):
            await api_main._run_collection_bg("job-2", "nvda", 7)

        mock_logger.exception.assert_called_once()
        self.assertEqual(api_main._collection_jobs["job-2"]["status"], "failed")
        self.assertEqual(api_main._collection_jobs["job-2"]["error"], "boom")
        self.assertIsNotNone(api_main._collection_jobs["job-2"]["finished_at"])

    async def test_run_collection_bg_without_registered_job(self) -> None:
        mock_logger = MagicMock()
        with (
            patch(
                "api.main._get_run_collection",
                return_value=AsyncMock(
                    return_value={
                        "ticker": "NVDA",
                        "days_back": 7,
                        "saved_articles": 1,
                        "collector_failures": [],
                    }
                ),
            ),
            patch("api.main.logging.getLogger", return_value=mock_logger),
        ):
            await api_main._run_collection_bg("missing-job", "nvda", 7)

        self.assertEqual(api_main._collection_jobs, {})
        mock_logger.info.assert_called_once()
        info_args = mock_logger.info.call_args[0]
        self.assertIn("NVDA", info_args)

    async def test_cleanup_collection_jobs_removes_old_finished_jobs(self) -> None:
        now = datetime.now(UTC)
        recent_finished = (now - timedelta(hours=1)).isoformat()
        stale_finished = (now - timedelta(hours=30)).isoformat()

        api_main._collection_jobs.update(
            {
                "job-running": {
                    "job_id": "job-running",
                    "status": "running",
                    "ticker": "NVDA",
                    "days_back": 7,
                    "queued_at": stale_finished,
                    "started_at": stale_finished,
                    "finished_at": None,
                    "error": None,
                    "summary": None,
                },
                "job-recent-completed": {
                    "job_id": "job-recent-completed",
                    "status": "completed",
                    "ticker": "NVDA",
                    "days_back": 7,
                    "queued_at": recent_finished,
                    "started_at": recent_finished,
                    "finished_at": recent_finished,
                    "error": None,
                    "summary": {"saved_articles": 1, "collector_failures": []},
                },
                "job-stale-failed": {
                    "job_id": "job-stale-failed",
                    "status": "failed",
                    "ticker": "NVDA",
                    "days_back": 7,
                    "queued_at": stale_finished,
                    "started_at": stale_finished,
                    "finished_at": stale_finished,
                    "error": "boom",
                    "summary": None,
                },
            }
        )

        api_main._cleanup_collection_jobs()

        self.assertIn("job-running", api_main._collection_jobs)
        self.assertIn("job-recent-completed", api_main._collection_jobs)
        self.assertNotIn("job-stale-failed", api_main._collection_jobs)


if __name__ == "__main__":
    unittest.main()
