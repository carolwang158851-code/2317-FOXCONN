from __future__ import annotations

import copy
import hashlib
import json
import unittest
from pathlib import Path
from unittest import mock

from pydantic import ValidationError

try:
    from .helpers import PACKAGE_ROOT, authority_sandbox, fixture, scratch, write_fixture
except ImportError:  # direct discovery with phaseb1 as the start directory
    from helpers import PACKAGE_ROOT, authority_sandbox, fixture, scratch, write_fixture

from p1008_research_plugin.adapters.authority_adapter import AuthorityAdapter, AuthorityAdapterError
from p1008_research_plugin.analysis.analysis_contracts import AnalysisPacket
from p1008_research_plugin.analysis.analysis_validator import AnalysisValidationError, AnalysisValidator
from p1008_research_plugin.contract_loader import ContractLoader
from p1008_research_plugin.phaseb1_common import PhaseB1BoundaryError, ensure_runtime_output, protected_state_hashes
from p1008_research_plugin.phaseb1_pipeline import PhaseB1Pipeline, PhaseB1PipelineError


class PhaseB1AnalysisLayerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        with scratch("analysis-valid-") as output:
            result = PhaseB1Pipeline(PACKAGE_ROOT).run_all(output_base=output)
            cls.packet = result["analysis"]
            cls.evidence = PhaseB1Pipeline(PACKAGE_ROOT).load_inputs()[1]

    def test_valid_analysis_has_required_vocabulary_and_actionable_false(self) -> None:
        self.assertFalse(self.packet.actionable)
        self.assertEqual(self.packet.event_type, "MONTHLY_REVENUE")
        self.assertEqual(self.packet.analysis_contract_version, "1.0")
        self.assertEqual(len(self.packet.audience_lenses), 3)
        self.assertEqual(self.packet.financial_trend.free_cash_flow.status.value, "WATCH")
        self.assertEqual(self.packet.investor_views.new_money_view.value, "WAIT")
        self.assertEqual(self.packet.investor_views.existing_holding_view.value, "HOLD")

    def test_additive_contract_manifests_match_exact_artifact_bytes(self) -> None:
        for relative in ("contracts/p1008_analysis/v1.0", "contracts/p1008_report_production/v1.0"):
            root = PACKAGE_ROOT / relative
            manifest = json.loads((root / "contract.manifest.json").read_text(encoding="utf-8"))
            lines = []
            for artifact in manifest["artifacts"]:
                path = root / artifact["path"]
                digest = hashlib.sha256(path.read_bytes()).hexdigest().upper()
                self.assertEqual(digest, artifact["sha256"])
                self.assertEqual(path.stat().st_size, artifact["sizeBytes"])
                lines.append(f"{artifact['path']}|{digest}")
            root_hash = hashlib.sha256("\n".join(sorted(lines, key=str.casefold)).encode("utf-8")).hexdigest().upper()
            self.assertEqual(root_hash, manifest["rootHash"])

    def test_missing_authority_file_fails_closed(self) -> None:
        with scratch("missing-authority-") as root:
            package = authority_sandbox(root)
            (package / "data" / "2317_daily_price.csv").unlink()
            adapter = AuthorityAdapter(package, ContractLoader(package))
            with self.assertRaises(AuthorityAdapterError):
                adapter.verify_all()

    def test_extra_hidden_authority_file_fails_closed(self) -> None:
        with scratch("extra-authority-") as root:
            package = authority_sandbox(root)
            manifest_path = package / "data" / "CSV_AUTHORITY_MANIFEST.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["nonAuthoritativeFiles"].append({"path": "data/hidden.csv", "sha256": "0" * 64})
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            (package / "data" / "hidden.csv").write_text("x\n", encoding="utf-8")
            with self.assertRaises(AuthorityAdapterError):
                AuthorityAdapter(package, ContractLoader(package))

    def test_authority_manifest_hash_drift_fails_closed(self) -> None:
        with scratch("hash-drift-") as root:
            package = authority_sandbox(root)
            path = package / "data" / "2317_daily_price.csv"
            path.write_bytes(path.read_bytes() + b"\n")
            with self.assertRaises(AuthorityAdapterError):
                AuthorityAdapter(package, ContractLoader(package)).verify_all()

    def test_stale_evidence_fails_closed(self) -> None:
        with scratch("stale-evidence-") as root:
            payload = fixture()
            payload["packets"][0]["expires_on"] = "2026-07-26"
            with self.assertRaises(PhaseB1PipelineError):
                PhaseB1Pipeline(PACKAGE_ROOT, write_fixture(root, payload)).load_inputs()

    def test_unsupported_source_domain_fails_closed(self) -> None:
        with scratch("bad-domain-") as root:
            payload = fixture()
            payload["packets"][0]["evidence"][0]["source_locators"][0]["locator"] = "https://example.invalid/revenue"
            with self.assertRaises(PhaseB1PipelineError):
                PhaseB1Pipeline(PACKAGE_ROOT, write_fixture(root, payload)).load_inputs()

    def test_conflicting_official_evidence_fails_closed(self) -> None:
        with scratch("conflict-") as root:
            payload = fixture()
            payload["packets"][1]["evidence"][0]["field_values"]["revenue"] = "conflicting official value"
            with self.assertRaises(PhaseB1PipelineError):
                PhaseB1Pipeline(PACKAGE_ROOT, write_fixture(root, payload)).load_inputs()

    def test_missing_evidence_id_fails_closed(self) -> None:
        with scratch("missing-id-") as root:
            payload = fixture()
            payload["packets"][0]["evidence"][0].pop("evidence_id")
            with self.assertRaises(PhaseB1PipelineError):
                PhaseB1Pipeline(PACKAGE_ROOT, write_fixture(root, payload)).load_inputs()

    def test_invalid_source_tier_fails_closed(self) -> None:
        with scratch("bad-tier-") as root:
            payload = fixture()
            payload["packets"][0]["evidence"][0]["source_locators"][0]["source_tier"] = "SOCIAL_MEDIA"
            with self.assertRaises(PhaseB1PipelineError):
                PhaseB1Pipeline(PACKAGE_ROOT, write_fixture(root, payload)).load_inputs()

    def test_missing_counterevidence_and_alternative_fail_schema(self) -> None:
        payload = self.packet.model_dump(mode="json", by_alias=True)
        payload["materialConclusions"][0].pop("counterEvidence")
        with self.assertRaises(ValidationError):
            AnalysisPacket.model_validate(payload)
        payload = self.packet.model_dump(mode="json", by_alias=True)
        payload["materialConclusions"][0].pop("alternativeExplanation")
        with self.assertRaises(ValidationError):
            AnalysisPacket.model_validate(payload)

    def test_unknown_analysis_status_and_market_regime_fail_schema(self) -> None:
        payload = self.packet.model_dump(mode="json", by_alias=True)
        payload["financialTrend"]["revenue"]["status"] = "MAGIC"
        with self.assertRaises(ValidationError):
            AnalysisPacket.model_validate(payload)
        payload = self.packet.model_dump(mode="json", by_alias=True)
        payload["marketRegime"]["primaryRegime"] = "CERTAIN_RALLY"
        with self.assertRaises(ValidationError):
            AnalysisPacket.model_validate(payload)

    def test_unsupported_ai_revenue_claim_fails_closed(self) -> None:
        payload = self.packet.model_dump(mode="json", by_alias=True)
        payload["materialConclusions"][0]["statement"] = "AI revenue is confirmed."
        parsed = AnalysisPacket.model_validate(payload)
        with self.assertRaises(AnalysisValidationError):
            AnalysisValidator().validate(parsed, self.evidence)

    def test_runtime_boundary_rejects_formal_and_sqlite_paths(self) -> None:
        with self.assertRaises(PhaseB1BoundaryError):
            ensure_runtime_output(PACKAGE_ROOT, PACKAGE_ROOT / "data")
        with self.assertRaises(PhaseB1BoundaryError):
            ensure_runtime_output(PACKAGE_ROOT, Path.home() / "AppData" / "Local" / "P1008" / "data")

    def test_protected_state_drift_fails_closed(self) -> None:
        with scratch("protected-drift-") as output:
            baseline = protected_state_hashes(PACKAGE_ROOT)
            changed = dict(baseline)
            changed["runtime_sqlite"] = "DRIFT"
            with mock.patch(
                "p1008_research_plugin.phaseb1_pipeline.protected_state_hashes",
                side_effect=[baseline, changed],
            ):
                with self.assertRaises(PhaseB1PipelineError):
                    PhaseB1Pipeline(PACKAGE_ROOT).build_analysis(output_base=output)


if __name__ == "__main__":
    unittest.main()
