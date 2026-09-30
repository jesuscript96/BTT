"""Fichero de configuración del cuadro de mandos del bot de ejecución en DAS.

QUÉ HACE
  Lee, valida, compara y escribe el fichero del cuadro (`config/bot_das_config.json`,
  esquema del documento §7): hash canónico, escritura atómica, último bueno,
  diferencias caliente/apagado (CM2), coherencia horaria de cada estrategia
  (R-L-02), hash del motor compartido (H-6), un hilo que vigila el fichero
  (CM1) y el puente provisional que lo genera desde `/api/bot-alerts/vigiladas`
  mientras no exista la pestaña «Ejecución».

POR QUÉ ESTÁ AQUÍ
  El bot NO llama al backend en caliente (CM1): la app (o el puente
  `python -m app.bot_das.config exportar`) escribe un fichero y el bot lo lee.
  Un fichero escrito a medias o corrupto no puede dejar al bot con tamaños
  vacíos sin saberlo (H-4): va con versión y `sha256` dentro, se escribe con
  `tmp` + `os.replace` en el mismo directorio y, si no valida, se usa el
  último bueno y se avisa. En caliente solo cambian los campos [C] de §7; un
  [A]/[T] distinto del cargado NO se aplica con el bot encendido o con
  posiciones (CM2, R-O-01) y el decisor lo anota como `config_cambio` (CM3).

LAS TRAMPAS
  * `hash_canonico` es EXACTAMENTE sha256(json.dumps(obj, sort_keys=True,
    separators=(",", ":"), ensure_ascii=False).encode("utf-8")), hex sin
    prefijo: el lote 0 firmó `config_ejemplo.json` así y un test lo comprueba.
    `definition_hash` y `estrategias_hash` llevan el prefijo "sha256:"; el
    campo `sha256` no.
  * `json.loads` acepta NaN e Infinity por defecto y claves repetidas (gana la
    última en silencio): aquí las dos cosas son corrupción y se rechazan.
  * Un número del JSON puede ser `bool` (True es int en Python): los rangos
    rechazan booleanos explícitamente.
  * La sesión de una estrategia es la UNIÓN de las casillas marcadas
    (memoria «la sesión se SUMA»): `["rth", "custom"]` con custom 04:00-12:00
    corre 04:00-16:00. `extraer_estrategia` calcula el fin de sesión igual que
    el motor y `comprobar_coherencia` lo avisa.
  * La ventana de ENTRADAS del motor incluye su minuto final
    (`build_entry_time_mask`: `<=`) y la de SESIÓN lo excluye
    (`_get_market_sessions_mask`: `<`): una ventana 09:30-11:30 con sesión
    hasta 11:30 tiene su último minuto fuera de sesión.
  * `motor_hash` normaliza CRLF → LF antes de hashear: la misma revisión del
    motor en dos clones con distinto `core.autocrlf` daría hashes distintos
    y el bot se negaría a operar (falso positivo de H-6).
  * Importar este módulo no abre red, no lee ficheros y no arranca hilos; las
    variables de entorno se leen en la llamada. Sin httpx (fuga de tokens en
    el log, memoria): el puente usa urllib.
"""
from __future__ import annotations

import argparse
import copy
import dataclasses
import hashlib
import json
import logging
import math
import os
import re
import tempfile
import threading
import urllib.error
import urllib.request
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable, Iterable, Optional, Sequence

from app.bot_das.cerrojo import HiloVigilado
from app.bot_das.reloj import ET
from app.bot_das.tipos import PERSEGUIR_ASK_MAX, REPLACE_SHARE_ES_ABIERTA, Config, EstrategiaConfig, Fase

logger = logging.getLogger("btt.bot_das.config")

# ── constantes del fichero ─────────────────────────────────────────────
ESQUEMA_VERSION = 1                                     # `schema_version` que entiende este código (§7)
FICHEROS_MOTOR = ("app/services/strategy_engine.py",   # memoria «tres ficheros compartidos» (H-6)
                  "app/services/market_frame.py",
                  "app/services/portfolio_sim.py")
NOMBRE_FICHERO_CONFIG = "bot_das_config.json"           # BOT_DAS_DIR/config/… (§1)
NOMBRE_ULTIMO_BUENO = "ultimo_bueno.json"               # BOT_DAS_DIR/config/… (H-4)
AVISO_FASE_FORZADA = "fase forzada a SOMBRA"            # SEG-02: marca del aviso cuando el respaldo venía en canario/real
DIR_BOT_POR_DEFECTO = r"D:\bot_senales\bot_ejecucion\vivo"   # §1: BOT_DAS_DIR si no está en el entorno
URL_BACKEND_POR_DEFECTO = "http://127.0.0.1:8010"       # igual que bot_alerts_cliente._base (BOT_ALERTS_API)
RUTA_VIGILADAS = "/bot-alerts/vigiladas"                # routers/bot_alerts.py l.725 (prefijo /api/bot-alerts)
TZ_BOT = "America/New_York"                             # el bot trabaja en ET (reloj.ET); otra tz sería ignorada
VIGILANTE_CADA_S = 1.0                                  # §7: mtime cada 1 s
EXPORTAR_TIMEOUT_S = 10.0
AL_DESACTIVAR = ("esperar_fin_dia", "cerrar_y_reiniciar")   # R-E-03
SALIDA_MOTOR = ("como_tp", "ignorar")                   # §14 pregunta 3
FUENTES_SPLITS = ("massive", "nasdaq_daily_list")       # §14 pregunta 6
TIPOS_STOP = ("STOPLMTP",)                              # R-C-01 v3: el único tipo de stop del bot

# Rutas con punto marcadas [C] en §7: EXACTAMENTE esas y ninguna más (CM2).
# Las de estrategia llevan `*` en lugar del strategy_id.
CALIENTE: frozenset[str] = frozenset({
    "vigilando",
    "pausar_entradas",
    "horario.tz", "horario.encender", "horario.apagar",
    "modo_seguridad.activo", "modo_seguridad.precio_min", "modo_seguridad.acum_dollar_volume_min",
    "lista_negra",
    "entrada.alto_riesgo_si",
    "locates.tope_gasto_pct_cuenta", "locates.hora_limite_intentos",
    "alertas_grupo_a.activo", "alertas_grupo_a.prealerta_simple",
    "alertas_grupo_a.prealerta_freno_min", "alertas_grupo_a.prealerta_ticks",
    "estrategias.*.ejecutar", "estrategias.*.avisar_grupo_a",
    "estrategias.*.riesgo_usd", "estrategias.*.riesgo_piramide_usd", "estrategias.*.riesgos_piramide",
    "estrategias.*.capital_usd", "estrategias.*.ev_pct", "estrategias.*.ev_rangos",
    "estrategias.*.cuentas", "estrategias.*.excluir_ipo", "estrategias.*.al_desactivar",
})
_PREFIJO_ESTRATEGIA = "estrategias.*."
# `sin_ev` se DERIVA de ev_pct (que es [C]): cambia con él en caliente; si no, quitar o poner el EV con el bot
# encendido lo rechazaba como [A] y dejaba la marca desfasada (Decisión 23, Jaume 30-sep).
_CALIENTE_ESTRATEGIA = frozenset(r[len(_PREFIJO_ESTRATEGIA):] for r in CALIENTE
                                 if r.startswith(_PREFIJO_ESTRATEGIA)) | {"sin_ev"}

# Campos de Config que identifican el FICHERO procesado, no su contenido: no son diferencias.
_META = ("sha256", "config_version", "generado_at", "estrategias_hash")
# Campos de EstrategiaConfig que se DERIVAN de `definition`: su cambio ya lo dice `definition_hash`.
_DERIVADOS_ESTRATEGIA = ("hora_fin_sesion", "ventana_entradas", "hora_salida", "accept_reentries",
                         "max_reentries", "niveles_piramide", "es_rth", "definition", "con_repeticiones")

# Decisión 20 (Jaume 30-sep): PENDIENTE FUTURO. Por seguridad, una estrategia con algún nivel de pirámide con
# repeticiones (`times` ≥ 2 o «ilimitado») NO ejecuta: carga, queda con ejecutar=false y avisa (como la de sin EV).
MOTIVO_REPETICIONES = "pirámide con repeticiones: no soportada aún"
_TIMES_ILIMITADO = frozenset({"inf", "infinity", "unlimited", "ilimitado", "ilimitadas", "∞"})


def _times_con_repeticiones(valor: Any) -> bool:
    """Decisión 20 (Jaume 30-sep): ¿este `times` de un nivel de pirámide significa MÁS de una vez?

    1, ausente, None, 0 o "" → una vez (lo que hace `strategy_engine.compile_strategy_def`: `max(1, int(times))`),
    pirámide normal. Un entero ≥ 2 → repeticiones. El motor no tiene un «ilimitado» (tope 100; −1 o texto no
    numérico los lee como 1), pero por seguridad cualquier valor que pueda significarlo (negativo, infinito,
    «inf»/«ilimitado»…) o que no se entienda cuenta como repeticiones: mejor no ejecutar que comprar sin tope.
    """
    if valor is None or isinstance(valor, bool):
        return False
    if isinstance(valor, str):
        texto = valor.strip().lower()
        if texto == "":
            return False
        if texto in _TIMES_ILIMITADO:
            return True
        try:
            valor = float(texto)
        except ValueError:
            return True
    if not isinstance(valor, (int, float, Decimal)):
        return True
    numero = float(valor)
    if not math.isfinite(numero) or numero < 0:
        return True
    return int(numero) >= 2


