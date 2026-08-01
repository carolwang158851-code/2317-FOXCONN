"""Media script candidates derived only from a validated report candidate."""

from __future__ import annotations

from .report_contracts import ReportCandidate


class ScriptInputError(TypeError):
    """The script generator was not given a validated ReportCandidate."""


class ScriptBuilder:
    @staticmethod
    def _require_report(report: ReportCandidate) -> ReportCandidate:
        if not isinstance(report, ReportCandidate):
            raise ScriptInputError("scripts may read only a validated ReportCandidate")
        if report.actionable is not False:
            raise ScriptInputError("scripts require actionable=false")
        return report

    def longform(self, report: ReportCandidate) -> str:
        report = self._require_report(report)
        section = {item.section_id: item.body_zh for item in report.sections}
        return f"""# 5–7分鐘長篇影音腳本候選

## 開場：今天真正要回答的問題

{report.primary_investor_question}

## 已驗證的新證據

{section['WHAT_CHANGED']}

這是本次唯一被官方月營收證據直接更新的核心判讀。年增很強，月增卻轉弱，兩者必須同時看，不能只挑較好看的數字。

## 從營收到投資意義

{section['FINANCIAL_TRANSMISSION']}

{section['EARNINGS_AND_MARGIN_QUALITY']}

## 現金流與估值矛盾

{section['CASH_FLOW_AND_DIVIDEND_SAFETY']}

{section['VALUATION_INTERPRETATION']}

## 市場如何解讀——這一段是推論

{section['PRICE_VOLUME_AND_MARKET_PSYCHOLOGY']}

替代解釋是：{section['ALTERNATIVE_EXPLANATION']}

反方證據是：{section['COUNTEREVIDENCE']}

## 公開、非個人化的三種觀察視角

{section['THREE_AUDIENCE_LENSES']}

## 下一個驗證點

{section['NEXT_VALIDATION_DATE_AND_EVENT']}

改變目前觀點的條件：{section['INVALIDATION_CONDITIONS']}

## 結語

現階段不是把高營收直接翻譯成高獲利，而是等待下一季正式資料驗證轉化。{section['ACTIONABLE_FALSE_DISCLAIMER']}
""".replace("\r\n", "\n")

    def shorts_75s(self, report: ReportCandidate) -> str:
        report = self._require_report(report)
        section = {item.section_id: item.body_zh for item in report.sections}
        return f"""# 75秒Shorts腳本候選

## 0–5秒｜投資人痛點
鴻海營收年增超過五成，為什麼現在還不能只看成長就下結論？

## 5–15秒｜目前研究判斷
核心矛盾是營收很強，但獲利與現金流尚未同步驗證；整體論點維持，新資金研究分類仍是WAIT。

## 15–35秒｜一項已驗證財務事實
{section['WHAT_CHANGED']}

## 35–50秒｜市場心理推論與替代解釋
{section['PRICE_VOLUME_AND_MARKET_PSYCHOLOGY']}替代解釋：{section['ALTERNATIVE_EXPLANATION']}

## 50–65秒｜三種公開受眾視角
累積期看成長轉化；退休轉換期看現金流與波動；退休收入期看TTM股利安全。這些不是個人化配置。

## 65–75秒｜下一驗證點
{section['NEXT_VALIDATION_DATE_AND_EVENT']}推翻條件：{section['INVALIDATION_CONDITIONS']}

actionable=false；不構成交易指令。
""".replace("\r\n", "\n")
