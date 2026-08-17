# FASE 0 — Informe de Reconocimiento: auth, tiers y billing

> **Naturaleza:** informe de reconocimiento **read-only**. No propone soluciones ni arquitectura (eso es Fase 1). Todas las citas son `ruta:línea` verificadas contra el árbol de trabajo `develop`, comparado con `main` y `adrian-garcia-develop` vía git read-only.
> **Fecha:** 2026-08-16 · **Rama base:** `develop`

**Titular:** existe un sistema de **entitlements/tiers real y funcional** (leído de Clerk `publicMetadata.tier`), pero **NO existe ninguna integración de pagos** — ni SDK, ni Price IDs, ni webhooks, ni tablas, ni UI de checkout. Toda la capa de cobro es **diseño-doc + placeholders**. El tier hoy se asigna **a mano en el dashboard de Clerk**.

---

## 1. Clerk — estado actual

**Verificación de identidad** — `backend/app/auth/clerk.py:104-138` (`verify_clerk_token`, RS256 contra JWKS, cache 1h `clerk.py:60-94`; issuer de `CLERK_ISSUER` o derivado de la publishable key `clerk.py:29-48`; `verify_aud` off a propósito porque Clerk usa `azp` `clerk.py:132-134`). Enforcement con flag `CLERK_AUTH_ENABLED` (`clerk.py:53`); si off → `user_id=None`, reads sin scoping. Del JWT solo se lee `sub` (`clerk.py:168,183`). `GET /api/users/me` (`routers/users.py:26-38`) devuelve email/sid/azp/iss/exp/iat de los claims, **no** llama a Clerk ni devuelve tier. **ENCONTRADO COMPLETO.**

**De dónde sale el TIER** — NO del JWT. `get_tier` (`entitlements/middleware.py:34-72`) hace REST a `api.clerk.com/v1/users/{id}` con `CLERK_SECRET_KEY` y lee `public_metadata.tier` (`middleware.py:67`). Es el **único** campo de metadata que lee el backend. **ENCONTRADO COMPLETO.**

**Metadata Clerk** — `publicMetadata.tier` (backend `middleware.py:67`; frontend pistas UI `PostHogIdentify.tsx:25`, `backtester/page.tsx:150`). `unsafeMetadata.lastSeenReleaseId` solo para el modal de novedades (`WhatsNewModal.tsx:23,35`), sin relación con billing. `privateMetadata`: **NO ENCONTRADO**. **Ningún código ESCRIBE metadata de Clerk** (sin `update_metadata`/`users.update` en el repo).

**Tiers hoy (5)** — fuente única `entitlements/policy.py:66-155`. ⚠️ En `develop`/`main` casi todo está en `True`/`-1` (ilimitado); los valores "de prod" están **comentados, no aplicados** (`policy.py:84-154`). Lo único que restringe de verdad hoy: `market.analysis.access` (cerrado solo en Beta) y `admin.preview_features` (solo Admin).

- **Admin** (`policy.py:67-83`): todo abierto + `admin.preview_features`. Internos.
- **Pro** (`policy.py:84-100`): abierto salvo `api.portal.access`, `market.sentiment.access`, preview.
- **Mid** (`policy.py:101-117`): en la práctica = Pro hoy; valores prod en comentarios.
- **Beta** (`policy.py:121-137`) — **el DEFAULT y el tier real de invitados**: solo Screener + Ticker Analysis + Backtester (incl. `surface_3d`) + Baúl. Cerrado: API, `market.sentiment.access`, **`market.analysis.access`** (único tier con esto cerrado), preview.
- **Free** (`policy.py:138-154`): abierto hoy; valores prod comentados; ya no es default, reservado "para registro público" (`policy.py:28-30`).

**Default fail-CLOSED** — `DEFAULT_TIER="Beta"` (`policy.py:26`); `get_tier` cae a Beta ante sin user_id / sin secret / tier ausente / error de red (`middleware.py:52-72`). Override dev `DEV_TIER` (`middleware.py:48-49`). **ENCONTRADO COMPLETO.**

**Dónde se aplica el gating REAL (backend, no solo menú)** — `require()` (403) / `consume()` (429) en `middleware.py:79-127`, vía `Depends()` en pocos sitios (el resto del backend no tiene guarda, reconocido en `policy.py:13-15`):

