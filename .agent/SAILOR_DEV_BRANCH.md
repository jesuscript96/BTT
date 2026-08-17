# Git Branch Rules — Sailor

Aplica cuando el desarrollador es Sailor.

## Rama de trabajo — `sailor-rama-desarrollo`

Sailor trabaja y commitea en su rama personal **`sailor-rama-desarrollo`**.
La rama **conjunta** con Álvaro es **`staging`**: ahí se integra el trabajo de
los dos para estar sincronizados, sin tocar `main`.

## Flujo diario
1. `git branch --show-current` — verificar rama.
2. Ponerte en tu rama: `git checkout sailor-rama-desarrollo`.
3. **Traer lo último de la conjunta antes de trabajar:**
   `git fetch && git merge origin/staging` (así tienes los avances de Álvaro).
4. Hacer cambios y commit a `sailor-rama-desarrollo`.
5. Antes de push, pedir confirmación al usuario. Tras OK:
   `git push origin sailor-rama-desarrollo`.

## Compartir tu trabajo (integrar a `staging`)
Cuando tu avance esté listo para que lo tenga Álvaro:
```
git checkout staging
git pull origin staging
git merge sailor-rama-desarrollo
git push origin staging          # (tras confirmación)
```
(O por Pull Request contra `staging` si preferís revisión.)

## Prohibido
- Tocar `main` (push / commit / merge). Es producción con clientes de pago.
- Push / commit directo a `develop`.

## Seguridad en local (imprescindible)
- `backend/.env` con `DISABLE_GCS_SYNC=true` y `LIVE_SCREENER_ENABLED=false`.
- Nunca commitear `.env`, `.env.local`, `gcs-key.json`, `*.duckdb*`, `data/`, `.cache/`.
- Guía completa: `docs/GUIA_DEV_LOCAL_Y_DEVELOP_PARA_IA.md`.
