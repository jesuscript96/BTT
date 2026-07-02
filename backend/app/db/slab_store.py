"""
Slab store — lectura mmap zero-copy del caché mensual columnar (PRD §03.6).

API:
  get_month(kind, y, m) -> MonthSlab | None
  MonthSlab.slice(row_start, row_end) -> PairArrays (float64 upcast, ts int64)
  iter_slab_groups(qualifying_df, months, strategy_def, qual_lookup)
      -> yields (date, ticker, daily_stats, PairArrays)

`iter_slab_groups` reproduce la semántica del stream actual + _preprocess_pair:
  - orden de emisión: mes cronológico; dentro del mes, (date, ticker) lexicográfico;
  - exclude_days / exclude_months (idéntico a backtest_signals._preprocess_pair);
  - swing_option: concatena el/los día(s) lead desde el slab del mes que toque,
    re-ordena+dedup por ts (idéntico al concat+sort+dedup actual);
  - descarta pares con menos de 5 filas;
  - pares sin datos en el slab simplemente no se emiten (como el groupby actual).
"""
import datetime as _dt
import logging
import os
import threading

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.ipc as pa_ipc

from app.db.slab_builder import slab_paths

logger = logging.getLogger("backtester.slab")


class PairArrays:
    """Arrays de un par (ticker, día): vistas/upcasts listos para el motor."""
    __slots__ = ("ts_ns", "open", "high", "low", "close", "volume")

    def __init__(self, ts_ns, open_, high, low, close, volume):
        self.ts_ns = ts_ns          # int64[n]
        self.open = open_           # float64[n]
        self.high = high
        self.low = low
        self.close = close
        self.volume = volume        # float64[n]

    def __len__(self):
        return len(self.ts_ns)

    def timestamps_dt64(self):
        """Vista datetime64[ns] (zero-copy) para arrays['timestamp']."""
        return self.ts_ns.view("datetime64[ns]")

    def to_day_df(self, ticker: str, date: str) -> pd.DataFrame:
        """Reconstruye un day_df equivalente al del stream actual (para el path legacy
        de señales, que necesita DataFrame). float32/int32 como el caché real."""
        return pd.DataFrame({
            "ticker": ticker,
            "date": date,
            "timestamp": self.timestamps_dt64(),
            "open": self.open.astype(np.float32),
            "high": self.high.astype(np.float32),
            "low": self.low.astype(np.float32),
            "close": self.close.astype(np.float32),
            "volume": self.volume.astype(np.int32),
        })


class MonthSlab:
    """Un mes mapeado en memoria. Las columnas float32/int32 viven en el page cache;
    slice() copia SOLO el rango del par (upcast a float64 para el motor)."""

    def __init__(self, kind: str, year: int, month: int, paths: dict):
        self.kind, self.year, self.month = kind, year, month
        self._paths = paths
        self._mmap = pa.memory_map(paths["slab"], "r")
        table = pa_ipc.open_file(self._mmap).read_all().combine_chunks()

        # to_numpy(zero_copy_only=True) garantiza que NO se materializa una copia:
        # los arrays numpy referencian los buffers del mmap. Tras combine_chunks hay
        # exactamente 1 chunk por columna (0 si el slab está vacío).
        def _col(name):
            col = table.column(name)
            if col.num_chunks == 0:
                return np.empty(0, dtype=np.int64 if name == "ts_ns" else np.float32)
            return col.chunk(0).to_numpy(zero_copy_only=True)

        self._ts = _col("ts_ns")
        self._open = _col("open")
        self._high = _col("high")
        self._low = _col("low")
        self._close = _col("close")
        self._volume = _col("volume")
        self._index_df = pd.read_parquet(paths["index"])
        self._pair_map = {
            (t, d): (int(s), int(e))
            for t, d, s, e in zip(
                self._index_df["ticker"], self._index_df["date"],
                self._index_df["row_start"], self._index_df["row_end"],
            )
        }

    @property
    def n_rows(self) -> int:
        return len(self._ts)

    def pairs(self) -> pd.DataFrame:
        return self._index_df

    def lookup(self, ticker: str, date: str):
        """(row_start, row_end) o None si el par no está en el mes."""
        return self._pair_map.get((ticker, date))

    def slice(self, row_start: int, row_end: int) -> PairArrays:
        s = slice(row_start, row_end)
        return PairArrays(
            ts_ns=self._ts[s],  # int64: sin copia (vista)
            open_=self._open[s].astype(np.float64),
            high=self._high[s].astype(np.float64),
            low=self._low[s].astype(np.float64),
            close=self._close[s].astype(np.float64),
            volume=self._volume[s].astype(np.float64),
        )

    def slice_pair(self, ticker: str, date: str) -> PairArrays | None:
        rng = self.lookup(ticker, date)
        if rng is None:
            return None
        return self.slice(*rng)


