"""Recarga en caliente de las estrategias vigiladas, y «Parado» = cerrar.

LO QUE PASO. Hasta el 11-sep-2026 el bot leia la lista de estrategias UNA vez
al arrancar. Con el bot esperando a que se marcara alguna, Jaume marco dos
seguidas: salio de la espera con la primera y nunca se entero de la segunda.
Una estrategia RTH entera sin vigilar, sin un solo error. Y editar una
estrategia con el bot en marcha tampoco le llegaba (el `size_by_sl` de la
piramide, el dia anterior).

LO QUE HAY QUE GARANTIZAR:
  1. Anyadir, quitar y cambiar estrategias en caliente.
  2. Sin recompilar lo que no cambio (compilar es lo caro).
  3. SIN PERDER LA MEMORIA DEL DIA: lo que ya se aviso sigue avisado. Si se
     perdiera, tocar una casilla repetiria las alertas de la manyana.
  4. El backend sube la version cuando cambia algo, y el cliente la recoge en
     el mismo /estado que ya pide cada 5 s.
  5. Un bot que se cierra manda «terminado», y el boton NO lo cuenta como vivo.
"""
import duckdb
import httpx
import pytest

from app.services import bot_alerts_engine as mod
from app.services import bot_alerts_service as bas
from app.services import bot_alerts_cliente as cli_mod
from app.routers import bot_alerts as router


def _est(sid, nombre="E", riesgo=300.0, ventana=None, extra=None):
    d = {"bias": "short", "entry_logic": {"root_condition": {"type": "group",
         "operator": "AND", "conditions": []}}, "risk_management": {}}
    if extra:
        d.update(extra)
    return {"strategy_id": sid, "name": nombre, "riesgo_usd": riesgo,
            "definition": d, "ventana": ventana or {"inicio": "04:00", "fin": "16:00"}}


@pytest.fixture
def compilaciones(monkeypatch):
    """Cuenta las llamadas al compilador, que es lo caro."""
    n = {"v": 0}

    def falso(sdef):
        n["v"] += 1
        # Como el de verdad: MODIFICA la definicion en sitio (normaliza
        # nombres). Sin esto el test no habria cazado el falso «cambiada».
        sdef["_normalizado"] = True
        return {"compilado": True}

    monkeypatch.setattr(mod, "compile_strategy_def", falso)
    return n


# ── 1. anyadir / quitar / cambiar ─────────────────────────────────────────
def test_anyadir_una_estrategia_en_caliente(compilaciones):
    m = mod.MotorAlertas([_est("a", "1B")])
    r = m.actualizar([_est("a", "1B"), _est("b", "2B")])
    assert r == {"anyadidas": ["2B"], "quitadas": [], "cambiadas": []}
    assert [e["strategy_id"] for e in m.estrategias] == ["a", "b"]


def test_quitar_una_estrategia_en_caliente(compilaciones):
    m = mod.MotorAlertas([_est("a", "1B"), _est("b", "2B")])
    r = m.actualizar([_est("a", "1B")])
    assert r == {"anyadidas": [], "quitadas": ["2B"], "cambiadas": []}
    assert [e["strategy_id"] for e in m.estrategias] == ["a"]


def test_quitar_todas_deja_el_motor_vacio_sin_reventar(compilaciones):
    m = mod.MotorAlertas([_est("a", "1B")])
    r = m.actualizar([])
    assert r["quitadas"] == ["1B"]
    assert m.estrategias == []


@pytest.mark.parametrize("cambio", [
    {"riesgo": 500.0},
    {"ventana": {"inicio": "09:30", "fin": "11:30"}},
    {"extra": {"risk_management": {"size_by_sl": True}}},
    {"nombre": "1B renombrada"},
])
def test_cambiar_algo_de_una_estrategia_la_recompila(compilaciones, cambio):
    """El caso del 10-sep: se cambio `size_by_sl` de la piramide con el bot en
    marcha y siguio con la definicion vieja toda la sesion."""
    m = mod.MotorAlertas([_est("a", "1B")])
    r = m.actualizar([_est("a", **{**{"nombre": "1B"}, **cambio})])
    assert r["cambiadas"] == [cambio.get("nombre", "1B")]
    assert r["anyadidas"] == [] and r["quitadas"] == []


