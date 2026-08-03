# Git Branch Rules — Álvaro

Aplica cuando el desarrollador es Álvaro.

## Rama de trabajo
Siempre trabajar en: `alvaro-rama-desarrollo`

## Prohibido
- Push a `develop`
- Push a `main`
- Merge a `develop` o `main`
- Commit en `develop` o `main`

## Flujo obligatorio
1. `git branch --show-current` — verificar rama actual
2. Si no está en `alvaro-rama-desarrollo`: `git checkout alvaro-rama-desarrollo`
   (si no existe aún: `git checkout develop && git pull origin develop && git checkout -b alvaro-rama-desarrollo`)
3. Hacer cambios y commit normalmente
4. Antes de push, preguntar al usuario: "¿Confirmas push a alvaro-rama-desarrollo?"
5. Solo tras confirmación explícita: `git push origin alvaro-rama-desarrollo`

## Integración a develop
- Los cambios llegan a `develop` **solo por Pull Request** (base: `develop`, compare: `alvaro-rama-desarrollo`).
- El salto de `develop` a `main` lo hace **Adrian**, nunca la IA.

## Nunca ejecutar sin confirmación
- `git push origin develop`
- `git push origin main`
- `git merge develop`
- `git merge main`

## Seguridad en local (imprescindible)
- `backend/.env` debe tener `DISABLE_GCS_SYNC=true` y `LIVE_SCREENER_ENABLED=false`.
- Nunca commitear `.env`, `.env.local`, `gcs-key.json`, `*.duckdb`, `data/`, `.cache/`.
- Guía completa: `docs/GUIA_DEV_LOCAL_Y_DEVELOP_PARA_IA.md`.
