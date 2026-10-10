"""Published expected times: prompt with bad news, sure of good news, never early, honest when unsure."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from india_rail.network import clock
from india_rail.railguard.national import NationalTwin
from india_rail.railguard.publish import EARLIER_HOLD_MIN, PUBLISH_STEP_MIN, STALE_REPORT_MIN, Publisher
from tests.test_shared_track import LOCAL, OPPOSING, RAJ, STATIONS, TRAINS, _build


@pytest.fixture(scope="module")
def data(tmp_path_factory):
    return _build(tmp_path_factory.mktemp("publish"), STATIONS, TRAINS)


@pytest.fixture()
def twin(data) -> NationalTwin:
    return NationalTwin(data, start_min=590.0)


def _timetable(twin: NationalTwin, run: str):
    saved = twin.plans.pop(run, None)
    plan = twin.plan_of(run)
    if saved is not None:
        twin.plans[run] = saved
    return plan


def _late(twin: NationalTwin, run: str, minutes: float) -> None:
    """Give `run` a plan `minutes` late from its first departure (replacing any earlier one)."""

    twin._set_plan(run, NationalTwin.propagate(_timetable(twin, run), {0: minutes}))
    twin.refresh()


def _expected(pub: Publisher, run: str, q: int, kind: str = "arr") -> str:
    return pub.train(run)["stops"][q][f"expected_{kind}"]


# ---- the rule, on its own ---------------------------------------------------------------------------------------
def _rule():
    pub = Publisher(SimpleNamespace(now=0.0, epoch=1))
    return pub, pub.twin


def test_a_later_time_is_published_at_once():
    pub, _ = _rule()
    assert pub._publish(("r", 1, "arr"), 600.0, None) == 600.0
    assert pub._publish(("r", 1, "arr"), 610.0, None) == 610.0


def test_a_change_smaller_than_the_step_does_not_move_the_time():
    pub, twin = _rule()
    pub._publish(("r", 1, "arr"), 600.0, None)
    for forecast in (601.0, 599.0, 601.5, 598.5):
        twin.now += 5
        assert pub._publish(("r", 1, "arr"), forecast, None) == 600.0


def test_an_earlier_time_is_published_only_once_it_has_held():
    pub, twin = _rule()
    pub._publish(("r", 1, "arr"), 620.0, None)
    assert pub._publish(("r", 1, "arr"), 610.0, None) == 620.0  # first seen: not yet
    twin.now += EARLIER_HOLD_MIN - 1
    assert pub._publish(("r", 1, "arr"), 610.5, None) == 620.0
    twin.now += 1
    assert pub._publish(("r", 1, "arr"), 610.0, None) == 610.0


def test_an_improvement_that_is_withdrawn_is_never_shown():
    pub, twin = _rule()
    pub._publish(("r", 1, "arr"), 620.0, None)
    pub._publish(("r", 1, "arr"), 610.0, None)
    twin.now += 1
    assert pub._publish(("r", 1, "arr"), 620.0, None) == 620.0  # withdrawn: the clock starts again
    twin.now += 1
    pub._publish(("r", 1, "arr"), 610.0, None)
    twin.now += EARLIER_HOLD_MIN - 0.5
    assert pub._publish(("r", 1, "arr"), 610.0, None) == 620.0


def test_a_departure_is_never_shown_before_its_floor():
    pub, _ = _rule()
    assert pub._publish(("r", 1, "dep"), 590.0, 600.0) == 600.0


# ---- one train ----------------------------------------------------------------------------------------------------
def test_a_train_with_no_report_shows_the_timetable_and_says_so(twin):
    info = Publisher(twin).train(LOCAL)
    assert info["evidence"]["basis"] == "TIMETABLE"
    last = info["stops"][-1]
    assert last["expected_arr"] == last["scheduled_arr"] and last["arr_status"] == "SCHEDULED"  # not "on time"
    assert "NTES" in info["note"]


def test_a_late_train_is_shown_late_at_once_and_back_on_time_only_once_sure(twin):
    pub = Publisher(twin)
    scheduled = pub.train(LOCAL)["stops"][3]["scheduled_arr"]
    _late(twin, LOCAL, 12)
    stop = pub.train(LOCAL)["stops"][3]
    assert stop["arr_status"] == "LATE 12 MIN" and stop["expected_arr"] != scheduled
    _late(twin, LOCAL, 4)  # the forecast improves
    assert pub.train(LOCAL)["stops"][3]["arr_status"] == "LATE 12 MIN"
    twin.tick(EARLIER_HOLD_MIN)
    assert pub.train(LOCAL)["stops"][3]["arr_status"] == "LATE 4 MIN"


def test_departure_is_never_before_the_timetable_nor_before_the_published_arrival(twin):
    pub = Publisher(twin)
    _late(twin, LOCAL, 12)
    pub.train(LOCAL)
    # The arrival at B improves (held, not yet published) while the departure forecast is earlier still
    _late(twin, LOCAL, 6)
    stop = pub.train(LOCAL)["stops"][1]
    s_dep = twin.runs[LOCAL].s_enter[1]
    assert stop["_dep_min"] >= stop["_arr_min"] >= s_dep
    # A plan that would leave early is shown leaving on time
    early = NationalTwin.propagate(_timetable(twin, LOCAL), {0: 0.0})
    early.enter[1] -= 3
    twin._set_plan(LOCAL, early)
    twin.refresh()
    fresh = Publisher(twin).train(LOCAL)["stops"][1]
    assert fresh["expected_dep"] == clock(s_dep) and fresh["dep_status"] == "ON TIME"  # re-planned: a claim


def test_stops_behind_the_train_are_shown_as_done_and_the_next_is_not(twin):
    pub = Publisher(twin)
    twin.tick(60)  # the twin starts at 09:50; at 10:50 59001 (B 10:42-10:43, C 10:55) is between B and C
    stops = pub.train(LOCAL)["stops"]
    assert stops[0]["dep_status"] == "DEPARTED"
    assert stops[1]["arr_status"] == "ARRIVED" and stops[1]["dep_status"] == "DEPARTED"
    assert "expected_arr" in stops[2] and stops[2]["arr_status"] != "ARRIVED"


def test_a_report_gone_quiet_is_marked_not_confirmed(twin):
    pub = Publisher(twin)
    twin.tick(15)  # 10:05: 59001 is due off A at 10:30; 12951 left A at 10:00
    sid = twin.runs[RAJ].sections[0]
    assert twin.ingest_position(RAJ, sid, 1.0)["accepted"]
    assert pub.train(RAJ)["evidence"]["basis"] == "LIVE"
    twin.tick(STALE_REPORT_MIN + 1)
    evidence = pub.train(RAJ)["evidence"]
    assert evidence["basis"] == "LAST_REPORT" and "not confirmed" in evidence["text"] and sid in evidence["text"]


def test_a_stop_whose_time_has_come_with_no_arrival_reported_is_due(twin):
    pub = Publisher(twin)
    twin.tick(37)  # 10:27: past 12951's 10:24 arrival at D
    assert twin.ingest_position(RAJ, twin.runs[RAJ].sections[0], 1.0)["accepted"]  # but reported still near A
    twin.tick(1)
    assert twin.position(RAJ).get("observed")
    assert pub.train(RAJ)["stops"][-1]["arr_status"] == "DUE"


def test_the_likely_range_always_contains_the_published_time(twin):
    class Eta:
        def forecast(self, _twin, run):
            return [{"delay_p10_min": 0.0, "delay_p90_min": 1.0} for _ in twin.plan_of(run).sections]

    twin.eta = Eta()
    pub = Publisher(twin)
    twin.tick(30)
    plan = twin.plan_of(LOCAL)
    twin.ingest_position(LOCAL, plan.sections[1], 0.5)
    _late(twin, LOCAL, 10)
    twin.ingest_position(LOCAL, twin.plan_of(LOCAL).sections[1], 0.5)
    stop = pub.train(LOCAL)["stops"][3]
    assert stop["likely_arrival"][0] <= stop["expected_arr"] <= stop["likely_arrival"][1]


def test_a_reset_twin_starts_publishing_again(twin):
    pub = Publisher(twin)
    _late(twin, LOCAL, 12)
    assert pub.train(LOCAL)["stops"][3]["arr_status"] == "LATE 12 MIN"
    twin.reset()
    assert pub.train(LOCAL)["stops"][3]["arr_status"] == "SCHEDULED"


def test_unknown_run_is_refused(twin):
    with pytest.raises(KeyError):
        Publisher(twin).train("00000@0")


# ---- a station board -----------------------------------------------------------------------------------------------
def test_the_board_lists_calls_in_the_window_soonest_first(twin):
    board = Publisher(twin).board("b", window_min=130)  # 09:50 to 12:00
    assert board["station"] == "B"
    runs = [row["run"] for row in board["trains"]]
    assert runs == [LOCAL, OPPOSING]  # 59001 at 10:42, 59004 at 11:55; 19001 left B at 08:00
    assert [row["run"] for row in Publisher(twin).board("B", window_min=120)["trains"]] == [LOCAL]
    narrow = Publisher(twin).board("B", window_min=30)
    assert narrow["trains"] == []


def test_a_late_train_stays_on_the_board_until_it_comes(twin):
    pub = Publisher(twin)
    _late(twin, LOCAL, 90)
    twin.tick(60)  # 10:50: its 10:42 call at B is past, but it is now due at 12:12
    rows = pub.board("B", window_min=120)["trains"]
    row = next(r for r in rows if r["run"] == LOCAL)
    assert row["arr_status"].startswith("LATE")


def test_the_board_is_ordered_by_expected_time_not_timetable(twin):
    pub = Publisher(twin)
    _late(twin, LOCAL, 100)  # 59001 now due at B 12:22, after 59004 (11:55)
    runs = [row["run"] for row in pub.board("B", window_min=180)["trains"]]
    assert runs.index(OPPOSING) < runs.index(LOCAL)


def test_a_diverted_train_is_shown_as_not_calling(twin):
    pub = Publisher(twin)
    plan = twin.plan_of(LOCAL)
    diverted = NationalTwin.propagate(plan, {0: 0.0})
    diverted.frm[1] = diverted.to[0] = "X"  # the stop at B replaced by one at X (a diversion)
    diverted.s_exit[0] = diverted.s_enter[1] = None
    twin._set_plan(LOCAL, diverted)
    twin.refresh()
    row = next(r for r in pub.board("B", window_min=120)["trains"] if r["run"] == LOCAL)
    assert row["status"] == "NOT CALLING HERE (diverted)"


def test_unknown_station_is_refused(twin):
    with pytest.raises(KeyError):
        Publisher(twin).board("ZZZ")


def test_the_step_and_hold_are_minutes_people_notice():
    assert 1 < PUBLISH_STEP_MIN <= 5 and 1 < EARLIER_HOLD_MIN <= 10


# ---- over HTTP -------------------------------------------------------------------------------------------------------
def test_the_routes_publish_to_viewers_only_and_validate_inputs(twin, monkeypatch):
    from fastapi.testclient import TestClient

    from india_rail import api
    from india_rail.railguard import api as rg

    monkeypatch.setenv("RAILGUARD_VIEWER_TOKEN", "v" * 40)
    monkeypatch.setattr(rg, "_national", lambda: twin)
    http, auth = TestClient(api.app), {"Authorization": "Bearer " + "v" * 40}
    assert http.get("/railguard/national/board/B").status_code in (401, 403)
    assert http.get(f"/railguard/national/expected/{LOCAL}").status_code in (401, 403)
    board = http.get("/railguard/national/board/B?window=130", headers=auth).json()
    assert [row["run"] for row in board["trains"]] == [LOCAL, OPPOSING]
    expected = http.get(f"/railguard/national/expected/{LOCAL}", headers=auth).json()
    assert expected["stops"][1]["expected_arr"] and not any(k.startswith("_") for s in expected["stops"] for k in s)
    assert http.get("/railguard/national/board/ZZZ", headers=auth).status_code == 404
    assert http.get("/railguard/national/board/B?window=5", headers=auth).status_code == 422
    assert http.get("/railguard/national/board/B%3Cx%3E", headers=auth).status_code == 422
    assert http.get("/railguard/national/expected/00000@0", headers=auth).status_code == 404
    page = http.get("/board")
    assert page.status_code == 200 and "board.js" in page.text
