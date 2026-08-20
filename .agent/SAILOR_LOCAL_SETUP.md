# Setup local de Sailor (BTT + lago propio) — LEER ANTES DE TOCAR NADA

> Documento de continuidad entre sesiones de IA. Si empiezas una sesión nueva
> sobre este repo, **lee esto entero antes de proponer o ejecutar nada**.
> Última actualización: 2026-08-19.

## 1. Git — reglas duras

- Rama de trabajo: **`sailor-rama-desarrollo`**. Clonada en modo `--single-branch`:
  el repo local **no conoce ninguna otra rama** (es deliberado).
- **Solo se sube a dos sitios, y SIEMPRE con orden explícita del usuario:**
  `sailor-rama-desarrollo` y `staging`. **Prohibido** tocar `main`, `develop`
  o cualquier otra rama.
- **Antes de cada `push`, pedir confirmación explícita.** Sin excepción.
- Para traer `staging` haría falta ampliar el `--single-branch` (operación de
  solo lectura, pero **preguntar antes**: sale del aislamiento pactado).

## 2. Dónde está cada cosa

| Qué | Dónde | Nota |
|---|---|---|
| Repo BTT | `D:\Backtester` | **fuera de OneDrive a propósito** |
| Lago de datos (194 GB) | `D:\lago_backtester` | raw, parquet, cold_storage |
| Proyecto del lago (código/docs) | `C:\...\Backtester personal\Base de datos Backtester` | scripts fase0-8, sql/, docs/ |
| BBDD que lee la app | `D:\Backtester\backend\local_data.duckdb` | **hard link** a `D:\lago_backtester\edgecute_db\` |

⚠️ El hard link se rompe si se regenera el lago con `actualizar_diario.py`
(escribe con patrón tmp+rename). Si pasa: recrear con
`New-Item -ItemType HardLink`.

## 3. Configuración local (`backend/.env`) — por qué cada línea

Los defaults del repo están calibrados para el **servidor de producción**
(Xeon, 128 GB RAM). Este equipo tiene **16 GB**. Sin estos overrides, el
backtest no arranca o tarda horas:

| Variable | Valor | Motivo |
|---|---|---|
| `DB_PROVIDER` | `local` | lee `local_data.duckdb`, no GCS |
| `DISABLE_GCS_SYNC` | `true` | **obligatorio** — sin esto el local puede pisar la BD de usuarios de PROD |
| `LIVE_SCREENER_ENABLED` | `false` | **obligatorio** — pelearía la conexión en vivo con PROD |
| `LOCAL_LAKE_DIR` | `D:/lago_backtester/parquet/edgecute` | el motor de backtests lee **Parquet**, no la tabla DuckDB |
| `MIN_AVAILABLE_DATE` | `2019-01-01` | el default `2022-01-01` ocultaba 3 años del lago |
| `DUCKDB_MEMORY_LIMIT` | `3GB` | 4GB (default) agotaba la RAM; 1.5GB hacía spillear la query de candidatos |
| `BACKTEST_MIN_AVAIL_GB` | `1.0` | el guard de 4GB rechazaba el backtest con 503 en 16GB |
| `INTRADAY_PREWARM_ENABLED` | `false` | el prewarm masivo saturaba el disco y mataba de hambre al backtest |
| `BACKTEST_NUMBA_SIM` | `1` | kernel compilado del simulador |
| `QUALIFYING_CACHE_TTL` | `86400` | el TTL de 300s caducaba antes de re-ejecutar |
| `QUALIFYING_DATE_PRUNE` | `true` | ver §4 |
| `ROBUSTNESS_ENABLED` | `true` | pagina de Robustez; **default OFF**, en prod no existe |

`frontend/.env.local`: `NEXT_PUBLIC_API_URL=http://localhost:8010`,
`NEXT_PUBLIC_LOCAL_AUTH_BYPASS=true` (sin claves de Clerk, no hacen falta) y
`NEXT_PUBLIC_ROBUSTNESS_ENABLED=true` (entrada de menu de Robustez; sin ella
la pagina no se lista).

## 4. Cambios en el código del repo (2, ambos sin commitear aún)

`backend/app/services/data_service.py`:

1. **`_QUALIFYING_REDIS_TTL`** ahora se lee de `QUALIFYING_CACHE_TTL`
   (antes constante 300). Sin riesgo: default idéntico.
2. **Poda por fechas de `raw_daily`**, gated por `QUALIFYING_DATE_PRUNE`
   (**default OFF** → prod no cambia). La query de candidatos calculaba 32
   ventanas LAG/LEAD sobre los 19M de filas enteros; acotada al rango del
   dataset + margen 45d baja de **494s a 34s (14x)**.
   ⚠️ **Verificado**: las columnas base (las que usa `apply_day=gap_day`) son
   IDÉNTICAS. Con margen 15d, 3 de 4.899 filas tenían lag/lead distintos
   (tickers con suspensión larga); con 45d el riesgo residual afecta solo a
   `gap±1/±2` o `preconditions` en esos tickers-frontera.

## 4bis. Pagina de Robustez (anadida 2026-08-20)

Modulo aparte para analizar estrategias ya backtesteadas: analisis basico,
Monte Carlo bootstrap, walk-forward (rapido y completo), y matriz
locates x slippage. Ruta `/robustez`, endpoints bajo `/api/robustness`.

**Apagado por defecto** (R7). En el repo solo cambian 3 lineas de `main.py`
(montar el router) y el bloque de menu de `Sidebar.tsx`; todo lo demas son
ficheros nuevos. Sin las variables de entorno, el router responde **503** y la
entrada del menu no se pinta.

