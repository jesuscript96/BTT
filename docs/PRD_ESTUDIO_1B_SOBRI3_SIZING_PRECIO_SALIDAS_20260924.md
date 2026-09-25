# PRD — Estudio 1B · Modelización Sobri 3: sizing, corte de precio y horario de salidas

> **Para:** GLM (ejecutor) · **Pide:** Álvaro · **Fecha:** 2026-09-24
> **Rama:** `alvaro-rama-desarrollo` · **Tipo:** estudio de backtests (NO cambia código del repo)
> **Salida:** informe con estadísticas + estrategias guardadas en el baúl + decisión recomendada para operar en real.

---

## 0. Antes de nada (obligatorio, no se salta)

1. Lee `AGENTS.md` entero. Aplica: motor real (`POST /api/backtest` → `run_backtest_orchestrator`), **`look_ahead_prevention: true` en TODAS las corridas**, protocolo **REPORTAR, NO ARREGLAR**.
2. `git branch --show-current` → `alvaro-rama-desarrollo`. No commitear nada salvo este informe y solo si Álvaro lo pide. **Ningún push sin OK explícito.**
3. El backend local debe loguear `GCS sync disabled by environment variable (DISABLE_GCS_SYNC=true)`. Si no aparece → PARAR.
4. **No tocar código del repo.** Todo script va en una carpeta efímera `.tmp_estudio_1b/`. Si el motor no puede expresar algo de este PRD → **parar y decírselo a Álvaro**, nunca aproximarlo con lógica propia.
5. **No tocar la zona del bot de Alertas** (ver `AGENTS.md`).
6. Plantilla útil de cómo lanzar baterías contra el motor real y auditarlas: `.tmp_scalp/bateria.py` (funciones `peticion`, `correr`) y `.tmp_scalp/guardar_ganadoras.py` (guardar vía `POST /api/strategies`). Reutiliza el patrón, no la lógica de trading.
7. Si el backend corre con `--reload`, **no edites `.py` del backend mientras haya una batería en marcha** (reinicia el proceso y mata el trabajo).

---

## 1. Contexto: qué opera Álvaro hoy

Estrategia **«Estrategia 1B – Modelización Sobri 3 + Piramidación Patas»**, `strategy_id = 68a748d5-995e-49b5-ba77-f29f124f7fdc` (copia exportada en `estrategias_compartidas/alvaro/estrategia-1b-modelizacion-sobri-3-piramidacion-pa--68a7.json`, del 2026-09-18).

Resumen de lo que hay en esa definición:

| Bloque | Valor |
|---|---|
| Sesgo / día | short · `gap_day` |
| Universo | PMH Gap % ≥ 50, shortable, excluye dilución |
| Entrada (1m, AND) | Acc. Dollar Volume > 1M · PM High Gap ≥ 50% · **Bar Close ≥ 0,70** · Close ≤ Prev. Bar Low · % Fade (PM, previous_max) < 30 |
| Ventana de entrada | 04:00–08:00 |
| Stop | Market Structure `Previous Max` + 10% |
| Reentradas | sí, máx. 2 |
| Salidas | parciales por hora: **08:15 → 25% · 08:30 → 50% · 08:45 → 25%** · TP final `Hour 09:00` |
| Sesión | `custom` 04:00–08:45 |
| Piramidación | nivel 1 (×1): Close < VWAP a <10% + ≥20 min desde último High PM + Close > EMA10 · nivel 2 (×3): rotura de pivote |

**Sizing que usa Álvaro (CONFIRMADO por él el 2026-09-24): VALOR DE MERCADO, no riesgo.**
El % es **dinero invertido (market value) sobre el equity**, tanto en la entrada como en la piramidación:
- Entrada: **4% del equity en nocional** → petición `risk_type: "PERCENT"`, `risk_r: 4` y en la estrategia `risk_management.size_by_sl: **false**`.
  Motor (`portfolio_sim.py` ~L2352 y ~L2472-2480): `risk_amount = (init_cash + realized_pnl) × 4%` y, sin `size_by_sl`, `size = risk_amount / entry_price`.
