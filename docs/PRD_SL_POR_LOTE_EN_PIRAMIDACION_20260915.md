# PRD — Stop Loss por lote en la piramidación (SL por ejecución)

- **Fecha:** 2026-09-15
- **Autor:** Álvaro (idea y decisiones de diseño) + ZCode (redacción y verificación de código)
- **Estado:** REVISADO CONTRA CÓDIGO (2026-09-15) — todas las afirmaciones de
  §5.2/§5.5/§3.1/§3.3 verificadas en el repo; incorporados dos ajustes de
  semántica (§3.3 precio de referencia del PnL de lote y §10·5). Listo para
  implementación.
- **Entrega deseada:** si el check es positivo, HOY (fases P0-P1 mínimas)

---

## 1. Contexto y motivación

La piramidación del backtester funciona por niveles con árbol de condiciones
completo (`pyramiding.levels[]`, compilados en
`backend/app/services/strategy_engine.py:365-415`), cada uno con acción
(`add`/`reduce`), cantidad (`pct`/`usd`), `times` (un nivel puede dispararse en
cada pata nueva) y campos de disciplina de tamaño (`size_by_sl`, `hybrid_stop`,
`hybrid_black_swan_pct`, `hybrid_max_loss_pct`).

**El problema** (verificado el 15-sep en `backend/app/services/portfolio_sim.py`):
cada añadido se **fusiona en una única posición agregada** — recalcula
`avg_entry_price` y suma tamaño (línea ~1680) — con **un solo stop por trade**
(`trade_sl_price`) compartido por base y añadidos. Stop, trailing, TPs y salidas
por señal actúan sobre el conjunto. No existe hoy forma de que un añadido que
falla se cierre solo, sin arrastrar toda la posición.

Caso de uso concreto (estrategia «Sobri 3 + Piramidación Patas», réplica id
`68a748d5-995e-49b5-ba77-f29f124f7fdc`): se añade en la muerte de cada
retroceso (`Retroceso (%) ≥ 40` + vela de rechazo). Si la pata N falla, hoy el
stop del trade (estructural, lejos) decide cuándo sale TODO — incluidas las
patas que iban bien. Se quiere que cada lote traiga su propio cinturón: cerrar
SOLO ese lote cuando su nivel se rompe.

**Precedente mecánico que ayuda mucho:** los niveles `reduce` ya son piernas de
cierre con pnl/fees propios registradas como trades (`exit_reason: "Pyramid
Reduce"`, `portfolio_sim.py` ~1714-1760) y en `pyr_exec` (kind reduce). Un stop
de lote es, mecánicamente, una pierna de cierre automática. La fontanería de
cierres parciales YA existe.

## 2. Objetivo y no-objetivos

**Objetivo:** permitir que cada nivel de piramidación declare un
**SL propio por ejecución (lote)**, por **%** o por **estructura** (Último
pivote, Previous Max, HOD/LOD, con offset), que al dispararse cierra únicamente
las acciones de ese lote.

**No-objetivos (v1):**
- Trailing del SL de lote (el nivel se congela al entrar el lote; ver §9).
- SL de lote en el kernel Numba (la piramidación vive en el simulador Python;
  ver §5.5 — VERIFICAR el dispatch).
- Cambiar el stop del trade, los TPs parciales, BSwan/halts, EV gate o locates.
- Lotes en la dirección contraria al bias (no existe hoy y no hace falta).

## 3. Semántica propuesta (las decisiones que hay que validar)

### 3.1 Dónde vive la clave

En cada **nivel** de `pyramiding.levels[]`, clave opcional `lot_stop`:

```json
{
  "root_condition": { ... },
  "action": "add",
  "unit": "pct",
  "capital_pct": 5,
  "times": 3,
  "lot_stop": {
    "mode": "pct" | "structure",
    "pct": 2.5,
    "level": "last_pivot" | "previous_max" | "hod" | "lod",
    "swing": "up" | "down",
    "pivot_window": 3,
    "offset_pct": 0.5
  }
}
```

- `mode: "pct"` → distancia % desde el precio de entrada del lote (lado
  correcto según bias: en corto, por encima; en largo, por debajo).
- `mode: "structure"` → el nivel de estructura **vigente en la vela de
  señal** —lo último totalmente cerrado al momento del fill, que es la
  apertura de la barra siguiente (§3.2)—
  (causal; el vocabulario es el del SL estructural existente del motor, más
  «Último pivote» con su `pivot_window` y `swing`). En corto con `last_pivot`:
  el techo confirmado (lower high de la pata) + `offset_pct` de holgura hacia
  arriba; en largo, el espejo con suelos.
- Sin `lot_stop` → comportamiento actual, idéntico (§4).

