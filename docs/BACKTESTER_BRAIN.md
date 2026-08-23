# Backtester: interpretación del "cerebro"

Este documento describe cómo el motor de backtest interpreta cada bloque de la página **New Strategy** y los parámetros de la pestaña **Backtester**.

## 1. Direction Bias (Sesgo de dirección)

- **Long Bias**: Las condiciones de entrada generan señales para **abrir posiciones largas**. Una condición como "Close cruza por encima de VWAP" dispara una entrada **LONG**.
- **Short Bias**: Las mismas condiciones de entrada generan señales para **abrir posiciones cortas**. "Close cruza por debajo de SMA" dispara una entrada **SHORT**.

El bias no cambia la lógica de la condición; solo determina la dirección de la operación (compra o venta en corto).

## 2. Entry Logic (Lógica de entrada)

Cada fila del builder se traduce en una condición booleana por barra:

- **Indicador (origen)** + **Comparador** + **Valor o indicador (destino)**  
  Ejemplo: `Close` `>` `VWAP` → "el cierre de la barra actual es mayor que el VWAP".

Comparadores soportados: `>`, `<`, `>=`, `<=`, `=`, **Crosses Above**, **Crosses Below**.

Las condiciones se combinan con **AND** u **OR** según el grupo. El motor evalúa cada indicador por **ticker** (sin mezclar datos entre símbolos).

### Indicadores disponibles

| Indicador | Parámetros | Descripción |
|-----------|------------|-------------|
| Close, Open, High, Low | — | Precio de cierre, apertura, máximo, mínimo de la vela |
| PMH, PML | — | Precio máximo/mínimo del premarket |
| SMA, EMA, WMA | period | Medias móviles |
| RVOL | period | Volumen relativo al promedio histórico |
| VWAP, AVWAP | — | VWAP acumulado de la sesión |
| RSI | period (overbought/oversold opcionales) | Índice de Fuerza Relativa |
| MACD, ATR, ADX | period | MACD, ATR, ADX |
| Williams %R | period | Estocástico Williams |
| Volume, AVolume | — | Volumen de la vela / acumulado desde inicio sesión |
| Consecutive Red Candles | — | Número de velas rojas consecutivas |
| Consecutive Higher Highs / Lower Lows | — | Conteo de máximos/mínimos consecutivos crecientes/decrecientes |
| Ret % PM / RTH / AM | — | % de retorno desde primer precio PM / apertura RTH / cierre RTH |
| Time of Day | time_hour, time_minute | Hora del día (minutos desde medianoche) |
| Max N Bars | period | Máximo de los high de las últimas n velas |

## 3. Exit Logic (Lógica de salida)

Misma estructura que Entry Logic. Las condiciones definen **cuándo cerrar** la posición (salida por señal), además del stop loss, take profit y trailing stop.

## 4. Risk Management

### Hard Stop Loss

- **Usar Hard Stop** (on/off): Si está off, no se aplica stop por porcentaje/ATR; la posición solo se cierra por TP, trailing, exit logic o tiempo.
- **Tipo**: Percentage (distancia % desde entrada), ATR Multiplier, Fixed Amount, Market Structure (HOD/LOD).

### Take Profit

- **Usar Take Profit** (on/off): Si está off, no se cierra por objetivo de ganancia fijo.
- **Tipo**: Por ahora solo Percentage ( % de ganancia desde entrada).

### Trailing Stop

- **Activo** (on/off).
- **Tipo**: Percentage (distancia % que sigue el precio a favor). La distancia se indica en **Distance %** (buffer_pct).
- Comportamiento: el stop solo se endurece cuando el precio va a favor (no se relaja). Salida cuando el precio toca el nivel (usando high/low de la barra).

## 5. Parámetros del Backtester (Execution Panel)

| Parámetro | Efecto |
|-----------|--------|
| **Commission ($/share)** | Coste por acción al abrir (y opcionalmente al cerrar). Comisión total = commission_per_share × position_size. |
| **Locates ($/100 shares)** | Coste por cada 100 acciones (redondeo al alza). Locate fee = ceil(position_size/100) × locate_cost_per_100. |
| **Slippage (%)** | Se aplica al precio de entrada y salida (empeora el precio en el % indicado). |
| **Lookahead Prevention** | Si está activo, las señales de entrada y salida se desplazan 1 barra (entrada/salida en la barra siguiente a la que disparó la condición). |
| **Risk per Trade (R)** | Cantidad en USD que se arriesga por operación. El tamaño de posición se calcula para que el riesgo por trade sea exactamente este valor (salvo límite de balance). |
| **Market Interval** | Solo se operan barras dentro de los intervalos elegidos: **PM** (04:00–09:30), **RTH** (09:30–16:00), **AM** (16:00–20:00). Se pueden elegir varios. |
| **Date From / Date To** | Solo se incluyen barras y universo en ese rango de fechas. |
| **Initial Capital** | Capital inicial del backtest. |

## 6. Flujo de señales (resumen)

1. Se cargan los datos de mercado y se filtran por **fechas** e **intervalo(s)** (PM/RTH/AM).
2. Por cada estrategia se evalúa la **Entry Logic** y la **Exit Logic** sobre el DataFrame (por ticker), generando matrices de señales booleanas.
3. Si **Lookahead Prevention** está activo, se aplica un shift(1) por ticker a las señales.
4. El motor JIT recorre barra a barra: cierra posiciones abiertas si tocan SL/TP, trailing, exit signal, tiempo máximo o EOD; luego abre nuevas posiciones cuando hay señal de entrada, aplicando **comisión por share**, **locates**, **slippage** y **risk per trade** (R en USD).
5. Los resultados se agregan (equity curve, trades, métricas) y se cruzan con VectorBT en el validator (win rate, max drawdown, Sharpe, profit factor, total PnL).

## Checklist de interpretación

- [ ] **Direction Bias**: Short → entradas short; Long → entradas long.
- [ ] **Entry Logic**: Cada fila (indicador + comparador + valor/indicador) es una condición; AND/OR según el grupo.
- [ ] **Exit Logic**: Misma lógica que Entry pero para cerrar.
- [ ] **Hard Stop / Take Profit**: Distancia en % o ATR desde entrada; se pueden desactivar con los toggles.
- [ ] **Trailing Stop**: Distancia % que sigue el precio a favor; solo se endurece.
- [ ] **Comisiones y locates**: Por share y por cada 100 shares.
- [ ] **Slippage**: Aplicado en entrada y salida.
- [ ] **Look-ahead**: Señales desplazadas 1 barra.
- [ ] **Risk per trade**: R en USD por operación.
- [ ] **Market Interval**: Solo barras en PM/RTH/AM seleccionados.
- [ ] **Date range**: Solo datos en [date_from, date_to].
