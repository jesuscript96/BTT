#!/usr/bin/env python3
"""
Merge SOLO-VOLUMEN (Opción A estricta) para el RE-PASE histórico.

A diferencia de merge_perday/merge_year (que aplican O/H/L/C + volumen del staging,
correcto para días NUEVOS), este merge está pensado para RE-PASAR el histórico ya
limpio de precio: **congela O/H/L/C exactamente como está en el lake** y solo
reescribe `volume`/`transactions` en las velas que el gen marcó con `vol_recon=True`.

  volume        = CASE WHEN s.vol_recon THEN s.volume        ELSE r.volume        END
  transactions  = CASE WHEN s.vol_recon THEN s.transactions  ELSE r.transactions  END
  O/H/L/C/ts/... = r.*  (del lake, SIEMPRE)

Gates DUROS por fichero (si fallan -> NO reemplaza, aborta):
  1. filas y nº de tickers idénticos al lake (preserve-count).
  2. O/H/L/C IDÉNTICOS al lake (0 diffs) — por construcción, se verifica igual.
  3. el volumen SOLO cambia en velas con vol_recon=True (0 cambios en velas no marcadas).
  4. cobertura (ticker,timestamp) idéntica.

Backup por fichero + reemplazo atómico. Trabaja sobre UN fichero del lake
(--lake-file), sea data_0.parquet mensual o catchup_intraday_*.parquet por día.
"""
import duckdb, os, sys, shutil, argparse

def log(m): print(m, flush=True)

def process(c, raw, stg, backup_dir, dry):
    fname = os.path.basename(raw)
    merged = raw + ".volmerged"
    if os.path.exists(merged): os.remove(merged)

    raw_rows = c.execute("SELECT count(*) FROM read_parquet(?)", [raw]).fetchone()[0]
    raw_tk   = c.execute("SELECT count(DISTINCT ticker) FROM read_parquet(?)", [raw]).fetchone()[0]

    body = f"""
        SELECT r.ticker AS ticker,
               CASE WHEN s.vol_recon IS TRUE THEN COALESCE(s.volume, r.volume)
                    ELSE r.volume END AS volume,
               r.open AS open, r.close AS close, r.high AS high, r.low AS low,
               r.timestamp AS timestamp,
               CASE WHEN s.vol_recon IS TRUE THEN COALESCE(s.transactions, r.transactions)
                    ELSE r.transactions END AS transactions,
               r.date AS date, r.month AS month, r.year AS year
        FROM read_parquet('{raw}') r
        LEFT JOIN read_parquet('{stg}') s
          ON s.ticker=r.ticker AND s.timestamp=r.timestamp
    """
    c.execute(f"COPY ({body}) TO '{merged}' (FORMAT PARQUET)")

    new_rows = c.execute("SELECT count(*) FROM read_parquet(?)", [merged]).fetchone()[0]
    new_tk   = c.execute("SELECT count(DISTINCT ticker) FROM read_parquet(?)", [merged]).fetchone()[0]

    # Gate 2: O/H/L/C idénticos al lake
    ohlc_diff = c.execute(f"""
      WITH m AS (SELECT ticker,timestamp,open,high,low,close FROM read_parquet('{merged}')),
           r AS (SELECT ticker,timestamp,open,high,low,close FROM read_parquet('{raw}'))
      SELECT count(*) FROM m JOIN r USING(ticker,timestamp)
      WHERE abs(m.open-r.open)>1e-9 OR abs(m.high-r.high)>1e-9
         OR abs(m.low-r.low)>1e-9 OR abs(m.close-r.close)>1e-9""").fetchone()[0]

    # Gate 3: volumen SOLO cambia en velas con vol_recon; 0 en no marcadas
    vol_changed = c.execute(f"""
      SELECT count(*) FROM read_parquet('{merged}') m JOIN read_parquet('{raw}') r USING(ticker,timestamp)
      WHERE m.volume<>r.volume""").fetchone()[0]
    vol_changed_unmarked = c.execute(f"""
      SELECT count(*) FROM read_parquet('{merged}') m
      JOIN read_parquet('{raw}') r USING(ticker,timestamp)
      LEFT JOIN read_parquet('{stg}') s USING(ticker,timestamp)
      WHERE m.volume<>r.volume AND (s.vol_recon IS NULL OR s.vol_recon IS FALSE)""").fetchone()[0]

    # Gate 4: cobertura idéntica
    cov = c.execute(f"""
      SELECT (SELECT count(*) FROM (SELECT ticker,timestamp FROM read_parquet('{merged}')
                                    EXCEPT SELECT ticker,timestamp FROM read_parquet('{raw}'))),
             (SELECT count(*) FROM (SELECT ticker,timestamp FROM read_parquet('{raw}')
                                    EXCEPT SELECT ticker,timestamp FROM read_parquet('{merged}')))""").fetchone()

    ok_rows = (new_rows == raw_rows); ok_tk = (new_tk == raw_tk)
    ok_ohlc = (ohlc_diff == 0); ok_unmarked = (vol_changed_unmarked == 0)
    ok_cov = (cov[0] == 0 and cov[1] == 0)
    ok = ok_rows and ok_tk and ok_ohlc and ok_unmarked and ok_cov
    log(f"[{fname}] filas={raw_rows:,}->{new_rows:,}(ok={ok_rows}) tk={raw_tk}/{new_tk}(ok={ok_tk}) | "
        f"OHLC_diffs={ohlc_diff}(ok={ok_ohlc}) | vol_cambiado={vol_changed:,} "
        f"vol_cambiado_SIN_marca={vol_changed_unmarked}(ok={ok_unmarked}) | "
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
    ap.add_argument("--lake-file", required=True, help="fichero del lake a re-pasar (data_0.parquet o catchup_*.parquet)")
    ap.add_argument("--staging", required=True, help="parquet de staging con columna vol_recon")
    ap.add_argument("--backup", required=True)
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()
    if not os.path.exists(args.lake_file):
        log(f"[FATAL] no existe lake-file {args.lake_file}"); sys.exit(2)
    if not os.path.exists(args.staging):
        log(f"[FATAL] no existe staging {args.staging}"); sys.exit(2)
    c = duckdb.connect()
    # sanity: el staging debe traer vol_recon
    cols = [r[0] for r in c.execute(f"DESCRIBE SELECT * FROM read_parquet('{args.staging}')").fetchall()]
    if "vol_recon" not in cols:
        log("[FATAL] el staging no tiene columna vol_recon (regenera con el gen actualizado)"); sys.exit(2)
    ok = process(c, args.lake_file, args.staging, args.backup, args.dry)
    if not ok and not args.dry:
        log("[FATAL] gate falló -> ABORTO"); sys.exit(2)
    log(f"[FIN] ok={ok} dry={args.dry}")

if __name__ == "__main__":
    main()