**No se ha tocado** `what_if_service.py` ni `montecarlo_service.py` pese a que
ambos tienen problemas para estrategias con `risk_type=PERCENT` (suman PnL en
dolares, lo que produce equity negativa). El modulo lleva sus propios motores.
Detalle y numeros en `MEMORIA.md` §4.2 y §4.4.

**Dos cosas del repo que conviene saber** (documentadas, no corregidas):
- `slippage` NO usa la misma unidad en las dos vias del simulador:
  `portfolio_sim_jit` lo trata como **fraccion**, `backtester/engine.py` como
  **porcentaje**. El campo de la UI se titula "Slippage (%)" pero va por la
  primera via, asi que un `0.001` son **0,1% reales**.
- `total_return_pct` se calcula **sin restar** `monthly_expenses`; los gastos
  solo aparecen en `total_pnl_net`.

**Un solo trabajo pesado a la vez:** los barridos llevan guardian; un segundo
lanzamiento devuelve 409.

**Cuidado al editar el backend mientras corre un barrido:** el `--reload` de
uvicorn SI funciona en esta maquina (lo contrario de lo que decia MEMORIA hasta
el 2026-08-20), asi que cualquier cambio en un `.py` reinicia el proceso y
**mata el trabajo en curso**. Esperar a que termine.

## 5. Arrancar en local

`.claude/launch.json` (en la carpeta de sesión, no en el repo) define
`btt-backend` y `btt-frontend`. Detalles no obvios:
- El backend se lanza vía `cmd /c cd /d ... && ...` porque el repo está fuera
  del directorio de la sesión.
- **`PYTHONUNBUFFERED=1` es imprescindible**: con `--reload`, uvicorn respawnea
  y sin esa variable los `print()` de arranque no aparecen (parece colgado).
- El log `[INFO] GCS sync disabled by environment variable` es la comprobación
  obligatoria de que el aislamiento está activo. Si no aparece, **parar**.

## 6. Rendimiento — números reales medidos (2026-08-19)

| Escenario | Tiempo |
|---|---|
| Backtest 2 años, 4.863 ticker-días, caché caliente | **36,8 s** |
| Query de candidatos, tabla completa | 494 s |
| Query de candidatos, acotada (`QUALIFYING_DATE_PRUNE`) | 34 s |
| Fetch de un mes de intradía, caché fría | ~14 s |
| Fetch de un mes de intradía, caché caliente | **0,28 s** |

Cachés que persisten entre reinicios:
- `D:\tmp\btt_intraday_cache` — un parquet por ticker-mes (cuota 40 GB, LRU)
- `/tmp/btt_qualifying_cache` — resultado de la query de candidatos

**Errata a no repetir:** se asumió que la máquina de referencia (la del autor
del prompt del lago) iba rápida por tener `intraday_1m_optimized`. **No lo
tiene.** Va rápida por 31 GB de RAM y una semana de caché caliente. Lo confirmó
él mismo.

## 7. Pendiente / ideas

### FASE 8 — APLAZADA A PROPÓSITO (decisión del usuario, 2026-08-19)

`intraday_1m_optimized`: una segunda copia del intradía **ordenada por ticker**,
que permite a DuckDB podar row-groups y leer solo el trozo del ticker pedido.

- **Script listo y probado**: `Base de datos Backtester/scripts/fase8_optimizar_intraday.py`
  (+ `lanzar_fase8.cmd`). Idempotente, escribe `.tmp` y renombra, prioriza
  2024-2026. **Solo escribe en `D:`, no toca el repo.**
- **Beneficio**: lecturas FRÍAS de 14s → ~1-2s por mes.
- **Coste medido**: **10-15 h** para los 92 meses (~6-10 min/mes; el ORDER BY de
  25M filas por mes es lo caro). Ocuparía ~41 GB adicionales.
- **Por qué se aplazó**: la caché por ticker-mes (§6) da el mismo beneficio
  práctico para el universo de gaps en **30 min en vez de 15 h**. La Fase 8 solo
  aporta para tickers FUERA de ese universo ya calentado.
- **Cuándo retomarla**: si aparecen backtests sobre tickers no cacheados y las
  esperas de ~14 s/mes molestan. Lanzar de noche con:
  `Start-Process "...\scripts\lanzar_fase8.cmd" -WindowStyle Hidden`

⚠️ **Errata histórica documentada**: durante el diagnóstico se asumió que la
máquina de referencia iba rápida por tener `_optimized`. **No la tiene.** Va
rápida por 31 GB de RAM y caché caliente. No repetir esa hipótesis.
- Faltan en el lago dos cosas que la app espera: columna `primary_exchange` en
  `tickers` y tabla `ticker_sector` (afecta a "Gaps by Sector" y filtros por
  bolsa). Requiere ampliar el ETL de la Fase 6.
- IPOs cuentan como gap falso (caso ATTO 2026-08-05, +4.733%). Arreglo pendiente
  en `sql/metricas_diarias.sql` del proyecto del lago — decidir umbral de días
  con el usuario.
- El lago va 3 días por detrás (llega a 2026-08-14): `actualizar_diario.py`.

## 8. Cómo trabajar con este usuario

- Trabajo **por fases con checkpoints**: enseñar números concretos y esperar OK.
- **Avisar antes** de cualquier operación >10 GB o >1 hora.
- Si un dato real contradice la documentación, **parar y reportar con
  evidencia** — no "arreglarlo" por cuenta propia.
- Las credenciales del `.env` **nunca** se imprimen ni se commitean.
