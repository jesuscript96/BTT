# Plan de implementación — Helper del Backtester v2 (Wizard, 9 pasos)

> Consolida la propuesta de **25 pasos** del PM en un tour de **9 paradas**, narrado por
> Edgie sobre un ejemplo **ya pre-rellenado**, recorriendo el **Wizard** (camino para
> principiantes). **Alcance: solo formulario** — el tour termina antes de ejecutar; no
> muestra resultados (Equity / Charts / What-If / OOS). Decidido con Jesús el 2026-06-28.

---

## 1. Diagnóstico: de dónde salen los 25 pasos

El Wizard (`WizardStrategyBuilder.tsx`) tiene **8 sub-pantallas internas** (`STEPS`):

```
universo · bias · apply_day · market_sessions · entry · exit · risk · summary
```

y dentro de `entry` un **mini-constructor de condiciones** (`wizardCondStep`) con 6 sub-pasos
(variable → modo eval → comparación/distancia → relación → objeto → indicador). El PM narra
**una parada por sub-pantalla** → 25.

**Palanca de reducción:** tour narrado sobre un ejemplo **pre-rellenado**. El usuario no
construye nada; observa la anatomía de una estrategia ya montada. Eso permite:

- Colapsar el sub-constructor de la condición en **1 parada** que resalta el **chip final**
  (`getConditionTags` ya pinta las condiciones precargadas como chips removibles → no hace
  falta entrar al sub-constructor).
- Colapsar `bias + apply_day + market_sessions` en **1 parada** ("parámetros del sistema").
- Colapsar `exit + risk(stop) + risk(reentradas)` en **1 parada** ("riesgo, simple").
- Eliminar todo el bloque de resultados (recorte de alcance acordado).

Resultado: **25 → 9**.

---

## 2. Storyboard (9 paradas, solo formulario)

Cada parada resalta su ancla con el fondo atenuado (`overlayOpacity: 0.7`, ya configurado).
El `enter` indica el estado que la página debe tener **antes** de resaltar.

> **Nota de implementación:** el Wizard NO tiene control de IS/OOS (vive en el
> panel de config). Por eso el cierre del tour (paso 9) vuelve a `config` para
> enseñar capital + reparto IS/OOS, y ahí queda el backtest **reflejado**. Además,
> las paradas "condición de entrada" y "ventana horaria" se fusionan en una sola
> (misma pantalla del Wizard). Las anclas del Wizard se resuelven con UN wrapper
> dinámico `data-helper="wiz-<paso>"` sobre `renderStep()` (no una por pantalla).

| # | id | `enter` (mode / paso wizard) | Ancla `data-helper` | Absorbe del PM |
|---|---|---|---|---|
| 1 | `intro` | config | *(centrado)* | Bienvenida |
| 2 | `panel` | config | `panel-root` *(existe)* | Panel principal |
| 3 | `mode` | builder_choice | `mode-selector` *(nuevo)* | Wizard vs libre |
| 4 | `universo` | wizard · `universo` | `wiz-universo` *(dinámico)* | Universo |
| 5 | `params` | wizard · `bias` | `wiz-bias` *(dinámico)* | Dirección + Día + Sesión (3→1) |
| 6 | `entry` | wizard · `entry` | `wiz-entry` *(dinámico)* | Entrada completa + ventana horaria (7→1) |
| 7 | `risk` | wizard · `risk` | `wiz-risk` *(dinámico)* | Salida + Stop + Reentradas (3→1) |
| 8 | `summary` | wizard · `summary` | `wiz-summary` *(dinámico)* | Resumen de la estrategia |
| 9 | `close` | config (fill) | `cfg-capital` *(existe)* | Capital + IS/OOS, **ejemplo reflejado** |

### Copy de los popovers (voz de Edgie — admite HTML simple)

1. **`intro`** · *¡Hola! Soy Edgie 👋*
   > Te voy a montar tu primer backtest conmigo, paso a paso. **Lo que vale, cuesta**, así
   > que te dejo un ejemplo ya armado —*qué pasa si el precio cae por debajo del VWAP en
   > horario de mercado*— y te lo voy contando. Dale a **Entendido** cuando lo pilles (o
   > *Saltar* si ya vas sobrado).

