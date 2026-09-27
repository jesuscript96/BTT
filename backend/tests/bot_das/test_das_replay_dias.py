"""Test DORADO del replay de días reales (lote G2, §10 «test_das_replay_dias»; R-O-02, injerto §8.24, riesgo 28).

QUÉ PRUEBA.
  Para cada `fixtures/esperado_AAAA-MM-DD.jsonl` con su grabación real
  `D:/bot_senales/grabaciones/AM_AAAA-MM-DD.jsonl.gz`, reproduce el día contra
  el EJECUTOR REAL en fase SOMBRA (motor de alertas real, `FuenteGrabacion`,
  DAS simulado por socket alimentado vela a vela con el spread DECLARADO en
  el guion) y compara con lo esperado: las SEÑALES, las DECISIONES (tipo y
  motivo), los TOKENS y la SECUENCIA DE ACCIONES (tipo, ticker, propósito,
  lado, tipo de orden, estado). NO compara precios, cantidades de fill ni
  horas (injerto §8.24: los fills del replay no son comparables, riesgo 28).
  Además, sin datos reales, prueba las funciones que extraen y comparan (con
  el diario de ejemplo de fixtures).

POR QUÉ ASÍ. El dorado detecta el cambio de COMPORTAMIENTO (una señal que ya
no se toma, un motivo de descarte distinto, un token que salta, una acción de
más) al tocar el motor o el decisor. Los precios dependen del modelo de
spread; las decisiones no deberían.

LAS TRAMPAS.
  * Se salta con motivo si no existe la carpeta de grabaciones o no hay
    ningún `esperado_*.jsonl` (este test NO crea el fichero esperado: lo
    genera una persona el primer día grabado, con `resultado_de` sobre el
    diario de un replay revisado a mano, y lo sube al repo).
  * Formato del esperado: JSONL, una línea por clase,
    `{"clase": "senales"|"decisiones"|"tokens"|"acciones", "valor": [...]}`;
    los elementos son listas (tuplas en JSON) en orden de aparición.
  * Config y guion del día: `fixtures/config_replay_AAAA-MM-DD.json` y
    `fixtures/guion_replay_AAAA-MM-DD.json` si existen; si no,
    `config_ejemplo.json` y un guion vacío (spread por defecto 0,5 %).
  * La referencia de Massive (ficha/splits) y el calendario son dobles fijos
    y sin red: el replay es reproducible (en vivo, Massive podría excluir un
    ticker que aquí se opera; eso no es comportamiento del bot).
  * `@pytest.mark.slow`: el conftest la registra (G2-09); se excluye con
    `-m "not slow"`.
  * G2-06: el gancho `paso` DEVUELVE las líneas de la vela y el ejecutor
    aplica su `$Quote` antes de la señal (sin eso el dorado compararía un día
    sin una sola orden). El `esperado_*.jsonl` de un día real lo genera y lo
    REVISA una persona (entrada, stop y salida a la vista); hasta entonces el
    dorado se salta con motivo.
  * R2-PRO-4: sin esperar a ese fichero, UNA entrada completa del replay
    (radar → SLPRICEINQUIRE con `%SLRET 2 AlreadyShortable` → entrada → fill
    → principal + emergencia → salida por el stop) la ejercita con el DAS
    simulado `test_das_ejecutor.test_r2_pro_4_replay_con_locate_already_
    shortable_entra_llena_pone_stops_y_sale_por_stop` (grabación recortada
    de fixtures, motor falso). El guion de un dorado real debe hacer lo
    mismo: `LibroSimulado.configurar_locate(ticker, fallo="AlreadyShortable")`
    (o un precio que pase el EV) y el radar del ticker; sin eso toda señal
    cae en «sin locates libres (R-H-04)».
"""
from __future__ import annotations

import dataclasses
import json
import re
import threading
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable, Optional

import pytest

from app.bot_das.diario import LectorDiario, leer_texto
from app.bot_das.reloj import ET, RelojSimulado
from app.bot_das.tipos import Ficha, Registro

BACKEND = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).parent / "fixtures"
GRABACIONES = Path("D:/bot_senales/grabaciones")
CUENTA = "CUENTA_PRUEBA"
USUARIO = "usuario_replay"
CLAVE_DAS = "clave-replay-inventada"
PLAZO_REPLAY_S = 600.0                     # un día entero de grabación en tiempo simulado
_RE_ESPERADO = re.compile(r"^esperado_(\d{4}-\d{2}-\d{2})\.jsonl$")