# ── caché de slabs abiertos por proceso (también en cada worker forkserver) ──
_OPEN_SLABS: dict = {}
_OPEN_LOCK = threading.Lock()


def slab_exists(kind: str, year: int, month: int) -> bool:
    p = slab_paths(kind, year, month)
    return os.path.exists(p["manifest"]) and os.path.exists(p["slab"]) and os.path.exists(p["index"])


def get_month(kind: str, year: int, month: int) -> MonthSlab | None:
    """MonthSlab cacheado por proceso, o None si no hay slab válido publicado."""
    key = (kind, year, month)
    with _OPEN_LOCK:
        hit = _OPEN_SLABS.get(key)
    if hit is not None:
        return hit
    if not slab_exists(kind, year, month):
        return None
    try:
        slab = MonthSlab(kind, year, month, slab_paths(kind, year, month))
    except Exception as e:
        logger.warning(f"[SLAB] no se pudo abrir {kind} {year}-{month:02d}: {e}")
        return None
    with _OPEN_LOCK:
        _OPEN_SLABS[key] = slab
    return slab


def get_month_any_kind(year: int, month: int) -> MonthSlab | None:
    """Preferencia opt > raw (igual que _select_intraday_glob_for_month)."""
    return get_month("opt", year, month) or get_month("raw", year, month)


def _merge_swing_arrays(base: PairArrays, extras: list) -> PairArrays:
    """Concat + orden estable por ts + dedup keep-first — réplica del
    pd.concat + sort_values('timestamp') + drop_duplicates de _preprocess_pair."""
    ts = np.concatenate([base.ts_ns] + [e.ts_ns for e in extras])
    o = np.concatenate([base.open] + [e.open for e in extras])
    h = np.concatenate([base.high] + [e.high for e in extras])
    l = np.concatenate([base.low] + [e.low for e in extras])
    c = np.concatenate([base.close] + [e.close for e in extras])
    v = np.concatenate([base.volume] + [e.volume for e in extras])
    order = np.argsort(ts, kind="stable")
    ts, o, h, l, c, v = ts[order], o[order], h[order], l[order], c[order], v[order]
    keep = np.empty(len(ts), dtype=bool)
    if len(ts):
        keep[0] = True
        keep[1:] = ts[1:] != ts[:-1]
    return PairArrays(ts_ns=ts[keep], open_=o[keep], high=h[keep],
                      low=l[keep], close=c[keep], volume=v[keep])


