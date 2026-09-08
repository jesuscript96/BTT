"""STOP HÍBRIDO: por distancia al stop, pero con techo de exposición.

DE DÓNDE SALE. Los dos modos clásicos fallan en extremos opuestos:

* **Por SL** escala muy bien y gestiona el riesgo cuando el stop queda lejos,
  pero si el stop cae MUY cerca de la entrada el tamaño se dispara. Con un
  hueco brutal en contra —el precio se va un 5.000 %— no pierdes tu riesgo:
  puedes acabar debiendo dinero.
* **Por valor de mercado** acota ese desastre (sabes cuánto tienes puesto) pero
  no escala igual de bien.

El híbrido va SIEMPRE por SL salvo que el tamaño resultante exponga más de lo
que aceptas perder ante un evento de cola. Entonces **recorta hasta el techo**,
no anula la operación.

    techo en dólares = (% de cuenta que aceptas perder × capital) / % del evento

EL ERROR FÁCIL, y por eso hay un test dedicado: **el techo es de VALOR, no de
acciones**. Con 100 $ de techo compras 100 acciones a 1 $, pero 200 a 0,50 $.
Confundirlo multiplica la exposición real por el precio.
"""
import numpy as np

from app.services.portfolio_sim import simulate, tope_hibrido


# ── El cálculo, aislado ──────────────────────────────────────────────────

def test_el_ejemplo_de_jaume():
    """10.000 de capital, acepta perder la mitad ante un evento del 5.000 %."""
    # (0,5 × 10.000) / 50 = 100 $ de posición. A 1 $/acción, 100 acciones.
    assert tope_hibrido(10_000, 5_000, 50, 1.0) == 100.0


def test_el_techo_es_de_valor_no_de_acciones():
    """El mismo techo en dólares son MÁS acciones si la acción vale menos."""
    assert tope_hibrido(10_000, 5_000, 50, 0.50) == 200.0
    assert tope_hibrido(10_000, 5_000, 50, 2.00) == 50.0
    # …y en los tres casos la exposición es la misma: 100 $.
    for precio in (0.50, 1.0, 2.0):
        assert tope_hibrido(10_000, 5_000, 50, precio) * precio == 100.0


def test_la_perdida_ante_el_evento_es_la_que_se_acepto():
    """La comprobación que da sentido a la fórmula."""
    capital, bs, perdida_max = 10_000.0, 5_000.0, 50.0
    precio = 3.7
    acciones = tope_hibrido(capital, bs, perdida_max, precio)
    valor = acciones * precio
    # Un movimiento del 5.000 % en contra cuesta 50 veces el valor de la posición.
    perdida = valor * (bs / 100.0)
    assert abs(perdida - capital * perdida_max / 100.0) < 1e-6


def test_sin_datos_no_se_inventa_un_techo():
    """Falta un dato -> None. Un techo inventado es peor que ninguno."""
    assert tope_hibrido(0, 5_000, 50, 1.0) is None          # sin capital
    assert tope_hibrido(10_000, None, 50, 1.0) is None      # sin evento
    assert tope_hibrido(10_000, 5_000, None, 1.0) is None   # sin % de pérdida
    assert tope_hibrido(10_000, 5_000, 50, 0) is None       # sin precio


# ── Dentro del simulador ─────────────────────────────────────────────────

def _correr(**extra):
    """Un caso con el stop MUY ceñido: por SL pediría un tamaño enorme."""
    n = 10
    base = dict(
        close=np.array([100.0] * n), open_=np.array([100.0] * n),
        high=np.array([101.0] * n), low=np.array([99.0] * n),
        entries=np.array([False, True] + [False] * (n - 2)),
        exits=np.array([False] * (n - 2) + [True, False]),
        direction="longonly", init_cash=10_000.0,
        risk_r=100.0, risk_type="FIXED", accumulate=True,
        size_by_sl=True, sl_stop=0.001,   # stop al 0,1 % -> 1.000 acciones
    )
    base.update(extra)
    return simulate(**base)


def test_sin_hibrido_manda_el_tope_de_caja():
    """Control: por SL pide 1.000 acciones y la caja lo deja en 100."""
    t = _correr()["trades"]
    assert t, "debería haber una operación"
    # 10.000 de caja / 100 de precio = 100 acciones.
    assert abs(t[0]["size"] - 100.0) < 1e-6


def test_con_hibrido_se_recorta_al_techo():
    """EL CASO QUE MOTIVA TODO: stop ceñido, exposición acotada.

    Evento del 1.000 % y media cuenta: (0,5 × 10.000) / 10 = 500 $ -> a 100 $
    la acción, 5 acciones. Muy por debajo de las 100 que dejaba la caja.
    """
    t = _correr(hybrid_stop=True, hybrid_black_swan_pct=1_000,
                hybrid_max_loss_pct=50)["trades"]
    assert t, "el híbrido RECORTA, no anula la operación"
    assert abs(t[0]["size"] - 5.0) < 1e-6


