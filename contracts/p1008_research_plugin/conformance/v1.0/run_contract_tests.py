"""P1008 Research Contract v1.0 conformance tests.

This is a test-only reference harness. It does not implement the plugin,
connect to OpenAI, or write to Warroom authority/runtime data.
"""

from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import json
import re
import sys
import time
import unicodedata
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


SCRIPT_ROOT = Path(__file__).resolve().parent
PACKAGE_ROOT = SCRIPT_ROOT.parents[3]
CONTRACT_ROOT = PACKAGE_ROOT / "contracts" / "p1008_research_plugin" / "v1.0"
ACCEPTANCE_PATH = (
    PACKAGE_ROOT
    / "contracts"
    / "p1008_research_plugin"
    / "acceptance"
    / "v1.0"
    / "OWNER_ACCEPTANCE_RECORD.json"
)
FIXTURE_ROOT = SCRIPT_ROOT / "fixtures"
REPORT_ROOT = SCRIPT_ROOT / "reports"
GENESIS_HASH = "0" * 64


@dataclass
class SuiteResult:
    suite_id: str
    status: str
    duration_ms: int
    details: dict[str, Any]
    error: str = ""


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def canonical_json(value: Any) -> str:
    # Fixtures use the RFC 8785 interoperable subset: no floats in hash input.
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest().upper()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def csv_header(path: Path) -> list[str]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("##"):
                continue
            return next(csv.reader([line]))
    raise AssertionError(f"No CSV header found: {path}")


def all_manifest_entries(authority: dict[str, Any]) -> dict[str, dict[str, Any]]:
    entries = authority.get("authoritativeFiles", []) + authority.get("nonAuthoritativeFiles", [])
    return {entry["path"]: entry for entry in entries}


def suite_backward_compatibility() -> dict[str, Any]:
    baseline = read_json(FIXTURE_ROOT / "backward_compatibility_baseline.json")
    authority = read_json(PACKAGE_ROOT / "data" / "CSV_AUTHORITY_MANIFEST.json")
    policy = read_json(CONTRACT_ROOT / "policies" / "plugin_policy.json")
    capabilities = read_json(CONTRACT_ROOT / "policies" / "capability_registry.json")
    api = read_json(CONTRACT_ROOT / "api" / "openapi.json")
    rule_manifest = read_json(PACKAGE_ROOT / "rules" / "RULE_STATUS_MANIFEST.json")
    entries = all_manifest_entries(authority)

    checked_headers = 0
    for relative_path, required_columns in baseline["formalDataContracts"].items():
        require(relative_path in entries, f"Authority manifest is missing {relative_path}")
        file_path = PACKAGE_ROOT / relative_path
        require(file_path.is_file(), f"Authority data file is missing: {relative_path}")
        require(
            sha256_file(file_path) == entries[relative_path]["sha256"].upper(),
            f"Authority hash mismatch: {relative_path}",
        )
        actual_header = set(csv_header(file_path))
        missing = sorted(set(required_columns) - actual_header)
        require(not missing, f"Backward-incompatible CSV header in {relative_path}: {missing}")
        checked_headers += 1

    app_server_text = (PACKAGE_ROOT / "tools" / "p1008_app_server.py").read_text(encoding="utf-8-sig")
    missing_routes = [path for path in baseline["existingAppApiPaths"] if path not in app_server_text]
    require(not missing_routes, f"Existing P1008 API routes disappeared: {missing_routes}")

    research_paths = set(api["paths"])
    require(
        all(path.startswith(baseline["researchApiPrefix"]) for path in research_paths),
        "Research API escaped its namespace",
    )
    require(
        not any(path.startswith(baseline["legacyApiPrefix"]) for path in research_paths),
        "Research API collides with the existing P1008 API namespace",
    )
    require(not (PACKAGE_ROOT / "modules" / "p1008_research_plugin").exists(), "Phase 1B module exists early")

    forbidden_roots = set(policy["forbiddenWriteRoots"])
    require("data/" in forbidden_roots and "rules/" in forbidden_roots, "Authority write roots are not forbidden")
    require(policy["canModifyRuntimeSqlite"] is False, "Runtime SQLite write was enabled")

    rule_material = json.dumps(rule_manifest["rules"], ensure_ascii=False, separators=(",", ":"))
    rule_digest = hashlib.sha256(rule_material.encode("utf-8")).hexdigest().upper()
    require(rule_digest == rule_manifest["rulesDigestSha256"], "Rule manifest digest mismatch")
    require(all(item["actionable"] is False for item in rule_manifest["rules"]), "Actionable rule detected")
    keep_disabled_count = sum(item["status"] == "KEEP_DISABLED" for item in rule_manifest["rules"])

    capability_ids = sorted(item["id"] for item in capabilities["capabilities"])
    require(capability_ids == baseline["expectedCapabilityIds"], "Capability registry changed incompatibly")
    contract_text = "\n".join(
        path.read_text(encoding="utf-8-sig", errors="replace")
        for path in CONTRACT_ROOT.rglob("*")
        if path.is_file() and path.name != "contract.manifest.json"
    )
    require(
        baseline["forbiddenAuthoritySubstitution"] not in contract_text,
        "Frozen contract references a non-authoritative replacement CSV",
    )

    return {
        "authorityFilesVerified": checked_headers,
        "legacyApiRoutesVerified": len(baseline["existingAppApiPaths"]),
        "researchApiPathsVerified": len(research_paths),
        "capabilitiesVerified": len(capability_ids),
        "ruleDigestMatch": True,
        "keepDisabledRules": keep_disabled_count,
        "phase1bModuleAbsent": True,
    }


