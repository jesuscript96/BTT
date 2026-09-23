# PRD para Sailor y su IA — traer de la rama de Álvaro lo que falta en staging (23-sep-2026)

> **Escribe:** ZCode (para Álvaro), petición suya del 23-sep: «sube a staging la memoria
> y un PRD con lo que hemos hecho que no tenga Sailor, para que se lo descargue como
> siempre».
> **Cómo se consume:** cherry-picks selectivos desde `alvaro-rama-desarrollo` (lo que ya
> hace Sailor), NUNCA un merge directo de la rama entera (dejaría la zona del bot a medias:
> Álvaro mantiene 17 ficheros del bot ausentes; ver TRABAJO 18-09·4 de la MEMORIA_MADRE
> que viaja en este mismo push).
> **Fuente de verdad:** `docs/MEMORIA_MADRE.md` (rama de Álvaro, incluida aquí) y los PRD
> originales citados en cada punto.

## Qué le FALTA a staging — verificado con `git grep` contra `origin/staging` (68d4c2a), 23-sep

### 1. TP por lote (la escalera de toma de beneficios por pirámide) — `lot_tp`
- **Commits:** `907a064` (PRD v1) → `5effdf7` (PRD v2, la buena: orden global de vela,
  multi-rung por vela, fill límite documentado, validador estricto) → `eaa7ce1`
  (implementación motor + builder + tests con números exactos).
- **PRD original:** `docs/PRD_TP_POR_LOTE_20260922.md` (viaja en la rama de Álvaro con
  `5effdf7`; traerlo también).
- **⚠️ CRÍTICO:** en una rama SIN `eaa7ce1`, una estrategia con `lot_tp` guardado lo
  **ignora en silencio** (el bloque se cae al hidratar la definición y no hay error
  ninguno). La compartida B200 `c2a24250` usaba lot_tp; por eso se retiró y la definitiva
  `aa06` no lo lleva (ver §6).
- **Conflictos esperados al cherry-pick:** `PyramidingBuilder.tsx` (staging retocó los
  tooltips del SL de lote; la rama de Álvaro añadió el bloque TP por lote al lado) y
  `schemas/strategy.py` (uniones de campos). Resolver conservando ambos lados.

### 2. Fase 2 de picos y valles — la familia al carril nativo
- **Commit:** `328bc0d` (más la memoria `c0bbaa5` que lo documenta).
- Staging tiene la Fase 1/1b (el carril legacy); la Fase 2 registra `_ri_pico*` en
  `_RAW_INDICATOR_DISPATCH` con la clave de dedup ampliada (`_cfg_key` Y `_cfg_key_static`
  — si una cambia sin la otra, las condiciones dan False en silencio; está todo en el
  commit y sus tests).
- Los dorados de Numba (`test_lot_stop_nivel`, `test_pyramid_steps_nivel`) se
  recongelaron en la rama de Álvaro con 3 campos nuevos por spec. Al cherry-pickear,
  regenerar los dorados en proceso fresco (OJO documentado: el hash del SIN_PYR se
  contamina si se compila el CON_PYR antes en el mismo proceso).
- El carril nativo sigue APAGADO por defecto (`BTT_N2A_NATIVE_ENABLED=0`): la Fase 2 no
  cambia ningún comportamiento por defecto.

### 3. Fix del dropdown `ap_session` (hallazgo 22-09·01)
- **Commits:** `4ac8683` (memoria del hallazgo) + `149cacb` (fix frontend).
- Con el campo `ap_session` vacío, el dropdown mostraba `ap.RTH` pero el motor usa
  `ap.PM` → el fix hace que muestre `ap.PM` (paridad con el default real del motor).
- Un archivo: `frontend/src/components/backtester/BacktestPanel.tsx`.

### 4. Fix del modal del día del calendario (R TOTAL, no la media)
- **Commit:** `38fa515` (cierra lo presentacional del hallazgo 17-09·03).
- El modal del día sumaba el PnL total pero mostraba la media R **por trade** sin
  etiqueta: parecía que nada cuadraba. Ahora muestra «R total del día» y la media
  etiquetada «media X R/trade».
- Un archivo: `frontend/src/components/backtester/tabs/CalendarTab.tsx`.

### 5. Etiquetas de organización de estrategias (tags) — 23-sep
- **Commit:** `9016fb1` (motor: `backend/app/services/strategy_tags.py` + columna `tags`
  en la tabla `strategies`; frontend: `TagEditor.tsx`, `StrategyPickerMenu.tsx` con
  filtros, tags en el Baúl).
- **Migración en local:** `init_db.py` crea la columna en BDs nuevas; en un
  `users.duckdb` existente hay que añadir a mano `ALTER TABLE strategies ADD COLUMN IF NOT EXISTS tags VARCHAR`
  (o regenerar la BD local). Sin ella, el listado sale sin etiquetas (es tolerante a
  propósito: nunca rompe).
- Los tags `premarket` / `rth` / `scalping` / `piramidacion` NO se guardan: el frontend
  los deriva de la definición (así no quedan desactualizados al editar).
- Conflictos esperados: `routers/strategies.py` y `BaulTab.tsx` (staging reestructuró el
  portfolio a dos pestañas el 21-sep; la integración en la rama de Álvaro ya resolvió
  esa unión en el merge `f5b1be7` — tomarla de referencia).

### 6. Compartida B200 (`aa06`) — VA YA EN ESTE PUSH, no necesita cherry-pick
- `estrategias_compartidas/alvaro/b200-nueva-estrategia--aa06.json` viaja en este mismo
  commit de staging. «Refrescar» + «Importar copia» y listo.
- **Sin `lot_tp` a propósito:** corre en CUALQUIER rama sin dependencia del §1.
  Números y advertencias (locates no incluidos): entradas [TRABAJO 22-09·2] y
  [COMPARTIDA · 23-09] de la MEMORIA_MADRE que viaja aquí.

## Lo que staging YA tiene (no re-traer; verificado 23-sep)
camino de condiciones (`same_bar`) · fix del SL por lote en la fusión (`b2b96cf`) · fix
del guardado scalping (`b0e1b03`) · picos y valles Fase 1/1b · fix del borrador tras
correr otra (`builderDraftOriginId`) · CSV de Trades · pestaña Rachas · rearme del camino
al disparar · visor de pirámides · escalera del scalping.

## Verificación esperada tras traerlo todo
Referencia de la rama de Álvaro al 23-sep (merge de staging `f5b1be7` + tags `9016fb1`):
**suite backend `pytest tests`: 1585 passed, 118 skipped, 3 xfailed** · `npx tsc
--noEmit` limpio. OJO: `openpyxl==3.1.5` ya está en `requirements.txt` — instalarlo si
el venv es viejo (sin él, `test_portfolio_crudo_cuenta_real.py::test_fichero_xlsx…`
falla con ModuleNotFoundError). Y ojo también: correr `pytest tests`, no `pytest` a
secas (`scripts/test_strategy_save.py` es un script con `sys.exit` que revienta la
recolección). Los tests llegan con sus propios cherry-picks (TP por lote, Fase 2,
tags: 6).

## Regla de la casa que sigue en pie
La zona del bot de avisos no se toca: estos cherry-picks no la pisan, pero si algún
conflicto cae ahí, parar y preguntar a Jaume (ver «Zona cerrada» del AGENTS.md).
