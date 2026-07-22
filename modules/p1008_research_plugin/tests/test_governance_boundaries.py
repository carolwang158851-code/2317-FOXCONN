from __future__ import annotations

import hashlib
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = MODULE_ROOT.parents[1]
sys.path.insert(0, str(MODULE_ROOT / "src"))

from p1008_research_plugin.contract_loader import ContractLoader
from p1008_research_plugin.events.catalog import EventCatalog
from p1008_research_plugin.governance import GovernanceBoundary, GovernanceError
from p1008_research_plugin.ledgers.store import LedgerStore


BASELINE_HASHES = {
    "launcher.html": "8BE1CAAAF3A516E02EA373D749FD3870CB756072D48A9038657B3BBCD7B540A5",
    "tools/p1008_app_server.py": "45C906977F42E416B532D3EF4C8909AE7AE07A618C7B62F5D515973B99A882A5",
    "data/CSV_AUTHORITY_MANIFEST.json": "8E15782AB300EDB1F17F5043CBAC1B888EFA7F1A2FD9CBB8B43814429949C953",
    "rules/RULE_STATUS_MANIFEST.json": "054DA1FDAF0C75BB27B56DF45B96F1CC1720558D44C700F1AB70AB0280A2FE5C",
    "contracts/p1008_research_plugin/v1.0/contract.manifest.json": "5D213CB4360329FCC969164F559952A0F1545BFE8E53D5CFDFF014B9D5619773",
}
LEGACY_AUTHORITY_MANIFEST_SHA256 = (
    "8BA304C36C224F1F8ADF78CB871A8200FDA0656BD5824801330EAF6EAF855847"
)
CURRENT_AUTHORITY_MANIFEST_SHA256 = BASELINE_HASHES[
    "data/CSV_AUTHORITY_MANIFEST.json"
]
AUTHORITY_BASELINE_FIXTURE = (
    MODULE_ROOT / "tests" / "fixtures" / "authority_baselines.json"
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


class GovernanceBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.loader = ContractLoader(PACKAGE_ROOT)
        self.governance = GovernanceBoundary(self.loader)

    def test_frozen_forbidden_capabilities_remain_rejected(self) -> None:
        for capability in (
            "AUTO_PUBLISH",
            "WRITE_FORMAL_CSV",
            "WRITE_RUNTIME_SQLITE",
            "ENABLE_RULE",
            "CHANGE_HOLD",
            "CHANGE_MIDR",
            "OPENAI_CALL",
        ):
            with self.assertRaises(GovernanceError):
                self.governance.reject_capability(capability)

    def test_target_module_has_no_openai_import(self) -> None:
        pattern = re.compile(r"^\s*(from\s+openai|import\s+openai)", re.MULTILINE)
        violations = []
        for path in (MODULE_ROOT / "src").rglob("*.py"):
            if pattern.search(path.read_text(encoding="utf-8")):
                violations.append(path.relative_to(MODULE_ROOT).as_posix())
        self.assertEqual(violations, [])

    def test_no_non_target_baseline_changed_by_temp_ledger(self) -> None:
        before = {relative: sha256(PACKAGE_ROOT / relative) for relative in BASELINE_HASHES}
        self.assertEqual(before, BASELINE_HASHES)
        catalog = EventCatalog(self.loader)
        with tempfile.TemporaryDirectory(
            prefix=".p1008-boundary-", dir=PACKAGE_ROOT.parent
        ) as temp_dir:
            store = LedgerStore(PACKAGE_ROOT, Path(temp_dir), self.loader, catalog)
            self.assertEqual(store.read_all(), {key: [] for key in sorted(store.ledgers)})
        after = {relative: sha256(PACKAGE_ROOT / relative) for relative in BASELINE_HASHES}
        self.assertEqual(after, before)

    def test_authority_manifest_baseline_migration_is_versioned(self) -> None:
        fixture = json.loads(AUTHORITY_BASELINE_FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual(
            fixture["legacy"]["manifestSha256"], LEGACY_AUTHORITY_MANIFEST_SHA256
        )
        self.assertEqual(fixture["legacy"]["verifiedFileCount"], 5)
        self.assertEqual(
            fixture["current"]["manifestSha256"], CURRENT_AUTHORITY_MANIFEST_SHA256
        )
        self.assertEqual(fixture["current"]["verifiedFileCount"], 6)
        self.assertEqual(
            fixture["current"]["addedPath"],
            "data/2317_cash_flow_authority.csv",
        )
        self.assertNotEqual(
            LEGACY_AUTHORITY_MANIFEST_SHA256, CURRENT_AUTHORITY_MANIFEST_SHA256
        )

    def test_contract_root_still_matches_owner_accepted_hash(self) -> None:
        result = self.loader.verify_manifest()
        self.assertEqual(
            result["root_hash"],
            "3370C4DBD6B564E2200D051AC07C8507442C130ADE64D770621107FA09D2924D",
        )


if __name__ == "__main__":
    unittest.main()
