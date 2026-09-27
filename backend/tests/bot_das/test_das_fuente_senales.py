"""Tests de `fuente_senales.py` y `enlace_bot_alertas.py` (documento §3.11, §6.1, §10).

QUÉ CUBRE. (1) Paridad `FuenteEnProceso` ↔ `RunnerAlertas` directo: mismos
`Evento` campo a campo y `Senal.id == id_evento` (R-A-05, R-A-06). (2) El radar
añade `strategy_id` por nombre y descarta nombres repetidos avisando UNA vez al
día (corrección 6, riesgo 25). (3) `FuenteTuberia` + `EnlaceEjecutor` en DOS
procesos (spawn): 5.000 mensajes sin pérdida ni desorden, reconexión tras
matar y relanzar el Listener, «hola» con hash distinto rechazado con aviso 3
(H-6), sin authkey → ValueError (riesgo 19). (4) Eventos de otra versión
descartados con aviso 2 (riesgo 18). (5) `FuenteGrabacion` reproduce
`AM_recorte.jsonl.gz` en orden de tiempo con el `Guion` y el `RelojSimulado`
avanza (R-O-02, injerto A §8.24). (6) Importar los módulos no carga pandas,
httpx ni websockets (injerto A §8.25, riesgo 29).

POR QUÉ ASÍ. Todo sin red exterior: la tubería escucha en 127.0.0.1 con
puerto 0 y los procesos hijos son funciones a nivel de módulo de este fichero
(spawn las reimporta). El motor de alertas se sustituye como en
`tests/test_bot_alerts_hidratar_ultima_vela.py` (translate/simulate falsos)
para que la señal caiga donde el test decide.

LAS TRAMPAS. Cada proceso hijo y cada fuente se paran en `finally`; las esperas
son sondeos con tope (≤ 20 s), nunca sleeps largos fijos.
"""
from __future__ import annotations

import dataclasses
import gzip
import json
import multiprocessing
import os
import socket
import subprocess
import sys
import time
from datetime import datetime, timedelta
from decimal import Decimal
from multiprocessing.connection import Client
from pathlib import Path
from typing import Any, Optional

import pytest

from app.bot_das import VERSION
from app.bot_das import enlace_bot_alertas as enl
from app.bot_das import fuente_senales as fs
from app.bot_das.reloj import ET, Reloj, RelojSimulado
from app.bot_das.tipos import Nivel, Senal

FIXTURES = Path(__file__).parent / "fixtures"
RUTA_AM = FIXTURES / "AM_recorte.jsonl.gz"
RUTA_GUION = FIXTURES / "guion_replay_ejemplo.json"
BACKEND = Path(__file__).resolve().parents[2]
HASH_BUENO = "sha256:motor-de-prueba"
INICIO_REPLAY = datetime(2026, 9, 25, 4, 0, tzinfo=ET)
ESPERA_MAX_S = 20.0


# ── ayudas a nivel de módulo (spawn las reimporta en el hijo) ───────────
@dataclasses.dataclass
class EventoFalso:
    """Lo mínimo de un `Evento` que la tubería exige (riesgo 18) + un número de secuencia."""
    tipo: str
    ticker: str
    strategy_id: str
    momento: Any
    seq: int


@dataclasses.dataclass
class EventoViejo:
    """Un `Evento` de «otra versión»: sin `strategy_id` (riesgo 18)."""
    tipo: str
    ticker: str
    momento: Any


def _clave() -> bytes:
    return os.urandom(16)


def _esperar(cond, segundos: float = ESPERA_MAX_S, paso: float = 0.02) -> bool:
    fin = time.monotonic() + segundos
    while time.monotonic() < fin:
        if cond():
            return True
        time.sleep(paso)
    return bool(cond())


def _hijo_eventos(direccion, authkey, n, motor_hash, cola_salud) -> None:
    """Proceso hijo: un `EnlaceEjecutor` que manda `n` mensajes «eventos» numerados y reporta su salud."""
    enlace = enl.EnlaceEjecutor(direccion, authkey, tope=n + 10, motor_hash=motor_hash,
                                reconectar_s=0.2, espera_ok_s=5.0)
    enlace.arrancar()
    try:
        for i in range(n):
            ev = EventoFalso("entrada", f"T{i % 7}", "s1", f"{i:019d}", i)   # id_evento usa momento[:19]
            enlace.eventos(ev.ticker, "09:30", i, [ev], False)
        _esperar(lambda: enlace.enviados >= n, segundos=15.0)
    finally:
        enlace.parar(vaciar_s=2.0)
        cola_salud.put(enlace.salud())


def _hijo_latidos(direccion, authkey, parar_ev, cola_salud) -> None:
    """Proceso hijo: un latido numerado cada 10 ms hasta que el padre diga basta."""
    enlace = enl.EnlaceEjecutor(direccion, authkey, motor_hash=HASH_BUENO, reconectar_s=0.2, espera_ok_s=5.0)
    enlace.arrancar()
    i = 0
    try:
        fin = time.monotonic() + 30.0
        while not parar_ev.is_set() and time.monotonic() < fin:
            enlace.latido(float(i), True)
            i += 1
            time.sleep(0.01)
    finally:
        enlace.parar(vaciar_s=1.0)
        cola_salud.put(enlace.salud())


def _hijo_hash_viejo(direccion, authkey, segundos, cola_salud) -> None:
    """Proceso hijo: un enlace con OTRO hash del motor; reintenta varias veces y reporta."""
    enlace = enl.EnlaceEjecutor(direccion, authkey, motor_hash="sha256:motor-viejo",
                                reconectar_s=0.2, espera_ok_s=5.0)
    enlace.arrancar()
    try:
        for i in range(3):
            enlace.eventos("ABCD", "09:30", i, [EventoFalso("entrada", "ABCD", "s1", f"m{i}", i)], False)
        _esperar(lambda: enlace.rechazos >= 3, segundos=segundos)
    finally:
        enlace.parar(vaciar_s=0.0)
        cola_salud.put(enlace.salud())


# ── fixtures ───────────────────────────────────────────────────────────
@pytest.fixture
def motor_falso(monkeypatch):
    """Motor de alertas con traductor y simulador sustituidos (forma de test_bot_alerts_hidratar_ultima_vela.py).

    `guion["entradas_en"]` = índices de vela (del frame del día) donde la entrada está encendida.
    """
    np = pytest.importorskip("numpy")
    from app.services import bot_alerts_engine as eng

    guion: dict = {"entradas_en": set()}

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
    monkeypatch.setattr(eng, "calcular_acciones", lambda *a, **k: 100.0)
    return guion


def _estrategia(sid: str = "s1", nombre: str = "1B") -> dict:
    return {"strategy_id": sid, "name": nombre, "riesgo_usd": 300.0,
            "definition": {"bias": "short", "risk_management": {}},
            "ventana": {"inicio": "04:00", "fin": "16:00"}}


def _velas(n: int = 30, precio: float = 1.0, base: str = "2026-09-25 04:00:00") -> list[dict]:
    """`n` velas de minuto consecutivas (forma de test_bot_alerts_procesos._velas, en el día del reloj)."""
    import pandas as pd
    t0 = pd.Timestamp(base)
    filas = []
    for i in range(n):
        p = precio + i * 0.01
        filas.append({"timestamp": str(t0 + pd.Timedelta(minutes=i)),
                      "open": p, "high": p * 1.02, "low": p * 0.99, "close": p, "volume": 100000.0})
    return filas


class Recolector:
    """Destino de señales y receptor de avisos (thread-safe: list.append)."""

    def __init__(self) -> None:
        self.senales: list[Senal] = []
        self.avisos: list[tuple[int, str]] = []

    def __call__(self, senal: Senal) -> None:
        self.senales.append(senal)

    def al_aviso(self, nivel: int, texto: str) -> None:
        self.avisos.append((nivel, texto))

    def de_clase(self, clase: str) -> list[Senal]:
        return [s for s in list(self.senales) if s.clase == clase]


@pytest.fixture
def tuberia():
    """Fábrica de `FuenteTuberia` en 127.0.0.1:0, paradas todas en el finally."""
    creadas: list[fs.FuenteTuberia] = []

    def crear(direccion=("127.0.0.1", 0), authkey: bytes = b"clave-de-test", hash_esperado: str = HASH_BUENO,
              version_minima: str = VERSION, rec: Optional[Recolector] = None, espera_hola_s: float = 5.0,
              espera_auth_s: float = 5.0):
        rec = rec if rec is not None else Recolector()
        fuente = fs.FuenteTuberia(direccion, authkey, rec, Reloj(), hash_esperado, version_minima,
                                  al_aviso=rec.al_aviso, espera_hola_s=espera_hola_s, espera_auth_s=espera_auth_s)
        creadas.append(fuente)
        fuente.arrancar()
        return fuente, rec

    try:
        yield crear
    finally:
        for fuente in creadas:
            fuente.parar()


