"""Deny-by-default registry loaded from local Phase 3A manifests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .contract import CapabilityContractError, CapabilityContractValidator
from .manifest import CapabilityManifest


class CapabilityRegistryError(RuntimeError):
    """Raised when registry configuration or lookup is invalid."""


class GovernedCapabilityRegistry:
    def __init__(self, config_root: Path) -> None:
        self.config_root = config_root.resolve()
        self.validator = CapabilityContractValidator()
        self.config = self._read_json(self.config_root / "capability_registry.json")
        self._validate_registry_config()
        self.manifests: dict[str, CapabilityManifest] = {}
        for relative in self.config["manifest_paths"]:
            path = self._safe_path(relative)
            manifest = self.validator.validate_mapping(self._read_json(path))
            if manifest.capability_id in self.manifests:
                raise CapabilityRegistryError("Duplicate capability id")
            self.manifests[manifest.capability_id] = manifest

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        try:
            value = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CapabilityRegistryError(f"Cannot read capability config: {path.name}") from exc
        if not isinstance(value, dict):
            raise CapabilityRegistryError("Capability config must be an object")
        return value

    def _safe_path(self, relative: str) -> Path:
        raw = Path(relative)
        if raw.is_absolute() or ".." in raw.parts:
            raise CapabilityRegistryError("Unsafe manifest path")
        path = (self.config_root / raw).resolve()
        if not path.is_relative_to(self.config_root) or not path.is_file():
            raise CapabilityRegistryError("Manifest path is missing or escapes config")
        return path

    def _validate_registry_config(self) -> None:
        if self.config.get("default_enabled") is not False:
            raise CapabilityRegistryError("Registry must deny by default")
        for key in (
            "production_enablement_allowed",
            "runtime_integration_authorized",
            "openai_production_authorized",
            "actionable",
        ):
            if self.config.get(key) is not False:
                raise CapabilityRegistryError(f"Registry boundary drift: {key}")
        paths = self.config.get("manifest_paths")
        if not isinstance(paths, list) or len(paths) != 6 or len(set(paths)) != 6:
            raise CapabilityRegistryError("Expected six unique capability manifests")

    def get(self, capability_id: str) -> CapabilityManifest:
        try:
            return self.manifests[capability_id]
        except KeyError as exc:
            raise CapabilityRegistryError(f"Unregistered capability: {capability_id}") from exc

    def require_shadow_enabled(self, capability_id: str) -> CapabilityManifest:
        manifest = self.get(capability_id)
        if not manifest.enabled or manifest.lifecycle_state != "SHADOW_ENABLED":
            raise CapabilityRegistryError(f"Capability is disabled: {capability_id}")
        return manifest

    def snapshot(self) -> dict[str, Any]:
        return {
            "framework_version": self.config["framework_version"],
            "enabled": sorted(
                key for key, item in self.manifests.items() if item.enabled
            ),
            "disabled": sorted(
                key for key, item in self.manifests.items() if not item.enabled
            ),
            "capabilities": [
                self.manifests[key].snapshot() for key in sorted(self.manifests)
            ],
            "production_enablement_allowed": False,
            "runtime_integration_authorized": False,
            "actionable": False,
        }
