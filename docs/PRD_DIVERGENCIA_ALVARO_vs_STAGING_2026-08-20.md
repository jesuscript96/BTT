# PRD / Handoff — Divergencia `alvaro-rama-desarrollo` vs `staging`

> **Para:** Sailor (y cualquiera que integre a `staging`).
> **De:** Álvaro. **Fecha:** 2026-08-20.
> **Objetivo:** que veas **exactamente** qué tiene mi rama que `staging` no tiene,
> **por qué**, y decidas **qué traer y qué no**. Nada aquí toca `main`.
>
> **Cómo leerlo:** la §2 es el resumen con recomendación por bloque (pull / opcional
> / no traer). La §3 detalla cada bloque. La §6 es lo que **NO** está en la rama
> (trabajo local sin commitear) para que no te sorprenda. La §9 son los comandos.

---

## 1. Estado de ramas (hechos, no memoria)

- Mi rama: **`alvaro-rama-desarrollo`** (subida a `origin/alvaro-rama-desarrollo`).
- Respecto a `origin/staging`: **+18 commits / −1 commit**.
  - Tengo 18 que staging no tiene (§2–§3).
  - Me falta **1** de staging: `2378237 feat(robustez): modulo de analisis de
    robustez de estrategias` → lo integraré yo en mi rama; **no** te afecta.
- Base común: el merge `23bd2e1` (ya trae tu `fbf8757` de vía materializada).
- Volumen del diff vs staging: **34 ficheros, +2218 / −168**.

> `main` NO se toca. Yo integro a `staging` solo con orden explícita; este doc es
> para que **tú** decidas si algo de esto te interesa para tu setup.

---

## 2. Resumen ejecutivo — qué aporta mi rama (con recomendación)

| # | Bloque | Tipo | ¿Traer? | Riesgo |
|---|---|---|---|---|
| A | **Fix reparto de locates** | 🐛 bug | **Sí, recomendado** | Bajo — solo shorts con locates |
| B | Parciales fade 1A/1B + toggle MAE/MFE | ✨ feature | Opcional | Medio — toca motor y UI |
| C | Indicador **Current Gap (%)** en entrada | ✨ feature | Opcional | Bajo |
| D | Chart: herramientas de medición + líneas de precio | ✨ feature | Opcional | Bajo (solo FE) |
| E | Export CSV de todos los trades | ✨ feature | Opcional | Bajo (solo FE) |
| F | Qualifying **bygap vía rápida** (perf) | ⚡ perf | Opcional | Bajo — **opt-in, apagado por defecto** |
| G | Fix parciales invisibles en columna EXIT | 🐛 bug | Sí si usas parciales | Bajo |
| H | Fix hidratación rango dataset + arranque local 1-clic | 🐛+DX | Opcional | Bajo |
| I | Logging de errores de `translate_strategy` | 🔧 DX | Opcional | Nulo |

> **Si solo traes una cosa, trae la A** (fix de locates): corrige un cálculo que
> falsea win rate y R por trade en cualquier backtest de shorts con locates.

---

## 3. Detalle por bloque

### A — Fix de reparto de locates 🐛 (commits `2a51b94`, `8896ece`, `de14125`)
**El bug:** el coste de locates de un día se imputaba **entero al primer short**
del día (`break`) y se restaba de **toda** la curva de equity (incluidas barras
premarket sin posición). El **total** era correcto; el **reparto** falseaba R por
trade, win rate y drawdown intradía.

**Evidencia** (misma estrategia, 867 trades idénticos, locate 0 → 3): RETURN
+9876.73% → −71.73% y **WIN RATE 64.1% → 56.2%** — el cambio de win rate con los
mismos trades es la huella del mal reparto.

**El fix** (PRD completo en [`docs/fix-locates-attribution/PRD.md`](fix-locates-attribution/PRD.md)):
- Reparte el `daily_locates_fee` entre **todos** los shorts del día **proporcional
  al `size`** de cada uno; el total no cambia (una sola compra por ticker-día sobre
  `max_short_size_today`). Residuo de redondeo al short mayor → `Σ == fee` exacto.
