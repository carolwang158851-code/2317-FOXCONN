from __future__ import annotations

import sys
import importlib.util
import unittest
from pathlib import Path
from unittest import mock


MODULE_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = MODULE_ROOT.parents[1]
sys.path.insert(0, str(MODULE_ROOT / "src"))

from p1008_research_plugin.adapters import anysearch_runtime
from p1008_research_plugin.adapters.official_ir_evidence_adapter import (
    OfficialIREvidenceAdapter,
    OfficialIREvidenceError,
)
from p1008_research_plugin.contract_loader import ContractLoader
from p1008_research_plugin.governance import GovernanceBoundary, GovernanceError
from p1008_research_plugin.phaseb1_common import PhaseB1BoundaryError, atomic_write
from p1008_research_plugin.phaseb1_pipeline import PhaseB1Pipeline
from p1008_research_plugin.reporting.owner_communication_renderer import (
    OwnerCommunicationRenderer,
)


class FilesystemWriterCoverageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.governance = GovernanceBoundary(ContractLoader(PACKAGE_ROOT))

    def test_official_ir_writer_allows_only_canonical_runtime_root(self) -> None:
        adapter = OfficialIREvidenceAdapter.__new__(OfficialIREvidenceAdapter)
        adapter.package_root = PACKAGE_ROOT
        adapter.filesystem_governance = self.governance
        allowed = (
            PACKAGE_ROOT
            / "runtime"
            / "official_ir_evidence"
            / "P1008-OFFICIAL-IR-TEST"
            / "scan_result.json"
        )
        self.assertEqual(adapter._authorize_output(allowed), allowed.resolve())
        denied = (
            PACKAGE_ROOT / "data" / "escape.json",
            PACKAGE_ROOT / "ui" / "escape.json",
            PACKAGE_ROOT / ".git" / "escape.json",
            PACKAGE_ROOT.parent / "P1008_SIBLING" / "escape.json",
            Path.home() / "AppData" / "Local" / "P1008" / "escape.json",
            Path("C:/Windows/Temp") / "p1008-ir-escape.json",
        )
        for target in denied:
            with self.subTest(target=target), self.assertRaises(
                OfficialIREvidenceError
            ):
                adapter._authorize_output(target)

    def test_anysearch_exact_root_is_centrally_authorized(self) -> None:
        envelope = {"actionable": False, "authority_writes": 0}
        staging = PACKAGE_ROOT / "runtime" / "anysearch_staging"
        with mock.patch.object(anysearch_runtime, "atomic_write") as writer:
            result = anysearch_runtime.write_staging_output(envelope, staging)
        self.assertEqual(result, (staging / "latest_smoke.json").resolve())
        self.assertEqual(writer.call_args.kwargs["capability"], "ANYSEARCH_STAGING")
        for target in (
            staging / "alternative",
            PACKAGE_ROOT / "runtime" / "other_staging",
            PACKAGE_ROOT.parent / "P1008_SIBLING" / "runtime" / "anysearch_staging",
        ):
            with self.subTest(target=target), self.assertRaisesRegex(
                anysearch_runtime.GovernedAnySearchRuntimeError,
                "UNAUTHORIZED_WRITE_ATTEMPT",
            ):
                anysearch_runtime.write_staging_output(envelope, target)

    def test_owner_renderer_output_and_profile_cleanup_are_exact(self) -> None:
        renderer = OwnerCommunicationRenderer.__new__(OwnerCommunicationRenderer)
        renderer.filesystem_governance = self.governance
        output = PACKAGE_ROOT / "runtime" / "owner_communication" / "P1008-TEST"
        profile = output / ".edge-profile"
        self.assertEqual(renderer.authorize_output_dir(output), output.resolve())
        with mock.patch.object(Path, "is_dir", return_value=True):
            self.assertEqual(
                renderer.authorize_profile_cleanup(output, profile),
                profile.resolve(),
            )
        for target in (
            PACKAGE_ROOT,
            PACKAGE_ROOT / "data",
            PACKAGE_ROOT / "contracts",
            PACKAGE_ROOT / "modules",
            PACKAGE_ROOT / "ui",
            PACKAGE_ROOT / "_archive",
            PACKAGE_ROOT / "_inventory",
            PACKAGE_ROOT.parent / "P1008_SIBLING",
        ):
            with self.subTest(target=target), self.assertRaises(RuntimeError):
                renderer.authorize_output_dir(target)
        for target, parent in ((output, output.parent), (output.parent, output)):
            with self.subTest(target=target), self.assertRaises(RuntimeError):
                renderer.authorize_profile_cleanup(parent, target)

    def test_common_atomic_writer_cannot_bypass_central_authorization(self) -> None:
        for target in (
            PACKAGE_ROOT / "data" / "atomic-bypass.json",
            PACKAGE_ROOT / "ui" / "atomic-bypass.json",
            PACKAGE_ROOT.parent / "P1008_SIBLING" / "atomic-bypass.json",
        ):
            with self.subTest(target=target), self.assertRaises(
                PhaseB1BoundaryError
            ):
                atomic_write(target, b"{}\n")

    def test_maintenance_capability_isolated_to_exact_review_tree(self) -> None:
        review = (
            PACKAGE_ROOT
            / "runtime"
            / "phaseb1_final_owner_review"
            / "P1008-PHASE-B1-FINAL-OWNER-REVIEW-R2-TEST"
        )
        pipeline_root = review / "_pipeline"
        self.assertEqual(
            self.governance.authorize_write("MAINTENANCE_CAPABILITY", review),
            review.resolve(),
        )
        pipeline = PhaseB1Pipeline(
            PACKAGE_ROOT, output_capability="MAINTENANCE_CAPABILITY"
        )
        run_root = pipeline._run_root("P1008-MAINTENANCE-TEST", pipeline_root)
        self.assertEqual(run_root, pipeline_root / "P1008-MAINTENANCE-TEST")
        with mock.patch.object(Path, "is_dir", return_value=True):
            self.assertEqual(
                self.governance.authorize_tree_delete(
                    "MAINTENANCE_CAPABILITY",
                    pipeline_root,
                    owned_parent=review,
                    expected_name="_pipeline",
                ),
                pipeline_root.resolve(),
            )
        for target in (
            PACKAGE_ROOT / "data",
            PACKAGE_ROOT / ".git",
            PACKAGE_ROOT.parent / "P1008_SIBLING",
        ):
            with self.subTest(target=target), self.assertRaises(GovernanceError):
                self.governance.authorize_write("MAINTENANCE_CAPABILITY", target)

    def test_final_review_tool_rejects_path_injection(self) -> None:
        tool = PACKAGE_ROOT / "tools" / "p1008_build_phaseb1_final_review.py"
        spec = importlib.util.spec_from_file_location("p1008_gfs1p1_review_tool", tool)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader if spec else None)
        module = importlib.util.module_from_spec(spec)
        assert spec is not None and spec.loader is not None
        spec.loader.exec_module(module)
        allowed = module.authorized_review_root(PACKAGE_ROOT, "GFS1P1-TEST")
        self.assertEqual(
            allowed.parent,
            (PACKAGE_ROOT / "runtime" / "phaseb1_final_owner_review").resolve(),
        )
        for stamp in ("../../data", "../../../P1008_SIBLING"):
            with self.subTest(stamp=stamp), self.assertRaises(GovernanceError):
                module.authorized_review_root(PACKAGE_ROOT, stamp)


if __name__ == "__main__":
    unittest.main()
