# PRD — Módulo de Robustez

**Estado:** implementado y verificado en local. Código en `staging`.
**Fecha:** 2026-08-20
**Ruta:** `/robustez` (frontend) · `/api/robustness/*` (backend)
**Gating:** `ROBUSTNESS_ENABLED` (backend) y `NEXT_PUBLIC_ROBUSTNESS_ENABLED`
(frontend). **Ambas apagadas por defecto.** Sin ellas, el router responde 503 y
la entrada del menú no se pinta.

---

## 0. Cómo leer este documento

El código está en `staging`, así que esto no es una especificación a ciegas:
es la explicación de **por qué** cada pieza está como está, con los números
medidos para que puedas verificar tu propia implementación contra los mismos.

**Si solo vas a leer una sección, lee la §2.** Son tres comportamientos del
motor de backtest que no son evidentes y que invalidan cualquier análisis de
robustez si no se tienen en cuenta. Los tres están verificados con datos, no
deducidos.

Al final, en la §10, hay una batería de cifras de control: si tu implementación
las reproduce, es correcta.

---

## 1. Qué es y qué responde

Una página para someter a estrés una estrategia **ya backtesteada y guardada**,
y contestar cinco preguntas que el backtest por sí solo no contesta:

| Módulo | Pregunta que responde |
|---|---|
| **Análisis básico** | ¿Cuánto y durante cuánto tiempo voy a estar perdiendo? ¿Qué aguanta si le quito sus mejores días? |
| **Monte Carlo Bootstrap** | ¿Cuánto de mi resultado fue habilidad y cuánto el orden en que llegaron los trades? ¿Qué drawdown debería esperar de verdad? |
| **Walk Forward** | ¿Los parámetros funcionaban, o estaban ajustados al pasado que ya había visto? |
| **Margen de EV — Black Swan** | *(hueco reservado, sin lógica)* |
| **Locates vs Slippage** | ¿A partir de qué coste de locates o de qué slippage deja de ser rentable? |

**Principio de diseño:** tres de los cinco módulos trabajan sobre los trades ya
guardados y son **instantáneos** (no tocan el lago ni leen una vela). Los dos
que sí re-ejecutan backtests están marcados como *pesados* en la interfaz y
llevan barra de progreso, cancelación y guardián de concurrencia.

---

## 2. Tres comportamientos del motor que hay que conocer

Estos tres puntos son la parte más importante del documento. Los tres se
descubrieron construyendo el módulo, los tres están verificados con datos, y
**los tres siguen presentes en el código de producción** (no se han tocado).

### 2.1 El motor compone POR DÍA, no por trade

`backtest_signals.simulate_and_accumulate` solo avanza `compounding_cash` al
**cambiar de fecha**:

```python
if date != current_date:
    global_realized_pnl += daily_pnl
    daily_pnl = 0.0
    current_date = date
compounding_cash = init_cash + global_realized_pnl
```

Es decir: dentro de una misma sesión, **todas las posiciones se dimensionan
sobre el balance de apertura del día**, y el PnL se acumula al cerrar.

**Consecuencia práctica:** al reconstruir una curva de capital hay que aplicar
la suma de R del día de una vez, no trade a trade.

| Método de reconstrucción | Equity final | Real |
|---|---|---|
| Componiendo trade a trade | 579,3% | 581,7% |
| Componiendo **por día** | 581,7% | 581,7% |

### 2.2 Sumar PnL en dólares produce cifras imposibles

Con `risk_type = PERCENT`, cada trade arriesga un % del capital **vivo**. Los
dólares que gana un trade dependen del balance que hubiera ese día. Por tanto,
**quitar trades y volver a sumar los dólares del resto rompe el vínculo con el
capital**.

Medido sobre la corrida real (3.544 trades, +581,7%), quitando el mejor 10%:

| | |
|---|---|
| Suma del top 10% (354 operaciones) | **152.578 $** — más que TODO el beneficio (58.167 $) |
| PnL restante, sumado en dólares | −94.411 $ |
| Equity final resultante | **−84.411 $** ← dinero negativo, imposible |
| Equity final, recomponiendo en R | **2.617 $** → −73,8% |

El **−73,8%** es la respuesta útil. El −944% no significa nada.

> ⚠️ Esto afecta a `what_if_service.run_what_if`, que es lo que usa hoy el
> botón de "what if" de la página de Backtester. Con esta estrategia devuelve
> −761% de retorno y −567% de drawdown. **No se ha modificado** —es código
> compartido con producción y cambiarlo alteraría el comportamiento de la
> página de Backtester—, pero el módulo de Robustez lleva su propio motor
> (`robustness_stress.py`) que trabaja en R-múltiplos.
>
> **Decidid entre vosotros** si queréis arreglar el original o dejar los dos
> conviviendo. Si lo arregláis, la regla es la misma: trabajar en R y
> recomponer por día.

### 2.3 `slippage` es una FRACCIÓN, aunque el campo se titule "%"

El simulador que se ejecuta de verdad
(`portfolio_sim_jit._core_simulate_jit`) aplica:

```python
slip = precio * slippage        # SIN dividir entre 100
```

Pero el campo de la página de Backtester se titula **"Slippage (%)"**.

```
frontend/src/components/backtester/BacktestPanel.tsx:1434
    Slippage (%)
```

**Consecuencia:** un `0.001` escrito ahí acaba valiendo **0,1% real**, cien
veces más de lo que sugiere la etiqueta.

Además, las dos vías del simulador **no usan la misma unidad**:

| Fichero | Fórmula | Unidad |
|---|---|---|
| `app/services/portfolio_sim_jit.py` (vía de estrategia única, la que se usa) | `precio * slippage` | **fracción** |
| `app/backtester/engine.py` (vía de portfolio) | `precio * (1 ± slippage/100)` | **porcentaje** |

