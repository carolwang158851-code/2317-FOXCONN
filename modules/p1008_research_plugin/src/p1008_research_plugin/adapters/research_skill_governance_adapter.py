"""Deterministic, non-executing governance boundary for a pinned research skill.

This module deliberately contains no provider client, credential loader, retry
loop, fallback, filesystem reader, or network operation.  It turns an already
governed report-trigger decision into a narrowly scoped *future* skill request,
then validates canned responses before they can become Discovery candidates.
"""

from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import json
import re
from typing import Any, Callable, Mapping
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
import weakref

from ..phaseb1_common import canonical_json_bytes, sha256_bytes


class ResearchSkillGovernanceError(ValueError):
    """Raised when a future research-skill operation cannot be proven safe."""


PINNED_SKILL_IDENTITY = {
    "provider_id": "ANYSEARCH",
    "skill_name": "AnySearch Skill",
    "vendor": "AnySearch",
    "repository": "anysearch-ai/anysearch-skill",
    "distribution_source": "anysearch-ai/anysearch-skill",
    # The tag is descriptive only.  The immutable commit and acquired artifact
    # digest are the governing supply-chain identity.
    "tag": "v3.0.1",
    "release_version": "v3.0.1",
    "commit_sha": "caed9eac2eb6e869b89faa2f3e92d8956b013b56",
    "immutable_source_revision": "caed9eac2eb6e869b89faa2f3e92d8956b013b56",
    "artifact_sha256": "1F42E68ECC290EDB224050D2BD4F80E7068F5AFC0FA3DC8076E6E22412334743",
    "acquired_at_utc": "2026-08-09T05:44:45Z",
    "allowed_endpoint_identities": ("https://api.anysearch.com/mcp",),
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
    "EXTRACT_RUNTIME_VALIDATION_REQUIRED",
})
_REPORT_KEY = re.compile(r"^P1008_[A-Z0-9_:-]+$")
_SHA256 = re.compile(r"^[A-F0-9]{64}$")
_FORBIDDEN_QUERY = re.compile(
    r"(?:\b(?:data|rules|runtime)/|(?:^|[\s@])(?:\.?\.?/)+(?:data|rules|runtime)/|"
    r"(?:^|[\s@])[a-z]:/|(?:^|[\s@])//|\.sqlite(?:3)?\b|\bhold\b|\bmidr\b|\bmrd\b|"
    r"api[_ -]?key\b|\btoken\b|\bpassword\b|\benv(?:ironment)?\b|\.env\b|"
    r"\bfile:/|\bowner private|\bprivate annotation)",
    re.IGNORECASE,
)
_FORBIDDEN_COMMAND_TERMS = re.compile(
    r"(?:batch_search|generate\.py|@\S+|\.env\b|auto[_ -]?register|key[_ -]?gen|"
    r"retry|fallback|write[_ -]?mode|state[_ -]?mutation)",
    re.IGNORECASE,
)
_SECRET_LOCATOR_KEYS = frozenset({
    "sig", "signature", "session", "code", "jwt", "token", "access_token",
    "api_key", "key", "auth", "authorization", "credential", "secret",
})


@dataclass(frozen=True)
class RawSkillResponse:
    """A captured provider payload; explicitly not a P1008 evidence record."""

    skill_call_id: str
    command: str
    retrieved_at_utc: str
    canonical_payload_json: str
    raw_response_hash: str

    def decoded_payload(self) -> Mapping[str, Any]:
        """Return a fresh decoded view; it cannot change the captured identity."""

        value = json.loads(self.canonical_payload_json)
        if not isinstance(value, dict):
            raise ResearchSkillGovernanceError("MALFORMED_RESPONSE")
        return value

    @property
    def result_count(self) -> int | None:
        results = self.decoded_payload().get("results")
        return len(results) if isinstance(results, list) else None


@dataclass(frozen=True, eq=False, init=False)
class ValidatedResearchSkillTrigger:
    """Opaque in-process capability minted only after G1-I2 handoff validation.

    ``decision_id`` is a canonical identity reference, not an authentication
    token.  Membership in the private mint registry proves only that the
    existing G1-I2 validator accepted the handoff in this process.
    """

    report_key: str
    revision: int
    event_type: str
    decision_id: str
    receipt_id: str
    event_reference: str
    event_fingerprint: str
    issuance_receipt_id: str
    issuance_receipt_hash: str
    producer_id: str
    run_id: str
    material_event_confirmed: bool
    report_trigger_valid: bool
    actionable: bool
    authority_conflict: bool
    policy_status: str
    _consume_callback: Callable[[], None]

    def __init__(self) -> None:
        raise TypeError(
            "ValidatedResearchSkillTrigger must be minted by the G1-I2 validator"
        )


