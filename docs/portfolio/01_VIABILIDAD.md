# 01 — Viabilidad (reality-check + veredicto)

## 1.1 Reality-check: lo que el PRD asumía vs. el código real

> Auditoría hecha sobre el repo (rama base `portfolio`). El PRD de producto contenía supuestos
> que NO se sostienen en el código. Esto cambia el alcance del MVP.

| Supuesto del PRD de producto | Realidad verificada | Decisión |
|---|---|---|
| `montecarlo_service.py` se reutiliza tal cual | Baraja **PnL de trades** (`run_montecarlo(pnls,...)`), no retornos diarios de cartera | Montecarlo de portfolio **nuevo** sobre retornos diarios agregados. Se reusa el *estilo* (percentiles, ruin). |
| El servicio nuevo se llama `portfolio_service.py` | Ya existe `portfolio_sim.py` (simulador del **motor**). Confusión garantizada | Renombrar a **`portfolio_analytics_service.py`**. |
| Existe un Journal de operaciones reales | **No existe** (ni tabla `journal_*` ni CRUD). Hay un PRD aparte: `docs/manual-prd/PRD_EJEMPLO_JOURNAL.md` | **Subpágina "Seguimiento por Journal" DIFERIDA a Fase 2** ("Próximamente"). El MVP no depende del Journal. |
| HRP con `riskfolio-lib` | **No instalado**; arrastra `cvxpy` (riesgo de build en Railway). Pero **`scipy>=1.12.0` SÍ está** en `requirements.txt:14` | **Decisión CTO: HRP propio** con `scipy.cluster.hierarchy` (receta de López de Prado, ~80 líneas). Cero dependencias nuevas. |
| `backtest_results` tiene curva diaria limpia | Tiene `results_json.day_results` (PnL por ticker-día) y `equity_curves` por ticker-día; **sin `user_id`** | La DuckDB es **por-usuario** (`get_user_db_connection` + `gcs_sync`). El portfolio lee el Baúl del usuario logueado. Hay que **derivar** la serie diaria de retornos desde `day_results`. |

## 1.2 Restricciones y coste

* **Volumen de datos:** los retornos diarios combinados se derivan de `day_results` ya calculados
  en el Baúl (`backtest_results`). Montecarlo y correlación son cálculos en memoria sobre arrays
  NumPy. Coste: **O(N·M)** (N simulaciones, M días). Con N=1000 y M≤~750 (3 años) es < 200 ms.
* **HRP (scipy):** clustering jerárquico + recursive bisection sobre la matriz de covarianza.
  Estático, una vez por configuración de pesos. Latencia esperada **< 300 ms**.
* **Seguimiento 3 meses:** re-ejecuta cada estrategia sobre los últimos 3 meses vía el
  orquestador existente. Acotado a 3 meses → latencia esperada **< 1.5 s** por estrategia
  (paralelizable). Es el único endpoint que toca el motor pesado.

## 1.3 Riesgos y mitigaciones

| Riesgo | Impacto | Mitigación |
|---|---|---|
| Fechas asíncronas entre estrategias | Error al sumar curvas | Alineación por calendario real; día sin trades de una estrategia → retorno **0%** en la agregación. Test explícito en Fase 1. |
| Overfitting en HRP/Kelly | Pérdida de capital del trader | Banners didácticos prominentes (§2.5) advirtiendo que correlación y Kelly histórico pueden no sostenerse por cambio de régimen. |
| Lookahead en asignación/escalado | Resultados irreales | **Cero lookahead**: ventanas deslizantes solo con datos pasados. Tests anti-lookahead obligatorios. |
| Colisión `portfolio_sim.py` ↔ servicio nuevo | Imports erróneos, bugs silenciosos | Nombre `portfolio_analytics_service.py` + nota en cabecera de ambos ficheros. |
| `results_json` heterogéneo entre backtests viejos | Curva diaria ausente | Validación defensiva: si un backtest no tiene `day_results` utilizable → error accionable `invalid_backtest` listando los IDs problemáticos. |
| HRP con < 2 estrategias o covarianza singular | Excepción numérica | Fallback a pesos iguales + warning; test de borde. |

## 1.4 Veredicto

**VIABLE para MVP** con dos recortes ya decididos:
1. **Journal → Fase 2** (subpágina "Próximamente"). El resto del PRD se construye completo.
2. **HRP in-house con scipy** (sin `riskfolio-lib`).

El grueso es **analítica pura en memoria** sobre datos ya persistidos; el único punto caro
(seguimiento 3m) reusa el orquestador existente y está acotado. La API comercial y el MCP
**reusan** el núcleo sin rearquitectura (el patrón modular ya existe).
