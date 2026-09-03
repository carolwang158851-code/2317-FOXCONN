from __future__ import annotations

import json
import os
import shutil
import stat
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
SRC = ROOT / "modules" / "p1008_research_plugin" / "src"
for item in (str(TOOLS), str(SRC)):
    if item not in sys.path:
        sys.path.insert(0, item)

import warroom_report_trigger_runtime as runtime  # noqa: E402
from p1008_research_plugin.phaseb1_pipeline import PhaseB1Pipeline  # noqa: E402


EXPECTED = "F014BE750095543B35ED2D482C0CF7A40B4A448167796F8AC4560AB928E609C5"
REVISED = "24E61BEFB2F87FC3582B0C7A1187DF35F5976EA49C11421DE324151180B7F7E8"
COMPAT = ROOT / "runtime" / "q2_historical_compatibility" / "F014BE750095543B_EDITORIAL_V1"


def _remove_tree(path: Path) -> None:
    def clear_read_only(function, target, _exc):
        os.chmod(target, stat.S_IWRITE)
        function(target)

    if path.exists():
        shutil.rmtree(path, onexc=clear_read_only)


class Q2AuthorityHandoffSelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not (COMPAT / "q2_historical_compatibility_manifest.json").is_file():
            raise unittest.SkipTest("governed Q2 compatibility evidence is unavailable")

    def test_live_revised_evidence_is_retained_but_contract_authority_is_selected(self):
        live_path = ROOT / "runtime/research_plugin/latest_content_integration.json"
        before = runtime._sha256_path(live_path)
        live = json.loads(live_path.read_text(encoding="utf-8"))
        self.assertIn(REVISED, {item.get("source_hash") for item in live["validated_event_evidence"]})

        selected, trigger, context = runtime.resolve_analysis_authority(ROOT)

        self.assertEqual(selected, COMPAT.resolve())
        self.assertEqual(context["selectedRawSha256"], EXPECTED)
        self.assertTrue(context["liveEvidenceRetained"])
        self.assertEqual(trigger["canonical_event_id"], "HON_HAI_FY2026_Q2_EARNINGS")
        self.assertEqual(runtime._sha256_path(live_path), before)

    def test_exact_current_contract_authority_is_preferred_when_available(self):
        with mock.patch.dict(
            os.environ, {runtime.GOVERNED_EVIDENCE_ROOT_ENV: str(COMPAT)}
        ):
            selected, _trigger, context = runtime.resolve_analysis_authority(ROOT)
        self.assertEqual(selected, COMPAT.resolve())
        self.assertEqual(context["selection"], "EXACT_CURRENT_CONTRACT_AUTHORITY")
        self.assertEqual(context["selectedRawSha256"], EXPECTED)

    def test_missing_compatibility_fails_closed(self):
        controlled = Path(os.environ["LOCALAPPDATA"]) / "P1008" / "pytest-temp"
        controlled.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=controlled, prefix="q2-selector-missing-") as temp:
            with self.assertRaisesRegex(
                runtime.RuntimeTriggerError, "Q2_CONTRACT_AUTHORITY_UNAVAILABLE"
            ):
                runtime.resolve_analysis_authority(
                    ROOT, compatibility_parent=Path(temp)
                )

    def test_tampered_compatibility_lineage_fails_closed(self):
        controlled = Path(os.environ["LOCALAPPDATA"]) / "P1008" / "pytest-temp"
        controlled.mkdir(parents=True, exist_ok=True)
        temp = Path(tempfile.mkdtemp(dir=controlled, prefix="q2-selector-tamper-"))
        try:
            candidate = temp / "candidate"
            shutil.copytree(COMPAT, candidate)
            trigger_path = candidate / "report_trigger/latest_decision.json"
            trigger = json.loads(trigger_path.read_text(encoding="utf-8"))
            trigger["candidate_workflow"]["historical_compatibility"][
                "originalRawSha256"
            ] = REVISED
            trigger_path.write_text(
                json.dumps(trigger, ensure_ascii=False, sort_keys=True), encoding="utf-8"
            )
            with self.assertRaisesRegex(
                runtime.RuntimeTriggerError, "Q2_CONTRACT_AUTHORITY_UNAVAILABLE"
            ):
                runtime.resolve_analysis_authority(
                    ROOT, compatibility_parent=temp
                )
        finally:
            _remove_tree(temp)

    def test_selection_is_deterministic_and_real_q2_analysis_uses_contract_sha(self):
        first = runtime.resolve_analysis_authority(ROOT)
        second = runtime.resolve_analysis_authority(ROOT)
        self.assertEqual(first, second)
        evidence_root, trigger, _context = first
        lineage = runtime.trigger_lineage(trigger)
        controlled = ROOT / "runtime/report_production/test_scratch"
        output = controlled / f"q2-authority-selector-{uuid.uuid4().hex}"
        output.mkdir(parents=True)
        try:
            result = PhaseB1Pipeline(
                ROOT, governed_evidence_root=evidence_root
            ).build_analysis(output_base=output, trigger_lineage=lineage)
            evidence = json.loads(
                (Path(result["run_root"]) / "evidence_manifest.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(evidence["sourceHash"], EXPECTED)
            self.assertEqual(result["analysis"].event_type, "QUARTERLY_EARNINGS")
        finally:
            _remove_tree(output)
            try:
                controlled.rmdir()
            except OSError:
                pass


if __name__ == "__main__":
    unittest.main()
