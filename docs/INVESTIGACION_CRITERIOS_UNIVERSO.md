# Investigación de criterios de universo (stock picking)

> Documento vivo de Álvaro. Se trabaja **bloque a bloque**, uno por sesión.
> Objetivo: encontrar filtros de UNIVERSO (dataset) con edge demostrado y
> reutilizables en varias estrategias. Empezado el 2026-09-25.

## Método (igual para todos los bloques)

1. **Cribado sobre el universo entero, sin estrategia.** Todos los días con
   PMH Gap ≥ 50 % de 2019 a 2026. Se mide si el criterio cambia el
   comportamiento del día del gap (para shorts de fade: cuánto cae desde el
   máximo del premarket).
2. **Segunda mirada con trades reales:** la 1B Sobri 3 (corrida B0), años
   2024, 2025 y 2026.
3. **Umbral movible, no fijo:** se mide el efecto por tramos (deciles). Si
   la curva es estable y va en la misma dirección todos los años, el
   criterio vale como filtro con umbral ajustable. Si solo funciona en un
   corte exacto o en un año, se descarta.
4. **Años fijados antes de mirar:** 2019–2022 para buscar, 2023–2026 para
   confirmar.
5. Solo lo que pase 1–4 se prueba en 2–3 estrategias distintas con el motor
   y, si mejora varias, se construye como filtro en la app.
6. Se registra TODO, también lo descartado (tabla del final).

## ▶ ORDEN DE TRABAJO (reordenado por Álvaro, 28-sep tarde)

1. **AHORA — Línea «Gestión por hora» (1B, genérica):** herramienta
   «a una HORA → si se cumple una CONDICIÓN → haz una ACCIÓN». Primero el
   DATO (combos 08:30/09:00/09:30 × VWAP/camino × cerrar todo/50 %/BE/nada,
   vs salida actual y vs aguantar-todo, por año, con las dos ideas de Álvaro),
   sin tocar código; luego descripción de la pieza que faltaría (PRD a Jaume,
   motor compartido). Informe: §nueva del `INFORME_AGUANTAR_RTH_1B_20260928.md`.
2. **Paquete de filtros para ESTRATEGIAS NUEVAS:** construir como filtros de
   dataset (umbral movible) los criterios con evidencia sólida en el universo
   aunque la 1B no los cobre — vol$ de la víspera, nº de gappers de la
   víspera (día caliente) y mecha superior de la víspera. (Idea de Álvaro: el
   semillero no es «no sirve», es material para diseñar estrategias distintas
   de la 1B.) NO EMPEZAR hasta que Álvaro lo diga.
3. **Hora de inicio del gap (con after-hours) como filtro** (tarea aparte,
   más pesada). NO EMPEZAR sin orden.
4. **Bloque 9 (overhead).**
5. **Bloque 1-bis (premarket de la víspera).**
   — Cerradas ya: Aguantar RTH §A/§B + regla VWAP verificada a mano (28-sep);
   reconciliación 7.2b + invalidación (28-sep, hallazgos 19-22); Bloque 8
   forma de velas (28-sep, sin construcción). (5, 6 y 7 ya están hechos aunque su
   cabecera diga PENDIENTE; ver Registro.)

## Bloques

### Bloque 1 — La vela de la víspera · COMPLETADO 2026-09-25 (umbral movible, 2019-2026 + trades 1B)
| # | Criterio | Qué mide | Dato |
|---|---|---|---|
| 1.1 | Posición del cierre en su rango | (close − low) / (high − low) de la RTH de la víspera. 0 % = cerró en el mínimo, 100 % = en el máximo | diario |
| 1.2 | Fade de la víspera | Cuánto devolvió desde su máximo del día (`rth_fade_pct`) | diario |
| 1.3 | Hora del máximo de la víspera | `hod_time`: subió por la mañana y se desinfló, o apretó al cierre | diario |
| 1.4 | PMH Gap de la víspera | `pmh_gap_pct` del día anterior (¿la víspera ya fue un gap?) | diario |
| 1.5 | Rango RTH de la víspera (umbral movible) | (high − low) / open. Descartado como filtro fijo el 25-sep; se revisa por tramos | diario |
| 1.6 | Neto RTH de la víspera (umbral movible) | (close − open) / open. Descartado como filtro fijo el 25-sep; se revisa por tramos | diario |

**Decisión 2026-09-25:** se construye 1.6 como filtro de dataset «Gap -1 · Day
Return %» (umbral movible), para estrategias de short premarket de fade. En RTH
no aporta (2B de Sailor plana).

**✅ CONSTRUIDO (2026-09-25, commit `f1e401b` en `alvaro-rama-desarrollo`, SIN
push):** `day_return_pct` en `PREV_DAY_LAG_SOURCES` (alias `lag_day_return_pct_1`
en las tres vías: datasets, qualifying local y GCS/Parquet) + UI en dataset
builder, strategy builder y genético, con la etiqueta «Day Return % (RTH, cierre
vs apertura)». Verificado: 22 tests, tsc limpio, paridad motor↔estudio (1502 vs
1507; 5 difs del 31-dic = hallazgo 15, `date_to` exclusivo preexistente) y UI
end-to-end. Detalle en MEMORIA_MADRE (FEATURE 25-sep · FILTRO 1.6).

### Bloque 1-bis — El PREMARKET de la víspera · PENDIENTE (al final, baja prioridad)
Idea de Álvaro (25-sep): lo mismo que el Bloque 1 pero con el premarket del día
anterior (04:00–09:30). Se hace al terminar los demás bloques si da mucho trabajo.
- Rango del PM de la víspera: (pm_high − pm_low). ✅ diario.
- Fade del PM de la víspera: `pmh_fade_pct` del día anterior (PMH → apertura). ✅ diario.
- Neto del PM de la víspera (04:00 → 09:29, rojo/verde). 🕐 necesita velas de 1 min
  (el diario no guarda apertura ni cierre del PM). Aproximación: rth_open de la
  víspera vs su prev_close.
- Volumen del PM de la víspera. ✅ diario.
- Ojo: 1.4 (PMH Gap de la víspera) ya salió ❌ — medir cómo se COMPORTÓ el PM, no
  cuánto subió. Muchas vísperas tienen el PM casi muerto (en 1.4 faltaba el 21 %).

### Bloque 2 — Actividad de la víspera · ✅ CERRADO (25-sep)
- Volumen de la víspera frente a su media de 20 días (`vol_rel_20`). → ❌ NO SIRVE (plano, sin consistencia, sin aporte sobre 1.6).
- Rotación de la víspera (volumen ÷ acciones en circulación). → ⏭️ SALTADO sin datos de circulación (pendiente de extracción con backend parado).
- Volumen de los 3 días previos frente a su media (`vol_prev3_rel_20`). → ❌ NO SIRVE (corr 0,49 con el 2.1, misma nada).

