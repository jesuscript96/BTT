# AGENTS.md — Reglas para agentes de IA en este repo (BTT)

> Este archivo lo cargan automáticamente los IDEs/agentes de IA (Antigravity, Cursor, Claude Code…).
> **Léelo entero antes de tocar el repo.** Contiene reglas que NO se pueden saltar.

## 🔴 Reglas de oro (universales)

1. **JAMÁS se toca `main`.** Nada de commit, push, PR base `main` ni merge a `main`. `main` = producción real con clientes de pago.
2. **Cada desarrollador trabaja en su rama personal** e integra a `develop` **solo por Pull Request**. El salto `develop → main` lo hace Adrian, nunca la IA.
3. **Antes de cada `push`, pídele confirmación explícita al usuario.**
4. **Nunca commitees secretos ni datos:** `.env`, `.env.local`, `gcs-key.json`, `*.duckdb`, `data/`, `.cache/`, `.venv/`, `node_modules/`. Ya están en `.gitignore`; no los fuerces.
5. **Antes de modificar un archivo, léelo completo.** Un paso a la vez; confirma antes de continuar. No borres código: muévelo a `_archive/`.
6. **🚨 EL BOT DE AVISOS EN VIVO Y LA PÁGINA DE ALERTAS NO SE TOCAN** (sección siguiente). No los modifiques, no los arranques, no los configures y **no te los descargues para probarlos**. Si tu tarea te lleva ahí, **para y pregunta a Jaume**.

## 🚨 Zona cerrada: el bot de avisos en vivo (Alertas)

**Esto lo llevan Jaume y Sailor en exclusiva, por ahora.** No es celo de código:
hay tres razones concretas, y ninguna se arregla teniendo cuidado.

1. **Opera con dinero real.** Los avisos salen a un grupo de Telegram y Jaume
   pone las órdenes a mano con ellos. Un cambio que altere una condición no
   rompe un test: le hace entrar en una operación que no era.
2. **La cuenta de datos en vivo admite UNA sola conexión.** Si arrancas el bot
   en tu equipo **echas al de Jaume y lo dejas sordo**, sin que ninguno de los
   dos vea un error. Pasó el 2026-09-02 con una simple prueba.
3. **Está en desarrollo activo** y todavía sin cobertura suficiente. Lo que hoy
   parece código muerto o mejorable suele ser una decisión medida.

**No toques, no arranques, no configures y no descargues:**

```
backend/app/services/bot_alerts_*.py    backend/app/routers/bot_alerts.py
backend/tests/test_bot_alerts_*.py      docs/BOT_ALERTAS_MODOS_DE_FALLO.md
frontend/src/components/bot-alerts/     frontend/src/lib/api_bot_alerts.ts
frontend/src/app/bot-alertas/           (y `D:\bot_senales\`, fuera del repo)
```

**Excepción, con aviso: `backend/app/services/market_frame.py`.** Ese SÍ es
compartido — el backtester y el bot usan la misma fórmula a propósito, verificada
bit a bit. Leerlo, todo lo que quieras. Para **cambiarlo**, avisa a Jaume antes:
cualquier retoque mueve las señales en vivo aunque los backtests sigan pasando.

Si algo de Alertas te estorba para una tarea legítima, dilo y se resuelve — pero
la decisión es de Jaume, no del agente.

## 🔒 Seguridad en desarrollo local (imprescindible)

Este proyecto lee/escribe en almacenamiento **compartido con producción**. En local, `backend/.env` DEBE tener:

```dotenv
DISABLE_GCS_SYNC=true        # si no, tu local puede SOBRESCRIBIR la BD de usuarios de PROD
LIVE_SCREENER_ENABLED=false  # si no, peleas la conexión en vivo y DEGRADAS el screener de PROD
```

Si al arrancar el backend **no** ves el log `GCS sync disabled by environment variable (DISABLE_GCS_SYNC=true)`, **para el servidor**: falta la variable. El porqué está en `docs/GUIA_DEV_LOCAL_Y_DEVELOP_PARA_IA.md` §5.

## 🧪 Backtests / análisis con el motor real (no réplicas manuales)

Cuando se pida un backtest o análisis, usar siempre la lógica ya
existente en el motor (`run_backtest_orchestrator`, `translate_strategy`,
etc.) — nunca una réplica manual con lógica propia. Si una regla no se
puede expresar tal cual con el motor, parar y decirlo, no improvisar
una aproximación silenciosa.

