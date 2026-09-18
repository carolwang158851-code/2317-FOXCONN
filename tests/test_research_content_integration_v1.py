from __future__ import annotations

import copy
import json
import pickle
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
MODULE_SRC = ROOT / "modules" / "p1008_research_plugin" / "src"
if str(MODULE_SRC) not in sys.path:
    sys.path.insert(0, str(MODULE_SRC))

from p1008_research_plugin.adapters import research_skill_governance_adapter as adapter  # noqa: E402
from p1008_research_plugin.orchestrator.research_content_integration import (  # noqa: E402
    OfflineFixtureTransport,
    ResearchContentIntegrationError,
    ResearchContentOrchestrator,
)
from p1008_research_plugin.phaseb1_common import sha256_file  # noqa: E402


NOW = "2026-08-11T00:00:00Z"
HASH = sha256_file(ROOT / "data" / "2317_master_v9.csv")


def provider_response(*urls: str) -> dict:
    results = [
        {"url": url, "title": f"Result {index}", "snippet": "Public event summary"}
        for index, url in enumerate(urls, start=1)
    ]
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {"content": [{"type": "text", "text": json.dumps(results)}]},
    }


def evidence(*, source_class: str = "AUTHORITY", **overrides: object) -> dict:
    value = {
        "event_id": "EVENT-001",
        "event_type": "MONTHLY_REVENUE",
        "event_status": "MATERIAL_EVENT_CONFIRMED",
        "occurred_at_utc": NOW,
        "published_at_utc": NOW,
        "received_at_utc": NOW,
        "data_cutoff": "2026-07-29",
        "source_id": "AUTHORITY-001",
        "source_type": "AUTHORITY_DATASET",
        "source_class": source_class,
        "source_locator": "data/2317_master_v9.csv#2026-07-29",
        "source_tier": "OFFICIAL",
        "source_hash": HASH,
        "originating_chain_id": "AUTHORITY-CHAIN",
        "evidence_ids": ["EVIDENCE-001"],
        "claim_summary": "Monthly revenue fact.",
        "affected_kpis": ["revenue"],
        "materiality": "MATERIAL",
        "novelty": "NEW",
        "evidence_status": "CONFIRMED",
        "validation_status": "VALIDATED",
        "confidence": 0.95,
        "quality_metadata": {"review": "deterministic"},
        "provenance": {"pipeline": "P1008_RESEARCH_CONTENT_INTEGRATION_V1"},
        "canonical_event_id": "MONTHLY_REVENUE_202607",
        "verification_status": "VALIDATED",
        "counter_evidence_ids": [],
        "missing_evidence": [],
        "source_conflicts": [],
        "actionable": False,
    }
    value.update(overrides)
    return value


def news_snapshot(*urls: str) -> dict:
    return {
        "task": "P1008_NEWS_SCAN",
        "runtimeOnly": True,
        "productionCsvModified": False,
        "actionable": False,
        "events": [
            {
                "accepted": True,
                "candidateRow": {"SourceUrl": url, "SourceTier": "MEDIA"},
            }
            for url in urls
        ],
    }


def discovery_qualification(**overrides: object) -> dict:
    value = evidence()
    for field in (
        "source_id",
        "source_type",
        "source_class",
        "source_locator",
        "source_tier",
        "source_hash",
        "event_status",
        "evidence_status",
        "validation_status",
        "verification_status",
        "actionable",
    ):
        value.pop(field)
    value["provider_result_index"] = 0
    value.update(overrides)
    return value


