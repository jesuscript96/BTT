# PRD de ejemplo — Edgecute Journal (Diario de trading)

> **Qué es este documento.** Un PRD **completo y real** de un **módulo greenfield** (un área
> que **no existe todavía** en el repo), escrito siguiendo el [Manual del PM](GUIA_PRD_EJECUTABLE.md).
> Es el ejemplo de cómo se especifica algo nuevo **anclándolo en los patrones que sí existen**
> aunque la funcionalidad no exista. Trae incluida, en el [Apéndice — Registro de la
> entrevista](#entrevista), la conversación agente↔PM que lo produjo: el agente **preguntó
> primero, redactó después**.
>
> **Por qué el Journal.** El producto hoy resuelve *encontrar* setups (Screener), *diseñarlos*
> (Strategy Builder) y *validarlos* (Backtester). Falta cerrar el círculo del trader real:
> **registrar y revisar sus operaciones** para aprender de sus errores. Es un módulo nuevo, con
> datos propios del usuario, que demuestra que esta guía sirve para mucho más que el backtester.
>
> **Tipo de feature:** Greenfield / área nueva (ver [Apéndice I del manual](GUIA_PRD_EJECUTABLE.md#apendice-i)).

---

## Índice del PRD

- [00 · Índice y trazabilidad (fuentes auditadas)](#s00)
- [01 · Viabilidad (reality check + veredicto)](#s01)
- [02 · PRD: qué, para quién, nomenclatura](#s02)
- [03 · Contrato de datos (modelo, endpoints, errores)](#s03)
- [04 · UI y componentes (pantalla, estados, navegación)](#s04)
- [05 · Arquitectura (dónde vive el código, persistencia, auth)](#s05)
- [06 · Prompt maestro de ejecución (guion del loop)](#s06)
- [07 · Decisiones abiertas](#s07)
- [Apéndice · Registro de la entrevista agente↔PM (la minuta)](#entrevista)

---

<a id="s00"></a>
## 00 · Índice y trazabilidad

**Feature:** Edgecute Journal — diario donde el trader registra sus operaciones **reales**
(manuales), las etiqueta por setup y errores, y revisa su rendimiento (win rate, R medio,
expectancy) para mejorar. Datos **privados por usuario**. **Estado:** PLAN (greenfield).

**Visión en una frase:** *"Un diario para registrar mis trades reales, etiquetar el setup y los
errores, y ver con datos qué setups me dan dinero y qué errores me lo quitan."*

### Fuentes auditadas (verdad anclada en código)

> Aunque el Journal no existe, **el cómo construirlo sí está anclado**: copiamos patrones reales
> de persistencia, auth, migración, navegación y fetch.

| Patrón a reusar | Fichero (fuente) | Qué nos da |
|---|---|---|
| Persistencia por usuario en `users.duckdb` | `app/routers/strategies.py` → `create_strategy()` (líneas 13–60) | patrón exacto: `get_user_db_connection()` + `get_user_db_lock()`, `INSERT … VALUES (?,…)`, luego `upload_user_db()` |
| Auth y scoping por usuario | `app/auth/__init__.py` → `get_current_user_id`, `scope_clause`, `AUTH_ENABLED` | cómo proteger y filtrar por `user_id` |
| Sync de la BD de usuario a GCS | `app/gcs_sync.py` → `upload_user_db()` | persistencia durable tras cada escritura |
| Creación de tablas (migración) | `app/init_db.py` (`saved_queries` línea 159, `strategies` línea 169) | dónde y cómo declarar la tabla `journal_entries` |
| Registro de routers | `app/main.py` (`include_router(...)`, líneas 218–236) + `init_db()` (línea 125) | dónde montar `/api/journal` |
| Forma de un trade (nomenclatura) | `app/services/backtest_service.py` → `_enrich_trades` | reusar claves: `ticker, date, direction, entry_price, exit_price, size, pnl, r_multiple, stop_loss, status, exit_reason` |
| Claves de métricas agregadas | `app/services/backtest_service.py` → `_aggregate_metrics()` | reusar `win_rate_pct, expectancy, payoff_ratio, avg_win, avg_loss` |
| Fetch centralizado FE | `frontend/src/lib/api.ts` (`getStrategies`, `createStrategy`, líneas 175–205) | patrón para `getJournal`, `createJournalEntry`… |
| Navegación lateral | `frontend/src/components/Sidebar.tsx` (entradas `/screener`, `/backtester`…) | cómo añadir la entrada "Journal" |
| Páginas de la app | `frontend/src/app/*/page.tsx` (p. ej. `screener/page.tsx`) | patrón de la página `/journal` |
| Componentes reusables | `frontend/src/components/DataGrid.tsx`, `components/backtester/MetricsCard.tsx`, `strategy-builder/` | tabla, KPIs y formularios |
| Tokens visuales | `.agent/EDGECUTE_DESIGN_SYSTEM.md` | colores P&L (`--ec-profit`, `--ec-loss`), tipografía |
| Reglas de ingeniería | `.agent/CODING_RULES.md` | routers finos, queries parametrizadas, no commitear `*.duckdb` |

**Comprobado que NO existe** (greenfield): `grep -rni "journal" backend/app frontend/src` → sin
resultados de dominio (solo, si acaso, librerías). No duplicamos nada.

---

<a id="s01"></a>
## 01 · Viabilidad

### 1.1 Restricciones y coste

- **Dato nuevo, pequeño.** Cada usuario tendrá decenas–miles de entradas (no millones). Una
  tabla `journal_entries` en `users.duckdb` es más que suficiente; no necesita GCS Parquet ni
  el motor.
- **Mismo patrón ya probado.** `strategies` y `saved_queries` ya viven en `users.duckdb` con
  el mismo ciclo escribir→`upload_user_db()`. El Journal es **otra tabla más** con ese patrón.
- **Latencia.** CRUD y agregación sobre la tabla del usuario: **milisegundos** (DuckDB local).
- **Auth ya existe.** Clerk + `get_current_user_id` + `scope_clause` ya scopea `strategies`;
  reusamos idéntico.

### 1.2 Riesgos y mitigaciones

| Riesgo | Impacto | Mitigación |
|---|---|---|
| Fugar entradas entre usuarios | Privacidad rota | **Todas** las queries con `scope_clause(user_id)`; test que un user no ve las de otro |
| Inconsistencia `pnl`/`r_multiple` (usuario teclea mal) | Stats mentirosas | El backend **recalcula** `pnl` y `r_multiple` desde `entry/exit/size/stop`; no confía en lo que mande el cliente |
| Trades abiertos (sin exit) en las stats | Win rate distorsionado | `status='open'` ⇒ `pnl=null`, **excluidos** de stats hasta cerrarse |
| Taxonomía de setups/errores rígida | No encaja con cómo opera el trader | Empezar con la lista del PM (entrevista §A) pero permitir que evolucione (doc 07) |
| `users.duckdb` no se sube tras escribir | Pérdida de datos al reiniciar | `upload_user_db()` tras cada escritura, igual que `strategies` |

### 1.3 Veredicto

**Viable y de bajo riesgo.** Es "otra tabla con CRUD" sobre infraestructura ya probada
(`strategies`). El valor está en la **capa de trading** (qué se registra y cómo se agrega), no
en la dificultad técnica. **Recomendación:** construir.

---

<a id="s02"></a>
## 02 · PRD: qué, para quién, nomenclatura

### 2.1 Usuarios

| Perfil | Necesidad | Cómo lo sirve el Journal |
|---|---|---|
| **Short-seller de small caps (usuario principal)** | Saber qué setups le dan dinero y qué errores se lo quitan | Registra trades reales con setup/errores y ve stats por setup |
| **Trader en formación** | Crear el hábito de revisar (review) y dejar de repetir errores | Campos de adherencia al plan, estado emocional y nota de revisión |
| **Nosotros (producto)** | Retención y diferenciación frente a Flash Research | Cierra el círculo screener→estrategia→backtest→**ejecución real** |

### 2.2 Jobs-to-be-done

1. **Registrar** un trade real (manual): ticker, dirección, precios, tamaño, stop planificado.
2. **Etiquetar**: setup, errores cometidos, si siguió el plan, estado emocional, nota libre.
3. **Listar y filtrar** sus trades (por fecha, ticker, setup, resultado).
4. **Revisar el rendimiento**: win rate, R medio (expectancy en R), payoff, desglose **por
   setup** y **por error**.
5. **Editar / cerrar / borrar** una entrada (un trade abierto se cierra al añadir el exit).

### 2.3 Alcance del MVP (lo que SÍ se construye ahora)

> **La idea amplia del PM** (de la entrevista): registrar trades reales, **importarlos del
> backtester**, subir **capturas**, ver un **calendario de PnL**, **conectar el broker** y sacar
> estadísticas. El **MVP** se queda en el corazón que ya aporta valor (registro manual + stats por
> setup); lo demás es **Fase 2** (§2.4) — no se construye ahora, pero condiciona el diseño del MVP.

- Tabla `journal_entries` (por usuario) + migración en `init_db.py`.
- Endpoints CRUD `/api/journal` + `/api/journal/stats` (ver doc 03), scopeados por usuario.
- **Recálculo en backend** de `pnl` y `r_multiple` (no confiar en el cliente).
- Soporte de trades **abiertos** (`status='open'`, `pnl=null`) y **cerrados**.
- Página `/journal`: tabla con filtros + cabecera de stats + formulario crear/editar. 4 estados.
- Entrada de navegación "Journal" en el `Sidebar`.
- Taxonomías iniciales de **setup**, **mistake** y **emotional_state** (decididas en la
  entrevista §A; evolucionables).

### 2.4 Fase 2 y Fuera de alcance

**Fase 2 — NO se construye ahora, pero el MVP se diseña para no bloquearla.** Por cada ítem, la
decisión que impone hoy:

| Idea (Fase 2) | Qué decisión impone YA en el MVP (para no cerrarle la puerta) |
|---|---|
| **Importar trades de un backtest guardado** | El contrato del journal usa **las mismas claves de trade** que `_enrich_trades` (import-ready). No se construye el importador, pero el modelo encaja. |
| **Subir capturas/imágenes** del chart | Nada bloqueante hoy (se podrá añadir una columna/relación luego). *Solo se lista.* |
| **Calendario/heatmap de PnL** | El listado guarda `trade_date` y `pnl` por entrada → el calendario podrá derivarse sin migrar datos. |
| **Broker sync** (fills automáticos) | El campo `status` (`open`/`closed`) y el origen manual dejan sitio a un origen "broker" futuro sin romper el esquema. |

**Fuera de alcance — NO se hará (o es otro feature):**
- ❌ Compartir el journal / social.
- ❌ Ejecutar órdenes reales (esto **nunca**: no somos un broker).

**Diferido a Jesús (negocio):**
- ❌ **Gating/monetización** (¿el journal es premium? ¿límite de entradas?): **el PRD no decide
  política** (doc 07 §A).

### 2.5 Glosario de dominio (nomenclatura OFICIAL)

> Reusamos las claves de la forma de trade del backtester (`_enrich_trades`) y de
> `_aggregate_metrics()`. **No renombrar.** Lo nuevo se marca como tal.

| Término | Definición operativa | Unidad | Fuente |
|---|---|---|---|
| `ticker` | símbolo en mayúsculas | — | trade |
| `trade_date` | fecha de la operación (`YYYY-MM-DD`) | fecha | nuevo (≈ `date` del trade) |
| `direction` | `long` \| `short` | enum | trade `direction` |
| `status` | `open` \| `closed` | enum | trade `status` |
| `entry_price` / `exit_price` | precio de entrada / salida | USD | trade |
| `size` | nº de acciones | shares | trade `size` |
| `stop_loss` | stop **planificado** (para calcular R) | USD | trade `stop_loss` |
| `pnl` | resultado en USD (**recalculado**, ver 2.6) | USD | trade `pnl` |
| `r_multiple` | resultado en R (**recalculado**, ver 2.6) | R | trade `r_multiple` |
| `setup` | tipo de setup (enum, ver §A entrevista) | enum | nuevo |
| `mistakes` | lista de errores cometidos (enum múltiple) | enum[] | nuevo |
| `followed_plan` | ¿siguió su plan? | bool | nuevo |
| `emotional_state` | estado emocional (enum) | enum | nuevo |
| `rating` | autovaloración de la ejecución 1–5 | entero | nuevo |
| `notes` | nota libre (texto/markdown) | texto | nuevo |
| `win_rate_pct` | % de trades cerrados ganadores | % | `_aggregate_metrics()` |
| `expectancy` | esperanza por trade (USD) | USD | `_aggregate_metrics()` |
| `avg_r` | R medio por trade cerrado | R | nuevo (media de `r_multiple`) |
| `payoff_ratio` | avg_win / |avg_loss| | ratio | `_aggregate_metrics()` |

**Enums (valores literales — decididos en la entrevista §A):**

```
Setup        = ["gap_and_crap", "pmh_reject", "vwap_reject", "first_red_day",
                "backside", "para_fade", "other"]
Mistake      = ["chased_entry", "no_stop", "moved_stop", "oversized",
                "revenge_trade", "exited_early", "fomo", "other"]
EmotionalState = ["calm", "fomo", "fear", "greed", "tilt"]
```

### 2.6 Reglas de trading (las 5 cosas por regla)

**Regla — cálculo de `pnl` (el backend manda, no el cliente):**
- **Nombre:** `pnl`.
- **Definición:** `status='open'` ⇒ `null`. Cerrado:
  - `long`: `(exit_price - entry_price) * size`
  - `short`: `(entry_price - exit_price) * size`
- **Unidad/rango:** USD, signo libre.
- **Sesión/timeframe:** N/A (operación real, una entrada por trade).
- **Edge case:** si falta `exit_price` o `size` en un trade marcado `closed` ⇒ `400` (no se
  puede cerrar sin salida); el backend **ignora** cualquier `pnl` que mande el cliente y lo
  recalcula.

**Regla — cálculo de `r_multiple`:**
- **Nombre:** `r_multiple`.
- **Definición:** `risk_per_share = |entry_price - stop_loss|`. Si `stop_loss` es `null` o
  `risk_per_share == 0` ⇒ `r_multiple = null`. Si no: `r_multiple = pnl / (risk_per_share * size)`.
- **Unidad/rango:** R (múltiplos de riesgo), signo libre.
- **Edge case:** `entry_price == stop_loss` ⇒ `r_multiple = null` (no dividir por cero) y la UI
  muestra "—"; trade abierto ⇒ `null`.

**Anti-lookahead: N/A — y se declara.** Este módulo registra **operaciones pasadas reales**; no
hay simulación ni señal que pueda "mirar al futuro". *Se hace constar explícitamente para que el
agente no introduzca lógica de mercado donde no aplica.* (Declarar "N/A" es parte del método:
ver Parte 3 del manual.)

### 2.7 Métricas de éxito del feature

- Un trader registra un trade en **< 30 s** (formulario corto).
- Las stats por setup coinciden con un cálculo manual sobre los mismos trades (test).
- 0 fugas entre usuarios (test de aislamiento).

### 2.8 Principios de diseño para el agente

1. **Reusar patrones, no inventar.** Persistencia y auth = clon de `strategies`.
2. **El backend recalcula** `pnl`/`r_multiple`; el cliente solo manda datos crudos.
3. **Scoping por usuario en TODA query** (`scope_clause`).
4. **No tocar** el motor ni `daily_metrics`/Parquet (este módulo no los usa).
5. Nomenclatura de trade/métricas = la del código existente.

---

<a id="s03"></a>
## 03 · Contrato de datos

### 3.1 Modelos Pydantic (nuevo fichero `app/schemas/journal.py`)

```python
# enums: Direction(long|short), Status(open|closed), Setup, Mistake, EmotionalState

class JournalEntryCreate(BaseModel):
    ticker: str
    trade_date: date
    direction: Literal["long", "short"]
    status: Literal["open", "closed"] = "closed"
    entry_price: float
    exit_price: float | None = None      # obligatorio si status=closed
    size: float
    stop_loss: float | None = None       # opcional; sin él, r_multiple=null
    setup: str | None = None             # uno de Setup
    mistakes: list[str] = []             # subconjunto de Mistake
    followed_plan: bool | None = None
    emotional_state: str | None = None   # uno de EmotionalState
    rating: int | None = None            # 1..5
    notes: str | None = None

class JournalEntry(JournalEntryCreate):
    id: str
    user_id: str
    pnl: float | None                    # recalculado por el backend
    r_multiple: float | None             # recalculado por el backend
    created_at: str
    updated_at: str
```

### 3.2 Endpoints (router fino `/api/journal`)

| Método · Ruta | Auth | Request | Response | Notas |
|---|---|---|---|---|
| `POST /api/journal` | user | `JournalEntryCreate` | `JournalEntry` | recalcula `pnl`/`r_multiple`; `INSERT` + `upload_user_db()` |
| `GET /api/journal` | user | query: `date_from, date_to, ticker, setup, outcome(win\|loss\|open), limit=100, cursor` | `{ "entries": JournalEntry[], "total": int, "next_cursor": str\|null }` | **scope_clause(user_id)** |
| `GET /api/journal/{id}` | user | — | `JournalEntry` | 404 si no es del user |
| `PATCH /api/journal/{id}` | user | campos parciales de `JournalEntryCreate` | `JournalEntry` | recalcula; `updated_at`; `upload_user_db()` |
| `DELETE /api/journal/{id}` | user | — | `204` | borra solo si es del user; `upload_user_db()` |
| `GET /api/journal/stats` | user | mismos filtros que el listado | `JournalStats` (3.3) | excluye `status=open` |

### 3.3 `JournalStats` (response)

```jsonc
{
  "count": 84,                 // trades CERRADOS en la muestra
  "win_rate_pct": 58.3,
  "avg_r": 0.42,               // R medio (expectancy en R)
  "expectancy": 37.5,          // USD por trade
  "payoff_ratio": 1.9,
  "avg_win": 120.0,
  "avg_loss": -63.0,
  "by_setup": [                // desglose ordenado por avg_r desc
    { "setup": "pmh_reject", "count": 31, "win_rate_pct": 67.7, "avg_r": 0.81 },
    { "setup": "gap_and_crap", "count": 22, "win_rate_pct": 54.5, "avg_r": 0.30 }
  ],
  "by_mistake": [              // impacto de cada error
    { "mistake": "chased_entry", "count": 14, "avg_r": -0.55 },
    { "mistake": "no_stop", "count": 6, "avg_r": -1.20 }
  ]
}
```

> `count: 0` ⇒ todas las medias `null` (no `0`), igual criterio que el resto del repo.

### 3.4 Errores (catálogo cerrado, sin filtrar internals)

| Código | Cuándo | Body |
|---|---|---|
| `400` | `status=closed` sin `exit_price`/`size`; precio negativo; `rating∉1..5`; `setup`/`mistake`/`emotional_state` fuera de enum; fecha futura | `{"error":{"code":"invalid_entry","message":"...","details":{...}}}` |
| `401` | sin auth (cuando `AUTH_ENABLED`) | `{"error":{"code":"unauthorized"}}` |
| `404` | `id` no existe **o no es del user** | `{"error":{"code":"not_found"}}` |
| `500` | fallo interno | `{"error":{"code":"internal_error","message":"Unexpected error"}}` — **sin** `str(exc)` |

### 3.5 Ejemplos numéricos cerrados (para los tests)

| Caso | Entrada | `pnl` | `r_multiple` |
|---|---|---|---|
| Short ganador con stop | dir=short, entry=10.00, exit=8.00, size=100, stop=11.00 | `(10-8)*100 = 200` | `risk/sh=|10-11|=1.00` → `200/(1.00*100)=2.0` |
| Long perdedor con stop | dir=long, entry=5.00, exit=4.50, size=200, stop=4.80 | `(4.50-5.00)*200 = -100` | `risk/sh=0.20` → `-100/(0.20*200)=-2.5` |
| Sin stop | dir=short, entry=3.00, exit=2.70, size=50, stop=null | `(3-2.70)*50 = 15` | `null` |
| Abierto | status=open, exit=null | `null` | `null` |
| entry==stop | entry=4, stop=4 | (según exit) | `null` (no div/0) |

---

<a id="s04"></a>
## 04 · UI y componentes

### 4.1 Navegación y página

- **Sidebar:** añadir entrada "Journal" (href `/journal`, icono `BookOpen` de `lucide-react`),
  con el mismo patrón que `/screener`, `/backtester` en `Sidebar.tsx`.
- **Página:** `frontend/src/app/journal/page.tsx` (patrón de `screener/page.tsx`).

### 4.2 Wireframe textual

```
┌─ Journal ─────────────────────────────────────────────────────────┐
│ [1] Cabecera de stats: Win rate · R medio · Expectancy · Payoff   │
│ [2] Filtros: fecha desde/hasta · ticker · setup · resultado   [+ Nuevo trade] │
├───────────────────────────────────────────────────────────────────┤
│ [3] Tabla de entradas:                                            │
│   Fecha · Ticker · Dir · Entry · Exit · Size · PnL · R · Setup ·  │
│   Errores · ✎ ✕                                                    │
├───────────────────────────────────────────────────────────────────┤
│ [4] (panel inferior o modal) Desglose por setup y por error       │
└───────────────────────────────────────────────────────────────────┘
   [+ Nuevo trade] / ✎  → modal con el formulario (JournalEntryForm)
```

- **[1]** reusa `MetricsCard` (`components/backtester/MetricsCard.tsx`).
- **[3]** reusa el patrón de `DataGrid.tsx` (o `TradeTable.tsx`); `PnL` y `R` con color
  `--ec-profit`/`--ec-loss`.
- **Formulario** (modal): patrón de los paneles de `strategy-builder/`.

### 4.3 Los 4 estados obligatorios

| Estado | Qué se ve |
|---|---|
| **Loading** | Skeleton de cabecera + tabla; spinner `Loader2` |
| **Empty** | Sin entradas → ilustración + "Registra tu primer trade" + botón `+ Nuevo trade` |
| **Error** | `AlertCircle` + mensaje accionable + reintento |
| **Success** | Stats + tabla; trades `open` con badge "abierto" y PnL/R en "—" |

### 4.4 Comportamiento

- **Datos** vía `lib/api.ts`: `getJournal`, `getJournalEntry`, `createJournalEntry`,
  `updateJournalEntry`, `deleteJournalEntry`, `getJournalStats` (patrón de `getStrategies`/
  `createStrategy`). **Nunca** `fetch` suelto.
- **Formulario**: validación cliente (precios ≥ 0, exit obligatorio si `status=closed`,
  `rating` 1–5) **y** servidor (el servidor es la autoridad). PnL/R se muestran calculados por
  el backend tras guardar (no se teclean).
- **Filtros** reflejados en la URL (compartible/recargable).
- **Borrado** con confirmación (acción destructiva).

### 4.5 Estilo (tokens del design system)

- PnL/R positivos `--ec-profit #4A9D7F`; negativos `--ec-loss #C94D3F`.
- Tarjetas: `MetricsCard` estándar; cobre `--ec-copper` solo para marca/eyebrow.
- Tipografía: valores en General Sans 600 (no Fraunces para cifras); títulos en Fraunces.

### 4.6 (Opcional) Asistible por Edgie

`journal.add_entry` y `journal.set_filters` siguiendo
`docs/assistant/guia_dev_componente_asistible.md`. `add_entry` ejecuta/guarda ⇒ `confirm:
'confirm'`. **Fuera del MVP** salvo que se pida (doc 07).

---

<a id="s05"></a>
## 05 · Arquitectura

### 5.1 Ficheros (nuevos y tocados)

**Backend**
- `app/schemas/journal.py` — **nuevo**: enums + `JournalEntryCreate`, `JournalEntry`, `JournalStats`.
- `app/routers/journal.py` — **nuevo**: router fino `/api/journal` (CRUD + stats). Auth con
  `Depends(get_current_user_id)`; toda query con `scope_clause(user_id)`.
- `app/services/journal_service.py` — **nuevo**: cálculo de `pnl`/`r_multiple`, agregación de
  stats (`by_setup`, `by_mistake`), reusando nomenclatura de `_aggregate_metrics()`.
- `app/init_db.py` — **tocar**: `CREATE TABLE IF NOT EXISTS journal_entries (...)` junto a
  `strategies`/`saved_queries`.
- `app/main.py` — **tocar**: `app.include_router(journal.router, prefix="/api/journal", tags=["Journal"])`.

**Frontend**
- `frontend/src/lib/api.ts` — **tocar**: funciones + tipos `JournalEntry`, `JournalStats`.
- `frontend/src/app/journal/page.tsx` — **nuevo**.
- `frontend/src/components/journal/JournalTable.tsx`, `JournalEntryForm.tsx`,
  `JournalFilters.tsx`, `JournalStatsHeader.tsx` — **nuevos** (reusan `DataGrid`/`MetricsCard`).
- `frontend/src/components/Sidebar.tsx` — **tocar**: entrada de navegación.

### 5.2 Persistencia (clon del patrón `strategies`)

DDL en `init_db.py`:

```sql
CREATE TABLE IF NOT EXISTS journal_entries (
    id VARCHAR PRIMARY KEY,
    user_id VARCHAR,
    ticker VARCHAR,
    trade_date DATE,
    direction VARCHAR,
    status VARCHAR,
    entry_price DOUBLE,
    exit_price DOUBLE,
    size DOUBLE,
    stop_loss DOUBLE,
    pnl DOUBLE,
    r_multiple DOUBLE,
    setup VARCHAR,
    mistakes VARCHAR,        -- JSON array como texto (patrón de strategies.definition)
    followed_plan BOOLEAN,
    emotional_state VARCHAR,
    rating INTEGER,
    notes VARCHAR,
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);
```

Escritura: `get_user_db_lock()` → `get_user_db_connection()` → `INSERT/UPDATE … VALUES (?,…)`
→ `con.close()` → `upload_user_db()` (idéntico a `create_strategy`). `mistakes` se serializa
con `json.dumps` (como `strategies.definition`).

### 5.3 Auth / scoping (clon del patrón existente)

- Cada endpoint: `user_id = Depends(get_current_user_id)`.
- Cada `SELECT/UPDATE/DELETE`: añadir `scope_clause(user_id)` (mismo helper que `strategies`).
- Con `AUTH_ENABLED=false` (dev) el comportamiento degrada a single-user, igual que hoy.

### 5.4 Flujo end-to-end

```
UI (journal/) → lib/api.ts → /api/journal* → routers/journal.py (auth + scope)
  → services/journal_service.py (recalcula pnl/r, agrega stats)
  → users.duckdb (get_user_db_connection + lock) → upload_user_db() [GCS]
  → respuesta JSON → UI
```

### 5.5 Lista "no tocar" — cómo se respeta

- No se toca `engine.py`/`indicators.py`/`daily_metrics`/Parquet: el Journal **no** usa el motor
  ni los datos de mercado. Es un módulo independiente sobre `users.duckdb`.
- No se commitean `*.duckdb` (ya en `.gitignore`).

### 5.6 Decisiones técnicas (y alternativas descartadas)

- **`journal_entries` en `users.duckdb`** (no Postgres/nuevo store): es el patrón vigente para
  dato de usuario; reusa sync a GCS. *Descartado Postgres* (añade infra sin necesidad en MVP).
- **`mistakes` como JSON en una columna** (no tabla N:M): simple y suficiente; *tabla aparte =
  v2* si se necesita query analítica pesada por error.

---

<a id="s06"></a>
## 06 · Prompt maestro de ejecución

> Lo que se pega en Claude Code (goal/loop). Tareas atómicas, TDD, comando por tarea. **No
> avanzar si el comando no pasa.**

### 0. Contexto obligatorio antes de tocar nada

1. Este documento entero.
2. `app/routers/strategies.py` (patrón persistencia + `upload_user_db`).
3. `app/auth/__init__.py` (`get_current_user_id`, `scope_clause`).
4. `app/init_db.py` (dónde declarar tablas) y `app/main.py` (registro de routers).
5. `app/services/backtest_service.py` (`_enrich_trades`, `_aggregate_metrics` — nomenclatura).
6. `frontend/src/lib/api.ts`, `components/Sidebar.tsx`, `components/DataGrid.tsx`,
   `components/backtester/MetricsCard.tsx`.
7. `.agent/CODING_RULES.md`, `.agent/EDGECUTE_DESIGN_SYSTEM.md`.

### 1. Restricciones globales (no negociables)

- Router fino; lógica en `services/journal_service.py`.
- **Toda** query scopeada por `user_id` (`scope_clause`). Tests de aislamiento.
- Backend **recalcula** `pnl`/`r_multiple`; ignora lo que mande el cliente.
- Queries **parametrizadas** (`?`). `upload_user_db()` tras cada escritura.
- Errores sin `str(exc)` ni trazas. TDD. Mover-no-borrar. Commits convencionales.
- No tocar motor/`daily_metrics`/Parquet.

### 2. Secuenciación atómica

**EPIC A — Backend**

- **A1. Schemas + enums** (`schemas/journal.py`).
  - *Test:* round-trip de `JournalEntryCreate`; enum inválido ⇒ ValidationError.
  - *Verif:* `cd backend && source .venv/bin/activate && pytest tests/test_journal_schemas.py -q`
- **A2. Cálculo `pnl`/`r_multiple`** (`journal_service.py`).
  - *Test:* los 5 casos de §3.5 (incluido `open`→null y `entry==stop`→null).
  - *Verif:* `pytest tests/test_journal_calc.py -q`
- **A3. Migración** (`init_db.py`: `journal_entries`).
  - *Test:* tras `init_db()`, la tabla existe; insertar/leer una fila funciona.
  - *Verif:* `pytest tests/test_journal_migration.py -q`
- **A4. CRUD endpoints + scoping** (`routers/journal.py`, registrar en `main.py`).
  - *Test:* crear→leer→editar→borrar; user B **no** ve entradas de user A (401/404);
    `closed` sin `exit_price` ⇒ 400.
  - *Verif:* `pytest tests/test_journal_endpoints.py -q` + `uvicorn app.main:app --port 8000` +
    `curl -XPOST localhost:8000/api/journal -d '{...}'`
- **A5. Stats** (`/api/journal/stats` + `by_setup`/`by_mistake`, excluye `open`).
  - *Test:* muestra conocida ⇒ `win_rate_pct`/`avg_r`/`by_setup` correctos; `count=0`⇒medias null.
  - *Verif:* `pytest tests/test_journal_stats.py -q`

**EPIC B — Frontend**

- **B1. API client + tipos** (`lib/api.ts`). *Verif:* `cd frontend && npm run build`.
- **B2. JournalEntryForm** (crear/editar, validación, 4 estados de envío). *Verif:* `npm run build`.
- **B3. JournalTable + JournalFilters** (reuso `DataGrid`; PnL/R con color; estados empty/loading/error). *Verif:* `npm run build` + `npm run dev`.
- **B4. JournalStatsHeader** (reuso `MetricsCard`) + desglose por setup/error. *Verif:* `npm run build`.
- **B5. Página `/journal` + entrada en `Sidebar`.** *Verif:* `npm run build`; navegable en `/journal`.

### 3. Definition of Done

**Por tarea:** test antes y en verde · comando pasa · sin regresiones (`pytest` + `npm run build`)
· scoping verificado · no se tocó motor/datos · commit convencional.

**Global:** CRUD funciona end-to-end en `/journal` · stats por setup/error correctas · 0 fugas
entre usuarios · `pnl`/`r_multiple` recalculados · trades `open` excluidos de stats · datos
persisten tras reinicio (gracias a `upload_user_db`).

### 4. Comandos de verificación

```bash
# Backend
cd backend && source .venv/bin/activate
pytest tests/test_journal_*.py -q
pytest tests/ -q                         # sin regresiones
uvicorn app.main:app --reload --port 8000
curl -s -XPOST localhost:8000/api/journal -H 'Content-Type: application/json' \
  -d '{"ticker":"XYZ","trade_date":"2026-06-20","direction":"short","status":"closed","entry_price":10,"exit_price":8,"size":100,"stop_loss":11,"setup":"pmh_reject"}'

# Frontend
cd frontend && npm install && npm run build && npm run lint && npm run dev
```

### 5. Orden de PRs

1. **PR-1**: EPIC A (schemas + cálculo + migración + CRUD + stats). Demoable por `curl`.
2. **PR-2**: EPIC B (UI completa).
3. *(v2)*: import desde backtest, capturas, calendario, asistible Edgie.

> Jesús trabaja en su rama; los merges los hace otra persona. No pushear a `main` ni mergear
> desde el loop.

---

<a id="s07"></a>
## 07 · Decisiones abiertas

### A. Decisiones de PRODUCTO (dueño: Jaume/Jesús)

- **A1. Taxonomías** (setup/mistake/emotional_state): la lista de §2.5 es la inicial de Jaume.
  *Recomendación:* dejarla editable en config a futuro; no hardcodear para siempre.
- **A2. ¿`rating` 1–5 o 1–10?** *Recomendación:* 1–5 (más rápido de rellenar). Reversible.
- **A3. ¿Asistible por Edgie en MVP?** *Recomendación:* no, v2.
- **A4. Gating/monetización** (¿journal premium? ¿límite de entradas en free?): **DIFERIDO a
  Jesús.** El PRD no decide política; si hace falta, se añade el hook de gating como mecanismo.

### B. Defaults técnicos reversibles (los asume la IA)

- **B1.** `mistakes` como JSON en columna (no tabla N:M). Reversible.
- **B2.** Paginación `limit=100` + cursor. Reversible.
- **B3.** `status` default `closed`. Reversible.
- **B4.** Orden por defecto del listado: `trade_date` desc. Reversible.

---

<a id="entrevista"></a>
## Apéndice — Registro de la entrevista agente↔PM (la minuta)

> **Esto demuestra el método del manual (Parte 2):** el agente **preguntó primero, redactó
> después** — y preguntó al PM **solo de funcionalidad y trading**; las decisiones técnicas las
> tomó él (ancladas en el repo) o quedaron para el CTO. Abajo, la conversación resumida.

### Preguntas al PM (solo funcionalidad y trading)

**Problema y la idea amplia → MVP vs Fase 2**
- *Agente:* Cuéntame el journal **en grande**, sin filtros. — **PM:** Registrar trades reales,
  importarlos del backtester, subir capturas, ver un calendario de PnL, conectar el broker,
  estadísticas por setup… (idea amplia).
- *Agente:* Eso es mucho. ¿Qué es lo **mínimo que ya te sirve** (MVP)? — **PM:** Registrar a
  mano un trade con setup/errores y ver stats por setup. → *(doc 02 §2.3 MVP)*
- *Agente:* El resto (import del backtester, capturas, calendario, broker) lo dejo en **Fase 2**:
  no se construye ahora, pero lo tengo en cuenta para **no cerrarle la puerta** desde el MVP. →
  *(doc 02 §2.4 Fase 2; por eso el contrato se deja import-ready)*
- *Agente:* ¿Una entrada = un trade o una nota de día? — **PM:** Un trade.
- *Agente:* ¿Registras trades **abiertos** (sin salida todavía)? — **PM:** Sí. → *(doc 02 §2.3)*

**Trading**
- *Agente:* ¿Cómo defines R? ¿el trader fija un stop planificado? — **PM:** Sí; `R = pnl /
  (riesgo_por_acción * size)`; sin stop, no hay R. → *(doc 02 §2.6)*
- *Agente:* En un short, ¿cómo se calcula el PnL? — **PM:** `(entry - exit) * size`. → *(doc 02 §2.6)*
- *Agente:* Dame tu lista de **setups** y de **errores** habituales. — **PM:** setups: gap&crap,
  PMH reject, VWAP reject, first red day, backside, para fade. errores: chased, no_stop,
  moved_stop, oversized, revenge, exited_early, fomo. → *(doc 02 §2.5 enums)*
- *Agente:* ¿Hay riesgo de anti-lookahead? — **PM:** No, son trades reales pasados. →
  *(N/A explícito, doc 02 §2.6)*

**Qué se captura / privacidad (producto)**
- *Agente:* Además de los precios, ¿qué quieres registrar? — **PM:** setup, errores, si seguí el
  plan, estado emocional y una nota. Lo emocional y el plan, **opcionales**. → *(doc 02 §2.5)*
- *Agente:* ¿El diario es privado de cada trader o compartido? — **PM:** Totalmente privado. →
  *(el cómo —scoping— lo resuelve el agente, doc 05 §5.3)*
- *Agente:* ¿El usuario puede editar y borrar? — **PM:** Sí, ambas. → *(CRUD, doc 03)*
- *Agente:* ¿El Journal es una sección propia del producto? — **PM:** Sí, su propio sitio. →
  *(el cómo —nav en el Sidebar— lo decide el agente, doc 04 §4.1)*

**Aceptación**
- *Agente:* Dame ejemplos para fijar los cálculos. — **PM:** short 10→8 ×100 con stop 11 = +200,
  2R; long 5→4.5 ×200 con stop 4.80 = −100, −2.5R. → *(doc 03 §3.5)*

**Negocio (no lo decide el PM)**
- *Agente:* ¿Es premium / tiene límites? — **PM:** Eso lo decide Jesús; **no lo fijes**. →
  *(doc 07 §A4, diferido)*

### Decisiones técnicas que tomó el AGENTE (no se preguntaron al PM)

> Ancladas en el repo o como default reversible. Si alguna fuera de peso, iría al CTO.
- **Recalcular `pnl`/`r_multiple` en el backend** (no fiarse del cliente) — integridad de datos.
- **Persistir en `users.duckdb`** con el patrón de `strategies` + `upload_user_db()` (doc 05 §5.2).
- **`scope_clause(user_id)`** en toda query para garantizar la privacidad (doc 05 §5.3).
- **`mistakes` como JSON**, paginación `limit=100`, orden `trade_date` desc, esquema de tabla y
  contrato de la API (doc 03, doc 07 §B). Todo reversible.
- **Contrato import-ready** (claves = `_enrich_trades`) para no bloquear la Fase 2 de importación.

### Minuta de cierre (confirmada por el PM antes de redactar)
- **Fijado por el PM (funcional / trading):** entry = 1 trade; open/closed; definición de R y
  PnL; enums de setup/mistake/emotional (emocional y plan opcionales); diario privado; CRUD;
  sección propia. **MVP** = registro manual + stats por setup; **Fase 2** = import del backtester,
  capturas, calendario, broker.
- **Decidido por el agente (técnico, doc 05 / 07 §B):** recálculo en backend; `users.duckdb` +
  scoping; JSON para mistakes; paginación; esquema y contrato; contrato import-ready.
- **Diferido a Jesús (negocio):** monetización / gating.

---

> **Cómo leer este ejemplo.** Es un módulo **que no existe**, pero cada decisión de *cómo*
> construirlo está anclada en un **patrón real** (persistencia de `strategies`, auth
> `scope_clause`, migración en `init_db.py`, nav en `Sidebar.tsx`). La capa de trading (qué se
> registra, cómo se calcula R, qué setups/errores) salió de la **entrevista** al PM. Eso es un
> PRD greenfield que la IA construye a la primera. El método completo está en el
> [Manual del PM](GUIA_PRD_EJECUTABLE.md).
