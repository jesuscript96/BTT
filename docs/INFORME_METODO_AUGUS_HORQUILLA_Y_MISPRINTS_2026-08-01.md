# Informe — Método de Augus, la horquilla NBBO y por qué algunos misprints siguen visibles

**Fecha:** 2026-08-01
**Autor:** Adrian Garcia
**Ámbito:** limpieza de misprints del histórico intradía (2022–2026), datos que alimentan charts y backtester.

---

## 1. Resumen ejecutivo

- Desde que adoptamos el **método de Augus** para sanear misprints, el pipeline **reconstruye las velas problemáticas** quedándose **solo con los trades válidos** (dentro de la horquilla NBBO) y **recalcula su volumen**.
- Hemos re-pasado el **mercado completo 2022–2026** (55 meses, 0 fallos) y **activado** el resultado: los **charts** (leen GCS) y el **backtester** (lee el lake local + su copia optimizada) ya sirven el dato re-pasado.
- **El volumen queda muy mejorado** (reducciones del 70–95 % en los ticker-días afectados).
- **Hallazgo importante:** con la **horquilla NBBO ±0,5 % actual**, algunos **picos de PRECIO** siguen apareciendo en charts. El método los considera *válidos* porque el print cae dentro de la horquilla. Esto **no es un fallo del pipeline** — es un **parámetro de calibración de Augus** y solo se resuelve recalibrando la horquilla (o añadiendo una regla relativa al máximo de premarket).
- **Caso testigo:** BQ, 11-sep-2024, 07:01 — `high = 0.5077` mientras las velas vecinas van a 0.37–0.43. El saneador **mantuvo** ese máximo porque está dentro de ±0,5 % del NBBO.

---

## 2. El problema: qué es un misprint

En premarket (04:00–09:30 NY), sobre todo en small/penny caps, aparecen **trades impresos fuera del mercado real** (errores de reporte, cruces raros, ticks sueltos). En una vela de 1 minuto eso produce:

- un **máximo o mínimo falso** (mecha larguísima) que no representa dónde se pudo operar de verdad, y
- **volumen inflado** por esos trades que no deberían contar.

Impacto directo: un backtest en premarket puede **disparar entradas o stops falsos** contra esas mechas, y el chart muestra picos que confunden al cliente.

---

## 3. El método de Augus (la horquilla NBBO)

La idea de Augus es **no borrar velas**, sino **reconstruirlas a partir de los trades válidos**:

1. Para cada minuto problemático se toma la referencia **NBBO** (mejor bid/ask del momento).
2. Se define una **horquilla de tolerancia** alrededor del NBBO: **±0,5 %** → `[bid × 0,995, ask × 1,005]`.
3. Se **descartan** los trades que caen **fuera** de esa horquilla (los misprints).
4. Con los trades que **sobreviven**, se **reconstruye** la vela: `open / high / low / close`, **volumen** (suma) y **transactions** (conteo).

El criterio de "vela problemática" que disparamos es un **spread intrabar** `(high − low) / open × 100 > 5 %` en premarket.

> La **horquilla ±0,5 %** es el parámetro clave y **es responsabilidad de Augus**. Está anotada como **"a recalibrar"** desde la decisión del método.

---

## 4. Qué implementamos nosotros (Opción A)

Sobre el método de Augus, el pipeline hace:

- **Detección** por mes: barre el lake y saca los ticker-días con al menos una vela premarket de spread > 5 % (universo **CS/ADRC**, mercado completo, **sin** filtro de gap).
- **Reconstrucción** (`gen`): sobre las velas marcadas, reconstruye `OHLC` desde los trades NBBO-válidos **y** recalcula su **volumen** y `transactions`. Marca cada vela reconstruida (`vol_recon = True`).
- **Merge quirúrgico**: aplica los cambios **solo** en las velas marcadas; el resto del lake queda **idéntico**. Gates duros abortan si cambian filas, tickers, cobertura, o si se toca alguna vela no marcada.

Esto es exactamente lo que Augus describe como solución: **quedarse con los trades válidos, reconstruir la vela y registrar el volumen limpio** (sin el volumen que aportaban los misprints).

---

## 5. Cronología del trabajo

