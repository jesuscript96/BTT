# MEMORIA — Álvaro × Claude (edgecute_app / BTT)

> Documento vivo. Se actualiza **cada sesión** en la que tocamos algo. Entradas
> por fecha, **lo más nuevo arriba**. Sirve para retomar con contexto: qué
> hicimos, por qué, qué decidimos y dónde lo dejamos.

---

## Estado actual del proyecto

- **Repo:** `edgecute_app` (monorepo BTT, GitHub `jesuscript96/BTT`).
- **Rama de trabajo de Álvaro:** `alvaro-rama-desarrollo` → integra a `staging`.
  Sailor: `sailor-rama-desarrollo`. **`main` NO se toca jamás** (producción con
  clientes de pago). Push solo con confirmación explícita de Álvaro.
- **Entorno local:** `DB_PROVIDER=local`, `DISABLE_GCS_SYNC=true`,
  `LIVE_SCREENER_ENABLED=false` (obligatorias; aíslan de producción).
- **Datos:** `daily_metrics` = **tabla** en `backend/local_data.duckdb` (~61 GB),
  **19.177.136 filas, 2019-01-02 → 2026-08-14**. Lago Parquet aparte en
  `.../TRADING APPs/cangrejo_data/datos/parquet/edgecute/`.
- **Nunca commitear** secretos ni datos: `.env`, `gcs-key.json`, `*.duckdb`,
  `data/`, `.cache/`. Ya en `.gitignore`.

## Reglas de trabajo entre Álvaro y Claude

- **No profundizar de más.** Si algo funciona en local y no aporta, se cierra.
- **No llenar `staging` de mierda.** Lo que funciona en local en
  `alvaro-rama-desarrollo` se queda ahí salvo decisión explícita de subir.
- Sailor también puede subir a `staging`; no somos los únicos.
- Esta memoria se actualiza al final de cada sesión con cambios.

---

## 2026-08-21 (tarde 2) — Rama handoff a producción con PRDs para Edgecute

**Qué hicimos**
- Álvaro pidió rama para entregar al developer de Edgecute (vía develop→main,
  ese salto es de Adrian) las dos mejoras apremiantes: fees por ejecución y
  calendario/retorno real. Creada **`alvaro/handoff-produccion`** (commit
  `7f65d83`) **basada en `origin/develop` @ `e368839`**, por worktree temporal
  (el working tree de esta rama no se tocó). Es un **canal permanente**: sin
  fecha en el nombre; cada tanda de mejoras va en una carpeta fechada dentro.
- **Solo documentación**: `docs/handoff-produccion/` con README índice vivo +
  tanda `2026-08-21-fees-y-calendario/` (PRD_01 fees, PRD_02 calendario,
  `reference/` con parches + `test_fees.py` copiable tal cual).
  Todas las anclas `fichero:línea` verificadas contra develop@e368839.

**Hechos verificados (importan para el futuro)**
- Cherry-pick de `77236d2` (fees) sobre develop **NO aplica limpio**:
  conflictúa en `portfolio_sim.py` (construido sobre trailing+locates+
  parciales fade de mi rama). Con `59a869d`+`77236d2` el trailing sí aplica,
  fees sigue conflictuando. → Handoff por PRD, no por código. `test_fees.py`
  sí es copiable (archivo nuevo, sin dependencias de features mías).
- `origin/alvaro-rama-desarrollo` == local (0 commits sin push): la nota
  "sin push" de las entradas anteriores quedó desactualizada.
- Clasificación del working tree sin commitear: **paquete calendario/retorno
  (6 ficheros: CalendarTab, PerformanceTab, EquityCurveTab, ChartsTab,
  MetricsCard, page.tsx)** = el fix que el usuario quiere en producción;
  `sl_dist_pct_*` (api_backtester, tradesCsv, MetricsCard, backend) y
  `activation_pct` (strategy.ts) = features aparte, fuera del handoff.
  El parche de referencia del calendario se generó de este diff.

**Decisiones**
- Handoff **docs-only**: nada de mi montaje local (bygap, migración GCS/lago,
  MEMORIA/PROXIMOS) puede colarse. README lista explícitamente lo excluido +
  candidatos futuros (fix locates `2a51b94..de14125`, OOS DD$ `5741202`).
- El fix del calendario sigue **sin commitear** en esta rama (trabajo de la
  sesión paralela); el PRD es autocontenido y el parche documenta el
  comportamiento exacto. Pendiente: validarlo (tsc + visual) y commitearlo
  aquí con su propio commit.

