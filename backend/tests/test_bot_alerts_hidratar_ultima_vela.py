"""Al hidratar un ticker, la ULTIMA vela completa es presente, no pasado.

LO QUE PASO (14-sep-2026, ELMT). El radar admite un ticker cuando su metrica
cruza el umbral, y eso ocurre en una vela concreta: la ultima cerrada. Si la
senyal de entrada cae en esa misma vela, sellarla como «pasado» la tira:

    06:58  PMH=24.19  gap=49,4 %  close=24.09
    06:59  PMH=24.46  gap=51,1 %  close=23.95   <- cruza el 50 %  Y  entrada

El radar lo admitio a las 13:00:07 (7 s despues del cierre), hidrato 104 velas
y el aviso de entrada salio como «1 avisos del pasado descartados». Jaume se
quedo sin la senyal; el simulador, con una posicion abierta cuyas salidas SI
iban a avisar mas tarde.

No es mala suerte: el filtro del radar y la entrada de 1B comparten el umbral
(gap >= 50), asi que la vela que admite es a menudo la vela que entra.

LO QUE HAY QUE GARANTIZAR:
  1. La entrada en la ultima vela completa SE AVISA.
  2. La entrada en una vela anterior se SELLA (no se avisa) y NO reaparece
     despues — que es lo que protegia el disenyo original (FLYE, 1-sep).
  3. La vela del minuto EN CURSO se aparta: ni se sella ni se evalua. La traera
     el feed cuando cierre.
"""
import numpy as np
import pandas as pd
import pytest

from app.services import bot_alerts_engine as eng
from app.services import bot_alerts_runner as run

T0 = pd.Timestamp("2026-09-14 06:00")
STATS = {"prev_close": 16.19}


def _frame(n, t0=T0):
    ts = pd.date_range(t0, periods=n, freq="1min")
    return pd.DataFrame({
        "timestamp": ts,
        "open": np.linspace(20, 24, n), "high": np.linspace(20.5, 24.5, n),
        "low": np.linspace(19.5, 23.5, n), "close": np.linspace(20, 24, n),
        "volume": np.full(n, 50_000.0),
    })


@pytest.fixture
def runner(monkeypatch):
    """Un RunnerAlertas con el traductor y el simulador sustituidos. La prueba
    decide en que indices de vela esta encendida la entrada."""
    guion = {"entradas_en": set()}

    def falso_translate(frame, sdef, stats, compiled=None):
        n = len(frame)
        ent = np.zeros(n, dtype=bool)
        for k in guion["entradas_en"]:
            if 0 <= k < n:
                ent[k] = True
        return {"direction": "Short", "entries": ent, "exits": np.zeros(n, dtype=bool),
                "accept_reentries": True, "max_reentries": -1}

    monkeypatch.setattr(eng, "translate_strategy", falso_translate)
    monkeypatch.setattr(eng, "simulate", lambda **kw: {"trades": []})
    monkeypatch.setattr(eng, "_kwargs_simulate", lambda *a, **k: {})
    monkeypatch.setattr(eng, "compile_strategy_def", lambda sdef: {})
    monkeypatch.setattr(eng, "calcular_acciones", lambda *a, **k: (100.0, None, None),
                        raising=False)

    est = {"strategy_id": "s1", "name": "1B", "riesgo_usd": 300.0,
           "definition": {"bias": "short", "risk_management": {}},
           "ventana": {"inicio": "04:00", "fin": "16:00"}}
    r = run.RunnerAlertas([est], al_avisar=lambda ev: None)
    r._guion = guion
    return r


def _entradas(evs):
    return [e for e in evs if e.tipo == "entrada"]


# ── 1. la entrada en la ULTIMA vela completa se avisa ────────────────────
def test_la_entrada_en_la_ultima_vela_completa_se_avisa(runner):
    """El caso ELMT: 10 velas, la entrada se cumple en la ultima (indice 9), y
    el radar admite el ticker 7 segundos despues de que cierre."""
    runner._guion["entradas_en"] = {9}
    df = _frame(10)                                   # 06:00 .. 06:09
    ahora = pd.Timestamp("2026-09-14 06:10:07")       # la de 06:09 esta cerrada
    evs = runner.hidratar("ELMT", df, STATS, ahora=ahora)
    assert len(_entradas(evs)) == 1, "la entrada de la ultima vela se tiro como pasado"
    assert _entradas(evs)[0].ticker == "ELMT"


