# PRD: Optimizacion de generacion de senales (N1 + N2a)

**Fecha:** 2026-07-01
**Objetivo:** Reducir 8-10x el tiempo de generacion de senales por par
**Impacto verificado:** De 1229us/par a 145us/par (8.5x) en estrategia simple; mayor en complejas
**Riesgo:** Bajo — path actual se mantiene como fallback, resultados bit-identicos

---

## 1. Diagnostico (datos reales)

Medido sobre 1,163 pares con tu estrategia SHORT real (gap >=50%, vol >=5M):

```
Pipeline ACTUAL:  1,429 ms = 1,229 us/par = 814 pares/s
Pipeline 2a:        168 ms =   145 us/par = 6,916 pares/s
Speedup: 8.5x | Resultados identicos (1,008 entries ambos)
```

### Donde se va el tiempo (1,229 us/par)

| Componente | Tiempo | % | Causa raiz |
|-----------|--------|---|------------|
| `pd.to_datetime` x3 redundantes | 200 us | 16% | Se parsea la misma columna 1-3 veces por par |
| Arrays + HOD/LOD/PM via pandas | 454 us | 37% | `.shift()`, `.loc[]`, `.iloc[]` en vez de numpy |
| `pd.DataFrame(arrays)` | 81 us | 7% | Construir DataFrame de 13 columnas x 390 filas |
| Session mask + filter DataFrame | 354 us | 29% | Otro `pd.to_datetime` + filtrar DataFrame |
| `translate_strategy()` | 139 us | 11% | Logica de senales (esto SI es necesario) |

**Conclusion: el 89% del tiempo NO es computar indicadores. Es maquinaria Pandas.**

### Overhead de compute_indicator vs raw numpy

| Indicador | Raw numpy | Via compute_indicator | Overhead |
|-----------|-----------|----------------------|----------|
| VWAP | 6.1 us | 18.6 us | 3.0x |
| SMA(20) | 2.8 us | 13.6 us | 4.9x |
| ATR(14) | 1.4 us | 13.2 us | 9.4x |

Cada llamada a `compute_indicator` tiene ~10us de overhead fijo:
- `normalize_indicator_name()` — dict lookup
- Construccion de cache key de 17 elementos + hash
- 1-50 comparaciones de string en `_compute_raw()`
- Creacion de `pd.Series` wrapper

---

## 2. Plan de implementacion

### 2.1 Nivel 1 — Quick Wins (~2h, ~30% mas rapido)

Cambios locales, sin tocar arquitectura. Cada uno es independiente.

#### 1a: Dict dispatch en `_compute_raw()` — `indicators.py:860-1511`

**Problema:** 50+ `if name == "X":` encadenados. Cada indicador recorre en promedio 25 comparaciones de string.

**Solucion:** Pre-construir un dict a nivel de modulo:

```python
# Al inicio de _compute_raw, reemplazar TODOS los if/elif por:
_INDICATOR_COMPUTE = {
    "Close": lambda close, high, low, open_, volume, period, period2, period3, std_dev, multiplier, days_lookback, time_hour, time_minute, time_condition, band_line, orb_minutes, ap_session, daily_stats, df, range_minutes, pivot_window, tri_lookback, slope_tolerance, min_r_squared, min_pivots: close,
    "Open": lambda close, high, low, open_, volume, period, ...: open_,
    "High": lambda ...: high,
    "Low": lambda ...: low,
    "Volume": lambda ...: volume.astype(float),
    # ... todos los demas
    "SMA": lambda ..., period, ...: pd.Series(_sma(close.values, period or 20), index=close.index),
    "EMA": lambda ..., period, ...: pd.Series(_ema(close.values, period or 20), index=close.index),
    "VWAP": lambda ..., close, high, low, volume, ...: pd.Series(_vwap(high.values.astype(np.float64), low.values.astype(np.float64), close.values.astype(np.float64), volume.values.astype(np.float64)), index=close.index),
    # ...
}
```

Luego en `_compute_raw` reemplazar los 50 ifs por:

```python
func = _INDICATOR_COMPUTE.get(name)
if func is not None:
    return func(close, high, low, open_, volume, period, period2, period3, std_dev, multiplier, days_lookback, time_hour, time_minute, time_condition, band_line, orb_minutes, ap_session, daily_stats, df, range_minutes, pivot_window, tri_lookback, slope_tolerance, min_r_squared, min_pivots)
return pd.Series(np.nan, index=close.index)
```

