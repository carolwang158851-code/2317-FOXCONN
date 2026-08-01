from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[2]
EXPECTED_RELEASE_ID = "REL-P1008-FH-20260622-70087679"
EXPECTED_MANIFEST_SHA = (
    "700876796348FE4D79F97A559B144C8032148129481A7297B4831082DF71C745"
)
PUBLISHER = "P1008_LOCAL_PUBLISHER"
ALLOWED_CHANGED_PATHS = {
    "data/2317_master_v9.csv",
    "data/CSV_AUTHORITY_MANIFEST.json",
}
PROTECTED_UNCHANGED_PATHS = {
    "data/2317_daily_price.csv",
    "data/macro_snapshot.csv",
}


class PublishError(RuntimeError):
    pass


class ApprovalError(PublishError):
    pass


class ValidationError(PublishError):
    pass


def canonical_json(data: object) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def ensure_within(path: Path, root: Path) -> Path:
    resolved = path.resolve()
    resolved_root = root.resolve()
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise ValidationError(f"路徑超出允許範圍：{resolved}") from exc
    return resolved


def candidate_path(candidate_dir: Path, relative_path: str) -> Path:
    run_root = candidate_dir.resolve().parent
    path = ensure_within(run_root / relative_path, run_root)
    if not path.is_file():
        raise ValidationError(f"候選檔案不存在：{path}")
    return path


def read_master(path: Path) -> tuple[list[str], list[str], list[dict[str, str]]]:
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    comments = [line for line in lines if line.startswith("##")]
    data_lines = [line for line in lines if line.strip() and not line.startswith("##")]
    reader = csv.DictReader(data_lines)
    if reader.fieldnames is None:
        raise ValidationError("master CSV 缺少表頭")
    rows = list(reader)
    return comments, reader.fieldnames, rows


def verify_candidate(
    candidate_dir: Path,
    project_root: Path,
    approved_release_id: str,
    approved_manifest_sha: str,
) -> tuple[dict, dict[str, Path]]:
    if approved_release_id != EXPECTED_RELEASE_ID:
        raise ApprovalError("Release ID 與第86項核准內容不一致")
    if approved_manifest_sha != EXPECTED_MANIFEST_SHA:
        raise ApprovalError("Manifest SHA-256 與第86項核准內容不一致")
    manifest_path = candidate_dir / "RELEASE_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("release_id") != approved_release_id:
        raise ApprovalError("候選 Release ID 與核准內容不一致")
    if manifest.get("manifest_sha256") != approved_manifest_sha:
        raise ApprovalError("候選 Manifest SHA-256 與核准內容不一致")
    recomputed = sha256_bytes(canonical_json(manifest["payload"]).encode("utf-8"))
    if recomputed != approved_manifest_sha:
        raise ApprovalError("Manifest canonical payload 雜湊不一致")

    items = manifest["payload"].get("items", [])
    item_paths = {item["path"] for item in items}
    expected_paths = ALLOWED_CHANGED_PATHS | PROTECTED_UNCHANGED_PATHS
    if item_paths != expected_paths:
        raise ValidationError("Manifest 檔案集合超出第86項核准範圍")
    resolved = {}
    for item in items:
        path = candidate_path(candidate_dir, item["candidate_path"])
        if sha256_file(path) != item["candidate_sha256"]:
            raise ApprovalError(f"候選檔案雜湊不一致：{item['path']}")
        formal = ensure_within(project_root / item["path"], project_root)
        if sha256_file(formal) != item["before_sha256"]:
            raise ApprovalError(f"正式檔案已偏離核准前基準：{item['path']}")
        if item["path"] in ALLOWED_CHANGED_PATHS and not item["changed"]:
            raise ValidationError(f"核准變更檔案未標示 changed：{item['path']}")
        if item["path"] in PROTECTED_UNCHANGED_PATHS and item["changed"]:
            raise ValidationError(f"唯讀檔案被標示為變更：{item['path']}")
        resolved[item["path"]] = path

    comments, columns, rows = read_master(resolved["data/2317_master_v9.csv"])
    if len(rows) != 21 or len(columns) != 54:
        raise ValidationError("候選 master 必須為21列54欄")
    if not any(line == "## version: v9.3-candidate" for line in comments):
        raise ValidationError("候選 master 版本註解不符合已核准內容")
    latest = next((row for row in rows if row["Quarter"] == "2026Q1"), None)
    if latest is None:
        raise ValidationError("候選 master 缺少2026Q1")
    if (
        latest["ForeignHoldRatio_Pct"],
        latest["ForeignHoldChange_Pct"],
        latest["ForeignHoldTrend"],
    ) != ("36.28", "-2.04", "DECLINING"):
        raise ValidationError("2026Q1外資候選值不符合第85項技術驗證")

    authority = json.loads(
        resolved["data/CSV_AUTHORITY_MANIFEST.json"].read_text(encoding="utf-8")
    )
    master_entry = next(
        (
            item
            for item in authority.get("authoritativeFiles", [])
            if item.get("path") == "data/2317_master_v9.csv"
        ),
        None,
    )
    if master_entry is None:
        raise ValidationError("候選 Authority Manifest 缺少 master 登錄")
    if master_entry.get("sha256") != sha256_file(
        resolved["data/2317_master_v9.csv"]
    ):
        raise ValidationError("Authority Manifest 與候選 master 雜湊不一致")
    if master_entry.get("fileVersion") != "v9.3":
        raise ValidationError("Authority Manifest 版本不是v9.3")
    overrides = master_entry.get("fieldOverrides", {})
    if (
        overrides.get("ForeignHoldRatio_Pct", {}).get("quality")
        != "OFFICIAL_TWSE_A1_L1"
    ):
        raise ValidationError("外資持股欄位未標示官方A1/L1")
    return manifest, resolved


def atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="wb", dir=path.parent, prefix=f".{path.name}.", delete=False
    ) as handle:
        temp_path = Path(handle.name)
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def restore_from_backup(project_root: Path, backup_dir: Path) -> None:
    for relative_path in ALLOWED_CHANGED_PATHS:
        source = backup_dir / relative_path
        target = project_root / relative_path
        if source.is_file():
            atomic_write(target, source.read_bytes())


def verify_published(
    project_root: Path,
    manifest: dict,
    protected_before: dict[str, str],
) -> dict:
    item_map = {item["path"]: item for item in manifest["payload"]["items"]}
    for relative_path in ALLOWED_CHANGED_PATHS:
        actual = sha256_file(project_root / relative_path)
        expected = item_map[relative_path]["candidate_sha256"]
        if actual != expected:
            raise ValidationError(f"發布後雜湊不一致：{relative_path}")
    for relative_path in PROTECTED_UNCHANGED_PATHS:
        if sha256_file(project_root / relative_path) != protected_before[relative_path]:
            raise ValidationError(f"未核准檔案在發布期間變更：{relative_path}")

    comments, columns, rows = read_master(project_root / "data/2317_master_v9.csv")
    authority = json.loads(
        (project_root / "data/CSV_AUTHORITY_MANIFEST.json").read_text(
            encoding="utf-8"
        )
    )
    master_entry = next(
        item
        for item in authority["authoritativeFiles"]
        if item["path"] == "data/2317_master_v9.csv"
    )
    master_hash = sha256_file(project_root / "data/2317_master_v9.csv")
    latest = next(row for row in rows if row["Quarter"] == "2026Q1")
    return {
        "row_count": len(rows),
        "column_count": len(columns),
        "version_comment": next(
            (line for line in comments if line.startswith("## version:")), None
        ),
        "version_warning": "CSV_INTERNAL_VERSION_LABEL_CANDIDATE",
        "master_sha256": master_hash,
        "authority_manifest_sha256": sha256_file(
            project_root / "data/CSV_AUTHORITY_MANIFEST.json"
        ),
        "authority_master_hash_matches": master_entry["sha256"] == master_hash,
        "authority_file_version": master_entry["fileVersion"],
        "candidate_2026Q1": {
            "ForeignHoldRatio_Pct": latest["ForeignHoldRatio_Pct"],
            "ForeignHoldChange_Pct": latest["ForeignHoldChange_Pct"],
            "ForeignHoldTrend": latest["ForeignHoldTrend"],
        },
    }