_VALIDATED_RESEARCH_TRIGGER_STATES: weakref.WeakKeyDictionary[ValidatedResearchSkillTrigger, str] = weakref.WeakKeyDictionary()


def _mint_validated_research_skill_trigger(
    *,
    report_key: str,
    revision: int,
    event_type: str,
    decision_id: str,
    receipt_id: str,
    event_reference: str,
    event_fingerprint: str,
    issuance_receipt_id: str,
    issuance_receipt_hash: str,
    producer_id: str,
    run_id: str,
    material_event_confirmed: bool,
    report_trigger_valid: bool,
    actionable: bool,
    authority_conflict: bool,
    policy_status: str,
    consume_callback: Callable[[], None],
) -> ValidatedResearchSkillTrigger:
    """Mint the capability for the verified G1-I2 validator only.

    This intentionally has no Mapping/JSON convenience constructor: raw
    caller data must pass the existing G1-I2 handoff validator before the
    capability exists.
    """

    _validate_report_identity(report_key, revision)
    if not all(isinstance(value, str) and value for value in (
        event_type, decision_id, receipt_id, event_reference, event_fingerprint,
        issuance_receipt_id, issuance_receipt_hash, producer_id, run_id, policy_status,
    )):
        raise ResearchSkillGovernanceError("TRUSTED_TRIGGER_MINT_INVALID")
    if not re.fullmatch(r"[A-F0-9]{64}", event_fingerprint) or not re.fullmatch(r"[A-F0-9]{64}", issuance_receipt_hash):
        raise ResearchSkillGovernanceError("TRUSTED_TRIGGER_MINT_INVALID")
    if not all(isinstance(value, bool) for value in (
        material_event_confirmed, report_trigger_valid, actionable, authority_conflict,
    )):
        raise ResearchSkillGovernanceError("TRUSTED_TRIGGER_MINT_INVALID")
    if not callable(consume_callback):
        raise ResearchSkillGovernanceError("TRUSTED_TRIGGER_MINT_INVALID")
    capability = object.__new__(ValidatedResearchSkillTrigger)
    for name, value in {
        "report_key": report_key,
        "revision": revision,
        "event_type": event_type,
        "decision_id": decision_id,
        "receipt_id": receipt_id,
        "event_reference": event_reference,
        "event_fingerprint": event_fingerprint,
        "issuance_receipt_id": issuance_receipt_id,
        "issuance_receipt_hash": issuance_receipt_hash,
        "producer_id": producer_id,
        "run_id": run_id,
        "material_event_confirmed": material_event_confirmed,
        "report_trigger_valid": report_trigger_valid,
        "actionable": actionable,
        "authority_conflict": authority_conflict,
        "policy_status": policy_status,
        "_consume_callback": consume_callback,
    }.items():
        object.__setattr__(capability, name, value)
    _VALIDATED_RESEARCH_TRIGGER_STATES[capability] = "ISSUED"
    return capability


def _is_validated_research_skill_trigger(value: object) -> bool:
    return isinstance(value, ValidatedResearchSkillTrigger) and value in _VALIDATED_RESEARCH_TRIGGER_STATES


def consume_validated_research_skill_trigger(value: object) -> None:
    """Consume one indexed capability immediately before provider execution."""

    if not _is_validated_research_skill_trigger(value):
        raise ResearchSkillGovernanceError("SKILL_INVOCATION_NOT_ELIGIBLE")
    assert isinstance(value, ValidatedResearchSkillTrigger)
    if _VALIDATED_RESEARCH_TRIGGER_STATES.get(value) != "ISSUED":
        raise ResearchSkillGovernanceError("SKILL_AUTHORIZATION_ALREADY_CONSUMED")
    value._consume_callback()
    _VALIDATED_RESEARCH_TRIGGER_STATES[value] = "CONSUMED"


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


def evaluate_invocation_eligibility(validated_trigger: object) -> dict[str, Any]:
    """Permit one future call only through a validated G1-I2 capability.

    Canonical decision identity proves representation integrity only.  Raw
    Mapping/JSON data, including a self-consistent decision ID or receipt, is
    never accepted as invocation authority.
    """

    if not _is_validated_research_skill_trigger(validated_trigger):
        return {
            "eligible": False, "skill_calls": 0, "status": "NOT_ELIGIBLE",
            "failure_code": "SOURCE_FAILED", "actionable": False,
        }
    valid = (
        _VALIDATED_RESEARCH_TRIGGER_STATES.get(validated_trigger) == "ISSUED"
        and validated_trigger.material_event_confirmed is True
        and validated_trigger.report_trigger_valid is True
        and validated_trigger.actionable is False
        and validated_trigger.policy_status == "PASS"
    )
    if not valid or validated_trigger.authority_conflict:
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
    normalized = " ".join(unicodedata.normalize("NFKC", query).split())
    policy_view = normalized.translate(str.maketrans({"\\": "/"}))
    if _FORBIDDEN_QUERY.search(policy_view) or _FORBIDDEN_COMMAND_TERMS.search(policy_view):
        raise ResearchSkillGovernanceError("QUERY_POLICY_BLOCKED")
    return normalized


