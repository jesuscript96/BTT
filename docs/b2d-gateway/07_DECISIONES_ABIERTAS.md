# 07 — Preguntas abiertas y defaults técnicos

> **Regla de este doc:** separar lo que es **tuyo (producto/negocio) y queda SIN resolver**, de lo
> que es un **default técnico reversible** que aplico salvo que digas otra cosa. Yo **no** decido
> precios, tiers ni a quién se bloquea. Nada de esto bloquea construir el MVP.

---

## El MVP es una API **modulada por módulos**

- El sistema se organiza en **módulos** (dominios): `backtest` (MVP), y después `screener`,
  `ticker-analysis`, `optimization`… Cada módulo es un **paquete autocontenido** que expone sus
  endpoints, sus secciones de datos y un **tag de gating**.
- **Gating = capa transversal fina**: cada módulo/feature lleva una marca de "acceso", y la
  **política** (qué es gratis, qué es de pago, a quién, cuándo) se aplica por config **después**.
  Técnicamente es un `if can_access(api_key, module)`; el problema no es ese `if`, es la política.
- El MVP entrega: el mecanismo de **metering** (ledger de uso) + el **hook de gating por módulo**.
  **No** entrega una política de precios. Eso lo decides tú cuando quieras, sin tocar código nuevo.

---

## A. Preguntas TUYAS (producto/negocio) — abiertas, NO las resuelvo yo

> Ninguna bloquea el MVP. El código deja el hook listo; tú pones la política cuando toque.

- **Q1 — Política de acceso por módulo.** ¿Qué módulos/funciones son gratis y cuáles de pago?
  *(El código solo necesita saber "este módulo es gateable"; el reparto gratis/pago es tuyo.)*
- **Q2 — A quién y cuándo se bloquea.** ¿Free por defecto y se abre/cierra según qué? *(Diferido.)*
- **Q3 — Modelo de cobro y precios.** Stripe (vía los tiers de la app), créditos, suscripción,
  límites… *(Diferido; lo trabajas tú aparte.)*
- **Q4 — Nombres comerciales y dominio.** Producto, paquete npm, dominio de la API. *(Diferido.)*

---

## B. Defaults TÉCNICOS (los aplico salvo que digas lo contrario — son MÍOS, no tu firma)

> Son decisiones de ingeniería con un default sensato. Cámbialos cuando quieras; son reversibles.

| Tema | Default técnico | Reversible a |
|---|---|---|
| Dónde vive la API | `backend/app/api_public/` (ASGI aparte, mismo repo, guard de imports) | microservicio |
| Lenguaje del MCP | TypeScript estricto | Python |
| Ejecución del backtest | síncrona con cap de tamaño (como el `/backtest` actual) | jobs async (v2) |
| Persistencia mínima | un Postgres: `api_keys` + `usage_ledger`; planes/flags = config | + Redis (v2) |
| Rate-limit | en proceso | Redis (v2) |
| Exports | GCS (ya hay creds) | S3 |
| Identidad del owner de la key | `user_id` de Clerk (puente con la app) | propio |

> El **cap de tamaño** por request es técnico (acota latencia/coste para que la API síncrona termine
> dentro del timeout). Su **valor** y **si depende del plan** es parte de Q1/Q3 → tuyo, diferido.

---

## C. Lo que TÚ ya dijiste explícitamente (no es mi propuesta, es tu instrucción)

- El **MCP es solo build-time** (codegen + componentes + docs); el runtime es la app del trader → API.
- La API es **modulada por módulos**.
- La **submodularización de componentes** del resultado (el trader elige piezas sueltas).
- El **gating/monetización se decide más tarde**; técnicamente no es el problema.

---

## Qué hace falta para arrancar el MVP

**Nada de la sección A.** Con los defaults de B y tus instrucciones de C, el MVP se construye:
una API modular (módulo `backtest`), con metering y hook de gating listos pero **sin política**, y
el MCP build-time. Cuando decidas A, es config.

> Si quieres cambiar algún default de B, dímelo y actualizo el plan. Si no, asumo B tal cual.
