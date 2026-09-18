"""Hash-bound Official IR input for governed QUARTERLY_EARNINGS Phase B1 runs."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from .phaseb1_common import canonical_json_bytes, sha256_bytes, sha256_file
from .plugin_module.contracts import (
    Confidence,
    EvidenceItem,
    EvidencePacket,
    PacketSignals,
    PluginId,
    RunType,
    Sentiment,
    SourceLocator,
    ValidatedEvidence,
)


class QuarterlyEarningsPacketError(RuntimeError):
    """The runtime Official IR authority does not match the governed packet."""


class QuarterlyEarningsPacket:
    EVENT_TYPE = "QUARTERLY_EARNINGS"
    CONFIG_REL = Path("modules/p1008_research_plugin/config/quarterly_earnings/FY2026_Q2.json")
    INTEGRATION_REL = Path("runtime/research_plugin/latest_content_integration.json")
    AUTHORITY_MANIFEST_REL = Path("data/CSV_AUTHORITY_MANIFEST.json")

    def __init__(
        self,
        package_root: Path,
        trigger_lineage: dict[str, Any],
        *,
        governed_evidence_root: Path | None = None,
    ) -> None:
        self.package_root = package_root.resolve()
        self.trigger_lineage = dict(trigger_lineage)
        self.config = self._read_json(self.package_root / self.CONFIG_REL, "quarterly packet")
        self.evidence_root, self.evidence_context = self._resolve_evidence_root(
            governed_evidence_root
        )
        self.integration = self._read_json(self.evidence_root / "research_plugin" / "latest_content_integration.json", "Official IR integration")
        self._bind_promoted_authority_lineage()
        self.event = self._validate_runtime_lineage()

    def _bind_promoted_authority_lineage(self) -> None:
        """Bind an Owner-promoted authority manifest without replacing IR authority.

        The quarterly financial facts remain bound to the approved Official IR
        document.  A Phase3A promotion is a separate data-authority lineage and
        is carried alongside that document so downstream candidates can prove
        which price/market/macro timeline was active for the same run.
        """
        path = self.package_root / self.AUTHORITY_MANIFEST_REL
        manifest = self._read_json(path, "CSV authority manifest")
        promotion = manifest.get("phase3aOwnerPromotion")
        if promotion is None:
            return
        q2 = promotion.get("q2Lineage") if isinstance(promotion, dict) else None
        valid = (
            manifest.get("authoritative") is True
            and manifest.get("actionable") is False
            and manifest.get("publishAuthorized") is False
            and manifest.get("ownerPromotionRequired") is False
            and manifest.get("classification")
            == "PROMOTED_CANONICAL_AUTHORITY_WITH_OBSERVATION_ONLY_SIDECARS"
            and isinstance(promotion, dict)
            and promotion.get("verifiedInputCount") == 6
            and isinstance(promotion.get("sourceManifestSha256"), str)
            and len(promotion["sourceManifestSha256"]) == 64
            and isinstance(q2, dict)
            and q2.get("quarter")
            == str(self.config["fiscalPeriod"]).replace("FY", "").replace(" ", "")
            and q2.get("basisClassification") == "DERIVED_VERIFIED"
            and q2.get("result") == "PASS"
            and q2.get("actionable") is False
            and isinstance(q2.get("closeoutReceiptSha256"), str)
            and len(q2["closeoutReceiptSha256"]) == 64
        )
        if not valid:
            raise QuarterlyEarningsPacketError("PROMOTED_AUTHORITY_Q2_LINEAGE_INVALID")
        self.evidence_context.update({
            "authority_manifest_version": str(manifest.get("manifestVersion") or ""),
            "authority_manifest_sha256": sha256_file(path),
            "authority_promotion_id": str(promotion.get("promotionId") or ""),
            "authority_source_manifest_sha256": str(promotion["sourceManifestSha256"]),
            "authority_q2_closeout_sha256": str(q2["closeoutReceiptSha256"]),
        })

    def _resolve_evidence_root(
        self, configured_root: Path | None
    ) -> tuple[Path, dict[str, str]]:
        root = configured_root.resolve() if configured_root else self.package_root / "runtime"
        if not root.is_dir():
            raise QuarterlyEarningsPacketError("GOVERNED_EVIDENCE_ROOT_MISSING")
        receipt = root / "report_trigger" / "latest_decision.json"
        integration = root / "research_plugin" / "latest_content_integration.json"
        if not receipt.is_file() or not integration.is_file():
            raise QuarterlyEarningsPacketError("GOVERNED_EVIDENCE_ROOT_INCOMPLETE")
        return root, {"mode": "EXTERNAL_GOVERNED_READ_ONLY" if configured_root else "LOCAL_RUNTIME",
                      "root": str(root), "trigger_receipt_sha256": sha256_file(receipt),
                      "integration_sha256": sha256_file(integration)}

    @property
    def generated_at_utc(self) -> str:
        return str(self.integration["evaluated_at_utc"])

    @property
    def as_of_date(self) -> str:
        return str(self.config["publicationDate"])

    @property
    def event_type(self) -> str:
        return self.EVENT_TYPE

    @property
    def values(self) -> dict[str, Any]:
        return self.config

    def deterministic_identity(self) -> dict[str, Any]:
        return {
            "eventType": self.EVENT_TYPE,
            "canonicalEventId": self.config["canonicalEventId"],
            "reportKey": self.config["reportKey"],
            "generatedAtUtc": self.generated_at_utc,
            "sourceSha256": self.config["expectedSourceSha256"],
            "governedPacketSha256": sha256_file(self.package_root / self.CONFIG_REL),
            "triggerReceiptSha256": self.trigger_lineage["triggerReceiptSha256"],
        }

    def validated_evidence(self) -> ValidatedEvidence:
        evidence_id = str(self.event["event_id"])
        fields = self._flat_fields()
        observed = datetime.fromisoformat(self.generated_at_utc.replace("Z", "+00:00")).astimezone(timezone.utc)
        locator = SourceLocator(
            source_id=str(self.event["source_id"]),
            locator=str(self.event["source_url"]),
            source_tier="OFFICIAL_COMPANY_INVESTOR_RELATIONS",
            observed_at=observed,
        )
        item = EvidenceItem(
            evidence_id=evidence_id,
            summary="Hon Hai FY2026 Q2 Results: official, receipt-backed financial and outlook packet.",
            changed_fields=sorted(fields),
            field_values={key: fields[key] for key in sorted(fields)},
            investment_impact="Quarterly earnings update requires margin, cash conversion, outlook, valuation and risk reassessment.",
            impact_direction=Sentiment.POSITIVE,
            confidence=Confidence.HIGH,
            catalysts=list(self.config["aiCloudNetworking"]) + list(self.config["officialOutlook"]),
            risks=[
                "H1 free cash flow is negative and is not a standalone Q2 cash-flow measure.",
                "Customer-specific Apple/iPhone, FX, tariff and policy impacts are not quantified in the Results document.",
            ],
            source_locators=[locator],
            data_quality_notes=[
                f"Raw PDF and receipt are SHA-256 bound: {self.config['expectedSourceSha256']}.",
                "The Results presentation states that financial information is not fully audited or reviewed.",
            ],
        )
        packet = EvidencePacket(
            packet_id=f"OFFICIAL-Q2-{self.config['expectedSourceSha256'][:16]}",
            plugin=PluginId.DATA_ANALYTICS,
            supported_run_types=[RunType.QUARTERLY_EARNINGS],
            as_of_date=date.fromisoformat(self.as_of_date),
            expires_on=date(2026, 11, 30),
            signals=PacketSignals(
                material_delta=True,
                numeric_anomaly=False,
                data_quality_warning=True,
                major_transaction=False,
                earnings_event=True,
                capital_allocation_event=False,
                financial_numbers=True,
            ),
            evidence=[item],
            executor="CODEX_PLUGIN_EXECUTOR",
            actionable=False,
        )
        return ValidatedEvidence(
            packets=[packet],
            evidence=[item],
            material_delta=True,
            changed_fields=sorted(fields),
            evidence_ids=[evidence_id],
            data_quality_notes=item.data_quality_notes,
        )

    def evidence_manifest(self) -> dict[str, Any]:
        evidence = self.validated_evidence()
        return {
            "status": "VALIDATED",
            "packetHashes": {
                evidence.packets[0].packet_id: sha256_bytes(
                    canonical_json_bytes(evidence.packets[0].model_dump(mode="json", by_alias=True))
                )
            },
            "evidenceIds": evidence.evidence_ids,
            "sourceLocators": [str(self.event["source_url"])],
            "sourceReceipt": str(self.event["provenance"]["receipt_path"]),
            "sourceHash": str(self.event["source_hash"]),
            "sourcePages": self.config["sourcePages"],
            "cashFlowStatus": str(self.config["cashFlow"]["status"]),
            "governedEvidence": self.evidence_context,
            "actionable": False,
        }

    def _validate_runtime_lineage(self) -> dict[str, Any]:
        expected = self.config
        lineage = self.trigger_lineage
        required = {
            "eventType": self.EVENT_TYPE,
            "canonicalEventId": expected["canonicalEventId"],
            "reportKey": expected["reportKey"],
            "actionable": False,
        }
        if any(lineage.get(key) != value for key, value in required.items()):
            raise QuarterlyEarningsPacketError("QUARTERLY_TRIGGER_LINEAGE_MISMATCH")
        if not (
            self.integration.get("report_key") == expected["reportKey"]
            and self.integration.get("research_state") == "TRIGGERED_INTERNAL_REPORT"
            and self.integration.get("handoff_eligible") is True
            and self.integration.get("actionable") is False
        ):
            raise QuarterlyEarningsPacketError("OFFICIAL_IR_INTEGRATION_IDENTITY_INVALID")
        scoped_events = [
            item for item in self.integration.get("validated_event_evidence", [])
            if item.get("canonical_event_id") == expected["canonicalEventId"]
            and item.get("event_type") == self.EVENT_TYPE
            and item.get("event_id") in lineage.get("evidenceIds", [])
        ]
        events = self._select_expected_events(scoped_events, expected)
        if not events:
            raise QuarterlyEarningsPacketError("OFFICIAL_IR_Q2_AUTHORITY_MISMATCH")
        if len(events) != 1:
            raise QuarterlyEarningsPacketError("OFFICIAL_IR_Q2_EVIDENCE_NOT_UNIQUE")
        event = events[0]
        provenance = event.get("provenance", {})
        receipt_path = self._safe_runtime_path(str(provenance.get("receipt_path") or ""))
        raw_path = self._safe_runtime_path(str(provenance.get("raw_artifact_path") or ""))
        receipt = self._read_json(receipt_path, "Official IR receipt")
        expected_hash = str(expected["expectedSourceSha256"])
        if sha256_file(raw_path) != expected_hash:
            raise QuarterlyEarningsPacketError("OFFICIAL_IR_Q2_RAW_HASH_MISMATCH")
        if not (
            receipt.get("receipt_id") == provenance.get("receipt_id")
            and receipt.get("raw_sha256") == expected_hash
            and receipt.get("source_hash") == expected_hash
            and receipt.get("document_type") == expected["expectedDocumentType"]
        ):
            raise QuarterlyEarningsPacketError("OFFICIAL_IR_Q2_RECEIPT_MISMATCH")
        self.evidence_context.update({
            "event_id": str(event["event_id"]),
            "official_receipt_id": str(receipt["receipt_id"]),
            "official_receipt_sha256": sha256_file(receipt_path),
            "raw_artifact_sha256": expected_hash,
        })
        return event

    @staticmethod
    def _select_expected_events(
        scoped_events: list[dict[str, Any]], expected: dict[str, Any]
    ) -> list[dict[str, Any]]:
        return [
            item for item in scoped_events
            if item.get("verification_status") == "OFFICIAL_VERIFIED"
            and item.get("source_hash") == expected["expectedSourceSha256"]
            and item.get("quality_metadata", {}).get("document_type")
            == expected["expectedDocumentType"]
            and item.get("quality_metadata", {}).get("raw_byte_hash_bound") is True
        ]

    def _safe_runtime_path(self, relative: str) -> Path:
        if not relative.startswith("runtime/") or ".." in Path(relative).parts:
            raise QuarterlyEarningsPacketError("UNSAFE_OFFICIAL_IR_RUNTIME_PATH")
        path = (self.evidence_root / Path(relative).relative_to("runtime")).resolve()
        if self.evidence_root not in path.parents:
            raise QuarterlyEarningsPacketError("UNSAFE_OFFICIAL_IR_RUNTIME_PATH")
        return path

    def _flat_fields(self) -> dict[str, str]:
        values: dict[str, str] = {}
        for group in ("financials", "cashFlow"):
            for key, value in self.config[group].items():
                values[f"{group}.{key}"] = str(value)
        values["officialOutlook"] = " | ".join(self.config["officialOutlook"])
        values["aiCloudNetworking"] = " | ".join(self.config["aiCloudNetworking"])
        return values

    @staticmethod
    def _read_json(path: Path, label: str) -> dict[str, Any]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise QuarterlyEarningsPacketError(f"{label.upper().replace(' ', '_')}_MISSING_OR_INVALID") from exc
        if not isinstance(payload, dict):
            raise QuarterlyEarningsPacketError(f"{label.upper().replace(' ', '_')}_INVALID")
        return payload
