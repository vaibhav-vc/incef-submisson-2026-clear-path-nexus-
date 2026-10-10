"""Free third-party running-status services: read only what is documented, never forced onto a journey, sent as a
signed unofficial feed that can place trains but never make a plan approvable as live."""

from __future__ import annotations

import json
from datetime import date, datetime

import pytest
from test_national import data  # noqa: F401 - shared synthetic national network fixture

from india_rail.railguard import thirdparty
from india_rail.railguard.livefeed import IST, FeedGateway, FeedSimulator
from india_rail.railguard.national import NationalTwin
from india_rail.railguard.publish import Publisher
from india_rail.railguard.thirdparty import PROVIDERS, Budget, Poller, Refused, Timetable
from tests.test_shared_track import STATIONS, TRAINS, _build

DAY = date(2026, 10, 7)
SECRET = bytes(range(32))
ENGINE, RADAR = PROVIDERS["railengine"], PROVIDERS["railradar"]


def _at(hhmm: str) -> datetime:
    hour, minute = map(int, hhmm.split(":"))
    return datetime.combine(DAY, datetime.min.time(), IST).replace(hour=hour, minute=minute)


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("thirdparty")
    return _build(tmp, STATIONS, TRAINS), Timetable(tmp / "rail.sqlite")


def _train(number, state, arr=None, dep=None, exp_arr=None, exp_dep=None):
    return {"trainNumber": number, "trainName": "x", "arrival": arr, "departure": dep, "expectedArrival": exp_arr,
            "expectedDeparture": exp_dep, "platform": "1", "delayMinutes": 0, "liveStatus": state}  # fmt: skip


def _board(*trains):
    return {"status": "SUCCESS", "data": {"station": {"name": "B"}, "count": len(trains), "trains": list(trains)},
            "error": None, "meta": {}}  # fmt: skip


# ---- reading a station board ------------------------------------------------------------------------------------
def test_a_station_board_gives_only_what_has_happened_on_journeys_in_our_timetable(built):
    _, timetable = built
    body = _board(
        _train("59001", "departed", "10:42", "10:43", exp_dep="2026-10-07T10:51:00+05:30"),  # 8 min late
        _train("59004", "upcoming", "11:55", "11:56"),
        _train("99999", "departed", "10:40", "10:41", exp_dep="2026-10-07T10:45:00+05:30"),  # not ours
        _train("19001", "departed", None, "10:50", exp_dep="2026-10-07T11:30:00+05:30"),  # in the future
        _train("59002", "departed", "09:25", "09:26", exp_dep="2026-10-07T09:30:00"),  # no zone
    )
    events, skipped = thirdparty.railengine_board(body, "B", timetable, _at("10:55"))
    assert events == [{"type": "STATION", "train_number": "59001", "start_date": "2026-10-07", "station_code": "B",
                       "event": "DEP", "observed_at": "2026-10-07T10:51:00+05:30"}]  # fmt: skip
    assert skipped == {"not an observation": 1, "not in our timetable at that time": 1, "not fresh": 1,
                       "refused: time without a zone": 1}  # fmt: skip


def test_a_report_on_another_timetable_is_not_forced_onto_a_journey(built):
    _, timetable = built
    body = _board(_train("59001", "departed", "10:46", "10:47", exp_dep="2026-10-07T10:51:00+05:30"))
    events, skipped = thirdparty.railengine_board(body, "B", timetable, _at("10:55"))
    assert events == [] and skipped == {"not in our timetable at that time": 1}


def test_a_response_without_the_documented_fields_is_refused(built):
    _, timetable = built
    for body in ({"status": "SUCCESS", "data": {}}, {"status": "ERROR"}, ["not", "an", "object"]):
        with pytest.raises(Refused):
            thirdparty.railengine_board(body, "B", timetable, _at("10:55"))
    with pytest.raises(Refused):
        thirdparty.railradar_train({"success": True, "data": {"trainNumber": "59001"}}, timetable, _at("10:55"))


# ---- reading one train's live status ------------------------------------------------------------------------------
def test_a_live_train_status_gives_the_actual_times_behind_the_train(built):
    _, timetable = built
    body = {"success": True, "data": {
        "trainNumber": "59001", "startDate": "2026-10-07", "currentLocation": {"stationCode": "C", "sequence": 2},
        "route": [
            {"sequence": 0, "stationCode": "A", "isHalt": True, "actualDeparture": "10:33"},
            {"sequence": 1, "stationCode": "B", "isHalt": True, "actualArrival": "2026-10-07T10:46:00+05:30",
             "actualDeparture": "10:48"},
            {"sequence": 2, "stationCode": "C", "isHalt": True, "actualArrival": None},
            {"sequence": 3, "stationCode": "D", "isHalt": True, "actualArrival": "11:20"},  # ahead: never taken
        ]}}  # fmt: skip
    events, _ = thirdparty.railradar_train(body, timetable, _at("10:55"))
    assert [(e["station_code"], e["event"], e["observed_at"][11:16]) for e in events] == [
        ("A", "DEP", "10:33"), ("B", "ARR", "10:46"), ("B", "DEP", "10:48")]  # fmt: skip


