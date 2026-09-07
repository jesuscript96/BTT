"""ESTILO CANGREJO: cuatro techos de sizing que viven con el SL (Álvaro, 2026-09-07).

No es un modo de dimensionado: son TECHOS que recortan el tamaño que salga del
modo activo (MV clásico, por SL o híbrido), nunca lo agrandan. Igual que el
tope híbrido, el de caja y el de locates: recorta, no anula.

    cangrejo_max_sl_dist_pct    — el SL nunca queda a más de D% del entry: se
                                  aprieta a entry*(1±D%) y el stop REAL (la
                                  salida) pasa a ser el apretado.
    cangrejo_max_loss_at_sl_pct — perder como mucho X% del equity en el
                                  recorrido al SL: encoge el MV si el SL queda
                                  lejos.
    cangrejo_max_mv_entry_pct   — market value máximo de cada entrada.
    cangrejo_max_mv_pyr_pct     — market value máximo AÑADIDO por NIVEL de
                                  pirámide (presupuesto independiente por nivel
                                  — decisión de Álvaro 2026-09-07 — que suma
                                  los disparos de ese nivel y se rearma con
                                  cada entrada).

EXCLUSIVO con el híbrido de Jaume: con ambos encendidos gana Cangrejo y el
techo del híbrido NO se aplica. La UI los desactiva mutuamente; el motor
arbitra por si un payload viejo trae los dos.
"""
import numpy as np

from app.services.portfolio_sim import simulate


# ── Helpers ───────────────────────────────────────────────────────────────

def _plano(n=10, **extra):
    """Precio plano a 100, entrada en la barra 1 (fill en la 2)."""
    base = dict(
        close=np.array([100.0] * n), open_=np.array([100.0] * n),
        high=np.array([101.0] * n), low=np.array([99.0] * n),
        entries=np.array([False, True] + [False] * (n - 2)),
        exits=np.array([False] * (n - 2) + [True, False]),
        direction="shortonly", init_cash=10_000.0,
        risk_r=10_000.0, risk_type="FIXED", accumulate=True,
        # Sin modo por SL: el tamaño base sale por MV (10000/100 = 100
        # acciones, justo lo que deja la caja), y los topes Cangrejo recortan.
        size_by_sl=False,
    )
    base.update(extra)
    return base


def _piramide(niveles, n=16, **extra):
    """Short con entrada en la barra 1 (fill 2) y salida por señal al final.

    `niveles` son dicts de nivel YA compilados (unit/amount_usd/signals...).
    """
    base = dict(
        close=np.array([100.0] * n), open_=np.array([100.0] * n),
        high=np.array([101.0] * n), low=np.array([99.0] * n),
        entries=np.array([False, True] + [False] * (n - 2)),
        exits=np.array([False] * (n - 2) + [True, False]),
        direction="shortonly", init_cash=100_000.0,
        risk_r=1_000.0, risk_type="FIXED", accumulate=True,
        size_by_sl=False,
        pyramid_levels=niveles,
    )
    base.update(extra)
    return base


def _nivel(n, barras, amount_usd=700.0, max_fires=1):
    sig = np.zeros(n, dtype=bool)
    for b in barras:
        sig[b] = True
    return {"signals": sig, "action": "add", "capital_frac": 0.0,
            "max_fires": max_fires, "unit": "usd", "amount_usd": amount_usd}


def _adds(trades):
    """Todos los 'add' de la bitácora de pirámide, en orden."""
    out = []
    for t in trades:
        for pe in (t.get("pyr_executions") or []):
            if pe.get("kind") == "add":
                out.append(pe)
    return out


# ── Opción 1: el SL nunca queda a más de D% del entry ─────────────────────

