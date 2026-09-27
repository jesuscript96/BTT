"""Tests de app.bot_das.config (documento §3.8, §7 y fila de §10; H-4, H-6, CM1-CM4, R-L-02, R-O-01).

QUÉ PRUEBA. Hash canónico contra el fixture firmado por el lote 0, roundtrip
escribir_atomico/cargar, respaldo con el último bueno, validar (cada
combinación imposible), extraer_estrategia (lectura de la definición como el
motor), comprobar_coherencia, diferencias/aplicar (caliente frente a apagado),
motor_hash sobre COPIAS de los tres ficheros, el puente contra un http.server
local en hilo, VigilanteConfig ante un os.replace y la línea de comandos.

POR QUÉ ESTÁ AQUÍ. Un fichero del cuadro mal leído cambia tamaños y stops sin
dar error (H-4); es el tipo de bug que no avisa.

LAS TRAMPAS. Ningún test toca red real, DAS, Massive ni la base; los ficheros
del motor se COPIAN a un temporal antes de alterarlos; los hilos y el
servidor HTTP se paran en un finally.
"""
from __future__ import annotations

import copy
import dataclasses
import hashlib
import json
import os
import shutil
import subprocess
import sys
import threading
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional

import pytest

from app.bot_das import config as C
from app.bot_das.tipos import Config, EstrategiaConfig, Fase

FIXTURES = Path(__file__).parent / "fixtures"
RUTA_EJEMPLO = FIXTURES / "config_ejemplo.json"
CUENTA = "CUENTA_PRUEBA"
BACKEND = Path(__file__).resolve().parents[2]
SHA_FIXTURE = "46b3934d4ebf644fcf3067158723b34f96e3fcc8934a5f9b3b73ec74b4dc607b"


# ── utilidades ─────────────────────────────────────────────────────────
def _crudo() -> dict:
    return json.loads(RUTA_EJEMPLO.read_text(encoding="utf-8"))


def _firmar(obj: dict, definiciones: bool = True) -> dict:
    """Recalcula definition_hash (opcional), estrategias_hash y sha256 como lo haría la app."""
    if definiciones:
        for e in obj.get("estrategias", []):
            if "definition" in e:
                e["definition_hash"] = "sha256:" + C.hash_canonico(e["definition"])
    obj["estrategias_hash"] = "sha256:" + C.hash_canonico(obj["estrategias"])
    obj["sha256"] = C.hash_canonico({k: v for k, v in obj.items() if k != "sha256"})
    return obj


def _escribir(ruta: Path, obj: dict) -> Path:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    return ruta


def _definicion(**cambios: Any) -> dict:
    d = copy.deepcopy(_crudo()["estrategias"][0]["definition"])
    for clave, valor in cambios.items():
        partes = clave.split("__")
        destino = d
        for p in partes[:-1]:
            destino = destino.setdefault(p, {})
        destino[partes[-1]] = valor
    return d


def _fila(definicion: Optional[dict] = None, **cambios: Any) -> dict:
    e = copy.deepcopy(_crudo()["estrategias"][0])
    if definicion is not None:
        e["definition"] = definicion
        e.pop("definition_hash", None)
    e.update(cambios)
    return e


def _cfg(crudo: Optional[dict] = None) -> Config:
    obj = _firmar(crudo) if crudo is not None else _crudo()
    return C._construir(obj, CUENTA)


# ── hash canónico ──────────────────────────────────────────────────────
def test_hash_canonico_reproduce_el_fixture_del_lote0():
    crudo = _crudo()
    assert crudo["sha256"] == SHA_FIXTURE
    assert C.hash_canonico({k: v for k, v in crudo.items() if k != "sha256"}) == SHA_FIXTURE
    assert crudo["estrategias_hash"] == "sha256:" + C.hash_canonico(crudo["estrategias"])
    e = crudo["estrategias"][0]
    assert e["definition_hash"] == "sha256:" + C.hash_canonico(e["definition"])


def test_hash_canonico_es_la_formula_exacta_y_estable_al_orden():
    obj = {"b": 1, "a": ["ñ", 3.0, None], "c": {"z": True, "y": 0.3}}
    texto = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    assert C.hash_canonico(obj) == hashlib.sha256(texto.encode("utf-8")).hexdigest()
    assert C.hash_canonico({"c": obj["c"], "a": obj["a"], "b": 1}) == C.hash_canonico(obj)
    assert len(C.hash_canonico(obj)) == 64 and not C.hash_canonico(obj).startswith("sha256:")


def test_hash_canonico_rechaza_decimal_y_nan():
    with pytest.raises(TypeError):
        C.hash_canonico({"x": Decimal("1")})
    with pytest.raises(ValueError):
        C.hash_canonico({"x": float("nan")})


# ── cargar ─────────────────────────────────────────────────────────────
def test_cargar_fixture_tal_cual(cfg):
    assert isinstance(cfg, Config)
    assert cfg.fase is Fase.SOMBRA and cfg.config_version == 1 and cfg.sha256 == SHA_FIXTURE
    assert cfg.cuenta_das == CUENTA and cfg.vigilando is True and cfg.pausar_entradas is False
    assert cfg.stops["principal_limite_pct"] == 3.0 and cfg.rutas["stop"] == "STOP"
    e = cfg.estrategias["prueba-1"]
    assert isinstance(e, EstrategiaConfig)
    assert e.riesgo_usd == Decimal("300") and isinstance(e.riesgo_usd, Decimal)
    assert e.ev_pct == Decimal("4.0") and isinstance(e.ev_pct, Decimal)
    assert e.hora_fin_sesion == "11:30" and e.hora_salida is None and e.es_rth is False
    assert e.ventana_entradas == [{"from_time": "04:00", "to_time": "09:29"}]
    assert e.accept_reentries is True and e.max_reentries == -1 and e.niveles_piramide == []
    assert e.definition_hash == _crudo()["estrategias"][0]["definition_hash"]
    assert C.comprobar_coherencia(e) == []


def test_cargar_devuelve_copias_independientes():
    a = C.cargar(RUTA_EJEMPLO, CUENTA)
    a.stops["principal_limite_pct"] = 99
    a.estrategias["prueba-1"].definition["bias"] = "long"
    b = C.cargar(RUTA_EJEMPLO, CUENTA)
    assert b.stops["principal_limite_pct"] == 3.0 and b.estrategias["prueba-1"].definition["bias"] == "short"


@pytest.mark.parametrize("cuenta", ["", "   ", None], ids=["R-Q-01 vacia", "R-Q-01 blancos", "R-Q-01 None"])
def test_cargar_exige_cuenta_das(cuenta):
    with pytest.raises(C.ConfigInvalida, match="DAS_CUENTA"):
        C.cargar(RUTA_EJEMPLO, cuenta)


@pytest.mark.parametrize("contenido, motivo", [
    ('{"schema_version": 1', "JSON"),
    ('[1, 2]', "objeto"),
    ('{"a": NaN}', "finito"),
    ('{"a": 1, "a": 2}', "repetida"),
    (b"\xff\xfe\x00", "UTF-8"),
], ids=["H-4 partido", "H-4 no objeto", "H-4 NaN", "H-4 clave repetida", "H-4 bytes basura"])
def test_cargar_rechaza_ficheros_corruptos(tmp_path, contenido, motivo):
    ruta = tmp_path / "c.json"
    if isinstance(contenido, bytes):
        ruta.write_bytes(contenido)
    else:
        ruta.write_text(contenido, encoding="utf-8")
    with pytest.raises(C.ConfigInvalida, match=motivo):
        C.cargar(ruta, CUENTA)


def test_cargar_fichero_inexistente(tmp_path):
    with pytest.raises(C.ConfigInvalida, match="no se pudo leer") as exc:
        C.cargar(tmp_path / "no.json", CUENTA)
    assert exc.value.errores and isinstance(exc.value, ValueError)


def test_cargar_acepta_bom_utf8(tmp_path):
    ruta = tmp_path / "c.json"
    ruta.write_bytes(b"\xef\xbb\xbf" + RUTA_EJEMPLO.read_bytes())
    assert C.cargar(ruta, CUENTA).sha256 == SHA_FIXTURE


# ── escribir_atomico ───────────────────────────────────────────────────
def test_escribir_atomico_roundtrip_y_no_muta(tmp_path):
    obj = _crudo()
    obj["config_version"] = 7
    obj["sha256"] = "0" * 64                         # obsoleto: se recalcula
    antes = copy.deepcopy(obj)
    ruta = tmp_path / "config" / "bot_das_config.json"
    C.escribir_atomico(ruta, obj)
    assert obj == antes
    cfg = C.cargar(ruta, CUENTA)
    assert cfg.config_version == 7
    escrito = json.loads(ruta.read_text(encoding="utf-8"))
    assert escrito["sha256"] == C.hash_canonico({k: v for k, v in escrito.items() if k != "sha256"})
    assert [p.name for p in ruta.parent.iterdir()] == [ruta.name]      # sin temporales


