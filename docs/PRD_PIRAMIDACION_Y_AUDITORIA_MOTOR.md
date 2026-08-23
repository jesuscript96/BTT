# Piramidación + auditoría del motor — especificación completa

> **Autor:** Sailor (Jaume) × Claude · **Fecha:** 2026-08-23
> **Para:** Álvaro y su IA.
> **Qué es:** la especificación EXACTA de la piramidación (gestión dinámica de
> la posición) y el informe íntegro de la auditoría del motor que se hizo
> encima, con los 7 fallos corregidos, los que se dejaron sin tocar y las cifras
> para verificar una implementación propia.
>
> Todo lo que hay aquí está **en el código de esta rama**. La semántica no la
> inventó la IA: cada decisión la fijó Jaume y va citada donde toca.

---

## 0. Resumen para quien tenga prisa

1. **Piramidación**: bloque nuevo `pyramiding` en la definición de estrategia.
   Permite AÑADIR o QUITAR posición con la operación abierta, con el mismo
   editor de condiciones que entrada/salida. §1 y §2.
2. **Regla nº1**: sin `pyramiding` en la definición, el backtest es
   **bit-idéntico** al de antes. Verificado (§6).
3. **La auditoría destapó 7 fallos reales del motor**, cuatro de ellos
   **ajenos a la piramidación** y que afectan a cualquier estrategia: el
   trailing pisaba al stop fijo, un comparador desconocido se evaluaba como
   "mayor que", un cruce en timeframe superior duraba todo el tramo, y el tope
   de caja anulaba añadidos en silencio. §4.
4. **Cuatro de los siete tocan el MOTOR COMPARTIDO** → cambian resultados de
   backtests existentes. Lista explícita en §5.
5. Cifras de control reproducibles en §6, para verificar sin compartir datos.

---

## 1. Qué es la piramidación y cómo se comporta

Un bloque de la estrategia, entre la salida lógica y el stop loss, con ON/OFF.
Contiene N "pirámides"; cada una es **un grupo de condiciones idéntico al de
entrada/salida** (mismo `GroupDisplay`, AND/OR anidados, todos los indicadores)
más una acción y una cantidad.

### 1.1 Semántica, punto por punto

Todas son decisiones explícitas de Jaume, no criterios de la IA.

| Concepto | Comportamiento |
|---|---|
| **Añadir** | % del EQUITY de la cuenta **o** una cifra fija en $ |
| **Quitar** | % de la posición FLOTANTE **o** $ de nocional |
| **Momento de ejecución** | **La vela INMEDIATAMENTE SIGUIENTE** a la que cumple la condición. Norma fija para todo: entradas, añadidos y reducciones |
| **Disparo** | Al pasar de "no se cumple" a "se cumple" **dentro del trade**. Una condición que ya se cumplía al entrar dispara en la primera barra |
| **Veces** | Cada pirámide puede disparar hasta N veces por trade (1 por defecto, tope 100) |
| **Modo Individual** | Cada pirámide vigila su condición por su cuenta, como entradas independientes. Un "quitar" puede ejecutarse sin esperar a los "añadir" |
| **Modo Secuencial** | **Lineal**: solo vigila el primer nivel que no haya agotado sus veces; cuando las agota se pasa al siguiente y **el anterior ya no dispara más** en ese trade |
| **Reentrada** | Rearma la secuencia entera (contadores y estado de señal) |
| **Niveles de SL/TP** | Anclados al precio de entrada **ORIGINAL**. Piramidar NO mueve el stop |
| **Ejecución de SL / TP completo** | Se llevan **toda la posición viva**, añadidos incluidos |
| **TP parciales** | Base = **inicial + añadido − reducido** (§1.2) |
| **Tope de caja** | Entrada + añadidos nunca comprometen más capital del que hay (§1.3) |

> ⚠️ **Consecuencia contraintuitiva y deliberada.** Los niveles siguen anclados a
> la entrada original pero se ejecutan sobre la posición viva. Un trade
> piramidado puede por tanto **perder varias R al saltar el stop**: la distancia
> es (precio medio → stop), sobre más acciones de las dimensionadas. No es un
> bug. Si tu implementación recalcula el stop al piramidar, los números NO
> cuadrarán con los nuestros.

### 1.2 La base de los TP parciales — la regla que más cuesta acertar

Jaume la fijó con tres casos, y solo una fórmula los satisface los tres:

