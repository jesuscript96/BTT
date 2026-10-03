"""Pestaña «Ejecución» del cuadro de mandos: estado y cuadro del bot de ejecución en DAS.

    GET  /api/bot-das/estado    -> procesos vivos (latidos), foto resumida, avisos de hoy y el cuadro
    PUT  /api/bot-das/cuadro    -> cambia hojas del cuadro, valida con config.cargar y re-firma
    POST /api/bot-das/exportar  -> regenera el cuadro desde /api/bot-alerts/vigiladas (+ cuadro de producción)

QUÉ HACE
  El bot NO habla con el backend (CM1): lee `BOT_DAS_DIR/config/bot_das_config.json`
  cada segundo y aplica lo que se puede aplicar. Este router solo LEE ficheros del
  bot (latidos, foto, diario) y ESCRIBE el fichero del cuadro con las funciones de
  `app.bot_das.config` (hash_canonico, escribir_atomico, cargar, diferencias).

LAS TRAMPAS
  * Se valida ANTES de escribir: el nuevo cuadro se escribe en un temporal, se carga
    con `config.cargar` y solo si carga se escribe el de verdad (422 si no).
  * Las hojas que no son [C] (`config.CALIENTE`, p. ej. `halts.silencio`) el bot las
    IGNORA con el bot encendido o con posiciones (CM2). Regla de Jaume: que avise y
    no lo deje → 409 si hay latido vivo y el bot vigila o tiene posiciones.
  * NUNCA se toma el cerrojo de un proceso del bot para saber si vive (impediría
    arrancar al supervisor si coincide): se mira la edad de los latidos.
  * La exportación se hace sobre un TEMPORAL y se ajusta antes de escribir el
    destino: conserva `ejecutar`/`riesgo_usd`/`ev_pct` de las estrategias que ya
    estaban y `vigilando`, `locates.tope_gasto_dia_usd`, `halts.silencio` (lo que se
    toca desde esta pestaña); así el bot no ve nunca un cuadro intermedio.
  * Los endpoints son `def` (no async): exportar llama por HTTP a este mismo backend
    y en el hilo del bucle se bloquearía a sí mismo.
"""
from __future__ import annotations

import copy
import json
import logging
import os
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.auth import get_current_user_id
from app.bot_das import config as cfgmod
from app.bot_das.reloj import ET

router = APIRouter()
logger = logging.getLogger("btt.bot_das.panel")

PROCESOS_CON_LATIDO = ("ejecutor", "vigilante")       # ejecutor.NOMBRE_LATIDO / vigilante.NOMBRE_LATIDO
LATIDO_VIVO_S = 10.0          # el supervisor da por colgado a los 3 s; 10 s cubre un tic lento sin falsos «apagado»
AVISOS_MAX = 30
TIPOS_AVISO = ("aviso", "incidente", "excepcion", "config_cambio")
COLA_DIARIO_BYTES = 2_000_000  # solo la cola de cada diario: el de un día movido pesa decenas de MB
NOMBRE_LOG_CAMBIOS = "panel_cuadro_cambios.jsonl"     # BOT_DAS_DIR/logs/…

_cerrojo_escritura = threading.Lock()


# ── guardia y rutas ────────────────────────────────────────────────────
def _enabled() -> bool:
    # Mismo interruptor que el bot de alertas: la pestaña vive en su página.
    return os.getenv("BOT_ALERTS_ENABLED", "false").strip().lower() in ("1", "true", "yes", "on")


def _guard() -> None:
    if not _enabled():
        raise HTTPException(status_code=503, detail="Bot de alertas desactivado (BOT_ALERTS_ENABLED)")


def _dir_bot() -> Path:
    return Path(os.environ.get("BOT_DAS_DIR") or cfgmod.DIR_BOT_POR_DEFECTO)


def _ruta_cuadro() -> Path:
    return _dir_bot() / "config" / cfgmod.NOMBRE_FICHERO_CONFIG


def _cuenta() -> str:
    # `cargar` exige una cuenta no vacía; el fichero no la lleva (R-Q-01) y aquí solo se valida.
    return (os.environ.get("DAS_CUENTA") or "").strip() or "panel"


