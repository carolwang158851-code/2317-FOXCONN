from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
from pathlib import Path
from typing import Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MASTER_CSV = PROJECT_ROOT / "data" / "2317_master_v9.csv"
AUTHORITY_MANIFEST = PROJECT_ROOT / "data" / "CSV_AUTHORITY_MANIFEST.json"
DAILY_CSV = PROJECT_ROOT / "data" / "2317_daily_price.csv"
MACRO_CSV = PROJECT_ROOT / "data" / "macro_snapshot.csv"
DEFAULT_RUNTIME_DB = (
    Path(os.environ.get("LOCALAPPDATA", PROJECT_ROOT / "staging"))
    / "P1008"
    / "data"
    / "warroom.sqlite3"
)
BEFORE_VERSION = "## version: v9.3-candidate"
AFTER_VERSION = "## version: v9.3"


class NormalizationError(RuntimeError):
    pass


def canonical_json(data: object) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def data_region(content: bytes) -> bytes:
    lines = content.splitlines(keepends=True)
    for index, line in enumerate(lines):
        if line.strip() and not line.startswith(b"##"):
            return b"".join(lines[index:])
    raise NormalizationError("master CSV 缺少資料表頭")


def normalize_master(content: bytes) -> bytes:
    marker_lf = (BEFORE_VERSION + "\n").encode("utf-8")
    marker_crlf = (BEFORE_VERSION + "\r\n").encode("utf-8")
    count = content.count(marker_lf) + content.count(marker_crlf)
    if count != 1:
        raise NormalizationError(
            f"正式master必須恰好一個{BEFORE_VERSION}註解，目前為{count}"
        )
    if marker_crlf in content:
        candidate = content.replace(
            marker_crlf, (AFTER_VERSION + "\r\n").encode("utf-8"), 1
        )
    else:
        candidate = content.replace(
            marker_lf, (AFTER_VERSION + "\n").encode("utf-8"), 1
        )
    if data_region(candidate) != data_region(content):
        raise NormalizationError("版本正規化不得改變CSV資料區")
    return candidate


def parse_shape(content: bytes) -> tuple[int, int]:
    text = content.decode("utf-8-sig")
    data_lines = [
        line for line in text.splitlines() if line.strip() and not line.startswith("##")
    ]
    reader = csv.reader(io.StringIO("\n".join(data_lines)))
    rows = list(reader)
    if not rows:
        raise NormalizationError("master CSV 缺少資料")
    return len(rows) - 1, len(rows[0])