**Continuación (misma tarde)**
- Álvaro pidió mensaje + PRD de orientación para Adri (que sepa qué subir a
  main sin liarse). Añadido **`PRD_00_PLAN_DE_SUBIDA_A_MAIN.md`** a la tanda
  (commit `9f7e22c`, en la rama handoff): resumen simple, 2 PRs pedidos,
  orden recomendado (PRD_02 primero), checklist de verificación antes de
  main (incluye smoke de identidad con fees=0), guarda-raíles (no mergear
  mis ramas, no git apply, quirks intactos) y nota de release sugerida.
  README del handoff actualizado con su fila. Mensaje corto para Adri
  entregado en la conversación (no en el repo).

**Continuación 2 (tarde) — PRD_03 trades vs ejecuciones (mea culpa)**
- Álvaro corrigió: el fix apremiante nº 1 NO era el de fees — era el de
  **trades listados como ejecuciones** (1 trade ≥ 2 ejecuciones; con
  parciales 3+). Lo arreglamos ~08-17/20 (¿sesión con otra IA?): commits
  `39a2d80` (función `_group_partial_exits`, backtest_service.py:992, +
  badge calendario), `3dcd7d0` (n_executions/legs en API+CSV+TradesTab),
  `1249ca1` (EXIT), `93656e0` (chart). Yo lo había clasificado como
  "botón export CSV" y no lo vi. Evidencia de esa sesión en el working
  tree: `backend/.audit_replay.py`, `backend/.audit_all_trades.csv`
  (columna `n_executions`).
- **Verificado contra develop**: el motor hace `trades.append` POR
  EJECUCIÓN (parcial :302, cierres :250/357/404/447/569) y NO existe
  agrupación → develop TIENE el bug (total_trades inflado, win rate
  contaminado).
- Añadido **`PRD_03_trades_vs_ejecuciones.md`** a la tanda (commit
  `33713af`, sin push al escribir esto): portar `_group_partial_exits`
  (copiada íntegra a `reference/group_partial_exits.py.txt`) envolviendo
  `_enrich_trades` (:756 único call-site en develop). PRD_00 y README
  actualizados a **3 PRs** (orden: PRD_02 → PRD_03 → PRD_01). Mensaje para
  Adri reescrito con 3 items.

**Continuación 3 (tarde) — Commiteado el trabajo aprobado que estaba vivo en el working tree + CSV fuera del handoff**
- **Queja de Álvaro (procede):** trabajo YA aprobado seguía sin commitear en
  la rama (ni MEMORIA). Commit `588588b` recoge los 9 ficheros frontend del
  working tree (tsc --noEmit limpio), en 3 bloques: (1) fix
  calendario/retorno real — el que va a producción vía handoff PRD_02;
  (2) métricas `sl_dist_pct_*` — feature LOCAL, no va al handoff; su
  cálculo backend sigue sin commitear (mezclado con migración GCS en
  `backtest_service.py`) → sin él las filas muestran 0; (3) tipo
  `activation_pct` — resto del ITEM 1 (`59a869d`) que quedó sin commitear.
- **Regla a partir de ahora:** cuando Álvaro aprueba algo, SE COMMITEA en la
  misma sesión (su rama + entrada MEMORIA). Nada aprobado queda vivo en el
  working tree. Lo no aprobado se declara en MEMORIA como pendiente.
- **Decisión de Álvaro — handoff solo fixes flagrantes, SIN export CSV** (los
  trades viven dentro del backtester, nada se externaliza): PRD_03 amendado
  (`6185254`) quitando el CSV del T4 y dejándolo dicho; README del handoff
  lo explicita. Sigue pendiente: merge a `staging` (requiere orden
  explícita de Álvaro; Sailor comparte esa rama).
- Pendiente de decisión: extraer algún día los hunks `sl_dist` de
  `backtest_service.py` para completar la feature (hoy bloqueado por la
  migración GCS sin commitear).

**Dónde lo dejamos (final de sesión)**
- `alvaro/handoff-produccion`: PRD_03 (`6185254`) **sin push** al escribir
  esto — pusheado a continuación con OK de Álvaro.
- `alvaro-rama-desarrollo`: `588588b` (trabajo aprobado) + commit de esta
  MEMORIA, **sin push** al escribir esto — pusheados a continuación.
- Working tree: queda SOLO el WIP no aprobado (migración GCS backend +
  renames staged + analisis/ + untracked varios).

---