# ── lectura del estado del bot ─────────────────────────────────────────
def _latidos(ahora: float) -> dict[str, dict]:
    salida: dict[str, dict] = {}
    for p in PROCESOS_CON_LATIDO:
        ruta = _dir_bot() / "estado" / f"latido_{p}"
        try:
            epoch = float(ruta.read_text(encoding="ascii").strip())
        except (OSError, ValueError):
            salida[p] = {"vivo": False, "edad_s": None, "ultimo": None}
            continue
        edad = ahora - epoch
        salida[p] = {"vivo": edad <= LATIDO_VIVO_S, "edad_s": round(edad, 1),
                     "ultimo": datetime.fromtimestamp(epoch, ET).isoformat(timespec="seconds")}
    return salida


def _leer_foto(ahora: float) -> tuple[Optional[dict], Optional[float]]:
    ruta = _dir_bot() / "estado" / "foto.json"
    try:
        edad = ahora - ruta.stat().st_mtime
        datos = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, None
    return (datos if isinstance(datos, dict) else None), round(edad, 1)


def _num(x: Any) -> Optional[float]:
    try:
        return None if x is None else float(x)
    except (TypeError, ValueError):
        return None


def _resumen_foto(f: dict) -> dict:
    posiciones = f.get("posiciones") if isinstance(f.get("posiciones"), dict) else {}
    filas_pos = []
    for ticker, p in posiciones.items():
        p = p if isinstance(p, dict) else {}
        lotes = p.get("lotes") if isinstance(p.get("lotes"), list) else []
        filas_pos.append({"ticker": ticker, "neta_das": p.get("neta_das"), "neta_fills": p.get("neta_fills"),
                          "avg_das": p.get("avg_das"), "estado": p.get("estado"), "motivo": p.get("motivo"),
                          "lotes": len(lotes), "cisne_negro": p.get("bs") is not None})
    ordenes = [o for o in (f.get("ordenes") or []) if isinstance(o, dict)]
    cuenta = f.get("cuenta") if isinstance(f.get("cuenta"), dict) else {}
    ejecutor = f.get("ejecutor") if isinstance(f.get("ejecutor"), dict) else {}
    feed = f.get("feed") if isinstance(f.get("feed"), dict) else {}
    das = f.get("das") if isinstance(f.get("das"), dict) else {}
    return {
        "fase": f.get("fase"), "hora_et": f.get("hora_et"), "vigilando": f.get("vigilando"),
        "pausa_global": f.get("pausa_global"), "control_humano": f.get("control_humano"),
        "version_config": f.get("version_config"),
        "posiciones": filas_pos,
        "ordenes": [{k: o.get(k) for k in ("token", "ticker", "lado", "tipo", "qty", "llenas", "precio", "stop",
                                            "estado", "proposito")} for o in ordenes],
        "locates": [loc for loc in (f.get("locates") or []) if isinstance(loc, dict)],
        "gasto_locates_dia": _num(f.get("gasto_locates_dia")),
        "locates_tope_dia": f.get("locates_tope_dia"),
        "locates_deshabilitados": f.get("locates_deshabilitados"),
        "equity": _num(cuenta.get("equity")), "bp": _num(cuenta.get("bp")),
        "das_conectado": das.get("conectado"), "feed_edad_s": feed.get("edad_s"),
        "modos_degradados": f.get("modos_degradados") or [],
        "tickers_pausados": f.get("tickers_pausados") or [],
        "parado": ejecutor.get("parado"), "sombra": ejecutor.get("sombra"), "todo_vivo": ejecutor.get("todo_vivo"),
    }


