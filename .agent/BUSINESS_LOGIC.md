# Lógica de negocio

## Glosario de trading
- Gap: diferencia % entre el close del día anterior y el open del día actual
- Small cap: empresa de baja capitalización bursátil, alta volatilidad
- Short: operación bajista (se vende primero, se compra después)
- PM (Pre-Market): sesión antes del mercado regular (04:00–09:30 ET)
- RTH (Regular Trading Hours): sesión regular (09:30–16:00 ET)
- PMH (Pre-Market High): máximo alcanzado en la sesión pre-market
- HOD/LOD: High of Day / Low of Day
- R-multiple: unidad de riesgo. 1R = riesgo inicial de la operación
- SL (Stop Loss): precio de salida para limitar pérdida
- TP (Take Profit): precio de salida para capturar ganancia
- EOD (End of Day): cierre forzado de posición al final de la sesión
- VWAP: Volume Weighted Average Price
- EV: Expected Value (valor esperado por operación)

## Flujo principal del producto
1. Market Analysis (Screener): filtra el mercado por gap, volumen, precio y métricas PM/RTH
2. Strategy Builder: define condiciones de entrada/salida y gestión de riesgo
3. Backtester: ejecuta simulación histórica sobre el universo filtrado
4. Resultados: métricas de performance (win rate, R-multiple, drawdown, Sharpe, etc.)

## Reglas de negocio críticas
- Los datos intradía son por minuto (1m bars): ticker, OHLCV, timestamp
- daily_metrics es una tabla precomputada con métricas del día (gap, PM stats, RTH stats)
- El backtester NO debe mirar hacia adelante (lookahead prevention: shift 1 bar)
- Las estrategias se persisten como JSON en DuckDB local (users.duckdb)
- El universo de backtest son tickers filtrados por daily_metrics (gaps + criterios)
- Más datos históricos = mejor pronóstico (actualmente 4-5 años, objetivo 20 años)

## Prioridades del cliente
1. Bugs críticos que rompen funcionalidades principales
2. Performance del backtester (actualmente lento en universos grandes)
3. Consolidación de las 3 apps en una sola
