# PROXIMOS ITEMS — Guía de pendientes (Álvaro)

> **Qué es este doc:** la lista de bugs a arreglar y features a hacer, con su
> spec técnica lista para ejecutar. Nacido de la auditoría del backtester del
> 2026-08-21.
>
> **Flujo (obligatorio):**
> 1. Cuando un item se **ejecuta**, se **borra de este doc** y se **registra en
>    `docs/MEMORIA.md`** (entrada del día con qué se hizo y dónde se dejó).
> 2. Las ideas sin decisión van a `docs/POSIBLES_ARREGLOS.md`, no aquí. Si se
>    deciden, suben a este doc con su spec.
> 3. Ninguna IA ejecuta nada de aquí por su cuenta: se trabaja cuando Álvaro
>    lo ordena, un item por vez.
>
> **Rama:** `alvaro-rama-desarrollo`. Reglas de la casa aplican (tests primero,
> paridad Python↔JIT, look_ahead_prevention, nunca `main`).
>
> **2026-08-21:** ejecutados ITEM 3 (fix MAX DD $ OOS, commit `5741202`) e
> ITEM 1 (trailing break-even + tests, commit `59a869d`) — ver MEMORIA. La
> spec de ITEM 2 fue corregida con las notas A/B/C de la revisión Claude del
> 2026-08-21 (verificadas contra código por segunda IA). **ITEM 2 sigue POR
> HACER y requiere visto bueno de Álvaro a la spec antes de tocar el motor.**

---

## ITEM 2 — Fix del modelo de comisiones (fees)

**Estado:** POR HACER. Bugs claros encontrados en la auditoría (2026-08-21).
Spec **corregida el 2026-08-21** con las notas A/B/C de la revisión (el `/100`
de PERCENT sobraba, el quirk de parciales es contractual, el relabel FLAT es
obligatorio). **No ejecutar sin orden explícita de Álvaro.**

**Decisión de producto ya tomada por Álvaro:** $ = **por acción**, % = **sobre
la ejecución** (nocional), no sobre la ganancia.

### 2.1 Los dos bugs (anclas)

La fórmula vive en `backend/app/services/portfolio_sim.py:679-685` (cierre
final) y se repite en los 5 bloques de parciales (EOD `:321-324`, TIME
`:373-376`, HOUR `:428-431`, PCT-long `:495-498`, PCT-short `:561-564`), con
copia exacta en el kernel `backend/app/services/portfolio_sim_jit.py:296-299,
340-343, 385-388, 442-445, 496-499, 602-605`:

```python
if fee_type == "FLAT":
    fee_amount = fees * 2                      # ← BUG 1: $ fijos por round-trip
else:
    fee_amount = abs(gross_pnl) * fees         # ← BUG 2: % del PnL, no del nocional
```

- **BUG 1 (`FLAT`)**: cobra `fees×2` fijos por ejecución sin importar el
  tamaño. La doc (`BACKTESTER_BRAIN.md` §5) dice "$/share". 0.01 sobre 3.000
  acciones deberían ser $30 y el motor cobra $0.02.
- **BUG 2 (`PERCENT`)**: cobra % del |PnL bruto|. Un trade plano paga 0, uno
  ganador y uno perdedor pagan distinto según su PnL. Ningún broker cobra
  así: debe ser % del **nocional ejecutado** (precio × tamaño).

### 2.2 Semántica nueva (fijada; con A y B aplicadas)

**Convención de unidades (nota A, crítica):** el frontend YA convierte el
porcentaje a fracción antes de enviar (`BacktestPanel.tsx:688`:
`fees: feeType === "PERCENT" ? fees / 100 : fees`). Al motor `fees` llega
**como fracción** (0.0001, no 0.01). Por eso **NO hay que dividir entre 100**
dentro del motor: dividir cobraría 100× de menos.

- `fee_type="FLAT"`: `fees` = **$ por acción y lado**.
- `fee_type="PERCENT"`: `fees` = **fracción del nocional por lado**.
- El PnL sigue siendo `gross − fee_amount`.
- Modelo **por ejecución (fill)**: cada acción paga la entrada una vez y la
  salida una vez. Los parciales pagan la salida de SUS acciones; la entrada
  de todo el tamaño se paga en el bloque de cierre final.

**Fórmulas exactas por bloque** (para que no haya que improvisar dónde cae el
fee de entrada; `entry_price` y `net_exit` ya son netos de slippage en el
motor):

| Bloque | FLAT | PERCENT |
|---|---|---|
| Cierre final (`portfolio_sim.py:679-685` y espejo JIT) | `fees × (original_size + size)` | `(entry_price × original_size + net_exit × size) × fees` |
| Cada parcial (5 bloques + espejos JIT) | `fees × pt_size` | `net_pt_exit × pt_size × fees` |

- `size` = tamaño restante en el cierre final; `original_size` = tamaño de
  entrada. Σ de todos los bloques = `fees × 2 × original_size` (FLAT) cuando
  todo cierra — cada lado exactamente una vez por acción.
- El reparto de locates NO se toca (`portfolio_sim.py:906` sigue sumando al
  trade final).

