from __future__ import annotations

import contextlib
import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import p1008_canonical_warroom as canonical
import p1008_open_warroom as launcher


class CanonicalWarroomTests(unittest.TestCase):
    def test_default_is_integrated(self):
        result = canonical.resolve_canonical()
        self.assertEqual(Path(result["resolvedPackageRoot"]), ROOT)
        self.assertEqual(result["status"], "CANONICAL_VERIFIED")
        self.assertFalse(result["override"])

    def test_tamper_fails_closed(self):
        record = canonical.load_record()
        record["canonicalRoot"] = "P1008_RESEARCH_CONTENT_INTEGRATION_V1"
        with patch.object(Path, "read_bytes", return_value=json.dumps(record).encode()):
            with self.assertRaisesRegex(canonical.CanonicalWarroomError, "HASH_MISMATCH"):
                canonical.resolve_canonical()

    def test_missing_record_even_explicit_fails_closed(self):
        with patch.object(Path, "read_bytes", side_effect=FileNotFoundError):
            with self.assertRaises(canonical.CanonicalWarroomError):
                canonical.resolve_canonical(ROOT)

    def test_missing_canonical_never_falls_back(self):
        with patch.object(Path, "is_dir", return_value=False):
            with self.assertRaisesRegex(canonical.CanonicalWarroomError, "ROOT_MISSING"):
                canonical.resolve_canonical()

    def test_wrong_history_fails_closed(self):
        with patch.object(canonical.subprocess, "run") as run:
            run.return_value.returncode = 1
            with self.assertRaisesRegex(canonical.CanonicalWarroomError, "HEAD_NOT_PRESERVED"):
                canonical.resolve_canonical()

    def test_explicit_override_is_visible(self):
        result = canonical.resolve_canonical(ROOT.parent / "P1008_RESEARCH_CONTENT_INTEGRATION_V1")
        self.assertEqual(result["status"], "EXPLICIT_NON_CANONICAL_OVERRIDE")
        self.assertTrue(result["override"])
        self.assertFalse(result["publication"])

    def test_launcher_read_only_smoke(self):
        output = io.StringIO()
        with patch.object(sys, "argv", ["launcher", "--preflight-only"]), contextlib.redirect_stdout(output):
            with patch.object(launcher, "start_server") as start:
                self.assertEqual(launcher.main(), 0)
                start.assert_not_called()
        self.assertIn("CANONICAL_VERIFIED", output.getvalue())

    def test_launcher_missing_record_stops_before_server(self):
        with patch.object(sys, "argv", ["launcher", "--preflight-only"]):
            with patch.object(Path, "read_bytes", side_effect=FileNotFoundError):
                self.assertEqual(launcher.main(), 6)

    def test_runtime_entry_has_same_preflight(self):
        source = (ROOT / "tools/p1008_app_server.py").read_text(encoding="utf-8")
        main = source[source.index("def main() -> int:"):]
        self.assertLess(main.index("resolve_canonical(args.directory)"), main.index("P1008JobManager(package_root)"))


if __name__ == "__main__":
    unittest.main()
