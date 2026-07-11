from __future__ import annotations

import sys
import unittest
from pathlib import Path


MODULE_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = MODULE_ROOT.parents[1]
sys.path.insert(0, str(MODULE_ROOT / "src"))

from p1008_research_plugin.adapters.authority_adapter import (
    AuthorityAdapter,
    AuthorityAdapterError,
)
from p1008_research_plugin.adapters.runtime_snapshot_adapter import (
    RuntimeSnapshotAdapter,
    RuntimeSnapshotError,
)
from p1008_research_plugin.contract_loader import ContractLoader


class ReadOnlyAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.loader = ContractLoader(PACKAGE_ROOT)
        self.authority = AuthorityAdapter(PACKAGE_ROOT, self.loader)
        self.runtime = RuntimeSnapshotAdapter(PACKAGE_ROOT)

    def test_comment_aware_csv_read_and_hash(self) -> None:
        snapshot = self.authority.read_csv("data/2317_master_v9.csv")
        self.assertTrue(snapshot.metadata_lines)
        self.assertEqual(snapshot.headers[0], "Quarter")
        self.assertIn("EPS_Q", snapshot.headers)
        self.assertEqual(snapshot.actual_sha256, snapshot.manifest_sha256)
        self.assertGreater(len(snapshot.rows), 0)
        with self.assertRaises(TypeError):
            snapshot.rows[0]["Quarter"] = "MUTATED"

    def test_observation_sidecars_remain_manifest_listed_reads(self) -> None:
        event = self.authority.read_csv("data/macro_event_observations.csv")
        fx = self.authority.read_csv("data/fx_trend_observations.csv")
        self.assertIn("Actionable", event.headers)
        self.assertIn("Actionable", fx.headers)
        self.assertTrue(all(row["Actionable"].lower() == "false" for row in event.rows))
        self.assertTrue(all(row["Actionable"].lower() == "false" for row in fx.rows))

    def test_unlisted_and_traversal_paths_are_rejected(self) -> None:
        with self.assertRaises(AuthorityAdapterError):
            self.authority.read_csv("data/2317_master_v10.csv")
        with self.assertRaises(AuthorityAdapterError):
            self.authority.read_csv("../rules/RULE_STATUS_MANIFEST.json")

    def test_rule_digest_and_keep_disabled_boundary(self) -> None:
        verified = self.authority.verify_all()
        self.assertEqual(verified["verified_count"], 5)
        summary = self.authority.read_rule_manifest()
        self.assertEqual(summary["keep_disabled_count"], 9)
        self.assertFalse(summary["actionable"])

    def test_runtime_snapshot_allowlist(self) -> None:
        results = self.runtime.read_all()
        self.assertEqual(len(results), 4)
        with self.assertRaises(RuntimeSnapshotError):
            self.runtime.read_snapshot("staging/2026-07-10/DRY_RUN.json")

    def test_adapters_expose_no_mutating_method(self) -> None:
        forbidden = {"write", "update", "delete", "append", "publish", "execute"}
        authority_methods = {name.lower() for name in dir(self.authority)}
        runtime_methods = {name.lower() for name in dir(self.runtime)}
        self.assertFalse(authority_methods & forbidden)
        self.assertFalse(runtime_methods & forbidden)


if __name__ == "__main__":
    unittest.main()
