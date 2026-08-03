# AGENTS.md — Reglas para agentes de IA en este repo (BTT)

> Este archivo lo cargan automáticamente los IDEs/agentes de IA (Antigravity, Cursor, Claude Code…).
> **Léelo entero antes de tocar el repo.** Contiene reglas que NO se pueden saltar.

## 🔴 Reglas de oro (universales)

1. **JAMÁS se toca `main`.** Nada de commit, push, PR base `main` ni merge a `main`. `main` = producción real con clientes de pago.
2. **Cada desarrollador trabaja en su rama personal** e integra a `develop` **solo por Pull Request**. El salto `develop → main` lo hace Adrian, nunca la IA.
3. **Antes de cada `push`, pídele confirmación explícita al usuario.**
4. **Nunca commitees secretos ni datos:** `.env`, `.env.local`, `gcs-key.json`, `*.duckdb`, `data/`, `.cache/`, `.venv/`, `node_modules/`. Ya están en `.gitignore`; no los fuerces.
5. **Antes de modificar un archivo, léelo completo.** Un paso a la vez; confirma antes de continuar. No borres código: muévelo a `_archive/`.

## 🔒 Seguridad en desarrollo local (imprescindible)

Este proyecto lee/escribe en almacenamiento **compartido con producción**. En local, `backend/.env` DEBE tener:

```dotenv
DISABLE_GCS_SYNC=true        # si no, tu local puede SOBRESCRIBIR la BD de usuarios de PROD
LIVE_SCREENER_ENABLED=false  # si no, peleas la conexión en vivo y DEGRADAS el screener de PROD
```

Si al arrancar el backend **no** ves el log `GCS sync disabled by environment variable (DISABLE_GCS_SYNC=true)`, **para el servidor**: falta la variable. El porqué está en `docs/GUIA_DEV_LOCAL_Y_DEVELOP_PARA_IA.md` §5.

## 👤 Reglas por desarrollador (rama + flujo)

Aplica el archivo que corresponda al usuario actual:

- **Álvaro** → `.agent/ALVARO_DEV_BRANCH.md` (rama `alvaro-rama-desarrollo`)
- **Jaume** → `.agent/JAUME_DEV_BRANCH.md` (rama `jaumen-rama-desarrollo`)

## 📚 Contexto del proyecto (lee según necesites)

- **Onboarding / arrancar en local / flujo git completo:** `docs/GUIA_DEV_LOCAL_Y_DEVELOP_PARA_IA.md` ← empieza aquí
- **Arquitectura:** `.agent/ARCHITECTURE.md`
- **Lógica de negocio:** `.agent/BUSINESS_LOGIC.md`
- **Reglas de código (backend/frontend/BD):** `.agent/CODING_RULES.md`
- **Sistema de diseño:** `.agent/EDGECUTE_DESIGN_SYSTEM.md`
- **Contexto general:** `.agent/PROJECT_CONTEXT.md`

## 🧭 Reglas de código (resumen — detalle en `.agent/CODING_RULES.md`)

- **Backend:** routers solo endpoints + Pydantic; la lógica va en `services/`. Env siempre por `os.getenv()`, nunca hardcodeada. Cambios en `backtester/` requieren verificar el JIT de Numba.
- **Frontend:** fetch centralizado en `lib/api.ts`; nunca hardcodear URLs, usar `NEXT_PUBLIC_API_URL`.
- **BD:** queries parametrizadas con `?`, nunca concatenación. No tocar el schema de `daily_metrics`/`intraday_1m` ni el Parquet de GCS sin consenso.

## ✅ Al empezar cada sesión

1. `git branch --show-current` → confirma que estás en tu rama personal (no `develop`/`main`).
2. Comprueba que el backend loguea `DISABLE_GCS_SYNC=true`.
3. Ante cualquier duda que implique datos, entornos o algo que pueda llegar a producción: **pregunta antes de ejecutar.**