**Quirk contractual de parciales (nota B — decisión: MANTENER):** los trades
de parciales **NO llevan clave `fees`** a propósito (`portfolio_sim.py:329-343`,
`sim_dispatch.py:348-351` — comentario "quirk contractual" en código), y el
total reportado (`backtest_service.py:1033`, `t.get("fees", 0.0)`) los excluye
aunque el pnl sí los descuenta. Así se queda: **no** añadir `fees` a los
parciales ni tocar el reporte de totales en este item. Si algún día se quiere
per-fill reporting, será otro item con su propio contrato + actualización de
`test_sim_jit_equivalence.py` (que hoy exige igualdad de dicts exacta).

### 2.3 Plan de implementación

1. **T1 — Tests primero** (`backend/tests/test_fees.py`, nuevo). Recordar:
   `fees` PERCENT llega como **fracción** (nota A).
   - FLAT: 1.000 acciones, 0.01 $/acción, sin slippage → fee total esperado
     $10 entrada + $10 salida = $20 descontados del pnl.
   - PERCENT: fees 0.0001 (0.01%) sobre nocional 10.000 $ → $1 por lado.
   - Parcial de 30% del tamaño → paga el 30% del fee de salida, y el cierre
     final paga la entrada completa + la salida del restante.
   - Parcial sin clave `fees` (quirk B): `assert "fees" not in trade_parcial`.
   - Paridad: mismo caso por `portfolio_sim.simulate` y `sim_dispatch.simulate_jit`.
2. **T2 — Helper único en Python**: extraer `_fee_amount(...)` y usarlo en los
   6 puntos de `portfolio_sim.py` (mata la duplicación).
3. **T3 — Kernel JIT**: portar el helper con el MISMO orden de operaciones FP
   (tol-0). `test_sim_jit_equivalence.py` debe seguir verde.
4. **T4 — Doc y UI**: actualizar `BACKTESTER_BRAIN.md` §5 y los labels de
   `BacktestPanel.tsx:1384`: "Fees ($/share)" / "Fees (% notional)". El
   relabel es **obligatorio**, no cosmético (ver 2.4).
5. **T5 — Suite**: `pytest backend/tests/ -q` ignorando los ya-rotos conocidos
   (ver Backlog; ojo: `test_strategy_api.py::test_create_and_get_strategy`
   falla 422 de forma preexistente, verificado 2026-08-21), + backtest real de
   humo en local comparando totales a ojo.

### 2.4 Impacto y notas (con C aplicada)

- **PERCENT**: rompe compatibilidad con backtests guardados que tuvieran
  `fees > 0` (mismo input, números distintos). Con el default (0.01%) el
  impacto era ~0 y sigue siendo ~0 — cambio de fórmula, no de magnitud.
- **FLAT**: el cambio es de **SIGNIFICADO, no de magnitud** — hoy `fees` es
  "$ por trade" (fijo ×2), pasa a "$ por acción". Un backtest guardado con
  FLAT=1.0 pasa de $2/round-trip a `1 × size × 2` (miles de × en trades
  grandes). Por eso el relabel a "$/share" de T4 es **obligatorio**: sin él,
  el usuario reinterpreta mal un valor viejo.
- **FUERA DE ALCANCE (decisión Álvaro 2026-08-21):** modelar remove/add
  liquidity, ECN fees de SAGEPROL, o comisiones asimétricas SL stop-limit.
  Queda como investigación futura con la fee schedule real del broker; NO
  incluirlo en este item.
- Al ejecutar: borrar de este doc, anotar en MEMORIA.

---

## Backlog CONGELADO — detectado en auditoría, NO tocar por ahora

*Decisiones de Álvaro 2026-08-21: no se usan hoy / no duelen hoy. Se listan
para que no se pierdan; desbloquear solo con orden explícita.*

1. **Look-ahead en indicadores**: `Ret % PM` (PMH final desde las 04:00,
   `indicators.py:1573-1577`), `AM Open` (`:1306-1315`), `Pivot Points` en
   modo `gap_day` (fallback a rth_high/low finales de hoy, `:691-707`),
   `Day Open` (`:1107-1110`), `offset` negativo sin validar (`:849`).
   *Congelado: Álvaro no usa estos indicadores ahora.*
2. **Stop ATR Multiplier con ATR del día completo** (media incluye futuro,
   `strategy_engine.py:1284-1288` y `:716-724`). *Congelado por lo mismo.*
3. **Path paralelo/slab sin agrupar parciales** y sin campos
   prev_max/fade (`backtest_signals.py:839-879,1051` vs
   `backtest_service.py:771`). Tests ya rojos: `test_accum_fast_equivalence`,
   `test_n2a_e2e_equivalence` (×2). *Solo importa si se activan
   `BACKTEST_PARALLEL_WORKERS>1` / `BTT_SLAB_STREAM_ENABLED` en Linux.*
4. **Tests decaídos**: `test_candle_delay` (semántica pre-2026-08-17, cuando
   `look_ahead_prevention` pasó a default True — el motor es el coherente,
   actualizar el test), `test_backtest_engine` + `test_backtest_integration`
   (imports muertos), `test_backtest_golden` (solo servidor),
   `test_prefetch_parity` (migración local). *Arreglarlos la próxima vez que
   se toque el motor, no antes.*
