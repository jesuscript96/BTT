# Runbook — Cutover de billing en STAGING (Fase 2G)

> **Objetivo:** encender el sistema de pagos (2A–2G) en **staging** con Stripe en **modo test**, validarlo de punta a punta, y NO tocar prod. Prod (`main`) sigue idéntico hasta que decidamos promover.
> **Rama:** `develop` (auto-deploy a staging). **Fecha:** 2026-08-19.

## Principio de dormancia
Todo el código de billing está detrás de dos flags, **ambos off por defecto**:
- Backend: `BILLING_ENABLED` (monta el router `/api/billing/*` y hace que `get_tier` lea el store local en vez de Clerk).
- Frontend: `NEXT_PUBLIC_BILLING_ENABLED` (muestra el enlace/sección de facturación y el `BillingGuard`).

Con los flags off, staging y prod se comportan **exactamente como hoy**. El cutover = encender los flags **en staging** tras preparar Stripe y sembrar los grants.

> **Nota clave:** NO hace falta cambiar `DEFAULT_TIER` (sigue `Beta` en código). Con `BILLING_ENABLED`, `get_tier` enruta por `resolve_tier`, cuyo default propio ya es `Locked`. Encender el flag flipa el fail-closed automáticamente.

---

## Orden ESTRICTO (no saltarse el orden)

