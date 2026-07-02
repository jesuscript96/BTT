"""
Slab builder — construye el caché mensual columnar (PRD rendimiento-backtester §03.5).

Un slab por (kind, year, month):
  {BTT_SLAB_DIR}/v1/{kind}/{year}/{month:02d}/slab.arrow    Arrow IPC SIN compresión (mmap)
  .../index.parquet                                          (ticker, date, row_start, row_end, n_rows)
  .../manifest.json                                          metadatos/validez

Garantías del slab (contrato):
  - Orden global estable (ticker, date, ts_ns) ascendente.
  - Deduplicado por (ticker, date, ts_ns) conservando la PRIMERA fila del orden estable —
    réplica exacta del sort_values("timestamp").drop_duplicates(keep="first") por par
    que hoy hace _preprocess_pair (backtest_signals.py).
  - Slices por par contiguos: [row_start, row_end) del índice.
  - Dtypes: ts_ns int64 · open/high/low/close float32 · volume int32 (paridad con el
    downcast del caché actual, gcs_cache._downcast_intraday).

La escritura es atómica: los tres ficheros se escriben como .tmp y se publican con
os.replace, el manifest EN ÚLTIMO LUGAR (su presencia marca el slab como válido).
"""
import json
import logging
import os
import threading
import time

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.ipc as pa_ipc

logger = logging.getLogger("backtester.slab")

SCHEMA_VERSION = 1

_SLAB_SCHEMA = pa.schema([
    ("ts_ns", pa.int64()),
    ("open", pa.float32()),
    ("high", pa.float32()),
    ("low", pa.float32()),
    ("close", pa.float32()),
    ("volume", pa.int32()),
])


def slab_root() -> str:
    from app.db.gcs_cache import LOCAL_CACHE_DIR
    return os.getenv("BTT_SLAB_DIR", os.path.join(LOCAL_CACHE_DIR, "slabs"))


def slab_dir(kind: str, year: int, month: int) -> str:
    return os.path.join(slab_root(), f"v{SCHEMA_VERSION}", kind, str(year), f"{month:02d}")


def slab_paths(kind: str, year: int, month: int) -> dict:
    d = slab_dir(kind, year, month)
    return {
        "dir": d,
        "slab": os.path.join(d, "slab.arrow"),
        "index": os.path.join(d, "index.parquet"),
        "manifest": os.path.join(d, "manifest.json"),
    }


def _normalize_month_df(df: pd.DataFrame) -> pd.DataFrame:
    """Orden estable + dedup con la semántica EXACTA del pipeline actual."""
    out = pd.DataFrame({
        "ticker": df["ticker"].astype(str),
        "date": df["date"].astype(str).str[:10],
        "ts_ns": pd.to_datetime(df["timestamp"]).values.astype("datetime64[ns]").astype(np.int64),
        "open": df["open"].astype(np.float32),
        "high": df["high"].astype(np.float32),
        "low": df["low"].astype(np.float32),
        "close": df["close"].astype(np.float32),
        "volume": pd.to_numeric(df["volume"], errors="coerce").fillna(0).astype(np.int32),
    })
    # kind="stable" preserva el orden fuente entre filas con la misma clave → el
    # drop_duplicates(keep="first") elige la MISMA fila que elegiría el path actual.
    out = out.sort_values(["ticker", "date", "ts_ns"], kind="stable")
    out = out.drop_duplicates(subset=["ticker", "date", "ts_ns"], keep="first")
    return out.reset_index(drop=True)


def _build_index(norm: pd.DataFrame) -> pd.DataFrame:
    """Rangos contiguos [row_start, row_end) por (ticker, date), en orden físico."""
    if norm.empty:
        return pd.DataFrame(columns=["ticker", "date", "row_start", "row_end", "n_rows"])
    key = norm["ticker"].values.astype(object) + "|" + norm["date"].values.astype(object)
    change = np.empty(len(key), dtype=bool)
    change[0] = True
    change[1:] = key[1:] != key[:-1]
    starts = np.flatnonzero(change)
    ends = np.append(starts[1:], len(key))
    return pd.DataFrame({
        "ticker": norm["ticker"].values[starts],
        "date": norm["date"].values[starts],
        "row_start": starts.astype(np.int64),
        "row_end": ends.astype(np.int64),
        "n_rows": (ends - starts).astype(np.int32),
    })


def _atomic_publish(tmp_path: str, final_path: str) -> None:
    os.replace(tmp_path, final_path)


