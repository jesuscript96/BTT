# PRD — TP por lote: take profit con parciales propios en cada piramidación

- **Fecha:** 2026-09-22
- **Autor:** Álvaro (necesidad, decisión y semántica exacta) + ZCode (análisis del
  motor y redacción)
- **Aplica sobre:** `alvaro-rama-desarrollo` a la altura de `149cacb`
- **Tipo:** funcionalidad nueva (extensión de la piramidación por lotes). No
  arregla ningún bug.
- **Familia:** es el ESPEJO del SL por lote (`lot_stop`, PRD 2026-09-15 + fix
  `fa1bc89` del 18-sep). Sigue su patrón de integración: schema → compile →
  simulador → builder → tests dorados.
- **No toca el bot de avisos** ni `market_frame.py` ni la página de Alertas.
- **Reglas del repo vigentes:** rama personal, integración a staging por merge
  con porta-verja, `main` intocable, confirmación antes de push a staging.

---

## 1. Resumen en una frase

Cada lote de piramidación ya sabe cortarse solo con SU stop (`lot_stop`); se
pide que también sepa tomar beneficios solo, con parciales propios: «al
recorrer X % desde SU precio de entrada, saca el Y % del lote; el resto del
lote cabalga hasta la salida final del trade (o su stop de lote, que sigue
inamovible)».

Ejemplo literal de Álvaro (2026-09-22): primera piramidación de la escalera —
quiero su stop loss de lote, que no se mueva pase lo que pase, y sus
parciales: **al recorrer el 10 % saca el 50 % del lote, y el otro 50 % lo
saco al final, junto con la ejecución de cierre del trade inicial.**

---

## 2. Qué existe hoy (verificado en código, no supuesto)

1. **El lote ya vive como individuo.** Cada add entra en `lots` con
   `{level, px, size, sl_px}` (`portfolio_sim.py:2065`). El cinturón del
   `lot_stop` recorre los lotes abiertos vela a vela y cierra el que perfora
   SU nivel (`portfolio_sim.py:1504-1607`), con leg propia (`"Pyramid Lot
   Stop"`), identidad del trade pegada para la fusión
   (`trade_entry_price`/`trade_stop_loss`, PRD_FIX_SL_LOTE_FUSION) y la media
   del trade recalculada restando la contribución del lote cerrado (§5.4).
2. **Los parciales globales ya saben hacer rungs.** El TP parcial del trade
   soporta escalones por % de distancia desde la entrada Y por hora
   (`HOUR:HH:MM`, `portfolio_sim.py:1100-1224`), cada rung dispara UNA vez
   (`partial_tp_hits`), y la base de cálculo sigue a la posición (crece con
   adds, no baja con parciales ya tomados: `pyr_base`, líneas 539-540 y
   2031-2033).
3. **NO existe ningún TP por lote.** `grep lot_tp|lot_take|tp_lot` sobre
   `app/services/` no devuelve nada. Los `reduce` cierran % de la posición
   FLOTANTE total (proporcional, no por lote). Un TP atado al precio de un
   add concreto **no es expresable hoy de ninguna manera.**

---

## 3. Qué se pide

Bloque opcional `lot_tp` en cada nivel de piramidación, hermano de `lot_stop`:

```json
"pyramiding": {
  "timeframe": "1m", "mode": "individual",
  "levels": [
    { "times": 5, "action": "add", "unit": "usd", "capital_pct": 1,
      "root_condition": { "...": "gatillo del add, p. ej. % Fade >= 10" },
      "lot_stop": { "mode": "structure", "level": "Ultimo pivote alto",
                    "pivot_window": 2, "offset_pct": 5.0 },
      "lot_tp": {
        "rungs": [
          { "travel_pct": 10.0, "capital_pct": 50.0 },
          { "travel_pct": 20.0, "capital_pct": 30.0 }
        ]
      }
    }
  ]
}
```

Con esta definición, CADA ejecución de ese nivel (cada peldaño de la escalera)
nace con:

