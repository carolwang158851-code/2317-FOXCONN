from __future__ import annotations

import copy
import json
import os
import shutil
import stat
import sys
import unittest
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
for item in (ROOT / "tools", ROOT / "modules" / "p1008_research_plugin" / "src"):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

import warroom_major_event_report_persistence as persistence  # noqa: E402
import warroom_quarterly_editorial_return as editorial  # noqa: E402
import warroom_rolling_brief as rolling_brief  # noqa: E402


def _remove_tree(path: Path) -> None:
    def clear_read_only(function, target, _exc):
        os.chmod(target, stat.S_IWRITE)
        function(target)
    if path.exists():
        shutil.rmtree(path, onexc=clear_read_only)


class QuarterlyEditorialReturnTests(unittest.TestCase):
    def setUp(self) -> None:
        self.case = ROOT / "runtime" / "report_production" / "test_scratch" / f"editorial-{uuid.uuid4().hex}"
        self.case.mkdir(parents=True)
        runtime = json.loads((ROOT / rolling_brief.RUNTIME_MANIFEST_REL).read_text(encoding="utf-8"))
        library = json.loads((ROOT / rolling_brief.REPORT_MANIFEST_REL).read_text(encoding="utf-8"))
        q2_key = "P1008_FY2026_Q2_EARNINGS"
        runtime["reports"] = [item for item in runtime["reports"] if item.get("report_key") == q2_key]
        library["reports"] = [item for item in library["reports"] if item.get("report_key") == q2_key]
        runtime["latest"] = {key: (value if isinstance(value, dict) and value.get("report_key") == q2_key else None)
                             for key, value in runtime["latest"].items()}
        library["latest"] = {key: (value if isinstance(value, dict) and value.get("report_key") == q2_key else None)
                             for key, value in library["latest"].items()}
        for target, value in ((self.case / rolling_brief.RUNTIME_MANIFEST_REL, runtime),
                              (self.case / rolling_brief.REPORT_MANIFEST_REL, library)):
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(rolling_brief._canonical_json_bytes(value))
        entry = library["reports"][0]
        for locator in [entry["reportCandidateLocator"], entry["editorialValidationLocator"],
                        entry["ownerReviewLocator"], *[item["locator"] for item in entry["renderedArtifacts"]]]:
            target = self.case / locator
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / locator, target)
        candidate = json.loads((self.case / entry["reportCandidateLocator"]).read_text(encoding="utf-8"))
        run_id = candidate["runId"]
        for relative in ("analysis_packet.json", "enterprise_value_war_report/chart_data_full_history.json"):
            source = ROOT / "runtime" / "report_production" / run_id / relative
            target = self.case / "runtime" / "report_production" / run_id / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        self.q2_key = q2_key
        self.candidate = candidate

    def tearDown(self) -> None:
        _remove_tree(self.case)
        try:
            self.case.parent.rmdir()
        except OSError:
            pass

    def envelope(self, *, key: str | None = None, parent: str = "e0", candidate=None):
        return {"report_key": key or self.q2_key, "revision": 1,
                "parentEditorialVersion": parent,
                "reportCandidate": candidate or copy.deepcopy(self.candidate)}

    def add_q3(self) -> str:
        q3_key = "P1008_FY2026_Q3_EARNINGS"
        runtime = json.loads((self.case / rolling_brief.RUNTIME_MANIFEST_REL).read_text(encoding="utf-8"))
        library = json.loads((self.case / rolling_brief.REPORT_MANIFEST_REL).read_text(encoding="utf-8"))
        for manifest in (runtime, library):
            source = manifest["reports"][0]
            item = copy.deepcopy(source)
            item["id"] = f"{q3_key}_R1"
            item["report_key"] = q3_key
            item["canonicalEventId"] = "HON_HAI_FY2026_Q3_EARNINGS"
            item["provenance"]["canonicalEventId"] = "HON_HAI_FY2026_Q3_EARNINGS"
            for field in ("reportCandidateLocator", "editorialValidationLocator", "ownerReviewLocator"):
                item[field] = item[field].replace(self.q2_key, q3_key)
            for artifact in item["renderedArtifacts"]:
                artifact["locator"] = artifact["locator"].replace(self.q2_key, q3_key)
            for artifact in item["pluginArtifacts"]:
                artifact["path"] = artifact["path"].replace(self.q2_key, q3_key)
            html_sha = next(value["sha256"] for value in item["renderedArtifacts"] if value["format"] == "HTML")
            item["governedContentSha256"] = editorial.completion._governed_content_sha(
                item["analysisCandidateSha256"], item["reportCandidateSha256"],
                item["editorialValidationSha256"], html_sha, item["provenance"]
            )
            manifest["reports"].append(item)
            manifest["latest"][f"quarterly:{q3_key}"] = copy.deepcopy(item)
        q2_entry, q3_entry = library["reports"]
        for field in ("reportCandidateLocator", "editorialValidationLocator"):
            target = self.case / q3_entry[field]
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(self.case / q2_entry[field], target)
        for left, right in zip(q2_entry["renderedArtifacts"], q3_entry["renderedArtifacts"]):
            target = self.case / right["locator"]
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(self.case / left["locator"], target)
        owner = json.loads((self.case / q2_entry["ownerReviewLocator"]).read_text(encoding="utf-8"))
        owner.update({"report_key": q3_key, "canonicalEventId": "HON_HAI_FY2026_Q3_EARNINGS",
                      "provenance": copy.deepcopy(q3_entry["provenance"]),
                      "renderedArtifacts": copy.deepcopy(q3_entry["renderedArtifacts"])})
        owner.pop("persistenceSha256")
        owner["persistenceSha256"] = persistence._sha256(persistence._canonical_bytes(owner))
        owner_body = persistence._canonical_bytes(owner)
        owner_target = self.case / q3_entry["ownerReviewLocator"]
        owner_target.parent.mkdir(parents=True, exist_ok=True)
        owner_target.write_bytes(owner_body)
        for manifest in (runtime, library):
            item = manifest["reports"][-1]
            for artifact in item["pluginArtifacts"]:
                if artifact["path"] == item["ownerReviewLocator"]:
                    artifact["sha256"] = persistence._sha256(owner_body)
            manifest["latest"][f"quarterly:{q3_key}"] = copy.deepcopy(item)
        (self.case / rolling_brief.RUNTIME_MANIFEST_REL).write_bytes(rolling_brief._canonical_json_bytes(runtime))
        (self.case / rolling_brief.REPORT_MANIFEST_REL).write_bytes(rolling_brief._canonical_json_bytes(library))
        return q3_key

    def test_import_is_pending_then_owner_apply_advances_same_revision(self):
        changed = copy.deepcopy(self.candidate)
        changed["sections"][0]["titleZh"] += "（潤稿）"
        imported = editorial.import_editorial_return(self.case, self.envelope(candidate=changed), created_at="2026-09-08T01:00:00Z")
        self.assertEqual(imported["status"], "PENDING")
        before = editorial.editorial_history(self.case, self.q2_key, 1)
        self.assertEqual(before["currentEditorialVersion"], "e0")
        self.assertEqual([item["editorialVersion"] for item in before["versions"]], ["e0", "e1"])
        applied = editorial.apply_editorial_return(self.case, self.q2_key, 1, "e1", applied_at="2026-09-08T01:01:00Z")
        self.assertEqual(applied["status"], "OWNER_REVIEW_REQUIRED")
        self.assertEqual(applied["currentEditorialVersion"], "e1")
        self.assertFalse(applied["publication"])
        catalog = editorial.quarterly_editorial_catalog(self.case)
        self.assertEqual(catalog["reportCardCount"], 1)
        self.assertEqual(catalog["reports"][0]["revision"], 1)

    def test_wrong_parent_and_real_numeric_change_fail_closed_without_pending_write(self):
        wrong_parent = editorial.import_editorial_return(self.case, self.envelope(parent="e9"))
        self.assertEqual(wrong_parent["status"], "FAIL_CLOSED")
        changed = copy.deepcopy(self.candidate)
        located = False
        for section in changed["sections"]:
            if "12.61" in section["bodyZh"]:
                section["bodyZh"] = section["bodyZh"].replace("12.61", "12.62", 1)
                located = True
                break
        self.assertTrue(located)
        invalid = editorial.import_editorial_return(self.case, self.envelope(candidate=changed))
        self.assertEqual(invalid["status"], "FAIL_CLOSED")
        self.assertIn("Unsupported numeric claims", invalid["reason"])
        self.assertFalse((self.case / editorial._history_rel(self.q2_key, 1)).exists())

    def test_wrong_report_identity_and_tampered_pending_content_fail_closed(self):
        wrong_key = editorial.import_editorial_return(
            self.case, self.envelope(key="P1008_FY2026_Q4_EARNINGS")
        )
        wrong_revision = self.envelope()
        wrong_revision["revision"] = 2
        self.assertEqual(wrong_key["status"], "FAIL_CLOSED")
        self.assertEqual(editorial.import_editorial_return(self.case, wrong_revision)["status"], "FAIL_CLOSED")
        changed = copy.deepcopy(self.candidate)
        changed["sections"][0]["titleZh"] += "（待驗證）"
        imported = editorial.import_editorial_return(self.case, self.envelope(candidate=changed))
        self.assertEqual(imported["status"], "PENDING")
        history = editorial.editorial_history(self.case, self.q2_key, 1)
        pending = history["versions"][-1]
        snapshot = json.loads((self.case / pending["snapshotLocator"]).read_text(encoding="utf-8"))
        candidate_path = self.case / snapshot["candidateLocator"]
        candidate_path.write_bytes(candidate_path.read_bytes() + b" ")
        applied = editorial.apply_editorial_return(self.case, self.q2_key, 1, "e1")
        self.assertEqual(applied["status"], "FAIL_CLOSED")
        self.assertIn("TAMPERED", applied["reason"])

    def test_section_source_lineage_cannot_be_reassigned(self):
        changed = copy.deepcopy(self.candidate)
        changed["sections"][0]["evidenceIds"] = changed["sections"][1]["evidenceIds"]
        result = editorial.import_editorial_return(self.case, self.envelope(candidate=changed))
        self.assertEqual(result["status"], "FAIL_CLOSED")
        self.assertIn("EVIDENCE_LINEAGE_CHANGED", result["reason"])

    def test_decimal_equivalent_formatting_is_accepted(self):
        changed = copy.deepcopy(self.candidate)
        located = False
        for section in changed["sections"]:
            if "597.30" in section["bodyZh"]:
                section["bodyZh"] = section["bodyZh"].replace("597.30", "597.3", 1)
                located = True
                break
        self.assertTrue(located)
        result = editorial.import_editorial_return(self.case, self.envelope(candidate=changed))
        self.assertEqual(result["status"], "PENDING")

    def test_q3_history_is_isolated_and_latest_is_navigation_only(self):
        q3_key = self.add_q3()
        q2_before = editorial.editorial_history(self.case, self.q2_key, 1)
        changed = copy.deepcopy(self.candidate)
        changed["sections"][1]["titleZh"] += "（Q3 潤稿測試）"
        result = editorial.import_editorial_return(self.case, self.envelope(key=q3_key, candidate=changed))
        self.assertEqual(result["status"], "PENDING")
        q2_after = editorial.editorial_history(self.case, self.q2_key, 1)
        q3_after = editorial.editorial_history(self.case, q3_key, 1)
        self.assertEqual(q2_before, q2_after)
        self.assertEqual(q3_after["currentEditorialVersion"], "e0")
        self.assertEqual(len(q3_after["versions"]), 2)
        catalog = editorial.quarterly_editorial_catalog(self.case)
        self.assertEqual([item["report_key"] for item in catalog["reports"]], [q3_key, self.q2_key])


if __name__ == "__main__":
    unittest.main()
