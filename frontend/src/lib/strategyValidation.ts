import type { ConditionGroup, AnyCondition } from "@/types/strategy";

type Node = ConditionGroup | AnyCondition;

export function validateConditions(
  conditions: Node[] | undefined,
  pathPrefix = "",
): string[] {
  const errors: string[] = [];
  if (!conditions) return errors;
  conditions.forEach((cond, i) => {
    const label = `${pathPrefix}Condición ${i + 1}`;
    if (cond.type === "price_level_distance") {
      if (!cond.level?.name) {
        errors.push(`${label}: falta el indicador "from" en Distancia %`);
      }
      if (!cond.comparator) {
        errors.push(`${label}: falta el comparador en Distancia %`);
      }
      if (cond.value_pct === undefined || cond.value_pct === null) {
        errors.push(`${label}: falta el valor % en Distancia %`);
      }
    }
    if (cond.type === "group" && cond.conditions) {
      errors.push(...validateConditions(cond.conditions, `${label} > `));
    }
  });
  return errors;
}

export function validateStrategyLogic(
  entryLogic?: { root_condition?: ConditionGroup } | null,
  exitLogic?: { root_condition?: ConditionGroup } | null,
): string[] {
  const entry = validateConditions(
    entryLogic?.root_condition?.conditions,
    "Entry > ",
  );
  const exit = validateConditions(
    exitLogic?.root_condition?.conditions,
    "Exit > ",
  );
  return [...entry, ...exit];
}
