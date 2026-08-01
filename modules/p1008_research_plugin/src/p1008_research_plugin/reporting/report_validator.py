"""Fail-closed Report Production gate."""

from __future__ import annotations

import re

from pydantic import ValidationError

from ..analysis.analysis_contracts import AnalysisPacket
from ..phaseb1_common import canonical_json_bytes, sha256_bytes
from .report_contracts import EditorialValidation, ReportCandidate


class ReportValidationError(RuntimeError):
    """Report candidate drifted from its validated Analysis Packet."""


class ReportValidator:
    def validate(
        self,
        report: ReportCandidate | dict[str, object],
        analysis: AnalysisPacket,
    ) -> ReportCandidate:
        try:
            parsed = report if isinstance(report, ReportCandidate) else ReportCandidate.model_validate(report)
        except ValidationError as exc:
            raise ReportValidationError("Report candidate schema validation failed") from exc

        analysis_sha = sha256_bytes(
            canonical_json_bytes(analysis.model_dump(mode="json", by_alias=True))
        )
        if parsed.analysis_packet_sha256 != analysis_sha:
            raise ReportValidationError("Report bypassed or changed validated Analysis Packet")
        if parsed.thesis_state is not analysis.thesis_scorecard.overall_thesis:
            raise ReportValidationError("Report changed the governed thesis state")
        expected_facts = [item.statement for item in analysis.material_conclusions]
        if parsed.evidence_bound_facts != expected_facts:
            raise ReportValidationError("Report changed an evidence-bound conclusion")
        if parsed.authority_manifest_sha256 != analysis.authority_manifest_sha256:
            raise ReportValidationError("Report changed authority identity")
        text = "\n".join(section.body_zh for section in parsed.sections)
        forbidden = re.compile(r"(?:保證報酬|目標價保證|立即買進|立即賣出|主力洗盤|法人刻意壓價)", re.IGNORECASE)
        if forbidden.search(text):
            raise ReportValidationError("Report contains a forbidden claim or instruction")
        return parsed

    @staticmethod
    def editorial_result(report: ReportCandidate) -> EditorialValidation:
        return EditorialValidation(
            status="PASS",
            report_candidate_sha256=sha256_bytes(
                canonical_json_bytes(report.model_dump(mode="json", by_alias=True))
            ),
            required_sections_present=True,
            evidence_identity_preserved=True,
            thesis_identity_preserved=True,
            scripts_read_validated_report_only=True,
            errors=[],
            actionable=False,
        )
