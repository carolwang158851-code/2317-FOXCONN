from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


MODULE_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = MODULE_ROOT.parents[1]
CASE_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(MODULE_ROOT / "src"))

from p1008_research_plugin.orchestrator import ResearchOrchestrator


class EchoGoldenTests(unittest.TestCase):
    def test_echo_output_matches_golden_case(self) -> None:
        request = json.loads((CASE_ROOT / "echo_input.json").read_text(encoding="utf-8"))
        expected = json.loads(
            (CASE_ROOT / "echo_expected.json").read_text(encoding="utf-8")
        )
        actual = ResearchOrchestrator(PACKAGE_ROOT).run(request)
        self.assertEqual(actual["request_id"], "86C76D6BDADFE87162F3B511")
        self.assertEqual(actual["output"], expected)
        self.assertEqual(
            actual["artifact"]["sha256"],
            "0177A7AF52719B9D241F64993AB2D38376E62A91AE5F68A420092A42E878F0B3",
        )


if __name__ == "__main__":
    unittest.main()
