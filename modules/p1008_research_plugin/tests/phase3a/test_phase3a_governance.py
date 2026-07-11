from __future__ import annotations

import hashlib
import re
import sys
import unittest
from pathlib import Path


MODULE_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = MODULE_ROOT.parents[1]
SRC_ROOT = MODULE_ROOT / "src" / "p1008_research_plugin" / "capabilities"
sys.path.insert(0, str(MODULE_ROOT / "src"))

from p1008_research_plugin.capabilities import GovernedCapabilityFramework


PROTECTED = (
    "modules/p1008_research_plugin/src/p1008_research_plugin/runtime/runtime_manager.py",
    "modules/p1008_research_plugin/src/p1008_research_plugin/runtime/capability_registry.py",
    "modules/p1008_research_plugin/docs/phase2a/Phase2A_Closure_Report.md",
    "contracts/p1008_research_plugin/v1.0/contract.manifest.json",
    "contracts/p1008_research_plugin/v2.0/contract.manifest.json",
    "launcher.html",
    "data/CSV_AUTHORITY_MANIFEST.json",
    "rules/RULE_STATUS_MANIFEST.json",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


class Phase3AGovernanceTests(unittest.TestCase):
    def test_framework_does_not_change_protected_files(self) -> None:
        before = {relative: sha256(PACKAGE_ROOT / relative) for relative in PROTECTED}
        snapshot = GovernedCapabilityFramework(PACKAGE_ROOT).snapshot()
        self.assertEqual(snapshot["conformance"]["status"], "PASS")
        after = {relative: sha256(PACKAGE_ROOT / relative) for relative in PROTECTED}
        self.assertEqual(after, before)

    def test_source_has_no_sdk_network_database_or_secret_access(self) -> None:
        pattern = re.compile(
            r"^\s*(?:from|import)\s+(?:openai|agents|requests|httpx|socket|urllib\.request|http\.client|sqlite3)\b|OPENAI_API_KEY|os\.environ",
            re.MULTILINE,
        )
        violations = [
            path.relative_to(MODULE_ROOT).as_posix()
            for path in SRC_ROOT.rglob("*.py")
            if pattern.search(path.read_text(encoding="utf-8"))
        ]
        self.assertEqual(violations, [])

    def test_disabled_manifests_have_no_provider_or_operations(self) -> None:
        framework = GovernedCapabilityFramework(PACKAGE_ROOT)
        for capability in ("financial", "macro", "news", "deep_research", "foreign_flow"):
            manifest = framework.registry.get(capability)
            self.assertFalse(manifest.enabled)
            self.assertFalse(manifest.implementation_available)
            self.assertIsNone(manifest.provider_id)
            self.assertEqual(manifest.allowed_operations, ())


if __name__ == "__main__":
    unittest.main()
