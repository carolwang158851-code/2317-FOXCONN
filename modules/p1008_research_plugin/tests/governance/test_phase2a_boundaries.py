from __future__ import annotations

import copy
import hashlib
import json
import re
import subprocess
import sys
import unittest
from pathlib import Path


MODULE_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = MODULE_ROOT.parents[1]
SRC_ROOT = MODULE_ROOT / "src" / "p1008_research_plugin"
sys.path.insert(0, str(MODULE_ROOT / "src"))

from p1008_research_plugin.orchestrator import ResearchOrchestrator
from p1008_research_plugin.runtime.runtime_validator import (
    RuntimeContractVerifier,
    RuntimeValidationError,
)


PROTECTED = (
    ".gitattributes",
    "contracts/p1008_research_plugin/acceptance/errata/v2.0/OWNER_ACCEPTANCE_HASH_ERRATA.json",
    "launcher.html",
    "tools/p1008_app_server.py",
    "data/CSV_AUTHORITY_MANIFEST.json",
    "rules/RULE_STATUS_MANIFEST.json",
    "contracts/p1008_research_plugin/v1.0/contract.manifest.json",
    "contracts/p1008_research_plugin/v2.0/contract.manifest.json",
    "contracts/p1008_research_plugin/acceptance/v2.0/OWNER_ACCEPTANCE_RECORD.json",
)