def _validate_discovery_locator(locator: object) -> str:
    """Establish syntax only; this is not source or DNS authenticity proof."""

    if not isinstance(locator, str) or not locator or locator.startswith("\\\\") or locator.startswith("//"):
        raise ResearchSkillGovernanceError("PROVENANCE_INCOMPLETE")
    parsed = urlsplit(locator)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ResearchSkillGovernanceError("PROVENANCE_INCOMPLETE")
    host = parsed.hostname.rstrip(".").lower()
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
        raise ResearchSkillGovernanceError("PROVENANCE_INCOMPLETE")
    try:
        literal = ipaddress.ip_address(host)
    except ValueError as exc:
        # A DNS hostname may be syntactically public, but is deliberately not
        # claimed DNS-verified in this deterministic, non-network phase.
        if "." not in host:
            raise ResearchSkillGovernanceError("PROVENANCE_INCOMPLETE") from exc
        return parsed.geturl()
    if not literal.is_global:
        raise ResearchSkillGovernanceError("PROVENANCE_INCOMPLETE")
    return parsed.geturl()


def sanitize_source_locator(locator: object) -> str:
    """Strip userinfo and secret-bearing query parameters before capture."""

    if not isinstance(locator, str) or not locator:
        raise ResearchSkillGovernanceError("PROVENANCE_INCOMPLETE")
    parsed = urlsplit(locator)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise ResearchSkillGovernanceError("PROVENANCE_INCOMPLETE")
    host = parsed.hostname
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    try:
        port = parsed.port
    except ValueError as exc:
        raise ResearchSkillGovernanceError("PROVENANCE_INCOMPLETE") from exc
    netloc = host if port is None else f"{host}:{port}"
    query = urlencode([
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key.casefold() not in _SECRET_LOCATOR_KEYS
    ], doseq=True)
    return _validate_discovery_locator(
        urlunsplit((parsed.scheme.lower(), netloc, parsed.path, query, ""))
    )


def validate_skill_request_authorization(
    skill_request: Mapping[str, Any], validated_trigger: object
) -> ValidatedResearchSkillTrigger:
    """Bind a request to the live opaque capability that created its context."""

    if not _is_validated_research_skill_trigger(validated_trigger):
        raise ResearchSkillGovernanceError("SKILL_INVOCATION_NOT_ELIGIBLE")
    assert isinstance(validated_trigger, ValidatedResearchSkillTrigger)
    if not evaluate_invocation_eligibility(validated_trigger)["eligible"]:
        raise ResearchSkillGovernanceError("SKILL_INVOCATION_NOT_ELIGIBLE")
    expected = {
        "report_key": validated_trigger.report_key,
        "revision": validated_trigger.revision,
        "event_reference": validated_trigger.event_reference,
        "trigger_receipt_reference": validated_trigger.issuance_receipt_id,
        "trigger_decision_id": validated_trigger.decision_id,
        "trigger_receipt_hash": validated_trigger.issuance_receipt_hash,
        "actionable": False,
    }
    if any(skill_request.get(field) != value for field, value in expected.items()):
        raise ResearchSkillGovernanceError("SKILL_AUTHORIZATION_CONTEXT_MISMATCH")
    return validated_trigger


