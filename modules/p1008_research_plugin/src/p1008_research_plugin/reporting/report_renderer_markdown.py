"""Canonical Markdown rendering for a validated report candidate."""

from __future__ import annotations

from .report_contracts import ReportCandidate


class MarkdownRenderer:
    def render(self, report: ReportCandidate) -> str:
        lines = [
            "# 鴻海月營收戰情報告：成長動能與現金轉化的落差",
            "",
            f"**Run ID：** `{report.run_id}`  ",
            f"**核心問題：** {report.primary_investor_question}",
            "",
        ]
        for section in report.sections:
            lines.extend([f"## {section.title_zh}", "", section.body_zh, ""])
            if section.evidence_ids:
                lines.extend([f"引用：{', '.join(f'[{item}]' for item in section.evidence_ids)}", ""])
        lines.extend(["---", "", "本文件為研究候選，actionable=false；不構成個人化投資建議或交易指令。", ""])
        return "\n".join(lines)
