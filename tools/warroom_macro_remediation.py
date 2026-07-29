"""Build a review-only candidate for invalid Hon_Hai_Rev_YoY values."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


FORMAL_REL = Path("data/macro_snapshot.csv")
EXPECTED_INVALID_DATES = {
    "2021-03-31",
    "2026-06-03",
    "2026-06-04",
    "2026-06-05",
    "2026-06-12",
}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def is_numeric_or_blank(value: str) -> bool:
    normalized = str(value).strip()
    if not normalized:
        return True
    if normalized.endswith("%"):
        normalized = normalized[:-1].strip()
    try:
        parsed = Decimal(normalized)
    except InvalidOperation:
        return False
    return parsed.is_finite()


def read_macro(path: Path) -> tuple[list[str], list[str], list[list[str]]]:
    comments: list[str] = []
    csv_lines: list[str] = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if not csv_lines and line.startswith("#"):
            comments.append(line)
        elif line.strip():
            csv_lines.append(line)
    parsed = list(csv.reader(csv_lines))
    if not parsed:
        raise ValueError("macro_snapshot.csv has no CSV header")
    return comments, parsed[0], parsed[1:]


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def build_candidate(package_root: Path, output_dir: Path) -> dict[str, Any]:
    package_root = package_root.resolve()
    output_dir = output_dir.resolve()
    runtime_root = (package_root / "runtime").resolve()
    if not output_dir.is_relative_to(runtime_root):
        raise ValueError("Macro remediation candidate must remain under runtime/")
    if output_dir.exists():
        raise FileExistsError(output_dir)

    formal_path = package_root / FORMAL_REL
    before_sha = sha256_file(formal_path)
    comments, header, rows = read_macro(formal_path)
    if "Date" not in header or "Hon_Hai_Rev_YoY" not in header:
        raise ValueError("macro_snapshot.csv lacks Date or Hon_Hai_Rev_YoY")
    date_index = header.index("Date")
    value_index = header.index("Hon_Hai_Rev_YoY")

    invalid: list[dict[str, str]] = []
    candidate_rows: list[list[str]] = []
    for row in rows:
        if len(row) != len(header):
            raise ValueError(
                f"macro_snapshot.csv row width mismatch for {row[date_index] if row else 'UNKNOWN'}"
            )
        candidate = list(row)
        value = candidate[value_index]
        if not is_numeric_or_blank(value):
            invalid.append(
                {
                    "date": candidate[date_index],
                    "original_value": value,
                    "source": "SOURCE_NOT_PROVIDED_IN_FORMAL_ROW",
                    "resolution": "BLANK_PENDING_OWNER_APPROVED_TRACEABLE_SOURCE",
                }
            )
            candidate[value_index] = ""
        candidate_rows.append(candidate)

    invalid_dates = {item["date"] for item in invalid}
    if invalid_dates != EXPECTED_INVALID_DATES:
        raise ValueError(
            "Unexpected Hon_Hai_Rev_YoY invalid-date set: "
            + ", ".join(sorted(invalid_dates))
        )

    text = io.StringIO(newline="")
    for comment in comments:
        text.write(comment + "\n")
    writer = csv.writer(text, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(candidate_rows)

    output_dir.mkdir(parents=True)
    candidate_path = output_dir / "macro_snapshot_hon_hai_rev_yoy.candidate.csv"
    candidate_path.write_text(text.getvalue(), encoding="utf-8", newline="")
    if any(
        not is_numeric_or_blank(row[value_index])
        for row in candidate_rows
    ):
        raise ValueError("Macro remediation candidate still contains nonnumeric values")
    if sha256_file(formal_path) != before_sha:
        raise ValueError("Macro remediation preview changed formal macro_snapshot.csv")

    review = {
        "status": "OWNER_REVIEW_REQUIRED",
        "target": str(FORMAL_REL).replace("\\", "/"),
        "formal_sha256": before_sha,
        "formal_rows": len(rows),
        "candidate_path": str(candidate_path),
        "candidate_sha256": sha256_file(candidate_path),
        "candidate_rows": len(candidate_rows),
        "invalid_values": invalid,
        "trusted_numeric_replacement_available": False,
        "formal_csv_modified": False,
        "promotion_eligible": False,
        "actionable": False,
    }
    atomic_json(output_dir / "MACRO_REMEDIATION_PREVIEW.json", review)
    return review


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            build_candidate(args.package_root, args.output_dir),
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
