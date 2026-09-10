"""
Computes technical indicators from OHLCV data.
Numba-accelerated numpy implementations for maximum performance.

Supports the full IndicatorConfig schema (BTT March 2026):
  name, period, period2, period3, stdDev, multiplier, offset,
  days_lookback, calc_on_heikin, time_hour, time_minute, time_condition
"""

import os

import numpy as np
import pandas as pd
from numba import njit

try:
    import talib as _talib
except ImportError:
    _talib = None

try:
    import pandas_ta as ta
except ImportError:
    ta = None


def _safe_float(val) -> float:
    if val is None or pd.isna(val):
        return np.nan
    try:
        return float(val)
    except Exception:
        return np.nan


# -- Tabla diaria de "Overhead last X days" ---------------------------------
# Velas DIARIAS de sesion regular (09:30-16:00), en un parquet APARTE que genera
# `backend/scripts/construir_daily_overhead.py`. NO forma parte del lago ni lo
# modifica, y se lee con `read_parquet` de DISCO: no abre `local_data.duckdb`,
# asi que no compite por el cerrojo de DuckDB con el resto del backend.
#
# Cache por ticker: ticker -> dict con el indice de fechas y arrays numpy.
_overhead_cache: dict = {}
_overhead_aviso_dado = False
_OVERHEAD_COLS = ("o", "h", "l", "c", "v", "cum_split")
# Que columna de la vela diaria es el NIVEL, segun `overhead_ref`.
_OVERHEAD_REF_COL = {"high": "h", "low": "l", "open": "o", "close": "c"}


def _overhead_ruta() -> str:
    return os.getenv("OVERHEAD_DAILY_PARQUET", "").strip()


def _overhead_vacio() -> dict:
    d = {"fechas": pd.Index([], dtype=object)}
    d.update({k: np.empty(0, dtype=np.float64) for k in _OVERHEAD_COLS})
    return d


def _overhead_avisar_falta(ruta: str) -> None:
    """Avisa UNA vez de que la tabla no esta.

    Sin esto, un fichero que falta daria NaN en silencio en todos los
    ticker-dias y pareceria que el indicador simplemente no encuentra niveles.
    """
    global _overhead_aviso_dado
    if _overhead_aviso_dado:
        return
    _overhead_aviso_dado = True
    if not ruta:
        print("[ERROR] 'Overhead last X days' necesita OVERHEAD_DAILY_PARQUET en "
              "backend/.env y no esta puesto. El indicador dara NaN.")
    else:
        print("[ERROR] 'Overhead last X days': no encuentro la tabla en "
              + ruta + ". Generala con backend/scripts/construir_daily_overhead.py. "
              "Mientras tanto el indicador dara NaN.")


def prefetch_overhead_daily(tickers) -> None:
    """Carga en memoria las velas diarias de los tickers pedidos.

    Podado por ticker sobre un parquet ORDENADO por ticker, que es lo que le
    permite a DuckDB podar row-groups en vez de escanear 19 M de filas. Medido
    en el lago local: 1.200 tickers x historia completa en ~4,5 s en frio y
    ~0,9 s en caliente, contra ~32 s leyendo `daily_metrics` particionado.

    SIN filtro de fechas a proposito: el indicador mira HACIA ATRAS desde el dia
    del trade, asi que recortar por ano truncaria la ventana al cruzar el cambio
    de ano y cambiaria el resultado en silencio.
    """
    global _overhead_cache
    if not tickers:
        return
    pendientes = [t for t in tickers if t and t not in _overhead_cache]
    if not pendientes:
        return

    ruta = _overhead_ruta()
    if not ruta or not os.path.exists(ruta):
        _overhead_avisar_falta(ruta)
        for t in pendientes:
            _overhead_cache[t] = _overhead_vacio()
        return

    import time
    t0 = time.time()
    try:
        import duckdb
        con = duckdb.connect()
        try:
            marcas = ",".join(["?"] * len(pendientes))
            ruta_sql = ruta.replace("'", "''")
            df_all = con.execute(
                "SELECT ticker, d, o, h, l, c, v, cum_split "
                "FROM read_parquet('" + ruta_sql + "') "
                "WHERE ticker IN (" + marcas + ") ORDER BY ticker, d",
                pendientes,
            ).fetchdf()
        finally:
            con.close()

        df_all["d"] = pd.to_datetime(df_all["d"]).dt.strftime("%Y-%m-%d")
        for tk, grupo in df_all.groupby("ticker", sort=False):
            grupo = grupo[~grupo["d"].duplicated(keep="first")]
            entrada = {"fechas": pd.Index(grupo["d"].values)}
            for col in _OVERHEAD_COLS:
                entrada[col] = grupo[col].to_numpy(dtype=np.float64)
            _overhead_cache[tk] = entrada
        print("[INFO] Overhead: {:,} velas diarias de {} tickers en {:.2f}s".format(
            len(df_all), len(pendientes), time.time() - t0))
    except Exception as e:
        print("[ERROR] Overhead: fallo al cargar la tabla diaria: " + str(e))

    # Los que no devolvieron nada (o fallaron) se cachean vacios para no repetir
    # la consulta en cada ticker-dia.
    for t in pendientes:
        if t not in _overhead_cache:
            _overhead_cache[t] = _overhead_vacio()


# Nombre historico: lo llaman `backtest_service` y `optimization_service`.
prefetch_daily_ohlc = prefetch_overhead_daily


def _overhead_nivel(name, close, volume, ds, lookback,
                    extremo, ref, regla_volumen) -> pd.Series:
    """"Overhead last X days": el nivel que dejo el dia mas extremo de la ventana.

    DOS PASOS, EN ESTE ORDEN (semantica de Jaume, 7-sep-2026):
      1. Se busca el dia MAS EXTREMO de los ultimos X dias de cotizacion: el del
         maximo mas alto (`extremo="max"`) o el del minimo mas bajo (`"min"`).
      2. Se mira el volumen DE ESE DIA y se compara con el volumen acumulado de
         HOY hasta la vela actual. Si la regla no se cumple, el nivel no existe
         (NaN) y la condicion es falsa.

    **NO es** "filtrar los dias por volumen y quedarse con el maximo de los que
    pasen": eso daria otro nivel. Si el maximo lo hizo un dia flojo, aqui la
    senal se descarta, no se baja al siguiente techo. Es la semantica que pidio
    Jaume, y la diferencia importa.

    `ref` elige QUE PRECIO de ese dia es el nivel (high/low/open/close): el
    maximo suele ser una mecha que nadie defiende, mientras que el cierre del
    dia del spike si es resistencia de verdad.

    AJUSTE POR SPLITS, relativo al DIA DEL TRADE:
        precio  = precio[P] * cum[T]/cum[P]
        volumen = volumen[P] / (cum[T]/cum[P])
    Sin esto, tras un contrasplit 20:1 el nivel queda 20 veces por debajo del
    precio y "cruza por encima" se cumple en la primera vela del dia, siempre,
    sin error y sin log. Cae un split dentro de la ventana en el 4,3% de los
    dias de gap con 30 dias de lookback, y en el 16,9% con un ano.

    Como el volumen de hoy va creciendo, el nivel puede APARECER o DESAPARECER
    durante el dia. Es a proposito.
    """
    vacio = pd.Series(np.nan, index=close.index)
    ticker = ds.get("ticker") if ds else None
    if not ticker:
        return vacio
    if not (ds and ds.get("date")):
        return vacio
    fecha = str(ds["date"])[:10]

    es_min = name in ("Low of last X days", "Min of last X days")
    if extremo not in ("max", "min"):
        extremo = "min" if es_min else "max"
    if ref not in _OVERHEAD_REF_COL:
        ref = "low" if es_min else "high"

    lookback = int(lookback) if lookback else 5
    if lookback <= 0:
        return vacio

    global _overhead_cache
    if ticker not in _overhead_cache:
        prefetch_overhead_daily([ticker])
    tabla = _overhead_cache.get(ticker) or _overhead_vacio()
    fechas = tabla["fechas"]
    if len(fechas) == 0:
        return vacio
    try:
        pos = int(fechas.get_loc(fecha))
    except KeyError:
        # El dia del trade no esta en la tabla diaria: sin ancla no hay escala de
        # splits fiable, asi que NO se inventa un nivel.
        return vacio

    fin = pos                            # exclusivo: hoy nunca entra
    ini = max(0, fin - lookback)
    if ini >= fin:
        return vacio

    cum = tabla["cum_split"]
    factor = cum[pos] / cum[ini:fin]     # escala de cada dia -> escala de hoy
    base = (tabla["h"] if extremo == "max" else tabla["l"])[ini:fin] * factor
    if not np.isfinite(base).any():
        return vacio
    k = int(np.nanargmax(base) if extremo == "max" else np.nanargmin(base))

    nivel = float(tabla[_OVERHEAD_REF_COL[ref]][ini + k] * factor[k])
    if not np.isfinite(nivel):
        return vacio

    if regla_volumen not in ("gt", "lt"):
        return pd.Series(nivel, index=close.index)

    vol_dia = float(tabla["v"][ini + k] / factor[k])
    if not np.isfinite(vol_dia):
        return vacio
    vol_hoy = volume.cumsum().to_numpy(dtype=np.float64)
    cumple = (vol_dia > vol_hoy) if regla_volumen == "gt" else (vol_dia < vol_hoy)
    return pd.Series(np.where(cumple, nivel, np.nan), index=close.index)


# ---------------------------------------------------------------------------
# Numba-accelerated indicator implementations
# ---------------------------------------------------------------------------

def _sma(values: np.ndarray, window: int) -> np.ndarray:
    """SMA via cumsum — already vectorized, no loop needed."""
    out = np.full(len(values), np.nan)
    if len(values) < window:
        return out
    cs = np.cumsum(values)
    out[window - 1] = cs[window - 1] / window
    out[window:] = (cs[window:] - cs[:-window]) / window
    return out


@njit(cache=True)
def _ema_core(values, window):
    n = len(values)
    alpha = 2.0 / (window + 1)
    out = np.empty(n, dtype=np.float64)
    for k in range(n):
        out[k] = np.nan
    # SE SALTAN LOS NaN DE CABECERA antes de sembrar.
    #
    # La siembra es la media de los primeros `window` valores. Sobre precios eso
    # esta bien —no hay NaN—, pero esta funcion tambien se aplica a la SALIDA de
    # otro indicador, y esa si empieza con NaN: la senal del MACD es una EMA de
    # la linea MACD, cuyos primeros `slow-1` valores (25 con el 26 por defecto)
    # son NaN. La suma salia NaN, la siembra salia NaN, y como cada valor
    # depende del anterior se propagaba hasta el final:
    #
    #     MACD            -> 275 valores de 300
    #     MACD Signal     ->   0 de 300     (todo NaN)
    #     MACD Histogram  ->   0 de 300     (todo NaN)
    #
    # Una comparacion contra NaN da False siempre, asi que una estrategia con
    # «MACD Signal» o «MACD Histogram» no operaba NUNCA, y lo hacia en silencio:
    # sin error, sin log, sin nada. Al DI+/DI- del ADX le pasaba lo mismo.
    #
    # Sin NaN de cabecera esto se comporta exactamente igual que antes.
    ini = 0
    while ini < n and np.isnan(values[ini]):
        ini += 1
    first_valid = ini + window - 1
    if first_valid >= n:
        return out
    s = 0.0
    for k in range(ini, ini + window):
        s += values[k]
    out[first_valid] = s / window
    for i in range(first_valid + 1, n):
        out[i] = alpha * values[i] + (1.0 - alpha) * out[i - 1]
    return out


def _ema(values: np.ndarray, window: int) -> np.ndarray:
    return _ema_core(np.ascontiguousarray(values, dtype=np.float64), window)


@njit(cache=True)
def _rsi_core(close, window):
    n = len(close)
    out = np.empty(n, dtype=np.float64)
    for k in range(n):
        out[k] = np.nan
    if n < 2:
        return out
    # Calculate deltas
    m = n - 1
    gain = np.empty(m, dtype=np.float64)
    loss = np.empty(m, dtype=np.float64)
    for i in range(m):
        d = close[i + 1] - close[i]
        gain[i] = d if d > 0.0 else 0.0
        loss[i] = -d if d < 0.0 else 0.0
    # EMA of gain/loss
    alpha = 2.0 / (window + 1)
    avg_g = np.empty(m, dtype=np.float64)
    avg_l = np.empty(m, dtype=np.float64)
    for k in range(m):
        avg_g[k] = np.nan
        avg_l[k] = np.nan
    fv = window - 1
    if fv < m:
        sg = 0.0
        sl = 0.0
        for k in range(window):
            sg += gain[k]
            sl += loss[k]
        avg_g[fv] = sg / window
        avg_l[fv] = sl / window
        for i in range(fv + 1, m):
            avg_g[i] = alpha * gain[i] + (1.0 - alpha) * avg_g[i - 1]
            avg_l[i] = alpha * loss[i] + (1.0 - alpha) * avg_l[i - 1]
    for i in range(m):
        ag = avg_g[i]
        al = avg_l[i]
        if al != al or ag != ag:  # NaN check
            out[i + 1] = np.nan
        elif al == 0.0:
            out[i + 1] = 100.0
        else:
            rs = ag / al
            out[i + 1] = 100.0 - 100.0 / (1.0 + rs)
    return out


def _rsi(close: np.ndarray, window: int) -> np.ndarray:
    return _rsi_core(np.ascontiguousarray(close, dtype=np.float64), window)


def _macd(close: np.ndarray, fast: int = 12, slow: int = 26, signal: int = 9) -> tuple:
    """Returns (macd_line, signal_line, histogram). Uses Numba-accelerated EMA."""
    c = np.ascontiguousarray(close, dtype=np.float64)
    ema_fast = _ema_core(c, fast)
    ema_slow = _ema_core(c, slow)
    macd_line = ema_fast - ema_slow
    signal_line = _ema_core(macd_line, signal)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


@njit(cache=True)
def _atr_core(high, low, close, window):
    n = len(close)
    tr = np.empty(n, dtype=np.float64)
    tr[0] = high[0] - low[0]
    for i in range(1, n):
        hl = high[i] - low[i]
        hc = abs(high[i] - close[i - 1])
        lc = abs(low[i] - close[i - 1])
        tr[i] = hl
        if hc > tr[i]:
            tr[i] = hc
        if lc > tr[i]:
            tr[i] = lc
    # SUAVIZADO DE WILDER (alpha = 1/n), que es el ATR canonico: el que usan
    # las plataformas y el que ya usaba `calculateATR` del grafico.
    #
    # ANTES ERA UNA EMA (alpha = 2/(n+1)) y no coincidia con el grafico: los dos
    # arrancan igual (media simple de los `window` primeros TR) y se separan
    # desde el SEGUNDO valor. Medido: hasta 8,5e-3 de diferencia sobre 300 velas.
    # Unificado el 2026-09-10 a peticion de Jaume, aprovechando que no habia
    # ninguna estrategia suya usando el ATR. Toca el indicador "ATR", el stop por
    # ATR y "ATR Extension" — los tres a la vez y en la misma direccion.
    alpha = 1.0 / window
    out = np.empty(n, dtype=np.float64)
    for k in range(n):
        out[k] = np.nan
    fv = window - 1
    if fv >= n:
        return out
    s = 0.0
    for k in range(window):
        s += tr[k]
    out[fv] = s / window
    for i in range(fv + 1, n):
        out[i] = alpha * tr[i] + (1.0 - alpha) * out[i - 1]
    return out


def _atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, window: int) -> np.ndarray:
    return _atr_core(
        np.ascontiguousarray(high, dtype=np.float64),
        np.ascontiguousarray(low, dtype=np.float64),
        np.ascontiguousarray(close, dtype=np.float64),
        window,
    )


def _vwap(high: np.ndarray, low: np.ndarray, close: np.ndarray, volume: np.ndarray) -> np.ndarray:
    typical = (high + low + close) / 3.0
    cum_tp_vol = np.cumsum(typical * volume)
    cum_vol = np.cumsum(volume)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(cum_vol != 0, cum_tp_vol / cum_vol, np.nan)


@njit(cache=True)
def _consecutive_count_core(signal):
    n = len(signal)
    result = np.zeros(n, dtype=np.float64)
    count = 0.0
    for i in range(n):
        if signal[i]:
            count += 1.0
        else:
            count = 0.0
        result[i] = count
    return result
