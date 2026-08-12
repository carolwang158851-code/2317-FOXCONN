from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest


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
)
from p1008_research_plugin.orchestrator.research_content_integration import (  # noqa: E402
    ResearchContentIntegrationError,
    ResearchContentOrchestrator,
)
import warroom_report_trigger_runtime as trigger_runtime  # noqa: E402


NOW = "2026-08-12T12:30:00Z"
CALENDAR = "https://www.honhai.com/zh-tw/investor-relations/investor-relations-activities/event-calendar"
CONFERENCE = "https://www.honhai.com/zh-tw/investor-relations/investor-relations-activities/investor-conference"
QUARTERLY = "https://www.honhai.com/zh-tw/investor-relations/financial-information/reports?section=quarterly"
PRESS = "https://www.honhai.com/zh-tw/press-center/press-releases/latest-news"
MOPS = "https://mops.twse.com.tw/mops/web/t05st02"
RESULTS = "https://image.honhai.com/lawtalk/Hon_Hai_2Q26_Results_Chinese.pdf"
TRANSCRIPT = "https://image.honhai.com/lawtalk/Hon_Hai_2Q26_Results_Transcript_Chinese.pdf"
REPORT = "https://image.honhai.com/financial/Hon_Hai_2026_Q2_Financial_Report.pdf"


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
        self.temp = tempfile.TemporaryDirectory(dir=scratch)
        self.root = Path(self.temp.name)
        shutil.copytree(ROOT / "contracts", self.root / "contracts")
        shutil.copytree(ROOT / "data", self.root / "data")
        shutil.copytree(ROOT / "rules", self.root / "rules")
        (self.root / "tools").mkdir()
        shutil.copy2(ROOT / "tools" / "warroom_report_governance.py", self.root / "tools")

    def tearDown(self) -> None:
        self.temp.cleanup()

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
        result = self.scan(values)
        self.assertEqual(result["validated_event_evidence"], [])
        adapter = OfficialIREvidenceAdapter(self.root, transport=FixtureTransport(values))
        with self.assertRaisesRegex(OfficialIREvidenceError, "OFF_DOMAIN"):
            adapter.validate_url("https://example.com/user-controlled")
        with self.assertRaises(OfficialIREvidenceError):
            adapter.validate_url("http://127.0.0.1/internal")

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


if __name__ == "__main__":
    unittest.main()