def test_el_tope_de_distancia_mueve_el_stop_de_verdad():
    """SL al 100% arriba (200) apretado al 50% (150): la SALIDA es en 150.

    Sin cangrejo el high de 160 no toca el SL de 200 y el trade sale por
    señal; con el tope, la misma vela de 160 SÍ toca el 150 y sale en SL.
    """
    n = 10
    high = np.array([101.0] * n)
    high[5] = 160.0
    con = simulate(**_plano(n=n, high=high, sl_stop=1.0,
                            cangrejo_active=True,
                            cangrejo_max_sl_dist_pct=50))["trades"]
    assert con and con[0]["exit_reason"] == "SL"
    assert abs(con[0]["exit_price"] - 150.0) < 1e-6
    assert abs(con[0]["stop_loss"] - 150.0) < 1e-6

    sin = simulate(**_plano(n=n, high=high, sl_stop=1.0))["trades"]
    assert sin[0]["exit_reason"] != "SL"
    assert abs(sin[0]["stop_loss"] - 200.0) < 1e-6


# ── Opción 2: perder como mucho X% del equity en el recorrido al SL ───────

def test_el_tope_de_perdida_encoge_el_mv():
    """SL al 50% (150): 100 acciones perderían 5.000 (50% de la cuenta).

    Con X=10% el tamaño baja a 1000/50 = 20 acciones. Recorta, no anula.
    """
    t = simulate(**_plano(sl_stop=0.5,
                          cangrejo_active=True,
                          cangrejo_max_loss_at_sl_pct=10))["trades"]
    assert t, "el tope RECORTA, no anula la operación"
    assert abs(t[0]["size"] - 20.0) < 1e-6
    # Pérdida si salta el SL: 20 acciones x 50$ = 1.000 = el 10% de la cuenta.
    assert abs(t[0]["size"] * 50.0 - 1_000.0) < 1e-6


def test_el_tope_de_perdida_no_toca_lo_que_ya_cabe():
    """Un SL ceñido ya pierde menos de X: el tope no recorta nada."""
    t = simulate(**_plano(sl_stop=0.05,
                          cangrejo_active=True,
                          cangrejo_max_loss_at_sl_pct=50))["trades"]
    # 100 acciones x 5$ de recorrido = 500$ = 5% de la cuenta < 50%.
    assert abs(t[0]["size"] - 100.0) < 1e-6


def test_el_tope_de_perdida_usa_la_distancia_apretada():
    """Orden: 1º se aprieta el SL (opción 1), 2º se acota la pérdida.

    SL al 100% (dist 100) apretado al 25% (dist 25): con X=10% el tamaño es
    1000/25 = 40. Si usara la distancia sin apretar daría 10.
    """
    t = simulate(**_plano(sl_stop=1.0,
                          cangrejo_active=True,
                          cangrejo_max_sl_dist_pct=25,
                          cangrejo_max_loss_at_sl_pct=10))["trades"]
    assert abs(t[0]["size"] - 40.0) < 1e-6


# ── Tope de market value de la entrada ────────────────────────────────────

def test_el_tope_de_mv_entrada_recorta_a_cualquier_modo():
    """MV base del 100% de la cuenta, tope E=5% -> 500$ -> 5 acciones."""
    t = simulate(**_plano(sl_stop=0.5,
                          cangrejo_active=True,
                          cangrejo_max_mv_entry_pct=5))["trades"]
    assert abs(t[0]["size"] - 5.0) < 1e-6


def test_gana_el_tope_mas_bajo_entre_mv_y_perdida():
    """min(E%, X%/dist): E=5% (5 acciones) vs X=10%/dist50 (20) -> 5."""
    t = simulate(**_plano(sl_stop=0.5,
                          cangrejo_active=True,
                          cangrejo_max_mv_entry_pct=5,
                          cangrejo_max_loss_at_sl_pct=10))["trades"]
    assert abs(t[0]["size"] - 5.0) < 1e-6


# ── Tope de MV por NIVEL de pirámide ──────────────────────────────────────

def test_el_tope_de_piramide_recorta_cada_add():
    """Sin tope, cada nivel añadiría 990 acciones (lo que deja la caja).

    Con P=1% (1.000$ de 100.000), cada nivel añade 10 acciones.
    """
    n = 14
    niveles = [_nivel(n, [4], amount_usd=100_000.0),
               _nivel(n, [8], amount_usd=100_000.0)]
    t = simulate(**_piramide(niveles, n=n,
                             cangrejo_active=True,
                             cangrejo_max_mv_pyr_pct=1))["trades"]
    adds = _adds(t)
    assert len(adds) == 2
    assert abs(adds[0]["size"] - 10.0) < 1e-6
    assert abs(adds[1]["size"] - 10.0) < 1e-6


