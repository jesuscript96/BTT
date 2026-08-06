# Hallazgos confirmados — investigación de splits

Solo lo verificado y validado hasta ahora. Nada de esto asume ninguna
regla de estrategia (entrada, salida, stop, universo) — eso queda
pendiente de las reglas reales que faltan por definir.

## 1. Timing de los splits: siempre en la primera vela del día

Verificado sobre una muestra de 20 reverse splits registrados en los
últimos 12 meses (tabla `splits`), comparando cada uno contra el
**día de trading anterior real** (no el día natural — el primer
intento tenía ese bug, corregido antes de sacar conclusiones).

- **17 de 17 casos con datos disponibles**: el salto de precio grande
  está en la primera vela del día del split, nunca a media sesión.
- 3 de los 20 tickers de la muestra (LGSXY, EELFF, CSCIF) no tenían
  ninguna vela intradía disponible — parecen tickers OTC/extranjeros
  fuera de cobertura del feed, no se pudieron verificar.

**Conclusión:** un detector basado en `ratio(prev_close, open)` entre
el cierre de ayer y la primera vela de hoy no se pierde ningún caso
por problemas de timing. El riesgo real sigue siendo solo de
cobertura (splits que faltan en la tabla `splits`), no de dónde mirar
el salto.

## 2. Tamaño del universo candidato

Con el filtro `PMH Gap >= 50%` y `open PM > $1` (tipo CS/ADRC/OS),
en los **últimos 12 meses** hay **2.398 días candidato** (ticker+fecha).

De esos, **467 (19,5%)** son sospechosos de split (registrados en
`splits` o con `ratio(prev_close, open) >= 10`).

Este número es solo un recuento del universo — no implica ningún
criterio de entrada/salida sobre él.

## 3. Bug encontrado y corregido: comparación de fechas de distinto tipo

Al cruzar candidatos de `daily_metrics` (fecha vía `CAST(... AS DATE)`,
que DuckDB devuelve a pandas como `Timestamp`) contra fechas de
`intraday_1m` (convertidas explícitamente a `datetime.date` con
`.dt.date`), una comprobación `(ticker, fecha) in cand_set` fallaba
**siempre**, silenciosamente — sin lanzar ningún error, simplemente
no encontraba coincidencias nunca.

Síntoma: un bucle que debería generar cientos de resultados devolvía
0 en todos los casos, de forma consistente mes a mes, sin ningún
mensaje de error.

**Lección para cualquier script futuro sobre estos datos:** normalizar
explícitamente el tipo de fecha (`pd.to_datetime(...).dt.date`) en
**todas** las columnas de fecha antes de cualquier `join`, `merge` o
comparación por `set`/`dict`, tanto si vienen de `daily_metrics` como
de `intraday_1m` o de `splits` — cada una puede llegar en un tipo
distinto desde DuckDB según cómo se construyó la consulta.

---

# Hallazgos — backtest vía motor real de Edgecute (no réplica manual)

A partir de aquí, las reglas de estrategia SÍ están definidas (PMH Gap
>= 50%, PM open > $1, corto, entrada M1 close<prev_close en 05:00-08:00,
stop 30%, salida 11:00) y el backtest se ejecuta llamando al motor real
de la app (`run_backtest_orchestrator`, `translate_strategy`, etc.), no
con lógica propia.

## 4. Zona horaria de `intraday_1m`: hora de Nueva York (ET), no UTC

Verificado comparando un mes de verano y uno de invierno, para
descartar cualquier duda por el cambio de hora:

- **ABTS, 2026-06-01** (verano, ET = UTC-4): primera vela `04:00:00`,
  última `19:59:00`.
- **FIG, 2025-12-01 a 2025-12-05** (invierno, ET = UTC-5): primera vela
  `04:00-04:10`, última `19:57-19:59`.

Si los timestamps fueran UTC real, el mismo horario de mercado
aparecería en horas UTC distintas entre verano e invierno (por el DST).
Aparece idéntico en ambos casos (04:00–20:00). **Conclusión: son ya
hora de Nueva York — no hace falta traducir horas de entrada/salida al
definir una estrategia.**

## 5. El motor de universo (dataset/`saved_queries.rules`) no soporta comparación campo-contra-campo ni OR

