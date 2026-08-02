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
    "launcher.html": "A0D5CAFDE151CCCCA5342AB719D83130A775965C64429CCE26092FED50FCDDC5",
    "tools/p1008_app_server.py": "B29A78E3F5F89026C2B116149186FBAADE6993A13F4137FDAEF6D7C498E8ADDD",
    "data/CSV_AUTHORITY_MANIFEST.json": "7DC97FFBC0E3F5E73E8085ACC25DD61E0F3588FCE04C360B4F19FA0D86AFA01B",
    "rules/RULE_STATUS_MANIFEST.json": "054DA1FDAF0C75BB27B56DF45B96F1CC1720558D44C700F1AB70AB0280A2FE5C",
    "contracts/p1008_research_plugin/v1.0/contract.manifest.json": "5D213CB4360329FCC969164F559952A0F1545BFE8E53D5CFDFF014B9D5619773",
}
PHASEB1_OPS_BOUNDARY_HASHES = {
    "launcher.html": "7A25A766D50F2A8514B5C51166FAD5274C6F05B58DB252CE97A325A0508BA998",
    "tools/p1008_app_server.py": "282C68BA845CC5CB3EC27AF14D9606806BB27F5312E5851F8E2822F9C959FFEA",
}
LEGACY_BOUNDARY_HASHES = {
    "launcher.html": "B638D39A9F6D6316389D16C67B68394F114F0B65EDBDFF6DCB69476C60A41448",
    "tools/p1008_app_server.py": "1381156A978274DF62DD693AEB71BC787607D3BF1D38BA786707D11D714E24D7",
}
PHASEB1_MVP_BOUNDARY_HASHES = {
    "launcher.html": "41B349691AB6CDEDE6D622F4B5A7FE0ED707F42B8D7BD6D2CD6776EAC2607F91",
    "tools/p1008_app_server.py": "03FC1742F308E245B66237CD415FE0BE2184ACFB4E7D0FB2086EF609027B242B",
}
PHASEB1_ACCEPTANCE_RECORD = (
    PACKAGE_ROOT
    / "contracts"
    / "p1008_report_production"
    / "acceptance"
    / "v1.0"
    / "PHASE_B1_OWNER_AUTHORIZATION_RECORD.json"
)
PHASEB1_ACCEPTANCE_SHA256 = (
    "67AE473810DFD0C01049FDAA32FE5A7685297CBE579808C6A77475BB297C110D"
)
PHASEB1_OPS_ACCEPTANCE_RECORD = (
    PACKAGE_ROOT
    / "contracts"
    / "p1008_report_production"
    / "acceptance"
    / "v1.1"
    / "PHASE_B1_OPS_OWNER_AUTHORIZATION_RECORD.json"
)
PHASEB1_OPS_ACCEPTANCE_SHA256 = (
    "4AD5A1622DC421865E99E62FC6636E104A30E706179971815A3B3CBAFDF53B3B"
)
PHASEB1_OPS_R1_ACCEPTANCE_RECORD = (
    PACKAGE_ROOT
    / "contracts"
    / "p1008_report_production"
    / "acceptance"
    / "v1.1"
    / "PHASE_B1_OPS_R1_OWNER_AUTHORIZATION_RECORD.json"
)
PHASEB1_OPS_R1_ACCEPTANCE_SHA256 = (
    "ED5AF459990F5390F39CDAC1DEBBA0CFCFFA20E8438E67087C0F29488DB092B6"
)
LEGACY_AUTHORITY_MANIFEST_SHA256 = (
    "8BA304C36C224F1F8ADF78CB871A8200FDA0656BD5824801330EAF6EAF855847"
)
PHASE_A_CLOSURE_MANIFEST_SHA256 = (
    "966352C4DD34938240901095DE5937C69C9BE8638413C2F900977C5EDBAA9C67"
)
INTEGRATED_AUTHORITY_MANIFEST_SHA256 = BASELINE_HASHES[
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

    def test_phaseb1_boundary_changes_are_owner_authorized_and_versioned(self) -> None:
        self.assertEqual(sha256(PHASEB1_ACCEPTANCE_RECORD), PHASEB1_ACCEPTANCE_SHA256)
        receipt = json.loads(PHASEB1_ACCEPTANCE_RECORD.read_text(encoding="utf-8"))
        self.assertEqual(receipt["phase"], "PHASE_B1")
        self.assertTrue(receipt["implementationAuthorized"])
        self.assertFalse(receipt["finalAcceptanceGranted"])
        self.assertNotIn("acceptedBy", receipt)
        self.assertEqual(
            receipt["authorizationPhrase"],
            "OWNER_APPROVE_P1008_PHASE_B1_ANALYSIS_REPORT_MVP_53323CC2",
        )
        changes = receipt["authorizedBoundaryChanges"]
        self.assertEqual(set(changes), set(LEGACY_BOUNDARY_HASHES))
        for relative, legacy_hash in LEGACY_BOUNDARY_HASHES.items():
            with self.subTest(path=relative):
                self.assertEqual(changes[relative]["baseSha256"], legacy_hash)
                self.assertEqual(
                    changes[relative]["phaseB1Sha256"], PHASEB1_MVP_BOUNDARY_HASHES[relative]
                )
        self.assertTrue(receipt["constraints"]["formalAuthorityReadOnly"])
        self.assertFalse(receipt["actionable"])

    def test_phaseb1_ops_boundary_changes_are_separately_authorized(self) -> None:
        self.assertEqual(
            sha256(PHASEB1_OPS_ACCEPTANCE_RECORD), PHASEB1_OPS_ACCEPTANCE_SHA256
        )
        receipt = json.loads(PHASEB1_OPS_ACCEPTANCE_RECORD.read_text(encoding="utf-8"))
        self.assertEqual(receipt["phase"], "PHASE_B1_OPS")
        self.assertEqual(
            receipt["base"]["commit"],
            "bfe19f353a7c26676507beeeb566a6ad60fcbedf",
        )
        self.assertTrue(receipt["implementationAuthorized"])
        self.assertFalse(receipt["finalAcceptanceGranted"])
        self.assertEqual(receipt["deliveryBoundary"], "DRAFT_PR_ONLY")
        self.assertTrue(receipt["constraints"]["formalAuthorityReadOnly"])
        self.assertTrue(receipt["constraints"]["rollingBriefNonArchival"])
        self.assertEqual(
            receipt["authorizedBoundaryChanges"]["launcher.html"][
                "phaseB1OpsSha256"
            ],
            PHASEB1_OPS_BOUNDARY_HASHES["launcher.html"],
        )
        self.assertEqual(
            receipt["authorizedBoundaryChanges"]["tools/p1008_app_server.py"][
                "phaseB1OpsSha256"
            ],
            PHASEB1_OPS_BOUNDARY_HASHES["tools/p1008_app_server.py"],
        )
        self.assertFalse(receipt["actionable"])

    def test_phaseb1_ops_r1_boundary_changes_are_separately_authorized(self) -> None:
        self.assertEqual(
            sha256(PHASEB1_OPS_R1_ACCEPTANCE_RECORD),
            PHASEB1_OPS_R1_ACCEPTANCE_SHA256,
        )
        receipt = json.loads(
            PHASEB1_OPS_R1_ACCEPTANCE_RECORD.read_text(encoding="utf-8")
        )
        self.assertEqual(receipt["phase"], "PHASE_B1_OPS_R1")
        self.assertEqual(receipt["pullRequest"], 10)
        self.assertEqual(
            receipt["priorHead"],
            "3bcc36db1b2822bf53cdd4b1631380ca42196f6c",
        )
        self.assertEqual(
            receipt["priorAuthorization"]["sha256"],
            PHASEB1_OPS_ACCEPTANCE_SHA256,
        )
        self.assertTrue(receipt["implementationAuthorized"])
        self.assertFalse(receipt["finalAcceptanceGranted"])
        self.assertEqual(receipt["deliveryBoundary"], "DRAFT_PR_ONLY")
        for relative, change in receipt["authorizedBoundaryChanges"].items():
            with self.subTest(path=relative):
                self.assertEqual(
                    sha256(PACKAGE_ROOT / relative),
                    change["phaseB1OpsR1Sha256"],
                )
        self.assertTrue(receipt["constraints"]["formalAuthorityReadOnly"])
        self.assertTrue(receipt["constraints"]["rollingBriefNonArchival"])
        self.assertTrue(receipt["constraints"]["phaseB1Point5NotStarted"])
        self.assertTrue(receipt["constraints"]["phaseB2NotStarted"])
        self.assertFalse(receipt["actionable"])

    def test_contract_root_still_matches_owner_accepted_hash(self) -> None:
        result = self.loader.verify_manifest()
        self.assertEqual(
            result["root_hash"],
            "3370C4DBD6B564E2200D051AC07C8507442C130ADE64D770621107FA09D2924D",
        )

    def test_authority_manifest_baseline_migration_is_versioned(self) -> None:
        fixture = json.loads(AUTHORITY_BASELINE_FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual(
            fixture["legacy"]["manifestSha256"], LEGACY_AUTHORITY_MANIFEST_SHA256
        )
        self.assertEqual(fixture["legacy"]["verifiedFileCount"], 5)
        self.assertEqual(
            fixture["phaseAClosureSix"]["manifestSha256"],
            PHASE_A_CLOSURE_MANIFEST_SHA256,
        )
        self.assertEqual(fixture["phaseAClosureSix"]["verifiedFileCount"], 6)
        self.assertEqual(
            fixture["integratedSeven"]["manifestSha256"],
            INTEGRATED_AUTHORITY_MANIFEST_SHA256,
        )
        self.assertEqual(fixture["integratedSeven"]["verifiedFileCount"], 7)
        self.assertEqual(
            fixture["integratedSeven"]["addedPath"],
            "data/2317_cash_flow_authority.csv",
        )
        self.assertNotEqual(
            PHASE_A_CLOSURE_MANIFEST_SHA256,
            INTEGRATED_AUTHORITY_MANIFEST_SHA256,
        )


if __name__ == "__main__":
    unittest.main()
