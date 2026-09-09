# Regla de oro del backend local: UN solo dueño de `local_data.duckdb`

> Creado el 2026-09-07 tras dos bloqueos de la carga diaria (2026-09-05 y
> 2026-09-07) y un backtest fallido con `INTERNAL Error: Failed to load
> metadata pointer (id 222121…)`. Ese error, **en esta máquina**, significa
> **contención** (otro proceso con la base abierta) **o choque de versiones
> de duckdb** — **no corrupción física**: quedó verificado el 2026-09-07 que
> la base abre y escanea perfecta con duckdb 1.5.5. Ese mismo día el venv del
> backend llevaba duckdb 1.1.3 y no podía leer el storage re-escrito por
> 1.5.5 (la verificación/carga hecha con el python del sistema), que es lo
> que producía exactamente ese error. **Toda operación sobre la base —carga,
> verificación, backend— debe usar la MISMA versión de duckdb.**

## La regla (una frase)

**Un único proceso puede tener abierto `backend/local_data.duckdb` a la vez,
arrancado siempre con `backend\.venv\Scripts\python.exe` y nunca con
`uvicorn --reload`.**

## Cómo se arranca (y cómo no)

```bat
:: BIEN — launcher con guardas (puerto + DuckDB + venv + flags de seguridad):
backend\scripts\arrancar_backend.bat
::      (equivalente: backend\.venv\Scripts\python.exe backend\scripts\run_backend_safe.py)

:: MAL — jamás, mientras el backend use local_data.duckdb:
uvicorn app.main:app --reload ...
```

El launcher (`run_backend_safe.py`) antes de arrancar:

1. Verifica que el intérprete es el del venv del proyecto (aborta si no).
2. Exige `DISABLE_GCS_SYNC=true` y `LIVE_SCREENER_ENABLED=false` (AGENTS.md).
3. Comprueba que **nadie escuche ya en el 8010** (si hay alguien, dice su PID
   y aborta en vez de pisarse).
4. Hace una **sonda del DuckDB**: abre y cierra `local_data.duckdb`; si otro
   proceso lo retiene, aborta traduciendo el error críptico de DuckDB y
   listando los procesos sospechosos con PID.
5. Arranca uvicorn **sin `--reload` y con 1 worker**, y pone
   `BTT_REQUIRE_DB=1` para que el proceso muera si la base no abre (nunca
   sirve "bien" sin datos).

Flags útiles: `--check-only` (solo comprobar, sin arrancar) y
`--kill-orphans` (mata árboles huérfanos de python que retengan la base).

## Por qué pasaba lo que pasaba (las 3 causas juntas)

1. **`uvicorn --reload`**: el reloader arranca workers hijo (`spawn_main`).
   Si la consola/consola padre muere (o se mata solo el proceso visible), los
   workers quedan **huérfanos reteniendo el DuckDB con el puerto libre**. El
   backend siguiente arranca "bien", no puede abrir la base y revienta con
   errores crípticos de lock/metadata. Hasta el 2026-09-07 la guía oficial
   decía literalmente `uvicorn app.main:app --reload …`, así que cada sesión
   de agente reintroducía el problema.
2. **El venv es de `uv` y su `python.exe` es un trampoline**: al ejecutar
   `backend\.venv\Scripts\python.exe` aparecen **DOS procesos** — el
   trampoline y el python real del sistema como **hijo** (misma línea de
   comandos, distinto ejecutable). Eso explica los "huérfanos con un Python
   distinto al del venv": son los hijos reales cuyo trampoline murió.
   Consecuencia práctica: **para parar el backend hay que matar el árbol
   completo** (`taskkill /PID <pid> /T /F`), nunca solo el proceso visible.
3. **Watchdog legacy**: `scripts/run_backend_forever.bat` (tarea "BTT backend
   watchdog", 2026-08-28) re-arrancaba el backend **con `--reload`** cada vez
   que el 8010 quedaba libre, y su `timeout` no esperaba sin consola
   (crash-loop el 05-sep). La tarea programada fue borrada, pero una
   instancia del bat siguió viva hasta el 2026-09-07. El bat sigue en el
   repo, ya corregido: sin reload, vía launcher seguro, sleeps con `ping`.
4. **Choque de versiones de duckdb** (causa del error de metadata del
   2026-09-07): el venv del backend llevaba `duckdb==1.1.3`
   (`backend/requirements.txt`), mientras el python del sistema (que usaron
   huérfanos y la verificación manual de la base) tiene 1.5.5. DuckDB lee
   hacia atrás (1.5.x abre ficheros de 1.1.x) pero **no al revés**: la base
   quedó checkpointeada por 1.5.5 y el backend 1.1.3 ya no podía abrirla —
   `Failed to load metadata pointer (id 222121)` incluso en solo-lectura y
   sin ningún proceso vivo. El venv se actualizó a 1.5.5 el 2026-09-07 para
   alinearlo; **`requirements.txt` sigue fijando 1.1.3** y eso hay que
   decidirlo en el repo (prod/staging usan GCS/MotherDuck, evaluar el salto
   juntos). Regla práctica: **una sola versión de duckdb puede tocar la base
   — la del venv alineada con la que cargue cangrejo_data**.

## Coordinación con la tarea de las 09:00 (cangrejo_data)

La tarea programada **"Edgecute Actualizar Datos Diario"** (proyecto
`cangrejo_data`, cada día 09:00):

1. Hace `taskkill` del árbol que escucha en el 8010 (el backend "muere": es
   normal, no es un fallo).
2. Carga los datos del día en `local_data.duckdb` reteniéndolo en exclusiva.
3. Rearranca uvicorn (sin reload) y espera al `/health`.

**Qué NO hacer:** no relances el backend en medio de la carga ni compitas por
la base entre ~08:55 y ~10:00. El launcher se autodetiene con un mensaje
claro si detecta la base retenida; espera y reintenta después. Ese pipeline y
su tarea **no se tocan desde este repo**.

## Chuleta de emergencia

```powershell
# ¿Quién escucha en el 8010?
netstat -ano | findstr ":8010"

# Procesos python relacionados con el backend (trampoline + hijo real):
Get-CimInstance Win32_Process -Filter "Name LIKE '%python%'" |
  Where-Object { $_.CommandLine -match 'uvicorn|spawn_main|app.main' } |
  Select ProcessId,ParentProcessId,ExecutablePath,CommandLine | Format-List

# Matar el backend o un huérfano (¡siempre con /T para llevarse el árbol!):
taskkill /PID <pid> /T /F

# Cazar huérfanos con el launcher (padre muerto + cmdline de uvicorn/spawn_main):
backend\scripts\arrancar_backend.bat --kill-orphans

# Health check:
curl http://127.0.0.1:8010/health
```

Señal de que todo está bien al arrancar: el banner del launcher, el log
`[INFO] GCS sync disabled by environment variable (DISABLE_GCS_SYNC=true).`,
`[INFO] Connected. Tables: [...]` y `/health` → `{"status":"ok"}`.
