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
    minimo — tipicamente 10 centimos. Al llegar al umbral cuenta el beneficio
    ENTERO, no el sobrante por encima de los 10. Por eso esto devuelve un si/no
    y no resta nada. (Jaume, 2026-09-04: «si supera los 10 centimos entonces se
    cuenta el beneficio de todo el trade».)

    EL RECORRIDO ES ENTRE MEDIAS (corregido 2026-09-07, re-portado del
    2b597cf de Álvaro en el merge del 08-sep). TTP lo publica asi: «10.0 cents
    difference between average entry and average exit price». Se mide del
    precio MEDIO de entrada al precio MEDIO de salida: con parciales y
    piramides cada venta cuenta por las acciones que cerro (`_salida_media`).
    Mirar solo el precio de la ULTIMA venta daba el veredicto equivocado en
    los dos sentidos.

    EL BORDE EXACTO CUENTA (corregido 2026-09-07). La norma dice «at least 10
    price ticks» y su ejemplo canonico es compra 50.10 venta «50.20 (at
    least)»: 10 centimos justos SI cuentan.

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
    salida = _salida_media(trade)
    if not entrada or salida is None:
        # Sin precios no se puede juzgar. Se deja pasar en vez de descartarlo:
        # esta regla quita trades ganadores, y quitarlos por falta de dato
        # castigaria la curva por un hueco nuestro, no por la regla de la mesa.
        return True
    # EPSILON. En coma flotante 50.20 - 50.10 sale 0.09999999999999998, asi que
    # el caso del borde exacto (que SI cuenta) pasaria por «menos de 0,10» si
    # se comparara a secas. Con tolerancia y mayor-o-igual.
    return (abs(float(salida) - float(entrada)) - float(min_cents)) >= -1e-9


def _salida_media(trade: Dict[str, Any]):
    """Precio MEDIO de salida de la posicion; `exit_price` si no hay detalle.

    La regla de la mesa mide contra la MEDIA de las ventas, no contra la
    ultima: cada salida cuenta por las acciones que cerro. El detalle vive en
    `executions[]` (kinds exit/reduce). Sin detalle —trade de una sola
    salida— la media y el `exit_price` son el mismo numero, asi que el
    fallback es exacto, no una aproximacion.
    """
    ventas = [
        (float(e["price"]), float(e["size"]))
        for e in (trade.get("executions") or [])
        if e.get("kind") in ("exit", "reduce") and e.get("price") and e.get("size")
    ]
    if ventas:
        total = sum(size for _, size in ventas)
        if total > 0:
            return sum(precio * size for precio, size in ventas) / total
    return trade.get("exit_price")


def _locates_supervivientes(
    locates_por_par: Dict[str, Any] | None,
    filtrados: List[Dict[str, Any]],
) -> Dict[str, float]:
    """Locates que se siguen debiendo con los trades que quedan.

    EL FALLO QUE ARREGLA. La curva del backtest va NETA de locates —
    `_compute_global_equity_and_drawdown` los descuenta por fecha— y la del
    What-if iba BRUTA, porque el locate no esta dentro del pnl de ningun trade
    y aqui no llegaba por ningun sitio. Resultado: la simulacion salia mejor
    que el original por el importe entero de la factura de alquiler, y una
    regla que solo QUITA ganadores parecia mejorar la estrategia.

    LA REGLA ES HONESTA, no un reparto aproximado: el locate se cobra UNA VEZ
    por ticker-dia, asi que si sobrevive aunque sea un trade de ese ticker ese
    dia, se sigue debiendo ENTERO. Si no sobrevive ninguno, no se alquilo nada
    y no se paga. Por eso viaja por par (`TICKER|FECHA`) y no por fecha.

    NO SE REESCALA con la recomposicion. Si la curva filtrada es mas pequena se
    habrian alquilado menos paquetes, asi que cobrarlo entero es el lado
    conservador — y el unico que no exige inventarse el tamano del paquete.
    """
    if not locates_por_par:
        return {}
    vivos = {f"{t.get('ticker', '')}|{t.get('date', '')}" for t in filtrados}
    por_fecha: Dict[str, float] = {}
    for clave, fee in locates_por_par.items():
        if clave not in vivos:
            continue
        fecha = str(clave).split("|", 1)[-1]
        por_fecha[fecha] = por_fecha.get(fecha, 0.0) + float(fee or 0.0)
    return por_fecha


