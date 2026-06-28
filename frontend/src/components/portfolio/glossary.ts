/**
 * Didactic copy for the Portfolio module — LITERAL texts from the PRD (§2.5).
 * Rendered in tooltips and help banners. Keep in sync with docs/portfolio/02 §2.5
 * and the MCP `docs://portfolio-glossary` resource.
 */
export const GLOSSARY = {
  var: {
    title: "Value at Risk (VaR)",
    body:
      "El VaR mide la pérdida máxima esperable en un solo día bajo condiciones normales de mercado, " +
      "para un nivel de confianza específico.",
    example:
      "Un VaR diario al 95% de -$250 significa que hay un 95% de probabilidad de que mañana tu cartera " +
      "no pierda más de $250. O lo que es lo mismo: solo 1 de cada 20 días sufrirás una pérdida mayor.",
  },
  cvar: {
    title: "Conditional VaR (Expected Shortfall)",
    body:
      "El CVaR responde: si las cosas van muy mal y superamos la pérdida del VaR, ¿cuál será la pérdida " +
      "media de ese peor escenario? Es la media de las pérdidas en la cola del peor 5% (o 1%) de los días.",
    example:
      "Si tu VaR 95% es -$250 pero tu CVaR 95% es -$450, significa que si caes en ese 5% de los peores días, " +
      "la pérdida promedio diaria que debes esperar es de $450.",
  },
  kelly: {
    title: "Criterio de Kelly",
    body:
      "Kelly calcula el porcentaje óptimo de tu cuenta que debes arriesgar según el win rate y el payoff ratio " +
      "de tu portfolio histórico para maximizar el crecimiento a largo plazo sin caer en bancarrota. " +
      "Como el Kelly completo es muy volátil, se aplica una fracción (medio = 0.5, cuarto = 0.25) para reducir el riesgo.",
    example: "f* = p − (1 − p) / b   ·   b = ganancia media / |pérdida media|",
  },
  correlation: {
    title: "Pearson vs Spearman",
    body:
      "Pearson mide la relación LINEAL entre los retornos de dos estrategias (suben proporcional los mismos días → " +
      "cercano a +1, rojo; opuestos → -1, verde). Spearman mide la relación NO lineal (monótona) por rangos: detecta " +
      "si dos estrategias ganan y pierden en los mismos momentos aunque la magnitud en USD no sea proporcional.",
    example:
      "Spearman 0.85 entre A y B → operan casi los mismos patrones, no diversifican. Si una tiene -0.40 con el resto, " +
      "actúa como cobertura y suaviza tu curva de equity global.",
  },
  hrp: {
    title: "Hierarchical Risk Parity (HRP)",
    body:
      "Método de Marcos López de Prado que usa clustering jerárquico sobre la matriz de covarianza de tus estrategias. " +
      "A diferencia de Markowitz, no necesita invertir la matriz de covarianza, lo que lo hace muy robusto contra el ruido " +
      "histórico y evita concentrar todo el capital en una sola estrategia sobreoptimizada.",
    example: "",
  },
  overfitting: {
    title: "Aviso de sobreajuste",
    body:
      "El análisis de correlación y el Kelly histórico pueden no mantenerse en el futuro debido a cambios en el régimen " +
      "del mercado. Úsalos como guía, no como certeza.",
    example: "",
  },
} as const;

export type GlossaryKey = keyof typeof GLOSSARY;
