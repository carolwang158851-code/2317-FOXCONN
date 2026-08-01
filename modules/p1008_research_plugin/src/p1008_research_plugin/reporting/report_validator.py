"""Fail-closed Report Production and editorial gates."""

from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher

from pydantic import ValidationError

from ..analysis.analysis_contracts import AnalysisPacket
from ..phaseb1_common import canonical_json_bytes, sha256_bytes
from .report_contracts import (
    EditorialValidation,
    REQUIRED_SECTION_IDS,
    ReportCandidate,
    ShortsDurationValidation,
)
from .script_builder import ShortsDurationValidator


class ReportValidationError(RuntimeError):
    """Report candidate drifted from its validated Analysis Packet."""


class ReportValidator:
    _FORBIDDEN = re.compile(
        r"(?:立即買進|立即賣出|保證獲利|主力洗盤|法人刻意壓價|外資故意吃貨|散戶被割)",
        re.IGNORECASE,
    )
    _PLACEHOLDER = re.compile(
        r"(?:example\.invalid|\b(?:mock|fixture|placeholder|todo|tbd)\b|待補|請填入)",
        re.IGNORECASE,
    )
    _NUMBER = re.compile(r"(?<![A-Za-z])[-+]?\d+(?:[,.]\d+)*")

    @classmethod
    def _numbers(cls, text: str) -> set[str]:
        result: set[str] = set()
        for token in cls._NUMBER.findall(text):
            try:
                normalized = Decimal(token.replace(",", "")).normalize()
            except InvalidOperation:
                continue
            result.add(format(normalized, "f"))
        return result

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
        if self._FORBIDDEN.search(text):
            raise ReportValidationError("Report contains a forbidden claim or instruction")
        return parsed

    @classmethod
    def editorial_result(
        cls,
        report: ReportCandidate,
        analysis: AnalysisPacket,
        longform: str,
        shorts: str,
        duration: ShortsDurationValidation,
    ) -> EditorialValidation:
        errors: list[str] = []
        actual_ids = tuple(section.section_id for section in report.sections)
        required_sections_present = (
            actual_ids == REQUIRED_SECTION_IDS
            and all(section.body_zh.strip() for section in report.sections)
        )
        if not required_sections_present:
            errors.append("Required report sections are missing, empty, or out of order")

        known_ids = {item.evidence_id for item in report.evidence_references}
        all_evidence_ids_resolve = all(
            set(section.evidence_ids).issubset(known_ids) for section in report.sections
        )
        if not all_evidence_ids_resolve:
            errors.append("A report section cites an unresolved Evidence ID")

        classes = {section.epistemic_class for section in report.sections}
        facts_and_inferences_separated = "FACT" in classes and "INFERENCE" in classes
        if not facts_and_inferences_separated:
            errors.append("FACT and INFERENCE sections are not explicitly separated")

        report_text = "\n".join(
            [report.primary_investor_question, *report.evidence_bound_facts]
            + [section.body_zh for section in report.sections]
        )
        analysis_text = json.dumps(
            analysis.model_dump(mode="json", by_alias=True), ensure_ascii=False
        )
        allowed_numbers = cls._numbers(analysis_text) | {"1", "5", "20"}
        report_numbers = cls._numbers(report_text)
        unsupported = sorted(report_numbers - allowed_numbers)
        unsupported_numeric_claims_absent = not unsupported
        if unsupported:
            errors.append("Unsupported numeric claims: " + ", ".join(unsupported))

        forbidden_intent_claims_absent = cls._FORBIDDEN.search(report_text) is None
        if not forbidden_intent_claims_absent:
            errors.append("Forbidden intent or trading language is present")
        placeholders_absent = cls._PLACEHOLDER.search(report_text) is None
        if not placeholders_absent:
            errors.append("Placeholder, mock, or fixture language is present")

        bodies = [re.sub(r"\s+", "", section.body_zh) for section in report.sections]
        duplicate_sections_absent = True
        for index, body in enumerate(bodies):
            for other in bodies[index + 1 :]:
                if body == other or (
                    min(len(body), len(other)) >= 40
                    and SequenceMatcher(None, body, other).ratio() >= 0.94
                ):
                    duplicate_sections_absent = False
                    break
        if not duplicate_sections_absent:
            errors.append("Duplicate or near-duplicate editorial sections were detected")

        shorts_duration_passed = duration.duration_gate_status != "FAIL"
        if not shorts_duration_passed:
            errors.extend(duration.errors)

        section_map = {item.section_id: item for item in report.sections}
        next_section = section_map.get("NEXT_VALIDATION_DATE_AND_EVENT")
        next_validation_evidence_bound = bool(
            next_section and next_section.evidence_ids and next_section.body_zh.strip()
        )
        if not next_validation_evidence_bound:
            errors.append("Next validation event is not evidence-bound")
        invalidation = section_map.get("INVALIDATION_CONDITIONS")
        invalidation_condition_present = bool(
            invalidation and invalidation.body_zh.strip() and invalidation.evidence_ids
        )
        if not invalidation_condition_present:
            errors.append("An evidence-bound invalidation condition is missing")

        expected_sha = sha256_bytes(
            canonical_json_bytes(analysis.model_dump(mode="json", by_alias=True))
        )
        analysis_identity_preserved = (
            report.analysis_packet_sha256 == expected_sha
            and report.thesis_state is analysis.thesis_scorecard.overall_thesis
            and report.evidence_bound_facts
            == [item.statement for item in analysis.material_conclusions]
        )
        if not analysis_identity_preserved:
            errors.append("Analysis identity was not preserved")

        scripts_read_validated_report_only = (
            bool(longform.strip())
            and bool(shorts.strip())
            and report.primary_investor_question in longform
            and section_map["NEXT_VALIDATION_DATE_AND_EVENT"].body_zh.split("；")[0]
            in longform
        )
        if not scripts_read_validated_report_only:
            errors.append("Script provenance from the validated report is incomplete")

        spoken_shorts = ShortsDurationValidator.spoken_text(shorts)
        actionable_false_preserved = (
            report.actionable is False
            and "actionable=false" not in spoken_shorts.casefold()
            and "立即買進" not in longform + shorts
            and "立即賣出" not in longform + shorts
        )
        if not actionable_false_preserved:
            errors.append("Actionable=false or non-spoken compliance boundary was not preserved")

        return EditorialValidation(
            status="FAIL" if errors else "PASS",
            report_candidate_sha256=sha256_bytes(
                canonical_json_bytes(report.model_dump(mode="json", by_alias=True))
            ),
            required_sections_present=required_sections_present,
            all_evidence_ids_resolve=all_evidence_ids_resolve,
            facts_and_inferences_separated=facts_and_inferences_separated,
            unsupported_numeric_claims_absent=unsupported_numeric_claims_absent,
            forbidden_intent_claims_absent=forbidden_intent_claims_absent,
            placeholders_absent=placeholders_absent,
            duplicate_sections_absent=duplicate_sections_absent,
            shorts_duration_passed=shorts_duration_passed,
            next_validation_evidence_bound=next_validation_evidence_bound,
            invalidation_condition_present=invalidation_condition_present,
            analysis_identity_preserved=analysis_identity_preserved,
            scripts_read_validated_report_only=scripts_read_validated_report_only,
            actionable_false_preserved=actionable_false_preserved,
            errors=errors,
            actionable=False,
        )