Informe: `docs/INFORME_BLOQUE2_ACTIVIDAD_VISPERA_20260925.md`. Único matiz
medido (archivado como curiosidad, no filtro): víspera con volumen alto → neto
del día del gap algo más flojo (D1 −1,1 % vs D10 −4,8 %, 6/8 años, |ρ|≤0,06) —
el fade no lo confirma y los trades no lo muestran.

### Bloque 3 — Historial reciente (¿es reincidente?) · ✅ CERRADO (25-sep)
- Días desde el último gap grande. → 🟡 DUDOSO (A apunta a «reincidente → menos fade» pero vive en 2023-26 y los trades de la 1B invierten el signo).
- Retorno acumulado de 3, 5 y 10 días. → **✅ SIRVE (el mejor desde 1.6): venía subiendo → MENOS fade; 8/8 años, ambos periodos, parcial −0,10 ctrl 1.6 en los 8 años y en cada quintil de 1.6; 1B confirma 3/3. NO filtrable hoy (falta columna de retorno acumulado).**
- Nº de gaps grandes en los últimos 30–90 días. → 🟡 DUDOSO (espejo del primero, corr −0,43; misma inconsistencia).

Informe: `docs/INFORME_BLOQUE3_REINCIDENCIA_20260925.md`. Pendiente de decisión
de Álvaro: construir el filtro de retorno acumulado (como el 1.6 pero con
ventana N-días, columna nueva en las tres vías).

**Cierre con CARTERA (27-sep, §7 del informe):** el 3.2 también mejora la
cartera de la 1B, no solo el retorno por trade — pesos 1,5/0,5 cae/sube:
total −6 % pero maxDD −16 %, total÷DD 40,9→45,6 (3/3 años). El mismo test
con 1.6 EMPEORA (control, reproduce la prueba manual de Álvaro). Bloque 3
cerrado.

**✅ CONSTRUIDO (2026-09-27):** filtro «Gap -1 · Retorno 5 días % (cierre
víspera vs 5 sesiones antes)» = `lag_ret5d_pct_1` en `qualifying_windows.py`
(definición EXACTA del estudio), en las tres vías y en las tres UIs, con
umbral movible. Verificado con backtest REAL de la 1B: dataset cae 2024-26 →
3.128 pares (estudio: 3.102; dif = corte hueco>7) y 1.374 trades = 1.368 del
estudio + 7 hueco − 1 borde, 0 intrusos. Detalle en MEMORIA_MADRE (FEATURE
27-sep · FILTRO 3.2). Aviso: en la 1B vale como SIZING/prioridad, no como
exclusión («venía subiendo» también gana); DT y 2B no aportaban.

### Bloque 4 — Dónde está el precio · ✅ CERRADO (27-sep)
- Cierre de la víspera vs MÁX/MÍN de 20 y 250 sesiones. → 🟡 DUDOSOS y REDUNDANTES: miden «víspera débil», que ya vive en 3.2 (corr 0,75-0,87; parcial ctrl 1.6+3.2 con signo mezclado 4-5/8).
- Distancia a la media de 20/50 sesiones. → 🟡 igual (corr 0,87 con 3.2).
- Gap de hoy ÷ ATR%14. → **✅ SIRVE (con asterisco): en PM, gap grande en ATRs = trade PEOR (1B D10 −8,7 %/trade, ρ −0,19 3/3; DT −0,16); en RTH (2B) se invierte (+0,10 3/3). Cartera 1B igual riesgo: recortar D8-10 a 0,5 → Calmar 40,9→79,7 y Sharpe 6,0→8,9, 3/3 años. Asterisco: ~2/3 del edge es el gap CRUDO (tope de PMH Gap % filtrable HOY); la normalización ATR añade −0,05..−0,08 (3/3).**

Informe: `docs/INFORME_BLOQUE4_PRECIO_20260927.md`. Pendiente de Álvaro: su
prueba en Portfolio (tope de PMH Gap y/o gap÷ATR como sizing) antes de decidir
si se construye la columna ATR%14.

### Bloque 5 — Entre el cierre y el premarket (necesita intradía) · PENDIENTE
- Movimiento en el after-hours de la víspera.
- Hora a la que empieza a subir en el premarket.

### Bloque 6 — La empresa · PENDIENTE
- Acciones en circulación / tamaño.
- Dilución reciente (crecimiento de acciones en circulación).
- Días desde la IPO y SPAC. **Jaume ya lo midió en staging** (1B y 2B,
  2024–2026: SPAC pierden, IPO recientes son lo mejor de la 1B) → partir de ahí.

### Bloque 7 — El mercado · PENDIENTE
- IWM/SPY de la víspera en rojo o verde.
- Nº de gappers ese día (día caliente o frío).

### Bloque 8 — Forma de las últimas velas (compresión y mechas) · PENDIENTE
Añadido por Álvaro el 2026-09-25. Datos diarios (OHLC), sin intradía.
- **Contracción de volatilidad en los 2-3 días previos**: las velas se van
  estrechando antes del gap. Formas de medirlo: rango de la víspera ÷ rango
  medio de los días −2 y −3; nº de días seguidos con rango decreciente; rango
  de los últimos 3 días ÷ ATR de 14-20 días (compresión tipo NR4/NR7).
- **Mechazos de las últimas velas** (se recupera la idea de la mecha,
  antes descartada):
  - mecha superior ÷ rango total (rechazo arriba: "weak ratio");
  - mecha inferior ÷ rango total (rechazo abajo / compras en el mínimo);
  - mecha ÷ cuerpo, en la víspera y sumado en los 2-3 días previos.
- Ojo, se solapa con el Bloque 1: la posición del cierre (1.1) y el fade (1.2)
  ya miden en parte la mecha superior de la víspera. Medir si aporta algo
  por encima de 1.2/1.6.

### Bloque 9 — Zonas de overhead (resistencia de días anteriores) · PENDIENTE
Añadido por Álvaro el 2026-09-25. Idea: si el gap de hoy sube hasta una zona
donde antes se negoció mucho (gente atrapada arriba que vende al recuperar),
el fade debería ser más fácil; si rompe a "cielo abierto", menos.
- **Distancia a máximos previos**: precio del gap frente al máximo de los
  últimos 20, 60 y 250 días. ¿Se mete DENTRO de una zona ya visitada o la
  supera?
- **Máximo del último runner**: si tuvo un spike en los últimos 30-90 días,
  ¿el gap de hoy llega a ese máximo, se queda por debajo o lo supera?