### 3.2 Anclaje: CONGELADO en la vela de señal del lote

El nivel del SL de lote se calcula una vez, con la información de la vela de
señal del añadido —lo último totalmente cerrado al momento del fill; el fill
es la apertura de la barra siguiente—, y no se recalcula. Precedente: el stop
ATR causal (fe40b65 — «nivel fijado en la entrada con el ATR de la vela de
señal»). Es la versión causal limpia; el trailing estructural de lote queda
para v2 (§9). *(Ratificado por Álvaro el 2026-09-15 tras la implementación.)*

### 3.3 Disparo y cierre

En cada barra, tras evaluar el stop del trade (orden en §3.4), para cada lote
vivo con `lot_stop`: si la vela cruza el nivel del lote (en corto, `high ≥
sl_px`; en largo, `low ≤ sl_px`), se cierra TODO el lote al precio del nivel
penalizado por el slippage configurado de la corrida (mismo tratamiento de fill
que el stop del trade). Se registra:

- Un trade de cierre con `exit_reason: "Pyramid Lot Stop"`, con su pnl/fees y
  `entry_price` = fill real del lote. Se clona la **estructura y el formato** del
  registro de los `reduce` (mismos campos, mismo cálculo de fees por los dos
  lados, misma entrada en `pyr_exec`), **PERO NO el precio de referencia del
  PnL**. ⚠️ El `reduce` calcula `gross_pnl` contra `avg_entry_price` —la media
  ponderada de TODA la posición (`portfolio_sim.py:1721-1723`)—; un SL de lote
  cierra un lote CONCRETO, así que su `gross_pnl` se calcula contra el **`px` de
  entrada de ESE lote**, no contra la media. Fórmula explícita (mismo slippage
  que el stop del trade): en largo `(net_lote − lot.px) × lot.size`, en corto
  `(lot.px − net_lote) × lot.size`. Clonar el `reduce` al pie de la letra aquí
  daría el número equivocado y rompería el propósito («cada lote con su propio
  pnl»). El `avg_entry_price` del trade global se sigue reportando aparte, como
  en los `reduce`.
- Entrada en `pyr_exec` con `kind: "lot_stop"` (o extender el `add`
  correspondiente con `closed_idx`/`closed_price` — decisión de implementación,
  ver §10).
- Las acciones salen de `size` y de `pyr_base` (los TP parciales siguientes
  porcentan sobre lo que quede vivo).

### 3.4 Coexistencia y orden dentro de la barra

1. Stop del **trade** (y BSwan/halts si activos): si salta, cierra TODO
   (base + lotes) como hoy. El stop global sigue siendo la red de seguridad.
2. Después, lot stops de los lotes vivos (en orden cronológico de lote).
3. Después, señales de niveles de piramidación y reduce.

Caso misma-barra (el stop global y un lot stop saltan en la misma vela): manda
el global — el trade entero sale con su `exit_reason` actual y NO se registran
cierres de lote separados (evita dobles fills en la misma vela).

### 3.5 Interacción con el sizing del nivel

Si el nivel tiene `size_by_sl` **y** `lot_stop`, la distancia que dimensiona el
añadido pasa a ser la **del SL del lote** (no la del stop del trade): el lote
entero arriesga exactamente lo que el nivel declara. Es coherente con el
propósito de `size_by_sl` («riesgo al stop») y con el espíritu de
`hybrid_max_loss_pct` del nivel. Si el nivel no tiene `lot_stop`, sigue siendo
la distancia al stop del trade (sin cambio).

### 3.6 Métricas y convenciones que NO cambian

- `r_multiple` del trade sigue dividiendo TODO el PnL (base + lotes, ganen o
  pierdan) por el 1R de la entrada inicial — convención documentada del motor
  (MEMORIA, hallazgo 2026-09-07·04). Opcional: exponer `r_lote` en el registro
  del cierre de lote para el panel/Trades.
- MAE/MFE del trade global se quedan como están; los trades de cierre de lote
  llevan los suyos (como los reduce).
- Locates: un cierre de lote en corto NO devuelve locates (se cobran una vez
  por ticker-día sobre el máximo en corto del día — sin cambio).
- Cangrejo modo B: el cupo de pérdida al stop se recalcula con el `size` vivo
  (un lote cerrado libera potencial) — verificar que usa size actual, que ya
  hace en el cálculo del margen por añadido.

## 4. Regla nº1 de este repo: compatibilidad byte-idéntica

Una definición **sin** `lot_stop` (ni en niveles nuevos ni viejos) debe
compilar y simular **exactamente igual que antes** — mismos trades, mismos
PnL, mismo payload. Esto incluye las estrategias ya guardadas y las
compartidas. Test de regresión obligatorio con corridas doradas (§6).