def test_el_hibrido_no_toca_lo_que_ya_estaba_por_debajo():
    """Si el tamaño por SL ya cabe en el techo, no se recorta nada."""
    # Techo enorme: (0,5 × 10.000) / 0,1 = 500.000 $ -> 5.000 acciones.
    t = _correr(hybrid_stop=True, hybrid_black_swan_pct=10,
                hybrid_max_loss_pct=50)["trades"]
    assert abs(t[0]["size"] - 100.0) < 1e-6   # manda la caja, como sin híbrido


def test_sin_size_by_sl_el_hibrido_no_se_aplica():
    """Por valor de mercado ya sabes lo que tienes puesto: nada que topar."""
    t = _correr(size_by_sl=False, hybrid_stop=True,
                hybrid_black_swan_pct=1_000, hybrid_max_loss_pct=50)["trades"]
    # 100 de riesgo / 100 de precio = 1 acción, y el híbrido no la toca.
    assert abs(t[0]["size"] - 1.0) < 1e-6


def test_hibrido_sin_parametros_se_comporta_como_size_by_sl():
    """Regla nº1: encender el modo sin rellenar los números no cambia nada."""
    con = _correr(hybrid_stop=True)["trades"]
    sin = _correr()["trades"]
    assert abs(con[0]["size"] - sin[0]["size"]) < 1e-9


# ── Las TRES CAPAS ───────────────────────────────────────────────────────
# Ver docs/MEMORIA_MADRE.md §4: la definición se reconstruye campo a campo en
# tres sitios y NINGUNO avisa cuando se le cae algo. `size_by_sl` se perdió en
# la capa del esquema y `pyramiding` en la del frontend; los dos, en silencio.

def test_capa_esquema_declara_el_hibrido():
    """Sin declararlo, pydantic (extra="ignore") lo tira SIN error ni 422."""
    from app.schemas.strategy import RiskManagement
    d = RiskManagement(size_by_sl=True, hybrid_stop=True,
                       hybrid_black_swan_pct=5_000, hybrid_max_loss_pct=50).model_dump()
    assert d["hybrid_stop"] is True
    assert d["hybrid_black_swan_pct"] == 5_000
    assert d["hybrid_max_loss_pct"] == 50


def test_una_estrategia_vieja_no_cambia_de_comportamiento():
    """Regla nº1: sin los campos nuevos, todo se compila como antes."""
    from app.schemas.strategy import RiskManagement
    d = RiskManagement(size_by_sl=True).model_dump()
    assert d["hybrid_stop"] is False
    assert d["hybrid_black_swan_pct"] is None


def test_el_backtest_lee_el_hibrido_de_la_definicion():
    """Los porcentajes viajan en la estrategia, no en los params del panel.

    Si esto se rompe, un backtest de una estrategia híbrida se dimensionaría
    por SL sin techo y NADA lo diría: los numeros saldrían, solo que mal.
    """
    import inspect
    from app.services import backtest_service as bs
    fichero = inspect.getsource(bs)
    assert 'rm.get("hybrid_stop")' in fichero, (
        "backtest_service ya no lee hybrid_stop de risk_management")
    assert "hybrid_black_swan_pct" in fichero and "hybrid_max_loss_pct" in fichero


def test_el_dispatcher_no_manda_el_hibrido_al_jit():
    """El kernel Numba NO implementa el techo: una estrategia híbrida tiene que
    ir al motor Python. Este equipo corre con BACKTEST_NUMBA_SIM=1, así que sin
    esto el techo se perdería en silencio en todo backtest sin piramidación."""
    import inspect
    from app.services import sim_dispatch
    src = inspect.getsource(sim_dispatch.simulate)
    assert 'kwargs.get("hybrid_stop")' in src
    assert "_legacy_simulate" in src


# ── La PIRÁMIDE tiene su propio modo de tamaño ───────────────────────────
# Encontrado auditando el 2026-09-04: los campos del nivel se leían en
# `portfolio_sim` pero NO se compilaban ni se entregaban, así que el modo no se
# activaba nunca. Las tres capas otra vez, esta vez cayéndose en la primera.

