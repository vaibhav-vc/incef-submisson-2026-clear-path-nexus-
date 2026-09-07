from __future__ import annotations

import hashlib
import json
from pathlib import Path

from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.shapes import Drawing, Line, Rect, String
from reportlab.lib import colors
from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    HRFlowable,
    KeepTogether,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)


ROOT = Path(__file__).resolve().parents[1]
EXPERIMENTS = ROOT / "submission" / "experiments"
OUTPUT_DIR = ROOT / "output" / "pdf"
OUTPUT_PATH = OUTPUT_DIR / "EvidenceGate_INSEF_2026_27_Final_Report.pdf"

NAVY = HexColor("#10233F")
BLUE = HexColor("#176B87")
TEAL = HexColor("#1B9AAA")
SAFFRON = HexColor("#F2A900")
INK = HexColor("#182230")
MUTED = HexColor("#5B6778")
PALE = HexColor("#EEF4F7")
GREEN = HexColor("#16825D")
RED = HexColor("#B42318")
WHITE = colors.white


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def register_fonts() -> tuple[str, str, str]:
    """Embed readable fonts when available so PDF viewers do not need fallbacks."""
    font_sets = [
        (
            Path("C:/Windows/Fonts/arial.ttf"),
            Path("C:/Windows/Fonts/arialbd.ttf"),
            Path("C:/Windows/Fonts/cour.ttf"),
        ),
        (
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"),
        ),
    ]
    for regular_path, bold_path, mono_path in font_sets:
        if regular_path.is_file() and bold_path.is_file() and mono_path.is_file():
            pdfmetrics.registerFont(TTFont("EvidenceGateSans", str(regular_path)))
            pdfmetrics.registerFont(TTFont("EvidenceGateSansBold", str(bold_path)))
            pdfmetrics.registerFont(TTFont("EvidenceGateMono", str(mono_path)))
            return "EvidenceGateSans", "EvidenceGateSansBold", "EvidenceGateMono"
    return "Helvetica", "Helvetica-Bold", "Courier"


BODY_FONT, BOLD_FONT, MONO_FONT = register_fonts()


def styles():
    sheet = getSampleStyleSheet()
    return {
        "body": ParagraphStyle(
            "Body",
            parent=sheet["BodyText"],
            fontName=BODY_FONT,
            fontSize=10.3,
            leading=14.2,
            textColor=INK,
            spaceAfter=6,
        ),
        "small": ParagraphStyle(
            "Small",
            parent=sheet["BodyText"],
            fontName=BODY_FONT,
            fontSize=8.3,
            leading=11.0,
            textColor=MUTED,
            spaceAfter=3,
        ),
        "h1": ParagraphStyle(
            "Heading1Custom",
            parent=sheet["Heading1"],
            fontName=BOLD_FONT,
            fontSize=18.5,
            leading=22,
            textColor=NAVY,
            spaceBefore=6,
            spaceAfter=9,
            keepWithNext=True,
        ),
        "h2": ParagraphStyle(
            "Heading2Custom",
            parent=sheet["Heading2"],
            fontName=BOLD_FONT,
            fontSize=13.2,
            leading=16.5,
            textColor=BLUE,
            spaceBefore=8,
            spaceAfter=5,
            keepWithNext=True,
        ),
        "kicker": ParagraphStyle(
            "Kicker",
            parent=sheet["BodyText"],
            fontName=BOLD_FONT,
            fontSize=8.5,
            leading=10.5,
            textColor=TEAL,
            uppercase=True,
            spaceAfter=4,
        ),
        "title": ParagraphStyle(
            "CoverTitle",
            parent=sheet["Title"],
            fontName=BOLD_FONT,
            fontSize=28,
            leading=31,
            textColor=WHITE,
            alignment=TA_LEFT,
            spaceAfter=10,
        ),
        "subtitle": ParagraphStyle(
            "CoverSubtitle",
            parent=sheet["BodyText"],
            fontName=BODY_FONT,
            fontSize=13,
            leading=17,
            textColor=HexColor("#D7E7EF"),
            spaceAfter=12,
        ),
        "callout": ParagraphStyle(
            "Callout",
            parent=sheet["BodyText"],
            fontName=BOLD_FONT,
            fontSize=10.5,
            leading=14.8,
            textColor=NAVY,
            borderColor=TEAL,
            borderWidth=1,
            borderPadding=8,
            backColor=PALE,
            # Paragraph borders extend outside the layout box by borderPadding.
            # Reserve that padding so callouts cannot strike through headings.
            spaceBefore=14,
            spaceAfter=16,
        ),
        "table": ParagraphStyle(
            "TableText",
            parent=sheet["BodyText"],
            fontName=BODY_FONT,
            fontSize=8.0,
            leading=10.2,
            textColor=INK,
        ),
        "table_bold": ParagraphStyle(
            "TableBold",
            parent=sheet["BodyText"],
            fontName=BOLD_FONT,
            fontSize=8.0,
            leading=10.2,
            textColor=WHITE,
            alignment=TA_CENTER,
        ),
        "center_small": ParagraphStyle(
            "CenterSmall",
            parent=sheet["BodyText"],
            fontName=BODY_FONT,
            fontSize=8.5,
            leading=10.8,
            textColor=MUTED,
            alignment=TA_CENTER,
        ),
    }


