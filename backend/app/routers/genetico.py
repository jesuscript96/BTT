"""Genetico: lanzar y seguir corridas del algoritmo genetico (proceso aparte).

ADITIVO y APAGADO por defecto (env GENETICO_ENABLED, solo en el .env local).
El backend NO corre el genetico: prepara el directorio de la corrida (config +
pares del dataset, que salen de users.duckdb con el cerrojo del backend, para
que el proceso externo no abra la base nunca) y lanza `python -m
genetico.corrida` con el venv, desacoplado del --reload (sobrevive a los
reinicios del backend). Despues solo lee los JSON que el proceso deja en disco:
nada de DuckDB en el sondeo de progreso (ver MEMORIA: «no hay lecturas
baratas»).

El paquete vive en `<repo>/genetico/`, FUERA de `backend/`, a proposito.
"""
from __future__ import annotations

import glob
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.database import get_user_db_connection, get_user_db_lock

router = APIRouter(prefix="/api/genetico", tags=["Genetico"])

RAIZ_REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
BACKEND = os.path.join(RAIZ_REPO, "backend")
DIR_TRABAJO = os.getenv("BTT_GENETICO_DIR", "D:/tmp/btt_genetico")
DIR_CORRIDAS = os.path.join(DIR_TRABAJO, "corridas")
DIR_DATOS = os.path.join(DIR_TRABAJO, "datos")
# Mismo patron que LAKE_UPDATE_PYTHON: el interprete se elige por env y, si
# no, el venv del backend (sys.executable en el worker del --reload es el
# Python base, sin los paquetes).
PYTHON = os.getenv("GENETICO_PYTHON") or os.path.join(BACKEND, ".venv", "Scripts", "python.exe")

FITNESS = [
    {"id": "expR_sqrtN", "label": "R media × √operaciones (recomendado)"},
    {"id": "avg_r", "label": "R media por operación"},
    {"id": "pf", "label": "Profit factor"},
    {"id": "dd_return", "label": "Retorno / drawdown"},
    {"id": "sharpe", "label": "Sharpe"},
]


def _catalogo_modulo():
    if RAIZ_REPO not in sys.path:
        sys.path.insert(0, RAIZ_REPO)
    from genetico import catalogo  # solo datos; no arranca el entorno del motor
    return catalogo


# ── Catalogo (lo que la pagina deja elegir) ─────────────────────────────────

@router.get("/catalogo")
def catalogo():
    C = _catalogo_modulo()
    return {
        "indicadores": [
            {"nombre": i.nombre, "familia": i.familia, "ayuda": i.ayuda,
             "por_defecto": i.por_defecto,
             "params": i.params, "valores": list(i.valores),
             "objetivos": list(i.objetivos), "comparadores": list(i.comparadores)}
            for i in C.CATALOGO.values()
        ],
        # Las familias, en el orden en que se pintan las pestanyas. Con dos
        # docenas de indicadores una lista plana de casillas no se puede leer.
        "familias": [{"clave": c, "etiqueta": e} for c, e in C.FAMILIAS],
        # Guardas fijas: van delante de todas las condiciones y NO las busca el
        # genetico, las fija Jaume.
        "guardas": [{"clave": k, "indicador": n, "etiqueta": e, "comparador": c,
                     "ayuda": a} for k, n, e, c, a in C.GUARDAS],
        "stops": {"pct": list(C.STOP_PCT), "offset_pct": list(C.STOP_OFFSET_PCT),
                  "niveles": {k: [n for n, _ in v] for k, v in C.STOP_NIVELES.items()}},
        "tps": {"pct": list(C.TP_PCT), "hora": list(C.TP_HORA),
                "tiempo": list(C.TP_TIEMPO_MIN),
                "parcial_cierre": list(C.TP_PARCIAL_CIERRE_PCT),
                "parcial_max": C.TP_PARCIAL_MAX_NIVELES},
        "fitness": FITNESS,
        "python": PYTHON,
        "python_ok": os.path.exists(PYTHON),
        "dir_trabajo": DIR_TRABAJO,
    }


# ── Corridas ────────────────────────────────────────────────────────────────

class NuevaCorrida(BaseModel):
    nombre: Optional[str] = None
    config: dict


def _dir(corrida_id: str) -> str:
    if not corrida_id or "/" in corrida_id or "\\" in corrida_id or ".." in corrida_id:
        raise HTTPException(400, "id de corrida invalido")
    d = os.path.join(DIR_CORRIDAS, corrida_id)
    if not os.path.isdir(d):
        raise HTTPException(404, "corrida no encontrada")
    return d


