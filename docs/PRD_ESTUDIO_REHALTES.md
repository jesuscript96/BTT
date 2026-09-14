# PRD — Estudio «Rehalt tras halt»: la vela de reapertura como señal de cadena

> **Para:** la IA que ejecute este estudio (probablemente una conversación nueva).
> **Pidió:** Álvaro (2026-09-14). Plan redactado por ZCode y aceptado por Álvaro.
> **Estado:** ⏸️ BLOQUEADO esperando datos de Jaime (ver §0). Todo lo demás está listo.

---

## La pregunta de negocio

Álvaro quiere **aumentar la probabilidad de saber si una acción va a rehaltear**
antes de entrar tras un halt, para no entrar en una lotería. Concretamente:

> «Necesito una regla en la cual, en un X % alto de los casos, el % de
> movimiento de la siguiente o siguientes velas de M1 propicie un siguiente
> halt seguido.»

Es decir: condicionado a que un ticker ya tuvo un halt, ¿qué dicen la primera
(o primeras) velas M1 tras la reapertura sobre la probabilidad de otro halt
encadenado? La entrega es una **regla operativa legible**, no un modelo.

**Nadie ha estudiado esto todavía.** El informe v7 de Jaime (predictores del
fogonazo) predice el PRIMER fogonazo a nivel día/instante; la pregunta aquí es
la CADENA (halt k+1 dado halt k). Las cadenas existen y son graves: GGAA llegó
a 16 LULD en un día, GATE 5; GATE acabó en T12 36 min después de que una
posición de 2B saliera por hora (`docs/MEMORIA_BOT_EJECUCION.md`, 11-sep noche 3).

## 0. Datos — QUÉ FALTA Y DÓNDE SE BUSCÓ (14-sep-2026)

**Falta el parquet de halts de Jaime** (`halts_mercado_2019_2026.parquet`,
277.645 halts, ~21k símbolos, 2019–2026; esquema por fila: symbol, date,
halt_ts, resume_ts, reason, motivo, minutos). Jaime dijo que lo subiría
commiteado; **a fecha 14-sep aún no está**. Buscado sin éxito en:

- git (`origin/staging`, `origin/sailor-rama-desarrollo`, `jaumen`): sin commits
  nuevos tras `3b60650` y sin parquet/CSV de halts en el árbol.
- Disco local: Downloads (también `Telegram Desktop/`), Desktop, repo, lago
  `cangrejo_data` y sus carpetas hermanas (`_lago_prueba, day_aggs, edgecute,
  minute_aggs, trades_premarket`). Nada.
- El lago local de Álvaro (`LOCAL_DATA_ROOT` en `backend/.env`) NO tiene carpeta
  `halts/`. El `HALTS_DIR` de `backend/app/services/halts.py` apunta por defecto
  a `D:/lago_backtester/...` (ruta de la máquina de Jaime, inexistente aquí).

**Primer paso de la sesión nueva:** `git fetch` y re-buscar (git + disco). Si
aparece por otra vía (Telegram, GCS…), basta con dejarlo accesible y anotar la
ruta aquí. Mientras tanto NO se puede ejecutar nada de las fases 1–5.

**Qué sí hay ya:**
- Velas M1 del lago GCS 2019+ (acceso igual que el backtester; `intraday_1m`).
- `backend/app/services/halts.py` (recién mergeado): define el formato del
  parquet por día y cómo se traduce a índices de vela. El estudio NO necesita
  el motor de backtest — es análisis de datos sobre el lago, en solo lectura.
- **PDFs de prior art EN ESTA MÁQUINA**: `C:\Users\Alvaro\Downloads\Telegram
  Desktop\BSwans y Halts.pdf` y `BSwans y Halts (2).pdf` (informes de Jaime).
  **LEERLOS ANTES DE EMPEZAR** (tarea añadida a Fase 0 por decisión de Álvaro).

## 1. Fase 0 — Terreno y prior art

1. **Leer los dos PDFs** de arriba + las secciones de halts de
   `docs/MEMORIA_BOT_EJECUCION.md` (informes v6–v8: `15_halts_profundo`,
   predictores `26_*`/`27_*`, T12/T1 reales). Extraer cualquier número de
   cadenas que ya esté medido para no duplicar.
2. Localizar/verificar el parquet de halts; validar esquema y rangos de fecha.
3. **Heredar las trampas ya documentadas (v7/v8), aplicarlas desde el minuto 1:**
   - T1/T12 de las 19:50/19:55 = contrasplits y bajas por fusión, no halts
     operativos → excluir.
   - `px_antes ≥ 0,5` y coherencia con `prev_close` (símbolos reutilizados:
     SMR, GOLD ×70 generaban reaperturas falsas).
   - Muchos «T12» tardíos son corporativos. Lo regulatorio real: filtro
     CS/ADRC con la tabla `tickers` del lago (regla de Jaume, v8).
   - Separar LULD de T1/T12 SIEMPRE; este estudio es de LULD (la cadena), con
     T12 como evento terminal a anotar, no a predecir aquí.