def test_escribir_atomico_tmp_en_el_mismo_directorio(tmp_path, monkeypatch):
    vistos: list[tuple[str, str]] = []
    real = os.replace

    def espia(src, dst):
        vistos.append((str(src), str(dst)))
        return real(src, dst)

    monkeypatch.setattr(C.os, "replace", espia)
    ruta = tmp_path / "d" / "c.json"
    C.escribir_atomico(ruta, _crudo())
    assert len(vistos) == 1
    assert Path(vistos[0][0]).parent == ruta.parent and Path(vistos[0][1]) == ruta


def test_escribir_atomico_fallo_deja_el_anterior_intacto(tmp_path, monkeypatch):
    ruta = tmp_path / "solo" / "c.json"
    C.escribir_atomico(ruta, _crudo())
    original = ruta.read_bytes()

    def falla(src, dst):
        raise OSError("disco lleno")

    monkeypatch.setattr(C.os, "replace", falla)
    otro = _crudo()
    otro["config_version"] = 99
    with pytest.raises(OSError, match="disco lleno"):
        C.escribir_atomico(ruta, otro)
    assert ruta.read_bytes() == original
    assert [p.name for p in ruta.parent.iterdir()] == ["c.json"]


def test_escribir_atomico_rechaza_no_dict_y_nan(tmp_path):
    with pytest.raises(TypeError):
        C.escribir_atomico(tmp_path / "c.json", [1, 2])        # type: ignore[arg-type]
    with pytest.raises(ValueError):
        C.escribir_atomico(tmp_path / "c.json", {"x": float("inf")})
    assert not (tmp_path / "c.json").exists()
    assert not [p for p in tmp_path.iterdir() if p.suffix == ".tmp"]


# ── respaldo (H-4) ─────────────────────────────────────────────────────
def test_hash_alterado_da_config_invalida_y_respaldo(tmp_path):
    ruta, bueno = tmp_path / "c.json", tmp_path / "ultimo_bueno.json"
    C.escribir_atomico(ruta, _crudo())
    cfg, aviso = C.cargar_con_respaldo(ruta, bueno, CUENTA)
    assert aviso is None and bueno.exists() and C.cargar(bueno, CUENTA).sha256 == cfg.sha256

    alterado = json.loads(ruta.read_text(encoding="utf-8"))
    alterado["estrategias"][0]["riesgo_usd"] = 3000            # sin volver a firmar
    _escribir(ruta, alterado)
    with pytest.raises(C.ConfigInvalida, match="sha256"):
        C.cargar(ruta, CUENTA)
    cfg2, aviso2 = C.cargar_con_respaldo(ruta, bueno, CUENTA)
    assert cfg2.estrategias["prueba-1"].riesgo_usd == Decimal("300")
    assert aviso2 is not None and "último bueno" in aviso2 and "H-4" in aviso2
    assert C.cargar(bueno, CUENTA).estrategias["prueba-1"].riesgo_usd == Decimal("300")   # no se pisó


def test_respaldo_sin_ultimo_bueno_lanza_con_los_dos_errores(tmp_path):
    ruta = _escribir(tmp_path / "c.json", {"roto": True})
    with pytest.raises(C.ConfigInvalida) as exc:
        C.cargar_con_respaldo(ruta, tmp_path / "no_existe.json", CUENTA)
    textos = " | ".join(exc.value.errores)
    assert "c.json" in textos and "último bueno" in textos


def test_respaldo_avisa_si_no_puede_guardar_el_ultimo_bueno(tmp_path, monkeypatch):
    def falla(*a, **k):
        raise OSError("sin permiso")

    monkeypatch.setattr(C, "escribir_atomico", falla)
    cfg, aviso = C.cargar_con_respaldo(RUTA_EJEMPLO, tmp_path / "ub.json", CUENTA)
    assert cfg.sha256 == SHA_FIXTURE and aviso is not None and "sin permiso" in aviso


@pytest.mark.parametrize("fase_respaldo", ["canario", "real"], ids=["SEG-02-canario", "SEG-02-real"])
def test_SEG_02_el_respaldo_nunca_sube_la_fase(tmp_path, fase_respaldo):
    """SEG-02 / R-O-03: fichero del cuadro roto + último bueno en CANARIO/REAL → se arranca en SOMBRA con aviso."""
    ruta, bueno = tmp_path / "c.json", tmp_path / "ultimo_bueno.json"
    crudo = _crudo()
    crudo["fase"] = fase_respaldo
    C.escribir_atomico(bueno, _firmar(crudo))
    assert C.cargar(bueno, CUENTA).fase is Fase(fase_respaldo)
    _escribir(ruta, {"roto": True})                          # Jaume bajaba a sombra y el fichero nuevo no valida
    cfg, aviso = C.cargar_con_respaldo(ruta, bueno, CUENTA)
    assert cfg.fase is Fase.SOMBRA
    assert aviso is not None and C.AVISO_FASE_FORZADA in aviso and fase_respaldo.upper() in aviso
    assert C.cargar(bueno, CUENTA).fase is Fase(fase_respaldo)           # el último bueno no se toca
    # el resto de la config del respaldo se conserva
    assert cfg.config_version == C.cargar(bueno, CUENTA).config_version and cfg.estrategias.keys() == {"prueba-1"}


def test_SEG_02_respaldo_en_sombra_no_marca_fase_forzada(tmp_path):
    ruta, bueno = tmp_path / "c.json", tmp_path / "ultimo_bueno.json"
    crudo = _crudo()
    crudo["fase"] = "sombra"
    C.escribir_atomico(bueno, _firmar(crudo))
    _escribir(ruta, {"roto": True})
    cfg, aviso = C.cargar_con_respaldo(ruta, bueno, CUENTA)
    assert cfg.fase is Fase.SOMBRA and aviso is not None and C.AVISO_FASE_FORZADA not in aviso


def test_SEG_02_un_fichero_valido_en_real_no_se_toca(tmp_path):
    """El candado solo actúa sobre el RESPALDO: una config buena en REAL arranca en REAL (el .env pone el otro candado)."""
    crudo = _crudo()
    crudo["fase"] = "real"
    C.escribir_atomico(tmp_path / "c.json", _firmar(crudo))
    cfg, aviso = C.cargar_con_respaldo(tmp_path / "c.json", tmp_path / "ub.json", CUENTA)
    assert cfg.fase is Fase.REAL and aviso is None


def test_A_02_replace_share_es_abierta_es_opcional_con_defecto_de_tipos():
    """A-02: `stops.replace_share_es_abierta` (defecto tipos.REPLACE_SHARE_ES_ABIERTA = True). Un fichero sin la clave
    (config_ejemplo.json, con su sha256 de siempre) valida y la Config la lleva con el defecto; con la clave, manda."""
    from app.bot_das.tipos import REPLACE_SHARE_ES_ABIERTA

    assert "replace_share_es_abierta" not in _crudo()["stops"]
    cfg = C.cargar(RUTA_EJEMPLO, CUENTA)
    assert cfg.sha256 == SHA_FIXTURE and cfg.stops["replace_share_es_abierta"] is REPLACE_SHARE_ES_ABIERTA is True
    crudo = _crudo()
    crudo["stops"]["replace_share_es_abierta"] = False
    assert C.validar(_firmar(crudo)) == []
    assert _cfg(crudo).stops["replace_share_es_abierta"] is False
    malo = _crudo()
    malo["stops"]["replace_share_es_abierta"] = "si"
    assert any("replace_share_es_abierta" in e for e in C.validar(_firmar(malo)))
    # cambiarla es una diferencia EN FRÍO ([A]): no entra en CALIENTE
    assert "stops.replace_share_es_abierta" not in C.CALIENTE
    difs = {r: cal for r, _a, _d, cal in C.diferencias(cfg, _cfg(crudo))}
    assert difs.get("stops.replace_share_es_abierta") is False


def test_guardar_ultimo_bueno_no_guarda_lo_invalido(tmp_path):
    malo = _crudo()
    malo["fase"] = "demo"
    with pytest.raises(C.ConfigInvalida):
        C.guardar_ultimo_bueno(malo, tmp_path / "ub.json")
    assert not (tmp_path / "ub.json").exists()
    C.guardar_ultimo_bueno(_crudo(), tmp_path / "ub.json")
    assert C.cargar(tmp_path / "ub.json", CUENTA).sha256 == SHA_FIXTURE


# ── validar ────────────────────────────────────────────────────────────
def _mutar(ruta: str, valor: Any):
    def f(obj: dict) -> None:
        partes = ruta.split(".")
        destino = obj
        for p in partes[:-1]:
            destino = destino[int(p)] if isinstance(destino, list) else destino[p]
        if valor is _BORRAR:
            del destino[partes[-1]]
        else:
            destino[partes[-1]] = valor
    return f


_BORRAR = object()

