# Edgecute — Sistema de Entitlements y Tiers

## Visión general

Sistema granular de permisos por tier, diseñado para:
- Arrancar con todo Free (sin restricciones)
- Activar límites feature a feature sin reescribir código
- Escalar a API pública cuando se decida monetizar

**Fuente de verdad única:** `backend/app/entitlements/policy.py`

---

## Arquitectura

```
backend/app/entitlements/
├── policy.py      ← tabla declarativa (FUENTE DE VERDAD)
├── checker.py     ← can(), limit(), consume()
├── usage.py       ← contadores en Redis (TTL automático)
└── middleware.py  ← Depends() para FastAPI

frontend/src/lib/
└── entitlements.ts ← hook useEntitlements() + fetch
```

---

## Tiers disponibles

| Tier | Descripción | Cómo se asigna |
|------|-------------|----------------|
| Free | Plan por defecto | Cualquier usuario nuevo |
| Mid | Plan intermedio | Stripe webhook → Clerk publicMetadata.tier |
| Pro | Plan completo | Stripe webhook → Clerk publicMetadata.tier |

El tier se lee de `user.publicMetadata.tier` (Clerk).
Si no existe → fallback a `"Free"`.

---

## Tabla de features (policy.py)

Cada feature tiene una clave string con formato `modulo.accion`.

| Feature key | Tipo | Free | Mid | Pro |
|-------------|------|------|-----|-----|
| `backtester.run` | boolean | ✅ | ✅ | ✅ |
| `backtester.surface_3d` | boolean | ❌ | ✅ | ✅ |
| `backtester.runs_per_day` | limit (-1=∞) | 5 | 50 | -1 |
| `backtester.date_range_years` | limit (-1=∞) | 2 | 4 | -1 |
| `ticker.edgie_assessment` | boolean | ✅ | ✅ | ✅ |
| `ticker.edgie_messages_per_day` | limit (-1=∞) | 5 | -1 | -1 |
| `vault.access` | boolean | ✅ | ✅ | ✅ |
| `vault.max_strategies` | limit (-1=∞) | 3 | 25 | -1 |
| `api.access` | boolean | ❌ | ❌ | ✅ |
| `api.runs_per_month` | limit (-1=∞) | 0 | 0 | -1 |

> **MVP:** todos los valores en `-1` / `True` (ilimitado).
> La tabla de arriba es la propuesta para cuando se active la monetización.
> Para cambiar un límite: editar `policy.py` únicamente.

---

## Cómo funciona en el código

### Backend — proteger un endpoint

```python
from app.entitlements.middleware import require, consume

# Solo verificar acceso (boolean)
@router.post("/surface")
async def run_surface(
    _access = Depends(require("backtester.surface_3d")),
):
    ...

# Verificar acceso Y consumir un uso del límite
@router.post("/run")
async def run_backtest(
    _access = Depends(require("backtester.run")),
    _quota  = Depends(consume("backtester.runs_per_day")),
):
    ...
```

### Frontend — mostrar/bloquear features

```tsx
import { useEntitlements } from '@/lib/entitlements'

function MyComponent() {
  const { can, limit, used, remaining } = useEntitlements()

  // Bloquear feature completo
  if (!can('backtester.surface_3d')) {
    return <LockedFeature requiredTier="Pro" />
  }

  // Mostrar uso y límite
  return (
    <div>
      <p>Backtests hoy: {used('backtester.runs_per_day')} / {limit('backtester.runs_per_day')}</p>
      <button disabled={remaining('backtester.runs_per_day') === 0}>
        Ejecutar
      </button>
    </div>
  )
}
```

---

## Contadores de uso (Redis)

Los límites numéricos se trackean en Redis con TTL automático.

```
Clave: usage:{user_id}:{feature}:{ventana}
Ejemplos:
  usage:user_abc:backtester.runs_per_day:2026-06-23
  usage:user_abc:ticker.edgie_messages_per_day:2026-06-23
  usage:user_abc:api.runs_per_month:2026-06
```