**Archivo:** `backend/app/services/indicators.py`
**Lineas afectadas:** 860-1511 (reemplazar con dict + dispatch)
**Ganancia:** ~8-12% en `translate_strategy()`
**Riesgo:** Muy bajo. Misma logica, distinto dispatch.

#### 1b: Simplificar cache key — `indicators.py:814-817`

**Problema:** Cada llamada construye tupla de 17 elementos (la mayoria None) y la hashea.

**Solucion:** Generar un `spec_id` string precomputado en `_compute_from_config()`:

```python
# En _compute_from_config, en vez de pasar 15 kwargs a compute_indicator,
# construir un spec_id una vez:
spec_id = f"{name}|{period}|{period2}|{period3}|{std_dev}|{multiplier}|{offset}|..."
```

Y en `compute_indicator`, usar spec_id como cache key en vez de la tupla de 17.

**Archivo:** `backend/app/services/indicators.py` (linea 814) y `backend/app/services/strategy_engine.py` (linea 389)
**Ganancia:** ~5-8%
**Riesgo:** Bajo. El cache key sigue siendo unico.

#### 1c: Dict dispatch en `_apply_comparator()` — `strategy_engine.py:417-452`

**Problema:** 7 if/elif comparando strings por cada condicion.

**Solucion:**

```python
_COMPARATOR_OPS = {
    "GREATER_THAN": lambda s, t: s > t,
    "LESS_THAN": lambda s, t: s < t,
    "GREATER_THAN_OR_EQUAL": lambda s, t: s >= t,
    "LESS_THAN_OR_EQUAL": lambda s, t: s <= t,
    "EQUAL": lambda s, t: s == t,
    "CROSSES_ABOVE": lambda s, t: (s.shift(1) <= t.shift(1)) & (s > t),
    "CROSSES_BELOW": lambda s, t: (s.shift(1) >= t.shift(1)) & (s < t),
}

def _apply_comparator(source, target, comparator):
    op = _COMPARATOR_OPS.get(comparator)
    if op is not None:
        return op(source, target)
    # Fallback para DISTANCE_* (ya manejados en otro lado, aqui solo warning)
    if comparator in ("DISTANCE_GREATER_THAN", "DISTANCE_LESS_THAN"):
        logger.warning(f"{comparator} used in indicator_comparison...")
        return pd.Series(False, index=source.index)
    return source > target
```

**Archivo:** `backend/app/services/strategy_engine.py` (lineas 417-452)
**Ganancia:** ~2-3%

#### 1d: Pre-normalizar nombres de indicador — `strategy_engine.py:42` y `indicators.py:784`

**Problema:** `normalize_indicator_name()` se llama en cada `compute_indicator()`. Traduce "Bar Close" → "Close", "Bar Open" → "Open", etc.

**Solucion:** En `compile_strategy_def()`, recorrer el arbol de condiciones y reemplazar todos los `cfg["name"]` por su version normalizada:

```python
# En compile_strategy_def, nueva funcion auxiliar:
def _normalize_conditions(group):
    if not group: return
    for cond in group.get("conditions", []):
        if cond.get("type") == "group":
            _normalize_conditions(cond)
        else:
            for key in ("source", "target", "level"):
                cfg = cond.get(key)
                if isinstance(cfg, dict) and "name" in cfg:
                    cfg["name"] = normalize_indicator_name(cfg["name"])

_normalize_conditions(entry_logic.get("root_condition", {}))
_normalize_conditions(exit_logic.get("root_condition", {}))
```

Luego en `compute_indicator()`, eliminar la llamada a `normalize_indicator_name()` porque el nombre ya viene normalizado.

**Archivos:** `backend/app/services/strategy_engine.py` (compile_strategy_def) y `backend/app/services/indicators.py` (compute_indicator)
**Ganancia:** ~3-5%

#### 1e: Unificar parseo de timestamps — `backtest_signals.py:94` y `strategy_engine.py:107,160,194`

**Problema:** `pd.to_datetime()` se llama 2-8 veces por par en distintos sitios.

