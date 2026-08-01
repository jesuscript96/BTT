# Runbook — Entorno de desarrollo / staging (co-ubicado en Falkenstein)

**Fecha:** 2026-07-30 (diseño) · **2026-08-01 (EJECUTADO)**
**Estado:** ✅ **VIVO en producción del servidor** — montado y verificado el 2026-08-01. El groundwork de diseño se conserva abajo; el estado real (as-built) está en la sección 0.
**Objetivo:** dar un entorno de pruebas real para validar cambios (filtros de datos, features) **antes de subir a prod**, y así **eliminar el anti-patrón actual** de meter gating admin/por-usuario en el código de prod solo para que los devs vean los cambios.

---

## 0. Estado REAL (as-built, 2026-08-01) ✅

Montado y verificado el **1 de agosto de 2026**. Todo lo de abajo (secciones 1-7) fue el diseño; esto es cómo quedó de verdad.

**Backend (API) — en el propio servidor principal**
- **Vive en el dedicado de Falkenstein `176.9.117.155`** como 2º contenedor aislado, junto a prod. Coste incremental 0. NO es máquina aparte.
- App Coolify: `b-t-t:develop-x2u32befrq2181gmym43yfhn`, proyecto `btt-marketanalysis-nuevo`, env `production` (Coolify 4.1.2 no dejó crear un env `staging`; **el aislamiento lo dan env+mounts+rama, no la etiqueta del environment**).
- **Rama:** `develop` (auto-deploy). `develop` sincronizada con `main` al montarlo.
- **URL API:** `https://x2u32befrq2181gmym43yfhn.176.9.117.155.sslip.io` (HTTPS con cert Let's Encrypt válido).

**Especificaciones con las que quedó**
| Parámetro | Valor |
|---|---|
| Rama | `develop` |
| Base Directory | **`/backend`** (Nixpacks fallaba con `/`: el backend está en subdir) |
| Build / Start | `pip install -r requirements.txt` / `uvicorn app.main:app --host 0.0.0.0 --port 3000` |
| RAM (tope cgroup) | **32 GiB** |
| CPU | **8** |
| `BACKTEST_PARALLEL_WORKERS` | `4` |
| `INTRADAY_STREAM_WORKERS` | `2` |
| `DUCKDB_MEMORY_LIMIT` | `12GB` |
| `DISABLE_GCS_SYNC` | `true` |
| `LIVE_SCREENER_ENABLED` | `false` |
| `REDIS_URL` | *(vacío)* |
| `LOCAL_LAKE_DIR` | `/lake` |

**Mounts (3)**
| Source (host) | Destination | Tipo |
|---|---|---|
| `/data/btt_lake` | `/lake` | Directory (RW; Coolify no da RO, ver nota) |
| `/data/btt_staging_cache` | `/tmp/btt_intraday_cache` | Directory (caché propia) |
| `/data/btt_staging/users.duckdb` | `/app/users.duckdb` | **File** (Directory Mount + "Convert to file") |

**Aislamiento verificado (staging NO puede dañar prod)**
- `DISABLE_GCS_SYNC=true` → no baja/sube `users.duckdb` a GCS. **Verificado**: la DB de prod en GCS quedó idéntica (byte a byte) tras el deploy de staging.
- `LIVE_SCREENER_ENABLED=false` → no arranca el WS de Massive → no pelea con prod (ver más abajo).
- Lake RW pero **la app nunca escribe/borra el lake** (verificado en código: `LOCAL_LAKE_DIR` solo se usa para leer). Caché en carpeta propia. Tope de RAM propio.
- Prod tras montar staging: contenedor con **0 reinicios**, DB intacta, screener sano.

**3 gotchas resueltos al montarlo (para la próxima)**
1. **Base Directory:** debe ser `/backend`, no `/` (si no, Nixpacks: *"failed to detect application type"*).
2. **Read-only del lake:** Coolify 4.1.2 **no ofrece toggle RO** en Directory Mounts. Se dejó RW; es seguro porque la app no escribe el lake (verificado). Si algún día se quiere RO físico, hay que hacerlo por config avanzada.
3. **HTTPS/cert:** el dominio hay que ponerlo con **`https://`** en General→Domains. Si se deja `http://`, Coolify solo crea el router `http-0` (sin `tls.certresolver`) y Traefik nunca pide cert → aviso de "conexión no privada". Con `https://` + redeploy, Let's Encrypt emite bien.
4. **`LIVE_SCREENER_ENABLED=false` es IMPRESCINDIBLE** (faltaba en el diseño original): el WS de Massive admite 1 conexión por API key; si staging arranca el screener, pelea con prod (error `1008` en bucle) y **degrada el screener en vivo de PROD**. Verificado en `live_screener_service.py:152`.

**Frontend (Vercel) — lo gestiona Jesús**
- Deploy de staging del frontend, rama `develop`, con env:
  `NEXT_PUBLIC_API_URL = https://x2u32befrq2181gmym43yfhn.176.9.117.155.sslip.io`
  (el front añade `/api` solo, `api.ts:15`).
- **CORS ya resuelto:** el backend acepta cualquier origen `*.vercel.app` (regex en `main.py:240`) → los previews funcionan sin tocar CORS.
- El cert válido de la API es imprescindible para que el `fetch` de Vercel (HTTPS) no se bloquee.

**Flujo resultante:** `push a develop → auto-deploy staging (back en servidor + front en Vercel) → validar → merge a main (prod)`.

---

## 1. Decisión

- **Staging = segundo contenedor aislado EN el propio servidor dedicado de Falkenstein** (176.9.117.155, 24c/125GB), NO en el CCX13.
- **Por qué no el CCX13** (US-east, Ashburn, 2 vCPU / 8 GB / 80 GB, hoy OFF):
  1. Está en **US**; el lake vive en el dedicado en **Alemania** → apuntar su storage al lake = montaje **transatlántico**, lecturas parquet aleatorias inservibles para backtests.
  2. Disco **80 GB < ~90 GB** del lake → ni cabe una copia.
  3. **8 GB RAM**: justo lo que se quiere testear (filtros de datos → backtests) es lo que más RAM come (prod usa 16 GB, un BROAD picó 29 GB) → OOM inmediato.
  → El CCX13 se deja **apagado/cancelable**. Para el objetivo real no sirve.
- **Coste incremental: 0** (usa capacidad ya pagada: 107 GB RAM libres, 1.4 TB disco libre).
- Creación vía **UI de Coolify** (build/SSL/auto-deploy gestionados por Coolify), no por API.

## 2. Seguridad — por qué staging NO puede dañar a prod (verificado en código)

- **`users.duckdb`:** `upload_user_db()` (`backend/app/gcs_sync.py:158`) es el **único punto de subida** a GCS — tanto el de shutdown como los "en background tras cada save" pasan por ahí. Chequea `DISABLE_GCS_SYNC` (línea 171) y `download_user_db()` (línea 123) igual. Con **`DISABLE_GCS_SYNC=true`** staging **no baja** la DB de prod ni **sube nada** a GCS por ninguna ruta.
- **Crons de escritura a GCS** (catchup_gcs / daily_wash): son crons del **host** que hacen `docker exec` al contenedor de **PROD** (nombre hardcodeado) → staging **nunca** los ejecuta. No se le añaden crons.
- **Lake:** se monta en **solo-lectura** → staging físicamente no puede corromper el lake de prod. (Además ningún code-path de request escribe el lake; los únicos escritores son los crons de ingesta, ausentes en staging.)
- **Caché de disco propia:** staging usa su **propia** carpeta de caché, no la de prod (comparten esquema de clave sin mtime → compartirla contaminaría/evictaría la de prod).
- **Recursos:** staging con **tope de memoria** (cgroup) → un OOM de staging (nos pasó con BROAD) muere en su cgroup, **no toca prod**.

## 3. Arquitectura

| Pieza | Prod | Staging |
|---|---|---|
| Máquina | dedicado Falkenstein | **el mismo** |
| Lake | `/data/btt_lake` → `/lake` (rw) | **`/data/btt_lake` → `/lake` (solo-lectura)** |
| `users.duckdb` | ciclo GCS | **copia local propia + `DISABLE_GCS_SYNC=true`** |
| Caché disco | `/data/btt_intraday_cache` | **`/data/btt_staging_cache`** (propia) |
| GCS/charts | lee/escribe | **solo lee** |
| Crons | sí | **ninguno** |
| Código | rama `main` (auto-deploy) | **rama `develop`** (auto-deploy independiente) |
| Dominio | sslip.io | **sslip.io propio** (sin DNS) |
| RAM | sin tope (`mem_limit=0`) | **tope ~32 GB** |
| Workers | 12 | reducidos (4/2) |

## 4. Groundwork YA hecho (2026-07-30)

- ✅ **Semilla de la DB:** descargada la copia autoritativa y consistente de GCS a **`/data/btt_staging/users.duckdb`** (1.148 GB). Verificada: abre bien, contiene datos reales (19 estrategias, 164 saved_queries, 164 datasets).
- ✅ Confirmado: fuente lake `/data/btt_lake`, app en `/app`, `users.duckdb` en `/app/users.duckdb`, puerto `3000`, build Nixpacks.
- ✅ Verificado el chokepoint de `DISABLE_GCS_SYNC` en el código.

## 5. Receta Coolify (cuando se ejecute)

**1) Proyecto/entorno:** en `btt-marketanalysis-nuevo` → Environment `staging` → **+ New Resource → Application → Private Repository (GitHub App)** → repo `jesuscript96/BTT`.