@pytest.fixture
def enlaces():
    """Fábrica de `EnlaceEjecutor` en este proceso, parados en el finally."""
    creados: list[enl.EnlaceEjecutor] = []

    def crear(direccion, authkey: bytes = b"clave-de-test", **kw):
        kw.setdefault("motor_hash", HASH_BUENO)
        kw.setdefault("reconectar_s", 0.2)
        enlace = enl.EnlaceEjecutor(direccion, authkey, **kw)
        creados.append(enlace)
        enlace.arrancar()
        return enlace

    try:
        yield crear
    finally:
        for enlace in creados:
            enlace.parar(vaciar_s=0.0)


def _puerto_cerrado() -> tuple[str, int]:
    """Un puerto local donde nadie escucha (se liga y se suelta)."""
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()
    finally:
        s.close()


def _proceso(objetivo, *args):
    ctx = multiprocessing.get_context("spawn")
    cola = ctx.Queue()
    return ctx, cola, (lambda *extra: ctx.Process(target=objetivo, args=args + extra + (cola,), daemon=True))


def _cerrar_proceso(p) -> None:
    if p is None:
        return
    p.join(timeout=10)
    if p.is_alive():
        p.terminate()
        p.join(timeout=5)


# ═══ 0. importar no carga nada pesado (injerto A §8.25, riesgo 29) ═════
def test_importar_no_carga_pandas_ni_red():
    """Riesgo 29: el ejecutor en modo tubería no paga pandas; ningún módulo abre httpx ni websockets al importarse."""
    codigo = ("import sys; import app.bot_das.fuente_senales, app.bot_das.enlace_bot_alertas; "
              "import threading; "
              "print(sorted(m for m in ('pandas', 'httpx', 'websockets', 'app.services.bot_alerts_runner') "
              "if m in sys.modules), threading.active_count())")
    salida = subprocess.run([sys.executable, "-c", codigo], cwd=str(BACKEND), capture_output=True,
                            text=True, timeout=60, env={**os.environ, "PYTHONPATH": str(BACKEND)})
    assert salida.returncode == 0, salida.stderr
    assert salida.stdout.strip() == "[] 1"


# ═══ 1. utilidades puras ═══════════════════════════════════════════════
@pytest.mark.parametrize("estrategias, mapa, repetidos", [
    pytest.param([{"name": "1B", "strategy_id": "a"}, {"name": "2C", "strategy_id": "b"}],
                 {"1B": "a", "2C": "b"}, set(), id="correccion6-nombres-unicos"),
    pytest.param([{"name": "1B", "strategy_id": "a"}, {"name": "1B", "strategy_id": "b"},
                  {"name": "2C", "strategy_id": "c"}],
                 {"2C": "c"}, {"1B"}, id="correccion6-repetido-ids-distintos-fuera"),
    pytest.param([{"name": "1B", "strategy_id": "a"}, {"name": "1B", "strategy_id": "a"}],
                 {"1B": "a"}, set(), id="correccion6-multicuenta-mismo-id-no-es-ambiguo"),
    pytest.param([{"name": "", "strategy_id": "a"}, {"name": "X"}, "no-dict", {"strategy_id": "z"}],
                 {}, set(), id="correccion6-entradas-incompletas-ignoradas"),
    pytest.param([{"name": "1B", "strategy_id": "a"}, {"name": "1B", "strategy_id": "b"},
                  {"name": "1B", "strategy_id": "a"}],
                 {}, {"1B"}, id="correccion6-ambiguo-no-reaparece"),
])
def test_mapa_nombres(estrategias, mapa, repetidos):
    assert enl.mapa_nombres(estrategias) == (mapa, repetidos)


def test_anadir_y_anotar_strategy_id_no_mutan_y_descartan():
    """Corrección 6 / riesgo 25: la fila ambigua o desconocida no viaja con id; la original no se toca."""
    filas = [{"nombre": "1B", "acciones": 100}, {"nombre": "2C", "acciones": 5},
             {"nombre": "ZZ", "acciones": 1}, {"nombre": "2C", "strategy_id": "falso"}, "basura"]
    copia = json.loads(json.dumps(filas))
    validas, descartados = enl.anadir_strategy_id(filas, {"1B": "a", "2C": "b"}, repetidos={"2C"})
    assert validas == [{"nombre": "1B", "acciones": 100, "strategy_id": "a"}]
    assert descartados == ["2C", "ZZ", "2C", "None"]
    assert filas == copia
    anotadas = enl.anotar_strategy_id(filas, {"1B": "a", "2C": "b"}, repetidos={"2C"})
    assert anotadas == [{"nombre": "1B", "acciones": 100, "strategy_id": "a"}, {"nombre": "2C", "acciones": 5},
                        {"nombre": "ZZ", "acciones": 1}, {"nombre": "2C"}]


@pytest.mark.parametrize("version, motor_hash, rechaza", [
    pytest.param(VERSION, HASH_BUENO, None, id="H-6-mismo-hash-y-version-acepta"),
    pytest.param("2099.01.01", HASH_BUENO, None, id="R-O-01-version-posterior-acepta"),
    pytest.param(VERSION, "sha256:otro", "hash", id="H-6-hash-distinto-rechaza"),
    pytest.param(VERSION, "", "hash", id="H-6-hash-vacio-rechaza"),
    pytest.param(VERSION, None, "hash", id="H-6-hash-ausente-rechaza"),
    pytest.param("2020.01.01", HASH_BUENO, "anterior", id="R-O-01-version-vieja-rechaza"),
    pytest.param("v1", HASH_BUENO, "ilegible", id="R-O-01-version-ilegible-rechaza"),
    pytest.param(None, HASH_BUENO, "ilegible", id="R-O-01-sin-version-rechaza"),
])
def test_motivo_rechazo_hola(version, motor_hash, rechaza):
    motivo = fs.motivo_rechazo_hola(version, motor_hash, VERSION, HASH_BUENO)
    if rechaza is None:
        assert motivo is None
    else:
        assert motivo is not None and rechaza in motivo


@pytest.mark.parametrize("texto, esperado", [
    pytest.param("127.0.0.1:8765", ("127.0.0.1", 8765), id="3.11-host-puerto"),
    pytest.param(" localhost:9000 ", ("localhost", 9000), id="3.11-espacios"),
    pytest.param("\\\\.\\pipe\\bot_das", "\\\\.\\pipe\\bot_das", id="3.11-tuberia-con-nombre"),
])
def test_direccion_de_texto(texto, esperado):
    assert enl.direccion_de_texto(texto) == esperado


@pytest.mark.parametrize("texto", [
    pytest.param("", id="3.11-vacia"), pytest.param("127.0.0.1", id="3.11-sin-puerto"),
    pytest.param(":8765", id="3.11-sin-host"), pytest.param("h:0", id="3.11-puerto-cero"),
    pytest.param("h:70000", id="3.11-puerto-fuera"), pytest.param("h:-1", id="3.11-puerto-negativo"),
    pytest.param("h:80a", id="3.11-puerto-no-numero"),
])
def test_direccion_de_texto_invalida(texto):
    with pytest.raises(ValueError):
        enl.direccion_de_texto(texto)


@pytest.mark.parametrize("ev, falta", [
    pytest.param(EventoFalso("entrada", "A", "s1", "m", 0), None, id="riesgo18-completo"),
    pytest.param(EventoViejo("entrada", "A", "m"), "strategy_id", id="riesgo18-sin-strategy_id"),
    pytest.param(EventoFalso("entrada", "A", "s1", None, 0), "momento", id="riesgo18-momento-None"),
    pytest.param(object(), "tipo", id="riesgo18-objeto-ajeno"),
])
def test_campo_ausente(ev, falta):
    assert fs.campo_ausente(ev) == falta


def test_vela_de_grabacion_igual_que_vela_de_mensaje_del_feed():
    """R-A-06: la réplica de `bot_alerts_feed.vela_de_mensaje` (l.177-187) da la MISMA vela, cruda o ya convertida."""
    import pandas as pd
    from app.services.bot_alerts_feed import vela_de_mensaje

    s_ms = int(pd.Timestamp("2026-09-25 09:31", tz="America/New_York").timestamp() * 1000)
    crudo = {"ev": "AM", "sym": "ABCD", "s": s_ms, "e": s_ms + 60_000, "o": 1.1, "h": 1.3, "l": 1.0,
             "c": 1.2, "v": 5000, "_r": s_ms + 61_500}
    s_leido, ticker, vela = fs.vela_de_grabacion(crudo)
    assert (s_leido, ticker) == (s_ms, "ABCD")
    assert vela == vela_de_mensaje(crudo)
    assert vela["timestamp"] == pd.Timestamp("2026-09-25 09:31")        # naive ET, INICIO del minuto
    convertida = {"timestamp": "2026-09-25 09:31:00", "open": 1.1, "high": 1.3, "low": 1.0, "close": 1.2,
                  "volume": 5000.0, "_r": s_ms + 61_500, "sym": "ABCD"}
    assert fs.vela_de_grabacion(convertida) == (s_ms, "ABCD", vela)
    assert fs.vela_de_grabacion({"sym": "ABCD", "s": s_ms, "o": 1, "h": 1, "l": 1}) is None
    assert fs.vela_de_grabacion({"s": s_ms, "o": 1, "h": 1, "l": 1, "c": 1}) is None
    sin_volumen = fs.vela_de_grabacion(dict(crudo, v=None))
    assert sin_volumen is not None and sin_volumen[2]["volume"] == 0.0