EVENT_STATE = {
    "KNOWLEDGE_GAP_OPENED": "OPEN",
    "KNOWLEDGE_GAP_INVESTIGATION_STARTED": "INVESTIGATING",
    "KNOWLEDGE_GAP_RESOLVED": "RESOLVED",
    "RESEARCH_AGENDA_PROPOSED": "PROPOSED",
    "RESEARCH_AGENDA_ACTIVATED": "ACTIVE",
    "RESEARCH_AGENDA_ANSWERED": "ANSWERED",
    "RESEARCH_DEBT_OPENED": "OPEN",
    "RESEARCH_DEBT_WAITING_DATA": "WAITING_DATA",
    "RESEARCH_DEBT_OVERDUE": "OVERDUE",
    "RESEARCH_DEBT_RESOLVED": "RESOLVED",
}

AGGREGATE_TRANSITION_KEY = {
    "GAP": "KNOWLEDGE_GAP",
    "AGENDA": "RESEARCH_AGENDA",
    "DEBT": "RESEARCH_DEBT",
}


def make_ledger_records(fixture: dict[str, Any]) -> list[dict[str, Any]]:
    sequences: dict[str, int] = {}
    previous_hashes: dict[str, str] = {}
    records: list[dict[str, Any]] = []
    base_time = "2026-07-10T12:00:"
    for index, item in enumerate(fixture["records"], start=1):
        ledger_id = item["ledgerId"]
        sequence = sequences.get(ledger_id, 0) + 1
        previous_hash = previous_hashes.get(ledger_id, GENESIS_HASH)
        occurred_at = f"{base_time}{index:02d}+00:00"
        event = {
            "event_id": f"EVT-{index:03d}",
            "event_type": item["eventType"],
            "aggregate_type": item["aggregateType"],
            "aggregate_id": item["aggregateId"],
            "occurred_at": occurred_at,
            "actor_type": item["actorType"],
            "actor_id": f"CONFORMANCE-{item['actorType']}",
            "causation_event_id": None,
            "correlation_id": "CONFORMANCE-REPLAY-001",
            "payload": item["payload"],
            "owner_review_required": item["actorType"] == "OWNER" or item["eventType"].endswith("OVERDUE"),
            "effective_change_applied": False,
            "actionable": False,
        }
        hash_input = {
            "ledger_id": ledger_id,
            "sequence": sequence,
            "contract_version": "1.0",
            "recorded_at": occurred_at,
            "previous_hash": previous_hash,
            "event": event,
        }
        record_hash = canonical_hash(hash_input)
        records.append({**hash_input, "record_hash": record_hash, "actionable": False})
        sequences[ledger_id] = sequence
        previous_hashes[ledger_id] = record_hash
    return records