Sensibilidad medida (locates=1, febrero–agosto 2026, 1.071 trades):

| Slippage real | Retorno | Profit factor |
|---|---|---|
| 0,001% | **+120,70%** | 1,25 |
| 0,021% | −45,89% | 0,84 |
| 0,041% | −87,74% | 0,55 |
| 0,080% | −100,00% | 0,18 |

El punto de equilibrio está en torno al **0,012%**. Si hubiésemos barrido el
rango "0,1 a 1" pensando que eran porcentajes, habrían sido 10%–100% de
slippage y **todas las celdas de la matriz habrían salido a −100%**.

**En este módulo se trabaja siempre en % real** y se convierte al entrar al
motor:

```python
def _slip(pct: float) -> float:
    """% real -> unidades del motor (que espera una fraccion)."""
    return float(pct) / 100.0
```

### 2.4 Bonus: `total_return_pct` no descuenta los gastos fijos

```python
total_pnl = float(pnls.sum())
total_return = (total_pnl / init_cash) * 100.0     # sin restar monthly_expenses
```

Los gastos fijos solo aparecen en `total_pnl_net` y `total_expenses`. Si usas
`total_return_pct` para calcular un punto de equilibrio, **poner gastos
mensuales no moverá la conclusión** — que es justo para lo que se ponen.

El módulo recalcula:

```python
def _net_return_pct(agg, init_cash):
    net = agg.get("total_pnl_net")
    if net is None or not init_cash:
        return agg.get("total_return_pct")
    return round(float(net) / float(init_cash) * 100.0, 4)
```

Y usa `global_equity_expenses` (no `global_equity`) para la curva cuando hay
gastos.

---

## 3. De dónde salen los datos

### 3.1 Los trades SÍ están guardados

La suposición de partida era que al guardar una estrategia se guarda su
histórico. **No es así:** la tabla `strategies` solo guarda la definición.

Los trades viven en `backtest_results.results_json`, enlazados por
`strategy_ids`. Estructura relevante de `results_json`:

```
aggregate_metrics    {...}
trades               [ {...}, ... ]        <- lo que consume el módulo
global_equity        [ {time, value}, ...] <- curva diaria
global_drawdown      [ {time, value}, ...]
backtest_params      {...}                 <- capital, locates, slippage, riesgo
```

Campos de cada trade (todos presentes, verificado):

```
ticker, date, entry_time, exit_time, entry_idx, exit_idx,
entry_time_epoch, exit_time_epoch, entry_price, exit_price,
pnl, fees, return_pct, direction, status, size, exit_reason,
mae, mfe, r_multiple, entry_hour, entry_weekday, gap_pct, stop_loss
```

El módulo recorta a los que usa (`TRADE_FIELDS` en `robustness_service.py`):
el resto solo sirve para pintar velas y engorda el payload.

### 3.2 ⚠️ El endpoint del Baúl no sirve para esto

`GET /api/strategy-search/list` devuelve el `results_json` **completo de todas
las corridas**. Medido con **una sola estrategia guardada: 48 MB**, y ni en
localhost termina de descargarse — la conexión se corta a mitad.

El módulo tiene endpoints propios ligeros. **No modifiques el del Baúl** para
esto; añade los tuyos.

Truco usado para traer `backtest_params` al listado sin cargar los trades
(extraer la clave en la propia base, no en Python):

```sql
SELECT id, json_extract(results_json, '$.backtest_params')
FROM backtest_results WHERE id IN (?, ?, ...)
```

### 3.3 La R exacta: `r_multiple` viene redondeado

`r_multiple` se guarda con **dos decimales**. Sobre 3.544 trades ese redondeo se
acumula y desvía el balance final un **+0,44%**.

La R exacta se puede recuperar, porque se sabe cómo dimensiona el motor
(arriesga `risk_pct` del balance de **apertura del día**):

```
R = pnl / (risk_pct × equity_al_empezar_el_día)
```

y ese balance es el punto anterior de la curva diaria, que viene en el payload.

| | Reconstruido | Real | Desvío |
|---|---|---|---|
| Con `r_multiple` (2 decimales) | 68.468,05 $ | 68.167,25 $ | +0,441% |
| Con **R exacta** | 68.167,24 $ | 68.167,25 $ | **−0,000015%** |
| Max drawdown, R exacta | −27,3500% | −27,3496% | 0,0004 pp |

Implementación: `attach_precise_r()` en `robustness_service.py`. Se ejecuta al
cargar la corrida y añade `r_precise` a cada trade. Si no hay curva diaria o el
riesgo no es porcentual, cae a `r_multiple`.

---

## 4. Arquitectura y ficheros

### 4.1 Backend

| Fichero | Responsabilidad |
|---|---|
| `app/routers/robustness.py` | Endpoints, gating, guardián de trabajos pesados |
| `app/services/robustness_service.py` | Carga ligera + `attach_precise_r` |
| `app/services/robustness_mc.py` | Monte Carlo (bootstrap / permutación), vectorizado |
| `app/services/robustness_stress.py` | Test de estrés en dominio compuesto |
| `app/services/robustness_grid.py` | Carga compartida de velas + matriz locates×slippage |
| `app/services/robustness_wfo.py` | Walk-forward rápido y completo + análisis de meseta |

**Único cambio en fichero compartido:** 3 líneas en `app/main.py`

```python
from app.routers import robustness
...
app.include_router(robustness.router, prefix="/api/robustness", tags=["Robustness"])
```

### 4.2 Frontend