- Ventana `day` → TTL 24 horas
- Ventana `month` → TTL 31 días
- Si Redis no está disponible → fallback permisivo (no bloquea)

---

## Endpoint de permisos

```
GET /api/users/me/entitlements
Authorization: Bearer <clerk_token>

Response:
{
  "tier": "Free",
  "entitlements": {
    "backtester.run": true,
    "backtester.surface_3d": false,
    "backtester.runs_per_day": 5,
    ...
  },
  "usage": {
    "backtester.runs_per_day": 2,
    "ticker.edgie_messages_per_day": 0
  }
}
```

El frontend llama este endpoint al montar y cachea con SWR.

---

## Flujo completo de una request protegida

```
Usuario hace click en "Ejecutar Backtest"
    ↓
Frontend: remaining('backtester.runs_per_day') > 0?
    ↓ No → muestra mensaje de límite alcanzado
    ↓ Sí → llama POST /api/backtest/run
    ↓
Backend: Depends(require("backtester.run"))
    → Lee tier de Clerk publicMetadata
    → policy.py: can("Free", "backtester.run") → True ✅
    ↓
Backend: Depends(consume("backtester.runs_per_day"))
    → get_usage(user_id, "backtester.runs_per_day") → 2
    → limit("Free", "backtester.runs_per_day") → 5
    → 2 < 5 → OK, incrementa a 3
    ↓
Backend ejecuta el backtest normalmente
    ↓
Frontend recibe resultado, refresca useEntitlements()
```

---

## Activar tiers reales (cuando se decida)

**Paso 1 — Stripe webhook actualiza Clerk:**
```python
# Al pagar → tier "Pro"
clerk.users.update_metadata(user_id, public_metadata={"tier": "Pro"})

# Al cancelar → tier "Free"  
clerk.users.update_metadata(user_id, public_metadata={"tier": "Free"})
```

**Paso 2 — Cambiar valores en policy.py:**
```python
# De MVP (todo ilimitado):
"backtester.runs_per_day": -1,

# A producción real:
"backtester.runs_per_day": 5,   # Free
```

**Nada más.** Todos los endpoints y componentes leen de
la política automáticamente.

---

## Compatibilidad con API pública (api-jesus)

Cuando se active la API pública de Yisus, conectar
`gating.py` con `policy.py`:

```python
# Una línea conecta ambos sistemas
from app.entitlements.policy import can as entitlement_can

def edgecute_policy(principal, module, action):
    tier = get_tier_for_principal(principal)
    return entitlement_can(tier, f"{module}.{action}")

set_policy(edgecute_policy)
```

Una sola fuente de verdad controla tanto la app
como la API pública.

---

## Fases de implementación

| Fase | Qué | Estado |
|------|-----|--------|
| 1 — Esqueleto backend | policy.py, checker.py, usage.py, middleware.py, endpoint /me/entitlements | ⏳ En curso |
| 2 — Hook frontend | useEntitlements(), LockedFeature, aplicar en UI | ⏳ Pendiente |
| 3 — Stripe | Webhooks → actualizar tier en Clerk | ⏳ Pendiente |
| 4 — Activar restricciones | Cambiar valores en policy.py | ⏳ Pendiente |
| 5 — API pública | Conectar con gating.py de Yisus | ⏳ Post-MVP |

---

## Piezas ya disponibles (no hay que construir)

- ✅ Clerk JWT + `get_current_user_id` (auth/clerk.py)
- ✅ `tier` en `publicMetadata` de Clerk (ya se lee en Sidebar)
- ✅ `gating.py` de Yisus (patrón can_access enchufable)
- ✅ `store.py` de Yisus (usage_ledger base)
- ✅ Redis para contadores (redis_client.py)
- ✅ Portal `/developers` (developers/page.tsx)

---

*Última actualización: junio 2026*
*Arquitecto: Adrian Garcia*