def replay_records(records: list[dict[str, Any]], transitions: dict[str, Any], event_types: set[str]) -> dict[str, str]:
    sequences: dict[str, int] = {}
    previous_hashes: dict[str, str] = {}
    projection: dict[str, str] = {}
    for record in records:
        ledger_id = record["ledger_id"]
        expected_sequence = sequences.get(ledger_id, 0) + 1
        require(record["sequence"] == expected_sequence, f"Non-monotonic sequence in {ledger_id}")
        require(
            record["previous_hash"] == previous_hashes.get(ledger_id, GENESIS_HASH),
            f"Broken previous_hash in {ledger_id}",
        )
        hash_input = {key: record[key] for key in ("ledger_id", "sequence", "contract_version", "recorded_at", "previous_hash", "event")}
        require(record["record_hash"] == canonical_hash(hash_input), f"Invalid record_hash in {ledger_id}")
        event = record["event"]
        require(event["event_type"] in event_types, f"Unregistered event: {event['event_type']}")
        require(event["actionable"] is False and event["effective_change_applied"] is False, "Effective event detected")

        target_state = EVENT_STATE[event["event_type"]]
        aggregate_id = event["aggregate_id"]
        aggregate_key = AGGREGATE_TRANSITION_KEY[event["aggregate_type"]]
        transition_contract = transitions["aggregates"][aggregate_key]
        current_state = projection.get(aggregate_id)
        if current_state is None:
            require(target_state == transition_contract["initial"], f"Invalid initial state for {aggregate_id}")
        else:
            allowed = transition_contract["transitions"][current_state]
            require(target_state in allowed, f"Invalid transition {current_state} -> {target_state}")
        if target_state in {"RESOLVED", "ANSWERED"}:
            require(bool(event["payload"].get("evidence_ids")), f"Evidence missing for {target_state}")
            require(event["actor_type"] != "OPENAI", f"Model performed final transition for {aggregate_id}")
        projection[aggregate_id] = target_state
        sequences[ledger_id] = record["sequence"]
        previous_hashes[ledger_id] = record["record_hash"]
    return projection


def suite_ledger_replay() -> dict[str, Any]:
    fixture = read_json(FIXTURE_ROOT / "ledger_replay_fixture.json")
    ledger_policy = read_json(CONTRACT_ROOT / "ledgers" / "ledger_formats.json")
    transitions = read_json(CONTRACT_ROOT / "events" / "state_transitions.json")
    event_definitions = read_json(CONTRACT_ROOT / "events" / "event_definitions.json")
    event_types = {item["eventType"] for item in event_definitions["events"]}
    require(ledger_policy["appendOnly"] is True, "Ledger is not append-only")
    require(not ledger_policy["inPlaceUpdateAllowed"], "In-place ledger update is allowed")
    records = make_ledger_records(fixture)
    projection = replay_records(records, transitions, event_types)
    require(projection == fixture["expectedProjection"], "Ledger projection differs from expected state")

    tampered = copy.deepcopy(records)
    tamper = fixture["tamperTest"]
    tampered[tamper["recordIndex"]]["event"]["payload"][tamper["payloadField"]] = tamper["replacement"]
    tamper_rejected = False
    try:
        replay_records(tampered, transitions, event_types)
    except AssertionError:
        tamper_rejected = True
    require(tamper_rejected, "Tampered ledger replay was not rejected")
    return {
        "recordsReplayed": len(records),
        "aggregatesProjected": len(projection),
        "hashChainsVerified": len({record["ledger_id"] for record in records}),
        "tamperRejected": tamper_rejected,
    }


def normalized_text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).strip().lower().split())


def deterministic_projection(fixture: dict[str, Any], health_policy: dict[str, Any]) -> dict[str, Any]:
    sources = {item["source_id"]: item for item in fixture["sources"]}
    claims = {item["claim_id"]: item for item in fixture["claims"]}
    gaps = {item["gap_id"]: item for item in fixture["knowledgeGaps"]}
    components = fixture["healthComponents"]
    score = sum(components[key] * weight / 100 for key, weight in health_policy["weights"].items())
    state = next(
        item["id"]
        for item in health_policy["states"]
        if item["minimum"] <= score <= item["maximum"]
    )
    return {
        "run_id": fixture["runId"],
        "as_of_date": fixture["asOfDate"],
        "normalized_question": normalized_text(fixture["question"]),
        "sources": [sources[key] for key in sorted(sources)],
        "claims": [claims[key] for key in sorted(claims)],
        "knowledge_gaps": [gaps[key] for key in sorted(gaps)],
        "health_score": round(score, 4),
        "health_state": state,
        "status": "owner_review_required" if gaps else "completed",
        "owner_review_required": sorted(gaps),
        "default_fill_used": False,
        "actionable": False,
        "no_auto_trade": True,
        "no_formal_csv_write": True,
        "no_rule_enablement": True,
    }


