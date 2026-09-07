"""
Lightweight numpy portfolio simulator.
Replaces vbt.Portfolio.from_signals() with ~0 memory overhead per day.

Supports: long/short, stop-loss (fixed & trailing), take-profit, fees, slippage.
Equity model: init_cash + sum(realized_pnl) + unrealized_pnl
"""

import numpy as np
from datetime import datetime, timezone


def _structural_level(
    value, i, hods, lods, pm_highs, pm_lows, prev_highs, prev_lows,
):
    """Nivel estructural de un hard stop en la barra i.

    Devuelve el valor del nivel pedido (HOD/LOD/PMH/PML/Previous Max/
    Previous Min) o 0.0 si no está disponible (array ausente o valor 0);
    el caller decide el default cuando es 0.0.
    """
    if value == "HOD" and hods is not None:
        return hods[i] if hods[i] > 0 else 0.0
    if value == "LOD" and lods is not None:
        return lods[i] if lods[i] > 0 else 0.0
    if value == "PMH" and pm_highs is not None:
        return pm_highs[i] if pm_highs[i] > 0 else 0.0
    if value == "PML" and pm_lows is not None:
        return pm_lows[i] if pm_lows[i] > 0 else 0.0
    if value in ("Previous Max", "PrevMax") and prev_highs is not None:
        return prev_highs[i] if prev_highs[i] > 0 else 0.0
    if value in ("Previous Min", "PrevMin", "Previous Low", "PrevLow") and prev_lows is not None:
        return prev_lows[i] if prev_lows[i] > 0 else 0.0
    return 0.0


def _sl_side_valid(stop_price, entry_price, is_long):
    """True si el stop queda en el lado perdedor de la entrada.

    Corto: SL estrictamente por encima del precio de entrada. Largo:
    estrictamente por debajo (y positivo). Un stop en el lado ganador
    (o a distancia cero) no es un stop: la premisa del nivel ya está
    invalidada al entrar.
    """
    if is_long:
        return 0.0 < stop_price < entry_price
    return stop_price > entry_price



def tope_hibrido(capital: float, black_swan_pct: float | None,
                 max_loss_pct: float | None, precio: float) -> float | None:
    """Acciones maximas para que un evento de cola no cueste mas de la cuenta.

    Si el precio se mueve `black_swan_pct` en contra, una posicion que vale V
    pierde `V x black_swan_pct/100`. Para que esa perdida no pase de
    `max_loss_pct` del capital:

        V <= (max_loss_pct/100 x capital) / (black_swan_pct/100)

    El resultado son DOLARES de exposicion; las acciones salen de dividir por el
    precio. Ejemplo de Jaume: capital 10.000, acepta perder el 50 % ante un
    evento del 5.000 % -> V <= 5.000/50 = 100 $ de posicion. Con la accion a
    1 $ son 100 acciones; a 0,50 $, 200. **El limite es de valor, no de
    acciones** — confundirlo multiplica la exposicion por el precio.

    Devuelve None si falta algun dato: sin capital o sin porcentajes no se puede
    calcular un tope, y aplicar uno inventado seria peor que no aplicarlo. Quien
    llama decide si eso significa "sin tope" o "no operar".
    """
    if not capital or capital <= 0:
        return None
    if not black_swan_pct or black_swan_pct <= 0:
        return None
    if max_loss_pct is None or max_loss_pct <= 0:
        return None
    if not precio or precio <= 0:
        return None
    valor_max = (max_loss_pct / 100.0) * capital / (black_swan_pct / 100.0)
    return valor_max / precio


