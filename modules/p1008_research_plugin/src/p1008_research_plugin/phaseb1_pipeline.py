"""Runtime-only deterministic Phase B1 vertical-slice orchestration."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .adapters.authority_adapter import AuthorityAdapter
from .analysis import AnalysisBuilder, AnalysisPacket, AnalysisValidator
from .contract_loader import ContractLoader
from .phaseb1_common import (
    PhaseB1BoundaryError,
    atomic_write,
    atomic_write_json,
    canonical_json_bytes,
    ensure_runtime_output,
    protected_state_hashes,
    sha256_bytes,
    sha256_file,
)
from .plugin_module.packet_gateway import PacketGateway, PacketValidationError
from .plugin_module.router import PluginRouter
from .reporting import (
    ReportBuilder,
    ReportCandidate,
    ReportValidator,
    ScriptBuilder,
    ShortsDurationValidator,
)
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
            raise PhaseB1BoundaryError(f"Run ID already exists: {run_id}")
        generated_at = fixture.generated_at_utc if isinstance(fixture, QuarterlyEarningsPacket) else fixture["generatedAtUtc"]
        generated = self._utc(generated_at)
        before = protected_state_hashes(self.package_root)
        run_root.mkdir(parents=True, exist_ok=False)
        atomic_write_json(run_root / "protected_state_hashes_before.json", before)

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

        analysis_sha = atomic_write_json(
            run_root / "analysis_packet.json",
            analysis.model_dump(mode="json", by_alias=True),
        )
        atomic_write_json(
            run_root / "analysis_validation.json",
            gate.model_dump(mode="json", by_alias=True),
        )
        evidence_sha = atomic_write_json(
            run_root / "evidence_manifest.json", evidence_manifest
        )
        after = protected_state_hashes(self.package_root)
        atomic_write_json(run_root / "protected_state_hashes_after.json", after)
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
        atomic_write_json(run_root / "run_manifest.json", manifest)
        return {
            "run_id": run_id,
            "run_root": str(run_root),
            "analysis": analysis,
            "evidence": evidence,
            "analysis_sha256": analysis_sha,
        }

    def build_report(
        self, *, run_id: str, output_base: Path | None = None,
        trigger_lineage: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        event_type = str((trigger_lineage or {}).get("eventType") or "MONTHLY_REVENUE")
        if event_type not in self.SUPPORTED_EVENTS:
            raise PhaseB1PipelineError(f"Unsupported Phase B1 event: {event_type}")
        fixture, evidence = self.load_inputs(event_type, trigger_lineage)
        expected_run_id = self.deterministic_run_id(fixture)
        if run_id != expected_run_id:
            raise PhaseB1PipelineError("Run ID does not match governed deterministic inputs")
        run_root = self._run_root(run_id, output_base)
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
            stored_run_manifest.get("state") != "ANALYSIS_CANDIDATE_READY"
            or stored_run_manifest.get("artifacts") != expected_analysis_artifacts
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
        markdown = MarkdownRenderer().render(report).replace("\r\n", "\n")
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
        html_preview = formal.html(report)
        pdf_preview = formal.pdf(report)

        report_sha = atomic_write_json(
            run_root / "report_candidate.json",
            report.model_dump(mode="json", by_alias=True),
        )
        atomic_write(run_root / "report_candidate.md", markdown.encode("utf-8"))
        atomic_write(run_root / "report_candidate.html", html_preview)
        atomic_write(run_root / "report_candidate.pdf", pdf_preview)
        atomic_write_json(
            run_root / "chart_data.json",
            [item.model_dump(mode="json", by_alias=True) for item in charts],
        )
        atomic_write(run_root / "longform_script_candidate.md", longform.encode("utf-8"))
        atomic_write(run_root / "shorts_75s_candidate.md", shorts.encode("utf-8"))
        atomic_write_json(
            run_root / "shorts_duration_validation.json",
            duration.model_dump(mode="json", by_alias=True),
        )
        atomic_write_json(
            run_root / "editorial_validation.json",
            editorial.model_dump(mode="json", by_alias=True),
        )
        owner_review = {
            "runId": run_id,
            "status": "OWNER_REVIEW_REQUIRED",
            "reportCandidateSha256": report_sha,
            "publishAuthorized": False,
            "liveSynthesisAuthorized": False,
            "phaseB2Started": False,
            "actionable": False,
        }
        atomic_write_json(run_root / "owner_review.json", owner_review)
        after = protected_state_hashes(self.package_root)
        atomic_write_json(
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
            "protected_state_hashes_before.json",
            "protected_state_hashes_after.json",
        ]
        manifest = {
            "runId": run_id,
            "eventType": event_type,
            "state": "REPORT_CANDIDATE_READY",
            "generatedAtUtc": generated_at,
            "deterministicMode": True,
            "artifacts": {
                name: sha256_file(run_root / name) for name in artifact_names
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
        atomic_write_json(run_root / "run_manifest.json", manifest, overwrite=True)
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
        }

    def run_all(self, *, output_base: Path | None = None) -> dict[str, Any]:
        analysis = self.build_analysis(output_base=output_base)
        return self.build_report(run_id=analysis["run_id"], output_base=output_base)

    def _run_root(self, run_id: str, output_base: Path | None) -> Path:
        if any(char not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-" for char in run_id):
            raise PhaseB1BoundaryError("Unsafe Run ID")
        base = output_base or self.package_root / "runtime" / "report_production"
        if output_base is None:
            ensure_runtime_output(self.package_root, base)
        return (base.resolve() / run_id).resolve()

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
        envelope = template_governance.build_task_envelope(
            run_id=run_id,
            task_id="FY2026_Q2_ENTERPRISE_VALUE_REVIEW",
            event=event_type,
            period=fixture.values["fiscalPeriod"],
            authority_cutoff=authority_cutoff,
            research_question="Assess earnings quality, cash conversion, durability and enterprise-value implications.",
            required_inputs=["OFFICIAL_IR_RESULTS", "GOVERNED_AUTHORITY", "GOVERNED_MARKET_DATA"],
            required_analysis=["FINANCIAL_TRANSMISSION", "DURABILITY", "NON_GREEN_DEEP_REVIEW", "VALUATION", "CHARTS"],
            required_output=["ANALYSIS_CANDIDATE", "REPORT_CANDIDATE", "OWNER_REVIEW"],
            prohibited_actions=["PUBLISH", "TRADE_INSTRUCTION", "AUTHORITY_WRITE", "MODEL_CALL"],
        )
        return {
            "templateId": template_governance.TEMPLATE_ID,
            "templateVersion": template_governance.TEMPLATE_VERSION,
            "templateHash": template_governance.template_hash(),
            "missionContext": template_governance.MISSION_CONTEXT,
            "taskEnvelope": envelope,
            "tasksDispatched": 1,
            "tasksCompleted": 1,
            "skillsUsed": ["OFFICIAL_IR_EVIDENCE_INGESTION"],
            "skillModes": {"DATA_ANALYTICS": "SKILL_GUIDED_ONLY", "INVESTMENT_BANKING": "UNAVAILABLE"},
            "skillReceipts": [fixture.event["provenance"]["receipt_path"]],
            "skillsUnavailable": ["INVESTMENT_BANKING_RUNTIME"],
            "validationStatus": "OWNER_REVIEW_REQUIRED",
            "actionable": False,
        }