- su `lot_stop` actual, **inamovible** (no se toca nada de su semántica);
- su escalera `lot_tp`: cuando el precio recorre a favor el `travel_pct` desde
  el PRECIO DE ESE LOTE, cierra el `capital_pct` % del TAMAÑO ORIGINAL del
  lote. Cada rung dispara una vez por lote. Rungs ordenados por `travel_pct`;
- **el resto del lote (100 − Σ capital_pct) NO se cierra solo**: queda vivo
  hasta la salida del trade (hora/EOD/TP/señal) o hasta su stop de lote. Ese
  «resto viaja con el trade final» es requisito explícito de Álvaro.

Semántica de `travel_pct` (decisión): **% de recorrido favorable sobre el
precio del lote**, en la dirección del trade — para un short, que el precio
caiga un 10 % bajo el precio del add; para un long, que suba un 10 % sobre él.
Es la misma métrica que usan los parciales globales por % (distancia desde la
entrada), medida desde la entrada del LOTE.

---

## 4. Contrato de comportamiento (obligatorio)

1. **Regla nº1 (la del SL por lote, sin discusión):** una definición sin
   `lot_tp` compila y corre **EXACTAMENTE igual** que hoy — byte a byte en el
   compilado (dorados de `test_lot_stop_nivel` / `test_pyramid_steps_nivel`)
   y céntimo a céntimo en el simulador. El bloque solo se escribe si existe.
2. **Disparo y fill:** un rung dispara la primera vez que la vela TOCA su
   nivel (high/low cruza el precio objetivo), igual que los rungs globales
   por %. Se marca disparado por lote+rung; no se re-arman nunca dentro del
   mismo trade (misma regla que `partial_tp_hits`).
   **Varios rungs en la MISMA vela** (gap fuerte a favor): disparan TODOS los
   cruzados, en orden de `travel_pct` ascendente, cada uno con SU fill. El
   fill es semántica de orden límite, idéntica a los parciales globales por %
   (`portfolio_sim.py:1281-1282`): **al nivel si la vela lo toca intrabar; si
   la vela ABRE ya más allá del nivel, al OPEN de la vela** (mejor para el
   que cierra, acotado al extremo de la vela). Nota de honestidad exigida en
   revisión: es fill de límite (nivel o mejor), deliberadamente distinto del
   tratamiento del stop (nivel acotado al extremo, `portfolio_sim.py:1520-1524`);
   el optimismo residual es asumir que el nivel tocado intrabar se pudo
   trading al nivel. Se acepta por paridad con los parciales globales.
3. **Orden DENTRO de la vela — el orden global completo, fijado** (verificado
   contra el simulador; los números de línea son de `portfolio_sim.py`):
   ```
   HALTS (665) → Black Swan (769) → salidas del trade: stop/TP/señal (911+)
   → parciales/TP GLOBALES (1054-1286)
   → cinturón SL por lote (1499)
   → RUNGS de lot_tp  [NUEVO: dentro del bloque del cinturón, inmediatamente
                        después del chequeo de SL de cada lote]
   → escalera scalping (1609) → adds/REDUCE de pirámide (1731-2139)
   → entradas nuevas (2140)
   ```
   Consecuencias explícitas (revisión de Álvaro, 22-sep):
   - Los **parciales globales corren ANTES**: NO ven los rungs de esa vela —
     su `pt_size = pyr_base × cap_frac` se calcula sobre el flotante intacto
     de los rungs (y de los lotes cerrados por el cinturón en esa misma vela
     tampoco: el cinturón va después).
   - El **REDUCE de pirámide corre DESPUÉS**: SÍ ve el `pyr_base` ya reducido
     por el cinturón y por los rungs de esa vela.
   - Si el **stop del TRADE** saltó en la vela, `in_position=False` y ni
     cinturón ni rungs corren (regla existente, `portfolio_sim.py:1500-1502`).
   - Dentro del lote: **primero el `lot_stop`, después los rungs de `lot_tp`**
   — si en la misma vela se toca el cinturón y un rung, gana el stop
   (conservador, y coherente con «el SL es inamovible»).