def _cola(ruta: Path) -> list[str]:
    try:
        with open(ruta, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            tam = fh.tell()
            fh.seek(max(0, tam - COLA_DIARIO_BYTES))
            texto = fh.read().decode("utf-8", errors="replace")
    except OSError:
        return []
    lineas = texto.splitlines()
    return lineas[1:] if tam > COLA_DIARIO_BYTES else lineas   # la primera puede venir partida


def _avisos_de_hoy() -> list[dict]:
    hoy = datetime.now(ET).date().isoformat()
    filas: list[dict] = []
    for ruta in sorted((_dir_bot() / "diario").glob(f"diario_*_{hoy}.jsonl")):
        for linea in _cola(ruta):
            try:
                obj = json.loads(linea)
            except ValueError:
                continue
            if not isinstance(obj, dict) or obj.get("tipo") not in TIPOS_AVISO:
                continue
            datos = obj.get("datos") if isinstance(obj.get("datos"), dict) else {}
            texto = datos.get("texto") or datos.get("tipo") or datos.get("error") or json.dumps(datos, ensure_ascii=False)[:300]
            filas.append({"t": obj.get("t"), "proceso": obj.get("proceso"), "tipo": obj.get("tipo"),
                          "nivel": datos.get("nivel"), "ticker": obj.get("ticker"), "texto": str(texto)[:600]})
    filas.sort(key=lambda r: str(r.get("t") or ""))
    return filas[-AVISOS_MAX:][::-1]


def _leer_crudo(ruta: Path) -> dict:
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    if not isinstance(datos, dict):
        raise ValueError("el cuadro no es un objeto JSON")
    return datos


_DEFECTO_TOPE_LOCATES = cfgmod._OPCIONALES.get("locates.tope_gasto_dia_usd")   # hoja opcional: si falta, esto
_DEFECTO_SILENCIO = cfgmod._OPCIONALES.get("halts.silencio")


def _resumen_cuadro(c: dict) -> dict:
    stops = c.get("stops") if isinstance(c.get("stops"), dict) else {}
    halts = c.get("halts") if isinstance(c.get("halts"), dict) else {}
    locates = c.get("locates") if isinstance(c.get("locates"), dict) else {}
    estrategias = []
    for e in c.get("estrategias") or []:
        if not isinstance(e, dict):
            continue
        estrategias.append({k: e.get(k) for k in ("strategy_id", "name", "origen", "ejecutar", "riesgo_usd",
                                                  "riesgo_piramide_usd", "ev_pct", "motivo_no_ejecuta")})
    return {
        "config_version": c.get("config_version"), "sha256": c.get("sha256"), "generado_at": c.get("generado_at"),
        "generado_por": c.get("generado_por"), "fase": c.get("fase"), "vigilando": c.get("vigilando"),
        "pausar_entradas": c.get("pausar_entradas"),
        "estrategias": estrategias,
        "locates": {"tope_gasto_dia_usd": locates.get("tope_gasto_dia_usd", _DEFECTO_TOPE_LOCATES)},
        "halts": {"silencio": halts.get("silencio", _DEFECTO_SILENCIO)},
        "stops": {k: stops.get(k) for k in ("limite_pct", "limite_tramos", "banda_pct", "banda_tramos", "techo_pct",
                                            "escalon_s", "respaldo", "sin_ejecutar_s", "pref", "ruta")},
        "rutas": c.get("rutas"),
    }


def _estado_bot(ahora: float, crudo: Optional[dict], foto: Optional[dict]) -> dict:
    latidos = _latidos(ahora)
    encendido = any(v["vivo"] for v in latidos.values())
    vigila = bool((crudo or {}).get("vigilando")) or bool((foto or {}).get("vigilando"))
    posiciones = bool((foto or {}).get("posiciones"))
    return {"latidos": latidos, "encendido": encendido,
            # CM2: con esto a true el bot IGNORA las hojas que no son [C]
            "bloquea_no_calientes": encendido and (vigila or posiciones)}


# ── endpoints ──────────────────────────────────────────────────────────
@router.get("/estado")
def estado(user_id: Optional[str] = Depends(get_current_user_id)):
    _guard()
    ahora = time.time()
    ruta = _ruta_cuadro()
    crudo: Optional[dict] = None
    error_cuadro: Optional[str] = None
    if ruta.exists():
        try:
            crudo = _leer_crudo(ruta)
            cfgmod.cargar(ruta, _cuenta())
        except cfgmod.ConfigInvalida as exc:
            error_cuadro = "; ".join(exc.errores[:5])
        except (OSError, ValueError) as exc:
            error_cuadro = f"{type(exc).__name__}: {exc}"
    else:
        error_cuadro = f"no existe {ruta}: exporta el cuadro"
    foto, edad_foto = _leer_foto(ahora)
    est = _estado_bot(ahora, crudo, foto)
    ultimos = [v["ultimo"] for v in est["latidos"].values() if v["ultimo"]]
    return {
        "dir_bot": str(_dir_bot()), "ruta_cuadro": str(ruta),
        **est,
        "ultimo_latido": max(ultimos) if ultimos else None,
        "foto": _resumen_foto(foto) if foto else None, "foto_edad_s": edad_foto,
        "avisos": _avisos_de_hoy(),
        "cuadro": _resumen_cuadro(crudo) if crudo else None, "cuadro_error": error_cuadro,
        "hojas_calientes": sorted(cfgmod.CALIENTE),
    }


class EstrategiaCambio(BaseModel):
    strategy_id: str
    ejecutar: Optional[bool] = None
    riesgo_usd: Optional[float] = None
    ev_pct: Optional[float] = None


class LocatesCambio(BaseModel):
    tope_gasto_dia_usd: float


class HaltsCambio(BaseModel):
    silencio: bool


class CuadroCambio(BaseModel):
    """Solo los campos PRESENTES se cambian; `riesgo_usd`/`ev_pct` a null se escriben como null."""
    config_version: Optional[int] = Field(None, description="la versión que se tenía delante; si cambió → 409")
    vigilando: Optional[bool] = None
    estrategias: list[EstrategiaCambio] = []
    locates: Optional[LocatesCambio] = None
    halts: Optional[HaltsCambio] = None


def _validar_en_temporal(obj: dict) -> cfgmod.Config:
    """Escribe `obj` firmado en un temporal y lo carga con `config.cargar` (ConfigInvalida si no carga)."""
    with tempfile.TemporaryDirectory(prefix="bot_das_panel_") as d:
        tmp = Path(d) / cfgmod.NOMBRE_FICHERO_CONFIG
        cfgmod.escribir_atomico(tmp, obj)
        return cfgmod.cargar(tmp, _cuenta())


def _refirmar(obj: dict, generado_por: str, version_base: Any) -> dict:
    obj = dict(obj)
    obj["config_version"] = (version_base + 1) if isinstance(version_base, int) and version_base >= 0 else 1
    obj["generado_at"] = datetime.now(ET).isoformat(timespec="seconds")
    obj["generado_por"] = generado_por
    if isinstance(obj.get("estrategias"), list):
        obj["estrategias_hash"] = "sha256:" + cfgmod.hash_canonico(obj["estrategias"])
    obj.pop("sha256", None)
    obj["sha256"] = cfgmod.hash_canonico(obj)
    return obj


def _anotar_cambio(user_id: Optional[str], accion: str, cambios: list, version: Any) -> None:
    quien = user_id or "local"
    logger.info("[BOT_DAS_PANEL] %s por %s → config_version %s: %s", accion, quien, version, cambios)
    try:
        ruta = _dir_bot() / "logs" / NOMBRE_LOG_CAMBIOS
        ruta.parent.mkdir(parents=True, exist_ok=True)
        with open(ruta, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"t": datetime.now(ET).isoformat(timespec="seconds"), "quien": quien,
                                 "accion": accion, "config_version": version, "cambios": cambios},
                                ensure_ascii=False, default=str) + "\n")
    except OSError as exc:   # el registro es informativo: el cambio ya está escrito
        logger.warning("[BOT_DAS_PANEL] no se pudo anotar el cambio: %s", exc)