```
app/robustez/page.tsx                     orquestador
components/robustez/
  StrategyPicker.tsx                      listado + desplegable de condiciones
  ModuleRail.tsx                          raíl izquierdo (plegable)
  ResultsPanel.tsx                        marco del panel derecho
  shared.tsx                              MetricTile, DataTable, Field, ...
  help.tsx                                Help (?), SubTabs, PlainStats, Verdict
  modules/
    types.ts                              contrato ModuleParts
    useBasico.tsx  useMonteCarlo.tsx  useWfo.tsx  useLocates.tsx  useBlackSwan.tsx
  charts/
    BasicCharts.tsx  StressCurves.tsx  MonteCarloCharts.tsx
    DrawdownCompare.tsx  LocatesCharts.tsx  WfoCharts.tsx
lib/api_robustez.ts                       cliente tipado
lib/robustez/analytics.ts                 drawdown y rachas (cliente)
lib/robustez/formatStrategy.ts            definición -> texto legible
```

**Único cambio en fichero compartido:** la entrada de menú en `Sidebar.tsx`,
envuelta en el flag.

### 4.3 El patrón de los módulos: un hook, dos mitades

La configuración (panel izquierdo) y los resultados (panel derecho) comparten
estado — los parámetros que eliges a la izquierda producen el gráfico de la
derecha. Partirlo en dos componentes hermanos obligaría a subir ese estado a la
página y repartirlo módulo por módulo.

Cada motor es un **hook que devuelve sus dos mitades**:

```ts
export interface ModuleParts {
  config: React.ReactNode;    // panel izquierdo
  results: React.ReactNode;   // panel derecho
}
export function useBasico(ctx: ModuleCtx): ModuleParts { ... }
```

Y la página los instancia todos (los hooks no pueden ser condicionales) pero
solo pinta el activo. Ventaja: cambiar de pestaña y volver **no pierde la
configuración**.

```tsx
const engines = {
  basico: useBasico(ctx), montecarlo: useMonteCarlo(ctx),
  wfo: useWfo(ctx), blackswan: useBlackSwan(ctx), locates: useLocates(ctx),
};
const engine = engines[activeModule];
// <ModuleRail config={engine.config} /> <ResultsPanel>{engine.results}</ResultsPanel>
```

---

## 5. Contratos de API

Todos bajo `/api/robustness`. Todos devuelven **503** si `ROBUSTNESS_ENABLED`
no está activa. La variable se lee **en cada petición**, no al importar el
módulo (si se lee al importar, `load_dotenv()` aún no ha poblado el entorno y
queda congelada a vacío).

### 5.1 Listado ligero

```
GET /strategies
```

```jsonc
[{
  "id": "c0af...", "name": "Estrategia de prueba", "description": "",
  "created_at": "...", "updated_at": "...",
  "definition": { /* definición completa, para el desplegable */ },
  "run": {                       // null si no tiene backtest guardado
    "run_id": "681c...", "executed_at": "2026-08-20T13:56:10",
    "total_trades": 3544, "win_rate": 65.41, "profit_factor": 1.2312,
    "total_return_pct": 581.6725, "max_drawdown_pct": -27.3496,
    "sharpe_ratio": 3.0698,
    "backtest_params": { "init_cash": 10000, "risk_r": 3, "risk_type": "PERCENT",
                         "locates_cost": 1, "slippage": 0.001, "fees": 1.5e-05, ... }
  }
}]
```

**Nunca incluye trades.** Coste medido: 2,1 s la primera llamada (abrir la
conexión de solo lectura a la base), **32–40 ms** en caliente.

### 5.2 Corrida completa

```
GET /strategies/{strategy_id}/run
```

```jsonc
{
  "run_id": "...", "executed_at": "...",
  "aggregate_metrics": { ... },
  "backtest_params": { ... },
  "global_equity": [{ "time": 1724025600, "value": 10000.0 }, ...],
  "global_drawdown": [ ... ],
  "trades": [{ ..., "r_precise": 0.10921233333 }, ...],
  "compounding": {
    "is_percent_risk": true, "risk_pct": 3.0,
    "init_cash": 10000.0, "r_precise_exact": true
  }
}
```

Coste medido: **613 ms** para 3.544 trades.

### 5.3 Monte Carlo

```
POST /montecarlo
{ values, init_cash, simulations, method, mode, risk_pct, ruin_pct, seed }
```

- `values`: R-múltiplos si `mode="compound"`, PnL en $ si `"additive"`.
  **El cliente agrega por día antes de enviar** (ver §6.2).
- `method`: `"bootstrap"` | `"permutacion"`
- `mode`: `"compound"` | `"additive"`

### 5.4 Estrés

```
POST /stress
{ trades, params, init_cash, mode, risk_pct, seed }
```

`params` admite: `skip_top_pct`, `extra_slippage`, `black_swan_count`,
`black_swan_pct`, `daily_max_trades`, `max_concurrent_trades`,
`random_monthly_days`, `monthly_expenses`, `exclude_days`, `exclude_months`,
`exclude_hour_start`, `exclude_hour_end`.

### 5.5 Walk-forward

```
POST /wfo/fast     { strategy_id, n_windows, oos_pct, anchored, metric }   -> síncrono
GET  /strategies/{id}/parameters                                            -> parámetros optimizables
POST /wfo/full     { strategy_id, params[], n_windows, oos_pct, anchored,
                     metric, start_date, end_date }                         -> { task_id }
```

### 5.6 Locates

```
POST /locates/curves  { strategy_id, locates_min, locates_max, locates_steps,
                        slippage, monthly_expenses, start_date, end_date }  -> { task_id }
POST /locates/matrix  { ..., slippage_min, slippage_max, slippage_steps }   -> { task_id }
```

### 5.7 Trabajos pesados

```
GET  /job                  -> { busy, task_id, kind, elapsed_s }
GET  /job/{task_id}        -> { status: running|done|error|cancelled, progress, result?, error? }
POST /job/{task_id}/cancel
```

