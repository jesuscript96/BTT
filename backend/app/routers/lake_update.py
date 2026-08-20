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
}
_log: deque = deque(maxlen=400)
_lock = threading.Lock()


def _corre(cmd: list[str], cwd: str) -> None:
    """Ejecuta el script y va volcando su salida a _log y _estado['fase']."""
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
            # Las cabeceras de fase del script van en MAYUSCULAS con guiones
            if "FASE" in linea or "ACTUALIZACION" in linea or "---" in linea:
                with _lock:
                    _estado["fase"] = linea.strip("- ").strip()[:120]
        rc = proc.wait()
        with _lock:
            _estado["status"] = "done" if rc == 0 else "error"
            _estado["error"] = None if rc == 0 else f"el script termino con codigo {rc}"
            _estado["terminado"] = datetime.now().isoformat(timespec="seconds")
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
                        "terminado": None})
    _log.clear()
    _log.append(f"[{datetime.now():%H:%M:%S}] lanzando {SCRIPT}")

    python = PYTHON or "python"
    threading.Thread(
        target=_corre, args=([python, "-u", SCRIPT], os.path.dirname(SCRIPT)), daemon=True
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
