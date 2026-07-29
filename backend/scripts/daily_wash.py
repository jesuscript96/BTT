#!/usr/bin/env python3
"""
Lavado diario Augus del lake LOCAL (Opción A) — corre DENTRO del contenedor de prod.

Para cada día objetivo (que exista en GCS y no esté ya lavado):
  1. ESPEJA el fichero per-día GCS -> lake local (raw as-traded), COPY vía DuckDB httpfs.
  2. UNIVERSO gap>=5 · CS/ADRC · sin splits del día -> CSV.
  3. GEN Augus (windowed, NBBO ±0.5%) sobre ese CSV -> staging del día.
  4. MERGE per-día (preserve-count) -> aplica limpio al fichero del lake local (backup previo).
  5. Marca el día como lavado (checkpoint).
Al final PURGA la disk-cache de los meses tocados (la app la reconstruye del lake limpio).

El cron (host) hace, tras esto, `docker restart` para recargar prewarm/RAM limpios.

Selección de días:
  --date YYYY-MM-DD           un solo día
  --from A --to B             rango
  (sin args)                  últimos WASH_LOOKBACK_DAYS días hasta hoy
Idempotente: un día ya en el checkpoint se salta. Reanudable.

Env (todas presentes en prod): MASSIVE_API_KEY, GCS_BUCKET, GCS_ACCESS_KEY_ID,
GCS_SECRET_ACCESS_KEY, CACHE_DIR, LOCAL_LAKE_DIR. Opcionales: WASH_DIR (/tmp/daily_wash),
WASH_LOOKBACK_DAYS (5), AUGUS_WORKERS (8), AUGUS_GAP_MIN (5).
"""
import os, sys, json, subprocess, argparse, logging
from datetime import datetime, timedelta, date

import duckdb

logging.basicConfig(level=logging.INFO, format="%(asctime)s [daily_wash] %(message)s")
log = logging.getLogger().info

BUCKET   = os.environ["GCS_BUCKET"]
LAKE     = os.getenv("LOCAL_LAKE_DIR", "/lake").rstrip("/")
CACHE    = os.getenv("CACHE_DIR", "/tmp/btt_intraday_cache").rstrip("/")
WASH_DIR = os.getenv("WASH_DIR", "/tmp/daily_wash").rstrip("/")
WORKERS  = os.getenv("AUGUS_WORKERS", "8")
GAP_MIN  = os.getenv("AUGUS_GAP_MIN", "5")
LOOKBACK = int(os.getenv("WASH_LOOKBACK_DAYS", "5"))
HERE     = os.path.dirname(os.path.abspath(__file__))
GEN      = os.path.join(HERE, "gen_clean_augus_par.py")
MERGE    = os.path.join(HERE, "merge_perday.py")

os.makedirs(WASH_DIR, exist_ok=True)
CKPT = f"{WASH_DIR}/wash_ckpt.json"
ckpt = json.load(open(CKPT)) if os.path.exists(CKPT) else {"done": []}


def _ddb():
    c = duckdb.connect()
    c.execute("INSTALL httpfs; LOAD httpfs;")
    c.execute(f"SET s3_access_key_id='{os.environ['GCS_ACCESS_KEY_ID']}';")
    c.execute(f"SET s3_secret_access_key='{os.environ['GCS_SECRET_ACCESS_KEY']}';")
    c.execute("SET s3_endpoint='storage.googleapis.com'; SET s3_region='us-east-1'; SET s3_url_style='path';")
    return c


def gcs_intraday(y, m, d):
    return f"gs://{BUCKET}/cold_storage/intraday_1m/year={y}/month={m}/catchup_intraday_{d}.parquet"

def local_intraday(y, m, d):
    return f"{LAKE}/cold_storage/intraday_1m/year={y}/month={m}/catchup_intraday_{d}.parquet"


def gcs_file_exists(c, path):
    try:
        return c.execute("SELECT count(*) FROM glob(?)", [path]).fetchone()[0] > 0
    except Exception:
        return False


def mirror(c, y, m, d):
    """GCS -> lake local (raw as-traded). Sobrescribe el fichero local."""
    src = gcs_intraday(y, m, d); dst = local_intraday(y, m, d)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    c.execute(f"COPY (SELECT * FROM read_parquet('{src}')) TO '{dst}' (FORMAT PARQUET)")
    n = c.execute("SELECT count(*) FROM read_parquet(?)", [dst]).fetchone()[0]
    log(f"  [1/mirror] {d}: {n:,} filas GCS->local")


