import React from 'react';
import {
    ConditionGroup,
    AnyCondition,
    IndicatorType,
    Comparator,
    IndicatorConfig,
    Timeframe
} from '@/types/strategy';
import { Plus, Trash2, GitBranch, Clock } from 'lucide-react';
import { getAllowedTargets, isOnlyTarget } from '@/lib/indicatorValidation';

// ----------------------------------------------------------------------
// Constants & Helpers
// ----------------------------------------------------------------------

const isTriangle = (name: string) =>
    name === IndicatorType.TRIANGLE_ASCENDING ||
    name === IndicatorType.TRIANGLE_DESCENDING ||
    name === IndicatorType.TRIANGLE_SYMMETRIC;

const isVolumeIndicator = (name?: string): boolean => {
    if (!name) return false;
    return (
        name === IndicatorType.VOLUME ||
        name === IndicatorType.ACCUMULATED_VOLUME ||
        name === IndicatorType.YESTERDAY_VOLUME
    );
};

const ALLOWED_CROSSES_INDICATORS: IndicatorType[] = [
    IndicatorType.BAR_CLOSE,
    IndicatorType.BAR_OPEN,
    IndicatorType.HIGH_BAR,
    IndicatorType.LOW_BAR,
    IndicatorType.SMA,
    IndicatorType.EMA,
    IndicatorType.VWAP
];

export const getDefaultParamsForIndicator = (name: IndicatorType): Partial<IndicatorConfig> => {
    switch (name) {
        case IndicatorType.SMA:
        case IndicatorType.EMA:
        case IndicatorType.ATR:
            return { period: 14 };
        case IndicatorType.RVOL:
            return { period: 20 };
        case IndicatorType.BOLLINGER_BANDS:
            return { period: 20, stdDev: 2, band_line: "Upper" };
        case IndicatorType.DONCHIAN:
            return { period: 20, band_line: "Upper" };
        case IndicatorType.HIGH_X_DAYS:
        case IndicatorType.LOW_X_DAYS:
            return { days_lookback: 5 };
        case IndicatorType.PREVIOUS_MAX:
        case IndicatorType.PREVIOUS_MIN:
            return { ap_session: "ap.RTH" };
        case IndicatorType.ELAPSED_TIME:
        case IndicatorType.ELAPSED_TIME_LAST_HIGH:
            return {};
        case IndicatorType.OPENING_RANGE_PLUS:
        case IndicatorType.OPENING_RANGE_MINUS:
        case IndicatorType.OPENING_RANGE_AM_PLUS:
        case IndicatorType.OPENING_RANGE_AM_MINUS:
            return { orb_minutes: 30 };
        case IndicatorType.TRIANGLE_ASCENDING:
        case IndicatorType.TRIANGLE_DESCENDING:
        case IndicatorType.TRIANGLE_SYMMETRIC:
            return { pivot_window: 5, tri_lookback: 35, slope_tolerance: 1.5, min_r_squared: 0.65, min_pivots: 2 };
        default:
            return {};
    }
};

export const INDICATOR_CATEGORIES: Record<string, IndicatorType[]> = {
    "Price Variables": [
        IndicatorType.BAR_CLOSE, IndicatorType.BAR_OPEN,
        IndicatorType.HIGH_BAR, IndicatorType.LOW_BAR,
        IndicatorType.PM_OPEN, IndicatorType.PM_HIGH, IndicatorType.PM_LOW,
        IndicatorType.RTH_OPEN, IndicatorType.RTH_HIGH, IndicatorType.RTH_LOW,
        IndicatorType.AM_OPEN,
        IndicatorType.PREVIOUS_MAX, IndicatorType.PREVIOUS_MIN,
        IndicatorType.ELAPSED_TIME_LAST_HIGH,
        IndicatorType.ELAPSED_TIME,
        IndicatorType.YESTERDAY_OPEN, IndicatorType.YESTERDAY_CLOSE,
        IndicatorType.YESTERDAY_HIGH, IndicatorType.YESTERDAY_LOW,
        IndicatorType.HIGH_X_DAYS, IndicatorType.LOW_X_DAYS,
    ],
    "Behaviour & Patterns": [
        IndicatorType.CONSEC_HIGHER_HIGHS, IndicatorType.CONSEC_LOWER_LOWS,
        IndicatorType.CONSEC_LOWER_HIGHS, IndicatorType.CONSEC_HIGHER_LOWS,
        IndicatorType.CONSEC_GREEN_CANDLES, IndicatorType.CONSEC_RED_CANDLES,
        IndicatorType.CANDLE_RANGE_PCT,
        IndicatorType.OPENING_RANGE_PLUS, IndicatorType.OPENING_RANGE_MINUS,
        IndicatorType.OPENING_RANGE_AM_PLUS, IndicatorType.OPENING_RANGE_AM_MINUS,
        IndicatorType.TRIANGLE_ASCENDING, IndicatorType.TRIANGLE_DESCENDING,
        IndicatorType.TRIANGLE_SYMMETRIC,
        IndicatorType.PM_HIGH_GAP,
    ],
    "Indicators": [
        IndicatorType.SMA, IndicatorType.EMA, IndicatorType.VWAP,
        IndicatorType.DONCHIAN, IndicatorType.BOLLINGER_BANDS,
        IndicatorType.ACCUMULATED_VOLUME,
        IndicatorType.RVOL, IndicatorType.VOLUME, IndicatorType.ATR,
    ],
};

// Human-readable labels for comparators using symbols
export const COMPARATOR_LABELS: Record<string, string> = {
    [Comparator.GT]: ">",
    [Comparator.LT]: "<",
    [Comparator.GTE]: "≥",
    [Comparator.LTE]: "≤",
    [Comparator.EQ]: "=",
    [Comparator.CROSSES_ABOVE]: "↗ Crosses Above",
    [Comparator.CROSSES_BELOW]: "↘ Crosses Below",
};

export const INDICATOR_LABELS: Record<string, string> = {
    // Price Variables
    [IndicatorType.BAR_CLOSE]: "Bar Close",
    [IndicatorType.BAR_OPEN]: "Bar Open",
    [IndicatorType.HIGH_BAR]: "High Bar",
    [IndicatorType.LOW_BAR]: "Low Bar",
    [IndicatorType.PM_OPEN]: "PM Open",
    [IndicatorType.PM_HIGH]: "PM High",
    [IndicatorType.PM_LOW]: "PM Low",
    [IndicatorType.RTH_OPEN]: "RTH Open",
    [IndicatorType.RTH_HIGH]: "RTH High",
    [IndicatorType.RTH_LOW]: "RTH Low",
    [IndicatorType.AM_OPEN]: "AM Open",
    [IndicatorType.PREVIOUS_MAX]: "Previous Max",
    [IndicatorType.PREVIOUS_MIN]: "Previous Min",
    [IndicatorType.YESTERDAY_OPEN]: "Yesterday Open",
    [IndicatorType.YESTERDAY_CLOSE]: "Yesterday Close",
    [IndicatorType.YESTERDAY_HIGH]: "Yesterday High",
    [IndicatorType.YESTERDAY_LOW]: "Yesterday Low",
    [IndicatorType.HIGH_X_DAYS]: "High of last X days",
    [IndicatorType.LOW_X_DAYS]: "Low of last X days",
    [IndicatorType.ELAPSED_TIME_LAST_HIGH]: "Elapsed Time Last High",
    [IndicatorType.ELAPSED_TIME]: "Elapsed Time",
    // Behaviour & Patterns
    [IndicatorType.CONSEC_HIGHER_HIGHS]: "Consec Higher Highs",
    [IndicatorType.CONSEC_LOWER_LOWS]: "Consec Lower Lows",
    [IndicatorType.CONSEC_LOWER_HIGHS]: "Consec Lower Highs",
    [IndicatorType.CONSEC_HIGHER_LOWS]: "Consec Higher Lows",
    [IndicatorType.CONSEC_GREEN_CANDLES]: "Consec Green Candles",
    [IndicatorType.CONSEC_RED_CANDLES]: "Consec Red Candles",
    [IndicatorType.CANDLE_RANGE_PCT]: "Candle Range %",
    [IndicatorType.OPENING_RANGE_PLUS]: "Opening Range +",
    [IndicatorType.OPENING_RANGE_MINUS]: "Opening Range -",
    [IndicatorType.OPENING_RANGE_AM_PLUS]: "Opening Range AM +",
    [IndicatorType.OPENING_RANGE_AM_MINUS]: "Opening Range AM -",
    [IndicatorType.TRIANGLE_ASCENDING]: "▲ Triangle Ascending",
    [IndicatorType.TRIANGLE_DESCENDING]: "▼ Triangle Descending",
    [IndicatorType.TRIANGLE_SYMMETRIC]: "◇ Triangle Symmetric",
    [IndicatorType.PM_HIGH_GAP]: "PM High Gap (%)",
    // Indicators
    [IndicatorType.SMA]: "SMA",
    [IndicatorType.EMA]: "EMA",
    [IndicatorType.VWAP]: "VWAP",
    [IndicatorType.DONCHIAN]: "Donchian",
    [IndicatorType.BOLLINGER_BANDS]: "Bollinger Bands",
    [IndicatorType.ACCUMULATED_VOLUME]: "Accum. Volume",
    [IndicatorType.YESTERDAY_VOLUME]: "Yesterday Volume",
    [IndicatorType.RVOL]: "RVOL by bar",
    [IndicatorType.VOLUME]: "Volume",
    [IndicatorType.ATR]: "ATR",
};

interface TooltipContextType {
    setActiveTooltip: (tooltip: { text: string; x: number; y: number; width: number; } | null) => void;
    containerRef: React.RefObject<HTMLDivElement | null>;
}
const TooltipContext = React.createContext<TooltipContextType | null>(null);

export const INDICATOR_DESCRIPTIONS: Record<string, string> = {
    [IndicatorType.BAR_CLOSE]: "Precio de cierre de la barra actual.",
    [IndicatorType.BAR_OPEN]: "Precio de apertura de la barra actual.",
    [IndicatorType.HIGH_BAR]: "Precio máximo de la barra actual.",
    [IndicatorType.LOW_BAR]: "Precio mínimo de la barra actual.",
    [IndicatorType.PM_OPEN]: "Apertura del Premarket (04:00).",
    [IndicatorType.PM_HIGH]: "Máximo de la sesión de Premarket.",
    [IndicatorType.PM_LOW]: "Mínimo de la sesión de Premarket.",
    [IndicatorType.RTH_OPEN]: "Precio de apertura de la sesión ordinaria de mercado (RTH, 09:30).",
    [IndicatorType.RTH_HIGH]: "Máximo de la sesión ordinaria de mercado (RTH).",
    [IndicatorType.RTH_LOW]: "Mínimo de la sesión ordinaria de mercado (RTH).",
    [IndicatorType.AM_OPEN]: "Apertura de la sesión After Market (16:00).",
    [IndicatorType.PREVIOUS_MAX]: "Último Máximo desde la apertura de la sesión de referencia y la vela actual",
    [IndicatorType.PREVIOUS_MIN]: "Último Mínimo desde la apertura de la sesión de referencia y la vela actual",
    [IndicatorType.ELAPSED_TIME_LAST_HIGH]: "Minutos transcurridos desde el último máximo de la sesión.",
    [IndicatorType.ELAPSED_TIME]: "Tiempo transcurrido desde la apertura de la orden (en minutos) para forzar su cierre.",
    [IndicatorType.YESTERDAY_OPEN]: "Precio de apertura de ayer.",
    [IndicatorType.YESTERDAY_CLOSE]: "Precio de cierre de ayer.",
    [IndicatorType.YESTERDAY_HIGH]: "Precio máximo de ayer.",
    [IndicatorType.YESTERDAY_LOW]: "Precio mínimo de ayer.",
    [IndicatorType.HIGH_X_DAYS]: "El máximo más alto de los últimos X días (diario).",
    [IndicatorType.LOW_X_DAYS]: "El mínimo más bajo de los últimos X días (diario).",
    
    // Behaviour & Patterns
    [IndicatorType.CONSEC_HIGHER_HIGHS]: "Número de máximos consecutivos más altos (velas consecutivas subiendo).",
    [IndicatorType.CONSEC_LOWER_LOWS]: "Número de mínimos consecutivos más bajos.",
    [IndicatorType.CONSEC_LOWER_HIGHS]: "Número de velas consecutivas con máximos más bajos.",
    [IndicatorType.CONSEC_HIGHER_LOWS]: "Número de velas consecutivas con mínimos más altos.",
    [IndicatorType.CONSEC_GREEN_CANDLES]: "Número de velas consecutivas alcistas (cierre > apertura).",
    [IndicatorType.CONSEC_RED_CANDLES]: "Número de velas consecutivas bajistas (cierre < apertura).",
    [IndicatorType.CANDLE_RANGE_PCT]: "Rango de la vela actual en porcentaje (High vs Low).",
    [IndicatorType.OPENING_RANGE_PLUS]: "Rompimiento alcista del rango de apertura (ej. los primeros 5/15/30 mins).",
    [IndicatorType.OPENING_RANGE_MINUS]: "Rompimiento bajista del rango de apertura.",
    [IndicatorType.OPENING_RANGE_AM_PLUS]: "Rompimiento alcista en After Market.",
    [IndicatorType.OPENING_RANGE_AM_MINUS]: "Rompimiento bajista en After Market.",
    [IndicatorType.TRIANGLE_ASCENDING]: "Patrón de triángulo ascendente.",
    [IndicatorType.TRIANGLE_DESCENDING]: "Patrón de triángulo descendente.",
    [IndicatorType.TRIANGLE_SYMMETRIC]: "Patrón de triángulo simétrico.",
    [IndicatorType.PM_HIGH_GAP]: "El máximo gap hecho durante la sesión de premercado, es decir, el % de diferencia entre el cierre de ayer y el máximo del premarket high.",
    
    // Technical Indicators
    [IndicatorType.SMA]: "Media Móvil Simple.",
    [IndicatorType.EMA]: "Media Móvil Exponencial.",
    [IndicatorType.VWAP]: "Precio Medio Ponderado por Volumen de la sesión.",
    [IndicatorType.DONCHIAN]: "Canales de Donchian.",
    [IndicatorType.BOLLINGER_BANDS]: "Bandas de Bollinger.",
    [IndicatorType.ACCUMULATED_VOLUME]: "Volumen total acumulado desde el inicio de la sesión en Premarket hasta la vela actual",
    [IndicatorType.YESTERDAY_VOLUME]: "Volumen total registrado el día de ayer.",
    [IndicatorType.RVOL]: "Volumen relativo de la barra respecto a su hora histórica.",
    [IndicatorType.VOLUME]: "Volumen individual de la barra actual.",
    [IndicatorType.ATR]: "Rango Medio Verdadero."
};