# ═══ 2. FuenteEnProceso: paridad con RunnerAlertas (R-A-05, R-A-06) ═════
def test_fuente_en_proceso_paridad_con_runner_directo(motor_falso):
    import pandas as pd
    from app.services.bot_alerts_cliente import id_evento
    from app.services.bot_alerts_runner import RunnerAlertas

    motor_falso["entradas_en"] = {9, 14, 22}
    velas = _velas(30)
    reloj = RelojSimulado(datetime(2026, 9, 25, 4, 10, 5, tzinfo=ET))     # la vela de 04:09 acaba de cerrar
    rec = Recolector()
    fuente = fs.FuenteEnProceso([_estrategia()], rec, reloj, al_aviso=rec.al_aviso)
    directo = RunnerAlertas([_estrategia()], al_avisar=None)
    stats = {"prev_close": 0.8}

    fuente.arrancar()
    fuente.hidratar("ABCD", velas[:10], stats)
    esperados = list(directo.hidratar("ABCD", pd.DataFrame(velas[:10]), stats,
                                      ahora=pd.Timestamp("2026-09-25 04:10:05")))
    assert [s.clase for s in rec.senales][:1] == ["hidratado"]
    assert rec.senales[0].feed == {"n_velas": 10, "prev_close": 0.8}
    for i, v in enumerate(velas[10:], start=10):
        reloj.fijar(datetime(2026, 9, 25, 4, 0, tzinfo=ET) + timedelta(minutes=i + 1, seconds=2))
        vela = dict(v, timestamp=pd.Timestamp(v["timestamp"]))
        antes = len(rec.senales)
        fuente.vela("ABCD", vela)
        nuevos = directo.nueva_vela("ABCD", dict(vela))
        esperados.extend(nuevos)
        for s in rec.senales[antes:]:
            assert s.recibida_en == reloj.mono()

    senales = rec.de_clase("evento")
    assert len(esperados) >= 3, "el motor falso debía dar al menos las tres entradas"
    assert [dataclasses.asdict(s.evento) for s in senales] == [dataclasses.asdict(e) for e in esperados]
    for s, e in zip(senales, esperados):
        assert s.id == id_evento(e)
        assert s.ticker == e.ticker and s.momento == e.momento
        assert s.origen == "proceso" and s.recuperada is False
    assert fuente.salud()["viva"] is True and fuente.salud()["origen"] == "proceso"
    assert fuente.salud()["ultimo_en"] == reloj.epoch()
    fuente.parar()
    assert fuente.salud()["viva"] is False
    assert rec.avisos == []


def test_fuente_en_proceso_hidratar_ultima_vela_es_presente(motor_falso):
    """Memoria ELMT (14-sep): la entrada en la última vela completa al hidratar SE entrega; el corte sale del reloj inyectado."""
    motor_falso["entradas_en"] = {9}
    rec = Recolector()
    fuente = fs.FuenteEnProceso([_estrategia()], rec, RelojSimulado(datetime(2026, 9, 25, 4, 10, 7, tzinfo=ET)))
    fuente.hidratar("ELMT", _velas(10))
    assert [s.clase for s in rec.senales] == ["hidratado", "evento"]
    assert rec.senales[1].evento.tipo == "entrada"


def test_fuente_en_proceso_fallo_del_motor_no_propaga(motor_falso, monkeypatch):
    """H-5: una vela que revienta el motor se cuenta y se avisa UNA vez al día; la fuente sigue."""
    rec = Recolector()
    fuente = fs.FuenteEnProceso([_estrategia()], rec, RelojSimulado(INICIO_REPLAY), al_aviso=rec.al_aviso)

    def revienta(*a, **k):
        raise RuntimeError("motor roto")

    monkeypatch.setattr(fuente.runner, "nueva_vela", revienta)
    fuente.vela("ABCD", _velas(1)[0])
    fuente.vela("ABCD", _velas(1)[0])
    assert fuente.fallos_motor == 2
    assert len(rec.avisos) == 1 and rec.avisos[0][0] == Nivel.AVISO
    assert rec.senales == []


def test_fuente_destino_que_lanza_no_propaga(motor_falso):
    """Frontera de callback: si el destino lanza, se cuenta y se avisa; la fuente no revienta."""
    avisos: list = []

    def destino(_s):
        raise RuntimeError("cola rota")

    fuente = fs.FuenteEnProceso([_estrategia()], destino, RelojSimulado(INICIO_REPLAY),
                                al_aviso=lambda n, t: avisos.append((n, t)))
    fuente.radar("NADA", Decimal("1"))
    fuente.radar("NADA", Decimal("1"))
    assert fuente.fallos_destino == 2 and fuente.entregadas == 0
    assert len(avisos) == 1


def test_fuente_en_proceso_dia_nuevo_reinicia_runner(motor_falso):
    rec = Recolector()
    fuente = fs.FuenteEnProceso([_estrategia()], rec, RelojSimulado(datetime(2026, 9, 25, 4, 30, tzinfo=ET)))
    fuente.hidratar("ABCD", _velas(20))
    assert fuente.runner.tickers == ["ABCD"]
    fuente.dia_nuevo()
    assert fuente.runner.tickers == []
    assert rec.senales[-1].clase == "dia_nuevo" and rec.senales[-1].ticker is None


# ═══ 3. radar: strategy_id por nombre (corrección 6, riesgo 25) ═════════
def test_radar_anade_strategy_id_y_descarta_repetidos_una_vez_al_dia(motor_falso):
    estrategias = [_estrategia("s-1b-a", "1B"), _estrategia("s-1b-b", "1B"), _estrategia("s-2c", "2C")]
    reloj = RelojSimulado(datetime(2026, 9, 25, 4, 30, tzinfo=ET))
    rec = Recolector()
    fuente = fs.FuenteEnProceso(estrategias, rec, reloj, al_aviso=rec.al_aviso)
    fuente.hidratar("ABCD", _velas(20))
    rec.senales.clear()

    fuente.radar("ABCD", Decimal("1.23"))
    fuente.radar("ABCD", Decimal("1.25"))
    radar = rec.de_clase("radar")
    assert len(radar) == 2
    assert radar[0].precio_radar == Decimal("1.23") and isinstance(radar[0].precio_radar, Decimal)
    assert radar[0].ticker == "ABCD" and radar[0].id is None and radar[0].origen == "proceso"
    assert [f["strategy_id"] for f in radar[0].estimacion] == ["s-2c"]
    assert [f["nombre"] for f in radar[0].estimacion] == ["2C"]
    assert all("strategy_id" in f for s in radar for f in s.estimacion)
    avisos_1b = [a for a in rec.avisos if "1B" in a[1]]
    assert len(avisos_1b) == 1 and avisos_1b[0][0] == Nivel.AVISO     # una vez al día, nivel 2

    reloj.avanzar(24 * 3600)                                            # otro día → vuelve a avisar
    fuente.radar("ABCD", Decimal("1.30"))
    assert len([a for a in rec.avisos if "1B" in a[1]]) == 2


def test_radar_precio_float_se_convierte_una_vez_y_sin_velas_da_lista_vacia(motor_falso):
    rec = Recolector()
    fuente = fs.FuenteEnProceso([_estrategia()], rec, RelojSimulado(INICIO_REPLAY))
    fuente.radar("NADA", 2.5)
    assert rec.senales[-1].estimacion == [] and rec.senales[-1].precio_radar == Decimal("2.5")


# ═══ 4. FuenteTuberia + EnlaceEjecutor (§6.1) ═══════════════════════════
@pytest.mark.parametrize("clave", [
    pytest.param(None, id="riesgo19-authkey-None"), pytest.param(b"", id="riesgo19-authkey-vacia"),
    pytest.param("", id="riesgo19-authkey-texto-vacio"), pytest.param(123, id="riesgo19-authkey-no-bytes"),
])
def test_tuberia_sin_authkey_no_arranca(clave):
    with pytest.raises(ValueError):
        fs.FuenteTuberia(("127.0.0.1", 0), clave, Recolector(), Reloj(), HASH_BUENO, VERSION)