@njit(cache=True)
def _fit_ols_numba(x, y):
    n = len(x)
    if n < 2:
        return 0.0, 0.0, 0.0
    
    x_mean = 0.0
    y_mean = 0.0
    for i in range(n):
        x_mean += x[i]
        y_mean += y[i]
    x_mean /= n
    y_mean /= n
    
    num = 0.0
    den = 0.0
    for i in range(n):
        dx = x[i] - x_mean
        dy = y[i] - y_mean
        num += dx * dy
        den += dx * dx
        
    if den == 0.0:
        return 0.0, y_mean, 1.0
        
    slope = num / den
    intercept = y_mean - slope * x_mean
    
    ss_tot = 0.0
    ss_res = 0.0
    for i in range(n):
        y_pred = slope * x[i] + intercept
        ss_tot += (y[i] - y_mean) ** 2
        ss_res += (y[i] - y_pred) ** 2
        
    if ss_tot == 0.0:
        r2 = 1.0
    else:
        r2 = 1.0 - (ss_res / ss_tot)
        
    return slope, intercept, r2


@njit(cache=True)
def _detect_triangles_numba(
    high,
    low,
    close,
    pivot_window,
    lookback,
    slope_tolerance,
    min_r_squared,
    min_pivots,
    pattern_type_code,
):
    n = len(close)
    out = np.zeros(n, dtype=np.float64)
    
    is_sh = np.zeros(n, dtype=np.bool_)
    is_sl = np.zeros(n, dtype=np.bool_)
    
    for i in range(pivot_window, n - pivot_window):
        val_h = high[i]
        is_high = True
        for j in range(i - pivot_window, i):
            if high[j] >= val_h:
                is_high = False
                break
        if is_high:
            for j in range(i + 1, i + pivot_window + 1):
                if high[j] > val_h:
                    is_high = False
                    break
        is_sh[i] = is_high
        
        val_l = low[i]
        is_low = True
        for j in range(i - pivot_window, i):
            if low[j] <= val_l:
                is_low = False
                break
        if is_low:
            for j in range(i + 1, i + pivot_window + 1):
                if low[j] < val_l:
                    is_low = False
                    break
        is_sl[i] = is_low

    for t in range(0, n):
        close_t = close[t]
        if close_t <= 0.0 or np.isnan(close_t):
            continue
            
        # EL `max(0, ...)` ES LO QUE IMPIDE QUE EL PROCESO SE ESFUME.
        #
        # Sin el, en las primeras velas del dia `start_idx` sale NEGATIVO
        # (t=0, lookback=50 -> -50). La guarda de abajo compara `end_idx <
        # start_idx`, o sea -5 < -50, que es falsa: la deja pasar. Y entonces el
        # bucle indexa `is_sh[-50]` en un array que puede tener menos de 50
        # elementos, porque `n` son las velas de ESE dia y un premercado corto
        # tiene menos.
        #
        # En Python eso es un `IndexError` limpio. COMPILADO CON NUMBA NO: sin
        # `boundscheck` (el defecto) lee memoria que no es suya, Windows lo corta
        # con una violacion de acceso 0xC0000005 y el proceso DESAPARECE — sin
        # traceback, sin excepcion y sin que ningun `except` se entere.
        #
        # Es lo que tumbaba las corridas del genetico cada ~24 minutos durante
        # dos noches. Se cazo el 5-sep-2026 apuntando la receta del individuo
        # antes de evaluarlo: `Triangle Symmetric(pivot_window=5,
        # tri_lookback=50, ...)`. Reproducido con 30 velas y lookback 50:
        #
        #     velas=30,  lookback=50 -> IndexError: index -50 out of bounds
        #     velas=100, lookback=50 -> ok
        #
        # Hace falta que coincidan un individuo con triangulos Y un dia mas
        # corto que su lookback; de ahi que tardara en aparecer.
        start_idx = max(0, t - lookback)
        end_idx = t - pivot_window

        if end_idx < start_idx:
            continue

        sh_indices = np.empty(lookback, dtype=np.float64)
        sh_prices = np.empty(lookback, dtype=np.float64)
        sh_count = 0
        for i in range(start_idx, end_idx + 1):
            if is_sh[i]:
                sh_indices[sh_count] = float(i)
                sh_prices[sh_count] = high[i] / close_t
                sh_count += 1
                
        sl_indices = np.empty(lookback, dtype=np.float64)
        sl_prices = np.empty(lookback, dtype=np.float64)
        sl_count = 0
        for i in range(start_idx, end_idx + 1):
            if is_sl[i]:
                sl_indices[sl_count] = float(i)
                sl_prices[sl_count] = low[i] / close_t
                sl_count += 1
                
        if sh_count < min_pivots or sl_count < min_pivots:
            continue
            
        # Ensure the pattern has just been confirmed on the current bar t
        last_high_confirm = sh_indices[sh_count - 1] + pivot_window
        last_low_confirm = sl_indices[sl_count - 1] + pivot_window
        if last_high_confirm != t and last_low_confirm != t:
            continue
            
        slope_R, intercept_R, r2_R = _fit_ols_numba(sh_indices[:sh_count], sh_prices[:sh_count])
        slope_S, intercept_S, r2_S = _fit_ols_numba(sl_indices[:sl_count], sl_prices[:sl_count])
        
        if r2_R < min_r_squared or r2_S < min_r_squared:
            continue
            
        y_R_t = slope_R * t + intercept_R
        y_S_t = slope_S * t + intercept_S
        if y_R_t <= y_S_t:
            continue
            
        # Convert slopes to percentage total change over the lookback window
        slope_R_pct = slope_R * lookback * 100.0
        slope_S_pct = slope_S * lookback * 100.0
        
        is_pattern = False
        if pattern_type_code == 1:
            # Ascending: flat resistance, rising support
            if abs(slope_R_pct) <= slope_tolerance and slope_S_pct > slope_tolerance:
                is_pattern = True
        elif pattern_type_code == 2:
            # Descending: falling resistance, flat support
            if slope_R_pct < -slope_tolerance and abs(slope_S_pct) <= slope_tolerance:
                is_pattern = True
        elif pattern_type_code == 3:
            # Symmetric: falling resistance, rising support
            if slope_R_pct < -slope_tolerance and slope_S_pct > slope_tolerance:
                is_pattern = True
                
        if is_pattern:
            out[t] = 1.0
            
    return out


def _consecutive_count(signal: np.ndarray) -> np.ndarray:
    return _consecutive_count_core(np.ascontiguousarray(signal))


# --- Darvas Box -----------------------------------------------------------
# Maquina de 3 estados, literal del documento del usuario ("Indicador Darvas"):
#   1. BUSCANDO_TECHO  -> un maximo que aguanta N velas sin ser igualado
#   2. BUSCANDO_SUELO  -> un minimo que aguanta N velas sin ser perforado
#   3. CAJA_CONSOLIDADA-> dos lineas HORIZONTALES y ESTATICAS hasta que un
#                         CIERRE salga de ellas
#
# Las dos reglas que no se pueden confundir, y que son la esencia del indicador:
#   * las MECHAS (high/low) construyen y validan la caja (pasos 1 y 2);
#   * solo los CIERRES la destruyen (paso 3). Una mecha fuera no rompe nada.
#
# Comparaciones, tomadas al pie de la letra del documento porque cambian el
# resultado: el techo se reinicia con un maximo "igual o mayor" (>=), pero se
# confirma con maximos "estrictamente menores" (<). El suelo se confirma con
# minimos "estrictamente mayores" (>), baja con uno menor (<), y con uno IGUAL
# ni confirma ni baja: rompe la racha y el contador vuelve a cero.
BUSCANDO_TECHO = 0
BUSCANDO_SUELO = 1
CAJA_CONSOLIDADA = 2


@njit(cache=True)
def _darvas_box_core(high, low, close, n_confirm):
    """Devuelve (techo, suelo) por vela. NaN mientras no haya caja viva.

    Causal por construccion: cada barra se decide solo con datos hasta esa
    barra, nunca mirando adelante.

    En la vela que ROMPE la caja se sigue emitiendo el nivel que tenia. Es
    deliberado: si se pusiera NaN ahi, un cruce contra el techo nunca podria
    detectarse en la vela que precisamente lo cruza. A partir de la siguiente
    ya sale NaN, hasta que nazca la caja nueva.
    """
    n = len(close)
    techo = np.full(n, np.nan)
    suelo = np.full(n, np.nan)
    if n == 0:
        return techo, suelo

    estado = BUSCANDO_TECHO
    cand_techo = high[0]
    # Indice donde nacio el candidato a techo: el suelo inicial es el minimo de
    # TODO el periodo de formacion del techo (desde esa vela hasta la que lo
    # confirma), tal y como pide el paso 2.
    idx_origen = 0
    cuenta = 0
    techo_ok = np.nan
    suelo_ok = np.nan
    cand_suelo = np.nan

    for i in range(1, n):
        if estado == BUSCANDO_TECHO:
            if high[i] >= cand_techo:
                cand_techo = high[i]        # reinicio: nuevo candidato
                idx_origen = i
                cuenta = 0
            else:
                cuenta += 1
                if cuenta >= n_confirm:
                    techo_ok = cand_techo
                    # Minimo de todo el periodo de formacion, extremos incluidos
                    m = low[idx_origen]
                    for j in range(idx_origen + 1, i + 1):
                        if low[j] < m:
                            m = low[j]
                    cand_suelo = m
                    cuenta = 0
                    estado = BUSCANDO_SUELO

        elif estado == BUSCANDO_SUELO:
            # Escenario C: el precio se dispara y supera el techo ya validado.
            # Se cancela todo y se vuelve al paso 1 con este maximo.
            if high[i] > techo_ok:
                cand_techo = high[i]
                idx_origen = i
                cuenta = 0
                techo_ok = np.nan
                cand_suelo = np.nan
                estado = BUSCANDO_TECHO
            elif low[i] < cand_suelo:
                cand_suelo = low[i]         # el suelo se desplaza hacia abajo
                cuenta = 0
            elif low[i] > cand_suelo:
                cuenta += 1
                if cuenta >= n_confirm:
                    suelo_ok = cand_suelo
                    estado = CAJA_CONSOLIDADA
            else:
                cuenta = 0                  # minimo IGUAL: rompe la racha

        else:  # CAJA_CONSOLIDADA
            # Solo el cierre puede matarla. Las mechas fuera no cuentan.
            if close[i] > techo_ok or close[i] < suelo_ok:
                techo[i] = techo_ok         # el nivel vive en la vela que rompe
                suelo[i] = suelo_ok
                cand_techo = high[i]        # el maximo de la vela de ruptura
                idx_origen = i
                cuenta = 0
                techo_ok = np.nan
                suelo_ok = np.nan
                cand_suelo = np.nan
                estado = BUSCANDO_TECHO
                continue

        if estado == CAJA_CONSOLIDADA:
            techo[i] = techo_ok
            suelo[i] = suelo_ok

    return techo, suelo


def _darvas_box(high: np.ndarray, low: np.ndarray, close: np.ndarray,
                n_confirm: int) -> tuple[np.ndarray, np.ndarray]:
    n_confirm = max(1, int(n_confirm))
    return _darvas_box_core(
        np.ascontiguousarray(high, dtype=np.float64),
        np.ascontiguousarray(low, dtype=np.float64),
        np.ascontiguousarray(close, dtype=np.float64),
        n_confirm,
    )


def _hammer(open_: np.ndarray, high: np.ndarray, low: np.ndarray, close: np.ndarray) -> np.ndarray:
    body = np.abs(close - open_)
    full_range = high - low + 1e-10
    lower_wick = np.minimum(open_, close) - low
    return (lower_wick >= 2 * body) & (body / full_range < 0.4)


def _shooting_star(open_: np.ndarray, high: np.ndarray, low: np.ndarray, close: np.ndarray) -> np.ndarray:
    body = np.abs(close - open_)
    full_range = high - low + 1e-10
    upper_wick = high - np.maximum(open_, close)
    return (upper_wick >= 2 * body) & (body / full_range < 0.4)


@njit(cache=True)
def _stochastic_k(high, low, close, k_period):
    n = len(close)
    k = np.empty(n, dtype=np.float64)
    for i in range(n):
        k[i] = np.nan
    for i in range(k_period - 1, n):
        hh = high[i]
        ll = low[i]
        for j in range(i - k_period + 1, i):
            if high[j] > hh:
                hh = high[j]
            if low[j] < ll:
                ll = low[j]
        if hh != ll:
            k[i] = (close[i] - ll) / (hh - ll) * 100.0
        else:
            k[i] = 50.0
    return k


def _stochastic(high: np.ndarray, low: np.ndarray, close: np.ndarray,
                k_period: int = 14, d_period: int = 3) -> tuple:
    """Returns (%K, %D)."""
    k = _stochastic_k(
        np.ascontiguousarray(high, dtype=np.float64),
        np.ascontiguousarray(low, dtype=np.float64),
        np.ascontiguousarray(close, dtype=np.float64),
        k_period,
    )
    d = _sma(k, d_period)
    return k, d


@njit(cache=True)
def _rolling_std_core(values, period):
    n = len(values)
    out = np.empty(n, dtype=np.float64)
    for k in range(n):
        out[k] = np.nan
    for i in range(period - 1, n):
        s = 0.0
        for j in range(i - period + 1, i + 1):
            s += values[j]
        mean = s / period
        ss = 0.0
        for j in range(i - period + 1, i + 1):
            d = values[j] - mean
            ss += d * d
        out[i] = (ss / period) ** 0.5
    return out


def _bollinger_bands(close: np.ndarray, period: int = 20, std_dev: float = 2.0) -> tuple:
    """Returns (upper, middle, lower)."""
    c = np.ascontiguousarray(close, dtype=np.float64)
    middle = _sma(c, period)
    rolling_std = _rolling_std_core(c, period)
    upper = middle + std_dev * rolling_std
    lower = middle - std_dev * rolling_std
    return upper, middle, lower


@njit(cache=True)
def _cci_core(high, low, close, period):
    n = len(close)
    typical = np.empty(n, dtype=np.float64)
    for i in range(n):
        typical[i] = (high[i] + low[i] + close[i]) / 3.0
    # SMA of typical
    sma_tp = np.empty(n, dtype=np.float64)
    for k in range(n):
        sma_tp[k] = np.nan
    for i in range(period - 1, n):
        s = 0.0
        for j in range(i - period + 1, i + 1):
            s += typical[j]
        sma_tp[i] = s / period
    # MAD and CCI
    out = np.empty(n, dtype=np.float64)
    for k in range(n):
        out[k] = np.nan
    for i in range(period - 1, n):
        sm = sma_tp[i]
        if sm != sm:  # NaN
            continue
        mad_sum = 0.0
        for j in range(i - period + 1, i + 1):
            d = typical[j] - sm
            if d < 0.0:
                d = -d
            mad_sum += d
        mad = mad_sum / period
        if mad != 0.0:
            out[i] = (typical[i] - sm) / (0.015 * mad)
        else:
            out[i] = 0.0
    return out


def _cci(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 20) -> np.ndarray:
    return _cci_core(
        np.ascontiguousarray(high, dtype=np.float64),
        np.ascontiguousarray(low, dtype=np.float64),
        np.ascontiguousarray(close, dtype=np.float64),
        period,
    )


def _roc(close: np.ndarray, period: int = 12) -> np.ndarray:
    out = np.full(len(close), np.nan)
    out[period:] = (close[period:] - close[:-period]) / close[:-period] * 100
    return out


def _momentum(close: np.ndarray, period: int = 10) -> np.ndarray:
    out = np.full(len(close), np.nan)
    out[period:] = close[period:] - close[:-period]
    return out


@njit(cache=True)
def _obv_core(close, volume):
    n = len(close)
    out = np.zeros(n, dtype=np.float64)
    for i in range(1, n):
        if close[i] > close[i - 1]:
            out[i] = out[i - 1] + volume[i]
        elif close[i] < close[i - 1]:
            out[i] = out[i - 1] - volume[i]
        else:
            out[i] = out[i - 1]
    return out


def _obv(close: np.ndarray, volume: np.ndarray) -> np.ndarray:
    return _obv_core(
        np.ascontiguousarray(close, dtype=np.float64),
        np.ascontiguousarray(volume, dtype=np.float64),
    )


