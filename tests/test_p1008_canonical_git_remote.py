from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import p1008_canonical_warroom as canonical


GITHUB_SHA = "1" * 40
ORIGIN_SHA = "2" * 40


class FakeGitRunner:
    def __init__(self, *, remotes=("github", "origin"), github_sha=GITHUB_SHA,
                 origin_sha=ORIGIN_SHA, query_returncode=0):
        self.remotes = remotes
        self.github_sha = github_sha
        self.origin_sha = origin_sha
        self.query_returncode = query_returncode
        self.calls = []

    def __call__(self, args, **_kwargs):
        self.calls.append(tuple(args))
        if args[-1] == "remote":
            return subprocess.CompletedProcess(args, 0, "\n".join(self.remotes) + "\n", "")
        if "ls-remote" in args and args[-2:] == ["github", "refs/heads/main"]:
            stdout = f"{self.github_sha}\trefs/heads/main\n" if not self.query_returncode else ""
            return subprocess.CompletedProcess(args, self.query_returncode, stdout, "query failed")
        if "ls-remote" in args and args[-2:] == ["origin", "refs/heads/main"]:
            return subprocess.CompletedProcess(
                args, 0, f"{self.origin_sha}\trefs/heads/main\n", ""
            )
        raise AssertionError(f"Unexpected Git call: {args}")


class CanonicalGitRemoteTests(unittest.TestCase):
    def contract(self):
        return {
            "canonicalGitRemote": {
                "canonical_remote": "github",
                "canonical_main_ref": "refs/heads/main",
                "origin_role": "NON_AUTHORITATIVE_LOCAL_SIBLING",
                "non_authoritative_remotes": ["origin"],
                "direct_query_required": True,
                "fallback_allowed": False,
                "fail_closed": True,
            }
        }

    def verify(self, runner, **kwargs):
        with patch.object(canonical, "load_record", return_value=self.contract()):
            return canonical.verify_canonical_git_remote(
                repository=ROOT, runner=runner, **kwargs
            )

    def assert_only_github_was_queried(self, runner):
        query_calls = [call for call in runner.calls if "ls-remote" in call]
        self.assertEqual(len(query_calls), 1)
        self.assertEqual(query_calls[0][-2:], ("github", "refs/heads/main"))

    def test_case_1_identical_histories_github_remains_canonical(self):
        runner = FakeGitRunner(github_sha=GITHUB_SHA, origin_sha=GITHUB_SHA)
        result = self.verify(runner, expected_sha=GITHUB_SHA)
        self.assertEqual(result["CANONICAL_REMOTE"], "github")
        self.assertEqual(result["CANONICAL_DIRECT_SHA"], GITHUB_SHA)
        self.assertEqual(result["REMOTE_IDENTITY_GATE"], "PASS")
        self.assert_only_github_was_queried(runner)

    def test_case_2_github_ahead_of_origin_github_remains_canonical(self):
        runner = FakeGitRunner(github_sha="3" * 40, origin_sha="2" * 40)
        result = self.verify(runner, expected_sha="3" * 40)
        self.assertEqual(result["CANONICAL_DIRECT_SHA"], "3" * 40)
        self.assert_only_github_was_queried(runner)

    def test_case_3_origin_ahead_cannot_become_canonical(self):
        runner = FakeGitRunner(github_sha="2" * 40, origin_sha="3" * 40)
        result = self.verify(runner, expected_sha="2" * 40)
        self.assertEqual(result["CANONICAL_REMOTE"], "github")
        self.assertIn("origin", result["NON_AUTHORITATIVE_REMOTES"])
        self.assert_only_github_was_queried(runner)

    def test_case_4_divergence_does_not_create_origin_rewrite_diagnosis(self):
        runner = FakeGitRunner(github_sha="a" * 40, origin_sha="b" * 40)
        result = self.verify(runner, expected_sha="a" * 40)
        self.assertNotIn("rewrite", result)
        self.assertFalse(result["fallbackUsed"])
        self.assert_only_github_was_queried(runner)

    def test_case_5_missing_github_fails_closed(self):
        runner = FakeGitRunner(remotes=("origin",))
        with self.assertRaisesRegex(canonical.CanonicalGitRemoteError, "REMOTE_MISSING"):
            self.verify(runner)
        self.assertFalse(any("ls-remote" in call for call in runner.calls))

    def test_case_6_github_query_failure_fails_closed(self):
        runner = FakeGitRunner(query_returncode=2)
        with self.assertRaisesRegex(canonical.CanonicalGitRemoteError, "DIRECT_QUERY_FAILED"):
            self.verify(runner)

    def test_case_7_generic_origin_main_cannot_satisfy_canonical_gate(self):
        runner = FakeGitRunner()
        with self.assertRaisesRegex(canonical.CanonicalGitRemoteError, "NOT_CANONICAL"):
            self.verify(runner, requested_remote="origin/main")
        self.assertEqual(runner.calls, [])

    def test_direct_sha_mismatch_fails_closed(self):
        runner = FakeGitRunner(github_sha=GITHUB_SHA)
        with self.assertRaisesRegex(canonical.CanonicalGitRemoteError, "SHA_MISMATCH"):
            self.verify(runner, expected_sha="f" * 40)


if __name__ == "__main__":
    unittest.main()
