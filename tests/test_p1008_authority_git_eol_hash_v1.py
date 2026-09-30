from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import p1008_authority_git_sync as sync


INCIDENT_CRLF_SHA256 = "6E4DDF7FA9E922F60088F4C1ADA0C2680526FF7158E5E021A16937997B9CB218"
INCIDENT_LF_SHA256 = "449EC025AC93CDC034AB4512183BF85BC1F80F38525C57B1782DBB85945ADC9F"
MANIFEST_REL = "data/CSV_AUTHORITY_MANIFEST.json"


def run_git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode:
        raise AssertionError(completed.stderr or completed.stdout)
    return completed.stdout.strip()


def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest().upper()


class AuthorityGitEolHashTests(unittest.TestCase):
    def build_policy_repo(self, autocrlf: str) -> Path:
        root = Path(tempfile.mkdtemp(prefix=f"p1008-eol-{autocrlf}-"))
        run_git(root, "init")
        run_git(root, "config", "user.name", "P1008 Test")
        run_git(root, "config", "user.email", "p1008-test@example.invalid")
        run_git(root, "config", "core.autocrlf", autocrlf)
        (root / "data").mkdir()
        (root / ".gitattributes").write_bytes(
            b"data/CSV_AUTHORITY_MANIFEST.json text eol=lf\n"
            b"data/authority.csv text eol=lf\n"
        )
        authority = b"Date,Value\n2026-09-30,1\n"
        manifest = {
            "approvedBy": "Owner",
            "authorityPolicy": {"hashAlgorithm": "SHA-256", "automaticRecovery": False},
            "validationClasses": {
                "productionAuthority": {"manifestSection": "authoritativeFiles"},
                "researchCurrentState": {"manifestSection": "nonAuthoritativeFiles"},
            },
            "authoritativeFiles": [
                {
                    "path": "data/authority.csv",
                    "sha256": digest(authority),
                    "fileSizeBytes": len(authority),
                }
            ],
            "nonAuthoritativeFiles": [],
        }
        (root / "data/authority.csv").write_bytes(authority)
        (root / MANIFEST_REL).write_bytes(
            (json.dumps(manifest, indent=2) + "\n").encode("utf-8")
        )
        run_git(root, "add", ".gitattributes", MANIFEST_REL, "data/authority.csv")
        run_git(root, "commit", "-m", "fixture")
        for relative in (MANIFEST_REL, "data/authority.csv"):
            path = root / relative
            path.unlink()
            run_git(root, "checkout", "--", relative)
        self.addCleanup(lambda: __import__("shutil").rmtree(root, ignore_errors=True))
        return root

    def assert_policy_is_deterministic(self, autocrlf: str) -> None:
        root = self.build_policy_repo(autocrlf)
        validation = sync.validate_formal_authority(root)
        self.assertTrue(validation["valid"], validation["errors"])
        for relative in (MANIFEST_REL, "data/authority.csv"):
            payload = (root / relative).read_bytes()
            self.assertNotIn(b"\r\n", payload)
            expected = run_git(root, "rev-parse", f"HEAD:{relative}")
            actual = run_git(root, "hash-object", "--path", relative, relative)
            self.assertEqual(expected, actual)

    def test_core_autocrlf_true_preserves_formal_and_git_identity(self):
        self.assert_policy_is_deterministic("true")

    def test_core_autocrlf_false_preserves_formal_and_git_identity(self):
        self.assert_policy_is_deterministic("false")

    def test_manifest_crlf_lf_incident_has_distinct_raw_but_equal_git_identity(self):
        lf = (ROOT / MANIFEST_REL).read_bytes()
        self.assertNotIn(b"\r\n", lf)
        crlf = lf.replace(b"\n", b"\r\n")
        self.assertEqual(digest(lf), INCIDENT_LF_SHA256)
        self.assertEqual(digest(crlf), INCIDENT_CRLF_SHA256)
        self.assertEqual(crlf.decode("utf-8").replace("\r\n", "\n"), lf.decode("utf-8"))

        with tempfile.TemporaryDirectory(prefix="p1008-eol-incident-") as temp:
            root = Path(temp)
            run_git(root, "init")
            run_git(root, "config", "core.autocrlf", "false")
            (root / "data").mkdir()
            (root / ".gitattributes").write_bytes(
                b"data/CSV_AUTHORITY_MANIFEST.json text eol=lf\n"
            )
            path = root / MANIFEST_REL
            path.write_bytes(crlf)
            crlf_oid = run_git(root, "hash-object", "--path", MANIFEST_REL, MANIFEST_REL)
            path.write_bytes(lf)
            lf_oid = run_git(root, "hash-object", "--path", MANIFEST_REL, MANIFEST_REL)
            self.assertEqual(crlf_oid, lf_oid)


if __name__ == "__main__":
    unittest.main()
