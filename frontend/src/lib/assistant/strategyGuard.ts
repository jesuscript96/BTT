// Deep runtime validation + normalization for strategy drafts produced by
// the LLM via strategy.fill. The generic JSON Schema validator can't enforce
// the recursive condition tree, so this guard checks every node before the
// draft touches the Strategy Builder state — a malformed condition would
// otherwise crash the page render.

import { Comparator, IndicatorType, RiskType, TakeProfitMode, Timeframe } from '@/types/strategy';

const INDICATORS = new Set<string>(Object.values(IndicatorType));
const COMPARATORS = new Set<string>(Object.values(Comparator));
const TIMEFRAMES = new Set<string>(Object.values(Timeframe));
const RISK_TYPES = new Set<string>(Object.values(RiskType));
const TP_MODES = new Set<string>(Object.values(TakeProfitMode));

const PRECONDITION_METRICS = new Set([
    'volume', 'close_vs_open', 'close_vs_high_low', 'close_vs_pm_high', 'close_vs_pm_low',
    'close_vs_high', 'close_vs_low', 'close_vs_vwap', 'close_vs_sma',
    'candle_range_pct', 'candle_range_ratio_gap_1_vs_gap',
]);
const PRECONDITION_OPERATORS = new Set(['>', '<', '> High', '< Low']);

interface GuardError { path: string; message: string }

const indicatorOptions = () => [...INDICATORS].join(' | ');

function normalizeIndicatorName(name: string): string {
    if (!name) return name;
    const LEGACY_MAP: Record<string, string> = {
        "bar high": "High Bar",
        "bar low": "Low Bar",
        "bar close": "Bar Close",
        "bar open": "Bar Open",
        "close price": "Bar Close",
        "open price": "Bar Open",
        "high price": "High Bar",
        "low price": "Low Bar",
        "close": "Bar Close",
        "open": "Bar Open",
        "high": "High Bar",
        "low": "Low Bar",
        "pre-market high": "PM High",
        "pre-market low": "PM Low",
        "premarket high": "PM High",
        "premarket low": "PM Low",
        "pmh": "PM High",
        "pml": "PM Low",
        "yesterday open": "Yesterday Open",
        "yesterday close": "Yesterday Close",
        "yesterday high": "Yesterday High",
        "yesterday low": "Yesterday Low",
        "yesterday volume": "Yesterday Volume",
        "range of time": "Range of Time",
        "time of day": "Range of Time",
        "time": "Range of Time",
        "opening range high": "Opening range +",
        "opening range low": "Opening range -",
        "opening range +": "Opening range +",
        "opening range -": "Opening range -",
        "opening range am +": "Opening range AM +",
        "opening range am -": "Opening range AM -",
        "opening range high (5m)": "Opening range +",
        "opening range low (5m)": "Opening range -",
        "opening range high (15m)": "Opening range +",
        "opening range low (15m)": "Opening range -",
        "accumulated volume": "Accumulated Volume",
        "rvol by bar": "RVOL by bar",
        "rvol": "RVOL by bar",
        "bollinger bands": "Bollinger Bands",
    };
    const key = name.toLowerCase().trim();
    if (LEGACY_MAP[key]) {
        return LEGACY_MAP[key];
    }
    // Case-insensitive fallback check for exact enum values
    for (const val of Object.values(IndicatorType)) {
        if (val.toLowerCase() === key) {
            return val;
        }
    }
    return name;
}

function checkIndicatorConfig(obj: any, path: string, errors: GuardError[]) {
    if (!obj || typeof obj !== 'object') {
        errors.push({ path, message: 'debe ser un objeto IndicatorConfig con al menos { name }' });
        return;
    }
    if (obj.name) {
        obj.name = normalizeIndicatorName(String(obj.name));
        if ((obj.name === "Opening range +" || obj.name === "Opening range -") && !obj.orb_minutes) {
            obj.orb_minutes = 5;
        }
    }
    if (!obj.name || !INDICATORS.has(obj.name)) {
        errors.push({ path: `${path}.name`, message: `indicador "${obj?.name}" no válido; opciones: ${indicatorOptions()}` });
    }
}

function checkConditionNode(node: any, path: string, errors: GuardError[], depth = 0) {
    if (depth > 6) {
        errors.push({ path, message: 'anidamiento de grupos demasiado profundo (máx 6)' });
        return;
    }
    if (!node || typeof node !== 'object') {
        errors.push({ path, message: 'la condición debe ser un objeto' });
        return;
    }
    if (node.type === 'group') {
        if (node.operator !== 'AND' && node.operator !== 'OR') {
            errors.push({ path: `${path}.operator`, message: 'debe ser "AND" u "OR"' });
        }
        if (!Array.isArray(node.conditions)) {
            errors.push({ path: `${path}.conditions`, message: 'debe ser un array de condiciones' });
            return;
        }
        node.conditions.forEach((c: any, i: number) => checkConditionNode(c, `${path}.conditions[${i}]`, errors, depth + 1));
    } else if (node.type === 'indicator_comparison') {
        checkIndicatorConfig(node.source, `${path}.source`, errors);
        if (!node.comparator || !COMPARATORS.has(node.comparator)) {
            errors.push({ path: `${path}.comparator`, message: `comparador "${node.comparator}" no válido; opciones: ${[...COMPARATORS].join(' | ')}` });
        }
        if (node.target === undefined || node.target === null) {
            errors.push({ path: `${path}.target`, message: 'obligatorio: número literal u objeto IndicatorConfig { name, ... }' });
        } else if (typeof node.target !== 'number') {
            checkIndicatorConfig(node.target, `${path}.target`, errors);
        }
        if (node.timeframe !== undefined && !TIMEFRAMES.has(node.timeframe)) {
            errors.push({ path: `${path}.timeframe`, message: `timeframe "${node.timeframe}" no válido; opciones: ${[...TIMEFRAMES].join(' | ')}` });
        }
    } else if (node.type === 'price_level_distance') {
        checkIndicatorConfig(node.source, `${path}.source`, errors);
        checkIndicatorConfig(node.level, `${path}.level`, errors);
        if (node.comparator !== 'DISTANCE_GT' && node.comparator !== 'DISTANCE_LT') {
            errors.push({ path: `${path}.comparator`, message: 'debe ser "DISTANCE_GT" o "DISTANCE_LT"' });
        }
        if (typeof node.value_pct !== 'number') {
            errors.push({ path: `${path}.value_pct`, message: 'obligatorio: número (% de distancia)' });
        }
    } else {
        errors.push({ path: `${path}.type`, message: `tipo "${node?.type}" desconocido; usa "group", "indicator_comparison" o "price_level_distance"` });
    }
}