| Caso | Debe cerrar |
|---|---|
| Sin piramidar, dos TP del 50% | el 100% (50 + 50) |
| Entrada 1000 acc + añadido 1000, TP del 50% | 1000 acc |
| Tras piramidar la posición vale 700, TP del 50% | 350 |

**Fórmula: `base = inicial + añadido − reducido`**, SIN descontar los parciales
ya tomados. En el motor es la variable `pyr_base`.

⚠️ **Trampa que nos costó encontrarla.** El código tenía
`pt_size = (size if pyramid_mode else original_size) * cap_frac`, y
`pyramid_mode` significa "hay niveles configurados", no "ha piramidado". Efecto
medido: con parciales 50%+50%, **configurar una pirámide que NUNCA dispara**
cambiaba el backtest de cerrar el 100% a cerrar 50% + 25%, dejando **un 25%
abierto hasta el cierre** (PnL 4,50 → 5,50 en el caso de prueba). Si tu
implementación usa la posición flotante, verifica este caso.

### 1.3 El tope de caja

> *«Eso que añadimos NUNCA debe ser mayor que el capital total del que
> disponemos... no en flotante sino sin contar con el flotante.»* — Jaume

```
comprometido = avg_entry_price × size      (al COSTE, no al precio actual)
disponible   = (init_cash + realized_pnl) − comprometido
add_cash     = min(add_cash_pedido, disponible)
```

Si no cabe entero **se recorta**, no se anula, y queda anotado en la ejecución
(`recortado_por_caja`).

⚠️ Lo que había antes medía las acciones vivas **al precio ACTUAL**, así que el
margen se encogía justo cuando el trade iba ganando, y con la entrada al 100%
del equity **ningún añadido se ejecutaba jamás, en silencio**.

---

## 2. Contrato de datos

Bloque opcional en la definición de estrategia:

```jsonc
"pyramiding": {
  "timeframe": "1m",
  "mode": "individual",          // "individual" | "sequential"
  "levels": [
    {
      "action": "add",           // "add" | "reduce"
      "unit": "pct",             // "pct" (por defecto) | "usd"
      "capital_pct": 2,          // % si unit=pct; DÓLARES si unit=usd
      "times": 1,                // disparos máximos por trade (1..100)
      "root_condition": { /* mismo árbol que entry_logic */ }
    }
  ]
}
```

**La clave solo viaja si el toggle está ON y hay niveles con condiciones.** Sin
piramidar, la definición queda byte-idéntica a las de siempre.

### 2.1 Salida: `executions[]` por trade

Cada trade puede traer el detalle cronológico de TODAS sus ejecuciones:

```jsonc
"executions": [
  {"kind": "entry",  "time_epoch": 1724135580, "price": 1.72827, "size": 306.17, "label": "Entrada"},
  {"kind": "add",    "time_epoch": 1724138460, "price": 1.50849, "size": 132.58, "label": "Pirámide 2: añade"},
  {"kind": "reduce", "time_epoch": 1724140000, "price": 1.55,    "size": 100.0,  "label": "Pirámide 3: reduce"},
  {"kind": "exit",   "time_epoch": 1724146140, "price": 1.5015,  "size": 306.17, "label": "EOD"}
]
```

Es **puramente informativo**: no entra en ninguna suma ni métrica. Solo se emite
cuando hubo más que entrada + cierre. El gráfico pinta un marcador por ejecución.

### 2.2 `entry_price` vs `avg_entry_price`

**Cambio de contrato que rompe compatibilidad de lectura.** Antes `entry_price`
llevaba el precio MEDIO ponderado. Ahora:

- `entry_price` = el fill **REAL** de la entrada (lo que se pinta y se lee).
- `avg_entry_price` = el precio medio ponderado, **el que gobierna el PnL**.

Sin piramidar coinciden. La prueba de que hacía falta: la misma entrada aparecía
con precios distintos (1,63 / 1,51 / 1,66) en tres corridas que solo variaban en
cuánto añadía la pirámide, y el gráfico etiquetaba la vela de entrada con un
precio que esa vela nunca tocó.

⚠️ Si consumes `entry_price` para calcular capital o rentabilidad, **cámbialo a
`avg_entry_price`**. Nosotros lo hicimos en `_group_partial_exits`.

---

## 3. Arquitectura — dónde vive cada cosa

