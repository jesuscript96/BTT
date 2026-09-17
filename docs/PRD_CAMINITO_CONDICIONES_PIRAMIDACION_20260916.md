# PRD — «Caminito» de condiciones en la piramidación (pasos secuenciales por nivel)

- **Fecha:** 2026-09-16
- **Autor:** Álvaro (idea, caso de uso y decisiones de diseño) + Claude Opus 4.8
  (redacción y verificación contra el código real). Propuesta de partida de una
  IA externa, reescrita y aterrizada al motor.
- **Estado:** REVISADO CONTRA CÓDIGO (2026-09-16). Toda afirmación sobre el motor
  está anclada a `portfolio_sim.py` / `strategy_engine.py` / `strategy.py` con
  línea. Listo para implementación por el dueño del código en su rama.
- **Regla nº1 del repo (recordatorio):** cualquier estrategia SIN `steps` compila
  y simula **byte-idéntica** a hoy. Test dorado obligatorio (§11).

---

## 1. Contexto y motivación

La piramidación funciona por **niveles**. Cada nivel se compila hoy con **un
único** árbol de condiciones `root_condition`
([strategy_engine.py:539-563](../backend/app/services/strategy_engine.py)) y se
evalúa a **un único** array booleano `signals`
([strategy_engine.py:1071-1089](../backend/app/services/strategy_engine.py)).
En el simulador cada nivel lleva dos estados paralelos por trade: `pyr_prev_sig[k]`
(para detectar el flanco) y `pyr_fired[k]` (contador de disparos)
([portfolio_sim.py:513-514](../backend/app/services/portfolio_sim.py)).

El disparo de un nivel es el flanco `False→True` de su señal, **medido dentro del
trade** ([portfolio_sim.py:1740](../backend/app/services/portfolio_sim.py)),
ejecuta en la apertura de la vela siguiente (`look_ahead_prevention`,
[portfolio_sim.py:1754-1758](../backend/app/services/portfolio_sim.py)) y **todo
se rearma en cada (re)entrada**
([portfolio_sim.py:2277-2278](../backend/app/services/portfolio_sim.py)).

**Lo que el usuario quiere y hoy no existe:** dentro de UN mismo nivel, una
**cadena ORDENADA de condiciones**: «primero que se cumpla A; cuando A se haya
cumplido (aunque luego deje de cumplirse), que se cumpla B; y al cumplirse B —
AHÍ— añadir X». Es una herramienta **genérica** de encadenar condiciones (como el
configurador de entrada), no atada a ningún caso concreto.

**Lo que NO vale como sustituto:**
- Un AND clásico exige A **y** B en la misma vela; el camino permite que B llegue
  **tarde**, aunque A ya no se cumpla.
- El modo `sequential` **entre niveles** ya existe, pero cada nivel es una ACCIÓN
  (mete/quita dinero). No sirve como «peldaños que no operan»: aquí solo el
  **último** paso opera; los intermedios solo abren la puerta al siguiente.

**Por qué encaja limpio:** la semántica del camino **no es nueva**. Es
*exactamente* la regla que el motor ya aplica **entre niveles** — «un nivel que no
tiene el turno NO consume su flanco»
([portfolio_sim.py:1728-1741](../backend/app/services/portfolio_sim.py)) —
aplicada ahora **dentro de un nivel, entre pasos**. Se generaliza una lógica ya
probada, no se inventa una nueva.

---

## 2. Objetivo y no-objetivos

**Objetivo:** permitir que un nivel de piramidación declare, en vez de un único
`root_condition`, una **lista ordenada de árboles de condición** (`steps`). El
nivel solo ejecuta su acción (`add`/`reduce`) cuando se enganchan **todos** los
pasos en orden.

**No-objetivos (v1):**
- Tocar entradas, salidas, stops del trade, TPs parciales, BSwan/halts, escalping,
  reentradas, EV gate, locates, `lot_stop` ni la semántica de `times`/`unit`.
- Tocar el kernel Numba (la piramidación nunca lo pisa — §9).
- Ramas condicionales dentro del camino (OR entre pasos, saltos). Un camino es
  una cadena lineal. Un OR *dentro* de un paso sí se expresa (cada paso es un
  árbol completo con su AND/OR).