def test_tuberia_argumentos_invalidos():
    with pytest.raises(ValueError):
        fs.FuenteTuberia(("127.0.0.1", 70000), b"k", Recolector(), Reloj(), HASH_BUENO, VERSION)
    with pytest.raises(ValueError):
        fs.FuenteTuberia(("127.0.0.1", 0), b"k", Recolector(), Reloj(), HASH_BUENO, "ayer")
    with pytest.raises(ValueError):
        fs.FuenteTuberia(("127.0.0.1", 0), b"k", "no-callable", Reloj(), HASH_BUENO, VERSION)


def test_enlace_sin_authkey_ni_entorno_no_arranca():
    """Riesgo 19: BOT_DAS_AUTHKEY obligatoria (la fixture autouse la borra del entorno)."""
    with pytest.raises(ValueError):
        enl.EnlaceEjecutor(("127.0.0.1", 8765))
    with pytest.raises(ValueError):
        enl.EnlaceEjecutor(("127.0.0.1", 8765), authkey=b"")


def test_enlace_lee_el_entorno_en_la_llamada(monkeypatch):
    """§3.11: BOT_DAS_TUBERIA (defecto 127.0.0.1:8765) y BOT_DAS_AUTHKEY se leen en __init__, no al importar."""
    monkeypatch.setenv("BOT_DAS_AUTHKEY", "clave-local-de-test")
    enlace = enl.EnlaceEjecutor()
    assert enlace.direccion == ("127.0.0.1", 8765) and enlace._authkey == b"clave-local-de-test"
    assert enlace.tope == 2000 and enlace.reconectar_s == 5.0 and enlace.version == VERSION
    monkeypatch.setenv("BOT_DAS_TUBERIA", "127.0.0.1:9001")
    assert enl.EnlaceEjecutor().direccion == ("127.0.0.1", 9001)
    monkeypatch.setenv("BOT_DAS_TUBERIA", "basura")
    with pytest.raises(ValueError):
        enl.EnlaceEjecutor()


def test_enlace_encola_sin_bloquear_y_respeta_el_tope():
    """§6.1: los métodos vuelven al instante aunque no haya ejecutor; al tope se tira lo MÁS VIEJO y se cuenta.

    F-03: antes se probaba con cinco latidos; ahora un latido sustituye al
    pendiente, así que el tope se prueba con «eventos» (que no se sustituyen)
    y los latidos van en `test_F_03_*`.
    """
    enlace = enl.EnlaceEjecutor(_puerto_cerrado(), b"k", tope=3)        # sin arrancar: nada consume
    t0 = time.perf_counter()
    for i in range(5):
        enlace.eventos("ABCD", f"09:3{i}", None, [], False)
    assert time.perf_counter() - t0 < 0.5
    assert enlace.pendientes == 3 and enlace.perdidos == 2 and enlace.encolados == 5
    assert [m["minuto"] for m in enlace._cola] == ["09:32", "09:33", "09:34"]
    enlace.parar(vaciar_s=0.0)
    with pytest.raises(ValueError):
        enl.EnlaceEjecutor(_puerto_cerrado(), b"k", tope=0)


def test_enlace_sin_ejecutor_reintenta_y_conserva(enlaces):
    """§6.1: sin Listener el enlace cuenta intentos fallidos, no pierde lo encolado y sigue vivo."""
    enlace = enlaces(_puerto_cerrado(), reconectar_s=0.05)
    enlace.dia_nuevo()
    assert _esperar(lambda: enlace.intentos_fallidos >= 2, segundos=15.0)
    salud = enlace.salud()
    assert salud["viva"] is True and salud["conectado"] is False and salud["pendientes"] == 1


def test_tuberia_mensajes_de_todos_los_tipos_en_proceso(tuberia, enlaces, motor_falso):
    """Los seis mensajes de §3.11 con un `Evento` REAL (momento pd.Timestamp) y el id de R-A-05; viaja como primitivos (F-01)."""
    import pandas as pd
    from app.services.bot_alerts_cliente import id_evento
    from app.services.bot_alerts_engine import Evento

    fuente, rec = tuberia()
    enlace = enlaces(fuente.direccion)
    assert _esperar(lambda: enlace.conectado)
    ev = Evento(tipo="entrada", ticker="ABCD", strategy_id="s1", estrategia="1B",
                momento=pd.Timestamp("2026-09-25 09:31"), precio=1.23, direccion="Short", acciones=100.0,
                stop=1.30)
    mapa, repetidos = enl.mapa_nombres([_estrategia("s1", "1B"), _estrategia("s2", "2C"), _estrategia("s3", "2C")])
    enlace.hidratado("ABCD", 42, [ev], 0.99)
    enlace.eventos("ABCD", "09:31", pd.Timestamp("2026-09-25 09:31"), [ev], True)
    enlace.radar([{"ticker": "ABCD", "precio": 1.25, "estimacion": [{"nombre": "1B", "acciones": 10},
                                                                     {"nombre": "2C", "acciones": 5}]},
                  "no-dict"], mapa, repetidos)
    enlace.latido(1790323321.5, True)
    enlace.dia_nuevo()
    assert _esperar(lambda: len(rec.senales) >= 6)
    clases = [s.clase for s in rec.senales]
    assert clases == ["hidratado", "evento", "evento", "radar", "latido_feed", "dia_nuevo"]
    hid, ev1, ev2, radar, latido, _dia = rec.senales
    assert hid.ticker == "ABCD" and hid.feed == {"n_velas": 42, "prev_close": 0.99}
    # F-01: llega como EventoLigero con los mismos campos y `momento` en texto (antes: el Evento tal cual)
    assert type(ev1.evento) is fs.EventoLigero
    ligero = dataclasses.asdict(ev1.evento)
    assert ligero.pop("extra") == {}
    assert ligero == {**dataclasses.asdict(ev), "momento": "2026-09-25 09:31:00"}
    assert ev1.id == ev2.id == id_evento(ev) and ev1.momento == "2026-09-25 09:31:00"
    assert ev1.recuperada is False and ev2.recuperada is True and ev2.origen == "tuberia"
    assert radar.precio_radar == Decimal("1.25")
    assert radar.estimacion == [{"nombre": "1B", "acciones": 10, "strategy_id": "s1"}]
    assert latido.feed == {"ultima_vela_en": 1790323321.5, "vivo": True}
    assert fuente.descartados == 1                                    # la fila 2C (ambigua) sin strategy_id
    assert len([a for a in rec.avisos if "2C" in a[1]]) == 1
    salud = fuente.salud()
    assert salud["viva"] is True and salud["origen"] == "tuberia" and salud["conectado"] is True
    assert salud["ultimo_en"] is not None and abs(salud["ultimo_en"] - time.time()) < 60
    assert salud["cliente_version"] == VERSION


def test_tuberia_evento_de_otra_version_descartado(tuberia, enlaces):
    """Riesgo 18: un Evento sin strategy_id se descarta con aviso 2 (una vez al día) y los buenos pasan."""
    fuente, rec = tuberia()
    enlace = enlaces(fuente.direccion)
    buenos = [EventoFalso("entrada", "ABCD", "s1", f"m{i}", i) for i in range(2)]
    for _ in range(3):
        enlace.eventos("ABCD", "09:31", None, [EventoViejo("entrada", "ABCD", "m"), *buenos], False)
    assert _esperar(lambda: fuente.recibidos >= 3)
    assert len(rec.de_clase("evento")) == 6 and fuente.descartados == 3
    avisos = [a for a in rec.avisos if "riesgo 18" in a[1]]
    assert len(avisos) == 1 and avisos[0][0] == Nivel.AVISO


def test_tuberia_mensajes_raros_no_tumban_el_hilo(tuberia):
    """Frontera de mensaje: no-dict, tipo desconocido y dict roto se cuentan; el hilo sigue sirviendo."""
    fuente, rec = tuberia()
    conn = Client(fuente.direccion, authkey=b"clave-de-test")
    try:
        conn.send({"t": "hola", "version": VERSION, "motor_hash": HASH_BUENO})
        assert conn.poll(5) and conn.recv()["t"] == "ok"
        conn.send(["no", "soy", "un", "dict"])
        conn.send({"t": "desconocido"})
        conn.send({"t": "hidratado", "ticker": None})
        conn.send({"t": "radar", "candidatos": [{"ticker": "", "precio": 1}, {"ticker": "X", "precio": "nan"}]})
        conn.send({"t": "hola", "version": VERSION, "motor_hash": HASH_BUENO})
        conn.send({"t": "dia_nuevo"})
        assert _esperar(lambda: len(rec.de_clase("dia_nuevo")) == 1)
    finally:
        conn.close()
    assert fuente.malformados == 2 and fuente.desconocidos == 2 and fuente.descartados == 2
    assert fuente.salud()["viva"] is True


