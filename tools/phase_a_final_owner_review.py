"""Build the P1008 Phase A Final Owner Review Package without formal writes.

The builder is intentionally offline.  It consumes an already preserved TWSE
monthly receipt, creates review-only candidates under runtime/, and proves that
all formal authority bytes remain unchanged.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import subprocess
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from owner_publish_csv_v2 import (
    DAILY_PRICE_GAPS_EXPECTED_FORMAL_SHA256,
    INVALID_DAILY_PRICE_APPROVAL_PHRASE,
    build_invalid_daily_price_removal_preview,
    market_activity_approval_phrase,
    validate_daily_price_publish_rows,
)
from warroom_macro_remediation import build_candidate as build_macro_candidate
from warroom_macro_remediation import is_numeric_or_blank, read_macro
from warroom_market_activity_updater import (
    FORMAL_FIELDS as MARKET_FIELDS,
    load_offline_month,
    parse_twse_month,
    read_formal_activity,
    source_url,
)


FORMAL_DAILY = Path("data/2317_daily_price.csv")
FORMAL_MARKET = Path("data/2317_daily_market_activity.csv")
FORMAL_MACRO = Path("data/macro_snapshot.csv")
MANIFEST = Path("data/CSV_AUTHORITY_MANIFEST.json")
TARGET_GAP_DATES = ("2026-07-22", "2026-07-24")
FULL_MARKET_DATES = (
    "2026-07-20",
    "2026-07-21",
    "2026-07-22",
    "2026-07-23",
    "2026-07-24",
    "2026-07-27",
)
EXPECTED_RAW_SHA256 = (
    "5F796822BD279DA8843E6BAA19CC238FAD9E9801874247A98DD5045379D299B5"
)
DAILY_GAP_REVIEW_PHRASE = "OWNER_APPROVE_DAILY_PRICE_GAPS_20260722_20260724"
MACRO_REVIEW_PHRASE = "OWNER_APPROVE_MACRO_HON_HAI_REV_YOY_REMEDIATION"


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest().upper()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def atomic_write(path: Path, value: bytes) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_bytes(value)
    os.replace(temporary, path)


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    atomic_write(
        path,
        (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
    )


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames:
            raise ValueError(f"CSV header is missing: {path}")
        return list(reader.fieldnames), [dict(row) for row in reader]


def render_csv(header: list[str], rows: list[dict[str, Any]]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=header, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8")


def committed_sha(package_root: Path, relative_path: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(package_root), "show", f"HEAD:{relative_path.as_posix()}"],
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        return "NOT_COMMITTED"
    return sha256_bytes(result.stdout)


def formal_hashes(package_root: Path) -> dict[str, str]:
    manifest = read_json(package_root / MANIFEST)
    entries = manifest.get("authoritativeFiles", []) + manifest.get(
        "nonAuthoritativeFiles", []
    )
    return {
        item["path"]: sha256_file(package_root / item["path"])
        for item in entries
        if (package_root / item["path"]).is_file()
    }


def nearest_supporting_rows(
    rows: list[dict[str, str]], target_date: str
) -> tuple[dict[str, str], dict[str, str]]:
    eligible = [
        row
        for row in rows
        if date.fromisoformat(row["Date"]).weekday() < 5
        and row["DataSupportLevel"].startswith("OFFICIAL_TWSE")
    ]
    before = [row for row in eligible if row["Date"] < target_date]
    after = [row for row in eligible if row["Date"] > target_date]
    if not before or not after:
        raise ValueError(f"Cannot derive authority context for {target_date}")
    left, right = before[-1], after[0]
    if (left["QuarterKey"], left["BVPS_ref"]) != (
        right["QuarterKey"],
        right["BVPS_ref"],
    ):
        raise ValueError(f"QuarterKey/BVPS is not uniquely determined for {target_date}")
    return left, right


def build_daily_gap_candidate(
    package_root: Path,
    twse_rows: dict[str, dict[str, Any]],
    output_dir: Path,
) -> dict[str, Any]:
    header, formal_rows = read_csv(package_root / FORMAL_DAILY)
    formal_dates = {row["Date"] for row in formal_rows}
    candidate_rows: list[dict[str, str]] = []
    review_rows: list[dict[str, Any]] = []
    for target_date in TARGET_GAP_DATES:
        if target_date in formal_dates:
            raise ValueError(f"Daily Price gap is no longer missing: {target_date}")
        if target_date not in twse_rows:
            raise ValueError(f"TWSE receipt does not contain {target_date}")
        left, right = nearest_supporting_rows(formal_rows, target_date)
        twse = twse_rows[target_date]
        close = Decimal(str(twse["close"]))
        bvps = Decimal(left["BVPS_ref"])
        pb = Decimal(str(round(float(close) / float(bvps), 3)))
        row = {
            "Date": target_date,
            "Close": str(close),
            "QuarterKey": left["QuarterKey"],
            "BVPS_ref": left["BVPS_ref"],
            "PB_daily": str(pb),
            "DataSupportLevel": "OFFICIAL_TWSE_A1",
            "Status": "STAGING_CANDIDATE",
        }
        candidate_rows.append(row)
        review_rows.append(
            {
                "date": target_date,
                "twse_url": twse["source_url"],
                "twse_close": str(close),
                "derived_quarter_key": row["QuarterKey"],
                "derived_bvps_ref": row["BVPS_ref"],
                "derived_pb_daily": row["PB_daily"],
                "derivation_evidence": {
                    "previous_formal_date": left["Date"],
                    "next_formal_date": right["Date"],
                    "formula": "round(TWSE Close / BVPS_ref, 3)",
                },
            }
        )

    publish_validation = [
        [
            row[name] if name != "Status" else "OK"
            for name in header
        ]
        for row in candidate_rows
    ]
    validate_daily_price_publish_rows(header, publish_validation)
    candidate_bytes = render_csv(header, candidate_rows)
    candidate_path = output_dir / "2317_daily_price_20260722_20260724.candidate.csv"
    atomic_write(candidate_path, candidate_bytes)
    return {
        "status": "OWNER_REVIEW_REQUIRED",
        "candidate_path": str(candidate_path),
        "candidate_sha256": sha256_bytes(candidate_bytes),
        "rows": review_rows,
        "approval_phrase": DAILY_GAP_REVIEW_PHRASE,
        "formal_csv_modified": False,
        "promotion_eligible": False,
        "actionable": False,
    }


def build_expected_daily_after(
    removal_candidate: Path,
    gap_candidate: Path,
) -> dict[str, Any]:
    header, rows = read_csv(removal_candidate)
    candidate_header, candidate_rows = read_csv(gap_candidate)
    if candidate_header != header:
        raise ValueError("Daily gap candidate schema mismatch")
    for row in candidate_rows:
        row["Status"] = "OK"
    combined = rows + candidate_rows
    combined.sort(key=lambda item: item["Date"])
    dates = [row["Date"] for row in combined]
    if dates != sorted(set(dates)):
        raise ValueError("Expected Daily Price authority is not unique and increasing")
    expected = render_csv(header, combined)
    return {
        "sha256": sha256_bytes(expected),
        "rows": len(combined),
        "cutoff": dates[-1],
        "price_by_date": {row["Date"]: row["Close"] for row in combined},
    }


def build_market_candidate(
    package_root: Path,
    twse_rows: dict[str, dict[str, Any]],
    expected_price: dict[str, Any],
    output_dir: Path,
) -> dict[str, Any]:
    formal_rows = read_formal_activity(package_root / FORMAL_MARKET)
    formal_dates = {row["date"] for row in formal_rows}
    price_by_date = expected_price["price_by_date"]
    candidate_rows: list[dict[str, Any]] = []
    review_rows: list[dict[str, Any]] = []
    for target_date in FULL_MARKET_DATES:
        if target_date in formal_dates:
            raise ValueError(f"Market Activity candidate duplicates {target_date}")
        twse = twse_rows.get(target_date)
        if twse is None:
            raise ValueError(f"TWSE receipt is missing {target_date}")
        formal_close = price_by_date.get(target_date)
        if formal_close is None:
            raise ValueError(f"Expected Daily Price authority is missing {target_date}")
        if Decimal(formal_close) != Decimal(str(twse["close"])):
            raise ValueError(f"TWSE/formal Close mismatch for {target_date}")
        row = {field: twse[field] for field in MARKET_FIELDS}
        candidate_rows.append(row)
        review_rows.append(
            {
                "date": target_date,
                "volume": row["trade_volume"],
                "value": row["trade_value"],
                "transactions": row["transaction_count"],
                "twse_url": row["source_url"],
                "twse_close": str(twse["close"]),
                "formal_price_close": formal_close,
                "source_month": row["source_month"],
            }
        )

    candidate_bytes = render_csv(list(MARKET_FIELDS), candidate_rows)
    candidate_path = (
        output_dir
        / "2317_daily_market_activity_20260720_20260727.complete.candidate.csv"
    )
    atomic_write(candidate_path, candidate_bytes)
    combined_rows = formal_rows + [
        {field: str(row[field]) for field in MARKET_FIELDS}
        for row in candidate_rows
    ]
    expected_bytes = render_csv(list(MARKET_FIELDS), combined_rows)
    return {
        "status": "OWNER_REVIEW_REQUIRED",
        "candidate_path": str(candidate_path),
        "candidate_sha256": sha256_bytes(candidate_bytes),
        "candidate_rows": review_rows,
        "expected_manifest_entry": {
            "path": FORMAL_MARKET.as_posix(),
            "sha256": sha256_bytes(expected_bytes),
            "rowCount": len(combined_rows),
            "cutoffDate": FULL_MARKET_DATES[-1],
            "lastPublishedAt": "OWNER_PUBLISH_TIME_UTC",
        },
        "approval_phrase": market_activity_approval_phrase(list(FULL_MARKET_DATES)),
        "formal_csv_modified": False,
        "promotion_eligible": False,
        "actionable": False,
    }


def build_stage1_market_activity_candidate(
    package_root: Path,
    receipt_dir: Path,
    output_dir: Path,
) -> dict[str, Any]:
    package_root = package_root.resolve()
    receipt_dir = receipt_dir.resolve()
    output_dir = output_dir.resolve()
    runtime_root = (package_root / "runtime").resolve()
    if not output_dir.is_relative_to(runtime_root):
        raise ValueError("Stage 1 Market Activity review must remain under runtime/")
    if output_dir.exists():
        raise FileExistsError(output_dir)
    if sha256_file(package_root / FORMAL_DAILY) != DAILY_PRICE_GAPS_EXPECTED_FORMAL_SHA256:
        raise ValueError("Formal Daily Price is not the approved Stage 1 authority")
    output_dir.mkdir(parents=True)

    protected_paths = (FORMAL_DAILY, FORMAL_MARKET, FORMAL_MACRO, MANIFEST)
    protected_before = {
        path.as_posix(): sha256_file(package_root / path)
        for path in protected_paths
    }
    raw_path = receipt_dir / "2026-07.twse.raw.csv"
    source_receipt_path = receipt_dir / "2026-07.receipt.json"
    raw, source_receipt = load_offline_month(receipt_dir, "2026-07")
    if sha256_bytes(raw) != EXPECTED_RAW_SHA256:
        raise ValueError("Approved TWSE raw receipt SHA mismatch")
    if source_receipt["request_url"] != source_url("2026-07"):
        raise ValueError("TWSE receipt URL is not the approved official channel")
    twse_rows = parse_twse_month(raw, "2026-07")

    _, formal_price_rows = read_csv(package_root / FORMAL_DAILY)
    dates = [row["Date"] for row in formal_price_rows]
    if dates != sorted(set(dates)):
        raise ValueError("Formal Daily Price dates are not unique and increasing")
    expected_price = {
        "price_by_date": {row["Date"]: row["Close"] for row in formal_price_rows}
    }
    market = build_market_candidate(
        package_root, twse_rows, expected_price, output_dir
    )
    protected_after = {
        path.as_posix(): sha256_file(package_root / path)
        for path in protected_paths
    }
    if protected_after != protected_before:
        raise ValueError("Stage 1 Market Activity review changed formal authority bytes")

    receipt_payload = {
        "schema_version": "1.0",
        "receipt_id": "P1008_PHASE_A_STAGE1_MARKET_ACTIVITY_CANDIDATE_20260729",
        "status": "OWNER_REVIEW_REQUIRED",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "formal_daily_price": {
            "path": FORMAL_DAILY.as_posix(),
            "sha256": protected_before[FORMAL_DAILY.as_posix()],
            "rows": len(formal_price_rows),
            "cutoff": dates[-1],
        },
        "twse_source": {
            **source_receipt,
            "source_receipt_path": str(source_receipt_path),
            "source_receipt_sha256": sha256_file(source_receipt_path),
            "raw_artifact_path": str(raw_path),
            "raw_artifact_sha256": sha256_file(raw_path),
            "http_calls_this_build": 0,
        },
        "candidate": {
            "path": market["candidate_path"],
            "sha256": market["candidate_sha256"],
            "rows": len(market["candidate_rows"]),
            "dates": [row["date"] for row in market["candidate_rows"]],
            "expected_manifest_entry": market["expected_manifest_entry"],
        },
        "close_checks": market["candidate_rows"],
        "formal_hashes_before": protected_before,
        "formal_hashes_after": protected_after,
        "formal_hashes_unchanged": True,
        "formal_market_activity_modified": False,
        "formal_macro_modified": False,
        "promotion_eligible": False,
        "network_calls": 0,
        "openai_api_calls": 0,
        "actionable": False,
    }
    receipt_path = output_dir / "MARKET_ACTIVITY_CANDIDATE_RECEIPT.json"
    atomic_json(receipt_path, receipt_payload)
    return {
        **market,
        "receipt_path": str(receipt_path),
        "receipt_sha256": sha256_file(receipt_path),
        "formal_hashes_unchanged": True,
        "network_calls": 0,
    }


def enrich_macro_review(
    package_root: Path, macro_review: dict[str, Any]
) -> dict[str, Any]:
    _, header, rows = read_macro(package_root / FORMAL_MACRO)
    date_index = header.index("Date")
    value_index = header.index("Hon_Hai_Rev_YoY")
    invalid_rows = {
        row[date_index]: row
        for row in rows
        if not is_numeric_or_blank(row[value_index])
    }
    details = []
    for item in macro_review["invalid_values"]:
        row = invalid_rows[item["date"]]
        details.append(
            {
                "date": item["date"],
                "original_hon_hai_rev_yoy": row[value_index],
                "original_source": "NOT_PRESENT_IN_MACRO_SNAPSHOT_SCHEMA",
                "candidate_value": "",
                "gap_reason": (
                    "The formal row contains text instead of a traceable numeric YoY "
                    "value and has no source locator; blank is required until Owner "
                    "approves a verifiable source."
                ),
            }
        )
    dates = [row[date_index] for row in rows]
    return {
        **macro_review,
        "formal_committed_authority_sha256": committed_sha(
            package_root, FORMAL_MACRO
        ),
        "formal_cutoff": max(dates),
        "expected_after_sha256": macro_review["candidate_sha256"],
        "expected_after_rows": len(rows),
        "expected_after_cutoff": max(dates),
        "row_preview": details,
        "approval_phrase": MACRO_REVIEW_PHRASE,
    }


def render_markdown(payload: dict[str, Any]) -> str:
    daily = payload["daily_price"]
    market = payload["market_activity"]
    macro = payload["macro"]
    lines = [
        "# P1008 Phase A Final Owner Review Package",
        "",
        f"- Status: `{payload['status']}`",
        "- Formal publish executed: `false`",
        "- OpenAI / Web Search / Canva calls: `0 / 0 / 0`",
        "",
        "## Daily Price remediation preview",
        "",
        f"- Invalid row: `{json.dumps(daily['removal']['invalid_row'], ensure_ascii=False)}`",
        f"- Before: `{daily['removal']['before_sha256']}` / {daily['removal']['before_rows']} rows / cutoff {daily['before_cutoff']}",
        f"- Removal expected: `{daily['removal']['candidate_sha256']}` / {daily['removal']['candidate_rows']} rows / cutoff {daily['removal']['candidate_cutoff']}",
        f"- Approval: `{daily['removal']['approval_phrase']}`",
        "",
        "## 2026-07-22 / 2026-07-24 Daily Price candidate",
        "",
    ]
    for row in daily["gap_candidate"]["rows"]:
        lines.append(
            f"- {row['date']}: Close={row['twse_close']}, PB={row['derived_pb_daily']}, "
            f"source={row['twse_url']}"
        )
    lines.extend(
        [
            "",
            "## Complete Market Activity candidate",
            "",
        ]
    )
    for row in market["candidate_rows"]:
        lines.append(
            f"- {row['date']}: volume={row['volume']}, value={row['value']}, "
            f"transactions={row['transactions']}, TWSE/formal close="
            f"{row['twse_close']}/{row['formal_price_close']}"
        )
    lines.extend(["", "## Macro five-row preview", ""])
    for row in macro["row_preview"]:
        lines.append(
            f"- {row['date']}: original=`{row['original_hon_hai_rev_yoy']}`; "
            "candidate=`blank`; source=`NOT_PRESENT_IN_MACRO_SNAPSHOT_SCHEMA`"
        )
    lines.extend(
        [
            "",
            "## Approval phrases",
            "",
            *[
                f"- `{value}`"
                for value in payload["owner_approval_phrases"].values()
            ],
            "",
        ]
    )
    return "\n".join(lines)


def build_package(
    package_root: Path,
    receipt_dir: Path,
    output_dir: Path,
) -> dict[str, Any]:
    package_root = package_root.resolve()
    receipt_dir = receipt_dir.resolve()
    output_dir = output_dir.resolve()
    runtime_root = (package_root / "runtime").resolve()
    if not output_dir.is_relative_to(runtime_root):
        raise ValueError("Owner review package must remain under runtime/")
    if output_dir.exists():
        raise FileExistsError(output_dir)
    output_dir.mkdir(parents=True)

    before_hashes = formal_hashes(package_root)
    raw, receipt = load_offline_month(receipt_dir, "2026-07")
    if sha256_bytes(raw) != EXPECTED_RAW_SHA256:
        raise ValueError("Approved TWSE raw receipt SHA mismatch")
    if receipt["request_url"] != source_url("2026-07"):
        raise ValueError("TWSE receipt URL is not the approved official channel")
    twse_rows = parse_twse_month(raw, "2026-07")

    removal = build_invalid_daily_price_removal_preview(
        package_root, output_dir / "daily_price_removal"
    )
    daily_gap = build_daily_gap_candidate(
        package_root, twse_rows, output_dir
    )
    expected_daily = build_expected_daily_after(
        Path(removal["candidate_path"]), Path(daily_gap["candidate_path"])
    )
    _, current_daily = read_csv(package_root / FORMAL_DAILY)
    daily_dates = [row["Date"] for row in current_daily]
    market = build_market_candidate(
        package_root, twse_rows, expected_daily, output_dir
    )
    macro_review = build_macro_candidate(
        package_root, output_dir / "macro_remediation"
    )
    macro = enrich_macro_review(package_root, macro_review)
    after_hashes = formal_hashes(package_root)
    if after_hashes != before_hashes:
        raise ValueError("Owner review generation changed formal authority bytes")

    payload = {
        "package_id": "P1008-PHASE-A-FINAL-OWNER-REVIEW-20260729",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "OWNER_REVIEW_REQUIRED",
        "twse_verification": {
            **receipt,
            "approved_raw_sha256": EXPECTED_RAW_SHA256,
            "http_calls_this_review": 0,
            "dates_verified": list(TARGET_GAP_DATES),
        },
        "daily_price": {
            "before_cutoff": max(daily_dates),
            "removal": removal,
            "gap_candidate": daily_gap,
            "expected_after_removal_and_gap_append": {
                key: value
                for key, value in expected_daily.items()
                if key != "price_by_date"
            },
        },
        "market_activity": market,
        "macro": macro,
        "owner_approval_phrases": {
            "daily_price_invalid_date_removal": INVALID_DAILY_PRICE_APPROVAL_PHRASE,
            "daily_price_gap_candidate": DAILY_GAP_REVIEW_PHRASE,
            "market_activity_complete_candidate": market["approval_phrase"],
            "macro_five_row_remediation": MACRO_REVIEW_PHRASE,
        },
        "formal_hashes_before": before_hashes,
        "formal_hashes_after": after_hashes,
        "formal_hashes_unchanged": True,
        "formal_publish_executed": False,
        "promotion_eligible": False,
        "openai_api_calls": 0,
        "web_search_calls": 0,
        "canva_calls": 0,
        "actionable": False,
    }
    report_path = output_dir / "FINAL_OWNER_REVIEW_PACKAGE.json"
    markdown_path = output_dir / "FINAL_OWNER_REVIEW_PACKAGE.md"
    atomic_json(report_path, payload)
    atomic_write(markdown_path, (render_markdown(payload) + "\n").encode("utf-8"))
    payload["package_json_path"] = str(report_path)
    payload["package_json_sha256"] = sha256_file(report_path)
    payload["package_markdown_path"] = str(markdown_path)
    payload["package_markdown_sha256"] = sha256_file(markdown_path)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-root", type=Path, required=True)
    parser.add_argument("--receipt-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--stage1-market-only",
        action="store_true",
        help="Rebuild only the post-Daily-Price Stage 1 Market Activity review candidate.",
    )
    args = parser.parse_args()
    builder = (
        build_stage1_market_activity_candidate
        if args.stage1_market_only
        else build_package
    )
    print(
        json.dumps(
            builder(args.package_root, args.receipt_dir, args.output_dir),
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
