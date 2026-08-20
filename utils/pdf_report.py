"""Builds the forensic analysis PDF for a completed scan.

Pulled in from api/detection_request.py's GET /{request_id}/report.pdf.
Generation is synchronous — a report is just formatting already-stored data
(the detection scores + chunk breakdown), not new AI work, so there's no
need for the async job/poll pattern the request/response cycle already
proved out for detection itself.

The score-over-time chart is hand-drawn with primitive shapes rather than
reportlab's stock VerticalBarChart widget — the widget's chunky evenly-
spaced bars and rotated labels read as a spreadsheet auto-chart. Full
control over gridlines, bar geometry, and label placement is what makes
this look like a produced report instead of a debug dump.
"""

import io
from datetime import datetime, timezone

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_CENTER
from reportlab.pdfgen import canvas as pdfcanvas
from reportlab.platypus import (
    BaseDocTemplate, PageTemplate, Frame, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, KeepTogether,
)
from reportlab.graphics.shapes import Drawing, Rect, Line, String

from config.project_config import MODEL_VERSION

PAGE_W, PAGE_H = letter
MARGIN = 0.75 * inch

INK = colors.HexColor("#111827")
MUTED = colors.HexColor("#6B7280")
FAINT = colors.HexColor("#9CA3AF")
BRAND = colors.HexColor("#C0376B")       # matches Colors.brand in the app
BRAND_DARK = colors.HexColor("#922B52")  # matches Colors.brandDark in the app
AI_HEX = "#DC2626"
AUTHENTIC_HEX = "#0D9488"
AI_COLOR = colors.HexColor(AI_HEX)
AUTHENTIC_COLOR = colors.HexColor(AUTHENTIC_HEX)
GRID = colors.HexColor("#E5E7EB")
CARD_BG = colors.HexColor("#F9FAFB")
CARD_BORDER = colors.HexColor("#F3F4F6")

DETECTION_LABELS = {
    "ai_audio": "AI Voice Detection",
    "ai_video": "Deepfake Video Detection",
    "lipsync": "Lip-Sync Detection",
    "changes": "Scene / Tamper Detection",
}

# Same copy as the in-app FAQ (HelpSupportScreen) — keeps the report
# consistent with what a user already read about how each mode works.
DETECTION_METHODOLOGY = {
    "ai_audio": "Detects AI-synthesised or cloned voices (text-to-speech, voice cloning) by analysing "
                "spectral and prosodic patterns across the audio in short overlapping segments.",
    "ai_video": "Detects deepfake faces — face-swaps, mouth-movement mismatches, and GAN artefacts — by "
                "scoring visual consistency frame-by-frame across the clip.",
    "lipsync": "Finds cut-and-splice edits, re-encoding jumps, and timeline discontinuities, regardless of "
               "whether AI was involved in producing them.",
    "changes": "Flags structural edits to the scene — cuts, splices, and re-encoded segments — independent "
               "of the audio/video content itself.",
}

CHUNK_SCORE_FIELD = {
    "ai_audio": "ai_audio_score",
    "ai_video": "ai_video_score",
    "lipsync": "lipsync_score",
}


def _styles():
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle("ReportBody", parent=styles["Normal"], fontSize=9.5, leading=14, textColor=INK))
    styles.add(ParagraphStyle("Muted", parent=styles["ReportBody"], textColor=MUTED, fontSize=8.5))
    styles.add(ParagraphStyle("SectionHeading", parent=styles["Heading2"],
                               fontSize=13, textColor=INK, spaceBefore=22, spaceAfter=8,
                               fontName="Helvetica-Bold"))
    styles.add(ParagraphStyle("SubHeading", parent=styles["ReportBody"],
                               fontSize=10.5, fontName="Helvetica-Bold", textColor=INK, spaceAfter=4))
    styles.add(ParagraphStyle("CardLabel", parent=styles["ReportBody"],
                               fontSize=7.5, textColor=MUTED, fontName="Helvetica-Bold", leading=10))
    styles.add(ParagraphStyle("CardValue", parent=styles["ReportBody"],
                               fontSize=15, fontName="Helvetica-Bold", textColor=INK, leading=18))
    styles.add(ParagraphStyle("ExecVerdict", parent=styles["ReportBody"],
                               fontSize=20, fontName="Helvetica-Bold", leading=24))
    styles.add(ParagraphStyle("ExecSub", parent=styles["ReportBody"], fontSize=9.5, textColor=MUTED, leading=13))
    styles.add(ParagraphStyle("TableHeadCell", parent=styles["ReportBody"],
                               fontSize=8, fontName="Helvetica-Bold", textColor=colors.white))
    styles.add(ParagraphStyle("TableCell", parent=styles["ReportBody"], fontSize=9))
    styles.add(ParagraphStyle("MethodText", parent=styles["ReportBody"], fontSize=9, textColor=MUTED, leading=13))
    return styles


