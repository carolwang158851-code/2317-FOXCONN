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
    ERRATA_RELATIVE = Path(
        "contracts/p1008_research_plugin/acceptance/errata/v2.0/"
        "OWNER_ACCEPTANCE_HASH_ERRATA.json"
    )
    PHASE3A_PARENT_SHA = "47dea688ad1e2041b24116b00d58281380700bd8"
    ACCEPTANCE_SHA256 = (
        "A056D8C139C254D04BEF9298DA34152D0CF5A18864D040E5B9B3FE7A226E0533"
    )
    OLD_MANIFEST_SHA256 = (
        "2686D044714E435CB4C1E63CB26B3BB555190F9A5BD21FE2C9439473DA998BE6"
    )
    MANIFEST_GIT_LF_SHA256 = (
        "6A1DFE54BA4FCA749C18FDA747969473A4903CF21001AAACA6078C6CC8FEB75F"
    )
    ERRATA_APPROVAL_REFERENCE = (
        "OWNER_APPROVE_P1008_PHASE3A_R_LINE_ENDING_"
        "REPRODUCIBILITY_REMEDIATION_TARGETFILES"
    )
    ERRATA_REASON = (
        "The accepted hash was calculated from a mixed LF/CRLF worktree; "
        "the replacement is the SHA-256 of the unchanged Phase 3A Git blob "
        "raw LF bytes."
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

    @classmethod
    def _expected_manifest_errata(cls) -> dict[str, Any]:
        return {
            "schemaVersion": "1.0",
            "recordId": "P1008_PHASE3A_R_LINE_ENDING_REPRODUCIBILITY_ERRATA",
            "phase": "Phase 3A-R Line-Ending Reproducibility Remediation",
            "phase3aParentSha": cls.PHASE3A_PARENT_SHA,
            "ownerAcceptancePath": cls.ACCEPTANCE_RELATIVE.as_posix(),
            "ownerAcceptanceSha256": cls.ACCEPTANCE_SHA256,
            "correction": {
                "fieldPath": "manifestSha256",
                "targetFile": (
                    "contracts/p1008_research_plugin/v2.0/contract.manifest.json"
                ),
                "oldSha256": cls.OLD_MANIFEST_SHA256,
                "newGitLfSha256": cls.MANIFEST_GIT_LF_SHA256,
                "reasonCode": "LINE_ENDING_REPRODUCIBILITY_DEFECT",
                "reason": cls.ERRATA_REASON,
            },
            "ownerApprovalReference": cls.ERRATA_APPROVAL_REFERENCE,
            "actionable": False,
        }

    @classmethod
    def _validate_manifest_errata(
        cls,
        errata: Mapping[str, Any],
        *,
        acceptance_sha: str,
        acceptance_manifest_sha: Any,
        manifest_sha: str,
    ) -> None:
        if dict(errata) != cls._expected_manifest_errata():
            raise RuntimeValidationError(
                "Manifest hash errata contains unsupported fields or values"
            )
        if acceptance_sha != cls.ACCEPTANCE_SHA256:
            raise RuntimeValidationError("Original Owner acceptance record drift")
        if acceptance_manifest_sha != cls.OLD_MANIFEST_SHA256:
            raise RuntimeValidationError("Original Owner acceptance binding drift")
        if manifest_sha != cls.MANIFEST_GIT_LF_SHA256:
            raise RuntimeValidationError("Frozen v2 manifest raw-byte drift")

    def verify(self) -> dict[str, Any]:
        v1 = ContractLoader(self.package_root).verify_manifest()
        root = (self.package_root / self.V2_RELATIVE).resolve()
        manifest_path = root / "contract.manifest.json"
        acceptance_path = (self.package_root / self.ACCEPTANCE_RELATIVE).resolve()
        errata_path = (self.package_root / self.ERRATA_RELATIVE).resolve()
        manifest = self._json(manifest_path)
        acceptance = self._json(acceptance_path)
        errata = self._json(errata_path)
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
        self._validate_manifest_errata(
            errata,
            acceptance_sha=self._sha(acceptance_path),
            acceptance_manifest_sha=acceptance.get("manifestSha256"),
            manifest_sha=self._sha(manifest_path),
        )
        bindings = {
            "acceptedRootHash": v2_root,
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
