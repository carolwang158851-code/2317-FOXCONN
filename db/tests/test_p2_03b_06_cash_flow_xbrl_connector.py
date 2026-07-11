from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


PACKAGE_ROOT = Path(__file__).resolve().parents[2]
TOOL_PATH = PACKAGE_ROOT / "db" / "tools" / "p2_03b_06_cash_flow_xbrl_connector.py"
SPEC = importlib.util.spec_from_file_location(
    "p2_03b_06_cash_flow_xbrl_connector", TOOL_PATH
)
connector = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = connector
SPEC.loader.exec_module(connector)


VALUES = {
    "ifrs-full:CashFlowsFromUsedInOperatingActivities": ("3,217,154", None),
    "tifrs-SCF:NetCashFlowsFromUsedInInvestingActivities": ("29,019,834", "-"),
    "tifrs-SCF:CashFlowsFromUsedInFinancingActivities": ("26,010,315", "-"),
    "ifrs-full:PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities":
        ("35,774,345", "-"),
    "ifrs-full:AdjustmentsForDepreciationExpense": ("25,883,347", None),
    "ifrs-full:AdjustmentsForAmortisationExpense": ("916,754", None),
    "ifrs-full:IncreaseDecreaseInCashAndCashEquivalents": ("30,122,657", "-"),
    "tifrs-SCF:CashAndCashEquivalentsAtEndOfPeriod": ("986,317,310", None),
}


def listing_html() -> bytes:
    return """
    <table>
      <tr><th>年度季別</th><th>財報類別</th><th>下載</th></tr>
      <tr><td>114Q4</td><td>合併</td><td><input onclick="window.open('/server-java/FileDownLoad?functionName=t164sb01&amp;step=9&amp;co_id=2317&amp;year=2025&amp;season=4&amp;report_id=C','new1');"/></td></tr>
      <tr><td>101Q4</td><td>合併</td><td><input onclick="window.open('/server-java/FileDownLoad?functionName=t147sb02&amp;step=9&amp;co_id=2317&amp;year=2012&amp;season=4&amp;report_id=B','new1');"/></td></tr>
      <tr><td>115Q1</td><td>個別</td><td><input onclick="window.open('/server-java/FileDownLoad?functionName=t164sb01&amp;step=9&amp;co_id=2317&amp;year=2026&amp;season=1&amp;report_id=A','new1');"/></td></tr>
      <tr><td>115Q1</td><td>合併</td><td><input onclick="window.open('/server-java/FileDownLoad?functionName=t164sb01&amp;step=9&amp;co_id=2317&amp;year=2026&amp;season=1&amp;report_id=C','new1');"/></td></tr>
    </table>
    """.encode()


def fact_xml(
    concept: str,
    value: str,
    sign: str | None,
    unit: str = "TWD",
    context: str | None = None,
) -> str:
    period_scope = next(
        spec[3] for spec in connector.FACT_SPECS if spec[0] == concept
    )
    context_ref = context or (
        "AsOf20260331" if period_scope == "INSTANT" else "From20260101To20260331"
    )
    sign_attr = f' sign="{sign}"' if sign else ""
    return (
        f'<ix:nonFraction name="{concept}" contextRef="{context_ref}" '
        f'format="ixt:numdotdecimal" scale="3" decimals="-3" '
        f'unitRef="{unit}"{sign_attr}>{value}</ix:nonFraction>'
    )


