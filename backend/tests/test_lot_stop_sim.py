"""SL POR LOTE en piramidación — P1: el simulador (PRD 2026-09-15, §6.1-6.3).

Llama a `simulate` directamente con velas sintéticas: cada test fija la
matemática EXACTA que el PRD manda (§3.3: PnL contra el px del LOTE, no
contra la media; §3.4: orden dentro de la barra; §3.5: size_by_sl apunta al
lote) y congela la regresión dorada de las corridas sin `lot_stop`.
"""
import hashlib
import json

import numpy as np
import pandas as pd

from app.services.portfolio_sim import simulate

RISK = 100.0      # FIXED: 100 $ por trade → 10 acciones a 10 $
CASH = 10000.0
N = 20


def _dia(n=N, precio=None, highs_puntual=None):
    """Velas planas a `precio`; `highs_puntual` = {bar: high} para pintar mechas."""
    p = precio if precio is not None else 10.0
    open_ = np.full(n, p)
    close = np.full(n, p)
    high = np.full(n, p + 0.05)
    low = np.full(n, p - 0.05)
    for i, h in (highs_puntual or {}).items():
        high[i] = h
    ts = pd.date_range("2026-09-15 04:00", periods=n, freq="1min")
    ts_ns = ts.values.astype("datetime64[ns]").astype(np.int64)
    return open_, high, low, close, ts_ns


def _senal(*barras, n=N):
    s = np.zeros(n, dtype=bool)
    for b in barras:
        s[b] = True
    return s


def _nivel_add(senal, lot_stop=None, **kw):
    """Nivel add en dólares fijos (amount_usd) por defecto: 100 $ a 10 = 10 acc."""
    nv = {
        "signals": senal, "action": "add", "capital_frac": 0.0,
        "max_fires": kw.pop("max_fires", 2), "unit": "usd",
        "amount_usd": kw.pop("amount_usd", 100.0), "size_by_sl": False,
        "hybrid_stop": False, "hybrid_black_swan_pct": None,
        "hybrid_max_loss_pct": None,
    }
    if lot_stop is not None:
        nv["lot_stop"] = lot_stop
    nv.update(kw)
    return nv


def _correr(open_, high, low, close, ts_ns, entries, exits, niveles,
            direction="shortonly", **kw):
    # hods/lods/previos como los pasa el caller real (`_compute_signals_for_pair`)
    hods = np.maximum.accumulate(high)
    lods = np.minimum.accumulate(low)
    prev_h = np.empty_like(hods); prev_h[0] = high[0]; prev_h[1:] = hods[:-1]
    prev_l = np.empty_like(lods); prev_l[0] = low[0]; prev_l[1:] = lods[:-1]
    params = dict(
        close=close, open_=open_, high=high, low=low,
        entries=entries, exits=exits, direction=direction,
        init_cash=CASH, risk_r=RISK, risk_type="FIXED",
        fees=0.0, fee_type="PERCENT", slippage=0.0,
        look_ahead_prevention=True,
        pyramid_levels=niveles, pyramid_sequential=False,
        timestamps=ts_ns,
        hods=hods, lods=lods, prev_highs=prev_h, prev_lows=prev_l,
    )
    params.update(kw)
    return simulate(**params)


def _legs(res):
    return [(t["exit_reason"], round(t["size"], 6), round(t["pnl"], 4)) for t in res["trades"]]


def _por_motivo(res, motivo):
    return [t for t in res["trades"] if t["exit_reason"] == motivo]


# ── §6.1: matemática del cierre por lote ───────────────────────────────────