- La curva de equity solo baja **desde la 1ª entrada corta**, no desde la barra 0.
- Aplicado en **`portfolio_sim.py`** y **`sim_dispatch.py`** (paridad Python↔JIT).
- **`daily_locates_fee` y `size` NO se tocan.** Modelo "una sola compra" confirmado
  (no se cobra por reentrada).

**Tests:** `test_locates.py` + `test_locates_flat_semantics.py` + `test_sim_jit_equivalence.py`
→ **13 passed** (verificado). Sin reentradas, el resultado es idéntico a hoy.

### B — Parciales fade 1A/1B + MAE/MFE ✨ (`e251727`, `d334aff`, `1e18432`, `d6a2fab`, `1249ca1`, `ddba140`)
Parciales de Take Profit con disparador dual (1A = fade desde el máximo previo del
día; 1B autocontenido con línea de respaldo en % desde entrada) y toggle MAE/MFE
medido desde el máximo previo. Toca **motor** (`portfolio_sim*`, `sim_dispatch`,
`strategy_engine`) + **UI** (`RiskManagement`, `Chart`, `ResultsTabs`). Mockup en
`docs/mockup_parciales_fade.html`. **Si lo traes, verifica el JIT (Numba).**

### C — Indicador Current Gap (%) ✨ (`6631056`)
Nuevo indicador en la lógica de **entrada** (no solo filtro de universo). Toca
`schemas/strategy.py`, `services/indicators.py`, `indicatorValidation.ts`,
`ConditionBuilder.tsx`. Test: `test_current_gap_semantics.py` (99 líneas).

### D — Chart: medición + líneas de precio ✨ (`447612c`, `93656e0`)
Herramientas estilo TradingView (regla + línea horizontal) y entrada/salida/parciales
señaladas con líneas al precio exacto. Solo frontend (`Chart.tsx`).

### E — Export CSV de trades ✨ (`3dcd7d0`)
Botón que exporta todos los trades del backtest. `lib/tradesCsv.ts` (nuevo) +
`TradesTab.tsx` + `api_backtester.ts`.

### F — Qualifying bygap vía rápida ⚡ (`9f39a17`)
Lee las 32 columnas de ventana (LAG/LEAD) de un Parquet materializado ordenado por
`pmh_gap_pct DESC` en vez de recalcularlas sobre 19,2 M filas. **Opt-in y apagado
por defecto** (`QUALIFYING_WINDOWED_*` en `.env`, no commiteado). Guardián de
frescura + centinela STRICT. Baseline 14,7 s → **0,18 s** (~80×). Paridad 7/7,
`rtol=1e-9`. Test: `test_bygap_parity.py`. **Cero impacto si no activas el env.**
Detalle en `docs/MEMORIA.md` (entrada del qualifying).

### G — Fix parciales invisibles en EXIT 🐛 (`1249ca1`)
En el reporte, los parciales dejaban la columna EXIT vacía. Corregido.

### H — Fix hidratación + arranque local 1-clic 🐛+DX (`6c37f94`)
Error de hidratación en el rango del dataset + `arrancar_local.bat` / `parar_local.bat`.

### I — Logging translate_strategy 🔧 (`e42d34b`)
Loguea errores de `translate_strategy` en el stream loop (antes se tragaban).

---

## 4. Bugs de P&L DIAGNOSTICADOS pero **NO** arreglados (para que lo sepas)

Hoy diagnostiqué inconsistencias de P&L en el backtester que **no** están
arregladas en esta rama (solo el fix de locates lo está). Están anotadas por si te
las cruzas — **no son de mi rama, son del código base**:
- **PnL % del grid mensual COMPONE los retornos diarios** (`PerformanceTab.tsx:148`)
  mientras el RETURN es `Σpnl/init_cash` simple → YTD absurdo (+3133%) vs RETURN real.
- **Capital por defecto $10.000 hardcodeado** (`BacktestPanel.tsx`, `page.tsx`) que
  se desincroniza del capital real → métricas en $ (MAX DD$/PROFIT$) sobre base
  equivocada.
- **Varios pipelines de P&L en paralelo** (agregado backend / calendario / PnL% /
  recomputo en `page.tsx`) sin fuente única de verdad.

Contexto completo en `docs/MEMORIA.md` (entrada "Diagnóstico inconsistencias de P&L").

---

## 5. Qué difiere de staging (diffstat agrupado)

