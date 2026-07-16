"""Single-agent typed synthesis with a deterministic, no-network mock client."""

from __future__ import annotations

import hashlib
import importlib
import json
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID, uuid4

from ..openai.model_registry import ModelDefinition
from ..openai.tool_registry import ToolRegistry
from ..runtime.runtime_config import PHASE3B_LIVE_MODEL_ID, RuntimeConfig
from .contracts import (
    BaselineSnapshot,
    Confidence,
    EvidenceItem,
    ExecutionStep,
    FinancialBriefReport,
    FinancialBriefSynthesis,
    HostedWebSearchTrace,
    MetricImpact,
    MetricSynthesis,
    PluginId,
    PluginTrace,
    ProviderCitation,
    RoutePlan,
    Sentiment,
    SourceLocator,
    TokenUsage,
    ToolUsage,
    ValidatedEvidence,
    canonical_json_ready,
)
from .packet_gateway import PacketGateway


class AgentExecutionError(RuntimeError):
    """Raised before or after an invalid synthesis; never repaired with guessed data."""


class SynthesisClient(Protocol):
    mode: str
    synthesis_calls: int
    provider_response_id: str | None
    provider_request_ids: list[str]
    hosted_web_search_trace: list[HostedWebSearchTrace]
    provider_citations: list[ProviderCitation]

    def synthesize(
        self,
        *,
        baseline: BaselineSnapshot,
        validated: ValidatedEvidence,
        plan: RoutePlan,
    ) -> tuple[FinancialBriefSynthesis, TokenUsage]: ...


METRIC_FIELDS = ("revenue", "EPS", "margins", "valuation", "fx_impact")
OPENAI_CLIENT_MAX_RETRIES = 0
AGENT_RUN_MAX_TURNS = 1
RESPONSES_MAX_TOOL_CALLS = 1
STEP_FOR_PLUGIN = {
    PluginId.WEB_SEARCH: ExecutionStep.WEB_SEARCH,
    PluginId.DATA_ANALYTICS: ExecutionStep.DATA_ANALYTICS,
    PluginId.INVESTMENT_BANKING: ExecutionStep.INVESTMENT_BANKING,
}


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _provider_trace(
    result: Any,
) -> tuple[list[str], list[HostedWebSearchTrace], list[ProviderCitation]]:
    """Extract only public, non-sensitive Responses metadata exposed by SDK 0.18.2."""

    request_ids: list[str] = []
    search_traces: list[HostedWebSearchTrace] = []
    citations: list[ProviderCitation] = []
    citation_keys: set[tuple[str, str]] = set()
    for response in list(getattr(result, "raw_responses", None) or []):
        request_id = getattr(response, "request_id", None)
        if isinstance(request_id, str) and request_id and request_id not in request_ids:
            request_ids.append(request_id)
        for output in list(getattr(response, "output", None) or []):
            output_type = getattr(output, "type", None)
            if output_type == "web_search_call":
                action = getattr(output, "action", None)
                action_type = str(getattr(action, "type", "unknown"))
                queries = []
                query = getattr(action, "query", None)
                if isinstance(query, str) and query:
                    queries.append(query)
                for value in list(getattr(action, "queries", None) or []):
                    if isinstance(value, str) and value and value not in queries:
                        queries.append(value)
                source_urls = []
                action_url = getattr(action, "url", None)
                if isinstance(action_url, str) and action_url:
                    source_urls.append(action_url)
                for source in list(getattr(action, "sources", None) or []):
                    source_url = getattr(source, "url", None)
                    if (
                        isinstance(source_url, str)
                        and source_url
                        and source_url not in source_urls
                    ):
                        source_urls.append(source_url)
                search_traces.append(
                    HostedWebSearchTrace(
                        call_id=str(getattr(output, "id", "")),
                        status=str(getattr(output, "status", "")),
                        action_type=action_type,
                        queries=queries,
                        source_urls=source_urls,
                    )
                )
            elif output_type == "message":
                for content in list(getattr(output, "content", None) or []):
                    for annotation in list(getattr(content, "annotations", None) or []):
                        if getattr(annotation, "type", None) != "url_citation":
                            continue
                        url = getattr(annotation, "url", None)
                        title = getattr(annotation, "title", None)
                        if not isinstance(url, str) or not isinstance(title, str):
                            continue
                        key = (url, title)
                        if key in citation_keys:
                            continue
                        citations.append(ProviderCitation(url=url, title=title))
                        citation_keys.add(key)
    return request_ids, search_traces, citations