def test_tuberia_primer_mensaje_no_hola_se_rechaza(tuberia):
    fuente, rec = tuberia()
    conn = Client(fuente.direccion, authkey=b"clave-de-test")
    try:
        conn.send({"t": "eventos", "eventos": []})
        assert conn.poll(5) and conn.recv()["t"] == "rechazado"
    finally:
        conn.close()
    assert _esperar(lambda: fuente.saludos_fallidos == 1)
    assert rec.senales == []


def test_tuberia_clave_incorrecta_se_rechaza(tuberia, enlaces):
    """Riesgo 19: un cliente con otra clave no llega a saludar; la fuente sigue aceptando al bueno."""
    fuente, rec = tuberia()
    malo = enlaces(fuente.direccion, authkey=b"otra-clave")
    assert _esperar(lambda: fuente.autenticaciones_fallidas >= 1)
    assert malo.conectado is False and malo.intentos_fallidos >= 1
    malo.parar(vaciar_s=0.0)
    bueno = enlaces(fuente.direccion)
    bueno.dia_nuevo()
    assert _esperar(lambda: len(rec.de_clase("dia_nuevo")) == 1)
    assert len([a for a in rec.avisos if "clave incorrecta" in a[1]]) == 1


def test_tuberia_parar_es_idempotente_y_salud_refleja(tuberia):
    fuente, _ = tuberia()
    assert fuente.salud()["viva"] is True
    fuente.parar()
    fuente.parar()
    assert fuente.salud()["viva"] is False


def test_dos_procesos_5000_mensajes_sin_perdida_ni_desorden(tuberia):
    """§10: 5.000 mensajes de un proceso a otro, completos y en orden, con authkey."""
    n = 5000
    clave = _clave()
    fuente, rec = tuberia(authkey=clave)
    _ctx, cola, hacer = _proceso(_hijo_eventos, fuente.direccion, clave, n, HASH_BUENO)
    p = hacer()
    try:
        p.start()
        assert _esperar(lambda: len(rec.senales) >= n, segundos=ESPERA_MAX_S), \
            f"llegaron {len(rec.senales)} de {n}"
        salud_hijo = cola.get(timeout=ESPERA_MAX_S)
    finally:
        _cerrar_proceso(p)
    assert [s.evento.seq for s in rec.senales] == list(range(n))
    assert len({s.id for s in rec.senales}) == n
    assert all(s.clase == "evento" and s.origen == "tuberia" for s in rec.senales)
    assert salud_hijo["enviados"] == n and salud_hijo["perdidos"] == 0 and salud_hijo["conexiones"] == 1
    assert fuente.descartados == 0 and fuente.malformados == 0


def test_dos_procesos_reconexion_tras_matar_y_relanzar_el_listener(tuberia):
    """§6.1: el Listener muere, vuelve en la misma dirección y el enlace reconecta solo; orden intacto."""
    clave = _clave()
    rec1 = Recolector()
    fuente1, _ = tuberia(authkey=clave, rec=rec1)
    direccion = fuente1.direccion
    ctx, cola, _hacer = _proceso(_hijo_latidos)
    parar_ev = ctx.Event()
    p = ctx.Process(target=_hijo_latidos, args=(direccion, clave, parar_ev, cola), daemon=True)
    try:
        p.start()
        assert _esperar(lambda: len(rec1.senales) >= 20), "el primer Listener no recibió latidos"
        fuente1.parar()
        n1 = len(rec1.senales)
        rec2 = Recolector()
        fuente2 = None
        fin = time.monotonic() + 5.0
        while fuente2 is None:
            try:
                fuente2, _ = tuberia(direccion=direccion, authkey=clave, rec=rec2)
            except OSError:
                if time.monotonic() > fin:
                    raise
                time.sleep(0.1)
        assert _esperar(lambda: len(rec2.senales) >= 20), "el enlace no reconectó con el Listener nuevo"
        parar_ev.set()
        salud_hijo = cola.get(timeout=ESPERA_MAX_S)
    finally:
        parar_ev.set()
        _cerrar_proceso(p)
    assert len(rec1.senales) == n1                                     # el muerto no recibe nada más
    v1 = [s.feed["ultima_vela_en"] for s in rec1.senales]
    v2 = [s.feed["ultima_vela_en"] for s in rec2.senales]
    assert v1 == sorted(set(v1)) and v2 == sorted(set(v2))             # sin desorden ni duplicados dentro de cada conexión
    assert v2[0] >= v1[-1]
    assert fuente2.conexiones == 1
    assert salud_hijo["conexiones"] == 2 and salud_hijo["desconexiones"] >= 1


def test_dos_procesos_hola_con_hash_distinto_se_rechaza(tuberia):
    """H-6: el ejecutor se niega a un bot.py con otro motor; aviso 3 UNA vez aunque reintente; no entra nada."""
    clave = _clave()
    fuente, rec = tuberia(authkey=clave)
    _ctx, cola, hacer = _proceso(_hijo_hash_viejo, fuente.direccion, clave, 15.0)
    p = hacer()
    try:
        p.start()
        salud_hijo = cola.get(timeout=ESPERA_MAX_S)
    finally:
        _cerrar_proceso(p)
    assert rec.senales == []
    assert fuente.rechazados >= 3
    maximos = [a for a in rec.avisos if a[0] == Nivel.MAXIMO]
    assert len(maximos) == 1 and "RECHAZADO" in maximos[0][1]
    assert salud_hijo["rechazos"] >= 3 and salud_hijo["enviados"] == 0
    assert salud_hijo["pendientes"] == 3 and "hash" in (salud_hijo["motivo_rechazo"] or "")


# ═══ 5. FuenteGrabacion + Guion (R-O-02, injerto A §8.24) ═══════════════
def test_am_recorte_es_la_fixture_pedida():
    """3 tickers × 40 velas consecutivas, claves de grabador.py, un solo miembro gzip."""
    import zlib
    datos = RUTA_AM.read_bytes()
    d = zlib.decompressobj(31)
    d.decompress(datos)
    assert d.eof and d.unused_data == b""
    por_ticker: dict[str, list[str]] = {}
    with gzip.open(RUTA_AM, "rt", encoding="utf-8") as f:
        for linea in f:
            m = json.loads(linea)
            assert set(m) == {"timestamp", "open", "high", "low", "close", "volume", "_r", "sym"}
            por_ticker.setdefault(m["sym"], []).append(m["timestamp"])
    assert len(por_ticker) == 3 and all(len(v) == 40 for v in por_ticker.values())
    for ts in por_ticker.values():
        minutos = [datetime.fromisoformat(t) for t in ts]
        assert all(b - a == timedelta(minutes=1) for a, b in zip(minutos, minutos[1:]))


def test_guion_carga_la_fixture_y_valida():
    guion = fs.Guion.cargar(RUTA_GUION)
    assert guion.spread.pct == Decimal("0.5") and isinstance(guion.spread.pct, Decimal)
    assert (guion.spread.minimo_ticks, guion.spread.tamano_bid, guion.spread.tamano_ask) == (1, 500, 500)
    assert len(guion.halts) == 1 and len(guion.rechazos) == 1 and len(guion.fills_parciales) == 1
    assert fs.Guion.desde_dict({}) == fs.Guion()
    for malo in ({"halts": {}}, {"rechazos": [1]}, {"spread": {"pct": "nan"}}, {"spread": {"pct": -1}},
                 {"spread": {"tamano_bid": 0}}, {"spread": {"minimo_ticks": 1.5}}, []):
        with pytest.raises(ValueError):
            fs.Guion.desde_dict(malo)


def test_guion_construye_el_modelo_spread_del_simulador():
    sim = pytest.importorskip("app.bot_das.simulador_das")
    modelo = fs.Guion.cargar(RUTA_GUION).spread.como(sim.ModeloSpread)
    assert isinstance(modelo, sim.ModeloSpread) and modelo.pct == Decimal("0.5")


def test_fuente_grabacion_reproduce_en_orden_y_avanza_el_reloj(motor_falso):
    motor_falso["entradas_en"] = {5}
    reloj = RelojSimulado(INICIO_REPLAY)
    rec = Recolector()
    guion = fs.Guion.cargar(RUTA_GUION)
    fuente = fs.FuenteGrabacion(RUTA_AM, [_estrategia()], rec, reloj, guion=guion, al_aviso=rec.al_aviso)
    pasos: list[tuple[datetime, str, float, float]] = []
    mono_inicial = reloj.mono()

    def paso(t, vela):
        assert reloj.ahora() == t                                     # el reloj ya está en el cierre
        assert t - timedelta(seconds=60) == vela["timestamp"].to_pydatetime().replace(tzinfo=ET)
        pasos.append((t, vela["ticker"], reloj.mono(), vela["close"]))

    fuente.arrancar()
    assert fuente.salud()["pendientes"] == 120
    aplicadas = fuente.reproducir(paso=paso)
    assert aplicadas == 120 and fuente.pendientes == 0
    tiempos = [p[0] for p in pasos]
    assert tiempos == sorted(tiempos)
    monos = [p[2] for p in pasos]
    assert monos == sorted(monos) and monos[-1] > mono_inicial
    assert reloj.ahora() == tiempos[-1] == datetime(2026, 9, 25, 7, 41, tzinfo=ET)
    assert {p[1] for p in pasos} == {"INLF", "CTNT", "MGLD"}
    assert len(rec.de_clase("hidratado")) == 3
    eventos = rec.de_clase("evento")
    assert eventos and all(s.origen == "grabacion" for s in eventos)
    assert fuente.salud()["aplicadas"] == 120 and fuente.salud()["lineas_malas"] == 0
    assert fuente.reproducir() == 0


