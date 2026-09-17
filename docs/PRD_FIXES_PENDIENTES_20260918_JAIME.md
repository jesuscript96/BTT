# PRD — Tres fixes pendientes del 17-sep (visor, genético y validación) para ejecutar por Jaime

- **Fecha:** 2026-09-18
- **Autor:** Álvaro (decisión) + ZCode (hallazgos, evidencia y redacción)
- **Origen:** `[HALLAZGO · 2026-09-17 · 01]`, `[HALLAZGO · 2026-09-17 · 02]` y
  `[HALLAZGO · 2026-09-17 · 03]` en `docs/MEMORIA_MADRE.md`
- **Aplica sobre:** `alvaro-rama-desarrollo` a la altura de `72d873a`
- **Nada de esto es urgente ni toca el bot de avisos.** Los tres bugs están
  ESQUIVADOS hoy (workaround documentado en cada uno); esto es para cerrarlos
  de raíz.
- **Regla del repo que sigue vigente:** cada fix en SU rama, integración por
  PR a `staging`, `main` intocable.

---

## Fix 1 — El visor de trade no distingue «error de carga» de «día sin velas», y no admite reintento

**Origen:** `[HALLAZGO · 2026-09-17 · 03]`. Severidad: bug (UX).

### El problema (con evidencia)

`frontend/src/app/backtester/page.tsx:1104-1107` — `loadCandles` captura
cualquier fallo de red con un `catch` que solo hace `console.error` y deja
`dayCandles = null`. Ese null es **el mismo estado** que el de un ticker-día
sin datos, y el visor (`PanelAnalisisTrade.tsx:136-152`) pinta para ambos
«No hay velas para este trade».

Repro real del 17-sep: Álvaro abrió HXHX 2025-12-22 y vio ese mensaje.
Verificado que el backend SÍ tenía las velas (200, 764 velas, en ambos
datasets) y que **su navegador nunca llegó a pedirías** — la petición cayó en
una ventana de reinicio del backend. El `catch` se la tragó en silencio.

**El agravante (esto es lo que hay que arreglar sí o sí):** el reintento es
imposible sin trucos. En `ResultsTabs.tsx:109-133`, `handleSelectTrade`:

1. Click 1 en el ticker → abre visor + `onSelectDay(dayIdx)`.
2. Click 2 (mismo ticker, visor abierto) → SOLO cierra el visor (rama
   `tradeDesplegado === clave`).
3. Click 3 (vis ya cerrado) → vuelve a `onSelectDay(dayIdx)` con el MISMO
   índice → `setSelectedDay(mismo valor)` → React no re-dispara el efecto
   (`page.tsx:1116-1120`) → **no se vuelve a pedir nada**.

Solo se recupera haciendo click en OTRO ticker-día y volviendo, o F5.

### Diseño del fix (pequeño, dos frentes)

1. **Estado de error aparte.** `const [candlesError, setCandlesError] =
   useState(false)`; a `true` solo en el `catch` de `loadCandles` (y a
   `false` al empezar cada carga). En `PanelAnalisisTrade` (prop nueva
   `cargandoError` o similar): si error → «No se pudieron cargar las velas»
   **+ botón «Reintentar»** que llame a recargar el día actual. El caso
   «día sin datos» (200 con lista vacía) sigue mostrando el mensaje actual:
   son cosas distintas y hoy se confunden.
2. **Forzar la recarga al re-click del mismo día.** En la página, un contador
   de recarga (`reloadNonce`) que `onSelectDay` incrementa siempre; el efecto
   de carga depende de él (`[result, selectedDay, loadCandles, reloadNonce]`).
   Así el click 3 del repro vuelve a pedir velas aunque el día no cambie.

### Criterio de aceptación

- Con el backend parado, abrir un visor → mensaje de error con botón;
  levantar el backend → click en «Reintentar» → el chart carga sin F5.
- Click-clic-click en el MISMO ticker (cerrar y reabrir el visor) re-pide las
  velas (se ve en la pestaña Network del navegador).
- Un ticker-día sin datos sigue mostrando «No hay velas para este trade.»

---

## Fix 2 — La página del genético CRASHEA con corridas cuyo config no trae `catalogo`/`sesiones`

**Origen:** `[HALLAZGO · 2026-09-17 · 02]`. Severidad: bug.

### El problema

`frontend/src/app/genetico/page.tsx:1410` pinta el detalle de una corrida con:

```tsx
{detalle.config.catalogo.length} indicadores · {detalle.config.sesgo} · {detalle.config.sesiones.join("/")}
```

sin guardas. Las corridas creadas desde la UI siempre llevan esos campos;
las creadas **por API** (como las 4 del genético del 17-sep) llevan solo los
obligatorios → TypeError al render → overlay rojo de Next.js tapa la página
entera. Repro: `POST /api/genetico/corridas` con un config sin `catalogo` ni
`sesiones` → abrir `http://localhost:3000/genetico` y seleccionar esa corrida.

**Parche aplicado el 17-sep (en DATOS, no en código):** los `config.json` de
las corridas existentes llevan ahora `catalogo`/`sesiones`/`n_condiciones`
añadidos (backup de los originales en `.tmp_camino/backup_configs/`). El bug
de fondo sigue ABIERTO: cualquier corrida futura por API vuelve a tumbar la
página.

### Diseño del fix (elige una puerta, la A es la más defensiva)

- **A (frontend):** en la línea 1410, guardas:
  `{(detalle.config.catalogo ?? []).length}`, `{(detalle.config.sesiones ?? []).join("/")}`,
  `{detalle.config.n_condiciones ?? "—"}`. Revisar el resto de accesos a
  `detalle.config.*` de la página con el mismo criterio (líneas ~825-830,
  1376-1380).
- **B (backend):** `backend/app/routers/genetico.py` — al leer el
  `config.json` para el listado y el detalle, rellenar defaults
  (`catalogo: []`, `sesiones: []`, `n_condiciones: None`) si faltan. Así
  TODOS los consumidores quedan cubiertos, también los que lleguen después.

Preferible B (cierra la puerta de raíz); A como cinturón si se quiere doble.

### Criterio de aceptación

- Una corrida con config mínimo (solo `modo`/`genes`/`riesgo`/`dataset_id`)
  abre su detalle en la página del genético sin overlay rojo.
- Las corridas viejas del usuario (con campos completos) pintan igual que
  antes.

---

## Fix 3 — El backend responde 500 (y sin mensaje) cuando un validador de estrategia debería dar 422

**Origen:** `[HALLAZGO · 2026-09-17 · 01]`. Severidad: bug (diagnóstico).
**NO es del camino de condiciones:** afecta a `lot_stop` igual (lleva días
así) — es del manejo global de excepciones.

### El problema

`POST /api/strategies/` con un `lot_stop` inválido (p. ej. `{"mode": "pct"}`
sin `pct`) o con `steps`+`root_condition` juntos responde:

```json
500 {"detail":"Internal Server Error","message":"Object of type ValueError is not JSON serializable"}
```

en vez del 422 con el mensaje del validador («levels[0].steps: hacen falta al
menos 2 pasos»). La validación pydantic SÍ funciona (nada inválido se guarda —
verificado con sondas), viaja mal el STATUS y el mensaje: el usuario ve un
500 sin explicación.

Los validadores están en `backend/app/schemas/strategy.py`
(`_valida_lot_stop_por_nivel`, `_valida_steps_por_nivel`, ambos
`field_validator` que lanzan `ValueError` con mensaje en claro). La sospecha
(HIPÓTESIS en el hallazgo): el manejador global de excepciones de
`app/main.py` re-serializa la excepción y `json.dumps` falla con el objeto
`ValueError` dentro.

### Diseño del fix

En el manejador global (o en un handler específico para `ValueError`/
`ValidationError` de pydantic que llegue desde routers de estrategias):
devolver 422 con `str(exc)` (o los `errors()` de pydantic) en el cuerpo.
Repro exacto para el test: el `POST` del hallazgo, con `steps:[un_paso]` y
con `lot_stop` sin `pct`.

### Criterio de aceptación

- Ambas sondas responden **422** con el mensaje del validador en el cuerpo.
- Los tests existentes de validación (`test_lot_stop_nivel.py`,
  `test_pyramid_steps_nivel.py`) siguen en verde (validan a nivel pydantic,
  no cambian).

---

## Orden sugerido y tamaño

1. Fix 1 (visor): ~30 líneas. Es el que más duele a diario.
2. Fix 2 (genético): ~10 líneas backend o ~6 frontend.
3. Fix 3 (422→500): localizar el manejador es la mitad del trabajo; el fix
   es pequeño.

Ninguno toca `portfolio_sim`, ni señales, ni el bot. Los tres tienen repro
exacto en sus hallazgos de origen.