### 3.1 Los CUATRO caminos que deben coincidir

Esto es lo más importante para integrar sin romper nada. El repo tiene:

| | Camino A | Camino B | Suite que los ata |
|---|---|---|---|
| **Simulación** | `portfolio_sim.py` (Python, especificación) | `portfolio_sim_jit.py` (Numba) | `test_sim_jit_equivalence` (tolerancia 0) |
| **Evaluación** | clásico (`_align_signals_to_1m`) | nativo (`_align_native_to_1m`) | `test_n2a_*_equivalence`, `test_run_backtest_slab_equivalence`, `test_accum_fast_equivalence` |

**Un cambio de lógica hay que aplicarlo a los cuatro.** Nos pasó: tocamos solo
el camino clásico y rompimos 6 tests de equivalencia sin darnos cuenta (§6.2).

### 3.2 Ruteo

`sim_dispatch.simulate` manda al motor **Python** cualquier estrategia con
niveles de pirámide; sin niveles retira el kwarg y el camino es exactamente el
de antes. **El kernel JIT no soporta piramidación** — pendiente de portar, solo
rendimiento.

### 3.3 Ficheros

**Backend**
- `services/portfolio_sim.py` — el motor: bloque de pirámide, `pyr_base`,
  `pyr_prev_sig`, `pyr_fired`, `pyr_exec`, tope de caja, `entry_price` real.
- `services/portfolio_sim_jit.py` — solo el fix del trailing, EN PARIDAD.
- `services/strategy_engine.py` — compila `pyramiding` (`unit`, `amount_usd`,
  `max_fires`), evalúa las señales por nivel, comparador desconocido,
  alineación de cruces en tf superior.
- `services/backtest_service.py` — `_build_executions()`, el agrupador emite
  `executions[]`, `_enrich_trades` propaga `avg_entry_price`.
- `services/backtest_signals.py` — `_enrich_trades_arr` propaga `avg_entry_price`.
- `services/sim_dispatch.py` — `avg_entry_price` en el envoltorio del JIT.
- `schemas/strategy.py` + `routers/strategies.py` — persistir `pyramiding`.

**Frontend**
- `components/strategy-builder/PyramidingBuilder.tsx` — el bloque, selector %/$.
- `components/backtester/InlineStrategyBuilder.tsx` — el builder del Backtester.
- `app/backtester/page.tsx` — **seis** listas blancas que había que tocar (§4.1).
- `components/backtester/Chart.tsx` — un marcador por ejecución.
- `components/backtester/BacktestPanel.tsx` — resumen completo de la estrategia.
- `lib/api_backtester.ts`, `types/strategy.ts` — tipos.

---

## 4. Los 7 fallos encontrados y corregidos

Dos auditorías independientes del código más una batería de pruebas ejecutadas
contra el motor.

### 4.1 La clave `pyramiding` no llegaba al backend (piramidación)

El síntoma: *«ni aparecen las entradas ni parece que añada ni nada»*. La causa:
la definición de estrategia **se reconstruye campo a campo en TRES capas**, y
`pyramiding` no estaba en ninguna:

1. **Frontend** — `app/backtester/page.tsx`, SEIS sitios distintos.
2. **Esquema y router** — `StrategyCreate` sin el campo (pydantic v2 descarta lo
   desconocido **sin error 422**) y `definition_json` montado a mano.
3. **Enriquecido de trades** — `_enrich_trades` tiraba la bitácora de ejecuciones.

El backend hacía `strategy_def.get("pyramiding")`, no lo encontraba y **apagaba
la piramidación en silencio**.

> **Aviso para tu implementación:** si añades un campo a la definición, revisa
> las tres capas. Ninguna avisa cuando se le cae algo.

### 4.2 El trailing pisaba al stop fijo (MOTOR COMPARTIDO)

⚠️ **Afecta a cualquier estrategia con trailing + stop fijo, piramidada o no.**

El bloque del trailing no comprobaba si el stop fijo ya había disparado en esa
barra. Como el trailing se mueve con el **máximo de la propia vela** y luego se
compara con el mínimo de esa misma vela, una vela que tocaba el stop podía
registrarse como salida **en beneficio**:

| Long, entrada 100, stop fijo 98, trailing 3% | Antes | Ahora |
|---|---|---|
| Vela con high 104 y **low 97** (el stop se toca) | Trailing @ 101, **+1** | **SL @ 98, −2** |
| Vela con low 100,5 (el fijo no se toca) | Trailing @ 101, +1 | Trailing @ 101, +1 |