**Guardián de concurrencia:** un solo trabajo pesado a la vez. Un segundo
lanzamiento devuelve **409**, no se encola. Dos barridos simultáneos se pelean
por el disco y ninguno avanza.

```python
_JOB_LOCK = threading.Lock()
_ACTIVE = {"task_id": None, "kind": None, "started": None}
```

El progreso reutiliza `set_progress` / `get_progress` / `pop_result` de
`optimization_service`. **Ojo:** `pop_result` devuelve una **tupla de tres**
`(encontrado, es_error, payload)`, no dos.

---

## 6. Los módulos, uno a uno

### 6.1 Análisis básico

Dos pestañas anidadas: *Análisis* y *Test de estrés*.

**Se calcula en el cliente** (`lib/robustez/analytics.ts`). Son unos pocos miles
de trades y dos barridos O(n): hacerlo en el navegador evita un viaje al
servidor por cada reajuste.

#### Episodios de drawdown

Se recorre la curva de equity marcando picos:

```ts
for (let i = 1; i < equity.length; i++) {
  const v = equity[i].value;
  if (v >= peakVal) {
    if (inDd) { cerrar episodio (recuperado en i); inDd = false; }
    peakVal = v; peakIdx = i;
  } else {
    if (!inDd) { inDd = true; troughVal = v; troughIdx = i; }
    else if (v < troughVal) { troughVal = v; troughIdx = i; }
  }
}
if (inDd) cerrar episodio como ABIERTO (nunca recuperado)
```

De cada episodio: profundidad (% y $), sesiones, días naturales, y si se
recuperó.

#### Métricas mostradas

| Métrica | Fórmula | Valor de control |
|---|---|---|
| Max drawdown | `min(depthPct)` | **−27,35%** |
| DD más largo | `max(sessions)` | **107 ses. / 157 días naturales** |
| Ese DD, en % del total | `sessions_del_más_largo / n_sesiones` | **21,4%** (107 de 499) |
| Tiempo total en DD | `sesiones_bajo_máximo / n` | **74,7%** (47 episodios) |
| Ulcer index | `sqrt(mean(dd²))` | **8,61** |
| Racha perdedora máx | trades negativos consecutivos | **8** trades, −5.014 $ |
| Racha ganadora máx | trades positivos consecutivos | **14** trades, +5.278 $ |

> **Por qué dos cifras de tiempo:** *Tiempo total* suma todas las temporadas
> bajo el máximo, aunque sean cortas y repartidas. *Ese DD en % del total* mira
> solo el hundimiento más largo, y responde a "¿cuánto tiempo **seguido** puedo
> estar sin ver un máximo nuevo?", que es lo que de verdad agota a un operador.

> **Ojo con el pnl=0:** un trade con PnL exactamente cero no rompe ninguna
> racha ni cuenta para ninguna.

#### Gráfico de drawdown

Área "bajo el agua" en rojo **con la curva de capital superpuesta detrás**, en
verde tenue y con **escala propia** (logarítmica). No comparten eje a propósito:
la equity solo sirve de referencia visual —ver si un hundimiento cayó en plena
subida o en un tramo plano—, no para leerle un valor.

#### Test de estrés

Motor propio (`robustness_stress.py`), NO `what_if_service` (ver §2.2).

Todo se traduce a R-múltiplos y se recompone `equity *= (1 + R_del_día × riesgo%)`:

- **Quitar el mejor %:** se ordena **por R**, no por dólares. El mismo R gana
  más dólares cuanto más tarde ocurre; ordenar por dólares sesgaría hacia el
  final del histórico.
- **Slippage extra:** un x% de deslizamiento mueve el retorno x puntos. En R son
  `x / stop_pct` unidades, donde `stop_pct` es la distancia al stop **de ese
  trade** (se conoce: los trades guardan `stop_loss` y `entry_price`). **No es
  una constante para todos.**
- **Black swan:** se fuerza el trade a `-N / stop_pct` R.
- **Gastos fijos:** se restan al cerrar cada mes, se opere o no.

##### ⚠️ El eje temporal debe ser COMPARTIDO

Los castigos que vacían días enteros (días perdidos al mes, límite de trades por
día, quitar los mejores) hacían desaparecer esos días de la serie. Dos
problemas:

1. la gráfica se acortaba, como si el histórico terminase antes;
2. **peor:** las dos curvas se dibujan indexando por posición, así que el punto
   *i* de la estresada ya no era la misma fecha que el punto *i* de la original.
   **Estaban desalineadas en el tiempo.**

La solución: las dos curvas se construyen sobre el **mismo calendario** (el del
histórico sin castigar). Un día sin trades arrastra el capital anterior.

```python
calendar = _all_days(work)          # calendario del histórico completo
base_pts, _     = _equity_curve(work, ..., calendar)
stressed_pts, _ = _equity_curve(kept, ..., calendar)
```

Verificado:

| Castigo | Puntos base | Puntos estresada | Mismo eje | Sesiones operadas |
|---|---|---|---|---|
| sin castigo | 498 | 498 | sí | 498/498 |
| 3 días perdidos/mes | 498 | 498 | sí | **423/498** |
| máx 2 trades/día | 498 | 498 | sí | 498/498 |

##### Cifras de control del estrés

| Castigo | Retorno | Max DD | PF |
|---|---|---|---|
| sin castigo (base) | **+581,67%** | −27,35% | 1,23 |
| quitar mejor 10% | **−89,2%** | −89,7% | 0,77 |
| quitar mejor 5% | −38,6% | −56,1% | 0,95 |
| slippage +0,5% | +108,5% | −40,3% | 1,18 |
| 3 black swans −500% | +104,9% | −68,0% | 1,21 |
| gastos 500 $/mes | +86,9% | −49,1% | 1,23 |

