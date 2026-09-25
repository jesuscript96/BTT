"""Los procesos de ALERTA y PREALERTA (23-sep-2026).

Lo que hay que garantizar, que es justo lo que costo descubrir midiendo:

  1. El proceso de alertas recibe velas de minuto y devuelve los avisos.
  2. El de prealertas evalua UNA VEZ POR SEGUNDO Y TICKER aunque le lluevan
     prints. Es el arreglo del 97 % de CPU del 23-sep: el print se aplica
     igual, solo se deja de repetir el calculo.
  3. Mandarles datos NUNCA bloquea al bot, ni con el hijo muerto. Es el motivo
     entero de que existan.
  4. Si un hijo se muere, el vigilante lo levanta y le devuelve lo que sabia.
  5. El de prealertas NO publica las alertas del cierre (las publica el de
     alertas): si lo hiciera, cada aviso saldria dos veces por Telegram.
"""
import time

import pytest

from app.services import bot_alerts_alerta_proceso as ap
from app.services import bot_alerts_prealerta_proceso as pp
from app.services.bot_alerts_proceso_base import Vigilante


def _velas(sym="AAA", n=30, precio=1.0, minuto0=None):
    """Un dia a medias: `n` velas de minuto consecutivas."""
    import pandas as pd
    base = pd.Timestamp("2026-09-23 09:30:00")
    filas = []
    for i in range(n):
        p = precio + i * 0.01
        filas.append({"timestamp": str(base + pd.Timedelta(minutes=i)),
                      "open": p, "high": p * 1.02, "low": p * 0.99,
                      "close": p, "volume": 100000.0})
    return filas


def _print(sym="AAA", precio=1.5, seg=50, ms_min=None):
    """Un print suelto en el segundo `seg` de un minuto."""
    import pandas as pd
    base = pd.Timestamp("2026-09-23 09:59:00", tz="America/New_York")
    ms = int(base.timestamp() * 1000) + seg * 1000
    return {"ev": "T", "sym": sym, "p": precio, "s": 100, "t": ms, "pt": ms, "c": []}


def _esperar(cond, segundos=25.0, paso=0.2):
    fin = time.time() + segundos
    while time.time() < fin:
        if cond():
            return True
        time.sleep(paso)
    return False


# ── 1. el proceso de alertas ──────────────────────────────────────────────
@pytest.mark.timeout(120)
def test_alerta_aplica_velas_y_contesta_por_cada_una():
    recibidas = []
    a = ap.AlertaEnProceso(al_eventos=lambda tk, m, ts, evs, rec: recibidas.append((tk, m, evs)))
    a.arrancar()
    try:
        a.configurar([])
        filas = _velas()
        a.hidratar("AAA", filas[:20], {"prev_close": 1.0})
        for fila in filas[20:]:
            a.vela("AAA", fila)
        # Contesta SIEMPRE, haya avisos o no: el minuto hace falta aunque este
        # vacio (antes lo necesitaba el de prealertas para cerrar las suyas).
        assert _esperar(lambda: len(recibidas) >= 10), \
            f"solo llegaron {len(recibidas)} de 10 velas"
        assert all(tk == "AAA" for tk, _, _ in recibidas)
    finally:
        a.parar()


@pytest.mark.timeout(120)
def test_alerta_hidratar_no_corre_en_el_bot():
    """La hidratacion (1 s la primera del dia, por compilar el motor) es lo que
    cada manyana mordia la lectura del socket. Aqui se comprueba que la llamada
    del bot vuelve al instante: el trabajo pasa al hijo."""
    hidratados = []
    a = ap.AlertaEnProceso(al_hidratado=lambda tk, n, evs, pc: hidratados.append((tk, n)))
    a.arrancar()
    try:
        a.configurar([])
        t0 = time.perf_counter()
        a.hidratar("AAA", _velas(n=300), {"prev_close": 1.0})
        tardado = time.perf_counter() - t0
        assert tardado < 0.05, f"hidratar bloqueo al bot {tardado:.3f} s"
        assert _esperar(lambda: hidratados), "el hijo no contesto a la hidratacion"
        assert hidratados[0] == ("AAA", 300)
    finally:
        a.parar()


# ── 2. el recorte de la prealerta ─────────────────────────────────────────
@pytest.mark.timeout(120)
def test_prealerta_evalua_una_vez_por_segundo_y_ticker():
    """EL ARREGLO DEL 23-sep. Le llueven 400 prints del MISMO segundo y solo
    puede evaluar una vez. Con una por print, el bot llego al 97 % de su unico
    nucleo y la alerta paso de 1,2 s a 15 s."""
    metricas = []
    # El bot resume cada 5 min; aqui cada segundo para no esperar.
    p = pp.PrealertaEnProceso(al_metricas=metricas.append, cada_seg=1.0)
    p.arrancar()
    try:
        p.configurar([])
        p.hidratar("AAA", _velas(), {"prev_close": 1.0})
        p.tickers(["AAA"])
        for _ in range(400):
            p.operacion(_print(seg=50))
        for _ in range(400):
            p.operacion(_print(seg=51))
        assert _esperar(lambda: metricas, segundos=40), "el hijo no mando metricas"
        m = metricas[-1]
        # 800 prints aplicados, pero solo dos segundos distintos -> 2 evaluaciones.
        assert m["evaluaciones"] <= 2, \
            f"evaluo {m['evaluaciones']} veces; deberia ser una por segundo"
        assert m["prints"] > 0, "los prints tienen que aplicarse igualmente"
    finally:
        p.parar()


