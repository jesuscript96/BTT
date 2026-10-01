"""Tests del proceso ejecutor (lote G2): bucle, write-ahead, política de disco, arranque F12 y DAS de verdad por socket.

QUÉ PRUEBA. `app.bot_das.ejecutor` en tres alturas:
  1. Piezas puras: `Temporizadores` (heap con sustitución por clave) y `Buzon`
     (la cola única y los callbacks de los hilos de borde).
  2. `Ejecutor` con un cliente FALSO (grabadora, `canal_falso.CanalFalso`) y el
     decisor REAL: el orden de F12 y sus salidas (doble instancia 3, reloj 2,
     motor 4), el write-ahead (M6: `orden_intencion` en disco ANTES del
     `enviar`), la política de disco (corrección 4) acción por acción, el
     candado de sombra (R-O-03), la foto atómica, las peticiones al supervisor,
     la parada ordenada, el latido que se retiene con un hilo muerto
     (injerto §8.11) y la reconexión por plan (R-J-02).
  3. Integración: `construir_desde_env` + `ClienteDAS`/`ClienteSombra` reales +
     `SimuladorDAS` en 127.0.0.1:0 + `FuenteEnProceso` con el motor de alertas
     sustituido (la vela da la señal de verdad). CANARIO: entrada → fills →
     stops residentes → el stop dispara → limpieza. SOMBRA: ni un mutante llega
     al DAS. Write-ahead visto DESDE el DAS. Diario bloqueado a mitad (no abre,
     sí protege). Métrica `senal_a_orden_ms` con y sin grupo A. Y el reinicio a
     mitad de mañana en dos SUBPROCESOS con la tubería de señales (H-2).

POR QUÉ ASÍ. El decisor ya tiene sus flujos probados en seco
(test_das_decisor); aquí se prueba lo que solo el ejecutor hace: el orden
entre diario y socket, los hilos, los ficheros de estado y el arranque.

LAS TRAMPAS.
  * Ninguna credencial: usuario, clave de DAS, cuenta y authkey son textos
    INVENTADOS para el simulador. El calendario y la referencia de Massive son
    dobles (los reales abren red). `main` solo se llama con `RUTA_DOTENV`
    apuntando a un fichero inexistente: el `.env` real NUNCA se carga.
  * El reloj de la integración es simulado y está PARADO: los mensajes de DAS
    llegan por el socket en tiempo real y el test bombea `paso()` hasta que se
    cumple la condición (con plazo real). Los temporizadores solo vencen si el
    test avanza el reloj.
  * El diario «roto» es un bloqueo de rango de bytes de Windows (`msvcrt`)
    sobre el final del fichero: las escrituras del ejecutor fallan de verdad
    (PermissionError) y vuelven al soltarlo.
  * El python del venv es un lanzador: el subproceso se mata por el PID de su
    fichero de cerrojo (`CerrojoInstancia.pid_guardado`), nunca por Popen.pid.
"""
from __future__ import annotations

import contextlib
import dataclasses
import json
import logging
import os
import signal
import socket
import subprocess
import sys
import time
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Iterator, Optional

import pytest

from app.bot_das import VERSION, protocolo
from app.bot_das import config as mod_config
from app.bot_das import ejecutor as ej
from app.bot_das.avisos import FiltroSecretos
from app.bot_das.cerrojo import CerrojoInstancia, Latido
from app.bot_das.cliente import ClienteDAS, ClienteSombra, EnvioProhibido
from app.bot_das.decisor import Decisor
from app.bot_das.diario import Diario, LectorDiario, nombre_fichero
from app.bot_das.mercado_das import MercadoDAS
from app.bot_das.reglas import rechazos
from app.bot_das.reloj import ET, RelojSimulado
from app.bot_das.simulador_das import Emparejador, LibroSimulado, SimuladorDAS
from app.bot_das.tipos import (
    LOCATES_INQUIRE_S,
    Anotar,
    Avisar,
    Cancelar,
    CancelarTicker,
    Config,
    Consultar,
    Desprogramar,
    EnviarOrden,
    Fase,
    Ficha,
    Grupo,
    InvalidarSerie,
    Lado,
    LocateComprar,
    LocateInquire,
    LocateOferta,
    Nivel,
    OrdenDescartada,
    OrdenNueva,
    Origen,
    PedirAlSupervisor,
    Programar,
    Proposito,
    PublicarFoto,
    Reemplazar,
    Registro,
    Salir,
    Senal,
    Suscribir,
    Tic,
    TipoOrden,
)
from app.bot_das.tokens import GeneradorTokens, componer
from canal_falso import CanalFalso

D = Decimal
BACKEND = Path(__file__).resolve().parents[2]
RUTA_CONFIG_EJEMPLO = Path(__file__).parent / "fixtures" / "config_ejemplo.json"
INICIO = datetime(2026, 9, 25, 9, 30, tzinfo=ET)          # el del reloj de conftest (viernes, RTH)
HOY = INICIO.date()
TICKER = "XYZ"
OTRO = "ABC"
SID = "prueba-1"
NOMBRE_ESTRATEGIA = "PM (A) prueba"
CUENTA = "CUENTA_PRUEBA"                                   # la del simulador: inventada
USUARIO = "usuario_prueba"                                 # inventado
CLAVE_DAS = "clave-inventada-para-tests-7731"              # inventada: solo la ve el simulador local
AUTHKEY = "authkey-inventada-para-tests-4410"              # inventada
PLAZO_S = 10.0                                             # plazo REAL para que llegue algo por el socket
TAM_BLOQUEO = 1 << 24                                      # bytes bloqueados al final del diario («disco roto»)


# ═══════════════════════════ dobles ══════════════════════════════════════
class CalendarioPrueba:
    """Franja por la hora ET, sin festivos ni red (el real pregunta a Massive en un hilo)."""

    def franja_de_mercado(self, ahora: datetime) -> str:
        minutos = ahora.hour * 60 + ahora.minute
        if 4 * 60 <= minutos < 9 * 60 + 30:
            return "premercado"
        if 9 * 60 + 30 <= minutos < 16 * 60:
            return "RTH"
        if 16 * 60 <= minutos < 20 * 60:
            return "postmercado"
        return "cerrado"

    def media_sesion(self, dia: date) -> Optional[str]:
        return None


class ReferenciaFalsa:
    """`ficha`/`splits_de_hoy` de Massive en memoria: una acción común vieja sin splits (no se excluye)."""

    def ficha(self, ticker: str) -> Ficha:
        return Ficha(ticker=ticker, list_date=date(2020, 1, 1), sic_code="1234", tipo="CS",
                     market_cap=D("100000000"), nombre="Prueba SA")

    def splits_de_hoy(self, dia: date) -> set[str]:
        return set()


class AvisosGrabados:
    """La cola de avisos del ejecutor, síncrona y en memoria (los avisos de arranque salen ANTES del diario)."""

    def __init__(self) -> None:
        self.avisos: list[Any] = []
        self.arrancado = False
        self.parado_con: Optional[float] = None
        self.vivo = True

    def poner(self, aviso: Any) -> None:
        self.avisos.append(aviso)

    def arrancar(self) -> None:
        self.arrancado = True

    def parar(self, espera_s: float = 30.0) -> None:
        self.parado_con = espera_s

    def foto(self) -> dict:
        return {"pendientes": 0}

    def de_nivel(self, nivel: Nivel) -> list[Any]:
        return [a for a in self.avisos if a.nivel is nivel]


class FuenteManual:
    """Una `FuenteSenales` que no produce nada sola: el test entrega por el buzón. `traza` registra el orden de F12."""

    origen = "manual"

    def __init__(self, traza: Optional[list] = None, falla: bool = False) -> None:
        self.viva = False
        self.falla = falla
        self.arranques = 0
        self.paradas = 0
        self.ultimo_en: Optional[float] = None
        self.ultimo_error: Optional[str] = None
        self._traza = traza if traza is not None else []

    def arrancar(self) -> None:
        self._traza.append(("fuente.arrancar",))
        if self.falla:
            raise OSError("la tubería no se pudo abrir (simulado)")
        self.viva = True
        self.arranques += 1

    def parar(self) -> None:
        self.viva = False
        self.paradas += 1

    def salud(self) -> dict:
        return {"viva": self.viva, "ultimo_en": self.ultimo_en, "origen": self.origen,
                "ultimo_error": self.ultimo_error}


class ClienteFalso(CanalFalso):
    """`CanalFalso` con el ciclo de vida del cliente (conectar/cerrar/hilos_vivos) y ganchos para los tests."""

    def __init__(self, traza: Optional[list] = None, conecta: bool = True, prohibir_mutantes: bool = False,
                 al_enviar: Optional[Callable[[str], None]] = None) -> None:
        super().__init__(conectado=False)
        self.conecta = conecta
        self.prohibir_mutantes = prohibir_mutantes
        self.al_enviar = al_enviar
        self.al_estado: Optional[Callable[[bool, str], None]] = None
        self.hilos_vivos = True
        self.conexiones = 0
        self.cerrado = False
        self._traza = traza if traza is not None else []

    def conectar(self) -> bool:
        self.conexiones += 1
        self._traza.append(("conectar", self.conecta))
        if not self.conecta:
            return False
        self.conectado = True
        if self.al_estado is not None:
            self.al_estado(True, "conectado (falso)")
        return True

    def cerrar(self) -> None:
        self.cerrado = True
        self.conectado = False

    def enviar(self, linea: str, serie: Optional[str] = None, version: int = 0) -> None:
        if self.prohibir_mutantes and protocolo.es_mutante(linea):
            raise EnvioProhibido(f"cliente de solo lectura: {linea}")
        if self.al_enviar is not None:
            self.al_enviar(linea)
        self._traza.append(("enviar", linea))
        super().enviar(linea, serie, version)


# ═══════════════════════════ utilidades ══════════════════════════════════
def registros(dir_bot: Path, proceso: str = "ejecutor", dia: date = HOY) -> list[Registro]:
    return LectorDiario(dir_bot / "diario").leer(dia, (proceso,))


def de_tipo(regs: list[Registro], tipo: str) -> list[Registro]:
    return [r for r in regs if r.tipo == tipo]


def lineas_jsonl(ruta: Path) -> list[dict]:
    """Lectura tolerante de un JSONL que otro proceso puede estar escribiendo (la última línea puede ir partida)."""
    try:
        texto = ruta.read_text(encoding="utf-8")
    except OSError:
        return []
    salida = []
    for linea in texto.split("\n"):
        try:
            salida.append(json.loads(linea))
        except ValueError:
            continue
    return salida


@contextlib.contextmanager
def diario_bloqueado(ruta: Path) -> Iterator[None]:
    """«Disco roto» (riesgo 23): bloqueo de Windows sobre el final del fichero; toda escritura del diario falla."""
    msvcrt = pytest.importorskip("msvcrt")
    manejador = open(ruta, "r+b")
    try:
        manejador.seek(0, os.SEEK_END)
        inicio = manejador.tell()
        msvcrt.locking(manejador.fileno(), msvcrt.LK_NBLCK, TAM_BLOQUEO)
        try:
            yield
        finally:
            manejador.seek(inicio)
            msvcrt.locking(manejador.fileno(), msvcrt.LK_UNLCK, TAM_BLOQUEO)
    finally:
        manejador.close()


def orden(proposito: Proposito, lado: Lado, *, seq: int, tipo: TipoOrden = TipoOrden.LIMITE, qty: int = 100,
          ticker: str = TICKER) -> OrdenNueva:
    token = componer(Origen.EJECUTOR, HOY.timetuple().tm_yday, seq)
    if tipo is TipoOrden.STOP_LIMITE_PP:
        return OrdenNueva(token=token, lado=lado, ticker=ticker, ruta="STOP", qty=qty, tipo=tipo, precio=D("4.12"),
                          stop=D("4"), proposito=proposito)
    if tipo is TipoOrden.MERCADO:
        return OrdenNueva(token=token, lado=lado, ticker=ticker, ruta="OPEN", qty=qty, tipo=tipo, proposito=proposito)
    return OrdenNueva(token=token, lado=lado, ticker=ticker, ruta="SAGEREB", qty=qty, tipo=tipo, precio=D("3.45"),
                      post_only=proposito is Proposito.ENTRADA_AGREGAR, proposito=proposito)


def neworders(lineas: list[str], lado: Optional[str] = None, ticker: Optional[str] = None) -> list[str]:
    salida = []
    for linea in lineas:
        p = linea.split()
        if not p or p[0].upper() != "NEWORDER":
            continue
        if lado is not None and p[2] != lado:
            continue
        if ticker is not None and p[3] != ticker:
            continue
        salida.append(linea)
    return salida


# ═══════════════════════════ montaje con cliente falso ═══════════════════
@dataclasses.dataclass
class Montaje:
    e: ej.Ejecutor
    diario: Diario
    cliente: ClienteFalso
    fuente: FuenteManual
    avisos: AvisosGrabados
    mercado: MercadoDAS
    reloj: RelojSimulado
    dir_bot: Path
    traza: list

    @property
    def estado(self) -> Path:
        return self.dir_bot / "estado"

    def regs(self) -> list[Registro]:
        return registros(self.dir_bot)

    def pasos(self, n: int = 3, espera_s: float = 0.0) -> None:
        for _ in range(n):
            assert self.e.paso(espera_s) is None


def _montar(cfg: Config, reloj: RelojSimulado, dir_bot: Path, *, cliente: Optional[ClienteFalso] = None,
            fuente: Optional[FuenteManual] = None, avisos: Optional[AvisosGrabados] = None,
            hash_motor: Optional[Callable[[Path], str]] = None, medir: Optional[Callable[[], Any]] = None,
            limpiar: Optional[Callable[[str], str]] = None, arrancar: bool = True,
            espera_reconciliacion_s: float = 0.2, latido: Optional[Latido] = None, referencia: Any = None,
            preparar_estado: Optional[Callable[[Any], None]] = None, aviso_config: Optional[str] = None) -> Montaje:
    traza: list = []
    cliente = cliente if cliente is not None else ClienteFalso(traza)
    cliente._traza = traza
    fuente = fuente if fuente is not None else FuenteManual(traza)
    fuente._traza = traza
    avisos = avisos if avisos is not None else AvisosGrabados()
    diario = Diario(dir_bot / "diario", reloj, "ejecutor", VERSION, cfg.fase, limpiar=limpiar)
    mercado = MercadoDAS(reloj)
    catalogo = rechazos.cargar_catalogo(rechazos.RUTA_CATALOGO)
    buzon = ej.Buzon()
    cliente.al_estado = buzon.al_estado

    ref = referencia if referencia is not None else ReferenciaFalsa()

    def fabrica(estado):
        if preparar_estado is not None:
            preparar_estado(estado)
        tokens = GeneradorTokens(Origen.EJECUTOR, estado.dia, estado.ultimo_seq_token)
        return Decisor(cfg, estado, mercado, ref, tokens, catalogo, lambda: diario.degradado,
                       calendario=CalendarioPrueba())

    estado_dir = dir_bot / "estado"
    e = ej.Ejecutor(cfg, cliente, fuente, diario, avisos, mercado, fabrica, reloj,
                    latido if latido is not None else Latido(estado_dir / ej.NOMBRE_LATIDO, reloj),
                    CerrojoInstancia(estado_dir / ej.NOMBRE_CERROJO),
                    [], None, estado_dir, buzon=buzon,
                    hash_motor=hash_motor if hash_motor is not None else (lambda base: cfg.motor_hash),
                    medir_desvio=medir if medir is not None else (lambda: 0.0), limpiar=limpiar,
                    espera_reconciliacion_s=espera_reconciliacion_s, espera_avisos_s=0.5, referencia=ref,
                    aviso_config=aviso_config)
    m = Montaje(e, diario, cliente, fuente, avisos, mercado, reloj, dir_bot, traza)
    if arrancar:
        assert e.arrancar() == ej.CODIGO_OK
    return m


