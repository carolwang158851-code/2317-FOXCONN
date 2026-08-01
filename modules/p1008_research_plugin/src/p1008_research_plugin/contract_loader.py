"""Read and validate the frozen Research Governance Contract."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urldefrag, urlparse


class ContractError(RuntimeError):
    """Raised when the frozen contract cannot be trusted or implemented."""


class ContractLoader:
    CONTRACT_VERSION = "1.0"
    MANIFEST_RELATIVE = Path("contracts/p1008_research_plugin/v1.0/contract.manifest.json")

    def __init__(self, package_root: Path | str) -> None:
        self.package_root = Path(package_root).resolve()
        self.contract_root = (
            self.package_root / "contracts" / "p1008_research_plugin" / "v1.0"
        ).resolve()
        if not self.contract_root.is_dir():
            raise ContractError(f"Frozen contract root is missing: {self.contract_root}")

    @staticmethod
    def discover_package_root(start: Path | str) -> Path:
        current = Path(start).resolve()
        if current.is_file():
            current = current.parent
        for candidate in (current, *current.parents):
            contract = candidate / ContractLoader.MANIFEST_RELATIVE
            if contract.is_file():
                return candidate
        raise ContractError(f"Cannot discover P1008 package root from {start}")

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        try:
            value = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ContractError(f"Cannot parse contract JSON {path}: {exc}") from exc
        if not isinstance(value, dict):
            raise ContractError(f"Contract JSON must be an object: {path}")
        return value

    @staticmethod
    def sha256_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest().upper()

    def manifest(self) -> dict[str, Any]:
        return self._read_json(self.contract_root / "contract.manifest.json")

    def _safe_contract_path(self, relative_path: str | Path) -> Path:
        raw = Path(relative_path)
        if raw.is_absolute() or ".." in raw.parts:
            raise ContractError(f"Unsafe contract path: {relative_path}")
        resolved = (self.contract_root / raw).resolve()
        if not resolved.is_relative_to(self.contract_root):
            raise ContractError(f"Contract path escapes frozen root: {relative_path}")
        return resolved

    def load_json(self, relative_path: str | Path) -> dict[str, Any]:
        path = self._safe_contract_path(relative_path)
        if not path.is_file():
            raise ContractError(f"Contract artifact is missing: {relative_path}")
        return self._read_json(path)

    def verify_manifest(self) -> dict[str, Any]:
        manifest = self.manifest()
        if manifest.get("contractVersion") != self.CONTRACT_VERSION:
            raise ContractError("Unexpected frozen contract version")
        artifacts = manifest.get("artifacts")
        if not isinstance(artifacts, list):
            raise ContractError("Contract manifest artifacts are missing")

        declared_paths: set[str] = set()
        root_lines: list[str] = []
        for artifact in artifacts:
            relative = artifact.get("path")
            if not isinstance(relative, str) or relative in declared_paths:
                raise ContractError(f"Invalid or duplicate artifact path: {relative}")
            declared_paths.add(relative)
            path = self._safe_contract_path(relative)
            if not path.is_file():
                raise ContractError(f"Frozen artifact is missing: {relative}")
            actual_hash = self.sha256_file(path)
            if actual_hash != artifact.get("sha256"):
                raise ContractError(f"Frozen artifact hash drift: {relative}")
            if path.stat().st_size != artifact.get("sizeBytes"):
                raise ContractError(f"Frozen artifact size drift: {relative}")
            root_lines.append(f"{relative}|{actual_hash}")

        actual_paths = {
            path.relative_to(self.contract_root).as_posix()
            for path in self.contract_root.rglob("*")
            if path.is_file() and path.name != "contract.manifest.json"
        }
        if actual_paths != declared_paths:
            drift = sorted(actual_paths ^ declared_paths)
            raise ContractError(f"Frozen artifact set drift: {drift}")

        material = "\n".join(sorted(root_lines, key=str.casefold)).encode("utf-8")
        root_hash = hashlib.sha256(material).hexdigest().upper()
        if root_hash != manifest.get("rootHash"):
            raise ContractError("Frozen contract root hash drift")
        return {
            "contract_version": self.CONTRACT_VERSION,
            "artifact_count": len(declared_paths),
            "root_hash": root_hash,
        }

    @staticmethod
    def _walk_refs(value: Any) -> Iterable[str]:
        if isinstance(value, dict):
            ref = value.get("$ref")
            if isinstance(ref, str):
                yield ref
            for child in value.values():
                yield from ContractLoader._walk_refs(child)
        elif isinstance(value, list):
            for child in value:
                yield from ContractLoader._walk_refs(child)

    def resolve_references(self) -> dict[str, int]:
        manifest = self.manifest()
        checked = 0
        internal = 0
        for artifact in manifest["artifacts"]:
            relative = artifact["path"]
            if not relative.endswith(".json"):
                continue
            document = self.load_json(relative)
            base = Path(relative).parent
            for reference in self._walk_refs(document):
                checked += 1
                target, _fragment = urldefrag(reference)
                if not target:
                    internal += 1
                    continue
                parsed = urlparse(target)
                if parsed.scheme or parsed.netloc:
                    raise ContractError(f"Remote contract $ref is forbidden: {reference}")
                candidate = (base / target).as_posix()
                resolved = (self.contract_root / candidate).resolve()
                if not resolved.is_relative_to(self.contract_root) or not resolved.is_file():
                    raise ContractError(f"Unresolved contract $ref in {relative}: {reference}")
        return {"references_checked": checked, "internal_references": internal}

    @staticmethod
    def _matches_type(value: Any, expected: str) -> bool:
        if expected == "null":
            return value is None
        if expected == "boolean":
            return isinstance(value, bool)
        if expected == "integer":
            return isinstance(value, int) and not isinstance(value, bool)
        if expected == "number":
            return isinstance(value, (int, float)) and not isinstance(value, bool)
        if expected == "string":
            return isinstance(value, str)
        if expected == "array":
            return isinstance(value, list)
        if expected == "object":
            return isinstance(value, dict)
        return False

    @staticmethod
    def _valid_datetime(value: str) -> bool:
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return False
        return True

    def validate_status(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Validate the deterministic subset used by plugin_status.schema.json."""
        schema = self.load_json("schemas/plugin_status.schema.json")
        required = set(schema["required"])
        properties = schema["properties"]
        missing = sorted(required - set(payload))
        if missing:
            raise ContractError(f"Status payload missing fields: {missing}")
        if schema.get("additionalProperties") is False:
            extra = sorted(set(payload) - set(properties))
            if extra:
                raise ContractError(f"Status payload has unknown fields: {extra}")

        for name, rule in properties.items():
            if name not in payload:
                continue
            value = payload[name]
            expected_types = rule.get("type")
            if isinstance(expected_types, str):
                expected_types = [expected_types]
            if expected_types and not any(self._matches_type(value, item) for item in expected_types):
                raise ContractError(f"Status field {name} has invalid type")
            if "const" in rule and value != rule["const"]:
                raise ContractError(f"Status field {name} violates const")
            if "enum" in rule and value not in rule["enum"]:
                raise ContractError(f"Status field {name} violates enum")
            if value is not None and isinstance(value, (int, float)) and not isinstance(value, bool):
                if "minimum" in rule and value < rule["minimum"]:
                    raise ContractError(f"Status field {name} is below minimum")
                if "maximum" in rule and value > rule["maximum"]:
                    raise ContractError(f"Status field {name} is above maximum")
            if rule.get("format") == "date-time" and value is not None:
                if not isinstance(value, str) or not self._valid_datetime(value):
                    raise ContractError(f"Status field {name} is not date-time")
        return json.loads(json.dumps(payload, ensure_ascii=False))