def build_skill_request(
    *,
    validated_trigger: ValidatedResearchSkillTrigger,
    report_key: str,
    revision: int,
    event_reference: str,
    command: str,
    query: str | None,
    target_url: str | None = None,
    auth_mode: str = "NONE",
    max_attempts: int = MAX_ATTEMPTS,
    fallback_enabled: bool = False,
) -> dict[str, Any]:
    """Build a non-executing, credential-free request for the pinned skill."""

    _validate_report_identity(report_key, revision)
    _required({"event_reference": event_reference}, "event_reference")
    if auth_mode not in AUTH_MODES or max_attempts != MAX_ATTEMPTS or fallback_enabled is not False:
        raise ResearchSkillGovernanceError("SKILL_COMMAND_NOT_ALLOWED")
    eligibility = evaluate_invocation_eligibility(validated_trigger)
    if not eligibility["eligible"]:
        raise ResearchSkillGovernanceError("SKILL_INVOCATION_NOT_ELIGIBLE")
    if (
        validated_trigger.report_key != report_key
        or validated_trigger.revision != revision
        or validated_trigger.event_reference != event_reference
    ):
        raise ResearchSkillGovernanceError("Trigger report identity mismatch")
    if command not in COMMAND_MAP:
        raise ResearchSkillGovernanceError("SKILL_COMMAND_NOT_ALLOWED")
    normalized_query: str | None = None
    normalized_target: str | None = None
    if command == "EXTRACT_PUBLIC_URL":
        # The future provider would resolve the hostname itself.  Because this
        # phase cannot bind request-time DNS resolution to that provider fetch,
        # extraction remains unavailable rather than trusting caller evidence.
        raise ResearchSkillGovernanceError("EXTRACT_RUNTIME_VALIDATION_REQUIRED")
    else:
        if target_url is not None:
            raise ResearchSkillGovernanceError("URL_POLICY_BLOCKED")
        normalized_query = sanitize_query(query or "")
    request_seed = {
        "report_key": report_key, "revision": revision, "event_reference": event_reference,
        "trigger_receipt_reference": validated_trigger.issuance_receipt_id,
        "trigger_decision_id": validated_trigger.decision_id,
        "trigger_receipt_hash": validated_trigger.issuance_receipt_hash,
        "command": command,
        "normalized_query": normalized_query, "target_url": normalized_target,
    }
    skill_call_id = "SKILL-" + sha256_bytes(canonical_json_bytes(request_seed))[:16]
    return {
        "skill_call_id": skill_call_id, **dict(PINNED_SKILL_IDENTITY),
        "report_key": report_key, "revision": revision, "event_reference": event_reference,
        "trigger_receipt_reference": validated_trigger.issuance_receipt_id,
        "trigger_decision_id": validated_trigger.decision_id,
        "trigger_receipt_hash": validated_trigger.issuance_receipt_hash,
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
    canonical_payload = canonical_json_bytes(dict(payload)).decode("utf-8")
    return RawSkillResponse(
        skill_call_id=str(skill_request["skill_call_id"]),
        command=str(skill_request["command"]),
        retrieved_at_utc=retrieved_at_utc,
        canonical_payload_json=canonical_payload,
        raw_response_hash=sha256_bytes(canonical_payload.encode("utf-8")),
    )


def build_skill_call_receipt(
    *, skill_request: Mapping[str, Any], raw_response: RawSkillResponse | None,
    started_at_utc: str, completed_at_utc: str, failure_code: str,
) -> dict[str, Any]:
    """Build a secret-free receipt for a future single-attempt provider call."""

    validate_skill_identity(skill_request)
    _required(skill_request, "skill_call_id", "report_key", "revision", "event_reference", "trigger_receipt_reference", "command")
    _false(skill_request)
    if failure_code not in FAILURE_CODES:
        raise ResearchSkillGovernanceError("Unknown controlled failure code")
    if raw_response is not None and raw_response.skill_call_id != skill_request["skill_call_id"]:
        raise ResearchSkillGovernanceError("Raw response call identity mismatch")
    result_count: int | None = None
    if raw_response is not None:
        result_count = raw_response.result_count
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
    **caller_controls: Any,
) -> dict[str, Any]:
    """Qualify one response item as Discovery only, never as authority evidence."""

    if caller_controls or not isinstance(result, Mapping):
        raise ResearchSkillGovernanceError("PROVENANCE_INCOMPLETE")
    required = ("source_id", "source_locator", "source_type", "source_hash", "content_hash")
    if any(result.get(field) in (None, "") for field in required):
        raise ResearchSkillGovernanceError("PROVENANCE_INCOMPLETE")
    normalized_locator = sanitize_source_locator(result["source_locator"])
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
        "source_id": result["source_id"], "source_locator": normalized_locator,
        "source_type": result["source_type"], "source_class": "DISCOVERY",
        "source_tier": "UNVERIFIED", "locator_validation_status": "LOCATOR_FORMAT_VALID",
        "source_hash": result["source_hash"], "content_hash": result["content_hash"],
        "originating_chain_id": chain if independence == "UNVERIFIED" else None,
        "independence_status": independence,
        "provider_confidence_advisory": result.get("provider_confidence"),
        "core_view_changed": False, "publication_ready": False,
        "published_externally": False, "actionable": False,
    }


THESIS_EVOLUTION_CONTRACT_STATUS = "THESIS_EVOLUTION_CONTRACT_DEFERRED"