**2) Source:** Branch **`develop`** · Build Pack **Nixpacks** · Port **3000**.

**3) Domain:** sslip.io autogenerado (sin DNS, SSL automático).

**4) Persistent Storage (3 mounts):**
| Source (host) | Destination | Modo |
|---|---|---|
| `/data/btt_lake` | `/lake` | **solo-lectura** |
| `/data/btt_staging/users.duckdb` | `/app/users.duckdb` | rw (mount de fichero) |
| `/data/btt_staging_cache` | `/tmp/btt_intraday_cache` | rw (caché propia) |

**5) Env Vars:** copiar TODAS las de prod y cambiar/añadir solo:
| Variable | Valor | Por qué |
|---|---|---|
| `DISABLE_GCS_SYNC` | `true` | no baja ni sube `users.duckdb` a GCS |
| `BACKTEST_PARALLEL_WORKERS` | `4` | prod=12; >4 segfaultea sin pre-spawn |
| `INTRADAY_STREAM_WORKERS` | `2` | seguro (4/2 validado) |
| `DUCKDB_MEMORY_LIMIT` | `12GB` | self-límite DuckDB |
| `REDIS_URL` | *(vacío)* | evita colisión de job-state con prod (degrada a memoria) |
| `LOCAL_LAKE_DIR` | `/lake` | igual (mount ya RO) |
| `LIVE_SCREENER_ENABLED` | `false` | 🔴 **IMPRESCINDIBLE**: el WS de Massive admite UNA conexión por key; si staging lo arranca, pelea con prod (error 1008 en bucle) y **degrada el screener en vivo de prod**. Verificado en `live_screener_service.py:152`. |

Resto (llaves GCS/Massive/Clerk, `GCS_BUCKET`, `DB_PROVIDER=gcs`, …) igual que prod (uso de solo lectura).

**6) Resource Limits (Advanced):** Memory **32 GB**, CPU opcional **8**.

**7) Deploy.** Con `DISABLE_GCS_SYNC=true` NO baja la DB → usa la semilla de `/app/users.duckdb`.

**8) Frontend:** preview de Vercel (por rama/PR) apuntando al API de staging, o proyecto Vercel `staging`.

## 6. Flujo resultante (sustituye al hack de gating admin)

`rama develop → push → auto-deploy staging (datos reales, aislado) → validar → merge a main (prod)`

Se retiran los gating admin de "preview" (los de tier/producto reales se quedan).

## 7. Verificación end-to-end (al montarlo)

- [ ] Arrancó con la semilla (19 estrategias visibles en la UI).
- [ ] Un backtest lee el lake (RO) y da resultados.
- [ ] En el log **NO** aparecen subidas a GCS (busca el aviso `DISABLE_GCS_SYNC=true`).
- [ ] La caché se crea en `/data/btt_staging_cache`, no en la de prod.
- [ ] Prod intacto (salud /health 200, sin reinicios).
