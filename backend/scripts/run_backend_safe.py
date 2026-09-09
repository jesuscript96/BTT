r"""Arranque seguro del backend local (BTT) — backend/scripts/run_backend_safe.py

REGLA DE ORO (docs/REGLA_ARRANQUE_BACKEND_LOCAL.md): local_data.duckdb admite
UN solo proceso escritor. Este launcher existe para que nunca haya dos:

  - Arranca uvicorn SIN --reload y con 1 worker. Un --reload suelto deja
    workers spawn_main huerfanos que retienen la base (incidentes 2026-09-05 y
    2026-09-07: bloqueo de la carga de las 09:00 y "INTERNAL Error: Failed to
    load metadata pointer", que aqui significa CONTENCION, no corrupcion).
  - Solo corre con backend/.venv (el python del proyecto). Nota: ese python es
    un trampoline de uv — el proceso REAL (python base del sistema) aparece
    como HIJO con la misma linea de comandos; para parar el backend hay que
    matar el arbol completo: taskkill /PID <pid> /T /F.
  - Antes de arrancar comprueba, en este orden:
      1. Flags de seguridad local (DISABLE_GCS_SYNC=true y
         LIVE_SCREENER_ENABLED=false — ver AGENTS.md).
      2. Que nadie escuche ya en el puerto 8010 (si hay alguien, dice quien es
         y sugiere no tocarlo si es el backend que rearranca la tarea de
         cangrejo_data tras la carga de las 09:00).
      3. Que nadie tenga abierto local_data.duckdb: abre y cierra la base; si
         falla, traduce el error criptico de DuckDB y lista los procesos
         sospechosos con PID.
  - Exporta BTT_REQUIRE_DB=1: si al arrancar la app no puede abrir la base, el
    proceso MUERE en vez de quedar sirviendo sin datos (solo local; prod no
    pasa por aqui).

Uso:
    backend\scripts\arrancar_backend.bat
    backend\.venv\Scripts\python.exe backend\scripts\run_backend_safe.py [flags]

Flags:
    --check-only     ejecuta solo las comprobaciones y sale (no arranca nada)
    --kill-orphans   antes de comprobar, mata arboles huerfanos de python
                     (spawn_main / uvicorn sin padre vivo) que retengan la base
    --port N         puerto (default 8010)
    --host H         host (default 0.0.0.0, igual que la tarea de cangrejo_data)

Codigos de salida: 0 ok, 2 puerto ocupado, 3 DuckDB retenido,
4 interprete equivocado, 5 entorno inseguro.
"""

from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]  # backend/
VENV_DIR = BASE_DIR / ".venv"
DEFAULT_PORT = 8010
DEFAULT_HOST = "0.0.0.0"

EXIT_OK = 0
EXIT_PORT_BUSY = 2
EXIT_DB_BUSY = 3
EXIT_WRONG_PYTHON = 4
EXIT_ENV_UNSAFE = 5

# Marcas de linea de comandos que delatan un proceso relacionado con el
# backend o sus workers.
_MARCAS = ("uvicorn", "spawn_main", "app.main", "run_backend", "backtest")


def _p(msg: str) -> None:
    print(msg, flush=True)


def _trunc(text: str, limit: int = 160) -> str:
    return text if len(text) <= limit else text[: limit - 3] + "..."


# ─────────────────────────── procesos sospechosos ───────────────────────────


def _iter_python_procs() -> list[dict]:
    """Procesos python con cmdline visible, como dicts planos (sin lanzar
    excepciones si un proceso muere a mitad de enumeracion)."""
    import psutil

    out = []
    for p in psutil.process_iter(["pid", "ppid", "name", "exe", "cmdline"]):
        info = p.info
        try:
            name = (info["name"] or "").lower()
        except Exception:
            continue
        if not name.startswith("python"):
            continue
        try:
            cmdline = " ".join(info["cmdline"] or [])
        except Exception:
            cmdline = ""
        out.append(
            {
                "pid": info["pid"],
                "ppid": info["ppid"],
                "exe": info["exe"] or info["name"],
                "cmdline": cmdline,
            }
        )
    return out


