"""Fase 1 de las alarmas: barras, evaluador y —lo importante— aislamiento.

El test de aislamiento no es decorativo. El fallo peor de este módulo no es una
fuga de listado, es MANDAR LA SEÑAL DE UN USUARIO AL TELEGRAM DE OTRO, y ese bug
no se ve leyendo el código: hay que provocarlo con dos usuarios de verdad.
"""
import os
import tempfile

import pytest

from app.services.alarms.bars import SessionBars, et_minute_of_day
from app.services.alarms.evaluator import (
    RuleError,
    evaluate,
    mode_of,
    normalize_conditions,
)
from app.services.alarms import fields as F


# ── utilidades ───────────────────────────────────────────────────────────────
# 2026-08-31 09:00 ET = 13:00 UTC (EDT, UTC-4). Base para construir minutos.
BASE_MS = 1756645200_000 - 5 * 3600 * 1000   # 04:00 ET del mismo día


def _ms(minute_of_day: int, second: int = 0) -> int:
    """Epoch ms del minuto `minute_of_day` (ET) de la sesión de prueba."""
    return BASE_MS + (minute_of_day - 240) * 60_000 + second * 1000


def _feed(series: SessionBars, minute: int, prices, vol=1000.0):
    """Mete varios agregados de segundo dentro del mismo minuto."""
    closed = None
    for i, p in enumerate(prices):
        c = series.ingest(_ms(minute, i), p, p, p, p, vol / len(prices))
        if c is not None:
            closed = c
    return closed


# ── barras ───────────────────────────────────────────────────────────────────
def test_minuto_et_correcto():
    assert et_minute_of_day(_ms(240)) == 240        # 04:00
    assert et_minute_of_day(_ms(570)) == 570        # 09:30


def test_barra_se_cierra_al_cambiar_de_minuto():
    s = SessionBars("XYZ", "2026-08-31")
    assert _feed(s, 400, [3.0, 3.2, 3.1]) is None   # sigue abierta
    bar = _feed(s, 401, [3.05])                     # el primer tick del 401 cierra el 400
    assert bar is not None
    assert bar["minute"] == 400
    assert bar["high"] == pytest.approx(3.2)
    assert bar["low"] == pytest.approx(3.0)
    assert bar["close"] == pytest.approx(3.1)


def test_fuera_de_sesion_no_entra_en_la_serie():
    """La serie está anclada a las 04:00: un tick de las 03:59 no cuenta."""
    s = SessionBars("XYZ", "2026-08-31")
    assert s.ingest(_ms(239), 3.0, 3.0, 3.0, 3.0, 100.0) is None
    assert s.bar_count == 0


def test_vwap_es_acumulado_desde_el_ancla():
    s = SessionBars("XYZ", "2026-08-31")
    _feed(s, 400, [10.0], vol=100.0)
    _feed(s, 401, [20.0], vol=100.0)
    _feed(s, 402, [30.0], vol=100.0)   # cierra la 401
    # Dos barras cerradas (400 y 401) con precio típico 10 y 20, volumen 100 cada una.
    assert s.vwap() == pytest.approx(15.0)


def test_prev_bar_low_y_maximo_corrido():
    s = SessionBars("XYZ", "2026-08-31")
    _feed(s, 400, [5.0, 5.5])
    _feed(s, 401, [5.2, 4.8])
    _feed(s, 402, [4.9])
    snap = s.snapshot()
    assert snap["prev_bar_low"] == pytest.approx(5.0)   # barra 400
    assert snap["previous_max"] == pytest.approx(5.5)
    assert snap["dollar_volume"] == pytest.approx(snap["close"] * snap["bar_volume"])


def test_minutos_desde_el_ultimo_maximo():
    s = SessionBars("XYZ", "2026-08-31")
    _feed(s, 400, [9.0])       # máximo aquí
    for m in range(401, 425):
        _feed(s, m, [5.0])
    _feed(s, 425, [5.0])
    assert s.snapshot()["mins_since_high"] == 424 - 400


def test_close_stale_cierra_la_barra_de_un_ticker_parado():
    """Un ticker que deja de operar no manda más agregados; sin este barrido su
    última barra no se evaluaría jamás."""
    s = SessionBars("XYZ", "2026-08-31")
    _feed(s, 400, [3.0])
    assert s.bar_count == 0
    bar = s.close_stale(402)
    assert bar is not None and bar["minute"] == 400


# ── evaluador ────────────────────────────────────────────────────────────────
def test_varias_condiciones_se_combinan_con_and():
    """Cuatro condiciones, incluidas dos que comparan contra otro campo en vez de
    contra un número. Todas tienen que cumplirse."""
    conds = normalize_conditions([
        {"left": "close", "op": ">", "right": 1.0},
        {"left": "dollar_volume", "op": ">", "right": 100_000},
        {"left": "close", "op": "<", "right": "prev_bar_low"},
        {"left": "close", "op": ">", "right": "vwap"},
    ])
    ctx = {"close": 10.0, "dollar_volume": 250_000, "prev_bar_low": 11.0, "vwap": 9.0}
    ok, reasons = evaluate(conds, ctx)
    assert ok and len(reasons) == 4

    ctx_malo = {**ctx, "close": 12.0}   # deja de cerrar bajo el mínimo anterior
    assert evaluate(conds, ctx_malo)[0] is False


