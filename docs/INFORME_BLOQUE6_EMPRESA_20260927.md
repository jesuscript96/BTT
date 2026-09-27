# INFORME · BLOQUE 6 — La empresa (2026-09-27)

> Método de siempre: tramos declarados, 2019-22 / 2023-26, trades 1B/DT/2B,
> parciales ctrl 1.6+3.2, sin-dato aparte con su retorno, cartera a igual
> riesgo para lo ✅. Todo causal (conocido en la víspera). Datos: circulación
> por informe con fecha (ETL del 2-bis: 48.203 informes), ref_splits (27.239
> splits con execution_date y ratio), ref_tipos (snapshot actual), primera
> fecha del ticker en el lago (proxy IPO). Sin código, sin backtests, sin
> parar el backend. Scripts en `.tmp_bloque6/`.

## Tabla-resumen

| Criterio | Veredicto | Dirección (1B) | ¿Aporta sobre 1.6/3.2? | ¿Filtrable hoy? |
|---|---|---|---|---|
| 6.1 Días desde la IPO (primera fila en el lago) | ✅ SEÑAL PER-TRADE (priorizador; cartera plana) | **recién listado = mucho mejor: <30 d +10,25 %/trade (n=239; ver corrección §8) · 30-90 d +4,83 · >5 y +2,15 (monótono), ρ 3/3 (−0,06/−0,09/−0,07), parcial 3/3**; 2B también 3/3 (−0,07); DT plano. Universo: celda <30 d fade 34,3 % vs ~27 el resto | SÍ (parcial ctrl 1.6+3.2: −0,03/−0,06/−0,06) — eje propio (juventud), no el de 1.6/3.2/2.4 | No (columna derivada de primera fecha; fácil) |
| 6.2 SPAC | ⬜ YA EXCLUIDO DE SERIE | — | — | Ya filtrado por tipo (CS/ADRC/OS): **0 SPAC en el universo A y en los trades**. La regla de Jaume (SPAC pierden: 26 % de los T12) queda como fundamento del filtro existente |
| 6.3 Contrasplit reciente (días desde el último) | 🟡 DUDOSO | reciente → algo más fade en universo (monótono: <30 d 30,4 vs >1 y 26,9; parcial −0,08); trades 1B −0,04 (3/3 flojo), DT +0,01, 2B +0,02 (sin cruzar) | Poco | No (necesita splits con fecha en la query) |
| 6.4 Dilución 3 m / 6 m (crecimiento de shares entre informes) | ❌ NO SIRVE | PLANA en universo (26,1-27,1 en todos los tramos) y trades (ρ ≈ 0) | NO | No |
| 6.5 Tamaño (shares y capitalización de la víspera) | ❌/🟡 DESCRIPTOR | mcap > 200 M$ → fade 21,4 % vs ~27 (A 7/8, parcial −0,07) — pero trades planos/mixtos (1B −0,02, DT +0,06, 2B −0,05) y es el MISMO eje del vol$ del 2-bis (más flojo y con 40-55 % de cobertura) | NO (redundante con 2.4) | No |

**Conclusión (3 líneas):** la única señal del bloque es la JUVENTUD: el
recién listado es el mejor trade de la 1B los 3 años (curva monotónica
+9,96 % → +2,15 %, parcial 3/3, y el 2B lo replica) — cuantifica lo que
Jaume ya midió y explica todos los «sin dato mejores» de los bloques
anteriores (son la cola izquierda de esta curva). Igual que 1.6/3.2/2.5:
discrimina pero la cartera no mejora recortando a los viejos (siguen
siendo +2,2 %), así que su uso es priorizar poder de compra. El SPAC ya
está excluido por el filtro de tipos (0 apariciones); la dilución medida
con informes reales es ruido; el tamaño es el vol$ del 2-bis re-expresado.

## 1. Definiciones (declaradas antes de mirar)

- 6.1 ipo_dias = D − primera fila del ticker en el lago (COTA INFERIOR: los
  listados antes de 2019 aparecen con la edad truncada; quedan en los tramos
  altos, que es donde están de todas formas). Tramos: <30 / 30-90 / 90-180 /
  6-12 m / 1-2 y / 2-5 y / >5 y.
- 6.2 spac = type 'SP' en ref_tipos (SNAPSHOT ACTUAL: caveat — un SPAC
  convertido antes de hoy figura como CS; el filtro de tipos ya excluye SP,
  UNIT, WARRANT, RIGHT, PFD, ETF desde el 6-sep).
- 6.3 csplit_dias = días desde el último contrasplit (split_to < split_from
  en ref_splits) con execution_date ≤ D−1. «Nunca» = grupo aparte.
- 6.4 dil3m/dil6m = shares(último informe ≤ D−1) / shares(último informe ≤
  D−1−90 d/180 d) − 1. **Higiene:** ventanas que cruzan un split → sin dato;
  y crecimiento < −50 % → sin dato (contrasplit no recogido por el ETL de
  splits — 1.217 de 6.721 ventanas lo disparan). Los positivos se quedan
  (dilución real de microcaps, hasta >+2.000 %).
- 6.5 shares = último informe ≤ D−1; mcap_prev = shares × close_1559 de la
  víspera.
- Universo A limpio: 13.920. Controles c16/c32_5 de siempre.