def _metric_synthesis(field_name: str, evidence: list[EvidenceItem]) -> MetricSynthesis:
    relevant = [item for item in evidence if field_name in item.changed_fields]
    if not relevant:
        return MetricSynthesis(
            new_evidence=["No validated new evidence for this field."],
            investment_impact="War-room baseline retained without a field-level change.",
        )
    summaries = [
        f"{item.summary} [{field_name}={item.field_values[field_name]}]"
        for item in relevant
    ]
    return MetricSynthesis(
        new_evidence=_unique(summaries),
        investment_impact=" ".join(_unique([item.investment_impact for item in relevant])),
    )


def deterministic_synthesis(validated: ValidatedEvidence) -> FinancialBriefSynthesis:
    evidence = list(validated.evidence)
    if not evidence:
        return FinancialBriefSynthesis(
            investment_impact="No validated material change; war-room baseline retained.",
            revenue=_metric_synthesis("revenue", evidence),
            EPS=_metric_synthesis("EPS", evidence),
            margins=_metric_synthesis("margins", evidence),
            valuation=_metric_synthesis("valuation", evidence),
            fx_impact=_metric_synthesis("fx_impact", evidence),
            catalysts=[],
            risks=[],
            sentiment=Sentiment.NEUTRAL,
            confidence=Confidence.LOW,
            data_quality_notes=["No new evidence packet claimed a material change."],
        )

    directions = {item.impact_direction for item in evidence}
    sentiment = next(iter(directions)) if len(directions) == 1 else Sentiment.NEUTRAL
    confidence_rank = {Confidence.LOW: 0, Confidence.MEDIUM: 1, Confidence.HIGH: 2}
    confidence = min(
        (item.confidence for item in evidence), key=lambda value: confidence_rank[value]
    )
    return FinancialBriefSynthesis(
        investment_impact=" ".join(
            _unique([item.investment_impact for item in evidence])
        ),
        revenue=_metric_synthesis("revenue", evidence),
        EPS=_metric_synthesis("EPS", evidence),
        margins=_metric_synthesis("margins", evidence),
        valuation=_metric_synthesis("valuation", evidence),
        fx_impact=_metric_synthesis("fx_impact", evidence),
        catalysts=_unique([value for item in evidence for value in item.catalysts]),
        risks=_unique([value for item in evidence for value in item.risks]),
        sentiment=sentiment,
        confidence=confidence,
        data_quality_notes=(
            list(validated.data_quality_notes)
            or ["Validated packets reported no additional data-quality warning."]
        ),
    )


