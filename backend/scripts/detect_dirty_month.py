#!/usr/bin/env python3
"""Detecta ticker-días con misprints premarket AÚN sucios en el lake, por SPREAD
(método de Augus), SIN filtro de gap — así cazamos los de bajo gap (p.ej. LIFW
2024-07-23, gap -0,35%) que el universo gap>=5 dejaba fuera.

Criterio = idéntico al detector del gen: barra PM (04:00-09:30 NY) con open>0 y
(high-low)/open*100 > SPREAD_LIMIT. Restringe a CS/ADRC (scope acordado del método).
NO filtra por gap ni por día de split (el spread intrabar no lo crean los splits; la
validación NBBO del gen es el árbitro). Barato: solo lee el lake local + tickers de GCS.

Salida: CSV con cabecera Ticker,Date (lo que come el gen con --csv).
"""
import os, sys, glob, csv, argparse, duckdb

SPREAD = float(os.getenv("SPREAD_LIMIT", "5.0"))
BUCKET = os.environ.get("GCS_BUCKET", "strategybuilderbbdd")


def lake_files(root, y, mo):
    return sorted(glob.glob(f"{root}/year={y}/month={mo}/*.parquet"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lake-root", default="/lake/cold_storage/intraday_1m")
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--month", type=int, required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--no-type-filter", action="store_true", help="no restringir a CS/ADRC")
    args = ap.parse_args()

    files = lake_files(args.lake_root, args.year, args.month)
    if not files:
        print(f"[DETECT {args.year}-{args.month}] sin ficheros de lake"); sys.exit(1)
    flist = ",".join("'" + f + "'" for f in files)

    c = duckdb.connect(); c.execute("SET memory_limit='6GB'; SET threads=4;")
    typ_join = ""
    if not args.no_type_filter:
        c.execute("INSTALL httpfs; LOAD httpfs;")
        c.execute(f"CREATE SECRET g (TYPE GCS, KEY_ID '{os.environ['GCS_HMAC_KEY']}', "
                  f"SECRET '{os.environ['GCS_HMAC_SECRET']}');")
        typ_join = (f"JOIN (SELECT DISTINCT ticker, type FROM "
                    f"read_parquet('gs://{BUCKET}/cold_storage/tickers/*.parquet')) tk "
                    f"ON pm.ticker = tk.ticker AND tk.type IN ('CS','ADRC')")

    q = f"""
    WITH pm AS (
      SELECT DISTINCT ticker, CAST(timestamp AS DATE) AS d
      FROM read_parquet([{flist}])
      WHERE open > 0
        AND (extract(hour FROM timestamp)*60 + extract(minute FROM timestamp)) BETWEEN 240 AND 569
        AND (high - low)/open*100 > {SPREAD}
    )
    SELECT DISTINCT pm.ticker AS Ticker, CAST(pm.d AS VARCHAR) AS Date
    FROM pm {typ_join}
    ORDER BY 1, 2
    """
    rows = c.execute(q).fetchall(); c.close()
    with open(args.out, "w", newline="") as fh:
        w = csv.writer(fh); w.writerow(["Ticker", "Date"])
        for r in rows: w.writerow([r[0], r[1]])
    print(f"[DETECT {args.year}-{args.month}] {len(rows)} ticker-días sucios (spread>{SPREAD}%) -> {args.out}")


if __name__ == "__main__":
    main()
