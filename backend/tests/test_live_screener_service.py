"""
Unit tests for the live screener service (pure, no network).

Validates the trading formulas (§3.2 of the PRD), the tab filters/order, the
aggregate-message handling and the ET session clock by injecting in-RAM state
directly into a fresh service instance.
"""
from datetime import datetime
from zoneinfo import ZoneInfo
import asyncio

import pytest

from app.services.live_screener_service import (
    LiveScreenerService,
    TickerLiveState,
    current_session,
    _ts_in_rth,
    _ts_in_pre,
    _ts_in_after,
    ET,
    TAB_GAINERS,
    TAB_LOSERS,
    TAB_PRE,
    TAB_AFT,
)


def _svc_with(states):
    svc = LiveScreenerService()
    svc._session = "rth"
    for st in states:
        svc._states[st.ticker] = st
    svc._allowlist = {st.ticker for st in states}
    return svc


def _state(ticker, prev_close, last_price, **kw):
    return TickerLiveState(ticker=ticker, prev_close=prev_close, last_price=last_price, **kw)


class TestMetrics:
    def test_change_and_gap_formulas(self):
        svc = LiveScreenerService()
        st = _state(
            "AAA", prev_close=10.0, last_price=12.0,
            day_high=13.0, day_low=9.5, day_open=11.0, rth_close=10.0,
            day_volume=500_000, avg_vol_20d=100_000,
        )
        m = svc._metrics(st)
        assert m["change_pct"] == pytest.approx(20.0)            # (12/10 - 1)*100  (day change)
        assert m["day_change_pct"] == pytest.approx(20.0)
        assert m["gap_pct"] == pytest.approx(10.0)               # (11/10 - 1)*100  (open gap)
        assert m["return_pct"] == pytest.approx(9.09, abs=0.01)  # (12/11 - 1)*100
        assert m["after_pct"] == pytest.approx(20.0)             # (12/10 - 1)*100  (from rth_close)
        assert m["high"] == pytest.approx(13.0)
        assert m["rvol"] == pytest.approx(5.0)                   # 500k / 100k

    def test_after_pct_is_none_without_rth_close(self):
        svc = LiveScreenerService()
        m = svc._metrics(_state("B", 10.0, 12.0, day_volume=200_000))
        assert m["after_pct"] is None
        assert m["change_pct"] == pytest.approx(20.0)  # day change still computable

    def test_rvol_defaults_to_one_without_avg_volume(self):
        svc = LiveScreenerService()
        m = svc._metrics(_state("BBB", 5.0, 6.0, day_volume=200_000, avg_vol_20d=None))
        assert m["rvol"] == 1.0

    def test_discards_record_without_prev_close(self):
        svc = LiveScreenerService()
        assert svc._metrics(_state("CCC", None, 6.0)) is None
        assert svc._metrics(_state("DDD", 0.0, 6.0)) is None
        assert svc._metrics(_state("EEE", 10.0, None)) is None