def _mensaje_bloqueo(rutas: list[str]) -> str:
    return (f"No se puede cambiar {', '.join(rutas)} con el bot encendido: apaga el bot (interruptor) y espera "
            f"a que no haya posiciones; el bot ignoraría el cambio.")


def _cargar_actual(ruta: Path) -> tuple[dict, cfgmod.Config]:
    if not ruta.exists():
        raise HTTPException(status_code=404, detail=f"No existe el cuadro {ruta}: expórtalo primero.")
    try:
        return _leer_crudo(ruta), cfgmod.cargar(ruta, _cuenta())
    except cfgmod.ConfigInvalida as exc:
        raise HTTPException(status_code=422, detail="El cuadro actual no carga (" + "; ".join(exc.errores[:5])
                            + "): vuelve a exportarlo.") from exc
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"No se puede leer el cuadro actual: {exc}") from exc


@router.put("/cuadro")
def cambiar_cuadro(req: CuadroCambio, user_id: Optional[str] = Depends(get_current_user_id)):
    _guard()
    ruta = _ruta_cuadro()
    with _cerrojo_escritura:
        crudo, cfg_actual = _cargar_actual(ruta)
        if req.config_version is not None and req.config_version != crudo.get("config_version"):
            raise HTTPException(status_code=409, detail=(
                f"El cuadro ha cambiado (versión {crudo.get('config_version')}, tenías la {req.config_version}): "
                f"recarga la página y repite el cambio."))
        nuevo = copy.deepcopy(crudo)
        if "vigilando" in req.model_fields_set and req.vigilando is not None:
            nuevo["vigilando"] = req.vigilando
        if req.locates is not None:
            nuevo.setdefault("locates", {})["tope_gasto_dia_usd"] = req.locates.tope_gasto_dia_usd
        if req.halts is not None:
            nuevo.setdefault("halts", {})["silencio"] = req.halts.silencio
        por_id = {e.get("strategy_id"): e for e in nuevo.get("estrategias") or [] if isinstance(e, dict)}
        for cambio in req.estrategias:
            e = por_id.get(cambio.strategy_id)
            if e is None:
                raise HTTPException(status_code=422, detail=f"La estrategia {cambio.strategy_id} no está en el cuadro.")
            for campo in ("ejecutar", "riesgo_usd", "ev_pct"):
                if campo in cambio.model_fields_set:
                    if campo == "ejecutar" and cambio.ejecutar is None:
                        continue
                    e[campo] = getattr(cambio, campo)
        obj = _refirmar(nuevo, f"panel:{user_id or 'local'}", crudo.get("config_version"))
        try:
            cfg_nueva = _validar_en_temporal(obj)
        except cfgmod.ConfigInvalida as exc:
            raise HTTPException(status_code=422, detail={"mensaje": "El cuadro no cargaría; no se ha escrito nada.",
                                                         "errores": exc.errores}) from exc
        difs = cfgmod.diferencias(cfg_actual, cfg_nueva)
        if not difs:
            return {"ok": True, "cambios": [], "config_version": crudo.get("config_version"), "escrito": False}
        no_calientes = [r for r, _, _, caliente in difs if not caliente]
        foto, _ = _leer_foto(time.time())
        if no_calientes and _estado_bot(time.time(), crudo, foto)["bloquea_no_calientes"]:
            raise HTTPException(status_code=409, detail=_mensaje_bloqueo(no_calientes))
        cfgmod.escribir_atomico(ruta, obj)
        cambios = [{"ruta": r, "antes": a, "despues": b} for r, a, b, _ in difs]
        _anotar_cambio(user_id, "cambiar", cambios, obj["config_version"])
        return {"ok": True, "cambios": cambios, "config_version": obj["config_version"], "escrito": True}


