from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_SRC = ROOT / "modules" / "p1008_research_plugin" / "src"
if str(MODULE_SRC) not in sys.path:
    sys.path.insert(0, str(MODULE_SRC))

from p1008_research_plugin.adapters import anysearch_runtime as runtime  # noqa: E402


def request() -> dict:
    return runtime.owner_authorized_smoke_request()


def response() -> dict:
    return {
        "jsonrpc": "2.0",
        "result": {"content": [{"type": "text", "text": '[{"title":"Hon Hai update","url":"https://example.com/hon-hai","snippet":"Public result"}]'}]},
    }


class GovernedAnySearchRuntimeTests(unittest.TestCase):
    def test_identity_endpoint_and_prohibited_capabilities_are_enforced(self) -> None:
        for change, code in (
            ({"commit_sha": "0" * 40}, "Pinned research-skill identity mismatch"),
            ({"provider_endpoint_identity": "https://other.example/mcp"}, "UNEXPECTED_ENDPOINT"),
            ({"command": "BATCH_SEARCH"}, "COMMAND_NOT_ALLOWED"),
            ({"max_attempts": 2}, "RUNTIME_POLICY_VIOLATION"),
            ({"fallback_enabled": True}, "RUNTIME_POLICY_VIOLATION"),
        ):
            with self.subTest(change=change), self.assertRaisesRegex(Exception, code):
                runtime.execute_governed_search({**request(), **change}, allow_anonymous=True, transport=lambda *_: response())

    def test_anonymous_requires_explicit_runtime_authorization(self) -> None:
        with self.assertRaisesRegex(runtime.GovernedAnySearchRuntimeError, "ANONYMOUS_MODE_NOT_AUTHORIZED"):
            runtime.execute_governed_search(request(), allow_anonymous=False, transport=lambda *_: response())

    def test_required_secret_is_process_scoped_and_missing_secret_fails_closed(self) -> None:
        secured = {**request(), "auth_mode": "OWNER_SUPPLIED_RUNTIME_SECRET"}
        with self.assertRaisesRegex(runtime.GovernedAnySearchRuntimeError, "REQUIRED_SECRET_UNAVAILABLE"):
            runtime.execute_governed_search(secured, allow_anonymous=False, transport=lambda *_: response())

    def test_response_normalizes_provenance_and_remains_non_actionable(self) -> None:
        seen: dict = {}

        def transport(endpoint: str, payload: dict, headers: dict) -> dict:
            seen.update({"endpoint": endpoint, "payload": payload, "headers": headers})
            return response()

        envelope = runtime.execute_governed_search(request(), allow_anonymous=True, transport=transport, retrieved_at_utc="2026-08-10T00:00:00Z")
        self.assertEqual(envelope["status"], "SUCCESS")
        self.assertEqual(seen["endpoint"], "https://api.anysearch.com/mcp")
        self.assertEqual(seen["payload"]["method"], "tools/call")
        self.assertEqual(seen["payload"]["params"]["name"], "search")
        self.assertNotIn("Authorization", seen["headers"])
        self.assertEqual(envelope["provider"], "ANYSEARCH")
        self.assertEqual(envelope["authority_writes"], 0)
        self.assertEqual(envelope["core_view_changes"], 0)
        self.assertEqual(envelope["formal_reports_generated"], 0)
        self.assertFalse(envelope["actionable"])
        candidate = envelope["candidates"][0]
        self.assertEqual(candidate["source_class"], "DISCOVERY")
        self.assertEqual(candidate["source_tier"], "UNVERIFIED")
        self.assertEqual(candidate["governed_provider_version"], "v3.0.1")
        self.assertEqual(candidate["governed_provider_commit"], "caed9eac2eb6e869b89faa2f3e92d8956b013b56")
        self.assertIn("raw_response_hash", candidate["provider_response_provenance"])
        self.assertEqual(candidate["validation_state"], "DISCOVERY_UNVERIFIED")
        self.assertFalse(candidate["actionable"])

    def test_provider_secret_fields_are_not_retained_in_staging_or_receipt(self) -> None:
        provider_response = response()
        provider_response["api_key"] = "never-store"
        provider_response["result"]["content"][0]["text"] = '[{"url":"https://example.com/hon-hai?api_key=never-store&kind=news","snippet":"Public result"}]'
        envelope = runtime.execute_governed_search(request(), allow_anonymous=True, transport=lambda *_: provider_response)
        self.assertNotIn("never-store", str(envelope))
        self.assertNotIn("api_key", str(envelope).lower())
        self.assertEqual(envelope["candidates"][0]["source_locator"], "https://example.com/hon-hai?kind=news")

    def test_malformed_provider_response_and_unauthorized_write_fail_closed(self) -> None:
        with self.assertRaisesRegex(runtime.GovernedAnySearchRuntimeError, "MALFORMED_RESPONSE"):
            runtime.execute_governed_search(request(), allow_anonymous=True, transport=lambda *_: {"result": {"content": []}})
        with self.assertRaisesRegex(runtime.GovernedAnySearchRuntimeError, "UNAUTHORIZED_WRITE_ATTEMPT"):
            runtime.write_staging_output({"actionable": False, "authority_writes": 0}, ROOT / "data")


if __name__ == "__main__":
    unittest.main()
