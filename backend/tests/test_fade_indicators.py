"""Los dos indicadores de caida (2026-08-31): "% Session Fade" y "% Fade".

    Session Fade[pm]  = (PM High  - apertura de mercado) / PM High  * 100
    Session Fade[rth] = (max. RTH - apertura del after)  / max. RTH * 100
    Fade[previous_max] = (max. previo - close) / max. previo * 100
    Fade[vwap_cross]   = (VWAP en la vela del ultimo cruce - close) / ese VWAP * 100

Los dos van en POSITIVO cuando el precio ha caido, para que la condicion se lea
igual que se dice en voz alta ("se desinflo mas de un 20%" -> "% Fade > 20").

Lo que se cubre, y por que:

  1. La ARITMETICA de cada modo, contra numeros escritos a mano.
  2. La CAUSALIDAD: "% Session Fade" es NaN hasta que abre la sesion siguiente.
     Es la propiedad que lo separa del "PM High Gap (%)" de engine.py, que usa
     el PMH final del dia (hallazgo 02 del 2026-08-29, sin arreglar a proposito).
  3. El REANCLAJE de "% Fade": si la referencia sube, el fade vuelve a caer.
  4. PARIDAD services/indicators.py <-> backtester/engine.py. Es la regla del
     repo para cualquier indicador: la via viva y la legacy no pueden divergir.
  5. Que la refactorizacion de "Previous max"/"Previous min" (el bucle por barra
     paso a ser vectorizado, y ahora lo comparte "% Fade") NO cambio su valor.
"""
import numpy as np
import pandas as pd

from app.backtester.engine import BacktestEngine
from app.schemas.strategy import IndicatorConfig, IndicatorType
from app.services.indicators import compute_indicator


# ── Utilidades ────────────────────────────────────────────────────────────

def _day(start: str, closes, highs=None, opens=None, volumes=None) -> pd.DataFrame:
    """Dia 1m sin huecos. Por defecto open=close y high=close."""
    c = np.asarray(closes, dtype=np.float64)
    h = c if highs is None else np.asarray(highs, dtype=np.float64)
    o = c if opens is None else np.asarray(opens, dtype=np.float64)
    v = np.full(len(c), 1000.0) if volumes is None else np.asarray(volumes, dtype=np.float64)
    return pd.DataFrame({
        "timestamp": pd.date_range(start, periods=len(c), freq="1min"),
        "ticker": "TEST",
        "open": o, "high": h, "low": np.minimum(o, c) - 0.01,
        "close": c, "volume": v,
    })


def _legacy(df: pd.DataFrame, **cfg) -> pd.Series:
    """La via de backtester/engine.py. `_resolve_indicator` no usa estado del
    motor mientras no haya Heikin-Ashi, asi que basta con la instancia cruda."""
    eng = object.__new__(BacktestEngine)
    return eng._resolve_indicator(IndicatorConfig(**cfg), df)


def _vivo(df: pd.DataFrame, name: str, **kw) -> pd.Series:
    """La via de services/indicators.py, la que dispara los backtests."""
    return compute_indicator(name, df, **kw)


def _paridad(df: pd.DataFrame, name: str, **kw):
    """Ambas vias, ya comprobado que coinciden. Devuelve la serie."""
    vivo = np.asarray(_vivo(df, name, **kw), dtype=np.float64)
    cfg = {k: v for k, v in kw.items() if v is not None}
    leg = np.asarray(_legacy(df, name=name, **cfg), dtype=np.float64)
    assert np.allclose(vivo, leg, equal_nan=True), (
        f"{name} {kw}: la via viva y la legacy divergen\n"
        f"  vivo={vivo[:12]}\n  legacy={leg[:12]}"
    )
    return vivo


# ── 1 y 2. "% Session Fade" ───────────────────────────────────────────────

def test_session_fade_pm_aritmetica_y_causalidad():
    """Premarket que sube a 120 y abre el mercado a 90: caida del 25%.

    Las barras premarket deben ser NaN: mientras el premercado corre, la
    apertura de mercado todavia no existe y el maximo aun puede subir.
    """
    # 08:00-08:59 premarket (60 barras), 09:30 en adelante RTH.
    pm = np.linspace(100.0, 120.0, 90)          # 08:00 -> 09:29
    rth = np.full(30, 90.0)                     # 09:30 -> 09:59
    closes = np.concatenate([pm, rth])
    opens = closes.copy()
    opens[90] = 90.0                            # apertura de mercado
    df = _day("2024-11-12 08:00", closes, opens=opens)

    fade = _paridad(df, "% Session Fade", session_ref="pm")

    assert np.isnan(fade[:90]).all(), "durante el premercado el fade no existe todavia"
    esperado = (120.0 - 90.0) / 120.0 * 100.0
    assert np.allclose(fade[90:], esperado), f"esperado {esperado}, obtenido {fade[90]}"