CASOS_INVALIDOS = [
    ("R-C-01 principal = disparo", [_mutar("stops.principal_limite_pct", 13.0)], "principal_limite_pct"),
    ("R-C-01 principal > disparo", [_mutar("stops.principal_limite_pct", 20.0)], "principal_limite_pct"),
    ("R-C-01 disparo = limite", [_mutar("stops.emergencia_disparo_pct", 63.0)], "emergencia_limite_pct"),
    ("R-C-01 disparo > limite", [_mutar("stops.emergencia_limite_pct", 10.0)], "emergencia_limite_pct"),
    ("R-C-01 principal 0", [_mutar("stops.principal_limite_pct", 0)], "principal_limite_pct"),
    ("R-C-01 principal negativo", [_mutar("stops.principal_limite_pct", -3.0)], "principal_limite_pct"),
    ("R-C-01 principal texto", [_mutar("stops.principal_limite_pct", "3")], "principal_limite_pct"),
    ("R-F-01 k_max 0", [_mutar("halts.k_max", 0)], "k_max"),
    ("R-F-01 k_max negativo", [_mutar("halts.k_max", -1)], "k_max"),
    ("R-F-01 k_max bool", [_mutar("halts.k_max", True)], "k_max"),
    ("R-F-01 k_max float", [_mutar("halts.k_max", 2.5)], "k_max"),
    ("R-H-03 tope 0", [_mutar("locates.tope_gasto_pct_cuenta", 0)], "tope_gasto_pct_cuenta"),
    ("R-H-03 tope negativo", [_mutar("locates.tope_gasto_pct_cuenta", -1)], "tope_gasto_pct_cuenta"),
    ("R-H-03 tope > 10", [_mutar("locates.tope_gasto_pct_cuenta", 10.5)], "tope_gasto_pct_cuenta"),
    ("R-H-03 tope null", [_mutar("locates.tope_gasto_pct_cuenta", None)], "tope_gasto_pct_cuenta"),
    ("R-L-01 encender H:MM", [_mutar("horario.encender", "3:55")], "horario.encender"),
    ("R-L-01 encender 24:00", [_mutar("horario.encender", "24:00")], "horario.encender"),
    ("R-L-01 apagar 25:00", [_mutar("horario.apagar", "25:00")], "horario.apagar"),
    ("R-L-01 apagar con segundos", [_mutar("horario.apagar", "16:00:00")], "horario.apagar"),
    ("R-H-01.5 hora_limite texto", [_mutar("locates.hora_limite_intentos", "pronto")], "hora_limite_intentos"),
    ("R-L-01 tz distinta", [_mutar("horario.tz", "Europe/Madrid")], "horario.tz"),
    ("R-O-03 fase demo", [_mutar("fase", "demo")], "fase"),
    ("R-O-03 fase mayusculas", [_mutar("fase", "SOMBRA")], "fase"),
    ("CM2 riesgo 0 con ejecutar", [_mutar("estrategias.0.riesgo_usd", 0)], "riesgo_usd"),
    ("CM2 riesgo negativo", [_mutar("estrategias.0.riesgo_usd", -300)], "riesgo_usd"),
    ("CM2 riesgo null con ejecutar", [_mutar("estrategias.0.riesgo_usd", None)], "riesgo_usd"),
    ("CM2 riesgo piramide 0", [_mutar("estrategias.0.riesgo_piramide_usd", 0)], "riesgo_piramide_usd"),
    ("CM2 riesgos piramide negativo", [_mutar("estrategias.0.riesgos_piramide", [100, -5])], "riesgos_piramide"),
    ("CM2 ev_pct null", [_mutar("estrategias.0.ev_pct", None)], "ev_pct"),
    ("R-E-03 al_desactivar raro", [_mutar("estrategias.0.al_desactivar", "cerrar")], "al_desactivar"),
    ("2h ruta agregar vacia", [_mutar("rutas.agregar.ge_1", "")], "rutas.agregar.ge_1"),
    ("2h ruta cruzar blancos", [_mutar("rutas.cruzar.lt_1_antes_0700", "  ")], "lt_1_antes_0700"),
    ("2h ruta stop vacia", [_mutar("rutas.stop", "")], "rutas.stop"),
    ("2h ruta halt null", [_mutar("rutas.halt", None)], "rutas.halt"),
    ("2h stops.ruta vacia", [_mutar("stops.ruta", "")], "stops.ruta"),
    ("§5.22 ruta_inquire vacia", [_mutar("locates.ruta_inquire", "")], "ruta_inquire"),
    ("EP-2 ruta_reapertura vacia", [_mutar("halts.ruta_reapertura", "")], "ruta_reapertura"),
    ("§7 schema_version 2", [_mutar("schema_version", 2)], "schema_version"),
    ("§7 falta bloque stops", [_mutar("stops", _BORRAR)], "stops"),
    ("§7 falta clave de bloque", [_mutar("entrada.caducidad_senal_s", _BORRAR)], "caducidad_senal_s"),
    ("§7 bloque no objeto", [_mutar("halts", [])], "halts"),
    ("§7 vigilando no bool", [_mutar("vigilando", 1)], "vigilando"),
    ("§7 salida_motor desconocida", [_mutar("salidas.salida_motor", "perseguir")], "salida_motor"),
    ("§7 fuente_splits desconocida", [_mutar("exclusiones.fuente_splits", "yahoo")], "fuente_splits"),
    ("§7 stops.tipo no STOPLMTP", [_mutar("stops.tipo", "STOP")], "stops.tipo"),
    ("§7 lista_negra con vacio", [_mutar("lista_negra", ["ABC", ""])], "lista_negra"),
    ("§7 reconexion vacia", [_mutar("tecnicos.das_reconexion_s", [])], "das_reconexion_s"),
    ("§7 config_version negativa", [_mutar("config_version", -1)], "config_version"),
    ("R-O-01 motor_hash sin prefijo", [_mutar("motor_hash", "0" * 64)], "motor_hash"),
    ("CM2 strategy_id repetido", [lambda o: o["estrategias"].append(copy.deepcopy(o["estrategias"][0]))], "repetido"),
    ("CM2 strategy_id vacio", [_mutar("estrategias.0.strategy_id", "")], "strategy_id"),
    ("CM4 definition ausente", [_mutar("estrategias.0.definition", _BORRAR)], "definition"),
    ("R-L-02 ventana mal formada", [_mutar("estrategias.0.definition.entry_logic.entry_time_windows",
                                           [{"from_time": "4h", "to_time": "09:29"}])], "from_time"),
    ("R-L-02 custom_end mal formada", [_mutar("estrategias.0.definition.custom_end_time", "11:75")], "custom_end_time"),
    ("R-L-02 TP Hour mal formado", [_mutar("estrategias.0.definition.risk_management.take_profit",
                                           {"type": "Hour", "value": "nueve"})], "take_profit"),
]


@pytest.mark.parametrize("mutaciones, esperado", [(m, e) for _, m, e in CASOS_INVALIDOS],
                         ids=[i for i, _, _ in CASOS_INVALIDOS])
def test_validar_rechaza_cada_combinacion_imposible(mutaciones, esperado):
    obj = _crudo()
    for m in mutaciones:
        m(obj)
    _firmar(obj)                                     # firmado: el ÚNICO error es el que se busca
    errores = C.validar(obj)
    assert errores, "debería rechazarse"
    assert any(esperado in e for e in errores), errores
    assert not any(e.startswith("sha256") for e in errores)


@pytest.mark.parametrize("mutaciones", [
    [_mutar("locates.tope_gasto_pct_cuenta", 10)],
    [_mutar("locates.tope_gasto_pct_cuenta", 0.01)],
    [_mutar("estrategias.0.ejecutar", False), _mutar("estrategias.0.riesgo_usd", 0)],
    [_mutar("estrategias.0.ejecutar", False), _mutar("estrategias.0.riesgo_usd", None)],
    [_mutar("horario.apagar", "20:00"), _mutar("locates.hora_limite_intentos", "10:30")],
    [_mutar("fase", "real")],
    [_mutar("halts.k_max", 1)],
    [_mutar("estrategias", [])],
    [_mutar("estrategias.0.definition.custom_end_time", "9:45")],
    [_mutar("entrada.distancia_max_ultimo_bid_pct", None)],
    [_mutar("extra_desconocida", {"a": 1})],
], ids=["R-H-03 tope 10 justo", "R-H-03 tope minimo", "CM2 riesgo 0 sin ejecutar", "CM2 riesgo null sin ejecutar",
        "R-L-01 horas validas", "R-O-03 fase real", "R-F-01 k_max 1", "§7 sin estrategias",
        "R-L-02 hora H:MM en definicion", "B20 bis apagada", "§7 clave extra tolerada"])
def test_validar_acepta_limites_validos(mutaciones):
    obj = _crudo()
    for m in mutaciones:
        m(obj)
    assert C.validar(_firmar(obj)) == []


def test_validar_fixture_sin_errores():
    assert C.validar(_crudo()) == []