# Lo que se toca desde la pestaña y una exportación no debe pisar.
_HOJAS_PANEL_GLOBALES = (("vigilando",), ("locates", "tope_gasto_dia_usd"), ("halts", "silencio"))
_CAMPOS_PANEL_ESTRATEGIA = ("riesgo_usd", "ev_pct")


def _conservar_panel(exportado: dict, previo: Optional[dict]) -> dict:
    """Pone sobre lo exportado lo que se decide en la pestaña (estrategias que ya estaban y hojas globales)."""
    if not previo:
        return exportado
    salida = copy.deepcopy(exportado)
    for ruta in _HOJAS_PANEL_GLOBALES:
        origen: Any = previo
        for k in ruta:
            origen = origen.get(k) if isinstance(origen, dict) else None
        if origen is None:
            continue
        destino = salida
        for k in ruta[:-1]:
            destino = destino.setdefault(k, {})
        destino[ruta[-1]] = copy.deepcopy(origen)
    previas = {e.get("strategy_id"): e for e in previo.get("estrategias") or [] if isinstance(e, dict)}
    for e in salida.get("estrategias") or []:
        p = previas.get(e.get("strategy_id"))
        if p is None:
            continue
        for campo in _CAMPOS_PANEL_ESTRATEGIA:
            if campo in p:
                e[campo] = p[campo]
        # Decisiones 20/22/23: conserva `ejecutar`, pero sin EV o con pirámide de repeticiones no ejecuta
        e["ejecutar"] = (p.get("ejecutar") is True and e.get("ev_pct") is not None
                         and "motivo_no_ejecuta" not in e)
    return salida