- Contar eventos previos a la entrada (decisión Q2 = A, §3).

---

## 3. Decisiones de diseño CERRADAS

Estas cinco estaban abiertas en la propuesta original; Álvaro las cerró el
2026-09-16.

| # | Decisión | Valor cerrado |
|---|----------|---------------|
| Q1 | ¿Completar el camino en la misma vela? | **Configurable por nivel**, `same_bar` (default `true` = permitido). Con `true`, un camino que de hecho es un AND da resultado equivalente al de hoy. Con `false`, se exige ≥1 vela entre enganches. |
| Q2 | ¿Desde cuándo cuentan los pasos? | **A — solo desde la entrada.** Consistente con toda la piramidación (post-entrada, `i > entry_idx`). Un ESTADO aún vigente al entrar engancha en la 1ª vela de su turno; solo se pierden EVENTOS transitorios ya terminados antes de entrar. Sin riesgo de look-ahead. |
| Q3 | ¿Conservar estados de señal tras disparo? | **Sí (anti-metralla).** Tras disparar, las llaves se reinician pero el `prev_sig` de cada paso se conserva: una condición sostenida no re-dispara barra a barra; hace falta un flanco nuevo. Misma filosofía que `pyr_prev_sig` hoy. |
| Q4 | ¿`times > 1` con camino? | **Recorrer el camino ENTERO por cada disparo.** Un nivel-camino con `times=3` puede completar el camino 3 veces en el trade. |
| Q5 | Nombres | Interno: `steps` (lista) / `steps_signals`. UI: conmutador **«Camino (condiciones en secuencia)»**; tarjeta «1º … → 2º … → añadir X%». |

**Alcance de `steps`:** aplica a niveles `add` **y** `reduce` (el camino solo
cambia el GATILLO; la acción es la de siempre). `lot_stop` sigue siendo solo
`add`, sin cambios.

---

## 4. Semántica del camino (el corazón)

Estado nuevo **por nivel-camino y por trade**:

- `step_k`: índice del paso pendiente (arranca en 0).
- `step_prev_sig[j]`: estado de señal previo de cada paso `j` (para el flanco).
- `bar_last_latch`: índice de la vela del último enganche (solo si `same_bar=false`).

Reglas (todas son la regla entre-niveles de hoy, llevada a pasos):

1. **Turno.** Solo se evalúa el paso `step_k` (el pendiente). Los pasos
   posteriores no se miran hasta que les toca — igual que un nivel desarmado no
   consume su flanco ([portfolio_sim.py:1728-1733](../backend/app/services/portfolio_sim.py)).
2. **Enganche.** El paso `step_k` engancha cuando su señal está en flanco
   `False→True` **en su turno**: `sig_now and not step_prev_sig[step_k]`. Como
   `step_prev_sig` arranca en `False` en cada entrada, una condición **ya vigente
   al entrar** engancha en la primera vela post-entrada (Q2 = A: los estados
   vigentes SÍ cuentan; los eventos transitorios previos NO).
   Enganchado queda: **no necesita seguir cumpliéndose.**
3. **Avance.** Al enganchar `step_k`, `step_k += 1`.
4. **Misma vela (`same_bar`).**
   - `true` (default): tras enganchar `step_k`, se sigue evaluando `step_k+1` en la
     MISMA vela; puede completarse el camino entero en una vela. Generaliza el AND.
   - `false`: en la vela del enganche no se evalúa el siguiente paso
     (`bar_last_latch == i` bloquea); el siguiente paso solo puede engancharse en
     `i+1` o posterior.
5. **Disparo.** Enganchar el ÚLTIMO paso = disparo del nivel. La ejecución es
   **exactamente la de hoy**: fill en apertura de `i+1`, tope de caja, disciplinas
   de tamaño (`size_by_sl`, híbrido, Cangrejo), y `lot_stop` anclado en la vela de
   señal del añadido ([portfolio_sim.py:1765-1935](../backend/app/services/portfolio_sim.py)).
   El disparo se cuenta (`pyr_fired[k] += 1`) **solo si se ejecuta de verdad**
   (misma regla que hoy, [portfolio_sim.py:1744-1748](../backend/app/services/portfolio_sim.py)).
