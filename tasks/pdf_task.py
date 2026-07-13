"""
Celery task that generates a forensic PDF report for a completed scan.
Requires: reportlab  (pip install reportlab)
"""

import io
import os
import tempfile
import uuid
from datetime import datetime, timezone

from celery_app import celery_app
from database import SessionLocal
from models.scan import Scan
from utils.s3 import upload_bytes, presigned_url, download_file
from utils.push import send_push


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _fmt_size(b: int) -> str:
    if not b:
        return "—"
    if b >= 1024 ** 3:
        return f"{b / 1024 ** 3:.1f} GB"
    if b >= 1024 ** 2:
        return f"{b / 1024 ** 2:.1f} MB"
    return f"{b / 1024:.1f} KB"


def _fmt_duration(s: float) -> str:
    if not s:
        return "—"
    m, sec = divmod(int(s), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}h {m:02d}m {sec:02d}s"
    return f"{m}m {sec:02d}s"


def _fmt_dt(dt) -> str:
    if not dt:
        return "—"
    return dt.strftime("%Y-%m-%d %H:%M UTC")


def _processing_time(created_at, completed_at) -> str:
    if not created_at or not completed_at:
        return "—"
    delta = (completed_at - created_at).total_seconds()
    if delta >= 60:
        return f"{int(delta // 60)}m {int(delta % 60)}s"
    return f"{delta:.1f}s"


RESULT_LABELS = {
    "deepfakeVideo": "AI-Generated (Deepfake Video)",
    "editTamper":    "Tampered / Edited Video",
    "aiVoice":       "AI-Generated Voice",
    "authentic":     "Authentic",
    "tampered":      "Tampered",
}

SCAN_TYPE_LABELS = {
    "video":  "AI Deepfake Detection",
    "tamper": "Tampering & Scene Detection",
    "audio":  "AI Voice Detection",
}

VERDICT_LABELS = {
    "ai":        "AI-GENERATED",
    "tampered":  "TAMPERED",
    "authentic": "AUTHENTIC",
}


# ---------------------------------------------------------------------------
# PDF builder
# ---------------------------------------------------------------------------