def test_el_presupuesto_de_piramide_es_por_nivel_y_acumulado_en_el():
    """La semántica "por nivel individual" (decisión de Álvaro).

    Nivel 1 dispara DOS veces pidiendo 700$ cada una con P=1.000$: la primera
    entra entera, la segunda se recorta al resto (300$) y queda anotada.
    El nivel 2 pide los mismos 700$ y le entran ENTEROS: su presupuesto es
    suyo, agotar el del nivel 1 no le merma.
    """
    n = 16
    # Flancos del nivel 1 en las barras 4 y 7 (False->True, con False entre
    # medias para que sea DOS disparos y no uno sostenido).
    sig1 = np.zeros(n, dtype=bool)
    sig1[4] = True
    sig1[7] = True
    lv1 = {"signals": sig1, "action": "add", "capital_frac": 0.0,
           "max_fires": 2, "unit": "usd", "amount_usd": 700.0}
    lv2 = _nivel(n, [10])
    t = simulate(**_piramide([lv1, lv2], n=n,
                             cangrejo_active=True,
                             cangrejo_max_mv_pyr_pct=1))["trades"]
    adds = _adds(t)
    assert len(adds) == 3, "dos disparos del nivel 1 + uno del nivel 2"
    assert adds[0]["level"] == 1 and abs(adds[0]["size"] - 7.0) < 1e-6
    # El segundo disparo del nivel 1: presupuesto 1.000 - 700 = 300 -> 3 acc.
    assert adds[1]["level"] == 1 and abs(adds[1]["size"] - 3.0) < 1e-6
    assert "recortado_por_cangrejo" in adds[1]
    # El nivel 2: presupuesto INTACTO (independiente) -> 7 acciones enteras.
    assert adds[2]["level"] == 2 and abs(adds[2]["size"] - 7.0) < 1e-6
    assert "recortado_por_cangrejo" not in adds[2]


def test_el_presupuesto_de_piramide_se_rearma_con_cada_entrada():
    """Una reentrada es una posición nueva: presupuesto de nivel a cero.

    El mismo nivel añade 700$ en la primera posición y, tras salir y
    reentrar, OTROS 700$ enteros. Sin reset, el segundo add saldría recortado
    a los 300$ restantes.
    """
    n = 16
    sig = np.zeros(n, dtype=bool)
    sig[4] = True    # disparo dentro de la posición 1
    sig[13] = True   # disparo dentro de la posición 2
    lv = {"signals": sig, "action": "add", "capital_frac": 0.0,
          "max_fires": 1, "unit": "usd", "amount_usd": 700.0}
    entries = np.zeros(n, dtype=bool)
    entries[1] = True
    entries[9] = True     # reentrada tras la salida por señal
    exits = np.zeros(n, dtype=bool)
    exits[6] = True       # salida de la posición 1
    t = simulate(**_piramide([lv], n=n, entries=entries, exits=exits,
                             cangrejo_active=True,
                             cangrejo_max_mv_pyr_pct=1))["trades"]
    assert len(t) == 2, "dos posiciones (entrada + reentrada)"
    adds = _adds(t)
    assert len(adds) == 2
    assert abs(adds[0]["size"] - 7.0) < 1e-6
    assert abs(adds[1]["size"] - 7.0) < 1e-6, "el presupuesto se rearma al entrar"


# ── Exclusividad con el híbrido ───────────────────────────────────────────

