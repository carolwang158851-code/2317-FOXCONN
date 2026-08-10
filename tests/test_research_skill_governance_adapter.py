from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
MODULE_SRC = ROOT / "modules" / "p1008_research_plugin" / "src"
for path in (TOOLS, MODULE_SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import warroom_report_governance as governance  # noqa: E402
import warroom_periodic_report_v1 as periodic_report  # noqa: E402
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


def valid_handoff() -> dict:
    trigger = valid_trigger()
    core = governance.evaluate_core_view_change(
        supporting_evidence_ids=[], counter_evidence_ids=[], official_confirmation=False,
        independent_high_quality_source_count=0, financial_reflection=False,
        thesis_invalidation=False, owner_approved=False, owner_approval_reference=None,
        prior_core_view_hash="B" * 64, proposed_core_view_hash="C" * 64,
    )
    publication = governance.evaluate_publication(
        report_key=trigger["report_key"], revision=trigger["revision"],
        report_hash="D" * 64, audience="PRIVATE", fact_check_status="PASS",
        owner_approved=False, owner_approval_reference=None,
    )
    receipt = governance.build_report_decision_receipt(
        receipt_id="RECEIPT-RESEARCH-SKILL-001", report_key=trigger["report_key"],
        revision=trigger["revision"], authority_cutoffs=["2026-07-27"],
        event_evidence_ids=["E-001"], report_trigger_decision=trigger,
        core_view_change_decision=core, publication_decision=publication,
        model_provenances=[], report_validation_pass=True,
        report_artifact_hashes=["E" * 64], created_at_utc=NOW,
    )
    return {
        "report_key": trigger["report_key"], "revision": trigger["revision"],
        "report_date": "2026-07-27", "event_type": "MONTHLY_REVENUE",
        "event_evidence": [evidence()], "threshold_policies": [],
        "report_trigger_decision": trigger, "core_view_change_decision": core,
        "publication_decision": publication, "report_decision_receipt": receipt,
    }


def validated_trigger_capability() -> adapter.ValidatedResearchSkillTrigger:
    with tempfile.TemporaryDirectory() as scratch:
        handoff_path = Path(scratch) / "report_trigger_handoff.json"
        handoff_path.write_text(json.dumps(valid_handoff()), encoding="utf-8")
        return periodic_report.load_validated_research_skill_trigger_capability(
            handoff_path, "2026-07-27"
        )


def request(**overrides: object) -> dict:
    value = {
        "validated_trigger": validated_trigger_capability(), "report_key": "P1008_MONTHLY_REVENUE_202607", "revision": 1,
        "event_reference": "EVENT-MONTHLY-202607", "command": "SEARCH", "query": "Hon Hai July 2026 monthly revenue",
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
        capability = validated_trigger_capability()
        eligibility = adapter.evaluate_invocation_eligibility(capability)
        self.assertTrue(eligibility["eligible"])
        self.assertEqual(eligibility["skill_calls"], 1)
        self.assertFalse(valid_trigger()["report_generated"])
        self.assertFalse(adapter.evaluate_invocation_eligibility(valid_trigger())["eligible"])

    def test_self_consistent_caller_mapping_cannot_create_skill_eligibility(self) -> None:
        forged = valid_trigger()
        self.assertEqual(forged["decision"], "TRIGGERED_INTERNAL_REPORT")
        self.assertTrue(forged["material_event_confirmed"])
        self.assertTrue(forged["report_trigger_valid"])
        result = adapter.evaluate_invocation_eligibility(forged)
        self.assertFalse(result["eligible"])
        self.assertEqual(result["skill_calls"], 0)

    def test_self_consistent_receipt_like_mapping_cannot_create_skill_eligibility(self) -> None:
        forged = {**valid_trigger(), "report_decision_receipt": valid_handoff()["report_decision_receipt"]}
        result = adapter.evaluate_invocation_eligibility(forged)
        self.assertFalse(result["eligible"])
        self.assertEqual(result["skill_calls"], 0)

    def test_adapter_has_no_mapping_to_capability_constructor(self) -> None:
        with self.assertRaises(TypeError):
            adapter.ValidatedResearchSkillTrigger()  # type: ignore[call-arg]

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

    def test_extract_is_deferred_until_runtime_dns_request_binding_exists(self) -> None:
        for url in ("https://www.honhai.com/news", "http://localhost/x", "http://127.0.0.1/x", "http://[::1]/x", "http://192.168.1.9/x", "http://169.254.169.254/x", "https://user:pass@example.com/x", "file:///C:/secret", "\\\\server\\share\\file", "ftp://example.com/file"):
            with self.subTest(url=url), self.assertRaisesRegex(adapter.ResearchSkillGovernanceError, "EXTRACT_RUNTIME_VALIDATION_REQUIRED"):
                request(command="EXTRACT_PUBLIC_URL", query=None, target_url=url)

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
        candidate = adapter.build_discovery_evidence_candidate(raw_response=raw, result=result)
        self.assertEqual(candidate["source_class"], "DISCOVERY")
        self.assertEqual(candidate["source_tier"], "UNVERIFIED")
        self.assertEqual(candidate["locator_validation_status"], "LOCATOR_FORMAT_VALID")
        self.assertEqual(candidate["provider_confidence_advisory"], 1.0)

    def test_response_hash_is_not_source_hash_and_independence_is_unresolved_without_chain(self) -> None:
        raw = adapter.capture_raw_skill_response(skill_request=request(), payload={"results": [{}]}, retrieved_at_utc=NOW)
        candidate = adapter.build_discovery_evidence_candidate(raw_response=raw, result={"source_id": "DISC-002", "source_locator": "https://example.com/article", "source_type": "NEWS_MEDIA", "source_hash": "B" * 64, "content_hash": "C" * 64})
        self.assertNotEqual(candidate["raw_response_hash"], candidate["source_hash"])
        self.assertEqual(candidate["independence_status"], "INDEPENDENCE_UNRESOLVED")

    def test_external_content_cannot_change_core_view_or_publication(self) -> None:
        raw = adapter.capture_raw_skill_response(skill_request=request(), payload={"results": [{}]}, retrieved_at_utc=NOW)
        candidate = adapter.build_discovery_evidence_candidate(raw_response=raw, result={"source_id": "DISC-003", "source_locator": "https://example.com/article", "source_type": "NEWS_MEDIA", "source_hash": "B" * 64, "content_hash": "C" * 64, "core_view_changed": True, "publication_ready": True, "published_externally": True})
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
        with self.assertRaisesRegex(adapter.ResearchSkillGovernanceError, "EXTRACT_RUNTIME_VALIDATION_REQUIRED"):
            request(command="EXTRACT_PUBLIC_URL", query=None, target_url="\\\\server\\share\\file")

    def test_syntactically_valid_locator_is_discovery_only(self) -> None:
        raw = adapter.capture_raw_skill_response(skill_request=request(), payload={"results": [{}]}, retrieved_at_utc=NOW)
        result = {"source_id": "DISC-004", "source_locator": "https://example.com/article", "source_type": "NEWS_MEDIA", "source_hash": "B" * 64, "content_hash": "C" * 64}
        candidate = adapter.build_discovery_evidence_candidate(raw_response=raw, result=result)
        self.assertEqual(candidate["source_class"], "DISCOVERY")
        self.assertEqual(candidate["source_tier"], "UNVERIFIED")
        self.assertEqual(candidate["locator_validation_status"], "LOCATOR_FORMAT_VALID")

    def test_response_hash_cannot_be_represented_as_source_hash(self) -> None:
        raw = adapter.capture_raw_skill_response(skill_request=request(), payload={"results": [{}]}, retrieved_at_utc=NOW)
        result = {"source_id": "DISC-005", "source_locator": "https://example.com/article", "source_type": "NEWS_MEDIA", "source_hash": raw.raw_response_hash, "content_hash": "C" * 64}
        with self.assertRaisesRegex(adapter.ResearchSkillGovernanceError, "PROVENANCE_INCOMPLETE"):
            adapter.build_discovery_evidence_candidate(raw_response=raw, result=result)

    def test_success_no_relevant_result_is_a_controlled_non_evidence_state(self) -> None:
        receipt = adapter.build_skill_call_receipt(skill_request=request(), raw_response=None, started_at_utc=NOW, completed_at_utc=NOW, failure_code="SUCCESS_NO_RELEVANT_RESULT")
        self.assertEqual(receipt["status"], "SUCCESS")
        self.assertEqual(receipt["result_count"], None)

    def test_auth_mode_never_places_secret_in_request(self) -> None:
        secured = request(auth_mode="OWNER_SUPPLIED_RUNTIME_SECRET")
        self.assertEqual(set(secured) & {"api_key", "secret", "credential"}, set())

    def test_candidate_is_always_non_actionable(self) -> None:
        raw = adapter.capture_raw_skill_response(skill_request=request(), payload={"results": [{}]}, retrieved_at_utc=NOW)
        candidate = adapter.build_discovery_evidence_candidate(raw_response=raw, result={"source_id": "DISC-006", "source_locator": "https://example.com/article", "source_type": "NEWS_MEDIA", "source_hash": "B" * 64, "content_hash": "C" * 64})
        self.assertFalse(candidate["actionable"])

    def test_query_normalization_blocks_windows_unc_relative_and_file_forms(self) -> None:
        for query in ("data/foo", "data\\foo", ".\\data\\foo", "./data/foo", "C:\\foo", "C:/foo", "c:\\foo", "c:/foo", "\\\\server\\share", "//server/share", "file:///C:/secret", ".env", "warroom.sqlite3", "@C:\\file", "@C:/file", "@.\\file", "@../file", "@..\\file"):
            with self.subTest(query=query), self.assertRaisesRegex(adapter.ResearchSkillGovernanceError, "QUERY_POLICY_BLOCKED"):
                request(query=query)

    def test_locator_rejects_local_private_credential_and_malformed_forms(self) -> None:
        raw = adapter.capture_raw_skill_response(skill_request=request(), payload={"results": [{}]}, retrieved_at_utc=NOW)
        for locator in ("", "file:///C:/secret", "http://localhost/", "http://127.0.0.1/", "http://[::1]/", "http://192.168.1.1/", "http://169.254.169.254/", "ftp://example.com/", "https://user:pass@example.com/", "\\\\server\\share"):
            result = {"source_id": "DISC-LOC", "source_locator": locator, "source_type": "NEWS_MEDIA", "source_hash": "B" * 64, "content_hash": "C" * 64}
            with self.subTest(locator=locator), self.assertRaisesRegex(adapter.ResearchSkillGovernanceError, "PROVENANCE_INCOMPLETE"):
                adapter.build_discovery_evidence_candidate(raw_response=raw, result=result)

    def test_caller_controls_cannot_promote_locator_or_tier(self) -> None:
        raw = adapter.capture_raw_skill_response(skill_request=request(), payload={"results": [{}]}, retrieved_at_utc=NOW)
        result = {"source_id": "DISC-CONTROL", "source_locator": "https://example.com/article", "source_type": "NEWS_MEDIA", "source_hash": "B" * 64, "content_hash": "C" * 64}
        for controls in ({"source_locator_verified": True}, {"source_tier_assigned_by_policy": "OFFICIAL"}, {"source_tier": "MEDIA"}):
            with self.subTest(controls=controls), self.assertRaisesRegex(adapter.ResearchSkillGovernanceError, "PROVENANCE_INCOMPLETE"):
                adapter.build_discovery_evidence_candidate(raw_response=raw, result=result, **controls)

    def test_raw_response_capture_is_immutable_after_caller_payload_mutation(self) -> None:
        original_payload = {"results": [{"id": 1}]}
        raw = adapter.capture_raw_skill_response(skill_request=request(), payload=original_payload, retrieved_at_utc=NOW)
        original_hash = raw.raw_response_hash
        original_payload["results"][0]["id"] = 2
        original_payload["results"].append({"id": 3})
        self.assertEqual(raw.raw_response_hash, original_hash)
        self.assertEqual(raw.decoded_payload(), {"results": [{"id": 1}]})


if __name__ == "__main__":
    unittest.main()