- **Volumen atrapado arriba**: cuánto volumen se negoció en días anteriores
  por ENCIMA del precio de hoy (perfil de volumen). Aproximable con OHLC +
  volumen diario; exacto con la vela de 1 min (más lento).
- Se solapa con el Bloque 4 (cierre vs máximo de 20 días / 52 semanas): allí
  se mira dónde cerró la víspera; aquí, adónde LLEGA el gap de hoy.
- ⚠️ Look-ahead: el máximo del premarket no se conoce hasta que acaba.
  Medir la zona con el precio disponible en el momento de entrar (o con el
  cierre de la víspera), no con el PMH final del día.

### Descartados sin probar
- (ninguno por ahora; la mecha pasó al Bloque 8)

## Registro de resultados

| Fecha | Criterio | Resultado | Informe |
|---|---|---|---|
| 2026-09-25 | Rango RTH víspera, umbral fijo (<10/15 %) | ❌ Ruido ya en 2025 | `INFORME_RANGO_PREV_RTH_20260925.md` |
| 2026-09-25 | Neto RTH víspera: roja (<0) y ≤ +10 % | ❌ Bien en 2025, no se confirma en 2024/2026 (≤+10 % se invierte en 2026) | `INFORME_RANGO_PREV_RTH_20260925.md` |
| 2026-09-25 | B1·1.1 Posición del cierre en el rango (deciles, 2019-26 + trades) | 🟡 DUDOSO — dirección como el neto (cierre débil → más fade) pero débil y redundante (ρ 0,71 con 1.6) | `INFORME_BLOQUE1_VELA_VISPERA_20260925.md` |
| 2026-09-25 | B1·1.2 Fade de la víspera `rth_fade_pct` (deciles) | ✅ SIRVE — víspera que se desinfla → día más rojo (8/8 años) y mejor short (3/3 en trades) | ídem |
| 2026-09-25 | B1·1.3 Hora del máximo `hod_time` (tramos 60 min) | ❌ NO SIRVE para fade (tramos planos); sólo asoma en day_ret (HOD tarde → día más rojo, 6/8) | ídem |
| 2026-09-25 | B1·1.4 PMH Gap de la víspera (tramos) | ❌ NO SIRVE — sin gradiente; escalón aislado en ≥50 que los trades no replican; 21 % sin dato | ídem |
| 2026-09-25 | B1·1.5 Rango víspera (deciles, umbral movible) | 🟡 DUDOSO — day_ret sí (8/8 años, ρ hasta −0,15), fade premarket NO; añade ~1,2 pp sobre el neto en el cruce 2×2 | ídem |
| 2026-09-25 | B1·1.6 Neto víspera (deciles, umbral movible) | ✅ SIRVE — el mejor: víspera roja → +2-4 pp de fade premarket y short 4-8 % vs 1-3 %; 7/8 años A + 3/3 B; forma segura = keep roja, NO excluir >+10 (se invirtió en 2026) | ídem |
| 2026-09-25 | Punto 5 · 1.6 Neto en 2ª estrategia (Doble Techo 1, PM short) | 🟡 MISMA DIRECCIÓN, más débil: D1>D10 3/3 años y ticker-día 3/3 (ρ −0,04/−0,06/−0,04, pooled −0,05); sin gradiente en deciles medios; el efecto vive en los extremos | ídem §8 |
| 2026-09-25 | Punto 5 · 1.2 Fade en 2ª estrategia (Doble Techo 1) | ❌ Casi plana (ρ ≈ 0 trade-level; ticker-día débil) — no se sostiene fuera de la 1B | ídem §8 |
| 2026-09-25 | Punto 5 · 1.6 Neto en 3ª estrategia (2B RTH de Sailor, RTH short) | ⬜ PLANA — no se invierte, se apaga (ρ +0,05/−0,01/−0,03; roja vs verde +0,3…+1,2 pp = ruido) | ídem §9 |
| 2026-09-25 | Punto 5 · 1.2 Fade en 3ª estrategia (2B RTH) | ⬜ Plana | ídem §9 |
| 2026-09-25 | Punto 5 · DECISIÓN | 1.6 se construye como filtro de umbral movible SOLO para estrategias PM de fade (keep-roja); en RTH no aporta ni perjudica. 1.2 no prosigue | ídem §9.3 |
| 2026-09-25 | B1·1.6 IMPLEMENTADO | ✅ HECHO — «Gap -1 · Day Return %» en las tres vías + tres UIs (commit `f1e401b`, SIN push); 22 tests, tsc, paridad 1502↔1507 (dif = hallazgo 15), navegador e2e | MEMORIA_MADRE (FEATURE 25-sep) |
| 2026-09-25 | B2·2.1 Volumen víspera/20d (deciles, 2019-26 + trades) | ❌ NO SIRVE — plano (rho ±0,01-0,07 signos mezclados); sin aporte sobre 1.6 (parcial ≈ simple) | `INFORME_BLOQUE2_ACTIVIDAD_VISPERA_20260925.md` |
| 2026-09-25 | B2·2.2 Rotación víspera | ⏭️ SALTADO — falta `shares_outstanding` (extracción pendiente con backend parado) | ídem §5 |
| 2026-09-25 | B2·2.3 Volumen 3d/20d | ❌ NO SIRVE — corr 0,49 con 2.1, misma nada; curiosidad archivada: víspera activa → neto del gap algo más flojo (6/8 años, \|ρ\|≤0,06, fade no confirma) | ídem |
| 2026-09-25 | B3·3.1 Días desde último gap (tramos) | 🟡 DUDOSO — «reincidente → menos fade» 6/8 años pero plano en 2019-22; trades 1B invierten el signo | `INFORME_BLOQUE3_REINCIDENCIA_20260925.md` |
| 2026-09-25 | B3·3.2 Retorno acumulado 3/5/10d (deciles) | ✅ SIRVE — 24/24 celdas ρ<0 (8 años × 3 ventanas), ambos periodos; parcial ctrl 1.6 −0,10 en 8/8; quintiles de 1.6 todos negativos; 1B 3/3 (2024 plano) | ídem |
| 2026-09-25 | B3·3.3 Nº gaps 30/90d (tramos) | 🟡 DUDOSO — espejo de 3.1 (corr −0,43), mismo perfil inconsistente | ídem |
| 2026-09-27 | 1.6 en la app, 1B 2025 (1R fijo 1 $): sin filtro / `<0` / `≤5` / `≥5` | Calmar 39,7 / **44,0** / 32,6 / 10,7. Efecto de 2 escalones: roja ~0,10 $/trade, verdes (pequeñas o grandes) ~0,05 $/trade; todas positivas → excluir verdes tira dinero | prueba manual de Álvaro |
| 2026-09-27 | 1.6 para SIZING, 1B 2024→sep-2026, Portfolio (rojas/verdes) | ❌ No mejora: 1/1 Calmar 56,7 · Sharpe 8,54 · DD −4,1 % → 1,2/0,8: 55,8 · 8,52 · −4,4 % → 1,5/0,5: 50,8 · 8,03 · −5,2 %. Más peso a rojas = más agresivo, no mejor (se pierde diversificación con las verdes). **Conclusión 1B: operar todo por igual.** El filtro queda como herramienta para priorizar si falta poder de compra. 34 trades sin víspera (IPO) = 0,26 $/trade, el mejor grupo → Bloque 6 | prueba manual de Álvaro |
| 2026-09-27 | B3·3.2 CARTERA, 1B 2024-26, split cae/sube + pesos 1/1 · 1,2/0,8 · 1,5/0,5 (sizing lineal) | ✅ MEJORA EL RATIO (a diferencia del 1.6): cae 1.368 trades +3,70 %/trade vs sube 2.954 +2,32 % (2024 plano, 2025/26 claros). 1/1: 14.134 pp · DD −346 · ÷DD 40,9 → 1,5/0,5: 13.248 · −290 · **45,6** (+11,6 %, 3/3 años). Total −6 %, DD −16 %: eficiencia de riesgo, no más beneficio. Control 1.6 en la misma base EMPEORA (40,9→36,4), como en la prueba manual. 160 trades sin dato 5d = +13,9 %/trade (eco IPO → Bloque 6) | `INFORME_BLOQUE3_REINCIDENCIA_20260925.md` §7 |
| 2026-09-27 | B3·3.2 CARTERA 4 grupos (1.6 × 3.2) + CIERRE Bloque 3 | Celdas se apilan: roja_cae 910 +4,15 % > roja_sube 1.126 +3,21 % > verde_cae 458 +2,81 % > verde_sube 1.828 +1,77 %. Ningún reparto de la rejilla le gana al tilt global 3.2 1,5/0,5 (÷DD 45,6 vs base 40,9; tilt 1.6 38,9/36,4 pierde; esquinas y solo-rojas 41,5). **Veredicto: 3.2 mejora la CARTERA (ratio 3/3 años) y el trade; B3 CERRADO. Pendiente decisión: construir columna `ret_cum_Nd` (filtro o sizing)** | ídem §7 |
| 2026-09-27 | B3·3.2 IMPLEMENTADO | ✅ HECHO — «Gap -1 · Retorno 5 días %» (`lag_ret5d_pct_1`, definición EXACTA del estudio) en las tres vías + tres UIs, umbral movible. Verificado con BACKTEST: dataset cae 2024-26 = 3.128 pares vs 3.102 del estudio (dif = corte hueco>7 del estudio); 1B real → **1.374 trades** (= 1.368 estudio + 7 hueco − 1 borde, 0 intrusos, WR 65,7 %, +5.206 %). 4 tests nuevos (1.653 OK) + tsc. Aviso: usar como SIZING/prioridad en 1B, no exclusión; DT/2B no aporta | MEMORIA_MADRE (FEATURE 27-sep · FILTRO 3.2) |
| 2026-09-27 | 3.2 en Portfolio (app), 1B 2024→sep-2026 | 🟡 MEJORA MODERADA, sobre todo de drawdown. A (cae/sube, sin los 356 trades sin dato): 1/1 Calmar 40,4 · 1,2/0,8 **47,2** · 1,5/0,5 41,3. B (cartera completa): todos 1 → Calmar 59,5 · Sharpe 8,72 · DD −4,1 % | todos 1,15 (mismo riesgo total) → 66,6 · 8,72 · −4,8 % | **todos 1 + cae 0,5 → 75,0 · 8,61 · −4,4 %**. A igual riesgo, la regla sube CAGR y baja DD (+13 % Calmar) pero el Sharpe no mejora (8,61 vs 8,72): recorta la peor caída, no la volatilidad diaria. Uso: regla de tamaño opcional en la 1B (+50 % a «venía cayendo»), vigilar exposición (35 % vs 32 %). Los 356 trades sin dato 5d son muy buenos: no usar el 3.2 para excluir | prueba manual de Álvaro |
| 2026-09-27 | Opción «si falta el dato: excluir/incluir» en reglas Gap -1 | ✅ HECHO — `missing: "include"` → (cond OR IS NULL) en las tres vías; default excluir BIT-IDÉNTICO (1.374 trades reproducido). En la 1B con incluir: 1.374 + **356 NULL** = 1.730 trades (WR 67,1 %, 0 intrusos). Desglose de los 356: 144 IPO/nuevos +13,1 % · 212 saltos de split sin ajustar +7,7 % — ambos buenos, meterlos todos es correcto. Nota: features_b3 del estudio tenía valor en 203 de los 212 «inválidos» (artefacto del parquet del estudio, no del filtro) | MEMORIA_MADRE (FEATURE 27-sep · MISSING) |
| 2026-09-27 | B4·4.1-4.3 Cierre vs máx/mín 20-250 y SMA 20/50 (deciles, 2019-26 + trades) | 🟡 DUDOSOS Y REDUNDANTES — dirección «víspera débil → más fade» 8/8 en A y 3/3 en 1B pero débil, y NO aportan sobre 3.2: corr 0,75-0,87 con c32_5, parcial ctrl 1.6+3.2 con signo mezclado. Sin dato: 1.497 (20s) / 6.840 (250) en A, +31,8/+29,2 de fade (mejores). No construir | `INFORME_BLOQUE4_PRECIO_20260927.md` |
| 2026-09-27 | B4·4.4 PMH Gap ÷ ATR%14 (deciles, 2019-26 + trades + cartera) | ✅ SIRVE (asterisco) — PM: gap grande en ATRs → trade PEOR: 1B ρ −0,19 3/3, D8-10 (32 % de trades, >7,6 ATRs) **−3,8 %/trade** (D10 −8,7); DT −0,16 3/3; parcial ctrl 1.6+3.2 −0,17..−0,22 3/3. RTH (2B) se INVIETE (+0,10 3/3). CARTERA igual riesgo: todos 1 + D8-10 a 0,5 → Calmar 40,9→**79,7** y Sharpe 6,0→**8,9**, 3/3 años (uniforme no cambia: reasignación pura). Asterisco: ~2/3 del edge es el gap CRUDO (ρ −0,24; tope de PMH Gap filtrable HOY); ÷ATR añade −0,05..−0,08 (3/3); en la vista A el fade lo explica el gap crudo. Pendiente: prueba de Álvaro en Portfolio | ídem |