@pytest.mark.parametrize("campo, valor", [
    ("sha256", "0" * 64), ("sha256", "sin-hex"), ("estrategias_hash", "sha256:" + "0" * 64),
    ("estrategias.0.definition_hash", "sha256:" + "1" * 64),
], ids=["H-4 sha alterado", "H-4 sha no hex", "R-O-01 estrategias_hash", "R-E-03 definition_hash"])
def test_validar_rechaza_hashes_que_no_casan(campo, valor):
    obj = _crudo()
    _mutar(campo, valor)(obj)
    if campo != "sha256":
        obj["sha256"] = C.hash_canonico({k: v for k, v in obj.items() if k != "sha256"})
    assert any(campo.split(".")[-1] in e for e in C.validar(obj))


def test_validar_no_lanza_con_basura():
    assert C.validar([]) == ["la configuración no es un objeto JSON"]           # type: ignore[arg-type]
    assert C.validar({})                                                     # muchos «falta»


# ── extraer_estrategia (CM4, R-L-02, paridad con el motor) ─────────────
@pytest.mark.parametrize("definicion, fin, es_rth, salida", [
    (_definicion(), "11:30", False, None),
    (_definicion(entry_logic__entry_time_windows=[{"from_time": "09:30", "to_time": "10:55"}],
                 custom_start_time="09:30"), "11:30", True, None),
    (_definicion(entry_logic__entry_time_windows=[{"from_time": "09:30", "to_time": "10:00"},
                                                  {"from_time": "08:00", "to_time": "09:00"}]), "11:30", False, None),
    (_definicion(entry_logic__entry_time_windows=[], market_sessions=["rth"]), "16:00", True, None),
    (_definicion(entry_logic__entry_time_windows=[]), "11:30", False, None),
    (_definicion(entry_logic__entry_time_windows=[{"from_time": "04:00", "to_time": "11:00"}],
                 market_sessions=["rth"]), "16:00", True, None),
    (_definicion(market_sessions=["pre", "rth"]), "16:00", False, None),
    (_definicion(market_sessions=["rth", "custom"], custom_start_time="04:00", custom_end_time="12:00"),
     "16:00", False, None),
    (_definicion(market_sessions=["all"]), None, False, None),
    (_definicion(market_sessions=[]), None, False, None),
    (_definicion(market_sessions=["custom"], custom_start_time=None, custom_end_time=None,
                 entry_logic__entry_time_windows=[]), "16:00", True, None),
    (_definicion(risk_management__use_take_profit=True, risk_management__take_profit={"type": "Hour", "value": "9:00"}),
     "11:30", False, "09:00"),
    (_definicion(risk_management__use_take_profit=True, risk_management__take_profit={"type": "Hour", "value": None}),
     "11:30", False, "15:30"),
    (_definicion(risk_management__use_take_profit=False, risk_management__take_profit={"type": "Hour", "value": "10:00"}),
     "11:30", False, None),
    (_definicion(risk_management__use_take_profit=True, risk_management__take_profit_mode="Partial",
                 risk_management__partial_take_profits=[{"distance_pct": "HOUR:08:15", "capital_pct": 100.0}],
                 risk_management__take_profit={"type": "Hour", "value": "09:00"}), "11:30", False, None),
], ids=["fixture PM", "RTH 09:30", "ventanas mixtas", "sin ventanas sesion rth", "sin ventanas custom 04:00",
        "ventana recortada por sesion rth", "pre+rth", "sesion sumada", "sesion all", "sin sesiones",
        "custom sin horas (defaults motor)", "TP Hour H:MM", "TP Hour sin valor 15:30", "use_take_profit false",
        "Partial ignora Hour"])
def test_extraer_estrategia_lee_la_definicion_como_el_motor(definicion, fin, es_rth, salida):
    e = C.extraer_estrategia(_fila(definicion))
    assert (e.hora_fin_sesion, e.es_rth, e.hora_salida) == (fin, es_rth, salida)
    assert e.definition_hash == "sha256:" + C.hash_canonico(definicion)
    assert e.definition == definicion and e.definition is not definicion


@pytest.mark.parametrize("rm, accept, maxr", [
    ({}, False, 0), ({"accept_reentries": True}, True, -1), ({"accept_reentries": True, "max_reentries": 2}, True, 2),
    ({"accept_reentries": False, "max_reentries": -1}, False, -1),
], ids=["defaults motor sin reentradas", "acepta sin tope -1", "tope 2", "max -1 tal cual (memoria reentradas -1)"])
def test_extraer_reentradas_con_defaults_del_motor(rm, accept, maxr):
    d = _definicion()
    d["risk_management"] = rm
    e = C.extraer_estrategia(_fila(d))
    assert (e.accept_reentries, e.max_reentries) == (accept, maxr)


def test_extraer_claves_ausentes_con_defaults():
    d = {"entry_logic": {}, "market_sessions": ["custom"], "custom_start_time": "04:00", "custom_end_time": "08:45"}
    e = C.extraer_estrategia({"strategy_id": "s", "ev_pct": 2, "riesgo_usd": 50.5, "definition": d})
    assert e.name == "s" and e.origen == "portfolio" and e.ejecutar is False and e.avisar_grupo_a is False
    assert e.excluir_ipo is True and e.al_desactivar == "esperar_fin_dia"
    assert e.riesgo_usd == Decimal("50.5") and e.riesgos_piramide == [] and e.riesgo_piramide_usd is None
    assert e.ev_rangos == [] and e.niveles_piramide == [] and e.ventana_entradas == []
    assert e.hora_fin_sesion == "08:45" and e.accept_reentries is False and e.max_reentries == 0


def test_extraer_convierte_riesgos_a_decimal_sin_float():
    e = C.extraer_estrategia(_fila(riesgo_usd=0.1, riesgos_piramide=[200, None, 0.3], riesgo_piramide_usd=150.25))
    assert e.riesgo_usd == Decimal("0.1") and e.riesgos_piramide == [Decimal("200"), None, Decimal("0.3")]
    assert e.riesgo_piramide_usd == Decimal("150.25")
    assert all(isinstance(x, Decimal) for x in (e.riesgo_usd, e.riesgo_piramide_usd, e.ev_pct))


def test_extraer_niveles_de_piramide_de_la_definicion():
    niveles = [{"times": 1, "root_condition": {"type": "group", "operator": "AND", "conditions": []}}]
    e = C.extraer_estrategia(_fila(_definicion(pyramiding={"timeframe": "1m", "mode": "sequential", "levels": niveles})))
    assert e.niveles_piramide == niveles


@pytest.mark.parametrize("fila", [
    {"definition": {}}, {"strategy_id": "", "definition": {}}, {"strategy_id": "s"},
    {"strategy_id": "s", "definition": {}, "ev_pct": None},
    {"strategy_id": "s", "definition": {}, "ev_pct": True},
    {"strategy_id": "s", "definition": {"custom_start_time": "4h", "market_sessions": ["custom"]}, "ev_pct": 1},
    {"strategy_id": "s", "definition": {"risk_management": {"max_reentries": "2"}}, "ev_pct": 1},
], ids=["CM4 sin id", "CM4 id vacio", "CM4 sin definition", "CM2 ev null", "CM2 ev bool", "R-L-02 hora mala",
        "R-E-03 max_reentries texto"])
def test_extraer_rechaza_lo_que_no_se_puede_inventar(fila):
    with pytest.raises(ValueError):
        C.extraer_estrategia(fila)


def test_extraer_conserva_definition_hash_de_la_fila():
    e = C.extraer_estrategia(_fila(definition_hash="sha256:" + "a" * 64))
    assert e.definition_hash == "sha256:" + "a" * 64


# ── comprobar_coherencia (R-L-02) ──────────────────────────────────────
def _est(definicion: dict) -> EstrategiaConfig:
    return C.extraer_estrategia(_fila(definicion))


@pytest.mark.parametrize("definicion, trozo", [
    (_definicion(market_sessions=["rth", "custom"], custom_start_time="04:00", custom_end_time="12:00"), "sumada"),
    (_definicion(market_sessions=["custom", "pre"]), "sumada"),
    (_definicion(custom_start_time="09:30"), "fuera de la sesión"),
    (_definicion(entry_logic__entry_time_windows=[{"from_time": "09:30", "to_time": "11:30"}]), "fuera de la sesión"),
    (_definicion(entry_logic__entry_time_windows=[{"from_time": "10:00", "to_time": "09:00"}]), "al revés"),
    (_definicion(risk_management__use_take_profit=True,
                 risk_management__take_profit={"type": "Hour", "value": "12:00"}), "hora_salida"),
    (_definicion(market_sessions=["all"]), "sin acotar"),
    (_definicion(market_sessions=["overnight"]), "desconocidas"),
    (_definicion(custom_start_time="12:00", custom_end_time="11:00"), "vacía"),
], ids=["R-L-02 sesion sumada rth+custom", "R-L-02 sesion sumada pre+custom", "R-L-02 ventana antes de la sesion",
        "R-L-02 ventana acaba en el fin exclusivo", "R-L-02 ventana al reves", "R-L-02 hora_salida tras EOD",
        "R-L-02 sin acotar", "R-L-02 sesion desconocida", "R-L-02 sesion vacia"])
def test_comprobar_coherencia_avisa(definicion, trozo):
    avisos = C.comprobar_coherencia(_est(definicion))
    assert any(trozo in a for a in avisos), avisos
    assert all("R-L-02" in a for a in avisos)


