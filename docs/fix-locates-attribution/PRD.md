# PRD — Fix de atribución de locates (short-selling)

> **Tipo:** bug fix acotado sobre el motor de simulación. Toca zona sensible
> (`services/portfolio_sim.py`, `services/sim_dispatch.py`) → sigue las reglas de
> "no cirugía a ciegas": leer completo, tests primero, paridad Python↔JIT.
> **Estado:** PLAN. **Rama de ejecución:** `alvaro-rama-desarrollo`.
> **Fuente de verdad:** el código. Todas las citas son `fichero:línea` verificadas.

---

## 1. Qué y por qué

### El problema (en una frase)
El coste de locates de un día se **imputa entero a un solo trade** (el primer
short del día) y se **resta de toda la curva de equity del día** (incluidas las
barras previas a abrir el corto). El **total** diario es correcto, pero su
**reparto** falsea R por trade, win rate y drawdown intradía.

### Evidencia (misma estrategia "Definitiva 2.3", 867 trades idénticos)

| Métrica | Locate = 0 | Locate = 3 ($/100 acc.) |
|---|---|---|
| RETURN | +9876.73% | −71.73% |
| PF | 1.845 | 0.879 |
| **WIN RATE** | **64.1%** | **56.2%** |
| MAX DD | −18.34% | −75.45% |

El coste de locates cuando se opera en `risk_type=PERCENT` ("% Eq") es
legítimamente grande (el tamaño en acciones escala con el equity compuesto), así
que **que penalice el retorno es correcto**. Lo que **no** es correcto es que el
**win rate cambie de 64.1% a 56.2% con exactamente los mismos trades**: eso es la
huella del reparto. Al volcar el locate de todo el día sobre un único short, ese
trade se voltea a perdedor artificialmente y los demás quedan intactos.

### Modelo correcto (confirmado por producto — Álvaro)
**"Los locates son de una sola compra."** El borrow se compra **una vez por
ticker-día**, dimensionado al **tamaño máximo** en corto de ese día. Esto ya lo
hace bien el código y **se preserva sin cambios**: no se multiplica por
reentradas, no se cobra por cada re-borrow.

> Lo que cambia es **a quién se le imputa** ese coste único y **desde qué barra**
> se refleja en la curva — no cuánto es.

### Alcance

- **MVP (ahora):**
  1. Repartir el `daily_locates_fee` entre los trades short del día en proporción
     a su tamaño, preservando el total exacto.
  2. Reflejar el coste en la curva de equity **desde la barra de la primera
     entrada corta**, no desde la barra 0.
  3. Aplicar idéntico en `portfolio_sim.py` y `sim_dispatch.py` (paridad).
- **Fase 2 (no ahora, pero no bloquear):** exponer el locate como línea de coste
  propia en la respuesta por trade (`locates_fee` por trade) para el tab
  "Análisis por trade". El MVP deja el reparto ya calculado por trade, así que
  añadir el campo luego es aditivo.
- **Fuera de alcance:** el sizing en modo "% Eq" y su realismo (que el tamaño en
  acciones se dispare al componer el equity) — es otro problema, otro PRD. Aquí
  **no** se toca el cálculo de `size` ni de `daily_locates_fee`.

---

## 2. Fuentes auditadas (verdad anclada en código)

| Pieza real | Fichero:línea | Qué aporta |
|---|---|---|
| Bloque de locates (legacy) | `backend/app/services/portfolio_sim.py:861-888` | el bug: `break` en el primer short + `equity[i]` para todo `i` |
| Bloque de locates (JIT) | `backend/app/services/sim_dispatch.py:372-395` | copia **verbatim** del mismo bug |
| Cálculo del tamaño (`size`) | `backend/app/services/portfolio_sim.py:792-804` | `size = risk_amount/dist`, capado a `available_cash/entry_price` — **no se toca** |
| Registro del máximo del día | `backend/app/services/portfolio_sim.py:809` | `max_short_size_today = max(...)` — **se preserva** |
| R por trade a partir del pnl | `backend/app/services/backtest_service.py:954` | `r_multiple = _compute_r_multiple(t["pnl"], risk_unit_dollar)` → hoy hereda el locate mal repartido |
| Win rate a partir de pnls | `backend/app/services/backtest_service.py:1328,1330` | `winning_trades = (pnls>0).sum()` → sensible al reparto |
| DD intradía → MAX DD global | `backend/app/services/backtest_service.py:1391-1395` | `worst_day_dd` usa la curva del día, hoy contaminada desde la barra 0 |
| Agrupado de parciales | `backend/app/services/backtest_service.py` (`_group_partial_exits`) | corre **después** del sim: al aplicar el locate los parciales aún están sin agrupar |
| Tests existentes | `backend/tests/test_locates.py`, `test_locates_flat_semantics.py`, `test_sim_jit_equivalence.py` | patrón a extender + no romper |

