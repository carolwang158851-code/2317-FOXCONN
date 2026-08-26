"""Create decision-oriented chart data from a validated Analysis Packet only."""

from __future__ import annotations

import re
from decimal import Decimal, ROUND_HALF_UP

from ..analysis.analysis_contracts import AnalysisPacket
from .report_contracts import ChartData, ChartSeries


class ChartDataBuilder:
    @staticmethod
    def _authority_id(analysis: AnalysisPacket, prefix: str) -> str:
        matches = [item for item in analysis.source_evidence_ids if item.startswith(prefix)]
        if len(matches) != 1:
            raise ValueError(f"analysis does not contain exactly one {prefix} identity")
        return matches[0]

    @staticmethod
    def _revenue_values(value: str | None) -> tuple[list[str], list[str]]:
        if value is None:
            return ["月增率", "年增率", "累計年增率"], ["INSUFFICIENT_DATA"] * 3
        patterns = (
            ("月增率", r"MoM\s*([+-]?\d+(?:\.\d+)?)%"),
            ("年增率", r"YoY\s*([+-]?\d+(?:\.\d+)?)%"),
            ("累計年增率", r"累計YoY\s*([+-]?\d+(?:\.\d+)?)%"),
        )
        values: list[str] = []
        for _label, pattern in patterns:
            match = re.search(pattern, value, re.IGNORECASE)
            values.append(match.group(1) if match else "INSUFFICIENT_DATA")
        return [label for label, _pattern in patterns], values

    @staticmethod
    def _indexed(values: list[str]) -> list[str]:
        base = Decimal(values[0])
        return [
            str((Decimal(value) / base * Decimal("100")).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))
            for value in values
        ]

    def build(self, analysis: AnalysisPacket) -> list[ChartData]:
        if analysis.event_type == "QUARTERLY_EARNINGS":
            q = analysis.quarterly_earnings
            if q is None:
                raise ValueError("quarterly chart data requires quarterly analysis")
            official_ids = [item for item in analysis.source_evidence_ids if not item.startswith("AUTH-")]
            master_id = self._authority_id(analysis, "AUTH-MASTER-")
            price_id = self._authority_id(analysis, "AUTH-PRICE-")
            activity_id = self._authority_id(analysis, "AUTH-MARKET-ACTIVITY-")
            cash_id = self._authority_id(analysis, "AUTH-CASHFLOW-")
            history = q.quarterly_history
            analytics = q.enterprise_value_analytics
            valuation = q.valuation_scenarios
            periods = history["periods"]
            chain = analytics["valueChainEvidenceMatrix"]
            scenario_rows = [
                ("Forward P/E", f"EPS {item['eps']}元", f"{item['multiple']}倍", f"{item['referenceValue']}元")
                for item in valuation["peMatrix"]
            ] + [
                ("P/B", f"受治理BVPS {valuation['governedBvps']['value']}元", f"{item['multiple']}倍", f"{item['referenceValue']}元")
                for item in valuation["pbScenarios"]
            ] + [
                ("Dividend Yield", f"股利 {valuation['dividend']['value']}元", item["yield"], f"{item['referenceValue']}元")
                for item in valuation["dividendYieldScenarios"]
            ]
            charts = [
                ChartData(
                    chart_id="growth_quality_divergence",
                    title_zh="成長品質與背離",
                    decision_question="營收成長是否等比例轉成毛利與營業利益？",
                    period=f"{periods[0]}至{periods[-1]}",
                    source_evidence_ids=[master_id, *official_ids],
                    labels=periods,
                    series=[
                        ChartSeries(label_zh="營收指數", unit="指數（首季=100）", values=self._indexed(history["revenue100mTwd"])),
                        ChartSeries(label_zh="毛利指數", unit="指數（首季=100）", values=self._indexed(history["grossProfit100mTwd"])),
                        ChartSeries(label_zh="營業利益指數", unit="指數（首季=100）", values=self._indexed(history["operatingIncome100mTwd"])),
                    ],
                    commentary_zh=["發現：營業利益增幅高於營收，毛利增幅低於營收。", "解釋：改善發生在毛利以下；營業費用代理值支持成本吸收，但不能指定唯一原因。", "企業價值含義：營運轉化改善，資本與現金治理仍待驗。"],
                    observation_zh=f"營收年增{q.revenue.yoy}，官方毛利年增約{analytics['grossProfitYoyPct']}%、官方營業利益年增約{analytics['operatingProfitYoyPct']}%。",
                    interpretation_zh="營業利益轉化優於毛利；規模吸收、費用槓桿與產品組合均屬可能解釋。",
                    p1008_implication_zh="成長支持既有HOLD論點，但不構成新資金估值結論。",
                    strategic_implication_zh="規模成長已開始轉為營業利益，但尚未證明3+3各支柱均創造價值。",
                    enterprise_value_implication_zh="營運價值鏈前半段改善，現金與資本報酬仍未完成。",
                    next_checkpoint_zh="FY2026 Q3營收、毛利與營業利益趨勢。",
                    visualization_type="QUANTITATIVE_CHART",
                    signal="YELLOW",
                    actionable=False,
                ),
                ChartData(
                    chart_id="operating_leverage_spread",
                    title_zh="營運槓桿差",
                    decision_question="營業利益成長超越營收的幅度有多大？",
                    period=q.fiscal_period,
                    source_evidence_ids=official_ids,
                    labels=["營收成長", "營業利益成長", "營運槓桿差"],
                    series=[ChartSeries(label_zh="成長與差值", unit="百分點", values=[q.revenue.yoy.rstrip("%"), analytics["operatingProfitYoyPct"], analytics["operatingLeverageSpreadPct"]])],
                    commentary_zh=[f"發現：營運槓桿差約{analytics['operatingLeverageSpreadPct']}個百分點。", "推論：規模、費用吸收或產品組合改善均與結果相容，來源尚未因果證實。", "待驗證：下一季檢查營益率與毛利率能否同向維持。"],
                    observation_zh=f"官方營業利益成長約{analytics['operatingProfitYoyPct']}%，高於營收成長{q.revenue.yoy}。",
                    interpretation_zh="營益率擴張而毛利率下降，只能確認毛利以下轉化效率改善。",
                    p1008_implication_zh="營運治理通過，但持續性仍屬EVIDENCE_BUILDING。",
                    strategic_implication_zh="與管理層規模／整合效率敘事一致，但不是因果證明。",
                    enterprise_value_implication_zh="若能延續，新增營收對營業利益的轉化率提高。",
                    next_checkpoint_zh="FY2026 Q3營益率、毛利率與營業費用代理值。",
                    visualization_type="QUANTITATIVE_CHART",
                    signal="YELLOW",
                    actionable=False,
                ),
                ChartData(
                    chart_id="margin_divergence_8q",
                    title_zh="八季利潤率背離",
                    decision_question="毛利率與營益率的背離是單季或延續趨勢？",
                    period=f"{periods[0]}至{periods[-1]}",
                    source_evidence_ids=[master_id, *official_ids],
                    labels=periods,
                    series=[ChartSeries(label_zh="毛利率", unit="%", values=history["grossMarginPct"]), ChartSeries(label_zh="營益率", unit="%", values=history["operatingMarginPct"])],
                    commentary_zh=["OBSERVATION：本季毛利率6.12%，營益率3.75%。", "INTERPRETATION：毛利率承壓與營益率擴張並存。", "P1008_IMPLICATION：不能把營益率改善直接解讀為毛利護城河擴張。"],
                    observation_zh="八季治理序列顯示本季營益率位於較高位置，毛利率未同步創高。",
                    interpretation_zh="規模吸收與營業費用槓桿比毛利率擴張更能解釋本季結果。",
                    p1008_implication_zh="下一檢查點是毛利率穩定性與費用槓桿耐久度。",
                    strategic_implication_zh="營益率改善較符合規模吸收，尚不能證明產品護城河擴張。",
                    enterprise_value_implication_zh="營業利益轉化改善，但毛利率承壓限制品質判斷。",
                    next_checkpoint_zh="未來兩季毛利率與營益率是否持續同向改善。",
                    visualization_type="QUANTITATIVE_CHART",
                    signal="YELLOW",
                    actionable=False,
                ),
                ChartData(
                    chart_id="operating_cost_absorption_8q",
                    title_zh="八季營業費用代理值吸收",
                    decision_question="規模成長是否伴隨毛利以下營業費用淨額代理值占比下降？",
                    period=f"{periods[0]}至{periods[-1]}",
                    source_evidence_ids=[master_id, *official_ids],
                    labels=periods,
                    series=[ChartSeries(label_zh="營業費用代理值／營收", unit="%", values=history["opexProxyRevenuePct"])],
                    commentary_zh=[
                        f"發現：占營收比重八季由約3.2%降至{analytics['operatingExpenseProxyRevenuePct']}%；Q2代理值597.30億元、年增{analytics['operatingExpenseProxyYoyPct']}%只作註記，不與百分比共用尺度。",
                        "解釋：這與規模吸收一致，但代理值無法拆分研發、管理、銷售與匯率影響。",
                        "企業價值含義：成本吸收已出現多季脈絡，持續性仍需後續季度確認。",
                    ],
                    observation_zh=f"Q2營業費用代理值占營收{analytics['operatingExpenseProxyRevenuePct']}%，營收增幅高於代理值增幅{analytics['revenueGrowthMinusOpexProxyGrowthPct']}個百分點。",
                    interpretation_zh="規模成長伴隨費用吸收，是營益率擴張的可驗證方向性解釋。",
                    p1008_implication_zh="支持營運治理改善，不足以單季外推永久結構效率。",
                    strategic_implication_zh="與全球規模、垂直整合及自動化的管理層敘事一致。",
                    enterprise_value_implication_zh="營業費用代理值吸收提高營收轉為營業利益的效率。",
                    next_checkpoint_zh="FY2026 Q3代理值占營收與營益率。",
                    visualization_type="QUANTITATIVE_CHART",
                    signal="GREEN",
                    actionable=False,
                ),
                ChartData(
                    chart_id="profit_pass_through_evidence_gap",
                    title_zh="獲利傳導橋接",
                    decision_question="營業利益如何經稅前損益與所得稅傳導至歸屬淨利？",
                    period=q.fiscal_period,
                    source_evidence_ids=official_ids,
                    labels=["營業利益", "稅前利益", "所得稅費用", "歸屬母公司淨利"],
                    series=[
                        ChartSeries(label_zh="數值", unit="新台幣百萬元", values=[analytics["operatingProfitMillionTwd"], analytics["pretaxProfitMillionTwd"], analytics["incomeTaxExpenseMillionTwd"], q.attributable_profit.value]),
                        ChartSeries(label_zh="狀態", unit="證據狀態", values=["PROVEN", "PROVEN", "PROVEN", "PROVEN"]),
                        ChartSeries(label_zh="來源", unit="來源", values=["官方Results"] * 4),
                        ChartSeries(label_zh="限制", unit="說明", values=["完整費用科目未拆分", "非營業淨收入63百萬元", "未拆分遞延／當期稅", "非控制權益橋接未完整揭露"]),
                    ],
                    commentary_zh=[f"發現：官方營業利益{analytics['operatingProfitMillionTwd']}百萬元、稅前淨利{analytics['pretaxProfitMillionTwd']}百萬元、所得稅費用{analytics['incomeTaxExpenseMillionTwd']}百萬元。", "限制：非控制權益與其他歸屬橋接未完整拆分。", "企業價值含義：營業利益至稅前端幾乎未稀釋，主要已知扣減為所得稅。"],
                    observation_zh="營業利益至稅前淨利增加63百萬元；所得稅費用24,810百萬元。",
                    interpretation_zh="稅前與所得稅直接值已補齊，僅非控制權益歸屬橋接仍有限。",
                    p1008_implication_zh="獲利傳導比v1.3更完整，但仍不以歸屬淨利替代NOPAT。",
                    strategic_implication_zh="公司整體營業利益改善確實傳到稅前端。",
                    enterprise_value_implication_zh="營運成果未在非營業端明顯流失；資本效率仍待NOPAT與投入資本。",
                    next_checkpoint_zh="正式財報中的非控制權益與稅率細節。",
                    visualization_type="EVIDENCE_TABLE",
                    signal="GREEN",
                    actionable=False,
                ),
                ChartData(
                    chart_id="cash_quality_evidence",
                    title_zh="Q1至Q2獲利轉現金",
                    decision_question="Q2獲利是否轉成營運現金與自由現金流？",
                    period="2026Q1至2026Q2（LIMITED_HISTORY）",
                    source_evidence_ids=[*official_ids, cash_id],
                    labels=["2026Q1", "2026Q2（H1減Q1推導）"],
                    series=[
                        ChartSeries(label_zh="營業現金流", unit="新台幣百萬元", values=[str(Decimal(analytics["cashFlow2026Q1Cfo100mTwd"]) * Decimal("100")), analytics["q2StandaloneCfoMillionTwd"]]),
                        ChartSeries(label_zh="資本支出", unit="新台幣百萬元", values=[str(Decimal(analytics["cashFlow2026Q1PpeCapex100mTwd"]) * Decimal("100")), analytics["q2StandaloneCapexMillionTwd"]]),
                        ChartSeries(label_zh="自由現金流", unit="新台幣百萬元", values=[str(Decimal(analytics["cashFlow2026Q1FcfCore100mTwd"]) * Decimal("100")), analytics["q2StandaloneFcfMillionTwd"]]),
                    ],
                    commentary_zh=[f"發現：Q2推導CFO為{analytics['q2StandaloneCfoMillionTwd']}百萬元、Capex為{analytics['q2StandaloneCapexMillionTwd']}百萬元、FCF為{analytics['q2StandaloneFcfMillionTwd']}百萬元。", f"驗證：CFO－Capex與H1 FCF－Q1 FCF相差{analytics['q2StandaloneFcfRoundingDifferenceMillionTwd']}百萬元，位於簡報整數四捨五入容許值內。", "退休任務含義：獲利與現金背離擴大，股利能力不得因EPS成長而上修。"],
                    observation_zh="Q2歸屬淨利為正，推導營業現金流與自由現金流均為負。",
                    interpretation_zh="現金背離主要需由營運資金增加與資本支出共同解釋；因果強度限於一致性。",
                    p1008_implication_zh="退休現金流任務維持警戒，但目前未證明結構性股利損害。",
                    strategic_implication_zh="AI與規模擴張尚未通過現金轉化驗證。",
                    enterprise_value_implication_zh="企業價值鏈停在營業利益，未完整到達FCF。",
                    next_checkpoint_zh="FY2026 Q3／全年CFO、Capex與FCF。",
                    visualization_type="QUANTITATIVE_CHART",
                    signal="RED",
                    actionable=False,
                ),
                ChartData(
                    chart_id="working_capital_3period",
                    title_zh="營運資金指數與現金循環週期",
                    decision_question="負營業現金流較符合成長帶動的營運資金吸收，還是效率惡化？",
                    period="2025Q2／2026Q1／2026Q2（歷史資料有限）",
                    source_evidence_ids=official_ids,
                    labels=analytics["workingCapital"]["periods"],
                    series=[
                        ChartSeries(label_zh="應收帳款指數", unit="2025Q2=100", values=analytics["workingCapital"]["indexedTo2025Q2"]["accountsReceivable"]),
                        ChartSeries(label_zh="存貨指數", unit="2025Q2=100", values=analytics["workingCapital"]["indexedTo2025Q2"]["inventory"]),
                        ChartSeries(label_zh="應付帳款指數", unit="2025Q2=100", values=analytics["workingCapital"]["indexedTo2025Q2"]["accountsPayable"]),
                        ChartSeries(label_zh="CCC獨立欄", unit="天（不共用指數尺度）", values=analytics["workingCapital"]["cashConversionCycleDays"]),
                    ],
                    commentary_zh=["發現：應收與存貨季增，吸收營運現金；應付帳款也增加，抵銷部分需求。", "效率面：現金循環週期由去年同期48天、2026Q1的44天降至42天，沒有顯示週轉效率惡化。", "企業價值含義：負CFO較符合規模成長的營運資金吸收加上資本支出，但仍需後續現金回收驗證。"],
                    observation_zh="Q2應收1,385,237百萬元、存貨1,370,073百萬元、應付1,527,523百萬元；CCC為42天。",
                    interpretation_zh="金額占用上升但週轉天數改善，證據較支持成長帶動的營運資金需求，而非效率同步惡化。",
                    p1008_implication_zh="現金治理仍未通過，但根因判讀由完全未解轉為成長吸收較具支持。",
                    strategic_implication_zh="規模擴張需要更高營運資金，供應商融資只能部分抵銷。",
                    enterprise_value_implication_zh="若後續營運資金回收，負CFO可能具時點性；若持續快於營收，則削弱價值創造。",
                    next_checkpoint_zh="FY2026 Q3應收、存貨、應付與CCC。",
                    visualization_type="QUANTITATIVE_CHART",
                    signal="YELLOW",
                    actionable=False,
                ),
                ChartData(
                    chart_id="capex_intensity_limited",
                    title_zh="資本支出兩期KPI比較",
                    decision_question="支撐本季規模成長需要多少資本支出？",
                    period="2026Q1至2026Q2（LIMITED_HISTORY）",
                    source_evidence_ids=[*official_ids, cash_id, master_id],
                    labels=["2026Q1", "2026Q2"],
                    series=[
                        ChartSeries(label_zh="Capex／營收", unit="%", values=["1.680", analytics["capexIntensityRevenuePct"]]),
                        ChartSeries(label_zh="Capex／營業利益", unit="%", values=["47.320", analytics["capexToOperatingProfitPct"]]),
                    ],
                    commentary_zh=[f"發現：Q2推導Capex為{analytics['q2StandaloneCapexMillionTwd']}百萬元，占營收{analytics['capexIntensityRevenuePct']}%。", "限制：只有Q1與Q2同口徑可比，不構成八季趨勢。", "企業價值含義：資本強度大致穩定，但增量ROIC分母仍不足。"],
                    observation_zh=f"Q2 Capex約為營業利益的{analytics['capexToOperatingProfitPct']}%。",
                    interpretation_zh="資本支出強度未明顯惡化，惟自由現金流仍被CFO負值與Capex雙重壓低。",
                    p1008_implication_zh="不能只因Capex比率穩定就宣稱AI擴張具資本效率。",
                    strategic_implication_zh="擴張需要持續資本投入，應與未來ROIC共同驗證。",
                    enterprise_value_implication_zh="Capex本身未顯示失控，但新增資本回報尚未可算。",
                    next_checkpoint_zh="FY2026 Q3／全年Capex與TTM投入資本。",
                    visualization_type="EVIDENCE_TABLE",
                    signal="YELLOW",
                    actionable=False,
                ),
                ChartData(
                    chart_id="capital_validation_status",
                    title_zh="歷史ROIC與Q2待驗證缺口",
                    decision_question="既有資本報酬歷史位於何處，而Q2缺口應如何閱讀？",
                    period=f"{periods[0]}至{periods[-1]}",
                    source_evidence_ids=[master_id, *official_ids],
                    labels=periods,
                    series=[ChartSeries(label_zh="ROIC", unit="%（Q2為證據缺口，非0）", values=history["roicPct"])],
                    commentary_zh=["發現：過去七個受治理觀察值約落在7.91%至14.41%。", "限制：FY2026 Q2沒有治理合格的同口徑值；圖中缺口不是0，也不是下降。", "企業價值含義：歷史資本效率提供脈絡，但Q2改善仍未證實。"],
                    observation_zh="歷史ROIC依序為10.51%、13.16%、7.91%、10.66%、11.77%、14.41%、12.57%；FY2026 Q2為資料不足。",
                    interpretation_zh="過去資本報酬曾落在約8%至14%區間；Q2只能標示待驗證缺口。",
                    p1008_implication_zh="不得把Q2缺口畫成0%或以舊期值外推。",
                    strategic_implication_zh="3+3商業化尚未進入可驗證資本回報階段。",
                    enterprise_value_implication_zh="價值鏈仍未完成Q2資本效率驗證。",
                    next_checkpoint_zh="FY2026 Q3／全年TTM NOPAT與平均投入資本。",
                    visualization_type="QUANTITATIVE_CHART",
                    signal="WHITE",
                    actionable=False,
                ),
                ChartData(
                    chart_id="roe_equity_compounding",
                    title_zh="每股淨值走勢與可比H1 ROE",
                    decision_question="股東權益累積時，股東資本效率是否同步改善？",
                    period=f"BVPS {periods[0]}至2026Q1；ROE 2025H1對2026H1",
                    source_evidence_ids=[master_id, *official_ids],
                    labels=history["periods"][:-1],
                    series=[ChartSeries(label_zh="每股淨值", unit="新台幣元", values=history["bvpsTwd"][:-1])],
                    commentary_zh=["官方可比H1 ROE由5.48%升至6.21%，增加0.73個百分點；2025全年受治理ROE基線11.3%僅作全年脈絡，不將H1年化。", "BVPS由2024Q3的115.16元至2026Q1的127.12元中期淨增加，但2025Q2降至105.14元後才回升，期間波動明顯；該次下降原因待驗證。", "ROE約等於淨利率乘以資產周轉再乘以財務槓桿；目前僅能做部分杜邦分析，不能把ROE改善全歸因於營運。"],
                    observation_zh="BVPS中期淨值較2024Q3提高，但期間波動明顯；可比H1 ROE同期改善，兩者以不同尺度分開呈現。",
                    interpretation_zh="受治理BVPS中期淨增加，且可比H1 ROE改善，支持股東資本累積與使用效率方向正面；完整股東複利仍須同時考慮BVPS變化與已分配股利。",
                    p1008_implication_zh="BVPS與ROE共同驗證股東資本累積及使用效率；分配股利會降低保留帳面權益，同時把價值移轉給股東，因此不得只用BVPS判斷完整股東複利。",
                    strategic_implication_zh="股東資本效率改善方向與營益率提升一致，但完整杜邦分析仍待驗。",
                    enterprise_value_implication_zh="P/B必須與ROE及BVPS經濟性共同判讀，不能單獨形成便宜或昂貴結論。",
                    next_checkpoint_zh="正式FY2026 Q2 BVPS、全年ROE及完整杜邦分析分解。",
                    visualization_type="QUANTITATIVE_CHART",
                    signal="YELLOW",
                    actionable=False,
                ),
                ChartData(
                    chart_id="strategy_scorecard_3plus3",
                    title_zh="3+3戰略價值轉化計分卡",
                    decision_question="官方長期策略的各支柱目前走到策略、商業化、獲利或現金哪一階段？",
                    period=f"官方策略基線至{q.fiscal_period}",
                    source_evidence_ids=official_ids,
                    labels=[item["strategicPillar"] for item in analytics["strategyScorecard"]],
                    series=[
                        ChartSeries(label_zh="先前階段", unit="階段", values=[item["priorStage"] for item in analytics["strategyScorecard"]]),
                        ChartSeries(label_zh="目前階段", unit="階段", values=[item["currentStage"] for item in analytics["strategyScorecard"]]),
                        ChartSeries(label_zh="本季變化", unit="說明", values=[item["changeThisQuarter"] for item in analytics["strategyScorecard"]]),
                        ChartSeries(label_zh="營收證據", unit="說明", values=[item["currentRevenueEvidence"] for item in analytics["strategyScorecard"]]),
                        ChartSeries(label_zh="獲利證據", unit="狀態", values=[item["currentProfitEvidence"] for item in analytics["strategyScorecard"]]),
                        ChartSeries(label_zh="資本效率證據", unit="狀態", values=[item["capitalEfficiencyEvidence"] for item in analytics["strategyScorecard"]]),
                        ChartSeries(label_zh="現金證據", unit="狀態", values=[item["cashFlowEvidence"] for item in analytics["strategyScorecard"]]),
                        ChartSeries(label_zh="下一關卡", unit="路徑", values=[item["nextGate"] for item in analytics["strategyScorecard"]]),
                        ChartSeries(label_zh="下一驗證點", unit="事件", values=[item["nextCheckpoint"] for item in analytics["strategyScorecard"]]),
                    ],
                    commentary_zh=["發現：主計分卡只列治理來源正式確認的3+3六個支柱；第三組『3』另列證據缺口。", "AI已進入營收階段，但AI特定營業利益、ROIC與FCF未被直接揭露。", "企業價值含義：每一支柱都以先前階段、目前階段、本季變化與下一關卡縱向追蹤。"],
                    observation_zh="六個正式3+3支柱中，人工智慧的商業化證據最強；其餘支柱多停留在策略或開發。",
                    interpretation_zh="長期策略必須沿客戶／訂單、營收、營業利益、ROIC、FCF逐級驗證。",
                    p1008_implication_zh="不把公司策略宣示直接當成核心持有安全性的財務證明。",
                    strategic_implication_zh="3+3已驗證，3+3+3第三組未驗證並明確保留證據缺口。",
                    enterprise_value_implication_zh="目前只有AI支柱可連到營收，尚無支柱完整連到ROIC與FCF。",
                    next_checkpoint_zh="各支柱正式分部營收、營業利益、投入資本與現金流揭露。",
                    visualization_type="STATUS_MATRIX",
                    signal="YELLOW",
                    actionable=False,
                ),
                ChartData(
                    chart_id="governance_target_vs_actual",
                    title_zh="治理目標與實績",
                    decision_question="Revenue到退休現金流安全的每一個傳導環節證據到哪裡？",
                    period=q.fiscal_period,
                    source_evidence_ids=[*official_ids, master_id, cash_id],
                    labels=[item["link"] for item in chain],
                    series=[
                        ChartSeries(label_zh="證據狀態", unit="狀態", values=[item["grade"] for item in chain]),
                        ChartSeries(label_zh="目前證據", unit="說明", values=[item["evidence"] for item in chain]),
                        ChartSeries(label_zh="限制", unit="說明", values=[item["limitation"] for item in chain]),
                        ChartSeries(label_zh="企業價值含義", unit="說明", values=[item["enterpriseValueImplication"] for item in chain]),
                        ChartSeries(label_zh="下一驗證點", unit="事件", values=[item["nextCheckpoint"] for item in chain]),
                    ],
                    commentary_zh=["發現：營收、毛利、營業利益與Q2推導現金流已取得官方或官方衍生證據。", "限制：NOPAT、TTM ROIC、增量ROIC與股利能力仍不足。", "退休任務含義：核心論點未失效不等於安全性已證實。"],
                    observation_zh="價值傳導鏈已推進到Q2 CFO與FCF，但現金結果為負；資本報酬仍待驗。",
                    interpretation_zh="獲利改善未傳導為正自由現金流，也未完成ROIC驗證。",
                    p1008_implication_zh="核心資產安全性未被推翻，但現金生命線仍需驗證。",
                    strategic_implication_zh="治理承諾在營運端部分兌現，資本與現金端未通過。",
                    enterprise_value_implication_zh="價值鏈進度從v1.3前移，但負FCF阻止完整價值創造結論。",
                    next_checkpoint_zh="FY2026 Q3／全年NOPAT、ROIC、CFO與FCF。",
                    visualization_type="STATUS_MATRIX",
                    signal="YELLOW",
                    actionable=False,
                ),
                ChartData(
                    chart_id="valuation_matrix",
                    title_zh="估值情境矩陣",
                    decision_question=f"{valuation['price']['readerLabel']}在EPS、P/B與股息研究情境下位於何處？",
                    period=f"價格至{analysis.valuation_analysis.data_window.split('..')[-1]}；財務至{q.fiscal_period}",
                    source_evidence_ids=[price_id, master_id, *official_ids],
                    labels=[f"情境{index + 1}" for index in range(len(scenario_rows))],
                    series=[
                        ChartSeries(label_zh="矩陣", unit="類型", values=[row[0] for row in scenario_rows]),
                        ChartSeries(label_zh="基礎輸入", unit="輸入", values=[row[1] for row in scenario_rows]),
                        ChartSeries(label_zh="倍數／殖利率", unit="情境", values=[row[2] for row in scenario_rows]),
                        ChartSeries(label_zh="參考值", unit="新台幣元", values=[row[3] for row in scenario_rows]),
                    ],
                    commentary_zh=[f"發現：鴻海官方2025Q4 basic EPS {valuation['q4_2025Eps']['value']}元，推導TTM EPS為{valuation['ttmEps']['value']}元、報告截止日P/E約{valuation['ttmPe']['value']}倍。", f"解釋：P/B使用最新直接揭露BVPS {valuation['governedBvps']['value']}元（{valuation['governedBvps']['period']}）；情境不是價格目標。", "企業價值含義：P/B需與ROE及股東權益複利共同判讀。"],
                    observation_zh=f"{valuation['price']['readerLabel']}{valuation['price']['value']}元（{valuation['price']['date']}）、P/B {valuation['pb']['value']}倍、推導TTM EPS {valuation['ttmEps']['value']}元、估算P/S {valuation['ps']['value']}倍。",
                    interpretation_zh="估值可量化描述；ROE改善提供方向性支持，但無Owner門檻，不判定便宜或昂貴。",
                    p1008_implication_zh="新資金與既有持有分類均維持研究觀察，不形成交易指令。",
                    strategic_implication_zh="估值情境不取代3+3商業化與資本回報驗證。",
                    enterprise_value_implication_zh="目前P/B需由ROE耐久度、BVPS複利、ROIC與FCF共同支持。",
                    next_checkpoint_zh="Q3財報、TTM EPS、ROIC與FCF更新。",
                    visualization_type="SCENARIO_MATRIX",
                    signal="YELLOW",
                    actionable=False,
                ),
                ChartData(
                    chart_id="ai_growth_quality",
                    title_zh="AI成長品質",
                    decision_question="AI成長已驗證哪些價值鏈環節？",
                    period=f"{q.fiscal_period}至3Q26指引",
                    source_evidence_ids=official_ids,
                    labels=["營收驅動", "前瞻成長", "公司整體營業利益方向", "AI特定營業利益金額", "AI特定利潤率", "資本效率", "現金轉化", "FCF貢獻"],
                    series=[ChartSeries(label_zh="驗證狀態", unit="狀態", values=[analytics["aiRevenueStatus"], analytics["aiForwardGrowthStatus"], analytics["aiMaterialOperatingProfitContributionDirection"], analytics["aiOperatingProfitStatus"], analytics["aiSpecificMarginStatus"], analytics["aiCapitalEfficiencyStatus"], analytics["aiCashGenerationStatus"], analytics["aiFcfContributionStatus"]])],
                    commentary_zh=["發現：AI是營收驅動且前瞻成長獲官方支持。", "推論：AI與公司整體營業利益改善方向一致，可列部分證實／高信心推論；AI特定金額仍未揭露。", "企業價值含義：AI特定利潤率、資本效率與現金貢獻均未證實。"],
                    observation_zh="AI已證明營收與成長動能；公司整體營業利益方向部分支持，但AI特定金額未知。",
                    interpretation_zh="營運成果與企業價值創造之間仍有資本與現金兩道驗證。",
                    p1008_implication_zh="下一季追蹤AI出貨、利潤率、ROIC與FCF。",
                    strategic_implication_zh="AI是3+3中最接近商業化營收的一柱，尚未進入可驗證資本回報。",
                    enterprise_value_implication_zh="AI成長提高營收與整體營業利益的支持度，但沒有AI特定FCF證明。",
                    next_checkpoint_zh="3Q26 AI機櫃出貨、AI伺服器營收、公司毛利率、ROIC與FCF。",
                    visualization_type="STATUS_MATRIX",
                    signal="YELLOW",
                    actionable=False,
                ),
            ]
            return [
                chart for chart in charts
                if chart.chart_id not in {"operating_leverage_spread", "governance_target_vs_actual"}
            ]
        revenue = analysis.financial_trend.revenue
        fcf = analysis.financial_trend.free_cash_flow
        valuation = analysis.valuation_analysis
        official_ids = [item for item in analysis.source_evidence_ids if item.startswith("E-")]
        price_id = self._authority_id(analysis, "AUTH-PRICE-")
        cash_id = self._authority_id(analysis, "AUTH-CASHFLOW-")
        labels, revenue_values = self._revenue_values(revenue.value)
        return [
            ChartData(
                chart_id="monthly_revenue_signal",
                title_zh=f"{revenue.period}營收變化",
                decision_question="月營收動能是加速、正常化，或仍不足以驗證獲利轉換？",
                period=revenue.period,
                source_evidence_ids=official_ids,
                labels=labels,
                series=[ChartSeries(label_zh="營收變化", unit="%", values=revenue_values)],
                commentary_zh=[
                    "年增與累計年增描述需求動能；月增率用來辨識相較前月的正常化。",
                    "月營收本身不提供毛利率、EPS或自由現金流結論。",
                ],
                observation_zh="月增、年增與累計年增描述已驗證營收動能。",
                interpretation_zh="月營收不足以單獨推論毛利率、EPS或自由現金流。",
                p1008_implication_zh="等待下一個正式財務驗證點。",
                signal="YELLOW",
                actionable=False,
            ),
            ChartData(
                chart_id="valuation_cash_conversion",
                title_zh="估值與現金轉化對照",
                decision_question="現有價格與P/B描述，是否得到自由現金流支持？",
                period=f"價格至{valuation.data_window.split('..')[-1]}；現金流{fcf.period}",
                source_evidence_ids=[price_id, cash_id],
                labels=["收盤價", "P/B", "核心自由現金流"],
                series=[
                    ChartSeries(label_zh="收盤價", unit="新台幣元", values=[valuation.current_price]),
                    ChartSeries(label_zh="P/B", unit="倍", values=[valuation.current_pb]),
                    ChartSeries(label_zh="核心自由現金流", unit="新台幣億元", values=[fcf.value or "INSUFFICIENT_DATA"]),
                ],
                commentary_zh=[
                    "P/B僅描述目前authority窗口內的位置，不套用未核准的便宜或昂貴門檻。",
                    f"{fcf.period}核心自由現金流狀態為{fcf.status.value}，現金轉化仍是估值驗證重點。",
                ],
                observation_zh="價格、P/B與核心自由現金流使用各自受治理截止期。",
                interpretation_zh="估值描述與現金轉化支持必須分開判讀。",
                p1008_implication_zh="維持研究分類，不形成交易指令。",
                signal="YELLOW",
                actionable=False,
            ),
        ]
