# PRD — Guard de SL estructural invalidado + fallback "Previous Max" (2026-08-27)

**Para:** Jaime. **De:** Álvaro (con GLM).
**Ámbito:** motor de backtest (portfolio_sim + kernel Numba) + UI del strategy
builder y del chart. **Commits en `alvaro-rama-desarrollo`:** `dfa6e51`
(motor + fallback + UI del apartado de SL) y `c79993d` (SL pintado en el
chart + regla de medición + fix de hidratación). Tests:
`backend/tests/test_hs_invalid_sl_guard.py`.

---

## 1. Resumen en una frase

Un stop de Market Structure (PMH/HOD/LOD/PML/Previous…) que al entrar quedaba
en el **lado ganador** del precio (ej. un corto cuando la acción ya había
saltado por encima del PMH) generaba en el backtest un **beneficio instantáneo
imposible**: eso ya no puede ocurrir — la entrada se salta — y además se puede
configurar un **nivel de respaldo** (típicamente "Previous Max": el último alto
antes de entrar) para rescatar reentradas, u opcionalmente también la primera
entrada.

## 2. El bug, con números

**Qué pasaba.** En corto, el stop se comprueba con `high >= SL` y el fill se
hace a `min(SL, high)`. Si el PMH ya estaba roto al entrar, el SL quedaba
**por debajo** del precio: el chequeo se cumplía en la propia vela de entrada
y el simulador vendía al precio del PMH — un precio que esa vela ni siquiera
tocó. Beneficio garantizado del tamaño del salto, sin riesgo, contado como
salida "SL".

**Ejemplo real (NITO 2025-01-03, run manual de RTH 2.3):** tres trades
entrando en corto a 3,19/3,17/3,09 con "SL" en 2,48 — por debajo de la
entrada — que salían **en 0 velas** a 2,48 cobrando +0,22 $ cada uno.
Físicamente imposible: nadie rellena una venta 22 % por debajo del mercado.

**Magnitud (run manual RTH 2.3 del 27/08, 1.261 trades):**

| | Run con bug (18:57) | Runs con fix (19:08 / 19:10) |
|---|---|---|
| Trades | 1.261 | 763 / 797 |
| Win rate | 70,7 % | 48,0 % / 49,1 % |
| Profit factor | 3,78 | 1,37 / 1,35 |
| PnL total | +82,39 $ | +11,08 $ / +11,29 $ |
| SL por debajo de la entrada | **540** | **0** |
| Salidas "SL" ganadoras en ≤1 vela | **540** | **0** |

El 43 % de los trades eran fills fantasma y aportaban el **87 % del PnL**.
La estrategia "buena" era mediocre (PF ≈ 1,36) más el bug imprimiendo dinero.
**Cualquier run anterior a esta fecha con SL de Market Structure está
inflado y no es comparable** — mismo aviso de semántica que hicimos con el
fix de splits.

## 3. La lógica nueva (qué hace el motor ahora)

1. **Guard, siempre activo, no configurable.** Para stops de tipo Market
   Structure se valida el **lado** del nivel calculado al precio REAL de
   entrada (apertura de la vela siguiente a la señal): en corto el SL debe
   quedar **estrictamente por encima** de la entrada; en largo,
   estrictamente por debajo (y positivo). Si no, la premisa del stop está
   muerta: **esa entrada no se hace**. Los stops porcentuales no se tocan
   (son válidos por construcción).
2. **`hard_stop.fallback_value`** (opcional, ej. `"Previous Max"`): si el
   nivel principal está invalidado en una **REENTRADA** (tras un stop-out es
   normal volver a entrar con el nivel ya rebasado), el SL se recalcula
   desde el nivel de respaldo **aplicando el mismo offset** (`operator` +
   `offset_pct`) que el principal. Valores: los mismos que `value`
   (HOD/LOD/PMH/PML/"Previous Max"/"Previous Min").
3. **`hard_stop.fallback_first_entry: true`** (opcional, checkbox): el
   respaldo rescata **también la primera entrada** con el nivel invalidado,
   no solo las reentradas.
4. Si el nivel de respaldo **también** queda invalidado → no se entra.
   Sin respaldo configurado → comportamiento del punto 1 puro.

Matriz de configuración:

| Configuración | 1ª entrada con nivel rebasado | Reentrada con nivel rebasado |
|---|---|---|
| Sin respaldo (default) | no se entra | no se entra |
| `fallback_value` | no se entra | entra con SL en el respaldo |
| `fallback_value` + `fallback_first_entry` | entra con SL en el respaldo | entra con SL en el respaldo |

**Por qué NO es look-ahead:** la serie `pm_high` ya era causal (PMH acumulado
barra a barra, completo a las 09:30; se arregló en su día). Para entradas RTH
el premarket entero es información conocida. El bug no era de información
futura: era un stop en el lado inválido **más un fill a un precio fuera del
rango de la vela**. El "Previous Max" del respaldo es el running HOD con
shift de 1 barra (el último alto antes de la señal), también causal.

## 4. Qué se tocó (y qué no)

**Backend (paridad Python ↔ Numba bit a bit, obligatoria en este motor):**
- `portfolio_sim.py` — helpers `_structural_level` y `_sl_side_valid`; guard
  + fallback en la colocación del SL de entrada; params `hs_fallback_value`
  y `hs_fallback_first`.