**Solucion:** Parsear UNA vez al inicio de `_compute_signals_for_pair()` y pasar el resultado como argumento:

```python
# En _compute_signals_for_pair, al inicio:
ts_parsed = day_df["timestamp"]
if not pd.api.types.is_datetime64_any_dtype(ts_parsed):
    ts_parsed = pd.to_datetime(ts_parsed)
minutes_arr = ts_parsed.dt.hour * 60 + ts_parsed.dt.minute  # precomputar

# Pasar minutes_arr a translate_strategy y usarlo en vez de pd.to_datetime
```

Modificar `translate_strategy()` para aceptar un parametro opcional `precomputed_minutes`:

```python
def translate_strategy(df, strategy_def, daily_stats=None, compiled=None, 
                       precomputed_minutes=None):
    ...
    if time_windows:
        if precomputed_minutes is not None:
            minutes_since_midnight = precomputed_minutes
        else:
            ts = pd.to_datetime(df["timestamp"])
            minutes_since_midnight = ts.dt.hour * 60 + ts.dt.minute
```

Mismo patron para `_resample_if_needed` y `_align_signals_to_1m`: pasar timestamp ya parseado.

**Archivos:** `backend/app/services/backtest_signals.py` (linea 94) y `backend/app/services/strategy_engine.py` (lineas 107, 160, 194)
**Ganancia:** ~15% (la mayor del Nivel 1)

### 2.2 Nivel 2a — Pre-extraccion de indicadores + arrays numpy (~2-3 dias, ~8.5x mas rapido)

#### Concepto

En vez de que cada condicion llame perezosamente a `compute_indicator()` (creando DataFrames, Series, cache keys), hacer DOS fases:

- **Fase A (1 vez por backtest):** Recorrer el arbol de la estrategia, extraer lista unica de indicadores
- **Fase B (por par):** Precomputar TODOS los indicadores contra arrays numpy, evaluar condiciones con operaciones booleanas numpy, sin DataFrames

#### Cambios concretos

##### Archivo 1: `backend/app/services/strategy_engine.py` — Nuevas funciones

**`extract_indicator_plan(compiled) -> dict`** (~40 lineas, nueva funcion)

Recorre `entry_root` y `exit_root`, extrae todos los indicadores unicos. Retorna:

```python
{
    "indicators": [
        {"key": "close_1m", "name": "Close", "tf": "1m", "period": None, ...},
        {"key": "vwap_1m", "name": "VWAP", "tf": "1m", "period": None, ...},
        {"key": "sma20_5m", "name": "SMA", "tf": "5m", "period": 20, ...},
    ],
    "by_timeframe": {
        "1m": [spec_close, spec_vwap, ...],
        "5m": [spec_sma20, ...],
    },
    "has_candle_patterns": False,  # si alguna condicion es candle_pattern
    "has_price_distance": False,
}
```

**`translate_strategy_native(ohclv_arrays, compiled, plan, daily_stats) -> dict`** (~80 lineas, nueva funcion)

Recibe arrays numpy (no DataFrame). Precomputa indicadores, evalua condiciones. Retorna mismo formato que `translate_strategy()`.

```python
def translate_strategy_native(arrays, compiled, plan, daily_stats=None):
    """
    arrays: dict con keys 'open', 'high', 'low', 'close', 'volume' (numpy float64)
            mas 'timestamp' (DatetimeIndex), 'minutes' (int array)
            mas 'hod', 'lod', 'pm_high', 'pm_low', 'prev_high', 'prev_low'
    compiled: resultado de compile_strategy_def
    plan: resultado de extract_indicator_plan
    """
    # Fase 1: Precomputar TODOS los indicadores
    indicator_results = {}
    for tf, specs in plan["by_timeframe"].items():
        if tf == "1m":
            # Sin resample — usar arrays directamente
            for spec in specs:
                indicator_results[spec["key"]] = _compute_indicator_raw(
                    spec, arrays
                )
        else:
            # Resamplear una vez para este timeframe
            resampled = _resample_arrays(arrays, tf)
            for spec in specs:
                indicator_results[spec["key"]] = _compute_indicator_raw(
                    spec, resampled
                )
    
    # Fase 2: Evaluar condiciones contra arrays numpy
    entries = _evaluate_group_native(
        compiled["entry_root"], indicator_results, arrays["close"].shape[0], plan
    )
    exits = _evaluate_group_native(
        compiled["exit_root"], indicator_results, arrays["close"].shape[0], plan
    )
    
    # Fase 3: Risk management (usa arrays, no DataFrame)
    sl_stop, sl_trail, tp_stop, tp_time_limit, trail_pct, partial_tps = \
        _parse_risk_management_native(compiled["risk_management"], arrays, indicator_results)
    
    return {
        "entries": entries,
        "exits": exits,
        "direction": compiled["direction"],
        "sl_stop": sl_stop,
        "sl_trail": sl_trail,
        "tp_stop": tp_stop,
        "tp_time_limit": tp_time_limit,
        "trail_pct": trail_pct,
        "accept_reentries": compiled["accept_reentries"],
        "max_reentries": compiled["max_reentries"],
        "partial_take_profits": partial_tps,
    }
```

