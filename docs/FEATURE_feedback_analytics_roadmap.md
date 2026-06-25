# Feature: Analítica (PostHog) + Feedback/Votación + Popup de novedades

Documentación de lo implementado en la rama `nextux-jesus`.
Resumen de diseño/decisiones: ver `plan_analytics_feedback_roadmap.md`.

---

## 1. Qué se ha construido

1. **Analítica PostHog arreglada** — ahora los eventos se vinculan al usuario de Clerk
   (antes todo era anónimo), con reverse-proxy anti-adblock y una taxonomía de eventos
   centralizada e instrumentada en los submódulos clave.
2. **Widget de Feedback / votación de roadmap** (NO es una página) — botón "Feedback" en la
   barra lateral abre un modal con una **lista de respuesta única**; al votar se ven los
   **más votados**. Incluye un campo libre ("Otra cosa…") para *"¿Qué echas de menos en
   Edgecute?"*. **Un voto por release**, todos los votos valen igual.
3. **Popup de novedades** — al entrar, una sola vez por release y por usuario, con un
   `releases.ts` que se actualiza añadiendo una línea.

---

## 2. Archivos

### Backend
| Archivo | Cambio |
|---|---|
| `backend/app/routers/feedback.py` | **Nuevo.** Endpoints del board de votación + sugerencias. |
| `backend/app/init_db.py` | Tablas `feature_options`, `feature_votes`, `feature_suggestions` + seed de opciones placeholder. |
| `backend/app/main.py` | Registra el router (`include_router(feedback.router)`). |

### Frontend
| Archivo | Cambio |
|---|---|
| `frontend/src/components/PostHogIdentify.tsx` | **Nuevo.** `identify()` con el user de Clerk + `reset()` al salir. |
| `frontend/src/app/providers.tsx` | `person_profiles:'identified_only'` + `api_host:'/ingest'`. |
| `frontend/next.config.ts` | Reverse-proxy `/ingest` → PostHog. |
| `frontend/src/app/layout.tsx` | Monta `<PostHogIdentify/>`. |
| `frontend/src/lib/analytics.ts` | **Nuevo.** Taxonomía `EVENTS` + helper `track()`. |
| `frontend/src/lib/api.ts` | `track()` en `runBacktest`, `createStrategy`, `createQuery`, `searchStrategies`. |
| `frontend/src/components/FeedbackWidget.tsx` | **Nuevo.** Modal de votación + resultados + texto libre. |
| `frontend/src/lib/api_feedback.ts` | **Nuevo.** Cliente del board (`getFeedbackBoard`, `voteFeature`, `sendSuggestion`). |
| `frontend/src/components/WhatsNewModal.tsx` | **Nuevo.** Popup de novedades. |
| `frontend/src/data/releases.ts` | **Nuevo.** Feed de releases (fuente única). |
| `frontend/src/components/LayoutShell.tsx` | Monta `FeedbackWidget` + `WhatsNewModal`; pasa `onOpenFeedback` al Sidebar. |
| `frontend/src/components/Sidebar.tsx` | Botón "Feedback" que abre el modal. |

---

## 3. Analítica (PostHog)

- **Identidad:** `PostHogIdentify` llama a `posthog.identify(user.id, {email, name, tier})`
  cuando carga el usuario de Clerk, y a `posthog.reset()` al cerrar sesión. Sin esto los
  eventos eran anónimos y no se podía analizar el uso por usuario.
- **Anti-adblock:** `next.config.ts` reescribe `/ingest/*` → `us(-assets).i.posthog.com`, y
  `providers.tsx` usa `api_host:'/ingest'`. Los eventos salen desde tu dominio.
