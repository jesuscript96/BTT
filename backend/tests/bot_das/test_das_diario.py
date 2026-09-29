"""Tests de `app.bot_das.diario` (R-N-01, H-2, M6, R-A-05; correcciones 3 y 4; riesgos 3, 20, 22 y 23).

Fila de §10: write-ahead (el fichero ya tiene `orden_intencion` aunque el
proceso muera con `os._exit`), última línea partida tolerada, `reconstruir`
sobre los dos diarios de `fixtures` (señales, lotes, tokens, fills/neta,
locates, pausas, BS), idempotencia, disco no escribible → `degradado`,
`pendientes` y sin excepción (y vuelco al volver), `Decimal` como cadena y
el limpiador de secretos aplicado a las `notas`.
"""
from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
import sys
import textwrap
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from app.bot_das import diario as mod_diario
from app.bot_das.diario import (
    FSYNC,
    PROCESOS,
    TEXTO_LIMPIAR_FALLO,
    TIPO_LINEA_PARTIDA,
    Diario,
    DiarioNoDisponible,
    LectorDiario,
    a_json_seguro,
    leer_texto,
    nombre_fichero,
    reconstruir,
    registro_a_linea,
    ultimo_seq_por_origen,
)
from app.bot_das.reloj import ET, RelojSimulado
from app.bot_das.tipos import (
    EstadoLote,
    EstadoOrden,
    EstadoTicker,
    Fase,
    Fill,
    Lado,
    Origen,
    Proposito,
    Registro,
    TipoOrden,
)

FIXTURES = Path(__file__).parent / "fixtures"
HOY = date(2026, 9, 25)                  # día del año 268: tokens 1268xxxxx / 2268xxxxx / 3268xxxxx
BACKEND = Path(__file__).resolve().parents[2]
ES_WINDOWS = sys.platform == "win32"

LOTE_XYZ = "XYZ|prueba-1|2026-09-25 09:30:00|entrada"
LOTE_ABCD = "ABCD|prueba-1|2026-09-25 10:04:00|entrada"
LOTE_MNOP = "MNOP|prueba-1|2026-09-25 10:39:00|entrada"


# ── ayudas ─────────────────────────────────────────────────────────────
@pytest.fixture
def dir_diario(dir_bot: Path) -> Path:
    return dir_bot / "diario"


@pytest.fixture
def diario(dir_diario: Path, reloj: RelojSimulado):
    d = Diario(dir_diario, reloj, "ejecutor", "2026.09.26", Fase.CANARIO)
    try:
        yield d
    finally:
        d.cerrar()


@pytest.fixture
def dir_fixtures_dia(tmp_path: Path) -> Path:
    """Los dos diarios de `fixtures` copiados con el nombre real del día (§8)."""
    destino = tmp_path / "diario_fixture"
    destino.mkdir()
    shutil.copy(FIXTURES / "diario_medio_dia_ejecutor.jsonl", destino / nombre_fichero("ejecutor", HOY))
    shutil.copy(FIXTURES / "diario_medio_dia_vigilante.jsonl", destino / nombre_fichero("vigilante", HOY))
    return destino


@pytest.fixture
def registros_fixture(dir_fixtures_dia: Path) -> list[Registro]:
    return LectorDiario(dir_fixtures_dia).leer(HOY)


def lineas(ruta: Path) -> list[dict]:
    return [json.loads(x) for x in ruta.read_text(encoding="utf-8").splitlines() if x.strip()]


_SEQ_PRUEBA = [0]


def reg(tipo: str, /, t: str = "09:31:00.000", proceso: str = "ejecutor", seq: int | None = None, **datos) -> Registro:
    """Registro sintético del día HOY (hora ET); `seq` creciente si no se da."""
    if seq is None:
        _SEQ_PRUEBA[0] += 1
        seq = _SEQ_PRUEBA[0]
    return Registro(v=1, seq=seq, t=f"2026-09-25T{t}-04:00", proceso=proceso, tipo=tipo, datos=datos)


def arranque(fase: str = "canario", t: str = "04:00:00.000") -> Registro:
    return reg("arranque", t=t, version="2026.09.26", fase=fase)


def intencion(token: int, ticker: str = "XYZ", t: str = "09:31:00.000", **extra) -> Registro:
    datos = dict(ticker=ticker, token=token, lado="SS", qty=1000, tipo_orden="LMT", precio="3.45", stop=None,
                 ruta="SAGEREB", proposito="entrada_agregar", lote_id=f"{ticker}|e|2026-09-25 09:30:00|entrada",
                 nivel="3.9000", version=0, origen=1)
    datos.update(extra)
    return reg("orden_intencion", t=t, **datos)


# ── nombre de fichero y constructor ────────────────────────────────────
@pytest.mark.parametrize("proceso", PROCESOS, ids=[f"correccion3-{p}" for p in PROCESOS])
def test_nombre_fichero_por_dia_y_proceso(proceso: str) -> None:
    assert nombre_fichero(proceso, HOY) == f"diario_{proceso}_2026-09-25.jsonl"


@pytest.mark.parametrize("proceso", ["", "Ejecutor", "bot", "ejecutor "], ids=lambda p: f"correccion3-rechaza-{p!r}")
def test_nombre_fichero_rechaza_proceso_desconocido(proceso: str) -> None:
    with pytest.raises(ValueError):
        nombre_fichero(proceso, HOY)


def test_diario_rechaza_proceso_fase_y_limpiador_invalidos(dir_diario: Path, reloj: RelojSimulado) -> None:
    with pytest.raises(ValueError):
        Diario(dir_diario, reloj, "otro", "v", Fase.SOMBRA)
    with pytest.raises(ValueError):
        Diario(dir_diario, reloj, "ejecutor", "v", "sombra")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        Diario(dir_diario, reloj, "ejecutor", "v", Fase.SOMBRA, limpiar="no")  # type: ignore[arg-type]


def test_fsync_contiene_los_tipos_de_la_tabla_de_s8() -> None:
    assert FSYNC == frozenset({"orden_intencion", "orden_enviada", "cancel_intencion", "replace_intencion",
                               "locate_intencion", "cierre_humano", "lote"})


# ── serialización (§8, riesgo 12) ──────────────────────────────────────
@dataclass(frozen=True)
class _Punto:
    x: Decimal
    lado: Lado


class _StrRoto:
    def __str__(self) -> str:
        raise RuntimeError("roto")


@pytest.mark.parametrize(
    "valor, esperado",
    [
        pytest.param(Decimal("3.4500"), "3.4500", id="s8-decimal-cadena-conserva-ceros"),
        pytest.param(Decimal("0.0001"), "0.0001", id="s8-decimal-subcentimo"),
        pytest.param(Decimal("1E+2"), "1E+2", id="s8-decimal-tal-cual-str"),
        pytest.param(datetime(2026, 9, 25, 9, 31, 2, tzinfo=ET), "2026-09-25T09:31:02-04:00", id="s8-datetime-iso-et"),
        pytest.param(date(2026, 9, 25), "2026-09-25", id="s8-date-iso"),
        pytest.param(Fase.CANARIO, "canario", id="s8-enum-str-valor"),
        pytest.param(Origen.VIGILANTE, 2, id="s8-intenum-entero"),
        pytest.param(Lado.CORTO, "SS", id="s8-lado"),
        pytest.param({"b", "a", "c"}, ["a", "b", "c"], id="s8-set-lista-ordenada"),
        pytest.param(frozenset({3, 1}), [1, 3], id="s8-frozenset-ordenado"),
        pytest.param((1, Decimal("2.5")), [1, "2.5"], id="s8-tupla-lista"),
        pytest.param(_Punto(Decimal("1.10"), Lado.VENTA), {"x": "1.10", "lado": "S"}, id="s8-dataclass-dict"),
        pytest.param(float("nan"), "nan", id="s8-nan-no-es-json"),
        pytest.param(float("inf"), "inf", id="s8-inf-no-es-json"),
        pytest.param(1.5, 1.5, id="s8-float-finito"),
        pytest.param(True, True, id="s8-bool"),
        pytest.param(None, None, id="s8-none"),
        pytest.param(Path("a/b"), str(Path("a/b")), id="s8-path"),
        pytest.param(b"\x00ab", "b'\\x00ab'", id="s8-bytes-repr"),
        pytest.param({Proposito.STOP: 1}, {"stop": 1}, id="s8-clave-enum"),
    ],
)
def test_a_json_seguro(valor, esperado) -> None:
    resultado = a_json_seguro(valor)
    assert resultado == esperado
    json.dumps(resultado, allow_nan=False)   # siempre JSON válido


def test_a_json_seguro_str_roto_no_lanza() -> None:
    assert a_json_seguro(_StrRoto()).startswith("<no serializable: _StrRoto")


def test_a_json_seguro_fill_completo() -> None:
    fill = Fill(id_trade=7, token=126800001, id_orden=501, ticker="XYZ", lado="SS", qty=400, precio=Decimal("3.45"),
                ruta="SAGEREB", hora="09:31:20", liq="A", ecn_fee=Decimal("-0.80"))
    assert a_json_seguro(fill)["precio"] == "3.45"
    assert a_json_seguro(fill)["ecn_fee"] == "-0.80"


# ── escritura: formato de línea, seq, cabecera ─────────────────────────
def test_abrir_dia_escribe_cabecera_arranque_R_O_01(diario: Diario, reloj: RelojSimulado) -> None:
    seq = diario.abrir_dia(reloj.hoy(), motor_hash="sha256:" + "0" * 64, config_version=7,
                           estrategias_hash="sha256:" + "1" * 64, reloj_desvio_s=-0.12)
    assert seq == 1
    assert diario.ruta is not None and diario.ruta.name == "diario_ejecutor_2026-09-25.jsonl"
    (cabecera,) = lineas(diario.ruta)
    assert cabecera["tipo"] == "arranque"
    assert cabecera["datos"] == {"version": "2026.09.26", "fase": "canario", "motor_hash": "sha256:" + "0" * 64,
                                 "config_version": 7, "estrategias_hash": "sha256:" + "1" * 64,
                                 "pid": os.getpid(), "reloj_desvio_s": -0.12}


def test_anotar_formato_de_linea_s8(diario: Diario, reloj: RelojSimulado) -> None:
    diario.abrir_dia(reloj.hoy())
    reloj.avanzar(1.417)
    seq = diario.anotar("orden_intencion", ticker="XYZ", token=126800001, lado=Lado.CORTO, qty=1200,
                        tipo_orden=TipoOrden.LIMITE, precio=Decimal("3.4500"), stop=None,
                        proposito=Proposito.ENTRADA_AGREGAR, origen=Origen.EJECUTOR,
                        vistos={"b", "a"}, cuando=datetime(2026, 9, 25, 9, 30, tzinfo=ET))
    assert seq == 2 and diario.seq == 2
    texto = diario.ruta.read_text(encoding="utf-8")
    assert '"precio":"3.4500"' in texto                       # Decimal como CADENA, nunca float
    linea = lineas(diario.ruta)[-1]
    assert list(linea) == ["v", "seq", "t", "mono", "proceso", "tipo", "ticker", "datos"]
    assert linea["v"] == 1 and linea["seq"] == 2 and linea["proceso"] == "ejecutor"
    assert linea["t"] == "2026-09-25T09:30:01.417-04:00"     # hora ET aware con milisegundos
    assert linea["mono"] == pytest.approx(1001.417)
    assert linea["ticker"] == "XYZ" and "ticker" not in linea["datos"]
    assert linea["datos"] == {"token": 126800001, "lado": "SS", "qty": 1200, "tipo_orden": "LMT", "precio": "3.4500",
                              "stop": None, "proposito": "entrada_agregar", "origen": 1, "vistos": ["a", "b"],
                              "cuando": "2026-09-25T09:30:00-04:00"}


def test_anotar_sin_abrir_dia_abre_el_de_hoy_con_cabecera(diario: Diario) -> None:
    assert diario.anotar("senal", ticker="XYZ", senal_id="s1", tipo="entrada") == 2
    tipos = [x["tipo"] for x in lineas(diario.ruta)]
    assert tipos == ["arranque", "senal"]
    assert lineas(diario.ruta)[-1]["datos"] == {"senal_id": "s1", "tipo": "entrada"}   # `tipo` de los datos no choca