def test_con_cangrejo_el_techo_del_hibrido_no_se_aplica():
    """El caso del stop ceñido del test híbrido, pero con Cangrejo activo.

    Sin cangrejo: híbrido (evento 1.000%, perder 50%) topa a 5 acciones.
    Con cangrejo activo el híbrido queda SUPRIMIDO y manda la caja: 100.
    """
    base = dict(
        close=np.array([100.0] * 10), open_=np.array([100.0] * 10),
        high=np.array([101.0] * 10), low=np.array([99.0] * 10),
        entries=np.array([False, True] + [False] * 8),
        exits=np.array([False] * 8 + [True, False]),
        direction="longonly", init_cash=10_000.0,
        risk_r=100.0, risk_type="FIXED", accumulate=True,
        size_by_sl=True, sl_stop=0.001,
    )
    hibrido = simulate(**base, hybrid_stop=True,
                       hybrid_black_swan_pct=1_000,
                       hybrid_max_loss_pct=50)["trades"]
    assert abs(hibrido[0]["size"] - 5.0) < 1e-6   # control: el híbrido topa

    ambos = simulate(**base, hybrid_stop=True,
                     hybrid_black_swan_pct=1_000,
                     hybrid_max_loss_pct=50,
                     cangrejo_active=True)["trades"]
    assert abs(ambos[0]["size"] - 100.0) < 1e-6   # manda la caja, no el híbrido


# ── Regla nº1: sin campos, nada cambia ────────────────────────────────────

def test_campos_inactivos_no_cambian_nada():
    """Pasar los campos apagados/en None = resultado idéntico al de siempre."""
    sin = simulate(**_plano(sl_stop=0.5, size_by_sl=True))["trades"]
    con = simulate(**_plano(sl_stop=0.5, size_by_sl=True,
                            cangrejo_active=False,
                            cangrejo_max_sl_dist_pct=None,
                            cangrejo_max_loss_at_sl_pct=None,
                            cangrejo_max_mv_entry_pct=None,
                            cangrejo_max_mv_pyr_pct=None))["trades"]
    assert sin == con


def test_porcentajes_sin_activar_son_inertes():
    """Rellenar números sin encender la sección no puede cambiar el sizing."""
    sin = simulate(**_plano(sl_stop=0.5))["trades"]
    con = simulate(**_plano(sl_stop=0.5,
                            cangrejo_max_sl_dist_pct=1,
                            cangrejo_max_loss_at_sl_pct=1,
                            cangrejo_max_mv_entry_pct=1,
                            cangrejo_max_mv_pyr_pct=1))["trades"]
    assert sin == con


# ── Las TRES CAPAS ────────────────────────────────────────────────────────
# Ver docs/MEMORIA_MADRE.md §4: la definición se reconstruye campo a campo en
# varias capas y NINGUNA avisa cuando se le cae algo. `size_by_sl` se perdió
# en la capa del esquema y `pyramiding` en la del frontend; los dos, en
# silencio. El híbrido ya declaró esta batería; Cangrejo hereda el peligro.

def test_capa_esquema_declara_el_cangrejo():
    """Sin declararlo, pydantic (extra="ignore") lo tira SIN error ni 422."""
    from app.schemas.strategy import RiskManagement
    d = RiskManagement(cangrejo_active=True,
                       cangrejo_max_sl_dist_pct=50,
                       cangrejo_max_loss_at_sl_pct=10,
                       cangrejo_max_mv_entry_pct=5,
                       cangrejo_max_mv_pyr_pct=5).model_dump()
    assert d["cangrejo_active"] is True
    assert d["cangrejo_max_sl_dist_pct"] == 50
    assert d["cangrejo_max_loss_at_sl_pct"] == 10
    assert d["cangrejo_max_mv_entry_pct"] == 5
    assert d["cangrejo_max_mv_pyr_pct"] == 5


def test_una_estrategia_vieja_no_cambia_de_comportamiento():
    """Regla nº1: sin los campos nuevos, todo se compila como antes."""
    from app.schemas.strategy import RiskManagement
    d = RiskManagement(size_by_sl=True).model_dump()
    assert d["cangrejo_active"] is False
    assert d["cangrejo_mode"] is None
    assert d["cangrejo_max_sl_dist_pct"] is None
    assert d["cangrejo_max_loss_at_sl_pct"] is None
    assert d["cangrejo_max_mv_entry_pct"] is None
    assert d["cangrejo_max_mv_pyr_pct"] is None


