# Logic Validation Document

**Purpose**: This document explains the LOGIC behind each test category - which columns are used, what comparisons are made, and what SQL queries are executed. This is for validating the correctness of the LOGIC, not specific test results.

---

## Market Analysis: Basic Filters

### Test: Filtro de Premarket Volume

**Columna Afectada**: `pm_volume` (Premarket Volume en número de acciones)

**Comparadores**: `>=` (mayor o igual)

**Query SQL**:
```sql
SELECT * FROM daily_metrics 
WHERE pm_volume >= ?
```

**Lógica de Aplicación**:
1. Usuario define `min_pm_volume = 500000`
2. Backend construye query con `WHERE pm_volume >= 500000`
3. DuckDB ejecuta comparación numérica
4. Solo retorna filas donde el volumen premarket es 500K o más

**Validación del Test**:
- Ejecutar query con valor conocido
- Verificar que TODOS los resultados cumplen `pm_volume >= valor`

---

### Test: Filtro de Gap at Open Percentage

**Columnas Afectadas**: `gap_at_open_pct`

**Comparadores**: `>=` (min), `<=` (max)

**Queries SQL**:
```sql
-- Minimum gap
SELECT * FROM daily_metrics WHERE gap_at_open_pct >= ?

-- Maximum gap
SELECT * FROM daily_metrics WHERE gap_at_open_pct <= ?
```

**Lógica de Aplicación**:
1. Usuario define rango: `min_gap = 5.0`, `max_gap = 10.0`
2. Backend construye: `WHERE gap_at_open_pct >= 5.0 AND gap_at_open_pct <= 10.0`
3. Solo retorna días con gap entre 5% y 10%

---

### Test: Filtros de RTH Run

**Columna Afectada**: `rth_run_pct` (RTH run desde open hasta high/low en %)

**Comparadores**: `>=` (min), `<=` (max)

**Queries SQL**:
```sql
SELECT * FROM daily_metrics WHERE rth_run_pct >= ?
SELECT * FROM daily_metrics WHERE rth_run_pct <= ?
```

**Lógica**: Filtrar días por el porcentaje de movimiento intradiario (RTH run).

---

### Test: Filtros de Time of Day (HOD/LOD)

**Columnas Afectadas**: `hod_time`, `lod_time`

**Comparadores**: `>=` (after), `<=` (before)

**Queries SQL**:
```sql
-- HOD after 10:00
SELECT * FROM daily_metrics WHERE hod_time >= '10:00'

-- LOD before 14:00
SELECT * FROM daily_metrics WHERE lod_time <= '14:00'
```

**Lógica**: Filtrar por la hora en que ocurrió el high/low del día.

---

### Test: Filtros Booleanos

**Columnas Afectadas**: `open_lt_vwap`, `pm_high_break`, `close_lt_m15`, `close_lt_m30`, `close_lt_m60`

**Comparador**: `= true`

**Query SQL Example**:
```sql
SELECT * FROM daily_metrics WHERE open_lt_vwap = true
```

**Lógica**: Filtrar días donde condición booleana es TRUE (ej: apertura bajo VWAP).

---

## Market Analysis: Advanced Filters (Dynamic Rules)

### Test: Comparación Estática con Valor

**Columna**: Cualquier métrica del METRIC_MAP

**Operadores**: `=`, `!=`, `>`, `>=`, `<`, `<=`

**Query SQL Example**:
```sql
SELECT * FROM daily_metrics WHERE rth_run_pct > 10.0
SELECT * FROM daily_metrics WHERE gap_at_open_pct >= 5.0
```

**Lógica**: Comparar columna con valor estático usando operador definido.

---

### Test: Comparación Variable (Columna vs Columna)

**Columnas**: Dos métricas cualesquiera

**Operadores**: `>`, `>=`, `<`, `<=`, `=`, `!=`

**Query SQL Example**:
```sql
-- RTH close < RTH open (red candle)
SELECT * FROM daily_metrics WHERE rth_close < rth_open

-- PM volume > RTH volume
SELECT * FROM daily_metrics WHERE pm_volume > rth_volume
```

**Lógica**: Comparar valores de dos columnas entre sí.

---

### Test: Lógica Combinada AND

**Query SQL Example**:
```sql
SELECT * FROM daily_metrics 
WHERE gap_at_open_pct >= 5.0
AND rth_volume >= 1000000
AND rth_run_pct >= 10.0
```

**Lógica**: TODAS las condiciones deben cumplirse. Si una falla, la fila se excluye.

---

### Test: Lógica Combinada OR