@pytest.mark.parametrize("definicion", [
    _definicion(),
    _definicion(entry_logic__entry_time_windows=[{"from_time": "04:00", "to_time": "11:29"}]),
    _definicion(risk_management__use_take_profit=True, risk_management__take_profit={"type": "Hour", "value": "11:30"}),
    _definicion(market_sessions=["pre", "rth"], entry_logic__entry_time_windows=[{"from_time": "04:00", "to_time": "15:59"}]),
], ids=["R-L-02 fixture", "R-L-02 ventana hasta el ultimo minuto", "R-L-02 hora_salida igual al fin",
        "R-L-02 pre+rth sin custom no es sumada"])
def test_comprobar_coherencia_sin_avisos(definicion):
    assert C.comprobar_coherencia(_est(definicion)) == []


def test_comprobar_coherencia_no_lanza_con_definicion_rota():
    e = dataclasses.replace(_est(_definicion()), definition={"market_sessions": ["custom"], "custom_start_time": "x"})
    avisos = C.comprobar_coherencia(e)
    assert len(avisos) == 1 and "mal formadas" in avisos[0]


@pytest.mark.parametrize("alias", ["premarket", "afterhours", "PreMarket"], ids=lambda a: f"DC-08-{a}")
def test_DC_08_alias_que_el_motor_no_reconoce_salen_como_sesion_desconocida(alias):
    """DC-08: `_get_market_sessions_mask` solo entiende pre/rth/regular/market/post/custom: «premarket» o «afterhours»
    no dan ninguna vela en el motor, así que el bot NO puede inventarse una sesión: aviso R-L-02 y sin sesión."""
    d = _definicion(market_sessions=[alias], entry_logic__entry_time_windows=[])
    e = _est(d)
    avisos = C.comprobar_coherencia(e)
    assert any("desconocidas" in a and alias.lower() in a for a in avisos), avisos
    assert e.hora_fin_sesion is None


# ── DC-09: las marcas [C] del documento y las estrategias reales de sailor ─────
RUTA_DOC = BACKEND.parent / "docs" / "BOT_DAS_ARQUITECTURA.md"
DIR_SAILOR = BACKEND.parent / "estrategias_compartidas" / "sailor"


def _bloque_json_de_la_seccion_7(texto: str) -> str:
    inicio = texto.index("## 7. Configuración")
    abre = texto.index("```json", inicio) + len("```json")
    return texto[abre:texto.index("```", abre)]


def _fichas_json(codigo: str) -> list[tuple[str, str]]:
    """Trocea el código JSON de una línea en fichas: ("cad", texto), ("sig", un signo de {}[]:,) y ("val", escalar)."""
    fichas: list[tuple[str, str]] = []
    i = 0
    while i < len(codigo):
        c = codigo[i]
        if c.isspace():
            i += 1
        elif c == '"':
            fin = codigo.index('"', i + 1)
            fichas.append(("cad", codigo[i + 1:fin]))
            i = fin + 1
        elif c in "{}[]:,":
            fichas.append(("sig", c))
            i += 1
        else:
            j = i
            while j < len(codigo) and not codigo[j].isspace() and codigo[j] not in "{}[]:,":
                j += 1
            fichas.append(("val", codigo[i:j]))
            i = j
    return fichas


def _rutas_marcadas(bloque: str, marca: str = "[C]") -> set[str]:
    """Rutas con punto de las HOJAS del JSON comentado de §7 cuya marca (la de su línea o, si no tiene, la heredada
    de su contenedor) es `marca`.

    Hoja = clave con valor escalar o cadena, o con un array de UNA línea (lista_negra, riesgos_piramide,
    ev_rangos). Un objeto (de una línea o no) es contenedor: sus claves son las hojas. Un objeto dentro de un array
    multilínea (estrategias) es el comodín «*». Lo que va dentro de un array de una línea no genera rutas.
    """
    rutas: set[str] = set()
    pila: list[dict] = []           # contenedores abiertos: {"nombre", "tipo" ({ o [), "marca", "linea"}
    for n_linea, linea in enumerate(bloque.splitlines()):
        codigo, _, comentario = linea.partition("//")
        marca_linea = next((m for m in ("[C]", "[A]", "[T]") if m in comentario), None)
        fichas = _fichas_json(codigo)
        clave: Optional[str] = None
        k = 0
        while k < len(fichas):
            tipo, texto = fichas[k]
            heredada = marca_linea or (pila[-1]["marca"] if pila else None)
            dentro_de_array_en_linea = any(c["tipo"] == "[" and c["linea"] == n_linea for c in pila)
            if tipo == "cad" and k + 1 < len(fichas) and fichas[k + 1] == ("sig", ":"):
                clave = texto
                k += 2
                continue
            if tipo in ("cad", "val"):
                if clave is not None and not dentro_de_array_en_linea and heredada == marca:
                    rutas.add(".".join([c["nombre"] for c in pila if c["nombre"]] + [clave]))
                clave = None
            elif texto in "{[":
                if clave is not None:
                    nombre = clave
                elif pila and pila[-1]["tipo"] == "[":
                    nombre = "*"
                else:
                    nombre = ""
                pila.append({"nombre": nombre, "tipo": texto, "marca": heredada, "linea": n_linea})
                clave = None
            elif texto in "}]":
                cerrado = pila.pop()
                if (cerrado["tipo"] == "[" and cerrado["linea"] == n_linea and cerrado["nombre"] not in ("", "*")
                        and not any(c["tipo"] == "[" and c["linea"] == n_linea for c in pila)
                        and cerrado["marca"] == marca):
                    rutas.add(".".join([c["nombre"] for c in pila if c["nombre"]] + [cerrado["nombre"]]))
            k += 1
    return rutas


def test_DC_09_caliente_es_exactamente_lo_marcado_C_en_el_bloque_de_s7():
    """DC-09: CALIENTE se compara con las marcas [C] LEÍDAS del documento (no con una copia a mano de la lista)."""
    bloque = _bloque_json_de_la_seccion_7(RUTA_DOC.read_text(encoding="utf-8"))
    marcadas = _rutas_marcadas(bloque, "[C]")
    assert len(marcadas) == 26
    assert C.CALIENTE == frozenset(marcadas)
    # y ninguna [A]/[T] se cuela en CALIENTE (los vecinos de las [C] siguen siendo en frío)
    frias = _rutas_marcadas(bloque, "[A]") | _rutas_marcadas(bloque, "[T]")
    assert {"fase", "locates.umbral_ultimo_paquete_pct", "estrategias.*.definition_hash",
            "stops.principal_limite_pct"} <= frias
    assert not (frias & C.CALIENTE)


def test_G2_09_la_marca_slow_esta_registrada_en_el_conftest(pytestconfig):
    """G2-09: `@pytest.mark.slow` (replay de días grabados) está registrada: con -W error la colección no falla."""
    assert any(m.split(":", 1)[0].strip() == "slow" for m in pytestconfig.getini("markers"))


def _sailor() -> list[Path]:
    return sorted(DIR_SAILOR.glob("*.json")) if DIR_SAILOR.is_dir() else []


def _fin_de_sesion_del_motor(definicion: dict) -> Optional[str]:
    """Fin de sesión («HH:MM», exclusivo) según `_get_market_sessions_mask` del MOTOR sobre los 1 440 minutos del día."""
    pd = pytest.importorskip("pandas")
    from app.services.backtest_service import _get_market_sessions_mask

    minutos = pd.Series(pd.date_range("2026-09-25 00:00", periods=24 * 60, freq="min"))
    mascara = _get_market_sessions_mask(minutos, list(definicion.get("market_sessions") or []),
                                        definicion.get("custom_start_time"), definicion.get("custom_end_time"))
    if mascara.all():
        return None
    activos = [i for i, v in enumerate(mascara) if v]
    if not activos:
        return "vacía"
    fin = activos[-1] + 1
    return f"{fin // 60:02d}:{fin % 60:02d}"


@pytest.mark.parametrize("ruta", _sailor(), ids=lambda p: f"DC-09-{p.stem}")
def test_DC_09_extraer_estrategia_con_las_definiciones_reales_de_sailor(ruta: Path):
    """DC-09 / CM4: cada estrategia compartida de sailor se extrae con el fin de sesión y las reentradas que usa el
    MOTOR (paridad calculada con el propio motor, sin copiar valores a mano) y `comprobar_coherencia` no lanza."""
    compartida = json.loads(ruta.read_text(encoding="utf-8"))
    definicion = compartida["definition"]
    e = C.extraer_estrategia({"strategy_id": compartida.get("source_strategy_id") or ruta.stem,
                              "name": compartida.get("name"), "ev_pct": 4, "riesgo_usd": 300,
                              "definition": definicion})
    fin_motor = _fin_de_sesion_del_motor(definicion)
    if fin_motor == "vacía":
        assert e.hora_fin_sesion is None or e.hora_fin_sesion == "00:00"
    else:
        assert e.hora_fin_sesion == fin_motor
    rm = definicion.get("risk_management") or {}
    accept = rm.get("accept_reentries", False)
    assert (e.accept_reentries, e.max_reentries) == (bool(accept), rm.get("max_reentries", -1 if accept else 0))
    niveles = (definicion.get("pyramiding") or {}).get("levels")
    assert e.niveles_piramide == (niveles or [])
    assert isinstance(C.comprobar_coherencia(e), list)
    assert e.definition_hash == "sha256:" + C.hash_canonico(definicion)


