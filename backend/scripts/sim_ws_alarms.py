"""Simulador de WebSocket para las alarmas del Screener (Fase 2 · docs/alerts).

Reinyecta las barras históricas de un ticker/día como si llegaran por el WS de
Massive, alimentando el MISMO live screener que usa producción, para poder
ejercitar el camino en vivo OFFLINE y de forma repetible — sin depender del
único WS de prod ni tocar nada.

Reproduce BUG A (docs/alerts/F1_BUG_A_REPRODUCCION.md): el `pre_high` (máximo de
premarket) es solo-memoria sin backfill, así que si el backend arranca DESPUÉS
del máximo real, el `pmh_gap_pct` sale bajo y el ticker se cae del filtro de
universo → la alarma nunca dispara.

Cómo funciona (interfaz del WS, verificada en live_screener_service.py):
  * Punto de inyección: `LiveScreenerService._apply_aggregate(ev)`. NO se abre un
    WS real y NUNCA se llama a `.start()` (eso arrancaría el consumidor real del
    WS y pelearía con prod → cierre 1008).
  * Evento: {"ev":"AM","sym":T,"o/h/l/c":..,"v":..,"s":<epoch ms UTC>}.
  * La sesión (pre/rth/after) la decide el TIMESTAMP del evento (`_ts_window`:
    ms→ET, premarket 04:00–09:30), no el reloj de pared. Solo hay que evitar el
    estado "closed" (se fuerza `_session="pre"`) y estar en la allowlist +
    tener `prev_close` sembrado.

Uso (local o staging, donde el entorno ya trae las libs):
    python -m scripts.sim_ws_alarms BAOS 2026-09-04
    python -m scripts.sim_ws_alarms BAOS 2026-09-04 --gap 50 --late 05:00

Nota: por `docker exec` ad-hoc en prod hay que pasar el LD_LIBRARY_PATH de Nixpacks
(gcc-lib) o `import duckdb` falla por libstdc++.
"""
from __future__ import annotations

import argparse
import datetime as dt
from typing import Any, Dict, List, Optional

from app.database import get_db_connection
from app.services.live_screener_service import LiveScreenerService, TickerLiveState, ET
from app.services.alarms.engine import evaluate, normalize_conditions

try:                                     # contexto idéntico al que arma el motor
    from app.services.alarms.engine import _instant_ctx
except Exception:                        # pragma: no cover
    _instant_ctx = None


def _load_prev_close(con, ticker: str, d: dt.date) -> Optional[float]:
    row = con.execute(
        """SELECT prev_close, pm_high FROM daily_metrics
           WHERE ticker=? AND year=? AND month=? AND CAST(timestamp AS DATE)=?""",
        [ticker, d.year, d.month, d],
    ).fetchone()
    return (row[0] if row else None)


def _load_premarket_bars(con, ticker: str, d: dt.date) -> List[Any]:
    return con.execute(
        """SELECT timestamp, open, high, low, close, volume
           FROM intraday_1m
           WHERE ticker=? AND year=? AND month=? AND date=?
             AND CAST(timestamp AS TIME) >= TIME '04:00:00'
             AND CAST(timestamp AS TIME) <  TIME '09:30:00'
           ORDER BY timestamp""",
        [ticker, d.year, d.month, d],
    ).fetchall()


def _to_event(bar, ticker: str) -> Dict[str, Any]:
    ms = int(bar[0].replace(tzinfo=ET).timestamp() * 1000)
    return {"ev": "AM", "sym": ticker,
            "o": bar[1], "h": bar[2], "l": bar[3], "c": bar[4], "v": bar[5], "s": ms}


