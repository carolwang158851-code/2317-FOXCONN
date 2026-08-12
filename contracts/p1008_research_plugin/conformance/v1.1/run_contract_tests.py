"""Phase-aware current conformance checks for the P1008 research plugin.

Version 1.1 is additive.  It does not reinterpret or modify the frozen v1.0
contract; it validates the approved implementation tree and reuses the v1.0
deterministic suites that remain valid after the module was authorized.
"""

from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable


SCRIPT_ROOT = Path(__file__).resolve().parent
PACKAGE_ROOT = SCRIPT_ROOT.parents[3]
ACCEPTANCE_PATH = (
    PACKAGE_ROOT
    / "contracts"
    / "p1008_research_plugin"
    / "acceptance"
    / "v1.1"
    / "PHASE_ROUTING_ACCEPTANCE_RECORD.json"
)
V1_RUNNER_PATH = SCRIPT_ROOT.parent / "v1.0" / "run_contract_tests.py"
V1_CONTRACT_ROOT = PACKAGE_ROOT / "contracts" / "p1008_research_plugin" / "v1.0"
MODULE_RELATIVE_PATH = Path("modules/p1008_research_plugin")
CURRENT_AUTHORITY_AMENDMENT_PATH = (
    "contracts/p1008_research_plugin/acceptance/v1.1/"
    "P1008_TWSE_AUTHORITY_INCREMENTAL_REMEDIATION_AMENDMENT.json"
)
CURRENT_AUTHORITY_AMENDMENT_SHA256 = (
    "9A0DDC6A85BE96123A7EC378DAC7BDD368D671DB8BFBFDD07DC40EFE438FD187"
)


@dataclass
class SuiteResult:
    suite_id: str
    status: str
    duration_ms: int
    details: dict[str, Any]
    error: str = ""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest().upper()


def git_blob_bytes(root: Path, relative_path: str, revision: str = "HEAD") -> bytes:
    result = subprocess.run(
        ["git", "-C", str(root), "show", f"{revision}:{relative_path}"],
        check=False,
        capture_output=True,
    )
    require(result.returncode == 0, f"Frozen v1 Git blob is unavailable: {relative_path}")
    return result.stdout


def normalize_checkout_eol(value: bytes) -> bytes:
    """Compare text artifacts without treating checkout EOL policy as contract drift."""
    return value.replace(b"\r\n", b"\n")


def validate_committed_text_artifact(root: Path, relative_path: str, expected_hash: str, label: str) -> None:
    path = root / relative_path
    require(path.is_file(), f"{label} is missing: {relative_path}")
    committed = git_blob_bytes(root, relative_path)
    require(sha256_bytes(committed) == expected_hash, f"{label} Git blob changed: {relative_path}")
    require(
        normalize_checkout_eol(path.read_bytes()) == normalize_checkout_eol(committed),
        f"{label} worktree content changed beyond checkout line endings: {relative_path}",
    )


