"""Billing / subscription state (Stripe integration).

Fase 2A ships ONLY the isolated persistence layer (store + config). It imports
no Stripe SDK, touches no request path, and is fully dormant: nothing here
affects access until later phases wire it in behind BILLING_ENABLED. See
docs/FASE1_DISENO_TRIAL_SUSCRIPCION_STRIPE.md.
"""
