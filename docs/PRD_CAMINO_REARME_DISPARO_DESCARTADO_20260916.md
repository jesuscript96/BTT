# PRD — Rearme del camino cuando un disparo se DESCARTA por riesgo

- **Fecha:** 2026-09-16
- **Autor:** Álvaro (decisión) + Claude Opus (hallazgo, repro y redacción)
- **Origen:** `[HALLAZGO · 2026-09-16 · 02]` en `docs/MEMORIA_MADRE.md`
- **Aplica sobre:** el «Caminito» ya implementado (commit `2fbbe5a`,
  PRD `docs/PRD_CAMINITO_CONDICIONES_PIRAMIDACION_20260916.md`)
- **Tamaño real del cambio:** mover 2 líneas de sitio y borrar dos bloques
  duplicados. Nada más. Si tu diff es más grande que eso, te has pasado.

---

## 1. El problema (con evidencia, no con teoría)

Cuando un nivel-camino engancha su ÚLTIMO paso, `pyr_step_k` sube a
`len(steps)` **antes** de intentar ejecutar el añadido
(`portfolio_sim.py:1771-1776`). El reinicio de llaves (`pyr_step_k = 0`) está
pegado a `pyr_fired += 1` (`:1949-1957` para el `add`, `:2030-2035` para el
`reduce`), o sea **solo se ejecuta si el añadido llega a hacerse**.

Si el añadido se descarta por una regla de riesgo —`cash_now <= 0` (`:1840`),
`add_cash <= 0` (`:1849`), `disponible <= 0` (`:1865`), cupo de locates
(`:1933`), `add_size <= 0` (`:1938`)— se hace `continue` sin tocar las llaves.
`pyr_step_k` se queda clavado en `len(steps)`, y como el bucle entra con
`while pyr_step_k < len(steps)`, **ese nivel no se vuelve a evaluar en todo el
trade**, aunque la caja se libere después y el patrón se repita entero.

**Repro real** (velas planas a 10 $, `init_cash=10000`, `risk_r=10000` FIXED →
la entrada compromete el 100 % del capital; nivel 0 = `reduce` 50 % en la barra
10 que libera 5.000 $; nivel comparado con `max_fires=2`):

```
=== CAMINO [A,B] (max_fires=2) ===
   reduce  barra 11  size   500.00
   -> ADDS EJECUTADOS: 0  []

=== NIVEL NORMAL (max_fires=2) ===
   reduce  barra 11  size   500.00
   add     barra 15  size    10.00
   -> ADDS EJECUTADOS: 1  [15]
```

Mismo escenario, mismo `max_fires`: el nivel normal se recupera y el camino se
queda con **cero añadidos**. El comentario del código que dice «espejo del nivel
normal» (`:1951-1955`) hoy no se cumple.

## 2. La decisión de Álvaro

**Opción B.** Un disparo descartado por caja/locates **rearma el camino igual
que uno ejecutado** —vuelve al paso 1 conservando los `prev_sig` de cada paso—
pero **NO gasta una de las `times`**.

Motivo: quedarse sin caja es una limitación temporal de la cuenta, no una señal
del mercado, y la caja **se libera sola dentro del mismo trade** (un `reduce` o
un TP parcial encogen la posición y `disponible = cash_now - avg_entry_price *
size` vuelve a ser positivo). Dejarlo como está acopla en silencio el TAMAÑO de
la posición con la DETECCIÓN del patrón: subir el tamaño de entrada mata caminos
antes y mueve los resultados por un motivo ajeno a la estrategia.

## 3. El cambio (hazlo EXACTAMENTE así)

La clave: **el reinicio de llaves no pertenece al momento de ejecutar, sino al
momento de disparar.** En los dos desenlaces posibles (ejecutado o descartado)
las llaves deben volver a cero. Por tanto se sube el reinicio al final del bucle
de pasos, y los dos bloques de abajo desaparecen por redundantes.

**3.1 — Añadir el rearme justo donde el camino dispara.** En la rama del
nivel-camino, inmediatamente DESPUÉS del `while` de pasos y ANTES del
`if not dispara: continue` (hoy en `portfolio_sim.py:1777-1779`):

```python
                    if dispara:
                        # REARME AL DISPARAR, no al ejecutar (PRD 2026-09-16
                        # del rearme, HALLAZGO 2026-09-16·02). Las llaves
                        # vuelven a cero pase lo que pase con la ejecución: si
                        # el añadido se descarta por caja o locates, el camino
                        # puede recorrerse otra vez (un descarte NO gasta una
                        # de las `times`; `pyr_fired` solo sube al ejecutar).
                        # `pyr_step_prev` se CONSERVA: la protección
                        # anti-metralla de Q3 sigue intacta — para volver a
                        # enganchar el paso 1 hace falta un flanco nuevo.
                        pyr_step_k[lv_idx] = 0
                        pyr_last_latch[lv_idx] = -1
```

