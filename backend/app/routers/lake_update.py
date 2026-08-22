"""Actualizacion del lago local desde la interfaz (solo entorno local).

Expone tres endpoints para que la UI pueda disparar y seguir la actualizacion
del lago sin bloquearse:

    POST /api/lake/update    -> arranca (o devuelve el que ya corre)
    GET  /api/lake/status    -> progreso, para pintar "actualizando..."
    GET  /api/lake/log       -> ultimas lineas, para diagnosticar

Se ejecuta `actualizar_diario.py` del proyecto del lago en un subproceso, en
un hilo aparte, y se sigue su salida. Gated por LAKE_UPDATE_ENABLED: en
produccion no existe el lago local, asi que por defecto esta APAGADO y el
endpoint responde 503 sin hacer nada.

EL SCRIPT NO ES TODO EL TRABAJO. Deja al dia el lago Parquet, pero un dia
nuevo no es backtesteable hasta que ademas esta en las tablas de
local_data.duckdb y dentro de la ventana de fechas del dataset. Esas dos capas
las cierra este mismo hilo al terminar el subproceso, con
`services/lake_db_loader.py` — ahi esta el porque de cada una. Antes eran
manuales y su ausencia no daba ningun error: el lago avanzaba y los backtests
seguian leyendo datos viejos en silencio (incidente del 2026-08-21).
"""
from __future__ import annotations

import os
import subprocess
import threading
import time
from collections import deque
from datetime import datetime

from fastapi import APIRouter, HTTPException

router = APIRouter()

# Se leen EN CADA PETICION, no al importar: el import de este modulo puede
# ocurrir antes de que load_dotenv() haya poblado el entorno, y entonces
# quedarian congeladas a vacio.
def _cfg() -> tuple[bool, str, str]:
    enabled = os.getenv("LAKE_UPDATE_ENABLED", "false").strip().lower() in ("1", "true", "yes", "on")
    return enabled, os.getenv("LAKE_UPDATE_SCRIPT", "").strip(), os.getenv("LAKE_UPDATE_PYTHON", "").strip()

# Estado en memoria del proceso. Un unico update a la vez: dos a la vez se
# pelearian por el disco y ninguno avanzaria (leccion aprendida con los
# backtests simultaneos).
_estado: dict = {
    "status": "idle",        # idle | running | done | error
    "fase": "",
    "empezado": None,
    "terminado": None,
    "error": None,
    "resumen": None,         # texto corto para la UI cuando termina bien
}
_log: deque = deque(maxlen=400)
_lock = threading.Lock()

# Marcas que imprime actualizar_diario.py para que este lado sepa que cerrar,
# sin tener que adivinarlo releyendo el lago. Ver el script.
MARCA_MESES = "[LAKE-MESES]"
MARCA_MAX_ANTERIOR = "[LAKE-MAX-ANTERIOR]"


def _apunta(texto: str) -> None:
    _log.append(texto)


def _parsea_meses(valor: str) -> list[tuple[int, int]]:
    """'2026-08,2026-09' -> [(2026, 8), (2026, 9)]. Lo ilegible se descarta."""
    meses = []
    for trozo in valor.replace(" ", "").split(","):
        if not trozo:
            continue
        try:
            y, m = trozo.split("-")
            meses.append((int(y), int(m)))
        except ValueError:
            continue
    return sorted(set(meses))


