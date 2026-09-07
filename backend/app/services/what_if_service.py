import random
import pandas as pd
import numpy as np
from typing import List, Dict, Any
from datetime import datetime

# Import the aggregate metrics helper from backtest_service
# We might need to handle imports carefully based on the project structure
from app.services.backtest_service import (
    _aggregate_metrics,
    _compute_global_equity_and_drawdown
)

def mueve_bastante(trade: Dict[str, Any], min_cents: float) -> bool:
    """¿Recorrio el precio los centimos que exige la mesa de fondeo?

    LA REGLA. Las cuentas de fondeo no abonan un trade que no se haya movido un
    minimo — tipicamente 10 centimos. Un short de 1,00 a 0,90 se movio 10
    justos y NO cuenta; a 0,89 cuenta, y cuenta el beneficio ENTERO, no el
    sobrante por encima de los 10. Por eso esto devuelve un si/no y no resta
    nada. (Jaume, 2026-09-04: «si supera los 10 centimos entonces se cuenta el
    beneficio de todo el trade».)

    ES ASIMETRICA, y no es un descuido: quien llama la aplica SOLO a los trades
    ganadores. La mesa no te paga lo que no se movio, pero las perdidas te las
    apunta enteras. Modelarla simetrica pintaria la curva mejor de lo que la
    cuenta va a ir.

    LA DIRECCION NO IMPORTA. Se mide el valor absoluto: en corto el precio baja
    y en largo sube, pero en los dos casos lo que exige la mesa es distancia
    recorrida. Y el trade ya se sabe ganador, asi que el signo no anyade nada.

    Se usa el precio MEDIO de entrada cuando lo hay: con piramidacion el
    recorrido que cuenta es desde donde quedo la posicion, no desde el primer
    trozo.
    """
    entrada = trade.get("avg_entry_price") or trade.get("entry_price")
    salida = trade.get("exit_price")
    if not entrada or salida is None:
        # Sin precios no se puede juzgar. Se deja pasar en vez de descartarlo:
        # esta regla quita trades ganadores, y quitarlos por falta de dato
        # castigaria la curva por un hueco nuestro, no por la regla de la mesa.
        return True
    # EPSILON. En coma flotante 1.00 - 0.90 sale 0.09999999999999998, asi que un
    # short de 1,00 a 0,90 pasaria por «se movio menos de 0,10» tanto si la
    # regla es estricta como si no. El caso del borde exacto es justo el del
    # ejemplo de Jaume, asi que se compara con tolerancia y luego se exige
    # estrictamente mayor.
    return (abs(float(salida) - float(entrada)) - float(min_cents)) > 1e-9