El gráfico va en **rendimiento acumulado (%)** en el eje vertical, no en
dólares, con escala logarítmica.

### 6.2 Monte Carlo Bootstrap

#### Por qué no vale el servicio existente

`montecarlo_service.run_montecarlo`:

1. Solo hace **permutación**. Todas las simulaciones acaban en el mismo balance,
   así que la "probabilidad de acabar perdiendo" sale 0 o 100 por construcción.
2. Además su histograma **revienta** en ese caso: rango cero →
   `ValueError: Too many bins for data range`. Comprobado ejecutándolo.
3. Suma PnL en dólares (ver §2.2).
4. Bucle Python por simulación.

#### El nuevo

Vectorizado con numpy. Dos métodos y dos modelos:

| Método | Qué responde |
|---|---|
| **Bootstrap** (con reemplazo) | ¿Y si me hubieran tocado OTROS trades de la misma distribución? |
| **Permutación** (baraja) | ¿Y si los mismos trades hubieran llegado en otro orden? |

```python
def _draw(rng, arr, m, n, bootstrap):
    if bootstrap:
        return rng.choice(arr, size=(m, n), replace=True)
    # Permutacion vectorizada: ordenar ruido da una permutacion por fila
    return arr[np.argsort(rng.random((m, n)), axis=1)]
```

##### Unidad de remuestreo: POR DÍA por defecto

No es un capricho. El motor compone por día (§2.1), así que la unidad natural es
el día. Además **los trades de una misma sesión están correlacionados** (mismo
régimen de mercado); remuestrearlos por separado rompe esa correlación y
**subestima el riesgo**.

El cliente agrega antes de enviar:

```ts
const byDay = new Map<string, number>();
for (const t of selected) byDay.set(t.date, (byDay.get(t.date) || 0) + t.r_precise);
values = [...byDay.entries()].sort().map(([, v]) => v);
```

##### Memoria

Las métricas escalares se acumulan sobre TODAS las simulaciones (vectores 1D,
cuestan nada). Las **bandas por paso** necesitan las curvas completas a la vez:
con 10.000 × 3.500 serían 280 MB. Se calculan sobre una submuestra acotada de
**1.500 trayectorias** — los percentiles ya son lisos y el error es despreciable
frente al ancho de las propias bandas.

##### Rendimiento medido

| Simulaciones | Tiempo |
|---|---|
| 1.000 | 0,30 s |
| 5.000 | 0,87 s |
| 10.000 | 1,37 s |
| 20.000 | 2,33 s |

##### Cifras de control (5.000 sims, bootstrap, por día)

| | |
|---|---|
| DD real | **−27,4%** (coincide con el guardado, −27,3496%) |
| DD mediano simulado | −18,9% |
| **Aguantar el 95%** | **−30,1%** |
| Aguantar el 99% | −36,1% |
| Peor simulado | −51,6% |
| Final p5 / p50 / p95 | 30.953 $ / 67.673 $ / 144.746 $ |
| Real | 68.167 $ (+582%) |

##### Gráfico comparativo de drawdowns

Entre el histograma y la tabla de percentiles. Muestra el **recorrido** del
drawdown, no solo su máximo: una caída del 30% de golpe y otra que se arrastra
medio año son la misma cifra y dos experiencias distintas.

Las curvas simuladas **no son inventadas**: se eligen, de la submuestra que ya
se guardaba para las bandas, las simulaciones concretas cuyo drawdown máximo cae
más cerca de cada percentil, y se devuelve su recorrido entero.

```python
def closest(target):
    idx = int(np.argmin(np.abs(band_dds - target)))
    return _underwater(band_curves[idx]).round(3).tolist()
```

Verificado — el mínimo de cada curva devuelta coincide con su objetivo:

| Curva | Mínimo real | Objetivo |
|---|---|---|
| real | −27,35% | −27,35% |
| mediana | −18,58% | −18,58% |
| p95 | −29,26% | −29,26% |
| p99 | −35,36% | −35,38% |

Se dibujan **solo** el real (área rellena) y dos líneas (mediana y p95). Con
cuatro curvas superpuestas el gráfico era ilegible. Leyenda **debajo** del
lienzo: dentro la tapaban las propias curvas.

### 6.3 Walk Forward

#### Dos modos, porque responden a cosas distintas

**RÁPIDO** — no re-ejecuta nada. Parte los trades ya guardados en ventanas y
compara la primera mitad de cada una (IS) con la segunda (OOS). Instantáneo
(**86 ms**). Sirve para ver **degradación**.

> **Lo que NO es:** un walk-forward canónico, porque no se re-optimiza nada — no
> hay parámetros ajustados en IS que validar en OOS. Su "eficiencia" es
> orientativa, y así se dice en la interfaz.

**COMPLETO** — el de verdad. En cada ventana:

1. barre una rejilla de parámetros sobre el tramo IS
2. se queda con la combinación que maximiza la métrica elegida
3. la aplica, tal cual, al tramo OOS que **no ha visto**

#### Ventanas

```python
seg = n_dias // n_windows
oos_len = max(1, int(seg * oos_pct / 100))
is_len  = seg - oos_len
# rolling  : is_start = seg_start        (tramo móvil)
# anchored : is_start = 0                (el IS arranca siempre en el primer día)
```

#### WFO Efficiency

`OOS / IS` de la métrica elegida, **mediana** de las ventanas. Devuelve `null`
si el IS no fue positivo: dividir por un número negativo no dice nada, y es
preferible dejarlo en blanco a inventar una cifra.

**La métrica SÍ cambia el resultado.** Medido:

| Métrica | Eficiencia mediana | Veredicto |
|---|---|---|
| Sharpe | 0,76 | Pasa el test |
| Retorno | 0,283 | Gana, pero muy degradada |
| Profit factor | 1,026 | Pasa el test |

> ⚠️ **Trampa de interfaz:** si al cambiar un mando el panel sigue mostrando el
> resultado anterior sin avisar, parece que la métrica no hace nada. Es
> imprescindible un aviso de "resultado obsoleto". Está implementado en los
> cuatro módulos con botón de ejecución.

#### Veredicto: ¿pasa el test?

No basta con la eficiencia. Una estrategia puede tener eficiencia 0,9 y haber
perdido dinero en 5 de 6 ventanas. El veredicto cruza **tres** cosas, y en este
orden:

```
1. ¿ganó dinero fuera de muestra?     cons < 50%           -> NO PASA
2. eficiencia >= 0,7                                        -> PASA
3. eficiencia >= 0,5                                        -> PASA CON RESERVAS
4. resto (gana pero conserva < 50%)                         -> GANA, PERO MUY DEGRADADA
   caso especial: eficiencia >= 1,5                         -> NO CONCLUYENTE
```

> **Una eficiencia muy por encima de 1 NO es buena noticia.** Significa que el
> tramo de optimización rindió poco comparado con el de validación, casi siempre
> porque las ventanas son pocas o cortas. Es ruido, no virtud. Nuestra primera
> versión daba "rango sano" a cualquier valor ≥0,7 y una prueba devolvió 3,91.

#### Qué valor usar de verdad: análisis de meseta

El ganador de una ventana suelta es el que mejor se ajustó a **ese** tramo — que
es justo de lo que el walk-forward existe para desconfiar. Lo que sirve es la
**meseta**: la zona de valores que va bien en todas.

Por cada valor del parámetro se devuelve:

| Campo | Qué es |
|---|---|
| `mean` | puntuación media entre ventanas |
| `std` | dispersión de esa media |
| `min` | su peor ventana |
| `wins` | en cuántas ventanas fue el mejor |
| `plateau` | **media del valor y sus dos vecinos** ← por esto se recomienda |

Un pico aislado rodeado de malos resultados cae en `plateau`; una meseta ancha
aguanta.

Además, **estabilidad del óptimo** = desviación típica de los ganadores entre
ventanas, normalizada por el ancho del barrido:

```
< 0,15  -> estable
< 0,30  -> dudosa
>= 0,30 -> ruido   (ese parámetro no tiene un valor bueno estable)
```

> ⚠️ **Aviso de borde:** si el recomendado cae en un extremo del rango barrido,
> casi siempre significa que el óptimo está FUERA y la rejilla se quedó corta.
> Lo que ves no es un máximo, es donde dejaste de mirar. Hay que avisarlo.

Ejemplo medido (Stop Loss, 20–70, 5 pasos, 3 ventanas):

```
   valor     media    meseta      peor   gana      std
    20.0   14.2308   22.7054    0.2523   0/3  14.7937
    32.5     31.18   29.6207    9.9329   0/3  18.1342
    45.0   43.4513   39.1256   10.2938   1/3  34.0699
    57.5   42.7454   44.6654    5.4191   0/3  43.4203
    70.0   47.7996   45.2725     11.58   2/3  41.9389
recomendado: 70.0  ·  estabilidad: dudosa (0,236)  ·  EN EL BORDE DEL RANGO
```

#### Matriz del walk-forward

Ventanas × valores del parámetro, coloreado por la métrica. Vista 3D y mapa
plano, con un círculo marcando el ganador de cada ventana. Si el óptimo se queda
en la misma zona ventana tras ventana, el parámetro es robusto; si salta de un
extremo a otro, lo que estás optimizando es ruido.

### 6.4 Margen de EV — Black Swan

**Hueco reservado, sin lógica.** Aparece en el raíl con su sitio pero no calcula
nada ni llama a ningún endpoint.

### 6.5 Locates vs Slippage

#### Cómo se cobran los locates (importante)

```python
blocks_of_100 = math.ceil(max_short_size_today / 100.0)
daily_locates_fee = blocks_of_100 * cost_per_100
```

Tres cosas:

1. **Paquetes de 100, redondeando hacia arriba.** 101 acciones = 2 paquetes.
2. Se cobra **una vez por ticker y día**, sobre `max_short_size_today` — el
   mayor tamaño abierto esa sesión —, **no una vez por operación**.
3. Se resta del **primer short** del día y se refleja en la curva de equity. El
   `pnl` guardado ya es **neto** de locates.

Con `locate_type = "PERCENT"` el coste por paquete es
`day_risk_unit * (locates_cost / 100)`; con `"FLAT"` es el valor tal cual.

#### La idea que hace viables los módulos pesados

Un backtest son dos cosas muy desiguales:

1. cargar las velas de minuto y traducir la estrategia a señales → **lo caro**
2. simular la ejecución sobre esas señales → **lo barato**

`locates_cost` y `slippage` **no intervienen en el paso 1**: no cambian la
definición de la estrategia ni cuándo entra o sale, solo cuánto cuesta cada
operación.

Por tanto: **las velas se cargan UNA vez**, las señales se cachean por
`(ticker, día)` y cada punto de la rejilla es solo el paso 2.

```python
res = run_backtest(
    qualifying_df=ctx["qualifying_df"],
    strategy_def=strategy_def,
    slippage=_slip(slippage),          # % real -> fracción
    locates_cost=lc,
    day_group_iter=iter(ctx["groups"]),
    n_groups_hint=ctx["n_groups"],
    _signal_cache=cache,               # <- la clave
    **_bt_kwargs(backtest_params),
)
```