def test_fuente_grabacion_hasta_filtro_y_reanudar(motor_falso):
    reloj = RelojSimulado(INICIO_REPLAY)
    rec = Recolector()
    fuente = fs.FuenteGrabacion(RUTA_AM, [_estrategia()], rec, reloj, tickers={"INLF"})
    assert fuente.reproducir(hasta=datetime(2026, 9, 25, 4, 11)) == 10     # cierres 04:02 … 04:11 (naive = ET)
    assert reloj.ahora() == datetime(2026, 9, 25, 4, 11, tzinfo=ET)
    assert fuente.reproducir() == 30
    assert fuente.salud()["lineas_filtradas"] == 80
    assert fuente.runner.tickers == ["INLF"]


def test_fuente_grabacion_hidrata_con_corte_en_la_primera_vela(motor_falso, tmp_path):
    """Memoria ELMT: el pasado de `hidratar_desde` hasta el minuto anterior se sella; lo solapado no se duplica."""
    import pandas as pd
    lineas = []
    for i in range(3):
        ts = pd.Timestamp("2026-09-25 04:10") + pd.Timedelta(minutes=i)
        lineas.append(json.dumps({"timestamp": str(ts), "open": 1.0, "high": 1.1, "low": 0.9, "close": 1.0,
                                  "volume": 1000.0, "_r": 0, "sym": "ABCD"}))
    ruta = tmp_path / "AM_2026-09-25.jsonl.gz"
    with open(ruta, "wb") as f:                                        # dos miembros gzip, como grabador.py
        f.write(gzip.compress(("\n".join(lineas[:2]) + "\n").encode()))
        f.write(gzip.compress((lineas[2] + "\n{roto\n").encode()))
    pasado = _velas(12, base="2026-09-25 03:59:00")                    # 03:59 … 04:10 (la de 04:10 solapa)
    rec = Recolector()
    fuente = fs.FuenteGrabacion(ruta, [_estrategia()], rec, RelojSimulado(INICIO_REPLAY),
                                hidratar_desde=lambda tk: (pasado, {"prev_close": 0.5}))
    assert fuente.reproducir() == 3
    assert fuente.salud()["lineas_malas"] == 1
    assert rec.de_clase("hidratado")[0].feed == {"n_velas": 12, "prev_close": 0.5}
    velas = [str(pd.Timestamp(v["timestamp"]))[:16] for v in fuente.runner._velas["ABCD"]]
    assert velas == sorted(set(velas)) and len(velas) == 11 + 3


def test_fuente_grabacion_exige_reloj_simulado_y_guion(motor_falso):
    with pytest.raises(ValueError):
        fs.FuenteGrabacion(RUTA_AM, [_estrategia()], Recolector(), Reloj())
    with pytest.raises(ValueError):
        fs.FuenteGrabacion(RUTA_AM, [_estrategia()], Recolector(), RelojSimulado(INICIO_REPLAY), guion={"spread": {}})


def test_las_fuentes_cumplen_el_protocolo(motor_falso):
    fuente = fs.FuenteEnProceso([_estrategia()], Recolector(), RelojSimulado(INICIO_REPLAY))
    assert isinstance(fuente, fs.FuenteSenales)
    assert set(fuente.salud()) >= {"viva", "ultimo_en", "origen"}
    assert isinstance(fs.FuenteTuberia(("127.0.0.1", 0), b"k", Recolector(), Reloj(), HASH_BUENO, VERSION),
                      fs.FuenteSenales)


# ═══ 6. arreglos de la revisión (F-01…F-05, D2-06) ══════════════════════
_HIJO_TUBERIA_LIMPIA = """
import json, sys, time
from app.bot_das import VERSION
from app.bot_das import fuente_senales as fs
from app.bot_das.reloj import Reloj
clave, esperados, motor_hash = bytes.fromhex(sys.argv[1]), int(sys.argv[2]), sys.argv[3]
senales = []
f = fs.FuenteTuberia(("127.0.0.1", 0), clave, senales.append, Reloj(), motor_hash, VERSION)
f.arrancar()
antes = sorted(m for m in ("pandas", "numpy") if m in sys.modules)
print(json.dumps(list(f.direccion)), flush=True)
fin = time.monotonic() + 30
while len([s for s in senales if s.clase == "evento"]) < esperados and time.monotonic() < fin:
    time.sleep(0.02)
ev = [s for s in senales if s.clase == "evento"]
mods = sorted(m for m in ("pandas", "numpy", "httpx", "websockets", "app.services.bot_alerts_engine",
                          "app.services.bot_alerts_cliente", "app.services.bot_alerts_runner") if m in sys.modules)
print(json.dumps({"antes": antes, "mods": mods, "ids": [s.id for s in ev], "momentos": [s.momento for s in ev],
                  "clases": sorted({type(s.evento).__name__ for s in ev}),
                  "precios": sorted({type(s.evento.precio).__name__ for s in ev}),
                  "malformados": f.malformados}), flush=True)
f.parar()
"""


def _eventos_reales():
    """Tres `Evento` REALES del motor con tipos de pandas/numpy dentro (lo que manda bot.py de verdad)."""
    np = pytest.importorskip("numpy")
    import pandas as pd
    from app.services.bot_alerts_engine import Evento
    e1 = Evento(tipo="entrada", ticker="ABCD", strategy_id="s1", estrategia="1B",
                momento=pd.Timestamp("2026-09-25 09:31"), precio=np.float64(1.23), direccion="Short",
                acciones=np.float64(100.0), stop=np.float64(1.30), entrada_idx=np.int64(7))
    e2 = Evento(tipo="salida", ticker="ABCD", strategy_id="s2", estrategia="2C",
                momento=pd.Timestamp("2026-09-25 09:32:00.500"), precio=1.10, direccion="Short",
                acciones=50.0, motivo="TP", cuenta="B")
    e3 = Evento(tipo="entrada", ticker="ABCD", strategy_id="s3", estrategia="3D",
                momento=pd.Timestamp("2026-09-25 09:32"), precio=1.11, direccion="Short", acciones=10.0)
    return e1, e2, e3


def test_F_01_evento_ligero_tiene_los_campos_de_evento():
    """F-01: `EventoLigero` replica los campos (y el defecto de `estado`) de `bot_alerts_engine.Evento`."""
    from app.services.bot_alerts_engine import Evento
    propios = {f.name: f for f in dataclasses.fields(fs.EventoLigero)}
    del propios["extra"]
    del propios["estado"]
    ajenos = {f.name for f in dataclasses.fields(Evento)}
    assert set(propios) | {"estado"} == ajenos
    assert fs.EventoLigero().estado == "alerta"
    ev = fs.EventoLigero.desde_dict({"tipo": "entrada", "estado": None, "seq": 4, "nuevo_campo": "x"})
    assert ev.estado == "alerta" and ev.seq == 4 and ev.nuevo_campo == "x"
    assert ev.extra == {"seq": 4, "nuevo_campo": "x"}
    with pytest.raises(AttributeError):
        _ = ev.no_existe
    assert fs.campo_ausente(fs.EventoLigero.desde_dict({"tipo": "entrada", "ticker": "A", "momento": "m"})) \
        == "strategy_id"


def test_F_01_id_de_evento_paridad_con_id_evento():
    """F-01 / R-A-05: la réplica local da el MISMO id que `bot_alerts_cliente.id_evento`, sobre Evento y sobre EventoLigero."""
    from app.services.bot_alerts_cliente import id_evento
    for ev in _eventos_reales():
        ligero = fs.EventoLigero.desde_dict(enl.a_primitivo(ev))
        assert fs.id_de_evento(ev) == id_evento(ev) == fs.id_de_evento(ligero) == id_evento(ligero)
    assert id_evento(_eventos_reales()[1]).endswith("|B")                  # con cuenta
    falso = EventoFalso("entrada", "X", "s", "2026-09-25 09:30:00.123456", 0)
    assert fs.id_de_evento(falso) == id_evento(falso)