- Piramidación: **3% del equity en nocional** → cada nivel con `unit: "pct"`, `capital_pct: 3` y **sin** `size_by_sl` en el nivel.
  Motor (~L2065-2122): `add_cash = (init_cash + realized_pnl) × 3%` → `add_size = add_cash / precio_del_añadido`.
- Total expuesto si piramida: **~7% del equity en nocional**. Lo que se pierde al stop NO es 7%: depende de la distancia al stop de cada trade (Previous Max +10%).
- En ambos casos el equity de referencia es el **realizado** (sin el flotante del trade abierto), y aplica el **tope de caja** (entrada + añadidos ≤ equity al precio de compra).

⚠️ El JSON exportado del 2026-09-18 **no coincide** con esto (`size_by_sl: true` a nivel estrategia y niveles `unit: "usd"`, `capital_pct: 1`). Con `size_by_sl: true` el 4% pasaría a ser RIESGO al stop, que es otra estrategia distinta.

### 1.1 Paso 0 — Reproducir el baseline (checkpoint con Álvaro)

1. Cargar la versión **actual** de la estrategia desde el baúl (`GET /api/strategies/68a748d5-...`), no el JSON exportado.
2. Enseñar a Álvaro, en una tabla, los valores reales de: `risk_type`, `risk_r`, `risk_management.size_by_sl`, y por cada nivel de piramidación `unit`, `capital_pct`, `size_by_sl` del nivel, `times`.
3. Si NO coinciden con lo confirmado arriba (4% MV entrada, 3% MV por nivel, sin `size_by_sl` en ningún sitio) → **parar y preguntar** a Álvaro qué versión es la buena. **Confirmado por Álvaro (2026-09-24):** la versión que opera tiene **UN SOLO nivel de piramidación**, de 3% MV, así que la exposición máxima es **4% + 3% = 7%** cuando piramida (el JSON exportado tenía 2 niveles, uno ×3: no es la versión buena). Verificar que el nivel tiene `times: 1`. Si la estrategia del baúl tiene más de un nivel o `times` > 1 → parar y preguntar.
4. Correr el baseline tal cual y guardar métricas. Es la referencia **B0**.

---

## 2. Campos que el motor rellena si no se dicen (enseñar a Álvaro ANTES de lanzar)

Regla de `AGENTS.md`: todo explícito. Proponer estos valores y **esperar OK**:

| Campo | Propuesta | ¿Afecta? | Nota |
|---|---|---|---|
| `look_ahead_prevention` | `true` | Sí | Fijo, no negociable |
| `init_cash` | **preguntar** (¿tamaño real de la cuenta?) | Sí | Con PERCENT afecta al tope de caja y a los locates |
| `risk_type` / `risk_r` | `PERCENT` / 4 (según variante) | Sí | |
| `fees` / `fee_type` | 0.0005 / `PERCENT` | Sí | Usado en baterías anteriores (5 bps/lado sobre nocional) |
| `slippage` | 0.001 | Sí | **Es fracción**: 0.001 = 0,1% por lado |
| locates (`locates_cost`, `locate_type`) | **preguntar** | Sí | Pesa mucho en sub-$1 (punto 2) |
| `market_sessions` + `custom_start_time`/`custom_end_time` | `["custom"]`, 04:00 / según variante | Sí | Sin decirlo cae en `["RTH"]` y borra el premarket **sin error** |
| `accept_reentries` / `max_reentries` | `true` / 2 (lo que tiene la estrategia) | Sí | El default del esquema es ilimitado |
| `start_date` / `end_date` + `dataset_id` | ver §3 | Sí | |
| what-if (`monthly_expenses`, `extra_slippage`, etc.) | 0 | No en `total_return_pct` | `total_return_pct` NO resta `monthly_expenses` |

Verificar cada default leyendo el orquestador real (puede pisar el default de `run_backtest()`), no solo la firma.

---

## 3. Datos y protocolo anti-sobreajuste

Verificar los IDs contra `GET /api/data/datasets` antes de usarlos:

| Rol | Dataset (según `.tmp_scalp/bateria.py`, 2026-09-18) |
|---|---|
| **IS** (donde se elige) | `c8bcddc7-…` — PMH Gap ≥ 50 · 2025 |
| **OOS-1** (validar) | `d088a358-…` — PMH Gap ≥ 50 · 2024 |
| **OOS-2** (validar) | `e5ca2514-…` — 2025+2026 → usar **solo 2026** (`start_date 2026-01-01`) |

Reglas:
- **Se elige solo con IS.** OOS-1 y OOS-2 se miran al final, una vez, con las finalistas. Si la ganadora IS se hunde en OOS, se reporta tal cual; no se re-optimiza sobre OOS.
- Mínimo razonable: no declarar ganadora una variante cuya ventaja sobre B0 dependa de < 30 trades o de 1–2 días extremos (enseñar el resultado **quitando el top 1% de trades**; el what-if `skip_top_pct` existe).
- Primero se aislan las tres preguntas **por separado** sobre B0 (cambiando una cosa cada vez); solo al final se combinan.

---

## 4. Métricas a sacar de CADA corrida

Tabla común (una fila por variante):

- nº trades, nº días con trade, % acierto
- **Expectancy en R** y **R total** (R = pérdida al stop del nocional de entrada; ver §5.6) y **expectancy en % del equity por trade**
- **Pérdida al stop en % del equity**: media, p95 y máximo (con sizing por MV es el riesgo real)
- PnL neto $, `total_return_pct`, CAGR
- **Max drawdown %** y **duración** del peor DD
- **Return / MaxDD** (MAR) · Sharpe · Sortino · Profit factor
- peor día, peor racha de pérdidas, nº de stops completos
- % de trades en los que el **tope de caja recortó** el tamaño (ver §5, crítico con 7%)
- Monte Carlo (módulo de Robustez, `/api/robustness`, si `ROBUSTNESS_ENABLED=true`): DD p95 y probabilidad de ruina a -30%/-50%. Si el módulo no está activo, decirlo, no inventarlo.

Criterio de decisión principal: **MAR (Return/MaxDD) y DD p95 de Monte Carlo**, no el retorno bruto. Un 7% que gana más pero con el doble de DD no es «mejor».

---

## 5. Punto 1 — ¿Sirve la piramidación o es mejor meter el 7% de golpe?

### Hipótesis
La piramidación solo aporta si **los añadidos tienen expectancy positiva por sí mismos** y/o si concentran el riesgo en los trades que ya van bien. Meter 7% de nocional de golpe expone el 7% también en los trades que nunca habrían piramidado (los que salen mal pronto). Todos los % de esta sección son **valor de mercado sobre el equity realizado** (`size_by_sl: false` en entrada y niveles).

### Variantes (sobre IS, todo lo demás = B0)

| ID | Entrada | Piramidación | Qué responde |
|---|---|---|---|
| **S0** = B0 | 4% MV | 3% MV (como hoy) | referencia |
| **S1** | 4% | **ninguna** | cuánto aporta la pirámide (S0 − S1) |
| **S2** | **7%** | ninguna | la pregunta literal de Álvaro |
| **S3** | X% | ninguna, con X = **nocional medio realmente desplegado por trade en S0** (en % del equity) | comparación justa a igual exposición media |
| **S4** | 5% | 2% | reparto intermedio |
| **S5** | 3% | 4% | más peso en la confirmación |

Para S3: calcular X desde los trades de S0 (nocional de entrada + nocional de los añadidos que sí se ejecutaron, en % del equity de ese momento, promediado sobre todos los trades). Enseñar el número antes de correr.