# ---- staying inside the free plans -----------------------------------------------------------------------------------
def test_requests_stay_inside_the_free_plans_and_the_month_survives_a_restart(tmp_path):
    clock = {"t": _at("10:00").timestamp()}
    minute = Budget(ENGINE, clock=lambda: clock["t"])
    assert sum(minute.take() for _ in range(100)) == int(60 * thirdparty.QUOTA_SHARE)
    clock["t"] += 61
    assert minute.take()
    state = tmp_path / "budget.json"
    month = Budget(RADAR, state, clock=lambda: clock["t"])
    assert sum(month.take() for _ in range(900)) == int(1000 * thirdparty.QUOTA_SHARE)
    assert not Budget(RADAR, state, clock=lambda: clock["t"]).take()  # a restart does not reset the month
    clock["t"] += 31 * 86400
    assert Budget(RADAR, state, clock=lambda: clock["t"]).take()  # a new month does
    assert set(json.loads(state.read_text())["railradar"]) == {"month", "used"}  # counts only


def test_the_key_goes_in_a_header_never_in_the_url(monkeypatch):
    seen = {}

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self, n):
            return b'{"status": "SUCCESS"}'

    def fake_urlopen(request, timeout):
        seen["url"], seen["headers"] = request.full_url, dict(request.header_items())
        return Response()

    monkeypatch.setattr(thirdparty.urllib.request, "urlopen", fake_urlopen)
    status, body = thirdparty.http_get(ENGINE, "secret-key-123", "/v1/station/NDLS/live")
    assert status == 200 and "secret-key-123" not in seen["url"] and seen["headers"]["X-api-key"] == "secret-key-123"
    assert seen["url"].startswith("https://") and "railguard" in seen["headers"]["User-agent"]


# ---- into the twin as an unofficial feed --------------------------------------------------------------------------
def _poll(built, departed_at: str):
    data_, timetable = built
    twin = NationalTwin(data_, start_min=655.0)  # 10:55
    now = _at("10:55").timestamp()
    gateway = FeedGateway(twin, {("RAILENGINE", "k1"): SECRET}, service_date=DAY, clock=lambda: now)
    body = _board(_train("59001", "departed", "10:42", "10:43", exp_dep=f"2026-10-07T{departed_at}:00+05:30"))
    poller = Poller(ENGINE, "k", timetable, gateway.receive, ("RAILENGINE", "k1", SECRET),
                    fetch=lambda *a, **k: (200, body), clock=lambda: now)  # fmt: skip
    poller.cycle(["B"])
    return twin, poller


def test_a_fresh_report_is_sent_signed_once_and_places_the_train_as_unofficial(built):
    twin, poller = _poll(built, "10:54")  # 11 min late, seen a minute ago
    assert poller.counts["events accepted"] == 1 and twin.position_source("59001@0") == "RAILENGINE"
    assert "59001@0" in twin.pending  # recorded for the controller to decide on
    poller.cycle(["B"])
    assert poller.counts["events sent"] == 1  # the same report is not sent twice
    info = Publisher(twin).train("59001@0")["evidence"]
    assert info["unofficial"] and "unofficial source: RAILENGINE" in info["text"]
    with pytest.raises(ValueError, match="feed key must be for source RAILENGINE"):
        Poller(ENGINE, "k", poller.timetable, poller.post, ("NTES", "k1", SECRET))


def test_a_report_a_few_minutes_old_gives_the_delay_but_not_a_position(built):
    twin, poller = _poll(built, "10:51")  # 8 min late, but 4 minutes ago: the train has moved on since
    assert poller.counts["events accepted"] == 1 and twin.position_source("59001@0") is None
    assert "59001@0" in twin.pending  # the delay is recorded and projected
    assert Publisher(twin).train("59001@0")["evidence"]["basis"] == "PLAN"
    twin, poller = _poll(built, "10:20")  # 35 minutes old: history, not refused silently
    assert poller.counts["events accepted"] == 0 and "59001@0" not in twin.pending


def test_a_plan_relying_on_an_unofficial_service_is_never_approvable_as_live(data):  # noqa: F811
    def ranked(source: str) -> dict:
        twin = NationalTwin(data, start_min=615.0)
        now = datetime.combine(DAY, datetime.min.time(), IST).timestamp() + 615 * 60
        gateway = FeedGateway(twin, {(source, "k1"): SECRET}, service_date=DAY, clock=lambda: now)
        sim = FeedSimulator(gateway, source, "k1", SECRET, seed=1)
        twin.disrupt("12001@0", "C", 6)
        gateway.receive(sim.envelope([sim.position_event("12001@0"), sim.position_event("54001@0")]))
        return twin.recommend("12001@0")

    assert ranked("RTIS")["state"] == "REVIEWABLE"  # the authorised feed: a real decision
    unofficial = ranked("RAILENGINE")
    assert unofficial["state"] == "PLANNING_ONLY" and "unofficial running-status service" in unofficial["reason"]


def test_the_list_says_what_was_checked_and_why_ixigo_and_ntes_are_not_used(capsys):
    assert thirdparty.main(["list"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert set(out["providers"]) == {"railengine", "railradar"} and {"ixigo", "NTES"} <= set(out["not_used"])


def test_without_a_key_the_poller_explains_where_to_get_one(monkeypatch, capsys):
    monkeypatch.delenv("RAILGUARD_RAILRADAR_KEY", raising=False)
    assert thirdparty.main(["poll", "--provider", "railradar", "--trains", "12951", "--once"]) == 2
    assert "RAILGUARD_RAILRADAR_KEY is not set" in capsys.readouterr().err
