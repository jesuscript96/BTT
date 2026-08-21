# PRD 02 — Calendario y retorno real de la estrategia (frontend)

> **Para:** Edgecute (frontend). **De:** Álvaro. **Fecha:** 2026-08-21.
> **Anclas verificadas sobre:** `develop` @ `e368839`.
> **Tipo:** fix de presentación (sin tocar motor ni API).
> **Prioridad:** alta — el calendario abre mostrando beneficio **bruto** por
> defecto: una estrategia perdedora neta se ve ganadora.
> **Implementación de referencia:** funcionando en mi entorno (parche en
> [`reference/calendario-retorno-real.patch`](reference/calendario-retorno-real.patch)).

---

## 1. El problema (lenguaje de usuario)

Cuatro formas en que la UI **no refleja el retorno real** de la estrategia:

1. **El Calendario abre en "Profits" = PnL BRUTO**: esa vista le devuelve las
   fees al PnL (`val = t.pnl + (t.fees || 0)`). Con los costes reales
   (comisiones + gastos mensuales), una estrategia puede ser perdedora y el
   calendario salir **verde** por defecto.
2. **El PnL% del grid mensual (tab Performance) compone retornos que no son
   de la cuenta completa**: cada `total_return_pct` de `day_results` es un
   retorno **por (ticker, día)** calculado sobre la base COMPLETA del
   portfolio; al componerlos `∏(1+r/100)` con posiciones solapadas el número
   se dispara. Caso real: **YTD +3133%** con un **RETURN real de +27.67%**.
3. **Las métricas en $ usan un capital desincronizado**: el capital por
   defecto 10.000 está hardcodeado y, al lanzar desde builder/estrategia
   guardada, los parámetros tecleados no llegaban (se enviaban los defaults).
   El MAX DD en $ sale en escala equivocada (ej. firma de −4.941/−49.41% con
   capital real 2.500). El drawdown en $ además se convierte con
   `(dd% / 100) × init_cash`, que es incorrecto con compounding: el dd% es
   relativo al **pico de equity del momento**, no al capital inicial.
4. **"Days" cuenta pares (ticker, día)**, no días de calendario: una jornada
   con 5 tickers cuenta 5 días.

## 2. Anclas en `develop` @ `e368839` (verificadas)

- `frontend/src/components/backtester/tabs/CalendarTab.tsx`
  - **:29** — `useState<...>("profits")` (default bruto).
  - **:43-48** — `profits: val = t.pnl + (t.fees || 0)`; `gastos: val = t.fees`;
    `net: val = t.pnl` (el neto ya resta gastos mensuales en el primer día
    hábil de cada mes, :55-68 — eso está bien y se conserva).
  - **:95** — labels `"Profits"` / `"Profits - Gastos"`.
- `frontend/src/components/backtester/tabs/PerformanceTab.tsx`
  - **:97-98** — `mMap.get(m)!.dailyReturns.push(dr.total_return_pct || 0)`
    (apila retornos por ticker-día).
  - **:148** — `val = cell.dailyReturns.reduce((acc, r) => acc * (1 + r / 100), 1) * 100 - 100`.
- `frontend/src/components/backtester/tabs/EquityCurveTab.tsx`
  - **:447** — `val = (p.value / 100) * initCash` (serie de DD en $).
  - **:682** — `` `$${((maxDD / 100) * initCash).toFixed(2)}` `` (header DD $).
- `frontend/src/app/backtester/page.tsx`
  - **:258** — `const initCashRef = useRef(10000)`.
  - **:400** — `const p = panelParamsRef.current` (única fuente al lanzar con
    draft: ignora lo tecleado si el ref no estaba al día).
  - **:464 / :469 / :505** — `p?.init_cash ?? 10000`.
  - **:1453 / :1515** — `initCash={initCashRef.current}` a los tabs.

> Si `develop` avanzó desde `e368839`, re-localizad por expresión.

## 3. Spec (T1–T7, ordenadas por impacto; T1+T2 son el dolor de usuario)

### T1 — Calendario: default "net" + label honesto
- Default del toggle: `"net"` (coincide con RETURN / `total_pnl` del backend).
- Label del modo bruto: `"Profits"` → `"Profits (brutos)"` (deja claro que
  ese modo devuelve las fees).
- Los tres modos se conservan; solo cambia el default y el texto.

### T2 — Performance: PnL% del periodo sobre base de equity real
- Sustituir la composición (:148) por `val = (cell.pnl / cell.baseEquity) * 100`.
- `baseEquity` de cada celda (mes y YTD) = `initCash + Σ pnl` de los trades
  **cerrados antes** del inicio del periodo:
  - Ordenar `trades` por `exit_time` (solo con `exit_time`) una vez.
  - Mes `M` del año `Y`: base al `1º de M,Y`; YTD: base al `1-Y`.
  - Guardar `0` si la base es ≤ 0 (celda muestra `0`, no Infinity).
