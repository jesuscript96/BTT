# Guía de trabajo — Entorno de desarrollo (BTT)

> **Para quién es esto:** este documento es para la **IA de desarrollo** (Claude Code / Cursor / Copilot Agent…) que va a programar sobre este repo mientras el equipo trabaja en modo `develop`.
> **Léelo entero antes de tocar nada.** Contiene reglas que **NO se pueden saltar**.
>
> 💡 Si tu herramienta lee automáticamente un archivo de instrucciones del repo (`AGENTS.md`, `CLAUDE.md`, `.cursorrules`), **copia este contenido ahí** para que se cargue solo en cada sesión.

---

## 0. TL;DR — Las 5 reglas de oro (si solo lees esto, que sea esto)

1. **JAMÁS se toca `main`.** No se hace commit, ni push, ni PR, ni merge hacia `main`. `main` = **producción real con clientes de pago**.
2. **Todo el trabajo va a `develop`.** Se crea una **rama propia** a partir de `develop`, se trabaja siempre sobre ella, y se integra a `develop` mediante Pull Request.
3. **En local, `DISABLE_GCS_SYNC=true` SIEMPRE.** Sin esto, tu instancia local puede **sobrescribir la base de datos de usuarios de producción** en la nube. Es el error más caro posible. Ver §5.
4. **En local, `LIVE_SCREENER_ENABLED=false` SIEMPRE.** Si no, tu local pelea con producción por la conexión de datos en vivo y **degrada el servicio real**. Ver §5.
5. **Nunca commitees secretos** ni datos: `.env`, `.env.local`, `gcs-key.json`, `users.duckdb`, `data/`, `.cache/`. Ya están en `.gitignore`; no los fuerces.

---

## 1. Los tres entornos

| Entorno | Rama | Dónde vive | Quién despliega | Datos |
|---|---|---|---|---|
| **Local** | tu rama (`feat/…`) | tu máquina | tú (manual) | lee datos reales de la nube (solo lectura), DB de usuarios **aislada** |
| **Staging / Dev** | `develop` | servidor del equipo (auto-deploy) | automático al hacer push a `develop` | datos reales, aislado de prod |
| **Producción** | `main` | servidor del equipo + Vercel | automático al hacer merge a `main` | **REAL. No se toca.** |

**Flujo completo:** `tu rama → PR a develop → auto-deploy a staging → validar en staging → (Adrian) merge develop→main`.

Tú te ocupas **solo de la parte izquierda**: tu rama y el PR a `develop`. El paso a `main` lo hace Adrian, no tú.

---

## 2. Arquitectura del proyecto (contexto mínimo)

```
BTT/
├── backend/     # API en Python (FastAPI) — la lógica, backtests, datos
├── frontend/    # App en Next.js 16 + TypeScript — la interfaz
├── docs/        # Documentación (esto)
└── data/        # Datos locales (gitignored, no se sube)
```

- **Backend:** FastAPI + Python. Motor de backtests, ingesta y lectura de datos de mercado (DuckDB embebido).
- **Frontend:** Next.js 16 + React 19 + Tailwind. Auth con Clerk.
- **Datos de mercado:** se leen bajo demanda desde almacenamiento en la nube (GCS) y se cachean en disco local. **No necesitas descargar el histórico completo** para desarrollar.
- **Base de datos de usuarios** (`users.duckdb`): estrategias guardadas, queries, datasets. En local usas **una copia propia y aislada** (ver §5).

---

## 3. Requisitos previos (instala esto una vez)

| Herramienta | Versión | Para qué |
|---|---|---|
| **Git** | cualquiera reciente | control de versiones |
| **Python** | 3.12+ (prod usa 3.14) | backend |
| **Node.js** | 20+ | frontend |
| **npm** | el que trae Node | dependencias frontend |

Comprueba:
```bash
git --version
python --version   # o py --version en Windows
node --version
```

**Acceso al repo (privado):** `jesuscript96/BTT` es **privado**. Pide a Adrian/Jesús que te **inviten como colaborador** en GitHub y autentícate. Lo más simple:
```bash
# opción recomendada: GitHub CLI
gh auth login        # elige GitHub.com → HTTPS → login por navegador
```
(Alternativa: clonar por HTTPS y usar un Personal Access Token como contraseña, o configurar una clave SSH.)

