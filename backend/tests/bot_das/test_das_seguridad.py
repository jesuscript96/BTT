"""Tests de seguridad del paquete del bot de DAS (lote G2, §10 «test_das_seguridad», riesgos 10, 19, 20 y 29).

QUÉ PRUEBA.
  (1) Importar `app.bot_das.ejecutor` y CONSTRUIRLO con `BOT_DAS_FUENTE=tuberia`
      en un intérprete limpio no carga pandas, ni el runner del motor, ni
      websockets, ni arranca hilos (injerto §8.25, riesgo 29).
  (2) Con valores secretos INVENTADOS en el entorno (tokens de Telegram, clave
      de DAS, authkey, clave de Massive, SMTP), un replay corto de verdad
      (`FuenteGrabacion` con `AM_recorte`, simulador de DAS por socket, fase
      SOMBRA) en el que DAS devuelve líneas que llevan esos secretos: ni el log
      ni el diario ni la foto contienen NINGUNO (corrección 8, riesgo 20).
  (3) `MUTANTES` es exactamente la lista del manual y `es_mutante` caza todas
      sus variantes (mayúsculas, espacios, tabuladores, saltos, ALLROUTE); el
      cliente de solo lectura las prohíbe TODAS antes de encolar (R-O-03).
  (4) Ningún fichero del paquete contiene literales con forma de credencial
      (token de Telegram, `sk-…`, `AKIA…`) ni importa websockets.
  (5) Ningún módulo propio importa httpx (el paquete usa urllib).

POR QUÉ ASÍ. Estas son las garantías que no se ven en un test funcional: una
fuga de secretos o un import pesado no rompen nada hasta el día que importan.

LAS TRAMPAS.
  * Los secretos son textos INVENTADOS por el test (con forma de secreto para
    que los patrones de `redactar` también trabajen); nunca se lee el `.env`.
  * El subproceso de (1) se lanza con un entorno explícito (el del test, ya
    limpio por `entorno_limpio`, más valores inventados).
  * El replay de (2) usa el motor de alertas con el traductor sustituido
    (`motor_falso`): la grabación produce señales sin depender del motor real.
"""
from __future__ import annotations

import dataclasses
import json
import logging
import re
import subprocess
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest

from app.bot_das import avisos as mod_avisos
from app.bot_das import ejecutor as ej
from app.bot_das import protocolo
from app.bot_das.cliente import ClienteDAS, ClienteSombra, EnvioProhibido
from app.bot_das.reloj import ET, RelojSimulado
from app.bot_das.simulador_das import LibroSimulado, SimuladorDAS
from app.bot_das.tipos import Config, Fase, Ficha

BACKEND = Path(__file__).resolve().parents[2]
PAQUETE = BACKEND / "app" / "bot_das"
FIXTURES = Path(__file__).parent / "fixtures"
RUTA_AM = FIXTURES / "AM_recorte.jsonl.gz"
CUENTA = "CUENTA_PRUEBA"
USUARIO = "usuario_prueba"

# Valores INVENTADOS con forma de secreto (ninguno es real ni lo ha sido).
SECRETOS = {
    "TELEGRAM_BOT_TOKEN_A": "1111111:inventadoGrupoAparaTestsNoEsRealXXXXXXXX",
    "TELEGRAM_BOT_TOKEN_B": "2222222:inventadoGrupoBparaTestsNoEsRealYYYYYYYY",
    "DAS_CLAVE": "claveDASinventada-7c1e9",
    "BOT_DAS_AUTHKEY": "authkeyInventada-55aa01",
    "MASSIVE_BOT_API_KEY": "massiveInventada-0f0f0f0f",
    "SMTP_PASS": "smtpInventada-9b9b9b",
}


