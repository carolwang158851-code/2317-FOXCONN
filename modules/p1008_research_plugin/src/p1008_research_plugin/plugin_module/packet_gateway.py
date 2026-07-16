"""Fail-closed validation for Codex executor and hosted-tool evidence packets."""

from __future__ import annotations

from collections import Counter
from datetime import date
from typing import Any, Iterable, Mapping
from urllib.parse import urlsplit

from pydantic import ValidationError

from .contracts import (
    EvidencePacket,
    ExecutionStep,
    PluginId,
    RoutePlan,
    RunType,
    ValidatedEvidence,
    is_verifiable_https_url,
)
from .router import RouteSignals


class PacketValidationError(RuntimeError):
    """Raised when packet evidence is incomplete, stale, or off-route."""


STEP_FOR_PLUGIN = {
    PluginId.WEB_SEARCH: ExecutionStep.WEB_SEARCH,
    PluginId.DATA_ANALYTICS: ExecutionStep.DATA_ANALYTICS,
    PluginId.INVESTMENT_BANKING: ExecutionStep.INVESTMENT_BANKING,
}
ALLOWED_CHANGED_FIELDS = {"revenue", "EPS", "margins", "valuation", "fx_impact"}
FORBIDDEN_LIVE_PROVENANCE_MARKERS = ("fixture", "mock", "deterministic")
OFFICIAL_MONTHLY_REVENUE_HOSTS = ("honhai.com", "mops.twse.com.tw")


class PacketGateway:
    def parse(self, payloads: Iterable[EvidencePacket | Mapping[str, Any]]) -> list[EvidencePacket]:
        packets = []
        for payload in payloads:
            try:
                packet = (
                    payload
                    if isinstance(payload, EvidencePacket)
                    else EvidencePacket.model_validate(payload)
                )
            except ValidationError as exc:
                raise PacketValidationError("Evidence packet schema validation failed") from exc
            packets.append(packet)
        return packets

    @staticmethod
    def aggregate_signals(packets: Iterable[EvidencePacket]) -> RouteSignals:
        signals = [packet.signals for packet in packets]
        return RouteSignals(
            material_delta=any(item.material_delta for item in signals),
            numeric_anomaly=any(item.numeric_anomaly for item in signals),
            data_quality_warning=any(item.data_quality_warning for item in signals),
            major_transaction=any(item.major_transaction for item in signals),
            earnings_event=any(item.earnings_event for item in signals),
            capital_allocation_event=any(item.capital_allocation_event for item in signals),
            financial_numbers=any(item.financial_numbers for item in signals),
        )

    def validate(
        self,
        plan: RoutePlan,
        packets: Iterable[EvidencePacket],
        as_of_date: date | str,
    ) -> ValidatedEvidence:
        normalized_date = date.fromisoformat(as_of_date) if isinstance(as_of_date, str) else as_of_date
        ordered_packets = sorted(packets, key=lambda item: (item.plugin.value, item.packet_id))
        counts = Counter(packet.plugin for packet in ordered_packets)

        missing = sorted(
            (plugin.value for plugin in plan.required_packets if counts[plugin] == 0)
        )
        if missing:
            raise PacketValidationError(f"Missing required evidence packets: {missing}")

        for plugin, count in counts.items():
            step = STEP_FOR_PLUGIN[plugin]
            ceiling = plan.calls_for(step)
            if ceiling == 0 or count > ceiling:
                raise PacketValidationError(f"Packet count exceeds route for {plugin.value}")

        seen_evidence_ids: set[str] = set()
        evidence = []
        for packet in ordered_packets:
            if plan.run_type not in packet.supported_run_types:
                raise PacketValidationError(
                    f"Packet {packet.packet_id} does not support {plan.run_type.value}"
                )
            if packet.as_of_date > normalized_date:
                raise PacketValidationError(f"Future-dated packet: {packet.packet_id}")
            if packet.expires_on < normalized_date:
                raise PacketValidationError(f"Expired packet: {packet.packet_id}")
            for item in packet.evidence:
                unknown_fields = sorted(set(item.changed_fields) - ALLOWED_CHANGED_FIELDS)
                if unknown_fields:
                    raise PacketValidationError(
                        f"Evidence claims unsupported changed fields: {unknown_fields}"
                    )
                if item.evidence_id in seen_evidence_ids:
                    raise PacketValidationError(
                        f"Duplicate evidence identifier: {item.evidence_id}"
                    )
                seen_evidence_ids.add(item.evidence_id)
                evidence.append(item)

        evidence.sort(key=lambda item: item.evidence_id)
        material_delta = any(packet.signals.material_delta for packet in ordered_packets)
        synthesis_calls = plan.calls_for(ExecutionStep.OPENAI_SYNTHESIS)
        if material_delta and synthesis_calls != 1:
            raise PacketValidationError("Material evidence requires one synthesis route")
        if synthesis_calls == 1 and not material_delta:
            raise PacketValidationError("Synthesis route requires material evidence")
        if material_delta and not evidence:
            raise PacketValidationError("Material delta has no validated evidence")
        if not material_delta and evidence:
            raise PacketValidationError("Non-material packets cannot claim changed evidence")

        changed_fields = sorted(
            {field_name for item in evidence for field_name in item.changed_fields}
        )
        notes = sorted({note for item in evidence for note in item.data_quality_notes})
        return ValidatedEvidence(
            packets=ordered_packets,
            evidence=evidence,
            material_delta=material_delta,
            changed_fields=changed_fields,
            evidence_ids=[item.evidence_id for item in evidence],
            data_quality_notes=notes,
        )

    @staticmethod
    def validate_live_evidence(plan: RoutePlan, validated: ValidatedEvidence) -> None:
        """Reject test provenance before a live synthesis can be requested."""

        for packet in validated.packets:
            for item in packet.evidence:
                provenance_text = " ".join(
                    [
                        item.summary,
                        *item.data_quality_notes,
                        *(locator.source_tier for locator in item.source_locators),
                        *(locator.locator for locator in item.source_locators),
                    ]
                ).lower()
                if any(
                    marker in provenance_text
                    for marker in FORBIDDEN_LIVE_PROVENANCE_MARKERS
                ):
                    raise PacketValidationError(
                        f"Live evidence cannot use test provenance: {item.evidence_id}"
                    )

                for locator in item.source_locators:
                    if not is_verifiable_https_url(locator.locator):
                        raise PacketValidationError(
                            f"Live evidence requires a verifiable HTTPS locator: {item.evidence_id}"
                        )

                if (
                    plan.run_type is RunType.MONTHLY_REVENUE
                    and "revenue" in item.changed_fields
                ):
                    official = any(
                        any(
                            (urlsplit(locator.locator).hostname or "").lower()
                            == host
                            or (urlsplit(locator.locator).hostname or "").lower().endswith(
                                "." + host
                            )
                            for host in OFFICIAL_MONTHLY_REVENUE_HOSTS
                        )
                        for locator in item.source_locators
                    )
                    if not official:
                        raise PacketValidationError(
                            "MONTHLY_REVENUE evidence must cite Hon Hai or MOPS for "
                            f"every revenue claim: {item.evidence_id}"
                        )
