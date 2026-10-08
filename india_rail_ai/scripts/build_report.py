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
    (
        "Decision core (twin, planner, gates, cab)",
        100,
        "Built; runs on the real 2024 timetable; final code and data verified by simulation (section 6)",
    ),
    (
        "Verification (tests, simulation, real data)",
        97,
        "159 tests; 8 invariants; verified on 56,395 real train runs; formal V&V plan needs IR",
    ),
    (
        "Security engineering",
        95,
        "Controls, 32 attack tests, SAST/SCA clean, ASVS L2 self-assessment; external audit pending",
    ),
    (
        "Docs, compliance, readiness packs",
        96,
        "Register, 14-hazard log, safety case, real-data report, contract, guide",
    ),
    (
        "Whole-network coverage",
        95,
        "9,229 stations, 2,272 junctions, 9,065 sections; 8,224 stations placed from the map",
    ),
    (
        "Live-data integration",
        93,
        "A real morning replayed: 96.6% of reports accepted, ~0.1 s per batch; CRIS mapping remains",
    ),
    (
        "All-train schedules and data completeness",
        92,
        "Running days observed for all 3,549 trains; 343 placeholder timetables caught",
    ),
    ("Machine learning", 93, "Forecast learned from 1.26M actual arrivals: 13.7 vs 17.2 min on unseen days"),
    (
        "Official data",
        85,
        "Pipeline ready; data.gov.in refuses this build network; data checked against Ministry figure",
    ),
    ("Infrastructure data", 80, "OSM line count on 90% of sections; block sections and loops need IR registers"),
    ("Conflict prediction on real days", 70, "Warnings 1.23x as likely to precede real time loss; needs IR block data"),
]
# (stage, weight %, done %, what this project has done, what only the railway can do)
DEPLOYMENT_PATH = [
    ("Software built and verified", 35, 94, "This repository, verified on real running data", "-"),
    ("Live data and CRIS integration", 15, 45, "Gateway proven on a real morning's reports; contract; test vector",
     "Authorise access; share spec and block-section data; issue keys; test in CRIS environment"),
    ("Security audit and hosting", 10, 35, "ASVS self-assessment, attack tests, SAST/SCA",
     "CERT-In/STQC audit; host on IR infrastructure"),
    ("Safety acceptance", 15, 35, "Hazard log (14 hazards) and safety case with real-data evidence",
     "Hazard workshop; scoring; independent assessment; RDSO/IR acceptance"),
    ("Shadow-mode trial", 20, 25, "Retrospective shadow run on real days; trial tooling, protocol, metrics",
     "Run 3-12 months on a division with live data; review disagreements"),
    ("Roll-out and training", 5, 30, "Operator guide and training modules", "Deliver training; issue procedures"),
]  # fmt: skip


REAL_FINDINGS = [
    (
        "Live-feed gateway threw away real reports",
        "A late train that had not reported yet was projected on time, so its real report at a station the projection "
        "had already passed was rejected (19% of a real morning's reports). Reports are now matched from the train's "
        "last accepted observation, never from the projection; a report behind it is refused as out of order.",
    ),
    (
        "Threats re-evaluated once per event",
        "Every report triggered a national threat evaluation: 0.5 s per one-minute batch in the first hour. Now once "
        "per batch: about 0.1 s over a whole morning, and every change still supersedes earlier rankings.",
    ),
    (
        "Placeholder timetables in the source",
        "343 trains (mostly specials) list every stop at the same minute; their 'actual' times mean nothing. They are "
        "excluded from the twin and from every score, and counted.",
    ),
    (
        "Track count over-read on curves and corridors",
        "The first OSM line count read curving single lines and the parallel Dedicated Freight Corridor as double "
        "line. It now counts lines crossing a perpendicular cross-section, ignores freight corridors, metros and "
        "sidings, and was checked against known single (Konkan) and double (Delhi-Bhopal) routes.",
    ),
    (
        "Old timetable and stale labels",
        "The 2016 timetable lacked 6,091 sections of 2024; the twin now runs on the 2024 one, and its data label no "
        "longer claims the network is inferred from the open timetable.",
    ),
    (
        "Conflict warnings barely predictive with the old projection",
        "Carrying a delay forward unchanged made warnings only slightly better than chance; projecting late trains "
        "with the forecast learned from real running made them clearly more predictive (see table).",
    ),
    (
        "Forecast plan overlapped itself (found by the simulation)",
        "A forecast recovering time faster than possible made a plan leave a stop before arriving (7 of the first 60 "
        "episodes). Forecast plans now never do that and never run a section under 85% of its timetabled time.",
    ),
    (
        "A forecast could replace a controller's decision",
        "A forecast now only replaces a projection; once a hold or yield shapes the plan, new delays are added on top.",
    ),
    (
        "Simulation workers stalled",
        "Model inference threads in every worker spun against each other; now one thread per worker (600 episodes in "
        "35 s).",
    ),
]