`_build_where_clause` / `_evaluate_rules_on_df`
([data_service.py:219](../backend/app/services/data_service.py#L219))
solo permite reglas de la forma `campo <operador> valor_fijo`, unidas
siempre por AND. No hay forma de expresar "columna A vs columna B"
(p.ej. `open premarket / prev_close >= 10`) ni combinar condiciones con
OR. Tampoco existe una columna precalculada de split-flag en
`daily_metrics` (confirmado leyendo el esquema real del parquet:
`ticker, timestamp, open, high, low, close, volume, transactions,
pm_volume, pm_high, pm_low, pm_high_time, pm_low_time, gap_pct,
pmh_gap_pct, ...` — sin ningún campo de split).

**Consecuencia práctica:** un filtro de exclusión "ratio open/prev_close
>= 10" (para descartar días sospechosos de split) no se puede expresar
tal cual con la lógica existente. La aproximación de una sola dirección
sí es nativa: `Open Gap % < 900` (matemáticamente equivalente a
`open/prev_close < 10` para el lado alcista), usada como Versión B del
28 backtest de fade premarket.

## 6. Fallo real que causó "0 operaciones" — no es el motor de señales, es un default silencioso del orquestador

Un primer intento de backtest con el motor real dio **0 operaciones en
2.761 pares día-ticker** que sí pasaban el filtro de universo. Antes de
asumir que la estrategia simplemente "no generaba señales", se
investigó la causa exacta:

- Se descartó que fuera una excepción tragada dentro de
  `translate_strategy` (ver hallazgo 7): se instrumentó el `except` y
  se relanzó el backtest para un solo mes — **0 excepciones
  capturadas**.
- La causa real está en
  [backend/app/services/backtest_orchestrator.py:331](../backend/app/services/backtest_orchestrator.py#L331):

  ```python
  market_sessions = req.market_sessions or _sdef.get("market_sessions") or ["RTH"]
  ```

  Si ni la petición de backtest ni la estrategia guardada especifican
  `market_sessions` explícitamente, el orquestador cae por defecto a
  `["RTH"]` (solo sesión regular, 09:30-16:00 ET) — **no** al "todo el
  día sin restricción" que sugiere la firma de `run_backtest()` en
  `backtest_service.py` (`market_sessions: list[str] | None = None`).
  Con `["RTH"]` activo, `_get_market_sessions_mask` recorta el
  DataFrame de cada día ANTES de evaluar la lógica de entrada,
  eliminando toda vela premarket — incluida la ventana entera 05:00-08:00
  de esta estrategia. Resultado: 0 entradas posibles, en todos los
  días, sin ningún error ni aviso.

**Lección:** el valor por defecto real de `market_sessions` no está en
`run_backtest()` (que sugiere "sin restricción" si se lee aislado),
sino en el orquestador que lo envuelve. Cualquier estrategia con lógica
fuera de RTH (premarket o after-hours) tiene que fijar
`market_sessions` explícitamente — `["all"]` para no restringir nada,
o la lista concreta de sesiones que necesite — tanto en la petición de
backtest como, idealmente, en la propia definición de estrategia. No
asumir el default.

## 7. Riesgo arquitectónico real (independiente del hallazgo 6): un fallo del motor de señales puede devolver "0 operaciones" indistinguible de un resultado válido

En el bucle secuencial de `run_backtest`
([backend/app/services/backtest_service.py](../backend/app/services/backtest_service.py),
~línea 552 en el momento de escribir esto):

```python
try:
    signals = translate_strategy(mini_df, strategy_def, daily_stats, compiled=compiled_strategy)
except Exception:
    del mini_df
    continue
```

Este `except Exception` no loguea nada. Si `translate_strategy` lanzara
una excepción real para todos los pares (un campo mal formado, un tipo
de dato inesperado, lo que sea), el resultado final sería exactamente
el mismo que "la estrategia no genera señales": `0 días, 0 operaciones`,
sin ningún rastro en logs ni en la respuesta de la API. Un usuario (o un
agente) no tiene forma de distinguir ambos casos desde fuera del código.

Esta vez no fue la causa (ver hallazgo 6, y la instrumentación de este
`except` para un mes completo confirmó 0 excepciones reales). Pero es un
riesgo real y queda documentado como tal: cualquier "0 operaciones"
inesperado debería descartarse instrumentando este `except` antes de
asumir que es un resultado legítimo.

## 8. Segundo default silencioso: `accept_reentries=true` / `max_reentries=-1` (reentradas ilimitadas)

`RiskManagement` en el esquema de estrategia
([backend/app/schemas/strategy.py:305-306](../backend/app/schemas/strategy.py#L305))
trae por defecto:

```python
accept_reentries: Optional[bool] = True
max_reentries: Optional[int] = -1   # ilimitado
```

Cualquier estrategia que no toque estos dos campos explícitamente
permite **reentradas ilimitadas el mismo día-ticker**: si una posición
cierra (por stop, por ejemplo) y vuelve a cumplirse la condición de
entrada dentro de la ventana horaria, el motor abre otra operación, sin
límite. No es un caso raro — con un stop del 30% y una ventana de horas,
es perfectamente posible que salte el stop y quede ventana para
reentrar.

Verificado con precisión en
[backend/app/services/portfolio_sim.py:597-598](../backend/app/services/portfolio_sim.py#L597)
el significado exacto de `max_reentries`: la comprobación es
`if total_trades > max_reentries: can_enter = False`, con `total_trades`
contando operaciones YA abiertas antes del intento actual. Con
`max_reentries=1`: 1ª entrada con `total_trades=0` (0>1 falso, entra,
pasa a 1), 2ª entrada con `total_trades=1` (1>1 falso, entra, pasa a 2),
3ª entrada con `total_trades=2` (2>1 verdadero, bloqueada). Es decir,
`max_reentries=N` permite `N+1` operaciones totales por día-ticker, no
`N`. Además, cada reentrada respeta la misma ventana horaria de entrada
que la primera (el masking por `entry_time_windows` se aplica una vez
sobre todo el array de señales, antes del bucle de simulación —
[strategy_engine.py:519-542](../backend/app/services/strategy_engine.py#L519)),
y cada reentrada calcula su propio stop desde su propio precio de
entrada, no hereda el nivel de la operación anterior
([portfolio_sim.py:644-667](../backend/app/services/portfolio_sim.py#L644)).

**Lección:** igual que `market_sessions` (hallazgo 6), este es un campo
que "parece neutro si no lo tocas" y no lo es. Cualquier estrategia
pensada como "una sola entrada por día" tiene que fijar
`accept_reentries: false` (o `max_reentries: 0`) explícitamente.

## 9. `size_by_sl` no es accesible desde la interfaz web (aunque el motor y la API sí lo soportan)

Intentando verificar a mano en `localhost:3000` un resultado ya
calculado por API, se encontró que `size_by_sl` no se puede activar
desde la web para una estrategia guardada:
[frontend/src/components/backtester/BacktestPanel.tsx:470](../frontend/src/components/backtester/BacktestPanel.tsx#L470)
— `const sizeBySl = riskMgmt?.size_by_sl || false;` — se lee
directamente (y solo) de la definición de estrategia ya guardada, sin
ningún checkbox propio en el panel de backtest. Y esa definición nunca
puede tener `size_by_sl=true` de forma persistente porque el esquema
`RiskManagement`
([backend/app/schemas/strategy.py:301-312](../backend/app/schemas/strategy.py#L301))
no declara ese campo — cualquier intento de guardarlo se descarta en
silencio al validar contra el modelo Pydantic (comportamiento default
de Pydantic: ignora campos no declarados). Resultado: **no accesible
desde la interfaz**, aunque `BacktestRequest` sí lo acepta perfectamente
por API/script.

Consecuencia práctica: un backtest con `size_by_sl=true` (para que el
"R" reportado sea el R normalizado por riesgo — ver hallazgo 10) lanzado
por API/script no se puede replicar tal cual desde la web hoy, porque
ahí siempre corre con `size_by_sl=false`.

**Para el equipo de producto:** para que sea accesible, `size_by_sl`
necesita (a) declararse en el esquema `RiskManagement` para que se
guarde, y (b) un control en `BacktestPanel` en vez de derivarse solo de
la definición guardada.

## 10. `size_by_sl`: qué mide cada modo exactamente — fórmula real, sin juzgar cuál es "mejor"

Verificado en [backend/app/services/portfolio_sim.py:626-681](../backend/app/services/portfolio_sim.py#L626).
`risk_amount` es el mismo en los dos modos (con `risk_type="FIXED"`:
`risk_amount = risk_r`, línea 641). Lo que cambia es cómo se calcula
`size` (nº de acciones):

**`size_by_sl=False`** (el que fuerza la web hoy, vía hallazgo 9) —
línea 676-677:
```python
# Traditional sizing: deploy risk_amount into the position
size = risk_amount / entry_price
```
Despliega siempre `risk_amount` **dólares de exposición** en la
posición, sea cual sea la distancia al stop. Si el stop salta, la
pérdida real es `size × distancia_stop = risk_amount × stop_pct` — con
`risk_r=100` y stop del 30%, un stop completo pierde $30, no $100. El
"R" que reporta el motor (`pnl / risk_r`,
[backtest_service.py:_compute_r_multiple](../backend/app/services/backtest_service.py))
en este modo resulta ser, matemáticamente, `(entrada-salida)/entrada` —
el movimiento porcentual del precio sin más. Un stop completo da
siempre exactamente `-stop_pct` en R (aquí, **-0,30R**), nunca -1R.
Mide "cuánto se movió el precio", con la misma exposición en dólares en
todas las operaciones.

**`size_by_sl=True`** — línea 669-674:
```python
if size_by_sl:
    dist = abs(entry_price - stop_loss_price) if stop_loss_price > 0.0 else 0.0
    if dist > 0.0:
        size = risk_amount / dist
    else:
        size = risk_amount / entry_price
```
Ajusta el tamaño para que, si el precio llega exactamente al stop, la
pérdida sea **exactamente** `risk_amount` ($100). El "R" reportado es
entonces la fracción real de lo que se decidió arriesgar — un stop
completo da siempre exactamente **-1,00R**, sea cual sea el % de stop.
Mide "cuánto arriesgaste de verdad", con exposición en dólares distinta
en cada operación según lo ancho que sea su stop.

En ambos casos, `size` queda topado por el efectivo disponible (línea
680-681: `max_size = available_cash / entry_price`).

Ninguno de los dos es "el correcto" en abstracto: sin `size_by_sl`, todas
las operaciones comprometen el mismo capital pero arriesgan cantidades
distintas; con `size_by_sl`, todas arriesgan la misma cantidad pero
comprometen capital distinto. Depende de si se quiere comparar
operaciones por movimiento de precio o por riesgo real asumido.

---

*Regla de estrategia definida y en uso desde el hallazgo 4 en adelante:
PMH Gap >= 50%, PM open > $1, corto, entrada M1 close<prev_close en
05:00-08:00 hora NY, stop 30%, salida 11:00 hora NY.*