@router.post("/exportar")
def exportar(user_id: Optional[str] = Depends(get_current_user_id)):
    _guard()
    ruta = _ruta_cuadro()
    url = os.environ.get("BOT_ALERTS_API") or cfgmod.URL_BACKEND_POR_DEFECTO
    defaults = Path(cfgmod.__file__).resolve().parents[2] / "tests" / "bot_das" / "fixtures" / "config_ejemplo.json"
    with _cerrojo_escritura:
        previo: Optional[dict] = None
        cfg_actual: Optional[cfgmod.Config] = None
        if ruta.exists():
            try:
                previo = _leer_crudo(ruta)
                cfg_actual = cfgmod.cargar(ruta, _cuenta())
            except (cfgmod.ConfigInvalida, OSError, ValueError):
                cfg_actual = None
        with tempfile.TemporaryDirectory(prefix="bot_das_exportar_") as d:
            tmp = Path(d) / cfgmod.NOMBRE_FICHERO_CONFIG
            if previo is not None:
                tmp.write_text(json.dumps(previo, ensure_ascii=False), encoding="utf-8")
            try:
                cfg = cfgmod.exportar_desde_backend(url, tmp, defaults, produccion=cfgmod.RUTA_CUADRO_PRODUCCION,
                                                    generado_por=f"panel:{user_id or 'local'}")
            except cfgmod.ConfigInvalida as exc:
                raise HTTPException(status_code=422, detail={"mensaje": "La exportación no valida; no se ha escrito nada.",
                                                             "errores": exc.errores}) from exc
            if cfg is None:
                raise HTTPException(status_code=502, detail="No se pudo leer /bot-alerts/vigiladas; no se ha escrito nada.")
            exportado = _leer_crudo(tmp)
        obj = _conservar_panel(exportado, previo)
        obj = _refirmar(obj, f"panel:{user_id or 'local'}", (previo or {}).get("config_version"))
        try:
            cfg_nueva = _validar_en_temporal(obj)
        except cfgmod.ConfigInvalida as exc:
            raise HTTPException(status_code=422, detail={"mensaje": "La exportación no valida; no se ha escrito nada.",
                                                         "errores": exc.errores}) from exc
        difs = cfgmod.diferencias(cfg_actual, cfg_nueva) if cfg_actual is not None else []
        no_calientes = [r for r, _, _, caliente in difs if not caliente]
        foto, _ = _leer_foto(time.time())
        if no_calientes and _estado_bot(time.time(), previo, foto)["bloquea_no_calientes"]:
            raise HTTPException(status_code=409, detail=_mensaje_bloqueo(no_calientes))
        cfgmod.escribir_atomico(ruta, obj)
        avisos = [a for e in cfg_nueva.estrategias.values() for a in cfgmod.comprobar_coherencia(e)]
        resumen = {
            "ok": True, "config_version": obj["config_version"], "estrategias": len(cfg_nueva.estrategias),
            "ejecutan": sum(1 for e in cfg_nueva.estrategias.values() if e.ejecutar),
            "nuevas": sorted(set(cfg_nueva.estrategias) - set(cfg_actual.estrategias if cfg_actual else {})),
            "quitadas": sorted(set(cfg_actual.estrategias if cfg_actual else {}) - set(cfg_nueva.estrategias)),
            "cambios": [r for r, _, _, _ in difs], "avisos": avisos,
        }
        _anotar_cambio(user_id, "exportar", resumen["cambios"] if cfg_actual is not None else ["(primer cuadro)"],
                       obj["config_version"])
        return resumen