### Medidas específicas
1. **Expectancy de los lotes de piramidación aislados** (en R y $): si el motor/trades exponen PnL por lote (lot SL/TP ya existen; mirar el payload de trades y `escalera_executions`), usarlo. Si no, aproximar **solo** como diferencia S0 − S1 y decir que es una diferencia, no un dato por lote.
2. **% de trades que piraman** en S0 y su resultado medio vs los que no.
3. **Pérdida real al stop**: con sizing por MV, lo que se pierde en un stop completo = nocional × distancia al stop (Previous Max +10%), y varía mucho entre trades. Reportar por variante la distribución (media, p95, máx.) de la pérdida al stop en % del equity: es el riesgo de verdad que se está comparando.
4. **Tope de caja** (entrada + añadidos ≤ equity): con 7% MV no debería saltar, pero reportar el % de trades recortados por si acaso (y por reentradas: hasta 3 trades por ticker/día).
5. Además del run con `PERCENT` (con interés compuesto, dependiente del camino), correr S0/S1/S2 con **`risk_type: FIXED`** (`risk_r` = 4% de `init_cash` en $ de nocional; añadidos con `unit: "usd"` = 3% de `init_cash`) para separar edge de efecto compounding.
6. **Medir en R**: con sizing por MV el «R» del motor no es un riesgo fijo. Definir R de cada trade = pérdida al stop de su nocional de entrada, y dar la expectancy también en % del equity por trade.

### Salida
Veredicto: «la piramidación aporta / no aporta / aporta pero con más DD», con los números de S0 vs S2 vs S3 en MAR y DD p95.

---

## 6. Punto 2 — Corte de precio: 0,70 $ vs 0,30 $

### Dónde está el corte
No es `universe_filters.min_price` (está a `null`), sino una **condición de entrada**: `Bar Close ≥ 0.7`. Ojo: **los añadidos de piramidación no pasan por esa condición**.

### Variantes (sobre IS, resto = B0)

| ID | Corte |
|---|---|
| **P0** = B0 | Bar Close ≥ 0,70 |
| **P1** | ≥ 0,30 |
| **P2** | ≥ 0,50 |
| **P3** | ≥ 1,00 |
| **P4** | sin corte (control) |

### Medidas específicas
1. Sobre la corrida **P4** (o P1), agrupar los trades por **precio de entrada** en tramos: `<0,30 · 0,30–0,50 · 0,50–0,70 · 0,70–1 · 1–2 · 2–5 · >5`. Por tramo: nº trades, % acierto, expectancy R, PnL, peor trade. (Esto es análisis de trades ya calculados por el motor, no una réplica.)
2. **Estrés de costes en sub-$1** (lo más importante de este punto): en sub-$1 el spread relativo es enorme y un slippage de 0,1% probablemente subestima. Repetir P1 con `slippage` 0,003 y 0,005 (o `extra_slippage` del what-if) y ver si el tramo 0,30–0,70 sigue siendo positivo.
3. **Locates**: con `locate_type PERCENT` o coste por 100 acciones, los sub-$1 exigen muchas más acciones por el mismo riesgo → reportar coste de locates por tramo.
4. **Liquidez real**: nº de acciones que pediría el sizing a 4% vs volumen de la vela de entrada. Si en sub-$1 se piden órdenes de > X% del volumen de la vela (proponer X = 5% a Álvaro), marcarlo como no ejecutable en real.

### Salida
Veredicto: ¿el tramo 0,30–0,70 añade edge **después de costes realistas**? Recomendación de corte.

---

## 7. Punto 3 — ¿Dónde está realmente el edge temporal de la salida?

### Advertencia de configuración (verificar primero)
La sesión es `custom` **04:00–08:45** y el TP final es `Hour 09:00`. Comprobar en el motor qué pasa con posición abierta a las 08:45 (¿cierre forzado de fin de sesión? ¿la hora 09:00 nunca se alcanza?). Para probar salidas después de 08:45 **hay que ampliar `custom_end_time`** en la petición y en la estrategia, o no se verá nada. Reportar lo que se encuentre.

### Fase 3A — Curva de edge por hora (el mapa)
Variantes con **una única salida del 100% a una hora fija**, resto = B0 (stop igual):
`08:00, 08:10, 08:15, 08:20, 08:25, 08:30, 08:35, 08:40, 08:45, 08:50, 09:00, 09:15, 09:25` (+ `09:35` como control post-apertura RTH, avisando que a las 09:30 cambia el régimen de volatilidad).

`custom_end_time` ≥ hora de salida en cada una. Mismas entradas en todas (la ventana de entrada acaba a las 08:00).

