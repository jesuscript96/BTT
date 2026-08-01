#!/usr/bin/env python3
"""Merge QUIRÚRGICO OHLCV para el re-pase POR-SPREAD (ticker-días nunca limpiados).

A diferencia de merge_volume_only (congela O/H/L/C porque el precio ya estaba limpio),
aquí los ticker-días detectados por spread NUNCA se limpiaron ⇒ precio Y volumen sucios.
Aplica O/H/L/C/volume/transactions del staging SOLO en las velas reconstruidas
(vol_recon=True); el resto de velas se quedan EXACTAS como el lake.

  open/high/low/close/volume/transactions = CASE WHEN s.vol_recon THEN s.*  ELSE r.* END
  timestamp/date/month/year               = r.*  (del lake, SIEMPRE)

Gates DUROS por fichero (si fallan ⇒ NO reemplaza, aborta):
  1. filas y nº de tickers idénticos al lake (preserve-count).
  2. O/H/L/C SOLO cambian en velas marcadas (0 cambios OHLC en no marcadas).
  3. volumen SOLO cambia en velas marcadas (0 cambios en no marcadas).
  4. cobertura (ticker,timestamp) idéntica.

Backup por fichero + reemplazo atómico. Un fichero del lake por invocación (--lake-file).
"""
import duckdb, os, sys, shutil, argparse

def log(m): print(m, flush=True)

