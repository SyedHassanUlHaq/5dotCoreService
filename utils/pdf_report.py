"""Builds the forensic analysis PDF for a completed scan.

Pulled in from api/detection_request.py's GET /{request_id}/report.pdf.
Generation is synchronous — a report is just formatting already-stored data
(the detection scores + chunk breakdown), not new AI work, so there's no
need for the async job/poll pattern the request/response cycle already
proved out for detection itself.
"""

import io
from datetime import datetime, timezone

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable,
)
from reportlab.graphics.shapes import Drawing
from reportlab.graphics.charts.barcharts import VerticalBarChart

AI_HEX = "#E63946"
AUTHENTIC_HEX = "#2A9D8F"
BRAND_COLOR = colors.HexColor("#6C5CE7")
AI_COLOR = colors.HexColor(AI_HEX)
AUTHENTIC_COLOR = colors.HexColor(AUTHENTIC_HEX)
MUTED = colors.HexColor("#6B7280")

DETECTION_LABELS = {
    "ai_audio": "AI Voice Detection",
    "ai_video": "Deepfake Video Detection",
    "lipsync": "Lip-Sync Detection",
    "changes": "Scene / Tamper Detection",
}

CHUNK_SCORE_FIELD = {
    "ai_audio": "ai_audio_score",
    "ai_video": "ai_video_score",
    "lipsync": "lipsync_score",
}


def _styles():
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        "ReportTitle", parent=styles["Title"], fontSize=22, textColor=BRAND_COLOR, spaceAfter=4,
    ))
    styles.add(ParagraphStyle(
        "ReportSubtitle", parent=styles["Normal"], fontSize=11, textColor=MUTED, spaceAfter=18,
    ))
    styles.add(ParagraphStyle(
        "SectionHeading", parent=styles["Heading2"], fontSize=13, spaceBefore=18, spaceAfter=8,
    ))
    styles.add(ParagraphStyle(
        "VerdictBig", parent=styles["Normal"], fontSize=16, spaceAfter=4,
    ))
    styles.add(ParagraphStyle(
        "Footer", parent=styles["Normal"], fontSize=8, textColor=MUTED,
    ))
    return styles


def _fmt_dt(dt: datetime | None) -> str:
    if not dt:
        return "—"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.strftime("%b %d, %Y at %H:%M UTC")


def _fmt_seconds(seconds: float) -> str:
    total = max(0, round(seconds))
    return f"{total // 60}:{total % 60:02d}"


def _score_chart(segments: list[tuple[float, float, float]], threshold: float, accent: colors.Color) -> Drawing:
    """segments: list of (start, end, score in 0-1)."""
    drawing = Drawing(460, 160)
    chart = VerticalBarChart()
    chart.x = 40
    chart.y = 20
    chart.width = 400
    chart.height = 120
    chart.data = [[s[2] * 100 for s in segments]]
    chart.categoryAxis.categoryNames = [_fmt_seconds(s[0]) for s in segments]
    chart.categoryAxis.labels.angle = 45
    chart.categoryAxis.labels.dy = -12
    chart.categoryAxis.labels.fontSize = 6
    chart.valueAxis.valueMin = 0
    chart.valueAxis.valueMax = 100
    chart.valueAxis.valueStep = 25
    chart.bars[0].fillColor = accent
    chart.strokeColor = colors.white

    # Threshold reference line, drawn as a thin bar-chart-relative overlay.
    from reportlab.graphics.shapes import Line
    threshold_y = chart.y + (threshold * 100 / chart.valueAxis.valueMax) * chart.height
    drawing.add(Line(chart.x, threshold_y, chart.x + chart.width, threshold_y,
                      strokeColor=MUTED, strokeDashArray=[3, 3], strokeWidth=0.75))

    drawing.add(chart)
    return drawing


def build_forensic_pdf(dr, chunks: list, requested_types: list[str]) -> bytes:
    """dr: models.detection_request.DetectionRequest (with .result_data etc).
    chunks: list[models.chunk.Chunk], already ordered by chunk_index.
    requested_types: from _requested_types_of(dr) — which detection kinds
    were actually asked for, in the caller's canonical order."""
    styles = _styles()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=letter,
        topMargin=0.75 * inch, bottomMargin=0.75 * inch,
        leftMargin=0.75 * inch, rightMargin=0.75 * inch,
        title=f"Forensic Report — {dr.filename}",
    )

    story = []
    story.append(Paragraph("5dot Forensic Analysis Report", styles["ReportTitle"]))
    story.append(Paragraph(
        f"Scan ID: {dr.id} &nbsp;·&nbsp; Generated {_fmt_dt(datetime.now(timezone.utc))}",
        styles["ReportSubtitle"],
    ))
    story.append(HRFlowable(width="100%", color=colors.HexColor("#E5E7EB"), thickness=1))
    story.append(Spacer(1, 14))

    # ── Scan metadata ──────────────────────────────────────────────────────
    meta_rows = [
        ["File", dr.filename],
        ["Submitted", _fmt_dt(dr.created_at)],
        ["Completed", _fmt_dt(dr.completed_at)],
        ["Status", dr.status.capitalize()],
    ]
    meta_table = Table(meta_rows, colWidths=[110, 350])
    meta_table.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("TEXTCOLOR", (0, 0), (0, -1), MUTED),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("LINEBELOW", (0, 0), (-1, -2), 0.5, colors.HexColor("#F3F4F6")),
    ]))
    story.append(meta_table)
    story.append(Spacer(1, 10))

    # ── Per-detection results ──────────────────────────────────────────────
    result_data = dr.result_data or {}

    for kind in requested_types:
        payload = result_data.get(kind)
        label = DETECTION_LABELS.get(kind, kind)
        story.append(Paragraph(label, styles["SectionHeading"]))

        if not payload or "score" not in payload:
            story.append(Paragraph("No result available for this check.", styles["Normal"]))
            story.append(Spacer(1, 8))
            continue

        score = payload["score"]
        threshold = payload.get("threshold", 0.5)
        flagged = score >= threshold
        verdict_text = "Flagged" if flagged else "Clear"
        verdict_hex = AI_HEX if flagged else AUTHENTIC_HEX
        verdict_color = AI_COLOR if flagged else AUTHENTIC_COLOR

        story.append(Paragraph(
            f'<font color="{verdict_hex}">{verdict_text}</font> — '
            f"{score * 100:.1f}% (threshold {threshold * 100:.0f}%)",
            styles["VerdictBig"],
        ))

        field = CHUNK_SCORE_FIELD.get(kind)
        segments = []
        if field:
            for c in chunks:
                val = getattr(c, field, None)
                if val is not None:
                    segments.append((c.segment_start, c.segment_end, val))

        if segments:
            story.append(Paragraph("Score over time (per-segment breakdown):", styles["Normal"]))
            story.append(Spacer(1, 4))
            story.append(_score_chart(segments, threshold, verdict_color))
        story.append(Spacer(1, 10))

    story.append(Spacer(1, 10))
    story.append(HRFlowable(width="100%", color=colors.HexColor("#E5E7EB"), thickness=1))
    story.append(Spacer(1, 6))
    story.append(Paragraph(
        "This report is generated automatically from 5dot's detection pipeline. "
        "Scores reflect model confidence, not certainty — no automated tool can "
        "guarantee 100% accuracy. This report is provided for informational "
        "purposes and is not a substitute for professional forensic analysis.",
        styles["Footer"],
    ))

    doc.build(story)
    return buf.getvalue()