class TestGetTop:
    def test_no_volume_gate_includes_thin_names(self):
        # No liquidity gate: even a thinly-traded ticker ranks if it has a price
        # and a prev_close (the tab metric is the only criterion now).
        svc = _svc_with([_state("THIN", 10.0, 12.0, day_volume=10_000)])
        assert [r["ticker"] for r in svc.get_top(TAB_GAINERS)] == ["THIN"]

    def test_gainers_order_no_pct_threshold(self):
        # No % threshold: every advancing ticker with volume qualifies, sorted desc.
        svc = _svc_with([
            _state("UP25", 10.0, 12.5, day_volume=1_000_000),   # +25%
            _state("UP22", 10.0, 12.2, day_volume=1_000_000),   # +22%
            _state("UP10", 10.0, 11.0, day_volume=1_000_000),   # +10% (would've been excluded before)
            _state("DN05", 10.0, 9.5, day_volume=1_000_000),    # -5% (decline → not a gainer)
        ])
        rows = svc.get_top(TAB_GAINERS)
        assert [r["ticker"] for r in rows] == ["UP25", "UP22", "UP10"]

    def test_losers_order_no_pct_threshold(self):
        # No % threshold: every declining ticker with volume qualifies, most negative first.
        svc = _svc_with([
            _state("DN25", 10.0, 7.5, day_volume=1_000_000),    # -25%
            _state("DN21", 10.0, 7.9, day_volume=1_000_000),    # -21%
            _state("DN05", 10.0, 9.5, day_volume=1_000_000),    # -5% (would've been excluded before)
        ])
        rows = svc.get_top(TAB_LOSERS)
        assert [r["ticker"] for r in rows] == ["DN25", "DN21", "DN05"]
        assert rows[0]["change_pct"] < rows[1]["change_pct"] < rows[2]["change_pct"]

    def test_aftermarket_tab_ranks_by_after_pct_no_threshold(self):
        # No % threshold: Aftermarket ranks by after_pct (from the RTH close).
        # RTH30 = +30% day but FLAT in after (after_pct 0); AFT25 = +25% in after.
        svc = _svc_with([
            _state("RTH30", prev_close=10.0, last_price=13.0, rth_close=13.0, day_volume=1_000_000),
            _state("AFT25", prev_close=10.0, last_price=12.5, rth_close=10.0, day_volume=1_000_000),
        ])
        rows = svc.get_top(TAB_AFT)
        # Ranked by after_pct desc — RTH30 still shows (no threshold), just last:
        assert [r["ticker"] for r in rows] == ["AFT25", "RTH30"]
        # ...and RTH30 leads the day-long Gainers tab (it is +30% on the day):
        assert [r["ticker"] for r in svc.get_top(TAB_GAINERS)] == ["RTH30", "AFT25"]

    def test_aftermarket_drops_ticker_without_rth_close(self):
        # No rth_close → after_pct is None → never qualifies for Aftermarket.
        svc = _svc_with([
            _state("NORC", prev_close=10.0, last_price=13.0, day_volume=1_000_000),
        ])
        assert svc.get_top(TAB_AFT) == []
        assert [r["ticker"] for r in svc.get_top(TAB_GAINERS)] == ["NORC"]

    def test_premarket_ranks_by_pre_pct_and_drops_no_pre_datum(self):
        # Premarket ranks by the pre-market peak gap (pre_pct from pre_high).
        svc = _svc_with([
            _state("PMH", 10.0, 10.5, pre_high=12.2, day_volume=1_000_000),   # pre_pct +22%
            _state("NOPRE", 10.0, 10.5, day_volume=1_000_000),               # no pre datum
        ])
        # Only the ticker with a pre datum qualifies (no % threshold otherwise):
        assert [r["ticker"] for r in svc.get_top(TAB_PRE)] == ["PMH"]

    def test_top_50_cap(self):
        states = [
            _state(f"T{i:03d}", 10.0, 10.0 + 0.1 * (i + 16), day_volume=1_000_000)
            for i in range(60)
        ]
        svc = _svc_with(states)
        rows = svc.get_top(TAB_GAINERS)
        assert len(rows) == 50