def xbrl_bytes(
    company_code: str = "2317",
    year: str = "2026",
    quarter: str = "1",
    category: str = "Consolidated report",
    unit_measure: str = "iso4217:TWD",
    omit_concept: str | None = None,
    duplicate_conflict: bool = False,
) -> bytes:
    facts = [
        fact_xml(concept, value, sign)
        for concept, (value, sign) in VALUES.items()
        if concept != omit_concept
    ]
    if duplicate_conflict:
        facts.append(
            fact_xml(
                "ifrs-full:CashFlowsFromUsedInOperatingActivities",
                "9,999,999",
                None,
            )
        )
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
    <html xmlns="http://www.w3.org/1999/xhtml"
      xmlns:ifrs-full="https://xbrl.ifrs.org/taxonomy/2025-03-27/ifrs-full"
      xmlns:iso4217="http://www.xbrl.org/2003/iso4217"
      xmlns:link="http://www.xbrl.org/2003/linkbase"
      xmlns:xbrli="http://www.xbrl.org/2003/instance"
      xmlns:xlink="http://www.w3.org/1999/xlink"
      xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
      xmlns:ixt="http://www.xbrl.org/inlineXBRL/transformation/2015-02-26"
      xmlns:tifrs-SCF="http://www.xbrl.org/tifrs/scf/2025-06-30"
      xmlns:tifrs-notes="http://www.xbrl.org/tifrs/notes/2025-06-30">
      <body>
        <div>
          <ix:header>
            <ix:hidden>
              <ix:nonNumeric name="tifrs-notes:CompanyID" contextRef="From20260101To20260331">{company_code}</ix:nonNumeric>
              <ix:nonNumeric name="tifrs-notes:CompanyChineseName" contextRef="From20260101To20260331">鴻海精密工業股份有限公司</ix:nonNumeric>
              <ix:nonNumeric name="tifrs-notes:Year" contextRef="From20260101To20260331">{year}</ix:nonNumeric>
              <ix:nonNumeric name="tifrs-notes:Quarter" contextRef="From20260101To20260331">{quarter}</ix:nonNumeric>
              <ix:nonNumeric name="tifrs-notes:ReportCategory" contextRef="From20260101To20260331">{category}</ix:nonNumeric>
            </ix:hidden>
            <ix:references>
              <link:schemaRef xlink:href="tifrs-ci-cr-2025-06-30.xsd" xlink:type="simple"/>
            </ix:references>
            <ix:resources>
              <xbrli:context id="From20260101To20260331">
                <xbrli:entity><xbrli:identifier scheme="http://www.twse.com.tw">2317</xbrli:identifier></xbrli:entity>
                <xbrli:period><xbrli:startDate>2026-01-01</xbrli:startDate><xbrli:endDate>2026-03-31</xbrli:endDate></xbrli:period>
              </xbrli:context>
              <xbrli:context id="AsOf20260331">
                <xbrli:entity><xbrli:identifier scheme="http://www.twse.com.tw">2317</xbrli:identifier></xbrli:entity>
                <xbrli:period><xbrli:instant>2026-03-31</xbrli:instant></xbrli:period>
              </xbrli:context>
              <xbrli:unit id="TWD"><xbrli:measure>{unit_measure}</xbrli:measure></xbrli:unit>
            </ix:resources>
          </ix:header>
        </div>
        <div>{''.join(facts)}</div>
      </body>
    </html>
    """
    return xml.encode()


def manual_html(mismatch: bool = False) -> bytes:
    operating = "3,217,155" if mismatch else "3,217,154"
    return f"""
    <html><body>
      <h1>合併現金流量表</h1>
      <div>民國115年第1季</div><div>單位：新台幣仟元</div>
      <table>
        <tr><td>營業活動之淨現金流入（流出）</td><td>{operating}</td></tr>
        <tr><td>投資活動之淨現金流入（流出）</td><td>-29,019,834</td></tr>
        <tr><td>籌資活動之淨現金流入（流出）</td><td>-26,010,315</td></tr>
        <tr><td>取得不動產、廠房及設備</td><td>-35,774,345</td></tr>
        <tr><td>折舊費用</td><td>25,883,347</td></tr>
        <tr><td>攤銷費用</td><td>916,754</td></tr>
        <tr><td>本期現金及約當現金增加（減少）數</td><td>-30,122,657</td></tr>
        <tr><td>期末現金及約當現金餘額</td><td>986,317,310</td></tr>
      </table>
    </body></html>
    """.encode()


class FakeFetcher:
    def __init__(
        self,
        xbrl: bytes | None = None,
        manual: bytes | None = None,
        fail_download: bool = False,
    ) -> None:
        self.xbrl = xbrl if xbrl is not None else xbrl_bytes()
        self.manual = manual if manual is not None else manual_html()
        self.fail_download = fail_download
        self.requests: list[connector.HttpRequest] = []

    def __call__(self, request: connector.HttpRequest, timeout: int):
        self.requests.append(request)
        if request.url == connector.DISCOVERY_URL:
            return connector.HttpResult(
                request.url, 200, "text/html", {}, listing_html()
            )
        if "FileDownLoad" in request.url:
            if self.fail_download:
                raise connector.PrimarySourceUnavailable("fixture unavailable")
            return connector.HttpResult(request.url, 200, "", {}, self.xbrl)
        if request.url == connector.MANUAL_URL:
            return connector.HttpResult(
                request.url, 200, "text/html", {}, self.manual
            )
        raise AssertionError(request.url)


class P203B06CashFlowXbrlConnectorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(
            prefix="cash-flow-xbrl-test-", dir=PACKAGE_ROOT / "staging"
        )
        self.root = Path(self.temp.name)
        self.runtime_db = self.root / "runtime.sqlite3"
        self.runtime_db.write_bytes(b"runtime-protected")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def run_connector(self, fetcher: FakeFetcher):
        with patch.object(connector, "read_existing_da", return_value=connector.Decimal("268.0")):
            return connector.run_connector(
                self.root / "run", self.runtime_db, fetcher
            )

    def test_happy_path_creates_eight_observations(self) -> None:
        result = self.run_connector(FakeFetcher())
        candidate = result["candidate"]
        self.assertEqual(candidate["period"]["period_label"], "2026Q1")
        self.assertEqual(candidate["report_scope"], "CONSOLIDATED")
        self.assertEqual(candidate["observation_count"], 8)
        self.assertEqual(candidate["blocked_fact_count"], 0)
        self.assertTrue(
            all(fact["promotion_status"] == "OBSERVATION_ONLY" for fact in candidate["facts"])
        )

    def test_scale_sign_and_twd_normalization(self) -> None:
        result = self.run_connector(FakeFetcher())
        facts = {
            fact["metric_code"]: fact for fact in result["candidate"]["facts"]
        }
        self.assertEqual(
            facts["MOPS_XBRL_CASH_FLOW_OPERATING"]["normalized_value_twd"],
            "3217154000",
        )
        self.assertEqual(
            facts["MOPS_XBRL_PURCHASE_PPE"]["normalized_value_twd"],
            "-35774345000",
        )
        self.assertEqual(
            facts["MOPS_XBRL_CASH_END"]["normalized_value_twd"],
            "986317310000",
        )

    def test_da_comparison_matches_without_promotion(self) -> None:
        result = self.run_connector(FakeFetcher())
        comparison = result["candidate"]["da_comparison"]
        self.assertEqual(
            comparison["official_depreciation_plus_amortisation_100m"],
            "268.00101",
        )
        self.assertEqual(comparison["status"], "SOURCE_MATCH_CONFIRMED")
        self.assertFalse(comparison["promotion_allowed"])
        self.assertEqual(
            result["candidate"]["fcf_boundary"]["status"],
            "FORMULA_NOT_APPROVED",
        )

    def test_discovery_selects_latest_consolidated_report(self) -> None:
        selected = connector.parse_discovery(listing_html())
        self.assertEqual(selected["roc_period"], "115Q1")
        self.assertEqual(selected["fiscal_year"], 2026)
        self.assertIn("report_id=C", selected["download_url"])

    def test_raw_bytes_are_preserved(self) -> None:
        fetcher = FakeFetcher()
        result = self.run_connector(fetcher)
        raw = Path(result["raw_artifacts"]["xbrl"]["local_path"]).read_bytes()
        self.assertEqual(raw, fetcher.xbrl)
        self.assertEqual(
            connector.sha256_bytes(raw),
            result["raw_artifacts"]["xbrl"]["sha256"],
        )

    def test_wrong_company_is_blocked(self) -> None:
        with self.assertRaises(connector.DataValidationError):
            self.run_connector(FakeFetcher(xbrl=xbrl_bytes(company_code="2330")))

    def test_non_consolidated_report_is_blocked(self) -> None:
        with self.assertRaises(connector.DataValidationError):
            self.run_connector(
                FakeFetcher(xbrl=xbrl_bytes(category="Individual report"))
            )

    def test_period_mismatch_is_blocked(self) -> None:
        with self.assertRaises(connector.DataValidationError):
            self.run_connector(FakeFetcher(xbrl=xbrl_bytes(year="2025")))

    def test_non_twd_unit_is_blocked(self) -> None:
        with self.assertRaises(connector.ContractError):
            self.run_connector(
                FakeFetcher(xbrl=xbrl_bytes(unit_measure="iso4217:USD"))
            )

    def test_missing_fact_is_blocked(self) -> None:
        with self.assertRaises(connector.DataValidationError):
            self.run_connector(
                FakeFetcher(
                    xbrl=xbrl_bytes(
                        omit_concept="ifrs-full:AdjustmentsForAmortisationExpense"
                    )
                )
            )

    def test_inconsistent_duplicate_fact_is_blocked(self) -> None:
        with self.assertRaises(connector.DataValidationError):
            self.run_connector(
                FakeFetcher(xbrl=xbrl_bytes(duplicate_conflict=True))
            )

    def test_doctype_or_entity_is_blocked(self) -> None:
        malicious = (
            b'<?xml version="1.0"?><!DOCTYPE html [<!ENTITY xxe SYSTEM "file:///x">]>'
            b"<html/>"
        )
        discovery = connector.parse_discovery(listing_html())
        with self.assertRaises(connector.ContractError):
            connector.parse_inline_xbrl(malicious, discovery)

    def test_manual_page_difference_is_blocked(self) -> None:
        with self.assertRaises(connector.DataValidationError):
            self.run_connector(FakeFetcher(manual=manual_html(mismatch=True)))

    def test_primary_failure_has_no_source_fallback(self) -> None:
        fetcher = FakeFetcher(fail_download=True)
        with self.assertRaises(connector.PrimarySourceUnavailable):
            self.run_connector(fetcher)
        self.assertEqual(len(fetcher.requests), 2)

    def test_runtime_and_formal_files_are_unchanged(self) -> None:
        before = connector.dbcore.sha256_file(self.runtime_db)
        result = self.run_connector(FakeFetcher())
        self.assertEqual(before, connector.dbcore.sha256_file(self.runtime_db))
        self.assertTrue(result["protected_files"]["unchanged"])

    def test_chinese_statuses_and_boundaries_are_explicit(self) -> None:
        result = self.run_connector(FakeFetcher())
        self.assertEqual(result["status_zh"], "通過但有警告")
        self.assertFalse(result["actionable"])
        self.assertIn(
            "FCF_FORMULA_NOT_APPROVED",
            result["candidate"]["warnings"],
        )
        for fact in result["candidate"]["facts"]:
            self.assertEqual(fact["status_zh"], "僅供觀察")
            self.assertIn("未獲准", fact["message_zh"])


if __name__ == "__main__":
    unittest.main()