const TooltipIcon = ({ indicatorName, customText }: { indicatorName?: IndicatorType; customText?: string }) => {
    const context = React.useContext(TooltipContext);
    if (!context) return null;

    const { setActiveTooltip, containerRef } = context;
    const description = customText || (indicatorName ? INDICATOR_DESCRIPTIONS[indicatorName] : undefined);
    if (!description) return null;

    return (
        <span
            onMouseEnter={(e) => {
                if (!containerRef.current) return;
                const containerRect = containerRef.current.getBoundingClientRect();
                const rect = e.currentTarget.getBoundingClientRect();
                
                // Estimar el ancho del tooltip basado en el largo del texto
                const estimatedWidth = Math.min(Math.max(description.length * 6.5 + 24, 100), 320);
                const halfWidth = estimatedWidth / 2;
                
                let tooltipX = rect.left - containerRect.left + rect.width / 2;
                const tooltipY = rect.top - containerRect.top - 6;
                
                const minMargin = 16;
                if (tooltipX - halfWidth < minMargin) {
                    tooltipX = minMargin + halfWidth;
                }
                
                const maxRight = containerRect.width - minMargin;
                if (tooltipX + halfWidth > maxRight) {
                    tooltipX = maxRight - halfWidth;
                }
                
                setActiveTooltip({
                    text: description,
                    x: tooltipX,
                    y: tooltipY,
                    width: estimatedWidth,
                });
                e.currentTarget.style.color = "var(--color-ec-text-primary)";
                e.currentTarget.style.borderColor = "var(--color-ec-text-muted)";
                e.currentTarget.style.backgroundColor = "var(--color-ec-bg-surface)";
            }}
            onMouseLeave={(e) => {
                setActiveTooltip(null);
                e.currentTarget.style.color = "var(--color-ec-text-muted)";
                e.currentTarget.style.borderColor = "var(--color-ec-border)";
                e.currentTarget.style.backgroundColor = "var(--color-ec-bg-elevated)";
            }}
            style={{
                display: "inline-flex",
                alignItems: "center",
                justifyContent: "center",
                width: 14,
                height: 14,
                borderRadius: "50%",
                backgroundColor: "var(--color-ec-bg-elevated)",
                border: "0.5px solid var(--color-ec-border)",
                color: "var(--color-ec-text-muted)",
                fontSize: 9,
                fontWeight: 700,
                cursor: "help",
                flexShrink: 0,
                userSelect: "none",
                transition: "all 150ms ease",
            }}
        >
            ?
        </span>
    );
};

const FIXED_VALUE_KEY = "__FIXED_VALUE__";

export const getInitialTargetForSource = (sourceName: IndicatorType): IndicatorConfig | number => {
    const allowed = getAllowedTargets(sourceName, 'indicator_comparison');
    if (allowed.length === 0) {
        return 0; // Fixed value
    }
    if (allowed.includes(IndicatorType.VWAP)) {
        return { name: IndicatorType.VWAP, offset: 0 };
    }
    return { name: allowed[0], offset: 0 };
};

// ----------------------------------------------------------------------
// Generic Selector
// ----------------------------------------------------------------------
export const IndicatorSelector = ({ 
    value, 
    onChange, 
    isTarget,
    allowedTargets,
    exclude = [],
    width = '100%'
}: { 
    value: string, 
    onChange: (val: string) => void, 
    isTarget?: boolean,
    allowedTargets?: IndicatorType[],
    exclude?: IndicatorType[],
    width?: string | number
}) => {
    const [isOpen, setIsOpen] = React.useState(false);
    const dropdownRef = React.useRef<HTMLDivElement>(null);

    React.useEffect(() => {
        const handleClickOutside = (event: MouseEvent) => {
            if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
                setIsOpen(false);
            }
        };
        document.addEventListener('mousedown', handleClickOutside);
        return () => document.removeEventListener('mousedown', handleClickOutside);
    }, []);

    const selectedLabel = value === FIXED_VALUE_KEY ? '── Fixed Value ──' : (INDICATOR_LABELS[value as IndicatorType] || value);

    return (
        <div 
            ref={dropdownRef} 
            style={{ 
                position: 'relative', 
                width: width,
                display: 'inline-block'
            }}
        >
            <div
                onClick={() => setIsOpen(!isOpen)}
                style={{
                    backgroundColor: 'var(--color-ec-bg-sidebar)',
                    border: '0.5px solid var(--color-ec-border)',
                    borderRadius: 5,
                    padding: '5px 10px',
                    fontSize: 12,
                    fontWeight: 500,
                    color: 'var(--color-ec-text-primary)',
                    fontFamily: 'var(--color-ec-sans)',
                    width: '100%',
                    cursor: 'pointer',
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    userSelect: 'none',
                    boxSizing: 'border-box'
                }}
            >
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, overflow: 'hidden', flex: 1 }}>
                    <span style={{ textOverflow: 'ellipsis', overflow: 'hidden', whiteSpace: 'nowrap' }}>{selectedLabel}</span>
                    {value !== FIXED_VALUE_KEY && (
                        <span onClick={(e) => e.stopPropagation()} style={{ display: 'inline-flex', alignItems: 'center' }}>
                            <TooltipIcon indicatorName={value as IndicatorType} />
                        </span>
                    )}
                </div>
                <span style={{ fontSize: 8, color: 'var(--color-ec-text-muted)', marginLeft: 6 }}>
                    {isOpen ? '▲' : '▼'}
                </span>
            </div>

            {isOpen && (
                <div style={{
                    position: 'absolute',
                    top: '100%',
                    left: 0,
                    marginTop: 4,
                    width: '100%',
                    minWidth: 220,
                    maxHeight: 280,
                    overflowY: 'auto',
                    backgroundColor: 'var(--color-ec-bg-elevated)',
                    border: '0.5px solid var(--color-ec-border)',
                    borderRadius: 5,
                    boxShadow: '0 8px 24px rgba(0,0,0,0.15)',
                    zIndex: 9999, // Ensure it floats above everything
                    fontFamily: 'var(--color-ec-sans)',
                }}>
                    {Object.entries(INDICATOR_CATEGORIES).map(([category, indicators]) => {
                        const filtered = indicators.filter(t => 
                            (allowedTargets ? allowedTargets.includes(t) : true) && 
                            !exclude.includes(t)
                        );
                        if (filtered.length === 0) return null;
                        
                        return (
                            <div key={category}>
                                <div style={{
                                    padding: '5px 10px',
                                    fontSize: 9,
                                    fontWeight: 700,
                                    color: 'var(--color-ec-text-muted)',
                                    textTransform: 'uppercase',
                                    letterSpacing: '0.08em',
                                    backgroundColor: 'rgba(255,255,255,0.01)',
                                    borderBottom: '0.5px solid var(--color-ec-border)',
                                    borderTop: '0.5px solid var(--color-ec-border)',
                                }}>
                                    {category}
                                </div>
                                {filtered.map(t => {
                                    const isSelected = value === t;
                                    return (
                                        <div 
                                            key={t}
                                            style={{
                                                display: 'flex',
                                                alignItems: 'center',
                                                justifyContent: 'flex-start',
                                                gap: 5,
                                                backgroundColor: isSelected ? 'rgba(216, 122, 61, 0.08)' : 'transparent',
                                                borderLeft: isSelected ? '3px solid var(--color-ec-copper)' : '3px solid transparent',
                                                padding: '4px 10px',
                                            }}
                                            onMouseEnter={(e) => {
                                                if (!isSelected) e.currentTarget.style.backgroundColor = 'var(--color-ec-bg-surface)';
                                            }}
                                            onMouseLeave={(e) => {
                                                if (!isSelected) e.currentTarget.style.backgroundColor = 'transparent';
                                            }}
                                        >
                                            <div 
                                                onClick={() => { onChange(t); setIsOpen(false); }}
                                                style={{
                                                    cursor: 'pointer',
                                                    color: isSelected ? 'var(--color-ec-copper-bright)' : 'var(--color-ec-text-primary)',
                                                    fontWeight: isSelected ? 600 : 400,
                                                    fontSize: 11.5,
                                                    textOverflow: 'ellipsis',
                                                    overflow: 'hidden',
                                                    whiteSpace: 'nowrap'
                                                }}
                                            >
                                                {INDICATOR_LABELS[t] || t}
                                            </div>
                                            <div style={{ display: 'flex', alignItems: 'center' }}>
                                                <TooltipIcon indicatorName={t} />
                                            </div>
                                        </div>
                                    );
                                })}
                            </div>
                        );
                    })}
                    {isTarget && (
                        <div 
                            style={{
                                display: 'flex',
                                alignItems: 'center',
                                justifyContent: 'space-between',
                                backgroundColor: value === FIXED_VALUE_KEY ? 'rgba(216, 122, 61, 0.08)' : 'transparent',
                                borderLeft: value === FIXED_VALUE_KEY ? '3px solid var(--color-ec-copper)' : '3px solid transparent',
                                borderTop: '0.5px solid var(--color-ec-border)',
                            }}
                            onMouseEnter={(e) => {
                                if (value !== FIXED_VALUE_KEY) e.currentTarget.style.backgroundColor = 'var(--color-ec-bg-surface)';
                            }}
                            onMouseLeave={(e) => {
                                if (value !== FIXED_VALUE_KEY) e.currentTarget.style.backgroundColor = 'transparent';
                            }}
                        >
                            <div 
                                onClick={() => { onChange(FIXED_VALUE_KEY); setIsOpen(false); }}
                                style={{
                                    flex: 1,
                                    padding: '6px 10px',
                                    cursor: 'pointer',
                                    color: value === FIXED_VALUE_KEY ? 'var(--color-ec-copper-bright)' : 'var(--color-ec-text-primary)',
                                    fontWeight: value === FIXED_VALUE_KEY ? 600 : 400,
                                    fontSize: 11.5,
                                }}
                            >
                                ── Fixed Value ──
                            </div>
                        </div>
                    )}
                </div>
            )}
        </div>
    );
};

