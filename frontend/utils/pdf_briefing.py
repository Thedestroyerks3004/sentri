from __future__ import annotations

import io
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def generate_briefing_pdf(briefing: dict) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=1.5 * cm, leftMargin=1.5 * cm,
                            topMargin=1.5 * cm, bottomMargin=1.5 * cm)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("Title", parent=styles["Heading1"], fontSize=16, spaceAfter=8)
    section_style = ParagraphStyle("Section", parent=styles["Heading2"], fontSize=12, spaceBefore=12, spaceAfter=6)
    body = styles["Normal"]

    story = [
        Paragraph("SENTRI — Parking Intelligence", title_style),
        Paragraph("DAILY ENFORCEMENT BRIEFING", styles["Heading2"]),
        Paragraph(briefing.get("generated_at", ""), body),
        Spacer(1, 0.3 * cm),
        Paragraph(
            f"<b>TODAY'S CITY RISK LEVEL: {briefing.get('city_risk_level', 'N/A')}</b>",
            body,
        ),
        Spacer(1, 0.5 * cm),
        Paragraph("CITY SNAPSHOT", section_style),
    ]

    snap = briefing.get("snapshot", {})
    snap_data = [
        ["Predicted violations today", str(snap.get("predicted_today", "—"))],
        ["Active hotspots (this hour)", str(snap.get("active_hotspots_now", "—"))],
        ["Repeat offenders flagged (week)", str(snap.get("repeat_offenders_week", "—"))],
        ["Integrity alerts (week)", str(snap.get("integrity_alerts_week", "—"))],
    ]
    t = Table(snap_data, colWidths=[10 * cm, 6 * cm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f1f5f9")),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
    ]))
    story.append(t)

    story.append(Paragraph("TOP 5 PATROL ZONES TODAY", section_style))
    patrol = briefing.get("patrol_zones", [])
    if patrol:
        patrol_rows = [["Rank", "Zone", "Risk", "Peak Window", "Predicted", "Station", "Action"]]
        for p in patrol:
            patrol_rows.append([
                str(p.get("rank", "")),
                str(p.get("zone", ""))[:40],
                str(p.get("risk", "")),
                str(p.get("peak_window", "")),
                str(p.get("predicted_today", "")),
                str(p.get("station", "")),
                str(p.get("action", "")),
            ])
        pt = Table(patrol_rows, repeatRows=1, colWidths=[1 * cm, 4.5 * cm, 2.5 * cm, 2.5 * cm, 1.8 * cm, 2.5 * cm, 3 * cm])
        pt.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e293b")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
        ]))
        story.append(pt)

    story.append(Paragraph("INTEGRITY ALERTS — TOP 5", section_style))
    alerts = briefing.get("integrity_alerts", [])
    if alerts:
        alert_rows = [["Officer ID", "Station", "Anomaly Type", "Severity", "Flagged On"]]
        for a in alerts:
            alert_rows.append([
                str(a.get("officer_id", "")),
                str(a.get("station", "")),
                str(a.get("anomaly_type", "")),
                str(a.get("severity", "")),
                str(a.get("flagged_on", "")),
            ])
        at = Table(alert_rows, repeatRows=1)
        at.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#7f1d1d")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
        ]))
        story.append(at)
    story.append(Paragraph(
        f"Total flagged this period: {briefing.get('integrity_total', 0):,} records.",
        body,
    ))

    story.append(Paragraph("REPEAT OFFENDERS ACTIVE THIS WEEK", section_style))
    repeaters = briefing.get("repeat_offenders_active", [])[:10]
    if repeaters:
        rep_rows = [["Vehicle", "Type", "Violations", "Last Zone", "Stations"]]
        for r in repeaters:
            rep_rows.append([
                str(r.get("vehicle_number", "")),
                str(r.get("vehicle_type", "")),
                str(r.get("violations", "")),
                str(r.get("last_zone", ""))[:35],
                str(r.get("stations", "")),
            ])
        rt = Table(rep_rows, repeatRows=1)
        rt.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e3a5f")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
        ]))
        story.append(rt)

    story.append(Paragraph("STATION PERFORMANCE SNAPSHOT", section_style))
    stations = briefing.get("station_performance", [])[:15]
    if stations:
        st_rows = [["Station", "Filed", "Approved", "Rejected", "Rejection %", "Trend"]]
        for s in stations:
            st_rows.append([
                str(s.get("police_station", "")),
                str(int(s.get("filed", 0))),
                str(int(s.get("approved", 0))),
                str(int(s.get("rejected", 0))),
                f"{s.get('rejection_rate', 0):.1f}%",
                str(s.get("trend", "")),
            ])
        st_t = Table(st_rows, repeatRows=1)
        st_t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#334155")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
        ]))
        story.append(st_t)

    story.append(Spacer(1, 0.5 * cm))
    story.append(Paragraph(
        f"Generated by SENTRI AI — powered by 298,450 violation records. "
        f"Document created {datetime.now().strftime('%Y-%m-%d %H:%M')}.",
        body,
    ))

    doc.build(story)
    buffer.seek(0)
    return buffer.read()
