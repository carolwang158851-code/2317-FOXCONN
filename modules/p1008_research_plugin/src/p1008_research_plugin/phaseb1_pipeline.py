"""Runtime-only deterministic Phase B1 vertical-slice orchestration."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .adapters.authority_adapter import AuthorityAdapter
from .analysis import AnalysisBuilder, AnalysisPacket, AnalysisValidator
from .contract_loader import ContractLoader
from .governance import GovernanceBoundary, GovernanceError
from .phaseb1_common import (
    PhaseB1BoundaryError,
    atomic_write,
    atomic_write_json,
    canonical_json_bytes,
    protected_state_hashes,
    sha256_bytes,
    sha256_file,
)
from .plugin_module.packet_gateway import PacketGateway, PacketValidationError
from .plugin_module.router import PluginRouter
from .reporting import (
    EditorialExecutionAuthorization,
    EditorialGovernance,
    ModelProvenance,
    EditorialResultEnvelope,
    ReportBuilder,
    ReportCandidate,
    ReportValidator,
    ScriptBuilder,
    ShortsDurationValidator,
)
from .runtime.runtime_config import RuntimeConfig
from .runtime.runtime_manager import RuntimeManager
from .reporting.chart_data_builder import ChartDataBuilder
from .reporting.report_renderer_markdown import MarkdownRenderer
from .reporting.report_renderer_formal import FormalPreviewRenderer
from .reporting import template_governance
from .quarterly_earnings import QuarterlyEarningsPacket


class PhaseB1PipelineError(RuntimeError):
    """The deterministic Phase B1 pipeline failed closed."""


class PhaseB1Pipeline:
    SUPPORTED_EVENT = "MONTHLY_REVENUE"
    SUPPORTED_EVENTS = frozenset({"MONTHLY_REVENUE", "QUARTERLY_EARNINGS"})

    def __init__(
        self,
        package_root: Path,
        fixture_path: Path | None = None,
        *,
        governed_evidence_root: Path | None = None,
        editorial_required: bool = False,
        editorial_authorization: dict[str, Any] | None = None,
        editorial_client: Any | None = None,
        editorial_runtime_config: RuntimeConfig | None = None,
        output_capability: str = "REPORT_PRODUCTION",
    ) -> None:
        self.package_root = package_root.resolve()
        self.governed_evidence_root = governed_evidence_root.resolve() if governed_evidence_root else None
        self.fixture_path = fixture_path or (
            self.package_root
            / "modules"
            / "p1008_research_plugin"
            / "tests"
            / "fixtures"
            / "phaseb1"
            / "monthly_revenue_fixture.json"
        )
        self.loader = ContractLoader(self.package_root)
        self.filesystem_governance = GovernanceBoundary(self.loader)
        self.output_capability = output_capability
        self.editorial_required = editorial_required
        self.editorial_authorization = editorial_authorization
        self.editorial_client = editorial_client
        self.editorial_runtime_config = editorial_runtime_config

    def _atomic_write(
        self, path: Path, data: bytes, *, overwrite: bool = False
    ) -> None:
        atomic_write(
            path,
            data,
            overwrite=overwrite,
            capability=self.output_capability,
        )

    def _atomic_write_json(
        self, path: Path, value: Any, *, overwrite: bool = False
    ) -> str:
        return atomic_write_json(
            path,
            value,
            overwrite=overwrite,
            capability=self.output_capability,
        )

    def load_inputs(
        self,
        event_type: str = "MONTHLY_REVENUE",
        trigger_lineage: dict[str, Any] | None = None,
    ) -> tuple[Any, Any]:
        if event_type == "QUARTERLY_EARNINGS":
            if trigger_lineage is None:
                raise PhaseB1PipelineError("QUARTERLY_EARNINGS requires trigger lineage")
            packet = QuarterlyEarningsPacket(
                self.package_root,
                trigger_lineage,
                governed_evidence_root=self.governed_evidence_root,
            )
            return packet, packet.validated_evidence()
        if event_type != "MONTHLY_REVENUE":
            raise PhaseB1PipelineError(f"Unsupported Phase B1 event: {event_type}")
        fixture = json.loads(self.fixture_path.read_text(encoding="utf-8"))
        if fixture.get("eventType") != self.SUPPORTED_EVENT:
            raise PhaseB1PipelineError("Phase B1 supports MONTHLY_REVENUE only")
        gateway = PacketGateway()
        try:
            packets = gateway.parse(fixture["packets"])
            plan = PluginRouter().route(
                self.SUPPORTED_EVENT, gateway.aggregate_signals(packets)
            )
            validated = gateway.validate(plan, packets, fixture["asOfDate"])
            gateway.validate_live_evidence(plan, validated)
        except (KeyError, PacketValidationError) as exc:
            raise PhaseB1PipelineError(f"Evidence validation failed closed: {exc}") from exc

        official_values: dict[str, str] = {}
        allowed_tiers = {
            "OFFICIAL_COMPANY_RELEASE",
            "OFFICIAL_COMPANY_INVESTOR_RELATIONS",
        }
        for item in validated.evidence:
            if any(locator.source_tier not in allowed_tiers for locator in item.source_locators):
                raise PhaseB1PipelineError(
                    f"Invalid Phase B1 source tier for {item.evidence_id}"
                )
            for field, value in item.field_values.items():
                previous = official_values.setdefault(field, value)
                if previous != value:
                    raise PhaseB1PipelineError(
                        f"Conflicting official evidence for {field}"
                    )
        return fixture, validated

    def deterministic_run_id(self, fixture: Any) -> str:
        if isinstance(fixture, QuarterlyEarningsPacket):
            identity = {
                **fixture.deterministic_identity(),
                "authorityManifestSha256": sha256_file(
                    self.package_root / "data" / "CSV_AUTHORITY_MANIFEST.json"
                ),
            }
            suffix = sha256_bytes(canonical_json_bytes(identity))[:12]
            generated = self._utc(fixture.generated_at_utc)
            return f"P1008-B1-QUARTERLY-EARNINGS-{generated:%Y%m%d}-DET-{suffix}"
        identity = {
            "eventType": fixture["eventType"],
            "asOfDate": fixture["asOfDate"],
            "generatedAtUtc": fixture["generatedAtUtc"],
            "inputPacketsSha256": sha256_bytes(canonical_json_bytes(fixture["packets"])),
            "authorityManifestSha256": sha256_file(
                self.package_root / "data" / "CSV_AUTHORITY_MANIFEST.json"
            ),
        }
        suffix = sha256_bytes(canonical_json_bytes(identity))[:12]
        generated = self._utc(fixture["generatedAtUtc"])
        return f"P1008-B1-MONTHLY-REVENUE-{generated:%Y%m%d}-DET-{suffix}"

    def build_analysis(
        self, *, output_base: Path | None = None,
        trigger_lineage: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        event_type = str((trigger_lineage or {}).get("eventType") or "MONTHLY_REVENUE")
        if event_type not in self.SUPPORTED_EVENTS:
            raise PhaseB1PipelineError(f"Unsupported Phase B1 event: {event_type}")
        fixture, evidence = self.load_inputs(event_type, trigger_lineage)
        run_id = self.deterministic_run_id(fixture)
        run_root = self._run_root(run_id, output_base)
        if run_root.exists():
            if event_type == "QUARTERLY_EARNINGS":
                return self._validate_quarterly_checkpoint(run_root, fixture, evidence, trigger_lineage)
            raise PhaseB1BoundaryError(f"Run ID already exists: {run_id}")
        generated_at = fixture.generated_at_utc if isinstance(fixture, QuarterlyEarningsPacket) else fixture["generatedAtUtc"]
        generated = self._utc(generated_at)
        before = protected_state_hashes(self.package_root)
        run_root.mkdir(parents=True, exist_ok=False)
        self._atomic_write_json(run_root / "protected_state_hashes_before.json", before)

        authority = AuthorityAdapter(self.package_root, self.loader)
        analysis = AnalysisBuilder(self.package_root, authority).build(
            run_id=run_id,
            generated_at_utc=generated,
            validated_evidence=evidence,
            event_type=event_type,
            quarterly_packet=(fixture if isinstance(fixture, QuarterlyEarningsPacket) else None),
        )
        analysis = AnalysisValidator().validate(analysis, evidence)
        gate = AnalysisValidator.result(analysis, checked_at=generated)
        evidence_manifest = fixture.evidence_manifest() if isinstance(fixture, QuarterlyEarningsPacket) else self._evidence_manifest(evidence)

        analysis_sha = self._atomic_write_json(
            run_root / "analysis_packet.json",
            analysis.model_dump(mode="json", by_alias=True),
        )
        self._atomic_write_json(
            run_root / "analysis_validation.json",
            gate.model_dump(mode="json", by_alias=True),
        )
        evidence_sha = self._atomic_write_json(
            run_root / "evidence_manifest.json", evidence_manifest
        )
        after = protected_state_hashes(self.package_root)
        self._atomic_write_json(run_root / "protected_state_hashes_after.json", after)
        if before != after:
            raise PhaseB1PipelineError("Protected state changed during analysis build")
        manifest = {
            "runId": run_id,
            "eventType": event_type,
            "state": "ANALYSIS_CANDIDATE_READY",
            "generatedAtUtc": generated_at,
            "deterministicMode": True,
            "artifacts": {
                "analysis_packet.json": analysis_sha,
                "analysis_validation.json": sha256_file(
                    run_root / "analysis_validation.json"
                ),
                "evidence_manifest.json": evidence_sha,
                "protected_state_hashes_before.json": sha256_file(
                    run_root / "protected_state_hashes_before.json"
                ),
                "protected_state_hashes_after.json": sha256_file(
                    run_root / "protected_state_hashes_after.json"
                ),
            },
            "externalCalls": self._zero_calls(),
            "templateGovernance": self._template_governance_metadata(
                run_id=run_id, event_type=event_type, fixture=fixture,
                authority_cutoff=self._authority_cutoff(analysis),
            ),
            "governedEvidence": (
                fixture.evidence_context if isinstance(fixture, QuarterlyEarningsPacket) else None
            ),
            "actionable": False,
        }
        if trigger_lineage is not None:
            manifest["triggerLineage"] = dict(trigger_lineage)
        self._atomic_write_json(run_root / "run_manifest.json", manifest)
        return {
            "run_id": run_id,
            "run_root": str(run_root),
            "analysis": analysis,
            "evidence": evidence,
            "analysis_sha256": analysis_sha,
        }

    def _validate_quarterly_checkpoint(self, run_root, fixture, evidence, trigger_lineage):
        """Read-only reconstruction of a deterministic checkpoint; never trust its label."""
        manifest = json.loads((run_root / "run_manifest.json").read_text(encoding="utf-8"))
        run_id = self.deterministic_run_id(fixture)
        states = {"ANALYSIS_CANDIDATE_READY", "REPORT_CANDIDATE_READY", "OWNER_REVIEW_REQUIRED"}
        if not (
            manifest.get("runId") == run_id
            and manifest.get("eventType") == "QUARTERLY_EARNINGS"
            and manifest.get("state") in states
            and manifest.get("triggerLineage") == trigger_lineage
            and manifest.get("governedEvidence") == fixture.evidence_context
            and manifest.get("actionable") is False
            and manifest.get("deterministicMode") is True
            and manifest.get("generatedAtUtc") == fixture.generated_at_utc
            and manifest.get("externalCalls") == self._zero_calls()
        ):
            raise PhaseB1PipelineError("QUARTERLY_CHECKPOINT_IDENTITY_MISMATCH")
        analysis = AnalysisBuilder(self.package_root, AuthorityAdapter(self.package_root, self.loader)).build(
            run_id=run_id, generated_at_utc=self._utc(fixture.generated_at_utc),
            validated_evidence=evidence, event_type="QUARTERLY_EARNINGS", quarterly_packet=fixture,
        )
        analysis = AnalysisValidator().validate(analysis, evidence)
        expected = {
            "analysis_packet.json": analysis.model_dump(mode="json", by_alias=True),
            "analysis_validation.json": AnalysisValidator.result(analysis, checked_at=self._utc(fixture.generated_at_utc)).model_dump(mode="json", by_alias=True),
            "evidence_manifest.json": fixture.evidence_manifest(),
            "protected_state_hashes_before.json": protected_state_hashes(self.package_root),
            "protected_state_hashes_after.json": protected_state_hashes(self.package_root),
        }
        artifacts = manifest.get("artifacts")
        if not isinstance(artifacts, dict) or not set(expected).issubset(artifacts):
            raise PhaseB1PipelineError("QUARTERLY_CHECKPOINT_ARTIFACTS_MISSING")
        for name, value in expected.items():
            if (run_root / name).read_bytes() != canonical_json_bytes(value):
                raise PhaseB1PipelineError(f"QUARTERLY_CHECKPOINT_CONTENT_MISMATCH: {name}")
        for name, digest in artifacts.items():
            path = (run_root / name).resolve()
            if not path.is_relative_to(run_root.resolve()) or not path.is_file() or sha256_file(path) != digest:
                raise PhaseB1PipelineError(f"QUARTERLY_CHECKPOINT_HASH_MISMATCH: {name}")
        actual = {p.relative_to(run_root).as_posix() for p in run_root.rglob("*") if p.is_file()}
        if actual != set(artifacts) | {"run_manifest.json"}:
            raise PhaseB1PipelineError("QUARTERLY_CHECKPOINT_UNRECORDED_ARTIFACT")
        if manifest.get("templateGovernance") != self._template_governance_metadata(
            run_id=run_id, event_type="QUARTERLY_EARNINGS", fixture=fixture,
            authority_cutoff=self._authority_cutoff(analysis),
        ):
            raise PhaseB1PipelineError("QUARTERLY_CHECKPOINT_TEMPLATE_MISMATCH")
        if manifest["state"] != "ANALYSIS_CANDIDATE_READY":
            if (manifest.get("reportRuntime") != "ENTERPRISE_VALUE_WAR_REPORT_V1"
                    or manifest.get("reportChapterCount") != 11
                    or Path(str(manifest.get("reportCandidateOutputPath") or "")).resolve()
                    != (run_root / "enterprise_value_war_report/war_report_candidate.html").resolve()):
                raise PhaseB1PipelineError("QUARTERLY_CHECKPOINT_REPORT_IDENTITY_MISMATCH")
            from .reporting.war_report_production_runtime import compile_existing_phaseb1_result
            compile_existing_phaseb1_result(
                package_root=self.package_root, analysis=analysis, evidence=evidence,
                trigger_context=trigger_lineage, output_root=run_root / "enterprise_value_war_report",
                validate_existing=True,
            )
            if manifest["state"] == "OWNER_REVIEW_REQUIRED":
                completed = manifest.get("reportCompletion") or {}
                if not (completed.get("reportKey") == trigger_lineage["reportKey"]
                        and completed.get("revision") == trigger_lineage["revision"]
                        and completed.get("editorialValidationSha256") == artifacts.get("enterprise_value_war_report/editorial_validation.json")
                        and all(completed.get(flag) is False for flag in ("actionable", "publishAuthorized", "publication", "publicationComplete"))):
                    raise PhaseB1PipelineError("QUARTERLY_CHECKPOINT_COMPLETION_MISMATCH")
        elif set(artifacts) != set(expected):
            raise PhaseB1PipelineError("QUARTERLY_CHECKPOINT_STATE_MISMATCH")
        return {"status": "EXISTING_VALIDATED_RUN", "run_id": run_id, "run_root": str(run_root),
                "analysis": analysis, "evidence": evidence,
                "analysis_sha256": sha256_file(run_root / "analysis_packet.json")}

    def build_report(
        self, *, run_id: str, output_base: Path | None = None,
        trigger_lineage: dict[str, Any] | None = None,
        report_runtime: str = "PHASE_B1_LEGACY",
    ) -> dict[str, Any]:
        event_type = str((trigger_lineage or {}).get("eventType") or "MONTHLY_REVENUE")
        if event_type not in self.SUPPORTED_EVENTS:
            raise PhaseB1PipelineError(f"Unsupported Phase B1 event: {event_type}")
        fixture, evidence = self.load_inputs(event_type, trigger_lineage)
        expected_run_id = self.deterministic_run_id(fixture)
        if run_id != expected_run_id:
            raise PhaseB1PipelineError("Run ID does not match governed deterministic inputs")
        run_root = self._run_root(run_id, output_base)
        if event_type == "QUARTERLY_EARNINGS":
            self._validate_quarterly_checkpoint(run_root, fixture, evidence, trigger_lineage)
        analysis_path = run_root / "analysis_packet.json"
        gate_path = run_root / "analysis_validation.json"
        evidence_manifest_path = run_root / "evidence_manifest.json"
        run_manifest_path = run_root / "run_manifest.json"
        if not all(
            path.is_file()
            for path in (
                analysis_path,
                gate_path,
                evidence_manifest_path,
                run_manifest_path,
            )
        ):
            raise PhaseB1PipelineError("Validated Analysis candidate is required before report build")
        gate = json.loads(gate_path.read_text(encoding="utf-8"))
        if gate.get("status") != "PASS" or gate.get("analysisPacketSha256") != sha256_file(analysis_path):
            raise PhaseB1PipelineError("Analysis validation gate is missing or stale")
        stored_run_manifest = json.loads(run_manifest_path.read_text(encoding="utf-8"))
        if trigger_lineage is not None and stored_run_manifest.get("triggerLineage") != trigger_lineage:
            raise PhaseB1PipelineError("Analysis trigger lineage is missing or stale")
        expected_analysis_artifacts = {
            "analysis_packet.json": sha256_file(analysis_path),
            "analysis_validation.json": sha256_file(gate_path),
            "evidence_manifest.json": sha256_file(evidence_manifest_path),
            "protected_state_hashes_before.json": sha256_file(
                run_root / "protected_state_hashes_before.json"
            ),
            "protected_state_hashes_after.json": sha256_file(
                run_root / "protected_state_hashes_after.json"
            ),
        }
        if (
            (event_type != "QUARTERLY_EARNINGS" and stored_run_manifest.get("state") != "ANALYSIS_CANDIDATE_READY")
            or any(stored_run_manifest.get("artifacts", {}).get(k) != v for k, v in expected_analysis_artifacts.items())
            or (event_type != "QUARTERLY_EARNINGS" and stored_run_manifest.get("artifacts") != expected_analysis_artifacts)
        ):
            raise PhaseB1PipelineError("Analysis run manifest is missing or stale")
        stored_evidence_manifest = json.loads(
            evidence_manifest_path.read_text(encoding="utf-8")
        )
        expected_evidence_manifest = fixture.evidence_manifest() if isinstance(fixture, QuarterlyEarningsPacket) else self._evidence_manifest(evidence)
        if stored_evidence_manifest != expected_evidence_manifest:
            raise PhaseB1PipelineError("Validated Evidence manifest drifted")
        analysis = AnalysisPacket.model_validate_json(analysis_path.read_text(encoding="utf-8"))
        AnalysisValidator().validate(analysis, evidence)
        if report_runtime == "ENTERPRISE_VALUE_WAR_REPORT_V1":
            if event_type != "QUARTERLY_EARNINGS":
                raise PhaseB1PipelineError(
                    "Enterprise Value report runtime currently requires QUARTERLY_EARNINGS"
                )
            return self._build_enterprise_value_report(
                run_id=run_id,
                run_root=run_root,
                evidence=evidence,
                analysis=analysis,
                trigger_lineage=trigger_lineage,
                stored_run_manifest=stored_run_manifest,
            )
        if report_runtime != "PHASE_B1_LEGACY":
            raise PhaseB1PipelineError(f"Unsupported report runtime: {report_runtime}")
        before = protected_state_hashes(self.package_root)
        generated_at = fixture.generated_at_utc if isinstance(fixture, QuarterlyEarningsPacket) else fixture["generatedAtUtc"]
        generated = self._utc(generated_at)
        report = ReportBuilder().build(
            analysis=analysis,
            evidence=evidence,
            generated_at_utc=generated,
        )
        report = ReportValidator().validate(report, analysis)
        charts = ChartDataBuilder().build(analysis)
        editorial_envelope = None
        if self.editorial_required:
            editorial_envelope = self._execute_editorial(
                run_id=run_id,
                analysis=analysis,
                analysis_sha256=sha256_file(analysis_path),
                structured_draft=report,
                charts=charts,
            )
            report = ReportValidator().validate(
                editorial_envelope.report_candidate, analysis
            )
        formula_cards = []
        if analysis.event_type == "QUARTERLY_EARNINGS" and analysis.quarterly_earnings is not None:
            formula_cards = analysis.quarterly_earnings.enterprise_value_analytics["formulaCards"]
        markdown = MarkdownRenderer().render(report, charts, formula_cards).replace("\r\n", "\n")
        scripts = ScriptBuilder()
        longform = scripts.longform(report).replace("\r\n", "\n")
        shorts = scripts.shorts_75s(report).replace("\r\n", "\n")
        duration = ShortsDurationValidator.validate(shorts)
        editorial = ReportValidator.editorial_result(
            report, analysis, longform, shorts, duration
        )
        if editorial.status != "PASS":
            raise PhaseB1PipelineError(
                "Editorial validation failed closed: " + "; ".join(editorial.errors)
            )
        formal = FormalPreviewRenderer()
        html_preview = formal.html(report, charts, formula_cards)
        pdf_preview = formal.pdf(report, charts, formula_cards)

        report_sha = self._atomic_write_json(
            run_root / "report_candidate.json",
            report.model_dump(mode="json", by_alias=True),
        )
        self._atomic_write(run_root / "report_candidate.md", markdown.encode("utf-8"))
        self._atomic_write(run_root / "report_candidate.html", html_preview)
        self._atomic_write(run_root / "report_candidate.pdf", pdf_preview)
        self._atomic_write_json(
            run_root / "chart_data.json",
            [item.model_dump(mode="json", by_alias=True) for item in charts],
        )
        if analysis.event_type == "QUARTERLY_EARNINGS":
            quarterly = analysis.quarterly_earnings
            if quarterly is None:
                raise PhaseB1PipelineError("quarterly analysis disappeared before artifact materialization")
            analytics = quarterly.enterprise_value_analytics
            self._atomic_write_json(
                run_root / "validated_research_pack.json",
                {
                    "recordType": "P1008_VALIDATED_RESEARCH_PACK",
                    "templateVersion": template_governance.TEMPLATE_VERSION,
                    "analysisPacketSha256": sha256_file(analysis_path),
                    "sourceEvidenceIds": analysis.source_evidence_ids,
                    "enterpriseValueAnalytics": analytics,
                    "quarterlyHistory": quarterly.quarterly_history,
                    "valuationScenarios": quarterly.valuation_scenarios,
                    "limitations": quarterly.limitations,
                    "actionable": False,
                },
            )
            self._atomic_write_json(run_root / "formula_cards.json", analytics["formulaCards"])
            self._atomic_write_json(run_root / "strategy_scorecard.json", analytics["strategyScorecard"])
        self._atomic_write(run_root / "longform_script_candidate.md", longform.encode("utf-8"))
        self._atomic_write(run_root / "shorts_75s_candidate.md", shorts.encode("utf-8"))
        self._atomic_write_json(
            run_root / "shorts_duration_validation.json",
            duration.model_dump(mode="json", by_alias=True),
        )
        self._atomic_write_json(
            run_root / "editorial_validation.json",
            editorial.model_dump(mode="json", by_alias=True),
        )
        if editorial_envelope is not None:
            self._atomic_write_json(
                run_root / "editorial_result_envelope.json",
                editorial_envelope.model_dump(mode="json", by_alias=True),
            )
        owner_review = {
            "runId": run_id,
            "status": "OWNER_REVIEW_REQUIRED",
            "ownerReviewRequired": True,
            "templateVersion": template_governance.TEMPLATE_VERSION,
            "reportCandidateSha256": report_sha,
            "publishAuthorized": False,
            "publication": False,
            "liveSynthesisAuthorized": bool(
                editorial_envelope
                and editorial_envelope.execution_status == "EXECUTED_LIVE"
            ),
            "openaiEditorialExecuted": bool(editorial_envelope),
            "phaseB2Started": False,
            "actionable": False,
        }
        self._atomic_write_json(run_root / "owner_review.json", owner_review)
        governance_metadata = self._template_governance_metadata(
            run_id=run_id,
            event_type=event_type,
            fixture=fixture,
            authority_cutoff=self._authority_cutoff(analysis),
        )
        skill_execution_summary = self._skill_execution_summary(
            fixture=fixture,
            governance_metadata=governance_metadata,
            analysis_sha256=sha256_file(analysis_path),
            report_sha256=report_sha,
            editorial_envelope=editorial_envelope,
            run_root=run_root,
        )
        self._atomic_write_json(
            run_root / "skill_execution_summary.json", skill_execution_summary
        )
        after = protected_state_hashes(self.package_root)
        self._atomic_write_json(
            run_root / "protected_state_hashes_after.json", after, overwrite=True
        )
        if before != after:
            raise PhaseB1PipelineError("Protected state changed during report build")
        artifact_names = [
            "analysis_packet.json",
            "analysis_validation.json",
            "evidence_manifest.json",
            "report_candidate.json",
            "report_candidate.md",
            "report_candidate.html",
            "report_candidate.pdf",
            "chart_data.json",
            "longform_script_candidate.md",
            "shorts_75s_candidate.md",
            "shorts_duration_validation.json",
            "editorial_validation.json",
            "owner_review.json",
            "skill_execution_summary.json",
            "protected_state_hashes_before.json",
            "protected_state_hashes_after.json",
        ]
        if editorial_envelope is not None:
            artifact_names.append("editorial_result_envelope.json")
        if analysis.event_type == "QUARTERLY_EARNINGS":
            artifact_names.extend([
                "validated_research_pack.json",
                "formula_cards.json",
                "strategy_scorecard.json",
            ])
        external_calls = self._zero_calls()
        if (
            editorial_envelope is not None
            and editorial_envelope.execution_status == "EXECUTED_LIVE"
        ):
            external_calls["openaiApi"] = 1
        manifest = {
            "runId": run_id,
            "eventType": event_type,
            "state": "REPORT_CANDIDATE_READY",
            "generatedAtUtc": generated_at,
            "deterministicMode": True,
            "artifacts": {
                name: sha256_file(run_root / name) for name in artifact_names
            },
            "externalCalls": external_calls,
            "templateGovernance": governance_metadata,
            "governedEvidence": (
                fixture.evidence_context if isinstance(fixture, QuarterlyEarningsPacket) else None
            ),
            "actionable": False,
        }
        if trigger_lineage is not None:
            manifest["triggerLineage"] = dict(trigger_lineage)
        self._atomic_write_json(run_root / "run_manifest.json", manifest, overwrite=True)
        return {
            "run_id": run_id,
            "run_root": str(run_root),
            "analysis": analysis,
            "report": report,
            "analysis_sha256": sha256_file(analysis_path),
            "report_json_sha256": report_sha,
            "report_markdown_sha256": sha256_file(run_root / "report_candidate.md"),
            "report_html_sha256": sha256_file(run_root / "report_candidate.html"),
            "report_pdf_sha256": sha256_file(run_root / "report_candidate.pdf"),
            "shorts_sha256": sha256_file(run_root / "shorts_75s_candidate.md"),
            "protected_state_unchanged": before == after,
            "editorial_result_envelope": editorial_envelope,
        }

    def _build_enterprise_value_report(
        self,
        *,
        run_id: str,
        run_root: Path,
        evidence: Any,
        analysis: AnalysisPacket,
        trigger_lineage: dict[str, Any] | None,
        stored_run_manifest: dict[str, Any],
    ) -> dict[str, Any]:
        """Materialize the governed 11-chapter candidate for Launcher use."""
        if trigger_lineage is None:
            raise PhaseB1PipelineError("Enterprise Value report requires trigger lineage")
        from .reporting.war_report_production_runtime import (
            compile_existing_phaseb1_result,
        )

        before = protected_state_hashes(self.package_root)
        output_root = run_root / "enterprise_value_war_report"
        replay = stored_run_manifest.get("state") in {"REPORT_CANDIDATE_READY", "OWNER_REVIEW_REQUIRED"}
        result = compile_existing_phaseb1_result(
            package_root=self.package_root,
            analysis=analysis,
            evidence=evidence,
            trigger_context=trigger_lineage,
            output_root=output_root,
            output_capability=self.output_capability,
            validate_existing=replay,
        )
        if result.get("state") != "REPORT_CANDIDATE_READY":
            raise PhaseB1PipelineError("Enterprise Value report runtime did not produce a candidate")
        after = protected_state_hashes(self.package_root)
        recorded_after = json.loads(
            (run_root / "protected_state_hashes_after.json").read_text(encoding="utf-8")
        )
        if before != after or recorded_after != after:
            raise PhaseB1PipelineError(
                "Protected state changed during Enterprise Value report build"
            )

        artifacts = {
            name: sha256_file(run_root / name)
            for name in (
                "analysis_packet.json",
                "analysis_validation.json",
                "evidence_manifest.json",
                "protected_state_hashes_before.json",
                "protected_state_hashes_after.json",
            )
        }
        for path in sorted(output_root.iterdir()):
            if path.is_file():
                artifacts[str(path.relative_to(run_root)).replace("\\", "/")] = sha256_file(path)

        manifest = {
            **stored_run_manifest,
            "state": "REPORT_CANDIDATE_READY",
            "reportRuntime": "ENTERPRISE_VALUE_WAR_REPORT_V1",
            "reportChapterCount": 11,
            "reportCandidateOutputPath": result["output_html"],
            "artifacts": artifacts,
            "externalCalls": self._zero_calls(),
            "actionable": False,
        }
        if not replay:
            self._atomic_write_json(run_root / "run_manifest.json", manifest, overwrite=True)
        receipt_path = output_root / "war_report_runtime_receipt.json"
        html_path = Path(result["output_html"])
        return {
            "run_id": run_id,
            "run_root": str(run_root),
            "candidate_output_root": str(output_root),
            "analysis": analysis,
            "report": result["report"],
            "analysis_sha256": sha256_file(run_root / "analysis_packet.json"),
            "report_json_sha256": sha256_file(receipt_path),
            "report_html_sha256": sha256_file(html_path),
            "protected_state_unchanged": before == after,
            "report_runtime": "ENTERPRISE_VALUE_WAR_REPORT_V1",
        }

    def _execute_editorial(
        self, *, run_id: str, analysis: AnalysisPacket, analysis_sha256: str,
        structured_draft: ReportCandidate, charts: list[Any],
    ) -> EditorialResultEnvelope:
        """Dispatch one authorized editorial task and validate its exact receipt."""
        if self.editorial_authorization is None:
            raise PhaseB1PipelineError("Editorial execution requires explicit Owner authorization")
        try:
            authorization = EditorialExecutionAuthorization.model_validate(
                self.editorial_authorization
            )
        except Exception as exc:
            raise PhaseB1PipelineError("Editorial Owner authorization is invalid") from exc
        if (
            authorization.run_id != run_id
            or authorization.template_id != template_governance.TEMPLATE_ID
            or authorization.template_version != template_governance.TEMPLATE_VERSION
        ):
            raise PhaseB1PipelineError("Editorial Owner authorization scope mismatch")

        client = self.editorial_client
        if client is None:
            if self.editorial_runtime_config is None:
                raise PhaseB1PipelineError("Editorial live runtime is not configured")
            try:
                client = RuntimeManager(
                    self.package_root, config=self.editorial_runtime_config
                ).resolve_editorial_client(
                    authorization.model_dump(mode="json", by_alias=True)
                )
            except Exception as exc:
                raise PhaseB1PipelineError("Editorial live runtime failed closed") from exc
        if getattr(client, "model_id", authorization.model) != authorization.model:
            raise PhaseB1PipelineError("Editorial client model mismatch")

        payload = template_governance.build_editorial_payload(
            run_id=run_id,
            input_research_pack_sha256=analysis_sha256,
            validated_research_pack=analysis.model_dump(mode="json", by_alias=True),
            structured_draft=structured_draft.model_dump(mode="json", by_alias=True),
            chart_conclusions=[
                {
                    "chartId": item.chart_id,
                    "decisionQuestion": item.decision_question,
                    "sourceEvidenceIds": item.source_evidence_ids,
                    "commentaryZh": item.commentary_zh,
                    "observationZh": item.observation_zh,
                    "interpretationZh": item.interpretation_zh,
                    "p1008ImplicationZh": item.p1008_implication_zh,
                }
                for item in charts
            ],
        )
        started = datetime.now(timezone.utc)
        try:
            candidate, usage = client.synthesize_editorial(
                payload=payload,
                instructions=template_governance.editorial_instructions(),
            )
        except Exception as exc:
            raise PhaseB1PipelineError("Editorial provider execution failed closed") from exc
        completed = datetime.now(timezone.utc)
        candidate = ReportCandidate.model_validate(candidate)
        output_sha = sha256_bytes(
            canonical_json_bytes(candidate.model_dump(mode="json", by_alias=True))
        )
        editorial_text = "\n\n".join(
            f"{section.title_zh}\n{section.body_zh}" for section in candidate.sections
        )
        live = getattr(client, "mode", "") == "AGENTS_SDK"
        provider_response_id = getattr(client, "provider_response_id", None)
        try:
            return EditorialResultEnvelope(
                run_id=run_id,
                template_id=template_governance.TEMPLATE_ID,
                template_version=template_governance.TEMPLATE_VERSION,
                input_research_pack_sha256=analysis_sha256,
                editorial_text=editorial_text,
                editorial_output_sha256=output_sha,
                report_candidate=candidate,
                model_provenance=ModelProvenance(
                    model_provenance_id=(
                        f"{run_id}:{template_governance.EDITORIAL_TASK_TYPE}:"
                        f"{output_sha[:12]}"
                    ),
                    model_surface=(
                        "OPENAI_AGENTS_SDK" if live else "DETERMINISTIC_TEST_DOUBLE"
                    ),
                    model_identifier=authorization.model,
                    input_receipt_ids=[analysis_sha256],
                    output_artifact_hash=output_sha,
                    started_at_utc=started,
                    completed_at_utc=completed,
                    status=("EXECUTED_LIVE" if live else "EXECUTED_TEST_DOUBLE"),
                    usage_metadata=(
                        usage.model_dump(mode="json", by_alias=True)
                        if hasattr(usage, "model_dump") else dict(usage or {})
                    ),
                    billing_metadata=None,
                ),
                provider_response_id=provider_response_id,
                governance=EditorialGovernance(),
                execution_status=("EXECUTED_LIVE" if live else "EXECUTED_TEST_DOUBLE"),
                validation_status="PASS",
            )
        except Exception as exc:
            raise PhaseB1PipelineError("Editorial receipt validation failed closed") from exc

    def run_all(self, *, output_base: Path | None = None) -> dict[str, Any]:
        analysis = self.build_analysis(output_base=output_base)
        return self.build_report(run_id=analysis["run_id"], output_base=output_base)

    def _run_root(self, run_id: str, output_base: Path | None) -> Path:
        if any(char not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-" for char in run_id):
            raise PhaseB1BoundaryError("Unsafe Run ID")
        base = output_base or self.package_root / "runtime" / "report_production"
        try:
            authorized_base = self.filesystem_governance.authorize_write(
                self.output_capability, base
            )
            run_root = authorized_base / run_id
            return self.filesystem_governance.authorize_write(
                self.output_capability, run_root
            )
        except GovernanceError as exc:
            raise PhaseB1BoundaryError(f"Phase B1 output denied: {exc}") from exc

    @staticmethod
    def _utc(value: str) -> datetime:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.utcoffset() is None or parsed.utcoffset().total_seconds() != 0:
            raise PhaseB1PipelineError("Fixture timestamp must be UTC")
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _evidence_manifest(evidence: Any) -> dict[str, Any]:
        return {
            "status": "VALIDATED",
            "packetHashes": {
                packet.packet_id: sha256_bytes(
                    canonical_json_bytes(packet.model_dump(mode="json", by_alias=True))
                )
                for packet in evidence.packets
            },
            "evidenceIds": evidence.evidence_ids,
            "sourceLocators": sorted(
                {
                    locator.locator
                    for item in evidence.evidence
                    for locator in item.source_locators
                }
            ),
            "actionable": False,
        }

    @staticmethod
    def _zero_calls() -> dict[str, int]:
        return {
            "openaiApi": 0,
            "hostedWebSearch": 0,
            "deepResearch": 0,
            "canva": 0,
            "gemini": 0,
            "youtube": 0,
        }

    @staticmethod
    def _authority_cutoff(analysis: AnalysisPacket) -> str:
        values = [value for value in analysis.authority_data_cutoffs.values() if value]
        return max(values) if values else "UNDECLARED"

    @staticmethod
    def _template_governance_metadata(*, run_id: str, event_type: str, fixture: Any,
                                      authority_cutoff: str) -> dict[str, Any] | None:
        if event_type != "QUARTERLY_EARNINGS" or not isinstance(fixture, QuarterlyEarningsPacket):
            return None
        common = {
            "run_id": run_id,
            "event": event_type,
            "period": fixture.values["fiscalPeriod"],
            "authority_cutoff": authority_cutoff,
            "required_inputs": [
                "OFFICIAL_IR_RESULTS",
                "GOVERNED_AUTHORITY",
                "GOVERNED_MARKET_DATA",
            ],
            "prohibited_actions": [
                "PUBLISH",
                "TRADE_INSTRUCTION",
                "AUTHORITY_WRITE",
                "UNVALIDATED_FACT",
            ],
        }
        task_specs = [
            (
                "TASK_A_FINANCIAL_TRANSMISSION",
                "How did Q2 revenue growth transmit through gross profit, operating profit, net income and cash?",
                ["EIGHT_QUARTER_INDEX", "MARGIN_DIVERGENCE", "TURNING_POINTS"],
                ["VALIDATED_FINANCIAL_TRANSMISSION"],
            ),
            (
                "TASK_B_CAPITAL_EFFICIENCY",
                "Is current growth creating economic value and can ROIC, incremental ROIC and DuPont quality be verified?",
                ["CAPITAL_INTENSITY", "ROIC_INPUT_GATE", "DUPONT_INPUT_GATE"],
                ["CAPITAL_EFFICIENCY_RESULT_OR_WHITE_GAP"],
            ),
            (
                "TASK_C_AI_GROWTH_QUALITY",
                "Which AI revenue, profit, capital and cash-conversion claims are actually proven?",
                ["AI_VALUE_CHAIN", "COUNTEREVIDENCE", "SOURCE_QUALITY"],
                ["AI_GROWTH_QUALITY_MATRIX"],
            ),
            (
                "TASK_D_GOVERNANCE_EXECUTION",
                "Is management's enterprise-value policy transmitting into financial results?",
                ["TEN_LINK_VALUE_CHAIN", "EVIDENCE_GRADE", "RETIREMENT_MISSION"],
                ["GOVERNANCE_EVIDENCE_MATRIX"],
            ),
            (
                "TASK_E_VALUATION_NEW_MONEY",
                "At price 263, where does valuation sit across earnings, book-value and dividend-yield scenarios?",
                ["TTM_PE", "FORWARD_PE", "PB", "DIVIDEND_YIELD"],
                ["THREE_SEPARATE_SCENARIO_MATRICES"],
            ),
        ]
        envelopes = [
            template_governance.build_task_envelope(
                task_id=task_id,
                research_question=question,
                required_analysis=analysis,
                required_output=outputs,
                **common,
            )
            for task_id, question, analysis, outputs in task_specs
        ]
        return {
            "templateId": template_governance.TEMPLATE_ID,
            "templateVersion": template_governance.TEMPLATE_VERSION,
            "templateHash": template_governance.template_hash(),
            "missionContext": template_governance.MISSION_CONTEXT,
            "taskEnvelope": envelopes[0],
            "taskEnvelopes": envelopes,
            "tasksDispatched": len(envelopes),
            "tasksCompleted": len(envelopes),
            "skillsUsed": ["OFFICIAL_IR_EVIDENCE_INGESTION"],
            "skillModes": template_governance.skill_capability_map(),
            "skillReceipts": [fixture.event["provenance"]["receipt_path"]],
            "skillsUnavailable": ["INVESTMENT_BANKING_RUNTIME"],
            "callableRuntimeNotExecuted": [
                "ANYSEARCH_RUNTIME",
                "OPENAI_EDITORIAL_RUNTIME",
            ],
            "validationStatus": "OWNER_REVIEW_REQUIRED",
            "actionable": False,
        }

    @staticmethod
    def _skill_execution_summary(
        *, fixture: Any, governance_metadata: dict[str, Any] | None,
        analysis_sha256: str, report_sha256: str,
        editorial_envelope: EditorialResultEnvelope | None,
        run_root: Path,
    ) -> dict[str, Any]:
        if not isinstance(fixture, QuarterlyEarningsPacket) or governance_metadata is None:
            return {
                "skillCapabilityMap": template_governance.skill_capability_map(),
                "taskEnvelopesDispatched": 0,
                "realSkillReceipts": [],
                "skillGuidedOnlyTasks": {"DATA_ANALYTICS": []},
                "callableRuntimeNotExecuted": ["ANYSEARCH", "OPENAI_EDITORIAL"],
                "unavailableSkills": ["INVESTMENT_BANKING"],
                "openaiEditorialExecuted": False,
                "openaiModel": "NOT_EXECUTED",
                "openaiFallbackUsed": False,
                "explicitBlockers": [
                    "OPENAI_EDITORIAL_NOT_AUTHORIZED_NOT_EXECUTED"
                ],
                "actionable": False,
            }
        provenance = fixture.event["provenance"]
        real_receipts = [
            {
                "skill": "OFFICIAL_IR",
                "receiptId": provenance["receipt_id"],
                "receiptPath": provenance["receipt_path"],
                "rawArtifactSha256": provenance["raw_sha256"],
                "status": "VALIDATED",
            }
        ]
        if editorial_envelope is not None:
            real_receipts.append(
                {
                    "skill": "OPENAI_EDITORIAL",
                    "receiptId": (
                        f"{editorial_envelope.run_id}:"
                        f"{editorial_envelope.task_id}:"
                        f"{editorial_envelope.editorial_output_sha256[:12]}"
                    ),
                    "receiptPath": str(run_root / "editorial_result_envelope.json"),
                    "inputResearchPackSha256": (
                        editorial_envelope.input_research_pack_sha256
                    ),
                    "outputSha256": editorial_envelope.editorial_output_sha256,
                    "status": editorial_envelope.validation_status,
                }
            )
        return {
            "recordType": "P1008_SKILL_EXECUTION_SUMMARY",
            "templateVersion": template_governance.TEMPLATE_VERSION,
            "skillCapabilityMap": template_governance.skill_capability_map(),
            "taskEnvelopesDispatched": governance_metadata["tasksDispatched"],
            "taskEnvelopeIds": [
                item["task_id"] for item in governance_metadata["taskEnvelopes"]
            ],
            "realSkillReceipts": real_receipts,
            "skillGuidedOnlyTasks": {
                "DATA_ANALYTICS": [
                    "TASK_A_FINANCIAL_TRANSMISSION",
                    "TASK_B_CAPITAL_EFFICIENCY",
                    "TASK_C_AI_GROWTH_QUALITY",
                    "TASK_E_VALUATION_NEW_MONEY",
                ],
            },
            "callableRuntimeNotExecuted": (
                ["ANYSEARCH"]
                if editorial_envelope is not None
                else ["ANYSEARCH", "OPENAI_EDITORIAL"]
            ),
            "unavailableSkills": ["INVESTMENT_BANKING"],
            "externalEvidenceCount": 0,
            "externalEvidenceSources": [],
            "openaiEditorialExecuted": editorial_envelope is not None,
            "openaiModel": (
                editorial_envelope.model_provenance.model_identifier
                if editorial_envelope is not None else "NOT_EXECUTED"
            ),
            "openaiFallbackUsed": False,
            "explicitBlockers": (
                [] if editorial_envelope is not None else [
                    "OPENAI_EDITORIAL_NOT_AUTHORIZED_NOT_EXECUTED"
                ]
            ),
            "validatedResearchPack": {
                "analysisPacketSha256": analysis_sha256,
                "reportCandidateSha256": report_sha256,
                "acceptedInputsOnly": True,
                "rawSkillOutputUsedDirectly": False,
            },
            "canvaExecuted": False,
            "actionable": False,
        }
