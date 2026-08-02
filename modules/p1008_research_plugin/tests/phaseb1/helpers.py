from __future__ import annotations

import json
import shutil
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
from uuid import uuid4


MODULE_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = MODULE_ROOT.parents[1]
SRC_ROOT = MODULE_ROOT / "src"
FIXTURE_PATH = MODULE_ROOT / "tests" / "fixtures" / "phaseb1" / "monthly_revenue_fixture.json"
sys.path.insert(0, str(SRC_ROOT))


@contextmanager
def scratch(prefix: str) -> Iterator[Path]:
    root = PACKAGE_ROOT / "runtime" / "phaseb1_test_scratch"
    root.mkdir(parents=True, exist_ok=True)
    # Do not use tempfile.TemporaryDirectory here. The verified bundled Python
    # can create normal runtime folders on Windows/OneDrive, while inherited
    # TemporaryDirectory ACLs are known to raise PermissionError in this host.
    path = root / f"{prefix}{uuid4().hex}"
    path.mkdir(parents=False, exist_ok=False)
    yield path


def fixture() -> dict[str, object]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def write_fixture(root: Path, payload: dict[str, object]) -> Path:
    path = root / "fixture.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8", newline="\n")
    return path


def authority_sandbox(root: Path) -> Path:
    package = root / "package"
    shutil.copytree(PACKAGE_ROOT / "data", package / "data")
    shutil.copytree(
        PACKAGE_ROOT / "contracts" / "p1008_research_plugin" / "v1.0",
        package / "contracts" / "p1008_research_plugin" / "v1.0",
    )
    (package / "rules").mkdir(parents=True)
    shutil.copy2(
        PACKAGE_ROOT / "rules" / "RULE_STATUS_MANIFEST.json",
        package / "rules" / "RULE_STATUS_MANIFEST.json",
    )
    return package