def _mi_arbol_pids() -> set[int]:
    """PIDs propios y de mis ancestros: el launcher nunca se lista a si mismo
    como sospechoso (su cmdline contiene 'run_backend')."""
    import psutil

    pids = set()
    try:
        p = psutil.Process(os.getpid())
        for anc in [p, *p.parents()]:
            pids.add(anc.pid)
    except Exception:
        pids.add(os.getpid())
    return pids


def _sospechosos() -> list[dict]:
    """Procesos python cuya cmdline delata backend/workers, excluido yo mismo
    y mis ancestros."""
    propios = _mi_arbol_pids()
    procs = _iter_python_procs()
    sospechosos = [
        p for p in procs
        if p["pid"] not in propios and any(m in p["cmdline"] for m in _MARCAS)
    ]
    # Quien tenga el DuckDB abierto tambien es sospechoso aunque su cmdline
    # no delate nada (psutil puede no ver los handles de otros usuarios).
    db_name = "local_data.duckdb"
    ya_listados = {s["pid"] for s in sospechosos}
    for p in procs:
        if p["pid"] in propios or p["pid"] in ya_listados:
            continue
        try:
            import psutil

            if any(f.path.endswith(db_name) for f in psutil.Process(p["pid"]).open_files()):
                p = dict(p, cmdline=p["cmdline"] or "(cmdline no visible)")
                sospechosos.append(p)
        except Exception:
            pass
    return sospechosos


def _huerfanos(sospechosos: list[dict]) -> list[dict]:
    vivos = {p["pid"] for p in _iter_python_procs()}
    return [p for p in sospechosos if p["ppid"] not in vivos and p["ppid"] != 0]


def _fmt(p: dict) -> str:
    return f"  PID {p['pid']} (padre {p['ppid']}) [{_trunc(p['exe'], 60)}] {_trunc(p['cmdline'])}"


def _matar_arbol(pid: int) -> None:
    import psutil

    try:
        proc = psutil.Process(pid)
        hijos = proc.children(recursive=True)
    except psutil.NoSuchProcess:
        return
    for h in hijos:
        try:
            h.kill()
        except psutil.NoSuchProcess:
            pass
    try:
        proc.kill()
    except psutil.NoSuchProcess:
        pass


# ─────────────────────────────── comprobaciones ─────────────────────────────


def check_interprete() -> bool:
    exe = Path(sys.executable).resolve()
    try:
        ok = exe.is_relative_to(VENV_DIR.resolve())
    except AttributeError:  # py<3.9 (no esperado en el venv)
        ok = str(exe).startswith(str(VENV_DIR.resolve()))
    if ok:
        _p(f"[OK] Interprete: {exe}")
        return True
    _p("[ABORT] Este launcher solo puede correr con el python del proyecto:")
    _p(f"        {VENV_DIR / 'Scripts' / 'python.exe'}")
    _p(f"        (estas usando: {exe})")
    _p("        Usa backend\\scripts\\arrancar_backend.bat, que lo localiza solo.")
    return False


def check_entorno() -> bool:
    from dotenv import load_dotenv

    load_dotenv(BASE_DIR / ".env")
    ok = True
    if os.getenv("DISABLE_GCS_SYNC", "").strip().lower() != "true":
        _p("[ABORT] DISABLE_GCS_SYNC no es 'true' en backend/.env.")
        _p("        Sin ello, tu local puede SOBRESCRIBIR la BD de usuarios de PROD")
        _p("        (ver AGENTS.md, seccion 'Seguridad en desarrollo local').")
        ok = False
    else:
        _p("[OK] DISABLE_GCS_SYNC=true (GCS sync desactivado en local)")
    if os.getenv("LIVE_SCREENER_ENABLED", "").strip().lower() != "false":
        _p("[ABORT] LIVE_SCREENER_ENABLED no es 'false' en backend/.env.")
        _p("        Sin ello peleas la unica conexion en vivo y DEGRADAS el")
        _p("        screener de PROD (ver AGENTS.md).")
        ok = False
    else:
        _p("[OK] LIVE_SCREENER_ENABLED=false")
    return ok


