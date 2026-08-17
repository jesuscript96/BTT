# CLAUDE.md

Este repo (BTT) usa **`AGENTS.md`** como fuente única de reglas para agentes de
IA (Claude Code, GLM, Antigravity…). Léelo entero antes de tocar nada:

@AGENTS.md

## Lo más importante que no se salta

- **JAMÁS se toca `main`** (producción con clientes de pago).
- La **rama de trabajo depende del desarrollador** — ver "Reglas por
  desarrollador" en `AGENTS.md`:
  - **Álvaro** y **Sailor** → rama conjunta **`staging`**. Todos los commits van
    ahí (`.agent/ALVARO_DEV_BRANCH.md` / `.agent/SAILOR_DEV_BRANCH.md`).
  - Antes de trabajar: `git pull origin staging` (rama compartida).
  - Antes de cada `push`: pedir confirmación explícita al usuario.
- **Nunca commitear** secretos ni datos (`.env`, `gcs-key.json`, `*.duckdb*`,
  `data/`, `.cache/`).