# ═══════════════════════════ (1) sin pandas en modo tubería ═══════════════
SONDA_IMPORTS = r"""
import json, sys, threading
from datetime import datetime
from pathlib import Path
backend = sys.argv[1]
sys.path.insert(0, backend)
from app.bot_das import config, ejecutor
from app.bot_das.reloj import ET, RelojSimulado
cfg = config.cargar(Path(sys.argv[2]), "CUENTA_PRUEBA")
e = ejecutor.construir_desde_env(cfg, RelojSimulado(datetime(2026, 9, 25, 9, 30, tzinfo=ET)), Path(backend))
print(json.dumps({
    "pandas": "pandas" in sys.modules,
    "runner": "app.services.bot_alerts_runner" in sys.modules,
    "websockets": "websockets" in sys.modules,
    "hilos": threading.active_count(),
    "fuente": type(e.fuente).__name__,
    "conectado": e.cliente.conectado,
}))
"""


def test_injerto_8_25_con_tuberia_el_ejecutor_no_importa_pandas(dir_bot: Path) -> None:
    """Injerto §8.25 / riesgo 29: importar y construir el ejecutor con BOT_DAS_FUENTE=tuberia no carga pandas ni el motor."""
    import os
    env = dict(os.environ)
    env.update({"BOT_DAS_DIR": str(dir_bot), "BOT_DAS_FUENTE": "tuberia", "BOT_DAS_AUTHKEY": SECRETOS["BOT_DAS_AUTHKEY"],
                "DAS_API_PORT": "50999", "DAS_USUARIO": USUARIO, "DAS_CLAVE": SECRETOS["DAS_CLAVE"],
                "DAS_CUENTA": CUENTA, "PYTHONIOENCODING": "utf-8"})
    resultado = subprocess.run([sys.executable, "-c", SONDA_IMPORTS, str(BACKEND), str(FIXTURES / "config_ejemplo.json")],
                               cwd=str(BACKEND), env=env, capture_output=True, text=True, timeout=60)
    assert resultado.returncode == 0, resultado.stderr[-3000:]
    datos = json.loads(resultado.stdout.strip().splitlines()[-1])
    assert datos == {"pandas": False, "runner": False, "websockets": False, "hilos": 1,
                     "fuente": "FuenteTuberia", "conectado": False}
    assert SECRETOS["DAS_CLAVE"] not in resultado.stdout + resultado.stderr


# ═══════════════════════════ (2) secretos: log y diario de un replay ══════
class CalendarioPrueba:
    def franja_de_mercado(self, ahora: datetime) -> str:
        minutos = ahora.hour * 60 + ahora.minute
        if 4 * 60 <= minutos < 9 * 60 + 30:
            return "premercado"
        if 9 * 60 + 30 <= minutos < 16 * 60:
            return "RTH"
        return "cerrado"

    def media_sesion(self, dia) -> None:
        return None


class ReferenciaFalsa:
    def ficha(self, ticker: str) -> Ficha:
        from datetime import date
        return Ficha(ticker=ticker, list_date=date(2020, 1, 1), sic_code="1234", tipo="CS",
                     market_cap=Decimal("100000000"), nombre="Prueba SA")

    def splits_de_hoy(self, dia) -> set:
        return set()


@pytest.fixture
def motor_falso(monkeypatch: pytest.MonkeyPatch) -> dict:
    """Motor de alertas con el traductor sustituido: entradas en los índices de `guion["entradas_en"]`."""
    np = pytest.importorskip("numpy")
    from app.services import bot_alerts_engine as eng

    guion: dict = {"entradas_en": {3, 7}}

    def falso_translate(frame, sdef, stats, compiled=None):
        n = len(frame)
        entradas = np.zeros(n, dtype=bool)
        for k in guion["entradas_en"]:
            if 0 <= k < n:
                entradas[k] = True
        return {"direction": "Short", "entries": entradas, "exits": np.zeros(n, dtype=bool),
                "accept_reentries": True, "max_reentries": -1}

    monkeypatch.setattr(eng, "translate_strategy", falso_translate)
    monkeypatch.setattr(eng, "simulate", lambda **kw: {"trades": []})
    monkeypatch.setattr(eng, "_kwargs_simulate", lambda *a, **k: {})
    monkeypatch.setattr(eng, "compile_strategy_def", lambda sdef: {})
    monkeypatch.setattr(eng, "calcular_acciones", lambda *a, **k: 100.0)
    return guion