S = styles()


def P(text: str, style: str = "body") -> Paragraph:
    return Paragraph(text, S[style])


def bullet_list(items: list[str]) -> Table:
    """Render ASCII bullets without relying on unavailable PDF symbol fonts."""
    rows = [[P("-", "body"), P(item, "body")] for item in items]
    table = Table(rows, colWidths=[5 * mm, 160 * mm], hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 2),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    return table


def data_table(rows: list[list[object]], widths: list[float], header: bool = True) -> Table:
    converted = []
    for row_index, row in enumerate(rows):
        converted.append(
            [
                P(str(value), "table_bold" if header and row_index == 0 else "table")
                for value in row
            ]
        )
    table = Table(converted, colWidths=widths, repeatRows=1 if header else 0, hAlign="LEFT")
    style = [
        ("GRID", (0, 0), (-1, -1), 0.4, HexColor("#CBD5E1")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]
    if header:
        style.extend(
            [
                ("BACKGROUND", (0, 0), (-1, 0), NAVY),
                ("ALIGN", (0, 0), (-1, 0), "CENTER"),
            ]
        )
    for row_index in range(1 if header else 0, len(rows)):
        if row_index % 2 == 0:
            style.append(("BACKGROUND", (0, row_index), (-1, row_index), HexColor("#F7FAFC")))
    table.setStyle(TableStyle(style))
    return table


def result_chart(scenarios: list[dict[str, object]]) -> Drawing:
    drawing = Drawing(470, 205)
    chart = VerticalBarChart()
    chart.x = 35
    chart.y = 38
    chart.height = 135
    chart.width = 405
    values = []
    colors_by_state = []
    labels = []
    for index, item in enumerate(scenarios):
        values.append(int(item["passed"]))
        state = next(iter(item["actual_states"]))
        colors_by_state.append(GREEN if state == "READY" else RED if state == "HARD_BLOCKED" else SAFFRON)
        labels.append(f"S{index + 1}")
    chart.data = [values]
    chart.categoryAxis.categoryNames = labels
    chart.categoryAxis.labels.fontName = BODY_FONT
    chart.categoryAxis.labels.fontSize = 8
    chart.valueAxis.valueMin = 0
    chart.valueAxis.valueMax = 200
    chart.valueAxis.valueStep = 50
    chart.valueAxis.labels.fontName = BODY_FONT
    chart.valueAxis.labels.fontSize = 7
    chart.barWidth = 24
    chart.groupSpacing = 9
    for index, color in enumerate(colors_by_state):
        chart.bars[0, index].fillColor = color
    drawing.add(chart)
    drawing.add(String(235, 188, "Expected-state agreement by scenario (n = 200 each)", textAnchor="middle", fontName=BOLD_FONT, fontSize=10, fillColor=NAVY))
    drawing.add(String(235, 9, "S1 baseline; S2-S8 controlled adverse conditions", textAnchor="middle", fontName=BODY_FONT, fontSize=7.5, fillColor=MUTED))
    return drawing


def architecture_drawing() -> Drawing:
    drawing = Drawing(470, 145)
    boxes = [
        (5, "Live + operator\ninputs", TEAL),
        (100, "Schema + time\nvalidation", BLUE),
        (195, "Clearance +\nscoring", NAVY),
        (290, "Signed SourceLine\nevidence", BLUE),
        (385, "EvidenceGate\ndecision", GREEN),
    ]
    for x, label, fill in boxes:
        drawing.add(Rect(x, 55, 80, 48, rx=7, ry=7, fillColor=fill, strokeColor=fill))
        lines = label.split("\n")
        drawing.add(String(x + 40, 82, lines[0], textAnchor="middle", fontName=BOLD_FONT, fontSize=7.5, fillColor=WHITE))
        drawing.add(String(x + 40, 69, lines[1], textAnchor="middle", fontName=BODY_FONT, fontSize=7, fillColor=WHITE))
        if x < 385:
            drawing.add(Line(x + 82, 79, x + 96, 79, strokeColor=MUTED))
            drawing.add(Line(x + 92, 83, x + 96, 79, strokeColor=MUTED))
            drawing.add(Line(x + 92, 75, x + 96, 79, strokeColor=MUTED))
    drawing.add(String(235, 126, "EvidenceGate decision-support pipeline", textAnchor="middle", fontName=BOLD_FONT, fontSize=11, fillColor=NAVY))
    drawing.add(String(235, 25, "READY only when required evidence is current and verifiable; otherwise HOLD, UNAVAILABLE or HARD_BLOCKED", textAnchor="middle", fontName=BODY_FONT, fontSize=7.4, fillColor=MUTED))
    return drawing


def header_footer(canvas_obj: canvas.Canvas, doc):
    canvas_obj.saveState()
    page_number = canvas_obj.getPageNumber()
    if page_number > 1:
        canvas_obj.setFillColor(NAVY)
        canvas_obj.rect(0, A4[1] - 15 * mm, A4[0], 15 * mm, fill=1, stroke=0)
        canvas_obj.setFillColor(WHITE)
        canvas_obj.setFont(BOLD_FONT, 8)
        canvas_obj.drawString(18 * mm, A4[1] - 9.5 * mm, "EVIDENCEGATE | INSEF 2026-27 PROJECT REPORT")
        canvas_obj.setStrokeColor(TEAL)
        canvas_obj.setLineWidth(1.2)
        canvas_obj.line(18 * mm, 17 * mm, A4[0] - 18 * mm, 17 * mm)
    canvas_obj.setFillColor(MUTED)
    canvas_obj.setFont(BODY_FONT, 8)
    canvas_obj.drawRightString(A4[0] - 18 * mm, 12 * mm, f"Page {page_number}")
    canvas_obj.restoreState()


def add_cover(story, executed_at: str):
    cover = Table(
        [[P("INSEF 2026-27 | COMPUTER SCIENCE & ENGINEERING", "kicker")],
         [P("EvidenceGate", "title")],
         [P("A fail-closed evidence integrity system for live multimodal rail-port decision support", "subtitle")],
         [P("WORKING SOFTWARE PROTOTYPE + REPRODUCIBLE EXPERIMENT", "kicker")]],
        colWidths=[A4[0] - 36 * mm],
        rowHeights=[18 * mm, 28 * mm, 31 * mm, 16 * mm],
    )
    cover.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), NAVY),
                ("LEFTPADDING", (0, 0), (-1, -1), 18),
                ("RIGHTPADDING", (0, 0), (-1, -1), 18),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )
    story.extend([Spacer(1, 18 * mm), cover, Spacer(1, 10 * mm)])
    metrics = Table(
        [
            [P("1,600", "h1"), P("100%", "h1"), P("0", "h1")],
            [P("controlled trials", "center_small"), P("expected-state agreement", "center_small"), P("false READY outcomes in adverse trials", "center_small")],
        ],
        colWidths=[55 * mm, 55 * mm, 55 * mm],
    )
    metrics.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), PALE),
                ("BOX", (0, 0), (-1, -1), 0.8, TEAL),
                ("INNERGRID", (0, 0), (-1, -1), 0.4, HexColor("#B8D8E2")),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )
    story.extend([metrics, Spacer(1, 13 * mm)])
    story.append(
        data_table(
            [
                ["Submission field", "Complete before upload"],
                ["Student 1", "Name: ____________________ | Grade: ______"],
                ["Student 2 (optional)", "Name: ____________________ | Grade: ______"],
                ["School", "School / City / State: ______________________________"],
                ["Guide", "Name / Role: _______________________________________"],
                ["Experiment executed", executed_at.replace("T", " ").replace("+00:00", " UTC")],
            ],
            [48 * mm, 117 * mm],
        )
    )
    story.extend(
        [
            Spacer(1, 7 * mm),
            P("Scientific integrity note", "h2"),
            P(
                "This report contains measured software-validation data generated from the included scripts. It does not claim railway field validation, safety certification, authenticated freight telemetry or port-authority testing. Students should rerun and understand every experiment before submission.",
                "callout",
            ),
            PageBreak(),
        ]
    )


