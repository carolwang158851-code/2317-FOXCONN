from __future__ import annotations

import sys
import unittest
from argparse import Namespace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
TOOLS = PACKAGE_ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import warroom_news_scanner_v2 as scanner  # noqa: E402


class NewsCrawlerGovernanceTests(unittest.TestCase):
    def args(self) -> Namespace:
        return Namespace(
            no_network=False,
            timeout_seconds=5,
            browser_fallback=True,
            _crawler_state={"sources": {}},
            _crawler_now_utc=datetime(2026, 7, 19, 0, 0, tzinfo=timezone.utc),
        )

    @staticmethod
    def ctee_source() -> dict:
        return {
            "sourceId": scanner.CTEE_SOURCE_ID,
            "sourceName": "工商時報",
            "sourceTier": "MEDIA",
            "enabled": True,
            "requiresNetwork": True,
            "connectorStatus": "APPROVED",
            "url": "https://www.ctee.com.tw/",
            "urls": [f"https://www.ctee.com.tw/page-{index}" for index in range(8)],
            "discoveryMode": ["HTML"],
        }

    def test_public_error_taxonomy(self) -> None:
        self.assertEqual(scanner.classify_fetch_error("HTTP Error 403"), "HTTP_403_POLICY_BLOCKED")
        self.assertEqual(scanner.classify_fetch_error("request timed out"), "TIMEOUT_TRANSIENT")

    def test_ctee_first_403_stops_all_remaining_urls_and_creates_candidate(self) -> None:
        failed = scanner.FetchResult(
            ok=False,
            url="https://www.ctee.com.tw/",
            final_url="https://www.ctee.com.tw/",
            status="HTTP_403_POLICY_BLOCKED",
            content_type="text/html",
            text="",
            error="HTTP Error 403",
            fetch_mode="PYTHON",
            duration_ms=1,
        )
        args = self.args()
        with mock.patch.object(scanner, "fetch_url", return_value=failed) as fetch, mock.patch.object(
            scanner, "browser_fetch_url"
        ) as browser:
            _, health = scanner.scan_source(self.ctee_source(), {}, args)
        self.assertEqual(fetch.call_count, 1)
        browser.assert_not_called()
        self.assertEqual(health["status"], "HTTP_403_POLICY_BLOCKED")
        self.assertEqual(health["severity"], "WARNING")
        self.assertEqual(health["webSearchCandidate"]["domain"], "ctee.com.tw")
        self.assertEqual(health["webSearchCandidate"]["status"], "CANDIDATE_ONLY_NOT_EXECUTED")

    def test_ctee_cooldown_prevents_direct_fetch_for_24_hours(self) -> None:
        args = self.args()
        args._crawler_state["sources"][scanner.CTEE_SOURCE_ID] = {
            "cooldownUntilUtc": (args._crawler_now_utc + timedelta(hours=12)).isoformat()
        }
        with mock.patch.object(scanner, "fetch_url") as fetch:
            _, health = scanner.scan_source(self.ctee_source(), {}, args)
        fetch.assert_not_called()
        self.assertEqual(health["status"], "HTTP_403_POLICY_BLOCKED")

    def test_azure_weekly_cadence_skips_until_due(self) -> None:
        args = self.args()
        args._crawler_state["sources"]["microsoft_azure_blog"] = {
            "lastSuccessfulAtUtc": (args._crawler_now_utc - timedelta(days=2)).isoformat()
        }
        source = {
            "sourceId": "microsoft_azure_blog",
            "sourceName": "Azure",
            "sourceTier": "OFFICIAL",
            "enabled": True,
            "requiresNetwork": True,
            "connectorStatus": "APPROVED",
            "scanCadence": "WEEKLY",
            "url": "https://azure.microsoft.com/en-us/blog/",
        }
        with mock.patch.object(scanner, "fetch_url") as fetch:
            _, health = scanner.scan_source(source, {}, args)
        fetch.assert_not_called()
        self.assertEqual(health["status"], "SKIPPED_CADENCE")

    def test_success_without_relevant_event_does_not_reduce_health(self) -> None:
        summary = scanner.build_network_summary(
            [
                {
                    "enabled": True,
                    "requiresNetwork": True,
                    "status": "SUCCESS_NO_RELEVANT_EVENT",
                    "fetchOk": 1,
                    "fetchFailed": 0,
                }
            ]
        )
        self.assertEqual(summary["succeeded"], 1)
        self.assertEqual(summary["failed"], 0)
        self.assertEqual(summary["successRate"], 100.0)

    def test_timeout_is_warning_but_real_transient_failure(self) -> None:
        summary = scanner.build_network_summary(
            [
                {
                    "enabled": True,
                    "requiresNetwork": True,
                    "status": "TIMEOUT_TRANSIENT",
                    "fetchOk": 0,
                    "fetchFailed": 1,
                }
            ]
        )
        self.assertEqual(summary["warnings"], 1)
        self.assertEqual(summary["failed"], 1)

    def test_policy_block_does_not_depress_crawler_health_rate(self) -> None:
        summary = scanner.build_network_summary(
            [
                {
                    "enabled": True,
                    "requiresNetwork": True,
                    "status": "SUCCESS_NO_RELEVANT_EVENT",
                    "fetchOk": 1,
                    "fetchFailed": 0,
                },
                {
                    "enabled": True,
                    "requiresNetwork": True,
                    "status": "HTTP_403_POLICY_BLOCKED",
                    "fetchOk": 0,
                    "fetchFailed": 0,
                },
            ]
        )
        self.assertEqual(summary["warnings"], 1)
        self.assertEqual(summary["failed"], 0)
        self.assertEqual(summary["successRate"], 100.0)


if __name__ == "__main__":
    unittest.main()
