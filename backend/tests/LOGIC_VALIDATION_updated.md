# Logic Validation Document (JAUME Architecture - REVISED)

**Purpose**: This document explains the LOGIC behind each metric calculation and filtering process in the new JAUME architecture. Metrics are now calculated **on-the-fly** from raw OHLCV data instead of being stored pre-calculated.

---

## Data Architecture: Raw Tables

The database (MotherDuck - JAUME) stores only raw trading data. No metrics are stored in the database.

### 1. `daily_metrics` Table
| Column | Type | Description |
|--------|------|-------------|
| ticker | VARCHAR | Stock symbol |
| date | DATE | Trading date |
| open | DOUBLE | RTH Open price |
| high | DOUBLE | RTH High price |
| low | DOUBLE | RTH Low price |
| close | DOUBLE | RTH Close price |
| volume | DOUBLE | Total daily volume |
| vwap | DOUBLE | Daily VWAP |

### 2. `intraday_1m` Table
| Column | Type | Description |
|--------|------|-------------|
| ticker | VARCHAR | Stock symbol |
| timestamp | TIMESTAMP| 1-minute interval start |
| open | DOUBLE | Minute Open |
| high | DOUBLE | Minute High |
| low | DOUBLE | Minute Low |
| close | DOUBLE | Minute Close |
| volume | DOUBLE | Minute Volume |
| vwap | DOUBLE | Minute VWAP |

---

## Metric Calculations (On-the-Fly)

These calculations are performed in the backend (`app/calculations.py`) or via specific SQL queries.

### 1. Gap at Open %
**Formula**: `((rth_open - prev_close) / prev_close) * 100`

**Lógica (Python)**:
1. Recupera `open` y `close` de `daily_metrics`.
2. Ordena por ticker y fecha.
3. Obtiene `prev_close` usando `shift(1)` sobre la columna `close`.
4. Calcula el porcentaje.

---

### 2. RTH Run % (Extension to High)
**Formula**: `((rth_high - rth_open) / rth_open) * 100`

**Lógica**: Mide la extensión máxima desde el open hasta el HOD (High of Day).
- **RTH Open**: Primer precio de `daily_metrics` o primera barra de `intraday_1m` a las 09:30.
- **RTH High**: Valor `high` de `daily_metrics`.

---

### 3. Day Return %
**Formula**: `((rth_close - rth_open) / rth_open) * 100`

**Lógica**: Mide el rendimiento neto del día (Open vs Close).

---

### 4. PM High Fade to Open %
**Formula**: `((rth_open - pm_high) / pm_high) * 100`

**Lógica (SQL Aggregation)**:
1. Filtra `intraday_1m` para `timestamp < 09:30`.
2. Obtiene `MAX(high)` como `pm_high`.
3. Calcula la diferencia relativa con el `open` de RTH.

---

### 5. M(x) Metrics (M15, M30, M60)
**Formula**: `((price_at_Mx - rth_open) / rth_open) * 100`

**Lógica**:
- **Price at Mx**: Se busca la barra de las 09:45 (M15), 10:00 (M30), etc., en `intraday_1m`.
- Si no existe la barra exacta, se usa la última disponible antes de ese tiempo.

### 6. Premarket Volume (Individual Records)
**Fórmula**: `SUM(volume)` para barras de 1m donde `timestamp < 09:30`.

**Lógica de Implementación**:
1. El screener realiza una agregación (CTE) de `intraday_1m` para cada `(ticker, date)` candidato.
2. Calcula la suma de volumen en el intervalo Premarket.
3. Unifica este dato con `daily_metrics` para permitir el filtrado.

---

## Filter Implementation: Screener Logic

El Screener (`/api/market/screener`) procesa los filtros en dos etapas:

### Etapa 1: Filtro de Base (SQL)
Se filtran las fechas y tickers en la base de datos para reducir el volumen de datos.
```sql
SELECT * FROM daily_metrics WHERE date BETWEEN ? AND ?
```

### Etapa 2: Agregación Intraday (SQL CTE)
Para los candidatos, se extraen métricas intradía que no están en la tabla diaria.
```sql
WITH intraday_stats AS (
    SELECT ticker, CAST(timestamp AS DATE) as d,
           SUM(CASE WHEN strftime(timestamp, '%H:%M') < '09:30' THEN volume END) as pm_volume,
           MAX(CASE WHEN strftime(timestamp, '%H:%M') < '09:30' THEN high END) as pm_high
    FROM intraday_1m
    GROUP BY 1, 2
)
```

### Etapa 3: Filtro Dinámico (Python)
Una vez calculadas las métricas (`gap`, `pm_volume`, `m15_return`, etc.) en un DataFrame, se aplican los filtros del usuario:
- **`min_{metric}`**: `df[df[metric] >= value]`
- **`max_{metric}`**: `df[df[metric] <= value]`
- **Especiales**: `min_pm_volume`, `hod_after`, `lod_before`.

---

## Statistical Aggregation Logic

Para el Dashboard, el backend realiza agregaciones complejas uniendo `daily_metrics` (subset filtrado) con `intraday_1m`.

### Promedio de Spikes y Fades
```sql
SELECT 
    AVG((h.high - f.rth_open) / f.rth_open * 100) as avg_high_spike,
    AVG((f.rth_open - pm_h) / pm_h * 100) as avg_pmh_fade
FROM intraday_1m h
JOIN filtered_subset f ON h.ticker = f.ticker AND CAST(h.timestamp AS DATE) = f.date
```

### Distribuciones HOD/LOD
Se utiliza la función `ARGMAX` y `ARGMIN` de DuckDB para encontrar la hora exacta del High/Low de forma eficiente:
```sql
SELECT ARGMAX(high, strftime(timestamp, '%H:%M')) as hod_time
FROM intraday_1m
GROUP BY ticker, CAST(timestamp AS DATE)
```

---

## Resumen de Cambios vs Arquitectura Antigua
1. **Eliminación de `historical_data`**: Reemplazada por `intraday_1m`.
2. **Fin de Pre-cálculos**: No existen columnas como `gap_at_open_pct` en la base de datos; se generan al vuelo.
3. **Filtros Flexibles**: Cualquier columna calculada en Python es filtrable automáticamente mediante los prefijos `min_` y `max_`.