def test_pct_corto_cierra_solo_su_lote_con_matematica_exacta():
    """Corto: base 10$ + lote 10$ con SL 5 %. Barra que cruza 10,5 cierra SOLO
    el lote a 10,5: pnl = (10 − 10,5) × 10 = −5. La base sigue viva."""
    open_, high, low, close, ts = _dia(highs_puntual={7: 10.6})
    niveles = [_nivel_add(_senal(4), lot_stop={"mode": "pct", "pct": 5.0})]
    res = _correr(open_, high, low, close, ts, _senal(1), _senal(12), niveles)

    lotes = _por_motivo(res, "Pyramid Lot Stop")
    assert len(lotes) == 1, _legs(res)
    leg = lotes[0]
    assert leg["pnl"] == -5.0                     # (10 − 10,5) × 10
    assert leg["size"] == 10.0                    # solo el lote
    assert leg["entry_price"] == 10.0             # px REAL del lote
    assert leg["exit_price"] == 10.5              # el nivel, sin pasar de la vela
    assert leg["stop_loss"] == 10.5               # el nivel DEL LOTE, no el del trade
    assert leg["fees"] == 0.0
    # el trade global sigue vivo con su base
    final = _por_motivo(res, "Signal")
    assert len(final) == 1 and final[0]["size"] == 10.0


def test_precio_de_referencia_el_px_del_lote_no_la_media():
    """TEST DISCRIMINANTE (§6.1/§3.3). Base a 10, lote a 9: media 9,5. El SL
    del lote (9,45) cierra el lote: contra el px del lote son −4,5 $; contra
    la media serían +0,5 $ (¡signo contrario!). Calcar el reduce aquí daría
    el número equivocado."""
    open_, high, low, close, ts = _dia(precio=None, highs_puntual={8: 9.5})
    # base
    open_[:6] = 10.0; close[:6] = 10.0; low[:6] = 9.95; high[:6] = 10.05
    # el lote se llena a 9 (open de la barra 6)
    open_[6:] = 9.0; close[6:] = 9.0; low[6:] = 8.95
    high[6:8] = 9.05
    niveles = [_nivel_add(_senal(5), amount_usd=90.0,
                          lot_stop={"mode": "pct", "pct": 5.0})]  # SL = 9,45
    res = _correr(open_, high, low, close, ts, _senal(1), _senal(12), niveles)

    lotes = _por_motivo(res, "Pyramid Lot Stop")
    assert len(lotes) == 1, _legs(res)
    leg = lotes[0]
    # CONTRA EL PX DEL LOTE: (9 − 9,45) × 10 = −4,5. Contra la media: +0,5.
    assert leg["pnl"] == -4.5
    assert leg["entry_price"] == 9.0
    # la media del trade se reporta aparte (pre-descuento), como los reduce
    assert leg["avg_entry_price"] == 9.5
    # y tras cerrar el lote la media vuelve a la base
    final = _por_motivo(res, "Signal")[0]
    assert final["size"] == 10.0 and final["avg_entry_price"] == 10.0


def test_pct_largo_espejo():
    """Largo: lote a 11 con SL 5 % (10,45). low 10,4 cierra a 10,45:
    pnl = (10,45 − 11) × 10 = −5,5."""
    open_, high, low, close, ts = _dia()
    open_[6:] = 11.0; close[6:] = 11.0; high[6:] = 11.05
    low[:6] = 9.95; low[6:8] = 10.95
    low[8] = 10.4   # cruza el 10,45
    niveles = [_nivel_add(_senal(5), amount_usd=110.0,
                          lot_stop={"mode": "pct", "pct": 5.0})]
    res = _correr(open_, high, low, close, ts, _senal(1), _senal(12), niveles,
                  direction="longonly")
    leg = _por_motivo(res, "Pyramid Lot Stop")[0]
    assert leg["exit_price"] == 10.45 and leg["pnl"] == -5.5


def test_slippage_y_fee_flat_clonan_el_tratamiento_del_stop():
    """Slippage 1 %: el add de un corto se llena a 10 × 0,99 = 9,9 (100 $ →
    10,1010… acc), su SL es 9,9 × 1,05 = 10,395 y el cierre sale a
    10,395 × 1,01 = 10,49895. Fee FLAT 0,01 $/acc por los dos lados. Mismo
    tratamiento de fill que el stop del trade: el slippage golpea TODOS los
    fills de la pierna."""
    open_, high, low, close, ts = _dia(highs_puntual={7: 10.6})
    niveles = [_nivel_add(_senal(4), lot_stop={"mode": "pct", "pct": 5.0})]
    res = _correr(open_, high, low, close, ts, _senal(1), _senal(12), niveles,
                  slippage=0.01, fees=0.01, fee_type="FLAT")
    leg = _por_motivo(res, "Pyramid Lot Stop")[0]
    q = 100.0 / 9.9                       # acciones del lote al fill con slip
    assert leg["entry_price"] == round(9.9, 6)
    assert leg["exit_price"] == round(9.9 * 1.05 * 1.01, 6)   # 10,49895
    assert leg["size"] == round(q, 6)
    assert leg["fees"] == round(0.01 * q * 2, 4)
    assert leg["pnl"] == round((9.9 - 9.9 * 1.05 * 1.01) * q - 0.01 * q * 2, 4)


