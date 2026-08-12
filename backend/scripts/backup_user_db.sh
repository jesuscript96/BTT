#!/usr/bin/env bash
#
# Backup rotado de users.duckdb — se ejecuta en el HOST via cron (NO dentro del
# contenedor). Necesario cuando users.duckdb vive en disco persistente y el sync
# a GCS esta apagado (DISABLE_GCS_SYNC=true): GCS ya no es el respaldo, asi que
# este cron es la unica copia de seguridad. Ver docs/RUNBOOK_USERDB_LOCAL_PERSIST.md
#
# Copia el fichero principal + su .wal (si existe) juntos, para que un snapshot
# tomado a mitad de una escritura siga siendo recuperable (DuckDB reproduce el WAL
# al abrir). Se guardan las ultimas N generaciones; una copia rota nunca es fatal
# porque queda la anterior buena.
#
# Instalar (en el host):
#   crontab -e
#   0 3 * * * /ruta/al/repo/backend/scripts/backup_user_db.sh >> /var/log/btt_userdb_backup.log 2>&1
#
set -euo pipefail

SRC_DIR="${USER_DB_DIR:-/data/btt_userdb}"
SRC="$SRC_DIR/users.duckdb"
DEST_DIR="${USER_DB_BACKUP_DIR:-/data/btt_userdb_backups}"
KEEP="${USER_DB_BACKUP_KEEP:-14}"

mkdir -p "$DEST_DIR"

if [ ! -f "$SRC" ]; then
    echo "[backup] $(date -u +%FT%TZ) sin origen en $SRC — nada que copiar"
    exit 0
fi

TS="$(date -u +%Y%m%d_%H%M%S)"
SNAP="$DEST_DIR/users_${TS}.duckdb"

cp -f "$SRC" "$SNAP"
if [ -f "$SRC.wal" ]; then
    cp -f "$SRC.wal" "$SNAP.wal"
fi

# Rotacion: conservar solo las KEEP mas recientes (borrando su .wal asociado)
ls -1t "$DEST_DIR"/users_*.duckdb 2>/dev/null | tail -n +"$((KEEP + 1))" | while read -r old; do
    rm -f "$old" "$old.wal"
done

echo "[backup] $(date -u +%FT%TZ) OK -> $SNAP ($(du -h "$SNAP" | cut -f1)); generaciones: $(ls -1 "$DEST_DIR"/users_*.duckdb 2>/dev/null | wc -l)"
