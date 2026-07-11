from __future__ import annotations

import hashlib
import re
import sys
import unittest
from pathlib import Path


MODULE_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = MODULE_ROOT.parents[1]
SRC_ROOT = MODULE_ROOT / "src" / "p1008_research_plugin"
sys.path.insert(0, str(MODULE_ROOT / "src"))

from p1008_research_plugin.orchestrator import ResearchOrchestrator
from p1008_research_plugin.runtime.runtime_validator import RuntimeContractVerifier


PROTECTED = (
    "launcher.html",
    "tools/p1008_app_server.py",
    "data/CSV_AUTHORITY_MANIFEST.json",
    "rules/RULE_STATUS_MANIFEST.json",
    "contracts/p1008_research_plugin/v1.0/contract.manifest.json",
    "contracts/p1008_research_plugin/v2.0/contract.manifest.json",
    "contracts/p1008_research_plugin/acceptance/v2.0/OWNER_ACCEPTANCE_RECORD.json",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


class Phase2ABoundaryTests(unittest.TestCase):
    def test_frozen_contracts_verify_before_execution(self) -> None:
        result = RuntimeContractVerifier(PACKAGE_ROOT).verify()
        self.assertTrue(result["v2_authoritative"])
        self.assertEqual(
            result["v2_root"],
            "E056357A8A63A15BCF9FDC286BEE0BDB56E043AF26F4DDCD5624FDB3707BD782",
        )

    def test_pipeline_does_not_change_protected_files(self) -> None:
        before = {relative: sha256(PACKAGE_ROOT / relative) for relative in PROTECTED}
        ResearchOrchestrator(PACKAGE_ROOT).run({"symbol": "2317", "question": "test"})
        after = {relative: sha256(PACKAGE_ROOT / relative) for relative in PROTECTED}
        self.assertEqual(after, before)

    def test_phase2a_source_has_no_sdk_network_or_secret_access(self) -> None:
        pattern = re.compile(
            r"^\s*(?:from|import)\s+(?:openai|agents|requests|httpx|socket|urllib\.request|http\.client)\b",
            re.MULTILINE,
        )
        violations = []
        secret_reads = []
        for path in SRC_ROOT.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            if pattern.search(text):
                violations.append(path.relative_to(MODULE_ROOT).as_posix())
            if "OPENAI_API_KEY" in text or "os.environ" in text:
                secret_reads.append(path.relative_to(MODULE_ROOT).as_posix())
        self.assertEqual(violations, [])
        self.assertEqual(secret_reads, [])

    def test_no_runtime_or_governance_store_is_created(self) -> None:
        watched = [
            PACKAGE_ROOT / "runtime" / "research_plugin" / "artifacts",
            PACKAGE_ROOT / "runtime" / "research_plugin" / "governance",
        ]
        before = [path.exists() for path in watched]
        ResearchOrchestrator(PACKAGE_ROOT).run({"symbol": "2317", "question": "test"})
        self.assertEqual([path.exists() for path in watched], before)


if __name__ == "__main__":
    unittest.main()