def run_what_if(
    trades: List[Dict[str, Any]],
    params: Dict[str, Any],
    init_cash: float = 10000.0,
    risk_r: float = 100.0
) -> Dict[str, Any]:
    """
    Runs a simulation on existing trades based on the 'What-if' parameters.
    """
    if not trades:
        return {
            "trades": [],
            "global_equity": [],
            "global_drawdown": [],
            "aggregate_metrics": {}
        }

    # Sort trades by entry time to ensure chronological processing
    sorted_trades = sorted(trades, key=lambda x: x["entry_time"])
    
    # --- 1) Temporal Filters ---
    exclude_days = params.get("exclude_days", []) # [0, 1, 2, 3, 4] for Mon-Fri
    exclude_months = params.get("exclude_months", []) # ["Enero", ...]
    exclude_hour_start = params.get("exclude_hour_start") # int
    exclude_hour_end = params.get("exclude_hour_end") # int
    random_monthly_days = params.get("random_monthly_days", 0)

    # Prepare Month mapping — accepts both numeric indices (0-based from frontend)
    # and Spanish month name strings (legacy)
    month_map = {
        "Enero": 1, "Febrero": 2, "Marzo": 3, "Abril": 4, "Mayo": 5, "Junio": 6,
        "Julio": 7, "Agosto": 8, "Septiembre": 9, "Octubre": 10, "Noviembre": 11, "Diciembre": 12
    }
    exclude_months_idx = []
    for m in exclude_months:
        if isinstance(m, int):
            # Frontend sends 0-based index (0=Jan, 11=Dec) → convert to 1-based month
            exclude_months_idx.append(m + 1)
        elif isinstance(m, str) and m in month_map:
            exclude_months_idx.append(month_map[m])
        elif isinstance(m, str) and m.isdigit():
            exclude_months_idx.append(int(m) + 1)

    # Handle Random Monthly Days
    # We group trades by YYYY-MM and pick N random days to exclude
    days_to_exclude = set()
    if random_monthly_days > 0:
        trades_by_month = {}
        for t in sorted_trades:
            m_key = t["date"][:7] # YYYY-MM
            if m_key not in trades_by_month:
                trades_by_month[m_key] = set()
            trades_by_month[m_key].add(t["date"])
        
        for m_key, dates in trades_by_month.items():
            dates_list = sorted(list(dates))
            to_drop = random.sample(dates_list, min(len(dates_list), random_monthly_days))
            days_to_exclude.update(to_drop)

    filtered_trades = []
    
    # --- 2) Trade Limits & Simulation ---
    daily_counter = {} # date -> count
    max_trades_per_day = params.get("daily_max_trades", 0)
    max_concurrent = params.get("max_concurrent_trades", 0)
    min_move_cents = params.get("min_move_cents", 0)

    open_trades = [] # List of exit_times for concurrent check

    for t in sorted_trades:
        # Exclusion checks
        if t["entry_weekday"] in exclude_days: continue
        if datetime.strptime(t["date"], "%Y-%m-%d").month in exclude_months_idx: continue
        if t["date"] in days_to_exclude: continue

        # Recorrido minimo en centimos: la regla de las cuentas de fondeo.
        # ASIMETRICA A PROPOSITO — ver `mueve_bastante`.
        if (min_move_cents > 0 and t.get("pnl", 0) > 0
                and not mueve_bastante(t, min_move_cents)):
            continue

        # Hour check
        if exclude_hour_start is not None and exclude_hour_end is not None:
            h = t["entry_hour"]
            # Interval check [start, end)
            if exclude_hour_start < exclude_hour_end:
                if exclude_hour_start <= h < exclude_hour_end: continue
            else: # Overnight interval e.g. 22:00 to 02:00
                if h >= exclude_hour_start or h < exclude_hour_end: continue

        # Daily limit
        if max_trades_per_day > 0:
            d = t["date"]
            daily_counter[d] = daily_counter.get(d, 0) + 1
            if daily_counter[d] > max_trades_per_day: continue

        # Concurrent limit
        if max_concurrent > 0:
            # Clean up closed trades
            entry_time = pd.to_datetime(t["entry_time"])
            open_trades = [ex for ex in open_trades if ex > entry_time]
            if len(open_trades) >= max_concurrent:
                continue
            open_trades.append(pd.to_datetime(t["exit_time"]))

        filtered_trades.append(t.copy())

    # --- 3) Alternative Size Management (Dynamic Post-hoc) ---
    #
    # APAGADO POR DEFECTO. Estaba en `dd_threshold=5` y `sma_period=20`, y la
    # pagina NUNCA manda esos dos parametros — asi que TODA simulacion, sin
    # marcar nada, recortaba a la mitad el tamano de cada trade abierto con mas
    # de un 5 % de drawdown encima. Segun donde cayeran las perdidas eso podia
    # MEJORAR la curva, y entonces el What-if «sin filtros» salia mejor que el
    # original: exactamente lo que vio Jaume el 2026-09-04 («la curva me sale
    # en el what if mejor que la original, es imposible»).
    #
    # La regla es que una simulacion sin opciones devuelva la curva de partida.
    # Si no, no hay contra que comparar.
    size_mgmt_type = params.get("size_mgmt_type", "dd")
    dd_threshold = params.get("dd_threshold", 0)
    dd_reduction = params.get("dd_reduction", 50)
    sma_period = params.get("sma_period", 0)
    sma_reduction = params.get("sma_reduction", 50)

    # We need to simulate the equity curve sequentially to calculate DD or SMA 
    # and reduce size accordingly on the fly.
    if dd_threshold > 0 or sma_period > 0:
        current_eq = init_cash
        running_max = init_cash
        eq_history = [init_cash]
        
        for t in filtered_trades:
            # 1. Evaluate current conditions (Before applying trade)
            current_dd_pct = ((running_max - current_eq) / running_max * 100) if running_max > 0 else 0

            # LA MEDIA SOLO SI ES LA QUE MANDA. Se calculaba siempre, tambien en
            # el modo «dd» donde no la mira nadie — y con `sma_period` en 0
            # divide entre cero. No saltaba porque el default era 20; al
            # apagarlo quedo a la vista.
            sma_val = 0.0
            if size_mgmt_type == "sma" and sma_period > 0:
                ventana = eq_history[-sma_period:] if len(eq_history) >= sma_period else eq_history
                sma_val = sum(ventana) / len(ventana)

            # 2. Decide size reduction factor
            reduce_factor = 1.0
            if size_mgmt_type == "dd":
                if dd_threshold > 0 and current_dd_pct > dd_threshold:
                    reduce_factor = max(0.0, 1.0 - (dd_reduction / 100.0))
            elif size_mgmt_type == "sma":
                if sma_period > 0 and current_eq < sma_val:
                    reduce_factor = max(0.0, 1.0 - (sma_reduction / 100.0))
            
            # 3. Apply reduction to the trade PnL and Size
            if reduce_factor < 1.0:
                t["size"] = t["size"] * reduce_factor
                t["pnl"] = t["pnl"] * reduce_factor

            # 4. Advance states
            current_eq += t["pnl"]
            if current_eq > running_max:
                running_max = current_eq
            eq_history.append(current_eq)


    # --- 4) Stress Test ---
    skip_top_pct = params.get("skip_top_pct", 0)
    extra_slippage = params.get("extra_slippage", 0)
    black_swan_count = params.get("black_swan_count", 0)
    black_swan_pct = params.get("black_swan_pct", 0)

    # Skip top %
    if skip_top_pct > 0 and filtered_trades:
        filtered_trades.sort(key=lambda x: x["pnl"], reverse=True)
        count_to_skip = int(len(filtered_trades) * (skip_top_pct / 100.0))
        filtered_trades = filtered_trades[count_to_skip:]
        # Resort chronologically after filtering top
        filtered_trades.sort(key=lambda x: x["entry_time"])

    # Extra Slippage & Recalculate PnL
    if extra_slippage > 0:
        for t in filtered_trades:
            # S = S_original - extra_slippage
            # PnL roughly follows the return change
            old_ret = t["return_pct"]
            new_ret = old_ret - extra_slippage
            # Proportional adjustment to PnL
            if old_ret != 0:
                t["pnl"] = (t["pnl"] * new_ret) / old_ret
            else:
                # If old_ret was 0, we estimate PnL from size * price * extra_slippage
                t["pnl"] -= (t["size"] * t["entry_price"] * (extra_slippage / 100.0))
            t["return_pct"] = new_ret

    # Black Swan (Random losses)
    if black_swan_count > 0 and filtered_trades:
        swan_indices = random.sample(range(len(filtered_trades)), min(len(filtered_trades), black_swan_count))
        for idx in swan_indices:
            t = filtered_trades[idx]
            # Replace trade with a significant loss
            t["return_pct"] = -abs(black_swan_pct) if black_swan_pct != 0 else -5.0
            t["pnl"] = -abs(t["size"] * t["entry_price"] * (abs(t["return_pct"]) / 100.0))
            t["exit_reason"] = "BLACK SWAN"

    # --- 5) Rebuild Equity & Finalize ---
    # We use the helpers from backtest_service to ensure consistency
    # Note: we pass monthly_expenses=0 for what-if often, unless requested
    monthly_expenses = params.get("monthly_expenses", 0.0)
    
    global_eq, global_dd, global_eq_exp = _compute_global_equity_and_drawdown(
        filtered_trades, init_cash, monthly_expenses
    )
    
    # For aggregate metrics, we need "day_results" but since it's a trade-level sim,
    # we can pass an empty list or construct simplified ones.
    # Actually, _aggregate_metrics handles empty day_results if it has global_eq
    # Let's check _aggregate_metrics in backtest_service.py to see if it can handle minimal day_results
    
    aggregate = _aggregate_metrics(
        day_results=[], 
        trades=filtered_trades, 
        global_eq=global_eq, 
        global_dd=global_dd, 
        init_cash=init_cash, 
        risk_r=risk_r,
        monthly_expenses=monthly_expenses
    )

    return {
        "trades": filtered_trades,
        "global_equity": global_eq,
        "global_drawdown": global_dd,
        "aggregate_metrics": aggregate,
        "day_results": _day_results_de(filtered_trades),
    }


