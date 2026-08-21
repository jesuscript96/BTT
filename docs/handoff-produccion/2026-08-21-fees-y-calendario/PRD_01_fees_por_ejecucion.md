# PRD 01 — Comisiones por ejecución (fill), no por trade

> **Para:** Edgecute (motor/backend). **De:** Álvaro. **Fecha:** 2026-08-21.
> **Anclas verificadas sobre:** `develop` @ `e368839`.
> **Tipo:** fix de motor. **Prioridad:** alta — el cálculo de comisiones es
> incorrecto hoy para cualquier usuario con `fees > 0`.
> **Implementación de referencia:** commit `77236d2` en `alvaro-rama-desarrollo`
> (testeada: 6/6 tests nuevos + 28/28 paridad JIT). Parche en
> [`reference/fees-por-ejecucion.patch`](reference/fees-por-ejecucion.patch) y
> test ejecutable en [`reference/test_fees.py`](reference/test_fees.py).

---

## 1. El problema (lenguaje de usuario)

Hoy el motor trata **un trade como si fuera una sola ejecución** y calcula la
comisión con dos fórmulas rotas:

1. **FLAT**: `fee_amount = fees * 2` — una cantidad **fija por trade** que no
   depende del tamaño. Una posición de 10 acciones y una de 1.000 pagan **lo
   mismo**. En la realidad el broker cobra $/acción ejecutada.
2. **PERCENT**: `fee_amount = abs(gross_pnl) * fees` — un porcentaje del
   **PnL bruto** del trade. Un trade que cierra plano paga **0 comisión**
   (imposible: por entrar y salir ya se ejecutaron órdenes).

Además, un trade real son **varias ejecuciones** (entrada, N parciales,
cierre): cada una debe pagar su comisión de su lado correspondiente.

**Impacto para clientes:** cualquier backtest con `fees > 0` muestra costes
de transacción irreales. Con FLAT, los tamaños grandes salen gratis; con
PERCENT, los trades planos salen gratis.

## 2. Anclas en `develop` @ `e368839` (verificadas)

- **Motor Python** — `backend/app/services/portfolio_sim.py`, 6 puntos de
  cálculo, todos con el par:
  - `fee_amount = fees * 2` (líneas **243, 295, 350, 397, 440, 556**)
  - `fee_amount = abs(gross_pnl) * fees` (líneas **245, 297, 352, 399, 442, 559**)
  - El trade guarda el fee en `"fees": round(fee_amount, 4)` (línea **575**).
- **Kernel JIT (Numba)** — `backend/app/services/portfolio_sim_jit.py`: los
  mismos pares en **279/281** y **323/325** (buscad todos con
  `grep -n "fees \* 2\|abs(gross" backend/app/services/portfolio_sim_jit.py`;
  el kernel y `sim_dispatch.py` deben recibir el mismo tratamiento).
- **Frontend ya envía `fees` como fracción en PERCENT** —
  `frontend/src/components/backtester/BacktestPanel.tsx:688`:
  `fees: feeType === "PERCENT" ? fees / 100 : fees`.
  **El motor NO debe dividir entre 100**: le llega la fracción ya calculada.

> Si `develop` avanzó desde `e368839`, re-localizad por expresión
> (`fees * 2`, `abs(gross_pnl) * fees`), no por número de línea.

## 3. Modelo objetivo (spec)

### 3.1 Fórmulas por ejecución (fill)

| Tipo | Significado nuevo de `fees` | Fee de un fill |
|------|------------------------------|----------------|
| `FLAT` | **$ por acción y lado** | `fees × qty` (acciones de ese fill) |
| `PERCENT` | **fracción del nocional por lado** | `precio_neto × qty × fees` (llega ya como fracción: sin `/100`) |

### 3.2 Qué paga cada ejecución

- **Cierre final del trade**: paga la **entrada de TODO el tamaño**
  (`original_size`) + la **salida del tamaño restante**. Es decir, el fee de
  la entrada no se cobró al entrar: se cobra al cerrar (junto con la salida).
  - FLAT: `fees × (original_size + size_restante)`
  - PERCENT: `(entrada_neta × original_size + salida_neta × size_restante) × fees`
- **Cada parcial**: paga **solo su salida** (la entrada ya se cobró en el
  cierre final sobre `original_size`).
  - FLAT: `fees × size_del_parcial`
  - PERCENT: `salida_neta_del_parcial × size_del_parcial × fees`

### 3.3 Estructura de código

- Helper único en Python:
  `def _fee_amount(fee_type: str, fees: float, qty: float, notional: float) -> float`
  → `FLAT: fees * qty`, `PERCENT: notional * fees`. Sustituye los 6 puntos.