6. **Tras disparar (si `times` no agotado).** `step_k = 0` (llaves reiniciadas),
   PERO `step_prev_sig[]` se **conserva** con su valor actual → una condición
   sostenida no re-dispara; hace falta flanco nuevo (Q3).
7. **Rearme por (re)entrada.** Cada entrada resetea `step_k=0`, `step_prev_sig[]=False`,
   `bar_last_latch=-1` — enganchado en el bloque de rearme existente
   ([portfolio_sim.py:2277-2278](../backend/app/services/portfolio_sim.py)).
8. **Ventana de conteo.** Solo post-entrada (`i > entry_idx`), como toda la
   piramidación hoy ([portfolio_sim.py:1702](../backend/app/services/portfolio_sim.py)).

**Propiedad clave:** con un solo `steps` de un elemento… no aplica (mínimo 2, §5).
Con dos pasos idénticos a los dos operandos de un AND y `same_bar=true`, el camino
produce el MISMO disparo que ese AND — el camino **generaliza** el AND, y el valor
nuevo es que el 2º paso puede llegar tarde.

---

## 5. Schema y validación (frontera del API)

`pyramiding` es hoy un **dict opaco** ([strategy.py:538](../backend/app/schemas/strategy.py));
la validación fuerte del bloque nuevo se hace en un `field_validator` que delega en
una **única fuente de verdad** del compilador — patrón idéntico al de `lot_stop`
([strategy.py:540-568](../backend/app/schemas/strategy.py)).

Clave nueva OPCIONAL por nivel:

```json
{
  "action": "add",
  "unit": "pct",
  "capital_pct": 5,
  "times": 3,
  "same_bar": true,
  "steps": [
    { "type": "group", "operator": "AND", "conditions": [ ... ] },
    { "type": "group", "operator": "AND", "conditions": [ ... ] }
  ]
}
```

Reglas de validación (todas → **422 en la frontera**, nunca drop silencioso):

- `steps` y `root_condition` son **mutuamente excluyentes** por nivel: ambos → 422;
  ninguno → 422.
- `steps` debe ser lista de **≥ 2** árboles; cada paso debe tener `conditions`
  no vacío. Un paso vacío → 422. **Esto es requisito duro:** hoy el compilador
  descarta EN SILENCIO un nivel con árbol vacío
  ([strategy_engine.py:501](../backend/app/services/strategy_engine.py)); con
  `steps` un paso vacío cambiaría el camino sin avisar — se REVIENTA (lección de
  las «TRES CAPAS», MEMORIA_MADRE §4).
- `same_bar`, si viene, debe ser bool (default `true`).
- Nueva función única de verdad en `strategy_engine`: `normaliza_steps(steps, same_bar)`,
  invocada tanto por el validador Pydantic (para 422 al guardar) como por el
  compilador (para normalizar al ejecutar). Reutiliza `_normalize_tree` en cada
  paso.

---

## 6. Compilador (`translate_strategy`)

En el bucle de niveles ([strategy_engine.py:499-563](../backend/app/services/strategy_engine.py)):

- Si el nivel trae `steps`: llamar a `normaliza_steps`, `_normalize_tree` en cada
  paso, y guardar `nivel_compilado["steps_def"] = [árbol, …]` y
  `nivel_compilado["same_bar"] = bool`. **No** se guarda `root_condition`.
- Si el nivel trae `root_condition` (sin `steps`): **exactamente como hoy** — el
  dict compilado sale sin `steps_def` y es bit-idéntico.
- El resto del nivel (`action`, `unit`, `capital_frac`, `amount_usd`, `max_fires`,
  `size_by_sl`, híbrido, `lot_stop`) se compila igual, sea camino o no.
- `has_special = True` se sigue forzando con `pyr_levels_def` no vacío
  ([strategy_engine.py:647](../backend/app/services/strategy_engine.py)): un
  nivel-camino va por el path Python clásico igual que cualquier nivel.

