"""Formal, non-publishing HTML/PDF preview renderer for Owner review."""

from __future__ import annotations

import html
from io import BytesIO
from pathlib import Path

from .report_contracts import ReportCandidate


class FormalPreviewRenderer:
    def html(self, report: ReportCandidate) -> bytes:
        sections = "\n".join(
            f'<section data-section-id="{html.escape(item.section_id)}"><h2>{html.escape(item.title_zh)}</h2>'
            f'<p>{html.escape(item.body_zh)}</p><p class="evidence">Evidence: '
            f'{html.escape(", ".join(item.evidence_ids) or "governance boundary")}</p></section>'
            for item in report.sections
        )
        references = "\n".join(
            f'<li><strong>{html.escape(item.evidence_id)}</strong> — {html.escape(item.claim)} '
            f'({html.escape(item.source_tier)}, {html.escape(item.source_date)})<br>'
            + " ".join(f'<a href="{html.escape(url)}">{html.escape(url)}</a>' for url in item.source_urls)
            + "</li>"
            for item in report.evidence_references
        )
        document = f"""<!doctype html>
<html lang="zh-Hant"><head><meta charset="utf-8"><title>P1008 {html.escape(report.event_type)} Owner Review</title>
<style>body{{font-family:system-ui,"Noto Sans TC",sans-serif;max-width:960px;margin:32px auto;padding:0 24px;color:#17202a;line-height:1.72}}header{{border-bottom:4px solid #23395d;padding-bottom:18px}}h1{{margin-bottom:4px}}h2{{color:#23395d;margin-top:30px}}.status{{display:inline-block;background:#fff3cd;border:1px solid #d6b656;padding:5px 10px}}.evidence{{font-size:.82rem;color:#52606d}}section{{break-inside:avoid}}a{{color:#174ea6;overflow-wrap:anywhere}}footer{{margin-top:36px;border-top:1px solid #ccd2d8;padding-top:16px}}</style></head>
<body data-run-id="{html.escape(report.run_id)}" data-event-type="{html.escape(report.event_type)}" data-publication="false">
<header><h1>鴻海 FY2026 Q2 正式戰情報告候選</h1><p>{html.escape(report.primary_investor_question)}</p><p class="status">OWNER_REVIEW_REQUIRED · PUBLICATION=NO</p></header>
{sections}<section><h2>Evidence references</h2><ol>{references}</ol></section>
<footer>actionable=false · publishAuthorized=false · Owner-gated preview</footer></body></html>"""
        return document.encode("utf-8")

    def pdf(self, report: ReportCandidate) -> bytes:
        try:
            from reportlab.lib.enums import TA_CENTER
            from reportlab.lib.pagesizes import A4
            from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
            from reportlab.lib.units import mm
            from reportlab.pdfbase import pdfmetrics
            from reportlab.pdfbase.cidfonts import UnicodeCIDFont
            from reportlab.pdfbase.ttfonts import TTFont
            from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer
        except ImportError as exc:
            raise RuntimeError("PDF_PREVIEW_DEPENDENCY_MISSING: reportlab") from exc
        cjk_font = "STSong-Light"
        for font_path in (
            Path("C:/Windows/Fonts/msjh.ttc"),
            Path("C:/Windows/Fonts/msjh.ttf"),
            Path("C:/Windows/Fonts/mingliu.ttc"),
        ):
            if font_path.is_file():
                pdfmetrics.registerFont(TTFont("P1008CJK", str(font_path), subfontIndex=0))
                cjk_font = "P1008CJK"
                break
        else:
            pdfmetrics.registerFont(UnicodeCIDFont(cjk_font))
        buffer = BytesIO()
        document = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=18 * mm, leftMargin=18 * mm, topMargin=18 * mm, bottomMargin=18 * mm, title="P1008 FY2026 Q2 Owner Review", author="P1008 Phase B1")
        styles = getSampleStyleSheet()
        title = ParagraphStyle("CJKTitle", parent=styles["Title"], fontName=cjk_font, fontSize=20, leading=27, alignment=TA_CENTER, textColor="#23395d")
        heading = ParagraphStyle("CJKHeading", parent=styles["Heading2"], fontName=cjk_font, fontSize=13, leading=18, textColor="#23395d", spaceBefore=12, spaceAfter=6)
        body = ParagraphStyle("CJKBody", parent=styles["BodyText"], fontName=cjk_font, fontSize=9.5, leading=15, spaceAfter=6)
        evidence = ParagraphStyle("CJKEvidence", parent=body, fontSize=7.5, leading=11, textColor="#52606d")
        story = [Paragraph("鴻海 FY2026 Q2 正式戰情報告候選", title), Spacer(1, 8), Paragraph(html.escape(report.primary_investor_question), body), Paragraph("OWNER_REVIEW_REQUIRED · PUBLICATION=NO", heading), Spacer(1, 6)]
        for item in report.sections:
            story.extend([Paragraph(html.escape(item.title_zh), heading), Paragraph(html.escape(item.body_zh), body), Paragraph("Evidence: " + html.escape(", ".join(item.evidence_ids) or "governance boundary"), evidence)])
        story.extend([PageBreak(), Paragraph("Evidence references", heading)])
        for item in report.evidence_references:
            story.append(Paragraph(html.escape(f"{item.evidence_id} — {item.claim} ({item.source_tier}, {item.source_date})"), evidence))
            for url in item.source_urls:
                story.append(Paragraph(html.escape(url), evidence))
        story.append(Paragraph("actionable=false · publishAuthorized=false · Owner-gated preview", evidence))
        document.build(story)
        return buffer.getvalue()