- Puerto al kernel: `_fee_amount_jit(fee_type_code, fees, qty, notional)` con
  **el mismo orden de operaciones en coma flotante** (paridad Python↔JIT
  bit-idéntica, tolerancia 0 — regla de la casa del motor).

### 3.4 Quirks que hay que PRESERVAR (no tocar)

Verificados como comportamiento contractual del resto del sistema:

1. **Los dicts de trades parciales NO llevan clave `fees`** (los agregados del
   backend excluyen su fee a propósito; tocarlo rompe consistencias asumidas).
2. El trade total no añade fee adicional fuera del modelo por-fill.
3. **Locates intactos**: `t["fees"] = round(t.get("fees", 0.0) + daily_locates_fee, 4)`
   (`portfolio_sim.py:736`) se queda como está.

### 3.5 UI (relabel obligatorio — FLAT cambia de significado)

`BacktestPanel.tsx` (buscad `Fees {feeType === "PERCENT" ? "(%)" : "($)"}`):

```diff
- Fees {feeType === "PERCENT" ? "(%)" : "($)"}
+ Fees {feeType === "PERCENT" ? "(% notional)" : "($/share)"}
```

y las `<option>` del selector: `%` → `% notional`, `$` → `$ / share`.

## 4. Plan atómico

- **T1** — Copiar `reference/test_fees.py` a `backend/tests/test_fees.py`.
  Correrlo: debe estar **ROJO** con el motor actual (especificación ejecutable).
- **T2** — Implementar `_fee_amount` en `portfolio_sim.py` y sustituir los 6
  puntos (§2) según §3.1–3.2. `test_fees.py` verde (casos Python).
- **T3** — Puerto `_fee_amount_jit` en `portfolio_sim_jit.py` (+ puntos
  equivalentes) con mismo orden FP. Verde el caso de paridad JIT de
  `test_fees.py` (usa `sim_dispatch.simulate_jit`).
- **T4** — Correr `backend/tests/test_sim_jit_equivalence.py` completo
  (existe en `develop`): paridad general sin regresión.
- **T5** — Relabel de UI (§3.5) + `tsc --noEmit`.

## 5. Tests de aceptación (ya escritos en `reference/test_fees.py`)

1. FLAT con cierre completo: fee exacto `fees × 2 × size`.
2. PERCENT con cierre completo: fee exacto sobre nocional entrada+salida.
3. **Trade plano (pnl 0) paga su fee** — mata el bug de `abs(gross_pnl)`.
4. Parciales FLAT: el total cuadra entrada (`original_size`) + salidas.
5. Parciales PERCENT + quirk: parciales sin clave `fees`.
6. Paridad Python↔JIT bit-idéntica.

Verificación adicional recomendada (la que hice yo): humo con ~34 trades /
~1.400 acciones — FLAT $0.01/share debe dar fee total ≈ `$0.02 × acciones`
exacto; PERCENT 0.01% ≈ `0.0002 × nocional`.

## 6. Definition of Done

- [ ] `test_fees.py` 6/6 verde sobre el motor de `develop`.
- [ ] `test_sim_jit_equivalence.py` sin regresiones.
- [ ] Ni rastro de `fees * 2` ni `abs(gross_pnl) * fees` en el motor ni el kernel.
- [ ] Relabel de UI desplegado con `tsc --noEmit` limpio.
- [ ] Quirks §3.4 intactos (locates, parciales sin `fees`).

## 7. Riesgos y rollout

- ⚠️ **BREAKING en FLAT**: el significado pasa de $/trade a **$/share**.
  Backtests guardados con FLAT > 0 darán números muy distintos (correctos,
  pero distintos). El relabel de UI lo hace visible; recomendable nota de
  release.
- **PERCENT**: con el default 0.01% la magnitud no cambia (el `/100` ya lo
  hacía el frontend); lo que cambia es que trades planos y parciales ahora
  pagan lo que deben.
- Sin cambios de schema ni de API: `fees` y `fee_type` viajan igual.

## 8. Referencia

- Commit: `77236d2` (visible en `origin/alvaro-rama-desarrollo`).
- Parche: [`reference/fees-por-ejecucion.patch`](reference/fees-por-ejecucion.patch)
  — **no aplicar con `git apply` sobre `develop`**: mi `portfolio_sim.py`
  lleva cambios previos (locates proporcionales, parciales fade, trailing
  break-even) y el parche conflictúa ahí (verificado). Usadlo como referencia
  de comportamiento exacto; la spec de arriba es la fuente de verdad.
- `reference/test_fees.py` sí es copiable tal cual (archivo nuevo, sin
  dependencias de features de mi rama — verificado: solo importa
  `portfolio_sim.simulate` y `sim_dispatch.simulate_jit`).