---

## 7. Evaluador de señales (`_evaluate_pyramid_levels`)

En [strategy_engine.py:1054-1089](../backend/app/services/strategy_engine.py):

- Nivel normal: sigue devolviendo `signals` (un array). Camino caliente intacto.
- Nivel-camino: devolver `steps_signals` = **lista de arrays** (uno por paso),
  cada uno evaluado con `_evaluate_condition_group` sobre el `pyramid_tf`,
  **compartiendo la caché de indicadores** (mismo tf que la entrada → misma caché,
  como ya se hace).
- **La ventana horaria de entrada (`entry_time_mask`) se aplica a CADA paso**, no
  solo al primero. Un añadido es una entrada: si la ventana está cerrada, ningún
  paso engancha. Esto es un bug real ya corregido en el pasado (GELS piramidó a
  las 08:08 con ventana hasta las 08:00,
  [strategy_engine.py:1041-1046,1059-1070](../backend/app/services/strategy_engine.py)).
  Si una máscara no cuadra en longitud con un paso → el nivel entero se omite con
  log de error (misma regla que hoy), nunca a medias.
- Salida del nivel-camino: en vez de `"signals": arr` se emite
  `"steps_signals": [arr, …], "same_bar": bool`; el resto de claves del dict
  (`action`, `capital_frac`, `max_fires`, `unit`, `amount_usd`, `size_by_sl`,
  híbrido, `lot_stop`) igual que hoy.

---

## 8. Simulador (`portfolio_sim.py`)

Todo dentro del bloque de piramidación existente
([portfolio_sim.py:1702-2004](../backend/app/services/portfolio_sim.py)); mismo
orden dentro de la barra (tras todas las salidas, solo si la posición sigue viva),
mismo respeto al bloqueo por pérdida diaria (`riesgo_bloqueado`).

**Estructuras nuevas** (junto a `pyr_prev_sig` / `pyr_fired`,
[portfolio_sim.py:513-514](../backend/app/services/portfolio_sim.py)),
inicializadas y rearmadas donde hoy se rearma la pirámide
([portfolio_sim.py:2277-2278](../backend/app/services/portfolio_sim.py)):

```python
# Solo para niveles-camino; los niveles normales no las usan (coste cero).
pyr_step_k       = [0]  * len(pyramid_levels)     # paso pendiente por nivel
pyr_step_prev    = [None] * len(pyramid_levels)   # list[bool] por paso, o None si no es camino
pyr_last_latch   = [-1] * len(pyramid_levels)     # vela del último enganche (para same_bar=false)
```

**Detección de disparo** (reemplaza `sig_now = bool(lv["signals"][i]); dispara = …`
en [portfolio_sim.py:1739-1741](../backend/app/services/portfolio_sim.py)):

```python
if lv.get("steps_signals") is None:
    # ── Nivel NORMAL: idéntico a hoy (byte-idéntico) ──
    sig_now = bool(lv["signals"][i])
    dispara = sig_now and not pyr_prev_sig[lv_idx]
    pyr_prev_sig[lv_idx] = sig_now
else:
    # ── Nivel CAMINO: avanzar tantos pasos como se pueda en esta vela ──
    steps = lv["steps_signals"]
    same_bar = lv.get("same_bar", True)
    dispara = False
    while pyr_step_k[lv_idx] < len(steps):
        k = pyr_step_k[lv_idx]
        if (not same_bar) and pyr_last_latch[lv_idx] == i:
            break                          # ya hubo un enganche en esta vela
        sig_now = bool(steps[k][i])
        engancha = sig_now and not pyr_step_prev[lv_idx][k]
        pyr_step_prev[lv_idx][k] = sig_now
        if not engancha:
            break                          # el paso pendiente no engancha hoy
        pyr_step_k[lv_idx] += 1
        pyr_last_latch[lv_idx] = i
        if pyr_step_k[lv_idx] == len(steps):
            dispara = True                 # enganchado el último paso
            break
```