- Añadir `initCash` a las dependencias del memo.

### T3 — EquityCurve: DD en $ desde el pico de equity (running peak)
- Memo `ddDollarByTime`: recorrer `globalEquity` en orden llevando el
  `peak = max(peak, p.value)`; map `time → p.value − peak`.
- Serie "$": usar `ddDollarByTime.get(p.time)` con **fallback** a la fórmula
  vieja `(p.value / 100) * initCash` si no hay punto.
- Header: `maxDdDollar = min(...ddDollarByTime.values())` (0 si vacío).
- (Mismo patrón que ya aplica el tab OOS en mi rama, commit `5741202`.)

### T4 — page.tsx: los parámetros tecleados llegan al backend
- `handleRunWithDraft(draft, paramsOverride?)` →
  `const p = paramsOverride ?? panelParamsRef.current`; los call sites que
  ya tienen `params` se los pasan.
- `start_date`/`end_date`: `p?.start_date || draft.universe_filters?.date_from`
  (idem end) en vez de ignorar lo del panel.

### T5 — page.tsx: la base sobrevive a la recarga
- Al restaurar de `sessionStorage`: `initCashRef.current = saved.result?.global_equity?.[0]?.value`;
  guardar también `backtestParams` (y restaurar `riskRRef` de
  `backtestParams.risk_r`).
- Al persistir: incluir `backtestParams: backtestParamsRef.current`.

### T6 — page.tsx: fuente única para el capital de la corrida
- `const runInitCash = useMemo(() => result?.global_equity?.length ? result.global_equity[0].value : initCashRef.current, [result])`.
- Pasar `runInitCash` a los tabs que hoy reciben `initCashRef.current`
  (:1453, :1515): el primer punto de `global_equity` SIEMPRE es el
  `init_cash` con el que corrió el backend.

### T7 — "Days" = días de calendario únicos
- `page.tsx` (filtro IS/OOS, también cuando IS=100): `uniqueDays = new Set(trades.map(t => t.date)).size`;
  `avg_r_per_day = Σ r_multiple / uniqueDays`.
- `MetricsCard.tsx`: tooltip de "Days" explicando días únicos.
- `ChartsTab.tsx` (What-If): el "Días totales" del SIM también con días
  únicos (hoy compara pares ticker-día del sim contra el valor corregido).

## 4. Verificación

- `tsc --noEmit` limpio.
- Escenarios manuales (los que usé yo):
  1. Estrategia perdedora neta con fees > 0 → el calendario abre en **rojo**;
     "Profits (brutos)" muestra el bruto.
  2. YTD% del grid ≈ RETURN del header (misma base simple; sin composición).
  3. DD$ de la curva coherente con la escala de la propia curva (p.ej. con
     capital 2.500, sin la firma del −49.41% de base 10.000).
  4. Teclear capital 2.500 y lanzar desde builder / estrategia guardada → el
     backend recibe 2.500 (verificar en el payload de la petición).
  5. Recargar la página con un resultado → la base de la corrida se mantiene
     (no vuelve a 10.000).
  6. "Days" = días únicos con varios tickers el mismo día.

## 5. Definition of Done

- [ ] T1–T7 aplicados; `tsc --noEmit` limpio.
- [ ] Escenarios 1–6 verificados manualmente.
- [ ] Sin cambios de motor, schema ni API (todo en TSX/TS de frontend).
- [ ] Nota de release recomendada: el calendario ahora abre en neto.

## 6. Riesgos

- Solo presentación: ningún número del backend cambia.
- Usuarios acostumbrados al verde bruto percibirán el cambio (es el objetivo,
  pero conviene comunicarlo).
- La T2 cambia un número que alguien podía usar como "referencia": el valor
  nuevo es el correcto (coincide en definición con el RETURN simple del
  header para el YTD).

## 7. Referencia

- [`reference/calendario-retorno-real.patch`](reference/calendario-retorno-real.patch):
  diff completo de los 6 ficheros con la implementación funcionando en mi
  entorno (`CalendarTab`, `PerformanceTab`, `EquityCurveTab`, `ChartsTab`,
  `MetricsCard`, `page.tsx`). **Leedlo, no lo apliquéis con `git apply`**:
  esos ficheros en mi rama llevan features propias y el contexto no coincide
  con `develop`; la spec de arriba es la fuente de verdad.