## 5. Cambios por capa

### 5.1 Schema (`backend/app/schemas/strategy.py` + tipo TS)

Campo opcional `lot_stop` en el nivel de piramidación, con validación
(`mode` en {pct, structure}; `pct > 0`; `level` del vocabulario permitido).
Rechazar (422) combinaciones imposibles (p. ej. `mode: pct` sin `pct`).

### 5.2 Compilador (`strategy_engine.py:compile_strategy_def`)

Normalizar y validar `lot_stop` por nivel; pasar el bloque validado a
`pyramid_levels_def`. Resolución de nombres del nivel de estructura igual que
el SL estructural existente (mismo mapa, mismo tratamiento de «Último pivote»
con `pivot_window`/`swing`).

### 5.3 Serie del nivel de estructura para el anclaje

El simulador necesita, en la vela del fill, el valor del nivel elegido (p. ej.
«Último pivote» con su ventana). Reutilizar el mecanismo que hoy usa el stop
estructural del trade para disponer de esas series en el bucle (mismo cálculo,
misma causalidad; NO una segunda implementación — paridad bit a bit con
`indicators.py`, como exige la excepción `market_frame.py` del protocolo).

### 5.4 Simulador Python (`portfolio_sim.py`)

- Estado nuevo por trade: `lots: list[{level_idx, px, size, sl_px}]` (vacío si
  ningún nivel declara `lot_stop` → camino caliente intacto).
- Cada `add` con nivel con `lot_stop` apunta su lote.
- Evaluación y cierre por barra según §3.3-3.4, con registro calcado de los
  `reduce`.
- `avg_entry_price` se **recalcula al cerrar un lote** restando su contribución,
  SIN necesidad de meter la base en la lista de `lots` (coherente con §10·4,
  base NO es lote en v1): `avg_new = (avg·size − lot.px·lot.size) /
  (size − lot.size)`. La media hoy se construye incrementalmente con cada `add`
  (`portfolio_sim.py:1680`); esto es la operación inversa. `size` y `pyr_base`
  bajan en `lot.size`. (No es "media de los lotes vivos": la base sigue disuelta
  en `avg_entry_price` como hasta ahora; solo se descuenta lo que cierra.)

### 5.5 Kernel Numba

`backend/app/backtester/portfolio.py` NO implementa piramidación (verificado
15-sep: cero referencias). Las señales de niveles se calculan en
`backtest_signals.py` y el consumo ocurre en el simulador Python. **Acción:**
VERIFICAR en `sim_dispatch.py` que una estrategia con piramidación (con o sin
`lot_stop`) fuerza el motor Python, igual que BSwan/halts. Si ya es así, Numba
queda fuera de alcance de este PRD y no hay riesgo de paridad. Si NO es así
(piramidea el kernel de alguna forma), parar y repensar (§8).

### 5.6 Frontend

- **Builder** (`InlineStrategyBuilder`, bloque Piramidación): sección opcional
  «SL del lote» por nivel, con los mismos controles y vocabulario que el SL de
  la estrategia (% / estructura + nivel + offset + swing/ventana para pivote).
- **Tarjeta del panel** (`BacktestPanel.tsx`, bloque PIRAMIDACIÓN): una línea
  por nivel con lot stop, p. ej. «cada lote con SL: pivote-3 +0,5 %».
- **Pestaña Trades / chart**: pintar los niveles de lotes (línea punteada
  corta por lote) y etiquetar las salidas «SL lote». `pyr_executions` extendido
  llega solo.

### 5.7 Persistencia y compartidas

La clave viaja dentro de `pyramiding.levels[]` de la definición — el JSON de
compartidas (`format_version: 1`) la transporta sin cambios de formato. Los
estrategias ajenas sin la clave importan/abren igual (§4).

## 6. Plan de pruebas

1. **Unit (sim):** matemática del cierre por lote — pct y estructura, largo y
   corto; slippage aplicado; pnl/fees del lote; `avg_entry_price` tras cerrar
   un lote; `pyr_base` reducida; lote recortado por tope de caja (cierra lo que
   haya). **Test discriminante del precio de referencia (§3.3):** un caso donde
   `lot.px ≠ avg_entry_price` (base + al menos un add a otro precio) para el que
   el PnL contra la media daría un número DISTINTO al PnL contra el px del lote;
   el test fija el valor correcto (px del lote) y falla si se calcó del `reduce`.
2. **Unit (same-bar):** stop global + lot stop en la misma vela (manda global,
   sin doble fill); dos lot stops en la misma vela; lot stop y reduce el mismo
   día.
