# INFORME · BLOQUE 2 — Actividad de la víspera (2026-09-25)

> Continuación de `INFORME_BLOQUE1_VELA_VISPERA_20260925.md` con el mismo método
> (deciles con bordes fijos sobre la muestra A completa, curva por año, periodos
> 2019-22 búsqueda / 2023-26 confirmación, aviso de múltiple testing).
> Análisis SOBRE los datos ya extraídos en el Bloque 1 (sin tocar el backend,
> sin backtests nuevos, sin código del repo). Scripts en `.tmp_bloque2/`.

## Tabla-resumen

| Criterio | Veredicto | Dirección (fade) | ¿Aporta sobre 1.6? | ¿Filtrable hoy? |
|---|---|---|---|---|
| 2.1 Volumen víspera ÷ media 20 d (`vol_rel_20`) | ❌ NO SIRVE | plano / sin consistencia (rho ±0,01-0,07, signos mezclados) | NO (parcial ≈ simple, \|ρ\|≤0,03) | Sí técnicamente (`vol_rel_20` ya existe en la API), pero no vale la pena |
| 2.2 Rotación víspera (vol ÷ circulación) | ⏭️ SALTADO | — | — | No: falta `shares_outstanding` (no extraído; pide parar el backend) |
| 2.3 Volumen 3 días previos ÷ media 20 d | ❌ NO SIRVE | plano (igual que 2.1; corr 0,49 con 2.1) | NO | Sí técnicamente, pero no vale la pena |

**Conclusión (3 líneas):** la actividad reciente de la víspera (cuánto se movió
su volumen contra su propia rutina) NO predice el fade del gap ni mejora lo que
ya da el 1.6. El único matiz medido — víspera con volumen alto → neto del día
del gap algo más flojo (D1 −1,1 % vs D10 −4,8 % pooled, 6/8 años negativos,
pero \|ρ\| ≤ 0,06) — no pasa el listón: el fade no lo confirma, los trades no lo
muestran de forma consistente y está dentro de lo que produce el azar con 9+
criterios probados. 2.2 queda pendiente de datos (circulación), sin prisa.

## 1. Definiciones (declaradas antes de mirar resultados)

- Día del gap = D, víspera = D−1. Volumen = **`rth_volume`** (sesión RTH),
  consistente con el marco RTH del Bloque 1. La columna `eod_volume` extraída
  vino entera a 0 (sin uso); variante de robustez con `volume` total del día
  (PM+RTH+post, corr 0,86 con `rth_volume`).
- **2.1 / c21** = `rth_volume[D−1] ÷ media(rth_volume[D−21..D−2])`. La víspera
  NO entra en su propia base (sin look-ahead). Ventana válida con ≥15 de 20 días.
- **2.3 / c23** = `media(rth_volume[D−3..D−1]) ÷ media(rth_volume[D−23..D−4])`
  (numerador y denominador disjuntos).
- **2.2** = volumen ÷ acciones en circulación: **NO calculable** — no extraje
  `shares_outstanding` al lago temporal y extraerlo exige otro ciclo con el
  backend parado (además el hallazgo 07 del 25-sep documenta que suele venir
  NULL en microcaps jóvenes justo en este universo). Se queda pendiente.
- Limpieza: fuera `sin_prev` (sin víspera) y huecos >7 días entre D y D−1.
  Universo A: 13.920 ticker-días (2019-2026). Ventanas rolling SIEMPRE dentro
  del grupo del ticker (corregido un cruce de fronteras del 0,5 % en la v1).

## 2. Vista A — universo (13.920 ticker-días, deciles con bordes fijos)

### 2.1 c21 → `pmh_fade_pct` (primario)

Pooled: D1 29,4 / D10 26,9 — gradiente débil y NO monótono (D8 sube a 28,4).

| Año | rho | D1 | D10 | | Año | rho | D1 | D10 |
|---|---|---|---|---|---|---|---|---|
| 2019 | +0,012 | 17,4 | 19,0 | | 2023 | +0,036 | 29,0 | 27,8 |
| 2020 | −0,039 | 24,3 | 22,9 | | 2024 | −0,018 | 28,6 | 28,5 |
| 2021 | −0,015 | 26,5 | 22,1 | | 2025 | −0,025 | 30,6 | 29,7 |
| 2022 | +0,065 | 21,4 | 24,5 | | 2026 | −0,049 | 32,4 | 29,8 |

Periodos: 2019-22 ρ=+0,001 · 2023-26 ρ=−0,024. **Signos mezclados dentro de
cada periodo → no hay dirección.** La variante con `volume` total (c21v) da lo
mismo salvo 2026 (−0,148, un año, sin gradiente pooled).

### 2.1 c21 → `day_return_pct` (secundario) — la única cosa que "se mueve"