def _json(ruta: str, defecto: Any = None) -> Any:
    try:
        with open(ruta, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return defecto


def _cola_log(ruta: str, n: int = 40) -> list[str]:
    try:
        with open(ruta, encoding="utf-8", errors="replace") as f:
            return [l.rstrip("\n") for l in f.readlines()[-n:]]
    except OSError:
        return []


def _vivo(d: str) -> bool:
    p = _json(os.path.join(d, "proceso.json"), {})
    pid = int(p.get("pid") or 0)
    if not pid:
        return False
    try:
        import psutil
        return psutil.pid_exists(pid) and "python" in (psutil.Process(pid).name() or "").lower()
    except Exception:
        return False


def _escribir_pares(dataset_id: str, dir_datos: str) -> int:
    """Los pares del dataset, leidos por el backend (que es quien tiene
    users.duckdb) y dejados en parquet para el proceso externo."""
    import pandas as pd
    os.makedirs(dir_datos, exist_ok=True)
    ruta = os.path.join(dir_datos, "pairs.parquet")
    if os.path.exists(ruta):
        return len(pd.read_parquet(ruta))
    with get_user_db_lock():
        con = get_user_db_connection()
        try:
            df = con.execute(
                "SELECT ticker, CAST(date AS VARCHAR) AS date FROM dataset_pairs "
                "WHERE dataset_id = ? ORDER BY date, ticker", [dataset_id],
            ).fetchdf()
        finally:
            con.close()
    if df.empty:
        raise HTTPException(400, "El dataset no tiene ticker-dias")
    tmp = ruta + ".tmp"
    df.to_parquet(tmp, index=False)
    os.replace(tmp, ruta)
    return len(df)


def _escribir_qualifying(cfg: dict, dir_datos: str) -> int:
    """El qualifying EXACTO del panel: misma funcion, mismos argumentos que el
    orquestador del backtest (fetch_qualifying_data con las fechas pedidas,
    sin precondiciones, gap_day). Medido el 2026-09-02: construirlo fuera con
    dataset_pairs dejaba fuera 62 ticker-dias anteriores al rango del dataset
    y los numeros no cuadraban con el panel. Se reescribe en cada corrida (es
    barato con el parquet materializado) y el proceso externo lo usa tal cual."""
    from app.services.data_service import fetch_qualifying_data
    import pandas as pd
    os.makedirs(dir_datos, exist_ok=True)
    q = fetch_qualifying_data(cfg["dataset_id"], cfg.get("fecha_ini"), cfg.get("fecha_fin"),
                              preconditions=[], apply_day="gap_day")
    if q is None or q.empty:
        raise HTTPException(400, "El dataset no tiene ticker-dias en ese periodo")
    q = q.copy()
    q["date"] = pd.to_datetime(q["date"]).dt.strftime("%Y-%m-%d")
    q = q.sort_values(["date", "ticker"]).reset_index(drop=True)
    tmp = os.path.join(dir_datos, "qualifying.feather.tmp")
    q.to_feather(tmp)
    os.replace(tmp, os.path.join(dir_datos, "qualifying.feather"))
    return len(q)


def _lanzar(d: str, reanudar: bool = False) -> int:
    if not os.path.exists(PYTHON):
        raise HTTPException(500, f"No encuentro el Python del genetico: {PYTHON}")
    cmd = [PYTHON, "-u", "-m", "genetico.corrida", "--dir", d]
    if reanudar:
        cmd.append("--reanudar")
    salida = open(os.path.join(d, "salida.txt"), "ab")
    flags = 0
    if os.name == "nt":
        # CREATE_NO_WINDOW y grupo propio: no abre consola y NO muere cuando el
        # --reload reinicia el backend. (Nunca DETACHED_PROCESS: ver MEMORIA.)
        flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
    proc = subprocess.Popen(
        cmd, cwd=RAIZ_REPO, stdout=salida, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
        env={**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8",
             "BTT_GENETICO_DIR": DIR_TRABAJO},
        creationflags=flags,
    )
    with open(os.path.join(d, "proceso.json"), "w", encoding="utf-8") as f:
        json.dump({"pid": proc.pid, "lanzado": time.time(), "reanudar": reanudar}, f)
    return proc.pid


@router.post("/corridas")
def crear_corrida(req: NuevaCorrida):
    cfg = dict(req.config or {})
    if not cfg.get("dataset_id"):
        raise HTTPException(400, "Falta el dataset")
    if not cfg.get("catalogo"):
        raise HTTPException(400, "Marca al menos un indicador")
    if int(cfg.get("n_condiciones", 2)) not in (1, 2, 3):
        raise HTTPException(400, "Condiciones: 1, 2 o 3")
    try:
        import psutil
        libre = psutil.virtual_memory().available / 1e9
    except Exception:
        libre = 99.0
    if libre < 2.0:
        raise HTTPException(503, f"Solo quedan {libre:.1f} GB libres; cierra cosas antes de lanzar")

    corrida_id = time.strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:4]
    d = os.path.join(DIR_CORRIDAS, corrida_id)
    os.makedirs(d, exist_ok=True)
    dir_datos = os.path.join(DIR_DATOS, f"{cfg['dataset_id']}_{cfg.get('fecha_ini')}_{cfg.get('fecha_fin')}")
    cfg["dir_datos"] = dir_datos
    cfg["nombre"] = req.nombre or corrida_id
    n_pares = _escribir_qualifying(cfg, dir_datos)
    with open(os.path.join(d, "config.json"), "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=1, ensure_ascii=False)
    pid = _lanzar(d)
    return {"id": corrida_id, "pid": pid, "pares_dataset": n_pares}


@router.get("/corridas")
def listar_corridas():
    filas = []
    dirs = [d for d in glob.glob(os.path.join(DIR_CORRIDAS, "*")) if os.path.isdir(d)]
    # Mas reciente primero, por fecha de creacion (no por nombre: las corridas
    # lanzadas desde la consola llevan nombre libre).
    dirs.sort(key=lambda d: os.path.getmtime(os.path.join(d, "config.json")) if os.path.exists(os.path.join(d, "config.json")) else 0, reverse=True)
    for d in dirs:
        cid = os.path.basename(d)
        cfg = _json(os.path.join(d, "config.json"), {})
        est = _json(os.path.join(d, "estado.json"), {})
        filas.append({
            "id": cid, "nombre": cfg.get("nombre", cid), "dataset_id": cfg.get("dataset_id"),
            "semilla": cfg.get("semilla"), "poblacion": cfg.get("poblacion"),
            "generaciones": cfg.get("generaciones"), "n_condiciones": cfg.get("n_condiciones"),
            "estado": est.get("estado", "preparando"), "generacion": est.get("generacion", 0),
            "evaluadas": est.get("evaluadas", 0), "inicio": est.get("inicio"), "actualizado": est.get("actualizado"),
            "mejor": est.get("mejor"), "vivo": _vivo(d),
        })
    return filas


@router.get("/corridas/{corrida_id}")
def ver_corrida(corrida_id: str):
    d = _dir(corrida_id)
    cfg = _json(os.path.join(d, "config.json"), {})
    est = _json(os.path.join(d, "estado.json"), {})
    mejores = _json(os.path.join(d, "mejores.json"), {}).get("mejores", [])
    datos = _json(os.path.join(cfg.get("dir_datos", ""), "datos.json"), None) if cfg.get("dir_datos") else None
    return {
        "id": corrida_id, "config": cfg, "estado": est, "mejores": mejores, "datos": datos,
        "vivo": _vivo(d), "parada_pedida": os.path.exists(os.path.join(d, "parar.txt")),
        "log": _cola_log(os.path.join(d, "log.txt")),
        "salida": _cola_log(os.path.join(d, "salida.txt"), 15),
    }


@router.post("/corridas/{corrida_id}/parar")
def parar_corrida(corrida_id: str):
    d = _dir(corrida_id)
    open(os.path.join(d, "parar.txt"), "w").close()
    return {"ok": True, "mensaje": "Se para al terminar la evaluacion en curso"}


@router.post("/corridas/{corrida_id}/reanudar")
def reanudar_corrida(corrida_id: str):
    d = _dir(corrida_id)
    if _vivo(d):
        raise HTTPException(409, "La corrida sigue en marcha")
    try:
        os.remove(os.path.join(d, "parar.txt"))
    except OSError:
        pass
    return {"ok": True, "pid": _lanzar(d, reanudar=True)}


@router.delete("/corridas/{corrida_id}")
def borrar_corrida(corrida_id: str):
    d = _dir(corrida_id)
    if _vivo(d):
        raise HTTPException(409, "Para la corrida antes de borrarla")
    shutil.rmtree(d, ignore_errors=True)
    return {"ok": True}
