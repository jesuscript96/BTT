# Cutover billing → PROD (Stripe LIVE + envs)  — hoja de ejecución

> **Cuándo:** Bloque 3 del go-live, DESPUÉS de que Clerk prod esté estable y hechos
> los remapeos (ver `RUNBOOK_GOLIVE_FASE3.md`). **Prod despliega de `main`.**
> **Seguridad:** las claves Stripe/Clerk NUNCA van al repo ni al chat. Las escrituras
> a Stripe (crear Price/Webhook) las ejecuta **Adrian** (Claude no puede). Pega los
> secretos SOLO en Coolify/Vercel/Stripe.

---

## Paso 0 — Prerrequisito
`develop` ya contiene **todo lo de main + billing Fase 2/3** (merge `main→develop` hecho
2026-08-21, build verde). Por tanto el cutover de código es un **`develop→main` limpio**
(sin divergencia, verificado con merge-tree).

---

## Paso 1 — Stripe LIVE (Adrian, dashboard en modo **Live**)

> Toggle "Test mode" **OFF** (arriba a la derecha) — todo esto en LIVE.

1. **Product + Price**
   - Products → Add product → nombre `Edgecute` (o el que prefieras; el usuario ve
     "Suscrito a Edgecute", no este nombre).
   - Price: **29,00 EUR**, **Recurring / Monthly**.
   - Copia el **Price ID** (`price_…`, LIVE). → va a `STRIPE_PRICE_ID_MONTHLY_EUR`.

2. **Customer Portal** (para gestionar tarjeta/baja)
   - Settings → Billing → Customer portal → activar; permitir cancelar suscripción
     (cancel at period end) y actualizar método de pago. Guardar.

3. **Webhook** → apuntando al backend de prod
   - Developers → Webhooks → Add endpoint.
   - URL: `https://<BACKEND_PROD>/api/billing/webhook`
   - Eventos (los **10** que procesa el backend):
     ```
     checkout.session.completed
     customer.subscription.created
     customer.subscription.updated
     customer.subscription.deleted
     customer.updated
     invoice.created
     invoice.finalized
     invoice.paid
     invoice.payment_succeeded
     invoice.payment_failed
     ```
   - Tras crearlo, copia el **Signing secret** (`whsec_…`, LIVE). → `STRIPE_WEBHOOK_SECRET`.

4. **API keys (Live)**: Developers → API keys → copia **Secret key** (`sk_live_…`).
   → `STRIPE_SECRET_KEY`. (La publishable NO hace falta: el Checkout es por redirect.)

> Alternativa por Stripe CLI (Adrian, con `stripe login` en modo live), corriendo cada
> línea con el prefijo `!` en el chat:
> ```bash
> !stripe products create --name "Edgecute"
> !stripe prices create --product <prod_id> --unit-amount 2900 --currency eur -d "recurring[interval]"=month
> !stripe webhook_endpoints create --url "https://<BACKEND_PROD>/api/billing/webhook" \
>    --enabled-events checkout.session.completed --enabled-events customer.subscription.created \
>    --enabled-events customer.subscription.updated --enabled-events customer.subscription.deleted \
>    --enabled-events customer.updated --enabled-events invoice.created --enabled-events invoice.finalized \
>    --enabled-events invoice.paid --enabled-events invoice.payment_succeeded --enabled-events invoice.payment_failed
> ```

---

## Paso 2a — Mount persistente DEDICADO del store de billing (IMPRESCINDIBLE)

> Igual que en staging (Paso 2b de `RUNBOOK_CUTOVER_BILLING_STAGING.md`), pero con
> **carpeta PROPIA y DISTINTA** de la de staging — el store de prod NUNCA comparte
> carpeta/fichero con el de staging (aislamiento datos reales/test,
> `ARQUITECTURA_BILLING.md` §12.5). El default cae en el CWD efímero → sin mount el
> store se borra en cada redeploy.

En el host de prod:
```bash
mkdir -p /data/btt_prod_billing && chmod 750 /data/btt_prod_billing
```
En Coolify → app de **prod** → **Storages** → Add (Bind mount / Directory):
- **Source (host):** `/data/btt_prod_billing`
- **Destination (contenedor):** `/data/btt_prod_billing`