## 2. Fase 1 — Cohorte y etiquetas

- **Unidad**: halt k-ésimo de un ticker-día (LULD, en sesión; PM aparte).
- **Etiqueta** `rehalt`: existe halt k+1 del mismo ticker-día dentro de H
  minutos tras la reapertura, con H ∈ {5, 15, 30, EOD}. Medir también
  «algún halt más hoy».
- **Tasas base PRIMERO**: P(2º|1º), P(3º|2º)… por año, por PM/RTH, y por
  DIRECCIÓN del halt (up vs down). Para un corto la cadena de halt-ups es la
  lotería; se mide asimétrica desde el principio. Sin tasa base no hay «X %
  alto» que valga.

## 3. Fase 2 — Features en el instante de decisión (sin look-ahead)

El instante de decisión es el **cierre de la vela k tras la reapertura**
(k = 1, 2, 3, y acumuladas 1–3). Solo se usa información conocida hasta ahí:

- **Velas post-reapertura**: rango % ((H−L)/precio de reapertura), cuerpo %,
  cierre cerca del extremo, volumen vs media previa del día.
- **Headroom a la banda LULD reconstruida** (la feature causal): la banda es
  determinista — ref = media de trades de los últimos 5 min (refresco cada
  30 s), tramo por precio: entre $1,00 y $3,00 → el menor entre 10 % y $0,30
  (tramos distintos: <$1, ≥$3, ETP, IPO, y bandas más anchas fuera de RTH).
  El rehalt ES volver a cruzar la banda; «(banda − precio)/precio en el cierre
  de la vela 1» es el predictor mecánico, el % de vela es su proxy. Calcular
  las dos. Error asumido ±1 céntimo por la ref oficial de la SIP (documentado).
- **Contexto del halt**: duración, nº de halts previos hoy, salto en la
  reapertura, ATR 14 M1 previo, y delgadez (features v7: <14k acciones
  acumuladas, <107 operaciones, vol medio 20d <88k, primera media hora).

## 4. Fase 3 — Estadística y umbral

- Curvas **P(rehalt | vela 1 ≥ X %)** y **P(rehalt | headroom ≤ X %)** por
  deciles, con IC de Wilson y lift sobre la tasa base.
- Umbral elegido para precisión alta con n decente. Criterio PROPUESTO (Álvaro
  lo ratifica o cambia al ver números): **P ≥ 70 % con n ≥ 30 casos**,
  reportando recall. Definirlo ANTES de mirar el OOS.
- Logístico/árbol simple solo como techo de comparación. La entrega es una
  regla legible.

## 5. Fase 4 — Validación y robustez

- **IS 2019–2024 / OOS 2025–2026** (la propia v7 se marcó a sí misma «sin
  validación fuera de muestra»; esta vez no se repite el fallo).
- Estabilidad por año; PM vs RTH; halt-up vs halt-down.
- **Re-test SIN los 5 días SPAC famosos** (GATE, GGAA, ASPA, NOVV, HYZN):
  si la regla solo caza esos, es una anécdota.

## 6. Fase 5 — Entrega

- Crib sheet «entro / no entro / espero» + tabla de contingencia.
- Entrada del estudio al final de `docs/MEMORIA_MADRE.md` (formato habitual).
- Scripts efímeros en scratchpad del estilo `.tmp_rehalt/` (NADA al repo).
- Si la regla sale buena: candidata a (a) feature/guard del backtester en la
  rama de Álvaro y (b) regla R-C del bot de ejecución — desarrollo aparte con
  su propio PRD, no parte de este estudio.

## 7. Reglas operativas para la IA que lo ejecute

- Rama `alvaro-rama-desarrollo`; jamás `main`; push solo con confirmación
  explícita de Álvaro. Backend local: debe loguear `DISABLE_GCS_SYNC=true`.
- El backend puede seguir corriendo durante el estudio (lecturas parquet
  directas); NO abrir `local_data.duckdb` con otro proceso (contención DuckDB).
- Lago en SOLO LECTURA. El parquet de halts es dato de Databento (licencia de
  Jaime): no se commitea, no sale del equipo.
- Esto es un estudio de datos, no un backtest de estrategia: no aplica
  `run_backtest_orchestrator`, pero TAMPOCO se improvisan réplicas del motor
  para números que el motor deba dar (aquí no hay ninguno: son estadísticas
  sobre halts y velas).
- Resultado negativo (no hay regla con precisión alta) TAMBIÉN se entrega y
  documenta: saber que no existe la señal es información operativa.
