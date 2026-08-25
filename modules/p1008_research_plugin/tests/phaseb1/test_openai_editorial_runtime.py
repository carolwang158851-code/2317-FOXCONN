from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest import mock

from pydantic import ValidationError

try:
    from .helpers import PACKAGE_ROOT, scratch, fixture_pipeline
except ImportError:
    from helpers import PACKAGE_ROOT, scratch, fixture_pipeline

from p1008_research_plugin.openai.model_registry import ModelDefinition
from p1008_research_plugin.phaseb1_pipeline import (
    PhaseB1PipelineError,
)
from p1008_research_plugin.plugin_module.agent_runner import (
    LiveAgentsSdkClient,
)
from p1008_research_plugin.plugin_module.contracts import TokenUsage
from p1008_research_plugin.plugin_module.router import PluginRouter
from p1008_research_plugin.reporting import template_governance
from p1008_research_plugin.reporting.report_contracts import (
    EditorialExecutionAuthorization,
    EditorialResultEnvelope,
    ReportCandidate,
)
from p1008_research_plugin.runtime.runtime_config import (
    PHASE3B_LIVE_MODEL_ID,
    RuntimeConfig,
    RuntimeConfigurationError,
)
from p1008_research_plugin.runtime.runtime_manager import RuntimeManager


class FakeEditorialClient:
    mode = "DETERMINISTIC_TEST_DOUBLE"
    model_id = PHASE3B_LIVE_MODEL_ID
    provider_response_id = "test-response-editorial"

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls = 0
        self.payload = None

    def synthesize_editorial(self, *, payload, instructions):
        self.calls += 1
        self.payload = payload
        if self.fail:
            raise RuntimeError("offline provider failure")
        candidate = ReportCandidate.model_validate(payload["structuredDraft"])
        return candidate, TokenUsage(
            source="DETERMINISTIC_ESTIMATE",
            model_id=PHASE3B_LIVE_MODEL_ID,
            input_tokens=10,
            output_tokens=5,
            total_tokens=15,
        )


def authorization(run_id: str, **changes):
    payload = {
        "runId": run_id,
        "taskId": "WAR_REPORT_EDITORIAL_SYNTHESIS",
        "templateId": template_governance.TEMPLATE_ID,
        "templateVersion": template_governance.TEMPLATE_VERSION,
        "model": PHASE3B_LIVE_MODEL_ID,
        "maxCalls": 1,
        "fallbackAllowed": False,
        "webSearchAllowed": False,
        "publication": False,
        "actionable": False,
        "ownerReviewRequired": True,
        "ownerAuthorized": True,
        "authorizationReference": "OFFLINE-TEST-OWNER-AUTHORIZATION",
    }
    payload.update(changes)
    return payload


