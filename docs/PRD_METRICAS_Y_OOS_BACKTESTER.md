# PRD — Métricas honestas del backtester y OOS real (IS/OOS persistido)

> **Para:** Jaume (y su IA). **De:** Álvaro (recopilado con ZCode). **Fecha:** 2026-09-08.
> **Estado:** propuesta — pendiente de revisión y decisiones.
> **Origen:** sesión de análisis de la 1B Modelización Sobri del 2026-09-08.
> Evidencia completa en `docs/MEMORIA_MADRE.md`, entradas
> [HALLAZGO · 2026-09-08 · 01], [· 02] y [· 03] (más el bug viejo de
> `total_return_r`, ya documentado en su día en la línea ~4064).

---

## 0. El problema, en una frase

Después de un día entero comparando versiones de la 1B Sobri descubrimos que
**tres de las cifras que usamos para decidir no significan lo que creemos**:
el split IS/OOS no existe en el motor (lo recorta el navegador y se pierde al
cerrar la página), el Return/Calmar que muestra la UI ignora los gastos y
depende del capital inicial que pongas, y la R total guarda siempre 0.

No hay ningún bug de aritmética: reconstruimos las curvas trade a trade y
cuadran al céntimo. Es un problema de **semántica y de qué se persiste**, y
eso lo hace traicionero: los números parecen válidos y no lo son como
comparadores entre configuraciones distintas.

## 1. Los cuatro problemas, con evidencia

### P1 — El OOS no existe en el backend (el `is_percent` se descarta)

- La UI envía `is_percent` en el POST del backtest
  (`frontend/src/components/backtester/BacktestPanel.tsx:712,815`), pero
  `BacktestRequest` (`backend/app/services/backtest_orchestrator.py:41`) **no
  declara ese campo**: Pydantic lo tira y el motor ejecuta el rango completo.
- El recorte IS que enseña la pestaña se recalcula **en el cliente**
  (`frontend/src/app/backtester/page.tsx:1076+`, memo `isFilteredResult`), y
  el OOS **no se guarda en ningún sitio**. Al cerrar la página, se pierde.
- Consecuencia práctica: hoy comparamos versiones "con OOS al 10 %" que en
  la BD son todas IS+OOS mezclados, y el OOS hay que reconstruirlo a mano
  con un script replicando la lógica del frontend.

**Arreglo propuesto (server-side, sin partir el motor):**
1. Declarar `is_percent: int = 100` en `BacktestRequest`.
2. El orquestador ejecuta UNA vez el rango completo (como ahora — mismo
   coste, mismos números) y después calcula las métricas por segmento con la
   MISMA lógica que hoy usa el frontend: cutoff por índice de equity
   (`floor(len(global_equity) * is/100)`), trades particionados por
   `entry_time_epoch`.
3. Persistir en `results_json.aggregate_metrics` dos bloques nuevos:
   `is_metrics` y `oos_metrics` (trades, WR, PF sobre pnl, R total, retorno,
   maxDD). Con `is_percent=100`, `oos_metrics` queda vacío/nulo.
4. La UI pasa a leer esos bloques del payload en vez de recalcular en el
   cliente (el memo actual se queda como fallback para corridas viejas).

**Criterios de aceptación:**
- Con `is_percent=90`, el payload persistido contiene `is_metrics` y
  `oos_metrics` y sus números coinciden bit a bit con lo que hoy pinta la
  pestaña IS de la UI.
- Una corrida guardada de hoy (1B Sobri 3, 17:10:28) re-ejecutada con
  `is_percent=90` reproduce: IS = 1713 trades / PF 1.583 / 318.07 R;
  OOS = 118 trades / PF 2.499 / 38.48 R.
- `is_percent=100` no cambia NADA respecto al comportamiento actual.

### P2 — Return y Calmar: el neto no existe y la escala es un espejismo de la config

- `total_return_pct = total_pnl / init_cash` con `total_pnl` SIN gastos
  (`backtest_service.py:1779-1780`); `monthly_expenses` solo llega a
  `total_pnl_net` (`:1760-1772`). Con 300 $/mes sobre 10.000 $ iniciales,
  la UI infla un 36 % del capital que no se ve en ningún número principal.
- El Calmar divide retorno TOTAL / maxDD (`:1882-1883`) — el propio código
  tiene un comentario admitiendo que "annualized makes more sense" — y el
  tooltip de la UI dice "rentabilidad **anualizada**", que es falso
  (`MetricsCard.tsx:25`).
- Con `risk_type=FIXED`, el sizing es 300 $ por trade independientemente del
  equity: el return es **inversamente proporcional a init_cash** (919 % con
  10 k, 92 % con 100 k, mismos trades) y el maxDD en % se encoge al crecer la
  cuenta (el de la Sobri 3 ocurrió el día 1 y nunca más) — de ahí el Calmar
  de 60. Comparar corridas con distinto init_cash o distinto risk_type por
  Return/Calmar es comparar peras con manzanas.
- La curva principal de equity pinta `global_equity` (sin gastos); la curva
  con gastos (`global_equity_expenses`) viaja en el payload y no se dibuja
  (`page.tsx:1538`, `ResultsTabs.tsx:293,481,502`).