// ----------------------------------------------------------------------
// Dynamic Inputs specific to Indicator
// ----------------------------------------------------------------------
export const IndicatorParams = ({
    value,
    onChange,
    hideOffset = false
}: {
    value: IndicatorConfig;
    onChange: (val: IndicatorConfig) => void;
    hideOffset?: boolean;
}) => {
    return (
        <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap', width: '100%' }}>
            {/* Specific Params */}
            {(() => {
                switch (value.name) {
                    case IndicatorType.SMA:
                    case IndicatorType.EMA:
                    case IndicatorType.ATR:
                    case IndicatorType.RVOL:
                        return (
                            <input
                                type="number"
                                value={value.period || ''}
                                onChange={(e) => onChange({ ...value, period: Number(e.target.value) })}
                                placeholder="Period"
                                style={{
                                    width: '100%',
                                    backgroundColor: 'var(--color-ec-bg-sidebar)',
                                    border: '0.5px solid var(--color-ec-border)',
                                    borderRadius: 5,
                                    padding: '5px 10px',
                                    fontSize: 12,
                                    fontWeight: 500,
                                    color: 'var(--color-ec-text-primary)',
                                    fontFamily: 'var(--color-ec-sans)',
                                    outline: 'none',
                                }}
                                title="Period"
                            />
                        );
                    case IndicatorType.BOLLINGER_BANDS:
                    case IndicatorType.DONCHIAN:
                        return (
                            <div style={{ display: 'flex', gap: 6, width: '100%', flexWrap: 'wrap' }}>
                                <input
                                    type="number"
                                    value={value.period || ''}
                                    onChange={(e) => onChange({ ...value, period: Number(e.target.value) })}
                                    placeholder="Period"
                                    style={{
                                        flex: '1 1 70px',
                                        minWidth: '70px',
                                        backgroundColor: 'var(--color-ec-bg-sidebar)',
                                        border: '0.5px solid var(--color-ec-border)',
                                        borderRadius: 5,
                                        padding: '5px 10px',
                                        fontSize: 12,
                                        fontWeight: 500,
                                        color: 'var(--color-ec-text-primary)',
                                        fontFamily: 'var(--color-ec-sans)',
                                        outline: 'none',
                                    }}
                                    title="Period"
                                />
                                {value.name === IndicatorType.BOLLINGER_BANDS && (
                                    <input
                                        type="number"
                                        value={value.stdDev || ''}
                                        onChange={(e) => onChange({ ...value, stdDev: Number(e.target.value) })}
                                        placeholder="Std Dev"
                                        style={{
                                            flex: '1 1 70px',
                                            minWidth: '70px',
                                            backgroundColor: 'var(--color-ec-bg-sidebar)',
                                            border: '0.5px solid var(--color-ec-border)',
                                            borderRadius: 5,
                                            padding: '5px 10px',
                                            fontSize: 12,
                                            fontWeight: 500,
                                            color: 'var(--color-ec-text-primary)',
                                            fontFamily: 'var(--color-ec-sans)',
                                            outline: 'none',
                                        }}
                                        title="Standard Deviation"
                                    />
                                )}
                                <select
                                    value={value.band_line || 'Upper'}
                                    onChange={(e) => onChange({ ...value, band_line: e.target.value as "Upper" | "Lower" | "Basis" })}
                                    style={{
                                        flex: '1 1 90px',
                                        minWidth: '90px',
                                        backgroundColor: 'var(--color-ec-bg-sidebar)',
                                        border: '0.5px solid var(--color-ec-border)',
                                        borderRadius: 5,
                                        padding: '5px 10px',
                                        fontSize: 12,
                                        fontWeight: 500,
                                        color: 'var(--color-ec-text-primary)',
                                        fontFamily: 'var(--color-ec-sans)',
                                        outline: 'none',
                                        cursor: 'pointer',
                                    }}
                                >
                                    <option value="Upper">Upper</option>
                                    <option value="Lower">Lower</option>
                                    <option value="Basis">Basis</option>
                                </select>
                            </div>
                        );
                    case IndicatorType.OPENING_RANGE_PLUS:
                    case IndicatorType.OPENING_RANGE_MINUS:
                    case IndicatorType.OPENING_RANGE_AM_PLUS:
                    case IndicatorType.OPENING_RANGE_AM_MINUS:
                        return (
                            <div style={{ display: 'flex', alignItems: 'center', gap: 6, width: '100%' }}>
                                <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--color-ec-text-muted)' }}>Mins:</span>
                                <input
                                    type="number"
                                    value={value.orb_minutes || ''}
                                    onChange={(e) => onChange({ ...value, orb_minutes: Number(e.target.value) })}
                                    placeholder="Minutes"
                                    style={{
                                        flex: 1,
                                        backgroundColor: 'var(--color-ec-bg-sidebar)',
                                        border: '0.5px solid var(--color-ec-border)',
                                        borderRadius: 5,
                                        padding: '5px 10px',
                                        fontSize: 12,
                                        fontWeight: 500,
                                        color: 'var(--color-ec-text-primary)',
                                        fontFamily: 'var(--color-ec-sans)',
                                        outline: 'none',
                                    }}
                                    title="Reference minutes (ex. 30 for 30min ORB)"
                                />
                            </div>
                        );

                    case IndicatorType.HIGH_X_DAYS:
                    case IndicatorType.LOW_X_DAYS:
                        return (
                            <div style={{ display: 'flex', alignItems: 'center', gap: 6, width: '100%' }}>
                                <input
                                    type="number"
                                    value={value.days_lookback || ''}
                                    onChange={(e) => onChange({ ...value, days_lookback: Number(e.target.value) })}
                                    placeholder="Days"
                                    style={{
                                        flex: 1,
                                        backgroundColor: 'var(--color-ec-bg-sidebar)',
                                        border: '0.5px solid var(--color-ec-border)',
                                        borderRadius: 5,
                                        padding: '5px 10px',
                                        fontSize: 12,
                                        fontWeight: 500,
                                        color: 'var(--color-ec-text-primary)',
                                        fontFamily: 'var(--color-ec-sans)',
                                        outline: 'none',
                                    }}
                                    title="Number of Days Back"
                                />
                                <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--color-ec-text-muted)' }}>días</span>
                            </div>
                        );
                    case IndicatorType.PREVIOUS_MAX:
                    case IndicatorType.PREVIOUS_MIN:
                        return (
                            <div style={{ display: 'flex', alignItems: 'center', gap: 6, width: '100%' }}>
                                <span style={{ fontSize: 10, fontWeight: 700, color: 'var(--color-ec-text-muted)', textTransform: 'uppercase', letterSpacing: 0.5 }}>
                                    Session:
                                </span>
                                <select
                                    value={value.ap_session || "ap.RTH"}
                                    onChange={(e) => onChange({ ...value, ap_session: e.target.value as "ap.PM" | "ap.RTH" | "ap.AM" })}
                                    style={{
                                        flex: 1,
                                        backgroundColor: 'var(--color-ec-bg-sidebar)',
                                        border: '0.5px solid var(--color-ec-border)',
                                        borderRadius: 5,
                                        padding: '5px 10px',
                                        fontSize: 12,
                                        fontWeight: 500,
                                        color: 'var(--color-ec-text-primary)',
                                        fontFamily: 'var(--color-ec-sans)',
                                        outline: 'none',
                                        cursor: 'pointer',
                                    }}
                                >
                                    <option value="ap.PM">ap.PM</option>
                                    <option value="ap.RTH">ap.RTH</option>
                                    <option value="ap.AM">ap.AM</option>
                                </select>
                            </div>
                        );
                    default:
                        // Triangle Patterns
                        if (
                            value.name === IndicatorType.TRIANGLE_ASCENDING ||
                            value.name === IndicatorType.TRIANGLE_DESCENDING ||
                            value.name === IndicatorType.TRIANGLE_SYMMETRIC
                        ) {
                            return (
                                <div style={{ display: 'flex', flexDirection: 'column', gap: 6, width: '100%' }}>
                                    <div style={{ display: 'flex', gap: 6, width: '100%', flexWrap: 'wrap' }}>
                                        <div style={{ flex: '1 1 60px', minWidth: '60px' }}>
                                            <span style={{ fontSize: 9, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--color-ec-text-muted)', display: 'block', marginBottom: 2 }}>Pivot Win.</span>
                                            <input
                                                type="number"
                                                min={2}
                                                max={20}
                                                value={value.pivot_window ?? 5}
                                                onChange={(e) => onChange({ ...value, pivot_window: Math.max(2, Number(e.target.value)) })}
                                                style={{
                                                    width: '100%',
                                                    backgroundColor: 'var(--color-ec-bg-sidebar)',
                                                    border: '0.5px solid var(--color-ec-border)',
                                                    borderRadius: 5,
                                                    padding: '5px 8px',
                                                    fontSize: 12,
                                                    fontWeight: 500,
                                                    color: 'var(--color-ec-text-primary)',
                                                    fontFamily: 'var(--color-ec-sans)',
                                                    outline: 'none',
                                                }}
                                                title="Pivot Window: candles to left and right required to confirm a Swing High/Low"
                                            />
                                        </div>
                                        <div style={{ flex: '1 1 60px', minWidth: '60px' }}>
                                            <span style={{ fontSize: 9, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--color-ec-text-muted)', display: 'block', marginBottom: 2 }}>Min Pivots</span>
                                            <input
                                                type="number"
                                                min={2}
                                                max={50}
                                                value={value.min_pivots ?? 2}
                                                onChange={(e) => onChange({ ...value, min_pivots: Math.max(2, Number(e.target.value)) })}
                                                style={{
                                                    width: '100%',
                                                    backgroundColor: 'var(--color-ec-bg-sidebar)',
                                                    border: '0.5px solid var(--color-ec-border)',
                                                    borderRadius: 5,
                                                    padding: '5px 8px',
                                                    fontSize: 12,
                                                    fontWeight: 500,
                                                    color: 'var(--color-ec-text-primary)',
                                                    fontFamily: 'var(--color-ec-sans)',
                                                    outline: 'none',
                                                }}
                                                title="Min Pivots: minimum swing highs and lows required to fit trend lines (min 2)"
                                            />
                                        </div>
                                        <div style={{ flex: '1 1 60px', minWidth: '60px' }}>
                                            <span style={{ fontSize: 9, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--color-ec-text-muted)', display: 'block', marginBottom: 2 }}>Lookback</span>
                                            <input
                                                type="number"
                                                min={10}
                                                max={200}
                                                value={value.tri_lookback ?? 35}
                                                onChange={(e) => onChange({ ...value, tri_lookback: Math.max(10, Number(e.target.value)) })}
                                                style={{
                                                    width: '100%',
                                                    backgroundColor: 'var(--color-ec-bg-sidebar)',
                                                    border: '0.5px solid var(--color-ec-border)',
                                                    borderRadius: 5,
                                                    padding: '5px 8px',
                                                    fontSize: 12,
                                                    fontWeight: 500,
                                                    color: 'var(--color-ec-text-primary)',
                                                    fontFamily: 'var(--color-ec-sans)',
                                                    outline: 'none',
                                                }}
                                                title="Lookback: how many bars back to search for pivots"
                                            />
                                        </div>
                                    </div>
                                    <div style={{ display: 'flex', gap: 6, width: '100%', flexWrap: 'wrap', alignItems: 'flex-end' }}>
                                        <div style={{ flex: '1 1 90px', minWidth: '90px' }}>
                                            <span style={{ fontSize: 9, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--color-ec-text-muted)', display: 'block', marginBottom: 2 }}>Slope Tol. (%)</span>
                                            <input
                                                type="number"
                                                min={0.01}
                                                max={10.0}
                                                step={0.1}
                                                value={value.slope_tolerance ?? 1.5}
                                                onChange={(e) => onChange({ ...value, slope_tolerance: Math.max(0.01, Number(e.target.value)) })}
                                                style={{
                                                    width: '100%',
                                                    backgroundColor: 'var(--color-ec-bg-sidebar)',
                                                    border: '0.5px solid var(--color-ec-border)',
                                                    borderRadius: 5,
                                                    padding: '5px 8px',
                                                    fontSize: 12,
                                                    fontWeight: 500,
                                                    color: 'var(--color-ec-text-primary)',
                                                    fontFamily: 'var(--color-ec-sans)',
                                                    outline: 'none',
                                                }}
                                                title="Slope Tolerance (%): max total price change over the lookback window to consider a trend line 'flat'"
                                            />
                                        </div>
                                        <div style={{ flex: '1 2 110px', minWidth: '110px' }}>
                                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 2 }}>
                                                <span style={{ fontSize: 9, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--color-ec-text-muted)' }}>Min R²</span>
                                                <span style={{ fontSize: 10, fontWeight: 600, color: 'var(--color-ec-text-primary)', fontFamily: 'var(--color-ec-sans)' }}>{(value.min_r_squared ?? 0.65).toFixed(2)}</span>
                                            </div>
                                            <input
                                                type="range"
                                                min={0}
                                                max={1}
                                                step={0.01}
                                                value={value.min_r_squared ?? 0.65}
                                                onChange={(e) => onChange({ ...value, min_r_squared: Number(e.target.value) })}
                                                style={{
                                                    width: '100%',
                                                    accentColor: 'var(--color-ec-copper)',
                                                    cursor: 'pointer',
                                                }}
                                                title="Minimum R-squared quality for trend lines (0 = no requirement, 1 = perfect fit)"
                                            />
                                        </div>
                                    </div>
                                </div>
                            );
                        }
                        return null;
                }
            })()}
            
            {/* Global Offset Param */}
            {!hideOffset && (
                <div className="flex items-center gap-1.5 ml-1 border-l border-border/30 pl-2">
                    <span style={{
                        fontSize: 9,
                        fontWeight: 700,
                        textTransform: 'uppercase',
                        letterSpacing: '0.1em',
                        color: 'var(--color-ec-copper)',
                        fontFamily: 'var(--color-ec-sans)',
                    }}>Bars Back (X):</span>
                    <input
                        type="number"
                        min="0"
                        value={value.offset || 0}
                        onChange={(e) => onChange({ ...value, offset: Math.max(0, Number(e.target.value)) })}
                        placeholder="0"
                        style={{
                            width: 52,
                            backgroundColor: 'color-mix(in srgb, var(--color-ec-copper) 10%, transparent)',
                            border: '0.5px solid color-mix(in srgb, var(--color-ec-copper) 30%, transparent)',
                            borderRadius: 4,
                            padding: '4px 8px',
                            fontSize: 11,
                            fontWeight: 700,
                            color: 'var(--color-ec-copper)',
                            fontFamily: 'var(--color-ec-sans)',
                            outline: 'none',
                        }}
                        title="Offset: 0 = current bar, 1 = previous bar, etc."
                    />
                </div>
            )}
        </div>
    );
};

// ----------------------------------------------------------------------
// Source Indicator Input (left side)
// ----------------------------------------------------------------------

export const SourceIndicatorInput = ({
    value,
    onChange,
    exclude = [],
    allowedTargets,
    hideOffset = false
}: {
    value: IndicatorConfig;
    onChange: (val: IndicatorConfig) => void;
    exclude?: IndicatorType[];
    allowedTargets?: IndicatorType[];
    hideOffset?: boolean;
}) => {
    return (
        <div className="flex flex-col gap-1.5 items-stretch bg-muted/5 border border-border/20 rounded p-1.5 w-full md:w-auto min-w-[200px]">
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <IndicatorSelector
                    value={value.name}
                    exclude={exclude}
                    allowedTargets={allowedTargets}
                    onChange={(nameStr) => {
                        const name = nameStr as IndicatorType;
                        const defaultParams = getDefaultParamsForIndicator(name);
                        onChange({ name, ...defaultParams });
                    }}
                />
            </div>
            <IndicatorParams value={value} onChange={onChange} hideOffset={hideOffset} />
        </div>
    );
};

// ----------------------------------------------------------------------
// Target Input (right side, after comparator)
// ----------------------------------------------------------------------

export const TargetInput = ({
    value,
    onChange,
    allowedTargets,
    hideOffset = false,
    sourceIndicatorName
}: {
    value: IndicatorConfig | number;
    onChange: (val: IndicatorConfig | number) => void;
    allowedTargets?: IndicatorType[];
    hideOffset?: boolean;
    sourceIndicatorName?: IndicatorType;
}) => {
    const isFixed = typeof value === 'number';
    const selectedKey = isFixed ? FIXED_VALUE_KEY : (value as IndicatorConfig).name;
    const isVol = isFixed && isVolumeIndicator(sourceIndicatorName);
    const isPercent = isFixed && sourceIndicatorName === IndicatorType.PM_HIGH_GAP;

    const [localText, setLocalText] = React.useState("");

    React.useEffect(() => {
        if (!isFixed && allowedTargets) {
            const currentName = (value as IndicatorConfig).name;
            if (allowedTargets.length === 0) {
                onChange(0);
            } else if (!allowedTargets.includes(currentName)) {
                if (allowedTargets.includes(IndicatorType.VWAP)) {
                    onChange({ name: IndicatorType.VWAP, offset: 0 });
                } else if (allowedTargets.length > 0) {
                    const name = allowedTargets[0];
                    const defaultParams = getDefaultParamsForIndicator(name);
                    onChange({ name, ...defaultParams });
                } else {
                    onChange(0);
                }
            }
        }
    }, [value, isFixed, allowedTargets, onChange]);

    React.useEffect(() => {
        if (isFixed) {
            if (isVol) {
                const clean = localText.trim().toLowerCase();
                const numericStr = clean.endsWith('m') ? clean.slice(0, -1) : clean;
                const parsedVal = parseFloat(numericStr) * 1000000;
                if (isNaN(parsedVal) || parsedVal !== value || localText === "") {
                    setLocalText((value / 1000000).toString());
                }
            } else {
                const parsedVal = parseFloat(localText);
                if (isNaN(parsedVal) || parsedVal !== value || localText === "") {
                    setLocalText(value.toString());
                }
            }
        }
    }, [value, isFixed, isVol]);

    const handleTextChange = (txt: string) => {
        setLocalText(txt);
        if (isVol) {
            const clean = txt.trim().toLowerCase();
            const numericStr = clean.endsWith('m') ? clean.slice(0, -1) : clean;
            const num = parseFloat(numericStr);
            if (!isNaN(num)) {
                onChange(num * 1000000);
            }
        } else {
            const num = parseFloat(txt);
            if (!isNaN(num)) {
                onChange(num);
            }
        }
    };

    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6, width: '100%' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <IndicatorSelector
                    isTarget
                    value={selectedKey}
                    allowedTargets={allowedTargets}
                    onChange={(key) => {
                        if (key === FIXED_VALUE_KEY) {
                            onChange(0);
                        } else {
                            const name = key as IndicatorType;
                            const defaultParams = getDefaultParamsForIndicator(name);
                            onChange({ name, ...defaultParams });
                        }
                    }}
                />
            </div>

            {!isFixed && (
                <IndicatorParams
                    value={value as IndicatorConfig}
                    onChange={(newVal) => onChange(newVal)}
                    hideOffset={hideOffset}
                />
            )}

            {isFixed && (
                isVol ? (
                    <div style={{ position: 'relative', width: '100%' }}>
                        <input
                            type="text"
                            value={localText}
                            onChange={(e) => handleTextChange(e.target.value)}
                            placeholder="e.g. 1.5"
                            style={{
                                width: '100%',
                                backgroundColor: 'var(--color-ec-bg-sidebar)',
                                border: '0.5px solid var(--color-ec-border)',
                                borderRadius: 5,
                                padding: '5px 24px 5px 8px',
                                fontSize: 12,
                                fontWeight: 500,
                                color: 'var(--color-ec-text-primary)',
                                fontFamily: 'var(--color-ec-sans)',
                                outline: 'none',
                            }}
                        />
                        <span style={{
                            position: 'absolute',
                            right: 8,
                            top: '50%',
                            transform: 'translateY(-50%)',
                            fontSize: 11,
                            fontWeight: 700,
                            color: 'var(--color-ec-text-muted)',
                            opacity: 0.6,
                            pointerEvents: 'none',
                            fontFamily: 'var(--color-ec-sans)',
                        }}>
                            M
                        </span>
                    </div>
                ) : isPercent ? (
                    <div style={{ position: 'relative', width: '100%' }}>
                        <input
                            type="number"
                            step="any"
                            value={localText}
                            onChange={(e) => handleTextChange(e.target.value)}
                            placeholder="e.g. 2.5"
                            style={{
                                width: '100%',
                                backgroundColor: 'var(--color-ec-bg-sidebar)',
                                border: '0.5px solid var(--color-ec-border)',
                                borderRadius: 5,
                                padding: '5px 24px 5px 8px',
                                fontSize: 12,
                                fontWeight: 500,
                                color: 'var(--color-ec-text-primary)',
                                fontFamily: 'var(--color-ec-sans)',
                                outline: 'none',
                            }}
                        />
                        <span style={{
                            position: 'absolute',
                            right: 8,
                            top: '50%',
                            transform: 'translateY(-50%)',
                            fontSize: 11,
                            fontWeight: 700,
                            color: 'var(--color-ec-text-muted)',
                            opacity: 0.6,
                            pointerEvents: 'none',
                            fontFamily: 'var(--color-ec-sans)',
                        }}>
                            %
                        </span>
                    </div>
                ) : (
                    <input
                        type="number"
                        value={localText}
                        onChange={(e) => handleTextChange(e.target.value)}
                        placeholder="Value"
                        style={{
                            width: '100%',
                            backgroundColor: 'var(--color-ec-bg-sidebar)',
                            border: '0.5px solid var(--color-ec-border)',
                            borderRadius: 5,
                            padding: '5px 8px',
                            fontSize: 12,
                            fontWeight: 500,
                            color: 'var(--color-ec-text-primary)',
                            fontFamily: 'var(--color-ec-sans)',
                            outline: 'none',
                        }}
                    />
                )
            )}
        </div>
    );
};