def niveles_con_repeticiones(niveles: Any) -> list[int]:
    """Decisión 20 (Jaume 30-sep): posiciones (en `pyramiding.levels`) de los niveles con repeticiones. Nunca lanza."""
    if not isinstance(niveles, list):
        return []
    return [k for k, nivel in enumerate(niveles)
            if isinstance(nivel, dict) and _times_con_repeticiones(nivel.get("times"))]


def _niveles_de_definicion(definicion: Any) -> Any:
    piramide = definicion.get("pyramiding") if isinstance(definicion, dict) else None
    return piramide.get("levels") if isinstance(piramide, dict) else None

# ── esquema de §7 ──────────────────────────────────────────────────────
# Tipos de hoja: "bool", "num" (finito), "num+" (> 0), "num0" (≥ 0), "num?" (null o num0),
# "int0" (entero ≥ 0), "int+" (entero > 0), "str", "str?", "ruta" (texto no vacío),
# "hhmm" (HH:MM estricto), "hhmm?", "lnum+" (lista no vacía de num+), "lstr" (lista de textos),
# "riesgo" (objeto cuyas claves son de CRITERIOS_ALTO_RIESGO con valor num+; {} = nunca), ("enum", valores…).
_ESQUEMA_BLOQUES: dict[str, Any] = {
    "horario": {"tz": "ruta", "encender": "hhmm", "apagar": "hhmm?"},
    "modo_seguridad": {"activo": "bool", "precio_min": "num0", "acum_dollar_volume_min": "num0"},
    "locates": {"tope_gasto_pct_cuenta": "num", "hora_limite_intentos": "hhmm?",
                "umbral_ultimo_paquete_pct": "num0", "inquiry_intervalo_s": "num+", "ruta_inquire": "ruta",
                "espera_intento_s": "num+"},
    "entrada": {"agregar_s": "num0", "nivel": "ruta", "post_only": "bool", "tope_caida_bid_pct": "num0",
                "cruce_bajo_bid_pct": "num0", "cruce_espera_s": "num0", "caducidad_senal_s": "num+",
                "distancia_max_ultimo_bid_pct": "num?", "retraso_max_senal_pct": "num?",
                "fraccion_max_volumen_acum": "num?", "reintentos_rechazo_conocido": "int0",
                "alto_riesgo_si": "riesgo"},
    "salidas": {
        "por_hora": {"anticipo_s": "num0", "nivel": "ruta", "al_ask_sin_tope": "bool",
                     "perseguir_ask_max": "int0", "perseguir_ask_s": "num0"},
        "eod": {"lanzar_antes_s": "num0", "comprobar_despues_s": "num0"},
        "tp_parcial": {"agregar_s": "num0", "techo_ask_pct": "num0",
                       "perseguir_ask_max": "int0", "perseguir_ask_s": "num0"},   # decisión 13 (Jaume 30-sep)
        "cerrar_todo": {"techo_pct": "num0", "reintentos": "int0"},
        "salida_motor": ("enum",) + SALIDA_MOTOR,
        "sl_motor_con_posicion_abierta": "ruta",
    },
    "stops": {"tipo": ("enum",) + TIPOS_STOP, "limite_pct": "num+", "proteccion_desconocidas_pct": "num+",
              "margen_bajo_limit_up_pct": "num0", "reintentos": "int0", "separacion_reintentos_s": "num0",
              "ventana_min": "num0", "subida_max_cierre_pct": "num+", "comprobacion_s": "num+",
              "debounce_s": "num0", "tipo_esperado_en_order": "str?", "ruta": "ruta",
              "replace_share_es_abierta": "bool"},
    "halts": {"k_max": "int", "distancia_banda_k2_pct": "num0", "primera_vela_max_reentrada_pct": "num0",
              "primera_vela_max_senal_guardada_pct": "num0", "t1_subida_max_cierre_pct": "num+",
              "t12_min": "num+", "ruta_reapertura": "ruta", "enviar_antes_fin_halt_s": "num0",
              "margen_limite_pm_pct": "num0"},
    "exclusiones": {"spac_sic": "lstr", "ipo_dias": "int0", "split_del_dia": "bool",
                    "fuente_splits": ("enum",) + FUENTES_SPLITS,
                    "opa_banda": {"minutos": "num+", "rango_max_pct": "num0", "dolares_min": "num0"}},
    "rutas": {"agregar": {"ge_1": "ruta", "lt_1": "ruta"},
              "cruzar": {"ge_1": "ruta", "lt_1_desde_0700": "ruta", "lt_1_antes_0700": "ruta"},
              "stop": "ruta", "halt": "ruta"},
    "tecnicos": {
        "barrido_s": {"tras_fill": "num+", "ventana_tras_fill_s": "num0", "con_posiciones": "num+", "sin_nada": "num+"},
        "reconciliacion_fallida_s": "num+",
        "feed": {"prealerta_s": "num+", "emergencia_s": "num+"},
        "das_reconexion_s": "lnum+", "das_aviso_cada_min": "num+",
        "vigilante": {"relanzar_s": "lnum+", "colgado_s": "num+", "latido_s": "num+", "ping_externo_s": "num+",
                      "ping_fallos_alarma": "int+", "plan_b_latido_s": "num+", "plan_b_descubierta_s": "num+",
                      "cerrar_si_descubierta": "bool", "margen_aviso": "num+"},
        "reloj": {"negarse_s": "num+", "aviso_s": "num+", "sntp": "ruta"},
        "disco_min_gb": "num0",
        "cisne_negro_informes": {"primeros": "int0", "cadencia_inicial_s": "num+", "cadencia_despues_s": "num+"},
        "filtro_prints_ms": "num0", "get_con_simbolo": "bool", "max_lv1": "int+",
        "cuotas": {"ordenes_s": "num+", "cancel_min": "num+", "replace_min": "num+", "locate_min": "num+",
                   "margen": "num+"},
        "cola_aviso_umbral": "int+", "foto_cada_s": "num+",
    },
    "alertas_grupo_a": {"activo": "bool", "prealerta_simple": "bool", "prealerta_freno_min": "num0",
                        "prealerta_ticks": "bool"},
}
# Jaume 29-sep (stop único, R-C-01 v4): las claves del par principal + emergencia de v3. Un cuadro que las traiga NO
# carga (`validar`): hoy hay UN stop por nivel con `stops.limite_pct`.
CLAVES_STOPS_V3: tuple[str, ...] = ("principal_limite_pct", "emergencia_disparo_pct", "emergencia_limite_pct")
# Hojas OPCIONALES (ruta → defecto): si faltan, el fichero sigue siendo válido y `_construir` pone el defecto;
# si están, se validan con su tipo del esquema. Así un fichero viejo (y config_ejemplo.json, con su sha256) vale.
_OPCIONALES: dict[str, Any] = {
    "stops.replace_share_es_abierta": REPLACE_SHARE_ES_ABIERTA,   # A-02: share del REPLACE = abierta (True) o total
    "entrada.alto_riesgo_si": {},                                 # D1-07: {} = ningún corto es de alto riesgo
    "salidas.tp_parcial.perseguir_ask_max": PERSEGUIR_ASK_MAX,     # decisión 13 (Jaume 30-sep): el TP persigue 3 veces
    "salidas.tp_parcial.perseguir_ask_s": 1,                      # decisión 13: cada 1 s (como salidas.por_hora)
}
_ESQUEMA_RAIZ: dict[str, Any] = {
    "schema_version": "int", "config_version": "int0", "generado_at": "str",
    "motor_hash": "hash", "estrategias_hash": "hash", "sha256": "hex",
    "fase": ("enum",) + tuple(f.value for f in Fase), "vigilando": "bool", "pausar_entradas": "bool",
    "lista_negra": "lstr",
}

# D1-07: criterios de «alto riesgo» (tope corto 0,5 × equity, libro 2c) que entiende capital.es_alto_riesgo; es
# un conjunto CERRADO: cada clave es un umbral > 0 y basta con que se cumpla UNO. `entrada.alto_riesgo_si` es un
# objeto (el decisor se lo pasa tal cual a es_alto_riesgo como Mapping), no una lista.
CRITERIOS_ALTO_RIESGO: tuple[str, ...] = ("precio_max", "tasa_corta_min_pct")

_RE_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")          # fichero del cuadro: estricto (reloj.a_hora_et)
_RE_HORA_DEF = re.compile(r"^(\d{1,2}):(\d{2})$")           # definition: como la parte el motor (split(":"))
_RE_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_SESIONES = {                                              # minutos desde medianoche, fin EXCLUSIVO (motor)
    # DC-08: SOLO los nombres que entiende `_get_market_sessions_mask` (backtest_service): pre, rth, regular,
    # market, post (+ custom aparte). «premarket»/«afterhours» NO: el motor no da ninguna vela con ellos y el bot
    # tiene que decirlo como «sesiones desconocidas» (R-L-02), no inventarse una sesión que el motor no corre.
    "pre": (240, 570),
    "rth": (570, 960), "regular": (570, 960), "market": (570, 960),
    "post": (960, 1200),
}
_CUSTOM_POR_DEFECTO = ("09:30", "16:00")                   # backtest_service l.2452-2453
_APERTURA_RTH_MIN = 570                                    # 09:30
_HORA_TP_POR_DEFECTO = "15:30"                             # strategy_engine l.1697