- `portfolio_sim_jit.py` — kernel: mismos códigos `HS_*` para el respaldo
  (`hs_fallback_code`) + flag `hs_fallback_first`; misma semántica.
- `sim_dispatch.py` — passthrough a Python y codificación al JIT con tabla
  compartida `_hs_value_to_code` (principal y respaldo no pueden divergir).
- `backtest_service.py` (camino secuencial) y `backtest_signals.py`
  (`_corre_uno`, caminos slab/paralelo) — leen `fallback_value` /
  `fallback_first_entry` del `hard_stop` del JSON de la estrategia.

**Frontend:** apartado "Si el nivel ya está rebasado al entrar" en
`RiskManagement.tsx` (desplegable + checkbox, textos dinámicos según nivel y
bias), `fallback_value`/`fallback_first_entry` en `types/strategy.ts`, bias
pasado desde los dos builders. En `c79993d`: el `stop_loss` pintado como
línea discontinua en el chart de análisis por trade, una regla de medición
estilo TradingView, y un fix de hidratación en `InlineDatasetBuilder`
(fechas calculadas a nivel de módulo).

**NO se tocó:** `backtester/engine.py` (ruta muerta — solo tests/scripts),
los stops porcentuales/fijos/ATR, la serie causal de PMH/PML, el sizing, y
ningún esquema de datos. `hard_stop` sigue siendo un dict libre: **cero
migraciones**.

## 5. Tests

`backend/tests/test_hs_invalid_sl_guard.py` (30 tests): semántica del guard
en corto y su espejo en largo, fallback solo-reentradas, flag de primera
entrada, respaldo también invalido, **paridad Python↔JIT en los 10
escenarios**, invariante "ningún trade con SL en el lado ganador", y **3 e2e**
por `run_backtest` que prueban que los campos viajan desde el JSON de la
estrategia hasta el simulador (incluido un día con el PMH roto desde el
arranque). Además el grid masivo de `test_sim_jit_equivalence.py` ahora
muestrea `fallback_value` (59/220 configs lo ejercitan). Estado: 37/37 ✓.

## 6. Verificación rápida (5 minutos)

1. `pytest tests/test_hs_invalid_sl_guard.py tests/test_sim_jit_equivalence.py -v`
   → 37 passed.
2. Relanzar un backtest corto con SL = PMH: en la tabla de trades, ningún
   short con `stop_loss < entry_price`, y ningún "SL" ganador en la vela de
   entrada. En el chart, la línea roja discontinua del SL queda SIEMPRE por
   encima de la entrada.
3. Comparar contra un run guardado de antes del 27/08: los trades que
   "faltan" (≈40 %) son los fills fantasma.

## 7. Prompt para la IA de Jaime

```text
Contexto: trabajamos en el repo edgecute_app (backtester BTT). Mi socio
Álvaro ha arreglado un bug grave del motor de simulación y quiero que me
ayudes a revisarlo e integrarlo. Todo el detalle está en
docs/PRD_GUARD_SL_ESTRUCTURAL_FALLBACK_20260827.md — LEELO ENTERO primero.

Tu trabajo:
1. Resúmeme con tus palabras el bug y la semántica nueva del guard + los
   dos campos nuevos (fallback_value, fallback_first_entry), para
   confirmar que lo hemos entendido igual.
2. Revisa el diff de los commits dfa6e51 y c79993d de la rama
   alvaro-rama-desarrollo (git show dfa6e51 / c79993d). Confirma que:
   a) el guard y el fallback están implementados IDÉNTICOS en
      portfolio_sim.py y portfolio_sim_jit.py (paridad bit a bit),
   b) el campo viaja desde el JSON de la estrategia hasta el simulador en
      los dos caminos (backtest_service secuencial y backtest_signals
      slab/paralelo), y c) no se ha tocado ninguna otra lógica de stops.
3. Ejecuta: cd backend && .venv/Scripts/python.exe -m pytest
   tests/test_hs_invalid_sl_guard.py tests/test_sim_jit_equivalence.py -v
   (deben pasar 37 tests). Antes de tocar nada verifica que backend/.env
   tiene DISABLE_GCS_SYNC=true y LIVE_SCREENER_ENABLED=false (regla del
   AGENTS.md: nunca arrancar el backend sin eso).
4. Comprueba si mi rama (jaumen-rama-desarrollo) diverge de
   alvaro-rama-desarrollo en portfolio_sim.py / portfolio_sim_jit.py /
   sim_dispatch.py: si hay cambios solapados, muéstrame el conflicto
   ANTES de mergear.
5. Si está todo verde, prepárame el merge a staging (sin tocar main ni
   develop, y sin push sin mi confirmación explícita).
Importante: cualquier backtest guardado antes del 2026-08-27 con SL de
Market Structure está inflado por el bug (hasta el 87 % del PnL podía ser
fills fantasma). No compares curvas nuevas contra runs viejos.
```

## 8. Nota final

Este cambio **redefine qué resultados son reales**. La discusión de producto
que abre: ¿qué estrategias de las guardadas sobreviven al motor honesto? La
primitiva "rescatar con Previous Max" (reentradas o también primera entrada)
es la palanca para recuperar parte de esos setup ahora con stops reales —
pero cada trade rescatado puede perder toda la distancia hasta ese último
alto, así que hay que re-optimizar con el motor nuevo.