// ----------------------------------------------------------------------
// Condition Row Component
// ----------------------------------------------------------------------

export const ConditionRow = ({
    condition,
    onChange,
    onDelete,
    parentTimeframe = Timeframe.M1
}: {
    condition: AnyCondition;
    onChange: (c: AnyCondition) => void;
    onDelete: () => void;
    parentTimeframe?: Timeframe;
}) => {

    const currentTimeframe = condition.timeframe || parentTimeframe;

    const handleSourceChange = (newSource: IndicatorConfig) => {
        if (condition.type === 'indicator_comparison') {
            const allowed = getAllowedTargets(newSource.name as IndicatorType, 'indicator_comparison');
            const currentTargetKey = typeof condition.target === 'number' ? FIXED_VALUE_KEY : (condition.target as IndicatorConfig).name;
            const isTargetAllowed = currentTargetKey === FIXED_VALUE_KEY || allowed.includes(currentTargetKey as IndicatorType);
            
            if (isTriangle(newSource.name)) {
                onChange({
                    ...condition,
                    source: newSource,
                    comparator: Comparator.GT,
                    target: 0
                });
            } else if (newSource.name?.toLowerCase() === 'range of time') {
                onChange({
                    ...condition,
                    source: newSource,
                    comparator: Comparator.LT,
                    target: 30
                });
            } else if (newSource.name === IndicatorType.PM_HIGH_GAP) {
                const isValidComp = [Comparator.LT, Comparator.GT, Comparator.LTE, Comparator.GTE].includes(condition.comparator);
                onChange({
                    ...condition,
                    source: newSource,
                    comparator: isValidComp ? condition.comparator : Comparator.GT,
                    target: typeof condition.target === 'number' ? condition.target : 0
                });
            } else {
                const isCrossAllowed = ALLOWED_CROSSES_INDICATORS.includes(newSource.name as IndicatorType);
                let newComparator = condition.comparator;
                if (!isCrossAllowed && (newComparator === Comparator.CROSSES_ABOVE || newComparator === Comparator.CROSSES_BELOW)) {
                    newComparator = Comparator.GT;
                }
                onChange({
                    ...condition,
                    source: newSource,
                    comparator: newComparator,
                    target: isTargetAllowed ? condition.target : getInitialTargetForSource(newSource.name as IndicatorType)
                });
            }
        } else {
            onChange({ ...condition, source: newSource });
        }
    };

    const handleTargetChange = (newTarget: IndicatorConfig | number) => {
        if (condition.type === 'indicator_comparison') {
            onChange({ ...condition, target: newTarget });
        }
    };

    const renderInputs = () => {
        switch (condition.type) {
            case 'indicator_comparison': {
                const isElapsed = condition.source.name === IndicatorType.ELAPSED_TIME_LAST_HIGH || condition.source.name === IndicatorType.ELAPSED_TIME;
                const isRangeOfTime = condition.source.name?.toLowerCase() === 'range of time';
                return (
                    <>
                        {/* SOURCE: indicator + params */}
                        <SourceIndicatorInput
                            value={condition.source}
                            onChange={handleSourceChange}
                            hideOffset={isElapsed || isRangeOfTime || isTriangle(condition.source.name)}
                            exclude={Object.values(IndicatorType).filter(isOnlyTarget)}
                        />

                        {isElapsed ? (
                            <div className="flex items-center gap-1">
                                <span className="text-xs text-muted-foreground">≥</span>
                                <input
                                    type="number"
                                    min="1"
                                    value={typeof condition.target === 'number' ? condition.target : 20}
                                    onChange={(e) => handleTargetChange(Math.max(1, Number(e.target.value)))}
                                    className="w-16 bg-muted/20 border border-border/50 rounded px-2 py-1 text-xs text-[var(--color-ec-copper)] font-mono outline-none"
                                />
                                <span className="text-xs text-muted-foreground font-semibold">mins</span>
                            </div>
                        ) : isRangeOfTime ? (
                            <div className="flex items-center gap-1.5">
                                {/* COMPARATOR: only <, >, <=, >= */}
                                <select
                                    value={condition.comparator}
                                    onChange={(e) => onChange({ ...condition, comparator: e.target.value as Comparator })}
                                    className="bg-muted/20 border border-border/50 rounded px-2 py-1 text-xs font-mono text-[var(--color-ec-copper)]"
                                >
                                    <option value={Comparator.LT}>&lt;</option>
                                    <option value={Comparator.GT}>&gt;</option>
                                    <option value={Comparator.LTE}>&le;</option>
                                    <option value={Comparator.GTE}>&ge;</option>
                                </select>

                                {/* TARGET VALUE (Minutes) */}
                                <input
                                    type="number"
                                    min="0"
                                    value={typeof condition.target === 'number' ? condition.target : 30}
                                    onChange={(e) => handleTargetChange(Math.max(0, Number(e.target.value)))}
                                    placeholder="Minutos"
                                    className="w-20 bg-muted/20 border border-border/50 rounded px-2 py-1 text-xs text-[var(--color-ec-copper)] font-mono outline-none"
                                />
                                <span className="text-xs text-muted-foreground font-semibold">mins</span>
                            </div>
                        ) : isTriangle(condition.source.name) ? null : (
                            <>
                                {/* COMPARATOR: symbols */}
                                <select
                                    value={condition.comparator}
                                    onChange={(e) => onChange({ ...condition, comparator: e.target.value as Comparator })}
                                    className="bg-muted/20 border border-border/50 rounded px-2 py-1 text-xs font-mono text-[var(--color-ec-copper)]"
                                >
                                    {Object.values(Comparator)
                                        .filter(c => {
                                            if (c.includes('DISTANCE')) return false;
                                            if (condition.source.name === IndicatorType.PM_HIGH_GAP) {
                                                return c === Comparator.LT || c === Comparator.GT || c === Comparator.LTE || c === Comparator.GTE;
                                            }
                                            if (c === Comparator.CROSSES_ABOVE || c === Comparator.CROSSES_BELOW) {
                                                return ALLOWED_CROSSES_INDICATORS.includes(condition.source.name as IndicatorType);
                                            }
                                            return true;
                                        })
                                        .map(c => (
                                            <option key={c} value={c}>{COMPARATOR_LABELS[c] || c}</option>
                                        ))
                                    }
                                </select>

                                {/* TARGET: indicator OR fixed value */}
                                <TargetInput
                                    value={condition.target}
                                    onChange={handleTargetChange}
                                    allowedTargets={getAllowedTargets(condition.source.name as IndicatorType, 'indicator_comparison')}
                                    sourceIndicatorName={condition.source.name}
                                />
                            </>
                        )}
                    </>
                );
            }
            case 'price_level_distance':
                return (
                    <>
                        <SourceIndicatorInput
                            value={condition.source}
                            exclude={[
                                ...Object.values(IndicatorType).filter(isOnlyTarget),
                                IndicatorType.TRIANGLE_ASCENDING,
                                IndicatorType.TRIANGLE_DESCENDING,
                                IndicatorType.TRIANGLE_SYMMETRIC
                            ]}
                            onChange={(val) => onChange({ ...condition, source: val })}
                        />
                        <div className="text-xs text-muted-foreground">is</div>
                        <select
                            value={condition.comparator}
                            onChange={(e) => onChange({ ...condition, comparator: e.target.value as 'DISTANCE_GT' | 'DISTANCE_LT' })}
                            className="bg-muted/20 border border-border/50 rounded px-2 py-1 text-xs font-mono text-[var(--color-ec-copper)]"
                        >
                            <option value="DISTANCE_GT">&gt; than</option>
                            <option value="DISTANCE_LT">&lt; than</option>
                        </select>
                        <div className="flex items-center gap-1">
                            <input
                                type="number"
                                value={condition.value_pct}
                                onChange={(e) => onChange({ ...condition, value_pct: Number(e.target.value) })}
                                className="w-12 bg-muted/20 border border-border/50 rounded px-2 py-1 text-xs text-[var(--color-ec-copper)] font-mono"
                            />
                            <span className="text-[10px] text-muted-foreground">%</span>
                        </div>
                        <div className="text-xs text-muted-foreground">from</div>
                        <SourceIndicatorInput
                            value={condition.level}
                            exclude={[
                                IndicatorType.TRIANGLE_ASCENDING,
                                IndicatorType.TRIANGLE_DESCENDING,
                                IndicatorType.TRIANGLE_SYMMETRIC
                            ]}
                            allowedTargets={getAllowedTargets(
                                condition.source?.name as IndicatorType,
                                'price_level_distance'
                            )}
                            onChange={(val) => onChange({ ...condition, level: val })}
                        />
                        <div className="flex items-center gap-1.5 ml-2 border-l border-border/30 pl-2">
                            <span className="text-[10px] text-muted-foreground uppercase font-bold">Pos:</span>
                            <select
                                value={condition.position || 'any'}
                                onChange={(e) => onChange({ ...condition, position: e.target.value as 'above' | 'below' | 'any' })}
                                className="bg-muted/20 border border-border/50 rounded px-1.5 py-0.5 text-[10px] text-[var(--color-ec-copper)] font-bold"
                            >
                                <option value="any">Any</option>
                                <option value="above">Above Level</option>
                                <option value="below">Below Level</option>
                            </select>
                        </div>
                    </>
                );
            default:
                return null;
        }
    };

    return (
        <div style={{
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            padding: '8px 12px',
            backgroundColor: 'var(--color-ec-bg-elevated)',
            border: '0.5px solid var(--color-ec-border)',
            borderRadius: 5,
            transition: 'border-color 150ms ease',
        }} className="group"
            onMouseEnter={(e) => (e.currentTarget.style.borderColor = 'var(--color-ec-copper)')}
            onMouseLeave={(e) => (e.currentTarget.style.borderColor = 'var(--color-ec-border)')}
        >
            {/* Timeframe Selector */}
            <div style={{
                display: 'flex',
                alignItems: 'center',
                gap: 5,
                padding: '3px 8px',
                backgroundColor: 'var(--color-ec-bg-sidebar)',
                border: '0.5px solid var(--color-ec-border)',
                borderRadius: 4,
            }}>
                <Clock className="w-3 h-3 text-[var(--color-ec-copper)]" />
                <select
                    value={currentTimeframe}
                    onChange={(e) => onChange({ ...condition, timeframe: e.target.value as Timeframe })}
                    style={{
                        background: 'transparent',
                        border: 'none',
                        outline: 'none',
                        fontSize: 11,
                        fontWeight: 700,
                        color: 'var(--color-ec-copper)',
                        fontFamily: 'var(--color-ec-sans)',
                        cursor: 'pointer',
                    }}
                >
                    {Object.values(Timeframe).filter(tf => tf !== Timeframe.D1).map(tf => (
                        <option key={tf} value={tf}>{tf}</option>
                    ))}
                </select>
            </div>

            <div style={{
                width: 1,
                height: 16,
                backgroundColor: 'var(--color-ec-border)',
                flexShrink: 0,
            }}></div>

            <select
                value={condition.type}
                onChange={(e) => {
                    const type = e.target.value;
                    if (type === 'indicator_comparison') {
                        onChange({
                            type: 'indicator_comparison',
                            source: { name: IndicatorType.SMA, period: 20 },
                            comparator: Comparator.GT,
                            target: { name: IndicatorType.VWAP },
                            timeframe: currentTimeframe
                        });
                    } else if (type === 'price_level_distance') {
                        onChange({
                            type: 'price_level_distance',
                            source: { name: IndicatorType.BAR_CLOSE, offset: 0 },
                            level: { name: IndicatorType.PM_HIGH, offset: 0 },
                            comparator: 'DISTANCE_LT',
                            value_pct: 2.0,
                            timeframe: currentTimeframe
                        });
                    }
                }}
                style={{
                    background: 'transparent',
                    border: 'none',
                    outline: 'none',
                    fontSize: 11,
                    fontWeight: 700,
                    textTransform: 'uppercase',
                    letterSpacing: '0.08em',
                    color: 'var(--color-ec-text-secondary)',
                    fontFamily: 'var(--color-ec-sans)',
                    cursor: 'pointer',
                }}
            >
                <option value="indicator_comparison">Indicator</option>
                <option value="price_level_distance">Distance</option>
            </select>

            <div style={{
                width: 1,
                height: 16,
                backgroundColor: 'var(--color-ec-border)',
                flexShrink: 0,
            }}></div>

            <div className="flex items-center gap-2 flex-1 flex-wrap">
                {renderInputs()}
            </div>

            <button onClick={onDelete} className="text-muted-foreground hover:text-ec-loss opacity-0 group-hover:opacity-100 transition-opacity">
                <Trash2 className="w-3.5 h-3.5" />
            </button>
        </div>
    );
};

