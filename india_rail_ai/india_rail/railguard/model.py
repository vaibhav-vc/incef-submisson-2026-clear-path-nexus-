"""Digital-twin entities and the TwinTrack demo network.

Units: kilometres, km/h, minutes for plans; integer seconds for the simulation
clock (`t`). The clock is simulated so every scenario replays identically.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

AUTHORITY = "ADVISORY_ONLY"
CAB_FOOTER = "ADVISORY PROTOTYPE - AUTHORISED SIGNALS, RULES AND ATP REMAIN CONTROLLING"


@dataclass
class Section:
    id: str
    a: str
    b: str
    length_km: float
    vmax_kmph: float
    tracks: int  # 1 = single line (opposing moves conflict), 2 = double line
    curvature: float = 1.0  # relative geometry class, 0.5-2.0
    gradient: float = 1.0  # relative gradient class, 0.5-2.0
    condition: float = 0.9  # TrackSense health 0 (failed) .. 1 (new)
    asset: str | None = None  # e.g. "BRIDGE"
    asset_sensitivity: float = 1.0
    axle_limit_t: float = 25.0
    utilisation: float = 40.0  # scheduled trains/day (demo value)
    available: bool = True
    temp_restriction_kmph: float | None = None
    weather_alert: str | None = None  # e.g. "HEAT", "FLOOD_WATCH"
    obstacle: bool = False  # tabletop obstacle-sensor event pending inspection
    data_quality: str = "DEMO_SPECIFIED"  # how each attribute was obtained (national data is inferred)

    def other(self, node: str) -> str:
        return self.b if node == self.a else self.a

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Train:
    id: str
    name: str
    kind: str  # "FREIGHT" or "EXPRESS"
    priority: int  # 1 = highest
    axle_load_t: float
    mass_t: float
    vmax_kmph: float
    origin: str
    destination: str
    scheduled_departure_min: float
    scheduled_arrival_min: float
    default_route: list[str]
    delay_weight: float = 1.0
    departure_delay_min: float = 0.0  # known late start (scenario input)
    # Live state (advanced by the simulator / TwinTrack feed)
    section_id: str | None = None
    offset_km: float = 0.0  # distance from `from_node` along section_id
    from_node: str | None = None
    speed_kmph: float = 0.0
    last_position_t: int | None = None  # simulation second of the last position fix
    position_source: str = "TWINTRACK_SIM"
    feed_frozen: bool = False
    sensor_offline: bool = False
    finished: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Network:
    nodes: dict[str, tuple[float, float]]  # node -> (x, y) for the schematic display
    sections: dict[str, Section]
    adjacency: dict[str, list[str]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.rebuild()

    def rebuild(self) -> None:
        self.adjacency = {node: [] for node in self.nodes}
        for section in self.sections.values():
            self.adjacency[section.a].append(section.id)
            self.adjacency[section.b].append(section.id)

    def path_nodes(self, origin: str, route: list[str]) -> list[str]:
        nodes = [origin]
        for sid in route:
            section = self.sections[sid]
            if nodes[-1] not in (section.a, section.b):
                raise ValueError(f"Route is disconnected at {sid}")
            nodes.append(section.other(nodes[-1]))
        return nodes

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes": {k: {"x": v[0], "y": v[1]} for k, v in self.nodes.items()},
            "sections": {k: s.to_dict() for k, s in self.sections.items()},
        }


def demo_network() -> Network:
    """TwinTrack tabletop network: 10 sections, junctions J1/J2/J3, three corridors.

    W -- J1 ==fast main (bridge)== J2 == J3 -- E      (S06 J3-E is single line)
          \\__ L (curved loop) __/  \\__ K (bypass) __/
                                        Y (yard) -- J3,  Y -- L (north link)
    """

    nodes = {
        "W": (60, 220),
        "J1": (220, 220),
        "L": (380, 90),
        "J2": (540, 220),
        "J3": (700, 220),
        "E": (880, 220),
        "K": (720, 360),
        "Y": (700, 60),
    }
    sections = [
        Section("S01", "W", "J1", 10, 110, 2),
        Section("S02", "J1", "J2", 14, 110, 2, asset="BRIDGE", asset_sensitivity=1.5, utilisation=60),
        Section("S03", "J1", "L", 8, 70, 1, curvature=1.2),
        Section("S04", "L", "J2", 9, 70, 1, curvature=1.2),
        Section("S05", "J2", "J3", 9, 100, 2, utilisation=55),
        Section("S06", "J3", "E", 6, 80, 1, utilisation=70),
        Section("S07", "J2", "K", 8, 70, 1, curvature=1.1, gradient=1.2),
        Section("S08", "K", "E", 9, 70, 1, gradient=1.2),
        Section("S09", "Y", "J3", 7, 60, 1),
        Section("S10", "Y", "L", 15, 60, 1, curvature=1.3, gradient=1.3, utilisation=10),
    ]
    return Network(nodes=nodes, sections={s.id: s for s in sections})


def demo_trains() -> dict[str, Train]:
    """Train A: heavy freight W->E. Train B: express E->Y. They meet on single-line S06."""

    a = Train(
        id="A",
        name="Train A (heavy freight)",
        kind="FREIGHT",
        priority=3,
        axle_load_t=25.0,
        mass_t=4500,
        vmax_kmph=75,
        origin="W",
        destination="E",
        scheduled_departure_min=0,
        scheduled_arrival_min=36,
        default_route=["S01", "S02", "S05", "S06"],
        delay_weight=1.0,
    )
    b = Train(
        id="B",
        name="Train B (express)",
        kind="EXPRESS",
        priority=1,
        axle_load_t=17.0,
        mass_t=900,
        vmax_kmph=110,
        origin="E",
        destination="Y",
        scheduled_departure_min=38,
        scheduled_arrival_min=50,
        default_route=["S06", "S09"],
        delay_weight=1.5,
    )
    for train in (a, b):
        train.from_node = train.origin
    return {"A": a, "B": b}