def _build_pdf(scan: Scan) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.units import cm
    from reportlab.lib.enums import TA_CENTER, TA_LEFT
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
        HRFlowable, Image, KeepTogether,
    )

    # Brand colours
    PINK       = colors.HexColor("#E91E8C")
    DARK       = colors.HexColor("#1A1A2E")
    LIGHT_GREY = colors.HexColor("#F5F5F5")
    MID_GREY   = colors.HexColor("#9E9E9E")
    RED        = colors.HexColor("#C62828")
    ORANGE     = colors.HexColor("#E65100")
    GREEN      = colors.HexColor("#2E7D32")
    WHITE      = colors.white

    verdict_color = {
        "ai":        RED,
        "tampered":  ORANGE,
        "authentic": GREEN,
    }.get(scan.verdict or "authentic", MID_GREY)

    severity_color = {
        "high":   RED,
        "medium": ORANGE,
        "low":    GREEN,
    }

    # Page layout
    MARGIN = 1.8 * cm
    CW = A4[0] - 2 * MARGIN   # usable content width ≈ 17.4 cm

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=MARGIN, bottomMargin=MARGIN,
    )

    # Styles
    base = getSampleStyleSheet()
    S = {
        "brand": ParagraphStyle("brand", fontSize=28, textColor=PINK,
                                fontName="Helvetica-Bold", spaceAfter=0),
        "subtitle": ParagraphStyle("subtitle", fontSize=10, textColor=MID_GREY,
                                   fontName="Helvetica", spaceAfter=4),
        "section": ParagraphStyle("section", fontSize=11, textColor=WHITE,
                                  fontName="Helvetica-Bold", spaceAfter=0,
                                  spaceBefore=0),
        "body": ParagraphStyle("body", fontSize=9, textColor=DARK,
                               fontName="Helvetica", leading=14),
        "small": ParagraphStyle("small", fontSize=7.5, textColor=MID_GREY,
                                fontName="Helvetica", leading=11),
        "verdict": ParagraphStyle("verdict", fontSize=18, textColor=WHITE,
                                  fontName="Helvetica-Bold", alignment=TA_CENTER),
        "score_label": ParagraphStyle("score_label", fontSize=9, textColor=DARK,
                                      fontName="Helvetica-Bold"),
        "explanation": ParagraphStyle("explanation", fontSize=9, textColor=DARK,
                                      fontName="Helvetica", leading=15),
    }

    # Reusable: dark section header row
    def _section_header(title: str) -> Table:
        t = Table([[Paragraph(title, S["section"])]], colWidths=[CW])
        t.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, -1), DARK),
            ("TOPPADDING",    (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("LEFTPADDING",   (0, 0), (-1, -1), 8),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
        ]))
        return t

    def _meta_table(rows: list[list]) -> Table:
        """Two-column key/value table."""
        styled = [[Paragraph(str(k), S["small"]),
                   Paragraph(str(v), S["body"])] for k, v in rows]
        t = Table(styled, colWidths=[4 * cm, CW - 4 * cm])
        t.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (0, -1), LIGHT_GREY),
            ("GRID",          (0, 0), (-1, -1), 0.4, colors.HexColor("#E0E0E0")),
            ("TOPPADDING",    (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING",   (0, 0), (-1, -1), 7),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 7),
            ("FONTNAME",      (0, 0), (0, -1), "Helvetica-Bold"),
            ("FONTSIZE",      (0, 0), (0, -1), 8),
            ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ]))
        return t

    story = []

    # ----------------------------------------------------------------
    # 1. Header
    # ----------------------------------------------------------------
    header_data = [[
        Paragraph("fAIk", S["brand"]),
        Paragraph(
            f"Forensic Analysis Report<br/>"
            f"<font color='#9E9E9E' size=8>Report ID: {scan.id}</font>",
            ParagraphStyle("rh", fontSize=10, textColor=DARK,
                           fontName="Helvetica-Bold", alignment=1),
        ),
    ]]
    header_tbl = Table(header_data, colWidths=[CW * 0.45, CW * 0.55])
    header_tbl.setStyle(TableStyle([
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",    (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(header_tbl)
    story.append(Paragraph("AI Media Authenticity Detection", S["subtitle"]))
    story.append(HRFlowable(width=CW, thickness=1.5, color=PINK, spaceAfter=10))

    # ----------------------------------------------------------------
    # 2. Report information
    # ----------------------------------------------------------------
    story.append(_section_header("REPORT INFORMATION"))
    user = scan.user
    display_name = (user.name or
                    f"{user.first_name or ''} {user.last_name or ''}".strip() or
                    user.email)
    story.append(_meta_table([
        ["Scan ID",       str(scan.id)],
        ["Generated",     _fmt_dt(datetime.now(timezone.utc))],
        ["Requested by",  display_name],
        ["Email",         user.email],
        ["Plan",          user.plan.capitalize()],
        ["Member since",  _fmt_dt(user.created_at)],
    ]))
    story.append(Spacer(1, 10))

    # ----------------------------------------------------------------
    # 3. File details
    # ----------------------------------------------------------------
    story.append(_section_header("FILE DETAILS"))
    file_rows = [
        ["Filename",   scan.filename or "—"],
        ["Scan type",  SCAN_TYPE_LABELS.get(scan.scan_type, scan.scan_type)],
        ["File size",  _fmt_size(scan.file_size)],
        ["Duration",   _fmt_duration(scan.duration)],
        ["Bitrate",    scan.bitrate or "—"],
        ["Source",     scan.url_source or "Local upload"],
        ["Submitted",  _fmt_dt(scan.created_at)],
        ["Completed",  _fmt_dt(scan.completed_at)],
        ["Processing", _processing_time(scan.created_at, scan.completed_at)],
    ]
    story.append(_meta_table(file_rows))
    story.append(Spacer(1, 10))

    # ----------------------------------------------------------------
    # 4. Thumbnail (video / tamper scans)
    # ----------------------------------------------------------------
    thumb_tmp = None
    if scan.thumbnail_key:
        try:
            thumb_tmp = tempfile.mktemp(suffix=".jpg")
            download_file(scan.thumbnail_key, thumb_tmp)
            img = Image(thumb_tmp, width=10 * cm, height=5.6 * cm)
            img_tbl = Table([[img]], colWidths=[CW])
            img_tbl.setStyle(TableStyle([
                ("ALIGN",         (0, 0), (-1, -1), "CENTER"),
                ("TOPPADDING",    (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]))
            story.append(img_tbl)
            story.append(Spacer(1, 6))
        except Exception:
            pass

    # ----------------------------------------------------------------
    # 5. Verdict & score
    # ----------------------------------------------------------------
    verdict_label = VERDICT_LABELS.get(scan.verdict or "authentic", "UNKNOWN")
    result_label  = RESULT_LABELS.get(scan.result_type or "", scan.result_type or "—")
    score         = scan.score or 0

    verdict_tbl = Table(
        [[Paragraph(verdict_label, S["verdict"]),
          Paragraph(result_label,
                    ParagraphStyle("rl", fontSize=9, textColor=WHITE,
                                   fontName="Helvetica", alignment=TA_CENTER))]],
        colWidths=[CW * 0.45, CW * 0.55],
        rowHeights=[40],
    )
    verdict_tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), verdict_color),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",    (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING",   (0, 0), (-1, -1), 8),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
    ]))
    story.append(verdict_tbl)

    # Score bar
    bar_w        = CW - 5 * cm
    filled_w     = bar_w * (score / 100) if score else 0
    empty_w      = bar_w - filled_w
    bar_color    = RED if score >= 70 else ORANGE if score >= 40 else GREEN
    score_rows   = [[
        Paragraph("CONFIDENCE SCORE", S["score_label"]),
        Paragraph(f"{score} / 100", S["body"]),
    ]]
    score_tbl = Table(score_rows, colWidths=[3.5 * cm, CW - 3.5 * cm], rowHeights=[22])
    score_tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), LIGHT_GREY),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING",   (0, 0), (-1, -1), 8),
        ("TOPPADDING",    (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(score_tbl)

    bar_data = [["", ""]] if empty_w > 0 else [["", ""]]
    bar = Table(bar_data, colWidths=[filled_w or 0.1, empty_w or bar_w], rowHeights=[10])
    bar.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (0, 0), bar_color),
        ("BACKGROUND",    (1, 0), (1, 0), colors.HexColor("#E0E0E0")),
        ("TOPPADDING",    (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ("LEFTPADDING",   (0, 0), (-1, -1), 0),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
    ]))
    story.append(bar)
    story.append(Spacer(1, 10))

    # ----------------------------------------------------------------
    # 6. Detailed findings — Video deepfake
    # ----------------------------------------------------------------
    rd = scan.result_data or {}

    if scan.scan_type == "video":
        explanation = rd.get("plainEnglishExplanation", "")
        segments    = rd.get("segments", [])

        story.append(_section_header("ANALYSIS SUMMARY"))
        if explanation:
            story.append(Spacer(1, 4))
            story.append(Paragraph(explanation, S["explanation"]))
        story.append(Spacer(1, 10))

        if segments:
            story.append(_section_header(f"DETECTED SEGMENTS  ({len(segments)} found)"))
            col_w = [1 * cm, 3.5 * cm, 2.8 * cm, CW - 9.8 * cm, 2.5 * cm]
            seg_header = [
                Paragraph(h, ParagraphStyle("th", fontSize=8, textColor=WHITE,
                                            fontName="Helvetica-Bold"))
                for h in ["#", "Time range", "Type", "Label", "Severity"]
            ]
            seg_rows = [seg_header]
            for i, seg in enumerate(segments):
                sev   = seg.get("severity", "")
                sev_c = severity_color.get(sev, MID_GREY)
                time_range = f"{seg.get('startSeconds', 0)}s – {seg.get('endSeconds', 0)}s"
                seg_rows.append([
                    Paragraph(str(i + 1), S["body"]),
                    Paragraph(time_range, S["body"]),
                    Paragraph(seg.get("type", "—"), S["body"]),
                    Paragraph(seg.get("label", "—"), S["body"]),
                    Paragraph(sev.upper(),
                              ParagraphStyle("sev", fontSize=8, textColor=WHITE,
                                             fontName="Helvetica-Bold",
                                             alignment=TA_CENTER)),
                ])
            seg_tbl = Table(seg_rows, colWidths=col_w)
            style = TableStyle([
                ("BACKGROUND",    (0, 0), (-1, 0), DARK),
                ("GRID",          (0, 0), (-1, -1), 0.4, colors.HexColor("#E0E0E0")),
                ("TOPPADDING",    (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LEFTPADDING",   (0, 0), (-1, -1), 5),
                ("RIGHTPADDING",  (0, 0), (-1, -1), 5),
                ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
                ("ALIGN",         (4, 1), (4, -1), "CENTER"),
            ])
            # Alternating rows + severity cell color
            for i, seg in enumerate(segments, start=1):
                if i % 2 == 0:
                    style.add("BACKGROUND", (0, i), (3, i), LIGHT_GREY)
                sev = seg.get("severity", "")
                style.add("BACKGROUND", (4, i), (4, i),
                          severity_color.get(sev, MID_GREY))
            seg_tbl.setStyle(style)
            story.append(seg_tbl)

        story.append(Spacer(1, 10))

    # ----------------------------------------------------------------
    # 7. Detailed findings — Tamper / scene detection
    # ----------------------------------------------------------------
    elif scan.scan_type == "tamper":
        edit_count   = rd.get("editCount", 0)
        edit_summary = rd.get("editSummary", "")
        tamper_level = rd.get("tamperLevel", "—").capitalize()
        edits        = rd.get("edits", [])

        story.append(_section_header("ANALYSIS SUMMARY"))
        summary_rows = [
            ["Edit count",   str(edit_count)],
            ["Tamper level", tamper_level],
            ["Summary",      edit_summary or "—"],
        ]
        story.append(_meta_table(summary_rows))
        story.append(Spacer(1, 10))

        if edits:
            story.append(_section_header(f"DETECTED EDITS  ({len(edits)} found)"))
            col_w = [0.8 * cm, 2.5 * cm, 2.5 * cm, CW - 8.3 * cm, 2.5 * cm]
            edit_header = [
                Paragraph(h, ParagraphStyle("th", fontSize=8, textColor=WHITE,
                                            fontName="Helvetica-Bold"))
                for h in ["#", "Timestamp", "Tag", "Label", "Severity"]
            ]
            edit_rows = [edit_header]
            for edit in edits:
                sev   = edit.get("severity", "")
                sev_c = severity_color.get(sev, MID_GREY)
                edit_rows.append([
                    Paragraph(str(edit.get("number", "—")), S["body"]),
                    Paragraph(f"{edit.get('timeSeconds', 0):.1f}s", S["body"]),
                    Paragraph(edit.get("tag", "—"), S["body"]),
                    Paragraph(edit.get("label", "—"), S["body"]),
                    Paragraph(sev.upper(),
                              ParagraphStyle("sev", fontSize=8, textColor=WHITE,
                                             fontName="Helvetica-Bold",
                                             alignment=TA_CENTER)),
                ])
            edit_tbl = Table(edit_rows, colWidths=col_w)
            estyle = TableStyle([
                ("BACKGROUND",    (0, 0), (-1, 0), DARK),
                ("GRID",          (0, 0), (-1, -1), 0.4, colors.HexColor("#E0E0E0")),
                ("TOPPADDING",    (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LEFTPADDING",   (0, 0), (-1, -1), 5),
                ("RIGHTPADDING",  (0, 0), (-1, -1), 5),
                ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
                ("ALIGN",         (4, 1), (4, -1), "CENTER"),
            ])
            for i, edit in enumerate(edits, start=1):
                if i % 2 == 0:
                    estyle.add("BACKGROUND", (0, i), (3, i), LIGHT_GREY)
                sev = edit.get("severity", "")
                estyle.add("BACKGROUND", (4, i), (4, i),
                           severity_color.get(sev, MID_GREY))
            edit_tbl.setStyle(estyle)
            story.append(edit_tbl)

        story.append(Spacer(1, 10))

    # ----------------------------------------------------------------
    # 8. Audio (stub — shows what's available)
    # ----------------------------------------------------------------
    elif scan.scan_type == "audio":
        story.append(_section_header("AUDIO ANALYSIS"))
        tagline = rd.get("tagline", "Audio analysis is not yet available.")
        story.append(Spacer(1, 4))
        story.append(Paragraph(tagline, S["explanation"]))
        story.append(Spacer(1, 10))

    # ----------------------------------------------------------------
    # 9. Footer
    # ----------------------------------------------------------------
    story.append(HRFlowable(width=CW, thickness=0.5, color=MID_GREY))
    story.append(Spacer(1, 4))
    story.append(Paragraph(
        f"Generated by <b>fAIk</b> · {_fmt_dt(datetime.now(timezone.utc))}  |  "
        f"Model version: {_get_model_version()}",
        S["small"],
    ))
    story.append(Paragraph(
        "This report is generated automatically by machine learning models and is provided "
        "for informational purposes only. fAIk does not guarantee the accuracy of results "
        "and this report should not be used as sole evidence in legal or official proceedings.",
        ParagraphStyle("disclaimer", fontSize=7, textColor=MID_GREY,
                       fontName="Helvetica-Oblique", leading=10),
    ))

    doc.build(story)
    buf.seek(0)

    if thumb_tmp and os.path.exists(thumb_tmp):
        os.remove(thumb_tmp)

    return buf.read()


def _get_model_version() -> str:
    try:
        from config.project_config import MODEL_VERSION
        return MODEL_VERSION
    except Exception:
        return "unknown"


# ---------------------------------------------------------------------------
# Celery task
# ---------------------------------------------------------------------------

@celery_app.task(bind=True)
def generate_pdf(self, scan_id: str):
    db = SessionLocal()
    try:
        scan = db.query(Scan).filter(Scan.id == uuid.UUID(scan_id)).first()
        if not scan:
            return

        pdf_bytes = _build_pdf(scan)
        pdf_key = f"reports/{scan.id}_forensic.pdf"
        upload_bytes(pdf_bytes, pdf_key, "application/pdf")

        url = presigned_url(pdf_key, expires_in=86400)

        rd = scan.result_data or {}
        rd["forensicPdfUrl"] = url
        scan.result_data = rd
        db.commit()

        send_push(
            scan.user.push_token,
            title="Forensic report ready",
            body=f"Your PDF report for {scan.filename} is ready to download.",
            data={"scanId": str(scan.id), "type": "forensic_pdf"},
        )

    finally:
        db.close()