def feed(ticker: str, prev_close: float, bars: List[Any], gap_threshold: float,
         backfill_bars: Optional[List[Any]] = None):
    """Alimenta un live screener AISLADO con las barras y devuelve el veredicto
    del filtro de universo `pmh_gap_pct > gap_threshold`.

    Si `backfill_bars` se pasa y el código trae el fix (F3.1), tras alimentar
    aplica `_fold_bars_into_state` con esas barras (backfill REST simulado) para
    comprobar que el ticker se recupera del universo."""
    svc = LiveScreenerService()          # instancia aislada; jamás .start()
    svc._session = "pre"                 # evita el gate 'closed'
    svc._allowlist.add(ticker)           # gate de allowlist
    st = TickerLiveState(ticker=ticker)
    st.prev_close = prev_close
    svc._states[ticker] = st
    for b in bars:
        svc._apply_aggregate(_to_event(b, ticker))
    if backfill_bars is not None and hasattr(svc, "_fold_bars_into_state"):
        svc._fold_bars_into_state(ticker, [_to_event(b, ticker) for b in backfill_bars])

    m = next((x for x in svc.snapshot_metrics() if x.get("ticker") == ticker), None)
    pre_pct = (m or {}).get("pre_pct")
    plan = normalize_conditions([{"left": "pmh_gap_pct", "op": ">", "right": gap_threshold}])
    ctx = _instant_ctx(m) if (_instant_ctx and m) else {"pmh_gap_pct": pre_pct}
    ok, _ = evaluate(plan, ctx)
    return {"n_bars": len(bars), "pre_high": st.pre_high, "last": st.last_price,
            "pmh_gap": pre_pct, "universe_pass": bool(ok)}


def main() -> None:
    ap = argparse.ArgumentParser(description="Simulador de WS para alarmas (reproduce BUG A).")
    ap.add_argument("ticker")
    ap.add_argument("date", help="YYYY-MM-DD")
    ap.add_argument("--gap", type=float, default=50.0, help="umbral PM High Gap del universo")
    ap.add_argument("--late", default="05:00", help="hora de arranque tardío HH:MM (escenario B)")
    ap.add_argument("--prev-close", type=float, default=None, help="override de prev_close")
    args = ap.parse_args()

    d = dt.date.fromisoformat(args.date)
    con = get_db_connection()
    prev_close = args.prev_close or _load_prev_close(con, args.ticker, d)
    if not prev_close:
        raise SystemExit(f"sin prev_close para {args.ticker} {d} (pásalo con --prev-close)")
    bars = _load_premarket_bars(con, args.ticker, d)
    if not bars:
        raise SystemExit(f"sin barras de premarket para {args.ticker} {d}")

    lh, lm = (int(x) for x in args.late.split(":"))
    late_bars = [b for b in bars if b[0].time() >= dt.time(lh, lm)]

    print(f"{args.ticker} {d} | prev_close={prev_close} | barras premarket={len(bars)} "
          f"({bars[0][0].time()}→{bars[-1][0].time()}) | universo pmh_gap>{args.gap}")

    a = feed(args.ticker, prev_close, bars, args.gap)
    print(f"\n[A] arranca 04:00 (premarket completo): pre_high={a['pre_high']} "
          f"pmh_gap={a['pmh_gap']} -> universo {'PASA (dispararia)' if a['universe_pass'] else 'CAE (no dispara)'}")

    b = feed(args.ticker, prev_close, late_bars, args.gap)
    print(f"[B] arranca {args.late} (deploy a media premarket): pre_high={b['pre_high']} "
          f"pmh_gap={b['pmh_gap']} -> universo {'PASA (dispararia)' if b['universe_pass'] else 'CAE (no dispara)'}")

    if a["universe_pass"] and not b["universe_pass"]:
        print("\n==> BUG A reproducido: el arranque tardío pierde el pre_high real y el ticker cae del universo.")
    else:
        print("\n==> No se reprodujo el contraste esperado (revisar datos/umbral).")

    # Escenario C: arranque tardío + FIX (F3.1). Solo si el código trae el backfill.
    if hasattr(LiveScreenerService, "_fold_bars_into_state"):
        c = feed(args.ticker, prev_close, late_bars, args.gap, backfill_bars=bars)
        print(f"[C] {args.late} + FIX (backfill REST de todo el día): pre_high={c['pre_high']} "
              f"pmh_gap={c['pmh_gap']} -> universo {'PASA (arreglado)' if c['universe_pass'] else 'CAE'}")
        if c["universe_pass"]:
            print("==> FIX verificado: el backfill recupera el pre_high real y el ticker vuelve al universo.")


if __name__ == "__main__":
    main()