def test_anotar_ticker_none_no_sale_en_la_linea(diario: Diario) -> None:
    diario.anotar("pausa", ticker=None, motivo="global")
    ultima = lineas(diario.ruta)[-1]
    assert "ticker" not in ultima and ultima["datos"] == {"motivo": "global"}


def test_seq_creciente_y_unico(diario: Diario) -> None:
    seqs = [diario.anotar("metrica", nombre="barrido_ms", valor=i) for i in range(50)]
    assert seqs == list(range(2, 52))
    assert [x["seq"] for x in lineas(diario.ruta)] == list(range(1, 52))
    assert diario.escritos == 51


@pytest.mark.parametrize("tipo", sorted(FSYNC) + ["arranque"], ids=lambda t: f"M6-fsync-{t}")
def test_fsync_en_tipos_write_ahead(diario: Diario, monkeypatch: pytest.MonkeyPatch, tipo: str) -> None:
    diario.abrir_dia(HOY)
    llamadas: list[int] = []
    real = os.fsync
    monkeypatch.setattr(mod_diario.os, "fsync", lambda fd: (llamadas.append(fd), real(fd))[1])
    diario.anotar(tipo, ticker="XYZ")
    assert len(llamadas) == 1


@pytest.mark.parametrize("tipo", ["senal", "orden_act", "fill", "aviso", "metrica", "stop_plan"],
                         ids=lambda t: f"M6-sin-fsync-{t}")
def test_sin_fsync_en_el_resto(diario: Diario, monkeypatch: pytest.MonkeyPatch, tipo: str) -> None:
    diario.abrir_dia(HOY)
    llamadas: list[int] = []
    monkeypatch.setattr(mod_diario.os, "fsync", lambda fd: llamadas.append(fd))
    diario.anotar(tipo, ticker="XYZ")
    assert llamadas == []


# ── write-ahead (M6, riesgo 3) ─────────────────────────────────────────
def test_write_ahead_la_linea_esta_en_disco_al_volver_anotar(diario: Diario) -> None:
    diario.abrir_dia(HOY)
    diario.anotar("orden_intencion", ticker="XYZ", token=126800001, precio=Decimal("3.45"))
    # Otro descriptor (como el vigilante) la ve sin que el escritor cierre ni vacíe nada más.
    with open(diario.ruta, encoding="utf-8") as otro:
        ultima = json.loads(otro.read().splitlines()[-1])
    assert ultima["tipo"] == "orden_intencion" and ultima["datos"]["token"] == 126800001


def test_write_ahead_sobrevive_a_os_exit_en_subproceso(dir_diario: Path) -> None:
    """M6/H-2: el proceso muere justo tras `anotar(orden_intencion)` (antes del send) y el registro está."""
    guion = textwrap.dedent(
        """
        import os, sys
        from datetime import datetime
        from decimal import Decimal
        from pathlib import Path
        sys.path.insert(0, sys.argv[1])
        from app.bot_das.diario import Diario
        from app.bot_das.reloj import ET, RelojSimulado
        from app.bot_das.tipos import Fase, Lado
        reloj = RelojSimulado(datetime(2026, 9, 25, 9, 31, 2, tzinfo=ET))
        d = Diario(Path(sys.argv[2]), reloj, "ejecutor", "2026.09.26", Fase.CANARIO)
        d.abrir_dia(reloj.hoy())
        d.anotar("orden_intencion", ticker="XYZ", token=126800001, lado=Lado.CORTO, qty=1200,
                 tipo_orden="LMT", precio=Decimal("3.45"), proposito="entrada_agregar")
        os._exit(3)
        """
    )
    resultado = subprocess.run([sys.executable, "-c", guion, str(BACKEND), str(dir_diario)],
                               capture_output=True, text=True, timeout=60, cwd=str(BACKEND))
    assert resultado.returncode == 3, resultado.stderr
    registros = LectorDiario(dir_diario).leer(HOY, procesos=("ejecutor",))
    assert [r.tipo for r in registros] == ["arranque", "orden_intencion"]
    assert registros[-1].datos["precio"] == "3.45"
    estado = reconstruir(registros, HOY)
    assert estado.ordenes[126800001].estado is EstadoOrden.SENDING     # «puede haber salido» (riesgo 3)
    assert estado.ultimo_seq_token == 1


# ── limpiador de secretos (ajuste (h), riesgo 20) ──────────────────────
SECRETO = "valor-secreto-inventado-9Xq2"


def test_limpiar_se_aplica_a_notas_claves_ticker_y_anidados(dir_diario: Path, reloj: RelojSimulado) -> None:
    d = Diario(dir_diario, reloj, "ejecutor", "v", Fase.SOMBRA, limpiar=lambda s: s.replace(SECRETO, "*****"))
    try:
        d.anotar("orden_act", ticker=f"X{SECRETO}", notas=f"login u {SECRETO}",
                 anidado={"lista": [SECRETO, Decimal("1")], SECRETO: "clave"}, conjunto={SECRETO})
        d.anotar(f"tipo-{SECRETO}")
    finally:
        d.cerrar()
    texto = d.ruta.read_text(encoding="utf-8")
    assert SECRETO not in texto
    ultima = lineas(d.ruta)[-2]
    assert ultima["datos"]["notas"] == "login u *****"
    assert ultima["datos"]["anidado"] == {"lista": ["*****", "1"], "*****": "clave"}


def test_limpiar_que_lanza_retira_el_texto_y_no_lanza(dir_diario: Path, reloj: RelojSimulado) -> None:
    def roto(texto: str) -> str:
        raise RuntimeError("limpiador roto")

    d = Diario(dir_diario, reloj, "ejecutor", "v", Fase.SOMBRA, limpiar=roto)
    try:
        seq = d.anotar("comando", notas=SECRETO)
    finally:
        d.cerrar()
    assert seq == 2 and not d.degradado
    texto = d.ruta.read_text(encoding="utf-8")
    assert SECRETO not in texto and TEXTO_LIMPIAR_FALLO in texto


def test_filtro_secretos_de_avisos_limpia_notas_del_diario(dir_diario: Path, reloj: RelojSimulado) -> None:
    """§10: `FiltroSecretos.limpiar` inyectado (ajuste (h)) quita el valor literal y la forma `bot123:…`."""
    avisos = pytest.importorskip("app.bot_das.avisos")
    filtro = avisos.FiltroSecretos([SECRETO])
    token_telegram = "bot1234567:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    d = Diario(dir_diario, reloj, "ejecutor", "v", Fase.SOMBRA, limpiar=filtro.limpiar)
    try:
        d.anotar("orden_act", ticker="XYZ", notas=f"notes con {SECRETO} y {token_telegram}", cruda=f"x {SECRETO}")
    finally:
        d.cerrar()
    texto = d.ruta.read_text(encoding="utf-8")
    assert SECRETO not in texto
    assert "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA" not in texto


# ── reinicio a mitad de día: seq continúa y la línea partida no se come la siguiente ──
def test_reinicio_continua_seq(dir_diario: Path, reloj: RelojSimulado) -> None:
    primero = Diario(dir_diario, reloj, "ejecutor", "v", Fase.CANARIO)
    primero.abrir_dia(HOY)
    primero.anotar("senal", senal_id="a")
    primero.anotar("senal", senal_id="b")
    primero.cerrar()
    segundo = Diario(dir_diario, reloj, "ejecutor", "v", Fase.CANARIO)
    try:
        assert segundo.abrir_dia(HOY) == 4
        assert segundo.anotar("senal", senal_id="c") == 5
    finally:
        segundo.cerrar()
    assert [x["seq"] for x in lineas(primero.ruta)] == [1, 2, 3, 4, 5]


def test_reinicio_tras_linea_partida_no_pega_el_registro_nuevo(dir_diario: Path, reloj: RelojSimulado) -> None:
    primero = Diario(dir_diario, reloj, "ejecutor", "v", Fase.CANARIO)
    primero.abrir_dia(HOY)
    primero.anotar("orden_intencion", ticker="XYZ", token=126800001)
    primero.cerrar()
    with open(primero.ruta, "a", encoding="utf-8", newline="\n") as f:
        f.write('{"v":1,"seq":3,"t":"2026-09-25T09:3')          # crash a medio write
    segundo = Diario(dir_diario, reloj, "ejecutor", "v", Fase.CANARIO)
    try:
        assert segundo.abrir_dia(HOY) == 4
    finally:
        segundo.cerrar()
    registros = LectorDiario(dir_diario).leer(HOY, procesos=("ejecutor",))
    assert [r.tipo for r in registros] == ["arranque", "orden_intencion", TIPO_LINEA_PARTIDA, "arranque"]
    assert registros[-1].seq == 4 and registros[-1].datos["version"] == "v"


# ── disco no escribible (corrección 4, riesgo 23) ──────────────────────
def test_directorio_no_escribible_degradado_pendientes_y_no_lanza(tmp_path: Path, reloj: RelojSimulado) -> None:
    bloqueo = tmp_path / "diario"
    bloqueo.write_text("soy un fichero, no un directorio", encoding="utf-8")
    d = Diario(bloqueo, reloj, "ejecutor", "v", Fase.CANARIO)
    try:
        assert d.abrir_dia(HOY) == 1
        assert d.degradado and d.ultimo_error is not None
        assert d.anotar("orden_intencion", ticker="XYZ", token=126800001) == 2
        assert d.anotar("senal", senal_id="s") == 3
        assert [p[0] for p in d.pendientes] == [1, 2, 3]
        assert [p[2] for p in d.pendientes] == [True, True, False]    # fsync recordado por registro
        assert d.escritos == 0
        # Vuelve el disco: el siguiente anotar vuelca los pendientes EN ORDEN antes del registro nuevo.
        bloqueo.unlink()
        assert d.anotar("senal", senal_id="t") == 4
        assert not d.degradado and d.pendientes == []
    finally:
        d.cerrar()
    assert [x["seq"] for x in lineas(bloqueo / nombre_fichero("ejecutor", HOY))] == [1, 2, 3, 4]


def test_abrir_dia_estricto_lanza_si_no_puede_escribir(tmp_path: Path, reloj: RelojSimulado) -> None:
    bloqueo = tmp_path / "diario"
    bloqueo.write_text("x", encoding="utf-8")
    d = Diario(bloqueo, reloj, "ejecutor", "v", Fase.CANARIO)
    with pytest.raises(DiarioNoDisponible):
        d.abrir_dia(HOY, estricto=True)
    d.cerrar()


def test_pendientes_con_tope_descarta_los_mas_viejos(tmp_path: Path, reloj: RelojSimulado,
                                                   monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mod_diario, "PENDIENTES_TOPE", 3)
    bloqueo = tmp_path / "diario"
    bloqueo.write_text("x", encoding="utf-8")
    d = Diario(bloqueo, reloj, "ejecutor", "v", Fase.CANARIO)
    d.abrir_dia(HOY)
    for i in range(5):
        d.anotar("metrica", valor=i)
    assert [p[0] for p in d.pendientes] == [4, 5, 6]
    assert d.perdidos == 3 and d.degradado
    d.cerrar()


def test_anotar_con_reloj_roto_no_lanza(dir_diario: Path) -> None:
    class RelojRoto:
        def hoy(self) -> date:
            return HOY

        def ahora(self) -> datetime:
            raise RuntimeError("reloj roto")

        def mono(self) -> float:
            return 0.0

    d = Diario(dir_diario, RelojRoto(), "ejecutor", "v", Fase.SOMBRA)
    d.anotar("senal", senal_id="x")
    assert d.degradado and "reloj roto" in (d.ultimo_error or "")
    d.cerrar()


def _bloquear(ruta: Path) -> int:
    import msvcrt
    fd = os.open(ruta, os.O_RDWR)
    os.lseek(fd, 0, os.SEEK_SET)
    msvcrt.locking(fd, msvcrt.LK_NBLCK, 2**31 - 1)
    return fd