**Query SQL Example**:
```sql
SELECT * FROM daily_metrics 
WHERE gap_at_open_pct >= 20.0
OR rth_run_pct >= 50.0
```

**Lógica**: AL MENOS una condición debe cumplirse. Si alguna es TRUE, la fila se incluye.

---

## Market Analysis: Statistical Calculations

### Test: Promedio de Gap

**Función**: `AVG(gap_at_open_pct)`

**Query SQL**:
```sql
SELECT AVG(gap_at_open_pct) as avg_gap FROM daily_metrics
```

**Lógica**: Calcula el promedio aritmético de todos los gaps. `SUM(gap_at_open_pct) / COUNT(*)`

**Validación**: Comparar resultado SQL con cálculo Python `df["gap_at_open_pct"].mean()`

---

### Test: Conversión Booleano a Porcentaje

**Función**: `AVG(CAST(open_lt_vwap AS INT)) * 100`

**Query SQL**:
```sql
SELECT AVG(CAST(open_lt_vwap AS INT)) * 100 as pct 
FROM daily_metrics
```

**Lógica**:
1. `CAST(open_lt_vwap AS INT)` convierte TRUE=1, FALSE=0
2. `AVG(...)` calcula promedio (ej: 0.65 si 65% son TRUE)
3. `* 100` convierte a porcentaje (65.0)

**Validación**: Comparar con `df["open_lt_vwap"].astype(int).mean() * 100`

---

### Test: Distribución de HOD Time

**Función**: `GROUP BY hod_time` con `COUNT(*)`

**Query SQL**:
```sql
SELECT hod_time, COUNT(*) as count
FROM daily_metrics
GROUP BY hod_time
ORDER BY count DESC
```

**Lógica**: Agrupa filas por hora del high del día, cuenta cuántas veces ocurrió cada hora.

**Validación**: Comparar con `df["hod_time"].value_counts()`

---

### Test: Cálculos Agregados Intraday

**Función**: `AVG((close - rth_open) / rth_open * 100)` con JOIN

**Query SQL**:
```sql
SELECT AVG((h.close - d.rth_open) / d.rth_open * 100) as avg_change
FROM historical_data h
JOIN daily_metrics d 
  ON h.ticker = d.ticker 
  AND CAST(h.timestamp AS DATE) = d.date
```

**Lógica**: 
1. JOIN entre datos intraday y daily metrics
2. Para cada barra intraday, calcula % de cambio desde RTH open
3. Promedia todos los cambios

---

## Backtester: Entry Signal Generation

### Test: Señal Basada en Precio

**Condición**: `close > 100`

**Lógica**:
1. Engine evalúa condición para cada row del DataFrame
2. Genera Series booleana: `df["close"] > 100`
3. Solo genera señal de entrada donde TRUE

**Validación**: Verificar que señales solo ocurren cuando `close > valor`

---

### Test: Señal Basada en VWAP

**Condición**: `close < vwap`

**Lógica**:
1. Compara precio de cierre con VWAP en cada barra
2. Señal TRUE cuando `df["close"] < df["vwap"]`

**Validación**: Confirmar que NO hay señales cuando `close >= vwap`

---

### Test: Múltiples Condiciones AND

**Condiciones**: 
- `close > 100`
- `time >= "10:00"`
- `extension > 2%`

**Lógica**:
```python
signal = (df["close"] > 100) & (df["time"] >= "10:00") & (df["extension"] > 2)
```
TODAS deben ser TRUE para generar señal.

---

## Backtester: Stop Loss Calculations

### Test: SL Percent para Short

**Tipo**: `PERCENT`

**Fórmula**: `SL = entry * (1 + percent/100)`

**Ejemplo**:
- Entry: $100
- SL Percent: 5%
- Cálculo: `100 * (1 + 5/100) = 100 * 1.05 = $105`

**Validación**: Confirmar que SL = $105 cuando entry=$100 y sl_pct=5%

---

### Test: SL Fixed para Short

**Tipo**: `FIXED`

**Fórmula**: `SL = entry + fixed_value`

**Ejemplo**:
- Entry: $100
- SL Fixed: $2.50
- Cálculo: `100 + 2.50 = $102.50`

---

### Test: SL ATR para Short

**Tipo**: `ATR`

**Fórmula**: `SL = entry + (atr * multiplier)`

**Ejemplo**:
- Entry: $100
- ATR: $1.50
- Multiplier: 2.0
- Cálculo: `100 + (1.50 * 2.0) = $103`

---

## Backtester: Take Profit Calculations

### Test: TP Percent para Short

**Tipo**: `PERCENT`

**Fórmula**: `TP = entry * (1 - percent/100)`