---

## 3. Nomenclatura (nombres oficiales del código)

- `locates_cost` (float): coste del paquete de locate. En modo `FLAT` = $ por 100
  acciones (tu "$ Locate / 100 acc." = 3).
- `locate_type` (`"FLAT"` | `"PERCENT"`): modelo de coste. El MVP arregla el
  reparto para **ambos**; solo cambia cómo se calcula `cost_per_100`, no el reparto.
- `max_short_size_today` (float, shares): pico de tamaño en corto del día.
- `daily_locates_fee` (float, $): `ceil(max_short_size_today/100) * cost_per_100`.
  **Invariante que no cambia.**
- `first_short_entry_idx` (int): índice de barra de la primera entrada corta del
  día. **Nuevo** — necesario para el fix de la curva.

---

## 4. El fix (definición operativa exacta)

### 4.1 Invariante que se preserva
```
daily_locates_fee = ceil(max_short_size_today / 100) * cost_per_100
```
Una sola compra por ticker-día. Idéntico a hoy. La **suma** de lo imputado a los
trades del día debe seguir siendo **exactamente** `daily_locates_fee` (para que
`Σ pnl == cambio de la curva de equity`, invariante contable actual).

### 4.2 Defecto 1 — reparto entre trades
**Hoy** ([portfolio_sim.py:878-882](backend/app/services/portfolio_sim.py#L878)):
```python
for t in trades:
    if t["direction"] == "Short":
        t["pnl"]  -= daily_locates_fee
        t["fees"] += daily_locates_fee
        break                      # ← todo al primero
```
**Nuevo:** repartir proporcional al tamaño de cada trade short del día.
- Sea `S = Σ size` de los trades con `direction == "Short"` del día.
- Para cada short `t`: `share_t = daily_locates_fee * (t.size / S)`.
- Restar `share_t` de `t["pnl"]` y sumarlo a `t["fees"]`.
- **Cuadre de redondeo:** tras redondear cada `share_t` a 4 decimales, el residuo
  (`daily_locates_fee - Σ share_t`) se asigna al short de mayor `size`, de modo
  que la suma cierre exacta.
- **Fallback:** si `S == 0` (no debería con shorts reales), reparto equitativo
  entre los shorts; si no hay ningún short en `trades`, no se imputa a pnl (solo
  afecta la curva, §4.3).

> Nota: al aplicarse el locate, los parciales aún **no** están agrupados. Repartir
> por `size` de cada registro es correcto: `_group_partial_exits` suma después los
> `pnl`, así que cada posición agrupada acaba con la fracción del locate que le
> corresponde por sus acciones.

### 4.3 Defecto 2 — reflejo en la curva de equity
**Hoy** ([portfolio_sim.py:887-888](backend/app/services/portfolio_sim.py#L887)):
```python
for i in range(len(equity)):
    equity[i] -= daily_locates_fee     # ← incluida la barra 0 (premarket, sin posición)
```
Esto baja la línea del día **desde antes de que exista el corto**, inflando el
drawdown intradía de ese ticker-día (que alimenta `worst_day_dd → final_max_dd`).

**Nuevo:** el borrow se paga cuando se establece el primer corto. Restar solo
desde esa barra en adelante:
```python
for i in range(first_short_entry_idx, len(equity)):
    equity[i] -= daily_locates_fee
```
`first_short_entry_idx` = `entry_idx` de la primera entrada con `direction ==
"Short"` del día (capturarlo cuando se hace `max_short_size_today = max(...)`).

### 4.4 Defecto 3 — reentradas (NO es bug, se documenta)
Álvaro confirma: locate = una sola compra. `max_short_size_today = max(...)` y una
única imputación por día es **el comportamiento correcto**. **No** se cobra por
reentrada. Se deja test de regresión que lo fije para que nadie lo "arregle" mal
en el futuro.

### 4.5 Paridad
El bloque de `sim_dispatch.py:372-395` es copia verbatim: aplicar el **mismo**
cambio, byte-equivalente en semántica de redondeo, para que
`test_sim_jit_equivalence.py` siga verde.

---

## 5. Ejemplo numérico cerrado (test)

Día con **2 posiciones cortas** (reentrada), `locate_type=FLAT`, `locates_cost=3`:
- Posición A: `size = 3000` shares. Posición B: `size = 1000` shares. No solapan.
- `max_short_size_today = 3000` → `daily_locates_fee = ceil(3000/100)*3 = 30*3 = $90`.

**Reparto nuevo** (`S = 4000`):
- A: `90 * 3000/4000 = $67.50` → `A.pnl -= 67.50`
- B: `90 * 1000/4000 = $22.50` → `B.pnl -= 22.50`
- `Σ = $90` ✓ (igual al total de hoy)

**Hoy (bug):** A −$90, B −$0.

**Curva:** si A entra en la barra 40 de 780, el equity solo baja $90 desde `i=40`,
no desde `i=0`. `equity[0]` queda intacto.

---

## 6. Plan de ejecución (atómico) + verificación

> Regla: cada tarea (a) test primero, (b) implementa, (c) corre el comando, (d)
> commit convencional. No avanzar si el comando no pasa. Rama `alvaro-rama-desarrollo`.

**T1 — Tests de reparto (rojo primero)**
- Extender `backend/tests/test_locates.py` con el caso §5 (2 shorts, reentrada):
  asserts (i) `Σ locate imputado == daily_locates_fee`, (ii) ningún trade carga el
  100% cuando hay ≥2 posiciones, (iii) `equity[0]` no cambia por el locate.
- Verif: `pytest backend/tests/test_locates.py -q` (debe fallar antes del fix).

**T2 — Fix en `portfolio_sim.py`**
- Sustituir `portfolio_sim.py:878-888` por el reparto proporcional (§4.2) + curva
  desde `first_short_entry_idx` (§4.3). Capturar `first_short_entry_idx` en L806-809.
- Verif: `pytest backend/tests/test_locates.py backend/tests/test_locates_flat_semantics.py -q`.

**T3 — Fix en `sim_dispatch.py` (paridad)**
- Aplicar el mismo cambio en `sim_dispatch.py:372-395`.
- Verif: `pytest backend/tests/test_sim_jit_equivalence.py -q` (Python↔JIT idénticos).

**T4 — Regresión de "una sola compra" (defecto 3)**
- Test: día con reentrada, `max_reentries=2` → `daily_locates_fee` se calcula UNA
  vez sobre `max_short_size_today`, no ×nº de entradas.
- Verif: `pytest backend/tests/test_locates.py -q`.

**T5 — Suite completa + no-regresión de contrato**
- Verif: `pytest backend/tests/ -q` (todo verde, incl. `test_backtest_integration.py`).

### Definition of Done
- [ ] `Σ` de locates imputados por día == `daily_locates_fee` (invariante contable intacta).
- [ ] Con ≥2 posiciones cortas, ningún trade carga el locate completo del día.
- [ ] `equity[0]` (y toda barra previa a `first_short_entry_idx`) no la altera el locate.
- [ ] Win rate y R por trade dejan de depender del orden/nº de shorts del día para un mismo coste total.
- [ ] `portfolio_sim.py` y `sim_dispatch.py` producen resultados idénticos (`test_sim_jit_equivalence.py` verde).
- [ ] Suite `backend/tests/` completa en verde.
- [ ] `RETURN` global (bruto/neto) **no cambia** respecto a hoy para un caso sin reentradas (el total era correcto; solo cambia el reparto).

---

## 7. Decisiones

- **(A) Método de reparto — ✅ FIJADO: proporcional al `size` de cada short**
  (decidido por Álvaro, 2026-08-20). Es la regla del §4.2 y **no** admite
  variante: el locate del día se reparte entre los trades short en proporción a
  sus acciones, preservando el total exacto. GLM implementa esto sin preguntar.

### Decisiones abiertas (no bloquean el MVP)

- **(B) Exponer `locates_fee` por trade en el response** (Fase 2). Reversible;
  el MVP ya deja el número calculado por trade. *Dueño: producto.*
- **(C) `size` fraccional en `ceil(size/100)`** — el tamaño en acciones es float
  (p. ej. 3333.33). Fuera de alcance de este PRD, pero anotado: en real las
  acciones son enteras. *Dueño: Adrián (sizing).*