def _con_piramide(**nivel):
    """Un short con un añadido en la vela 4. Stop al 2 % (distancia 2 $)."""
    n = 12
    sig = np.zeros(n, dtype=bool)
    sig[4] = True
    lv = {"signals": sig, "action": "add", "capital_frac": 0.0,
          "max_fires": 1, "unit": "usd", "amount_usd": 300.0}
    lv.update(nivel)
    t = simulate(
        close=np.array([100.0] * n), open_=np.array([100.0] * n),
        high=np.array([101.0] * n), low=np.array([99.0] * n),
        entries=np.array([False, True] + [False] * (n - 2)),
        exits=np.array([False] * (n - 2) + [True, False]),
        direction="shortonly", init_cash=100_000.0,
        risk_r=1000.0, risk_type="FIXED", accumulate=True,
        size_by_sl=True, sl_stop=0.02,
        pyramid_levels=[lv],
    )["trades"]
    ex = (t[0].get("pyr_executions") or []) if t else []
    return ex[0]["size"] if ex else 0.0


def test_la_piramide_por_defecto_va_por_valor_de_mercado():
    """Regla nº1: un nivel sin campos nuevos se comporta como siempre."""
    # 300 $ / 100 $ por acción = 3 acciones.
    assert abs(_con_piramide() - 3.0) < 1e-6


def test_la_piramide_puede_ir_por_distancia_al_stop():
    """LO QUE NO FUNCIONABA. 300 $ de riesgo / 2 $ de distancia = 150 acciones.

    Cincuenta veces más que por valor de mercado: si esta clave no llega al
    simulador, el añadido sale del tamaño equivocado y nada lo dice.
    """
    assert abs(_con_piramide(size_by_sl=True) - 150.0) < 1e-6


def test_la_piramide_tiene_su_propio_techo_hibrido():
    """Con sus propios porcentajes, distintos de los de la entrada.

    Jaume los reparte (50 % y 50 %) para que entrada + añadido no pasen juntos
    de lo que acepta perder.
    """
    # Techo: (5 % × 100.000) / 10 = 500 $ -> 5 acciones a 100 $.
    assert abs(_con_piramide(size_by_sl=True, hybrid_stop=True,
                             hybrid_black_swan_pct=1_000,
                             hybrid_max_loss_pct=5) - 5.0) < 1e-6


def test_los_campos_del_nivel_llegan_desde_la_definicion():
    """De punta a punta: JSON -> compilar -> señales -> simulador.

    El test de arriba llama a `simulate` con el nivel ya montado, así que no
    veria que se pierda al compilar. Este si.
    """
    import sys
    sys.path.insert(0, "tests")
    from test_pyramid_entry_time_window import _definicion, _frame
    from app.services.strategy_engine import compile_strategy_def, translate_strategy

    d = _definicion([])
    d["pyramiding"]["levels"][0].update({
        "size_by_sl": True, "hybrid_stop": True,
        "hybrid_black_swan_pct": 1_000, "hybrid_max_loss_pct": 50,
    })
    niveles = translate_strategy(_frame(), d, {},
                                 compiled=compile_strategy_def(d)).get("pyramid_levels") or []
    assert niveles, "la estrategia define un nivel"
    lv = niveles[0]
    assert lv.get("size_by_sl") is True
    assert lv.get("hybrid_stop") is True
    assert lv.get("hybrid_black_swan_pct") == 1_000
    assert lv.get("hybrid_max_loss_pct") == 50


def test_el_techo_puede_calcularse_sobre_un_capital_dado():
    """`hybrid_capital` separa el techo del `init_cash` de la simulación.

    LO NECESITA EL BOT DE ALERTAS. Allí `init_cash` es un capital NOMINAL
    enorme (1e9), puesto a propósito para que el tope de caja no recorte nunca
    el tamaño del aviso. Si el techo se calculara sobre ese número saldría
    astronómico y **no recortaría jamás**: el aviso daría un tamaño sin topar y
    nada lo indicaría.
    """
    n = 10
    base = dict(
        close=np.array([100.0] * n), open_=np.array([100.0] * n),
        high=np.array([101.0] * n), low=np.array([99.0] * n),
        entries=np.array([False, True] + [False] * (n - 2)),
        exits=np.array([False] * (n - 2) + [True, False]),
        direction="shortonly", init_cash=1e9,        # el nominal del bot
        risk_r=300.0, risk_type="FIXED", accumulate=True,
        size_by_sl=True, sl_stop=0.01,
        hybrid_stop=True, hybrid_black_swan_pct=1_000, hybrid_max_loss_pct=50,
    )
    # Sin decir el capital: el techo sale de 1e9 y no recorta nada.
    sin = simulate(**base)["trades"][0]["size"]
    # Con el capital real: (0,5 × 10.000) / 10 = 500 $ -> 5 acciones a 100 $.
    con = simulate(**{**base, "hybrid_capital": 10_000.0})["trades"][0]["size"]

    assert abs(con - 5.0) < 1e-6
    assert sin > con * 10, (
        "sin capital explícito el techo se calcula sobre el nominal y no recorta")
