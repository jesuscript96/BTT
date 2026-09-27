"""Fixtures propias de los tests del bot de ejecución en DAS (documento §10).

QUÉ HACE. Reloj simulado a las 09:30 ET del 25-sep-2026, config de ejemplo
cargada, directorio temporal del bot con su estructura (§1), simulador de DAS
en 127.0.0.1:0 arrancado y parado, generador de tokens, estado vacío y una
fábrica de cotizaciones. Y una fixture autouse que deja el entorno LIMPIO.

POR QUÉ ESTÁ AQUÍ. Este directorio NO lleva `__init__.py` (como `tests/`):
pytest lo mete en `sys.path` y `import canal_falso` funciona. El `conftest.py`
raíz (`tests/conftest.py`) carga el `.env` real en `os.environ` al arrancar:
sin la fixture `entorno_limpio` un test podría depender de las credenciales
de Jaume o escribir en `D:\bot_senales`. NINGÚN test de aquí usa `real_db`.

LAS TRAMPAS.
  * `config.py` y `simulador_das.py` los escriben otros lotes en paralelo:
    se importan PEREZOSAMENTE dentro de la fixture con `pytest.importorskip`,
    así este fichero carga aunque falten.
  * La fábrica `cotizacion` convierte lo que le den con `Decimal(str(x))`:
    los tests escriben `cotizacion("XYZ", "3.44", "3.46")` o números y el
    objeto siempre lleva `Decimal` (nunca `float`).
  * `entorno_limpio` borra TODAS las `BOT_DAS_*` y luego fija `BOT_DAS_DIR`
    al directorio temporal: un test que necesite otra bandera la pone él.
"""
from __future__ import annotations

import os
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Optional

import pytest

from app.bot_das.reloj import ET, RelojSimulado
from app.bot_das.tipos import Cotizacion, EstadoBot, Fase, Origen
from app.bot_das.tokens import GeneradorTokens

FIXTURES = Path(__file__).parent / "fixtures"
RUTA_CONFIG_EJEMPLO = FIXTURES / "config_ejemplo.json"
CUENTA_DAS_PRUEBA = "CUENTA_PRUEBA"


def pytest_configure(config) -> None:
    """Registra el marcador `slow` (R-O-02: el replay de dias grabados) para que
    pytest no lo tome por una errata. Se puede excluir con `-m "not slow"`."""
    config.addinivalue_line("markers", "slow: replay de dias grabados reales (lento; se salta sin grabaciones)")
INICIO_RELOJ = datetime(2026, 9, 25, 9, 30, tzinfo=ET)
SUBCARPETAS_BOT = ("config", "diario", "estado", "cache", "logs")
# Ningún test depende del .env real (R-Q-01): fuera credenciales, chat ids y banderas del bot.
PREFIJOS_ENTORNO_BORRADOS = ("DAS_", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "BOT_DAS_", "SMTP_", "SMS_")
VARIABLES_ENTORNO_BORRADAS = ("BOT_DAS_PERMITIR_ORDENES", "BOT_DAS_AUTHKEY", "BOT_DAS_PING_URL", "MASSIVE_BOT_API_KEY")


@pytest.fixture(autouse=True)
def entorno_limpio(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Borra del entorno las variables del bot y fija BOT_DAS_DIR al temporal (nadie escribe en D:\\bot_senales)."""
    for nombre in list(os.environ):
        if nombre.startswith(PREFIJOS_ENTORNO_BORRADOS) or nombre in VARIABLES_ENTORNO_BORRADAS:
            monkeypatch.delenv(nombre, raising=False)
    raiz = tmp_path / "bot_das"
    for sub in SUBCARPETAS_BOT:
        (raiz / sub).mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("BOT_DAS_DIR", str(raiz))
    return raiz


@pytest.fixture
def dir_bot(entorno_limpio: Path) -> Path:
    """Directorio del bot (= BOT_DAS_DIR) con config/ diario/ estado/ cache/ logs/ creados."""
    return entorno_limpio


@pytest.fixture
def reloj() -> RelojSimulado:
    """RelojSimulado en 2026-09-25 09:30 ET (viernes con sesión)."""
    return RelojSimulado(INICIO_RELOJ)


@pytest.fixture
def cfg():
    """config_ejemplo.json cargado con `config.cargar` (lote B); se salta si config.py aún no existe."""
    config = pytest.importorskip("app.bot_das.config")
    return config.cargar(RUTA_CONFIG_EJEMPLO, cuenta_das=CUENTA_DAS_PRUEBA)


@pytest.fixture
def libro():
    """LibroSimulado vacío (lote A); se salta si simulador_das.py aún no existe."""
    simulador_das = pytest.importorskip("app.bot_das.simulador_das")
    return simulador_das.LibroSimulado()


@pytest.fixture
def _simulador_arrancado(libro, reloj: RelojSimulado):
    simulador_das = pytest.importorskip("app.bot_das.simulador_das")
    servidor = simulador_das.SimuladorDAS(libro, reloj, host="127.0.0.1", puerto=0)
    direccion = servidor.arrancar()
    try:
        yield servidor, direccion
    finally:
        servidor.parar()


@pytest.fixture
def simulador(_simulador_arrancado):
    """SimuladorDAS ya arrancado en 127.0.0.1:0 y parado al terminar el test."""
    return _simulador_arrancado[0]


@pytest.fixture
def direccion_simulador(_simulador_arrancado) -> tuple[str, int]:
    """(host, puerto) que devolvió `SimuladorDAS.arrancar()` para la fixture `simulador`."""
    return _simulador_arrancado[1]


@pytest.fixture
def tokens(reloj: RelojSimulado) -> GeneradorTokens:
    """GeneradorTokens(Origen.EJECUTOR, hoy del reloj)."""
    return GeneradorTokens(Origen.EJECUTOR, reloj.hoy())


@pytest.fixture
def estado_vacio(reloj: RelojSimulado) -> EstadoBot:
    """EstadoBot(fase=SOMBRA, dia=hoy del reloj), sin posiciones ni órdenes."""
    return EstadoBot(fase=Fase.SOMBRA, dia=reloj.hoy())


def _decimal(x) -> Decimal:
    return x if isinstance(x, Decimal) else Decimal(str(x))


@pytest.fixture
def cotizacion(reloj: RelojSimulado):
    """Fábrica: cotizacion(ticker, bid, ask, last=None, bsz=500, asz=500) → Cotizacion fresca (actualizada_en = reloj.mono())."""
    def _crear(ticker: str, bid, ask, last=None, bsz: int = 500, asz: int = 500) -> Cotizacion:
        ultimo: Optional[Decimal] = _decimal(last) if last is not None else None
        return Cotizacion(ticker=ticker, bid=_decimal(bid), ask=_decimal(ask), bsz=bsz, asz=asz,
                          last=ultimo, actualizada_en=reloj.mono())
    return _crear