2. **`panel`** · *Tu panel de mando*
   > Desde aquí cargas estrategias que ya tengas guardadas, las configuras o creas una
   > nueva. Antes de simular, acuérdate de fijar **capital, comisiones y riesgo**. Vamos a
   > crear una **nueva estrategia**.

3. **`mode`** · *¿Wizard o modo libre?*
   > Puedes montarla pieza a pieza con el **Wizard**, con componentes básicos, o a pelo en
   > **modo libre** con todas las opciones avanzadas. Como esta es simple, vamos por la línea
   > fácil: el **Wizard**. Tranquilo, *no vas a necesitar programar*.

4. **`universo`** · *1 · El Universo*
   > Toda estrategia son tres bloques: **universo · parámetros · riesgo**. Empezamos por el
   > universo: qué días miro. Por ejemplo, que el **gap del día sea > 50 %** o el **volumen
   > de premarket de 5 M**. Cuantos más filtros, más fino (y más pequeño) el universo.

5. **`params`** · *2 · Parámetros del sistema*
   > Ahora la dirección y el cuándo. Voy **CORTO**, opero **solo el día del gap** y en
   > **horario de mercado (RTH)** —porque vamos a probar qué pasa cuando el precio atraviesa
   > el VWAP—. Te lo dejo ya marcado.

6. **`entry-cond`** · *2 · La entrada (la chicha)*
   > Quiero entrar cuando el cierre de la vela (**Close**) **cruza por debajo del VWAP**.
   > El Wizard también permite medir **distancia** a otra variable para sistemas más finos,
   > pero como aquí solo comparamos Close con VWAP, nos quedamos en **modo comparación**. Ya
   > te lo dejo montado: *Close ✕ VWAP (cruza por debajo)*.

7. **`entry-windows`** · *2 · Ventana de entrada*
   > Podríamos entrar a cualquier hora, pero, ¿y si solo opero cuando el mercado está más
   > volátil? Fijo la ventana de **09:30 a 11:00** y solo acepto entradas ahí.

8. **`risk`** · *3 · El riesgo, simple*
   > La salida la dejamos **sin condición por indicador**: salimos por stop o por la hora.
   > Pongo un **stop del 20 %** y permito un **máximo de 2 reentradas** si la cosa va en
   > contra. Mi premisa: cuanto más simple la estrategia, **mejor**.

9. **`summary`** · *¡Y aquí lo tienes!*
   > El resumen de toda tu estrategia. Antes de correrla, **no te olvides de fijar el reparto
   > IS / OOS** —te recomiendo un **OOS del 20 %**— para cazar el sobreajuste. Cuando la
   > tengas guardada y seleccionada arriba, el botón de correr se enciende y lo pulsas tú.
   > ¿Repetir el tour? Me tienes en *¿Cómo funciona?*. — Edgie

> **Lever de granularidad:** si en pruebas el salto de pantallas del paso 5 (bias → día →
> sesión sin popover intermedio) se siente brusco, se parte en 3 micro-paradas → 11 pasos.
> Sigue muy por debajo de 25. Recomendación: empezar en 9 y validar en pantalla.

---

## 3. Cambios técnicos (sobre el código real)

### 3.1 `helper/steps.ts`
- Ampliar `HelperMode`: `"config" | "dataset" | "builder" | "builder_choice" | "wizard"`.
- Añadir al `enter` un campo opcional `wizardStep?: StepKey` para los pasos 4–9.
- Reescribir `HELPER_STEPS` con las 9 paradas y el copy de arriba.

### 3.2 `helper/exampleBacktest.ts`
El ejemplo actual **no coincide** con el guion nuevo (hoy: *vela M1 roja por encima de
VWAP / stop 50 % / sin reentradas*). Actualizar `EXAMPLE_STRATEGY` a:
- `entry_logic.root_condition`: una sola condición `BAR_CLOSE` **`CROSSES_BELOW`** `VWAP`
  (enum confirmado en `@/types/strategy`).
- `risk_management.hard_stop`: `{ type: PERCENTAGE, value: 20 }`.
- `risk_management.accept_reentries: true`, `max_reentries: 2`.
- `entry_time_windows`: `09:30 → 11:00` (en lugar de codificarlo como sesión custom).
- `EXAMPLE_CONFIG.isPercent: 80` (OOS = 20 %).

