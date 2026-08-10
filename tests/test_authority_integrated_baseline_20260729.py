from __future__ import annotations

import csv
import hashlib
import json
import re
import subprocess
import unittest
from decimal import Decimal
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
ACCEPTANCE = (
    ROOT / "contracts" / "p1008_research_plugin" / "acceptance" / "v1.1"
)
EXPECTED_MANIFEST_SHA = (
    "7DC97FFBC0E3F5E73E8085ACC25DD61E0F3588FCE04C360B4F19FA0D86AFA01B"
)
EXPECTED_CASH_FLOW_SHA = (
    "082ECA44A96A06F7DAE10DD33CBAF77C75DABA9B1B4DEA27B5B930F8CE8CD95C"
)
EXPECTED_ROW_IDENTITY_SHA = (
    "E72989762053D20665DD87DA263F8B4DB1E77D277A6A27FD6C8AABBFE4921B9D"
)
EXPECTED_CLOSURE_SHA = (
    "C9291E01C7370FFB1D70FDF7F6363C672E77912BFA74DD6C5862F4146DD52213"
)
EXPECTED_INTEGRATION_RECEIPT_SHA = (
    "112373EA26100384F93B85A87415C5625DA34A1634B1C83E557C45BCC7829AAE"
)
EXPECTED_PATHS = {
    "data/2317_master_v9.csv",
    "data/2317_daily_price.csv",
    "data/2317_daily_market_activity.csv",
    "data/2317_cash_flow_authority.csv",
    "data/macro_snapshot.csv",
    "data/macro_event_observations.csv",
    "data/fx_trend_observations.csv",
}
PHASE_A_CLOSURE_RECEIPT = (
    "contracts/p1008_research_plugin/acceptance/v1.1/"
    "PHASE_A_AUTHORITY_DATA_CLOSURE_RECEIPT.json"
)
PHASE_A_CLOSURE_PORTABILITY_AMENDMENT = (
    ACCEPTANCE / "PHASE_A_CLOSURE_RECEIPT_PORTABILITY_AMENDMENT.json"
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def canonical_git_blob_sha256(relative: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(ROOT), "cat-file", "blob", f"HEAD:{relative}"],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"canonical Git blob unavailable for {relative}: "
            f"{result.stderr.decode('utf-8', errors='replace').strip()}"
        )
    return hashlib.sha256(result.stdout).hexdigest().upper()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