def git_output(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    require(result.returncode == 0, f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def validate_phase_record(record: dict[str, Any]) -> None:
    require(record.get("scopeId") == "P1008-CONTRACT-CONFORMANCE-PHASE-ROUTING-20260722", "Unknown scope metadata")
    require(record.get("acceptanceStatus") == "CURRENT_PHASE_CONFORMANCE_AUTHORIZED", "Phase metadata is not authorized")
    require(record.get("contractVersion") == "1.1", "Unknown current contract version")
    require(record.get("currentPhase") == "PHASE_3B", "Unknown or unsupported phase")
    require(record.get("moduleExpectation") == "PRESENT", "Phase/module metadata conflict")
    require(record.get("modulePath") == MODULE_RELATIVE_PATH.as_posix(), "Unapproved module namespace")
    require(record.get("legacySuite") == "contracts/p1008_research_plugin/conformance/v1.0/run_contract_tests.py", "Legacy suite metadata conflict")
    require(record.get("currentSuite") == "contracts/p1008_research_plugin/conformance/v1.1/run_contract_tests.py", "Current suite metadata conflict")
    lineage = record.get("phaseLineage", {})
    require(lineage.get("legacyFrozenCommit") == "efbf0b2ec1aaf25d1d4f9025fe4a04b0f336dce7", "Legacy commit metadata conflict")
    require(lineage.get("firstModuleAuthorizedCommit") == "da8f1e286c5a3c2bb0c77fe176a277c3bbc6faa9", "Module authorization metadata conflict")
    require(record.get("openAiCallsAuthorized") is False, "OpenAI calls unexpectedly authorized")
    require(record.get("webSearchCallsAuthorized") is False, "Web Search calls unexpectedly authorized")
    require(record.get("canvaCallsAuthorized") is False, "Canva calls unexpectedly authorized")
    require(record.get("actionable") is False, "Current contract became actionable")


def validate_module_state(root: Path, expectation: str) -> None:
    module = root / MODULE_RELATIVE_PATH
    if expectation == "ABSENT":
        require(not module.exists(), "Phase 1B module exists early")
    elif expectation == "PRESENT":
        require(module.is_dir(), "Approved Phase 3B module is missing")
        require((module / "src" / "p1008_research_plugin").is_dir(), "Approved module package is missing")
    else:
        raise AssertionError(f"Unknown module expectation: {expectation}")


def validate_module_namespace(root: Path, module_path: str) -> list[str]:
    approved = Path(module_path).as_posix().rstrip("/")
    candidates = sorted(
        path.relative_to(root).as_posix()
        for path in (root / "modules").glob("p1008_research_plugin*")
        if path.exists()
    )
    require(candidates == [approved], f"Research module escaped approved namespace: {candidates}")
    return candidates


def _python_files(module_root: Path) -> Iterable[Path]:
    source_root = module_root / "src"
    return source_root.rglob("*.py") if source_root.is_dir() else []


def protected_write_violations(module_root: Path) -> list[str]:
    """Conservatively reject code combining protected roots with write sinks."""

    root_tokens = (
        "data/",
        "data\\",
        "rules/",
        "rules\\",
        "RULE_STATUS_MANIFEST",
        "warroom.sqlite",
        "HOLD",
        "MIDR",
        "MRD",
    )
    write_pattern = re.compile(
        r"write_text\s*\(|write_bytes\s*\(|\.open\s*\([^\n]*(?:['\"](?:w|a|x)[bt+]?['\"])|"
        r"csv\.writer\s*\(|(?:INSERT|UPDATE|DELETE|CREATE|DROP|ALTER|REPLACE)\s+",
        re.IGNORECASE,
    )
    violations: list[str] = []
    for path in _python_files(module_root):
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        if any(token.lower() in text.lower() for token in root_tokens) and write_pattern.search(text):
            violations.append(path.relative_to(module_root).as_posix())
    return violations


def actionable_violations(module_root: Path) -> list[str]:
    violations: list[str] = []
    true_pattern = re.compile(r"['\"]?actionable['\"]?\s*[:=]\s*True\b")
    for path in _python_files(module_root):
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        if true_pattern.search(text):
            violations.append(path.relative_to(module_root).as_posix())
    for path in (module_root / "config").rglob("*.json"):
        if path.name.endswith(".schema.json"):
            continue
        value = read_json(path)
        stack = [value]
        while stack:
            item = stack.pop()
            if isinstance(item, dict):
                if "actionable" in item and item["actionable"] is not False:
                    violations.append(path.relative_to(module_root).as_posix())
                    break
                stack.extend(item.values())
            elif isinstance(item, list):
                stack.extend(item)
    return sorted(set(violations))


def classify_authority_paths(paths: Iterable[str], record: dict[str, Any]) -> str:
    actual = set(paths)
    baselines = record.get("authorityBaselines", {})
    legacy = set(baselines.get("legacyFive", []))
    current = set(baselines.get("currentSix", []))
    phase_a_closure = set(baselines.get("phaseAClosureSix", []))
    integrated = set(baselines.get("integratedSeven", []))
    if actual == legacy:
        return "LEGACY_FIVE"
    if actual == current:
        return "CURRENT_SIX"
    if actual == phase_a_closure:
        return "PHASE_A_CLOSURE_SIX"
    if actual == integrated:
        return "INTEGRATED_SEVEN"
    allowed = legacy | current | phase_a_closure | integrated
    extras = sorted(actual - allowed)
    missing = sorted(legacy - actual)
    raise AssertionError(f"Unknown authority baseline; extras={extras}; missing={missing}")


def _manifest_entries(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    return manifest.get("authoritativeFiles", []) + manifest.get("nonAuthoritativeFiles", [])


def validate_authority_manifest(root: Path, record: dict[str, Any]) -> dict[str, Any]:
    manifest = read_json(root / "data" / "CSV_AUTHORITY_MANIFEST.json")
    entries = _manifest_entries(manifest)
    classification = classify_authority_paths((item["path"] for item in entries), record)
    actual_hashes: dict[str, str] = {}
    for entry in entries:
        path = root / entry["path"]
        require(path.is_file(), f"Authority file is missing: {entry['path']}")
        committed = git_blob_bytes(root, entry["path"])
        committed_hash = sha256_bytes(committed)
        require(
            committed_hash == entry["sha256"].upper(),
            f"Authority hash mismatch: {entry['path']}",
        )
        require(
            normalize_checkout_eol(path.read_bytes()) == normalize_checkout_eol(committed),
            f"Authority worktree content changed beyond checkout line endings: {entry['path']}",
        )
        actual_hashes[entry["path"]] = committed_hash

    receipt_verified = False
    if classification in {"PHASE_A_CLOSURE_SIX", "INTEGRATED_SEVEN"}:
        receipt_ref = record.get("authorityBaselineReceipts", {}).get(classification, {})
        receipt_path = receipt_ref.get("path", "")
        receipt_hash = receipt_ref.get("sha256", "")
        if classification == "INTEGRATED_SEVEN":
            receipt_path = CURRENT_AUTHORITY_AMENDMENT_PATH
            receipt_hash = CURRENT_AUTHORITY_AMENDMENT_SHA256
        require(receipt_path and receipt_hash, "Phase A authority receipt metadata is missing")
        receipt_file = root / receipt_path
        require(receipt_file.is_file(), "Phase A authority receipt is missing")
        receipt_committed = git_blob_bytes(root, receipt_path)
        require(
            sha256_bytes(receipt_committed) == receipt_hash,
            "Phase A authority receipt hash mismatch",
        )
        require(
            normalize_checkout_eol(receipt_file.read_bytes())
            == normalize_checkout_eol(receipt_committed),
            "Phase A authority receipt worktree changed beyond checkout line endings",
        )
        receipt = json.loads(receipt_committed.decode("utf-8-sig"))
        acceptance_status = receipt.get("acceptanceStatus")
        require(
            acceptance_status
            in {
                "EXISTING_OWNER_PUBLISHED_AUTHORITIES_PINNED_FOR_CI",
                "OWNER_APPROVED_FORMAL_AUTHORITY_PUBLISH",
                "OWNER_APPROVED_MARKET_ACTIVITY_STAGE2A_PUBLISH",
                "PHASE_A_AUTHORITY_DATA_CLOSURE_COMPLETE",
                "PHASE_A_FINAL_INTEGRATION_RECONCILED",
                "P1008_TWSE_AUTHORITY_INCREMENTAL_REMEDIATION_AMENDMENT",
            },
            "Phase A authority receipt is not accepted",
        )
        require(
            receipt.get("authorityFiles") == actual_hashes,
            "Phase A authority receipt does not match committed authority bytes",
        )
        if acceptance_status == "EXISTING_OWNER_PUBLISHED_AUTHORITIES_PINNED_FOR_CI":
            require(
                receipt.get("formalPublishExecutedByThisReceipt") is False,
                "Baseline CI receipt must not claim a formal publish",
            )
        elif acceptance_status == "OWNER_APPROVED_FORMAL_AUTHORITY_PUBLISH":
            require(
                receipt.get("formalPublishExecutedByThisReceipt") is True,
                "Formal authority publish receipt must record the publish",
            )
            require(
                receipt.get("ownerApprovalPhrases")
                == [
                    "OWNER_APPROVE_REMOVE_INVALID_DAILY_PRICE_2026-07-19",
                    "OWNER_APPROVE_DAILY_PRICE_GAPS_20260722_20260724",
                ],
                "Stage 1 Daily Price Owner approval phrases do not match",
            )
            daily_publish = receipt.get("dailyPricePublish", {})
            require(
                daily_publish.get("afterGapPublishSha256")
                == actual_hashes.get("data/2317_daily_price.csv"),
                "Stage 1 Daily Price publish hash mismatch",
            )
            require(
                daily_publish.get("beforeSha256")
                == "25567CE773F7270ED3B22AFBD9D2664E467A2F3D525425AFAE7F20631E56D1B4",
                "Stage 1 Daily Price prior authority hash mismatch",
            )
            require(
                daily_publish.get("afterRows") == 116
                and daily_publish.get("cutoff") == "2026-07-27"
                and daily_publish.get("removedDates") == ["2026-07-19"]
                and daily_publish.get("addedDates")
                == ["2026-07-22", "2026-07-24"],
                "Stage 1 Daily Price publish scope drifted",
            )
            for journal_name in ("removalJournal", "gapJournal"):
                journal = daily_publish.get(journal_name, {})
                require(
                    journal.get("status") == "PUBLISHED"
                    and journal.get("rollbackPerformed") is False
                    and re.fullmatch(r"[0-9A-F]{64}", journal.get("sha256", "")),
                    f"Stage 1 {journal_name} evidence is invalid",
                )
            manifest_ref = receipt.get("authorityManifest", {})
            require(
                manifest_ref.get("path") == "data/CSV_AUTHORITY_MANIFEST.json"
                and manifest_ref.get("sha256")
                == sha256_bytes(
                    git_blob_bytes(root, "data/CSV_AUTHORITY_MANIFEST.json")
                ),
                "Stage 1 authority manifest receipt mismatch",
            )
            prior = receipt.get("priorBaselineReceipt", {})
            require(
                prior.get("path")
                == "contracts/p1008_research_plugin/acceptance/v1.1/PHASE_A_AUTHORITY_BASELINE_RECEIPT.json"
                and prior.get("sha256")
                == sha256_bytes(git_blob_bytes(root, prior.get("path", ""))),
                "Stage 1 prior baseline receipt is not preserved",
            )
            market_decision = receipt.get("marketActivityDecision", {})
            require(
                market_decision.get("publishedInStage1") is False
                and market_decision.get("promotionEligible") is False
                and market_decision.get("formalSha256")
                == actual_hashes.get("data/2317_daily_market_activity.csv"),
                "Stage 1 improperly accepted Market Activity",
            )
        elif acceptance_status == "OWNER_APPROVED_MARKET_ACTIVITY_STAGE2A_PUBLISH":
            require(
                receipt.get("formalPublishExecutedByThisReceipt") is True,
                "Stage 2A receipt must record the formal publish",
            )
            require(
                receipt.get("ownerApprovalPhrase")
                == "OWNER_APPROVE_MARKET_ACTIVITY_20260720_20260727",
                "Stage 2A Market Activity Owner approval phrase does not match",
            )
            prior = receipt.get("priorStage1Receipt", {})
            require(
                prior.get("path")
                == "contracts/p1008_research_plugin/acceptance/v1.1/PHASE_A_DAILY_PRICE_STAGE1_PUBLISH_RECEIPT.json"
                and prior.get("sha256")
                == sha256_bytes(git_blob_bytes(root, prior.get("path", ""))),
                "Stage 2A prior Stage 1 receipt is not preserved",
            )
            market_publish = receipt.get("marketActivityPublish", {})
            require(
                market_publish.get("transactionStatus") == "PUBLISHED"
                and market_publish.get("candidateSha256")
                == "D48730840F5449BE8DF815F58D262173FACF4884593DE11D0B9AF89392792941"
                and market_publish.get("candidateReceiptSha256")
                == "DA3F4852BDF9652ADA3403ADC6E5D720E6F154E748C44077403A219D485BD606",
                "Stage 2A Market Activity candidate evidence is invalid",
            )
            require(
                market_publish.get("beforeFormalSha256")
                == "83AB695E478517DC11004D17CC1EAE98F6B320BE266A586E29DAD0FF28D663BD"
                and market_publish.get("afterFormalSha256")
                == actual_hashes.get("data/2317_daily_market_activity.csv"),
                "Stage 2A Market Activity authority hash mismatch",
            )
            require(
                market_publish.get("beforeRows") == 60
                and market_publish.get("afterRows") == 66
                and market_publish.get("cutoff") == "2026-07-27"
                and market_publish.get("publishedDates")
                == [
                    "2026-07-20",
                    "2026-07-21",
                    "2026-07-22",
                    "2026-07-23",
                    "2026-07-24",
                    "2026-07-27",
                ],
                "Stage 2A Market Activity publish scope drifted",
            )
            journal = market_publish.get("journal", {})
            require(
                journal.get("status") == "PUBLISHED"
                and journal.get("rollbackPerformed") is False
                and re.fullmatch(r"[0-9A-F]{64}", journal.get("sha256", ""))
                and market_publish.get("rollbackStatus") == "NOT_REQUIRED",
                "Stage 2A Market Activity journal evidence is invalid",
            )
            price_dependency = receipt.get("dailyPriceDependency", {})
            require(
                price_dependency.get("path") == "data/2317_daily_price.csv"
                and price_dependency.get("sha256")
                == actual_hashes.get("data/2317_daily_price.csv")
                and price_dependency.get("modifiedInStage2A") is False,
                "Stage 2A Daily Price dependency changed",
            )
            manifest_ref = receipt.get("authorityManifest", {})
            require(
                manifest_ref.get("path") == "data/CSV_AUTHORITY_MANIFEST.json"
                and manifest_ref.get("sha256")
                == sha256_bytes(
                    git_blob_bytes(root, "data/CSV_AUTHORITY_MANIFEST.json")
                ),
                "Stage 2A authority manifest receipt mismatch",
            )
        elif acceptance_status == "PHASE_A_AUTHORITY_DATA_CLOSURE_COMPLETE":
            require(
                receipt.get("formalPublishExecutedByThisReceipt") is False,
                "Final closure receipt must not claim a separate formal publish",
            )
            require(
                receipt.get("phaseAStatus") == "AUTHORITY_DATA_CLOSURE_COMPLETE"
                and receipt.get("candidateFirstLauncher") is True
                and receipt.get("automaticFormalCsvPublish") is False
                and receipt.get("automaticReportGeneration") is False
                and receipt.get("ownerGateRequired") is True
                and receipt.get("phaseBStarted") is False,
                "Final Phase A closure boundary drifted",
            )
            require(
                receipt.get("openAiCalls") == 0
                and receipt.get("webSearchCalls") == 0
                and receipt.get("canvaCalls") == 0,
                "Final Phase A closure recorded an unauthorized external call",
            )
            final_authorities = receipt.get("finalAuthorities", {})
            expected_final = {
                "dailyPrice": {
                    "path": "data/2317_daily_price.csv",
                    "sha256": "2581AF868AA0D8C4BFCEA913B156DBB515AF3929FAAE7D0FDC947EA4A8256304",
                    "rows": 116,
                    "cutoff": "2026-07-27",
                },
                "marketActivity": {
                    "path": "data/2317_daily_market_activity.csv",
                    "sha256": "FE7B33B649012E7D8143838793FE5ED6244BB2183B966C0DAD2C9775FB0E4807",
                    "rows": 66,
                    "cutoff": "2026-07-27",
                },
                "macro": {
                    "path": "data/macro_snapshot.csv",
                    "sha256": "30A4755E87CECD4230FA8A521DF485385A89AC2A4E1E2B5726CBFD14AB96C86F",
                    "rows": 39,
                    "cutoff": "2026-07-10",
                },
            }
            require(
                final_authorities == expected_final,
                "Final Phase A authority summary drifted",
            )
            chain = receipt.get("receiptChain", {})
            expected_chain_paths = {
                "baseline": "contracts/p1008_research_plugin/acceptance/v1.1/PHASE_A_AUTHORITY_BASELINE_RECEIPT.json",
                "stage1DailyPrice": "contracts/p1008_research_plugin/acceptance/v1.1/PHASE_A_DAILY_PRICE_STAGE1_PUBLISH_RECEIPT.json",
                "stage2aMarketActivity": "contracts/p1008_research_plugin/acceptance/v1.1/PHASE_A_MARKET_ACTIVITY_STAGE2A_PUBLISH_RECEIPT.json",
                "stage2bMacro": "contracts/p1008_research_plugin/acceptance/v1.1/PHASE_A_MACRO_STAGE2B_PUBLISH_RECEIPT.json",
            }
            for key, expected_path in expected_chain_paths.items():
                reference = chain.get(key, {})
                require(
                    reference.get("path") == expected_path
                    and reference.get("sha256")
                    == sha256_bytes(git_blob_bytes(root, expected_path)),
                    f"Final Phase A receipt chain mismatch: {key}",
                )
            row_identity = chain.get("rowIdentity", {})
            require(
                row_identity.get("path")
                == "runtime/phase_a_stage2b_review/P1008-PHASE-A-STAGE2B-ROW-IDENTITY-20260729/MACRO_STAGE2B_ROW_IDENTITY_RECEIPT.json"
                and row_identity.get("sha256")
                == "E72989762053D20665DD87DA263F8B4DB1E77D277A6A27FD6C8AABBFE4921B9D"
                and row_identity.get("runtimeEvidence") is True,
                "Final Phase A row-identity evidence mismatch",
            )
            manifest_reference = chain.get("authorityManifest", {})
            require(
                manifest_reference.get("path") == "data/CSV_AUTHORITY_MANIFEST.json"
                and manifest_reference.get("sha256")
                == sha256_bytes(
                    git_blob_bytes(root, "data/CSV_AUTHORITY_MANIFEST.json")
                ),
                "Final Phase A authority manifest chain mismatch",
            )
            stage2b_reference = chain["stage2bMacro"]
            stage2b = json.loads(
                git_blob_bytes(root, stage2b_reference["path"]).decode("utf-8-sig")
            )
            require(
                stage2b.get("acceptanceStatus")
                == "OWNER_APPROVED_MACRO_STAGE2B_PUBLISH"
                and stage2b.get("formalPublishExecutedByThisReceipt") is True
                and stage2b.get("approvalPhrase")
                == "OWNER_APPROVE_MACRO_HON_HAI_REV_YOY_REMEDIATION",
                "Stage 2B Macro Owner approval evidence is invalid",
            )
            require(
                stage2b.get("canonicalBeforeSha256")
                == "353025C29D678488F7022939C86C36CB15D3B348DC5876909D6779E56CFE213B"
                and stage2b.get("candidateSha256")
                == "30A4755E87CECD4230FA8A521DF485385A89AC2A4E1E2B5726CBFD14AB96C86F"
                and stage2b.get("rowIdentityReceiptSha256")
                == "E72989762053D20665DD87DA263F8B4DB1E77D277A6A27FD6C8AABBFE4921B9D"
                and stage2b.get("formalAfterSha256")
                == actual_hashes.get("data/macro_snapshot.csv")
                and stage2b.get("manifestAfterSha256")
                == sha256_bytes(
                    git_blob_bytes(root, "data/CSV_AUTHORITY_MANIFEST.json")
                ),
                "Stage 2B Macro hash evidence is invalid",
            )
            require(
                stage2b.get("beforeRows") == 39
                and stage2b.get("afterRows") == 39
                and stage2b.get("cutoff") == "2026-07-10"
                and stage2b.get("changedColumn") == "Hon_Hai_Rev_YoY"
                and stage2b.get("changedRecordCount") == 5
                and stage2b.get("canonicalOrdinals") == [1, 26, 27, 28, 29]
                and stage2b.get("physicalLines") == [23, 48, 49, 50, 51]
                and stage2b.get("addedRows") == 0
                and stage2b.get("removedRows") == 0
                and stage2b.get("unapprovedSevenRowsAccepted") is False,
                "Stage 2B Macro publish scope drifted",
            )
            require(
                stage2b.get("transactionStatus") == "PUBLISHED"
                and stage2b.get("rollbackTriggered") is False
                and stage2b.get("authorityFiles") == actual_hashes
                and stage2b.get("openAiCalls") == 0
                and stage2b.get("webSearchCalls") == 0
                and stage2b.get("canvaCalls") == 0
                and stage2b.get("actionable") is False,
                "Stage 2B Macro transaction evidence is invalid",
            )
        elif acceptance_status == "PHASE_A_FINAL_INTEGRATION_RECONCILED":
            require(
                classification == "INTEGRATED_SEVEN"
                and receipt.get("baselineId") == "INTEGRATED_SEVEN",
                "Final integration receipt is bound to the wrong baseline",
            )
            require(
                receipt.get("formalPublishExecutedByThisReceipt") is False
                and receipt.get("candidateFirstLauncher") is True
                and receipt.get("automaticFormalCsvPublish") is False
                and receipt.get("automaticReportGeneration") is False
                and receipt.get("ownerGateRequired") is True
                and receipt.get("phaseBStarted") is False,
                "Final integration boundary drifted",
            )
            prior = receipt.get("priorFinalClosureReceipt", {})
            require(
                prior.get("path")
                == "contracts/p1008_research_plugin/acceptance/v1.1/PHASE_A_AUTHORITY_DATA_CLOSURE_RECEIPT.json"
                and prior.get("sha256")
                == sha256_bytes(git_blob_bytes(root, prior.get("path", ""))),
                "Final integration prior closure receipt mismatch",
            )
            evidence = receipt.get("committedRowIdentityEvidence", {})
            evidence_path = evidence.get("path", "")
            require(
                evidence_path
                == "contracts/p1008_research_plugin/acceptance/v1.1/evidence/PHASE_A_MACRO_ROW_IDENTITY_RECEIPT.json"
                and evidence.get("sha256")
                == "E72989762053D20665DD87DA263F8B4DB1E77D277A6A27FD6C8AABBFE4921B9D"
                and evidence.get("byteIdenticalToApprovedRuntimeEvidence") is True,
                "Committed Macro row identity evidence metadata mismatch",
            )
            evidence_committed = git_blob_bytes(root, evidence_path)
            require(
                sha256_bytes(evidence_committed) == evidence.get("sha256"),
                "Committed Macro row identity evidence hash mismatch",
            )
            require(
                normalize_checkout_eol((root / evidence_path).read_bytes())
                == normalize_checkout_eol(evidence_committed),
                "Committed Macro row identity worktree evidence drifted",
            )
            evidence_document = json.loads(evidence_committed.decode("utf-8-sig"))
            require(
                evidence_document.get("input", {}).get("source")
                == "CANONICAL_GIT_BLOB_ONLY"
                and evidence_document.get("canonical_statistics", {}).get(
                    "data_record_count"
                )
                == 39
                and evidence_document.get("hon_hai_rev_yoy_non_numeric_count") == 5
                and [
                    item.get("canonical_data_record_ordinal")
                    for item in evidence_document.get("row_identities", [])
                ]
                == [1, 26, 27, 28, 29],
                "Committed Macro row identity evidence content mismatch",
            )
            manifest_reference = receipt.get("authorityManifest", {})
            require(
                manifest_reference.get("path") == "data/CSV_AUTHORITY_MANIFEST.json"
                and manifest_reference.get("sha256")
                == sha256_bytes(
                    git_blob_bytes(root, "data/CSV_AUTHORITY_MANIFEST.json")
                ),
                "Final integration authority manifest mismatch",
            )
            summary = receipt.get("authoritySummary", {})
            require(
                summary
                == {
                    "verifiedFileCount": 7,
                    "dailyPriceRows": 116,
                    "dailyPriceCutoff": "2026-07-27",
                    "marketActivityRows": 66,
                    "marketActivityCutoff": "2026-07-27",
                    "cashFlowRows": 2,
                    "cashFlowCutoff": "2026Q1",
                    "macroRows": 39,
                    "macroCutoff": "2026-07-10",
                },
                "Final integration authority summary drifted",
            )
            cash_flow = receipt.get("cashFlowGovernance", {})
            require(
                cash_flow.get("sourcePr") == 4
                and cash_flow.get("sourceHead")
                == "41e2fae01fdaecdcdce2d3002f290941ca9dc332"
                and cash_flow.get("selectivePortOnly") is True
                and cash_flow.get("oldDailyPriceImported") is False
                and cash_flow.get("oldManifestImported") is False
                and cash_flow.get("formulaChecksRequired") is True
                and cash_flow.get("officialSourceRequired") is True
                and cash_flow.get("actionable") is False,
                "Cash Flow selective integration boundary drifted",
            )
            pr5 = receipt.get("pr5Reconciliation", {})
            require(
                pr5.get("sourcePr") == 5
                and pr5.get("comparedFileCount") == 6
                and pr5.get("uniqueGovernanceDifferenceCount") == 0
                and pr5.get("cherryPickOrMergePerformed") is False,
                "PR #5 reconciliation evidence drifted",
            )
            require(
                receipt.get("ruleHoldMidrModified") is False
                and receipt.get("runtimeSqliteModified") is False
                and receipt.get("openAiCalls") == 0
                and receipt.get("webSearchCalls") == 0
                and receipt.get("canvaCalls") == 0,
                "Final integration recorded an unauthorized state change or call",
            )
        else:
            require(
                classification == "INTEGRATED_SEVEN"
                and receipt.get("baselineId") == "INTEGRATED_SEVEN",
                "TWSE remediation amendment is bound to the wrong baseline",
            )
            previous = receipt.get("previousReceipt", {})
            previous_path = previous.get("path", "")
            require(
                previous_path
                == "contracts/p1008_research_plugin/acceptance/v1.1/PHASE_A_FINAL_INTEGRATION_AMENDMENT_RECEIPT.json"
                and previous.get("sha256")
                == "112373EA26100384F93B85A87415C5625DA34A1634B1C83E557C45BCC7829AAE",
                "TWSE remediation amendment predecessor identity mismatch",
            )
            previous_committed = git_blob_bytes(root, previous_path)
            require(
                sha256_bytes(previous_committed) == previous.get("sha256"),
                "Historical final-integration receipt hash changed",
            )
            require(
                normalize_checkout_eol((root / previous_path).read_bytes())
                == normalize_checkout_eol(previous_committed),
                "Historical final-integration receipt worktree changed",
            )
            previous_document = json.loads(previous_committed.decode("utf-8-sig"))
            require(
                previous_document.get("acceptanceStatus")
                == "PHASE_A_FINAL_INTEGRATION_RECONCILED"
                and previous_document.get("authorityFiles", {}).get(
                    "data/2317_daily_price.csv"
                )
                == "2581AF868AA0D8C4BFCEA913B156DBB515AF3929FAAE7D0FDC947EA4A8256304"
                and previous_document.get("authorityFiles", {}).get(
                    "data/2317_daily_market_activity.csv"
                )
                == "FE7B33B649012E7D8143838793FE5ED6244BB2183B966C0DAD2C9775FB0E4807",
                "Historical final-integration receipt content drifted",
            )
            previous_authority = receipt.get("previousGovernedAuthority", {})
            require(
                previous_authority
                == {
                    "dailyPriceSha256": "2581AF868AA0D8C4BFCEA913B156DBB515AF3929FAAE7D0FDC947EA4A8256304",
                    "dailyPriceRows": 116,
                    "dailyPriceCutoff": "2026-07-27",
                    "marketActivitySha256": "FE7B33B649012E7D8143838793FE5ED6244BB2183B966C0DAD2C9775FB0E4807",
                    "marketActivityRows": 66,
                    "marketActivityCutoff": "2026-07-27",
                },
                "TWSE remediation prior authority state drifted",
            )
            manifest_reference = receipt.get("authorityManifest", {})
            require(
                manifest_reference.get("path") == "data/CSV_AUTHORITY_MANIFEST.json"
                and manifest_reference.get("sha256")
                == sha256_bytes(
                    git_blob_bytes(root, "data/CSV_AUTHORITY_MANIFEST.json")
                ),
                "TWSE remediation current authority manifest mismatch",
            )
            require(
                receipt.get("authoritySummary")
                == {
                    "verifiedFileCount": 7,
                    "dailyPriceRows": 127,
                    "dailyPriceCutoff": "2026-08-11",
                    "marketActivityRows": 77,
                    "marketActivityCutoff": "2026-08-11",
                },
                "TWSE remediation current authority summary drifted",
            )
            lineage = receipt.get("remediationLineage", {})
            base_commit = lineage.get("baseCommit", "")
            remediation_commit = lineage.get("remediationCommit", "")
            require(
                base_commit == "ac53c1dd151e2e2645cdd3128a7dd70cfad7c582"
                and remediation_commit
                == "28537440c9bfd1cfbe89cbbe7cae51803c6aa9dc"
                and lineage.get("commitCount") == 1,
                "TWSE remediation commit lineage metadata drifted",
            )
            require(
                subprocess.run(
                    ["git", "-C", str(root), "merge-base", "--is-ancestor", base_commit, remediation_commit],
                    check=False,
                ).returncode
                == 0
                and git_output(root, "rev-list", "--count", f"{base_commit}..{remediation_commit}")
                == "1",
                "TWSE remediation commit lineage is invalid",
            )
            require(
                receipt.get("sourceAuthority")
                == "TWSE_OFFICIAL_STOCK_DAY_MONTHLY_CSV"
                and receipt.get("formalAuthorityPublication")
                == "ALREADY_COMPLETED_BY_REMEDIATION"
                and receipt.get("formalPublishExecutedByThisReceipt") is False
                and receipt.get("newAuthorityWriteDuringCiClosure") is False
                and receipt.get("governanceAcknowledgementOnly") is True
                and receipt.get("ownerGateRequired") is True
                and receipt.get("automaticReportGeneration") is False
                and receipt.get("ruleHoldMidrModified") is False
                and receipt.get("runtimeSqliteModified") is False
                and receipt.get("openAiCalls") == 0
                and receipt.get("webSearchCalls") == 0
                and receipt.get("canvaCalls") == 0,
                "TWSE remediation governance boundary drifted",
            )
        macro_decision = receipt.get("macroAuthorityDecision", {})
        require(
            macro_decision.get("unapprovedRowsAccepted") is False,
            "Unapproved macro authority rows were accepted",
        )
        require(
            macro_decision.get("requiredSha256")
            == actual_hashes.get("data/macro_snapshot.csv"),
            "Macro authority receipt hash mismatch",
        )
        require(receipt.get("actionable") is False, "Authority receipt became actionable")
        receipt_verified = True
    return {
        "baseline": classification,
        "filesVerified": len(entries),
        "authorityReceiptVerified": receipt_verified,
    }


def validate_immutable_v1(root: Path, record: dict[str, Any]) -> dict[str, Any]:
    immutable = record.get("immutableV1", {})
    artifacts = immutable.get("artifacts", {})
    require(artifacts, "Immutable v1 artifact metadata is missing")
    for relative_path, expected_hash in artifacts.items():
        validate_committed_text_artifact(root, relative_path, expected_hash, "Frozen v1 artifact")
    manifest = read_json(root / "contracts" / "p1008_research_plugin" / "v1.0" / "contract.manifest.json")
    require(manifest["rootHash"] == immutable.get("contractRootHash"), "Frozen v1 root hash changed")
    return {"artifactCount": len(artifacts), "rootHash": manifest["rootHash"]}


def _load_v1_runner() -> Any:
    spec = importlib.util.spec_from_file_location("p1008_v1_frozen_runner", V1_RUNNER_PATH)
    require(spec is not None and spec.loader is not None, "Cannot load frozen v1 runner")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def suite_phase_metadata() -> dict[str, Any]:
    record = read_json(ACCEPTANCE_PATH)
    validate_phase_record(record)
    validate_module_state(PACKAGE_ROOT, record["moduleExpectation"])
    namespaces = validate_module_namespace(PACKAGE_ROOT, record["modulePath"])

    lineage = record["phaseLineage"]
    legacy_commit = lineage["legacyFrozenCommit"]
    first_module_commit = lineage["firstModuleAuthorizedCommit"]
    current_base = lineage["currentBaseCommit"]
    require(git_output(PACKAGE_ROOT, "cat-file", "-e", f"{legacy_commit}^{{commit}}") == "", "Legacy commit is unavailable")
    require(git_output(PACKAGE_ROOT, "cat-file", "-e", f"{first_module_commit}^{{commit}}") == "", "Module authorization commit is unavailable")
    require(git_output(PACKAGE_ROOT, "cat-file", "-e", f"{current_base}^{{commit}}") == "", "Current base commit is unavailable")
    legacy_tree = git_output(PACKAGE_ROOT, "ls-tree", "-d", "--name-only", legacy_commit, record["modulePath"])
    module_tree = git_output(PACKAGE_ROOT, "ls-tree", "-d", "--name-only", first_module_commit, record["modulePath"])
    require(not legacy_tree, "Legacy frozen tree unexpectedly contains the module")
    require(module_tree == record["modulePath"], "First authorized module commit does not contain the module")
    require(subprocess.run(["git", "-C", str(PACKAGE_ROOT), "merge-base", "--is-ancestor", first_module_commit, "HEAD"], check=False).returncode == 0, "Current tree is not descended from the authorized module commit")

    for path_key, hash_key in (
        ("phase1bAcceptanceRecord", "phase1bAcceptanceSha256"),
        ("phase2aOwnerRecord", "phase2aOwnerRecordSha256"),
        ("phase3aOwnerRecord", "phase3aOwnerRecordSha256"),
    ):
        validate_committed_text_artifact(
            PACKAGE_ROOT,
            lineage[path_key],
            lineage[hash_key],
            f"Phase lineage record {path_key}",
        )
    return {"phase": record["currentPhase"], "moduleNamespaces": namespaces, "metadataDriven": True}


def suite_current_governance() -> dict[str, Any]:
    record = read_json(ACCEPTANCE_PATH)
    authority = validate_authority_manifest(PACKAGE_ROOT, record)
    module_root = PACKAGE_ROOT / record["modulePath"]
    write_violations = protected_write_violations(module_root)
    require(not write_violations, f"Module can write protected state: {write_violations}")
    act_violations = actionable_violations(module_root)
    require(not act_violations, f"Actionable output detected: {act_violations}")

    policy = read_json(V1_CONTRACT_ROOT / "policies" / "plugin_policy.json")
    require({"data/", "rules/"} <= set(policy["forbiddenWriteRoots"]), "Formal authority roots are not protected")
    require(policy["canModifyRuntimeSqlite"] is False, "Runtime SQLite mutation was enabled")
    require(policy["canChangeHold"] is False and policy["canChangeMidr"] is False, "HOLD/MIDR mutation was enabled")
    require(policy["actionable"] is False, "Frozen policy became actionable")

    rule_manifest = read_json(PACKAGE_ROOT / "rules" / "RULE_STATUS_MANIFEST.json")
    material = json.dumps(rule_manifest["rules"], ensure_ascii=False, separators=(",", ":"))
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest().upper()
    require(digest == rule_manifest["rulesDigestSha256"], "Rule manifest digest mismatch")
    require(all(item.get("actionable") is False for item in rule_manifest["rules"]), "Actionable formal rule detected")
    return {**authority, "protectedWriteViolations": 0, "actionableViolations": 0, "ruleDigestMatch": True}


def suite_api_continuity() -> dict[str, Any]:
    baseline = read_json(SCRIPT_ROOT.parent / "v1.0" / "fixtures" / "backward_compatibility_baseline.json")
    app_text = (PACKAGE_ROOT / "tools" / "p1008_app_server.py").read_text(encoding="utf-8-sig")
    missing = [path for path in baseline["existingAppApiPaths"] if path not in app_text]
    require(not missing, f"Legacy API route disappeared: {missing}")
    api = read_json(V1_CONTRACT_ROOT / "api" / "openapi.json")
    research_paths = set(api["paths"])
    require(all(path.startswith(baseline["researchApiPrefix"]) for path in research_paths), "Research API escaped approved namespace")
    require(not any(path.startswith(baseline["legacyApiPrefix"]) for path in research_paths), "Research API collided with legacy namespace")
    forbidden = re.compile(r"/(publish|trade|position|rule|shell|command|hold|midr)(/|$)", re.IGNORECASE)
    require(not [path for path in research_paths if forbidden.search(path)], "Unapproved API namespace exposed")
    return {"legacyRoutesVerified": len(baseline["existingAppApiPaths"]), "researchPathsVerified": len(research_paths)}


def _assigned_int_constants(path: Path) -> dict[str, int]:
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    values: dict[str, int] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, int):
            values[node.targets[0].id] = node.value.value
    return values


def suite_runtime_capability_gates() -> dict[str, Any]:
    module_root = PACKAGE_ROOT / MODULE_RELATIVE_PATH
    runner_path = module_root / "src" / "p1008_research_plugin" / "plugin_module" / "agent_runner.py"
    runner = runner_path.read_text(encoding="utf-8-sig")
    constants = _assigned_int_constants(runner_path)
    require(constants.get("OPENAI_CLIENT_MAX_RETRIES") == 0, "OpenAI client retry ceiling changed")
    require(constants.get("AGENT_RUN_MAX_TURNS") == 1, "Runner turn ceiling changed")
    require(constants.get("RESPONSES_MAX_TOOL_CALLS") == 1, "Hosted tool ceiling changed")
    require("parallel_tool_calls=False" in runner, "Parallel tool calls were enabled")
    require("max_retries=OPENAI_CLIENT_MAX_RETRIES" in runner, "Retry ceiling is not passed to the client")
    require("max_turns=AGENT_RUN_MAX_TURNS" in runner, "Turn ceiling is not passed to Runner")
    require('extra_args={"max_tool_calls": RESPONSES_MAX_TOOL_CALLS}' in runner, "Tool ceiling is not passed to Responses")

    tools_text = (module_root / "src" / "p1008_research_plugin" / "openai" / "tool_registry.py").read_text(encoding="utf-8-sig")
    require("build_hosted_web_search" in tools_text and "importlib.import_module" in tools_text, "Hosted Web Search is not lazy-gated")
    require("max_calls_per_run\": 1" in tools_text, "Web Search route ceiling changed")
    contracts_text = (module_root / "src" / "p1008_research_plugin" / "plugin_module" / "contracts.py").read_text(encoding="utf-8-sig")
    require("actionable: Literal[False]" in contracts_text, "Typed output no longer enforces actionable=false")
    require("manual_shadow: Literal[True]" in contracts_text, "Manual Shadow boundary disappeared")
    capability_schema = read_json(module_root / "config" / "phase3a" / "capability.schema.json")
    require(capability_schema["properties"]["actionable"].get("const") is False, "Capability schema no longer fixes actionable=false")
    return {"maxRetries": 0, "maxTurns": 1, "maxToolCalls": 1, "parallelToolCalls": False, "actionable": False}


def suite_v1_continuity() -> dict[str, Any]:
    record = read_json(ACCEPTANCE_PATH)
    immutable = validate_immutable_v1(PACKAGE_ROOT, record)
    v1 = _load_v1_runner()
    details: dict[str, Any] = {"immutableV1": immutable}
    for name in (
        "suite_ledger_replay",
        "suite_deterministic_research",
        "suite_contract_drift",
        "suite_openai_capability_boundary",
    ):
        details[name] = getattr(v1, name)()
    return details


SUITES: list[tuple[str, Callable[[], dict[str, Any]]]] = [
    ("PHASE_METADATA_AND_MODULE_ROUTING", suite_phase_metadata),
    ("CURRENT_GOVERNANCE_BOUNDARY", suite_current_governance),
    ("LEGACY_API_CONTINUITY", suite_api_continuity),
    ("CURRENT_RUNTIME_CAPABILITY_GATES", suite_runtime_capability_gates),
    ("FROZEN_V1_CONTINUITY", suite_v1_continuity),
]


def run_suite(suite_id: str, function: Callable[[], dict[str, Any]]) -> SuiteResult:
    started = time.perf_counter()
    try:
        return SuiteResult(suite_id, "PASS", round((time.perf_counter() - started) * 1000), function())
    except Exception as exc:
        return SuiteResult(suite_id, "FAIL", round((time.perf_counter() - started) * 1000), {}, f"{type(exc).__name__}: {exc}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate current P1008 phase-aware contract v1.1")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--no-write-report", action="store_true")
    args = parser.parse_args()
    if not args.all:
        parser.error("--all is required")

    protected_paths = [PACKAGE_ROOT / "data" / "CSV_AUTHORITY_MANIFEST.json", PACKAGE_ROOT / "rules" / "RULE_STATUS_MANIFEST.json"]
    before = {path: sha256_file(path) for path in protected_paths}
    results = [run_suite(suite_id, function) for suite_id, function in SUITES]
    for path, digest in before.items():
        require(sha256_file(path) == digest, f"Protected state changed during conformance: {path}")
    all_pass = all(item.status == "PASS" for item in results)
    report = {
        "reportId": "P1008_RESEARCH_CURRENT_CONFORMANCE_V1_1",
        "contractVersion": "1.1",
        "phase": read_json(ACCEPTANCE_PATH).get("currentPhase", "UNKNOWN"),
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "overallStatus": "PASS" if all_pass else "FAIL",
        "results": [asdict(item) for item in results],
        "safety": {"openAiCallsMade": 0, "webSearchCallsMade": 0, "canvaCallsMade": 0, "formalWrites": 0, "actionable": False},
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