// ----------------------------------------------------------------------
// Recursive Group Component
// ----------------------------------------------------------------------
export const formatConditionText = (c: AnyCondition): string => {
    const tfStr = c.timeframe ? `[${c.timeframe}]` : '';
    if (c.type === 'indicator_comparison') {
        if (c.source.name === IndicatorType.ELAPSED_TIME_LAST_HIGH) {
            const mins = typeof c.target === 'number' ? c.target : 20;
            return `${tfStr} Elapsed Time Last High ≥ ${mins} mins`;
        }
        if (c.source.name === IndicatorType.ELAPSED_TIME) {
            const mins = typeof c.target === 'number' ? c.target : 60;
            return `${tfStr} Elapsed Time = ${mins} mins`;
        }
        const sourceStr = `${INDICATOR_LABELS[c.source.name] || c.source.name}${c.source.offset ? `[t-${c.source.offset}]` : ''}`;
        const compStr = COMPARATOR_LABELS[c.comparator] || c.comparator;
        let targetStr = '';
        if (typeof c.target === 'number') {
            if (isVolumeIndicator(c.source.name)) {
                targetStr = `${(c.target / 1000000).toString()}M`;
            } else if (c.source.name === IndicatorType.PM_HIGH_GAP) {
                targetStr = `${c.target}%`;
            } else {
                targetStr = String(c.target);
            }
        } else {
            targetStr = `${INDICATOR_LABELS[c.target.name] || c.target.name}${c.target.offset ? `[t-${c.target.offset}]` : ''}`;
        }
        return `${tfStr} ${sourceStr} ${compStr} ${targetStr}`;
    } else if (c.type === 'price_level_distance') {
        const sourceStr = `${INDICATOR_LABELS[c.source.name] || c.source.name}${c.source.offset ? `[t-${c.source.offset}]` : ''}`;
        const levelStr = `${INDICATOR_LABELS[c.level.name] || c.level.name}${c.level.offset ? `[t-${c.level.offset}]` : ''}`;
        const compStr = c.comparator === 'DISTANCE_GT' ? '>' : '<';
        const pctStr = `${c.value_pct}%`;
        const posStr = c.position && c.position !== 'any' ? ` (${c.position})` : '';
        return `${tfStr} Dist(${sourceStr}, ${levelStr}) ${compStr} ${pctStr}${posStr}`;
    }
    return '';
};