def test_fee_percent_sobre_el_nocional_del_lote():
    """PERCENT: fee = (px_lote + net) × size × fee — con la ENTRADA del lote."""
    open_, high, low, close, ts = _dia(highs_puntual={7: 10.6})
    niveles = [_nivel_add(_senal(4), lot_stop={"mode": "pct", "pct": 5.0})]
    res = _correr(open_, high, low, close, ts, _senal(1), _senal(12), niveles,
                  fees=0.001, fee_type="PERCENT")
    leg = _por_motivo(res, "Pyramid Lot Stop")[0]
    assert leg["fees"] == round((10.0 + 10.5) * 10 * 0.001, 4)   # 0,205


def test_structure_hod_congelado_en_la_vela_de_senal():
    """HOD en la vela de señal = 10,2 → SL 10,2 PARA SIEMPRE: la vela que
    dispara tiene HOD 10,3 y aun así se sale a 10,2 (§3.2 congelado)."""
    open_, high, low, close, ts = _dia(highs_puntual={4: 10.2, 5: 10.1, 6: 10.1, 7: 10.3})
    niveles = [_nivel_add(_senal(4),
                          lot_stop={"mode": "structure", "level": "hod", "offset_pct": 0.0})]
    res = _correr(open_, high, low, close, ts, _senal(1), _senal(12), niveles)
    leg = _por_motivo(res, "Pyramid Lot Stop")[0]
    assert leg["stop_loss"] == 10.2
    assert leg["exit_price"] == 10.2      # min(10,2 ; high 10,3)
    assert leg["pnl"] == -2.0             # (10 − 10,2) × 10


def test_structure_offset_aleja_el_nivel_del_precio():
    """offset_pct 1 sobre HOD 10,2 → 10,402, hacia arriba en corto."""
    open_, high, low, close, ts = _dia(highs_puntual={4: 10.2, 7: 10.5})
    niveles = [_nivel_add(
        _senal(4), lot_stop={"mode": "structure", "level": "hod", "offset_pct": 1.0})]
    res = _correr(open_, high, low, close, ts, _senal(1), _senal(12), niveles)
    leg = _por_motivo(res, "Pyramid Lot Stop")[0]
    assert leg["stop_loss"] == round(10.2 * 1.01, 6)


def test_structure_ultimo_pivote_alto_con_offset():
    """Corto: pivote alto 10,5 en la barra 4, confirmado en la 7 (ventana 3
    necesita 3 velas a cada lado DENTRO del día). Señal en la 8 → SL =
    10,5 × 1,005 = 10,5525. Cruce en la 11."""
    n = 16
    open_, high, low, close, ts = _dia(n=n)
    high[:] = 10.04
    high[3] = 10.3
    high[4] = 10.5          # el techo de la pata
    high[5:8] = 10.1        # cae → pivote confirmado en la 4+3 = 7
    high[8:11] = 10.3
    high[11] = 10.6         # cruza el SL del lote
    low[5:8] = 9.9
    niveles = [_nivel_add(_senal(8, n=n),
                          lot_stop={"mode": "structure", "level": "last_pivot",
                                    "swing": "up", "pivot_window": 3,
                                    "offset_pct": 0.5})]
    res = _correr(open_, high, low, close, ts, _senal(1, n=n), _senal(13, n=n), niveles)
    leg = _por_motivo(res, "Pyramid Lot Stop")[0]
    assert leg["stop_loss"] == round(10.5 * 1.005, 6)
    assert leg["exit_price"] == round(10.5 * 1.005, 6)


