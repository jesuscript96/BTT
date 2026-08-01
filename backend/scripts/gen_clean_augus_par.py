#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GENERA data limpia PERSISTIDA — método de Augus al pie de la letra, generalizado.
Reutiliza VERBATIM la lógica de /root/pilot/gen_clean_june.py (validada tol-0 en
junio): día COMPLETO 1m crudo de Massive, PREMARKET limpiado (spread>5% -> NBBO
±0.5% -> reconstrucción OHLC), RTH tal cual. Escribe UN parquet con el esquema
EXACTO del intraday_1m en un dir de staging.

Novedades vs junio:
  - Input dual:  --csv PATH  (validación: ticker-días de un CSV)  |  --month YYYY-MM
    (producción: universo gap_pct>=10 · tipos CS+ADRC · splits fuera, de daily_metrics)
  - Log de progreso por ticker-día + fichero JSON de estado (para la guardia horaria)
  - Idempotente por fichero de salida.
NO toca el lake ni prod: solo escribe el parquet de staging.
"""
import os, csv, sys, json, time, bisect, argparse, threading, warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
import pandas as pd, requests, duckdb
warnings.filterwarnings("ignore")

API_KEY  = os.environ["MASSIVE_API_KEY"]
BASE_URL = os.getenv("MASSIVE_API_BASE_URL", "https://api.polygon.io")
GCS_BUCKET = os.environ["GCS_BUCKET"]
SPREAD_LIMIT = 5.0
NBBO_LOW, NBBO_HIGH = 0.995, 1.005
PM_START = pd.to_datetime("04:00").time()
PM_END   = pd.to_datetime("09:30").time()
SLEEP_MIN, SLEEP_TKR = 0.15, 0.3
CLUSTER_GAP_MIN = int(os.getenv("AUGUS_CLUSTER_GAP_MIN", "15"))  # windowed: agrupa marcadas a <=N min
MAX_RPS = float(os.getenv("AUGUS_MAX_RPS", "80"))                 # techo global de requests/seg (soft ~100)
# Opción A (feedback cliente 2026-07-30): además del precio, reconstruye el VOLUMEN de la
# vela limpiada = suma de shares de los trades NBBO-válidos (fórmula Valeri/Augus). Así el
# pico de volumen de los misprints (p.ej. 8am) desaparece. transactions = nº de trades válidos,
# por coherencia. El volumen crudo queda preservado en los backups (_raw_backup + locales).
# Flag para poder generar staging "solo precio" (comparación A/B); por defecto ON.
CLEAN_VOLUME = os.getenv("AUGUS_CLEAN_VOLUME", "1") == "1"

PROGRESS = os.getenv("AUGUS_PROGRESS", "/root/backfill_logs/augus_progress.json")

# ── rate-limiter global (token bucket, thread-safe) ──────────────────────────
class _RateLimiter:
    def __init__(self, rps):
        self.rps = max(0.1, rps); self.cap = max(1.0, rps)
        self.tokens = self.cap; self.last = time.monotonic(); self.lock = threading.Lock()
    def acquire(self):
        while True:
            with self.lock:
                now = time.monotonic()
                self.tokens = min(self.cap, self.tokens + (now - self.last) * self.rps)
                self.last = now
                if self.tokens >= 1.0:
                    self.tokens -= 1.0; return
                wait = (1.0 - self.tokens) / self.rps
            time.sleep(wait)

_RL = None                        # se activa en main() solo si --workers > 1
def _rl():
    if _RL is not None: _RL.acquire()

# ── Augus funcs (VERBATIM de gen_clean_june.py) ──────────────────────────────
def _to_ny_naive(ms):
    return (pd.to_datetime(ms, unit="ms", utc=True)
            .dt.tz_convert("America/New_York").dt.tz_localize(None))
def _ny_naive_to_utc_ns(ts):
    return int(pd.Timestamp(ts).tz_localize("America/New_York").tz_convert("UTC").value)

def get_fullday_raw(ticker, date_str):
    url = f"{BASE_URL}/v2/aggs/ticker/{ticker}/range/1/minute/{date_str}/{date_str}"
    for a in range(4):
        try:
            _rl()
            r = requests.get(url, params={"apiKey": API_KEY, "adjusted": "false",
                             "sort": "asc", "limit": 50000}, verify=False, timeout=30)
        except Exception:
            time.sleep(1.0*(a+1)); continue
        if r.status_code == 200:
            res = r.json().get("results", [])
            if not res: return pd.DataFrame()
            df = pd.DataFrame(res).rename(columns={"t":"timestamp","o":"open","h":"high",
                "l":"low","c":"close","v":"volume","n":"transactions"})
            df["timestamp"] = _to_ny_naive(df["timestamp"])
            if "transactions" not in df: df["transactions"] = 0
            return df[["timestamp","open","high","low","close","volume","transactions"]]
        if r.status_code in (429,500,502,503,504): time.sleep(2.0*(a+1)); continue
        return pd.DataFrame()
    return pd.DataFrame()

def _paginated(url, ns_gte, ns_lt, max_pages=20):
    params = {"timestamp.gte":ns_gte,"timestamp.lt":ns_lt,"limit":50000,
              "order":"asc","sort":"timestamp","apiKey":API_KEY}
    out, nxt_url, use = [], url, params
    for _ in range(max_pages):
        payload=None
        for a in range(4):
            try: _rl(); r=requests.get(nxt_url,params=use,verify=False,timeout=40)
            except Exception: time.sleep(1.0*(a+1)); continue
            if r.status_code==200:
                try: payload=r.json(); break
                except ValueError: time.sleep(1.0*(a+1)); continue
            if r.status_code in (429,500,502,503,504): time.sleep(2.0*(a+1)); continue
            return out
        if payload is None: return out
        res=payload.get("results",[]); out.extend(res)
        nx=payload.get("next_url")
        if not nx or not res: break
        nxt_url, use = nx, {"apiKey":API_KEY}; time.sleep(0.2)
    return out

def _last_quote_before(ticker, ns0):
    try:
        _rl()
        r=requests.get(f"{BASE_URL}/v3/quotes/{ticker}",
            params={"timestamp.lt":ns0,"order":"desc","limit":1,"apiKey":API_KEY},
            verify=False,timeout=30)
        if r.status_code==200:
            res=r.json().get("results",[]); return res[0] if res else None
    except Exception: pass
    return None

def valid_nbbo_trades(trades, quotes):
    if not trades or not quotes: return None
    try:
        dt=pd.DataFrame(trades)[["price","size","sip_timestamp"]].sort_values("sip_timestamp")
        dq=pd.DataFrame(quotes)[["bid_price","ask_price","sip_timestamp"]].sort_values("sip_timestamp")
        m=pd.merge_asof(dt,dq,on="sip_timestamp",direction="backward").dropna(subset=["bid_price","ask_price"])
        m=m[(m["bid_price"]>0)&(m["ask_price"]>0)]
        ok=m[(m["price"]>=m["bid_price"]*NBBO_LOW)&(m["price"]<=m["ask_price"]*NBBO_HIGH)]
    except Exception: return None
    return ok if not ok.empty else None

def clean_ticker_day(ticker, date_str):
    df = get_fullday_raw(ticker, date_str)
    if df.empty: return None, 0, 0
    df = df.copy(); df["ticker"] = ticker
    df["vol_recon"] = False   # marca de vela con volumen reconstruido (Opción A estricta)
    flagged = cleaned = 0
    for idx, bar in df.iterrows():
        if not (PM_START <= bar["timestamp"].time() < PM_END): continue
        o = float(bar["open"])
        if o <= 0: continue
        if (float(bar["high"]) - float(bar["low"]))/o*100 <= SPREAD_LIMIT: continue
        flagged += 1
        minute = pd.Timestamp(bar["timestamp"])
        ns0=_ny_naive_to_utc_ns(minute); ns1=_ny_naive_to_utc_ns(minute+pd.Timedelta(minutes=1))
        trades=_paginated(f"{BASE_URL}/v3/trades/{ticker}",ns0,ns1)
        quotes=_paginated(f"{BASE_URL}/v3/quotes/{ticker}",ns0,ns1)
        lq=_last_quote_before(ticker,ns0)
        if lq: quotes=[lq]+quotes
        ok=valid_nbbo_trades(trades,quotes)
        if ok is None:
            time.sleep(SLEEP_MIN); continue
        high=float(ok["price"].max()); low=float(ok["price"].min())
        o0,c0=float(bar["open"]),float(bar["close"])
        no=o0 if low<=o0<=high else float(ok.iloc[0]["price"])
        nc=c0 if low<=c0<=high else float(ok.iloc[-1]["price"])
        if abs(high-float(bar["high"]))>1e-6 or abs(low-float(bar["low"]))>1e-6: cleaned+=1
        df.at[idx,"open"]=no; df.at[idx,"high"]=high; df.at[idx,"low"]=low; df.at[idx,"close"]=nc
        if CLEAN_VOLUME:  # Opción A: volumen/transactions solo de los trades NBBO-válidos
            df.at[idx,"volume"]=int(ok["size"].sum()); df.at[idx,"transactions"]=int(len(ok))
            df.at[idx,"vol_recon"]=True
        time.sleep(SLEEP_MIN)
    return df, flagged, cleaned

# ── WINDOWED (producción): 1 trades + 1 quotes por CLUSTER de marcadas ─────────
def _flagged_pm_minutes(df):
    """(idx, ts) de las barras PM con spread>SPREAD_LIMIT, orden temporal asc."""
    out = []
    for idx, bar in df.iterrows():
        t = bar["timestamp"]
        if not (PM_START <= t.time() < PM_END): continue
        o = float(bar["open"])
        if o <= 0: continue
        if (float(bar["high"]) - float(bar["low"]))/o*100 <= SPREAD_LIMIT: continue
        out.append((idx, pd.Timestamp(t)))
    out.sort(key=lambda x: x[1])
    return out

def _cluster_minutes(mins, gap_min):
    clusters, cur = [], []
    for it in mins:
        if cur and (it[1]-cur[-1][1]) > pd.Timedelta(minutes=gap_min):
            clusters.append(cur); cur=[]
        cur.append(it)
    if cur: clusters.append(cur)
    return clusters

def clean_ticker_day_windowed(ticker, date_str):
    """Idéntico a clean_ticker_day pero con pull WINDOWED por cluster. Para cada
    minuto marcado reconstruye EXACTAMENTE los inputs del per-barra (trades del
    minuto + quotes del minuto + última quote antes del minuto) desde la ventana
    ya bajada -> resultado bit-idéntico (tol-0), con muchas menos llamadas."""
    df = get_fullday_raw(ticker, date_str)
    if df.empty: return None, 0, 0
    df = df.copy(); df["ticker"] = ticker
    df["vol_recon"] = False   # marca de vela con volumen reconstruido (Opción A estricta)
    fmins = _flagged_pm_minutes(df)
    flagged = len(fmins); cleaned = 0
    if flagged == 0: return df, 0, 0
    for cluster in _cluster_minutes(fmins, CLUSTER_GAP_MIN):
        span0 = cluster[0][1]; span1 = cluster[-1][1] + pd.Timedelta(minutes=1)
        ns0 = _ny_naive_to_utc_ns(span0); ns1 = _ny_naive_to_utc_ns(span1)
        trades = _paginated(f"{BASE_URL}/v3/trades/{ticker}", ns0, ns1, max_pages=400)
        wq = _paginated(f"{BASE_URL}/v3/quotes/{ticker}", ns0, ns1, max_pages=400)
        prepend = _last_quote_before(ticker, ns0)
        wq_sorted = sorted(wq, key=lambda q: q["sip_timestamp"])
        wq_ts = [q["sip_timestamp"] for q in wq_sorted]
        for idx, minute in cluster:
            m0 = _ny_naive_to_utc_ns(minute); m1 = _ny_naive_to_utc_ns(minute + pd.Timedelta(minutes=1))
            tr_min = [t for t in trades if m0 <= t["sip_timestamp"] < m1]
            lo = bisect.bisect_left(wq_ts, m0); hi = bisect.bisect_left(wq_ts, m1)
            q_min = wq_sorted[lo:hi]
            q_before = wq_sorted[lo-1] if lo > 0 else prepend   # última quote antes del minuto
            quotes = ([q_before] if q_before else []) + q_min
            bar = df.loc[idx]
            ok = valid_nbbo_trades(tr_min, quotes)
            if ok is None: continue
            high = float(ok["price"].max()); low = float(ok["price"].min())
            o0, c0 = float(bar["open"]), float(bar["close"])
            no = o0 if low <= o0 <= high else float(ok.iloc[0]["price"])
            nc = c0 if low <= c0 <= high else float(ok.iloc[-1]["price"])
            if abs(high-float(bar["high"]))>1e-6 or abs(low-float(bar["low"]))>1e-6: cleaned += 1
            df.at[idx,"open"]=no; df.at[idx,"high"]=high; df.at[idx,"low"]=low; df.at[idx,"close"]=nc
            if CLEAN_VOLUME:  # Opción A: volumen/transactions solo de los trades NBBO-válidos
                df.at[idx,"volume"]=int(ok["size"].sum()); df.at[idx,"transactions"]=int(len(ok))
                df.at[idx,"vol_recon"]=True
        time.sleep(SLEEP_MIN)
    return df, flagged, cleaned

# ── universo por mes (producción) ────────────────────────────────────────────
def _ddb():
    c = duckdb.connect()
    c.execute("INSTALL httpfs; LOAD httpfs;")
    c.execute(f"SET s3_access_key_id='{os.environ['GCS_ACCESS_KEY_ID']}';")
    c.execute(f"SET s3_secret_access_key='{os.environ['GCS_SECRET_ACCESS_KEY']}';")
    c.execute("SET s3_endpoint='storage.googleapis.com'; SET s3_region='us-east-1'; SET s3_url_style='path';")
    return c

def universe_month(year, month):
    """Ticker-días del PDF: gap_pct>=10 · tipos CS+ADRC · splits fuera."""
    import os as _os
    _gmin=float(_os.environ.get("AUGUS_GAP_MIN","10"))
    _gmax=_os.environ.get("AUGUS_GAP_MAX","")
    _gclause=("dm.gap_pct >= %s"%_gmin)+((" AND dm.gap_pct < %s"%float(_gmax)) if _gmax else "")
    c = _ddb(); B = GCS_BUCKET
    dm = f"gs://{B}/cold_storage/daily_metrics/year={year}/month={month}/*.parquet"
    q = f"""
      SELECT dm.ticker AS ticker, CAST(dm.timestamp AS DATE) AS d
      FROM read_parquet('{dm}') dm
      JOIN (SELECT DISTINCT ticker,type FROM read_parquet('gs://{B}/cold_storage/tickers/*.parquet')) tk
        ON dm.ticker=tk.ticker AND tk.type IN ('CS','ADRC')
      WHERE {_gclause}
        AND NOT EXISTS (SELECT 1 FROM read_parquet('gs://{B}/cold_storage/splits/*.parquet') sp
                        WHERE sp.ticker=dm.ticker AND CAST(sp.execution_date AS DATE)=CAST(dm.timestamp AS DATE))
    """
    rows = c.execute(q).fetchdf()
    c.close()
    return [{"Ticker": r.ticker, "Date": str(pd.Timestamp(r.d).date())} for r in rows.itertuples()]

# ── progreso ─────────────────────────────────────────────────────────────────
def write_progress(d):
    try:
        os.makedirs(os.path.dirname(PROGRESS), exist_ok=True)
        json.dump(d, open(PROGRESS, "w"))
    except Exception:
        pass

def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--csv", help="CSV con columnas Ticker,Date (validación)")
    g.add_argument("--month", help="YYYY-MM (producción: universo del PDF)")
    ap.add_argument("--out", required=True, help="parquet de staging de salida")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--tag", default="augus")
    ap.add_argument("--window", action="store_true", help="pull windowed por cluster (producción)")
    ap.add_argument("--workers", type=int, default=1, help=">1 = paralelo (ThreadPool + rate-limit global)")
    args = ap.parse_args()
    clean_fn = clean_ticker_day_windowed if args.window else clean_ticker_day

    if args.csv:
        rows = list(csv.DictReader(open(args.csv)))
        y, m = 2026, 6
    else:
        y, m = [int(x) for x in args.month.split("-")]
        rows = universe_month(y, m)
    if args.limit: rows = rows[:args.limit]
    os.makedirs(os.path.dirname(args.out), exist_ok=True)

    started = time.time()
    n = len(rows)
    print(f"[GEN {args.tag}] {n} ticker-días -> {args.out} (workers={args.workers})", flush=True)
    frames=[]; tf=tc=0; done=0
    lock = threading.Lock()

    def record(tk, dt, df, f, c, err):
        nonlocal tf, tc, done
        with lock:
            done += 1; d = done
            if df is not None and not df.empty:
                frames.append(df); tf += f; tc += c
                print(f"  [{d}/{n}] {tk} {dt}: filas={len(df)} marcadas={f} limpiadas={c}", flush=True)
            elif err:
                print(f"  [{d}/{n}] {tk} {dt} ERROR: {err}", flush=True)
            else:
                print(f"  [{d}/{n}] {tk} {dt}: sin datos", flush=True)
            if d % 10 == 0 or d == n:
                el = time.time()-started
                write_progress({"tag": args.tag, "done": d, "total": n, "flagged": tf,
                                "cleaned_bars": tc, "current": f"{tk} {dt}",
                                "elapsed_s": round(el), "rate_td_per_h": round(d/el*3600, 1) if el>0 else 0})

    def work(r):
        tk, dt = r["Ticker"].strip(), r["Date"].strip()
        try:
            df, f, c = clean_fn(tk, dt); return tk, dt, df, f, c, None
        except Exception as e:
            return tk, dt, None, 0, 0, f"{type(e).__name__}: {str(e)[:80]}"

    if args.workers > 1:
        global _RL
        _RL = _RateLimiter(MAX_RPS)
        print(f"[paralelo] {args.workers} workers, rate-limit {MAX_RPS:.0f} req/s", flush=True)
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            for fut in as_completed([ex.submit(work, r) for r in rows]):
                record(*fut.result())
    else:
        for r in rows:
            record(*work(r)); time.sleep(SLEEP_TKR)

    if not frames:
        print("SIN DATOS, no se escribe"); return
    full = pd.concat(frames, ignore_index=True)
    full["date"] = pd.to_datetime(full["timestamp"]).dt.date
    full["month"] = m; full["year"] = y
    if "vol_recon" not in full.columns:
        full["vol_recon"] = False
    full = full[["ticker","volume","open","close","high","low","timestamp","transactions","date","month","year","vol_recon"]]
    con = duckdb.connect(); con.register("d", full)
    con.execute(f"""COPY (SELECT ticker, TRY_CAST(volume AS BIGINT) AS volume,
        open, close, high, low, CAST(timestamp AS TIMESTAMP) AS timestamp,
        transactions, date, month, year, COALESCE(vol_recon, FALSE) AS vol_recon FROM d) TO '{args.out}' (FORMAT PARQUET)""")
    con.close()
    el = time.time()-started
    write_progress({"tag": args.tag, "done": n, "total": n, "flagged": tf, "cleaned_bars": tc,
                    "current": "FIN", "elapsed_s": round(el),
                    "rate_td_per_h": round(n/el*3600, 1) if el>0 else 0, "fin": True})
    print(f"\n[FIN] ticker-días={len(frames)} filas={len(full):,} marcadas={tf:,} limpiadas={tc:,} {el:.0f}s -> {args.out}", flush=True)

if __name__ == "__main__":
    main()