def _cerrar_actualizacion(meses: list[tuple[int, int]], max_anterior: str | None) -> str:
    """Capas 4 y 5: Parquet -> tablas de DuckDB, y ventana de los datasets.

    Corre en el hilo de la actualizacion, nunca en el de una peticion. Ningun
    fallo de aqui se propaga: la descarga ya esta hecha y hay que dejar
    constancia de que falto, no perderla.
    """
    from app.services import lake_db_loader as L

    if not meses:
        # Sin delta que descargar tampoco esta de mas mirar: asi se repara solo
        # un desfase Parquet-vs-tabla que hubiera quedado de una vez anterior.
        meses = L.meses_por_defecto()

    with _lock:
        _estado["fase"] = "Cargando en la base de datos"
    carga = L.cargar_meses_en_duckdb(meses, _apunta)

    max_nuevo = L.max_fecha_en_tabla()
    partes = []
    if carga.get("error"):
        partes.append(f"carga incompleta: {carga['error']}")
    elif carga["cargados"]:
        partes.append(f"{carga['filas']:,} filas nuevas en la base")
    else:
        partes.append("la base ya estaba al dia")

    if max_nuevo:
        with _lock:
            _estado["fase"] = "Ampliando los datasets"
        ext = L.extender_datasets(max_anterior, max_nuevo, _apunta)
        if ext["extendidos"]:
            partes.append(f"{len(ext['extendidos'])} datasets hasta {max_nuevo}")
        if ext["rezagados"]:
            partes.append(f"{len(ext['rezagados'])} con ventana propia, sin tocar")

    with _lock:
        _estado["fase"] = "Añadiendo los dias nuevos a la copia rapida"
    # No se le pasa el delta descargado a proposito: la funcion compara cada
    # fichero de la copia rapida contra el lago, asi que pulsar el boton repara
    # lo que falte haya habido descarga o no. Si todo esta al dia, no toca nada.
    cache = L.anadir_dias_al_cache(meses, _apunta)
    if cache["ficheros"]:
        partes.append(f"{cache['velas']:,} velas añadidas a la copia rapida")

    L.invalidar_caches_qualifying(_apunta)

    resumen = (f"Datos hasta {max_nuevo}. " if max_nuevo else "") + "; ".join(partes)
    _apunta(f"[FIN] {resumen}")
    return resumen


