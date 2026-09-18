"""Append-only, test-root JSONL ledger store."""

from __future__ import annotations

import hashlib
import json
import math
import os
from decimal import Decimal
from pathlib import Path
from typing import Any

from ..contract_loader import ContractLoader
from ..events.catalog import EventCatalog
from ..governance import GovernanceBoundary, GovernanceError


class LedgerError(RuntimeError):
    """Raised when a ledger write or replay violates the frozen format."""


GENESIS_HASH = "0" * 64
RECORD_FIELDS = frozenset(
    {
        "ledger_id",
        "sequence",
        "contract_version",
        "recorded_at",
        "previous_hash",
        "record_hash",
        "event",
        "actionable",
    }
)


def _canonical_number(value: int | float) -> str:
    if isinstance(value, int):
        if abs(value) > 9_007_199_254_740_991:
            raise LedgerError("Integer exceeds the RFC 8785 interoperable range")
        return str(value)
    if not math.isfinite(value):
        raise LedgerError("Non-finite number cannot be canonicalized")
    if value == 0:
        return "0"
    decimal_value = Decimal(repr(value))
    magnitude = abs(value)
    if 1e-6 <= magnitude < 1e21:
        fixed = format(decimal_value, "f")
        if "." in fixed:
            fixed = fixed.rstrip("0").rstrip(".")
        return fixed

    sign = "-" if decimal_value.is_signed() else ""
    digits_tuple = decimal_value.copy_abs().normalize().as_tuple()
    digits = "".join(str(digit) for digit in digits_tuple.digits)
    exponent = len(digits) + digits_tuple.exponent - 1
    fraction = digits[1:].rstrip("0")
    mantissa = digits[0] + (f".{fraction}" if fraction else "")
    exponent_sign = "+" if exponent >= 0 else ""
    return f"{sign}{mantissa}e{exponent_sign}{exponent}"


