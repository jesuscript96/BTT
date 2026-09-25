# INFORME · BLOQUE 3 — Historial reciente / reincidencia (2026-09-25)

> Mismo método que los Bloques 1 y 2: deciles con bordes fijos sobre la muestra
> A completa (o TRAMOS para variables de conteo/distancia), curva por año,
> periodos 2019-22 búsqueda / 2023-26 confirmación, trades reales, aviso de
> múltiple testing y prueba de aporte sobre 1.6 (ya construido).
> Solo con los datos extraídos en el Bloque 1; backend intacto, cero código del
> repo, cero backtests. Scripts en `.tmp_bloque3/`.

## Tabla-resumen

| Criterio | Veredicto | Dirección (fade) | ¿Aporta sobre 1.6? | ¿Filtrable hoy? |
|---|---|---|---|---|
| 3.1 Días desde el último gap grande | 🟡 DUDOSO | reincidente reciente → algo MENOS fade, pero concentrado en 2023-26 y los trades lo INVIERTEN | poco (parcial +0,05) | No (necesitaría cálculo nuevo) |
| **3.2 Retorno acumulado 3/5/10 días previos** | **✅ SIRVE** | **venía subiendo → MENOS fade; venía cayendo → MÁS fade** (8/8 años, ambos periodos) | **SÍ — parcial ρ −0,10 con 1.6 controlado, negativo en los 8 años y dentro de cada quintil de 1.6** | No: no existe columna de retorno acumulado N-días en el lago; habría que construirla (decisión de Álvaro) |
| 3.3 Nº de gaps grandes en 30/90 días | 🟡 DUDOSO | espejo del 3.1 (corr −0,43); mismo perfil inconsistente | poco | No (igual que 3.1) |

**Conclusión (3 líneas):** 3.2 es el primer criterio desde el 1.6 que pasa TODAS
las puertas declaradas: mismo signo en los 8 años y en los dos periodos,
magnitud comparable al propio 1.6 (ρ ≈ −0,11) e información INDEPENDIENTE de él
(corr 0,31; controlando 1.6 por Spearman parcial o por quintiles, 3.2 se
mantiene negativo en los 8 años y en los 5 quintiles). En la 1B confirma la
dirección los 3 años (2024 plano, 2025/26 claros: D1 +6,9 % vs D10 +2,3 % en
2025); DT queda sucio y 2B plana, como ya pasaba con 1.6 — el fenómeno sigue
siendo PREMARKET. 3.1/3.3 (reincidencia) se quedan en dudosos: en el universo
apuntan a "reincidente reciente → menos fade" pero el efecto vive en 2023-26 y
los trades de la 1B sacan el signo CONTRARIO — no construir.

## 1. Definiciones (declaradas antes de mirar)

- Día del gap = D, víspera = D−1. Retorno diario OFICIAL `r = close/prev_close − 1`
  con la `prev_close` PERSISTIDA del ETL (splits horneados — hallazgo 25-sep·01;
  así las ventanas de varios días no explotan al cruzar splits). |r| ≤ 500 %
  (higiene), válido el 99,9 % de filas.
- **3.2 / c32_N** = retorno acumulado de los N días ANTES de D (cierre de D−1
  contra cierre de D−1−N, en log-espacio): N = 3, 5, 10.
- **3.1 / c31** = días de COTIZACIÓN desde el último día con PMH Gap ≥ 50
  ESTRICTAMENTE anterior a D (el propio D es gap por definición del universo;
  se excluye). NaN = nunca hubo otro gap grande en el historial del lago.
- **3.3 / c33_W** = nº de días con PMH Gap ≥ 50 en la ventana CALENDAR de W días
  anteriores a D (excluye D). W = 30, 90. Conteos → TRAMOS, no deciles.
- Limpieza: sin `sin_prev`, hueco ≤ 7 días. Universo A: 13.920 ticker-días.
  Ventanas SIEMPRE dentro del grupo del ticker.

## 2. Vista A — universo (13.920 ticker-días)

### 3.2 · retorno acumulado N días → `pmh_fade_pct` (primario)

ρ por año (deciles, bordes fijos sobre A completa):

| Ventana | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 | 19-22 | 23-26 |
|---|---|---|---|---|---|---|---|---|---|---|
| 3 d | −0,063 | −0,060 | −0,069 | −0,085 | −0,044 | −0,099 | −0,090 | −0,175 | −0,063 | −0,106 |
| 5 d | −0,059 | −0,073 | −0,064 | −0,099 | −0,058 | −0,093 | −0,083 | −0,180 | −0,070 | −0,106 |
| 10 d | −0,056 | −0,117 | −0,081 | −0,079 | −0,082 | −0,099 | −0,062 | −0,153 | −0,085 | −0,099 |

**24/24 celdas negativas.** Pooled (5 d): D1 30,6 → D10 25,4, monótono. Para el
neto del día la relación es más floja y se apaga en 2023-26 (como pasaba con
otros criterios: el fade es donde vive la señal).

### Aporte sobre 1.6 — la clave de este bloque

- Spearman **parcial** (ctrl `lag_day_return_pct_1`), ρ por año, ventana 5 d:
  −0,057 · −0,064 · −0,076 · −0,102 · −0,069 · −0,084 · −0,077 · −0,173
  (**8/8 negativos**, pooled −0,104 vs simple −0,112 → casi nada de la señal
  se explica por 1.6).
