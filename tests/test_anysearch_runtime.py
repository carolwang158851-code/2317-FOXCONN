from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
MODULE_SRC = ROOT / "modules" / "p1008_research_plugin" / "src"
if str(MODULE_SRC) not in sys.path:
    sys.path.insert(0, str(MODULE_SRC))

from p1008_research_plugin.adapters import anysearch_runtime as runtime  # noqa: E402
from p1008_research_plugin.adapters import research_skill_governance_adapter as adapter  # noqa: E402
from tests.test_research_skill_governance_adapter import validated_trigger_capability  # noqa: E402


def governed_request(**overrides: object) -> tuple[adapter.ValidatedResearchSkillTrigger, dict]:
    capability = validated_trigger_capability()
    value = adapter.build_skill_request(
        validated_trigger=capability,
        report_key="P1008_MONTHLY_REVENUE_202607",
        revision=1,
        event_reference="EVENT-MONTHLY-202607",
        command="SEARCH",
        query="Hon Hai July 2026 monthly revenue",
    )
    value.update(overrides)
    return capability, value


def response(*, locator: str = "https://example.com/hon-hai") -> dict:
    result = [{"title": "Hon Hai update", "url": locator, "snippet": "Public result"}]
    return {
        "jsonrpc": "2.0",
        "result": {"content": [{"type": "text", "text": json.dumps(result)}]},
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
            capability, request = governed_request(**change)
            with self.subTest(change=change), self.assertRaisesRegex(Exception, code):
                runtime.execute_governed_search(
                    capability, request, allow_anonymous=True, transport=lambda *_: response()
                )

    def test_fabricated_missing_and_malformed_authorization_fail_before_transport(self) -> None:
        capability, request = governed_request()
        calls = 0

        def transport(*_: object) -> dict:
            nonlocal calls
            calls += 1
            return response()

        for authorization in (
            None,
            {},
            {"report_key": capability.report_key, "report_trigger_valid": True},
            object(),
        ):
            with self.subTest(authorization=authorization), self.assertRaisesRegex(
                adapter.ResearchSkillGovernanceError, "SKILL_INVOCATION_NOT_ELIGIBLE"
            ):
                runtime.execute_governed_search(  # type: ignore[arg-type]
                    authorization, request, allow_anonymous=True, transport=transport
                )
        self.assertEqual(calls, 0)

    def test_authorization_context_mismatch_fails_before_transport(self) -> None:
        capability, request = governed_request(event_reference="EVENT-FORGED")
        calls = 0

        def transport(*_: object) -> dict:
            nonlocal calls
            calls += 1
            return response()

        with self.assertRaisesRegex(adapter.ResearchSkillGovernanceError, "SKILL_AUTHORIZATION_CONTEXT_MISMATCH"):
            runtime.execute_governed_search(
                capability, request, allow_anonymous=True, transport=transport
            )
        self.assertEqual(calls, 0)

    def test_valid_authorization_is_single_use_and_replay_makes_no_second_call(self) -> None:
        capability, request = governed_request()
        calls = 0

        def transport(*_: object) -> dict:
            nonlocal calls
            calls += 1
            return response()

        first = runtime.execute_governed_search(
            capability, request, allow_anonymous=True, transport=transport
        )
        self.assertEqual(first["status"], "SUCCESS")
        with self.assertRaisesRegex(adapter.ResearchSkillGovernanceError, "SKILL_INVOCATION_NOT_ELIGIBLE"):
            runtime.execute_governed_search(
                capability, request, allow_anonymous=True, transport=transport
            )
        self.assertEqual(calls, 1)

    def test_failed_provider_attempt_consumes_authorization_and_cannot_retry(self) -> None:
        capability, request = governed_request()
        calls = 0

        def failing_transport(*_: object) -> dict:
            nonlocal calls
            calls += 1
            raise RuntimeError("offline provider failure")

        with self.assertRaisesRegex(RuntimeError, "offline provider failure"):
            runtime.execute_governed_search(
                capability, request, allow_anonymous=True, transport=failing_transport
            )
        with self.assertRaisesRegex(adapter.ResearchSkillGovernanceError, "SKILL_INVOCATION_NOT_ELIGIBLE"):
            runtime.execute_governed_search(
                capability, request, allow_anonymous=True, transport=failing_transport
            )
        self.assertEqual(calls, 1)

    def test_anonymous_requires_explicit_runtime_authorization(self) -> None:
        capability, request = governed_request()
        with self.assertRaisesRegex(runtime.GovernedAnySearchRuntimeError, "ANONYMOUS_MODE_NOT_AUTHORIZED"):
            runtime.execute_governed_search(
                capability, request, allow_anonymous=False, transport=lambda *_: response()
            )

    def test_required_secret_is_process_scoped_and_missing_secret_fails_closed(self) -> None:
        capability, secured = governed_request(auth_mode="OWNER_SUPPLIED_RUNTIME_SECRET")
        with mock.patch.dict(os.environ, {}, clear=True), self.assertRaisesRegex(
            runtime.GovernedAnySearchRuntimeError, "REQUIRED_SECRET_UNAVAILABLE"
        ):
            runtime.execute_governed_search(
                capability, secured, allow_anonymous=False, transport=lambda *_: response()
            )

    def test_response_normalizes_provenance_and_remains_non_actionable(self) -> None:
        capability, request = governed_request()
        seen: dict = {}

        def transport(endpoint: str, payload: dict, headers: dict) -> dict:
            seen.update({"endpoint": endpoint, "payload": payload, "headers": headers})
            return response()

        envelope = runtime.execute_governed_search(
            capability,
            request,
            allow_anonymous=True,
            transport=transport,
            retrieved_at_utc="2026-08-10T00:00:00Z",
        )
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

    def test_secret_url_material_and_userinfo_never_reach_normalized_or_staged_output(self) -> None:
        locator = (
            "https://user:password@example.com/hon-hai?kind=news&sig=never-store"
            "&jwt=never-store&access_token=never-store&KEY=never-store#secret"
        )
        provider_response = response(locator=locator)
        provider_response["api_key"] = "never-store"
        capability, request = governed_request()
        envelope = runtime.execute_governed_search(
            capability, request, allow_anonymous=True, transport=lambda *_: provider_response
        )
        serialized = json.dumps(envelope, sort_keys=True)
        self.assertNotIn("never-store", serialized)
        self.assertNotIn("user:password", serialized)
        self.assertNotIn("api_key", serialized.casefold())
        self.assertEqual(
            envelope["candidates"][0]["source_locator"],
            "https://example.com/hon-hai?kind=news",
        )
        with mock.patch.object(Path, "mkdir"), mock.patch.object(Path, "write_bytes") as write_bytes:
            runtime.write_staging_output(envelope, ROOT / "runtime" / "anysearch_staging")
        staged_bytes = write_bytes.call_args.args[0]
        self.assertNotIn(b"never-store", staged_bytes)
        self.assertNotIn(b"user:password", staged_bytes)
        self.assertNotIn(b"api_key", staged_bytes.lower())

    def test_environment_proxies_are_explicitly_disabled_offline(self) -> None:
        captured_handlers: tuple[object, ...] = ()

        class FakeResponse:
            def __enter__(self) -> "FakeResponse":
                return self

            def __exit__(self, *_: object) -> None:
                return None

            def geturl(self) -> str:
                return runtime._ALLOWED_ENDPOINT

            def read(self) -> bytes:
                return json.dumps(response()).encode("utf-8")

        class FakeOpener:
            def open(self, *_: object, **__: object) -> FakeResponse:
                return FakeResponse()

        def opener_factory(*handlers: object) -> FakeOpener:
            nonlocal captured_handlers
            captured_handlers = handlers
            return FakeOpener()

        proxy_env = {
            "HTTP_PROXY": "http://proxy.invalid:8080",
            "HTTPS_PROXY": "http://proxy.invalid:8080",
            "ALL_PROXY": "socks5://proxy.invalid:1080",
        }
        with mock.patch.dict(os.environ, proxy_env, clear=True), mock.patch.object(
            runtime, "build_opener", side_effect=opener_factory
        ):
            result = runtime._post_once(runtime._ALLOWED_ENDPOINT, {"jsonrpc": "2.0"}, {})
        self.assertEqual(result["jsonrpc"], "2.0")
        proxy_handlers = [handler for handler in captured_handlers if isinstance(handler, runtime.ProxyHandler)]
        self.assertEqual(len(proxy_handlers), 1)
        self.assertEqual(proxy_handlers[0].proxies, {})

    def test_redirect_to_unexpected_endpoint_fails_closed_offline(self) -> None:
        class RedirectedResponse:
            def __enter__(self) -> "RedirectedResponse":
                return self

            def __exit__(self, *_: object) -> None:
                return None

            def geturl(self) -> str:
                return "https://other.example/mcp"

            def read(self) -> bytes:
                return b"{}"

        fake_opener = mock.Mock()
        fake_opener.open.return_value = RedirectedResponse()
        with mock.patch.object(runtime, "build_opener", return_value=fake_opener), self.assertRaisesRegex(
            runtime.GovernedAnySearchRuntimeError, "UNEXPECTED_ENDPOINT"
        ):
            runtime._post_once(runtime._ALLOWED_ENDPOINT, {"jsonrpc": "2.0"}, {})

    def test_malformed_provider_response_and_unauthorized_write_fail_closed(self) -> None:
        capability, request = governed_request()
        with self.assertRaisesRegex(runtime.GovernedAnySearchRuntimeError, "MALFORMED_RESPONSE"):
            runtime.execute_governed_search(
                capability,
                request,
                allow_anonymous=True,
                transport=lambda *_: {"result": {"content": []}},
            )
        with self.assertRaisesRegex(runtime.GovernedAnySearchRuntimeError, "UNAUTHORIZED_WRITE_ATTEMPT"):
            runtime.write_staging_output({"actionable": False, "authority_writes": 0}, ROOT / "data")


if __name__ == "__main__":
    unittest.main()