# ── diferencias y aplicar (CM2, CM3, R-O-01) ───────────────────────────
def test_caliente_es_exactamente_lo_marcado_C_en_el_documento():
    assert C.CALIENTE == frozenset({
        "vigilando", "pausar_entradas", "horario.tz", "horario.encender", "horario.apagar",
        "modo_seguridad.activo", "modo_seguridad.precio_min", "modo_seguridad.acum_dollar_volume_min",
        "lista_negra", "locates.tope_gasto_pct_cuenta", "locates.hora_limite_intentos",
        "alertas_grupo_a.activo", "alertas_grupo_a.prealerta_simple", "alertas_grupo_a.prealerta_freno_min",
        "alertas_grupo_a.prealerta_ticks",
        "estrategias.*.ejecutar", "estrategias.*.avisar_grupo_a", "estrategias.*.riesgo_usd",
        "estrategias.*.riesgo_piramide_usd", "estrategias.*.riesgos_piramide", "estrategias.*.capital_usd",
        "estrategias.*.ev_pct", "estrategias.*.ev_rangos", "estrategias.*.cuentas", "estrategias.*.excluir_ipo",
        "estrategias.*.al_desactivar",
    })


def _nueva(*mutaciones) -> Config:
    obj = _crudo()
    obj["config_version"] = 2
    for m in mutaciones:
        m(obj)
    return _cfg(obj)


@pytest.mark.parametrize("mutacion, ruta, antes, despues, caliente", [
    (_mutar("vigilando", False), "vigilando", True, False, True),
    (_mutar("pausar_entradas", True), "pausar_entradas", False, True, True),
    (_mutar("horario.encender", "04:00"), "horario.encender", "03:55", "04:00", True),
    (_mutar("lista_negra", ["ABC"]), "lista_negra", [], ["ABC"], True),
    (_mutar("locates.tope_gasto_pct_cuenta", 2.0), "locates.tope_gasto_pct_cuenta", 3.0, 2.0, True),
    (_mutar("alertas_grupo_a.prealerta_simple", True), "alertas_grupo_a.prealerta_simple", False, True, True),
    (_mutar("modo_seguridad.precio_min", 3.0), "modo_seguridad.precio_min", 5.0, 3.0, True),
    (_mutar("estrategias.0.riesgo_usd", 500), "estrategias.prueba-1.riesgo_usd", Decimal("300"), Decimal("500"), True),
    (_mutar("estrategias.0.ejecutar", False), "estrategias.prueba-1.ejecutar", True, False, True),
    (_mutar("estrategias.0.ev_pct", 6.5), "estrategias.prueba-1.ev_pct", Decimal("4.0"), Decimal("6.5"), True),
    (_mutar("stops.principal_limite_pct", 4.0), "stops.principal_limite_pct", 3.0, 4.0, False),
    (_mutar("salidas.por_hora.perseguir_ask_max", 2), "salidas.por_hora.perseguir_ask_max", 3, 2, False),
    (_mutar("locates.umbral_ultimo_paquete_pct", 40), "locates.umbral_ultimo_paquete_pct", 30, 40, False),
    (_mutar("tecnicos.foto_cada_s", 5), "tecnicos.foto_cada_s", 2, 5, False),
    (_mutar("fase", "canario"), "fase", Fase.SOMBRA, Fase.CANARIO, False),
    (_mutar("motor_hash", "sha256:" + "1" * 64), "motor_hash", "sha256:" + "0" * 64, "sha256:" + "1" * 64, False),
    (_mutar("estrategias.0.name", "otro"), "estrategias.prueba-1.name", "PM (A) prueba", "otro", False),
], ids=["CM2 vigilando", "CM2 pausar", "CM2 horario", "R-A-03 lista negra", "R-H-03 tope", "R-M-05 prealerta",
        "R-I-04 seguridad", "CM2 riesgo", "CM2 ejecutar", "CM2 ev", "R-C-01 stops [A]", "R-D-08 anidado [A]",
        "H6 [A]", "tecnico [T]", "R-O-03 fase [A]", "H-6 motor [A]", "nombre no [C]"])
def test_diferencias_marca_caliente_segun_CALIENTE(mutacion, ruta, antes, despues, caliente):
    difs = C.diferencias(_cfg(), _nueva(mutacion))
    assert difs == [(ruta, antes, despues, caliente)]


def test_diferencias_sin_cambios_ni_metadatos():
    nueva = _nueva(_mutar("generado_at", "2026-09-27T08:00:00-04:00"), _mutar("generado_por", "otro"))
    assert nueva.config_version != _cfg().config_version and nueva.sha256 != _cfg().sha256
    assert C.diferencias(_cfg(), nueva) == []


def test_diferencias_definicion_y_estrategias_nuevas_o_quitadas_no_son_calientes():
    def otra(obj):
        e = copy.deepcopy(obj["estrategias"][0])
        e["strategy_id"] = "nueva-2"
        obj["estrategias"].append(e)
    difs = {r: c for r, _, _, c in C.diferencias(_cfg(), _nueva(otra))}
    assert difs == {"estrategias.nueva-2": False}
    difs = C.diferencias(_nueva(otra), _cfg())
    assert [(r, d, c) for r, _, d, c in difs] == [("estrategias.nueva-2", None, False)]
    cambio_def = _nueva(_mutar("estrategias.0.definition.custom_end_time", "12:00"))
    difs = C.diferencias(_cfg(), cambio_def)
    assert [(r, c) for r, _, _, c in difs] == [("estrategias.prueba-1.definition_hash", False)]


def test_diferencias_bool_frente_a_entero_es_cambio():
    nueva = dataclasses.replace(_cfg(), tecnicos={**_cfg().tecnicos, "get_con_simbolo": 1})
    assert [r for r, *_ in C.diferencias(_cfg(), nueva)] == ["tecnicos.get_con_simbolo"]


def test_aplicar_con_bot_encendido_y_posiciones_acepta_C_y_rechaza_A():
    actual = _cfg()
    nueva = _nueva(_mutar("estrategias.0.riesgo_usd", 450), _mutar("vigilando", False),
                   _mutar("locates.tope_gasto_pct_cuenta", 2.5), _mutar("stops.principal_limite_pct", 4.0),
                   _mutar("estrategias.0.definition.custom_end_time", "12:00"), _mutar("fase", "real"))
    copia_actual, copia_nueva = copy.deepcopy(actual), copy.deepcopy(nueva)
    res, rechazadas = C.aplicar(actual, nueva, bot_encendido=True, hay_posiciones=True)
    assert sorted(rechazadas) == ["estrategias.prueba-1.definition_hash", "fase", "stops.principal_limite_pct"]
    assert res.estrategias["prueba-1"].riesgo_usd == Decimal("450")
    assert res.vigilando is False and res.locates["tope_gasto_pct_cuenta"] == 2.5
    assert res.stops["principal_limite_pct"] == 3.0 and res.fase is Fase.SOMBRA
    assert res.estrategias["prueba-1"].hora_fin_sesion == "11:30"
    assert res.estrategias["prueba-1"].definition_hash == actual.estrategias["prueba-1"].definition_hash
    assert res.config_version == nueva.config_version and res.sha256 == nueva.sha256     # fichero procesado
    assert actual == copia_actual and nueva == copia_nueva                                # nada mutado
    assert C.diferencias(res, nueva) and all(not c for *_, c in C.diferencias(res, nueva))   # solo quedan [A]
    res.locates["tope_gasto_pct_cuenta"] = 0
    assert actual.locates["tope_gasto_pct_cuenta"] == 3.0 and nueva.locates["tope_gasto_pct_cuenta"] == 2.5


@pytest.mark.parametrize("encendido, posiciones, aplica_todo", [
    (False, False, True), (True, False, False), (False, True, False), (True, True, False),
], ids=["CM2 apagado sin posiciones", "CM2 encendido sin posiciones", "CM2 apagado con posiciones",
        "CM2 encendido con posiciones"])
def test_aplicar_A_solo_con_bot_apagado_y_sin_posiciones(encendido, posiciones, aplica_todo):
    nueva = _nueva(_mutar("stops.emergencia_disparo_pct", 12.0), _mutar("pausar_entradas", True))
    res, rechazadas = C.aplicar(_cfg(), nueva, bot_encendido=encendido, hay_posiciones=posiciones)
    assert res.pausar_entradas is True
    if aplica_todo:
        assert res is nueva and rechazadas == []
    else:
        assert rechazadas == ["stops.emergencia_disparo_pct"] and res.stops["emergencia_disparo_pct"] == 13.0


