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

### Bloque 2 — Actividad de la víspera · PENDIENTE
- Volumen de la víspera frente a su media de 20 días (`vol_rel_20`).
- Rotación de la víspera (volumen ÷ acciones en circulación).
- Volumen de los 3 días previos frente a su media (`vol_prev3_rel_20`).

### Bloque 3 — Historial reciente (¿es reincidente?) · PENDIENTE
- Días desde el último gap grande.
- Retorno acumulado de 3, 5 y 10 días.
- Nº de gaps grandes en los últimos 30–90 días.

### Bloque 4 — Dónde está el precio · PENDIENTE
- Cierre de la víspera frente a su máximo/mínimo de 20 días y de 52 semanas.
- Distancia a la media de 20 o 50 días.
- Gap de hoy ÷ volatilidad típica (ATR 14 días). Candidato fuerte.

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
