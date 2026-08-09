"""Deterministic, non-executing governance boundary for a pinned research skill.

This module deliberately contains no provider client, credential loader, retry
loop, fallback, filesystem reader, or network operation.  It turns an already
governed report-trigger decision into a narrowly scoped *future* skill request,
then validates canned responses before they can become Discovery candidates.
"""

from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import re
from typing import Any, Mapping, Sequence
from urllib.parse import urlsplit

from ..phaseb1_common import canonical_json_bytes, sha256_bytes


class ResearchSkillGovernanceError(ValueError):
    """Raised when a future research-skill operation cannot be proven safe."""


PINNED_SKILL_IDENTITY = {
    "skill_name": "AnySearch Skill",
    "vendor": "AnySearch",
    "repository": "anysearch-ai/anysearch-skill",
    # The tag is descriptive only.  The immutable commit and acquired artifact
    # digest are the governing supply-chain identity.
    "tag": "v2.1.0",
    "commit_sha": "6ff6aa958ad9747659d669b5e9984f07c896f2aa",
    "artifact_sha256": "C98E3B5401E8407F9B52B3E03A2554AF30E849E6DE11160A967531B48E4AD031",
}
PROVIDER_ENDPOINT_IDENTITY = "https://api.anysearch.com/mcp"
MAX_ATTEMPTS = 1
AUTH_MODES = frozenset({"NONE", "OWNER_SUPPLIED_RUNTIME_SECRET"})
COMMAND_MAP = {
    "SEARCH": "search",
    "GET_SUB_DOMAINS": "get_sub_domains",
    "EXTRACT_PUBLIC_URL": "extract",
}
FAILURE_CODES = frozenset({
    "SUCCESS",
    "SUCCESS_NO_RELEVANT_RESULT",
    "HTTP_403_POLICY_BLOCKED",
    "AUTH_REQUIRED",
    "RATE_LIMITED",
    "TIMEOUT_TRANSIENT",
    "SOURCE_FAILED",
    "MALFORMED_RESPONSE",
    "PROVENANCE_INCOMPLETE",
    "COMMAND_NOT_ALLOWED",
    "QUERY_POLICY_BLOCKED",
    "URL_POLICY_BLOCKED",
})
_REPORT_KEY = re.compile(r"^P1008_[A-Z0-9_:-]+$")
_SHA256 = re.compile(r"^[A-F0-9]{64}$")
_FORBIDDEN_QUERY = re.compile(
    r"(?:\bdata/|\brules/|\bruntime/|\.sqlite(?:3)?\b|\bhold\b|\bmidr\b|\bmrd\b|"
    r"api[_ -]?key\b|\btoken\b|\bpassword\b|\benv(?:ironment)?\b|\.env\b|"
    r"(?:[A-Za-z]:\\)|(?:^|\s)\\\\|\bfile://|\bowner private|\bprivate annotation)",
    re.IGNORECASE,
)
_FORBIDDEN_COMMAND_TERMS = re.compile(
    r"(?:batch_search|generate\.py|@\S+|\.env\b|auto[_ -]?register|key[_ -]?gen|"
    r"retry|fallback|write[_ -]?mode|state[_ -]?mutation)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class RawSkillResponse:
    """A captured provider payload; explicitly not a P1008 evidence record."""

    skill_call_id: str
    command: str
    retrieved_at_utc: str
    payload: Mapping[str, Any]

    @property
    def raw_response_hash(self) -> str:
        return sha256_bytes(canonical_json_bytes(dict(self.payload)))


def _required(value: Mapping[str, Any], *fields: str) -> None:
    missing = [field for field in fields if value.get(field) in (None, "")]
    if missing:
        raise ResearchSkillGovernanceError(
            f"Missing governed research-skill fields: {', '.join(missing)}"
        )


def _false(value: Mapping[str, Any], field: str = "actionable") -> None:
    if value.get(field) is not False:
        raise ResearchSkillGovernanceError(f"{field} must be false")


def _validate_report_identity(report_key: str, revision: int) -> None:
    if not isinstance(report_key, str) or not _REPORT_KEY.fullmatch(report_key):
        raise ResearchSkillGovernanceError("Invalid stable report_key")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        raise ResearchSkillGovernanceError("revision must be an integer >= 1")


def validate_skill_identity(identity: Mapping[str, Any]) -> dict[str, str]:
    """Reject frontmatter or caller metadata that differs from the pinned artifact."""

    if any(identity.get(field) != value for field, value in PINNED_SKILL_IDENTITY.items()):
        raise ResearchSkillGovernanceError("Pinned research-skill identity mismatch")
    return dict(PINNED_SKILL_IDENTITY)


def evaluate_invocation_eligibility(trigger_decision: Mapping[str, Any]) -> dict[str, Any]:
    """Permit at most one future call only after the G1 trigger is already valid."""

    _false(trigger_decision)
    report_key = trigger_decision.get("report_key")
    revision = trigger_decision.get("revision")
    try:
        _validate_report_identity(report_key, revision)
    except ResearchSkillGovernanceError:
        return {
            "eligible": False, "skill_calls": 0, "status": "FAIL_CLOSED",
            "failure_code": "SOURCE_FAILED", "actionable": False,
        }
    canonical_trigger = dict(trigger_decision)
    supplied_decision_id = canonical_trigger.pop("decision_id", None)
    verified_trigger_identity = isinstance(supplied_decision_id, str) and supplied_decision_id == (
        "TRIGGER-" + sha256_bytes(canonical_json_bytes(canonical_trigger))[:16]
    )
    valid = (
        trigger_decision.get("material_event_confirmed") is True
        and trigger_decision.get("report_trigger_valid") is True
        and trigger_decision.get("decision") == "TRIGGERED_INTERNAL_REPORT"
        and verified_trigger_identity
    )
    conflict = trigger_decision.get("authority_conflict") is True or trigger_decision.get("conflict_detected") is True
    if not valid or conflict:
        return {
            "eligible": False, "skill_calls": 0, "status": "NOT_ELIGIBLE",
            "failure_code": "SOURCE_FAILED", "actionable": False,
        }
    return {
        "eligible": True, "skill_calls": 1, "status": "ELIGIBLE",
        "failure_code": None, "actionable": False,
    }


def sanitize_query(query: str) -> str:
    """Accept only minimal public research terms; never concatenate P1008 context."""

    if not isinstance(query, str) or not query.strip() or len(query) > 512:
        raise ResearchSkillGovernanceError("QUERY_POLICY_BLOCKED")
    normalized = " ".join(query.split())
    if _FORBIDDEN_QUERY.search(normalized) or _FORBIDDEN_COMMAND_TERMS.search(normalized):
        raise ResearchSkillGovernanceError("QUERY_POLICY_BLOCKED")
    return normalized


def validate_public_extract_url(url: str, *, resolved_ip_addresses: Sequence[str]) -> str:
    """Validate a public HTTP(S) extraction target using caller-supplied DNS proof.

    DNS resolution is intentionally not performed here.  A later, separately
    authorized runtime must supply one or more observed resolved IP addresses;
    missing or private/ambiguous resolution fails closed before extraction.
    """

    if not isinstance(url, str) or not url or url.startswith("\\\\"):
        raise ResearchSkillGovernanceError("URL_POLICY_BLOCKED")
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ResearchSkillGovernanceError("URL_POLICY_BLOCKED")
    host = parsed.hostname.rstrip(".").lower()
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
        raise ResearchSkillGovernanceError("URL_POLICY_BLOCKED")
    if not isinstance(resolved_ip_addresses, Sequence) or isinstance(resolved_ip_addresses, (str, bytes)) or not resolved_ip_addresses:
        raise ResearchSkillGovernanceError("URL_POLICY_BLOCKED")
    try:
        addresses = [ipaddress.ip_address(value) for value in resolved_ip_addresses]
    except ValueError as exc:
        raise ResearchSkillGovernanceError("URL_POLICY_BLOCKED") from exc
    if any(not address.is_global for address in addresses):
        raise ResearchSkillGovernanceError("URL_POLICY_BLOCKED")
    return parsed.geturl()


def build_skill_request(
    *,
    trigger_decision: Mapping[str, Any],
    report_key: str,
    revision: int,
    event_reference: str,
    command: str,
    query: str | None,
    target_url: str | None = None,
    resolved_ip_addresses: Sequence[str] = (),
    auth_mode: str = "NONE",
    max_attempts: int = MAX_ATTEMPTS,
    fallback_enabled: bool = False,
) -> dict[str, Any]:
    """Build a non-executing, credential-free request for the pinned skill."""

    _validate_report_identity(report_key, revision)
    _required({"event_reference": event_reference}, "event_reference")
    if auth_mode not in AUTH_MODES or max_attempts != MAX_ATTEMPTS or fallback_enabled is not False:
        raise ResearchSkillGovernanceError("SKILL_COMMAND_NOT_ALLOWED")
    eligibility = evaluate_invocation_eligibility(trigger_decision)
    if not eligibility["eligible"]:
        raise ResearchSkillGovernanceError("SKILL_INVOCATION_NOT_ELIGIBLE")
    if trigger_decision.get("report_key") != report_key or trigger_decision.get("revision") != revision:
        raise ResearchSkillGovernanceError("Trigger report identity mismatch")
    if command not in COMMAND_MAP:
        raise ResearchSkillGovernanceError("SKILL_COMMAND_NOT_ALLOWED")
    normalized_query: str | None = None
    normalized_target: str | None = None
    if command == "EXTRACT_PUBLIC_URL":
        if query is not None:
            raise ResearchSkillGovernanceError("QUERY_POLICY_BLOCKED")
        normalized_target = validate_public_extract_url(
            target_url or "", resolved_ip_addresses=resolved_ip_addresses
        )
    else:
        if target_url is not None:
            raise ResearchSkillGovernanceError("URL_POLICY_BLOCKED")
        normalized_query = sanitize_query(query or "")
    request_seed = {
        "report_key": report_key, "revision": revision, "event_reference": event_reference,
        "trigger_receipt_reference": trigger_decision["decision_id"], "command": command,
        "normalized_query": normalized_query, "target_url": normalized_target,
    }
    skill_call_id = "SKILL-" + sha256_bytes(canonical_json_bytes(request_seed))[:16]
    return {
        "skill_call_id": skill_call_id, **dict(PINNED_SKILL_IDENTITY),
        "report_key": report_key, "revision": revision, "event_reference": event_reference,
        "trigger_receipt_reference": trigger_decision["decision_id"],
        "command": command, "provider_command": COMMAND_MAP[command],
        "normalized_query": normalized_query,
        "normalized_query_hash": sha256_bytes(canonical_json_bytes(normalized_query)) if normalized_query else None,
        "target_url": normalized_target,
        "target_url_hash": sha256_bytes(canonical_json_bytes(normalized_target)) if normalized_target else None,
        "auth_mode": auth_mode, "max_attempts": MAX_ATTEMPTS, "fallback_enabled": False,
        "provider_endpoint_identity": PROVIDER_ENDPOINT_IDENTITY, "actionable": False,
    }


def capture_raw_skill_response(
    *, skill_request: Mapping[str, Any], payload: Mapping[str, Any], retrieved_at_utc: str
) -> RawSkillResponse:
    """Capture canned output identity only; this neither executes nor trusts a provider."""

    validate_skill_identity(skill_request)
    _required(skill_request, "skill_call_id", "command")
    if skill_request.get("command") not in COMMAND_MAP:
        raise ResearchSkillGovernanceError("COMMAND_NOT_ALLOWED")
    if not isinstance(payload, Mapping) or not isinstance(retrieved_at_utc, str) or not retrieved_at_utc:
        raise ResearchSkillGovernanceError("MALFORMED_RESPONSE")
    return RawSkillResponse(
        skill_call_id=str(skill_request["skill_call_id"]),
        command=str(skill_request["command"]),
        retrieved_at_utc=retrieved_at_utc,
        payload=dict(payload),
    )


def build_skill_call_receipt(
    *, skill_request: Mapping[str, Any], raw_response: RawSkillResponse | None,
    started_at_utc: str, completed_at_utc: str, failure_code: str,
) -> dict[str, Any]:
    """Create a secret-free receipt for a future single-attempt provider call."""

    validate_skill_identity(skill_request)
    _required(skill_request, "skill_call_id", "report_key", "revision", "event_reference", "trigger_receipt_reference", "command")
    _false(skill_request)
    if failure_code not in FAILURE_CODES:
        raise ResearchSkillGovernanceError("Unknown controlled failure code")
    if raw_response is not None and raw_response.skill_call_id != skill_request["skill_call_id"]:
        raise ResearchSkillGovernanceError("Raw response call identity mismatch")
    result_count: int | None = None
    if raw_response is not None and isinstance(raw_response.payload.get("results"), list):
        result_count = len(raw_response.payload["results"])
    status = "SUCCESS" if failure_code in {"SUCCESS", "SUCCESS_NO_RELEVANT_RESULT"} else "FAIL_CLOSED"
    return {
        "skill_call_id": skill_request["skill_call_id"], **dict(PINNED_SKILL_IDENTITY),
        "report_key": skill_request["report_key"], "revision": skill_request["revision"],
        "event_reference": skill_request["event_reference"],
        "trigger_receipt_reference": skill_request["trigger_receipt_reference"],
        "command": skill_request["command"],
        "normalized_query_hash": skill_request.get("normalized_query_hash"),
        "target_url_hash": skill_request.get("target_url_hash"),
        "started_at_utc": started_at_utc, "completed_at_utc": completed_at_utc,
        "status": status, "attempt_count": MAX_ATTEMPTS,
        "provider_endpoint_identity": PROVIDER_ENDPOINT_IDENTITY,
        "raw_response_hash": raw_response.raw_response_hash if raw_response else None,
        "result_count": result_count, "failure_code": failure_code,
        "actionable": False,
    }


def build_discovery_evidence_candidate(
    *, raw_response: RawSkillResponse, result: Mapping[str, Any],
    source_tier_assigned_by_policy: str = "UNVERIFIED",
    source_locator_verified: bool = False,
) -> dict[str, Any]:
    """Qualify one response item as Discovery only, never as authority evidence."""

    if not isinstance(result, Mapping):
        raise ResearchSkillGovernanceError("PROVENANCE_INCOMPLETE")
    required = ("source_id", "source_locator", "source_type", "source_hash", "content_hash")
    if any(result.get(field) in (None, "") for field in required):
        raise ResearchSkillGovernanceError("PROVENANCE_INCOMPLETE")
    if not isinstance(result["source_locator"], str) or not result["source_locator"].strip() or source_locator_verified is not True:
        raise ResearchSkillGovernanceError("PROVENANCE_INCOMPLETE")
    if source_tier_assigned_by_policy not in {"UNVERIFIED", "MEDIA", "OFFICIAL", "PUBLIC_MARKET", "CSV_AUTHORITY", "OWNER_NOTE"}:
        raise ResearchSkillGovernanceError("PROVENANCE_INCOMPLETE")
    if not all(isinstance(result[field], str) and _SHA256.fullmatch(result[field]) for field in ("source_hash", "content_hash")):
        raise ResearchSkillGovernanceError("PROVENANCE_INCOMPLETE")
    if result["source_hash"] == raw_response.raw_response_hash:
        raise ResearchSkillGovernanceError("PROVENANCE_INCOMPLETE")
    chain = result.get("originating_chain_id")
    independence = "INDEPENDENCE_UNRESOLVED" if not isinstance(chain, str) or not chain else "UNVERIFIED"
    return {
        "raw_response_hash": raw_response.raw_response_hash,
        "skill_call_id": raw_response.skill_call_id,
        "provider": PINNED_SKILL_IDENTITY["vendor"],
        "command": raw_response.command, "retrieved_at_utc": raw_response.retrieved_at_utc,
        "source_id": result["source_id"], "source_locator": result["source_locator"],
        "source_type": result["source_type"], "source_class": "DISCOVERY",
        "source_tier": source_tier_assigned_by_policy,
        "source_hash": result["source_hash"], "content_hash": result["content_hash"],
        "originating_chain_id": chain if independence == "UNVERIFIED" else None,
        "independence_status": independence,
        "provider_confidence_advisory": result.get("provider_confidence"),
        "core_view_changed": False, "publication_ready": False,
        "published_externally": False, "actionable": False,
    }


THESIS_EVOLUTION_CONTRACT_STATUS = "THESIS_EVOLUTION_CONTRACT_DEFERRED"
