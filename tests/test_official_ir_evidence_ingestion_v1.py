from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys
import unittest
from uuid import uuid4
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
MODULE_SRC = ROOT / "modules" / "p1008_research_plugin" / "src"
TOOLS = ROOT / "tools"
for value in (str(MODULE_SRC), str(TOOLS)):
    if value not in sys.path:
        sys.path.insert(0, value)

from p1008_research_plugin.adapters.official_ir_evidence_adapter import (  # noqa: E402
    FetchResponse,
    OfficialIREvidenceAdapter,
    OfficialIREvidenceError,
    _ascii_transport_url,
    _period,
)
from p1008_research_plugin.orchestrator.research_content_integration import (  # noqa: E402
    ResearchContentIntegrationError,
    ResearchContentOrchestrator,
)
import warroom_report_trigger_runtime as trigger_runtime  # noqa: E402


NOW = "2026-08-12T12:30:00Z"
CALENDAR = "https://www.honhai.com/zh-tw/investor-relations/investor-relations-activities/event-calendar"
CONFERENCE = "https://www.honhai.com/zh-tw/investor-relations/investor-relations-activities/investor-conference"
QUARTERLY = "https://www.honhai.com/zh-tw/investor-relations/financial-information/reports?category=quarterly"
OBSOLETE_QUARTERLY = "https://www.honhai.com/zh-tw/investor-relations/financial-information/reports?section=quarterly"
PRESS = "https://www.honhai.com/zh-tw/press-center/press-releases/latest-news"
MOPS = "https://mops.twse.com.tw/mops/api/t164sb03"
RESULTS = "https://image.honhai.com/lawtalk/Hon_Hai_2Q26_Results_Chinese.pdf"
TRANSCRIPT = "https://image.honhai.com/lawtalk/Hon_Hai_2Q26_Results_Transcript_Chinese.pdf"
REPORT = "https://image.honhai.com/financial/Hon_Hai_2026_Q2_Financial_Report.pdf"
Q1_RESULTS = "https://image.honhai.com/lawtalk/Hon_Hai_1Q26_Results_Chinese.pdf"
Q4_RESULTS = "https://image.honhai.com/lawtalk/Hon_Hai_4Q25_Results_Chinese.pdf"
Q3_RESULTS = "https://image.honhai.com/lawtalk/Hon_Hai_3Q25_Results_Chinese.pdf"


def html(body: str, url: str) -> FetchResponse:
    return FetchResponse(body.encode(), url, 200, "text/html; charset=utf-8")


def pdf(body: bytes, url: str) -> FetchResponse:
    return FetchResponse(b"%PDF-1.7\n" + body, url, 200, "application/pdf")


class FixtureTransport:
    def __init__(self, values: dict[str, FetchResponse | Exception]) -> None:
        self.values = values
        self.calls: list[str] = []

    def __call__(self, url: str) -> FetchResponse:
        self.calls.append(url)
        value = self.values[url]
        if isinstance(value, Exception):
            raise value
        return value


