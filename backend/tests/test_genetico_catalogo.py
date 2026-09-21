"""El catálogo del genético contra el motor de verdad.

POR QUÉ ESTE FICHERO EXISTE. Un nombre de indicador mal escrito en el catálogo
**no da ningún error**: la condición se evalúa como falsa, el individuo no opera
nunca, saca nota 0 y el genético lo descarta por malo. El gen desaparece de la
búsqueda y nadie se entera — no hay excepción, ni log, ni un 422. Es el mismo
fallo silencioso de las tres capas de la definición de estrategia, y con el
catálogo recién ampliado a 24 indicadores es donde más fácil se cuela.

Así que aquí no se prueba lógica: se prueba que **todo lo que el catálogo
ofrece, el motor lo sabe calcular**.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# El paquete `genetico` vive en la raíz del repo, no dentro de backend.
RAIZ = Path(__file__).resolve().parents[2]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from genetico import catalogo as C          # noqa: E402
from genetico import cromosoma as X         # noqa: E402


def _velas(n=600):
    """Un día sintético que LLEGA AL RTH, no solo el premercado.

    600 minutos desde las 04:00 pasan de las 09:30, y eso hace falta: el
    «% Session Fade» mide del máximo de una sesión a la apertura de la
    SIGUIENTE, así que con solo premercado sale todo NaN y aquí se leería como
    que el motor no conoce el nombre. Los indicadores de sesión necesitan que
    la sesión exista.
    """
    idx = pd.date_range("2026-01-05 04:00", periods=n, freq="1min", tz="America/New_York")
    paso = np.sin(np.arange(n) / 9.0) * 0.25
    close = 10.0 + np.cumsum(np.full(n, 0.004)) + paso
    return pd.DataFrame({
        "timestamp": idx, "open": close - 0.02, "high": close + 0.06,
        "low": close - 0.06, "close": close, "volume": np.full(n, 40_000.0),
    })


# ── Los nombres, que es lo que se cae en silencio ────────────────────────

# `daily_stats` lo necesitan los de gap para saber contra qué comparar. Sin él
# devuelven NaN entero, que aquí se leería como «el motor no lo conoce».
STATS = {"prev_close": 8.0, "pm_high": 12.0, "pm_low": 9.0,
         "rth_open": 10.5, "open": 10.0, "gap_pct": 25.0, "pmh_gap_pct": 50.0}


def _calcula(nombre: str, params: dict):
    """Llama al motor como lo llama el motor: argumentos por nombre.

    `compute_indicator(name, df, period=..., band_line=...)` — no un dict de
    configuración, que es la forma que viaja en la definición de estrategia y
    la que traduce `compile_strategy_def`.
    """
    from app.services.indicators import compute_indicator
    return compute_indicator(nombre, _velas(), daily_stats=STATS, **params)


def _utiles(nombre: str, rejilla: dict) -> dict:
    """El primer valor de cada parámetro. Basta para saber si el motor conoce
    el nombre, y así el test no depende del azar."""
    return {k: v[0] for k, v in rejilla.items() if v and v[0] is not None}


@pytest.mark.parametrize("nombre", sorted(C.CATALOGO))
def test_el_motor_sabe_calcular_cada_indicador(nombre):
    """Cada nombre del catálogo tiene que devolver una serie de verdad.

    No se comprueba el VALOR —eso es cosa de los tests de cada indicador— sino
    que el motor lo reconozca y devuelva algo con la longitud del día. Un
    nombre desconocido devuelve todo NaN o revienta, y las dos cosas fallan.
    """
    df_len = len(_velas())
    s = _calcula(nombre, _utiles(nombre, C.CATALOGO[nombre].params))
    assert s is not None, f"{nombre}: el motor no devuelve nada"
    assert len(s) == df_len, f"{nombre}: devuelve {len(s)} valores para {df_len} velas"
    assert pd.Series(s).notna().any(), \
        f"{nombre}: todo NaN — probablemente el motor no reconoce el nombre"


# El unico del catalogo que se apoya en una tabla EXTERNA (velas diarias por
# ticker, OVERHEAD_DAILY_PARQUET). Con el ticker sintetico de STATS devuelve
# NaN, y eso es CORRECTO: no significa que el motor no conozca el nombre. Se
# comprueba entero en tests/test_overhead_last_x_days.py, que inyecta un ticker
# en la cache y ademas verifica que el nombre esta dado de alta.
NIVELES_CON_TABLA_EXTERNA = {"Overhead last X days"}


@pytest.mark.parametrize("nombre", sorted(set(C.TODOS_LOS_NIVELES)))
def test_el_motor_sabe_calcular_cada_NIVEL(nombre):
    """Lo mismo para los del lado derecho. Estos se olvidan más porque no salen
    en la lista de la pantalla: se usan como objetivo de un cruce y ya."""
    df_len = len(_velas())
    if nombre in NIVELES_CON_TABLA_EXTERNA:
        pytest.skip("se cubre en test_overhead_last_x_days.py (necesita tabla diaria)")
    s = _calcula(nombre, _utiles(nombre, C.NIVELES_CON_PARAMS.get(nombre, {})))
    assert s is not None and len(s) == df_len, f"{nombre}: el motor no lo conoce"
    assert pd.Series(s).notna().any(), f"{nombre}: todo NaN"


def test_las_guardas_tambien_son_indicadores_de_verdad():
    df_len = len(_velas())
    for _clave, nombre, _etiqueta, _comp, _ayuda in C.GUARDAS:
        s = _calcula(nombre, {})
        assert s is not None and len(s) == df_len, f"guarda {nombre}: desconocida"
        assert pd.Series(s).notna().any(), f"guarda {nombre}: todo NaN"


# ── La forma del catálogo ────────────────────────────────────────────────

def test_toda_familia_declarada_existe():
    """Un indicador con una familia inventada no saldría en ninguna pestaña de
    la pantalla: estaría en el catálogo y sería invisible."""
    validas = {c for c, _ in C.FAMILIAS}
    for nombre, ind in C.CATALOGO.items():
        assert ind.familia in validas, f"{nombre}: familia '{ind.familia}' no existe"


def test_toda_familia_tiene_al_menos_un_indicador():
    """Una pestaña vacía en la pantalla es un despiste, no una decisión."""
    usadas = {i.familia for i in C.CATALOGO.values()}
    for clave, etiqueta in C.FAMILIAS:
        assert clave in usadas, f"la familia '{etiqueta}' se quedó sin indicadores"


def test_todos_tienen_ayuda():
    """La lista tiene 24 entradas con nombres en inglés del motor. Sin una línea
    que diga qué hace cada uno, no se puede elegir."""
    for nombre, ind in C.CATALOGO.items():
        assert ind.ayuda.strip(), f"{nombre}: sin ayuda"


def test_ninguno_se_queda_sin_lado_derecho():
    """Un indicador sin `valores` ni `objetivos` no puede formar ninguna
    condición: `_condicion_aleatoria` se quedaría sin opciones y reventaría.

    Salvo los NIVELES OPCIONALES (`solo_destino`): esos no van a la izquierda
    nunca, entran como destino de Bar Close / High / Low. Que no tengan lado
    derecho es la definición, no un despiste."""
    for nombre, ind in C.CATALOGO.items():
        if ind.solo_destino:
            assert nombre in C.NIVELES_OPCIONALES or nombre in C.NIVELES_BASE,                 f"{nombre}: solo_destino sin rejilla de nivel"
            continue
        assert ind.valores or ind.objetivos, f"{nombre}: no se puede comparar con nada"


# ── Los niveles opcionales (12-sep-2026) ─────────────────────────────────
#
# El perfil de volumen y el último pivote son precios, así que van como
# DESTINO de los cruces. Pero no de serie: solo si se marcan en la página. La
# premisa fue «no romper nada de lo que ya funciona»: una corrida configurada
# como siempre tiene que sortear exactamente lo mismo que antes.

_DE_SIEMPRE = C.NIVELES + tuple(n for n in C.NIVELES_CON_PARAMS
                                if n not in C.NIVELES_OPCIONALES and n not in C.NIVELES)


def test_sin_marcar_nada_los_destinos_son_los_de_siempre():
    """La lista de destinos de Bar Close sin niveles opcionales marcados es la
    de antes, en el mismo orden — el mismo orden importa porque `rng.choice`
    sobre la misma lista da el mismo individuo con la misma semilla."""
    for nombre in ("Bar Close", "High Bar", "Low Bar"):
        assert C.objetivos_permitidos(C.CATALOGO[nombre], [nombre, "RSI"]) == _DE_SIEMPRE


def test_los_niveles_opcionales_solo_entran_marcados():
    import random
    sin = {c["objetivo"]["ind"]
           for c in (X._condicion_aleatoria(random.Random(1), ["Bar Close"], ["Bar Close"])
                     for _ in range(400)) if isinstance(c["objetivo"], dict)}
    assert not (sin & set(C.NIVELES_OPCIONALES)), f"se colaron sin marcar: {sin & set(C.NIVELES_OPCIONALES)}"

    marcados = ["Bar Close", "Punto de control", "Ultimo pivote"]
    con = {}
    rng = random.Random(2)
    for _ in range(600):
        c = X._condicion_aleatoria(rng, ["Bar Close"], marcados)
        if isinstance(c["objetivo"], dict):
            con.setdefault(c["objetivo"]["ind"], set()).add(str(sorted(c["objetivo"]["params"].items())))
    assert "Punto de control" in con and "Ultimo pivote" in con, sorted(con)
    assert "Zona alta" not in con, "un nivel SIN marcar salió como destino"
    # y con sus parámetros sorteados, no siempre los mismos
    assert len(con["Ultimo pivote"]) > 1 and len(con["Punto de control"]) > 1


def test_un_nivel_opcional_nunca_va_a_la_izquierda():
    import random
    cfg = {"catalogo": ["RSI", "Punto de control", "Zona alta", "Ultimo pivote"],
           "n_condiciones": 1, "sesgo": "short", "stops": ["pct"], "tps": ["pct"]}
    rng = random.Random(4)
    izq = {c["ind"] for i in (X.aleatorio(cfg, rng) for _ in range(200)) for c in i["condiciones"]}
    assert izq == {"RSI"}, izq


def test_solo_niveles_marcados_falla_con_un_mensaje_claro():
    """Sin nada que poner a la izquierda, mejor un ValueError que diga qué
    falta que un `rng.choice([])` críptico en la primera generación."""
    import random
    cfg = {"catalogo": ["Punto de control"], "n_condiciones": 1, "sesgo": "short"}
    with pytest.raises(ValueError, match="Punto de control"):
        X.aleatorio(cfg, random.Random(1))


# ── Los niveles BASE con casilla y la familia de picos (21-sep-2026) ────
#
# Jaume: «no tiene en cuenta indicadores como el pico/valle (nºN) o el Ultimo
# pivote, previous max y min, Prev. Bar close/open/high/low...». Los niveles
# base entraban como destino pero sin casilla: ni se veian ni se podian quitar.
# Ahora tienen casilla, marcada de serie, y la pagina manda
# `niveles_explicitos: true`. Un config antiguo (sin la clave y sin ningun
# nivel base en `catalogo`) tiene que sortear EXACTAMENTE lo de siempre.

def test_los_niveles_base_estan_en_el_catalogo_marcados_de_serie():
    for n in C.NIVELES_BASE:
        assert n in C.CATALOGO and C.CATALOGO[n].solo_destino and C.CATALOGO[n].por_defecto, n
        assert C.CATALOGO[n].familia == "precio"


def test_con_niveles_explicitos_solo_entran_los_marcados():
    bc = C.CATALOGO["Bar Close"]
    marcados = ["Bar Close", "Prev. Bar Low", "VWAP"]
    permitidos = C.objetivos_permitidos(bc, marcados, explicitos=True)
    assert "Prev. Bar Low" in permitidos and "VWAP" in permitidos
    assert "Prev. Bar Close" not in permitidos and "Previous max" not in permitidos
    # los que no tienen casilla (medias, bandas, Darvas...) siguen entrando
    assert "SMA" in permitidos and "Darvas Box" in permitidos
    # y el orden relativo es el de siempre
    assert [o for o in _DE_SIEMPRE if o in permitidos] == list(permitidos)


def test_sin_la_clave_pero_con_niveles_base_marcados_se_deduce_explicito():
    """La pagina nueva manda la clave; pero si alguien construye el config a
    mano con «Prev. Bar Low» dentro, es que sabe que hay casillas."""
    bc = C.CATALOGO["Bar Close"]
    permitidos = C.objetivos_permitidos(bc, ["Bar Close", "Prev. Bar Low"])
    assert "Prev. Bar Low" in permitidos and "VWAP" not in permitidos


def test_con_todo_desmarcado_y_explicito_no_se_queda_sin_destinos():
    """Desmarcar los nueve no puede reventar `rng.choice(())`: quedan medias y
    bandas."""
    import random
    cfg = {"catalogo": ["Bar Close"], "niveles_explicitos": True, "n_condiciones": 1,
           "sesgo": "short", "stops": ["pct"], "tps": ["pct"]}
    destinos = {c["objetivo"]["ind"] for i in (X.aleatorio(cfg, random.Random(3)) for _ in range(300))
                for c in i["condiciones"] if isinstance(c["objetivo"], dict)}
    assert destinos and not (destinos & set(C.NIVELES_BASE)), destinos


def test_el_pico_entra_como_destino_solo_marcado_y_del_2_al_4():
    import random
    rng = random.Random(8)
    con = {}
    for _ in range(600):
        c = X._condicion_aleatoria(rng, ["Bar Close"], ["Bar Close", "Pico"])
        if isinstance(c["objetivo"], dict) and c["objetivo"]["ind"] == "Pico":
            con.setdefault("rank", set()).add(c["objetivo"]["params"]["pivot_rank"])
    assert con.get("rank") == {2, 3, 4}, con
    sin = {c["objetivo"]["ind"] for c in (X._condicion_aleatoria(random.Random(1), ["Bar Close"], ["Bar Close"])
                                          for _ in range(400)) if isinstance(c["objetivo"], dict)}
    assert "Pico" not in sin


def test_pico_contra_pico_nunca_es_el_mismo_giro_ni_mezcla_techos_con_suelos():
    """«Pico nº1(up) > Pico nº1(down)» es siempre verdad y «Pico nº2 > Pico
    nº2» siempre falso: dos condiciones muertas que no se sortean ni salen al
    mutar."""
    import random
    from genetico import motor as M
    cfg = {"catalogo": ["Pico"], "n_condiciones": 1, "sesgo": "short",
           "stops": ["pct"], "tps": ["pct"], "p_mutacion": 0.9}
    rng = random.Random(12)
    vistos = set()
    for _ in range(300):
        i = X.aleatorio(cfg, rng)
        for _m in range(3):
            i = M.mutar(i, cfg, rng)
            c = i["condiciones"][0]
            assert c["ind"] == "Pico" and c["objetivo"]["ind"] == "Pico"
            a, b = c["params"], c["objetivo"]["params"]
            assert a["pivot_rank"] != b["pivot_rank"], c
            assert a["swing_dir"] == b["swing_dir"] and a["pivot_window"] == b["pivot_window"], c
            vistos.add((a["pivot_rank"], b["pivot_rank"], a["swing_dir"]))
    assert len(vistos) >= 8, vistos


def test_la_receta_de_los_picos_dice_el_numero_de_giro():
    ind = {"condiciones": [{"ind": "Pico", "params": {"pivot_window": 3, "swing_dir": "up", "pivot_rank": 1},
                            "comp": C.LT,
                            "objetivo": {"ind": "Pico", "params": {"pivot_window": 3, "swing_dir": "up", "pivot_rank": 2}}}],
           "stop": {"modo": "pct", "valor": 5}, "tp": {"modo": "pct", "valor": 10}}
    r = X.receta(ind)
    assert "Pico nº1(3, up) < Pico nº2(3, up)" in r, r


def test_la_familia_de_picos_llega_al_motor_con_pivot_rank():
    """`pivot_rank` tiene que viajar en la definicion: sin el, el motor usa 1 y
    «Pico nº3» seria «Ultimo pivote» sin avisar."""
    cfg = _config(catalogo=["Edad del pico"], n_condiciones=1)
    import random
    i = X.aleatorio(cfg, random.Random(2))
    src = X.a_definicion(i, cfg)["entry_logic"]["root_condition"]["conditions"][-1]["source"]
    assert src["name"] == "Edad del pico" and src["pivot_rank"] in (1, 2, 3)
    assert src["swing_dir"] in ("up", "down") and src["pivot_window"] in (2, 3, 5)


# ── Parametros FIJADOS en la pagina: `ap_session` sigue a la sesion (21-sep) ──
#
# Jaume: «previous max y min tienen que tener en cuenta la sesion en la que fijo
# que se corran las pruebas; mejor si puedo seleccionar el periodo». El motor
# calcula sobre el dia entero y recorta despues, asi que en RTH un Previous max
# desde las 04:00 incluye el premercado: es otro indicador.

def test_la_sesion_de_referencia_sigue_a_la_sesion_de_la_corrida():
    f = C.sesion_de_referencia
    assert f({"sesiones": ["rth"]}) == "ap.RTH"
    assert f({"sesiones": ["pre"]}) == "ap.PM"
    assert f({"sesiones": ["post"]}) == "ap.AM"
    assert f({"sesiones": ["custom"], "hora_ini": "08:00"}) == "ap.PM"
    assert f({"sesiones": ["custom"], "hora_ini": "10:30"}) == "ap.RTH"
    assert f({"sesiones": ["custom"], "hora_ini": "16:30"}) == "ap.AM"
    assert f({"sesiones": ["pre", "rth"]}) == "ap.PM"        # la mas temprana
    assert f({}) == "ap.RTH"                                  # el defecto de la pagina


def _cfg_fijos(valor, **extra):
    cfg = {"catalogo": ["Bar Close", "Previous max", "% Fade"], "niveles_explicitos": True,
           "n_condiciones": 1, "sesgo": "short", "stops": ["pct"], "tps": ["pct"],
           "sesiones": ["rth"], "p_mutacion": 0.9,
           "params_fijos": {"Previous max": {"ap_session": valor}, "% Fade": {"ap_session": valor}}}
    cfg.update(extra)
    return cfg


def _ap_sessions_vistos(cfg, n=300, mutar=True):
    import random
    from genetico import motor as M
    rng = random.Random(17)
    vistos = {"Previous max": set(), "% Fade": set()}
    for _ in range(n):
        i = X.aleatorio(cfg, rng)
        for _m in range(2 if mutar else 0):
            i = M.mutar(i, cfg, rng)
        for c in i["condiciones"]:
            if c["ind"] == "% Fade":
                vistos["% Fade"].add(c["params"].get("ap_session"))
            obj = c["objetivo"]
            if isinstance(obj, dict) and obj["ind"] == "Previous max":
                vistos["Previous max"].add(obj["params"].get("ap_session"))
    return vistos


def test_con_auto_previous_max_y_fade_llevan_la_sesion_de_la_corrida_tambien_al_mutar():
    v = _ap_sessions_vistos(_cfg_fijos("auto"))
    assert v["Previous max"] == {"ap.RTH"} and v["% Fade"] == {"ap.RTH"}, v
    v = _ap_sessions_vistos(_cfg_fijos("auto", sesiones=["pre"]))
    assert v["Previous max"] == {"ap.PM"} and v["% Fade"] == {"ap.PM"}, v


def test_un_valor_fijo_a_mano_manda_sobre_la_sesion():
    v = _ap_sessions_vistos(_cfg_fijos("ap.PM"))          # corrida RTH, pero pedido 04:00
    assert v["Previous max"] == {"ap.PM"} and v["% Fade"] == {"ap.PM"}, v


def test_sortear_y_config_antiguo_prueban_las_dos():
    v = _ap_sessions_vistos(_cfg_fijos("*"))
    assert v["Previous max"] == {"ap.PM", "ap.RTH"} and v["% Fade"] == {"ap.PM", "ap.RTH"}, v
    cfg = _cfg_fijos("auto"); del cfg["params_fijos"]      # corrida anterior al 21-sep
    v = _ap_sessions_vistos(cfg)
    assert v["Previous max"] == {"ap.PM", "ap.RTH"}, v


def test_un_parametro_fijado_no_es_un_gen_al_mutar():
    """Con `ap_session` fijado y `fade_ref` libre, la mutacion de parametro del
    % Fade solo puede tocar `fade_ref`: sortear el fijo devolveria un clon."""
    import random
    from genetico import motor as M
    cfg = _cfg_fijos("auto")
    rng = random.Random(3)
    c = {"ind": "% Fade", "params": {"fade_ref": "previous_max", "ap_session": "ap.RTH"},
         "comp": C.GT, "objetivo": 10}
    for _ in range(200):
        m = M._mutar_condicion(c, cfg, rng)
        assert m["params"]["ap_session"] == "ap.RTH", m


def test_el_pivote_entra_al_stop_solo_si_esta_marcado():
    """El mismo interruptor que lo mete como destino lo mete como stop de
    estructura, con los valores que entiende el motor (VALORES_PIVOTE)."""
    import random
    from app.services.portfolio_sim import VALORES_PIVOTE
    for sesgo, esperado in (("short", "Ultimo pivote alto"), ("long", "Ultimo pivote bajo")):
        assert esperado in VALORES_PIVOTE
        rng = random.Random(9)
        con = {X._stop_aleatorio(rng, ["estructura"], sesgo, 0.0, ["Ultimo pivote"])["nivel"]
               for _ in range(200)}
        assert esperado in con, con
        rng = random.Random(9)
        sin = {X._stop_aleatorio(rng, ["estructura"], sesgo, 0.0, ["RSI"])["nivel"]
               for _ in range(200)}
        assert esperado not in sin, sin
        assert sin == {n for n, _ in C.STOP_NIVELES[sesgo]}


def test_el_hard_stop_del_pivote_es_lo_que_espera_el_motor():
    from app.services.portfolio_sim import necesita_pivotes
    hs = X._hard_stop({"modo": "estructura", "nivel": "Ultimo pivote alto",
                       "operador": ">=", "offset_pct": 5})
    assert hs["type"] == "Market Structure (HOD/LOD)"
    assert necesita_pivotes(hs), "el motor no calcularía los pivotes y caería al 5 % sin avisar"


# ── Que los parámetros se sorteen de verdad ──────────────────────────────

def test_los_parametros_del_NIVEL_tambien_se_sortean():
    """LA DUDA DE JAUME (2026-09-04): «si pongo Darvas box, ¿probará tanto por
    arriba como por abajo, o se queda en una?».

    La respuesta es que sí, y esto lo fija: el lado derecho lleva sus propios
    parámetros sorteados. Sin ello el Darvas saldría siempre con la línea de
    arriba y media herramienta no se probaría nunca.
    """
    import random
    rng = random.Random(7)
    vistos = set()
    for _ in range(400):
        c = X._condicion_aleatoria(rng, ["Bar Close"])
        obj = c["objetivo"]
        if isinstance(obj, dict) and obj["ind"] == "Darvas Box":
            vistos.add(obj["params"].get("band_line"))
    assert {"Upper", "Lower", "Basis"} <= vistos, f"solo salieron {vistos}"


def test_los_parametros_del_indicador_se_sortean():
    """Lo mismo del lado izquierdo, que ya funcionaba: el Squeeze prueba las dos
    direcciones."""
    import random
    rng = random.Random(3)
    vistos = {X._condicion_aleatoria(rng, ["Squeeze"])["params"]["squeeze_direction"]
              for _ in range(200)}
    assert vistos == {"up", "down"}


# ── Ramas del indicador que no se prueban ────────────────────────────────

# Todos los parámetros que acepta `compute_indicator`, con dos valores lo
# bastante distintos como para que se note si mueven la aguja.
SONDAS = {
    "period": [5, 50], "period2": [10, 40], "period3": [3, 20],
    "std_dev": [1.0, 3.0], "band_line": ["Upper", "Lower"],
    "ap_session": ["ap.PM", "ap.RTH"], "range_minutes": [3, 30],
    "pivot_window": [2, 5], "tri_lookback": [15, 60],
    "slope_tolerance": [0.01, 0.5], "min_r_squared": [0.3, 0.95],
    "min_pivots": [2, 4], "session_ref": ["pm", "rth"],
    "squeeze_direction": ["up", "down"],
    "fade_ref": ["previous_max", "vwap_cross"],
    "days_lookback": [1, 5], "orb_minutes": [5, 30], "time_hour": [5, 8],
    # Los de los alternativos (9 y 10-sep-2026).
    "ref_level": ["vwap", "pmh"], "level_dir": ["above", "below"],
    "wick_side": ["upper", "lower"], "swing_dir": ["up", "down"],
    "bin_pct": [0.5, 2.0], "liston_pct": [30, 90], "zona_pct": [50, 85],
    # La familia de picos enumerados (21-sep-2026).
    "pivot_rank": [1, 2],
}

# `multiplier` NO es una rama del indicador: `indicators.py` lo aplica al final
# a CUALQUIERA (`result = result * multiplier`), así que cambia el resultado de
# los 26 y saldría en todas las filas sin decir nada. Escalar un indicador es
# lo mismo que mover el número contra el que se compara, y eso ya se busca.
SIN_SONDAR = {"multiplier"}


def _valores(nombre: str, **kw):
    from app.services.indicators import compute_indicator
    try:
        s = compute_indicator(nombre, _velas(), daily_stats=STATS, **kw)
        return pd.Series(s).astype(float).fillna(-1e18).values
    except Exception:                                        # noqa: BLE001
        return None


def _ramas_perdidas(nombre: str, declarados: dict) -> list:
    """Parámetros que CAMBIAN el resultado y el catálogo no sortea."""
    perdidas = []
    for p, (a, b) in SONDAS.items():
        if p in declarados or p in SIN_SONDAR:
            continue
        sa, sb = _valores(nombre, **{p: a}), _valores(nombre, **{p: b})
        if sa is None or sb is None:
            continue
        if not np.array_equal(sa, sb):
            perdidas.append(p)
    return perdidas


@pytest.mark.parametrize("nombre", sorted(C.CATALOGO))
def test_no_queda_ninguna_rama_del_indicador_sin_probar(nombre):
    """LO QUE PREGUNTÓ JAUME (2026-09-04), y tenía razón en preguntarlo.

    Al meter el Darvas salió que el lado derecho no sorteaba nada: ofrecer
    «Darvas Box» era ofrecer «Darvas por arriba con 3 velas», una sola de sus
    formas. Su pregunta fue si pasaba con más — y pasaba: el MACD iba siempre
    con 12/26/9 y las Bollinger siempre con 2 desviaciones.

    Esto lo detecta solo. Si mañana se añade un indicador y se olvida un
    parámetro que cambia el resultado, salta aquí en vez de quedarse como una
    rama muerta que el genético no explora nunca.
    """
    perdidas = _ramas_perdidas(nombre, C.CATALOGO[nombre].params)
    assert not perdidas, (
        f"{nombre}: {', '.join(perdidas)} cambian el resultado pero el genético "
        f"prueba siempre el mismo valor. Añádelos a `params` o justifícalos.")


@pytest.mark.parametrize("nombre", sorted(C.NIVELES_CON_PARAMS))
def test_a_los_NIVELES_tampoco_les_falta_ninguna(nombre):
    """El lado derecho, que es donde apareció el fallo del Darvas."""
    perdidas = _ramas_perdidas(nombre, C.NIVELES_CON_PARAMS[nombre])
    assert not perdidas, (
        f"nivel {nombre}: {', '.join(perdidas)} no se sortean")


# ── Gestión de riesgo ────────────────────────────────────────────────────

def _config(**extra):
    cfg = {"catalogo": ["RSI", "Squeeze"], "n_condiciones": 2, "sesgo": "short",
           "stops": ["pct"], "tps": ["pct"], "riesgo": {}}
    cfg["riesgo"].update(extra.pop("riesgo", {}))
    cfg.update(extra)
    return cfg


def _individuos(cfg, n=200, semilla=11):
    import random
    rng = random.Random(semilla)
    return [X.aleatorio(cfg, rng) for _ in range(n)]


def test_el_suelo_del_stop_se_respeta():
    """Un stop del 2 % en una acción que se mueve un 50 % al día es ruido, y el
    genético lo elige porque con «shares por distancia» reparte un tamaño
    enorme y la R media sale preciosa (Jaume, 2026-09-04)."""
    cfg = _config(riesgo={"stop_min_pct": 8})
    valores = {i["stop"]["valor"] for i in _individuos(cfg)}
    assert valores and min(valores) >= 8


def test_el_suelo_del_stop_no_toca_los_de_estructura():
    """Allí la distancia la pone el mercado —dónde esté el máximo previo—, no un
    número que se pueda acotar."""
    cfg = _config(stops=["estructura"], riesgo={"stop_min_pct": 20})
    modos = {i["stop"]["modo"] for i in _individuos(cfg)}
    assert modos == {"estructura"}       # no se queda sin opciones ni revienta


def test_el_take_profit_minimo_se_respeta():
    cfg = _config(riesgo={"tp_min_pct": 10})
    valores = {i["tp"]["valor"] for i in _individuos(cfg)}
    assert valores and min(valores) >= 10


def test_un_suelo_imposible_no_deja_al_genetico_sin_opciones():
    """Pedir un stop mínimo del 500 % no puede reventar la corrida: se queda con
    el mayor de la rejilla y se sigue. Un ValueError aquí mataría el proceso
    entero en la primera generación."""
    cfg = _config(riesgo={"stop_min_pct": 500, "tp_min_pct": 500})
    ind = _individuos(cfg, n=5)[0]
    assert ind["stop"]["valor"] == max(C.STOP_PCT)
    assert ind["tp"]["valor"] == max(C.TP_PCT)


def test_los_suelos_tambien_valen_al_mutar():
    """Hasta el 12-sep-2026 el suelo solo se aplicaba al NACER: un stop del 8 %
    bajaba al 5 y al 3 a base de vecinos, y al saltar de estructura a
    porcentaje se sorteaba sin suelo. El `stop_min_pct` de la página parecía
    puesto y no lo estaba."""
    import random
    from genetico import motor as M
    cfg = _config(stops=["pct", "estructura"], tps=["pct", "hora"],
                  riesgo={"stop_min_pct": 8, "tp_min_pct": 10}, p_mutacion=0.6)
    rng = random.Random(21)
    pob = _individuos(cfg, n=60)
    stops, tps = set(), set()
    for _ in range(40):
        pob = [M.mutar(i, cfg, rng) for i in pob]
        stops |= {i["stop"]["valor"] for i in pob if i["stop"]["modo"] == "pct"}
        tps |= {i["tp"]["valor"] for i in pob if i["tp"]["modo"] == "pct"}
    assert stops and min(stops) >= 8, stops
    assert tps and min(tps) >= 10, tps


def test_el_destino_mutado_conserva_sus_parametros():
    """Al mutar el destino se ponía `params: {}` y un Darvas mutado volvía a
    los defectos del motor en silencio. Ahora se sortean como al nacer, y
    solo entre los destinos permitidos en la corrida."""
    import random
    from genetico import motor as M
    cfg = _config(catalogo=["Bar Close", "Ultimo pivote"], n_condiciones=1)
    rng = random.Random(5)
    vistos = {}
    for _ in range(600):
        c = M._mutar_condicion(X._condicion_aleatoria(rng, ["Bar Close"], cfg["catalogo"]), cfg, rng)
        if isinstance(c["objetivo"], dict) and c["objetivo"]["ind"] in C.NIVELES_CON_PARAMS:
            assert c["objetivo"]["params"], f"destino con params vacíos: {c}"
            vistos.setdefault(c["objetivo"]["ind"], set()).add(str(sorted(c["objetivo"]["params"].items())))
    assert "Ultimo pivote" in vistos and len(vistos["Ultimo pivote"]) > 1
    assert "Punto de control" not in vistos       # no estaba marcado


def test_sin_parciales_no_se_ponen():
    cfg = _config()
    assert all(not i["parciales"] for i in _individuos(cfg))


def test_los_parciales_se_sortean_incluyendo_NINGUNO():
    """Se sortea CUÁNTOS pone, ninguno incluido: si siempre pusiera dos, no se
    podría comparar contra no ponerlos."""
    cfg = _config(riesgo={"tp_parciales": True})
    cuantos = {len(i["parciales"]) for i in _individuos(cfg)}
    assert cuantos == {0, 1, 2}


def test_dos_parciales_no_caen_en_EL_MISMO_SITIO():
    """Salió en la primera corrida de verdad con esto puesto:

        Parciales: 25% a las 12:00, 33% a las 12:00

    Dos niveles con el mismo objetivo no son dos niveles. El motor los aplica
    en orden, así que el segundo salta justo detrás del primero: cierra más
    posición de golpe y gasta un gen en algo que no añade ninguna decisión.
    """
    cfg = _config(tps=["pct", "hora", "tiempo"], riesgo={"tp_parciales": True})
    for i in _individuos(cfg, n=800):
        claves = [(p["modo"], p["valor"]) for p in i["parciales"]]
        assert len(claves) == len(set(claves)), f"parciales repetidos: {claves}"


def test_con_un_solo_objetivo_posible_se_pone_UNO_y_no_dos():
    """Con «hora» como único modo y la rejilla agotada, antes que repetir se
    pone un nivel menos."""
    cfg = _config(tps=["hora"], riesgo={"tp_parciales": True})
    for i in _individuos(cfg, n=300):
        horas = [p["valor"] for p in i["parciales"]]
        assert len(horas) == len(set(horas))


def test_los_parciales_no_cierran_mas_del_100():
    """Dos niveles al 75 % cerrarían más posición de la que hay."""
    cfg = _config(riesgo={"tp_parciales": True})
    for i in _individuos(cfg, n=500):
        assert sum(p["cierre_pct"] for p in i["parciales"]) <= 100


def test_el_modo_del_take_profit_SIGUE_A_los_parciales():
    """LA TRAMPA DEL MOTOR. `partial_take_profits` solo se lee cuando
    `take_profit_mode` es "Partial"; en "Full" se ignoran EN SILENCIO. Dejarlo
    en Full con la lista llena tiraría los parciales sin avisar, y ponerlo en
    Partial con la lista vacía dejaría la estrategia sin objetivo."""
    cfg = _config(riesgo={"tp_parciales": True})
    for i in _individuos(cfg, n=200):
        rm = X.a_definicion(i, cfg)["risk_management"]
        if i["parciales"]:
            assert rm["take_profit_mode"] == "Partial" and rm["partial_take_profits"]
        else:
            assert rm["take_profit_mode"] == "Full" and rm["partial_take_profits"] == []


def test_el_parcial_viaja_en_la_forma_del_motor():
    """`{distance_pct, capital_pct}`, y `distance_pct` es un número para el %
    pero una CADENA con prefijo para hora y minutos."""
    cfg = _config(tps=["pct", "hora", "tiempo"], riesgo={"tp_parciales": True})
    vistos = set()
    for i in _individuos(cfg, n=400):
        for p in X.a_definicion(i, cfg)["risk_management"]["partial_take_profits"]:
            assert set(p) == {"distance_pct", "capital_pct"}
            assert 0 < p["capital_pct"] <= 100
            d = p["distance_pct"]
            vistos.add("pct" if isinstance(d, (int, float))
                       else d.split(":")[0])
    assert vistos == {"pct", "HOUR", "TIME"}, f"solo salieron {vistos}"


def test_el_hibrido_implica_shares_por_stop():
    """Es «por distancia al stop, pero con techo». Sin `size_by_sl` no iría por
    distancia y el techo quedaría puesto sin recortar nada."""
    cfg = _config(riesgo={"hybrid_stop": True, "hybrid_black_swan_pct": 50,
                          "hybrid_max_loss_pct": 3, "size_by_sl": False})
    rm = X.a_definicion(_individuos(cfg, n=1)[0], cfg)["risk_management"]
    assert rm["hybrid_stop"] is True
    assert rm["size_by_sl"] is True
    assert rm["hybrid_black_swan_pct"] == 50 and rm["hybrid_max_loss_pct"] == 3


def test_sin_hibrido_los_campos_van_apagados():
    rm = X.a_definicion(_individuos(_config(), n=1)[0], _config())["risk_management"]
    assert rm["hybrid_stop"] is False
    assert rm["hybrid_black_swan_pct"] is None and rm["hybrid_max_loss_pct"] is None


def test_la_receta_dice_que_linea_del_nivel_se_usa():
    """Un «Donchian» a secas no dice si es la banda de arriba o la de abajo, y
    son estrategias opuestas. La receta es lo que se lee en la lista de
    resultados para decidir si una estrategia merece la pena."""
    ind = {"condiciones": [{"ind": "Bar Close", "params": {}, "comp": C.CRUZA_ABAJO,
                            "objetivo": {"ind": "Donchian",
                                         "params": {"period": 20, "band_line": "Lower"}}}],
           "stop": {"modo": "pct", "valor": 5},
           "tp": {"modo": "pct", "valor": 10},
           "parciales": [{"modo": "pct", "valor": 5, "cierre_pct": 50}]}
    r = X.receta(ind)
    assert "Donchian(Lower, 20)" in r or "Donchian(20, Lower)" in r
    assert "Parciales: 50% 5%" in r