Pintar: **expectancy R vs hora de salida**, **MAR vs hora** y **% trades cerrados por stop vs hora** (más tiempo = más stops). El máximo de esa curva es «dónde está el edge».

### Fase 3B — Calendarios de parciales candidatos
Construidos a partir del mapa 3A (no a ciegas). Mínimo:

| ID | Calendario |
|---|---|
| **T0** = B0 | 08:15 25% · 08:30 50% · 08:45 25% |
| **T1** | 08:30 100% |
| **T2** | 08:45 100% |
| **T3** | 08:30 50% · 08:45 50% |
| **T4** | 08:30 25% · 08:40 50% · 08:50 25% |
| **T5** | 08:25 33% · 08:35 33% · 08:45 34% |
| **T6** | centrado en el pico de 3A ±10 min (25/50/25) |

### Robustez del punto 3
- La curva 3A debe ser **suave**: si el «pico» es una hora aislada rodeada de peores, es ruido. Decirlo.
- Repetir 3A en OOS-1 y OOS-2 al final y enseñar si el pico se mantiene en la misma zona.
- Desglosar por **día de la semana** y por **trimestre** solo T0 vs la mejor, para ver si la ventaja es estable.

### Salida
Veredicto: hora/calendario de salida recomendado y si la sospecha de Álvaro (edge entre 08:30 y 08:45) se confirma.

---

## 8. Fase final — Combinar, validar y decidir

1. Tomar la mejor opción de cada punto (sizing, corte, calendario) según IS.
2. Correr **combinaciones** (máx. 8, p. ej. 2 sizings × 2 cortes × 2 calendarios) — hay interacciones (p. ej. un corte más bajo mete trades más volátiles que cambian dónde conviene salir).
3. Finalistas (≤ 3) + B0 → correr en **OOS-1 (2024)** y **OOS-2 (2026)**. Tabla IS vs OOS por finalista.
4. Monte Carlo de las finalistas.
5. Recomendación final con la regla: **se elige la que mejor MAR y DD p95 tenga de forma consistente en IS y en los dos OOS**; si ninguna bate a B0 fuera de muestra, la recomendación es **quedarse con B0** y decirlo sin adornos.

---

## 9. Guardar las modelizaciones (baúl)

Guardar vía `POST /api/strategies` (patrón de `.tmp_scalp/guardar_ganadoras.py`) **solo**: B0 reproducido, la mejor de cada punto, y las finalistas. Nombre:

```
1B-Sobri3 · <ID> · <resumen corto>        ej.  1B-Sobri3 · S2 · 7% entrada sin pirámide
```

En la descripción: qué cambia respecto a B0, dataset IS, métricas clave IS/OOS y fecha. **No modificar la estrategia original `68a748d5-…`**: todas son copias nuevas.

---

## 10. Entregables

1. `docs/INFORME_ESTUDIO_1B_SOBRI3_<fecha>.md` con:
   - resumen de 10 líneas con las tres respuestas y la recomendación final;
   - tablas de §5, §6, §7, §8;
   - gráficos (curva de edge por hora, tramos de precio, equity/DD de finalistas) como PNG en `docs/` o embebidos;
   - lista de todas las corridas con su petición completa (JSONL en `.tmp_estudio_1b/corridas.jsonl`).
2. Estrategias guardadas en el baúl (§9) con sus IDs en el informe.
3. Cualquier cosa rara del motor → **entrada nueva al final de `docs/MEMORIA_MADRE.md`** con el formato de HALLAZGO de `AGENTS.md`, sin tocar código.
4. Entrada en `docs/MEMORIA.md` al terminar.

## 11. Checkpoints con Álvaro (parar y esperar OK)

1. Tras §1.1: tabla del sizing real + respuesta a la duda riesgo-vs-nocional del 3%.
2. Tras §2: tabla de campos por defecto (init_cash, locates, costes).
3. Tras cada punto (§5, §6, §7): tabla de resultados IS + veredicto provisional.
4. Antes de §8.3: lista de finalistas.
5. Informe final.

Avisar antes de cualquier batería de > 1 hora: medir cuánto tarda la corrida B0 y estimar con eso el total (solo §7A ya son ~14 corridas por dataset).
