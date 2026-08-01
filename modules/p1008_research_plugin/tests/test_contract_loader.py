from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


MODULE_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = MODULE_ROOT.parents[1]
sys.path.insert(0, str(MODULE_ROOT / "src"))

from p1008_research_plugin.contract_loader import ContractError, ContractLoader


class ContractLoaderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.loader = ContractLoader(PACKAGE_ROOT)
        self.status = json.loads(
            (MODULE_ROOT / "tests" / "fixtures" / "status_expected.json").read_text(
                encoding="utf-8"
            )
        )

    def test_frozen_root_and_references(self) -> None:
        result = self.loader.verify_manifest()
        self.assertEqual(result["artifact_count"], 43)
        self.assertEqual(
            result["root_hash"],
            "3370C4DBD6B564E2200D051AC07C8507442C130ADE64D770621107FA09D2924D",
        )
        references = self.loader.resolve_references()
        self.assertGreater(references["references_checked"], 0)

    def test_status_contract_subset_accepts_frozen_shape(self) -> None:
        self.assertEqual(self.loader.validate_status(self.status), self.status)

    def test_status_contract_rejects_missing_extra_and_const_drift(self) -> None:
        missing = dict(self.status)
        missing.pop("openai_enabled")
        with self.assertRaises(ContractError):
            self.loader.validate_status(missing)
        extra = {**self.status, "model": "forbidden"}
        with self.assertRaises(ContractError):
            self.loader.validate_status(extra)
        enabled = {**self.status, "actionable": True}
        with self.assertRaises(ContractError):
            self.loader.validate_status(enabled)

    def test_contract_path_traversal_is_rejected(self) -> None:
        with self.assertRaises(ContractError):
            self.loader.load_json("../data/CSV_AUTHORITY_MANIFEST.json")


if __name__ == "__main__":
    unittest.main()