@pytest.fixture
def montar(cfg: Config, reloj: RelojSimulado, dir_bot: Path):
    creados: list[Montaje] = []

    def crear(**kw: Any) -> Montaje:
        m = _montar(kw.pop("config", cfg), reloj, dir_bot, **kw)
        creados.append(m)
        return m

    yield crear
    for m in creados:
        m.e.parar()


# ═══════════════════════════ 1. piezas puras ═════════════════════════════
def test_temporizadores_sustituyen_por_clave_y_salen_en_orden() -> None:
    """§6.1: `Programar` con una clave existente la SUSTITUYE; `Desprogramar` inexistente no hace nada; orden por instante."""
    t = ej.Temporizadores()
    t.programar("barrido", 10.0, {"a": 1})
    t.programar("cruce:XYZ", 5.0)
    t.programar("barrido", 3.0, {"a": 2})                     # sustituye: solo cuenta el último
    t.programar("foto", 5.0)                                  # mismo instante que cruce: sale después (orden de alta)
    assert len(t) == 3 and t.claves() == ["barrido", "cruce:XYZ", "foto"]
    assert t.proximo() == 3.0 and t.cuando("barrido") == 3.0
    assert t.desprogramar("no_existe") is False
    assert t.sacar_vencido(2.9) is None
    assert t.sacar_vencido(3.0) == ("barrido", {"a": 2})
    assert t.sacar_vencido(100.0) == ("cruce:XYZ", {})
    assert t.desprogramar("foto") is True
    assert t.sacar_vencido(100.0) is None and t.proximo() is None and len(t) == 0


@pytest.mark.parametrize("clave, cuando", [("", 1.0), (None, 1.0), ("x", float("nan")), ("x", float("inf")),
                                           ("x", True), ("x", "1")],
                         ids=["§6.1-clave-vacia", "§6.1-clave-none", "§6.1-nan", "§6.1-inf", "§6.1-bool", "§6.1-texto"])
def test_temporizadores_rechazan_claves_e_instantes_imposibles(clave: Any, cuando: Any) -> None:
    with pytest.raises(ValueError):
        ej.Temporizadores().programar(clave, cuando)


def test_buzon_solo_admite_mensajes_y_traduce_los_callbacks_de_borde(monkeypatch: pytest.MonkeyPatch) -> None:
    """§6.1: los hilos de borde SOLO encolan; los avisos de borde van aparte, con tope, y los convierte el hilo principal."""
    b = ej.Buzon()
    with pytest.raises(TypeError):
        b.poner("no soy un Mensaje")  # type: ignore[arg-type]
    b.al_estado(True, "ok")
    b.al_caida_hilo("das-lector", "OSError: x", True)
    b.al_senal(Senal(clase="latido_feed", ticker=None, id=None))
    assert b.tamano() == 3
    assert type(b.sacar(0)).__name__ == "ConexionDAS"
    assert type(b.sacar(0)).__name__ == "HiloCaido"
    assert type(b.sacar(0)).__name__ == "SenalRecibida"
    assert b.sacar(0) is None and b.sacar(0.01) is None
    monkeypatch.setattr(ej, "AVISOS_BORDE_TOPE", 3)
    for i in range(5):
        b.al_aviso(f"aviso {i}")
    b.al_aviso_nivel(9, "nivel imposible → 2")
    pendientes = b.avisos_pendientes()
    assert [t for _, t, _ in pendientes] == ["aviso 3", "aviso 4", "nivel imposible → 2"]
    assert all(n is Nivel.AVISO for n, _, _ in pendientes)
    assert b.avisos_perdidos == 3 and b.avisos_pendientes() == []


# ═══════════════════════════ 2. arranque F12 ═════════════════════════════
def test_f12_doble_instancia_no_arranca_ni_toca_el_diario_de_la_viva(montar, dir_bot: Path) -> None:
    """R-J-04 c / F11 e: con el cerrojo tomado por otra instancia → código 3 + aviso 3; ni diario ni latido."""
    viva = CerrojoInstancia(dir_bot / "estado" / ej.NOMBRE_CERROJO)
    assert viva.adquirir()
    try:
        m = montar(arrancar=False)
        assert m.e.arrancar() == ej.CODIGO_DOBLE_INSTANCIA == 3
        assert m.e.codigo == 3
        maximos = m.avisos.de_nivel(Nivel.MAXIMO)
        assert len(maximos) == 1 and "R-J-04" in maximos[0].texto and maximos[0].grupo is Grupo.B
        assert not (dir_bot / "diario" / nombre_fichero("ejecutor", HOY)).exists()
        assert not (dir_bot / "estado" / ej.NOMBRE_LATIDO).exists()
        m.e.parar()
        assert viva.tomado and m.traza == []               # ni conectó ni arrancó la fuente
    finally:
        viva.soltar()


@pytest.mark.parametrize("desvio, codigo, aviso", [
    (2.5, ej.CODIGO_RELOJ, "R-J-07"), (-2.1, ej.CODIGO_RELOJ, "R-J-07"),
    (0.6, ej.CODIGO_OK, "Reloj"), (None, ej.CODIGO_OK, "sin SNTP"), (0.1, ej.CODIGO_OK, None),
], ids=["R-J-07-adelantado-2.5s-se-niega", "R-J-07-atrasado-2.1s-se-niega", "R-J-07-0.6s-avisa",
        "R-J-07-sin-SNTP-avisa", "R-J-07-0.1s-callado"])
def test_f12_veredicto_del_reloj(montar, dir_bot: Path, desvio: Optional[float], codigo: int,
                                 aviso: Optional[str]) -> None:
    m = montar(arrancar=False, medir=lambda: desvio)
    assert m.e.arrancar() == codigo
    if codigo == ej.CODIGO_RELOJ:
        assert not (dir_bot / "diario" / nombre_fichero("ejecutor", HOY)).exists()   # F12: el reloj va antes del diario
        assert m.traza == [] and len(m.avisos.de_nivel(Nivel.MAXIMO)) == 1
        return
    regs = m.regs()
    assert de_tipo(regs, "arranque")[0].datos["reloj_desvio_s"] == desvio
    avisos_reloj = [a for a in m.avisos.avisos if a.clave == "reloj_arranque"]
    if aviso is None:
        assert not avisos_reloj
    else:
        assert len(avisos_reloj) == 1 and aviso in avisos_reloj[0].texto and avisos_reloj[0].nivel is Nivel.AVISO


def test_f12_una_medida_sntp_que_revienta_cuenta_como_sin_sntp(montar) -> None:
    def rota() -> float:
        raise OSError("sin red (simulado)")

    m = montar(arrancar=False, medir=rota)
    assert m.e.arrancar() == ej.CODIGO_OK
    assert any("sin SNTP" in a.texto for a in m.avisos.avisos)


@pytest.mark.parametrize("hash_motor", [lambda base: "sha256:" + "f" * 64, "revienta"],
                         ids=["H-6-hash-distinto", "H-6-motor-ilegible"])
def test_f12_motor_distinto_niega_el_arranque_con_codigo_4(montar, dir_bot: Path, hash_motor: Any) -> None:
    def ilegible(base: Path) -> str:
        raise FileNotFoundError("strategy_engine.py (simulado)")

    m = montar(arrancar=False, hash_motor=ilegible if hash_motor == "revienta" else hash_motor)
    assert m.e.arrancar() == ej.CODIGO_MOTOR == 4
    texto = m.avisos.de_nivel(Nivel.MAXIMO)[0].texto
    assert "H-6" in texto and texto.startswith("[SOMBRA]")
    assert not (dir_bot / "diario" / nombre_fichero("ejecutor", HOY)).exists()
    assert m.traza == []


def test_f12_orden_del_arranque_y_la_fuente_al_final(montar) -> None:
    """F12 (R-J-02.5, R-O-01): diario → reconstrucción → conectar → consultas → (reconciliación) → la fuente la ÚLTIMA."""
    m = montar(espera_reconciliacion_s=0.1)
    pasos = m.traza
    assert pasos[0] == ("conectar", True)
    i_fuente = pasos.index(("fuente.arrancar",))
    enviadas = [p[1] for p in pasos[:i_fuente] if p[0] == "enviar"]
    for comando in ("GET RouteStatus", "GET BP", "GET AccountInfo", "GET INTMSGS", "SLRouteMinCharge ALLROUTE"):
        assert comando in enviadas, comando
    assert not any(protocolo.es_mutante(linea) for linea in m.cliente.enviadas())
    tipos = [r.tipo for r in m.regs()]
    for antes, despues in (("arranque", "config"), ("config", "reconstruccion"),
                           ("reconstruccion", "decisor_arranque"), ("decisor_arranque", "ejecutor_listo")):
        assert tipos.index(antes) < tipos.index(despues), (antes, despues)
    arranque = de_tipo(m.regs(), "arranque")[0].datos
    assert arranque["version"] == VERSION and arranque["motor_hash"] == m.e.cfg.motor_hash
    assert de_tipo(m.regs(), "reconciliacion_pendiente")                # el cliente falso no manda volcado
    assert any(a.clave == "reconciliacion_arranque" for a in m.avisos.avisos)
    listo = de_tipo(m.regs(), "ejecutor_listo")[0].datos
    assert listo["fuente_arrancada"] is True and listo["reconciliado"] is False and listo["pid"] == os.getpid()
    assert m.avisos.arrancado and m.fuente.viva
    with pytest.raises(RuntimeError):
        m.e.arrancar()                                                  # una sola vez por Ejecutor


def test_f11_sin_das_al_arrancar_arranca_degradado_y_reconecta_por_plan(montar) -> None:
    """R-J-02 / F11 a: sin DAS se arranca igual (stops residentes); reconexión a 2 s en un hilo aparte, no en el principal."""
    m = montar(cliente=ClienteFalso(conecta=False))
    m.pasos(2)
    assert "das" in m.e.decisor.estado.modo_degradado
    reconectar = de_tipo(m.regs(), "das_reconectar")
    assert reconectar and reconectar[0].datos["en_s"] == 2.0 and reconectar[0].datos["intento"] == 1
    m.cliente.conecta = True
    m.reloj.avanzar(1.9)
    m.pasos(2)
    assert m.cliente.conexiones == 1                                   # antes de los 2 s no se reintenta
    m.reloj.avanzar(0.2)
    limite = time.monotonic() + PLAZO_S
    while not m.e.decisor.estado.das_conectado:
        assert time.monotonic() < limite, "no reconectó"
        m.pasos(1, espera_s=0.02)
    assert m.cliente.conexiones == 2
    m.pasos(2)
    assert "das" not in m.e.decisor.estado.modo_degradado


def test_login_rechazado_no_programa_reconexion_y_avisa_una_vez(montar) -> None:
    """DAS real (01-oct): con «ERROR:INVALID PASSWORD» el cliente cierra la sesión; el ejecutor NO programa la
    reconexión (una clave mala en bucle bloquea el usuario en DAS): `das_reconectar_parado` en el diario, un único
    aviso 3 del decisor y el bot como con DAS caído (modo «das»)."""
    from app.bot_das.tipos import MsgLogin
    m = montar()
    m.pasos(2)
    assert m.cliente.conexiones == 1
    m.cliente.login_rechazado = "INVALID PASSWORD"                   # lo que deja ClienteDAS antes de avisar
    m.cliente.conectado = False
    m.e.buzon.al_mensaje(MsgLogin(cruda="ERROR:INVALID PASSWORD", ok=False, motivo="INVALID PASSWORD"))
    m.e.buzon.al_estado(False, "DAS rechazó el LOGIN: INVALID PASSWORD; no se reintenta")
    m.pasos(3)
    for _ in range(3):                                              # pasan los 2/4/8 s del plan: nada
        m.reloj.avanzar(10.0)
        m.pasos(2, espera_s=0.02)
    assert m.cliente.conexiones == 1
    assert not de_tipo(m.regs(), "das_reconectar")
    parado = de_tipo(m.regs(), "das_reconectar_parado")
    assert len(parado) == 1 and parado[0].datos["motivo"] == "DAS rechazó el LOGIN: INVALID PASSWORD"
    login = [a for a in m.avisos.avisos if a.clave == "das_logon:LOGIN"]
    assert len(login) == 1 and login[0].nivel is Nivel.MAXIMO and login[0].grupo is Grupo.B
    assert not [a for a in m.avisos.avisos if (a.clave or "").startswith("das_caido")]
    assert "das" in m.e.decisor.estado.modo_degradado and not m.e.decisor.estado.das_conectado
    assert CLAVE_DAS not in json.dumps([r.datos for r in m.regs()], default=str)


# ═══════════════════════════ 3. ejecutar(): write-ahead y política de disco ══
def test_m6_orden_intencion_en_disco_antes_del_envio_y_enviada_despues(montar, dir_bot: Path) -> None:
    """M6 / riesgo 3: cuando el cliente recibe la línea, `orden_intencion` (fsync) YA está en el fichero; `orden_enviada` después."""
    vistos: list[bool] = []
    ruta = dir_bot / "diario" / nombre_fichero("ejecutor", HOY)
    o = orden(Proposito.STOP, Lado.COMPRA, seq=900, tipo=TipoOrden.STOP_LIMITE_PP)

    def comprobar(linea: str) -> None:
        if linea.startswith("NEWORDER"):
            regs = [r for r in lineas_jsonl(ruta) if r.get("tipo") == "orden_intencion"]
            vistos.append(any(r["datos"]["token"] == o.token and r["datos"]["linea"] == linea for r in regs))

    m = montar(cliente=ClienteFalso(al_enviar=comprobar))
    m.e.ejecutar(EnviarOrden(o, serie="stops:XYZ"))
    assert vistos == [True]
    assert m.cliente.lineas[-1] == (f"NEWORDER {o.token} B XYZ STOP 100 STOPLMTP 4 4.12 TIF=DAY+", "stops:XYZ", 0)
    regs = m.regs()
    intencion = [r for r in de_tipo(regs, "orden_intencion") if r.datos["token"] == o.token][0]
    enviada = [r for r in de_tipo(regs, "orden_enviada") if r.datos["token"] == o.token][0]
    assert intencion.seq < enviada.seq
    assert intencion.datos["proposito"] == "stop" and intencion.datos["precio"] == "4.12"
    assert intencion.datos["origen"] == int(Origen.EJECUTOR) and intencion.datos["serie"] == "stops:XYZ"


CASOS_DISCO = [
    (Proposito.ENTRADA_AGREGAR, Lado.CORTO, TipoOrden.LIMITE, False),
    (Proposito.ENTRADA_CRUCE, Lado.CORTO, TipoOrden.LIMITE, False),
    (Proposito.DESCONOCIDA, Lado.CORTO, TipoOrden.LIMITE, False),
    (Proposito.ENTRADA_AGREGAR, Lado.COMPRA, TipoOrden.LIMITE, False),
    (Proposito.STOP, Lado.COMPRA, TipoOrden.STOP_LIMITE_PP, True),
    (Proposito.STOP_PROTECCION, Lado.COMPRA, TipoOrden.STOP_LIMITE_PP, True),
    (Proposito.VENTA_EXCESO, Lado.VENTA, TipoOrden.LIMITE, True),
    (Proposito.TP_CRUCE, Lado.COMPRA, TipoOrden.LIMITE, True),
    (Proposito.HORA_ASK, Lado.COMPRA, TipoOrden.LIMITE, True),
    (Proposito.CIERRE_HUMANO, Lado.COMPRA, TipoOrden.LIMITE, True),
    (Proposito.HALT_OPEN, Lado.COMPRA, TipoOrden.MERCADO, True),
]


@pytest.mark.parametrize("proposito, lado, tipo, sale", CASOS_DISCO,
                         ids=[f"correccion4-{p.value}-{l.value}-{'sale' if s else 'NO-sale'}"
                              for p, l, _, s in CASOS_DISCO])