CLASES = ("senales", "decisiones", "tokens", "acciones")
TIPOS_SENAL = ("senal", "senal_repetida", "senal_descartada")
TIPOS_ACCION = ("orden_intencion", "cancel_intencion", "replace_intencion", "locate_intencion", "lote", "pausa",
                "reanudar", "bs")
CAMPOS_ACCION = ("ticker", "proposito", "lado", "tipo_orden", "token", "lote_id", "estado", "motivo")


# ═══════════════════════════ extracción y comparación (puras) ════════════
def _tipo_y_datos(r: Any) -> tuple[str, dict]:
    if isinstance(r, Registro):
        return r.tipo, dict(r.datos)
    if isinstance(r, dict):
        datos = dict(r.get("datos") or {})
        if "ticker" in r and "ticker" not in datos:
            datos["ticker"] = r["ticker"]
        return str(r.get("tipo", "")), datos
    raise TypeError(f"registro no reconocido: {type(r).__name__}")


def resultado_de(registros: Iterable[Any]) -> dict[str, list]:
    """Lo comparable de un diario (R-O-02): señales, decisiones con motivo, tokens y secuencia de acciones, SIN precios.

    Acepta `Registro` o líneas JSON del diario (dict). Cada elemento es una
    lista (así queda igual tras un viaje por JSON).
    """
    senales: list[list] = []
    vistas: set[str] = set()
    decisiones: list[list] = []
    tokens: list[int] = []
    acciones: list[list] = []
    for r in registros:
        tipo, datos = _tipo_y_datos(r)
        if tipo in TIPOS_SENAL:
            senal_id = datos.get("senal_id")
            if senal_id is not None and senal_id not in vistas:
                vistas.add(senal_id)
                senales.append([senal_id, datos.get("ticker")])
            decisiones.append([senal_id, tipo, datos.get("motivo")])
        if tipo == "orden_intencion" and isinstance(datos.get("token"), int):
            tokens.append(datos["token"])
        if tipo in TIPOS_ACCION:
            acciones.append([tipo] + [datos.get(c) for c in CAMPOS_ACCION])
    return {"senales": senales, "decisiones": decisiones, "tokens": tokens, "acciones": acciones}


def escribir_esperado(ruta: Path, resultado: dict[str, list]) -> None:
    """Formato del dorado (para la persona que lo genere; el test no lo llama sobre fixtures)."""
    lineas = [json.dumps({"clase": c, "valor": resultado[c]}, ensure_ascii=False) for c in CLASES]
    Path(ruta).write_text("\n".join(lineas) + "\n", encoding="utf-8")


def leer_esperado(ruta: Path) -> dict[str, list]:
    """Lee `esperado_AAAA-MM-DD.jsonl`. ValueError si una clase falta, se repite o es desconocida."""
    esperado: dict[str, list] = {}
    for n, linea in enumerate(Path(ruta).read_text(encoding="utf-8").splitlines(), start=1):
        if not linea.strip():
            continue
        objeto = json.loads(linea)
        clase = objeto.get("clase") if isinstance(objeto, dict) else None
        if clase not in CLASES or clase in esperado or not isinstance(objeto.get("valor"), list):
            raise ValueError(f"{ruta.name}:{n}: línea no válida (clase {clase!r})")
        esperado[clase] = objeto["valor"]
    faltan = [c for c in CLASES if c not in esperado]
    if faltan:
        raise ValueError(f"{ruta.name}: faltan las clases {faltan}")
    return esperado


def diferencias(esperado: dict[str, list], obtenido: dict[str, list]) -> list[str]:
    """Texto legible de cada diferencia (vacío = igual): primera posición distinta y longitudes, por clase."""
    salida: list[str] = []
    for clase in CLASES:
        a, b = list(esperado.get(clase, [])), list(obtenido.get(clase, []))
        if a == b:
            continue
        i = next((k for k, (x, y) in enumerate(zip(a, b)) if x != y), min(len(a), len(b)))
        salida.append(f"{clase}: esperado {len(a)} elementos, obtenido {len(b)}; primera diferencia en {i}: "
                      f"esperado {a[i] if i < len(a) else '—'} / obtenido {b[i] if i < len(b) else '—'}")
    return salida


def dias_dorados(carpeta: Path = FIXTURES) -> list[date]:
    dias = []
    for p in sorted(carpeta.glob("esperado_*.jsonl")):
        m = _RE_ESPERADO.match(p.name)
        if m:
            dias.append(date.fromisoformat(m.group(1)))
    return dias