**Motor / backend:** `portfolio_sim.py` (+213), `portfolio_sim_jit.py` (+82),
`sim_dispatch.py` (+63), `strategy_engine.py` (+71), `backtest_service.py` (+55),
`data_service.py` (±156, del qualifying bygap), `indicators.py` (+11),
`schemas/strategy.py` (+1), `api_public/.../catalog.py` (±2).

**Tests (nuevos):** `test_locates.py` (+97), `test_fade_partials.py` (+228),
`test_current_gap_semantics.py` (+99), `test_bygap_parity.py` (+125).

**Frontend:** `Chart.tsx` (+240), `TradesTab.tsx` (+150), `RiskManagement.tsx`
(+137), `tradesCsv.ts` (+113), `CalendarTab.tsx` (+33), `strategy.ts` (+16),
`api_backtester.ts` (+21), y toques menores en varios builders/tabs.

**Docs / tooling:** `MEMORIA.md`, `CAMBIOS_RECIENTES.md`,
`GUIA_DEV_LOCAL_Y_DEVELOP_PARA_IA.md`, `mockup_parciales_fade.html`,
`arrancar_local.bat`, `parar_local.bat`.

---

## 6. Trabajo LOCAL en curso, **sin commitear** (NO está en la rama, NO pulleable)

Tengo en la working tree cambios grandes que **no** he commiteado, así que **no
salen en el push** y **no puedes traerlos** todavía. Los declaro para transparencia:

1. **Migración GCS → lago LOCAL** (`data_paths.py` nuevo, `database.py`, `db/*`,
   `cache_service.py`, `init_db.py`, `DATA.md`, `docs/PRD_migracion_datos_local.md`,
   `test_no_gcs_references.py`). Es tu terreno (tú ya operas en lago local): cuando
   lo cierre y commitee, hará su propio PRD/handoff. Probablemente lleve rutas
   específicas de mi máquina → **no se comparte tal cual**.
2. **Trailing break-even (`trail_activation`)** — desacopla el umbral de activación
   de la distancia de trailing; `trail_pct == 0` deja el stop fijo en la entrada.
   Toca `portfolio_sim*`, `sim_dispatch`, `strategy_engine`, `RiskManagement.tsx`.
   Feature en curso, aún sin commitear.

> Si en el futuro commiteo estos, saldrán en un handoff nuevo. Por ahora: **no
> existen para ti**.

---

## 7. Lo que a mí me falta de staging

- `2378237 feat(robustez): modulo de analisis de robustez de estrategias` — lo
  integraré en mi rama por mi cuenta. Solo lo apunto para trazabilidad.

---

## 8. Riesgos / notas para Sailor

- **Motor (`portfolio_sim*`, `sim_dispatch`):** cualquier cosa que traigas de aquí
  exige verificar que el **JIT de Numba compila** y que `test_sim_jit_equivalence.py`
  sigue verde (Python↔JIT bit-idénticos).
- **Qualifying bygap (F):** inerte si no pones el env. No cambia producción.
- **Nada de esto depende de mi `.env`** salvo la vía rápida del qualifying (opt-in).
- Los cambios de la migración a lago local **no** están aquí (§6), así que traer mi
  rama **no** te fuerza a mi montaje de datos.

---

## 9. Cómo traerlo (comandos)

Tu repo está en `--single-branch`; primero amplía el fetch a mi rama (operación de
solo lectura):

```bash
git remote set-branches --add origin alvaro-rama-desarrollo
git fetch origin alvaro-rama-desarrollo
```

**Opción 1 — cherry-pick solo el fix de locates (lo recomendado):**
```bash
git cherry-pick 2a51b94 8896ece de14125
```

**Opción 2 — inspeccionar antes de decidir:**
```bash
git log --oneline origin/staging..origin/alvaro-rama-desarrollo
git diff origin/staging...origin/alvaro-rama-desarrollo -- backend/app/services/portfolio_sim.py
```

**Opción 3 — traerlo todo a tu rama** (revisa conflictos en el motor):
```bash
git merge origin/alvaro-rama-desarrollo
```

> Antes de cualquier push a `staging`, confirmación explícita (regla de la casa).
> Este doc no autoriza nada: solo describe para que **tú** decidas.
