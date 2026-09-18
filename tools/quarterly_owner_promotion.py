"""Build and apply an Owner-gated quarterly field-availability promotion."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import sys
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
SRC = PACKAGE_ROOT / "modules" / "p1008_research_plugin" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from p1008_research_plugin.quarterly_authority import (  # noqa: E402
    CONTRACT_RELATIVE_PATH,
    ROIC_UNAVAILABLE,
    load_quarterly_authority_contract,
    quarterly_metric_availability,
    validate_quarterly_authority_row,
)


MASTER_RELATIVE = Path("data/2317_master_v9.csv")
MANIFEST_RELATIVE = Path("data/CSV_AUTHORITY_MANIFEST.json")
APPROVAL_TOKEN = "OWNER_APPROVE_P1008_2026Q2_QUARTERLY_FIELD_AVAILABILITY"
REVIEW_ID = "P1008-2026Q2-QUARTERLY-FIELD-AVAILABILITY-OWNER-REVIEW"
Q2_RESULTS_SHA = "F014BE750095543B35ED2D482C0CF7A40B4A448167796F8AC4560AB928E609C5"
Q4_RESULTS_SHA = "91E4994341856DF0E1985DD87704DBE17E1E35CA66FF730CE8CA833CA7766EC0"
TWSE_Q2_BALANCE_ROW_SHA = "D0ACDC0092A4F9F89C6DA4FA538A5E10ED6D904CF9AF8B556C6054B203161B02"


class QuarterlyPromotionError(RuntimeError):
    """Fail-closed promotion error."""


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest().upper()


def canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def display_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def read_master(payload: bytes) -> tuple[list[str], list[str], list[dict[str, str]]]:
    text = payload.decode("utf-8-sig")
    lines = text.splitlines()
    header_index = next((index for index, line in enumerate(lines) if line.startswith("Quarter,")), None)
    if header_index is None:
        raise QuarterlyPromotionError("MASTER_HEADER_MISSING")
    prefix = lines[:header_index]
    reader = csv.DictReader(lines[header_index:])
    if not reader.fieldnames:
        raise QuarterlyPromotionError("MASTER_SCHEMA_MISSING")
    return prefix, list(reader.fieldnames), [dict(row) for row in reader]


def render_master(prefix: list[str], fields: list[str], rows: list[dict[str, str]]) -> bytes:
    stream = io.StringIO(newline="")
    if prefix:
        stream.write("\n".join(prefix) + "\n")
    writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n", extrasaction="raise")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def _append_note(value: str, note: str) -> str:
    parts = [item for item in str(value or "").split(";") if item]
    if note not in parts:
        parts.append(note)
    return ";".join(parts)


def build_q2_row(fields: list[str]) -> dict[str, str]:
    row = {field: "" for field in fields}
    row.update(
        {
            "Quarter": "2026Q2",
            "QuarterEndDate": "2026-06-30",
            "EstimatedEffectiveDate": "2026-08-12",
            "Revenue_Q_100M": "25258.94",
            "GrossMarginPct": "6.12",
            "OperatingIncome_Q_100M": "948.03",
            "OperatingMarginPct": "3.75",
            "OperatingMarginStatus": "ABOVE_MINIMUM_FLOOR",
            "TaxExpense_Q_1M": "24810",
            "TaxRev_Pct": "0.982",
            "EPS_Q": "4.27",
            "EPS_YoY_Pct": "+34.0",
            "EPS_TTM": "15.21",
            "BVPS": "136.02",
            "QuarterEndClose": "251.0",
            "CloseAdjusted": "251.0",
            "ROE_TTM_Pct": "12.61",
            "PB_QuarterEnd": "1.85",
            "PB_Adjusted": "1.85",
            "ROE_Signal": "ROE_STRONG_QUALIFIED",
            "CashDividend": "7.17179227",
            "DividendYield_Pct": "2.86",
            "FCFYield_Annual_Pct": "",
            "ROIC_Approx_Pct": "",
            "ROIC_Precise_Pct": "",
            "ROIC_Status": ROIC_UNAVAILABLE,
            "NOPAT_Annual_100M": "",
            "InvestedCapital_100M": "",
            "Cash_100M": "9630.02",
            "InterestBearingDebt_100M": "",
            "BalanceSheetDataQuality": "OFFICIAL_PARTIAL_FIELD_AVAILABILITY",
            "DataSource": "CSV_AUTHORITY",
            "DataSupportLevel": "L1",
            "LookaheadRisk": "LOW",
            "Notes": (
                "Q2_EPS_BVPS_ROE_OFFICIAL_FIELD_LEVEL_AUTHORITY;"
                "ROIC_INSUFFICIENT_DATA_NO_ESTIMATE;"
                "CONVERTIBLE_BOND_SHARE_COUNT_DILUTION_TRACKED_SEPARATELY"
            ),
        }
    )
    validate_quarterly_authority_row(row)
    return row


def field_lineage() -> dict[str, Any]:
    return {
        "2025Q4.EPS_Q": {
            "before": "3.25",
            "after": "3.23",
            "sourceSha256": Q4_RESULTS_SHA,
            "sourceLocator": (
                "https://image.honhai.com/upload/202603/law_talk/"
                "Hon_Hai_4Q25_Results_Chinese_20260316_2632.pdf#page=5"
            ),
            "correctionReason": "Official Q4 Results supersedes USER_CURATED_WEB_DATA.",
            "trendAnnotation": (
                "The 0.02 change is a source correction, not standalone evidence of earnings "
                "deterioration. Later convertible-bond/share-count dilution is tracked separately."
            ),
        },
        "2026Q2.EPS_Q": {
            "value": "4.27",
            "sourceSha256": Q2_RESULTS_SHA,
            "sourceLocator": "FY2026_Q2_RESULTS#page=6:Basic EPS",
        },
        "2026Q2.EPS_TTM": {
            "value": "15.21",
            "formula": "2025Q3 4.15 + official 2025Q4 3.23 + 2026Q1 3.56 + 2026Q2 4.27",
            "sourceSha256": Q2_RESULTS_SHA,
        },
        "2026Q2.BVPS": {
            "value": "136.02",
            "sourceSha256": TWSE_Q2_BALANCE_ROW_SHA,
            "sourceLocator": "TWSE t187ap07_L_ci#115Q2/2317:每股參考淨值",
        },
        "2026Q2.Average_BVPS": {
            "value": "120.58",
            "formula": "(2025Q2 105.14 + 2026Q2 136.02) / 2",
            "storage": "PROMOTION_RECEIPT_DERIVATION_ONLY",
        },
        "2026Q2.ROE_TTM_Pct": {
            "value": "12.61",
            "formula": "EPS_TTM 15.21 / Average_BVPS 120.58 * 100",
            "rounding": "2 decimal places",
        },
        "2026Q2.ROIC": {
            "availability": ROIC_UNAVAILABLE,
            "blankFields": [
                "ROIC_Precise_Pct",
                "NOPAT_Annual_100M",
                "InvestedCapital_100M",
                "InterestBearingDebt_100M",
            ],
            "reason": "Standardized tax-rate and same-definition invested-capital governance unresolved.",
        },
    }


def proposed_authority(package_root: Path) -> dict[str, Any]:
    load_quarterly_authority_contract(package_root)
    master_path = package_root / MASTER_RELATIVE
    manifest_path = package_root / MANIFEST_RELATIVE
    before_master = master_path.read_bytes()
    before_manifest = manifest_path.read_bytes()
    prefix, fields, rows = read_master(before_master)
    quarters = [row["Quarter"] for row in rows]
    if quarters.count("2025Q4") != 1 or "2026Q2" in quarters:
        raise QuarterlyPromotionError("QUARTERLY_PROMOTION_BASELINE_INVALID")
    q4 = next(row for row in rows if row["Quarter"] == "2025Q4")
    if q4.get("EPS_Q") != "3.25":
        raise QuarterlyPromotionError("Q4_EPS_EXPECTED_OLD_VALUE_MISSING")
    q4["EPS_Q"] = "3.23"
    q4["Notes"] = _append_note(q4.get("Notes", ""), "EPS_Q_OFFICIAL_CORRECTION_3.25_TO_3.23")
    q4["Notes"] = _append_note(q4["Notes"], "EPS_SOURCE_CORRECTION_NOT_STANDALONE_EARNINGS_DETERIORATION")
    rows.append(build_q2_row(fields))
    after_master = render_master(prefix, fields, rows)

    manifest = json.loads(before_manifest.decode("utf-8-sig"))
    entry = next(
        item for item in manifest.get("authoritativeFiles", [])
        if item.get("path") == MASTER_RELATIVE.as_posix()
    )
    entry["fileVersion"] = "v9.4"
    entry["sha256"] = sha256_bytes(after_master)
    entry["fileSizeBytes"] = len(after_master)
    entry["rowCount"] = len(rows)
    entry["validationStatus"] = "PASS_WITH_FIELD_LEVEL_AVAILABILITY"
    entry["fieldAvailabilityContract"] = CONTRACT_RELATIVE_PATH.as_posix()
    entry.setdefault("fieldOverrides", {})["ROIC_Precise_Pct"] = {
        "availabilityStatusField": "ROIC_Status",
        "unavailableStatus": ROIC_UNAVAILABLE,
        "conditionallyBlankFields": [
            "ROIC_Precise_Pct",
            "NOPAT_Annual_100M",
            "InvestedCapital_100M",
            "InterestBearingDebt_100M",
        ],
        "bareUnavailableTokensInvalid": True,
    }
    entry.setdefault("fieldOverrides", {})["EPS_Q"] = {
        **entry.get("fieldOverrides", {}).get("EPS_Q", {}),
        "2025Q4OfficialCorrection": field_lineage()["2025Q4.EPS_Q"],
        "2026Q2Quality": "OFFICIAL_HON_HAI_RESULTS_A1_L1",
    }
    entry.setdefault("fieldOverrides", {})["ROE_TTM_Pct"] = {
        "2026Q2Value": "12.61",
        "2026Q2Quality": "DERIVED_FROM_OFFICIAL_EPS_AND_BVPS",
        "latestValidQuarter": "2026Q2",
    }
    entry.setdefault("fieldOverrides", {})["ROIC_Status"] = {
        "2026Q2Value": ROIC_UNAVAILABLE,
        "latestValidQuarter": "2026Q1",
    }
    after_manifest = display_json_bytes(manifest)
    return {
        "beforeMaster": before_master,
        "afterMaster": after_master,
        "beforeManifest": before_manifest,
        "afterManifest": after_manifest,
        "rows": rows,
        "availability": quarterly_metric_availability(rows),
        "lineage": field_lineage(),
    }


def create_owner_review(package_root: Path, output_root: Path) -> Path:
    proposal = proposed_authority(package_root)
    output_root.mkdir(parents=True, exist_ok=False)
    candidate_master = output_root / "2317_master_v9.candidate.csv"
    candidate_manifest = output_root / "CSV_AUTHORITY_MANIFEST.candidate.json"
    candidate_master.write_bytes(proposal["afterMaster"])
    candidate_manifest.write_bytes(proposal["afterManifest"])
    review = {
        "schemaVersion": "P1008_QUARTERLY_OWNER_PROMOTION_REVIEW_V1",
        "reviewId": REVIEW_ID,
        "status": "OWNER_REVIEW_REQUIRED",
        "ownerApproval": False,
        "actionable": False,
        "publishAuthorized": False,
        "approvalTokenRequired": APPROVAL_TOKEN,
        "authority": {
            "master": {
                "path": MASTER_RELATIVE.as_posix(),
                "beforeSha256": sha256_bytes(proposal["beforeMaster"]),
                "afterSha256": sha256_bytes(proposal["afterMaster"]),
                "candidateSha256": sha256_bytes(candidate_master.read_bytes()),
            },
            "manifest": {
                "path": MANIFEST_RELATIVE.as_posix(),
                "beforeSha256": sha256_bytes(proposal["beforeManifest"]),
                "afterSha256": sha256_bytes(proposal["afterManifest"]),
                "candidateSha256": sha256_bytes(candidate_manifest.read_bytes()),
            },
        },
        "fieldLineage": proposal["lineage"],
        "availability": proposal["availability"],
        "rollback": "RESTORE_EXACT_BEFORE_BYTES_ON_ANY_PARTIAL_FAILURE",
    }
    (output_root / "owner_review.json").write_bytes(display_json_bytes(review))
    return output_root


def _atomic_replace(path: Path, payload: bytes) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_bytes(payload)
    os.replace(temporary, path)


def apply_owner_promotion(
    package_root: Path,
    review_root: Path,
    owner_approval: str,
    *,
    fail_after_master_for_test: bool = False,
) -> dict[str, Any]:
    if owner_approval != APPROVAL_TOKEN:
        raise QuarterlyPromotionError("OWNER_APPROVAL_REQUIRED")
    review_path = review_root / "owner_review.json"
    review = json.loads(review_path.read_text(encoding="utf-8"))
    master_path = package_root / MASTER_RELATIVE
    manifest_path = package_root / MANIFEST_RELATIVE
    before_master = master_path.read_bytes()
    before_manifest = manifest_path.read_bytes()
    if sha256_bytes(before_master) != review["authority"]["master"]["beforeSha256"]:
        raise QuarterlyPromotionError("MASTER_BEFORE_SHA_MISMATCH")
    if sha256_bytes(before_manifest) != review["authority"]["manifest"]["beforeSha256"]:
        raise QuarterlyPromotionError("MANIFEST_BEFORE_SHA_MISMATCH")
    after_master = (review_root / "2317_master_v9.candidate.csv").read_bytes()
    after_manifest = (review_root / "CSV_AUTHORITY_MANIFEST.candidate.json").read_bytes()
    if sha256_bytes(after_master) != review["authority"]["master"]["afterSha256"]:
        raise QuarterlyPromotionError("MASTER_CANDIDATE_SHA_MISMATCH")
    if sha256_bytes(after_manifest) != review["authority"]["manifest"]["afterSha256"]:
        raise QuarterlyPromotionError("MANIFEST_CANDIDATE_SHA_MISMATCH")
    _, _, rows = read_master(after_master)
    for row in rows:
        validate_quarterly_authority_row(row)
    receipt = deepcopy(review)
    receipt.update(
        {
            "schemaVersion": "P1008_QUARTERLY_OWNER_PROMOTION_RECEIPT_V1",
            "status": "PROMOTED",
            "ownerApproval": True,
            "ownerApprovalToken": owner_approval,
            "promotedAtUtc": datetime.now(timezone.utc).isoformat(),
        }
    )
    receipt_path = review_root / "promotion_receipt.json"
    try:
        _atomic_replace(master_path, after_master)
        if fail_after_master_for_test:
            raise QuarterlyPromotionError("INJECTED_PARTIAL_FAILURE")
        _atomic_replace(manifest_path, after_manifest)
        _atomic_replace(receipt_path, display_json_bytes(receipt))
    except Exception:
        _atomic_replace(master_path, before_master)
        _atomic_replace(manifest_path, before_manifest)
        if receipt_path.exists():
            receipt_path.unlink()
        raise
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package-root", type=Path, default=PACKAGE_ROOT)
    parser.add_argument("--review-root", type=Path, required=True)
    parser.add_argument("--owner-approval")
    args = parser.parse_args()
    if args.owner_approval:
        result = apply_owner_promotion(
            args.package_root.resolve(), args.review_root.resolve(), args.owner_approval
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        created = create_owner_review(args.package_root.resolve(), args.review_root.resolve())
        print(created)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