> **Regla de Jaume:** *«si el stop fijo se ejecuta quita todas las órdenes sí o
> sí, siempre irá por encima del trailing en importancia»*.

Aplicado en **los dos motores**. Verificado con 600 escenarios aleatorios de
trailing + stop fijo (long y short): **0 divergencias**.

### 4.3 Un comparador desconocido se evaluaba como "mayor que" (MOTOR COMPARTIDO)

`_apply_comparator` terminaba en `return source > target`. Una condición que
dijera "menor que" podía ejecutarse como "mayor que" —entrando justo en los
máximos— **sin error, sin aviso y sin rastro**. Ahora la condición queda
**desactivada** y se registra un ERROR.

⚠️ Detalle que lo hacía fácil de pisar: `schemas/strategy.py` declara
`DISTANCE_GT = "DISTANCE_GREATER_THAN"` — el **nombre** del enum y su **valor**
son distintos, y el frontend manda el nombre corto. El guard solo reconocía los
largos. Ahora acepta ambos.

### 4.4 Un cruce en timeframe superior duraba todo el tramo (MOTOR COMPARTIDO)

Al bajar una señal de 5m a la malla de 1m, valía para las 5 barras siguientes.
Correcto para un ESTADO ("el precio está bajo la EMA", que dura); **incorrecto
para un EVENTO**: un "cruza por debajo" permitía entrar hasta 4 minutos después
del cruce, con el precio ya movido.

| Vela de 5m que cumple, cierra al acabar 09:39 | Barras de 1m con señal |
|---|---|
| condición de ESTADO (`<`, `>`, …) | 09:39, 09:40, 09:41, 09:42, 09:43 |
| condición de CRUCE (`CROSSES_*`) | **solo 09:39** |

Aplicado en los **dos** caminos de evaluación.

**Extra:** una condición en timeframe **diario** sobre una sesión intradía no
tiene ninguna vela diaria cerrada en el rango → siempre falsa → 0 entradas **en
silencio**. Ahora lo registra como ERROR explicando por qué.

### 4.5 El tope de caja anulaba añadidos en silencio (piramidación)

Ver §1.3.

### 4.6 Los disparos no se rearmaban por trade (piramidación)

El disparo miraba el flanco del **array completo**, no del trade. Consecuencias:
una condición que ya se cumplía al entrar **no disparaba jamás**; y en modo
secuencial, si la condición del nivel 2 se cumplía mientras esperaba al 1, su
flanco se consumía y el nivel quedaba muerto para siempre.

### 4.7 Un disparo que no ejecutaba gastaba una "vez" (piramidación)

`pyr_fired` se incrementaba **antes** de validar precio y caja, así que un
intento descartado inutilizaba el nivel el resto del trade (con el default
veces=1, para siempre).

---

## 5. ⚠️ Lo que cambia resultados de backtests EXISTENTES

Cuatro de los siete tocan el motor compartido. **Un backtest guardado antes del
2026-08-23 puede dar números distintos al repetirlo:**

| Cambio | A quién afecta |
|---|---|
| El stop fijo manda sobre el trailing (§4.2) | cualquier estrategia con trailing **y** stop fijo |
| Comparador desconocido → condición apagada (§4.3) | solo definiciones mal formadas (antes daban resultados falsos) |
| Cruces en tf superior solo una barra (§4.4) | cualquier estrategia que mezcle temporalidades **con cruces** |
| `entry_price` pasa a ser el fill real (§2.2) | cualquier consumidor que lo usara para calcular capital |

Las estrategias 100% en 1m, sin trailing y sin piramidar **no se ven afectadas**.

---

## 6. Cifras de control (para verificar sin compartir datos)

### 6.1 Semántica de la piramidación

Reproducibles con velas sintéticas; cada una comprueba una regla:

| # | Escenario | Resultado esperado |
|---|---|---|
| 1 | Sin pirámide, 2 TP del 50% | cierra el 100% |
| 2 | Pirámide configurada que **nunca dispara** | resultado **idéntico** al de sin pirámide |
| 3 | Entrada 500 acc + añadido 500, TP del 50% | cierra 500 (50% de 1000) |
| 4 | Condición ya cierta al entrar | **dispara** en la primera barra |
| 5 | Secuencial: nivel 1 en barras 2 y 8, nivel 2 en 5 y 10 | dispara `(1,barra 2)` y `(2,barra 5)`; el 1 **no** vuelve en la 8 |
| 6 | Señal en la barra 2 (close 20), open de la barra 3 = 10 | el añadido se ejecuta **en la barra 3 a 10** |
| 7 | Entrada 10,00 + añadido 12,00 | `entry_price` = **10,00**, `avg_entry_price` = **11,612903** |
| 8 | Fijo: cuenta 100, apuesto 99, **pido añadir 2** | **añade 1**, total 100 |
| 9 | %: entrada 90%, dos añadidos del 10% | **entra el primero, el segundo no**; total 100% |
| 10 | Stop loss + reentrada | la pirámide dispara **en los dos trades** |

### 6.2 Regresión — cómo lo comprobamos (y cómo casi la liamos)

La suite completa arrastra ~119 fallos **preexistentes** en un entorno local sin
GCS. **"Pasan los tests" no significa nada.** El método que sí sirve:

1. ejecutar la suite CON los cambios y guardar la **lista de nombres** en rojo,
2. `git stash` de los ficheros tocados, ejecutar de nuevo, guardar la lista,
3. `git stash pop` y **restar las listas**.

La primera pasada delató **6 tests rotos**, todos de equivalencia entre caminos,
que un recuento global (125 vs 119) habría dejado pasar como ruido:

| Test roto | Causa |
|---|---|
| `test_accum_fast_equivalence::test_enrich_trades_arr_identical` | `avg_entry_price` solo en un enriquecedor |
| `test_n2a_e2e_equivalence` (2) + `test_n2a_native_equivalence::test_crosses_en_timeframe_5m` | el fix de los cruces solo en el camino clásico |
| `test_run_backtest_slab_equivalence` (2) | lo mismo, vía slab |

Corregidos, la comparación final da **119 con cambios y 119 sin ellos, 0 rotos**.
Más **30/30** en las suites de paridad de motores y `tsc --noEmit` con 0 errores.

### 6.3 Caso real de extremo a extremo

Backtest sobre un dataset de 258 ticker-días con 2 niveles de pirámide:

| Corrida | Trades | Retorno | Añadidos | Reducciones |
|---|---|---|---|---|
| **Sin pirámide** (control) | 396 | **+7,6149%** | — | — |
| Con pirámide en **%** (add 5% equity / reduce 50%) | 396 | −0,9344% | 330 | 201 |
| Con pirámide en **$** (500 $/disparo) | 481 | −53,1474% | 302 | 184 |

La corrida sin pirámide sale **bit a bit idéntica** a la de referencia previa
—mismos 396 trades, mismo ticker, fecha, PnL y tamaño en todos—, que es la
verificación de la regla nº1.

---

## 7. Hallazgos NO corregidos (decisión de Jaume)

- **La definición de estrategia no se valida contra pydantic**
  (`backtest_orchestrator` la recibe como `dict` desnudo). **Reportado y NO
  arreglado por decisión expresa.** Se midió el alcance real: casi toda la
  basura **apaga** la condición (indicador inexistente, tipo inventado, sin
  target → 0 barras; `period` como texto → excepción), lo que deja el backtest
  en 0 trades e imposible de no notar. Solo **tres** entradas producen un
  backtest creíble y falso: `period` **negativo** (60/60 barras en True),
  `offset` **negativo** (lookahead: compara contra el futuro) y **timeframe
  inválido**. Ninguna alcanzable desde la interfaz.
- **El kernel JIT no soporta piramidación** (solo rendimiento). Aplazado.

---

## 8. Notas de integración

1. **`entry_price` cambió de significado** (§2.2). Es lo primero que hay que
   revisar en cualquier consumidor.
2. **Los cuatro caminos** (§3.1): aplica cada cambio de lógica a los cuatro o
   romperás las suites de equivalencia.
3. **Cuatro cambios afectan al motor compartido** (§5). Si mantienes tus propios
   números de referencia, regenéralos.
4. **La suite local sin GCS arrastra ~119 fallos**; usa la comparación por
   listas de §6.2, nunca el recuento.
5. `pyramid_mode` significa "hay niveles configurados", no "ha piramidado". Fue
   la fuente del fallo más sutil (§1.2).
