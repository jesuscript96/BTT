"""Verificar CUÁNDO salta una alarma, minuto a minuto, sobre un día real.

Responde a la pregunta «¿avisa en el momento adecuado?». Corre un día histórico
por el MISMO motor que en vivo (SessionBars + evaluator) e imprime, para cada
barra cerrada, los valores que ve la alarma y si dispararía. Así se ve el BORDE:
el minuto justo antes NO cumple, el del evento SÍ. Si disparara tarde, pronto o
de más, se vería aquí.

No es un backtest: no simula ejecuciones ni rendimiento. Solo el instante y el
precio del aviso, para cotejarlos contra un gráfico que ya conoces.

Uso:
  python -m scripts.trace_alarm LGHL 2026-07-27 "close crosses_above vwap"
  python -m scripts.trace_alarm TSLA 2026-07-27 "close < prev_bar_low" --from 09:30 --to 10:00
  python -m scripts.trace_alarm ABCD 2026-07-27 "close > vwap;dollar_volume > 500000"

Condiciones: "campo op valor" separadas por ';' (se combinan con AND, igual que
la alarma). El valor puede ser un número o el nombre de otro campo.
"""
import argparse, asyncio, os, ssl, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import certifi, httpx
from dotenv import load_dotenv

load_dotenv(str(Path(__file__).resolve().parent.parent / ".env"))
from app.services.alarms.bars import SessionBars
from app.services.alarms.evaluator import normalize_conditions, evaluate, describe
from app.services.alarms import fields as F

KEY = os.getenv("MASSIVE_API_KEY", "")
BASE = os.getenv("MASSIVE_API_BASE_URL", "https://api.massive.com")


def _f(v):
    try: return float(v)
    except (TypeError, ValueError): return None


def _mins(hhmm):
    if not hhmm: return None
    h, m = hhmm.split(":"); return int(h) * 60 + int(m)


def _parse(spec):
    out = []
    for part in spec.split(";"):
        toks = part.split()
        if len(toks) != 3:
            raise SystemExit(f"Condición mal formada: «{part}» (esperado: campo op valor)")
        out.append({"left": toks[0], "op": toks[1], "right": toks[2]})
    return out


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ticker"); ap.add_argument("date")
    ap.add_argument("conditions")
    ap.add_argument("--from", dest="lo", default=None)
    ap.add_argument("--to", dest="hi", default=None)
    a = ap.parse_args()

    conds = normalize_conditions(_parse(a.conditions))
    lo, hi = _mins(a.lo) or 0, _mins(a.hi) or 1439
    # Campos que se imprimen: los que aparecen en las condiciones.
    cols = []
    for c in conds:
        cols += [c["left"]] + ([c["right_field"]] if c.get("right_field") else [])
    cols = list(dict.fromkeys(cols))

    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get(f"{BASE}/v2/aggs/ticker/{a.ticker}/range/1/minute/{a.date}/{a.date}",
                             params={"apiKey": KEY, "adjusted": "true", "sort": "asc", "limit": 50000})
        rows = r.json().get("results") or []
    if not rows:
        raise SystemExit(f"Sin barras de {a.ticker} el {a.date}.")

    print(f"\n{a.ticker} {a.date} — {' Y '.join(describe(c) for c in conds)}")
    header = f"{'hora':>6} " + " ".join(f"{c[:11]:>11}" for c in cols) + "   ¿SALTA?"
    print(header); print("-" * len(header))

    s = SessionBars(a.ticker, a.date)
    fires = 0
    for row in rows:
        ts = row.get("t")
        if ts is None: continue
        bar = s.ingest(int(ts), _f(row.get("o")), _f(row.get("h")), _f(row.get("l")),
                       _f(row.get("c")), _f(row.get("v")))
        if bar is None: continue
        m = bar["minute"]
        if not (lo <= m <= hi): continue
        ctx = s.snapshot()
        ok, _ = evaluate(conds, ctx, prev_lookup=s.prev_snapshot_value)
        vals = " ".join(f"{(ctx.get(c) if ctx.get(c) is not None else float('nan')):>11.4f}" for c in cols)
        mark = "  <<< SALTA" if ok else ""
        print(f"{m//60:02d}:{m%60:02d} {vals}{mark}")
        fires += int(ok)
    print(f"\nTotal: {fires} disparo(s) en la ventana.")


if __name__ == "__main__":
    asyncio.run(main())
