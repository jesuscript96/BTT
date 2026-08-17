# FASE 1 — Diseño de arquitectura: trial + suscripción de pago (Stripe + Clerk)

> **Naturaleza:** documento de diseño. NO contiene código de producción. Cada decisión se justifica contra los hallazgos de la Fase 0 (`docs/FASE0_RECON_AUTH_TIERS_BILLING.md`) con citas `archivo:línea`. Al final: **PREGUNTAS ABIERTAS PARA ADRIAN**.
> **Fecha:** 2026-08-16 · **Rama base:** `develop`

## Decisiones confirmadas por Adrian (2026-08-16)
Estas 4 respuestas quedan como inputs fijos (resuelven las preguntas abiertas #1, #2, #3, #8):
1. **Alcance del plan de 29 €/mes = tier `Pro` actual** (`policy.py:84-100`): incluye Market Analysis; excluye Market Sentiment, portal de API y preview. Se reutiliza tal cual, sin tocar entitlements.
2. **Admin siempre a mano** (allowlist / `entitlement_grants.grant_tier='Admin'`), fuera de Stripe.
3. **Cancelación = hasta fin de periodo** (`cancel_at_period_end=true`): conserva acceso hasta la fecha ya pagada, luego `Locked`. Sin reembolso/prorrateo.
4. **Trial único por IDENTIDAD, no por `user_id`**: Stripe debe impedir reciclar el trial borrando/recreando cuenta → se deduplica por **email + fingerprint de la tarjeta** (Stripe `PaymentMethod.card.fingerprint`), no solo por Clerk `user_id`. **Los usuarios migrados NO reciben trial nuevo**: pasan directo a estado **`gracia`** con fecha de corte comunicada (ya usan el producto, no lo están probando).

## Contexto Fase 0 (resumen, ya verificado)
- Auth = Clerk (RS256/JWKS, `auth/clerk.py`). El tier se resuelve **en cada request gateado** con un `httpx.get` síncrono a `api.clerk.com` leyendo `public_metadata.tier` (`entitlements/middleware.py:59-67`, timeout 5 s). Ningún código **escribe** metadata a Clerk.
- Tiers en `entitlements/policy.py:66-155`. Hoy `Free/Mid/Pro` están casi abiertos; **`Free` está TODO en `True`/`-1`** (`policy.py:138-154`) → *no sirve como estado "bloqueado"*. `Beta` es el único que restringe de verdad (`market.analysis.access=False`, `policy.py:135`) y es el `DEFAULT_TIER` fail-closed (`policy.py:26`).
- Sin persistencia local de suscripción; `users.duckdb` no tiene tabla de usuarios/tiers.
- Stripe = cero integración. Solo stubs: `routers/api_console.py:162-177` (`/billing` devuelve `invoices:[]`, `stripe:{connected:False}`), `config.py:56-58` (`UPGRADE_URL` vacío). El store transaccional del repo es **SQLite separado** a propósito (`api_public/core/store.py:1-10`, "never reuse the engine DB — avoids its locks").
- Registro CERRADO (`sign-up/[[...sign-up]]/page.tsx:155-186`, Clerk restricted). Alta 100% manual.
- Frontend `useEntitlements()` es **OPTIMISTA**: `can()` → `true` mientras carga/error/feature desconocida (`lib/entitlements.ts:96-100`). ⚠️ Riesgo central: un fallo de sync da acceso de MÁS, no de menos. El backend debe ser el gate real.

---

## 1. Fuente de verdad del tier — DECISIÓN

**Decisión: el estado de suscripción vive en una tabla local nueva (SQLite dedicado, patrón `edgecute_api.sqlite`), alimentada por webhooks de Stripe; `get_tier` deriva el tier de esa tabla. Clerk queda SOLO como auth. NO se escribe `publicMetadata.tier` de vuelta a Clerk.**

Jerarquía de verdad:
- **Stripe = fuente de verdad del COBRO** (customer, subscription, invoices).
- **Tabla local = fuente de verdad del ESTADO que consume la app** — es un *mirror materializado* de Stripe, reconstruible desde Stripe si se pierde.
- **Clerk = identidad/sesión.** Nada de billing.

### Por qué NO la opción B (escribir `publicMetadata.tier` en Clerk)
1. **Doble destino de escritura que deriva.** Stripe→backend→Clerk→(lectura) tiene más saltos y más puntos de fallo que Stripe→backend→(lectura local). Cada webhook tendría que hacer un `PATCH` a Clerk; si falla, tier y pago divergen sin traza.
2. **Coste/latencia por request.** Hoy `get_tier` hace un GET síncrono a Clerk **en cada endpoint gateado** (`middleware.py:59-64`). Mantener eso ata la disponibilidad del gating a la API de Clerk y añade ~decenas de ms + riesgo de rate-limit por request. Derivar el tier de una lectura local elimina ese salto de red.
3. **Pobreza del dato.** `publicMetadata.tier` es un único string; no puede representar `current_period_end`, `trial_end`, `past_due`, ni el historial de facturas que la sección de billing necesita. La tabla local sí.

### Por qué SÍ la opción A (tabla local autoritativa)
- Un solo escritor (los webhooks) y un solo lector (`get_tier`), ambos locales.
- `get_tier` pasa de "GET a Clerk" a "SELECT local" → más rápido y más disponible.
- El dato rico (estado + fechas + facturas) queda en un sitio.
- **Durabilidad:** aunque el SQLite local se pierda (deploy/volumen), se reconstruye desde Stripe (`customers.list` + `subscriptions.list`) con un job de reconciliación. Stripe es la verdad; lo local es caché.

### Comportamiento ante fallo/retraso del webhook (análisis fail-closed)
Hoy el fallback es `DEFAULT_TIER="Beta"` (`middleware.py:52-53,72`), que es **generoso** (desbloquea Backtester/Screener/Ticker/Baúl). Con cobro, el fallback generoso es una **fuga de ingresos**. Decisión de asimetría de errores:

| Escenario | Riesgo | Coste | Elección |
|---|---|---|---|
| Pagó pero el tier aún no subió (webhook tarda) | Negar acceso a quien pagó | Ticket de soporte / fricción | **Mitigado por diseño**: el row local se crea también en el retorno síncrono del Checkout (ver §4), no solo por webhook → el acceso no depende del timing del webhook |
| Canceló pero conserva acceso (webhook de baja falló) | Fuga de ingresos | Recuperable (reconciliación nocturna) | Aceptable como transitorio |
| No sabemos el estado (sin row / error de lectura) | Dar acceso de gratis | Fuga | **Fail-CLOSED**: sin subscripción activa ni grant → tier **`Locked`** (nuevo, todo cerrado). Reemplaza a `Beta` como `DEFAULT_TIER` |

**Cambio concreto en el código existente:** `get_tier` (`middleware.py:34-72`) deja de llamar a Clerk y pasa a: `DEV_TIER` override (se mantiene) → admin allowlist → SELECT local de estado → mapeo estado→tier (§3) → si nada, `Locked`. `require()`/`consume()`/`policy.py` NO cambian de interfaz (siguen recibiendo un string de tier). Es un cambio **quirúrgico y aislado** en `get_tier`.

---

## 2. Modelo de datos — DDL

**Dónde vive:** SQLite dedicado `edgecute_billing.sqlite` (env `EDGECUTE_BILLING_DB_PATH`), **separado** de `users.duckdb` y también del `edgecute_api.sqlite` del portal.
Justificación:
- `users.duckdb` es analítico y, en prod, se **re-sube entero a GCS bajo un lock global tras cada escritura** (ver memorias `btt-strategies-save-timeout`, `btt-production-infra`). Escribir estado de suscripción ahí en cada webhook es inviable.
- El repo ya establece el patrón "store transaccional = SQLite separado, nunca el engine DB" (`api_public/core/store.py:1-10,55-64`). Reutilizamos ese patrón (clase `Store` thread-safe con `RLock`).
- **Durabilidad en prod:** el fichero debe ir en volumen persistente (o sync GCS como `users.duckdb`); si no, se reconstruye desde Stripe. Es un requisito de despliegue, no de esquema.

```sql
-- Cliente de Stripe ↔ usuario de Clerk (1:1)
CREATE TABLE IF NOT EXISTS billing_customers (
    user_id            TEXT PRIMARY KEY,          -- Clerk sub (JWT 'sub')
    stripe_customer_id TEXT NOT NULL UNIQUE,
    email              TEXT,
    created_at         REAL NOT NULL,
    updated_at         REAL NOT NULL
);

-- Suscripción (una activa por usuario en el MVP; permitimos histórico)
CREATE TABLE IF NOT EXISTS subscriptions (
    stripe_subscription_id  TEXT PRIMARY KEY,
    user_id                 TEXT NOT NULL,
    stripe_customer_id      TEXT NOT NULL,
    status                  TEXT NOT NULL,        -- trialing|active|past_due|canceled|unpaid|incomplete|incomplete_expired
    price_id                TEXT,                 -- Stripe Price (29€/mes)
    currency                TEXT,                 -- 'eur'
    trial_end               REAL,                 -- epoch, NULL si no trial
    current_period_end      REAL,                 -- epoch, fin de periodo/renovación
    cancel_at_period_end    INTEGER NOT NULL DEFAULT 0,
    canceled_at             REAL,
    default_pm_id           TEXT,                 -- referencia PM, NO datos de tarjeta
    created_at              REAL NOT NULL,
    updated_at              REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sub_user ON subscriptions(user_id);

-- Método de pago por defecto (referencia + datos NO sensibles para pintar en UI)
CREATE TABLE IF NOT EXISTS payment_methods (
    stripe_pm_id  TEXT PRIMARY KEY,
    user_id       TEXT NOT NULL,
    brand         TEXT,      -- visa|mastercard...
    last4         TEXT,      -- 4 dígitos, NO PAN completo
    exp_month     INTEGER,
    exp_year      INTEGER,
    is_default    INTEGER NOT NULL DEFAULT 0,
    updated_at    REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_pm_user ON payment_methods(user_id);

-- Historial de facturas (metadatos + enlaces Stripe; el PDF lo sirve Stripe)
CREATE TABLE IF NOT EXISTS invoices (
    stripe_invoice_id   TEXT PRIMARY KEY,
    user_id             TEXT NOT NULL,
    subscription_id     TEXT,
    status              TEXT NOT NULL,   -- paid|open|void|uncollectible|draft
    amount_due          INTEGER,         -- céntimos
    amount_paid         INTEGER,
    currency            TEXT,            -- 'eur'
    hosted_invoice_url  TEXT,            -- página Stripe
    invoice_pdf         TEXT,            -- PDF Stripe
    period_start        REAL,
    period_end          REAL,
    created_at          REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_inv_user ON invoices(user_id);

-- Concesiones manuales (usuarios gratis + admins), sin Stripe
CREATE TABLE IF NOT EXISTS entitlement_grants (
    user_id      TEXT PRIMARY KEY,
    grant_tier   TEXT NOT NULL,   -- 'Pro' (gratis comped) | 'Admin'
    reason       TEXT,
    granted_by   TEXT,
    expires_at   REAL,            -- NULL = perpetuo; se usa en la migración (§7)
    created_at   REAL NOT NULL
);

-- Idempotencia de webhooks (Stripe reintenta; hay que deduplicar)
CREATE TABLE IF NOT EXISTS webhook_events (
    stripe_event_id TEXT PRIMARY KEY,
    type            TEXT NOT NULL,
    processed_at    REAL NOT NULL
);
```

El mapeo a tier interno **no se persiste**: es una función pura `resolve_tier(user_id)` que lee `entitlement_grants` (gana Admin/grant) y `subscriptions` (estado + fechas) y devuelve un string de `policy.POLICY` (§3).

---

## 3. Modelo de estados → tiers existentes

Los tiers actuales (`Admin/Pro/Mid/Beta/Free`) se diseñaron para el alta manual. El nuevo eje es el **estado de suscripción**, que se **traduce** a los tiers YA definidos en `policy.py` (no se inventan entitlements nuevos; solo se añade **un tier `Locked`** cuyos valores usan las mismas feature-keys existentes, todas cerradas).

### Estados (mirror de `subscription.status` de Stripe + añadidos locales)
| Estado | Origen | ¿Acceso? | Tier resuelto |
|---|---|---|---|
| `trialing` | Stripe | Sí | **`Pro`** |
| `active` | Stripe | Sí | **`Pro`** |
| `past_due` | Stripe (fallo de cobro, en dunning) | Sí, **durante ventana de gracia** | `Pro` hasta `grace_deadline`, luego `Locked` |
| `canceled` / `unpaid` / `incomplete_expired` | Stripe | No | **`Locked`** |
| `incomplete` (pago inicial pendiente) | Stripe | No | `Locked` |
| `admin_grant` (gratis comped) | local `entitlement_grants.grant_tier='Pro'` | Sí | **`Pro`** |
| `admin` | allowlist / `grant_tier='Admin'` | Sí, total | **`Admin`** |
| (sin registro) | — | No | **`Locked`** (nuevo `DEFAULT_TIER`) |

### Traducción a `policy.POLICY`
- **`Admin`** → tier `Admin` existente (`policy.py:67-83`). Sin cambios.
- **Usuario con acceso (trialing/active/gracia/comped)** → tier **`Pro`** existente (`policy.py:84-100`): es el tier no-admin más completo (`market.analysis.access=True`), solo cierra `api.portal.access`, `market.sentiment.access`, `admin.preview_features`. Reutiliza entitlements tal cual. *(Ver PREGUNTA ABIERTA #2: confirmar que el plan de 29€ = feature-set de `Pro`.)*
- **Sin acceso** → tier **`Locked`** (NUEVO en `POLICY`): todas las feature-keys de `FEATURE_TYPES` (`policy.py:35-52`) en `False`/`0`. No inventa features; solo es una fila de config todo-cerrada. Pasa a ser `DEFAULT_TIER`.

### Qué pasa con `Beta`, `Mid`, `Free`
- **`Beta`**: se **retira del flujo nuevo** (deja de asignarse). No es "el otorgado a mano": el usuario comped debe ver el **producto completo** (`Pro`), no un beta recortado. La fila `Beta` puede permanecer en `POLICY` por compatibilidad durante la migración (§7) y eliminarse después.
- **`Mid`/`Free`**: quedan **sin asignar** (no hay tier intermedio ni gratis-público en el modelo de 29€ único). Se conservan como vocabulario por si se introduce un plan intermedio más adelante. ⚠️ **`Free` NO puede usarse como estado bloqueado** porque hoy está todo abierto (`policy.py:138-154`); por eso se crea `Locked` explícito.
- **`DEFAULT_TIER`** cambia de `Beta` (`policy.py:26`) a `Locked`. Esto endurece el fail-closed: quien no resuelve a nada no ve nada (coherente con "hay que pagar/trial").

---

## 4. Mecanismo del trial con tarjeta obligatoria

**Decisión: Stripe Checkout Session en `mode=subscription`, con `subscription_data.trial_period_days=7` y `payment_method_collection="always"`.**

### Por qué Checkout y no Setup Intent + Payment Element embebido
- `payment_method_collection="always"` obliga a **tarjeta desde el inicio** aun con trial — cumple la regla de negocio sin lógica propia.
- Página **alojada por Stripe** → PCI SAQ-A (no tocamos datos de tarjeta), SCA/3DS gestionado por Stripe, menos código.
- El Payment Element embebido daría más control visual pero exige montar SetupIntent + confirmar + crear Subscription a mano: más superficie de fallo para un MVP "billing mínimo".

### Flujo paso a paso
1. Usuario se registra en Clerk → cuenta creada, **sin acceso** (`Locked`).
2. En primer login sin suscripción, la app lo lleva a "Empieza tu prueba". Backend: `get_or_create` Stripe Customer con `metadata.clerk_user_id=<sub>`, guarda `billing_customers`.
3. Backend crea Checkout Session: `mode=subscription`, `line_items=[{price: STRIPE_PRICE_ID_MONTHLY_EUR, quantity:1}]`, `subscription_data.trial_period_days=7`, `payment_method_collection="always"`, `client_reference_id=<clerk_user_id>`, `success_url`/`cancel_url`.
4. Usuario introduce tarjeta en la página Stripe. Stripe crea la Subscription en `status=trialing`, guarda el PM por defecto, **no cobra aún**.
5. **Doble confirmación del acceso** (evita depender del timing del webhook):
   - (a) **Retorno síncrono**: en `success_url` el backend recupera la sesión (`checkout.sessions.retrieve` con expand subscription) y **upsert** inmediato de `subscriptions` (`status=trialing`, `trial_end=+7d`) → tier `Pro` al instante.
   - (b) **Webhook** `checkout.session.completed` + `customer.subscription.created` (idempotente) confirma/consolida lo mismo.
6. **Fin del trial (día 7):** Stripe genera factura y cobra la tarjeta automáticamente:
   - Éxito → `invoice.paid` + `customer.subscription.updated status=active` → sigue `Pro`.
   - **Tarjeta rechazada** → `invoice.payment_failed`; la Subscription pasa a `past_due`. Stripe aplica **Smart Retries / dunning** (según config del dashboard). Mantenemos acceso (`Pro`) durante la **ventana de gracia** (`grace_deadline`, configurable — PREGUNTA #4). Si tras los reintentos sigue impago → `subscription.updated status=unpaid`/`deleted` → tier `Locked` (paywall).

### Trial único por identidad (anti-reciclaje) — decisión confirmada
El trial de 7 días es **único por identidad**, no por `user_id` de Clerk (si fuera por `user_id`, bastaría borrar y recrear cuenta para repetirlo). Deduplicación:
- **Email** del Customer + **`PaymentMethod.card.fingerprint`** de Stripe (mismo plástico → mismo fingerprint aunque cambie el email/cuenta).
- Antes de conceder `trial_period_days=7`, el backend comprueba si ese email o fingerprint ya consumió un trial (tabla local `trial_ledger` o consulta a Stripe). Si ya lo usó → Checkout **sin trial** (cobro inmediato de 29 €).
- Requiere una tabla auxiliar mínima `trial_ledger(identity_key TEXT PRIMARY KEY, kind TEXT, first_trial_at REAL)` donde `identity_key` = email normalizado y/o card fingerprint.

### Nota SCA/Europa
Cliente europeo → 3DS frecuente. Con Checkout + trial, el primer cobro real es en el día 7; Stripe puede requerir autenticación off-session que a veces falla. El flujo `past_due`→gracia→dunning cubre ese caso.

---

## 5. Matriz de eventos de webhook

Verificación de firma con `STRIPE_WEBHOOK_SECRET`; deduplicación por `event.id` en `webhook_events`; todo el manejo **idempotente**.

| Evento Stripe | Tabla/campo que actualiza | Efecto en tier/entitlement |
|---|---|---|
| `checkout.session.completed` | `billing_customers` (link customer↔user vía `client_reference_id`), upsert `subscriptions` | Alta de acceso → `Pro` (trialing) |
| `customer.subscription.created` | `subscriptions` (status, `trial_end`, `current_period_end`, `default_pm_id`) | Resuelve → `Pro` si trialing/active |
| `customer.subscription.updated` | `subscriptions` (status, `current_period_end`, `cancel_at_period_end`) | Recomputa: active/trialing→`Pro`; past_due→`Pro` en gracia; unpaid/canceled→`Locked` |
| `customer.subscription.deleted` | `subscriptions.status=canceled`, `canceled_at` | → `Locked` |
| `customer.subscription.trial_will_end` (−3 días) | — (solo notifica) | Sin cambio de tier; dispara email "tu prueba termina / se cobrará 29€" |
| `invoice.paid` (o `invoice.payment_succeeded`) | upsert `invoices` (`status=paid`, montos, urls, periodo) | Asegura `active` → `Pro` |
| `invoice.payment_failed` | upsert `invoices` (`status=open`), `subscriptions.status=past_due` | Entra en gracia (`Pro` hasta `grace_deadline`), luego `Locked` |
| `invoice.finalized` / `invoice.created` | upsert `invoices` (`status=open`, "pendiente") | Sin cambio de tier (alimenta "facturas pendientes" en UI) |
| `payment_method.attached` · `customer.updated` (invoice_settings.default_payment_method) | upsert `payment_methods`, `subscriptions.default_pm_id` | Sin cambio de tier (actualiza "método de pago" en UI) |

Regla transversal: **tras cualquier evento que toque `subscriptions`, se recomputa `resolve_tier(user_id)`** (función pura; no hay tier persistido que sincronizar). Job nocturno de **reconciliación** (`subscriptions.list`/`invoices.list`) para curar divergencias por webhooks perdidos.

---

## 6. Rediseño del flujo de registro

Hoy: `sign-up` es un mensaje estático, Clerk en `restricted` (`sign-up/[[...sign-up]]/page.tsx:155-186`; reabrir = 2 pasos, memoria `btt-signup-cerrado`).

### Nuevo flujo (registro público con trial)
1. **Reabrir Clerk sign-up**: restaurar `<SignUp/>` en la página + cambiar sign-up mode a `Public` en el dashboard de Clerk (los 2 pasos ya documentados).
2. **La tarjeta se pide DESPUÉS de crear la cuenta en Clerk**, no antes. Justificación: necesitamos un `user_id` autenticado para (a) crear el Stripe Customer con `metadata.clerk_user_id` y (b) pasar `client_reference_id` al Checkout, de modo que el webhook pueda atar la suscripción al usuario. Pedir tarjeta antes del alta produciría *customers huérfanos* sin identidad.
3. Orden: **Clerk sign-up → (usuario logueado, tier `Locked`) → pantalla "Empieza tu prueba de 7 días" → Checkout (tarjeta) → trialing → acceso `Pro`.**
4. **Gate/paywall**: un guard (front + back) detecta "logueado, sin suscripción activa, sin grant, no admin" y encamina al Checkout. El backend es el gate real: `resolve_tier` → `Locked` → todos los endpoints con `Depends(require(...))` responden 403.

### Coexistencia con "usuarios gratis" (invitación manual)
- Se conserva un camino de **grant manual**: un endpoint/script de admin inserta en `entitlement_grants (user_id, grant_tier='Pro', reason, granted_by)`. Ese usuario **salta el Checkout**: en login, `resolve_tier` ve el grant y da `Pro`. No toca Stripe.
- Así conviven dos mecanismos: **camino de pago** (Checkout→Stripe) y **camino comped** (grant local).

### ⚠️ Riesgo a resolver antes de implementar (crítico)
- El backend **hoy casi no tiene `Depends(require)`**: solo Market Analysis, Market Sentiment y el portal de API (`policy.py:13-15`). El Backtester, Ticker Analysis y el Baúl **no están gateados en backend** → un `Locked` no los bloquearía server-side. Para que "sin pagar = sin producto" sea real hay que **añadir `require()` a los endpoints de producto** (o un guard global de suscripción), no basta con el menú.
- El frontend `useEntitlements()` es **optimista** (`lib/entitlements.ts:96-100`): mientras carga/error da acceso. Para el paywall hay que **volverlo fail-closed** (o pintar el paywall solo desde un estado ya cargado). El gate de verdad debe ser el backend.

---

## 7. Migración de usuarios existentes ("reset")

Objetivo del cliente: que los usuarios actuales pasen por el nuevo flujo de trial.

### Mecanismo propuesto (cutover suave, no duro)
1. **Antes del cutover**: crear grants de **gracia** (no trial) para todos los usuarios actuales conocidos: `entitlement_grants (user_id, grant_tier='Pro', reason='migración', expires_at=<fecha de corte comunicada>)`. Durante la gracia siguen viendo el producto igual que hoy. **No reciben trial de 7 días** (decisión confirmada #4): ya usan el producto; al llegar la fecha de corte deben suscribirse (cobro directo, sin trial).
2. **Cambiar `DEFAULT_TIER` de `Beta` a `Locked`** (`policy.py:26`) y activar los `require()` en los endpoints de producto. Sin el paso 1, esto **bloquearía a todos de golpe** (cutover duro) — por eso los grants con gracia.
3. **Admins internos** (Jaume/Álvaro/Jesús/Adrián): grant `grant_tier='Admin'` sin `expires_at`, o allowlist por env. No pasan por Stripe (PREGUNTA #1).
4. Durante la gracia, la app muestra banner "activa tu suscripción" que lleva al Checkout. Al **expirar el grant** (`expires_at`), `resolve_tier` cae a `Locked` → paywall. El usuario inicia trial/pago cuando quiera.

### Datos guardados durante la transición
- Estrategias, datasets, backtests están **keyed por `user_id`** en `users.duckdb` (`init_db.py` scoping) y **no se tocan** por un cambio de tier: bloquear solo restringe acceso a features, **no borra datos**. Al suscribirse, mismo `user_id` → datos intactos.

### Riesgos
- **Cutover duro accidental** si se cambia `DEFAULT_TIER`/`require()` sin sembrar los grants primero → todos bloqueados. Orden estricto: grants → luego endurecer.
- **Frontend optimista** puede aparentar acceso tras expirar el grant hasta que carga el estado real → confirmar fail-closed (§6).
- **Deliverability**: el aviso de "activa tu suscripción" depende de email; si no llega, el usuario ve el paywall sin contexto.
- **Percepción**: beta-testers que hoy tienen todo gratis pueden vivir el paso a 29€ como degradación → mensaje y ventana de gracia importan (PREGUNTA #5).
- **Trial repetido**: usuarios migrados que ya "probaron" el producto ¿tienen derecho a otro trial de 7 días? (PREGUNTA #8).

---

## 8. Sección de billing en frontend — especificación mínima

Base: el placeholder `BillingTab` (`ApiConsole.tsx:305-341`) y la interfaz `Billing` (`lib/api_console.ts:55-61`) hoy pintan `stripe.note` y `invoices:[]`. La versión real (nuevo `GET /api/billing/me`) debe entregar:

### Datos a mostrar
- **Suscripción**: `status` (trialing/active/past_due/canceled), nombre de plan, precio (**29 €/mes**, `currency='eur'`), `current_period_end` (fecha de próxima renovación), `trial_end` (si trialing), `cancel_at_period_end` (si va a cancelarse).
- **Método de pago**: `brand` + `last4` + `exp_month/exp_year` (de `payment_methods`; nunca PAN).
- **Facturas**: lista `[{date, amount, currency, status: paid|pending|failed, hosted_invoice_url, invoice_pdf}]` — separables en "pagadas" y "pendientes" (`status=open`).

### Acciones (mínimas)
- **Gestionar facturación / actualizar tarjeta / cancelar** → botón que abre una **Stripe Billing Portal Session** (backend crea la sesión, redirige). El Billing Portal cubre out-of-the-box: actualizar PM, cancelar, ver/descargar facturas → **minimiza UI propia** y cumple "billing mínimo".
- **Ver/descargar factura** → enlace directo a `hosted_invoice_url` / `invoice_pdf` (servidos por Stripe).
- **Empezar prueba / arreglar pago** (si `Locked` o `past_due`) → botón a Checkout / Billing Portal.

**Recomendación:** apoyarse en el **Stripe Billing Portal** para todas las acciones de gestión; nuestra página solo muestra el resumen (estado + próxima factura + método de pago + historial) y un botón "Gestionar facturación". Es lo más barato de construir y lo más seguro (Stripe gestiona el PCI y los flujos).

### Env vars nuevas necesarias (para Fase 2)
`STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_PRICE_ID_MONTHLY_EUR`, `STRIPE_PUBLISHABLE_KEY` (frontend), `EDGECUTE_BILLING_DB_PATH`, `BILLING_TRIAL_DAYS` (=7), `BILLING_GRACE_DAYS`, URLs de retorno del Checkout/Portal, y rellenar `UPGRADE_URL` (`config.py:58`).

---

## PREGUNTAS ABIERTAS PARA ADRIAN

### ✅ Resueltas (2026-08-16)
- **#1 Admin** → siempre a mano (allowlist / `grant_tier='Admin'`), fuera de Stripe.
- **#2 Alcance del plan de 29 €** → = tier `Pro` (`policy.py:84-100`): incluye Market Analysis; excluye Market Sentiment, portal de API, preview.
- **#3 Cancelación** → hasta fin de periodo (`cancel_at_period_end=true`), sin reembolso/prorrateo.
- **#8 Trial** → único por identidad (email + card fingerprint, no `user_id`); migrados sin trial nuevo → estado `gracia` con fecha de corte.

### ⏳ Pendientes de decisión
4. **Ventana de gracia en `past_due`**: ¿cuántos días se mantiene el acceso tras un cobro fallido antes de cortar? ¿Usamos el dunning/Smart Retries de Stripe o un `grace_deadline` propio?
5. **Comunicación del "reset" a usuarios actuales**: ¿qué mensaje y qué fecha de corte (`expires_at`) les damos? ¿Email + banner in-app?
6. **Fiscalidad (IVA / facturación española-UE)**: ¿activamos **Stripe Tax**? ¿Recabamos datos fiscales (autónomo/empresa, NIF) para las facturas? Afecta al contenido de `invoices` y al Checkout.
7. **¿Un único plan (29 €/mes) o habrá anual/variantes?** Define cuántos Prices creamos en Stripe.
