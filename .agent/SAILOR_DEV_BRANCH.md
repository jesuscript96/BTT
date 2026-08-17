# Git Branch Rules — Sailor

Aplica cuando el desarrollador es Sailor.

## Rama de trabajo — `staging` (conjunta Álvaro + Sailor)

**Todos los commits van a `staging`.** Es el entorno de desarrollo compartido
entre Sailor y Álvaro: así los dos están siempre en la misma versión sin tocar
`main`. Desde `staging` se decide, cuando queramos, qué se promociona.

> (Opcional) Para experimentar en aislado sin afectar a Álvaro, usar la rama
> personal `sailor-rama-desarrollo` y luego mergearla a `staging`.

## Prohibido
- Push / commit / merge a `main`
- Push / commit / merge a `develop`

## Flujo obligatorio
1. `git branch --show-current` — verificar rama actual.
2. Si no estás en `staging`: `git checkout staging`.
3. **Antes de trabajar/commitear: `git pull origin staging`.** Es una rama
   COMPARTIDA con Álvaro — sincroniza siempre antes para no chocar en el push.
4. Hacer cambios y commit a `staging`.
5. Antes de push, preguntar al usuario: "¿Confirmas push a staging?"
6. Solo tras confirmación explícita: `git push origin staging`.

## Promoción (staging → producción)
- Lo que sea útil para el usuario final se promociona desde `staging` **solo por
  Pull Request**, nunca tocando `main` directamente.
- El salto final a `main` lo hace **Adrian**, nunca la IA.

## Nunca ejecutar sin confirmación
- `git push origin main` / `git push origin develop`
- `git merge main` / `git merge develop`

## Seguridad en local (imprescindible)
- `backend/.env` debe tener `DISABLE_GCS_SYNC=true` y `LIVE_SCREENER_ENABLED=false`.
- Nunca commitear `.env`, `.env.local`, `gcs-key.json`, `*.duckdb*`, `data/`, `.cache/`.
- Guía completa: `docs/GUIA_DEV_LOCAL_Y_DEVELOP_PARA_IA.md`.
