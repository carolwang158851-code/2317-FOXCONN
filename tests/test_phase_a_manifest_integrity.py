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
def git_blob_bytes(relative: str, revision: str = "HEAD") -> bytes:
    return subprocess.run(
        ["git", "show", f"{revision}:{relative}"],
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
        for entry in manifest.get("authoritativeFiles", []):
            relative = entry["path"]
            with self.subTest(relative=relative):
                path = PACKAGE_ROOT / relative
                committed = git_blob_bytes(relative)
                worktree = path.read_bytes()
                self.assertEqual(
                    hashlib.sha256(worktree).hexdigest().upper(),
                    entry["sha256"],
                    "PRODUCTION_AUTHORITY_HASH_MISMATCH",
                )
                self.assertEqual(
                    entry["sha256"],
                    hashlib.sha256(committed).hexdigest().upper(),
                    "PRODUCTION_AUTHORITY_REPOSITORY_MISMATCH",
                )
                self.assertEqual(entry["rowCount"], csv_row_count_bytes(committed))

        for entry in manifest.get("nonAuthoritativeFiles", []):
            relative = entry["path"]
            with self.subTest(relative=relative):
                current = (PACKAGE_ROOT / relative).read_bytes()
                self.assertEqual(entry["sha256"], entry["currentSha256"])
                self.assertEqual(
                    hashlib.sha256(current).hexdigest().upper(),
                    entry["currentSha256"],
                    "NON_AUTHORITATIVE_RESEARCH_LINEAGE_MISMATCH",
                )
                baseline = git_blob_bytes(relative, entry["acceptedBaselineRevision"])
                self.assertEqual(
                    hashlib.sha256(baseline).hexdigest().upper(),
                    entry["acceptedBaselineSha256"],
                    "RESEARCH_HISTORICAL_BASELINE_LINEAGE_MISMATCH",
                )

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
