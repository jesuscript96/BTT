"""El radar en un proceso aparte (22-sep-2026).

Lo que hay que garantizar, y que es justo lo que costo descubrir midiendo:
  1. El hijo recibe las velas del mercado y devuelve candidatos.
  2. Mandarle velas NO bloquea al bot, aunque el hijo este ocupado o muerto:
     es el motivo entero del cambio.
  3. Si el hijo se muere, se resucita y se le devuelve lo que sabia (el estado
     del mercado del bot), para no perder el maximo de premercado del dia.
  4. `volcar`/`cargar` del estado del mercado son simetricos.
"""
import time

import pytest

from app.services import bot_alerts_radar_proceso as rp
from app.services.bot_alerts_mercado import MercadoEnVivo


def _vela(sym, precio, volumen=100000.0, minuto=None):
    ms = int((minuto if minuto is not None else time.time() // 60 * 60) * 1000)
    return {"ev": "AM", "sym": sym, "v": volumen, "av": volumen, "op": precio,
            "o": precio, "c": precio, "h": precio, "l": precio, "vw": precio,
            "a": precio, "z": 100, "s": ms, "e": ms + 60000}


ESTRATEGIA = [{
    "strategy_id": 1, "name": "gap grande",
    "definition": {"universe_filters": {"rules": [
        {"metric": "Current Gap %", "op": ">=", "value": 50},
    ]}},
}]


def _esperar(cond, segundos=25.0, paso=0.25):
    fin = time.time() + segundos
    while time.time() < fin:
        if cond():
            return True
        time.sleep(paso)
    return False


@pytest.mark.timeout(90)
def test_el_hijo_recibe_velas_y_devuelve_candidatos():
    radar = rp.RadarEnProceso(cada_seg=0.5)
    radar.arrancar()
    try:
        radar.configurar(ESTRATEGIA)
        radar.sembrar_prev_close({"AAA": 1.00, "BBB": 10.0})
        # AAA cotiza a 2,00 con cierre de ayer 1,00: gap del 100 %.
        radar.enviar_velas([_vela("AAA", 2.00), _vela("BBB", 10.05)])
        assert _esperar(lambda: any(c.ticker == "AAA" for c in radar.candidatos())), \
            "el radar deberia haber admitido AAA (gap 100 %)"
        assert not any(c.ticker == "BBB" for c in radar.candidatos()), \
            "BBB no hace gap: no deberia entrar"
        assert radar.coste_barrido >= 0.0 and radar.ultimo_barrido > 0
    finally:
        radar.parar()


@pytest.mark.timeout(90)
def test_mandar_velas_no_bloquea_aunque_el_hijo_no_lea():
    """La razon de ser del cambio: el bot no puede pararse a esperar al radar.

    Se arranca y se MATA al hijo, que es el peor caso (nadie lee la tuberia), y
    se le mandan lotes grandes. Si algo bloqueara, esto tardaria segundos.
    """
    radar = rp.RadarEnProceso(cada_seg=5.0)
    radar.arrancar()
    try:
        radar._proc.kill()
        radar._proc.join(5)
        lote = [_vela(f"TK{i:04d}", 1.0 + i / 1000) for i in range(5700)]
        t0 = time.perf_counter()
        for _ in range(20):
            radar.enviar_velas(lote)
        tardado = time.perf_counter() - t0
        assert tardado < 1.0, f"mandar velas bloqueo al bot {tardado:.2f} s"
        assert radar.lotes_tirados > 0, "con el hijo muerto la cola deberia desbordar y tirar lotes"
    finally:
        radar.parar()


@pytest.mark.timeout(120)
def test_si_el_hijo_muere_se_resucita_con_lo_que_sabia():
    radar = rp.RadarEnProceso(cada_seg=0.5)
    radar.arrancar()
    try:
        radar.configurar(ESTRATEGIA)
        radar.sembrar_prev_close({"AAA": 1.00})
        radar.enviar_velas([_vela("AAA", 2.00)])
        assert _esperar(lambda: any(c.ticker == "AAA" for c in radar.candidatos()))

        # El bot lleva su propio estado del mercado: es lo que le devuelve.
        mercado = MercadoEnVivo()
        mercado.sembrar_prev_close({"AAA": 1.00})
        mercado.aplicar(_vela("AAA", 2.00))

        radar._proc.kill()
        radar._proc.join(5)
        assert not radar.vivo()
        assert radar.vigilar(mercado.volcar()) is True
        assert radar.vivo() and radar.reinicios == 1
        # Sin mandarle ni una vela mas, vuelve a tener a AAA: el estado viajo.
        assert _esperar(lambda: any(c.ticker == "AAA" for c in radar.candidatos())), \
            "tras resucitar deberia recordar el gap de AAA"
    finally:
        radar.parar()


def test_volcar_y_cargar_el_estado_del_mercado():
    a = MercadoEnVivo()
    a.sembrar_prev_close({"AAA": 1.00})
    a.aplicar(_vela("AAA", 2.00))
    datos = a.volcar()

    b = MercadoEnVivo()
    assert b.cargar(datos) == len(datos)
    st = b.estado("AAA")
    assert st is not None and st.prev_close == 1.00 and st.precio == 2.00
    assert a.estado("AAA").metricas() == st.metricas()