### 3.3 `WizardStrategyBuilder.tsx` — pilotaje externo (única pieza nueva de fondo)
Hoy el Wizard gobierna su `currentStep` internamente. Añadir un **listener de evento**
(mismo patrón que los `fill-*` existentes):

```ts
useEffect(() => {
  const onSetStep = (e: CustomEvent<{ step: StepKey }>) => {
    const i = STEPS.findIndex(s => s.key === e.detail.step);
    if (i >= 0) setCurrentStep(i);
  };
  window.addEventListener("wizard-set-step", onSetStep as EventListener);
  return () => window.removeEventListener("wizard-set-step", onSetStep as EventListener);
}, []);
```

Anclas `data-helper` a colocar en sus `renderXStep()`:
`wiz-universo`, `wiz-params` (contenedor del paso bias), `wiz-entry-cond` (el chip de la
condición vía `getConditionTags`), `wiz-entry-windows`, `wiz-risk`, `wiz-summary`, `wiz-isoos`
(el control de reparto IS/OOS).

### 3.4 `StrategyModeSelector.tsx`
Añadir `data-helper="mode-selector"` al contenedor de las dos opciones (Wizard / libre).

### 3.5 `helper/useBacktestHelper.ts` — coreografía
- En `applyEnter`, para pasos con `enter.mode === "wizard"`: `setMode('wizard')` +
  `loadExampleStrategy()` (si aún no), y despachar `wizard-set-step` con `enter.wizardStep`
  **antes** de resaltar.
- Subir el margen de transición de `380ms` cuando hay cambio de sub-pantalla del Wizard
  (montaje + animación). Validar el valor en pruebas.
- `cleanup(completed)`: si el usuario **completa** el tour, se DEJA el ejemplo reflejado
  (estrategia en `builderDraft` + capital/OOS en config) para que lo guarde y corra; si lo
  **salta**, se restaura el `builderDraft` previo y se resetea lo que tocó.
- La gate de primera visita (`localStorage`) y el re-lanzamiento ya existen — sin cambios.

> **Estado: IMPLEMENTADO Y VERIFICADO** (28-jun-2026). Tour completo de 9 pasos probado en
> navegador: cada parada resalta su ancla correcta, el ejemplo se refleja en el Wizard
> (universo PMH Gap ≥ 70%, Short, Gap Day, RTH, chip "Bar Close ↘ Crosses Below VWAP",
> ventana 09:30–11:00, stop 20%), el resumen agrega todo, y al completar el panel de config
> queda con capital 10.000$, riesgo 100$ e IS/OOS 80/20. Sin errores de consola.

### 3.6 `app/backtester/page.tsx`
El `HelperController.setMode` ya acepta los 5 modos. Verificar que `setMode('wizard')` con
`builderDraft` cargado monta `WizardStrategyBuilder` con `initialStrategy` (ya lo hace,
línea ~1383). Sin cambios estructurales esperados.

---

## 4. Plan de verificación

**Tipos:** `npm run build` en `frontend/`.

**Manual (pasada del tour):**
1. Lanzar el helper desde *¿Cómo funciona?* (o primera visita).
2. Cada parada: ancla iluminada + fondo atenuado; la sub-pantalla del Wizard coincide con el
   texto del popover.
3. El paso 6 muestra el **chip** `Close ✕ VWAP (cruza por debajo)` sin abrir el sub-constructor.
4. El tour **termina en el resumen**, sin ejecutar ni mostrar resultados.
5. *Saltar* en cualquier punto → `cleanup` restaura el borrador previo y vuelve a `config`
   sin dejar el ejemplo metido en los formularios del usuario.

---

## 5. Estimación

| Bloque | Esfuerzo |
|---|---|
| `steps.ts` + copy | bajo |
| `exampleBacktest.ts` (nuevo ejemplo) | bajo |
| Anclas en Wizard + ModeSelector | medio (7 anclas en un archivo de 6,6k líneas) |
| Evento `wizard-set-step` + coreografía en el hook | medio (la pieza con más riesgo) |
| Verificación | bajo |

**Total ≈ 1 día.** El riesgo concentrado está en la sincronización
`currentStep` ↔ popover (timings de montaje); todo lo demás reaprovecha el andamiaje del
helper actual.