## Pendientes fuera de la investigación
- Punto 5 CERRADO (25-sep): 1.6 probado en DT (misma dirección, débil — §8) y en la
  2B RTH de Sailor (plana; NO se invierte — §9). Decisión: filtro de umbral movible
  keep-roja SOLO para la familia premarket-fade. ✅ **IMPLEMENTADO** el mismo día:
  `lag_day_return_pct_1` en `PREV_DAY_LAG_SOURCES` de `qualifying_windows.py`
  (commit `f1e401b`, SIN push) — ver «CONSTRUIDO» más arriba.
- ✅ **Creación de datasets en local ARREGLADA** (25-sep, con OK de Álvaro): hallazgos
  11/12 (recursión de la vista `tickers`: duckdb moderno re-resuelve `main.X` dentro
  de la db attachada) → fix con nombre 3-part dinámico, commit `cd180fa` en
  `alvaro-rama-desarrollo` (SIN push). Verificado: dataset de prueba con 303 pares
  vía POST. Detalle en MEMORIA_MADRE 11/12/13 (aviso para Sailor incluido).
- Hallazgo 25-sep·10: en la 1B-Sobri3-B la rama OR de pirámide con `% Fade (ap.RTH)`
  nunca dispara en sesión premarket (siempre NaN). Usar `ap.PM` si se quiere esa rama.