def iter_slab_groups(qualifying_df, months, strategy_def, qual_lookup):
    """Itera pares desde slabs. months = [(year, month), ...] cronológico.

    Yields (date: str, ticker: str, daily_stats: dict, PairArrays).
    Los meses SIN slab no se emiten aquí — el caller decide el fallback legacy
    (iter_slab_groups_with_fallback en data_service se ocupa de eso).
    """
    from app.services.backtest_service import format_date_str

    rm = strategy_def.get("risk_management", {}) if strategy_def else {}
    exclude_active = rm.get("exclude_days_active", False)
    exclude_days = rm.get("exclude_days", []) if exclude_active else []
    exclude_months = rm.get("exclude_months", []) if exclude_active else []
    swing_opt = rm.get("swing_option", {}) if isinstance(rm, dict) else {}
    swing_active = swing_opt.get("active", False) if isinstance(swing_opt, dict) else False
    swing_target = swing_opt.get("target_day", "gap_1_day")
    apply_day = strategy_def.get("apply_day", "gap_day") if strategy_def else "gap_day"

    q_dates = pd.to_datetime(qualifying_df["date"])

    for (y, m) in months:
        slab = get_month_any_kind(y, m)
        if slab is None:
            continue
        mask = (q_dates.dt.year == y) & (q_dates.dt.month == m)
        vp = qualifying_df.loc[mask, ["ticker", "date"]].drop_duplicates()
        if vp.empty:
            continue
        vp = vp.copy()
        vp["date"] = pd.to_datetime(vp["date"]).dt.strftime("%Y-%m-%d")
        # Orden de emisión idéntico al groupby(["date","ticker"]) actual.
        vp = vp.sort_values(["date", "ticker"])

        for ticker, date in zip(vp["ticker"], vp["date"]):
            ticker = str(ticker)
            # exclusiones temporales (misma lógica que _preprocess_pair)
            if exclude_days or exclude_months:
                try:
                    dt = _dt.datetime.strptime(date, "%Y-%m-%d")
                    if dt.weekday() in exclude_days:
                        continue
                    if (dt.month - 1) in exclude_months:
                        continue
                except Exception as e:
                    logger.warning(f"Error parsing date {date} for temporal exclusion: {e}")

            arrs = slab.slice_pair(ticker, date)
            if arrs is None:
                continue  # el par no tiene datos este mes (como el groupby actual)

            daily_stats = qual_lookup.get((ticker, date), {})

            if swing_active:
                dates_to_fetch = []
                if apply_day == "gap_day":
                    if swing_target in ("gap_1_day", "gap_2_day"):
                        t1 = daily_stats.get("lead_timestamp_1")
                        if t1 is not None and not pd.isna(t1):
                            dates_to_fetch.append(t1)
                    if swing_target == "gap_2_day":
                        t2 = daily_stats.get("lead_timestamp_2")
                        if t2 is not None and not pd.isna(t2):
                            dates_to_fetch.append(t2)
                elif apply_day == "gap_1_day" and swing_target == "gap_2_day":
                    t2 = daily_stats.get("lead_timestamp_2")
                    if t2 is not None and not pd.isna(t2):
                        dates_to_fetch.append(t2)

                extras = []
                for d_val in dates_to_fetch:
                    d_str = format_date_str(d_val)
                    if not d_str:
                        continue
                    sy, sm = int(d_str[:4]), int(d_str[5:7])
                    s_slab = slab if (sy, sm) == (y, m) else get_month_any_kind(sy, sm)
                    if s_slab is None:
                        continue  # equivalente al cache-miss actual (no concat)
                    extra = s_slab.slice_pair(ticker, d_str)
                    if extra is not None and len(extra):
                        extras.append(extra)
                if extras:
                    arrs = _merge_swing_arrays(arrs, extras)

            if len(arrs) < 5:
                continue

            yield date, ticker, daily_stats, arrs


def months_spanned_by_qualifying(qualifying_df) -> list:
    dates = pd.to_datetime(qualifying_df["date"])
    return sorted(set(zip(dates.dt.year.astype(int), dates.dt.month.astype(int))))


def ensure_slabs_from_ticker_cache(months, kind: str = "opt") -> int:
    """Construye (si faltan) los slabs de los meses dados desde el caché por-ticker.
    Devuelve cuántos construyó. Es el mismo build one-time que hará el sync nightly."""
    from app.db.slab_builder import build_month_from_ticker_cache
    built = 0
    for (y, m) in months:
        if not slab_exists(kind, y, m):
            if build_month_from_ticker_cache(y, m, kind) is not None:
                built += 1
    return built


def iter_slab_groups_bench(qualifying_df, qual_lookup, strategy_def, months):
    """Hook para scripts/bench_e2e.py: lista materializada de pares slab.
    Requiere slabs ya construidos (ensure_slabs_from_ticker_cache)."""
    return [
        (date, ticker, daily_stats, arrs)
        for date, ticker, daily_stats, arrs in iter_slab_groups(
            qualifying_df, months, strategy_def, qual_lookup)
    ]
