"""Contract and typed-output validation for Phase 2A."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from ..contract_loader import ContractLoader


class RuntimeValidationError(RuntimeError):
    """Raised when contract or output validation fails."""


class RuntimeContractVerifier:
    V2_RELATIVE = Path("contracts/p1008_research_plugin/v2.0")
    ACCEPTANCE_RELATIVE = Path(
        "contracts/p1008_research_plugin/acceptance/v2.0/OWNER_ACCEPTANCE_RECORD.json"
    )

    def __init__(self, package_root: Path) -> None:
        self.package_root = package_root.resolve()

    @staticmethod
    def _json(path: Path) -> dict[str, Any]:
        try:
            value = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeValidationError(f"Cannot read frozen artifact: {path.name}") from exc
        if not isinstance(value, dict):
            raise RuntimeValidationError("Frozen JSON must be an object")
        return value

    @staticmethod
    def _sha(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest().upper()

    def verify(self) -> dict[str, Any]:
        v1 = ContractLoader(self.package_root).verify_manifest()
        root = (self.package_root / self.V2_RELATIVE).resolve()
        manifest_path = root / "contract.manifest.json"
        acceptance_path = (self.package_root / self.ACCEPTANCE_RELATIVE).resolve()
        manifest = self._json(manifest_path)
        acceptance = self._json(acceptance_path)
        lines: list[str] = []
        artifacts = manifest.get("artifacts")
        if not isinstance(artifacts, list) or len(artifacts) != manifest.get("artifactCount"):
            raise RuntimeValidationError("v2 manifest artifact count drift")
        declared: set[str] = set()
        for artifact in artifacts:
            relative = artifact.get("path")
            if (
                not isinstance(relative, str)
                or ".." in Path(relative).parts
                or relative in declared
            ):
                raise RuntimeValidationError("Unsafe v2 manifest path")
            declared.add(relative)
            path = (root / relative).resolve()
            if not path.is_relative_to(root) or not path.is_file():
                raise RuntimeValidationError("Missing v2 contract artifact")
            actual = self._sha(path)
            if actual != artifact.get("sha256") or path.stat().st_size != artifact.get(
                "sizeBytes"
            ):
                raise RuntimeValidationError(f"v2 artifact drift: {relative}")
            lines.append(f"{relative}|{actual}")
        material = "\n".join(sorted(lines, key=str.casefold)).encode("utf-8")
        v2_root = hashlib.sha256(material).hexdigest().upper()
        if v2_root != manifest.get("rootHash"):
            raise RuntimeValidationError("v2 root drift")
        excluded = {
            item
            for item in manifest.get("evidenceExcluded", [])
            if isinstance(item, str) and ".." not in Path(item).parts
        }
        actual = {
            path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()
        }
        if actual != declared | excluded:
            raise RuntimeValidationError("v2 contract artifact set drift")
        evidence_path = root / "validation" / "CONFORMANCE_EVIDENCE.json"
        evidence = self._json(evidence_path)
        summary = evidence.get("summary", {})
        if summary.get("checks") != 22 or summary.get("passed") != 22 or summary.get(
            "failed"
        ) != 0:
            raise RuntimeValidationError("v2 conformance evidence drift")
        bindings = {
            "acceptedRootHash": v2_root,
            "manifestSha256": self._sha(manifest_path),
            "conformanceEvidenceSha256": self._sha(evidence_path),
        }
        for key, expected in bindings.items():
            if acceptance.get(key) != expected:
                raise RuntimeValidationError(f"Owner acceptance binding drift: {key}")
        if acceptance.get("approvalToken") != (
            "OWNER_APPROVE_P1008_PHASE1C_V2_CONTRACT_FREEZE_TARGETFILES"
        ):
            raise RuntimeValidationError("Unexpected v2 Owner approval token")
        return {
            "v1_root": v1["root_hash"],
            "v2_root": v2_root,
            "v2_authoritative": acceptance.get("v2ContractAuthoritative") is True,
        }


class RuntimeValidator:
    TOP_LEVEL = frozenset(
        {
            "claims",
            "evidence",
            "counter_evidence",
            "knowledge_gaps",
            "sources",
            "confidence",
            "limitations",
            "owner_review_required",
            "actionable",
        }
    )
    CONFIDENCE = frozenset({"high", "medium", "low", "insufficient_data"})

    @staticmethod
    def _require_keys(value: Mapping[str, Any], expected: set[str], label: str) -> None:
        if set(value) != expected:
            raise RuntimeValidationError(f"{label} fields do not match the typed contract")

    def validate(self, output: Mapping[str, Any]) -> dict[str, Any]:
        self._require_keys(output, set(self.TOP_LEVEL), "output")
        if output["actionable"] is not False:
            raise RuntimeValidationError("Output actionable must be false")
        if output["confidence"] not in self.CONFIDENCE:
            raise RuntimeValidationError("Invalid confidence")
        for name in (
            "claims",
            "evidence",
            "counter_evidence",
            "knowledge_gaps",
            "sources",
            "limitations",
            "owner_review_required",
        ):
            if not isinstance(output[name], list):
                raise RuntimeValidationError(f"{name} must be an array")

        sources: set[str] = set()
        for source in output["sources"]:
            if not isinstance(source, dict):
                raise RuntimeValidationError("Source must be an object")
            self._require_keys(
                source,
                {"source_id", "source_tier", "source_name", "locator", "evidence_level"},
                "source",
            )
            if source["source_id"] in sources:
                raise RuntimeValidationError("Duplicate source id")
            sources.add(source["source_id"])

        evidence_ids: set[str] = set()
        for collection in (output["evidence"], output["counter_evidence"]):
            for item in collection:
                if not isinstance(item, dict):
                    raise RuntimeValidationError("Evidence must be an object")
                self._require_keys(
                    item,
                    {"evidence_id", "description", "source_ids", "actionable"},
                    "evidence",
                )
                if item["actionable"] is not False:
                    raise RuntimeValidationError("Evidence actionable must be false")
                if not item["source_ids"] or not set(item["source_ids"]).issubset(sources):
                    raise RuntimeValidationError("Evidence source linkage is invalid")
                evidence_ids.add(item["evidence_id"])

        for claim in output["claims"]:
            if not isinstance(claim, dict):
                raise RuntimeValidationError("Claim must be an object")
            self._require_keys(
                claim,
                {"claim_id", "claim", "evidence_ids", "confidence", "actionable"},
                "claim",
            )
            if claim["actionable"] is not False or claim["confidence"] not in self.CONFIDENCE:
                raise RuntimeValidationError("Claim boundary is invalid")
            if not claim["evidence_ids"] or not set(claim["evidence_ids"]).issubset(
                evidence_ids
            ):
                raise RuntimeValidationError("Unsupported claim must not pass validation")

        for gap in output["knowledge_gaps"]:
            if not isinstance(gap, dict):
                raise RuntimeValidationError("Knowledge gap must be an object")
            self._require_keys(gap, {"gap_id", "question", "reason", "actionable"}, "gap")
            if gap["actionable"] is not False:
                raise RuntimeValidationError("Knowledge gap actionable must be false")
        if not all(isinstance(item, str) and item for item in output["limitations"]):
            raise RuntimeValidationError("Limitations must be non-empty strings")
        if not all(
            isinstance(item, str) and item for item in output["owner_review_required"]
        ):
            raise RuntimeValidationError("Owner review items must be non-empty strings")
        return json.loads(json.dumps(output, ensure_ascii=False))