- Market Analysis: `routers/market.py:38,145,160`, `routers/market_adjusted.py:22,32,42`.
- Market Sentiment: `routers/social.py:29` (5 endpoints).
- Portal API: `routers/api_console.py:31` (router-level).
- `consume()` (cuotas Redis): **PARCIAL** — infra existe (`usage.py`, `LIMIT_WINDOWS` `policy.py:57-61`) pero **ningún endpoint real usa `Depends(consume(...))`**; solo en docstrings/docs.

**Endpoints de tier** — `GET /api/users/me/entitlements` (`routers/entitlements.py:18-32`) devuelve tier+entitlements+usage. **ENCONTRADO COMPLETO.**

**Webhooks de Clerk** — **NO ENCONTRADO**. Sin handler, sin `svix`, sin `user.created`/`user.updated`. Los "webhook" de `backend/scripts/*` son de **Discord**. La única mención de webhook Clerk es planeada (`docs/entitlements/ARQUITECTURA.md:34-35`).

**subscription_status/plan/billing en Clerk** — **NO ENCONTRADO**. El único campo de permisos es `public_metadata.tier`.

**Por rama:** `clerk.py`/`policy.py`/`middleware.py` **idénticos develop==main**. `adrian-garcia-develop` está **desfasada**: sin tier Beta, default = `FREE_TIER` (fail-**open**), scoping NULL-tolerante. `entitlements.py`/`users.py` idénticos en las tres.

---

## 2. Base de datos — usuarios y tiers

**NO existe ninguna tabla de usuarios, tiers, planes, suscripciones ni fechas de expiración/renovación en `users.duckdb`.** El vínculo usuario→tier es 100% Clerk en tiempo de request (`middleware.py:59-69`), sin persistencia local. La matriz de permisos es una constante Python (`policy.py:66`).

**Tablas en `users.duckdb`** (DDL en `init_db.py`, `develop==main`): `strategies`, `saved_queries`, `datasets`, `dataset_pairs`, `backtest_results`, `ticker_analysis_cache`, `dilution_banks_registry`, `precache_state`, `feature_options`, `feature_votes`, `feature_suggestions`. Todas usan a lo sumo `user_id` como propiedad; **ninguna** tiene columna de tier/plan/billing. `database.py` y `db/connection.py` no tienen DDL de usuarios (solo market-data). **ENCONTRADO COMPLETO.**

**Store del portal API — SQLite SEPARADO `edgecute_api.sqlite`** (NO users.duckdb; `api_public/core/store.py:66-98`, `:4-6`; ruta `config.STORE_PATH`). **PARCIAL:**

- `api_keys` (`store.py:70-79`): incluye columna **`plan TEXT DEFAULT 'default'`** — pero **solo toma el valor literal `"default"`** (`core/auth.py:20`, `config.py:65-69`). No hay plan de pago ni código que asigne otro valor. Sin columna de expiración/renovación/período.
- `usage_ledger` (`store.py:80-88`): metering de consumo, USADA (`metering.py:13-22`).
- `backtest_results` (job store), USADA.

**Cuotas de uso** — Redis efímero (`usage.py:37-38`, TTL 24h/31d), no tabla; sin Redis nunca bloquea (`usage.py:47-53`).

**Relación `user_id ↔ tier ↔ expiración/renovación`** — **NO ENCONTRADO** (grep `expires|renew|valid_until|trial_end|period_end` sin columnas DDL).

**Por rama:** `init_db.py`/`store.py` **develop==main**. `adrian-garcia-develop`: `init_db.py` difiere (rama atrasada); `store.py` idéntico.

---

## 3. Stripe u otro proveedor de pagos

**NO ENCONTRADO (implementación) / PARCIAL (placeholder + diseño diferido).** Cero integración funcional en cualquier rama.

