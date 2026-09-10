from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = (
    ROOT
    / "contracts"
    / "p1008_research_plugin"
    / "conformance"
    / "v1.1"
    / "run_contract_tests.py"
)
SPEC = importlib.util.spec_from_file_location("p1008_current_conformance", RUNNER_PATH)
assert SPEC is not None and SPEC.loader is not None
RUNNER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = RUNNER
SPEC.loader.exec_module(RUNNER)


class CurrentAuthorityAmendmentConformanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.record = RUNNER.read_json(
            ROOT
            / "contracts"
            / "p1008_research_plugin"
            / "acceptance"
            / "v1.1"
            / "PHASE_ROUTING_ACCEPTANCE_RECORD.json"
        )
        cls.original_git_blob_bytes = staticmethod(RUNNER.git_blob_bytes)
        cls.original_normalize_checkout_eol = staticmethod(RUNNER.normalize_checkout_eol)

    def validate(self) -> dict[str, object]:
        return RUNNER.validate_authority_manifest(ROOT, self.record)

    def validation_fixture(self) -> tuple[tempfile.TemporaryDirectory[str], Path, dict[str, object]]:
        temporary = tempfile.TemporaryDirectory(prefix="p1008-authority-classes-")
        root = Path(temporary.name)
        manifest = RUNNER.read_json(ROOT / "data" / "CSV_AUTHORITY_MANIFEST.json")
        paths = [item["path"] for item in RUNNER._manifest_entries(manifest)]
        for relative in paths:
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((ROOT / relative).read_bytes())
        manifest_path = root / "data" / "CSV_AUTHORITY_MANIFEST.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        record = {
            "authorityBaselines": {
                "legacyFive": paths,
                "currentSix": [],
                "phaseAClosureSix": [],
                "integratedSeven": [],
            }
        }
        return temporary, root, record

    def validate_fixture(self, root: Path, record: dict[str, object]) -> dict[str, object]:
        def blob(_root: Path, relative: str, revision: str = "HEAD") -> bytes:
            if revision == "HEAD":
                return (root / relative).read_bytes()
            return self.original_git_blob_bytes(ROOT, relative, revision)

        with mock.patch.object(RUNNER, "git_blob_bytes", side_effect=blob):
            return RUNNER.validate_authority_manifest(root, record)

    def test_production_authority_filesystem_mismatch_is_hard_failure(self) -> None:
        temporary, root, record = self.validation_fixture()
        with temporary:
            path = root / "data" / "2317_master_v9.csv"
            path.write_bytes(path.read_bytes() + b"tamper")
            with self.assertRaisesRegex(
                AssertionError, "PRODUCTION_AUTHORITY_HASH_MISMATCH"
            ):
                self.validate_fixture(root, record)

    def test_research_current_state_can_differ_from_historical_baseline(self) -> None:
        temporary, root, record = self.validation_fixture()
        with temporary:
            result = self.validate_fixture(root, record)
            self.assertEqual(result["productionAuthority"], "PASS")
            self.assertEqual(result["researchCurrentStateLineage"], "PASS")
            self.assertEqual(result["productionAuthorityFilesVerified"], 4)
            self.assertEqual(result["researchCurrentStateFilesVerified"], 3)

    def test_research_current_state_mismatch_is_classified_separately(self) -> None:
        temporary, root, record = self.validation_fixture()
        with temporary:
            path = root / "data" / "macro_snapshot.csv"
            path.write_bytes(path.read_bytes() + b"tamper")
            with self.assertRaisesRegex(
                AssertionError, "NON_AUTHORITATIVE_RESEARCH_LINEAGE_MISMATCH"
            ):
                self.validate_fixture(root, record)

    def test_reconciled_master_matches_owner_approved_manifest_hash(self) -> None:
        temporary, root, record = self.validation_fixture()
        with temporary:
            result = self.validate_fixture(root, record)
            manifest = RUNNER.read_json(root / "data" / "CSV_AUTHORITY_MANIFEST.json")
            master = next(
                item
                for item in manifest["authoritativeFiles"]
                if item["path"] == "data/2317_master_v9.csv"
            )
            self.assertEqual(RUNNER.sha256_file(root / master["path"]), master["sha256"])
            self.assertEqual(result["productionAuthority"], "PASS")

    def mutated_amendment(self, mutate: object) -> tuple[bytes, str]:
        original = self.original_git_blob_bytes(
            ROOT, RUNNER.CURRENT_AUTHORITY_AMENDMENT_PATH
        )
        document = json.loads(original.decode("utf-8-sig"))
        mutate(document)
        changed = (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode()
        return changed, hashlib.sha256(changed).hexdigest().upper()

    def validate_with_amendment(self, changed: bytes, changed_hash: str) -> None:
        def blob(root: Path, relative: str, revision: str = "HEAD") -> bytes:
            if relative == RUNNER.CURRENT_AUTHORITY_AMENDMENT_PATH:
                return changed
            return self.original_git_blob_bytes(root, relative, revision)

        with (
            mock.patch.object(RUNNER, "git_blob_bytes", side_effect=blob),
            mock.patch.object(
                RUNNER, "CURRENT_AUTHORITY_AMENDMENT_SHA256", changed_hash
            ),
            mock.patch.object(
                RUNNER,
                "normalize_checkout_eol",
                side_effect=lambda value: (
                    self.original_normalize_checkout_eol(
                        changed
                        if value
                        == (
                            ROOT / RUNNER.CURRENT_AUTHORITY_AMENDMENT_PATH
                        ).read_bytes()
                        else value
                    )
                ),
            ),
        ):
            self.validate()

    def test_historical_receipt_remains_historical_while_current_chain_passes(self) -> None:
        historical = json.loads(
            self.original_git_blob_bytes(
                ROOT,
                "contracts/p1008_research_plugin/acceptance/v1.1/"
                "PHASE_A_FINAL_INTEGRATION_AMENDMENT_RECEIPT.json",
            ).decode("utf-8-sig")
        )
        self.assertEqual(
            historical["authorityFiles"]["data/2317_daily_price.csv"],
            "2581AF868AA0D8C4BFCEA913B156DBB515AF3929FAAE7D0FDC947EA4A8256304",
        )
        self.assertEqual(
            historical["authorityFiles"]["data/2317_daily_market_activity.csv"],
            "FE7B33B649012E7D8143838793FE5ED6244BB2183B966C0DAD2C9775FB0E4807",
        )
        self.assertTrue(self.validate()["authorityReceiptVerified"])

    def test_missing_current_amendment_fails_closed(self) -> None:
        with mock.patch.object(
            RUNNER,
            "CURRENT_AUTHORITY_AMENDMENT_PATH",
            "contracts/p1008_research_plugin/acceptance/v1.1/MISSING.json",
        ):
            with self.assertRaisesRegex(AssertionError, "receipt is missing"):
                self.validate()

    def test_wrong_price_hash_in_amendment_fails_closed(self) -> None:
        changed, changed_hash = self.mutated_amendment(
            lambda value: value["authorityFiles"].__setitem__(
                "data/2317_daily_price.csv", "0" * 64
            )
        )
        with self.assertRaisesRegex(AssertionError, "committed authority bytes"):
            self.validate_with_amendment(changed, changed_hash)

    def test_wrong_market_activity_hash_in_amendment_fails_closed(self) -> None:
        changed, changed_hash = self.mutated_amendment(
            lambda value: value["authorityFiles"].__setitem__(
                "data/2317_daily_market_activity.csv", "0" * 64
            )
        )
        with self.assertRaisesRegex(AssertionError, "committed authority bytes"):
            self.validate_with_amendment(changed, changed_hash)

    def test_wrong_manifest_hash_in_amendment_fails_closed(self) -> None:
        changed, changed_hash = self.mutated_amendment(
            lambda value: value["authorityManifest"].__setitem__("sha256", "0" * 64)
        )
        with self.assertRaisesRegex(AssertionError, "manifest mismatch"):
            self.validate_with_amendment(changed, changed_hash)

    def test_broken_predecessor_fails_closed(self) -> None:
        changed, changed_hash = self.mutated_amendment(
            lambda value: value["previousReceipt"].__setitem__("sha256", "0" * 64)
        )
        with self.assertRaisesRegex(AssertionError, "predecessor identity mismatch"):
            self.validate_with_amendment(changed, changed_hash)

    def test_undeclared_authority_fails_closed(self) -> None:
        manifest_path = ROOT / "data" / "CSV_AUTHORITY_MANIFEST.json"
        manifest = RUNNER.read_json(manifest_path)
        changed = copy.deepcopy(manifest)
        changed["authoritativeFiles"].append(
            {
                "path": "data/undeclared_authority.csv",
                "sha256": "0" * 64,
            }
        )
        original_read_json = RUNNER.read_json

        def read_json(path: Path) -> dict[str, object]:
            if Path(path) == manifest_path:
                return changed
            return original_read_json(path)

        with mock.patch.object(RUNNER, "read_json", side_effect=read_json):
            with self.assertRaisesRegex(AssertionError, "Unknown authority baseline"):
                self.validate()


if __name__ == "__main__":
    unittest.main()
