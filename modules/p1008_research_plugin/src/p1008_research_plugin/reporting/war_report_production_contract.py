"""Executable adapter for the permanent Hon Hai 2317 war-report contract.

This module extends the existing G1 trigger and Phase B1 report pipeline.  It
does not fetch evidence, calculate ungoverned financial facts, publish, or
write authority state.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
import subprocess
from copy import deepcopy
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


class WarReportContractError(ValueError):
    """The permanent production contract cannot be satisfied safely."""


_CONTRACT_DIR = Path(__file__).resolve().parents[5] / "contracts" / "p1008_report_production" / "v1.1"
_CONTRACT_PATH = _CONTRACT_DIR / "P1008_WAR_REPORT_PRODUCTION_CONTRACT_V1.json"
_MATRIX_PATH = _CONTRACT_DIR / "P1008_REPORT_TRIGGER_SECTION_MATRIX_V1.json"
_TOKEN = re.compile(r"\{\{[A-Z0-9_]+\}\}")
_SECTION = re.compile(r'<section\s+id="(s\d+)"[^>]*>.*?<h2>(.*?)</h2>', re.DOTALL)
_EXTERNAL_ASSET = re.compile(
    r'<(?:script|link)\b[^>]*(?:src|href)="(?:https?:)?//|<img\b[^>]*src="(?!data:)',
    re.IGNORECASE,
)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WarReportContractError(f"CONTRACT_UNREADABLE:{path}") from exc
    if not isinstance(value, dict):
        raise WarReportContractError(f"CONTRACT_ROOT_INVALID:{path}")
    return value


def load_contract() -> dict[str, Any]:
    return _read_json(_CONTRACT_PATH)


def load_trigger_matrix() -> dict[str, Any]:
    return _read_json(_MATRIX_PATH)


def chapter_identity(contract: Mapping[str, Any] | None = None) -> tuple[tuple[str, str], ...]:
    value = contract or load_contract()
    chapters = value["chapter_contract"]["chapters"]
    return tuple((item["id"], item["title_zh"]) for item in chapters)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def _canonical_committed_text(path: Path, expected_sha256: str) -> bytes:
    package_root = _CONTRACT_DIR.parents[2]
    relative = path.relative_to(package_root).as_posix()
    result = subprocess.run(
        ["git", "-C", str(package_root), "show", f"HEAD:{relative}"],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0 or _sha256(result.stdout) != expected_sha256:
        raise WarReportContractError("MOTHER_TEMPLATE_HASH_MISMATCH")
    try:
        materialized = path.read_bytes()
    except OSError as exc:
        raise WarReportContractError("MOTHER_TEMPLATE_UNRESOLVED") from exc
    if materialized.replace(b"\r\n", b"\n") != result.stdout.replace(b"\r\n", b"\n"):
        raise WarReportContractError("MOTHER_TEMPLATE_HASH_MISMATCH")
    return result.stdout


def resolve_mother_template() -> str:
    contract = load_contract()
    template_contract = contract["template_contract"]
    path = _CONTRACT_DIR / template_contract["template_path"]
    try:
        raw = _canonical_committed_text(path, template_contract["template_sha256"])
        text = raw.decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise WarReportContractError("MOTHER_TEMPLATE_UNRESOLVED") from exc
    if '<article class="report"' not in text:
        raise WarReportContractError("MOTHER_TEMPLATE_ROOT_MISSING")
    actual = tuple((item[0], re.sub(r"^\d+｜", "", item[1]).strip()) for item in _SECTION.findall(text))
    if actual != chapter_identity(contract):
        raise WarReportContractError("MOTHER_TEMPLATE_CHAPTER_DRIFT")
    if "position:sticky" not in text or "@media print" not in text or "@media(max-width:900px)" not in text:
        raise WarReportContractError("MOTHER_TEMPLATE_LAYOUT_CONTRACT_MISSING")
    if _EXTERNAL_ASSET.search(text):
        raise WarReportContractError("MOTHER_TEMPLATE_NOT_SELF_CONTAINED")
    return text


def validate_contract() -> None:
    contract = load_contract()
    matrix = load_trigger_matrix()
    triggers = tuple(contract["valid_triggers"])
    if triggers != ("MONTHLY_REVENUE", "QUARTERLY_EARNINGS", "MAJOR_EVENT"):
        raise WarReportContractError("VALID_TRIGGER_DRIFT")
    if "DAILY" not in contract["invalid_formal_triggers"]:
        raise WarReportContractError("DAILY_FORMAL_REPORT_NOT_BLOCKED")
    chapters = chapter_identity(contract)
    if len(chapters) != 11 or tuple(item[0] for item in chapters) != tuple(f"s{i}" for i in range(1, 12)):
        raise WarReportContractError("CHAPTER_CONTRACT_INVALID")
    if tuple(matrix["chapter_ids"]) != tuple(item[0] for item in chapters):
        raise WarReportContractError("TRIGGER_MATRIX_CHAPTER_DRIFT")
    if set(matrix["triggers"]) != set(triggers):
        raise WarReportContractError("TRIGGER_MATRIX_EVENT_DRIFT")
    decision = contract["decision_contract"]
    if decision["dimension_count"] != 3 or len(decision["dimensions"]) != 3:
        raise WarReportContractError("DECISION_DIMENSION_DRIFT")
    if contract["publication_policy"]["automatic_publication"] is not False:
        raise WarReportContractError("AUTOMATIC_PUBLICATION_NOT_BLOCKED")
    resolve_mother_template()


def plan_trigger(trigger: str | None, impacted_chapters: Iterable[str] = ()) -> dict[str, Any]:
    contract = load_contract()
    matrix = load_trigger_matrix()
    if trigger not in contract["valid_triggers"]:
        return deepcopy(contract["no_valid_trigger_behavior"])
    route = deepcopy(matrix["triggers"][trigger])
    route.update({
        "trigger": trigger,
        "state": "FORMAL_REPORT_CANDIDATE_ALLOWED",
        "formal_report_generated": True,
        "render_chapters": [item[0] for item in chapter_identity(contract)],
        "automatic_publication": False,
        "owner_review_required": True,
    })
    if trigger == "MAJOR_EVENT":
        impacted = tuple(dict.fromkeys(impacted_chapters))
        allowed = set(route["render_chapters"])
        if not impacted or not set(impacted).issubset(allowed):
            raise WarReportContractError("MAJOR_EVENT_IMPACT_PATH_REQUIRED")
        route["impacted_chapters"] = list(impacted)
        route["unchanged_chapters"] = [item for item in route["render_chapters"] if item not in impacted]
    return route


def append_full_history(
    existing: Sequence[Mapping[str, Any]], new_observation: Mapping[str, Any], *, period_key: str = "period"
) -> list[dict[str, Any]]:
    before = [dict(item) for item in existing]
    period = new_observation.get(period_key)
    if not isinstance(period, str) or not period:
        raise WarReportContractError("HISTORY_PERIOD_REQUIRED")
    if any(item.get(period_key) == period for item in before):
        raise WarReportContractError("HISTORY_PERIOD_COLLISION")
    result = before + [dict(new_observation)]
    if [item.get(period_key) for item in result] != sorted(item.get(period_key) for item in result):
        raise WarReportContractError("HISTORY_NOT_CHRONOLOGICAL")
    return result


def recent_zoom(full_history: Sequence[Mapping[str, Any]], periods: int) -> list[dict[str, Any]]:
    if periods not in {8, 12}:
        raise WarReportContractError("UNAPPROVED_HISTORY_ZOOM")
    return deepcopy([dict(item) for item in full_history[-periods:]])


def resolve_quarterly_roic(
    *, official_same_basis_quarterly: float | None, third_party_ttm: float | None = None
) -> dict[str, Any]:
    del third_party_ttm  # explicitly excluded from the quarterly result
    if official_same_basis_quarterly is None:
        return {"basis": "QUARTERLY", "value": None, "status": "PENDING_OR_UNAVAILABLE"}
    return {"basis": "QUARTERLY", "value": official_same_basis_quarterly, "status": "AVAILABLE"}


def _main_prose(rendered_html: str) -> str:
    match = re.search(r'<main>(.*?)<section\s+id="s11"', rendered_html, re.DOTALL | re.IGNORECASE)
    return re.sub(r"<[^>]+>", " ", match.group(1) if match else rendered_html)


def validate_reader_html(rendered_html: str) -> None:
    contract = load_contract()
    actual = tuple((item[0], re.sub(r"^\d+｜", "", item[1]).strip()) for item in _SECTION.findall(rendered_html))
    if actual != chapter_identity(contract):
        raise WarReportContractError("CHAPTER_COUNT_OR_ORDER_CHANGED")
    prose = html.unescape(_main_prose(rendered_html)).casefold()
    for forbidden in contract["reader_language_contract"]["forbidden_main_prose_terms"]:
        if forbidden.casefold() in prose:
            raise WarReportContractError(f"INTERNAL_TERM_LEAK:{forbidden}")
    if _EXTERNAL_ASSET.search(rendered_html):
        raise WarReportContractError("REPORT_NOT_SELF_CONTAINED")


def render_owner_review_candidate(
    *, report_title: str, headline: str, deck: str, eyebrow: str, report_meta: str,
    chapter_html: Mapping[str, str], footer: str,
) -> str:
    template = resolve_mother_template()
    expected = [item[0] for item in chapter_identity()]
    if tuple(chapter_html) != tuple(expected):
        raise WarReportContractError("CHAPTER_COUNT_OR_ORDER_CHANGED")
    substitutions = {
        "REPORT_TITLE": html.escape(report_title), "HEADLINE": html.escape(headline),
        "DECK": html.escape(deck), "EYEBROW": html.escape(eyebrow),
        "REPORT_META": html.escape(report_meta), "FOOTER": html.escape(footer),
        **{f"CHAPTER_{index:02d}": chapter_html[chapter] for index, chapter in enumerate(expected, 1)},
    }
    rendered = template
    for token, value in substitutions.items():
        rendered = rendered.replace("{{" + token + "}}", value)
    if _TOKEN.search(rendered):
        raise WarReportContractError("MOTHER_TEMPLATE_SLOT_UNRESOLVED")
    validate_reader_html(rendered)
    return rendered