def test_F_01_a_primitivo_no_deja_tipos_de_pandas_ni_numpy():
    """F-01: el mensaje que sale del enlace solo lleva primitivos; `momento` en texto «AAAA-MM-DD HH:MM:SS»."""
    import pickle
    import pandas as pd
    e1, e2, _ = _eventos_reales()
    msg = {"t": "eventos", "ticker": "ABCD", "minuto": "09:31", "timestamp": pd.Timestamp("2026-09-25 09:31"),
           "eventos": [e1, e2], "recuperada": False, "precio": Decimal("1.5"), "tupla": (1, 2)}
    prim = enl.a_primitivo(msg)
    assert prim["timestamp"] == "2026-09-25 09:31:00" and prim["tupla"] == [1, 2]
    assert prim["precio"] == Decimal("1.5")
    d1, d2 = prim["eventos"]
    assert d1["momento"] == "2026-09-25 09:31:00" and d2["momento"] == "2026-09-25 09:32:00"
    assert type(d1["precio"]) is float and type(d1["acciones"]) is float and type(d1["entrada_idx"]) is int
    assert d2["cuenta"] == "B"

    def tipos(x):
        if isinstance(x, dict):
            return set().union(*(tipos(v) for v in x.values())) | {type(k) for k in x}
        if isinstance(x, list):
            return set().union(set(), *(tipos(v) for v in x))
        return {type(x)}

    assert tipos(prim) <= {dict, list, str, int, float, bool, type(None), Decimal}
    datos = pickle.dumps(prim)
    assert fs._DespickladorPrimitivos(__import__("io").BytesIO(datos)).load() == prim
    with pytest.raises(pickle.UnpicklingError):
        fs._DespickladorPrimitivos(__import__("io").BytesIO(pickle.dumps(e1))).load()


def test_F_01_tuberia_descarta_un_pickle_con_clases(tuberia):
    """F-01: un pickle que nombra una clase (un enlace viejo que manda el Evento tal cual) se descarta como ilegible."""
    fuente, rec = tuberia()
    conn = Client(fuente.direccion, authkey=b"clave-de-test")
    try:
        conn.send({"t": "hola", "version": VERSION, "motor_hash": HASH_BUENO})
        assert conn.poll(5) and conn.recv()["t"] == "ok"
        conn.send({"t": "eventos", "ticker": "ABCD", "eventos": [EventoFalso("entrada", "ABCD", "s1", "m", 0)]})
        conn.send({"t": "eventos", "ticker": "ABCD", "eventos": [{"tipo": "entrada", "ticker": "ABCD",
                                                                 "strategy_id": "s1", "momento": "m1"}]})
        assert _esperar(lambda: len(rec.de_clase("evento")) == 1)
    finally:
        conn.close()
    assert fuente.malformados == 1
    assert rec.de_clase("evento")[0].evento.momento == "m1"
    assert len([a for a in rec.avisos if "ilegible" in a[1]]) == 1


def test_F_01_ejecutor_limpio_no_carga_pandas_con_la_primera_senal(enlaces):
    """F-01 / riesgo 29: un proceso LIMPIO con FuenteTuberia recibe Evento reales (pd.Timestamp, np.float64) y no carga pandas, numpy ni httpx."""
    from app.services.bot_alerts_cliente import id_evento
    e1, e2, e3 = _eventos_reales()
    clave = _clave()
    with subprocess.Popen([sys.executable, "-c", _HIJO_TUBERIA_LIMPIA, clave.hex(), "3", HASH_BUENO],
                          cwd=str(BACKEND), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                          encoding="utf-8", env={**os.environ, "PYTHONPATH": str(BACKEND),
                                                 "PYTHONIOENCODING": "utf-8"}) as hijo:
        try:
            direccion = tuple(json.loads(hijo.stdout.readline()))
            enlace = enlaces(direccion, authkey=clave)
            enlace.hidratado("ABCD", 10, [e1], 0.99)
            enlace.eventos("ABCD", "09:32", e3.momento, [e3, e2], False)   # D2-06: la salida sale antes
            linea = hijo.stdout.readline()
            assert linea, hijo.stderr.read()
            informe = json.loads(linea)
        finally:
            try:
                hijo.wait(timeout=20)
            except subprocess.TimeoutExpired:
                hijo.kill()
                hijo.wait(timeout=5)
    assert informe["antes"] == []
    assert informe["mods"] == [], f"el ejecutor cargó {informe['mods']} con la primera señal"
    assert informe["ids"] == [id_evento(e1), id_evento(e2), id_evento(e3)]
    assert informe["momentos"] == ["2026-09-25 09:31:00", "2026-09-25 09:32:00", "2026-09-25 09:32:00"]
    assert informe["clases"] == ["EventoLigero"] and informe["precios"] == ["float"]
    assert informe["malformados"] == 0


def test_D2_06_tuberia_entrega_la_tanda_ordenada_por_prioridad(tuberia, enlaces):
    """D2-06 / R-D-07: [entrada B, pirámide add, pirámide lot_tp, salida A] → salida, lot_tp, add, entrada."""
    fuente, rec = tuberia()
    enlace = enlaces(fuente.direccion)
    tanda = [EventoFalso("entrada", "ABCD", "sB", "m", 0), EventoFalso("piramide", "ABCD", "sC", "m", 1),
             EventoFalso("piramide", "ABCD", "sD", "m", 2), EventoFalso("salida", "ABCD", "sA", "m", 3)]
    dicts = [dataclasses.asdict(e) for e in tanda]
    dicts[1]["accion_piramide"] = "add"
    dicts[2]["accion_piramide"] = "lot_tp"
    enlace.eventos("ABCD", "09:31", None, dicts, False)
    assert _esperar(lambda: len(rec.de_clase("evento")) == 4)
    assert [s.evento.seq for s in rec.de_clase("evento")] == [3, 2, 1, 0]


def test_D2_06_en_proceso_ordena_la_tanda_de_la_vela(motor_falso, monkeypatch):
    """D2-06: `FuenteEnProceso.vela` entrega el TP de A antes que la entrada de B aunque el motor los dé al revés."""
    rec = Recolector()
    fuente = fs.FuenteEnProceso([_estrategia()], rec, RelojSimulado(INICIO_REPLAY))
    tanda = [EventoFalso("entrada", "ABCD", "sB", "2026-09-25 04:00:00", 0),
             EventoFalso("salida", "ABCD", "sA", "2026-09-25 04:00:00", 1)]
    monkeypatch.setattr(fuente.runner, "nueva_vela", lambda *a, **k: list(tanda))
    fuente.vela("ABCD", _velas(1)[0])
    assert [s.evento.tipo for s in rec.de_clase("evento")] == ["salida", "entrada"]


def test_D2_06_si_ordenar_falla_la_tanda_sale_en_el_orden_del_motor(monkeypatch):
    """D2-06: un fallo en `salidas.prioridad` no pierde señales: se entregan en el orden del motor."""
    from app.bot_das.reglas import salidas

    def revienta(_s):
        raise RuntimeError("prioridad rota")

    monkeypatch.setattr(salidas, "prioridad", revienta)
    senales = [Senal(clase="evento", ticker="A", id=str(i), evento=EventoFalso(t, "A", "s", "m", i))
               for i, t in enumerate(("entrada", "salida"))]
    assert fs.ordenar_tanda(senales) == senales


def test_F_02_cliente_callado_no_deja_sorda_la_tuberia(tuberia, enlaces):
    """F-02: un socket local que conecta y no habla ya no bloquea el accept; el enlace legítimo entra en < 10 s."""
    fuente, rec = tuberia(espera_auth_s=1.0)
    callado = socket.create_connection(fuente.direccion, timeout=5)
    try:
        time.sleep(0.2)
        t0 = time.monotonic()
        bueno = enlaces(fuente.direccion)
        bueno.dia_nuevo()
        assert _esperar(lambda: len(rec.de_clase("dia_nuevo")) == 1, segundos=10.0)
        assert time.monotonic() - t0 < 10.0
    finally:
        callado.close()
    assert fuente.autenticaciones_caducadas >= 1 and fuente.salud()["autenticaciones_caducadas"] >= 1


def test_F_02_cliente_que_manda_medio_mensaje_se_corta(tuberia, enlaces):
    """F-02: medio mensaje y silencio → el `recv` sale por `SO_RCVTIMEO`; la tubería sigue aceptando."""
    fuente, rec = tuberia(espera_auth_s=1.0)
    raro = socket.create_connection(fuente.direccion, timeout=5)
    try:
        raro.recv(64)                                   # el reto HMAC que manda el Listener
        raro.sendall(b"\x00\x00\x00\x10\x01")           # cabecera de 16 bytes y solo uno de cuerpo
        bueno = enlaces(fuente.direccion)
        bueno.dia_nuevo()
        assert _esperar(lambda: len(rec.de_clase("dia_nuevo")) == 1, segundos=10.0)
    finally:
        raro.close()
    assert fuente.autenticaciones_caducadas >= 1