## Paso 2b — Env PROD backend (Coolify)

| Variable | Valor |
|---|---|
| `BILLING_ENABLED` | `true` **(el ÚLTIMO en encenderse — tras sembrar, Paso 5)** |
| `STRIPE_SECRET_KEY` | `sk_live_…` |
| `STRIPE_PRICE_ID_MONTHLY_EUR` | `price_…` (live) |
| `STRIPE_WEBHOOK_SECRET` | `whsec_…` (live) |
| `EDGECUTE_BILLING_DB_PATH` | `/data/btt_prod_billing/edgecute_billing.sqlite` (**dentro** del mount 2a, distinto de staging) |
| `BILLING_SUCCESS_URL` | `https://app.edgecute.com/billing?session_id={CHECKOUT_SESSION_ID}` (fallback; el front envía el suyo) |
| `BILLING_CANCEL_URL` | `https://app.edgecute.com/billing?checkout=cancel` (fallback) |
| `BILLING_PORTAL_RETURN_URL` | `https://app.edgecute.com/billing` |
| `BILLING_ADMIN_USER_IDS` | **vacío** (admins van por email ahora) — o ids prod como respaldo |
| `BILLING_COMPED_USER_IDS` | **vacío** (cortesía va por email) |
| `CLERK_SECRET_KEY` | `sk_live_…` (Clerk prod) |
| `CLERK_PUBLISHABLE_KEY` / issuer / JWKS | de la instancia Clerk prod |

> ⚠️ **Orden estricto:** pon TODAS las envs salvo `BILLING_ENABLED`, siembra las
> listas (Paso 5), y SOLO ENTONCES `BILLING_ENABLED=true`. Si enciendes el flag
> antes de sembrar, los usuarios ya migrados caen a `Locked` de golpe.
> ⚠️ Si el store se pierde se reconstruye de Stripe (reconciliación), pero las
> tablas locales (admin/cortesía/preferenciales por email) hay que re-sembrarlas.

---

## Paso 3 — Env PROD frontend (Vercel)

| Variable | Valor |
|---|---|
| `NEXT_PUBLIC_BILLING_ENABLED` | `true` |
| `NEXT_PUBLIC_API_URL` | backend de prod (`https://<BACKEND_PROD>`) |
| `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` | `pk_live_…` (Clerk prod) |

---

## Paso 4 — Código a prod
```bash
git checkout main && git pull
git merge develop --no-edit        # limpio (verificado); prod despliega solo
git push origin main               # auto-deploy Coolify (backend) + Vercel (front)
```

## Paso 5 — Sembrar prod (Claude, en el contenedor de prod, todo por EMAIL)
```bash
python -m scripts.admin_emails      --add <emails-admin>       --granted-by adrian
python -m scripts.comp_emails       --add <emails-cortesia>    --granted-by adrian
python -m scripts.pref_trial_emails --add <emails-pref> --days 14 --granted-by adrian
```
(Se materializan solos en el 1er `/me` de cada usuario — no hace falta su user_id.)

## Paso 6 — Global sign-out + e2e (Adrian + Claude)
1. Revocar sesiones en Clerk prod (o cambiar clave de firma) → todos re-entran.
2. Al re-entrar, quien no sea admin/cortesía ve el **gate de tarjeta** (onboarding).
3. e2e: alta → gate → tarjeta (trial) → acceso; admin sin gate; cortesía "Gratis";
   preferencial con 14d en el Checkout.
4. Verificar que el webhook LIVE marca eventos (Stripe → Webhooks → intentos 2xx).

---

## Checklist de verificación
- [ ] Price LIVE 29€/mes creado, Price ID copiado.
- [ ] Webhook LIVE → backend prod, 10 eventos, secret copiado, primer evento 2xx.
- [ ] Envs backend (Coolify) puestas, `EDGECUTE_BILLING_DB_PATH` en mount persistente.
- [ ] Envs frontend (Vercel) puestas.
- [ ] `develop→main` mergeado y desplegado (backend + front sanos).
- [ ] admin/cortesía/preferenciales sembrados por email.
- [ ] Global sign-out hecho; e2e OK (gate, tarjeta, admin, cortesía, preferencial).