## 2026-08-21 (noche 5) — RETRACTACIÓN: el "bug de clic" del picker de robustez NO existe

**Qué pasó**
- La entrada "noche 2" reportaba un bug de selección por clic (off-by-one) en
  el picker de estrategias del módulo de robustez, y el mensaje para Sailor
  lo incluía. **Era falso**: fue un artefacto de mi automatización.
- Sesión de diagnóstico exhaustiva: repro "limpia" en pestaña nueva seguía
  fallando, PERO los resultados eran incoherentes entre sí (a veces 1 arriba,
  a veces 2, a veces "teleporta" a la primera tarjeta, a veces clic muerto) —
  ningún patrón compatible con un bug real de la página. El Enter (sin
  coordenadas) SIEMPRE selecciona correcto. El código React revisado línea a
  línea es correcto (`onSelect(s.id)` directo, keys estables, sin CSS
          solapado/absolute/transform). Y el propio Álvaro confirma que con su
  ratón real funciona bien.
- **Causa del artefacto:** el pipeline de input del navegador integrado que
  uso para probar despacha los clics con desfase/contaminación (además la
  pestaña estaba visible en la pantalla de Álvaro → clics suyos simultáneos
  posibles en algunos tests).

**Correcciones**
- El mensaje para Sailor: quitar la sección del bug (versión corregida
  entregada en la conversación). **No hay nada que arreglar en robustez.**
- Lección para futuras sesiones (regla): los clics automatizados del
  navegador integrado NO son evidencia válida de bugs de UI en este repo;
  usar teclado (`press("Enter")`) para probar selección, o pedir a Álvaro
  que clique él. Verificar siempre con el código antes de reportar.

---

## 2026-08-21 (noche 4) — Cierre: staging mergeado + robustez listo para usar en local

**Subido todo (con OK de Álvaro)**
- Pushes: `alvaro-rama-desarrollo` → `e2e084d` y `alvaro/handoff-produccion`
  → `e850d56` (F4).
- **Merge rama→`staging`**: fast-forward limpio `d423046..e2e084d` (47
  ficheros, +3.696/−291) y pusheado. Sailor ya tiene TODO el inventario
  priorizado; su mensajito de handoff está en la conversación (incluye el
  reporte del bug de clic del picker).

**Robustez listo en local (para que Álvaro lo use ya)**
- `backend/.env`: `ROBUSTNESS_ENABLED=true` (gitignored).
- `frontend/.env.local`: `NEXT_PUBLIC_ROBUSTNESS_ENABLED=true` (gitignored,
  añadido sin tocar lo existente) → link "Robustez" visible en el sidebar
  (verificado en navegador).
- Servidores arrancados con `arrancar_local.bat` (ventanas propias); el
  backend responde los 11 endpoints de robustez con las estrategias reales.
- Recordatorio del bug: clic de ratón en el picker selecciona la estrategia
  de ARRIBA (usar teclado o clic en la de abajo mientras Sailor lo arregla).

---

## 2026-08-21 (noche 3) — Revisión externa del handoff+sync: 4 correcciones aplicadas (F1–F4)

**Contexto**
- La IA arquitecta de Álvaro revisó el trabajo contra el repo real: confirma
  handoff docs-only (9 ficheros, +1.740, 100% en docs/handoff-produccion/),
  anclas de los 4 PRDs exactas contra `origin/develop@e368839`,
  independencia de los 3 PRDs verificada (interacción fees↔agrupación
  segura en cualquier orden) y reference copiable. 4 correcciones, ninguna
  bloqueante — **todas aplicadas**.

