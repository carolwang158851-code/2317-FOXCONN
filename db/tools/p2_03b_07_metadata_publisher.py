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
EXPECTED_RELEASE_ID = "REL-P1008-META93-20260623-D61B1A84"
EXPECTED_MANIFEST_SHA = (
    "D61B1A848F5FA6B14B59DFB4FFEDCAF83A5C2F656FE95308D1902C6881BF8F71"
)
EXPECTED_DATA_REGION_SHA = (
    "12224CD3B9588DD1B7A10BD599181D070F0CA2E979B71AD3D95CB56890353689"
)
PUBLISHER = "P1008_LOCAL_PUBLISHER"
CHANGED_PATHS = {
    "data/2317_master_v9.csv",
    "data/CSV_AUTHORITY_MANIFEST.json",
}
UNCHANGED_PATHS = {
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


def data_region(content: bytes) -> bytes:
    lines = content.splitlines(keepends=True)
    for index, line in enumerate(lines):
        if line.strip() and not line.startswith(b"##"):
            return b"".join(lines[index:])
    raise ValidationError("master CSV 缺少資料表頭")


def read_master_bytes(content: bytes) -> tuple[list[str], list[str], list[dict[str, str]]]:
    lines = content.decode("utf-8-sig").splitlines()
    comments = [line for line in lines if line.startswith("##")]
    data_lines = [line for line in lines if line.strip() and not line.startswith("##")]
    reader = csv.DictReader(data_lines)
    if reader.fieldnames is None:
        raise ValidationError("master CSV 缺少表頭")
    return comments, reader.fieldnames, list(reader)


def json_differences(before: object, after: object, path: str = "") -> list[str]:
    if type(before) is not type(after):
        return [path]
    if isinstance(before, dict):
        result = []
        for key in sorted(set(before) | set(after)):
            child = f"{path}/{key}"
            if key not in before or key not in after:
                result.append(child)
            else:
                result.extend(json_differences(before[key], after[key], child))
        return result
    if isinstance(before, list):
        if len(before) != len(after):
            return [f"{path}/length"]
        result = []
        for index, (left, right) in enumerate(zip(before, after)):
            result.extend(json_differences(left, right, f"{path}/{index}"))
        return result
    return [] if before == after else [path]


def resolve_candidate(candidate_dir: Path, relative_path: str) -> Path:
    run_root = candidate_dir.resolve().parent
    path = ensure_within(run_root / relative_path, run_root)
    if not path.is_file():
        raise ValidationError(f"候選檔案不存在：{path}")
    return path


def verify_candidate(
    candidate_dir: Path,
    project_root: Path,
    release_id: str,
    manifest_sha: str,
) -> tuple[dict, dict[str, Path]]:
    if release_id != EXPECTED_RELEASE_ID or manifest_sha != EXPECTED_MANIFEST_SHA:
        raise ApprovalError("Release ID或Manifest SHA與第88項核准不一致")
    manifest = json.loads(
        (candidate_dir / "RELEASE_MANIFEST.json").read_text(encoding="utf-8")
    )
    if manifest.get("release_id") != release_id:
        raise ApprovalError("候選Release ID與核准不一致")
    if manifest.get("manifest_sha256") != manifest_sha:
        raise ApprovalError("候選Manifest SHA與核准不一致")
    recomputed = sha256_bytes(canonical_json(manifest["payload"]).encode("utf-8"))
    if recomputed != manifest_sha:
        raise ApprovalError("Manifest canonical payload雜湊不一致")
    payload = manifest["payload"]
    if (
        payload.get("change_scope") != "CSV_VERSION_COMMENT_ONLY"
        or payload.get("owner_candidate_approval_item") != 87
        or payload.get("data_region_equal") is not True
        or payload.get("data_region_sha256_before") != EXPECTED_DATA_REGION_SHA
        or payload.get("data_region_sha256_after") != EXPECTED_DATA_REGION_SHA
    ):
        raise ValidationError("Manifest版本正規化契約不符合第87/88項")

    items = payload["items"]
    if {item["path"] for item in items} != CHANGED_PATHS | UNCHANGED_PATHS:
        raise ValidationError("Manifest檔案集合超出核准範圍")
    resolved = {}
    for item in items:
        candidate = resolve_candidate(candidate_dir, item["candidate_path"])
        formal = ensure_within(project_root / item["path"], project_root)
        if sha256_file(candidate) != item["candidate_sha256"]:
            raise ApprovalError(f"候選檔案雜湊不一致：{item['path']}")
        if sha256_file(formal) != item["before_sha256"]:
            raise ApprovalError(f"正式檔案已偏離核准前基準：{item['path']}")
        if item["changed"] != (item["path"] in CHANGED_PATHS):
            raise ValidationError(f"changed標記不符合核准範圍：{item['path']}")
        resolved[item["path"]] = candidate

    formal_master = (project_root / "data/2317_master_v9.csv").read_bytes()
    candidate_master = resolved["data/2317_master_v9.csv"].read_bytes()
    formal_lines = formal_master.splitlines()
    candidate_lines = candidate_master.splitlines()
    line_diffs = [
        (left, right)
        for left, right in zip(formal_lines, candidate_lines)
        if left != right
    ]
    if line_diffs != [(b"## version: v9.3-candidate", b"## version: v9.3")]:
        raise ValidationError("master差異不是唯一核准版本註解")
    if data_region(formal_master) != data_region(candidate_master):
        raise ValidationError("master資料區發生未核准變更")
    if sha256_bytes(data_region(candidate_master)) != EXPECTED_DATA_REGION_SHA:
        raise ValidationError("master資料區SHA不符合核准Manifest")
    comments, columns, rows = read_master_bytes(candidate_master)
    if len(rows) != 21 or len(columns) != 54:
        raise ValidationError("候選master不是21列54欄")
    if "## version: v9.3" not in comments:
        raise ValidationError("候選master版本註解不是v9.3")

    formal_authority = json.loads(
        (project_root / "data/CSV_AUTHORITY_MANIFEST.json").read_text(
            encoding="utf-8"
        )
    )
    candidate_authority = json.loads(
        resolved["data/CSV_AUTHORITY_MANIFEST.json"].read_text(encoding="utf-8")
    )
    differences = json_differences(formal_authority, candidate_authority)
    allowed = {
        "/authoritativeFiles/0/fileSizeBytes",
        "/authoritativeFiles/0/sha256",
    }
    if set(differences) != allowed:
        raise ValidationError(f"Authority Manifest差異超出白名單：{differences}")
    entry = candidate_authority["authoritativeFiles"][0]
    if (
        entry["path"] != "data/2317_master_v9.csv"
        or entry["sha256"] != sha256_bytes(candidate_master)
        or entry["fileSizeBytes"] != len(candidate_master)
        or entry["fileVersion"] != "v9.3"
    ):
        raise ValidationError("候選Authority Manifest未正確指向master")
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


def restore(project_root: Path, backup_dir: Path) -> None:
    for relative_path in CHANGED_PATHS:
        source = backup_dir / relative_path
        if source.is_file():
            atomic_write(project_root / relative_path, source.read_bytes())


def publish(
    candidate_dir: Path,
    project_root: Path,
    output_dir: Path,
    *,
    release_id: str,
    manifest_sha: str,
    approval_item: int,
    runtime_db: Path,
) -> dict:
    if approval_item != 88:
        raise ApprovalError("本Publisher只接受Owner第88項核准")
    candidate_dir = candidate_dir.resolve()
    project_root = project_root.resolve()
    output_dir = output_dir.resolve()
    if output_dir.exists():
        raise PublishError(f"發布輸出目錄已存在：{output_dir}")
    manifest, candidates = verify_candidate(
        candidate_dir, project_root, release_id, manifest_sha
    )
    output_dir.mkdir(parents=True)
    backup_dir = output_dir / "backup"
    protected_before = {
        path: sha256_file(project_root / path) for path in CHANGED_PATHS | UNCHANGED_PATHS
    }
    runtime_before = sha256_file(runtime_db)
    for relative_path in CHANGED_PATHS:
        backup = backup_dir / relative_path
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(project_root / relative_path, backup)

    try:
        for relative_path in (
            "data/2317_master_v9.csv",
            "data/CSV_AUTHORITY_MANIFEST.json",
        ):
            atomic_write(project_root / relative_path, candidates[relative_path].read_bytes())
        for item in manifest["payload"]["items"]:
            actual = sha256_file(project_root / item["path"])
            expected = item["candidate_sha256"] if item["changed"] else item["before_sha256"]
            if actual != expected:
                raise ValidationError(f"發布後雜湊不一致：{item['path']}")
        if sha256_file(runtime_db) != runtime_before:
            raise ValidationError("Runtime SQLite在發布期間發生變更")
        master = (project_root / "data/2317_master_v9.csv").read_bytes()
        comments, columns, rows = read_master_bytes(master)
        if (
            "## version: v9.3" not in comments
            or len(rows) != 21
            or len(columns) != 54
            or sha256_bytes(data_region(master)) != EXPECTED_DATA_REGION_SHA
        ):
            raise ValidationError("發布後master驗證失敗")
    except Exception:
        restore(project_root, backup_dir)
        raise

    published = json.loads(json.dumps(manifest, ensure_ascii=False))
    published["owner_approval"] = {
        "status": "APPROVED",
        "approved_by": "Owner",
        "approved_at": "2026-06-23",
        "approval_item": 88,
        "approved_manifest_sha256": manifest_sha,
    }
    published["publication"] = {
        "status": "PUBLISHED",
        "status_zh": "已發布",
        "status_note_zh": "v9.3版本註解已正規化，資料區逐位元不變",
        "published_at": "2026-06-23",
        "publisher": PUBLISHER,
        "post_publish_verified": True,
        "published_master_sha256": sha256_file(
            project_root / "data/2317_master_v9.csv"
        ),
        "published_authority_manifest_sha256": sha256_file(
            project_root / "data/CSV_AUTHORITY_MANIFEST.json"
        ),
    }
    (output_dir / "RELEASE_MANIFEST.json").write_text(
        json.dumps(published, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    result = {
        "release_id": release_id,
        "manifest_sha256": manifest_sha,
        "status": "PUBLISHED",
        "status_zh": "已發布",
        "status_note_zh": "v9.3版本註解已正規化；資料表頭與21列資料未變",
        "actionable": False,
        "publisher": PUBLISHER,
        "approval_item": 88,
        "backup_dir": str(backup_dir),
        "rollback_available": True,
        "validation": {
            "version_comment": "## version: v9.3",
            "row_count": 21,
            "column_count": 54,
            "data_region_sha256": EXPECTED_DATA_REGION_SHA,
            "master_sha256": sha256_file(
                project_root / "data/2317_master_v9.csv"
            ),
            "authority_manifest_sha256": sha256_file(
                project_root / "data/CSV_AUTHORITY_MANIFEST.json"
            ),
        },
        "protected_unchanged": {
            path: sha256_file(project_root / path) for path in UNCHANGED_PATHS
        },
        "runtime_sqlite_sha256": sha256_file(runtime_db),
    }
    (output_dir / "POST_PUBLISH_RESULT.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return result


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="P2-03B-07 v9.3 metadata Publisher")
    parser.add_argument("--candidate-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--approval-item", type=int, required=True)
    parser.add_argument(
        "--runtime-db",
        type=Path,
        default=Path(os.environ["LOCALAPPDATA"])
        / "P1008"
        / "data"
        / "warroom.sqlite3",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = make_parser().parse_args(argv)
    try:
        result = publish(
            args.candidate_dir,
            PROJECT_ROOT,
            args.output_dir,
            release_id=args.release_id,
            manifest_sha=args.manifest_sha256,
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
