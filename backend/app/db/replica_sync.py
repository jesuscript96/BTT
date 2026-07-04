"""
Réplica local de slabs (EPIC C, PRD rendimiento-backtester §03.5/§03.10).

Construye y refresca los slabs mensuales para TODO el histórico configurado, desde
una fuente configurable — el punto pensado para la migración de datos del CTO:

  BTT_REPLICA_SOURCE = "gcs"        → lee gs://{GCS_BUCKET}/cold_storage/... (hoy)
  BTT_REPLICA_SOURCE = "/data/..."  → lee un mirror local con el MISMO layout hive
                                       <root>/intraday_1m{,_optimized}/year=Y/month=M/*.parquet
                                       (mañana, cuando los datos vivan en el hardware propio)

El código de build es el mismo en ambos casos (slab_builder.build_month_from_parquet_glob);
migrar = cambiar una env. GCS sigue siendo la fuente de verdad; el slab es caché derivado.

Reglas de refresco (idempotente):
  - mes sin slab → se construye;
  - el MES CORRIENTE se reconstruye siempre (sigue recibiendo datos);
  - resto de meses con slab válido → se saltan.

Todo best-effort: nunca lanza, nunca tumba el proceso (patrón prewarm_gap_universe).
"""
import datetime as _dt
import logging
import os
import re
import threading
import time

logger = logging.getLogger("backtester.replica")

REPLICA_ENABLED = os.getenv("BTT_REPLICA_SYNC_ENABLED", "false").strip().lower() in ("1", "true", "yes", "on")
REPLICA_SOURCE = os.getenv("BTT_REPLICA_SOURCE", "gcs").strip()
REPLICA_INTERVAL_H = float(os.getenv("BTT_REPLICA_SYNC_INTERVAL_H", "24"))
REPLICA_YEARS = os.getenv("BTT_REPLICA_YEARS", "2021-2026").strip()
PAGECACHE_WARM = os.getenv("BTT_SLAB_PAGECACHE_WARM", "false").strip().lower() in ("1", "true", "yes", "on")

_KINDS = (("opt", "intraday_1m_optimized"), ("raw", "intraday_1m"))
_HIVE_RE = re.compile(r"year=(\d{4})/month=(\d{1,2})/")


def parse_years(spec: str) -> set[int]:
    """"2021-2026" | "2024" | "2021,2023" → set de años. Inválido → set vacío."""
    years: set[int] = set()
    try:
        for part in spec.split(","):
            part = part.strip()
            if not part:
                continue
            if "-" in part:
                a, b = part.split("-", 1)
                years.update(range(int(a), int(b) + 1))
            else:
                years.add(int(part))
    except Exception:
        return set()
    return years


def discover_months(source: str = None) -> list[dict]:
    """Meses disponibles en la fuente. Devuelve [{kind, folder, year, month, glob}].
    Con opt y raw para el mismo mes, gana opt (paridad con _select_intraday_glob_for_month)."""
    source = source if source is not None else REPLICA_SOURCE
    found: dict[tuple[int, int], dict] = {}

    if source == "gcs":
        from app.db.connection import get_connection, GCS_BUCKET
        conn = get_connection()
        for kind, folder in _KINDS:
            try:
                rows = conn.execute(
                    f"SELECT file FROM glob('gs://{GCS_BUCKET}/cold_storage/{folder}/*/*/*.parquet')"
                ).fetchall()
            except Exception as e:
                logger.warning(f"[REPLICA] glob GCS {folder} falló: {e}")
                continue
            for (f,) in rows:
                m = _HIVE_RE.search(f)
                if not m:
                    continue
                y, mm = int(m.group(1)), int(m.group(2))
                key = (y, mm)
                # _KINDS itera opt primero: si el mes ya está como opt, raw no lo pisa
                if key in found and found[key]["kind"] == "opt":
                    continue
                found[key] = {
                    "kind": kind, "folder": folder, "year": y, "month": mm,
                    "glob": f"gs://{GCS_BUCKET}/cold_storage/{folder}/year={y}/month={mm}/*.parquet",
                }
    else:
        # Mirror local (migración): <root>/<folder>/year=Y/month=M/*.parquet
        for kind, folder in _KINDS:
            base = os.path.join(source, folder)
            if not os.path.isdir(base):
                continue
            for ydir in sorted(os.listdir(base)):
                if not ydir.startswith("year="):
                    continue
                for mdir in sorted(os.listdir(os.path.join(base, ydir))):
                    if not mdir.startswith("month="):
                        continue
                    full = os.path.join(base, ydir, mdir)
                    if not any(n.endswith(".parquet") for n in os.listdir(full)):
                        continue
                    y, mm = int(ydir.split("=")[1]), int(mdir.split("=")[1])
                    key = (y, mm)
                    if key in found and found[key]["kind"] == "opt":
                        continue  # opt ya encontrado, no degradar a raw
                    found[key] = {"kind": kind, "folder": folder, "year": y, "month": mm,
                                  "glob": os.path.join(full, "*.parquet")}

    return [found[k] for k in sorted(found)]


