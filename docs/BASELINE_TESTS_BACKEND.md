# Baseline de tests backend — expected-fails (2026-08-21)

> **Qué es:** la foto de los tests ROJOS conocidos tras el merge con staging
> (commit `894127b` + WIP GCS sin commitear en el working tree). Sirve para
> distinguir "rojo preexistente" de "regresión nueva" antes de cualquier
> salto `staging → develop → main`.
>
> **Cómo usarla:** correr el mismo comando y comparar. Todo rojo que esté en
> esta lista = preexistente (no bloquea). Todo rojo NUEVO (o verde que se
> vuelve rojo) = regresión → parar e investigar.

**Comando de reproducción** (venv del backend):

```bash
cd backend && ./.venv/Scripts/python.exe -m pytest tests/ -q --continue-on-collection-errors
```

**Resultado de la foto:** `108 failed, 337 passed, 15 errors` (2 min 39 s).
**Entorno:** local de Álvaro (`DISABLE_GCS_SYNC=true`,
`LIVE_SCREENER_ENABLED=false`, `ROBUSTNESS_ENABLED=true`; lago de datos
local). Los rojos masivos de filtros/métricas son de **datos/entorno** (sin
GCS y contra el DuckDB local), no del motor.

## Resumen por módulo

| Módulo | Rojos | Categoría |
|---|---|---|
| test_market_filters_basic / _advanced | 45 | Entorno/datos (DB local) |
| test_market_calculations | 25 | Entorno/datos (DB local) |
| test_backtest_queries | 12 | Entorno/datos (DB local) |
| test_new_metrics_tier1/2/3 | 27 | Entorno/datos (DB local) |
| test_run_backtest_slab_equivalence, test_slab_staleness | 4 | Backlog #3 (path paralelo/slab) |
| test_n2a_e2e_equivalence | 2 | Backlog #3 |
| test_accum_fast_equivalence | 1 | Backlog #3 |
| test_backtest_engine, test_backtest_integration | 2 (módulos) | Backlog #4 (imports muertos) |
| test_backtest_golden | 1 | Backlog #4 (solo servidor) |
| test_prefetch_parity | 1 | Backlog #4 (migración local) |
| test_candle_delay | 1 | Backlog #4 (semántica pre-2026-08-17) |
| test_strategy_api (422), test_strategy_update_idor | 2 | Preexistente conocido (MEMORIA 08-21) |

(Backlog = `docs/PROXIMOS_ITEMS.md` "Backlog CONGELADO".)

## Lista completa (123)

