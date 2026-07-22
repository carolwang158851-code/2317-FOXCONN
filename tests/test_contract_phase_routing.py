from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = ROOT / "contracts" / "p1008_research_plugin" / "conformance" / "v1.1" / "run_contract_tests.py"
ROUTER_PATH = ROOT / "contracts" / "p1008_research_plugin" / "conformance" / "run_phase_conformance.py"
RECORD_PATH = ROOT / "contracts" / "p1008_research_plugin" / "acceptance" / "v1.1" / "PHASE_ROUTING_ACCEPTANCE_RECORD.json"


def load_runner():
    spec = importlib.util.spec_from_file_location("phase_routing_test_runner", RUNNER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load current conformance runner")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_router():
    spec = importlib.util.spec_from_file_location("phase_routing_test_router", ROUTER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load phase-aware conformance router")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class PhaseRoutingConformanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.runner = load_runner()
        cls.router = load_router()
        cls.record = json.loads(RECORD_PATH.read_text(encoding="utf-8"))

    def _tree(self, *, module: bool) -> tempfile.TemporaryDirectory[str]:
        holder = tempfile.TemporaryDirectory(prefix="p1008-phase-routing-test-")
        root = Path(holder.name)
        if module:
            (root / "modules" / "p1008_research_plugin" / "src" / "p1008_research_plugin").mkdir(parents=True)
        return holder

    def _module_with_source(self, source: str) -> tempfile.TemporaryDirectory[str]:
        holder = self._tree(module=True)
        path = Path(holder.name) / "modules" / "p1008_research_plugin" / "src" / "p1008_research_plugin" / "candidate.py"
        path.write_text(source, encoding="utf-8")
        return holder

    def test_legacy_tree_with_module_absent_passes(self) -> None:
        with self._tree(module=False) as root:
            self.runner.validate_module_state(Path(root), "ABSENT")

    def test_legacy_tree_with_module_present_fails(self) -> None:
        with self._tree(module=True) as root:
            with self.assertRaisesRegex(AssertionError, "exists early"):
                self.runner.validate_module_state(Path(root), "ABSENT")

    def test_current_phase_with_module_present_passes(self) -> None:
        with self._tree(module=True) as root:
            self.runner.validate_module_state(Path(root), "PRESENT")

    def test_current_phase_with_module_missing_fails(self) -> None:
        with self._tree(module=False) as root:
            with self.assertRaisesRegex(AssertionError, "module is missing"):
                self.runner.validate_module_state(Path(root), "PRESENT")

    def test_current_module_formal_csv_write_fails(self) -> None:
        source = 'from pathlib import Path\nPath("data/2317_daily_price.csv").write_text("bad")\n'
        with self._module_with_source(source) as root:
            module = Path(root) / "modules" / "p1008_research_plugin"
            self.assertTrue(self.runner.protected_write_violations(module))

    def test_current_module_rule_or_sqlite_write_fails(self) -> None:
        cases = (
            'from pathlib import Path\nPath("rules/RULE_STATUS_MANIFEST.json").write_text("bad")\n',
            'db = "warroom.sqlite3"\nsql = "UPDATE status SET value=1"\n',
        )
        for source in cases:
            with self.subTest(source=source):
                with self._module_with_source(source) as root:
                    module = Path(root) / "modules" / "p1008_research_plugin"
                    self.assertTrue(self.runner.protected_write_violations(module))

    def test_current_actionable_true_fails(self) -> None:
        with self._module_with_source("payload = {'actionable': True}\n") as root:
            module = Path(root) / "modules" / "p1008_research_plugin"
            self.assertTrue(self.runner.actionable_violations(module))

    def test_unknown_phase_fails_closed(self) -> None:
        value = dict(self.record)
        value["currentPhase"] = "UNKNOWN"
        with self.assertRaisesRegex(AssertionError, "Unknown or unsupported phase"):
            self.runner.validate_phase_record(value)

    def test_frozen_v1_bytes_and_root_hash_are_unchanged(self) -> None:
        result = self.runner.validate_immutable_v1(ROOT, self.record)
        self.assertEqual(result["rootHash"], "3370C4DBD6B564E2200D051AC07C8507442C130ADE64D770621107FA09D2924D")
        for relative, expected in self.record["immutableV1"]["artifacts"].items():
            actual = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest().upper()
            self.assertEqual(actual, expected)

    def test_push_and_pull_request_share_current_router(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "p1008-research-contract.yml").read_text(encoding="utf-8")
        self.assertIn("push:", workflow)
        self.assertIn("pull_request:", workflow)
        trigger_blocks = {
            name: tuple(re.findall(r'^      - "([^"]+)"$', body, flags=re.MULTILINE))
            for name, body in re.findall(
                r"^  (push|pull_request):\n    paths:\n((?:      - .*\n)+)",
                workflow,
                flags=re.MULTILINE,
            )
        }
        self.assertEqual(trigger_blocks["push"], trigger_blocks["pull_request"])
        self.assertEqual(workflow.count("run_phase_conformance.py"), 1)
        self.assertNotIn("conformance/v1.0/run_contract_tests.py", workflow)
        self.assertIn("fetch-depth: 0", workflow)
        self.assertEqual(workflow.count('"data/2317_cash_flow_authority.csv"'), 2)

    def test_legacy_archive_is_independent_of_runner_line_endings(self) -> None:
        command = self.router.legacy_archive_command(Path("legacy.zip"), "legacy-commit")
        self.assertEqual(command[:5], ["git", "-c", "core.autocrlf=false", "-c", "core.eol=lf"])
        self.assertEqual(command[-1], "legacy-commit")

    def test_authority_current_baseline_is_six_files(self) -> None:
        current = self.record["authorityBaselines"]["currentSix"]
        self.assertEqual(len(current), 6)
        self.assertEqual(self.runner.classify_authority_paths(current, self.record), "CURRENT_SIX")

    def test_unapproved_seventh_authority_file_fails_closed(self) -> None:
        current = list(self.record["authorityBaselines"]["currentSix"])
        current.append("data/unapproved.csv")
        with self.assertRaisesRegex(AssertionError, "Unknown authority baseline"):
            self.runner.classify_authority_paths(current, self.record)

    def test_actual_current_module_is_non_actionable_and_protected(self) -> None:
        module = ROOT / "modules" / "p1008_research_plugin"
        self.assertEqual(self.runner.protected_write_violations(module), [])
        self.assertEqual(self.runner.actionable_violations(module), [])


if __name__ == "__main__":
    unittest.main()