def recursive_keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        return set(value) | set().union(*(recursive_keys(item) for item in value.values()), set())
    if isinstance(value, list):
        return set().union(*(recursive_keys(item) for item in value), set())
    return set()


def suite_deterministic_research() -> dict[str, Any]:
    fixture = read_json(FIXTURE_ROOT / "deterministic_research_fixture.json")
    health_policy = read_json(CONTRACT_ROOT / "policies" / "research_health_policy.json")
    source_policy = read_json(CONTRACT_ROOT / "policies" / "source_policy.json")
    first = deterministic_projection(fixture, health_policy)
    second = deterministic_projection(copy.deepcopy(fixture), health_policy)
    shuffled = copy.deepcopy(fixture)
    shuffled["sources"].reverse()
    shuffled["claims"].reverse()
    shuffled["knowledgeGaps"].reverse()
    third = deterministic_projection(shuffled, health_policy)
    hashes = {canonical_hash(item) for item in (first, second, third)}
    require(len(hashes) == 1, "Research projection changes with input order or repeat execution")

    expected = fixture["expected"]
    require(first["normalized_question"] == expected["normalizedQuestion"], "Question normalization drift")
    require(len(first["sources"]) == expected["sourceCount"], "Source deduplication drift")
    require(len(first["claims"]) == expected["claimCount"], "Claim projection drift")
    require(len(first["knowledge_gaps"]) == expected["knowledgeGapCount"], "Gap deduplication drift")
    require(first["health_score"] == expected["healthScore"], "Research Health score drift")
    require(first["health_state"] == expected["healthState"], "Research Health state drift")
    require(first["status"] == expected["status"], "Missing-data status drift")
    require(source_policy["defaultFillAllowed"] is False and first["default_fill_used"] is False, "DefaultFill detected")
    require(first["knowledge_gaps"], "Known unknown was silently discarded")
    forbidden_keys = {"hold", "midr", "trade_action", "target_position", "formal_csv_write", "ic_score"}
    require(not (recursive_keys(first) & forbidden_keys), "Research output contains Warroom decision keys")
    return {
        "stableOutputHash": next(iter(hashes)),
        "repeatRunsCompared": 3,
        "healthScore": first["health_score"],
        "healthState": first["health_state"],
        "knownUnknownPreserved": True,
        "defaultFillUsed": False,
    }


def suite_contract_drift() -> dict[str, Any]:
    manifest = read_json(CONTRACT_ROOT / "contract.manifest.json")
    acceptance = read_json(ACCEPTANCE_PATH)
    errors: list[str] = []
    root_lines: list[str] = []
    manifest_paths = {item["path"] for item in manifest["artifacts"]}
    for artifact in manifest["artifacts"]:
        path = CONTRACT_ROOT / artifact["path"]
        if not path.is_file():
            errors.append(f"missing:{artifact['path']}")
            continue
        actual_hash = sha256_file(path)
        if actual_hash != artifact["sha256"]:
            errors.append(f"hash:{artifact['path']}")
        if path.stat().st_size != artifact["sizeBytes"]:
            errors.append(f"size:{artifact['path']}")
        root_lines.append(f"{artifact['path']}|{actual_hash}")
    actual_files = {
        path.relative_to(CONTRACT_ROOT).as_posix()
        for path in CONTRACT_ROOT.rglob("*")
        if path.is_file() and path.name != "contract.manifest.json"
    }
    require(actual_files == manifest_paths, f"Frozen artifact set drift: {sorted(actual_files ^ manifest_paths)}")
    require(not errors, f"Frozen artifact drift: {errors}")
    # The freeze was produced on Windows with case-insensitive path ordering.
    root_material = "\n".join(sorted(root_lines, key=str.casefold)).encode("utf-8")
    root_hash = hashlib.sha256(root_material).hexdigest().upper()
    require(root_hash == manifest["rootHash"], "Frozen contract root hash drift")
    require(acceptance["acceptedRootHash"] == root_hash, "Owner acceptance does not reference this frozen root")
    require(acceptance["acceptanceStatus"] == "ACCEPTED_WITH_PHASE_1B_CONDITIONS", "Unexpected acceptance state")
    require(not list(CONTRACT_ROOT.rglob("*.py")), "Python implementation found inside frozen contract")
    return {
        "artifactCount": len(actual_files),
        "rootHash": root_hash,
        "ownerAcceptanceMatched": True,
        "pythonFilesInFrozenRoot": 0,
    }


