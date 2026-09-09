# ALVARO_CAMBIOS — Documentación de trabajo de Álvaro (para Sailor)

> **Qué es esta carpeta:** los documentos vivos de trabajo de Álvaro
> (`MEMORIA.md` y `PROXIMOS_ITEMS.md`), compartidos en `staging` para que
> tengas visibilidad de qué está haciendo. **No cambia nada del código de
> `staging`** — es solo documentación. El código real vive en su rama.

## Sesión 2026-08-22 — ITEM 4 fees: cierre 100% vía parciales (commit `cd455ae`)

Tu reporte de las comisiones (22/08 07:28) cotejado contra el código: el
modelo por-fill del ITEM 2 **ya cobraba los dos lados** en el camino normal
(round trip = `fees × acciones × 2`, como el tuyo — me alegra que lo demos por
cerrado). Pero destapó un **agujero real que ya está fixeado**: si la posición
se cerraba **entera por parciales** (p. ej. dos slots de 50%, o un parcial que
liquida todo), el bloque de cierre final nunca corría y **el lado de entrada
no se cobraba nunca** — 1.000 acciones a $0.01 pagaban $10 en vez de $20.

El fix es de mínima superficie: el cierre final queda intacto (fórmula
combinada); solo el parcial que liquida la posición añade la entrada UNA vez
(flag por posición). Sin parciales y con parciales que no cierran todo, los
resultados son **bit-idénticos** a antes (tests T-C/T-D lo congelan). Paridad
Python↔JIT verificada. Tests: 17+54 passed.

**⚠️ Aviso para cuando tu fix del quirk B llegue a staging**
Con este ITEM 4, cuando el cierre es 100% por parciales el fee de entrada
queda **dentro del `pnl` de la leg que cierra** pero no en su clave `fees`
(que no existe — quirk B). Cuando tu corrección exponga `fees` por leg, esa
leg de cierre tendrá que reflejar **salida + entrada absorbida**, o su `fees`
no reconciliará con su `pnl`. Está también anotado en `MEMORIA.md` del día.

## Sesión 2026-08-21 — 3 fixes del backtester ejecutados

Todo el trabajo está en la rama **`alvaro-rama-desarrollo`** (commits
`5741202`, `59a869d`, `75f4bee`, `77236d2`), con tests y paridad
Python↔JIT verificadas. **Todavía NO mergeado a `staging`.**

| Fix | Qué arregla | Riesgo |
|---|---|---|
| MAX DD $ tab OOS (`5741202`) | El tab "OOS degradation" calculaba el DD$ como `(dd%/100)×capital inicial`, subestimándolo cuando el pico supera el capital. Ahora usa el pico real de la curva (mismo patrón que Equity Curve). | Solo frontend, el motor no se toca |
| Trailing break-even (`59a869d`) | Trailing Stop con `activation_pct` desacoplado de la distancia; distancia 0 = stop fijo en entrada ("trade gratis") tras activarse. Ya estaba en la working tree de Álvaro; ahora tiene tests T1-T6 (19/19) y está commiteado. | Regresión bit-idéntica del trailing clásico verificada por test |
| Fees por ejecución (`77236d2`) | FLAT pasa de "$ por trade" fijo a **$/acción**; PERCENT pasa de % del PnL a **% del nocional** por lado. Modelo por-fill: entrada y salida pagan cada una; parciales pagan su salida. **Cambia números de backtests guardados con fees>0** (en FLAT, muchísimo). | Motor Python + kernel JIT, paridad 28/28; quirk de parciales sin `fees` intacto |

## Contenido

- **`MEMORIA.md`** — histórico de sesiones: qué se hizo, por qué, dónde se
  dejó cada cosa (entradas por fecha, lo más nuevo arriba).
- **`PROXIMOS_ITEMS.md`** — guía de pendientes. Ahora mismo solo queda el
  Backlog congelado (bugs conocidos, decisión de no tocar por ahora).

Si algo de esto te afecta (especialmente el cambio de fees, que altera
resultados), háblalo con Álvaro antes de mergear nada.