4. **Nunca en la vela de entrada del lote** (el add entra en la apertura de la
   vela siguiente a su señal; sus rungs se vigilan desde la vela posterior —
   misma regla que el cinturón y la escalera).
5. **Tamaño:** cada rung cierra `capital_pct` % del tamaño ORIGINAL del lote
   (escalera aditiva: 50+30 = 80 % del lote; el 20 % restante cabalga). Nunca
   más de lo que queda vivo del lote (recortes de caja/locates incluidos: si
   el add se recortó al ejecutarse, los rungs se aplican sobre lo AÑADIDO de
   verdad, como hace el cinturón).
6. **Contabilidad:** cada rung es una leg de cierre completa — su pnl, sus
   fees por los dos lados, `entry_price` = precio REAL del lote y
   `avg_entry_price` = la del trade (patrón de las legs de lot_stop y
   reduce), `exit_reason` = `"Lot TP (1/2)"` etc., con
   `trade_entry_price`/`trade_stop_loss` para la fusión. La media del trade se
   recalcula restando la contribución del trozo cerrado (misma aritmética §5.4
   del cinturón); `pyr_base` baja lo cerrado.
7. **El stop del lote sigue siendo el de HOY** para el resto que cabalga: el
   cinturón vigila el tamaño vivo del lote aunque ya haya soltado rungs (el
   `size` del lote es el vivo).
8. **Lote que queda vacío:** si Σ rungs = 100 %, el lote sale del array de
   supervivientes sin matar el trade (la base y otros lotes siguen). Si los
   rungs + cinturón vacían TODA la posición, se aplica el flujo existente de
   «posición muerta por lotes» (`portfolio_sim.py:1592-1607`).

---

## 5. Los sitios donde esto se perdería EN SILENCIO (el §5 de siempre)

1. **`schemas/strategy.py`** — validador del bloque `pyramiding`: `lot_tp`
   declarado y validado (rungs no vacíos, `travel_pct` > 0, `capital_pct` en
   (0, 100], Σ ≤ 100, y `travel_pct` **ESTRICTAMENTE creciente** — dos rungs
   al mismo nivel o en orden decreciente son un 422, NO se reordenan en
   silencio: un ladder desordenado es un error de quien lo escribe, y
   reordenarlo escondería el error). Sin declarar, `extra="ignore"` lo tira
   sin avisar. **422**, como `lot_stop`.
2. **`compile_strategy_def` (strategy_engine)** — normalización de niveles:
   `lot_tp` → estructura interna por nivel. Dorados: el compilado de una
   definición SIN lot_tp no cambia (hash congelado, recongelado documentando
   el motivo si el plan de niveles gana campos nulos).
3. **`portfolio_sim`** — la ejecución (bloque del cinturón, §4). Si el compile
   no lleva los rungs, el sim ni los ve: mismo fallo de «el parámetro no
   llega» que ya sufrieron `pyramiding` y `scalping` en el router.
4. **Routers de strategies** — ya curado el patrón (b0e1b03): el dict opaco de
   `pyramiding` viaja entero en POST/PUT; no hace falta tocar. Verificar con
   round-trip igual que la regresión del scalping.
5. **Builder frontend (`RiskManagement.tsx`, sección piramidación)** — editor
   de rungs por nivel (lista dinámica travel/capital), resumen legible
   («TP lote: 50 % a +10 % · 30 % a +20 % · resto al cierre») y pintado en el
   visor: las legs `Lot TP` como chips del color de su lote (mismo carril que
   los chips de `Pyramid Lot Stop`).
6. **Camino JIT de numba** — la piramidación va por el simulador Python
   (`sim_dispatch` la desvía del kernel JIT, ver `test_scalping.py`): sin
   paridad nueva que exigir, pero añadir un test que lo SIGA desviando con
   `lot_tp` presente (que nunca se meta en el kernel por accidente).

---

