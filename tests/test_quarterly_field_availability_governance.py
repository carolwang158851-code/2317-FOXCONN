from __future__ import annotations

import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "modules" / "p1008_research_plugin" / "src"
import sys

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from p1008_research_plugin.quarterly_authority import (
    QuarterlyAuthorityError,
    latest_available_roic_row,
    quarterly_metric_availability,
    validate_quarterly_authority_row,
)


SPEC = importlib.util.spec_from_file_location(
    "quarterly_owner_promotion", ROOT / "tools" / "quarterly_owner_promotion.py"
)
assert SPEC and SPEC.loader
PROMOTION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PROMOTION)

FETCHER_SPEC = importlib.util.spec_from_file_location(
    "warroom_data_fetcher_v2", ROOT / "tools" / "warroom_data_fetcher_v2.py"
)
assert FETCHER_SPEC and FETCHER_SPEC.loader
FETCHER = importlib.util.module_from_spec(FETCHER_SPEC)
FETCHER_SPEC.loader.exec_module(FETCHER)


class QuarterlyFieldAvailabilityGovernanceTests(unittest.TestCase):
    def setUp(self) -> None:
        scratch = ROOT / "runtime" / "report_production" / "test_scratch"
        scratch.mkdir(parents=True, exist_ok=True)
        self.root = scratch / f"quarterly-field-availability-{uuid4().hex}"
        self.root.mkdir(parents=False, exist_ok=False)
        (self.root / "data").mkdir(parents=True)
        contract_target = self.root / PROMOTION.CONTRACT_RELATIVE_PATH
        contract_target.parent.mkdir(parents=True)
        shutil.copyfile(ROOT / PROMOTION.MASTER_RELATIVE, self.root / PROMOTION.MASTER_RELATIVE)
        shutil.copyfile(ROOT / PROMOTION.MANIFEST_RELATIVE, self.root / PROMOTION.MANIFEST_RELATIVE)
        shutil.copyfile(ROOT / PROMOTION.CONTRACT_RELATIVE_PATH, contract_target)

    def tearDown(self) -> None:
        # OneDrive may set directory ReadOnly attributes during the test. The
        # focused validation runner removes these exact scratch roots afterward.
        pass

    def test_valid_partial_q2_row_passes_and_exposes_split_latest_quarters(self) -> None:
        proposal = PROMOTION.proposed_authority(self.root)
        q2 = proposal["rows"][-1]
        validate_quarterly_authority_row(q2)
        availability = quarterly_metric_availability(proposal["rows"])
        self.assertEqual(availability["latestValidRoeQuarter"], "2026Q2")
        self.assertEqual(availability["latestValidRoicQuarter"], "2026Q1")
        self.assertEqual(availability["roe"]["values"][-1], "12.61")
        self.assertEqual(availability["roic"]["values"][-1], "12.57")
        self.assertEqual(availability["unavailableRoicQuarters"], ["2026Q2"])

    def test_missing_roic_status_with_blanks_fails_closed(self) -> None:
        row = PROMOTION.build_q2_row(list(PROMOTION.read_master((self.root / PROMOTION.MASTER_RELATIVE).read_bytes())[1]))
        row["ROIC_Status"] = ""
        with self.assertRaisesRegex(QuarterlyAuthorityError, "ROIC_STATUS_INVALID_OR_MISSING"):
            validate_quarterly_authority_row(row)

    def test_numeric_roic_with_unavailable_status_fails_closed(self) -> None:
        fields = PROMOTION.read_master((self.root / PROMOTION.MASTER_RELATIVE).read_bytes())[1]
        row = PROMOTION.build_q2_row(fields)
        row["ROIC_Precise_Pct"] = "16.46"
        with self.assertRaisesRegex(QuarterlyAuthorityError, "REQUIRES_BLANK_FIELDS"):
            validate_quarterly_authority_row(row)

    def test_bare_na_is_invalid(self) -> None:
        fields = PROMOTION.read_master((self.root / PROMOTION.MASTER_RELATIVE).read_bytes())[1]
        row = PROMOTION.build_q2_row(fields)
        row["ROIC_Precise_Pct"] = "N/A"
        with self.assertRaisesRegex(QuarterlyAuthorityError, "BARE_UNAVAILABLE_TOKEN_INVALID"):
            validate_quarterly_authority_row(row)

    def test_available_roic_consumer_uses_q1_without_decimal_on_q2_blank(self) -> None:
        proposal = PROMOTION.proposed_authority(self.root)
        selected = latest_available_roic_row(proposal["rows"])
        self.assertEqual(selected["Quarter"], "2026Q1")
        self.assertEqual(selected["ROIC_Precise_Pct"], "12.57")

    def test_owner_gated_atomic_manifest_and_master_update(self) -> None:
        review = self.root / "review"
        PROMOTION.create_owner_review(self.root, review)
        result = PROMOTION.apply_owner_promotion(self.root, review, PROMOTION.APPROVAL_TOKEN)
        self.assertEqual(result["status"], "PROMOTED")
        receipt = json.loads((review / "promotion_receipt.json").read_text(encoding="utf-8"))
        self.assertEqual(
            PROMOTION.sha256_bytes((self.root / PROMOTION.MASTER_RELATIVE).read_bytes()),
            receipt["authority"]["master"]["afterSha256"],
        )
        self.assertEqual(
            PROMOTION.sha256_bytes((self.root / PROMOTION.MANIFEST_RELATIVE).read_bytes()),
            receipt["authority"]["manifest"]["afterSha256"],
        )

    def test_formal_master_verifier_accepts_governed_partial_q2(self) -> None:
        review = self.root / "review"
        PROMOTION.create_owner_review(self.root, review)
        PROMOTION.apply_owner_promotion(self.root, review, PROMOTION.APPROVAL_TOKEN)
        verified = FETCHER.verify_master_authority(self.root)
        self.assertEqual(verified["quarter"], "2026Q2")
        self.assertEqual(verified["bvps"], 136.02)

    def test_partial_failure_rolls_back_exact_bytes(self) -> None:
        review = self.root / "review"
        PROMOTION.create_owner_review(self.root, review)
        before_master = (self.root / PROMOTION.MASTER_RELATIVE).read_bytes()
        before_manifest = (self.root / PROMOTION.MANIFEST_RELATIVE).read_bytes()
        with self.assertRaisesRegex(PROMOTION.QuarterlyPromotionError, "INJECTED_PARTIAL_FAILURE"):
            PROMOTION.apply_owner_promotion(
                self.root,
                review,
                PROMOTION.APPROVAL_TOKEN,
                fail_after_master_for_test=True,
            )
        self.assertEqual((self.root / PROMOTION.MASTER_RELATIVE).read_bytes(), before_master)
        self.assertEqual((self.root / PROMOTION.MANIFEST_RELATIVE).read_bytes(), before_manifest)
        self.assertFalse((review / "promotion_receipt.json").exists())

    def test_no_owner_approval_denies_formal_write(self) -> None:
        review = self.root / "review"
        PROMOTION.create_owner_review(self.root, review)
        with self.assertRaisesRegex(PROMOTION.QuarterlyPromotionError, "OWNER_APPROVAL_REQUIRED"):
            PROMOTION.apply_owner_promotion(self.root, review, "")


if __name__ == "__main__":
    unittest.main()