def test_el_modo_de_la_tarjeta_se_guarda_con_la_estrategia():
    """El modo del selector ('recorrido' | 'perdida') es estado de la UI, pero
    viaja en la estrategia para recordar la elección. Sin declararlo, pydantic
    lo tira en silencio y la tarjeta vuelve a rebotar entre modos (el bug del
    botón que "no iba", 2026-09-07). El motor NO lo lee: solo los valores."""
    from app.schemas.strategy import RiskManagement
    d = RiskManagement(cangrejo_active=True, cangrejo_mode="perdida").model_dump()
    assert d["cangrejo_mode"] == "perdida"
    d2 = RiskManagement(cangrejo_active=True, cangrejo_mode="recorrido").model_dump()
    assert d2["cangrejo_mode"] == "recorrido"


def test_el_backtest_lee_el_cangrejo_de_la_definicion():
    """Los porcentajes viajan en la estrategia, no solo en los kwargs.

    Si esto se rompe, un backtest de una estrategia Cangrejo saldría sin
    topes y NADA lo diría: los números saldrían, solo que mal (el mismo modo
    de fallo silencioso que motivó declarar el híbrido en el esquema).
    """
    import inspect
    from app.services import backtest_service as bs
    src = inspect.getsource(bs)
    assert 'rm.get("cangrejo_active")' in src, (
        "backtest_service ya no lee cangrejo_active de risk_management")
    for campo in ("cangrejo_max_sl_dist_pct", "cangrejo_max_loss_at_sl_pct",
                  "cangrejo_max_mv_entry_pct", "cangrejo_max_mv_pyr_pct"):
        assert campo in src, f"backtest_service ya no lee {campo}"


def test_el_orquestador_lleva_el_cangrejo_a_run_backtest():
    """El merge con la estrategia y el dict de kwargs los nombran campo a campo."""
    import inspect
    from app.services import backtest_orchestrator as orch
    src = inspect.getsource(orch)
    assert "cangrejo_active: bool = False" in src          # BacktestRequest
    assert 'strategy_rm.get("cangrejo_active"' in src      # merge con la estrategia
    assert "cangrejo_active=cangrejo_active" in src        # _bt_kwargs


def test_el_dispatcher_no_manda_el_cangrejo_al_jit():
    """El kernel Numba NO implementa los topes: una estrategia Cangrejo tiene
    que ir al motor Python. Igual que el híbrido: sin esto, con
    BACKTEST_NUMBA_SIM=1 el tope se perdería en silencio."""
    import inspect
    from app.services import sim_dispatch
    src = inspect.getsource(sim_dispatch.simulate)
    assert 'kwargs.get("cangrejo_active")' in src
    assert "_legacy_simulate" in src
    for campo in ("cangrejo_max_sl_dist_pct", "cangrejo_max_loss_at_sl_pct",
                  "cangrejo_max_mv_entry_pct", "cangrejo_max_mv_pyr_pct"):
        assert f'kwargs.pop("{campo}", None)' in src, (
            f"sim_dispatch no limpia {campo} antes del JIT")


def test_el_legacy_recibe_hybrid_capital_con_cangrejo(monkeypatch):
    """`hybrid_capital` es la BASE de los topes Cangrejo: el dispatcher no
    puede perdérselo por el camino (hallazgo de la auditoría 2026-09-07 —
    el pop del path JIT se lo llevaba antes del check de Cangrejo)."""
    from app.services import sim_dispatch

    capturado = {}
    real = sim_dispatch._legacy_simulate

    def _espia(**kwargs):
        capturado.update(kwargs)
        return real(**kwargs)

    monkeypatch.setattr(sim_dispatch, "_legacy_simulate", _espia)
    n = 8
    sim_dispatch.simulate(
        close=np.array([100.0] * n), open_=np.array([100.0] * n),
        high=np.array([101.0] * n), low=np.array([99.0] * n),
        entries=np.array([False, True] + [False] * (n - 2)),
        exits=np.array([False] * (n - 2) + [True, False]),
        direction="shortonly", init_cash=10_000.0,
        risk_r=50.0, risk_type="FIXED", accumulate=True,
        hybrid_stop=False, hybrid_capital=1_000.0,
        cangrejo_active=True, cangrejo_max_mv_entry_pct=5,
    )
    assert capturado.get("cangrejo_active") is True
    assert capturado.get("hybrid_capital") == 1_000.0, (
        "el motor Python tiene que recibir hybrid_capital con Cangrejo activo")
