# PRD — Fix del `stop_loss`/`entry_price` del trade contaminados por el SL por lote (para ejecutar por GLM)

- **Fecha:** 2026-09-18
- **Autor:** Álvaro (decisión) + Claude Opus 5 (hallazgo, evidencia y redacción)
- **Origen:** `[HALLAZGO · 2026-09-18 · 01]` en `docs/MEMORIA_MADRE.md`
- **Aplica sobre:** `alvaro-rama-desarrollo` a la altura de `c720319` (con el
  merge de `staging` ya integrado)
- **Severidad:** bug de reporte. No altera PnL ni ninguna métrica de dinero,
  pero deja mal `stop_loss` y `entry_price` en el 28 % de los trades de una
  corrida con SL por lote — y con ellos el visor de «Análisis por trade».
- **No toca el bot de avisos** ni `market_frame.py`.
- **Reglas del repo vigentes:** trabajo en la rama de quien lo aplique,
  integración a `staging` por merge, `main` intocable, confirmación explícita
  antes de cualquier `push`.

---

## 1. Resumen en una frase

Cuando el SL de un lote de piramidación salta **antes** que cualquier parcial o
que el cierre del trade, la fusión de legs (`dict(first)`) le pega al trade
entero el `entry_price` y el `stop_loss` **del lote**, y el stop real del trade
no se guarda en ninguna parte.

---

## 2. Qué NO es el bug (leer antes de tocar nada)

Esto se verificó expresamente porque es la confusión natural:

- **Una piramidación SIN SL propio hereda el stop general, y eso está bien.**
  Es el diseño, se reporta bien y se pinta bien: sin `sl_px` el visor no dibuja
  ni chip de SL ni punteada de lote, y la única línea roja es la del trade.
- **Dos lotes contra el mismo pivote comparten cinturón, y eso también está
  bien.** Ya está documentado en `[TRABAJO · 2026-09-17 · 7]`.
- **El motor de simulación (`portfolio_sim.py`) calcula bien los dos stops.**
  El leg del lote DEBE llevar `entry_price = px del añadido` y
  `stop_loss = nivel del lote`: es lo que exige el PRD del SL por lote (§3.3,
  PnL del lote contra su propio precio) y lo que fijan los tests
  `test_lot_stop_sim.py:100-102`. **Eso no se toca.**

El defecto está **solo** en la capa de reporte que fusiona los legs en un trade.

---

## 3. Evidencia

Corrida guardada `f72bbf33-151c-480c-abdd-9999c9f4df73` (users.duckdb,
2026-09-18 10:40, 1831 trades; `hard_stop` = Previous Max +10 %,
`lot_stop` = Último pivote alto w2 +5 %).

Trade **ATMV 2025-12-09**, tal como quedó guardado:

```
entry_price = 9.30   stop_loss = 10.248   exit_reason = 'SL'   exit_price = 13.574
  entry     05:41  @ 9.30    sl_px=None
  add       05:43  @ 9.30    sl_px=10.248     <- pirámide 1
  lot_stop  07:08  @ 10.248  sl_px=10.248     <- salta el cinturón del lote
  add       08:01  @ 10.87   sl_px=13.0725
  add       08:03  @ 10.75   sl_px=13.0725
  exit      08:20  @ 13.574  (SL)
```

El trade salió por SL en **13.574** (= Previous Max 12.34 × 1.10, verificado
sobre el parquet del lago) pero reporta `stop_loss = 10.248`, que es
9.76 × 1.05 — el último pivote alto (w=2) vigente a las 05:42, o sea el
`sl_px` del añadido.

Desglose de esa corrida por lo que hace el lote:

| grupo | trades | salidas por `SL` | `stop_loss` ≠ precio de salida |
|---|---:|---:|---:|
| sin piramidación | 322 | 140 | **0** |
| pirámide con `lot_stop` que NO saltó | 966 | 80 | **0** |
| `lot_stop` saltó pero NO fue el primer cierre | 22 | 5 | **0** |
| `lot_stop` saltó **y fue el primer cierre** | 521 | 276 | **274** |

Y 520 de esos 521 tienen además `entry_price` == el precio del añadido de ese
lote, no el de la entrada.