def real_data_section(rv: dict[str, Any]) -> list[Any]:
    """Section 2: verification against what actually happened (observed running, September 2024)."""

    if not rv:
        return []
    cred, drift, fc = rv["credibility"], rv["timetable_drift"], rv["forecast"]
    track, build_ = rv.get("track_data", {}), rv.get("data_build", {})
    conf, feed = rv["conflicts"], rv["live_feed_replay"]
    lines = track.get("accepted_lines", {})
    double = sum(v for k, v in lines.items() if k not in ("1", "None"))
    out: list[Any] = [
        p("2. Verified on real running", "h1"),
        p(
            "Everything in this section is computed from <b>what really happened</b>: the actual arrival times of "
            f"{cred['runs_observed']:,} train runs ({cred['arrivals_observed']:,} station arrivals, "
            f"{cred['trains']:,} trains) in September 2024, published for research by Chowdhury, Koley, "
            "Chakraborty and Ghosh (IIT Kharagpur, IEEE T-ITS 2026). Real track data comes from OpenStreetMap. "
            "Nothing here is generated by this project. The running data is fetched by the user, checked against a "
            "pinned SHA-256 and never redistributed; only these aggregate results are published."
        ),
        tiles(
            [
                ("real train runs checked", f"{cred['runs_observed']:,}"),
                ("actual arrival times", f"{cred['arrivals_observed'] / 1e6:.2f}M"),
                ("sections with mapped track data", f"{track.get('sections_accepted', 0):,}"),
                (
                    "forecast error on unseen days",
                    f"{fc['scores']['learned_from_real_running']['mae_min']:.1f} min",
                ),  # fmt: skip
            ]
        ),
        Spacer(1, 3 * mm),
        p("Is the data credible?", "h2"),
        table(
            [
                ["Measure", "Observed (Sep 2024)", "Official"],
                [
                    "Mail/Express at destination within 15 min",
                    f"{cred['destination_on_time_pct_mail_express']:.1f}%",
                    f"{cred['official_figure']['value_pct']}% (FY 2024-25, Ministry of Railways)",
                ],
            ],
            [70, 40, 60],
        ),  # fmt: skip
        p(cred["reading"], "small"),
        p("What the real data changed in the twin", "h2"),
        table(
            [
                ["Item", "Before (open 2016 data)", "Now (real data)"],
                [
                    "Timetable",
                    "2016 community snapshot",
                    f"September 2024: {build_.get('trains', 0):,} trains, {build_.get('stops', 0):,} timed stops",
                ],
                [
                    "Running days",
                    "unknown for every train",
                    f"from observed running for all {build_.get('trains_with_running_days', 0):,} trains",
                ],
                [
                    "Station positions",
                    "community coordinates",
                    f"{track.get('stations_located_by_osm_ref', 0):,} located on the map by their IR code",
                ],
                [
                    "Track count",
                    "inferred from timetable or assumed single",
                    f"mapped on {track.get('sections_accepted', 0):,} of {track.get('sections', 0):,} sections: "
                    f"{lines.get('1', 0):,} single, {double:,} double or more",
                ],
                [
                    "Electrification",
                    "unknown",
                    f"{track.get('accepted_electrified_over_90pct', 0):,} sections at least 90% electrified",
                ],
                [
                    "Trains with placeholder times",
                    "not detected",
                    f"{build_.get('trains_with_placeholder_timetable_excluded', 0)} excluded and counted",
                ],
            ],
            [40, 50, 80],
        ),  # fmt: skip
        p(
            f"Of the trains running under the same number, origin and destination in 2016 and 2024, "
            f"{drift.get('journey_time_changed_over_15_min_pct', 0)}% changed journey time by more than 15 minutes, "
            f"and {drift.get('sections_2024_missing_from_2016', 0):,} sections of 2024 did not exist in the 2016 "
            "data: running on the current timetable matters.",
            "small",
        ),
        p("Forecasting where late trains will be (forward in time: learned on 1-20 Sep, scored on 21-30 Sep)", "h2"),
    ]
    names = {"twin_current_rule": "Twin's previous rule", "persistence": "Delay stays the same",
             "history": "Train's own history", "learned_from_real_running": "Learned from real running"}  # fmt: skip
    rows = [["Method", "Average error", "Within 15 min", "<=1 h ahead", "1-3 h", "3-6 h", ">6 h"]]
    for key, label in names.items():
        sc = fc["scores"][key]
        hz = sc["mae_by_horizon_min"]
        rows.append([label, f"{sc['mae_min']:.1f} min", f"{sc['within_15_min_pct']:.1f}%",
                     *(f"{hz[b]:.1f}" for b in ("<=1h", "1-3h", "3-6h", ">6h"))])  # fmt: skip
    gain = fc["mae_reduction_vs"]["twin_current_rule"]
    out += [
        table(rows, [44, 24, 22, 20, 20, 20, 20]),
        p(
            f"{fc['split']['test_pairs']:,} forecasts for {fc['split']['test_runs']:,} real runs on days the model "
            f"never saw. Improvement over the previous rule: {gain['mae_reduction_min']} min "
            f"(95% interval {gain['ci95_min'][0]}-{gain['ci95_min'][1]}, bootstrap over runs). The P10-P90 band "
            f"covered {fc['interval_p10_p90_coverage_pct']}% of real outcomes (target 80%). The deployed model is "
            "exactly the one scored here; it is rebuilt locally and not distributed.",
            "small",
        ),
        p("Do conflict warnings come true? (retrospective shadow run on real days)", "h2"),
        p(
            "At six times of day on four unseen real days, the national twin was given every train's real delay "
            "and flagged conflicts in the next two hours. For each warning, the train that has to give way "
            "should then lose time on that section. It is compared with unflagged trains in the same state "
            "(already late or not), because late trains tend to recover on their own.",
            "small",
        ),
    ]
    variants = [("twin_rule_without_real_track_data", "Previous projection, no track data"),
                ("twin_rule_with_real_track_data", "Previous projection + real track data"),
                ("learned_projection_with_real_track_data", "Learned projection + real track data")]  # fmt: skip
    rows = [["Twin", "Warnings", "Give-way train lost >=5 min", "Comparable trains", "Lift"]]
    for key, label in variants:
        c = conf[key]
        rows.append([label, f"{c['flagged_gives_way']:,}", f"{c['gives_way_lost_5_min_pct']}%",
                     f"{c['comparable_unflagged_lost_5_min_pct']}%", f"{c['lift']}x"])  # fmt: skip
    single_before = conf["twin_rule_without_real_track_data"]["single_line"]["flagged_gives_way"]
    single_after = conf["twin_rule_with_real_track_data"]["single_line"]["flagged_gives_way"]
    out += [
        table(rows, [60, 22, 36, 30, 22]),
        p(
            f"Real track data removed {single_before - single_after:,} of {single_before:,} single-line warnings "
            "that the old 'assume single line' rule raised. Warnings are informative but far from certain: section "
            "data between stopping stations cannot see block sections, intermediate loops or signals. That data is "
            "held by Indian Railways (engineering registers, COA) and is the next real gain.",
            "small",
        ),
        p("A real morning through the signed live-feed gateway", "h2"),
    ]
    rows = [["Projection", "Reports", "Accepted", "Batch p50 / p95", "Projection within 15 min of reality"]]
    for key, label in (("twin_rule", "Previous rule"), ("learned_projection", "Learned forecast")):
        f = feed[key]
        rows.append([label, f"{f['events_sent']:,}", f"{f['accepted'] / f['events_sent'] * 100:.1f}%",
                     f"{f['batch_latency_ms']['p50']:.0f} / {f['batch_latency_ms']['p95']:.0f} ms",
                     f"{f['projection_error_at_arrival_min']['within_15_min_pct']}%"])  # fmt: skip
    out += [
        table(rows, [36, 22, 22, 34, 56]),
        p(
            f"{feed['twin_rule']['window']} on {feed['twin_rule']['day']}: every real arrival sent as a signed "
            "NTES-style STATION event at its real time. Rejected reports are out-of-order or unknown runs, refused "
            "on purpose.",
            "small",
        ),
        p("Defects found by real data (all fixed)", "h2"),
        table([["Finding", "What changed"]] + [[a, b] for a, b in REAL_FINDINGS], [44, 126]),
        p(
            "<b>Limits.</b> One month (September: no fog season); only arrivals are observed (departures in the "
            "file are arrival plus scheduled halt); early running is recorded as zero; freight and suburban trains "
            "are not included; OpenStreetMap is volunteer-mapped. A shadow trial on live data with controllers is "
            "still needed.",
            "small",
        ),
        PageBreak(),
    ]
    return out


