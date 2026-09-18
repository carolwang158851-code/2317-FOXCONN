import hashlib
import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
V11 = ROOT / "contracts/p1008_formula_registry/v1.1"
V12 = ROOT / "contracts/p1008_formula_registry/v1.2"
RECORD = V12 / "acceptance/P1008_UD_RESEARCH_REVIEW_DECISION_V1.json"

HISTORICAL_AUTHORITY_HASHES = {
    "data/2317_master_v9.csv": "E623CA082F2A080613C33F4155BA8006646E30D6A517DE926AF6108062F84D48",
    "data/2317_daily_price.csv": "CBCF7D96490CB5B5C24E282F362F29953216DE8BEA16124D4B854842B250567C",
    "data/2317_daily_market_activity.csv": "86618182D9A6441DA9CE1761CF10D99D27F0B26B91CB4FEF732F3FE55447B326",
    "data/CSV_AUTHORITY_MANIFEST.json": "3A977A8B38A02D7F51C9E18F35B4E46464A3F148BCB97C9E9CBC1ADEC2861CDA",
}
CURRENT_AUTHORITY_HASHES = {
    "data/2317_master_v9.csv": "E623CA082F2A080613C33F4155BA8006646E30D6A517DE926AF6108062F84D48",
    "data/2317_daily_price.csv": "E79843DFAD1472314E6C01998B7E7017924FAC1C2A02F095BEFE13CB73D4A3FF",
    "data/2317_daily_market_activity.csv": "A8430FFCA96B5620A9924DC1973326627C33A30120E8D8FB2659051C1CC4D5D6",
    "data/CSV_AUTHORITY_MANIFEST.json": "C8CFD56D178918AABB3CAACE6725579BED10AC94EEF3B62D2A9DD0F125050459",
}