**Ejemplo**:
- Entry: $100
- TP Percent: 5%
- Cálculo: `100 * (1 - 5/100) = 100 * 0.95 = $95`

---

### Test: TP Structure para Short

**Tipo**: `STRUCTURE`

**Fórmula**: `TP = vwap` (o cualquier nivel estructural definido)

**Lógica**: TP se fija en un nivel de precio estructural (VWAP, PM Low, etc.)

---

## Backtester: R-Multiple Calculation

**Fórmula**: `R = (entry - exit) / (entry - stop_loss)`

**Para Short**:
- Entry: $100
- Exit: $97.50
- Stop Loss: $105
- Risk: `100 - 105 = -5` → `abs(-5) = 5`
- Profit: `100 - 97.50 = 2.50`
- R-Multiple: `2.50 / 5 = 0.5R`

**Validación**:
- Winning trade: R > 0
- Losing trade: R < 0
- Breakeven: R ≈ 0

---

## Backtester: Position Sizing

**Fórmula**: `position_size = allocated_capital / risk_per_share`

**Ejemplo**:
- Allocated Capital: $10,000
- Entry: $100
- Stop Loss: $105
- Risk per Share: `105 - 100 = $5`
- Position Size: `10000 / 5 = 2000 shares`

**Validación**: Confirmar que el riesgo total = allocated capital (si SL golpea, pierdes 2000 shares * $5/share = $10,000)

---

## Backtester: Portfolio Metrics

### Test: Win Rate

**Fórmula**: `win_rate = (winning_trades / total_trades) * 100`

**Ejemplo**:
- Total Trades: 10
- Winning Trades: 6
- Win Rate: `(6 / 10) * 100 = 60%`

**Validación**: Verificar que trades con R > 0 se cuentan como winners

---

### Test: Profit Factor

**Fórmula**: `profit_factor = gross_wins / gross_losses`

**Ejemplo**:
- R-Multiples: [1.0, 0.5, -1.0, -0.5, 0.8]
- Gross Wins: `1.0 + 0.5 + 0.8 = 2.3`
- Gross Losses: `1.0 + 0.5 = 1.5`
- Profit Factor: `2.3 / 1.5 = 1.53`

---

### Test: Max Drawdown %

**Fórmula**: `max_dd = max((peak - balance) / peak * 100)`

**Lógica**:
1. Track running peak balance
2. Para cada punto, calcula drawdown desde peak
3. Retorna el máximo drawdown %

---

### Test: Sharpe Ratio

**Fórmula** (simplificada): `sharpe = mean(R) / std_dev(R)`

**Lógica**: Mide retorno ajustado por riesgo. Mayor Sharpe = mejor consistencia.

---

## Backtester: SQL Queries

### Test: Reconstrucción de Query Guardada

**Lógica**: Cuando se guarda una estrategia, los filtros se serializan. Al ejecutar backtest, se reconstruyen.

**Ejemplo**:
```json
{"min_gap_pct": 5.0, "min_rth_volume": 1000000}
```

**Reconstrucción**:
```sql
SELECT * FROM daily_metrics 
WHERE gap_at_open_pct >= 5.0 
AND rth_volume >= 1000000
```

---

### Test: JOIN entre Daily y Historical

**Query**:
```sql
SELECT d.*, h.*
FROM daily_metrics d
JOIN historical_data h 
  ON d.ticker = h.ticker 
  AND CAST(d.date AS TIMESTAMP) <= h.timestamp
  AND h.timestamp < CAST(d.date AS TIMESTAMP) + INTERVAL 1 DAY
```

**Lógica**:
1. Une daily metrics (un row por día) con historical data (390+ rows/día)
2. Asegura que timestamps de historical caen dentro del día correcto
3. Permite acceder a datos intraday filtrados por condiciones diarias

---

### Test: Date Filtering

**Query**:
```sql
SELECT * FROM historical_data
WHERE timestamp >= CAST('2024-01-01' AS TIMESTAMP)
AND timestamp <= CAST('2024-12-31' AS TIMESTAMP)
```

**Lógica**: Limita datos a un rango de fechas específico para optimizar performance.

---

## Resumen de Cobertura

- **Filtros Básicos**: 30+ tests (numeric, time, boolean, date)
- **Filtros Avanzados**: 15+ tests (all operators, variable comparisons, logic combinations)
- **Cálculos Estadísticos**: 25+ tests (averages, percentages, distributions)
- **Backtester Engine**: 20+ tests (signals, SL/TP, R-multiples, metrics)
- **SQL Queries**: 15+ tests (joins, reconstruction, filtering)

**Total**: ~100+ test cases cubriendo toda la lógica de negocio