class ConfigInvalida(ValueError):
    """El fichero del cuadro no se puede usar (H-4). `errores` lista cada motivo en castellano."""

    def __init__(self, errores: Iterable[str]) -> None:
        self.errores: list[str] = [str(e) for e in errores] or ["configuración inválida"]
        super().__init__("; ".join(self.errores))


# ── hashes ─────────────────────────────────────────────────────────────
def hash_canonico(obj: Any) -> str:
    """H-4: sha256 hex (64, SIN prefijo) de json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False) en UTF-8.

    Es la fórmula con la que el lote 0 firmó `config_ejemplo.json`; cambiar un
    solo argumento de `json.dumps` invalida todos los ficheros ya escritos.
    Trampa: no admite `Decimal` ni NaN (json lanza), a propósito: lo que se
    firma es lo que se escribe.
    """
    texto = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def motor_hash(base: Path) -> str:
    """H-6 / R-O-01 / A13: "sha256:" + sha256 de los tres ficheros de FICHEROS_MOTOR concatenados en ese orden.

    `base` es el directorio `backend` (el que contiene `app/services`). El bot
    compara este valor con el `motor_hash` del fichero al arrancar y se niega
    a operar si no coincide. Trampa evitada: los finales de línea se
    normalizan (CRLF → LF) antes de hashear, para que la misma revisión en dos
    clones con distinto `core.autocrlf` dé el mismo hash. Lanza OSError
    (FileNotFoundError) si falta un fichero: sin motor no hay hash que comparar.
    """
    h = hashlib.sha256()
    for relativa in FICHEROS_MOTOR:
        h.update(Path(base, relativa).read_bytes().replace(b"\r\n", b"\n"))
    return "sha256:" + h.hexdigest()


def _hash_prefijado(obj: Any) -> str:
    return "sha256:" + hash_canonico(obj)


