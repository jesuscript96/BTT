"""BUG B (F4): las alarmas INSTANTÁNEAS deben respetar la franja horaria.

Antes, el camino instantáneo (`_tick_instant`) disparaba justo tras `evaluate`
sin comprobar la ventana; solo el camino de barra (`_bar_worker`) usaba
`_in_window`. → una alarma instantánea con franja avisaba fuera de ella.
"""
import asyncio

import app.services.alarms.engine as eng_mod
import app.services.live_screener_service as lss
from app.services.alarms.engine import AlarmEngine, _today_key


def _alarm(window=None):
    return {"id": "a1", "name": "t", "side": "long", "definition": {
        "conditions": [{"left": "price", "op": ">", "right": 0}],   # instantánea, siempre cierta
        "universe": [],
        "watchlist": ["AAPL"],
        "window": window,                                           # {"from":"09:00","to":"10:00"} = 540..600
        "channels": {"browser": True, "telegram": False, "sound": False},
    }}


def _run(now_minute, monkeypatch, window={"from": "09:00", "to": "10:00"}):
    eng = AlarmEngine()
    eng._session_date = _today_key()          # evita _refresh_splits
    alarm = _alarm(window)
    eng._alarms = [alarm]
    eng._compiled = {"a1": eng._compile(alarm)}
    monkeypatch.setattr(lss.live_screener_service, "snapshot_metrics",
                        lambda: [{"ticker": "AAPL", "price": 10.0}])
    monkeypatch.setattr(eng_mod, "_now_minute", lambda: now_minute)
    fired = []

    async def rec(*a, **k):
        fired.append(a[2])                    # a = (alarm, plan, ticker, ...)

    monkeypatch.setattr(eng, "_fire", rec)
    asyncio.run(eng._tick_instant())
    return fired


def test_instantanea_dispara_dentro_de_la_franja(monkeypatch):
    assert _run(570, monkeypatch) == ["AAPL"]        # 09:30, dentro de 09:00-10:00


def test_instantanea_no_dispara_fuera_de_la_franja(monkeypatch):
    assert _run(480, monkeypatch) == []              # 08:00, fuera → no dispara (fix BUG B)


def test_instantanea_no_dispara_pasada_la_franja(monkeypatch):
    assert _run(660, monkeypatch) == []              # 11:00, después de las 10:00 → no dispara


def test_instantanea_sin_franja_dispara_siempre(monkeypatch):
    assert _run(480, monkeypatch, window=None) == ["AAPL"]   # sin ventana → cualquier hora
