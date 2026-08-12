# Runbook — users.duckdb en disco persistente vía File Mount (Fase 1)

**Objetivo.** Eliminar de raíz el timeout de `POST /strategies/` (20 s). Hoy en PROD,
`users.duckdb` (1,15 GB) se re-sube ENTERO a GCS **dentro del lock global** tras cada
guardado → el lock queda retenido 30-50 s → los guardados esperan → corte a los 20 s.

**Enfoque (confirmado en vivo en STAGING).** Poner `users.duckdb` en un **File Mount** de
Coolify (fichero del host, persistente) y **apagar el sync a GCS**. Sin subida no hay lock
retenido. **El bucket de GCS se conserva CONGELADO** como respaldo frío durante la transición.

## Estado real (verificado 2026-08-11)

| | Staging (app `x2u32…`, rama develop) | **Prod (app `kvcfvkb…`, rama main)** |
|---|---|---|
| File Mount `users.duckdb` | ✅ `/data/btt_staging/users.duckdb → /app/users.duckdb` | ❌ **no existe** |
| `users.duckdb` | persistente (disco, desde 30-jul) | **efímero** (`/app`, se recrea en redeploy) |
| `DISABLE_GCS_SYNC` | `true` | **sin definir → GCS ON** (causa del timeout) |

**Staging ya corre el modelo objetivo y funciona → es la prueba de que el enfoque es correcto.**
A prod solo hay que replicarlo. En Coolify el mount de un fichero suelto se llama **"File Mount"**
(Storages → Persistent Storage → + Add → File Mount).

> Nota: el cambio de código `USER_DB_PATH` (merge `eb4b484`) **NO es necesario** con este enfoque
> —el File Mount cae sobre la ruta por defecto `/app/users.duckdb`—. Queda como opción inofensiva
> (por defecto no altera nada). Encoger el fichero es la **Fase 2** (sacar `dataset_pairs`).

---

## Cutover de PROD — reparto de tareas

Regla de oro: **nunca** dejar el fichero efímero **y** GCS apagado a la vez. Orden estricto.

### Paso 1 — [YO · SSH] Sembrar el fichero persistente del host
Copiar el `users.duckdb` vivo de prod al path del host que usará el mount (antes de montarlo,
para que no arranque vacío):
```bash
mkdir -p /data/btt_userdb
docker cp <contenedor_prod>:/app/users.duckdb /data/btt_userdb/users.duckdb
# (+ .wal si existe)
```

### Paso 2 — [YO · SSH] Instalar el backup local (GCS deja de respaldar)
`backend/scripts/backup_user_db.sh` en el host + cron diario:
```
0 3 * * * /ruta/repo/backend/scripts/backup_user_db.sh >> /var/log/btt_userdb_backup.log 2>&1
```
(Por defecto respalda `/data/btt_userdb/users.duckdb`, 14 generaciones, fichero + `.wal`.)

### Paso 3 — [TÚ · Coolify UI] Añadir el File Mount en la app de PROD
Storages → **+ Add → File Mount**:
- **Source Path (host):** `/data/btt_userdb/users.duckdb`
- **Destination Path (container):** `/app/users.duckdb`
- Guardar. **Redeploy.**

> Estado intermedio SEGURO: fichero persistente **+ GCS aún ON** (sigue respaldando). Verificar aquí.

### Paso 4 — [YO · SSH] Verificar persistencia
- El mount aparece en `docker inspect` del contenedor prod.
- Guardar una estrategia → **redeploy** → el fichero (y la estrategia) **sobreviven**.

### Paso 5 — [TÚ · Coolify UI] Apagar el sync a GCS
Environment Variables → añadir `DISABLE_GCS_SYNC=true` → **Redeploy**.
→ Se acaban subidas/descargas. **El timeout desaparece.** GCS queda **congelado** (no se borra).

### Paso 6 — [YO · SSH] Verificación final
- Bajo guardados, `/strategies/` responde **< 1 s** (hoy > 20 s).
- El fichero persiste tras redeploy; el backup cron genera su primera copia.

## Rollback
Quitar el env `DISABLE_GCS_SYNC` (vuelve el ciclo GCS) y, si hiciera falta, el File Mount
(vuelve efímero + GCS). El bucket GCS sigue intacto (congelado) → se recupera el estado previo.
Los backups locales quedan como red extra.

## Qué NO toca
El lago GCS (`cold_storage`), los backtests, el motor. Solo la **persistencia de users.duckdb**.

## Siguiente (Fase 2)
Sacar `dataset_pairs` (31 M filas, regenerable vía `_populate_dataset_pairs`; el orquestador ya
la repuebla on-demand) a un almacén aparte → `users.duckdb` baja a pocos MB → backups/checkpoints
instantáneos. Ya no es urgente (con Fase 1 el tamaño no causa el timeout); es higiene.
