"""
Unit tests for the live screener service (pure, no network).

Validates the trading formulas (§3.2 of the PRD), the tab filters/order, the
aggregate-message handling and the ET session clock by injecting in-RAM state
directly into a fresh service instance.
"""
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.services.live_screener_service import (
    LiveScreenerService,
    TickerLiveState,
    current_session,
    _ts_in_rth,
    ET,
    TAB_GAINERS,
    TAB_LOSERS,
    TAB_PRE,
    TAB_AFT,
)


def _svc_with(states):
    svc = LiveScreenerService()
    for st in states:
        svc._states[st.ticker] = st
    return svc


def _state(ticker, prev_close, last_price, **kw):
    return TickerLiveState(ticker=ticker, prev_close=prev_close, last_price=last_price, **kw)


class TestMetrics:
    def test_change_and_gap_formulas(self):
        svc = LiveScreenerService()
        st = _state(
            "AAA", prev_close=10.0, last_price=12.0,
            session_high=13.0, session_low=9.5, rth_open=11.0,
            session_volume=500_000, avg_vol_20d=100_000,
        )
        m = svc._metrics(st)
        assert m["change_pct"] == pytest.approx(20.0)          # (12/10 - 1)*100
        assert m["pmh_gap_pct"] == pytest.approx(30.0)         # (13/10 - 1)*100
        assert m["gap_pct"] == pytest.approx(10.0)             # (11/10 - 1)*100
        assert m["return_pct"] == pytest.approx(9.09, abs=0.01)  # (12/11 - 1)*100
        assert m["rvol"] == pytest.approx(5.0)                 # 500k / 100k

    def test_rvol_defaults_to_one_without_avg_volume(self):
        svc = LiveScreenerService()
        m = svc._metrics(_state("BBB", 5.0, 6.0, session_volume=200_000, avg_vol_20d=None))
        assert m["rvol"] == 1.0

    def test_discards_record_without_prev_close(self):
        svc = LiveScreenerService()
        assert svc._metrics(_state("CCC", None, 6.0)) is None
        assert svc._metrics(_state("DDD", 0.0, 6.0)) is None
        assert svc._metrics(_state("EEE", 10.0, None)) is None


class TestGetTop:
    def test_volume_floor_excludes_thin_names(self):
        # +20% move but only 10k volume -> filtered out (< 50k floor).
        svc = _svc_with([_state("THIN", 10.0, 12.0, session_volume=10_000)])
        assert svc.get_top(TAB_GAINERS) == []

    def test_gainers_threshold_and_order(self):
        svc = _svc_with([
            _state("UP25", 10.0, 12.5, session_volume=1_000_000),   # +25%
            _state("UP18", 10.0, 11.8, session_volume=1_000_000),   # +18%
            _state("UP10", 10.0, 11.0, session_volume=1_000_000),   # +10% (below 15)
        ])
        rows = svc.get_top(TAB_GAINERS)
        assert [r["ticker"] for r in rows] == ["UP25", "UP18"]      # sorted desc, UP10 excluded

    def test_losers_threshold_and_order(self):
        svc = _svc_with([
            _state("DN20", 10.0, 8.0, session_volume=1_000_000),    # -20%
            _state("DN16", 10.0, 8.4, session_volume=1_000_000),    # -16%
            _state("DN05", 10.0, 9.5, session_volume=1_000_000),    # -5% (above -15)
        ])
        rows = svc.get_top(TAB_LOSERS)
        # Most negative first (ascending change_pct), -5% excluded.
        assert [r["ticker"] for r in rows] == ["DN20", "DN16"]
        assert rows[0]["change_pct"] < rows[1]["change_pct"]

    def test_premarket_qualifies_on_session_high_gap(self):
        # Price only +5% now, but session high hit +18% -> qualifies in Premarket.
        svc = _svc_with([
            _state("PMH", 10.0, 10.5, session_high=11.8, session_volume=1_000_000),
        ])
        assert [r["ticker"] for r in svc.get_top(TAB_PRE)] == ["PMH"]
        # ...but not in RTH Gainers, where only live change counts.
        assert svc.get_top(TAB_GAINERS) == []

    def test_top_50_cap(self):
        states = [
            _state(f"T{i:03d}", 10.0, 10.0 + 0.1 * (i + 16), session_volume=1_000_000)
            for i in range(60)
        ]
        svc = _svc_with(states)
        rows = svc.get_top(TAB_GAINERS)
        assert len(rows) == 50


class TestAggregate:
    def test_apply_aggregate_updates_state(self):
        svc = _svc_with([_state("XYZ", 10.0, 10.0, session_high=10.0, session_low=10.0)])
        # Accumulated daily volume 'a', new high/low, last close 'c'.
        svc._apply_aggregate({"ev": "A", "sym": "XYZ", "c": 12.0, "h": 12.5, "l": 9.8, "a": 750_000})
        st = svc._states["XYZ"]
        assert st.last_price == 12.0
        assert st.session_high == 12.5
        assert st.session_low == 9.8
        assert st.session_volume == 750_000

    def test_apply_aggregate_ignores_unknown_symbol(self):
        svc = _svc_with([_state("XYZ", 10.0, 10.0)])
        svc._apply_aggregate({"ev": "A", "sym": "NOPE", "c": 5.0, "a": 999_999})
        assert "NOPE" not in svc._states

    def test_rth_open_captured_inside_regular_hours(self):
        svc = _svc_with([_state("OPN", 10.0, 11.0)])
        rth_ts = int(datetime(2024, 1, 8, 10, 0, tzinfo=ET).timestamp() * 1000)  # Mon 10:00 ET
        svc._apply_aggregate({"ev": "A", "sym": "OPN", "c": 11.0, "o": 10.8, "s": rth_ts})
        assert svc._states["OPN"].rth_open == 10.8


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

    def test_ts_in_rth(self):
        assert _ts_in_rth(int(datetime(2024, 1, 8, 10, 0, tzinfo=ET).timestamp() * 1000)) is True
        assert _ts_in_rth(int(datetime(2024, 1, 8, 5, 0, tzinfo=ET).timestamp() * 1000)) is False
        assert _ts_in_rth(None) is False