- Informe de papers (otro worker de Claude) → encajar sus ideas en estos bloques.
- Revisar lo que ha subido Jaume a `staging` (~20 commits hasta el 24-sep).
- Hallazgos abiertos en MEMORIA_MADRE: `prev_close` persistida (afecta a PMH Gap %),
  WAL que se rompe en cada reinicio.
| 2026-09-27 | ⚠️ CORRECCIÓN B4·4.4 — look-ahead (hallazgo de Álvaro) | ❌ INVALIDADO — pmh_gap_pct usa el PM completo (04:00-09:29) pero la 1B entra 04:00-08:45: el decil alto contenía los shorts que perdieron POR seguir subiendo (contaminado por el resultado). Remedido con el gap EN EL MOMENTO DE ENTRAR (Current Gap % y PM High Gap % de vela, fórmulas del motor): ρ −0,19 → ≈ 0 (c44 ÷ATR: −0,004/+0,012, parciales ≈ 0) y la relación se INVIETE levemente (entrar con gap vivo enorme es MEJOR: Current Gap>200 = +9,99 %/trade, 3/3 ρ +0,04..+0,08). El tope «PM High Gap ≤ X» NO se prueba: recortaría los mejores trades. 4.1-4.3 y los filtros 1.6/3.2 (datos de D−1) NO afectados | `INFORME_BLOQUE4_PRECIO_20260927.md` §9 |
| 2026-09-27 | B2bis·2.4 Vol$ víspera y 3 días (tramos $, 2019-26 + trades) | 🟡 FUERTE EN UNIVERSO, FLOJO EN TRADES — A 8/8 (ρ −0,11..−0,23, monótono 30,9→19,7 % fade), parcial ctrl 1.6+3.2 INTACTO (−0,21): el eje liquidez-tamaño más fuerte desde 1.6. Pero trades: 1B −0,04 (2/3), DT +0,05 3/3 INVERTIDO, 2B −0,06 3/3 → descriptor de universo, no filtro de la 1B. No filtrable hoy (columna derivada) | `INFORME_BLOQUE2BIS_VOLUMEN_20260927.md` |
| 2026-09-27 | B2bis·2.2 Rotación víspera (vol ÷ shares ASOF; circulación descargada 48.203 informes) | ❌ NO SIRVE — A 7/8 (parcial −0,09) pero al controlar el vol$ DESAPARECE (+0,03; corr 0,55; el vol$ ctrl rotación aguanta −0,19) y 47-48 % sin dato (los sin dato MEJORES: fade +29,2 / 1B +4,58). La circulación queda descargada para Bloque 6 (dilución, tamaño) | ídem |
| 2026-09-27 | B2bis·2.5 Cruce vol × neto víspera («compra fuerte» vs «distribución») | ✅ SEÑAL PER-TRADE (priorizador, no sizing) — «compra fuerte» (verde + vol$>2M) = peor celda de la 1B 3/3 años: +0,89 % vs +3,51 resto; triple con 3.2 (verde×subía×vol$alto) = −0,40 % (n=466). Dirección replica en DT (0,79 vs 1,43) y 2B (2,51 vs 4,94). «Distribución» (roja+vol) NO supera a roja normal. Cartera NO mejora (grupo flojo-positivo; Calmar 39,6→38-39): igual que 1.6, priorizar nunca excluir | ídem §4 |
| 2026-09-27 | B5·5.1 AH de la víspera (cierre→último AH) | ❌ NO SIRVE — pooled −0,08 pero parcial ctrl 1.6+3.2 = −0,02 (vive dentro de 1.6/3.2 y de 5.2: corr −0,61 con la hora del gap); 1B −0,05 parcial 0; 65 % cobertura (microcaps sin AH, sin-dato +2,32) | `INFORME_BLOQUE5_ENTRECIERREYPREMARKET_20260927.md` |
| 2026-09-27 | B5·5.2 Hora del primer +20/50 % (madrugada vs tarde) | ✅ EN UNIVERSO, 🟡 NO ACCIONABLE — gap de madrugada → mucho más fade del DÍA: 8/8 años (ρ −0,09..−0,30, parcial −0,24; 04:00-04:30 ~33 % vs 08:00+ ~24-25 %). Pero causal en trades: 1B plana (entra tan pronto que el 60 % cruza en el primer minuto), DT −0,05 3/3 débil, 2B plana. Descriptivo del día; nada que construir | ídem |
| 2026-09-27 | B5·5.3 Minutos del +50 % a la entrada | ❌ NO SIRVE — 1B ±0,00, 2B flat, DT +0,06 3/3 débil (signos cruzados entre estrategias) | ídem |

## Ideas para estrategias nuevas (semillero de la investigación)