def test_structure_ultimo_pivote_bajo_en_largo():
    """Espejo en largo: pivote bajo 9,5 confirmado en la 7 → SL 9,5; cruce con
    low 9,4 en la 11."""
    n = 16
    open_, high, low, close, ts = _dia(n=n)
    low[:] = 9.96
    low[3] = 9.7
    low[4] = 9.5
    low[5:8] = 9.9
    low[11] = 9.4
    niveles = [_nivel_add(_senal(8, n=n),
                          lot_stop={"mode": "structure", "level": "last_pivot",
                                    "swing": "down", "pivot_window": 3})]
    res = _correr(open_, high, low, close, ts, _senal(1, n=n), _senal(13, n=n),
                  niveles, direction="longonly")
    leg = _por_motivo(res, "Pyramid Lot Stop")[0]
    assert leg["stop_loss"] == 9.5 and leg["exit_price"] == 9.5
    assert leg["pnl"] == -5.0


def test_nivel_invalido_el_lote_no_se_hace():
    """Estructura en el lado GANADOR (LOD por debajo, en corto) = premisa
    muerta: el añadido NO se ejecuta. Sin cinturón no hay lote."""
    open_, high, low, close, ts = _dia(highs_puntual={7: 10.6})
    niveles = [_nivel_add(_senal(4),
                          lot_stop={"mode": "structure", "level": "lod"})]
    res = _correr(open_, high, low, close, ts, _senal(1), _senal(12), niveles)
    assert not _por_motivo(res, "Pyramid Lot Stop")
    final = _por_motivo(res, "Signal")[0]
    assert final["size"] == 10.0           # el add nunca metió acciones


def test_size_by_sl_del_nivel_dimensiona_contra_el_sl_del_lote():
    """§3.5. Nivel 10 % del equity con size_by_sl: riesgo 1000 $.
    CON lot_stop 5 % (dist 0,5): pide 2000 acc, caja lo recorta a 990.
    SIN lot_stop (y sin stop de trade): dist 0 → fallback 1000/10 = 100 acc."""
    def _run(con_lot):
        open_, high, low, close, ts = _dia(highs_puntual={7: 10.6})
        lot = {"mode": "pct", "pct": 5.0} if con_lot else None
        niveles = [_nivel_add(_senal(4), amount_usd=0.0, unit="pct",
                              capital_frac=0.10, size_by_sl=True, lot_stop=lot)]
        return _correr(open_, high, low, close, ts, _senal(1), _senal(12), niveles)

    leg = _por_motivo(_run(True), "Pyramid Lot Stop")[0]
    assert leg["size"] == 990.0            # recortado por caja, no 2000

    res_sin = _run(False)
    adds = [e for e in (res_sin["trades"][-1].get("pyr_executions") or [])
            if e["kind"] == "add"]
    # sin lot_stop: dist 0 → fallback add_cash/add_px = 100 acc (como siempre)
    assert adds and adds[0]["size"] == 100.0


def test_pyr_base_baja_con_el_lote_cerrado():
    """Los TP parciales porcentan sobre lo que queda vivo: base 10 + lote 10,
    lot stop cierra 10 → pyr_base 10 → un parcial del 50 % cierra 5."""
    open_, high, low, close, ts = _dia(highs_puntual={7: 10.6}, n=16)
    open_[9:] = 10.0; close[9:] = 10.0
    low[9] = 9.4; low[10] = 9.4            # el parcial (TP 5 % a 9,5) salta en la 9
    niveles = [_nivel_add(_senal(4, n=16), lot_stop={"mode": "pct", "pct": 5.0})]
    res = _correr(open_, high, low, close, ts, _senal(1, n=16), _senal(13, n=16),
                  niveles, partial_take_profits=[
                      {"distance_pct": 0.05, "capital_pct": 0.5}])
    parcial = _por_motivo(res, "Partial TP")
    assert len(parcial) == 1 and parcial[0]["size"] == 5.0