def _day_results_de(trades: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Reconstruye los resultados por ticker-dia con los trades que quedan.

    PARA QUE. El calendario del What-if. Sin esto habria que rehacer la cuenta
    en la pagina, y entonces el calendario del What-if y el de siempre podrian
    decir cosas distintas del mismo dia — que es el peor fallo posible en una
    pantalla que se usa para comparar justo eso.

    LO QUE NO SE PUEDE RECONSTRUIR se deja en None y no se inventa: sharpe,
    sortino y el drawdown intradia salen de la curva del dia, y esa curva aqui
    no existe — solo quedan los trades sueltos. El calendario pinta PnL y
    numero de operaciones, que si salen de los trades; el resto de campos estan
    para cumplir la forma de `DayResult`, no para leerlos.

    LOS LOCATES NO SE ARRASTRAN. Se cobran una vez por ticker-dia y no estan en
    el pnl de ningun trade; si el What-if se ha quedado con la mitad de los
    trades de ese dia, no hay forma honesta de decidir que parte del locate
    sigue debiendose. Se deja a cero y se dice aqui.
    """
    por_dia: Dict[tuple, List[Dict[str, Any]]] = {}
    for t in trades:
        por_dia.setdefault((t.get("ticker", ""), t.get("date", "")), []).append(t)

    salida = []
    for (ticker, fecha), ts in sorted(por_dia.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        pnl = sum(float(x.get("pnl") or 0.0) for x in ts)
        ganadores = [x for x in ts if float(x.get("pnl") or 0.0) > 0]
        perdedores = [x for x in ts if float(x.get("pnl") or 0.0) <= 0]
        bruto_gana = sum(float(x.get("pnl") or 0.0) for x in ganadores)
        bruto_pierde = abs(sum(float(x.get("pnl") or 0.0) for x in perdedores))
        retornos = [float(x.get("return_pct") or 0.0) for x in ts]
        salida.append({
            "ticker": ticker,
            "date": fecha,
            # El calendario suma el pnl de los trades del dia; `total_return_pct`
            # queda como referencia y va en % sobre el valor de partida, que
            # aqui no se conoce — de ahi que sea None.
            "total_return_pct": None,
            "max_drawdown_pct": None,
            "win_rate_pct": (len(ganadores) / len(ts) * 100.0) if ts else None,
            "total_trades": len(ts),
            "profit_factor": (bruto_gana / bruto_pierde) if bruto_pierde > 0 else None,
            "sharpe_ratio": None,
            "sortino_ratio": None,
            "expectancy": (pnl / len(ts)) if ts else None,
            "best_trade_pct": max(retornos) if retornos else None,
            "worst_trade_pct": min(retornos) if retornos else None,
            "init_value": None,
            "end_value": None,
            "locates_fee": 0.0,
        })
    return salida
