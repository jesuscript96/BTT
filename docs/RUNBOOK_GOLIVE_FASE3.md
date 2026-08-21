# Runbook — Go-live Fase 3 (billing + Clerk producción)

> **Objetivo:** todo en PROD (billing live + Clerk instancia de producción). Acordado 2026-08-21.
> **Ver también:** `docs/FASE3_FLUJO_SUSCRIPCION_LANZAMIENTO.md` (diseño+decisiones),
> `docs/RUNBOOK_CUTOVER_BILLING_STAGING.md` (cutover billing, base para prod).

Regla de oro: la data de estrategias/backtests **vive en `users.duckdb`** (nuestra base), no
en Clerk. Clerk solo guarda identidad. Al migrar a Clerk prod los `user_id` **cambian**; la data
no se pierde, se **re-etiqueta** cruzando `old→new` por **email**.

---

## Decisiones fijadas
1. **Admins por EMAIL** (como la cortesía) → sobreviven la migración (email no cambia). Admin
   con revocación instantánea (más sensible).
2. **Días preferenciales = 14 días** (Path B, `trial_overrides`).
3. **Migración Clerk = re-etiquetar por email** (no se conservan user_id; se remapea la data).
4. **Stripe prod**: credenciales LIVE ya disponibles.
5. **Clerk prod**: la instancia nueva da `pk_live`/`sk_live` → al env de prod.

---

## 🟢 BLOQUE 1 — Código + config (sin depender de re-registros)

### 1.1 [Claude] Admins por email
Mismo patrón que la cortesía por email, con **revocación instantánea** (al quitar un email deja
de ser admin al momento). Tabla/lista `admin_emails` + CLI, resuelto vía el email verificado del
JWT. Precedencia: admin > cortesía > store.

### 1.2 [Adrian/Jesús] Claims en Clerk (instancia ACTUAL)
*Sessions → Customize session token* → añadir:
```json
{ "email": "{{user.primary_email_address}}", "email_verified": "{{user.email_verified}}" }
```
+ exigir verificación de email al registro. Sin esto, admin/cortesía por email quedan **inertes**
(fail-closed). Prerequisito para 1.3.

### 1.3 [Claude] Sembrar + validar en STAGING
- Preferenciales 14d (lista de Adrian): `python -m scripts.set_trial_override --user-ids … --days 14`
- Admin emails + comped emails (`scripts/comp_emails.py`, y el equivalente de admin).
- Validar e2e: admin sin gate, cortesía "Gratis", preferencial 14d en Checkout.

---

## 🟠 BLOQUE 2 — Migración Clerk a producción (mientras los colegas se re-registran)

### 2.1 [Adrian/Jesús] Crear instancia Clerk PROD
- *Go to prod → Clone development instance* (copia auth/tema, NO usuarios).
- **Dominio**: CNAME para el Frontend API (ej. `clerk.edgecute.com`) → esperar verificación+SSL.
- **OAuth propio**: crear apps OAuth de Google y Discord (en dev eran las compartidas de Clerk),
  meter client id/secret en Clerk, configurar redirect URIs.
- Obtener `pk_live` / `sk_live` + issuer/JWKS de la instancia prod.
- Repetir los claims JWT (`email`/`email_verified`) en la instancia PROD.

### 2.2 [colegas] Re-registro en prod
Cada usuario existente se registra en la instancia nueva (mismo email) → obtiene `user_id` nuevo.

### 2.3 [Claude] Script de re-etiquetado por email
- Exportar `(old_user_id, email)` de la instancia dev (Clerk API).
- Obtener `(new_user_id, email)` de la instancia prod (Clerk API).
- Cruzar por email → mapa `old→new`.
- `UPDATE` en `users.duckdb` de las columnas owner (estrategias, backtests, saved_queries,
  datasets) `old→new`.
- Re-sembrar `trial_overrides` (preferenciales) por el nuevo `user_id`.
- Admin/cortesía por email **NO** requieren remapeo (sobreviven por email).

### 2.4 [Adrian/Jesús] Swap de keys Clerk en env PROD
- Backend (Coolify): `CLERK_SECRET_KEY=sk_live`, `CLERK_PUBLISHABLE_KEY=pk_live`,
  `CLERK_ISSUER`/`CLERK_JWKS_URL` de la instancia prod.
- Frontend (Vercel): `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=pk_live` (+ claves relacionadas).

---

## 🔴 BLOQUE 3 — Cutover billing a producción

### 3.1 [Claude] Merge develop → main
Todo el código de billing Fase 2/3 pasa a main (prod despliega de main).

### 3.2 [Adrian/Jesús + Claude] Stripe LIVE
- Product + Price **29 €/mes EUR** (modo LIVE).
- Billing Portal (config).
- Webhook LIVE → `https://<prod-backend>/api/billing/webhook` (9 eventos), guardar `whsec_…` live.
- Claves `sk_live`/`pk_live` de Stripe.

### 3.3 [Adrian/Jesús] Env PROD (backend Coolify)
- `BILLING_ENABLED=true`
- `STRIPE_SECRET_KEY` (live), `STRIPE_PUBLISHABLE_KEY` (live), `STRIPE_PRICE_ID_MONTHLY_EUR` (live),
  `STRIPE_WEBHOOK_SECRET` (live whsec)
- `BILLING_ADMIN_USER_IDS` (ids prod — o vacío si todo va por admin_emails)
- `EDGECUTE_BILLING_DB_PATH` en **volumen persistente** (mount, como en staging)
- `BILLING_SUCCESS_URL`/`CANCEL_URL`/`PORTAL_RETURN_URL` (o se derivan del origin)

### 3.4 [Adrian/Jesús] Env PROD (frontend Vercel)
- `NEXT_PUBLIC_BILLING_ENABLED=true`
- `NEXT_PUBLIC_API_URL` → backend de prod

### 3.5 [Claude] Sembrar prod
- admin_emails + comped_emails (CLI, en el store de prod).
- preferenciales 14d por el nuevo `user_id`.
- (migración de usuarios actuales a "en prueba" según se decida.)

### 3.6 [Claude + Adrian] Global sign-out + e2e
- Forzar cierre de sesión global (revocar sesiones Clerk prod) → al re-entrar, gate de tarjeta.
- Prueba e2e con tarjeta real de bajo importe o test según Stripe: alta → gate → tarjeta →
  "En prueba" → acceso.

---

## Riesgo
Lo arriesgado NO es el remapeo (script por email, ~15 usuarios, trivial), sino **montar Clerk
prod**: dominio (CNAME + propagación) y OAuth propio (Google/Discord), y que la gente se
re-registre a tiempo. Stripe está desbloqueado. Hacer Clerk prod ANTES del cutover billing para
sembrar con los `user_id` definitivos.