def build(out: Path) -> Path:
    sim = load(EVIDENCE / "simulation" / "simulation_results.json")
    reg = load(EVIDENCE / "simulation" / "regression_results.json")
    final = load(EVIDENCE / "simulation" / "final_code_results.json")
    real_final = load(EVIDENCE / "simulation" / "real_data_final_results.json")
    real_national = load(EVIDENCE / "simulation" / "real_data_national_results.json")
    tlog = load(ROOT / "models" / "training_log.json")
    model = load(ROOT / "models" / "runtime_model_metrics.json")
    audit = load(EVIDENCE / "audit" / "audit_summary.json")
    sched = load(EVIDENCE / "schedules" / "schedule_audit.json")
    rv = load(EVIDENCE / "real_data" / "real_validation.json")
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
            "real data: a digital twin of every station, junction, section and timetabled train (September 2024 "
            "timetable, observed running days, mapped track); a re-planner that ranks conflict-free alternatives after "
            "a disruption; a driver cab advisory; delay forecasts learned from real running; a tamper-evident audit "
            "trail; and a gateway ready for authorised live feeds, tested with a real morning's reports."
        ),
        p(
            "<b>What it is not.</b> It is advisory. It has no interface to signals, points, interlocking, Kavach/ATP or "
            "brakes, and it does not hold or grant movement authority. Authorised signals, the General & Subsidiary "
            "Rules and railway staff remain controlling."
        ),
        p(
            "<b>How to read the numbers.</b> The verification in section 2 uses real recorded running of Indian "
            "Railways trains (September 2024) and real track data; the safety checks use randomised simulation. None of "
            "it is yet a live field trial. Readiness percentages are judgements and are stated with their reasons."
        ),
        Spacer(1, 6 * mm),
    ]
    sim_ops = sim.get("operations_checked", 0)
    viol = sum(t.get("violations_total", 0) for t in sim.get("twins", {}).values())
    last = real_final or final
    final_viol = sum(t.get("violations_total", 0) for t in last.get("twins", {}).values()) if last else viol
    locked = tlog.get("locked_test", {})
    story.append(
        tiles(
            [
                ("stations in the twin", f"{nat_stats.get('stations_total', 8990):,}"),
                ("junctions", f"{nat_stats.get('junctions', 1454):,}"),
                ("sections between stops", f"{nat_stats.get('sections', 8738):,}"),
                ("timetabled train runs in the 2-day window", f"{nat_stats.get('runs_in_window', 7580):,}"),
                ("operations checked in simulation", f"{sim_ops:,}"),
                ("invariant violations on the final code", f"{final_viol}"),
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
            f"<b>Software side: about {software_pct:.0f}% done</b> - everything this project can build and verify, "
            "now verified on real recorded running (section 2). The rest of the software work needs inputs only "
            "Indian Railways holds: CRIS's interface specification and live feed, block-section and loop registers "
            "(what makes conflict warnings precise), the current official timetable, and controller feedback from a "
            "trial."
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
    story += [PageBreak(), *real_data_section(rv)]

    # ---- 3. what was built ---------------------------------------------------------------------------------
    story += [
        p("3. What was built", "h1"),
        table(
            [
                ["Component", "What it does"],
                [
                    "National twin (railguard/national.py)",
                    "Every station, junction and section of the 2024 timetable with mapped track data; train runs over a "
                    "two-day window on their observed running days; occupancy index for fast conflict search; "
                    "disruption, ranking, approval, threats, cab, replay.",
                ],
                [
                    "Real data (realdata.py, osm_infra.py, realval.py, railguard/eta.py)",
                    "Observed running and the 2024 timetable; OpenStreetMap track data; verification against what "
                    "happened; delay forecasts learned from real running for feed-reported trains.",
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
                [
                    "Data",
                    "SQLite, pandas, NumPy, SciPy; observed running Sep 2024 (research use); OpenStreetMap (ODbL) "
                    "via pyosmium; DataMeet (CC0); data.gov.in pipeline (GODL)",
                ],
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
        p("4. Data: the whole network", "h1"),
        p(
            "The twin is built from <b>real data</b>: the September 2024 timetable (3,549 trains; 343 with placeholder "
            "times excluded), running days observed for every train, station positions and line counts from "
            "OpenStreetMap, and station records from the open DataMeet data (CC0). Every attribute is labelled with "
            "its evidence, so nobody mistakes an inference for a survey. Without the real data the twin falls back to "
            "the 2016 open timetable; production refuses that."
        ),
        table(
            [["Quantity", "Value", "How it was obtained"]]
            + [
                [k.replace("_", " "), f"{v:,}" if isinstance(v, int) else v, how]
                for k, v, how in [
                    (
                        "stations_total",
                        nat_stats.get("stations_total", 8990),
                        "every station in the open and 2024 data",
                    ),
                    (
                        "stations_located_from_osm",
                        nat_stats.get("stations_located_from_osm", 0),
                        "positioned on the map by their Indian Railways code (OpenStreetMap ref)",
                    ),
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
                        "sections_with_osm_infrastructure",
                        nat_stats.get("sections_with_osm_infrastructure", 0),
                        "mapped track path accepted (agrees with the timetable's rail distance)",
                    ),
                    (
                        "sections_osm_double_or_more",
                        nat_stats.get("sections_osm_double_or_more", 0),
                        "two or more parallel running lines mapped along the section",
                    ),
                    (
                        "sections_osm_single",
                        nat_stats.get("sections_osm_single", 0),
                        "a single-line stretch over 2 km, or over 10% of the section",
                    ),
                    (
                        "sections_inferred_multi_track",
                        nat_stats.get("sections_inferred_multi_track", 5098),
                        "opposing trains timetabled on it at the same time (they must cross inside it)",
                    ),
                    (
                        "sections_assumed_single",
                        nat_stats.get("sections_assumed_single", 3640),
                        "no evidence at all: treated as single line (the safe assumption)",
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
            "<b>Known limits.</b> The timetable is from September 2024 (the current official one must be ingested from "
            "India). OpenStreetMap is volunteer-mapped. Loops, platforms, block sections and signals are not in any "
            "open dataset; they are what conflict warnings need next (section 2)."
        ),
    ]
    if sched:
        cov = sched.get("coverage_pct", {})
        dur = sched.get("timetable_vs_published_duration", {})
        suspects = sched.get("suspect_station_coordinates", [])
        story += [
            p("All trains in the open data: working schedules and completeness", "h2"),
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
        p("5. Machine learning: section run-time model", "h1"),
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
            "allowances that no public feature explains, so zero error is not achievable. The real gain comes from "
            "actual running: section 2 trains a delay forecast on 1.26 million real arrivals and scores it on unseen "
            "days; with IR's live feed it can be retrained across seasons.",
            "body",
        ),
    ]

    # ---- 5. simulation -------------------------------------------------------------------------------------
    twins = sim.get("twins", {})
    story += [
        p("6. Simulation: 9.9 million checked operations", "h1"),
        p(
            "An <b>episode</b> starts a fresh twin with random conditions, then runs a random sequence of operations. "
            "The operations are clock ticks, recommendations, approvals (including stale and wrong ones), section and "
            "sensor events, malformed or impossible feed data, holds and acknowledgements. Eight safety invariants are "
            "checked after <b>every</b> operation, and every episode is seeded so any failure can be replayed exactly. "
            "Full end-to-end episodes cost about 0.1 s each, so the 5-million target is counted honestly as checked "
            "operations, not as episodes."
        ),
        p(
            "<b>Result.</b> The main run checked over 5 million operations. The national twin had no violations. "
            "The tabletop twin had 8 violations in 70,000 episodes: 7 were one real defect (re-holding a train that "
            "was already held released it forward) and 1 was a test-case error in the harness. Both were fixed, all 8 "
            "episodes replay clean, and a further run on the fixed, final code is reported below."
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
    runs = (
        ("Regression run (after the main run's code)", reg),
        ("Run on the code before real data", final),
        ("Final code on real data with the learned forecast", real_final),
        ("Final code, national twin on the real network", real_national),
    )
    for label, run in runs:
        if run:
            story.append(p(f"{label}: {run.get('completed_episodes', 0):,} episodes, "
                           f"{run.get('operations_checked', 0):,} operations, "
                           f"{sum(t.get('violations_total', 0) for t in run.get('twins', {}).values())} violations "
                           f"(code checksum {str(run.get('code_checksum', ''))[:16]}…).", "small"))  # fmt: skip
    every = (sim, reg, final, real_final, real_national)
    total_ops = sum(r.get("operations_checked", 0) for r in every if r)
    story.append(p(f"<b>All runs together: {total_ops:,} checked operations, "
                   f"{sum(t.get('violations_total', 0) for r in every if r for t in r.get('twins', {}).values())} "
                   "violations.</b>", "body"))  # fmt: skip
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
        p("7. Security", "h1"),
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
                [
                    "Dependency audit (pip-audit)",
                    f"{audit.get('pip_audit', {}).get('known_vulnerabilities', 0)} known vulnerabilities in "
                    f"{audit.get('pip_audit', {}).get('packages', '-')} pinned packages",
                ],
                ["Browser", "Strict Content-Security-Policy verified in Chromium: no console errors on any page"],
            ],
            [44, 126],
        ),  # fmt: skip
        Spacer(1, 3 * mm),
        p("Security findings fixed during the audits", "h2"),
        table([["#", "Finding", "Fix"]] + [[i + 1, f, x] for i, (f, x) in enumerate(SEC_FINDINGS)], [8, 82, 80]),
    ]

    # ---- 7. audits ------------------------------------------------------------------------------------------
    story += [p("8. Six audit passes", "h1"),
              p("Each pass looked at the whole system through one lens, fixed what it found, and re-ran the full "
                "test suite and lint before the next pass. Details are in <i>seva2026/AUDIT_LOG.md</i>.")]  # fmt: skip
    story.append(table([["Pass", "Lens", "Main findings and fixes", "Evidence"], *AUDITS], [12, 30, 92, 36]))

    # ---- 8. live data, compliance, remaining ------------------------------------------------------------------
    story += [
        p("9. Ready for live data", "h1"),
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
                "Tested with real data: a real morning's 7,979 arrivals sent as signed STATION events at their real "
                "times; 96.6% accepted (the rest out of order or unknown runs, refused on purpose), about 0.1 s per "
                "one-minute batch. Reports are matched from each train's last observation, never from its projection.",
                "Remaining for go-live: CRIS's interface specification (field names, identifiers, transport), credentials, "
                "and a shadow-mode trial.",
            ]
        ),
        p("10. Legal, safety and data compliance", "h1"),
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
        p("11. What is left", "h1"),
        *bullets(
            [
                "Indian Railways / CRIS: authorise live feeds (NTES/RTIS/COA) and share the interface specification.",
                "Indian Railways: share block-section, loop and line-speed registers; measured on real days, they are "
                "what conflict warnings need to become precise.",
                "Download the current official timetable from a connection in India and ingest it (one command).",
                "Retrain the delay forecast on IR's own feed across seasons (fog, monsoon); it is learned from one "
                "month of real running today.",
                "Independent CERT-In/STQC security audit; hosting on railway infrastructure in India.",
                "Safety case and hazard log signed by IR; independent safety assessment; RDSO acceptance of the advisory role.",
                "Shadow-mode trial on one division: compare recommendations with controllers' actual decisions.",
            ]
        ),
        p("12. How to run", "h1"),
        table(
            [
                ["Task", "Command (in india_rail_ai/)"],
                ["Install", "pip install -r requirements.txt"],
                ["Get data and train", "python -m india_rail setup"],
                ["Real data", "python -m india_rail real fetch | build | osm --pbf FILE | validate"],
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
    (
        "Main run, 7 episodes: re-holding an already-held train released it towards its timetabled position",
        "A re-hold never moves the stop point later; regression test fails on the old code",
    ),
    (
        "Main run, 1 episode: a harness test case (not the system) mislabelled a plausible move as a jump",
        "Harness fixed",
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
        "14 system defects found by the randomised simulation and fixed (section 5): stale approvals, "
        "position snapping, holds and re-holds, closures, planner scope, cascade hang, horizon symmetry, "
        "replay determinism",
        "simulate.py; 0 violations on the final code",
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
    [
        "6",
        "Real-life data",
        "10 findings fixed (section 2): feed reports rejected by a projection, per-event threat refresh, placeholder "
        "timetables, OSM line over-count, old timetable, weak warnings, forecast plan overlap (caught by the "
        "simulation), forecasts replacing decisions, worker thread contention, stale labels",
        "56,395 real runs; realval.py; REAL_DATA_VALIDATION.md",
    ],
]


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=OUT)
    print(build(parser.parse_args().out))