@njit(cache=True)
def _dmi_loops(high, low, close):
    n = len(close)
    plus_dm = np.zeros(n, dtype=np.float64)
    minus_dm = np.zeros(n, dtype=np.float64)
    tr = np.zeros(n, dtype=np.float64)
    for i in range(1, n):
        up_move = high[i] - high[i - 1]
        down_move = low[i - 1] - low[i]
        if up_move > down_move and up_move > 0.0:
            plus_dm[i] = up_move
        if down_move > up_move and down_move > 0.0:
            minus_dm[i] = down_move
        hl = high[i] - low[i]
        hc = abs(high[i] - close[i - 1])
        lc = abs(low[i] - close[i - 1])
        tr[i] = hl
        if hc > tr[i]:
            tr[i] = hc
        if lc > tr[i]:
            tr[i] = lc
    return plus_dm, minus_dm, tr


def _dmi(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 14) -> tuple:
    """Returns (+DI, -DI)."""
    h = np.ascontiguousarray(high, dtype=np.float64)
    l = np.ascontiguousarray(low, dtype=np.float64)
    c = np.ascontiguousarray(close, dtype=np.float64)
    plus_dm, minus_dm, tr = _dmi_loops(h, l, c)

    atr = _ema_core(tr, period)
    plus_di = _ema_core(plus_dm, period) / np.where(atr != 0, atr, np.nan) * 100
    minus_di = _ema_core(minus_dm, period) / np.where(atr != 0, atr, np.nan) * 100
    return plus_di, minus_di


@njit(cache=True)
def _heikin_ashi_core(open_, high, low, close):
    n = len(close)
    ha_close = np.empty(n, dtype=np.float64)
    ha_open = np.empty(n, dtype=np.float64)
    ha_high = np.empty(n, dtype=np.float64)
    ha_low = np.empty(n, dtype=np.float64)
    for i in range(n):
        ha_close[i] = (open_[i] + high[i] + low[i] + close[i]) / 4.0
    ha_open[0] = (open_[0] + close[0]) / 2.0
    for i in range(1, n):
        ha_open[i] = (ha_open[i - 1] + ha_close[i - 1]) / 2.0
    for i in range(n):
        hh = high[i]
        if ha_open[i] > hh:
            hh = ha_open[i]
        if ha_close[i] > hh:
            hh = ha_close[i]
        ha_high[i] = hh
        ll = low[i]
        if ha_open[i] < ll:
            ll = ha_open[i]
        if ha_close[i] < ll:
            ll = ha_close[i]
        ha_low[i] = ll
    return ha_open, ha_high, ha_low, ha_close


def _heikin_ashi(open_: np.ndarray, high: np.ndarray, low: np.ndarray, close: np.ndarray) -> tuple:
    """Returns (ha_open, ha_high, ha_low, ha_close)."""
    return _heikin_ashi_core(
        np.ascontiguousarray(open_, dtype=np.float64),
        np.ascontiguousarray(high, dtype=np.float64),
        np.ascontiguousarray(low, dtype=np.float64),
        np.ascontiguousarray(close, dtype=np.float64),
    )


@njit(cache=True)
def _linear_regression_core(close, period):
    n = len(close)
    out = np.empty(n, dtype=np.float64)
    for k in range(n):
        out[k] = np.nan
    # Pre-compute x stats
    x_mean = (period - 1.0) / 2.0
    x_var = 0.0
    for k in range(period):
        d = k - x_mean
        x_var += d * d
    if x_var == 0.0:
        return out
    for i in range(period - 1, n):
        y_sum = 0.0
        for j in range(i - period + 1, i + 1):
            y_sum += close[j]
        y_mean = y_sum / period
        cov = 0.0
        for k in range(period):
            cov += (k - x_mean) * (close[i - period + 1 + k] - y_mean)
        slope = cov / x_var
        out[i] = y_mean + slope * (period - 1.0 - x_mean)
    return out


def _linear_regression(close: np.ndarray, period: int = 14) -> np.ndarray:
    return _linear_regression_core(np.ascontiguousarray(close, dtype=np.float64), period)