export const GroupDisplay = ({
    group,
    onChange,
    onDelete,
    level = 0,
    accentColor = 'blue',
    parentTimeframe = Timeframe.M1
}: {
    group: ConditionGroup;
    onChange: (g: ConditionGroup) => void;
    onDelete?: () => void;
    level?: number;
    accentColor?: 'blue' | 'rose' | 'amber';
    parentTimeframe?: Timeframe;
}) => {
    const [showForm, setShowForm] = React.useState(false);
    const [editingIndex, setEditingIndex] = React.useState<number | null>(null);
    const [formCondition, setFormCondition] = React.useState<AnyCondition>({
        type: 'indicator_comparison',
        source: { name: IndicatorType.BAR_CLOSE, offset: 0 },
        comparator: Comparator.GT,
        target: { name: IndicatorType.VWAP, offset: 0 },
    });
    
    const compCondition = formCondition.type === 'indicator_comparison' ? formCondition : null;
    const distCondition = formCondition.type === 'price_level_distance' ? formCondition : null;
    const activeAccentColor = accentColor === 'blue' ? 'var(--color-ec-profit)' : accentColor === 'rose' ? 'var(--color-ec-loss)' : 'var(--color-ec-copper)';

    const handleToggleType = (newType: 'indicator_comparison' | 'price_level_distance') => {
        if (newType === 'indicator_comparison') {
            const allowed = getAllowedTargets(formCondition.source.name as IndicatorType, 'indicator_comparison');
            const defaultTarget = allowed.includes(IndicatorType.VWAP)
                ? { name: IndicatorType.VWAP, offset: 0 }
                : allowed.length > 0
                    ? { name: allowed[0], offset: 0 }
                    : 0;

            setFormCondition({
                type: 'indicator_comparison',
                source: { ...formCondition.source, offset: 0 },
                comparator: Comparator.GT,
                target: defaultTarget,
                timeframe: formCondition.timeframe
            });
        } else {
            const allowed = getAllowedTargets(formCondition.source.name as IndicatorType, 'price_level_distance');
            const defaultLevel = allowed.includes(IndicatorType.PM_HIGH)
                ? { name: IndicatorType.PM_HIGH, offset: 0 }
                : allowed.length > 0
                    ? { name: allowed[0], offset: 0 }
                    : { name: IndicatorType.PM_HIGH, offset: 0 };

            setFormCondition({
                type: 'price_level_distance',
                source: { ...formCondition.source, offset: 0 },
                level: defaultLevel,
                comparator: 'DISTANCE_LT',
                value_pct: 2.0,
                timeframe: formCondition.timeframe
            });
        }
    };

    const handleSaveCondition = () => {
        const savedCondition = {
            ...formCondition,
            source: {
                ...formCondition.source,
                offset: 0
            }
        };
        if (editingIndex !== null) {
            const newConditions = [...group.conditions];
            newConditions[editingIndex] = savedCondition;
            onChange({ ...group, conditions: newConditions });
            setEditingIndex(null);
        } else {
            onChange({
                ...group,
                conditions: [...group.conditions, savedCondition]
            });
        }
        setShowForm(false);
    };

    const handleRemoveCondition = (indexInAll: number) => {
        const newConditions = group.conditions.filter((_, i) => i !== indexInAll);
        onChange({ ...group, conditions: newConditions });
        if (editingIndex === indexInAll) {
            setEditingIndex(null);
            setShowForm(false);
        }
    };

    const addGroup = () => {
        const newGroup: ConditionGroup = {
            type: 'group',
            operator: 'AND',
            conditions: []
        };
        onChange({
            ...group,
            conditions: [...group.conditions, newGroup]
        });
    };

    const updateCondition = (index: number, newCond: AnyCondition | ConditionGroup) => {
        const newConditions = [...group.conditions];
        newConditions[index] = newCond;
        onChange({ ...group, conditions: newConditions });
    };

    const removeCondition = (index: number) => {
        const newConditions = group.conditions.filter((_, i) => i !== index);
        onChange({ ...group, conditions: newConditions });
    };

    const labelStyle: React.CSSProperties = {
        fontFamily: 'var(--color-ec-sans)',
        fontSize: '9px',
        fontWeight: 700,
        textTransform: 'uppercase',
        letterSpacing: '0.05em',
        color: 'var(--color-ec-text-muted)',
        marginBottom: '2px',
    };

    const inputStyle: React.CSSProperties = {
        backgroundColor: 'var(--color-ec-bg-sidebar)',
        border: '0.5px solid var(--color-ec-border)',
        borderRadius: '4px',
        padding: '5px 8px',
        fontSize: '11px',
        fontWeight: 500,
        color: 'var(--color-ec-text-primary)',
        fontFamily: 'var(--color-ec-sans)',
        outline: 'none',
        width: '100%',
    };

    const selectStyle: React.CSSProperties = {
        backgroundColor: 'var(--color-ec-bg-sidebar)',
        border: '0.5px solid var(--color-ec-border)',
        borderRadius: '4px',
        padding: '5px 8px',
        fontSize: '11px',
        fontWeight: 500,
        color: 'var(--color-ec-text-primary)',
        fontFamily: 'var(--color-ec-sans)',
        outline: 'none',
        width: '100%',
        cursor: 'pointer',
    };

    const subGroups = group.conditions.filter(c => c.type === 'group') as ConditionGroup[];

    return (
        <div 
            style={{
                display: 'flex',
                flexDirection: 'column',
                gap: 12,
                position: 'relative',
                marginLeft: level > 0 ? 16 : 0,
                paddingLeft: level > 0 ? 16 : 0,
                paddingRight: level > 0 ? 12 : 0,
                paddingTop: level > 0 ? 12 : 0,
                paddingBottom: level > 0 ? 12 : 0,
                borderLeft: level > 0 ? `2.5px solid ${activeAccentColor}` : 'none',
                backgroundColor: level > 0 ? 'color-mix(in srgb, var(--color-ec-bg-surface) 40%, transparent)' : 'transparent',
                borderRadius: level > 0 ? '0 6px 6px 0' : 0,
                borderTop: level > 0 ? '0.5px solid var(--color-ec-border)' : 'none',
                borderBottom: level > 0 ? '0.5px solid var(--color-ec-border)' : 'none',
                borderRight: level > 0 ? '0.5px solid var(--color-ec-border)' : 'none',
            }}
        >
            {/* Group Header */}
            <div className="flex items-center gap-3">
                <div
                    style={group.operator === 'AND' ? {
                        backgroundColor: `color-mix(in srgb, ${activeAccentColor} 15%, transparent)`,
                        color: activeAccentColor,
                        fontFamily: 'var(--color-ec-sans)',
                        fontSize: 10,
                        fontWeight: 700,
                        textTransform: 'uppercase',
                        letterSpacing: '0.1em',
                        padding: '3px 10px',
                        borderRadius: 4,
                        cursor: 'pointer',
                        border: 'none',
                    } : {
                        fontSize: 10,
                        fontWeight: 700,
                        textTransform: 'uppercase',
                        letterSpacing: '0.1em',
                        padding: '3px 10px',
                        borderRadius: 4,
                        cursor: 'pointer',
                        border: 'none',
                        color: 'var(--color-ec-text-secondary)',
                        fontFamily: 'var(--color-ec-sans)',
                        backgroundColor: 'transparent',
                    }}
                    onClick={() => onChange({ ...group, operator: group.operator === 'AND' ? 'OR' : 'AND' })}
                >
                    {group.operator}
                </div>

                {level > 0 && (
                    <span style={{
                        fontSize: 9,
                        fontWeight: 700,
                        textTransform: 'uppercase',
                        color: activeAccentColor,
                        letterSpacing: '0.08em',
                        fontFamily: 'var(--color-ec-sans)',
                        backgroundColor: `color-mix(in srgb, ${activeAccentColor} 10%, transparent)`,
                        padding: '2px 6px',
                        borderRadius: 3,
                    }}>
                        Grupo Lógico
                    </span>
                )}

                {onDelete && (
                    <button onClick={onDelete} className="ml-auto text-muted-foreground/30 hover:text-ec-loss transition-colors">
                        <Trash2 className="w-3.5 h-3.5" />
                    </button>
                )}
            </div>

            {/* Config & Tags Row */}
            <div style={{
                display: 'flex',
                flexDirection: 'row',
                gap: 16,
                alignItems: 'flex-start',
                width: '100%',
            }}>
                {/* Left side: Buttons or Vertical Form */}
                <div style={{
                    width: 250,
                    display: 'flex',
                    flexDirection: 'column',
                    gap: 10,
                    flexShrink: 0,
                }}>
                    {showForm ? (
                        <div style={{
                            display: 'flex',
                            flexDirection: 'column',
                            gap: 10,
                            padding: 12,
                            border: `0.5px solid ${activeAccentColor}`,
                            backgroundColor: 'var(--color-ec-bg-surface)',
                            borderRadius: 6,
                        }}>
                            {/* Form Header */}
                            <div style={{
                                display: 'flex',
                                justifyContent: 'space-between',
                                alignItems: 'center',
                                borderBottom: '0.5px solid var(--color-ec-border)',
                                paddingBottom: 6,
                                marginBottom: 4
                            }}>
                                <span style={{
                                    fontSize: 10,
                                    fontWeight: 700,
                                    textTransform: 'uppercase',
                                    color: activeAccentColor,
                                    letterSpacing: '0.08em',
                                    fontFamily: 'var(--color-ec-sans)',
                                }}>
                                    {editingIndex !== null ? 'Editar Condición' : 'Nueva Condición'}
                                </span>
                            </div>

                            {/* Timeframe selector (Tiempo) */}
                            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                                <span style={labelStyle}>Tiempo</span>
                                <select
                                    value={formCondition.timeframe || parentTimeframe}
                                    onChange={(e) => setFormCondition({ ...formCondition, timeframe: e.target.value as Timeframe })}
                                    style={selectStyle}
                                >
                                    {Object.values(Timeframe).filter(tf => tf !== Timeframe.D1).map(tf => (
                                        <option key={tf} value={tf}>{tf}</option>
                                    ))}
                                </select>
                            </div>

                            {/* Variable de entrada */}
                            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                                <span style={labelStyle}>Variable de entrada</span>
                                <IndicatorSelector
                                    value={formCondition.source.name}
                                    exclude={[
                                        ...Object.values(IndicatorType).filter(isOnlyTarget),
                                        ...(accentColor !== 'rose' ? [IndicatorType.ELAPSED_TIME] : [])
                                    ]}
                                    onChange={(nameStr) => {
                                        const name = nameStr as IndicatorType;
                                        const defaultParams = getDefaultParamsForIndicator(name);
                                        const timeframe = formCondition.timeframe;

                                        if (name === IndicatorType.ELAPSED_TIME_LAST_HIGH) {
                                            setFormCondition({
                                                type: 'indicator_comparison',
                                                source: { name, offset: 0 },
                                                comparator: Comparator.GTE,
                                                target: 20,
                                                timeframe
                                            });
                                            return;
                                        }
                                        if (name === IndicatorType.ELAPSED_TIME) {
                                            setFormCondition({
                                                type: 'indicator_comparison',
                                                source: { name, offset: 0 },
                                                comparator: Comparator.GTE,
                                                target: 60,
                                                timeframe
                                            });
                                            return;
                                        }
                                        if (name?.toLowerCase() === 'range of time') {
                                            setFormCondition({
                                                type: 'indicator_comparison',
                                                source: { name, offset: 0 },
                                                comparator: Comparator.LT,
                                                target: 30,
                                                timeframe
                                            });
                                            return;
                                        }

                                        // Check if distance is supported
                                        const hasDistance = getAllowedTargets(name, 'price_level_distance').length > 0;
                                        
                                        // If we are in distance mode but the new indicator doesn't support it, switch to comparison mode
                                        if (formCondition.type === 'price_level_distance' && !hasDistance) {
                                            const allowed = getAllowedTargets(name, 'indicator_comparison');
                                            const defaultTarget = allowed.includes(IndicatorType.VWAP)
                                                ? { name: IndicatorType.VWAP, offset: 0 }
                                                : allowed.length > 0
                                                    ? { name: allowed[0], offset: 0 }
                                                    : 0;
                                            
                                            setFormCondition({
                                                type: 'indicator_comparison',
                                                source: { name, offset: 0, ...defaultParams },
                                                comparator: Comparator.GT,
                                                target: defaultTarget,
                                                timeframe
                                            });
                                        } else if (formCondition.type === 'indicator_comparison') {
                                            const allowed = getAllowedTargets(name, 'indicator_comparison');
                                            const currentTargetKey = typeof formCondition.target === 'number' ? FIXED_VALUE_KEY : (formCondition.target as IndicatorConfig).name;
                                            const isTargetAllowed = currentTargetKey === FIXED_VALUE_KEY || allowed.includes(currentTargetKey as IndicatorType);
                                            
                                            const isCrossAllowed = ALLOWED_CROSSES_INDICATORS.includes(name);
                                            let newComparator = formCondition.comparator;
                                            if (!isCrossAllowed && (newComparator === Comparator.CROSSES_ABOVE || newComparator === Comparator.CROSSES_BELOW)) {
                                                newComparator = Comparator.GT;
                                            }

                                            setFormCondition({
                                                type: 'indicator_comparison',
                                                source: { name, offset: 0, ...defaultParams },
                                                comparator: newComparator as Comparator,
                                                target: isTargetAllowed ? formCondition.target : getInitialTargetForSource(name),
                                                timeframe
                                            });
                                        } else {
                                            // We are in price_level_distance and the new indicator does support distance
                                            const allowed = getAllowedTargets(name, 'price_level_distance');
                                            const currentLevelKey = (formCondition.level as IndicatorConfig).name;
                                            const isLevelAllowed = allowed.includes(currentLevelKey);
                                            const defaultLevel = allowed.includes(IndicatorType.PM_HIGH)
                                                ? { name: IndicatorType.PM_HIGH, offset: 0 }
                                                : allowed.length > 0
                                                    ? { name: allowed[0], offset: 0 }
                                                    : { name: IndicatorType.PM_HIGH, offset: 0 };

                                            setFormCondition({
                                                type: 'price_level_distance',
                                                source: { name, offset: 0, ...defaultParams },
                                                level: isLevelAllowed ? formCondition.level : defaultLevel,
                                                comparator: formCondition.comparator as 'DISTANCE_GT' | 'DISTANCE_LT',
                                                value_pct: formCondition.value_pct,
                                                timeframe
                                            });
                                        }
                                    }}
                                />
                                <IndicatorParams
                                    value={formCondition.source}
                                    onChange={(newSource) => setFormCondition({ ...formCondition, source: newSource })}
                                    hideOffset={true}
                                />
                            </div>

                            {/* Mode toggle (Comparación vs Distancia %) if supported */}
                            {(() => {
                                const hasDistance = getAllowedTargets(formCondition.source.name as IndicatorType, 'price_level_distance').length > 0;
                                if (!hasDistance) return null;
                                return (
                                    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                                        <span style={labelStyle}>Modo de Condición</span>
                                        <div style={{
                                            display: 'flex',
                                            backgroundColor: 'var(--color-ec-bg-sidebar)',
                                            border: '0.5px solid var(--color-ec-border)',
                                            borderRadius: 6,
                                            padding: 2,
                                            position: 'relative'
                                        }}>
                                            <button
                                                type="button"
                                                onClick={() => handleToggleType('indicator_comparison')}
                                                style={{
                                                    flex: 1,
                                                    padding: '6px 10px',
                                                    fontSize: 11,
                                                    fontWeight: 700,
                                                    borderRadius: 4,
                                                    border: 'none',
                                                    backgroundColor: formCondition.type === 'indicator_comparison' ? 'var(--color-ec-copper)' : 'transparent',
                                                    color: formCondition.type === 'indicator_comparison' ? '#ffffff' : 'var(--color-ec-text-muted)',
                                                    cursor: 'pointer',
                                                    transition: 'all 150ms ease',
                                                    textAlign: 'center'
                                                }}
                                            >
                                                Comparación
                                            </button>
                                            <button
                                                type="button"
                                                onClick={() => handleToggleType('price_level_distance')}
                                                style={{
                                                    flex: 1,
                                                    padding: '6px 10px',
                                                    fontSize: 11,
                                                    fontWeight: 700,
                                                    borderRadius: 4,
                                                    border: 'none',
                                                    backgroundColor: formCondition.type === 'price_level_distance' ? 'var(--color-ec-copper)' : 'transparent',
                                                    color: formCondition.type === 'price_level_distance' ? '#ffffff' : 'var(--color-ec-text-muted)',
                                                    cursor: 'pointer',
                                                    transition: 'all 150ms ease',
                                                    textAlign: 'center'
                                                }}
                                            >
                                                Distancia %
                                            </button>
                                        </div>
                                    </div>
                                );
                            })()}



                            {/* relación */}
                            {!isTriangle(formCondition.source.name) && formCondition.source.name !== IndicatorType.ELAPSED_TIME_LAST_HIGH && formCondition.source.name !== IndicatorType.ELAPSED_TIME && (
                                <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                                    <span style={labelStyle}>Relación</span>
                                    {formCondition.source.name?.toLowerCase() === 'range of time' ? (
                                        <select
                                            value={compCondition ? compCondition.comparator : Comparator.LT}
                                            onChange={(e) => {
                                                if (compCondition) {
                                                    setFormCondition({
                                                        ...compCondition,
                                                        comparator: e.target.value as Comparator
                                                    });
                                                }
                                            }}
                                            style={selectStyle}
                                        >
                                            <option value={Comparator.LT}>&lt;</option>
                                            <option value={Comparator.GT}>&gt;</option>
                                            <option value={Comparator.LTE}>&le;</option>
                                            <option value={Comparator.GTE}>&ge;</option>
                                        </select>
                                    ) : formCondition.type === 'indicator_comparison' ? (
                                        <select
                                            value={compCondition ? compCondition.comparator : Comparator.GT}
                                            onChange={(e) => {
                                                if (compCondition) {
                                                    setFormCondition({
                                                        ...compCondition,
                                                        comparator: e.target.value as Comparator
                                                    });
                                                }
                                            }}
                                            style={selectStyle}
                                        >
                                            {Object.values(Comparator)
                                                .filter(c => {
                                                    if (c.includes('DISTANCE')) return false;
                                                    if (c === Comparator.CROSSES_ABOVE || c === Comparator.CROSSES_BELOW) {
                                                        const sourceName = compCondition ? compCondition.source.name : formCondition.source.name;
                                                        return ALLOWED_CROSSES_INDICATORS.includes(sourceName as IndicatorType);
                                                    }
                                                    return true;
                                                })
                                                .map(c => (
                                                    <option key={c} value={c}>{COMPARATOR_LABELS[c] || c}</option>
                                                ))
                                            }
                                        </select>
                                    ) : (
                                        <select
                                            value={formCondition.type === 'price_level_distance' ? formCondition.comparator : 'DISTANCE_GT'}
                                            onChange={(e) => {
                                                if (formCondition.type === 'price_level_distance') {
                                                    setFormCondition({
                                                        ...formCondition,
                                                        comparator: e.target.value as 'DISTANCE_GT' | 'DISTANCE_LT'
                                                    });
                                                }
                                            }}
                                            style={selectStyle}
                                        >
                                            <option value="DISTANCE_GT">&gt; que</option>
                                            <option value="DISTANCE_LT">&lt; que</option>
                                        </select>
                                    )}
                                </div>
                            )}

                            {/* Variables de cruce */}
                            {formCondition.source.name === IndicatorType.ELAPSED_TIME_LAST_HIGH || formCondition.source.name === IndicatorType.ELAPSED_TIME ? (
                                <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                                    <span style={labelStyle}>Tiempo Transcurrido</span>
                                    <div style={{ position: 'relative', display: 'flex', alignItems: 'center' }}>
                                        <input
                                            type="number"
                                            min="1"
                                            value={compCondition && typeof compCondition.target === 'number' ? compCondition.target : (formCondition.source.name === IndicatorType.ELAPSED_TIME ? 60 : 20)}
                                            onChange={(e) => {
                                                if (compCondition) {
                                                    setFormCondition({
                                                        ...compCondition,
                                                        type: 'indicator_comparison',
                                                        target: Math.max(1, Number(e.target.value))
                                                    });
                                                }
                                            }}
                                            style={{ ...inputStyle, width: '100%', paddingRight: 40 }}
                                        />
                                        <span style={{
                                            position: 'absolute',
                                            right: 8,
                                            fontSize: 10,
                                            fontWeight: 600,
                                            color: 'var(--color-ec-text-muted)',
                                            pointerEvents: 'none'
                                        }}>mins</span>
                                    </div>
                                </div>
                            ) : formCondition.source.name?.toLowerCase() === 'range of time' ? (
                                <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                                    <span style={labelStyle}>Minutos del rango</span>
                                    <input
                                        type="number"
                                        min="0"
                                        value={compCondition && typeof compCondition.target === 'number' ? compCondition.target : 30}
                                        onChange={(e) => {
                                            if (compCondition) {
                                                setFormCondition({
                                                    ...compCondition,
                                                    type: 'indicator_comparison',
                                                    target: Math.max(0, Number(e.target.value))
                                                });
                                            }
                                        }}
                                        style={inputStyle}
                                    />
                                </div>
                            ) : compCondition && !isTriangle(formCondition.source.name) ? (
                                <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                                    <span style={labelStyle}>Variables de cruce</span>
                                    <TargetInput
                                        value={compCondition.target}
                                        onChange={(newTarget) => setFormCondition({
                                            ...compCondition,
                                            type: 'indicator_comparison',
                                            target: newTarget
                                        })}
                                        allowedTargets={getAllowedTargets(formCondition.source.name as IndicatorType, 'indicator_comparison')}
                                        hideOffset={true}
                                        sourceIndicatorName={formCondition.source.name}
                                    />
                                </div>
                            ) : distCondition ? (
                                <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                                    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                                        <span style={labelStyle}>Distancia %</span>
                                        <input
                                            type="number"
                                            step="0.1"
                                            value={distCondition.value_pct}
                                            onChange={(e) => setFormCondition({
                                                ...distCondition,
                                                type: 'price_level_distance',
                                                value_pct: Number(e.target.value)
                                            })}
                                            style={inputStyle}
                                        />
                                    </div>
                                    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                                        <span style={labelStyle}>Variables de cruce (Nivel)</span>
                                        <IndicatorSelector
                                            value={distCondition.level.name}
                                            exclude={[
                                                IndicatorType.TRIANGLE_ASCENDING,
                                                IndicatorType.TRIANGLE_DESCENDING,
                                                IndicatorType.TRIANGLE_SYMMETRIC
                                            ]}
                                            allowedTargets={getAllowedTargets(distCondition.source.name as IndicatorType, 'price_level_distance')}
                                            onChange={(nameStr) => {
                                                const name = nameStr as IndicatorType;
                                                const defaultParams = getDefaultParamsForIndicator(name);
                                                setFormCondition({
                                                    ...distCondition,
                                                    type: 'price_level_distance',
                                                    level: { name, offset: distCondition.level.offset, ...defaultParams }
                                                });
                                            }}
                                        />
                                        <IndicatorParams
                                            value={distCondition.level}
                                            onChange={(newLevel) => setFormCondition({
                                                ...distCondition,
                                                type: 'price_level_distance',
                                                level: newLevel
                                            })}
                                            hideOffset={true}
                                        />
                                    </div>
                                    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                                        <span style={labelStyle}>Posición</span>
                                        <select
                                            value={distCondition.position || 'any'}
                                            onChange={(e) => setFormCondition({
                                                ...distCondition,
                                                type: 'price_level_distance',
                                                position: e.target.value as 'above' | 'below' | 'any'
                                            })}
                                            style={selectStyle}
                                        >
                                            <option value="any">Cualquiera (Any)</option>
                                            <option value="above">Por encima del nivel</option>
                                            <option value="below">Por debajo del nivel</option>
                                        </select>
                                    </div>
                                </div>
                            ) : null}

                            {/* Checkbox for Offset to Variable de cruce */}
                            {((formCondition.type === 'indicator_comparison' && typeof formCondition.target !== 'number') || 
                              formCondition.type === 'price_level_distance') && (
                                <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 4 }}>
                                    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                                        <input
                                            type="checkbox"
                                            id="offset-checkbox"
                                            checked={
                                                formCondition.type === 'indicator_comparison'
                                                    ? !!(formCondition.target as IndicatorConfig).offset
                                                    : !!formCondition.level.offset
                                            }
                                            onChange={(e) => {
                                                const checked = e.target.checked;
                                                if (formCondition.type === 'indicator_comparison') {
                                                    const target = formCondition.target as IndicatorConfig;
                                                    setFormCondition({
                                                        ...formCondition,
                                                        target: {
                                                            ...target,
                                                            offset: checked ? (target.offset || 1) : 0
                                                        }
                                                    });
                                                } else {
                                                    setFormCondition({
                                                        ...formCondition,
                                                        level: {
                                                            ...formCondition.level,
                                                            offset: checked ? (formCondition.level.offset || 1) : 0
                                                        }
                                                    });
                                                }
                                            }}
                                            style={{
                                                width: 14,
                                                height: 14,
                                                accentColor: 'var(--color-ec-copper)',
                                                cursor: 'pointer'
                                            }}
                                        />
                                        <label
                                            htmlFor="offset-checkbox"
                                            style={{
                                                fontSize: 11,
                                                fontWeight: 600,
                                                color: 'var(--color-ec-text-primary)',
                                                cursor: 'pointer',
                                                userSelect: 'none'
                                            }}
                                        >
                                            ¿Offset a Variable de cruce?
                                        </label>
                                        <TooltipIcon
                                            customText="Compara la variable de entrada con el valor de la variable de cruce de X velas hacia atrás. Ejemplo: Si Bar Close > SMA_30 y le indicamos un offset de 3 velas, el Bar Close Actual comparará si es mayor que el valor del SMA_30 de hace 3 velas y no del actual"
                                        />
                                    </div>

                                    {/* Mostrar select de velas de retraso si el checkbox está activo */}
                                    {!!((formCondition.type === 'indicator_comparison' && typeof formCondition.target !== 'number' && (formCondition.target as IndicatorConfig).offset) ||
                                      (formCondition.type === 'price_level_distance' && formCondition.level.offset)) && (
                                        <div style={{ 
                                            display: 'flex', 
                                            alignItems: 'center', 
                                            gap: 8, 
                                            paddingLeft: 20,
                                            marginTop: 2
                                        }}>
                                            <span style={{
                                                fontSize: 11,
                                                fontWeight: 600,
                                                color: 'var(--color-ec-text-secondary)',
                                                fontFamily: 'var(--color-ec-sans)',
                                            }}>Velas atrás:</span>
                                            <select
                                                value={
                                                    formCondition.type === 'indicator_comparison'
                                                        ? (formCondition.target as IndicatorConfig).offset || 1
                                                        : formCondition.level.offset || 1
                                                }
                                                onChange={(e) => {
                                                    const val = Number(e.target.value);
                                                    if (formCondition.type === 'indicator_comparison') {
                                                        const target = formCondition.target as IndicatorConfig;
                                                        setFormCondition({
                                                            ...formCondition,
                                                            target: { ...target, offset: val }
                                                        });
                                                    } else {
                                                        setFormCondition({
                                                            ...formCondition,
                                                            level: { ...formCondition.level, offset: val }
                                                        });
                                                    }
                                                }}
                                                style={{
                                                    backgroundColor: 'var(--color-ec-bg-sidebar)',
                                                    border: '0.5px solid var(--color-ec-border)',
                                                    borderRadius: 4,
                                                    padding: '2px 8px 2px 6px',
                                                    fontSize: 11,
                                                    fontWeight: 700,
                                                    color: 'var(--color-ec-copper)',
                                                    fontFamily: 'var(--color-ec-sans)',
                                                    outline: 'none',
                                                    cursor: 'pointer',
                                                    width: 55,
                                                    textAlign: 'center'
                                                }}
                                            >
                                                {Array.from({ length: 20 }, (_, i) => i + 1).map((val) => (
                                                    <option key={val} value={val} style={{ backgroundColor: 'var(--color-ec-bg-surface)', color: 'var(--color-ec-text-primary)' }}>
                                                        {val}
                                                    </option>
                                                ))}
                                            </select>
                                        </div>
                                    )}
                                </div>
                            )}

                            {/* Save/Cancel buttons */}
                            <div style={{ display: 'flex', gap: 8, marginTop: 4 }}>
                                <button
                                    onClick={handleSaveCondition}
                                    style={{
                                        flex: 1,
                                        padding: '6px 12px',
                                        backgroundColor: activeAccentColor,
                                        border: 'none',
                                        borderRadius: 4,
                                        fontSize: 11,
                                        fontWeight: 700,
                                        color: '#ffffff',
                                        cursor: 'pointer',
                                    }}
                                >
                                    {editingIndex !== null ? 'Guardar' : 'Añadir'}
                                </button>
                                <button
                                    onClick={() => {
                                        setShowForm(false);
                                        setEditingIndex(null);
                                    }}
                                    style={{
                                        flex: 1,
                                        padding: '6px 12px',
                                        backgroundColor: 'transparent',
                                        border: '0.5px solid var(--color-ec-border)',
                                        borderRadius: 4,
                                        fontSize: 11,
                                        fontWeight: 600,
                                        color: 'var(--color-ec-text-muted)',
                                        cursor: 'pointer',
                                    }}
                                >
                                    Cancelar
                                </button>
                            </div>
                        </div>
                    ) : (
                        <div className="flex gap-2">
                            <button
                                onClick={() => {
                                    setEditingIndex(null);
                                    setFormCondition({
                                        type: 'indicator_comparison',
                                        source: { name: IndicatorType.BAR_CLOSE, offset: 0 },
                                        comparator: Comparator.GT,
                                        target: { name: IndicatorType.VWAP, offset: 0 },
                                        timeframe: parentTimeframe
                                    });
                                    setShowForm(true);
                                }}
                                style={{
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: 5,
                                    padding: '6px 12px',
                                    backgroundColor: 'transparent',
                                    border: '0.5px dashed var(--color-ec-border)',
                                    borderRadius: 5,
                                    fontSize: 11,
                                    fontWeight: 600,
                                    color: 'var(--color-ec-text-muted)',
                                    fontFamily: 'var(--color-ec-sans)',
                                    cursor: 'pointer',
                                    transition: 'border-color 150ms ease, color 150ms ease',
                                    flex: 1,
                                    justifyContent: 'center',
                                }}
                                onMouseEnter={(e) => { e.currentTarget.style.borderColor = activeAccentColor; e.currentTarget.style.color = activeAccentColor; }}
                                onMouseLeave={(e) => { e.currentTarget.style.borderColor = 'var(--color-ec-border)'; e.currentTarget.style.color = 'var(--color-ec-text-muted)'; }}
                            >
                                <Plus className="w-3 h-3" />
                                Condición
                            </button>
                            <button
                                onClick={addGroup}
                                style={{
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: 5,
                                    padding: '6px 12px',
                                    backgroundColor: 'transparent',
                                    border: '0.5px dashed var(--color-ec-border)',
                                    borderRadius: 5,
                                    fontSize: 11,
                                    fontWeight: 600,
                                    color: 'var(--color-ec-text-muted)',
                                    fontFamily: 'var(--color-ec-sans)',
                                    cursor: 'pointer',
                                    transition: 'border-color 150ms ease, color 150ms ease',
                                    flex: 1,
                                    justifyContent: 'center',
                                }}
                                onMouseEnter={(e) => { e.currentTarget.style.borderColor = activeAccentColor; e.currentTarget.style.color = activeAccentColor; }}
                                onMouseLeave={(e) => { e.currentTarget.style.borderColor = 'var(--color-ec-border)'; e.currentTarget.style.color = 'var(--color-ec-text-muted)'; }}
                            >
                                <GitBranch className="w-3 h-3" />
                                Grupo Lógico
                            </button>
                        </div>
                    )}
                </div>

                {/* Right side: Line of Tags */}
                <div style={{
                    flex: 1,
                    display: 'flex',
                    flexWrap: 'wrap',
                    gap: 6,
                    paddingTop: showForm ? 0 : 4,
                }}>
                    {group.conditions.map((cond, idx) => {
                        if (cond.type === 'group') return null;
                        return (
                            <div 
                                key={idx} 
                                onClick={() => {
                                    setEditingIndex(idx);
                                    setFormCondition(cond);
                                    setShowForm(true);
                                }}
                                style={{
                                    display: 'inline-flex',
                                    alignItems: 'center',
                                    gap: 6,
                                    padding: '4px 8px',
                                    backgroundColor: 'var(--color-ec-bg-elevated)',
                                    border: '0.5px solid var(--color-ec-border)',
                                    borderRadius: 4,
                                    fontSize: 10,
                                    fontWeight: 600,
                                    color: 'var(--color-ec-text-primary)',
                                    fontFamily: 'var(--color-ec-sans)',
                                    cursor: 'pointer',
                                    transition: 'border-color 150ms ease',
                                }}
                                onMouseEnter={(e) => e.currentTarget.style.borderColor = activeAccentColor}
                                onMouseLeave={(e) => e.currentTarget.style.borderColor = 'var(--color-ec-border)'}
                            >
                                <span>{formatConditionText(cond)}</span>
                                <button 
                                    onClick={(e) => {
                                        e.stopPropagation();
                                        handleRemoveCondition(idx);
                                    }} 
                                    style={{
                                        background: 'none',
                                        border: 'none',
                                        color: 'var(--color-ec-text-muted)',
                                        cursor: 'pointer',
                                        fontSize: 12,
                                        padding: '0 2px',
                                        lineHeight: 1,
                                    }}
                                    onMouseEnter={(e) => e.currentTarget.style.color = 'var(--color-ec-loss)'}
                                    onMouseLeave={(e) => e.currentTarget.style.color = 'var(--color-ec-text-muted)'}
                                >
                                    ×
                                </button>
                            </div>
                        );
                    })}
                </div>
            </div>

            {/* Nested subgroups */}
            <div className="flex flex-col gap-3">
                {subGroups.map((sub, idx) => {
                    const mainIdx = group.conditions.indexOf(sub);
                    return (
                        <GroupDisplay
                            key={idx}
                            group={sub}
                            onChange={(newG) => updateCondition(mainIdx, newG)}
                            onDelete={() => removeCondition(mainIdx)}
                            level={level + 1}
                            accentColor={accentColor}
                            parentTimeframe={parentTimeframe}
                        />
                    );
                })}
            </div>
        </div>
    );
};