def _desbloquear(fd: int) -> None:
    import msvcrt
    os.lseek(fd, 0, os.SEEK_SET)
    msvcrt.locking(fd, msvcrt.LK_UNLCK, 2**31 - 1)
    os.close(fd)


@pytest.mark.skipif(not ES_WINDOWS, reason="bloqueo de rango con msvcrt: solo Windows (el VPS del bot)")
def test_fichero_bloqueado_a_mitad_de_dia_degrada_y_luego_vuelca(diario: Diario) -> None:
    diario.abrir_dia(HOY)
    diario.anotar("senal", senal_id="a")
    fd = _bloquear(diario.ruta)
    try:
        assert diario.anotar("orden_intencion", ticker="XYZ", token=126800001) == 3
        assert diario.degradado and len(diario.pendientes) == 1
        assert diario.anotar("senal", senal_id="b") == 4
        assert [p[0] for p in diario.pendientes] == [3, 4]
    finally:
        _desbloquear(fd)
    assert diario.anotar("senal", senal_id="c") == 5
    assert not diario.degradado
    diario.cerrar()
    assert [x["seq"] for x in lineas(diario.ruta)] == [1, 2, 3, 4, 5]


@pytest.mark.skipif(not ES_WINDOWS, reason="bloqueo de rango con msvcrt: solo Windows (el VPS del bot)")
def test_media_linea_tras_un_fallo_se_cierra_antes_del_vuelco(diario: Diario, dir_diario: Path) -> None:
    """Riesgo 23: un `write` a medias (disco lleno) no se come el registro que se reintenta después."""
    diario.abrir_dia(HOY)
    fd = _bloquear(diario.ruta)
    try:
        diario.anotar("orden_intencion", ticker="XYZ", token=126800001)
    finally:
        _desbloquear(fd)
    with open(diario.ruta, "a", encoding="utf-8", newline="\n") as f:
        f.write('{"v":1,"seq":2,"t":"2026-09-25T09:30:00.000-04:0')    # lo que el disco llegó a guardar
    assert diario.anotar("senal", senal_id="x") == 3
    diario.cerrar()
    registros = LectorDiario(dir_diario).leer(HOY, procesos=("ejecutor",))
    assert [(r.tipo, r.seq) for r in registros] == [("arranque", 1), (TIPO_LINEA_PARTIDA, 1),
                                                    ("orden_intencion", 2), ("senal", 3)]


@pytest.mark.skipif(not ES_WINDOWS, reason="bloqueo de rango con msvcrt: solo Windows (el VPS del bot)")
def test_reinicio_con_fichero_bloqueado_renumera_pendientes_detras_del_maximo(dir_diario: Path,
                                                                              reloj: RelojSimulado) -> None:
    primero = Diario(dir_diario, reloj, "ejecutor", "v", Fase.CANARIO)
    primero.abrir_dia(HOY)
    for _ in range(4):
        primero.anotar("metrica", valor=1)
    primero.cerrar()                                   # seq 1..5 en el fichero
    fd = _bloquear(primero.ruta)
    segundo = Diario(dir_diario, reloj, "ejecutor", "v", Fase.CANARIO)
    try:
        segundo.abrir_dia(HOY)                         # no puede ni leer el fichero: pendiente seq 1
        segundo.anotar("senal", senal_id="x")          # pendiente seq 2
        assert segundo.degradado
    finally:
        _desbloquear(fd)
    try:
        assert segundo.anotar("senal", senal_id="y") == 8
    finally:
        segundo.cerrar()
    seqs = [x["seq"] for x in lineas(primero.ruta)]
    assert seqs == [1, 2, 3, 4, 5, 6, 7, 8]            # sin repetidos ni hacia atrás (riesgo 22)


# ── lectura ────────────────────────────────────────────────────────────
def test_DC_06_la_fixture_usa_la_forma_real_del_decisor(registros_fixture: list[Registro]) -> None:
    """DC-06: la fixture lleva las claves que escriben de verdad decisor y reconciliación: fill del Execute con
    id_trade null + su eco del %TRADE, `neta_fills` (no `neta_fills_tras`), «Replaced» tras el REPLACE, la pausa
    global del caso 4 y el /sigue de `_anotar_comando`."""
    fills = [r.datos for r in registros_fixture if r.tipo == "fill"]
    assert all("neta_fills" in d and "neta_fills_tras" not in d and {"eco", "origen", "simulado", "proposito"} <= set(d)
               for d in fills)
    assert [d["origen"] for d in fills if d["id_trade"] is None] == ["execute"]
    assert [d["id_trade"] for d in fills if d["eco"]] == [7001]
    assert len([r for r in registros_fixture if r.tipo == "orden_act" and r.datos["accion"] == "Replaced"]) == 2
    pausa = next(r for r in registros_fixture if r.tipo == "pausa" and "ticker" not in r.datos)
    assert pausa.datos["pausa_global"] is True and pausa.datos["ticker_ajeno"] == "QRS"
    sigue = next(r for r in registros_fixture if r.tipo == "comando")
    assert sigue.datos["original"] == "sigue" and sigue.datos["confirmado"] is True


def test_leer_une_y_ordena_los_dos_diarios(registros_fixture: list[Registro]) -> None:
    assert len(registros_fixture) == 95 + 12
    claves = [(r.t, r.proceso, r.seq) for r in registros_fixture]
    assert claves == sorted(claves)
    assert {r.proceso for r in registros_fixture} == {"ejecutor", "vigilante"}
    assert registros_fixture[0].tipo == "arranque" and registros_fixture[0].proceso == "ejecutor"
    assert all(r.tipo != TIPO_LINEA_PARTIDA for r in registros_fixture)


def test_leer_pone_ticker_y_mono_en_datos(registros_fixture: list[Registro]) -> None:
    orden = next(r for r in registros_fixture if r.tipo == "orden_intencion")
    assert orden.datos["ticker"] == "XYZ" and orden.datos["mono"] == pytest.approx(20862.417)
    linea = registro_a_linea(orden)
    assert linea["ticker"] == "XYZ" and "ticker" not in linea["datos"] and linea["mono"] == pytest.approx(20862.417)


def test_leer_fichero_ausente_es_vacio(tmp_path: Path) -> None:
    assert LectorDiario(tmp_path / "no_existe").leer(HOY) == []


def test_cada_cruda_de_las_fixtures_la_entiende_el_protocolo(registros_fixture: list[Registro]) -> None:
    """Las fixtures son realistas: toda línea `cruda` de DAS se parsea (ninguna queda MsgDesconocido)."""
    from app.bot_das import protocolo
    from app.bot_das.tipos import MsgDesconocido

    crudas = [r.datos["cruda"] for r in registros_fixture if "cruda" in r.datos]
    assert len(crudas) > 30
    for cruda in crudas:
        assert not isinstance(protocolo.parsear(cruda), MsgDesconocido), cruda


def test_ultima_linea_partida_se_tolera_y_se_anota(dir_diario: Path, diario: Diario) -> None:
    diario.abrir_dia(HOY)
    diario.anotar("senal", senal_id="a")
    diario.cerrar()
    with open(diario.ruta, "a", encoding="utf-8", newline="\n") as f:
        f.write('{"v":1,"seq":3,"t":"2026-09-25T09:30:00.000-04:00","proceso":"ejec')
    registros = LectorDiario(dir_diario).leer(HOY)
    assert [r.tipo for r in registros] == ["arranque", "senal", TIPO_LINEA_PARTIDA]
    partida = registros[-1]
    assert partida.seq == 2 and partida.proceso == "ejecutor"
    assert partida.datos["posicion"] == 3 and partida.datos["texto"].startswith('{"v":1,"seq":3')
    assert reconstruir(registros, HOY).senales_vistas == {"a"}


def test_linea_rota_en_medio_y_basura_no_lanzan() -> None:
    texto = ('{"v":1,"seq":1,"t":"a","proceso":"ejecutor","tipo":"senal","datos":{"senal_id":"x"}}\n'
             'esto no es json\n'
             '[1,2,3]\n'
             '\n'
             '{"v":1,"seq":2,"t":"b","proceso":"ejecutor","tipo":"senal","datos":{"senal_id":"y"}}\n')
    registros = leer_texto(texto, "ejecutor")
    assert [r.tipo for r in registros] == ["senal", TIPO_LINEA_PARTIDA, TIPO_LINEA_PARTIDA, "senal"]
    assert [r.seq for r in registros] == [1, 1, 1, 2]


def test_seguir_ignora_la_cola_a_medio_escribir(dir_diario: Path, diario: Diario) -> None:
    """Riesgo 22: el vigilante no toma por registro una línea que el ejecutor aún escribe."""
    diario.abrir_dia(HOY)
    diario.anotar("orden_intencion", ticker="XYZ", token=126800001)
    diario.anotar("orden_enviada", ticker="XYZ", token=126800001)
    lector = LectorDiario(dir_diario)
    trozo = '{"v":1,"seq":4,"t":"2026-09-25T09:30:00.000-04:00","mono":1000.0,"proceso":"ejecutor","tipo":"fill",'
    with open(diario.ruta, "a", encoding="utf-8", newline="\n") as f:
        f.write(trozo)
    assert [r.seq for r in lector.seguir(HOY, "ejecutor", 1)] == [2, 3]
    with open(diario.ruta, "a", encoding="utf-8", newline="\n") as f:
        f.write('"datos":{"id_trade":1}}\n')
    nuevos = lector.seguir(HOY, "ejecutor", 3)
    assert [(r.seq, r.tipo) for r in nuevos] == [(4, "fill")]
    assert lector.seguir(HOY, "ejecutor", 4) == []
    assert lector.seguir(HOY, "vigilante", 0) == []


# ── reconstruir sobre las fixtures (H-2, §8) ───────────────────────────
@pytest.fixture
def estado_fixture(registros_fixture: list[Registro]):
    return reconstruir(registros_fixture, HOY)


def test_reconstruir_fase_dia_y_config(estado_fixture) -> None:
    assert estado_fixture.fase is Fase.CANARIO
    assert estado_fixture.dia == HOY
    assert estado_fixture.config_version == 1
    assert estado_fixture.pausa_global is False and estado_fixture.control_humano is False
    assert estado_fixture.modo_degradado == set()


def test_reconstruir_senales_vistas_R_A_05(estado_fixture) -> None:
    assert estado_fixture.senales_vistas == {
        LOTE_XYZ, LOTE_ABCD, "ABCD|prueba-1|2026-09-25 10:06:00|entrada", LOTE_MNOP,
    }


def test_reconstruir_lotes(estado_fixture) -> None:
    xyz = estado_fixture.posiciones["XYZ"].lotes[LOTE_XYZ]
    assert (xyz.pedidas, xyz.llenas, xyz.estado) == (1200, 800, EstadoLote.ABIERTO)
    assert xyz.precio_medio == Decimal("3.4350") and xyz.nivel_stop == Decimal("3.90")
    # Los registros posteriores no traen estrategia ni riesgo: se conservan del primero.
    assert xyz.estrategia == "PM (A) prueba" and xyz.riesgo_usd == Decimal("300") and xyz.direccion == "short"
    assert xyz.version_estrategia == "sha256:" + "2b" * 32
    assert estado_fixture.posiciones["ABCD"].lotes[LOTE_ABCD].estado is EstadoLote.CANCELADO
    mnop = estado_fixture.posiciones["MNOP"].lotes[LOTE_MNOP]
    assert (mnop.llenas, mnop.estado, mnop.precio_medio) == (300, EstadoLote.ABIERTO, Decimal("1.21"))