def test_F_02_clave_incorrecta_cierra_la_conexion(tuberia):
    """F-02: con un digest malo el servidor contesta FAILURE y CIERRA la conexión (antes quedaba abierta hasta el GC)."""
    from multiprocessing import connection as mpc
    fuente, rec = tuberia()
    conn = Client(fuente.direccion)                     # sin authkey: el saludo lo hace el test a mano
    try:
        reto = conn.recv_bytes(256)
        assert reto.startswith(mpc.CHALLENGE)
        conn.send_bytes(b"x" * 16)                      # digest incorrecto
        assert conn.recv_bytes(256) == mpc.FAILURE
        assert conn.poll(5)
        with pytest.raises((EOFError, OSError)):
            conn.recv_bytes()
    finally:
        conn.close()
    assert _esperar(lambda: fuente.autenticaciones_fallidas == 1)
    assert len([a for a in rec.avisos if "clave incorrecta" in a[1]]) == 1


def test_F_03_los_latidos_no_expulsan_eventos():
    """F-03: tope 3, dos «eventos» y diez latidos → quedan los 2 eventos y el ÚLTIMO latido; nada perdido."""
    enlace = enl.EnlaceEjecutor(_puerto_cerrado(), b"k", tope=3)
    enlace.eventos("ABCD", "09:30", None, [], False)
    for i in range(5):
        enlace.latido(float(i), True)
    enlace.eventos("ABCD", "09:31", None, [], False)
    for i in range(5, 10):
        enlace.latido(float(i), True)
    cola = list(enlace._cola)
    assert [m["t"] for m in cola] == ["eventos", "eventos", "latido"]
    assert cola[-1]["ultima_vela_en"] == 9.0
    assert enlace.perdidos == 0 and enlace.latidos_sustituidos == 9 and enlace.encolados == 12
    assert enlace.salud()["latidos_sustituidos"] == 9
    enlace.parar(vaciar_s=0.0)


def test_F_03_cola_llena_tira_antes_latidos_y_radar():
    """F-03: con la cola llena se sacrifica el radar/latido más viejo; un latido que no cabe se tira él."""
    enlace = enl.EnlaceEjecutor(_puerto_cerrado(), b"k", tope=3)
    enlace.eventos("ABCD", "09:30", None, [], False)
    enlace.radar([{"ticker": "ABCD", "precio": 1.0, "estimacion": []}], {})
    enlace.eventos("ABCD", "09:31", None, [], False)
    enlace.eventos("ABCD", "09:32", None, [], False)               # llena → fuera el radar, no el evento viejo
    assert [m.get("minuto") for m in enlace._cola] == ["09:30", "09:31", "09:32"] and enlace.perdidos == 1
    enlace.latido(1.0, True)                                        # llena de eventos → el latido no expulsa nada
    assert [m.get("minuto") for m in enlace._cola] == ["09:30", "09:31", "09:32"] and enlace.perdidos == 2
    enlace.dia_nuevo()                                              # sin desechables: se tira el más viejo
    assert [m["t"] for m in enlace._cola] == ["eventos", "eventos", "dia_nuevo"] and enlace.perdidos == 3
    enlace.parar(vaciar_s=0.0)


def test_F_03_devolver_no_repone_un_latido_viejo():
    """F-03: un latido que falló al enviarse no vuelve si ya hay otro más nuevo; un evento sí vuelve a la cabeza."""
    enlace = enl.EnlaceEjecutor(_puerto_cerrado(), b"k", tope=3)
    enlace.latido(2.0, True)
    enlace._devolver({"t": "latido", "ultima_vela_en": 1.0, "feed_vivo": True})
    assert [m["ultima_vela_en"] for m in enlace._cola] == [2.0]
    enlace._devolver({"t": "eventos", "minuto": "09:30"})
    assert [m["t"] for m in enlace._cola] == ["eventos", "latido"]
    enlace.eventos("ABCD", "09:31", None, [], False)
    enlace._devolver({"t": "eventos", "minuto": "09:29"})             # llena: se sacrifica el latido, no el evento
    assert [m.get("minuto") for m in enlace._cola] == ["09:29", "09:30", "09:31"]
    enlace.parar(vaciar_s=0.0)


def _velas_de_procesos():
    """`_velas` de tests/test_bot_alerts_procesos.py (la fila de §10 pide ESAS velas).

    Se extrae SOLO esa función del fichero (ast) en vez de importar el módulo
    entero, que arrastra los procesos del bot de alertas y sus marcas de pytest.
    """
    import ast
    fuente = (BACKEND / "tests" / "test_bot_alerts_procesos.py").read_text(encoding="utf-8")
    nodo = next(n for n in ast.parse(fuente).body if isinstance(n, ast.FunctionDef) and n.name == "_velas")
    espacio: dict = {}
    exec(compile(ast.Module(body=[nodo], type_ignores=[]), "test_bot_alerts_procesos.py", "exec"), espacio)
    return espacio["_velas"]


ESTRATEGIA_REAL = {
    "strategy_id": "real-1", "name": "Real mínima", "riesgo_usd": 300.0,
    "definition": {"bias": "short",
                   "entry_logic": {"root_condition": {"type": "group", "operator": "AND", "conditions": [
                       {"type": "indicator_comparison", "source": {"name": "Bar Close"},
                        "comparator": "GREATER_THAN", "target": 1.095}]}},
                   "exit_logic": {"root_condition": {"type": "group", "operator": "AND", "conditions": [
                       {"type": "indicator_comparison", "source": {"name": "Bar Close"},
                        "comparator": "GREATER_THAN", "target": 1.195}]}},
                   "risk_management": {"use_stop_loss": True, "stop_loss_mode": "Fixed", "fixed_stop_loss_pct": 50,
                                       "hard_stop": {"type": "Percentage", "value": 50}}},
    "ventana": {"inicio": "04:00", "fin": "16:00"},
}


def test_F_04_paridad_con_runner_directo_y_motor_real():
    """F-04 / R-A-06: SIN motor falso, con una estrategia real mínima y las velas de test_bot_alerts_procesos._velas."""
    import copy
    import pandas as pd
    from app.services.bot_alerts_cliente import id_evento
    from app.services.bot_alerts_runner import RunnerAlertas

    velas = _velas_de_procesos()(n=30)                                  # 09:30 … 09:59 del 23-sep, 1,00 → 1,29
    reloj = RelojSimulado(datetime(2026, 9, 23, 9, 35, 5, tzinfo=ET))    # la de 09:34 acaba de cerrar
    rec = Recolector()
    fuente = fs.FuenteEnProceso([copy.deepcopy(ESTRATEGIA_REAL)], rec, reloj, al_aviso=rec.al_aviso)
    directo = RunnerAlertas([copy.deepcopy(ESTRATEGIA_REAL)], al_avisar=None)
    stats = {"prev_close": 0.9}
    fuente.hidratar("AAA", velas[:5], stats)
    esperados = list(directo.hidratar("AAA", pd.DataFrame(velas[:5]), stats,
                                      ahora=pd.Timestamp("2026-09-23 09:35:05")))
    for i, v in enumerate(velas[5:], start=5):
        reloj.fijar(datetime(2026, 9, 23, 9, 30, tzinfo=ET) + timedelta(minutes=i + 1, seconds=2))
        vela = dict(v, timestamp=pd.Timestamp(v["timestamp"]))
        fuente.vela("AAA", vela)
        esperados.extend(directo.nueva_vela("AAA", dict(vela)))
    senales = rec.de_clase("evento")
    assert {e.tipo for e in esperados} == {"entrada", "salida"}, "la estrategia real debía entrar y salir"
    assert [dataclasses.asdict(s.evento) for s in senales] == [dataclasses.asdict(e) for e in esperados]
    assert [s.id for s in senales] == [id_evento(e) for e in esperados]
    assert fuente.fallos_motor == 0 and rec.avisos == []


@pytest.mark.skipif(sys.platform != "win32", reason="tubería con nombre de Windows")
def test_F_05_parar_despierta_una_tuberia_con_nombre(tuberia, enlaces):
    """F-05: con `\\\\.\\pipe\\…` el accept se despierta al parar (antes el hilo se abandonaba a los 5 s)."""
    nombre = "\\\\.\\pipe\\bot_das_test_" + os.urandom(6).hex()
    fuente, rec = tuberia(direccion=nombre)
    enlace = enlaces(nombre)
    enlace.dia_nuevo()
    assert _esperar(lambda: len(rec.de_clase("dia_nuevo")) == 1)
    enlace.parar(vaciar_s=0.0)
    time.sleep(0.3)                                                     # el hilo vuelve a quedarse en accept()
    t0 = time.monotonic()
    fuente.parar()
    assert time.monotonic() - t0 < 3.0
    assert fuente._hilo is not None and not fuente._hilo.vivo
    assert fuente.salud()["viva"] is False
