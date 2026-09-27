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
