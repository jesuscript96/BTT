// JSON Schemas for the assistant's tools. These are the single source of
// truth the LLM sees via function calling — every field carries a Spanish
// description with units, ranges and semantics so the model can fill the
// forms "a la perfección". Keep them in sync with the UI components:
//   BacktestPanel.tsx, InlineStrategyBuilder.tsx, InlineDatasetBuilder.tsx
// and with types/strategy.ts enums.

import { Comparator, IndicatorType, Timeframe } from '@/types/strategy';
import type { JSONSchema } from './types';

const DATE_PATTERN = '^\\d{4}-\\d{2}-\\d{2}$';
const TIME_PATTERN = '^\\d{2}:\\d{2}$';

// ── Backtest config form (BacktestPanel) ─────────────────────────

export const BacktestParamsSchema: JSONSchema = {
    type: 'object',
    description: 'Parámetros del formulario de configuración del backtest. Todos opcionales: solo se aplican los enviados.',
    properties: {
        initCash: { type: 'number', minimum: 0, description: 'Capital inicial en USD (ej. 50000).' },
        riskR: { type: 'number', minimum: 0, description: 'Riesgo por operación (1R). En USD si riskType=FIXED, en % del capital si riskType=PERCENT.' },
        riskType: { type: 'string', enum: ['FIXED', 'PERCENT', 'FIXED_RATIO'], description: 'Modo de dimensionado del riesgo. FIXED=importe fijo en USD, PERCENT=% del capital, FIXED_RATIO=método fixed ratio (usa fixedRatioDelta).' },
        fixedRatioDelta: { type: 'number', minimum: 0, description: 'Delta del método FIXED_RATIO en USD (solo aplica con riskType=FIXED_RATIO).' },
        fees: { type: 'number', minimum: 0, description: 'Comisiones por operación. En % si feeType=PERCENT (ej. 0.05), en USD si feeType=FLAT.' },
        feeType: { type: 'string', enum: ['PERCENT', 'FLAT'], description: 'Tipo de comisión.' },
        slippage: { type: 'number', minimum: 0, description: 'Slippage estimado en % (ej. 0.02).' },
        startDate: { type: 'string', pattern: DATE_PATTERN, description: 'Fecha inicial del backtest, formato YYYY-MM-DD. Rango de datos disponible: 2006-01-01 a hoy.' },
        endDate: { type: 'string', pattern: DATE_PATTERN, description: 'Fecha final del backtest, formato YYYY-MM-DD.' },
        marketSessions: {
            type: 'array',
            items: { type: 'string', enum: ['pre', 'rth', 'post', 'custom'] },
            description: 'Sesiones de mercado a operar: pre=premarket (04:00-09:30), rth=horario regular (09:30-16:00), post=after hours (16:00-20:00), custom=ventana personalizada (requiere customStartTime/customEndTime).',
        },
        customStartTime: { type: 'string', pattern: TIME_PATTERN, description: 'Inicio de la sesión custom, formato HH:MM (solo si marketSessions incluye "custom").' },
        customEndTime: { type: 'string', pattern: TIME_PATTERN, description: 'Fin de la sesión custom, formato HH:MM.' },
        locatesCost: { type: 'number', minimum: 0, description: 'Coste de locates por operación en USD (para shorts). 0 desactiva el cálculo.' },
        monthlyExpenses: { type: 'number', minimum: 0, description: 'Gastos fijos mensuales en USD a descontar de la curva. 0 desactiva.' },
        datasetId: { type: 'string', description: 'ID exacto del dataset a usar (preferible; consulta el catálogo en el contexto backtest.catalog).' },
        datasetName: { type: 'string', description: 'Nombre (o fragmento) del dataset si no conoces el ID. Si hay varios candidatos, pregunta al usuario antes.' },
        strategyId: { type: 'string', description: 'ID exacto de la estrategia guardada a usar.' },
        strategyName: { type: 'string', description: 'Nombre (o fragmento) de la estrategia si no conoces el ID.' },
    },
    additionalProperties: false,
};

// ── Strategy builder (InlineStrategyBuilder) ─────────────────────

const indicatorEnum = Object.values(IndicatorType);
const comparatorEnum = Object.values(Comparator);
const timeframeEnum = Object.values(Timeframe);