def canonical_json(value: Any) -> str:
    """Serialize the I-JSON subset using RFC 8785 ordering and numbers."""
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return _canonical_number(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if isinstance(value, list):
        return "[" + ",".join(canonical_json(item) for item in value) + "]"
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise LedgerError("Canonical JSON object keys must be strings")
        keys = sorted(
            value,
            key=lambda key: key.encode("utf-16be", errors="surrogatepass"),
        )
        return "{" + ",".join(
            f"{canonical_json(key)}:{canonical_json(value[key])}" for key in keys
        ) + "}"
    raise LedgerError(f"Unsupported canonical JSON type: {type(value).__name__}")


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest().upper()


class LedgerStore:
    """A ledger store that refuses all repository/live roots in Phase 1B."""

    def __init__(
        self,
        package_root: Path | str,
        sandbox_root: Path | str,
        loader: ContractLoader,
        catalog: EventCatalog,
    ) -> None:
        self.package_root = Path(package_root).resolve()
        self.sandbox_root = Path(sandbox_root).resolve()
        self.loader = loader
        self.catalog = catalog
        try:
            self.governance = GovernanceBoundary(loader)
            self.sandbox_root = self.governance.authorize_write(
                "RESEARCH_PLUGIN_LEDGER", self.sandbox_root
            )
        except GovernanceError as exc:
            raise LedgerError(f"Ledger sandbox denied: {exc}") from exc
        formats = loader.load_json("ledgers/ledger_formats.json")
        if not formats["appendOnly"] or formats["inPlaceUpdateAllowed"]:
            raise LedgerError("Frozen ledger policy is not append-only")
        if formats["deleteAllowed"] or formats["truncateAllowed"]:
            raise LedgerError("Frozen ledger delete/truncate boundary changed")
        self.formats = formats
        self.ledgers = {item["ledgerId"]: item for item in formats["ledgers"]}

    def _ledger_path(self, ledger_id: str) -> Path:
        config = self.ledgers.get(ledger_id)
        if config is None:
            raise LedgerError(f"Unknown ledger: {ledger_id}")
        relative = Path(config["relativePath"])
        if relative.is_absolute() or ".." in relative.parts:
            raise LedgerError(f"Unsafe frozen ledger path: {relative}")
        path = (self.sandbox_root / relative).resolve()
        try:
            path = self.governance.authorize_write("RESEARCH_PLUGIN_LEDGER", path)
        except GovernanceError as exc:
            raise LedgerError(f"Ledger path escapes sandbox: {ledger_id}") from exc
        if not path.is_relative_to(self.sandbox_root):
            raise LedgerError(f"Ledger path escapes selected sandbox: {ledger_id}")
        return path

    @staticmethod
    def _hash_input(record: dict[str, Any]) -> dict[str, Any]:
        return {
            key: record[key]
            for key in (
                "ledger_id",
                "sequence",
                "contract_version",
                "recorded_at",
                "previous_hash",
                "event",
            )
        }

    def append_event(self, ledger_id: str, event: dict[str, Any]) -> dict[str, Any]:
        event = self.catalog.validate_event(event)
        config = self.ledgers.get(ledger_id)
        if config is None:
            raise LedgerError(f"Unknown ledger: {ledger_id}")
        if event["aggregate_type"] not in config["aggregateTypes"]:
            raise LedgerError(
                f"Aggregate {event['aggregate_type']} cannot be written to {ledger_id}"
            )
        existing = self.read_records(ledger_id)
        sequence = len(existing) + 1
        previous_hash = existing[-1]["record_hash"] if existing else GENESIS_HASH
        record = {
            "ledger_id": ledger_id,
            "sequence": sequence,
            "contract_version": "1.0",
            "recorded_at": event["occurred_at"],
            "previous_hash": previous_hash,
            "event": event,
            "actionable": False,
        }
        record["record_hash"] = canonical_hash(self._hash_input(record))
        path = self._ledger_path(ledger_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(canonical_json(record) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return dict(record)

    def read_records(
        self, ledger_id: str, expected_count: int | None = None
    ) -> list[dict[str, Any]]:
        path = self._ledger_path(ledger_id)
        if not path.exists():
            if expected_count not in (None, 0):
                raise LedgerError(f"Ledger record count mismatch: {ledger_id}")
            return []
        if not path.is_file():
            raise LedgerError(f"Ledger path is not a file: {ledger_id}")
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError) as exc:
            raise LedgerError(f"Cannot read ledger {ledger_id}: {exc}") from exc
        records: list[dict[str, Any]] = []
        previous_hash = GENESIS_HASH
        config = self.ledgers[ledger_id]
        for index, line in enumerate(lines, start=1):
            if not line.strip():
                raise LedgerError(f"Blank ledger record in {ledger_id}")
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise LedgerError(f"Malformed ledger JSON at {ledger_id}:{index}") from exc
            if not isinstance(record, dict) or set(record) != RECORD_FIELDS:
                raise LedgerError(f"Ledger record shape mismatch at {ledger_id}:{index}")
            if record["ledger_id"] != ledger_id:
                raise LedgerError(f"ledger_id mismatch at {ledger_id}:{index}")
            if record["sequence"] != index:
                raise LedgerError(f"Sequence mismatch at {ledger_id}:{index}")
            if record["contract_version"] != "1.0" or record["actionable"] is not False:
                raise LedgerError(f"Contract/actionable mismatch at {ledger_id}:{index}")
            if record["previous_hash"] != previous_hash:
                raise LedgerError(f"previous_hash mismatch at {ledger_id}:{index}")
            expected_hash = canonical_hash(self._hash_input(record))
            if record["record_hash"] != expected_hash:
                raise LedgerError(f"record_hash mismatch at {ledger_id}:{index}")
            event = self.catalog.validate_event(record["event"])
            if event["aggregate_type"] not in config["aggregateTypes"]:
                raise LedgerError(f"Aggregate mismatch at {ledger_id}:{index}")
            previous_hash = record["record_hash"]
            records.append(record)
        if expected_count is not None and len(records) != expected_count:
            raise LedgerError(f"Ledger record count mismatch: {ledger_id}")
        return records

    def read_all(self) -> dict[str, list[dict[str, Any]]]:
        return {ledger_id: self.read_records(ledger_id) for ledger_id in sorted(self.ledgers)}
