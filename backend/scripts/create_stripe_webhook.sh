#!/bin/bash
# Crea (o detecta) el webhook de Stripe LIVE para el backend de PROD.
# Lee STRIPE_SECRET_KEY de DENTRO del contenedor (no la expone en el comando).
# Imprime el whsec SOLO si lo crea nuevo (Stripe oculta el secreto tras la creación).
set -e
URL="https://kvcfvkb3e9plgdcwgeq67w24.176.9.117.155.sslip.io/api/billing/webhook"
C=$(docker ps --format '{{.Names}}' | grep '^kvcfvkb' | head -1)
echo "contenedor: $C"
echo "url webhook: $URL"
docker exec -i -e WH_URL="$URL" "$C" /opt/venv/bin/python - <<'PY'
import os, httpx
sk = os.environ.get("STRIPE_SECRET_KEY", "")
url = os.environ["WH_URL"]
if not sk:
    raise SystemExit("STRIPE_SECRET_KEY vacío en el contenedor")
auth = (sk, "")
# 1) ¿ya existe un endpoint con esta URL?
r = httpx.get("https://api.stripe.com/v1/webhook_endpoints",
              params={"limit": 100}, auth=auth, timeout=30)
r.raise_for_status()
existing = [e for e in r.json().get("data", []) if e.get("url") == url]
if existing:
    e = existing[0]
    print("[YA EXISTE] endpoint id:", e["id"])
    print("Stripe NO vuelve a mostrar el whsec de un endpoint ya creado.")
    print("Si NO tienes su whsec guardado: borra este endpoint en el panel/API y re-ejecuta este script.")
    raise SystemExit(0)
# 2) crear
events = [
    "checkout.session.completed",
    "customer.subscription.created",
    "customer.subscription.updated",
    "customer.subscription.deleted",
    "customer.updated",
    "invoice.created",
    "invoice.finalized",
    "invoice.paid",
    "invoice.payment_succeeded",
    "invoice.payment_failed",
]
from urllib.parse import urlencode
data = [("url", url), ("description", "Edgecute prod billing")]
data += [("enabled_events[]", ev) for ev in events]
body = urlencode(data)
r = httpx.post("https://api.stripe.com/v1/webhook_endpoints",
               content=body, auth=auth,
               headers={"Content-Type": "application/x-www-form-urlencoded"},
               timeout=30)
if r.status_code >= 300:
    raise SystemExit(f"ERROR creando webhook: {r.status_code} {r.text[:400]}")
body = r.json()
print("[CREADO] endpoint id:", body.get("id"))
print("eventos:", len(body.get("enabled_events", [])))
print()
print("===== COPIA ESTO A COOLIFY =====")
print("STRIPE_WEBHOOK_SECRET=" + body.get("secret", "(sin secreto?)"))
print("================================")
PY