def test_reconstruir_ordenes_por_token(estado_fixture) -> None:
    o = estado_fixture.ordenes
    assert sorted(o) == [126800001 + i for i in range(8)] + [226800001]
    assert (o[126800001].estado, o[126800001].llenas, o[126800001].cxlqty, o[126800001].id_das) == (
        EstadoOrden.CANCELED, 400, 800, 501)
    assert o[126800001].proposito is Proposito.ENTRADA_AGREGAR and o[126800001].lado is Lado.CORTO
    assert o[126800001].enviada_en == pytest.approx(20862.43)
    assert o[126800002].qty == 800                      # tras el REPLACE confirmado por %ORDER
    assert o[126800002].tipo is TipoOrden.STOP_LIMITE_PP and o[126800002].estado is EstadoOrden.ACCEPTED
    assert (o[126800002].stop, o[126800002].precio) == (Decimal("3.90"), Decimal("4.02"))
    assert o[126800002].tipo_das_crudo == "SLP: 3.90 4.02"
    assert (o[126800004].estado, o[126800004].llenas, o[126800004].cxlqty) == (EstadoOrden.CANCELED, 400, 400)
    assert o[126800005].estado is EstadoOrden.REJECTED and o[126800005].notas == "Rejected: 0 shares available"
    assert (o[126800006].estado, o[126800006].llenas) == (EstadoOrden.EXECUTED, 300)
    vig = o[226800001]
    assert vig.origen is Origen.VIGILANTE and vig.proposito is Proposito.STOP_PROTECCION and vig.lote_id is None
    assert vig.lado is Lado.VENTA and vig.estado is EstadoOrden.ACCEPTED
    assert estado_fixture.id_a_token == {500 + i: 126800000 + i for i in range(1, 9)} | {601: 226800001}


def test_reconstruir_tokens_por_origen(registros_fixture, estado_fixture) -> None:
    assert ultimo_seq_por_origen(registros_fixture, HOY) == {Origen.EJECUTOR: 8, Origen.VIGILANTE: 1,
                                                             Origen.EJECUTOR_LOCATE: 1}
    assert estado_fixture.ultimo_seq_token == 8


def test_reconstruir_fills_y_neta_con_dedupe(estado_fixture) -> None:
    """Corrección 2: el volcado del #Trade tras la reconexión repite 7002 y no suma dos veces."""
    fills = estado_fixture.fills
    assert {t: [f.id_trade for f in lista] for t, lista in fills.items()} == {
        126800001: [7001], 126800004: [7002], 126800006: [7003]}
    assert fills[126800001][0].precio == Decimal("3.45") and fills[126800001][0].ecn_fee == Decimal("-0.80")
    pos = estado_fixture.posiciones
    assert (pos["XYZ"].neta_fills, pos["MNOP"].neta_fills, pos["ABCD"].neta_fills) == (-800, -300, 0)
    assert pos["XYZ"].version_stops == 2 and pos["MNOP"].version_stops == 1
    assert estado_fixture.ultimo_fill_en == pytest.approx(25005.005)


def test_reconstruir_posicion_ajena_del_vigilante(estado_fixture) -> None:
    qrs = estado_fixture.posiciones["QRS"]
    assert (qrs.neta_das, qrs.neta_fills, qrs.avg_das, qrs.tipo_das) == (200, 0, Decimal("10.00"), 1)


def test_reconstruir_locates_R_H_03(estado_fixture) -> None:
    loc = estado_fixture.locates[("XYZ", "prueba-1")]
    assert (loc.estado, loc.localizadas, loc.usadas, loc.pedidas, loc.compras) == ("Located", 1200, 800, 1200, 1)
    assert (loc.coste, loc.precio_accion, loc.id_das, loc.token) == (Decimal("12.00"), Decimal("0.0100"), 9101,
                                                                      326800001)
    assert estado_fixture.gasto_locates_dia == Decimal("12.00")
    assert estado_fixture.locates_deshabilitados is False


def test_reconstruir_pausas_y_bs(estado_fixture) -> None:
    pos = estado_fixture.posiciones
    assert pos["ABCD"].estado is EstadoTicker.PAUSADO and "R-B-07" in pos["ABCD"].motivo_estado
    assert pos["XYZ"].estado is EstadoTicker.NORMAL
    mnop = pos["MNOP"]
    assert mnop.estado is EstadoTicker.BS and mnop.bs is not None
    # el fixture es un diario de antes del stop único (Jaume 29-sep): su `emergencia_limite` se lee como `limite_stop`
    assert (mnop.bs.primer_stop, mnop.bs.limite_stop, mnop.bs.max_visto) == (
        Decimal("1.32"), Decimal("2.16"), Decimal("2.45"))
    assert mnop.bs.informes == 2 and mnop.bs.ultimo_informe == pytest.approx(25854.0)
    assert mnop.bs.activado_en == pytest.approx(25734.02) and mnop.bs.silenciado is False


# ── idempotencia y pureza ──────────────────────────────────────────────
def test_reconstruir_idempotente_y_puro(registros_fixture: list[Registro]) -> None:
    copia = copy.deepcopy(registros_fixture)
    primero = reconstruir(registros_fixture, HOY)
    assert reconstruir(registros_fixture, HOY) == primero
    assert reconstruir(registros_fixture + registros_fixture, HOY) == primero       # tramo leído dos veces
    assert reconstruir(list(reversed(registros_fixture)), HOY) == primero            # el orden lo pone reconstruir
    assert reconstruir(iter(registros_fixture), HOY) == primero                      # acepta un iterable
    assert registros_fixture == copia                                                # no modifica la entrada


def test_reconstruir_sin_registros() -> None:
    estado = reconstruir([], HOY)
    assert estado.fase is Fase.SOMBRA and estado.dia == HOY and estado.ultimo_seq_token == 0
    assert estado.posiciones == {} and estado.ordenes == {} and estado.senales_vistas == set()


# ── reconstruir: casos puntuales ───────────────────────────────────────
def test_intencion_sin_enviada_queda_sending_riesgo_3() -> None:
    estado = reconstruir([arranque(), intencion(126800007)], HOY)
    orden = estado.ordenes[126800007]
    assert orden.estado is EstadoOrden.SENDING and orden.enviada_en == 0.0
    assert estado.ultimo_seq_token == 7


def test_tokens_de_ayer_no_cuentan_2f5() -> None:
    ayer = 126700050                    # día 267
    estado = reconstruir([arranque(), intencion(ayer), reg("fill", ticker="XYZ", id_trade=1, token=ayer,
                                                            lado="SS", qty=100, precio="3.4")], HOY)
    assert estado.ordenes == {} and estado.fills == {} and estado.ultimo_seq_token == 0
    assert estado.posiciones == {}


def test_origen_sale_del_token_no_de_los_datos() -> None:
    estado = reconstruir([intencion(226800003, origen=1)], HOY)
    assert estado.ordenes[226800003].origen is Origen.VIGILANTE


def test_ultimo_seq_token_es_el_maximo_de_los_origenes_del_ejecutor() -> None:
    registros = [intencion(126800002), reg("locate_intencion", ticker="XYZ", strategy_id="e", token=326800009),
                 intencion(226800050)]
    assert reconstruir(registros, HOY).ultimo_seq_token == 9
    assert ultimo_seq_por_origen(registros, HOY)[Origen.VIGILANTE] == 50


def test_fill_sin_token_se_casa_por_id_orden() -> None:
    registros = [intencion(126800001), reg("orden_act", ticker="XYZ", id=900, accion="Accept", token=126800001),
                 reg("fill", ticker="XYZ", id_trade=1, id_orden=900, lado="SS", qty=300, precio="3.45")]
    estado = reconstruir(registros, HOY)
    assert estado.posiciones["XYZ"].neta_fills == -300
    assert estado.ordenes[126800001].estado is EstadoOrden.PARTIAL and estado.ordenes[126800001].llenas == 300


def test_fill_ajeno_no_cuenta_R_K_02() -> None:
    estado = reconstruir([reg("fill", ticker="QRS", id_trade=5, id_orden=77, lado="B", qty=200, precio="10")], HOY)
    assert estado.fills == {} and "QRS" not in estado.posiciones


def test_fill_con_lado_desconocido_no_mueve_la_neta() -> None:
    estado = reconstruir([reg("fill", ticker="XYZ", id_trade=1, token=126800001, lado="??", qty=300, precio="3")],
                         HOY)
    assert estado.posiciones["XYZ"].neta_fills == 0 and len(estado.fills[126800001]) == 1


@pytest.mark.parametrize("lado, signo", [("B", 1), ("S", -1), ("SS", -1), ("Buy", 1), ("Shrt", -1)],
                         ids=lambda x: f"correccion2-lado-{x}")
def test_signo_de_los_fills(lado: str, signo: int) -> None:
    estado = reconstruir([reg("fill", ticker="XYZ", id_trade=1, token=126800001, lado=lado, qty=10, precio="3")],
                         HOY)
    assert estado.posiciones["XYZ"].neta_fills == 10 * signo


@pytest.mark.parametrize("fase, esperado", [("sombra", -100), ("canario", 0), ("real", 0)],
                         ids=lambda x: f"s9-simulados-{x}")
def test_fills_simulados_solo_cuentan_en_sombra(fase: str, esperado: int) -> None:
    estado = reconstruir([arranque(fase), reg("fill", ticker="XYZ", id_trade=1, token=126800001, lado="SS", qty=100,
                                             precio="3", simulado=True)], HOY)
    assert estado.posiciones["XYZ"].neta_fills == esperado


def test_discrepancia_caso_6_neta_fills_toma_la_de_das() -> None:
    """Caso 6 con las claves REALES de `reconciliacion._caso_neta_distinta` (`caso: 6`): manda DAS (M7)."""
    registros = [reg("fill", ticker="XYZ", id_trade=1, token=126800001, lado="SS", qty=400, precio="3"),
                 reg("discrepancia", ticker="XYZ", caso=6, detalle="caso 6", neta_fills=-400, neta_das=-300,
                     regla="M7 / corrección 2: manda DAS")]
    pos = reconstruir(registros, HOY).posiciones["XYZ"]
    assert pos.neta_fills == -300 and pos.neta_das == -300


def test_discrepancia_caso_5_plana_en_das() -> None:
    registros = [reg("fill", ticker="XYZ", id_trade=1, token=126800001, lado="SS", qty=400, precio="3"),
                 reg("discrepancia", ticker="XYZ", caso=5, neta_fills=-400, neta_das=0, regla="R-C-10 (5) / M7")]
    pos = reconstruir(registros, HOY).posiciones["XYZ"]
    assert pos.neta_fills == 0 and pos.neta_das == 0


@pytest.mark.parametrize("origen", ["cierre_humano", None], ids=["cisne_negro.cierre_humano", "salidas.cerrar_todo"])
def test_discrepancia_detectada_sin_caso_no_cambia_la_neta(origen) -> None:
    """La `discrepancia` que anotan cerrar_todo / cierre_humano al DETECTAR una diferencia (sin `caso`) solo pide
    GET POSITIONS: el decisor no toca su neta y reconstruir tampoco (alineado con las claves reales)."""
    extra = {"origen": origen} if origen else {}
    registros = [reg("fill", ticker="XYZ", id_trade=1, token=126800001, lado="SS", qty=400, precio="3"),
                 reg("discrepancia", ticker="XYZ", neta_fills=-400, neta_das=-300, **extra)]
    pos = reconstruir(registros, HOY).posiciones["XYZ"]
    assert pos.neta_fills == -400 and pos.neta_das is None


def test_pos_de_das_no_toca_neta_fills_correccion_2() -> None:
    registros = [reg("fill", ticker="XYZ", id_trade=1, token=126800001, lado="SS", qty=400, precio="3"),
                 reg("pos", ticker="XYZ", tipo=3, neta=-100, avg="3.00")]
    pos = reconstruir(registros, HOY).posiciones["XYZ"]
    assert pos.neta_fills == -400 and pos.neta_das == -100


@pytest.mark.parametrize(
    "accion, estado_esperado",
    [("Accept", EstadoOrden.ACCEPTED), ("Canceled", EstadoOrden.CANCELED), ("Send_Rej", EstadoOrden.REJECTED),
     ("Close", EstadoOrden.CLOSED), ("Canceling", EstadoOrden.SENDING), ("Replacing", EstadoOrden.SENDING),
     ("Execute", EstadoOrden.SENDING)],
    ids=lambda x: f"manual-L434-{x}")
def test_orden_act_estado_por_accion(accion: str, estado_esperado: EstadoOrden) -> None:
    estado = reconstruir([intencion(126800001), reg("orden_act", ticker="XYZ", id=900, accion=accion,
                                                    token=126800001)], HOY)
    assert estado.ordenes[126800001].estado is estado_esperado


