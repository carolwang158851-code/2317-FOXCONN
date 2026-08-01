"""Build a MONTHLY_REVENUE report exclusively from validated Phase B1 inputs."""

from __future__ import annotations

from datetime import datetime

from ..analysis.analysis_contracts import AnalysisPacket
from ..phaseb1_common import canonical_json_bytes, sha256_bytes
from ..plugin_module.contracts import ValidatedEvidence
from .report_contracts import EvidenceReference, ReportCandidate, ReportSection


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
        revenue = analysis.financial_trend.revenue
        fcf = analysis.financial_trend.free_cash_flow
        valuation = analysis.valuation_analysis
        activity = analysis.price_and_market_activity
        psychology = analysis.market_psychology
        views = analysis.investor_views
        authority_ids = [
            "AUTH-MASTER-2026Q1",
            "AUTH-PRICE-20260727",
            "AUTH-MARKET-ACTIVITY-20260727",
            "AUTH-CASHFLOW-2026Q1",
        ]

        sections = [
            self._section("REPORT_IDENTITY_AND_CUTOFF", "報告識別與資料截止", f"本報告為MONTHLY_REVENUE deterministic候選；月營收截止2026年6月，市場authority截止{valuation.data_window.split('..')[-1]}，財務截止2026Q1。", []),
            self._section("EXECUTIVE_JUDGMENT", "編輯台判斷", "最重要的問題不是營收是否成長，而是強勁營收能否在2026Q2轉成獲利率與自由現金流。現階段論點維持，但新資金分類為等待驗證。", official_ids + ["AUTH-CASHFLOW-2026Q1"]),
            self._section("WHAT_CHANGED", "本次改變", f"{revenue.value}。這項官方新證據提高營收動能的可信度，但只改變營收判讀。", official_ids),
            self._section("WHAT_DID_NOT_CHANGE", "本次未改變", "本次證據未提供2026Q2毛利率、營益率、EPS或現金流，因此不調升獲利品質、股利安全或整體論點。", official_ids + ["AUTH-MASTER-2026Q1", "AUTH-CASHFLOW-2026Q1"]),
            self._section("FINANCIAL_TRANSMISSION", "財務傳導", "事件到營收已由官方數字驗證；營收到毛利、EPS、現金流及估值的後續鏈結仍未確認。把營收直接等同獲利或AI變現不符合證據。", official_ids),
            self._section("EARNINGS_AND_MARGIN_QUALITY", "獲利與利潤率品質", f"2026Q1毛利率{analysis.financial_trend.gross_margin.value}%、營益率{analysis.financial_trend.operating_margin.value}%、EPS {analysis.financial_trend.eps.value}元；月營收公告不足以證明這些指標已改善。", ["AUTH-MASTER-2026Q1"]),
            self._section("CASH_FLOW_AND_DIVIDEND_SAFETY", "現金流與股利安全", f"2026Q1核心自由現金流為{fcf.value}億元，狀態為WATCH。負的單季FCF使估值支持受限，但不足以單獨證明結構性股利危險，需等待2026Q2與TTM。", ["AUTH-CASHFLOW-2026Q1", "AUTH-MASTER-2026Q1"]),
            self._section("VALUATION_INTERPRETATION", "估值判讀", f"截至{valuation.data_window.split('..')[-1]}收盤價{valuation.current_price}元、P/B {valuation.current_pb}倍；在現有治理窗口的位置為{valuation.governed_historical_pb_position}。估值狀態為{valuation.valuation_status.value}，但此短窗口不代表完整歷史週期。", ["AUTH-PRICE-20260727", "AUTH-MASTER-2026Q1"]),
            self._section("PRICE_VOLUME_AND_MARKET_PSYCHOLOGY", "價格、成交活動與市場心理", f"1／5／20期報酬分別為{activity.return_windows['1D']}、{activity.return_windows['5D']}、{activity.return_windows['20D']}；最新成交量分位{activity.volume_percentile}。{psychology.interpretation}這是推論，成交量不能用來推定法人或主力意圖。", ["AUTH-PRICE-20260727", "AUTH-MARKET-ACTIVITY-20260727", *official_ids]),
            self._section("SUPPORTING_EVIDENCE", "支持證據", "鴻海官方公告與投資人關係月營收頁對2026年6月與上半年累計數字一致；本機authority另提供價格、市場活動、2026Q1財務與現金流基線。", official_ids + authority_ids),
            self._section("ALTERNATIVE_EXPLANATION", "替代解釋", psychology.alternative_explanation, psychology.evidence_basis),
            self._section("COUNTEREVIDENCE", "反方證據", "；".join(psychology.counter_evidence + ["6月營收月減4.38%，與年增強勁並存。"]), official_ids + ["AUTH-PRICE-20260727"]),
            self._section("MISSING_EVIDENCE", "缺失證據", "尚缺2026Q2產品組合、毛利率、營益率、EPS、營運資金與FCF，也缺可治理的benchmark-adjusted return；不得用零或推測補齊。", ["AUTH-MASTER-2026Q1", "AUTH-CASHFLOW-2026Q1"]),
            self._section("NEW_MONEY_VIEW", "新資金觀察", f"研究分類：{views.new_money_view.value}。理由是營收改善已驗證，但估值與現金轉化尚未形成一致支持；WAIT不等同賣出。", official_ids + ["AUTH-PRICE-20260727", "AUTH-CASHFLOW-2026Q1"]),
            self._section("EXISTING_HOLDING_VIEW", "既有持有觀察", f"研究分類：{views.existing_holding_view.value}。單季負FCF與較高P/B要求持續驗證，但目前沒有結構性論點破壞證據。", ["AUTH-CASHFLOW-2026Q1", "AUTH-PRICE-20260727"]),
            self._section("THREE_AUDIENCE_LENSES", "三種公開受眾視角", "；".join(f"{lens.lens_id}：{lens.narrative}" for lens in analysis.audience_lenses), authority_ids + official_ids),
            self._section("INVALIDATION_CONDITIONS", "推翻條件", "若2026Q2獲利率與FCF未隨營收成長改善，需下修目前維持論點；若FCF與利潤率同步改善，則應重新評估WAIT與估值警戒。", official_ids + ["AUTH-CASHFLOW-2026Q1"]),
            self._section("NEXT_VALIDATION_DATE_AND_EVENT", "下一驗證事件", "下一個關鍵驗證點為2026Q2正式財報／法說；屆時核對產品組合、利潤率、EPS、營業現金流、資本支出與TTM自由現金流。", ["AUTH-MASTER-2026Q1", "AUTH-CASHFLOW-2026Q1"]),
            self._section("DATA_LIMITATIONS", "資料限制", "月營收為未經查核的公司公告數字；PB歷史位置只涵蓋現有日價authority；宏觀與媒體觀察資料不提升為事實；本次無網路、模型或外掛呼叫。", official_ids + authority_ids),
            self._section("ACTIONABLE_FALSE_DISCLAIMER", "研究安全邊界", "本候選只提供公開、非個人化研究分類，不蒐集財務身分、不產生買賣、部位、目標價或急迫性指令；actionable=false。", []),
        ]
        return ReportCandidate(
            run_id=analysis.run_id,
            event_type="MONTHLY_REVENUE",
            generated_at_utc=generated_at_utc,
            analysis_packet_sha256=analysis_sha,
            authority_manifest_sha256=analysis.authority_manifest_sha256,
            primary_investor_question="營收高成長能否在下一季轉成獲利與現金流，足以支撐目前估值？",
            thesis_state=analysis.thesis_scorecard.overall_thesis,
            evidence_bound_facts=[item.statement for item in analysis.material_conclusions],
            evidence_references=references,
            sections=sections,
            actionable=False,
        )

    @staticmethod
    def _section(section_id: str, title: str, body: str, evidence_ids: list[str]) -> ReportSection:
        return ReportSection(section_id=section_id, title_zh=title, body_zh=body, evidence_ids=evidence_ids)

    @staticmethod
    def _references(analysis: AnalysisPacket, evidence: ValidatedEvidence) -> list[EvidenceReference]:
        references: list[EvidenceReference] = []
        for item in evidence.evidence:
            references.append(
                EvidenceReference(
                    evidence_id=item.evidence_id,
                    claim=item.summary,
                    source_tier=" + ".join(sorted({locator.source_tier for locator in item.source_locators})),
                    source_date="2026-07-05",
                    source_urls=sorted({locator.locator for locator in item.source_locators}),
                )
            )
        authority_claims = {
            "AUTH-MASTER-2026Q1": "2026Q1獲利、ROE、ROIC、BVPS與股利基線",
            "AUTH-PRICE-20260727": "正式日價與P/B基線",
            "AUTH-MARKET-ACTIVITY-20260727": "TWSE成交量、成交金額與成交筆數基線",
            "AUTH-CASHFLOW-2026Q1": "官方季報現金流與透明公式衍生FCF",
        }
        for evidence_id, claim in authority_claims.items():
            path = {
                "AUTH-MASTER-2026Q1": "data/2317_master_v9.csv",
                "AUTH-PRICE-20260727": "data/2317_daily_price.csv",
                "AUTH-MARKET-ACTIVITY-20260727": "data/2317_daily_market_activity.csv",
                "AUTH-CASHFLOW-2026Q1": "data/2317_cash_flow_authority.csv",
            }[evidence_id]
            references.append(
                EvidenceReference(
                    evidence_id=evidence_id,
                    claim=claim,
                    source_tier="GOVERNED_AUTHORITY_MANIFEST",
                    source_date=analysis.authority_data_cutoffs[path],
                    source_urls=[f"p1008-authority:{path}@{analysis.authority_file_hashes[path]}"],
                )
            )
        return sorted(references, key=lambda item: item.evidence_id)
