# PRD — Estilo Cangrejo: acotar cada trade "o por recorrido del SL, o por pérdida máxima"

> **Para:** Jaume (y su IA). **De:** Álvaro. **Fecha:** 2026-09-07.
> **Estado:** implementado y verificado en la rama `alvaro-rama-desarrollo`
> (pendiente del flujo habitual de PR a staging). Este documento se sube a
> staging por adelantado para que se pueda entender y comentar sin esperar al
> merge.

---

## 1. El problema, en una frase

Con SL por market structure (p. ej. previous max + 10%), la distancia al stop
cambia en cada entrada: con el mismo market value, unos stops te cuestan poco
y otros te cuestan muchísimo — y no había manera sencilla de ponerle techo.

## 2. La solución: dos modos, "o una u otra"

Nueva tarjeta **Estilo Cangrejo** en el Risk Management del builder, debajo de
todo lo del Stop Loss. Se enciende y eliges **UNO** de dos modos (excluyentes
entre sí — decisión de Álvaro: "debe ser o una u otra"):

### Modo A — "Recorrido máx. del SL" (apretar el stop lejano)

**Un campo:** distancia máxima entry → SL, en %.

- El stop se queda donde dice la estructura, **pero si queda a más de ese % del
  precio de entrada, se aprieta hasta ese %** — y la salida real pasa a ser el
  stop apretado (el motor sale ahí, no en el nivel original).
- **Cambia DÓNDE sales, no cuánto pones.**
- Ejemplo: entras a 1,00 y el previous max + 10% te pone el SL en 2,00 (100%
  de recorrido). Con tope al 50%, el SL se aprieta a 1,50 y ahí se sale.

### Modo B — "Pérdida máx. por trade" (encoger el tamaño)

**Un campo:** % máximo de la cuenta a perder en un trade.

- El stop NO se toca: se queda donde dice la estructura. Lo que se encoge es
  el **tamaño de la posición**, para que el recorrido hasta el SL no cueste
  más de ese % de la cuenta.
- **Cambia CUÁNTO pones, no dónde sales.**
- Ejemplo: cuenta de 10.000, tope de pérdida 3% (300 $) y SL al 100% de
  distancia → el motor dimensiona a 300 $ de market value (300 $ / 1,00 de
  recorrido). El stop sigue en 2,00; si salta, pierdes 300 $, no 10.000.

**Reglas comunes a los dos modos:**

- Son **techos, no modos de cálculo**: se aplican SOBRE el sizing que ya
  exista (MV clásico, por distancia al SL o híbrido) y **solo recortan,
  nunca agrandan**.
- Aplican a cada entrada, reentradas incluidas (cada una es una posición
  nueva).
- Exclusivos con el **Stop Loss Híbrido**: encender uno apaga el otro en la
  UI; si un payload llegara con los dos, el motor arbitra a favor de Cangrejo
  (test dedicado). La lógica del híbrido de Jaume **no se ha tocado**.

## 3. Por qué así (y no con más campos)

La primera versión de la tarjeta tenía 4 topes independientes (distancia,
pérdida, MV de entrada, MV por nivel de pirámide). Se probó con la estrategia
1B y resultó **poco intuitiva y mal explicada**: cuatro números sueltos no
cuentan qué va a pasar. Decisión de Álvaro (2026-09-07): simplificar a los dos
modos de arriba, uno visible cada vez. Los topes de MV siguen **admitidos por
el motor** (inertos, en `None`) por si algún día vuelven a la UI; la tarjeta
los limpia al activarse para que ningún borrador viejo arrastre capas
invisibles.

## 4. Detalles de implementación que interesan al equipo

- Campos en `risk_management`: `cangrejo_active`, `cangrejo_mode`
  ("recorrido" | "perdida", solo UI), `cangrejo_max_sl_dist_pct`,
  `cangrejo_max_loss_at_sl_pct`, `cangrejo_max_mv_entry_pct` y
  `cangrejo_max_mv_pyr_pct` (los dos últimos inertos sin UI). Declarados en
  el esquema pydantic desde el día 1 — la lección de las TRES CAPAS.
- El apretado del stop (Modo A) va **antes de dimensionar** y gobierna también
  la salida: el bloque de exits usa el stop apretado, y el trailing ya no
  puede quedar por detrás de él. Sin Cangrejo activo, el cálculo del exit es
  bit a bit el de siempre (verificado).
- El tope de pérdida (Modo B) usa la distancia final (tras apretar, si el
  Modo A estuviera en un payload) y la base de equity viva
  (`hybrid_capital` si viene — lo usará el bot —, si no `init_cash + realized`).
- Con Cangrejo activo la simulación va **siempre al motor Python** (el kernel
  Numba no lo implementa; mismo tratamiento que el híbrido, vigilado por test).
- **Bot de alertas: NO se ha tocado nada.** Único aviso a futuro: el
  dispatcher ya respeta `hybrid_capital` como base de los topes Cangrejo
  (fix del 2026-09-07 tras la auditoría) para cuando el bot pase ese
  parámetro.

## 5. Verificación

- 19 tests propios (`backend/tests/test_estilo_cangrejo.py`): matemática de
  cada modo, el stop apretado mueve la salida real, exclusividad con el
  híbrido, regla nº1 (sin campos = resultado idéntico) y las TRES CAPAS.
