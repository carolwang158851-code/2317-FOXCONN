from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pydantic import BaseModel


MODULE_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = MODULE_ROOT.parents[1]
SRC_ROOT = MODULE_ROOT / "src" / "p1008_research_plugin"
FIXTURE_PATH = MODULE_ROOT / "tests" / "fixtures" / "phase3b" / "plugin_packets.json"
sys.path.insert(0, str(MODULE_ROOT / "src"))

from p1008_research_plugin.runtime.runtime_config import (
    RuntimeConfig,
    RuntimeConfigurationError,
)
from p1008_research_plugin.runtime.runtime_manager import RuntimeManager
from p1008_research_plugin.openai.model_registry import ModelRegistry
from p1008_research_plugin.openai.tool_registry import ToolRegistry
from p1008_research_plugin.plugin_module.contracts import FinancialBriefReport
from p1008_research_plugin.plugin_module.packet_gateway import (
    PacketGateway,
    PacketValidationError,
)
from p1008_research_plugin.plugin_module.router import PluginRouter


def fixture() -> dict[str, object]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


class Phase3BPluginBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = fixture()
        self.monthly = self.fixture["cases"]["monthly_revenue"]
        self.gateway = PacketGateway()

    def validate_mutated_packets(self, packets: list[dict[str, object]]) -> None:
        parsed = self.gateway.parse(packets)
        plan = PluginRouter().route(
            self.monthly["run_type"], self.gateway.aggregate_signals(parsed)
        )
        self.gateway.validate(plan, parsed, self.fixture["as_of_date"])

    def test_missing_source_evidence_id_stale_and_schema_drift_fail_closed(self) -> None:
        mutations = []

        missing_source = copy.deepcopy(self.monthly["packets"])
        missing_source[0]["evidence"][0]["source_locators"] = []
        mutations.append(missing_source)

        missing_evidence_id = copy.deepcopy(self.monthly["packets"])
        missing_evidence_id[0]["evidence"][0].pop("evidence_id")
        mutations.append(missing_evidence_id)

        stale = copy.deepcopy(self.monthly["packets"])
        stale[0]["expires_on"] = "2026-07-13"
        mutations.append(stale)

        schema_drift = copy.deepcopy(self.monthly["packets"])
        schema_drift[0]["unapproved_field"] = True
        mutations.append(schema_drift)

        for packets in mutations:
            with self.subTest(mutation=mutations.index(packets)):
                with self.assertRaises(PacketValidationError):
                    self.validate_mutated_packets(packets)

    def test_live_path_fails_before_sdk_loading_when_key_is_missing(self) -> None:
        env_name = "_".join(("OPENAI", "API", "KEY"))
        config = RuntimeConfig.phase3b_shadow(live=True)
        with mock.patch.dict(os.environ, {env_name: ""}, clear=False):
            with mock.patch(
                "p1008_research_plugin.plugin_module.agent_runner.importlib.import_module"
            ) as sdk_import:
                with self.assertRaises(RuntimeConfigurationError):
                    ModelRegistry().resolve_phase3b(config)
                sdk_import.assert_not_called()

    def test_phase3b_source_has_no_embedded_key_or_hardcoded_openai_model(self) -> None:
        env_name = "_".join(("OPENAI", "API", "KEY"))
        files = [
            SRC_ROOT / "runtime" / "runtime_config.py",
            SRC_ROOT / "openai" / "model_registry.py",
            SRC_ROOT / "plugin_module" / "agent_runner.py",
        ]
        combined = "\n".join(path.read_text(encoding="utf-8") for path in files)
        self.assertNotIn(env_name, combined)
        self.assertIsNone(re.search(r"\bgpt-[a-z0-9.-]+", combined, re.IGNORECASE))
        self.assertNotIn("sk-" + "proj-", combined)

    def test_agents_sdk_contract_is_typed_single_agent_and_hosted_web_search(self) -> None:
        self.assertTrue(issubclass(FinancialBriefReport, BaseModel))
        snapshot = ToolRegistry().phase3b_snapshot()
        self.assertEqual(
            snapshot["web_search"]["implementation"], "OPENAI_HOSTED_WEB_SEARCH"
        )
        self.assertEqual(
            type(ToolRegistry().build_hosted_web_search()).__name__, "WebSearchTool"
        )
        self.assertEqual(snapshot["canva"]["max_calls_per_run"], 0)
        capability = RuntimeManager(PACKAGE_ROOT).capabilities.shadow_snapshot()
        self.assertFalse(capability["multi_agent"])
        self.assertFalse(capability["handoffs"])

    def test_mock_shadow_preserves_formal_csv_sqlite_rules_hold_and_midr_state(self) -> None:
        watched = [
            PACKAGE_ROOT / "data" / "2317_master_v9.csv",
            PACKAGE_ROOT / "data" / "2317_daily_price.csv",
            PACKAGE_ROOT / "data" / "macro_snapshot.csv",
            *sorted(path for path in (PACKAGE_ROOT / "rules").rglob("*") if path.is_file()),
        ]
        local_app_data = os.getenv("LOCALAPPDATA", "")
        runtime_db = Path(local_app_data) / "P1008" / "data" / "warroom.sqlite3"
        if local_app_data and runtime_db.is_file():
            watched.append(runtime_db)
        before = {str(path): sha256(path) for path in watched}

        with tempfile.TemporaryDirectory(prefix="p1008-p3b-boundary-") as temp_dir:
            manager = RuntimeManager(PACKAGE_ROOT, RuntimeConfig.phase3b_shadow())
            result = manager.execute_plugin_shadow(
                run_type=self.monthly["run_type"],
                as_of_date=self.fixture["as_of_date"],
                packets=self.monthly["packets"],
                baseline=self.fixture["baseline"],
                output_root=Path(temp_dir),
            )

        after = {str(path): sha256(path) for path in watched}
        self.assertEqual(after, before)
        for field in (
            "formal_csv_changed",
            "runtime_sqlite_changed",
            "rules_changed",
            "hold_changed",
            "midr_changed",
            "scheduled",
            "actionable",
        ):
            self.assertFalse(result[field], field)

    def test_mock_output_is_non_actionable_and_has_no_trading_instruction(self) -> None:
        with tempfile.TemporaryDirectory(prefix="p1008-p3b-output-") as temp_dir:
            result = RuntimeManager(
                PACKAGE_ROOT, RuntimeConfig.phase3b_shadow()
            ).execute_plugin_shadow(
                run_type=self.monthly["run_type"],
                as_of_date=self.fixture["as_of_date"],
                packets=self.monthly["packets"],
                baseline=self.fixture["baseline"],
                output_root=Path(temp_dir),
            )
        output = json.dumps(
            result["report"].model_dump(mode="json", by_alias=True),
            ensure_ascii=False,
            sort_keys=True,
        )
        self.assertFalse(result["report"].actionable)
        forbidden = "|".join(("B" + "UY", "S" + "ELL", "A" + "DD", "T" + "RIM"))
        self.assertIsNone(re.search(rf"\b(?:{forbidden})\b", output, re.IGNORECASE))


if __name__ == "__main__":
    unittest.main()
