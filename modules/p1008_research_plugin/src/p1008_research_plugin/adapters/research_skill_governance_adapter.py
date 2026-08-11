"""Deterministic, non-executing governance boundary for a pinned research skill.

This module deliberately contains no provider client, credential loader, retry
loop, fallback, or network operation.  It reads only the manifest-bound
Discovery authorization below the controlled report-governance contract root,
then validates requests and canned responses before they can become Discovery
candidates.
"""

from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import json
from pathlib import Path
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
_RUN_ID = re.compile(r"^P1008-[A-Z0-9-]+$")
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
_REPOSITORY_ROOT = Path(__file__).resolve().parents[5]
_REPORT_GOVERNANCE_ROOT = (
    _REPOSITORY_ROOT / "contracts" / "p1008_report_governance" / "v1.0"
)
_DISCOVERY_AUTHORIZATION_PATH = (
    "authorizations/P1008_ANYSEARCH_DISCOVERY_SCAN_AUTHORIZATION_V1.json"
)
_DISCOVERY_REPIN_PATH = "repins/ANYSEARCH_V3_0_1_GOVERNED_REPIN.json"
_DISCOVERY_POLICY_PATH = "policies/external_discovery_provider_policy.json"


def _read_controlled_bytes(path: Path) -> bytes:
    return path.read_bytes()


def _json_object(data: bytes, failure: str) -> dict[str, Any]:
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ResearchSkillGovernanceError(failure) from exc
    if not isinstance(value, dict):
        raise ResearchSkillGovernanceError(failure)
    return value


def _exact_json_equal(actual: object, expected: object) -> bool:
    """Compare governed JSON with exact recursive value and type semantics."""

    if type(actual) is not type(expected):
        return False
    if type(expected) is dict:
        actual_dict = actual  # type: ignore[assignment]
        expected_dict = expected  # type: ignore[assignment]
        return actual_dict.keys() == expected_dict.keys() and all(
            _exact_json_equal(actual_dict[key], expected_dict[key])
            for key in expected_dict
        )
    if type(expected) is list:
        actual_list = actual  # type: ignore[assignment]
        expected_list = expected  # type: ignore[assignment]
        return len(actual_list) == len(expected_list) and all(
            _exact_json_equal(actual_item, expected_item)
            for actual_item, expected_item in zip(actual_list, expected_list)
        )
    return actual == expected


def _verified_report_governance_artifacts(package_root: Path | str) -> dict[str, bytes]:
    if Path(package_root).resolve() != _REPOSITORY_ROOT:
        raise ResearchSkillGovernanceError("DISCOVERY_AUTHORIZATION_LOCATOR_INVALID")
    manifest_path = _REPORT_GOVERNANCE_ROOT / "contract.manifest.json"
    manifest = _json_object(
        _read_controlled_bytes(manifest_path), "DISCOVERY_AUTHORIZATION_MANIFEST_INVALID"
    )
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list):
        raise ResearchSkillGovernanceError("DISCOVERY_AUTHORIZATION_MANIFEST_INVALID")
    declared: dict[str, bytes] = {}
    root_lines: list[str] = []
    for entry in artifacts:
        if not isinstance(entry, Mapping):
            raise ResearchSkillGovernanceError("DISCOVERY_AUTHORIZATION_MANIFEST_INVALID")
        relative = entry.get("path")
        if not isinstance(relative, str) or relative in declared:
            raise ResearchSkillGovernanceError("DISCOVERY_AUTHORIZATION_MANIFEST_INVALID")
        raw = Path(relative)
        path = (_REPORT_GOVERNANCE_ROOT / raw).resolve()
        if raw.is_absolute() or ".." in raw.parts or not path.is_relative_to(
            _REPORT_GOVERNANCE_ROOT
        ) or not path.is_file():
            raise ResearchSkillGovernanceError("DISCOVERY_AUTHORIZATION_MANIFEST_INVALID")
        data = _read_controlled_bytes(path)
        actual_hash = sha256_bytes(data)
        if entry.get("sha256") != actual_hash or entry.get("sizeBytes") != len(data):
            raise ResearchSkillGovernanceError("DISCOVERY_AUTHORIZATION_ARTIFACT_DRIFT")
        declared[relative] = data
        root_lines.append(f"{relative}|{actual_hash}")
    actual_paths = {
        path.relative_to(_REPORT_GOVERNANCE_ROOT).as_posix()
        for path in _REPORT_GOVERNANCE_ROOT.rglob("*")
        if path.is_file() and path.name != "contract.manifest.json"
    }
    if actual_paths != set(declared):
        raise ResearchSkillGovernanceError("DISCOVERY_AUTHORIZATION_MANIFEST_INVALID")
    root_hash = sha256_bytes(
        "\n".join(sorted(root_lines, key=str.casefold)).encode("utf-8")
    )
    if manifest.get("rootHash") != root_hash:
        raise ResearchSkillGovernanceError("DISCOVERY_AUTHORIZATION_ROOT_HASH_INVALID")
    for required in (
        _DISCOVERY_AUTHORIZATION_PATH,
        _DISCOVERY_REPIN_PATH,
        _DISCOVERY_POLICY_PATH,
    ):
        if required not in declared:
            raise ResearchSkillGovernanceError("DISCOVERY_AUTHORIZATION_MANIFEST_INVALID")
    return declared


