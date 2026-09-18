"""Deterministic governance boundaries for the Phase 1B skeleton."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .contract_loader import ContractLoader


class GovernanceError(RuntimeError):
    """Raised when an operation would cross a frozen governance boundary."""


class GovernanceBoundary:
    def __init__(self, loader: ContractLoader) -> None:
        self.loader = loader
        self.policy = loader.load_json("policies/plugin_policy.json")
        loader.verify_selected_overlay("filesystem_governance")
        self.filesystem_policy = loader.load_selected_overlay_json(
            "filesystem_governance", "policies/plugin_policy.json"
        )
        self._apply_filesystem_overlay()
        self.gate_schema = loader.load_json("schemas/gate_result.schema.json")
        self.gate_types = frozenset(
            self.gate_schema["properties"]["gate_type"]["enum"]
        )
        self._assert_frozen_boundaries()

    def _apply_filesystem_overlay(self) -> None:
        overlay = self.filesystem_policy
        if overlay.get("status") != "OWNER_ACCEPTANCE_REQUIRED":
            raise GovernanceError("Filesystem governance Owner gate is missing")
        if overlay.get("ownerAcceptanceRequired") is not True:
            raise GovernanceError("Filesystem governance Owner gate is missing")
        if overlay.get("productionPromotionAuthorized") is not False:
            raise GovernanceError("Filesystem governance permits Production promotion")
        for base_key, addition_key in (
            ("writeRoots", "writeRootsAdditions"),
            ("forbiddenWriteRoots", "forbiddenWriteRootsAdditions"),
            ("forbiddenCapabilities", "forbiddenCapabilitiesAdditions"),
        ):
            additions = overlay.get(addition_key)
            if not isinstance(additions, list) or not all(
                isinstance(item, str) for item in additions
            ):
                raise GovernanceError(f"Invalid filesystem overlay: {addition_key}")
            self.policy[base_key] = list(
                dict.fromkeys([*self.policy[base_key], *additions])
            )
        self.policy["filesystemCapabilities"] = overlay.get(
            "filesystemCapabilities"
        )
        self.policy["filesystemBoundary"] = overlay.get("filesystemBoundary")

    @property
    def package_root(self) -> Path:
        return self.loader.package_root.resolve()

    @staticmethod
    def _has_parent_traversal(path: Path) -> bool:
        return ".." in path.parts

    @staticmethod
    def _is_reparse_point(path: Path) -> bool:
        if not path.exists() and not path.is_symlink():
            return False
        if path.is_symlink():
            return True
        is_junction = getattr(os.path, "isjunction", None)
        if is_junction is not None and is_junction(path):
            return True
        try:
            attributes = path.stat(follow_symlinks=False).st_file_attributes
        except (AttributeError, OSError):
            return False
        return bool(attributes & getattr(os, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))

    def _reject_reparse_chain(self, target: Path, allowed_root: Path) -> None:
        boundary = self.package_root.parent
        current = target
        while True:
            if current.exists() or current.is_symlink():
                if self._is_reparse_point(current):
                    raise GovernanceError(
                        f"Filesystem reparse boundary denied: {current}"
                    )
            if current == boundary or current == current.parent:
                break
            current = current.parent
        if not target.resolve(strict=False).is_relative_to(allowed_root):
            raise GovernanceError("Filesystem target escapes allowed root")

    def authorize_write(self, capability: str, target: Path | str) -> Path:
        """Return a canonical write target or fail closed without mutating it."""

        normalized = capability.strip().upper()
        configured = self.policy.get("filesystemCapabilities")
        boundary = self.policy.get("filesystemBoundary")
        if not isinstance(configured, dict) or not isinstance(boundary, dict):
            raise GovernanceError("Filesystem governance policy is unavailable")
        if boundary.get("failClosed") is not True:
            raise GovernanceError("Filesystem governance is not fail closed")
        roots = configured.get(normalized)
        if not isinstance(roots, list) or not roots:
            raise GovernanceError(f"Undeclared filesystem capability: {capability}")

        raw = Path(target)
        if self._has_parent_traversal(raw):
            raise GovernanceError(f"Filesystem traversal denied: {target}")
        candidate = raw if raw.is_absolute() else self.package_root / raw
        resolved = candidate.resolve(strict=False)

        allowed_roots: list[Path] = []
        for item in roots:
            relative = Path(item)
            if relative.is_absolute() or self._has_parent_traversal(relative):
                raise GovernanceError(
                    f"Unsafe filesystem capability root: {normalized}"
                )
            allowed = (self.package_root / relative).resolve(strict=False)
            if not allowed.is_relative_to(self.package_root):
                raise GovernanceError(
                    f"Filesystem capability escapes package: {normalized}"
                )
            allowed_roots.append(allowed)

        matched = next(
            (root for root in allowed_roots if resolved.is_relative_to(root)),
            None,
        )
        if matched is None:
            raise GovernanceError(
                f"Filesystem target is outside capability {normalized}: {resolved}"
            )

        forbidden = self.policy.get("forbiddenWriteRoots")
        if not isinstance(forbidden, list):
            raise GovernanceError("Forbidden filesystem roots are unavailable")
        for item in forbidden:
            if not isinstance(item, str):
                raise GovernanceError("Invalid forbidden filesystem root")
            if item.startswith("%"):
                continue
            relative = Path(item)
            if relative.is_absolute() or self._has_parent_traversal(relative):
                raise GovernanceError(f"Unsafe forbidden filesystem root: {item}")
            denied = (self.package_root / relative).resolve(strict=False)
            if resolved == denied or resolved.is_relative_to(denied):
                raise GovernanceError(f"Hard-denied filesystem target: {resolved}")

        if resolved == self.package_root or resolved.parent == self.package_root:
            raise GovernanceError("Package root authority writes are denied")
        self._reject_reparse_chain(resolved, matched)
        return resolved

    def authorize_tree_delete(
        self,
        capability: str,
        target: Path | str,
        *,
        owned_parent: Path | str,
        expected_name: str,
    ) -> Path:
        """Authorize deletion of one exact, run-owned disposable child tree."""

        resolved_parent = self.authorize_write(capability, owned_parent)
        resolved = self.authorize_write(capability, target)
        if not expected_name or Path(expected_name).name != expected_name:
            raise GovernanceError("Invalid disposable child identity")
        if resolved.parent != resolved_parent or resolved.name != expected_name:
            raise GovernanceError("Filesystem tree delete is not an owned exact child")
        if not resolved.is_dir():
            raise GovernanceError("Filesystem tree delete target is not a directory")
        for descendant in resolved.rglob("*"):
            if self._is_reparse_point(descendant):
                raise GovernanceError(
                    f"Filesystem reparse boundary denied: {descendant}"
                )
        return resolved

    def _assert_frozen_boundaries(self) -> None:
        expected = {
            "noAutoTrade": True,
            "noFormalCsvWrite": True,
            "noRuleEnablement": True,
            "canModifyRuntimeSqlite": False,
            "canChangeMidr": False,
            "canChangeHold": False,
            "canPublish": False,
            "actionable": False,
        }
        for key, required in expected.items():
            if self.policy.get(key) is not required:
                raise GovernanceError(f"Frozen governance boundary changed: {key}")

    def require_gate_type(self, gate_type: str) -> None:
        if gate_type not in self.gate_types:
            raise GovernanceError(f"Unregistered deterministic gate: {gate_type}")

    def gate_result(
        self,
        gate_id: str,
        gate_type: str,
        result: str,
        reason_codes: list[str] | None = None,
        violations: list[str] | None = None,
    ) -> dict[str, Any]:
        self.require_gate_type(gate_type)
        allowed_results = self.gate_schema["properties"]["result"]["enum"]
        if result not in allowed_results:
            raise GovernanceError(f"Invalid gate result: {result}")
        payload = {
            "gate_id": gate_id,
            "gate_type": gate_type,
            "evaluated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "result": result,
            "reason_codes": sorted(set(reason_codes or [])),
            "violations": list(violations or []),
            "owner_review_required": result == "OWNER_REVIEW_REQUIRED",
            "effective_change_applied": False,
            "actionable": False,
        }
        return payload

    def reject_capability(self, capability: str) -> None:
        normalized = capability.strip().upper()
        forbidden = set(self.policy.get("forbiddenCapabilities", []))
        if normalized in forbidden or normalized.startswith("OPENAI"):
            raise GovernanceError(f"Forbidden capability: {capability}")

    @staticmethod
    def assert_phase1b_status(payload: dict[str, Any]) -> None:
        if payload.get("openai_enabled") is not False:
            raise GovernanceError("OpenAI runtime must remain disabled in Phase 1B")
        if payload.get("actionable") is not False:
            raise GovernanceError("Phase 1B output cannot be actionable")
        if payload.get("implementation_status") != "SKELETON":
            raise GovernanceError("Phase 1B implementation status must be SKELETON")
