# Plan — Analítica (PostHog) + Feedback + Roadmap votable + Popup de novedades

> Objetivo de Jesús: saber **cómo usa la gente la app** (páginas vistas, interacción con
> submódulos), **recoger feedback explícito** ("¿Qué echas de menos en Edgecute para tu
> día a día?"), tener un **roadmap votable con impacto visible**, y un **popup de novedades**
> al iniciar sesión que **no se muestre cada vez** (consciente de la sesión/usuario).
> Todo debe ser **fácilmente mantenible**.

Estado del doc: **IMPLEMENTADO** (decisiones de Jesús del 2026-06-23 abajo). Ver §11 "Lo construido".

### Decisiones tomadas por Jesús (2026-06-23)
- **Roadmap (C):** NO es página nueva → **widget modal** desde la barra lateral. Feedback =
  **lista de respuesta única**; al votar se ven **los más votados**. Simple, sin estados de roadmap.
- **(1) Auth backend:** "Sí" — pero ver ⚠️ en §11: el backend **no tiene config de Clerk** y
  Clerk corre **keyless**, así que activar `CLERK_AUTH_ENABLED` ahora **rompería** la verificación.
  El widget se diseñó para **no depender** de ese flag (dedup por `user.id` que envía el frontend).
- **(2) Votos:** **un voto por release**, todos **iguales**. (`FEATURE_VOTE_ROUND` resetea por release.)
- **(3) Feedback:** lo más simple y manejable. Analítica = PostHog; "ver más votados" = mini-backend
  (PostHog no muestra resultados al usuario en la app sin plumbing extra).

---

## 0. TL;DR

| Bloque | Qué | Esfuerzo | Mantenibilidad |
|---|---|---|---|
| **A. PostHog** | Arreglar identify + proxy + eventos de submódulos | S | Alta (1 archivo de taxonomía) |
| **B. Feedback** | Widget "¿Qué echas de menos?" → DuckDB + evento PostHog | S | Alta |
| **C. Roadmap** | Página `/roadmap` votable, impacto = nº votos | M | Alta (datos en DuckDB) |
| **D. Popup novedades** | Modal post-login, 1 vez por release, por usuario | S | Muy alta (1 archivo `releases.ts`) |

Orden recomendado: **A0 (identify+proxy) primero** — desbloquea "cómo usa la gente la app"
de inmediato sin tocar producto.

---

## 1. Auditoría PostHog — estado actual

Archivos relevantes:
- `frontend/src/app/providers.tsx` — `posthog.init()`
- `frontend/src/components/PostHogPageView.tsx` — captura manual de `$pageview`
- `frontend/src/app/layout.tsx` — monta `PHProvider` + `PostHogPageView`
- `frontend/.env.local` — `NEXT_PUBLIC_POSTHOG_KEY=phc_o8oinbFh…` (key real), `…_HOST=https://us.i.posthog.com`

### Lo que está BIEN ✅
- `posthog-js` 1.391.2 instalado y proveedor montado en el layout raíz.
- Key **real** (no placeholder) y host correcto en `.env.local`.
- `capture_pageview: false` + captura manual de `$pageview` en `PostHogPageView` → es **lo correcto** para el App Router de Next 16 (evita perder navegaciones cliente).
- `capture_pageleave: true` → tiempo en página OK.
- **Autocapture activo por defecto** → ya se registran clicks/inputs genéricos.

### Problemas detectados ⚠️

| # | Severidad | Problema | Efecto |
|---|---|---|---|
| 1 | 🔴 Alta | **No se llama nunca a `posthog.identify()`** | Todos los eventos son anónimos (`device_id`). **No puedes responder "cómo usa la gente la app" por usuario** ni segmentar por tier. Es el fallo principal. |
| 2 | 🟠 Media | **Sin reverse proxy** (eventos van directos a `us.i.posthog.com`) | Adblockers/uBlock los bloquean. Con audiencia de *traders-devs* esto puede ser **20–40% de datos perdidos**. |
| 3 | 🟠 Media | **Interacción con submódulos no tiene eventos nombrados** | Autocapture registra "click en botón" pero sin semántica. No hay `backtest_run`, `screener_filter_applied`, etc. |
| 4 | 🟡 Baja | Falta confirmar la key en **producción (Vercel env)**, no solo `.env.local` | Si falta en Vercel, no hay datos en prod. (No verificable desde aquí.) |
| 5 | 🟡 Baja | `person_profiles` no configurado | Anónimos inflan MAU. Recomendado `person_profiles: 'identified_only'`. |
| 6 | 🟡 Baja | Check de init frágil: `posthog.get_property('$device_id')` | Usar `posthog.__loaded`. Menor. |

---

## 2. Bloque A — Analítica completa

### A0 · Arreglo crítico: `identify` + `reset` (vincular Clerk ↔ PostHog)

Nuevo componente cliente que, cuando carga el usuario de Clerk, lo identifica en PostHog;
y al cerrar sesión limpia la identidad.

`frontend/src/components/PostHogIdentify.tsx`:
```tsx
'use client'
import { useEffect } from 'react'
import { useUser } from '@clerk/nextjs'
import { usePostHog } from 'posthog-js/react'

export default function PostHogIdentify() {
  const { user, isLoaded } = useUser()
  const posthog = usePostHog()

  useEffect(() => {
    if (!isLoaded || !posthog) return
    if (user) {
      posthog.identify(user.id, {
        email: user.primaryEmailAddress?.emailAddress,
        name: user.fullName,
        tier: (user.publicMetadata?.tier as string) ?? 'Free',
        created_at: user.createdAt,
      })
    } else {
      posthog.reset() // sesión cerrada → no mezclar con el siguiente usuario
    }
  }, [isLoaded, user, posthog])

  return null
}
```
Montar junto a `PostHogPageView` en `layout.tsx` (dentro de `PHProvider`).

En `providers.tsx`, añadir `person_profiles: 'identified_only'` al `init`.

### A1 · Reverse proxy (anti-adblock)

`next.config.ts` → rewrites para que los eventos salgan desde **tu propio dominio**:
```ts
async rewrites() {
  return [
    { source: '/ingest/static/:path*', destination: 'https://us-assets.i.posthog.com/static/:path*' },
    { source: '/ingest/:path*',        destination: 'https://us.i.posthog.com/:path*' },
  ]
}
```
Y en `providers.tsx`: `api_host: '/ingest'`, `ui_host: 'https://us.posthog.com'`.
> Nota Next 16: añadir `skipTrailingSlashRedirect: true` para no romper el ingest.

### A2 · Capa de eventos nombrados (la clave de la mantenibilidad)

**Toda la taxonomía de eventos en UN solo archivo** → fácil de auditar y evolucionar.

`frontend/src/lib/analytics.ts`:
```ts
import posthog from 'posthog-js'

export const EVENTS = {
  BACKTEST_RUN: 'backtest_run',
  SCREENER_FILTER_APPLIED: 'screener_filter_applied',
  STRATEGY_CREATED: 'strategy_created',
  DATASET_CREATED: 'dataset_created',
  TICKER_ANALYSIS_OPENED: 'ticker_analysis_opened',
  API_KEY_CREATED: 'api_key_created',
  ASSISTANT_MESSAGE_SENT: 'assistant_message_sent',
  FEEDBACK_SUBMITTED: 'feedback_submitted',
  ROADMAP_VOTED: 'roadmap_voted',
  WHATSNEW_VIEWED: 'whatsnew_viewed',
} as const

export function track(event: string, props?: Record<string, unknown>) {
  if (typeof window === 'undefined') return
  posthog.capture(event, props)
}
```

**Submódulos a instrumentar** (una llamada `track()` por acción significativa):
- Backtester → `BACKTEST_RUN` (al lanzar; props: nº estrategias, dataset, rango).
- Screener (`Screener.tsx`) → `SCREENER_FILTER_APPLIED`.
- Strategy builder → `STRATEGY_CREATED`.
- Baúl/datasets → `DATASET_CREATED`.
- Ticker Analysis → `TICKER_ANALYSIS_OPENED`.
- Developers → `API_KEY_CREATED`.
- ChatBot/Edgie → `ASSISTANT_MESSAGE_SENT`.

### A3 · Verificación
- **Dashboards en PostHog** (sin código): páginas más vistas, embudo por submódulo, retención, segmentación por `tier`.
- Confirmar `NEXT_PUBLIC_POSTHOG_KEY` en **Vercel (prod)**.
- (Opcional, sin código) activar **Session Replay** y **Heatmaps** desde el panel de PostHog.

---

## 3. Bloque B — Feedback "¿Qué echas de menos en Edgecute?"

PostHog **sí** tiene encuestas (Surveys). Dos caminos:

- **B-rápido (cero código):** crear una *Survey* de texto libre en el panel de PostHog
  targeteada por URL. El SDK la renderiza solo. Respuestas viven en PostHog. Pega como
  *quick win*, pero **no alimenta el roadmap** ni es de tu propiedad.
- **B-recomendado (widget propio):** un componente con la pregunta, que guarda en **tu
  DuckDB** y además emite el evento `feedback_submitted` a PostHog. Es de tu propiedad y
  **alimenta el roadmap** (un feedback se puede promover a item votable).

### Diseño recomendado (B-recomendado)
- Componente `FeedbackWidget.tsx`: botón flotante discreto o tarjeta inline → modal con
  textarea: *"¿Qué echas de menos en Edgecute para tu día a día?"* + envío.
- POST `/api/feedback` → tabla `feedback` (ver §5) + `track(EVENTS.FEEDBACK_SUBMITTED)`.
- Se monta global en `LayoutShell` (excepto rutas de auth).

> Los dos caminos pueden coexistir: Survey de PostHog para captar rápido + widget propio
> para lo que va al roadmap.

---

## 4. Bloque C — Roadmap votable con impacto

Página nueva `/roadmap` + entrada en `Sidebar.tsx`. **Impacto = nº de votos** (mostrado
como contador/barra). Datos en DuckDB (no hardcode) → mantenible y editable.

### Comportamiento
- Lista agrupada por estado: **Pedidas** · **En curso** · **Entregadas**.
- Cada item: título, descripción, contador de votos, botón *upvote* (optimista).
- **Un voto por usuario por item** (PK `(item_id, user_id)`), toggle para quitar voto.
- Item entregado puede enlazar al release que lo cumplió (conecta con Bloque D:
  "esto lo habéis pedido vosotros → hecho").
- Flujo admin: convertir un `feedback` en `roadmap_item`; cambiar estado.

### [DECISIÓN JESÚS] — negocio, no lo decido aquí
- ¿Se **ponderan** los votos por tier? ¿Pueden votar los Free? ¿Límite de votos por usuario?
- ¿El roadmap y los textos de feedback son **públicos** entre usuarios o privados?
- ¿Gestión de estados vía **mini-panel admin** o editando datos directamente?

---

## 5. Modelo de datos (DuckDB) — añadir a `backend/app/init_db.py`

Siguiendo el patrón existente (crear en `get_db_connection()` y `get_user_db_connection()`,
`user_id VARCHAR` nullable, scoping NULL-tolerante con `app.auth.scope_clause`):

```sql
CREATE TABLE IF NOT EXISTS feedback (
  id VARCHAR PRIMARY KEY,
  user_id VARCHAR,                 -- Clerk sub (nullable si auth off)
  text VARCHAR,
  context_page VARCHAR,            -- de dónde se envió
  status VARCHAR DEFAULT 'new',    -- new | reviewed | promoted | dismissed
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS roadmap_items (
  id VARCHAR PRIMARY KEY,
  title VARCHAR,
  description VARCHAR,
  status VARCHAR DEFAULT 'idea',   -- idea | planned | in_progress | shipped
  category VARCHAR,
  shipped_release_id VARCHAR,      -- enlaza con releases.ts (Bloque D)
  source_feedback_id VARCHAR,      -- si nació de un feedback
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS roadmap_votes (
  item_id VARCHAR,
  user_id VARCHAR,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (item_id, user_id)   -- 1 voto por usuario por item
);
```

> ⚠️ **Dependencia:** votos/feedback **por usuario** requieren `CLERK_AUTH_ENABLED=true`
> en el backend (hoy puede estar `false`). Si está off, `user_id` es `None` y no se puede
> deduplicar el voto. **[DECISIÓN JESÚS]**: confirmar que auth backend está activo en prod.

---

## 6. Endpoints backend — nuevo `backend/app/routers/feedback.py`

Reutiliza `get_current_user_id` / `get_optional_user_id` de `app/auth/clerk.py` y se
registra en `main.py` como los demás (`app.include_router(...)`).

| Método | Ruta | Auth | Qué |
|---|---|---|---|
| POST | `/api/feedback` | usuario | Crear feedback |
| GET | `/api/feedback` | admin | Listar (gestión) |
| GET | `/api/roadmap` | público/usuario | Items + `vote_count` + `has_voted` |
| POST | `/api/roadmap/{id}/vote` | usuario | Toggle voto |
| POST | `/api/roadmap` | admin | Crear item |
| PATCH | `/api/roadmap/{id}` | admin | Editar estado/datos |

Frontend: añadir funciones en `frontend/src/lib/api.ts` reutilizando `apiRequest`
(ya gestiona token Clerk, errores y timeouts).

---

## 7. Bloque D — Popup de novedades (1 vez por release, por usuario)

### Fuente de la verdad de releases = **1 archivo versionado en git** (cero infra)

`frontend/src/data/releases.ts`:
```ts
export interface Release {
  id: string            // 'r-2026-06-23'
  date: string
  title: string         // 'Habéis pedido X, lo hemos hecho'
  items: string[]       // bullets de novedades
  roadmapItemIds?: string[]  // items entregados → "esto lo pedisteis vosotros"
}
export const RELEASES: Release[] = [ /* la más reciente arriba */ ]
export const LATEST_RELEASE = RELEASES[0]
```
> Mantenimiento: cada vez que subís algo, **añadís una entrada** y listo.

### "Visto" por usuario y persistente entre sesiones (no cada vez)

**Recomendado: Clerk `unsafeMetadata.lastSeenReleaseId`** → per-usuario, cross-device,
**sin backend**. El frontend lo lee y lo escribe:

`frontend/src/components/WhatsNewModal.tsx` (montado en `LayoutShell`):
```tsx
'use client'
import { useEffect, useState } from 'react'
import { useUser } from '@clerk/nextjs'
import { LATEST_RELEASE } from '@/data/releases'
import { track, EVENTS } from '@/lib/analytics'

export default function WhatsNewModal() {
  const { user, isLoaded } = useUser()
  const [open, setOpen] = useState(false)

  useEffect(() => {
    if (!isLoaded || !user) return
    const seen = user.unsafeMetadata?.lastSeenReleaseId as string | undefined
    if (seen !== LATEST_RELEASE.id) setOpen(true)   // ← solo si hay release nuevo
  }, [isLoaded, user])

  async function dismiss() {
    setOpen(false)
    track(EVENTS.WHATSNEW_VIEWED, { release_id: LATEST_RELEASE.id })
    await user?.update({ unsafeMetadata: {
      ...user.unsafeMetadata, lastSeenReleaseId: LATEST_RELEASE.id,
    }})
  }
  // ...modal con LATEST_RELEASE.title + items; botón "Entendido" → dismiss()
}
```

**Por qué cumple lo pedido:**
- *"No mostrar cada vez"* → solo si `lastSeenReleaseId !== LATEST_RELEASE.id`. ✅
- *"Tener en cuenta las sesiones del usuario"* → estado **por usuario** en Clerk,
  sobrevive a cierres de sesión y cambios de dispositivo (no es localStorage por equipo). ✅
- Mantenibilidad máxima: un release nuevo = **una línea** en `releases.ts`. ✅

> Alternativa si prefieres no usar `unsafeMetadata`: tabla `user_seen_releases` en backend.
> Más control, pero más código y depende de `CLERK_AUTH_ENABLED`. La de Clerk es más simple.

---

## 8. Principios de mantenibilidad (resumen)

1. **Una fuente por cosa:** taxonomía de eventos en `lib/analytics.ts`; releases en `releases.ts`.
2. **Roadmap dirigido por datos** (DuckDB + endpoints), no hardcode.
3. **Reutilizar lo que ya existe:** patrón de auth Clerk (`get_current_user_id`, `scope_clause`),
   helper `apiRequest`, patrón de routers de `main.py`, patrón de tablas de `init_db.py`.
4. **Feedback ↔ Roadmap ↔ Releases conectados:** un feedback se promueve a item, un item
   entregado se enlaza a un release, el popup lo anuncia.

---

## 9. Fases de implementación

- **Fase 0 — Arreglo PostHog (1 PR pequeño):** `PostHogIdentify` + `person_profiles` +
  reverse proxy. Desbloquea "cómo usa la gente la app" por usuario **ya**.
- **Fase 1 — Eventos de submódulos:** `lib/analytics.ts` + instrumentar acciones clave.
- **Fase 2 — Feedback:** tabla + endpoint + `FeedbackWidget`.
- **Fase 3 — Roadmap:** tablas + endpoints + página `/roadmap` + entrada en Sidebar.
- **Fase 4 — Popup novedades:** `releases.ts` + `WhatsNewModal`.

---

## 11. Lo construido (as-built)

**Backend**
- `app/init_db.py` — tablas `feature_options`, `feature_votes` (PK `round_id+user_id` = 1 voto/release),
  `feature_suggestions`; seed de 5 opciones **placeholder** (editar libremente en DB).
- `app/routers/feedback.py` — `GET /api/feedback/board`, `POST /api/feedback/vote` (upsert),
  `POST /api/feedback/suggestion`, `GET /api/feedback/suggestions`. Ronda actual vía `FEATURE_VOTE_ROUND`.
- `app/main.py` — router registrado.

**Frontend**
- PostHog: `PostHogIdentify.tsx` (identify/reset con Clerk), `providers.tsx` (`person_profiles:'identified_only'`
  + `api_host:'/ingest'`), `next.config.ts` (reverse proxy `/ingest`), `layout.tsx` (monta identify).
- `lib/analytics.ts` — taxonomía de eventos + `track()`. Instrumentado en `lib/api.ts`:
  `backtest_run`, `strategy_created`, `dataset_created`, `strategy_search_run`.
- `components/FeedbackWidget.tsx` — modal lista única + resultados (barras, más votados arriba) + "Otra cosa".
- `components/WhatsNewModal.tsx` + `data/releases.ts` — popup novedades 1×/release vía Clerk `unsafeMetadata`.
- `lib/api_feedback.ts`, `LayoutShell.tsx` (monta widgets), `Sidebar.tsx` (botón "Feedback").

**⚠️ Pendiente operativo (no rompe nada, pero leer):**
1. **Reiniciar el backend** para que `init_db` cree las tablas nuevas.
2. **Auth backend:** dejé `CLERK_AUTH_ENABLED` **sin tocar** a propósito. Para activarlo de verdad hay
   que **añadir las llaves de Clerk al backend** (`CLERK_PUBLISHABLE_KEY`/`CLERK_ISSUER`) primero; si no,
   `verify_clerk_token` lanza 500. El widget funciona igualmente sin ese flag.
3. **Vercel/prod:** confirmar `NEXT_PUBLIC_POSTHOG_KEY`. El proxy `/ingest` solo aplica donde corre Next.
4. Editar las 5 opciones placeholder y la entrada de `releases.ts` con contenido real.

---

## 10. Decisiones abiertas para Jesús

1. **Auth backend:** ¿`CLERK_AUTH_ENABLED=true` en prod? (necesario para votos/feedback por usuario).
2. **Feedback:** ¿Survey de PostHog (rápido) o widget propio (recomendado, alimenta roadmap)? ¿o ambos?
3. **Roadmap (negocio):** ponderación de votos por tier, quién vota, límites, público vs privado.
4. **Gestión roadmap:** ¿mini-panel admin o edición directa de datos?
5. **Popup "visto":** ¿Clerk `unsafeMetadata` (recomendado) o tabla backend?
6. **Vercel:** confirmar `NEXT_PUBLIC_POSTHOG_KEY` presente en el entorno de producción.
