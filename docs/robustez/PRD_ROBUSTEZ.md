# PRD — Módulo de Robustez de Estrategias (Market & Strategy Analysis)

> **Qué es este documento.** Un PRD funcional y conceptual completo para el nuevo módulo **Robustez** de la plataforma Edgecute. Está redactado siguiendo la metodología del PM Manual, anclando cada requerimiento en la estructura de código del repositorio y definiendo con absoluta precisión matemática y lógica las reglas de trading y de simulación.
> 
> **Objetivo del feature.** Someter las estrategias guardadas en el Baúl (provenientes de ejecuciones del backtest) a diversas pruebas de stress, re-muestreo estadístico y optimización walk-forward. Esto permite validar si el "edge" de la estrategia es real, duradero y resistente ante condiciones adversas de mercado y ejecución, antes de poner capital real en juego.

---

## Índice del PRD

- [00 · Índice y trazabilidad (fuentes auditadas)](#s00)
- [01 · Viabilidad (reality check)](#s01)
- [02 · PRD: qué, para quién, nomenclatura y reglas](#s02)
- [03 · Contrato de datos (request/response + errores)](#s03)
- [04 · UI y componentes (pantallas, estados)](#s04)
- [05 · Arquitectura (ficheros, flujo)](#s05)
- [06 · Prompt maestro de ejecución (guion de desarrollo)](#s06)
- [07 · Decisiones abiertas](#s07)
- [Apéndice · Registro de la entrevista PM↔Agente](#entrevista)

---

<a id="s00"></a>
## 00 · Índice y trazabilidad

**Feature:** Módulo de Robustez — Panel analítico para someter estrategias del Baúl a pruebas de Montecarlo, Walk-Forward Analysis (WFO), Sensibilidad de costes y Simulador de Cisne Negro.  
**Estado:** PLAN.  
**Visión en una frase:** *"Quiero saber si mi estrategia es robusta en el tiempo, resistente a costes de ejecución imprevistos y si sobrevivirá a un crash o Cisne Negro de small caps."*

### Fuentes auditadas (verdad anclada en código)

| Pieza real | Fichero | Qué aporta a este PRD |
|---|---|---|
| DDL de resultados del backtest | `backend/app/init_db.py` (líneas 224-240) | La tabla `backtest_results` almacena `results_json` con el listado de trades reales evaluados. |
| Estructura y campos del trade | `backend/app/services/backtest_service.py` → `_enrich_trades` | Nombres de campos que usaremos: `ticker`, `date`, `entry_price`, `exit_price`, `size`, `pnl`, `return_pct`, `direction`, `exit_reason`. |
| Algoritmo de Montecarlo base | `backend/app/services/montecarlo_service.py` | Implementación del endpoint actual (línea 9) que baraja PnLs de forma secuencial. |
| Simulación What-if existente | `backend/app/services/what_if_service.py` | Patrón de inyección de Black Swans y costes de slippage sobre trades históricos (líneas 158-196). |
| Extracción de parámetros optimizables | `backend/app/services/optimization_service.py` | Función `extract_parameters()` (línea 225) para determinar qué variables se pueden optimizar en el WFO. |
| Motor de optimización por grid | `backend/app/services/optimization_service.py` | Lógica de `run_optimization_grid()` (línea 565) que reusaremos para las ventanas In-Sample. |
| Pestañas y DataGrids de la UI | `frontend/src/components/DataGrid.tsx` | Componentes de grids reutilizables para listar estrategias y trades. |
| Tokens de Diseño | `.agent/EDGECUTE_DESIGN_SYSTEM.md` | Colores semánticos (`--ec-profit`, `--ec-loss`), tipografía (Fraunces, General Sans) y tarjetas. |

---

<a id="s01"></a>
## 01 · Viabilidad

### 1.1 Restricciones y coste
* **Procesamiento en memoria:** Los Módulos 1 (Montecarlo), 3 (Sensibilidad) y 4 (Black Swan) operan directamente sobre el array de trades históricos pre-calculados de la estrategia. Esto es $O(K \times S)$ en CPU, donde $K$ es el número de trades y $S$ las simulaciones. Al correr sobre arrays de numpy pequeños (cientos o miles de trades), la respuesta es instantánea (**< 100 ms**).
* **Mapeo pesado (WFO):** El Módulo 2 (WFO) requiere ejecutar optimizaciones sobre datos históricos de mercado (DuckDB/GCS Parquet). Es un proceso muy pesado. **Debe correr como BackgroundTask** con polling en el frontend, reutilizando la infraestructura actual de optimización.
* **Payload:** Las respuestas de Montecarlo y Black Swan devuelven matrices reducidas (curvas por percentiles e histogramas de drawdown). Payload de pocos KB.

### 1.2 Riesgos y mitigaciones

| Riesgo | Impacto | Mitigación |
|---|---|---|
| WFO bloquea el servidor | Degradación de API | Se encola como tarea en background con un ID único (`task_id`) y se reporta progreso incremental en la UI. |
| Muestra de trades demasiado pequeña | Estadísticas de Montecarlo ruidosas | Si el backtest inicial tiene $K < 20$ trades, mostrar advertencia en UI: *“Trades insuficientes para un análisis estadístico fiable”*. |
| Drift de definiciones de trading | Inconsistencia en métricas | WFO y Sensibilidad usan exactamente el mismo motor y helpers de agregación (`_aggregate_metrics`) que el backtester principal. |

### 1.3 Veredicto
**Viable.** Los módulos 1, 3 y 4 son rápidos de calcular. El módulo 2 es viable al reusar el andamiaje del optimizador en segundo plano del backend.

---

<a id="s02"></a>
## 02 · PRD

### 2.1 Usuarios
* **Short-sellers de Small Caps (Jaume):** Necesita saber qué probabilidad real tiene de arruinarse si se concatenan varias operaciones perdedoras, o si la estrategia depende de haber tenido la "suerte" de entrar en 2 o 3 trades gigantescos.
* **Desarrollador Senior (Adrián):** Necesita un contrato e indicaciones precisas de qué algoritmos y funciones del backend llamar sin inventar la rueda.

### 2.2 Jobs-to-be-done
1. **Seleccionar** una estrategia testeada de la tabla superior (idéntica al Baúl).
2. **Elegir** el módulo de robustez en el panel inferior izquierdo.
3. **Configurar** las variables específicas del módulo y pulsar "Ejecutar".
4. **Visualizar** curvas de capital (estilo espagueti), histogramas y tablas de métricas estresadas en el panel derecho.

### 2.3 Alcance del MVP (Lo que SÍ entra)
* **Pantalla de Robustez:** Diseño de layout dividido (Grid superior + dos columnas inferiores).
* **Módulo 1 (Montecarlo Bootstrap con reemplazo):** Simulación de curvas de capital con remuestreo, cálculo de probabilidad de ruina configurable, percentiles de drawdown y probabilidad de retorno negativo a $N$ trades o periodos equivalentes.
* **Módulo 2 (Walk-Forward Analysis):** Partición IS/OOS por porcentajes, re-optimización paramétrica en IS (vía `extract_parameters`), evaluación ciega en OOS, concatenación de curvas OOS y métrica Walk-Forward Efficiency (WFE) y Win Rate Penalty.
* **Módulo 3 (Sensibilidad Estocástica):** Curvas multi-línea con diferentes locates ($0.5\%$ a $3.0\%$), cálculo del "Umbral Crítico de Locates" analítico, y slippage estocástico ($X\%$ probabilidad de tener $Y$ slippage).
* **Módulo 4 (Simulador de Black Swan):** Inyección de $X$ eventos de pérdidas extremas, cálculo de tiempo medio de recuperación (TTR), y probabilidad de ruina post-impacto en 100 trades. Matriz de sensibilidad posicional coloreada (verde, amarillo, rojo).

### 2.4 Fase 2 (Fuera de alcance del MVP pero preparado)
* **Broker sync / Live Trade Robustness:** Evaluar robustez con datos en tiempo real de operaciones vivas. *El MVP se limita a estrategias guardadas del Baúl.*
* **Guardado de Informes de Robustez:** Persistencia de los resultados de robustez en base de datos. *El MVP calcula en caliente y se muestra en la sesión actual.*

### 2.5 Glosario de dominio
* **In-Sample (IS):** Periodo de datos históricos usado para entrenar y buscar la mejor combinación de parámetros.
* **Out-of-Sample (OOS):** Periodo de datos históricos "no vistos" por el optimizador, usado para evaluar el rendimiento real de los parámetros encontrados.
* **Walk-Forward Efficiency (WFE):** Ratio de rendimiento que compara el retorno (o Sharpe) del OOS contra el IS.
* **Riesgo de Ruina (RoR):** Probabilidad de que el capital de la cuenta caiga por debajo de un umbral catastrófico predefinido.
* **Time to Recovery (TTR):** Número medio de trades necesarios para recuperar el nivel máximo de equity anterior a un Drawdown masivo o Black Swan.

### 2.6 Reglas de trading (Las 5 cosas por regla)

#### Regla 1 — Montecarlo Bootstrap con reemplazo
1. **Nombre oficial:** `run_montecarlo_bootstrap`.
2. **Definición operativa:** Dada una lista de $M$ trades de la estrategia, se generan $S$ simulaciones independientes. Para cada simulación, se construyen $K$ pasos seleccionando de forma aleatoria con reemplazo un trade de la lista original.
   * Si el usuario selecciona un periodo temporal (Mes, Trimestre, Año), el número de pasos $K$ se calcula como:
     \[
     K = \text{round}\left( \frac{M}{\Delta t_{\text{años}}} \times \text{factor\_periodo} \right)
     \]
     Donde `factor_periodo` es $\frac{1}{12}$ para mes, $\frac{1}{4}$ para trimestre, y $1.0$ para año.
3. **Unidades:** $S$ (entero, por defecto 1000), $K$ (entero, pasos/trades), capital inicial (USD).
4. **Sesión/Timeframe:** N/A (operación sobre el histórico consolidado).
5. **Edge case:** Si la estrategia no tiene trades ($M = 0$), el endpoint devuelve un error `400` ("No trades available for bootstrap").

#### Regla 2 — Walk-Forward Efficiency (WFE) y Win Rate Penalty
1. **Nombre oficial:** `wfe` y `win_rate_penalty`.
2. **Definición operativa:**
   * **WFE:** Ratio de rentabilidad anualizada (o Sharpe) promedio en periodos OOS vs IS concatenados:
     \[
     WFE = \left( \frac{\text{Métrica}_{\text{OOS}}}{\text{Métrica}_{\text{IS}}} \right) \times 100
     \]
     Si $WFE < 50\%$, se marca visualmente como "Inestable/Malo".
   * **Win Rate Penalty:** Degradación de la probabilidad de acierto entre el periodo de entrenamiento y prueba ciega:
     \[
     WRP = \text{WinRate}_{\text{IS}} - \text{WinRate}_{\text{OOS}}
     \]
3. **Unidades:** $\%$.
4. **Sesión/Timeframe:** Determinado por el backtest.
5. **Edge case:** Si la métrica IS es $0$ o negativa, $WFE$ se reporta como `0.0` para evitar divisiones por cero.

#### Regla 3 — Umbral Crítico de Locates
1. **Nombre oficial:** `critical_locate_threshold`.
2. **Definición operativa:** El coste de locate por acción en porcentaje en el que el Net Profit neto de locates de la estrategia es exactamente $0$. Puesto que el coste de locate se aplica linealmente a las operaciones en corto, se calcula analíticamente como:
     \[
     C_{\text{crit}} = \frac{NP_{\text{base}}}{\sum_{i \in \text{shorts}} (Size_i \times EntryPrice_i)} \times 100
     \]
     Donde $NP_{\text{base}}$ es el Net Profit antes de aplicar locates.
3. **Unidades:** $\%$.
4. **Sesión/Timeframe:** N/A.
5. **Edge case:** Si la estrategia no realiza ninguna operación en corto, $C_{\text{crit}} = \text{null}$ (se muestra como "N/A" en la UI). Si el denominador es $0$, retorna `null`.

#### Regla 4 — Riesgo de Ruina Post-Swan (Post-Swan Ruin Risk)
1. **Nombre oficial:** `post_swan_ruin_risk`.
2. **Definición operativa:** La probabilidad de que la cuenta toque el umbral de ruina en los siguientes 100 trades tras haber recibido el impacto directo de un Cisne Negro. Se calcula ejecutando una simulación de Montecarlo bootstrap de 1000 iteraciones con longitud de 100 pasos, pero inicializando el capital en:
     \[
     Capital_{\text{inicial}} = Capital_{\text{pre-swan}} - \text{Pérdida\_Swan}
     \]
3. **Unidades:** $\%$.
4. **Sesión/Timeframe:** N/A.
5. **Edgecase:** Si el balance resultante tras el Cisne Negro ya es menor o igual al umbral de ruina configurado, la métrica devuelve automáticamente `100.0%`.

---

<a id="s03"></a>
## 03 · Contrato de datos

### 3.1 Módulo 1 (Montecarlo): Request y Response

**Ruta:** `POST /api/robustness/montecarlo`
**Request JSON:**
```jsonc
{
  "strategy_id": "strat_12345",
  "init_cash": 10000.0,
  "simulations": 1000,
  "ruin_pct": 10.0,            // Ruina si queda el 10% del capital ($1000)
  "n_trades_limit": 500,       // N trades para probabilidad de retorno negativo
  "period_unit": "trimestre"   // Opcional: "mes" | "trimestre" | "año" | null (si se da, sobreescribe n_trades_limit)
}
```

**Response JSON (200 OK):**
```jsonc
{
  "simulations_run": 1000,
  "ruin_probability": 1.25,        // % de curvas que tocaron la ruina
  "worst_drawdown": -62.4,        // % Drawdown máximo histórico de todas las curvas
  "median_drawdown": -18.5,       // % Drawdown mediano
  "extreme_drawdown_p95": -32.1,  // % Drawdown percentil 95
  "extreme_drawdown_p99": -54.8,  // % Drawdown percentil 99
  "probability_negative_return": 15.4, // % de curvas que terminan por debajo de saldo inicial en N trades
  "n_trades_calculated": 500,     // N real usado
  "percentiles": {
    "p5": [ {"time": 10000000, "value": 10000.0}, ... ],
    "p25": [ ... ],
    "p50": [ ... ],
    "p75": [ ... ],
    "p95": [ ... ]
  }
}
```

### 3.2 Módulo 2 (WFO): Request y Response

**Ruta:** `POST /api/robustness/walk-forward`
**Request JSON:**
```jsonc
{
  "strategy_id": "strat_12345",
  "dataset_id": "small_caps_historical",
  "is_pct": 70.0,              // % In-Sample
  "oos_pct": 30.0,             // % Out-of-Sample
  "step_pct": 30.0,            // Desplazamiento
  "metric": "sharpe",          // Métrica para elegir el mejor en IS
  "param_configs": [
    {
      "id": "sma_period",
      "path": "definition.indicators[0].params.period",
      "min": 10.0,
      "max": 50.0,
      "steps": 5
    }
  ]
}
```

**Response JSON (200 OK - Task encolada):**
```jsonc
{
  "task_id": "wfo_task_889211",
  "status": "running",
  "progress": 0.0
}
```

**Ruta de consulta:** `GET /api/robustness/walk-forward/result/{task_id}`
**Response JSON (200 OK - Completado):**
```jsonc
{
  "status": "completed",
  "progress": 100.0,
  "wfe": 68.4,                 // Walk-forward efficiency (%)
  "win_rate_penalty": 8.5,     // IS WinRate - OOS WinRate (%)
  "oos_max_drawdown": -24.3,   // Max DD registrado en OOS concatenado (%)
  "is_metrics": { "sharpe": 1.8, "win_rate": 55.2 },
  "oos_metrics": { "sharpe": 1.23, "win_rate": 46.7 },
  "heatmap_matrix": {          // Matriz de combinaciones de parámetros y su score
    "parameters": ["sma_period"],
    "data": [
      { "values": [10.0], "is_score": 1.1, "oos_score": 0.7 },
      { "values": [20.0], "is_score": 1.8, "oos_score": 1.23 }
    ]
  }
}
```

### 3.3 Módulo 3 (Sensibilidad): Request y Response

**Ruta:** `POST /api/robustness/sensitivity`
**Request JSON:**
```jsonc
{
  "strategy_id": "strat_12345",
  "locate_range": { "min": 0.5, "max": 3.0, "step": 0.5 },
  "slippage_probability": 15.0,  // X%
  "slippage_value": 0.02         // Y USD
}
```

**Response JSON (200 OK):**
```jsonc
{
  "critical_locate_threshold": 1.85, // %
  "curves": {
    "locate_0.5": [ {"time": 10000000, "value": 11200.0}, ... ],
    "locate_1.0": [ ... ],
    "locate_1.5": [ ... ],
    "locate_2.0": [ ... ],
    "locate_2.5": [ ... ],
    "locate_3.0": [ ... ]
  }
}
```

### 3.4 Módulo 4 (Black Swan): Request y Response

**Ruta:** `POST /api/robustness/black-swan`
**Request JSON:**
```jsonc
{
  "strategy_id": "strat_12345",
  "init_cash": 10000.0,
  "black_swan_count": 3,
  "severity_multiplier": 10.0,   // -1000% de la pérdida promedio
  "ruin_pct": 10.0
}
```

**Response JSON (200 OK):**
```jsonc
{
  "time_to_recovery_trades": 45,       // Media de trades para recuperar el pico pre-swan
  "post_swan_ruin_risk_100t": 18.3,   // Probabilidad de ruina en los siguientes 100 trades
  "sensitivity_matrix": [              // Matriz para pintar el mapa de calor
    {
      "position_size_pct": 1.0,        // % del capital arriesgado
      "severity_multiplier": 5.0,
      "ruin_probability": 2.1,
      "max_drawdown": 14.5,
      "zone": "GREEN"                  // GREEN | YELLOW | RED
    },
    {
      "position_size_pct": 2.0,
      "severity_multiplier": 10.0,
      "ruin_probability": 18.3,
      "max_drawdown": 38.2,
      "zone": "YELLOW"
    },
    {
      "position_size_pct": 5.0,
      "severity_multiplier": 10.0,
      "ruin_probability": 65.4,
      "max_drawdown": 82.1,
      "zone": "RED"
    }
  ]
}
```

### 3.5 Catálogo de Errores

| Código HTTP | Código Interno | Motivo |
|---|---|---|
| `400` | `INVALID_STRATEGY` | La estrategia seleccionada no existe o no tiene un backtest válido ejecutado. |
| `400` | `PARAMETER_OUT_OF_BOUNDS` | Parámetros de simulación fuera de rango (ej. $S > 10000$ o step WFO $\le 0$). |
| `500` | `PROCESSING_ERROR` | Error matemático interno o de base de datos durante la optimización IS. |

---

<a id="s04"></a>
## 04 · UI y componentes

### 4.1 Wireframe textual de la página "Robustez"

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│  Robustez de Estrategias                                                               │
├────────────────────────────────────────────────────────────────────────────────────────┤
│  [1] Selecciona Estrategia del Baúl (Filtros de Ticker, Fecha, Dirección...)           │
│  ┌──────────┬─────────────┬──────────┬───────────┬─────────────┬───────────┬─────────┐ │
│  │ Ticker   │ Nombre      │ Trades   │ Win Rate  │ Net Profit  │ Executed  │ Select  │ │
│  ├──────────┼─────────────┼──────────┼───────────┼─────────────┼───────────┼─────────┤ │
│  │ AMD      │ Gap&Crap    │ 142      │ 58.2%     │ $4,210.00   │ 24-06-26  │ [ X ]   │ │
│  └──────────┴─────────────┴──────────┴───────────┴─────────────┴───────────┴─────────┘ │
├────────────────────────────────────────────────────────────────────────────────────────┤
│  [2] Configuración de Robustez           │ [3] Resultados y Visualización              │
│  Selector de Módulo:                     │ Curvas de Capital / Spaguetti Chart         │
│  (Montecarlo) [WFO] (Sensibilidad) [Swan]│                                             │
│                                          │ 📈 [Gráfico interactivo multi-curvas]       │
│  Configuración del Módulo:               │                                             │
│  - Window IS: [ 70 ] %                   │ ------------------------------------------- │
│  - Window OOS: [ 30 ] %                  │ Estadísticas Destacadas:                    │
│  - Step: [ 30 ] %                        │ ┌───────────────┐ ┌───────────────┐         │
│  - Métrica: [ Sharpe ]                   │ │ WFE           │ │ Win Rate Pen. │         │
│  - Variables a optimizar:                │ │    68.4%      │ │     8.5%      │         │
│    [x] SMA Period (10-50, step 5)        │ │  (Estable)    │ │   (Normal)    │         │
│                                          │ └───────────────┘ └───────────────┘         │
│  [ EJECUTAR PRUEBA DE ROBUSTEZ ]         │                                             │
│  (Advertencia: WFO es un proceso pesado) │ (Matriz de Sensibilidad o heatmap abajo)    │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

### 4.2 Los 4 estados obligatorios de la UI

1. **Loading:** Spinner de carga y Skeleton de las tarjetas de métricas. En WFO, barra de progreso interactiva cargada mediante polling a `GET /api/robustness/walk-forward/progress/{task_id}`.
2. **Empty:** Mensaje central sobre el fondo: *"Selecciona una estrategia del Baúl y pulsa 'Ejecutar' para iniciar el análisis de robustez."*
3. **Error:** Banner rojo de `AlertCircle` indicando el error (ej. trades insuficientes) con botón de reintento.
4. **Success:** Renderizado completo del gráfico de curvas, tarjetas de métricas e indicadores de umbral crítico destacados.

### 4.3 Comportamiento e Interacciones
* **Puntero y Tooltips:** Al pasar el ratón por los títulos de métricas (ej. *WFE, RoR, TTR, Post-Swan Risk*), se despliega un popover detallado con fórmulas y ejemplos claros de interpretación (ver glosario y minuta).
* **Color Semántico de Trading:**
  * WFE $\ge 50\%$, RoR $< 5\%$ y post-swan risk $< 5\%$ $\rightarrow$ Verde `--ec-profit` (`#4A9D7F`).
  * WFE entre $40-50\%$, RoR/post-swan risk entre $5-20\%$ $\rightarrow$ Amarillo/Cobre `--ec-copper` (`#D87A3D`).
  * WFE $< 40\%$, RoR/post-swan risk $> 20\%$ $\rightarrow$ Rojo `--ec-loss` (`#C94D3F`).

---

<a id="s05"></a>
## 05 · Arquitectura

### 5.1 Ficheros implicados

**Backend:**
* `backend/app/routers/robustness.py` [NUEVO]: Router fino que expone los endpoints descritos en el contrato.
* `backend/app/services/robustness_service.py` [NUEVO]: Implementación de los algoritmos:
  * Remuestreo bootstrap con reemplazo.
  * Lógica de WFO encadenando optimizaciones.
  * Análisis analítico de umbral crítico de locates y simulación estocástica.
  * Inyección y estadísticas post-swan (TTR y RoR 100t).
* `backend/app/main.py`: Registro del nuevo router.

**Frontend:**
* `frontend/src/lib/api.ts`: Añadir tipos de respuesta y llamadas cliente para los endpoints de robustez.
* `frontend/src/app/robustness/page.tsx` [NUEVO]: Página principal de robustez.
* `frontend/src/components/robustness/RobustnessConfig.tsx` [NUEVO]: Panel izquierdo de configuración.
* `frontend/src/components/robustness/RobustnessCharts.tsx` [NUEVO]: Renderizador de spaguetti charts (recharts) y matrices de sensibilidad.

### 5.2 Flujo de Datos del WFO
```
UI (robustness/) ──> POST /walk-forward ──> backend encola BackgroundTask
                                                  │
UI inicia polling <── HTTP 200 (task_id) <────────┘
    │
    ▼
GET /walk-forward/result/{task_id} ──> Lee estado de la tarea
    │
    ├──> (completed) ──> Retorna WFE + Heatmap ──> UI renderiza heatmaps
```

---

<a id="s06"></a>
## 06 · Prompt maestro de ejecución

### 0. Contexto obligatorio antes de tocar nada
1. Este documento (`docs/robustez/PRD_ROBUSTEZ.md`).
2. Ficheros del backend: `app/routers/backtest.py`, `app/services/montecarlo_service.py`, `app/services/what_if_service.py` y `app/services/optimization_service.py`.
3. Guía de diseño: `.agent/EDGECUTE_DESIGN_SYSTEM.md` y `.agent/CODING_RULES.md`.

### 1. Restricciones globales
* Lógica siempre en `services/`, nunca en `routers/`.
* WFO debe ser asíncrono y monitorizable por `task_id` para no bloquear el hilo principal.
* Las simulaciones rápidas (Montecarlo, Sensibilidad, Black Swan) se ejecutan en caliente en el backend y retornan de forma síncrona en <200ms.
* Todo cálculo sobre arrays se optimiza mediante `numpy` y se valida con tests unitarios.

### 2. Secuenciación atómica (EPICs)

#### EPIC A — Backend Lógica & Endpoints
* **A1. Implementar Bootstrap en Montecarlo:** Modificar o extender `montecarlo_service.py` para usar remuestreo con reemplazo (`rng.choice`), cálculo de percentiles de drawdown (P95, P99), e indicador de pérdida en $N$ trades.
  * *Test:* `tests/test_montecarlo_bootstrap.py`.
* **A2. Implementar Motor WFO:** En `robustness_service.py`, implementar partición temporal de datos, llamada a `run_optimization_grid` en IS, y validación en OOS.
  * *Test:* `tests/test_wfo_engine.py`.
* **A3. Sensibilidad de Locates y Slippage:** Implementar la inyección estocástica de slippage en trades y la deducción analítica del umbral crítico.
  * *Test:* `tests/test_sensitivity.py`.
* **A4. Simulador Black Swan y Métricas Post-Swan:** Implementar la inyección de cisnes negros aleatorios en trades, cálculo del TTR promedio, y simulación de RoR post-swan en 100 trades.
  * *Test:* `tests/test_black_swan.py`.
* **A5. Router e Integración:** Exponer en `routers/robustness.py` y registrar en `main.py`.
  * *Verif:* `pytest tests/ -q` y arrancar uvicorn.

#### EPIC B — Frontend (UI)
* **B1. API client & Types:** Declarar tipos y llamadas en `lib/api.ts`.
* **B2. Panel de selección superior:** Reusar DataGrid de estrategias guardadas.
* **B3. Panel de Configuración y Módulos:** Crear formularios con los 4 módulos y validaciones.
* **B4. Visualizaciones de resultados:** Gráfico de espagueti para curvas e histograma/matriz de calor para WFO y Black Swan.
* **B5. Integración y Tooltips:** Pulir diseño sin excesivos bordes, integrar tooltips informativos y colores según los umbrales definidos en la minuta.

---

<a id="s07"></a>
## 07 · Decisiones abiertas

### A. Decisiones de PRODUCTO (dueño: Jesús)
* **Tasa de cálculo en WFO:** WFO puede tardar varios minutos dependiendo de la estrategia y los rangos de optimización. ¿Deberíamos limitar la cantidad máxima de combinaciones paramétricas a evaluar en WFO en el MVP (ej. máx. 50 combinaciones)?  
  * *Recomendación:* Sí, capar a 50 combinaciones en el MVP para evitar sobrecarga del servidor en desarrollo.

### B. Defaults técnicos reversibles (asumidos por el agente)
* **Cantidad de simulaciones por defecto:** 1000 iteraciones para Montecarlo y Black Swan (equilibrio perfecto entre precisión estadística y latencia).
* **Step temporal por defecto:** Si no se especifica, el "Trimestre" se calcula en base a 65 trades históricos (asumiendo ~260 días de trading anualizados).

---

<a id="entrevista"></a>
## Apéndice · Registro de la entrevista PM↔Agente

### Preguntas clave resueltas durante el análisis:

* **PM (Jaume):** Nos gusta la recomendación de usar equivalencia temporal para estimar $N$ trades de retorno negativo.
* **PM (Jaume):** El riesgo de ruina representa perder el capital, pero debe ser parametrizable para que el usuario elija qué porcentaje le queda antes de considerarse arruinado. (Añadido slider `% ruina` en MVP).
* **PM (Jaume):** En el WFO, nos aseguramos de optimizar solo parámetros numéricos válidos (usando la extracción automática del optimizador actual).
* **PM (Jaume):** En el Módulo 3, el umbral crítico calcula cuándo el Net Profit llega a cero. El slippage aleatorio simula problemas graves de ejecución (micro Black Swans de deslizamiento).
* **PM (Jaume):** En el Módulo 4, nos encanta la métrica de supervivencia post-cisne: calcular el tiempo de recuperación (TTR) y la probabilidad de ruina post-swan en los siguientes 100 trades usando Montecarlo.
* **PM (Jaume):** Fijamos los colores de la matriz: Verde (ruina <5%, DD <20%), Amarillo (ruina 5-20%, DD 20-40%), Rojo (ruina >20% o DD >40%).