def collect_post_operations(api: dict[str, Any]) -> list[dict[str, Any]]:
    operations: list[dict[str, Any]] = []
    path_items = api["components"]["pathItems"]
    for path, item in api["paths"].items():
        candidate = item
        if "$ref" in item:
            name = item["$ref"].rsplit("/", 1)[-1]
            candidate = path_items[name]
        if "post" in candidate:
            operations.append({"path": path, **candidate["post"]})
    return operations


def suite_openai_capability_boundary() -> dict[str, Any]:
    fixture = read_json(FIXTURE_ROOT / "openai_capability_boundary_cases.json")
    capabilities = read_json(CONTRACT_ROOT / "policies" / "capability_registry.json")
    plugin_policy = read_json(CONTRACT_ROOT / "policies" / "plugin_policy.json")
    source_policy = read_json(CONTRACT_ROOT / "policies" / "source_policy.json")
    gate_schema = read_json(CONTRACT_ROOT / "schemas" / "gate_result.schema.json")
    api = read_json(CONTRACT_ROOT / "api" / "openapi.json")

    expected_capabilities = {"financial", "deep_research", "macro", "foreign_flow", "valuation", "evidence"}
    actual_capabilities = {item["id"] for item in capabilities["capabilities"]}
    require(actual_capabilities == expected_capabilities, "OpenAI capability set drift")
    require(all(item["enabledInPhase1A"] is False for item in capabilities["capabilities"]), "Phase 1A capability enabled")
    require(capabilities["defaultEnabled"] is False, "Capabilities are enabled by default")

    allowed = set(fixture["allowedAgentTools"])
    forbidden = set(fixture["forbiddenAgentTools"])
    require(not (allowed & forbidden), "Tool allowlist and denylist overlap")
    for case in fixture["cases"]:
        actual = "ALLOW" if case["tool"] in allowed and case["tool"] not in forbidden else "DENY"
        require(actual == case["expected"], f"Capability boundary mismatch: {case['id']}")

    gate_types = set(gate_schema["properties"]["gate_type"]["enum"])
    required_gates = set(fixture["deterministicGovernanceGates"])
    require(required_gates <= gate_types, f"Deterministic governance gate missing: {sorted(required_gates - gate_types)}")
    require(source_policy["modelCitationMayUpgradeTier"] is False, "Model may upgrade source tier")
    require(source_policy["defaultFillAllowed"] is False, "Model DefaultFill is allowed")
    require(source_policy["unregisteredKnowledgeBaseUse"] == "REJECT", "Unregistered KB is allowed")

    required_policy_denials = {
        "noAutoTrade": True,
        "noFormalCsvWrite": True,
        "noRuleEnablement": True,
        "canModifyRuntimeSqlite": False,
        "canChangeMidr": False,
        "canChangeHold": False,
        "canPublish": False,
    }
    for key, expected in required_policy_denials.items():
        require(plugin_policy[key] is expected, f"Governance boundary changed: {key}")

    forbidden_path_pattern = re.compile(r"/(publish|trade|position|rule|shell|command|hold|midr)(/|$)", re.IGNORECASE)
    bad_paths = [path for path in api["paths"] if forbidden_path_pattern.search(path)]
    require(not bad_paths, f"Forbidden API capability exposed: {bad_paths}")
    posts = collect_post_operations(api)
    require(posts and all(item.get("security") == [{"LocalSession": []}] for item in posts), "Unsecured POST operation")
    require(api["x-p1008-no-publish-endpoint"] is True, "API publish boundary removed")
    require(api["x-p1008-no-effective-decision-change"] is True, "API effective-change boundary removed")
    require(not list(CONTRACT_ROOT.rglob("*.py")), "OpenAI/runtime implementation found in Phase 1A")
    return {
        "capabilitiesVerified": len(actual_capabilities),
        "boundaryCasesVerified": len(fixture["cases"]),
        "deterministicGatesVerified": len(required_gates),
        "securedPostOperations": len(posts),
        "openAiCallsMade": 0,
    }