## 2. Vista A — universo

- **6.1:** celda <30 d = fade 34,3 % (n=668) vs 26,8-29,4 el resto; el
  gradiente por encima de 30 d es plano y el ρ por año sale mezclado (+0,12
  en 2019 a −0,09 en 2024-26): la señal es la CELDA, no la pendiente.
- 6.3: monótono suave (30,4 → 26,9), pooled −0,092, parcial −0,083, años
  mezclados (2019-20 positivos).
- 6.4: plano total (26,1-27,1 por tramos; ρ ≈ 0, parcial ≈ 0).
- 6.5: mcap 7/8 negativo (parcial −0,07); el salto está en >200 M$ (21,4 %).
  shares igual pero más flojo.
- 6.2: **0 SPAC de 13.920** (y 0 en los trades): el filtro de tipos ya los
  quita — la medición de Jaume («SPAC pierden; 26 % de los T12») es la razón
  de ser de ese filtro, no un criterio nuevo.

## 3. Vista B — trades

| Estrategia | 6.1 ipo_dias | 6.3 csplit | 6.4 dil3m | 6.5 mcap |
|---|---|---|---|---|
| **1B** | **−0,06/−0,09/−0,07 3/3 · parcial −0,03/−0,06/−0,06 · tramos <30 d +9,96 → >5 y +2,15 (monótono)** | −0,05/−0,05/−0,01 (flojo 3/3) | ≈ 0 | −0,02 (mixto) |
| DT | +0,01 plano | +0,01 plano | ≈ 0 | +0,06 3/3 (leve) |
| 2B | **−0,09/−0,08/−0,06 3/3** | +0,02 mixto | ≈ 0 | −0,05 (2/3) |

**Sin dato (nº y retorno, 1B):** 6.1: NADIE sin dato (primera fecha siempre
existe — el primer criterio con cobertura 100 %). 6.3 «nunca contrasplit»:
1.605 trades **+4,05 %** (mejor que la mediana: los que nunca se contrajeron
están más vivos). 6.4: 2.908 sin informe/ventana (65 %) **+4,16 %** — otra
vez los mejores; 6.5: 2.687 (60 %) similar. Cobertura de circulación sigue
siendo el límite del eje empresa.

## 4. Cartera (igual riesgo total, 1B) — 6.1

Grupo = «viejos» (IPO > 1 año, n=3.482, +2,48 %; jóvenes +5,51 %):

| Escenario | Total (pp) | MaxDD | Calmar | Sharpe |
|---|---|---|---|---|
| todos 1 | 14.134 | −346 | 40,9 | 6,03 |
| todos 0,612 uniforme | 8.644 | −212 | 40,9 | 6,03 |
| todos 1 + viejos a 0,5 | 9.824 | −249 | 39,4 | **6,44** |

Con >2 años: Calmar 35,7. **La cartera no mejora en Calmar** (el grupo
recortado sigue ganando); el Sharpe sube un toque (+7 % con >1 y) — misma
familia que 1.6/2.5/3.2: **priorizador, no exclusión**. Uso natural:
cuando el poder de compra no da para todo, llenar primero los <90 días.

## 5. Múltiple testing (acumulado)

**~32 criterios** acumulados (6 B1 + 5 B2/2-bis + 5 B3 + 7 B4 + 3+1 B5 +
5 B6). El 6.1 pasa 3/3 + parcial 3/3 + replicación en 2B + respaldo externo
(la medición de Jaume) — es la corroboración más sólida posible dentro de
este programa, pero con 32 tiradas y cartera plana se queda en señal, no en
filtro. La dilución (la apuesta teórica del bloque) es la gran ausente: con
informes trimestrales la ventana 3-6 m casi siempre cruza splits u
ofertas y el ruido se come la señal.

## 6. ¿Filtrable hoy?

Nada: 6.1 necesita «primera fecha del ticker en el lago» como columna (o
calcularla al vuelo en el qualifying — es un MIN(timestamp) por ticker,
barato); 6.3/6.4/6.5 necesitan la tabla de splits/circulación con ASOF en
la query (la circulación ya está descargada en
`.cache/intraday/circulacion/`). Si algún día se pide: 6.1 es el único con
señal y es el más fácil de construir.

## 7. Reproducibilidad

- Features: `paso1_features.py` → `features_b6.parquet` (14.028 pares
  universo+trades; ASOF por demanda con searchsorted).
- Vistas: `paso2_vistas.py` → `resultados_A.txt`, `resultados_trades.txt`.
- Parciales por año y cartera del 6.1: impresos en la sesión (en §3-4).
- Higiene documentada: dilución <−50 % = sin dato; ventanas que cruzan
  splits = sin dato; csplit «nunca» = grupo aparte.

## 8. Corrección (28-sep mismo informe) — el tramo «<30 d» subcontado por pd.cut

El bin `(0, 30]` de `pd.cut` EXCLUIA el día 0 (ipo_dias == 0, el día de IPO
pura: 31 trades) — la tabla de §3 decía n=208/+9,96 %. Correcto: **n=239,
+10,25 %** (verificado bit-exacto contra el backtest del filtro construido,
FEATURE 27-sep · FILTRO 6.1 en MEMORIA_MADRE). ρ y parciales no cambian.
