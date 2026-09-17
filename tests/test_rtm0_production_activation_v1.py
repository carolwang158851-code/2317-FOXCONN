import hashlib
import json
import unittest
from collections import Counter
from datetime import date
from pathlib import Path

from tests import test_formula_registry_and_midr_truthfulness_v1 as baseline


ROOT = Path(__file__).resolve().parents[1]
V10 = ROOT / "contracts/p1008_formula_registry/v1.0"
V11 = ROOT / "contracts/p1008_formula_registry/v1.1"
SOURCE = ROOT / "src/index_p1008_v7.source.html"
RECEIPT_PATH = V11 / "acceptance/P1008_RTM0_PRODUCTION_ACTIVATION_RECEIPT_V1.json"

BEFORE_SHA256 = "A234DD3A99360E4EE5586EF00D850CC0CAB09578DA926584FC40C49AD21546AC"
AFTER_SHA256 = "899E8452509C7BD248253E59D587BAFEDDB533DE67F06FCD1C2A74EFAD9AF0AB"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _governed_text_bytes(path: Path) -> bytes:
    return path.read_bytes().replace(b"\r\n", b"\n")


def _replay_rows():
    daily = baseline._read_governed_csv(ROOT / "data/2317_daily_price.csv")
    master = [row for row in baseline._read_governed_csv(ROOT / "data/2317_master_v9.csv") if row.get("EstimatedEffectiveDate")]
    macro = [row for row in baseline._read_governed_csv(ROOT / "data/macro_snapshot.csv") if row.get("Date")]
    replay = []
    for daily_row in daily:
        current_date = date.fromisoformat(daily_row["Date"])
        master_row = max(
            (row for row in master if date.fromisoformat(row["EstimatedEffectiveDate"]) <= current_date),
            key=lambda row: row["EstimatedEffectiveDate"],
        )
        eligible_macro = [row for row in macro if date.fromisoformat(row["Date"]) <= current_date]
        macro_row = dict(max(eligible_macro, key=lambda row: row["Date"]))
        for field in ("US_10Y_Yield", "Fed_Hike_Prob_YE"):
            latest_nonblank = max(
                (row for row in eligible_macro if baseline._number(row, field) is not None),
                key=lambda row: row["Date"],
            )
            macro_row[field] = latest_nonblank[field]
        old_total, old_verdict = baseline._midr_numeric(daily_row, master_row, macro_row, 0.1)
        new_total, new_verdict = baseline._midr_numeric(daily_row, master_row, macro_row, 0.0)
        risk = baseline._risk_keyword(macro_row.get("RiskLevel"))
        ud = 0.90 if risk == "CAUTION" else 0.80 if risk == "SYSTEMIC" else 1.0
        replay.append(
            {
                "date": daily_row["Date"],
                "old_total": old_total,
                "new_total": new_total,
                "delta": new_total - old_total,
                "old_verdict": old_verdict,
                "new_verdict": new_verdict,
                "ud": ud,
                "old_rtm_weighted": 0.01 * ud,
                "new_rtm_weighted": 0.0,
            }
        )
    return replay


def _activation_serialization(rows):
    return "\n".join(
        f'{row["date"]}|{row["old_total"]:.3f}|{row["new_total"]:.3f}|{row["delta"]:.3f}|'
        f'{row["old_verdict"]}|{row["new_verdict"]}|{row["ud"]:.2f}|'
        f'{row["old_rtm_weighted"]:.3f}|{row["new_rtm_weighted"]:.3f}'
        for row in rows
    )