---

## 4. Bajar el repo y montar el environment

### 4.1 Clonar el repo

Colócate en la carpeta donde guardas tus proyectos y clona:

```bash
git clone https://github.com/jesuscript96/BTT.git
cd BTT
```

Sitúate en la base de la que parte el desarrollo (`develop`):

```bash
git checkout develop
git pull origin develop
```

> Aún **no** crees tu rama de trabajo aquí; eso es la §7. Primero deja el proyecto funcionando en local.

### 4.2 Colocar el "environment" que te pasa Adrian (probablemente en tu carpeta de Descargas)

Adrian te pasa **3 archivos con secretos** por canal privado. **No están en el repo** (están en `.gitignore`) y **nunca se commitean**. Normalmente te llegan a **`Downloads`** con estos nombres:

| Te llega como… | Va colocado en… | Qué es |
|---|---|---|
| `backend.env` | `backend/.env` | claves de API, credenciales de datos, config del backend |
| `frontend.env.local` | `frontend/.env.local` | URL del backend + claves de Clerk (test) |
| `gcs-key.json` | `backend/gcs-key.json` | credencial para leer los datos de mercado en la nube |

Muévelos y renómbralos (desde la raíz del repo `BTT/`):

**Windows (PowerShell):**
```powershell
$dl = "$HOME\Downloads"          # ajusta si tu carpeta de descargas es otra
Copy-Item "$dl\backend.env"        ".\backend\.env"
Copy-Item "$dl\frontend.env.local" ".\frontend\.env.local"
Copy-Item "$dl\gcs-key.json"       ".\backend\gcs-key.json"
```

**macOS / Linux:**
```bash
dl="$HOME/Downloads"             # ajusta si tu carpeta de descargas es otra
cp "$dl/backend.env"        backend/.env
cp "$dl/frontend.env.local" frontend/.env.local
cp "$dl/gcs-key.json"       backend/gcs-key.json
```

> ⚠️ Ojo con los nombres: el fichero del backend debe quedar como **`backend/.env`** (con punto delante, sin `.env` duplicado) y el del frontend como **`frontend/.env.local`**.
> ⚠️ **Nunca** hagas `git add` de estos archivos ni los pegues en un commit, PR, issue o chat. Si `git status` los muestra como "untracked", **déjalos así** — están correctamente ignorados.

### 4.3 Verifica los seguros de local en `backend/.env`

El `backend/.env` que te pasa Adrian **ya viene** con estas dos líneas (son los seguros de aislamiento de §5, **no** son secretas). Confirma que están y que valen exactamente así:

```dotenv
DISABLE_GCS_SYNC=true
LIVE_SCREENER_ENABLED=false
```

El resto de variables (`MASSIVE_API_KEY`, `GCS_*`, `CLERK_*`, `REDIS_URL`, etc.) vienen con los valores correctos. **No las cambies.** (`REDIS_URL` llega **vacío** a propósito, para no chocar con producción.)

### 4.4 Verifica la URL del backend en `frontend/.env.local`

Debe apuntar a tu backend local (puerto **8010**):
```dotenv
NEXT_PUBLIC_API_URL=http://localhost:8010
```
(El frontend añade `/api` por su cuenta; no lo pongas tú.)

---

## 5. Por qué esas dos variables son sagradas (léelo, no las quites)

Este proyecto lee y escribe en almacenamiento **compartido con producción**. Dos mecanismos pueden hacer daño real desde tu máquina local:

### `DISABLE_GCS_SYNC=true` — protege la base de datos de usuarios
Con `DB_PROVIDER=gcs`, al arrancar el backend **descarga** `users.duckdb` de la nube y, al guardar o apagar, lo **vuelve a subir**. Si dejas esto activo en local:
- tu instancia subiría **tu** `users.duckdb` local encima del de **producción**,
- borrando estrategias y datos de **usuarios reales de pago**.

Con `DISABLE_GCS_SYNC=true` no baja ni sube nada: trabajas con una `users.duckdb` **local y aislada**. (Verificado en código: `backend/app/gcs_sync.py:123` y `:171`.)