PHASE3A_PARENT_SHA = "47dea688ad1e2041b24116b00d58281380700bd8"
MANIFEST_GIT_LF_SHA256 = (
    "6A1DFE54BA4FCA749C18FDA747969473A4903CF21001AAACA6078C6CC8FEB75F"
)
MANIFEST_CRLF_SHA256 = (
    "A33AA4F29D363364BCD519BD8BFA137E3DB191A6C1F8F4D1161AD34190BBDBCD"
)
MANIFEST_MIXED_SHA256 = (
    "2686D044714E435CB4C1E63CB26B3BB555190F9A5BD21FE2C9439473DA998BE6"
)
FROZEN_MACRO_SHA256 = (
    "353025C29D678488F7022939C86C36CB15D3B348DC5876909D6779E56CFE213B"
)
FROZEN_MACRO_SIZE = 9075
CURRENT_MACRO_SHA256 = (
    "30A4755E87CECD4230FA8A521DF485385A89AC2A4E1E2B5726CBFD14AB96C86F"
)
CURRENT_MACRO_SIZE = 9012
ERRATA_RELATIVE = (
    "contracts/p1008_research_plugin/acceptance/errata/v2.0/"
    "OWNER_ACCEPTANCE_HASH_ERRATA.json"
)
ERRATA_BINDINGS = {
    "acceptance_sha": (
        "A056D8C139C254D04BEF9298DA34152D0CF5A18864D040E5B9B3FE7A226E0533"
    ),
    "acceptance_manifest_sha": MANIFEST_MIXED_SHA256,
    "manifest_sha": MANIFEST_GIT_LF_SHA256,
}
PHASE3A_RAW_HASHES = {
    "contracts/p1008_research_plugin/v1.0/contract.manifest.json": (
        "5D213CB4360329FCC969164F559952A0F1545BFE8E53D5CFDFF014B9D5619773"
    ),
    "contracts/p1008_research_plugin/v2.0/contract.manifest.json": (
        MANIFEST_GIT_LF_SHA256
    ),
    "contracts/p1008_research_plugin/acceptance/v2.0/OWNER_ACCEPTANCE_RECORD.json": (
        "A056D8C139C254D04BEF9298DA34152D0CF5A18864D040E5B9B3FE7A226E0533"
    ),
    "contracts/p1008_research_plugin/v2.0/validation/CONFORMANCE_EVIDENCE.json": (
        "13E514244F93BD02E523C1C3A14412056898A89654613DA5E5172339AA472A97"
    ),
    "data/macro_snapshot.csv": FROZEN_MACRO_SHA256,
}
PHASE3A_R_TARGETFILES = {
    ".gitattributes",
    ERRATA_RELATIVE,
    (
        "modules/p1008_research_plugin/src/p1008_research_plugin/"
        "runtime/runtime_validator.py"
    ),
    "data/CSV_AUTHORITY_MANIFEST.json",
    "modules/p1008_research_plugin/tests/test_governance_boundaries.py",
    (
        "modules/p1008_research_plugin/tests/governance/"
        "test_phase2a_boundaries.py"
    ),
}
TEST_CONSTANT_PATHS = {
    "launcher.html",
    "tools/p1008_app_server.py",
    "data/CSV_AUTHORITY_MANIFEST.json",
    "rules/RULE_STATUS_MANIFEST.json",
    "contracts/p1008_research_plugin/v1.0/contract.manifest.json",
    "contracts/p1008_research_plugin/v2.0/contract.manifest.json",
    "contracts/p1008_research_plugin/acceptance/v2.0/OWNER_ACCEPTANCE_RECORD.json",
    (
        "modules/p1008_research_plugin/src/p1008_research_plugin/"
        "runtime/runtime_manager.py"
    ),
    (
        "modules/p1008_research_plugin/src/p1008_research_plugin/"
        "runtime/capability_registry.py"
    ),
    "modules/p1008_research_plugin/docs/phase2a/Phase2A_Closure_Report.md",
    "modules/p1008_research_plugin/tests/fixtures/authority_baselines.json",
    (
        "contracts/p1008_research_plugin/acceptance/v1.1/"
        "PHASE_A_FINAL_INTEGRATION_AMENDMENT_RECEIPT.json"
    ),
    (
        "contracts/p1008_research_plugin/acceptance/v1.1/"
        "PHASE_A_AUTHORITY_BASELINE_RECEIPT.json"
    ),
    (
        "contracts/p1008_research_plugin/acceptance/v1.1/"
        "PHASE_A_AUTHORITY_DATA_CLOSURE_RECEIPT.json"
    ),
    (
        "contracts/p1008_research_plugin/acceptance/v1.1/"
        "PHASE_A_DAILY_PRICE_STAGE1_PUBLISH_RECEIPT.json"
    ),
    (
        "contracts/p1008_research_plugin/acceptance/v1.1/"
        "PHASE_A_MACRO_STAGE2B_PUBLISH_RECEIPT.json"
    ),
    (
        "contracts/p1008_research_plugin/acceptance/v1.1/"
        "PHASE_A_MARKET_ACTIVITY_STAGE2A_PUBLISH_RECEIPT.json"
    ),
    (
        "contracts/p1008_research_plugin/acceptance/v1.1/"
        "PHASE_ROUTING_ACCEPTANCE_RECORD.json"
    ),
    (
        "contracts/p1008_research_plugin/acceptance/v1.1/evidence/"
        "PHASE_A_MACRO_ROW_IDENTITY_RECEIPT.json"
    ),
    (
        "contracts/p1008_research_plugin/acceptance/v1.1/evidence/"
        "phase_a_twse_202607/2026-07.twse.raw.csv"
    ),
    (
        "contracts/p1008_research_plugin/acceptance/v1.1/evidence/"
        "phase_a_twse_202607/2026-07.receipt.json"
    ),
}
RAW_BINARY_EVIDENCE_PATHS = {
    (
        "contracts/p1008_research_plugin/acceptance/v1.1/evidence/"
        "phase_a_twse_202607/2026-07.twse.raw.csv"
    ),
}
PHASEB1_HASH_GOVERNED_PATHS = {
    ".github/workflows/p1008-phaseb1-analysis-report.yml",
    "P1008_BUILD_ANALYSIS.bat",
    "P1008_BUILD_REPORT.bat",
    "contracts/p1008_analysis/v1.0/ANALYSIS_CONTRACT.md",
    "contracts/p1008_analysis/v1.0/contract.manifest.json",
    "contracts/p1008_analysis/v1.0/schemas/analysis_gate_result.schema.json",
    "contracts/p1008_analysis/v1.0/schemas/analysis_packet.schema.json",
    "contracts/p1008_analysis/v1.0/schemas/financial_trend.schema.json",
    "contracts/p1008_analysis/v1.0/schemas/market_psychology.schema.json",
    "contracts/p1008_analysis/v1.0/schemas/market_regime.schema.json",
    "contracts/p1008_analysis/v1.0/schemas/price_and_market_activity.schema.json",
    "contracts/p1008_analysis/v1.0/schemas/thesis_scorecard.schema.json",
    "contracts/p1008_analysis/v1.0/schemas/valuation_analysis.schema.json",
    (
        "contracts/p1008_report_production/acceptance/v1.0/"
        "PHASE_B1_OWNER_AUTHORIZATION_RECORD.json"
    ),
    (
        "contracts/p1008_report_production/acceptance/v1.1/"
        "PHASE_B1_OPS_OWNER_AUTHORIZATION_RECORD.json"
    ),
    (
        "contracts/p1008_report_production/acceptance/v1.1/"
        "PHASE_B1_OPS_R1_OWNER_AUTHORIZATION_RECORD.json"
    ),
    (
        "contracts/p1008_report_production/acceptance/v1.1/"
        "PHASE_B1_OPS_R2_OWNER_AUTHORIZATION_RECORD.json"
    ),
    (
        "contracts/p1008_report_production/acceptance/v1.1/"
        "PHASE_B1_OPS_R2_TRACKED_UI_SOURCE_RECEIPT.json"
    ),
    "contracts/p1008_report_production/v1.0/REPORT_PRODUCTION_CONTRACT.md",
    "contracts/p1008_report_production/v1.0/contract.manifest.json",
    "contracts/p1008_report_production/v1.0/schemas/chart_data.schema.json",
    "contracts/p1008_report_production/v1.0/schemas/editorial_validation.schema.json",
    "contracts/p1008_report_production/v1.0/schemas/evidence_reference.schema.json",
    "contracts/p1008_report_production/v1.0/schemas/report_candidate.schema.json",
    "contracts/p1008_report_production/v1.0/schemas/report_gate_result.schema.json",
    "contracts/p1008_report_production/v1.0/schemas/shorts_duration_validation.schema.json",
    "docs/APP_WORKFLOW.md",
    "docs/P1008_PHASE_B1_OPS_LAUNCHER_REPORT_RECOVERY.md",
    "ui/P1008_WARROOM_COMMAND_CENTER_v24.html",
    "modules/p1008_research_plugin/docs/phaseb1/PhaseB1_Analysis_Report_MVP.md",
    "modules/p1008_research_plugin/src/p1008_research_plugin/analysis/__init__.py",
    (
        "modules/p1008_research_plugin/src/p1008_research_plugin/analysis/"
        "analysis_builder.py"
    ),
    (
        "modules/p1008_research_plugin/src/p1008_research_plugin/analysis/"
        "analysis_contracts.py"
    ),
    (
        "modules/p1008_research_plugin/src/p1008_research_plugin/analysis/"
        "analysis_validator.py"
    ),
    "modules/p1008_research_plugin/src/p1008_research_plugin/phaseb1_common.py",
    "modules/p1008_research_plugin/src/p1008_research_plugin/phaseb1_pipeline.py",
    "modules/p1008_research_plugin/tests/fixtures/phaseb1/monthly_revenue_fixture_alt_dates.json",
    "modules/p1008_research_plugin/tests/phaseb1/test_owner_review_remediation_r1.py",
    "modules/p1008_research_plugin/src/p1008_research_plugin/reporting/__init__.py",
    (
        "modules/p1008_research_plugin/src/p1008_research_plugin/reporting/"
        "chart_data_builder.py"
    ),
    (
        "modules/p1008_research_plugin/src/p1008_research_plugin/reporting/"
        "report_builder.py"
    ),
    (
        "modules/p1008_research_plugin/src/p1008_research_plugin/reporting/"
        "report_contracts.py"
    ),
    (
        "modules/p1008_research_plugin/src/p1008_research_plugin/reporting/"
        "report_renderer_markdown.py"
    ),
    (
        "modules/p1008_research_plugin/src/p1008_research_plugin/reporting/"
        "report_validator.py"
    ),
    (
        "modules/p1008_research_plugin/src/p1008_research_plugin/reporting/"
        "script_builder.py"
    ),
    "modules/p1008_research_plugin/tests/fixtures/phaseb1/monthly_revenue_fixture.json",
    "modules/p1008_research_plugin/tests/phaseb1/__init__.py",
    "modules/p1008_research_plugin/tests/phaseb1/helpers.py",
    "modules/p1008_research_plugin/tests/phaseb1/test_analysis_layer.py",
    "modules/p1008_research_plugin/tests/phaseb1/test_report_production.py",
    "modules/p1008_research_plugin/tests/phaseb1/test_script_candidates.py",
    "tests/test_phaseb1_launcher.py",
    "report_viewer.html",
    "reports.html",
    "tests/test_p1008_app_market_activity_pipeline.py",
    "tests/test_phaseb1_ops_launcher_report_recovery.py",
    "tools/p1008_build_analysis.py",
    "tools/p1008_build_report.py",
    "tools/p1008_build_phaseb1_final_review.py",
    "tools/p1008_open_warroom.py",
    "tools/warroom_periodic_report_v1.py",
    "tools/warroom_rolling_brief.py",
}
G1_REPORT_GOVERNANCE_HASH_GOVERNED_PATHS = {
    "contracts/p1008_report_governance/v1.0/REPORT_GOVERNANCE_CONTRACT.md",
    "contracts/p1008_report_governance/v1.0/contract.manifest.json",
    "contracts/p1008_report_governance/v1.0/schemas/event_evidence.schema.json",
    "contracts/p1008_report_governance/v1.0/schemas/report_trigger_decision.schema.json",
    "contracts/p1008_report_governance/v1.0/schemas/core_view_change_decision.schema.json",
    "contracts/p1008_report_governance/v1.0/schemas/publication_decision.schema.json",
    "contracts/p1008_report_governance/v1.0/schemas/model_provenance.schema.json",
    "contracts/p1008_report_governance/v1.0/schemas/report_decision_receipt.schema.json",
    "contracts/p1008_report_governance/v1.0/schemas/materiality_threshold_policy.schema.json",
    "contracts/p1008_report_governance/v1.0/schemas/trigger_issuance_receipt.schema.json",
    "contracts/p1008_report_governance/v1.0/schemas/trigger_issuance_index.schema.json",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def git_blob_sha256(revision: str, relative: str) -> str:
    blob = subprocess.run(
        ["git", "cat-file", "blob", f"{revision}:{relative}"],
        cwd=PACKAGE_ROOT,
        check=True,
        stdout=subprocess.PIPE,
    ).stdout
    return hashlib.sha256(blob).hexdigest().upper()


def load_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def expected_hash_governed_paths() -> set[str]:
    expected = (
        set(PHASE3A_R_TARGETFILES)
        | set(TEST_CONSTANT_PATHS)
        | set(PHASEB1_HASH_GOVERNED_PATHS)
        | set(G1_REPORT_GOVERNANCE_HASH_GOVERNED_PATHS)
    )
    for relative_root in (
        "contracts/p1008_research_plugin/v1.0",
        "contracts/p1008_research_plugin/v2.0",
    ):
        root = PACKAGE_ROOT / relative_root
        manifest = load_json(root / "contract.manifest.json")
        expected.add(f"{relative_root}/contract.manifest.json")
        expected.update(
            (root / artifact["path"]).relative_to(PACKAGE_ROOT).as_posix()
            for artifact in manifest["artifacts"]
        )
        expected.update(
            (root / relative).resolve().relative_to(PACKAGE_ROOT).as_posix()
            for relative in manifest.get("evidenceExcluded", [])
        )
    authority = load_json(PACKAGE_ROOT / "data/CSV_AUTHORITY_MANIFEST.json")
    expected.add("data/CSV_AUTHORITY_MANIFEST.json")
    for group in ("authoritativeFiles", "nonAuthoritativeFiles"):
        expected.update(
            entry["path"]
            for entry in authority[group]
            if entry["path"].lower().endswith((".csv", ".tsv"))
        )
    return expected


def load_errata() -> dict[str, object]:
    return RuntimeContractVerifier._json(PACKAGE_ROOT / ERRATA_RELATIVE)


def validate_errata(errata: dict[str, object], **overrides: object) -> None:
    bindings = dict(ERRATA_BINDINGS)
    bindings.update(overrides)
    RuntimeContractVerifier._validate_manifest_errata(errata, **bindings)


class Phase2ABoundaryTests(unittest.TestCase):
    def test_frozen_contracts_verify_before_execution(self) -> None:
        result = RuntimeContractVerifier(PACKAGE_ROOT).verify()
        self.assertTrue(result["v2_authoritative"])
        self.assertEqual(
            RuntimeContractVerifier._sha(
                PACKAGE_ROOT
                / "contracts/p1008_research_plugin/v2.0/contract.manifest.json"
            ),
            MANIFEST_GIT_LF_SHA256,
        )
        self.assertEqual(
            result["v1_root"],
            "3370C4DBD6B564E2200D051AC07C8507442C130ADE64D770621107FA09D2924D",
        )
        self.assertEqual(
            result["v2_root"],
            "E056357A8A63A15BCF9FDC286BEE0BDB56E043AF26F4DDCD5624FDB3707BD782",
        )

    def test_hash_governed_paths_are_exactly_lf_pinned(self) -> None:
        raw = (PACKAGE_ROOT / ".gitattributes").read_bytes()
        self.assertNotIn(b"\r", raw)
        lines = raw.decode("ascii").splitlines()
        self.assertEqual(
            lines[0],
            "# Phase 3A-R: exact LF policy for reviewed hash-governed text files.",
        )
        entries = []
        for line in lines[1:]:
            path, attributes = line.split(" ", 1)
            expected_attributes = (
                "binary" if path in RAW_BINARY_EVIDENCE_PATHS else "text eol=lf"
            )
            self.assertEqual(attributes, expected_attributes)
            self.assertFalse(any(character in path for character in "*?["))
            entries.append(path)
        self.assertEqual(len(entries), len(set(entries)))
        self.assertEqual(set(entries), expected_hash_governed_paths())
        self.assertEqual(len(entries), 168)

    def test_crlf_and_mixed_manifest_bytes_are_rejected(self) -> None:
        for rejected in (MANIFEST_CRLF_SHA256, MANIFEST_MIXED_SHA256):
            with self.subTest(manifest_sha=rejected):
                with self.assertRaises(RuntimeValidationError):
                    validate_errata(load_errata(), manifest_sha=rejected)

    def test_macro_authority_hash_and_size_match_git_blob(self) -> None:
        authority = load_json(PACKAGE_ROOT / "data/CSV_AUTHORITY_MANIFEST.json")
        entries = authority["authoritativeFiles"] + authority["nonAuthoritativeFiles"]
        entry = next(
            item for item in entries if item["path"] == "data/macro_snapshot.csv"
        )
        macro = PACKAGE_ROOT / "data/macro_snapshot.csv"
        self.assertEqual(entry["sha256"], CURRENT_MACRO_SHA256)
        self.assertEqual(entry["fileSizeBytes"], CURRENT_MACRO_SIZE)
        self.assertEqual(sha256(macro), CURRENT_MACRO_SHA256)
        self.assertEqual(macro.stat().st_size, CURRENT_MACRO_SIZE)

    def test_phase3a_frozen_bytes_are_unchanged(self) -> None:
        for relative, expected in PHASE3A_RAW_HASHES.items():
            self.assertEqual(git_blob_sha256(PHASE3A_PARENT_SHA, relative), expected)
        self.assertEqual(
            subprocess.run(
                [
                    "git",
                    "cat-file",
                    "-s",
                    f"{PHASE3A_PARENT_SHA}:data/macro_snapshot.csv",
                ],
                cwd=PACKAGE_ROOT,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip(),
            str(FROZEN_MACRO_SIZE),
        )

    def test_errata_is_bound_to_phase3a_parent(self) -> None:
        self.assertEqual(load_errata()["phase3aParentSha"], PHASE3A_PARENT_SHA)

    def test_errata_rejects_unknown_top_level_field(self) -> None:
        errata = load_errata()
        errata["extraCorrection"] = True
        with self.assertRaises(RuntimeValidationError):
            validate_errata(errata)

    def test_errata_rejects_unknown_correction_field(self) -> None:
        errata = load_errata()
        correction = errata["correction"]
        self.assertIsInstance(correction, dict)
        correction["acceptedRootHash"] = "0" * 64
        with self.assertRaises(RuntimeValidationError):
            validate_errata(errata)

    def test_errata_rejects_other_path_field_or_hash(self) -> None:
        base = load_errata()
        cases = (
            ("fieldPath", "acceptedRootHash"),
            (
                "targetFile",
                "contracts/p1008_research_plugin/v1.0/contract.manifest.json",
            ),
            ("oldSha256", "0" * 64),
            ("newGitLfSha256", "F" * 64),
        )
        for field, value in cases:
            with self.subTest(field=field):
                errata = copy.deepcopy(base)
                correction = errata["correction"]
                self.assertIsInstance(correction, dict)
                correction[field] = value
                with self.assertRaises(RuntimeValidationError):
                    validate_errata(errata)

    def test_errata_rejects_original_binding_or_manifest_drift(self) -> None:
        for binding in ERRATA_BINDINGS:
            with self.subTest(binding=binding):
                with self.assertRaises(RuntimeValidationError):
                    validate_errata(load_errata(), **{binding: "0" * 64})

    def test_pipeline_does_not_change_protected_files(self) -> None:
        before = {relative: sha256(PACKAGE_ROOT / relative) for relative in PROTECTED}
        ResearchOrchestrator(PACKAGE_ROOT).run({"symbol": "2317", "question": "test"})
        after = {relative: sha256(PACKAGE_ROOT / relative) for relative in PROTECTED}
        self.assertEqual(after, before)

    def test_phase2a_source_has_no_sdk_network_or_secret_access(self) -> None:
        pattern = re.compile(
            r"^\s*(?:from|import)\s+(?:openai|agents|requests|httpx|socket|urllib\.request|http\.client)\b",
            re.MULTILINE,
        )
        violations = []
        secret_reads = []
        for path in SRC_ROOT.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            if pattern.search(text):
                violations.append(path.relative_to(MODULE_ROOT).as_posix())
            if "OPENAI_API_KEY" in text or "os.environ" in text:
                secret_reads.append(path.relative_to(MODULE_ROOT).as_posix())
        self.assertEqual(violations, [])
        self.assertEqual(secret_reads, [])

    def test_no_runtime_or_governance_store_is_created(self) -> None:
        watched = [
            PACKAGE_ROOT / "runtime" / "research_plugin" / "artifacts",
            PACKAGE_ROOT / "runtime" / "research_plugin" / "governance",
        ]
        before = [path.exists() for path in watched]
        ResearchOrchestrator(PACKAGE_ROOT).run({"symbol": "2317", "question": "test"})
        self.assertEqual([path.exists() for path in watched], before)


if __name__ == "__main__":
    unittest.main()
