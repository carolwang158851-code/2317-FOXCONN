"""Media candidates derived exclusively from a validated report candidate."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from .report_contracts import ReportCandidate, ShortsDurationValidation


class ScriptInputError(TypeError):
    """The script generator was not given a validated ReportCandidate."""


class ScriptBuilder:
    _REVENUE = re.compile(
        r"(?P<period>\d{4})年(?P<month>\d{1,2})月營收新台幣"
        r"(?P<amount>[\d,]+)百萬元；MoM (?P<mom>[+-]?\d+(?:\.\d+)?)%；"
        r"YoY (?P<yoy>[+-]?\d+(?:\.\d+)?)%"
    )
    _FCF = re.compile(
        r"(?P<period>\d{4}Q[1-4])核心自由現金流為"
        r"(?P<value>[+-]?\d+(?:\.\d+)?)億元"
    )
    _EVENT_T1 = re.compile(r"T-1_TO_T\+1=(?P<value>[+-]?\d+(?:\.\d+)?)%")
    _EVENT_T5 = re.compile(r"T-1_TO_T\+5=(?P<value>[+-]?\d+(?:\.\d+)?)%")
    _VALUATION = re.compile(
        r"截至(?P<date>\d{4}-\d{2}-\d{2})收盤價(?P<price>\d+(?:\.\d+)?)元、"
        r"P/B (?P<pb>\d+(?:\.\d+)?)倍"
    )
    _RESEARCH_CLASS = re.compile(r"研究分類：(?P<value>WAIT|HOLD)")
    _NEXT_EVENT = re.compile(r"下一個關鍵驗證點為(?P<event>[^；。]+)")
    _QUARTER = re.compile(r"\d{4}Q[1-4]")

    @staticmethod
    def _require_report(report: ReportCandidate) -> ReportCandidate:
        if not isinstance(report, ReportCandidate):
            raise ScriptInputError("scripts may read only a validated ReportCandidate")
        if report.actionable is not False:
            raise ScriptInputError("scripts require actionable=false")
        return report

    @staticmethod
    def _match(pattern: re.Pattern[str], value: str, field: str) -> re.Match[str]:
        match = pattern.search(value)
        if match is None:
            raise ScriptInputError(f"validated report is missing structured Shorts field: {field}")
        return match

    @staticmethod
    def _spoken_integer(value: int) -> str:
        digits = "零一二三四五六七八九"
        if value < 10:
            return digits[value]
        if value < 100:
            tens, ones = divmod(value, 10)
            prefix = "十" if tens == 1 else digits[tens] + "十"
            return prefix if ones == 0 else prefix + digits[ones]
        return "".join(digits[int(char)] for char in str(value))

    @classmethod
    def _spoken_decimal(cls, raw: str) -> str:
        try:
            value = Decimal(raw.replace(",", ""))
        except InvalidOperation as exc:
            raise ScriptInputError(f"invalid governed numeric value: {raw}") from exc
        normalized = format(abs(value), "f")
        integer, dot, fraction = normalized.partition(".")
        spoken = cls._spoken_integer(int(integer))
        if dot and fraction:
            digits = "零一二三四五六七八九"
            spoken += "點" + "".join(digits[int(char)] for char in fraction)
        return spoken

    @classmethod
    def _spoken_change(cls, raw: str, *, positive: str, negative: str) -> str:
        value = Decimal(raw)
        direction = positive if value > 0 else negative if value < 0 else "持平"
        return f"{direction}百分之{cls._spoken_decimal(raw)}"

    @staticmethod
    def _quarter_zh(value: str) -> str:
        match = re.fullmatch(r"(?P<year>\d{4})Q(?P<quarter>[1-4])", value)
        if match is None:
            return value
        quarters = {"1": "第一季", "2": "第二季", "3": "第三季", "4": "第四季"}
        return f"{match.group('year')}年{quarters[match.group('quarter')]}"

    @classmethod
    def _next_event_zh(cls, value: str) -> str:
        value = re.sub(
            r"(?P<period>\d{4}Q[1-4])",
            lambda match: cls._quarter_zh(match.group("period")),
            value,
        )
        return value.replace("／", "或").replace("（日期待官方公告）", "，日期待官方公告")

    @staticmethod
    def _date_zh(value: str) -> str:
        year, month, day = value.split("-")
        return f"{year}年{int(month)}月{int(day)}日"

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
        revenue = self._match(self._REVENUE, section["WHAT_CHANGED"], "monthly revenue")
        fcf = self._match(self._FCF, section["CASH_FLOW_AND_DIVIDEND_SAFETY"], "free cash flow")
        valuation = self._match(self._VALUATION, section["VALUATION_INTERPRETATION"], "valuation")
        next_event = self._match(self._NEXT_EVENT, section["NEXT_VALIDATION_DATE_AND_EVENT"], "next event")
        next_period = self._match(self._QUARTER, next_event.group("event"), "next validation period")
        wait = self._match(self._RESEARCH_CLASS, section["NEW_MONEY_VIEW"], "WAIT classification")
        hold = self._match(self._RESEARCH_CLASS, section["EXISTING_HOLDING_VIEW"], "HOLD classification")

        yoy = self._spoken_change(revenue.group("yoy"), positive="年增", negative="年減")
        mom = self._spoken_change(revenue.group("mom"), positive="月增", negative="月減")
        fcf_value = Decimal(fcf.group("value"))
        fcf_spoken = (
            f"負{format(abs(fcf_value), 'f')}億元"
            if fcf_value < 0
            else f"{format(fcf_value, 'f')}億元"
        )
        event_t1 = self._EVENT_T1.search(section["PRICE_VOLUME_AND_MARKET_PSYCHOLOGY"])
        event_t5 = self._EVENT_T5.search(section["PRICE_VOLUME_AND_MARKET_PSYCHOLOGY"])
        if event_t1 and event_t5:
            event_reaction = (
                f"公告後一個交易日{self._spoken_change(event_t1.group('value'), positive='上漲', negative='下跌')}，"
                f"五個交易日後{self._spoken_change(event_t5.group('value'), positive='上漲', negative='下跌')}；"
                "沒有受治理基準，不能推論超額報酬。"
            )
        else:
            event_reaction = "事件窗口交易日資料不足，暫不判讀公告後價格反應。"

        return f"""# 75秒 Shorts 候選稿

