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

## 🟢 BLOQUE 1 — Código + config (sin depender de re-registros) — ✅ COMPLETO 2026-08-21

### 1.1 [Claude] ✅ Admins + preferenciales por email (develop `d7d9c36`)
Mismo patrón que la cortesía por email, con **revocación instantánea**. Tablas `admin_emails` y
`trial_override_emails` en el store; `_reconcile_identity_email` (admin > cortesía, único grant
por user_id, idempotente) + `_reconcile_trial_override_email` (siembra one-shot UNA vez, nunca
re-arma → el trial preferencial no recicla). Resuelto vía el email verificado del JWT. Precedencia
admin > cortesía > store. **Mejora:** los preferenciales ahora son por email (antes user_id) →
migration-proof, se re-siembran solos bajo el nuevo user_id (elimina el re-seed del Bloque 2).
CLIs: `scripts/admin_emails.py`, `scripts/pref_trial_emails.py --days`, `scripts/comp_emails.py`.
16 tests + suite billing 100/100.

### 1.2 [Adrian] ✅ Claims en Clerk (instancia ACTUAL)
*Sessions → Customize session token* (Name `__session`) → añadido y **guardado**:
```json
{ "email": "{{user.primary_email_address}}", "email_verified": "{{user.email_verified}}" }
```
Preview user confirmó `email_verified: true` (booleano). Backend `_claim_is_true` acepta bool/str.

### 1.3 [Claude] ✅ Validado e2e en STAGING (store real `/data/btt_staging_billing/…`)
Sembrado con dummies vía servicio desplegado + limpieza total: admin-email → Admin/admin (gate
resolve_tier=Admin), comped-email → Pro/comped (gate=Pro), pref-email → override 14d, revocar →
Locked+grant borrado. Listas REALES se siembran en el CUTOVER (Bloque 3.5), no antes.

---

## 🟠 BLOQUE 2 — Migración Clerk a producción (mientras los colegas se re-registran)

### 2.1 [Adrian/Jesús] Crear instancia Clerk PROD  — decisiones: **app.edgecute.com** + **Google & Discord**
- *Create production instance → Clone from development* (copia auth/tema, NO usuarios).
- **Dominio = `app.edgecute.com`**: Clerk da varios CNAME (`clerk.`, `accounts.`, `clkmail.`,
  `clk._domainkey…`) bajo `edgecute.com` → crearlos en el proveedor DNS → esperar verificación+SSL
  (propaga, minutos-horas). La landing `www.edgecute.com` (repo aparte) no se toca.
- **OAuth propio (obligatorio en prod):**
  - **Google**: Google Cloud Console → APIs & Services → Credentials → OAuth client ID (Web) →
    pegar Client ID/Secret en Clerk prod + añadir el **Authorized redirect URI** que Clerk muestra.
  - **Discord**: Discord Developer Portal → New Application → OAuth2 → Client ID/Secret a Clerk +
    añadir el redirect URI de Clerk.
- Obtener `pk_live` / `sk_live` + issuer/JWKS de la instancia prod.
- **Repetir los claims JWT** (`email`/`email_verified`) en la instancia PROD (NO se heredan).

### 2.2 [colegas] Re-registro en prod
Cada usuario existente se registra en la instancia nueva (**mismo email**) → obtiene `user_id` nuevo.
El email es la clave del remapeo, así que debe coincidir exactamente.

### 2.3 [Claude] Re-etiquetado por email — `scripts/clerk_remap.py` (LISTO, probado e2e)
```bash
# en el contenedor de prod (backend/), keys por env, NUNCA hardcodeadas:
python -m scripts.clerk_remap dump --clerk-secret "$CLERK_DEV_SECRET"  --out dev.json   # instancia actual
python -m scripts.clerk_remap dump --clerk-secret "$CLERK_PROD_SECRET" --out prod.json  # instancia nueva
python -m scripts.clerk_remap build-map --old dev.json --new prod.json --out map.json    # reporta no-emparejados
python -m scripts.clerk_remap apply --map map.json --dry-run     # contar sin escribir
python -m scripts.clerk_remap apply --map map.json               # ejecutar
```
- `apply` introspecciona el esquema y actualiza `user_id` en **toda** tabla que la tenga
  (strategies, saved_queries, datasets, backtest_results, feature_votes/suggestions, …).
- **NO** hace falta re-sembrar preferenciales: al ser por email se re-siembran solos en el 1er /me.
- Admin/cortesía por email **NO** requieren remapeo (sobreviven por email).
- ⚠️ **users.duckdb se sube a GCS al apagar** → correr el `apply` con la app parada, o forzar la
  subida después, para que el cambio persista. Los emails no re-registrados quedan en el reporte
  (su data sigue bajo el user_id viejo hasta que se registren).

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

### 3.5 [Claude] Sembrar prod (todo por EMAIL → sin depender de user_id)
- admin_emails (`scripts/admin_emails.py --add … --granted-by adrian`).
- comped_emails (`scripts/comp_emails.py --add …`).
- preferenciales 14d (`scripts/pref_trial_emails.py --add … --days 14`). Se materializan solos en
  el 1er /me de cada usuario (no hay que conocer su user_id).
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