def test_correccion4_con_el_diario_roto_no_abre_pero_protege(montar, dir_bot: Path, proposito: Proposito,
                                                              lado: Lado, tipo: TipoOrden, sale: bool) -> None:
    """Corrección 4 / riesgo 23: sin `orden_intencion` en disco NO sale nada que abra; stops, salidas y cierres SÍ."""
    m = montar()
    o = orden(proposito, lado, seq=901, tipo=tipo)
    antes = len(m.cliente.lineas)
    with diario_bloqueado(m.diario.ruta):
        m.e.ejecutar(EnviarOrden(o))
        assert m.diario.degradado
        salieron = neworders([linea for linea, _, _ in m.cliente.lineas[antes:]])
        assert (len(salieron) == 1) is sale
        avisos_disco = [a for a in m.avisos.avisos if a.clave == "disco_ejecutor"]
        assert len(avisos_disco) == (0 if sale else 1)
        if not sale:
            assert avisos_disco[0].nivel is Nivel.MAXIMO and "corrección 4" in avisos_disco[0].texto
    m.e.ejecutar(Anotar("prueba_disco", {"n": 1}))                         # el disco vuelve: se vuelca lo pendiente
    assert not m.diario.degradado
    regs = m.regs()
    assert [r.datos["token"] for r in de_tipo(regs, "orden_intencion")][-1] == o.token
    if sale:
        assert de_tipo(regs, "orden_enviada")[-1].datos["token"] == o.token
    else:
        descartada = de_tipo(regs, "senal_descartada")[-1]
        assert descartada.datos["token"] == o.token and descartada.datos["regla"] == "corrección 4"
        assert not [r for r in de_tipo(regs, "orden_enviada") if r.datos["token"] == o.token]


def test_correccion4_cancelaciones_replace_y_locates_con_el_diario_roto(montar) -> None:
    """Corrección 4: CANCEL, CANCEL ALLSYMB y REPLACE salen; la compra de locates NO; el aviso 3 sale UNA vez por episodio."""
    m = montar()
    antes = len(m.cliente.lineas)
    token_locate = componer(Origen.EJECUTOR_LOCATE, HOY.timetuple().tm_yday, 1)
    with diario_bloqueado(m.diario.ruta):
        m.e.ejecutar(Cancelar(1234, None, "prueba"))
        m.e.ejecutar(CancelarTicker(TICKER, "prueba"))
        m.e.ejecutar(Reemplazar(1235, 126800002, 50, D("4"), D("4.12"), "prueba", version=2, serie="stops:XYZ"))
        m.e.ejecutar(LocateComprar(TICKER, 1000, "LOCSIM", token_locate))
        m.e.ejecutar(EnviarOrden(orden(Proposito.ENTRADA_AGREGAR, Lado.CORTO, seq=902)))
    lineas = [linea for linea, _, _ in m.cliente.lineas[antes:]]
    assert lineas == ["CANCEL 1234", "CANCEL ALLSYMB XYZ", "REPLACE 1235 50 STOPLMT 4 4.12"]
    assert [a for a in m.avisos.avisos if a.clave == "disco_ejecutor"].__len__() == 1
    m.e.ejecutar(Anotar("prueba_disco", {}))
    regs = m.regs()
    assert de_tipo(regs, "locate_bloqueado")[0].datos["token"] == token_locate
    assert [r.datos.get("todas") for r in de_tipo(regs, "cancel_intencion")] == [None, True]
    assert de_tipo(regs, "replace_intencion")[0].datos["version"] == 2


def test_cancelar_reemplazar_e_invalidar_escriben_su_intencion_antes(montar, dir_bot: Path) -> None:
    """M6 / injerto §8.6: `cancel_intencion`/`replace_intencion` antes del socket; REPLACE con serie y versión; InvalidarSerie."""
    ruta = dir_bot / "diario" / nombre_fichero("ejecutor", HOY)
    orden_visto: list[tuple[str, bool]] = []

    def comprobar(linea: str) -> None:
        """La ÚLTIMA intención del fichero es la de esta línea (por su `linea`), no una anterior."""
        intenciones = [r for r in lineas_jsonl(ruta) if r.get("tipo") in ("cancel_intencion", "replace_intencion")]
        if linea.startswith(("CANCEL", "REPLACE")):
            orden_visto.append((linea, bool(intenciones) and intenciones[-1]["datos"].get("linea") == linea))

    m = montar(cliente=ClienteFalso(al_enviar=comprobar))
    m.e.ejecutar(InvalidarSerie("stops:XYZ", 3))
    m.e.ejecutar(Reemplazar(1235, 126800002, 60, D("4"), D("4.12"), "cantidad", version=3, serie="stops:XYZ"))
    m.e.ejecutar(Reemplazar(1236, 126800003, 60, None, D("3.50"), "perseguir"))
    m.e.ejecutar(Cancelar(1237, 126800004, "sobrante"))
    assert m.cliente.series_invalidadas == [("stops:XYZ", 3)]
    assert m.cliente.invalida_antes_de_enviar("stops:XYZ", 3)          # L0-01 / riesgo 7: invalidar PRECEDE al plan
    assert m.cliente.lineas[-3:] == [("REPLACE 1235 60 STOPLMT 4 4.12", "stops:XYZ", 3),
                                     ("REPLACE 1236 60 3.5", None, 0), ("CANCEL 1237", None, 0)]
    assert orden_visto == [("REPLACE 1235 60 STOPLMT 4 4.12", True), ("REPLACE 1236 60 3.5", True),
                           ("CANCEL 1237", True)]


def test_consultas_suscripciones_y_locates_van_por_protocolo(montar) -> None:
    """§3.27: Consultar/Suscribir/Locate* → `cliente.enviar` con `protocolo.cmd_*`."""
    m = montar()
    antes = len(m.cliente.lineas)
    token_locate = componer(Origen.EJECUTOR_LOCATE, HOY.timetuple().tm_yday, 7)
    for a in (Consultar("GET SymStatus XYZ"), Suscribir(TICKER, True), Suscribir(TICKER, False),
              LocateInquire(TICKER, 1000, "ALLROUTEWTTYPE1"), LocateComprar(TICKER, 1000, "LOCSIM", token_locate),
              LocateOferta(9001, True)):
        m.e.ejecutar(a)
    assert [linea for linea, _, _ in m.cliente.lineas[antes:]] == [
        "GET SymStatus XYZ", "SB XYZ Lv1", "UNSB XYZ Lv1", "SLPRICEINQUIRE XYZ 1000 ALLROUTEWTTYPE1",
        f"SLNEWORDER XYZ 1000 LOCSIM {token_locate}", "SLOFFEROPERATION 9001 Accept"]


def test_r_o_03_un_consultar_mutante_no_sale_y_un_envio_prohibido_es_un_bug(montar) -> None:
    """R-O-03: un Consultar mutante es un bug de programación (no sale, aviso 3); EnvioProhibido → orden_simulada bug + aviso 3."""
    m = montar(cliente=ClienteFalso(prohibir_mutantes=True))
    antes = len(m.cliente.lineas)
    m.e.ejecutar(Consultar("CANCEL ALL"))
    m.e.ejecutar(Consultar("get bp\r\nNEWORDER 1 SS XYZ SAGEREB 1 3 TIF=DAY+"))
    o = orden(Proposito.STOP, Lado.COMPRA, seq=903, tipo=TipoOrden.STOP_LIMITE_PP)
    m.e.ejecutar(EnviarOrden(o))
    assert m.cliente.lineas[antes:] == []
    maximos = m.avisos.de_nivel(Nivel.MAXIMO)
    assert len([a for a in maximos if a.clave == "consulta_mutante"]) == 2
    assert [a for a in maximos if a.clave == f"envio_prohibido:{o.token}"]
    regs = m.regs()
    simulada = de_tipo(regs, "orden_simulada")[-1].datos
    assert simulada["token"] == o.token and simulada["bug"] is True
    assert len(de_tipo(regs, "consulta_rechazada")) == 2


def test_riesgo12_una_accion_imposible_se_descarta_y_las_siguientes_salen(montar) -> None:
    """Riesgo 12 / H-5: un REPLACE fuera de tick no sale (aviso 2) y el stop de detrás SÍ sale."""
    m = montar()
    antes = len(m.cliente.lineas)
    stop = orden(Proposito.STOP, Lado.COMPRA, seq=904, tipo=TipoOrden.STOP_LIMITE_PP)
    for a in (Reemplazar(1235, 1, 60, None, D("3.455"), "fuera de tick"), EnviarOrden(stop),
              Avisar(Nivel.INFO, Grupo.B, "hola", None)):
        m.e.ejecutar(a)
    assert neworders([linea for linea, _, _ in m.cliente.lineas[antes:]]) == [protocolo.cmd_neworder(stop)]
    assert de_tipo(m.regs(), "accion_invalida")[0].datos["accion"] == "Reemplazar"
    assert [a.texto for a in m.avisos.avisos if a.clave == "accion_invalida:Reemplazar"]
    with pytest.raises(TypeError):
        m.e.ejecutar("no soy una Accion")  # type: ignore[arg-type]


def test_avisar_pone_en_la_cola_y_anota(montar) -> None:
    """R-M-01 / R-M-05: `Avisar` → `avisos.poner` (no bloquea) + registro `aviso` con nivel, grupo, clave y texto."""
    m = montar()
    m.e.ejecutar(Avisar(Nivel.AVISO, Grupo.A, "alerta al grupo A", "clave-a"))
    ultimo = m.avisos.avisos[-1]
    assert (ultimo.nivel, ultimo.grupo, ultimo.texto, ultimo.clave) == (Nivel.AVISO, Grupo.A, "alerta al grupo A",
                                                                        "clave-a")
    aviso = de_tipo(m.regs(), "aviso")[-1].datos
    assert (aviso["nivel"], aviso["grupo"], aviso["clave"], aviso["texto"]) == (2, "A", "clave-a", "alerta al grupo A")


def test_publicar_foto_es_atomica_y_sin_secretos(montar, dir_bot: Path) -> None:
    """Panel 4.4 / R-Q-01: `estado/foto.json` por tmp + os.replace, JSON válido, sin temporales, con el limpiador aplicado."""
    secreto = "valor-secreto-inventado-889911"
    m = montar(limpiar=FiltroSecretos([secreto]).limpiar)
    m.fuente.ultimo_error = f"la tubería dijo {secreto}"
    m.e.ejecutar(PublicarFoto())
    ruta = dir_bot / "estado" / ej.NOMBRE_FOTO
    texto = ruta.read_text(encoding="utf-8")
    assert secreto not in texto
    foto = json.loads(texto)
    assert foto["fase"] == "sombra" and foto["version"] == VERSION
    assert foto["ejecutor"]["pid"] == os.getpid() and foto["ejecutor"]["listo"] is True
    assert foto["ejecutor"]["fuente"]["viva"] is True and foto["ejecutor"]["todo_vivo"] is True
    assert list((dir_bot / "estado").glob("*.tmp")) == []


def test_pedir_al_supervisor_escribe_una_linea_json(montar, dir_bot: Path) -> None:
    """Corrección 16: `PedirAlSupervisor` → una línea JSON en `estado/orden_supervisor.jsonl` (append) y registro."""
    m = montar()
    m.e.ejecutar(PedirAlSupervisor("relanzar ejecutor"))
    m.e.ejecutar(PedirAlSupervisor("relanzar vigilante"))
    m.e.ejecutar(PedirAlSupervisor("parar"))                         # jamás se traduce a {"parar": true}
    peticiones = lineas_jsonl(dir_bot / "estado" / ej.NOMBRE_ORDEN_SUPERVISOR)
    assert [p["peticion"] for p in peticiones] == ["relanzar ejecutor", "relanzar vigilante", "parar"]
    assert [p.get("relanzar") for p in peticiones] == ["ejecutor", "vigilante", None]   # formato de tipos.PedirAlSupervisor
    assert all(p["proceso"] == "ejecutor" and p["pid"] == os.getpid() and "parar" not in p for p in peticiones)
    assert len(de_tipo(m.regs(), "peticion_supervisor")) == 3
    m.pasos(2)
    assert m.e.codigo is None                                        # su propia petición no lo para


def test_programar_desprogramar_y_el_temporizador_llega_al_decisor(montar) -> None:
    """§6.1: `Programar` al heap con el reloj inyectado; vencido → `Temporizador` al decisor; `Desprogramar` lo quita."""
    m = montar()
    m.e.ejecutar(Programar("sonda_prueba:XYZ", 5.0, {"n": 1}))
    m.e.ejecutar(Programar("sonda_quitada:XYZ", 5.0))
    m.e.ejecutar(Desprogramar("sonda_quitada:XYZ"))
    m.e.ejecutar(Desprogramar("no_existe"))
    m.e.ejecutar(Programar("sonda_invalida:XYZ", float("nan")))          # instante imposible → ya
    m.reloj.avanzar(4.9)
    m.pasos(1)
    claves = [r.datos.get("clave") for r in de_tipo(m.regs(), "temporizador_desconocido")]
    assert claves == ["sonda_invalida:XYZ"]
    m.reloj.avanzar(0.2)
    m.pasos(1)
    claves = [r.datos.get("clave") for r in de_tipo(m.regs(), "temporizador_desconocido")]
    assert claves == ["sonda_invalida:XYZ", "sonda_prueba:XYZ"]
    assert de_tipo(m.regs(), "temporizador_invalido")[0].datos["clave"] == "sonda_invalida:XYZ"


def test_salir_termina_el_bucle_con_su_codigo(montar) -> None:
    m = montar()
    m.e.ejecutar(Salir(7, "prueba de salida"))
    assert m.e.paso(0) == 7 and m.e.correr() == 7 and m.e.codigo == 7
    assert de_tipo(m.regs(), "salir")[0].datos == {"codigo": 7, "motivo": "prueba de salida", "mono": 1000.0}


