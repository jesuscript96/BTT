"""Apagado limpio del entorno local desde la interfaz (solo en local).

    GET  /api/local-control/status    -> {"disponible": bool}
    POST /api/local-control/shutdown  -> lanza el apagado y responde

Gated por LOCAL_SHUTDOWN_ENABLED (default OFF) + LOCAL_SHUTDOWN_SCRIPT. En
produccion no existe ninguna de las dos: el status devuelve disponible=false
—con lo que el boton ni se pinta— y el POST responde 503 sin hacer nada.
Mismo patron que lake_update.py.

Dos detalles que no son opcionales:

* El script arranca con una espera inicial. Uno de los procesos que va a matar
  es este mismo, y la respuesta HTTP tiene que salir antes.
* Se lanza con CREATE_NO_WINDOW, NO con DETACHED_PROCESS. Medido el 2026-08-24:
  con DETACHED_PROCESS, powershell.exe se queda sin consola, **sale con codigo 0
  sin ejecutar una sola linea del script** y no hay ningun error en ninguna
  parte. Parecia que el apagado fallaba; en realidad nunca llego a empezar.
  CREATE_NO_WINDOW le da una consola oculta y funciona.

El script no muere con el backend: en Windows un hijo sobrevive a su padre, y
el propio script se excluye de la lista de procesos que mata.
"""
from __future__ import annotations

import os
import subprocess

from fastapi import APIRouter, HTTPException

router = APIRouter()

# Segundos que espera el script antes de empezar a matar procesos: lo justo
# para que salga la respuesta y el navegador pinte el aviso de "apagando".
ESPERA_INICIAL_SEG = 3


# Se lee EN CADA PETICION, no al importar: el import de este modulo puede
# ocurrir antes de que load_dotenv() haya poblado el entorno.
def _cfg() -> tuple[bool, str]:
    enabled = os.getenv("LOCAL_SHUTDOWN_ENABLED", "false").strip().lower() in ("1", "true", "yes", "on")
    return enabled, os.getenv("LOCAL_SHUTDOWN_SCRIPT", "").strip()


@router.get("/status")
def estado():
    """Le dice a la UI si debe pintar el boton de apagado. Nunca falla."""
    enabled, script = _cfg()
    return {"disponible": bool(enabled and script and os.path.exists(script))}


@router.post("/shutdown")
def apagar():
    enabled, script = _cfg()
    if not enabled:
        raise HTTPException(
            status_code=503,
            detail={"code": "local_shutdown_disabled",
                    "message": "El apagado solo esta disponible en local."},
        )
    if not script or not os.path.exists(script):
        raise HTTPException(
            status_code=500,
            detail={"code": "local_shutdown_script_missing",
                    "message": f"No se encuentra el script de apagado: {script or '(sin configurar)'}"},
        )

    flags = 0
    if os.name == "nt":
        # CREATE_NO_WINDOW, no DETACHED_PROCESS. Ver la cabecera del modulo.
        flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]

    # Sin capturar la salida: el script escribe su propio apagar_btt.log, que es
    # lo unico que queda para diagnosticar cuando el apagado sale mal (aqui no
    # hay ventana donde mirar, y este proceso es una de las victimas).
    subprocess.Popen(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
         "-File", script, "-EsperaInicialSeg", str(ESPERA_INICIAL_SEG)],
        creationflags=flags,
        close_fds=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return {"ok": True, "espera_seg": ESPERA_INICIAL_SEG,
            "mensaje": "Apagando el backend y el frontend..."}