PROTECTED_HEAD_PATHS = (
    "src/index_p1008_v7.source.html",
    "dist/index_p1008_v7.bundle.js",
    "index_p1008_v7.html",
    "rules/RULE_STATUS_MANIFEST.json",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _governed_text_bytes(path: Path) -> bytes:
    return path.read_bytes().replace(b"\r\n", b"\n")


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


class UdResearchReviewDecisionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = _load(V12 / "formula_registry.json")
        cls.record = _load(RECORD)
        cls.entries = {entry["formulaId"]: entry for entry in cls.registry["entries"]}

    def test_v11_snapshot_remains_hash_valid_and_immutable(self):
        manifest = _load(V11 / "contract.manifest.json")
        self.assertEqual(manifest["rootHash"], "A35AC312C1C0B2D2E7D0D19C0E0FE3DC7E7B1B86F1352F817AAEF15B209AFD6A")
        for entry in manifest["artifacts"]:
            payload = _governed_text_bytes(V11 / entry["path"])
            self.assertEqual(hashlib.sha256(payload).hexdigest().upper(), entry["sha256"])
            self.assertEqual(len(payload), entry["sizeBytes"])

    def test_v12_registry_and_record_match_schema_contracts(self):
        registry_schema = _load(V12 / "schemas/formula_registry.schema.json")
        record_schema = _load(V12 / "schemas/ud_research_review_decision.schema.json")
        self.assertTrue(set(registry_schema["required"]).issubset(self.registry))
        self.assertEqual(self.registry["registryVersion"], registry_schema["properties"]["registryVersion"]["const"])
        self.assertEqual(self.registry["status"], registry_schema["properties"]["status"]["const"])
        self.assertTrue(set(record_schema["required"]).issubset(self.record))
        self.assertEqual(self.record["recordType"], record_schema["properties"]["recordType"]["const"])
        self.assertEqual(self.record["formulaId"], record_schema["properties"]["formulaId"]["const"])

    def test_v12_manifest_hashes_every_revision_artifact(self):
        manifest = _load(V12 / "contract.manifest.json")
        entries = manifest["artifacts"]
        self.assertEqual(len(entries), len({entry["path"] for entry in entries}))
        for entry in entries:
            artifact = V12 / entry["path"]
            self.assertTrue(artifact.is_file(), entry["path"])
            payload = _governed_text_bytes(artifact)
            self.assertEqual(hashlib.sha256(payload).hexdigest().upper(), entry["sha256"])
            self.assertEqual(len(payload), entry["sizeBytes"])
        material = "\n".join(sorted(f'{entry["path"]}|{entry["sha256"]}' for entry in entries))
        self.assertEqual(hashlib.sha256(material.encode("utf-8")).hexdigest().upper(), manifest["rootHash"])
        self.assertEqual(manifest["predecessorVersion"], "1.1")
        self.assertEqual(manifest["predecessorRootHash"], "A35AC312C1C0B2D2E7D0D19C0E0FE3DC7E7B1B86F1352F817AAEF15B209AFD6A")

    def test_ud_production_formula_remains_unchanged_and_protected(self):
        ud = self.entries["MIDR.UD"]
        self.assertEqual(ud["formulaDefinition"]["currentBehavior"], {"NORMAL": 1.0, "CAUTION": 0.9, "SYSTEMIC": 0.8})
        self.assertEqual(ud["formulaDefinition"]["productionFormula"], "MIDR_final = MIDR_raw * UD")
        self.assertEqual(ud["formulaDefinition"]["status"], "UNCHANGED_PROTECTED")
        self.assertFalse(self.registry["formulaChange"])
        self.assertFalse(self.registry["productionFormulaChanged"])
        self.assertFalse(self.registry["udValuesChanged"])

    def test_owner_decision_distinguishes_not_proven_from_proven_correct(self):
        decision = self.record["decisionSemantics"]
        self.assertEqual(decision["designIntent"], "NOT_PROVEN")
        self.assertEqual(decision["defect"], "NOT_PROVEN")
        self.assertFalse(decision["currentFormulaProvenCorrect"])
        self.assertFalse(decision["currentFormulaOptimalityProven"])
        self.assertFalse(decision["formulaChangeJustified"])
        self.assertEqual(decision["ownerDecision"], "KEEP_CURRENT")
        self.assertEqual(decision["udStatus"], "UNCHANGED_PROTECTED")

    def test_canonical_151_day_research_record_and_limitations(self):
        replay = self.record["canonicalBacktest"]
        self.assertEqual(replay["rows"], 151)
        self.assertEqual(replay["riskLevelCounts"], {"NORMAL": 45, "CAUTION": 106, "SYSTEMIC": 0})
        self.assertEqual(replay["rawVerdictCounts"], {"SEVERE": 59, "CAUTION": 49, "NEUTRAL": 43})
        self.assertEqual(replay["currentUdFinalCounts"], {"SEVERE": 51, "CAUTION": 55, "NEUTRAL": 45})
        self.assertEqual(replay["udCausedFlips"], 10)
        self.assertEqual(replay["systemicSample"], "NONE")
        self.assertEqual(replay["baselineSha256"], "2DE165ADD677DF2492FBC63F27CE6CAA25BBBE9708901740B99F1237F65AD18E")
        self.assertEqual(self.record["limitations"]["systemicObservations"], 0)
        self.assertFalse(self.record["limitations"]["outOfSampleValidation"])

    def test_research_candidates_are_not_activated(self):
        candidates = self.record["researchCandidates"]
        self.assertEqual(candidates["UD-0_CURRENT_SHRINKAGE"]["status"], "KEEP_PRODUCTION")
        self.assertTrue(candidates["UD-0_CURRENT_SHRINKAGE"]["productionActivated"])
        for candidate in ("UD-1_NO_UD", "UD-2_DOWNSIDE_AMPLIFIER", "UD-3_NEGATIVE_HOLD_POSITIVE_DISCOUNT"):
            self.assertFalse(candidates[candidate]["productionActivated"], candidate)
        self.assertFalse(self.record["candidateActivationAuthorized"])

    def test_rtm_mrd_and_actionable_state_remain_unchanged(self):
        self.assertEqual(self.entries["MIDR.RTM"]["formulaDefinition"]["currentProduction"], "RTM_0_TRUTHFUL_NEUTRAL")
        self.assertEqual(self.entries["MIDR.RTM"]["formulaDefinition"]["score"], 0)
        self.assertEqual(self.entries["MIDR.MRD_WIRING"]["formulaDefinition"]["currentProduction"], "MRD-M0_DISPLAY_ONLY")
        self.assertFalse(self.entries["MIDR.MRD_WIRING"]["activationStatus"]["dynamicThresholdActive"])
        self.assertFalse(self.registry["actionable"])
        self.assertFalse(self.record["actionable"])
        self.assertFalse(self.record["productionFormulaChange"])

    def test_authority_files_remain_unchanged(self):
        self.assertEqual(self.record["authorityProtection"]["beforeAndAfter"], HISTORICAL_AUTHORITY_HASHES)
        self.assertFalse(self.record["authorityProtection"]["authorityBytesChanged"])
        for relative, expected in CURRENT_AUTHORITY_HASHES.items():
            self.assertEqual(_sha256(ROOT / relative), expected, relative)

    def test_runtime_code_and_rule_files_match_head(self):
        for relative in PROTECTED_HEAD_PATHS:
            result = subprocess.run(
                ["git", "diff", "--quiet", "HEAD", "--", relative],
                cwd=ROOT,
            )
            self.assertEqual(result.returncode, 0, relative)
        protection = self.record["codeProtection"]
        for field in ("sourceHtmlChanged", "bundleChanged", "runtimeHtmlChanged", "ruleChanged", "holdChanged", "sqliteChanged"):
            self.assertFalse(protection[field], field)


if __name__ == "__main__":
    unittest.main()