# ═══════════════════════════ tests sin datos reales ══════════════════════
def _registros_fixture() -> list[Registro]:
    ruta = FIXTURES / "diario_medio_dia_ejecutor.jsonl"
    return leer_texto(ruta.read_text(encoding="utf-8"), "ejecutor", str(ruta))


def test_r_o_02_resultado_de_extrae_senales_decisiones_tokens_y_acciones_sin_precios() -> None:
    regs = _registros_fixture()
    r = resultado_de(regs)
    assert set(r) == set(CLASES)
    brutos = [(x.tipo, x.datos) for x in regs]
    assert len(r["decisiones"]) == sum(1 for t, _ in brutos if t in TIPOS_SENAL) == 5
    assert len(r["senales"]) == len({d.get("senal_id") for t, d in brutos if t in TIPOS_SENAL})
    assert r["tokens"] == [d["token"] for t, d in brutos if t == "orden_intencion"] and len(r["tokens"]) == 8
    assert [a[0] for a in r["acciones"]] == [t for t, _ in brutos if t in TIPOS_ACCION]
    descartada = next(d for d in r["decisiones"] if d[1] == "senal_descartada")
    assert descartada[2]                                                  # el motivo viaja
    texto = json.dumps(r, ensure_ascii=False)
    for t, d in brutos:                                                   # ni un precio de orden ni de fill
        for campo in ("precio", "stop", "precio_medio"):
            valor = d.get(campo)
            if isinstance(valor, str) and re.fullmatch(r"\d+\.\d+", valor):
                assert f'"{valor}"' not in texto, f"{campo}={valor} de {t} en el resultado"


def test_r_o_02_el_resultado_es_el_mismo_desde_registro_o_desde_json() -> None:
    ruta = FIXTURES / "diario_medio_dia_ejecutor.jsonl"
    lineas = [json.loads(x) for x in ruta.read_text(encoding="utf-8").splitlines() if x.strip()]
    assert resultado_de(lineas) == resultado_de(_registros_fixture())


def test_r_o_02_esperado_ida_y_vuelta_y_comparacion(tmp_path: Path) -> None:
    obtenido = resultado_de(_registros_fixture())
    ruta = tmp_path / "esperado_2026-09-25.jsonl"
    escribir_esperado(ruta, obtenido)
    esperado = leer_esperado(ruta)
    assert diferencias(esperado, obtenido) == []
    assert dias_dorados(tmp_path) == [date(2026, 9, 25)]
    cambiado = json.loads(json.dumps(obtenido))
    cambiado["decisiones"][0][2] = "motivo inventado"
    cambiado["tokens"].append(126899999)
    difs = diferencias(esperado, cambiado)
    assert [d.split(":")[0] for d in difs] == ["decisiones", "tokens"]
    assert "motivo inventado" in difs[0] and "obtenido 9" in difs[1]


@pytest.mark.parametrize("contenido", ['{"clase": "senales", "valor": []}\n',
                                       '{"clase": "precios", "valor": []}\n',
                                       '{"clase": "tokens", "valor": 3}\n'],
                         ids=["faltan-clases", "clase-desconocida", "valor-no-lista"])
def test_r_o_02_un_esperado_mal_formado_no_se_acepta(tmp_path: Path, contenido: str) -> None:
    ruta = tmp_path / "esperado_2026-09-25.jsonl"
    ruta.write_text(contenido, encoding="utf-8")
    with pytest.raises(ValueError):
        leer_esperado(ruta)


# ═══════════════════════════ el dorado (datos reales) ════════════════════
class _ReferenciaFija:
    """Massive sin red: toda acción es común, vieja y sin splits (reproducible)."""

    def ficha(self, ticker: str) -> Ficha:
        return Ficha(ticker=ticker, list_date=date(2020, 1, 1), sic_code="1234", tipo="CS",
                     market_cap=Decimal("100000000"), nombre=ticker)

    def splits_de_hoy(self, dia: date) -> set[str]:
        return set()


class _CalendarioFijo:
    """Franjas por la hora ET; día entero (los días grabados son días de mercado)."""

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


