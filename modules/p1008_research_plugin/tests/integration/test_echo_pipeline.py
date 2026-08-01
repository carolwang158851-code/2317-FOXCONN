from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = MODULE_ROOT.parents[1]
sys.path.insert(0, str(MODULE_ROOT / "src"))

from p1008_research_plugin.orchestrator import ResearchOrchestrator
from p1008_research_plugin.runtime.artifact_writer import (
    ArtifactBoundaryError,
    ArtifactWriter,
)
from p1008_research_plugin.runtime.typed_output import TypedResearchArtifact


class EchoPipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.orchestrator = ResearchOrchestrator(PACKAGE_ROOT)
        self.request = {"symbol": "2317", "question": "test"}

    def test_echo_pipeline_is_typed_governed_and_memory_only(self) -> None:
        result = self.orchestrator.run(self.request)
        self.assertEqual(result["output"]["claims"][0]["claim"], "Echo Capability Active")
        self.assertFalse(result["output"]["actionable"])
        self.assertFalse(result["artifact"]["persisted"])
        self.assertFalse(result["ledger_changed"])
        self.assertFalse(result["governance_changed"])
        self.assertFalse(result["runtime_state_changed"])
        self.assertFalse(result["health"]["openai_enabled"])
        self.assertEqual(result["health"]["mock_calls"], 1)
        self.assertEqual(result["lifecycle"][-1], "COMPLETED")

    def test_replay_is_deterministic(self) -> None:
        first = self.orchestrator.run(self.request)
        second = self.orchestrator.run(self.request)
        self.assertEqual(first["request_id"], second["request_id"])
        self.assertEqual(first["output"], second["output"])
        self.assertEqual(first["artifact"]["sha256"], second["artifact"]["sha256"])

    def test_artifact_can_only_be_materialized_in_explicit_test_sandbox(self) -> None:
        output = self.orchestrator.run(self.request)["output"]
        artifact = TypedResearchArtifact.from_mapping(output)
        writer = ArtifactWriter(PACKAGE_ROOT)
        envelope = writer.build(artifact)
        with self.assertRaises(ArtifactBoundaryError):
            writer.write_test_only(envelope, MODULE_ROOT)
        with tempfile.TemporaryDirectory(prefix="p1008-p2a-") as temp_dir:
            path = writer.write_test_only(envelope, Path(temp_dir))
            self.assertTrue(path.is_relative_to(Path(temp_dir).resolve()))
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), output)


if __name__ == "__main__":
    unittest.main()