Pooled: D1 −1,1 % → D10 −4,8 % («víspera activa → día del gap más flojo»).
Por año ρ: +0,024 / −0,013 / −0,046 / −0,061 / −0,009 / −0,008 / −0,001 / −0,053
(6/8 negativos, todos |ρ| ≤ 0,06). Periodos: −0,029 y −0,020. Cumpliría la
letra «mayoría de años + ambos periodos», pero: (a) el fade (el resultado que
uso) no lo confirma; (b) magnitudes al nivel del ruido con 9+ criterios
probados; (c) los trades reales no lo enseñan (§3). Se archiva como curiosidad,
no como filtro. Es el mismo patrón que 1.5 (rango) en el Bloque 1: mueve el
neto del día, no el fade, y sin fuerza.

### 2.3 c23 → ambos

Idéntico a 2.1 con menos gradiente (corr c21·c23 = 0,49). Fade: ρ por año entre
−0,045 y +0,044, periodos −0,016/−0,023. Neto: D1 −1,2 → D10 −3,3, sin
monotonía (D8 −4,8 es el mínimo). **NO SIRVE.**

### Aporte sobre 1.6 (el criterio ya construido)

Spearman **parcial** (controlando `lag_day_return_pct_1`) ≈ Spearman simple en
todos los casos — p. ej. c21→fade: simple −0,037, parcial −0,030; por año los
parciales van de −0,044 a +0,067 con signos mezclados. La correlación c21·c16
es 0,086 (casi ortogonales) y aún así el criterio no tiene señal propia.
Condicional (deciles de c21 DENTRO de víspera roja / no roja): plano en roja
(ρ −0,014) y casi plano en no-roja (ρ −0,055, signos mezclados por año).
**Nada por encima de 1.6.**

## 3. Vista B — trades reales (bordes de decil de la muestra A)

| Estrategia | n trades | c21: ρ por año (trade) | c21 pooled / ticker-día | c23 pooled |
|---|---|---|---|---|
| 1B Sobri3 (PM fade) | 4.264 (2024-26) | −0,007 / −0,066 / +0,006 | −0,030 / −0,042 | −0,000 |
| Doble Techo 1 (PM short) | 11.213 | +0,011 / +0,002 / +0,036 | +0,017 / −0,012 | +0,024 |
| 2B RTH (Sailor) | 1.569 | −0,070 / +0,028 / +0,019 | −0,009 / −0,009 | +0,009 |

Deciles planos en las tres (1B: D1 3,3 vs D10 2,2 con D2=4,5 por encima; DT:
1,6 vs 1,5 sin gradiente; 2B: sierra). Condicional roja/no-roja: |ρ| ≤ 0,04 en
todo. En 1B-2025 el D1→D10 cae de 4,75 a 1,73 pero 2024 va al revés y 2026 no
mantiene → no es un corte estable.

## 4. Múltiple testing (acumulado)

Con el Bloque 2 van **9 criterios + 2 variantes** probados (6 del Bloque 1 +
2,1/2,3 + variantes), cada uno contra 2 resultados (fade/neto), en 4 vistas
(A por año, A por periodo, trades, ticker-día). Con n≈14.000, un |ρ| de 0,026
ya es p<0,05: **esperamos varios "significativos" por puro azar**, y de hecho
todos los ρ aquí están en 0,02-0,07 — la firma del ruido, no de una señal. El
listón del Bloque 1 (misma dirección en mayoría de años Y ambos periodos Y en
trades) existe precisamente para filtrar esto: 2.1 y 2.3 no lo pasan.

## 5. Qué haría falta para 2.2 (rotación)

- `shares_outstanding` por ticker-día (o `shares_float`): está en los parquets
  de circulación del lago, NO en `hist_universo`. Extraerlo pide un ciclo con
  el backend parado (como el autorizado del Bloque 1) o el fix del hallazgo 07
  (NaN → 500 en `/api/data/filter`). Nada de esto se ha hecho en este bloque
  (regla de la sesión: no parar el backend).
- Aunque se extraiga: en este universo (microcaps PMH ≥ 50 %) la circulación
  cambia por splits/rS y el hallazgo 25-sep·01 documenta que `prev_close`
  persistida ya hornea splits — habría que decidir la base de acciones con
  cuidado antes de fiar un umbral.

## 6. Detalles de reproducibilidad

- Features: `.tmp_bloque2/paso1_features.py` → `features_b2.parquet`
  (c21 válido 98,4 %, c23 98,2 % sobre 3,6 M filas de historial).
- Vista A: `paso2_vistaA.py` → `resultados_A.txt` (incluye parciales por
  Spearman de rangos con residuos, y condicional roja/no-roja).
- Trades: `paso3_trades.py` → `resultados_trades.txt` (1B desde `vistaB`,
  DT/2B desde los JSON del punto 5 del Bloque 1, mismos de §8/§9 del informe 1).
- Universo A tras limpieza: 13.920 filas (por año: 534/1.709/1.112/1.132/
  1.945/2.551/2.927/2.010).