def simulate(
    close: np.ndarray,
    open_: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    entries: np.ndarray,
    exits: np.ndarray,
    direction: str = "longonly",
    init_cash: float = 10000.0,
    risk_r: float = 100.0,
    risk_type: str = "FIXED",
    fixed_ratio_delta: float = 500.0,
    size_by_sl: bool = False,
    fees: float = 0.0,
    fee_type: str = "PERCENT",  # "PERCENT" or "FLAT"
    slippage: float = 0.0,
    sl_stop: float | None = None,
    sl_trail: bool = False,
    tp_stop: float | None = None,
    tp_time_limit: float | str | None = None,
    accumulate: bool = False,
    max_reentries: int = -1,
    trail_pct: float | None = None,
    locates_cost: float = 0.0,
    locate_type: str = "FLAT",
    # TOPE DE LOCATES (2026-08-26). Maximo de paquetes de 100 acciones que se
    # esta dispuesto a alquilar para un ticker-dia. 0 = sin tope (comportamiento
    # de siempre). En CORTO limita el tamano a `max_locates * 100` acciones:
    # como la factura del dia es ceil(max_corto_del_dia / 100) * coste, topar
    # cada entrada topa el gasto del dia entero. Recorta la posicion, NO anula
    # el trade. En largo no se aplica: los locates son cosa del corto.
    max_locates: int = 0,
    look_ahead_prevention: bool = True,
    # STOP HIBRIDO (2026-09-03). Va por distancia al stop como `size_by_sl`,
    # PERO topando la exposicion para que un evento de cola no se lleve mas de
    # lo que se acepta perder. Nace de que los dos modos clasicos fallan en
    # extremos opuestos: por SL, un stop muy cenido dispara el tamano y un hueco
    # brutal te deja debiendo dinero; por MV escalas mal. El tope se calcula
    # como `(% de cuenta que aceptas perder x capital) / % del evento`, y el
    # resultado son DOLARES de exposicion, que se pasan a acciones al precio de
    # la barra. Solo aplica con `size_by_sl`: sin el ya se va por valor de
    # mercado y no hay nada que topar.
    hybrid_stop: bool = False,
    hybrid_black_swan_pct: float | None = None,
    hybrid_max_loss_pct: float | None = None,
    # CAPITAL SOBRE EL QUE SE CALCULA EL TECHO. None (lo normal) = el equity de
    # la simulacion, `init_cash + realized_pnl`, que es lo correcto en un
    # backtest y escala con la cuenta.
    #
    # Hace falta poder darlo aparte por el BOT DE ALERTAS: alli `init_cash` es
    # un capital NOMINAL enorme (1e9) puesto a proposito para que el tope de
    # caja no recorte nunca el tamano del aviso. Con ese numero, el techo
    # hibrido saldria astronomico y NO RECORTARIA JAMAS — el aviso diria un
    # tamano sin topar y nada lo indicaria.
    hybrid_capital: float | None = None,
    partial_take_profits: list | None = None,
    pyramid_levels: list | None = None,
    pyramid_sequential: bool = False,
    hs_type: str | None = None,
    hs_value: str | float | None = None,
    hs_operator: str | None = ">=",
    hs_offset_pct: float | None = 0.0,
    # Nivel de respaldo ("HOD"/"LOD"/"PMH"/"PML"/"Previous Max"/"Previous
    # Min") para cuando el nivel principal del hard stop estructural queda
    # invalidado al entrar (ej. corto con el PMH ya roto). Solo aplica en
    # REENTRADAS (total_trades > 0): la primera entrada con el nivel roto
    # no se hace. None (default) = sin respaldo, nivel invalidado = no se
    # entra. Viaja en `hard_stop.fallback_value` del JSON de la estrategia.
    hs_fallback_value: str | None = None,
    # Con `fallback_first_entry: true` en el JSON, el respaldo rescata
    # TAMBIEN la primera entrada con el nivel invalidado (no solo reentradas).
    hs_fallback_first: bool = False,
    hods: np.ndarray | None = None,
    lods: np.ndarray | None = None,
    pm_highs: np.ndarray | None = None,
    pm_lows: np.ndarray | None = None,
    prev_highs: np.ndarray | None = None,
    prev_lows: np.ndarray | None = None,
    timestamps: np.ndarray | None = None,
    elapsed_limit: float = -1.0,
    elapsed_operator: str = "GREATER_THAN_OR_EQUAL",
    # Cortacircuitos de perdida diaria. Ambos en NANOSEGUNDOS epoch, igual que
    # `timestamps`; 0 = desactivado. Quien decide el instante T es el bucle del
    # dia (backtest_signals), que es el unico que ve el PnL de TODOS los tickers
    # de la sesion; aqui solo se obedece.
    no_new_risk_after: int = 0,
    force_close_at: int = 0,
) -> dict:
    n = len(close)
    is_long = direction == "longonly"

    equity = np.empty(n, dtype=np.float64)
    trades: list[dict] = []

    realized_pnl = 0.0
    in_position = False
    entry_price = 0.0
    entry_idx = 0
    entry_time = 0
    entry_fee_amount = 0.0
    size = 0.0
    trade_sl_price = 0.0
    trail_extreme = 0.0
    mae = 0.0  # Maximum Adverse Excursion
    mfe = 0.0  # Maximum Favorable Excursion
    trail_activated = False
    original_size = 0.0  # Track original position size for partial TPs
    # -- Piramidacion (2026-08-22) --
    # avg_entry_price: precio medio ponderado de la posicion. SIN piramidar
    # se asigna una vez (= entry_price) y no cambia: todos los calculos de
    # PnL/fees/capital que lo usan son bit-identicos al motor anterior.
    # entry_price queda como ANCLA DE NIVELES: SL, TP, trailing y las
    # distancias de los parciales se siguen midiendo desde la entrada
    # ORIGINAL (decision del usuario: el stop no se mueve al piramidar).
    avg_entry_price = 0.0
    pyramid_mode = bool(pyramid_levels)
    pyr_exec = []
    # Base de los TP parciales: la posicion que "hay" en el trade = inicial mas
    # lo añadido menos lo reducido por piramide. NO baja con los parciales ya
    # tomados, para que 50%+50% siga cerrando el 100% cuando no se piramida.
    pyr_base = 0.0
    # Estado de la señal de cada nivel DENTRO del trade (se rearma al entrar).
    pyr_prev_sig: list = []
    pyr_fired: list = []   # contador de disparos por nivel (int)
    partial_tp_hits: list[bool] = []  # Track which partial TP levels have been hit

    # Risk amount tracking for reporting
    risk_amount = risk_r

    # Locates tracking (daily maximum short size)
    max_short_size_today = 0.0

    total_trades = 0
    prev_signal = False

    for i in range(n):
        # Misprint patch removed: intraday source data is now NBBO-clipped at the
        # lake, so the motor processes every bar normally (no 08:00-08:45 skip).
        # Kept as constants so the (now inert) restriction branches below fold away.
        is_restricted = False
        skip_exits = False

        # Cortacircuitos diario: pasado T no entra riesgo NUEVO de ningun tipo
        # —ni entradas, ni reentradas, ni añadidos de piramide—. Se compara con
        # >= y no con >: si el limite salta en el mismo minuto, la operacion
        # nueva no llega a existir. En un limite de riesgo se redondea a favor
        # de no operar.
        riesgo_bloqueado = (
            no_new_risk_after > 0
            and timestamps is not None
            and timestamps[i] >= no_new_risk_after
        )

        # ... existing logic ...
        # --- check exits before entries ---
        if in_position:
            exit_triggered = False
            exit_price = close[i]
            exit_reason = "Signal"
            eff_exit_idx = i

            if is_long:
                price_for_sl = low[i]
                price_for_tp = high[i]
            else:
                price_for_sl = high[i]
                price_for_tp = low[i]

            # stop-loss / trailing stop
            if not skip_exits:
                # 1. Hard Stop Logic
                if hs_type == "Market Structure (HOD/LOD)":
                    if is_long:
                        if price_for_sl <= trade_sl_price:
                            exit_triggered = True
                            exit_price = max(trade_sl_price, low[i])
                            exit_reason = "SL"
                    else:
                        if price_for_sl >= trade_sl_price:
                            exit_triggered = True
                            exit_price = min(trade_sl_price, high[i])
                            exit_reason = "SL"
                elif sl_stop is not None:
                    if is_long:
                        hard_sl_price = entry_price * (1 - sl_stop)
                        if price_for_sl <= hard_sl_price:
                            exit_triggered = True
                            exit_price = max(hard_sl_price, low[i])
                            exit_reason = "SL"
                    else:
                        hard_sl_price = entry_price * (1 + sl_stop)
                        if price_for_sl >= hard_sl_price:
                            exit_triggered = True
                            exit_price = min(hard_sl_price, high[i])
                            exit_reason = "SL"

                # 2. Trailing Stop Logic (Standard High-Water Mark)
                if sl_trail and trail_pct is not None:
                    if is_long:
                        # Check activation: price must go in favor by at least trail_pct
                        if not trail_activated:
                            if high[i] >= entry_price * (1 + trail_pct) - 1e-9:
                                trail_activated = True
                                trail_extreme = max(entry_price, high[i])

                        # Evaluate trailing stop if active
                        if trail_activated:
                            trail_extreme = max(trail_extreme, high[i])
                            trail_sl_price = trail_extreme - (entry_price * trail_pct)
                            
                            # Si el STOP FIJO ya ha disparado en esta misma barra,
                            # manda el fijo: quita todas las ordenes si o si y
                            # esta por encima del trailing en importancia (regla
                            # del usuario, 2026-08-23). Antes el trailing lo
                            # pisaba usando el MAXIMO de la propia barra, y una
                            # vela que tocaba el stop podia acabar registrada
                            # como salida en beneficio.
                            if price_for_sl <= trail_sl_price + 1e-9 and not exit_triggered:
                                # Verify trailing stop doesn't override a better hard stop
                                if hs_type == "Market Structure (HOD/LOD)":
                                    hard_sl_price = trade_sl_price
                                else:
                                    hard_sl_price = entry_price * (1 - sl_stop) if sl_stop is not None else -1e18
                                if trail_sl_price > hard_sl_price:
                                    exit_triggered = True
                                    exit_price = max(trail_sl_price, low[i])
                                    exit_reason = "Trailing"
                    else:
                        # Short: Check activation: price must go in favor by at least trail_pct (drops)
                        if not trail_activated:
                            if low[i] <= entry_price * (1 - trail_pct) + 1e-9:
                                trail_activated = True
                                trail_extreme = min(entry_price, low[i])

                        # Evaluate trailing stop if active
                        if trail_activated:
                            trail_extreme = min(trail_extreme, low[i])
                            trail_sl_price = trail_extreme + (entry_price * trail_pct)
                            
                            # Mismo criterio que en long: el stop fijo manda.
                            if price_for_sl >= trail_sl_price - 1e-9 and not exit_triggered:
                                # Verify trailing stop doesn't override a better hard stop
                                if hs_type == "Market Structure (HOD/LOD)":
                                    hard_sl_price = trade_sl_price
                                else:
                                    hard_sl_price = entry_price * (1 + sl_stop) if sl_stop is not None else 1e18
                                if trail_sl_price < hard_sl_price:
                                    exit_triggered = True
                                    exit_price = min(trail_sl_price, high[i])
                                    exit_reason = "Trailing"

            # take-profit (full mode — only if partial TPs are NOT configured)
            if not exit_triggered and not partial_take_profits and not skip_exits:
                if tp_stop is not None:
                    if is_long:
                        tp_level = entry_price * (1 + tp_stop)
                        if price_for_tp >= tp_level:
                            exit_triggered = True
                            exit_price = min(tp_level, high[i])
                            exit_reason = "TP"
                    else:
                        tp_level = entry_price * (1 - tp_stop)
                        if price_for_tp <= tp_level:
                            exit_triggered = True
                            exit_price = max(tp_level, low[i])
                            exit_reason = "TP"

                if not exit_triggered and tp_time_limit is not None and timestamps is not None:
                    if isinstance(tp_time_limit, str) and tp_time_limit.startswith("HOUR:"):
                        try:
                            parts = tp_time_limit.split(":")
                            tp_hour = int(parts[1])
                            tp_min = int(parts[2])
                        except:
                            tp_hour, tp_min = 0, 0
                        dt = datetime.fromtimestamp(timestamps[i] / 1e9, tz=timezone.utc)
                        if dt.hour > tp_hour or (dt.hour == tp_hour and dt.minute >= tp_min):
                            exit_triggered = True
                            exit_price = close[i]
                            exit_reason = "TP"
                    else:
                        elapsed_mins = (timestamps[i] - entry_time) / 6e10
                        if elapsed_mins >= tp_time_limit:
                            exit_triggered = True
                            exit_price = close[i]
                            exit_reason = "TP"

            # --- Partial Take-Profits ---
            if not exit_triggered and partial_take_profits and not skip_exits:
                for pt_idx, pt in enumerate(partial_take_profits):
                    if partial_tp_hits[pt_idx]:
                        continue  # Already hit
                    dist_frac = pt["distance_pct"]
                    cap_frac = pt["capital_pct"]
                    
                    if dist_frac == "EOD":
                        if i == n - 1:
                            # It is the end of the day, trigger this EOD partial TP!
                            partial_tp_hits[pt_idx] = True
                            pt_exit_price = close[i]
                            
                            slip = pt_exit_price * slippage
                            net_pt_exit = (pt_exit_price - slip) if is_long else (pt_exit_price + slip)
                            pt_size = pyr_base * cap_frac
                            pt_size = min(pt_size, size)
                            if pt_size > 0:
                                if is_long:
                                    gross_pnl = (net_pt_exit - avg_entry_price) * pt_size
                                else:
                                    gross_pnl = (avg_entry_price - net_pt_exit) * pt_size
                                
                                if fee_type == "FLAT":
                                    fee_amount = fees * pt_size * 2
                                else:
                                    # % sobre el NOCIONAL de cada lado (entrada + salida),
                                    # no sobre el PnL: un breakeven tambien paga comision.
                                    fee_amount = (avg_entry_price + net_pt_exit) * pt_size * fees
                                pnl = gross_pnl - fee_amount
                                realized_pnl += pnl
                                capital_at_risk = avg_entry_price * pt_size
                                ret_pct = (pnl / capital_at_risk) * 100 if capital_at_risk > 0 else 0.0
                                trades.append({
                                    "entry_idx": entry_idx,
                                    "exit_idx": i,
                                    "entry_price": round(entry_price, 6),
                                    "avg_entry_price": round(avg_entry_price, 6),
                                    "exit_price": round(net_pt_exit, 6),
                                    "pnl": round(pnl, 4),
                                    "return_pct": round(ret_pct, 4),
                                    "direction": "Long" if is_long else "Short",
                                    "status": "Closed",
                                    "size": round(pt_size, 6),
                                    "exit_reason": "Partial TP (EOD)",
                                    "fees": round(fee_amount, 4),
                                    "mae": round(mae, 4),
                                    "mfe": round(mfe, 4),
                                    "stop_loss": round(trade_sl_price, 6),
                                })
                                size -= pt_size
                                if size <= 0.0001:
                                    in_position = False
                                    size = 0.0
                                    break
                        else:
                            # Not EOD yet, skip
                            continue
                    
                    elif isinstance(dist_frac, str) and dist_frac.startswith("TIME:"):
                        try:
                            tp_mins = float(dist_frac.split(":")[1])
                        except:
                            tp_mins = 0.0
                        elapsed_mins = (timestamps[i] - entry_time) / 6e10 if timestamps is not None else 0.0
                        if elapsed_mins >= tp_mins:
                            partial_tp_hits[pt_idx] = True
                            pt_exit_price = close[i]
                            
                            slip = pt_exit_price * slippage
                            net_pt_exit = (pt_exit_price - slip) if is_long else (pt_exit_price + slip)
                            pt_size = pyr_base * cap_frac
                            pt_size = min(pt_size, size)
                            if pt_size > 0:
                                if is_long:
                                    gross_pnl = (net_pt_exit - avg_entry_price) * pt_size
                                else:
                                    gross_pnl = (avg_entry_price - net_pt_exit) * pt_size
                                
                                if fee_type == "FLAT":
                                    fee_amount = fees * pt_size * 2
                                else:
                                    # % sobre el NOCIONAL de cada lado (entrada + salida),
                                    # no sobre el PnL: un breakeven tambien paga comision.
                                    fee_amount = (avg_entry_price + net_pt_exit) * pt_size * fees
                                pnl = gross_pnl - fee_amount
                                realized_pnl += pnl
                                capital_at_risk = avg_entry_price * pt_size
                                ret_pct = (pnl / capital_at_risk) * 100 if capital_at_risk > 0 else 0.0
                                trades.append({
                                    "entry_idx": entry_idx,
                                    "exit_idx": i,
                                    "entry_price": round(entry_price, 6),
                                    "avg_entry_price": round(avg_entry_price, 6),
                                    "exit_price": round(net_pt_exit, 6),
                                    "pnl": round(pnl, 4),
                                    "return_pct": round(ret_pct, 4),
                                    "direction": "Long" if is_long else "Short",
                                    "status": "Closed",
                                    "size": round(pt_size, 6),
                                    "exit_reason": "Partial TP (Time)",
                                    "fees": round(fee_amount, 4),
                                    "mae": round(mae, 4),
                                    "mfe": round(mfe, 4),
                                    "stop_loss": round(trade_sl_price, 6),
                                })
                                size -= pt_size
                                if size <= 0.0001:
                                    in_position = False
                                    size = 0.0
                                    break
                        else:
                            continue
                    
                    elif isinstance(dist_frac, str) and dist_frac.startswith("HOUR:"):
                        try:
                            parts = dist_frac.split(":")
                            tp_hour = int(parts[1])
                            tp_min = int(parts[2])
                        except Exception:
                            tp_hour, tp_min = 0, 0
                        
                        if timestamps is not None:
                            dt = datetime.fromtimestamp(timestamps[i] / 1e9, tz=timezone.utc)
                            if dt.hour > tp_hour or (dt.hour == tp_hour and dt.minute >= tp_min):
                                partial_tp_hits[pt_idx] = True
                                pt_exit_price = close[i]
                                
                                slip = pt_exit_price * slippage
                                net_pt_exit = (pt_exit_price - slip) if is_long else (pt_exit_price + slip)
                                pt_size = pyr_base * cap_frac
                                pt_size = min(pt_size, size)
                                if pt_size > 0:
                                    if is_long:
                                        gross_pnl = (net_pt_exit - avg_entry_price) * pt_size
                                    else:
                                        gross_pnl = (avg_entry_price - net_pt_exit) * pt_size
                                    
                                    if fee_type == "FLAT":
                                        fee_amount = fees * pt_size * 2
                                    else:
                                        # % sobre el NOCIONAL de cada lado (entrada + salida).
                                        fee_amount = (avg_entry_price + net_pt_exit) * pt_size * fees
                                    pnl = gross_pnl - fee_amount
                                    realized_pnl += pnl
                                    capital_at_risk = avg_entry_price * pt_size
                                    ret_pct = (pnl / capital_at_risk) * 100 if capital_at_risk > 0 else 0.0
                                    trades.append({
                                        "entry_idx": entry_idx,
                                        "exit_idx": i,
                                        "entry_price": round(entry_price, 6),
                                        "avg_entry_price": round(avg_entry_price, 6),
                                        "exit_price": round(net_pt_exit, 6),
                                        "pnl": round(pnl, 4),
                                        "return_pct": round(ret_pct, 4),
                                        "direction": "Long" if is_long else "Short",
                                        "status": "Closed",
                                        "size": round(pt_size, 6),
                                        "exit_reason": "Partial TP (Hour)",
                                        "fees": round(fee_amount, 4),
                                        "mae": round(mae, 4),
                                        "mfe": round(mfe, 4),
                                        "stop_loss": round(trade_sl_price, 6),
                                    })
                                    size -= pt_size
                                    if size <= 0.0001:
                                        in_position = False
                                        size = 0.0
                                        break
                        else:
                            continue
                    
                    elif is_long:
                        pt_level = entry_price * (1 + dist_frac)
                        if price_for_tp >= pt_level:
                            # Partial exit
                            partial_tp_hits[pt_idx] = True
                            # If it gapped above target at open, take the open, else the target
                            pt_exit_price = max(pt_level, open_[i])
                            pt_exit_price = min(pt_exit_price, high[i]) # Bound by high
                            
                            slip = pt_exit_price * slippage
                            net_pt_exit = pt_exit_price - slip
                            # Close cap_frac of original position
                            pt_size = pyr_base * cap_frac
                            pt_size = min(pt_size, size)  # Can't close more than remaining
                            if pt_size > 0:
                                gross_pnl = (net_pt_exit - avg_entry_price) * pt_size
                                if fee_type == "FLAT":
                                    fee_amount = fees * pt_size * 2
                                else:
                                    # % sobre el NOCIONAL de cada lado (entrada + salida),
                                    # no sobre el PnL: un breakeven tambien paga comision.
                                    fee_amount = (avg_entry_price + net_pt_exit) * pt_size * fees
                                pnl = gross_pnl - fee_amount
                                realized_pnl += pnl
                                capital_at_risk = avg_entry_price * pt_size
                                ret_pct = (pnl / capital_at_risk) * 100 if capital_at_risk > 0 else 0.0
                                trades.append({
                                    "entry_idx": entry_idx,
                                    "exit_idx": i,
                                    "entry_price": round(entry_price, 6),
                                    "avg_entry_price": round(avg_entry_price, 6),
                                    "exit_price": round(net_pt_exit, 6),
                                    "pnl": round(pnl, 4),
                                    "return_pct": round(ret_pct, 4),
                                    "direction": "Long" if is_long else "Short",
                                    "status": "Closed",
                                    "size": round(pt_size, 6),
                                    "exit_reason": "Partial TP",
                                    "fees": round(fee_amount, 4),
                                    "mae": round(mae, 4),
                                    "mfe": round(mfe, 4),
                                    "stop_loss": round(trade_sl_price, 6),
                                })
                                size -= pt_size
                                if size <= 0.0001:
                                    # All position closed via partial TPs
                                    in_position = False
                                    size = 0.0
                                    break
                    else:
                        pt_level = entry_price * (1 - dist_frac)
                        if price_for_tp <= pt_level:
                            partial_tp_hits[pt_idx] = True
                            # If it gapped below target at open, take the open, else the target
                            pt_exit_price = min(pt_level, open_[i])
                            pt_exit_price = max(pt_exit_price, low[i]) # Bound by low
                            
                            slip = pt_exit_price * slippage
                            net_pt_exit = pt_exit_price + slip
                            pt_size = pyr_base * cap_frac
                            pt_size = min(pt_size, size)
                            if pt_size > 0:
                                gross_pnl = (avg_entry_price - net_pt_exit) * pt_size
                                if fee_type == "FLAT":
                                    fee_amount = fees * pt_size * 2
                                else:
                                    # % sobre el NOCIONAL de cada lado (entrada + salida),
                                    # no sobre el PnL: un breakeven tambien paga comision.
                                    fee_amount = (avg_entry_price + net_pt_exit) * pt_size * fees
                                pnl = gross_pnl - fee_amount
                                realized_pnl += pnl
                                capital_at_risk = avg_entry_price * pt_size
                                ret_pct = (pnl / capital_at_risk) * 100 if capital_at_risk > 0 else 0.0
                                trades.append({
                                    "entry_idx": entry_idx,
                                    "exit_idx": i,
                                    "entry_price": round(entry_price, 6),
                                    "avg_entry_price": round(avg_entry_price, 6),
                                    "exit_price": round(net_pt_exit, 6),
                                    "pnl": round(pnl, 4),
                                    "return_pct": round(ret_pct, 4),
                                    "direction": "Long" if is_long else "Short",
                                    "status": "Closed",
                                    "size": round(pt_size, 6),
                                    "exit_reason": "Partial TP",
                                    "fees": round(fee_amount, 4),
                                    "mae": round(mae, 4),
                                    "mfe": round(mfe, 4),
                                    "stop_loss": round(trade_sl_price, 6),
                                })
                                size -= pt_size
                                if size <= 0.0001:
                                    in_position = False
                                    size = 0.0
                                    break
                # If all position was closed via partials, skip the rest of exit logic
                if not in_position:
                    # La posicion se vacio por parciales: la bitacora de la
                    # piramide se cuelga de la ultima leg para no perderse.
                    if pyramid_mode and pyr_exec and trades:
                        trades[-1]["pyr_executions"] = pyr_exec
                        pyr_exec = []
                    equity[i] = init_cash + realized_pnl
                    prev_signal = bool(entries[i])
                    continue

            # Track MAE and MFE as positive percentages based on absolute price excursions
            # We calculate this *before* forcing 'EOD' exits so we don't accidentally ignore wicks.
            # But we calculate it *after* setting exit_price for intrabar STOPS so we can bound the excursions.
            if not is_restricted:
                bound_low = low[i]
                bound_high = high[i]
                
                if exit_triggered and exit_reason in ["SL", "Trailing", "TP"]:
                    # Do not let the recorded excursion go further than the executed stop/TP price
                    if exit_reason in ["SL", "Trailing"]:
                        if is_long:
                            bound_low = max(low[i], exit_price)
                        else:
                            bound_high = min(high[i], exit_price)
                    elif exit_reason == "TP":
                        if is_long:
                            bound_high = min(high[i], exit_price)
                        else:
                            bound_low = max(low[i], exit_price)

                if is_long:
                    mae_pct = ((entry_price - bound_low) / entry_price) * 100
                    mfe_pct = ((bound_high - entry_price) / entry_price) * 100
                else:
                    mae_pct = ((bound_high - entry_price) / entry_price) * 100
                    mfe_pct = ((entry_price - bound_low) / entry_price) * 100
                    
                if mae_pct > mae:
                    mae = mae_pct
                if mfe_pct > mfe:
                    mfe = mfe_pct

            # elapsed time exit
            if not exit_triggered and elapsed_limit > 0 and timestamps is not None:
                elapsed_mins = (timestamps[i] - entry_time) / 6e10
                trigger = False
                if elapsed_operator in ("GREATER_THAN_OR_EQUAL", "GTE"):
                    trigger = (elapsed_mins >= elapsed_limit)
                elif elapsed_operator in ("GREATER_THAN", "GT"):
                    trigger = (elapsed_mins > elapsed_limit)
                elif elapsed_operator in ("LESS_THAN", "LT"):
                    trigger = (elapsed_mins < elapsed_limit)
                elif elapsed_operator in ("LESS_THAN_OR_EQUAL", "LTE"):
                    trigger = (elapsed_mins <= elapsed_limit)
                elif elapsed_operator in ("EQUAL", "EQ"):
                    trigger = (elapsed_mins == elapsed_limit)
                else:
                    trigger = (elapsed_mins >= elapsed_limit)

                if trigger:
                    exit_triggered = True
                    exit_price = close[i]
                    exit_reason = "Time Limit"

            # signal exit
            if not exit_triggered and exits[i] and not skip_exits:
                exit_triggered = True
                if look_ahead_prevention and i < n - 1:
                    exit_price = open_[i + 1]
                    eff_exit_idx = i + 1
                else:
                    exit_price = close[i]
                exit_reason = "Signal"

            # cierre forzado por el cortacircuitos de perdida diaria. Va
            # ANTES del de fin de dia y DESPUES de stop, TP y señal: si la
            # operacion iba a cerrar sola en esta misma barra, manda su motivo
            # real — el corte no debe robarle la autoria a un stop.
            if (
                not exit_triggered
                and force_close_at > 0
                and timestamps is not None
                and timestamps[i] >= force_close_at
            ):
                exit_triggered = True
                exit_price = close[i]
                exit_reason = "Daily Limit"

            # end-of-day forced close
            if not exit_triggered and i == n - 1:
                exit_triggered = True
                exit_price = close[i]
                exit_reason = "EOD"

            if exit_triggered:
                slip = exit_price * slippage
                net_exit = (exit_price - slip) if is_long else (exit_price + slip)
                
                # Gross PnL
                if is_long:
                    gross_pnl = (net_exit - avg_entry_price) * size
                else:
                    gross_pnl = (avg_entry_price - net_exit) * size

                # Fee calculation depends on fee_type
                if fee_type == "FLAT":
                    # FLAT = $ POR ACCION, cobrado en los DOS lados (fix de
                    # 2026-08-22). 0,003 con 100 acciones = 0,30 $ al comprar +
                    # 0,30 $ al vender. Antes era `fees * 2`: una cantidad fija
                    # por operacion que IGNORABA el tamaño, asi que con 10.000
                    # acciones cobraba 1 centimo donde el broker cobra 60 $.
                    fee_amount = fees * size * 2
                else:
                    # Percentage fee sobre el NOCIONAL de cada lado (entrada +
                    # salida), como cobra un broker real. Antes se aplicaba
                    # sobre |PnL bruto|, con lo que un trade en tablas pagaba
                    # $0 de comision moviera las acciones que moviera.
                    fee_amount = (avg_entry_price + net_exit) * size * fees
                
                # Net PnL is Gross PnL minus Fees
                pnl = gross_pnl - fee_amount

                realized_pnl += pnl
                # For capital at risk, we just use the entry capital required
                capital_at_risk = avg_entry_price * size
                ret_pct = (pnl / capital_at_risk) * 100 if capital_at_risk > 0 else 0.0

                trades.append({
                    "entry_idx": entry_idx,
                    "exit_idx": eff_exit_idx,
                    "entry_price": round(entry_price, 6),
                    "avg_entry_price": round(avg_entry_price, 6),
                    "exit_price": round(net_exit, 6),
                    "pnl": round(pnl, 4),
                    "fees": round(fee_amount, 4),
                    "return_pct": round(ret_pct, 4),
                    "direction": "Long" if is_long else "Short",
                    "status": "Closed",
                    "size": round(size, 6),
                    "exit_reason": exit_reason,
                    "mae": round(mae, 4),
                    "mfe": round(mfe, 4),
                    "stop_loss": round(trade_sl_price, 6),
                })
                if pyramid_mode and pyr_exec:
                    trades[-1]["pyr_executions"] = pyr_exec
                    pyr_exec = []
                in_position = False
                size = 0.0


        # --- Piramidacion: condiciones logicas POST-entrada (2026-08-22) ---
        # Orden dentro de la barra: DESPUES de todas las salidas y solo si la
        # posicion sigue viva -- una barra que toca el stop no piramida.
        #
        # Las piramides son INDIVIDUALES por defecto: cada una vigila su propia
        # condicion en paralelo, sin anclaje entre ellas (la numeracion de la
        # UI es solo orden de lista). Con pyramid_sequential=True, cada nivel
        # solo se ARMA cuando el anterior ya ha disparado al menos una vez.
        #
        # Cada nivel dispara hasta `max_fires` veces por trade (decision del
        # usuario 2026-08-22: configurable; antes era 1 fija), SOLO en FLANCOS
        # de su señal (False->True): una condicion sostenida muchas barras es
        # UN evento, no uno por barra — sin esto, "gana mas de X%" con 3 veces
        # dispararia en 3 barras seguidas. Con señales de cruce (eventos de una
        # barra) el flanco es identico al comportamiento anterior. Todo se
        # rearma con cada entrada nueva; TP/SL/parciales corren en paralelo.
        if pyramid_mode and in_position and i > entry_idx:
            # SECUENCIAL: la piramide avanza EN LINEA y no vuelve atras. Solo
            # vigila el primer nivel que aun no haya agotado sus veces; cuando
            # las agota se pasa al siguiente y el anterior ya no dispara mas en
            # este trade. Una reentrada rearma la secuencia entera.
            # INDIVIDUAL: `nivel_activo` es None y todos vigilan a la vez, como
            # entradas independientes.
            nivel_activo = None
            if riesgo_bloqueado:
                # Cortado el dia, un añadido es riesgo nuevo sobre una posicion
                # viva: se bloquea igual que una entrada. `pyr_prev_sig` NO se
                # actualiza aqui a proposito — si el dia no estuviera cortado el
                # flanco seguiria intacto, y asi el bloqueo no altera el estado
                # de los niveles, solo impide ejecutar.
                pyramid_levels_iter = []
            else:
                pyramid_levels_iter = pyramid_levels
            if pyramid_sequential:
                nivel_activo = next(
                    (k for k in range(len(pyramid_levels))
                     if pyr_fired[k] < pyramid_levels[k]["max_fires"]),
                    -1,
                )
            for lv_idx, lv in enumerate(pyramid_levels_iter):
                if pyr_fired[lv_idx] >= lv["max_fires"]:
                    continue
                # Mientras un nivel no tiene el turno NO se actualiza su estado
                # de señal, para que al llegarle pueda disparar aunque su
                # condicion llevara rato cumpliendose. Antes el flanco se
                # consumia estando desarmado y el nivel quedaba muerto.
                if nivel_activo is not None and lv_idx != nivel_activo:
                    continue
                # El disparo es en el paso de "no se cumple" a "se cumple", pero
                # medido DENTRO del trade: `pyr_prev_sig` arranca en False en
                # cada entrada, asi que una condicion que YA se cumplia al entrar
                # dispara en la primera barra. Antes se miraba la barra anterior
                # del array completo y esa condicion no disparaba jamas.
                sig_now = bool(lv["signals"][i])
                dispara = sig_now and not pyr_prev_sig[lv_idx]
                pyr_prev_sig[lv_idx] = sig_now
                if not dispara:
                    continue
                # El disparo se contabiliza SOLO si llega a ejecutarse (mas
                # abajo). Contarlo aqui gastaba una de las "veces" aunque el
                # add/reduce se descartara por precio o por caja, dejando el
                # nivel inutilizado para el resto del trade con el default
                # veces=1.
                # Norma fija del usuario: si se cumple una condicion, se opera en
                # la vela INMEDIATAMENTE SIGUIENTE. Vale para las entradas y
                # tambien para la piramide; antes los add/reduce se ejecutaban al
                # cierre de la propia vela de la señal (lookahead e incoherente
                # con las entradas).
                if look_ahead_prevention:
                    if i >= n - 1:
                        continue          # no hay vela siguiente donde operar
                    px = open_[i + 1]
                    exec_idx = i + 1
                else:
                    px = close[i]
                    exec_idx = i
                if px <= 0:
                    continue
                slip = px * slippage
                if lv["action"] == "add":
                    # AÑADIR: % del EQUITY de la cuenta (decision del usuario),
                    # convertido a acciones al precio de la barra con slippage
                    # de entrada. Tope: el coste total de la posicion no puede
                    # superar el cash disponible (misma regla que la entrada).
                    add_px = (px + slip) if is_long else (px - slip)
                    if add_px <= 0:
                        continue
                    cash_now = init_cash + realized_pnl
                    if cash_now <= 0:
                        continue
                    # 'pct' -> % del EQUITY de la cuenta; 'usd' -> una cantidad
                    # fija en dolares. En ambos casos se convierte a acciones al
                    # precio de la barra.
                    if lv.get("unit") == "usd":
                        add_cash = float(lv.get("amount_usd", 0.0))
                    else:
                        add_cash = cash_now * lv["capital_frac"]
                    if add_cash <= 0:
                        continue
                    # TOPE DE CAJA (regla del usuario, 2026-08-23): entrada mas
                    # añadidos NUNCA pueden comprometer mas capital del que hay
                    # en la cuenta, contado SIN el flotante y valorando lo que ya
                    # se tiene AL PRECIO AL QUE SE COMPRO (`avg_entry_price`), no
                    # al de ahora. Si no cabe entero, se RECORTA hasta el limite
                    # en vez de anularse.
                    #   fijo: apuesto 99 y añado 1 -> cabe; pido 2 -> añade 1.
                    #   %:    entro al 90% y añado 10% -> cabe; el segundo 10% no.
                    # El tope anterior contaba las acciones vivas al precio
                    # ACTUAL, asi que el margen se encogia justo cuando el trade
                    # iba GANANDO, y con la entrada al 100% del equity ningun
                    # añadido llegaba a ejecutarse nunca, en silencio.
                    comprometido = avg_entry_price * size
                    disponible = cash_now - comprometido
                    if disponible <= 0:
                        continue
                    # COMO SE CONVIERTE EL IMPORTE EN ACCIONES. Cada nivel
                    # elige su modo, independiente del de la entrada: un
                    # anyadido puede ir por distancia al stop aunque la entrada
                    # vaya por valor de mercado, y al reves.
                    if lv.get("size_by_sl"):
                        # `add_cash` deja de ser capital y pasa a ser RIESGO: se
                        # divide por la distancia al stop, igual que la entrada.
                        dist_pyr = (abs(add_px - trade_sl_price)
                                    if trade_sl_price and trade_sl_price > 0 else 0.0)
                        add_size_pedido = (add_cash / dist_pyr if dist_pyr > 0
                                           else add_cash / add_px)
                        # Y con el tope hibrido del NIVEL, que tiene sus propios
                        # porcentajes: Jaume los reparte entre entrada y
                        # piramide para que la suma de las dos no pase de lo que
                        # acepta perder.
                        if lv.get("hybrid_stop"):
                            tope_pyr = tope_hibrido(
                                hybrid_capital if hybrid_capital else cash_now,
                                lv.get("hybrid_black_swan_pct"),
                                lv.get("hybrid_max_loss_pct"), add_px)
                            if tope_pyr is not None:
                                add_size_pedido = min(add_size_pedido, tope_pyr)
                    else:
                        add_size_pedido = add_cash / add_px
                    # El tope de caja se aplica siempre sobre el VALOR, venga el
                    # tamano de donde venga.
                    add_size = min(add_size_pedido, disponible / add_px)
                    add_cash_pedido = add_size_pedido * add_px
                    add_cash = add_size * add_px
                    # TOPE DE LOCATES: un anadido en corto sube el maximo del
                    # dia y con el la factura, asi que el cupo cuenta entrada
                    # MAS anadidos. Se recorta igual que con el tope de caja.
                    recortado_locates = False
                    if (not is_long) and max_locates > 0:
                        cupo_locates = max_locates * 100.0 - size
                        if cupo_locates <= 0:
                            continue
                        if add_size > cupo_locates:
                            add_size = cupo_locates
                            recortado_locates = True
                    if add_size <= 0:
                        continue
                    recortado = add_cash < add_cash_pedido - 1e-9
                    avg_entry_price = (avg_entry_price * size + add_px * add_size) / (size + add_size)
                    size += add_size
                    # La base de los TP parciales sigue a la posicion: crece con
                    # los añadidos y baja con las reducciones, pero NO con los
                    # parciales ya tomados. Asi 50%+50% cierra el 100% sin
                    # piramidar, y con 1000+1000 el 50% cierra 1000 (regla del
                    # usuario, 2026-08-23).
                    pyr_base += add_size
                    pyr_fired[lv_idx] += 1
                    pyr_exec.append({
                        "kind": "add",
                        "idx": exec_idx,
                        # timestamps va en nanosegundos; el grafico usa epoch en
                        # segundos, igual que entry_time_epoch/exit_time_epoch.
                        "time_epoch": int(timestamps[exec_idx] // 1_000_000_000) if timestamps is not None else None,
                        "price": round(add_px, 6),
                        "size": round(add_size, 6),
                        "level": lv_idx + 1,
                        "position_size": round(size, 6),
                        # Queda anotado cuando el tope de caja recorta, para que
                        # un añadido a medias no parezca uno normal.
                        **({"recortado_por_caja": round(add_cash_pedido, 2)} if recortado else {}),
                        **({"recortado_por_locates": int(max_locates)} if recortado_locates else {}),
                    })
                    if not is_long:
                        max_short_size_today = max(max_short_size_today, size)
                else:
                    # REDUCIR: % de la posicion FLOTANTE actual (coherente con
                    # los parciales en modo piramide). Es una leg de cierre
                    # normal: su pnl, sus fees por los dos lados y su registro.
                    # 'pct' -> % de la posicion FLOTANTE; 'usd' -> el nocional en
                    # dolares que se quiere cerrar, convertido a acciones al
                    # precio de la barra. Nunca mas de lo que queda vivo.
                    if lv.get("unit") == "usd":
                        red_size = min(size, float(lv.get("amount_usd", 0.0)) / px)
                    else:
                        red_size = min(size, size * lv["capital_frac"])
                    if red_size <= 0:
                        continue
                    net_red = (px - slip) if is_long else (px + slip)
                    if is_long:
                        gross_pnl = (net_red - avg_entry_price) * red_size
                    else:
                        gross_pnl = (avg_entry_price - net_red) * red_size
                    if fee_type == "FLAT":
                        fee_amount = fees * red_size * 2
                    else:
                        fee_amount = (avg_entry_price + net_red) * red_size * fees
                    pnl = gross_pnl - fee_amount
                    realized_pnl += pnl
                    capital_at_risk = avg_entry_price * red_size
                    ret_pct = (pnl / capital_at_risk) * 100 if capital_at_risk > 0 else 0.0
                    trades.append({
                        "entry_idx": entry_idx,
                        "exit_idx": exec_idx,
                        # entry_price = el fill REAL de la entrada (ancla); el
                        # precio medio ponderado va aparte. Antes aqui iba la
                        # media, asi que el grafico etiquetaba la vela de entrada
                        # con un precio que esa vela nunca toco.
                        "entry_price": round(entry_price, 6),
                        "avg_entry_price": round(avg_entry_price, 6),
                        "exit_price": round(net_red, 6),
                        "pnl": round(pnl, 4),
                        "return_pct": round(ret_pct, 4),
                        "direction": "Long" if is_long else "Short",
                        "status": "Closed",
                        "size": round(red_size, 6),
                        "exit_reason": "Pyramid Reduce",
                        "fees": round(fee_amount, 4),
                        "mae": round(mae, 4),
                        "mfe": round(mfe, 4),
                        "stop_loss": round(trade_sl_price, 6),
                    })
                    size -= red_size
                    pyr_base -= red_size
                    pyr_fired[lv_idx] += 1
                    pyr_exec.append({
                        "kind": "reduce",
                        "idx": exec_idx,
                        "time_epoch": int(timestamps[exec_idx] // 1_000_000_000) if timestamps is not None else None,
                        "price": round(net_red, 6),
                        "size": round(red_size, 6),
                        "level": lv_idx + 1,
                        "position_size": round(size, 6),
                        "pnl": round(pnl, 4),
                    })
                    if size <= 0.0001:
                        # La posicion se ha vaciado con esta reduccion: no
                        # habra trade de cierre, asi que la bitacora se cuelga
                        # de esta ultima leg.
                        trades[-1]["pyr_executions"] = pyr_exec
                        pyr_exec = []
                        in_position = False
                        size = 0.0
                        break

        # --- check entries ---
        # Edge Detection: only enter when signal turns from False to True.
        # This prevents re-entering in the same 'signal block'.
        current_signal = bool(entries[i])
        is_signal_trigger = current_signal and not prev_signal
        
        if not in_position and is_signal_trigger and i < n - 1 and not is_restricted and not riesgo_bloqueado:
            # Re-entry logic:
            can_enter = True
            if max_reentries >= 0:
                if total_trades > max_reentries:
                    can_enter = False
            elif not accumulate and total_trades > 0:
                can_enter = False
            
            if can_enter:
                available_cash = init_cash + realized_pnl
                if available_cash <= 0:
                    equity[i] = init_cash + realized_pnl
                    prev_signal = current_signal # Update for next loop
                    continue

                if look_ahead_prevention:
                    # Standard: enter on next open after signal
                    ep = open_[i + 1]
                    eff_entry_idx = i + 1
                else:
                    # Aggressive/Look-ahead: enter on current close
                    ep = close[i]
                    eff_entry_idx = i

                slip = ep * slippage
                entry_price = (ep + slip) if is_long else (ep - slip)
                if entry_price <= 0:
                    equity[i] = init_cash + realized_pnl
                    prev_signal = current_signal # Update for next loop
                    continue

                # Fees are now calculated purely on exit Gross PnL
                
                # Calculate Risk Amount ($)
                if risk_type == "PERCENT":
                    risk_amount = available_cash * (risk_r / 100.0)
                elif risk_type == "FIXED_RATIO":
                    # Ryan Jones Fixed Ratio formula
                    # N = 0.5 + 0.5 * sqrt(1 + (8 * Profit / Delta))
                    if realized_pnl > 0 and fixed_ratio_delta > 0:
                        import math
                        n_units = 0.5 + 0.5 * math.sqrt(1 + (8 * realized_pnl / fixed_ratio_delta))
                    else:
                        n_units = 1.0
                    risk_amount = risk_r * n_units
                else:
                    risk_amount = risk_r

                # Determine Stop Loss Price
                stop_loss_price = 0.0
                if hs_type == "Market Structure (HOD/LOD)":
                    val_struct = _structural_level(
                        hs_value, i, hods, lods, pm_highs, pm_lows, prev_highs, prev_lows,
                    )
                    if val_struct <= 0.0:
                        val_struct = entry_price * (0.95 if is_long else 1.05)

                    # Calculate sl_offset
                    offset_pct = float(hs_offset_pct) if hs_offset_pct is not None else 0.0
                    offset_op = hs_operator or ">="
                    sign = 1.0 if offset_op in (">", ">=") else -1.0
                    sl_offset = sign * offset_pct / 100.0
                    stop_loss_price = val_struct * (1.0 + sl_offset)

                    # Un stop estructural que queda en el lado GANADOR de la
                    # entrada no es un stop: el chequeo de corto `high >= SL`
                    # dispararia en la propia vela y haria fill al precio del
                    # nivel (fuera del rango de la vela), contando un
                    # beneficio instantaneo imposible. Nivel invalidado =
                    # premisa muerta: no se entra. Excepciones: en REENTRADAS
                    # (tras un stop-out es normal quedar pasado el nivel) se
                    # rescatera con `hs_fallback_value` aplicando el mismo
                    # offset; con `hs_fallback_first` tambien la primera
                    # entrada. Si el respaldo tambien queda invalidado, no se
                    # entra.
                    if not _sl_side_valid(stop_loss_price, entry_price, is_long):
                        if hs_fallback_value and (hs_fallback_first or total_trades > 0):
                            fb_level = _structural_level(
                                hs_fallback_value, i, hods, lods, pm_highs, pm_lows, prev_highs, prev_lows,
                            )
                            if fb_level > 0:
                                fb_stop = fb_level * (1.0 + sl_offset)
                                if _sl_side_valid(fb_stop, entry_price, is_long):
                                    stop_loss_price = fb_stop
                        if not _sl_side_valid(stop_loss_price, entry_price, is_long):
                            equity[i] = init_cash + realized_pnl
                            prev_signal = current_signal
                            continue
                elif sl_stop is not None and sl_stop > 0:
                    stop_loss_price = entry_price * (1 - sl_stop) if is_long else entry_price * (1 + sl_stop)

                if size_by_sl:
                    dist = abs(entry_price - stop_loss_price) if stop_loss_price > 0.0 else 0.0
                    if dist > 0.0:
                        size = risk_amount / dist
                    else:
                        size = risk_amount / entry_price
                else:
                    # Traditional sizing: deploy risk_amount into the position
                    size = risk_amount / entry_price

                # TOPE HIBRIDO: por SL pero sin pasarse de la exposicion que
                # un evento de cola convertiria en una perdida inasumible.
                # RECORTA, no anula — igual que el tope de caja y el de locates.
                if hybrid_stop and size_by_sl:
                    tope = tope_hibrido(hybrid_capital if hybrid_capital
                                        else init_cash + realized_pnl,
                                        hybrid_black_swan_pct,
                                        hybrid_max_loss_pct, entry_price)
                    if tope is not None:
                        size = min(size, tope)

                # Cap size by available cash
                max_size = available_cash / entry_price
                size = min(size, max_size)

                # Tope de locates: en corto, nunca mas acciones de las que
                # cubren los paquetes que se esta dispuesto a alquilar.
                if (not is_long) and max_locates > 0:
                    size = min(size, max_locates * 100.0)

                if size > 0:
                    # Track Max Short Size for Locates
                    if not is_long:
                        max_short_size_today = max(max_short_size_today, size)

                    in_position = True
                    entry_idx = eff_entry_idx
                    entry_time = timestamps[entry_idx] if timestamps is not None else 0
                    trade_sl_price = stop_loss_price
                    trail_extreme = entry_price
                    trail_activated = False
                    mae = 0.0
                    mfe = 0.0
                    original_size = size
                    avg_entry_price = entry_price
                    # La piramide va SIEMPRE asociada a la entrada: cada
                    # entrada (reentradas incluidas) rearma sus niveles.
                    pyr_fired = [0] * len(pyramid_levels) if pyramid_mode else []
                    pyr_prev_sig = [False] * len(pyramid_levels) if pyramid_mode else []
                    pyr_base = size
                    # Bitacora de las ejecuciones de piramide de ESTA posicion.
                    # Viaja pegada al trade de cierre (`pyr_executions`) para
                    # poder pintarlas en el grafico: un `add` no genera trade
                    # propio, asi que sin esto no deja ningun rastro.
                    pyr_exec = []
                    partial_tp_hits = [False] * len(partial_take_profits) if partial_take_profits else []
                    total_trades += 1
                else:
                    equity[i] = available_cash
        
        # Always update signal state for next bar's edge detection
        prev_signal = current_signal

        # --- equity ---
        current_equity = init_cash + realized_pnl
        if in_position:
            if is_long:
                unrealized = (close[i] - avg_entry_price) * size
            else:
                unrealized = (avg_entry_price - close[i]) * size
            equity[i] = current_equity + unrealized
        else:
            equity[i] = current_equity

    # Deduct Daily Locates Fee
    import math
    daily_locates_fee = 0.0
    if max_short_size_today > 0 and locates_cost > 0:
        if locate_type == "PERCENT":
            if risk_type == "PERCENT":
                day_risk_unit = init_cash * (risk_r / 100.0)
            else:
                day_risk_unit = risk_r
            cost_per_100 = day_risk_unit * (locates_cost / 100.0)
        else:
            cost_per_100 = locates_cost

        blocks_of_100 = math.ceil(max_short_size_today / 100.0)
        daily_locates_fee = blocks_of_100 * cost_per_100

        # Deliberately NOT attributed to any single trade's pnl/fees: it is a
        # cost of the ticker's day as a whole (one locate covers every short of
        # that ticker that day), not of whichever trade happened to go first.
        # Attaching it to one trade's pnl used to flip that trade's win/loss and
        # skew win rate / profit factor / avg win-loss for the ticker. The caller
        # nets `daily_locates_fee` into the day/portfolio totals instead (see
        # backend/app/services/backtest_service.py and backtest_signals.py).
        #
        # `pnl_with_locates` is a SEPARATE, cost-inclusive field kept only for
        # robustness reconstruction (Monte Carlo / WFO / stress rebuild the
        # equity curve from per-trade R-multiples, not from the real equity
        # array, so they need a cost-inclusive value or they'd silently ignore
        # locates). It intentionally keeps the old first-short-trade attribution
        # — fine for a statistical reconstruction, but never used for display,
        # win rate, or any other per-trade classification.
        for t in trades:
            t["pnl_with_locates"] = t["pnl"]
        for t in trades:
            if t["direction"] == "Short":
                t["pnl_with_locates"] = round(t["pnl"] - daily_locates_fee, 4)
                break

        # Update equity curve retroactively downwards so it reflects the end of day state.
        # In a perfect world we would apply it exactly when the short is taken,
        # but applying at EOF keeps accounting perfectly aligned with the total.
        for i in range(len(equity)):
            equity[i] -= daily_locates_fee

    # Always update signal state for next bar's edge detection
    prev_signal = current_signal

    # Finalize result
    results = {"equity": equity, "trades": trades, "locates_fee": daily_locates_fee}
    if risk_type == "PERCENT":
        results["last_risk_amount"] = risk_amount
    else:
        results["last_risk_amount"] = risk_r
        
    return results