def test_locate_dos_compras_suma_gasto_y_cuenta_entradas_R_H_02() -> None:
    registros = [
        reg("locate_intencion", ticker="XYZ", strategy_id="e", qty=500, token=326800001),
        reg("locate_estado", ticker="XYZ", strategy_id="e", estado="Located", coste_nuevo="5.00", coste_total="5.00"),
        reg("locate_estado", ticker="XYZ", strategy_id="e", estado="Located", usadas=500, coste_nuevo="0",
            coste_total="5.00"),
        reg("locate_estado", ticker="XYZ", strategy_id="e", estado="Closed"),
        reg("locate_estado", ticker="XYZ", strategy_id="e", estado="Located", coste_nuevo="7.50", coste_total="12.50"),
        reg("locates_deshabilitar", motivo="compra repetida (R-H-02)"),
    ]
    estado = reconstruir(registros, HOY)
    loc = estado.locates[("XYZ", "e")]
    assert loc.compras == 2 and loc.coste == Decimal("12.50") and loc.usadas == 500
    assert estado.gasto_locates_dia == Decimal("12.50")
    assert estado.locates_deshabilitados is True


def test_locate_intencion_sin_estado_queda_comprando() -> None:
    estado = reconstruir([reg("locate_intencion", ticker="XYZ", strategy_id="e", qty=300, qty_ajustada=400,
                              token=326800002, precio_accion="0.02")], HOY)
    loc = estado.locates[("XYZ", "e")]
    assert (loc.estado, loc.pedidas, loc.token, loc.precio_accion) == ("comprando", 400, 326800002, Decimal("0.02"))
    assert estado.gasto_locates_dia == Decimal("0")


def test_bs_cerrado_veta_reentrada_hasta_sigue_ticker_R_G_03() -> None:
    base = [reg("bs", ticker="XYZ", evento="activado", primer_stop="3.9", limite_stop="5.85", max_visto="6.5"),
            reg("bs", ticker="XYZ", evento="cerrado")]
    estado = reconstruir(base, HOY)
    pos = estado.posiciones["XYZ"]
    assert pos.bs is None and pos.estado is EstadoTicker.NORMAL and pos.sin_reentrada_hasta_sigue
    # /sigue global (R-M-03) NO levanta el veto del BS; /sigue sin confirmar tampoco; /sigue XYZ sí.
    assert reconstruir(base + [reg("comando", nombre="sigue", args=[])], HOY).posiciones[
        "XYZ"].sin_reentrada_hasta_sigue
    assert reconstruir(base + [reg("comando", nombre="sigue", args=["XYZ"], confirmado=False)], HOY).posiciones[
        "XYZ"].sin_reentrada_hasta_sigue
    assert not reconstruir(base + [reg("comando", nombre="sigue", args=["xyz"], confirmado=True)], HOY).posiciones[
        "XYZ"].sin_reentrada_hasta_sigue


def test_reanudar_no_levanta_un_bs_vivo() -> None:
    estado = reconstruir([reg("bs", ticker="XYZ", primer_stop="3.9", limite_stop="5.85", max_visto="6.5"),
                          reg("reanudar", ticker="XYZ"), reg("comando", nombre="reanudar_todo")], HOY)
    assert estado.posiciones["XYZ"].estado is EstadoTicker.BS


@pytest.mark.parametrize("nombre, silenciado", [("parar_avisos", True), ("reanudar_avisos", False)],
                         ids=lambda x: f"F7-{x}")
def test_parar_y_reanudar_avisos_bs(nombre: str, silenciado: bool) -> None:
    registros = [reg("bs", ticker="XYZ", primer_stop="3.9", limite_stop="5.85", max_visto="6.5",
                     silenciado=not silenciado),
                 reg("comando", nombre=nombre, args=["XYZ", "BS"], confirmado=True)]
    assert reconstruir(registros, HOY).posiciones["XYZ"].bs.silenciado is silenciado


def test_bs_informe_sin_campo_informes_suma_uno_y_max_visto_no_baja() -> None:
    registros = [reg("bs", ticker="XYZ", primer_stop="3.9", limite_stop="5.85", max_visto="6.5", informes=1),
                 reg("bs_informe", ticker="XYZ", max_visto="6.40"), reg("bs_informe", ticker="XYZ")]
    bs = reconstruir(registros, HOY).posiciones["XYZ"].bs
    assert bs.informes == 3 and bs.max_visto == Decimal("6.5")


def test_intervencion_humana_pausa_global_y_sigue_R_M_03() -> None:
    registros = [reg("pausa", motivo="caso 4"),
                 reg("pausa", ticker="QRS", estado="control_humano", intervencion_humana=True, motivo="ajena")]
    estado = reconstruir(registros, HOY)
    assert estado.pausa_global and estado.posiciones["QRS"].intervencion_humana
    assert estado.posiciones["QRS"].estado is EstadoTicker.CONTROL_HUMANO
    tras_sigue = reconstruir(registros + [reg("comando", nombre="sigue", args=[], confirmado=True)], HOY)
    assert not tras_sigue.pausa_global and not tras_sigue.posiciones["QRS"].intervencion_humana
    tras_sigue_qrs = reconstruir(registros + [reg("comando", nombre="sigue", args=["QRS"])], HOY)
    assert tras_sigue_qrs.posiciones["QRS"].estado is EstadoTicker.NORMAL
    assert tras_sigue_qrs.pausa_global                 # el /sigue de un ticker no levanta la pausa global


@pytest.mark.parametrize(
    "comandos, pausa_global, control_humano",
    [(["pausar"], True, False), (["pausar", "reanudar"], False, False), (["apagar"], False, True),
     (["control_humano", "encender"], False, False)],
    ids=["R-M-04-pausar", "R-M-04-reanudar", "R-M-04-apagar", "R-M-04-encender"])
def test_comandos_globales(comandos: list[str], pausa_global: bool, control_humano: bool) -> None:
    estado = reconstruir([reg("comando", nombre=n, args=[], confirmado=True) for n in comandos], HOY)
    assert (estado.pausa_global, estado.control_humano) == (pausa_global, control_humano)


def test_pausa_y_reanudar_de_un_ticker() -> None:
    estado = reconstruir([reg("pausa", ticker="ABCD", motivo="rechazo (R-B-07)"), reg("reanudar", ticker="ABCD")],
                         HOY)
    assert estado.posiciones["ABCD"].estado is EstadoTicker.NORMAL and estado.posiciones["ABCD"].motivo_estado == ""


def test_config_version_es_la_del_ultimo_config() -> None:
    estado = reconstruir([reg("config", config_version=3, sha256="a"), reg("config", config_version=4, sha256="b")],
                         HOY)
    assert estado.config_version == 4


def test_registros_con_valores_raros_no_rompen_reconstruir() -> None:
    registros = [intencion(126800001, qty="no-numero", precio="NaN", lado="ZZ", proposito="inventado"),
                 reg("fill", ticker="XYZ", id_trade="x", token=126800001),
                 reg("lote", lote_id=None), reg("lote", lote_id="XYZ|e|m|entrada", precio_medio="abc", estado="raro"),
                 reg("locate_estado", strategy_id="e"), reg("bs"), reg("pos", ticker="XYZ", neta="?"),
                 reg("comando", nombre=None, args="XYZ")]
    estado = reconstruir(registros, HOY)
    orden = estado.ordenes[126800001]
    assert orden.qty == 0 and orden.precio is None and orden.lado is Lado.COMPRA
    assert orden.proposito is Proposito.DESCONOCIDA
    lote = estado.posiciones["XYZ"].lotes["XYZ|e|m|entrada"]
    assert lote.precio_medio == Decimal("0") and lote.estado is EstadoLote.ABRIENDO


def test_roundtrip_diario_a_reconstruir(diario: Diario, reloj: RelojSimulado, dir_diario: Path) -> None:
    """Lo que escribe `Diario` con tipos vivos (Enum, Decimal) lo entiende `reconstruir`."""
    diario.abrir_dia(HOY, config_version=2)
    diario.anotar("senal", ticker="XYZ", senal_id=LOTE_XYZ, tipo="entrada")
    diario.anotar("lote", ticker="XYZ", lote_id=LOTE_XYZ, strategy_id="prueba-1", pedidas=1000,
                  estado=EstadoLote.ABRIENDO, nivel_stop=Decimal("3.90"))
    diario.anotar("orden_intencion", ticker="XYZ", token=126800001, lado=Lado.CORTO, qty=1000,
                  tipo_orden=TipoOrden.LIMITE, precio=Decimal("3.45"), proposito=Proposito.ENTRADA_AGREGAR,
                  lote_id=LOTE_XYZ, origen=Origen.EJECUTOR)
    reloj.avanzar(0.01)
    diario.anotar("orden_enviada", ticker="XYZ", token=126800001)
    reloj.avanzar(0.2)
    diario.anotar("fill", ticker="XYZ", id_trade=1, token=126800001, id_orden=501, lado=Lado.CORTO, qty=1000,
                  precio=Decimal("3.45"))
    diario.cerrar()
    estado = reconstruir(LectorDiario(dir_diario).leer(HOY), HOY)
    orden = estado.ordenes[126800001]
    assert orden.lado is Lado.CORTO and orden.precio == Decimal("3.45") and orden.estado is EstadoOrden.EXECUTED
    assert orden.enviada_en == pytest.approx(1000.01) and estado.id_a_token == {501: 126800001}
    assert estado.posiciones["XYZ"].neta_fills == -1000
    assert estado.posiciones["XYZ"].lotes[LOTE_XYZ].nivel_stop == Decimal("3.90")
    assert estado.senales_vistas == {LOTE_XYZ} and estado.fase is Fase.CANARIO


def test_reinicio_mismo_dia_reconstruye_y_no_reutiliza_tokens(dir_diario: Path, reloj: RelojSimulado) -> None:
    """H-2: tras relanzar el ejecutor, el generador de tokens sigue detrás del último usado."""
    from app.bot_das.tokens import GeneradorTokens

    d = Diario(dir_diario, reloj, "ejecutor", "v", Fase.CANARIO)
    gen = GeneradorTokens(Origen.EJECUTOR, HOY)
    for _ in range(3):
        d.anotar("orden_intencion", ticker="XYZ", token=gen.siguiente(), lado=Lado.CORTO, qty=10)
    d.cerrar()
    reloj.avanzar(60)
    estado = reconstruir(LectorDiario(dir_diario).leer(HOY), reloj.hoy())
    nuevo = GeneradorTokens(Origen.EJECUTOR, HOY, ultimo_seq=estado.ultimo_seq_token)
    assert nuevo.siguiente() not in estado.ordenes
    assert nuevo.ultimo_seq == 4


def test_reconstruir_no_mira_el_dia_del_reloj() -> None:
    """Puro: `hoy` manda (un token de hoy deja de ser «nuestro» si se reconstruye como si fuera mañana)."""
    registros = [intencion(126800001)]
    assert 126800001 in reconstruir(registros, HOY).ordenes
    assert reconstruir(registros, HOY + timedelta(days=1)).ordenes == {}


# ── claves REALES de decisor / ejecutor / vigilante (DC-01, DC-02, DC-04, DC-05) ──
def fill_decisor(token: int, id_trade, id_orden: int, qty: int, *, lado: str = "SS", precio: str = "3.45",
                 origen: str = "trade", eco: bool = False, simulado: bool = False, proposito: str = "entrada_agregar",
                 ticker: str = "XYZ", t: str = "09:31:20.000", **extra) -> Registro:
    """Un `fill` con EXACTAMENTE las claves de `decisor._datos_fill` (id_trade None en el Execute, eco en su %TRADE)."""
    return reg("fill", t=t, id_trade=id_trade, token=token, id_orden=id_orden, ticker=ticker, lado=lado, qty=qty,
               precio=precio, ruta="SAGEREB", hora="09:31:20", liq=None if id_trade is None else "A",
               ecn_fee=None if id_trade is None else "-0.80", simulado=simulado, origen=origen, eco=eco,
               proposito=proposito, neta_fills=None, version_stops=None, **extra)