def process(c, raw, stg, backup_dir, dry):
    fname = os.path.basename(raw)
    merged = raw + ".ohlcvmerged"
    if os.path.exists(merged): os.remove(merged)

    raw_rows = c.execute("SELECT count(*) FROM read_parquet(?)", [raw]).fetchone()[0]
    raw_tk   = c.execute("SELECT count(DISTINCT ticker) FROM read_parquet(?)", [raw]).fetchone()[0]

    body = f"""
        SELECT r.ticker AS ticker,
               CASE WHEN s.vol_recon IS TRUE THEN COALESCE(s.volume, r.volume) ELSE r.volume END AS volume,
               CASE WHEN s.vol_recon IS TRUE THEN COALESCE(s.open,  r.open)  ELSE r.open  END AS open,
               CASE WHEN s.vol_recon IS TRUE THEN COALESCE(s.close, r.close) ELSE r.close END AS close,
               CASE WHEN s.vol_recon IS TRUE THEN COALESCE(s.high,  r.high)  ELSE r.high  END AS high,
               CASE WHEN s.vol_recon IS TRUE THEN COALESCE(s.low,   r.low)   ELSE r.low   END AS low,
               r.timestamp AS timestamp,
               CASE WHEN s.vol_recon IS TRUE THEN COALESCE(s.transactions, r.transactions) ELSE r.transactions END AS transactions,
               r.date AS date, r.month AS month, r.year AS year
        FROM read_parquet('{raw}') r
        LEFT JOIN read_parquet('{stg}') s
          ON s.ticker = r.ticker AND s.timestamp = r.timestamp
    """
    c.execute(f"COPY ({body}) TO '{merged}' (FORMAT PARQUET)")

    new_rows = c.execute("SELECT count(*) FROM read_parquet(?)", [merged]).fetchone()[0]
    new_tk   = c.execute("SELECT count(DISTINCT ticker) FROM read_parquet(?)", [merged]).fetchone()[0]

    # cambios OHLC (marcados y sin marcar)
    ohlc_changed = c.execute(f"""
      SELECT count(*) FROM read_parquet('{merged}') m JOIN read_parquet('{raw}') r USING(ticker,timestamp)
      WHERE abs(m.open-r.open)>1e-9 OR abs(m.high-r.high)>1e-9 OR abs(m.low-r.low)>1e-9 OR abs(m.close-r.close)>1e-9""").fetchone()[0]
    ohlc_changed_unmarked = c.execute(f"""
      SELECT count(*) FROM read_parquet('{merged}') m
      JOIN read_parquet('{raw}') r USING(ticker,timestamp)
      LEFT JOIN read_parquet('{stg}') s USING(ticker,timestamp)
      WHERE (abs(m.open-r.open)>1e-9 OR abs(m.high-r.high)>1e-9 OR abs(m.low-r.low)>1e-9 OR abs(m.close-r.close)>1e-9)
        AND (s.vol_recon IS NULL OR s.vol_recon IS FALSE)""").fetchone()[0]

    # cambios volumen (marcados y sin marcar)
    vol_changed = c.execute(f"""
      SELECT count(*) FROM read_parquet('{merged}') m JOIN read_parquet('{raw}') r USING(ticker,timestamp)
      WHERE m.volume<>r.volume""").fetchone()[0]
    vol_changed_unmarked = c.execute(f"""
      SELECT count(*) FROM read_parquet('{merged}') m
      JOIN read_parquet('{raw}') r USING(ticker,timestamp)
      LEFT JOIN read_parquet('{stg}') s USING(ticker,timestamp)
      WHERE m.volume<>r.volume AND (s.vol_recon IS NULL OR s.vol_recon IS FALSE)""").fetchone()[0]

    cov = c.execute(f"""
      SELECT (SELECT count(*) FROM (SELECT ticker,timestamp FROM read_parquet('{merged}')
                                    EXCEPT SELECT ticker,timestamp FROM read_parquet('{raw}'))),
             (SELECT count(*) FROM (SELECT ticker,timestamp FROM read_parquet('{raw}')
                                    EXCEPT SELECT ticker,timestamp FROM read_parquet('{merged}')))""").fetchone()

    ok_rows = (new_rows == raw_rows); ok_tk = (new_tk == raw_tk)
    ok_ohlc_u = (ohlc_changed_unmarked == 0); ok_vol_u = (vol_changed_unmarked == 0)
    ok_cov = (cov[0] == 0 and cov[1] == 0)
    ok = ok_rows and ok_tk and ok_ohlc_u and ok_vol_u and ok_cov
    log(f"[{fname}] filas={raw_rows:,}->{new_rows:,}(ok={ok_rows}) tk={raw_tk}/{new_tk}(ok={ok_tk}) | "
        f"OHLC_cambiado={ohlc_changed:,} SIN_marca={ohlc_changed_unmarked}(ok={ok_ohlc_u}) | "
        f"vol_cambiado={vol_changed:,} SIN_marca={vol_changed_unmarked}(ok={ok_vol_u}) | "
        f"cobertura_id={ok_cov}(extra={cov[0]},faltan={cov[1]})")

    if not ok:
        log(f"[{fname}] !!! GATE FALLA -> NO reemplaza, borro temporal"); os.remove(merged); return False
    if dry:
        os.remove(merged); return True
    os.makedirs(backup_dir, exist_ok=True)
    bfile = f"{backup_dir}/{fname}"
    if not os.path.exists(bfile):
        shutil.copy2(raw, bfile)
    os.replace(merged, raw)
    return True

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lake-file", required=True)
    ap.add_argument("--staging", required=True)
    ap.add_argument("--backup", required=True)
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()
    if not os.path.exists(args.lake_file):
        log(f"[FATAL] no existe lake-file {args.lake_file}"); sys.exit(2)
    if not os.path.exists(args.staging):
        log(f"[FATAL] no existe staging {args.staging}"); sys.exit(2)
    c = duckdb.connect()
    cols = [r[0] for r in c.execute(f"DESCRIBE SELECT * FROM read_parquet('{args.staging}')").fetchall()]
    if "vol_recon" not in cols:
        log("[FATAL] el staging no tiene columna vol_recon"); sys.exit(2)
    ok = process(c, args.lake_file, args.staging, args.backup, args.dry)
    if not ok and not args.dry:
        log("[FATAL] gate falló -> ABORTO"); sys.exit(2)
    log(f"[FIN] ok={ok} dry={args.dry}")

if __name__ == "__main__":
    main()