**Control (el caso sano):** 12 corridas guardadas de estrategias con
piramidación y CERO `lot_stop` (`6b058a06`, `d4a49232`, `1ebce568`, `71789b34`,
`234aa8cf`, `8d6a1555`, `ab9649a0`, `d2beecaa`, `e1c411a9`, `f1e8d3be`,
`04ad5550`, `16dccb9f`): entre 79 y 258 salidas por `SL` con añadidos en cada
una, **0 discrepancias en todas**. Mismo ticker-día como contraste directo —
ALCE 2025-01-02: sin `lot_stop` reporta `stop_loss = 1.815` = `exit_price`
(correcto); con `lot_stop` reporta `stop_loss = 1.512` y sale en 1.815.

---

## 4. Causa raíz (rutas y líneas exactas)

1. **`backend/app/services/portfolio_sim.py:1554-1573`** — el cierre por SL de
   lote emite un leg con identidad PROPIA:
   `"entry_price": round(_lot["px"], 6)` y `"stop_loss": round(_lot["sl_px"], 6)`.
   Es el **único** leg del motor que hace eso: todos los demás (parciales,
   reducciones, escalera, cierre final) usan `entry_price` y `trade_sl_price`,
   las variables del trade.
2. **`backend/app/services/backtest_service.py:1732`** —
   `_group_partial_exits._flush` hace `trade = dict(first)`. El grupo son los
   legs consecutivos con el mismo `entry_idx`, en orden cronológico de cierre:
   si el lote salta antes que el primer parcial, ese leg **es** `first`, y sus
   dos campos propios pasan al trade fusionado.
3. **`backend/app/services/backtest_service.py:1600-1605`** —
   `_build_executions` construye la ejecución `entry` con
   `first.get("entry_price")`, o sea del mismo leg contaminado: por eso el
   marcador de entrada del gráfico también muestra el precio del añadido.
4. **`frontend/src/components/backtester/Chart.tsx:916-917`** — el visor pinta
   `t.stop_loss` en rojo con la etiqueta «SL». No hay bug aquí: pinta fielmente
   lo que le llega. Se arregla solo cuando el dato llegue bien.

---

## 5. Diseño del fix

Dos cambios, ambos en backend. **Nada en el frontend.**

### 5.1 Que el leg del lote lleve también la identidad del TRADE

`backend/app/services/portfolio_sim.py`, en el `trades.append({...})` del
bloque de SL por lote (~línea 1554), añadir dos claves al final del dict:

```python
    # La identidad del TRADE viaja con el leg para que la fusión pueda
    # restaurarla: este es el único leg con entrada y stop propios, y si es
    # el primero del grupo `dict(first)` se los pega al trade entero.
    "trade_entry_price": round(entry_price, 6),
    "trade_stop_loss": round(trade_sl_price, 6),
```

`entry_price` y `trade_sl_price` están vivas en ese scope (son las mismas que
usan los demás legs). Son campos **informativos**: no entran en ningún cálculo
de PnL, tamaño ni métrica.

### 5.2 Que la fusión no confunda la identidad del lote con la del trade

`backend/app/services/backtest_service.py`. Un helper junto a
`_group_partial_exits`:

```python
def _identidad_trade(run: list[dict]) -> tuple:
    """(entry_price, stop_loss) del TRADE, inmunes al leg del SL por lote.

    El cierre por SL de lote es el único leg con entrada y stop propios (el px
    del añadido y el cinturón del lote). Si salta antes que cualquier parcial
    es el primero del grupo, y `dict(first)` se los pegaría al trade entero.
    """
    first = run[0]
    if first.get("exit_reason") != "Pyramid Lot Stop":
        return first.get("entry_price"), first.get("stop_loss")
    if first.get("trade_entry_price") is not None:
        return first.get("trade_entry_price"), first.get("trade_stop_loss")
    # Respaldo para resultados de corridas anteriores a 5.1: el primer leg que
    # no sea de lote sí trae la identidad del trade.
    base = next((l for l in run if l.get("exit_reason") != "Pyramid Lot Stop"), None)
    if base is not None:
        return base.get("entry_price"), base.get("stop_loss")
    return first.get("entry_price"), first.get("stop_loss")
```

Y usarlo en los dos sitios:

- **`_flush`** (línea 1732), justo después de `trade = dict(first)`:
  fijar `trade["entry_price"]` y `trade["stop_loss"]` con `_identidad_trade(run)`,
  y quitar del trade final las dos claves auxiliares
  (`trade.pop("trade_entry_price", None)`, `trade.pop("trade_stop_loss", None)`),
  igual que ya se hace con `pyr_executions`.
- **`_build_executions`** (línea 1603): el `price` de la ejecución `entry` sale
  del mismo helper, no de `first.get("entry_price")`.