def check_puerto(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(2.0)
        ocupado = s.connect_ex(("127.0.0.1", port)) == 0
    if not ocupado:
        _p(f"[OK] Puerto {port} libre")
        return True

    _p(f"[ABORT] Ya hay un proceso escuchando en el puerto {port}:")
    pid = _pid_en_puerto(port)
    if pid:
        desc = _descripcion_pid(pid)
        _p(f"        {desc}")
    _p("        - Si responde GET /health, probablemente sea el backend ya")
    _p("          arrancado (quizas el que rearranco la tarea 'Edgecute")
    _p("          Actualizar Datos Diario' tras la carga de las 09:00):")
    _p("          NO lo mates ni arranques un segundo.")
    _p("        - Si es un huerfano que no responde, matalo con:")
    _p(f"          taskkill /PID {pid or '<pid>'} /T /F")
    return False


def _pid_en_puerto(port: int) -> int | None:
    import psutil

    try:
        for c in psutil.net_connections(kind="inet"):
            if (
                c.status == psutil.CONN_LISTEN
                and c.laddr is not None
                and c.laddr.port == port
                and c.pid
            ):
                return c.pid
    except Exception:
        pass
    try:  # fallback clasico
        out = subprocess.run(
            ["netstat", "-ano", "-p", "tcp"], capture_output=True, text=True
        ).stdout
        for line in out.splitlines():
            if "LISTENING" in line and f":{port} " in line:
                return int(line.split()[-1])
    except Exception:
        pass
    return None


def _descripcion_pid(pid: int) -> str:
    import psutil

    try:
        p = psutil.Process(pid)
        cmdline = " ".join(p.cmdline()) or "(sin cmdline)"
        return f"PID {pid} [{p.name()}] {_trunc(cmdline)}"
    except Exception:
        return f"PID {pid} (sin detalles)"


def check_duckdb() -> bool:
    if os.getenv("DB_PROVIDER", "local").lower() != "local":
        _p(f"[SKIP] DB_PROVIDER={os.getenv('DB_PROVIDER')!r}: la sonda de "
            f"local_data.duckdb solo aplica en modo local.")
        return True

    db = BASE_DIR / "local_data.duckdb"
    if not db.exists():
        _p(f"[ABORT] No existe {db}.")
        _p("        DuckDB CREARIA una base vacia al abrirlo — eso es justo lo")
        _p("        que hay que evitar (backend servido 'bien' sin datos).")
        _p("        Revisa que el cwd del backend es backend/ y que el lago")
        _p("        local esta donde debe.")
        return False

    import duckdb

    try:
        con = duckdb.connect(str(db))
        con.close()
        _p(f"[OK] {db.name} se abre y se cierra limpio (nadie lo retiene)")
        return True
    except Exception as e:
        _p("[ABORT] No se pudo abrir local_data.duckdb en exclusiva.")
        _p(f"        Error original de DuckDB: {type(e).__name__}: {_trunc(str(e), 400)}")
        _p("        Ese error criptico (lock / 'Failed to load metadata pointer')")
        _p("        significa CONTENCION (otro proceso con la base abierta; DuckDB")
        _p("        solo admite un escritor) o CHOQUE DE VERSIONES de duckdb: este")
        _p(f"        venv usa duckdb {getattr(duckdb, '__version__', '?')}; si la base")
        _p("        se verifico/actualizo/cargo con OTRO interprete (p.ej. el python")
        _p("        del sistema) con otra version, su storage puede ser ilegible")
        _p("        para este. Compara versiones antes de tocar nada:")
        _p('          py -c "import duckdb; print(duckdb.__version__)"')
        _p('          backend\\.venv\\Scripts\\python.exe -c "import duckdb; print(duckdb.__version__)"')
        now = datetime.now()
        if 8 <= now.hour < 11:
            _p("        OJO con la hora: la tarea 'Edgecute Actualizar Datos Diario'")
            _p("        (cangrejo_data) para el backend sobre las 09:00 y retiene el")
            _p("        DuckDB mientras carga. NO compitas con ella: espera a que")
            _p("        termine y el backend vuelva solo (GET /health).")
        sosp = _sospechosos()
        if sosp:
            _p("        Procesos sospechosos ahora mismo:")
            vivos = {p["pid"] for p in _iter_python_procs()}
            for p in sosp:
                estado = "HUERFANO (padre muerto)" if p["ppid"] not in vivos else "vivo"
                _p(_fmt(p) + f"  <- {estado}")
            _p("        Para matar un arbol huerfano: taskkill /PID <pid> /T /F")
            _p("        (o relanza este script con --kill-orphans).")
        else:
            _p("        No veo procesos python sospechosos: puede ser la carga de")
            _p("        las 09:00 de cangrejo_data u otro usuario de la maquina.")
        return False


def matar_huerfanos() -> int:
    sosp = _sospechosos()
    huerf = _huerfanos(sosp)
    if not huerf:
        _p("[OK] Sin huerfanos spawn_main/uvicorn detectados")
        return 0
    _p(f"[KILL] Matando {len(huerf)} arbol(es) huerfano(s):")
    for p in huerf:
        _p(f"      {_fmt(p)}")
        _matar_arbol(p["pid"])
    import time

    time.sleep(1.0)
    return len(huerf)


# ─────────────────────────────────── main ───────────────────────────────────


def main() -> int:
    ap = argparse.ArgumentParser(description="Arranque seguro del backend local BTT")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--host", default=DEFAULT_HOST)
    ap.add_argument("--kill-orphans", action="store_true",
                    help="matar arboles huerfanos de python antes de comprobar")
    ap.add_argument("--check-only", action="store_true",
                    help="solo ejecutar las comprobaciones, sin arrancar")
    args = ap.parse_args()

    _p("=" * 68)
    _p("ARRANQUE SEGURO DEL BACKEND BTT")
    _p("Regla de oro: UN solo proceso con local_data.duckdb abierto.")
    _p("Sin --reload, 1 worker. Detalle: docs/REGLA_ARRANQUE_BACKEND_LOCAL.md")
    _p("=" * 68)

    if not check_interprete():
        return EXIT_WRONG_PYTHON
    if not check_entorno():
        return EXIT_ENV_UNSAFE

    try:
        import psutil  # noqa: F401
    except ImportError:
        _p("[ABORT] Falta psutil en el venv (pip install psutil).")
        return EXIT_ENV_UNSAFE

    if args.kill_orphans:
        matar_huerfanos()

    if not check_puerto(args.port):
        return EXIT_PORT_BUSY
    if not check_duckdb():
        return EXIT_DB_BUSY

    if args.check_only:
        _p("[OK] Comprobaciones superadas (--check-only: no se arranca nada).")
        return EXIT_OK

    _p(f"[START] uvicorn app.main:app  host={args.host}  port={args.port}  "
        f"reload=False  workers=1")
    _p(f"[START] PID del launcher: {os.getpid()} — para parar el backend:")
    _p(f"        taskkill /PID {os.getpid()} /T /F   (el /T mata tambien al")
    _p("        hijo python-base que crea el trampoline del venv)")

    os.chdir(BASE_DIR)  # app usa rutas relativas: .env, users.duckdb, caches
    # `python -m uvicorn` mete el cwd en sys.path; como script hay que hacerlo
    # a mano para que `app.main` sea importable.
    if str(BASE_DIR) not in sys.path:
        sys.path.insert(0, str(BASE_DIR))
    os.environ.setdefault("BTT_REQUIRE_DB", "1")

    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=args.host,
        port=args.port,
        reload=False,
        workers=1,
    )
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
