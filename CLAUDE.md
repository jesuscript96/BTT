# CLAUDE.md

Este repo (BTT) usa **`AGENTS.md`** como fuente única de reglas para agentes de
IA (Claude Code, GLM, Antigravity…). Léelo entero antes de tocar nada:

@AGENTS.md

## Lo más importante que no se salta

- **JAMÁS se toca `main`** (producción con clientes de pago).
- La **rama de trabajo depende del desarrollador** — ver "Reglas por
  desarrollador" en `AGENTS.md`:
  - **Álvaro** → `alvaro-rama-desarrollo`, **Sailor** → `sailor-rama-desarrollo`.
    Cada uno commitea en SU rama e integra a la conjunta **`staging`**
    (`.agent/ALVARO_DEV_BRANCH.md` / `.agent/SAILOR_DEV_BRANCH.md`).
  - Antes de trabajar: traer la conjunta con `git fetch && git merge origin/staging`.
  - Antes de cada `push`: pedir confirmación explícita al usuario.
- **Nunca commitear** secretos ni datos (`.env`, `gcs-key.json`, `*.duckdb*`,
  `data/`, `.cache/`).

## Si el desarrollador es Sailor — leer también

@.agent/SAILOR_LOCAL_SETUP.md

Este equipo tiene un **lago de datos propio en `D:`** y **16 GB de RAM**, no los
128 GB del servidor. Varios defaults del repo (guard de memoria, prewarm,
límites de DuckDB, `MIN_AVAILABLE_DATE`) están **sobrescritos en `backend/.env`
por motivos medidos**, y hay 2 cambios en `data_service.py` sin commitear. Ese
documento explica el porqué de cada uno y los números que lo justifican.
**No revertir ni "limpiar" nada de eso sin leerlo antes.**
