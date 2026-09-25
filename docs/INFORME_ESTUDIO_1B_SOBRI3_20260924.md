# Informe — Estudio 1B · Modelización Sobri 3: sizing, corte de precio y horario de salidas

> **Fecha:** 2026-09-24 · **Pide:** Álvaro · **Ejecuta:** GLM (ZCode) · **Rama:** `alvaro-rama-desarrollo`
> **PRD:** `docs/PRD_ESTUDIO_1B_SOBRI3_SIZING_PRECIO_SALIDAS_20260924.md`
> **Motor real** vía `POST /api/backtest` (jobs) · `look_ahead_prevention: true` en TODAS las corridas.
> Selección solo con IS 2025; 2024 y 2026 usados una única vez al final.

> ## ⚠️ NOTAS OBLIGATORIAS DE LECTURA
>
> **«Resultados sin costes (fees, slippage, locates = 0): el tramo de precio < 1 $ está sobreestimado.»**
>
> **«PENDIENTE: estudio de buying power de Sage sobre la ganadora (cortos ≥ 2,50 $ al 25 % del valor, < 2,50 $ al 100 %), para ver si cabría en real. La exposición simultánea máx llega al 150-270 % del equity.»**

---

## 0. Resumen (10 líneas)

1. **Sizing — la pirámide se queda.** 4 % MV de entrada + 3 % MV de añadido gana en riesgo-ajustado al 7 % de golpe y al nocional plano equivalente, en 2025 **y en los dos OOS**. Los añadidos tienen expectancy positiva por sí mismos (+4,6 % por cada 300 $ desplegados).
2. **Corte de precio — bajar a 0,30 $ gana en los tres años** (más retorno, menos DD, mejor MAR), pero es exactamente el tramo que el estudio de BP de Sage puede tumbar: la decisión final queda pospuesta a ese estudio.
3. **Salidas — el edge temporal está en 08:25→08:40** (hasta +3.654 $ por cada 5 min de aguantar). La sospecha «entre 08:30 y 08:45» se confirma afinada: 08:30→08:40 muy positivo, 08:40→08:45 ligeramente negativo, después meseta sin edge hasta la apertura.
4. **El calendario exacto no es la palanca**: todos los calendarios que no venden antes de las 08:30 empatan (MAR 69-73). T3 (08:30 50 % · 08:45 50 %) se elige **por simplicidad**, no por rendimiento.
5. **Ganadora: C4** (corte 0,30 + T3) — mejor que lo de hoy en MAR, DD **y** retorno en los tres años. **Plan B si el BP castiga el sub-1 $: C2** (0,70 + T3) o **C1** (lo de hoy) si no se quiere tocar el calendario.
6. Monte Carlo por días: DD p50 ≈ −5 %, cola p95 ≈ −10 %, peor camino −21/−23 %, ruina a −30/−50 % ≈ 0 %. Sin separación material entre finalistas.
7. El salto post-apertura (salida única 09:35) se repite en 2024 (mejor de la tabla) pero **no** en 2026: mixto, no candidata.
8. La exposición simultánea pica a 150-270 % del equity — es la razón del estudio de BP pendiente.
9. Todo medido en frame FIXED (400 $ entrada + 300 $ añadido, sin compuesto) para que los años sean comparables; para operar en real: `risk_type PERCENT, risk_r 4` + pirámide `pct/3`.
10. Estrategia original `5ed17d89` intacta; guardadas como copias nuevas C1, C2, C4, C5 (IDs en §6).

---

## 1. Metodología

