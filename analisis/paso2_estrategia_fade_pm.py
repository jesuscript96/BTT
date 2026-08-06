"""
PASO 2 -- Backtest "a mano" de la estrategia que definio el usuario,
ejecutado dos veces sobre los mismos datos y las mismas reglas:

  Version A: universo completo, tal cual esta hoy.
  Version B: igual, pero descartando dias sospechosos de split
             (registrados en `splits` O ratio prev_close/open >= 10).

Reglas EXACTAS (no se ha anadido ningun filtro/valor no especificado):
  Sesion:    04:00 (PM) hasta 11:00 (parte de RTH), nunca mas alla.
  Universo:  PMH Gap >= 50%  Y  precio de open en PM > $1.
  Direccion: corto.
  Entrada:   primera vela M1, dentro de 05:00-08:00, donde
             close < close de la vela M1 anterior.
             Se entra al precio de cierre de esa vela.
  Stop:      30% por encima del precio de entrada (short).
  Salida:    a las 11:00 si no salto el stop antes.
  Riesgo:    1R fijo (R = (entry-exit) / (entry*0.30)).
  Periodo:   ultimos 12 meses (eleccion propia, dejada abierta por el usuario).

No toca nada del codigo de Edgecute. Solo lectura de GCS.
"""

import os
import duckdb
import pandas as pd
from dotenv import load_dotenv

ENV_PATH = os.path.join(os.path.dirname(__file__), "..", "backend", ".env")
load_dotenv(ENV_PATH)
GCS_BUCKET = os.getenv("GCS_BUCKET", "strategybuilderbbdd")

con = duckdb.connect()
con.execute("INSTALL httpfs; LOAD httpfs;")
con.execute(
    f"CREATE SECRET gcs_secret (TYPE GCS, KEY_ID '{os.getenv('GCS_HMAC_KEY')}', "
    f"SECRET '{os.getenv('GCS_HMAC_SECRET')}');"
)
con.execute("SET memory_limit='6GB';")

MONTHS = [(2025, m) for m in range(8, 13)] + [(2026, m) for m in range(1, 8)]
STOP_PCT = 0.30
ENTRY_WINDOW = ("05:00:00", "08:00:00")
EXIT_TIME = "11:00:00"

# ------------------------------------------------------------------
# 1) Universo de candidatos: PMH Gap >= 50%, open PM > $1, tipo CS/ADRC/OS
# ------------------------------------------------------------------
all_candidates = []
for y, m in MONTHS:
    dm_path = f"gs://{GCS_BUCKET}/cold_storage/daily_metrics/year={y}/month={m}/*.parquet"
    df = con.execute(f"""
        SELECT dm.ticker, CAST(dm.timestamp AS DATE) AS fecha, dm.pmh_gap_pct,
               dm.open AS open_pm, dm.prev_close
        FROM read_parquet('{dm_path}') dm
        JOIN read_parquet('gs://{GCS_BUCKET}/cold_storage/tickers/*.parquet') t
            ON dm.ticker = t.ticker
        WHERE t.type IN ('CS','ADRC','OS')
          AND dm.pmh_gap_pct >= 50 AND dm.open > 1
    """).fetchdf()
    df["fecha"] = pd.to_datetime(df["fecha"]).dt.date  # normalizar: DuckDB DATE -> Timestamp por defecto
    df["year"] = y
    df["month"] = m
    all_candidates.append(df)

candidatos = pd.concat(all_candidates, ignore_index=True)
print(f"Candidatos totales (12m): {len(candidatos)}")

# ------------------------------------------------------------------
# 2) Marcar dias sospechosos de split: registrados en `splits` O
#    ratio prev_close/open >= 10 (mismo criterio usado en el resto
#    de esta investigacion).
# ------------------------------------------------------------------
splits_df = con.execute(f"""
    SELECT ticker, CAST(execution_date AS DATE) AS fecha
    FROM read_parquet('gs://{GCS_BUCKET}/cold_storage/splits/*.parquet')
""").fetchdf()
splits_df["fecha"] = pd.to_datetime(splits_df["fecha"]).dt.date
splits_set = set(zip(splits_df["ticker"], splits_df["fecha"]))

candidatos["ratio_prevclose_open"] = candidatos.apply(
    lambda r: max(r["open_pm"] / r["prev_close"], r["prev_close"] / r["open_pm"])
    if r["prev_close"] and r["prev_close"] > 0 else 0, axis=1
)
candidatos["registrado_en_splits"] = candidatos.apply(
    lambda r: (r["ticker"], r["fecha"]) in splits_set, axis=1
)
candidatos["sospechoso_split"] = candidatos["registrado_en_splits"] | (candidatos["ratio_prevclose_open"] >= 10)
print(f"De esos, sospechosos de split: {candidatos['sospechoso_split'].sum()}")

# ------------------------------------------------------------------
# 3) Simulacion mes a mes: para cada candidato, velas de 04:00 a 11:00
# ------------------------------------------------------------------
trades = []