Notas finas:
- El `prev_sig` de un paso **solo se actualiza en su turno** (dentro del `while`,
  cuando `k == step_k`), no en cada barra para todos los pasos — es la regla de
  [portfolio_sim.py:1728-1733](../backend/app/services/portfolio_sim.py) llevada a
  pasos. Un paso futuro no consume su flanco antes de tiempo.
- Con `riesgo_bloqueado`, igual que hoy: `pyramid_levels_iter = []` → el bloque no
  corre, y el estado de pasos **no** se toca (el flanco queda intacto,
  [portfolio_sim.py:1710-1716](../backend/app/services/portfolio_sim.py)).

**Tras disparar y ejecutar** (donde hoy `pyr_fired[lv_idx] += 1`,
[portfolio_sim.py:1914](../backend/app/services/portfolio_sim.py) para add y
[:1987](../backend/app/services/portfolio_sim.py) para reduce): si es camino y
quedan `times`, reiniciar `pyr_step_k[lv_idx] = 0` y `pyr_last_latch[lv_idx] = -1`,
CONSERVANDO `pyr_step_prev[lv_idx]` (Q3).

**Interacción con `sequential` entre niveles (ORTOGONAL, pero con invariante fijo):**
el gate `nivel_activo` ([portfolio_sim.py:1719-1733](../backend/app/services/portfolio_sim.py))
elige el primer nivel con `pyr_fired[k] < max_fires`. Un nivel-camino a medias
(algunos pasos enganchados, no todos) **sigue teniendo `pyr_fired < max_fires`**,
así que **ocupa el turno y bloquea al siguiente nivel** hasta que dispara o agota
`times`. Esto es lo que se quiere: la secuencia entre niveles avanza por DISPARO,
no por enganche de pasos. **Invariante a testear (§11).**

`lot_stop`: sin cambios; el disparo del camino entra por el mismo bloque `add` y el
lote se ancla en la vela de señal como ya hace
([portfolio_sim.py:1773-1935](../backend/app/services/portfolio_sim.py)).

---

## 9. Qué NO cambia (garantía byte-idéntica)

- **Kernel Numba:** intacto. `has_special=True` fuerza el path Python; el dispatch
  retira los kwargs de pirámide antes del JIT (`sim_dispatch`). Un nivel-camino
  no llega jamás al kernel.
- **Cualquier nivel sin `steps`:** la rama `if lv.get("steps_signals") is None`
  ejecuta el código actual sin tocar una coma. El dict de un nivel normal no gana
  ninguna clave nueva.
- **Ejecución del add/reduce, topes de caja, `size_by_sl`, híbrido, Cangrejo,
  `lot_stop`, `pyr_base`, `pyr_exec`, reentradas, TPs:** sin cambios.
- **Test dorado obligatorio (§11):** estrategia sin pirámide + estrategia con
  pirámide clásica → trades byte a byte iguales antes y después del cambio.

---

## 10. UI (`PyramidingBuilder.tsx`)

Hoy cada nivel pinta un `ConditionBuilder` sobre `lv.root_condition`
([PyramidingBuilder.tsx:335-336](../frontend/src/components/strategy-builder/PyramidingBuilder.tsx)).

- Conmutador por nivel **«Camino (condiciones en secuencia)»**. OFF (default) → un
  solo bloque de condición, como hoy. ON → lista ordenada de bloques (pasos), cada
  uno con el mismo editor, y reordenación **▲▼** (patrón ya usado en Portfolio y
  Robustez, git log 738cec2).
- Al activar el camino: interruptor **«Permitir completar en la misma vela»**
  (`same_bar`, default ON).
- Mínimo 2 pasos para guardar en modo camino (el front avisa; el back lo blinda
  con 422).
- Tarjeta del panel: «1º Retroceso ≥ 40% → 2º spike 5%/5min y ≤10% VWAP → añadir 5%».
- `types/strategy.ts`: añadir `steps?: ConditionGroup[]` y `same_bar?: boolean` al
  tipo de nivel; `root_condition` pasa a opcional cuando hay `steps`.

---

## 11. Tests obligatorios

