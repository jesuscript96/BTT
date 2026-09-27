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
        pytest.param({Proposito.STOP_PRINCIPAL: 1}, {"stop_principal": 1}, id="s8-clave-enum"),
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
def test_leer_une_y_ordena_los_dos_diarios(registros_fixture: list[Registro]) -> None:
    assert len(registros_fixture) == 93 + 12
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
    assert (mnop.bs.primer_stop, mnop.bs.emergencia_limite, mnop.bs.max_visto) == (
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
    registros = [reg("fill", ticker="XYZ", id_trade=1, token=126800001, lado="SS", qty=400, precio="3"),
                 reg("discrepancia", ticker="XYZ", detalle="caso 6", neta_fills=-400, neta_das=-300)]
    pos = reconstruir(registros, HOY).posiciones["XYZ"]
    assert pos.neta_fills == -300 and pos.neta_das == -300


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
    base = [reg("bs", ticker="XYZ", evento="activado", primer_stop="3.9", emergencia_limite="6.36", max_visto="6.5"),
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
    estado = reconstruir([reg("bs", ticker="XYZ", primer_stop="3.9", emergencia_limite="6.36", max_visto="6.5"),
                          reg("reanudar", ticker="XYZ"), reg("comando", nombre="reanudar_todo")], HOY)
    assert estado.posiciones["XYZ"].estado is EstadoTicker.BS


@pytest.mark.parametrize("nombre, silenciado", [("parar_avisos", True), ("reanudar_avisos", False)],
                         ids=lambda x: f"F7-{x}")
def test_parar_y_reanudar_avisos_bs(nombre: str, silenciado: bool) -> None:
    registros = [reg("bs", ticker="XYZ", primer_stop="3.9", emergencia_limite="6.36", max_visto="6.5",
                     silenciado=not silenciado),
                 reg("comando", nombre=nombre, args=["XYZ", "BS"], confirmado=True)]
    assert reconstruir(registros, HOY).posiciones["XYZ"].bs.silenciado is silenciado


def test_bs_informe_sin_campo_informes_suma_uno_y_max_visto_no_baja() -> None:
    registros = [reg("bs", ticker="XYZ", primer_stop="3.9", emergencia_limite="6.36", max_visto="6.5", informes=1),
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