def test_un_campo_sin_valor_no_dispara():
    """None NUNCA se sustituye por 0: un 0 silencioso haría que «precio < 1» se
    cumpliera siempre y dispararía avisos que nadie sabría explicar."""
    conds = normalize_conditions([{"left": "price", "op": "<", "right": 1.0}])
    assert evaluate(conds, {"price": None})[0] is False
    assert evaluate(conds, {})[0] is False


def test_modelo_client_side_antiguo_sigue_valiendo():
    """Las reglas de las alarmas sonoras (localStorage) migran sin traducción."""
    conds = normalize_conditions([
        {"field": "change_pct", "op": "gte", "value": 20},
        {"field": "pre_pct", "op": "gte", "value": 50},   # alias de pmh_gap_pct
    ])
    assert conds[0]["op"] == ">=" and conds[1]["left"] == "pmh_gap_pct"
    assert evaluate(conds, {"change_pct": 25.0, "pmh_gap_pct": 58.0})[0] is True


def test_el_modo_se_deduce_de_los_campos():
    solo_instant = normalize_conditions([{"left": "price", "op": ">", "right": 5}])
    assert mode_of(solo_instant) == F.INSTANT
    con_barra = normalize_conditions([
        {"left": "price", "op": ">", "right": 5},
        {"left": "close", "op": ">", "right": "vwap"},
    ])
    assert mode_of(con_barra) == F.BAR


def test_cruce_sobre_campo_instantaneo_se_rechaza():
    with pytest.raises(RuleError):
        normalize_conditions([{"left": "price", "op": "crosses_above", "right": 5}])


def test_campo_desconocido_se_rechaza():
    with pytest.raises(RuleError):
        normalize_conditions([{"left": "no_existe", "op": ">", "right": 1}])


def test_cruce_usa_la_barra_anterior():
    conds = normalize_conditions([{"left": "close", "op": "crosses_below", "right": "vwap"}])
    ctx = {"close": 3.20, "vwap": 3.30}
    prev = {"close": 3.40, "vwap": 3.30}
    assert evaluate(conds, ctx, prev_lookup=prev.get)[0] is True
    # Si ya venía por debajo, no hay cruce.
    assert evaluate(conds, ctx, prev_lookup={"close": 3.10, "vwap": 3.30}.get)[0] is False


# ── aislamiento por usuario ──────────────────────────────────────────────────
@pytest.fixture
def store_tmp(monkeypatch, tmp_path):
    """`get_user_db_connection` abre 'users.duckdb' relativo al cwd: se aísla el
    test moviéndose a un directorio temporal."""
    from app.services.alarms import store as st
    monkeypatch.chdir(tmp_path)
    st._schema_ready = False
    st.ensure_schema()
    return st


def test_cada_usuario_ve_solo_sus_alarmas(store_tmp):
    st = store_tmp
    a = st.create_alarm("user_A", "Fade de A", "short", {"conditions": []})
    b = st.create_alarm("user_B", "Fade de B", "short", {"conditions": []})

    assert [x["id"] for x in st.list_alarms("user_A")] == [a["id"]]
    assert [x["id"] for x in st.list_alarms("user_B")] == [b["id"]]

    # Conocer el id de otro no basta: el GET también va filtrado por dueño.
    assert st.get_alarm("user_A", b["id"]) is None
    assert st.get_alarm("user_B", a["id"]) is None

    # Tampoco se puede editar ni borrar lo ajeno.
    assert st.update_alarm("user_A", b["id"], name="secuestrada") is None
    assert st.delete_alarm("user_A", b["id"]) is False
    assert st.get_alarm("user_B", b["id"])["name"] == "Fade de B"


def test_ninguna_fila_nace_sin_dueno(store_tmp):
    """Con la auth desactivada (solo desarrollo) el dueño es un centinela, nunca
    NULL: es exactamente la fuga que arregló b2ac1eb."""
    st = store_tmp
    st.create_alarm(None, "Alarma local", "long", {"conditions": []})
    con = st.get_user_db_connection()
    try:
        huerfanas = con.execute("SELECT COUNT(*) FROM alarms WHERE user_id IS NULL").fetchone()[0]
    finally:
        con.close()
    assert huerfanas == 0


def test_el_chat_id_viaja_con_su_dueno(store_tmp):
    """El caso peor del módulo: que el aviso de A acabe en el Telegram de B.

    Se previene porque `iter_active_alarms` trae el chat_id en el MISMO JOIN que
    el dueño, en vez de resolverlo después contra un diccionario compartido."""
    st = store_tmp
    st.create_alarm("user_A", "De A", "short", {"conditions": []})
    st.create_alarm("user_B", "De B", "short", {"conditions": []})

    tok_a = st.create_link_token("user_A")["token"]
    tok_b = st.create_link_token("user_B")["token"]
    assert st.consume_link_token(tok_a, "111111", "a") == "user_A"
    assert st.consume_link_token(tok_b, "222222", "b") == "user_B"

    por_usuario = {r["user_id"]: r["chat_id"] for r in st.iter_active_alarms()}
    assert por_usuario == {"user_A": "111111", "user_B": "222222"}