# ── escritura y lectura ───────────────────────────────────────────────
def escribir_atomico(ruta: Path, obj: dict) -> None:
    """H-4: escribe `obj` con `sha256` = hash_canonico(resto) en `tmp` del MISMO directorio + fsync + os.replace.

    `os.replace` es atómico en Windows y en POSIX solo dentro del mismo
    volumen, por eso el temporal va junto al destino y no en %TEMP%. `obj` no
    se modifica (el `sha256` que traiga se ignora y se recalcula). Si algo
    falla, el destino anterior queda intacto, el temporal se borra y la
    excepción sube (quien escribe debe saberlo). Crea el directorio si falta.
    """
    if not isinstance(obj, dict):
        raise TypeError(f"escribir_atomico espera un dict, no {type(obj).__name__}")
    ruta = Path(ruta)
    resto = {k: v for k, v in obj.items() if k != "sha256"}
    final = dict(resto)
    final["sha256"] = hash_canonico(resto)
    texto = json.dumps(final, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    ruta.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=ruta.name + ".", suffix=".tmp", dir=str(ruta.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(texto)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, ruta)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _sin_constantes(nombre: str) -> Any:
    raise ValueError(f"valor no finito en el JSON: {nombre}")


def _sin_repetidas(pares: list[tuple[str, Any]]) -> dict:
    d: dict = {}
    for k, v in pares:
        if k in d:
            raise ValueError(f"clave repetida en el JSON: {k!r}")
        d[k] = v
    return d


def _leer_json(ruta: Path) -> dict:
    """Lee un JSON de objeto; NaN/Infinity y claves repetidas son corrupción. Lanza ConfigInvalida."""
    ruta = Path(ruta)
    try:
        texto = ruta.read_bytes().decode("utf-8-sig")
    except OSError as exc:
        raise ConfigInvalida([f"no se pudo leer {ruta}: {exc.__class__.__name__}: {exc}"]) from exc
    except UnicodeDecodeError as exc:
        raise ConfigInvalida([f"{ruta} no es UTF-8: {exc}"]) from exc
    try:
        obj = json.loads(texto, parse_constant=_sin_constantes, object_pairs_hook=_sin_repetidas)
    except ValueError as exc:                      # JSONDecodeError es ValueError
        raise ConfigInvalida([f"{ruta} no es JSON válido: {exc}"]) from exc
    if not isinstance(obj, dict):
        raise ConfigInvalida([f"{ruta} no contiene un objeto JSON"])
    return obj


# ── validación ─────────────────────────────────────────────────────────
def _es_num(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and x == x and x not in (float("inf"), float("-inf"))


def _es_int(x: Any) -> bool:
    return isinstance(x, int) and not isinstance(x, bool)


def _comprobar_hoja(ruta: str, tipo: Any, x: Any, errores: list[str]) -> None:
    if isinstance(tipo, tuple):                    # ("enum", valores…)
        if x not in tipo[1:]:
            errores.append(f"{ruta}: {x!r} no es uno de {list(tipo[1:])}")
        return
    ok = {
        "bool": lambda: isinstance(x, bool),
        "num": lambda: _es_num(x),
        "num+": lambda: _es_num(x) and x > 0,
        "num0": lambda: _es_num(x) and x >= 0,
        "num?": lambda: x is None or (_es_num(x) and x >= 0),
        "int": lambda: _es_int(x),
        "int0": lambda: _es_int(x) and x >= 0,
        "int+": lambda: _es_int(x) and x > 0,
        "str": lambda: isinstance(x, str),
        "str?": lambda: x is None or isinstance(x, str),
        "ruta": lambda: isinstance(x, str) and x.strip() != "",
        "hhmm": lambda: isinstance(x, str) and _RE_HHMM.match(x) is not None,
        "hhmm?": lambda: x is None or (isinstance(x, str) and _RE_HHMM.match(x) is not None),
        "lnum+": lambda: isinstance(x, list) and len(x) > 0 and all(_es_num(v) and v > 0 for v in x),
        "lstr": lambda: isinstance(x, list) and all(isinstance(v, str) and v.strip() != "" for v in x),
        "hash": lambda: isinstance(x, str) and x.startswith("sha256:") and _RE_HEX64.match(x[7:]) is not None,
        "hex": lambda: isinstance(x, str) and _RE_HEX64.match(x) is not None,
        "riesgo": lambda: isinstance(x, dict) and all(k in CRITERIOS_ALTO_RIESGO and _es_num(v) and v > 0
                                                      for k, v in x.items()),
    }[tipo]()
    if not ok:
        errores.append(f"{ruta}: valor {x!r} no válido (se espera {tipo})")


def _comprobar_bloque(prefijo: str, esquema: dict, valor: Any, errores: list[str]) -> None:
    if not isinstance(valor, dict):
        errores.append(f"{prefijo}: falta o no es un objeto")
        return
    for clave, tipo in esquema.items():
        ruta = f"{prefijo}.{clave}"
        if clave not in valor:
            if ruta not in _OPCIONALES:
                errores.append(f"{ruta}: falta")
        elif isinstance(tipo, dict):
            _comprobar_bloque(ruta, tipo, valor[clave], errores)
        else:
            _comprobar_hoja(ruta, tipo, valor[clave], errores)


def _minutos_def(x: Any) -> int:
    """Hora de la DEFINICIÓN («H:MM» o «HH:MM», como la parte el motor) → minutos. ValueError si no."""
    m = _RE_HORA_DEF.match(x) if isinstance(x, str) else None
    if m is None:
        raise ValueError(f"hora mal formada: {x!r}")
    h, mi = int(m.group(1)), int(m.group(2))
    if h > 23 or mi > 59:
        raise ValueError(f"hora fuera de rango: {x!r}")
    return h * 60 + mi


def _hhmm(minutos: int) -> str:
    return f"{minutos // 60:02d}:{minutos % 60:02d}"


def _validar_definicion(prefijo: str, d: Any, errores: list[str]) -> None:
    """Horas de la definición (sesión, ventanas de entrada, TP por hora): «horas mal formadas» de §7."""
    if not isinstance(d, dict):
        errores.append(f"{prefijo}.definition: falta o no es un objeto")
        return
    sesiones = d.get("market_sessions")
    if sesiones is not None and not (isinstance(sesiones, list) and all(isinstance(s, str) for s in sesiones)):
        errores.append(f"{prefijo}.definition.market_sessions: debe ser una lista de textos")
    for clave in ("custom_start_time", "custom_end_time"):
        v = d.get(clave)
        if v not in (None, ""):
            try:
                _minutos_def(v)
            except ValueError as exc:
                errores.append(f"{prefijo}.definition.{clave}: {exc}")
    el = d.get("entry_logic") or {}
    if not isinstance(el, dict):
        errores.append(f"{prefijo}.definition.entry_logic: no es un objeto")
        el = {}
    ventanas = el.get("entry_time_windows")
    if ventanas is not None and not isinstance(ventanas, list):
        errores.append(f"{prefijo}.definition.entry_logic.entry_time_windows: debe ser una lista")
        ventanas = None
    for i, w in enumerate(ventanas or []):
        if not isinstance(w, dict):
            errores.append(f"{prefijo}.definition.entry_logic.entry_time_windows[{i}]: no es un objeto")
            continue
        for clave in ("from_time", "to_time"):
            v = w.get(clave)
            if v not in (None, ""):
                try:
                    _minutos_def(v)
                except ValueError as exc:
                    errores.append(f"{prefijo}.definition.entry_logic.entry_time_windows[{i}].{clave}: {exc}")
    rm = d.get("risk_management") or {}
    if not isinstance(rm, dict):
        errores.append(f"{prefijo}.definition.risk_management: no es un objeto")
        return
    tp = rm.get("take_profit")
    if isinstance(tp, dict) and tp.get("type") == "Hour" and tp.get("value") not in (None, ""):
        try:
            _minutos_def(tp.get("value"))
        except ValueError as exc:
            errores.append(f"{prefijo}.definition.risk_management.take_profit.value: {exc}")


def _validar_estrategia(i: int, e: Any, vistos: set[str], errores: list[str]) -> None:
    # Decisión 23 (Jaume 30-sep): ev_pct null es válido (sin EV → carga pero no ejecuta); ausente sigue siendo error.
    if not isinstance(e, dict):
        errores.append(f"estrategias[{i}]: no es un objeto")
        return
    sid = e.get("strategy_id")
    prefijo = f"estrategias[{i}]" if not isinstance(sid, str) else f"estrategias.{sid}"
    if not isinstance(sid, str) or not sid.strip():
        errores.append(f"estrategias[{i}].strategy_id: falta o está vacío")
    elif sid in vistos:
        errores.append(f"{prefijo}: strategy_id repetido")
    else:
        vistos.add(sid)
    for clave, tipo in (("name", "str"), ("origen", "str"), ("ejecutar", "bool"), ("avisar_grupo_a", "bool"),
                        ("excluir_ipo", "bool"), ("ev_pct", "num?"), ("al_desactivar", ("enum",) + AL_DESACTIVAR),
                        ("definition_hash", "hash")):
        if clave not in e:
            errores.append(f"{prefijo}.{clave}: falta")
        else:
            _comprobar_hoja(f"{prefijo}.{clave}", tipo, e[clave], errores)
    riesgo = e.get("riesgo_usd")
    if e.get("ejecutar") is True:
        if not (_es_num(riesgo) and riesgo > 0):
            errores.append(f"{prefijo}.riesgo_usd: {riesgo!r} debe ser > 0 con ejecutar=true")
    elif riesgo is not None and not (_es_num(riesgo) and riesgo >= 0):
        errores.append(f"{prefijo}.riesgo_usd: {riesgo!r} no es un número ≥ 0")
    for clave in ("riesgo_piramide_usd", "capital_usd"):
        v = e.get(clave)
        if v is not None and not (_es_num(v) and v > 0):
            errores.append(f"{prefijo}.{clave}: {v!r} debe ser null o > 0")
    rp = e.get("riesgos_piramide")
    if rp is not None and not (isinstance(rp, list) and all(v is None or (_es_num(v) and v > 0) for v in rp)):
        errores.append(f"{prefijo}.riesgos_piramide: debe ser null o una lista de (null | > 0)")
    evr = e.get("ev_rangos")
    if evr is not None and not (isinstance(evr, list) and all(isinstance(r, dict) for r in evr)):
        errores.append(f"{prefijo}.ev_rangos: debe ser null o una lista de objetos")
    _validar_definicion(prefijo, e.get("definition"), errores)
    if isinstance(e.get("definition"), dict) and isinstance(e.get("definition_hash"), str):
        esperado = _hash_prefijado(e["definition"])
        if e["definition_hash"] != esperado:
            errores.append(f"{prefijo}.definition_hash: no casa con la definición (esperado {esperado})")


def validar(crudo: dict) -> list[str]:
    """H-4 / §7: lista de errores del fichero crudo ([] = válido). No lanza.

    Comprueba: esquema (claves de §7 y su tipo), `schema_version`, `sha256` =
    hash_canonico(resto), `estrategias_hash` y cada `definition_hash`, y los
    rangos imposibles de §7: stops.limite_pct > 0 (R-C-01 v4), k_max ≥ 1
    (R-F-01), tope_gasto_pct_cuenta ∈ (0, 10] (R-H-03), horas HH:MM, fase ∈
    Fase (R-O-03; «demo» ya no existe), riesgo_usd > 0 si ejecutar, rutas no
    vacías, tz = America/New_York. Trampa: booleanos no cuentan como números.
    Un cuadro con las claves del par de stops de v3 (`CLAVES_STOPS_V3`:
    principal_limite_pct, emergencia_disparo_pct, emergencia_limite_pct) NO
    carga (Jaume 29-sep, stop único): el esquema ignora las claves que no
    conoce, y un fichero viejo arrancaría con el 50 % por defecto sin que
    nadie lo hubiera decidido; el error dice qué hacer.
    """
    if not isinstance(crudo, dict):
        return ["la configuración no es un objeto JSON"]
    errores: list[str] = []
    for clave, tipo in _ESQUEMA_RAIZ.items():
        if clave not in crudo:
            errores.append(f"{clave}: falta")
        else:
            _comprobar_hoja(clave, tipo, crudo[clave], errores)
    if _es_int(crudo.get("schema_version")) and crudo["schema_version"] != ESQUEMA_VERSION:
        errores.append(f"schema_version: {crudo['schema_version']} no soportada (este código entiende {ESQUEMA_VERSION})")
    for bloque, esquema in _ESQUEMA_BLOQUES.items():
        _comprobar_bloque(bloque, esquema, crudo.get(bloque), errores)

    horario = crudo.get("horario")
    if isinstance(horario, dict) and isinstance(horario.get("tz"), str) and horario["tz"] != TZ_BOT:
        errores.append(f"horario.tz: {horario['tz']!r}: el bot trabaja en {TZ_BOT}")
    stops = crudo.get("stops")
    if isinstance(stops, dict):
        viejas = [k for k in CLAVES_STOPS_V3 if k in stops]
        if viejas:
            errores.append(f"stops: cuadro de DOS stops ({', '.join(viejas)}): desde el 29-sep hay un solo stop por "
                           f"nivel, usa stops.limite_pct (R-C-01 v4, Jaume 29-sep)")
    halts = crudo.get("halts")
    if isinstance(halts, dict) and _es_int(halts.get("k_max")) and halts["k_max"] < 1:
        errores.append(f"halts.k_max: {halts['k_max']} debe ser ≥ 1 (R-F-01)")
    locates = crudo.get("locates")
    if isinstance(locates, dict) and _es_num(locates.get("tope_gasto_pct_cuenta")):
        t = locates["tope_gasto_pct_cuenta"]
        if not 0 < t <= 10:
            errores.append(f"locates.tope_gasto_pct_cuenta: {t} fuera de (0, 10] (R-H-03)")

    estrategias = crudo.get("estrategias")
    if not isinstance(estrategias, list):
        errores.append("estrategias: falta o no es una lista")
    else:
        vistos: set[str] = set()
        for i, e in enumerate(estrategias):
            _validar_estrategia(i, e, vistos, errores)
        if isinstance(crudo.get("estrategias_hash"), str):
            try:
                esperado = _hash_prefijado(estrategias)
            except (TypeError, ValueError) as exc:
                errores.append(f"estrategias: no serializable: {exc}")
            else:
                if crudo["estrategias_hash"] != esperado:
                    errores.append(f"estrategias_hash: no casa con el bloque estrategias (esperado {esperado})")

    if isinstance(crudo.get("sha256"), str):
        try:
            esperado = hash_canonico({k: v for k, v in crudo.items() if k != "sha256"})
        except (TypeError, ValueError) as exc:
            errores.append(f"sha256: el contenido no es serializable: {exc}")
        else:
            if crudo["sha256"] != esperado:
                errores.append("sha256: no casa con el contenido (fichero alterado o escrito a medias; H-4)")
    return errores


# ── estrategias ────────────────────────────────────────────────────────
def _dec(x: Any, campo: str) -> Decimal:
    if isinstance(x, bool) or x is None:
        raise ValueError(f"{campo}: {x!r} no es un número")
    if isinstance(x, Decimal):
        valor = x
    else:
        try:
            valor = Decimal(str(x).strip() if isinstance(x, str) else str(x))
        except (InvalidOperation, ValueError) as exc:
            raise ValueError(f"{campo}: {x!r} no es un número") from exc
    if not valor.is_finite():
        raise ValueError(f"{campo}: {x!r} no es finito")
    return valor


def _dec_opcional(x: Any, campo: str) -> Optional[Decimal]:
    return None if x is None else _dec(x, campo)


def _intervalos_sesion(d: dict) -> tuple[Optional[list[tuple[int, int]]], list[str]]:
    """Unión de las sesiones marcadas, como el motor (`mask |=`). None = sin acotar. Devuelve también los nombres desconocidos."""
    sesiones = d.get("market_sessions") or []
    nombres = [str(s).lower().strip() for s in sesiones]
    if not nombres or "all" in nombres:
        return None, []
    intervalos: list[tuple[int, int]] = []
    desconocidas: list[str] = []
    for s in nombres:
        if s in _SESIONES:
            intervalos.append(_SESIONES[s])
        elif s == "custom":
            ini = d.get("custom_start_time") or _CUSTOM_POR_DEFECTO[0]
            fin = d.get("custom_end_time") or _CUSTOM_POR_DEFECTO[1]
            intervalos.append((_minutos_def(ini), _minutos_def(fin)))
        else:
            desconocidas.append(s)
    unidos: list[tuple[int, int]] = []
    for ini, fin in sorted(i for i in intervalos if i[0] < i[1]):
        if unidos and ini <= unidos[-1][1]:
            unidos[-1] = (unidos[-1][0], max(unidos[-1][1], fin))
        else:
            unidos.append((ini, fin))
    return unidos, desconocidas


def _ventanas(d: dict) -> list[tuple[int, int]]:
    """Ventanas de entrada completas en minutos (fin INCLUSIVO, `build_entry_time_mask`); las incompletas se saltan como en el motor."""
    el = d.get("entry_logic") or {}
    out = []
    for w in (el.get("entry_time_windows") or []) if isinstance(el, dict) else []:
        if isinstance(w, dict) and w.get("from_time") and w.get("to_time"):
            out.append((_minutos_def(w["from_time"]), _minutos_def(w["to_time"])))
    return out


def _hora_salida(d: dict) -> Optional[str]:
    """TP por hora del motor (strategy_engine l.1685-1697): solo si use_take_profit no es False y no es modo Partial con parciales."""
    rm = d.get("risk_management") or {}
    if not isinstance(rm, dict) or rm.get("use_take_profit") is False:
        return None
    if rm.get("take_profit_mode", "Full") == "Partial" and rm.get("partial_take_profits"):
        return None
    tp = rm.get("take_profit")
    if isinstance(tp, dict) and tp.get("type") == "Hour":
        return _hhmm(_minutos_def(tp.get("value") or _HORA_TP_POR_DEFECTO))
    return None


def extraer_estrategia(v: dict) -> EstrategiaConfig:
    """CM4 / R-L-02 / ÁREA P: EstrategiaConfig desde la fila del cuadro + su `definition` (leída como el motor).

    De la definición: hora_fin_sesion = fin de la UNIÓN de sesiones (None si
    sin acotar); ventana_entradas = `entry_logic.entry_time_windows` tal cual;
    hora_salida = TP «Hour» si el motor lo usaría; accept_reentries /
    max_reentries con los defaults del motor (False; −1 si acepta, 0 si no);
    niveles_piramide = `pyramiding.levels`; es_rth = toda la ventana de
    entradas EFECTIVA (recortada a la sesión) empieza ≥ 09:30.
    definition_hash = el de la fila o "sha256:" + hash_canonico(definition).
    Claves ausentes → defaults documentados; horas mal formadas, strategy_id
    ausente o ev_pct/riesgo no numéricos → ValueError (no se inventa dinero).
    """
    if not isinstance(v, dict):
        raise ValueError("la estrategia no es un objeto")
    sid = v.get("strategy_id")
    if not isinstance(sid, str) or not sid.strip():
        raise ValueError("estrategia sin strategy_id")
    d = v.get("definition")
    if not isinstance(d, dict):
        raise ValueError(f"estrategia {sid}: sin definition")
    definicion = copy.deepcopy(d)
    rm = definicion.get("risk_management") or {}
    rm = rm if isinstance(rm, dict) else {}

    intervalos, _ = _intervalos_sesion(definicion)
    hora_fin = _hhmm(max(f for _, f in intervalos)) if intervalos else None
    ventanas = _ventanas(definicion)
    if ventanas:
        inicios = []
        for ini, fin in ventanas:
            if intervalos is None:
                inicios.append(ini)
                continue
            efectivos = [max(ini, a) for a, b in intervalos if max(ini, a) <= min(fin, b - 1)]
            if efectivos:
                inicios.append(min(efectivos))
        es_rth = bool(inicios) and min(inicios) >= _APERTURA_RTH_MIN
    else:
        es_rth = bool(intervalos) and min(a for a, _ in intervalos) >= _APERTURA_RTH_MIN

    accept = bool(rm.get("accept_reentries", False))
    max_re = rm.get("max_reentries", -1 if accept else 0)
    if not _es_int(max_re):
        raise ValueError(f"estrategia {sid}: max_reentries {max_re!r} no es entero")
    piramide = definicion.get("pyramiding") or {}
    niveles = piramide.get("levels") if isinstance(piramide, dict) else None
    el = definicion.get("entry_logic") or {}
    ventana_cruda = el.get("entry_time_windows") if isinstance(el, dict) else None

    # Decisión 23 (Jaume 30-sep): EV nulo/ausente → carga, pero NO ejecuta (aunque el cuadro diga ejecutar=true);
    # el decisor descarta sus señales como «sin ejecutar» y avisa una vez al día. Nunca se inventa un EV.
    sin_ev = v.get("ev_pct") is None
    # Decisión 20 (Jaume 30-sep): pirámide con repeticiones → carga, pero NO ejecuta (aunque diga ejecutar=true).
    con_repeticiones = bool(niveles_con_repeticiones(niveles))
    ejecutar = v.get("ejecutar", False) is True and not sin_ev and not con_repeticiones
    riesgo = v.get("riesgo_usd")
    riesgos_p = v.get("riesgos_piramide") or []
    return EstrategiaConfig(
        strategy_id=sid,
        name=str(v.get("name") or sid),
        origen=str(v.get("origen") or "portfolio"),
        ejecutar=ejecutar,
        avisar_grupo_a=v.get("avisar_grupo_a", False) is True,
        riesgo_usd=_dec(riesgo, f"{sid}.riesgo_usd") if riesgo is not None else Decimal("0"),
        riesgos_piramide=[_dec_opcional(x, f"{sid}.riesgos_piramide") for x in riesgos_p],
        riesgo_piramide_usd=_dec_opcional(v.get("riesgo_piramide_usd"), f"{sid}.riesgo_piramide_usd"),
        ev_pct=Decimal("0") if sin_ev else _dec(v.get("ev_pct"), f"{sid}.ev_pct"),
        ev_rangos=copy.deepcopy(list(v.get("ev_rangos") or [])),
        excluir_ipo=v.get("excluir_ipo", True) is True,
        al_desactivar=str(v.get("al_desactivar") or AL_DESACTIVAR[0]),
        hora_fin_sesion=hora_fin,
        ventana_entradas=copy.deepcopy(list(ventana_cruda or [])),
        hora_salida=_hora_salida(definicion),
        accept_reentries=accept,
        max_reentries=max_re,
        niveles_piramide=copy.deepcopy(list(niveles or [])),
        es_rth=es_rth,
        definition_hash=v.get("definition_hash") or _hash_prefijado(definicion),
        definition=definicion,
        sin_ev=sin_ev,
        con_repeticiones=con_repeticiones,
    )


def comprobar_coherencia(e: EstrategiaConfig) -> list[str]:
    """R-L-02: avisos de coherencia horaria de UNA estrategia ([] = nada raro). No lanza.

    Avisa de: sesión «sumada» (custom junto a pre/rth/post: el motor corre la
    UNIÓN, memoria «la sesión se SUMA»), sesión sin acotar o con nombres
    desconocidos, ventana de entradas al revés o fuera de la sesión (el
    minuto final de la ventana entra; el de la sesión no), y hora_salida
    posterior al fin de sesión (el EOD llegaría antes que la salida por hora).
    """
    avisos: list[str] = []
    d = e.definition if isinstance(e.definition, dict) else {}
    try:
        intervalos, desconocidas = _intervalos_sesion(d)
        ventanas = _ventanas(d)
    except ValueError as exc:
        return [f"{e.name}: definición con horas mal formadas ({exc})"]
    nombres = [str(s).lower().strip() for s in (d.get("market_sessions") or [])]
    if "custom" in nombres and any(n in _SESIONES for n in nombres):
        efectiva = ", ".join(f"{_hhmm(a)}-{_hhmm(b)}" for a, b in intervalos or [])
        avisos.append(f"{e.name}: sesión «sumada» {nombres}: el motor corre la UNIÓN ({efectiva}), "
                      f"no solo el horario personalizado (R-L-02)")
    if desconocidas:
        avisos.append(f"{e.name}: sesiones desconocidas {desconocidas}: el motor no las reconoce (R-L-02)")
    if intervalos is None:
        avisos.append(f"{e.name}: sesión sin acotar (toda la jornada): revisar la ventana a mano (R-L-02)")
    elif not intervalos:
        avisos.append(f"{e.name}: la sesión está vacía: la estrategia no operaría nunca (R-L-02)")
    for ini, fin in ventanas:
        texto = f"{_hhmm(ini)}-{_hhmm(fin)}"
        if ini > fin:
            avisos.append(f"{e.name}: ventana de entradas {texto} al revés (R-L-02)")
        elif intervalos is not None and not any(a <= ini and fin < b for a, b in intervalos):
            sesion = ", ".join(f"{_hhmm(a)}-{_hhmm(b)}" for a, b in intervalos) or "vacía"
            avisos.append(f"{e.name}: ventana de entradas {texto} fuera de la sesión ({sesion}) (R-L-02)")
    if e.hora_salida and e.hora_fin_sesion and _minutos_def(e.hora_salida) > _minutos_def(e.hora_fin_sesion):
        avisos.append(f"{e.name}: hora_salida {e.hora_salida} posterior al fin de sesión {e.hora_fin_sesion}: "
                      f"cerraría antes por EOD (R-L-02)")
    return avisos


# ── carga ──────────────────────────────────────────────────────────────
def _construir(crudo: dict, cuenta_das: str) -> Config:
    """Config desde un crudo YA validado. ValueError de extraer_estrategia → ConfigInvalida."""
    estrategias: dict[str, EstrategiaConfig] = {}
    errores: list[str] = []
    for fila in crudo["estrategias"]:
        try:
            e = extraer_estrategia(fila)
        except ValueError as exc:
            errores.append(str(exc))
            continue
        estrategias[e.strategy_id] = e
    if errores:
        raise ConfigInvalida(errores)
    def bloque(k: str) -> Any:
        valor = copy.deepcopy(crudo[k])
        for ruta, defecto in _OPCIONALES.items():                  # hojas opcionales ausentes → su defecto
            partes = ruta.split(".")
            if partes[0] != k or not isinstance(valor, dict):
                continue
            destino = valor
            for parte in partes[1:-1]:
                destino = destino.setdefault(parte, {})
            destino.setdefault(partes[-1], copy.deepcopy(defecto))
        return valor

    return Config(
        schema_version=crudo["schema_version"], config_version=crudo["config_version"], sha256=crudo["sha256"],
        motor_hash=crudo["motor_hash"], estrategias_hash=crudo["estrategias_hash"], generado_at=crudo["generado_at"],
        fase=Fase(crudo["fase"]), vigilando=crudo["vigilando"], horario=bloque("horario"),
        modo_seguridad=bloque("modo_seguridad"), lista_negra=list(crudo["lista_negra"]),
        pausar_entradas=crudo["pausar_entradas"], locates=bloque("locates"), entrada=bloque("entrada"),
        salidas=bloque("salidas"), stops=bloque("stops"), halts=bloque("halts"), exclusiones=bloque("exclusiones"),
        rutas=bloque("rutas"), tecnicos=bloque("tecnicos"), alertas_grupo_a=bloque("alertas_grupo_a"),
        estrategias=estrategias, cuenta_das=cuenta_das,
    )


def _cargar_crudo(ruta: Path, cuenta_das: str) -> tuple[Config, dict]:
    if not isinstance(cuenta_das, str) or not cuenta_das.strip():
        raise ConfigInvalida(["cuenta_das vacía: DAS_CUENTA debe venir del .env (R-Q-01)"])
    crudo = _leer_json(ruta)
    errores = validar(crudo)
    if errores:
        raise ConfigInvalida(errores)
    return _construir(crudo, cuenta_das), crudo


def cargar(ruta: Path, cuenta_das: str) -> Config:
    """H-4: lee, valida y construye la Config. Lanza ConfigInvalida con TODOS los errores.

    `cuenta_das` viene del `.env` (DAS_CUENTA), nunca del fichero (R-Q-01), y
    no puede estar vacía (SLAvailQuery la exige). Fichero ilegible, JSON roto,
    NaN, claves repetidas, esquema o hash malos → ConfigInvalida.
    """
    return _cargar_crudo(ruta, cuenta_das)[0]


def guardar_ultimo_bueno(cfg_cruda: dict, ultimo_bueno: Path) -> None:
    """H-4: guarda como «último bueno» un crudo que VALIDA (si no, ConfigInvalida y no se escribe nada).

    Se escribe con `escribir_atomico`: un último bueno a medias sería peor que
    no tenerlo. OSError sube.
    """
    errores = validar(cfg_cruda)
    if errores:
        raise ConfigInvalida(errores)
    escribir_atomico(ultimo_bueno, cfg_cruda)


def _cargar_con_respaldo_crudo(ruta: Path, ultimo_bueno: Path,
                               cuenta_das: str) -> tuple[Config, Optional[str], Optional[dict]]:
    """(config, aviso, crudo leído de `ruta` o None si se usó el último bueno)."""
    try:
        cfg, crudo = _cargar_crudo(ruta, cuenta_das)
        return cfg, None, crudo
    except ConfigInvalida as exc1:
        try:
            cfg = cargar(ultimo_bueno, cuenta_das)
        except ConfigInvalida as exc2:
            raise ConfigInvalida([f"{ruta}: {e}" for e in exc1.errores]
                                 + [f"último bueno {ultimo_bueno}: {e}" for e in exc2.errores]) from exc2
        resumen = "; ".join(exc1.errores[:3]) + ("; …" if len(exc1.errores) > 3 else "")
        aviso = (f"Configuración del cuadro inválida ({resumen}): se usa el último bueno "
                 f"(config_version {cfg.config_version}) (H-4)")
        if cfg.fase is not Fase.SOMBRA:
            # SEG-02 / R-O-03: el respaldo NUNCA sube la fase. Si Jaume bajaba de REAL a SOMBRA y el fichero nuevo
            # está roto, arrancar con el último bueno en REAL sería mandar dinero que pidió no mandar.
            aviso += (f" · {AVISO_FASE_FORZADA}: el último bueno estaba en {cfg.fase.value.upper()} y con el "
                      f"fichero del cuadro roto no se opera con dinero; corrige el fichero (SEG-02, R-O-03)")
            cfg = dataclasses.replace(cfg, fase=Fase.SOMBRA)
        return cfg, aviso, None


def cargar_con_respaldo(ruta: Path, ultimo_bueno: Path, cuenta_das: str) -> tuple[Config, Optional[str]]:
    """H-4 / R-I-03: (config, None) si `ruta` valida (y queda guardada como último bueno); si no, (último bueno, aviso).

    Si tampoco vale el último bueno → ConfigInvalida con los errores de los
    dos. Si la config es buena pero no se puede guardar el último bueno, se
    devuelve igualmente con un aviso (el disco falla; la config sirve).
    """
    cfg, aviso, crudo = _cargar_con_respaldo_crudo(ruta, ultimo_bueno, cuenta_das)
    if crudo is not None:
        try:
            guardar_ultimo_bueno(crudo, ultimo_bueno)
        except (OSError, ConfigInvalida) as exc:
            aviso = f"No se pudo guardar el último bueno en {ultimo_bueno}: {exc} (H-4)"
    return cfg, aviso


# ── diferencias en caliente (CM2 / CM3) ────────────────────────────────
def _es_caliente(ruta: tuple[str, ...]) -> bool:
    if ruta[0] == "estrategias":
        return len(ruta) == 3 and ruta[2] in _CALIENTE_ESTRATEGIA
    return ".".join(ruta) in CALIENTE


def _dif(ruta: tuple[str, ...], a: Any, b: Any, out: list[tuple[tuple[str, ...], Any, Any]]) -> None:
    # Una hoja [C] que es un objeto (entrada.alto_riesgo_si, D1-07) se compara y se sustituye ENTERA: sus claves no
    # son rutas de CALIENTE y, abiertas, saldrían como [A] y se rechazarían; al quitar un criterio quedaría a None.
    if isinstance(a, dict) and isinstance(b, dict) and ".".join(ruta) not in CALIENTE:
        for k in sorted(set(a) | set(b), key=str):
            _dif(ruta + (str(k),), a.get(k), b.get(k), out)
    elif a != b or (type(a) is not type(b) and (isinstance(a, bool) or isinstance(b, bool))):   # True == 1 no es «igual»
        out.append((ruta, a, b))


_CAMPOS_ESTRATEGIA = tuple(f.name for f in dataclasses.fields(EstrategiaConfig)
                           if f.name != "strategy_id" and f.name not in _DERIVADOS_ESTRATEGIA)
_CAMPOS_CONFIG = tuple(f.name for f in dataclasses.fields(Config) if f.name not in _META and f.name != "estrategias")


def _diferencias_tupla(vieja: Config, nueva: Config) -> list[tuple[tuple[str, ...], Any, Any]]:
    out: list[tuple[tuple[str, ...], Any, Any]] = []
    for campo in _CAMPOS_CONFIG:
        _dif((campo,), getattr(vieja, campo), getattr(nueva, campo), out)
    for sid in sorted(set(vieja.estrategias) | set(nueva.estrategias)):
        a, b = vieja.estrategias.get(sid), nueva.estrategias.get(sid)
        if a is None or b is None:
            out.append((("estrategias", sid), a, b))
            continue
        for campo in _CAMPOS_ESTRATEGIA:
            _dif(("estrategias", sid, campo), getattr(a, campo), getattr(b, campo), out)
    return out


def diferencias(vieja: Config, nueva: Config) -> list[tuple[str, Any, Any, bool]]:
    """CM2 / CM3: [(ruta con puntos, antes, despues, caliente)] entre dos configs, en orden estable.

    Rutas: "vigilando", "stops.limite_pct", "estrategias.<id>.riesgo_usd";
    una estrategia que aparece o desaparece sale como "estrategias.<id>" (con
    None en el lado que falta; nunca en caliente: R-O-01). Los campos
    derivados de `definition` no salen sueltos: los representa
    `definition_hash`. No son diferencias los metadatos del fichero
    (sha256, config_version, generado_at, estrategias_hash). Una clave
    ausente equivale a null. `caliente` = la ruta está en CALIENTE.
    """
    return [(".".join(r), a, b, _es_caliente(r)) for r, a, b in _diferencias_tupla(vieja, nueva)]


def _poner(arbol: dict, ruta: tuple[str, ...], valor: Any) -> None:
    for k in ruta[:-1]:
        arbol = arbol.setdefault(k, {})
    arbol[ruta[-1]] = copy.deepcopy(valor)


def aplicar(actual: Config, nueva: Config, bot_encendido: bool,
            hay_posiciones: bool) -> tuple[Config, list[str]]:
    """CM2 / R-I-03 / R-O-01: (config resultante, rutas rechazadas). No muta ninguna de las dos.

    Con el bot apagado y sin posiciones se aplica todo (devuelve `nueva`). Si
    no, solo las rutas [C]; cada [A]/[T] distinto se rechaza (el decisor
    avisa nivel 2 y anota `config_cambio` con aplicado=False, CM3). La
    resultante lleva los metadatos del fichero procesado (config_version,
    sha256, generado_at, estrategias_hash de `nueva`) para no reprocesarlo;
    su contenido efectivo es el de `actual` más los [C]. Trampa (riesgo 21):
    se devuelve una Config COMPLETA para sustituirla entre mensajes, nunca a
    medias; los intentos vivos conservan su `cfg_congelada`.
    """
    if not bot_encendido and not hay_posiciones:
        return nueva, []
    cambios: dict[str, Any] = {}
    estrategias = dict(actual.estrategias)
    rechazadas: list[str] = []
    for ruta, _, despues in _diferencias_tupla(actual, nueva):
        if not _es_caliente(ruta):
            rechazadas.append(".".join(ruta))
        elif ruta[0] == "estrategias":
            sid, campo = ruta[1], ruta[2]
            estrategias[sid] = dataclasses.replace(estrategias[sid], **{campo: copy.deepcopy(despues)})
        elif len(ruta) == 1:
            cambios[ruta[0]] = copy.deepcopy(despues)
        else:
            if ruta[0] not in cambios:
                cambios[ruta[0]] = copy.deepcopy(getattr(actual, ruta[0]))
            _poner(cambios[ruta[0]], ruta[1:], despues)
    resultante = dataclasses.replace(
        actual, **cambios, estrategias=estrategias, config_version=nueva.config_version, sha256=nueva.sha256,
        generado_at=nueva.generado_at, estrategias_hash=nueva.estrategias_hash)
    return resultante, rechazadas


# ── vigilante del fichero (CM1) ────────────────────────────────────────
def _firma(ruta: Path) -> Optional[tuple[int, int, int]]:
    try:
        st = os.stat(ruta)
    except OSError:
        return None
    return st.st_mtime_ns, st.st_size, st.st_ino


class VigilanteConfig:
    """CM1 / H-4: HiloVigilado que mira el fichero cada `cada_s` (1 s) y llama a `al_cambio(Config, aviso)`.

    Detecta el cambio por (mtime, tamaño, identificador del fichero): un
    `os.replace` cambia el identificador aunque el mtime coincida. Carga con
    respaldo; entrega: la nueva (aviso None); el último bueno con aviso si la
    nueva no valida; la anterior con aviso si `config_version` retrocede (no
    se aplica); la nueva con aviso si cambió el contenido sin subir la
    versión. El mismo contenido reescrito no se entrega. Solo se guarda como
    último bueno lo que se entrega como nuevo. Un `al_cambio` que lanza no
    mata el hilo (frontera de callback). `comprobar()` hace una pasada
    síncrona (la usan los tests y el arranque).
    """

    def __init__(self, ruta: Path, ultimo_bueno: Path, cuenta_das: str,
                 al_cambio: Callable[[Config, Optional[str]], None], *, cada_s: float = VIGILANTE_CADA_S,
                 al_caida: Optional[Callable[[str, str, bool], None]] = None) -> None:
        if cada_s <= 0:
            raise ValueError(f"cada_s debe ser > 0: {cada_s}")
        self.ruta = Path(ruta)
        self.ultimo_bueno = Path(ultimo_bueno)
        self._cuenta = cuenta_das
        self._al_cambio = al_cambio
        self._cada_s = float(cada_s)
        self._cerrojo = threading.Lock()
        self._firma_vista: Optional[tuple[int, int, int]] = None
        self._ultima: Optional[Config] = None
        self.ultimo_error: Optional[str] = None
        self.entregas = 0
        self._hilo = HiloVigilado("vigilante_config", self._cuerpo, al_caida or (lambda *_: None))

    @property
    def ultima(self) -> Optional[Config]:
        """La última Config conocida (la de partida o la última entregada)."""
        return self._ultima

    @property
    def vivo(self) -> bool:
        return self._hilo.vivo

    def arrancar(self) -> None:
        """Toma la firma y la config actuales como punto de partida (sin entregar) y arranca el hilo."""
        with self._cerrojo:
            self._firma_vista = _firma(self.ruta)
            try:
                self._ultima = cargar(self.ruta, self._cuenta)
            except ConfigInvalida as exc:
                self._ultima = None
                self.ultimo_error = str(exc)
        self._hilo.arrancar()

    def parar(self) -> None:
        self._hilo.parar()

    def _cuerpo(self) -> None:
        while not self._hilo.parando.wait(self._cada_s):
            self.comprobar()

    def comprobar(self) -> bool:
        """Una pasada: True si ha llamado a `al_cambio`."""
        with self._cerrojo:
            firma = _firma(self.ruta)
            if firma == self._firma_vista:
                return False
            self._firma_vista = firma
            try:
                cfg, aviso, crudo = _cargar_con_respaldo_crudo(self.ruta, self.ultimo_bueno, self._cuenta)
            except ConfigInvalida as exc:
                self.ultimo_error = str(exc)
                if self._ultima is None:
                    return False
                cfg, aviso, crudo = self._ultima, f"Configuración inválida y sin último bueno: {exc} (H-4)", None
            previa = self._ultima
            if crudo is not None and previa is not None:
                if cfg.config_version < previa.config_version:
                    aviso = (f"config_version retrocede ({previa.config_version} → {cfg.config_version}): "
                             f"no se aplica (H-4)")
                    cfg, crudo = previa, None
                elif cfg.config_version == previa.config_version:
                    if cfg.sha256 == previa.sha256:
                        return False
                    aviso = (f"El fichero del cuadro cambió sin subir config_version "
                             f"({cfg.config_version}): se aplica igualmente (H-4)")
            if crudo is not None:
                try:
                    guardar_ultimo_bueno(crudo, self.ultimo_bueno)
                except (OSError, ConfigInvalida) as exc:
                    extra = f"No se pudo guardar el último bueno: {exc} (H-4)"
                    aviso = f"{aviso} · {extra}" if aviso else extra
            self._ultima = cfg
            self.entregas += 1
        try:
            self._al_cambio(cfg, aviso)
        except Exception as exc:  # noqa: BLE001 — frontera de callback (CM1): el vigilante del fichero no muere por el receptor
            self.ultimo_error = f"al_cambio: {exc.__class__.__name__}: {exc}"
            logger.warning("[BOT_DAS] al_cambio de la config falló: %s", self.ultimo_error)
        return True


# ── puente provisional desde el backend ────────────────────────────────
def _url_api(url_base: str) -> str:
    """Como bot_alerts_cliente._base: acepta la raíz del backend o ya terminada en /api."""
    raiz = str(url_base).rstrip("/")
    return raiz if raiz.endswith("/api") else f"{raiz}/api"


def _pedir_vigiladas(url_base: str, timeout_s: float) -> Optional[list]:
    """GET /api/bot-alerts/vigiladas. None = no se pudo preguntar; [] = no hay ninguna activa. NUNCA lanza.

    Sin cabecera de autenticación: `bot_alerts_cliente.ClienteBackend` no
    manda ninguna (el backend local corre sin AUTH_ENABLED); con auth
    encendida responde 401 y esto devuelve None. Sin proxies: el backend es
    local y un HTTP_PROXY del entorno lo rompería.
    """
    url = _url_api(url_base) + RUTA_VIGILADAS
    abridor = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    peticion = urllib.request.Request(url, headers={"Accept": "application/json"}, method="GET")
    try:
        with abridor.open(peticion, timeout=timeout_s) as r:
            cuerpo = r.read()
        datos = json.loads(cuerpo.decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 — frontera de red (§3): el puente devuelve None, nunca lanza
        logger.warning("[BOT_DAS] no se pudo leer %s: %s: %s", RUTA_VIGILADAS, exc.__class__.__name__, exc)
        return None
    if not isinstance(datos, dict) or not isinstance(datos.get("estrategias"), list):
        logger.warning("[BOT_DAS] respuesta de %s sin lista 'estrategias'", RUTA_VIGILADAS)
        return None
    return datos["estrategias"]


def _fila_a_estrategia(fila: Any, plantilla: dict, previa: Optional[dict]) -> dict:
    if not isinstance(fila, dict) or not isinstance(fila.get("strategy_id"), str) or not isinstance(fila.get("definition"), dict):
        raise ConfigInvalida([f"fila de /vigiladas sin strategy_id o sin definition: {str(fila)[:120]}"])
    base = previa or plantilla
    definicion = copy.deepcopy(fila["definition"])
    ev = fila.get("ev_pct")
    # Decisión 22 (Jaume 30-sep): una estrategia NUEVA entra apagada; solo Jaume la activa. Las que ya estaban
    # conservan su `ejecutar`. Decisión 23: sin EV en el cuadro → ev_pct null y ejecutar=false (no el EV de la plantilla).
    ejecutar = previa is not None and previa.get("ejecutar", False) is True and ev is not None
    # Decisión 20 (Jaume 30-sep): pirámide con repeticiones → ejecutar=false con su motivo en el cuadro.
    repeticiones = niveles_con_repeticiones(_niveles_de_definicion(definicion))
    if repeticiones:
        ejecutar = False
    return {
        **({"motivo_no_ejecuta": f"{MOTIVO_REPETICIONES} (niveles {[k + 1 for k in repeticiones]})"}
           if repeticiones else {}),
        "strategy_id": fila["strategy_id"],
        "name": fila.get("name") or fila["strategy_id"],
        "origen": fila.get("origen") or "portfolio",
        "ejecutar": ejecutar,
        "avisar_grupo_a": base.get("avisar_grupo_a", False) is True,
        "riesgo_usd": fila.get("riesgo_usd"),
        "riesgo_piramide_usd": fila.get("riesgo_piramide_usd"),
        "riesgos_piramide": list(fila.get("riesgos_piramide") or []),
        "capital_usd": fila.get("capital_usd"),
        "ev_pct": ev,
        "ev_rangos": list(fila.get("ev_rangos") or []),
        "cuentas": fila.get("cuentas"),
        "excluir_ipo": base.get("excluir_ipo", True) is True,
        "al_desactivar": base.get("al_desactivar") or AL_DESACTIVAR[0],
        "definition_hash": _hash_prefijado(definicion),
        "definition": definicion,
    }


def exportar_desde_backend(url_base: str, destino: Path, defaults: Path, *, cuenta_das: Optional[str] = None,
                           base_motor: Optional[Path] = None, timeout_s: float = EXPORTAR_TIMEOUT_S,
                           generado_por: str = "puente:bot-alerts/vigiladas") -> Optional[Config]:
    """PUENTE PROVISIONAL (§7, H-4, H-6, CM1): GET /api/bot-alerts/vigiladas + defaults → fichero del cuadro.

    Bloques globales: los de `defaults` (config_ejemplo.json). Por estrategia:
    riesgos, EV, capital, cuentas y definición de la fila del backend (manda
    el cuadro, R-I-03); avisar_grupo_a/excluir_ipo/al_desactivar del
    fichero `destino` anterior si ya la tenía, si no de la primera estrategia
    de `defaults`; `ejecutar` del destino anterior y, si es NUEVA, false
    (Decisión 22, Jaume 30-sep); ev_pct null → queda null y ejecutar=false
    (Decisión 23: sin EV no ejecuta). config_version = la del
    destino anterior + 1 (1 si no hay), para que el vigilante vea que sube.
    motor_hash con `base_motor` (por defecto el `backend` de este paquete).
    Devuelve None si no se pudo preguntar al backend (no escribe nada); lanza
    ConfigInvalida si el resultado no valida (tampoco escribe). La Config
    devuelta lleva `cuenta_das` (o DAS_CUENTA del entorno, o "").
    """
    base_defaults = _leer_json(defaults)
    filas = _pedir_vigiladas(url_base, timeout_s)
    if filas is None:
        return None
    try:
        previo = _leer_json(destino) if Path(destino).exists() else None
    except ConfigInvalida:
        previo = None
    previas: dict[str, dict] = {}
    if previo is not None and isinstance(previo.get("estrategias"), list):
        previas = {e["strategy_id"]: e for e in previo["estrategias"]
                   if isinstance(e, dict) and isinstance(e.get("strategy_id"), str)}
    plantillas = base_defaults.get("estrategias") or []
    plantilla = plantillas[0] if plantillas and isinstance(plantillas[0], dict) else {}
    estrategias = [_fila_a_estrategia(f, plantilla, previas.get(f.get("strategy_id")) if isinstance(f, dict) else None)
                   for f in filas]
    version_previa = previo.get("config_version") if previo is not None else None
    obj = {k: copy.deepcopy(v) for k, v in base_defaults.items() if k not in ("sha256", "estrategias")}
    obj.update({
        "schema_version": ESQUEMA_VERSION,
        "config_version": version_previa + 1 if _es_int(version_previa) and version_previa >= 0 else 1,
        "generado_at": datetime.now(ET).isoformat(timespec="seconds"),
        "generado_por": generado_por,
        "motor_hash": motor_hash(base_motor if base_motor is not None else Path(__file__).resolve().parents[2]),
        "estrategias": estrategias,
        "estrategias_hash": _hash_prefijado(estrategias),
    })
    obj["sha256"] = hash_canonico({k: v for k, v in obj.items() if k != "sha256"})
    errores = validar(obj)
    if errores:
        raise ConfigInvalida(errores)
    escribir_atomico(Path(destino), obj)
    cuenta = cuenta_das if cuenta_das is not None else os.environ.get("DAS_CUENTA", "")
    return _construir(obj, cuenta)


# ── línea de comandos ──────────────────────────────────────────────────
def _dir_bot() -> Path:
    return Path(os.environ.get("BOT_DAS_DIR") or DIR_BOT_POR_DEFECTO)


def _backend() -> Path:
    return Path(__file__).resolve().parents[2]


def main(argv: Optional[Sequence[str]] = None) -> int:
    """python -m app.bot_das.config exportar|validar|hash. 0 = bien, 1 = error, 2 = uso incorrecto."""
    p = argparse.ArgumentParser(prog="python -m app.bot_das.config",
                                description="Fichero del cuadro del bot de ejecución en DAS (§7).")
    sub = p.add_subparsers(dest="orden", required=True)
    pe = sub.add_parser("exportar", help="genera el fichero desde /api/bot-alerts/vigiladas (puente provisional)")
    pe.add_argument("--url", default=None, help="raíz del backend (defecto: BOT_ALERTS_API o http://127.0.0.1:8010)")
    pe.add_argument("--destino", type=Path, default=None, help="defecto: BOT_DAS_DIR/config/bot_das_config.json")
    pe.add_argument("--defaults", type=Path, default=None, help="defecto: tests/bot_das/fixtures/config_ejemplo.json")
    pv = sub.add_parser("validar", help="valida un fichero del cuadro y lista los avisos R-L-02")
    pv.add_argument("--ruta", type=Path, default=None, help="defecto: BOT_DAS_DIR/config/bot_das_config.json")
    ph = sub.add_parser("hash", help="imprime el motor_hash de este backend (H-6)")
    ph.add_argument("--base", type=Path, default=None, help="directorio backend (defecto: el de este paquete)")
    try:
        args = p.parse_args(list(argv) if argv is not None else None)
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 2

    if args.orden == "hash":
        try:
            print(motor_hash(args.base or _backend()))
        except OSError as exc:
            print(f"ERROR: {exc}")
            return 1
        return 0

    if args.orden == "validar":
        ruta = args.ruta or (_dir_bot() / "config" / NOMBRE_FICHERO_CONFIG)
        try:
            crudo = _leer_json(ruta)
        except ConfigInvalida as exc:
            for e in exc.errores:
                print(f"ERROR: {e}")
            return 1
        errores = validar(crudo)
        for e in errores:
            print(f"ERROR: {e}")
        if errores:
            return 1
        cfg = _construir(crudo, "validar")
        for e in cfg.estrategias.values():
            for aviso in comprobar_coherencia(e):
                print(f"AVISO: {aviso}")
        print(f"OK: {ruta} (config_version {cfg.config_version}, {len(cfg.estrategias)} estrategias)")
        return 0

    url = args.url or os.environ.get("BOT_ALERTS_API") or URL_BACKEND_POR_DEFECTO
    destino = args.destino or (_dir_bot() / "config" / NOMBRE_FICHERO_CONFIG)
    defaults = args.defaults or (_backend() / "tests" / "bot_das" / "fixtures" / "config_ejemplo.json")
    try:
        cfg = exportar_desde_backend(url, destino, defaults)
    except (ConfigInvalida, OSError) as exc:
        print(f"ERROR: {exc}")
        return 1
    if cfg is None:
        print(f"ERROR: no se pudo leer {RUTA_VIGILADAS} de {url} (¿backend encendido?). No se ha escrito nada.")
        return 1
    for e in cfg.estrategias.values():
        for aviso in comprobar_coherencia(e):
            print(f"AVISO: {aviso}")
    print(f"OK: {destino} (config_version {cfg.config_version}, {len(cfg.estrategias)} estrategias)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