def publish_release(
    candidate_dir: Path,
    project_root: Path,
    output_dir: Path,
    *,
    approved_release_id: str,
    approved_manifest_sha: str,
    approval_item: int,
    runtime_db: Path | None = None,
) -> dict:
    if approval_item != 86:
        raise ApprovalError("本Publisher只接受Owner第86項核准")
    candidate_dir = candidate_dir.resolve()
    project_root = project_root.resolve()
    output_dir = output_dir.resolve()
    if output_dir.exists():
        raise PublishError(f"發布輸出目錄已存在：{output_dir}")
    manifest, candidates = verify_candidate(
        candidate_dir,
        project_root,
        approved_release_id,
        approved_manifest_sha,
    )
    output_dir.mkdir(parents=True)
    backup_dir = output_dir / "backup"
    protected_before = {
        path: sha256_file(project_root / path)
        for path in ALLOWED_CHANGED_PATHS | PROTECTED_UNCHANGED_PATHS
    }
    runtime_before = sha256_file(runtime_db) if runtime_db and runtime_db.is_file() else None
    for relative_path in ALLOWED_CHANGED_PATHS:
        backup_path = backup_dir / relative_path
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(project_root / relative_path, backup_path)

    try:
        for relative_path in (
            "data/2317_master_v9.csv",
            "data/CSV_AUTHORITY_MANIFEST.json",
        ):
            atomic_write(project_root / relative_path, candidates[relative_path].read_bytes())
        validation = verify_published(project_root, manifest, protected_before)
        runtime_after = (
            sha256_file(runtime_db) if runtime_db and runtime_db.is_file() else None
        )
        if runtime_before != runtime_after:
            raise ValidationError("Runtime SQLite 在發布期間發生變更")
    except Exception:
        restore_from_backup(project_root, backup_dir)
        raise

    published_manifest = json.loads(json.dumps(manifest, ensure_ascii=False))
    published_manifest["owner_approval"] = {
        "status": "APPROVED",
        "approved_by": "Owner",
        "approved_at": "2026-06-23",
        "approval_item": 86,
        "approved_manifest_sha256": approved_manifest_sha,
    }
    published_manifest["publication"] = {
        "status": "PUBLISHED_WITH_METADATA_WARNING",
        "status_zh": "已發布但有中繼資料警告",
        "status_note_zh": "正式數據與權威雜湊已發布；CSV內部版本註解仍為v9.3-candidate",
        "published_at": "2026-06-23",
        "publisher": PUBLISHER,
        "post_publish_verified": True,
        "published_master_sha256": validation["master_sha256"],
        "published_authority_manifest_sha256": validation[
            "authority_manifest_sha256"
        ],
    }
    manifest_output = output_dir / "RELEASE_MANIFEST.json"
    manifest_output.write_text(
        json.dumps(published_manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    result = {
        "release_id": approved_release_id,
        "manifest_sha256": approved_manifest_sha,
        "status": "PUBLISHED_WITH_METADATA_WARNING",
        "status_zh": "已發布但有中繼資料警告",
        "status_note_zh": "官方外資持股序列已發布；內部版本註解待另案正規化",
        "actionable": False,
        "approval_item": 86,
        "publisher": PUBLISHER,
        "backup_dir": str(backup_dir),
        "validation": validation,
        "protected_unchanged": {
            path: sha256_file(project_root / path)
            for path in PROTECTED_UNCHANGED_PATHS
        },
        "runtime_sqlite_sha256": runtime_after,
        "rollback_available": True,
    }
    (output_dir / "POST_PUBLISH_RESULT.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return result


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="P2-03B-07 Owner核准發布器")
    parser.add_argument("--candidate-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--approval-item", type=int, required=True)
    parser.add_argument(
        "--runtime-db",
        type=Path,
        default=Path(os.environ.get("LOCALAPPDATA", PROJECT_ROOT / "staging"))
        / "P1008"
        / "data"
        / "warroom.sqlite3",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = make_parser().parse_args(argv)
    try:
        result = publish_release(
            args.candidate_dir,
            PROJECT_ROOT,
            args.output_dir,
            approved_release_id=args.release_id,
            approved_manifest_sha=args.manifest_sha256,
            approval_item=args.approval_item,
            runtime_db=args.runtime_db,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(
            json.dumps(
                {
                    "status": "FAIL",
                    "status_zh": "發布失敗",
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
