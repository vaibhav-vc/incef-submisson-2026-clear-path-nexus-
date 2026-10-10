"""GPS / GNSS tracking: NMEA, quality gates, map-matching onto mapped track, plausibility and the device agent."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest
from test_national import data  # noqa: F401 - shared synthetic national network fixture

from india_rail.railguard import gps
from india_rail.railguard.gnss_agent import GnssAgent
from india_rail.railguard.livefeed import IST, FeedGateway, FeedSimulator
from india_rail.railguard.national import NationalTwin

DAY = date(2026, 10, 7)
SECRET = bytes(range(32))
CURVE = [[77.1, 28.0], [77.15, 28.01], [77.2, 28.0]]  # B-C bows ~1.1 km north of the straight station line


def _fix(**kw) -> gps.GpsFix:
    base = {"when": datetime(2026, 10, 7, 4, 45, 0, tzinfo=UTC), "lat": 28.6139, "lon": 77.209, "speed_kmph": 72.0,
            "hdop": 0.9, "satellites": 14, "course": 87.5}  # fmt: skip
    return gps.GpsFix(**{**base, **kw})


def test_nmea_sentences_checksums_and_navic():
    fix = _fix()
    gga, rmc = gps.nmea_sentence("GGA", fix), gps.nmea_sentence("RMC", fix, talker="GI")  # GI = NavIC
    a, b = gps.parse_nmea(gga), gps.parse_nmea(rmc)
    assert a["satellites"] == 14 and a["hdop"] == 0.9 and a["lat"] == pytest.approx(28.6139, abs=1e-6)
    assert b["talker"] == "GI" and b["valid"] and b["speed_kmph"] == pytest.approx(72.0, abs=0.1)
    assert b["lon"] == pytest.approx(77.209, abs=1e-6)
    with pytest.raises(gps.NmeaError, match="checksum"):
        gps.parse_nmea(gga.replace("28", "29", 1))  # one changed digit: the checksum no longer holds
    with pytest.raises(gps.NmeaError, match="talker"):
        gps.parse_nmea(gps.nmea_sentence("GGA", fix, talker="ZZ"))
    with pytest.raises(gps.NmeaError):
        gps.parse_nmea("$GNGSV,1,1,00*79")


def test_fix_builder_pairs_same_second_in_either_order():
    fix = _fix()
    builder = gps.FixBuilder()
    assert builder.feed(gps.nmea_sentence("RMC", fix)) is None  # RMC first, as many receivers send it
    out = builder.feed(gps.nmea_sentence("GGA", fix))
    assert out is not None and out.satellites == 14 and out.when == fix.when and out.accuracy_m == pytest.approx(4.5)
    later = _fix(when=fix.when + timedelta(seconds=1))
    assert builder.feed(gps.nmea_sentence("GGA", fix)) is None
    assert builder.feed(gps.nmea_sentence("RMC", later)) is None  # different seconds never pair


def test_quality_gates():
    now = datetime(2026, 10, 7, 4, 45, 5, tzinfo=UTC)
    assert gps.quality_problem(_fix(), now) is None
    assert "satellites" in gps.quality_problem(_fix(satellites=3), now)
    assert "HDOP" in gps.quality_problem(_fix(hdop=7.5), now)
    assert "age" in gps.quality_problem(_fix(), now + timedelta(minutes=2))
    assert "speed" in gps.quality_problem(_fix(speed_kmph=320), now)
    assert gps.quality_problem(_fix(lat=51.5, lon=-0.12), now) == "outside India"


def test_polyline_projection_and_interpolation():
    line = gps.Polyline([(77.1, 28.0), (77.15, 28.01), (77.2, 28.0)])
    cross, along = line.project(77.15, 28.01)
    assert cross < 1 and along == pytest.approx(line.length_m / 2, rel=1e-3)
    lon, lat = line.point_at(line.length_m / 2)
    assert (lon, lat) == pytest.approx((77.15, 28.01), abs=1e-9)
    assert line.point_at(-5) == (77.1, 28.0) and line.point_at(1e9) == pytest.approx((77.2, 28.0))


def _setup(data, minute: float = 615.0, geometry: bool = True):  # noqa: F811
    infra = {"B-C": {"geometry": json.dumps(CURVE)}} if geometry else {}
    twin = NationalTwin(replace(data, infrastructure=infra), start_min=minute)
    now = [datetime.combine(DAY, datetime.min.time(), IST).timestamp() + minute * 60]
    gateway = FeedGateway(twin, {("RTIS", "k1"): SECRET}, service_date=DAY, clock=lambda: now[0])
    return twin, gateway, FeedSimulator(gateway, "RTIS", "k1", SECRET, seed=3), now


def test_positions_follow_and_match_the_mapped_track(data):  # noqa: F811
    twin, gateway, sim = _setup(data)[:3]
    lon, lat = twin.lonlat("12001@0")
    assert lat > 28.002  # drawn on the curved mapped track, not the straight station line
    result = gateway.receive(sim.envelope([sim.position_event("12001@0")]))["results"][0]
    assert result["accepted"] and result["matched_to"] == "MAPPED_TRACK" and result["cross_track_m"] < 60
    opposite = gateway.receive(sim.envelope([sim.position_event("54001@0")]))["results"][0]
    assert opposite["accepted"] and opposite["matched_to"] == "STRAIGHT_LINE"  # C-D is not mapped: said so


def test_a_fix_on_the_straight_line_but_off_the_mapped_track_is_a_deviation(data):  # noqa: F811
    twin, gateway, sim = _setup(data)[:3]
    event = {**sim.position_event("12001@0"), "lat": 28.0, "lon": 77.15}  # 1.1 km from the real track
    result = gateway.receive(sim.envelope([event]))["results"][0]
    assert not result["accepted"] and "km from the planned route's track" in result["reason"]
    assert "ROUTE_DEVIATION" in {t.type for t in twin.threats.active()}
    # A fix 200 m off (multipath in a cutting) is refused, but only a second one in a row is a deviation.
    twin2, gateway2, sim2 = _setup(data)[:3]
    near = sim2.position_event("12001@0")
    near = {**near, "lat": near["lat"] + 200 / 110574.0}
    first = gateway2.receive(sim2.envelope([near]))["results"][0]
    assert not first["accepted"] and "second in a row" in first["reason"]
    assert "ROUTE_DEVIATION" not in {t.type for t in twin2.threats.active()}
    gateway2.receive(sim2.envelope([near]))
    assert "ROUTE_DEVIATION" in {t.type for t in twin2.threats.active()}
    # Without mapped geometry the same fix lies on the straight line and would have been accepted:
    plain_twin, plain_gateway, plain_sim = _setup(data, geometry=False)[:3]
    plain = plain_gateway.receive(plain_sim.envelope([{**plain_sim.position_event("12001@0"), "lat": 28.0,
                                                        "lon": 77.15}]))["results"][0]  # fmt: skip
    assert plain["accepted"] and plain["matched_to"] == "STRAIGHT_LINE"


def test_poor_gnss_quality_is_refused_without_moving_the_train(data):  # noqa: F811
    twin, gateway, sim = _setup(data)[:3]
    weak = sim.position_event("12001@0", satellites=3)
    blurred = sim.position_event("12001@0", hdop=9.0)
    results = gateway.receive(sim.envelope([weak, blurred]))["results"]
    assert [r["accepted"] for r in results] == [False, False]
    assert "satellites" in results[0]["reason"] and "HDOP" in results[1]["reason"]
    assert twin.position_state("12001@0") == "PROJECTED"  # no evidence recorded from a poor fix


def test_jumps_and_backward_moves_are_refused_and_flagged(data):  # noqa: F811
    twin, gateway, sim, now = _setup(data)
    assert gateway.receive(sim.envelope([sim.position_event("12001@0")]))["accepted"] == 1
    twin.tick(1)
    now[0] += 60
    ahead = {**sim.position_event("12001@0"), "lat": 28.0, "lon": 77.29}  # ~11 km on in 60 s: 650 km/h
    result = gateway.receive(sim.envelope([ahead]))["results"][0]
    assert not result["accepted"] and "implied speed" in result["reason"]
    threat = next(t for t in twin.threats.active() if t.type == "GNSS_IMPLAUSIBLE")
    assert "spoofing" in threat.to_dict()["detail"].lower()
    twin.tick(1)
    now[0] += 60
    back_lon, back_lat = gps.Polyline([tuple(p) for p in CURVE]).point_at(500)  # 0.5 km out of B: ~3 km back
    behind = {**sim.position_event("12001@0"), "lat": back_lat, "lon": back_lon}
    result = gateway.receive(sim.envelope([behind]))["results"][0]
    assert not result["accepted"] and "backwards" in result["reason"]
    good = gateway.receive(sim.envelope([sim.position_event("12001@0")]))["results"][0]
    assert good["accepted"]  # the real next fix still goes through


def test_device_agent_end_to_end(data):  # noqa: F811
    twin, gateway, sim, now = _setup(data)
    sent: list[dict] = []

    def post(envelope):
        sent.append(envelope)
        return gateway.receive(envelope)

    agent = GnssAgent("12001", DAY.isoformat(), "RTIS", "k1", SECRET, post, interval_s=10, clock=lambda: now[0])
    lon, lat = twin.lonlat("12001@0")
    when = datetime.fromtimestamp(now[0], UTC)
    for k in range(3):  # three seconds of receiver output, RMC before GGA, with one corrupted line
        fix = _fix(when=when + timedelta(seconds=k - 2), lat=lat, lon=lon)
        agent.feed_line(gps.nmea_sentence("RMC", fix))
        agent.feed_line(gps.nmea_sentence("GGA", fix) if k != 1 else "$GNGGA,garbage*00")
    assert agent.counts["bad_sentences"] == 1 and agent.counts["queued"] == 1  # one fix per 10 s interval
    result = agent.flush()
    assert result["accepted"] == 1 and twin.position_state("12001@0") == "FRESH"
    assert "signature" in sent[0] and sent[0]["events"][0]["hdop"] == 0.9
    # A fix that could not be sent within the 3-minute policy is dropped, not delivered late.
    now[0] += 30
    agent.feed_line(gps.nmea_sentence("RMC", _fix(when=when + timedelta(seconds=30), lat=lat, lon=lon)))
    agent.feed_line(gps.nmea_sentence("GGA", _fix(when=when + timedelta(seconds=30), lat=lat, lon=lon)))
    assert agent.counts["queued"] == 2
    now[0] += 600
    assert agent.flush() is None and agent.counts["expired"] == 1


def test_agent_refuses_plain_http():
    from india_rail.railguard.gnss_agent import http_post

    with pytest.raises(ValueError, match="https"):
        http_post("http://railguard.example", "token")


def test_a_track_that_doubles_back_keeps_every_plausible_place_until_fixes_resolve_it():
    # A horseshoe: out 2 km east, a tight turn, back west 30 m to the north. A fix at the middle of the
    # outbound leg is also within reach of the return leg.
    line = gps.Polyline([(77.0, 28.0), (77.02, 28.0), (77.02, 28.0003), (77.0, 28.0003)])
    places = line.candidates(77.01, 28.00015, 60)
    assert len(places) == 2 and places[0][1] < places[1][1]
    t0 = datetime(2026, 10, 7, 5, 0, tzinfo=UTC)
    found = [gps.Match(0, "A-B", along / 1000, cross, gps.MAPPED_TRACK, False, along) for cross, along in places]
    best, track, problem = gps.locate(None, t0, found, 5.0, 60.0)
    assert problem is None and len(track.all()) == 2  # both passes kept: the train is at one of them
    # 30 s later at 60 km/h the train is 500 m on; only the outbound place fits from the first pass.
    later = [gps.Match(0, "A-B", 1.5, 3.0, gps.MAPPED_TRACK, False, 1500.0)]
    best, narrowed, problem = gps.locate(track, t0 + timedelta(seconds=30), later, 5.0, 60.0)
    assert problem is None and narrowed.all() == (1500.0,)
    # From the narrowed track, going back to the outbound middle is a backwards move, refused.
    _, _, problem = gps.locate(narrowed, t0 + timedelta(seconds=60), found[:1], 5.0, 60.0)
    assert "backwards" in problem


def test_reported_speed_picks_the_pass_where_the_train_should_be():
    t0 = datetime(2026, 10, 7, 5, 0, tzinfo=UTC)
    prev = gps.Track(t0, 10_000.0)
    found = [gps.Match(3, "C-D", 0.2, 4.0, gps.MAPPED_TRACK, False, 10_200.0),
             gps.Match(5, "E-F", 1.5, 2.0, gps.MAPPED_TRACK, False, 11_500.0)]  # fmt: skip
    best, _, _ = gps.locate(prev, t0 + timedelta(seconds=60), found, 5.0, 90.0)  # 90 km/h: 1.5 km in a minute
    assert best.section_id == "E-F"
    best, _, _ = gps.locate(prev, t0 + timedelta(seconds=60), found, 5.0, 12.0)  # crawling: 200 m
    assert best.section_id == "C-D"


def test_a_fix_between_two_possible_places_is_not_plausible_from_either():
    """Track shared by two passes of the route (e.g. through Solapur): the train is at one pass or the other,
    never anywhere between them, so a spoofed fix 7 km on from the first pass is still a jump."""

    t0 = datetime(2026, 10, 7, 5, 0, tzinfo=UTC)
    prev = gps.Track(t0, 193_340.0, (193_340.0, 220_559.0))
    jump = [gps.Match(7, "HG-SUR", 8.6, 5.0, gps.MAPPED_TRACK, False, 200_342.0),
            gps.Match(8, "AKOR-SUR", 6.0, 0.0, gps.MAPPED_TRACK, False, 213_609.0)]  # fmt: skip
    best, track, problem = gps.locate(prev, t0 + timedelta(seconds=60), jump, 5.0, 16.4)
    assert best is None and track is None and ("jump" in problem or "backwards" in problem)
    honest = [gps.Match(8, "AKOR-SUR", 0.3, 4.0, gps.MAPPED_TRACK, False, 220_830.0)]
    best, track, problem = gps.locate(prev, t0 + timedelta(seconds=60), honest, 5.0, 16.4)
    assert problem is None and track.all() == (220_830.0,)  # the second pass was the right one