def _fmt_dt(dt: datetime | None) -> str:
    if not dt:
        return "—"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.strftime("%b %d, %Y · %H:%M UTC")


def _fmt_seconds(seconds: float) -> str:
    total = max(0, round(seconds))
    return f"{total // 60}:{total % 60:02d}"


def _fmt_bytes(n: int | None) -> str:
    if not n:
        return "—"
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def _processing_time(dr) -> str:
    if not dr.created_at or not dr.completed_at:
        return "—"
    started = dr.created_at if dr.created_at.tzinfo else dr.created_at.replace(tzinfo=timezone.utc)
    ended = dr.completed_at if dr.completed_at.tzinfo else dr.completed_at.replace(tzinfo=timezone.utc)
    return f"{(ended - started).total_seconds():.1f}s"


# ── Header / footer, drawn on every page ─────────────────────────────────────

class _ReportCanvas(pdfcanvas.Canvas):
    """Buffers pages so the footer can show 'Page X of Y' — reportlab only
    knows the final page count once every page has already been built."""

    def __init__(self, *args, **kwargs):
        pdfcanvas.Canvas.__init__(self, *args, **kwargs)
        self._saved_states = []

    def showPage(self):
        self._saved_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._saved_states)
        for state in self._saved_states:
            self.__dict__.update(state)
            self._draw_chrome(total)
            pdfcanvas.Canvas.showPage(self)
        pdfcanvas.Canvas.save(self)

    def _draw_chrome(self, total_pages):
        page_num = self._pageNumber
        # Header band
        self.setFillColor(BRAND)
        self.rect(0, PAGE_H - 0.55 * inch, PAGE_W, 0.55 * inch, fill=1, stroke=0)
        self.setFillColor(colors.white)
        self.setFont("Helvetica-Bold", 13)
        self.drawString(MARGIN, PAGE_H - 0.37 * inch, "5dot")
        self.setFont("Helvetica", 8)
        self.drawRightString(PAGE_W - MARGIN, PAGE_H - 0.36 * inch, "FORENSIC ANALYSIS REPORT")

        # Footer
        self.setStrokeColor(GRID)
        self.setLineWidth(0.5)
        self.line(MARGIN, 0.55 * inch, PAGE_W - MARGIN, 0.55 * inch)
        self.setFillColor(FAINT)
        self.setFont("Helvetica", 7.5)
        self.drawString(MARGIN, 0.38 * inch,
                         "Generated automatically by 5dot. Scores reflect model confidence, not certainty.")
        self.drawRightString(PAGE_W - MARGIN, 0.38 * inch, f"Page {page_num} of {total_pages}")


def _score_chart(segments: list[tuple[float, float, float]], threshold: float, accent_hex: str) -> Drawing:
    """Hand-drawn bar chart: gridlines, precise bar geometry, sparse labels."""
    W, H = 460, 150
    plot_x, plot_y = 46, 34
    plot_w, plot_h = 400, 92
    accent = colors.HexColor(accent_hex)

    d = Drawing(W, H)

    # Gridlines + y-axis labels at 0/25/50/75/100
    for pct in (0, 25, 50, 75, 100):
        y = plot_y + (pct / 100) * plot_h
        d.add(Line(plot_x, y, plot_x + plot_w, y, strokeColor=GRID, strokeWidth=0.5))
        d.add(String(plot_x - 8, y - 3, str(pct), fontSize=6.5, fillColor=MUTED, textAnchor="end"))

    # Threshold line
    thr_y = plot_y + threshold * plot_h
    d.add(Line(plot_x, thr_y, plot_x + plot_w, thr_y,
                strokeColor=colors.HexColor("#B45309"), strokeWidth=0.9, strokeDashArray=[3, 2]))
    d.add(String(plot_x + plot_w, thr_y + 3, f"Threshold {threshold * 100:.0f}%",
                  fontSize=6.5, fillColor=colors.HexColor("#B45309"), textAnchor="end"))

    # Bars
    n = len(segments)
    gap = 3
    bar_w = min(18, (plot_w - gap * (n - 1)) / n) if n else 0
    total_bars_w = n * bar_w + (n - 1) * gap
    start_x = plot_x + (plot_w - total_bars_w) / 2

    label_every = max(1, round(n / 8))
    for i, (seg_start, _seg_end, score) in enumerate(segments):
        x = start_x + i * (bar_w + gap)
        bar_h = max(1.5, score * plot_h)
        fill = accent if score >= threshold else colors.HexColor(accent_hex + "80")
        d.add(Rect(x, plot_y, bar_w, bar_h, fillColor=fill, strokeColor=None))
        if i % label_every == 0 or i == n - 1:
            d.add(String(x + bar_w / 2, plot_y - 12, _fmt_seconds(seg_start),
                          fontSize=6, fillColor=MUTED, textAnchor="middle"))

    # Axis line
    d.add(Line(plot_x, plot_y, plot_x + plot_w, plot_y, strokeColor=FAINT, strokeWidth=0.75))
    d.add(String(plot_x, plot_y - 24, "Time (mm:ss)", fontSize=6.5, fillColor=MUTED))
    d.add(String(4, plot_y + plot_h / 2, "Score %", fontSize=6.5, fillColor=MUTED))

    return d