def test_DC_02_execute_sin_trade_cuenta_y_el_eco_no_suma_dos_veces() -> None:
    """DC-02: Execute → fill(id_trade=None) cuenta; el %TRADE posterior (eco=True) solo le pone el id real."""
    base = [arranque("real"), intencion(126800001, qty=1200),
            reg("orden_act", ticker="XYZ", token=126800001, id=501, accion="Accept", qty=1200, precio="3.45"),
            reg("orden_act", ticker="XYZ", token=126800001, id=501, accion="Execute", qty=400, precio="3.45"),
            fill_decisor(126800001, None, 501, 400, origen="execute")]
    # 1) crash entre el Execute y el %TRADE: la neta NO se pierde
    tras_crash = reconstruir(base, HOY)
    assert tras_crash.posiciones["XYZ"].neta_fills == -400
    (solo,) = tras_crash.fills[126800001]
    assert solo.id_trade < 0 and solo.qty == 400                   # id sintético negativo, como el decisor
    assert tras_crash.ordenes[126800001].llenas == 400 and tras_crash.posiciones["XYZ"].version_stops == 1
    # 2) llega el %TRADE (eco): mismo resultado, con el id real puesto y sin sumar dos veces
    con_eco = reconstruir(base + [fill_decisor(126800001, 7001, 501, 400, eco=True)], HOY)
    assert con_eco.posiciones["XYZ"].neta_fills == -400
    assert [f.id_trade for f in con_eco.fills[126800001]] == [7001]
    assert con_eco.fills[126800001][0].liq == "A" and con_eco.fills[126800001][0].ecn_fee == Decimal("-0.80")
    assert con_eco.ordenes[126800001].llenas == 400 and con_eco.posiciones["XYZ"].version_stops == 1
    # 3) y el volcado del #Trade tras una reconexión (mismo id, sin eco) tampoco suma
    repetido = reconstruir(base + [fill_decisor(126800001, 7001, 501, 400, eco=True),
                                   fill_decisor(126800001, 7001, 501, 400)], HOY)
    assert repetido.posiciones["XYZ"].neta_fills == -400


def test_DC_02_dos_execute_iguales_sin_trade_cuentan_los_dos() -> None:
    """Dos Execute de 100 de la misma orden sin %TRADE: 200 (el dedupe por id solo es para ids reales)."""
    registros = [intencion(126800001, qty=1200), fill_decisor(126800001, None, 501, 100, origen="execute"),
                 fill_decisor(126800001, None, 501, 100, origen="execute"),
                 fill_decisor(126800001, 7001, 501, 100, eco=True)]
    estado = reconstruir(registros, HOY)
    assert estado.posiciones["XYZ"].neta_fills == -200
    assert sorted(f.id_trade for f in estado.fills[126800001])[-1] == 7001
    assert len([f for f in estado.fills[126800001] if f.id_trade < 0]) == 1


def test_DC_02_eco_sin_su_execute_en_el_diario_cuenta() -> None:
    """Si la línea del Execute se perdió (línea partida), el eco es la única huella del fill: cuenta."""
    estado = reconstruir([intencion(126800001), fill_decisor(126800001, 7001, 501, 300, eco=True)], HOY)
    assert estado.posiciones["XYZ"].neta_fills == -300 and [f.id_trade for f in estado.fills[126800001]] == [7001]


def test_DC_02_lado_desconocido_toma_el_de_su_orden() -> None:
    estado = reconstruir([intencion(126800001), fill_decisor(126800001, 9, 501, 300, lado="??")], HOY)
    assert estado.posiciones["XYZ"].neta_fills == -300


def test_DC_01_orden_simulada_no_machaca_la_intencion_en_sombra() -> None:
    """DC-01: en SOMBRA el ejecutor escribe orden_simulada {token, ticker, proposito, fills_simulados, regla}."""
    registros = [arranque("sombra"),
                 intencion(126800001, qty=1200, lado="SS", tipo_orden="LMT", precio="3.45", t="09:31:00.000"),
                 reg("orden_simulada", t="09:31:00.010", token=126800001, ticker="XYZ", proposito="entrada_agregar",
                     fills_simulados=[], regla="R-O-03", mono=20862.43),
                 intencion(126800002, lado="B", qty=400, tipo_orden="STOPLMTP", precio="4.02", stop="3.90",
                       ruta="STOP", proposito="stop", t="09:31:20.110"),
                 reg("orden_simulada", t="09:31:20.115", token=126800002, ticker="XYZ", proposito="stop",
                     fills_simulados=[], regla="R-O-03", mono=20880.115)]
    estado = reconstruir(registros, HOY)
    entrada, stop = estado.ordenes[126800001], estado.ordenes[126800002]
    assert (entrada.lado, entrada.qty, entrada.tipo, entrada.precio, entrada.lote_id) == (
        Lado.CORTO, 1200, TipoOrden.LIMITE, Decimal("3.45"), "XYZ|e|2026-09-25 09:30:00|entrada")
    assert entrada.enviada_en == pytest.approx(20862.43)
    assert (stop.lado, stop.qty, stop.tipo, stop.stop, stop.precio, stop.proposito) == (
        Lado.COMPRA, 400, TipoOrden.STOP_LIMITE_PP, Decimal("3.90"), Decimal("4.02"), Proposito.STOP)


def test_DC_01_orden_simulada_con_bug_no_salio_y_sin_intencion_se_crea() -> None:
    bug = reconstruir([intencion(126800001),
                       reg("orden_simulada", token=126800001, ticker="XYZ", bug=True, error="x", fills_simulados=[],
                           regla="R-O-03", mono=5.0)], HOY)
    assert bug.ordenes[126800001].enviada_en == 0.0 and bug.ordenes[126800001].qty == 1000
    sola = reconstruir([reg("orden_simulada", token=126800009, ticker="XYZ", proposito="stop", mono=7.0)],
                       HOY)
    assert sola.ordenes[126800009].proposito is Proposito.STOP and sola.ordenes[126800009].enviada_en == 7.0


def _con_stop_y_replace(*acciones: str) -> list[Registro]:
    """Stop aceptado + replace_intencion y, DESPUÉS (seq mayor), un `orden_act` por cada acción pedida."""
    base = [arranque("real"),
            intencion(126800002, lado="B", qty=400, tipo_orden="STOPLMTP", precio="4.02", stop="3.90", ruta="STOP",
                      proposito="stop"),
            reg("orden_act", ticker="XYZ", token=126800002, id=502, accion="Accept", qty=400, precio="4.02"),
            # el ejecutor NO pone ticker en replace_intencion (ejecutor._reemplazar): se casa por token
            reg("replace_intencion", id_das=502, token=126800002, qty=800, stop="3.80", precio="3.92", version=2,
                serie="stops:XYZ", motivo="neta 800", linea="REPLACE 502 800 STOPLMTP 3.8 3.92", regla="M6")]
    return base + [reg("orden_act", ticker="XYZ", token=126800002, id=502, accion=a, qty=800, precio="3.92",
                       notas="too late" if a == "ReplaceRej" else "") for a in acciones]


def test_DC_04_replace_confirmado_aplica_qty_precio_y_stop() -> None:
    """DC-04: intención + replace_intencion + «Replaced» → el stop NUEVO (como decisor._reemplazo_pedido)."""
    estado = reconstruir(_con_stop_y_replace("Replaced"), HOY)
    o = estado.ordenes[126800002]
    assert (o.qty, o.lvqty, o.stop, o.precio) == (800, 800, Decimal("3.80"), Decimal("3.92"))


def test_DC_04_replace_rechazado_conserva_el_viejo() -> None:
    estado = reconstruir(_con_stop_y_replace("ReplaceRej", "Replaced"), HOY)
    o = estado.ordenes[126800002]
    assert (o.qty, o.stop, o.precio) == (400, Decimal("3.90"), Decimal("4.02"))


def test_DC_04_replace_sin_confirmar_no_cambia_nada() -> None:
    o = reconstruir(_con_stop_y_replace(), HOY).ordenes[126800002]
    assert (o.qty, o.stop, o.precio) == (400, Decimal("3.90"), Decimal("4.02"))


def test_DC_04_con_parte_llena_y_share_abierta_o_total_A_02() -> None:
    """Stop con 100 llenas: share ABIERTA (defecto) → qty = 100 + 300; con share TOTAL → qty = 300 (A-02)."""
    registros = [intencion(126800002, lado="B", qty=400, tipo_orden="STOPLMTP", precio="4.02", stop="3.90",
                           proposito="stop"),
                 reg("orden_act", ticker="XYZ", token=126800002, id=502, accion="Accept"),
                 fill_decisor(126800002, 11, 502, 100, lado="B", proposito="stop"),
                 reg("replace_intencion", id_das=502, token=126800002, qty=300, stop="3.90", precio="4.02"),
                 reg("orden_act", ticker="XYZ", token=126800002, id=502, accion="Replaced")]
    abierta = reconstruir(registros, HOY).ordenes[126800002]
    assert (abierta.qty, abierta.lvqty, abierta.llenas) == (400, 300, 100)
    total = reconstruir(registros, HOY, replace_share_es_abierta=False).ordenes[126800002]
    assert (total.qty, total.lvqty) == (300, 200)


def test_DC_05_dentro_de_un_proceso_manda_el_seq_aunque_el_reloj_retroceda() -> None:
    """DC-05: el reloj de pared da un paso atrás (orden_act con t ANTERIOR a su intención, seq posterior)."""
    registros = [reg("arranque", t="09:30:00.000", seq=1, fase="real"),
                 reg("orden_intencion", t="09:31:02.500", seq=2, ticker="XYZ", token=126800001, lado="SS", qty=100,
                     tipo_orden="LMT", precio="3.45", proposito="entrada_agregar"),
                 reg("orden_act", t="09:31:00.100", seq=3, ticker="XYZ", token=126800001, id=501, accion="Accept"),
                 reg("fill", t="09:31:00.200", seq=4, ticker="XYZ", id_trade=7001, id_orden=501, lado="SS", qty=100,
                     precio="3.45")]
    ordenados = mod_diario.ordenar_registros(list(reversed(registros)))
    assert [r.seq for r in ordenados] == [1, 2, 3, 4]
    estado = reconstruir(registros, HOY)
    assert estado.id_a_token == {501: 126800001}                     # el %TRADE sin token se casa por id
    assert estado.posiciones["XYZ"].neta_fills == -100


def test_DC_05_entre_procesos_se_mezcla_por_t() -> None:
    ejecutor = [reg("x", t="09:31:00.000", seq=10), reg("y", t="09:32:00.000", seq=11)]
    vigilante = [reg("v", t="09:31:30.000", seq=3, proceso="vigilante")]
    assert [r.tipo for r in mod_diario.ordenar_registros(ejecutor + vigilante)] == ["x", "v", "y"]
    assert [r.tipo for r in mod_diario.ordenar_registros(vigilante + ejecutor)] == ["x", "v", "y"]


# ── E2c-01: órdenes ajenas tratadas ─────────────────────────────────────
def test_E2c_01_ajenas_tratadas_sobreviven_al_reinicio() -> None:
    """E2c-01: `ajenas_tratadas {ids, ticker}` (y la pausa global del caso 4) rellenan `estado.ordenes_ajenas`:
    tras /sigue y un reinicio, el volcado de GET ORDERS no vuelve a pausar por las mismas órdenes manuales."""
    from app.bot_das.reglas import reconciliacion

    registros = [reg("orden_ajena_vista", id=900, token=None, ticker="QRS", lado="B", qty=200, order_src="Manual",
                     estado="Accepted", regla="R-K-02"),
                 reg("ajenas_tratadas", ids=[900], ticker="QRS"),
                 reg("pausa", pausa_global=True, intervencion_humana=True, ticker_ajeno="QRS", ordenes_ajenas=[900, 901],
                     motivo="intervención humana", regla="R-M-03"),
                 reg("comando", nombre="sigue", args=[], confirmado=True)]
    estado = reconstruir(registros, HOY)
    assert sorted(estado.ordenes_ajenas) == [900, 901] and estado.pausa_global is False
    ajena = estado.ordenes_ajenas[900]
    assert (ajena.ticker, ajena.lado, ajena.qty, ajena.estado, ajena.order_src) == (
        "QRS", "B", 200, EstadoOrden.ACCEPTED, "Manual")
    assert estado.ordenes_ajenas[901].estado is EstadoOrden.DESCONOCIDO and estado.ordenes_ajenas[901].ticker == "QRS"
    assert reconciliacion.PETICION_PAUSA_GLOBAL == "pausa"
    # `orden_ajena_vista` sola (vista, aún sin tratar) NO cuenta: si el proceso murió antes, se trata al volver
    assert reconstruir(registros[:1], HOY).ordenes_ajenas == {}