class TestAggregate:
    def test_apply_aggregate_updates_day_state(self):
        svc = _svc_with([_state("XYZ", 10.0, 10.0, day_high=10.0, day_low=10.0)])
        # Polygon second-aggregate: accumulated daily volume is `av`; new high/low;
        # last close `c`. No timestamp → no per-window accumulation.
        svc._apply_aggregate({"ev": "A", "sym": "XYZ", "c": 12.0, "h": 12.5, "l": 9.8, "av": 750_000})
        st = svc._states["XYZ"]
        assert st.last_price == 12.0
        assert st.day_high == 12.5
        assert st.day_low == 9.8
        assert st.day_volume == 750_000

    def test_apply_aggregate_sums_bar_volume_without_av(self):
        svc = _svc_with([_state("XYZ", 10.0, 10.0, day_volume=100_000)])
        svc._apply_aggregate({"ev": "A", "sym": "XYZ", "c": 11.0, "v": 50_000})  # per-bar v
        assert svc._states["XYZ"].day_volume == 150_000  # 100k + 50k

    def test_apply_aggregate_accumulates_after_window(self):
        svc = _svc_with([_state("XYZ", 10.0, 10.0, rth_close=10.0)])
        svc._session = "after"
        after_ts = int(datetime(2024, 1, 8, 17, 0, tzinfo=ET).timestamp() * 1000)  # Mon 17:00 ET
        svc._apply_aggregate({"ev": "A", "sym": "XYZ", "c": 12.0, "h": 12.5, "l": 11.8, "v": 30_000, "s": after_ts})
        st = svc._states["XYZ"]
        assert st.after_volume == 30_000
        assert st.after_high == 12.5
        assert st.after_low == 11.8

    def test_apply_aggregate_ignores_unknown_symbol(self):
        svc = _svc_with([_state("XYZ", 10.0, 10.0)])
        svc._apply_aggregate({"ev": "A", "sym": "NOPE", "c": 5.0, "av": 999_999})
        assert "NOPE" not in svc._states

    def test_apply_aggregate_drops_non_allowlisted(self):
        # A symbol present in state but NOT in the allow-list is dropped (PRD §05.3).
        svc = _svc_with([_state("XYZ", 10.0, 10.0)])
        svc._states["ABC"] = _state("ABC", 5.0, 5.0)  # in state, not allow-listed
        svc._apply_aggregate({"ev": "A", "sym": "ABC", "c": 9.0, "av": 999_999})
        assert svc._states["ABC"].last_price == 5.0  # unchanged → was dropped

    def test_apply_aggregate_freezes_when_closed(self):
        svc = _svc_with([_state("XYZ", 10.0, 10.0, day_high=10.0, day_volume=100_000)])
        svc._session = "closed"
        svc._apply_aggregate({"ev": "A", "sym": "XYZ", "c": 12.0, "h": 12.5, "av": 750_000})
        st = svc._states["XYZ"]
        assert st.last_price == 10.0
        assert st.day_high == 10.0
        assert st.day_volume == 100_000

    def test_day_open_captured_inside_regular_hours(self):
        svc = _svc_with([_state("OPN", 10.0, 11.0)])
        rth_ts = int(datetime(2024, 1, 8, 10, 0, tzinfo=ET).timestamp() * 1000)  # Mon 10:00 ET
        svc._apply_aggregate({"ev": "A", "sym": "OPN", "c": 11.0, "o": 10.8, "s": rth_ts})
        assert svc._states["OPN"].day_open == 10.8