function checkLogic(logic: any, path: string, errors: GuardError[]) {
    if (!logic || typeof logic !== 'object') {
        errors.push({ path, message: 'debe ser un objeto { timeframe, root_condition }' });
        return;
    }
    if (logic.timeframe !== undefined && !TIMEFRAMES.has(logic.timeframe)) {
        errors.push({ path: `${path}.timeframe`, message: `timeframe "${logic.timeframe}" no válido; opciones: ${[...TIMEFRAMES].join(' | ')}` });
    }
    if (!logic.root_condition) {
        errors.push({ path: `${path}.root_condition`, message: 'obligatorio: grupo raíz { type: "group", operator: "AND"|"OR", conditions: [...] }' });
        return;
    }
    if (logic.root_condition.type !== 'group') {
        errors.push({ path: `${path}.root_condition.type`, message: 'la raíz debe ser un "group" (mete tus condiciones dentro de conditions)' });
        return;
    }
    checkConditionNode(logic.root_condition, `${path}.root_condition`, errors);
}

function checkPreconditions(items: any, path: string, errors: GuardError[]) {
    if (!Array.isArray(items)) {
        errors.push({ path, message: 'debe ser un array' });
        return;
    }
    items.forEach((p: any, i: number) => {
        if (!p || typeof p !== 'object') {
            errors.push({ path: `${path}[${i}]`, message: 'cada precondición debe ser un objeto' });
            return;
        }
        if (p.day !== 'gap_day' && p.day !== 'gap_1_day') {
            errors.push({ path: `${path}[${i}].day`, message: 'debe ser "gap_day" o "gap_1_day"' });
        }
        if (!PRECONDITION_METRICS.has(p.metric)) {
            errors.push({ path: `${path}[${i}].metric`, message: `métrica "${p.metric}" no válida; opciones: ${[...PRECONDITION_METRICS].join(' | ')}` });
        }
        if (!PRECONDITION_OPERATORS.has(p.operator)) {
            errors.push({ path: `${path}[${i}].operator`, message: `operador "${p.operator}" no válido; opciones: ${[...PRECONDITION_OPERATORS].join(' | ')}` });
        }
    });
}

/**
 * Validates a strategy.fill payload in depth and normalizes it in place
 * (default timeframes, generated precondition ids). Returns an error string
 * for the LLM to self-repair, or null if the payload is safe to apply.
 */
export function guardStrategyDraft(args: Record<string, any>): string | null {
    const errors: GuardError[] = [];

    const entry = args.entryLogic ?? args.entry_logic;
    if (entry !== undefined) {
        if (entry && typeof entry === 'object' && entry.timeframe === undefined) entry.timeframe = '1m';
        checkLogic(entry, 'entryLogic', errors);
    }
    const exit = args.exitLogic ?? args.exit_logic;
    if (exit !== undefined) {
        if (exit && typeof exit === 'object' && exit.timeframe === undefined) exit.timeframe = '1m';
        checkLogic(exit, 'exitLogic', errors);
    }

    const preconds = args.postgapPreconditions ?? args.postgap_preconditions;
    if (preconds !== undefined) {
        checkPreconditions(preconds, 'postgapPreconditions', errors);
        if (Array.isArray(preconds)) {
            preconds.forEach((p: any, i: number) => {
                if (p && typeof p === 'object' && !p.id) p.id = `pre_${Date.now()}_${i}`;
            });
        }
    }

    const risk = args.riskManagement ?? args.risk_management;
    if (risk !== undefined) {
        if (typeof risk !== 'object' || risk === null) {
            errors.push({ path: 'riskManagement', message: 'debe ser un objeto' });
        } else {
            const riskOpts = [...RISK_TYPES].join(' | ');
            if (risk.hard_stop?.type !== undefined && !RISK_TYPES.has(risk.hard_stop.type)) {
                errors.push({ path: 'riskManagement.hard_stop.type', message: `tipo "${risk.hard_stop.type}" no válido; opciones: ${riskOpts}` });
            }
            if (risk.take_profit?.type !== undefined && !RISK_TYPES.has(risk.take_profit.type)) {
                errors.push({ path: 'riskManagement.take_profit.type', message: `tipo "${risk.take_profit.type}" no válido; opciones: ${riskOpts}` });
            }
            if (risk.take_profit_mode !== undefined && !TP_MODES.has(risk.take_profit_mode)) {
                errors.push({ path: 'riskManagement.take_profit_mode', message: `modo "${risk.take_profit_mode}" no válido; opciones: ${[...TP_MODES].join(' | ')}` });
            }
        }
    }

    if (errors.length === 0) return null;
    return 'Borrador rechazado, corrige y reintenta — ' + errors.map(e => `${e.path}: ${e.message}`).join('; ');
}