const IndicatorConfigSchema: JSONSchema = {
    type: 'object',
    description: 'Configuración de un indicador o variable de precio.',
    properties: {
        name: { type: 'string', enum: indicatorEnum, description: 'Nombre del indicador o variable de precio.' },
        period: { type: 'number', description: 'Periodo principal (SMA/EMA/ATR/Donchian...).' },
        stdDev: { type: 'number', description: 'Desviaciones estándar (Bollinger Bands).' },
        offset: { type: 'number', description: 'Offset en % aplicado al valor (ej. 1 = +1%). Puede ser negativo.' },
        consecutive_count: { type: 'number', description: 'Nº de velas consecutivas (patrones Consecutive...).' },
        days_lookback: { type: 'number', description: 'Días hacia atrás (High/Low of last X days, Previous max/min).' },
        time_hour: { type: 'number', description: 'Hora (0-23) para condiciones temporales.' },
        time_minute: { type: 'number', description: 'Minuto (0-59) para condiciones temporales.' },
        time_condition: { type: 'string', enum: ['BEFORE', 'AFTER'], description: 'Antes o después de la hora indicada.' },
        orb_minutes: { type: 'number', description: 'Minutos del opening range (Opening range +/-).' },
        range_minutes: { type: 'number', description: 'Minutos de la ventana (Range of Time).' },
        elapsed_minutes: { type: 'number', description: 'Minutos transcurridos (Elapsed time from last High).' },
        ap_session: { type: 'string', enum: ['ap.PM', 'ap.RTH', 'ap.AM'], description: 'Sesión de referencia para variables PM/RTH/AM.' },
    },
};

const ComparisonConditionSchema: JSONSchema = {
    type: 'object',
    description: 'Condición que compara un indicador contra otro indicador o un número.',
    properties: {
        type: { type: 'string', enum: ['indicator_comparison'] },
        source: IndicatorConfigSchema,
        comparator: { type: 'string', enum: comparatorEnum, description: 'Operador de comparación. CROSSES_ABOVE/BELOW = cruce; DISTANCE_GT/LT = distancia en %.' },
        target: { description: 'Indicador objetivo (objeto como source) o valor numérico literal.' },
        timeframe: { type: 'string', enum: timeframeEnum, description: 'Timeframe de evaluación de esta condición.' },
    },
    required: ['type', 'source', 'comparator', 'target'],
};

const ConditionGroupSchema: JSONSchema = {
    type: 'object',
    description: 'Grupo lógico de condiciones (anidable).',
    properties: {
        type: { type: 'string', enum: ['group'] },
        operator: { type: 'string', enum: ['AND', 'OR'] },
        conditions: {
            type: 'array',
            description: 'Lista de condiciones o sub-grupos anidados.',
            items: {
                type: 'object',
                description:
                    'Condición: { "type":"indicator_comparison", "source":{"name":"<indicador>"}, "comparator":"<comparador>", "target": <número> | {"name":"<indicador>"}, "timeframe?":"5m" } ' +
                    'o sub-grupo { "type":"group", "operator":"AND"|"OR", "conditions":[...] }. ' +
                    'source y target son SIEMPRE objetos con "name" (salvo target numérico literal). Ejemplo: cruce bajo VWAP = { "type":"indicator_comparison", "source":{"name":"Bar Close"}, "comparator":"CROSSES_BELOW", "target":{"name":"VWAP"} }.',
            },
        },
    },
    required: ['type', 'operator', 'conditions'],
};

export const StrategyDraftSchema: JSONSchema = {
    type: 'object',
    description: 'Borrador completo o parcial de una estrategia para el Strategy Builder. Solo se aplican los campos enviados.',
    properties: {
        name: { type: 'string', description: 'Nombre de la estrategia.' },
        bias: { type: 'string', enum: ['long', 'short'], description: 'Dirección de la estrategia.' },
        applyDay: { type: 'string', enum: ['gap_day', 'gap_1_day', 'gap_2_day'], description: 'Día sobre el que opera: el día del gap, el siguiente (+1) o dos después (+2).' },
        postgapPreconditions: {
            type: 'array',
            description:
                'Precondiciones sobre días anteriores (solo si applyDay no es gap_day). Cada una: ' +
                '{ "day": "gap_day"|"gap_1_day", "metric": "volume"|"close_vs_open"|"close_vs_high_low"|"close_vs_pm_high"|"close_vs_pm_low"|"close_vs_high"|"close_vs_low"|"close_vs_vwap"|"close_vs_sma"|"candle_range_pct"|"candle_range_ratio_gap_1_vs_gap", ' +
                '"operator": ">"|"<"|"> High"|"< Low", "value?": número, "sma_period?": número }.',
            items: { type: 'object' },
        },
        entryLogic: {
            type: 'object',
            description: 'Lógica de entrada: { timeframe, root_condition (group), entry_time_windows?: [{from_time:"HH:MM", to_time:"HH:MM"}] }.',
            properties: {
                timeframe: { type: 'string', enum: timeframeEnum },
                root_condition: ConditionGroupSchema,
                entry_time_windows: { type: 'array', items: { type: 'object' } },
            },
        },
        exitLogic: {
            type: 'object',
            description: 'Lógica de salida: { timeframe, root_condition (group) }.',
            properties: {
                timeframe: { type: 'string', enum: timeframeEnum },
                root_condition: ConditionGroupSchema,
            },
        },
        riskManagement: {
            type: 'object',
            description: 'Gestión de riesgo: stop loss { type: "Fixed Amount"|"Percentage"|"ATR Multiplier"|"Market Structure (HOD/LOD)", value, offset_pct? }, take profit { mode: "Full"|"Partial", distance_pct, partials? }, trailing stop { active, buffer_pct }.',
        },
    },
    additionalProperties: false,
};