- **Dependencias:** sin `stripe`/`@stripe/*`/`svix`/`paddle`/`paypal` en `requirements.txt` ni `package.json`. Ningún `import stripe` en el repo ni en ninguna rama remota (única coincidencia = plantilla archivada `_archive/.../nextjs-saas/TEMPLATE.md`, fuera de alcance).
- **Único código relacionado (PLACEHOLDER):** `routers/api_console.py:162-177` `GET /billing` devuelve `invoices: []` y `stripe: {connected: False, note:"…próximamente"}`, con comentario `# Stripe is wired later (docs/b2d-gateway/07)`. `/plans` (`:180-187`) lista solo `default`, `price: None`. Contrato fijado en test `api_public/tests/test_console.py:89-92`.
- **Price IDs / Product IDs / webhooks de pago / moneda:** **NO ENCONTRADO** (todos los `webhook` del backend son Discord; los `USD` en docs son P&L de backtesting, no moneda de cobro).
- **Distinción clave:** hay entitlements/tiers REALES leídos de Clerk, pero la pieza pago→tier (webhook Stripe→Clerk) es **diseño-doc-only**.

---

## 4. Variables de entorno

| Variable | Definida en | Default | Relación pago | Estado |
|---|---|---|---|---|
| `EDGECUTE_UPGRADE_URL` | `api_public/config.py:56-58` | `""` | CTA upgrade; "empty until pricing/Stripe exists" | **PARCIAL** (vacío) |
| `EDGECUTE_MAX_KEYS_PER_OWNER` | `config.py:59` | 25 | límite técnico, no pago | ENCONTRADO (no-pago) |
| `EDGECUTE_MAX_TICKER_DAYS_PER_RUN` | `config.py:66` | — | cap técnico por request | ENCONTRADO (no-pago) |

`STRIPE_*` / `STRIPE_SECRET_KEY` / `STRIPE_WEBHOOK_SECRET` / `SVIX_*` / `PADDLE_*` / `BILLING_*`: **NO ENCONTRADO** en ningún `.env.example`, README, `DEPLOYMENT.md` ni runbook (única aparición = plantilla archivada). Los planes/tiers viven como **constantes en código**, no en env (confirmado por diseño `b2d-gateway/05_ARQUITECTURA.md:63`).

---

## 5. Frontend

**NO existe UI real de pricing / checkout / gestión de suscripción** (ni en develop, ni main, ni ninguna rama). El árbol `frontend/src/app/` no tiene `pricing/`, `billing/`, `checkout/`, `plans/`, `subscription/`. Búsqueda de esos términos → solo 3 ficheros, todos del panel de developer.

- **Pestaña "Facturación" (PARCIAL, no conectada a cobro):** `components/developers/ApiConsole.tsx:305-341` (`BillingTab`, tab id `"billing"` `:99,136`) muestra plan/uso/estado desde `GET /billing`; botón "Mejorar plan" = simple `<a href={upgrade_url}>` externo (`:322-325`), **no es checkout**; "Facturas" pinta `data.stripe.note` cuando `invoices.length===0` (`:335-337`). Interfaz `Billing` en `lib/api_console.ts:55-61` (`stripe` es solo campo de estado pasivo).
- **Gating por tier (mixto: visual pero alimentado por entitlement real del backend):** hook `useEntitlements()` (`lib/entitlements.ts`) lee `GET /api/users/me/entitlements` (`:28,43`). **Diseño OPTIMISTA**: `can()` devuelve `true` mientras carga/error/feature desconocida (`entitlements.ts:96-100`). `LockedFeature.tsx` renderiza children si `can()`; si no, tarjeta candado con botón **deshabilitado** "Ver planes" `title="Próximamente"` sin destino (`:76-94`). Gates reales: `Sidebar.tsx:41,47,260,276`; `screener/page.tsx:13`; `market-analysis/page.tsx:13`; `market-analysis-adjusted/page.tsx:11`; `market-sentiment/page.tsx:13`; `developers/ApiConsoleGuard.tsx:22`; `ResultsTabs.tsx:408` (único gate que menciona **"Pro"**). Doble fuente de tier: `backtester/page.tsx:150` y `PostHogIdentify.tsx:25` leen `publicMetadata.tier` de Clerk (fallback "Free"); el Sidebar pide al backend porque Clerk "mentía" (`Sidebar.tsx:56-59`).
- **Tiers conocidos en frontend:** literales `"Admin"`, `"Pro"`, `"Free"` (fallback), `"Beta"` (comentarios); el tier real es dinámico del backend. Sin enum/config de tiers en el front.

---

## 6. Flujo de invitaciones beta