def _parametros_dorado() -> list:
    if not GRABACIONES.is_dir():
        return [pytest.param(None, marks=pytest.mark.skip(reason=f"no existe {GRABACIONES} (R-O-02: sin días grabados)"))]
    dias = dias_dorados()
    if not dias:
        return [pytest.param(None, marks=pytest.mark.skip(
            reason="no hay ningún fixtures/esperado_AAAA-MM-DD.jsonl todavía (se crea el primer día grabado)"))]
    return [pytest.param(d, id=d.isoformat()) for d in dias]


@pytest.mark.slow
@pytest.mark.parametrize("dia", _parametros_dorado())
def test_r_o_02_dorado_de_un_dia_grabado(dia: Optional[date], dir_bot: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """R-O-02 / injerto §8.24: el ejecutor real en SOMBRA sobre el día grabado reproduce señales, decisiones, tokens y
    secuencia de acciones del dorado (sin precios)."""
    assert dia is not None
    grabacion = GRABACIONES / f"AM_{dia.isoformat()}.jsonl.gz"
    if not grabacion.is_file():
        pytest.skip(f"falta la grabación {grabacion.name}")
    ejecutor_mod = pytest.importorskip("app.bot_das.ejecutor")
    mod_config = pytest.importorskip("app.bot_das.config")
    simulador_mod = pytest.importorskip("app.bot_das.simulador_das")
    from app.bot_das.tipos import Fase

    ruta_cfg = FIXTURES / f"config_replay_{dia.isoformat()}.json"
    cfg = mod_config.cargar(ruta_cfg if ruta_cfg.is_file() else FIXTURES / "config_ejemplo.json", CUENTA)
    cfg = dataclasses.replace(cfg, fase=Fase.SOMBRA)
    ruta_guion = FIXTURES / f"guion_replay_{dia.isoformat()}.json"
    programa = simulador_mod.ProgramaGuion.cargar(ruta_guion) if ruta_guion.is_file() else \
        simulador_mod.ProgramaGuion({})
    reloj = RelojSimulado(datetime(dia.year, dia.month, dia.day, 3, 55, tzinfo=ET))
    simulador = simulador_mod.SimuladorDAS(simulador_mod.LibroSimulado(), reloj)
    host, puerto = simulador.arrancar()
    for nombre, valor in {"DAS_API_HOST": host, "DAS_API_PORT": str(puerto), "DAS_USUARIO": USUARIO,
                          "DAS_CLAVE": CLAVE_DAS, "DAS_CUENTA": CUENTA,
                          "BOT_DAS_FUENTE": f"grabacion={grabacion}"}.items():
        monkeypatch.setenv(nombre, valor)

    def paso(t: datetime, vela: dict) -> list[str]:
        """Guion del replay: halts/reaperturas a su hora y la vela como cotización con el spread declarado.

        G2-06: devuelve las líneas de DAS de la vela; el ejecutor aplica su `$Quote` ANTES de la señal (si no, toda
        entrada del replay salía descartada «sin cotización fresca de DAS»)."""
        programa.aplicar_hasta(simulador, t)
        return simulador.desde_vela(vela["ticker"], vela, programa.spread)

    e = ejecutor_mod.construir_desde_env(cfg, reloj, BACKEND, referencia=_ReferenciaFija(),
                                         calendario=_CalendarioFijo(), hash_motor=lambda base: cfg.motor_hash,
                                         medir_desvio=lambda: 0.0, canales=[], paso_replay=paso)
    resultado: dict[str, Any] = {}
    hilo = threading.Thread(target=lambda: resultado.update(codigo=e.arrancar() or e.correr()),
                            name="replay-dorado", daemon=True)
    try:
        emparejador = getattr(e.cliente, "emparejador", None)
        if emparejador is not None:
            programa.aplicar_inicio(emparejador.libro)                  # rechazos y parciales: cuenta de la sombra
        hilo.start()
        hilo.join(PLAZO_REPLAY_S)
        if hilo.is_alive():
            e.pedir_parada("plazo del test agotado", 1)
            hilo.join(30.0)
            pytest.fail(f"el replay de {dia} no terminó en {PLAZO_REPLAY_S:g} s")
    finally:
        e.parar()
        simulador.parar()
    assert resultado.get("codigo") == 0
    obtenido = resultado_de(LectorDiario(dir_bot / "diario").leer(dia, ("ejecutor",)))
    esperado = leer_esperado(FIXTURES / f"esperado_{dia.isoformat()}.jsonl")
    difs = diferencias(esperado, obtenido)
    assert not difs, "el replay ya no reproduce el dorado:\n" + "\n".join(difs)