# ── 2. la entrada en una vela anterior se sella y NO reaparece ───────────
def test_la_entrada_antigua_se_sella_y_no_reaparece(runner):
    """Lo que protegia el disenyo original: una entrada de hace 5 velas no se
    avisa al hidratar, y tampoco la vela siguiente la «descubre»."""
    runner._guion["entradas_en"] = {4}
    df = _frame(10)
    evs = runner.hidratar("ELMT", df, STATS, ahora=pd.Timestamp("2026-09-14 06:10:07"))
    assert _entradas(evs) == [], "una entrada de hace 5 velas no puede avisar"

    # llega la vela siguiente por el feed: la entrada de la 4 sigue sellada
    vela = _frame(11).iloc[10].to_dict()
    evs2 = runner.nueva_vela("ELMT", vela, STATS)
    assert _entradas(evs2) == []


def test_la_entrada_penultima_se_sella(runner):
    """Solo la ULTIMA completa es presente. La penultima ya es pasado."""
    runner._guion["entradas_en"] = {8}
    df = _frame(10)
    evs = runner.hidratar("ELMT", df, STATS, ahora=pd.Timestamp("2026-09-14 06:10:07"))
    assert _entradas(evs) == []


# ── 3. la vela en curso se aparta ─────────────────────────────────────────
def test_la_vela_en_curso_no_se_evalua_ni_se_sella(runner):
    """Massive devuelve por REST el minuto a medias. Si la entrada «parece»
    cumplirse en esa vela a medias, NO se avisa: puede deshacerse antes de
    cerrar. La traera el feed entera."""
    runner._guion["entradas_en"] = {9}                # la ultima fila del REST
    df = _frame(10)                                   # 06:00 .. 06:09
    ahora = pd.Timestamp("2026-09-14 06:09:30")       # la de 06:09 esta EN CURSO
    evs = runner.hidratar("ELMT", df, STATS, ahora=ahora)
    assert _entradas(evs) == [], "se aviso de una vela a medias"
    # y no se ha guardado: el frame tiene 9 velas, la de 06:09 llegara por el feed
    assert len(runner._velas["ELMT"]) == 9

    # cuando el feed la trae cerrada, ENTONCES si se evalua y avisa
    vela = df.iloc[9].to_dict()
    evs2 = runner.nueva_vela("ELMT", vela, STATS)
    assert len(_entradas(evs2)) == 1


def test_con_la_vela_en_curso_apartada_la_anterior_es_la_actual(runner):
    """REST trae 06:00..06:09 a las 06:09:30. La de 06:09 esta a medias, asi
    que la ACTUAL es la de 06:08, y una entrada ahi si se avisa."""
    runner._guion["entradas_en"] = {8}
    df = _frame(10)
    evs = runner.hidratar("ELMT", df, STATS, ahora=pd.Timestamp("2026-09-14 06:09:30"))
    assert len(_entradas(evs)) == 1


# ── bordes ────────────────────────────────────────────────────────────────
def test_sin_velas_no_revienta(runner):
    evs = runner.hidratar("ELMT", pd.DataFrame(), STATS,
                          ahora=pd.Timestamp("2026-09-14 06:10:07"))
    assert evs == []
    assert "ELMT" in runner._hidratados


def test_una_sola_vela_completa_se_evalua_como_actual(runner):
    """Un ticker que entra al radar en su primer minuto: no hay pasado que
    sellar, y esa unica vela es la actual."""
    runner._guion["entradas_en"] = {0}
    df = _frame(1)
    evs = runner.hidratar("ELMT", df, STATS, ahora=pd.Timestamp("2026-09-14 06:01:07"))
    # con una sola vela el motor no puede ver flanco (no hay anterior): no avisa,
    # pero tampoco revienta y la vela queda guardada
    assert isinstance(evs, list)
    assert len(runner._velas["ELMT"]) == 1