def _recomponer_por_dia(
    originales: List[Dict[str, Any]],
    filtrados: List[Dict[str, Any]],
    init_cash: float,
) -> None:
    """Reescala el PnL de los trades que quedan al capital que habrian tenido.

    EL PROBLEMA. Con `risk_type = PERCENT` cada trade arriesga un % del capital
    VIVO, asi que los dolares que gana dependen del balance que hubiera ese
    dia. Quitar trades y volver a sumar los dolares del resto rompe el vinculo
    con el capital y produce cifras imposibles. Medido sobre la corrida de
    3.544 trades: quitando el mejor 10 %, la suma del top eran 152.578 $ —mas
    que TODO el beneficio— y la curva aditiva acababa en -84.411 $, dinero
    negativo. Recompuesta da 2.617 $, o sea -73,8 %, que es la respuesta util.

    La regla de los centimos es justo ese caso, y peor: descarta ganadores de
    forma sistematica, no un 10 % puntual.

    LA CUENTA. El motor compone POR DIA, no por trade: dentro de una sesion
    todas las posiciones se dimensionan sobre el balance de apertura y el PnL
    se acumula al cerrar. Asi que el PnL de cada dia escala con la razon entre
    los dos capitales de apertura de ESE dia:

        factor(dia) = capital_filtrado(dia) / capital_original(dia)

    Es exactamente recomponer en R-multiplos —R = pnl / riesgo, y el riesgo es
    un % del capital, asi que el % se cancela—, pero sin necesitar la distancia
    al stop de cada trade.

    NO SE TOCA EL RIESGO FIJO. En aditivo los dolares de un trade no dependen
    del balance y sumarlos ya es correcto; quien llama solo entra aqui con
    PERCENT.

    INVARIANTE. Sin ningun filtro los dos capitales coinciden dia a dia, el
    factor es 1,0 exacto y la curva sale identica a la de partida. Hay un test.

    LA CUENTA NO PUEDE IR A NEGATIVO. Si el capital recompuesto llega a cero se
    queda ahi y los dias siguientes escalan por cero: no se puede perder mas de
    lo que hay. Es lo contrario de lo que hacia la suma en dolares.
    """
    pnl_por_dia: Dict[str, float] = {}
    for t in originales:
        d = t.get("date") or ""
        if d:
            pnl_por_dia[d] = pnl_por_dia.get(d, 0.0) + float(t.get("pnl") or 0.0)

    apertura: Dict[str, float] = {}
    capital = init_cash
    for d in sorted(pnl_por_dia):
        apertura[d] = capital
        capital += pnl_por_dia[d]

    por_dia: Dict[str, List[Dict[str, Any]]] = {}
    for t in filtrados:
        por_dia.setdefault(t.get("date") or "", []).append(t)

    capital = init_cash
    for d in sorted(por_dia):
        base = apertura.get(d, 0.0)
        factor = (capital / base) if base > 0 else 1.0
        del_dia = 0.0
        for t in por_dia[d]:
            t["pnl"] = float(t.get("pnl") or 0.0) * factor
            if t.get("size") is not None:
                t["size"] = float(t["size"]) * factor
            del_dia += t["pnl"]

        # El dia que reventaria la cuenta se recorta hasta dejarla en cero, y
        # el recorte se reparte entre sus trades. Si no, el PnL en dolares que
        # se llevan los trades no cuadraria con la curva y el equity acabaria
        # en negativo por detras — que es el fallo que se venia a arreglar.
        if capital + del_dia < 0.0 and del_dia < 0.0:
            recorte = capital / abs(del_dia)
            for t in por_dia[d]:
                t["pnl"] = float(t["pnl"]) * recorte
                if t.get("size") is not None:
                    t["size"] = float(t["size"]) * recorte
            del_dia = -capital

        capital = max(capital + del_dia, 0.0)


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

        # Recorrido minimo en centimos: la regla de las cuentas de fondeo.
        # ASIMETRICA A PROPOSITO — ver `mueve_bastante`.
        #
        # VA LA ULTIMA, DESPUES DE LOS LIMITES, y no es indiferente: el trade
        # EXISTIO. Ocupo su hueco del dia y su plaza de simultaneos aunque la
        # mesa no lo abone. Filtrandolo antes —como estaba— un ganador corto
        # liberaba un hueco que en la realidad estaba ocupado, y entraba en su
        # lugar un trade posterior que nunca se llego a operar.
        #
        # NOTA DE MERGE (2026-09-08): la variante de Álvaro «el win invalidado
        # se queda pagando solo sus fees» (2b597cf) NO llegó nunca a staging;
        # su recomposición en R (892b7fd) está construida sobre QUITAR el
        # ganador. Aquí manda staging hasta que Álvaro y Jaume acuerden cuál
        # de las dos semánticas vale — ver MEMORIA_MADRE (pendiente de decidir).
        if (min_move_cents > 0 and t.get("pnl", 0) > 0
                and not mueve_bastante(t, min_move_cents)):
            continue

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

    # --- 4 bis) Recomposicion en R si el riesgo era PORCENTUAL ---
    #
    # Va DESPUES de todos los castigos —los castigos cambian el PnL, y lo que
    # se recompone es el PnL final— y ANTES de construir la curva, para que
    # equity, drawdown, metricas y calendario salgan todos del mismo numero.
    #
    # `risk_type` lo manda la pagina. Si no llega, se asume FIJO y todo se
    # comporta como siempre: esta correccion no puede activarse sola.
    if str(params.get("risk_type") or "FIXED").upper() == "PERCENT":
        _recomponer_por_dia(sorted_trades, filtered_trades, init_cash)

    # --- 5) Rebuild Equity & Finalize ---
    # We use the helpers from backtest_service to ensure consistency
    # Note: we pass monthly_expenses=0 for what-if often, unless requested
    monthly_expenses = params.get("monthly_expenses", 0.0)
    
    # Los locates de los ticker-dia que siguen vivos. Sin esto la simulacion
    # se compara BRUTA contra un original NETO y sale mejor por la cara.
    locates_por_par = params.get("locates_by_pair") or {}
    locates_por_fecha = _locates_supervivientes(locates_por_par, filtered_trades)

    global_eq, global_dd, global_eq_exp = _compute_global_equity_and_drawdown(
        filtered_trades, init_cash, monthly_expenses, locates_por_fecha
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
        "day_results": _day_results_de(filtered_trades, locates_por_par),
    }


def _day_results_de(
    trades: List[Dict[str, Any]],
    locates_por_par: Dict[str, Any] | None = None,
) -> List[Dict[str, Any]]:
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

    LOS LOCATES SI SE ARRASTRAN desde el 2026-09-07. Se cobran una vez por
    ticker-dia y no estan en el pnl de ningun trade, asi que llegan aparte
    (`locates_by_pair`) y se cobran ENTEROS si sobrevive algun trade de ese
    ticker ese dia. Antes se dejaban a cero, y el calendario del What-if
    contaba en bruto contra un calendario neto.
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
            "locates_fee": float((locates_por_par or {}).get(
                f"{ticker}|{fecha}", 0.0) or 0.0),
        })
    return salida