- **`invite_beta.py` NO EXISTE** en el repo (`git ls-files | grep -i invite` vacío). Ningún código asigna metadata, crea invitaciones ni copia tier. El proceso es **manual en el dashboard de Clerk**.
- **Mecanismo (por diseño):** invitar en Clerk basta — quien se registra sin `tier` en `publicMetadata` cae a `DEFAULT_TIER="Beta"` (`policy.py:26`, `middleware.py:52-53`), que ya desbloquea las 4 secciones beta. El "trabajo del backend después" es solo `get_tier` leyendo `public_metadata.tier` o Beta si falta. Internos llevan `tier:"Admin"` puesto a mano.
- **Sign-up mode = RESTRICTED (registro cerrado):** `sign-up/[[...sign-up]]/page.tsx:3-7` (comentario explícito) reemplaza `<SignUp/>` por mensaje estático "El registro está cerrado / Acceso por invitación" (`:155-186`). Reabrir = **2 pasos** (restaurar `<SignUp/>` + cambiar mode a Public en Clerk). `middleware.ts:7-13`: solo `/sign-in` y `/sign-up` públicas; sin `auth.protect()` (`:18-23`). **Idéntico en las tres ramas.**

---

## 7. Verificación de dirección de arquitectura

- **Clerk Billing: NO ENCONTRADO.** Cero `<PricingTable>`, `clerk.billing`, `has({plan/feature})`, `__experimental_`, `<Protect>` con plan/feature, ni API de billing de `@clerk/nextjs` (verificado en `main` y `develop`). Clerk = solo auth (`@clerk/nextjs ^7.4.3`, `package.json:12-13`). No hay que revertir nada: no se empezó por ahí.
- **Stripe Price IDs / Product IDs / moneda: NO ENCONTRADO** en código ni docs.
- **Webhook handler de Stripe: NO ENCONTRADO.** Solo pseudocódigo en `docs/entitlements/ARQUITECTURA.md:184-193` (sin archivo real; `entitlements/` solo tiene `policy/checker/usage/middleware/__init__`).
- **Diseño existente (doc-only):** `docs/b2d-gateway/` describe el MECANISMO (metering `usage_ledger` + hook `can_access`), y difiere Stripe explícitamente: `01_VIABILIDAD.md:22,206-208`, `05_ARQUITECTURA.md:172` ("No incluido: tiers, precios, créditos, Stripe"), `07_DECISIONES_ABIERTAS.md:29-30` (Q3 diferido), `BUILD_STATUS.md:37-38,53`, `entitlements/ARQUITECTURA.md:236` (Fase 3 "Pendiente"). La dirección documentada es "Stripe = config, no código", pero **a día de hoy ese código no está escrito en ninguna rama**.

---

## RESUMEN EJECUTIVO — huecos más grandes (NO ENCONTRADO)

1. **Cero integración de pagos:** sin SDK Stripe (ni otro), sin Price/Product IDs, sin config de moneda, en ninguna rama.
2. **Sin webhook de pago→tier:** la pieza que asignaría tier tras cobro es solo pseudocódigo en docs (`entitlements/ARQUITECTURA.md:184-193`).
3. **Sin webhooks de Clerk** de ningún tipo (ni `user.created`, ni svix).
4. **Sin persistencia de suscripción:** ninguna tabla usuario↔tier↔expiración/renovación; el tier vive solo en Clerk `publicMetadata.tier`, sin fecha.
5. **Sin `invite_beta.py`:** el alta beta es manual en Clerk; funciona por el default fail-closed a Beta.
6. **Sin UI de pricing/checkout/gestión de suscripción:** solo un placeholder read-only y un botón "Ver planes" deshabilitado.
7. **Sin env vars de billing** (`STRIPE_*` etc.); `EDGECUTE_UPGRADE_URL` existe pero vacío.
8. **`api_keys.plan` inerte:** columna presente pero siempre `"default"`, sin planes de pago.
9. **`consume()`/cuotas sin cablear:** infra de metering existe pero ningún endpoint la aplica.
10. **Punto de partida real:** hay un motor de entitlements por tier funcional (Clerk→policy.py), pero **la asignación de tier es 100% manual** — todo lo que conecta "pago" con "tier" está por construir.
