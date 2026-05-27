# Git Branch Rules — Jaume (jaimefh90@gmail.com)

Aplica SOLO cuando el usuario es Jaume (jaimefh90@gmail.com).

## Rama de trabajo
Siempre trabajar en: `jaumen-rama-desarrollo`

## Prohibido
- Push a `develop`
- Push a `main`
- Merge a `develop` o `main`

## Flujo obligatorio
1. `git branch --show-current` — verificar rama actual
2. Si no está en `jaumen-rama-desarrollo`: `git checkout jaumen-rama-desarrollo`
3. Hacer cambios y commit normalmente
4. Antes de push, preguntar al usuario: "¿Confirmas push a jaumen-rama-desarrollo?"
5. Solo tras confirmación explícita: `git push origin jaumen-rama-desarrollo`

## Nunca ejecutar sin confirmación
- `git push origin develop`
- `git push origin main`
- `git merge develop`
- `git merge main`