def _stat_card(styles, label: str, value: str, width: float) -> Table:
    t = Table(
        [[Paragraph(label.upper(), styles["CardLabel"])], [Paragraph(value, styles["CardValue"])]],
        colWidths=[width],
    )
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), CARD_BG),
        ("BOX", (0, 0), (-1, -1), 0.75, CARD_BORDER),
        ("TOPPADDING", (0, 0), (-1, 0), 10),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 2),
        ("TOPPADDING", (0, 1), (-1, 1), 0),
        ("BOTTOMPADDING", (0, 1), (-1, 1), 10),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
    ]))
    return t


def _verdict_badge(styles, text: str, hexcolor: str):
    p = Paragraph(f'<font color="white"><b>{text}</b></font>', ParagraphStyle(
        "Badge", parent=styles["ReportBody"], fontSize=9, alignment=TA_CENTER, textColor=colors.white,
    ))
    t = Table([[p]], colWidths=[1.3 * inch])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(hexcolor)),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
    ]))
    return t


def build_forensic_pdf(dr, chunks: list, requested_types: list[str]) -> bytes:
    """dr: models.detection_request.DetectionRequest.
    chunks: list[models.chunk.Chunk], already ordered by chunk_index.
    requested_types: from _requested_types_of(dr), canonical order."""
    styles = _styles()
    buf = io.BytesIO()

    frame = Frame(MARGIN, 0.7 * inch, PAGE_W - 2 * MARGIN, PAGE_H - 1.55 * inch, id="body")
    doc = BaseDocTemplate(
        buf, pagesize=letter, title=f"Forensic Report — {dr.filename}",
        topMargin=1.0 * inch, bottomMargin=0.7 * inch, leftMargin=MARGIN, rightMargin=MARGIN,
    )
    doc.addPageTemplates([PageTemplate(id="report", frames=[frame])])

    result_data = dr.result_data or {}
    all_results = [(k, result_data.get(k)) for k in requested_types if result_data.get(k) and "score" in result_data.get(k, {})]
    headline = max(all_results, key=lambda kv: kv[1]["score"], default=None)

    story = []

    # ── Title block ──────────────────────────────────────────────────────
    story.append(Paragraph(dr.filename, ParagraphStyle(
        "Title", parent=styles["ReportBody"], fontSize=17, fontName="Helvetica-Bold", leading=21,
    )))
    story.append(Paragraph(
        f"Scan ID {dr.id}  ·  Report generated {_fmt_dt(datetime.now(timezone.utc))}",
        styles["Muted"],
    ))
    story.append(Spacer(1, 16))

    # ── Executive summary ───────────────────────────────────────────────
    if headline:
        kind, payload = headline
        flagged = payload["score"] >= payload.get("threshold", 0.5)
        verdict_text = "AI-GENERATED / TAMPERED" if flagged else "NO MANIPULATION DETECTED"
        verdict_hex = AI_HEX if flagged else AUTHENTIC_HEX
        exec_left = [
            Paragraph(verdict_text, ParagraphStyle(
                "ExecVerdict2", parent=styles["ExecVerdict"], textColor=colors.HexColor(verdict_hex),
            )),
            Spacer(1, 3),
            Paragraph(
                f"Highest-confidence signal: {DETECTION_LABELS.get(kind, kind)} "
                f"at {payload['score'] * 100:.1f}% (flagging threshold {payload.get('threshold', 0.5) * 100:.0f}%).",
                styles["ExecSub"],
            ),
        ]
        exec_table = Table([[exec_left]], colWidths=[PAGE_W - 2 * MARGIN])
        exec_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), CARD_BG),
            ("BOX", (0, 0), (-1, -1), 1, colors.HexColor(verdict_hex)),
            ("TOPPADDING", (0, 0), (-1, -1), 14),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 14),
            ("LEFTPADDING", (0, 0), (-1, -1), 16),
            ("RIGHTPADDING", (0, 0), (-1, -1), 16),
        ]))
        story.append(exec_table)
        story.append(Spacer(1, 18))

    # ── File metadata ────────────────────────────────────────────────────
    story.append(Paragraph("FILE DETAILS", styles["SubHeading"]))
    meta_rows = [
        ["Source", dr.url_source or "Direct upload"],
        ["File size", _fmt_bytes(dr.file_size)],
        ["Duration", _fmt_seconds(dr.duration) if dr.duration else "—"],
        ["Bitrate", dr.bitrate or "—"],
        ["Submitted", _fmt_dt(dr.created_at)],
        ["Completed", _fmt_dt(dr.completed_at)],
        ["Processing time", _processing_time(dr)],
        ["Model version", MODEL_VERSION],
    ]
    meta_table = Table(
        [[Paragraph(f"<b>{k}</b>", styles["TableCell"]), Paragraph(str(v), styles["TableCell"])] for k, v in meta_rows],
        colWidths=[130, PAGE_W - 2 * MARGIN - 130],
    )
    meta_table.setStyle(TableStyle([
        ("TEXTCOLOR", (0, 0), (0, -1), MUTED),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("LINEBELOW", (0, 0), (-1, -2), 0.5, CARD_BORDER),
    ]))
    story.append(meta_table)

    # ── Summary table across all detections ─────────────────────────────
    if len(all_results) > 1:
        story.append(Paragraph("SUMMARY", styles["SubHeading"]))
        head = [Paragraph(h, styles["TableHeadCell"]) for h in ("Detection", "Verdict", "Score", "Threshold")]
        rows = [head]
        for kind, payload in all_results:
            flagged = payload["score"] >= payload.get("threshold", 0.5)
            rows.append([
                Paragraph(DETECTION_LABELS.get(kind, kind), styles["TableCell"]),
                _verdict_badge(styles, "FLAGGED" if flagged else "CLEAR", AI_HEX if flagged else AUTHENTIC_HEX),
                Paragraph(f"{payload['score'] * 100:.1f}%", styles["TableCell"]),
                Paragraph(f"{payload.get('threshold', 0.5) * 100:.0f}%", styles["TableCell"]),
            ])
        summary_table = Table(rows, colWidths=[190, 120, 80, 80])
        summary_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), BRAND),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 7),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ("LINEBELOW", (0, 0), (-1, -2), 0.5, CARD_BORDER),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, CARD_BG]),
        ]))
        story.append(summary_table)

    # ── Per-detection deep dive ──────────────────────────────────────────
    for idx, kind in enumerate(requested_types):
        is_last = idx == len(requested_types) - 1
        payload = result_data.get(kind)
        label = DETECTION_LABELS.get(kind, kind)

        section = [Paragraph(label, styles["SectionHeading"])]
        section.append(Paragraph(DETECTION_METHODOLOGY.get(kind, ""), styles["MethodText"]))
        section.append(Spacer(1, 10))

        if not payload or "score" not in payload:
            section.append(Paragraph("No result available for this check.", styles["ReportBody"]))
            story.append(KeepTogether(section))
            if not is_last:
                story.append(Spacer(1, 6))
                story.append(HRFlowable(width="100%", color=CARD_BORDER, thickness=0.75))
            continue

        score = payload["score"]
        threshold = payload.get("threshold", 0.5)
        flagged = score >= threshold
        verdict_hex = AI_HEX if flagged else AUTHENTIC_HEX

        field = CHUNK_SCORE_FIELD.get(kind)
        segment_scores = []
        if field:
            for c in chunks:
                val = getattr(c, field, None)
                if val is not None:
                    segment_scores.append((c.segment_start, c.segment_end, val))

        # Stat card row: verdict, score, segments analyzed, segments flagged
        vals = [s[2] for s in segment_scores] or [score]
        cards = [
            _stat_card(styles, "Verdict", "Flagged" if flagged else "Clear", 118),
            _stat_card(styles, "Overall score", f"{score * 100:.1f}%", 118),
            _stat_card(styles, "Peak segment", f"{max(vals) * 100:.1f}%", 118),
            _stat_card(styles, "Segments analyzed", str(len(segment_scores)) if segment_scores else "1", 118),
        ]
        card_row = Table([cards], colWidths=[118] * 4)
        card_row.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (1, 0), (-1, -1), 6)]))
        section.append(card_row)
        section.append(Spacer(1, 12))

        if segment_scores:
            section.append(Paragraph("Score over time", ParagraphStyle(
                "ChartTitle", parent=styles["ReportBody"], fontSize=8.5, fontName="Helvetica-Bold", textColor=MUTED,
            )))
            section.append(Spacer(1, 4))
            section.append(_score_chart(segment_scores, threshold, verdict_hex))

        story.append(KeepTogether(section[:2]))
        story.extend(section[2:])
        if not is_last:
            story.append(Spacer(1, 6))
            story.append(HRFlowable(width="100%", color=CARD_BORDER, thickness=0.75))

    doc.build(story, canvasmaker=_ReportCanvas)
    return buf.getvalue()