**F1 (🔴) — Baseline de tests backend (la importante de cara a main)**
- Suite completa: `pytest tests/ -q --continue-on-collection-errors` →
  **108 failed / 337 passed / 15 errors** (2:39). Requiere el flag: 2
  módulos con imports muertos abortan la recolección (Backlog #4).
- Baseline registrada en **`docs/BASELINE_TESTS_BACKEND.md`** (123 rojos,
  agrupados y categorizados: entorno/datos vs Backlog #3/#4 vs conocidos).
- **Regla:** antes de cualquier salto `staging→develop→main`, correr la
  suite y comparar contra esa lista: rojo NUEVO = regresión → parar.

**F2 (🟡) — develop local desfasado**
- El branch local `develop` estaba en `d4065b9` (por detrás de
  `origin/develop@e368839`) → `git branch -f develop origin/develop`.
- **Regla:** las anclas de los PRDs se verifican SIEMPRE contra
  `origin/develop`, nunca contra el branch local.

**F3 (🟡) — 588588b mal etiquetado**
- El inventario lo listaba como 🔴 puro; es **MIXTO** (calendario→prod +
  sl_dist local + activation_pct). Corregido arriba en el inventario.

**F4 (🟡) — PRD_03 sobrevendía portabilidad**
- `_group_partial_exits` tiene 8 subíndices duros (`pnl`, `size`,
  `entry_price`, `exit_idx`, `exit_time`, `exit_time_epoch`, `exit_price`,
  `exit_reason`) → KeyError si develop los toca, no None silencioso.
  PRD_03 §3-T1 corregido (commit `e850d56` en la rama handoff, sin push
  al escribir esto).

**Dónde lo dejamos**
- Pendiente push: `alvaro/handoff-produccion` (`e850d56`) y esta rama.
  El merge rama→`staging` sigue esperando OK de Álvaro (la revisión no lo
  bloquea).

---

## 2026-08-21 (noche 2) — Prueba runtime del módulo de robustez: FUNCIONA, con 1 bug de selección

**Montaje**
- El backend que corría era **pre-merge** (sin endpoints de robustez):
  reiniciado con el código del merge (puerto 8010, queda corriendo en
  background de esta sesión). Frontend ya corría (Next dev recompila solo).
- `ROBUSTNESS_ENABLED=true` añadido a `backend/.env` (local, gitignored; el
  módulo viene apagado por defecto — regla R7). El link del sidebar sigue
  oculto sin `NEXT_PUBLIC_ROBUSTNESS_ENABLED`, pero `/robustez` entra por
  URL directa.

**Verificado ✓**
- Página carga; lista las 4 estrategias reales con sus métricas; auto-análisis
  de la primera al abrir (drawdown, rachas, 5 peores hundimientos, ulcer).
- 11 endpoints del router responden 200; el análisis recalcula al cambiar de
  estrategia; `tsc` limpio (ya verificado en el merge).

**🐛 Bug encontrado (presente en staging; reportado a Sailor)**
- **Clic con ratón en la tarjeta N selecciona la estrategia N−1**: clic en
  "Definitiva 2.3" (4ª) → cargó "Sailor RTH 1" (3ª); clic en "RTH 2" (2ª) →
  cargó "Investigar contextos AH" (1ª). Patrón consistente (verificado en el
  log del backend: los `/run` pedidos no coinciden con la tarjeta clicada).
- **Con teclado (Enter) selecciona la CORRECTA** → el código React está bien
  (`StrategyPicker.tsx` pasa `s.id` directo; `page.tsx:72` también): es un
  problema de **área de clic / hit-testing solapado** entre tarjetas
  (probablemente CSS del header clicable). Un usuario real con ratón lo
  sufrirá igual.

**Dónde lo dejamos**
- Backend corriendo con código del merge + robustez activo (local).
- Merge rama → `staging` sigue **pendiente de OK** de Álvaro.

---

## 2026-08-21 (noche) — Sync con staging (opción A): merge limpio + inventario priorizado para subir

**Qué hicimos**
- Revisión de divergencia con `origin/staging`: ellos +6 / nosotros +28.
- **Merge `38298f1`** (origin/staging → alvaro-rama-desarrollo), **0 conflictos**.
  Truco necesario: los renames STAGED del WIP (backend/scripts → _archive)
  bloqueaban el merge por estado de índice; se des-stagearon, se mergeó y se
  re-stagearon idénticos (12 entradas A/R intactas, disco sin tocar).
- **Nos trae** (33 ficheros, +10.280 líneas): módulo de **robustez** de
  Sailor completo (useLocates/useMonteCarlo/useWfo + api_robustez + analytics,
  30 ficheros nuevos), su aplicación del fix de locates, copia del PRD y
  carpeta `ALVARO_CAMBIOS/` (MEMORIA+PROXIMOS para el equipo).

**Verificado**
- Fix de locates de Sailor = **idéntico al nuestro**: el merge dejó nuestros
  `portfolio_sim.py`/`sim_dispatch.py`/`test_locates.py`/PRD.md byte a byte
  iguales (diff vacío). Nada que reemplazar.
- `test_locates.py` + `test_sim_jit_equivalence.py`: **12/12 verde**.
- `tsc --noEmit`: **limpio** con el módulo de robustez incluido.

**Inventario priorizado de NUESTROS commits para staging (28, decisión de
Álvaro: subir TODOS, con esta prioridad)**

🔴 **Urgente — bug** (van también a main vía handoff):
- `77236d2` fees por ejecución (fill) · `588588b` **MIXTO**: calendario/retorno
  real (→prod vía PRD_02) + métricas `sl_dist_pct_*` (local, NO handoff) +
  tipo `activation_pct` (resto ITEM 1) · `5741202` OOS MAX DD $ ·
  `2a51b94+8896ece+de14125` locates (ya en staging
  por Sailor, duplicado idéntico) · `1249ca1` EXIT parciales invisibles ·
  `6c37f94` hidratación rango dataset · `e42d34b` logging translate_strategy

🟡 **Feature validada** (Sailor decide si las toma):
- `59a869d` trailing break-even (activation_pct) + tests · parciales fade
  1A/1B (`ddba140`,`e251727`,`d334aff`,`1e18432`,`d6a2fab`) · `6631056`
  Current Gap (%) · `447612c` regla/línea chart · `93656e0` ejecuciones
  señaladas al precio · `3dcd7d0` export CSV (interno; NO va a main)

🟢 **Infra/DX**:
- `9f39a17` bygap vía rápida (env-gated, inerte sin `.env`) · arranque 1-clic
  (dentro de `6c37f94`)

📄 **Docs** (nuestro kanban real para el equipo, complementa ALVARO_CAMBIOS):
- `f8a7bd7`, `c779560`, `75f4bee`, `2e431ac`, `478ce55`, `8176d83`,
  `1a04176` + este · `23bd2e1` merge previo (histórico)

**Pendiente**
- Push de `alvaro-rama-desarrollo` (merge + docs) → hecho tras este commit.
- **Merge de nuestra rama → `staging`**: pendiente OK explícito de Álvaro.
  Se haría por worktree (el working tree principal está sucio con el WIP
  GCS). Con eso Sailor recibe TODO el inventario de arriba.

---

## 2026-08-21 — Ejecutados ITEM 3 e ITEM 1 (PROXIMOS_ITEMS); spec ITEM 2 corregida

**Contexto**
- Auditoría del backtester del 2026-08-21 → `docs/PROXIMOS_ITEMS.md` con 3 items.
- Revisión Claude (Opus) con notas 🔎 A/B/C sobre la spec de ITEM 2. Esta sesión:
  verificar esas notas contra el código, ejecutar ITEM 3 e ITEM 1 (aprobados por
  Álvaro, en ese orden), corregir la spec de ITEM 2. **ITEM 2 NO ejecutado.**

**Verificación de las notas A/B/C (todas correctas)**
- **A**: `BacktestPanel.tsx:688` ya divide `fees/100` antes de enviar → al motor
  llega como fracción; el `/100` de la fórmula PERCENT de la spec habría cobrado
  100× de menos.
- **B**: parciales sin clave `fees` a propósito (`sim_dispatch.py:348-351`,
  comentario "quirk contractual"); el total (`backtest_service.py:1033`) los
  excluye. Tocarlo rompería `test_sim_jit_equivalence`.
- **C**: label actual es `Fees ($)` (`BacktestPanel.tsx:1384`); con el cambio
  $/trade → $/share el relabel es obligatorio.
- Anclas de ITEM 1 (7/7) e ITEM 3 verificadas. Ningún test referenciaba
  `trail_activation` (hueco real de cobertura).

**ITEM 3 — MAX DD $ del tab OOS (commit `5741202`)**
- `OOSDegradationTab.tsx`: la serie (`:371`) y el header (`:556`) convertían
  `dd$ = (dd%/100) × initCash`, que subestima el DD cuando el pico supera el
  capital inicial. Arreglado copiando el patrón de `EquityCurveTab.tsx:177-193`:
  memo `ddDollarByTime` (value − running peak sobre `fullGlobalEquity`) para
  serie y header, con fallback a la fórmula vieja si no hay punto. Solo
  presentación; `tsc --noEmit` limpio.

**ITEM 1 — Trailing Break-Even desacoplado (commit `59a869d`)**
- La feature vivía sin commitear en la working tree. Validada contra cálculo
  manual, testeada, documentada y commiteada (solo sus 9 ficheros):
  `strategy_engine.py` (parsing ×2 paths), `portfolio_sim.py`, `portfolio_sim_jit.py`
  (puerto línea a línea, mismo orden FP), `sim_dispatch.py`, `schemas/strategy.py`
  (`activation_pct: None` explícito en el default), `RiskManagement.tsx`,
  `BACKTESTER_BRAIN.md` §4 + checklist.
- Tests nuevos: `backend/tests/test_trail_break_even.py` (T1 BE long, T2
  no-activación → SL, T3 activación+distancia, T4 espejo short, T5 regresión
  bit-identica del trailing clásico via `trail_activation=None` vs
  `=trail_pct`) y `test_sim_jit_equivalence.py::test_trail_activation_equivalence`
  (T6 paridad JIT con BE y mixto). **19/19 verdes** (suite ITEM 1 + fade
  partials). Numba 0.66.0 real, kernel cacheado.
- Nota semántica: `buffer_pct=0` antes era falsy → trailing inerte; ahora
  admite 0.0 → "BE inmediato" (caso documentado en BRAIN §4).

**ITEM 2 — Fix fees: spec corregida, PENDIENTE de orden**
- `docs/PROXIMOS_ITEMS.md` §ITEM 2 reescrito con A/B/C aplicadas: fórmula
  PERCENT sin `/100` (fees llega como fracción), tabla de fórmulas por bloque
  (el fee de ENTRADA cae en el cierre final: `original_size`; parciales solo su
  salida), decisión explícita de **mantener el quirk** de parciales sin `fees`,
  y relabel "$/share" marcado obligatorio.
- **Esperando visto bueno de Álvaro a la spec antes de tocar el motor.**

**Dónde lo dejamos**
- Commits en `alvaro-rama-desarrollo`, **sin push** (pendiente confirmación).
- Working tree: siguen los cambios WIP de Álvaro (migración GCS, renames
  `backend/scripts → backend/_archive/scripts_gcs_2026-08` staged, etc.).
- `test_strategy_api.py::test_create_and_get_strategy` falla 422 de forma
  **preexistente** (verificado con stash, sin relación con estos cambios). No
  estaba en la lista de tests rotos conocidos del Backlog.

---

## 2026-08-21 (tarde) — Ejecutado ITEM 2: fees por ejecución (fill)

**Qué hicimos**
- Álvaro dio el visto bueno a la spec corregida (A/B/C) y ordenó ejecutar.
- Nuevo modelo de comisiones **por fill** en `portfolio_sim.py` (helper
  `_fee_amount`, 6 puntos) y kernel JIT (`_fee_amount_jit`, puerto con mismo
  orden FP): FLAT = $/acción y lado (`fees × qty`); PERCENT = fracción del
  nocional (`notional × fees`, SIN `/100`: el frontend ya divide). El cierre
  final paga la entrada de TODO el tamaño (`original_size`) + la salida del
  restante; cada parcial paga solo su salida. Quirk B intacto: parciales sin
  clave `fees`, totales sin su fee, locates intactos.
- UI: labels `Fees (% notional)` / `Fees ($/share)` en `BacktestPanel.tsx`
  (relabel obligatorio por el cambio de significado de FLAT). BRAIN §5
  actualizado con el modelo por-fill.

**Verificación**
- `backend/tests/test_fees.py` nuevo (6 tests): FLAT/PERCENT full, trade plano
  paga fee (mata el bug `abs(pnl)`), parciales FLAT/PERCENT + quirk sin
  `fees`, paridad JIT. Escrito primero y visto en rojo (5 fallos con el motor
  viejo), verde tras el cambio.
- Paridad: `test_sim_jit_equivalence.py` (grid 220 configs con fees 0.01/2.5
  ambos tipos) + fade partials + trail + locates: **28/28**.
- Suite completa con diff contra stash: **0 fallos nuevos**; los ~119 fallos
  preexistentes son de entorno/datos (GCS 403, bygap Parquet local, DB).
- Humo (34 trades, 1.416 acciones, random walk sembrado): FLAT $0.01/share →
  fee total $28.32 = exacto a $0.02 × 1.416; PERCENT 0.01% → $13.59 ≈
  0.0002 × nocional; paridad JIT exacta en los 3 escenarios.

**Impacto (avisado en spec y commit)**
- PERCENT: cambia la fórmula, no la magnitud con el default 0.01%.
- FLAT: cambio de SIGNIFICADO ($/trade → $/share) — backtests guardados con
  FLAT>0 dan números muy distintos; el relabel de UI lo hace explícito.

**Dónde lo dejamos**
- Commits del día: `5741202` (ITEM 3), `59a869d` (ITEM 1), `75f4bee` (docs),
  + commit de ITEM 2 (fees). Todo en `alvaro-rama-desarrollo`, **sin push**.
- `PROXIMOS_ITEMS.md` queda solo con el Backlog congelado: los 3 items de la
  auditoría están ejecutados y registrados aquí.

---

## 2026-08-20 (tarde) — Diagnóstico inconsistencias de P&L + PRD fix de locates

**Qué hicimos**
- Diagnóstico de por qué los números del backtester **no cuadran entre paneles**
  (Álvaro veía cifras contradictorias en varias estrategias). Solo diagnóstico +
  un PRD: **no se tocó código esta sesión**.
- Revisión concreta del **cálculo de locates** (sospecha de Álvaro).

**Hallazgos (anclados en código)**
- **PnL% del grid mensual COMPONE los retornos diarios** (`PerformanceTab.tsx:148`,
  `∏(1+r/100)−1`) mientras el RETURN del backend es simple `Σpnl/init_cash`
  (`backtest_service.py:1336`). Por eso YTD salía +3133% con RETURN +27.67%. Bug real.
- **Capital por defecto $10.000 hardcodeado** en 4 sitios (`BacktestPanel.tsx:417`,
  `page.tsx:259/465/470/506`). Las métricas en $ del header de la curva usan
  `initCashRef.current` (`EquityCurveTab.tsx:663/682`), que se desincroniza del
  `init_cash` real → firma del $10k en `MAX DD` (−4941/−49.41%) con capital 2.500.
- **3–4 pipelines de P&L en paralelo sin fuente única**: backend agregado
  (`Σpnl/init_cash`), curva backend (`init_cash+cumsum`), calendario (suma cruda
  de `t.pnl`, `CalendarTab.tsx:68-75`), PnL% compuesto, y `page.tsx:1087` recalcula
  el return por su cuenta. Cada uno da un número distinto.
- **Calendario "verde pero plano"**: en modo neto no resta los `$150/mes` (solo en
  modo "gastos", `CalendarTab.tsx:87-89`); el neto real es `total_pnl−total_expenses`
  (`backtest_service.py:1327`).
- **Locates — el total es correcto, el reparto está mal**:
  - Todo el locate del día se imputa al **primer short** (`break`) en
    `portfolio_sim.py:878-882` y **duplicado verbatim** en `sim_dispatch.py:372-395`
    (path JIT). → falsea R por trade y win rate.
  - Se resta de **toda la curva de equity** desde la barra 0 (`equity[i]` para todo
    `i`), incluidas barras premarket sin posición → infla el DD intradía.
  - Evidencia (misma "Definitiva 2.3", 867 trades): locate 0 → 3 pasa RETURN de
    **+9876.73% a −71.73%** y **WIN RATE de 64.1% a 56.2%** (huella del mal reparto).

**Decisiones**
- Modelo de locate **"una sola compra por ticker-día"** confirmado por Álvaro:
  **no** se cobra por reentrada (el `max_short_size_today` + una imputación es
  correcto y se preserva).
- **Reparto FIJADO: proporcional al `size` de cada short**, preservando el total
  exacto (elimina la distorsión de win rate con reentradas).

**Entregable**
- **`docs/fix-locates-attribution/PRD.md`** — PRD ejecutable condensado (formato
  casa, anclado a `fichero:línea`, plan atómico T1–T5, DoD, ejemplo numérico).
  **Pensado para que lo ejecute GLM** en `alvaro-rama-desarrollo`. El fix va en los
  **dos** paths (`portfolio_sim.py` + `sim_dispatch.py`) y debe dejar verde
  `test_locates.py`, `test_locates_flat_semantics.py` y `test_sim_jit_equivalence.py`.

**Abierto (deferred)**
1. **El bug PnL%/initCash NO tiene PRD todavía** — solo diagnóstico. Decidir si se
   unifica todo a una sola curva de equity (fuente única de verdad) y quién lo hace.
2. **Trabajo en paralelo sobre los MISMOS ficheros**: `PerformanceTab.tsx`,
   `EquityCurveTab.tsx`, `page.tsx`, `CalendarTab.tsx` se editaron a las 19:54–19:57
   (otro agente/sesión). Cuidado con pisar al tocar el fix del P&L.

---

## 2026-08-20 — Vía rápida de qualifying (bygap ordenado por gap)

**Qué hicimos**
- Adoptada la optimización de Sailor: leer las 32 columnas de ventana (LAG/LEAD)
  del qualifying de un Parquet materializado y **ordenado por `pmh_gap_pct DESC`**,
  en vez de recalcularlas sobre 19,2 M filas en cada backtest.
- Revalidado que `edgecute_app` = mismo montaje que Sailor (fuente **DuckDB**,
  `main.daily_metrics`), no la vía Parquet (eso fue un despiste del repo `edgecute_lab`,
  que era una prueba desechable y **se borró**).
- Generado el bygap con `opt_por_gap.py` desde `main.daily_metrics` (misma fuente
  que la app → paridad por construcción): **3,51 GB, 173 s**, 19.177.136 filas.
- Implementado + **merge de `origin/staging`** (trae `fbf8757` de Sailor) resuelto
  en **`23bd2e1`**: estructura de Sailor (`_remap_trading_day` extraída, `return`
  temprano, TTL por `QUALIFYING_CACHE_TTL`) + **guardián de frescura** (footer
  `parquet_metadata` + memo, CAST en SQL) + **`QUALIFYING_WINDOWED_STRICT`** con
  centinela `_BygapStaleStrictError` + **remap unificado** (vía lenta llama a la
  función, sin inline duplicado).

**Resultado medido**
- Baseline (vía lenta): 14,7 s (2020→hoy), 17,0 s (2022-2023).
- Vía rápida: **0,18 s** (~80-90×). Guardián: 0,25 s fresco; desfasado → degrada
  con resultados idénticos; desfasado + STRICT → error propagado (no cae al hot-cache).
- **Paridad 7/7, 0 diferencias, `rtol=1e-9`** sin aflojar, incluidos `gap_1_day`,
  `gap_2_day` y borde derecho. `py_compile` OK.

**Decisiones**
- **NO push a `staging`.** `fbf8757` ya está en `staging` (lo subió Sailor); nuestros
  extras (guardián, STRICT, test) se quedan en `alvaro-rama-desarrollo`. Env-gated y
  **apagado por defecto** → cero impacto en producción / resto del equipo.
- No perseguir convergencia total de código con Sailor. Él mantiene su versión.

**Config local añadida a `backend/.env`** (ignorado por git)
- `QUALIFYING_WINDOWED_PARQUET=.../cold_storage/daily_metrics_bygap/*.parquet` (glob, no fichero)
- `QUALIFYING_WINDOWED_STRICT` (default false), `QUALIFYING_CACHE_TTL=604800`,
  `MIN_AVAILABLE_DATE=2019-01-01`, `DUCKDB_MEMORY_LIMIT=3GB`,
  `INTRADAY_PREWARM_ENABLED=false`, `BACKTEST_MIN_AVAIL_GB=1.0`.

**Dónde lo dejamos**
- `23bd2e1` commiteado en `alvaro-rama-desarrollo`, **sin push**. Funciona en local.
  **Tema cerrado.**

**Abierto (deferred — no bloquea, no actuar salvo decisión)**
1. **Dos copias inline más del remap** sin unificar: hot-cache (~1060) y fallback
   GCS (~1131). Si se unifican algún día, acordar con Sailor al subir a `staging`.
2. **`except` ancho del branch local** (`data_service.py` ~975): cualquier excepción
   de la vía local cae al hot-cache, que filtra por `gap_pct` (no `pmh_gap_pct`) →
   "no falla, contesta otra cosa" (por eso 53 vs 65 filas). El centinela cubre STRICT;
   el caso general (`has_custom_rules`) queda como posible follow-up con dueño.
3. **Concurrencia** del `read_parquet` sobre el bygap (varios backtests a la vez)
   no probada. Irrelevante en local de 1 usuario.
4. Script de Sailor `opt_qualifying_incremental.py` tiene bug de orden (borra los
   parquet antes de renombrar el compactado). No lo usamos aún; si se adopta,
   renombrar primero y borrar después.
5. **Inyección SQL preexistente** en `_build_where_clause` (interpola filtros de
   usuario sin parametrizar). No la introduce este cambio; deuda aparte.

**Ficheros de referencia (Downloads)**
- PRDs de Sailor: `PRD_CONSTRUCCION_Y_OPTIMIZACION.md`, `PRD_RESPUESTAS_QUALIFYING.md`,
  `PRD_COORDINACION_QUALIFYING.md`, `PRD_REVISION_RECONCILIACION.md`.
- Nuestros: `PRD_ADOPCION_QUALIFYING_BYGAP_ALVARO.md`, `RECONCILIACION_QUALIFYING_STAGING.md`,
  `opt_por_gap.py`.
- En el repo: `backend/tests/test_bygap_parity.py`.
