"""Tests for API background task resilience and logging."""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import api.main as api_main


class ApiBackgroundTaskTests(unittest.IsolatedAsyncioTestCase):
    async def test_run_collection_bg_logs_summary_on_success(self) -> None:
        mock_logger = MagicMock()
        with (
            patch("main.run_collection", new=AsyncMock(
                return_value={
                    "ticker": "NVDA",
                    "days_back": 7,
                    "saved_articles": 3,
                    "collector_failures": [{"collector": "XCollector", "error": "boom"}],
                }
            )),
            patch("api.main.logging.getLogger", return_value=mock_logger),
        ):
            await api_main._run_collection_bg("nvda", 7)

        mock_logger.info.assert_called_once()
        info_args = mock_logger.info.call_args[0]
        self.assertIn("NVDA", info_args)

    async def test_run_collection_bg_logs_exception_on_failure(self) -> None:
        mock_logger = MagicMock()
        with (
            patch("main.run_collection", new=AsyncMock(side_effect=RuntimeError("boom"))),
            patch("api.main.logging.getLogger", return_value=mock_logger),
        ):
            await api_main._run_collection_bg("nvda", 7)

        mock_logger.exception.assert_called_once()


if __name__ == "__main__":
    unittest.main()