def _validate_discovery_authorization_documents(
    authorization: Mapping[str, Any],
    repin: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> None:
    expected_keys = {
        "authorizationIdentity",
        "authorizationVersion",
        "ownerDecision",
        "scope",
        "provider",
        "command",
        "max_attempts",
        "fallback_enabled",
        "actionable",
        "source_class",
        "authority_writes",
        "core_view_changes",
        "formal_reports_generated",
        "publication_actions",
    }
    if set(authorization) != expected_keys:
        raise ResearchSkillGovernanceError("DISCOVERY_AUTHORIZATION_CONTENT_INVALID")
    provider = authorization.get("provider")
    if not isinstance(provider, Mapping) or set(provider) != {
        "provider_id",
        "release_version",
        "immutable_source_revision",
        "artifact_sha256",
        "endpoint",
    }:
        raise ResearchSkillGovernanceError("DISCOVERY_AUTHORIZATION_CONTENT_INVALID")
    expected_provider = {
        "provider_id": PINNED_SKILL_IDENTITY["provider_id"],
        "release_version": PINNED_SKILL_IDENTITY["release_version"],
        "immutable_source_revision": PINNED_SKILL_IDENTITY[
            "immutable_source_revision"
        ],
        "artifact_sha256": PINNED_SKILL_IDENTITY["artifact_sha256"],
        "endpoint": PROVIDER_ENDPOINT_IDENTITY,
    }
    expected_authorization = {
        "authorizationIdentity": "P1008_ANYSEARCH_DISCOVERY_SCAN_AUTHORIZATION_V1",
        "authorizationVersion": "1.0",
        "ownerDecision": "APPROVED",
        "scope": "PRE_TRIGGER_DISCOVERY_SCAN",
        "provider": expected_provider,
        "command": "SEARCH",
        "max_attempts": 1,
        "fallback_enabled": False,
        "actionable": False,
        "source_class": "DISCOVERY",
        "authority_writes": 0,
        "core_view_changes": 0,
        "formal_reports_generated": 0,
        "publication_actions": 0,
    }
    if not _exact_json_equal(dict(authorization), expected_authorization):
        raise ResearchSkillGovernanceError("DISCOVERY_AUTHORIZATION_CONTENT_INVALID")
    governed = repin.get("newGovernedIdentity")
    binding = repin.get("governanceBinding")
    capabilities = repin.get("capabilityControl")
    if not all(isinstance(value, Mapping) for value in (governed, binding, capabilities)):
        raise ResearchSkillGovernanceError("DISCOVERY_AUTHORIZATION_REPIN_INVALID")
    if any(governed.get(field) != value for field, value in expected_provider.items() if field != "endpoint"):
        raise ResearchSkillGovernanceError("DISCOVERY_AUTHORIZATION_REPIN_INVALID")
    if governed.get("allowed_endpoint_identities") != [PROVIDER_ENDPOINT_IDENTITY]:
        raise ResearchSkillGovernanceError("DISCOVERY_AUTHORIZATION_REPIN_INVALID")
    expected_binding = {
        "role": "DISCOVERY",
        "sourceClass": "DISCOVERY",
        "sourceTier": "UNVERIFIED",
        "authoritative": False,
        "actionable": False,
        "coreViewDirectModificationAllowed": False,
        "formalReportGenerationOrPublicationAllowed": False,
        "authorityWritesAllowed": False,
        "productionEvidenceLedgerWritesAllowed": False,
        "identityMismatchOutcome": "FAIL_CLOSED",
    }
    if any(binding.get(field) != value for field, value in expected_binding.items()):
        raise ResearchSkillGovernanceError("DISCOVERY_AUTHORIZATION_REPIN_INVALID")
    if (
        "SEARCH" not in capabilities.get("adapterAllowlistedCommands", [])
        or capabilities.get("automaticRetryAllowed") is not False
        or capabilities.get("fallbackAllowed") is not False
    ):
        raise ResearchSkillGovernanceError("DISCOVERY_AUTHORIZATION_REPIN_INVALID")
    runtime = policy.get("runtimeGovernance")
    authority = policy.get("authorityBoundary")
    if not isinstance(runtime, Mapping) or not isinstance(authority, Mapping):
        raise ResearchSkillGovernanceError("DISCOVERY_AUTHORIZATION_POLICY_INVALID")
    if (
        runtime.get("networkDefault") != "DENY"
        or runtime.get("automaticRetryProhibited") is not True
        or runtime.get("fallbackProhibitedUnlessSeparatelyAuthorized") is not True
    ):
        raise ResearchSkillGovernanceError("DISCOVERY_AUTHORIZATION_POLICY_INVALID")
    expected_authority = {
        "providerOutputClass": "DISCOVERY",
        "authorityPromotionInsideAdapterProhibited": True,
        "authorityWriteProhibited": True,
        "productionEvidenceLedgerWriteProhibited": True,
        "coreViewWriteProhibited": True,
        "formalReportGenerationOrPublicationProhibited": True,
        "retrievalSuccessMayBecomeActionable": False,
    }
    if any(authority.get(field) != value for field, value in expected_authority.items()):
        raise ResearchSkillGovernanceError("DISCOVERY_AUTHORIZATION_POLICY_INVALID")


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


@dataclass(frozen=True, eq=False, init=False)
class ValidatedDiscoveryAuthorization:
    """Opaque, manifest-verified Owner authorization for one scan mint."""

    authorization_identity: str
    authorization_version: str
    authorization_scope: str
    authorization_locator: str
    authorization_artifact_sha256: str
    provider_id: str
    release_version: str
    immutable_source_revision: str
    artifact_sha256: str
    endpoint: str
    command: str
    max_attempts: int
    fallback_enabled: bool
    actionable: bool
    authority_writes: int
    core_view_changes: int
    formal_reports_generated: int
    publication_actions: int

    def __init__(self) -> None:
        raise TypeError(
            "ValidatedDiscoveryAuthorization must be loaded from the governed contract"
        )

    def __reduce__(self) -> object:
        raise TypeError("ValidatedDiscoveryAuthorization is not serializable")


@dataclass(frozen=True)
class _ValidatedDiscoveryAuthorizationSnapshot:
    authorization_identity: str
    authorization_version: str
    authorization_scope: str
    authorization_locator: str
    authorization_artifact_sha256: str
    provider_id: str
    release_version: str
    immutable_source_revision: str
    artifact_sha256: str
    endpoint: str
    command: str
    max_attempts: int
    fallback_enabled: bool
    actionable: bool
    authority_writes: int
    core_view_changes: int
    formal_reports_generated: int
    publication_actions: int
    issuance_state: str


_AUTHORIZATION_OBJECT_FIELDS = tuple(
    field
    for field in _ValidatedDiscoveryAuthorizationSnapshot.__dataclass_fields__
    if field != "issuance_state"
)


_VALIDATED_DISCOVERY_AUTHORIZATIONS: weakref.WeakKeyDictionary[
    ValidatedDiscoveryAuthorization, _ValidatedDiscoveryAuthorizationSnapshot
] = weakref.WeakKeyDictionary()


def _authorization_matches_snapshot(
    authorization: ValidatedDiscoveryAuthorization,
    snapshot: _ValidatedDiscoveryAuthorizationSnapshot,
) -> bool:
    for field in _AUTHORIZATION_OBJECT_FIELDS:
        current = getattr(authorization, field, None)
        expected = getattr(snapshot, field)
        if type(current) is not type(expected) or current != expected:
            return False
    return True


def _authorization_snapshot_with_state(
    snapshot: _ValidatedDiscoveryAuthorizationSnapshot, issuance_state: str
) -> _ValidatedDiscoveryAuthorizationSnapshot:
    values = {
        field: getattr(snapshot, field)
        for field in _ValidatedDiscoveryAuthorizationSnapshot.__dataclass_fields__
    }
    values["issuance_state"] = issuance_state
    return _ValidatedDiscoveryAuthorizationSnapshot(**values)


def load_validated_discovery_authorization(
    package_root: Path | str,
) -> ValidatedDiscoveryAuthorization:
    """Load only the controlled, manifest-bound authorization and pinned inputs."""

    artifacts = _verified_report_governance_artifacts(package_root)
    authorization_bytes = artifacts[_DISCOVERY_AUTHORIZATION_PATH]
    authorization = _json_object(
        authorization_bytes, "DISCOVERY_AUTHORIZATION_CONTENT_INVALID"
    )
    repin = _json_object(
        artifacts[_DISCOVERY_REPIN_PATH], "DISCOVERY_AUTHORIZATION_REPIN_INVALID"
    )
    policy = _json_object(
        artifacts[_DISCOVERY_POLICY_PATH], "DISCOVERY_AUTHORIZATION_POLICY_INVALID"
    )
    _validate_discovery_authorization_documents(authorization, repin, policy)
    provider = authorization["provider"]
    snapshot = _ValidatedDiscoveryAuthorizationSnapshot(
        authorization_identity=authorization["authorizationIdentity"],
        authorization_version=authorization["authorizationVersion"],
        authorization_scope=authorization["scope"],
        authorization_locator=_DISCOVERY_AUTHORIZATION_PATH,
        authorization_artifact_sha256=sha256_bytes(authorization_bytes),
        provider_id=provider["provider_id"],
        release_version=provider["release_version"],
        immutable_source_revision=provider["immutable_source_revision"],
        artifact_sha256=provider["artifact_sha256"],
        endpoint=provider["endpoint"],
        command=authorization["command"],
        max_attempts=authorization["max_attempts"],
        fallback_enabled=authorization["fallback_enabled"],
        actionable=authorization["actionable"],
        authority_writes=authorization["authority_writes"],
        core_view_changes=authorization["core_view_changes"],
        formal_reports_generated=authorization["formal_reports_generated"],
        publication_actions=authorization["publication_actions"],
        issuance_state="ISSUED",
    )
    capability = object.__new__(ValidatedDiscoveryAuthorization)
    for field in _AUTHORIZATION_OBJECT_FIELDS:
        object.__setattr__(capability, field, getattr(snapshot, field))
    _VALIDATED_DISCOVERY_AUTHORIZATIONS[capability] = snapshot
    return capability


def evaluate_discovery_authorization_eligibility(value: object) -> dict[str, Any]:
    snapshot = (
        _VALIDATED_DISCOVERY_AUTHORIZATIONS.get(value)
        if isinstance(value, ValidatedDiscoveryAuthorization)
        else None
    )
    valid = bool(
        snapshot is not None
        and snapshot.issuance_state == "ISSUED"
        and snapshot.authorization_scope == "PRE_TRIGGER_DISCOVERY_SCAN"
        and _authorization_matches_snapshot(value, snapshot)
    )
    return {
        "eligible": valid,
        "scan_mints": 1 if valid else 0,
        "status": "ELIGIBLE" if valid else "NOT_ELIGIBLE",
        "actionable": False,
    }


@dataclass(frozen=True, eq=False, init=False)
class ValidatedDiscoveryScan:
    """Opaque, single-use capability for Discovery before report triggering."""

    scan_id: str
    run_id: str
    scan_reference: str
    event_reference: str
    authority_manifest_sha256: str
    authorization_identity: str
    authorization_version: str
    discovery_authorization_scope: str
    authorization_locator: str
    authorization_artifact_sha256: str
    producer_id: str
    actionable: bool
    _consume_callback: Callable[[], None]

    def __init__(self) -> None:
        raise TypeError(
            "ValidatedDiscoveryScan must be minted by the trusted research orchestrator"
        )

    def __reduce__(self) -> object:
        raise TypeError("ValidatedDiscoveryScan is not serializable")


_VALIDATED_DISCOVERY_SCAN_STATES: weakref.WeakKeyDictionary[ValidatedDiscoveryScan, str] = weakref.WeakKeyDictionary()


def _mint_validated_discovery_scan(
    *,
    validated_authorization: ValidatedDiscoveryAuthorization,
    scan_id: str,
    run_id: str,
    scan_reference: str,
    event_reference: str,
    authority_manifest_sha256: str,
    consume_callback: Callable[[], None],
) -> ValidatedDiscoveryScan:
    """Consume one opaque Owner authorization to mint one Discovery scan."""

    snapshot = (
        _VALIDATED_DISCOVERY_AUTHORIZATIONS.get(validated_authorization)
        if isinstance(validated_authorization, ValidatedDiscoveryAuthorization)
        else None
    )
    if (
        snapshot is None
        or snapshot.issuance_state != "ISSUED"
        or snapshot.authorization_scope != "PRE_TRIGGER_DISCOVERY_SCAN"
    ):
        raise ResearchSkillGovernanceError("DISCOVERY_AUTHORIZATION_NOT_ELIGIBLE")
    if not _authorization_matches_snapshot(validated_authorization, snapshot):
        raise ResearchSkillGovernanceError("DISCOVERY_AUTHORIZATION_TAMPERED")
    if not isinstance(scan_id, str) or not scan_id.startswith("DISCOVERY-SCAN-"):
        raise ResearchSkillGovernanceError("DISCOVERY_SCAN_MINT_INVALID")
    if not isinstance(run_id, str) or not _RUN_ID.fullmatch(run_id):
        raise ResearchSkillGovernanceError("DISCOVERY_SCAN_MINT_INVALID")
    if not all(
        isinstance(value, str) and value
        for value in (scan_reference, event_reference)
    ):
        raise ResearchSkillGovernanceError("DISCOVERY_SCAN_MINT_INVALID")
    if not _SHA256.fullmatch(authority_manifest_sha256):
        raise ResearchSkillGovernanceError("DISCOVERY_SCAN_MINT_INVALID")
    if not callable(consume_callback):
        raise ResearchSkillGovernanceError("DISCOVERY_SCAN_MINT_INVALID")
    capability = object.__new__(ValidatedDiscoveryScan)
    for name, value in {
        "scan_id": scan_id,
        "run_id": run_id,
        "scan_reference": scan_reference,
        "event_reference": event_reference,
        "authority_manifest_sha256": authority_manifest_sha256,
        "authorization_identity": snapshot.authorization_identity,
        "authorization_version": snapshot.authorization_version,
        "discovery_authorization_scope": snapshot.authorization_scope,
        "authorization_locator": snapshot.authorization_locator,
        "authorization_artifact_sha256": snapshot.authorization_artifact_sha256,
        "producer_id": "P1008_RESEARCH_CONTENT_ORCHESTRATOR_V1",
        "actionable": False,
        "_consume_callback": consume_callback,
    }.items():
        object.__setattr__(capability, name, value)
    _VALIDATED_DISCOVERY_SCAN_STATES[capability] = "ISSUED"
    _VALIDATED_DISCOVERY_AUTHORIZATIONS[validated_authorization] = (
        _authorization_snapshot_with_state(snapshot, "CONSUMED")
    )
    return capability


def evaluate_discovery_scan_eligibility(value: object) -> dict[str, Any]:
    valid = (
        isinstance(value, ValidatedDiscoveryScan)
        and value in _VALIDATED_DISCOVERY_SCAN_STATES
        and _VALIDATED_DISCOVERY_SCAN_STATES.get(value) == "ISSUED"
        and value.actionable is False
    )
    return {
        "eligible": valid,
        "skill_calls": 1 if valid else 0,
        "status": "ELIGIBLE" if valid else "NOT_ELIGIBLE",
        "actionable": False,
    }


def consume_validated_discovery_scan(value: object) -> None:
    if not isinstance(value, ValidatedDiscoveryScan) or value not in _VALIDATED_DISCOVERY_SCAN_STATES:
        raise ResearchSkillGovernanceError("DISCOVERY_SCAN_NOT_ELIGIBLE")
    if _VALIDATED_DISCOVERY_SCAN_STATES.get(value) != "ISSUED":
        raise ResearchSkillGovernanceError("DISCOVERY_SCAN_AUTHORIZATION_ALREADY_CONSUMED")
    value._consume_callback()
    _VALIDATED_DISCOVERY_SCAN_STATES[value] = "CONSUMED"


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


def validate_discovery_skill_request_authorization(
    skill_request: Mapping[str, Any], validated_scan: object
) -> ValidatedDiscoveryScan:
    """Bind SEARCH to the live opaque Discovery capability that created it."""

    if not isinstance(validated_scan, ValidatedDiscoveryScan):
        raise ResearchSkillGovernanceError("DISCOVERY_SCAN_NOT_ELIGIBLE")
    if not evaluate_discovery_scan_eligibility(validated_scan)["eligible"]:
        raise ResearchSkillGovernanceError("DISCOVERY_SCAN_NOT_ELIGIBLE")
    expected = {
        "authorization_scope": "DISCOVERY_SCAN",
        "discovery_scan_id": validated_scan.scan_id,
        "run_id": validated_scan.run_id,
        "scan_reference": validated_scan.scan_reference,
        "event_reference": validated_scan.event_reference,
        "authority_manifest_sha256": validated_scan.authority_manifest_sha256,
        "authorization_identity": validated_scan.authorization_identity,
        "authorization_version": validated_scan.authorization_version,
        "discovery_authorization_scope": validated_scan.discovery_authorization_scope,
        "authorization_locator": validated_scan.authorization_locator,
        "authorization_artifact_sha256": validated_scan.authorization_artifact_sha256,
        "producer_id": validated_scan.producer_id,
        "actionable": False,
    }
    if any(skill_request.get(field) != value for field, value in expected.items()):
        raise ResearchSkillGovernanceError("DISCOVERY_SCAN_CONTEXT_MISMATCH")
    return validated_scan


def build_discovery_skill_request(
    *,
    validated_scan: ValidatedDiscoveryScan,
    query: str,
    auth_mode: str = "NONE",
    max_attempts: int = MAX_ATTEMPTS,
    fallback_enabled: bool = False,
) -> dict[str, Any]:
    """Build one SEARCH-only request before any report-trigger evaluation."""

    if auth_mode not in AUTH_MODES or max_attempts != 1 or fallback_enabled is not False:
        raise ResearchSkillGovernanceError("SKILL_COMMAND_NOT_ALLOWED")
    if not evaluate_discovery_scan_eligibility(validated_scan)["eligible"]:
        raise ResearchSkillGovernanceError("DISCOVERY_SCAN_NOT_ELIGIBLE")
    normalized_query = sanitize_query(query)
    request_seed = {
        "authorization_scope": "DISCOVERY_SCAN",
        "discovery_scan_id": validated_scan.scan_id,
        "run_id": validated_scan.run_id,
        "event_reference": validated_scan.event_reference,
        "normalized_query": normalized_query,
    }
    skill_call_id = "SKILL-" + sha256_bytes(canonical_json_bytes(request_seed))[:16]
    return {
        "skill_call_id": skill_call_id,
        **dict(PINNED_SKILL_IDENTITY),
        "authorization_scope": "DISCOVERY_SCAN",
        "discovery_scan_id": validated_scan.scan_id,
        "run_id": validated_scan.run_id,
        "scan_reference": validated_scan.scan_reference,
        "event_reference": validated_scan.event_reference,
        "authority_manifest_sha256": validated_scan.authority_manifest_sha256,
        "authorization_identity": validated_scan.authorization_identity,
        "authorization_version": validated_scan.authorization_version,
        "discovery_authorization_scope": validated_scan.discovery_authorization_scope,
        "authorization_locator": validated_scan.authorization_locator,
        "authorization_artifact_sha256": validated_scan.authorization_artifact_sha256,
        "producer_id": validated_scan.producer_id,
        "command": "SEARCH",
        "provider_command": "search",
        "normalized_query": normalized_query,
        "normalized_query_hash": sha256_bytes(canonical_json_bytes(normalized_query)),
        "target_url": None,
        "target_url_hash": None,
        "auth_mode": auth_mode,
        "max_attempts": 1,
        "fallback_enabled": False,
        "provider_endpoint_identity": PROVIDER_ENDPOINT_IDENTITY,
        "actionable": False,
    }


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


def build_discovery_skill_call_receipt(
    *,
    skill_request: Mapping[str, Any],
    raw_response: RawSkillResponse | None,
    started_at_utc: str,
    completed_at_utc: str,
    failure_code: str,
) -> dict[str, Any]:
    """Build the non-report, secret-free receipt for one Discovery scan."""

    validate_skill_identity(skill_request)
    _required(
        skill_request,
        "skill_call_id",
        "discovery_scan_id",
        "run_id",
        "scan_reference",
        "event_reference",
        "authority_manifest_sha256",
        "authorization_identity",
        "authorization_version",
        "discovery_authorization_scope",
        "authorization_locator",
        "authorization_artifact_sha256",
        "producer_id",
        "command",
    )
    _false(skill_request)
    if skill_request.get("authorization_scope") != "DISCOVERY_SCAN":
        raise ResearchSkillGovernanceError("DISCOVERY_SCAN_CONTEXT_MISMATCH")
    if failure_code not in FAILURE_CODES:
        raise ResearchSkillGovernanceError("Unknown controlled failure code")
    if raw_response is not None and raw_response.skill_call_id != skill_request["skill_call_id"]:
        raise ResearchSkillGovernanceError("Raw response call identity mismatch")
    status = "SUCCESS" if failure_code in {"SUCCESS", "SUCCESS_NO_RELEVANT_RESULT"} else "FAIL_CLOSED"
    return {
        "skill_call_id": skill_request["skill_call_id"],
        **dict(PINNED_SKILL_IDENTITY),
        "authorization_scope": "DISCOVERY_SCAN",
        "discovery_scan_id": skill_request["discovery_scan_id"],
        "run_id": skill_request["run_id"],
        "scan_reference": skill_request["scan_reference"],
        "event_reference": skill_request["event_reference"],
        "authority_manifest_sha256": skill_request["authority_manifest_sha256"],
        "authorization_identity": skill_request["authorization_identity"],
        "authorization_version": skill_request["authorization_version"],
        "discovery_authorization_scope": skill_request[
            "discovery_authorization_scope"
        ],
        "authorization_locator": skill_request["authorization_locator"],
        "authorization_artifact_sha256": skill_request[
            "authorization_artifact_sha256"
        ],
        "producer_id": skill_request["producer_id"],
        "command": "SEARCH",
        "normalized_query_hash": skill_request["normalized_query_hash"],
        "started_at_utc": started_at_utc,
        "completed_at_utc": completed_at_utc,
        "status": status,
        "attempt_count": 1,
        "provider_endpoint_identity": PROVIDER_ENDPOINT_IDENTITY,
        "raw_response_hash": raw_response.raw_response_hash if raw_response else None,
        "result_count": raw_response.result_count if raw_response else None,
        "failure_code": failure_code,
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