def test_session_fade_pm_es_constante_tras_la_apertura():
    """El fade de premercado se congela: mide la apertura, no el precio vivo."""
    pm = np.concatenate([np.full(60, 110.0), np.full(30, 105.0)])   # PMH = 110
    rth = np.array([100.0, 95.0, 90.0, 85.0, 99.0])                 # da igual
    opens = np.concatenate([pm, rth]).copy()
    df = _day("2024-11-12 08:00", np.concatenate([pm, rth]), opens=opens)

    fade = _paridad(df, "% Session Fade", session_ref="pm")
    esperado = (110.0 - 100.0) / 110.0 * 100.0
    assert np.allclose(fade[90:], esperado), "solo cuenta la vela de apertura"


def test_session_fade_rth_mide_hasta_la_apertura_del_after():
    """Modo RTH: del maximo de la sesion regular a la apertura del after."""
    # 15:00-15:59 RTH (60 barras) y 16:00+ after.
    rth = np.concatenate([np.full(30, 50.0), np.full(30, 40.0)])    # max RTH = 50
    am = np.full(10, 30.0)
    opens = np.concatenate([rth, am]).copy()
    df = _day("2024-11-12 15:00", np.concatenate([rth, am]), opens=opens)

    fade = _paridad(df, "% Session Fade", session_ref="rth")

    assert np.isnan(fade[:60]).all(), "en RTH todavia no ha abierto el after"
    esperado = (50.0 - 30.0) / 50.0 * 100.0
    assert np.allclose(fade[60:], esperado)


def test_session_fade_full_coge_el_maximo_venga_de_donde_venga():
    """Modo «dia completo»: el maximo del dia ENTERO (PM o RTH, el que gane)
    hasta la apertura del after. Es el desinflado real del dia."""
    # Premarket con maximo 150 (mas alto que el del RTH), RTH que se queda en
    # 120, y el after abriendo en 60.
    pm = np.concatenate([np.full(45, 100.0), np.full(45, 150.0)])   # 08:00-09:29
    rth = np.concatenate([np.full(30, 120.0), np.full(30, 80.0)])   # 09:30-10:29
    closes = np.concatenate([pm, rth])
    df = _day("2024-11-12 08:00", closes, opens=closes.copy())
    after = _day("2024-11-12 16:00", np.full(5, 60.0), opens=np.full(5, 60.0))
    df = pd.concat([df, after], ignore_index=True)

    fade = _paridad(df, "% Session Fade", session_ref="full")

    assert np.isnan(fade[:len(closes)]).all(), "no existe hasta que abre el after"
    esperado = (150.0 - 60.0) / 150.0 * 100.0
    assert np.allclose(fade[len(closes):], esperado), (
        f"debe medir desde el maximo del PM (150), no desde el del RTH. "
        f"Esperado {esperado}, obtenido {fade[len(closes)]}")


def test_session_fade_full_vs_rth_dan_numeros_distintos():
    """Si el maximo del dia se hizo en premarket, «full» y «rth» NO coinciden.
    Es justo la diferencia por la que existe el modo nuevo."""
    pm = np.full(90, 200.0)                                          # maximo del dia
    rth = np.concatenate([np.full(30, 100.0), np.full(30, 90.0)])    # maximo RTH = 100
    closes = np.concatenate([pm, rth])
    df = _day("2024-11-12 08:00", closes, opens=closes.copy())
    after = _day("2024-11-12 16:00", np.full(3, 50.0), opens=np.full(3, 50.0))
    df = pd.concat([df, after], ignore_index=True)

    i = len(closes)
    full = _paridad(df, "% Session Fade", session_ref="full")
    rth_only = _paridad(df, "% Session Fade", session_ref="rth")

    assert np.allclose(full[i], (200.0 - 50.0) / 200.0 * 100.0)       # 75%
    assert np.allclose(rth_only[i], (100.0 - 50.0) / 100.0 * 100.0)   # 50%


