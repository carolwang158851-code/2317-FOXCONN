"""Build a MONTHLY_REVENUE report exclusively from validated Phase B1 inputs."""

from __future__ import annotations

from datetime import datetime

from ..analysis.analysis_contracts import AnalysisPacket
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
