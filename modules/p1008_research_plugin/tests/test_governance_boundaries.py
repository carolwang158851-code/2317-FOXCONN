from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
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
    "data/CSV_AUTHORITY_MANIFEST.json": "90870F2CBE5F17F0B0BC1033D056542D2F9DDA96F94BCB81E8BF7018817E86F9",
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
PHASEB1_OPS_R2_ACCEPTANCE_RECORD = (
    PACKAGE_ROOT
    / "contracts"
    / "p1008_report_production"
    / "acceptance"
    / "v1.1"
    / "PHASE_B1_OPS_R2_OWNER_AUTHORIZATION_RECORD.json"
)
PHASEB1_OPS_R2_ACCEPTANCE_SHA256 = (
    "76D58C43D8622A1F069D554D0B435756EE1679E48DF54EF78EC4714DE1E8C781"
)
PHASEB1_OPS_R2_R1_PORTABILITY_AMENDMENT = (
    PACKAGE_ROOT
    / "contracts"
    / "p1008_report_production"
    / "acceptance"
    / "v1.1"
    / "PHASE_B1_OPS_R2_R1_CROSS_PLATFORM_BOUNDARY_PORTABILITY_AMENDMENT.json"
)
R2_ORIGINAL_HEAD = "48900b7d88202e06926caa7cdf6781f36de66c02"
R2_PARENT_HEAD = "5f744c458d0af270602723e3b6e6ca75777d3f58"
R2_LINK_FROM = "output/ui-concepts/P1008_WARROOM_COMMAND_CENTER_v24.html"
R2_LINK_TO = "ui/P1008_WARROOM_COMMAND_CENTER_v24.html"
LEGACY_AUTHORITY_MANIFEST_SHA256 = (
    "8BA304C36C224F1F8ADF78CB871A8200FDA0656BD5824801330EAF6EAF855847"
)
PHASE_A_CLOSURE_MANIFEST_SHA256 = (
    "966352C4DD34938240901095DE5937C69C9BE8638413C2F900977C5EDBAA9C67"
)
INTEGRATED_AUTHORITY_MANIFEST_SHA256 = (
    "7DC97FFBC0E3F5E73E8085ACC25DD61E0F3588FCE04C360B4F19FA0D86AFA01B"
)
AUTHORITY_BASELINE_FIXTURE = (
    MODULE_ROOT / "tests" / "fixtures" / "authority_baselines.json"
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def canonical_git_blob_bytes(relative: str, revision: str = "HEAD") -> bytes:
    if not relative or relative.startswith("/") or ".." in Path(relative).parts:
        raise ValueError(f"invalid governed path: {relative!r}")
    result = subprocess.run(
        ["git", "-C", str(PACKAGE_ROOT), "cat-file", "blob", f"{revision}:{relative}"],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        raise ValueError(
            f"canonical Git blob unavailable for {revision}:{relative}: "
            f"{result.stderr.decode('utf-8', errors='replace').strip()}"
        )
    if not result.stdout:
        raise ValueError(f"canonical Git blob is empty for {revision}:{relative}")
    return result.stdout


def verify_portability_boundary(
    relative: str, entry: dict[str, object], revision: str = "HEAD"
) -> None:
    expected = entry.get("canonicalGitBlobSha256")
    blob_id = entry.get("canonicalGitBlobId")
    if not isinstance(expected, str) or not re.fullmatch(r"[A-F0-9]{64}", expected):
        raise ValueError(f"missing or invalid canonical SHA for {relative}")
    if not isinstance(blob_id, str) or not re.fullmatch(r"[0-9a-f]{40}", blob_id):
        raise ValueError(f"missing or invalid canonical blob ID for {relative}")
    actual = hashlib.sha256(
        canonical_git_blob_bytes(relative, revision)
    ).hexdigest().upper()
    if actual != expected:
        raise ValueError(
            f"canonical Git blob SHA mismatch for {relative}: {actual} != {expected}"
        )


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
        temp_dir = tempfile.mkdtemp(prefix=".p1008-boundary-", dir=PACKAGE_ROOT.parent)
        try:
            store = LedgerStore(PACKAGE_ROOT, Path(temp_dir), self.loader, catalog)
            self.assertEqual(store.read_all(), {key: [] for key in sorted(store.ledgers)})
        finally:
            # A local synchronization service can retain the directory handle; this
            # cleanup must not obscure the boundary assertion that already passed.
            shutil.rmtree(temp_dir, ignore_errors=True)
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

    def test_phaseb1_ops_r1_receipt_remains_immutable(self) -> None:
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
        self.assertEqual(
            receipt["authorizedBoundaryChanges"]["launcher.html"]["phaseB1OpsR1Sha256"],
            "A0D5CAFDE151CCCCA5342AB719D83130A775965C64429CCE26092FED50FCDDC5",
        )
        self.assertTrue(receipt["constraints"]["formalAuthorityReadOnly"])
        self.assertTrue(receipt["constraints"]["rollingBriefNonArchival"])
        self.assertTrue(receipt["constraints"]["phaseB1Point5NotStarted"])
        self.assertTrue(receipt["constraints"]["phaseB2NotStarted"])
        self.assertFalse(receipt["actionable"])

    def test_phaseb1_ops_r2_receipt_remains_immutable(self) -> None:
        self.assertEqual(
            sha256(PHASEB1_OPS_R2_ACCEPTANCE_RECORD),
            PHASEB1_OPS_R2_ACCEPTANCE_SHA256,
        )
        receipt = json.loads(
            PHASEB1_OPS_R2_ACCEPTANCE_RECORD.read_text(encoding="utf-8")
        )
        self.assertEqual(receipt["phase"], "PHASE_B1_OPS_R2")
        self.assertEqual(receipt["pullRequest"], 10)
        self.assertEqual(receipt["priorHead"], "5f744c458d0af270602723e3b6e6ca75777d3f58")
        self.assertEqual(
            receipt["authorizationPhrase"],
            "OWNER_APPROVE_P1008_PHASE_B1_OPS_R2_CLEAN_CLONE_BOOTSTRAP_5F744C45",
        )
        self.assertTrue(receipt["implementationAuthorized"])
        self.assertFalse(receipt["finalAcceptanceGranted"])
        self.assertEqual(receipt["deliveryBoundary"], "DRAFT_PR_ONLY")
        self.assertTrue(receipt["constraints"]["formalAuthorityReadOnly"])
        self.assertTrue(receipt["constraints"]["rollingBriefNonArchival"])
        self.assertTrue(receipt["constraints"]["phaseB1Point5NotStarted"])
        self.assertTrue(receipt["constraints"]["phaseB2NotStarted"])
        self.assertFalse(receipt["actionable"])

    def test_phaseb1_ops_r2_r1_portability_amendment_uses_canonical_git_blobs(
        self,
    ) -> None:
        historical = json.loads(
            PHASEB1_OPS_R2_ACCEPTANCE_RECORD.read_text(encoding="utf-8")
        )
        amendment = json.loads(
            PHASEB1_OPS_R2_R1_PORTABILITY_AMENDMENT.read_text(encoding="utf-8")
        )
        self.assertEqual(
            amendment["amendmentType"],
            "CROSS_PLATFORM_BOUNDARY_BASELINE_PORTABILITY",
        )
        self.assertEqual(
            amendment["defectClassification"],
            "MIXED_BASELINE_PROVENANCE_DEFECT",
        )
        self.assertEqual(amendment["originalR2Candidate"], R2_ORIGINAL_HEAD)
        self.assertTrue(amendment["originalR2AuthorizationReceipt"]["historicalRecordPreserved"])
        self.assertFalse(amendment["productionSemanticContentChangedByAmendment"])
        self.assertFalse(amendment["authorityChanged"])
        self.assertFalse(amendment["ruleHoldMidrMrdChanged"])
        self.assertFalse(amendment["sqliteChanged"])
        self.assertFalse(amendment["actionable"])

        boundaries = amendment["canonicalBoundaries"]
        self.assertEqual(
            set(boundaries),
            {
                "SOP_v4.html",
                "report_viewer.html",
                "reports.html",
                "src/index_p1008_v7.source.html",
                "dist/index_p1008_v7.bundle.js",
            },
        )
        for relative, entry in boundaries.items():
            with self.subTest(path=relative):
                self.assertEqual(
                    entry["historicalReceiptSha256"],
                    historical["authorizedBoundaryChanges"][relative][
                        "phaseB1OpsR2Sha256"
                    ],
                )
                verify_portability_boundary(relative, entry, R2_ORIGINAL_HEAD)
                canonical = canonical_git_blob_bytes(relative, R2_ORIGINAL_HEAD)
                self.assertEqual(
                    canonical_git_blob_bytes(relative, R2_PARENT_HEAD).replace(
                        R2_LINK_FROM.encode("utf-8"), R2_LINK_TO.encode("utf-8")
                    ),
                    canonical,
                )
                self.assertEqual(
                    hashlib.sha256(canonical.replace(b"\n", b"\r\n")).hexdigest().upper()
                    != entry["canonicalGitBlobSha256"],
                    True,
                )

    def test_phaseb1_ops_r2_r1_canonical_identity_fails_closed(self) -> None:
        amendment = json.loads(
            PHASEB1_OPS_R2_R1_PORTABILITY_AMENDMENT.read_text(encoding="utf-8")
        )
        entry = dict(amendment["canonicalBoundaries"]["SOP_v4.html"])
        with self.assertRaisesRegex(ValueError, "unavailable"):
            canonical_git_blob_bytes("missing-governed-boundary.html")
        entry.pop("canonicalGitBlobSha256")
        with self.assertRaisesRegex(ValueError, "missing or invalid canonical SHA"):
            verify_portability_boundary("SOP_v4.html", entry)
        wrong = dict(amendment["canonicalBoundaries"]["SOP_v4.html"])
        wrong["canonicalGitBlobSha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "canonical Git blob SHA mismatch"):
            verify_portability_boundary("SOP_v4.html", wrong)

    def test_phaseb1_ops_r2_r1_explicit_eol_policies_remain_declared(self) -> None:
        for relative in ("report_viewer.html", "reports.html"):
            with self.subTest(path=relative):
                result = subprocess.run(
                    ["git", "-C", str(PACKAGE_ROOT), "check-attr", "eol", "--", relative],
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                self.assertEqual(result.stdout.strip(), f"{relative}: eol: lf")

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