- **Auditoría independiente** (2026-09-07): contra el código anterior
  commit a commit — 123 comparaciones de invarianza en 25 escenarios + 400
  configs aleatorias, **cero divergencias** (incluido JIT activado);
  recortes exactos a la fórmula; plumbing verificado de punta a punta
  capturando los kwargs reales; incidente "resultados idénticos con Cangrejo"
  reproducido end-to-end vía HTTP y explicado (con riesgo 0,5 % y topes al
  5 %, los topes no pueden morder — comportamiento correcto, no bug).
- Suite completa del backend: 733 passed, 86 skipped.

## 6. Dónde está el código

Rama `alvaro-rama-desarrollo`: `schemas/strategy.py`, `portfolio_sim.py`,
`sim_dispatch.py`, `backtest_signals.py`, `backtest_service.py`,
`backtest_orchestrator.py`, `tests/test_estilo_cangrejo.py`,
`frontend/types/strategy.ts` y `frontend/.../RiskManagement.tsx`.

---

## 7. Implementación en `sailor` (Claude, 2026-09-08) — LEER ANTES DE COMPARAR

**El código de la rama `alvaro-rama-desarrollo` nunca llegó al remoto.** Un
`git fetch --all --prune` el 2026-09-08 la deja en el **30-ago**, y el único
objeto "cangrejo" de todo el repo es este `.md`. Así que lo de `sailor` es una
implementación **desde este documento**, no un merge de la rama de Álvaro.

La semántica de los dos modos es la del §2, sin cambios. Hay **tres
divergencias deliberadas** que hay que contrastar antes de dar por buena
ninguna comparación de resultados entre las dos ramas:

### 7.1 Con Cangrejo activo NO se cae al motor Python

El §4 dice que la simulación va siempre al Python. Aquí los dos modos están
portados al kernel Numba (`portfolio_sim_jit.py`), con paridad verificada:
**400 configuraciones aleatorias, cero divergencias**, más los casos dirigidos
de `test_estilo_cangrejo.py`.

El motivo es el genético: evalúa miles de individuos, y forzar el motor lento
multiplicaba cada corrida. Medido, ×1,7 en un ticker-día de 390 velas — y sobre
todo desaparece la caída al Python.

El **híbrido sí sigue yendo al Python** (no se ha portado). Con los dos
encendidos el híbrido está muerto por el arbitraje, así que el kernel es válido
y el dispatcher no desvía; eso tiene test propio en las dos direcciones.

Los parámetros llegan al kernel como floats con centinela `0.0 = sin tope`:
numba no admite `Optional` en un `njit(cache=True)` sin disparar una firma nueva
por cada combinación.

### 7.2 El Modo B topa también los añadidos de pirámide

El §2 solo habla de entradas y reentradas. Sin extenderlo a los añadidos, el
techo se esquiva entero en cuanto la estrategia piramida: se entra con el tamaño
topado y se añade sin mirar — sin error y sin log.

La pérdida al stop de la posición completa es **separable**, así que el cupo del
añadido sale sin recalcular el precio medio:

    pérdida_total = |avg − stop| × size + |add_px − stop| × add

y de ahí `margen = (cupo − gastado) / |add_px − stop|`. Si no queda margen, el
añadido no se ejecuta. Tres tests.

### 7.3 El Modo B no exige `size_by_sl`

A diferencia del híbrido. Es un techo sobre el sizing que ya haya, y con sizing
por valor de mercado es justo donde la pérdida al stop se descontrola.

### 7.4 El bot de alertas SÍ se ha tocado

El §4 lo dejaba intacto. Se ha extendido porque, si no, el aviso diría una cosa
y el backtest haría otra sin que nada avisara:

- `_kwargs_simulate` pasa los tres campos al simulador interno, con
  `hybrid_capital` como base del Modo B (el `init_cash` del bot es el nominal de
  1e9: sobre eso el techo no recortaría jamás).
- El aviso da el stop **apretado** por el Modo A, que es donde el motor sale.
- `calcular_acciones` aplica el Modo B en las dos ramas (con y sin `size_by_sl`).
- `_hibrido_de` devuelve `None` con Cangrejo activo — el mismo arbitraje.
- `/watch` no deja activar el Modo B sin capital de cuenta.

**Un bot ya en marcha no lo coge:** importa del backend por `sys.path`, así que
hay que reiniciarlo (y volver a encender el interruptor, que arranca en
«Parado»).

### 7.5 En el genético NO es un gen

Va en el panel de la corrida (modo explorar) y sale de la estrategia (modo
mejorar), igual que el híbrido. Dejar que la corrida mueva el `%` del Modo A
sería buscar en el histórico el recorte que mejor queda, y ese número cambia
DÓNDE se sale: el sobreajuste sería inmediato.

### 7.6 Verificación

36 tests propios en `backend/tests/test_estilo_cangrejo.py`; **855 passed /
88 skipped** en `backend/tests`; `tsc --noEmit` limpio; 400 configuraciones
aleatorias Python↔JIT sin divergencias y 94 comprobaciones de invarianza con
Cangrejo apagado.
