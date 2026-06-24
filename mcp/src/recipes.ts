/** Ready-made strategy + dashboard recipes for scaffolding. */

export interface Recipe {
  id: string;
  title: string;
  tags: string[];
  description: string;
  strategy: Record<string, unknown>;
  components: string[];
}

export const RECIPES: Recipe[] = [
  {
    id: "vwap-fade-short",
    title: "VWAP fade (short)",
    tags: ["short", "vwap", "mean-reversion"],
    description: "Entra corto cuando el precio cruza por debajo del VWAP; stop 3%.",
    strategy: {
      name: "VWAP fade short",
      bias: "short",
      apply_day: "gap_day",
      entry_logic: {
        timeframe: "1m",
        root_condition: {
          type: "group",
          operator: "AND",
          conditions: [
            {
              type: "indicator_comparison",
              source: { name: "Bar Close" },
              comparator: "CROSSES_BELOW",
              target: { name: "VWAP" },
            },
          ],
        },
      },
      risk_management: {
        use_hard_stop: true,
        hard_stop: { type: "Percentage", value: 3.0 },
        use_take_profit: true,
        take_profit: { type: "Percentage", value: 6.0 },
      },
    },
    components: ["equity-chart", "metrics-grid", "trades-table"],
  },
  {
    id: "orb-breakout-long",
    title: "Opening-range breakout (long)",
    tags: ["long", "breakout", "momentum"],
    description: "Entra largo al romper el máximo del rango de apertura.",
    strategy: {
      name: "ORB breakout long",
      bias: "long",
      apply_day: "gap_day",
      entry_logic: {
        timeframe: "1m",
        root_condition: {
          type: "group",
          operator: "AND",
          conditions: [
            {
              type: "indicator_comparison",
              source: { name: "Bar Close" },
              comparator: "CROSSES_ABOVE",
              target: { name: "Opening Range +", orb_minutes: 5 },
            },
          ],
        },
      },
      risk_management: {
        use_hard_stop: true,
        hard_stop: { type: "Percentage", value: 2.0 },
        use_take_profit: true,
        take_profit: { type: "Percentage", value: 4.0 },
      },
    },
    components: ["equity-chart", "drawdown-chart", "metrics-grid"],
  },
];

export function listRecipes(tag?: string): Recipe[] {
  if (!tag) return RECIPES;
  return RECIPES.filter((r) => r.tags.includes(tag));
}

export function getRecipe(id: string): Recipe | undefined {
  return RECIPES.find((r) => r.id === id);
}