### tests/test_accum_fast_equivalence.py
- test_enrich_trades_arr_identical
### tests/test_backtest_engine.py
- (ERROR de coleccion/import del modulo)
### tests/test_backtest_golden.py
- test_backtest_golden
### tests/test_backtest_integration.py
- (ERROR de coleccion/import del modulo)
### tests/test_backtest_queries.py
- TestDateFiltering::test_date_from_filter
- TestDateFiltering::test_date_to_filter
- TestDateFiltering::test_ticker_filter_in_query
- TestJoinLogic::test_daily_historical_join
- TestJoinLogic::test_date_casting_in_join
- TestJoinLogic::test_interval_calculation
- TestRowLimiting::test_max_rows_limit
- TestRowLimiting::test_no_date_range_default_limit
- TestSavedQueryReconstruction::test_saved_query_dynamic_rules
- TestSavedQueryReconstruction::test_saved_query_max_gap
- TestSavedQueryReconstruction::test_saved_query_min_gap
- TestSavedQueryReconstruction::test_saved_query_volume
### tests/test_candle_delay.py
- test_candle_delay_and_session_leakage
### tests/test_market_calculations.py
- TestAggregateIntradayCalculations::test_aggregate_avg_change
- TestAggregateIntradayCalculations::test_aggregate_median_change
- TestAggregateIntradayCalculations::test_aggregate_time_grouping
- TestAverageCalculations::test_avg_gap_at_open_pct
- TestAverageCalculations::test_avg_high_spike_pct
- TestAverageCalculations::test_avg_low_spike_pct
- TestAverageCalculations::test_avg_m15_return_pct
- TestAverageCalculations::test_avg_m30_return_pct
- TestAverageCalculations::test_avg_m60_return_pct
- TestAverageCalculations::test_avg_pmh_fade_to_open_pct
- TestAverageCalculations::test_avg_rth_fade_to_close_pct
- TestAverageCalculations::test_avg_rth_run_pct
- TestBooleanToPercentageConversions::test_close_direction_red
- TestBooleanToPercentageConversions::test_close_lt_m15_percentage
- TestBooleanToPercentageConversions::test_close_lt_m30_percentage
- TestBooleanToPercentageConversions::test_close_lt_m60_percentage
- TestBooleanToPercentageConversions::test_open_lt_vwap_percentage
- TestBooleanToPercentageConversions::test_pm_high_break_percentage
- TestDistributionCalculations::test_hod_time_distribution
- TestDistributionCalculations::test_lod_time_distribution
- TestPriceCalculations::test_avg_pm_high
- TestPriceCalculations::test_avg_rth_close
- TestPriceCalculations::test_avg_rth_open
- TestVolumeCalculations::test_avg_pm_volume
- TestVolumeCalculations::test_avg_rth_volume
### tests/test_market_filters_advanced.py
- TestEdgeCases::test_combined_filters_with_nulls
- TestEdgeCases::test_empty_result_set
- TestEdgeCases::test_null_value_handling
- TestLogicCombinations::test_mixed_static_and_variable
- TestLogicCombinations::test_multiple_rules_and_logic
- TestLogicCombinations::test_multiple_rules_or_logic
- TestLogicCombinations::test_single_rule_and_logic
- TestStaticValueComparisons::test_static_equals
- TestStaticValueComparisons::test_static_greater_or_equal
- TestStaticValueComparisons::test_static_greater_than
- TestStaticValueComparisons::test_static_less_or_equal
- TestStaticValueComparisons::test_static_less_than
- TestStaticValueComparisons::test_static_not_equals
- TestVariableComparisons::test_all_metric_combinations
- TestVariableComparisons::test_variable_price_comparison
- TestVariableComparisons::test_variable_price_vs_pm_high
- TestVariableComparisons::test_variable_spike_comparison
- TestVariableComparisons::test_variable_volume_comparison
### tests/test_market_filters_basic.py
- TestBasicNumericFilters::test_max_gap_filter
- TestBasicNumericFilters::test_max_high_spike_filter
- TestBasicNumericFilters::test_max_low_spike_filter
- TestBasicNumericFilters::test_max_m15_return_filter
- TestBasicNumericFilters::test_max_m30_return_filter
- TestBasicNumericFilters::test_max_m60_return_filter
- TestBasicNumericFilters::test_max_rth_run_filter
- TestBasicNumericFilters::test_min_gap_filter
- TestBasicNumericFilters::test_min_high_spike_filter
- TestBasicNumericFilters::test_min_low_spike_filter
- TestBasicNumericFilters::test_min_m15_return_filter
- TestBasicNumericFilters::test_min_m30_return_filter
- TestBasicNumericFilters::test_min_m60_return_filter
- TestBasicNumericFilters::test_min_pm_volume_filter
- TestBasicNumericFilters::test_min_pmh_fade_filter
- TestBasicNumericFilters::test_min_rth_run_filter
- TestBasicNumericFilters::test_min_rth_volume_filter
- TestBooleanFilters::test_close_lt_m15_filter
- TestBooleanFilters::test_close_lt_m30_filter
- TestBooleanFilters::test_close_lt_m60_filter
- TestBooleanFilters::test_open_lt_vwap_filter
- TestBooleanFilters::test_pm_high_break_filter
- TestDateFilters::test_date_range_filter
- TestDateFilters::test_single_date_filter
- TestDateFilters::test_ticker_filter
- TestTimeFilters::test_hod_after_filter
- TestTimeFilters::test_lod_before_filter
### tests/test_n2a_e2e_equivalence.py
- test_n2a_on_estrategia_gated_cae_a_legacy_e2e
- test_n2a_on_igual_a_legacy_e2e
### tests/test_new_metrics_tier1.py
- TestDayReturnPct::test_day_return_formula
- TestDayReturnPct::test_day_return_negative_for_red_days
- TestDayReturnPct::test_day_return_positive_for_green_days
- TestPMHGapPct::test_pmh_gap_formula
- TestPMHGapPct::test_pmh_gap_positive_when_pm_high_above_prev_close
- TestPMHighTime::test_pm_high_time_format
- TestPMHighTime::test_pm_high_time_in_pm_session
- TestPrevClose::test_prev_close_exists
- TestRTHRangePct::test_rth_range_always_positive
- TestRTHRangePct::test_rth_range_formula
### tests/test_new_metrics_tier2.py
- TestMxHighSpike::test_all_mx_high_spike_columns_exist
- TestMxHighSpike::test_m1_high_spike_exists
- TestMxHighSpike::test_mx_high_spikes_increasing
- TestMxLowSpike::test_all_mx_low_spike_columns_exist
- TestMxLowSpike::test_low_spikes_usually_negative
- TestMxLowSpike::test_m1_low_spike_exists
- TestMxLowSpike::test_mx_low_spikes_decreasing
- TestMxSpikeRelationships::test_high_spike_greater_than_low_spike
- TestMxSpikeRelationships::test_m180_contains_hod_lod
### tests/test_new_metrics_tier3.py
- TestReturnMxRelationships::test_fade_detection_via_returns
- TestReturnMxRelationships::test_return_consistency_across_timeframes
- TestReturnMxToClose::test_all_return_mx_columns_exist
- TestReturnMxToClose::test_return_m15_negative_when_close_below_m15
- TestReturnMxToClose::test_return_m15_positive_when_close_above_m15
- TestReturnMxToClose::test_return_m15_to_close_exists
- TestReturnMxToClose::test_return_m30_calculation_logic
- TestReturnMxToClose::test_return_m60_calculation_logic
### tests/test_prefetch_parity.py
- test_prefetch_parity
### tests/test_run_backtest_slab_equivalence.py
- test_run_backtest_slab_equals_legacy
- test_run_backtest_slab_fallback_month_without_slab
- test_run_backtest_slab_with_jit
### tests/test_slab_staleness.py
- test_stale_slab_rebuilds_on_source_change
### tests/test_strategy_api.py
- test_create_and_get_strategy
### tests/test_strategy_update_idor.py
- test_update_fila_legacy_null_sigue_editable