- Correlación con 1.6: 0,31 (3 d) · 0,31 (5 d) · 0,23 (10 d) — familias
  relacionadas pero no redundantes (la víspera es 1 día de los N).
- Dentro de CADA quintil de 1.6, ρ(5 d → fade): Q1 −0,142 · Q2 −0,100 ·
  Q3 −0,075 · Q4 −0,087 · Q5 −0,145. **Los dos criterios se apilan.**
- Condicional: dentro de roja (c16<0) quintiles de c32_10: 30,5 → 25,7;
  dentro de no-roja: 28,8 → 24,9. Gradiente limpio en ambos grupos.

### 3.1 · días desde el último gap grande (tramos)

Pooled: 1d 25,7 · 2d 26,5 · 3-5d 27,4 · 6-10d 28,0 · 11-20d 28,1 · 21-60d 28,1 ·
>60d 28,6 — gradiente suave "más reciente, menos fade". Pero: 1-2d vs >60d por
año: −1,4 · −1,5 · −1,2 · **+2,8** · −0,9 · −4,7 · −4,6 · −3,6 (6/8) y por
periodo el tramo plano en 2019-22 (23,4 vs 23,5) y vivo en 2023-26 (26,7 vs
30,6). ρ parcial ctrl 1.6: +0,02..+0,10, 7/8 positivo. Dirección consistente
pero débil y cargada al periodo de confirmación.

### 3.3 · nº de gaps en 30/90 días (tramos)

Espejo del 3.1 (corr c31·c33_90 = −0,43). 90 d pooled: 0→28,0 · 1→28,1 ·
2→27,5 · 3-5→27,1 · 6+→24,4; por año ρ parcial 6/8 negativo, otra vez con
2019-22 casi plano (23,5 vs 18,7 con n=5 en 6+) y 2023-26 marcado (30,9 vs
24,8).

## 3. Vista B — trades reales

| Estrategia | c32_5: ρ por año (trade / ticker-día) | lectura |
|---|---|---|
| **1B Sobri3 (PM fade)** | 2024 −0,009/−0,007 · 2025 **−0,067/−0,076** · 2026 −0,033/−0,056 | **confirma**: mismo signo 3/3, 2024 plano; 2025 D1 +6,9 % vs D10 +2,3 %; dentro de roja y no-roja también negativo |
| Doble Techo 1 (PM short) | +0,017..+0,039 (trade) pero ρTD ≈ 0 y deciles D1 2,7 vs D10 1,4 (no monótono) | sucio, sin lectura fiable (le pasaba igual con 1.6) |
| 2B RTH (Sailor) | −0,044..+0.057, pooled ≈ 0 | plana — el fenómeno es premarket, como 1.6 |

3.1/3.3 sobre trades: **contradicen la vista A** — en 1B los tramos de c31 dan
1-2d 3,9 / 3-10d 5,1 / 11-60d 2,2 / >60d 2,1 (los reincidentes rinden MEJOR,
no peor) y c33_90 también sube con más gaps (0→2,3 … 3+→4,0). Con vista A
diciendo una cosa y trades la contraria, y el efecto de A concentrado en
2023-26: **no construir**.

## 4. Múltiple testing (acumulado)

Van **13 criterios + variantes** (6 del B1, 2 del B2, 5 del B3) × 2 resultados
× varias vistas. 3.2 es el PRIMERO desde 1.6 que cruza todas las puertas
declaradas de antemano (8/8 años, dos periodos, parcial sobre lo ya construido,
trades en la estrategia que importa). Eso no lo inmiza del todo: con 13+tiradas
una racha así puede salir por azar, aunque la coherencia económica (gap tras
caída = reversión que se deshace; gap sobre subida = continuación) y la
estabilidad por años apuntan a señal real. Si se construye, recomendaría
vigilarlo en vivo como se hizo con 1.6 (umbral movible, sin corte fijo).

## 5. ¿Filtrable hoy?

**No.** No existe columna de retorno acumulado N-días en `daily_metrics` (las
`m15/m30/m60/m180_return_pct` son del MISMO día) ni en el mapa de métricas del
qualifying. Construirlo sería como el 1.6 pero con ventana: una columna
derivada (p. ej. `ret_cum_5d` computada por el processor o por SQL de ventana
en las tres vías) + entrada en `universoFiltros.ts`. Decisión de Álvaro;
si se pide, se hace en rama con tests y paridad como el filtro 1.6.

## 6. Reproducibilidad

- Features: `.tmp_bloque3/paso1_features.py` → `features_b3.parquet`
  (c32 válido 99-100 %; c31 NaN 24 % del universo = nunca hubo otro gap;
  c33_30 p50 = 0, c33_90 p90 = 1 → tramos).
- Vista A: `paso2_vistaA.py` → `resultados_A.txt` (incluye parciales ctrl c16
  y condicional por quintiles/tramos).
- Trades: `paso3_trades.py` → `resultados_trades.txt`.
- Universo A: 13.920 filas (534/1.709/1.112/1.132/1.945/2.551/2.927/2.010).