def build_report():
    evidence_summary_path = EXPERIMENTS / "evidencegate_experimental_summary.json"
    provider_summary_path = EXPERIMENTS / "live_provider_summary.json"
    evidence_csv_path = EXPERIMENTS / "evidencegate_experimental_results.csv"
    provider_csv_path = EXPERIMENTS / "live_provider_observations.csv"
    evidence = json.loads(evidence_summary_path.read_text(encoding="utf-8"))
    providers = json.loads(provider_summary_path.read_text(encoding="utf-8"))
    release_hashes = (ROOT / "release" / "SHA256SUMS.txt").read_text(encoding="utf-8").strip()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    doc = BaseDocTemplate(
        str(OUTPUT_PATH),
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=22 * mm,
        bottomMargin=22 * mm,
        title="EvidenceGate INSEF 2026-27 Final Project Report",
        author="EvidenceGate student project team",
        creator="EvidenceGate reproducible report builder",
        subject="Reproducible software engineering experiment and working prototype report",
    )
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="normal")
    doc.addPageTemplates([PageTemplate(id="report", frames=frame, onPage=header_footer)])
    story = []
    add_cover(story, evidence["executed_at_utc"])

    story.extend(
        [
            P("Abstract", "h1"),
            P(
                "EvidenceGate is a working decision-support prototype designed to prevent unsupported rail-port logistics decisions from appearing operationally ready. The system binds route decisions to source identity, observation time, freshness, required evidence roles, checksums, HMAC-signed lineage and human approval. A controlled experiment executed 1,600 trials across eight scenarios. All 200 complete baselines returned READY; all 1,400 adverse trials returned HOLD or HARD_BLOCKED as specified. The adverse-case false-READY count was 0. A separate short live-provider observation made ten public API requests: five to Open-Meteo for Mumbai weather and five to NOAA SWPC for planetary Kp data. All ten returned HTTP 200 with the required schema. These results demonstrate deterministic fail-closed behavior under the tested software conditions, but do not establish railway safety, long-term provider uptime or real freight-field performance.",
            ),
            P("Keywords", "h2"),
            P("evidence integrity; fail-closed software; data provenance; freshness; logistics; railway-port coordination; reproducible experiment"),
            P("Original contribution", "h2"),
            bullet_list(
                [
                    "A four-state evidence decision model: READY, HOLD, UNAVAILABLE and HARD_BLOCKED.",
                    "A signed SourceLine record binding decision inputs, timestamps, transformations and data-source identity.",
                    "Atomic multi-leg journey dispatch after fresh evidence verification and human approval.",
                    "Truthful provider degradation: missing or malformed live data is shown as unavailable rather than replaced by a convincing fixed value.",
                ]
            ),
            P("INSEF fit", "h2"),
            P(
                "The current INSEF 2026-27 page accepts practical engineering or research projects in Computer Science & Engineering and Technology, for Grades 5-12 with up to two participants. It asks for a PDF containing project details and a project-demonstration video URL. This document supplies the technical PDF component; student identity and the final video URL must still be added during submission.",
            ),
            PageBreak(),
            P("1. Problem statement and research question", "h1"),
            P(
                "Logistics dashboards often combine weather, port schedules, congestion estimates, engineering limits and operator declarations. If one source is stale, missing or silently replaced with a fixed fallback, a polished interface can communicate more certainty than the evidence supports. The engineering problem is therefore not only route calculation; it is preventing a result from being treated as dispatch-ready when its evidence cannot be verified.",
            ),
            P("Research question", "h2"),
            P(
                "Can a software evidence gate accept a complete, current and integrity-valid decision while consistently refusing decisions whose evidence is missing, stale, future-dated, seeded, hard-blocked or altered after signing?",
                "callout",
            ),
            P("Hypotheses", "h2"),
            bullet_list(
                [
                    "H1: Complete baseline evidence will produce READY in every controlled trial.",
                    "H2: Every tested adverse condition will prevent READY.",
                    "H3: Post-signing modifications to snapshot or record trust fields will invalidate the signed root and produce HOLD.",
                    "H4: Decision-gate evaluation will remain below 10 ms p95 on the test computer for these in-memory records.",
                ]
            ),
            P("Engineering objectives", "h2"),
            bullet_list(
                [
                    "Remove operationally deceptive hardcoded live values and expose unavailable states.",
                    "Validate provider schemas, observation timestamps, ranges and authorization contracts.",
                    "Require certified engineering imports before static corridor limits can support READY.",
                    "Bind schedules and approval receipts to the exact sealed evidence used for evaluation.",
                    "Produce an incident-ready evidence kit with reproducible checksums and signer metadata.",
                ]
            ),
            PageBreak(),
            P("2. Prototype architecture", "h1"),
            architecture_drawing(),
            P("Decision-state rules", "h2"),
            data_table(
                [
                    ["State", "Meaning", "Operational interpretation"],
                    ["READY", "Required evidence is available, current and integrity-valid.", "Eligible for authorized approval and dispatch."],
                    ["HOLD", "Evidence exists but is stale, incomplete, untrusted or changed.", "Re-evaluate or repair evidence; do not dispatch."],
                    ["UNAVAILABLE", "Required evidence or a signed snapshot is absent.", "No decision can be made."],
                    ["HARD_BLOCKED", "Physical clearance or another absolute rule failed.", "Numeric scores cannot override the block."],
                ],
                [23 * mm, 67 * mm, 75 * mm],
            ),
            P("Live-data design", "h2"),
            P(
                "Open-Meteo supplies public weather when no OpenWeather key is configured. NOAA SWPC supplies planetary Kp observations. Authorized railway and maritime adapters require configured endpoints and bearer credentials. Their payloads must include bounded numeric values and timezone-aware observation timestamps. Configuration or provider failure produces UNAVAILABLE; it does not fall back to a passenger feed or fixed port window for operational scoring.",
            ),
            P("Evidence integrity", "h2"),
            P(
                "Each decision stores normalized records with source type, availability, observed and fetched times, freshness, value checksum and a checksum of the complete trust envelope. The snapshot and lineage graph are hashed into an evidence root and signed using HMAC-SHA256 with a key identifier. Verification uses the key identifier stored with the snapshot, permitting controlled key rotation while unknown historical signers fail closed.",
            ),
            P("Scope boundary", "h2"),
            P(
                "EvidenceGate is a research and decision-support prototype. It does not control trains, signalling, interlocking, braking, Kavach/ATP, port equipment or customs systems. Operational use would require railway and port authority integration, certified engineering datasets, cybersecurity review and regulatory approval.",
                "callout",
            ),
            PageBreak(),
            P("3. Experimental method", "h1"),
            P("Independent variable", "h2"),
            P(
                "The evidence condition was varied across eight controlled scenarios. Each scenario was executed 200 times with deterministic unique identifiers. The decision snapshot contained five required roles: clearance, weather, port alignment, congestion and historical delay.",
            ),
            P("Dependent variables", "h2"),
            bullet_list(
                [
                    "Decision state returned by EvidenceGate.",
                    "Agreement between expected and actual state.",
                    "Evaluation latency measured with a monotonic high-resolution timer.",
                    "Reason codes identifying why a decision was held or blocked.",
                ]
            ),
            P("Controls", "h2"),
            bullet_list(
                [
                    "Same EvidenceGate 6.0.0 implementation and evidence-role set in all trials.",
                    "Same cargo, route summary, weights and expected reliability score.",
                    "Fixed experiment seed 20260831 and deterministic UUID generation.",
                    "A process-local experiment-only HMAC key; no production secret was used or written to the results.",
                    "Single computer and Python process to reduce environmental variation.",
                ]
            ),
            P("Scenario matrix", "h2"),
            data_table(
                [
                    ["ID", "Condition introduced", "Expected"],
                    ["S1", "Complete, fresh, signed baseline", "READY"],
                    ["S2", "Snapshot timestamp changed after sealing", "HOLD"],
                    ["S3", "Record source type changed after sealing", "HOLD"],
                    ["S4", "Weather decision role removed", "HOLD"],
                    ["S5", "Weather observation two hours old", "HOLD"],
                    ["S6", "Weather observation one hour in the future", "HOLD"],
                    ["S7", "Clearance evidence labelled seeded baseline", "HOLD"],
                    ["S8", "Physical clearance state hard-blocked", "HARD_BLOCKED"],
                ],
                [16 * mm, 108 * mm, 41 * mm],
            ),
            P("Live-provider observation", "h2"),
            P(
                "Five sequential requests were made to each public provider from the same machine. Open-Meteo was queried at Mumbai coordinates 19.0760, 72.8777. A response counted as valid only if every scoring field was present. The NOAA response counted as valid only if the latest object row contained a timestamp and a numeric Kp value from 0 to 9. This is a short functionality check, not an uptime study.",
            ),
            PageBreak(),
            P("4. Results", "h1"),
            result_chart(evidence["scenarios"]),
            P("Table 1. EvidenceGate controlled experiment", "small"),
            data_table(
                [["Scenario", "Actual state", "Pass", "Rate", "Mean ms", "p95 ms"]]
                + [
                    [
                        f"S{index + 1} {item['scenario'].replace('_', ' ')}",
                        ", ".join(f"{key}: {value}" for key, value in item["actual_states"].items()),
                        item["passed"],
                        f"{item['pass_rate_pct']:.2f}%",
                        f"{item['latency_ms_mean']:.3f}",
                        f"{item['latency_ms_p95']:.3f}",
                    ]
                    for index, item in enumerate(evidence["scenarios"])
                ],
                [52 * mm, 39 * mm, 17 * mm, 18 * mm, 19 * mm, 20 * mm],
            ),
            Spacer(1, 5 * mm),
            P(
                f"All {evidence['total_trials']:,} trials matched their specified expected state. Baseline acceptance was 200/200. Across the 1,400 adverse trials, false READY outcomes were 0. The largest measured p95 decision-gate latency was {max(item['latency_ms_p95'] for item in evidence['scenarios']):.3f} ms, supporting H4 on this machine and dataset.",
                "callout",
            ),
            P("Interpretation", "h2"),
            P(
                "H1-H4 were supported under the controlled conditions. Post-signing trust changes were detected by record-envelope and evidence-root verification. Missing and temporally invalid evidence produced HOLD. Seeded clearance could not qualify a route as READY. HARD_BLOCKED retained absolute precedence rather than being averaged away by a numerical reliability score.",
            ),
            PageBreak(),
            P("5. Live-provider and system verification results", "h1"),
            P("Table 2. Public-provider observations", "small"),
            data_table(
                [["Provider", "Requests", "HTTP 200", "Schema valid", "Availability*", "Mean ms", "p95 ms"]]
                + [
                    [
                        item["provider"],
                        item["requests"],
                        item["http_200"],
                        item["schema_valid"],
                        f"{item['availability_pct']:.1f}%",
                        f"{item['latency_ms_mean']:.1f}",
                        f"{item['latency_ms_p95']:.1f}",
                    ]
                    for item in providers["providers"]
                ],
                [35 * mm, 21 * mm, 22 * mm, 26 * mm, 25 * mm, 18 * mm, 18 * mm],
            ),
            P("*Availability is limited to this five-request observation window and must not be interpreted as a long-term service-level estimate.", "small"),
            P("Observed result", "h2"),
            P(
                "All five Open-Meteo requests returned HTTP 200 and the required weather fields. All five NOAA SWPC requests returned HTTP 200 with a valid latest timestamp and Kp value. During fact-checking, NOAA's current object-row timestamp format was reproduced and the parser was updated to canonical UTC; a regression test now covers that format.",
            ),
            P("System release gate", "h2"),
            data_table(
                [
                    ["Verification", "Measured result"],
                    ["Backend automated suite", "215 tests passed; repeated full gate"],
                    ["Backend static checks", "Ruff and compileall passed; Alembic head 20260831_14"],
                    ["API contract", "OpenAPI 6.0.0 exported; 58 paths"],
                    ["Web client", "Type-check and lint passed; 197 modules built"],
                    ["Web dependency audit", "No known production vulnerabilities reported"],
                    ["Android client", "Unit tests, debug APK assembly and lint passed; 53 Gradle tasks"],
                    ["Release integrity", "APK, web and source archives independently matched SHA-256 manifest"],
                ],
                [53 * mm, 112 * mm],
            ),
            P("Unconfigured integrations", "h2"),
            P(
                "Supabase, authenticated freight rail, maritime berth, database and production evidence-signing credentials were not present in the execution environment. Therefore they were contract-tested with controlled payloads but not claimed as live production connections. The released software reports their absence explicitly and blocks READY where required.",
                "callout",
            ),
            PageBreak(),
            P("6. Discussion", "h1"),
            P(
                "The experiment supports the central engineering claim: the prototype distinguishes a technically computed score from an evidence-qualified decision. A route can have a numerical score and still remain HOLD when a required input is stale or untrusted. This reduces the risk that interface polish or a plausible fallback value will be mistaken for operational evidence.",
            ),
            P("Why the signed evidence root matters", "h2"),
            P(
                "Checksumming only the displayed result would not protect source labels, observation time, transformation metadata or the decision graph. EvidenceGate includes these trust fields in record envelopes and includes the snapshot, record checksums and lineage edges in the signed root. The S2 and S3 trials show that changing a timestamp or source classification after sealing prevents READY.",
            ),
            P("Why fail-closed behavior matters", "h2"),
            P(
                "In a demo-oriented system, missing provider data is often replaced with a fixed number so the interface remains attractive. That behavior hides uncertainty. EvidenceGate instead communicates uncertainty as an operational state. This does not solve provider availability, but it prevents the software from silently converting absence into confidence.",
            ),
            P("Novelty and practical application", "h2"),
            bullet_list(
                [
                    "Combines temporal freshness, provenance integrity and human approval in one dispatch gate.",
                    "Makes provenance inspectable as a downloadable incident evidence kit rather than an internal log only.",
                    "Applies atomic dispatch to multi-leg journeys so a waypoint chain is not partially dispatched through the main clients.",
                    "Separates public environmental feeds, authorized enterprise feeds, certified imports, operator declarations and seeded baselines in the decision record.",
                ]
            ),
            P("Threats to validity", "h2"),
            bullet_list(
                [
                    "The 200 repetitions per scenario exercise deterministic code with different identifiers; they are useful for consistency and latency observations but are not independent field events.",
                    "The adverse scenarios are selected tests, not an exhaustive proof against all implementation or cybersecurity failures.",
                    "The live-provider window is too short to estimate uptime, seasonal behavior or rate-limit performance.",
                    "The experiment validates evidence-gate logic, not the accuracy of railway clearance limits, freight congestion or berth predictions.",
                ]
            ),
            PageBreak(),
            P("7. Safety, ethics and data integrity", "h1"),
            P("No fabricated evidence", "h2"),
            P(
                "No railway or maritime observation was invented to complete the report. Missing credentials are recorded as a limitation. Seeded engineering baselines remain labelled and are prevented from qualifying critical clearance as READY. Operator berth windows require a document reference and SHA-256 digest so the declaration is bound into the signed evidence.",
            ),
            P("Human responsibility", "h2"),
            P(
                "READY is not an autonomous authorization. The backend requires an authenticated operator, approver or administrator role and stores an approval receipt bound to the current evidence root. Any evidence-root change invalidates the old approval. This supports accountability but does not replace organizational procedures or legal authority.",
            ),
            P("Cybersecurity boundary", "h2"),
            P(
                "The prototype uses bearer-authenticated provider contracts, Supabase session verification, dedicated evidence-signing keys and retained verification-only keys for rotation. Production deployment still requires secret management, penetration testing, least-privilege network policy, audit retention, backups and incident-response exercises.",
            ),
            P("Responsible presentation", "h2"),
            P(
                "During judging, the prototype should be described as an evidence-integrity and decision-support system. It should not be described as an official Indian Railways dispatch system, a certified safety product, or a replacement for port, customs or railway authorities.",
                "callout",
            ),
            P("Student declaration before submission", "h2"),
            bullet_list(
                [
                    "Rerun both experiment scripts and retain the newly generated CSV and JSON files.",
                    "Understand and be able to explain every scenario, metric, limitation and code path shown in the demonstration.",
                    "Complete the cover identity lines with accurate participant, grade, school and guide information.",
                    "Add the final demonstration video URL to the submission form; do not insert a non-working link in this report.",
                    "Disclose any mentor or AI assistance according to school and fair requirements.",
                ]
            ),
            PageBreak(),
            P("8. Conclusion and future work", "h1"),
            P(
                "EvidenceGate 6.0.0 achieved 100% expected-state agreement across 1,600 controlled trials, with no false READY result in 1,400 adverse trials. The original public-provider check successfully validated five Open-Meteo and five NOAA SWPC responses during the 31 August 2026 observation window. These results support the prototype's fail-closed software behavior under the tested conditions.",
            ),
            P(
                "Later verification, 7 September 2026: a separate controlled rerun again passed all 1,600 cases. NOAA returned five valid responses, but all five Open-Meteo requests timed out from the test host. These later observations are preserved separately under submission/experiments/runs and do not replace the original study data. Live availability is not guaranteed.",
                "small",
            ),
            P(
                "The experiment does not establish real-world railway safety or live freight-port accuracy. The next phase is field validation with authorized partners and certified data, followed by longer-duration provider monitoring and human-factors testing with intended operators.",
            ),
            P("Planned next experiments", "h2"),
            data_table(
                [
                    ["Experiment", "Required input", "Primary metric"],
                    ["Certified clearance replay", "Authority-approved segment limits", "False-accept and false-block rate"],
                    ["Freight feed endurance", "Authorized railway operations API", "Availability, freshness and latency over 30 days"],
                    ["Berth alignment validation", "Port-authority schedules and actual events", "Arrival-window error and missed-window rate"],
                    ["Operator usability", "Consent-based participant study", "Decision time, comprehension and unsafe-action prevention"],
                    ["Security assessment", "Independent test environment", "Tamper, authorization and key-rotation findings"],
                ],
                [50 * mm, 63 * mm, 52 * mm],
            ),
            P("Final claim", "h2"),
            P(
                "EvidenceGate is a reproducibly tested software prototype that blocks unsupported readiness under the tested conditions. A live demonstration requires deployed services, real client configuration and device testing. Field validation and production railway certification remain outside these experimental results.",
                "callout",
            ),
            PageBreak(),
            P("Appendix A. Reproducibility and raw evidence", "h1"),
            P("Included experiment files", "h2"),
            data_table(
                [
                    ["File", "Purpose", "SHA-256"],
                    ["run_evidencegate_experiment.py", "Controlled 1,600-trial experiment", file_sha256(EXPERIMENTS / "run_evidencegate_experiment.py")],
                    ["evidencegate_experimental_results.csv", "Raw trial-level observations", file_sha256(evidence_csv_path)],
                    ["evidencegate_experimental_summary.json", "Aggregate results and environment", file_sha256(evidence_summary_path)],
                    ["run_live_provider_observations.py", "Public-provider observation script", file_sha256(EXPERIMENTS / "run_live_provider_observations.py")],
                    ["live_provider_observations.csv", "Raw provider observations", file_sha256(provider_csv_path)],
                    ["live_provider_summary.json", "Provider aggregates and limitations", file_sha256(provider_summary_path)],
                ],
                [49 * mm, 58 * mm, 58 * mm],
            ),
            P("Repeat procedure", "h2"),
            bullet_list(
                [
                    "Open PowerShell in the repository's backend directory.",
                    "Set PYTHONPATH to a single dot for the current backend directory.",
                    "Run .venv\\Scripts\\python.exe ..\\submission\\experiments\\run_evidencegate_experiment.py.",
                    "Run .venv\\Scripts\\python.exe ..\\submission\\experiments\\run_live_provider_observations.py while connected to the internet.",
                    "Compare the new aggregate state counts; provider latencies and observation values may legitimately differ.",
                    "Run the full backend, web and Android verification commands documented in the repository before packaging.",
                ]
            ),
            P("Release SHA-256 manifest", "h2"),
            P(f"<font name='{MONO_FONT}'>" + release_hashes.replace("&", "&amp;").replace("\n", "<br/>") + "</font>", "small"),
            PageBreak(),
            P("Appendix B. References and INSEF upload checklist", "h1"),
            P("References", "h2"),
            bullet_list(
                [
                    "Science Society of India. INSEF 2026-27 Project Submission. https://insef.org/insef/ (accessed 31 August 2026).",
                    "Open-Meteo. Weather Forecast API documentation. https://open-meteo.com/en/docs (accessed 31 August 2026).",
                    "NOAA Space Weather Prediction Center. Planetary K-index product feed. https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json (accessed 31 August 2026).",
                    "Krawczyk, H., Bellare, M., and Canetti, R. HMAC: Keyed-Hashing for Message Authentication. RFC 2104, 1997. https://www.rfc-editor.org/rfc/rfc2104",
                    "EvidenceGate 6.0.0 source, evidence policy, deployment guide and experiment package included with this submission build.",
                ]
            ),
            P("Current INSEF upload checklist", "h2"),
            data_table(
                [
                    ["Item", "Status before upload"],
                    ["Eligible participant grade and category", "Confirm Grade 5-12 and Junior/Senior rules"],
                    ["Maximum team size", "Confirm one or two participants"],
                    ["Student, school and guide identities", "Complete the cover-page identity lines"],
                    ["Project PDF", "This visually verified report"],
                    ["Working demonstration", "APK/web/source package available"],
                    ["Demonstration video URL", "Record, upload and test access"],
                    ["Original logbook/raw data", "Retain CSV, JSON, hashes and rerun notes"],
                    ["Regional submission", "Submit to one region only by the current official deadline"],
                    ["Safety and assistance disclosures", "Complete accurately with school/organizer guidance"],
                ],
                [68 * mm, 97 * mm],
            ),
            Spacer(1, 7 * mm),
            HRFlowable(width="100%", thickness=1.2, color=TEAL),
            Spacer(1, 4 * mm),
            P(
                "Submission note: the official page currently lists 30 September 2026 for regional submissions and 25 October 2026 for Online-India, but participants must recheck the official page immediately before submission because dates and regional arrangements may change.",
                "small",
            ),
        ]
    )
    doc.build(story)
    print(OUTPUT_PATH)


if __name__ == "__main__":
    build_report()