> **Nota de plataforma:** en Windows solo existe el método de arranque `spawn`,
> así que el optimizador ya cae a su vía secuencial con caché compartida. En
> Linux (`fork`/`forkserver`) el pool paralelo sí funciona y habría que decidir
> si merece la pena: la caché de señales es por proceso.

#### Dos vistas

**Modelización (1D):** una curva de equity por cada coste de locates, eje X
conmutable entre tiempo y trades. Devuelve el **coste máximo asumible**
(interpolando dónde el retorno **neto de gastos** cruza cero).

**Matriz 3D (2D):** un backtest real por celda. X = locates, Y = slippage,
Z = retorno neto / Sharpe / EV. Con:

- **plano Z=0 translúcido** — donde la superficie lo atraviesa está la frontera
- **curvas de nivel proyectadas en la base** — esa frontera vista desde arriba
- **marcador del punto real de operación** con plomada hasta el plano cero, para
  ver de un vistazo cuánto margen queda

#### Cifras de control

Modelización, ventana feb–ago 2026, slippage 0,1%, gastos 500 $/mes:

| Locates $/100 | Retorno BRUTO | Retorno NETO | Gastos |
|---|---|---|---|
| 0,50 | +242,16% | **+207,16%** | 3.500 $ |
| 1,875 | −0,92% | −35,92% | 3.500 $ |
| 3,25 | −78,26% | −113,26% | 3.500 $ |

→ punto de equilibrio sobre el **neto**: **1,67 $/100 acciones**
(sobre el bruto habría salido ~1,86 — de ahí la corrección de §2.4).

Frontera de la matriz (mismo periodo):

| Slippage | Locates máximo asumible |
|---|---|
| 0,05% | 1,99 $ |
| 0,17% | 1,86 $ |
| 0,28% | 1,69 $ |
| 0,40% | 1,63 $ |

---

## 7. Diseño y comportamiento de la interfaz

### 7.1 Estructura

```
┌──────────────────────────────────────────────────────────┐
│  ESTRATEGIAS GUARDADAS   (desplegable con TODAS las cond.)│
├────────────────┬─────────────────────────────────────────┤
│ MOTORES        │  RESULTADOS                             │
│ (raíl, plegable)│  (gráficos + datos + explicaciones)     │
│  · Análisis    │                                         │
│  · Monte Carlo │                                         │
│  · Walk Forward│                                         │
│  · Black Swan  │                                         │
│  · Locates     │                                         │
└────────────────┴─────────────────────────────────────────┘
```

Grid: `minmax(280px, 340px) minmax(0, 1fr)`. El raíl es `sticky`.

### 7.2 Reglas aprendidas

- **El plegado debe ser independiente de qué módulo está activo.** Si solo se
  puede cerrar abriendo otro, no se puede consultar los resultados sin la
  configuración delante.
- **Aviso de resultado obsoleto** en todo módulo con botón de ejecución. Sin él,
  cambiar un mando parece no hacer nada.
- **Los tooltips van por portal a `document.body`.** Los paneles tienen scroll y
  `overflow` propio; un globo posicionado dentro se recorta justo cuando el
  icono está cerca del borde, que es casi siempre.
- **Nada de valores de diseño en crudo.** Todo sale de los tokens
  (`components/ui/tokens.ts`): `color.copper`, `font.mono`, `radius.md`…
- **Escala logarítmica** en toda curva de capital: una estrategia que compone
  recorre dos órdenes de magnitud y en lineal los primeros meses se aplastan
  contra el eje, que es justo donde se decide si sobrevives.
- **Paleta divergente centrada en cero** en la matriz, para que el color diga
  "gana o pierde" y no solo "más o menos". Sin centrar, una superficie toda
  negativa se pintaría verde. Que sea un degradado **continuo**: probamos un
  corte gris duro en el cero y solo ensuciaba.

### 7.3 Ayuda contextual

Icono `?` con globo en cada métrica no evidente: drawdown, Ulcer index,
percentiles, eficiencia WFO, cómo leer el histograma de rachas, por qué hay dos
cifras de tiempo en drawdown, cómo se cobran los locates y por qué el slippage
guardado vale cien veces lo que parece.

### 7.4 Parámetros de ejecución visibles

En el desplegable de la estrategia, junto a universo / entrada / salida /
riesgo, hay una columna **Ejecución**: capital inicial, riesgo por trade,
locates, slippage (convertido a % real), comisiones y periodo. Sin esos datos no
se pueden interpretar ni el retorno ni el resto de gráficos.

---

## 8. Rendimiento medido

Máquina: 16 GB RAM, Windows, DuckDB local de 62 GB, caché de intradía por
ticker-mes ya caliente.

### Instantáneo (sobre trades guardados)

| Operación | Tiempo |
|---|---|
| Listado de estrategias (caliente) | 32–40 ms |
| Cargar corrida (3.544 trades) | 613 ms |
| Análisis básico completo | inmediato (cliente) |
| Test de estrés | 0,03–0,69 s |
| Monte Carlo 5.000 sims | 0,53–0,87 s |
| WFO rápido, 6 ventanas | 86 ms |

### Pesado (re-ejecuta backtests)

| Escenario | Carga de velas | Por punto |
|---|---|---|
| Rango completo (4.891 día·ticker) | 71,9 s | ~18 s |
| Medio año (1.452 día·ticker) | 31,5 s (2,8 s en caliente) | 4,9 s (1º: 6,6 s) |
| WFO 3 ventanas × 4 pasos (15 backtests) | 88 s | 3,9 s |

**Dos cosas que abaratan mucho:**

1. **Acotar las fechas.** El coste escala con los día·ticker cargados.
2. **En el WFO, cada backtest solo cubre SU ventana**, no el histórico entero:
   el coste por punto baja al subir el número de ventanas.

