"""Build a MONTHLY_REVENUE report exclusively from validated Phase B1 inputs."""

from __future__ import annotations

from datetime import datetime

from ..analysis.analysis_contracts import AnalysisPacket
from ..analysis.numeric_claim_lineage import validate_working_capital_qoq_lineage
from ..phaseb1_common import canonical_json_bytes, sha256_bytes
from ..plugin_module.contracts import ValidatedEvidence
from .report_contracts import EvidenceReference, ReportCandidate, ReportSection


AUTHORITY_PATHS = {
    "AUTH-MASTER-": "data/2317_master_v9.csv",
    "AUTH-PRICE-": "data/2317_daily_price.csv",
    "AUTH-MARKET-ACTIVITY-": "data/2317_daily_market_activity.csv",
    "AUTH-CASHFLOW-": "data/2317_cash_flow_authority.csv",
}


class ReportBuilder:
    CONTRACT_VERSION = "1.0"

    def build(
        self,
        *,
        analysis: AnalysisPacket,
        evidence: ValidatedEvidence,
        generated_at_utc: datetime,
    ) -> ReportCandidate:
        if analysis.event_type == "QUARTERLY_EARNINGS":
            return self._build_quarterly(
                analysis=analysis,
                evidence=evidence,
                generated_at_utc=generated_at_utc,
            )
        analysis_sha = sha256_bytes(
            canonical_json_bytes(analysis.model_dump(mode="json", by_alias=True))
        )
        references = self._references(analysis, evidence)
        official_ids = sorted(evidence.evidence_ids)
        authority_ids = self._authority_ids(analysis)
        master_id = authority_ids["AUTH-MASTER-"]
        price_id = authority_ids["AUTH-PRICE-"]
        activity_id = authority_ids["AUTH-MARKET-ACTIVITY-"]
        cash_id = authority_ids["AUTH-CASHFLOW-"]
        all_authority_ids = [master_id, price_id, activity_id, cash_id]

        revenue = analysis.financial_trend.revenue
        gross_margin = analysis.financial_trend.gross_margin
        operating_margin = analysis.financial_trend.operating_margin
        eps = analysis.financial_trend.eps
        fcf = analysis.financial_trend.free_cash_flow
        valuation = analysis.valuation_analysis
        activity = analysis.price_and_market_activity
        psychology = analysis.market_psychology
        views = analysis.investor_views
        next_event = analysis.material_conclusions[0].next_validation_event
        invalidations = "；".join(
            conclusion.invalidation_condition
            for conclusion in analysis.material_conclusions
        )
        recent_returns = activity.recent_price_context.return_windows
        event_reaction = activity.event_window_reaction
        event_text = (
            "；".join(f"{key}={value}" for key, value in event_reaction.return_windows.items())
            if event_reaction.return_windows
            else "正式事件窗口資料不足，維持INSUFFICIENT_DATA"
        )

        sections = [
            self._section("REPORT_IDENTITY_AND_CUTOFF", "報告識別與資料截止", f"本報告為MONTHLY_REVENUE deterministic候選；營收期間{revenue.period}，市場authority截止{valuation.data_window.split('..')[-1]}，財務截止{fcf.period}。", "FACT", []),
            self._section("EXECUTIVE_JUDGMENT", "編輯台判斷", f"最重要的問題是{revenue.period}營收動能能否在{next_event}轉成獲利率與自由現金流。現階段論點維持，但新資金分類為等待驗證。", "INFERENCE", official_ids + [cash_id]),
            self._section("WHAT_CHANGED", "本次改變", f"{revenue.value}。這項官方新證據提高營收動能的可信度，但只改變營收判讀。", "FACT", official_ids),
            self._section("WHAT_DID_NOT_CHANGE", "本次未改變", f"本次證據未提供{next_event}所需的毛利率、營益率、EPS或現金流，因此不調升獲利品質、股利安全或整體論點。", "MIXED", official_ids + [master_id, cash_id]),
            self._section("FINANCIAL_TRANSMISSION", "財務傳導", "事件到營收已由官方數字驗證；營收到毛利、EPS、現金流及估值的後續鏈結仍未確認。把營收直接等同獲利或AI變現不符合證據。", "MIXED", official_ids),
            self._section("EARNINGS_AND_MARGIN_QUALITY", "獲利與利潤率品質", f"{gross_margin.period}毛利率{gross_margin.value}%、營益率{operating_margin.value}%、EPS {eps.value}元；月營收公告不足以證明這些指標已改善。", "FACT", [master_id]),
            self._section("CASH_FLOW_AND_DIVIDEND_SAFETY", "現金流與股利安全", f"{fcf.period}核心自由現金流為{fcf.value}億元，狀態為{fcf.status.value}。負的單季FCF使估值支持受限，但不足以單獨證明結構性股利危險，需等待{next_event}。", "MIXED", [cash_id, master_id]),
            self._section("VALUATION_INTERPRETATION", "估值判讀", f"截至{valuation.data_window.split('..')[-1]}收盤價{valuation.current_price}元、P/B {valuation.current_pb}倍；在現有治理窗口的位置為{valuation.governed_historical_pb_position}。估值分類為{valuation.valuation_status.value}，因尚無Owner核准門檻，不輸出便宜、昂貴或極端分類。", "MIXED", [price_id, master_id]),
            self._section("PRICE_VOLUME_AND_MARKET_PSYCHOLOGY", "價格、成交活動與市場心理", f"近期1／5／20期報酬為{recent_returns.get('1D')}、{recent_returns.get('5D')}、{recent_returns.get('20D')}；事件窗口為{event_text}；最新成交量分位{activity.volume_percentile}。{psychology.interpretation}這是推論，成交量不能用來推定法人或主力意圖。", "MIXED", [price_id, activity_id, *official_ids]),
            self._section("SUPPORTING_EVIDENCE", "支持證據", f"官方公司來源交叉核對{revenue.period}營收；本機authority另提供價格、市場活動、{gross_margin.period}財務與{fcf.period}現金流基線。", "FACT", official_ids + all_authority_ids),
            self._section("ALTERNATIVE_EXPLANATION", "替代解釋", psychology.alternative_explanation, "INFERENCE", psychology.evidence_basis),
            self._section("COUNTEREVIDENCE", "反方證據", "；".join(psychology.counter_evidence + ["官方月營收同時呈現月減與年增動能。"]), "MIXED", official_ids + [price_id]),
            self._section("MISSING_EVIDENCE", "缺失證據", f"尚缺{next_event}的產品組合、毛利率、營益率、EPS、營運資金與FCF，也缺受治理benchmark-adjusted return；不得用零或推測補齊。", "FACT", [master_id, cash_id]),
            self._section("NEW_MONEY_VIEW", "新資金觀察", f"研究分類：{views.new_money_view.value}。營收改善已驗證，但估值只可描述、現金轉化尚未形成一致支持；WAIT不等同賣出。", "INFERENCE", official_ids + [price_id, cash_id]),
            self._section("EXISTING_HOLDING_VIEW", "既有持有觀察", f"研究分類：{views.existing_holding_view.value}。單季負FCF要求持續驗證，但目前沒有結構性論點破壞證據。", "INFERENCE", [cash_id, price_id]),
            self._section("THREE_AUDIENCE_LENSES", "三種公開受眾視角", "；".join(f"{lens.lens_id}：{lens.narrative}" for lens in analysis.audience_lenses), "INFERENCE", all_authority_ids + official_ids),
            self._section("INVALIDATION_CONDITIONS", "推翻條件", invalidations, "INFERENCE", official_ids + [cash_id, price_id]),
            self._section("NEXT_VALIDATION_DATE_AND_EVENT", "下一驗證事件", f"下一個關鍵驗證點為{next_event}；屆時核對產品組合、利潤率、EPS、營業現金流、資本支出與TTM自由現金流。", "FACT", [master_id, cash_id]),
            self._section("DATA_LIMITATIONS", "資料限制", "月營收為公司公告數字；P/B歷史位置只涵蓋現有日價authority且沒有核准分類門檻；事件窗口沒有受治理benchmark；本次無網路、模型或外掛呼叫。", "FACT", official_ids + all_authority_ids),
            self._section("ACTIONABLE_FALSE_DISCLAIMER", "研究安全邊界", "本候選只提供公開、非個人化研究分類，不蒐集財務身分、不產生買賣、部位、目標價或急迫性指令；actionable=false。", "COMPLIANCE", []),
        ]
        return ReportCandidate(
            run_id=analysis.run_id,
            event_type="MONTHLY_REVENUE",
            generated_at_utc=generated_at_utc,
            analysis_packet_sha256=analysis_sha,
            authority_manifest_sha256=analysis.authority_manifest_sha256,
            primary_investor_question=f"{revenue.period}營收動能能否在下一個正式財務驗證點轉成獲利與現金流？",
            thesis_state=analysis.thesis_scorecard.overall_thesis,
            evidence_bound_facts=[item.statement for item in analysis.material_conclusions],
            evidence_references=references,
            sections=sections,
            actionable=False,
        )

    def _build_quarterly(
        self,
        *,
        analysis: AnalysisPacket,
        evidence: ValidatedEvidence,
        generated_at_utc: datetime,
    ) -> ReportCandidate:
        q = analysis.quarterly_earnings
        if q is None:
            raise ValueError("QUARTERLY_EARNINGS report requires quarterly analysis")
        analysis_sha = sha256_bytes(
            canonical_json_bytes(analysis.model_dump(mode="json", by_alias=True))
        )
        references = self._references(analysis, evidence)
        official_ids = sorted(evidence.evidence_ids)
        authority_ids = self._authority_ids(analysis)
        master_id = authority_ids["AUTH-MASTER-"]
        price_id = authority_ids["AUTH-PRICE-"]
        activity_id = authority_ids["AUTH-MARKET-ACTIVITY-"]
        cash_id = authority_ids["AUTH-CASHFLOW-"]
        returns = analysis.price_and_market_activity.recent_price_context.return_windows
        price_cutoff = analysis.valuation_analysis.data_window.split("..")[-1]
        invalidations = "；".join(item.invalidation_condition for item in analysis.material_conclusions)
        next_events = "；".join(dict.fromkeys(item.next_validation_event for item in analysis.material_conclusions))
        analytics = q.enterprise_value_analytics
        working_capital_qoq = validate_working_capital_qoq_lineage(
            analytics["workingCapitalQoqIncrease"],
            expected_source_ids=official_ids,
            expected_source_sha256=q.source_hash,
            expected_source_page=q.source_pages["balanceSheet"],
        )
        working_capital_inputs = working_capital_qoq["inputs"]
        valuation = q.valuation_scenarios
        price_label = valuation["price"]["readerLabel"]
        valuation_context_label = (
            "財報公布前估值脈絡"
            if valuation["valuationTimeBasis"]["valuationState"] == "PRE_EVENT_VALUATION_CONTEXT"
            else "財報公布後報告截止日估值脈絡"
        )
        forward = "；".join(
            f"研究敏感度 H2年增{item['h2Yoy']}：FY26 EPS {item['fy26Eps']}元、以{price_label}計算P/E {item['peAtCurrentPrice']}倍"
            for item in valuation["forwardPeScenarios"]
        )
        pe_matrix = "；".join(
            f"SCENARIO EPS {item['eps']}元×{item['multiple']}倍={item['referenceValue']}元"
            for item in valuation["peMatrix"]
        )
        pb_scenarios = "；".join(
            f"SCENARIO {item['multiple']}倍={item['referenceValue']}元"
            for item in valuation["pbScenarios"]
        )
        yield_scenarios = "；".join(
            f"SCENARIO 殖利率{item['yield']}={item['referenceValue']}元"
            for item in valuation["dividendYieldScenarios"]
        )
        sections = [
            self._section("REPORT_IDENTITY_AND_CUTOFF", "報告識別與權威截止", f"本報告以鴻海官方FY2026 Q2結果與既有受治理authority為證據；市場資料截止{price_cutoff}。Q2現金流採同口徑2026H1減2026Q1推導，與官方累計FCF路徑僅差{analytics['q2StandaloneFcfRoundingDifferenceMillionTwd']}百萬元，位於揭露整數四捨五入容許值內。", "FACT", official_ids + [master_id, price_id, activity_id, cash_id]),
            self._section("EXECUTIVE_SUMMARY", "營運槓桿轉強，現金轉化仍是企業價值斷點", f"本季真正證明的是規模成長開始轉為更快的營業利益增長：營收年增{q.revenue.yoy}，營業利益年增{analytics['operatingProfitYoyPct']}%。尚未證明的是AI專屬資本效率與正常化FCF；推導Q2 CFO為{analytics['q2StandaloneCfoMillionTwd']}百萬元、FCF為{analytics['q2StandaloneFcfMillionTwd']}百萬元。核心論點存續，但估值安全性沒有改善，後續關鍵是現金回收與資本效率。", "MIXED", official_ids + [master_id, price_id, cash_id]),
            self._section("GOVERNANCE_COMMITMENT_EXECUTION", "3+3治理承諾與價值傳導", "官方受治理來源確認3+3涵蓋電動車、數位健康、機器人及人工智慧、半導體、次世代通訊；第三個3或智慧平台目前未在本次受治理官方來源中確認。人工智慧已連到營收與成長指引，但六個支柱尚無任何一項完整連到ROIC與FCF，因此策略存在不等於企業價值創造完成。", "MIXED", official_ids + [master_id, cash_id]),
            self._section("Q2_FINANCIAL_SUMMARY", "本季真正改變了什麼", f"官方直接揭露Q2營收{q.revenue.value}百萬元、毛利{analytics['grossProfitMillionTwd']}百萬元、營業利益{analytics['operatingProfitMillionTwd']}百萬元、稅前利益{analytics['pretaxProfitMillionTwd']}百萬元、所得稅費用{analytics['incomeTaxExpenseMillionTwd']}百萬元、歸屬母公司淨利{q.attributable_profit.value}百萬元及EPS {q.eps.value}元。營業利益增幅高於營收，現金卻轉負，形成本季核心矛盾。", "FACT", official_ids),
            self._section("GROWTH_QUALITY", "成長品質與產品組合", f"官方毛利年增{analytics['grossProfitYoyPct']}%，落後營收成長{analytics['grossProfitLagPct']}個百分點；官方營業利益年增{analytics['operatingProfitYoyPct']}%。Cloud & Networking占營收{analytics['cloudNetworkingRevenueSharePct']}%，但AI特定營收占比未揭露。這支持需求規模與公司整體獲利改善，不支持把全部改善歸因於AI。", "MIXED", official_ids),
            self._section("OPERATING_LEVERAGE", "營運槓桿與費用吸收", f"營業利益年增{analytics['operatingProfitYoyPct']}%，比營收快{analytics['operatingLeverageSpreadPct']}個百分點。毛利以下營業費用淨額代理值由毛利減營業利益推導，本季為{analytics['operatingExpenseProxyMillionTwd']}百萬元（597.30億元）、年增{analytics['operatingExpenseProxyYoyPct']}%；占營收比重八季由約3.2%降至2.365%。這與規模吸收及費用紀律一致，但代理值不是公司直接揭露的營業費用科目，更不是營業成本，也不能證明永久結構效率。", "MIXED", official_ids),
            self._section("MARGIN_QUALITY", "利潤率與八季脈絡", f"毛利率{q.gross_margin.value}%、營益率{q.operating_margin.value}%、淨利率{q.net_margin.value}%。自2024Q2至2026Q2，毛利率下降30個基點、營益率提高87個基點；八季背離顯示改善主要發生在毛利以下，支持成本吸收，不支持毛利護城河擴張。", "MIXED", official_ids + [master_id]),
            self._section("EARNINGS_TO_CASH_QUALITY", "Q2獲利轉現金品質", f"Q2 CFO由2026H1減2026Q1推導為{analytics['q2StandaloneCfoMillionTwd']}百萬元，Capex為{analytics['q2StandaloneCapexMillionTwd']}百萬元，FCF為{analytics['q2StandaloneFcfMillionTwd']}百萬元；兩條FCF路徑差{analytics['q2StandaloneFcfRoundingDifferenceMillionTwd']}百萬元。CFO／歸母淨利警示代理值為{analytics['cashConversion']}，只顯示嚴重獲利—現金背離；因合併CFO與歸屬母公司淨利範圍不同，不是同口徑標準現金轉化率。", "MIXED", official_ids + [cash_id]),
            self._section("WORKING_CAPITAL_CAPITAL_REQUIREMENT", "營運資金與現金循環", f"Q2應收帳款{int(working_capital_inputs['q2AccountsReceivableMillionTwd']):,}百萬元、存貨{int(working_capital_inputs['q2InventoryMillionTwd']):,}百萬元，兩者較Q1增加會吸收現金；應付帳款{int(working_capital_inputs['q2AccountsPayableMillionTwd']):,}百萬元較Q1增加，則是供應商融資與部分現金抵銷，不是現金吸收。三項淨額仍增加{int(working_capital_qoq['value']):,}百萬元，與成長期資金占用相容。同時，現金循環週期由2025Q2的48天、2026Q1的44天降至42天，表示週轉效率未同步惡化；但這不等於現金回收已完成。", "MIXED", working_capital_qoq["sourceEvidenceIds"]),
            self._section("CAPITAL_EFFICIENCY", "資本效率與ROIC", f"Q2推導Capex占營收{analytics['capexIntensityRevenuePct']}%、占營業利益{analytics['capexToOperatingProfitPct']}%，只有Q1與Q2兩期可比，維持歷史有限，不稱長期趨勢。受治理ROIC自2024Q3至2026Q1依序為10.51%、13.16%、7.91%、10.66%、11.77%、14.41%、12.57%；FY2026 Q2不是0或下降，而是缺標準化NOPAT與可比平均投入資本的待驗證缺口。", "FACT", official_ids + [master_id]),
            self._section("ROE_DUPONT_INTERPRETATION", "ROE、股東權益與每股淨值複利", f"官方可比H1 ROE由2025H1的5.48%升至2026H1的6.21%，增加0.73個百分點；2025全年受治理ROE基線11.3%僅作全年脈絡，H1不年化。受治理BVPS由2024Q3的115.16元至2026Q1的{valuation['governedBvps']['value']}元中期淨增加，但2025Q2曾降至105.14元，之後回升至117.18元、126.96元及127.12元；下降原因待驗證。這支持股東資本累積與使用效率方向正面，但完整股東複利仍須同時考慮BVPS變化與已分配股利。ROE約等於淨利率乘以資產周轉再乘以財務槓桿，目前只能做部分杜邦分析。", "MIXED", official_ids + [master_id]),
            self._section("PROFIT_PASS_THROUGH", "營業利益至淨利傳導", f"公式怎麼看？官方營業利益{analytics['operatingProfitMillionTwd']}百萬元，加上非營業淨收入63百萬元，形成稅前利益{analytics['pretaxProfitMillionTwd']}百萬元；扣除所得稅費用{analytics['incomeTaxExpenseMillionTwd']}百萬元後，再經非控制權益歸屬形成母公司淨利{q.attributable_profit.value}百萬元。稅前與稅額已補齊，非控制權益細節仍有限。", "MIXED", official_ids),
            self._section("AI_SERVER_CLOUD_NETWORKING", "AI成長品質", "AI是營收驅動且3Q26前瞻成長獲官方管理層指引支持。AI與公司整體營業利益改善方向一致，可列為部分證實／高信心推論；但AI特定營業利益金額與AI特定利潤率仍未揭露，AI的ROIC、現金轉化與FCF貢獻均未證實。", "MIXED", official_ids),
            self._section("GOVERNANCE_TARGET_VS_ACTUAL", "治理承諾與執行力", "管理承諾經策略與執行傳到營收、毛利與營業利益後，必須由三條互相驗證但不互為單一路徑的分支檢查。企業資本效率分支以營業利益、NOPAT與ROIC回答投入營運資本是否有效創造報酬；股東資本效率分支以稅前利益、淨利、ROE與BVPS回答股東資本是否有效使用；現金生成分支以淨利、非現金項目、營運資金、CFO、Capex與FCF回答帳面獲利是否變成自由現金。三者共同支持股利能力、股東回報與退休現金流安全，但Q2 ROIC及現金回收仍待驗。", "MIXED", official_ids + [master_id, cash_id]),
            self._section("VALUATION", "估值", f"{price_label}為{valuation['price']['value']}元（{valuation['price']['date']}），以最新直接揭露BVPS {valuation['governedBvps']['value']}元（{valuation['governedBvps']['period']}）計算的P/B為{valuation['pb']['value']}倍。過去十二個月EPS由2025Q3 4.15元、鴻海官方2025Q4 basic EPS 3.23元、2026Q1 3.56元及官方2026Q2 4.27元組成，合計{valuation['ttmEps']['value']}元，對應P/E約{valuation['ttmPe']['value']}倍。2025H2 EPS為{valuation['priorH2Eps']['value']}元；FY2026研究情境EPS為{', '.join(item['fy26Eps'] for item in valuation['forwardPeScenarios'])}元。以估算相容加權平均股數及TTM營收推導的P/S為{valuation['ps']['value']}倍。以上均屬{valuation_context_label}，無核准的估值安全邊際門檻，不形成交易規則。", "MIXED", [master_id, price_id, *official_ids]),
            self._section("HOLDING_THESIS", "核心持有論點", "既有持有研究分類維持：營收、毛利、公司整體營業利益與EPS支持營運能力，但Q2推導CFO與FCF為負，資本效率仍待驗。論點存續只表示尚未被推翻，不等於估值安全性改善，也不等於退休現金流安全性已證實。", "INFERENCE", official_ids + [master_id, cash_id]),
            self._section("NEW_MONEY_VALUATION_CONTEXT", "新資金估值脈絡", f"{price_label}對推導TTM EPS的P/E為{valuation['ttmPe']['value']}倍，P/S為{valuation['ps']['value']}倍；FY2026情境只作敏感度。P/B的基本面支持取決於ROE、BVPS複利、ROIC與FCF能否共同改善，不形成便宜、昂貴或買賣判定。", "INFERENCE", official_ids + [master_id, price_id]),
            self._section("GREEN_SIGNALS", "3+3戰略落地訊號", "正式治理來源支持3+3六項支柱；AI基礎設施需求、共同開發及量產整合支持人工智慧支柱已進入營收階段。其餘支柱的客戶／訂單、營收、營業利益、ROIC與FCF多未有本期可量化證據，第三個3亦未確認。", "MIXED", official_ids + [master_id]),
            self._section("NON_GREEN_DEEP_REVIEW", "治理執行與未通過項目", "毛利率下降、營益率上升與營業費用代理值占比下降，支持規模吸收但仍非唯一因果結論。Q2 CFO與FCF雙負；同時CCC由48天降至42天，現有證據較支持高速擴張造成的營運資金占用加上資本支出，而非已證實的週轉效率惡化。現金回收、Q2 ROIC與完整杜邦分析仍待驗。", "MIXED", official_ids + [master_id, cash_id]),
            self._section("COUNTEREVIDENCE_LIMITATIONS", "反方證據與限制", f"毛利率季變動{q.gross_margin.qoq}、年變動{q.gross_margin.yoy}，上半年自由現金流為負；Q2結果簡報的財務資訊未完全經會計師查核或核閱；Apple／iPhone、匯率、關稅與政策影響未量化；市場資料截至{price_cutoff}，時點屬{valuation_context_label}，但尚無完整基準調整事件窗口。", "FACT", official_ids + [price_id, activity_id, cash_id]),
            self._section("INVALIDATION_CONDITIONS", "推翻條件", "若公司更正Q2結果、後續AI出貨未依指引轉化、營益率改善無法維持，或自由現金流持續惡化，必須重新檢查既有持有論點。完整事件窗口若顯示相反市場反應，也需更新估值脈絡。", "INFERENCE", official_ids + [master_id, price_id, cash_id]),
            self._section("NEXT_VALIDATION_DATE_AND_EVENT", "未來1至4季驗證重點", "優先順序一：FY2026 Q3毛利率、營益率與營業費用代理值，確認營運槓桿耐久度。二：應收、存貨、應付與CCC，確認營運資金回收。三：TTM NOPAT、平均投入資本、ROIC與增量ROIC。四：可比ROE、直接BVPS與完整杜邦分析，確認股東資本複利品質。五：全年CFO、Capex、FCF與股利政策。另需補足完整事件後價格與成交量窗口。", "FACT", official_ids + [master_id, price_id, activity_id, cash_id]),
            self._section("RETIREMENT_CASHFLOW_IMPLICATION", "治理、企業價值與退休任務總結", "Q2證明的不是只有營收成長，而是營業利益增速更快、費用代理占比下降，管理層規模與整合策略在營運端已有可信財務證據。企業價值創造目前只完成營收至營業利益的前半段，尚未完成資本效率與現金回收驗證。Q2沒有證明AI專屬利潤率、Q2 ROIC、正向FCF或股利能力升級；3+3六支柱已核對，AI走到營收與公司整體獲利方向，其專屬ROIC與現金仍未知。官方H1 ROE由5.48%升至6.21%；治理BVPS由2024Q3至2026Q1中期淨增加，但2025Q2曾明顯下降且原因待驗證。兩項證據支持股東資本累積與使用效率方向正面；完整股東複利仍須納入分配股利，完整杜邦分析與Q2 BVPS也尚未齊備。Q2 CFO與FCF為負，CCC反而改善，較符合成長驅動的營運資金占用加上Capex；現金回收仍是主問題。若AI出貨成長卻伴隨毛利率與營益率同步惡化、營運資金長期快於營收、ROE或增量ROIC下降，或FCF持續未跟上獲利，現有解讀即失效。未來一至四季須驗證營益率耐久度、營運資金回收、ROIC、ROE／BVPS與全年FCF。最終分項判斷：核心論點存續；估值安全性未上修；退休現金流安全尚未證實；股利能力不因負FCF而上修；股東資本累積與效率方向正面但仍待Q2資料。", "INFERENCE", official_ids + [master_id, cash_id]),
            self._section("ACTIONABLE_FALSE_DISCLAIMER", "研究安全邊界", "本候選只提供公開、非個人化研究分類，不產生買賣、部位、價格參考指令或急迫性指令；actionable=false，publication=false，停在Owner Review。", "COMPLIANCE", []),
        ]
        return ReportCandidate(
            run_id=analysis.run_id,
            event_type="QUARTERLY_EARNINGS",
            generated_at_utc=generated_at_utc,
            analysis_packet_sha256=analysis_sha,
            authority_manifest_sha256=analysis.authority_manifest_sha256,
            primary_investor_question="這次事件，是否改變鴻海作為退休現金流＋長期複利核心資產的安全性？",
            thesis_state=analysis.thesis_scorecard.overall_thesis,
            evidence_bound_facts=[item.statement for item in analysis.material_conclusions],
            evidence_references=references,
            sections=sections,
            actionable=False,
        )

    @staticmethod
    def _section(section_id: str, title: str, body: str, epistemic_class: str, evidence_ids: list[str]) -> ReportSection:
        return ReportSection(section_id=section_id, title_zh=title, body_zh=body, epistemic_class=epistemic_class, evidence_ids=evidence_ids)

    @staticmethod
    def _authority_ids(analysis: AnalysisPacket) -> dict[str, str]:
        result: dict[str, str] = {}
        for prefix in AUTHORITY_PATHS:
            matches = [item for item in analysis.source_evidence_ids if item.startswith(prefix)]
            if len(matches) != 1:
                raise ValueError(f"analysis does not contain exactly one authority identity for {prefix}")
            result[prefix] = matches[0]
        return result

    @staticmethod
    def _references(analysis: AnalysisPacket, evidence: ValidatedEvidence) -> list[EvidenceReference]:
        references: list[EvidenceReference] = []
        evidence_dates = {
            item.evidence_id: packet.as_of_date.isoformat()
            for packet in evidence.packets
            for item in packet.evidence
        }
        for item in evidence.evidence:
            references.append(
                EvidenceReference(
                    evidence_id=item.evidence_id,
                    claim=item.summary,
                    source_tier=" + ".join(sorted({locator.source_tier for locator in item.source_locators})),
                    source_date=evidence_dates[item.evidence_id],
                    source_urls=sorted({locator.locator for locator in item.source_locators}),
                )
            )
        claims = {
            "AUTH-MASTER-": "獲利、ROE、ROIC、BVPS與股利基線",
            "AUTH-PRICE-": "正式日價與P/B基線",
            "AUTH-MARKET-ACTIVITY-": "TWSE成交量、成交金額與成交筆數基線",
            "AUTH-CASHFLOW-": "官方季報現金流與透明公式衍生FCF",
        }
        authority_ids = ReportBuilder._authority_ids(analysis)
        for prefix, evidence_id in authority_ids.items():
            path = AUTHORITY_PATHS[prefix]
            references.append(
                EvidenceReference(
                    evidence_id=evidence_id,
                    claim=f"{analysis.authority_data_cutoffs[path]} {claims[prefix]}",
                    source_tier="GOVERNED_AUTHORITY_MANIFEST",
                    source_date=analysis.authority_data_cutoffs[path],
                    source_urls=[f"p1008-authority:{path}@{analysis.authority_file_hashes[path]}"],
                )
            )
        return sorted(references, key=lambda item: item.evidence_id)
