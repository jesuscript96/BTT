# Handoff go-live — estado y lo que falta (para Jesús)

> **Objetivo:** llevar Edgecute a **producción**: instancia **Clerk de producción**
> (`app.edgecute.com`, dominio propio + OAuth propio) y **cobro Stripe** (29,90 €/mes).
>
> **Estado a 2026-08-22 (madrugada):** casi todo hecho y **verificado en prod**. El
> acceso está **CERRADO/congelado** (billing apagado por flag) hasta terminar. Lo
> único que falta y que necesita tus accesos es **añadir 3 variables al frontend en
> Vercel** (ver §1). Todo lo demás (DNS, backend, Stripe, webhook, mount) ya está.

---

## ✅ Lo que YA está hecho y verificado en prod

- **DNS de Clerk (Hostinger):** 5/5 verificado. `clerk.edgecute.com` sirve el JWKS
  con **cert válido (Let's Encrypt)**. Clerk prod operativo.
- **Código a prod:** `develop → main` mergeado y desplegado (Coolify + Vercel).
- **Backend Clerk (Coolify):** `CLERK_PUBLISHABLE_KEY` + `CLERK_SECRET_KEY` en
  `pk_live/sk_live`. `health 200`, JWKS 200. Verificado.
- **Backend Stripe (Coolify):** todo cargado y medido dentro del contenedor:
  - `STRIPE_SECRET_KEY` (cuenta correcta — encontró el precio).
  - `STRIPE_PRICE_ID_MONTHLY_EUR = price_1U6pcTJXrEpYoMWAcnVTIJr9` (29,90 €/mes,
    producto `prod_V73jXOYpjeAvYs`).
  - `STRIPE_WEBHOOK_SECRET` (`whsec_…`, 39 chars) — **webhook creado** vía API:
    endpoint `we_1U7JHzJXrEpYoMWA2RrKL1z2`, **10 eventos**, apuntando a
    `https://kvcfvkb3e9plgdcwgeq67w24.176.9.117.155.sslip.io/api/billing/webhook`.
  - `EDGECUTE_BILLING_DB_PATH = /data/btt_prod_billing/edgecute_billing.sqlite`
    con **mount dedicado** montado y escribible (aislado de staging).
  - `BILLING_ADMIN_USER_IDS` / `BILLING_COMPED_USER_IDS` **vacíos** (a propósito:
    admins y cortesía van **por email**, con los CLIs).
  - `BILLING_ENABLED = false` (congelado — se enciende el día del lanzamiento).
- **Backup de usuarios viejos:** 14 `email→user_id` de la instancia Clerk dev
  guardados (`/root/clerk_dev_dump.json`) para el remapeo de propiedad por email.
- **Script de remapeo** (`backend/scripts/clerk_remap.py`) ya en la imagen de prod.

---

## 🔴 §1 — LO ÚNICO QUE FALTA DE TU LADO: variables en **Vercel** (frontend)

El frontend en vivo (`app.edgecute.com`) **todavía sirve la instancia Clerk DEV**
(`pk_test…accounts.dev`). Hay que ponerlo en prod. En **Vercel → Settings →
Environment Variables → scope `Production`**:

| Variable | Valor |
|---|---|
| `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` | `pk_live_Y2xlcmsuZWRnZWN1dGUuY29tJA` |
| `CLERK_SECRET_KEY` | `sk_live_…` (el de la instancia Clerk prod) |
| `NEXT_PUBLIC_BILLING_ENABLED` | `false` (se pondrá `true` el día del lanzamiento) |

> ⚠️ `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` se **incrusta en el build**: tras guardar,
> **Deployments → Redeploy → DESMARCAR "Use existing Build Cache"**. Si no, el bundle
> sigue con `pk_test`.
> **NO se tocan:** `NEXT_PUBLIC_API_URL` ni las `NEXT_PUBLIC_CLERK_SIGN_IN_URL /
> SIGN_UP_URL / AFTER_*`. **Nada más se borra.**

Cuando el redeploy termine, se valida que `app.edgecute.com` ya sirva `pk_live`.

---

## 🚀 §2 — Día del lanzamiento (cuando se decida "ya")

Solo quedan interruptores y el remapeo (guion detallado en `CUTOVER_BILLING_PROD.md`):

1. **Clerk prod → Sign-up mode = Public** (abrir registro).
2. Los ~14 usuarios se **re-registran** con su **mismo email**.
3. **Remapeo** de propiedad por email (`scripts/clerk_remap.py`: dump prod →
   build-map → apply) → estrategias/backtests se reconectan al user_id nuevo.
   Nadie pierde datos.
4. **Sembrar** por email (admin / cortesía / preferenciales 14 d) con los CLIs.
5. Encender **los dos flags a la vez**: `BILLING_ENABLED=true` (Coolify) +
   `NEXT_PUBLIC_BILLING_ENABLED=true` (Vercel + redeploy sin caché).
6. **Global sign-out** en Clerk prod + prueba e2e (gate de tarjeta, admin sin gate,
   cortesía "Gratis", preferencial con 14 d en el checkout, webhook 2xx).

---

## Notas de seguridad
- Los secretos (`sk_live`, `whsec`, `sk_secret` de Clerk) viven **solo** en
  Coolify/Vercel/Stripe. **Nunca** en el repo.
- No hace falta `STRIPE_PUBLISHABLE_KEY` (checkout por redirect) ni `CLERK_ISSUER`/
  `CLERK_JWKS_URL` (se derivan de la publishable).