def _corre(cmd: list[str], cwd: str) -> None:
    """Ejecuta el script y va volcando su salida a _log y _estado['fase']."""
    meses: list[tuple[int, int]] = []
    max_anterior: str | None = None
    try:
        proc = subprocess.Popen(
            cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1, encoding="utf-8", errors="replace",
            # PYTHONIOENCODING es OBLIGATORIO, no cosmetico: con la salida por
            # una tuberia, Python usa la codificacion local (cp1252 aqui) y
            # cualquier caracter fuera de ella aborta el script con
            # UnicodeEncodeError. El 2026-08-20 un emoji en un aviso final tumbo
            # una actualizacion que ya habia hecho todo el trabajo.
            env={**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"},
        )
        for linea in proc.stdout:  # type: ignore[union-attr]
            linea = linea.rstrip("\n")
            if not linea:
                continue
            _log.append(linea)
            if linea.startswith(MARCA_MESES):
                meses = _parsea_meses(linea[len(MARCA_MESES):])
                continue
            if linea.startswith(MARCA_MAX_ANTERIOR):
                valor = linea[len(MARCA_MAX_ANTERIOR):].strip()
                max_anterior = valor if valor and valor != "-" else None
                continue
            # Las cabeceras de fase del script van en MAYUSCULAS con guiones
            if "FASE" in linea or "ACTUALIZACION" in linea or "---" in linea:
                with _lock:
                    _estado["fase"] = linea.strip("- ").strip()[:120]
        rc = proc.wait()

        resumen = None
        if rc == 0:
            # El script solo ha dejado el Parquet al dia. Lo que hace que un dia
            # nuevo llegue de verdad al backtest es esto de aqui.
            try:
                resumen = _cerrar_actualizacion(meses, max_anterior)
            except Exception as e:
                _log.append(f"[FIN] no se pudo cerrar la actualizacion: {type(e).__name__}: {e}")
                resumen = "descarga OK, pero fallo el cierre (ver el log)"

        with _lock:
            _estado["status"] = "done" if rc == 0 else "error"
            _estado["error"] = None if rc == 0 else f"el script termino con codigo {rc}"
            _estado["terminado"] = datetime.now().isoformat(timespec="seconds")
            _estado["resumen"] = resumen
            if rc == 0:
                _estado["fase"] = "Completado"
    except Exception as e:
        _log.append(f"[ERROR] {type(e).__name__}: {e}")
        with _lock:
            _estado["status"] = "error"
            _estado["error"] = f"{type(e).__name__}: {e}"
            _estado["terminado"] = datetime.now().isoformat(timespec="seconds")


@router.post("/lake/update")
def lanzar_actualizacion():
    ENABLED, SCRIPT, PYTHON = _cfg()
    if not ENABLED:
        raise HTTPException(
            status_code=503,
            detail={"code": "lake_update_disabled",
                    "message": "La actualizacion del lago solo esta disponible en local."},
        )
    if not SCRIPT or not os.path.exists(SCRIPT):
        raise HTTPException(
            status_code=503,
            detail={"code": "lake_update_misconfigured",
                    "message": f"LAKE_UPDATE_SCRIPT no apunta a un fichero valido: {SCRIPT!r}"},
        )

    with _lock:
        if _estado["status"] == "running":
            return {"status": "running", "fase": _estado["fase"], "ya_estaba": True}
        _estado.update({"status": "running", "fase": "Arrancando...", "error": None,
                        "empezado": datetime.now().isoformat(timespec="seconds"),
                        "terminado": None, "resumen": None})
    _log.clear()
    _log.append(f"[{datetime.now():%H:%M:%S}] lanzando {SCRIPT}")

    python = PYTHON or "python"
    # --fase7-externa: la carga en local_data.duckdb la hace este backend al
    # terminar (_cerrar_actualizacion), no el script. Sin el flag, el script
    # cierra con un aviso a pantalla completa de que falta ese paso — cierto
    # cuando se lanza a mano, falso y alarmante cuando se lanza desde aqui.
    threading.Thread(
        target=_corre,
        args=([python, "-u", SCRIPT, "--fase7-externa"], os.path.dirname(SCRIPT)),
        daemon=True,
    ).start()
    return {"status": "running", "fase": "Arrancando...", "ya_estaba": False}


@router.get("/lake/status")
def estado_actualizacion():
    ENABLED, SCRIPT, _ = _cfg()
    with _lock:
        e = dict(_estado)
    e["disponible"] = ENABLED and bool(SCRIPT) and os.path.exists(SCRIPT)
    e["ultima_linea"] = _log[-1] if _log else ""
    return e


@router.get("/lake/log")
def log_actualizacion(lineas: int = 80):
    return {"lineas": list(_log)[-max(1, min(lineas, 400)):]}


@router.post("/lake/extend-datasets")
def extender_datasets_rezagados(solo: str | None = None):
    """Pone al dia la ventana de fechas de TODOS los datasets que se hayan
    quedado cortos, hasta el ultimo dia que hay en la base.

    La actualizacion automatica solo estira los que iban al dia, para no tocar
    una ventana elegida a proposito. Esto es lo contrario: una accion explicita
    para recuperar los datasets que se congelaron en la fecha en que se
    crearon, de cuando ese estiron no existia. Cambia el universo de esos
    datasets, asi que se pide a mano y nunca pasa sola.

    `?solo=<dataset_id>` la limita a un dataset.

    Sincrono: no descarga nada, solo recalcula pares sobre datos que ya estan.
    """
    ENABLED, _, _ = _cfg()
    if not ENABLED:
        raise HTTPException(
            status_code=503,
            detail={"code": "lake_update_disabled",
                    "message": "Solo disponible en local."},
        )
    with _lock:
        if _estado["status"] == "running":
            raise HTTPException(
                status_code=409,
                detail={"code": "lake_update_running",
                        "message": "Hay una actualizacion en curso; espera a que termine."},
            )

    from app.services import lake_db_loader as L
    max_nuevo = L.max_fecha_en_tabla()
    if not max_nuevo:
        raise HTTPException(
            status_code=503,
            detail={"code": "sin_datos", "message": "daily_metrics esta vacia."},
        )
    ext = L.extender_datasets(None, max_nuevo, _apunta, todos=True, solo=solo)
    L.invalidar_caches_qualifying(_apunta)
    return {"hasta": max_nuevo, **ext}
