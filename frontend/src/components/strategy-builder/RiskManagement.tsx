
import React from 'react';
import { RiskManagement, RiskType, RiskSettings, TakeProfitMode, PartialTakeProfit } from '@/types/strategy';
import { PlusCircle, Trash2, Info } from 'lucide-react';

interface Props {
    risk: RiskManagement;
    onChange: (risk: RiskManagement) => void;
}

export const RiskManagementComponent: React.FC<Props> = ({ risk, onChange }) => {

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
        const lastDist = currentPartials.length > 0 ? currentPartials[currentPartials.length - 1].distance_pct : 3.0;
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
            partial_take_profits: risk.partial_take_profits.filter((_, i) => i !== index)
        });
    };

    const updatePartial = (index: number, field: keyof PartialTakeProfit, value: number) => {
        onChange({
            ...risk,
            partial_take_profits: risk.partial_take_profits.map((p, i) =>
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
                    paddingBottom: (risk.use_hard_stop !== false) ? 12 : 0,
                    borderBottom: (risk.use_hard_stop !== false) ? '0.5px solid var(--color-ec-border)' : 'none',
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
                            }}>Hard Stop Loss</h2>
                        </div>
                        <span style={{
                            fontFamily: 'var(--color-ec-sans)',
                            fontSize: 10,
                            fontWeight: 400,
                            color: 'var(--color-ec-text-muted)',
                            marginTop: 2,
                        }}>Define maximum loss tolerance per trade</span>
                    </div>
                    <div className="flex items-center gap-2">
                        <span style={{
                            fontFamily: 'var(--color-ec-sans)',
                            fontSize: 10,
                            fontWeight: 700,
                            color: 'var(--color-ec-text-muted)',
                        }}>{risk.use_hard_stop !== false ? 'ON' : 'OFF'}</span>
                        <div
                            className={`w-8 h-4 rounded-full relative cursor-pointer transition-colors ${risk.use_hard_stop !== false ? 'bg-ec-loss/70' : 'bg-muted'}`}
                            onClick={() => onChange({ ...risk, use_hard_stop: risk.use_hard_stop === false })}
                        >
                            <div className={`absolute top-0.5 w-3 h-3 rounded-full bg-white transition-all shadow-sm ${risk.use_hard_stop !== false ? 'left-4.5' : 'left-0.5'}`}></div>
                        </div>
                    </div>
                </div>

                {/* Body */}
                {(risk.use_hard_stop !== false) && (
                    <div className="flex gap-2 animate-in fade-in duration-200">
                        <select
                            value={risk.hard_stop.type}
                            onChange={(e) => updateRiskSetting('hard_stop', 'type', e.target.value)}
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
                            }}
                        >
                            {Object.values(RiskType).map(type => (
                                <option key={type} value={type}>{type}</option>
                            ))}
                        </select>
                        <input
                            type="number"
                            value={risk.hard_stop.value}
                            onChange={(e) => updateRiskSetting('hard_stop', 'value', Number(e.target.value))}
                            style={{
                                backgroundColor: 'var(--color-ec-bg-sidebar)',
                                border: '0.5px solid var(--color-ec-border)',
                                borderRadius: 5,
                                padding: '7px 10px',
                                fontSize: 13,
                                fontWeight: 600,
                                color: 'var(--color-ec-text-primary)',
                                fontFamily: 'var(--color-ec-sans)',
                                outline: 'none',
                                flex: 1,
                            }}
                        />
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
                    paddingBottom: (risk.use_take_profit !== false) ? 12 : 0,
                    borderBottom: (risk.use_take_profit !== false) ? '0.5px solid var(--color-ec-border)' : 'none',
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
                        }}>Define target profit and exit scaling</span>
                    </div>
                    <div className="flex items-center gap-2">
                        <span style={{
                            fontFamily: 'var(--color-ec-sans)',
                            fontSize: 10,
                            fontWeight: 700,
                            color: 'var(--color-ec-text-muted)',
                        }}>{risk.use_take_profit !== false ? 'ON' : 'OFF'}</span>
                        <div
                            className={`w-8 h-4 rounded-full relative cursor-pointer transition-colors ${risk.use_take_profit !== false ? 'bg-ec-profit/70' : 'bg-muted'}`}
                            onClick={() => onChange({ ...risk, use_take_profit: risk.use_take_profit === false })}
                        >
                            <div className={`absolute top-0.5 w-3 h-3 rounded-full bg-white transition-all shadow-sm ${risk.use_take_profit !== false ? 'left-4.5' : 'left-0.5'}`}></div>
                        </div>
                    </div>
                </div>

                {/* Body */}
                {(risk.use_take_profit !== false) && (
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
                            <div className="flex gap-2 animate-in fade-in zoom-in-95 duration-200">
                                <select
                                    value={risk.take_profit.type}
                                    onChange={(e) => updateRiskSetting('take_profit', 'type', e.target.value)}
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
                                    }}
                                >
                                    {Object.values(RiskType).map(type => (
                                        <option key={type} value={type}>{type}</option>
                                    ))}
                                </select>
                                <div className="relative flex-1">
                                    <input
                                        type="number"
                                        value={risk.take_profit.value}
                                        onChange={(e) => updateRiskSetting('take_profit', 'value', Number(e.target.value))}
                                        style={{
                                            backgroundColor: 'var(--color-ec-bg-sidebar)',
                                            border: '0.5px solid var(--color-ec-border)',
                                            borderRadius: 5,
                                            padding: '7px 10px',
                                            fontSize: 13,
                                            fontWeight: 600,
                                            color: 'var(--color-ec-text-primary)',
                                            fontFamily: 'var(--color-ec-sans)',
                                            outline: 'none',
                                            width: '100%',
                                        }}
                                    />
                                    <span className="absolute right-3 top-1/2 -translate-y-1/2 text-[10px] font-bold text-muted-foreground/40">%</span>
                                </div>
                            </div>
                        ) : (
                            <div className="space-y-4 animate-in fade-in zoom-in-95 duration-200">
                                <div className="space-y-2">
                                    {risk.partial_take_profits.map((partial, idx) => (
                                        <div key={idx} className="group relative"
                                            style={{
                                                backgroundColor: 'var(--color-ec-bg-elevated)',
                                                border: '0.5px solid var(--color-ec-border)',
                                                borderRadius: 5,
                                                padding: '12px 14px',
                                            }}
                                            onMouseEnter={(e) => (e.currentTarget.style.borderColor = 'var(--color-ec-profit)')}
                                            onMouseLeave={(e) => (e.currentTarget.style.borderColor = 'var(--color-ec-border)')}
                                        >
                                            <div className="flex items-center justify-between">
                                                <span className="text-[10px] font-black text-ec-profit/70 tracking-tighter">PARTIAL #{idx + 1}</span>
                                                {risk.partial_take_profits.length > 1 && (
                                                    <button
                                                        onClick={() => removePartial(idx)}
                                                        className="p-1 text-muted-foreground hover:text-ec-loss transition-colors opacity-0 group-hover:opacity-100"
                                                    >
                                                        <Trash2 className="w-3.5 h-3.5" />
                                                    </button>
                                                )}
                                            </div>
                                            
                                            <div className="grid grid-cols-2 gap-4">
                                                <div className="space-y-1.5">
                                                    <label className="text-[9px] font-bold text-muted-foreground uppercase opacity-50">Distancia %</label>
                                                    <div className="relative">
                                                        <input
                                                            type="number"
                                                            step="0.1"
                                                            value={partial.distance_pct}
                                                            onChange={(e) => updatePartial(idx, 'distance_pct', Number(e.target.value))}
                                                            className="w-full bg-background/50 border border-border/50 rounded-lg px-2 py-1.5 text-xs font-bold focus:ring-1 focus:ring-[var(--color-ec-profit)]/30"
                                                        />
                                                        <span className="absolute right-2 top-1/2 -translate-y-1/2 text-[9px] font-bold text-muted-foreground/30">%</span>
                                                    </div>
                                                </div>
                                                <div className="space-y-1.5">
                                                    <div className="flex justify-between items-center">
                                                        <label className="text-[9px] font-bold text-muted-foreground uppercase opacity-50">Capital %</label>
                                                        <span className="text-[10px] font-black text-foreground">{partial.capital_pct}%</span>
                                                    </div>
                                                    <input
                                                        type="range"
                                                        min="1"
                                                        max="100"
                                                        value={partial.capital_pct}
                                                        onChange={(e) => updatePartial(idx, 'capital_pct', Number(e.target.value))}
                                                        className="w-full h-1.5 bg-muted rounded-lg appearance-none cursor-pointer accent-[var(--color-ec-profit)]"
                                                    />
                                                </div>
                                            </div>
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
                            }}>Trailing Stop</h2>
                        </div>
                        <span style={{
                            fontFamily: 'var(--color-ec-sans)',
                            fontSize: 10,
                            fontWeight: 400,
                            color: 'var(--color-ec-text-muted)',
                            marginTop: 2,
                        }}>Adjust stop loss dynamically as price hits targets</span>
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
                    <div className="grid grid-cols-2 gap-3 animate-in fade-in duration-200">
                        <div>
                            <label className="block text-[9px] font-bold text-muted-foreground uppercase mb-1.5 opacity-50">Type</label>
                            <select
                                value={risk.trailing_stop.type}
                                onChange={(e) => setTrailingField('type', e.target.value)}
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
                                }}
                            >
                                <option value="Percentage">Percentage</option>
                                <option value="EMA13">EMA 13</option>
                                <option value="HWM">High Water Mark</option>
                            </select>
                        </div>
                        <div>
                            <label className="block text-[9px] font-bold text-muted-foreground uppercase mb-1.5 opacity-50">Distance %</label>
                            <input
                                type="number"
                                step="0.1"
                                value={risk.trailing_stop.buffer_pct}
                                onChange={(e) => setTrailingField('buffer_pct', Number(e.target.value))}
                                style={{
                                    backgroundColor: 'var(--color-ec-bg-sidebar)',
                                    border: '0.5px solid var(--color-ec-border)',
                                    borderRadius: 5,
                                    padding: '7px 10px',
                                    fontSize: 13,
                                    fontWeight: 600,
                                    color: 'var(--color-ec-text-primary)',
                                    fontFamily: 'var(--color-ec-sans)',
                                    outline: 'none',
                                }}
                            />
                        </div>
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
                            }}>Accept Re-entries</h2>
                        </div>
                        <span style={{
                            fontFamily: 'var(--color-ec-sans)',
                            fontSize: 10,
                            fontWeight: 400,
                            color: 'var(--color-ec-text-muted)',
                            marginTop: 2,
                        }}>Allow entering trade again if closed on stop/target</span>
                    </div>
                    <div className="flex items-center gap-2">
                        <span style={{
                            fontFamily: 'var(--color-ec-sans)',
                            fontSize: 10,
                            fontWeight: 700,
                            color: 'var(--color-ec-text-muted)',
                        }}>{risk.accept_reentries !== false ? 'YES' : 'NO'}</span>
                        <div
                            className={`w-8 h-4 rounded-full relative cursor-pointer transition-colors ${risk.accept_reentries !== false ? 'bg-[var(--color-ec-copper)]' : 'bg-muted'}`}
                            onClick={() => onChange({ ...risk, accept_reentries: risk.accept_reentries === false })}
                        >
                            <div className={`absolute top-0.5 w-3 h-3 rounded-full bg-white transition-all shadow-sm ${risk.accept_reentries !== false ? 'left-4.5' : 'left-0.5'}`}></div>
                        </div>
                    </div>
                </div>
            </div>

        </div>
    );
};