# ── /apagar y /encender ────────────────────────────────────────────────
def test_apagar_y_encender_reconstruyen_vigilando() -> None:
    """Alineado con decisor._ejecutar_comando: /apagar → vigilando=False + control_humano; /encender lo deshace."""
    apagado = reconstruir([reg("comando", nombre="apagar", args=[], confirmado=True)], HOY)
    assert apagado.vigilando is False and apagado.control_humano is True
    encendido = reconstruir([reg("comando", nombre="apagar", args=[], confirmado=True),
                             reg("comando", nombre="encender", args=[], confirmado=True)], HOY)
    assert encendido.vigilando is True and encendido.control_humano is False


def test_DC_03_sigue_ticker_con_la_forma_del_decisor_levanta_el_veto() -> None:
    """DC-03 / G1A-08: el decisor anota /sigue X con `_anotar_comando` (nombre, args=[X], chat_id, id, confirmado,
    original); reconstruir levanta el veto R-G-03 de ESE ticker y no la pausa global."""
    registros = [reg("bs", ticker="XYZ", evento="activado", primer_stop="3.9", limite_stop="5.85", max_visto="6.5"),
                 reg("bs", ticker="XYZ", evento="cerrado", dentro_del_margen=True, regla="R-G-03"),
                 reg("pausa", motivo="caso 4"),
                 reg("comando", nombre="sigue", args=["XYZ"], chat_id=111, id=7, confirmado=True, original="sigue")]
    estado = reconstruir(registros, HOY)
    assert estado.posiciones["XYZ"].sin_reentrada_hasta_sigue is False and estado.pausa_global is True


# ── memoria_decisor (E1-03, G1A-18/G1B-18, G1A-12/G1B-10, G1B-09) ──────
def test_E1_03_k_de_halts_por_ticker_desde_el_diario() -> None:
    """E1-03: k se SIEMBRA al arrancar con el mayor `k` de los `halt`/`halt_reapertura` del día (claves del decisor
    y de halts.al_entrar_en_halt)."""
    registros = [reg("halt", ticker="XYZ", ta="LUDP", tat="09:35:00", k=1, sin_posicion=True),
                 reg("halt_reapertura", ticker="XYZ", k=1, precio="4.10", decision=None),
                 reg("halt", ticker="XYZ", ta="LUDP", tipo="LULD", franja="RTH", precio_parada="4.50", neta=-300, k=2,
                     decision=None),
                 reg("halt", ticker="ABC", ta="T1", k=0)]
    memoria = mod_diario.memoria_decisor(registros, HOY)
    assert memoria.k_halts_up == {"XYZ": 2, "ABC": 0}
    assert memoria.halt_hoy == {"XYZ", "ABC"}
    assert mod_diario.memoria_decisor([], HOY) == mod_diario.MemoriaDecisor()


def test_G1A_18_veto_R_F_03_stop_hoy_y_reapertura() -> None:
    """G1A-18 / G1B-18: stop_hoy con fills de stop o de salida del halt (HALT_*); reapertura_ok con la primera vela."""
    registros = [intencion(126800002, lado="B", tipo_orden="STOPLMTP", proposito="desconocida", qty=100),
                 reg("halt", ticker="XYZ", k=1),
                 fill_decisor(126800002, 21, 502, 100, lado="B", proposito="desconocida"),   # stop sin propósito
                 fill_decisor(126800003, 22, 503, 100, lado="B", proposito="halt_open", ticker="ABC"),
                 fill_decisor(126800004, 23, 504, 100, lado="B", proposito="tp_agregar", ticker="MNO"),
                 fill_decisor(126800005, 24, 505, 100, lado="B", proposito="stop", ticker="EFG", eco=True),
                 reg("halt_primera_vela", ticker="XYZ", pct="2.1", k=1, reentrada=True)]
    memoria = mod_diario.memoria_decisor(registros, HOY)
    assert memoria.stop_hoy == {"XYZ", "ABC"}                     # el TP no veta; el eco no es un fill nuevo
    assert memoria.reapertura_ok == {"XYZ"}
    # un halt posterior vuelve a exigir la primera vela
    assert mod_diario.memoria_decisor(registros + [reg("halt", ticker="XYZ", k=2)], HOY).reapertura_ok == set()


def test_stop_unico_su_fill_veta_y_un_diario_de_antes_del_29_sep_tambien() -> None:
    """R-F-03 con el stop único (Jaume 29-sep): el fill de `stop` veta la reentrada; un diario escrito ANTES del
    cambio (propósitos `stop_principal`/`stop_emergencia`, que hoy se leen como DESCONOCIDA) sigue vetando, para que
    un reinicio con el diario viejo no vuelva a entrar tras un stop."""
    registros = [fill_decisor(126800002, 21, 502, 100, lado="B", proposito="stop", ticker="XYZ"),
                 fill_decisor(126800003, 22, 503, 100, lado="B", proposito="stop_principal", ticker="ABC"),
                 fill_decisor(126800004, 23, 504, 100, lado="B", proposito="stop_emergencia", ticker="EFG")]
    assert mod_diario.memoria_decisor(registros, HOY).stop_hoy == {"XYZ", "ABC", "EFG"}


def test_bs_de_un_diario_viejo_lee_emergencia_limite_y_el_nuevo_manda() -> None:
    """Cisne negro con el stop único (Jaume 29-sep): el umbral es `limite_stop` (límite del primer stop); un diario
    de antes lo anotaba como `emergencia_limite` y se sigue leyendo; si hay los dos, manda `limite_stop`."""
    viejo = reconstruir([reg("bs", ticker="XYZ", primer_stop="3.9", emergencia_limite="6.36", max_visto="6.5")], HOY)
    assert viejo.posiciones["XYZ"].bs.limite_stop == Decimal("6.36")
    nuevo = reconstruir([reg("bs", ticker="XYZ", primer_stop="3.9", limite_stop="5.85", emergencia_limite="6.36",
                             max_visto="6.5")], HOY)
    assert nuevo.posiciones["XYZ"].bs.limite_stop == Decimal("5.85")
    assert not hasattr(nuevo.posiciones["XYZ"].bs, "emergencia_limite")


def test_G1A_12_control_manual_sobrevive_al_reinicio() -> None:
    """G1A-12 / G1B-10: /cancelar_ordenes X confirmado → manual hasta /reanudar X (nombre reanudar_ticker)."""
    cancelar = reg("comando", nombre="cancelar_ordenes", args=["QRS"], chat_id=1, id=3, confirmado=True,
                   original="cancelar_ordenes")
    memoria = mod_diario.memoria_decisor([cancelar], HOY)
    assert memoria.manual == {"QRS"}
    sin_confirmar = reg("comando", nombre="cancelar_ordenes", args=["ABC"], confirmado=False)
    assert mod_diario.memoria_decisor([sin_confirmar], HOY).manual == set()
    reanudado = reg("comando", nombre="reanudar_ticker", args=["QRS"], confirmado=True, original="reanudar")
    assert mod_diario.memoria_decisor([cancelar, reanudado], HOY).manual == set()
    todo = reg("comando", nombre="reanudar_todo", args=[], confirmado=True)
    assert mod_diario.memoria_decisor([cancelar, todo], HOY).manual == set()


def test_G1B_09_cambios_por_telegram_se_reaplican_y_el_fichero_los_suelta() -> None:
    """G1B-09: /desactivar y /modo_seguridad (config_cambio origen telegram) sobreviven; un config_cambio CM3 del
    fichero aplicado sobre la misma ruta los suelta (decisor._soltar_override)."""
    desactivar = reg("config_cambio", ruta="estrategias.prueba-1.ejecutar", antes=True, despues=False, caliente=True,
                     aplicado=True, origen="telegram")
    seguridad = reg("config_cambio", ruta="modo_seguridad.activo", antes=False, despues=True, caliente=True,
                    aplicado=True, origen="telegram")
    al_desactivar = reg("comando", nombre="cerrar_y_reiniciar", args=["PM (A) prueba"], confirmado=True)
    memoria = mod_diario.memoria_decisor([desactivar, seguridad, al_desactivar], HOY)
    assert memoria.override_estrategia == {"prueba-1": {"ejecutar": False}}
    assert memoria.override_modo_seguridad is True
    assert memoria.al_desactivar_por_arg == {"PM (A) prueba": "cerrar_y_reiniciar"}
    del_fichero = reg("config_cambio", ruta="estrategias.prueba-1.ejecutar", antes=True, despues=True, caliente=True,
                      aplicado=True, config_version=5, regla="CM3")
    rechazado = reg("config_cambio", ruta="modo_seguridad.activo", antes=False, despues=False, caliente=True,
                    aplicado=False, config_version=5, regla="CM3")
    tras = mod_diario.memoria_decisor([desactivar, seguridad, del_fichero, rechazado], HOY)
    assert tras.override_estrategia == {} and tras.override_modo_seguridad is True


# ── DC-06: el diario que escribe el EJECUTOR REAL se reconstruye igual que el estado vivo ──
# Montaje del ejecutor REAL contra el SimuladorDAS: se IMPORTA de test_das_ejecutor (a nivel de módulo), sin copiarlo.
# `vivo` y `motor_falso` son fixtures: importarlas las registra en este módulo.
from test_das_ejecutor import TICKER as _TICKER_VIVO  # noqa: E402
from test_das_ejecutor import Vivo, motor_falso, vivo  # noqa: E402,F401


def _comparar_con_el_vivo(reconstruido, vivo) -> None:
    """DC-06: lo que `reconstruir` saca del diario REAL coincide, campo a campo, con lo que el decisor tiene en memoria."""
    assert reconstruido.fase is vivo.fase
    assert reconstruido.senales_vistas == vivo.senales_vistas
    assert sorted(reconstruido.ordenes) == sorted(vivo.ordenes)
    for token, o in vivo.ordenes.items():
        r = reconstruido.ordenes[token]
        assert (r.ticker, r.lado, r.tipo, r.qty, r.precio, r.stop, r.lote_id, r.proposito, r.llenas, r.origen) == (
            o.ticker, o.lado, o.tipo, o.qty, o.precio, o.stop, o.lote_id, o.proposito, o.llenas, o.origen), token
        assert (r.id_das, r.estado, r.lvqty) == (o.id_das, o.estado, o.lvqty), token
    assert reconstruido.id_a_token == vivo.id_a_token
    assert {t: sorted(f.qty for f in fs) for t, fs in reconstruido.fills.items()} == {
        t: sorted(f.qty for f in fs) for t, fs in vivo.fills.items()}
    assert {t: sorted(f.id_trade for f in fs if f.id_trade > 0) for t, fs in reconstruido.fills.items()} == {
        t: sorted(f.id_trade for f in fs if f.id_trade > 0) for t, fs in vivo.fills.items()}
    for ticker, pos in vivo.posiciones.items():
        rp = reconstruido.posiciones.get(ticker)
        if pos.neta_fills == 0 and not pos.lotes and rp is None:
            continue
        assert rp is not None, ticker
        assert (rp.neta_fills, rp.version_stops, rp.estado, rp.sin_reentrada_hasta_sigue) == (
            pos.neta_fills, pos.version_stops, pos.estado, pos.sin_reentrada_hasta_sigue), ticker
        assert sorted(rp.lotes) == sorted(pos.lotes), ticker
        for lote_id, lote in pos.lotes.items():
            rl = rp.lotes[lote_id]
            assert (rl.llenas, rl.pedidas, rl.estado, rl.nivel_stop, rl.precio_medio) == (
                lote.llenas, lote.pedidas, lote.estado, lote.nivel_stop, lote.precio_medio), lote_id
        # R2-PER-2: el cisne negro (vivo o cerrado) también sale igual del diario
        assert (rp.bs is None) == (pos.bs is None), ticker
        if pos.bs is not None:
            assert (rp.bs.primer_stop, rp.bs.limite_stop, rp.bs.max_visto, rp.bs.informes, rp.bs.silenciado) == (
                pos.bs.primer_stop, pos.bs.limite_stop, pos.bs.max_visto, pos.bs.informes,
                pos.bs.silenciado), ticker
    for clave, loc in vivo.locates.items():
        rl = reconstruido.locates[clave]
        assert (rl.estado, rl.localizadas, rl.usadas, rl.compras, rl.token, rl.coste) == (
            loc.estado, loc.localizadas, loc.usadas, loc.compras, loc.token, loc.coste), clave
    assert reconstruido.gasto_locates_dia == vivo.gasto_locates_dia
    assert (reconstruido.pausa_global, reconstruido.control_humano) == (vivo.pausa_global, vivo.control_humano)
    from app.bot_das.tokens import descomponer
    seqs = [partes[2] for partes in (descomponer(t) for t in vivo.ordenes) if partes and partes[0] is Origen.EJECUTOR]
    assert reconstruido.ultimo_seq_token >= max(seqs, default=0)          # no reutiliza un token tras el reinicio