def test_aplicar_rechaza_estrategia_nueva_con_bot_vivo():
    def otra(obj):
        e = copy.deepcopy(obj["estrategias"][0])
        e["strategy_id"] = "nueva-2"
        obj["estrategias"].append(e)
    res, rechazadas = C.aplicar(_cfg(), _nueva(otra), bot_encendido=True, hay_posiciones=False)
    assert rechazadas == ["estrategias.nueva-2"] and set(res.estrategias) == {"prueba-1"}


def test_aplicar_sin_diferencias_no_rechaza_nada():
    res, rechazadas = C.aplicar(_cfg(), _cfg(), bot_encendido=True, hay_posiciones=True)
    assert rechazadas == [] and res == _cfg()


# ── motor_hash (H-6) ───────────────────────────────────────────────────
@pytest.fixture
def base_motor(tmp_path) -> Path:
    base = tmp_path / "backend"
    for rel in C.FICHEROS_MOTOR:
        destino = base / rel
        destino.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(BACKEND / rel, destino)
    return base


def test_motor_hash_es_el_sha_de_los_tres_concatenados(base_motor):
    h = hashlib.sha256()
    for rel in C.FICHEROS_MOTOR:
        h.update((base_motor / rel).read_bytes().replace(b"\r\n", b"\n"))
    assert C.motor_hash(base_motor) == "sha256:" + h.hexdigest()
    assert C.motor_hash(base_motor) == C.motor_hash(BACKEND)          # copia fiel = mismo hash


@pytest.mark.parametrize("indice", [0, 1, 2], ids=["H-6 strategy_engine", "H-6 market_frame", "H-6 portfolio_sim"])
def test_motor_hash_cambia_con_un_byte(base_motor, indice):
    antes = C.motor_hash(base_motor)
    ruta = base_motor / C.FICHEROS_MOTOR[indice]
    datos = bytearray(ruta.read_bytes())
    pos = len(datos) // 2
    datos[pos] = ord("x") if datos[pos] != ord("x") else ord("y")
    ruta.write_bytes(bytes(datos))
    assert C.motor_hash(base_motor) != antes


def test_motor_hash_ignora_finales_de_linea(base_motor):
    antes = C.motor_hash(base_motor)
    ruta = base_motor / C.FICHEROS_MOTOR[1]
    ruta.write_bytes(ruta.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
    assert C.motor_hash(base_motor) == antes


def test_motor_hash_sin_fichero_lanza(base_motor):
    (base_motor / C.FICHEROS_MOTOR[2]).unlink()
    with pytest.raises(FileNotFoundError):
        C.motor_hash(base_motor)


def test_ficheros_motor_son_los_tres_compartidos():
    assert C.FICHEROS_MOTOR == ("app/services/strategy_engine.py", "app/services/market_frame.py",
                                "app/services/portfolio_sim.py")


# ── exportar_desde_backend (puente) ────────────────────────────────────
class _Backend:
    """http.server local en hilo que imita GET /api/bot-alerts/vigiladas."""

    def __init__(self) -> None:
        self.estado = 200
        self.cuerpo: bytes = b"{}"
        self.peticiones: list[tuple[str, dict]] = []
        padre = self

        class Manejador(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                padre.peticiones.append((self.path, dict(self.headers)))
                self.send_response(padre.estado)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(padre.cuerpo)))
                self.end_headers()
                self.wfile.write(padre.cuerpo)

            def log_message(self, *a):
                return

        self.servidor = ThreadingHTTPServer(("127.0.0.1", 0), Manejador)
        self.hilo = threading.Thread(target=self.servidor.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.servidor.server_address[1]}"

    def responder(self, obj: Any, estado: int = 200) -> None:
        self.estado = estado
        self.cuerpo = obj if isinstance(obj, bytes) else json.dumps(obj).encode("utf-8")


@pytest.fixture
def backend():
    b = _Backend()
    b.hilo.start()
    try:
        yield b
    finally:
        b.servidor.shutdown()
        b.servidor.server_close()
        b.hilo.join(5)


def _fila_backend(sid: str = "s-1", **cambios: Any) -> dict:
    """Forma exacta de una fila de bot_alerts_service.vigiladas (l.790-822)."""
    d = copy.deepcopy(_crudo()["estrategias"][0]["definition"])
    fila = {"strategy_id": sid, "name": f"Estrategia {sid}", "origen": "portfolio", "riesgo_usd": 250.0,
            "riesgo_piramide_usd": None, "riesgos_piramide": None, "ev_pct": 5.0, "ev_rangos": None,
            "capital_usd": None, "cuentas": None, "definition": d,
            "ventana": {"inicio": "04:00", "fin": "11:30"},
            "ventana_entradas": [{"inicio": "04:00", "fin": "09:29"}]}
    fila.update(cambios)
    return fila


def test_exportar_escribe_un_fichero_valido(backend, tmp_path, base_motor):
    backend.responder({"total": 2, "estrategias": [_fila_backend("s-1"), _fila_backend("s-2", ev_pct=None)]})
    destino = tmp_path / "config" / "bot_das_config.json"
    cfg = C.exportar_desde_backend(backend.url, destino, RUTA_EJEMPLO, cuenta_das=CUENTA, base_motor=base_motor)
    assert cfg is not None and set(cfg.estrategias) == {"s-1", "s-2"}
    assert backend.peticiones[0][0] == "/api/bot-alerts/vigiladas"
    assert not any(k.lower() == "authorization" for k in backend.peticiones[0][1])
    leida = C.cargar(destino, CUENTA)
    assert leida == cfg
    assert leida.config_version == 1 and leida.motor_hash == C.motor_hash(base_motor)
    assert leida.fase is Fase.SOMBRA and leida.stops == C.cargar(RUTA_EJEMPLO, CUENTA).stops
    e1, e2 = leida.estrategias["s-1"], leida.estrategias["s-2"]
    assert e1.riesgo_usd == Decimal("250.0") and e1.ev_pct == Decimal("5.0")
    assert e2.ev_pct == Decimal("4.0")                            # ev null → el de la plantilla
    assert e1.ejecutar is True and e1.excluir_ipo is False       # de la plantilla de defaults
    crudo = json.loads(destino.read_text(encoding="utf-8"))
    assert crudo["generado_por"].startswith("puente") and "ventana" not in crudo["estrategias"][0]
    assert C.validar(crudo) == []


def test_exportar_sube_version_y_conserva_ejecutar(backend, tmp_path, base_motor):
    backend.responder({"total": 1, "estrategias": [_fila_backend("s-1")]})
    destino = tmp_path / "c.json"
    C.exportar_desde_backend(backend.url, destino, RUTA_EJEMPLO, cuenta_das=CUENTA, base_motor=base_motor)
    crudo = json.loads(destino.read_text(encoding="utf-8"))
    crudo["estrategias"][0]["ejecutar"] = False                  # Jaume la apagó en el cuadro
    C.escribir_atomico(destino, _firmar(crudo, definiciones=False))
    backend.responder({"total": 1, "estrategias": [_fila_backend("s-1", riesgo_usd=100.0)]})
    cfg = C.exportar_desde_backend(backend.url + "/api/", destino, RUTA_EJEMPLO, cuenta_das=CUENTA,
                                   base_motor=base_motor)
    assert cfg.config_version == 2
    assert cfg.estrategias["s-1"].ejecutar is False and cfg.estrategias["s-1"].riesgo_usd == Decimal("100.0")
    assert backend.peticiones[-1][0] == "/api/bot-alerts/vigiladas"


def test_exportar_lista_vacia_es_respuesta_real(backend, tmp_path, base_motor):
    backend.responder({"total": 0, "estrategias": []})
    cfg = C.exportar_desde_backend(backend.url, tmp_path / "c.json", RUTA_EJEMPLO, cuenta_das=CUENTA,
                                   base_motor=base_motor)
    assert cfg is not None and cfg.estrategias == {}


@pytest.mark.parametrize("cuerpo, estado", [
    ({"detail": "Bot de alertas desactivado"}, 503), (b"no es json", 200), ({"total": 1}, 200),
    ([1, 2], 200), ({"detail": "Missing bearer token"}, 401),
], ids=["CM1 backend 503", "CM1 json roto", "CM1 sin lista", "CM1 no objeto", "CM1 auth 401"])
def test_exportar_devuelve_none_y_no_escribe(backend, tmp_path, base_motor, cuerpo, estado):
    backend.responder(cuerpo, estado)
    destino = tmp_path / "c.json"
    assert C.exportar_desde_backend(backend.url, destino, RUTA_EJEMPLO, cuenta_das=CUENTA,
                                    base_motor=base_motor) is None
    assert not destino.exists()


def test_exportar_backend_apagado_devuelve_none(tmp_path, base_motor):
    b = _Backend()                                              # puerto reservado y cerrado sin servir
    url = b.url
    b.servidor.server_close()
    assert C.exportar_desde_backend(url, tmp_path / "c.json", RUTA_EJEMPLO, cuenta_das=CUENTA,
                                    base_motor=base_motor, timeout_s=2.0) is None
    assert not (tmp_path / "c.json").exists()


