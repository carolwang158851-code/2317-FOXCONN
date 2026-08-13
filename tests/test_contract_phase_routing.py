from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = ROOT / "contracts" / "p1008_research_plugin" / "conformance" / "v1.1" / "run_contract_tests.py"
ROUTER_PATH = ROOT / "contracts" / "p1008_research_plugin" / "conformance" / "run_phase_conformance.py"
RECORD_PATH = ROOT / "contracts" / "p1008_research_plugin" / "acceptance" / "v1.1" / "PHASE_ROUTING_ACCEPTANCE_RECORD.json"


def controlled_test_temp_root() -> Path:
    """Return the user-owned, non-OneDrive root for Windows test scratch."""

    configured = os.environ.get("P1008_TEST_TEMP_ROOT", "").strip()
    if configured:
        root = Path(configured)
    else:
        local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
        if not local_app_data:
            raise RuntimeError("P1008_TEST_TEMP_ROOT_REQUIRED")
        root = Path(local_app_data) / "P1008" / "pytest-temp"
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def load_runner():
    spec = importlib.util.spec_from_file_location("phase_routing_test_runner", RUNNER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load current conformance runner")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_router():
    spec = importlib.util.spec_from_file_location("phase_routing_test_router", ROUTER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load phase-aware conformance router")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class PhaseRoutingConformanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.runner = load_runner()
        cls.router = load_router()
        cls.record = json.loads(RECORD_PATH.read_text(encoding="utf-8"))

    def _tree(self, *, module: bool) -> tempfile.TemporaryDirectory[str]:
        holder = tempfile.TemporaryDirectory(
            prefix="p1008-phase-routing-test-", dir=controlled_test_temp_root()
        )
        root = Path(holder.name)
        if module:
            (root / "modules" / "p1008_research_plugin" / "src" / "p1008_research_plugin").mkdir(parents=True)
        return holder

    def _module_with_source(self, source: str) -> tempfile.TemporaryDirectory[str]:
        holder = self._tree(module=True)
        path = Path(holder.name) / "modules" / "p1008_research_plugin" / "src" / "p1008_research_plugin" / "candidate.py"
        path.write_text(source, encoding="utf-8")
        return holder

    def test_legacy_tree_with_module_absent_passes(self) -> None:
        with self._tree(module=False) as root:
            self.runner.validate_module_state(Path(root), "ABSENT")

    def test_legacy_tree_with_module_present_fails(self) -> None:
        with self._tree(module=True) as root:
            with self.assertRaisesRegex(AssertionError, "exists early"):
                self.runner.validate_module_state(Path(root), "ABSENT")

    def test_current_phase_with_module_present_passes(self) -> None:
        with self._tree(module=True) as root:
            self.runner.validate_module_state(Path(root), "PRESENT")

    def test_current_phase_with_module_missing_fails(self) -> None:
        with self._tree(module=False) as root:
            with self.assertRaisesRegex(AssertionError, "module is missing"):
                self.runner.validate_module_state(Path(root), "PRESENT")

    def test_current_module_formal_csv_write_fails(self) -> None:
        source = 'from pathlib import Path\nPath("data/2317_daily_price.csv").write_text("bad")\n'
        with self._module_with_source(source) as root:
            module = Path(root) / "modules" / "p1008_research_plugin"
            self.assertTrue(self.runner.protected_write_violations(module))

    def test_current_module_rule_or_sqlite_write_fails(self) -> None:
        cases = (
            'from pathlib import Path\nPath("rules/RULE_STATUS_MANIFEST.json").write_text("bad")\n',
            'db = "warroom.sqlite3"\nsql = "UPDATE status SET value=1"\n',
        )
        for source in cases:
            with self.subTest(source=source):
                with self._module_with_source(source) as root:
                    module = Path(root) / "modules" / "p1008_research_plugin"
                    self.assertTrue(self.runner.protected_write_violations(module))

    def test_current_actionable_true_fails(self) -> None:
        with self._module_with_source("payload = {'actionable': True}\n") as root:
            module = Path(root) / "modules" / "p1008_research_plugin"
            self.assertTrue(self.runner.actionable_violations(module))

    def test_unknown_phase_fails_closed(self) -> None:
        value = dict(self.record)
        value["currentPhase"] = "UNKNOWN"
        with self.assertRaisesRegex(AssertionError, "Unknown or unsupported phase"):
            self.runner.validate_phase_record(value)

    def test_frozen_v1_bytes_and_root_hash_are_unchanged(self) -> None:
        result = self.runner.validate_immutable_v1(ROOT, self.record)
        self.assertEqual(result["rootHash"], "3370C4DBD6B564E2200D051AC07C8507442C130ADE64D770621107FA09D2924D")
        for relative, expected in self.record["immutableV1"]["artifacts"].items():
            actual = hashlib.sha256(self.runner.git_blob_bytes(ROOT, relative)).hexdigest().upper()
            self.assertEqual(actual, expected)

    def test_frozen_v1_checkout_allows_only_line_ending_materialization(self) -> None:
        relative = "contracts/p1008_research_plugin/conformance/v1.0/frozen.txt"
        manifest_relative = "contracts/p1008_research_plugin/v1.0/contract.manifest.json"
        with tempfile.TemporaryDirectory(
            prefix="p1008-frozen-checkout-test-", dir=controlled_test_temp_root()
        ) as root_value:
            root = Path(root_value)
            artifact = root / relative
            manifest = root / manifest_relative
            artifact.parent.mkdir(parents=True)
            manifest.parent.mkdir(parents=True)
            artifact.write_bytes(b"frozen\ncontent\n")
            manifest.write_text(json.dumps({"rootHash": "ROOT"}), encoding="utf-8")
            subprocess_args = ["git", "-C", str(root)]
            subprocess.run([*subprocess_args, "init", "-q"], check=True)
            subprocess.run([*subprocess_args, "add", relative, manifest_relative], check=True)
            subprocess.run(
                [*subprocess_args, "-c", "user.name=P1008 Test", "-c", "user.email=p1008@example.invalid", "commit", "-qm", "frozen"],
                check=True,
            )
            record = {
                "immutableV1": {
                    "contractRootHash": "ROOT",
                    "artifacts": {relative: hashlib.sha256(b"frozen\ncontent\n").hexdigest().upper()},
                }
            }

            artifact.write_bytes(b"frozen\r\ncontent\r\n")
            self.runner.validate_immutable_v1(root, record)

            artifact.write_bytes(b"changed\r\ncontent\r\n")
            with self.assertRaisesRegex(AssertionError, "beyond checkout line endings"):
                self.runner.validate_immutable_v1(root, record)

    def test_push_and_pull_request_share_current_router(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "p1008-research-contract.yml").read_text(encoding="utf-8")
        self.assertIn("push:", workflow)
        self.assertIn("pull_request:", workflow)
        trigger_blocks = {
            name: tuple(re.findall(r'^      - "([^"]+)"$', body, flags=re.MULTILINE))
            for name, body in re.findall(
                r"^  (push|pull_request):\n    paths:\n((?:      - .*\n)+)",
                workflow,
                flags=re.MULTILINE,
            )
        }
        self.assertEqual(trigger_blocks["push"], trigger_blocks["pull_request"])
        self.assertEqual(workflow.count("run_phase_conformance.py"), 1)
        self.assertNotIn("conformance/v1.0/run_contract_tests.py", workflow)
        self.assertIn("fetch-depth: 0", workflow)
        self.assertEqual(workflow.count('"data/2317_cash_flow_authority.csv"'), 2)
        self.assertEqual(workflow.count('"data/2317_daily_market_activity.csv"'), 2)

    def test_legacy_archive_is_independent_of_runner_line_endings(self) -> None:
        command = self.router.legacy_archive_command(Path("legacy.zip"), "legacy-commit")
        self.assertEqual(command[:5], ["git", "-c", "core.autocrlf=false", "-c", "core.eol=lf"])
        self.assertEqual(command[-1], "legacy-commit")

    def test_phase_lineage_records_match_canonical_git_blobs(self) -> None:
        lineage = self.record["phaseLineage"]
        for path_key, hash_key in (
            ("phase1bAcceptanceRecord", "phase1bAcceptanceSha256"),
            ("phase2aOwnerRecord", "phase2aOwnerRecordSha256"),
            ("phase3aOwnerRecord", "phase3aOwnerRecordSha256"),
        ):
            with self.subTest(path_key=path_key):
                self.runner.validate_committed_text_artifact(
                    ROOT,
                    lineage[path_key],
                    lineage[hash_key],
                    f"Phase lineage record {path_key}",
                )

    def test_authority_current_baseline_is_six_files(self) -> None:
        current = self.record["authorityBaselines"]["currentSix"]
        self.assertEqual(len(current), 6)
        self.assertEqual(self.runner.classify_authority_paths(current, self.record), "CURRENT_SIX")

    def test_phase_a_closure_baseline_is_receipt_pinned(self) -> None:
        current = self.record["authorityBaselines"]["phaseAClosureSix"]
        self.assertEqual(len(current), 6)
        self.assertEqual(
            self.runner.classify_authority_paths(current, self.record),
            "PHASE_A_CLOSURE_SIX",
        )
        receipt_ref = self.record["authorityBaselineReceipts"]["PHASE_A_CLOSURE_SIX"]
        self.assertEqual(
            hashlib.sha256(self.runner.git_blob_bytes(ROOT, receipt_ref["path"]))
            .hexdigest()
            .upper(),
            receipt_ref["sha256"],
        )

    def test_integrated_seven_baseline_is_active_and_receipt_pinned(self) -> None:
        current = self.record["authorityBaselines"]["integratedSeven"]
        self.assertEqual(len(current), 7)
        self.assertEqual(
            self.runner.classify_authority_paths(current, self.record),
            "INTEGRATED_SEVEN",
        )
        result = self.runner.validate_authority_manifest(ROOT, self.record)
        self.assertEqual(result["baseline"], "INTEGRATED_SEVEN")
        self.assertEqual(result["filesVerified"], 7)
        self.assertTrue(result["authorityReceiptVerified"])

    def test_phase_a_closure_receipt_pins_owner_approved_macro_hash(self) -> None:
        receipt_ref = self.record["authorityBaselineReceipts"]["PHASE_A_CLOSURE_SIX"]
        receipt_path = ROOT / receipt_ref["path"]
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        self.assertFalse(receipt["macroAuthorityDecision"]["unapprovedRowsAccepted"])
        self.assertEqual(
            receipt["macroAuthorityDecision"]["requiredSha256"],
            "30A4755E87CECD4230FA8A521DF485385A89AC2A4E1E2B5726CBFD14AB96C86F",
        )
        self.assertEqual(
            receipt["authorityFiles"]["data/macro_snapshot.csv"],
            receipt["macroAuthorityDecision"]["requiredSha256"],
        )

    def test_phase_a_stage1_receipt_accepts_only_owner_approved_daily_price(self) -> None:
        receipt_ref = {
            "path": "contracts/p1008_research_plugin/acceptance/v1.1/PHASE_A_DAILY_PRICE_STAGE1_PUBLISH_RECEIPT.json"
        }
        receipt = json.loads(
            (ROOT / receipt_ref["path"]).read_text(encoding="utf-8")
        )
        self.assertEqual(
            receipt["acceptanceStatus"],
            "OWNER_APPROVED_FORMAL_AUTHORITY_PUBLISH",
        )
        self.assertTrue(receipt["formalPublishExecutedByThisReceipt"])
        self.assertEqual(
            receipt["ownerApprovalPhrases"],
            [
                "OWNER_APPROVE_REMOVE_INVALID_DAILY_PRICE_2026-07-19",
                "OWNER_APPROVE_DAILY_PRICE_GAPS_20260722_20260724",
            ],
        )
        self.assertEqual(
            receipt["dailyPricePublish"]["afterGapPublishSha256"],
            "2581AF868AA0D8C4BFCEA913B156DBB515AF3929FAAE7D0FDC947EA4A8256304",
        )
        self.assertFalse(receipt["marketActivityDecision"]["publishedInStage1"])
        self.assertFalse(receipt["marketActivityDecision"]["promotionEligible"])
        self.assertFalse(receipt["macroAuthorityDecision"]["publishedInStage1"])

    def test_phase_a_stage2a_receipt_accepts_only_owner_approved_market_activity(self) -> None:
        receipt_ref = {
            "path": "contracts/p1008_research_plugin/acceptance/v1.1/PHASE_A_MARKET_ACTIVITY_STAGE2A_PUBLISH_RECEIPT.json"
        }
        receipt = json.loads(
            (ROOT / receipt_ref["path"]).read_text(encoding="utf-8")
        )
        self.assertEqual(
            receipt["acceptanceStatus"],
            "OWNER_APPROVED_MARKET_ACTIVITY_STAGE2A_PUBLISH",
        )
        self.assertTrue(receipt["formalPublishExecutedByThisReceipt"])
        self.assertEqual(
            receipt["ownerApprovalPhrase"],
            "OWNER_APPROVE_MARKET_ACTIVITY_20260720_20260727",
        )
        publish = receipt["marketActivityPublish"]
        self.assertEqual(publish["transactionStatus"], "PUBLISHED")
        self.assertEqual(publish["beforeRows"], 60)
        self.assertEqual(publish["afterRows"], 66)
        self.assertEqual(publish["cutoff"], "2026-07-27")
        self.assertEqual(
            publish["afterFormalSha256"],
            "FE7B33B649012E7D8143838793FE5ED6244BB2183B966C0DAD2C9775FB0E4807",
        )
        self.assertFalse(publish["journal"]["rollbackPerformed"])
        self.assertFalse(receipt["dailyPriceDependency"]["modifiedInStage2A"])
        self.assertFalse(receipt["macroAuthorityDecision"]["publishedInStage2A"])
        self.assertFalse(receipt["actionable"])

    def test_phase_a_stage2b_receipt_accepts_only_canonical_five_cell_repair(self) -> None:
        receipt = json.loads(
            (
                ROOT
                / "contracts"
                / "p1008_research_plugin"
                / "acceptance"
                / "v1.1"
                / "PHASE_A_MACRO_STAGE2B_PUBLISH_RECEIPT.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(
            receipt["acceptanceStatus"],
            "OWNER_APPROVED_MACRO_STAGE2B_PUBLISH",
        )
        self.assertEqual(
            receipt["approvalPhrase"],
            "OWNER_APPROVE_MACRO_HON_HAI_REV_YOY_REMEDIATION",
        )
        self.assertEqual(receipt["canonicalOrdinals"], [1, 26, 27, 28, 29])
        self.assertEqual(receipt["physicalLines"], [23, 48, 49, 50, 51])
        self.assertEqual(receipt["changedColumn"], "Hon_Hai_Rev_YoY")
        self.assertEqual(receipt["changedRecordCount"], 5)
        self.assertEqual(receipt["addedRows"], 0)
        self.assertEqual(receipt["removedRows"], 0)
        self.assertFalse(receipt["unapprovedSevenRowsAccepted"])
        self.assertEqual(receipt["transactionStatus"], "PUBLISHED")
        self.assertFalse(receipt["rollbackTriggered"])
        self.assertFalse(receipt["actionable"])

    def test_phase_a_final_closure_preserves_owner_gates_and_phase_boundary(self) -> None:
        receipt_ref = self.record["authorityBaselineReceipts"]["PHASE_A_CLOSURE_SIX"]
        receipt = json.loads(
            (ROOT / receipt_ref["path"]).read_text(encoding="utf-8")
        )
        self.assertEqual(
            receipt["acceptanceStatus"],
            "PHASE_A_AUTHORITY_DATA_CLOSURE_COMPLETE",
        )
        self.assertEqual(
            receipt["phaseAStatus"], "AUTHORITY_DATA_CLOSURE_COMPLETE"
        )
        self.assertTrue(receipt["candidateFirstLauncher"])
        self.assertFalse(receipt["automaticFormalCsvPublish"])
        self.assertFalse(receipt["automaticReportGeneration"])
        self.assertTrue(receipt["ownerGateRequired"])
        self.assertFalse(receipt["phaseBStarted"])
        self.assertEqual(receipt["openAiCalls"], 0)
        self.assertEqual(receipt["webSearchCalls"], 0)
        self.assertEqual(receipt["canvaCalls"], 0)
        self.assertFalse(receipt["actionable"])

    def test_prior_phase_a_stage1_receipt_remains_immutable(self) -> None:
        receipt_path = (
            ROOT
            / "contracts"
            / "p1008_research_plugin"
            / "acceptance"
            / "v1.1"
            / "PHASE_A_DAILY_PRICE_STAGE1_PUBLISH_RECEIPT.json"
        )
        self.assertEqual(
            hashlib.sha256(
                self.runner.git_blob_bytes(
                    ROOT, receipt_path.relative_to(ROOT).as_posix()
                )
            ).hexdigest().upper(),
            "C9C73AAE1185F21E5194526D006A966169C81CCC1E924DBCE6625212CD242984",
        )

    def test_prior_phase_a_baseline_receipt_remains_immutable(self) -> None:
        receipt_path = (
            ROOT
            / "contracts"
            / "p1008_research_plugin"
            / "acceptance"
            / "v1.1"
            / "PHASE_A_AUTHORITY_BASELINE_RECEIPT.json"
        )
        self.assertEqual(
            hashlib.sha256(self.runner.git_blob_bytes(ROOT, receipt_path.relative_to(ROOT).as_posix())).hexdigest().upper(),
            "550CD7C0EA961E4643F708AE066740AEC4F69B662E9A45A79C3248814737478B",
        )

    def test_phase_a_receipt_hash_uses_canonical_git_blob(self) -> None:
        receipt_ref = self.record["authorityBaselineReceipts"]["PHASE_A_CLOSURE_SIX"]
        committed = self.runner.git_blob_bytes(ROOT, receipt_ref["path"])
        worktree = (ROOT / receipt_ref["path"]).read_bytes()
        self.assertEqual(self.runner.sha256_bytes(committed), receipt_ref["sha256"])
        self.assertEqual(
            self.runner.normalize_checkout_eol(worktree),
            self.runner.normalize_checkout_eol(committed),
        )

    def test_committed_row_identity_evidence_matches_owner_approved_bytes(self) -> None:
        path = (
            ROOT
            / "contracts"
            / "p1008_research_plugin"
            / "acceptance"
            / "v1.1"
            / "evidence"
            / "PHASE_A_MACRO_ROW_IDENTITY_RECEIPT.json"
        )
        self.assertEqual(
            hashlib.sha256(path.read_bytes()).hexdigest().upper(),
            "E72989762053D20665DD87DA263F8B4DB1E77D277A6A27FD6C8AABBFE4921B9D",
        )

    def test_unapproved_eighth_authority_file_fails_closed(self) -> None:
        current = list(self.record["authorityBaselines"]["integratedSeven"])
        current.append("data/unapproved.csv")
        with self.assertRaisesRegex(AssertionError, "Unknown authority baseline"):
            self.runner.classify_authority_paths(current, self.record)

    def test_actual_current_module_is_non_actionable_and_protected(self) -> None:
        module = ROOT / "modules" / "p1008_research_plugin"
        self.assertEqual(self.runner.protected_write_violations(module), [])
        self.assertEqual(self.runner.actionable_violations(module), [])


if __name__ == "__main__":
    unittest.main()