- **Fade en apertura del máximo premarket con hora de inicio del gap (del B5/5.2-bis):** el gap que nace 04:00-06:00 deja ~33 % de fade premarket vs ~24 % el de última hora y ~26 % el que viene del AH de la víspera (8/8 años, parcial −0,21). La 1B no lo puede cobrar (entra demasiado pronto y plana); la forma de cobrarlo es fade TARDE (apertura/RTH contra el PMH). Haría falta el indicador de vela «minutos desde que el PMH cruzó +50 %» (causal, running) o la columna ETL de hora de inicio. `INFORME_BLOQUE5...md` §7.
- **Prioridad de poder de compra contra la celda «compra fuerte» (del B2-bis/2.5):** víspera verde + vol$ > 2 M$ (+ peor si además venía subiendo: −0,40 %/trade) es la peor celda de la 1B 3/3 años y replica en DT y 2B. No mejora la cartera recortándola (sigue positiva): usarla para ORDENAR entradas cuando el capital no da para todo.
- **Sizing por 3.2 (venía cayendo):** ya construido como filtro; su uso validado es sizing/prioridad (Calmar 40,9→45,6 con 1,5/0,5; en Portfolio de Álvaro, «todos 1 + cae 0,5» dio el mejor Calmar).
| 2026-09-27 | B5bis·5.2-bis Hora de inicio del gap (línea continua AH víspera → 09:30) | ✅ EN UNIVERSO (descriptivo del día) — inicio 04-06h → fade PM 32-34 %; tarde 24 %; AH víspera 26,4 % (16 % de los gaps ya cruzaron ayer). ρ 8/8, parcial −0,21. CAUSALIDAD confirmada: 0 trades con cruce tras la entrada. Trades: 1B plana, DT −0,05 3/3 (tarde 0,4 % vs madrugada 2 %), 2B plana. Construcción: columna ETL de minuto del primer cruce o indicador de vela «minutos desde cruce +50 %»; sentido en fades TARDE (apertura/RTH), no en la 1B | `INFORME_BLOQUE5_ENTRECIERREYPREMARKET_20260927.md` §7 |
| 2026-09-27 | B6·6.1 Días desde la IPO (primera fecha en el lago) | ✅ SEÑAL PER-TRADE (priorizador) — curva monótona en 1B: **<30 d +9,96 %/trade · >5 y +2,15 %**, ρ 3/3 y parcial ctrl 1.6+3.2 3/3; 2B replica 3/3; DT plano; universo: celda <30 d fade 34,3 %. Cartera plana (viejos siguen +2,2 %) → prioridad de poder de compra, no exclusión. Cuantifica el «IPO recientes son lo mejor» de Jaume y explica los sin-dato-mejores de todos los bloques. Cobertura 100 % (único criterio sin sin-dato) | `INFORME_BLOQUE6_EMPRESA_20260927.md` |
| 2026-09-27 | B6·6.2 SPAC | ⬜ YA EXCLUIDO — 0 SPAC (type SP) en universo A y trades: el filtro de tipos CS/ADRC/OS los quita de serie. La medición de Jaume (SPAC pierden, 26 % de los T12) queda como fundamento del filtro existente | ídem |
| 2026-09-27 | B6·6.3 Contrasplit reciente | 🟡 DUDOSO — universo monótono (reciente → más fade, parcial −0,08) pero trades flojos y sin cruzar (1B −0,04 3/3 leve, DT/2B ~0). «Nunca contrasplit»: 1.605 trades 1B +4,05 % (mejores) | ídem |
| 2026-09-27 | B6·6.4 Dilución 3/6 m (informes reales con fecha) | ❌ NO SIRVE — plana en universo (26-27 % en todos los tramos) y trades (ρ≈0). Higiene necesaria: ventanas cruzando splits y crecimientos <−50 % = sin dato (1.217/6.721 eran contrasplits no recogidos). 65 % sin dato en 1B (+4,16 %, mejores) | ídem |
| 2026-09-27 | B6·6.5 Tamaño (shares, mcap víspera) | ❌/🟡 DESCRIPTOR — mcap >200 M$ → fade 21,4 % (A 7/8, parcial −0,07) pero trades planos/mixtos y es el mismo eje del vol$ del B2-bis (más flojo, 40-55 % cobertura) | ídem |
| 2026-09-27 | B6·6.1 IMPLEMENTADO | ✅ HECHO — «Días desde 1er día en lago (≈IPO, lago 2019+)» (`days_since_first_day`, DATEDIFF vs MIN por ticker) en las tres vías + UI (GAP DAY); vía GCS amplía la lectura a todo el lago cuando se usa (evita primeras fechas falsas por año). Verificado con BACKTEST: dataset <30 d → 355 pares; 1B real → **239 trades = grupo estudio BIT-EXACTO** (+10,25 %/trade, 0 intrusos). Corrección del informe: <30d era 239 (pd.cut excluyó el día 0). 1.661 tests + tsc. Uso: priorizador, no exclusión | MEMORIA_MADRE (FEATURE 27-sep · FILTRO 6.1) |