def test_lotes_vacian_la_posicion_y_la_bitacora_se_cuelga():
    """Base 10 + lote 10, un reduce del 50 % deja 10 vivas, y el lot stop
    cierra las 10 que quedan (q = min(lote, vivo)): la posición muere en la
    pierna del lote y `pyr_executions` se cuelga de ella, como los reduce."""
    open_, high, low, close, ts = _dia(highs_puntual={9: 10.6}, n=16)
    niveles = [
        _nivel_add(_senal(4, n=16), lot_stop={"mode": "pct", "pct": 5.0}),
        {"signals": _senal(6, n=16), "action": "reduce", "capital_frac": 0.5,
         "max_fires": 1, "unit": "pct", "amount_usd": 0.0, "size_by_sl": False,
         "hybrid_stop": False, "hybrid_black_swan_pct": None,
         "hybrid_max_loss_pct": None},
    ]
    res = _correr(open_, high, low, close, ts, _senal(1, n=16), _senal(13, n=16), niveles)
    assert _legs(res) == [
        ("Pyramid Reduce", 10.0, 0.0),
        ("Pyramid Lot Stop", 10.0, -5.0),
    ], _legs(res)
    ultima = res["trades"][-1]
    bitacora = ultima.get("pyr_executions") or []
    assert [e["kind"] for e in bitacora] == ["add", "reduce", "lot_stop"]
    assert bitacora[-1]["pnl"] == -5.0 and bitacora[-1]["sl_px"] == 10.5


# ── §6.2: misma barra ──────────────────────────────────────────────────────

def test_stop_global_manda_en_la_misma_vela_sin_doble_fill():
    """SL del trade a 10,2 y SL del lote a 10,5; vela con high 10,6 cruza los
    DOS: sale TODO por 'SL' (20 acc a 10,2) y NO se registra cierre de lote."""
    open_, high, low, close, ts = _dia(highs_puntual={7: 10.6})
    niveles = [_nivel_add(_senal(4), lot_stop={"mode": "pct", "pct": 5.0})]
    res = _correr(open_, high, low, close, ts, _senal(1), _senal(12), niveles,
                  sl_stop=0.02)
    sl = _por_motivo(res, "SL")
    assert len(sl) == 1 and sl[0]["size"] == 20.0
    assert sl[0]["pnl"] == round((10.0 - 10.2) * 20, 4)   # −4
    assert not _por_motivo(res, "Pyramid Lot Stop")


def test_dos_lot_stops_en_la_misma_vela():
    """Lote 1 (SL 10,5) y lote 2 (SL 10,8); vela high 10,9 cruza los dos: dos
    piernas en la MISMA vela, en orden cronológico de lote, cada una a su
    nivel."""
    open_, high, low, close, ts = _dia(highs_puntual={10: 10.9})
    niveles = [
        _nivel_add(_senal(4), lot_stop={"mode": "pct", "pct": 5.0}),
        _nivel_add(_senal(6), amount_usd=100.0,
                   lot_stop={"mode": "pct", "pct": 8.0}),
    ]
    res = _correr(open_, high, low, close, ts, _senal(1), _senal(14), niveles)
    lotes = _por_motivo(res, "Pyramid Lot Stop")
    assert len(lotes) == 2, _legs(res)
    assert lotes[0]["exit_idx"] == lotes[1]["exit_idx"] == 10
    assert lotes[0]["level"] if "level" in lotes[0] else True
    # el primero añadido (nivel 1) sale primero, a su 10,5; el segundo a 10,8
    assert lotes[0]["exit_price"] == 10.5 and lotes[1]["exit_price"] == 10.8
    assert lotes[0]["pnl"] == -5.0 and lotes[1]["pnl"] == -8.0


# ── §6.3: regresión dorada sintética (piramidación SIN lot_stop) ───────────

