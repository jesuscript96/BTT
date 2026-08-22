# Handoff go-live — lo que necesitamos de Jesús (accesos DNS + Stripe)

> **Contexto:** estamos llevando Edgecute a **producción de verdad**: instancia
> **Clerk de producción** (dominio propio `app.edgecute.com` + OAuth propio) y el
> **cobro con Stripe** (suscripción 29 €/mes). Casi todo está montado y probado en
> staging; faltan **2 cosas que solo puede hacer quien tiene los accesos** (DNS de
> `edgecute.com` y la cuenta de Stripe). Este doc las deja listas para ejecutar.
>
> **Estado:** instancia Clerk prod creada · OAuth Google + Discord conectados ·
> claims JWT copiados · billing probado e2e en staging (admin/cortesía/preferencial/
> registro-nuevo). **Bloqueado en:** DNS de Clerk (0/5) + Price/webhook de Stripe.

---

## 1) DNS de Clerk — proveedor **Hostinger** (hPanel)

Verificado con `dig`: los 5 registros **NO existen aún** en la zona de `edgecute.com`
(nameservers `*.dns-parking.com` = Hostinger). Clerk **solo verifica**; hay que
**crearlos** en Hostinger. Ninguno está mal — simplemente faltan los 5.

**hPanel → Domains → `edgecute.com` → DNS records → Add record.** Crear estos **5 CNAME**
(Name = valor relativo; Hostinger añade `.edgecute.com` solo):

| Tipo  | Name (relativo)   | Target / Points to                       |
|-------|-------------------|------------------------------------------|
| CNAME | `accounts`        | `accounts.clerk.services`                |
| CNAME | `clerk`           | `frontend-api.clerk.services`            |
| CNAME | `clk._domainkey`  | `dkim1.kd7mj6gectyj.clerk.services`      |
| CNAME | `clk2._domainkey` | `dkim2.kd7mj6gectyj.clerk.services`      |
| CNAME | `clkmail`         | `mail.kd7mj6gectyj.clerk.services`       |

- Targets **exactos** (sin espacios, sin `https://`, sin punto final de más).
- Hostinger **no hace proxy** (no es Cloudflare) → no hay toggle "DNS only".
- Tras guardar: **Clerk → Domains → "Verify configuration"** hasta que quede **5/5**.

---

## 2) Stripe LIVE — cuenta con acceso

Necesitamos dos cosas de la **cuenta LIVE** cuyas claves ya tenemos
(`pk_live_…51U4M…` / `sk_live_…`):

1. **Producto + Price 29 €/mes EUR** en modo **LIVE** → copiar el **`price_…`**.
   - ⚠️ **Debe ser la MISMA cuenta** que las claves `…51U4M…`. Si el producto se
     creó en otra cuenta de la organización, la `sk_live` no lo encontrará y el
     Checkout fallará. (Nos comentaron que al salir de test no se guardó la config
     y tuvieron que rehacer el producto — por eso este check es clave.)
2. **Webhook** (se crea al final, cuando el backend de prod tenga billing activo):
   - URL: `https://<BACKEND_PROD>/api/billing/webhook`
   - Eventos (10): `checkout.session.completed`, `customer.subscription.created`,
     `customer.subscription.updated`, `customer.subscription.deleted`,
     `customer.updated`, `invoice.created`, `invoice.finalized`, `invoice.paid`,
     `invoice.payment_succeeded`, `invoice.payment_failed`.
   - Copiar el **signing secret** (`whsec_…`).
   - Activar el **Customer Portal** (Settings → Billing) con cancelación al fin de periodo.

---

## 3) Variables de entorno de PROD (referencia — valores reales van directos a Coolify/Vercel, NUNCA al repo)

### Backend (Coolify) — **CAMBIAR** las 2 de Clerk
| Variable | Ahora (dev) | → Valor prod |
|---|---|---|
| `CLERK_PUBLISHABLE_KEY` | `pk_test_…` | `pk_live_…` (decodifica a `clerk.edgecute.com`) |
| `CLERK_SECRET_KEY` | `sk_test_…` | `sk_live_…` |
| `CLERK_AUTH_ENABLED` | `true` | *(sin cambio)* |

> No hacen falta `CLERK_ISSUER` ni `CLERK_JWKS_URL`: se derivan de `CLERK_PUBLISHABLE_KEY`.

### Backend (Coolify) — **AÑADIR** Stripe/billing
| Variable | Valor |
|---|---|
| `STRIPE_SECRET_KEY` | `sk_live_…` |
| `STRIPE_PRICE_ID_MONTHLY_EUR` | `price_…` (del paso 2) |
| `STRIPE_WEBHOOK_SECRET` | `whsec_…` (del paso 2) |
| `EDGECUTE_BILLING_DB_PATH` | `/data/btt_prod_billing/edgecute_billing.sqlite` |
| `BILLING_ENABLED` | `true` — **el ÚLTIMO en poner** |

> **NO** poner `BILLING_ADMIN_USER_IDS` / `BILLING_COMPED_USER_IDS` (admins y cortesía
> van por **email**, con los CLIs). **NO** hace falta `STRIPE_PUBLISHABLE_KEY`.

### Backend (Coolify) — **mount persistente** (antes de encender billing)
```bash
mkdir -p /data/btt_prod_billing && chmod 750 /data/btt_prod_billing
```
Coolify → app prod → **Storages** → bind mount `/data/btt_prod_billing` → `/data/btt_prod_billing`.

### Frontend (Vercel) — **CAMBIAR / AÑADIR**
| Variable | Valor |
|---|---|
| `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` | `pk_live_…` |
| `CLERK_SECRET_KEY` | `sk_live_…` |
| `NEXT_PUBLIC_BILLING_ENABLED` | `true` |
| `NEXT_PUBLIC_API_URL` | backend prod *(ya puesto)* |

> Las `NEXT_PUBLIC_CLERK_SIGN_IN_URL` / `SIGN_UP_URL` / `AFTER_*` **no cambian**.
> **Nada más se borra**: el resto de envs (GCS, MotherDuck, Massive, Redis, DuckDB…)
> se quedan igual.

---

## 4) Orden del cutover (para no romper prod)

1. **DNS 5/5 verde** en Clerk (paso 1).
2. Los ~15 usuarios se **re-registran** en prod (mismo email).
3. **Remapeo** de propiedad por email (`scripts/clerk_remap.py`) → estrategias/backtests
   se re-conectan al user_id nuevo (nadie pierde datos).
4. **Swap de claves Clerk** en env prod (backend + Vercel) → cutover de identidad.
5. **Merge `develop → main`** (código a prod).
6. Crear **Price + webhook** Stripe (paso 2) + **mount** + envs Stripe (sin flag).
7. **Sembrar** listas por email (admin / cortesía / preferenciales 14 d).
8. Encender **`BILLING_ENABLED=true`** (backend) + `NEXT_PUBLIC_BILLING_ENABLED=true` (Vercel).
9. **Global sign-out** + prueba e2e en prod.

> Detalle completo: `docs/CUTOVER_BILLING_PROD.md` y `docs/RUNBOOK_GOLIVE_FASE3.md`.
