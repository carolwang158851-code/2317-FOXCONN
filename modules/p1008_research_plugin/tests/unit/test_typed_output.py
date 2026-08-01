from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path


MODULE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(MODULE_ROOT / "src"))

from p1008_research_plugin.runtime.capability_registry import CapabilityRegistry
from p1008_research_plugin.runtime.runtime_validator import (
    RuntimeValidationError,
    RuntimeValidator,
)
from p1008_research_plugin.runtime.typed_output import TypedResearchArtifact


def valid_output() -> dict:
    return CapabilityRegistry().execute_echo({"context_id": "A" * 24})


class TypedOutputTests(unittest.TestCase):
    def setUp(self) -> None:
        self.validator = RuntimeValidator()

    def test_valid_echo_output_is_canonical_and_deterministic(self) -> None:
        output = self.validator.validate(valid_output())
        first = TypedResearchArtifact.from_mapping(output)
        second = TypedResearchArtifact.from_mapping(output)
        self.assertEqual(first.sha256(), second.sha256())
        self.assertFalse(first.to_dict()["actionable"])

    def test_missing_evidence_rejects_unsupported_claim(self) -> None:
        output = valid_output()
        output["evidence"] = []
        with self.assertRaises(RuntimeValidationError):
            self.validator.validate(output)

    def test_actionable_and_unknown_fields_are_rejected(self) -> None:
        actionable = valid_output()
        actionable["actionable"] = True
        with self.assertRaises(RuntimeValidationError):
            self.validator.validate(actionable)
        unknown = copy.deepcopy(valid_output())
        unknown["recommendation"] = "none"
        with self.assertRaises(RuntimeValidationError):
            self.validator.validate(unknown)

    def test_evidence_requires_registered_source(self) -> None:
        output = valid_output()
        output["evidence"][0]["source_ids"] = ["MISSING"]
        with self.assertRaises(RuntimeValidationError):
            self.validator.validate(output)


if __name__ == "__main__":
    unittest.main()
