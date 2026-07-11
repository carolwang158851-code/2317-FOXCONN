"""Read-only access to authority-manifest-listed P1008 data."""

from __future__ import annotations

import csv
import hashlib
import io
import json
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from ..contract_loader import ContractLoader


class AuthorityAdapterError(RuntimeError):
    """Raised when an authority input is missing, unlisted, or changed."""


@dataclass(frozen=True)
class CsvSnapshot:
    relative_path: str
    manifest_sha256: str
    actual_sha256: str
    headers: tuple[str, ...]
    rows: tuple[Mapping[str, str], ...]
    metadata_lines: tuple[str, ...]


class AuthorityAdapter:
    MANIFEST_PATH = "data/CSV_AUTHORITY_MANIFEST.json"
    RULE_MANIFEST_PATH = "rules/RULE_STATUS_MANIFEST.json"

    def __init__(self, package_root: Path | str, loader: ContractLoader) -> None:
        self.package_root = Path(package_root).resolve()
        self.loader = loader
        self._manifest = self._read_json(self._safe_package_path(self.MANIFEST_PATH))
        all_entries = self._manifest.get("authoritativeFiles", []) + self._manifest.get(
            "nonAuthoritativeFiles", []
        )
        self._entries = {entry["path"]: entry for entry in all_entries}
        if len(self._entries) != len(all_entries):
            raise AuthorityAdapterError("Duplicate authority manifest path")

    def _safe_package_path(self, relative_path: str) -> Path:
        raw = Path(relative_path)
        if raw.is_absolute() or ".." in raw.parts:
            raise AuthorityAdapterError(f"Unsafe package path: {relative_path}")
        resolved = (self.package_root / raw).resolve()
        if not resolved.is_relative_to(self.package_root):
            raise AuthorityAdapterError(f"Package path escapes root: {relative_path}")
        return resolved

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        try:
            value = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            raise AuthorityAdapterError(f"Cannot read JSON {path}: {exc}") from exc
        if not isinstance(value, dict):
            raise AuthorityAdapterError(f"Expected JSON object: {path}")
        return value

    @staticmethod
    def _sha256_bytes(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest().upper()

    @property
    def listed_paths(self) -> tuple[str, ...]:
        return tuple(sorted(self._entries))

    def manifest_summary(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "manifest_version": self._manifest.get("manifestVersion"),
                "approved_at": self._manifest.get("approvedAt"),
                "entry_count": len(self._entries),
                "actionable": False,
            }
        )

    def verify_all(self) -> Mapping[str, Any]:
        verified = []
        for relative_path in self.listed_paths:
            data, _entry = self._verified_bytes(relative_path)
            verified.append(
                {
                    "relative_path": relative_path,
                    "sha256": self._sha256_bytes(data),
                }
            )
        return MappingProxyType(
            {
                "verified_count": len(verified),
                "verified": tuple(MappingProxyType(item) for item in verified),
                "actionable": False,
            }
        )

    def _verified_bytes(self, relative_path: str) -> tuple[bytes, dict[str, Any]]:
        entry = self._entries.get(relative_path)
        if entry is None:
            raise AuthorityAdapterError(f"Path is not authority-listed: {relative_path}")
        path = self._safe_package_path(relative_path)
        if not path.is_file():
            raise AuthorityAdapterError(f"Authority file is missing: {relative_path}")
        data = path.read_bytes()
        actual_hash = self._sha256_bytes(data)
        expected_hash = str(entry.get("sha256", "")).upper()
        if not expected_hash or actual_hash != expected_hash:
            raise AuthorityAdapterError(f"Authority hash mismatch: {relative_path}")
        return data, entry

    def read_csv(self, relative_path: str) -> CsvSnapshot:
        data, entry = self._verified_bytes(relative_path)
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise AuthorityAdapterError(f"CSV is not UTF-8: {relative_path}") from exc

        metadata: list[str] = []
        data_lines: list[str] = []
        header_found = False
        for line in text.splitlines():
            stripped = line.strip()
            if not header_found and (not stripped or stripped.startswith("##")):
                if stripped.startswith("##"):
                    metadata.append(stripped)
                continue
            header_found = True
            data_lines.append(line)
        if not data_lines:
            raise AuthorityAdapterError(f"CSV header is missing: {relative_path}")

        reader = csv.DictReader(io.StringIO("\n".join(data_lines)))
        if not reader.fieldnames:
            raise AuthorityAdapterError(f"CSV header is invalid: {relative_path}")
        rows = tuple(MappingProxyType(dict(row)) for row in reader)
        return CsvSnapshot(
            relative_path=relative_path,
            manifest_sha256=str(entry["sha256"]).upper(),
            actual_sha256=self._sha256_bytes(data),
            headers=tuple(reader.fieldnames),
            rows=rows,
            metadata_lines=tuple(metadata),
        )

    def read_rule_manifest(self) -> Mapping[str, Any]:
        path = self._safe_package_path(self.RULE_MANIFEST_PATH)
        document = self._read_json(path)
        rules = document.get("rules")
        if not isinstance(rules, list):
            raise AuthorityAdapterError("Rule manifest rules are missing")
        material = json.dumps(rules, ensure_ascii=False, separators=(",", ":"))
        actual_digest = hashlib.sha256(material.encode("utf-8")).hexdigest().upper()
        if actual_digest != document.get("rulesDigestSha256"):
            raise AuthorityAdapterError("Rule manifest digest mismatch")
        if any(rule.get("actionable") is not False for rule in rules):
            raise AuthorityAdapterError("Actionable rule found")
        return MappingProxyType(
            {
                "manifest_version": document.get("manifestVersion"),
                "rules_digest": actual_digest,
                "rule_count": len(rules),
                "keep_disabled_count": sum(
                    rule.get("status") == "KEEP_DISABLED" for rule in rules
                ),
                "actionable": False,
            }
        )