class OfficialIREvidenceIngestionTests(unittest.TestCase):
    def setUp(self) -> None:
        scratch = ROOT / "runtime" / "official_ir_test_scratch"
        scratch.mkdir(parents=True, exist_ok=True)
        self.root = scratch / f"p1008-official-ir-{uuid4().hex}"
        self.root.mkdir()
        shutil.copytree(ROOT / "contracts", self.root / "contracts")
        shutil.copytree(ROOT / "data", self.root / "data")
        shutil.copytree(ROOT / "rules", self.root / "rules")
        (self.root / "tools").mkdir()
        shutil.copy2(ROOT / "tools" / "warroom_report_governance.py", self.root / "tools")

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=False)
        try:
            self.root.parent.rmdir()
            self.root.parent.parent.rmdir()
        except OSError:
            pass

    def mapping(self, *, conference: str = "", quarterly: str = "", press: str = "", mops: str = "", documents: dict[str, bytes] | None = None) -> dict[str, FetchResponse | Exception]:
        values: dict[str, FetchResponse | Exception] = {
            CALENDAR: html("<table><tr><td>2026/08/12</td><td>2026年第二季法人說明會</td></tr></table>", CALENDAR),
            CONFERENCE: html(conference, CONFERENCE),
            QUARTERLY: html(quarterly, QUARTERLY),
            PRESS: html(press, PRESS),
            MOPS: html(mops, MOPS),
        }
        for url, body in (documents or {}).items():
            values[url] = pdf(body, url)
        return values

    def scan(self, values: dict[str, FetchResponse | Exception]):
        return OfficialIREvidenceAdapter(self.root, transport=FixtureTransport(values)).scan(target_period=(2026, 2), evaluated_at_utc=NOW)

    def scan_period(self, values: dict[str, FetchResponse | Exception], target_period: tuple[int, int] | None):
        return OfficialIREvidenceAdapter(self.root, transport=FixtureTransport(values)).scan(target_period=target_period, evaluated_at_utc=NOW)

    @staticmethod
    def mixed_history_page(order: tuple[str, ...] = (RESULTS, Q1_RESULTS, Q4_RESULTS, Q3_RESULTS)) -> str:
        labels = {
            RESULTS: "Hon Hai 2Q26 Results",
            Q1_RESULTS: "Hon Hai 1Q26 Results",
            Q4_RESULTS: "Hon Hai 4Q25 Results",
            Q3_RESULTS: "Hon Hai 3Q25 Results",
        }
        return "".join(f'<a href="{url}">{labels[url]}</a>' for url in order)

    def mixed_history_mapping(self, order: tuple[str, ...] = (RESULTS, Q1_RESULTS, Q4_RESULTS, Q3_RESULTS)):
        return self.mapping(
            conference=self.mixed_history_page(order),
            documents={url: url.encode("ascii") for url in order},
        )

    def test_schedule_only_is_watch_and_never_triggers(self) -> None:
        result = self.scan(self.mapping())
        self.assertEqual(result["status"], "SCHEDULE_CONFIRMED")
        self.assertEqual(result["schedule"]["state"], "EVENT_SCHEDULE_CONFIRMED")
        self.assertEqual(result["validated_event_evidence"], [])
        integration = ResearchContentOrchestrator(self.root).integrate_official_ir(result)
        self.assertEqual(integration["display_state"], "WATCH")
        self.assertFalse(integration["report_trigger_decision"]["report_trigger_valid"])

    def test_results_pdf_enters_orchestrator_and_triggers_g1(self) -> None:
        result = self.scan(self.mapping(
            conference=f'<a href="{RESULTS}">Hon Hai 2Q26 Results</a>',
            documents={RESULTS: b"official-results"},
        ))
        self.assertEqual(result["status"], "AUTHORITY_EVIDENCE_READY")
        evidence = result["validated_event_evidence"]
        self.assertEqual(evidence[0]["event_type"], "QUARTERLY_EARNINGS")
        self.assertEqual(evidence[0]["quality_metadata"]["document_type"], "RESULTS_DOCUMENT_CONFIRMED")
        integration = ResearchContentOrchestrator(self.root).integrate_official_ir(result)
        self.assertEqual(integration["report_key"], "P1008_FY2026_Q2_EARNINGS")
        self.assertEqual(integration["evidence"]["cross_validation"]["validation_status"], "AUTHORITY_CONFIRMED")
        self.assertEqual(integration["report_trigger_decision"]["decision"], "TRIGGERED_INTERNAL_REPORT")
        trigger_runtime.persist_integration_result(self.root, integration)
        receipt = trigger_runtime.evaluate_and_persist(self.root, evaluated_at_utc=NOW)
        self.assertTrue(receipt["report_trigger_valid"])
        self.assertFalse(receipt["report_generated"])
        self.assertFalse(receipt["report_candidate_valid"])
        self.assertFalse(receipt["actionable"])

    def test_transcript_quarterly_press_and_mops_share_one_event(self) -> None:
        values = self.mapping(
            conference=f'<a href="{RESULTS}">Hon Hai 2Q26 Results</a><a href="{TRANSCRIPT}">Hon Hai 2Q26 Results Transcript</a>',
            quarterly=f'<a href="{REPORT}">2026 Q2 財務報告</a>',
            press='<a href="/zh-tw/press-center/press-releases/latest-news/123">鴻海2026年第二季財務結果</a>',
            mops="2317 鴻海 2026年第二季 財務報告",
            documents={RESULTS: b"results", TRANSCRIPT: b"transcript", REPORT: b"report"},
        )
        # The press detail URL is governed and represented as HTML evidence.
        detail = "https://www.honhai.com/zh-tw/press-center/press-releases/latest-news/123"
        values[detail] = html("鴻海2026年第二季財務結果", detail)
        result = self.scan(values)
        self.assertEqual({item["canonical_event_id"] for item in result["validated_event_evidence"]}, {"HON_HAI_FY2026_Q2_EARNINGS"})
        self.assertEqual(result["report_key"], "P1008_FY2026_Q2_EARNINGS")
        types = {item["quality_metadata"]["document_type"] for item in result["validated_event_evidence"]}
        self.assertTrue({"RESULTS_DOCUMENT_CONFIRMED", "CALL_TRANSCRIPT_CONFIRMED", "QUARTERLY_REPORT_CONFIRMED", "RESULTS_PRESS_RELEASE_CONFIRMED", "MOPS_RESULTS_DISCLOSURE_CONFIRMED"}.issubset(types), types)

    def test_mixed_history_selects_newest_active_event_and_runtime_accepts_it(self) -> None:
        result = self.scan_period(self.mixed_history_mapping(), None)
        self.assertEqual(result["detected_evidence_count"], 4)
        self.assertEqual(result["active_event_evidence_count"], 1)
        self.assertEqual(result["historical_evidence_count"], 3)
        self.assertEqual(result["active_fiscal_period"], "FY2026 Q2")
        self.assertEqual(result["canonical_event_id"], "HON_HAI_FY2026_Q2_EARNINGS")
        self.assertEqual(result["report_key"], "P1008_FY2026_Q2_EARNINGS")
        self.assertEqual(
            {item["canonical_event_id"] for item in result["validated_event_evidence"]},
            {"HON_HAI_FY2026_Q2_EARNINGS"},
        )
        self.assertEqual(
            {item["canonical_event_id"] for item in result["historical_evidence"]},
            {
                "HON_HAI_FY2026_Q1_EARNINGS",
                "HON_HAI_FY2025_Q4_EARNINGS",
                "HON_HAI_FY2025_Q3_EARNINGS",
            },
        )
        integration = ResearchContentOrchestrator(self.root).integrate_official_ir(result)
        self.assertEqual(integration["evidence"]["cross_validation"]["validation_status"], "AUTHORITY_CONFIRMED")
        self.assertEqual(integration["report_trigger_decision"]["decision"], "TRIGGERED_INTERNAL_REPORT")
        trigger_runtime.persist_integration_result(self.root, integration)
        receipt = trigger_runtime.evaluate_and_persist(self.root, evaluated_at_utc=NOW)
        self.assertEqual(receipt["canonical_event_id"], "HON_HAI_FY2026_Q2_EARNINGS")
        self.assertEqual(receipt["decision"], "TRIGGERED_INTERNAL_REPORT")

    def test_explicit_target_scopes_trigger_but_preserves_detected_history(self) -> None:
        result = self.scan_period(self.mixed_history_mapping(), (2026, 1))
        self.assertEqual(result["detected_evidence_count"], 4)
        self.assertEqual(result["canonical_event_id"], "HON_HAI_FY2026_Q1_EARNINGS")
        self.assertEqual(result["report_key"], "P1008_FY2026_Q1_EARNINGS")
        self.assertEqual(
            {item["canonical_event_id"] for item in result["validated_event_evidence"]},
            {"HON_HAI_FY2026_Q1_EARNINGS"},
        )
        self.assertEqual(result["historical_evidence_count"], 3)

    def test_active_event_selection_is_independent_of_link_order(self) -> None:
        forward = self.scan_period(self.mixed_history_mapping(), None)
        reverse = self.scan_period(
            self.mixed_history_mapping((Q3_RESULTS, Q4_RESULTS, Q1_RESULTS, RESULTS)),
            None,
        )
        self.assertEqual(forward["canonical_event_id"], reverse["canonical_event_id"])
        self.assertEqual(forward["report_key"], reverse["report_key"])
        self.assertEqual(forward["active_fiscal_period"], reverse["active_fiscal_period"])

    def test_future_schedule_does_not_steal_current_published_results(self) -> None:
        values = self.mixed_history_mapping()
        values[CALENDAR] = html("2026 Q3 earnings conference", CALENDAR)
        result = self.scan_period(values, None)
        self.assertEqual(result["schedule"]["fiscal_period"], "FY2026 Q3")
        self.assertEqual(result["canonical_event_id"], "HON_HAI_FY2026_Q2_EARNINGS")
        self.assertEqual(result["active_fiscal_period"], "FY2026 Q2")

    def test_orchestrator_rejects_mixed_scope_and_report_identity_mismatch(self) -> None:
        result = self.scan_period(self.mixed_history_mapping(), None)
        mixed = dict(result)
        mixed["validated_event_evidence"] = [
            result["validated_event_evidence"][0],
            result["historical_evidence"][0],
        ]
        with self.assertRaisesRegex(ResearchContentIntegrationError, "CANONICAL_EVENT_SCOPE_MISMATCH"):
            ResearchContentOrchestrator(self.root).integrate_official_ir(mixed)
        mismatched = dict(result)
        mismatched["report_key"] = "P1008_FY2026_Q1_EARNINGS"
        with self.assertRaisesRegex(ResearchContentIntegrationError, "CANONICAL_EVENT_SCOPE_MISMATCH"):
            ResearchContentOrchestrator(self.root).integrate_official_ir(mismatched)

    def test_duplicate_document_is_idempotent_and_changed_bytes_change_identity(self) -> None:
        page = f'<a href="{RESULTS}">Hon Hai 2Q26 Results</a><a href="{RESULTS}">Hon Hai 2Q26 Results</a>'
        first = self.scan(self.mapping(conference=page, documents={RESULTS: b"v1"}))
        second = self.scan(self.mapping(conference=page, documents={RESULTS: b"v1"}))
        self.assertEqual(len(first["validated_event_evidence"]), 1)
        self.assertEqual(first["validated_event_evidence"][0]["event_id"], second["validated_event_evidence"][0]["event_id"])
        changed = self.scan(self.mapping(conference=page, documents={RESULTS: b"v2"}))
        self.assertNotEqual(first["validated_event_evidence"][0]["source_hash"], changed["validated_event_evidence"][0]["source_hash"])

    def test_off_domain_redirect_and_malformed_pdf_fail_closed_per_source(self) -> None:
        off_domain = self.mapping(conference='<a href="https://evil.example/2Q26_Results.pdf">2Q26 Results</a>')
        blocked = self.scan(off_domain)
        self.assertEqual(blocked["status"], "PARTIAL_FAILURE_NO_AUTHORITY")
        self.assertEqual(blocked["validated_event_evidence"], [])
        self.assertEqual(next(item for item in blocked["failed_sources"] if item["source_id"] == "HON_HAI_INVESTOR_CONFERENCE")["status"], "SECURITY_REJECTED")
        redirect = self.mapping(conference=f'<a href="{RESULTS}">2Q26 Results</a>', documents={RESULTS: b"x"})
        redirect[RESULTS] = FetchResponse(b"%PDF-x", "https://evil.example/result.pdf", 200, "application/pdf")
        self.assertEqual(self.scan(redirect)["status"], "PARTIAL_FAILURE_NO_AUTHORITY")
        malformed = self.mapping(conference=f'<a href="{RESULTS}">2Q26 Results</a>')
        malformed[RESULTS] = FetchResponse(b"not-pdf", RESULTS, 200, "text/html")
        self.assertEqual(self.scan(malformed)["status"], "PARTIAL_FAILURE_NO_AUTHORITY")

    def test_results_survive_mops_timeout_and_reach_g1(self) -> None:
        values = self.mapping(conference=f'<a href="{RESULTS}">2Q26 Results</a>', documents={RESULTS: b"results"})
        values[MOPS] = OfficialIREvidenceError("NETWORK_TIMEOUT")
        result = self.scan(values)
        self.assertEqual(result["scan_status"], "PARTIAL_FAILURE")
        self.assertEqual(result["status"], "PARTIAL_FAILURE_WITH_AUTHORITY")
        self.assertFalse(result["coverage_complete"])
        self.assertTrue(result["scan_integrity_valid"])
        self.assertEqual(len(result["validated_event_evidence"]), 1)
        self.assertEqual(result["failed_sources"][0]["status"], "TIMEOUT")
        integration = ResearchContentOrchestrator(self.root).integrate_official_ir(result)
        self.assertEqual(len(integration["validated_event_evidence"]), 1)
        self.assertEqual(integration["report_trigger_decision"]["decision"], "TRIGGERED_INTERNAL_REPORT")

    def test_results_survive_mops_http_error_and_reach_g1(self) -> None:
        values = self.mapping(conference=f'<a href="{RESULTS}">2Q26 Results</a>', documents={RESULTS: b"results"})
        values[MOPS] = FetchResponse(b"error", MOPS, 500, "text/html")
        result = self.scan(values)
        self.assertEqual(result["status"], "PARTIAL_FAILURE_WITH_AUTHORITY")
        self.assertEqual(len(result["validated_event_evidence"]), 1)
        self.assertEqual(result["failed_sources"][0]["status"], "HTTP_ERROR")
        integration = ResearchContentOrchestrator(self.root).integrate_official_ir(result)
        self.assertEqual(len(integration["validated_event_evidence"]), 1)

    def test_current_mops_financial_api_response_is_period_bound_authority(self) -> None:
        values = self.mapping()
        values[MOPS] = FetchResponse(
            json.dumps({"code": 200, "result": {"year": "115", "season": "2", "reportList": [["official"]]}}).encode(),
            MOPS,
            200,
            "application/json;charset=UTF-8",
            request_method="POST",
            request_body_sha256="A" * 64,
        )
        result = self.scan(values)
        mops = next(item for item in result["validated_event_evidence"] if item["source_id"] == "MOPS_OFFICIAL_DISCLOSURE")
        self.assertEqual(mops["canonical_event_id"], "HON_HAI_FY2026_Q2_EARNINGS")
        self.assertEqual(mops["quality_metadata"]["document_type"], "MOPS_RESULTS_DISCLOSURE_CONFIRMED")
        self.assertEqual(next(item for item in result["source_statuses"] if item["source_id"] == "MOPS_OFFICIAL_DISCLOSURE")["status"], "SUCCESS")

    def test_mops_financial_api_rejects_wrong_period_and_empty_report(self) -> None:
        for result_payload in (
            {"year": "115", "season": "1", "reportList": [["wrong-quarter"]]},
            {"year": "115", "season": "2", "reportList": []},
        ):
            with self.subTest(result=result_payload):
                values = self.mapping()
                values[MOPS] = FetchResponse(
                    json.dumps({"code": 200, "result": result_payload}).encode(),
                    MOPS,
                    200,
                    "application/json;charset=UTF-8",
                    request_method="POST",
                    request_body_sha256="A" * 64,
                )
                result = self.scan(values)
                failure = next(item for item in result["failed_sources"] if item["source_id"] == "MOPS_OFFICIAL_DISCLOSURE")
                self.assertEqual(failure["error"], "MOPS_RESPONSE_SCHEMA_INVALID")

    def test_invalid_results_hash_does_not_block_independent_mops_evidence(self) -> None:
        values = self.mapping(
            conference=f'<a href="{RESULTS}">2Q26 Results</a>',
            mops="2317 2026 Q2",
            documents={RESULTS: b"genuine"},
        )
        result = self.scan(values)
        results = next(item for item in result["validated_event_evidence"] if item["source_id"] == "HON_HAI_INVESTOR_CONFERENCE")
        (self.root / results["provenance"]["raw_artifact_path"]).write_bytes(b"tampered")
        integration = ResearchContentOrchestrator(self.root).integrate_official_ir(result)
        self.assertEqual([item["source_id"] for item in integration["validated_event_evidence"]], ["MOPS_OFFICIAL_DISCLOSURE"])
        self.assertEqual(integration["official_ir"]["evidence_validation_failures"][0]["source_id"], "HON_HAI_INVESTOR_CONFERENCE")

    def test_all_official_sources_fail_without_evidence_or_trigger(self) -> None:
        values = self.mapping()
        for url in (CALENDAR, CONFERENCE, QUARTERLY, PRESS, MOPS):
            values[url] = OfficialIREvidenceError("NETWORK_TIMEOUT")
        result = self.scan(values)
        self.assertEqual(result["status"], "FAIL_CLOSED")
        self.assertEqual(result["validated_event_evidence"], [])
        self.assertEqual(len(result["failed_sources"]), 5)
        with self.assertRaisesRegex(ResearchContentIntegrationError, "FAIL_CLOSED"):
            ResearchContentOrchestrator(self.root).integrate_official_ir(result)

    def test_off_domain_results_and_mops_outage_never_promote_evidence(self) -> None:
        values = self.mapping(conference='<a href="https://evil.example/2Q26_Results.pdf">2Q26 Results</a>')
        values[MOPS] = OfficialIREvidenceError("OFFICIAL_ENDPOINT_ERROR")
        result = self.scan(values)
        self.assertEqual(result["status"], "PARTIAL_FAILURE_NO_AUTHORITY")
        self.assertEqual(result["validated_event_evidence"], [])
        integration = ResearchContentOrchestrator(self.root).integrate_official_ir(result)
        self.assertFalse(integration["report_trigger_decision"]["report_trigger_valid"])

    def test_schedule_survives_mops_outage_without_trigger(self) -> None:
        values = self.mapping()
        values[MOPS] = OfficialIREvidenceError("OFFICIAL_ENDPOINT_ERROR")
        result = self.scan(values)
        self.assertEqual(result["status"], "PARTIAL_FAILURE_NO_AUTHORITY")
        self.assertEqual(result["schedule"]["state"], "EVENT_SCHEDULE_CONFIRMED")
        self.assertEqual(result["validated_event_evidence"], [])
        integration = ResearchContentOrchestrator(self.root).integrate_official_ir(result)
        self.assertEqual(integration["display_state"], "WATCH")
        self.assertFalse(integration["report_trigger_decision"]["report_trigger_valid"])

    def test_wrong_mops_issuer_generic_press_old_period_and_url_injection_do_not_promote(self) -> None:
        values = self.mapping(
            conference='<a href="https://image.honhai.com/lawtalk/Hon_Hai_2Q25_Results.pdf">2Q25 Results</a>',
            press='<a href="/zh-tw/press-center/press-releases/latest-news/ai">鴻海 AI 伺服器活動</a>',
            mops="2330 台積電 2026年第二季 財務報告",
        )
        old_results = "https://image.honhai.com/lawtalk/Hon_Hai_2Q25_Results.pdf"
        values[old_results] = pdf(b"historical-results", old_results)
        result = self.scan(values)
        self.assertEqual(result["validated_event_evidence"], [])
        adapter = OfficialIREvidenceAdapter(self.root, transport=FixtureTransport(values))
        with self.assertRaisesRegex(OfficialIREvidenceError, "OFF_DOMAIN"):
            adapter.validate_url("https://example.com/user-controlled")
        with self.assertRaises(OfficialIREvidenceError):
            adapter.validate_url("http://127.0.0.1/internal")

    def test_quarterly_discovery_uses_only_the_current_fixed_official_source(self) -> None:
        adapter = OfficialIREvidenceAdapter(self.root, transport=FixtureTransport(self.mapping()))
        self.assertEqual(adapter.validate_url(QUARTERLY, fixed_page=True), QUARTERLY)
        with self.assertRaisesRegex(OfficialIREvidenceError, "OFF_DOMAIN_URL_REJECTED"):
            adapter.validate_url(OBSOLETE_QUARTERLY, fixed_page=True)

    def test_hash_mismatch_is_rejected(self) -> None:
        result = self.scan(self.mapping(conference=f'<a href="{RESULTS}">2Q26 Results</a>', documents={RESULTS: b"genuine"}))
        evidence = result["validated_event_evidence"][0]
        raw_path = self.root / evidence["provenance"]["raw_artifact_path"]
        raw_path.write_bytes(b"tampered")
        with self.assertRaisesRegex(ResearchContentIntegrationError, "HASH_MISMATCH"):
            ResearchContentOrchestrator(self.root).integrate_official_ir(result)

    def test_launcher_wires_separate_official_component_without_auto_candidates(self) -> None:
        server = (ROOT / "tools" / "p1008_app_server.py").read_text(encoding="utf-8")
        launcher = (ROOT / "launcher.html").read_text(encoding="utf-8")
        self.assertIn('"official-ir-scan", "Governed Official IR evidence scan"', server)
        self.assertIn('"/api/p1008/run/official-ir-scan": "official-ir-scan"', server)
        self.assertLess(server.index("self._run_news_scan_step()"), server.index("self._run_official_ir_step()"))
        self.assertLess(server.index("self._run_official_ir_step()"), server.index("self._evaluate_report_trigger_step()"))
        self.assertIn('id="official-ir-status"', launcher)
        self.assertIn('id="official-ir-coverage"', launcher)
        self.assertIn('id="official-ir-failures"', launcher)
        self.assertIn("Schedule awareness is not results authority.", launcher)
        adapter = (ROOT / "modules/p1008_research_plugin/src/p1008_research_plugin/adapters/official_ir_evidence_adapter.py").read_text(encoding="utf-8")
        self.assertNotIn("openai", adapter.lower())
        self.assertNotIn("generate_report", adapter)


