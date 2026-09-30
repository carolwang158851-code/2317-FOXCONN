from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import p1008_authority_git_sync as sync
import p1008_app_server as app_server


CANONICAL_SHA = "a" * 40
MANIFEST_REL = "data/CSV_AUTHORITY_MANIFEST.json"
AUTHORITY_REL = "data/authority.csv"


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest().upper()


def build_package(root: Path, *, manifest_crlf: bool = False) -> dict[str, bytes]:
    authority = b"Date,Value\n2026-09-30,1\n"
    manifest = {
        "manifestVersion": "TEST-1.0",
        "approvedAt": "2026-09-30",
        "approvedBy": "Owner",
        "authorityPolicy": {
            "hashAlgorithm": "SHA-256",
            "automaticRecovery": False,
            "csvWritePolicy": "READ_ONLY",
        },
        "validationClasses": {
            "productionAuthority": {"manifestSection": "authoritativeFiles"},
            "researchCurrentState": {"manifestSection": "nonAuthoritativeFiles"},
        },
        "authoritativeFiles": [
            {
                "path": AUTHORITY_REL,
                "sha256": sha256(authority),
                "fileSizeBytes": len(authority),
            }
        ],
        "nonAuthoritativeFiles": [],
    }
    manifest_bytes = (
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")
    if manifest_crlf:
        manifest_bytes = manifest_bytes.replace(b"\n", b"\r\n")
    (root / "data").mkdir(parents=True)
    (root / AUTHORITY_REL).write_bytes(authority)
    (root / MANIFEST_REL).write_bytes(manifest_bytes)
    return {MANIFEST_REL: manifest_bytes, AUTHORITY_REL: authority}


class FakeGitRunner:
    def __init__(
        self,
        expected_blobs: dict[str, str],
        canonical_blobs: dict[str, str],
        *,
        remotes: tuple[str, ...] = ("github", "origin"),
        remote_returncode: int = 0,
    ) -> None:
        self.expected_blobs = expected_blobs
        self.canonical_blobs = canonical_blobs
        self.remotes = remotes
        self.remote_returncode = remote_returncode
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, args, **_kwargs):
        command = tuple(args)
        self.calls.append(command)
        if command[-1] == "remote":
            return subprocess.CompletedProcess(args, 0, "\n".join(self.remotes) + "\n", "")
        if "ls-remote" in command:
            output = f"{CANONICAL_SHA}\trefs/heads/main\n" if not self.remote_returncode else ""
            return subprocess.CompletedProcess(args, self.remote_returncode, output, "unavailable")
        if "hash-object" in command:
            relative = command[-1]
            return subprocess.CompletedProcess(args, 0, self.expected_blobs[relative] + "\n", "")
        if "ls-tree" in command:
            relative = command[-1]
            oid = self.canonical_blobs.get(relative)
            output = f"100644 blob {oid}\t{relative}\n" if oid else ""
            return subprocess.CompletedProcess(args, 0, output, "")
        raise AssertionError(f"Unexpected command: {command}")


class AuthorityGitLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="p1008-authority-git-")
        self.root = Path(self.temp.name)
        self.payloads = build_package(self.root)
        self.expected = {
            MANIFEST_REL: "1" * 40,
            AUTHORITY_REL: "2" * 40,
        }

    def tearDown(self) -> None:
        self.temp.cleanup()

    def evaluate(self, runner: FakeGitRunner):
        return sync.evaluate_authority_git_sync(self.root, runner=runner)

    def test_case_a_valid_authority_and_identical_canonical_git_is_synced(self):
        runner = FakeGitRunner(self.expected, dict(self.expected))
        result = self.evaluate(runner)
        self.assertTrue(result["formalAuthorityValid"])
        self.assertEqual(result["authorityGitSyncStatus"], "SYNCED")
        self.assertTrue(result["authorityGitSynced"])
        self.assertFalse(result["authorityGitSyncPending"])

    def test_case_b_valid_authority_and_older_canonical_git_is_pending(self):
        older = {**self.expected, AUTHORITY_REL: "3" * 40}
        result = self.evaluate(FakeGitRunner(self.expected, older))
        self.assertTrue(result["formalAuthorityValid"])
        self.assertEqual(result["authorityGitSyncStatus"], "PENDING")
        self.assertTrue(result["authorityGitSyncPending"])

    def test_case_c_crlf_worktree_manifest_with_matching_canonical_blob_is_synced(self):
        lf_manifest = self.payloads[MANIFEST_REL]
        crlf_manifest = lf_manifest.replace(b"\n", b"\r\n")
        (self.root / MANIFEST_REL).write_bytes(crlf_manifest)
        self.assertNotEqual(sha256(lf_manifest), sha256(crlf_manifest))
        result = self.evaluate(FakeGitRunner(self.expected, dict(self.expected)))
        self.assertTrue(result["formalAuthorityValid"])
        self.assertEqual(result["authorityGitSyncStatus"], "SYNCED")

    def test_case_d_invalid_formal_authority_is_blocked_not_pending(self):
        (self.root / AUTHORITY_REL).write_bytes(b"tampered\n")
        runner = FakeGitRunner(self.expected, dict(self.expected))
        result = self.evaluate(runner)
        self.assertFalse(result["formalAuthorityValid"])
        self.assertEqual(result["authorityGitSyncStatus"], "BLOCKED")
        self.assertFalse(result["authorityGitSyncPending"])
        self.assertEqual(runner.calls, [])

    def test_case_e_canonical_github_unavailable_is_blocked(self):
        runner = FakeGitRunner(self.expected, dict(self.expected), remotes=("origin",))
        result = self.evaluate(runner)
        self.assertTrue(result["formalAuthorityValid"])
        self.assertEqual(result["authorityGitSyncStatus"], "BLOCKED")

    def test_case_f_origin_match_cannot_override_github_mismatch(self):
        github_older = {**self.expected, AUTHORITY_REL: "4" * 40}
        runner = FakeGitRunner(self.expected, github_older)
        result = self.evaluate(runner)
        self.assertEqual(result["authorityGitSyncStatus"], "PENDING")
        ls_remote_calls = [call for call in runner.calls if "ls-remote" in call]
        self.assertEqual(len(ls_remote_calls), 1)
        self.assertEqual(ls_remote_calls[0][-2:], ("github", "refs/heads/main"))

    def test_case_g_formal_publish_remains_valid_while_git_sync_is_pending(self):
        canonical = {MANIFEST_REL: "5" * 40, AUTHORITY_REL: "6" * 40}
        result = self.evaluate(FakeGitRunner(self.expected, canonical))
        self.assertTrue(result["formalAuthorityValid"])
        self.assertEqual(result["authorityGitSyncStatus"], "PENDING")
        self.assertFalse(result["actionable"])

    def test_case_h_evaluation_performs_no_git_or_authority_mutation(self):
        before = {path: (self.root / path).read_bytes() for path in self.payloads}
        runner = FakeGitRunner(self.expected, dict(self.expected))
        result = self.evaluate(runner)
        after = {path: (self.root / path).read_bytes() for path in self.payloads}
        self.assertEqual(before, after)
        self.assertFalse(result["gitMutationPerformed"])
        forbidden = {"add", "commit", "push", "merge", "rebase", "reset", "stash", "clean"}
        self.assertFalse(any(forbidden.intersection(call) for call in runner.calls))

    def test_app_status_hook_records_read_only_pending_result(self):
        pending = sync.not_evaluated_result()
        pending.update(
            {
                "formalAuthorityValid": True,
                "authorityGitSyncStatus": "PENDING",
                "authorityGitSyncPending": True,
                "errors": [],
            }
        )
        manager = app_server.P1008JobManager(self.root)
        with patch.object(
            app_server.authority_git_sync,
            "evaluate_authority_git_sync",
            return_value=pending,
        ):
            result = manager.refresh_authority_git_sync()
        self.assertEqual(result["authorityGitSyncStatus"], "PENDING")
        self.assertEqual(manager.state["authorityGitSync"], pending)
        persisted = json.loads(manager.state_path.read_text(encoding="utf-8"))
        self.assertEqual(persisted["authorityGitSync"]["authorityGitSyncStatus"], "PENDING")

    def test_owner_publish_job_success_is_not_gated_by_pending_sync(self):
        pending = sync.not_evaluated_result()
        pending.update(
            {
                "formalAuthorityValid": True,
                "authorityGitSyncStatus": "PENDING",
                "authorityGitSyncPending": True,
                "errors": [],
            }
        )
        manager = app_server.P1008JobManager(self.root)
        manager.state["errors"] = []
        with (
            patch.object(app_server, "formal_csv_hashes", return_value={}),
            patch.object(manager, "_run_owner_publish_inner", return_value=None),
            patch.object(manager, "refresh_authority_git_sync", return_value=pending),
            patch.object(manager, "pending_owner_review", return_value={"pending": False}),
            patch.object(manager, "review_package", return_value={"status": "READY"}),
            patch.object(manager, "_append_log"),
        ):
            manager._run_owner_publish_job("TEST", None, "OWNER_APPROVE_TEST")
        self.assertEqual(manager.state["status"], "SUCCEEDED")
        self.assertEqual(manager.state["errors"], [])


if __name__ == "__main__":
    unittest.main()