- Extremo del mismo problema: `risk_type=PERCENT` compone el 5 % sobre el
  equity diario sin tope de nocional/liquidez → corridas de 9,5 billones %
  (corrida `bc7df3a6` del 08-sep). Aritméticamente exacta, absolutamente
  irreal.

**Arreglo propuesto:**
1. **Neto como cifra principal:** Return, Calmar y expectancy sobre
   `total_pnl_net`; el bruto pasa a secundario (tooltip o métrica extra).
   Decisión a tomar: ¿retro-compatible o solo corridas nuevas?
2. **Calmar anualizado de verdad** (CAGR / maxDD) y tooltip corregido. En
   ventanas de 1 año apenas cambia; en backtests más largos deja de mentir.
3. **Pintar la equity con gastos** en la curva principal (toggle bruto/neto;
   por defecto neto).
4. **Darle a la R el protagonismo de comparador:** mostrar "R total" (ΣR)
   junto al Return — es el único número inmune a init_cash/risk_type. Va
   de la mano del P3.
5. **(Decisión grande, separable):** tope opcional de nocional/liquidez para
   PERCENT (máx. $ por trade y/o % del ADV). No lo bloquea todo lo demás.

**Criterios de aceptación:**
- El Return principal de la corrida de referencia pasa de 919,31 % a 883,31 %
  (neto con 3.600 $ de gastos) y el equity final de la curva coincide con
  `global_equity_expenses[-1]`.
- El tooltip del Calmar describe exactamente el cálculo que hace el backend.
- Dos corridas idénticas salvo init_cash (10 k vs 100 k) muestran el MISMO
  ΣR y Return en R, y distintos % (eso se documenta, no se "arregla").

### P3 — `total_return_r` guarda siempre 0 (bug conocido, sin fix)

- `strategy_search.py:42` lee una clave que `aggregate_metrics` no tiene y
  cae a 0. Lo hemos ido sorteando con scripts que suman `r_multiple` de los
  trades embebidos en el JSON.
- **Arreglo:** que el motor guarde ΣR en `aggregate_metrics` (p. ej.
  `r_total`) y que la columna lea de ahí. Barato, y desbloquea el punto 4
  del P2 y cualquier análisis desde la BD sin parsear megas de JSON.

**Criterio de aceptación:** la corrida de referencia guarda
`total_return_r = 356.55` (Sobri 3) sin tocar su `results_json` a mano.

### P4 — `backtest_params` persiste fechas que no son las ejecutadas

- Dos corridas de hoy (`240d10bc`, `fe1040b1`) guardan
  `start_date=2026-01-02 / end_date=2026-09-04` pero sus trades reales van
  de 2025-01-02 a 2025-12-31. Parece que se persiste el formulario, no lo
  ejecutado.
- **Arreglo:** persistir el rango efectivo (min/max de fechas de trades o el
  que el orquestador resuelva tras su validación). Es higiene de metadatos,
  pero cualquier segmentación por fechas (incluido el IS/OOS del P1)
  heredaría esta bomba si no se arregla.

**Criterio de aceptación:** imposible guardar un `backtest_params` cuyas
fechas no coincidan con los trades persistidos (assert o normalización).

## 2. Qué NO se toca

- **La zona del bot de alertas** (íntegra, ni un fichero): esto es todo del
  backtester. `market_frame.py` tampoco.
- El motor de señales/ejecución: el P1-P4 no cambian NI UN trade. Misma
  entrada, misma salida, mismos R. Solo cambia qué se calcula, persiste y
  pinta. Eso hace el PR seguro para paridad: cualquier corrida antigua
  re-ejecutada debe dar los mismos trades y las mismas métricas brutas.
- El schema de `daily_metrics`/`intraday_1m` y el Parquet de GCS.
- No se "arregla" que el return dependa de init_cash con riesgo FIXED: es
  definitorio del modo. Se documenta y se acompaña de R.

## 3. Orden propuesto

1. **P3** (ΣR persistido) — 1 tarde, desbloquea análisis desde BD.
2. **P1** (IS/OOS persistido server-side) — el de más valor para decidir
   estrategias con rigor.
3. **P2.1-2.3** (neto + Calmar anualizado + curva con gastos) — honestidad
   de las cifras que ya miramos a diario.
4. **P4** — higiene de metadatos, idealmente antes que el P1 (mismo terreno).
5. **P2.5** (topes PERCENT) — decisión de producto separada, sin prisa.

## 4. Decisiones que faltan (las de Álvaro/Jaume)

- ¿Return/Calmar netos rompen retro-compatibilidad con corridas guardadas o
  conviven bruto+neto desde ya?
- ¿Calmar anualizado con CAGR o ventana móvil? (Recomendación: CAGR.)
- ¿El OOS segmentado server-side es suficiente, o queremos walk-forward real
  multi-ventana (`/api/robustness/wfo/*`) integrado en la pestaña?
- ¿Topes de nocional para PERCENT: % ADV, $ fijo, ambos?

## 5. Verificación prevista

- Paridad bit a bit: re-ejecutar las 5 corridas de la Sobri de hoy y exigir
  mismos trades/mismas métricas brutas que las guardadas.
- Tests nuevos: bloqueo P4 (fechas coherentes), bloques IS/OOS con
  `is_percent` 100/90/edge-cases (equity corta, cutoff en fin de semana),
  Calmar anualizado contra cálculo manual.
- Auditoría de UI: pestaña IS muestra lo persistido, no lo recalculado.
