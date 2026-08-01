from __future__ import annotations

import copy
import hashlib
import json
import shutil
import sys
import tempfile
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
        self.assertEqual(verified["verified_count"], 7)
        self.assertEqual(
            self.authority.manifest_summary()["authority_baseline_version"],
            AuthorityAdapter.INTEGRATED_BASELINE_VERSION,
        )
        self.assertEqual(
            set(self.authority.listed_paths),
            AuthorityAdapter.INTEGRATED_AUTHORITY_PATHS,
        )
        self.assertIn(
            "data/2317_cash_flow_authority.csv",
            {item["relative_path"] for item in verified["verified"]},
        )
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

    def _manifest(self) -> dict[str, object]:
        return json.loads(
            (PACKAGE_ROOT / "data" / "CSV_AUTHORITY_MANIFEST.json").read_text(
                encoding="utf-8"
            )
        )

    def _copy_manifest_files(
        self,
        root: Path,
        manifest: dict[str, object],
        *,
        omit: set[str] | None = None,
        additionally_copy: set[str] | None = None,
    ) -> None:
        omitted = omit or set()
        entries = manifest["authoritativeFiles"] + manifest["nonAuthoritativeFiles"]
        for entry in entries:
            relative = entry["path"]
            if relative in omitted:
                continue
            destination = root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(PACKAGE_ROOT / relative, destination)
        for relative in additionally_copy or set():
            destination = root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(PACKAGE_ROOT / relative, destination)
        manifest_path = root / "data" / "CSV_AUTHORITY_MANIFEST.json"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def test_integrated_baseline_missing_cash_flow_fails_closed(self) -> None:
        manifest = self._manifest()
        with tempfile.TemporaryDirectory(prefix="p1008-authority-missing-") as temp:
            root = Path(temp)
            self._copy_manifest_files(
                root, manifest, omit={"data/2317_cash_flow_authority.csv"}
            )
            adapter = AuthorityAdapter(root, self.loader)
            with self.assertRaises(AuthorityAdapterError):
                adapter.verify_all()

    def test_cash_flow_hash_mismatch_fails_closed(self) -> None:
        manifest = self._manifest()
        with tempfile.TemporaryDirectory(prefix="p1008-authority-hash-") as temp:
            root = Path(temp)
            self._copy_manifest_files(root, manifest)
            cash = root / "data" / "2317_cash_flow_authority.csv"
            cash.write_bytes(cash.read_bytes() + b"\n")
            adapter = AuthorityAdapter(root, self.loader)
            with self.assertRaises(AuthorityAdapterError):
                adapter.verify_all()

    def test_unauthorized_eighth_manifest_path_fails_closed(self) -> None:
        manifest = self._manifest()
        manifest["nonAuthoritativeFiles"].append(
            {
                "path": "data/unauthorized_eighth.csv",
                "sha256": hashlib.sha256(b"x\n").hexdigest().upper(),
            }
        )
        with tempfile.TemporaryDirectory(prefix="p1008-authority-extra-") as temp:
            root = Path(temp)
            self._copy_manifest_files(
                root, manifest, omit={"data/unauthorized_eighth.csv"}
            )
            extra = root / "data" / "unauthorized_eighth.csv"
            extra.write_bytes(b"x\n")
            with self.assertRaises(AuthorityAdapterError):
                AuthorityAdapter(root, self.loader)

    def test_legacy_manifest_cannot_hide_existing_cash_flow_file(self) -> None:
        manifest = copy.deepcopy(self._manifest())
        manifest["manifestVersion"] = "1.2.2"
        manifest.pop("authorityBaselineIntegration", None)
        manifest["authoritativeFiles"] = [
            entry
            for entry in manifest["authoritativeFiles"]
            if entry["path"]
            not in {
                "data/2317_cash_flow_authority.csv",
                "data/2317_daily_market_activity.csv",
            }
        ]
        with tempfile.TemporaryDirectory(prefix="p1008-authority-hidden-") as temp:
            root = Path(temp)
            self._copy_manifest_files(
                root,
                manifest,
                additionally_copy={"data/2317_cash_flow_authority.csv"},
            )
            with self.assertRaises(AuthorityAdapterError):
                AuthorityAdapter(root, self.loader)


if __name__ == "__main__":
    unittest.main()