# ── 2. sin recompilar lo que no cambio ────────────────────────────────────
def test_lo_que_no_cambia_no_se_recompila(compilaciones):
    m = mod.MotorAlertas([_est("a", "1B"), _est("b", "2B")])
    assert compilaciones["v"] == 2
    r = m.actualizar([_est("a", "1B"), _est("b", "2B")])
    assert r == {"anyadidas": [], "quitadas": [], "cambiadas": []}
    assert compilaciones["v"] == 2, "recompilo sin haber cambiado nada"

    m.actualizar([_est("a", "1B"), _est("b", "2B"), _est("c", "3B")])
    assert compilaciones["v"] == 3, "solo la nueva"


# ── 3. LA MEMORIA DEL DIA SE CONSERVA ─────────────────────────────────────
def test_actualizar_no_borra_lo_ya_avisado(compilaciones):
    """Si esto fallara, marcar una casilla a las 10:30 repetiria la alerta de
    entrada de las 10:02 de todos los tickers. Es lo mas grave que podria hacer
    la recarga."""
    m = mod.MotorAlertas([_est("a", "1B"), _est("b", "2B")])
    par = m._par("TNON", "a")
    par.entradas_avisadas.add(17)
    par.salidas_avisadas.add((17, 0))

    m.actualizar([_est("a", "1B", riesgo=999.0), _est("c", "3B")])   # cambia a, quita b, anyade c

    par2 = m._par("TNON", "a")
    assert par2 is par, "se creo un estado nuevo: la memoria se perdio"
    assert 17 in par2.entradas_avisadas
    assert (17, 0) in par2.salidas_avisadas


def test_una_estrategia_que_vuelve_recupera_su_memoria(compilaciones):
    """Quitar y volver a poner una casilla no puede volver a avisar lo de la
    manyana."""
    m = mod.MotorAlertas([_est("a", "1B")])
    m._par("TNON", "a").entradas_avisadas.add(5)
    m.actualizar([])
    m.actualizar([_est("a", "1B")])
    assert 5 in m._par("TNON", "a").entradas_avisadas


def test_reiniciar_si_borra_todo(compilaciones):
    """El cambio de dia sigue tirando la memoria: eso no cambia."""
    m = mod.MotorAlertas([_est("a", "1B")])
    m._par("TNON", "a").entradas_avisadas.add(5)
    m.reiniciar()
    assert 5 not in m._par("TNON", "a").entradas_avisadas


# ── 4. la version: backend la sube, el cliente la recoge ─────────────────
def test_marcar_una_estrategia_sube_la_version():
    con = duckdb.connect(":memory:")
    v0 = bas.version_estrategias()
    bas.set_watch(con, "s1", True, 300.0)
    assert bas.version_estrategias() == v0 + 1
    bas.set_watch(con, "s1", False, 300.0)
    assert bas.version_estrategias() == v0 + 2


def test_el_cliente_recoge_la_version_del_estado(monkeypatch):
    class _Falso:
        def request(self, metodo, url, **kw):
            return httpx.Response(200, json={"vigilando": True, "estrategias_version": 7},
                                  request=httpx.Request(metodo, url))
        def close(self): pass

    monkeypatch.setattr(cli_mod.httpx, "Client", lambda *a, **k: _Falso())
    c = cli_mod.ClienteBackend("http://backend")
    assert c.version_estrategias is None
    assert c.debe_vigilar() is True
    assert c.version_estrategias == 7


def test_un_estado_sin_version_no_la_pisa(monkeypatch):
    """Backend viejo: la version no viene. El cliente conserva la ultima en vez
    de ponerla a None y disparar una recarga en cada latido."""
    class _Falso:
        def request(self, metodo, url, **kw):
            return httpx.Response(200, json={"vigilando": True},
                                  request=httpx.Request(metodo, url))
        def close(self): pass

    monkeypatch.setattr(cli_mod.httpx, "Client", lambda *a, **k: _Falso())
    c = cli_mod.ClienteBackend("http://backend")
    c.version_estrategias = 3
    c.debe_vigilar()
    assert c.version_estrategias == 3


# ── 5. «terminado» no cuenta como vivo ───────────────────────────────────
def test_un_bot_que_se_ha_cerrado_no_cuenta_como_vivo():
    from datetime import datetime
    ahora = str(datetime.now())
    assert router._bot_esta_vivo({"latido_at": ahora, "detalle": "conectado · RTH"}) is True
    assert router._bot_esta_vivo({"latido_at": ahora, "detalle": "terminado"}) is False, (
        "sin esto, darle a Vigilar en los 150 s siguientes a Parado no arrancaria nada")
    assert router._bot_esta_vivo({"latido_at": None}) is False