3. **Regresión dorada:** corridas de (a) estrategia SIN piramidación, (b) con
   piramidación sin `lot_stop` (p. ej. la réplica Sobri 3 + Patas actual) —
   trades idénticos byte a byte antes/después del cambio.
4. **Compilador:** normalización de nombres, 422 en combinaciones inválidas,
   definición sin claves → dict compilado idéntico (hash).
5. **Integración UI:** builder → guardar → cargar → correr; tarjeta del panel
   muestra el SL de lote; Trades pinta salidas «SL lote».
6. **Validación A/B (post-implementación):** la réplica `68a748d5…` con
   `lot_stop: {mode: structure, level: last_pivot, swing: up, pivot_window: 3,
   offset_pct: 0.5}` en el nivel de patas vs. sin él — mismo dataset, mismos
   parámetros del panel, `look_ahead_prevention: true`.

## 7. Criterios de aceptación

- [ ] Definiciones sin `lot_stop` → corridas byte-idénticas (test dorado verde).
- [ ] `lot_stop` pct y estructura cierran SOLO su lote, con registro propio.
- [ ] El PnL del cierre de lote se calcula contra el `px` del lote, NO contra
      `avg_entry_price` (test discriminante §6.1 verde).
- [ ] El stop del trade sigue mandando sobre el conjunto; misma-barra sin dobles fills.
- [ ] `size_by_sl` del nivel usa la distancia al SL del lote cuando ambos existen.
- [ ] Schema valida y rechaza basura con 422; builder y tarjeta lo muestran.
- [ ] Dispatch a motor Python confirmado (§5.5) o paridad Numba tratada.
- [ ] Tests 1-5 del §6 en verde; suite existente sin regresiones.

## 8. Riesgos

- **Misma-barra y orden de evaluación:** es el sitio donde esto puede mentir.
  Los tests del §6.2 son obligatorios, no opcionales.
- **Camino caliente:** el estado de lotes NO debe penalizar corridas sin
  piramidación ni sin lot_stop (lista vacía, cero allocs por barra).
- **Paridad Python↔Numba:** solo si §5.5 sale mal. Parar y volver con Jaume.
- **Acoplamiento con Cangrejo/hybrid:** no tocar sus fórmulas; solo verificar
  que operan sobre el `size` vivo (§3.6).

## 9. Fases

- **P0 (hoy):** schema + compilador + tests del §6.4. Sin sim.
- **P1 (hoy/mañana):** simulador Python + tests §6.1-6.3 + corrida dorada.
- **P2:** UI (builder + tarjeta + Trades).
- **P3:** validación A/B con la réplica (§6.6) y decisión de trailing de lote
  (v2: `mode: "structure_trail"` que re-ancle el nivel con cada pivote nuevo
  confirmado — mismo mecanismo, reevaluación por barra; solo si P3 lo pide).

## 10. Preguntas abiertas para el revisor (decidir antes de P1)

1. **Nombre de la clave:** `lot_stop` (propuesto) vs `stop_loss` por nivel
   (colisiona visualmente con el del trade) vs `per_lot_sl`.
2. **Registro del cierre:** trade aparte con `exit_reason: "Pyramid Lot Stop"`
   (propuesto — consistente con reduce) vs. solo anotación en `pyr_exec`.
3. **§3.5 (`size_by_sl` apuntando al lote):** confirmar el cambio de semántica
   condicional o mantener siempre el stop del trade.
4. **Base como lote implícito:** ¿la entrada principal también pasa a la
   estructura de lotes (uniforme, sin `lot_stop`)? Propuesto: NO en v1 — solo
   los añadidos; menos superficie de regresión.
5. **Precio de referencia del PnL del lote (RESUELTO — ver §3.3):** el
   `gross_pnl` del cierre de lote va contra el `px` de entrada de ESE lote, no
   contra `avg_entry_price`. Se deja fijado aquí para que no se reabra ni se
   "calque del reduce" por inercia: el `reduce` usa la media a propósito (cierra
   un % de la flotante, no un lote identificado); el lot stop cierra un lote
   concreto y su PnL es contra su propio precio. Decisión cerrada por Álvaro.

---

*Referencias de código verificadas el 15-sep: `strategy_engine.py:365-415`
(compilación de niveles), `portfolio_sim.py` ~1600-1705 (adds y agregación),
~1714-1760 (reduce como pierna), `backtest_signals.py:213-322` (señales de
niveles), `backtester/portfolio.py` (sin piramidación). Estrategia de
validación: «Estrategia 1B - Modelización Sobri 3 + Piramidación Patas», id
`68a748d5-995e-49b5-ba77-f29f124f7fdc`.*