1. **Re-pase por-gap (Opción A, volumen).** Primer barrido limpiando volumen sobre el universo `gap ≥ 5 %`. Validado en casos como LIFW/RR/WENA/MGOL (−68/−87 % de volumen), quirúrgico.
2. **Hallazgo de alcance (scoping).** El filtro `gap ≥ 5 %` era **una limitación nuestra** ("solo lo que entra en RAM"), **no** parte del método de Augus. Dejaba fuera ticker-días con misprints reales pero **gap bajo** (p.ej. LIFW 2024-07-23 con gap −0,35 %, BQ 2024-09-11 con gap 4,18 %), que **el cliente sí ve** porque los charts sirven el mercado completo.
3. **Re-pase por-spread (mercado completo).** Nuevo pipeline **sin filtro de gap**, mes a mes, con memoria acotada (DuckDB 8 GB). Cubre el mercado entero.
   - Piloto **2024-07** validado: LIFW 1.104.443 → 240.183 de volumen; SLNA 9,5 M → 1,3 M; MAXN 5,7 M → 1,5 M; CNSP 4,89 M → 258.867. Control (RR, ya limpio) **idéntico**.
   - Barrido **completo 2022-01 … 2026-07**: **55 meses, 0 fallos** (~10 h).
4. **Activación.** Subida del raw limpio a GCS (charts) + regeneración de la copia optimizada (backtester), con gates de tamaño/filas. Purga de caché + reinicio de producción. **Todo verde.**

---

## 6. Estado actual — qué está limpio y dónde se ve

| Consumidor | De dónde lee | Estado |
|---|---|---|
| **Charts** | GCS `cold_storage/intraday_1m` (raw) | Sirviendo el dato re-pasado (raw local == GCS, verificado por tamaño) |
| **Backtester** | Lake local + copia `optimized` | Optimized regenerado hoy desde el raw limpio; sin ficheros rancios |

**Volumen:** correcto y muy mejorado en todos los ticker-días afectados.

---

## 7. El hallazgo clave — la horquilla deja pasar misprints de PRECIO

Al verificar los casos reales tras la activación:

**BQ — 11 de septiembre de 2024 (premarket)**

- Velas con spread > 5 %: **32 → 22** (el re-pase sí actuó).
- Volúmenes recalculados a la baja en cada vela (p.ej. 07:00 → 353.934 pasa a 340.572).
- **Pero** la vela de las **07:01** mantiene `high = 0.5077` con vecinas en 0.37–0.43 (**+18/37 %**). La reconstrucción **conservó** ese máximo (0.5077 → 0.5077; volumen solo −2 %).

**Motivo:** ese print de 0.5077 **cae dentro de la horquilla NBBO ±0,5 %**, así que el método de Augus lo trata como **trade válido** y no lo elimina. El chart, por tanto, **sigue mostrando el pico**.

**LIFW — 23 de julio de 2024:** volumen bajó drásticamente (1,1 M → 240 k), pero **14 velas** conservan spread > 5 % (máx 9 %) por el mismo motivo.

---

## 8. Por qué ocurre (mecánica)

El saneador solo descarta lo que queda **fuera** de `[bid × 0,995, ask × 1,005]`. Si durante un movimiento rápido el NBBO se ensancha, o si el propio print anómalo cae dentro de ese ±0,5 %, **el print se considera legítimo**. Resultado: la mecha sobrevive a la reconstrucción.

No hay forma de resolverlo "por otro lado" desde nuestro pipeline sin cambiar el criterio de validez — y ese criterio (**la horquilla**) es **una métrica de Augus**.

---

## 9. Qué depende de Augus

Para que esos picos de precio desaparezcan, hace falta **recalibrar la horquilla** en el lado de Augus. Opciones típicas:

- **Estrechar** la horquilla (p.ej. ±0,2 %) para que prints como el de BQ 07:01 caigan fuera.
- Añadir una **regla relativa al PMH** (máximo de premarket): un print que supere el PMH razonable por encima de X % se marca misprint (regla observada por Jaume: los misprints **no superan** el PMH por más de 1–2 %).

Hasta que Augus decida el ajuste, **el volumen queda saneado** pero **algunos picos de precio permanecerán visibles**.

---

## 10. Recomendación

1. **Mantener** lo activado (volumen saneado, mercado completo) — es una mejora real y ya en producción.
2. **Trasladar a Augus** los casos concretos (BQ 2024-09-11, LIFW 2024-07-23) con estos números para que **recalibre la horquilla**.
3. **No comunicar al cliente** "misprints resueltos" usando BQ 11-sep como ejemplo hasta que la horquilla esté recalibrada, porque **el pico de precio sigue visible**.
4. En cuanto Augus fije el nuevo parámetro, **re-pasar** con esa horquilla (el pipeline ya está listo y es reproducible).

---

*Anexo — parámetros actuales:* `SPREAD_LIMIT = 5,0 %` · horquilla NBBO `±0,5 %` · ventana premarket 04:00–09:30 NY · universo CS/ADRC · Opción A (reconstrucción OHLC + volumen limpio en velas marcadas).