@pytest.mark.parametrize("filas", [
    [{"name": "sin id", "definition": {}}], [_fila_backend("s-1", definition=None)],
    [_fila_backend("s-1"), _fila_backend("s-1")], [_fila_backend("s-1", riesgo_usd=0)],
], ids=["CM4 sin strategy_id", "CM4 sin definition", "CM2 id repetido", "CM2 riesgo 0 ejecutando"])
def test_exportar_filas_malas_no_escriben(backend, tmp_path, base_motor, filas):
    backend.responder({"total": len(filas), "estrategias": filas})
    destino = tmp_path / "c.json"
    with pytest.raises(C.ConfigInvalida):
        C.exportar_desde_backend(backend.url, destino, RUTA_EJEMPLO, cuenta_das=CUENTA, base_motor=base_motor)
    assert not destino.exists()


def test_exportar_cuenta_del_entorno(backend, tmp_path, base_motor, monkeypatch):
    backend.responder({"total": 0, "estrategias": []})
    monkeypatch.setenv("DAS_CUENTA", "CUENTA_ENTORNO")
    cfg = C.exportar_desde_backend(backend.url, tmp_path / "c.json", RUTA_EJEMPLO, base_motor=base_motor)
    assert cfg.cuenta_das == "CUENTA_ENTORNO"
    assert "CUENTA_ENTORNO" not in (tmp_path / "c.json").read_text(encoding="utf-8")   # R-Q-01


# ── VigilanteConfig (CM1) ──────────────────────────────────────────────
@pytest.fixture
def ficheros(tmp_path):
    ruta, bueno = tmp_path / "config" / "bot_das_config.json", tmp_path / "config" / "ultimo_bueno.json"
    C.escribir_atomico(ruta, _crudo())
    return ruta, bueno


def _version(n: int, *mutaciones) -> dict:
    obj = _crudo()
    obj["config_version"] = n
    for m in mutaciones:
        m(obj)
    return _firmar(obj)


def test_vigilante_detecta_un_os_replace_en_su_hilo(ficheros):
    ruta, bueno = ficheros
    recibidas: list[tuple[Config, Optional[str]]] = []
    llego = threading.Event()

    def al_cambio(cfg, aviso):
        recibidas.append((cfg, aviso))
        llego.set()

    v = C.VigilanteConfig(ruta, bueno, CUENTA, al_cambio, cada_s=0.02)
    v.arrancar()
    try:
        assert v.vivo and v.ultima is not None and v.ultima.config_version == 1
        C.escribir_atomico(ruta, _version(2, _mutar("estrategias.0.riesgo_usd", 400)))
        assert llego.wait(5), "el vigilante no vio el os.replace"
    finally:
        v.parar()
    assert not v.vivo
    cfg, aviso = recibidas[0]
    assert aviso is None and cfg.config_version == 2 and cfg.estrategias["prueba-1"].riesgo_usd == Decimal("400")
    assert C.cargar(bueno, CUENTA).config_version == 2                # queda como último bueno
    assert len(recibidas) == 1


def test_vigilante_casos_sincronos(ficheros):
    ruta, bueno = ficheros
    recibidas: list[tuple[Config, Optional[str]]] = []
    v = C.VigilanteConfig(ruta, bueno, CUENTA, lambda c, a: recibidas.append((c, a)))
    with v._cerrojo:                                  # punto de partida sin arrancar el hilo
        v._firma_vista = C._firma(ruta)
        v._ultima = C.cargar(ruta, CUENTA)
    assert v.comprobar() is False                     # nada cambió

    C.escribir_atomico(ruta, _crudo())                # mismo contenido reescrito
    assert v.comprobar() is False and recibidas == []

    C.escribir_atomico(ruta, _version(3, _mutar("vigilando", False)))
    assert v.comprobar() is True and recibidas[-1][1] is None and recibidas[-1][0].vigilando is False

    C.escribir_atomico(ruta, _version(2))              # retrocede
    assert v.comprobar() is True
    cfg, aviso = recibidas[-1]
    assert cfg.config_version == 3 and "retrocede" in aviso
    assert C.cargar(bueno, CUENTA).config_version == 3

    C.escribir_atomico(ruta, _version(3, _mutar("pausar_entradas", True)))    # contenido nuevo, versión igual
    assert v.comprobar() is True
    cfg, aviso = recibidas[-1]
    assert cfg.pausar_entradas is True and "sin subir config_version" in aviso

    ruta.write_text('{"roto": ', encoding="utf-8")   # corrupto → último bueno + aviso
    assert v.comprobar() is True
    cfg, aviso = recibidas[-1]
    assert cfg.pausar_entradas is True and cfg.config_version == 3 and "último bueno" in aviso

    ruta.unlink()                                    # desaparece → último bueno + aviso
    assert v.comprobar() is True and "último bueno" in recibidas[-1][1]
    assert v.comprobar() is False                    # sin cambios nuevos, no insiste


def test_vigilante_sobrevive_a_un_al_cambio_que_lanza(ficheros):
    ruta, bueno = ficheros

    def revienta(cfg, aviso):
        raise RuntimeError("receptor roto")

    v = C.VigilanteConfig(ruta, bueno, CUENTA, revienta)
    with v._cerrojo:
        v._firma_vista = C._firma(ruta)
        v._ultima = C.cargar(ruta, CUENTA)
    C.escribir_atomico(ruta, _version(2))
    assert v.comprobar() is True and "receptor roto" in v.ultimo_error
    assert v.ultima.config_version == 2


def test_vigilante_sin_config_de_partida_ni_ultimo_bueno(tmp_path):
    ruta = _escribir(tmp_path / "c.json", {"roto": True})
    recibidas = []
    v = C.VigilanteConfig(ruta, tmp_path / "ub.json", CUENTA, lambda c, a: recibidas.append((c, a)))
    ruta.write_text('{"roto": 1}', encoding="utf-8")
    assert v.comprobar() is False and recibidas == [] and v.ultimo_error


def test_vigilante_rechaza_intervalo_no_positivo(tmp_path):
    with pytest.raises(ValueError):
        C.VigilanteConfig(tmp_path / "c.json", tmp_path / "u.json", CUENTA, lambda c, a: None, cada_s=0)


# ── línea de comandos ──────────────────────────────────────────────────
def test_main_hash(capsys, base_motor):
    assert C.main(["hash", "--base", str(base_motor)]) == 0
    assert capsys.readouterr().out.strip() == C.motor_hash(base_motor)
    assert C.main(["hash", "--base", str(base_motor / "no")]) == 1


def test_main_validar(capsys, tmp_path):
    assert C.main(["validar", "--ruta", str(RUTA_EJEMPLO)]) == 0
    assert "OK" in capsys.readouterr().out
    malo = _crudo()
    malo["halts"]["k_max"] = 0
    ruta = _escribir(tmp_path / "m.json", _firmar(malo))
    assert C.main(["validar", "--ruta", str(ruta)]) == 1
    assert "k_max" in capsys.readouterr().out
    assert C.main(["validar", "--ruta", str(tmp_path / "no.json")]) == 1


def test_main_validar_por_defecto_lee_BOT_DAS_DIR(dir_bot, capsys):
    C.escribir_atomico(dir_bot / "config" / C.NOMBRE_FICHERO_CONFIG, _crudo())
    assert C.main(["validar"]) == 0


def test_main_exportar(backend, dir_bot, capsys):
    backend.responder({"total": 1, "estrategias": [_fila_backend("s-1")]})
    assert C.main(["exportar", "--url", backend.url, "--defaults", str(RUTA_EJEMPLO)]) == 0
    destino = dir_bot / "config" / C.NOMBRE_FICHERO_CONFIG
    assert destino.exists() and C.validar(json.loads(destino.read_text(encoding="utf-8"))) == []
    assert json.loads(destino.read_text(encoding="utf-8"))["motor_hash"] == C.motor_hash(BACKEND)
    backend.responder({"x": 1}, 500)
    assert C.main(["exportar", "--url", backend.url, "--defaults", str(RUTA_EJEMPLO)]) == 1
    assert "No se ha escrito nada" in capsys.readouterr().out


@pytest.mark.parametrize("argv", [[], ["borrar"], ["hash", "--nada"]], ids=["sin orden", "orden desconocida",
                                                                             "opcion desconocida"])
def test_main_uso_incorrecto(argv, capsys):
    assert C.main(argv) == 2


# ── importar no ejecuta nada ──────────────────────────────────────────
def test_importar_no_carga_httpx_ni_pandas_ni_hilos():
    codigo = ("import sys, threading; import app.bot_das.config; "
              "print('httpx' in sys.modules, 'pandas' in sys.modules, threading.active_count())")
    salida = subprocess.run([sys.executable, "-c", codigo], cwd=str(BACKEND), capture_output=True, text=True,
                            timeout=60, env={**os.environ, "PYTHONPATH": str(BACKEND)})
    assert salida.returncode == 0, salida.stderr
    assert salida.stdout.split() == ["False", "False", "1"]