def test_el_token_de_vinculacion_es_de_un_solo_uso(store_tmp):
    st = store_tmp
    token = st.create_link_token("user_A")["token"]
    assert st.consume_link_token(token, "111111", "a") == "user_A"
    # Un segundo canjeo no puede enganchar otro teléfono a la misma cuenta.
    assert st.consume_link_token(token, "999999", "atacante") is None
    assert st.get_link("user_A")["chat_id"] == "111111"


def test_los_eventos_tambien_van_por_dueno(store_tmp):
    st = store_tmp
    a = st.create_alarm("user_A", "De A", "short", {"conditions": []})
    st.record_event(a["id"], "user_A", "XYZ", "2026-08-31", 10.0, {"x": 1})
    assert len(st.list_events("user_A")) == 1
    assert st.list_events("user_B") == []


# ── reproducción histórica ───────────────────────────────────────────────────
def test_la_reproduccion_es_causal():
    """El pmh_gap de la reproducción usa el máximo de premarket ACUMULADO hasta
    esa barra, no el del día entero. Si usara el final, avisaría a las 5:00 de
    algo que no se sabía hasta las 8:00 y no se parecería a lo que hace el motor
    en vivo — que es justo lo que la reproducción debe demostrar."""
    from app.services.alarms.replay import _instant_from_replay

    s = SessionBars("XYZ", "2026-08-31")
    _feed(s, 300, [1.5])       # premarket: máximo 1,5
    _feed(s, 301, [2.0])       # cierra la 300
    ctx = _instant_from_replay(s, s.last_bar, prev_close=1.0,
                               day_high=1.5, day_low=1.5, day_volume=1000)
    assert ctx["pmh_gap_pct"] == pytest.approx(50.0)   # 1,5 sobre 1,0

    _feed(s, 302, [4.0])       # el máximo sube DESPUÉS
    _feed(s, 303, [3.0])
    ctx_tarde = _instant_from_replay(s, s.last_bar, prev_close=1.0,
                                     day_high=4.0, day_low=1.5, day_volume=4000)
    assert ctx_tarde["pmh_gap_pct"] == pytest.approx(300.0)


def test_la_reproduccion_no_promete_lo_que_no_sabe():
    """`gap_pct` y `rvol` necesitan la apertura RTH y la media de 20 sesiones.
    Se devuelven en None explícitamente: una condición sobre ellos no se cumple,
    en vez de cumplirse con un valor inventado."""
    from app.services.alarms.replay import _instant_from_replay

    s = SessionBars("XYZ", "2026-08-31")
    _feed(s, 300, [1.5])
    _feed(s, 301, [2.0])
    ctx = _instant_from_replay(s, s.last_bar, 1.0, 1.5, 1.5, 1000)
    assert ctx["gap_pct"] is None and ctx["rvol"] is None


# ── cruce contra un campo derivado (VWAP), regresión ─────────────────────────
def test_cruce_del_vwap_dispara_en_la_barra_del_cruce():
    """«cierre cruza arriba el VWAP» debe saltar en la barra donde el cierre pasa
    de estar por debajo del VWAP a estar por encima — ni antes, ni después, ni
    nunca. Antes no saltaba jamás: prev_snapshot_value solo tenía close/open/high/
    low, así que el valor previo del VWAP era None y el cruce se descartaba."""
    conds = normalize_conditions([{"left": "close", "op": "crosses_above", "right": "vwap"}])

    s = SessionBars("XYZ", "2026-08-31")
    # Barra 1: cierre por DEBAJO de su VWAP (típico = (h+l+c)/3 > c cuando c=low).
    _feed(s, 300, [10.0, 12.0, 8.0, 9.0])   # o=10 h=12 l=8 c=9 → vwap≈9.67, close 9 < vwap
    _feed(s, 301, [10.0])                    # cierra la 300
    snap1 = s.snapshot()
    assert snap1["close"] < snap1["vwap"]    # de partida, por debajo
    assert evaluate(conds, s.snapshot(), prev_lookup=s.prev_snapshot_value)[0] is False

    # Barra siguiente que cierra CLARAMENTE por encima del VWAP acumulado → cruce.
    _feed(s, 302, [50.0])                     # cierra la 301, cierre muy por encima
    snap2 = s.snapshot()
    assert snap2["close"] > snap2["vwap"]
    assert evaluate(conds, snap2, prev_lookup=s.prev_snapshot_value)[0] is True

    # Mientras siga por encima, NO vuelve a disparar (no hay nuevo cruce).
    _feed(s, 303, [51.0])
    _feed(s, 304, [52.0])
    assert evaluate(conds, s.snapshot(), prev_lookup=s.prev_snapshot_value)[0] is False