class AuthorityIntegratedBaseline20260729Tests(unittest.TestCase):
    def test_cash_flow_formula_schema_source_and_safety(self) -> None:
        path = DATA / "2317_cash_flow_authority.csv"
        rows = read_csv(path)
        self.assertEqual(sha256(path), EXPECTED_CASH_FLOW_SHA)
        self.assertEqual(len(rows), 2)
        self.assertEqual({row["ticker"] for row in rows}, {"2317"})
        self.assertEqual({row["period"] for row in rows}, {"2025Q1", "2026Q1"})

        for row in rows:
            cfo = int(row["operating_cash_flow_thousand_ntd"])
            ppe = int(row["ppe_capex_thousand_ntd"])
            intangible = int(row["intangible_capex_thousand_ntd"])
            core = int(row["free_cash_flow_core_thousand_ntd"])
            after_intangibles = int(
                row["free_cash_flow_after_intangibles_thousand_ntd"]
            )
            self.assertEqual(core, cfo - ppe)
            self.assertEqual(after_intangibles, cfo - ppe - intangible)
            self.assertEqual(
                Decimal(row["free_cash_flow_core_100m_ntd"]),
                Decimal(core) / Decimal("100000"),
            )
            self.assertEqual(
                Decimal(row["free_cash_flow_after_intangibles_100m_ntd"]),
                Decimal(after_intangibles) / Decimal("100000"),
            )
            self.assertTrue(row["source_report_url"].startswith("https://"))
            self.assertTrue(row["source_landing_url"].startswith("https://"))
            self.assertEqual(row["source_pages"], "10|11")
            self.assertRegex(
                row["source_document_sha256"], re.compile(r"^[0-9A-F]{64}$")
            )
            self.assertEqual(
                row["verification_status"], "OFFICIAL_HONHAI_PDF_VERIFIED"
            )
            self.assertEqual(row["actionable"].lower(), "false")

        q1 = next(row for row in rows if row["period"] == "2026Q1")
        self.assertEqual(q1["operating_cash_flow_thousand_ntd"], "3217154")
        self.assertEqual(q1["ppe_capex_thousand_ntd"], "35774345")
        self.assertEqual(q1["intangible_capex_thousand_ntd"], "300141")
        self.assertEqual(q1["free_cash_flow_core_thousand_ntd"], "-32557191")
        self.assertEqual(q1["free_cash_flow_core_100m_ntd"], "-325.57191")

    def test_manifest_is_exact_integrated_seven_file_baseline(self) -> None:
        manifest_path = DATA / "CSV_AUTHORITY_MANIFEST.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        entries = manifest["authoritativeFiles"] + manifest["nonAuthoritativeFiles"]
        self.assertEqual(sha256(manifest_path), EXPECTED_MANIFEST_SHA)
        self.assertEqual({entry["path"] for entry in entries}, EXPECTED_PATHS)
        self.assertEqual(len(entries), 7)
        for entry in entries:
            self.assertEqual(sha256(ROOT / entry["path"]), entry["sha256"])

        integration = manifest["authorityBaselineIntegration"]
        self.assertEqual(
            integration["version"], "P1008_AUTHORITY_INTEGRATED_SEVEN_20260729"
        )
        self.assertEqual(integration["verifiedFileCount"], 7)
        self.assertEqual(set(integration["paths"]), EXPECTED_PATHS)
        self.assertEqual(integration["cashFlowCutoff"], "2026Q1")
        self.assertFalse(integration["automaticFormalCsvPublish"])
        self.assertFalse(integration["automaticReportGeneration"])
        self.assertFalse(integration["phaseBStarted"])
        self.assertFalse(integration["actionable"])

        cash = next(
            entry
            for entry in manifest["authoritativeFiles"]
            if entry["path"] == "data/2317_cash_flow_authority.csv"
        )
        self.assertEqual(cash["sha256"], EXPECTED_CASH_FLOW_SHA)
        self.assertEqual(cash["rowCount"], 2)
        self.assertEqual(cash["financialCutoffPeriod"], "2026Q1")
        self.assertEqual(cash["sourceTier"], "OFFICIAL_HONHAI_PDF_A1_L1_DERIVED")
        self.assertFalse(cash["actionable"])

    def test_row_identity_evidence_is_byte_persisted(self) -> None:
        evidence_path = (
            ACCEPTANCE / "evidence" / "PHASE_A_MACRO_ROW_IDENTITY_RECEIPT.json"
        )
        self.assertEqual(sha256(evidence_path), EXPECTED_ROW_IDENTITY_SHA)
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        self.assertEqual(evidence["input"]["source"], "CANONICAL_GIT_BLOB_ONLY")
        self.assertEqual(evidence["canonical_statistics"]["data_record_count"], 39)
        self.assertEqual(evidence["hon_hai_rev_yoy_non_numeric_count"], 5)
        self.assertEqual(
            [
                row["canonical_data_record_ordinal"]
                for row in evidence["row_identities"]
            ],
            [1, 26, 27, 28, 29],
        )

    def test_integration_receipt_preserves_historical_chain(self) -> None:
        closure_path = ROOT / PHASE_A_CLOSURE_RECEIPT
        receipt_path = ACCEPTANCE / "PHASE_A_FINAL_INTEGRATION_AMENDMENT_RECEIPT.json"
        self.assertEqual(
            canonical_git_blob_sha256(PHASE_A_CLOSURE_RECEIPT), EXPECTED_CLOSURE_SHA
        )
        amendment = json.loads(
            PHASE_A_CLOSURE_PORTABILITY_AMENDMENT.read_text(encoding="utf-8")
        )
        self.assertEqual(
            amendment["defectClassification"],
            "CROSS_PLATFORM_RECEIPT_REPRODUCIBILITY_DEFECT",
        )
        self.assertEqual(
            amendment["remediationMethod"], "CANONICAL_GIT_BLOB_VERIFICATION"
        )
        self.assertTrue(amendment["historicalReceipt"]["historicalReceiptPreserved"])
        self.assertEqual(
            amendment["historicalReceipt"]["canonicalGitBlobSha256"],
            EXPECTED_CLOSURE_SHA,
        )
        self.assertFalse(amendment["authorityChanged"])
        self.assertFalse(amendment["productionCodeChanged"])
        self.assertFalse(amendment["actionable"])
        self.assertEqual(sha256(receipt_path), EXPECTED_INTEGRATION_RECEIPT_SHA)
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        self.assertEqual(
            receipt["acceptanceStatus"], "PHASE_A_FINAL_INTEGRATION_RECONCILED"
        )
        self.assertEqual(receipt["baselineId"], "INTEGRATED_SEVEN")
        self.assertEqual(
            receipt["priorFinalClosureReceipt"]["sha256"], EXPECTED_CLOSURE_SHA
        )
        self.assertEqual(
            receipt["committedRowIdentityEvidence"]["sha256"],
            EXPECTED_ROW_IDENTITY_SHA,
        )
        self.assertEqual(
            receipt["authorityManifest"]["sha256"], EXPECTED_MANIFEST_SHA
        )
        self.assertEqual(set(receipt["authorityFiles"]), EXPECTED_PATHS)
        self.assertEqual(receipt["authoritySummary"]["verifiedFileCount"], 7)
        self.assertEqual(
            receipt["pr5Reconciliation"]["uniqueGovernanceDifferenceCount"], 0
        )
        self.assertFalse(receipt["formalPublishExecutedByThisReceipt"])
        self.assertFalse(receipt["phaseBStarted"])
        self.assertFalse(receipt["actionable"])


if __name__ == "__main__":
    unittest.main()
