# 03 — Contrato de datos

## 3.1 Origen de la serie diaria (clave para todo el módulo)

El portfolio **no** recalcula backtests: deriva la serie de retornos diarios desde lo ya
persistido en `backtest_results` (DuckDB **por-usuario**).

```
backtest_results.results_json
  ├─ day_results: [ { date, pnl/return_r/..., ... }, ... ]   ← fuente de la serie diaria
  ├─ equity_curves: [ { ticker, date, equity:[...] }, ... ]  ← intradía por ticker-día (no usar aquí)
  └─ all_trades / day-level stats
```

**Derivación canónica (`portfolio_analytics_service`):**
1. Para cada `backtest_id`, leer `results_json.day_results` y construir una serie `{date → pnl}`.
2. Convertir a retorno diario sobre el capital de simulación (`return_t = pnl_t / capital_base`).
3. **Alinear todas las series al calendario unión**; día sin trades de una estrategia → `0.0`.
4. Curva combinada: `equity_t = init_cash · ∏(1 + Σ_i w_i · r_{i,t})` (o aditivo en USD según
   convención del Cuadro de Riesgo — fijar en Fase 1 y testear).

> **Regla:** toda la lógica vive en `portfolio_analytics_service.py`. El router solo valida,
> resuelve el Baúl del usuario y serializa. La derivación se testea con un DataFrame ficticio
> antes de tocar datos reales (TDD, Fase 1).

## 3.2 Modelos Pydantic — `backend/app/schemas/portfolio.py` [NEW]

```python
from pydantic import BaseModel, Field
from typing import List, Dict, Optional, Literal

class PortfolioCombineRequest(BaseModel):
    backtest_ids: List[str] = Field(..., min_items=1)
    weights: Optional[Dict[str, float]] = Field(None, description="backtest_id -> peso (suma 1.0). None = equiponderado.")

class PortfolioCombineResponse(BaseModel):
    timestamps: List[int]                 # epoch diario común
    combined_equity: List[float]
    combined_drawdown: List[float]
    metrics: Dict[str, float]             # Sharpe, total_return_pct, max_drawdown_pct, ...

class MontecarloSimulationRequest(BaseModel):
    backtest_ids: List[str]
    weights: Dict[str, float]
    simulations: int = Field(1000, ge=100, le=10000)
    init_cash: float = Field(10000.0, ge=100.0)

class MontecarloSimulationResponse(BaseModel):
    percentiles: Dict[str, List[float]]   # p5,p25,p50,p75,p95 (equity temporal)
    var_95_pct: float;  var_95_usd: float
    var_99_pct: float;  var_99_usd: float
    cvar_95_pct: float; cvar_95_usd: float
    cvar_99_pct: float; cvar_99_usd: float
    ruin_probability: float

class CorrelationMatrixRequest(BaseModel):
    backtest_ids: List[str]

class CorrelationMatrixResponse(BaseModel):
    labels: List[str]
    pearson: List[List[float]]            # NxN
    spearman: List[List[float]]           # NxN

class CapitalAllocationRequest(BaseModel):
    backtest_ids: List[str]
    method: Literal["leaders", "hrp"]
    lookback_days: Optional[int] = Field(15, description="Ventana para Líderes (default 15, decidido).")
    leaders_weights: Optional[List[float]] = Field(None, description="Pesos por ranking (mejor→peor).")
    kelly_fraction: Optional[float] = Field(None, ge=0.0, le=1.0)

class CapitalAllocationResponse(BaseModel):
    weights: Dict[str, float]             # suman 1.0
    comparison_equity: List[float]
    comparison_drawdown: List[float]
    metrics: Dict[str, float]

class AccountScalingRequest(BaseModel):
    backtest_ids: List[str]
    weights: Dict[str, float]
    init_cash: float = Field(10000.0, ge=100.0)
    mode: Literal["kelly", "fixed_pct", "drawdown_stop"]
    kelly_fraction: Optional[float] = Field(0.5, ge=0.0, le=1.0)
    fixed_pct: Optional[float] = Field(None, ge=0.0, le=1.0)

class AccountScalingResponse(BaseModel):
    equity: List[float]
    drawdown: List[float]
    metrics: Dict[str, float]
```

> El simulador de escalado (`AccountScaling`) está implícito en el PRD de producto (§2.3
> "Escalado de cuenta") pero no tenía contrato; se formaliza aquí.

## 3.3 Endpoints internos — `/api/portfolio/*`

| Método | Ruta | Request | Response |
|---|---|---|---|
| `POST` | `/api/portfolio/combine` | `PortfolioCombineRequest` | `PortfolioCombineResponse` |
| `POST` | `/api/portfolio/montecarlo` | `MontecarloSimulationRequest` | `MontecarloSimulationResponse` |
| `POST` | `/api/portfolio/correlation` | `CorrelationMatrixRequest` | `CorrelationMatrixResponse` |
| `POST` | `/api/portfolio/allocation` | `CapitalAllocationRequest` | `CapitalAllocationResponse` |
| `POST` | `/api/portfolio/scaling` | `AccountScalingRequest` | `AccountScalingResponse` |
| `POST` | `/api/portfolio/monitoring/refresh` | `{backtest_ids}` | curvas 3m por estrategia (toca el orquestador) |

> Se usa `POST` (no `GET` como decía el PRD de producto) porque la entrada es una lista de IDs +
> pesos → cuerpo JSON, no query-string.

## 3.4 Errores (envelope del proyecto)

| Código | Cuándo | Mensaje accionable |
|---|---|---|
| `invalid_backtest` | algún `backtest_id` no existe o no tiene `day_results` utilizable | "Estos backtests no se pueden combinar: [ids]. Re-ejecútalos en el Baúl." |
| `weights_sum_invalid` | los pesos no suman ~1.0 | "Los pesos deben sumar 1.0 (actual: X)." |
| `insufficient_strategies` | < 2 IDs para correlación/HRP | "Necesitas al menos 2 estrategias para este análisis." |
| `no_overlap` | calendario unión vacío | "Las estrategias no comparten fechas. Revisa los rangos." |

> En la **API comercial** estos errores se traducen al envelope `{ok,result?,error?}` sin filtrar
> trazas (regla de aislamiento de IP — ver doc 04/05).
