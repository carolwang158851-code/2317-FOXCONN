from __future__ import annotations

import csv
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import owner_publish_csv_v2 as publisher
import warroom_market_activity_updater as twse
import p1008_app_server as app


class TwseNonTradingReadinessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.run = self.root / "runtime/daily_price_incremental/TEST"
        self.receipts = self.run / "receipts"
        self.receipts.mkdir(parents=True)
        self.days = ["2026-10-01", "2026-10-02"]
        self.formal()
        self.evidence()
        self.csv("data/macro_snapshot.csv", ["Date", "VIX"], [["2026-10-02", "15"]])
        self.csv("staging/2026-10-04/macro_snapshot_candidate.csv", ["Date", "VIX"], [["2026-10-04", "16"]])
        self.csv("staging/2026-10-04/2317_daily_price_candidate.csv", twse.PRICE_CANDIDATE_FIELDS,
                 [["2026-10-04", "200", "2026Q2", "100", "2.000", "PUBLIC_MARKET_DATA", "STAGING_CANDIDATE"]])
        self.dry = {
            "candidateDate": "2026-10-04",
            "generatedFiles": ["staging/2026-10-04/2317_daily_price_candidate.csv", "staging/2026-10-04/macro_snapshot_candidate.csv"],
            "inputSources": {"stock_price": "DATA_MISSING", "vix": "OFFICIAL"},
            "sourceMeta": {"stock_price": {"dataset": "daily", "requiredForFormal": True}, "vix": {"dataset": "macro", "requiredForFormal": True}},
            "validationChecks": [{"dataset": "daily", "status": "FAIL"}, {"dataset": "macro", "status": "PASS"}],
            "criticalMissingFields": ["Close"],
        }

    def csv(self, relative, fields, rows):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle, lineterminator="\n")
            writer.writerow(fields)
            writer.writerows(rows)

    def formal(self, price_days=None, market_days=None):
        self.csv(publisher.DAILY_TARGET, twse.PRICE_CANDIDATE_FIELDS,
                 [[day, "200", "2026Q2", "100", "2.000", "OFFICIAL_TWSE_A1", "OK"] for day in (self.days if price_days is None else price_days)])
        self.csv(publisher.MARKET_ACTIVITY_TARGET, twse.FORMAL_FIELDS,
                 [[day, "2317", "1000", "200000", "100", twse.source_url("2026-10"), "2026-10"] for day in (self.days if market_days is None else market_days)])
        entries = [{"path": rel, "sha256": publisher.sha256_file(self.root / rel)} for rel in (publisher.DAILY_TARGET, publisher.MARKET_ACTIVITY_TARGET)]
        entries.append({"path": publisher.MACRO_TARGET})
        (self.root / publisher.MANIFEST_PATH).write_text(json.dumps({"authoritativeFiles": entries}), encoding="utf-8")

    def evidence(self, observed="2026-10-04T10:00:00Z"):
        buffer = io.StringIO(newline="")
        writer = csv.writer(buffer, lineterminator="\n")
        writer.writerow(["2026-10 2317 test"])
        writer.writerow(["date", "volume", "value", "open", "high", "low", "close", "change", "count"])
        for day in self.days:
            writer.writerow(["115/10/" + day[-2:], "1000", "200000", "200", "200", "200", "200", "0", "100"])
        raw = self.receipts / "2026-10.twse.raw.csv"
        raw.write_bytes(buffer.getvalue().encode("cp950"))
        receipt = self.receipts / "2026-10.receipt.json"
        receipt.write_text(json.dumps({"status": "SUCCESS", "http_status": 200, "request_url": twse.source_url("2026-10"),
                                       "raw_artifact_sha256": publisher.sha256_file(raw), "fetched_at_utc": observed}), encoding="utf-8")
        status = {"run_id": "TEST", "run_dir": str(self.run), "receipt_paths": [str(receipt)],
                  "status": "NO_NEW_DAILY_PRICE", "exit_code": 0, "actionable": False}
        for path in (self.run / "RESULT.json", self.root / publisher.DAILY_PRICE_STATUS_PATH):
            path.write_text(json.dumps(status), encoding="utf-8")
        market_run = self.root / "runtime/market_activity_incremental/TEST"
        market_receipts = market_run / "receipts"
        market_receipts.mkdir(parents=True, exist_ok=True)
        shutil.copy2(raw, market_receipts / raw.name)
        shutil.copy2(receipt, market_receipts / receipt.name)
        market_status = {**status, "run_dir": str(market_run), "receipt_paths": [str(market_receipts / receipt.name)], "status": "NO_NEW_MARKET_ACTIVITY"}
        for path in (market_run / "RESULT.json", self.root / publisher.MARKET_ACTIVITY_STATUS_PATH):
            path.write_text(json.dumps(market_status), encoding="utf-8")

    def readiness(self, selected=None):
        return publisher.build_publish_readiness(self.root, self.dry, selected)

    def assert_closed(self):
        result = self.readiness()
        self.assertEqual(result["twseRequirement"]["dailyPriceRequirement"], "NOT_APPLICABLE_MARKET_CLOSED")
        self.assertEqual(result["twseRequirement"]["marketState"], "TWSE_NON_TRADING_DAY")
        self.assertEqual(result["twseRequirement"]["latestValidatedTradingDate"], "2026-10-02")
        self.assertEqual(result["score"], 100)
        self.assertEqual(result["blockers"], [])
        self.assertEqual(result["sourceTotal"], 1)
        self.assertEqual(result["applicableValidationCheckCount"], 1)
        self.assertEqual(result["validationChecks"][0]["status"], "NOT_APPLICABLE_MARKET_CLOSED")
        return result

    def test_sunday_current_no_penalty(self):
        self.assert_closed()

    def test_saturday_current_no_penalty(self):
        self.dry["candidateDate"] = "2026-10-03"
        self.assert_closed()

    def test_weekday_receipt_proven_holiday(self):
        # Synthetic TWSE closure fixture: weekday absent only after market close.
        self.dry["candidateDate"] = "2026-10-05"
        self.evidence("2026-10-05T10:00:00Z")
        self.assert_closed()

    def test_stale_daily_remains_fail_closed(self):
        self.formal(price_days=self.days[:1])
        result = self.readiness()
        self.assertFalse(result["allowed"])
        self.assertEqual(result["twseRequirement"]["dailyPriceRequirement"], "FAIL")
        self.assertIn("missing_price=['2026-10-02']", " ".join(result["blockers"]))

    def test_stale_market_remains_visible(self):
        self.formal(market_days=self.days[:1])
        self.assertIn("missing_market_activity=['2026-10-02']", " ".join(self.readiness()["blockers"]))

    def trading_day(self):
        self.days.append("2026-10-05")
        self.evidence("2026-10-05T10:00:00Z")
        self.dry["candidateDate"] = "2026-10-05"

    def test_trading_day_missing_candidate(self):
        self.trading_day()
        result = self.readiness()
        self.assertFalse(result["allowed"])
        self.assertEqual(result["notApplicableDatasets"], [])

    def test_trading_day_undeclared_missing_candidate(self):
        self.trading_day()
        self.dry["generatedFiles"] = self.dry["generatedFiles"][1:]
        self.assertIn("Trading-day Daily Price candidate missing", " ".join(self.readiness()["blockers"]))

    def test_trading_day_invalid_date_candidate(self):
        self.trading_day()
        self.csv(self.dry["generatedFiles"][0], twse.PRICE_CANDIDATE_FIELDS,
                 [["invalid-date", "200", "2026Q2", "100", "2.000", "OFFICIAL_TWSE_A1", "STAGING_CANDIDATE"]])
        self.assertIn("Candidate inspection failed", " ".join(self.readiness()["blockers"]))

    def test_next_trading_day_reactivates_without_reset(self):
        self.assert_closed()
        self.trading_day()
        self.assertEqual(self.readiness()["twseRequirement"]["dailyPriceRequirement"], "APPLICABLE")

    def bytes_before(self):
        return {str(path.relative_to(self.root)): path.read_bytes() for path in (self.root / "data").iterdir()}

    def test_no_synthetic_price_row(self):
        before = (self.root / publisher.DAILY_TARGET).read_bytes()
        self.assert_closed()
        self.assertEqual((self.root / publisher.DAILY_TARGET).read_bytes(), before)
        self.assertNotIn(b"2026-10-04", before)

    def test_no_synthetic_market_row(self):
        before = (self.root / publisher.MARKET_ACTIVITY_TARGET).read_bytes()
        self.assert_closed()
        self.assertEqual((self.root / publisher.MARKET_ACTIVITY_TARGET).read_bytes(), before)
        self.assertNotIn(b"2026-10-04", before)

    def test_no_formal_carry_forward_or_manifest_write(self):
        before = self.bytes_before()
        self.assert_closed()
        self.assertEqual(self.bytes_before(), before)

    def test_independent_macro_failure_not_hidden(self):
        self.dry["inputSources"]["vix"] = "DATA_MISSING"
        self.dry["criticalMissingFields"].append("VIX")
        result = self.readiness()
        self.assertFalse(result["allowed"])
        self.assertIn("Missing required sources: vix", result["blockers"])
        self.assertIn("Missing critical fields: VIX", result["blockers"])

    def test_dataset_scoped_macro_publish_unaffected(self):
        self.formal(price_days=self.days[:1])
        result = self.readiness(("macro",))
        self.assertTrue(result["allowed"])
        self.assertEqual(result["selectedTargets"], [publisher.MACRO_TARGET])

    def test_independent_failure_survives_absent_other_candidates(self):
        self.dry["generatedFiles"] = self.dry["generatedFiles"][:1]
        self.dry["criticalMissingFields"].append("VIX")
        result = self.readiness()
        self.assertFalse(result["allowed"])
        self.assertIn("Missing critical fields: VIX", result["blockers"])

    def test_fx_candidate_failure_remains_independent(self):
        self.csv(publisher.FX_TREND_TARGET, ["Date", "SourceTier", "Actionable"], [["2026-10-02", "OFFICIAL", "false"]])
        candidate = "staging/2026-10-04/fx_trend_observations_candidate.csv"
        self.csv(candidate, ["Date", "SourceTier", "Actionable"], [["2026-10-04", "OFFICIAL", "true"]])
        self.dry["generatedFiles"].append(candidate)
        result = self.readiness()
        self.assertFalse(result["allowed"])
        self.assertIn("Actionable=false", " ".join(result["blockers"]))

    def test_closed_daily_market_scope_is_no_action_not_passed_candidate(self):
        result = self.readiness(("daily", "market_activity"))
        self.assertTrue(result["noActionRequired"])
        self.assertEqual(result["publishFiles"], [])
        self.assertIsNone(result["candidateFileScore"])
        self.assertIsNone(result["validationScore"])

    def test_old_receipt_cannot_waive_next_weekday(self):
        self.dry["candidateDate"] = "2026-10-05"
        self.assertEqual(self.readiness()["notApplicableDatasets"], [])

    def test_intraday_absence_is_not_holiday(self):
        self.dry["candidateDate"] = "2026-10-05"
        self.evidence("2026-10-05T01:00:00Z")
        self.assertEqual(self.readiness()["notApplicableDatasets"], [])

    def test_weekend_alone_never_waives_checks(self):
        (self.root / publisher.DAILY_PRICE_STATUS_PATH).unlink()
        self.assertFalse(self.readiness()["allowed"])
        self.assertEqual(self.readiness()["notApplicableDatasets"], [])

    def test_tampered_receipt_fails_closed(self):
        with (self.receipts / "2026-10.twse.raw.csv").open("ab") as handle:
            handle.write(b"tampered")
        self.assertFalse(self.readiness()["allowed"])

    def test_latest_market_run_failure_is_not_bypassed(self):
        path = self.root / publisher.MARKET_ACTIVITY_STATUS_PATH
        status = json.loads(path.read_text(encoding="utf-8"))
        status.update(status="FAILED", exit_code=20)
        path.write_text(json.dumps(status), encoding="utf-8")
        self.assertFalse(self.readiness()["allowed"])
        self.assertIn("Latest Market Activity run", " ".join(self.readiness()["blockers"]))

    def test_owner_news_gate_independent(self):
        review = {"candidatePending": False, "formalPublishBlocked": False,
                  "newsScan": {"ownerReviewRequired": True}, "eventReview": {"ownerAckRequired": True}}
        manager = object.__new__(app.P1008JobManager)
        state = {"latestReport": {"health": {"status": "PASS"}}, "status": "SUCCEEDED"}
        self.assertEqual(manager.launcher_gate_status(review, state)["code"], "OWNER_REVIEW_REQUIRED")

    def test_review_uses_effective_files_and_retains_closed_explanation(self):
        path = self.root / "staging/2026-10-04/DRY_RUN.json"
        path.write_text(json.dumps(self.dry), encoding="utf-8")
        manager = app.P1008JobManager(self.root)
        with mock.patch.object(manager, "latest_report_status", return_value={}), mock.patch.object(manager, "pending_owner_review", return_value={}):
            review = manager.review_package("2026-10-04")
        self.assertEqual(review["status"], "READY")
        self.assertEqual(review["marketContext"]["status"], "TWSE_NON_TRADING_DAY")
        self.assertIn("台股例行休市", review["marketContext"]["zh"])
        self.assertIsNone(review["dailyRow"])
        self.assertNotIn(self.dry["generatedFiles"][0], review["generatedFiles"])
        self.assertEqual(review["readiness"]["blockers"], [])


if __name__ == "__main__":
    unittest.main()