**Antes de lanzar cualquier backtest, análisis o consulta**, mostrar
siempre la lista completa de campos que el usuario NO ha especificado
y que el motor va a rellenar por su cuenta — con el valor por defecto
de cada uno y si afecta o no al resultado. No decidir por criterio
propio cuál es "neutro": verificarlo leyendo el código de ejecución
real (el orquestador puede pisar el default del propio motor), no solo
la firma de la función. Si un campo cambia el resultado y el usuario
no lo ha dicho, preguntar antes de rellenarlo.

Motivo: en la sesión del 2026-08-05 esto falló dos veces seguidas —
`market_sessions` sin especificar cae en `["RTH"]` por un default del
orquestador (no de `run_backtest()`, que sugiere "sin restricción"),
borrando toda vela premarket sin ningún error; y `accept_reentries`/
`max_reentries` del esquema de estrategia por defecto son `true`/`-1`
(reentradas ilimitadas), no acotadas. Las dos veces se dijo que el
default era neutro y las dos veces no lo era.

**`look_ahead_prevention: true` siempre**, en todos los backtests de
Álvaro. Cuando una vela M1 cierra, ya no se puede ejecutar a ese
precio — entrar al cierre de la propia vela de señal es look-ahead
encubierto (información que en tiempo real no estaría disponible
todavía). La ejecución realista entra en la apertura de la vela
siguiente. No es un valor por defecto neutro que se pueda dejar sin
especificar: fijarlo explícito a `true` en cada backtest.

## 🧾 Protocolo de hallazgos — REPORTAR, NO ARREGLAR

> Aplica a toda IA que trabaje en este repo en rol de **pruebas y análisis**.
> Fijado a petición de Álvaro el 2026-08-29. Modificar este protocolo requiere
> su OK explícito.

### Rol

Investigar, probar, medir y REPORTAR con evidencia. La IA de pruebas NO es
quien arregla el código: el dueño del código aplica el fix en SU rama; la IA
de pruebas solo reporta y luego verifica.

### Regla nuclear (no se salta nunca)

Cuando, probando o analizando, encuentres un bug, una inconsistencia, un
número que no cuadra o cualquier cosa dudosa: **NO modifiques el código para
arreglarlo.** Lo REPORTAS en memoria y paras.
Motivo: en este repo trabajan dos desarrolladores en ramas separadas
(Álvaro → `alvaro-rama-desarrollo`, Sailor → `sailor-rama-desarrollo`) que
integran a `staging`. Si cada IA arregla por su cuenta, se MEZCLAN cambios y se
generan conflictos.

### Qué es un "hallazgo" reportable

- Bug: resultado imposible, crash, cálculo erróneo.
- Inconsistencia: dos caminos que deberían dar lo mismo y no; un default que no
  es neutro; look-ahead encubierto; paridad Python↔Numba rota.
- Número que no cuadra: métricas que no atan, R/PnL que no salen.
- Duda de semántica/diseño que afecta a resultados.

Si es solo cosmética o una refactor opcional, márcalo como "MEJORA (opcional)",
no como bug.

### Cómo reportar (formato OBLIGATORIO)

Añadir una entrada AL FINAL de `docs/MEMORIA_MADRE.md` (se escribe hacia abajo,
bajo la fecha de hoy; NUNCA editar entradas anteriores). Un hallazgo por entrada,
con este formato exacto:

```text
### [HALLAZGO · AAAA-MM-DD · nn] <título corto>
- **Reporta:** <nombre de tu IA> (para Álvaro)
- **Severidad:** crítico | bug | inconsistencia | duda | mejora
- **Dónde:** <ruta/archivo.py:línea>  (o "N/A")
- **Qué observé:** <el hecho concreto, sin adornos>
- **Cómo reproducir:** <comando exacto / config EXACTA / pasos>
- **Evidencia:** <números reales, salida, logs — NUNCA suposiciones>
- **Hipótesis de causa:** <opcional, y marcado literalmente como HIPÓTESIS>
- **Impacto:** <qué resultados o áreas afecta>
- **Código tocado:** NINGUNO (confirmado)
- **Estado:** ABIERTO
```

### El bucle de resolución (cómo se cierra)

