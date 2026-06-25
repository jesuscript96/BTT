# PRD ejecutable — Helper guiado del Backtester ("Tour Entendido")

> Documento al nivel de `docs/manual-prd/GUIA_PRD_EJECUTABLE.md`: anclado en código real
> (`fichero:línea`), cero ambigüedad, ejemplo copiable y criterios de aceptación verificables.
> Pensado para que la ejecución la pueda hacer incluso un modelo menor sin adivinar nada.

---

## 1. Context (por qué)

El backtester de Edgecute es potente pero **intimidante para el recién llegado**: para lanzar un
backtest hay que configurar **tres piezas separadas** —Universo (dataset), Estrategia (lógica) y
Ajustes (capital/riesgo/comisiones)— repartidas en un panel lateral y dos *drawers* que se
despliegan. Un usuario nuevo no sabe por dónde empezar ni qué poner.

**Objetivo:** un *tour guiado paso a paso* que, la **primera vez** que el usuario llega a
`/backtester`, **rellena un backtest de ejemplo a la vista** y lo explica resaltando lo
estratégicamente importante, obligando a pulsar **"Entendido"** en cada paso. Con:
- una **frase de intro** que avisa de que "lo que vale, cuesta";
- un **contador de pasos visible** todo el rato;
- **botón de saltar** siempre disponible;
- un **acceso directo** en la cabecera del backtester para **volver a verlo**.