def _escenario_dorado():
    """Piramidación rica SIN lot_stop: add pct con size_by_sl+híbrido, add
    usd, reduce, parcial, slippage y fees. Golden congelado del código de
    HEAD (pre-feature) el 2026-09-15 — hash idéntico al de la captura."""
    n = 60
    base = np.full(n, 10.0)
    rng = np.random.default_rng(42)
    close = base + np.cumsum(rng.normal(0, 0.05, n))
    open_ = np.r_[close[0], close[:-1]]
    high = np.maximum(open_, close) + 0.05
    low = np.minimum(open_, close) - 0.05
    ts = pd.date_range("2026-09-15 04:00", periods=n, freq="1min")
    ts_ns = ts.values.astype("datetime64[ns]").astype(np.int64)
    entries = np.zeros(n, dtype=bool); entries[2] = True
    exits = np.zeros(n, dtype=bool); exits[50] = True
    sig1 = np.zeros(n, dtype=bool); sig1[6] = True; sig1[20] = True
    sig2 = np.zeros(n, dtype=bool); sig2[15] = True
    sig3 = np.zeros(n, dtype=bool); sig3[40] = True
    niveles = [
        {"signals": sig1, "action": "add", "capital_frac": 0.05, "max_fires": 2,
         "unit": "pct", "amount_usd": 0.0, "size_by_sl": True,
         "hybrid_stop": True, "hybrid_black_swan_pct": 50.0, "hybrid_max_loss_pct": 1.0},
        {"signals": sig2, "action": "add", "capital_frac": 0.0, "max_fires": 1,
         "unit": "usd", "amount_usd": 300.0, "size_by_sl": False,
         "hybrid_stop": False, "hybrid_black_swan_pct": None, "hybrid_max_loss_pct": None},
        {"signals": sig3, "action": "reduce", "capital_frac": 0.5, "max_fires": 1,
         "unit": "pct", "amount_usd": 0.0, "size_by_sl": False,
         "hybrid_stop": False, "hybrid_black_swan_pct": None, "hybrid_max_loss_pct": None},
    ]
    return simulate(
        close=close, open_=open_, high=high, low=low,
        entries=entries, exits=exits, direction="shortonly",
        init_cash=10000.0, risk_r=100.0, risk_type="FIXED",
        size_by_sl=False, fees=0.001, fee_type="PERCENT", slippage=0.0005,
        sl_stop=0.03, sl_trail=False, tp_stop=None,
        look_ahead_prevention=True,
        pyramid_levels=niveles, pyramid_sequential=False,
        timestamps=ts_ns,
        partial_take_profits=[{"distance_pct": 0.04, "capital_pct": 0.5}],
    )


def test_dorado_simulador_sin_lot_stop_byte_identico():
    res = _escenario_dorado()
    dump = json.dumps({"trades": res["trades"],
                       "equity": [round(x, 10) for x in res["equity"]]},
                      sort_keys=True, default=str)
    assert hashlib.sha256(dump.encode()).hexdigest() == \
        "54b5b95ee5e2ff8181823e541d34e9f0ebc090ea65f963f1440e109567043df8"
    # El escenario tiene que seguir ejercitando la rama add (si no, el golden
    # sería vacuo): 3 adds + 1 reduce en la bitácora del cierre.
    bitacora = res["trades"][-1].get("pyr_executions") or []
    assert [e["kind"] for e in bitacora].count("add") == 3


# ── Parcial → luego lot stop: el lote es notional sobre el pool ────────────

def _dia_conservacion(pct_parcial):
    """Base 10@10 + lote 10@9,5 (avg 9,75). Parcial HOUR-agnóstico por
    distancia: 5 % a la baja (9,5) cerrando `pct_parcial` del pool. Luego el
    lote salta a 9,975."""
    n = 18
    open_, high, low, close, ts = _dia(n=n)
    # vela del lote: señal en la 5, fill a 9,5 (open de la 6)
    open_[6:] = 9.5; close[6:] = 9.5
    high[6:10] = 9.55; low[6:10] = 9.45
    low[8] = 9.4          # dispara el parcial (nivel 9,5) en la 8
    high[10] = 10.0       # dispara el lote (SL 9,975) en la 10
    open_[11:] = 10.0; close[11:] = 10.0; high[11:] = 10.05; low[11:] = 9.95
    niveles = [_nivel_add(_senal(5, n=n), amount_usd=95.0,
                          lot_stop={"mode": "pct", "pct": 5.0})]   # SL 9,975
    res = _correr(open_, high, low, close, ts, _senal(1, n=n), _senal(13, n=n),
                  niveles,
                  partial_take_profits=[{"distance_pct": 0.05,
                                         "capital_pct": pct_parcial}])
    return res