def test_session_fade_negativo_si_abre_por_encima():
    """No es un valor absoluto: si la apertura supera al maximo, sale negativo."""
    pm = np.full(90, 100.0)
    rth = np.full(5, 110.0)
    opens = np.concatenate([pm, rth]).copy()
    df = _day("2024-11-12 08:00", np.concatenate([pm, rth]), opens=opens)

    fade = _paridad(df, "% Session Fade", session_ref="pm")
    assert np.allclose(fade[90:], -10.0), "abrir un 10% arriba es un fade de -10"


def test_session_fade_sin_sesion_siguiente_es_todo_nan():
    """Un dia que acaba antes de las 09:30 no tiene fade de premercado."""
    df = _day("2024-11-12 08:00", np.linspace(100.0, 120.0, 60))
    fade = _paridad(df, "% Session Fade", session_ref="pm")
    assert np.isnan(fade).all()


# ── 3. "% Fade" ───────────────────────────────────────────────────────────

def test_fade_previous_max_aritmetica():
    """El maximo previo NO incluye la barra actual (shift de 1)."""
    closes = np.array([100.0, 110.0, 105.0, 90.0, 95.0])
    df = _day("2024-11-12 08:00", closes)

    fade = _paridad(df, "% Fade", fade_ref="previous_max", ap_session="ap.PM")

    # max previo: [nan, 100, 110, 110, 110]
    assert np.isnan(fade[0]), "en la primera barra no hay maximo previo"
    assert np.allclose(fade[1], (100.0 - 110.0) / 100.0 * 100.0)   # -10, va por encima
    assert np.allclose(fade[2], (110.0 - 105.0) / 110.0 * 100.0)
    assert np.allclose(fade[3], (110.0 - 90.0) / 110.0 * 100.0)    # caida del 18,18%
    assert np.allclose(fade[4], (110.0 - 95.0) / 110.0 * 100.0)


def test_fade_previous_max_se_reancla_al_hacer_maximo_nuevo():
    """Sube, cae un 20%, vuelve a maximos: el fade tiene que volver a bajar."""
    closes = np.array([100.0, 100.0, 80.0, 80.0, 130.0, 120.0])
    df = _day("2024-11-12 08:00", closes)
    fade = _paridad(df, "% Fade", fade_ref="previous_max", ap_session="ap.PM")

    assert np.allclose(fade[2], 20.0), "cae de 100 a 80 = 20%"
    # Tras el maximo de 130, el fade se mide contra 130, no contra 100.
    assert np.allclose(fade[5], (130.0 - 120.0) / 130.0 * 100.0)


def test_fade_previous_max_respeta_ap_session():
    """Con ap.RTH el maximo no empieza a contar hasta las 09:30."""
    closes = np.concatenate([np.full(90, 200.0), np.array([100.0, 90.0, 95.0])])
    df = _day("2024-11-12 08:00", closes)

    fade = _paridad(df, "% Fade", fade_ref="previous_max", ap_session="ap.RTH")

    assert np.isnan(fade[:91]).all(), "el maximo de RTH no existe antes de las 09:30"
    # 09:31: el maximo previo es el de las 09:30 (100), no el 200 del premercado.
    assert np.allclose(fade[91], (100.0 - 90.0) / 100.0 * 100.0)


def test_fade_vwap_cross_ancla_en_la_vela_del_cruce():
    """Sube por encima del VWAP, lo cruza a la baja y sigue cayendo.

    La referencia es el VWAP DE LA VELA DEL CRUCE, no el VWAP vivo: por eso el
    fade sigue creciendo aunque el VWAP tambien baje.
    """
    closes = np.array([100.0, 100.0, 100.0, 100.0, 90.0, 80.0, 70.0])
    df = _day("2024-11-12 08:00", closes)

    fade = _paridad(df, "% Fade", fade_ref="vwap_cross")

    # Con precio plano a 100 no hay cruce: NaN hasta que el precio se va abajo.
    assert np.isnan(fade[:4]).all(), "sin cruce todavia no hay desde donde medir"

    ref = float(np.asarray(fade)[4])
    assert not np.isnan(ref), "la vela que rompe el VWAP a la baja ancla la medida"
    # La referencia queda fija: el fade crece monotonamente mientras el precio cae.
    assert fade[4] < fade[5] < fade[6], "el ancla no se mueve, asi que la caida se acumula"


def test_fade_vwap_cross_se_reancla_en_cada_cruce():
    """Cruza abajo, vuelve a cruzar arriba: la referencia cambia."""
    closes = np.array([100.0, 100.0, 90.0, 85.0, 120.0, 130.0, 110.0])
    df = _day("2024-11-12 08:00", closes)
    fade = _paridad(df, "% Fade", fade_ref="vwap_cross")

    # Tras volver arriba del VWAP el fade es negativo (precio por encima del ancla).
    assert fade[5] < 0, "por encima del ancla el fade es negativo"