def build_universe_csv(c, y, m, d):
    """Universo gap>=GAP_MIN · CS/ADRC · sin splits del día -> CSV Ticker,Date."""
    dm = f"gs://{BUCKET}/cold_storage/daily_metrics/year={y}/month={m}/*.parquet"
    q = f"""
      SELECT DISTINCT dm.ticker AS ticker
      FROM read_parquet('{dm}') dm
      JOIN (SELECT DISTINCT ticker,type FROM read_parquet('gs://{BUCKET}/cold_storage/tickers/*.parquet')) tk
        ON dm.ticker=tk.ticker AND tk.type IN ('CS','ADRC')
      WHERE dm.gap_pct >= {float(GAP_MIN)}
        AND CAST(dm.timestamp AS DATE) = DATE '{d}'
        AND NOT EXISTS (SELECT 1 FROM read_parquet('gs://{BUCKET}/cold_storage/splits/*.parquet') sp
                        WHERE sp.ticker=dm.ticker AND CAST(sp.execution_date AS DATE)=DATE '{d}')
    """
    tickers = [r[0] for r in c.execute(q).fetchall()]
    csv = f"{WASH_DIR}/uni_{d}.csv"
    with open(csv, "w") as f:
        f.write("Ticker,Date\n")
        for t in tickers:
            f.write(f"{t},{d}\n")
    log(f"  [2/universo] {d}: {len(tickers)} ticker-días gap>={GAP_MIN}")
    return csv, len(tickers)


def run(cmd, extra_env=None):
    env = dict(os.environ)
    if extra_env:
        env.update(extra_env)
    r = subprocess.run(cmd, env=env, capture_output=True, text=True)
    if r.returncode != 0:
        log(f"  !! ERROR ({r.returncode}) en: {' '.join(cmd)}")
        log(r.stdout[-2000:]); log(r.stderr[-2000:])
        raise RuntimeError(f"subprocess falló: {cmd[0]}")
    return r.stdout


def wash_day(c, d):
    dt = datetime.strptime(d, "%Y-%m-%d").date()
    y, m = dt.year, dt.month
    if not gcs_file_exists(c, gcs_intraday(y, m, d)):
        log(f"  {d}: no hay fichero en GCS todavía, skip"); return False
    log(f"=== LAVANDO {d} ===")
    mirror(c, y, m, d)
    csv, n = build_universe_csv(c, y, m, d)
    stg = f"{WASH_DIR}/y{y}_m{m}.parquet"
    if n > 0:
        run([sys.executable, GEN, "--csv", csv, "--window", "--workers", WORKERS, "--out", stg, "--tag", f"daily {d}"],
            extra_env={"AUGUS_GAP_MIN": GAP_MIN, "AUGUS_PROGRESS": f"{WASH_DIR}/progress_{d}.json"})
        run([sys.executable, MERGE, "--year", str(y), "--month", str(m), "--date", d,
             "--staging", WASH_DIR, "--backup", f"{WASH_DIR}/backup"])
    else:
        log(f"  {d}: universo vacío, nada que lavar (fichero espejado tal cual)")
    ckpt["done"].append(d); json.dump(ckpt, open(CKPT, "w"))
    return (y, m)


def purge_cache(months):
    import shutil
    for (y, m) in months:
        for sub in ("raw", "opt"):
            p = f"{CACHE}/{sub}/{y}/{m:02d}"
            if os.path.isdir(p):
                shutil.rmtree(p, ignore_errors=True); log(f"  [purge] {sub}/{y}/{m:02d}")
            p1 = f"{CACHE}/{sub}/{y}/{m}"   # por si el mes va sin cero
            if os.path.isdir(p1):
                shutil.rmtree(p1, ignore_errors=True); log(f"  [purge] {sub}/{y}/{m}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date")
    ap.add_argument("--from", dest="dfrom")
    ap.add_argument("--to", dest="dto")
    args = ap.parse_args()

    if args.date:
        days = [args.date]
    elif args.dfrom and args.dto:
        a = datetime.strptime(args.dfrom, "%Y-%m-%d").date()
        b = datetime.strptime(args.dto, "%Y-%m-%d").date()
        days = [(a + timedelta(days=i)).strftime("%Y-%m-%d") for i in range((b - a).days + 1)]
    else:
        today = datetime.now().date()
        days = [(today - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(LOOKBACK, 0, -1)]

    days = [d for d in days if d not in ckpt["done"]]
    if not days:
        log("nada que lavar (todos en checkpoint)"); return
    log(f"días objetivo: {days}")

    c = _ddb()
    touched = set()
    n_dias = 0
    for d in days:
        try:
            r = wash_day(c, d)
            if r:
                touched.add(r); n_dias += 1
        except Exception as e:
            log(f"  {d}: FALLÓ ({e}); sigo con el resto")
    if touched:
        log(f"purgando cache de meses tocados: {sorted(touched)}")
        purge_cache(touched)
    log(f"[FIN] dias_lavados={n_dias} meses_tocados={sorted(touched)}")


if __name__ == "__main__":
    main()