export { ComparisonConditionSchema, ConditionGroupSchema, IndicatorConfigSchema };

// ── Dataset builder (InlineDatasetBuilder) ───────────────────────

const DATASET_PARAM_KEYS = [
    'rth_close', 'pm_open', 'pmh_gap_pct_min', 'pmh_gap_pct_max', 'pm_volume',
    'gap_pct_min', 'gap_pct_max', 'rth_volume', 'rth_range_pct',
];

export const DatasetDraftSchema: JSONSchema = {
    type: 'object',
    description:
        'Borrador de dataset (universo de pares ticker-día). Filtros por sección de día: gap_day (día del gap), gap_plus_1_day, gap_plus_2_day. ' +
        `Claves de filtro disponibles: ${DATASET_PARAM_KEYS.join(', ')}. ` +
        'gap_pct_min/max = % de gap (mín. 10), pm_volume/rth_volume en millones, rth_close = precio mínimo de apertura en $, rth_range_pct = rango de la vela diaria en % (admite negativo).',
    properties: {
        name: { type: 'string', description: 'Nombre del dataset.' },
        dateFrom: { type: 'string', pattern: DATE_PATTERN, description: 'Fecha inicial (mínimo 2006-01-01).' },
        dateTo: { type: 'string', pattern: DATE_PATTERN, description: 'Fecha final (máximo hoy).' },
        values: {
            type: 'object',
            description: 'Valores por sección: { gap_day: { gap_pct_min: "20" }, gap_plus_1_day: {...}, gap_plus_2_day: {...} }. Los valores son strings numéricos.',
            properties: {
                gap_day: { type: 'object' },
                gap_plus_1_day: { type: 'object' },
                gap_plus_2_day: { type: 'object' },
            },
        },
        includedConditions: {
            type: 'array',
            description: 'Condiciones marcadas como incluidas: [{ section, paramKey, label, value, unit }]. Deben corresponderse con values.',
            items: { type: 'object' },
        },
    },
    additionalProperties: false,
};

// ── Misc shared schemas ──────────────────────────────────────────

export const EmptySchema: JSONSchema = { type: 'object', properties: {}, additionalProperties: false };

export const NavigateSchema: JSONSchema = {
    type: 'object',
    description: 'Navega a una página de la aplicación.',
    properties: {
        to: {
            type: 'string',
            enum: ['/', '/backtester', '/database', '/tutorials'],
            description: 'Ruta destino: "/" = Ticker Analysis, "/backtester" = Backtester (formulario, builders y resultados), "/database" = Trunk (estrategias/datasets/backtests guardados), "/tutorials" = tutoriales.',
        },
    },
    required: ['to'],
    additionalProperties: false,
};

export const SetModeSchema: JSONSchema = {
    type: 'object',
    description: 'Cambia el panel visible del Backtester.',
    properties: {
        mode: {
            type: 'string',
            enum: ['config', 'builder', 'dataset'],
            description: 'config = formulario del backtest, builder = constructor de estrategias, dataset = constructor de datasets.',
        },
    },
    required: ['mode'],
    additionalProperties: false,
};

export const TrunkDeleteSchema: JSONSchema = {
    type: 'object',
    description: 'Elimina permanentemente una estrategia o un dataset guardado del Trunk.',
    properties: {
        type: { type: 'string', enum: ['strategy', 'dataset'], description: 'Tipo de elemento a borrar.' },
        id: { type: 'string', description: 'ID exacto (preferido; consulta el contexto trunk.page).' },
        name: { type: 'string', description: 'Nombre exacto o fragmento, solo si no conoces el ID. Con varias coincidencias devolverá error.' },
    },
    required: ['type'],
    additionalProperties: false,
};

export const TrunkOpenStrategySchema: JSONSchema = {
    type: 'object',
    description: 'Abre una estrategia guardada en el Backtester (precarga su selección).',
    properties: {
        id: { type: 'string', description: 'ID exacto de la estrategia (preferido).' },
        name: { type: 'string', description: 'Nombre o fragmento si no conoces el ID.' },
    },
    additionalProperties: false,
};

export const TickerLoadSchema: JSONSchema = {
    type: 'object',
    description: 'Carga un ticker en la página de Ticker Analysis.',
    properties: {
        ticker: { type: 'string', description: 'Símbolo del ticker en mayúsculas, ej. "AAPL".' },
    },
    required: ['ticker'],
    additionalProperties: false,
};