- **Perfiles:** `person_profiles:'identified_only'` para no inflar MAU con anónimos.
- **Eventos nombrados:** todos en `lib/analytics.ts` (`EVENTS`). Instrumentados:
  `backtest_run`, `strategy_created`, `dataset_created`, `strategy_search_run`,
  y desde el widget `roadmap_voted`, `feedback_submitted`, `whatsnew_viewed`.
  Para añadir eventos: añade la constante en `EVENTS` y llama `track(EVENTS.X, {...})`.

---

## 4. Feedback / votación

### Modelo de datos (DuckDB, en `users.duckdb`)
- `feature_options(id, label, description, sort_order, archived, created_at)` — las opciones.
- `feature_votes(round_id, user_id, option_id, created_at, PK(round_id,user_id))`
  → **un voto por usuario por release**; revotar es un upsert.
- `feature_suggestions(id, user_id, message, round_id, created_at)` — texto libre.

### Endpoints (`/api/feedback`)
| Método | Ruta | Descripción |
|---|---|---|
| GET | `/board?user_id=...` | Opciones ordenadas por votos (desc) + `my_vote` + `total_votes`. |
| POST | `/vote` `{option_id, user_id}` | Vota/cambia el voto del usuario en la ronda actual. |
| POST | `/suggestion` `{text, user_id}` | Guarda texto libre. |
| GET | `/suggestions?limit=200` | Lista las sugerencias (para revisión del equipo). |

### "Un voto por release"
La ronda activa la define `FEATURE_VOTE_ROUND` (env del backend, por defecto `r1`).
**Cuando subáis algo nuevo, cambiad ese valor** (`r2`, `r3`, …) para reabrir la votación:
cada usuario vuelve a tener un voto. El histórico de votos anteriores se conserva por ronda.

### Dedup de votos sin auth de backend
El backend **no verifica** el token de Clerk (la app corre Clerk *keyless* y el backend no
tiene config de Clerk). El frontend envía el `user.id` de Clerk y se usa solo para
deduplicar el voto. Es suficiente para una encuesta de features (bajo riesgo). Si en el
futuro queréis verificación real, añadid las llaves de Clerk al backend (ver §6).

---

## 5. Popup de novedades

- Fuente única: `frontend/src/data/releases.ts`. La entrada `RELEASES[0]` es la más reciente.
- Se muestra solo si `LATEST_RELEASE.id` ≠ `user.unsafeMetadata.lastSeenReleaseId`.
- El "visto" se guarda en **Clerk `unsafeMetadata`** (por usuario, sobrevive a sesiones y
  dispositivos) → **no se muestra cada vez**, solo cuando hay un release nuevo.
- **Para anunciar algo nuevo:** añade una entrada al principio de `RELEASES` con un `id`
  nuevo. (Opcional: `requestedByYou: true` muestra el badge "Lo pedisteis vosotros".)

---

## 6. Puesta en marcha / operación

1. **Reiniciar el backend** una vez tras desplegar → `init_db` crea las tablas nuevas.
2. **Editar las opciones placeholder** de `feature_options` con las funcionalidades reales
   del roadmap (en la DB; el seed solo inserta si la tabla está vacía).
3. **Editar `releases.ts`** con el contenido real del primer anuncio.
4. **`NEXT_PUBLIC_POSTHOG_KEY`** debe estar también en el entorno de **producción (Vercel)**.
5. Para reabrir votación por release: cambiar `FEATURE_VOTE_ROUND` en el backend.
6. (Opcional, futuro) Activar verificación de auth en backend: añadir `CLERK_PUBLISHABLE_KEY`
   o `CLERK_ISSUER` y `CLERK_AUTH_ENABLED=true`. **No activar `CLERK_AUTH_ENABLED` sin esas
   llaves**, o `verify_clerk_token` devolverá 500.

---

## 7. Verificación realizada

- `tsc --noEmit` del frontend: **sin errores**.
- `py_compile` de los archivos backend: **OK**.
- Lógica SQL probada en DuckDB: un voto por usuario/ronda, revoto = upsert, rondas aisladas,
  board agregado correctamente.