SUITES: list[tuple[str, Callable[[], dict[str, Any]]]] = [
    ("BACKWARD_COMPATIBILITY_TEST", suite_backward_compatibility),
    ("LEDGER_REPLAY_TEST", suite_ledger_replay),
    ("DETERMINISTIC_RESEARCH_TEST", suite_deterministic_research),
    ("CONTRACT_DRIFT_MONITOR", suite_contract_drift),
    ("OPENAI_CAPABILITY_BOUNDARY_TEST", suite_openai_capability_boundary),
]


def run_suite(suite_id: str, function: Callable[[], dict[str, Any]]) -> SuiteResult:
    started = time.perf_counter()
    try:
        details = function()
        return SuiteResult(suite_id, "PASS", round((time.perf_counter() - started) * 1000), details)
    except Exception as exc:  # The report must retain every failed gate.
        return SuiteResult(suite_id, "FAIL", round((time.perf_counter() - started) * 1000), {}, f"{type(exc).__name__}: {exc}")


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# P1008 Research Contract Conformance Report",
        "",
        f"- Contract version: `{report['contractVersion']}`",
        f"- Frozen root hash: `{report['frozenRootHash']}`",
        f"- Generated at: `{report['generatedAt']}`",
        f"- Overall status: **{report['overallStatus']}**",
        f"- Phase 1B status: **{report['phase1bStatus']}**",
        "- OpenAI calls: `0`",
        "- Formal CSV / rule / Runtime SQLite writes: `0`",
        "",
        "## Gate Results",
        "",
        "| Gate | Status | Duration | Evidence |",
        "|---|---:|---:|---|",
    ]
    for result in report["results"]:
        evidence = result["error"] or "; ".join(f"{key}={value}" for key, value in result["details"].items())
        lines.append(f"| `{result['suite_id']}` | **{result['status']}** | {result['duration_ms']} ms | {evidence} |")
    lines.extend(
        [
            "",
            "## Governance Interpretation",
            "",
            "A passing report confirms contract conformance only. It does not authorize Phase 1B implementation, OpenAI calls, Launcher integration, formal publication, HOLD/MIDR changes, rule enablement, or trading actions.",
            "",
            "SDK guardrails remain defense in depth. Source, Evidence, Anti-Fantasy, Legacy Reuse, Warroom Adapter, and Owner gates remain deterministic application logic.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate P1008 Research Contract Freeze v1.0")
    parser.add_argument("--all", action="store_true", help="Run all required conformance suites")
    parser.add_argument("--no-write-report", action="store_true", help="Print results without writing report files")
    args = parser.parse_args()
    if not args.all:
        parser.error("--all is required")

    before_authority_hash = sha256_file(PACKAGE_ROOT / "data" / "CSV_AUTHORITY_MANIFEST.json")
    before_rules_hash = sha256_file(PACKAGE_ROOT / "rules" / "RULE_STATUS_MANIFEST.json")
    results = [run_suite(suite_id, function) for suite_id, function in SUITES]
    manifest = read_json(CONTRACT_ROOT / "contract.manifest.json")
    all_pass = all(result.status == "PASS" for result in results)
    report = {
        "reportId": "P1008_RESEARCH_CONTRACT_CONFORMANCE_V1",
        "contractVersion": "1.0",
        "frozenRootHash": manifest["rootHash"],
        "generatedAt": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "overallStatus": "PASS" if all_pass else "FAIL",
        "phase1bStatus": "DRY_RUN_ELIGIBLE_SEPARATE_OWNER_APPROVAL_REQUIRED" if all_pass else "BLOCKED",
        "results": [asdict(result) for result in results],
        "safety": {
            "openAiCallsMade": 0,
            "networkCallsMade": 0,
            "formalCsvWrites": 0,
            "ruleManifestWrites": 0,
            "runtimeSqliteWrites": 0,
            "launcherChanges": 0,
            "actionable": False,
        },
    }
    require(before_authority_hash == sha256_file(PACKAGE_ROOT / "data" / "CSV_AUTHORITY_MANIFEST.json"), "Authority manifest changed during tests")
    require(before_rules_hash == sha256_file(PACKAGE_ROOT / "rules" / "RULE_STATUS_MANIFEST.json"), "Rule manifest changed during tests")
    if not args.no_write_report:
        REPORT_ROOT.mkdir(parents=True, exist_ok=True)
        (REPORT_ROOT / "latest_test_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (REPORT_ROOT / "latest_test_report.md").write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