@pytest.mark.timeout(120)
def test_prealerta_no_publica_las_alertas_del_cierre():
    """El de prealertas aplica la vela cerrada para seguir en sincronia, pero
    NO devuelve sus avisos: los publica el de alertas. Si los devolviera, cada
    aviso saldria dos veces por Telegram."""
    avisos = []
    p = pp.PrealertaEnProceso(al_prealerta=lambda *a: avisos.append(a))
    p.arrancar()
    try:
        p.configurar([])
        filas = _velas()
        p.hidratar("AAA", filas[:20], {"prev_close": 1.0})
        p.tickers(["AAA"])
        for fila in filas[20:]:
            p.vela("AAA", fila)
        time.sleep(4)
        assert not avisos, f"el proceso de prealertas publico {len(avisos)} avisos de cierre"
    finally:
        p.parar()


# ── 3. no bloquear nunca ──────────────────────────────────────────────────
@pytest.mark.timeout(120)
@pytest.mark.parametrize("cual", ["alerta", "prealerta"])
def test_mandar_datos_no_bloquea_aunque_el_hijo_este_muerto(cual):
    hijo = ap.AlertaEnProceso() if cual == "alerta" else pp.PrealertaEnProceso()
    hijo.arrancar()
    try:
        hijo._proc.kill()
        hijo._proc.join(5)
        filas = _velas(n=200)
        t0 = time.perf_counter()
        for _ in range(200):
            if cual == "alerta":
                hijo.vela("AAA", filas[0])
            else:
                hijo.operacion(_print())
        tardado = time.perf_counter() - t0
        assert tardado < 1.0, f"mandar datos bloqueo al bot {tardado:.2f} s"
    finally:
        hijo.parar()


# ── 4. el vigilante ───────────────────────────────────────────────────────
@pytest.mark.timeout(150)
def test_el_vigilante_levanta_al_hijo_y_le_devuelve_lo_que_sabia():
    hidratados = []
    a = ap.AlertaEnProceso(al_hidratado=lambda tk, n, evs, pc: hidratados.append(tk))
    a.arrancar()
    v = Vigilante([a], cada_seg=1.0)
    try:
        a.configurar([])
        a.hidratar("AAA", _velas(), {"prev_close": 1.0})
        assert _esperar(lambda: hidratados), "no hidrato la primera vez"
        hidratados.clear()

        v.arrancar()
        a._proc.kill()
        a._proc.join(5)
        assert _esperar(lambda: a.vivo() and a.reinicios == 1, segundos=30), \
            "el vigilante no lo levanto"
        # Sin mandarle nada mas, vuelve a tener el dia de AAA: el estado viajo.
        assert _esperar(lambda: "AAA" in hidratados, segundos=30), \
            "tras resucitar no recupero el pasado del ticker"
    finally:
        v.parar()
        a.parar()


def test_el_resumen_del_vigilante_dice_quien_esta_vivo():
    a = ap.AlertaEnProceso()
    p = pp.PrealertaEnProceso()
    v = Vigilante([a, p])
    texto = v.resumen()
    assert "alerta" in texto and "prealerta" in texto
    assert "MUERTO" in texto          # aun no se han arrancado


# ── 5. la recuperacion tras un corte no repite velas ──────────────────────
@pytest.mark.timeout(120)
def test_prealerta_recuperar_tras_un_corte_no_repite_velas():
    """EL FALLO DEL 25-sep. Al reconectar, el bot manda el DIA ENTERO por REST
    a los dos procesos. El de prealertas las aplicaba todas otra vez y quedaban
    REPETIDAS (INLF y CTNT, 04:00-04:04 dobles, tras un 1008). Ahora solo entra
    lo que falta, como en el de alertas."""
    avisos = []
    p = pp.PrealertaEnProceso()
    p.al_aviso = avisos.append
    p.arrancar()
    try:
        p.configurar([])
        filas = _velas(n=22)
        p.hidratar("AAA", filas[:20], {"prev_close": 1.0})
        p.tickers(["AAA"])
        # El dia entero, 20 que ya tiene + 2 que faltan: solo deben entrar 2.
        p.vela_lote("AAA", filas)
        assert _esperar(lambda: any("del hueco aplicadas" in a for a in avisos), segundos=30), \
            f"no aplico ninguna vela del hueco: {avisos}"
        assert "AAA: 2 vela(s) del hueco aplicadas" in avisos, \
            f"debia aplicar exactamente las 2 que faltaban: {avisos}"
        # Otra vez el mismo dia: ya no falta ninguna, no debe aplicar nada.
        avisos.clear()
        p.vela_lote("AAA", filas)
        time.sleep(3)
        assert not any("del hueco aplicadas" in a for a in avisos), \
            f"volvio a aplicar velas que ya tenia: {avisos}"
    finally:
        p.parar()
