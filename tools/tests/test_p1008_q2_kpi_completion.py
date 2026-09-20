from __future__ import annotations

import sys
import unittest
from pathlib import Path


PACKAGE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PACKAGE / "tools"))

import p1008_q2_kpi_completion as completion


class Q2KpiCompletionQuarantineTests(unittest.TestCase):
    def test_tool_is_explicitly_quarantined_and_non_actionable(self) -> None:
        state = completion.disposition()
        self.assertEqual("OBSOLETE_LEGACY_MAINTENANCE_ONLY", state["status"])
        self.assertEqual(
            "SUPERSEDED_BY_CURRENT_QUARTERLY_AUTHORITY_INTERFACE", state["reason"]
        )
        self.assertFalse(state["authorityMutation"])
        self.assertFalse(state["actionable"])

    def test_candidate_generation_fails_closed(self) -> None:
        with self.assertRaisesRegex(
            completion.ObsoleteQ2CompletionError,
            "SUPERSEDED_BY_CURRENT_QUARTERLY_AUTHORITY_INTERFACE",
        ):
            completion.build_candidate(PACKAGE)

    def test_owner_promotion_fails_closed_without_writing(self) -> None:
        with self.assertRaisesRegex(
            completion.ObsoleteQ2CompletionError,
            "SUPERSEDED_BY_CURRENT_QUARTERLY_AUTHORITY_INTERFACE",
        ):
            completion.promote(PACKAGE)


if __name__ == "__main__":
    unittest.main()