def build_month_from_df(
    df: pd.DataFrame, kind: str, year: int, month: int,
    source_desc: str = "df", out_root: str | None = None,
) -> dict | None:
    """Construye el slab de un mes desde un DataFrame crudo (cualquier orden, con dups).

    Devuelve el manifest dict, o None si el mes queda vacío.
    Columnas requeridas del df: ticker, date, timestamp, open, high, low, close, volume.
    """
    t0 = time.time()
    if df is None or df.empty:
        logger.info(f"[SLAB] {kind} {year}-{month:02d}: fuente vacía, no se construye")
        return None

    norm = _normalize_month_df(df)
    index = _build_index(norm)

    paths = slab_paths(kind, year, month)
    if out_root is not None:
        d = os.path.join(out_root, f"v{SCHEMA_VERSION}", kind, str(year), f"{month:02d}")
        paths = {"dir": d, "slab": os.path.join(d, "slab.arrow"),
                 "index": os.path.join(d, "index.parquet"),
                 "manifest": os.path.join(d, "manifest.json")}
    os.makedirs(paths["dir"], exist_ok=True)

    table = pa.Table.from_arrays(
        [
            pa.array(norm["ts_ns"].values, type=pa.int64()),
            pa.array(norm["open"].values, type=pa.float32()),
            pa.array(norm["high"].values, type=pa.float32()),
            pa.array(norm["low"].values, type=pa.float32()),
            pa.array(norm["close"].values, type=pa.float32()),
            pa.array(norm["volume"].values, type=pa.int32()),
        ],
        schema=_SLAB_SCHEMA,
    )

    suffix = f".tmp.{os.getpid()}.{threading.get_ident()}"
    tmp_slab = paths["slab"] + suffix
    tmp_index = paths["index"] + suffix
    tmp_manifest = paths["manifest"] + suffix
    try:
        # IPC file SIN compresión → memory-map zero-copy en lectura.
        with pa.OSFile(tmp_slab, "wb") as sink:
            with pa_ipc.new_file(sink, _SLAB_SCHEMA) as writer:
                writer.write_table(table)
        index.to_parquet(tmp_index, index=False)

        manifest = {
            "schema_version": SCHEMA_VERSION,
            "kind": kind, "year": int(year), "month": int(month),
            "source": source_desc,
            "n_rows": int(len(norm)), "n_pairs": int(len(index)),
            "built_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "duckdb_version": _duckdb_version(),
        }
        with open(tmp_manifest, "w") as f:
            json.dump(manifest, f)

        _atomic_publish(tmp_slab, paths["slab"])
        _atomic_publish(tmp_index, paths["index"])
        _atomic_publish(tmp_manifest, paths["manifest"])  # el manifest publica el slab
        logger.info(
            f"[SLAB] {kind} {year}-{month:02d}: {len(norm):,} filas, {len(index):,} pares "
            f"({round(time.time()-t0, 2)}s)"
        )
        return manifest
    except Exception:
        for p in (tmp_slab, tmp_index, tmp_manifest):
            try:
                if os.path.exists(p):
                    os.remove(p)
            except OSError:
                pass
        raise


def _duckdb_version() -> str:
    try:
        import duckdb
        return duckdb.__version__
    except Exception:
        return "-"


def build_month_from_parquet_glob(
    source_glob: str, kind: str, year: int, month: int,
    hive_filter: bool = True, out_root: str | None = None,
) -> dict | None:
    """Construye el slab leyendo parquet vía DuckDB (GCS o disco local).

    La MISMA función sirve para la fuente GCS de hoy y para la réplica local en el
    hardware propio (migración del CTO): solo cambia el glob (gs://... → /data/...).
    """
    import duckdb
    from app.db.connection import get_connection

    if source_glob.startswith("gs://") or source_glob.startswith("s3://"):
        conn = get_connection()  # conexión con httpfs+credenciales
    else:
        conn = duckdb.connect()
        conn.execute(f"SET threads={min(8, os.cpu_count() or 4)}")

    where = ""
    if hive_filter:
        where = (f"WHERE CAST(i.year AS INTEGER) = {int(year)} "
                 f"AND CAST(i.month AS INTEGER) = {int(month)}")
    sql = f"""
    SELECT i.ticker, i.date, i."timestamp", i.open, i.high, i.low, i."close", i.volume
    FROM read_parquet('{source_glob}', hive_partitioning=true) i
    {where}
    """
    t0 = time.time()
    df = conn.execute(sql).fetchdf()
    logger.info(f"[SLAB] fuente {kind} {year}-{month:02d}: {len(df):,} filas leídas "
                f"({round(time.time()-t0, 1)}s) de {source_glob}")
    return build_month_from_df(df, kind, year, month, source_desc=source_glob, out_root=out_root)


def build_month_from_ticker_cache(
    year: int, month: int, kind: str, out_root: str | None = None,
) -> dict | None:
    """Construye el slab desde el caché por-ticker existente ({CACHE_DIR}/{kind}/{y}/{mm}/*.parquet).

    Lee los ficheros en orden alfabético (determinista); el orden dentro de cada fichero
    se preserva → misma semántica keep-first que el path actual.
    """
    from app.db.gcs_cache import LOCAL_CACHE_DIR
    base = os.path.join(LOCAL_CACHE_DIR, kind, str(year), f"{month:02d}")
    if not os.path.isdir(base):
        return None
    parts = []
    for name in sorted(os.listdir(base)):
        if name.endswith(".parquet"):
            try:
                p = pd.read_parquet(os.path.join(base, name))
                if not p.empty:
                    parts.append(p)
            except Exception as e:
                logger.warning(f"[SLAB] no se pudo leer {name}: {e}")
    if not parts:
        return None
    df = pd.concat(parts, ignore_index=True)
    return build_month_from_df(df, kind, year, month,
                               source_desc=f"ticker_cache:{base}", out_root=out_root)