def test_parcial_25_luego_lot_stop_cierra_lo_suyo_y_la_base_residual():
    """Parcial del 25 % (5 acc) → lote cierra 10 (su tamaño completo, queda
    base 5) → la salida por señal cierra el RESIDUAL de la base a la media
    recalculada (10,25). Conservación: la suma de las piernas cuadra con la
    equity final, sin sizes negativos ni piernas mayores que el pool vivo."""
    res = _dia_conservacion(0.25)
    razones = [t["exit_reason"] for t in res["trades"]]
    assert razones == ["Partial TP", "Pyramid Lot Stop", "Signal"], razones
    parcial, lote, final = res["trades"]
    # parcial: 25 % del pool (20) = 5 acc a 9,5 contra avg 9,75
    assert parcial["size"] == 5.0 and parcial["pnl"] == 1.25
    # lote: SU tamaño completo (10 ≤ 15 vivas), contra SU px 9,5
    assert lote["size"] == 10.0 and lote["pnl"] == -4.75
    assert lote["entry_price"] == 9.5
    # base residual: 5 acc a la media recalculada (9,75·15 − 9,5·10)/5 = 10,25
    assert final["size"] == 5.0 and final["avg_entry_price"] == 10.25
    assert final["pnl"] == 1.25
    # conservación: equity final == inicial + suma de piernas (a céntimo)
    suma = sum(t["pnl"] for t in res["trades"])
    assert abs((res["equity"][-1] - (CASH + suma))) < 1e-6
    assert sum(t["size"] for t in res["trades"]) == 20.0   # base 10 + lote 10


def test_parcial_75_capsa_el_lote_al_pool_vivo_y_vacia_la_posicion():
    """Parcial del 75 % (15 acc) → solo quedan 5 vivas: el lote pidió 10 pero
    se CAPA a min(10, 5) = 5, la posición se vacía en la pierna del lote (la
    base residual es 0) y la bitácora se cuelga de esa última pierna. Sin
    sizes negativos y conservación exacta."""
    res = _dia_conservacion(0.75)
    razones = [t["exit_reason"] for t in res["trades"]]
    assert razones == ["Partial TP", "Pyramid Lot Stop"], razones
    parcial, lote = res["trades"]
    assert parcial["size"] == 15.0 and parcial["pnl"] == 3.75
    # CAPADO al pool vivo: 5, no las 10 del lote
    assert lote["size"] == 5.0 and lote["pnl"] == -2.375
    bitacora = lote.get("pyr_executions") or []
    assert [e["kind"] for e in bitacora] == ["add", "lot_stop"]
    # conservación y cierre total: 15 + 5 = 20 acc, nada queda vivo
    assert sum(t["size"] for t in res["trades"]) == 20.0
    suma = sum(t["pnl"] for t in res["trades"])
    assert abs((res["equity"][-1] - (CASH + suma))) < 1e-6


# ── lot_stop × stop VWAP del trade (merge 738cec2) ─────────────────────────

def _dia_vwap(n=18):
    """Precio plano a 10; VWAP constante a 10,3 → stop del trade (VWAP +2 %)
    = 10,506, por encima de la entrada: válido en corto."""
    open_, high, low, close, ts = _dia(n=n)
    return open_, high, low, close, ts, np.full(n, 10.3)


HS_VWAP = {"hs_type": "Market Structure (HOD/LOD)", "hs_value": "VWAP",
           "hs_operator": ">=", "hs_offset_pct": 2.0}