// ----------------------------------------------------------------------
// Main Entry Point for Logic Builder Component
// ----------------------------------------------------------------------
export const LogicBuilder = ({
    title,
    timeframe,
    onTimeframeChange,
    rootCondition,
    onConditionChange,
    accentColor = 'blue',
    candleDelay,
    onCandleDelayChange,
    children
}: {
    title: string;
    timeframe: Timeframe;
    onTimeframeChange: (tf: Timeframe) => void;
    rootCondition: ConditionGroup;
    onConditionChange: (g: ConditionGroup) => void;
    accentColor?: 'blue' | 'rose' | 'amber';
    candleDelay?: number;
    onCandleDelayChange?: (delay: number | undefined) => void;
    children?: React.ReactNode;
}) => {
    const headerAccentColor = accentColor === 'blue' ? 'var(--color-ec-profit)' : accentColor === 'rose' ? 'var(--color-ec-loss)' : 'var(--color-ec-copper)';
    const isEntry = title.toLowerCase().includes('entry');
    const tooltipText = `Esta opción (también llamada "slippage sintético") permite ejecutar la entrada o salida N velas después de que se cumpla la señal (por defecto es 1 vela para evitar look-ahead bias). Es una función especial orientada al trading sistemático de ejecución manual para dar tiempo a preparar y enviar la orden manualmente tras recibir o ver la alerta de ${isEntry ? 'entrada' : 'salida'}.

Con esta función podrás asegurarte de que tu sistema sigue siendo rentable incluso con retardo en la ejecución, puesto que la volatilidad instantanea puede "falsear" los resultados de un backtest si no se aplica de manera algorítmica (bot).`;

    const [activeTooltip, setActiveTooltip] = React.useState<{
        text: string;
        x: number;
        y: number;
        width: number;
    } | null>(null);

    const containerRef = React.useRef<HTMLDivElement>(null);

    return (
        <TooltipContext.Provider value={{ setActiveTooltip, containerRef }}>
            <div 
                ref={containerRef}
                style={{
                    display: 'flex',
                    flexDirection: 'column',
                    gap: 16,
                    padding: '20px 0',
                    backgroundColor: 'transparent',
                    borderBottom: '0.5px solid var(--color-ec-border)',
                    position: 'relative',
                }}
            >
                {/* Header with Title and Global Timeframe */}
                <div style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    paddingBottom: 4,
                    marginBottom: 4,
                }}>
                    <div className="flex flex-col gap-1">
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                            <div style={{
                                width: 3,
                                height: 14,
                                borderRadius: 1,
                                backgroundColor: headerAccentColor,
                            }} />
                            <h2 style={{
                                fontFamily: 'var(--color-ec-sans)',
                                fontSize: 13,
                                fontWeight: 700,
                                textTransform: 'uppercase',
                                letterSpacing: '0.08em',
                                color: 'var(--color-ec-text-high)',
                                margin: 0,
                            }}>{title}</h2>
                        </div>
                        <span style={{
                            fontFamily: 'var(--color-ec-sans)',
                            fontSize: 10,
                            fontWeight: 400,
                            color: 'var(--color-ec-text-muted)',
                            marginTop: 2,
                        }}>Define las condiciones lógicas y el timeframe de ejecución</span>
                    </div>
                </div>

                {/* Root Condition Group */}
                <GroupDisplay
                    group={rootCondition}
                    onChange={onConditionChange}
                    accentColor={accentColor}
                    parentTimeframe={timeframe}
                />

                {/* Delayed Execution (Candle Delay) */}
                {onCandleDelayChange && (
                    <div style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: 12,
                        marginTop: -10,
                        paddingTop: 6,
                        borderTop: '0.5px dotted var(--color-ec-border)',
                        paddingLeft: 4,
                        paddingRight: 4,
                        width: '100%',
                    }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                            <label style={{
                                display: 'flex',
                                alignItems: 'center',
                                gap: 8,
                                cursor: 'pointer',
                                userSelect: 'none',
                                fontSize: 11,
                                fontWeight: 600,
                                color: 'var(--color-ec-text-primary)',
                                fontFamily: 'var(--color-ec-sans)',
                            }}>
                                <input
                                    type="checkbox"
                                    checked={candleDelay !== undefined && candleDelay > 1}
                                    onChange={(e) => {
                                        if (e.target.checked) {
                                            onCandleDelayChange(3); // Default to 3 candles when checked
                                        } else {
                                            onCandleDelayChange(undefined); // Reset/Disable delay
                                        }
                                    }}
                                    style={{
                                        accentColor: headerAccentColor,
                                        cursor: 'pointer',
                                    }}
                                />
                                Retardar ejecución (velas futuras)
                            </label>
                            <TooltipIcon customText={tooltipText} />
                        </div>

                        {candleDelay !== undefined && candleDelay > 1 && (
                            <div style={{
                                display: 'flex',
                                alignItems: 'center',
                                gap: 8,
                                paddingLeft: 12,
                                borderLeft: '0.5px solid var(--color-ec-border)',
                            }}>
                                <span style={{
                                    fontSize: 11,
                                    color: 'var(--color-ec-text-muted)',
                                    fontFamily: 'var(--color-ec-sans)',
                                }}>
                                    Ejecutar en la vela futura número:
                                </span>
                                <select
                                    value={candleDelay}
                                    onChange={(e) => onCandleDelayChange(Number(e.target.value))}
                                    style={{
                                        backgroundColor: 'var(--color-ec-bg-sidebar)',
                                        border: '0.5px solid var(--color-ec-border)',
                                        borderRadius: '4px',
                                        padding: '3px 8px',
                                        fontSize: '11px',
                                        fontWeight: 600,
                                        color: 'var(--color-ec-text-primary)',
                                        fontFamily: 'var(--color-ec-sans)',
                                        outline: 'none',
                                        cursor: 'pointer',
                                    }}
                                >
                                    {[2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 15, 20, 30, 45, 60].map((num) => (
                                        <option key={num} value={num}>
                                            {num}
                                        </option>
                                    ))}
                                </select>
                            </div>
                        )}
                    </div>
                )}

                {children}

                {activeTooltip && (
                    <div
                        style={{
                            position: "absolute",
                            top: activeTooltip.y,
                            left: activeTooltip.x,
                            transform: "translate(-50%, -100%)",
                            backgroundColor: "var(--color-ec-bg-sidebar)",
                            color: "var(--color-ec-text-primary)",
                            border: "0.5px solid var(--color-ec-border)",
                            borderRadius: 6,
                            padding: "8px 12px",
                            fontSize: 10,
                            fontStyle: "italic",
                            lineHeight: 1.4,
                            width: activeTooltip.width,
                            zIndex: 9999,
                            pointerEvents: "none",
                            boxShadow: "0 6px 20px rgba(0,0,0,0.4)",
                            fontFamily: "var(--color-ec-sans)",
                            transition: "opacity 150ms ease",
                            whiteSpace: "pre-line",
                        }}
                    >
                        {activeTooltip.text}
                    </div>
                )}
            </div>
        </TooltipContext.Provider>
    );
};
