from __future__ import annotations

import csv
import hashlib
import json
import shutil
import sys
import unittest
import uuid
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
TOOLS = PACKAGE_ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import warroom_macro_remediation as remediation  # noqa: E402


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


class PhaseAMacroRemediationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.output = (
            PACKAGE_ROOT
            / "runtime"
            / "macro_remediation_tests"
            / uuid.uuid4().hex
        )
        self.addCleanup(
            lambda: shutil.rmtree(self.output) if self.output.exists() else None
        )

    def test_five_text_values_become_explicit_blanks_in_candidate_only(self) -> None:
        formal = PACKAGE_ROOT / remediation.FORMAL_REL
        before = sha256(formal)
        result = remediation.build_candidate(PACKAGE_ROOT, self.output)
        self.assertEqual(
            {item["date"] for item in result["invalid_values"]},
            remediation.EXPECTED_INVALID_DATES,
        )
        self.assertTrue(
            all(
                item["source"] == "SOURCE_NOT_PROVIDED_IN_FORMAL_ROW"
                for item in result["invalid_values"]
            )
        )
        _, header, rows = remediation.read_macro(Path(result["candidate_path"]))
        value_index = header.index("Hon_Hai_Rev_YoY")
        date_index = header.index("Date")
        by_date = {row[date_index]: row for row in rows}
        for invalid_date in remediation.EXPECTED_INVALID_DATES:
            self.assertEqual(by_date[invalid_date][value_index], "")
        self.assertEqual(sha256(formal), before)
        self.assertFalse(result["formal_csv_modified"])
        self.assertFalse(result["promotion_eligible"])

    def test_manifest_has_cutoff_for_macro_fx_and_event(self) -> None:
        manifest = json.loads(
            (PACKAGE_ROOT / "data/CSV_AUTHORITY_MANIFEST.json").read_text(
                encoding="utf-8"
            )
        )
        entries = {
            item["path"]: item
            for item in manifest.get("nonAuthoritativeFiles", [])
        }
        expected_cutoffs = {
            "data/macro_snapshot.csv": "2026-07-10",
            "data/fx_trend_observations.csv": "2026-07-27",
            "data/macro_event_observations.csv": "2026-07-27",
        }
        for path, cutoff in expected_cutoffs.items():
            with self.subTest(path=path):
                self.assertEqual(entries[path]["cutoffDate"], cutoff)


if __name__ == "__main__":
    unittest.main()
