"""Tests del fix de BUG A (F3.1): backfill del estado de sesión del live screener.

El bug: `pre_high` (y demás acumuladores de sesión) son solo-memoria del WS y se
pierden al reiniciar; el snapshot REST no los recupera → un ticker que picó en
premarket antes del arranque cae del universo. El fix reconstruye TODO el estado
de sesión desde barras de minuto (REST) con `_fold_bars_into_state`, sin disparar
listeners y con merge. Ver docs/alerts/F3_ANALISIS_PREVIO.md.
"""
import asyncio
import datetime as dt
from zoneinfo import ZoneInfo

import app.services.live_screener_service as m
from app.services.live_screener_service import LiveScreenerService, TickerLiveState

ET = ZoneInfo("America/New_York")
PREV = 0.2807


def _ms(h: int, mm: int) -> int:
    """Epoch ms (ET) de las HH:MM de un día de prueba (2026-09-04)."""
    return int(dt.datetime(2026, 9, 4, h, mm, tzinfo=ET).timestamp() * 1000)


def _svc(ticker="BAOS", prev=PREV, last=0.35):
    s = LiveScreenerService()
    s._session = "pre"
    s._allowlist.add(ticker)
    st = TickerLiveState(ticker=ticker)
    st.prev_close = prev
    st.last_price = last
    s._states[ticker] = st
    return s, st


def _bar(t, h, l, v):
    return {"t": t, "h": h, "l": l, "v": v}


# ── _fold_bars_into_state ─────────────────────────────────────────────────────
def test_fold_reconstruye_premarket():
    s, st = _svc()
    s._fold_bars_into_state("BAOS", [_bar(_ms(4, 0), 0.4372, 0.29, 100000),
                                     _bar(_ms(5, 0), 0.375, 0.35, 40000)])
    assert st.pre_high == 0.4372
    assert st.pre_volume == 140000
    assert st.day_high == 0.4372
    assert st.day_low == 0.29
    assert st.day_volume == 140000


def test_fold_reconstruye_after_y_day():
    s, st = _svc()
    s._fold_bars_into_state("BAOS", [
        _bar(_ms(4, 0), 0.40, 0.30, 10000),    # premarket
        _bar(_ms(10, 0), 0.50, 0.35, 80000),   # RTH
        _bar(_ms(17, 0), 0.45, 0.38, 20000),   # afterhours
    ])
    assert st.pre_high == 0.40 and st.pre_volume == 10000
    assert st.after_high == 0.45 and st.after_low == 0.38 and st.after_volume == 20000
    assert st.day_high == 0.50          # máx en todas las ventanas
    assert st.day_low == 0.30           # mín en todas las ventanas
    assert st.day_volume == 110000      # suma de todas


def test_fold_merge_nunca_baja_ni_acumula_de_mas():
    s, st = _svc()
    st.pre_high = 0.50                    # el WS ya tenía un máximo más alto
    st.pre_volume = 200000
    s._fold_bars_into_state("BAOS", [_bar(_ms(4, 0), 0.40, 0.30, 10000)])
    assert st.pre_high == 0.50           # no baja (max-merge)
    assert st.pre_volume == 200000       # volumen por max, no se acumula (no 210000)


def test_fold_sube_cuando_el_backfill_es_mayor_e_idempotente():
    s, st = _svc()
    st.pre_high = 0.375                   # arranque tardío: máximo parcial
    s._fold_bars_into_state("BAOS", [_bar(_ms(4, 0), 0.4372, 0.29, 100000)])
    assert st.pre_high == 0.4372          # el backfill recupera el máximo real
    s._fold_bars_into_state("BAOS", [_bar(_ms(4, 0), 0.4372, 0.29, 100000)])
    assert st.pre_high == 0.4372          # idempotente


def test_fold_no_dispara_listeners():
    s, st = _svc()
    n = {"c": 0}
    s.add_aggregate_listener(lambda ev: n.__setitem__("c", n["c"] + 1))
    s._fold_bars_into_state("BAOS", [_bar(_ms(4, 0), 0.4372, 0.29, 100000)])
    assert n["c"] == 0                    # el fold NUNCA dispara listeners


def test_fold_ignora_fuera_de_allowlist():
    s, _ = _svc()
    touched = s._fold_bars_into_state("NOPE", [_bar(_ms(4, 0), 1.0, 0.9, 100)])
    assert touched is False
    assert "NOPE" not in s._states


def test_fold_bars_vacias_no_hace_nada():
    s, st = _svc()
    assert s._fold_bars_into_state("BAOS", []) is False
    assert st.pre_high is None


# ── recuperación end-to-end de BUG A ──────────────────────────────────────────
def test_backfill_recupera_del_universo():
    """Arranque tardío (05:00) via _apply_aggregate → pre_high bajo → CAE.
    Tras el fold con todo el día → recupera → PASA el universo (pmh_gap > 50)."""
    s, st = _svc()
    late = [{"sym": "BAOS", "s": _ms(5, 0), "h": 0.37489, "l": 0.35, "c": 0.36, "v": 40000},
            {"sym": "BAOS", "s": _ms(6, 0), "h": 0.35, "l": 0.33, "c": 0.34, "v": 30000}]
    for ev in late:
        s._apply_aggregate(ev)
    gap_bug = (st.pre_high / PREV - 1) * 100
    assert gap_bug < 50                   # el bug: cae del universo

    full = [{"t": _ms(4, 0), "h": 0.4372, "l": 0.29, "v": 100000},
            {"t": _ms(4, 30), "h": 0.40, "l": 0.34, "v": 50000},
            {"t": _ms(5, 0), "h": 0.37489, "l": 0.35, "v": 40000},
            {"t": _ms(6, 0), "h": 0.35, "l": 0.33, "v": 30000}]
    s._fold_bars_into_state("BAOS", full)
    gap_fixed = (st.pre_high / PREV - 1) * 100
    assert st.pre_high == 0.4372
    assert gap_fixed > 50                  # arreglado: vuelve al universo


# ── selección de movers (capa 1) ──────────────────────────────────────────────
def test_seed_selecciona_solo_movers(monkeypatch):
    monkeypatch.setattr(m, "SESSION_BACKFILL_ENABLED", True)
    monkeypatch.setattr(m, "API_KEY", "x")
    s = LiveScreenerService()
    s._session = "pre"
    for tk, last in [("MOV", 0.44), ("FLAT", 0.29)]:   # MOV +57% (mover), FLAT +3,5% (no)
        s._allowlist.add(tk)
        st = TickerLiveState(ticker=tk)
        st.prev_close = 0.28
        st.last_price = last
        s._states[tk] = st
    s._allowlist.add("NODATA")                          # sin state → no entra

    calls = []

    async def fake_many(tickers):
        calls.append(list(tickers))
        return len(tickers)

    monkeypatch.setattr(s, "_backfill_many", fake_many)
    asyncio.run(s._seed_session_state("test"))
    assert calls and calls[0] == ["MOV"]               # capa 1 = solo el mover


def test_seed_no_corre_si_desactivado(monkeypatch):
    monkeypatch.setattr(m, "SESSION_BACKFILL_ENABLED", False)
    monkeypatch.setattr(m, "API_KEY", "x")
    s, _ = _svc()
    calls = []
    monkeypatch.setattr(s, "_backfill_many", lambda t: calls.append(t))
    asyncio.run(s._seed_session_state("test"))
    assert calls == []                                 # gate OFF → no-op