Se construye con **[Driver.js](https://driverjs.com/docs/installation)** (overlay + popover guiado).

**Resultado esperado:** el usuario entiende las 3 piezas viendo un ejemplo real montado delante
de él, y termina con el formulario relleno y el botón *Ejecutar* resaltado para pulsarlo él mismo.

---

## 2. Realidad anclada en el código (lo que YA existe — no reinventar)

### 2.1 La página y sus modos
`frontend/src/app/backtester/page.tsx` es la página. Estado clave:
- `const [mode, setMode] = useState<"config" | "builder_choice" | "builder" | "wizard" | "dataset">("config")` — [page.tsx:28](frontend/src/app/backtester/page.tsx). `setMode` abre/cierra los *drawers*.
- Layout: `<aside width:280>` con `<BacktestPanel>` (panel de Ajustes, siempre visible) — [page.tsx:761](frontend/src/app/backtester/page.tsx); `<main>` con resultados; dos *drawers* absolutos a `left:280` para Estrategia ([page.tsx:1229](frontend/src/app/backtester/page.tsx)) y Dataset ([page.tsx:1318](frontend/src/app/backtester/page.tsx)).
- El *backdrop* oscuro con `onClick={() => setMode('config')}` cuando hay drawer abierto — [page.tsx:1212](frontend/src/app/backtester/page.tsx). **Hay que neutralizarlo mientras el tour está activo** (ver §5.5).
- El builder de Estrategia se monta **condicionalmente** (`{mode === 'builder' && <InlineStrategyBuilder ... initialStrategy={builderDraft || activeStrategy} />}`) — [page.tsx:1295](frontend/src/app/backtester/page.tsx). El de Dataset está **siempre montado** (drawer translado fuera de pantalla) — [page.tsx:1334](frontend/src/app/backtester/page.tsx).
- `const [builderDraft, setBuilderDraft] = useState<Draft|null>(null)` — [page.tsx:78](frontend/src/app/backtester/page.tsx). **Esto es la vía oficial para precargar la estrategia**: fluye a `initialStrategy` del builder.

### 2.2 El contrato de eventos DORMIDO (la clave de la arquitectura)
Existe un mecanismo "rellenar formulario por evento", **pero está comentado (POST-MVP AGENTIC) y
nadie escucha los eventos todavía** (verificado: no hay ningún `addEventListener('fill-*')` activo):
- `BacktestPanel` despacharía `window.dispatchEvent(new CustomEvent("fill-backtest-form", { detail }))` — [BacktestPanel.tsx:335](frontend/src/components/backtester/BacktestPanel.tsx) (dentro de bloque `/* POST-MVP */`).
- `InlineDatasetBuilder` → `fill-dataset-builder` — [InlineDatasetBuilder.tsx:83](frontend/src/components/backtester/InlineDatasetBuilder.tsx).
- `InlineStrategyBuilder` → `fill-strategy-builder` — [InlineStrategyBuilder.tsx:317](frontend/src/components/backtester/InlineStrategyBuilder.tsx).
- `ChatBotAgentic` (no montado) también los despacha — [ChatBotAgentic.tsx:482-494](frontend/src/components/ChatBotAgentic.tsx).

**Decisión de arquitectura:** el helper **revive este contrato** añadiendo los *listeners* que
faltan (en `BacktestPanel` y `InlineDatasetBuilder`). Es trabajo que el asistente Edgie necesitaría
de todas formas → **forward-compatible**. Para la Estrategia no hace falta listener: se usa la vía
`builderDraft → initialStrategy` que ya funciona (ver 2.3).

### 2.3 Cómo el builder de Estrategia consume `initialStrategy`
[InlineStrategyBuilder.tsx:378-426](frontend/src/components/backtester/InlineStrategyBuilder.tsx): un `useEffect` lee `initialStrategy` (o `initialStrategy.definition`) y aplica `setBias`, `setApplyDay`, `setEntryLogic`, `setExitLogic`, `setRiskManagement`, `setLocalMarketSessions`, `setLocalCustomStartTime/EndTime`, `setSelectedDataset`/`setUniverseFilters`. Guardado por `lastLoadedStrategyRef`. Para `id:"draft"` carga **una vez por montaje** ([:380](frontend/src/components/backtester/InlineStrategyBuilder.tsx)); como el builder se desmonta/remonta al cambiar `mode`, **al re-abrirlo se recarga** → sirve para el *replay*.
⇒ **Precargar la estrategia = `setBuilderDraft(EJEMPLO.strategy)` + `setMode('builder')`.**

### 2.4 Tipos AUTORITATIVOS del ejemplo
- Enums en [frontend/src/types/strategy.ts](frontend/src/types/strategy.ts): `IndicatorType` (`BAR_CLOSE="Bar Close"`, `BAR_OPEN="Bar Open"`, `VWAP="VWAP"`…), `Comparator` (`LT="LESS_THAN"`, `GT="GREATER_THAN"`, `CROSSES_ABOVE/BELOW`…), `Timeframe` (`M1="1m"`…), `RiskType` (`PERCENTAGE="Percentage"`, `TIME="Time"`…), `TakeProfitMode` (`FULL="Full"`).
- El tipo del borrador es `Draft` exportado por el builder — [InlineStrategyBuilder.tsx:128-144](frontend/src/components/backtester/InlineStrategyBuilder.tsx): `{ id, name, bias, apply_day, postgap_preconditions, entry_logic, exit_logic, risk_management, market_sessions, custom_start_time, custom_end_time, dataset_id, universe_filters, created_at }`.
- ⚠️ **Hay dos formas de `risk_management` en circulación**: la AUTORITATIVA es `types/strategy.ts` (`use_hard_stop`, `hard_stop:{type,value}`, `use_take_profit`, `take_profit`, `partial_take_profits`, `accept_reentries`, `size_by_sl`, `swing_option`) — la que consume `RiskManagement.tsx` ([:14, :143, :590](frontend/src/components/strategy-builder/RiskManagement.tsx)). Existe un *default legacy inconsistente* (`use_stop_loss/fixed_stop_loss_pct/time_exit_value`) en [page.tsx:820-834](frontend/src/app/backtester/page.tsx) que **NO se usa en nuestro camino** (solo es fallback cuando falta `risk_management`). Nuestro ejemplo provee `risk_management` completo en la forma autoritativa.

### 2.5 El builder de Dataset (Universo)
[InlineDatasetBuilder.tsx](frontend/src/components/backtester/InlineDatasetBuilder.tsx): parámetros por sección en `SECTION_PARAMS` ([:22-30](frontend/src/components/backtester/InlineDatasetBuilder.tsx)): `rth_close`(Open price $), `pm_open`($), `pmh_gap_pct`(PM High Gap %), `pm_volume`(M), `gap_pct`(%), `rth_volume`(M), `rth_range_pct`(%). Secciones: `gap_day`, `gap_plus_1_day`, `gap_plus_2_day`. Estado interno: `name`, `dateFrom`, `dateTo`, `values: Record<SectionId, Record<paramKey, {op,val1,val2}>>` ([:131](frontend/src/components/backtester/InlineDatasetBuilder.tsx)), `includedConditions: IncludedCondition[]` ([:137](frontend/src/components/backtester/InlineDatasetBuilder.tsx), forma `{section,paramKey,label,op,val1,val2?,unit}` en [:50-58](frontend/src/components/backtester/InlineDatasetBuilder.tsx)). **No acepta props iniciales** → usaremos el *listener* `fill-dataset-builder`.

### 2.6 El panel de Ajustes (BacktestPanel)
[BacktestPanel.tsx](frontend/src/components/backtester/BacktestPanel.tsx): estado local (no props): `initCash`(10000), `riskR`(100), `riskType`("FIXED"|"PERCENT"|"FIXED_RATIO"), `fees`(0.01), `feeType`("PERCENT"|"FLAT"), `slippage`(0.01), `marketSessions`(["rth"]), `customStartTime`/`customEndTime`, `isPercent`(100) — [:416-433](frontend/src/components/backtester/BacktestPanel.tsx). Botón **Ejecutar Backtest** — [:1578](frontend/src/components/backtester/BacktestPanel.tsx) (`disabled` si no hay dataset+estrategia seleccionados). Botones **Nueva Estrategia** ([:1093](frontend/src/components/backtester/BacktestPanel.tsx)) y **Nuevo Dataset**. Ya sincroniza `marketSessions` desde la estrategia seleccionada — [:608-627](frontend/src/components/backtester/BacktestPanel.tsx).

### 2.7 Sesión de mercado = mecanismo de la "salida a las 11:00"
El selector "¿En qué sesión deseas ejecutar la estrategia?" (Pre/RTH/After/**Horas personalizadas** con *Desde/Hasta ET*) vive en el builder de Estrategia y escribe `market_sessions`/`custom_start_time`/`custom_end_time` en el draft. **El builder NO tiene salida por hora de reloj** (verificado: el Take Profit solo admite `% Distancia`, `Tiempo (minutos desde la entrada)` o `EOD` — [RiskManagement.tsx:614-616, 681-711](frontend/src/components/strategy-builder/RiskManagement.tsx)). Por decisión del usuario, **el "Take Profit a las 11:00 NY" se codifica como sesión personalizada 09:30 → 11:00 ET**: la estrategia solo gestiona posiciones dentro de la ventana, forzando el cierre a las 11:00.

### 2.8 Layout, tokens, primera visita
- Layout global: [LayoutShell.tsx](frontend/src/components/LayoutShell.tsx) (Sidebar + `<main>`). El sidebar ([Sidebar.tsx](frontend/src/components/Sidebar.tsx)) NO es el sitio del acceso directo: va en la **cabecera de la página** del backtester ([page.tsx:738-757](frontend/src/app/backtester/page.tsx), junto al `<h1>Backtester</h1>`).
- Tokens de diseño en [globals.css:4-17](frontend/src/app/globals.css): `--color-ec-copper:#D87A3D` (acento), `--color-ec-bg-surface:#1C1E21`, `--color-ec-bg-elevated:#232528`, `--color-ec-border:#2C2F33`, `--color-ec-text-high/primary/secondary/muted`, `--color-ec-copper-text:#1A0A00`. Fuentes: `var(--color-ec-sans)` ("General Sans"), `var(--color-ec-serif)`. **El popover del tour debe usar estos tokens.**
- No existe ningún onboarding/tour previo. La gate de "primera visita" se hace con `localStorage` (patrón ya usado para el popup de novedades). **driver.js NO está instalado** (0 en `package-lock.json`).

---

## 3. El backtest de EJEMPLO (especificación cero-ambigüedad)

**Nombre pedagógico:** *"Fade de gap parabólico (+70%)"* — un **short** clásico de small-caps.
Es exactamente lo que pidió el usuario. Todos los valores son enums/strings reales del repo (§2.4).

### 3.1 Universo (Dataset) — payload del evento `fill-dataset-builder`
```ts
{
  name: "Ejemplo · Gap PMH ≥ 70%",
  dateFrom: TWO_YEARS_AGO,           // = InlineDatasetBuilder TWO_YEARS_AGO (hoy - 2 años)
  dateTo: MAX_DATE,                  // = hoy (YYYY-MM-DD)
  values: {
    gap_day: { pmh_gap_pct: { op: ">=", val1: "70", val2: "" } },
    gap_plus_1_day: {},
    gap_plus_2_day: {},
  },
  includedConditions: [
    { section: "gap_day", paramKey: "pmh_gap_pct", label: "PM High Gap", op: ">=", val1: 70, unit: "%" },
  ],
}
```
> Único filtro: **PMH Gap ≥ 70%** (lo que el usuario especificó). `paramKey` y `label` deben
> calzar con `SECTION_PARAMS` ([InlineDatasetBuilder.tsx:25](frontend/src/components/backtester/InlineDatasetBuilder.tsx)).

### 3.2 Estrategia (Draft) — vía `setBuilderDraft(...)`
```ts
{
  id: "draft",
  name: "Ejemplo · Fade gap +70%",
  bias: "short",
  apply_day: "gap_day",
  postgap_preconditions: [],
  entry_logic: {
    timeframe: "1m",                         // Timeframe.M1
    root_condition: {
      type: "group", operator: "AND",
      conditions: [
        // Vela M1 roja (cierre por debajo de su apertura)
        { type: "indicator_comparison", source: { name: "Bar Close" }, comparator: "LESS_THAN",    target: { name: "Bar Open" }, timeframe: "1m" },
        // ...y por encima de VWAP
        { type: "indicator_comparison", source: { name: "Bar Close" }, comparator: "GREATER_THAN", target: { name: "VWAP" },     timeframe: "1m" },
      ],
    },
    entry_time_windows: [],                  // la ventana la limita la sesión (abajo)
  },
  exit_logic: {                              // sin condición de salida por indicador:
    timeframe: "1m",                         // sale por stop 50% o por fin de sesión (11:00)
    root_condition: { type: "group", operator: "AND", conditions: [] },
  },
  risk_management: {
    use_hard_stop: true,
    hard_stop: { type: "Percentage", value: 50 },   // SL = 50% del precio de entrada
    use_take_profit: false,                          // el "TP" es la salida por hora (sesión)
    take_profit_mode: "Full",
    take_profit: { type: "Percentage", value: 6 },   // ignorado (use_take_profit=false)
    partial_take_profits: [],
    trailing_stop: { active: false, type: "Percentage", buffer_pct: 0.5 },
    accept_reentries: false,                          // sin reentradas
    max_reentries: -1,
    size_by_sl: false,
    swing_option: { active: false, target_day: "gap_1_day" },
  },
  market_sessions: ["custom"],               // Horas personalizadas
  custom_start_time: "09:30",                // apertura RTH
  custom_end_time: "11:00",                  // ← fuerza la salida a las 11:00 NY
  dataset_id: undefined,
  universe_filters: undefined,
  created_at: new Date().toISOString(),
}
```
> **Verificar** en ejecución que `validateStrategyLogic(entry, exit)` ([lib/strategyValidation.ts](frontend/src/lib/strategyValidation.ts)) acepta `exit_logic` vacío cuando hay `hard_stop` activo. Si lo rechazara (fallback): añadir a `exit_logic.conditions` una condición espejo de cobertura, o documentarlo; preferimos mantener la salida por sesión+stop tal cual.

### 3.3 Ajustes (Config) — payload del evento `fill-backtest-form`
```ts
{
  initCash: 10000,
  riskType: "FIXED", riskR: 100,             // riesgo fijo de 100$ (1R)
  feeType: "PERCENT", fees: 0.01,
  slippage: 0.01,
  marketSessions: ["custom"], customStartTime: "09:30", customEndTime: "11:00",
  isPercent: 100,
}
```

Estos tres objetos viven en **un único módulo** `exampleBacktest.ts` (§5.1) como fuente de verdad.

---

## 4. Storyboard del tour (9 pasos, agrupados)

Contador siempre visible: **"Paso {{current}} de 9"**. `Entendido →` avanza; `Saltar` y `✕`
salen. Sin botón "atrás" (tour solo-hacia-delante, simplifica la coreografía de *drawers*).

| # | Modo | Preparación (antes de resaltar) | Elemento `[data-helper]` | Copy (resumen) |
|---|------|----------------------------------|--------------------------|----------------|
| 1 | config | — (popover centrado, sin elemento) | — | **"Vas a montar tu primer backtest. Lo que vale, cuesta"** → te acompaño con un ejemplo ya montado; pulsa *Entendido* en cada paso. |
| 2 | config | — | `panel-root` (todo el `<aside>`) | Un backtest = **3 piezas**: Universo, Estrategia y Ajustes. Aquí se orquestan. |
| 3 | dataset | `setMode('dataset')` + `dispatch(fill-dataset-builder, EJEMPLO.dataset)` | `ds-gapday` (sección GAP DAY) | **Universo**: solo los días con **PMH Gap ≥ 70%** (gaps parabólicos). Más filtros = universo más fino. |
| 4 | builder | `setBuilderDraft(EJEMPLO.strategy)` + `setMode('builder')` | `st-bias` (dirección + día) | **Estrategia**: vas **CORTO** el **día del gap** (fade de la subida). |
| 5 | builder | — | `st-entry` (lógica de entrada) | **Entrada**: vela **M1 roja por encima del VWAP** (señal de agotamiento). |
| 6 | builder | — | `st-sessions` (selector de sesión) | **Salida temporal**: *Horas personalizadas* **09:30 → 11:00 ET** → cierra a las **11:00 NY**. |
| 7 | builder | — | `st-risk` (gestión de riesgo) | **Riesgo**: Stop **50%** del precio de entrada, **sin reentradas**, sin take-profit por precio. |
| 8 | config | `setMode('config')` + `dispatch(fill-backtest-form, EJEMPLO.config)` | `cfg-capital` (Capital + 1R) | **Ajustes**: $10.000 de capital, riesgo **fijo 100$** por operación (1R). |
| 9 | config | — | `cfg-run` (botón Ejecutar) | Todo listo. Cuando tengas tu **dataset y estrategia guardados y seleccionados**, este botón se activa: púlsalo tú. **¡Hecho!** |

> Agrupación: fusiona costes/slippage/IS-OOS dentro del paso 8 (mención breve) para no inflar
> pasos. Total **9** (intro + mapa + 1 universo + 3 estrategia + 1 ajustes + ejecutar).
> El texto íntegro de cada paso (ES, tono cercano) se redacta en `steps.ts` (§5.2).

---

## 5. Cambios por fichero (implementación)

### 5.0 Dependencia
`cd frontend && npm install driver.js` (1.x). Import: `import { driver } from "driver.js"; import "driver.js/dist/driver.css";` (confirmar nombres de la API contra la versión instalada y los [docs](https://driverjs.com/docs/installation)).

### 5.1 NUEVO `frontend/src/components/backtester/helper/exampleBacktest.ts`
Exporta `EXAMPLE_DATASET`, `EXAMPLE_STRATEGY` (`Draft`), `EXAMPLE_CONFIG` exactamente como §3,
importando enums de `@/types/strategy` y `TWO_YEARS_AGO`/`MAX_DATE` (replicar las constantes de
`InlineDatasetBuilder.tsx:60-64`). Tipar `EXAMPLE_STRATEGY` como `Draft` (import de `InlineStrategyBuilder`).

### 5.2 NUEVO `frontend/src/components/backtester/helper/steps.ts`
Array de definiciones de paso: `{ id, mode, prepare?: 'dataset'|'strategy'|'config', element?, popover:{title,description,side,align} }` con el copy completo en español. Mantener exactamente los 9 pasos y selectores `[data-helper="…"]` de la tabla §4.

### 5.3 NUEVO `frontend/src/components/backtester/helper/useBacktestHelper.ts`
Hook `useBacktestHelper(ctrl: { setMode, loadExampleStrategy, fillConfig, fillDataset, setHelperActive })` que devuelve `{ startHelper }` y:
- **Crea el `driver(...)`** con: `showProgress:true`, `progressText:"Paso {{current}} de {{total}}"`, `allowClose:false`, `disableActiveInteraction:true`, `showButtons:["next"]`, `nextBtnText:"Entendido →"`, `doneBtnText:"¡Hecho!"`, `popoverClass:"ec-helper-popover"`, `steps` (mapeados desde `steps.ts`), `onDestroyed: () => { ctrl.setHelperActive(false); markSeen(); }`.
- **Coreografía de modos/relleno (patrón robusto):** la preparación de un paso se hace en el
  `onNextClick` del paso ANTERIOR, con retardo para la transición del drawer (300ms CSS):
  ```ts
  onNextClick: () => { ctrl.setMode('dataset'); ctrl.fillDataset(); setTimeout(() => d.moveNext(), 350); }
  ```
  Para el paso 4 (estrategia): `ctrl.loadExampleStrategy()` (= `setBuilderDraft(EXAMPLE_STRATEGY)`) + `setMode('builder')`. Para el 8: `setMode('config')` + `ctrl.fillConfig()`. (Alternativa equivalente: hacerlo en `onHighlightStarted` + `d.refresh()` tras 350ms; elegir una y ser consistente.)
- **Saltar siempre visible:** en `onPopoverRender(popover)` inyectar un botón "Saltar tutorial" en `popover.footerButtons` que llame `d.destroy()`.
- **Inicio:** `startHelper()` → `ctrl.setHelperActive(true)`, resetea estado al paso 1 y `d.drive()`.
- **Gate de primera visita:** constante `SEEN_KEY = "edgecute:bt-helper:v1:seen"`. `markSeen()` setea localStorage. Exportar también `hasSeenHelper()`.

### 5.4 NUEVO `frontend/src/components/backtester/helper/helper.css` (tema del popover)
Clase `.ec-helper-popover` (y `.driver-popover.ec-helper-popover`) con tokens: fondo `--color-ec-bg-surface`, borde `--color-ec-border`, títulos `--color-ec-text-high` + `--color-ec-serif`, texto `--color-ec-text-secondary` + `--color-ec-sans`, botón *Entendido* fondo `--color-ec-copper` color `--color-ec-copper-text`, barra de progreso en copper. Importar el CSS una vez (en el hook o en la página).

### 5.5 EDIT `frontend/src/app/backtester/page.tsx`
- Importar y llamar `useBacktestHelper({ setMode, loadExampleStrategy: () => setBuilderDraft(EXAMPLE_STRATEGY as any), fillConfig, fillDataset, setHelperActive })`.
- `fillConfig`/`fillDataset` = funciones que hacen `window.dispatchEvent(new CustomEvent('fill-backtest-form'|'fill-dataset-builder', { detail: EXAMPLE_CONFIG|EXAMPLE_DATASET }))`.
- **Auto-arranque primera visita:** `useEffect(() => { if (!hasSeenHelper() && window.innerWidth > 1024) { const t = setTimeout(startHelper, 800); return () => clearTimeout(t); } }, [])` (delay para que el panel cargue sus datos).
- **Acceso directo (replay):** en la cabecera ([page.tsx:748](frontend/src/app/backtester/page.tsx), junto al `<h1>`) un botón `¿Cómo funciona?` con icono `GraduationCap`/`HelpCircle` (lucide, ya disponible) → `onClick={startHelper}`, estilado con tokens.
- **Guard del backdrop:** `const [helperActive, setHelperActive] = useState(false)` y cambiar el `onClick` del backdrop ([page.tsx:1213-1214](frontend/src/app/backtester/page.tsx)) a `onClick={() => { if (!helperActive) setMode('config'); }}` para que el tour no se cierre por un clic perdido.

### 5.6 EDIT `frontend/src/components/backtester/BacktestPanel.tsx`
Añadir un `useEffect` (fuera del bloque comentado) que escuche `fill-backtest-form` y mapee `detail` a los setters: `initCash→setInitCash`, `riskType→setRiskType`, `riskR→setRiskR`, `feeType→setFeeType`, `fees→setFees`, `slippage→setSlippage`, `marketSessions→setMarketSessions`, `customStartTime→setCustomStartTime`, `customEndTime→setCustomEndTime`, `isPercent→setIsPercent` (aplicar solo claves presentes). Añadir `data-helper="panel-root"` al `<div>` raíz ([:825](frontend/src/components/backtester/BacktestPanel.tsx)), `data-helper="cfg-capital"` al grid Capital/1R ([:1168](frontend/src/components/backtester/BacktestPanel.tsx)), `data-helper="cfg-run"` al botón Ejecutar ([:1578](frontend/src/components/backtester/BacktestPanel.tsx)).

### 5.7 EDIT `frontend/src/components/backtester/InlineDatasetBuilder.tsx`
Añadir un `useEffect` que escuche `fill-dataset-builder` y aplique `detail` a `setName`, `setDateFrom`, `setDateTo`, `setValues`, `setIncludedConditions` (merge sobre el estado inicial). Añadir `data-helper="ds-gapday"` al contenedor de la sección GAP DAY y `data-helper="ds-dates"` al bloque de fechas.

### 5.8 EDIT `frontend/src/components/backtester/InlineStrategyBuilder.tsx`
Solo **anclas** (la precarga ya va por `initialStrategy`, §2.3): `data-helper="st-bias"` (sección dirección/día), `st-entry` (lógica de entrada), `st-sessions` (selector de sesión de mercado), `st-risk` (gestión de riesgo). Localizar cada sección por sus encabezados existentes.

### 5.9 Persistir el PRD
Como primer paso de ejecución, copiar este documento a `docs/helper-backtester/PRD_HELPER_BACKTESTER.md` (junto a `docs/manual-prd/`) para que quede versionado en el repo.

---

## 6. Detalles de Driver.js (anti-sorpresas)

- **Forzar el botón**: `allowClose:false` (clic en overlay/Esc no cierra) + `disableActiveInteraction:true` (el campo resaltado no es interactivo: es demo). Único avance = *Entendido*; salida = *Saltar*/*✕*.
- **Paso intro centrado**: step sin `element` → popover centrado en viewport.
- **z-index**: el overlay de driver.js va por encima (≈10000) del sidebar (z45), drawers (z40) y backdrop (z35). El elemento activo lo eleva driver.js. **Verificar** que el resalte no queda tapado dentro del drawer; si hiciera falta, ajustar `stagePadding`/z-index o asegurar que el drawer ya esté visible antes de resaltar (de ahí el retardo de 350ms).
- **Transiciones**: los drawers animan 300ms ([page.tsx:1239](frontend/src/app/backtester/page.tsx)). Preparar modo/relleno en el `onNextClick` previo + `setTimeout(...,350)` antes de `moveNext()` evita resaltar un elemento aún fuera de pantalla.
- **Móvil**: el auto-arranque solo en `innerWidth > 1024` (el layout de drawers no está pensado para móvil). El botón de replay siempre disponible.

---

## 7. Criterios de aceptación / Definition of Done

1. Primera visita a `/backtester` (localStorage limpio, desktop) → el tour arranca solo tras ~0.8s.
2. Los **9 pasos** se recorren con *Entendido*; el contador muestra **"Paso N de 9"** siempre.
3. Paso 3 abre el drawer de Dataset **relleno** con PMH Gap ≥ 70% (condición incluida visible).
4. Pasos 4-7 abren el builder de Estrategia **relleno**: short / día del gap / entrada "Bar Close < Bar Open AND Bar Close > VWAP" en 1m / sesión personalizada **09:30-11:00** / stop 50% / sin reentradas.
5. Paso 8 vuelve a Ajustes con **1R = 100$ (Fijo)** y capital 10.000$ visibles.
6. *Saltar* y *✕* cierran el tour y marcan visto; recargar **no** vuelve a lanzarlo.
7. El botón **"¿Cómo funciona?"** de la cabecera relanza el tour en cualquier momento.
8. `npm run build` (tsc) pasa sin errores nuevos; sin warnings de consola al recorrer el tour.
9. Ningún efecto secundario: el tour **no** crea datasets/estrategias reales ni lanza backtests.

---

## 8. Verificación end-to-end

1. `cd frontend && npm install driver.js && npm run dev`.
2. En el navegador, DevTools → `localStorage.removeItem('edgecute:bt-helper:v1:seen')`, recargar `/backtester` → confirmar auto-arranque y los 9 pasos (criterios §7). Las MCP de *Claude Preview* (`preview_*`) pueden usarse para *screenshot* de cada paso.
3. Probar *Saltar*, recarga (no relanza), y el botón de cabecera (relanza).
4. Revisar que los valores precargados coinciden con §3 (abrir cada drawer y leer los campos).
5. `npm run build` para validar TypeScript.

---

## 9. Riesgos / anti-patrones a evitar

- **No** reimplementar el relleno: reutilizar el contrato de eventos (§2.2) y `initialStrategy` (§2.3).
- **No** usar la forma legacy de `risk_management` de [page.tsx:820-834](frontend/src/app/backtester/page.tsx): usar la de `types/strategy.ts` (§2.4).
- **No** inventar salida por hora de reloj: usar la **sesión personalizada 09:30-11:00** (§2.7).
- **No** dejar que el tour corra backtests reales (el usuario eligió "parar en Ejecutar").
- **No** anclar a selectores frágiles: usar siempre `[data-helper="…"]` añadidos a propósito.
- Vigilar que el guard `helperActive` impide que un clic en el backdrop cierre el drawer a media demo.

---

## 10. Archivos tocados (resumen)

**Nuevos:** `helper/exampleBacktest.ts`, `helper/steps.ts`, `helper/useBacktestHelper.ts`, `helper/helper.css`, `docs/helper-backtester/PRD_HELPER_BACKTESTER.md`.
**Editados:** `app/backtester/page.tsx`, `components/backtester/BacktestPanel.tsx`, `components/backtester/InlineDatasetBuilder.tsx`, `components/backtester/InlineStrategyBuilder.tsx`, `frontend/package.json` (driver.js).