**Ojo con la rama de un solo registro:** `_group_partial_exits` tiene un
atajo al principio (`if len(trades_records) < 2`) y `_flush` tiene otro
(`if len(run) == 1`). Un trade cuya posición se vacía ENTERA por lotes puede
caer ahí con un único leg de lote: hay que limpiar las claves auxiliares
también en esos dos caminos (y la identidad ya la resuelve el helper por
`trade_entry_price`).

### 5.3 Fuera de alcance (no tocar en este fix)

- **`avg_entry_price`**: el trade fusionado lo hereda de `first` y por tanto es
  la media en un instante intermedio, no la final. Ya era así con los parciales
  antes del SL por lote; es un campo ambiguo por diseño. **Dejarlo como está**
  y no empeorarlo — solo comprobar que el fix no lo cambia.
- El leg crudo del lote, el visor, y cualquier cosa del bot.

---

## 6. Qué NO hay que verificar (ahorra tiempo)

- **No hay paridad JIT que romper.** `sim_dispatch.simulate` rutea SIEMPRE al
  motor Python cuando hay `pyramid_levels` (`sim_dispatch.py:43-45`): el kernel
  Numba no soporta piramidación.
- **Los golden hashes no se tocan.** `GOLDEN_CON_PYR` / `GOLDEN_SIN_PYR`
  (`test_lot_stop_nivel.py:76-77`, `test_pyramid_steps_nivel.py:72`) son del
  COMPILADOR de estrategias, no de los resultados.
- **Los asserts de `test_lot_stop_sim.py:100-102`** (sobre el leg crudo) siguen
  válidos tal cual: el leg no cambia, solo gana dos claves.

---

## 7. Criterio de aceptación

1. **Test unitario nuevo** (en `backend/tests/test_lot_stop_sim.py`), sin motor:
   `_group_partial_exits([leg_lot_stop, leg_cierre])` con `entry_idx` común →
   el trade resultante tiene el `entry_price` y el `stop_loss` del TRADE, no
   los del lote; y `pnl`/`size` siguen siendo la suma de los legs.
2. **Test del caso límite:** posición vaciada ENTERA por lotes (todos los legs
   son `Pyramid Lot Stop`, incluido el camino de `len(run) == 1`) → la
   identidad sale de `trade_entry_price`/`trade_stop_loss` y el trade no expone
   esas dos claves auxiliares.
3. **Test de no regresión:** una pirámide SIN `lot_stop` y un trade con
   parciales dan EXACTAMENTE lo mismo que antes del fix.
4. **Suite completa del backend verde:** 1125 passed / 115 skipped / 3 xfailed
   (la referencia del merge de `c720319`).
5. **E2E con motor real**, re-corriendo la estrategia «GA Sobri MEJORADA»
   (`hard_stop` Previous Max +10 %, `lot_stop` pivote alto w2 +5 %) sobre el
   mismo rango que `f72bbf33`:
   - ATMV 2025-12-09 pasa a `stop_loss = 13.574` (hoy 10.248).
   - ALCE 2025-01-02 pasa a `stop_loss = 1.815` (hoy 1.512).
   - **Chequeo agregado:** 0 trades con `exit_reason == 'SL'` y
     `abs(exit_price - stop_loss) > 0.005` (hoy son 274).
   - **Invariante de dinero:** `total_pnl`, `total_trades` y `win_rate`
     IDÉNTICOS a los de `f72bbf33`. Si cambia un céntimo, el fix se ha pasado
     de sitio.
6. **Visual:** en el visor de ATMV 2025-12-09, la línea roja «SL» queda en
   13.57 y el chip del añadido sigue diciendo `SL 10.25`. Dos niveles
   distintos, que es lo que hay de verdad.

---

## 8. Notas para quien lo aplique

- **Los resultados YA guardados no se recalculan.** Las 82 corridas de
  `users.duckdb` seguirán con el dato malo; hay que re-correr para verlo bien.
  No hace falta migrarlas.
- **`backtest_service.py` y `portfolio_sim.py` son los dos ficheros que
  `staging` acaba de mover** (merge `00ed733`). Rebasar antes de empezar y
  revisar que las líneas citadas siguen donde dice este PRD.
- El hallazgo queda ABIERTO en `docs/MEMORIA_MADRE.md` hasta que se verifique;
  el cambio de estado va como entrada NUEVA al final, no editando la vieja.