class OfficialIRTransportPortabilityTests(unittest.TestCase):
    def test_existing_period_normalizer_accepts_canonical_quarters_and_rejects_invalid(self) -> None:
        for value, expected in (
            ("FY2025 Q4", (2025, 4)),
            ("FY2026 Q1", (2026, 1)),
            ("FY2026 Q2", (2026, 2)),
            ("FY2026 Q3", (2026, 3)),
            ("FY2026 Q4", (2026, 4)),
            ("FY2027 Q1", (2027, 1)),
        ):
            with self.subTest(value=value):
                self.assertEqual(_period(value), expected)
        for value in ("FY2026 Q0", "FY2026 Q5", "FY2026"):
            with self.subTest(value=value):
                self.assertIsNone(_period(value))

    def test_live_mops_missing_target_period_remains_fail_closed(self) -> None:
        adapter = OfficialIREvidenceAdapter.__new__(OfficialIREvidenceAdapter)
        with self.assertRaisesRegex(OfficialIREvidenceError, "MOPS_TARGET_PERIOD_REQUIRED"):
            adapter._fetch_live_mops({}, None)

    def test_unicode_official_link_is_ascii_encoded_only_for_transport(self) -> None:
        original = "https://image.honhai.com/lawtalk/鴻海_2Q26_Results.pdf?語言=中文"
        encoded = _ascii_transport_url(original)
        self.assertTrue(encoded.isascii())
        self.assertIn("%E9%B4%BB%E6%B5%B7", encoded)
        self.assertIn("%E8%AA%9E%E8%A8%80=%E4%B8%AD%E6%96%87", encoded)
        self.assertEqual(_ascii_transport_url(encoded), encoded)

    def test_live_fetch_builds_request_from_ascii_transport_url(self) -> None:
        original = "https://image.honhai.com/lawtalk/鴻海_2Q26_Results.pdf"
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = b"%PDF-1.7\nfixture"
        response.geturl.return_value = _ascii_transport_url(original)
        response.status = 200
        response.headers.get.return_value = "application/pdf"
        response.headers.items.return_value = []
        opener = mock.MagicMock()
        opener.open.return_value = response
        adapter = OfficialIREvidenceAdapter.__new__(OfficialIREvidenceAdapter)
        adapter.authorization = {"timeoutSeconds": 12, "maxResponseBytes": 1024}
        adapter._validate_live_url = mock.MagicMock(side_effect=lambda value: value)
        with mock.patch(
            "p1008_research_plugin.adapters.official_ir_evidence_adapter.build_opener",
            return_value=opener,
        ):
            result = adapter._fetch_live(original)
        request = opener.open.call_args.args[0]
        self.assertTrue(request.full_url.isascii())
        self.assertIn("%E9%B4%BB%E6%B5%B7", request.full_url)
        self.assertEqual(result.body, b"%PDF-1.7\nfixture")

    def test_live_mops_fetch_uses_exact_post_profile_and_records_lineage(self) -> None:
        body = json.dumps({"code": 200, "result": {"year": "115", "season": "2", "reportList": [["official"]]}}).encode()
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = body
        response.geturl.return_value = MOPS
        response.status = 200
        response.headers.get.return_value = "application/json;charset=UTF-8"
        response.headers.items.return_value = []
        opener = mock.MagicMock()
        opener.open.return_value = response
        adapter = OfficialIREvidenceAdapter.__new__(OfficialIREvidenceAdapter)
        adapter.authorization = {"timeoutSeconds": 12, "maxResponseBytes": 1024, "issuer": {"stockId": "2317"}}
        adapter._validate_live_url = mock.MagicMock(side_effect=lambda value: value)
        adapter.validate_url = mock.MagicMock(side_effect=lambda value, **_: value)
        source = {"url": MOPS, "requestMethod": "POST", "requestProfile": "MOPS_T164SB03_FINANCIAL_STATEMENT_V1"}
        with mock.patch(
            "p1008_research_plugin.adapters.official_ir_evidence_adapter.build_opener",
            return_value=opener,
        ):
            result = adapter._fetch_live_mops(source, (2026, 2))
        request = opener.open.call_args.args[0]
        self.assertEqual(request.method, "POST")
        self.assertEqual(json.loads(request.data), {"companyId": "2317", "dataType": "2", "year": "115", "season": "2", "subsidiaryCompanyId": ""})
        self.assertEqual(result.request_method, "POST")
        self.assertRegex(result.request_body_sha256 or "", r"^[A-F0-9]{64}$")


if __name__ == "__main__":
    unittest.main()