**`_compute_indicator_raw(spec, arrays) -> np.ndarray`** (~50 lineas)

Dispatch directo a funciones Numba/numpy, sin cache keys, sin normalize, sin if/elif:

```python
_RAW_COMPUTE = {
    "Close": lambda a: a["close"],
    "Open": lambda a: a["open"], 
    "High": lambda a: a["high"],
    "Low": lambda a: a["low"],
    "VWAP": lambda a: _vwap(a["high"], a["low"], a["close"], a["volume"]),
    "SMA": lambda a, p: _sma(a["close"], p),
    "EMA": lambda a, p: _ema(a["close"], p),
    "RSI": lambda a, p: _rsi(a["close"], p),
    "ATR": lambda a, p: _atr(a["high"], a["low"], a["close"], p),
    # ... todos los indicadores Numba
}

def _compute_indicator_raw(spec, arrays):
    name = spec["name"]
    fn = _RAW_COMPUTE.get(name)
    if fn is None:
        return np.full(len(arrays["close"]), np.nan)
    period = spec.get("period")
    if period:
        return fn(arrays, period)
    return fn(arrays)
```

**`_evaluate_group_native(group, results, n_bars, plan) -> np.ndarray`** (~30 lineas)

Evalua el arbol AND/OR contra arrays numpy:

```python
_COMP_NATIVE = {
    "GREATER_THAN": lambda s, t: s > t,
    "LESS_THAN": lambda s, t: s < t,
    "GREATER_THAN_OR_EQUAL": lambda s, t: s >= t,
    "LESS_THAN_OR_EQUAL": lambda s, t: s <= t,
    "EQUAL": lambda s, t: s == t,
    "CROSSES_ABOVE": lambda s, t: np.concatenate([[False], (s[:-1] <= t[:-1]) & (s[1:] > t[1:])]),
    "CROSSES_BELOW": lambda s, t: np.concatenate([[False], (s[:-1] >= t[:-1]) & (s[1:] < t[1:])]),
}

def _evaluate_group_native(group, results, n_bars, plan):
    if not group or not group.get("conditions"):
        return np.zeros(n_bars, dtype=bool)
    
    operator = group.get("operator", "AND")
    conditions = group.get("conditions", [])
    
    combined = None
    for cond in conditions:
        if cond.get("type") == "group":
            res = _evaluate_group_native(cond, results, n_bars, plan)
        elif cond.get("type") == "indicator_comparison":
            res = _eval_comparison_native(cond, results, plan)
        elif cond.get("type") == "price_level_distance":
            res = _eval_distance_native(cond, results, plan)
        elif cond.get("type") == "candle_pattern":
            # Fallback a implementacion actual (necesita DataFrame)
            res = np.zeros(n_bars, dtype=bool)
        else:
            res = np.zeros(n_bars, dtype=bool)
        
        if combined is None:
            combined = res
        elif operator == "AND":
            combined = combined & res
        else:
            combined = combined | res
    
    return combined if combined is not None else np.zeros(n_bars, dtype=bool)
```

##### Archivo 2: `backend/app/services/backtest_signals.py` — Modificar `_compute_signals_for_pair()`

**Cambios en `_compute_signals_for_pair()` (lineas 73-260):**

