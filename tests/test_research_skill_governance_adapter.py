from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
MODULE_SRC = ROOT / "modules" / "p1008_research_plugin" / "src"
for path in (TOOLS, MODULE_SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import warroom_report_governance as governance  # noqa: E402
from p1008_research_plugin.adapters import research_skill_governance_adapter as adapter  # noqa: E402


HASH = "A" * 64
NOW = "2026-08-09T00:00:00Z"


def evidence() -> dict:
    return {
        "event_id": "EV-001", "event_type": "MONTHLY_REVENUE", "event_status": "MATERIAL_EVENT_CONFIRMED",
        "occurred_at_utc": NOW, "published_at_utc": NOW, "received_at_utc": NOW, "data_cutoff": "2026-07-27",
        "source_id": "OFFICIAL-001", "source_type": "AUTHORITY_DATASET", "source_class": "AUTHORITY",
        "source_locator": "authority:monthly-revenue#2026-07", "source_tier": "OFFICIAL", "source_hash": HASH,
        "originating_chain_id": "OFFICIAL-CHAIN", "evidence_ids": ["E-001"], "claim_summary": "Validated fact.",
        "affected_kpis": ["revenue"], "materiality": "MATERIAL", "novelty": "NEW", "evidence_status": "CONFIRMED",
        "validation_status": "VERIFIED", "confidence": 0.95, "quality_metadata": {"review": "test"},
        "provenance": {"collector": "test"}, "canonical_event_id": "MONTHLY_REVENUE_202607",
        "verification_status": "VERIFIED", "counter_evidence_ids": [], "missing_evidence": [], "source_conflicts": [], "actionable": False,
    }


def valid_trigger() -> dict:
    return governance.evaluate_report_trigger(
        report_key="P1008_MONTHLY_REVENUE_202607", revision=1,
        event_evidence=[evidence()], evaluated_at_utc=NOW,
    )


def request(**overrides: object) -> dict:
    value = {
        "trigger_decision": valid_trigger(), "report_key": "P1008_MONTHLY_REVENUE_202607", "revision": 1,
        "event_reference": "EVENT-MONTHLY-202607", "command": "SEARCH", "query": "鴻海 2026年7月 月營收",
    }
    value.update(overrides)
    return adapter.build_skill_request(**value)


class ResearchSkillGovernanceAdapterTests(unittest.TestCase):
    def test_no_material_change_and_invalid_trigger_make_zero_calls(self) -> None:
        no_change = governance.evaluate_report_trigger(report_key="P1008_DAILY_20260809", revision=1, event_evidence=[], evaluated_at_utc=NOW)
        self.assertEqual(adapter.evaluate_invocation_eligibility(no_change)["skill_calls"], 0)
        denied = {**valid_trigger(), "report_trigger_valid": False}
        self.assertEqual(adapter.evaluate_invocation_eligibility(denied)["skill_calls"], 0)

    def test_valid_trigger_is_eligible_but_cannot_be_created_by_skill(self) -> None:
        eligibility = adapter.evaluate_invocation_eligibility(valid_trigger())
        self.assertTrue(eligibility["eligible"])
        self.assertEqual(eligibility["skill_calls"], 1)
        self.assertFalse(valid_trigger()["report_generated"])

    def test_command_allowlist_and_forbidden_commands_fail_closed(self) -> None:
        self.assertEqual(request()["provider_command"], "search")
        self.assertEqual(request(command="GET_SUB_DOMAINS", query="Hon Hai")["provider_command"], "get_sub_domains")
        for command in ("batch_search", "batch_search @file", "generate.py", "WRITE"):
            with self.subTest(command=command), self.assertRaisesRegex(adapter.ResearchSkillGovernanceError, "SKILL_COMMAND_NOT_ALLOWED"):
                request(command=command)

    def test_query_policy_blocks_files_secrets_and_file_input(self) -> None:
        for query in ("data/2317_daily_price.csv", "RULE HOLD MIDR", "C:\\private\\report.txt", "@private.txt", "ANYSEARCH_API_KEY=secret", ".env dump"):
            with self.subTest(query=query), self.assertRaisesRegex(adapter.ResearchSkillGovernanceError, "QUERY_POLICY_BLOCKED"):
                request(query=query)

    def test_extract_requires_proven_public_url_and_rejects_private_or_local(self) -> None:
        extracted = request(command="EXTRACT_PUBLIC_URL", query=None, target_url="https://www.honhai.com/news", resolved_ip_addresses=["93.184.216.34"])
        self.assertEqual(extracted["provider_command"], "extract")
        for url, ips in (("file:///C:/secret", []), ("http://localhost/x", ["127.0.0.1"]), ("http://192.168.1.9/x", ["192.168.1.9"]), ("https://user:pass@example.com/x", ["93.184.216.34"]), ("https://example.com/x", [])):
            with self.subTest(url=url), self.assertRaisesRegex(adapter.ResearchSkillGovernanceError, "URL_POLICY_BLOCKED"):
                request(command="EXTRACT_PUBLIC_URL", query=None, target_url=url, resolved_ip_addresses=ips)

    def test_retry_fallback_and_auth_policy_are_fixed(self) -> None:
        self.assertEqual(request()["max_attempts"], 1)
        self.assertFalse(request()["fallback_enabled"])
        self.assertEqual(request(auth_mode="OWNER_SUPPLIED_RUNTIME_SECRET")["auth_mode"], "OWNER_SUPPLIED_RUNTIME_SECRET")
        for kwargs in ({"max_attempts": 2}, {"fallback_enabled": True}, {"auth_mode": "AUTO_REGISTER"}):
            with self.subTest(kwargs=kwargs), self.assertRaisesRegex(adapter.ResearchSkillGovernanceError, "SKILL_COMMAND_NOT_ALLOWED"):
                request(**kwargs)

    def test_raw_response_is_distinct_from_discovery_evidence(self) -> None:
        raw = adapter.capture_raw_skill_response(skill_request=request(), payload={"results": []}, retrieved_at_utc=NOW)
        self.assertIsInstance(raw, adapter.RawSkillResponse)
        self.assertNotIsInstance(raw, dict)
        self.assertRegex(raw.raw_response_hash, r"^[A-F0-9]{64}$")

    def test_missing_provenance_cannot_become_evidence(self) -> None:
        raw = adapter.capture_raw_skill_response(skill_request=request(), payload={"results": [{}]}, retrieved_at_utc=NOW)
        with self.assertRaisesRegex(adapter.ResearchSkillGovernanceError, "PROVENANCE_INCOMPLETE"):
            adapter.build_discovery_evidence_candidate(raw_response=raw, result={})

    def test_discovery_cannot_promote_class_or_provider_confidence_to_tier(self) -> None:
        raw = adapter.capture_raw_skill_response(skill_request=request(), payload={"results": [{}]}, retrieved_at_utc=NOW)
        result = {"source_id": "DISC-001", "source_locator": "https://example.com/article", "source_type": "NEWS_MEDIA", "source_hash": "B" * 64, "content_hash": "C" * 64, "source_class": "AUTHORITY", "source_tier": "OFFICIAL", "provider_confidence": 1.0}
        candidate = adapter.build_discovery_evidence_candidate(raw_response=raw, result=result, source_locator_verified=True)
        self.assertEqual(candidate["source_class"], "DISCOVERY")
        self.assertEqual(candidate["source_tier"], "UNVERIFIED")
        self.assertEqual(candidate["provider_confidence_advisory"], 1.0)

    def test_response_hash_is_not_source_hash_and_independence_is_unresolved_without_chain(self) -> None:
        raw = adapter.capture_raw_skill_response(skill_request=request(), payload={"results": [{}]}, retrieved_at_utc=NOW)
        candidate = adapter.build_discovery_evidence_candidate(raw_response=raw, result={"source_id": "DISC-002", "source_locator": "https://example.com/article", "source_type": "NEWS_MEDIA", "source_hash": "B" * 64, "content_hash": "C" * 64}, source_locator_verified=True)
        self.assertNotEqual(candidate["raw_response_hash"], candidate["source_hash"])
        self.assertEqual(candidate["independence_status"], "INDEPENDENCE_UNRESOLVED")

    def test_external_content_cannot_change_core_view_or_publication(self) -> None:
        raw = adapter.capture_raw_skill_response(skill_request=request(), payload={"results": [{}]}, retrieved_at_utc=NOW)
        candidate = adapter.build_discovery_evidence_candidate(raw_response=raw, result={"source_id": "DISC-003", "source_locator": "https://example.com/article", "source_type": "NEWS_MEDIA", "source_hash": "B" * 64, "content_hash": "C" * 64, "core_view_changed": True, "publication_ready": True, "published_externally": True}, source_locator_verified=True)
        self.assertFalse(candidate["core_view_changed"])
        self.assertFalse(candidate["publication_ready"])
        self.assertFalse(candidate["published_externally"])
        self.assertFalse(candidate["actionable"])

    def test_receipt_is_identity_pinned_and_excludes_secret_values(self) -> None:
        secured = request(auth_mode="OWNER_SUPPLIED_RUNTIME_SECRET")
        raw = adapter.capture_raw_skill_response(skill_request=secured, payload={"results": [{"id": 1}], "api_key": "never-store"}, retrieved_at_utc=NOW)
        receipt = adapter.build_skill_call_receipt(skill_request=secured, raw_response=raw, started_at_utc=NOW, completed_at_utc=NOW, failure_code="SUCCESS")
        self.assertEqual(receipt["commit_sha"], adapter.PINNED_SKILL_IDENTITY["commit_sha"])
        self.assertEqual(receipt["artifact_sha256"], adapter.PINNED_SKILL_IDENTITY["artifact_sha256"])
        self.assertNotIn("api_key", receipt)
        self.assertNotIn("never-store", str(receipt))
        self.assertEqual(receipt["attempt_count"], 1)
        self.assertFalse(receipt["actionable"])

    def test_identity_rejects_frontmatter_version_override_and_failure_codes_are_controlled(self) -> None:
        with self.assertRaises(adapter.ResearchSkillGovernanceError):
            adapter.validate_skill_identity({**adapter.PINNED_SKILL_IDENTITY, "tag": "2.0.0"})
        with self.assertRaises(adapter.ResearchSkillGovernanceError):
            adapter.build_skill_call_receipt(skill_request=request(), raw_response=None, started_at_utc=NOW, completed_at_utc=NOW, failure_code="RETRYING")
        self.assertEqual(adapter.THESIS_EVOLUTION_CONTRACT_STATUS, "THESIS_EVOLUTION_CONTRACT_DEFERRED")

    def test_authority_conflict_blocks_skill_calls(self) -> None:
        self.assertEqual(adapter.evaluate_invocation_eligibility({**valid_trigger(), "authority_conflict": True})["skill_calls"], 0)

    def test_unsupported_event_blocks_skill_calls(self) -> None:
        denied = governance.evaluate_report_trigger(report_key="P1008_DAILY_20260809", revision=1, event_evidence=[{**evidence(), "event_type": "WEEKLY_SUMMARY"}], evaluated_at_utc=NOW)
        self.assertEqual(adapter.evaluate_invocation_eligibility(denied)["skill_calls"], 0)

    def test_missing_threshold_policy_blocks_skill_calls(self) -> None:
        denied = governance.evaluate_report_trigger(report_key="P1008_ANOMALY_20260809", revision=1, event_evidence=[{**evidence(), "event_type": "APPROVED_PRICE_VOLUME_POSITIONING_ANOMALY"}], evaluated_at_utc=NOW)
        self.assertEqual(adapter.evaluate_invocation_eligibility(denied)["skill_calls"], 0)

    def test_tampered_trigger_identity_blocks_skill_calls(self) -> None:
        self.assertEqual(adapter.evaluate_invocation_eligibility({**valid_trigger(), "trigger_reason": "tampered"})["skill_calls"], 0)

    def test_batch_file_syntax_is_rejected_even_as_search_query(self) -> None:
        with self.assertRaisesRegex(adapter.ResearchSkillGovernanceError, "QUERY_POLICY_BLOCKED"):
            request(query="batch_search @authority.csv")

    def test_explicit_generate_mode_is_rejected(self) -> None:
        with self.assertRaisesRegex(adapter.ResearchSkillGovernanceError, "SKILL_COMMAND_NOT_ALLOWED"):
            request(command="generate.py")

    def test_local_unc_path_is_not_an_extract_target(self) -> None:
        with self.assertRaisesRegex(adapter.ResearchSkillGovernanceError, "URL_POLICY_BLOCKED"):
            request(command="EXTRACT_PUBLIC_URL", query=None, target_url="\\\\server\\share\\file", resolved_ip_addresses=[])

    def test_unverified_locator_cannot_become_discovery_evidence(self) -> None:
        raw = adapter.capture_raw_skill_response(skill_request=request(), payload={"results": [{}]}, retrieved_at_utc=NOW)
        result = {"source_id": "DISC-004", "source_locator": "https://example.com/article", "source_type": "NEWS_MEDIA", "source_hash": "B" * 64, "content_hash": "C" * 64}
        with self.assertRaisesRegex(adapter.ResearchSkillGovernanceError, "PROVENANCE_INCOMPLETE"):
            adapter.build_discovery_evidence_candidate(raw_response=raw, result=result)

    def test_response_hash_cannot_be_represented_as_source_hash(self) -> None:
        raw = adapter.capture_raw_skill_response(skill_request=request(), payload={"results": [{}]}, retrieved_at_utc=NOW)
        result = {"source_id": "DISC-005", "source_locator": "https://example.com/article", "source_type": "NEWS_MEDIA", "source_hash": raw.raw_response_hash, "content_hash": "C" * 64}
        with self.assertRaisesRegex(adapter.ResearchSkillGovernanceError, "PROVENANCE_INCOMPLETE"):
            adapter.build_discovery_evidence_candidate(raw_response=raw, result=result, source_locator_verified=True)

    def test_success_no_relevant_result_is_a_controlled_non_evidence_state(self) -> None:
        receipt = adapter.build_skill_call_receipt(skill_request=request(), raw_response=None, started_at_utc=NOW, completed_at_utc=NOW, failure_code="SUCCESS_NO_RELEVANT_RESULT")
        self.assertEqual(receipt["status"], "SUCCESS")
        self.assertEqual(receipt["result_count"], None)

    def test_auth_mode_never_places_secret_in_request(self) -> None:
        secured = request(auth_mode="OWNER_SUPPLIED_RUNTIME_SECRET")
        self.assertEqual(set(secured) & {"api_key", "secret", "credential"}, set())

    def test_candidate_is_always_non_actionable(self) -> None:
        raw = adapter.capture_raw_skill_response(skill_request=request(), payload={"results": [{}]}, retrieved_at_utc=NOW)
        candidate = adapter.build_discovery_evidence_candidate(raw_response=raw, result={"source_id": "DISC-006", "source_locator": "https://example.com/article", "source_type": "NEWS_MEDIA", "source_hash": "B" * 64, "content_hash": "C" * 64}, source_locator_verified=True)
        self.assertFalse(candidate["actionable"])


if __name__ == "__main__":
    unittest.main()
