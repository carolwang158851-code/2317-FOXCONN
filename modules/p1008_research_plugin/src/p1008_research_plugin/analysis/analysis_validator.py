"""Fail-closed semantic validation for Phase B1 analysis packets."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from pydantic import ValidationError

from .analysis_contracts import AnalysisGateResult, AnalysisPacket
from ..phaseb1_common import canonical_json_bytes, sha256_bytes
from ..plugin_module.contracts import ValidatedEvidence


class AnalysisValidationError(RuntimeError):
    """Analysis did not meet the governed Phase B1 contract."""


FORBIDDEN_INTENT_CLAIMS = (
    "主力洗盤",
    "法人刻意壓價",
    "外資故意吃貨",
    "散戶被割",
    "市場一定已經反映完畢",
)


class AnalysisValidator:
    def validate(
        self,
        packet: AnalysisPacket | dict[str, object],
        evidence: ValidatedEvidence,
    ) -> AnalysisPacket:
        try:
            parsed = packet if isinstance(packet, AnalysisPacket) else AnalysisPacket.model_validate(packet)
        except ValidationError as exc:
            raise AnalysisValidationError("Analysis packet schema validation failed") from exc

        payload = json.dumps(parsed.model_dump(mode="json", by_alias=True), ensure_ascii=False)
        if any(statement in payload for statement in FORBIDDEN_INTENT_CLAIMS):
            raise AnalysisValidationError("Unsupported market-participant intent claim")
        if re.search(r"(?:AI revenue|AI營收)", payload, re.IGNORECASE):
            raise AnalysisValidationError("AI exposure cannot be relabeled as AI revenue")
        if parsed.actionable is not False or parsed.investor_views.actionable is not False:
            raise AnalysisValidationError("Analysis candidate must remain actionable=false")

        validated_ids = set(evidence.evidence_ids)
        packet_ids = set(parsed.source_evidence_ids)
        if not validated_ids.issubset(packet_ids):
            raise AnalysisValidationError("Analysis dropped validated Evidence IDs")
        expected_input_hashes = {
            input_packet.packet_id: sha256_bytes(
                canonical_json_bytes(
                    input_packet.model_dump(mode="json", by_alias=True)
                )
            )
            for input_packet in evidence.packets
        }
        if parsed.input_evidence_hashes != expected_input_hashes:
            raise AnalysisValidationError("Analysis input Evidence hashes drifted")
        for conclusion in parsed.material_conclusions:
            if not conclusion.alternative_explanation:
                raise AnalysisValidationError("Material conclusion lacks alternative explanation")
            if conclusion.counter_evidence is None:
                raise AnalysisValidationError("Material conclusion lacks counterevidence")
        return parsed

    @staticmethod
    def result(packet: AnalysisPacket, *, checked_at: datetime) -> AnalysisGateResult:
        return AnalysisGateResult(
            status="PASS",
            analysis_packet_sha256=sha256_bytes(
                canonical_json_bytes(packet.model_dump(mode="json", by_alias=True))
            ),
            errors=[],
            warnings=[
                "Market psychology is inference, not fact.",
                "Quarterly FCF is negative; structural dividend risk remains unproven.",
            ],
            checked_at_utc=checked_at.astimezone(timezone.utc),
            actionable=False,
        )