## (actualización del semillero tras el Bloque 7)
- **Guarda de mercado para la 1B/DT: «no entrar si ≥10 gaps llevan ya empezados hoy» (del B7/7.2b):** el fade premarket es de quien llega fresco — con ≥10 gaps corriendo, la 1B PIERDE (−1,9 %/trade 3/3, DT replica); recortar ese grupo a la mitad dobla el Calmar (40,9→78,3) y sube el Sharpe un 57 % a igual riesgo. Requiere tabla (fecha, minuto) de «gaps empezados» o market-frame en el motor. `INFORME_BLOQUE7_MERCADO_20260927.md` §4.
- **El día caliente de microcaps (del B7/7.2a):** víspera con >20 gappers → el fade del día sube a 35-40 % (8/8 años, parcial +0,29). Combina con el 5.2-bis: el día caliente + gap nacido de madrugada = el escenario del fade-tarde (apertura/RTH). La 2B ya lo cobra (+0,08 3/3).
| 2026-09-27 | B7·7.1 SPY/IWM víspera (roja/verde, %, 5 días) | ❌ NO SIRVE — roja 28,1 % vs verde 27,6 % (nada); ρ ±0,03 años mezclados; el índice amplio no mueve el fade de microcaps | `INFORME_BLOQUE7_MERCADO_20260927.md` |
| 2026-09-27 | B7·7.2a Nº de gaps de la víspera (día caliente/frío) | ✅ EN UNIVERSO — el criterio de universo MÁS FUERTE del programa: monótono 22,2 % → 39,5 % fade, ρ 8/8, parcial +0,29; 2B lo cobra (+0,075 3/3); 1B solo flojo (+0,07 3/3). Causal puro (víspera) | ídem |
| 2026-09-27 | B7·7.2b Nº de gaps YA EMPEZADOS antes de la entrada | ✅✅ SEÑAL DE TRADE MÁS FUERTE (1B y DT, causal) — ≥10 gaps empezados = PERDER (−1,9 %/trade, 3/3 1B y DT; <3 gaps = +12,8 %); NO es la hora (ctrl −0,23) ni el día (ctrl −0,36, se refuerza); 2B invertida (+0,08 3/3). CARTERA igual riesgo: Calmar 40,9→**78,3** (+92 %) y Sharpe 6,03→**9,46** (+57 %), 3/3 años, grupo NEGATIVO de verdad. No filtrable como dataset (cross-sectional intradía: tabla fecha×minuto o market-frame) | ídem §4 |
| 2026-09-28 | B7·7.2b ROBUSTEZ (antes de construir) | ✅ SOBREVIVE TODO — umbral GRADUAL (meseta 8-12, pico 10); 416/668 días, sin 3/5/10 peores días el efecto intacto (Calmar hasta sube); bootstrap por día: 100 % de iteraciones mejoran Calmar y Sharpe; contador limpio (solo cruces de vela previos a la entrada). GIRO: el daño vive SOLO en entradas tempranas (<05:30: −4,5 %; tardías: +0,3 %) = frenesí nocturno; el proxy a hora fija (05:00/06:00) sale con signo CRUZADO → ninguna vía dataset lo captura; implementación real = tabla (fecha,minuto) + condición de entrada (toca motor compartido: avisar a Jaume) | `INFORME_BLOQUE7_MERCADO_20260927.md` §8 |
| 2026-09-28 | B7·7.2b CONSTRUIDO como indicador «Gappers activos (+X %)» | ✅ HECHO — indicador de vela causal (tabla fecha×nivel×minuto, 206.547 cruces, 9 niveles X movibles, inicial 50), solo aditivo, tras GAPPERS_ACTIVE_ENABLED (OFF por defecto) y sin tocar market_frame/bot. No-regresión BIT-IDÉNTICA (hash 0401ce44); backtest real con OR(Gappers+50<10, Range≥90): 3.541 trades (−941 vs 4.482), WR 66,4 %, DD −10,5 %, ret/trade +3,36 % (el Σtotal baja vs el skip puro del estudio porque el OR re-admite desde las 05:30 — decisión de diseño, no fallo). 1.667 tests + tsc | MEMORIA_MADRE (FEATURE 28-sep · GAPPERS) |
| 2026-09-28 | B7·7.2b INVALIDADO (reconciliación trade a trade) | ❌ ERA UN ARTEFACTO — el n_gaps_pre del estudio estaba contaminado (colisión de minuto de entrada: reentradas/DT/2B pisaban el minuto de la 1B; 56,6 % de trades inflados +3,45 de media). Con contador LIMPIO: bloqueados 304 Σ+627 (+2,06 %/trade) vs resto +3,23 % — **sin edge**; con el del motor: 532 Σ+798 (+1,50 %) — tampoco. Backtest real de la guarda OR(Gappers+50<10, **Time of Day≥330**): 4.265 trades (−217), Σ +518 pp netos que salen de la CASCADA (entrar más tarde), no de podar perdedores — los 119 borrados eran ganadores (Σ+2.053, +17 % medio). Reconciliación EXACTA: −[1]+[2]+[3] = +518,16 = ΔΣ. De paso: 2 bugs de MI generator corregidos (tabla 216.102 cruces, cruces bit-idénticos al estudio) y «Range of Time» NO es hora de reloj (cuenta desde la 1ª vela). El INDICADOR «Gappers activos» sigue siendo válido y causal; la REGLA umbral-10 no | `INFORME_BLOQUE7_MERCADO_20260927.md` §10 · MEMORIA hallazgos 19-21 |
| 2026-09-28 | Línea «Aguantar en RTH» (1B, 4.482 trades 2024-26, % camino = precios, hold 08:45→11:00 simulado con velas) | ✅ CON REGLA — (A) NO hay corte por «% camino a las 08:30»: lo muy recorrido (<−100) es lo MEJOR de aguantar (−11 camino pp, 2 % stops) y el daño vive en camino>0 (22-58 % stops); el discriminador real es el **precio vs VWAP del premarket** (≥VWAP: efecto +1,3/+0,4 y 27-42 % stops → NO aguantar; ≤−4 % bajo VWAP: −6,5 y ~6 % stops). Regla: aguantar solo si ≤VWAP−4 % (+IPO<365 d blinda 2026, único 3/3): misma Σ que aguantar-todo con la MITAD de stops (5,8 % vs 11,6 %) — el DD−7,6 % de Portfolio es sizing-$, la regla ataca su causa (frecuencia de stops). (B) Peor 10 % (448, 444 stops): **PMH +166 % vs +96 %, vol$ 3,4 M vs 6,0 M, víspera RTH +17 % vs +10 %, entrada <04:30 y piramidando**; exclusión «pmh≥200 % ∨ (≥150 % ∧ vol<5 M$)» quita 997 trades que pierden solos −54,5 R (3/3 años) — in-sample, confirmar. Gappers/contador: sin separación (re-invalida 7.2b) | `INFORME_AGUANTAR_RTH_1B_20260928.md` |
| 2026-09-28 | Línea «Aguantar en RTH» · §B CORRECCIÓN look-ahead (hallazgo 18, detectado por Álvaro) | ❌ LA EXCLUSIÓN «MONSTER-GAP» ERA UN ARTEFACTO — el PMH FINAL lo empujan los perdedores al subir hasta el stop (peor10 +166 % vs +96 %) y «piramidó» es post-entrada. Re-hecho SOLO con lo conocido al minuto de entrada: el PMH ACUMULADO hasta la entrada del peor10 es +87,5 % vs +84,5 % (NADA; el tramo causal ≥200 % es de los MEJORES, +0,146 R) y NINGUNA exclusión causal quita un grupo perdedor (todas +16..+87 R fuera). Lo que sobrevive: concentración en vol$<3 M$ a la entrada (45 % del peor10 vs 33 %), víspera RTH ≥+40 % (38 % vs 31 %), 1ª entrada <04:30 — gradiente causal de edge +0,025 R (celda fina-fuerte) → +0,070 R (vol≥20 M$): usar como TAMAÑO/prioridad, no exclusión. La Parte A (VWAP a las 08:30) no cambia: ya era causal | `INFORME_AGUANTAR_RTH_1B_20260928.md` §B (corregido) |
| 2026-09-28 | B7·7.2b VERIFICACIÓN FINAL (pedido de Álvaro) | ❌ NO SOBREVIVE — el estudio NO tenía el bug AH/PM (14.388/14.388 cruces IDÉNTICOS a la tabla corregida; su única contaminación fue la colisión de minuto del hallazgo 19). Re-derivado con contador limpio: bloqueados 304 Σ**+627** (+2,06 %/trade, signo cruzado por año: +1,3/−1,3/+5,6 %); NINGÚN umbral da grupo perdedor (curva +2 a +4,3 %); buckets <3:+6,3 % / ≥10:+2,8 % (gradiente suave, sin acantilado); cartera: el skip contaminado reproduce el Calmar ×2 (32→62) pero el skip limpio EMPEORA el Calmar 2/3 años. El Calmar ×2 publicado era 100 % artefacto. Indicador construido queda disponible (flag OFF) sin regla con edge | `INFORME_BLOQUE7_MERCADO_20260927.md` §11 |
| 2026-09-28 | Regla VWAP aguantar-RTH · verificación MANUAL vela a vela (lección de los 3 falsos) | ✅ EL CÁLCULO ES FIEL — 19/19 trades recalculan IDÉNTICO (Δ=0.000: VWAP, precio 08:30, camino, stop del hold, efecto); stop estático confirmado (S=PMH_ent·1,10 en 96 %), 0 velas duplicadas (6,7 M), precio fresco (99 % vela en 08:30, 95 % en 11:00) y el edge NO vive en trades rancios (frescos n=2.344: efecto −6,0, 5,8 % stops). NO prueba que gane ejecutada: falta backtest en la app (salida condicional → motor compartido → Jaume). Estado: prometedora, cálculo limpio, sin verificar en app | `INFORME_AGUANTAR_RTH_1B_20260928.md` §Verificación manual |
| 2026-09-28 | B8·8.1-8.2 Forma de las últimas velas (solo víspera: compresión rango÷rango, racha estrechando, 3d÷ATR14-20; mechas sup/inf÷rango, mecha÷cuerpo, 1d y media 2-3d) | ❌ SIN CONSTRUCCIÓN — compresión: NADA (comp1 2/8 años; comp3_atr 7/8 pero ρ≈−0,03; racha 4/8). Mecha inferior: NADA. **Mecha superior víspera: descriptor de universo DÉBIL** (ws1 7/8 años —solo 2021 en contra—, buscar +0,02→confirmar +0,06, parcial +0,067 ctrl 1.6/3.2/6.1, deciles monótonos fade 25,4→31,4 %: víspera con rechazo arriba → al día siguiente más fade) que NO se cobra: 1B plano/ruido (parcial +0,011, mitades cruzan signo por año) y 2B inconsistente (2024 al revés, 2025 plano, 2026 sí). Features verificadas 6/6 a mano del OHLC crudo; reglas fijas aplicadas (solo ≤D-1, dedup, un trade una fila) | `INFORME_BLOQUE8_FORMA_VELAS_20260928.md` |
| 2026-09-28 | Línea «Gestión por hora» (1B, hora×condición×acción, 9.812 filas trade×hora) | ✅ LA HORA ES LAS 08:30 — a 09:00 débil, a 09:30 nada (decidir tarde = no decidir). Celdas afiladas 08:30: «a favor pero sobre VWAP» cerrar −9,1 camino pp (n=128); Álvaro-(i) sobre-VWAP→BE −6,0 (n=214). Cartera (1R lineal, else=aguantar a 11:00): todas las políticas VWAP ≈ +315 R 3a (vs current 295,3 / hold 313,6; entre sí ruido) — lo que cambian es el RIESGO: P4 (≥4 % bajo VWAP o cierra) baja stops 403→138 (−66 %) con 72 % exposición; P3 (sobre-VWAP cierra) −47 %; P2/BE (i) convierte paradas en scratches; P1 quirúrgica (128 disparos, +19,8 R). **Álvaro-(ii) descartada** (−5,6 vs hold: los 0-15 % a favor aguantan mejor). Verificado 20/20 adversarial a mano. Pieza nueva para la app: «salida programada condicional» (hora+condición+acción sobre la posición) — motor compartido, PRD a Jaume | `INFORME_AGUANTAR_RTH_1B_20260928.md` §Gestión por hora |
| 2026-09-28 | PAQUETE ESTRATEGIAS NUEVAS (ORDEN §2): filtros de dataset «Vol $ víspera» (2.4), «Gappers víspera» (7.2a) y «Mecha sup. víspera» (B8) — umbral movible, tres vías, sin-dato:incluir | ✅ CONSTRUIDOS — mismos nombres de app: **«Vol. $ víspera (cierre×vol RTH)» (lag_volusd_1)** · **«Gappers víspera (nº con PMH≥50 %)» (lag_gappers_prev_1)** · **«Mecha superior víspera (% del rango)» (lag_wick_sup_1)**, en la sección Gap −1 del builder de universo. Antes de gappers: 7.2a verificado INMUNE a la colisión del 7.2b (60/60 idénticos — es lookup por fecha, nunca minutos de entrada). Semánticas documentadas (gappers cuenta el lago entero y hereda último día con gappers en días a cero). Verificación: dataset PMH≥50+3 reglas (vol$≥2 M · mecha≥40 % · gappers≥20) → **203 pares = SUBCONJUNTO EXACTO** del esperado-del-lago (226; los 23 fuera: 9 por el filtro de tipo por defecto warrants/ETF/ADRC/PFD + 14 ticker-días con divergencia tabla-local vs lago, preexistente). **1B real sobre el dataset: 147 trades, Σ+568,5 pp, +3,87 %/trade** (baseline 3,15 %; 2026 +6,38 %). No-regresión B0 BIT-IDÉNTICA (4.482). Tests +8 (combinación de las 3 incluida — pilló un bug real de pisado del FROM al-vuelo). Suite 1.683/0 · tsc limpio | MEMORIA_MADRE (FEATURE 28-sep · PAQUETE ESTRATEGIAS NUEVAS) |
| 2026-09-28 | ORDEN §3 · Filtro «Hora de inicio del gap» (5.2-bis: t del primer cruce +X % en línea continua 16:00 víspera→09:30, AH incluido) | ✅ CONSTRUIDO — en la app: **«Hora inicio gap +20 %» / «Hora inicio gap +50 %» (gap_start_min_20/50)**, sección día del gap, umbral movible sobre t (780 = antes de las 05:00; tabla de conversión en la descripción) y «sin dato: incluye». Fuente: pivote gap_start.parquet (74.355 ticker-días) que escribe el MISMO script del indicador Gappers activos (regeneración documentada). Tres vías vía LEFT JOIN gateado + guard del hot-cache. Aviso en la UI: sin look-ahead SOLO entrando tras el cruce (ej. exigiendo PMH Gap ≥ X en la vela). Verificación: manual 24/24 desde velas crudas (mi primer verificador tenía un bug — contaba la tarde del día D como víspera; los lunes heredan la semántica calendar del estudio); dataset PMH≥50+≤780 → 3.347 pares SUBCONJUNTO EXACTO del esperado (0 intrusos; 184 fuera = divergencia local/lago preexistente); **1B real: 2.710 trades, +2,98 %/trade** (baseline +3,15 % — plano, como el estudio decía de la 1B; la señal vive en fades TARDE). No-regresión B0 BIT-IDÉNTICA. Suite 1.688/0 · tsc 0 | MEMORIA_MADRE (FEATURE 28-sep · HORA INICIO GAP) |