def test_r_l_01_la_orden_parar_del_supervisor_para_el_bucle(montar, dir_bot: Path) -> None:
    """§6.2.5 / R-L-01: `{"parar": true}` escrito TRAS arrancar para; uno viejo, otro destinatario o media línea no."""
    ruta = dir_bot / "estado" / ej.NOMBRE_ORDEN_SUPERVISOR
    ruta.write_text(json.dumps({"parar": True}) + "\n", encoding="utf-8")        # de un apagado anterior
    m = montar()
    m.pasos(2)
    with open(ruta, "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps({"parar": True, "para": "vigilante"}) + "\n")
        f.write("esto no es json\n")
        f.write(json.dumps({"relanzar": "ejecutor"}) + "\n")
        f.write('{"parar": tr')                                                 # a medio escribir
    m.pasos(2)
    assert m.e.codigo is None
    with open(ruta, "a", encoding="utf-8", newline="\n") as f:
        f.write('ue}\n')
    assert m.e.correr() == ej.CODIGO_OK
    assert de_tipo(m.regs(), "orden_supervisor")[0].datos["regla"] == "R-L-01"


def test_injerto_8_11_el_latido_se_retiene_si_un_hilo_critico_muere(montar, dir_bot: Path) -> None:
    """R-J-04 b / injerto §8.11: con la fuente muerta el latido NO se escribe (el supervisor ve «colgado»); vuelve al revivir."""
    m = montar()
    ruta = dir_bot / "estado" / ej.NOMBRE_LATIDO
    assert Latido.edad(ruta, m.reloj.epoch()) == pytest.approx(0.0)
    m.fuente.viva = False
    m.reloj.avanzar(3.0)
    m.pasos(2)
    assert Latido.edad(ruta, m.reloj.epoch()) == pytest.approx(3.0)
    retenido = de_tipo(m.regs(), "latido_retenido")
    assert len(retenido) == 1 and retenido[0].datos["hilos"] == {"das": True, "avisos": True, "fuente": False}
    m.cliente.hilos_vivos = False                                           # otro hilo muerto: se anota el cambio
    m.reloj.avanzar(1.0)
    m.pasos(1)
    assert len(de_tipo(m.regs(), "latido_retenido")) == 2
    m.fuente.viva = True
    m.cliente.hilos_vivos = True
    m.reloj.avanzar(1.0)
    m.pasos(1)
    assert Latido.edad(ruta, m.reloj.epoch()) == pytest.approx(0.0)


def test_una_fuente_que_no_arranca_retiene_el_latido_y_avisa_3(montar, dir_bot: Path) -> None:
    m = montar(fuente=FuenteManual(falla=True))
    assert any(a.clave == "fuente_fallo" and a.nivel is Nivel.MAXIMO for a in m.avisos.avisos)
    assert de_tipo(m.regs(), "fuente_fallo")[0].datos["fuente"] == "FuenteManual"
    m.reloj.avanzar(2.0)
    m.pasos(1)
    assert Latido.edad(dir_bot / "estado" / ej.NOMBRE_LATIDO, m.reloj.epoch()) >= 2.0
    m.e.parar()
    assert m.fuente.paradas == 0                                            # nunca arrancó: no se para


def test_h5_una_excepcion_del_decisor_no_tumba_el_bucle(montar, monkeypatch: pytest.MonkeyPatch) -> None:
    m = montar()
    llamadas = {"n": 0}
    original = m.e.decisor.procesar

    def rota(msg, ahora, ahora_et):
        llamadas["n"] += 1
        if llamadas["n"] == 1:
            raise RuntimeError("fallo inesperado (simulado)")
        return original(msg, ahora, ahora_et)

    monkeypatch.setattr(m.e.decisor, "procesar", rota)
    m.e.buzon.poner(Tic())
    m.pasos(2)
    assert llamadas["n"] >= 2
    excepcion = de_tipo(m.regs(), "excepcion")[0].datos
    assert excepcion["donde"] == "decisor.procesar" and "RuntimeError" in excepcion["error"]
    assert any(a.clave == "excepcion_ejecutor:Tic" for a in m.avisos.avisos)


def test_f11_b_la_fuente_en_proceso_da_el_latido_del_feed(montar) -> None:
    """R-J-01 (F11 b): sin tubería, el latido del feed sale de `salud()["ultimo_en"]` de la fuente (si no, a los 60 s no se abriría)."""
    m = montar()
    estado = m.e.decisor.estado
    m.pasos(1)
    assert estado.feed_ultima_vela_en is None                               # sin velas todavía: nada
    m.fuente.ultimo_en = m.reloj.epoch() - 10.0
    m.pasos(1)
    assert estado.feed_ultima_vela_en == pytest.approx(m.reloj.mono() - 10.0)
    m.reloj.avanzar(90.0)
    m.fuente.ultimo_en = m.reloj.epoch()
    m.pasos(1)
    assert estado.feed_ultima_vela_en == pytest.approx(m.reloj.mono())
    assert "feed" not in estado.modo_degradado


def test_riesgo17_la_cola_grande_avisa_una_vez(montar, cfg: Config, monkeypatch: pytest.MonkeyPatch) -> None:
    m = montar(config=dataclasses.replace(cfg, tecnicos={**cfg.tecnicos, "cola_aviso_umbral": 3}))
    monkeypatch.setattr(ej, "TIC_MAX_S", 0.0)
    for _ in range(8):
        m.e.buzon.poner(Tic())
    m.pasos(3)
    assert len([a for a in m.avisos.avisos if a.clave == "cola_grande"]) == 1
    assert de_tipo(m.regs(), "cola_grande")[0].datos["umbral"] == 3


def test_cambio_de_dia_abre_el_diario_del_dia_nuevo(montar, dir_bot: Path) -> None:
    """§8: un diario por día y proceso; si el ejecutor sigue vivo a medianoche abre el del día siguiente."""
    m = montar()
    m.reloj.fijar(datetime(2026, 9, 26, 0, 0, 5, tzinfo=ET))
    m.pasos(1)
    nuevos = registros(dir_bot, dia=date(2026, 9, 26))
    assert [r.tipo for r in nuevos][:1] == ["arranque"] and de_tipo(nuevos, "dia_nuevo_diario")


def test_parar_es_ordenado_e_idempotente(montar, dir_bot: Path) -> None:
    """§6.2.5: fuente → cliente (QUIT) → avisos.parar → diario → cerrojo; deja `parada` y la foto final."""
    m = montar()
    m.e.parar()
    m.e.parar()
    assert m.fuente.paradas == 1 and m.cliente.cerrado and m.avisos.parado_con == 0.5
    otro = CerrojoInstancia(dir_bot / "estado" / ej.NOMBRE_CERROJO)
    assert otro.adquirir()
    otro.soltar()
    assert de_tipo(m.regs(), "parada")[0].datos["codigo"] is None
    foto = json.loads((dir_bot / "estado" / ej.NOMBRE_FOTO).read_text(encoding="utf-8"))
    assert foto["ejecutor"]["parado"] is True


def test_el_constructor_rechaza_piezas_equivocadas(cfg: Config, reloj: RelojSimulado, dir_bot: Path) -> None:
    diario = Diario(dir_bot / "diario", reloj, "ejecutor", VERSION, cfg.fase)
    mercado = MercadoDAS(reloj)
    base = dict(cfg=cfg, cliente=ClienteFalso(), fuente=FuenteManual(), diario=diario, avisos=AvisosGrabados(),
                mercado=mercado, decisor=lambda estado: None, reloj=reloj,
                latido=Latido(dir_bot / "estado" / "l", reloj), cerrojo=CerrojoInstancia(dir_bot / "estado" / "c"),
                receptores=[], config_watch=None, ruta_estado=dir_bot / "estado")
    ej.Ejecutor(**base)
    for campo, malo in (("cfg", {}), ("cliente", object()), ("fuente", object()), ("diario", object()),
                        ("avisos", object()), ("mercado", object()), ("decisor", "no callable"),
                        ("latido", object()), ("cerrojo", object()), ("receptores", [object()]),
                        ("config_watch", object())):
        with pytest.raises(TypeError):
            ej.Ejecutor(**{**base, campo: malo})
    with pytest.raises(ValueError):
        ej.Ejecutor(**base, espera_reconciliacion_s=-1)
    with pytest.raises(RuntimeError):
        ej.Ejecutor(**base).correr()


# ═══════════════════════════ 3b. correcciones de la revisión (G2, D2a-06, G1A-03, G1B-01, H-2) ═══
class RelojReal:
    """Reloj de pared para medir el latido de verdad (el simulado de conftest está PARADO)."""

    def mono(self) -> float:
        return time.monotonic()

    def epoch(self) -> float:
        return time.time()


class LatidoEspia(Latido):
    """Latido que apunta cuándo (tiempo real) escribió de verdad."""

    def __init__(self, ruta: Path) -> None:
        super().__init__(ruta, RelojReal(), cada_s=0.1)
        self.escrito_en: list[float] = []

    def tocar(self, todo_vivo: bool = True) -> None:
        antes = self.escrituras
        super().tocar(todo_vivo)
        if self.escrituras != antes:
            self.escrito_en.append(time.monotonic())


class ClienteLento(ClienteFalso):
    """`connect` que tarda (DAS que acepta tarde): el hilo principal no puede quedarse sin latido."""

    def __init__(self, tarda_s: float) -> None:
        super().__init__()
        self.tarda_s = tarda_s

    def conectar(self) -> bool:
        time.sleep(self.tarda_s)
        return super().conectar()


class ClienteQueDescarta(ClienteFalso):
    """`enviar` devuelve False para los mutantes (sin conexión o cola llena): G2-05."""

    def enviar(self, linea: str, serie: Optional[str] = None, version: int = 0) -> Optional[bool]:
        super().enviar(linea, serie, version)
        return False if protocolo.es_mutante(linea) else True


def test_g2_02_sntp_hash_y_connect_lentos_no_dejan_el_latido_sin_tocar(montar, dir_bot: Path) -> None:
    """G2-02 (R-J-04 b, §6): con un SNTP que tarda 1,6 s y un connect de 1,6 s el latido se sigue tocando cada ≤ 1 s
    durante `arrancar()` (el supervisor mata a los 3 s): la red corre en un hilo de un solo uso."""
    latido = LatidoEspia(dir_bot / "estado" / ej.NOMBRE_LATIDO)

    def sntp_lento() -> float:
        time.sleep(1.6)
        return 0.0

    def hash_lento(base: Path) -> str:
        time.sleep(1.2)
        return m.e.cfg.motor_hash

    m = montar(arrancar=False, medir=sntp_lento, cliente=ClienteLento(1.6), latido=latido)
    m.e._hash_motor = hash_lento
    inicio = time.monotonic()
    assert m.e.arrancar() == ej.CODIGO_OK
    fin = time.monotonic()
    marcas = [inicio] + [t for t in latido.escrito_en if inicio <= t <= fin] + [fin]
    huecos = [b - a for a, b in zip(marcas, marcas[1:])]
    assert fin - inicio >= 4.0 and max(huecos) <= 1.0, huecos
    assert m.cliente.conexiones == 1 and m.e.decisor.estado.das_conectado


def test_g2_02_una_excepcion_en_el_hilo_auxiliar_llega_al_principal(montar) -> None:
    """G2-02: `_con_latido` devuelve el resultado o relanza en el hilo principal lo que lanzó el hilo auxiliar."""
    m = montar()
    assert m.e._con_latido("prueba", lambda: 7) == 7
    with pytest.raises(ZeroDivisionError):
        m.e._con_latido("prueba", lambda: 1 / 0)


def test_g2_05_una_orden_que_el_cliente_descarta_no_se_anota_como_enviada(montar, dir_bot: Path) -> None:
    """G2-05 (M6, riesgo 3): `cliente.enviar` → False ⇒ `orden_intencion` + `orden_descartada`, NUNCA `orden_enviada`, y
    el decisor recibe `OrdenDescartada` (D2a-06: la cierra y replanifica). Un CANCEL descartado → `linea_descartada`."""
    m = montar(cliente=ClienteQueDescarta())
    o = orden(Proposito.STOP, Lado.COMPRA, seq=950, tipo=TipoOrden.STOP_LIMITE_PP)
    enviadas_antes = m.e._enviadas
    m.e.ejecutar(EnviarOrden(o, serie="stops:XYZ"))
    regs = m.regs()
    assert [r for r in de_tipo(regs, "orden_intencion") if r.datos["token"] == o.token]
    assert not [r for r in de_tipo(regs, "orden_enviada") if r.datos["token"] == o.token]
    descartada = [r for r in de_tipo(regs, "orden_descartada") if r.datos["token"] == o.token]
    assert len(descartada) == 1 and descartada[0].datos["regla"] == "G2-05"
    assert m.e._enviadas == enviadas_antes
    msg = m.e.buzon.sacar(0)
    assert isinstance(msg, OrdenDescartada) and msg.token == o.token and msg.ticker == TICKER
    assert msg.serie == "stops:XYZ" and msg.motivo == ej.MOTIVO_NO_ENCOLADA
    m.e.buzon.poner(msg)
    m.pasos(2)
    assert [r for r in de_tipo(m.regs(), "orden_descartada") if r.datos.get("regla") == "D2a-06"]   # lo vio el decisor
    m.e.ejecutar(Cancelar(id_das=4242, token=o.token, motivo="prueba"))
    assert [r for r in de_tipo(m.regs(), "linea_descartada") if r.datos["accion"] == "Cancelar"]


def test_g2_05_d2a_06_construir_conecta_al_descartar_del_cliente_con_la_cola(cfg: Config, reloj: RelojSimulado,
                                                                            monkeypatch: pytest.MonkeyPatch) -> None:
    """D2a-06: `construir_desde_env` da al `ClienteDAS` el `al_descartar` del buzón; lo que el emisor purga llega al
    decisor como `OrdenDescartada` (también en sombra, con el emparejador respetando A-02)."""
    _entorno_das(monkeypatch)
    monkeypatch.setenv("BOT_DAS_PERMITIR_ORDENES", "1")
    e = _construir(dataclasses.replace(cfg, fase=Fase.CANARIO), reloj)
    assert e.cliente._al_descartar == e.buzon.al_descartar
    e.cliente._al_descartar(OrdenDescartada(token=123, serie="stops:XYZ", version=1, motivo="descartada por versión"))
    assert isinstance(e.buzon.sacar(0), OrdenDescartada)
    with pytest.raises(TypeError):
        e.buzon.al_descartar("no es un mensaje")  # type: ignore[arg-type]
    sombra_cfg = dataclasses.replace(cfg, fase=Fase.SOMBRA, stops={**cfg.stops, "replace_share_es_abierta": False})
    s = _construir(sombra_cfg, reloj)
    assert s.cliente.real._al_descartar == s.buzon.al_descartar
    assert s.cliente.emparejador.replace_share_es_abierta is False


class ReferenciaCacheLenta:
    """La caché de `referencia_massive.Referencia` (G1A-03) con una «red» que tarda: registra las precargas."""

    def __init__(self, tarda_s: float = 0.0, splits_revienta: bool = False) -> None:
        import threading
        self.tarda_s = tarda_s
        self.splits_revienta = splits_revienta
        self._lock = threading.Lock()
        self._fichas: dict[str, Ficha] = {}
        self._pendientes: set[str] = set()
        self._splits: Optional[set[str]] = None
        self.precargas_splits: list[date] = []
        self.precargas_ficha: list[str] = []

    def ficha_en_cache(self, ticker: str) -> Optional[Ficha]:
        with self._lock:
            if ticker in self._fichas:
                return self._fichas[ticker]
            self._pendientes.add(ticker)
            return None

    def pedir_ficha(self, ticker: str) -> None:
        with self._lock:
            if ticker not in self._fichas:
                self._pendientes.add(ticker)

    def splits_en_cache(self, dia: date) -> Optional[set[str]]:
        with self._lock:
            return None if self._splits is None else set(self._splits)

    def splits_pendientes(self, dia: date) -> bool:
        with self._lock:
            return self._splits is None and not self.precargas_splits

    def tomar_pendientes(self) -> list[str]:
        with self._lock:
            return sorted(self._pendientes)

    def precargar_splits(self, dia: date) -> Optional[set[str]]:
        if self.splits_revienta:
            raise OSError("Massive caído (simulado)")
        time.sleep(self.tarda_s)
        with self._lock:
            self.precargas_splits.append(dia)
            self._splits = set()
        return set()

    def precargar_ficha(self, ticker: str) -> Optional[Ficha]:
        time.sleep(self.tarda_s)
        ficha = ReferenciaFalsa().ficha(ticker)
        with self._lock:
            self.precargas_ficha.append(ticker)
            self._fichas[ticker] = ficha
            self._pendientes.discard(ticker)
        return ficha


def test_g1a_03_g1b_08_el_hilo_referencia_precarga_sin_frenar_el_bucle(montar) -> None:
    """G1A-03 / G1B-08: el HiloVigilado «referencia» precarga los splits del día al arrancar y las fichas que el decisor
    pide; cada vuelta del bucle sigue durando milisegundos aunque cada petición a Massive tarde 1 s."""
    ref = ReferenciaCacheLenta(tarda_s=1.0)
    m = montar(referencia=ref)
    assert de_tipo(m.regs(), "referencia_precarga")
    ref.pedir_ficha(TICKER)
    limite = time.monotonic() + PLAZO_S
    duraciones: list[float] = []
    while TICKER not in ref.precargas_ficha:
        assert time.monotonic() < limite, "el hilo referencia no precargó la ficha"
        antes = time.monotonic()
        m.pasos(1, espera_s=0.02)
        duraciones.append(time.monotonic() - antes)
    assert ref.precargas_splits == [HOY]
    assert ref.ficha_en_cache(TICKER) is not None
    assert max(duraciones) < 0.5, max(duraciones)
    assert m.e._hilo_referencia.vivo
    m.e.parar()
    assert m.e._hilo_referencia.parando.is_set()


def test_g1a_03_sin_precarga_no_hay_hilo_y_si_muere_avisa_3(montar, monkeypatch: pytest.MonkeyPatch) -> None:
    """G1A-03: una referencia en memoria (replay, tests) no arranca hilo; si el hilo de la real muere sin relanzarse, sin
    fichas no se abre nada (A12): aviso 3 una sola vez."""
    m = montar()
    assert m.e._hilo_referencia is None
    m.e.parar()                                              # suelta el cerrojo: el segundo ejecutor es otra instancia
    import functools
    from app.bot_das.cerrojo import HiloVigilado
    monkeypatch.setattr(ej, "HiloVigilado", functools.partial(HiloVigilado, max_relanzos=0, espera_s=0.0))
    m2 = montar(referencia=ReferenciaCacheLenta(splits_revienta=True))
    limite = time.monotonic() + PLAZO_S
    while m2.e._hilo_referencia.vivo:
        assert time.monotonic() < limite
        time.sleep(0.02)
    m2.pasos(3)
    m2.e.buzon.poner(Tic())
    m2.pasos(2)
    muertas = [a for a in m2.avisos.avisos if a.clave == "referencia_muerta"]
    assert len(muertas) == 1 and muertas[0].nivel is Nivel.MAXIMO and "A12" in muertas[0].texto
    assert de_tipo(m2.regs(), "referencia_muerta")


def _escribir_diario_previo(dir_bot: Path, reloj: RelojSimulado, cfg: Config, registros_previos: list) -> None:
    previo = Diario(dir_bot / "diario", reloj, "ejecutor", VERSION, cfg.fase)
    previo.abrir_dia(HOY, motor_hash=cfg.motor_hash, config_version=cfg.config_version,
                     estrategias_hash=cfg.estrategias_hash)
    for tipo, datos in registros_previos:
        previo.anotar(tipo, **datos)
    previo.cerrar()


def test_h2_e1_03_g1b_09_c_02_la_memoria_del_decisor_se_siembra_del_diario(montar, cfg: Config, reloj: RelojSimulado,
                                                                           dir_bot: Path) -> None:
    """E1-03 / G1B-09 / C-02 (lo que el decisor dejó pendiente al ejecutor): al arrancar, el decisor se siembra con
    `diario.memoria_decisor`: k de halts, /modo_seguridad de Telegram y los ids de comando ya vistos (un «/estado» con
    el mismo id que Telegram reentrega tras el reinicio se ignora)."""
    from app.bot_das import comandos as mod_comandos
    from app.bot_das.tipos import Comando, ComandoRecibido
    _escribir_diario_previo(dir_bot, reloj, cfg, [
        ("halt", {"ticker": TICKER, "k": 2, "ta": "H"}),
        ("config_cambio", {"ruta": "modo_seguridad.activo", "antes": False, "despues": True, "caliente": True,
                           "aplicado": True, "origen": "telegram"}),
        ("comando", {"nombre": "estado", "args": [], "chat_id": 1, "id": "tg:77", "confirmado": True}),
    ])
    m = montar()
    memoria = de_tipo(m.regs(), "memoria_decisor")
    assert memoria and memoria[-1].datos["k_halts_up"] == {TICKER: 2} and memoria[-1].datos["comandos_ids"] == 1
    assert m.mercado.simbolo(TICKER).k_halts_up == 2
    assert m.e.decisor.cfg.modo_seguridad.get("activo") is True
    m.e.buzon.poner(ComandoRecibido(Comando(nombre="estado", args=[], chat_id=1, requiere=mod_comandos.REQUIERE_NADA,
                                            id="tg:77", texto="/estado")))
    m.pasos(2)
    assert [r for r in de_tipo(m.regs(), "comando_repetido") if r.datos.get("id") == "tg:77"]


def test_g1b_01_rearranque_con_eod_vencido_no_compra_nada_antes_de_reconciliar(montar) -> None:
    """G1B-01 (R-J-02.5): el ejecutor arranca con un lote cuyo EOD ya venció y DAS sin volcado (no hay reconciliación):
    los temporizadores vencidos pasan por el decisor, que los aplaza; en 5 s ningún NEWORDER de compra sale a DAS."""
    from app.bot_das.tipos import EstadoLote, Lote, PosicionTicker

    def con_lote(estado) -> None:
        pos = PosicionTicker(ticker=TICKER, neta_fills=-100)
        lote = Lote(id=f"{TICKER}|{SID}|2026-09-25 09:00:00|entrada", strategy_id=SID, estrategia=NOMBRE_ESTRATEGIA,
                    ticker=TICKER, direccion="Short", pedidas=100, llenas=100, precio_medio=D("3.45"),
                    nivel_stop=D("4.0"), estado=EstadoLote.ABIERTO, eod="09:20:00")
        pos.lotes[lote.id] = lote
        estado.posiciones[TICKER] = pos

    m = montar(preparar_estado=con_lote)
    assert "reconciliacion" in m.e.decisor.estado.modo_degradado
    for _ in range(10):
        m.reloj.avanzar(0.5)
        m.pasos(2)
    assert neworders(m.cliente.enviadas(), "B", TICKER) == []
    assert de_tipo(m.regs(), "salida_aplazada")


@pytest.mark.parametrize("valor, esperado", [(False, False), (True, True), (None, True)],
                         ids=["A-02-total", "A-02-abierta", "A-02-sin-clave-defecto"])
def test_a_02_reconstruir_lee_el_replace_con_el_interruptor_de_la_config(montar, cfg: Config,
                                                                         monkeypatch: pytest.MonkeyPatch,
                                                                         valor: Any, esperado: bool) -> None:
    """A-02 (pendiente del decisor para el ejecutor): `reconstruir` recibe `stops.replace_share_es_abierta` de la config
    (sin la clave, el defecto de tipos): un REPLACE confirmado se relee tras un reinicio igual que lo mandó el decisor."""
    vistos: list[bool] = []
    original = ej.reconstruir

    def espia(registros, hoy, replace_share_es_abierta=True):
        vistos.append(replace_share_es_abierta)
        return original(registros, hoy, replace_share_es_abierta=replace_share_es_abierta)

    monkeypatch.setattr(ej, "reconstruir", espia)
    stops = {k: v for k, v in cfg.stops.items() if k != "replace_share_es_abierta"}
    if valor is not None:
        stops["replace_share_es_abierta"] = valor
    montar(config=dataclasses.replace(cfg, stops=stops))
    assert vistos == [esperado]


def test_pedir_al_supervisor_se_deduplica_10_s(montar, dir_bot: Path) -> None:
    """Dedupe de PedirAlSupervisor (como el vigilante, corrección 16): la misma petición como mucho cada 10 s."""
    m = montar()
    for _ in range(3):
        m.e.ejecutar(PedirAlSupervisor("relanzar vigilante"))
    ruta = dir_bot / "estado" / ej.NOMBRE_ORDEN_SUPERVISOR
    assert len(lineas_jsonl(ruta)) == 1
    m.reloj.avanzar(ej.PETICION_REPETIR_S)
    m.e.ejecutar(PedirAlSupervisor("relanzar vigilante"))
    m.e.ejecutar(PedirAlSupervisor("relanzar ejecutor"))
    assert [p["peticion"] for p in lineas_jsonl(ruta)] == ["relanzar vigilante", "relanzar vigilante",
                                                           "relanzar ejecutor"]


@pytest.mark.parametrize("forzada,nivel", [(True, Nivel.MAXIMO), (False, Nivel.AVISO)],
                         ids=["R2-PRO-3-fase-forzada-nivel-3", "R2-PRO-3-respaldo-sin-forzar-nivel-2"])
def test_r2_pro_3_el_aviso_de_fase_forzada_a_sombra_sale_con_nivel_3(montar, dir_bot: Path, forzada: bool,
                                                                     nivel: Nivel) -> None:
    """R2-PRO-3 (SEG-02): si `cargar_con_respaldo` usó el último bueno y bajó la fase a SOMBRA, el aviso del arranque
    sale con Nivel.MAXIMO (el bot deja de operar dinero real); un respaldo sin forzar la fase sigue siendo nivel 2."""
    texto = "Configuración del cuadro inválida (x): se usa el último bueno (config_version 1) (H-4)"
    if forzada:
        texto += f" · {mod_config.AVISO_FASE_FORZADA}: el último bueno estaba en REAL"
    m = montar(aviso_config=texto)
    avisos = [a for a in m.avisos.avisos if a.clave == "config_respaldo"]
    assert len(avisos) == 1 and avisos[0].nivel is nivel
    assert (mod_config.AVISO_FASE_FORZADA in avisos[0].texto) is forzada
    anotado = [r for r in de_tipo(m.regs(), "aviso") if r.datos.get("clave") == "config_respaldo"]
    assert len(anotado) == 1 and anotado[0].datos["nivel"] == int(nivel)


def test_a_07_la_cuota_agotada_de_la_sombra_se_anota(montar) -> None:
    """A-07: lo que `ClienteSombra.al_cuota_agotada` cuenta llega al diario como «cuota_agotada» desde el hilo principal."""
    m = montar()
    m.e.buzon.al_cuota_agotada("CANCEL 1", 0.4)
    m.pasos(1)
    registro = de_tipo(m.regs(), "cuota_agotada")
    assert registro and registro[0].datos["linea"] == "CANCEL 1" and registro[0].datos["espera_s"] == 0.4


# ═══════════════════════════ 4. integración con el simulador de DAS ═══════
@pytest.fixture
def motor_falso(monkeypatch: pytest.MonkeyPatch) -> dict:
    """Motor de alertas con el traductor sustituido: `guion["entradas_en"]` = índices de vela con entrada encendida."""
    np = pytest.importorskip("numpy")
    from app.services import bot_alerts_engine as eng

    guion: dict = {"entradas_en": set()}

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


def velas_previas(n: int = 30, precio: float = 3.45) -> list[dict]:
    """`n` velas de minuto que terminan a las 09:28 (la de las 09:29 es la de la señal)."""
    import pandas as pd
    t0 = pd.Timestamp("2026-09-25 09:29:00") - pd.Timedelta(minutes=n)
    return [{"timestamp": str(t0 + pd.Timedelta(minutes=i)), "open": precio, "high": precio * 1.01,
             "low": precio * 0.99, "close": precio, "volume": 100000.0} for i in range(n)]


def vela_senal(precio: float = 3.45) -> dict:
    import pandas as pd
    return {"timestamp": pd.Timestamp("2026-09-25 09:29:00"), "open": precio, "high": precio * 1.01,
            "low": precio * 0.99, "close": precio, "volume": 100000.0}


def evento_manual(ticker: str, precio: float = 3.45, stop: float = 4.0) -> Any:
    """Un `Evento` de entrada como los que viajan por la tubería (R-A-05: id = ticker|estrategia|momento|tipo)."""
    import pandas as pd
    from app.services.bot_alerts_engine import Evento
    return Evento(tipo="entrada", ticker=ticker, strategy_id=SID, estrategia=NOMBRE_ESTRATEGIA,
                  momento=pd.Timestamp("2026-09-25 09:29:00"), precio=precio, direccion="Short", acciones=100.0,
                  stop=stop, distancia_stop=stop - precio, riesgo_usd=55.0)


class Vivo:
    """Un ejecutor de producción (`construir_desde_env`) contra el simulador, bombeado desde el test."""

    def __init__(self, e: ej.Ejecutor, sim: SimuladorDAS, libro: LibroSimulado, reloj: RelojSimulado, dir_bot: Path,
                 motor: dict) -> None:
        self.e = e
        self.sim = sim
        self.libro = libro
        self.reloj = reloj
        self.dir_bot = dir_bot
        self.motor = motor

    def paso_hasta(self, cond: Callable[[], bool], que: str, plazo_s: float = PLAZO_S) -> None:
        limite = time.monotonic() + plazo_s
        while not cond():
            if time.monotonic() > limite:
                tipos = [r.tipo for r in self.regs()][-15:]
                pytest.fail(f"plazo vencido esperando: {que}; DAS recibió (últimas) {self.recibidas()[-8:]}; "
                            f"pendientes de enviar {getattr(self.e.cliente, 'pendientes', '?')}; diario {tipos}")
            codigo = self.e.paso(0.02)
            assert codigo is None, f"el ejecutor salió con {codigo} esperando {que}"

    def recibidas(self) -> list[str]:
        return self.sim.recibidas()

    def regs(self) -> list[Registro]:
        return registros(self.dir_bot)

    def radar(self, ticker: str, acciones: float = 1000.0) -> None:
        self.e.buzon.al_senal(Senal(clase="radar", ticker=ticker, id=None, recibida_en=self.reloj.mono(),
                                    estimacion=[{"strategy_id": SID, "acciones": acciones, "riesgo_usd": 300.0}],
                                    precio_radar=D("3.45"), origen="proceso"))

    def locate_listo(self, ticker: str) -> bool:
        loc = self.e.decisor.estado.locates.get((ticker, SID))
        return loc is not None and loc.estado == "Located" and loc.localizadas > 0

    def senal_por_vela(self, ticker: str) -> None:
        """La señal de VERDAD: `FuenteEnProceso.hidratar` + la vela de las 09:29 con la entrada encendida (motor falso)."""
        self.motor["entradas_en"] = set()
        self.e.fuente.hidratar(ticker, velas_previas())
        self.motor["entradas_en"] = {30}
        self.e.fuente.vela(ticker, vela_senal())

    def preparar(self, *tickers: str) -> None:
        """Cotiza, arranca (F12 completo contra el simulador), mete los tickers en el radar y compra sus locates (F9)."""
        for t in tickers:
            self.libro.cotizar(t, D("3.44"), D("3.46"), last=D("3.45"), volumen=500_000, vwap=D("3.40"))
        assert self.e.arrancar() == ej.CODIGO_OK
        assert self.e.decisor.estado.reconciliacion_ok_en is not None
        for i, t in enumerate(tickers):
            if i:
                # cuota GLOBAL del SLPRICEINQUIRE: 1 cada 3 s al 90 % = 1 cada 3,33 s del reloj inyectado (riesgo 36)
                self.reloj.avanzar(LOCATES_INQUIRE_S / 0.9 + 0.1)
            self.radar(t)
            self.paso_hasta(lambda t=t: self.locate_listo(t), f"locate de {t}")
            self.paso_hasta(lambda t=t: self.e.mercado.cotizacion(t) is not None, f"cotización de {t}")
        self.drenar()

    def drenar(self, quieto_s: float = 0.3) -> None:
        """Procesa todo lo que llegue hasta que DAS lleve `quieto_s` reales callado (con el reloj parado no hay temporizadores):
        así el siguiente mensaje que entre en la cola es el PRIMERO que decide el decisor (respuestas de barridos incluidas)."""
        limite = time.monotonic() + PLAZO_S
        callado_desde = time.monotonic()
        while time.monotonic() - callado_desde < quieto_s:
            if time.monotonic() > limite:
                pytest.fail("DAS no deja de hablar")
            seq = self.e.diario.seq
            habia = self.e.buzon.tamano()
            assert self.e.paso(0.02) is None
            if habia or self.e.diario.seq != seq:
                callado_desde = time.monotonic()

    def stops_vivos(self, ticker: str = TICKER) -> list[dict]:
        return [o for o in self.libro.ordenes() if o["ticker"] == ticker and o["tipo"] == "STOPLMTP"
                and o["estado"] in ("Accepted", "Partial")]


@pytest.fixture
def vivo(cfg: Config, reloj: RelojSimulado, dir_bot: Path, libro: LibroSimulado, simulador: SimuladorDAS,
         direccion_simulador: tuple[str, int], motor_falso: dict, monkeypatch: pytest.MonkeyPatch):
    """Fábrica de `Vivo`: entorno de DAS inventado apuntando al simulador y `BOT_DAS_FUENTE=proceso`."""
    host, puerto = direccion_simulador
    for nombre, valor in {"DAS_API_HOST": host, "DAS_API_PORT": str(puerto), "DAS_USUARIO": USUARIO,
                          "DAS_CLAVE": CLAVE_DAS, "DAS_CUENTA": CUENTA, "BOT_DAS_FUENTE": ej.FUENTE_PROCESO}.items():
        monkeypatch.setenv(nombre, valor)
    creados: list[Vivo] = []

    def crear(fase: Fase = Fase.CANARIO, permitir: bool = True, config: Optional[Config] = None) -> Vivo:
        if permitir:
            monkeypatch.setenv("BOT_DAS_PERMITIR_ORDENES", "1")
        c = dataclasses.replace(config if config is not None else cfg, fase=fase)
        e = ej.construir_desde_env(c, reloj, BACKEND, referencia=ReferenciaFalsa(), calendario=CalendarioPrueba(),
                                   hash_motor=lambda base: c.motor_hash, medir_desvio=lambda: 0.0, canales=[])
        v = Vivo(e, simulador, libro, reloj, dir_bot, motor_falso)
        creados.append(v)
        return v

    yield crear
    for v in creados:
        v.e.parar()


def test_canario_entrada_fills_stops_residentes_el_stop_dispara_y_limpieza(vivo) -> None:
    """F1 + F2 + R-C-11 de punta a punta por el socket: señal de la vela → SS agregar → fill → UN stop STOPLMTP
    residente en DAS (stop único, Jaume 29-sep: disparo en L, límite L + 50 %) → el stop dispara → neta 0 → CANCEL
    ALLSYMB."""
    v = vivo(Fase.CANARIO)
    v.preparar(TICKER)
    regs = v.regs()
    assert de_tipo(regs, "reconciliacion")[0].seq < de_tipo(regs, "ejecutor_listo")[0].seq    # R-J-02.5
    assert len([linea for linea in v.recibidas() if linea.startswith("SLNEWORDER")]) == 1
    v.senal_por_vela(TICKER)
    v.paso_hasta(lambda: neworders(v.recibidas(), "SS", TICKER), "NEWORDER SS")
    entrada = neworders(v.recibidas(), "SS", TICKER)
    assert len(entrada) == 1 and entrada[0].endswith("SAGEREB 100 3.45 PostOnly TIF=DAY+")
    v.sim.cotizar(TICKER, D("3.45"), D("3.47"), last=D("3.45"), volumen=500_000)
    v.paso_hasta(lambda: len(v.stops_vivos()) == 1, "el stop único residente")
    assert v.libro.posiciones() == {TICKER: -100}
    (stop,) = v.stops_vivos()
    assert (stop["qty"], stop["ruta"]) == (100, "SMAT")
    assert stop["precio"] == stop["stop"] * D("1.5")                                # R-C-01 v4: límite L + 50 %
    assert v.e.decisor.estado.posiciones[TICKER].neta_fills == -100
    v.sim.cotizar(TICKER, stop["stop"] + D("0.05"), stop["stop"] + D("0.10"),
                  last=stop["stop"] + D("0.10"), volumen=500_000)
    v.paso_hasta(lambda: v.libro.posiciones().get(TICKER) == 0 and not v.stops_vivos(), "stop disparado y limpieza")
    # R-C-11 (a): con el stop único no queda ninguna orden viva tras su fill (en v3 caía la emergencia sobrante)
    assert not [o for o in v.libro.ordenes() if o["estado"] == "Accepted"]
    estados = {o["token"]: o["estado"] for o in v.libro.ordenes()}
    assert estados[stop["token"]] == "Executed"
    assert len(neworders(v.recibidas(), "B", TICKER)) == 1                  # una sola compra: nunca dos stops
    regs = v.regs()
    for linea in neworders(v.recibidas()):                               # M6: cada NEWORDER con su intención y su envío
        token = int(linea.split()[1])
        assert [r for r in de_tipo(regs, "orden_intencion") if r.datos["token"] == token]
        assert [r for r in de_tipo(regs, "orden_enviada") if r.datos["token"] == token]
    assert not de_tipo(regs, "orden_simulada") and not de_tipo(regs, "excepcion")
    assert v.sim.errores() == []


def test_sombra_ni_un_mutante_llega_a_das_y_el_diario_lleva_orden_simulada(vivo) -> None:
    """R-O-03 / §9: en SOMBRA (aunque BOT_DAS_PERMITIR_ORDENES=1) el DAS solo recibe LOGIN/GET/SB/consultas;
    los mutantes van al emparejador y el diario los registra como `orden_simulada` con sus fills."""
    v = vivo(Fase.SOMBRA, permitir=True)
    assert isinstance(v.e.cliente, ClienteSombra) and v.e.cliente.real.solo_lectura
    v.libro.sembrar_posicion("ZZZ", -50, D("2.00"))                  # la cuenta REAL no es la de la sombra
    v.preparar(TICKER)
    v.senal_por_vela(TICKER)
    v.paso_hasta(lambda: de_tipo(v.regs(), "orden_simulada"), "orden_simulada de la entrada")
    v.sim.cotizar(TICKER, D("3.45"), D("3.47"), last=D("3.45"), volumen=500_000)
    libro_sombra = v.e.cliente.emparejador.libro
    v.paso_hasta(lambda: len([o for o in libro_sombra.ordenes() if o["tipo"] == "STOPLMTP"
                              and o["estado"] == "Accepted"]) == 1, "stop simulado (único, Jaume 29-sep)")
    assert libro_sombra.posiciones() == {TICKER: -100}
    assert v.libro.posiciones() == {"ZZZ": -50} and v.libro.ordenes() == []     # el DAS de verdad: intacto
    mutantes = [linea for linea in v.recibidas() if protocolo.es_mutante(linea)]
    assert mutantes == []
    regs = v.regs()
    simuladas = de_tipo(regs, "orden_simulada")
    assert len(simuladas) >= 2 and not de_tipo(regs, "orden_enviada")          # entrada + el stop único
    fills = de_tipo(regs, "fill")
    assert fills and all(f.datos["simulado"] is True for f in fills)
    assert "ZZZ" not in v.e.decisor.estado.posiciones                          # R-O-03: la cuenta de la sombra manda
    assert de_tipo(regs, "sombra_ignorado")


def test_sombra_no_se_construye_con_dinero_aunque_este_la_llave(vivo) -> None:
    """Corrección 15 / tercer candado: fase SOMBRA ⇒ `ClienteSombra` sobre un cliente de SOLO LECTURA, siempre."""
    v = vivo(Fase.SOMBRA, permitir=True)
    assert isinstance(v.e.cliente, ClienteSombra)
    assert v.e.cliente.real.solo_lectura is True and v.e.sombra is True
    with pytest.raises(EnvioProhibido):
        v.e.cliente.real.enviar("NEWORDER 1 SS XYZ SAGEREB 100 3.45 TIF=DAY+")


def test_m6_el_das_recibe_cada_neworder_con_su_intencion_ya_en_disco(cfg: Config, reloj: RelojSimulado,
                                                                    dir_bot: Path, motor_falso: dict,
                                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    """M6 / riesgo 3 medido DESDE DAS: en el instante en que el simulador recibe un NEWORDER, su `orden_intencion` ya está."""
    ruta = dir_bot / "diario" / nombre_fichero("ejecutor", HOY)
    vistos: list[tuple[int, bool]] = []

    class EmparejadorEspia(Emparejador):
        def recibir(self, linea: str) -> list[str]:
            if linea.upper().startswith("NEWORDER"):
                token = int(linea.split()[1])
                vistos.append((token, any(r.get("tipo") == "orden_intencion" and r["datos"].get("token") == token
                                          for r in lineas_jsonl(ruta))))
            return super().recibir(linea)

    libro = LibroSimulado()
    sim = SimuladorDAS(libro, reloj, emparejador=EmparejadorEspia(libro, reloj))
    host, puerto = sim.arrancar()
    try:
        for nombre, valor in {"DAS_API_HOST": host, "DAS_API_PORT": str(puerto), "DAS_USUARIO": USUARIO,
                              "DAS_CLAVE": CLAVE_DAS, "DAS_CUENTA": CUENTA, "BOT_DAS_FUENTE": ej.FUENTE_PROCESO,
                              "BOT_DAS_PERMITIR_ORDENES": "1"}.items():
            monkeypatch.setenv(nombre, valor)
        c = dataclasses.replace(cfg, fase=Fase.CANARIO)
        e = ej.construir_desde_env(c, reloj, BACKEND, referencia=ReferenciaFalsa(), calendario=CalendarioPrueba(),
                                   hash_motor=lambda base: c.motor_hash, medir_desvio=lambda: 0.0, canales=[])
        v = Vivo(e, sim, libro, reloj, dir_bot, motor_falso)
        try:
            v.preparar(TICKER)
            v.senal_por_vela(TICKER)
            v.paso_hasta(lambda: neworders(sim.recibidas(), "SS"), "NEWORDER SS")
            sim.cotizar(TICKER, D("3.45"), D("3.47"), last=D("3.45"), volumen=500_000)
            v.paso_hasta(lambda: len(v.stops_vivos()) == 1, "stop")
        finally:
            e.parar()
    finally:
        sim.parar()
    assert len(vistos) == 2 and all(ok for _, ok in vistos), vistos          # entrada + el stop único (Jaume 29-sep)


def test_correccion4_diario_bloqueado_a_mitad_no_abre_pero_los_stops_salen(vivo) -> None:
    """Corrección 4 / riesgo 23 de punta a punta: con el diario bloqueado, la entrada de ABC NO llega a DAS (0 NEWORDER SS)
    y el stop de XYZ que DAS canceló por su cuenta SÍ se repone (NEWORDER B STOPLMTP); al volver el disco, todo al fichero."""
    v = vivo(Fase.CANARIO)
    v.preparar(TICKER, OTRO)
    v.senal_por_vela(TICKER)
    v.paso_hasta(lambda: neworders(v.recibidas(), "SS", TICKER), "entrada de XYZ")
    v.sim.cotizar(TICKER, D("3.45"), D("3.47"), last=D("3.45"), volumen=500_000)
    v.paso_hasta(lambda: len(v.stops_vivos()) == 1, "stop de XYZ")
    (stop,) = v.stops_vivos()
    n_stops = len(neworders(v.recibidas(), "B", TICKER))
    v.drenar()                                        # el decisor decidirá la señal de ABC con el diario aún «sano»
    with diario_bloqueado(v.e.diario.ruta):
        v.e.buzon.al_senal(Senal(clase="evento", ticker=OTRO, id=f"{OTRO}|{SID}|2026-09-25 09:29:00|entrada",
                                 evento=evento_manual(OTRO), momento=evento_manual(OTRO).momento,
                                 recibida_en=v.reloj.mono(), origen="tuberia"))
        v.paso_hasta(lambda: v.e.decisor.estado.posiciones.get(OTRO) is not None
                     and v.e.decisor.estado.posiciones[OTRO].lotes, "la señal de ABC decidida")
        v.paso_hasta(lambda: v.e.diario.degradado, "diario degradado")
        for linea in v.sim.emparejador.recibir(f"CANCEL {stop['id']}"):          # DAS lo cancela por su cuenta
            v.sim.emitir(linea)
        v.paso_hasta(lambda: len(neworders(v.recibidas(), "B", TICKER)) > n_stops, "reposición del stop")
        v.paso_hasta(lambda: len(v.stops_vivos()) == 1, "el stop repuesto")
        assert neworders(v.recibidas(), "SS", OTRO) == []
        assert v.e.diario.degradado
    v.e.buzon.poner(Tic())
    v.paso_hasta(lambda: not v.e.diario.degradado, "el diario vuelve")
    regs = v.regs()
    bloqueadas = [r for r in de_tipo(regs, "senal_descartada") if r.datos.get("regla") == "corrección 4"]
    assert len(bloqueadas) == 1 and bloqueadas[0].datos["ticker"] == OTRO
    assert len([r for r in de_tipo(regs, "aviso") if r.datos.get("clave") == "disco_ejecutor"]) == 1
    repuesto = neworders(v.recibidas(), "B", TICKER)[-1]
    token = int(repuesto.split()[1])
    assert [r for r in de_tipo(regs, "orden_intencion") if r.datos["token"] == token]     # se volcó al volver
    assert neworders(v.recibidas(), "SS", OTRO) == []


@pytest.mark.parametrize("grupo_a", [False, True], ids=["R-M-05-sin-grupo-A", "R-M-05-con-grupo-A"])
def test_r_m_05_metrica_senal_a_orden_con_y_sin_grupo_a(vivo, cfg: Config, grupo_a: bool) -> None:
    """R-M-05 / corrección 18: `metrica{senal_a_orden_ms}` en el diario con y sin grupo A; con A, su aviso va ANTES de la orden."""
    config = cfg
    if grupo_a:
        estrategia = dataclasses.replace(cfg.estrategias[SID], avisar_grupo_a=True)
        config = dataclasses.replace(cfg, alertas_grupo_a={**cfg.alertas_grupo_a, "activo": True},
                                     estrategias={SID: estrategia})
    v = vivo(Fase.CANARIO, config=config)
    v.preparar(TICKER)
    v.senal_por_vela(TICKER)
    v.paso_hasta(lambda: neworders(v.recibidas(), "SS"), "NEWORDER SS")
    regs = v.regs()
    metricas = [r for r in de_tipo(regs, "metrica") if r.datos.get("nombre") == "senal_a_orden_ms"]
    assert len(metricas) == 1
    valor = metricas[0].datos["valor"]
    assert isinstance(valor, (int, float)) and valor >= 0
    avisos_a = [r for r in de_tipo(regs, "aviso") if r.datos.get("grupo") == "A"]
    intencion = [r for r in de_tipo(regs, "orden_intencion") if r.datos["proposito"] == "entrada_agregar"][0]
    if grupo_a:
        assert len(avisos_a) == 1 and TICKER in avisos_a[0].datos["texto"] and avisos_a[0].seq < intencion.seq
    else:
        assert avisos_a == []


def test_r_o_02_replay_de_una_grabacion_avanza_el_reloj_y_termina(cfg: Config, dir_bot: Path, libro: LibroSimulado,
                                                                simulador: SimuladorDAS,
                                                                direccion_simulador: tuple[str, int],
                                                                motor_falso: dict,
                                                                monkeypatch: pytest.MonkeyPatch) -> None:
    """R-O-02: con `BOT_DAS_FUENTE=grabacion=…` el reloj simulado avanza vela a vela (o hasta el próximo temporizador),
    cada vela pasa por el gancho del guion, las señales llegan al decisor y, agotada la grabación, `correr()` devuelve 0.
    El ritmo lo marca el reloj simulado: 3 h 40 min de grabación en segundos reales."""
    reloj = RelojSimulado(datetime(2026, 9, 25, 3, 55, tzinfo=ET))
    host, puerto = direccion_simulador
    ruta_am = Path(__file__).parent / "fixtures" / "AM_recorte.jsonl.gz"
    for nombre, valor in {"DAS_API_HOST": host, "DAS_API_PORT": str(puerto), "DAS_USUARIO": USUARIO,
                          "DAS_CLAVE": CLAVE_DAS, "DAS_CUENTA": CUENTA, "BOT_DAS_FUENTE": f"grabacion={ruta_am}"}.items():
        monkeypatch.setenv(nombre, valor)
    motor_falso["entradas_en"] = {5}
    vistas: list[tuple[datetime, str]] = []
    c = dataclasses.replace(cfg, fase=Fase.SOMBRA)
    e = ej.construir_desde_env(c, reloj, BACKEND, referencia=ReferenciaFalsa(), calendario=CalendarioPrueba(),
                               hash_motor=lambda base: c.motor_hash, medir_desvio=lambda: 0.0, canales=[],
                               paso_replay=lambda t, vela: vistas.append((t, vela["ticker"])))
    inicio = time.monotonic()
    try:
        assert e.arrancar() == ej.CODIGO_OK
        assert e.correr() == ej.CODIGO_OK
    finally:
        e.parar()
    assert time.monotonic() - inicio < 30.0
    assert len(vistas) == 120 and [t for t, _ in vistas] == sorted(t for t, _ in vistas)
    assert reloj.ahora() >= datetime(2026, 9, 25, 7, 41, tzinfo=ET)
    regs = registros(dir_bot)
    assert de_tipo(regs, "fin_grabacion")[0].datos["aplicadas"] == 120
    assert de_tipo(regs, "salir")[-1].datos["codigo"] == 0
    decididas = de_tipo(regs, "senal") + de_tipo(regs, "senal_descartada")   # sin cotización de DAS: descartadas
    assert {r.datos.get("ticker") for r in decididas} >= {"INLF", "CTNT", "MGLD"}
    assert [r for r in de_tipo(regs, "feed") if r.datos.get("nivel") == "ok"]     # F11 b: latido de la grabación
    assert not [linea for linea in simulador.recibidas() if protocolo.es_mutante(linea)]


def test_g2_06_replay_con_la_cotizacion_de_la_vela_ya_no_descarta_por_falta_de_cotizacion(
        cfg: Config, dir_bot: Path, libro: LibroSimulado, simulador: SimuladorDAS,
        direccion_simulador: tuple[str, int], motor_falso: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    """G2-06 (R-O-02): el gancho del guion devuelve las líneas de DAS de la vela (`SimuladorDAS.desde_vela`) y el
    ejecutor aplica su `$Quote` ANTES de entregar la señal: ninguna entrada se descarta «sin cotización fresca de DAS»
    (antes era el destino de TODAS); en el recorte, sin radar ni locates, pasan esa puerta y caen en la de locates."""
    from app.bot_das.simulador_das import ProgramaGuion
    reloj = RelojSimulado(datetime(2026, 9, 25, 3, 55, tzinfo=ET))
    host, puerto = direccion_simulador
    ruta_am = Path(__file__).parent / "fixtures" / "AM_recorte.jsonl.gz"
    for nombre, valor in {"DAS_API_HOST": host, "DAS_API_PORT": str(puerto), "DAS_USUARIO": USUARIO,
                          "DAS_CLAVE": CLAVE_DAS, "DAS_CUENTA": CUENTA, "BOT_DAS_FUENTE": f"grabacion={ruta_am}"}.items():
        monkeypatch.setenv(nombre, valor)
    motor_falso["entradas_en"] = {5}
    programa = ProgramaGuion({})
    c = dataclasses.replace(cfg, fase=Fase.SOMBRA)
    e = ej.construir_desde_env(c, reloj, BACKEND, referencia=ReferenciaFalsa(), calendario=CalendarioPrueba(),
                               hash_motor=lambda base: c.motor_hash, medir_desvio=lambda: 0.0, canales=[],
                               paso_replay=lambda t, vela: simulador.desde_vela(vela["ticker"], vela, programa.spread))
    try:
        assert e.arrancar() == ej.CODIGO_OK
        assert e.correr() == ej.CODIGO_OK
    finally:
        e.parar()
    regs = registros(dir_bot)
    motivos = [str(r.datos.get("motivo", "")) for r in de_tipo(regs, "senal_descartada")]
    assert motivos and not [m for m in motivos if "cotiz" in m.lower()], motivos
    assert not [linea for linea in simulador.recibidas() if protocolo.es_mutante(linea)]


def test_r2_pro_4_replay_con_locate_already_shortable_entra_llena_pone_stops_y_sale_por_stop(
        cfg: Config, dir_bot: Path, libro: LibroSimulado, simulador: SimuladorDAS,
        direccion_simulador: tuple[str, int], motor_falso: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    """R2-PRO-4 (G2-06): replay de la grabación recortada con el DAS simulado respondiendo al SLPRICEINQUIRE con
    `%SLRET 2 … AlreadyShortable`: UNA señal entra de punta a punta en SOMBRA.

    El radar de INLF se inyecta a las 04:29 (la grabación no trae radar): SLPRICEINQUIRE → ETB, «no hace falta»
    locate. La vela 30 (04:31) enciende la entrada (motor falso) → SS agregar → fill simulado → el stop único (máximo
    previo + 1 % = 5,70; límite + 50 %, Jaume 29-sep) → INLF sube a 5,89 en las 04:38 → el stop dispara → neta 0 → CANCEL
    ALLSYMB. El test se
    corta al acabar INLF (04:41) para no recorrer el hueco hasta MGLD. Sin fichero `esperado_*`."""
    from app.bot_das.simulador_das import ProgramaGuion
    reloj = RelojSimulado(datetime(2026, 9, 25, 3, 55, tzinfo=ET))
    host, puerto = direccion_simulador
    ruta_am = Path(__file__).parent / "fixtures" / "AM_recorte.jsonl.gz"
    for nombre, valor in {"DAS_API_HOST": host, "DAS_API_PORT": str(puerto), "DAS_USUARIO": USUARIO,
                          "DAS_CLAVE": CLAVE_DAS, "DAS_CUENTA": CUENTA, "BOT_DAS_FUENTE": f"grabacion={ruta_am}"}.items():
        monkeypatch.setenv(nombre, valor)
    libro.configurar_locate("INLF", fallo="AlreadyShortable")
    motor_falso["entradas_en"] = {30}                     # la vela de las 04:31 (cierre 5,48; máximo previo 5,6429)
    programa = ProgramaGuion({})
    c = dataclasses.replace(cfg, fase=Fase.SOMBRA)
    caja: dict[str, Any] = {"radar": False}
    radar_en = datetime(2026, 9, 25, 4, 29, tzinfo=ET)    # tarde: con radar hay SymStatus cada 1 s y el replay va lento
    corte = datetime(2026, 9, 25, 4, 41, tzinfo=ET)

    def paso(t: datetime, vela: dict) -> list[str]:
        lineas = simulador.desde_vela(vela["ticker"], vela, programa.spread)
        if vela["ticker"] == "INLF" and not caja["radar"] and t >= radar_en:
            caja["radar"] = True
            caja["e"].buzon.al_senal(Senal(clase="radar", ticker="INLF", id=None, recibida_en=reloj.mono(),
                                           estimacion=[{"strategy_id": SID, "acciones": 1000.0, "riesgo_usd": 300.0}],
                                           precio_radar=D(str(vela["close"])), origen="grabacion"))
        if t >= corte:
            caja["e"].pedir_parada("R2-PRO-4: INLF terminado", ej.CODIGO_OK)
        return lineas

    e = ej.construir_desde_env(c, reloj, BACKEND, referencia=ReferenciaFalsa(), calendario=CalendarioPrueba(),
                               hash_motor=lambda base: c.motor_hash, medir_desvio=lambda: 0.0, canales=[],
                               paso_replay=paso)
    caja["e"] = e
    try:
        assert e.arrancar() == ej.CODIGO_OK
        assert e.correr() == ej.CODIGO_OK
        libro_sombra = e.cliente.emparejador.libro
    finally:
        e.parar()
    regs = [r for r in registros(dir_bot) if r.datos.get("ticker") == "INLF"]
    assert [r.datos["estado"] for r in de_tipo(regs, "locate_estado")] == ["no_hace_falta"]
    assert len(de_tipo(regs, "senal")) == 1 and not de_tipo(regs, "senal_descartada")
    intenciones = [(r.datos["proposito"], r.datos["lado"], r.datos["tipo_orden"]) for r in de_tipo(regs, "orden_intencion")]
    assert intenciones == [("entrada_agregar", "SS", "LMT"), ("stop", "B", "STOPLMTP")]   # stop único (Jaume 29-sep)
    fills = [(r.datos["proposito"], r.datos["neta_fills"]) for r in de_tipo(regs, "fill") if not r.datos.get("eco")]
    assert fills == [("entrada_agregar", -100), ("stop", 0)]
    cerrada = de_tipo(regs, "posicion_cerrada")
    assert len(cerrada) == 1 and D(cerrada[0].datos["resultado"]) < 0                  # salió por el stop, perdiendo
    assert [r for r in de_tipo(regs, "cancel_intencion") if r.datos.get("linea") == "CANCEL ALLSYMB INLF"]
    assert libro_sombra.posiciones().get("INLF") == 0
    assert e.decisor.estado.posiciones["INLF"].neta_fills == 0
    assert [linea for linea in simulador.recibidas() if linea.startswith("SLPRICEINQUIRE INLF ")]  # al DAS real
    assert not [linea for linea in simulador.recibidas() if protocolo.es_mutante(linea)]          # sombra: nada muta


# ═══════════════════════════ 5. reinicio a mitad (H-2) en subprocesos ═════
DRIVER = r"""
import sys, time
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
backend = sys.argv[1]
sys.path.insert(0, backend)
from app.bot_das import avisos as mod_avisos, config as mod_config, ejecutor as ej
from app.bot_das.reloj import ET, Reloj
from app.bot_das.tipos import Ficha

ANCLA_ET = datetime.fromisoformat(sys.argv[2])
ANCLA_EPOCH = float(sys.argv[3])


class RelojDesplazado(Reloj):
    # El reloj real corrido al día de la prueba: los dos procesos comparten el ancla (diario ordenado).
    def ahora(self):
        return (ANCLA_ET + timedelta(seconds=time.time() - ANCLA_EPOCH)).astimezone(ET)


class Calendario:
    def franja_de_mercado(self, ahora):
        m = ahora.hour * 60 + ahora.minute
        return "RTH" if 570 <= m < 960 else ("premercado" if 240 <= m < 570 else "cerrado")

    def media_sesion(self, dia):
        return None


class Referencia:
    def ficha(self, ticker):
        return Ficha(ticker, date(2020, 1, 1), "1234", "CS", Decimal("100000000"), "Prueba SA")

    def splits_de_hoy(self, dia):
        return set()


reloj = RelojDesplazado()
dir_bot = ej.directorio_bot()
mod_avisos.instalar_logging("ejecutor", dir_bot / "logs", mod_avisos.secretos_desde_env(), reloj=reloj)
cfg, aviso = mod_config.cargar_con_respaldo(dir_bot / "config" / mod_config.NOMBRE_FICHERO_CONFIG,
                                            dir_bot / "config" / mod_config.NOMBRE_ULTIMO_BUENO, "CUENTA_PRUEBA")
e = ej.construir_desde_env(cfg, reloj, Path(backend), referencia=Referencia(), calendario=Calendario(),
                           hash_motor=lambda base: cfg.motor_hash, medir_desvio=lambda: 0.0, canales=[],
                           aviso_config=aviso)
codigo = e.arrancar()
try:
    if codigo == 0:
        codigo = e.correr()
finally:
    e.parar()
    mod_avisos.desinstalar_logging()
sys.exit(codigo)
"""


def _puerto_libre() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Hijo:
    """Un ejecutor en un subproceso (Popen del lanzador del venv) con sus salidas a ficheros."""

    def __init__(self, dir_bot: Path, env: dict, ancla: tuple[str, float], n: int) -> None:
        self.dir_bot = dir_bot
        self.salida = dir_bot / "logs" / f"hijo_{n}.txt"
        self._f = open(self.salida, "w", encoding="utf-8")
        self.proc = subprocess.Popen([sys.executable, "-c", DRIVER, str(BACKEND), ancla[0], repr(ancla[1])],
                                     cwd=str(BACKEND), env=env, stdout=self._f, stderr=subprocess.STDOUT)

    def diario(self) -> list[dict]:
        return lineas_jsonl(self.dir_bot / "diario" / nombre_fichero("ejecutor", HOY))

    def texto(self) -> str:
        try:
            return self.salida.read_text(encoding="utf-8", errors="replace")[-3000:]
        except OSError:
            return ""

    def matar(self) -> None:
        """Muerte súbita (TerminateProcess) del intérprete REAL, por el PID de su cerrojo (trampa del lanzador)."""
        pid = CerrojoInstancia.pid_guardado(self.dir_bot / "estado" / ej.NOMBRE_CERROJO)
        if pid is not None and pid != os.getpid():
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass
        self.esperar_fin(10.0)

    def esperar_fin(self, plazo_s: float) -> Optional[int]:
        try:
            return self.proc.wait(timeout=plazo_s)
        except subprocess.TimeoutExpired:
            return None

    def cerrar(self) -> None:
        if self.proc.poll() is None:
            self.matar()
        if self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait(timeout=5)
        self._f.close()


def _esperar(cond: Callable[[], bool], que: str, hijo: Optional[Hijo] = None, plazo_s: float = 25.0) -> None:
    limite = time.monotonic() + plazo_s
    while not cond():
        if hijo is not None and hijo.proc.poll() is not None:
            pytest.fail(f"el hijo murió (código {hijo.proc.returncode}) esperando {que}:\n{hijo.texto()}")
        if time.monotonic() > limite:
            pytest.fail(f"plazo vencido esperando {que}:\n{hijo.texto() if hijo else ''}")
        time.sleep(0.05)


def test_h2_reinicio_a_mitad_no_reentra_ni_recompra(cfg: Config, reloj: RelojSimulado, dir_bot: Path,
                                                    libro: LibroSimulado, simulador: SimuladorDAS,
                                                    direccion_simulador: tuple[str, int]) -> None:
    """H-2 / F13 / R-A-05 / R-H-02: un ejecutor en subproceso compra locates, entra y pone stops; se le MATA; el
    segundo, con el mismo BOT_DAS_DIR, reconstruye del diario: ante el MISMO radar y la MISMA señal no recompra ni
    reentra, adopta los stops (0 órdenes nuevas) y para ordenado con `{"parar": true}` del supervisor."""
    from app.bot_das.enlace_bot_alertas import EnlaceEjecutor

    crudo = json.loads(RUTA_CONFIG_EJEMPLO.read_text(encoding="utf-8"))
    crudo["fase"] = "canario"
    mod_config.escribir_atomico(dir_bot / "config" / mod_config.NOMBRE_FICHERO_CONFIG, crudo)
    libro.cotizar(TICKER, D("3.44"), D("3.46"), last=D("3.45"), volumen=500_000, vwap=D("3.40"))
    host, puerto = direccion_simulador
    puerto_tuberia = _puerto_libre()
    env = dict(os.environ)
    env.update({"DAS_API_HOST": host, "DAS_API_PORT": str(puerto), "DAS_USUARIO": USUARIO, "DAS_CLAVE": CLAVE_DAS,
                "DAS_CUENTA": CUENTA, "BOT_DAS_DIR": str(dir_bot), "BOT_DAS_FUENTE": ej.FUENTE_TUBERIA,
                "BOT_DAS_TUBERIA": f"127.0.0.1:{puerto_tuberia}", "BOT_DAS_AUTHKEY": AUTHKEY,
                "BOT_DAS_PERMITIR_ORDENES": "1", "PYTHONIOENCODING": "utf-8"})
    ancla = (INICIO.isoformat(), time.time())
    motor_hash = mod_config.cargar(dir_bot / "config" / mod_config.NOMBRE_FICHERO_CONFIG, CUENTA).motor_hash
    enlace = EnlaceEjecutor(("127.0.0.1", puerto_tuberia), AUTHKEY, version=VERSION, motor_hash=motor_hash,
                            reconectar_s=0.2, espera_ok_s=3.0)
    radar = [{"ticker": TICKER, "precio": 3.45,
              "estimacion": [{"nombre": NOMBRE_ESTRATEGIA, "acciones": 1000.0, "riesgo_usd": 300.0}]}]
    nombres = {NOMBRE_ESTRATEGIA: SID}
    evento = evento_manual(TICKER)

    def epoch_hijo() -> float:
        return INICIO.timestamp() + (time.time() - ancla[1])

    def listos() -> int:
        return len([r for r in lineas_jsonl(dir_bot / "diario" / nombre_fichero("ejecutor", HOY))
                    if r.get("tipo") == "ejecutor_listo"])

    hijos: list[Hijo] = []
    try:
        primero = Hijo(dir_bot, env, ancla, 1)
        hijos.append(primero)
        _esperar(lambda: listos() == 1, "arranque del primer ejecutor", primero)
        enlace.arrancar()
        enlace.latido(epoch_hijo(), True)
        enlace.radar(radar, nombres)
        _esperar(lambda: any(linea.startswith("SLNEWORDER") for linea in simulador.recibidas()), "compra de locates",
                 primero)
        _esperar(lambda: any(r.get("tipo") == "locate_estado" and r["datos"].get("estado") == "Located"
                             for r in primero.diario()), "locate Located", primero)
        enlace.eventos(TICKER, "09:29", 0, [evento], False)
        _esperar(lambda: neworders(simulador.recibidas(), "SS", TICKER), "NEWORDER SS", primero)
        simulador.cotizar(TICKER, D("3.45"), D("3.47"), last=D("3.45"), volumen=500_000)
        _esperar(lambda: len([o for o in libro.ordenes() if o["tipo"] == "STOPLMTP" and o["estado"] == "Accepted"])
                 == 1, "stop residente (único, Jaume 29-sep)", primero)
        _esperar(lambda: any(r.get("tipo") == "lote" and r["datos"].get("estado") == "abierto"
                             for r in primero.diario()), "lote abierto en el diario", primero)
        recibidas_antes = simulador.recibidas()
        primero.matar()
        assert primero.proc.poll() is not None

        segundo = Hijo(dir_bot, env, ancla, 2)
        hijos.append(segundo)
        _esperar(lambda: listos() == 2, "arranque del segundo ejecutor", segundo)
        enlace.latido(epoch_hijo(), True)
        enlace.radar(radar, nombres)
        enlace.eventos(TICKER, "09:29", 0, [evento], True)
        _esperar(lambda: [r for r in segundo.diario() if r.get("tipo") == "senal_repetida"], "senal_repetida", segundo)
        time.sleep(1.5)                                    # margen: un barrido y un plan completos del segundo
        nuevas = simulador.recibidas()[len(recibidas_antes):]
        assert [linea for linea in nuevas if linea.startswith("SLNEWORDER")] == []            # R-H-02: no recompra
        assert neworders(nuevas) == []                                                        # H-2: ni reentra ni duplica
        assert libro.posiciones() == {TICKER: -100}
        assert len([o for o in libro.ordenes() if o["tipo"] == "STOPLMTP" and o["estado"] == "Accepted"]) == 1
        diario = segundo.diario()
        reconstruccion = [r for r in diario if r.get("tipo") == "reconstruccion"][-1]["datos"]
        assert reconstruccion["senales_vistas"] >= 1 and TICKER in reconstruccion["posiciones"]
        assert reconstruccion["ultimo_seq_token"] >= 2          # entrada + el stop único (Jaume 29-sep)
        with open(dir_bot / "estado" / ej.NOMBRE_ORDEN_SUPERVISOR, "a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps({"parar": True}) + "\n")
        codigo = segundo.esperar_fin(20.0)
        assert codigo == 0, segundo.texto()
    finally:
        enlace.parar(vaciar_s=0.0, espera_s=2.0)
        for h in hijos:
            h.cerrar()


# ═══════════════════════════ 6. construir_desde_env y main ════════════════
def _entorno_das(monkeypatch: pytest.MonkeyPatch, puerto: int = 50999) -> None:
    for nombre, valor in {"DAS_API_PORT": str(puerto), "DAS_USUARIO": USUARIO, "DAS_CLAVE": CLAVE_DAS,
                          "DAS_CUENTA": CUENTA, "BOT_DAS_AUTHKEY": AUTHKEY}.items():
        monkeypatch.setenv(nombre, valor)


def _construir(cfg: Config, reloj: RelojSimulado, **kw: Any) -> ej.Ejecutor:
    return ej.construir_desde_env(cfg, reloj, BACKEND, referencia=None, canales=[], **kw)


def test_construir_canario_exige_la_llave_de_entorno(cfg: Config, reloj: RelojSimulado,
                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    """Corrección 15 / R-O-03: CANARIO o REAL sin `BOT_DAS_PERMITIR_ORDENES=1` no se construye; con ella, cliente con dinero."""
    _entorno_das(monkeypatch)
    for fase in (Fase.CANARIO, Fase.REAL):
        with pytest.raises(RuntimeError, match="BOT_DAS_PERMITIR_ORDENES"):
            _construir(dataclasses.replace(cfg, fase=fase), reloj)
    monkeypatch.setenv("BOT_DAS_PERMITIR_ORDENES", "1")
    e = _construir(dataclasses.replace(cfg, fase=Fase.CANARIO), reloj)
    assert isinstance(e.cliente, ClienteDAS) and e.cliente.solo_lectura is False and not e.sombra


def test_construir_no_abre_red_ni_hilos_ni_escribe_el_diario(cfg: Config, reloj: RelojSimulado, dir_bot: Path,
                                                             monkeypatch: pytest.MonkeyPatch) -> None:
    """§3.27: construir no conecta, no arranca hilos y no escribe; eso es de `arrancar()`."""
    import threading
    _entorno_das(monkeypatch)
    hilos = threading.active_count()
    e = _construir(cfg, reloj)
    assert threading.active_count() == hilos
    assert not e.cliente.conectado and e.decisor is None
    assert list((dir_bot / "diario").iterdir()) == []
    assert type(e.fuente).__name__ == "FuenteTuberia"                    # defecto: tubería (sin pandas, §8.25)


@pytest.mark.parametrize("valor, clase", [("", "FuenteTuberia"), ("tuberia", "FuenteTuberia"),
                                          ("proceso", "FuenteEnProceso"), ("basura", None),
                                          ("grabacion=", None)],
                         ids=["§3.27-defecto-tuberia", "§3.27-tuberia", "§3.27-proceso", "§3.27-desconocida",
                              "§3.27-grabacion-sin-ruta"])
def test_construir_elige_la_fuente_por_entorno(cfg: Config, reloj: RelojSimulado, monkeypatch: pytest.MonkeyPatch,
                                               valor: str, clase: Optional[str]) -> None:
    _entorno_das(monkeypatch)
    monkeypatch.setenv(ej.ENV_FUENTE, valor)
    if clase is None:
        with pytest.raises(ValueError, match=ej.ENV_FUENTE):
            _construir(cfg, reloj)
        return
    assert type(_construir(cfg, reloj).fuente).__name__ == clase


def test_construir_la_tuberia_exige_authkey(cfg: Config, reloj: RelojSimulado, monkeypatch: pytest.MonkeyPatch) -> None:
    """Riesgo 19: sin `BOT_DAS_AUTHKEY` la tubería no se construye."""
    _entorno_das(monkeypatch)
    monkeypatch.delenv("BOT_DAS_AUTHKEY")
    with pytest.raises(ValueError, match="authkey"):
        _construir(cfg, reloj)


def test_construir_grabacion_con_ruta(cfg: Config, reloj: RelojSimulado, monkeypatch: pytest.MonkeyPatch) -> None:
    _entorno_das(monkeypatch)
    ruta = Path(__file__).parent / "fixtures" / "AM_recorte.jsonl.gz"
    monkeypatch.setenv(ej.ENV_FUENTE, f"grabacion={ruta}")
    fuente = _construir(cfg, reloj).fuente
    assert type(fuente).__name__ == "FuenteGrabacion" and fuente.ruta_am == ruta


def test_construir_grabacion_con_gancho_de_hidratacion(cfg: Config, reloj: RelojSimulado,
                                                       monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensayo 28-sep: `construir_desde_env(hidratar_desde=f)` llega a `FuenteGrabacion` (el pasado de cada ticker, como
    el REST en vivo); sin el gancho la fuente hidrata vacío y la reproducción se queda muda. Con la tubería se ignora."""
    _entorno_das(monkeypatch)
    ruta = Path(__file__).parent / "fixtures" / "AM_recorte.jsonl.gz"
    monkeypatch.setenv(ej.ENV_FUENTE, f"grabacion={ruta}")

    def gancho(ticker: str):
        return [], {"prev_close": 1.0}

    fuente = _construir(cfg, reloj, hidratar_desde=gancho).fuente
    assert type(fuente).__name__ == "FuenteGrabacion" and fuente._hidratar_desde is gancho
    assert _construir(cfg, reloj).fuente._hidratar_desde is None


@pytest.mark.parametrize("token, chats, con_telegram", [
    ("", "111", False), ("token-inventado-b", "", False), ("token-inventado-b", "111, x, 222", True),
], ids=["R-Q-01-sin-token", "R-Q-01-sin-chat-ids", "R-Q-01-token-y-chats"])
def test_construir_telegram_solo_con_token_y_chats_autorizados(cfg: Config, reloj: RelojSimulado,
                                                               monkeypatch: pytest.MonkeyPatch, token: str,
                                                               chats: str, con_telegram: bool) -> None:
    _entorno_das(monkeypatch)
    monkeypatch.setenv(ej.ENV_TOKEN_B, token)
    monkeypatch.setenv(ej.ENV_CHAT_IDS, chats)
    e = _construir(cfg, reloj)
    nombres = [type(r).__name__ for r in e.receptores]
    assert nombres[0] == "LectorComandosFichero"
    assert ("ReceptorTelegram" in nombres) is con_telegram
    if con_telegram:
        assert ej._chat_ids_de_entorno() == frozenset({111, 222})


def test_c_02_el_receptor_de_telegram_persiste_su_offset_en_estado(cfg: Config, reloj: RelojSimulado, dir_bot: Path,
                                                                   monkeypatch: pytest.MonkeyPatch) -> None:
    """C-02: `construir_desde_env` da al `ReceptorTelegram` la ruta `estado/telegram_offset` (lo leído no se repite al
    relanzar el ejecutor: un «/cerrar X N SI» entregado no cierra N acciones más)."""
    from app.bot_das.comandos import FICHERO_OFFSET_TELEGRAM
    _entorno_das(monkeypatch)
    monkeypatch.setenv(ej.ENV_TOKEN_B, "token-inventado-b")
    monkeypatch.setenv(ej.ENV_CHAT_IDS, "111")
    e = _construir(cfg, reloj)
    telegram = [r for r in e.receptores if type(r).__name__ == "ReceptorTelegram"]
    assert len(telegram) == 1 and telegram[0]._ruta_offset == dir_bot / "estado" / FICHERO_OFFSET_TELEGRAM


def test_r2_pro_5_el_offset_de_telegram_sobrevive_al_relanzar_el_ejecutor_solo_con_el_mismo_token(
        cfg: Config, reloj: RelojSimulado, dir_bot: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """R2-PRO-5 (C-02 + R2-CMD-1): lo que guarda el receptor de un ejecutor lo carga el del ejecutor relanzado (mismo
    token, con el reloj del ejecutor como fecha); con OTRO token el fichero se descarta y se empieza en 0."""
    _entorno_das(monkeypatch)
    monkeypatch.setenv(ej.ENV_CHAT_IDS, "111")
    monkeypatch.setenv(ej.ENV_TOKEN_B, "token-inventado-b")

    def receptor() -> Any:
        e = _construir(cfg, reloj)
        return next(r for r in e.receptores if type(r).__name__ == "ReceptorTelegram")

    primero = receptor()
    primero.offset, primero.ultimo_update_id = 58, 57
    primero._guardar_offset()
    reloj.avanzar(3600.0)
    relanzado = receptor()
    assert (relanzado.offset, relanzado.ultimo_update_id) == (58, 57)
    monkeypatch.setenv(ej.ENV_TOKEN_B, "otro-token-inventado")
    assert receptor().offset == 0


def test_r2_pro_5_la_tuberia_exige_la_version_del_paquete(cfg: Config, reloj: RelojSimulado,
                                                          monkeypatch: pytest.MonkeyPatch) -> None:
    """R2-PRO-5 (R2-FUE-1): `construir_desde_env` monta la tubería con `version_minima = VERSION`: un bot.py con el
    enlace anterior se rechaza en el «hola» en vez de pasar y perder sus eventos en silencio."""
    from app.bot_das.fuente_senales import FuenteTuberia
    _entorno_das(monkeypatch)
    monkeypatch.setenv(ej.ENV_FUENTE, ej.FUENTE_TUBERIA)
    e = _construir(cfg, reloj)
    assert isinstance(e.fuente, FuenteTuberia) and e.fuente.version_minima == VERSION


def test_r2_pro_5_el_temporizador_exceso_verificar_llega_al_decisor(montar) -> None:
    """R2-PRO-5 (D2a-04 / R2-STOPS-2): `Programar("exceso_verificar:X")` del decisor pasa por el heap del ejecutor y,
    al vencer, lo atiende el decisor (no es un «temporizador_desconocido»)."""
    from app.bot_das.reglas import stops as reglas_stops
    m = montar()
    clave = reglas_stops.clave_exceso_verificar(TICKER)
    m.e.ejecutar(Programar(clave, reglas_stops.EXCESO_VERIFICAR_EN_S, {"ticker": TICKER, "persecuciones": 0}))
    m.reloj.avanzar(reglas_stops.EXCESO_VERIFICAR_EN_S + 0.1)
    m.pasos(2)
    assert not [r for r in de_tipo(m.regs(), "temporizador_desconocido") if r.datos.get("clave") == clave]
    assert not de_tipo(m.regs(), "excepcion")


def test_r2_pro_5_cancelar_al_tener_id_del_decisor_queda_en_el_diario(montar) -> None:
    """R2-PRO-5 (R2-DEC-4): el `Anotar("cancelar_al_tener_id")` que el decisor deja pasar llega al diario del ejecutor
    tal cual (lo lee el vigilante y la persona) y no sale nada hacia DAS."""
    m = montar()
    antes = [t for t in m.traza if t[0] == "enviar"]
    m.e.ejecutar(Anotar("cancelar_al_tener_id", {"token": 126800007, "ticker": TICKER, "proposito": "entrada_agregar",
                                                 "qty": 100, "motivo": "R-C-11 (3)", "regla": "R2-STOPS-1"}))
    registro = de_tipo(m.regs(), "cancelar_al_tener_id")
    assert len(registro) == 1 and registro[0].datos["token"] == 126800007
    assert [t for t in m.traza if t[0] == "enviar"] == antes


def test_main_sin_cuenta_sale_con_5_sin_tocar_el_env_real(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """R-Q-01: `main` carga SOLO el `.env` de `RUTA_DOTENV` (aquí, inexistente); sin DAS_CUENTA → código 5 y logging retirado."""
    monkeypatch.setattr(ej, "RUTA_DOTENV", tmp_path / "no_existe.env")
    raiz = logging.getLogger()
    antes = list(raiz.handlers)
    assert ej.main([]) == ej.CODIGO_CONFIG
    assert "DAS_CUENTA" not in os.environ
    assert list(raiz.handlers) == antes


def test_main_con_config_inexistente_sale_con_5(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ej, "RUTA_DOTENV", tmp_path / "no_existe.env")
    monkeypatch.setenv("DAS_CUENTA", CUENTA)
    assert ej.main(["--config", str(tmp_path / "no_hay.json")]) == ej.CODIGO_CONFIG


def test_main_con_una_grabacion_sin_fecha_sale_con_5(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ej, "RUTA_DOTENV", tmp_path / "no_existe.env")
    monkeypatch.setenv(ej.ENV_FUENTE, "")                     # main escribe --fuente en el entorno: que se restaure
    assert ej.main(["--fuente", f"grabacion={tmp_path / 'sin_fecha.jsonl.gz'}"]) == ej.CODIGO_CONFIG