**3.2 — Borrar los dos bloques ahora redundantes**, que hacen exactamente eso
mismo pero solo en el camino ejecutado:

- `portfolio_sim.py:1955-1957` (en el `add`, tras `pyr_fired[lv_idx] += 1`)
- `portfolio_sim.py:2033-2035` (en el `reduce`, tras `pyr_fired[lv_idx] += 1`)

Son estas dos, idénticas:

```python
                    if lv.get("steps_signals") is not None:
                        pyr_step_k[lv_idx] = 0
                        pyr_last_latch[lv_idx] = -1
```

Borra también sus comentarios inmediatamente anteriores (los que hablan del
rearme de llaves), porque esa explicación se muda al punto 3.1. **No toques** el
`pyr_fired[lv_idx] += 1`: sigue donde está y sigue subiendo solo al ejecutar —
eso es lo que hace que un descarte no gaste una `times`.

## 4. Por qué esto NO mueve nada más

- **Caso ejecutado:** hoy las llaves se reinician después de ejecutar; con el
  cambio se reinician un poco antes, en la misma barra, y entre los dos puntos
  **nadie lee `pyr_step_k` ni `pyr_last_latch`** (el bloque intermedio solo
  calcula precios, tamaños y registra la ejecución). Resultado idéntico.
- **Niveles normales (sin `steps`):** la rama `if lv.get("steps_signals") is
  None` no se toca. Cero cambios, byte-idénticos.
- **`pyr_step_prev` no se toca nunca:** Q3 (anti-metralla) intacto. Tras un
  descarte, el paso 1 necesita un flanco `False→True` nuevo para reenganchar;
  una condición sostenida NO reinicia el camino en barra a barra.
- **`max_fires` / `times`:** intactos. Un descarte no incrementa `pyr_fired`,
  así que el nivel conserva todas sus veces — que es justo lo que se pide.
- **`lot_stop`, topes de caja, locates, `size_by_sl`, híbrido, Numba:** sin
  tocar.

## 5. Tests

**5.1 — Test nuevo** en `backend/tests/test_pyramid_steps_sim.py` (añádelo al
final, con el estilo de los que ya hay; reusa `_correr` / `_adds`):

> `test_disparo_descartado_por_caja_rearma_el_camino`
> Entrada que compromete el 100 % del capital (`risk_r = init_cash`), un nivel
> `reduce` del 50 % que libera caja en mitad del día, y un nivel-camino con
> `max_fires=2` cuyos pasos se completan DOS veces: la primera sin caja
> (descartada) y la segunda con caja. **Debe ejecutarse 1 add** en la segunda.
> Antes del fix: 0 adds. Añade en el mismo test la comprobación de que un nivel
> NORMAL equivalente también da 1 add (es la paridad que se estaba rompiendo).

**5.2 — Test de que Q3 sigue vivo:** tras un disparo descartado, con la
condición del paso 1 **sostenida** (sin flanco nuevo), el camino **no** vuelve a
engancharse. Si este test no pasa, has reiniciado `pyr_step_prev` por error.

**5.3 — Regresión obligatoria, todo verde y sin excusas:**

```bash
cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_pyramid_steps_nivel.py tests/test_pyramid_steps_sim.py tests/test_lot_stop_sim.py tests/test_lot_stop_nivel.py tests/test_run_backtest_slab_equivalence.py tests/test_slab_stream_equivalence.py tests/test_pyramid_entry_time_window.py -q
```

Referencia antes de tocar nada: **45 passed** en los dos de `steps`, y **71
passed** en el conjunto de arriba con `test_strategy_api.py` incluido. Después
del cambio deben seguir todos verdes, más los tests nuevos.

## 6. Límites duros del repo (no los cruces)

- Rama `alvaro-rama-desarrollo`. **`main` y `staging` no se tocan.**
- **Antes de cualquier `push`, confirmación explícita de Álvaro.** La IA nunca
  hace push a `staging` (normativa fijada el 2026-09-16).
- Nada de secretos ni datos (`.env`, `*.duckdb`, `data/`, `gcs-key.json`).
- No borres código: si algo sobra de verdad, va a `_archive/`. (Aquí no aplica:
  los dos bloques del punto 3.2 se eliminan porque su lógica se MUDA al 3.1, no
  porque se descarten.)
- Si al abrir el fichero la realidad no cuadra con lo que dice este documento
  (líneas movidas, otro contenido), **para y dilo con la línea concreta** — no
  improvises una variante.

## 7. Entrada de memoria al terminar

Añade una entrada NUEVA al final de `docs/MEMORIA_MADRE.md` (nunca edites las
anteriores) marcando el `[HALLAZGO · 2026-09-16 · 02]` como **RESUELTO**, con el
commit, el resultado de los tests y la confirmación de que el repro del hallazgo
ahora da 1 add en vez de 0.
