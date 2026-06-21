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
      if (!cond.source?.name) {
        errors.push(`${label}: falta el indicador "source" en Distancia %`);
      }
      if (!cond.level?.name) {
        errors.push(`${label}: falta el indicador "from" en Distancia %`);
      }
      if (!cond.comparator) {
        errors.push(`${label}: falta el comparador en Distancia %`);
      }
      if (cond.value_pct === undefined || cond.value_pct === null || isNaN(cond.value_pct)) {
        errors.push(`${label}: falta el valor % en Distancia %`);
      }
    } else if (cond.type === "indicator_comparison") {
      if (!cond.source?.name) {
        errors.push(`${label}: falta la variable de entrada`);
      }
      if (!cond.comparator) {
        errors.push(`${label}: falta la relación/comparador`);
      }
      if (cond.target === undefined || cond.target === null || (cond.target as any) === "") {
        errors.push(`${label}: falta la variable de cruce o valor fijo`);
      } else if (typeof cond.target === "object") {
        if (!cond.target.name) {
          errors.push(`${label}: falta la variable de cruce`);
        }
      } else if (typeof cond.target === "number") {
        if (isNaN(cond.target)) {
          errors.push(`${label}: el valor fijo no es un número válido`);
        }
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