La caché de señales solo sobrevive si **ningún** parámetro toca los indicadores.
Con parámetros de `risk_management` se reutiliza; con parámetros de indicador
hay que recalcular. La interfaz marca cuáles son "baratos".

---

## 9. Despliegue

### Variables de entorno

```bash
# backend/.env
ROBUSTNESS_ENABLED=true

# frontend/.env.local
NEXT_PUBLIC_ROBUSTNESS_ENABLED=true
```

Ambas **apagadas por defecto**. Sin ellas: 503 en el router, entrada de menú
invisible. Producción no ve ningún cambio de comportamiento.

La variable del backend se lee **en cada petición**:

```python
def _enabled() -> bool:
    return os.getenv("ROBUSTNESS_ENABLED", "false").strip().lower() in ("1","true","yes","on")
```

Leerla al importar el módulo la congela a vacío, porque el import puede ocurrir
antes de que `load_dotenv()` haya poblado el entorno.

### Dependencias

Ninguna nueva. Usa lo que ya está: `numpy`, `pandas`, `duckdb`, `msgpack` en el
backend; `plotly.js-dist-min` + `react-plotly.js` (carga dinámica, `ssr: false`)
y SVG a mano en el frontend.

---

## 10. Cómo verificar tu implementación

Estas cifras salen de la estrategia de prueba: **3.544 trades, 2024-08-20 →
2026-08-14, `init_cash` 10.000 $, `risk_r` 3% PERCENT, `locates_cost` 1,
`slippage` 0.001**. Si tu implementación las reproduce, es correcta.

### 10.1 Control maestro — la re-ejecución debe ser idéntica

Re-ejecuta la estrategia con exactamente sus parámetros guardados y compara con
la corrida del Baúl:

| | Re-ejecutado | Guardado |
|---|---|---|
| Retorno | **581,6725%** | 581,6725% |
| Max drawdown | **−27,3496%** | −27,3496% |
| Trades | 3.544 | 3.544 |
| Profit factor | 1,2312 | 1,2312 |

Idéntico dígito a dígito. Si no coincide, la maquinaria de rejilla está mal
montada y todo lo demás es ruido.

### 10.2 R exacta

```
equity reconstruida con R exacta : 68.167,24 $
equity real                      : 68.167,25 $
desvío                           : −0,000015%
max DD reconstruido              : −27,3500%   (real −27,3496%)
```

### 10.3 Análisis básico

```
Max drawdown           −27,35%
DD más largo           107 sesiones / 157 días naturales / 21,4% del histórico
Tiempo total en DD     74,7%  ·  47 episodios, todos recuperados
Ulcer index            8,61
Racha perdedora máx    8 trades  (−5.014 $)
Racha ganadora máx     14 trades (+5.278 $)
Peor día               −3.620 $ (2026-05-09)
```

Las rachas deben coincidir con `max_consecutive_losses` y
`max_consecutive_wins` de `aggregate_metrics` (8 y 14).

### 10.4 Estrés

```
quitar el mejor 10%  ->  +581,7%  se convierte en  −89,2%   (DD −89,7%, PF 0,77)
```

Si te sale un número por debajo de −100%, estás sumando dólares (§2.2).

### 10.5 Monte Carlo (5.000 sims, bootstrap, por día)

```
DD real           −27,4%     <- debe coincidir con el guardado
DD mediano        −18,9%
Aguantar el 95%   −30,1%
Aguantar el 99%   −36,1%
Final p50         67.673 $   <- debe quedar cerca del real, 68.167 $
```

### 10.6 Walk Forward rápido (6 ventanas, 30% OOS, rolling)

```
métrica=sharpe          -> eficiencia mediana 0,76   consistencia 83,3%
métrica=total_return    -> eficiencia mediana 0,283
métrica=profit_factor   -> eficiencia mediana 1,026
```

Si las tres dan lo mismo, la métrica no está llegando al cálculo.

### 10.7 Locates

```
punto de equilibrio, sin gastos       ~1,86 $/100 acc
punto de equilibrio, 500 $/mes        ~1,67 $/100 acc
```

Si los gastos no mueven el punto de equilibrio, estás usando
`total_return_pct` en vez del neto (§2.4).

---

## 11. Resumen de lo que NO se ha tocado

Para que quede claro qué es seguro y qué no en producción:

| Fichero | Estado | Por qué |
|---|---|---|
| `what_if_service.py` | **sin tocar** | lo usa el Backtester; tiene el problema de §2.2 |
| `montecarlo_service.py` | **sin tocar** | lo usa el Backtester; tiene el problema de §6.2 |
| `portfolio_sim_jit.py` | **sin tocar** | ahí está la unidad del slippage de §2.3 |
| `backtest_service.py` | **sin tocar** | ahí está `total_return_pct` de §2.4 |
| `strategy_search.py` | **sin tocar** | el endpoint de 48 MB de §3.2 |
| `app/main.py` | **+3 líneas** | import + `include_router` |
| `Sidebar.tsx` | **+16 líneas** | entrada de menú, tras el flag |

Todo lo demás son ficheros nuevos.

---

## 12. Pendientes conocidos

- **Black Swan** está vacío a propósito.
- El **WFO completo** solo optimiza **un parámetro** a la vez. La estructura
  admite varios (`param_configs` es una lista y el barrido es un `product`),
  pero la matriz y el análisis de meseta solo están implementados para uno.
- La **matriz locates×slippage** no cachea entre ejecuciones: cambiar un rango
  vuelve a cargar las velas (mitigado por la caché de mes en disco: 31,5 s →
  2,8 s en la segunda pasada del mismo periodo).
- En Linux convendría revisar si el pool paralelo del optimizador compensa aquí
  (§6.5).