- **Motor real**, sin réplicas: cada corrida es un job del orquestador con **todos** los campos explícitos (incluido `size_by_sl: false`, que es OR con la estrategia y la plantilla antigua de `.tmp_scalp` llevaba `true` — habría convertido el 4 % en riesgo al stop).
- **Sin costes** en todas las corridas: `fees=0`, `slippage=0`, `locates_cost=0` (decisión de Álvaro, 2026-09-24). El motor tampoco modela comisión mínima por orden (verificado: solo `%` del nocional o `$/acción`).
- **R del PRD** (todas las tablas): pérdida al stop de **todos los lotes desplegados** (entrada + añadidos) = Σ lotes `size×|precio−stop|`, con el stop estructural (Previous Max +10 %) anclado a la entrada. En % del equity realizado del momento. *La «R» del motor es otra cosa: con MV sizing, `r_multiple = pnl / nocional de entrada* (`backtest_service.py:651-654`).
- **Bitácora por lote**: el motor la sirve en `executions[]` por trade (entrada, añadidos, parciales, cierre, con hora/precio/tamaño). Los trades cerrados por SL antes del primer parcial no llevan la clave (pierna única); su nocional desplegado es exacto vía `size × avg_entry_price`.
- **Datasets** (verificados contra `GET /api/data/datasets`): IS `c8bcddc7` (2025, 3.103 pares) · OOS-1 `d088a358` (2024, 4.200) · OOS-2 `e5ca2514` recortado a 2026-01-01→07-30. El motor aplica además su universo (fuera warrants/ETF y precio < 0,1 $): IS efectivo 3.008 pares.
- **Peticiones completas auditables** en `.tmp_estudio_1b/corridas.jsonl` (49 corridas registradas con su JSON de petición, job_id, duración y métricas).

### Corrección previa (checkpoint 1)

La estrategia del baúl (`5ed17d89`, actualizada el 23-sep) tenía el nivel de pirámide en `unit: "usd", capital_pct: 1` → el motor añadía **1 $ fijos**, no 3 % MV. Corregido a `unit: "pct", capital_pct: 3, times: 1` (diff completo verificado: solo esos dos campos cambiaron; backups en `.tmp_estudio_1b/backup_5ed17d89_antes|despues.json`). La UI pinta exactamente lo guardado («Añade 3% del equity», por valor de mercado, ×1) — sin hallazgo.

---

## 2. Punto 1 — ¿Piramidar o meter el 7 % de golpe?

**Veredicto solo con corridas FIXED** (el MAR compuesto distorsiona: en compuesto S2 aparenta ganar). FIXED: entrada 400 $ + pirámide 300 $ (usd), sin compuesto.

### IS 2025

| | S1-F · 4 % | S0-F · 4+3 | S3-F · 574,49 $ (= X real de S0-F) | S2-F · 7 % |
|---|---|---|---|---|
| Retorno | +336,9 % | +482,8 % | +483,8 % | +589,5 % |
| Máx DD | −6,69 % | −7,29 % | −8,50 % | −9,55 % |
| MAR | 50,3 | **66,2** | 56,9 | 61,7 |
| Exposición máx | 199 % | **150 %** | 214 % | 221 % |
| R PRD % (media/p95, con adds) | 0,53/1,18 | 0,71/1,79 | 0,64/1,55 | 0,71/1,82 |

- **A igual nocional medio** (S3-F = 574,49 $, el despliegue medio real de S0-F): mismo retorno con menos DD y mejor MAR → **el timing del añadido aporta** (concentra tamaño en los trades que van bien; 58,2 % piramidan).
- Expectancy de los añadidos aislados (valorados al VWAP de salida de su trade): **+4,6 % por cada 300 $**; en S0-F los adds aportan 14.594 $ y las entradas cuadran al dólar con S1-F (33.689 $) — validación interna del método.
- El 7 % de golpe compra +107 pp de retorno con +2,3 pp de DD y +71 pp de exposición pico.

### Validación OOS (pedida por Álvaro; corte 0,70 + T0 como en el punto 1)

| | 2024 ret / DD / MAR | 2026 ret / DD / MAR | Exp máx 24/26 |
|---|---|---|---|
| S0-F (4+3) | +295,4 % / −7,68 % / 38,5 | +353,7 % / −5,89 % / 60,0 | 157 % / 135 % |
| S3-F (574,49 $) | +317,2 % / −8,80 % / 36,1 | +358,1 % / −7,04 % / 50,9 | 217 % / 181 % |
| S2-F (700 $) | +386,5 % / −10,33 % / 37,4 | +436,4 % / −8,42 % / 51,9 | 227 % / 188 % |

**Se mantiene fuera de muestra:** la pirámide gana a igual nocional medio en MAR y DD en los dos OOS (2024: 38,5 vs 36,1 y −7,7 vs −8,8; 2026: 60,0 vs 50,9 y −5,9 vs −7,0), con bastante menos exposición pico, a retorno igual o similar. El 7 % de golpe sigue comprando retorno con claramente más DD.

**Conclusión punto 1: pirámide 4+3 (cerrado).**

---

## 3. Punto 2 — Corte de precio 0,70 vs 0,30

FIXED 400+300, IS 2025. P0 = corte 0,70 (hoy).

| Corte | Trades | Retorno | Máx DD | MAR | PF |
|---|---|---|---|---|---|
| ≥ 1,00 | 1.690 | +450,7 % | −6,33 % | 71,2 | 1,676 |
| **≥ 0,70 (hoy)** | 1.831 | +482,8 % | −7,29 % | 66,2 | 1,669 |
| ≥ 0,50 | 1.966 | +521,0 % | −5,89 % | 88,4 | 1,675 |
| ≥ 0,30 | 2.152 | +554,3 % | −5,81 % | **95,4** | 1,647 |
| sin corte | 2.331 | +595,7 % | −6,71 % | 88,7 | 1,638 |

Tramos de entrada (sobre la corrida sin corte; expectancy en R del PRD con adds):

| Tramo | n | WR | Exp R | PnL | % pirámide |
|---|---|---|---|---|---|
| < 0,30 | 189 | 63,0 % | 0,072 | +4.738 $ | 65,6 % |
| 0,30-0,50 | 188 | 58,5 % | **0,042** | +2.912 $ | 60,1 % |
| 0,50-0,70 | 133 | 63,9 % | 0,099 | +3.310 $ | 57,9 % |
| 0,70-1 | 143 | 66,4 % | **0,119** | +4.132 $ | 58,7 % |
| 1-2 | 363 | 70,2 % | 0,083 | +11.016 $ | 68,0 % |
| 2-5 | 659 | 64,8 % | 0,082 | +18.049 $ | 58,3 % |
| > 5 | 656 | 60,1 % | 0,044 | +15.415 $ | 52,6 % |

En muestra y sin costes **todos** los tramos son positivos y el corte de 0,70 quita 321 trades (0,30-0,70) que suman +7,2 k$ bajando el DD. La decisión se pospone al estudio de BP: con SageTrader, un corto de 0,50 $ exige 2,50 $/acción = **500 % del nocional** de margen — ver nota obligatoria de cabecera. P0 y P1 pasaron a la fase final (C1/C2 vs C3/C4).

---

## 4. Punto 3 — Dónde está el edge temporal de la salida

### Advertencia verificada

Con sesión custom hasta 08:45, a las 08:45 cierra por EOD y el TP «Hora 09:00» nunca se alcanza: cada variante posterior llevó `custom_end_time = hora+1min` **en petición y definición**. La pirámide solo puede dispararse dentro de la ventana de entrada (04:00-08:00 inclusive: 1.065 añadidos, 8 exactamente a las 08:00) → sin mezcla de efectos en la curva ≥ 08:00.

### Fase 3A — curva por hora de salida única (FIXED 400+300, IS)

| Hora | PnL | Exp R | MAR | Máx DD | % SL | **PnL marginal /5 min** |
|---|---|---|---|---|---|---|
| 08:00 | 39.764 | 0,0427 | 48,9 | −8,14 | 25,0 | — |
| 08:10 | 43.211 | 0,0561 | 52,2 | −8,28 | 25,6 | +1.724 |
| 08:15 | 43.613 | 0,0573 | 56,9 | −7,67 | 25,9 | +402 |
| 08:20 | 44.542 | 0,0589 | 57,8 | −7,71 | 26,3 | +929 |
| 08:25 | 45.716 | 0,0621 | 64,3 | −7,11 | 26,7 | +1.174 |
| 08:30 | 48.334 | 0,0695 | 67,7 | −7,14 | 26,9 | +2.618 |
| **08:35** | 51.988 | 0,0810 | **72,7** | −7,15 | 27,0 | **+3.654** |
| **08:40** | **52.815** | **0,0823** | 72,0 | −7,34 | 27,3 | +827 |
| 08:45 | 52.118 | 0,0797 | 71,6 | −7,28 | 27,5 | **−697** |
| 08:50 | 52.772 | 0,0808 | 70,2 | −7,52 | 27,7 | +654 |
| 09:00 | 52.136 | 0,0800 | 67,4 | −7,73 | 28,2 | −318 |
| 09:15 | 52.872 | 0,0814 | 80,5 | −6,57 | 28,5 | +245 |
| 09:25 | 53.200 | 0,0797 | 72,7 | −7,31 | 28,7 | +164 |
| 09:35 | 59.292 | 0,0942 | 82,1 | −7,22 | 29,5 | +3.046 |

Gráfico: `docs/3A_edge_por_hora_20260924.png` (PnL/expectancy, marginales, %SL).

**El edge está en 08:25→08:40**; 08:40→08:45 ligeramente negativo; después meseta ruidosa. El salto 09:25→09:35 cruza la apertura RTH (régimen distinto; control únicamente).

### Fase 3B — calendarios (mismas 1.831 entradas)

| Calendario | Ret | DD | MAR |
|---|---|---|---|
| **T0 = hoy (08:15 25 · 08:30 50 · 08:45 25)** | +482,8 % | −7,29 % | 66,2 |
| T1 · 08:30 100 % | +483,3 % | −7,14 % | 67,7 |
| T3 · 08:30 50 · 08:45 50 | +501,6 % | −7,11 % | 70,5 |
| T5 · 08:25 33 · 08:35 33 · 08:45 34 | +499,0 % | −7,15 % | 69,8 |
| T6 · 08:25 25 · 08:35 50 · 08:45 25 | +503,7 % | −7,15 % | 70,5 |
| T4 · 08:30 25 · 08:40 50 · 08:50 25 | +514,4 % | −7,24 % | 71,0 |
| Salida única 08:35 | +519,9 % | −7,15 % | **72,7** |

**Conclusión calendario: el edge NO está en el calendario — basta con no vender antes de las 08:30.** Todos los calendarios que cumplen eso empatan (MAR 69-73); el T0 actual se vacía justo antes del mejor tramo. **T3 se elige por simplicidad, no por rendimiento** (0,5 MAR de diferencia con T4 no es significativa con un solo año).

---

## 5. Fase final — combinaciones IS vs OOS (sin margen)

Configuración común: FIXED 400+300 $ · sin costes · `look_ahead_prevention: true`. **Mejor por columna en negrita** (entre candidatas C1-C5).

### IS 2025

| Var | Retorno | Máx DD | MAR | PF | Trades | Exp máx %eq |
|---|---|---|---|---|---|---|
| C1 (hoy: 0,70+T0) | 482,8 % | −7,3 % | 66,2 | 1,669 | 1.831 | 149,8 % |
| C2 (0,70+T3) | 501,6 % | −7,1 % | 70,5 | 1,684 | 1.831 | 149,7 % |
| C3 (0,30+T0) | 554,3 % | −5,8 % | 95,4 | 1,647 | 2.152 | 154,9 % |
| **C4 (0,30+T3)** | **571,2 %** | **−5,8 %** | **99,0** | 1,653 | 2.152 | 155,7 % |
| C5 (0,70+T4, ref) | 514,4 % | −7,2 % | 71,0 | **1,696** | 1.831 | **148,7 %** |
| CTRL 09:35 (no cand.) | 592,9 % | −7,2 % | 82,1 | 1,725 | 1.831 | 106,3 % |

### OOS 2024

| Var | Retorno | Máx DD | MAR | PF | Trades | Exp máx %eq |
|---|---|---|---|---|---|---|
| C1 | 295,4 % | −7,7 % | 38,5 | 1,531 | 1.392 | 157,2 % |
| C2 | 302,2 % | −8,6 % | 35,0 | 1,528 | 1.392 | 158,3 % |
| C3 | 341,9 % | **−5,4 %** | **63,5** | 1,497 | 1.674 | 167,5 % |
| **C4** | **352,0 %** | −5,9 % | 59,4 | 1,499 | 1.674 | 168,1 % |
| C5 | 315,3 % | −8,5 % | 37,0 | **1,548** | 1.392 | **156,3 %** |
| CTRL | 407,9 % | −5,1 % | 79,4 | 1,628 | 1.392 | 113,0 % |

### OOS 2026 (ene-jul)

| Var | Retorno | Máx DD | MAR | PF | Trades | Exp máx %eq |
|---|---|---|---|---|---|---|
| C1 | 353,7 % | −5,9 % | 60,0 | 1,866 | 1.041 | 135,1 % |
| C2 | 361,5 % | −5,6 % | 64,9 | 1,876 | 1.041 | 135,1 % |
| C3 | 382,7 % | −4,7 % | 80,7 | 1,749 | 1.263 | 144,2 % |
| **C4** | **391,1 %** | **−4,4 %** | **89,2** | 1,758 | 1.263 | 144,1 % |
| C5 | 366,0 % | −5,1 % | 72,0 | **1,886** | 1.041 | **134,9 %** |
| CTRL | 342,1 % | −5,4 % | 63,1 | 1,729 | 1.041 | 105,4 % |

### Monte Carlo por días (bootstrap de días enteros, 5.000 sims, 3 años agrupados, aditivo)

| Var | días | DD p50 | DD cola p95 | DD cola p99 | DD peor | Ruina −30 % | Ruina −50 % | Ret p50 |
|---|---|---|---|---|---|---|---|---|
| C1 | 642 | −5,1 % | −10,2 % | −13,7 % | −21,0 % | 0,00 % | 0,00 % | +1.131 % |
| C2 | 642 | −5,1 % | −10,1 % | −13,8 % | −20,7 % | 0,00 % | 0,00 % | +1.165 % |
| C4 | 645 | −5,0 % | −10,0 % | −13,7 % | −23,1 % | 0,00 % | 0,00 % | **+1.315 %** |

Notas de semántica (verificadas en `robustness_mc.py`): los percentiles del DD van con signo — **la cola mala es `dd_tolerance.p95` (percentil 5 real)**, que es lo que muestra la tabla; `prob_ruin_pct` mide tocar `init_cash×(1−x)` **desde el arranque** (no desde el pico corriente), por eso un peor camino de −21 % en DD puede coexistir con ruina 0 %. El bootstrap por días preserva el clustering intradía (el anterior, por trades, lo diluía).

### Veredicto (regla de Álvaro: mejor o igual que C1 en MAR y DD en los TRES años)

- **¿T3 bate a T0 en 2024 y 2026? No de forma consistente**: en 2024, C2 es peor que C1 en MAR (35,0 vs 38,5) **y** DD (−8,6 vs −7,7). Dentro del corte 0,30, C4 vs C3 también queda repartido (C3 mejor en 2024, C4 mejor en 2026 e IS). **La diferencia de calendario no es robusta año a año.**
- **¿El corte 0,30 bate al 0,70 en 2024 y 2026? SÍ, en ambos y con los dos calendarios** (más retorno, menos DD, mejor MAR).
- **¿El salto de la apertura (CTRL) se repite OOS? Mixto**: 2024 sí (mejor de toda la tabla), 2026 no (peor retorno de todas y MAR por debajo de las candidatas). Solo informativo.
- **Ganadora por la regla: C4** (estrictamente mejor que C1 en MAR, DD y retorno los tres años). C3 también pasa la regla pero **no cubre el riesgo del sub-1 $** (también lleva corte 0,30) y no aporta nada frente a C4 salvo el calendario.

### Recomendación

- **Principal: C4** (corte 0,30 + T3), **pendiente del estudio de buying power de Sage** — el tramo 0,30-0,70 $ es justamente el que puede no caber con cortos < 2,50 $ al 100 % del valor.
- **Plan B si el BP castiga el sub-1 $: C2** (0,70 + T3), o **C1** (lo de hoy) si se prefiere no cambiar el calendario.
- Sizing para operar: **PERCENT 4 % MV + pirámide pct/3 MV** (cerrado en punto 1); el frame FIXED fue solo el marco de medición.

---

## 6. Estrategias guardadas en el baúl (copias nuevas; `5ed17d89` intacta)

| ID | Nombre |
|---|---|
| `8e4f648a-b334-4d55-923c-c4e949579cbd` | 1B-Sobri3 · C1 · hoy · corte 0,70 · T0 (08:15/30/45 25-50-25) |
| `ff96e0c4-d1bc-41f8-a185-c49e3028e2f6` | 1B-Sobri3 · C2 · corte 0,70 · T3 (08:30/45 50-50) |
| `70dcb6e3-de29-43b8-8596-2350cd69779b` | 1B-Sobri3 · C4 · GANADORA · corte 0,30 · T3 (08:30/45 50-50) |
| `3595c470-d2af-45a3-8bfb-560c7d680f6c` | 1B-Sobri3 · C5 · ref · corte 0,70 · T4 (08:30/40/50 25-50-25) |

Las copias llevan la pirámide en `pct/3` (configuración real de operación); las métricas de sus descripciones son las del frame de estudio FIXED 400+300 sin costes. Finales de sesión verificados contra las corridas (re-verificación de Álvaro): **C1 `08:45`** (réplica de hoy: el 25 % restante lo cierra el EOD), **C2 y C4 `08:46`** (para que el parcial de las 08:45 dispare en su vela — con 08:45 lo anticipaba un minuto: +250,27 $ y −0,17 pp de DD en IS), **C5 `08:51`** (parcial a las 08:50).

## 7. Limitaciones y notas metodológicas

1. **Sin costes** (decisión de Álvaro): sin fees, slippage ni locates; el sub-1 $ está sobreestimado (nota de cabecera). El motor soporta `fee_type FLAT` ($/acción a dos lados) pero **no** comisión mínima por orden.
2. **Sin margen/BP**: la exposición simultánea máxima llega al 150-270 % del equity según variante y año — el estudio de Sage BP sobre la ganadora queda **pendiente** y puede invertir la decisión del corte.
3. **MC por días**: bootstrap sobre los 642-645 días con trade (los días sin trade no entran en el remuestreo); cota de DD razonable pero optimista frente a un año con más días perdidos encadenados.
4. La R del PRD incluye los lotes de añadido (decisión de Álvaro en revisión): no comparar `R_exp` entre variantes con y sin pirámide (unidades distintas).
5. `executions[]` solo existe en trades multi-pierna (parciales); para el resto, nocional desplegado exacto vía `size × avg_entry_price`.
6. Un despiste propio, documentado: en la fase final de IS, C1/C2/C5/CTRL reutilizan corridas previas idénticas (S0-F, 3B-T3, 3B-T4, 3A-H0935) — definiciones replicadas campo a campo, no re-corridas.

## 8. Auditoría

- 49 corridas registradas con petición completa: `.tmp_estudio_1b/corridas.jsonl` (tags B0, S1-S5, S0-F/S1-F/S2-F/S3-F, P1-P4, 3A-H…, 3B-T…, FF-IS/24/26-…, FF-24/26-S0F/S2F/S3F, B0-1d-*).
- Resultados crudos por corrida: `.tmp_estudio_1b/resultados/<tag>.json`.
- Backups de la corrección del baúl: `.tmp_estudio_1b/backup_5ed17d89_antes|despues.json`.
- Gráfico 3A: `docs/3A_edge_por_hora_20260924.png`.
- **Hallazgos de motor reportados a MEMORIA_MADRE: ninguno.** (La ausencia inicial de `pyr_executions` resultó ser un rename a `executions[]` del agrupador, no un bug.)