> La primera vez arrancará con una `users.duckdb` local vacía (o la semilla que te pase Adrian). Es normal: creas tus propias estrategias de prueba. Los **datos de mercado** (velas) sí son reales — se leen de la nube en **solo lectura**.

### `LIVE_SCREENER_ENABLED=false` — no pelees con producción
El proveedor de datos en vivo (Massive/Polygon) admite **una sola conexión por clave**. Si tu local abre el screener en vivo con la misma clave que prod, ambos se pelean (error `1008` en bucle) y **degradas el screener en vivo de producción**. En local **no lo necesitas**: déjalo en `false`. (Verificado en `backend/app/services/live_screener_service.py:152`.)

---

## 6. Arrancar en local (paso a paso)

> **Atajo (Windows):** `arrancar_local.bat` en la raíz del repo hace todo esto de un golpe:
> valida los seguros de `backend/.env` (§5) y aborta si faltan, prepara venv/dependencias
> si no existen, arranca backend (:8010) y frontend (:3000) en ventanas separadas —para ver
> el log `DISABLE_GCS_SYNC=true`—, espera el `/health` y abre `http://localhost:3000`.
> Si ya hay algo escuchando en esos puertos, lo detecta y no lo duplica.
> Para pararlo todo: `parar_local.bat`.

Necesitas **dos terminales**: una para el backend, otra para el frontend.

### 6.1 Backend (terminal 1)

**Windows (PowerShell):**
```powershell
cd backend
python -m venv .venv                 # solo la 1ª vez
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt      # solo la 1ª vez o si cambian deps
# (coloca aquí backend\.env y backend\gcs-key.json — ver §4)
uvicorn app.main:app --reload --host 0.0.0.0 --port 8010
```

**macOS / Linux:**
```bash
cd backend
python3 -m venv .venv                # solo la 1ª vez
source .venv/bin/activate
pip install -r requirements.txt      # solo la 1ª vez o si cambian deps
# (coloca aquí backend/.env y backend/gcs-key.json — ver §4)
uvicorn app.main:app --reload --host 0.0.0.0 --port 8010
```

Backend listo cuando veas el log de Uvicorn en `http://0.0.0.0:8010` **y** este mensaje de seguridad:
```
[INFO] GCS sync disabled by environment variable (DISABLE_GCS_SYNC=true).
```
Si **no** ves ese mensaje, **para el servidor**: te falta `DISABLE_GCS_SYNC=true`. No sigas.

Prueba rápida: abre `http://localhost:8010/health` → debe responder OK.

### 6.2 Frontend (terminal 2)

```bash
cd frontend
npm install        # solo la 1ª vez o si cambia package.json
# (coloca aquí frontend/.env.local — ver §4)
npm run dev
```

Abre **http://localhost:3000**. La app debe cargar y hablar con tu backend local (8010).

---

## 7. Flujo de trabajo con Git (esto es lo importante)

### 7.1 Tu rama de trabajo (una vez, al empezar)

El equipo trabaja con **una rama personal persistente por desarrollador** (p. ej. `jaumen-rama-desarrollo`, `adrian-garcia-develop`). La tuya es:

```
alvaro-rama-desarrollo
```

**Trabajas SIEMPRE sobre ella.** Créala a partir de `develop` actualizado (si aún no existe en remoto):

```bash
git checkout develop
git pull origin develop

git checkout -b alvaro-rama-desarrollo      # si ya existe: git checkout alvaro-rama-desarrollo
git push -u origin alvaro-rama-desarrollo   # súbela para que exista en remoto desde el minuto 1
```

### 7.2 Ciclo diario (mientras programas)

```bash
git branch --show-current    # verifica que estás en alvaro-rama-desarrollo
git add -A
git commit -m "feat: descripción clara de qué cambiaste"
git push                     # sube a TU rama (alvaro-rama-desarrollo)
```

Trabaja **siempre sobre `alvaro-rama-desarrollo`**. No hagas commit en `develop` ni en `main`.
**Antes de cada `push`, confirma con Adrian** (regla del equipo: se pregunta antes de subir).

### 7.3 Integrar tu trabajo → PR a `develop` (NUNCA a `main`)

Cuando tengas algo listo para revisar:

1. Ve a GitHub → repo `jesuscript96/BTT`.
2. Abre un **Pull Request**.
3. **Base branch: `develop`.** ← revisa esto SIEMPRE. Debe decir `develop`, **jamás `main`**.
4. Compare branch: `alvaro-rama-desarrollo`.
5. Describe qué cambiaste y por qué. Pide revisión.

Al hacer merge del PR a `develop`, se **auto-despliega a staging** y ahí se valida. El salto de `develop` a `main` (producción) lo decide y ejecuta **Adrian**, no tú.

### 7.4 Mantener tu rama al día (si `develop` avanza)

```bash
git checkout develop
git pull origin develop
git checkout alvaro-rama-desarrollo
git merge develop          # trae los cambios de develop a tu rama
# resuelve conflictos si los hay, luego:
git push
```

---

## 8. Lo que NUNCA debes hacer (checklist rojo)

- ❌ `git checkout main`, `git commit` en `main`, `git push origin main`, PR con base `main`.
- ❌ Quitar o poner en `false`/comentar `DISABLE_GCS_SYNC=true` en local.
- ❌ Poner `LIVE_SCREENER_ENABLED=true` en local (o borrarlo).
- ❌ `git add` de `backend/.env`, `frontend/.env.local`, `backend/gcs-key.json`, `users.duckdb`, `data/`, `.cache/`, `.venv/`, `node_modules/`.
- ❌ Pegar claves/secretos en commits, PRs, issues o chats.
- ❌ Cambiar variables de entorno "de producción" (claves GCS/Massive/Clerk) sin acordarlo con Adrian.
- ❌ Rotar/regenerar claves por tu cuenta.

## 9. Lo que SÍ debes hacer

- ✅ Partir siempre de `develop` actualizado y trabajar en tu rama.
- ✅ Verificar el log `DISABLE_GCS_SYNC=true` en cada arranque del backend.
- ✅ Commits pequeños y descriptivos, push frecuente a tu rama.
- ✅ Abrir PR **a `develop`** y validar en staging.
- ✅ Ante la duda sobre datos, entorno o si algo puede afectar a prod: **pregunta a Adrian antes de ejecutar.**

---

## 10. Smoke test — comprobar que todo va bien

1. Backend arranca en `:8010` y loguea `DISABLE_GCS_SYNC=true`. ✅
2. `http://localhost:8010/health` responde OK. ✅
3. Frontend arranca en `:3000` y carga la interfaz. ✅
4. La app hace peticiones al backend local (mira la pestaña Network → van a `localhost:8010`). ✅
5. Un backtest de prueba corre y devuelve resultados (lee datos reales de la nube en solo lectura). ✅
6. `git status`: `.env`, `.env.local`, `gcs-key.json` aparecen como ignorados/no rastreados (no en el commit). ✅

---

## 11. Problemas comunes

| Síntoma | Causa probable | Solución |
|---|---|---|
| Backend no ve el mensaje `DISABLE_GCS_SYNC=true` | falta la variable en `backend/.env` | añádela y reinicia. **No sigas sin ella.** |
| `nixpacks`/build falla o "no detecta app" | (solo en servidor) directorio base | el backend vive en `backend/`; en local no aplica |
| Error 1008 / screener en bucle | `LIVE_SCREENER_ENABLED` no está en `false` | ponlo en `false` y reinicia |
| Frontend no habla con el backend | `NEXT_PUBLIC_API_URL` mal | debe ser `http://localhost:8010` (sin `/api`) |
| `ModuleNotFoundError` en backend | venv no activado o faltan deps | activa `.venv` y `pip install -r requirements.txt` |
| Faltan datos / errores de auth GCS | falta `backend/gcs-key.json` o claves en `.env` | pídeselos a Adrian; colócalos como en §4 |
| Auth de Clerk falla en frontend | faltan claves en `frontend/.env.local` | usa las de test que pasa Adrian |

---

## 12. Resumen en una frase

**Trabaja en tu rama a partir de `develop`, arranca en local con `DISABLE_GCS_SYNC=true` y `LIVE_SCREENER_ENABLED=false`, integra por PR a `develop` (nunca a `main`), y no commitees secretos.**

> Cualquier duda que implique tocar datos, entornos o algo que pueda llegar a producción: **pregunta a Adrian antes de ejecutarlo.**
