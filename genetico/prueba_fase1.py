"""Fase 1 — prueba de aceptacion: N individuos al azar, evaluados por el
motor, con su receta en texto para replicarlos a mano en el panel.

    python -m genetico.prueba_fase1 [--n 10] [--semilla 42]

Deja en D:/tmp/btt_genetico/fase1/: recetas.txt (para Jaume), individuos.json
(genes + definicion del motor + metricas) y los feather del dataset.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import time

from genetico import entorno

entorno.preparar()

from genetico import cromosoma, datos, evaluador  # noqa: E402

P = lambda *a: print(*a, flush=True)  # noqa: E731

# Configuracion de la prueba: lo que en la pagina elegira el usuario.
CONFIG = {
    "dataset_id": "10cea798-4b62-413b-9535-7f5adb23f8f5",   # Universo_Estrategia_1B_50k_9309
    "fecha_ini": "2019-01-01",
    "fecha_fin": "2024-12-31",                               # IS; 2025-2026 queda como OOS
    "sesgo": "short",
    "sesiones": ["rth"],
    "hora_ini": None,
    "hora_fin": None,
    "ventana_entrada": None,
    "guardas": [
        {"type": "indicator_comparison", "source": {"name": "Bar Close", "offset": 0},
         "comparator": "GREATER_THAN", "target": 0.7, "timeframe": "1m"},
        {"type": "indicator_comparison", "source": {"name": "Accumulated Dollar Volume", "offset": 0},
         "comparator": "GREATER_THAN", "target": 1000000.0, "timeframe": "1m"},
    ],
    "catalogo": ["Bar Close", "Consecutive red candles", "Candle Range %", "% Fade", "Squeeze", "RSI"],
    "n_condiciones": 2,
    "stops": ["pct", "estructura"],
    "tps": ["pct", "hora"],
    # size_by_sl=True = «Calculo de Shares por Distancia al SL» en el panel: asi
    # el riesgo fijo de 100 $ es riesgo de verdad y la R media es una R.
    "riesgo": {"init_cash": 50000, "risk_r": 100, "risk_type": "FIXED", "fees": 0, "fee_type": "PERCENT",
               "slippage": 0, "locates_cost": 0, "max_locates": 0, "size_by_sl": True,
               "accept_reentries": True, "max_reentries": -1},
    "fitness": "expR_sqrtN",
    "min_trades": 100,
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=10)
    ap.add_argument("--semilla", type=int, default=42)
    args = ap.parse_args()

    dir_corrida = os.path.join(entorno.DIR_TRABAJO, "fase1")
    P(f"RAM libre {entorno.ram_libre_gb():.1f} GB")
    meta = datos.preparar(CONFIG["dataset_id"], dir_corrida, CONFIG["fecha_ini"], CONFIG["fecha_fin"], log=P)
    P("dataset:", meta)
    t = time.time()
    q, grupos = datos.cargar(dir_corrida)
    P(f"cargado en {time.time()-t:.1f}s: {len(grupos)} grupos, RSS {entorno.rss_gb():.2f} GB")

    rng = random.Random(args.semilla)
    vistos = set()
    individuos = []
    while len(individuos) < args.n:
        ind = cromosoma.aleatorio(CONFIG, rng)
        h = cromosoma.huella(ind)
        if h in vistos:
            continue
        vistos.add(h)
        individuos.append(ind)

    salida = []
    lineas = [f"Fase 1 — {args.n} individuos al azar (semilla {args.semilla}) sobre "
              f"{meta['pares']} pares {meta['primer_dia']} → {meta['ultimo_dia']}",
              "Config del panel para replicar: short · sesión RTH · guardas Bar Close > 0,70 y "
              "Accumulated Dollar Volume > 1.000.000 · riesgo FIJO 100 $ con «Shares por Distancia al SL» "
              "ACTIVADO · capital 50.000 · reentradas sí (sin límite) · comisiones 0 · slippage 0 · "
              "locates 0 · sin piramidación, sin salida por condiciones, sin swing · "
              "fechas 2019-01-01 → 2024-12-31", ""]
    for i, ind in enumerate(individuos, 1):
        try:
            m = evaluador.evaluar(ind, CONFIG, q, grupos)
        except Exception as e:  # que un individuo roto no tumbe la prueba
            m = {"error": f"{type(e).__name__}: {str(e)[:200]}"}
        r = cromosoma.receta(ind)
        linea = (f"#{i:02d} [{cromosoma.huella(ind)}]  {r}\n"
                 f"      trades {m.get('trades')} · R media {m.get('avg_r')} · PF {m.get('pf')} · "
                 f"WR {m.get('wr')} · maxDD {m.get('max_dd')} · fitness {m.get('fitness')} · {m.get('segundos')}s"
                 + (f"\n      ERROR {m['error']}" if "error" in m else ""))
        P(linea)
        lineas.append(linea)
        lineas.append("")
        salida.append({"huella": cromosoma.huella(ind), "receta": r, "individuo": ind,
                       "definicion": cromosoma.a_definicion(ind, CONFIG), "metricas": m})
        json.dump({"config": CONFIG, "individuos": salida},
                  open(os.path.join(dir_corrida, "individuos.json"), "w", encoding="utf-8"),
                  indent=1, ensure_ascii=False)
        open(os.path.join(dir_corrida, "recetas.txt"), "w", encoding="utf-8").write("\n".join(lineas))
    P(f"FIN · RSS {entorno.rss_gb():.2f} GB · {dir_corrida}")


if __name__ == "__main__":
    main()