class Rtm0RegistryActivationTests(unittest.TestCase):
    def test_v10_snapshot_remains_hash_valid_and_immutable(self):
        manifest = json.loads((V10 / "contract.manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["rootHash"], "86FEDB268064923A02E8F8B3F8814B8098AFFB9A526DA657FD85A96829D54B1B")
        for entry in manifest["artifacts"]:
            self.assertEqual(
                hashlib.sha256(_governed_text_bytes(V10 / entry["path"])).hexdigest().upper(),
                entry["sha256"],
            )

    def test_v11_registry_and_receipt_match_schema_contracts(self):
        registry = json.loads((V11 / "formula_registry.json").read_text(encoding="utf-8"))
        schema = json.loads((V11 / "schemas/formula_registry.schema.json").read_text(encoding="utf-8"))
        receipt = json.loads(RECEIPT_PATH.read_text(encoding="utf-8"))
        receipt_schema = json.loads((V11 / "schemas/activation_receipt.schema.json").read_text(encoding="utf-8"))
        self.assertTrue(set(schema["required"]).issubset(registry))
        self.assertEqual(registry["registryVersion"], schema["properties"]["registryVersion"]["const"])
        self.assertTrue(set(receipt_schema["required"]).issubset(receipt))
        self.assertEqual(receipt["recordType"], receipt_schema["properties"]["recordType"]["const"])

    def test_v11_manifest_hashes_every_revision_artifact(self):
        manifest = json.loads((V11 / "contract.manifest.json").read_text(encoding="utf-8"))
        entries = manifest["artifacts"]
        for entry in entries:
            artifact = V11 / entry["path"]
            self.assertTrue(artifact.is_file(), entry["path"])
            payload = _governed_text_bytes(artifact)
            self.assertEqual(hashlib.sha256(payload).hexdigest().upper(), entry["sha256"])
            self.assertEqual(len(payload), entry["sizeBytes"])
        material = "\n".join(sorted(f'{entry["path"]}|{entry["sha256"]}' for entry in entries))
        self.assertEqual(hashlib.sha256(material.encode("utf-8")).hexdigest().upper(), manifest["rootHash"])
        self.assertEqual(manifest["predecessorRootHash"], "86FEDB268064923A02E8F8B3F8814B8098AFFB9A526DA657FD85A96829D54B1B")

    def test_rtm0_is_current_and_legacy_is_historical(self):
        registry = json.loads((V11 / "formula_registry.json").read_text(encoding="utf-8"))
        entries = {entry["formulaId"]: entry for entry in registry["entries"]}
        rtm = entries["MIDR.RTM"]
        self.assertEqual(rtm["formulaDefinition"]["currentProduction"], "RTM_0_TRUTHFUL_NEUTRAL")
        self.assertEqual(rtm["formulaDefinition"]["score"], 0)
        self.assertEqual(rtm["formulaDefinition"]["weight"], 0.1)
        self.assertEqual(rtm["formulaDefinition"]["weightedRawContribution"], 0)
        self.assertEqual(rtm["formulaDefinition"]["approvedForeignNumericMapping"], "NONE")
        self.assertEqual(rtm["formulaDefinition"]["legacyPreviousProduction"]["formula"], "LEGACY_FIXED_0_1")
        self.assertFalse(rtm["formulaDefinition"]["missingForeignDataZeroFilled"])
        self.assertFalse(rtm["dataProvenance"]["currentPeriodFallbackAllowed"])
        self.assertFalse(rtm["dataProvenance"]["foreignObservationUsedForNumericScoring"])

    def test_activation_receipt_distinguishes_candidate_and_activation(self):
        receipt = json.loads(RECEIPT_PATH.read_text(encoding="utf-8"))
        self.assertEqual(receipt["candidateApproval"]["status"], "PREVIOUSLY_COMPLETED")
        self.assertEqual(receipt["productionActivation"]["newProductionFormula"], "RTM_0_TRUTHFUL_NEUTRAL")
        self.assertEqual(receipt["productionActivation"]["priorProductionFormula"], "LEGACY_FIXED_0_1")
        self.assertTrue(receipt["activationReceipt"])
        self.assertIsNone(receipt["implementationCommitSha"])
        self.assertEqual(receipt["commitStatus"], "NOT_COMMITTED")
        self.assertFalse(receipt["actionable"])

    def test_every_active_source_path_uses_truthful_neutral(self):
        source = SOURCE.read_text(encoding="utf-8")
        self.assertIn("const RTM_MODE = 'TRUTHFUL_NEUTRAL';", source)
        self.assertIn("const RTM_SCORE = 0;", source)
        self.assertIn("const RTM_WEIGHTED_RAW_CONTRIBUTION = 0;", source)
        self.assertEqual(source.count("const rtmScore = RTM_SCORE;"), 2)
        self.assertNotIn("const rtmScore = 0.1", source)
        self.assertEqual(source.count("rtm: 1.1"), 0)
        self.assertNotIn("const zForeign = rawRiskLevel", source)
        self.assertNotIn("zForeign: riskKeyword ===", source)
        self.assertNotIn('<td className="py-3 text-emerald-400">RISING</td>', source)
        self.assertIn("NEUTRAL_ZERO_BY_GOVERNANCE", source)
        self.assertIn("missingForeignDataZeroFilled: false", source)

    def test_only_rtm_changes_across_current_authority_replay(self):
        rows = _replay_rows()
        self.assertEqual(len(rows), 153)
        self.assertEqual(Counter(row["old_verdict"] for row in rows), {"SEVERE": 51, "CAUTION": 50, "NEUTRAL": 52})
        self.assertEqual(Counter(row["new_verdict"] for row in rows), {"SEVERE": 51, "CAUTION": 57, "NEUTRAL": 45})
        flips = Counter((row["old_verdict"], row["new_verdict"]) for row in rows if row["old_verdict"] != row["new_verdict"])
        self.assertEqual(flips, {("NEUTRAL", "CAUTION"): 7})
        for row in rows:
            self.assertAlmostEqual(row["delta"], -0.01 * row["ud"], places=12)
            self.assertAlmostEqual(row["old_rtm_weighted"] - row["new_rtm_weighted"], 0.01 * row["ud"], places=12)
        serialization = _activation_serialization(rows)
        self.assertEqual(
            hashlib.sha256(serialization.encode("utf-8")).hexdigest().upper(),
            "A314A0D88C7131BA5C64CC50FABE298206D9DCD3416F918E165D1C872B7C0282",
        )

    def test_invariants_and_authority_bytes_are_protected(self):
        registry = json.loads((V11 / "formula_registry.json").read_text(encoding="utf-8"))
        entries = {entry["formulaId"]: entry for entry in registry["entries"]}
        self.assertEqual(entries["MIDR.MRD_WIRING"]["formulaDefinition"]["currentProduction"], "MRD-M0_DISPLAY_ONLY")
        self.assertFalse(entries["MIDR.MRD_WIRING"]["activationStatus"]["dynamicThresholdActive"])
        self.assertEqual(entries["MIDR.UD"]["formulaDefinition"]["currentBehavior"], {"NORMAL": 1.0, "CAUTION": 0.9, "SYSTEMIC": 0.8})
        receipt = json.loads(RECEIPT_PATH.read_text(encoding="utf-8"))
        invariants = receipt["invariantProtection"]
        for field in ("YAChanged", "VALChanged", "FRVChanged", "MDRChanged", "MRDChanged", "midrWeightsChanged", "midrVerdictBoundariesChanged", "UDChanged", "holdChanged", "ruleChanged", "sqliteChanged"):
            self.assertFalse(invariants[field], field)
        for relative, expected in baseline.CURRENT_AUTHORITY_HASHES.items():
            self.assertEqual(_sha256(ROOT / relative), expected, relative)


if __name__ == "__main__":
    unittest.main()
