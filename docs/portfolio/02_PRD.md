# 02 — PRD: qué, para quién, alcance, glosario

## 2.1 Usuarios

* **Trader profesional / gestor de cartera (Jaume):** necesita saber qué combinación de pesos
  maximiza PnL reduciendo correlación, y simular riesgo de ruina (Montecarlo) antes de desplegar
  capital.
* **Trader principiante:** requiere explicaciones claras de VaR/CVaR, Spearman y Kelly para evitar
  riesgos catastróficos. → **Requisito crítico**: tooltips/banners didácticos (§2.5) literales.

## 2.2 Jobs-to-be-done

1. **Combinar** backtests del Baúl con ticks y ver la curva de equity + drawdown conjunta,
   agregada por días de calendario real.
2. **Estudiar el riesgo** con modelos analíticos (Montecarlo, Pearson, Spearman, VaR/CVaR).
3. **Optimizar pesos** y escalado (Kelly, Líderes, HRP) y exportar la distribución ("Guardar
   pesos") al Cuadro de Riesgo principal.
4. **Monitorizar** la evolución conjunta de los últimos 3 meses solapando curvas. *(Journal → F2.)*

## 2.3 Alcance del MVP (lo que SÍ se construye)

**Vista principal "Portfolio":**
* Selector de backtests del Baúl con ticks (tabla: Nombre, Setup, Win Rate, Total PnL, Sharpe).
* Botón "Construir portfolio" → curva de equity + drawdown agregada (pesos iguales por defecto).
* **Cuadro de Riesgo**: métricas tradicionales (Sharpe, MaxDD, PnL %, etc.) + almacén de los
  pesos y métricas enviados desde las subpáginas ("Agregar a cuadro de riesgo").

**Subpágina "Análisis de Riesgo":**
* **Montecarlo:** shuffling de retornos **diarios** agregados (X simulaciones) → percentiles
  (P5/P25/P50/P75/P95), VaR y CVaR al 95% y 99% (en % y USD), probabilidad de ruina.
* **Matriz de correlación:** heatmap interactivo Pearson (lineal) y Spearman (no lineal). Días sin
  operación = 0%.
* **Escalado de cuenta:** Kelly (a nivel de portfolio, fracción configurable), % fijo por
  operación, y escalado según drawdown. Capital por defecto **$10,000** (configurable).
* **Asignación de capital:**
  * *Líderes:* rebalanceo dinámico con ventana deslizante configurable (**default 15 días**),
    más peso a la estrategia de mejor rendimiento (Sharpe/PnL). **Cero lookahead.**
  * *HRP:* pesos estáticos por clustering jerárquico (**scipy in-house**, no `riskfolio-lib`).

**Subpágina "Seguimiento":**
* *Seguimiento de estrategias:* solapamiento de curvas individuales de los últimos 3 meses,
  ejecución incremental por el backend (botón "Actualizar"). Tarjetas de equity individuales en
  grid 2-col debajo.

## 2.4 Fase 2 (se dibuja la pestaña con estado "Próximamente")

* **Seguimiento por Journal** (curva de equity real desde PnLs del Journal) — **diferido**: el
  Journal aún no existe (ver `PRD_EJEMPLO_JOURNAL.md`). UI muestra estado "Soon" con guía.
* Modelos de asignación **Markov** y **Fix ratio**.
* Comparativa normalizada **Journal vs. Simulación Ideal**.

## 2.5 Glosario de dominio y explicaciones didácticas (REQUISITO CRÍTICO)

> Estos textos van **literales** en la UI (tooltips, banners, secciones de ayuda con ejemplos).
> Implementarlos como constantes reutilizables y servirlos también vía `docs://` del MCP.

### A. Value at Risk (VaR) 95% y 99%
* **Didáctico:** el VaR mide la pérdida máxima esperable en un solo día bajo condiciones normales,
  para un nivel de confianza dado.
* **Ejemplo:** *"Un VaR diario al 95% de -$250 USD significa que hay un 95% de probabilidad de que
  mañana tu cartera no pierda más de $250. O lo que es lo mismo: solo 1 de cada 20 días sufrirás una
  pérdida mayor."*
* **Fórmula:** $\text{VaR}_{\alpha}(X) = -\inf\{x\in\mathbb{R}: P(X\le x) > 1-\alpha\}$, con $X$ =
  retornos diarios agregados y $\alpha\in\{0.95, 0.99\}$.

### B. Conditional VaR (CVaR / Expected Shortfall)
* **Didáctico:** responde *"si superamos la pérdida del VaR, ¿cuál será la pérdida media de ese peor
  escenario?"* Es la media de la cola del peor 5% (o 1%) de los días.
* **Ejemplo:** *"Si tu VaR 95% es -$250 pero tu CVaR 95% es -$450, significa que si caes en ese 5%
  de peores días, la pérdida media esperada es de $450."*
* **Fórmula:** $\text{CVaR}_{\alpha}(X) = \frac{1}{1-\alpha}\int_{\alpha}^{1}\text{VaR}_u(X)\,du$.

### C. Criterio de Kelly
* **Didáctico:** Kelly calcula el % óptimo de la cuenta a arriesgar según win rate y payoff ratio del
  portfolio histórico, para maximizar crecimiento a largo plazo sin quebrar.
* **Fractional Kelly:** como el Kelly completo es muy volátil, se aplica una fracción (medio = 0.5,
  cuarto = 0.25) para reducir el riesgo.
* **Fórmula:** $f^* = \frac{p\cdot b - (1-p)}{b} = p - \frac{1-p}{b}$, con $f^*$ = fracción óptima,
  $p$ = win rate (decimal), $b$ = payoff ratio (ganancia media / |pérdida media|).

### D. Correlación de Pearson vs. Spearman
* **Pearson:** relación **lineal** entre retornos. Suben proporcionalmente los mismos días → ~1.0
  (rojo); se mueven opuestos → -1.0 (verde).
* **Spearman:** relación **no lineal** (monótona) por rangos. Detecta si dos estrategias ganan/pierden
  en los mismos momentos aunque la magnitud en USD no sea proporcional.
* **Ejemplo:** *"Spearman 0.85 entre A y B → operan los mismos patrones, no diversifican. Si una tiene
  -0.40 con el resto, actúa como cobertura y suaviza tu curva global."*

### E. Hierarchical Risk Parity (HRP)
* **Didáctico:** método de López de Prado que usa clustering jerárquico sobre la matriz de covarianza.
  A diferencia de Markowitz, **no invierte** la matriz de covarianza → robusto frente al ruido
  histórico y evita concentrar todo en una estrategia sobreoptimizada. Distribuye pesos según el
  perfil de riesgo correlacionado de cada grupo.
* **Nota de implementación (interna, no UI):** en Edgecute HRP se calcula **in-house con scipy**
  (`linkage` + recursive bisection), sin `riskfolio-lib`.
