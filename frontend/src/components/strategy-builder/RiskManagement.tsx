
import React from 'react';
import { RiskManagement, RiskType, RiskSettings, TakeProfitMode, PartialTakeProfit } from '@/types/strategy';
import { PlusCircle, Trash2, Info, HelpCircle } from 'lucide-react';

interface Props {
    risk: RiskManagement;
    onChange: (risk: RiskManagement) => void;
    applyDay?: 'gap_day' | 'gap_1_day' | 'gap_2_day';
}

const RiskManagementComponentInner: React.FC<Props> = ({ risk, onChange, applyDay = 'gap_day' }) => {

    const updateRiskSetting = (key: 'hard_stop' | 'take_profit', field: keyof RiskSettings, value: any) => {
        onChange({
            ...risk,
            [key]: {
                ...risk[key],
                [field]: value
            }
        });
    };

    const addPartial = () => {
        const currentPartials = risk.partial_take_profits || [];
        // Default to a reasonable new partial: next 2% distance, remaining capital or 25%
        const lastPartial = currentPartials.length > 0 ? currentPartials[currentPartials.length - 1] : null;
        let lastDist = 3.0;
        if (lastPartial && typeof lastPartial.distance_pct === 'number') {
            lastDist = lastPartial.distance_pct;
        }
        const currentTotal = currentPartials.reduce((sum, p) => sum + p.capital_pct, 0);
        const remaining = Math.max(0, 100 - currentTotal);
        
        onChange({
            ...risk,
            partial_take_profits: [
                ...currentPartials,
                { distance_pct: Number((lastDist + 2).toFixed(1)), capital_pct: remaining > 0 ? remaining : 25 }
            ]
        });
    };

    const removePartial = (index: number) => {
        onChange({
            ...risk,
            partial_take_profits: (risk.partial_take_profits || []).filter((_, i) => i !== index)
        });
    };

    const updatePartial = (index: number, field: keyof PartialTakeProfit, value: any) => {
        onChange({
            ...risk,
            partial_take_profits: (risk.partial_take_profits || []).map((p, i) =>
                i === index ? { ...p, [field]: value } : p
            )
        });
    };

    const totalPartialCapital = (risk.partial_take_profits || []).reduce((sum, p) => sum + p.capital_pct, 0);



    // Helper for Trailing (fixing typing above)
    const setTrailingField = (field: keyof typeof risk.trailing_stop, value: any) => {
        onChange({
            ...risk,
            trailing_stop: {
                ...risk.trailing_stop,
                [field]: value
            }
        });
    };


    return (
        <div style={{
            display: 'flex',
            flexDirection: 'column',
            gap: 0,
        }}>

            {/* Hard Stop Loss Card */}
            <div style={{
                display: 'flex',
                flexDirection: 'column',
                gap: 16,
                padding: '20px 0',
                backgroundColor: 'transparent',
                borderBottom: '0.5px solid var(--color-ec-border)',
            }}>
                {/* Header */}
                <div style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    paddingBottom: (risk.use_hard_stop === true) ? 12 : 0,
                    borderBottom: (risk.use_hard_stop === true) ? '0.5px solid var(--color-ec-border)' : 'none',
                }}>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                            <div style={{
                                width: 3,
                                height: 14,
                                borderRadius: 1,
                                backgroundColor: 'var(--color-ec-loss)',
                            }} />
                            <h2 style={{
                                fontFamily: 'var(--color-ec-sans)',
                                fontSize: 13,
                                fontWeight: 700,
                                textTransform: 'uppercase',
                                letterSpacing: '0.08em',
                                color: 'var(--color-ec-text-high)',
                                margin: 0,
                            }}>Stop Loss Fijo</h2>
                        </div>
                        <span style={{
                            fontFamily: 'var(--color-ec-sans)',
                            fontSize: 10,
                            fontWeight: 400,
                            color: 'var(--color-ec-text-muted)',
                            marginTop: 2,
                        }}>Define la tolerancia máxima de pérdida por trade</span>
                    </div>
                    <div className="flex items-center gap-2">
                        <span style={{
                            fontFamily: 'var(--color-ec-sans)',
                            fontSize: 10,
                            fontWeight: 700,
                            color: 'var(--color-ec-text-muted)',
                        }}>{risk.use_hard_stop === true ? 'ON' : 'OFF'}</span>
                        <div
                            className={`w-8 h-4 rounded-full relative cursor-pointer transition-colors ${risk.use_hard_stop === true ? 'bg-ec-loss/70' : 'bg-muted'}`}
                            onClick={() => onChange({ ...risk, use_hard_stop: !risk.use_hard_stop })}
                        >
                            <div className={`absolute top-0.5 w-3 h-3 rounded-full bg-white transition-all shadow-sm ${risk.use_hard_stop === true ? 'left-4.5' : 'left-0.5'}`}></div>
                        </div>
                    </div>
                </div>

                {/* Body */}
                {(risk.use_hard_stop === true) && (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }} className="animate-in fade-in duration-200">
                        <div className={`flex gap-2 ${risk.hard_stop.type === RiskType.PERCENTAGE ? 'items-center justify-center' : ''}`}>
                            <select
                                value={risk.hard_stop.type}
                                onChange={(e) => {
                                    const newType = e.target.value as RiskType;
                                    const newValue = newType === RiskType.MARKET_STRUCTURE ? 'LOD' : 2.0;
                                    onChange({
                                        ...risk,
                                        hard_stop: {
                                            type: newType,
                                            value: newValue
                                        },
                                        size_by_sl: newType === RiskType.MARKET_STRUCTURE ? risk.size_by_sl : false
                                    });
                                }}
                                style={{
                                    backgroundColor: 'var(--color-ec-bg-sidebar)',
                                    border: '0.5px solid var(--color-ec-border)',
                                    borderRadius: 5,
                                    padding: '7px 10px',
                                    fontSize: 12,
                                    fontWeight: 500,
                                    color: 'var(--color-ec-text-primary)',
                                    fontFamily: 'var(--color-ec-sans)',
                                    outline: 'none',
                                    cursor: 'pointer',
                                    height: '36px',
                                    width: risk.hard_stop.type === RiskType.PERCENTAGE ? '52px' : 'auto',
                                }}
                            >
                                <option value={RiskType.PERCENTAGE}>%</option>
                                <option value={RiskType.MARKET_STRUCTURE}>Market Structure</option>
                            </select>
                            {risk.hard_stop.type === RiskType.MARKET_STRUCTURE ? (
                                <>
                                    <select
                                        value={risk.hard_stop.value || 'LOD'}
                                        onChange={(e) => updateRiskSetting('hard_stop', 'value', e.target.value)}
                                        style={{
                                            backgroundColor: 'var(--color-ec-bg-sidebar)',
                                            border: '0.5px solid var(--color-ec-border)',
                                            borderRadius: 5,
                                            padding: '7px 10px',
                                            fontSize: 12,
                                            fontWeight: 500,
                                            color: 'var(--color-ec-text-primary)',
                                            fontFamily: 'var(--color-ec-sans)',
                                            outline: 'none',
                                            cursor: 'pointer',
                                            flex: 2,
                                            height: '36px',
                                        }}
                                    >
                                        <option value="HOD">HOD (High of Day)</option>
                                        <option value="LOD">LOD (Low of Day)</option>
                                        <option value="PMH">PMH (Premarket High)</option>
                                        <option value="PML">PML (Premarket Low)</option>
                                        <option value="Previous Max">Previous Max</option>
                                        <option value="Previous Min">Previous Min</option>
                                    </select>
                                    
                                    <select
                                        value={risk.hard_stop.operator || '>='}
                                        onChange={(e) => updateRiskSetting('hard_stop', 'operator', e.target.value)}
                                        style={{
                                            backgroundColor: 'var(--color-ec-bg-sidebar)',
                                            border: '0.5px solid var(--color-ec-border)',
                                            borderRadius: 5,
                                            padding: '7px 10px',
                                            fontSize: 12,
                                            fontWeight: 500,
                                            color: 'var(--color-ec-text-primary)',
                                            fontFamily: 'var(--color-ec-sans)',
                                            outline: 'none',
                                            cursor: 'pointer',
                                            width: '120px',
                                            height: '36px',
                                        }}
                                    >
                                        <option value=">=">Por encima</option>
                                        <option value="<=">Por debajo</option>
                                    </select>

                                    <div style={{ position: 'relative', width: '80px' }}>
                                        <input
                                            type="number"
                                            step="0.1"
                                            value={risk.hard_stop.offset_pct ?? ''}
                                            onChange={(e) => updateRiskSetting('hard_stop', 'offset_pct', e.target.value === '' ? '' : e.target.value)}
                                            onBlur={() => {
                                                const val = parseFloat(String(risk.hard_stop.offset_pct));
                                                updateRiskSetting('hard_stop', 'offset_pct', isNaN(val) ? 0.0 : val);
                                            }}
                                            onFocus={(e) => e.target.select()}
                                            style={{
                                                backgroundColor: 'var(--color-ec-bg-sidebar)',
                                                border: '0.5px solid var(--color-ec-border)',
                                                borderRadius: 5,
                                                padding: '7px 18px 7px 8px',
                                                fontSize: 12,
                                                fontWeight: 600,
                                                color: 'var(--color-ec-text-primary)',
                                                fontFamily: 'var(--color-ec-sans)',
                                                outline: 'none',
                                                width: '100%',
                                                height: '36px',
                                            }}
                                        />
                                        <span style={{
                                            position: 'absolute',
                                            right: 8,
                                            top: '50%',
                                            transform: 'translateY(-50%)',
                                            fontSize: 10,
                                            fontWeight: 700,
                                            color: 'var(--color-ec-text-muted)',
                                            pointerEvents: 'none',
                                        }}>
                                            %
                                        </span>
                                    </div>
                                </>
                            ) : (
                                <div className="relative" style={{ width: '120px' }}>
                                    <input
                                        type="number"
                                        step="0.1"
                                        value={risk.hard_stop.value ?? ''}
                                        onChange={(e) => updateRiskSetting('hard_stop', 'value', e.target.value === '' ? '' : e.target.value)}
                                        onBlur={() => {
                                            const val = parseFloat(String(risk.hard_stop.value));
                                            updateRiskSetting('hard_stop', 'value', isNaN(val) ? 2.0 : val);
                                        }}
                                        onFocus={(e) => e.target.select()}
                                        style={{
                                            backgroundColor: 'var(--color-ec-bg-sidebar)',
                                            border: '0.5px solid var(--color-ec-border)',
                                            borderRadius: 5,
                                            padding: '7px 24px 7px 10px',
                                            fontSize: 13,
                                            fontWeight: 600,
                                            color: 'var(--color-ec-text-primary)',
                                            fontFamily: 'var(--color-ec-sans)',
                                            outline: 'none',
                                            width: '100%',
                                            height: '36px',
                                            textAlign: 'center',
                                        }}
                                    />
                                    <span className="absolute right-3 top-1/2 -translate-y-1/2 text-[10px] font-bold text-muted-foreground/40">%</span>
                                </div>
                            )}
                        </div>

                        {/* Size by SL Description block with Switch */}
                        <div style={{
                            marginTop: 4,
                            paddingTop: 10,
                            borderTop: '0.5px dotted var(--color-ec-border)',
                            display: 'flex',
                            flexDirection: 'column',
                            gap: 4,
                            opacity: risk.hard_stop.type === RiskType.MARKET_STRUCTURE ? 1 : 0.4,
                            pointerEvents: risk.hard_stop.type === RiskType.MARKET_STRUCTURE ? 'auto' : 'none',
                            transition: 'opacity 150ms ease',
                        }}>
                            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                                    <HelpCircle size={12} style={{ color: 'var(--color-ec-copper)' }} />
                                    <span style={{
                                        fontFamily: 'var(--color-ec-sans)',
                                        fontSize: 10,
                                        fontWeight: 700,
                                        textTransform: 'uppercase',
                                        letterSpacing: '0.05em',
                                        color: 'var(--color-ec-text-secondary)'
                                    }}>
                                        Cálculo de Shares por Distancia al SL
                                    </span>
                                </div>
                                <div className="flex items-center gap-2">
                                    <span style={{
                                        fontFamily: 'var(--color-ec-sans)',
                                        fontSize: 10,
                                        fontWeight: 700,
                                        color: 'var(--color-ec-text-muted)',
                                    }}>{risk.size_by_sl ? 'YES' : 'NO'}</span>
                                    <div
                                        className={`w-8 h-4 rounded-full relative cursor-pointer transition-colors ${risk.size_by_sl ? 'bg-ec-loss/70' : 'bg-muted'}`}
                                        onClick={() => onChange({ ...risk, size_by_sl: !risk.size_by_sl })}
                                    >
                                        <div className={`absolute top-0.5 w-3 h-3 rounded-full bg-white transition-all shadow-sm ${risk.size_by_sl ? 'left-4.5' : 'left-0.5'}`}></div>
                                    </div>
                                </div>
                            </div>
                            <span style={{
                                fontFamily: 'var(--color-ec-sans)',
                                fontSize: 10,
                                color: 'var(--color-ec-text-secondary)',
                                fontStyle: 'italic',
                                marginLeft: 18,
                                marginTop: 4,
                                lineHeight: '1.3',
                            }}>
                                Calcula nº Shares usando el Riesgo dividido por la distancia real al Stop Loss
                            </span>
                        </div>
                    </div>
                )}
            </div>

            {/* Trailing Stop Card */}
            <div style={{
                display: 'flex',
                flexDirection: 'column',
                gap: 16,
                padding: '20px 0',
                backgroundColor: 'transparent',
                borderBottom: '0.5px solid var(--color-ec-border)',
            }}>
                {/* Header */}
                <div style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    paddingBottom: (risk.trailing_stop.active) ? 12 : 0,
                    borderBottom: (risk.trailing_stop.active) ? '0.5px solid var(--color-ec-border)' : 'none',
                }}>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                            <div style={{
                                width: 3,
                                height: 14,
                                borderRadius: 1,
                                backgroundColor: 'var(--color-ec-loss)',
                            }} />
                            <h2 style={{
                                fontFamily: 'var(--color-ec-sans)',
                                fontSize: 13,
                                fontWeight: 700,
                                textTransform: 'uppercase',
                                letterSpacing: '0.08em',
                                color: 'var(--color-ec-text-high)',
                                margin: 0,
                            }}>Trailing Stop</h2>
                        </div>
                        <span style={{
                            fontFamily: 'var(--color-ec-sans)',
                            fontSize: 10,
                            fontWeight: 400,
                            color: 'var(--color-ec-text-muted)',
                            marginTop: 2,
                        }}>Ajusta el stop loss dinámicamente a medida que el precio alcanza objetivos</span>
                    </div>
                    <div className="flex items-center gap-2">
                        <span style={{
                            fontFamily: 'var(--color-ec-sans)',
                            fontSize: 10,
                            fontWeight: 700,
                            color: 'var(--color-ec-text-muted)',
                        }}>{risk.trailing_stop.active ? 'ACTIVE' : 'OFF'}</span>
                        <div
                            className={`w-8 h-4 rounded-full relative cursor-pointer transition-colors ${risk.trailing_stop.active ? 'bg-[var(--color-ec-copper)]' : 'bg-muted'}`}
                            onClick={() => setTrailingField('active', !risk.trailing_stop.active)}
                        >
                            <div className={`absolute top-0.5 w-3 h-3 rounded-full bg-white transition-all shadow-sm ${risk.trailing_stop.active ? 'left-4.5' : 'left-0.5'}`}></div>
                        </div>
                    </div>
                </div>

                {/* Body */}
                {risk.trailing_stop.active && (
                    <div className="flex items-center justify-center animate-in fade-in duration-200" style={{ marginTop: 12 }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                            <span style={{ fontSize: 9, fontWeight: 700, color: 'var(--color-ec-text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Distancia Trailing:</span>
                            <div className="relative" style={{ width: '120px' }}>
                                <input
                                    type="number"
                                    step="0.1"
                                    value={risk.trailing_stop.buffer_pct ?? ''}
                                    onChange={(e) => setTrailingField('buffer_pct', e.target.value === '' ? '' : e.target.value)}
                                    onBlur={() => {
                                        const val = parseFloat(String(risk.trailing_stop.buffer_pct));
                                        setTrailingField('buffer_pct', isNaN(val) ? 0.5 : val);
                                    }}
                                    onFocus={(e) => e.target.select()}
                                    style={{
                                        backgroundColor: 'var(--color-ec-bg-sidebar)',
                                        border: '0.5px solid var(--color-ec-border)',
                                        borderRadius: 5,
                                        padding: '7px 24px 7px 10px',
                                        fontSize: 13,
                                        fontWeight: 600,
                                        color: 'var(--color-ec-text-primary)',
                                        fontFamily: 'var(--color-ec-sans)',
                                        outline: 'none',
                                        width: '100%',
                                        height: '36px',
                                        textAlign: 'center',
                                    }}
                                />
                                <span className="absolute right-3 top-1/2 -translate-y-1/2 text-[10px] font-bold text-muted-foreground/40">%</span>
                            </div>
                        </div>
                    </div>
                )}
            </div>

            {/* Take Profit Card */}
            <div style={{
                display: 'flex',
                flexDirection: 'column',
                gap: 16,
                padding: '20px 0',
                backgroundColor: 'transparent',
                borderBottom: '0.5px solid var(--color-ec-border)',
            }}>
                {/* Header */}
                <div style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    paddingBottom: (risk.use_take_profit === true) ? 12 : 0,
                    borderBottom: (risk.use_take_profit === true) ? '0.5px solid var(--color-ec-border)' : 'none',
                }}>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                            <div style={{
                                width: 3,
                                height: 14,
                                borderRadius: 1,
                                backgroundColor: 'var(--color-ec-profit)',
                            }} />
                            <h2 style={{
                                fontFamily: 'var(--color-ec-sans)',
                                fontSize: 13,
                                fontWeight: 700,
                                textTransform: 'uppercase',
                                letterSpacing: '0.08em',
                                color: 'var(--color-ec-text-high)',
                                margin: 0,
                            }}>Take Profit</h2>
                        </div>
                        <span style={{
                            fontFamily: 'var(--color-ec-sans)',
                            fontSize: 10,
                            fontWeight: 400,
                            color: 'var(--color-ec-text-muted)',
                            marginTop: 2,
                        }}>Define el objetivo de ganancia y el escalado de salida</span>
                    </div>
                    <div className="flex items-center gap-2">
                        <span style={{
                            fontFamily: 'var(--color-ec-sans)',
                            fontSize: 10,
                            fontWeight: 700,
                            color: 'var(--color-ec-text-muted)',
                        }}>{risk.use_take_profit === true ? 'ON' : 'OFF'}</span>
                        <div
                            className={`w-8 h-4 rounded-full relative cursor-pointer transition-colors ${risk.use_take_profit === true ? 'bg-ec-profit/70' : 'bg-muted'}`}
                            onClick={() => onChange({ ...risk, use_take_profit: !risk.use_take_profit })}
                        >
                            <div className={`absolute top-0.5 w-3 h-3 rounded-full bg-white transition-all shadow-sm ${risk.use_take_profit === true ? 'left-4.5' : 'left-0.5'}`}></div>
                        </div>
                    </div>
                </div>

                {/* Body */}
                {(risk.use_take_profit === true) && (
                    <div className="space-y-4 animate-in fade-in duration-200">
                        {/* Mode Toggle */}
                        <div style={{
                            display: 'flex',
                            backgroundColor: 'var(--color-ec-bg-elevated)',
                            border: '0.5px solid var(--color-ec-border)',
                            borderRadius: 5,
                            padding: 3,
                            gap: 2,
                        }}>
                            <button
                                onClick={() => onChange({ ...risk, take_profit_mode: TakeProfitMode.FULL })}
                                style={risk.take_profit_mode === TakeProfitMode.FULL ? {
                                    flex: 1,
                                    backgroundColor: 'var(--color-ec-bg-sidebar)',
                                    color: 'var(--color-ec-text-high)',
                                    fontFamily: 'var(--color-ec-sans)',
                                    fontSize: 9,
                                    fontWeight: 700,
                                    textTransform: 'uppercase',
                                    letterSpacing: '0.12em',
                                    padding: '6px 12px',
                                    borderRadius: 4,
                                    border: '0.5px solid var(--color-ec-border)',
                                    cursor: 'pointer',
                                } : {
                                    flex: 1,
                                    backgroundColor: 'transparent',
                                    color: 'var(--color-ec-text-muted)',
                                    fontFamily: 'var(--color-ec-sans)',
                                    fontSize: 9,
                                    fontWeight: 700,
                                    textTransform: 'uppercase',
                                    letterSpacing: '0.12em',
                                    padding: '6px 12px',
                                    borderRadius: 4,
                                    border: 'none',
                                    cursor: 'pointer',
                                }}
                            >
                                Completo (Full)
                            </button>
                            <button
                                onClick={() => onChange({ ...risk, take_profit_mode: TakeProfitMode.PARTIAL })}
                                style={risk.take_profit_mode === TakeProfitMode.PARTIAL ? {
                                    flex: 1,
                                    backgroundColor: 'var(--color-ec-bg-sidebar)',
                                    color: 'var(--color-ec-text-high)',
                                    fontFamily: 'var(--color-ec-sans)',
                                    fontSize: 9,
                                    fontWeight: 700,
                                    textTransform: 'uppercase',
                                    letterSpacing: '0.12em',
                                    padding: '6px 12px',
                                    borderRadius: 4,
                                    border: '0.5px solid var(--color-ec-border)',
                                    cursor: 'pointer',
                                } : {
                                    flex: 1,
                                    backgroundColor: 'transparent',
                                    color: 'var(--color-ec-text-muted)',
                                    fontFamily: 'var(--color-ec-sans)',
                                    fontSize: 9,
                                    fontWeight: 700,
                                    textTransform: 'uppercase',
                                    letterSpacing: '0.12em',
                                    padding: '6px 12px',
                                    borderRadius: 4,
                                    border: 'none',
                                    cursor: 'pointer',
                                }}
                            >
                                Parciales (Partial)
                            </button>
                        </div>

                        {risk.take_profit_mode === TakeProfitMode.FULL ? (
                            <div className="flex gap-2 items-center justify-center animate-in fade-in zoom-in-95 duration-200" style={{ marginTop: 12 }}>
                                <select
                                    value={risk.take_profit.type || RiskType.PERCENTAGE}
                                    onChange={(e) => {
                                        const newType = e.target.value as RiskType;
                                        updateRiskSetting('take_profit', 'type', newType);
                                        const defaultVal = newType === RiskType.TIME ? 30 : 6.0;
                                        updateRiskSetting('take_profit', 'value', defaultVal);
                                    }}
                                    style={{
                                        backgroundColor: 'var(--color-ec-bg-sidebar)',
                                        border: '0.5px solid var(--color-ec-border)',
                                        borderRadius: 5,
                                        padding: '7px 10px',
                                        fontSize: 12,
                                        fontWeight: 600,
                                        color: 'var(--color-ec-text-primary)',
                                        fontFamily: 'var(--color-ec-sans)',
                                        height: '36px',
                                        outline: 'none',
                                        cursor: 'pointer',
                                    }}
                                >
                                    <option value={RiskType.PERCENTAGE}>% Distancia</option>
                                    <option value={RiskType.TIME}>Tiempo (minutos)</option>
                                </select>
                                <div className="relative" style={{ width: '120px' }}>
                                    <input
                                        type="number"
                                        step={risk.take_profit.type === RiskType.TIME ? '1' : '0.1'}
                                        value={risk.take_profit.value ?? ''}
                                        onChange={(e) => updateRiskSetting('take_profit', 'value', e.target.value === '' ? '' : e.target.value)}
                                        onBlur={() => {
                                            const val = parseFloat(String(risk.take_profit.value));
                                            const isTime = risk.take_profit.type === RiskType.TIME;
                                            const defaultVal = isTime ? 30 : 6.0;
                                            updateRiskSetting('take_profit', 'value', isNaN(val) ? defaultVal : val);
                                        }}
                                        onFocus={(e) => e.target.select()}
                                        style={{
                                            backgroundColor: 'var(--color-ec-bg-sidebar)',
                                            border: '0.5px solid var(--color-ec-border)',
                                            borderRadius: 5,
                                            padding: '7px 30px 7px 10px',
                                            fontSize: 13,
                                            fontWeight: 600,
                                            color: 'var(--color-ec-text-primary)',
                                            fontFamily: 'var(--color-ec-sans)',
                                            outline: 'none',
                                            width: '100%',
                                            height: '36px',
                                            textAlign: 'center',
                                        }}
                                    />
                                    <span className="absolute right-3 top-1/2 -translate-y-1/2 text-[10px] font-bold text-muted-foreground/40">
                                        {risk.take_profit.type === RiskType.TIME ? 'min' : '%'}
                                    </span>
                                </div>
                            </div>
                        ) : (
                            <div className="space-y-3 animate-in fade-in zoom-in-95 duration-200" style={{ marginTop: 12 }}>
                                <div className="space-y-2">
                                    {(risk.partial_take_profits || []).map((partial, idx) => (
                                        <div key={idx} className="group relative"
                                            style={{
                                                backgroundColor: 'transparent',
                                                borderBottom: '0.5px dotted var(--color-ec-border)',
                                                padding: '8px 0',
                                                display: 'flex',
                                                alignItems: 'center',
                                                gap: 12,
                                            }}
                                        >
                                            {/* Partial Tag */}
                                            <span style={{
                                                fontSize: 9,
                                                fontWeight: 800,
                                                color: 'var(--color-ec-profit)',
                                                textTransform: 'uppercase',
                                                letterSpacing: '0.05em',
                                                width: 65,
                                                flexShrink: 0
                                            }}>
                                                Parcial #{idx + 1}
                                            </span>

                                            {/* Distance Input */}
                                            <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexShrink: 0 }}>
                                                {(() => {
                                                    const valStr = String(partial.distance_pct);
                                                    const mode = valStr === 'EOD' ? 'EOD' : valStr.startsWith('TIME:') ? 'TIME' : valStr.startsWith('HOUR:') ? 'HOUR' : 'PCT';
                                                    
                                                    return (
                                                        <>
                                                            <select
                                                                value={mode}
                                                                onChange={(e) => {
                                                                    const newMode = e.target.value;
                                                                    if (newMode === 'EOD') {
                                                                        updatePartial(idx, 'distance_pct', 'EOD');
                                                                    } else if (newMode === 'TIME') {
                                                                        updatePartial(idx, 'distance_pct', 'TIME:30');
                                                                    } else if (newMode === 'HOUR') {
                                                                        updatePartial(idx, 'distance_pct', 'HOUR:15:30');
                                                                    } else {
                                                                        updatePartial(idx, 'distance_pct', 3.0);
                                                                    }
                                                                }}
                                                                style={{
                                                                    backgroundColor: 'var(--color-ec-bg-sidebar)',
                                                                    border: '0.5px solid var(--color-ec-border)',
                                                                    borderRadius: 4,
                                                                    padding: '4px 6px',
                                                                    fontSize: 10,
                                                                    fontWeight: 600,
                                                                    color: 'var(--color-ec-text-primary)',
                                                                    fontFamily: 'var(--color-ec-sans)',
                                                                    outline: 'none',
                                                                    cursor: 'pointer',
                                                                }}
                                                            >
                                                                <option value="PCT">% Distancia</option>
                                                                <option value="TIME">Tiempo (minutos)</option>
                                                                <option value="HOUR">Hora específica</option>
                                                                <option value="EOD">Fin del Día (EOD)</option>
                                                            </select>
                                                            
                                                            {mode === 'EOD' ? (
                                                                <div style={{
                                                                    width: 65,
                                                                    border: '0.5px solid var(--color-ec-border)',
                                                                    borderRadius: 4,
                                                                    padding: '4px 6px',
                                                                    fontSize: 11,
                                                                    fontWeight: 700,
                                                                    color: 'var(--color-ec-text-muted)',
                                                                    textAlign: 'center',
                                                                    backgroundColor: 'rgba(255, 255, 255, 0.03)',
                                                                }}>
                                                                    EOD
                                                                </div>
                                                            ) : mode === 'HOUR' ? (
                                                                <input
                                                                    type="time"
                                                                    value={valStr.startsWith('HOUR:') ? valStr.substring(5) : '15:30'}
                                                                    onChange={(e) => {
                                                                        updatePartial(idx, 'distance_pct', `HOUR:${e.target.value || '15:30'}`);
                                                                    }}
                                                                    style={{
                                                                        width: 72,
                                                                        backgroundColor: 'var(--color-ec-bg-sidebar)',
                                                                        border: '0.5px solid var(--color-ec-border)',
                                                                        borderRadius: 4,
                                                                        padding: '4px 4px',
                                                                        fontSize: 11,
                                                                        fontWeight: 700,
                                                                        color: 'var(--color-ec-text-primary)',
                                                                        outline: 'none',
                                                                        textAlign: 'center',
                                                                        boxSizing: 'border-box',
                                                                    }}
                                                                />
                                                            ) : (
                                                                <div className="relative" style={{ width: 65 }}>
                                                                    <input
                                                                        type="number"
                                                                        step={mode === 'TIME' ? '1' : '0.1'}
                                                                        value={mode === 'TIME' ? (valStr.split(':')[1] || '') : (partial.distance_pct ?? '')}
                                                                        onChange={(e) => {
                                                                            const rawVal = e.target.value;
                                                                            if (mode === 'TIME') {
                                                                                updatePartial(idx, 'distance_pct', rawVal === '' ? 'TIME:' : `TIME:${rawVal}`);
                                                                            } else {
                                                                                updatePartial(idx, 'distance_pct', rawVal === '' ? '' : Number(rawVal));
                                                                            }
                                                                        }}
                                                                        onBlur={() => {
                                                                            if (mode === 'TIME') {
                                                                                const rawMins = valStr.split(':')[1] || '';
                                                                                const parsed = parseInt(rawMins);
                                                                                updatePartial(idx, 'distance_pct', `TIME:${isNaN(parsed) ? 30 : parsed}`);
                                                                            } else {
                                                                                const val = parseFloat(valStr);
                                                                                updatePartial(idx, 'distance_pct', isNaN(val) ? 3.0 : val);
                                                                            }
                                                                        }}
                                                                        onFocus={(e) => e.target.select()}
                                                                        style={{
                                                                            width: '100%',
                                                                            backgroundColor: 'var(--color-ec-bg-sidebar)',
                                                                            border: '0.5px solid var(--color-ec-border)',
                                                                            borderRadius: 4,
                                                                            padding: '4px 16px 4px 6px',
                                                                            fontSize: 11,
                                                                            fontWeight: 700,
                                                                            color: 'var(--color-ec-text-primary)',
                                                                            outline: 'none',
                                                                            textAlign: 'right',
                                                                        }}
                                                                    />
                                                                    <span className="absolute right-1 top-1/2 -translate-y-1/2 text-[8px] font-bold text-muted-foreground/40">
                                                                        {mode === 'TIME' ? 'm' : '%'}
                                                                    </span>
                                                                </div>
                                                            )}
                                                        </>
                                                    );
                                                })()}
                                            </div>

                                            {/* Capital Slider */}
                                            <div style={{ display: 'flex', alignItems: 'center', gap: 8, flex: 1 }}>
                                                <span style={{ fontSize: 9, fontWeight: 600, color: 'var(--color-ec-text-muted)', flexShrink: 0 }}>Cap.</span>
                                                <input
                                                    type="range"
                                                    min="1"
                                                    max="100"
                                                    value={partial.capital_pct}
                                                    onChange={(e) => updatePartial(idx, 'capital_pct', Number(e.target.value))}
                                                    style={{
                                                        backgroundColor: 'rgba(255, 255, 255, 0.12)',
                                                        accentColor: 'var(--color-ec-profit)',
                                                        outline: 'none',
                                                        height: '4px',
                                                        flex: 1,
                                                        minWidth: '50px',
                                                        cursor: 'pointer',
                                                        borderRadius: '2px',
                                                        appearance: 'none',
                                                    }}
                                                />
                                                <span style={{
                                                    fontSize: 10,
                                                    fontWeight: 800,
                                                    color: 'var(--color-ec-text-primary)',
                                                    width: 35,
                                                    textAlign: 'right',
                                                    flexShrink: 0
                                                }}>
                                                    {partial.capital_pct}%
                                                </span>
                                            </div>

                                            {/* Delete button */}
                                            {(risk.partial_take_profits || []).length > 1 && (
                                                <button
                                                    onClick={() => removePartial(idx)}
                                                    className="p-1 text-muted-foreground hover:text-ec-loss transition-colors opacity-0 group-hover:opacity-100"
                                                    style={{
                                                        background: 'transparent',
                                                        border: 'none',
                                                        cursor: 'pointer',
                                                        padding: 2,
                                                        flexShrink: 0
                                                    }}
                                                >
                                                    <Trash2 className="w-3.5 h-3.5" />
                                                </button>
                                            )}
                                        </div>
                                    ))}
                                </div>

                                <button
                                    onClick={addPartial}
                                    style={{
                                        width: '100%',
                                        padding: '7px 0',
                                        border: '0.5px dashed var(--color-ec-border)',
                                        borderRadius: 5,
                                        fontSize: 10,
                                        fontWeight: 700,
                                        textTransform: 'uppercase',
                                        letterSpacing: '0.1em',
                                        color: 'var(--color-ec-text-muted)',
                                        backgroundColor: 'transparent',
                                        cursor: 'pointer',
                                        fontFamily: 'var(--color-ec-sans)',
                                        transition: 'border-color 150ms ease, color 150ms ease',
                                        display: 'flex',
                                        alignItems: 'center',
                                        justifyContent: 'center',
                                        gap: 6,
                                        margin: '20px 0 16px 0',
                                    }}
                                    onMouseEnter={(e) => { e.currentTarget.style.borderColor = 'var(--color-ec-profit)'; e.currentTarget.style.color = 'var(--color-ec-profit)'; }}
                                    onMouseLeave={(e) => { e.currentTarget.style.borderColor = 'var(--color-ec-border)'; e.currentTarget.style.color = 'var(--color-ec-text-muted)'; }}
                                >
                                    <PlusCircle className="w-3.5 h-3.5" />
                                    <span>Add Partial Take Profit</span>
                                </button>

                                <div className={`flex items-center gap-2 p-2 rounded-lg border transition-all ${Math.abs(totalPartialCapital - 100) < 0.01 ? 'bg-ec-profit/5 border-ec-profit/20 text-ec-profit/80' : 'bg-[var(--color-ec-copper)]/5 border-[var(--color-ec-copper)]/20 text-[var(--color-ec-copper)]'}`}>
                                    <Info className="w-3.5 h-3.5 shrink-0" />
                                    <div className="flex-1 text-[9px] font-bold leading-tight">
                                        Total Capital: <span className="font-black underline">{totalPartialCapital}%</span>
                                        {Math.abs(totalPartialCapital - 100) > 0.01 && (
                                            <span className="block opacity-70">Sum must be exactly 100% to save/test.</span>
                                        )}
                                    </div>
                                </div>
                            </div>
                        )}
                    </div>
                )}
            </div>

            {/* Re-entries Card */}
            <div style={{
                display: 'flex',
                flexDirection: 'column',
                gap: 16,
                padding: '20px 0',
                backgroundColor: 'transparent',
                borderBottom: '0.5px solid var(--color-ec-border)',
            }}>
                <div style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                }}>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                            <div style={{
                                width: 3,
                                height: 14,
                                borderRadius: 1,
                                backgroundColor: 'var(--color-ec-copper)',
                            }} />
                            <h2 style={{
                                fontFamily: 'var(--color-ec-sans)',
                                fontSize: 13,
                                fontWeight: 700,
                                textTransform: 'uppercase',
                                letterSpacing: '0.08em',
                                color: 'var(--color-ec-text-high)',
                                margin: 0,
                            }}>Aceptar Reentradas</h2>
                        </div>
                        <span style={{
                            fontFamily: 'var(--color-ec-sans)',
                            fontSize: 10,
                            fontWeight: 400,
                            color: 'var(--color-ec-text-muted)',
                            marginTop: 2,
                        }}>Permitir entrar de nuevo al trade si se cerró por stop o target</span>
                    </div>
                    <div className="flex items-center gap-2">
                        <span style={{
                            fontFamily: 'var(--color-ec-sans)',
                            fontSize: 10,
                            fontWeight: 700,
                            color: 'var(--color-ec-text-muted)',
                        }}>{risk.accept_reentries === true ? 'YES' : 'NO'}</span>
                        <div
                            className={`w-8 h-4 rounded-full relative cursor-pointer transition-colors ${risk.accept_reentries === true ? 'bg-[var(--color-ec-copper)]' : 'bg-muted'}`}
                            onClick={() => onChange({ ...risk, accept_reentries: !risk.accept_reentries, max_reentries: !risk.accept_reentries ? -1 : 0 })}
                        >
                            <div className={`absolute top-0.5 w-3 h-3 rounded-full bg-white transition-all shadow-sm ${risk.accept_reentries === true ? 'left-4.5' : 'left-0.5'}`}></div>
                        </div>
                    </div>
                </div>
                {risk.accept_reentries === true && (
                    <div 
                        className="flex items-center justify-between animate-in fade-in slide-in-from-top-1 duration-200"
                        style={{
                            borderTop: '0.5px dotted var(--color-ec-border)',
                            marginTop: '14px',
                            paddingTop: '14px',
                        }}
                    >
                        <div style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
                            <span style={{
                                fontFamily: 'var(--color-ec-sans)',
                                fontSize: 11,
                                fontWeight: 600,
                                color: 'var(--color-ec-text-high)',
                            }}>Tipo de Reentradas</span>
                            <span style={{
                                fontFamily: 'var(--color-ec-sans)',
                                fontSize: 9,
                                color: 'var(--color-ec-text-muted)',
                            }}>Límite de reentradas adicionales permitidas</span>
                        </div>
                        <div className="flex items-center gap-2">
                            <select
                                value={risk.max_reentries === undefined || risk.max_reentries === -1 ? 'infinite' : 'limited'}
                                onChange={(e) => {
                                    if (e.target.value === 'infinite') {
                                        onChange({ ...risk, max_reentries: -1 });
                                    } else {
                                        onChange({ ...risk, max_reentries: 2 });
                                    }
                                }}
                                style={{
                                    backgroundColor: 'var(--color-ec-bg-sidebar)',
                                    border: '0.5px solid var(--color-ec-border)',
                                    borderRadius: 5,
                                    padding: '5px 8px',
                                    fontSize: 12,
                                    fontWeight: 500,
                                    color: 'var(--color-ec-text-primary)',
                                    fontFamily: 'var(--color-ec-sans)',
                                    outline: 'none',
                                    cursor: 'pointer',
                                    height: '30px',
                                }}
                            >
                                <option value="infinite">Infinitas</option>
                                <option value="limited">Limitadas</option>
                            </select>
                            {risk.max_reentries !== undefined && risk.max_reentries >= 0 && (
                                <input
                                    type="number"
                                    value={risk.max_reentries ?? ''}
                                    onChange={(e) => onChange({ ...risk, max_reentries: (e.target.value === '' ? '' : Number(e.target.value)) as any })}
                                    onBlur={() => {
                                        const val = parseInt(String(risk.max_reentries));
                                        onChange({ ...risk, max_reentries: isNaN(val) ? 2 : Math.max(0, val) });
                                    }}
                                    onFocus={(e) => e.target.select()}
                                    style={{
                                        backgroundColor: 'var(--color-ec-bg-sidebar)',
                                        border: '0.5px solid var(--color-ec-border)',
                                        borderRadius: 5,
                                        padding: '5px 8px',
                                        fontSize: 12,
                                        fontWeight: 600,
                                        color: 'var(--color-ec-text-primary)',
                                        fontFamily: 'var(--color-ec-sans)',
                                        outline: 'none',
                                        width: '60px',
                                        height: '30px',
                                        textAlign: 'center',
                                    }}
                                />
                            )}
                        </div>
                    </div>
                )}
            </div>

            {/* Swing Option Card */}
            {applyDay !== 'gap_2_day' && (
                <div style={{
                    display: 'flex',
                    flexDirection: 'column',
                    gap: 16,
                    padding: '20px 0',
                    backgroundColor: 'transparent',
                    borderBottom: '0.5px solid var(--color-ec-border)',
                }}>
                    <div style={{
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        paddingBottom: (risk.swing_option?.active) ? 12 : 0,
                        borderBottom: (risk.swing_option?.active) ? '0.5px solid var(--color-ec-border)' : 'none',
                    }}>
                        <div style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                                <div style={{
                                    width: 3,
                                    height: 14,
                                    borderRadius: 1,
                                    backgroundColor: 'var(--color-ec-copper)',
                                }} />
                                <h2 style={{
                                    fontFamily: 'var(--color-ec-sans)',
                                    fontSize: 13,
                                    fontWeight: 700,
                                    textTransform: 'uppercase',
                                    letterSpacing: '0.08em',
                                    color: 'var(--color-ec-text-high)',
                                    margin: 0,
                                }}>Opción Swing</h2>
                            </div>
                            <span style={{
                                fontFamily: 'var(--color-ec-sans)',
                                fontSize: 10,
                                fontWeight: 400,
                                color: 'var(--color-ec-text-muted)',
                                marginTop: 2,
                            }}>Configura esta opción si quieres que el trade se mantenga más allá del día en el que se opera</span>
                        </div>
                        <div className="flex items-center gap-2">
                            <span style={{
                                fontFamily: 'var(--color-ec-sans)',
                                fontSize: 10,
                                fontWeight: 700,
                                color: 'var(--color-ec-text-muted)',
                            }}>{risk.swing_option?.active ? 'YES' : 'NO'}</span>
                            <div
                                className={`w-8 h-4 rounded-full relative cursor-pointer transition-colors ${risk.swing_option?.active ? 'bg-[var(--color-ec-copper)]' : 'bg-muted'}`}
                                onClick={() => {
                                    const nextActive = !risk.swing_option?.active;
                                    const defaultTarget = applyDay === 'gap_1_day' ? 'gap_2_day' : 'gap_1_day';
                                    onChange({
                                        ...risk,
                                        swing_option: {
                                            active: nextActive,
                                            target_day: risk.swing_option?.target_day || defaultTarget
                                        }
                                    });
                                }}
                            >
                                <div className={`absolute top-0.5 w-3 h-3 rounded-full bg-white transition-all shadow-sm ${risk.swing_option?.active ? 'left-4.5' : 'left-0.5'}`}></div>
                            </div>
                        </div>
                    </div>

                    {/* Conditional sub-options */}
                    {risk.swing_option?.active && (
                        <div className="animate-in fade-in duration-200" style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                            <span style={{
                                fontFamily: 'var(--color-ec-sans)',
                                fontSize: 10,
                                fontWeight: 700,
                                color: 'var(--color-ec-text-secondary)',
                                textTransform: 'uppercase',
                                letterSpacing: '0.05em'
                            }}>
                                Mantener trade abierto hasta:
                            </span>
                            
                            {applyDay === 'gap_day' ? (
                                <div style={{ display: 'flex', gap: 8 }}>
                                    <button
                                        type="button"
                                        onClick={() => onChange({
                                            ...risk,
                                            swing_option: { ...risk.swing_option!, target_day: 'gap_1_day' }
                                        })}
                                        style={{
                                            flex: 1,
                                            padding: '8px 12px',
                                            borderRadius: 5,
                                            fontSize: 11,
                                            fontWeight: 600,
                                            fontFamily: 'var(--color-ec-sans)',
                                            cursor: 'pointer',
                                            transition: 'all 150ms ease',
                                            backgroundColor: risk.swing_option?.target_day === 'gap_1_day' ? 'rgba(216, 122, 61, 0.15)' : 'var(--color-ec-bg-surface)',
                                            border: risk.swing_option?.target_day === 'gap_1_day' ? '1px solid var(--color-ec-copper)' : '0.5px solid var(--color-ec-border)',
                                            color: risk.swing_option?.target_day === 'gap_1_day' ? 'var(--color-ec-text-high)' : 'var(--color-ec-text-muted)',
                                        }}
                                    >
                                        Gap +1 Day
                                    </button>
                                    <button
                                        type="button"
                                        onClick={() => onChange({
                                            ...risk,
                                            swing_option: { ...risk.swing_option!, target_day: 'gap_2_day' }
                                        })}
                                        style={{
                                            flex: 1,
                                            padding: '8px 12px',
                                            borderRadius: 5,
                                            fontSize: 11,
                                            fontWeight: 600,
                                            fontFamily: 'var(--color-ec-sans)',
                                            cursor: 'pointer',
                                            transition: 'all 150ms ease',
                                            backgroundColor: risk.swing_option?.target_day === 'gap_2_day' ? 'rgba(216, 122, 61, 0.15)' : 'var(--color-ec-bg-surface)',
                                            border: risk.swing_option?.target_day === 'gap_2_day' ? '1px solid var(--color-ec-copper)' : '0.5px solid var(--color-ec-border)',
                                            color: risk.swing_option?.target_day === 'gap_2_day' ? 'var(--color-ec-text-high)' : 'var(--color-ec-text-muted)',
                                        }}
                                    >
                                        Gap +2 Day
                                    </button>
                                </div>
                            ) : (
                                <div style={{ display: 'flex', gap: 8 }}>
                                    <button
                                        type="button"
                                        disabled
                                        style={{
                                            flex: 1,
                                            padding: '8px 12px',
                                            borderRadius: 5,
                                            fontSize: 11,
                                            fontWeight: 600,
                                            fontFamily: 'var(--color-ec-sans)',
                                            backgroundColor: 'rgba(216, 122, 61, 0.15)',
                                            border: '1px solid var(--color-ec-copper)',
                                            color: 'var(--color-ec-text-high)',
                                            cursor: 'not-allowed'
                                        }}
                                    >
                                        Gap +2 Day
                                    </button>
                                </div>
                            )}
                        </div>
                    )}
                </div>
            )}

        </div>
    );
};

export const RiskManagementComponent = React.memo(RiskManagementComponentInner);
RiskManagementComponent.displayName = "RiskManagementComponent";