1. La IA de pruebas reporta → estado ABIERTO.
2. Álvaro lo lee y lo lleva al dueño del código / a la IA de fixes.
3. Se resuelve en la rama que corresponda.
4. La IA de pruebas VERIFICA el fix (no lo escribe ella): reproduce, confirma
   que el hallazgo desaparece, y marca RESUELTO (con el commit) o REABIERTO
   (con la evidencia de que sigue). El cambio de estado va como entrada NUEVA
   al final de `docs/MEMORIA_MADRE.md`, no editando la vieja.

### Lo único que la IA de pruebas SÍ puede tocar sin reportar

- Ficheros efímeros de prueba en su carpeta temporal/scratchpad (scripts de un
  solo uso para medir). Eso NO es "tocar el código del repo".
- Un cambio real en el repo SOLO si Álvaro lo pide EXPLÍCITAMENTE, en SU rama,
  y tras enseñarle exactamente qué se va a cambiar y esperar su OK.

### Recordatorio de límites duros (definidos arriba en este archivo)

- JAMÁS se toca `main`. Rama por desarrollador. Antes de CUALQUIER push,
  confirmación explícita del usuario.
- Nunca commitear secretos ni datos (`.env`, `*.duckdb`, `data/`, `gcs-key.json`).
- El backend local DEBE loguear `DISABLE_GCS_SYNC=true`; si no aparece, PARAR.
- Backtests con el motor real (`run_backtest_orchestrator`/`translate_strategy`),
  nunca réplicas manuales. Antes de lanzar uno, enseñar la lista de campos que
  el motor rellena por defecto y si afectan al resultado.
  `look_ahead_prevention=true` siempre.
- Antes de modificar un archivo, leerlo entero. No borrar código: moverlo a
  `_archive/`.

## 👤 Reglas por desarrollador (rama + flujo)

Aplica el archivo que corresponda al usuario actual:

- **Álvaro** → `.agent/ALVARO_DEV_BRANCH.md` (rama `alvaro-rama-desarrollo`, integra a `staging`)
- **Sailor** → `.agent/SAILOR_DEV_BRANCH.md` (rama `sailor-rama-desarrollo`, integra a `staging`)
- **Jaume** → `.agent/JAUME_DEV_BRANCH.md` (rama `jaumen-rama-desarrollo`)

> Álvaro y Sailor comparten la rama de integración `staging`: cada uno trabaja en
> SU rama personal y la mergea a `staging` para sincronizarse. `main` no se toca.

## 📚 Contexto del proyecto (lee según necesites)

- **Onboarding / arrancar en local / flujo git completo:** `docs/GUIA_DEV_LOCAL_Y_DEVELOP_PARA_IA.md` ← empieza aquí
- **Arquitectura:** `.agent/ARCHITECTURE.md`
- **Lógica de negocio:** `.agent/BUSINESS_LOGIC.md`
- **Reglas de código (backend/frontend/BD):** `.agent/CODING_RULES.md`
- **Sistema de diseño:** `.agent/EDGECUTE_DESIGN_SYSTEM.md`
- **Contexto general:** `.agent/PROJECT_CONTEXT.md`

## 🧭 Reglas de código (resumen — detalle en `.agent/CODING_RULES.md`)

- **Backend:** routers solo endpoints + Pydantic; la lógica va en `services/`. Env siempre por `os.getenv()`, nunca hardcodeada. Cambios en `backtester/` requieren verificar el JIT de Numba.
- **Frontend:** fetch centralizado en `lib/api.ts`; nunca hardcodear URLs, usar `NEXT_PUBLIC_API_URL`.
- **BD:** queries parametrizadas con `?`, nunca concatenación. No tocar el schema de `daily_metrics`/`intraday_1m` ni el Parquet de GCS sin consenso.

## ✅ Al empezar cada sesión

1. `git branch --show-current` → confirma que estás en tu rama personal (no `develop`/`main`).
2. Comprueba que el backend loguea `DISABLE_GCS_SYNC=true`.
3. Ante cualquier duda que implique datos, entornos o algo que pueda llegar a producción: **pregunta antes de ejecutar.**
4. Si tu rol en la sesión es pruebas y análisis: aplica el **§ 🧾 Protocolo de hallazgos — REPORTAR, NO ARREGLAR** (más arriba). Hallazgos → entrada nueva al final de `docs/MEMORIA_MADRE.md`; jamás arreglar el código por tu cuenta.
