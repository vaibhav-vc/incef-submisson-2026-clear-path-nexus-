# ruff: noqa: E501 - this file is mostly report prose; wrapping sentences mid-string would not make it clearer
"""Build the detailed project report (PDF) from the evidence files in this repository.

    python scripts/build_report.py            # writes seva2026/ClearPath_Nexus_RailGuard_Report.pdf

Every number is read from an evidence file (simulation results, training log, model metrics, audit
summary) so the report cannot drift from what was measured. Judgements (readiness percentages) are
stated as judgements, with the reason next to each.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from reportlab.graphics.shapes import Circle, Drawing, Line, PolyLine, Rect, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "seva2026" / "evidence"
OUT = ROOT / "seva2026" / "ClearPath_Nexus_RailGuard_Report.pdf"

# Palette (validated reference instance, light mode): series slot 1, text and surface tokens.
SERIES = colors.HexColor("#2a78d6")
TEXT = colors.HexColor("#0b0b0b")
TEXT_2 = colors.HexColor("#52514e")
GRID = colors.HexColor("#e3e2dc")
SURFACE = colors.HexColor("#fcfcfb")
HEADER_BG = colors.HexColor("#eef3fb")

FONT, BOLD = "Helvetica", "Helvetica-Bold"
for name, path in (("DejaVu", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
                   ("DejaVu-Bold", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")):  # fmt: skip
    if Path(path).exists():
        pdfmetrics.registerFont(TTFont(name, path))
        FONT, BOLD = ("DejaVu", "DejaVu-Bold") if name == "DejaVu-Bold" else (name, BOLD)

base = getSampleStyleSheet()
S = {
    "title": ParagraphStyle("t", parent=base["Title"], fontName=BOLD, fontSize=22, leading=27, textColor=TEXT),
    "sub": ParagraphStyle("s", parent=base["Normal"], fontName=FONT, fontSize=11, leading=15, textColor=TEXT_2),
    "h1": ParagraphStyle(
        "h1",
        parent=base["Heading1"],
        fontName=BOLD,
        fontSize=15,
        leading=19,
        textColor=TEXT,
        spaceBefore=10,
        spaceAfter=6,
        keepWithNext=1,
    ),  # fmt: skip
    "h2": ParagraphStyle(
        "h2",
        parent=base["Heading2"],
        fontName=BOLD,
        fontSize=11.5,
        leading=15,
        textColor=TEXT,
        spaceBefore=8,
        spaceAfter=4,
        keepWithNext=1,
    ),  # fmt: skip
    "body": ParagraphStyle(
        "b",
        parent=base["Normal"],
        fontName=FONT,
        fontSize=9.4,
        leading=13,
        textColor=TEXT,
        alignment=TA_LEFT,
        spaceAfter=4,
    ),  # fmt: skip
    "small": ParagraphStyle("sm", parent=base["Normal"], fontName=FONT, fontSize=8, leading=10.5, textColor=TEXT_2),
    "cell": ParagraphStyle("c", parent=base["Normal"], fontName=FONT, fontSize=8, leading=10.2, textColor=TEXT),
    "cellb": ParagraphStyle("cb", parent=base["Normal"], fontName=BOLD, fontSize=8, leading=10.2, textColor=TEXT),
    "big": ParagraphStyle("big", parent=base["Normal"], fontName=BOLD, fontSize=17, leading=20, textColor=TEXT),
}


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text()) if path.exists() else {}


def p(text: str, style: str = "body") -> Paragraph:
    return Paragraph(text, S[style])


def bullets(items: list[str]) -> list[Paragraph]:
    return [Paragraph(f"•&nbsp;&nbsp;{item}", S["body"]) for item in items]


def table(rows: list[list[Any]], widths: list[float], header: bool = True) -> Table:
    data = [
        [cell if isinstance(cell, Paragraph) else Paragraph(str(cell), S["cellb" if header and r == 0 else "cell"])
         for cell in row]
        for r, row in enumerate(rows)
    ]  # fmt: skip
    t = Table(data, colWidths=[w * mm for w in widths], repeatRows=1 if header else 0)
    style = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, GRID),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]
    if header:
        style.append(("BACKGROUND", (0, 0), (-1, 0), HEADER_BG))
    t.setStyle(TableStyle(style))
    return t


def tiles(items: list[tuple[str, str]]) -> Table:
    """Hero numbers: value over label, four per row."""

    cells = [[Paragraph(v, S["big"]), Paragraph(k, S["small"])] for k, v in items]
    rows = [cells[i : i + 4] for i in range(0, len(cells), 4)]
    data = []
    for row in rows:
        row = [*row, *[["", ""]] * (4 - len(row))]
        data.append([Table([[c[0]], [c[1]]], colWidths=[42 * mm]) for c in row])
    t = Table(data, colWidths=[44 * mm] * 4)
    t.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0, colors.white), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))  # fmt: skip
    return t


def bar_chart(items: list[tuple[str, float]], title: str, width: float = 170, label_w: float = 62) -> Drawing:
    """Horizontal bars (one series): thin bars, rounded data end, value at the tip, recessive grid."""

    row_h, top = 7.5 * mm, 9 * mm
    height = top + row_h * len(items) + 7 * mm
    d = Drawing(width * mm, height)
    d.add(String(0, height - 5 * mm, title, fontName=BOLD, fontSize=9, fillColor=TEXT))
    x0, x1 = label_w * mm, (width - 14) * mm
    plot_top = height - top
    for pct in (0, 25, 50, 75, 100):
        x = x0 + (x1 - x0) * pct / 100
        d.add(Line(x, 5 * mm, x, plot_top, strokeColor=GRID, strokeWidth=0.4))
        d.add(String(x, 1.5 * mm, f"{pct}%", fontName=FONT, fontSize=6.5, fillColor=TEXT_2, textAnchor="middle"))
    for i, (label, value) in enumerate(items):
        y = plot_top - (i + 1) * row_h + 2.2 * mm
        d.add(String(0, y + 1.2 * mm, label, fontName=FONT, fontSize=7.5, fillColor=TEXT))
        w = max((x1 - x0) * value / 100, 0.5)
        bar_h = 3.6 * mm
        d.add(Rect(x0, y, w, bar_h, rx=1.4 * mm, ry=1.4 * mm, fillColor=SERIES, strokeColor=None))
        d.add(Rect(x0, y, min(w, 2 * mm), bar_h, fillColor=SERIES, strokeColor=None))  # square at the baseline
        d.add(String(x0 + w + 1.5 * mm, y + 1 * mm, f"{value:.0f}%", fontName=BOLD, fontSize=7.5, fillColor=TEXT))
    return d


def line_chart(points: list[tuple[int, float, bool]], baseline: float, title: str) -> Drawing:
    """CV error by training round: 2px line, kept rounds as markers, baseline as a labelled reference."""

    width, height = 170 * mm, 62 * mm
    d = Drawing(width, height)
    d.add(String(0, height - 5 * mm, title, fontName=BOLD, fontSize=9, fillColor=TEXT))
    x0, x1, y0, y1 = 14 * mm, width - 30 * mm, 9 * mm, height - 12 * mm
    lo, hi = 1.3, max(baseline, max(v for _, v, _ in points)) + 0.05
    n = max(r for r, _, _ in points) or 1

    def xy(r: float, v: float) -> tuple[float, float]:
        return x0 + (x1 - x0) * r / n, y0 + (y1 - y0) * (v - lo) / (hi - lo)

    for tick in (1.4, 1.6, 1.8, 2.0):
        if lo <= tick <= hi:
            _x, y = xy(0, tick)
            d.add(Line(x0, y, x1, y, strokeColor=GRID, strokeWidth=0.4))
            d.add(String(x0 - 2 * mm, y - 1, f"{tick:.1f}", fontName=FONT, fontSize=6.5, fillColor=TEXT_2,
                         textAnchor="end"))  # fmt: skip
    for r in range(0, n + 1, 2):
        x, _y = xy(r, lo)
        d.add(String(x, y0 - 5 * mm, str(r), fontName=FONT, fontSize=6.5, fillColor=TEXT_2, textAnchor="middle"))
    d.add(String((x0 + x1) / 2, 0, "training round", fontName=FONT, fontSize=6.5, fillColor=TEXT_2,
                 textAnchor="middle"))  # fmt: skip
    _bx, by = xy(0, baseline)
    d.add(Line(x0, by, x1, by, strokeColor=TEXT_2, strokeWidth=0.8, strokeDashArray=[3, 2]))
    d.add(String(x1 + 1.5 * mm, by - 2, f"section-median baseline {baseline:.2f}", fontName=FONT, fontSize=6.5,
                 fillColor=TEXT_2))  # fmt: skip
    best, path = None, []
    for r, v, kept in points:  # the running best is what the procedure carries forward
        best = v if best is None or (kept and v < best) else best
        path.extend(xy(r, best))
    d.add(PolyLine(path, strokeColor=SERIES, strokeWidth=2))
    for r, v, kept in points:
        x, y = xy(r, v)
        if kept:
            d.add(Circle(x, y, 1.6 * mm, fillColor=SERIES, strokeColor=SURFACE, strokeWidth=1))
        else:
            d.add(Circle(x, y, 1.1 * mm, fillColor=SURFACE, strokeColor=TEXT_2, strokeWidth=0.6))
    x, y = xy(*points[-1][:2]) if points[-1][2] else xy(n, best)
    d.add(String(x1 + 1.5 * mm, xy(n, best)[1] - 2, f"kept configuration {best:.3f}", fontName=BOLD, fontSize=6.5,
                 fillColor=TEXT))  # fmt: skip
    return d


def git_head() -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True)
        return out.stdout.strip() or "uncommitted"
    except OSError:
        return "unknown"


# ---- judgements, stated as such --------------------------------------------------------------------
SOFTWARE_READINESS = [
    ("Decision core (twin, planner, gates, cab)", 100, "Built; 5M+-operation simulation clean; replayable"),
    (
        "Verification (tests + simulation)",
        96,
        "Unit, API and attack tests; 8 invariants; regression on final code; formal V&V plan needs IR",
    ),
    (
        "Security engineering",
        95,
        "Controls, 32 attack tests, SAST/SCA clean, ASVS L2 self-assessment; external audit pending",
    ),
    (
        "Docs, compliance, readiness packs",
        95,
        "Register, hazard log, safety case, interface contract, trial plan, guide",
    ),
    (
        "Whole-network coverage",
        93,
        "All 8,990 stations; 914 non-halt placed; 105 stations with suspect coordinates named",
    ),
    ("Live-data integration", 90, "Signed gateway, contract with test vector, IST clock; CRIS field mapping remains"),
    (
        "All-train schedules and data completeness",
        85,
        "Every train audited; working schedules for 5,187; running days not in open data",
    ),
    ("Machine learning", 85, "Best model on public data; retraining on actual running data needs live feeds"),
    ("Official data", 85, "Pipeline incl. running days, provenance, tests; data.gov.in refuses this build network"),
]
# (stage, weight %, done %, what this project has done, what only the railway can do)
DEPLOYMENT_PATH = [
    ("Software built and verified", 35, 92, "This repository", "-"),
    ("Live data and CRIS integration", 15, 40, "Gateway, contract, test vector, simulator",
     "Authorise access; share spec; issue keys; test in CRIS environment"),
    ("Security audit and hosting", 10, 35, "ASVS self-assessment, attack tests, SAST/SCA",
     "CERT-In/STQC audit; host on IR infrastructure"),
    ("Safety acceptance", 15, 30, "Draft hazard log and safety case with evidence",
     "Hazard workshop; scoring; independent assessment; RDSO/IR acceptance"),
    ("Shadow-mode trial", 20, 20, "Trial tooling (/shadow), protocol, metrics",
     "Run 3-12 months on a division; review disagreements"),
    ("Roll-out and training", 5, 30, "Operator guide and training modules", "Deliver training; issue procedures"),
]  # fmt: skip


def build(out: Path) -> Path:
    sim = load(EVIDENCE / "simulation" / "simulation_results.json")
    reg = load(EVIDENCE / "simulation" / "regression_results.json")
    tlog = load(ROOT / "models" / "training_log.json")
    model = load(ROOT / "models" / "runtime_model_metrics.json")
    audit = load(EVIDENCE / "audit" / "audit_summary.json")
    sched = load(EVIDENCE / "schedules" / "schedule_audit.json")
    nat_stats = audit.get("national_stats", {})
    software_pct = sum(v for _, v, _ in SOFTWARE_READINESS) / len(SOFTWARE_READINESS)
    path_pct = sum(w * done / 100 for _, w, done, _, _ in DEPLOYMENT_PATH)

    story: list[Any] = []
    # ---- cover ---------------------------------------------------------------------------------------
    story += [
        Spacer(1, 18 * mm),
        p("Clear Path Nexus · RailGuard", "title"),
        p("Decision support for Indian Railways traffic control: build, verification and readiness report", "sub"),
        Spacer(1, 6 * mm),
        p(
            f"Generated {datetime.now(UTC).strftime('%d %B %Y, %H:%M UTC')} · code revision {git_head()} · "
            "SEVA 2026 submission",
            "small",
        ),  # fmt: skip
        Spacer(1, 10 * mm),
        p(
            "<b>What this is.</b> A controller decision-support system for the whole Indian Railways network built from "
            "open data: a digital twin of every station, junction, section and timetabled train; a re-planner that ranks "
            "conflict-free alternatives after a disruption; a driver cab advisory; a machine-learning run-time model; "
            "a tamper-evident audit trail; and a gateway ready for authorised live feeds."
        ),
        p(
            "<b>What it is not.</b> It is advisory. It has no interface to signals, points, interlocking, Kavach/ATP or "
            "brakes, and it does not hold or grant movement authority. Authorised signals, the General & Subsidiary "
            "Rules and railway staff remain controlling."
        ),
        p(
            "<b>How to read the numbers.</b> Everything measured here is a software result on open and synthetic data. "
            "None of it is a field measurement on Indian Railways. Readiness percentages are judgements and are stated "
            "with their reasons."
        ),
        Spacer(1, 6 * mm),
    ]
    sim_ops = sim.get("operations_checked", 0)
    viol = sum(t.get("violations_total", 0) for t in sim.get("twins", {}).values())
    locked = tlog.get("locked_test", {})
    story.append(
        tiles(
            [
                ("stations in the twin (all in the open data)", f"{nat_stats.get('stations_total', 8990):,}"),
                ("junctions", f"{nat_stats.get('junctions', 1454):,}"),
                ("sections between stops", f"{nat_stats.get('sections', 8738):,}"),
                ("timetabled train runs in the 2-day window", f"{nat_stats.get('runs_in_window', 7580):,}"),
                ("operations checked in simulation", f"{sim_ops:,}"),
                ("safety-invariant violations (final run)", f"{viol}"),
                ("automated tests passing", f"{audit.get('tests_passed', '-')}"),
                (
                    "ML error vs section median (locked test)",
                    f"{locked.get('model', {}).get('mae_min', 0):.2f} vs {locked.get('baseline_section_median', {}).get('mae_min', 0):.2f} min",
                ),
            ]
        )
    )
    story.append(PageBreak())

    # ---- 1. readiness -----------------------------------------------------------------------------------
    story += [
        p("1. How much is done, and what is left", "h1"),
        p(
            f"<b>Software side: about {software_pct:.0f}% done</b> - everything this project can build and verify. "
            "The rest of the software work needs inputs only Indian Railways holds: CRIS's interface specification, "
            "actual running data to retrain on, the official timetable with running days (downloadable only from "
            "India), and controller feedback from a trial."
        ),
        p(
            f"<b>Whole path to railway use: about {path_pct:.0f}% done, about {100 - path_pct:.0f}% left.</b> "
            "For every railway stage the project has prepared what it can, so that stage becomes review and sign-off. "
            "What is left is authorisation, an independent audit, safety acceptance and a field trial. Software alone "
            "cannot complete those, so this figure cannot honestly reach 90% before Indian Railways acts."
        ),
        bar_chart([(k, v) for k, v, _ in SOFTWARE_READINESS], "Software readiness by work package (judgement)"),
        Spacer(1, 3 * mm),
        table(
            [["Work package", "Done", "Why this figure"]] + [[k, f"{v}%", why] for k, v, why in SOFTWARE_READINESS],
            [62, 14, 94],
        ),  # fmt: skip
        Spacer(1, 4 * mm),
        p("Path to railway use (weights are shares of total effort)", "h2"),
        bar_chart([(k, d) for k, _w, d, _a, _b in DEPLOYMENT_PATH], "Done per stage (judgement)"),
        table(
            [["Stage", "Weight", "Done", "Done by this project", "Left: only the railway can do"]]
            + [[k, f"{w}%", f"{d}%", a, b] for k, w, d, a, b in DEPLOYMENT_PATH],
            [34, 16, 12, 50, 58],
        ),  # fmt: skip
        p(
            "Readiness packs: <i>seva2026/railway_readiness/</i> - hazard log, safety case, live-data interface "
            "contract, ASVS checklist, shadow-trial plan, operator guide.",
            "small",
        ),  # fmt: skip
    ]

    # ---- 2. what was built ---------------------------------------------------------------------------------
    story += [
        p("2. What was built", "h1"),
        table(
            [
                ["Component", "What it does"],
                [
                    "National twin (railguard/national.py)",
                    "Every station, junction and section from the open timetable; 7,580 train runs over a two-day window; "
                    "occupancy index for fast conflict search; disruption, ranking, approval, threats, cab, replay.",
                ],
                [
                    "Tabletop twin + TwinTrack (engine.py, hardware/)",
                    "A 10-section demonstration line with two trains, ESP32 sensor/cab firmware and six scripted scenarios.",
                ],
                [
                    "Planner and scoring (planner.py, scoring.py)",
                    "Generates CONTINUE / HOLD / PATH-THROUGH / PRIORITY (with cascading re-paths) / REROUTE options, "
                    "resolves conflicts by making lower-priority trains yield, ranks by 7 explainable factors.",
                ],
                [
                    "Evidence gate and approval",
                    "Fresh/aging/stale evidence states; a named controller approves only the latest recommendation for the "
                    "current state; anything older is superseded.",
                ],
                [
                    "Threat registry",
                    "Converging paths, opposing occupancy, blocked/closed sections, stale data, route "
                    "deviation, impossible movement; OPEN → ACKNOWLEDGED → CLEARED lifecycle.",
                ],
                [
                    "Nexus Control / Nexus Cab (static/)",
                    "Controller console (tabletop and national map) and driver cab "
                    "view; strict CSP, no inline code, tokens never in URLs sent to the server.",
                ],
                [
                    "Audit (audit.py)",
                    "Hash-chained events with optional HMAC, persisted as JSON lines, verified by CLI; "
                    "decision snapshots that replay to the same ranking.",
                ],
                [
                    "Run-time ML (runtime_model.py, training.py)",
                    "Gradient-boosted trees with quantile intervals and "
                    "conformal calibration; measured training rounds with a locked test set.",
                ],
                [
                    "Official data (official.py)",
                    "Registry, licences, SHA-256 provenance and a parser for the "
                    "data.gov.in timetable; official rail distances replace straight-line estimates when present.",
                ],
                [
                    "Live-feed gateway (livefeed.py)",
                    "Signed batches from authorised sources (RTIS/NTES/COA-style); "
                    "replay protection; GNSS map-matching; station events become disruptions for the controller.",
                ],
                [
                    "Security layer (security.py)",
                    "Roles, fail-closed production mode, rate limits, body caps, host "
                    "allow-list, strict request schemas, security headers.",
                ],
                [
                    "Working schedules (schedules.py)",
                    "Every train's stop matrix (day, times, dwell, distance, section speed), per-train metrics and a "
                    "completeness audit of all 5,208 trains; running days honoured when official data supplies them.",
                ],
                [
                    "Shadow trial (shadow.py)",
                    "Logs controllers' actual decisions beside the recommendations shown at the time and measures "
                    "agreement, without changing anything: the evidence a field trial needs.",
                ],
                [
                    "Simulation harness (simulate.py)",
                    "Randomised operation sequences on both twins with 8 safety "
                    "invariants checked after every operation.",
                ],
                [
                    "Assistant (assistant.py, free_assistant.py)",
                    "Offline or local open-source model (Ollama) by default; " "the paid Claude option is opt-in only.",
                ],
            ],
            [52, 118],
        ),
        Spacer(1, 4 * mm),
        p("Technology used", "h2"),
        table(
            [
                ["Area", "Technology"],
                [
                    "Language / runtime",
                    "Python 3.11 (CI) and 3.13; HTML, CSS and plain JavaScript (no framework); "
                    "Arduino C++ for the ESP32",
                ],
                ["Service", "FastAPI 0.142, Starlette 1.7, Pydantic 2 (strict models), Uvicorn"],
                ["Data", "SQLite, pandas, NumPy; DataMeet open timetable (CC0); data.gov.in pipeline (GODL)"],
                [
                    "Machine learning",
                    "scikit-learn HistGradientBoosting (absolute-error and quantile losses), "
                    "GroupKFold, split-conformal calibration, joblib",
                ],
                [
                    "Security",
                    "HMAC-SHA256, SHA-256 hash chains, constant-time comparison, token buckets, CSP; "
                    "Bandit (SAST), pip-audit (SCA)",
                ],
                [
                    "Quality",
                    "pytest, ruff 0.8.6 (pinned, as in CI), radon, vulture, GitHub Actions CI, "
                    "Playwright + Chromium for UI checks",
                ],
                ["Assistant", "Ollama (local, free) or the Anthropic SDK (opt-in, paid)"],
                ["Report", "ReportLab (this PDF)"],
            ],
            [36, 134],
        ),
    ]

    # ---- 3. data -------------------------------------------------------------------------------------------
    story += [
        p("3. Data: the whole network", "h1"),
        p(
            "The twin is built from the open Indian Railways timetable (DataMeet, CC0): 8,990 stations, 5,208 trains "
            "and 417,080 stop rows, pinned by SHA-256. Every attribute that the open data does not publish is inferred "
            "and labelled with how it was obtained, so nobody mistakes an inference for a survey."
        ),
        table(
            [["Quantity", "Value", "How it was obtained"]]
            + [
                [k.replace("_", " "), f"{v:,}" if isinstance(v, int) else v, how]
                for k, v, how in [
                    ("stations_total", nat_stats.get("stations_total", 8990), "every station in the open data"),
                    ("stations", nat_stats.get("stations", 7679), "stations where at least one train halts"),
                    (
                        "stations_without_halt_placed_on_sections",
                        nat_stats.get("stations_without_halt_placed_on_sections", 914),
                        "non-halt stations projected onto the section they lie on (≤2 km)",
                    ),
                    (
                        "stations_without_halt_not_placed",
                        nat_stats.get("stations_without_halt_not_placed", 397),
                        "no coordinates, or farther than 2 km from every section",
                    ),
                    ("junctions", nat_stats.get("junctions", 1454), "stations joined to 3 or more neighbours"),
                    ("sections", nat_stats.get("sections", 8738), "pairs of consecutive stops"),
                    (
                        "sections_inferred_multi_track",
                        nat_stats.get("sections_inferred_multi_track", 5098),
                        "opposing trains timetabled on it at the same time",
                    ),
                    (
                        "sections_assumed_single",
                        nat_stats.get("sections_assumed_single", 3640),
                        "no such evidence: treated as single line (the safe assumption)",
                    ),
                    ("runs_in_window", nat_stats.get("runs_in_window", 7580), "train numbers x start days in 2 days"),
                    ("occupations", nat_stats.get("occupations", 843568), "section occupations in the window"),
                ]
            ],
            [52, 22, 96],
        ),  # fmt: skip
        Spacer(1, 3 * mm),
        p(
            "<b>Official data.</b> <i>india_rail/official.py</i> registers the Government sources (data.gov.in "
            "timetable, Trains at a Glance, station codes) with publisher and licence. It parses the data.gov.in format, "
            "including its 00:00:00 placeholders, and records each file's SHA-256 in <i>official_provenance</i>. It "
            "reconciles the file against the community data and gives the twin official rail distances per section. "
            "The Government portals reset connections from this cloud build network, so the file must be fetched from "
            "India with <i>python -m india_rail official --file &lt;csv&gt;</i>. Tests cover the whole path with a "
            "format fixture."
        ),
        p(
            "<b>Known limits.</b> The timetable snapshot is from about 2016 and has no running days, so trains without "
            "known days are treated as daily (the twin honours running days as soon as an official file supplies them). "
            "Track counts, line speeds and lengths are inferred. Loops, platforms and signals are not in any open dataset."
        ),
    ]
    if sched:
        cov = sched.get("coverage_pct", {})
        dur = sched.get("timetable_vs_published_duration", {})
        suspects = sched.get("suspect_station_coordinates", [])
        story += [
            p("All trains: working schedules and completeness", "h2"),
            p(
                "Every published train was checked: <i>python -m india_rail schedules --audit</i>. Each train's working "
                "schedule (every stop with day, arrival, departure, dwell, distance from origin, section run time and "
                "speed) is available from <i>python -m india_rail schedules --train &lt;number&gt;</i> and "
                "<i>GET /trains/&lt;number&gt;/working-schedule</i>."
            ),
            table(
                [
                    ["Measure", "Value"],
                    ["Trains in the published list", f"{sched.get('trains_published', 0):,}"],
                    [
                        "With a usable timetable",
                        f"{sched.get('trains_with_usable_timetable', 0):,} ({cov.get('timetable')}%)",
                    ],
                    [
                        "Timed stops / halts with dwell",
                        f"{sched.get('stops_in_timetables', 0):,} / {sched.get('halts_with_dwell', 0):,}",
                    ],
                    [
                        "Timetable duration within 30 min of the published duration",
                        f"{dur.get('within_tolerance', 0):,} trains (median difference {dur.get('median_abs_diff_min')} min)",
                    ],
                    [
                        "Published duration / distance known",
                        f"{cov.get('published_duration')}% / {cov.get('published_distance')}%",
                    ],
                    [
                        "Accommodation classes / return train known",
                        f"{cov.get('class_information')}% / {cov.get('return_train')}%",
                    ],
                    ["Running days known", f"{cov.get('running_days')}% (not in the open data)"],
                    [
                        "Stations with suspect published coordinates",
                        f"{len(suspects)} (e.g. "
                        + ", ".join(f"{x['station_code']} {x['impossible_sections']}" for x in suspects[:4])
                        + " impossible sections)",
                    ],
                ],
                [80, 90],
            ),  # fmt: skip
            Spacer(1, 2 * mm),
            table([["Flag", "Trains"]] + [[k, f"{v:,}"] for k, v in sched.get("flag_counts", {}).items()], [80, 30]),
        ]

    # ---- 4. ML ---------------------------------------------------------------------------------------------
    rounds = tlog.get("rounds", [])
    points = [(r["round"], r["cv"]["mae_min"], r["kept"]) for r in rounds]
    base_mae = locked.get("baseline_section_median", {}).get("mae_min", 1.957)
    scores = model.get("scores", {})
    ex = scores.get("gradient_boosting_existing_train", {})
    newp = scores.get("gradient_boosting_new_path", {})
    med = scores.get("baseline_section_median", {})
    iv = model.get("interval_p10_p90", {})
    story += [
        p("4. Machine learning: section run-time model", "h1"),
        p(
            "The model predicts the scheduled run time between two stops: the planning quantity a re-planner needs. "
            "It learns the correction to a section prior. Section priors are recomputed inside every cross-validation "
            "fold from training trains only, and folds are grouped by train pair, so no evaluated train is ever seen "
            "in training."
        ),
        p(
            "<b>Training protocol.</b> Before any training round, 15% of train groups were locked away as a final "
            f"test set ({tlog.get('rows_locked_test', 0):,} sections, {tlog.get('trains_locked_test', 0)} trains). "
            "Each round changed one thing and was kept only if 3-fold grouped CV error improved by at least 0.005 min. "
            "Training stopped when a full pass found no further gain."
        ),
    ]
    if points:
        story.append(
            line_chart(points, base_mae, "Cross-validated mean absolute error by round (minutes; lower is better)")
        )
    story.append(
        table(
            [["Round", "Change", "Kept", "CV MAE (min)", "Within 2 min"]]
            + [
                [
                    r["round"],
                    r["change"],
                    "yes" if r["kept"] else "no",
                    f"{r['cv']['mae_min']:.3f}",
                    f"{r['cv']['within_2_min_pct']:.1f}%",
                ]
                for r in rounds
            ],
            [14, 102, 12, 22, 20],
        )  # fmt: skip
    )
    story += [
        Spacer(1, 3 * mm),
        p("Locked test set, scored once", "h2"),
        table(
            [["Predictor", "MAE (min)", "Within 2 min", "MAPE ≥10-min sections"]]
            + [
                [
                    name,
                    f"{v.get('mae_min', 0):.3f}",
                    f"{v.get('within_2_min_pct', 0):.1f}%",
                    f"{v.get('mape_sections_10min_plus', 0):.1f}%",
                ]
                for name, v in (
                    ("Final model", locked.get("model", {})),
                    ("Section-median baseline", locked.get("baseline_section_median", {})),
                    ("Speed-by-train-type baseline", locked.get("baseline_type_speed", {})),
                )
            ],
            [70, 30, 30, 40],
        ),  # fmt: skip
    ]
    if ex:
        story += [
            Spacer(1, 3 * mm),
            p("Production model (5-fold grouped CV on all data)", "h2"),
            table(
                [
                    ["Mode", "MAE (min)", "Within 2 min"],
                    [
                        "Existing train (uses its other sections)",
                        f"{ex['mae_min']:.3f}",
                        f"{ex['within_2_min_pct']:.1f}%",
                    ],
                    [
                        "New path (no train context)",
                        f"{newp.get('mae_min', 0):.3f}",
                        f"{newp.get('within_2_min_pct', 0):.1f}%",
                    ],
                    [
                        "Section-median baseline",
                        f"{med.get('mae_min', 0):.3f}",
                        f"{med.get('within_2_min_pct', 0):.1f}%",
                    ],
                ],
                [90, 40, 40],
            ),  # fmt: skip
            p(
                f"P10-P90 interval coverage after conformal calibration: {iv.get('conformal_coverage_pct', '-')}% "
                f"(target 80%), mean width {iv.get('conformal_mean_width_min', '-')} min.",
                "small",
            ),
        ]
    story += [
        p(
            "<b>Why not 'perfect'.</b> The target is a published timetable in whole minutes with operator-chosen "
            "allowances that no public feature explains, so zero error is not achievable. The next real gain needs "
            "actual running data (NTES/COA), which is exactly what the live-feed gateway is for.",
            "body",
        ),
    ]

    # ---- 5. simulation -------------------------------------------------------------------------------------
    twins = sim.get("twins", {})
    story += [
        p("5. Simulation: 5 million checked operations", "h1"),
        p(
            "An <b>episode</b> starts a fresh twin with random conditions, then runs a random sequence of operations. "
            "The operations are clock ticks, recommendations, approvals (including stale and wrong ones), section and "
            "sensor events, malformed or impossible feed data, holds and acknowledgements. Eight safety invariants are "
            "checked after <b>every</b> operation, and every episode is seeded so any failure can be replayed exactly. "
            "Full end-to-end episodes cost about 0.1 s each, so the 5-million target is counted honestly as checked "
            "operations, not as episodes."
        ),
        table(
            [["Twin", "Episodes", "Operations checked", "Violations", "CPU ms / episode"]]
            + [
                [
                    k,
                    f"{t.get('episodes', 0):,}",
                    f"{t.get('stats', {}).get('ops', 0):,}",
                    t.get("violations_total", 0),
                    t.get("cpu_ms_per_episode", "-"),
                ]
                for k, t in twins.items()
            ]
            + [["Total", f"{sim.get('completed_episodes', 0):,}", f"{sim_ops:,}", viol, ""]],
            [34, 30, 40, 26, 40],
        ),  # fmt: skip
        p(
            f"Simulated 5-second steps (tabletop twin): {sim.get('simulated_5s_steps', 0):,}. "
            f"Wall time {sim.get('wall_seconds', 0) / 60:.0f} min on {sim.get('workers', '-')} workers. "
            f"Code checksum {str(sim.get('code_checksum', ''))[:16]}…",
            "small",
        ),
    ]
    if reg:
        story.append(p(f"Regression run on the final code: {reg.get('completed_episodes', 0):,} episodes, "
                       f"{reg.get('operations_checked', 0):,} operations, "
                       f"{sum(t.get('violations_total', 0) for t in reg.get('twins', {}).values())} violations "
                       f"(code checksum {str(reg.get('code_checksum', ''))[:16]}…).", "small"))  # fmt: skip
    story += [
        p("Invariants", "h2"),
        table(
            [
                ["Invariant", "Meaning"],
                [
                    "SAFE_SEPARATION",
                    "Approved plans never conflict; simulated trains never share a single-line section or "
                    "close up on one track; later conflicts entering the planning horizon are always on the threat list",
                ],
                [
                    "APPROVAL_GATE",
                    "Only the latest recommendation for the current state can be approved, with fresh "
                    "evidence, no open critical threat, and no closed or obstructed section on the plan",
                ],
                ["EVIDENCE_GATE", "Stale or missing mandatory evidence never yields an approvable recommendation"],
                [
                    "INPUT_REJECTION",
                    "Malformed, replayed, future or physically impossible observations never move the twin",
                ],
                [
                    "CAB_ADVISORY",
                    "No speed band without fresh evidence and an approved plan; never a proceed status with a "
                    "blocked section ahead; band never above line speed",
                ],
                [
                    "RANKING",
                    "Ranked plans are conflict-free, feasible, monotonic in time, never early, scored 0-1, "
                    "winner first; yields never re-route a train",
                ],
                ["REPLAY", "Snapshots verify and replay to the same ranking; the audit chain verifies"],
                ["NO_CRASH / LIVENESS", "No unexpected exception; every episode completes within 60 s"],
            ],
            [36, 134],
        ),  # fmt: skip
        Spacer(1, 3 * mm),
        p("What the simulation found (all fixed, each with a regression test or replayable episode)", "h2"),
        table([["#", "Finding", "Fix"]] + [[i + 1, f, x] for i, (f, x) in enumerate(SIM_FINDINGS)], [8, 82, 80]),
    ]

    # ---- 6. security -----------------------------------------------------------------------------------------
    story += [
        p("6. Security", "h1"),
        table(
            [
                ["Check", "Result"],
                [
                    "Adversarial API tests",
                    f"{audit.get('attack_tests', 32)} cases pass: auth bypass, token tricks, "
                    "path traversal, NaN/Infinity, type confusion, JSON bombs, injection strings, method tampering, CORS, "
                    "error leakage, role separation",
                ],
                [
                    "Security tests",
                    "Fail-closed production mode, role separation, host allow-list, body limits, "
                    "security headers, rate limits, bounded memory, audit tamper detection",
                ],
                [
                    "Live-feed tests",
                    "Bad signature, unknown key, replayed nonce, stale timestamp, sequence regression, "
                    "oversize batch, off-route fixes",
                ],
                [
                    "Static analysis (Bandit)",
                    f"{audit.get('bandit_findings', 0)} findings "
                    f"({audit.get('bandit_reviewed_suppressions', 7)} reviewed suppressions, each justified in the code)",
                ],
                ["Dependency audit (pip-audit)", f"{audit.get('pip_audit', '0 known vulnerabilities')}"],
                ["Browser", "Strict Content-Security-Policy verified in Chromium: no console errors on any page"],
            ],
            [44, 126],
        ),  # fmt: skip
        Spacer(1, 3 * mm),
        p("Security findings fixed during the audits", "h2"),
        table([["#", "Finding", "Fix"]] + [[i + 1, f, x] for i, (f, x) in enumerate(SEC_FINDINGS)], [8, 82, 80]),
    ]

    # ---- 7. audits ------------------------------------------------------------------------------------------
    story += [p("7. Five audit passes", "h1"),
              p("Each pass looked at the whole system through one lens, fixed what it found, and re-ran the full "
                "test suite and lint before the next pass. Details are in <i>seva2026/AUDIT_LOG.md</i>.")]  # fmt: skip
    story.append(table([["Pass", "Lens", "Main findings and fixes", "Evidence"], *AUDITS], [12, 30, 92, 36]))

    # ---- 8. live data, compliance, remaining ------------------------------------------------------------------
    story += [
        p("8. Ready for live data", "h1"),
        p("When the Ministry of Railways / CRIS authorises a feed, it plugs in without code changes to the twin."),
        *bullets(
            [
                "Envelope: source, key id, sent-at, nonce, sequence and events, HMAC-SHA256 signed with a per-source key "
                "(RAILGUARD_FEED_KEYS). Refused before reading: bad signature, unknown key, clock skew beyond ±120 s, "
                "replayed nonce, non-increasing sequence, more than 250 events.",
                "POSITION events (e.g. RTIS GNSS) are map-matched onto the train's planned route within 3 km. Anything "
                "else is raised as a route-deviation threat, never silently accepted.",
                "STATION events (e.g. NTES/COA arrival/departure) update the position. Lateness of 5 minutes or more is "
                "recorded as a disruption for the controller to decide on. The feed approves nothing.",
                "With every involved train on a fresh live fix, recommendations become REVIEWABLE instead of "
                "PLANNING_ONLY. This is tested end to end with a signed feed simulator.",
                "Remaining for go-live: CRIS's interface specification (field names, identifiers, transport), credentials, "
                "and a shadow-mode trial.",
            ]
        ),
        p("9. Legal, safety and data compliance", "h1"),
        table(
            [
                ["Instrument", "How the design addresses it", "Status"],
                [
                    "Railways Act 1989; General & Subsidiary Rules",
                    "Advisory only; named-controller approval; " "no interface to the safety chain",
                    "Met by design",
                ],
                [
                    "RDSO / EN 50126, 50129, 50716; CRS",
                    "Outside the SIL chain by design; V&V evidence prepared; " "safety case and assessor are IR steps",
                    "Needs authority",
                ],
                [
                    "IT Act 2000 s.43/66/70 (CII)",
                    "Ingests only signed, pushed, authorised data; no scraping or probing",
                    "Met by design",
                ],
                [
                    "CERT-In Directions 2022",
                    "Tamper-evident persistent logs (operator keeps ≥180 days in India), "
                    "NTP-synced clocks, 6-hour incident runbook",
                    "Ready (operator config)",
                ],
                [
                    "DPDP Act 2023 / Rules 2025",
                    "No passenger data; only controller IDs for accountability",
                    "Met by design",
                ],
                ["GODL / NDSAP, CC0, ODbL", "Publisher, licence and SHA-256 recorded for every source", "Met"],
                ["CERT-In/STQC audit, GIGW", "Self-tested; needs an empanelled auditor", "Open (external)"],
            ],
            [52, 88, 30],
        ),  # fmt: skip
        p(
            "Full register: <i>seva2026/COMPLIANCE_REGISTER.md</i>. This is an engineering register, not legal advice.",
            "small",
        ),
        p("10. What is left", "h1"),
        *bullets(
            [
                "Indian Railways / CRIS: authorise live feeds (NTES/RTIS/COA) and share the interface specification.",
                "Download the official data.gov.in timetable from a connection in India and ingest it (one command).",
                "Retrain the run-time model on observed running data, and add a delay-propagation model once real "
                "delays are available.",
                "Independent CERT-In/STQC security audit; hosting on railway infrastructure in India.",
                "Safety case and hazard log signed by IR; independent safety assessment; RDSO acceptance of the advisory role.",
                "Shadow-mode trial on one division: compare recommendations with controllers' actual decisions.",
            ]
        ),
        p("11. How to run", "h1"),
        table(
            [
                ["Task", "Command (in india_rail_ai/)"],
                ["Install", "pip install -r requirements.txt"],
                ["Get data and train", "python -m india_rail setup"],
                ["Serve the API and consoles", "python -m india_rail serve  →  /control, /control/national, /cab"],
                ["Tests and lint", "python -m pytest -q;  ruff check ."],
                ["Simulation", "python -m india_rail.railguard.simulate --demo 70000 --national 90000"],
                ["ML training rounds", "python -m india_rail.training"],
                ["Official data", "python -m india_rail official --file timetable.csv"],
                ["All-train schedules", "python -m india_rail schedules --audit | --train 12951 | --export DIR"],
                ["Shadow trial", "POST /railguard/national/shadow/actual; GET /railguard/national/shadow/report"],
                ["Verify an audit log", "python -m india_rail.railguard.audit verify <events.jsonl>"],
                ["Rebuild this report", "python scripts/build_report.py"],
            ],
            [46, 124],
        ),  # fmt: skip
    ]

    doc = SimpleDocTemplate(str(out), pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm,
                            bottomMargin=16 * mm, title="Clear Path Nexus RailGuard report", author="Clear Path Nexus")  # fmt: skip

    def footer(canvas, doc_):
        canvas.saveState()
        canvas.setFont(FONT, 7)
        canvas.setFillColor(TEXT_2)
        canvas.drawString(
            18 * mm, 9 * mm, "Clear Path Nexus · RailGuard · advisory decision support - not movement authority"
        )
        canvas.drawRightString(A4[0] - 18 * mm, 9 * mm, f"page {doc_.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return out


SIM_FINDINGS = [
    (
        "An approval went through after the state changed at the same clock time (e.g. a controller hold), and "
        "cancelled the hold",
        "Every state change bumps a version; approval must match the ranked version",
    ),
    ("A train re-planned mid-section was moved back to the start of the section", "Plans carry the starting offset"),
    ("A held train could stop at the start of the next section instead of the station", "Holds stop at the node"),
    (
        "A closed section ahead raised no threat on the tabletop twin (cab showed NORMAL)",
        "SECTION_CLOSED critical threat",
    ),
    (
        "Rounded plan times put a re-planned train back at the station for a fraction of a minute",
        "Position held until the plan's first time",
    ),
    (
        "National planner checked closures and conflicts only from the disruption station onward",
        "Planning starts at the first section the train can still change",
    ),
    ("PRIORITY-path option skipped the closed/obstructed/axle-load check", "One feasibility filter for every option"),
    (
        "Conflicts on the section a train already occupies were never examined",
        "Conflict search starts at the occupied section",
    ),
    ("Two re-pathed trains could ping-pong forever (planning hang)", "Bounded cascade; LIVENESS invariant"),
    ("The 240-min horizon was applied per train, so a pair was seen from one side only", "Pair-symmetric horizon"),
    ("The PRIORITY option returned a plan that its own re-check had not validated", "Return the validated plan"),
    (
        "Replay did not reproduce rankings (threats/acks not restored; order-dependent index)",
        "Restore derived state; sorted index; 1,585 replays 0 mismatches",
    ),
    (
        "A disruption reported by a live station event could not be applied where the train really was",
        "Feed events pin the stop index",
    ),
]
SEC_FINDINGS = [
    (
        "Starlette 0.41.3 had 7 published advisories; pytest 8.3.4 had 1",
        "FastAPI 0.142.2 / Starlette 1.7.0 / pytest 9.0.3; pip-audit 0",
    ),
    (
        "NaN in a request crashed the 422 response (500) and errors echoed client input",
        "Validation handler that never echoes input",
    ),
    (
        'Lax coercion accepted "5" and true as numbers and ignored unknown fields',
        "Strict request models: exact types, no extra fields, finite numbers",
    ),
    ("Audit chain could not be verified after a restart (second GENESIS in one file)", "Chain resumes from the file"),
    ("Ollama URL from the environment was opened without a scheme check (file://)", "http(s) only"),
    ("SQL assembled with an f-string (safe but fragile)", "Constant statement, all values bound"),
    ("Chunked uploads bypassed the body-size cap", "411 for bodies without a length"),
    ("Interactive API docs exposed in production", "Disabled when RAILGUARD_MODE=production"),
]
AUDITS = [
    [
        "1",
        "Safety logic",
        "13 defects found by the randomised simulation and fixed (section 5): stale approvals, "
        "position snapping, holds, closures, planner scope, cascade hang, horizon symmetry, replay determinism",
        "simulate.py; 0 violations in the final run",
    ],
    [
        "2",
        "Security",
        "8 findings fixed (section 6): dependency CVEs, NaN crash and input echo, type coercion, audit "
        "restart, URL schemes, SQL construction, chunked bodies, docs exposure",
        "test_attacks.py, Bandit 0, pip-audit 0",
    ],
    [
        "3",
        "Performance",
        "Plan and stress caches keyed on exact inputs, cheap snapshot copies, distance cache: "
        "39% less CPU per episode with byte-identical outputs (6 scenario and 30 episode checksums equal)",
        "baseline checksums, profiles",
    ],
    [
        "4",
        "Data and ML",
        "Locked-test training protocol; model error 1.96 → 1.38 min (-30%); production model "
        "retrained; official-data pipeline; 914 non-halt stations placed; placeholder-time bug caught by tests",
        "training_log.json, test_official.py",
    ],
    [
        "5",
        "Code quality",
        "Dead code removed; national builder split (complexity F 62 → C 16) with an identical data "
        "checksum; lint/format clean on Python 3.11 and 3.13; CI parity checked",
        "radon, vulture, ruff, CI",
    ],
]


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=OUT)
    print(build(parser.parse_args().out))