def test_lot_stop_convive_con_el_stop_vwap_del_trade():
    """Lote con SL 10,4; stop del trade VWAP+2 % = 10,506. Una vela con high
    10,45 cruza SOLO el lote: cierra el lote y el trade sigue vivo hasta que
    otra vela cruza el VWAP-stop y cierra la base POR SU MOTIVO."""
    open_, high, low, close, ts, vwaps = _dia_vwap()
    high[7] = 10.45      # cruza el lote (10,4), no el trade (10,506)
    high[11] = 10.6      # cruza el stop del trade
    niveles = [_nivel_add(_senal(4), lot_stop={"mode": "pct", "pct": 4.0})]
    res = _correr(open_, high, low, close, ts, _senal(1), _senal(14), niveles,
                  vwaps=vwaps, **HS_VWAP)
    razones = [t["exit_reason"] for t in res["trades"]]
    assert razones == ["Pyramid Lot Stop", "SL"], razones
    lote, sl_trade = res["trades"]
    assert lote["exit_price"] == 10.4 and lote["size"] == 10.0
    # el stop del trade cierra la base al nivel VWAP+2 %, clamped a la vela
    assert sl_trade["exit_price"] == 10.506 and sl_trade["size"] == 10.0
    assert sl_trade["stop_loss"] == 10.506


def test_stop_vwap_manda_en_la_misma_vela_sin_doble_fill():
    """Una SOLA vela (high 10,6) cruza el lote (10,4) y el VWAP-stop (10,506):
    manda el global — sale TODO por 'SL' a 10,506 y NO se registra cierre de
    lote (§3.4, sin dobles fills)."""
    open_, high, low, close, ts, vwaps = _dia_vwap()
    high[7] = 10.6
    niveles = [_nivel_add(_senal(4), lot_stop={"mode": "pct", "pct": 4.0})]
    res = _correr(open_, high, low, close, ts, _senal(1), _senal(14), niveles,
                  vwaps=vwaps, **HS_VWAP)
    razones = [t["exit_reason"] for t in res["trades"]]
    assert razones == ["SL"], razones
    assert res["trades"][0]["size"] == 20.0
    assert res["trades"][0]["exit_price"] == 10.506


# ── Payload: _build_executions con piernas de lote ─────────────────────────

def test_build_executions_sin_duplicar_el_cierre_de_lote():
    """El cierre de lote sale por partida doble (leg + pyr_exec kind lot_stop):
    la bitácora debe quedarse con la entrada de pirámide (dice el nivel), NO
    pintar dos marcadores. Y el label dice «SL lote», con sl_px para la línea
    punteada del gráfico."""
    from app.services.backtest_service import _build_executions

    ts = 1789445000
    run = [
        # cierre final de la posición (la base, tras salir el lote)
        {"entry_time_epoch": ts, "entry_price": 10.0, "size": 10.0,
         "exit_time_epoch": ts + 600, "exit_price": 9.0, "pnl": 10.0,
         "exit_reason": "Signal"},
        # la pierna del SL de lote (el simulador también la emite como trade)
        {"entry_time_epoch": ts, "entry_price": 9.9, "size": 10.0,
         "exit_time_epoch": ts + 300, "exit_price": 10.395, "pnl": -4.95,
         "exit_reason": "Pyramid Lot Stop"},
    ]
    run[0]["pyr_executions"] = [
        {"kind": "add", "idx": 5, "time_epoch": ts + 60, "price": 9.9,
         "size": 10.0, "level": 1, "position_size": 20.0},
        {"kind": "lot_stop", "idx": 9, "time_epoch": ts + 300,
         "price": 10.395, "size": 10.0, "level": 1,
         "position_size": 10.0, "pnl": -4.95, "sl_px": 10.395},
    ]
    execs = _build_executions(run)
    clases = [(e["kind"], e["time_epoch"]) for e in execs]
    # UN solo marcador en el instante del lote (la entrada de bitácora), y la
    # leg de "Pyramid Lot Stop" queda deduplicada.
    en_el_lote = [e for e in execs if e["time_epoch"] == ts + 300]
    assert len(en_el_lote) == 1, clases
    assert en_el_lote[0]["kind"] == "lot_stop"
    assert en_el_lote[0]["label"] == "Pirámide 1: SL lote"
    assert en_el_lote[0]["sl_px"] == 10.395
    # la entrada sigue siendo la base (sum legs − adds = 20 − 10)
    assert execs[0]["kind"] == "entry" and execs[0]["size"] == 10.0