def _pivot_points(daily_stats: dict) -> dict:
    """Calculate pivot points from daily stats. Returns dict with PP, R1, S1, R2, S2, R3, S3."""
    h = daily_stats.get("yesterday_high", daily_stats.get("rth_high", np.nan))
    l = daily_stats.get("yesterday_low", daily_stats.get("rth_low", np.nan))
    c = daily_stats.get("previous_close", np.nan)
    if np.isnan(h) or np.isnan(l) or np.isnan(c):
        return {}
    pp = (h + l + c) / 3.0
    return {
        "PP": pp,
        "R1": 2 * pp - l,
        "S1": 2 * pp - h,
        "R2": pp + (h - l),
        "S2": pp - (h - l),
        "R3": h + 2 * (pp - l),
        "S3": l - 2 * (h - pp),
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

# Normalize frontend indicator names to backend names
INDICATOR_NAME_MAP = {
    # Price Variables — nuevos nombres del frontend
    "Bar Close": "Close",
    "Bar Open": "Open",
    "High Bar": "High",
    "Low Bar": "Low",
    "PM Open": "PM Open",
    "PM High": "Pre-Market High",
    "PM Low": "Pre-Market Low",
    "RTH Open": "RTH Open",
    "RTH High": "RTH High",
    "RTH Low": "RTH Low",
    "AM Open": "AM Open",
    "Previous max": "Previous max",
    "Previous min": "Previous min",
    "Yesterday Open": "Yesterday Open",
    "Yesterday Close": "Yesterday Close",
    "Yesterday High": "Yesterday High",
    "Yesterday Low": "Yesterday Low",
    "Yesterday AM High": "Yesterday AM High",
    "Yesterday AM Low": "Yesterday AM Low",
    "High of last X days": "Max of last X days",
    "Low of last X days": "Min of last X days",
    "Overhead last X days": "Overhead last X days",
    "Overhead": "Overhead last X days",
    "Prev. Bar Close": "Prev. Close Bar",
    "Prev. Bar Open": "Prev. Open Bar",
    "Prev. Bar High": "Prev. High Bar",
    "Prev. Bar Low": "Prev. Low Bar",

    # Behaviour & Patterns
    "Consecutive higher highs": "Consecutive Higher Highs",
    "Consecutive lower lows": "Consecutive Lower Lows",
    "Consecutive lower highs": "Consecutive Lower Highs",
    "Consecutive higher lows": "Consecutive Higher Lows",
    "Consecutive green candles": "Consecutive Green Candles",
    "Consecutive red candles": "Consecutive Red Candles",
    
    # Abbreviated label aliases
    "Consec Higher Highs": "Consecutive Higher Highs",
    "Consec Lower Lows": "Consecutive Lower Lows",
    "Consec Lower Highs": "Consecutive Lower Highs",
    "Consec Higher Lows": "Consecutive Higher Lows",
    "Consec Green Candles": "Consecutive Green Candles",
    "Consec Red Candles": "Consecutive Red Candles",
    "Candle Range %": "Candle Range %",
    "Recorrido (%)": "Recorrido (%)",
    # Alias. Sin esto, un JSON que traiga cualquiera de estas formas
    # normalizaria a nada y el indicador saldria NaN sin avisar.
    "Recorrido": "Recorrido (%)",
    "Recorrido %": "Recorrido (%)",
    "Candle Move %": "Recorrido (%)",
    "Range of time": "Range of time",
    "Opening range +": "Opening Range +",
    "Opening range -": "Opening Range -",
    "Opening range AM +": "Opening Range AM +",
    "Opening range AM -": "Opening Range AM -",
    "Elapsed time from last High": "Elapsed Time from Last High",
    "Triangle Ascending": "Triangle Ascending",
    "Triangle Descending": "Triangle Descending",
    "Triangle Symmetric": "Triangle Symmetric",

    # Indicators
    # Darvas: el nombre canonico es "Darvas Box"; los alias son como puede
    # llegar desde la interfaz o desde estrategias escritas a mano.
    "Darvas Box": "Darvas Box",
    "Darvas": "Darvas Box",
    "Caja Darvas": "Darvas Box",
    "Squeeze": "Squeeze",
    "Vol. de la franja": "Vol. de la franja",
    "Punto de control": "Punto de control",
    "Nodo de arriba": "Nodo de arriba",
    "Nodo de abajo": "Nodo de abajo",
    "Zona alta": "Zona alta",
    "Zona baja": "Zona baja",
    "Ultimo pivote": "Ultimo pivote",
    "\u00daltimo pivote": "Ultimo pivote",
    "Retroceso (%)": "Retroceso (%)",
    "Absorption": "Absorption",
    "Wick Ratio": "Wick Ratio",
    "Absorption + Wick": "Absorption + Wick",
    "Reg. Slope": "Reg. Slope",
    "Reg. R2": "Reg. R2",
    "Reg. R²": "Reg. R2",
    "ATR Extension": "ATR Extension",
    "Time vs Level": "Time vs Level",
    "Donchian": "Donchian Channels",
    "Bollinger Bands": "Bollinger Bands",
    "Accumulated Volume": "Accumulated Volume",
    "Accumulated Dollar Volume": "Accumulated Dollar Volume",
    "Dollar Volume": "Dollar Volume",
    "Yesterday Volume": "Yesterday Volume",
    "RVOL": "RVOL",

    # Legacy aliases (compatibilidad con estrategias antiguas)
    "Max of last X days": "Max of last X days",
    "Min of last X days": "Min of last X days",
    "Bollinger Upper": "Bollinger Upper",
    "Bollinger Lower": "Bollinger Lower",
    "Bollinger Middle": "Bollinger Middle",
}

def normalize_indicator_name(name: str) -> str:
    return INDICATOR_NAME_MAP.get(name, name)

def compute_indicator(
    name: str,
    df: pd.DataFrame,
    period: int | None = None,
    period2: int | None = None,
    period3: int | None = None,
    std_dev: float | None = None,
    multiplier: float | None = None,
    offset: int = 0,
    days_lookback: int | None = None,
    calc_on_heikin: bool = False,
    time_hour: int | None = None,
    time_minute: int | None = None,
    time_condition: str | None = None,
    band_line: str | None = None,
    orb_minutes: int | None = None,
    ap_session: str | None = None,
    daily_stats: dict | None = None,
    cache: dict | None = None,
    range_minutes: int | None = None,
    pivot_window: int | None = None,
    tri_lookback: int | None = None,
    slope_tolerance: float | None = None,
    min_r_squared: float | None = None,
    min_pivots: int | None = None,
    session_ref: str | None = None,
    squeeze_direction: str | None = None,
    fade_ref: str | None = None,
    # "Overhead last X days". Los tres van en la CLAVE DE CACHE de abajo:
    # si no entraran, dos configuraciones distintas compartirian resultado.
    overhead_extreme: str | None = None,
    overhead_ref: str | None = None,
    overhead_vol_rule: str | None = None,
    # "ATR Extension" y "Time vs Level": contra QUE nivel se mide, y hacia que
    # lado cuenta el reloj. Los dos van en la CLAVE DE CACHE de abajo.
    ref_level: str | None = None,
    level_dir: str | None = None,
    # "Wick Ratio" y "Absorption + Wick". Los cinco van en la CLAVE DE CACHE.
    wick_side: str | None = None,
    abs_op: str | None = None,
    abs_level: float | None = None,
    wick_op: str | None = None,
    wick_level: float | None = None,
    # "Retroceso (%)": si el impulso que se mide es al alza o a la baja.
    swing_dir: str | None = None,
    # Perfil de volumen: anchura de franja (% del primer precio del dia) y
    # liston para que una franja cuente como nodo (% del volumen del POC).
    bin_pct: float | None = None,
    liston_pct: float | None = None,
    # "Zona alta"/"Zona baja": que % del volumen del dia abarca la banda.
    zona_pct: float | None = None,
) -> pd.Series:
    # N1d: name already normalized by compile_strategy_def; normalize here for legacy callers
    name = normalize_indicator_name(name)
    # N1b: simplified cache key — string instead of 17-tuple
    cache_key = f"{name}|{period}|{period2}|{period3}|{std_dev}|{multiplier}|{offset}|{days_lookback}|{calc_on_heikin}|{time_hour}|{time_minute}|{time_condition}|{band_line}|{orb_minutes}|{ap_session}|{range_minutes}|{pivot_window}|{tri_lookback}|{slope_tolerance}|{min_r_squared}|{min_pivots}|{session_ref}|{squeeze_direction}|{fade_ref}|{overhead_extreme}|{overhead_ref}|{overhead_vol_rule}|{ref_level}|{level_dir}|{wick_side}|{abs_op}|{abs_level}|{wick_op}|{wick_level}|{swing_dir}|{bin_pct}|{liston_pct}|{zona_pct}"
    if cache is not None and cache_key in cache:
        return cache[cache_key]

    close = df["close"]
    high = df["high"]
    low = df["low"]
    open_ = df["open"]
    volume = df["volume"]

    # If calc_on_heikin, transform OHLC to Heikin-Ashi
    if calc_on_heikin:
        ha_o, ha_h, ha_l, ha_c = _heikin_ashi(
            open_.values.astype(np.float64),
            high.values.astype(np.float64),
            low.values.astype(np.float64),
            close.values.astype(np.float64),
        )
        close = pd.Series(ha_c, index=df.index)
        high = pd.Series(ha_h, index=df.index)
        low = pd.Series(ha_l, index=df.index)
        open_ = pd.Series(ha_o, index=df.index)

    result = _compute_raw(
        name, close, high, low, open_, volume,
        period, period2, period3, std_dev, multiplier,
        days_lookback, time_hour, time_minute, time_condition,
        band_line, orb_minutes, ap_session, daily_stats, df, range_minutes,
        pivot_window, tri_lookback, slope_tolerance, min_r_squared, min_pivots,
        session_ref, squeeze_direction, fade_ref,
        overhead_extreme=overhead_extreme, overhead_ref=overhead_ref,
        overhead_vol_rule=overhead_vol_rule,
        ref_level=ref_level, level_dir=level_dir,
        wick_side=wick_side, abs_op=abs_op, abs_level=abs_level,
        wick_op=wick_op, wick_level=wick_level, swing_dir=swing_dir,
        bin_pct=bin_pct, liston_pct=liston_pct, zona_pct=zona_pct,
    )

    if offset and offset != 0:
        result = result.shift(offset)

    if name != "Parabolic SAR" and multiplier is not None:
        result = result * multiplier

    if cache is not None:
        cache[cache_key] = result

    return result


# N1a: Fast-path dict dispatch — O(1) lookup vs O(50) if/elif chain
def _mk_fast(name, fn):
    """Wrap an indicator function to match _compute_raw's signature."""
    def _wrapper(close, high, low, open_, volume, period, period2, period3,
                 std_dev, multiplier, days_lookback, time_hour, time_minute,
                 time_condition, band_line, orb_minutes, ap_session, ds, df,
                 range_minutes, pivot_window, tri_lookback, slope_tolerance,
                 min_r_squared, min_pivots):
        return fn(close, high, low, open_, volume, period, period2, period3,
                  std_dev, multiplier, days_lookback, time_hour, time_minute,
                  time_condition, band_line, orb_minutes, ap_session, ds, df,
                  range_minutes, pivot_window, tri_lookback, slope_tolerance,
                  min_r_squared, min_pivots)
    return _wrapper


def _raw_close(close, high, low, open_, volume, period, period2, period3,
               std_dev, multiplier, days_lookback, time_hour, time_minute,
               time_condition, band_line, orb_minutes, ap_session, ds, df,
               range_minutes, pivot_window, tri_lookback, slope_tolerance,
               min_r_squared, min_pivots):
    return close

def _raw_open(close, high, low, open_, volume, period, period2, period3,
              std_dev, multiplier, days_lookback, time_hour, time_minute,
              time_condition, band_line, orb_minutes, ap_session, ds, df,
              range_minutes, pivot_window, tri_lookback, slope_tolerance,
              min_r_squared, min_pivots):
    return open_

def _raw_high(close, high, low, open_, volume, period, period2, period3,
              std_dev, multiplier, days_lookback, time_hour, time_minute,
              time_condition, band_line, orb_minutes, ap_session, ds, df,
              range_minutes, pivot_window, tri_lookback, slope_tolerance,
              min_r_squared, min_pivots):
    return high

def _raw_low(close, high, low, open_, volume, period, period2, period3,
             std_dev, multiplier, days_lookback, time_hour, time_minute,
             time_condition, band_line, orb_minutes, ap_session, ds, df,
             range_minutes, pivot_window, tri_lookback, slope_tolerance,
             min_r_squared, min_pivots):
    return low

def _raw_volume(close, high, low, open_, volume, period, period2, period3,
                std_dev, multiplier, days_lookback, time_hour, time_minute,
                time_condition, band_line, orb_minutes, ap_session, ds, df,
                range_minutes, pivot_window, tri_lookback, slope_tolerance,
                min_r_squared, min_pivots):
    return volume.astype(float)

def _raw_sma(close, high, low, open_, volume, period, period2, period3,
             std_dev, multiplier, days_lookback, time_hour, time_minute,
             time_condition, band_line, orb_minutes, ap_session, ds, df,
             range_minutes, pivot_window, tri_lookback, slope_tolerance,
             min_r_squared, min_pivots):
    return pd.Series(_sma(close.values, period or 20), index=close.index)

def _raw_ema(close, high, low, open_, volume, period, period2, period3,
             std_dev, multiplier, days_lookback, time_hour, time_minute,
             time_condition, band_line, orb_minutes, ap_session, ds, df,
             range_minutes, pivot_window, tri_lookback, slope_tolerance,
             min_r_squared, min_pivots):
    return pd.Series(_ema(close.values, period or 20), index=close.index)

def _raw_vwap(close, high, low, open_, volume, period, period2, period3,
              std_dev, multiplier, days_lookback, time_hour, time_minute,
              time_condition, band_line, orb_minutes, ap_session, ds, df,
              range_minutes, pivot_window, tri_lookback, slope_tolerance,
              min_r_squared, min_pivots):
    vals = _vwap(high.values.astype(np.float64), low.values.astype(np.float64),
                 close.values.astype(np.float64), volume.values.astype(np.float64))
    return pd.Series(vals, index=close.index)

def _raw_rsi(close, high, low, open_, volume, period, period2, period3,
             std_dev, multiplier, days_lookback, time_hour, time_minute,
             time_condition, band_line, orb_minutes, ap_session, ds, df,
             range_minutes, pivot_window, tri_lookback, slope_tolerance,
             min_r_squared, min_pivots):
    return pd.Series(_rsi(close.values, period or 14), index=close.index)

def _raw_atr(close, high, low, open_, volume, period, period2, period3,
             std_dev, multiplier, days_lookback, time_hour, time_minute,
             time_condition, band_line, orb_minutes, ap_session, ds, df,
             range_minutes, pivot_window, tri_lookback, slope_tolerance,
             min_r_squared, min_pivots):
    return pd.Series(_atr(high.values.astype(np.float64), low.values.astype(np.float64),
                          close.values.astype(np.float64), period or 14), index=close.index)

def _raw_macd(close, high, low, open_, volume, period, period2, period3,
              std_dev, multiplier, days_lookback, time_hour, time_minute,
              time_condition, band_line, orb_minutes, ap_session, ds, df,
              range_minutes, pivot_window, tri_lookback, slope_tolerance,
              min_r_squared, min_pivots):
    fast = period or 12; slow = period2 or 26; signal = period3 or 9
    macd_line, _, _ = _macd(close.values.astype(np.float64), fast, slow, signal)
    return pd.Series(macd_line, index=close.index)

def _raw_hod(close, high, low, open_, volume, period, period2, period3,
             std_dev, multiplier, days_lookback, time_hour, time_minute,
             time_condition, band_line, orb_minutes, ap_session, ds, df,
             range_minutes, pivot_window, tri_lookback, slope_tolerance,
             min_r_squared, min_pivots):
    return high.cummax()

def _raw_lod(close, high, low, open_, volume, period, period2, period3,
             std_dev, multiplier, days_lookback, time_hour, time_minute,
             time_condition, band_line, orb_minutes, ap_session, ds, df,
             range_minutes, pivot_window, tri_lookback, slope_tolerance,
             min_r_squared, min_pivots):
    return low.cummin()

def _raw_prev_close_bar(close, high, low, open_, volume, period, period2, period3,
                        std_dev, multiplier, days_lookback, time_hour, time_minute,
                        time_condition, band_line, orb_minutes, ap_session, ds, df,
                        range_minutes, pivot_window, tri_lookback, slope_tolerance,
                        min_r_squared, min_pivots):
    return close.shift(1)


_FAST_INDICATOR_DISPATCH = {
    "Close": _raw_close, "Open": _raw_open, "High": _raw_high, "Low": _raw_low,
    "Volume": _raw_volume, "Bar Close": _raw_close, "Bar Open": _raw_open,
    "SMA": _raw_sma, "EMA": _raw_ema, "VWAP": _raw_vwap, "AVWAP": _raw_vwap,
    "RSI": _raw_rsi, "ATR": _raw_atr, "MACD": _raw_macd,
    "High of Day": _raw_hod, "Low of Day": _raw_lod,
    "Prev. Close Bar": _raw_prev_close_bar, "Prev. Bar Close": _raw_prev_close_bar,
}


def _pm_running_series(df: pd.DataFrame, index, which: str) -> pd.Series | None:
    """PM High/Low acumulado hasta la barra actual (causal, sin lookahead).

    NaN antes de la primera barra de premarket (el nivel aún no existe: cualquier
    comparación evalúa False). Tras el cierre del premarket (09:30) la serie se
    mantiene en el valor final, idéntico al comportamiento previo en RTH.
    Devuelve None si el df no tiene barras de premarket (p.ej. dato solo-RTH):
    el caller decide el fallback (constante de daily_stats, que ahí sí es causal).
    """
    if df is None or "timestamp" not in df or len(df) == 0:
        return None
    timestamps = pd.to_datetime(df["timestamp"])
    minutes = timestamps.dt.hour.values * 60 + timestamps.dt.minute.values
    pm_mask = (minutes >= 240) & (minutes < 570)
    if not pm_mask.any():
        return None
    vals = np.asarray(df[which], dtype=np.float64)
    masked = np.where(pm_mask, vals, np.nan)
    acc = np.fmax.accumulate(masked) if which == "high" else np.fmin.accumulate(masked)
    return pd.Series(acc, index=index)


def _rth_running_series(df: pd.DataFrame, index, which: str) -> pd.Series | None:
    """RTH Open/High/Low causal (mismo defecto que tenía PM High: la constante
    del día completo hacía 'ver' a las 10:00 el máximo de las 15:30).

    - "high"/"low": cummax/cummin de la sesión regular (09:30-16:00) hasta la
      barra actual; NaN antes de la primera barra RTH; tras las 16:00 se
      mantiene el valor final (after-hours ve el RTH completo, ya causal).
    - "open": NaN antes de la primera barra RTH; desde ella, su open constante.
    Devuelve None si el df no tiene barras RTH: el caller distingue si la sesión
    regular ya pasó (constante de daily_stats, causal) o aún no llegó (NaN).
    """
    if df is None or "timestamp" not in df or len(df) == 0:
        return None
    timestamps = pd.to_datetime(df["timestamp"])
    minutes = timestamps.dt.hour.values * 60 + timestamps.dt.minute.values
    rth_mask = (minutes >= 570) & (minutes < 960)
    if not rth_mask.any():
        return None
    if which == "open":
        first_idx = int(np.argmax(rth_mask))
        vals = np.full(len(df), np.nan)
        vals[first_idx:] = float(np.asarray(df["open"], dtype=np.float64)[first_idx])
        return pd.Series(vals, index=index)
    vals = np.asarray(df[which], dtype=np.float64)
    masked = np.where(rth_mask, vals, np.nan)
    acc = np.fmax.accumulate(masked) if which == "high" else np.fmin.accumulate(masked)
    return pd.Series(acc, index=index)


def _rth_constant_fallback(df: pd.DataFrame, index, ds: dict | None, key: str) -> pd.Series:
    """Fallback cuando el frame no tiene barras RTH: si la sesión regular aún no
    empezó (todo el frame es pre-09:30), el valor NO existe todavía → NaN (usar
    la constante de daily_stats sería lookahead). Si ya pasó (after-hours),
    la constante del día es causal."""
    val = ds.get(key) if ds else None
    if df is not None and "timestamp" in df and len(df) > 0:
        timestamps = pd.to_datetime(df["timestamp"])
        minutes = timestamps.dt.hour.values * 60 + timestamps.dt.minute.values
        if minutes.max() < 570:
            return pd.Series(np.nan, index=index)
    return pd.Series(_safe_float(val if val is not None else np.nan), index=index)


def _session_running_max(df: pd.DataFrame, index, from_minutes: int, to_minutes: int) -> pd.Series:
    """Máximo del high ACUMULADO dentro de una ventana de reloj `[from, to)`.

    Versión general de `_pm_running_series`/`_rth_running_series` para ventanas
    que no son ni el premarket ni el RTH — la que usa "% Session Fade" en modo
    "full" (04:00-16:00, premarket y sesión regular juntos). NaN antes de la
    primera barra de la ventana; tras el cierre se queda en el valor final.
    """
    n = len(df) if df is not None else 0
    if df is None or "timestamp" not in df or n == 0:
        return pd.Series(np.nan, index=index)
    timestamps = pd.to_datetime(df["timestamp"])
    minutes = timestamps.dt.hour.values * 60 + timestamps.dt.minute.values
    mask = (minutes >= from_minutes) & (minutes < to_minutes)
    vals = np.asarray(df["high"], dtype=np.float64)
    return pd.Series(np.fmax.accumulate(np.where(mask, vals, np.nan)), index=index)


def _session_open_series(df: pd.DataFrame, index, from_minutes: int) -> pd.Series:
    """Open de la PRIMERA barra a partir de `from_minutes` (minutos desde
    medianoche), constante desde ahí y NaN antes.

    Es la versión general del ramo "open" de `_rth_running_series`: 570 = 09:30
    (apertura de mercado), 960 = 16:00 (apertura del after). El NaN previo es lo
    que hace causal a "% Session Fade": la caída de una sesión no existe hasta
    que abre la siguiente.
    """
    n = len(df) if df is not None else 0
    vals = np.full(n, np.nan)
    if df is None or "timestamp" not in df or n == 0:
        return pd.Series(vals, index=index)
    timestamps = pd.to_datetime(df["timestamp"])
    minutes = timestamps.dt.hour.values * 60 + timestamps.dt.minute.values
    mask = minutes >= from_minutes
    if not mask.any():
        return pd.Series(vals, index=index)
    first_idx = int(np.argmax(mask))
    vals[first_idx:] = float(np.asarray(df["open"], dtype=np.float64)[first_idx])
    return pd.Series(vals, index=index)


def _ap_session_started(df: pd.DataFrame, ap_session: str | None) -> np.ndarray:
    """Máscara "la sesión de referencia ya ha empezado", para Previous max/min.

    ap.RTH arranca a las 09:30, ap.AM a las 16:00 y ap.PM (defecto) desde la
    primera barra del frame.
    """
    timestamps = pd.to_datetime(df["timestamp"])
    hours = timestamps.dt.hour.values
    minutes = timestamps.dt.minute.values
    if ap_session == "ap.RTH":
        start_mask = (hours > 9) | ((hours == 9) & (minutes >= 30))
    elif ap_session == "ap.AM":
        start_mask = hours >= 16
    else:  # ap.PM default
        start_mask = np.ones(len(df), dtype=bool)
    # "started" es pegajoso: una vez dentro, ya no se sale.
    return np.maximum.accumulate(start_mask.astype(bool))


def _previous_extreme_series(
    df: pd.DataFrame, index, values: pd.Series, ap_session: str | None, which: str
) -> pd.Series:
    """Máximo/mínimo acumulado de la sesión de referencia, DESPLAZADO una barra.

    El `.shift(1)` es lo que lo hace "previous": el nivel de la barra actual no
    se incluye, así que comparar el precio contra él no es circular. Compartido
    por "Previous max"/"Previous min" y por "% Fade" con referencia al máximo
    previo, para que no puedan divergir.
    """
    started = _ap_session_started(df, ap_session)
    vals = np.asarray(values, dtype=np.float64)
    masked = np.where(started, vals, np.nan)
    acc = np.fmax.accumulate(masked) if which == "max" else np.fmin.accumulate(masked)
    return pd.Series(acc, index=index).shift(1)


def _vwap_cross_ref_series(close: pd.Series, vwap_values: np.ndarray) -> pd.Series:
    """Precio del VWAP en la vela en que el close lo cruzó por última vez.

    Cruce = la vela cierra al otro lado del VWAP respecto de la anterior. Se
    guarda el VWAP DE ESA VELA y se arrastra hasta el cruce siguiente, así que
    "% Fade" se reancla solo cada vez que el precio vuelve a cruzar. NaN antes
    del primer cruce del día: todavía no hay desde dónde medir.
    """
    c = np.asarray(close, dtype=np.float64)
    v = np.asarray(vwap_values, dtype=np.float64)
    valid = ~np.isnan(c) & ~np.isnan(v)
    above = c > v
    crossed = np.zeros(len(c), dtype=bool)
    if len(c) > 1:
        # Un NaN a cualquiera de los dos lados no es un cruce: sin esto, la
        # primera vela con volumen (VWAP pasa de NaN a número) se contaría.
        crossed[1:] = (above[1:] != above[:-1]) & valid[1:] & valid[:-1]
    ref = np.where(crossed, v, np.nan)
    return pd.Series(ref, index=close.index).ffill()


# ---------------------------------------------------------------------------
# Regresion lineal sobre el PRECIO en ventana de reloj -> pendiente y R2.
#
# Por que sobre el precio y no sobre una media: una EMA es un filtro CAUSAL,
# va retrasada (la pendiente de la EMA(20) cuenta lo que paso hace ~10 velas).
# La recta de minimos cuadrados sobre el precio suaviza igual pero SIN retraso.
# De paso sale el R2 del mismo ajuste, que es justo lo que la pendiente sola no
# dice: si el movimiento es una escalera o una sierra.
#
# La ventana es de RELOJ, no de velas — las velas del lago son dispersas y
# "20 velas atras" es una ventana distinta en cada ticker. Ver el Squeeze.
# Como el hueco nocturno mide horas, la ventana se vacia sola entre sesiones:
# no hace falta un reset por dia.
@njit(cache=True)
def _rolling_reg_clock(t_min, y, win_min, min_points):
    n = len(y)
    slope_out = np.full(n, np.nan)
    r2_out = np.full(n, np.nan)
    start = 0
    for i in range(n):
        limit = t_min[i] - win_min
        while start < i and t_min[start] < limit:
            start += 1
        cnt = i - start + 1
        if cnt < min_points:
            continue

        # x centrado en la ventana: mismo ajuste, mejor condicionamiento.
        x_mean = 0.0
        y_mean = 0.0
        for k in range(start, i + 1):
            x_mean += t_min[k]
            y_mean += y[k]
        x_mean /= cnt
        y_mean /= cnt

        num = 0.0
        den = 0.0
        for k in range(start, i + 1):
            dx = t_min[k] - x_mean
            dy = y[k] - y_mean
            num += dx * dy
            den += dx * dx
        if den == 0.0:
            # Todas las velas en el mismo instante: no hay recta que ajustar.
            continue

        slope = num / den
        intercept = y_mean - slope * x_mean

        ss_tot = 0.0
        ss_res = 0.0
        for k in range(start, i + 1):
            pred = slope * t_min[k] + intercept
            ss_tot += (y[k] - y_mean) * (y[k] - y_mean)
            ss_res += (y[k] - pred) * (y[k] - pred)

        if ss_tot <= 0.0:
            # Precio plano: la recta lo explica entero, pendiente 0.
            r2 = 1.0
        else:
            r2 = 1.0 - (ss_res / ss_tot)
            if r2 < 0.0:
                r2 = 0.0

        if y_mean > 0.0:
            # $/min -> %/min sobre el precio medio de la ventana. SIN esto la
            # pendiente no es comparable entre un ticker de 0,60 $ y uno de 45 $
            # y ningun umbral fijo valdria para el universo entero.
            slope_out[i] = slope / y_mean * 100.0
        r2_out[i] = r2
    return slope_out, r2_out


# Minutos SEGUIDOS que el precio lleva por encima (o por debajo) de un nivel.
# Es la "aceptacion": un precio que lleva 2 minutos sobre el PM High y otro que
# lleva 90 son situaciones opuestas, y para una condicion `precio > PMH` son
# identicas. Se cuenta por RELOJ y se reinicia en cada dia: una racha no puede
# arrastrarse de una sesion a la siguiente.
@njit(cache=True)
def _time_vs_level_streak(t_min, price, level, day_id, above):
    n = len(price)
    out = np.full(n, np.nan)
    t_start = 0.0
    open_streak = False
    cur_day = -1
    for i in range(n):
        if day_id[i] != cur_day:
            cur_day = day_id[i]
            open_streak = False
        lv = level[i]
        pr = price[i]
        if np.isnan(lv) or np.isnan(pr):
            # Sin referencia no hay medida. NaN, y la racha se cierra.
            open_streak = False
            continue
        if above:
            cond = pr > lv
        else:
            cond = pr < lv
        if cond:
            if not open_streak:
                t_start = t_min[i]
                open_streak = True
            out[i] = t_min[i] - t_start
        else:
            open_streak = False
            out[i] = 0.0
    return out


# Absorcion y ratio de mecha, sobre una ventana de RELOJ. Los dos salen del
# mismo recorrido, asi que se calculan juntos y el indicador elige cual devuelve.
#
#   Absorcion = millones de $ negociados por cada 1% de recorrido. ALTO = hace
#               falta mucho dinero para mover el precio: alguien esta vendiendo
#               (o comprando) todo lo que le echan. Es la profundidad de mercado
#               — el inverso de la lambda de Kyle. Se devuelve invertida a
#               proposito para que se lea natural: "Absorcion > 2" es "hacen
#               falta mas de 2 millones para moverlo un 1%".
#   Mecha     = que fraccion del recorrido total se devolvio. Arriba o abajo.
@njit(cache=True)
def _absorption_wick_clock(t_min, o, h, l, c, v, win_min):
    n = len(c)
    absorp = np.full(n, np.nan)
    wick_up = np.full(n, np.nan)
    wick_dn = np.full(n, np.nan)
    start = 0
    for i in range(n):
        limit = t_min[i] - win_min
        while start < i and t_min[start] < limit:
            start += 1
        hi = -1.0e300
        lo = 1.0e300
        dv = 0.0
        sum_rng = 0.0
        sum_up = 0.0
        sum_dn = 0.0
        for k in range(start, i + 1):
            if h[k] > hi:
                hi = h[k]
            if l[k] < lo:
                lo = l[k]
            dv += c[k] * v[k]
            sum_rng += h[k] - l[k]
            if o[k] > c[k]:
                body_hi = o[k]
                body_lo = c[k]
            else:
                body_hi = c[k]
                body_lo = o[k]
            sum_up += h[k] - body_hi
            sum_dn += body_lo - l[k]

        # El denominador es el DESPLAZAMIENTO NETO de la ventana, no el rango.
        # Es la diferencia entre las dos preguntas:
        #   rango -> "cuanto se movio" ; una vela que sube y vuelve recorrio mucho
        #   neto  -> "cuanto AVANZO"   ; esa misma vela avanzo cero
        # La absorcion es justamente "entro mucho dinero y el precio acabo donde
        # empezo", asi que el neto es el que la detecta. Con el rango, una vela
        # de absorcion con mecha larga puntuaba BAJO — medido y descartado.
        # Ademas asi no se pisa con "Wick Ratio": una mide el dinero y la otra
        # la forma, que es lo que hace util combinarlas.
        if c[i] > 0.0 and i > start:
            neto_pct = (c[i] - c[start]) / c[i] * 100.0
            if neto_pct < 0.0:
                neto_pct = -neto_pct
            # Suelo de 0,05%: medio centimo en un ticker de 5 $. Un precio que
            # vuelve EXACTO a su sitio es absorcion maxima, no un infinito que
            # rompe las comparaciones.
            if neto_pct < 0.05:
                neto_pct = 0.05
            absorp[i] = (dv / 1.0e6) / neto_pct
        if sum_rng > 0.0:
            wick_up[i] = sum_up / sum_rng
            wick_dn[i] = sum_dn / sum_rng
    return absorp, wick_up, wick_dn


# Profundidad del retroceso: que fraccion del impulso se ha devuelto ya.
#
# CAUSAL POR CONSTRUCCION, y por eso no usa deteccion de pivotes. Un pivote
# clasico mira N barras a la IZQUIERDA y N a la DERECHA, asi que en la barra t
# no se puede saber todavia que t-N era un pivote: usarlo como senal seria
# mirar al futuro. Aqui el impulso se define solo con pasado:
#
#   maximo  = el mayor high de la ventana hasta AHORA (como "High of Day")
#   base    = el menor low ANTERIOR a la barra en que se hizo ese maximo
#   impulso = maximo - base
#   salida  = (maximo - close) / impulso * 100
#
# Se lee: 0 = esta en maximos, 40 = ha devuelto el 40% de lo que subio, 100 =
# ha vuelto entero a la base del impulso, >100 = la ha perforado. Al hacer un
# maximo nuevo el impulso se reancla y el retroceso vuelve casi a 0 — igual que
# "Previous max" se actualiza vela a vela.
#
# La ventana se reinicia CADA DIA: un impulso no se arrastra de una sesion a la
# siguiente. Con `win_min = 0` el impulso es el del dia entero (el caso normal);
# con un valor > 0 se limita a esos MINUTOS DE RELOJ hacia atras.
@njit(cache=True)
def _retracement_clock(t_min, h, l, c, day_id, win_min, up):
    n = len(c)
    out = np.full(n, np.nan)
    cur_day = -1
    day_start = 0
    ptr = 0
    # Estado incremental para el caso de dia entero (win_min == 0): O(n).
    ext = 0.0        # maximo (o minimo) corrido
    base = 0.0       # extremo contrario ANTERIOR al extremo corrido
    run_opp = 0.0    # extremo contrario corrido, candidato a base
    tiene = False

    for i in range(n):
        if day_id[i] != cur_day:
            cur_day = day_id[i]
            day_start = i
            ptr = i
            tiene = False

        if win_min > 0.0:
            # Ventana de reloj: se recalcula el tramo. `w` es pequeno, asi que
            # el coste es O(n*w) y no compensa complicarlo con un deque.
            limit = t_min[i] - win_min
            while ptr < i and t_min[ptr] < limit:
                ptr += 1
            w0 = ptr
            if w0 < day_start:
                w0 = day_start
            idx = w0
            if up:
                best = h[w0]
                for k in range(w0 + 1, i + 1):
                    if h[k] > best:
                        best = h[k]
                        idx = k
                opp = l[w0]
                for k in range(w0 + 1, idx + 1):
                    if l[k] < opp:
                        opp = l[k]
                imp = best - opp
                if imp > 0.0:
                    out[i] = (best - c[i]) / imp * 100.0
            else:
                best = l[w0]
                for k in range(w0 + 1, i + 1):
                    if l[k] < best:
                        best = l[k]
                        idx = k
                opp = h[w0]
                for k in range(w0 + 1, idx + 1):
                    if h[k] > opp:
                        opp = h[k]
                imp = opp - best
                if imp > 0.0:
                    out[i] = (c[i] - best) / imp * 100.0
            continue

        # Dia entero, incremental.
        if not tiene:
            ext = h[i] if up else l[i]
            base = l[i] if up else h[i]
            run_opp = base
            tiene = True
        else:
            if up:
                if l[i] < run_opp:
                    run_opp = l[i]
                if h[i] > ext:
                    # Maximo nuevo: la base es el minimo visto ANTES de el.
                    ext = h[i]
                    base = run_opp
            else:
                if h[i] > run_opp:
                    run_opp = h[i]
                if l[i] < ext:
                    ext = l[i]
                    base = run_opp
        if up:
            imp = ext - base
            if imp > 0.0:
                out[i] = (ext - c[i]) / imp * 100.0
        else:
            imp = base - ext
            if imp > 0.0:
                out[i] = (c[i] - ext) / imp * 100.0
    return out


# Ultimo pivote confirmado: el ultimo sitio donde el precio GIRO de verdad.
#
# QUE ES UN PIVOTE. Un maximo local: una vela cuyo `high` es mayor que el de las
# `win` velas de su izquierda Y el de las `win` de su derecha. El minimo local
# es el espejo con `low`.
#
# POR QUE NO ES "Previous max". Aquel es el maximo CORRIDO del dia y NUNCA baja:
# con 10 -> 15 -> 12 -> 14 -> 11 se queda en 15 para siempre. El ultimo pivote
# alto es 14, que es el techo que el mercado acaba de dejar. Para un stop la
# diferencia lo es todo: 15 esta lejisimos y 14 esta pegado.
#
# POR QUE ES CAUSAL AUNQUE MIRE A LA DERECHA. Un pivote necesita ver `win` velas
# POSTERIORES para saber que lo era. Eso NO es mirar al futuro si se respeta el
# retardo: en la barra `i` se confirma el pivote centrado en `i - win`, o sea que
# el nivel solo esta disponible `win` velas DESPUES de haber ocurrido. Se mira
# hacia atras, nunca hacia delante. El precio a pagar es ese retardo, y es
# inevitable: hasta que no pasan velas no se sabe si un maximo era un techo.
#
# Vale NaN hasta que se confirma el primero del dia, y se reinicia cada dia.
@njit(cache=True)
def _ultimo_pivote(h, l, day_id, win, alto):
    n = len(h)
    out = np.full(n, np.nan)
    cur_day = -1
    day_start = 0
    nivel = np.nan
    for i in range(n):
        if day_id[i] != cur_day:
            cur_day = day_id[i]
            day_start = i
            nivel = np.nan
        c = i - win                      # candidato: el centro de la ventana
        if c - win >= day_start:         # con sus `win` velas a cada lado, del MISMO dia
            es_pivote = True
            # ESTRICTAMENTE mayor (o menor) que TODAS las de su ventana. Con
            # `>` en vez de `>=` los empates contaban como pivote, y en un tramo
            # de precio PLANO cada vela era su propio pivote: el nivel seguia al
            # precio en vez de quedarse en el ultimo giro. Medido y corregido.
            # Un doble techo exacto tampoco cuenta, y es lo correcto: si el
            # precio volvio al mismo sitio no hubo un giro claro.
            if alto:
                for k in range(c - win, c + win + 1):
                    if k != c and h[k] >= h[c]:
                        es_pivote = False
                        break
                if es_pivote:
                    nivel = h[c]
            else:
                for k in range(c - win, c + win + 1):
                    if k != c and l[k] <= l[c]:
                        es_pivote = False
                        break
                if es_pivote:
                    nivel = l[c]
        out[i] = nivel
    return out


# Perfil de volumen intradia: el volumen del dia repartido por FRANJAS DE
# PRECIO, en vez de por tiempo. Dice donde se ha cruzado el dinero, que es donde
# esta la gente con su coste — y por tanto donde hay oferta esperando.
#
# FRANJAS DE ANCHURA FIJA, no "el rango del dia partido en N". Si las franjas
# salieran de partir el rango, cada maximo nuevo moveria TODOS los bordes y
# habria que rehacer el histograma entero en cada vela: O(n^2 x franjas). Con
# anchura fija los bordes no se mueven y el histograma es un acumulador
# incremental. La anchura va en % del primer precio del dia, asi que es
# comparable entre un ticker de 0,40 $ y uno de 45 $.
#
# CADA VELA REPARTE su volumen entre TODAS las franjas que toca (de su minimo a
# su maximo), no entero en el cierre: una vela de un minuto que recorre un 5% no
# dejo todo su volumen en un solo precio.
#
# Los cuatro numeros que salen, todos con el dia hasta la barra i y nunca con
# velas posteriores:
#   pct   percentil de la franja del precio actual (0 = de las mas vacias)
#   poc   precio de la franja con mas volumen (el punto de control)
#   arr   primera franja POR ENCIMA que pasa el liston (la resistencia)
#   aba   primera franja POR DEBAJO que pasa el liston (el soporte)
#
# EL LISTON, en vez de "dame las N zonas mas gordas": una franja es un nodo si
# tiene al menos ese % del volumen del POC. Asi el numero de zonas lo pone el
# DIA y no un parametro — si hubo una zona sale una, si hubo tres salen tres.
_PERFIL_MAX_FRANJAS = 4096


@njit(cache=True)
def _perfil_volumen(h, l, c, v, day_id, bin_pct, liston_pct, zona_pct):
    n = len(c)
    out_pct = np.full(n, np.nan)
    out_poc = np.full(n, np.nan)
    out_arr = np.full(n, np.nan)
    out_aba = np.full(n, np.nan)
    out_zalta = np.full(n, np.nan)
    out_zbaja = np.full(n, np.nan)

    hist = np.zeros(_PERFIL_MAX_FRANJAS)
    cur_day = -1
    ancho = 0.0

    for i in range(n):
        if day_id[i] != cur_day:
            cur_day = day_id[i]
            hist[:] = 0.0
            ancho = c[i] * bin_pct / 100.0

        if ancho <= 0.0:
            continue

        i0 = int(l[i] / ancho)
        i1 = int(h[i] / ancho)
        if i0 < 0:
            i0 = 0
        if i1 >= _PERFIL_MAX_FRANJAS:
            i1 = _PERFIL_MAX_FRANJAS - 1
        if i1 < i0:
            i1 = i0
        reparto = v[i] / (i1 - i0 + 1)
        for k in range(i0, i1 + 1):
            hist[k] += reparto

        j = int(c[i] / ancho)
        if j < 0:
            j = 0
        if j >= _PERFIL_MAX_FRANJAS:
            j = _PERFIL_MAX_FRANJAS - 1

        mx = 0.0
        i_poc = -1
        con_vol = 0
        for k in range(_PERFIL_MAX_FRANJAS):
            if hist[k] > 0.0:
                con_vol += 1
                if hist[k] > mx:
                    mx = hist[k]
                    i_poc = k
        if i_poc < 0 or con_vol == 0:
            continue

        menores = 0
        for k in range(_PERFIL_MAX_FRANJAS):
            if hist[k] > 0.0 and hist[k] < hist[j]:
                menores += 1
        out_pct[i] = menores * 100.0 / con_vol if hist[j] > 0.0 else 0.0
        out_poc[i] = (i_poc + 0.5) * ancho

        umbral = mx * liston_pct / 100.0
        for k in range(j + 1, _PERFIL_MAX_FRANJAS):
            if hist[k] >= umbral:
                out_arr[i] = (k + 0.5) * ancho
                break
        for k in range(j - 1, -1, -1):
            if hist[k] >= umbral:
                out_aba[i] = (k + 0.5) * ancho
                break

        # ZONA DE VALOR. A diferencia de los nodos, NO mira donde esta el precio:
        # arranca en el POC y va tragando la franja vecina mas gorda (arriba o
        # abajo) hasta juntar `zona_pct` % del volumen del dia. Lo que sale son
        # los dos bordes de la banda donde se ha negociado casi todo.
        #
        # Por eso es ESTABLE: solo se mueve cuando cambia el reparto del volumen,
        # no cada vez que el precio cruza una franja. Es lo que se suele querer
        # dibujar en el grafico.
        total = 0.0
        for k in range(_PERFIL_MAX_FRANJAS):
            total += hist[k]
        objetivo = total * zona_pct / 100.0
        acum = hist[i_poc]
        z_lo = i_poc
        z_hi = i_poc
        while acum < objetivo:
            v_arr = hist[z_hi + 1] if z_hi + 1 < _PERFIL_MAX_FRANJAS else -1.0
            v_aba = hist[z_lo - 1] if z_lo - 1 >= 0 else -1.0
            if v_arr < 0.0 and v_aba < 0.0:
                break
            if v_arr >= v_aba:
                z_hi += 1
                acum += hist[z_hi]
            else:
                z_lo -= 1
                acum += hist[z_lo]
        out_zalta[i] = (z_hi + 0.5) * ancho
        out_zbaja[i] = (z_lo + 0.5) * ancho

    return out_pct, out_poc, out_arr, out_aba, out_zalta, out_zbaja


# Nivel de referencia compartido por "ATR Extension" y "Time vs Level".
_REF_LEVEL_MAP = {
    "vwap": "VWAP",
    "sma": "SMA",
    "ema": "EMA",
    "day_open": "Day Open",
    "rth_open": "RTH Open",
    "pmh": "PM High",
    "pml": "PM Low",
    "prev_close": "Previous Close",
    "previous_max": "Previous max",
    "previous_min": "Previous min",
    "hod": "High of Day",
    "lod": "Low of Day",
}


def _minutes_axis(df, n):
    """Eje de tiempo en minutos + id de dia. Devuelve (t_min, day_id, order).

    `order` no es None cuando las velas venian desordenadas: el asof y la
    ventana deslizante EXIGEN el eje ordenado, y sobre datos desordenados
    darian resultados arbitrarios sin avisar.
    """
    if n == 0 or "timestamp" not in df.columns:
        return None, None, None
    ts = pd.to_datetime(df["timestamp"])
    t_ns = ts.values.astype("datetime64[ns]").astype(np.int64)
    order = None
    if n > 1 and not np.all(t_ns[1:] >= t_ns[:-1]):
        order = np.argsort(t_ns, kind="stable")
        t_ns = t_ns[order]
    t_min = t_ns.astype(np.float64) / 6e10
    day_id = (t_ns // 86_400_000_000_000).astype(np.int64)
    return t_min, day_id, order


def _compute_raw(
    name: str,
    close: pd.Series,
    high: pd.Series,
    low: pd.Series,
    open_: pd.Series,
    volume: pd.Series,
    period: int | None,
    period2: int | None,
    period3: int | None,
    std_dev: float | None,
    multiplier: float | None,
    days_lookback: int | None,
    time_hour: int | None,
    time_minute: int | None,
    time_condition: str | None,
    band_line: str | None,
    orb_minutes: int | None,
    ap_session: str | None,
    daily_stats: dict | None,
    df: pd.DataFrame,
    range_minutes: int | None = None,
    pivot_window: int | None = None,
    tri_lookback: int | None = None,
    slope_tolerance: float | None = None,
    min_r_squared: float | None = None,
    min_pivots: int | None = None,
    session_ref: str | None = None,
    squeeze_direction: str | None = None,
    fade_ref: str | None = None,
    overhead_extreme: str | None = None,
    overhead_ref: str | None = None,
    overhead_vol_rule: str | None = None,
    ref_level: str | None = None,
    level_dir: str | None = None,
    wick_side: str | None = None,
    abs_op: str | None = None,
    abs_level: float | None = None,
    wick_op: str | None = None,
    wick_level: float | None = None,
    swing_dir: str | None = None,
    bin_pct: float | None = None,
    liston_pct: float | None = None,
    zona_pct: float | None = None,
) -> pd.Series:
    ds = daily_stats or {}

    # N1a: Fast-path dict dispatch for hot indicators (avoids O(n) if/elif chain)
    _fast = _FAST_INDICATOR_DISPATCH.get(name)
    if _fast is not None:
        return _fast(close, high, low, open_, volume, period, period2, period3,
                     std_dev, multiplier, days_lookback, time_hour, time_minute,
                     time_condition, band_line, orb_minutes, ap_session, ds, df,
                     range_minutes, pivot_window, tri_lookback, slope_tolerance,
                     min_r_squared, min_pivots)

    # --- Fallback: legacy if/elif chain for uncommon indicators ---
    if name == "Close":
        return close
    if name == "Open":
        return open_
    if name == "High":
        return high
    if name == "Low":
        return low
    if name == "Volume":
        return volume.astype(float)
    if name == "Day Open":
        if "rth_open" in ds and not pd.isna(ds["rth_open"]):
            return pd.Series(_safe_float(ds["rth_open"]), index=close.index)
        return pd.Series(float(open_.iloc[0]) if len(open_) > 0 else np.nan, index=close.index)
    # "Current Open" = open de la barra actual (definición de producto, Jaume
    # 2026-07-07); antes era un alias erróneo de Day Open (RTH open constante).
    if name in ("Bar Open", "Current Open"):
        return open_
    if name == "Prev. Close Bar" or name == "Prev. Bar Close":
        return close.shift(1)
    if name == "Prev. Open Bar" or name == "Prev. Bar Open":
        return open_.shift(1)
    if name == "Prev. High Bar" or name == "Prev. Bar High":
        return high.shift(1)
    if name == "Prev. Low Bar" or name == "Prev. Bar Low":
        return low.shift(1)
    if name == "Yesterday Open":
        return pd.Series(_safe_float(ds.get("yesterday_open", ds.get("lag_rth_open_1", np.nan))), index=close.index)
    if name == "Yesterday Close" or name == "Previous Close":
        return pd.Series(_safe_float(ds.get("previous_close", ds.get("prev_close", ds.get("lag_rth_close_1", np.nan)))), index=close.index)
    if name == "Yesterday High":
        return pd.Series(_safe_float(ds.get("yesterday_high", ds.get("lag_rth_high_1", np.nan))), index=close.index)
    if name == "Yesterday Low":
        return pd.Series(_safe_float(ds.get("yesterday_low", ds.get("lag_rth_low_1", np.nan))), index=close.index)
    if name == "Pre-Market High":
        # Causal: máximo del premarket ACUMULADO hasta la barra actual. Usar el PMH
        # final del día introduce lookahead en entradas premarket (la condición se
        # cumple horas antes de que el máximo exista). Tras las 09:30 la serie vale
        # el PMH completo, así que el comportamiento en RTH no cambia.
        running = _pm_running_series(df, close.index, "high")
        if running is not None:
            return running
        return pd.Series(_safe_float(ds.get("pm_high", np.nan) if ds else np.nan), index=close.index)

    if name == "Pre-Market Low":
        running = _pm_running_series(df, close.index, "low")
        if running is not None:
            return running
        return pd.Series(_safe_float(ds.get("pm_low", np.nan) if ds else np.nan), index=close.index)

    if name == "PM High Gap (%)":
        yest_close_val = ds.get("previous_close", ds.get("prev_close", ds.get("lag_rth_close_1", np.nan))) if ds else np.nan
        if yest_close_val is None or pd.isna(yest_close_val):
            yest_close_val = df["close"].iloc[0] if len(df) > 0 else np.nan
        if pd.isna(yest_close_val) or yest_close_val == 0:
            return pd.Series(np.nan, index=close.index)
        # Gap causal barra a barra sobre el PMH acumulado (ver Pre-Market High).
        running = _pm_running_series(df, close.index, "high")
        if running is None:
            pm_high_val = ds.get("pm_high") if ds else None
            running = pd.Series(_safe_float(pm_high_val if pm_high_val is not None else np.nan), index=close.index)
        return (running - float(yest_close_val)) / float(yest_close_val) * 100.0
    if name == "Current Gap (%)":
        # Gap VIVO barra a barra: close de la barra actual vs cierre de ayer
        # (misma cadena de fallback que "PM High Gap (%)"). A diferencia de
        # aquel, mide dónde está el precio AHORA: sigue actualizándose durante
        # el RTH y baja si el precio baja.
        yest_close_val = ds.get("previous_close", ds.get("prev_close", ds.get("lag_rth_close_1", np.nan))) if ds else np.nan
        if yest_close_val is None or pd.isna(yest_close_val):
            yest_close_val = df["close"].iloc[0] if len(df) > 0 else np.nan
        if pd.isna(yest_close_val) or yest_close_val == 0:
            return pd.Series(np.nan, index=close.index)
        return (close - float(yest_close_val)) / float(yest_close_val) * 100.0

    if name == "Open Gap (%)":
        # GAP DE APERTURA: la apertura del RTH contra el cierre de ayer. A
        # diferencia de «Current Gap (%)», que se mueve con el precio, este es
        # el gap con el que abrio el mercado y ya no cambia en todo el dia.
        #
        # CAUSAL A PROPOSITO: NaN antes de las 09:30. Usar la constante del dia
        # (gap_at_open_pct de daily_metrics) desde las 04:00 seria LOOKAHEAD —
        # en premercado nadie sabe todavia a cuanto va a abrir el mercado, y una
        # estrategia que entra a las 08:00 la estaria usando. El NaN de la
        # manyana no es un fallo: cualquier condicion sobre el evalua False
        # hasta que el mercado abre (mismo criterio que «% Session Fade»).
        yest_close_val = ds.get("previous_close", ds.get("prev_close", ds.get("lag_rth_close_1", np.nan))) if ds else np.nan
        if yest_close_val is None or pd.isna(yest_close_val):
            yest_close_val = df["close"].iloc[0] if len(df) > 0 else np.nan
        if pd.isna(yest_close_val) or yest_close_val == 0:
            return pd.Series(np.nan, index=close.index)
        apertura = _rth_running_series(df, close.index, "open")
        if apertura is None:
            # Sin barras RTH en el frame: el fallback ya distingue si la sesion
            # regular aun no ha llegado (NaN) o si ya paso (constante causal).
            apertura = _rth_constant_fallback(df, close.index, ds, "rth_open")
        return (apertura - float(yest_close_val)) / float(yest_close_val) * 100.0

    if name == "% Session Fade":
        # Cuánto se desinfló una sesión entera, en POSITIVO (10 = cayó un 10%):
        #   pm   -> (PM High        − apertura de mercado) / PM High        * 100
        #   rth  -> (máx. RTH       − apertura del after)  / máx. RTH       * 100
        #   full -> (máx. PM + RTH  − apertura del after)  / máx. PM+RTH    * 100
        # Causal sin necesidad de trucos: la apertura de la sesión siguiente es
        # NaN hasta que esa sesión abre, y para entonces el máximo de referencia
        # ya está cerrado y no puede cambiar. Antes de eso el indicador es NaN y
        # cualquier condición evalúa False.
        if session_ref == "rth":
            peak = _rth_running_series(df, close.index, "high")
            if peak is None:
                peak = _rth_constant_fallback(df, close.index, ds, "rth_high")
            nxt_open = _session_open_series(df, close.index, 960)
        elif session_ref == "full":
            # El día entero de negociación (04:00-16:00): mide el desinflado
            # REAL, sin que importe si el máximo se hizo en premarket o en RTH.
            peak = _session_running_max(df, close.index, 240, 960)
            nxt_open = _session_open_series(df, close.index, 960)
        else:  # "pm" por defecto
            peak = _pm_running_series(df, close.index, "high")
            if peak is None:
                peak = pd.Series(_safe_float(ds.get("pm_high", np.nan)), index=close.index)
            nxt_open = _rth_running_series(df, close.index, "open")
            if nxt_open is None:
                nxt_open = _rth_constant_fallback(df, close.index, ds, "rth_open")
        peak = peak.where(peak != 0.0, np.nan)
        return (peak - nxt_open) / peak * 100.0

    if name == "% Fade":
        # Caída VIVA desde una referencia que se reancla sola, en positivo. Si la
        # referencia sube (nuevo máximo, nuevo cruce), el fade vuelve a ~0 y
        # empieza a contar de nuevo. Negativo = el precio está por encima.
        if fade_ref == "vwap_cross":
            vwap_vals = _vwap(
                high.values.astype(np.float64),
                low.values.astype(np.float64),
                close.values.astype(np.float64),
                volume.values.astype(np.float64),
            )
            ref = _vwap_cross_ref_series(close, vwap_vals)
        else:  # "previous_max" por defecto
            ref = _previous_extreme_series(df, close.index, high, ap_session, "max")
        ref = ref.where(ref != 0.0, np.nan)
        return (ref - close) / ref * 100.0

    if name in ("RTH Open", "rth_open"):
        # Causal: NaN antes de la primera barra RTH (antes devolvía la constante
        # del día → una condición premarket "veía" el open de las 09:30).
        running = _rth_running_series(df, close.index, "open")
        if running is not None:
            return running
        return _rth_constant_fallback(df, close.index, ds, "rth_open")
    if name in ("RTH High", "rth_high"):
        # Causal: cummax de la sesión regular hasta la barra actual (antes la
        # constante del día completo = lookahead intradía, mismo defecto que
        # tenía Pre-Market High).
        running = _rth_running_series(df, close.index, "high")
        if running is not None:
            return running
        return _rth_constant_fallback(df, close.index, ds, "rth_high")
    if name in ("RTH Low", "rth_low"):
        running = _rth_running_series(df, close.index, "low")
        if running is not None:
            return running
        return _rth_constant_fallback(df, close.index, ds, "rth_low")
    if name == "High of Day":
        return high.cummax()
    if name == "Low of Day":
        return low.cummin()
    if name in ("High of last X days", "Max of last X days",
                "Low of last X days", "Min of last X days",
                "Overhead last X days"):
        # Los tres nombres comparten motor. Los dos historicos solo fijan los
        # defectos (`Low/Min` -> el dia del minimo mas bajo, y su low como
        # nivel); "Overhead" es el que expone los cuatro parametros.
        return _overhead_nivel(
            name, close, volume, ds,
            days_lookback or period,
            overhead_extreme, overhead_ref, overhead_vol_rule,
        )

    if name == "Previous max":
        return _previous_extreme_series(df, close.index, high, ap_session, "max")

    if name == "Previous min":
        return _previous_extreme_series(df, close.index, low, ap_session, "min")

    if name == "PM Open":
        timestamps = pd.to_datetime(df["timestamp"])
        hours = timestamps.dt.hour
        minutes = timestamps.dt.minute
        pm_mask = (hours < 9) | ((hours == 9) & (minutes < 30))
        pm_bars = open_[pm_mask]
        if len(pm_bars) > 0:
            pm_open_val = float(pm_bars.iloc[0])
        else:
            pm_open_val = _safe_float(ds.get("rth_open", np.nan))
        return pd.Series(pm_open_val, index=close.index)

    if name == "AM Open":
        timestamps = pd.to_datetime(df["timestamp"])
        hours = timestamps.dt.hour
        am_mask = hours >= 16
        am_bars = open_[am_mask]
        if len(am_bars) > 0:
            am_open_val = float(am_bars.iloc[0])
        else:
            am_open_val = np.nan
        return pd.Series(am_open_val, index=close.index)

    # --- Trend / MA ---
    if name == "SMA":
        return pd.Series(_sma(close.values, period or 20), index=close.index)
    if name == "EMA":
        return pd.Series(_ema(close.values, period or 20), index=close.index)
    if name == "WMA":
        if _talib is not None:
            return pd.Series(_talib.WMA(close.values, timeperiod=period or 20), index=close.index)
        if ta is not None:
            result = ta.wma(close, length=period or 20)
            if result is not None:
                return result
        # Fallback: weighted moving average
        w = period or 20
        weights = np.arange(1, w + 1, dtype=np.float64)
        out = np.full(len(close), np.nan)
        for i in range(w - 1, len(close)):
            out[i] = np.dot(close.values[i - w + 1:i + 1], weights) / weights.sum()
        return pd.Series(out, index=close.index)

    if name in ("VWAP", "AVWAP"):
        vals = _vwap(high.values.astype(np.float64), low.values.astype(np.float64),
                     close.values.astype(np.float64), volume.values.astype(np.float64))
        return pd.Series(vals, index=close.index)

    if name == "Linear Regression":
        return pd.Series(_linear_regression(close.values.astype(np.float64), period or 14), index=close.index)

    # --- Momentum ---
    if name == "RSI":
        return pd.Series(_rsi(close.values, period or 14), index=close.index)

    if name == "MACD":
        fast = period or 12
        slow = period2 or 26
        signal = period3 or 9
        macd_line, signal_line, histogram = _macd(close.values.astype(np.float64), fast, slow, signal)
        return pd.Series(macd_line, index=close.index)

    if name == "MACD Signal":
        fast = period or 12
        slow = period2 or 26
        signal = period3 or 9
        _, signal_line, _ = _macd(close.values.astype(np.float64), fast, slow, signal)
        return pd.Series(signal_line, index=close.index)

    if name == "MACD Histogram":
        fast = period or 12
        slow = period2 or 26
        signal = period3 or 9
        _, _, histogram = _macd(close.values.astype(np.float64), fast, slow, signal)
        return pd.Series(histogram, index=close.index)

    if name == "Stochastic":
        k_period = period or 14
        d_period = period2 or 3
        k, d = _stochastic(high.values.astype(np.float64), low.values.astype(np.float64),
                           close.values.astype(np.float64), k_period, d_period)
        return pd.Series(k, index=close.index)

    if name == "Stochastic %D":
        k_period = period or 14
        d_period = period2 or 3
        _, d = _stochastic(high.values.astype(np.float64), low.values.astype(np.float64),
                           close.values.astype(np.float64), k_period, d_period)
        return pd.Series(d, index=close.index)

    if name == "Momentum":
        return pd.Series(_momentum(close.values.astype(np.float64), period or 10), index=close.index)

    if name == "CCI":
        return pd.Series(_cci(high.values.astype(np.float64), low.values.astype(np.float64),
                              close.values.astype(np.float64), period or 20), index=close.index)

    if name == "ROC":
        return pd.Series(_roc(close.values.astype(np.float64), period or 12), index=close.index)

    if name == "DMI":
        plus_di, minus_di = _dmi(high.values.astype(np.float64), low.values.astype(np.float64),
                                 close.values.astype(np.float64), period or 14)
        return pd.Series(plus_di, index=close.index)

    if name == "DMI-":
        _, minus_di = _dmi(high.values.astype(np.float64), low.values.astype(np.float64),
                           close.values.astype(np.float64), period or 14)
        return pd.Series(minus_di, index=close.index)

    if name == "Williams %R":
        if _talib is not None:
            return pd.Series(
                _talib.WILLR(high.values, low.values, close.values, timeperiod=period or 14),
                index=close.index,
            )
        if ta is not None:
            result = ta.willr(high, low, close, length=period or 14)
            if result is not None:
                return result
        # Fallback
        p = period or 14
        out = np.full(len(close), np.nan)
        for i in range(p - 1, len(close)):
            hh = np.max(high.values[i - p + 1:i + 1])
            ll = np.min(low.values[i - p + 1:i + 1])
            if hh != ll:
                out[i] = (hh - close.values[i]) / (hh - ll) * -100
        return pd.Series(out, index=close.index)

    # --- Volatility ---
    if name == "ATR":
        return pd.Series(_atr(high.values.astype(np.float64), low.values.astype(np.float64),
                               close.values.astype(np.float64), period or 14), index=close.index)

    if name == "ADX":
        if _talib is not None:
            return pd.Series(
                _talib.ADX(high.values, low.values, close.values, timeperiod=period or 14),
                index=close.index,
            )
        if ta is not None:
            adx_df = ta.adx(high, low, close, length=period or 14)
            if adx_df is not None:
                return adx_df.iloc[:, 0]
        return pd.Series(np.nan, index=close.index)

    if name == "Bollinger Bands" or name == "Bollinger Upper":
        period = period or 20
        sd = std_dev or 2.0
        upper, middle, lower = _bollinger_bands(close.values.astype(np.float64), period, sd)
        if band_line == "Lower":
            return pd.Series(lower, index=close.index)
        elif band_line == "Basis":
            return pd.Series(middle, index=close.index)
        else:  # Upper es default
            return pd.Series(upper, index=close.index)

    if name == "Bollinger Middle":
        sd = std_dev or 2.0
        _, middle, _ = _bollinger_bands(close.values.astype(np.float64), period or 20, sd)
        return pd.Series(middle, index=close.index)

    if name == "Bollinger Lower":
        sd = std_dev or 2.0
        _, _, lower = _bollinger_bands(close.values.astype(np.float64), period or 20, sd)
        return pd.Series(lower, index=close.index)

    if name == "Darvas Box":
        # `period` = N velas de confirmacion (3 en el Darvas clasico).
        # `band_line` elige que linea de la caja se devuelve:
        #   "Upper" -> darvas superior, la RESISTENCIA (por defecto)
        #   "Lower" -> darvas inferior, el SOPORTE
        #   "Basis" -> el centro, por simetria con las otras bandas
        # Devuelve un NIVEL por vela, constante mientras la caja vive, para
        # poder cruzarlo contra cualquier otra variable igual que un soporte o
        # una resistencia cualquiera. NaN mientras no hay caja: una comparacion
        # contra NaN da False, que es justo lo que se quiere (sin caja no hay
        # señal). Ver _darvas_box_core para la maquina de estados.
        techo, suelo = _darvas_box(
            high.values.astype(np.float64),
            low.values.astype(np.float64),
            close.values.astype(np.float64),
            period or 3,
        )
        if band_line == "Lower":
            return pd.Series(suelo, index=close.index)
        if band_line == "Basis":
            return pd.Series((techo + suelo) / 2.0, index=close.index)
        return pd.Series(techo, index=close.index)

    if name == "Donchian Channels":
        period = period or 20
        upper = high.rolling(period).max().shift(1)
        lower = low.rolling(period).min().shift(1)
        mid = (upper + lower) / 2
        if band_line == "Lower":
            return lower
        elif band_line == "Basis":
            return mid
        else:  # Upper es default
            return upper

    if name == "Parabolic SAR":
        if _talib is not None:
            accel = multiplier or 0.02
            return pd.Series(
                _talib.SAR(high.values, low.values, acceleration=accel, maximum=0.2),
                index=close.index,
            )
        if ta is not None:
            result = ta.psar(high, low, close)
            if result is not None:
                # pandas_ta returns a DataFrame, pick the main column
                for col in result.columns:
                    if 'PSARl' in col or 'PSAR' in col:
                        return result[col]
        return pd.Series(np.nan, index=close.index)

    # --- Volume ---
    if name == "OBV":
        return pd.Series(_obv(close.values.astype(np.float64), volume.values.astype(np.float64)), index=close.index)

    if name == "Accumulated Volume":
        return volume.cumsum().astype(float)

    if name == "Accumulated Dollar Volume":
        # Acum. Dollar Volume: suma de (volumen x cierre) de CADA vela desde el
        # inicio de sesion hasta la actual. Es cumsum(volumen x close) — cada
        # barra aporta su propio volumen x su propio close.
        return (volume.astype(float) * close.astype(float)).cumsum()

    if name == "Dollar Volume":
        # Dollar Volume: el valor en dolares de ESTA vela, volumen x cierre. Sin
        # acumular.
        return (volume.astype(float) * close.astype(float))

    if name == "RVOL by bar" or name == "RVOL":
        # Relative Volume: current cumulative volume / average cumulative volume at same time
        # Simple approximation: volume / SMA(volume, period)
        p = period or 20
        avg_vol = _sma(volume.values.astype(np.float64), p)
        with np.errstate(divide="ignore", invalid="ignore"):
            rvol = volume.values.astype(np.float64) / np.where(avg_vol != 0, avg_vol, np.nan)
        return pd.Series(rvol, index=close.index)

    if name == "Chaikin Money Flow":
        p = period or 20
        mfm = ((close.values - low.values) - (high.values - close.values)) / (high.values - low.values + 1e-10)
        mfv = mfm * volume.values.astype(np.float64)
        sum_mfv = _sma(mfv, p) * p
        sum_vol = _sma(volume.values.astype(np.float64), p) * p
        with np.errstate(divide="ignore", invalid="ignore"):
            cmf = np.where(sum_vol != 0, sum_mfv / sum_vol, 0)
        return pd.Series(cmf, index=close.index)

    if name == "Accumulation/Distribution":
        mfm = ((close.values - low.values) - (high.values - close.values)) / (high.values - low.values + 1e-10)
        ad = np.cumsum(mfm * volume.values.astype(np.float64))
        return pd.Series(ad, index=close.index)

    # --- Behavior / Consecutive ---
    if name == "Consecutive Red Candles":
        signal = (close.values < open_.values)
        return pd.Series(_consecutive_count(signal), index=close.index)

    if name == "Consecutive Green Candles":
        signal = (close.values > open_.values)
        return pd.Series(_consecutive_count(signal), index=close.index)

    if name == "Consecutive Higher Highs":
        hh = np.empty(len(high), dtype=np.bool_)
        hh[0] = False
        hh[1:] = high.values[1:] > high.values[:-1]
        return pd.Series(_consecutive_count(hh), index=close.index)

    if name == "Consecutive Lower Highs":
        lh = np.empty(len(high), dtype=np.bool_)
        lh[0] = False
        lh[1:] = high.values[1:] < high.values[:-1]
        return pd.Series(_consecutive_count(lh), index=close.index)

    if name == "Consecutive Lower Lows":
        ll = np.empty(len(low), dtype=np.bool_)
        ll[0] = False
        ll[1:] = low.values[1:] < low.values[:-1]
        return pd.Series(_consecutive_count(ll), index=close.index)

    if name == "Consecutive Higher Lows":
        hl = np.empty(len(low), dtype=np.bool_)
        hl[0] = False
        hl[1:] = low.values[1:] > low.values[:-1]
        return pd.Series(_consecutive_count(hl), index=close.index)

    # --- Heikin-Ashi values (for direct reference, not calc_on_heikin) ---
    if name == "Heikin-Ashi" or name == "HA Close":
        ha_o, ha_h, ha_l, ha_c = _heikin_ashi(open_.values.astype(np.float64), high.values.astype(np.float64),
                                                low.values.astype(np.float64), close.values.astype(np.float64))
        return pd.Series(ha_c, index=close.index)
    if name == "HA Open":
        ha_o, _, _, _ = _heikin_ashi(open_.values.astype(np.float64), high.values.astype(np.float64),
                                      low.values.astype(np.float64), close.values.astype(np.float64))
        return pd.Series(ha_o, index=close.index)
    if name == "HA High":
        _, ha_h, _, _ = _heikin_ashi(open_.values.astype(np.float64), high.values.astype(np.float64),
                                      low.values.astype(np.float64), close.values.astype(np.float64))
        return pd.Series(ha_h, index=close.index)
    if name == "HA Low":
        _, _, ha_l, _ = _heikin_ashi(open_.values.astype(np.float64), high.values.astype(np.float64),
                                      low.values.astype(np.float64), close.values.astype(np.float64))
        return pd.Series(ha_l, index=close.index)

    # --- Time / Other ---
    if name == "Ret % PM":
        pm_h = ds.get("pm_high", np.nan)
        prev_c = ds.get("previous_close", np.nan)
        val = (pm_h - prev_c) / prev_c * 100 if prev_c and prev_c > 0 else np.nan
        return pd.Series(val, index=close.index)
    if name == "Ret % RTH":
        return (close - open_.iloc[0]) / open_.iloc[0] * 100 if open_.iloc[0] > 0 else pd.Series(np.nan, index=close.index)
    if name == "Ret % AM":
        return (close - open_.iloc[0]) / open_.iloc[0] * 100 if open_.iloc[0] > 0 else pd.Series(np.nan, index=close.index)

    if name == "Time of Day":
        ts = pd.to_datetime(df["timestamp"])
        minutes = ts.dt.hour * 60 + ts.dt.minute
        # Apply time_condition if provided
        if time_hour is not None and time_minute is not None and time_condition:
            target_min = time_hour * 60 + time_minute
            if time_condition == "BEFORE":
                return (minutes < target_min).astype(float)
            elif time_condition == "AFTER":
                return (minutes >= target_min).astype(float)
        return minutes

    if name == "Squeeze":
        # Squeeze — cuanto se ha DISPARADO el precio en una ventana de reloj.
        #
        # Mide punta a punta: cierre actual contra el cierre de hace
        # `range_minutes` MINUTOS. Un zigzag dentro de la ventana no lo rompe
        # (100 -> 110 -> 104,5 -> 114,95 sale +15%), pero una caida seguida de
        # un disparo dentro de la MISMA ventana se compensa (100 -> 90 -> 105
        # sale +5%, no +16,7%). Semantica fijada por el usuario el 2026-08-26.
        #
        # La ventana es de RELOJ, no de velas, y esto NO es un detalle: las
        # velas del lago son dispersas (solo existe el minuto que tuvo
        # operaciones), asi que "5 velas atras" seria una ventana distinta en
        # cada ticker y en cada tramo del dia. La referencia se busca con un
        # asof HACIA ATRAS: el ultimo cierre conocido en `t - X min`. Si el
        # simbolo no cotizo en ese hueco, el precio no cambio — la referencia
        # sigue siendo el ultimo print y el spike aparece entero en la primera
        # vela nueva, que es justo lo que se ve en el grafico.
        #
        # Vale NaN mientras la ventana empieza antes de la primera vela del
        # dia (no hay contra que comparar). Una comparacion contra NaN da
        # False: sin referencia, no hay senal. Mismo convenio que Darvas.
        win = int(range_minutes) if range_minutes else 5
        if win < 1:
            win = 1
        c_vals = close.values.astype(np.float64)
        n = len(c_vals)
        out = np.full(n, np.nan)
        if n > 0 and "timestamp" in df.columns:
            t_ns = pd.to_datetime(df["timestamp"]).values.astype("datetime64[ns]").astype(np.int64)
            order = None
            if n > 1 and not np.all(t_ns[1:] >= t_ns[:-1]):
                # El asof exige el eje de tiempo ordenado. El motor entrega las
                # velas en orden, pero sobre datos desordenados searchsorted
                # devolveria referencias arbitrarias SIN avisar.
                order = np.argsort(t_ns, kind="stable")
                t_ns = t_ns[order]
                c_ord = c_vals[order]
            else:
                c_ord = c_vals
            ref_ns = t_ns - int(win) * 60 * 1_000_000_000
            idx = np.searchsorted(t_ns, ref_ns, side="right") - 1
            ok = idx >= 0
            if ok.any():
                base = c_ord[idx[ok]]
                with np.errstate(divide="ignore", invalid="ignore"):
                    pct = np.where(base > 0, (c_ord[ok] - base) / base * 100.0, np.nan)
                res = np.full(n, np.nan)
                res[ok] = pct
                if order is not None:
                    out[order] = res
                else:
                    out = res
        if str(squeeze_direction or "up").lower() == "down":
            # "Abajo" devuelve la CAIDA en positivo, para que la condicion se
            # lea igual en las dos direcciones: "Squeeze > 10" es "se ha
            # movido mas de un 10% en la direccion elegida".
            out = -out
        return pd.Series(out, index=close.index)

    if name in ("Reg. Slope", "Reg. R2"):
        # Recta de minimos cuadrados sobre el PRECIO de los ultimos
        # `range_minutes` MINUTOS (de reloj, no de velas).
        #
        #   Reg. Slope -> pendiente en % por minuto (normalizada por el precio
        #                 medio de la ventana, asi que 0,25 significa lo mismo
        #                 en un ticker de 0,60 $ que en uno de 45 $).
        #   Reg. R2    -> de 0 a 1: que parte del movimiento explica la recta.
        #
        # Las dos salen del MISMO ajuste. La pendiente dice cuanto se mueve;
        # el R2 dice si se puede uno montar encima. Dos series que suben lo
        # mismo pueden ser una escalera (R2 ~ 0,99) o una sierra (R2 ~ 0,15).
        #
        # NaN mientras la ventana no tenga al menos 3 velas: con 2 puntos la
        # recta pasa por los dos y el R2 seria 1 siempre — un 1 que no
        # significa nada.
        win = int(range_minutes) if range_minutes else 20
        if win < 1:
            win = 1
        c_vals = close.values.astype(np.float64)
        n = len(c_vals)
        out = np.full(n, np.nan)
        t_min, _day_id, order = _minutes_axis(df, n)
        if t_min is not None:
            c_ord = c_vals[order] if order is not None else c_vals
            slope_arr, r2_arr = _rolling_reg_clock(t_min, c_ord, float(win), 3)
            res = slope_arr if name == "Reg. Slope" else r2_arr
            if order is not None:
                out[order] = res
            else:
                out = res
        return pd.Series(out, index=close.index)

    if name in ("Vol. de la franja", "Punto de control",
                "Nodo de arriba", "Nodo de abajo",
                "Zona alta", "Zona baja"):
        # Los cuatro salen del MISMO recorrido. Ver `_perfil_volumen`.
        n = len(close)
        out = np.full(n, np.nan)
        t_min, day_id, order = _minutes_axis(df, n)
        if t_min is not None:
            h_v = high.values.astype(np.float64)
            l_v = low.values.astype(np.float64)
            c_v = close.values.astype(np.float64)
            v_v = volume.values.astype(np.float64)
            if order is not None:
                h_v, l_v, c_v, v_v = h_v[order], l_v[order], c_v[order], v_v[order]
            bp = float(bin_pct) if bin_pct else 1.0
            if bp <= 0.0:
                bp = 1.0
            lp = float(liston_pct) if liston_pct is not None else 60.0
            if lp < 0.0:
                lp = 0.0
            zp = float(zona_pct) if zona_pct is not None else 70.0
            if zp <= 0.0:
                zp = 70.0
            if zp > 100.0:
                zp = 100.0
            pct, poc, arr, aba, zalta, zbaja = _perfil_volumen(
                h_v, l_v, c_v, v_v, day_id, bp, lp, zp)
            if name == "Vol. de la franja":
                res = pct
            elif name == "Punto de control":
                res = poc
            elif name == "Nodo de arriba":
                res = arr
            elif name == "Nodo de abajo":
                res = aba
            elif name == "Zona alta":
                res = zalta
            else:
                res = zbaja
            if order is not None:
                out[order] = res
            else:
                out = res
        return pd.Series(out, index=close.index)

    if name == "Ultimo pivote":
        # Ver `_ultimo_pivote`. `pivot_window` son las velas de confirmacion a
        # cada lado (las mismas que usan los triangulos), y `swing_dir` elige si
        # se buscan techos ("up") o suelos ("down").
        win = int(pivot_window) if pivot_window else 3
        if win < 1:
            win = 1
        n = len(close)
        out = np.full(n, np.nan)
        t_min, day_id, order = _minutes_axis(df, n)
        if t_min is not None:
            h_v = high.values.astype(np.float64)
            l_v = low.values.astype(np.float64)
            if order is not None:
                h_v, l_v = h_v[order], l_v[order]
            res = _ultimo_pivote(h_v, l_v, day_id, win,
                                 str(swing_dir or "up").lower() != "down")
            if order is not None:
                out[order] = res
            else:
                out = res
        return pd.Series(out, index=close.index)

    if name == "Retroceso (%)":
        # Ver `_retracement_clock` para la definicion y por que es causal.
        win = float(range_minutes) if range_minutes else 0.0
        if win < 0.0:
            win = 0.0
        n = len(close)
        out = np.full(n, np.nan)
        t_min, day_id, order = _minutes_axis(df, n)
        if t_min is not None:
            h_v = high.values.astype(np.float64)
            l_v = low.values.astype(np.float64)
            c_v = close.values.astype(np.float64)
            if order is not None:
                h_v, l_v, c_v = h_v[order], l_v[order], c_v[order]
            up = str(swing_dir or "up").lower() != "down"
            res = _retracement_clock(t_min, h_v, l_v, c_v, day_id, win, up)
            if order is not None:
                out[order] = res
            else:
                out = res
        return pd.Series(out, index=close.index)

    if name in ("Absorption", "Wick Ratio", "Absorption + Wick"):
        # Los tres salen del MISMO recorrido de la ventana de reloj.
        #
        # "Absorption": millones de dolares negociados por cada 1% de recorrido.
        #   Se devuelve INVERTIDA respecto a la lambda de Kyle para que la
        #   condicion se lea natural: mas alto = mas dificil de mover = alguien
        #   esta absorbiendo. "Absorption > 2" es "hicieron falta mas de 2
        #   millones para moverlo un 1%".
        #
        # "Wick Ratio": que fraccion del recorrido total de la ventana se
        #   devolvio en forma de mecha, arriba (`wick_side="upper"`) o abajo.
        #   De 0 a 1. 0,5 = la mitad de lo que se recorrio se rechazo.
        #
        # "Absorption + Wick": 1 si se cumplen LAS DOS condiciones de umbral,
        #   0 si no, NaN si falta cualquiera de las dos medidas. Existe para
        #   poder pedir "mucho dinero Y mucho rechazo" en UNA condicion — que
        #   es cuando la lectura significa algo. Por separado, cada una tiene
        #   una interpretacion distinta segun como este la otra.
        win = int(range_minutes) if range_minutes else 5
        if win < 1:
            win = 1
        n = len(close)
        out = np.full(n, np.nan)
        t_min, _day_id, order = _minutes_axis(df, n)
        if t_min is not None:
            o_v = open_.values.astype(np.float64)
            h_v = high.values.astype(np.float64)
            l_v = low.values.astype(np.float64)
            c_v = close.values.astype(np.float64)
            v_v = volume.values.astype(np.float64)
            if order is not None:
                o_v, h_v, l_v, c_v, v_v = (o_v[order], h_v[order], l_v[order],
                                           c_v[order], v_v[order])
            absorp, wick_up, wick_dn = _absorption_wick_clock(
                t_min, o_v, h_v, l_v, c_v, v_v, float(win))
            wick = wick_dn if str(wick_side or "upper").lower() == "lower" else wick_up

            if name == "Absorption":
                res = absorp
            elif name == "Wick Ratio":
                res = wick
            else:
                a_lvl = float(abs_level) if abs_level is not None else 2.5
                w_lvl = float(wick_level) if wick_level is not None else 0.4
                a_gt = str(abs_op or "gt").lower() != "lt"
                w_gt = str(wick_op or "gt").lower() != "lt"
                ok_a = absorp > a_lvl if a_gt else absorp < a_lvl
                ok_w = wick > w_lvl if w_gt else wick < w_lvl
                res = np.where(np.isnan(absorp) | np.isnan(wick), np.nan,
                               np.where(ok_a & ok_w, 1.0, 0.0))
            if order is not None:
                out[order] = res
            else:
                out = res
        return pd.Series(out, index=close.index)

    if name in ("ATR Extension", "Time vs Level"):
        # Los dos miden contra un NIVEL de referencia (`ref_level`), y los dos
        # lo resuelven llamando al indicador que ya existe para ese nivel: no
        # hay una segunda formula del VWAP ni del PM High que pueda divergir.
        #
        # El periodo de la media de referencia (si `ref_level` es sma/ema) sale
        # SIEMPRE de `period2`, nunca de `period` — en "ATR Extension" `period`
        # es el del ATR.
        ref_key = str(ref_level or "vwap").lower()
        ref_name = normalize_indicator_name(_REF_LEVEL_MAP.get(ref_key, "VWAP"))
        ref_period = int(period2) if period2 else 20
        level = _compute_raw(
            ref_name, close, high, low, open_, volume,
            ref_period, None, None, std_dev, None,
            days_lookback, time_hour, time_minute, time_condition,
            band_line, orb_minutes, ap_session, ds, df,
            range_minutes=range_minutes,
            pivot_window=pivot_window, tri_lookback=tri_lookback,
            slope_tolerance=slope_tolerance, min_r_squared=min_r_squared,
            min_pivots=min_pivots, session_ref=session_ref,
            squeeze_direction=squeeze_direction, fade_ref=fade_ref,
        )
        lvl_vals = np.asarray(level, dtype=np.float64)

        if name == "ATR Extension":
            # Cuantos ATR separan al precio de su referencia. Positivo = por
            # encima. Es la version comparable de "esta un 8% sobre el VWAP":
            # un 8% es una barbaridad en un ticker que se mueve un 2% al dia y
            # es ruido en uno que se mueve un 30%, asi que un umbral en % no
            # vale para el universo entero y uno en ATR si.
            atr_vals = _atr(
                high.values.astype(np.float64), low.values.astype(np.float64),
                close.values.astype(np.float64), period or 14,
            )
            atr_vals = np.asarray(atr_vals, dtype=np.float64)
            with np.errstate(divide="ignore", invalid="ignore"):
                out = np.where(atr_vals > 0, (close.values.astype(np.float64) - lvl_vals) / atr_vals, np.nan)
            return pd.Series(out, index=close.index)

        # "Time vs Level": minutos SEGUIDOS por encima (o por debajo) del nivel.
        # 0 cuando la condicion no se cumple; NaN mientras el nivel no exista
        # todavia (antes de las 09:30 no hay RTH Open, y comparar contra NaN da
        # False: sin referencia, no hay senal).
        n = len(close)
        out = np.full(n, np.nan)
        t_min, day_id, order = _minutes_axis(df, n)
        if t_min is not None:
            pr = close.values.astype(np.float64)
            pr_ord = pr[order] if order is not None else pr
            lv_ord = lvl_vals[order] if order is not None else lvl_vals
            above = str(level_dir or "above").lower() != "below"
            res = _time_vs_level_streak(t_min, pr_ord, lv_ord, day_id, above)
            if order is not None:
                out[order] = res
            else:
                out = res
        return pd.Series(out, index=close.index)

    if name == "Range of time" or name == "Range of Time":
        timestamps = pd.to_datetime(df["timestamp"])
        if len(timestamps) > 0:
            dates = timestamps.dt.normalize()
            rth_start = dates + pd.to_timedelta("9h 30m")
            am_start = dates + pd.to_timedelta("16h")
            first_candle_of_day = pd.to_datetime(df.groupby(dates)["timestamp"].transform("first"))
            
            is_rth = (timestamps >= rth_start) & (timestamps < am_start)
            is_am = timestamps >= am_start
            
            start_times = pd.Series(first_candle_of_day, index=df.index)
            start_times = start_times.mask(is_rth, rth_start)
            start_times = start_times.mask(is_am, am_start)
            
            elapsed = (timestamps - start_times).dt.total_seconds() / 60.0
            return elapsed.clip(lower=0.0)
        else:
            return pd.Series(0.0, index=close.index)

    if name == "Max N Bars":
        return pd.Series(np.arange(len(close), dtype=float), index=close.index)

    if name == "Pivot Points" or name == "PP":
        pivots = _pivot_points(ds)
        return pd.Series(pivots.get("PP", np.nan), index=close.index)
    if name == "R1":
        pivots = _pivot_points(ds)
        return pd.Series(pivots.get("R1", np.nan), index=close.index)
    if name == "S1":
        pivots = _pivot_points(ds)
        return pd.Series(pivots.get("S1", np.nan), index=close.index)
    if name == "R2":
        pivots = _pivot_points(ds)
        return pd.Series(pivots.get("R2", np.nan), index=close.index)
    if name == "S2":
        pivots = _pivot_points(ds)
        return pd.Series(pivots.get("S2", np.nan), index=close.index)

    if name in ("Opening Range +", "Opening Range", "Opening Range Plus",
                "Opening Range -", "Opening Range Minus",
                "Opening Range AM +", "Opening Range AM Plus",
                "Opening Range AM -", "Opening Range AM Minus"):
        n_mins = int(orb_minutes) if orb_minutes else 30
        timestamps = pd.to_datetime(df["timestamp"])
        
        result = pd.Series(np.nan, index=close.index)
        is_am = "AM" in name
        is_minus = name.endswith("-") or name.endswith("Minus")
        
        dates = timestamps.dt.normalize()
        minutes_of_day = timestamps.dt.hour * 60 + timestamps.dt.minute
        
        for date, group_indices in df.groupby(dates).groups.items():
            group_minutes = minutes_of_day.loc[group_indices]
            
            if is_am:
                session_start = 960
                session_end = 1440
            else:
                session_start = 570
                session_end = 960
                
            session_mask = (group_minutes >= session_start) & (group_minutes < session_end)
            if not session_mask.any():
                continue
                
            orb_mask = session_mask & (group_minutes < session_start + n_mins)
            if not orb_mask.any():
                continue
                
            orb_indices = group_minutes[orb_mask].index
            
            if is_minus:
                range_val = low.loc[orb_indices].min()
            else:
                range_val = high.loc[orb_indices].max()
                
            trading_mask = session_mask & (group_minutes >= session_start + n_mins)
            trading_indices = group_minutes[trading_mask].index
            
            result.loc[trading_indices] = float(range_val)
            
        return result


    if name == "Yesterday Volume":
        yesterday_volume = ds.get("eod_volume", np.nan)
        return pd.Series(float(yesterday_volume), index=close.index)

    if name == "Candle Range %":
        candle_range = ((close - open_) / open_.abs()) * 100
        return candle_range.abs()

    if name == "Recorrido (%)":
        # Lo MISMO que `Candle Range %` pero SIN el `abs()`: el signo se
        # conserva, que es el punto entero del indicador. Positivo = la vela
        # subio; negativo = bajo. Mide apertura -> cierre (lo que se mueve la
        # vela), no las mechas.
        return ((close - open_) / open_.abs()) * 100

    if name in ("Elapsed Time from Last High", "Elapsed time from last High"):
        # session_ref — ancla del reloj:
        #   "full" (default): máximo acumulado del día completo (comportamiento
        #                     histórico, mezcla PM+RTH).
        #   "pm":  máximo del premercado (04:00-09:30). El reloj se resetea con
        #          cada nuevo PMH; tras las 09:30 el PMH queda congelado y el
        #          reloj sigue creciendo desde la última actualización.
        #   "rth": máximo de la sesión regular (09:30-16:00). Antes de las 09:30
        #          el indicador NO existe (NaN → la condición nunca dispara);
        #          se resetea con cada nuevo máximo RTH.
        ref = (session_ref or "full").strip().lower()
        n = len(high)
        high_vals = np.asarray(high, dtype=np.float64)
        if ref in ("pm", "rth") and df is not None and "timestamp" in df and n:
            timestamps = pd.to_datetime(df["timestamp"])
            minutes = timestamps.dt.hour.values * 60 + timestamps.dt.minute.values
            if ref == "pm":
                sess_mask = (minutes >= 240) & (minutes < 570)
            else:
                sess_mask = (minutes >= 570) & (minutes < 960)
            elapsed = np.full(n, np.nan)
            sess_idx = np.flatnonzero(sess_mask)
            if len(sess_idx):
                hv = high_vals[sess_idx]
                # Nueva actualización del máximo: high estrictamente mayor que
                # el acumulado (igual que el modo full: máximos iguales no resetean).
                run_max = np.maximum.accumulate(hv)
                is_new = np.concatenate(([True], hv[1:] > run_max[:-1]))
                pos_last_new = np.maximum.accumulate(
                    np.where(is_new, np.arange(len(sess_idx)), -1)
                )
                # Barras (de sesión) desde la última actualización
                elapsed[sess_idx] = np.arange(len(sess_idx)) - pos_last_new
                # Tras terminar la sesión de referencia el máximo queda congelado:
                # el reloj sigue contando desde la barra que lo fijó.
                last_new_global = sess_idx[pos_last_new]
                after = np.flatnonzero(~sess_mask & (np.arange(n) > sess_idx[-1]))
                if len(after):
                    elapsed[after] = after - last_new_global[-1]
            return pd.Series(elapsed, index=close.index)

        # Modo "full" — comportamiento original: máximo acumulado del día.
        elapsed = pd.Series(0, index=close.index, dtype=float)
        last_high_idx = 0
        current_high = high.iloc[0] if len(high) > 0 else 0
        for i in range(len(high)):
            if high.iloc[i] > current_high:
                current_high = high.iloc[i]
                last_high_idx = i
            elapsed.iloc[i] = i - last_high_idx
        return elapsed

    if name in ("Triangle Ascending", "Triangle Descending", "Triangle Symmetric"):
        pw = pivot_window or 5
        lb = tri_lookback or 35
        st = slope_tolerance or 1.5
        mr = min_r_squared or 0.65
        mp = min_pivots or 2
        
        pattern_code = 1
        if name == "Triangle Descending":
            pattern_code = 2
        elif name == "Triangle Symmetric":
            pattern_code = 3
            
        vals = _detect_triangles_numba(
            high.values.astype(np.float64),
            low.values.astype(np.float64),
            close.values.astype(np.float64),
            pw,
            lb,
            st,
            mr,
            mp,
            pattern_code
        )
        return pd.Series(vals, index=close.index)

    return pd.Series(np.nan, index=close.index)


def detect_candle_pattern(
    df: pd.DataFrame,
    pattern: str,
    lookback: int = 0,
    consecutive_count: int = 1,
) -> pd.Series:
    close = df["close"].values
    open_ = df["open"].values
    high = df["high"].values
    low = df["low"].values
    volume = df["volume"].values
    idx = df.index

    if pattern == "GREEN_VOLUME":
        sig = close > open_
    elif pattern == "GREEN_VOLUME_PLUS":
        vol_up = np.empty(len(volume), dtype=np.bool_)
        vol_up[0] = False
        vol_up[1:] = volume[1:] > volume[:-1]
        sig = (close > open_) & vol_up
    elif pattern == "RED_VOLUME":
        sig = close < open_
    elif pattern == "RED_VOLUME_PLUS":
        vol_up = np.empty(len(volume), dtype=np.bool_)
        vol_up[0] = False
        vol_up[1:] = volume[1:] > volume[:-1]
        sig = (close < open_) & vol_up
    elif pattern == "DOJI":
        body = np.abs(close - open_)
        full_range = high - low + 1e-10
        sig = (body / full_range) < 0.1
    elif pattern == "HAMMER":
        sig = _hammer(open_, high, low, close)
    elif pattern == "SHOOTING_STAR":
        sig = _shooting_star(open_, high, low, close)
    else:
        return pd.Series(False, index=idx)

    signal = pd.Series(sig, index=idx)

    if lookback > 0:
        signal = signal.shift(lookback).fillna(False).astype(bool)

    if consecutive_count > 1:
        rolling_sum = signal.astype(int).rolling(window=consecutive_count, min_periods=consecutive_count).sum()
        signal = rolling_sum >= consecutive_count

    return signal.astype(bool)
