#!/usr/bin/env python3
"""
Merge de limpieza Augus al lake LOCAL, layout PER-DÍA (catchup_intraday_YYYY-MM-DD.parquet).
Cada fichero = un día, todos los tickers. Aplica OHLCV limpio SOLO sobre velas ya
existentes en el fichero (LEFT JOIN por ticker,timestamp + COALESCE) -> NO añade ni
quita barras (preserve-count). Backup por fichero + reemplazo atómico. Reanudable.
Gates duros por fichero: filas==raw, tickers==raw, cobertura idéntica, OHLC=staging.

--date YYYY-MM-DD  restringe a un solo día (uso diario). Sin él, todo el mes.
"""
import duckdb, os, sys, json, shutil, argparse, glob

def log(m): print(m, flush=True)

def process_file(c, raw, stg, backup_dir, dry, ckpt_path, ckpt):
    fname = os.path.basename(raw)
    if not dry and fname in ckpt["done"]:
        log(f"[{fname}] ya aplicado (checkpoint), skip"); return True
    merged = raw + ".merged"
    if os.path.exists(merged): os.remove(merged)

    raw_rows = c.execute("SELECT count(*) FROM read_parquet(?)", [raw]).fetchone()[0]
    raw_tk   = c.execute("SELECT count(DISTINCT ticker) FROM read_parquet(?)", [raw]).fetchone()[0]

    stg_day_rows = c.execute(
        "SELECT count(*) FROM read_parquet(?) WHERE CAST(date AS DATE) IN "
        "(SELECT DISTINCT CAST(date AS DATE) FROM read_parquet(?))", [stg, raw]).fetchone()[0]

    body = f"""
        SELECT r.ticker AS ticker,
               COALESCE(s.volume,r.volume) AS volume,
               COALESCE(s.open,r.open) AS open,
               COALESCE(s.close,r.close) AS close,
               COALESCE(s.high,r.high) AS high,
               COALESCE(s.low,r.low) AS low,
               r.timestamp AS timestamp,
               COALESCE(s.transactions,r.transactions) AS transactions,
               r.date AS date, r.month AS month, r.year AS year
        FROM read_parquet('{raw}') r
        LEFT JOIN read_parquet('{stg}') s
          ON s.ticker=r.ticker AND s.timestamp=r.timestamp
    """
    c.execute(f"COPY ({body}) TO '{merged}' (FORMAT PARQUET)")

    new_rows = c.execute("SELECT count(*) FROM read_parquet(?)", [merged]).fetchone()[0]
    new_tk   = c.execute("SELECT count(DISTINCT ticker) FROM read_parquet(?)", [merged]).fetchone()[0]
    diffs = c.execute(f"""
      WITH m AS (SELECT ticker,timestamp,open,high,low,close FROM read_parquet('{merged}')),
           s AS (SELECT ticker,timestamp,open,high,low,close FROM read_parquet('{stg}'))
      SELECT count(*) FROM m JOIN s USING(ticker,timestamp)
      WHERE abs(m.open-s.open)>1e-9 OR abs(m.high-s.high)>1e-9
         OR abs(m.low-s.low)>1e-9 OR abs(m.close-s.close)>1e-9""").fetchone()[0]
    cov = c.execute(f"""
      SELECT (SELECT count(*) FROM (SELECT ticker,timestamp FROM read_parquet('{merged}')
                                    EXCEPT SELECT ticker,timestamp FROM read_parquet('{raw}'))),
             (SELECT count(*) FROM (SELECT ticker,timestamp FROM read_parquet('{raw}')
                                    EXCEPT SELECT ticker,timestamp FROM read_parquet('{merged}')))""").fetchone()
    stg_in_raw = c.execute(f"""
      SELECT count(*) FROM read_parquet('{stg}') s
      WHERE EXISTS (SELECT 1 FROM read_parquet('{raw}') r
                    WHERE r.ticker=s.ticker AND r.timestamp=s.timestamp)""").fetchone()[0]

    ok_rows = (new_rows == raw_rows); ok_tk = (new_tk == raw_tk)
    ok_diff = (diffs == 0); ok_cov = (cov[0] == 0 and cov[1] == 0)
    ok = ok_rows and ok_tk and ok_diff and ok_cov
    log(f"[{fname}] | raw_rows={raw_rows:,} new={new_rows:,}(ok={ok_rows}) | "
        f"tk={raw_tk}/{new_tk}(ok={ok_tk}) | OHLC_diffs={diffs}(ok={ok_diff}) | "
        f"cobertura_id={ok_cov}(extra={cov[0]},faltan={cov[1]}) | "
        f"staging_aplicado={stg_in_raw}/{stg_day_rows}(AH_descartadas={stg_day_rows-stg_in_raw})")

    if not ok:
        log(f"[{fname}] !!! GATE FALLA -> NO reemplaza, borro temporal"); os.remove(merged); return False
    if dry:
        os.remove(merged); return True
    os.makedirs(backup_dir, exist_ok=True)
    bfile = f"{backup_dir}/{fname}"
    if not os.path.exists(bfile):
        shutil.copy2(raw, bfile)
    os.replace(merged, raw)
    ckpt["done"].append(fname); json.dump(ckpt, open(ckpt_path, "w"))
    return True

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--month", type=int, required=True)
    ap.add_argument("--date", help="YYYY-MM-DD: restringe a un solo día (uso diario)")
    ap.add_argument("--lake", default="/lake/cold_storage/intraday_1m")
    ap.add_argument("--staging", default="/augus_run/staging_2026")
    ap.add_argument("--backup", required=True)
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()

    mdir = f"{args.lake}/year={args.year}/month={args.month}"
    stg  = f"{args.staging}/y{args.year}_m{args.month}.parquet"
    if args.date:
        files = [f"{mdir}/catchup_intraday_{args.date}.parquet"]
        files = [f for f in files if os.path.exists(f)]
    else:
        files = sorted(glob.glob(f"{mdir}/catchup_*.parquet"))
    if not files:
        log(f"[FATAL] no hay fichero(s) per-día en {mdir} (date={args.date})"); sys.exit(2)
    if not os.path.exists(stg):
        log(f"[FATAL] no existe staging {stg}"); sys.exit(2)

    os.makedirs(args.backup, exist_ok=True)
    ckpt_path = f"{args.backup}/perday_ckpt.json"
    ckpt = json.load(open(ckpt_path)) if os.path.exists(ckpt_path) else {"done": []}

    c = duckdb.connect()
    log(f"=== MERGE PER-DÍA {args.year}-{args.month} ficheros={len(files)} date={args.date} dry={args.dry} ===")
    nok = 0
    for raw in files:
        if process_file(c, raw, stg, args.backup, args.dry, ckpt_path, ckpt):
            nok += 1
        elif not args.dry:
            log(f"[FATAL] {os.path.basename(raw)} falló gate -> ABORTO"); sys.exit(2)
    log(f"[FIN] ficheros_ok={nok}/{len(files)} dry={args.dry}")

if __name__ == "__main__":
    main()
