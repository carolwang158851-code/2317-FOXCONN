from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from uuid import uuid4


MODULE_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = MODULE_ROOT.parents[1]
sys.path.insert(0, str(MODULE_ROOT / "src"))

from p1008_research_plugin.contract_loader import ContractLoader
from p1008_research_plugin.events.catalog import EventCatalog
from p1008_research_plugin.governance import GovernanceBoundary, GovernanceError
from p1008_research_plugin.ledgers.store import LedgerError, LedgerStore
from p1008_research_plugin.phaseb1_common import PhaseB1BoundaryError, atomic_write
from p1008_research_plugin.phaseb1_pipeline import PhaseB1Pipeline


class FilesystemGovernanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.loader = ContractLoader(PACKAGE_ROOT)
        self.governance = GovernanceBoundary(self.loader)
        self.created: list[Path] = []

    def tearDown(self) -> None:
        for path in sorted(self.created, key=lambda item: len(item.parts), reverse=True):
            if path.is_symlink() or path.is_file():
                path.unlink(missing_ok=True)
            elif path.exists():
                shutil.rmtree(path, ignore_errors=False)
        for relative in (
            Path("runtime/research_plugin/ledgers"),
            Path("runtime/research_plugin"),
            Path("runtime/report_production"),
            Path("runtime"),
        ):
            try:
                (PACKAGE_ROOT / relative).rmdir()
            except OSError:
                pass

    def _track(self, path: Path) -> Path:
        self.created.append(path)
        return path

    def test_allowed_plugin_root_supports_mkdir_and_atomic_write(self) -> None:
        root = self._track(
            PACKAGE_ROOT / "runtime" / "research_plugin" / f"gfs1-{uuid4().hex}"
        )
        target = root / "candidate.json"
        authorized = self.governance.authorize_write(
            "RESEARCH_PLUGIN_RUNTIME", target
        )
        authorized.parent.mkdir(parents=True)
        atomic_write(authorized, b"{}\n", capability="RESEARCH_PLUGIN_RUNTIME")
        self.assertEqual(authorized.read_bytes(), b"{}\n")

    def test_all_declared_write_capabilities_are_package_bounded(self) -> None:
        capabilities = self.governance.policy["filesystemCapabilities"]
        declared_roots = [
            (PACKAGE_ROOT / relative).resolve()
            for relative in self.governance.policy["writeRoots"]
        ]
        for capability, relative_roots in capabilities.items():
            for relative in relative_roots:
                with self.subTest(capability=capability, root=relative):
                    authorized = self.governance.authorize_write(
                        capability, PACKAGE_ROOT / relative
                    )
                    self.assertTrue(authorized.is_relative_to(PACKAGE_ROOT))
                    self.assertTrue(
                        any(authorized.is_relative_to(root) for root in declared_roots)
                    )

    def test_repository_lifecycle_capabilities_remain_forbidden(self) -> None:
        for capability in (
            "GIT_MUTATION",
            "REPOSITORY_LIFECYCLE",
            "CREATE_WORKTREE",
            "REMOVE_WORKTREE",
            "MOVE_PACKAGE",
            "COPY_PACKAGE",
            "DELETE_PACKAGE",
        ):
            with self.subTest(capability=capability), self.assertRaises(
                GovernanceError
            ):
                self.governance.reject_capability(capability)

    def test_phaseb1_default_and_declared_output_are_authorized(self) -> None:
        pipeline = PhaseB1Pipeline(PACKAGE_ROOT)
        expected = (
            PACKAGE_ROOT / "runtime" / "report_production" / "P1008-GFS1"
        ).resolve()
        self.assertEqual(pipeline._run_root("P1008-GFS1", None), expected)
        self.assertEqual(
            pipeline._run_root("P1008-GFS1", expected.parent), expected
        )

    def test_phaseb1_default_pipeline_preserves_report_semantics(self) -> None:
        result = PhaseB1Pipeline(PACKAGE_ROOT).run_all()
        run_root = self._track(Path(result["run_root"]))
        self.assertTrue(
            run_root.is_relative_to(PACKAGE_ROOT / "runtime" / "report_production")
        )
        self.assertFalse(result["report"].actionable)
        self.assertEqual(result["report"].report_contract_version, "1.0")

    def test_traversal_and_undeclared_capability_fail_closed(self) -> None:
        with self.assertRaises(GovernanceError):
            self.governance.authorize_write(
                "RESEARCH_PLUGIN_RUNTIME",
                Path("runtime/research_plugin/../../data/escape.json"),
            )
        with self.assertRaises(GovernanceError):
            self.governance.authorize_write("REPOSITORY_MAINTENANCE", PACKAGE_ROOT)

    def test_production_and_external_roots_fail_closed(self) -> None:
        denied = (
            PACKAGE_ROOT / "data" / "escape.csv",
            PACKAGE_ROOT / "ui" / "escape.html",
            PACKAGE_ROOT / ".git" / "config",
            PACKAGE_ROOT / "_archive" / "escape.json",
            PACKAGE_ROOT / "_inventory" / "escape.json",
            PACKAGE_ROOT.parent / "P1008_SIBLING_PACKAGE" / "escape.json",
            Path.home() / "AppData" / "Local" / "P1008" / "data" / "warroom.sqlite3",
            Path(tempfile.gettempdir()) / "p1008-arbitrary" / "escape.json",
        )
        for target in denied:
            with self.subTest(target=target), self.assertRaises(GovernanceError):
                self.governance.authorize_write("RESEARCH_PLUGIN_RUNTIME", target)

    def test_caller_defined_phaseb1_output_and_external_ledger_fail_closed(self) -> None:
        pipeline = PhaseB1Pipeline(PACKAGE_ROOT)
        with self.assertRaises(PhaseB1BoundaryError):
            pipeline._run_root("P1008-GFS1", PACKAGE_ROOT.parent / "arbitrary-output")
        catalog = EventCatalog(self.loader)
        with self.assertRaises(LedgerError):
            LedgerStore(
                PACKAGE_ROOT,
                PACKAGE_ROOT.parent / "arbitrary-ledger",
                self.loader,
                catalog,
            )

    def test_ledger_append_is_allowed_only_in_declared_root(self) -> None:
        sandbox = self._track(
            PACKAGE_ROOT
            / "runtime"
            / "research_plugin"
            / "ledgers"
            / f"gfs1-{uuid4().hex}"
        )
        catalog = EventCatalog(self.loader)
        store = LedgerStore(PACKAGE_ROOT, sandbox, self.loader, catalog)
        definition = catalog.events["RUN_STARTED"]
        event = {
            "event_id": "GFS1-LEDGER-001",
            "event_type": "RUN_STARTED",
            "aggregate_type": definition["aggregateType"],
            "aggregate_id": "GFS1-RUN",
            "occurred_at": "2026-08-30T00:00:00+00:00",
            "actor_type": definition["allowedActors"][0],
            "actor_id": "GFS1-TEST",
            "causation_event_id": None,
            "correlation_id": "GFS1",
            "payload": {},
            "owner_review_required": bool(definition["ownerReviewRequired"]),
            "effective_change_applied": False,
            "actionable": False,
        }
        record = store.append_event("inference_chain", event)
        self.assertEqual(record["sequence"], 1)
        self.assertEqual(len(store.read_records("inference_chain")), 1)

    def test_existing_reparse_component_fails_closed(self) -> None:
        root = self._track(
            PACKAGE_ROOT / "runtime" / "research_plugin" / f"gfs1-{uuid4().hex}"
        )
        root.mkdir(parents=True)
        with mock.patch.object(
            GovernanceBoundary,
            "_is_reparse_point",
            side_effect=lambda path: path == root,
        ):
            with self.assertRaisesRegex(GovernanceError, "reparse"):
                self.governance.authorize_write(
                    "RESEARCH_PLUGIN_RUNTIME", root / "escape.json"
                )

    def test_symlink_escape_fails_closed_where_supported(self) -> None:
        root = self._track(
            PACKAGE_ROOT / "runtime" / "research_plugin" / f"gfs1-{uuid4().hex}"
        )
        root.mkdir(parents=True)
        external = self._track(
            PACKAGE_ROOT.parent / f".gfs1-symlink-target-{uuid4().hex}"
        )
        external.mkdir()
        link = root / "link"
        try:
            os.symlink(external, link, target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"symlink creation unavailable: {exc}")
        with self.assertRaises(GovernanceError):
            self.governance.authorize_write(
                "RESEARCH_PLUGIN_RUNTIME", link / "escape.json"
            )


if __name__ == "__main__":
    unittest.main()