class DeterministicMockClient:
    """Deterministic typed client; it never reads credentials or opens a network."""

    mode = "DETERMINISTIC_MOCK"

    def __init__(self, model_id: str = "phase3b-deterministic-mock") -> None:
        self.model_id = model_id
        self.synthesis_calls = 0
        self.provider_response_id: str | None = None
        self.provider_request_ids: list[str] = []
        self.hosted_web_search_trace: list[HostedWebSearchTrace] = []
        self.provider_citations: list[ProviderCitation] = []

    def synthesize(
        self,
        *,
        baseline: BaselineSnapshot,
        validated: ValidatedEvidence,
        plan: RoutePlan,
    ) -> tuple[FinancialBriefSynthesis, TokenUsage]:
        if self.synthesis_calls >= 1:
            raise AgentExecutionError("A Shadow run cannot synthesize more than once")
        self.synthesis_calls += 1
        synthesis = deterministic_synthesis(validated)
        prompt_payload = {
            "baseline": canonical_json_ready(baseline),
            "evidence": canonical_json_ready(validated),
            "route": canonical_json_ready(plan),
        }
        input_size = len(
            json.dumps(prompt_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        )
        output_size = len(
            json.dumps(
                canonical_json_ready(synthesis),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        input_tokens = (input_size + 3) // 4
        output_tokens = (output_size + 3) // 4
        return synthesis, TokenUsage(
            source="DETERMINISTIC_ESTIMATE",
            model_id=self.model_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
        )


class LiveAgentsSdkClient:
    """Official Agents SDK path. Construction is inert; synthesis requires credentials."""

    mode = "AGENTS_SDK"

    def __init__(
        self,
        *,
        config: RuntimeConfig,
        model: ModelDefinition,
        prompt_path: Path,
        tool_registry: ToolRegistry,
    ) -> None:
        self.config = config
        self.model = model
        self.prompt_path = prompt_path.resolve()
        self.tool_registry = tool_registry
        self.synthesis_calls = 0
        self.provider_response_id: str | None = None
        self.provider_request_ids: list[str] = []
        self.hosted_web_search_trace: list[HostedWebSearchTrace] = []
        self.provider_citations: list[ProviderCitation] = []

    def synthesize(
        self,
        *,
        baseline: BaselineSnapshot,
        validated: ValidatedEvidence,
        plan: RoutePlan,
    ) -> tuple[FinancialBriefSynthesis, TokenUsage]:
        PacketGateway.validate_live_evidence(plan, validated)
        configured_model = self.config.require_live_credentials()
        if (
            configured_model != PHASE3B_LIVE_MODEL_ID
            or configured_model != self.model.model_id
            or not self.model.network_required
        ):
            raise AgentExecutionError("Live model registry binding is invalid")
        if self.synthesis_calls >= 1:
            raise AgentExecutionError("A Shadow run cannot synthesize more than once")
        if not self.prompt_path.is_file():
            raise AgentExecutionError("Financial Brief prompt is unavailable")

        try:
            sdk = importlib.import_module("".join(("ag", "ents")))
            openai_sdk = importlib.import_module("openai")
            agent_class = getattr(sdk, "Agent")
            runner_class = getattr(sdk, "Runner")
            model_settings_class = getattr(sdk, "ModelSettings")
            retry_settings_class = getattr(sdk, "ModelRetrySettings")
            provider_class = getattr(sdk, "OpenAIProvider")
            run_config_class = getattr(sdk, "RunConfig")
            async_openai_class = getattr(openai_sdk, "AsyncOpenAI")
        except (ImportError, AttributeError) as exc:
            raise AgentExecutionError("OpenAI Agents SDK is unavailable") from exc

        tools = []
        if plan.calls_for(ExecutionStep.WEB_SEARCH) == 1:
            tools.append(self.tool_registry.build_hosted_web_search())
        instructions = self.prompt_path.read_text(encoding="utf-8")
        payload = {
            "run_type": plan.run_type.value,
            "baseline": canonical_json_ready(baseline),
            "validated_evidence": canonical_json_ready(validated),
            "route": canonical_json_ready(plan),
        }
        agent = agent_class(
            name="P1008 Financial Brief Agent",
            instructions=instructions,
            model=self.model.model_id,
            tools=tools,
            output_type=FinancialBriefSynthesis,
        )
        openai_client = async_openai_class(max_retries=OPENAI_CLIENT_MAX_RETRIES)
        model_settings = model_settings_class(
            parallel_tool_calls=False,
            extra_args={"max_tool_calls": RESPONSES_MAX_TOOL_CALLS},
            retry=retry_settings_class(max_retries=OPENAI_CLIENT_MAX_RETRIES),
        )
        run_config = run_config_class(
            model_provider=provider_class(
                openai_client=openai_client,
                use_responses=True,
            ),
            model_settings=model_settings,
            tracing_disabled=True,
        )
        self.synthesis_calls += 1
        result = runner_class.run_sync(
            agent,
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            max_turns=AGENT_RUN_MAX_TURNS,
            run_config=run_config,
        )
        response_id = getattr(result, "last_response_id", None)
        self.provider_response_id = response_id if isinstance(response_id, str) else None
        (
            self.provider_request_ids,
            self.hosted_web_search_trace,
            self.provider_citations,
        ) = _provider_trace(result)
        if len(self.hosted_web_search_trace) > RESPONSES_MAX_TOOL_CALLS:
            raise AgentExecutionError("Hosted Web Search call ceiling exceeded")
        output = result.final_output
        synthesis = (
            output
            if isinstance(output, FinancialBriefSynthesis)
            else FinancialBriefSynthesis.model_validate(output)
        )
        usage = getattr(getattr(result, "context_wrapper", None), "usage", None)
        input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
        output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
        return synthesis, TokenUsage(
            source="AGENTS_SDK",
            model_id=self.model.model_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
        )


class AgentRunner:
    def __init__(
        self,
        client: SynthesisClient,
        model: ModelDefinition,
        *,
        utc_now: Callable[[], datetime] | None = None,
        uuid_factory: Callable[[], UUID] | None = None,
    ) -> None:
        self.client = client
        self.model = model
        self.utc_now = utc_now or (lambda: datetime.now(timezone.utc))
        self.uuid_factory = uuid_factory or uuid4

    @staticmethod
    def _run_id(
        baseline: BaselineSnapshot,
        validated: ValidatedEvidence,
        plan: RoutePlan,
        execution_mode: str,
        executed_at_utc: datetime | None,
        live_uuid: UUID | None,
    ) -> str:
        material = json.dumps(
            {
                "run_type": plan.run_type.value,
                "as_of_date": baseline.as_of_date.isoformat(),
                "baseline_hash": baseline.baseline_hash,
                "evidence_ids": validated.evidence_ids,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        digest = hashlib.sha256(material).hexdigest().upper()[:16]
        run_label = plan.run_type.value.replace("_", "-")
        prefix = f"P3B-{run_label}-{baseline.as_of_date:%Y%m%d}-{execution_mode}"
        if execution_mode == "MOCK":
            return f"{prefix}-{digest}"
        if executed_at_utc is None or live_uuid is None:
            raise AgentExecutionError("Live run identity requires local UTC and UUID metadata")
        timestamp = executed_at_utc.strftime("%Y%m%dT%H%M%S%fZ")
        return f"{prefix}-{timestamp}-{live_uuid.hex[:8].upper()}"

    def _execution_identity(
        self,
        baseline: BaselineSnapshot,
        validated: ValidatedEvidence,
        plan: RoutePlan,
    ) -> tuple[str, datetime | None, str]:
        if self.client.mode == "DETERMINISTIC_MOCK":
            mode = "MOCK"
            executed_at_utc = None
            live_uuid = None
        elif self.client.mode == "AGENTS_SDK":
            mode = "LIVE"
            observed = self.utc_now()
            if observed.tzinfo is None or observed.utcoffset() is None:
                raise AgentExecutionError("Live run identity requires a timezone-aware UTC clock")
            executed_at_utc = observed.astimezone(timezone.utc)
            live_uuid = self.uuid_factory()
        else:
            raise AgentExecutionError("Unknown synthesis execution mode")
        return (
            mode,
            executed_at_utc,
            self._run_id(
                baseline,
                validated,
                plan,
                mode,
                executed_at_utc,
                live_uuid,
            ),
        )

    @staticmethod
    def _metric_impact(
        field_name: str,
        baseline: BaselineSnapshot,
        validated: ValidatedEvidence,
        synthesis: FinancialBriefSynthesis,
    ) -> MetricImpact:
        attribute = "eps" if field_name == "EPS" else field_name
        narrative: MetricSynthesis = getattr(synthesis, attribute)
        evidence_ids = [
            item.evidence_id
            for item in validated.evidence
            if field_name in item.changed_fields
        ]
        baseline_value = baseline.data.get(field_name, {})
        return MetricImpact(
            baseline=baseline_value if isinstance(baseline_value, dict) else {"value": baseline_value},
            new_evidence=narrative.new_evidence,
            investment_impact=narrative.investment_impact,
            evidence_ids=evidence_ids,
        )

    @staticmethod
    def _trace(
        plan: RoutePlan,
        validated: ValidatedEvidence,
        synthesis_mode: str,
    ) -> tuple[list[PluginTrace], list[ToolUsage]]:
        evidence_by_step: dict[ExecutionStep, list[str]] = {
            step: [] for step in ExecutionStep
        }
        packet_counts = {step: 0 for step in ExecutionStep}
        for packet in validated.packets:
            step = STEP_FOR_PLUGIN[packet.plugin]
            packet_counts[step] += 1
            evidence_by_step[step].extend(item.evidence_id for item in packet.evidence)

        traces = []
        usages = []
        for step in ExecutionStep:
            if step is ExecutionStep.OPENAI_SYNTHESIS:
                count = int(validated.material_delta)
                status = (
                    "LIVE_SYNTHESIZED"
                    if count and synthesis_mode == "AGENTS_SDK"
                    else "MOCK_SYNTHESIZED"
                    if count
                    else "NOT_ROUTED"
                )
                mode = synthesis_mode if count else "NOT_ROUTED"
                ids = list(validated.evidence_ids) if count else []
            else:
                count = packet_counts[step]
                status = "PACKET_VALIDATED" if count else "NOT_ROUTED"
                mode = "EXECUTOR_PACKET" if count else "NOT_ROUTED"
                ids = sorted(set(evidence_by_step[step]))
            traces.append(
                PluginTrace(
                    plugin=step,
                    status=status,
                    call_count=count,
                    evidence_ids=ids,
                )
            )
            usages.append(ToolUsage(tool=step, mode=mode, call_count=count))
        return traces, usages

    def run(
        self,
        *,
        baseline: BaselineSnapshot,
        validated: ValidatedEvidence,
        plan: RoutePlan,
    ) -> FinancialBriefReport:
        execution_mode, executed_at_utc, run_id = self._execution_identity(
            baseline, validated, plan
        )
        if execution_mode == "LIVE":
            PacketGateway.validate_live_evidence(plan, validated)
        if validated.material_delta:
            synthesis, token_usage = self.client.synthesize(
                baseline=baseline, validated=validated, plan=plan
            )
        else:
            synthesis = deterministic_synthesis(validated)
            token_usage = TokenUsage(
                source="NOT_CALLED",
                model_id=self.model.model_id,
                input_tokens=0,
                output_tokens=0,
                total_tokens=0,
            )
        if self.client.synthesis_calls > 1:
            raise AgentExecutionError("Synthesis call ceiling exceeded")

        change_evidence = {
            field_name: [
                item.evidence_id
                for item in validated.evidence
                if field_name in item.changed_fields
            ]
            for field_name in validated.changed_fields
        }
        locators: list[SourceLocator] = []
        seen_locators: set[tuple[str, str]] = set()
        for item in validated.evidence:
            for locator in item.source_locators:
                key = (locator.source_id, locator.locator)
                if key not in seen_locators:
                    locators.append(locator)
                    seen_locators.add(key)

        traces, tool_usage = self._trace(plan, validated, self.client.mode)
        material = validated.material_delta
        return FinancialBriefReport(
            run_id=run_id,
            execution_mode=execution_mode,
            executed_at_utc=executed_at_utc,
            provider_response_id=getattr(self.client, "provider_response_id", None),
            provider_request_ids=list(
                getattr(self.client, "provider_request_ids", [])
            ),
            hosted_web_search_call_count=len(
                getattr(self.client, "hosted_web_search_trace", [])
            ),
            hosted_web_search_trace=list(
                getattr(self.client, "hosted_web_search_trace", [])
            ),
            provider_citations=list(
                getattr(self.client, "provider_citations", [])
            ),
            run_type=plan.run_type,
            as_of_date=baseline.as_of_date,
            baseline_hash=baseline.baseline_hash,
            plugin_trace=traces,
            war_room_baseline=baseline.data,
            new_evidence=validated.evidence,
            investment_impact=synthesis.investment_impact,
            revenue=self._metric_impact("revenue", baseline, validated, synthesis),
            EPS=self._metric_impact("EPS", baseline, validated, synthesis),
            margins=self._metric_impact("margins", baseline, validated, synthesis),
            valuation=self._metric_impact("valuation", baseline, validated, synthesis),
            fx_impact=self._metric_impact("fx_impact", baseline, validated, synthesis),
            catalysts=synthesis.catalysts,
            risks=synthesis.risks,
            sentiment=synthesis.sentiment,
            confidence=synthesis.confidence,
            changed_fields=validated.changed_fields,
            change_evidence=change_evidence,
            evidence_ids=validated.evidence_ids,
            source_locators=locators,
            data_quality_notes=synthesis.data_quality_notes,
            token_usage=token_usage,
            tool_usage=tool_usage,
            no_material_change=not material,
            status=("MATERIAL_CHANGE_CANDIDATE" if material else "NO_MATERIAL_CHANGE"),
            synthesis_count=int(material),
            manual_shadow=True,
            actionable=False,
        )
