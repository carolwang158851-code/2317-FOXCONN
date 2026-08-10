"""Minimal governed AnySearch runtime for non-authoritative Discovery staging.

The provider client lives outside the deterministic governance adapter.  It
accepts only a request already constructed by that adapter, uses the one
identity-bound endpoint, performs exactly one HTTP attempt, and returns a
secret-free, non-actionable staging envelope.  It has no authority, Core View,
Evidence Ledger, publication, retry, fallback, registration, or key-persistence
path.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from . import research_skill_governance_adapter as governance
from ..phaseb1_common import canonical_json_bytes, sha256_bytes


class GovernedAnySearchRuntimeError(RuntimeError):
    """A fail-closed runtime error with no provider response or secret text."""


SMOKE_QUERY = "Hon Hai Foxconn 2317 latest company developments"
SMOKE_AUTHORIZATION_REFERENCE = "OWNER_ANYSEARCH_V3_RUNTIME_INTEGRATION_20260810"
_ALLOWED_ENDPOINT = governance.PROVIDER_ENDPOINT_IDENTITY
_SECRET_NAME = "ANYSEARCH_API_KEY"
_SECRETISH_KEY = re.compile(r"(?:api[_-]?key|authorization|token|password|secret)", re.IGNORECASE)
_URL = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)


class _RejectRedirect(HTTPRedirectHandler):
    def redirect_request(self, req: Request, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
        raise GovernedAnySearchRuntimeError("UNEXPECTED_ENDPOINT")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _identity() -> dict[str, Any]:
    return dict(governance.PINNED_SKILL_IDENTITY)


def _require_governed_search_request(skill_request: Mapping[str, Any], *, allow_anonymous: bool) -> None:
    governance.validate_skill_identity(skill_request)
    if skill_request.get("command") != "SEARCH" or skill_request.get("provider_command") != "search":
        raise GovernedAnySearchRuntimeError("COMMAND_NOT_ALLOWED")
    if skill_request.get("provider_endpoint_identity") != _ALLOWED_ENDPOINT:
        raise GovernedAnySearchRuntimeError("UNEXPECTED_ENDPOINT")
    if tuple(skill_request.get("allowed_endpoint_identities", ())) != (_ALLOWED_ENDPOINT,):
        raise GovernedAnySearchRuntimeError("UNEXPECTED_ENDPOINT")
    if skill_request.get("max_attempts") != 1 or skill_request.get("fallback_enabled") is not False:
        raise GovernedAnySearchRuntimeError("RUNTIME_POLICY_VIOLATION")
    if skill_request.get("actionable") is not False:
        raise GovernedAnySearchRuntimeError("RUNTIME_POLICY_VIOLATION")
    query = skill_request.get("normalized_query")
    if governance.sanitize_query(query) != query:
        raise GovernedAnySearchRuntimeError("QUERY_POLICY_BLOCKED")
    auth_mode = skill_request.get("auth_mode")
    if auth_mode == "NONE":
        if not allow_anonymous:
            raise GovernedAnySearchRuntimeError("ANONYMOUS_MODE_NOT_AUTHORIZED")
    elif auth_mode != "OWNER_SUPPLIED_RUNTIME_SECRET":
        raise GovernedAnySearchRuntimeError("RUNTIME_POLICY_VIOLATION")


def _authorization_header(auth_mode: str) -> dict[str, str]:
    headers = {"Content-Type": "application/json", "X-Anysearch-Client": "P1008-GOVERNED-DISCOVERY"}
    if auth_mode == "NONE":
        return headers
    secret = os.environ.get(_SECRET_NAME)
    if not isinstance(secret, str) or not secret:
        raise GovernedAnySearchRuntimeError("REQUIRED_SECRET_UNAVAILABLE")
    headers["Authorization"] = f"Bearer {secret}"
    return headers


def _post_once(endpoint: str, payload: Mapping[str, Any], headers: Mapping[str, str], *, timeout_seconds: int = 30) -> Mapping[str, Any]:
    if endpoint != _ALLOWED_ENDPOINT:
        raise GovernedAnySearchRuntimeError("UNEXPECTED_ENDPOINT")
    request = Request(endpoint, data=canonical_json_bytes(dict(payload)), headers=dict(headers), method="POST")
    opener = build_opener(_RejectRedirect())
    try:
        with opener.open(request, timeout=timeout_seconds) as response:
            if response.geturl() != _ALLOWED_ENDPOINT:
                raise GovernedAnySearchRuntimeError("UNEXPECTED_ENDPOINT")
            body = response.read()
    except GovernedAnySearchRuntimeError:
        raise
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise GovernedAnySearchRuntimeError("RUNTIME_UNAVAILABLE") from exc
    try:
        parsed = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GovernedAnySearchRuntimeError("MALFORMED_RESPONSE") from exc
    if not isinstance(parsed, Mapping):
        raise GovernedAnySearchRuntimeError("MALFORMED_RESPONSE")
    return parsed


def _scrub(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _scrub(item) for key, item in value.items() if not _SECRETISH_KEY.search(str(key))}
    if isinstance(value, list):
        return [_scrub(item) for item in value]
    return value


def _text_content(response: Mapping[str, Any]) -> str:
    if response.get("error") is not None:
        raise GovernedAnySearchRuntimeError("SOURCE_FAILED")
    result = response.get("result")
    if not isinstance(result, Mapping):
        raise GovernedAnySearchRuntimeError("MALFORMED_RESPONSE")
    content = result.get("content")
    if not isinstance(content, list):
        raise GovernedAnySearchRuntimeError("MALFORMED_RESPONSE")
    text = [item.get("text") for item in content if isinstance(item, Mapping) and item.get("type") == "text" and isinstance(item.get("text"), str)]
    if not text:
        raise GovernedAnySearchRuntimeError("MALFORMED_RESPONSE")
    return "\n".join(text)


def _result_items(provider_response: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    text = _text_content(provider_response)
    try:
        decoded = json.loads(text)
    except json.JSONDecodeError:
        decoded = None
    if isinstance(decoded, list):
        return [item for item in decoded if isinstance(item, Mapping)]
    if isinstance(decoded, Mapping):
        for key in ("results", "data", "items"):
            value = decoded.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, Mapping)]
            if isinstance(value, Mapping) and isinstance(value.get("results"), list):
                return [item for item in value["results"] if isinstance(item, Mapping)]
    urls = []
    for url in _URL.findall(text):
        clean = url.rstrip(".,;:)]}")
        if clean not in urls:
            urls.append(clean)
    return [{"url": url, "snippet": text} for url in urls]


def _normalize_result(item: Mapping[str, Any], index: int) -> dict[str, Any]:
    locator = item.get("url") or item.get("link") or item.get("source_locator")
    if not isinstance(locator, str) or not locator:
        raise GovernedAnySearchRuntimeError("MALFORMED_RESPONSE")
    title = item.get("title") or item.get("name") or "AnySearch result"
    snippet = item.get("snippet") or item.get("content") or item.get("description") or ""
    if not isinstance(title, str) or not isinstance(snippet, str):
        raise GovernedAnySearchRuntimeError("MALFORMED_RESPONSE")
    parsed = urlsplit(locator)
    query = urlencode(
        [(key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True) if not _SECRETISH_KEY.search(key)],
        doseq=True,
    )
    locator = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, query, ""))
    locator_hash = sha256_bytes(canonical_json_bytes(locator))
    content_hash = sha256_bytes(canonical_json_bytes({"locator": locator, "title": title, "snippet": snippet}))
    return {
        "source_id": f"ANYSEARCH-{locator_hash[:16]}",
        "source_locator": locator,
        "source_type": "WEB_SEARCH_RESULT",
        "source_hash": locator_hash,
        "content_hash": content_hash,
        "provider_confidence": item.get("score") or item.get("confidence"),
        "provider_result_index": index,
    }


def execute_governed_search(
    skill_request: Mapping[str, Any],
    *,
    allow_anonymous: bool,
    transport: Callable[[str, Mapping[str, Any], Mapping[str, str]], Mapping[str, Any]] | None = None,
    retrieved_at_utc: str | None = None,
) -> dict[str, Any]:
    """Execute exactly one governed SEARCH and normalize only Discovery candidates."""

    _require_governed_search_request(skill_request, allow_anonymous=allow_anonymous)
    started_at = _utc_now()
    rpc_payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "search", "arguments": {"query": skill_request["normalized_query"]}}}
    headers = _authorization_header(str(skill_request["auth_mode"]))
    response = (transport or _post_once)(_ALLOWED_ENDPOINT, rpc_payload, headers)
    if not isinstance(response, Mapping):
        raise GovernedAnySearchRuntimeError("MALFORMED_RESPONSE")
    retrieved_at = retrieved_at_utc or _utc_now()
    raw = governance.capture_raw_skill_response(skill_request=skill_request, payload=_scrub(response), retrieved_at_utc=retrieved_at)
    candidates: list[dict[str, Any]] = []
    for index, item in enumerate(_result_items(response)):
        candidate = governance.build_discovery_evidence_candidate(raw_response=raw, result=_normalize_result(item, index))
        candidate["governed_provider_version"] = governance.PINNED_SKILL_IDENTITY["release_version"]
        candidate["governed_provider_commit"] = governance.PINNED_SKILL_IDENTITY["immutable_source_revision"]
        candidate["governed_artifact_sha256"] = governance.PINNED_SKILL_IDENTITY["artifact_sha256"]
        candidate["provider_response_provenance"] = {"raw_response_hash": raw.raw_response_hash, "result_index": index}
        candidate["validation_state"] = "DISCOVERY_UNVERIFIED"
        candidate["actionable"] = False
        candidates.append(candidate)
    completed_at = _utc_now()
    failure_code = "SUCCESS" if candidates else "SUCCESS_NO_RELEVANT_RESULT"
    receipt = governance.build_skill_call_receipt(skill_request=skill_request, raw_response=raw, started_at_utc=started_at, completed_at_utc=completed_at, failure_code=failure_code)
    return {
        "record_type": "P1008_ANYSEARCH_DISCOVERY_STAGING",
        "schema_version": "1.0",
        "status": receipt["status"],
        "receipt": receipt,
        "provider": "ANYSEARCH",
        "governed_provider_identity": _identity(),
        "retrieved_at_utc": retrieved_at,
        "query_hash": skill_request["normalized_query_hash"],
        "candidates": candidates,
        "authority_writes": 0,
        "core_view_changes": 0,
        "formal_reports_generated": 0,
        "actionable": False,
    }


def owner_authorized_smoke_request() -> dict[str, Any]:
    """Build the single fixed Owner-authorized smoke request; not a general bypass."""

    query = governance.sanitize_query(SMOKE_QUERY)
    return {
        "skill_call_id": "SMOKE-" + sha256_bytes(canonical_json_bytes({"authorization": SMOKE_AUTHORIZATION_REFERENCE, "query": query}))[:16],
        **_identity(),
        "report_key": "P1008_NEWS_RD_ANYSEARCH_RUNTIME_SMOKE",
        "revision": 1,
        "event_reference": SMOKE_AUTHORIZATION_REFERENCE,
        "trigger_receipt_reference": SMOKE_AUTHORIZATION_REFERENCE,
        "trigger_decision_id": SMOKE_AUTHORIZATION_REFERENCE,
        "trigger_receipt_hash": sha256_bytes(canonical_json_bytes(SMOKE_AUTHORIZATION_REFERENCE)),
        "command": "SEARCH",
        "provider_command": "search",
        "normalized_query": query,
        "normalized_query_hash": sha256_bytes(canonical_json_bytes(query)),
        "target_url": None,
        "target_url_hash": None,
        "auth_mode": "NONE",
        "max_attempts": 1,
        "fallback_enabled": False,
        "provider_endpoint_identity": _ALLOWED_ENDPOINT,
        "actionable": False,
    }


def write_staging_output(envelope: Mapping[str, Any], staging_root: Path) -> Path:
    """Persist only a complete non-actionable envelope below runtime/anysearch_staging."""

    repo_root = Path(__file__).resolve().parents[5]
    approved_root = (repo_root / "runtime" / "anysearch_staging").resolve()
    root = staging_root.resolve()
    if root != approved_root:
        raise GovernedAnySearchRuntimeError("UNAUTHORIZED_WRITE_ATTEMPT")
    if envelope.get("actionable") is not False or envelope.get("authority_writes") != 0:
        raise GovernedAnySearchRuntimeError("UNAUTHORIZED_WRITE_ATTEMPT")
    root.mkdir(parents=True, exist_ok=True)
    path = root / "latest_smoke.json"
    path.write_bytes(canonical_json_bytes(dict(envelope)))
    return path