class ResearchContentIntegrationV1Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.orchestrator = ResearchContentOrchestrator(ROOT)
        self.manifest_path = ROOT / "data" / "CSV_AUTHORITY_MANIFEST.json"
        self.before_manifest = sha256_file(self.manifest_path)

    def capability(self, suffix: str) -> adapter.ValidatedDiscoveryScan:
        return self.orchestrator.authorize_discovery_scan(
            run_id=f"P1008-RESEARCH-CONTENT-{suffix}",
            scan_reference=f"NEWS_SCAN_{suffix}",
            event_reference=f"EVENT_{suffix}",
        )

    @staticmethod
    def mint_with_authorization(
        authorization: object, suffix: str = "NEGATIVE"
    ) -> adapter.ValidatedDiscoveryScan:
        return adapter._mint_validated_discovery_scan(
            validated_authorization=authorization,  # type: ignore[arg-type]
            scan_id=f"DISCOVERY-SCAN-{suffix}",
            run_id=f"P1008-AUTH-{suffix}",
            scan_reference=f"SCAN_{suffix}",
            event_reference=f"EVENT_{suffix}",
            authority_manifest_sha256="A" * 64,
            consume_callback=lambda: None,
        )

    def run_case(
        self,
        suffix: str,
        *,
        response: dict,
        qualified: object,
        snapshot: dict | None = None,
        discovery: list[dict] | None = None,
    ) -> dict:
        return self.orchestrator.run(
            validated_scan=self.capability(suffix),
            query="Hon Hai public company event",
            report_key="P1008_MONTHLY_REVENUE_202607",
            revision=1,
            evaluated_at_utc=NOW,
            news_scan_snapshot=snapshot or news_snapshot(),
            qualified_event_evidence=qualified,  # type: ignore[arg-type]
            transport=OfflineFixtureTransport(response),
            discovery_qualifications=discovery or [],
        )

    def assert_zero_side_effects(self, result: dict) -> None:
        self.assertEqual(result["authority_writes"], 0)
        self.assertEqual(result["core_view_changes"], 0)
        self.assertEqual(result["evidence_ledger_writes"], 0)
        self.assertEqual(result["formal_reports_generated"], 0)
        self.assertEqual(result["publication_count"], 0)
        self.assertEqual(result["external_live_calls"], 0)
        self.assertFalse(result["report_generated"])
        self.assertFalse(result["actionable"])
        self.assertEqual(sha256_file(self.manifest_path), self.before_manifest)

    def test_case_a_no_relevant_events_observes_without_report(self) -> None:
        result = self.run_case("CASE-A", response=provider_response(), qualified=[])
        self.assertTrue(result["discovery"]["completed_before_trigger"])
        self.assertEqual(result["research_state"], "NO_MATERIAL_CHANGE")
        self.assertEqual(result["display_state"], "OBSERVE")
        self.assertFalse(result["handoff_eligible"])
        self.assertIsNone(result["handoff_receipt"])
        self.assert_zero_side_effects(result)

    def test_case_b_repeated_discovery_event_is_deduplicated_and_not_triggered(self) -> None:
        item = discovery_qualification(
            originating_chain_id="ANYSEARCH-UNVERIFIED",
            evidence_ids=["DISCOVERY-EVIDENCE-001"],
        )
        result = self.run_case(
            "CASE-B",
            response=provider_response("https://example.com/event"),
            qualified=[],
            discovery=[item, dict(item)],
        )
        self.assertEqual(result["evidence"]["duplicate_count"], 1)
        self.assertEqual(result["evidence"]["qualified_count"], 1)
        self.assertEqual(result["display_state"], "WATCH")
        self.assertFalse(result["report_trigger_decision"]["report_trigger_valid"])
        self.assertEqual(
            result["validated_evidence_lineage_ledger"]["records"][0]["source_channel"],
            "GOVERNED_ANYSEARCH",
        )
        self.assert_zero_side_effects(result)

    def test_case_c_authority_conflict_requires_review_and_never_overwrites(self) -> None:
        locator = "https://news.example.com/conflict"
        secondary = evidence(
            source_class="SECONDARY",
            source_id="MEDIA-001",
            source_type="NEWS_MEDIA",
            source_locator=locator,
            source_tier="MEDIA",
            source_hash="B" * 64,
            originating_chain_id="EDITORIAL-001",
            evidence_ids=["MEDIA-EVIDENCE-001"],
            claim_summary="Conflicting monthly revenue claim.",
        )
        result = self.run_case(
            "CASE-C",
            response=provider_response(),
            qualified=[evidence(), secondary],
            snapshot=news_snapshot(locator),
        )
        self.assertEqual(result["display_state"], "REVIEW_REQUIRED")
        self.assertEqual(result["evidence"]["conflicts"], ["AUTHORITY_NEWS_CONFLICT"])
        self.assertFalse(result["handoff_eligible"])
        channels = {
            item["source_channel"]
            for item in result["validated_evidence_lineage_ledger"]["records"]
        }
        self.assertIn("NEWS", channels)
        self.assert_zero_side_effects(result)

    def test_case_d_trigger_emits_handoff_but_does_not_generate_report(self) -> None:
        result = self.run_case("CASE-D", response=provider_response(), qualified=[evidence()])
        self.assertEqual(result["research_state"], "TRIGGERED_INTERNAL_REPORT")
        self.assertEqual(result["display_state"], "REPORT")
        self.assertTrue(result["handoff_eligible"])
        self.assertTrue(result["handoff_receipt"]["handoff_eligible"])
        self.assertFalse(result["handoff_receipt"]["report_generated"])
        self.assert_zero_side_effects(result)

    def test_discovery_capability_is_opaque_context_bound_and_single_use(self) -> None:
        with self.assertRaises(TypeError):
            adapter.ValidatedDiscoveryScan()  # type: ignore[call-arg]
        capability = self.capability("AUTHZ")
        forged = {"discovery_scan_id": capability.scan_id, "actionable": False}
        self.assertFalse(adapter.evaluate_discovery_scan_eligibility(forged)["eligible"])
        request = adapter.build_discovery_skill_request(
            validated_scan=capability, query="Hon Hai public company event"
        )
        self.assertEqual(request["authorization_scope"], "DISCOVERY_SCAN")
        self.assertEqual(request["command"], "SEARCH")
        self.assertEqual(request["max_attempts"], 1)
        self.assertFalse(request["fallback_enabled"])
        self.assertFalse(request["actionable"])
        self.assertNotIn("api_key", json.dumps(request).lower())
        for change in (
            {"max_attempts": 2},
            {"fallback_enabled": True},
            {"auth_mode": "AUTO_REGISTER"},
        ):
            with self.subTest(change=change), self.assertRaises(adapter.ResearchSkillGovernanceError):
                adapter.build_discovery_skill_request(
                    validated_scan=capability,
                    query="Hon Hai public company event",
                    **change,
                )
        altered = {**request, "event_reference": "EVENT_FORGED"}
        with self.assertRaisesRegex(adapter.ResearchSkillGovernanceError, "CONTEXT_MISMATCH"):
            adapter.validate_discovery_skill_request_authorization(altered, capability)
        self.orchestrator.run(
            validated_scan=capability,
            query="Hon Hai public company event",
            report_key="P1008_MONTHLY_REVENUE_202607",
            revision=1,
            evaluated_at_utc=NOW,
            news_scan_snapshot=news_snapshot(),
            qualified_event_evidence=[],
            transport=OfflineFixtureTransport(provider_response()),
        )
        with self.assertRaises(ResearchContentIntegrationError):
            self.orchestrator.run(
                validated_scan=capability,
                query="Hon Hai public company event",
                report_key="P1008_MONTHLY_REVENUE_202607",
                revision=1,
                evaluated_at_utc=NOW,
                news_scan_snapshot=news_snapshot(),
                qualified_event_evidence=[],
                transport=OfflineFixtureTransport(provider_response()),
            )

    def test_authorization_is_manifest_bound_opaque_and_non_serializable(self) -> None:
        authorization = adapter.load_validated_discovery_authorization(ROOT)
        self.assertTrue(
            adapter.evaluate_discovery_authorization_eligibility(authorization)[
                "eligible"
            ]
        )
        self.assertEqual(
            authorization.authorization_locator,
            "authorizations/P1008_ANYSEARCH_DISCOVERY_SCAN_AUTHORIZATION_V1.json",
        )
        self.assertEqual(
            authorization.authorization_artifact_sha256,
            "E4978A409B56C563CDCBC18006134D7D1C3C695E0A9162D3DBCE25F148F4981E",
        )
        with self.assertRaises(TypeError):
            adapter.ValidatedDiscoveryAuthorization()  # type: ignore[call-arg]
        with self.assertRaises(TypeError):
            pickle.dumps(authorization)
        copied_json = json.loads(
            (
                ROOT
                / "contracts/p1008_report_governance/v1.0"
                / authorization.authorization_locator
            ).read_text(encoding="utf-8")
        )
        for forged in (
            copied_json,
            authorization.authorization_identity,
            authorization.authorization_artifact_sha256,
        ):
            with self.subTest(forged_type=type(forged).__name__):
                self.assertFalse(
                    adapter.evaluate_discovery_authorization_eligibility(forged)[
                        "eligible"
                    ]
                )
                with self.assertRaisesRegex(
                    adapter.ResearchSkillGovernanceError,
                    "DISCOVERY_AUTHORIZATION_NOT_ELIGIBLE",
                ):
                    self.mint_with_authorization(forged)

    def test_fake_locator_and_modified_authorization_hash_cannot_mint(self) -> None:
        with self.assertRaisesRegex(
            adapter.ResearchSkillGovernanceError,
            "DISCOVERY_AUTHORIZATION_LOCATOR_INVALID",
        ):
            adapter.load_validated_discovery_authorization(ROOT / "fake")

        original_read = adapter._read_controlled_bytes

        def tampered_read(path: Path) -> bytes:
            data = original_read(path)
            if path.name == "P1008_ANYSEARCH_DISCOVERY_SCAN_AUTHORIZATION_V1.json":
                return data.replace(b'"SEARCH"', b'"EXTRACT"')
            return data

        with patch.object(adapter, "_read_controlled_bytes", side_effect=tampered_read):
            with self.assertRaisesRegex(
                adapter.ResearchSkillGovernanceError,
                "DISCOVERY_AUTHORIZATION_ARTIFACT_DRIFT",
            ):
                adapter.load_validated_discovery_authorization(ROOT)

    def test_wrong_authorization_semantics_cannot_validate_or_mint(self) -> None:
        self.assertFalse(
            adapter._exact_json_equal(
                {"nested": [1, {"zero": 0}]},
                {"nested": [True, {"zero": False}]},
            )
        )
        artifacts = adapter._verified_report_governance_artifacts(ROOT)
        authorization = json.loads(
            artifacts[adapter._DISCOVERY_AUTHORIZATION_PATH].decode("utf-8")
        )
        repin = json.loads(artifacts[adapter._DISCOVERY_REPIN_PATH].decode("utf-8"))
        policy = json.loads(artifacts[adapter._DISCOVERY_POLICY_PATH].decode("utf-8"))
        changes = (
            ("wrong identity", lambda value: value["provider"].__setitem__("provider_id", "FORGED")),
            ("wrong endpoint", lambda value: value["provider"].__setitem__("endpoint", "https://example.invalid/mcp")),
            ("wrong scope", lambda value: value.__setitem__("scope", "REPORT_GENERATION")),
            ("wrong command", lambda value: value.__setitem__("command", "EXTRACT_PUBLIC_URL")),
            ("retry", lambda value: value.__setitem__("max_attempts", 2)),
            ("fallback", lambda value: value.__setitem__("fallback_enabled", True)),
            ("attempt bool alias", lambda value: value.__setitem__("max_attempts", True)),
            ("fallback int alias", lambda value: value.__setitem__("fallback_enabled", 0)),
            ("actionable int alias", lambda value: value.__setitem__("actionable", 0)),
            ("authority writes bool alias", lambda value: value.__setitem__("authority_writes", False)),
            ("core view bool alias", lambda value: value.__setitem__("core_view_changes", False)),
            ("formal reports bool alias", lambda value: value.__setitem__("formal_reports_generated", False)),
            ("publication bool alias", lambda value: value.__setitem__("publication_actions", False)),
        )
        for label, mutate in changes:
            candidate = copy.deepcopy(authorization)
            mutate(candidate)
            with self.subTest(label=label), self.assertRaisesRegex(
                adapter.ResearchSkillGovernanceError,
                "DISCOVERY_AUTHORIZATION_CONTENT_INVALID",
            ):
                adapter._validate_discovery_authorization_documents(
                    candidate, repin, policy
                )

    def test_post_validation_authorization_field_drift_blocks_mint(self) -> None:
        drifts = (
            ("authorization_identity", "P1008_FORGED_AUTHORIZATION"),
            ("authorization_version", "9.9"),
            ("authorization_scope", "REPORT_GENERATION"),
            ("authorization_locator", "authorizations/FORGED.json"),
            ("authorization_artifact_sha256", "B" * 64),
            ("provider_id", "FORGED_PROVIDER"),
            ("release_version", "v9.9.9"),
            ("immutable_source_revision", "0" * 40),
            ("artifact_sha256", "C" * 64),
            ("endpoint", "https://example.invalid/mcp"),
            ("command", "EXTRACT_PUBLIC_URL"),
            ("max_attempts", 2),
            ("fallback_enabled", True),
            ("actionable", True),
            ("authority_writes", 1),
            ("core_view_changes", 1),
            ("formal_reports_generated", 1),
            ("publication_actions", 1),
            # bool/int compare equal in Python, so type drift is tested too.
            ("max_attempts", True),
            ("fallback_enabled", 0),
            ("authority_writes", False),
        )
        for field, forged_value in drifts:
            authorization = adapter.load_validated_discovery_authorization(ROOT)
            object.__setattr__(authorization, field, forged_value)
            with self.subTest(field=field):
                self.assertFalse(
                    adapter.evaluate_discovery_authorization_eligibility(
                        authorization
                    )["eligible"]
                )
                with patch(
                    "p1008_research_plugin.adapters.anysearch_runtime._post_once"
                ) as provider_transport:
                    with self.assertRaisesRegex(
                        adapter.ResearchSkillGovernanceError,
                        "DISCOVERY_AUTHORIZATION_TAMPERED",
                    ):
                        self.mint_with_authorization(authorization, "DRIFT")
                    provider_transport.assert_not_called()

    def test_authorization_replay_and_old_direct_mint_are_blocked(self) -> None:
        authorization = adapter.load_validated_discovery_authorization(ROOT)
        scan = self.mint_with_authorization(authorization, "ONCE")
        self.assertTrue(adapter.evaluate_discovery_scan_eligibility(scan)["eligible"])
        self.assertFalse(
            adapter.evaluate_discovery_authorization_eligibility(authorization)[
                "eligible"
            ]
        )
        with self.assertRaisesRegex(
            adapter.ResearchSkillGovernanceError,
            "DISCOVERY_AUTHORIZATION_NOT_ELIGIBLE",
        ):
            self.mint_with_authorization(authorization, "TWICE")
        with self.assertRaises(TypeError):
            adapter._mint_validated_discovery_scan(  # type: ignore[call-arg]
                scan_id="DISCOVERY-SCAN-OLD",
                run_id="P1008-AUTH-OLD",
                scan_reference="SCAN_OLD",
                event_reference="EVENT_OLD",
                authority_manifest_sha256="A" * 64,
                owner_authorization_reference="OWNER_COPIED",
                producer_id="P1008_RESEARCH_CONTENT_ORCHESTRATOR_V1",
                actionable=False,
                consume_callback=lambda: None,
            )

    def test_secret_material_never_enters_receipt_or_result(self) -> None:
        result = self.run_case(
            "SECRET",
            response=provider_response("https://example.com/item?sig=never-store&topic=public"),
            qualified=[],
        )
        serialized = json.dumps(result, sort_keys=True)
        self.assertNotIn("never-store", serialized)
        self.assertNotIn("ANYSEARCH_API_KEY", serialized)
        self.assertNotIn("sig=", serialized)

    def test_arbitrary_transport_is_rejected_before_callback_execution(self) -> None:
        callback_executed = False

        def malicious_transport(_endpoint: str, _payload: dict, _headers: dict) -> dict:
            nonlocal callback_executed
            callback_executed = True
            return provider_response()

        with self.assertRaisesRegex(
            ResearchContentIntegrationError, "UNAUTHORIZED_DISCOVERY_TRANSPORT"
        ):
            self.orchestrator.run(
                validated_scan=self.capability("TRANSPORT-ESCAPE"),
                query="Hon Hai public company event",
                report_key="P1008_MONTHLY_REVENUE_202607",
                revision=1,
                evaluated_at_utc=NOW,
                news_scan_snapshot=news_snapshot(),
                qualified_event_evidence=[],
                transport=malicious_transport,  # type: ignore[arg-type]
            )
        self.assertFalse(callback_executed)

        class FixtureSubclass(OfflineFixtureTransport):
            pass

        with self.assertRaisesRegex(
            ResearchContentIntegrationError, "UNAUTHORIZED_DISCOVERY_TRANSPORT"
        ):
            self.orchestrator.run(
                validated_scan=self.capability("TRANSPORT-SUBCLASS"),
                query="Hon Hai public company event",
                report_key="P1008_MONTHLY_REVENUE_202607",
                revision=1,
                evaluated_at_utc=NOW,
                news_scan_snapshot=news_snapshot(),
                qualified_event_evidence=[],
                transport=FixtureSubclass(provider_response()),
            )

        mutable_response = provider_response("https://example.com/original")
        fixture = OfflineFixtureTransport(mutable_response)
        mutable_response["result"]["content"][0]["text"] = "caller mutation"
        isolated = fixture("unused", {}, {})
        self.assertNotIn("caller mutation", json.dumps(isolated))

        class CallerMapping(dict):
            pass

        with self.assertRaisesRegex(
            ResearchContentIntegrationError, "OFFLINE_FIXTURE_INVALID"
        ):
            OfflineFixtureTransport(CallerMapping(provider_response()))

    def test_unstaged_discovery_and_invalid_news_snapshot_fail_closed(self) -> None:
        unbound = evidence(
            source_class="DISCOVERY",
            source_id="FORGED",
            source_type="OTHER",
            source_locator="https://example.com/forged",
            source_tier="UNVERIFIED",
            evidence_status="DISCOVERED",
        )
        with self.assertRaisesRegex(ResearchContentIntegrationError, "NOT_STAGED"):
            self.run_case("UNBOUND", response=provider_response(), qualified=[unbound])
        invalid = {**news_snapshot(), "productionCsvModified": True}
        with self.assertRaisesRegex(ResearchContentIntegrationError, "NEWS_SCAN_BOUNDARY_INVALID"):
            self.run_case("NEWS-BOUNDARY", response=provider_response(), qualified=[], snapshot=invalid)
        with self.assertRaisesRegex(ResearchContentIntegrationError, "AUTHORITY_PROVENANCE_HASH_MISMATCH"):
            self.run_case(
                "AUTHORITY-HASH",
                response=provider_response(),
                qualified=[evidence(source_hash="F" * 64)],
            )

    def test_module_has_no_report_generation_or_model_client_dependency(self) -> None:
        source = (
            ROOT
            / "modules/p1008_research_plugin/src/p1008_research_plugin/orchestrator/research_content_integration.py"
        ).read_text(encoding="utf-8")
        for forbidden in (
            "ReportBuilder(",
            "ChartDataBuilder(",
            "MarkdownRenderer(",
            "ScriptBuilder(",
            "build_report(",
            "openai",
            "canva",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