def run_sync_once(source: str = None, years: set[int] = None, now: _dt.date = None) -> dict:
    """Una pasada de sync. Devuelve {built, skipped, failed, months}."""
    from app.db.slab_builder import build_month_from_parquet_glob
    from app.db.slab_store import slab_exists

    years = years if years is not None else parse_years(REPLICA_YEARS)
    now = now or _dt.date.today()
    months = [x for x in discover_months(source) if not years or x["year"] in years]

    built = skipped = failed = 0
    t0 = time.time()
    for mi, spec in enumerate(months, 1):
        y, m, kind = spec["year"], spec["month"], spec["kind"]
        is_current = (y == now.year and m == now.month)
        if slab_exists(kind, y, m) and not is_current:
            skipped += 1
            continue
        try:
            res = build_month_from_parquet_glob(spec["glob"], kind, y, m)
            if res is not None:
                built += 1
            else:
                skipped += 1
        except Exception as e:
            failed += 1
            logger.warning(f"[REPLICA] build {kind} {y}-{m:02d} falló: {e}")
        if mi % 6 == 0:
            logger.info(f"[REPLICA] {mi}/{len(months)} meses ({built} nuevos, {round(time.time()-t0)}s)")

    logger.info(f"[REPLICA] sync done: {built} construidos, {skipped} al día, "
                f"{failed} fallidos de {len(months)} meses ({round(time.time()-t0)}s)")
    return {"built": built, "skipped": skipped, "failed": failed, "months": len(months)}


def warm_page_cache(max_bytes: int = 0) -> int:
    """Lee secuencialmente los slabs (recientes primero) para calentar el page cache.
    En HDD esto convierte lecturas aleatorias posteriores en hits de RAM (128 GB).
    Devuelve bytes leídos. max_bytes=0 → sin límite."""
    from app.db.slab_builder import slab_root
    root = slab_root()
    if not os.path.isdir(root):
        return 0
    slabs = []
    for dirpath, _dirs, names in os.walk(root):
        for n in names:
            if n == "slab.arrow":
                slabs.append(os.path.join(dirpath, n))
    # recientes primero: los backtests suelen tocar los últimos años
    slabs.sort(reverse=True)
    read = 0
    t0 = time.time()
    for p in slabs:
        try:
            with open(p, "rb", buffering=1024 * 1024) as f:
                while chunk := f.read(8 * 1024 * 1024):
                    read += len(chunk)
                    if max_bytes and read >= max_bytes:
                        raise StopIteration
        except StopIteration:
            break
        except OSError:
            continue
    logger.info(f"[REPLICA] page cache warm: {read/1e9:.1f} GB en {round(time.time()-t0)}s "
                f"({len(slabs)} slabs)")
    return read


def start_replica_daemon() -> None:
    """Hilo daemon: sync inicial (+warm) y refresco periódico. Gated por env."""
    if not REPLICA_ENABLED:
        logger.info("[REPLICA] disabled (BTT_REPLICA_SYNC_ENABLED=false)")
        return

    def _loop():
        while True:
            try:
                run_sync_once()
                if PAGECACHE_WARM:
                    warm_page_cache()
            except Exception as e:  # nunca tumbar el proceso
                logger.warning(f"[REPLICA] pasada de sync falló: {e}")
            time.sleep(max(1.0, REPLICA_INTERVAL_H) * 3600)

    threading.Thread(target=_loop, daemon=True, name="replica-sync").start()
    logger.info(f"[REPLICA] daemon iniciado (source={REPLICA_SOURCE}, years={REPLICA_YEARS}, "
                f"interval={REPLICA_INTERVAL_H}h, warm={PAGECACHE_WARM})")
