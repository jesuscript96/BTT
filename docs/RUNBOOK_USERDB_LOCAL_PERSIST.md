# Runbook — Fase 1: users.duckdb en disco persistente (adiós al timeout de /strategies/)

**Objetivo.** Eliminar de raíz el timeout de `POST /strategies/` (20 s). Hoy `users.duckdb`
(1,15 GB) se re-sube ENTERO a GCS **dentro del lock global** tras cada guardado → el lock
queda retenido 30-50 s → los guardados esperan → el frontend corta a los 20 s.

**Enfoque (alineado con Jesús: salir de GCS hacia disco local).** Poner `users.duckdb` en un
**volumen persistente del host** y **apagar el sync a GCS**. Sin subida no hay lock retenido:
la app lee/escribe directo el fichero local durable. **El bucket de GCS se conserva CONGELADO**
como respaldo frío durante la transición (no se borra).

> Reduce el TAMAÑO del fichero es la **Fase 2** (sacar `dataset_pairs`, 31 M filas, regenerable).
> Con disco local el tamaño ya no causa el timeout, pero adelgazarlo hace el backup ligero.

---

## 1. Cambios de código (ya en esta rama)

- `backend/app/database.py`: nuevo helper `user_db_path()` → `os.getenv("USER_DB_PATH", "users.duckdb")`.
  `get_user_db_connection()` lo usa. **Todos** los accesos pasan por aquí, así que con esto basta.
- `backend/app/gcs_sync.py`: `download_user_db` / `upload_user_db` / checkpoint usan `user_db_path()`
  (la **key** de GCS `object_name` sigue siendo `"users.duckdb"`).
- `backend/scripts/backup_user_db.sh`: backup rotado (host cron).

Por defecto (`USER_DB_PATH` sin definir) el comportamiento es **idéntico al de hoy** → deploy seguro.

## 2. Infra que ya existe (verificado 2026-08-11)

- Host `176.9.117.155`: disco `/dev/md2` con **1,3 TB libres**.
- El contenedor de prod ya monta persistencia del host: `/data/btt_lake → /lake`, `/data/btt_intraday_cache`.
  Añadimos otro mount bajo `/data/` para la BD de usuarios.

## 3. Orden de CUTOVER (crítico — sin ventana sin durabilidad)

> La regla de oro: nunca dejar el fichero en ruta efímera **y** con GCS apagado a la vez.

1. **Desplegar el código** de esta rama (con `USER_DB_PATH` SIN definir aún → nada cambia).
2. **Backup cron primero:** instalar `backup_user_db.sh` en el host (cron diario) — antes de
   depender del disco local.
3. **Montar volumen + apuntar la ruta, con GCS TODAVÍA ENCENDIDO:**
   - Coolify (app prod): añadir mount `Source=/data/btt_userdb` → `Destination=/data/btt_userdb`.
   - Env: `USER_DB_PATH=/data/btt_userdb/users.duckdb`. **Dejar `DISABLE_GCS_SYNC=false` de momento.**
   - Al arrancar, `download_user_db()` **siembra solo** el fichero persistente desde GCS (baja la
     copia actual a esa ruta). Estado intermedio SEGURO: fichero persistente **+ aún respaldado por GCS**.
   - Verificar: guardar una estrategia, forzar un redeploy, comprobar que **sobrevive**.
4. **Apagar el sync:** poner `DISABLE_GCS_SYNC=true`. Se acaban subidas/descargas; la app usa el
   fichero persistente. **El timeout desaparece.** GCS queda **congelado** en su última subida.

## 4. Validación en STAGING primero

Staging ya corre con `DISABLE_GCS_SYNC=true`. Repetir allí los pasos 3-4 con su propio mount
(`/data/btt_userdb_staging`) y comprobar:
- Guardar/cargar estrategias OK; el fichero persiste tras un redeploy de staging.
- **Bajo guardados concurrentes, `/strategies/` responde < 1 s** (hoy > 20 s).
- Backtests corren y encuentran su universo (`dataset_pairs` intacto en este fichero aún).

## 5. Rollback

Revertir es quitar dos envs: `USER_DB_PATH` (vuelve a `users.duckdb` efímero) y
`DISABLE_GCS_SYNC=false` (vuelve el ciclo GCS). El bucket de GCS sigue intacto (congelado),
así que se recupera el estado anterior. Los backups locales quedan como red extra.

## 6. Qué NO toca

El lago de GCS (`cold_storage`), los backtests, el motor. Solo la **persistencia de users.duckdb**.

## 7. Siguiente (Fase 2)

Sacar `dataset_pairs` (regenerable vía `_populate_dataset_pairs`; el orquestador ya la repuebla
on-demand) a un almacén aparte → `users.duckdb` baja a pocos MB → backups y checkpoints
instantáneos. Documento aparte cuando toque.