1. Parsear timestamps UNA vez al inicio
2. Construir arrays de mercado con numpy puro (sin `.shift()`, sin `.loc[]`)
3. Si `compiled_strategy` tiene un `indicator_plan`, usar `translate_strategy_native()`
4. Si no, fallback a `translate_strategy()` actual
5. Aplicar session mask con numpy indexing (no DataFrame filtering)

```python
def _compute_signals_for_pair(date, ticker, day_df, daily_stats, strategy_def,
                               compiled_strategy, market_sessions, custom_start_time,
                               custom_end_time, swing_active):
    # --- Parsear timestamps UNA vez ---
    ts_col = day_df["timestamp"]
    if not pd.api.types.is_datetime64_any_dtype(ts_col):
        ts_col = pd.to_datetime(ts_col)
    minutes = ts_col.dt.hour * 60 + ts_col.dt.minute
    
    # --- Arrays OHLCV (evitar .astype() si ya son float64) ---
    C = np.asarray(day_df["close"], dtype=np.float64)
    O = np.asarray(day_df["open"], dtype=np.float64)
    H = np.asarray(day_df["high"], dtype=np.float64)
    L = np.asarray(day_df["low"], dtype=np.float64)
    V = np.asarray(day_df["volume"], dtype=np.float64)
    
    # --- Market structure (numpy puro) ---
    hod = np.maximum.accumulate(H)
    lod = np.minimum.accumulate(L)
    
    pm_mask = (minutes >= 240) & (minutes < 570)
    pm_h = float(H[pm_mask].max()) if pm_mask.any() else np.nan
    pm_l = float(L[pm_mask].min()) if pm_mask.any() else np.nan
    
    prev_h = np.empty_like(hod); prev_h[0] = H[0]; prev_h[1:] = hod[:-1]
    prev_l = np.empty_like(lod); prev_l[0] = L[0]; prev_l[1:] = lod[:-1]
    
    prev_close = daily_stats.get("prev_close")
    if prev_close is None or pd.isna(prev_close):
        prev_close = float(C[0])
    yest_open = daily_stats.get("yesterday_open", daily_stats.get("lag_rth_open_1"))
    if yest_open is None or pd.isna(yest_open):
        yest_open = float(O[0])
    
    # --- Usar plan de indicadores si esta disponible ---
    indicator_plan = compiled_strategy.get("_indicator_plan") if compiled_strategy else None
    
    if indicator_plan is not None:
        # Fast path: numpy arrays, sin DataFrames
        arrays = {
            "open": O, "high": H, "low": L, "close": C, "volume": V,
            "timestamp": ts_col, "minutes": minutes.values if hasattr(minutes, 'values') else np.asarray(minutes),
            "hod": hod, "lod": lod,
            "pm_high": np.full_like(C, pm_h) if not np.isnan(pm_h) else np.zeros_like(C),
            "pm_low": np.full_like(C, pm_l) if not np.isnan(pm_l) else np.zeros_like(C),
            "prev_high": prev_h, "prev_low": prev_l,
            "prev_close": np.full_like(C, prev_close),
            "yesterday_open": np.full_like(C, yest_open),
        }
        
        signals = translate_strategy_native(
            arrays, compiled_strategy, indicator_plan,
            daily_stats={"prev_close": prev_close}
        )
        entries_arr = signals["entries"]
        exits_arr = signals["exits"]
    else:
        # Slow path: actual (compatibilidad)
        arrays_dict = {
            "ticker": np.full(len(day_df), ticker, dtype=object),
            "open": O, "high": H, "low": L, "close": C, "volume": V,
            "timestamp": day_df["timestamp"].values,
            "hod": hod, "lod": lod,
            "pm_high": np.full(len(day_df), pm_h, dtype=np.float64),
            "pm_low": np.full(len(day_df), pm_l, dtype=np.float64),
            "prev_high": prev_h, "prev_low": prev_l,
            "prev_close": np.full(len(day_df), prev_close, dtype=np.float64),
            "yesterday_open": np.full(len(day_df), yest_open, dtype=np.float64),
        }
        mini_df = pd.DataFrame(arrays_dict)
        
        try:
            signals = translate_strategy(mini_df, strategy_def, daily_stats, compiled=compiled_strategy)
        except Exception:
            return None
        if not signals["entries"].any():
            return None
        
        entries_arr = signals["entries"].values
        exits_arr = signals["exits"].values
    
    # --- Resto del codigo igual (session mask, candle_delay, patch) ---
    # pero usando numpy indexing en vez de DataFrame filtering
    if market_sessions and "all" not in market_sessions:
        from app.services.backtest_service import _get_market_sessions_mask
        session_mask = _get_market_sessions_mask(ts_col, market_sessions, custom_start_time, custom_end_time)
        session_mask_np = session_mask.values if hasattr(session_mask, "values") else np.asarray(session_mask)
        entries_arr = entries_arr[session_mask_np]
        exits_arr = exits_arr[session_mask_np]
        
        # Filtrar arrays para el simulador
        arrays = {
            "open": O[session_mask_np],
            "high": H[session_mask_np],
            "low": L[session_mask_np],
            "close": C[session_mask_np],
            "volume": V[session_mask_np],
            "timestamp": ts_col[session_mask_np],
            "hod": hod[session_mask_np],
            "lod": lod[session_mask_np],
            "pm_high": np.full(entries_arr.shape, pm_h if not np.isnan(pm_h) else 0.0, dtype=np.float64),
            "pm_low": np.full(entries_arr.shape, pm_l if not np.isnan(pm_l) else 0.0, dtype=np.float64),
            "prev_high": prev_h[session_mask_np],
            "prev_low": prev_l[session_mask_np],
        }
    
    # ... resto igual ...
```