def build_authority_candidate(master_content: bytes) -> bytes:
    authority = json.loads(AUTHORITY_MANIFEST.read_text(encoding="utf-8-sig"))
    target = next(
        (
            item
            for item in authority.get("authoritativeFiles", [])
            if item.get("path") == "data/2317_master_v9.csv"
        ),
        None,
    )
    if target is None:
        raise NormalizationError("Authority Manifest 缺少 master 登錄")
    target["sha256"] = sha256_bytes(master_content)
    target["fileSizeBytes"] = len(master_content)
    return (json.dumps(authority, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def protected_hashes(runtime_db: Path) -> dict[str, str]:
    paths = [MASTER_CSV, AUTHORITY_MANIFEST, DAILY_CSV, MACRO_CSV, runtime_db]
    return {str(path.resolve()): sha256_file(path) for path in paths}


def build_candidate(output_dir: Path, runtime_db: Path) -> dict:
    output_dir.mkdir(parents=True, exist_ok=False)
    before = protected_hashes(runtime_db)
    master_before = MASTER_CSV.read_bytes()
    master_candidate = normalize_master(master_before)
    authority_candidate = build_authority_candidate(master_candidate)
    rows, columns = parse_shape(master_candidate)
    if (rows, columns) != (21, 54):
        raise NormalizationError("候選master必須為21列54欄")

    candidate_dir = output_dir / "candidate"
    data_dir = candidate_dir / "data"
    data_dir.mkdir(parents=True)
    files = {
        "data/2317_master_v9.csv": master_candidate,
        "data/CSV_AUTHORITY_MANIFEST.json": authority_candidate,
        "data/2317_daily_price.csv": DAILY_CSV.read_bytes(),
        "data/macro_snapshot.csv": MACRO_CSV.read_bytes(),
    }
    for relative_path, content in files.items():
        path = candidate_dir / relative_path.removeprefix("data/")
        if relative_path.startswith("data/"):
            path = data_dir / Path(relative_path).name
        path.write_bytes(content)

    items = []
    formal_paths = {
        "data/2317_master_v9.csv": MASTER_CSV,
        "data/CSV_AUTHORITY_MANIFEST.json": AUTHORITY_MANIFEST,
        "data/2317_daily_price.csv": DAILY_CSV,
        "data/macro_snapshot.csv": MACRO_CSV,
    }
    for relative_path in (
        "data/2317_master_v9.csv",
        "data/2317_daily_price.csv",
        "data/macro_snapshot.csv",
        "data/CSV_AUTHORITY_MANIFEST.json",
    ):
        candidate_content = files[relative_path]
        changed = relative_path in {
            "data/2317_master_v9.csv",
            "data/CSV_AUTHORITY_MANIFEST.json",
        }
        items.append(
            {
                "path": relative_path,
                "candidate_path": f"candidate/{relative_path}",
                "before_sha256": sha256_file(formal_paths[relative_path]),
                "candidate_sha256": sha256_bytes(candidate_content),
                "changed": changed,
            }
        )

    payload = {
        "release_type": "METADATA_NORMALIZATION",
        "batch_id": "P2-03B-07-METADATA-NORMALIZATION",
        "as_of": "2026-06-23",
        "subject": "LISTING:TWSE:2317",
        "change_scope": "CSV_VERSION_COMMENT_ONLY",
        "owner_candidate_approval_item": 87,
        "items": items,
        "change": {
            "before": BEFORE_VERSION,
            "after": AFTER_VERSION,
        },
        "data_region_sha256_before": sha256_bytes(data_region(master_before)),
        "data_region_sha256_after": sha256_bytes(data_region(master_candidate)),
        "data_region_equal": data_region(master_before) == data_region(master_candidate),
        "row_count": rows,
        "column_count": columns,
        "excluded_changes": [
            "CSV header",
            "21 data rows",
            "field overrides",
            "warnings",
            "daily price CSV",
            "macro CSV",
            "Runtime SQLite",
            "UI",
            "rules",
        ],
        "validation_status": "PASS",
        "actionable": False,
    }
    manifest_sha = sha256_bytes(canonical_json(payload).encode("utf-8"))
    release_id = f"REL-P1008-META93-20260623-{manifest_sha[:8]}"
    manifest = {
        "release_id": release_id,
        "manifest_sha256": manifest_sha,
        "manifest_hash_scope": "CANONICAL_PAYLOAD",
        "generated_at": "2026-06-23",
        "owner_approval": {
            "status": "PENDING",
            "approval_item": 88,
            "approved_manifest_sha256": None,
        },
        "publication": {
            "status": "NOT_PUBLISHED",
            "publisher": None,
            "post_publish_verified": False,
        },
        "payload": payload,
    }
    (candidate_dir / "RELEASE_MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    report = {
        "release_id": release_id,
        "manifest_sha256": manifest_sha,
        "status": "PASS",
        "status_zh": "候選驗證通過",
        "status_note_zh": "只正規化版本註解；資料表頭與21列資料逐位元不變，尚未發布",
        "actionable": False,
        "data_region_equal": payload["data_region_equal"],
        "data_region_sha256": payload["data_region_sha256_after"],
        "row_count": rows,
        "column_count": columns,
        "candidate_master_sha256": sha256_bytes(master_candidate),
        "candidate_authority_manifest_sha256": sha256_bytes(authority_candidate),
        "published": False,
    }
    (output_dir / "DRY_RUN.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    after = protected_hashes(runtime_db)
    if before != after:
        raise NormalizationError("候選建立期間正式檔案或Runtime SQLite發生變更")
    report["protected_files"] = {
        "before": before,
        "after": after,
        "unchanged": True,
    }
    (output_dir / "DRY_RUN.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return report


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="P2-03B-07 v9.3版本註解正規化候選")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--runtime-db", type=Path, default=DEFAULT_RUNTIME_DB)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = make_parser().parse_args(argv)
    try:
        result = build_candidate(args.output_dir, args.runtime_db)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(
            json.dumps(
                {
                    "status": "FAIL",
                    "status_zh": "候選建立失敗",
                    "status_note_zh": str(exc),
                    "error_type": type(exc).__name__,
                    "actionable": False,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