def test_fade_vwap_cross_sin_volumen_no_inventa_cruces():
    """Velas sin volumen: el VWAP es NaN y el paso NaN->numero no es un cruce."""
    closes = np.array([100.0, 100.0, 100.0, 90.0])
    df = _day("2024-11-12 08:00", closes, volumes=np.array([0.0, 0.0, 1000.0, 1000.0]))
    fade = _paridad(df, "% Fade", fade_ref="vwap_cross")
    assert np.isnan(fade[:3]).all(), "el arranque del VWAP no cuenta como cruce"


# ── 4. Paridad y 5. la refactorizacion de Previous max ────────────────────

def _previous_extreme_bucle(df, values, ap_session, which):
    """El bucle por barra que habia antes de vectorizar (copia literal)."""
    timestamps = pd.to_datetime(df["timestamp"])
    hours, minutes = timestamps.dt.hour, timestamps.dt.minute
    if ap_session == "ap.RTH":
        start_mask = (hours > 9) | ((hours == 9) & (minutes >= 30))
    elif ap_session == "ap.AM":
        start_mask = hours >= 16
    else:
        start_mask = pd.Series(True, index=df.index)
    result = pd.Series(np.nan, index=df.index)
    running, started = np.nan, False
    for i in range(len(df)):
        if not started and start_mask.iloc[i]:
            started = True
        if started:
            if np.isnan(running):
                running = values.iloc[i]
            else:
                running = max(running, values.iloc[i]) if which == "max" else min(running, values.iloc[i])
            result.iloc[i] = running
    return result.shift(1)


def test_previous_max_min_vectorizado_da_lo_mismo_que_el_bucle():
    """La refactorizacion no puede mover ni un decimal de los backtests viejos."""
    rng = np.random.default_rng(7)
    closes = 100.0 + np.cumsum(rng.normal(0, 1.0, 200))
    df = _day("2024-11-12 08:00", closes, highs=closes + 0.5)

    for sesion in ("ap.PM", "ap.RTH", "ap.AM"):
        esperado_max = _previous_extreme_bucle(df, df["high"], sesion, "max")
        obtenido_max = _vivo(df, "Previous max", ap_session=sesion)
        assert np.allclose(obtenido_max, esperado_max, equal_nan=True), f"Previous max {sesion}"

        esperado_min = _previous_extreme_bucle(df, df["low"], sesion, "min")
        obtenido_min = _vivo(df, "Previous min", ap_session=sesion)
        assert np.allclose(obtenido_min, esperado_min, equal_nan=True), f"Previous min {sesion}"


def test_paridad_vias_con_dia_aleatorio():
    """Paridad viva<->legacy sobre ruido, no solo sobre casos escritos a mano."""
    rng = np.random.default_rng(11)
    closes = 50.0 + np.cumsum(rng.normal(0, 0.4, 540))       # 08:00 -> 17:00
    df = _day("2024-11-12 08:00", closes, highs=closes + 0.3,
              volumes=rng.uniform(100, 5000, 540))

    _paridad(df, "% Session Fade", session_ref="pm")
    _paridad(df, "% Session Fade", session_ref="rth")
    _paridad(df, "% Session Fade", session_ref="full")
    _paridad(df, "% Fade", fade_ref="previous_max", ap_session="ap.PM")
    _paridad(df, "% Fade", fade_ref="previous_max", ap_session="ap.RTH")
    _paridad(df, "% Fade", fade_ref="vwap_cross")


def test_defectos_de_los_parametros():
    """Sin parametro: Session Fade cae a "pm" y Fade a "previous_max"."""
    rng = np.random.default_rng(3)
    closes = 20.0 + np.cumsum(rng.normal(0, 0.2, 200))
    df = _day("2024-11-12 08:00", closes, highs=closes + 0.2)

    assert np.allclose(_vivo(df, "% Session Fade"),
                       _vivo(df, "% Session Fade", session_ref="pm"), equal_nan=True)
    assert np.allclose(_vivo(df, "% Fade"),
                       _vivo(df, "% Fade", fade_ref="previous_max"), equal_nan=True)


def test_los_dos_nombres_estan_en_el_enum():
    """Si el enum no los tiene, guardar la estrategia devuelve 422 (caso Darvas)."""
    assert IndicatorType.SESSION_FADE.value == "% Session Fade"
    assert IndicatorType.FADE.value == "% Fade"