## 6. Tests exigibles (todos sintéticos, sin DuckDB ni GCS)

1. **Regla nº1:** definición con lot_stop pero SIN lot_tp → mismo hash dorado
   de compilado y misma corrida céntimo a céntimo que hoy.
2. **Escalera a mano:** día sintético donde el add nº1 recorre 10 % y 20 % —
   comprobar las dos legs con SU precio de entrada, SU tamaño (50 %/30 % del
   lote), sus fees, y que el 20 % restante sale con la salida global (hora),
   con el `stop_loss` del leg final = el del trade.
   **Variante «una vela cruza DOS rungs»** (exigida en revisión): gap fuerte
   a favor — una sola vela M1 cruza los niveles de los rungs 1 y 2 → las DOS
   legs en esa vela, en orden de travel ascendente, y si la vela ABRE más
   allá del segundo nivel, AMBAS legs al precio del open (semántica límite,
   §4.2). Fills, tamaños y fees calculados a mano dentro del test.
3. **SL inamovible:** día donde el lote recorre +9 % y vuelve a perforar el
   cinturón — cero rungs disparados, leg única de `Pyramid Lot Stop` por el
   tamaño vivo completo. Y el caso límite: vela que toca rung Y cinturón →
   gana el cinturón (§4.3).
4. **Rung único por lote:** precio oscila y cruza el nivel del rung dos veces
   → una sola leg.
5. **Recorte de caja:** add recortado por el tope de caja → rungs sobre el
   tamaño ejecutado, no sobre el nominal pedido. **Con el número exacto
   clavado** (exigido en revisión): el test fabrica un add que pide 2 $ y la
   caja solo deja ejecutar 1 $; con un rung del 50 %, la leg debe cerrar
   exactamente 0,50 $ al fill del nivel con sus fees calculados a mano —
   «% del original» significa aquí «% del tamaño EJECUTADO del add».
6. **Vela de entrada:** el rung no dispara en la vela en que el add entra.
7. **Σ = 100 %:** lote se vacía por rungs sin matar el trade (la base sigue);
   y lotes vacíos + cinturón vaciando todo → bitácora colgada de la última
   leg (flujo existente).
8. **Fusión:** trade con legs de `Lot TP` + leg final → el trade fusionado
   reporta SU entrada y SU stop (regresión del hallazgo 18-01 extendida).
9. **Round-trip de guardado:** POST/PUT con `lot_tp` → GET devuelve el bloque
   entero (patrón b0e1b03).

---

## 7. Riesgos y qué NO se pide

- **No se toca** `lot_stop` (semántica y tests actuales intactos), ni los
  `reduce`, ni los parciales globales, ni `_ultimo_pivote`/indicadores.
- **No se pide (fases futuras explícitas):** trailing por lote, rungs en
  múltiplos de R del lote, rungs por condición de indicador o por hora DEL
  LOTE (hoy: solo % de recorrido), TP por lote en el modo secuencial de
  grupos (arrancar con `individual`, que es lo que usa la escalera).
- **Rendimiento:** por vela, lotes abiertos × rungs sin disparar — despreciable
  frente al coste de carga de datos.
- **Expectativa honesta (medida el 22-sep):** en la familia Sobri-escalera,
  TODA salida temprana probada hoy (08:30 plano, 50/50, reduce-50 % en
  fade<5) pierde R frente a aguantar hasta las 09:00. Este PRD no promete
  más R: da la PERILLA para medirlo por lote (p. ej. peldaños profundos con
  TP corto y base larga), que es lo que Álvaro quiere poder expresar.

---

## 8. Decisiones ya tomadas por Álvaro (2026-09-22)

- Cada ejecución de piramidación lleva SU stop (inamovible, el actual) y SU
  take profit con parciales por rung de % recorrido.
- El resto no tomado por rungs sale CON LA EJECUCIÓN FINAL del trade, no
  solo.
- Unidades: % de recorrido sobre el precio del lote; % de capital sobre el
  tamaño original del lote.