### Paso 1 — Stripe (modo TEST) · dashboard.stripe.com
1. **Producto + Price:** crea un producto "Edgecute Pro" con un **Price recurrente mensual en EUR de 29,00 €**. Copia el `price_id` (`price_…`).
2. **Billing Portal:** actívalo (Settings → Billing → Customer portal). Configura cancelación = **al final del periodo** (coincide con la decisión #3). Permite actualizar método de pago y ver facturas.
3. **Webhook:** crea un endpoint apuntando a `https://<STAGING_BACKEND>/api/billing/webhook`. Suscribe estos eventos (matriz §5):
   `checkout.session.completed`, `customer.subscription.created`, `customer.subscription.updated`, `customer.subscription.deleted`, `invoice.paid`, `invoice.payment_failed`, `invoice.finalized`, `payment_method.attached`, `customer.updated`.
   Copia el **signing secret** (`whsec_…`).
4. **Claves test:** copia `sk_test_…` (secret) y `pk_test_…` (publishable).

### Paso 2 — Env del BACKEND en staging (Coolify → app `develop`)
Añade (test mode):
```
BILLING_ENABLED=true
STRIPE_SECRET_KEY=sk_test_…
STRIPE_WEBHOOK_SECRET=whsec_…
STRIPE_PRICE_ID_MONTHLY_EUR=price_…
BILLING_SUCCESS_URL=https://<STAGING_FRONTEND>/billing?session_id={CHECKOUT_SESSION_ID}
BILLING_CANCEL_URL=https://<STAGING_FRONTEND>/billing?checkout=cancel
BILLING_PORTAL_RETURN_URL=https://<STAGING_FRONTEND>/billing
BILLING_ADMIN_USER_IDS=<clerk_id_jaume>,<clerk_id_alvaro>,<clerk_id_jesus>,<clerk_id_adrian>
EDGECUTE_BILLING_DB_PATH=/data/btt_staging_billing/edgecute_billing.sqlite   # dentro del mount del Paso 2b
```
- ⚠️ **Las 3 URLs de retorno (`BILLING_SUCCESS_URL`/`CANCEL`/`PORTAL_RETURN_URL`) son OPCIONALES**: el frontend las envía en el body derivadas de `window.location.origin` (`SubscriptionPanel.tsx`), y el backend usa `body or env` (`service.py`). Ponlas solo como fallback si alguna vez se llama la API sin frontend.

### Paso 2b — Mount persistente para el store de billing (IMPRESCINDIBLE)
> **Verificado (2026-08-19):** el default cae en el CWD efímero, y en el contenedor de staging **no hay mount en ninguna ruta `/data/…` interna** (los binds del host van a `/lake`, `/tmp/btt_intraday_cache`, `/app/users.duckdb`). Sin este paso, el store se borra en cada redeploy.

En Coolify → app `develop` → **Storages** → Add (Bind mount / Directory):
- **Source (host):** `/data/btt_staging_billing`
- **Destination (contenedor):** `/data/btt_staging_billing`

Crea la carpeta del host con permisos restrictivos (no heredar el `777` de la caché):
```bash
mkdir -p /data/btt_staging_billing && chmod 750 /data/btt_staging_billing
```
- ⚠️ `EDGECUTE_BILLING_DB_PATH` **debe** apuntar **dentro** de ese mount. Es reconstruible desde Stripe (`reconcile_all`), pero mejor persistir. Detalle de seguridad/persistencia: `docs/ARQUITECTURA_BILLING.md` §12.
- ⚠️ No pongas aún `BILLING_ENABLED=true` si no has hecho el Paso 3 (sembrar grants), o los usuarios existentes de staging caerán a `Locked` de golpe. En staging con pocos usuarios da igual, pero mantén el orden por costumbre.

### Paso 3 — Sembrar grants de trial (ANTES de encender el flag en prod; en staging opcional)
Desde el contenedor de staging, en `backend/`:
```bash
# previsualizar
python -m scripts.seed_migration_trials --dry-run
# sembrar de verdad (usuarios de Clerk; salta admins de BILLING_ADMIN_USER_IDS)
python -m scripts.seed_migration_trials
```
Idempotente: re-ejecutar no acorta trials existentes. En staging puedes probar con `--user-ids u_test1,u_test2`.

### Paso 4 — Env del FRONTEND (staging)
`NEXT_PUBLIC_BILLING_ENABLED=true` y `NEXT_PUBLIC_API_URL=https://<STAGING_BACKEND>/api`, y redeploy del frontend de staging.

> **Alternativa rápida para validar la UI (sin frontend de staging):** correr el frontend en local apuntando al backend de staging:
> ```bash
> cd frontend
> NEXT_PUBLIC_BILLING_ENABLED=true NEXT_PUBLIC_API_URL=https://<STAGING_BACKEND>/api npm run dev
> ```
> (coincide con tu preferencia de validar en local antes de integrar).

### Paso 5 — Reabrir sign-up en Clerk (solo si vas a probar alta pública)
Restaurar `<SignUp/>` en `sign-up/[[...sign-up]]/page.tsx` + cambiar sign-up mode a **Public** en el dashboard de Clerk (2 pasos, ver memoria `btt-signup-cerrado`). Para validar el flujo de trial de altas nuevas. Para probar solo la migración/paywall no hace falta.

---

## Validación end-to-end (checklist)
Con Stripe en test (tarjeta `4242 4242 4242 4242`, cualquier fecha futura/CVC):

- [ ] **Paywall:** usuario nuevo sin grant/sub → cualquier página de producto redirige a `/billing` → se ve el paywall "Empieza tu prueba".
- [ ] **Checkout + trial:** "Empezar prueba" → Stripe Checkout pide tarjeta → completar → vuelve a `/billing?session_id=…` → `sync` materializa la sub → estado **En prueba** con contador; producto accesible.
- [ ] **Webhook:** en el dashboard de Stripe, el endpoint recibe `checkout.session.completed` + `customer.subscription.created` con 200. El store refleja la sub.
- [ ] **Admin allowlist:** un `BILLING_ADMIN_USER_IDS` entra sin pasar por Stripe (tier Admin).
- [ ] **Grant de migración:** un usuario sembrado en el Paso 3 ve el contador de prueba y accede; al caducar (`expires_at`) → Locked → paywall.
- [ ] **past_due:** forzar fallo (tarjeta `4000 0000 0000 0341` u otra de test que falle al renovar) → banner ámbar, acceso mantenido; al pasar a `unpaid`/`canceled` → Locked.
- [ ] **Portal:** "Gestionar facturación" abre el Billing Portal; cancelar → `cancel_at_period_end` → banner "se cancelará al final del periodo".
- [ ] **Facturas:** aparecen en la sección con enlace a Stripe.
- [ ] **Aislamiento:** prod (`main`) intacto — sus flags siguen off; su store de billing no existe.

---

## Rollback en staging
Poner `BILLING_ENABLED=false` (backend) y `NEXT_PUBLIC_BILLING_ENABLED=false` (frontend) y redeploy → todo vuelve a dormido, comportamiento de hoy. Los grants/subs sembrados quedan en el store pero no se consultan.

## Promoción a prod (cuando staging esté validado) — FUERA DE ESTE RUNBOOK
Merge `develop`→`main`, repetir Pasos 1–5 con Stripe en **modo LIVE** (claves `sk_live_`/`pk_live_`, webhook a la URL de prod), sembrar grants en prod, y encender flags en prod. Orden estricto: **sembrar grants → encender `BILLING_ENABLED`**. Se hará como acción separada y consciente.

⚠️ **Blindaje del store en prod:** usar una carpeta **dedicada y distinta de la de staging** (p. ej. `/data/btt_prod_billing`, permisos `750`), claves LIVE solo en env, y decidir explícitamente el cifrado en reposo. Checklist completa en `docs/ARQUITECTURA_BILLING.md` §12.5. El store de prod **nunca** comparte carpeta ni fichero con el de staging (aislamiento datos test/reales).