class TestSessionTransitions:
    def test_reset_day_clears_accumulators_and_uses_rth_close_as_prev_close(self):
        svc = _svc_with([
            _state(
                "XYZ", prev_close=9.0, last_price=12.0,
                day_high=12.5, day_low=8.8, day_volume=900_000,
                day_open=10.0, rth_close=11.75, after_volume=5_000, pre_high=9.5,
            )
        ])
        svc._top_cache["RTH Gainers"] = (123.0, [{"ticker": "XYZ"}])
        svc._refresh_from_snapshot = lambda: None

        svc._reset_day()

        st = svc._states["XYZ"]
        assert st.prev_close == 11.75            # yesterday's RTH close carried into prev_close
        assert st.rth_close is None
        assert st.last_price is None
        assert st.day_high is None
        assert st.day_low is None
        assert st.day_volume == 0.0
        assert st.day_open is None
        assert st.after_volume == 0.0
        assert st.pre_high is None
        assert svc._top_cache == {}

    def test_reset_day_without_rth_close_waits_for_snapshot_prev_close(self):
        svc = _svc_with([_state("XYZ", 9.0, 12.0, day_volume=900_000)])
        svc._refresh_from_snapshot = lambda: None

        svc._reset_day()

        assert svc._states["XYZ"].prev_close is None

    def test_rth_to_after_transition_captures_rth_close_and_inits_after_window(self):
        svc = _svc_with([
            _state("XYZ", 10.0, 11.25, after_volume=999_000, after_high=99.0),
            _state("EMPTY", 10.0, None),
        ])
        svc._session = "rth"

        asyncio.run(svc._handle_session_transition("after"))

        assert svc._session == "after"
        assert svc._states["XYZ"].rth_close == 11.25      # captured at the close
        assert svc._states["XYZ"].after_volume == 0.0      # fresh after accumulator
        assert svc._states["XYZ"].after_high is None
        assert svc._states["EMPTY"].rth_close is None
        # Day metrics are NOT reset on this intra-day transition:
        assert svc._states["XYZ"].prev_close == 10.0

    def test_intraday_transitions_do_not_reset_day(self):
        # day_* must persist across pre → rth → after (only closed → active resets).
        svc = _svc_with([_state("UP25", 10.0, 12.5, day_volume=1_000_000, day_high=12.5)])
        svc._refresh_from_snapshot = lambda: None
        calls = {"reset_day": 0}
        orig = svc._reset_day

        def counting_reset():
            calls["reset_day"] += 1
            orig()

        svc._reset_day = counting_reset
        svc._session = "pre"
        asyncio.run(svc._handle_session_transition("rth"))    # intra-day
        asyncio.run(svc._handle_session_transition("after"))  # intra-day
        assert calls["reset_day"] == 0
        st = svc._states["UP25"]
        assert st.day_volume == 1_000_000      # persisted
        assert st.day_high == 12.5
        assert st.rth_close == 12.5            # captured at rth→after

    def test_closed_to_active_transition_resets_day_once(self):
        svc = _svc_with([_state("XYZ", 10.0, 11.25, day_volume=500_000)])
        svc._session = "closed"
        called = {"reset": 0}

        def fake_reset():
            called["reset"] += 1

        svc._reset_day = fake_reset

        asyncio.run(svc._handle_session_transition("pre"))

        assert svc._session == "pre"
        assert called["reset"] == 1


class TestSessionClock:
    @pytest.mark.parametrize("hh,mm,expected", [
        (5, 0, "pre"), (9, 0, "pre"),
        (9, 30, "rth"), (12, 0, "rth"), (15, 59, "rth"),
        (16, 0, "after"), (19, 0, "after"),
        (21, 0, "closed"), (3, 0, "closed"),
    ])
    def test_weekday_sessions(self, hh, mm, expected):
        dt = datetime(2024, 1, 8, hh, mm, tzinfo=ET)  # Monday
        assert current_session(dt) == expected

    def test_weekend_is_closed(self):
        assert current_session(datetime(2024, 1, 6, 12, 0, tzinfo=ET)) == "closed"  # Saturday

    def test_ts_windows(self):
        rth = int(datetime(2024, 1, 8, 10, 0, tzinfo=ET).timestamp() * 1000)
        pre = int(datetime(2024, 1, 8, 7, 0, tzinfo=ET).timestamp() * 1000)
        aft = int(datetime(2024, 1, 8, 17, 0, tzinfo=ET).timestamp() * 1000)
        assert _ts_in_rth(rth) is True and _ts_in_pre(rth) is False and _ts_in_after(rth) is False
        assert _ts_in_pre(pre) is True and _ts_in_rth(pre) is False
        assert _ts_in_after(aft) is True and _ts_in_rth(aft) is False
        assert _ts_in_rth(None) is False


class TestOutlierGate:
    def test_moves_beyond_500pct_are_dropped(self):
        svc = _svc_with([
            _state("REAL", 10.0, 14.0, day_volume=1_000_000),   # +40% ok
            _state("CORRUPT", 1.0, 10.0, day_volume=1_000_000), # +900% -> outlier
        ])
        tickers = [r["ticker"] for r in svc.get_top(TAB_GAINERS)]
        assert "REAL" in tickers and "CORRUPT" not in tickers