class OpenAIEditorialRuntimeTests(unittest.TestCase):
    def _run_editorial(self, root: Path, client=None):
        pipeline = fixture_pipeline(root)
        output = root / "output"
        analysis = pipeline.build_analysis(output_base=output)
        pipeline.editorial_required = True
        pipeline.editorial_authorization = authorization(analysis["run_id"])
        pipeline.editorial_client = client or FakeEditorialClient()
        result = pipeline.build_report(
            run_id=analysis["run_id"], output_base=output
        )
        return result, pipeline.editorial_client

    def test_mocked_execution_produces_hash_bound_editorial_envelope(self):
        with scratch("editorial-envelope-") as root:
            result, client = self._run_editorial(root)
            envelope = result["editorial_result_envelope"]
            self.assertIsInstance(envelope, EditorialResultEnvelope)
            self.assertEqual(envelope.validation_status, "PASS")
            self.assertEqual(
                envelope.input_research_pack_sha256, result["analysis_sha256"]
            )
            self.assertFalse(envelope.governance.actionable)
            self.assertFalse(envelope.governance.publication)
            self.assertTrue(envelope.governance.owner_review_required)
            self.assertEqual(client.calls, 1)
            self.assertEqual(
                set(client.payload),
                {
                    "taskType", "templateId", "templateVersion", "missionContext",
                    "inputResearchPackSha256", "validatedResearchPack",
                    "structuredDraft", "chartConclusions", "allowedInputClasses",
                    "webSearchAllowed", "publication", "actionable",
                },
            )
            receipt = Path(result["run_root"]) / "editorial_result_envelope.json"
            self.assertTrue(receipt.is_file())

    def test_hashes_and_governance_are_mandatory_and_fail_closed(self):
        with scratch("editorial-contract-") as root:
            result, _ = self._run_editorial(root)
            payload = result["editorial_result_envelope"].model_dump(
                mode="json", by_alias=True
            )
            for field in ("inputResearchPackSha256", "editorialOutputSha256"):
                broken = dict(payload)
                broken.pop(field)
                with self.subTest(field=field), self.assertRaises(ValidationError):
                    EditorialResultEnvelope.model_validate(broken)
            for field, value in (
                ("inputResearchPackSha256", "0" * 64),
                ("editorialOutputSha256", "F" * 64),
            ):
                broken = dict(payload)
                broken[field] = value
                with self.subTest(field=field), self.assertRaises(ValidationError):
                    EditorialResultEnvelope.model_validate(broken)
            for field, value in (
                ("actionable", True),
                ("publication", True),
                ("ownerReviewRequired", False),
            ):
                broken = json.loads(json.dumps(payload))
                broken["governance"][field] = value
                with self.subTest(field=field), self.assertRaises(ValidationError):
                    EditorialResultEnvelope.model_validate(broken)

    def test_live_receipt_requires_provider_response_id(self):
        with scratch("editorial-response-id-") as root:
            result, _ = self._run_editorial(root)
            payload = result["editorial_result_envelope"].model_dump(
                mode="json", by_alias=True
            )
            payload["executionStatus"] = "EXECUTED_LIVE"
            payload["modelProvenance"]["modelSurface"] = "OPENAI_AGENTS_SDK"
            payload["modelProvenance"]["status"] = "EXECUTED_LIVE"
            payload["providerResponseId"] = None
            with self.assertRaises(ValidationError):
                EditorialResultEnvelope.model_validate(payload)

    def test_model_fallback_and_wrong_model_are_rejected(self):
        with self.assertRaises(ValidationError):
            EditorialExecutionAuthorization.model_validate(
                authorization("P1008-TEST", model="gpt-5.6-terra")
            )
        with self.assertRaises(ValidationError):
            EditorialExecutionAuthorization.model_validate(
                authorization("P1008-TEST", fallbackAllowed=True)
            )

    def test_unvalidated_skill_output_cannot_enter_editorial_payload(self):
        with self.assertRaises(TypeError):
            template_governance.build_editorial_payload(
                run_id="P1008-TEST",
                input_research_pack_sha256="A" * 64,
                validated_research_pack={"runId": "P1008-TEST"},
                structured_draft={
                    "runId": "P1008-TEST", "analysisPacketSha256": "A" * 64
                },
                chart_conclusions=[],
                unvalidated_skill_output={"claim": "unsupported"},
            )

    def test_missing_authorization_and_provider_failure_fail_closed(self):
        with scratch("editorial-auth-") as root:
            pipeline = fixture_pipeline(root)
            output = root / "output"
            analysis = pipeline.build_analysis(output_base=output)
            pipeline.editorial_required = True
            pipeline.editorial_client = FakeEditorialClient()
            with self.assertRaisesRegex(PhaseB1PipelineError, "Owner authorization"):
                pipeline.build_report(run_id=analysis["run_id"], output_base=output)
        with scratch("editorial-provider-fail-") as root:
            with self.assertRaisesRegex(PhaseB1PipelineError, "provider execution"):
                self._run_editorial(root, FakeEditorialClient(fail=True))

    def test_router_fails_closed_on_authorization_network_or_model(self):
        valid = dict(
            task_type="WAR_REPORT_EDITORIAL_SYNTHESIS",
            owner_authorized=True,
            live_enabled=True,
            network_enabled=True,
            model_id=PHASE3B_LIVE_MODEL_ID,
        )
        self.assertEqual(PluginRouter.route_editorial(**valid)["client"], "LiveAgentsSdkClient")
        for key, value in (
            ("owner_authorized", False),
            ("live_enabled", False),
            ("network_enabled", False),
            ("model_id", "gpt-5.6-terra"),
        ):
            broken = dict(valid)
            broken[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                PluginRouter.route_editorial(**broken)

    def test_runtime_reuses_existing_client_and_missing_key_fails_closed(self):
        config = RuntimeConfig.phase3b_shadow(live=True)
        manager = RuntimeManager(PACKAGE_ROOT, config=config)
        auth = authorization("P1008-TEST")
        with mock.patch.object(
            RuntimeConfig, "require_live_credentials", return_value=PHASE3B_LIVE_MODEL_ID
        ):
            client = manager.resolve_editorial_client(auth)
        self.assertIsInstance(client, LiveAgentsSdkClient)
        with mock.patch.object(RuntimeConfig, "api_key_available", return_value=False):
            with self.assertRaises(RuntimeConfigurationError):
                config.require_live_credentials()

    def test_phaseb1_routes_editorial_through_existing_runtime_manager(self):
        with scratch("editorial-runtime-route-") as root:
            pipeline = fixture_pipeline(root)
            output = root / "output"
            analysis = pipeline.build_analysis(output_base=output)
            pipeline.editorial_required = True
            pipeline.editorial_authorization = authorization(analysis["run_id"])
            pipeline.editorial_runtime_config = RuntimeConfig.phase3b_shadow(live=True)
            fake = FakeEditorialClient()
            with mock.patch.object(
                RuntimeManager, "resolve_editorial_client", return_value=fake
            ) as resolver:
                result = pipeline.build_report(
                    run_id=analysis["run_id"], output_base=output
                )
            resolver.assert_called_once()
            self.assertEqual(fake.calls, 1)
            self.assertEqual(
                result["editorial_result_envelope"].task_id,
                "WAR_REPORT_EDITORIAL_SYNTHESIS",
            )

    def test_default_run_reports_callable_capability_without_claiming_execution(self):
        with scratch("editorial-default-") as root:
            pipeline = fixture_pipeline(root)
            output = root / "output"
            analysis = pipeline.build_analysis(output_base=output)
            result = pipeline.build_report(run_id=analysis["run_id"], output_base=output)
            skills = json.loads(
                (Path(result["run_root"]) / "skill_execution_summary.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(skills["skillCapabilityMap"]["OPENAI_EDITORIAL"], "CALLABLE_RUNTIME")
            self.assertEqual(skills["skillCapabilityMap"]["ANYSEARCH"], "CALLABLE_RUNTIME")
            self.assertFalse(skills["openaiEditorialExecuted"])
            self.assertEqual(skills["openaiModel"], "NOT_EXECUTED")
            self.assertIn("ANYSEARCH", skills["callableRuntimeNotExecuted"])
            self.assertEqual(skills["skillCapabilityMap"]["DATA_ANALYTICS"], "SKILL_GUIDED_ONLY")
            self.assertEqual(skills["skillCapabilityMap"]["INVESTMENT_BANKING"], "UNAVAILABLE")

    def test_identical_editorial_candidate_preserves_existing_rendered_output(self):
        with scratch("editorial-render-baseline-") as baseline_root:
            baseline_pipeline = fixture_pipeline(baseline_root)
            baseline_out = baseline_root / "output"
            baseline_analysis = baseline_pipeline.build_analysis(output_base=baseline_out)
            baseline = baseline_pipeline.build_report(
                run_id=baseline_analysis["run_id"], output_base=baseline_out
            )
        with scratch("editorial-render-test-") as editorial_root:
            editorial, _ = self._run_editorial(editorial_root)
        self.assertEqual(baseline["report"], editorial["report"])
        self.assertEqual(baseline["report_html_sha256"], editorial["report_html_sha256"])
        baseline_root = Path(baseline["run_root"])
        editorial_root = Path(editorial["run_root"])
        self.assertEqual(
            (baseline_root / "chart_data.json").read_bytes(),
            (editorial_root / "chart_data.json").read_bytes(),
        )
        self.assertTrue((baseline_root / "report_candidate.pdf").is_file())
        self.assertTrue((editorial_root / "report_candidate.pdf").is_file())
        report_text = "\n".join(item.body_zh for item in editorial["report"].sections)
        self.assertNotRegex(report_text, r"\b(?:BUY|SELL|ADD|TRIM)\b")

    def test_only_existing_live_openai_client_class_is_used(self):
        source_root = (
            PACKAGE_ROOT / "modules" / "p1008_research_plugin" / "src"
            / "p1008_research_plugin"
        )
        declarations = []
        for path in source_root.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            if "class LiveAgentsSdkClient" in text:
                declarations.append(path)
        self.assertEqual(
            declarations,
            [source_root / "plugin_module" / "agent_runner.py"],
        )


if __name__ == "__main__":
    unittest.main()