## 0–5秒
今天只回答一題：營收成長，能不能轉成獲利與現金流？

## 5–15秒
{revenue.group('period')}年{int(revenue.group('month'))}月官方營收為新台幣{revenue.group('amount')}百萬元，{yoy}，{mom}。

## 15–35秒
公告只驗證營收；尚未提供{self._quarter_zh(next_period.group(0))}毛利率、每股盈餘與現金流。{self._quarter_zh(fcf.group('period'))}核心自由現金流為{fcf_spoken}，獲利與現金轉化仍待驗證。

## 35–50秒
{event_reaction}

## 50–65秒
截至{self._date_zh(valuation.group('date'))}，收盤價{valuation.group('price')}元、股價淨值比{valuation.group('pb')}倍；估值只做描述，不套用未核准門檻。

## 65–75秒
下一個驗證事件是{self._next_event_zh(next_event.group('event'))}。新資金研究分類為{wait.group('value')}，既有持有研究分類為{hold.group('value')}；若官方更正營收，撤回本次結論。

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
    _REQUIRED_SEGMENTS = ("0–5秒", "5–15秒", "15–35秒", "35–50秒", "50–65秒", "65–75秒")
    _FORBIDDEN_TERMINAL = re.compile(r"(?:所|核|結|為|與|及|的)。(?:\s|$)")
    _RAW_TECHNICAL_CODE = re.compile(
        r"(?:T-1_TO_T\+[15]|DESCRIPTIVE_ONLY|INSUFFICIENT_DATA|AUTH-[A-Z0-9_-]+|E-[A-Z0-9_-]+)"
    )
    _NUMBER = re.compile(r"(?<![A-Za-z])[-+]?\d+(?:,\d{3})*(?:\.\d+)?")
    _NUMERIC_UNITS = ("百萬元", "億元", "元", "倍", "%", "年", "月", "日", "季", "期", "秒")

    @classmethod
    def _balanced_punctuation(cls, body: str) -> bool:
        return all(
            body.count(left) == body.count(right)
            for left, right in (("（", "）"), ("(", ")"), ("【", "】"), ("[", "]"))
        )

    @classmethod
    def _numeric_units_present(cls, body: str) -> bool:
        for match in cls._NUMBER.finditer(body):
            suffix = body[match.end() : match.end() + 4]
            prefix = body[max(0, match.start() - 4) : match.start()]
            if not any(suffix.startswith(unit) for unit in cls._NUMERIC_UNITS) and not prefix.endswith("百分之"):
                return False
        return True

    @classmethod
    def _segment_is_complete(cls, body: str) -> bool:
        stripped = body.strip()
        return bool(stripped) and stripped.endswith(("。", "！", "？")) and not cls._FORBIDDEN_TERMINAL.search(stripped)

    @classmethod
    def validate(cls, script: str) -> ShortsDurationValidation:
        segment_counts: dict[str, int] = {}
        segment_seconds: dict[str, float] = {}
        segment_integrity: dict[str, bool] = {}
        sentence_complete = True
        numeric_units_preserved = True
        spoken_technical_codes_absent = True
        balanced_punctuation = True
        no_mechanical_truncation = True
        for match in cls._SEGMENT.finditer(script.replace("\r\n", "\n")):
            label = match.group("label")
            body = match.group("body").strip()
            count = len(cls._SPOKEN_CHARACTER.findall(body))
            segment_counts[label] = count
            segment_seconds[label] = round(count / cls.SPOKEN_CHARACTERS_PER_SECOND, 2)
            complete = cls._segment_is_complete(body)
            units = cls._numeric_units_present(body)
            codes_absent = cls._RAW_TECHNICAL_CODE.search(body) is None
            punctuation = cls._balanced_punctuation(body)
            not_truncated = cls._FORBIDDEN_TERMINAL.search(body) is None
            segment_integrity[label] = all((complete, units, codes_absent, punctuation, not_truncated))
            sentence_complete = sentence_complete and complete
            numeric_units_preserved = numeric_units_preserved and units
            spoken_technical_codes_absent = spoken_technical_codes_absent and codes_absent
            balanced_punctuation = balanced_punctuation and punctuation
            no_mechanical_truncation = no_mechanical_truncation and not_truncated

        count = sum(segment_counts.values())
        seconds = round(count / cls.SPOKEN_CHARACTERS_PER_SECOND, 2)
        warnings: list[str] = []
        errors: list[str] = []
        expected_segments_present = tuple(segment_counts) == cls._REQUIRED_SEGMENTS
        all_segments_complete = expected_segments_present and all(segment_integrity.values())
        if not expected_segments_present:
            errors.append("All six governed timed segments are required and must be ordered")
        if not sentence_complete:
            errors.append("A timed segment does not end with a complete sentence")
        if not numeric_units_preserved:
            errors.append("A spoken numeric claim is missing its unit")
        if not spoken_technical_codes_absent:
            errors.append("Spoken copy contains a raw internal technical code")
        if not balanced_punctuation:
            errors.append("Spoken copy contains unbalanced punctuation")
        if not no_mechanical_truncation:
            errors.append("Spoken copy contains a mechanically truncated terminal token")
        if not all_segments_complete:
            errors.append("One or more timed segments are not semantically complete")
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
            segment_integrity=segment_integrity,
            sentence_integrity_status="PASS" if all_segments_complete else "FAIL",
            numeric_unit_status="PASS" if numeric_units_preserved else "FAIL",
            sentence_completeness_passed=sentence_complete,
            numeric_units_preserved=numeric_units_preserved,
            spoken_technical_codes_absent=spoken_technical_codes_absent,
            balanced_punctuation_passed=balanced_punctuation,
            no_mechanical_truncation=no_mechanical_truncation,
            all_segments_semantically_complete=all_segments_complete,
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