def _lineas_con_secretos() -> list[str]:
    """Lo que DAS podría devolver con un secreto dentro (notas de un rechazo, un mensaje del bróker, basura)."""
    clave = SECRETOS["DAS_CLAVE"]
    token = SECRETOS["TELEGRAM_BOT_TOKEN_B"]
    return [
        "$INTMSG Send Time: 2026/09/25 04:05:00",
        "$INTMSG From: BROKER",
        "$INTMSG To: ALL",
        f"$INTMSG Title: aviso con {SECRETOS['MASSIVE_BOT_API_KEY']}",
        f"$INTMSG Msg: la clave es {clave}\tel token es {token}\tla authkey {SECRETOS['BOT_DAS_AUTHKEY']}",
        f"LINEA_RARA LOGIN {USUARIO} {clave} {CUENTA} 0 bot{token} {SECRETOS['SMTP_PASS']}",
    ]


def test_correccion8_ningun_secreto_en_el_log_ni_en_el_diario_de_un_replay(
        cfg: Config, dir_bot: Path, motor_falso: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    """Corrección 8 / riesgo 20 / R-Q-01: replay corto (grabación + DAS simulado por socket) con secretos inventados en el
    entorno y en las líneas de DAS: el log, el diario y la foto no contienen NINGUNO de sus valores."""
    reloj = RelojSimulado(datetime(2026, 9, 25, 3, 55, tzinfo=ET))
    libro = LibroSimulado()
    simulador = SimuladorDAS(libro, reloj)
    host, puerto = simulador.arrancar()
    for nombre, valor in SECRETOS.items():
        monkeypatch.setenv(nombre, valor)
    for nombre, valor in {"DAS_API_HOST": host, "DAS_API_PORT": str(puerto), "DAS_USUARIO": USUARIO,
                          "DAS_CUENTA": CUENTA, "BOT_DAS_FUENTE": f"grabacion={RUTA_AM}"}.items():
        monkeypatch.setenv(nombre, valor)
    mod_avisos.instalar_logging("ejecutor", dir_bot / "logs", mod_avisos.secretos_desde_env(), nivel=logging.DEBUG,
                                consola=False, reloj=reloj)
    inyectado = {"hecho": False}

    def paso_replay(t: datetime, vela: dict) -> None:
        if not inyectado["hecho"]:
            inyectado["hecho"] = True
            for linea in _lineas_con_secretos():
                simulador.emitir(linea)

    e = None
    try:
        config = dataclasses.replace(cfg, fase=Fase.SOMBRA)
        e = ej.construir_desde_env(config, reloj, BACKEND, referencia=ReferenciaFalsa(), calendario=CalendarioPrueba(),
                                   hash_motor=lambda base: config.motor_hash, medir_desvio=lambda: 0.0, canales=[],
                                   paso_replay=paso_replay)
        assert isinstance(e.cliente, ClienteSombra)
        assert e.arrancar() == ej.CODIGO_OK
        logging.getLogger("btt.bot_das.prueba").warning("secreto directo al log: %s", SECRETOS["DAS_CLAVE"])
        assert e.correr() == ej.CODIGO_OK                              # la grabación se agota → fin (R-O-02)
    finally:
        if e is not None:
            e.parar()
        mod_avisos.desinstalar_logging()
        simulador.parar()
    assert inyectado["hecho"]
    assert f"LOGIN {USUARIO} {SECRETOS['DAS_CLAVE']} {CUENTA} 0" in simulador.recibidas()   # el secreto SÍ se usó
    ficheros = [p for sub in ("logs", "diario", "estado") for p in (dir_bot / sub).rglob("*") if p.is_file()]
    textos = {p.name: p.read_text(encoding="utf-8", errors="replace") for p in ficheros}
    assert any(n.startswith("bot_das_ejecutor") for n in textos) and any(n.startswith("diario_ejecutor") for n in textos)
    for nombre, valor in SECRETOS.items():
        for fichero, texto in textos.items():
            assert valor not in texto, f"{nombre} aparece en {fichero}"
    diario = next(t for n, t in textos.items() if n.startswith("diario_ejecutor"))
    registros = [json.loads(linea) for linea in diario.splitlines() if linea.strip()]
    tipos = {r["tipo"] for r in registros}
    assert {"intmsg", "das_desconocido", "fin_grabacion"} <= tipos      # las líneas con secretos SÍ se registraron
    assert mod_avisos.MASCARA in json.dumps([r for r in registros if r["tipo"] in ("intmsg", "das_desconocido")])
    log = next(t for n, t in textos.items() if n.startswith("bot_das_ejecutor"))
    assert "secreto directo al log" in log and mod_avisos.MASCARA in log
    # F11 b: la grabación NO manda latidos; el feed solo puede «volver» con el latido que el ejecutor saca de la fuente
    assert [r for r in registros if r["tipo"] == "feed" and r["datos"].get("nivel") == "ok"]


# ═══════════════════════════ (3) mutantes ═════════════════════════════════
MUTANTES_MANUAL = frozenset({"NEWORDER", "CANCEL", "REPLACE", "COMPLEXORDER", "SCRIPT", "GSCRIPT", "SLNEWORDER",
                             "SLOFFEROPERATION", "SLCANCELORDER"})


def test_r_o_03_mutantes_es_la_lista_completa_del_manual() -> None:
    assert protocolo.MUTANTES == MUTANTES_MANUAL


def _variantes(palabra: str) -> list[str]:
    resto = " 1 SS XYZ SAGEREB 100 3.45 TIF=DAY+"
    return [palabra + resto, palabra.lower() + resto, palabra.capitalize() + resto, "  " + palabra + resto,
            "\t" + palabra.lower() + resto, "GET BP\r\n" + palabra + resto, "GET BP\n" + palabra.lower() + resto,
            "SB XYZ Lv1\x0b" + palabra + resto]


CASOS_MUTANTES = [(p, v) for p in sorted(MUTANTES_MANUAL) for v in _variantes(p)]


@pytest.mark.parametrize("palabra, linea", CASOS_MUTANTES,
                         ids=[f"R-O-03-{p}-{i % 8}" for i, (p, _) in enumerate(CASOS_MUTANTES)])
def test_r_o_03_es_mutante_caza_todas_las_variantes_y_el_cliente_de_solo_lectura_las_prohibe(
        palabra: str, linea: str, reloj: RelojSimulado) -> None:
    assert protocolo.es_mutante(linea), linea
    cliente = ClienteDAS("127.0.0.1", 50999, USUARIO, "clave-inventada", CUENTA, False, True,
                         lambda m: None, lambda c, t: None, reloj)
    with pytest.raises(EnvioProhibido):
        cliente.enviar(linea)
    assert cliente.pendientes == 0


@pytest.mark.parametrize("linea, mutante", [
    ("SLPRICEINQUIRE XYZ 100 ALLROUTE", True), ("slpriceinquire xyz 100 allroute", True),
    ("SLPRICEINQUIRE XYZ 100 ALLROUTEWTTYPE1", False), ("GET BP", False), ("GET ORDERS", False),
    ("SB XYZ Lv1", False), ("UNSB XYZ Lv1", False), ("POSREFRESH", False), ("SLRouteMinCharge ALLROUTE", False),
    ("SLReuseQuery XYZ", False), ("QUIT", False), ("ECHO", False), ("", False), ("NEWORDERX 1", False),
], ids=["§5.22-ALLROUTE-crea-ofertas", "§5.22-allroute-minusculas", "§5.22-WTTYPE1-es-consulta", "R-O-03-GET-BP",
        "R-O-03-GET-ORDERS", "R-O-03-SB", "R-O-03-UNSB", "R-O-03-POSREFRESH", "R-O-03-min-charge",
        "R-O-03-reuse", "R-O-03-QUIT", "R-O-03-ECHO", "R-O-03-vacia", "R-O-03-palabra-parecida"])
def test_r_o_03_es_mutante_casos_frontera(linea: str, mutante: bool) -> None:
    assert protocolo.es_mutante(linea) is mutante


# ═══════════════════════════ (4) y (5) el código del paquete ══════════════
PATRONES_CREDENCIAL = {
    # un token de Telegram de verdad: «bot» + id (≥ 6 dígitos) + «:» + 30 o más caracteres de secreto
    "token_telegram": re.compile(r"bot\d{6,}:[A-Za-z0-9_-]{30,}"),
    "token_telegram_suelto": re.compile(r"(?<![\w-])\d{8,10}:[A-Za-z0-9_-]{35}(?![\w-])"),
    "clave_openai": re.compile(r"(?<![A-Za-z0-9])sk-[A-Za-z0-9_-]{16,}"),
    "clave_aws": re.compile(r"AKIA[0-9A-Z]{16}"),
}
IMPORT_WEBSOCKETS = re.compile(r"^\s*(import\s+websockets|from\s+websockets\b)", re.MULTILINE)
IMPORT_HTTPX = re.compile(r"^\s*(import\s+httpx|from\s+httpx\b)", re.MULTILINE)


def _ficheros_del_paquete() -> list[Path]:
    ficheros = sorted(p for p in PAQUETE.rglob("*") if p.is_file() and p.suffix in (".py", ".json")
                      and "__pycache__" not in p.parts)
    assert len(ficheros) > 20, ficheros                    # el paquete está ahí (no un directorio vacío)
    return ficheros


@pytest.mark.parametrize("nombre, patron", list(PATRONES_CREDENCIAL.items()),
                         ids=[f"riesgo20-{n}" for n in PATRONES_CREDENCIAL])
def test_riesgo20_ningun_literal_con_forma_de_credencial_en_el_paquete(nombre: str, patron: re.Pattern) -> None:
    hallados = [(p.relative_to(BACKEND).as_posix(), m.group(0)[:12] + "…")
                for p in _ficheros_del_paquete() for m in patron.finditer(p.read_text(encoding="utf-8"))]
    assert hallados == []


@pytest.mark.parametrize("patron, que", [(IMPORT_WEBSOCKETS, "websockets"), (IMPORT_HTTPX, "httpx")],
                         ids=["R-A-06-sin-websockets", "riesgo20-sin-httpx"])
def test_el_paquete_no_importa_websockets_ni_httpx(patron: re.Pattern, que: str) -> None:
    """R-A-06 (nunca un websocket desde el bot de DAS) y riesgo 20 (httpx filtra tokens en el log: el paquete usa urllib)."""
    hallados = [p.relative_to(BACKEND).as_posix() for p in _ficheros_del_paquete() if p.suffix == ".py"
                and patron.search(p.read_text(encoding="utf-8"))]
    assert hallados == [], f"{que} importado en {hallados}"


def test_los_patrones_de_credencial_cazan_lo_que_deben() -> None:
    """Guardia del propio test: los patrones reconocen formas típicas (inventadas) y no los ejemplos de documentación."""
    assert PATRONES_CREDENCIAL["token_telegram"].search("https://api/bot12345678:" + "A" * 35 + "/sendMessage")
    assert not PATRONES_CREDENCIAL["token_telegram"].search("/bot123456:ABC-def/sendMessage")
    assert PATRONES_CREDENCIAL["clave_openai"].search("sk-" + "a1" * 12)
    assert not PATRONES_CREDENCIAL["clave_openai"].search("task-runner desk-top")
    assert PATRONES_CREDENCIAL["clave_aws"].search("AKIA" + "Z9" * 8)
    assert IMPORT_HTTPX.search("x = 1\nimport httpx\n") and not IMPORT_HTTPX.search("# sin httpx: urllib\n")