def _entrada_con_stops(v: Vivo, libro_ordenes) -> list[dict]:
    """Señal de la vela → SS → fill de las 100 → el stop único residente (Jaume 29-sep); devuelve [ese stop]."""
    v.senal_por_vela(_TICKER_VIVO)
    tipo_envio = "orden_simulada" if v.e.cfg.fase is Fase.SOMBRA else "orden_enviada"
    v.paso_hasta(lambda: any(r.tipo == tipo_envio and r.datos.get("proposito") == "entrada_agregar"
                             for r in v.regs()), "envío de la entrada")
    v.sim.cotizar(_TICKER_VIVO, Decimal("3.45"), Decimal("3.47"), last=Decimal("3.45"), volumen=500_000)

    def stops_vivos() -> list[dict]:
        return [o for o in libro_ordenes.ordenes() if o["ticker"] == _TICKER_VIVO and o["tipo"] == "STOPLMTP"
                and o["estado"] in ("Accepted", "Partial")]

    v.paso_hasta(lambda: len(stops_vivos()) == 1, "el stop único")
    v.drenar()
    return sorted(stops_vivos(), key=lambda o: o["stop"])


@pytest.mark.parametrize("fase", ["sombra", "canario"], ids=["DC-06-sombra", "DC-06-canario"])
def test_DC_06_reinicio_con_el_diario_del_ejecutor_real(fase: str, vivo) -> None:
    """DC-06 (y DC-01/DC-02/DC-04 de punta a punta): el ejecutor REAL (construir_desde_env) contra el SimuladorDAS
    en SOMBRA y en CANARIO: locate, señal de la vela, SS, fill, stops residentes y (canario) el stop que dispara.
    Después se relee SU diario con LectorDiario y `reconstruir` debe dar el mismo estado que el decisor vivo."""
    v = vivo(Fase(fase))
    v.preparar(_TICKER_VIVO)
    libro_ordenes = v.e.cliente.emparejador.libro if fase == "sombra" else v.libro
    _entrada_con_stops(v, libro_ordenes)
    regs = v.regs()
    fills = [r for r in regs if r.tipo == "fill"]
    assert fills and (fase != "sombra" or all(f.datos["simulado"] is True for f in fills))
    # el simulador manda el Execute ANTES del %TRADE: el caso de DC-02 (fill sin id + eco) está en este diario
    assert [(f.datos["id_trade"] is None, f.datos["eco"]) for f in fills] == [(True, False), (False, True)]
    assert (fase == "sombra") == any(r.tipo == "orden_simulada" for r in regs)
    vivo_estado = v.e.decisor.estado
    assert vivo_estado.posiciones[_TICKER_VIVO].neta_fills == -100
    _comparar_con_el_vivo(reconstruir(regs, HOY), vivo_estado)
    if fase == "canario":
        (stop,) = v.stops_vivos(_TICKER_VIVO)
        v.sim.cotizar(_TICKER_VIVO, stop["stop"] + Decimal("0.05"), stop["stop"] + Decimal("0.10"),
                      last=stop["stop"] + Decimal("0.10"), volumen=500_000)
        v.paso_hasta(lambda: v.libro.posiciones().get(_TICKER_VIVO) == 0 and not v.stops_vivos(_TICKER_VIVO),
                     "stop y limpieza")
        v.drenar()
        assert vivo_estado.posiciones[_TICKER_VIVO].neta_fills == 0
        _comparar_con_el_vivo(reconstruir(v.regs(), HOY), vivo_estado)
        memoria = mod_diario.memoria_decisor(v.regs(), HOY)
        assert memoria.stop_hoy == {_TICKER_VIVO}                    # el fill del stop quedó en el diario


def test_R2_PER_2_DC_06_stop_lleno_en_parte_y_cisne_negro_cerrado_se_reconstruyen(vivo) -> None:
    """R2-PER-2 (DC-06) con el stop único (Jaume 29-sep): ejecutor REAL contra el SimuladorDAS en CANARIO, (1) el
    stop dispara y se llena en PARTE → sigue vivo con lo que le queda (ninguna compra más, ningún REPLACE: nunca dos
    compras por las mismas acciones) y (2) el precio pasa de largo su límite (L + 50 %) → cisne negro activado,
    informe periódico y «/cerrar XYZ SI». Tras cada paso, `reconstruir` sobre SU diario coincide con decisor.estado:
    órdenes (lvqty tras el parcial), fills, neta, lotes, bs y sin_reentrada_hasta_sigue. (El REPLACE reconstruido
    lo cubren los DC-04 y el fixture del diario.)"""
    from app.bot_das import comandos

    v = vivo(Fase.CANARIO)
    v.preparar(_TICKER_VIVO)
    estado = v.e.decisor.estado
    (stop,) = _entrada_con_stops(v, v.libro)
    assert stop["qty"] == 100 and stop["precio"] == stop["stop"] * Decimal("1.5")      # R-C-01 v4
    tok_stop = stop["token"]
    compras_antes = len([r for r in v.regs() if r.tipo == "orden_enviada" and r.datos.get("lado") == "B"])

    # (1) el stop dispara y solo hay 50 acciones al ask: se llena en parte y la otra mitad queda viva
    v.sim.cotizar(_TICKER_VIVO, stop["stop"], stop["stop"] + Decimal("0.01"),
                  last=stop["stop"] + Decimal("0.01"), volumen=500_000, tamano_ask=50)

    def stop_sim() -> dict:
        return next(o for o in v.libro.ordenes() if o["token"] == tok_stop)

    v.paso_hasta(lambda: estado.posiciones[_TICKER_VIVO].neta_fills == -50, "fill parcial del stop")
    v.paso_hasta(lambda: stop_sim()["lvqty"] == 50, "el stop sigue vivo con 50")
    v.drenar()
    regs = v.regs()
    assert not any(r.tipo == "replace_intencion" and r.datos.get("token") == tok_stop for r in regs)
    assert len([r for r in regs if r.tipo == "orden_enviada" and r.datos.get("lado") == "B"]) == compras_antes
    assert v.libro.posiciones()[_TICKER_VIVO] == -50
    reconstruido = reconstruir(regs, HOY)
    assert reconstruido.ordenes[tok_stop].lvqty == 50
    _comparar_con_el_vivo(reconstruido, estado)

    # (2) cisne negro: el precio pasa de largo el límite del stop (lo que le queda ya no puede llenar)
    salto = (stop["precio"] * 2).quantize(Decimal("0.01"))
    v.sim.cotizar(_TICKER_VIVO, salto, salto + Decimal("0.20"), last=salto + Decimal("0.10"), volumen=900_000)
    v.paso_hasta(lambda: estado.posiciones[_TICKER_VIVO].bs is not None, "activación del cisne negro")
    v.drenar()
    assert estado.posiciones[_TICKER_VIVO].estado is EstadoTicker.BS
    _comparar_con_el_vivo(reconstruir(v.regs(), HOY), estado)
    # un informe de la cadencia (60 s después de la activación)
    v.reloj.avanzar(61)
    v.paso_hasta(lambda: estado.posiciones[_TICKER_VIVO].bs.informes >= 1, "informe periódico del cisne negro")
    v.drenar()
    assert estado.posiciones[_TICKER_VIVO].bs is not None
    _comparar_con_el_vivo(reconstruir(v.regs(), HOY), estado)

    # /cerrar XYZ SI: el stop se cancela antes y se compra lo que sigue corto
    chat = 111
    c = comandos.parsear(f"/cerrar {_TICKER_VIVO} SI", chat, frozenset({chat}), id_comando="tg:r2per2")
    assert c is not None and c.requiere == comandos.REQUIERE_SI
    v.e.buzon.al_comando(c)
    v.drenar()
    for _ in range(20):                    # E2-03: la compra sale tras ver el stop cancelado (esperas de 0,5 s)
        if estado.posiciones[_TICKER_VIVO].neta_fills == 0 and estado.posiciones[_TICKER_VIVO].bs is None:
            break
        v.reloj.avanzar(0.5)
        v.drenar(0.1)
    else:
        pytest.fail(f"cierre humano del cisne negro sin terminar; diario {[r.tipo for r in v.regs()][-15:]}")
    v.drenar()
    pos = estado.posiciones[_TICKER_VIVO]
    assert pos.sin_reentrada_hasta_sigue is True and v.libro.posiciones()[_TICKER_VIVO] == 0
    regs = v.regs()
    assert [r.datos.get("evento") for r in regs if r.tipo == "bs" and r.datos.get("ticker") == _TICKER_VIVO][-1] == "cerrado"
    reconstruido = reconstruir(regs, HOY)
    assert reconstruido.posiciones[_TICKER_VIVO].bs is None
    assert reconstruido.posiciones[_TICKER_VIVO].sin_reentrada_hasta_sigue is True
    _comparar_con_el_vivo(reconstruido, estado)


def test_memoria_decisor_idempotente_y_sin_orden() -> None:
    registros = [reg("halt", ticker="XYZ", k=1), reg("halt", ticker="XYZ", k=2),
                 reg("comando", nombre="cancelar_ordenes", args=["XYZ"], confirmado=True)]
    primero = mod_diario.memoria_decisor(registros, HOY)
    assert mod_diario.memoria_decisor(registros + registros, HOY) == primero
    assert mod_diario.memoria_decisor(list(reversed(registros)), HOY) == primero


def test_locates_por_fases_se_reconstruyen_jaume_29_sep() -> None:
    """H-2 + Jaume 29-sep: la fase del locate, la referencia «a tiro», la N recalculada, la N original (`qty_pedida`)
    y la PRIMERA señal principal de cada pareja salen del diario igual que en caliente."""
    registros = [
        reg("locate_estado", ticker="XYZ", strategy_id="s1", estado="buscando", qty=113, qty_ajustada=100,
            qty_pedida=113),
        reg("locate_estado", ticker="XYZ", strategy_id="s1", fase="B", precio_senal="3.45"),
        reg("senal_principal", ticker="XYZ", strategy_id="s1", senal_id="XYZ|s1|09:29|entrada"),
        reg("senal_principal", ticker="XYZ", strategy_id="s1", senal_id="XYZ|s1|09:30|entrada"),   # no pisa la 1.ª
        reg("locate_estado", ticker="ABC", strategy_id="s1", estado="buscando", qty=300),
        reg("locate_estado", ticker="ABC", strategy_id="s1", pedidas_n=250, fase="C", precio_senal=None),
    ]
    estado = reconstruir(registros, HOY)
    xyz, abc = estado.locates[("XYZ", "s1")], estado.locates[("ABC", "s1")]
    assert (xyz.fase, xyz.precio_senal, xyz.pedidas) == ("B", Decimal("3.45"), 113)
    assert (abc.fase, abc.precio_senal, abc.pedidas) == ("C", None, 250)
    assert estado.senales_principales == {("XYZ", "s1"): "XYZ|s1|09:29|entrada"}
