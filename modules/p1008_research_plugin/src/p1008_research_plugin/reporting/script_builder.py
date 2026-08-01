"""Media candidates derived exclusively from a validated report candidate."""

from __future__ import annotations

import re

from .report_contracts import ReportCandidate, ShortsDurationValidation


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

    @staticmethod
    def _first_sentence(value: str, limit: int) -> str:
        sentence = re.split(r"(?<=[。！？])", value.strip(), maxsplit=1)[0].strip()
        if len(sentence) <= limit:
            return sentence
        return sentence[:limit].rstrip("，；： ") + "。"

    def longform(self, report: ReportCandidate) -> str:
        report = self._require_report(report)
        section = {item.section_id: item.body_zh for item in report.sections}
        return f"""# 五分鐘研究影片候選稿

## 今日核心問題
{report.primary_investor_question}

## 已驗證的新證據
{section['WHAT_CHANGED']}

## 從營收到投資意義
{section['FINANCIAL_TRANSMISSION']}

{section['EARNINGS_AND_MARGIN_QUALITY']}

## 現金流與估值
{section['CASH_FLOW_AND_DIVIDEND_SAFETY']}

{section['VALUATION_INTERPRETATION']}

## 市場價格如何反應
{section['PRICE_VOLUME_AND_MARKET_PSYCHOLOGY']}

替代解釋：{section['ALTERNATIVE_EXPLANATION']}

反方證據：{section['COUNTEREVIDENCE']}

## 三種受眾視角
{section['THREE_AUDIENCE_LENSES']}

## 下一個驗證點
{section['NEXT_VALIDATION_DATE_AND_EVENT']}

推翻條件：{section['INVALIDATION_CONDITIONS']}

## 畫面合規字卡（不口播）
{section['ACTIONABLE_FALSE_DISCLAIMER']}
""".replace("\r\n", "\n")

    def shorts_75s(self, report: ReportCandidate) -> str:
        report = self._require_report(report)
        section = {item.section_id: item.body_zh for item in report.sections}
        changed = self._first_sentence(section["WHAT_CHANGED"], 45)
        unchanged = self._first_sentence(section["WHAT_DID_NOT_CHANGE"], 30)
        transmission = self._first_sentence(section["FINANCIAL_TRANSMISSION"], 40)
        market = self._first_sentence(section["PRICE_VOLUME_AND_MARKET_PSYCHOLOGY"], 50)
        next_event = self._first_sentence(section["NEXT_VALIDATION_DATE_AND_EVENT"], 35)
        invalidation = self._first_sentence(section["INVALIDATION_CONDITIONS"], 25)
        return f"""# 75秒 Shorts 候選稿

## 0–5秒
今天只回答一題：營收成長，能不能轉成獲利與現金流？

## 5–15秒
{changed}

## 15–35秒
{transmission}{unchanged}

## 35–50秒
{market}

## 50–65秒
估值只做描述，不套用未核准的便宜或昂貴門檻；負自由現金流仍限制支持，需由下一期正式財務資料交叉驗證。

## 65–75秒
{next_event}{invalidation}

## 畫面合規字卡（不口播）
本內容為公開、非個人化研究候選；actionable=false。
""".replace("\r\n", "\n")


class ShortsDurationValidator:
    """Estimate spoken duration with a documented deterministic zh-TW rate."""

    SPOKEN_CHARACTERS_PER_SECOND = 4.2
    _SEGMENT = re.compile(
        r"^## (?P<label>\d+[–-]\d+秒)\s*$\n(?P<body>.*?)(?=^## |\Z)",
        re.MULTILINE | re.DOTALL,
    )
    _SPOKEN_CHARACTER = re.compile(r"[\u3400-\u9fffA-Za-z0-9%]", re.UNICODE)

    @classmethod
    def validate(cls, script: str) -> ShortsDurationValidation:
        segment_counts: dict[str, int] = {}
        segment_seconds: dict[str, float] = {}
        for match in cls._SEGMENT.finditer(script.replace("\r\n", "\n")):
            label = match.group("label")
            body = match.group("body")
            count = len(cls._SPOKEN_CHARACTER.findall(body))
            segment_counts[label] = count
            segment_seconds[label] = round(count / cls.SPOKEN_CHARACTERS_PER_SECOND, 2)

        count = sum(segment_counts.values())
        seconds = round(count / cls.SPOKEN_CHARACTERS_PER_SECOND, 2)
        warnings: list[str] = []
        errors: list[str] = []
        if not segment_counts:
            errors.append("No timed spoken segments were found")
        if seconds > 78:
            errors.append("Estimated spoken duration exceeds 78 seconds")
        elif seconds > 75:
            warnings.append("Estimated duration is within the 76–78 second warning band")
        elif seconds < 60:
            warnings.append("Estimated duration is below the preferred 60-second floor")
        status = "FAIL" if errors else ("PASS_WITH_WARNING" if warnings else "PASS")
        return ShortsDurationValidation(
            speech_rate_assumption="繁體中文口播以每秒4.2個可發音中文字、英文字母或數字估算；Markdown標題與不口播合規字卡排除",
            spoken_characters_per_second=cls.SPOKEN_CHARACTERS_PER_SECOND,
            spoken_character_count=count,
            estimated_spoken_seconds=seconds,
            segment_character_counts=segment_counts,
            segment_estimated_seconds=segment_seconds,
            duration_gate_status=status,
            warnings=warnings,
            errors=errors,
            actionable=False,
        )

    @staticmethod
    def spoken_text(script: str) -> str:
        return "\n".join(
            match.group("body").strip()
            for match in ShortsDurationValidator._SEGMENT.finditer(
                script.replace("\r\n", "\n")
            )
        )