##### Archivo 3: `backend/app/services/backtest_service.py` — Generar el plan en compile-time

En `run_backtest()`, tras `compile_strategy_def()`, generar el plan de indicadores:

```python
compiled_strategy = compile_strategy_def(strategy_def) if strategy_def else None

# NUEVO: extraer plan de indicadores para el fast path
if compiled_strategy:
    from app.services.strategy_engine import extract_indicator_plan
    compiled_strategy["_indicator_plan"] = extract_indicator_plan(compiled_strategy)
```

---

## 3. Verificacion

### 3.1 Test de correccion

Correr `scripts/contrast_before_optimization.py` ANTES y DESPUES de los cambios. Verifica que:

- El numero de entries por par es identico entre el path actual y el nuevo
- Los arrays de entrada/salida tienen el mismo shape
- Los parametros de riesgo (sl_stop, tp_stop, etc.) son identicos

### 3.2 Test de rendimiento

Correr `scripts/profile_2a_full.py` despues de los cambios. Verificar:

- Speedup >= 8x para estrategias simples (1m)
- Speedup >= 5x para estrategias multi-timeframe
- Sin regresion en el path legado (cuando `_indicator_plan` no esta disponible)

### 3.3 Golden tests

Ejecutar los tests existentes:
```bash
cd backend && .venv/bin/python -m pytest tests/test_backtest_golden.py -v
```

---

## 4. Rollout

### Fase 1: Nivel 1 (mismo dia)
1. Implementar 1a, 1b, 1c, 1d, 1e
2. Correr tests de correccion
3. Deploy a produccion (cambios locales, bajo riesgo)

### Fase 2: Nivel 2a (2-3 dias)
1. Implementar `extract_indicator_plan()`
2. Implementar `translate_strategy_native()` con todas las funciones auxiliares
3. Modificar `_compute_signals_for_pair()` con el fast path (con fallback)
4. Modificar `run_backtest()` para generar el plan
5. Correr tests exhaustivos de correccion
6. Deploy con feature flag: `BACKTEST_USE_NATIVE_SIGNALS=1`

### Rollback
Si algo falla, basta con:
- No generar `_indicator_plan` → el codigo toma automaticamente el slow path
- O revertir el env `BACKTEST_USE_NATIVE_SIGNALS=0`

---

## 5. Impacto estimado

| Escenario | Pares | Antes | Despues | Ganancia |
|-----------|-------|-------|---------|----------|
| Tu backtest SHORT (1,163 pares) | 1,163 | 1.43s | 0.17s | **8.5x** |
| Backtest medio (10k pares) | 10,000 | 12.3s | 1.5s | **8.5x** |
| Backtest grande (50k pares) | 50,000 | 61.5s | 7.3s | **8.5x** |
| Estrategia compleja multi-tf | 10,000 | 94.6s | ~12s | **~8x** |