**Unitarios de semántica** (nuevo `test_pyramid_steps_*`):
1. Orden de enganche: B antes que A no dispara; A→B sí.
2. Condición sostenida: A vigente al entrar engancha en la 1ª vela de su turno (Q2=A).
3. Evento transitorio previo a la entrada NO cuenta (Q2=A).
4. `same_bar=true`: A y B en la misma vela → dispara esa vela (equivale al AND).
5. `same_bar=false`: A y B en la misma vela → NO dispara; B en `i+1` → dispara.
6. `times=2`: el camino se recorre dos veces; tras el 1er disparo, condición
   sostenida NO re-dispara sin flanco nuevo (Q3).
7. Rearme en reentrada: nueva entrada resetea `step_k` y `step_prev`.
8. Camino que nunca completa B: cero añadidos, sin crash.
9. `sequential` entre niveles: nivel-camino a medias BLOQUEA al siguiente nivel
   hasta disparar (invariante §8).
10. Ventana horaria: ningún paso engancha fuera de `entry_time_windows`.
11. `look_ahead_prevention`: fill del disparo en apertura de `i+1`.
12. Camino + `lot_stop`: el lote se ancla en la vela de señal del disparo.

**Regresión dorada** (§9): mismas corridas doradas del `lot_stop`
(`.tmp_lot_stop/`) + una sin pirámide → trades byte a byte idénticos.

**Frontera API** (`test_strategy_api`): `steps`+`root_condition` juntos → 422;
`steps` con <2 → 422; paso vacío → 422; `steps` sin `root_condition` → 200.

---

## 12. Fases

- **P0** — Schema + `normaliza_steps` + compilador (`steps_def`) + tests de
  compilación y de 422. Sin tocar el simulador todavía.
- **P1** — Evaluador (`steps_signals` + máscara por paso) + simulador (bucle de
  pasos) + tests unitarios §11 + **dorada**.
- **P2** — UI: conmutador, pasos con ▲▼, `same_bar`, tarjeta, tipos.
- **P3** — Validación A/B sobre una estrategia real del usuario (una cadena de ≥2
  condiciones), con `look_ahead_prevention: true`. Comparar contra la misma
  estrategia expresada como AND (debe coincidir cuando `same_bar=true` y los pasos
  son simultáneos) y contra el `sequential` de niveles (debe diferir: aquí los
  pasos intermedios no operan).

---

## 13. Coordinación de merges (IMPORTANTE)

Toca los **mismos 3 archivos** que el trabajo del SL por lote, ya commiteado en
`alvaro-rama-desarrollo` (9ba49bd): `strategy.py`, `strategy_engine.py`,
`portfolio_sim.py`. **Secuenciar, no paralelizar:**

1. Que `lot_stop` (P0+P1, 9ba49bd) esté integrado y estable primero.
2. Construir el camino ENCIMA de ese estado: el bloque `add` que el camino dispara
   **ya incluye** el `lot_stop` — el camino no lo reescribe, lo reutiliza.
3. Un solo desarrollador/rama a la vez sobre estos 3 archivos para evitar
   conflictos de fusión (regla de dos-devs del repo).

**Recordatorio del repo:** antes de cualquier `push`, confirmación explícita del
usuario. `main` no se toca. Nada de secretos ni datos.

---

## 14. Riesgos

| Riesgo | Mitigación |
|--------|-----------|
| Semántica de flancos/llaves «miente» (el punto donde esto puede fallar) | Tests §11 1-8 cubren cada regla; la lógica es la ya probada entre niveles. |
| Drop silencioso de un paso vacío cambia resultados sin avisar | 422 duro en la frontera + en el compilador (§5). Nunca `continue` silencioso. |
| Romper byte-identidad de niveles normales | Rama `if steps_signals is None` = código actual intacto; dorada obligatoria. |
| Conflicto de merge con `lot_stop` | Secuenciar merges (§13). |
| Look-ahead al mirar pasos previos a la entrada | Q2=A lo elimina de raíz: solo post-entrada, causal. |
| `same_bar=false` crea el caso «todo se cumplió y no disparó» | Documentado y default `true`; el flag es opt-in consciente. |
