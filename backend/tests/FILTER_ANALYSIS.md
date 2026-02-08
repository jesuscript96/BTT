# Análisis de Filtros: Implementados vs Testeados

## Filtros en market.py

### Prefijos implementados (dinámicos):
- `min_*`: Aplica `>=` (ej: `min_gap_at_open_pct`, `min_rth_volume`)
- `max_*`: Aplica `<=` (ej: `max_gap_at_open_pct`, `max_rth_run_pct`)
- `exact_*`: Aplica `=` (ej: `exact_gap_at_open_pct`)

### Filtros especiales (hardcoded):
- `trade_date`: Fecha específica
- `start_date` + `end_date`: Rango de fechas
- `ticker`: Filtro por ticker específico
- `limit`: Limitación de resultados

## Filtros en data.py

**(Necesito revisar data.py completo)**

## Tests Existentes

### test_market_filters_basic.py:
- ✅ `test_min_gap_filter`
- ✅ `test_max_gap_filter`
- ✅ `test_min_rth_volume_filter`
- ✅ `test_min_pm_volume_filter`
- ✅ `test_min_rth_run_filter`
- ✅ `test_max_rth_run_filter`
- ✅ `test_min_pmh_fade_filter`
- ✅ `test_min_high_spike_filter`
- ✅ `test_max_high_spike_filter`
- ✅ `test_min_low_spike_filter`
- ✅ `test_max_low_spike_filter`
- ✅ `test_min_m15_return_filter`
- ✅ `test_max_m15_return_filter`
- ✅ `test_min_m30_return_filter`
- ✅ `test_max_m30_return_filter`
- ✅ `test_min_m60_return_filter`
- ✅ `test_max_m60_return_filter`
- ✅ `test_hod_after_filter`
- ✅ `test_lod_before_filter`
- ✅ `test_open_lt_vwap_filter`
- ✅ `test_pm_high_break_filter`
- ✅ `test_close_lt_m15_filter`
- ✅ `test_close_lt_m30_filter`
- ✅ `test_close_lt_m60_filter`
- ✅ `test_single_date_filter`
- ✅ `test_date_range_filter`
- ✅ `test_ticker_filter`

## Filtros Potencialmente Faltantes

*Necesito el documento del usuario para identificar qué falta*

## Pregunta para el Usuario

Como no puedo acceder al Google Doc, necesito que me proporciones:
1. Lista de todos los filtros que DEBERÍAN estar implementados
2. Cuáles específicamente NO funcionan o dan resultados incorrectos
3. Cuáles NO están implementados pero deberían estarlo
