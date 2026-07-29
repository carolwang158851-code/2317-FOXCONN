from __future__ import annotations

import csv
import hashlib
import io
import json
import subprocess
import unittest
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
MANIFEST = PACKAGE_ROOT / "data/CSV_AUTHORITY_MANIFEST.json"
PHASE_A_FILES = (
    "data/2317_daily_price.csv",
    "data/2317_daily_market_activity.csv",
    "data/macro_snapshot.csv",
    "data/fx_trend_observations.csv",
    "data/macro_event_observations.csv",
)


def git_blob_bytes(relative: str) -> bytes:
    return subprocess.run(
        ["git", "show", f"HEAD:{relative}"],
        cwd=PACKAGE_ROOT,
        check=True,
        capture_output=True,
    ).stdout


def csv_row_count_bytes(payload: bytes) -> int:
    lines = [
        line
        for line in payload.decode("utf-8-sig").splitlines()
        if line.strip() and not line.startswith("#")
    ]
    return max(0, len(list(csv.reader(io.StringIO("\n".join(lines))))) - 1)


class PhaseAManifestIntegrityTests(unittest.TestCase):
    def test_phase_a_csv_hashes_and_rows_match_manifest(self) -> None:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        entries = {
            item["path"]: item
            for item in (
                manifest.get("authoritativeFiles", [])
                + manifest.get("nonAuthoritativeFiles", [])
            )
        }
        for relative in PHASE_A_FILES:
            with self.subTest(relative=relative):
                path = PACKAGE_ROOT / relative
                entry = entries[relative]
                committed = git_blob_bytes(relative)
                worktree = path.read_bytes().replace(b"\r\n", b"\n")
                self.assertEqual(
                    worktree,
                    committed.replace(b"\r\n", b"\n"),
                    "worktree differs from the accepted Git blob beyond line endings",
                )
                self.assertEqual(
                    entry["sha256"],
                    hashlib.sha256(committed).hexdigest().upper(),
                )
                self.assertEqual(entry["rowCount"], csv_row_count_bytes(committed))

    def test_phase_a_tools_do_not_import_ai_or_canva_clients(self) -> None:
        for relative in (
            "tools/warroom_market_activity_updater.py",
            "tools/warroom_macro_remediation.py",
            "tools/owner_publish_csv_v2.py",
        ):
            source = (PACKAGE_ROOT / relative).read_text(encoding="utf-8")
            with self.subTest(relative=relative):
                self.assertNotIn("OPENAI_API_KEY", source)
                self.assertNotIn("from openai", source)
                self.assertNotIn("import openai", source)
                self.assertNotIn("Canva", source)


if __name__ == "__main__":
    unittest.main()