for (y, m), grupo in candidatos.groupby(["year", "month"]):
    id_path = f"gs://{GCS_BUCKET}/cold_storage/intraday_1m/year={y}/month={m}/*.parquet"
    tickers_mes = sorted(set(grupo["ticker"]))
    tickers_sql = "(" + ",".join(f"'{t}'" for t in tickers_mes) + ")"

    velas = con.execute(f"""
        SELECT ticker, date, timestamp, open, high, low, close
        FROM read_parquet('{id_path}')
        WHERE ticker IN {tickers_sql}
          AND CAST(timestamp AS TIME) >= TIME '04:00:00'
          AND CAST(timestamp AS TIME) <= TIME '{EXIT_TIME}'
        ORDER BY ticker, timestamp
    """).fetchdf()
    velas["date"] = pd.to_datetime(velas["date"]).dt.date
    velas["hora"] = velas["timestamp"].dt.time

    cand_set = set(zip(grupo["ticker"], grupo["fecha"]))
    for (ticker, fecha), dia_df in velas.groupby(["ticker", "date"]):
        if (ticker, fecha) not in cand_set:
            continue
        dia_df = dia_df.sort_values("timestamp").reset_index(drop=True)
        dia_df["close_prev"] = dia_df["close"].shift(1)

        # Buscar la PRIMERA vela dentro de 05:00-08:00 con close < close anterior
        en_ventana = dia_df[(dia_df["hora"] >= pd.to_datetime(ENTRY_WINDOW[0]).time()) &
                             (dia_df["hora"] <= pd.to_datetime(ENTRY_WINDOW[1]).time())]
        señal = en_ventana[en_ventana["close"] < en_ventana["close_prev"]]
        if señal.empty:
            continue
        entry_row = señal.iloc[0]
        entry_idx = entry_row.name
        entry_price = entry_row["close"]
        entry_time = entry_row["timestamp"]
        stop_price = entry_price * (1 + STOP_PCT)

        # Velas desde la entrada hasta las 11:00
        post = dia_df.loc[entry_idx:].copy()
        stop_hit = post[post["high"] >= stop_price]

        if not stop_hit.empty:
            exit_row = stop_hit.iloc[0]
            exit_price = stop_price
            exit_reason = "stop"
            exit_time = exit_row["timestamp"]
        else:
            exit_row = post.iloc[-1]  # ultima vela <= 11:00
            exit_price = exit_row["close"]
            exit_reason = "hora_11am"
            exit_time = exit_row["timestamp"]

        r_multiple = (entry_price - exit_price) / (entry_price * STOP_PCT)

        # Heuristica simple de "posible misprint": el stop salto por una vela
        # con high muy por encima de su propio close Y del close de la vela
        # siguiente (pico aislado de una sola vela, no un movimiento sostenido).
        posible_misprint = False
        if exit_reason == "stop":
            idx_pos = post.index.get_loc(exit_row.name)
            siguiente = post.iloc[idx_pos + 1] if idx_pos + 1 < len(post) else None
            spike_vs_close = exit_row["high"] / exit_row["close"] if exit_row["close"] > 0 else 1
            reviert = (siguiente is not None) and (siguiente["close"] < exit_row["high"] * 0.9)
            posible_misprint = (spike_vs_close >= 1.15) and reviert

        trades.append({
            "ticker": ticker, "fecha": fecha,
            "sospechoso_split": bool(cand_set and grupo[(grupo.ticker == ticker) & (grupo.fecha == fecha)]["sospechoso_split"].iloc[0]),
            "entry_time": entry_time, "entry_price": entry_price,
            "exit_time": exit_time, "exit_price": exit_price, "exit_reason": exit_reason,
            "stop_price": stop_price, "r_multiple": r_multiple,
            "posible_misprint_pm": posible_misprint,
        })
    print(f"  {y}-{m:02d}: {len(tickers_mes)} tickers candidatos procesados, {len(trades)} operaciones acumuladas", flush=True)

trades_df = pd.DataFrame(trades)
trades_df.to_csv(os.path.join(os.path.dirname(__file__), "paso2_trades_completos.csv"), index=False)
print(f"\nTotal operaciones generadas: {len(trades_df)}")
print(f"Guardado detalle en analisis/paso2_trades_completos.csv")


def resumen(df, nombre):
    print(f"\n{'='*20} {nombre} {'='*20}")
    print(f"Operaciones: {len(df)}")
    if len(df) == 0:
        return
    win_rate = (df["r_multiple"] > 0).mean() * 100
    print(f"Win rate: {win_rate:.1f}%")
    print(f"Resultado medio: {df['r_multiple'].mean():.3f}R")
    print(f"Suma total: {df['r_multiple'].sum():.2f}R")
    print("\nTop 5 operaciones mas rentables:")
    top5 = df.sort_values("r_multiple", ascending=False).head(5)
    print(top5[["ticker", "fecha", "r_multiple", "exit_reason", "sospechoso_split", "posible_misprint_pm"]].to_string(index=False))


resumen(trades_df, "VERSION A - universo completo")
resumen(trades_df[~trades_df["sospechoso_split"]], "VERSION B - excluyendo dias sospechosos de split")

print("\nDONE")
