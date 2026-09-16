import csv
import hashlib
import json
import math
import shutil
import subprocess
import tempfile
import unittest
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTRY_ROOT = ROOT / "contracts" / "p1008_formula_registry" / "v1.0"
SOURCE = ROOT / "src" / "index_p1008_v7.source.html"

AUTHORITY_HASHES = {
    "data/2317_master_v9.csv": "E623CA082F2A080613C33F4155BA8006646E30D6A517DE926AF6108062F84D48",
    "data/2317_daily_price.csv": "CBCF7D96490CB5B5C24E282F362F29953216DE8BEA16124D4B854842B250567C",
    "data/2317_daily_market_activity.csv": "86618182D9A6441DA9CE1761CF10D99D27F0B26B91CB4FEF732F3FE55447B326",
    "data/CSV_AUTHORITY_MANIFEST.json": "3A977A8B38A02D7F51C9E18F35B4E46464A3F148BCB97C9E9CBC1ADEC2861CDA",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _read_governed_csv(path: Path):
    lines = [line for line in path.read_text(encoding="utf-8-sig").splitlines() if not line.startswith("##")]
    return list(csv.DictReader(lines))


def _number(row, key):
    value = row.get(key, "") if row else ""
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _risk_keyword(value):
    upper = (value or "").upper()
    if "SYSTEMIC" in upper:
        return "SYSTEMIC"
    if "CAUTION" in upper:
        return "CAUTION"
    if "STRONG" in upper:
        return "STRONG"
    return "NORMAL"


def _midr_numeric(daily_row, master_row, macro_row, rtm_score=0.1):
    current_pb = _number(daily_row, "PB_daily")
    current_price = _number(daily_row, "Close")
    cash_dividend = _number(master_row, "CashDividend")
    us10y = _number(macro_row, "US_10Y_Yield")
    fed_probability = _number(macro_row, "Fed_Hike_Prob_YE")
    eps_yoy = _number(master_row, "EPS_YoY_Pct")
    if None in (current_pb, current_price, cash_dividend, us10y, eps_yoy):
        raise AssertionError(f"Incomplete replay input on {daily_row.get('Date')}")

    current_yield = cash_dividend / current_price * 100
    excess_yield = current_yield - us10y
    if excess_yield >= 0:
        ya_score = min(1.0, math.log(1 + excess_yield) / math.log(3))
    else:
        ya_score = max(-1.0, -math.log(1 + abs(excess_yield)) / math.log(3))

    pb_ref, pb_add, pb_strict = 1.923, 1.162, 2.115
    if current_pb <= pb_ref:
        pb_score = min((pb_ref - current_pb) / (pb_ref - pb_add), 1.0) ** 0.88
    else:
        pb_score = max(
            -2.25 * min((current_pb - pb_ref) / (pb_strict - pb_ref), 2.0) ** 0.88 / 2.25,
            -1.0,
        )
    pb_score = max(pb_score + (-0.10 if current_pb > pb_ref else 0) + (-0.20 if current_pb > pb_strict else 0), -1.0)

    frv_score = 0.8 if eps_yoy > 50 else 0.5 if eps_yoy > 20 else 0.2
    mdr_score = -0.5 if us10y > 4.5 else -0.3 if us10y > 4.0 else 0.0
    if fed_probability is not None and fed_probability > 70:
        mdr_score -= 0.1
    risk = _risk_keyword(macro_row.get("RiskLevel"))
    ud = 0.90 if risk == "CAUTION" else 0.80 if risk == "SYSTEMIC" else 1.0
    raw = ya_score * 0.20 + pb_score * 0.25 + frv_score * 0.20 + rtm_score * 0.10 + mdr_score * 0.25
    total = float(f"{raw * ud:.3f}")
    verdict = "SEVERE" if total < -0.25 else "CAUTION" if total < -0.15 else "NEUTRAL"
    return total, verdict


class FormulaRegistryContractTests(unittest.TestCase):
    def test_registry_and_owner_record_validate_against_schemas(self):
        registry = json.loads((REGISTRY_ROOT / "formula_registry.json").read_text(encoding="utf-8"))
        registry_schema = json.loads((REGISTRY_ROOT / "schemas/formula_registry.schema.json").read_text(encoding="utf-8"))
        owner_record = json.loads((REGISTRY_ROOT / "acceptance/P1008_FORMULA_REGISTRY_OWNER_DECISION_V1.json").read_text(encoding="utf-8"))
        owner_schema = json.loads((REGISTRY_ROOT / "schemas/owner_decision_record.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(registry_schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
        self.assertEqual(owner_schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
        self.assertEqual(registry["formulaRegistryId"], registry_schema["properties"]["formulaRegistryId"]["const"])
        self.assertEqual(registry["registryVersion"], registry_schema["properties"]["registryVersion"]["const"])
        self.assertTrue(set(registry_schema["required"]).issubset(registry))
        for entry in registry["entries"]:
            self.assertTrue(set(registry_schema["properties"]["entries"]["items"]["required"]).issubset(entry))
        self.assertEqual(owner_record["recordType"], owner_schema["properties"]["recordType"]["const"])
        self.assertEqual(owner_record["recordVersion"], owner_schema["properties"]["recordVersion"]["const"])
        self.assertTrue(set(owner_schema["required"]).issubset(owner_record))

    def test_manifest_hashes_every_governed_artifact(self):
        manifest = json.loads((REGISTRY_ROOT / "contract.manifest.json").read_text(encoding="utf-8"))
        entries = manifest["artifacts"]
        self.assertEqual(len(entries), len({entry["path"] for entry in entries}))
        for entry in entries:
            artifact = REGISTRY_ROOT / entry["path"]
            self.assertTrue(artifact.is_file(), entry["path"])
            self.assertEqual(_sha256(artifact), entry["sha256"])
            self.assertEqual(artifact.stat().st_size, entry["sizeBytes"])
        material = "\n".join(sorted(f'{entry["path"]}|{entry["sha256"]}' for entry in entries))
        self.assertEqual(hashlib.sha256(material.encode("utf-8")).hexdigest().upper(), manifest["rootHash"])

    def test_registry_preserves_lifecycle_and_activation_distinctions(self):
        registry = json.loads((REGISTRY_ROOT / "formula_registry.json").read_text(encoding="utf-8"))
        entries = {entry["formulaId"]: entry for entry in registry["entries"]}
        rtm = entries["MIDR.RTM"]
        self.assertEqual(rtm["formulaDefinition"]["currentProduction"], "LEGACY_FIXED_0_1")
        self.assertEqual(rtm["formulaDefinition"]["preferredCandidate"], "RTM-0_TRUTHFUL_NEUTRAL")
        self.assertFalse(rtm["activationStatus"]["candidateProductionActivated"])
        self.assertFalse(rtm["dataProvenance"]["currentPeriodFallbackAllowed"])
        self.assertEqual(rtm["dataProvenance"]["currentPeriodStatus"], "DATA_UNAVAILABLE")
        mrd = entries["MIDR.MRD_WIRING"]
        self.assertEqual(mrd["formulaDefinition"]["currentProduction"], "DISPLAY_ONLY")
        self.assertFalse(mrd["formulaDefinition"]["thresholdConsumedByMidrVerdict"])
        self.assertFalse(mrd["activationStatus"]["dynamicThresholdActive"])
        self.assertEqual(mrd["formulaDefinition"]["rejectedAlternatives"]["MRD-M1_CAUTION_BOUNDARY_ONLY"], "REJECTED_CURRENT_MAPPING")
        self.assertEqual(mrd["formulaDefinition"]["rejectedAlternatives"]["MRD-M2_BOUNDARY_OFFSET_MODEL"], "REJECTED_CURRENT_MAPPING")
        self.assertEqual(entries["MIDR.UD"]["formulaDefinition"]["currentBehavior"], {"NORMAL": 1.0, "CAUTION": 0.9, "SYSTEMIC": 0.8})
        self.assertFalse(registry["actionable"])
        self.assertFalse(registry["productionActivation"])

    def test_owner_decision_is_not_an_activation_receipt(self):
        record = json.loads((REGISTRY_ROOT / "acceptance/P1008_FORMULA_REGISTRY_OWNER_DECISION_V1.json").read_text(encoding="utf-8"))
        self.assertTrue(record["decisions"]["RTM_0_CANDIDATE_APPROVED"])
        self.assertFalse(record["decisions"]["RTM_0_PRODUCTION_ACTIVATED"])
        self.assertTrue(record["decisions"]["MRD_M0_CURRENT_BEHAVIOR_APPROVED"])
        self.assertFalse(record["decisions"]["UD_CHANGE_ALLOWED"])
        self.assertFalse(record["activationReceipt"])
        self.assertIsNone(record["implementationCommitSha"])
        self.assertEqual(record["commitStatus"], "NOT_COMMITTED")

    def test_authority_bytes_match_protected_baseline(self):
        for relative, expected in AUTHORITY_HASHES.items():
            self.assertEqual(_sha256(ROOT / relative), expected, relative)
        record = json.loads((REGISTRY_ROOT / "acceptance/P1008_FORMULA_REGISTRY_OWNER_DECISION_V1.json").read_text(encoding="utf-8"))
        self.assertEqual(record["authorityProtection"]["preImplementation"], AUTHORITY_HASHES)
        self.assertEqual(record["authorityProtection"]["postImplementation"], AUTHORITY_HASHES)
        self.assertFalse(record["authorityProtection"]["authorityBytesChanged"])
        self.assertFalse(record["authorityProtection"]["missingValuesFabricatedOrZeroFilled"])


class MidrTruthfulnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = SOURCE.read_text(encoding="utf-8")

    def test_numeric_formula_verdict_and_ud_are_unchanged_except_approved_rtm_activation(self):
        self.assertIn("const RTM_SCORE = 0;", self.source)
        self.assertEqual(self.source.count("const rtmScore = RTM_SCORE;"), 2)
        self.assertEqual(self.source.count("rtmScore * w.rtm"), 4)
        self.assertEqual(self.source.count("parseFloat(total) < -0.25"), 1)
        self.assertEqual(self.source.count("parseFloat(total) < -0.15"), 1)
        self.assertEqual(self.source.count("parseFloat(totalMidr2) < -0.25"), 1)
        self.assertEqual(self.source.count("parseFloat(totalMidr2) < -0.15"), 1)
        self.assertIn("riskKeyword === 'CAUTION' ? 0.90 : riskKeyword === 'SYSTEMIC' ? 0.80 : 1.0", self.source)
        self.assertIn("rawRiskLevel === 'CAUTION' ? 0.90 : rawRiskLevel === 'SYSTEMIC' ? 0.80 : 1.0", self.source)

    def test_truthful_rtm_metadata_replaces_misleading_fields(self):
        self.assertNotIn("rtm: 1.1", self.source)
        self.assertNotIn("<td className=\"py-3 text-emerald-400\">RISING</td>", self.source)
        self.assertNotIn("const zForeign = rawRiskLevel", self.source)
        self.assertNotIn("zForeign: riskKeyword ===", self.source)
        self.assertIn("const RTM_MODE = 'TRUTHFUL_NEUTRAL'", self.source)
        self.assertIn("rtmRawScore: RTM_SCORE", self.source)
        self.assertIn("rtmWeightedRawContribution: RTM_WEIGHTED_RAW_CONTRIBUTION", self.source)
        self.assertIn("rtmContributionStatus: 'NEUTRAL_ZERO_BY_GOVERNANCE'", self.source)
        self.assertIn("approvedForeignNumericMapping: 'NONE'", self.source)
        self.assertIn("missingForeignDataZeroFilled: false", self.source)
        self.assertIn("zForeign: 'NOT_AVAILABLE_NOT_DERIVED_FROM_FOREIGN_DATA'", self.source)
        self.assertIn("currentPeriodFallbackUsed: false", self.source)

    def test_current_2026q2_foreign_data_does_not_fall_back(self):
        rows = sorted(_read_governed_csv(ROOT / "data/2317_master_v9.csv"), key=lambda row: row["Quarter"], reverse=True)
        self.assertEqual(rows[0]["Quarter"], "2026Q2")
        self.assertIsNone(_number(rows[0], "ForeignHoldChange_Pct"))
        self.assertFalse(rows[0].get("ForeignHoldTrend"))
        populated = next(row for row in rows if _number(row, "ForeignHoldChange_Pct") is not None and row.get("ForeignHoldTrend"))
        self.assertEqual(populated["Quarter"], "2026Q1")
        self.assertIn("latestGovernedForeignPeriod", self.source)
        self.assertIn("rtmCurrentPeriodStatus: currentPeriodAvailable ? 'AVAILABLE' : 'DATA_UNAVAILABLE'", self.source)

    def test_mrd_remains_display_only_and_diagnostic(self):
        self.assertNotIn("MIDR 觀察門檻調整為", self.source)
        self.assertGreaterEqual(self.source.count("NOT_CONSUMED_BY_MIDR_VERDICT"), 8)
        self.assertIn("MRD 診斷參考 {midrResult?.threshold}", self.source)
        self.assertIn("MIDR 判讀邊界維持 -0.25/-0.15", self.source)
        self.assertGreaterEqual(self.source.count("actionable: false"), 10)

    def test_151_date_numeric_and_verdict_replay_matches_baseline(self):
        daily = _read_governed_csv(ROOT / "data/2317_daily_price.csv")
        master = _read_governed_csv(ROOT / "data/2317_master_v9.csv")
        macro = _read_governed_csv(ROOT / "data/macro_snapshot.csv")
        master = [row for row in master if row.get("EstimatedEffectiveDate")]
        macro = [row for row in macro if row.get("Date")]
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
                    (row for row in eligible_macro if _number(row, field) is not None),
                    key=lambda row: row["Date"],
                )
                macro_row[field] = latest_nonblank[field]
            total, verdict = _midr_numeric(daily_row, master_row, macro_row)
            replay.append((daily_row["Date"], total, verdict))
        self.assertEqual(len(replay), 151)
        self.assertEqual(Counter(verdict for _, _, verdict in replay), {"SEVERE": 51, "CAUTION": 48, "NEUTRAL": 52})
        replay_material = "\n".join(f"{day}|{total:.3f}|{verdict}" for day, total, verdict in replay)
        self.assertEqual(
            hashlib.sha256(replay_material.encode("utf-8")).hexdigest().upper(),
            "A234DD3A99360E4EE5586EF00D850CC0CAB09578DA926584FC40C49AD21546AC",
        )

    def test_source_bundle_and_runtime_html_parity(self):
        if shutil.which("node") is None:
            self.skipTest("node is required for the deterministic P1008 build")
        with tempfile.TemporaryDirectory(prefix="p1008-formula-registry-build-") as temp:
            temp_root = Path(temp)
            for relative in ("tools", "src", "vendor", "dist"):
                (temp_root / relative).mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / "tools/build_index_p1008_v7.js", temp_root / "tools/build_index_p1008_v7.js")
            shutil.copy2(SOURCE, temp_root / "src/index_p1008_v7.source.html")
            shutil.copy2(ROOT / "vendor/babel-standalone-7.12.9.min.js", temp_root / "vendor/babel-standalone-7.12.9.min.js")
            subprocess.run(["node", "tools/build_index_p1008_v7.js"], cwd=temp_root, check=True, capture_output=True, text=True)
            generated_bundle = (temp_root / "dist/index_p1008_v7.bundle.js").read_text(encoding="utf-8").replace("\r\n", "\n")
            tracked_bundle = (ROOT / "dist/index_p1008_v7.bundle.js").read_text(encoding="utf-8").replace("\r\n", "\n")
            generated_html = (temp_root / "index_p1008_v7.html").read_text(encoding="utf-8").replace("\r\n", "\n")
            tracked_html = (ROOT / "index_p1008_v7.html").read_text(encoding="utf-8").replace("\r\n", "\n")
            self.assertEqual(generated_bundle, tracked_bundle)
            self.assertEqual(generated_html, tracked_html)


if __name__ == "__main__":
    unittest.main()
