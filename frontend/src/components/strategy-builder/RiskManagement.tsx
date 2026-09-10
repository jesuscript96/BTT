
import React from 'react';
import { RiskManagement, RiskType, RiskSettings, TakeProfitMode, PartialTakeProfit } from '@/types/strategy';
import { PlusCircle, Trash2, Info, HelpCircle } from 'lucide-react';

interface Props {
    risk: RiskManagement;
    onChange: (risk: RiskManagement) => void;
    applyDay?: 'gap_day' | 'gap_1_day' | 'gap_2_day';
    /** Se sigue aceptando para no romper a los llamadores; ya no se usa
     *  desde que se quitó el bloque de "nivel rebasado al entrar". */
    bias?: 'long' | 'short' | null;
}

const RiskManagementComponentInner: React.FC<Props> = ({ risk, onChange, applyDay = 'gap_day' }) => {

    // Cortacircuitos de perdida diaria. Se lee con defaults para que una
    // estrategia guardada antes de que esto existiera no rompa nada.
    const tope = {
        enabled: false,
        unit: 'CASH' as 'CASH' | 'PCT',
        value: 1000,
        on_open_positions: 'LET_RUN' as 'LET_RUN' | 'CLOSE_ALL',
        ...(risk.daily_loss_limit || {}),
    };
    const setTope = (patch: Partial<typeof tope>) =>
        onChange({ ...risk, daily_loss_limit: { ...tope, ...patch } });

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
                                        // El calculo por distancia al SL sirve para CUALQUIER stop
                                        // que de un nivel de precio, no solo el estructural: con "%"
                                        // la distancia es entrada x pct (el dimensionado clasico de
                                        // "arriesgo X con un stop del Y%"). Los dos motores ya lo
                                        // hacen igual (portfolio_sim.py y portfolio_sim_jit.py:722:
                                        // `size = risk_amount / abs(entrada - stop)`). Antes, cambiar
                                        // de Market Structure a % apagaba el interruptor en silencio.
                                        size_by_sl: risk.size_by_sl
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
                                title={
                                    "% — el stop a una distancia fija del precio de entrada.\n" +
                                    "ATR — el stop a N veces el ATR(14) DE LA VELA DE ENTRADA, asi que se " +
                                    "ensancha cuando el ticker se mueve mas y se estrecha cuando se calma. " +
                                    "Durante las primeras velas del dia el ATR todavia no existe y ahi NO se " +
                                    "entra: sin ATR no se sabe cuanto se mueve esto.\n" +
                                    "Market Structure — el stop en un nivel del dia (HOD, PMH, maximo previo...)."
                                }
                            >
                                <option value={RiskType.PERCENTAGE}>%</option>
                                <option value={RiskType.ATR}>ATR</option>
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
                                        <option value="Ultimo pivote alto">\u00daltimo pivote alto</option>
                                        <option value="Ultimo pivote bajo">\u00daltimo pivote bajo</option>
                                    </select>
                                    {/* VELAS DE CONFIRMACION del pivote. Solo sale
                                        con los dos niveles de pivote, porque los
                                        demas no la usan. */}
                                    {(risk.hard_stop.value === 'Ultimo pivote alto'
                                      || risk.hard_stop.value === 'Ultimo pivote bajo') && (
                                        <div className="relative" style={{ width: '92px' }}>
                                            <input
                                                type="number"
                                                min="1"
                                                step="1"
                                                placeholder="3"
                                                value={risk.hard_stop.pivot_window ?? ''}
                                                onChange={(e) => updateRiskSetting('hard_stop', 'pivot_window', e.target.value === '' ? '' : e.target.value)}
                                                onBlur={() => {
                                                    const val = parseInt(String(risk.hard_stop.pivot_window), 10);
                                                    updateRiskSetting('hard_stop', 'pivot_window', isNaN(val) ? 3 : val);
                                                }}
                                                onFocus={(e) => e.target.select()}
                                                title={
                                                    "Velas de CONFIRMACION a cada lado del pivote.\n\n" +
                                                    "Un pivote alto es una vela cuyo maximo supera al de las N velas de su " +
                                                    "izquierda y al de las N de su derecha. Con 1 o 2 salen pivotes de ruido; " +
                                                    "con 8 o mas son fiables pero llegan tarde.\n\n" +
                                                    "El nivel aparece N velas DESPUES de que ocurriera el giro, y ese retardo " +
                                                    "es justo lo que hace que no mire al futuro. Mientras no haya ningun pivote " +
                                                    "confirmado del dia, el motor aplica su respaldo."
                                                }
                                                style={{
                                                    backgroundColor: 'var(--color-ec-bg-sidebar)',
                                                    border: '0.5px solid var(--color-ec-border)',
                                                    borderRadius: 5,
                                                    padding: '7px 34px 7px 8px',
                                                    fontSize: 12,
                                                    fontWeight: 600,
                                                    color: 'var(--color-ec-text-primary)',
                                                    fontFamily: 'var(--color-ec-sans)',
                                                    outline: 'none',
                                                    width: '100%',
                                                    height: '36px',
                                                    textAlign: 'center',
                                                }}
                                            />
                                            <span className="absolute right-2 top-1/2 -translate-y-1/2 text-[9px] font-bold text-muted-foreground/40">
                                                VELAS
                                            </span>
                                        </div>
                                    )}
                                    
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

                                    {/* RESPALDO cuando el nivel no se resuelve: el
                                        pivote aun sin confirmar, un PMH que no
                                        existe, un dia sin datos previos. Era un 5 %
                                        clavado en el codigo. Vacio = 5 %. */}
                                    <div className="relative" style={{ width: '116px' }}>
                                        <input
                                            type="number"
                                            step="0.5"
                                            min="0"
                                            placeholder="5"
                                            value={risk.hard_stop.struct_fallback_pct ?? ''}
                                            onChange={(e) => updateRiskSetting('hard_stop', 'struct_fallback_pct', e.target.value === '' ? '' : e.target.value)}
                                            onBlur={() => {
                                                const val = parseFloat(String(risk.hard_stop.struct_fallback_pct));
                                                updateRiskSetting('hard_stop', 'struct_fallback_pct', isNaN(val) ? undefined : val);
                                            }}
                                            onFocus={(e) => e.target.select()}
                                            title={
                                                "Stop de respaldo, en % del precio de entrada, para cuando el nivel " +
                                                "elegido NO se puede resolver en esa vela.\n\n" +
                                                "Pasa, por ejemplo, con el ultimo pivote mientras no hay ninguno " +
                                                "confirmado del dia, o con un PMH en un ticker que no cotizo en " +
                                                "premercado.\n\n" +
                                                "Vacio = 5 %, que es lo que el motor lleva usando desde siempre. " +
                                                "El respaldo pasa por los mismos topes que el nivel: Cangrejo A y B, " +
                                                "hibrido y «Shares por SL»."
                                            }
                                            style={{
                                                backgroundColor: 'var(--color-ec-bg-sidebar)',
                                                border: '0.5px dashed var(--color-ec-border)',
                                                borderRadius: 5,
                                                padding: '7px 46px 7px 8px',
                                                fontSize: 12,
                                                fontWeight: 600,
                                                color: 'var(--color-ec-text-primary)',
                                                fontFamily: 'var(--color-ec-sans)',
                                                outline: 'none',
                                                width: '100%',
                                                height: '36px',
                                                textAlign: 'center',
                                            }}
                                        />
                                        <span className="absolute right-2 top-1/2 -translate-y-1/2 text-[9px] font-bold text-muted-foreground/40">
                                            RESPALDO
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
                                        title={risk.hard_stop.type === RiskType.ATR
                                            ? "Cuantos ATR de distancia. Con 2, el stop de un corto va a entrada + 2 x ATR(14) de la vela en que se entra."
                                            : "Distancia del stop en % del precio de entrada."}
                                        style={{
                                            backgroundColor: 'var(--color-ec-bg-sidebar)',
                                            border: '0.5px solid var(--color-ec-border)',
                                            borderRadius: 5,
                                            // Con ATR el sufijo es "xATR" y necesita mas hueco que "%".
                                            padding: risk.hard_stop.type === RiskType.ATR
                                                ? '7px 38px 7px 10px' : '7px 24px 7px 10px',
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
                                        {risk.hard_stop.type === RiskType.ATR ? '\u00d7ATR' : '%'}
                                    </span>
                                </div>
                            )}
                            {/* RESPALDO DEL ATR. Durante las primeras velas del dia el
                                ATR(14) todavia no existe. Vacio o 0 = no se entra en ese
                                tramo; con un numero, ahi se usa un stop en % del precio.
                                El respaldo pasa por los MISMOS topes que el ATR (Cangrejo
                                A y B, hibrido y «Shares por SL»), porque todos miran el
                                precio del stop y no la fraccion. */}
                            {risk.hard_stop.type === RiskType.ATR && (
                                <div className="relative" style={{ width: '150px' }}>
                                    <input
                                        type="number"
                                        step="0.5"
                                        min="0"
                                        placeholder="sin respaldo"
                                        value={risk.hard_stop.atr_fallback_pct ?? ''}
                                        onChange={(e) => updateRiskSetting('hard_stop', 'atr_fallback_pct', e.target.value === '' ? '' : e.target.value)}
                                        onBlur={() => {
                                            const val = parseFloat(String(risk.hard_stop.atr_fallback_pct));
                                            updateRiskSetting('hard_stop', 'atr_fallback_pct', isNaN(val) ? undefined : val);
                                        }}
                                        onFocus={(e) => e.target.select()}
                                        title={
                                            "Stop de respaldo para las primeras velas del dia, cuando el ATR(14) " +
                                            "todavia no existe (le faltan velas).\n\n" +
                                            "Vacio o 0: en ese tramo NO se entra. Es lo mas conservador — sin ATR " +
                                            "no se sabe cuanto se mueve el ticker.\n" +
                                            "Con un numero: ahi se usa un stop a ese % del precio de entrada, y en " +
                                            "cuanto el ATR existe se vuelve a el.\n\n" +
                                            "El respaldo respeta los mismos topes que el ATR: Estilo Cangrejo (A y B), " +
                                            "stop hibrido y «Shares por SL»."
                                        }
                                        style={{
                                            backgroundColor: 'var(--color-ec-bg-sidebar)',
                                            border: '0.5px dashed var(--color-ec-border)',
                                            borderRadius: 5,
                                            padding: '7px 58px 7px 10px',
                                            fontSize: 12,
                                            fontWeight: 600,
                                            color: 'var(--color-ec-text-primary)',
                                            fontFamily: 'var(--color-ec-sans)',
                                            outline: 'none',
                                            width: '100%',
                                            height: '36px',
                                            textAlign: 'center',
                                        }}
                                    />
                                    <span className="absolute right-2 top-1/2 -translate-y-1/2 text-[9px] font-bold text-muted-foreground/40">
                                        % SIN ATR
                                    </span>
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

                            {/* ── STOP LOSS HÍBRIDO ────────────────────────────────
                                Justo debajo del anterior y excluyente con él: los dos
                                apagados = por valor de mercado; uno u otro encendido =
                                ese manda.

                                Va SIEMPRE por SL (por eso enciende `size_by_sl`), pero
                                topa la exposición para que un evento de cola no cueste
                                más de lo que aceptas perder. Los dos modos clásicos
                                fallan en extremos opuestos: por SL escalas bien pero un
                                stop muy ceñido dispara el tamaño y un hueco brutal deja
                                debiendo dinero; por MV acotas el desastre pero no
                                escalas igual. */}
                            <div style={{
                                marginTop: 10,
                                paddingTop: 10,
                                borderTop: '0.5px dotted var(--color-ec-border)',
                                display: 'flex',
                                flexDirection: 'column',
                                gap: 4,
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
                                            Cálculo de Shares por Stop Loss Híbrido
                                        </span>
                                    </div>
                                    <div className="flex items-center gap-2">
                                        <span style={{
                                            fontFamily: 'var(--color-ec-sans)',
                                            fontSize: 10,
                                            fontWeight: 700,
                                            color: 'var(--color-ec-text-muted)',
                                        }}>{risk.hybrid_stop ? 'YES' : 'NO'}</span>
                                        <div
                                            className={`w-8 h-4 rounded-full relative cursor-pointer transition-colors ${risk.hybrid_stop ? 'bg-ec-copper/70' : 'bg-muted'}`}
                                            onClick={() => {
                                                const on = !risk.hybrid_stop;
                                                // Encenderlo implica ir por SL: el híbrido ES el
                                                // modo por SL con techo. Apagarlo deja size_by_sl
                                                // como estaba, para no cambiar el dimensionado
                                                // sin que se haya pedido.
                                                // EXCLUYENTE con Estilo Cangrejo: son dos
                                                // techos distintos sobre el mismo tamaño y
                                                // tenerlos a la vez no dice nada al usuario
                                                // sobre cuál recortó. El motor arbitra a
                                                // favor de Cangrejo, así que aquí se apaga
                                                // para que la UI diga la verdad.
                                                onChange({
                                                    ...risk,
                                                    hybrid_stop: on,
                                                    size_by_sl: on ? true : risk.size_by_sl,
                                                    cangrejo_active: on ? false : risk.cangrejo_active,
                                                });
                                            }}
                                        >
                                            <div className={`absolute top-0.5 w-3 h-3 rounded-full bg-white transition-all shadow-sm ${risk.hybrid_stop ? 'left-4.5' : 'left-0.5'}`}></div>
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
                                    Calcula nº Shares por distancia al Stop Loss, pero sin exponer más de lo que aceptas perder ante un evento extremo
                                </span>

                                {risk.hybrid_stop && (
                                    <div style={{ display: 'flex', gap: 10, marginLeft: 18, marginTop: 6 }}>
                                        <label style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
                                            <span style={{
                                                fontFamily: 'var(--color-ec-sans)',
                                                fontSize: 9.5,
                                                color: 'var(--color-ec-text-secondary)',
                                            }}>Evento adverso máx. (%)</span>
                                            <input
                                                type="number"
                                                min={1}
                                                step={100}
                                                value={risk.hybrid_black_swan_pct ?? ''}
                                                placeholder="5000"
                                                title="El peor movimiento en contra que quieres contemplar."
                                                onChange={(e) => onChange({
                                                    ...risk,
                                                    hybrid_black_swan_pct: e.target.value === '' ? null : Number(e.target.value),
                                                })}
                                                style={{
                                                    width: 92,
                                                    padding: '4px 6px',
                                                    fontSize: 11,
                                                    backgroundColor: 'var(--color-ec-bg-sidebar)',
                                                    border: '0.5px solid var(--color-ec-border)',
                                                    borderRadius: 4,
                                                    color: 'var(--color-ec-text-primary)',
                                                    fontFamily: 'var(--color-ec-mono)',
                                                    textAlign: 'right',
                                                }}
                                            />
                                        </label>
                                        <label style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
                                            <span style={{
                                                fontFamily: 'var(--color-ec-sans)',
                                                fontSize: 9.5,
                                                color: 'var(--color-ec-text-secondary)',
                                            }}>De mi cuenta, perder máx. (%)</span>
                                            <input
                                                type="number"
                                                min={1}
                                                max={100}
                                                step={5}
                                                value={risk.hybrid_max_loss_pct ?? ''}
                                                placeholder="50"
                                                title="Sobre tu CUENTA ENTERA, no sobre la posición."
                                                onChange={(e) => onChange({
                                                    ...risk,
                                                    hybrid_max_loss_pct: e.target.value === '' ? null : Number(e.target.value),
                                                })}
                                                style={{
                                                    width: 92,
                                                    padding: '4px 6px',
                                                    fontSize: 11,
                                                    backgroundColor: 'var(--color-ec-bg-sidebar)',
                                                    border: '0.5px solid var(--color-ec-border)',
                                                    borderRadius: 4,
                                                    color: 'var(--color-ec-text-primary)',
                                                    fontFamily: 'var(--color-ec-mono)',
                                                    textAlign: 'right',
                                                }}
                                            />
                                        </label>
                                    </div>
                                )}

                                <span style={{
                                    fontFamily: 'var(--color-ec-sans)',
                                    fontSize: 10,
                                    color: 'var(--color-ec-text-secondary)',
                                    fontStyle: 'italic',
                                    marginLeft: 18,
                                    marginTop: 4,
                                    lineHeight: '1.3',
                                }}>
                                    {risk.hybrid_stop && risk.hybrid_black_swan_pct && risk.hybrid_max_loss_pct
                                        ? `Nunca expone más del ${(risk.hybrid_max_loss_pct / risk.hybrid_black_swan_pct * 100).toFixed(2)}% del capital: si el precio se fuera un ${risk.hybrid_black_swan_pct}% en contra, perderías el ${risk.hybrid_max_loss_pct}% de la cuenta.`
                                        : ''}
                                </span>
                            </div>
                        </div>
                    </div>
                )}
            </div>


            {/* ── ESTILO CANGREJO ──────────────────────────────────────────
                PRD de Álvaro, 8-sep-2026 (`docs/PRD_ESTILO_CANGREJO.md`).

                EL PROBLEMA: con SL por estructura (previous max + 10 %, p. ej.)
                la distancia entry→SL cambia en cada entrada. Con el mismo
                market value, unos stops cuestan poco y otros cuestan
                muchísimo, y no había forma sencilla de ponerle techo.

                DOS MODOS Y SE ELIGE UNO — decisión de Álvaro: «debe ser o una
                u otra». La primera versión tenía cuatro topes sueltos y
                resultó poco intuitiva: cuatro números no cuentan qué va a
                pasar. Un modo visible cada vez sí. */}
            <div style={{
                marginTop: 12,
                padding: 10,
                border: '0.5px solid var(--color-ec-border)',
                borderRadius: 6,
                display: 'flex',
                flexDirection: 'column',
                gap: 4,
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
                            Estilo Cangrejo
                        </span>
                    </div>
                    <div className="flex items-center gap-2">
                        <span style={{
                            fontFamily: 'var(--color-ec-sans)',
                            fontSize: 10,
                            fontWeight: 700,
                            color: 'var(--color-ec-text-muted)',
                        }}>{risk.cangrejo_active ? 'YES' : 'NO'}</span>
                        <div
                            className={`w-8 h-4 rounded-full relative cursor-pointer transition-colors ${risk.cangrejo_active ? 'bg-ec-copper/70' : 'bg-muted'}`}
                            onClick={() => {
                                const on = !risk.cangrejo_active;
                                onChange({
                                    ...risk,
                                    cangrejo_active: on,
                                    // Al encender hay que tener SIEMPRE un modo:
                                    // sin él la tarjeta no enseñaría ningún campo
                                    // y quedaría activa sin hacer nada.
                                    cangrejo_mode: on ? (risk.cangrejo_mode ?? 'perdida') : risk.cangrejo_mode,
                                    // Excluyente con el híbrido (el motor arbitra
                                    // a favor de Cangrejo; aquí se refleja).
                                    hybrid_stop: on ? false : risk.hybrid_stop,
                                    // Los dos topes de market value son INERTES y
                                    // no tienen UI. Se limpian al activar para que
                                    // un borrador viejo no arrastre capas
                                    // invisibles que nadie puede ver ni quitar.
                                    cangrejo_max_mv_entry_pct: on ? null : risk.cangrejo_max_mv_entry_pct,
                                    cangrejo_max_mv_pyr_pct: on ? null : risk.cangrejo_max_mv_pyr_pct,
                                });
                            }}
                        >
                            <div className={`absolute top-0.5 w-3 h-3 rounded-full bg-white transition-all shadow-sm ${risk.cangrejo_active ? 'left-4.5' : 'left-0.5'}`}></div>
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
                    Acota cada operación: o limitando el recorrido hasta el stop, o limitando lo que puede costarte. Es un techo — solo recorta, nunca agranda.
                </span>

                {risk.cangrejo_active && (
                    <div style={{ marginLeft: 18, marginTop: 8, display: 'flex', flexDirection: 'column', gap: 8 }}>
                        {/* Selector de modo. Botones y no un desplegable: son
                            dos y el usuario tiene que ver los dos a la vez para
                            entender que son alternativas. */}
                        <div style={{ display: 'flex', gap: 6 }}>
                            {([
                                { id: 'recorrido', label: 'Recorrido máx. del SL' },
                                { id: 'perdida', label: 'Pérdida máx. por trade' },
                            ] as const).map((m) => {
                                const activo = (risk.cangrejo_mode ?? 'perdida') === m.id;
                                return (
                                    <button
                                        key={m.id}
                                        type="button"
                                        onClick={() => onChange({
                                            ...risk,
                                            cangrejo_mode: m.id,
                                            // Cambiar de modo LIMPIA el del otro. Si
                                            // no, un número escondido seguiría
                                            // recortando desde un campo que ya no se
                                            // ve — el motor aplica lo que le llegue.
                                            cangrejo_max_sl_dist_pct: m.id === 'recorrido' ? risk.cangrejo_max_sl_dist_pct : null,
                                            cangrejo_max_loss_at_sl_pct: m.id === 'perdida' ? risk.cangrejo_max_loss_at_sl_pct : null,
                                        })}
                                        style={{
                                            flex: 1,
                                            padding: '5px 8px',
                                            fontSize: 10,
                                            fontFamily: 'var(--color-ec-sans)',
                                            fontWeight: activo ? 700 : 400,
                                            borderRadius: 4,
                                            cursor: 'pointer',
                                            border: activo
                                                ? '0.5px solid var(--color-ec-copper)'
                                                : '0.5px solid var(--color-ec-border)',
                                            backgroundColor: activo
                                                ? 'var(--color-ec-copper)'
                                                : 'var(--color-ec-bg-sidebar)',
                                            color: activo ? '#fff' : 'var(--color-ec-text-secondary)',
                                        }}
                                    >
                                        {m.label}
                                    </button>
                                );
                            })}
                        </div>

                        {(risk.cangrejo_mode ?? 'perdida') === 'recorrido' ? (
                            <label style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
                                <span style={{
                                    fontFamily: 'var(--color-ec-sans)',
                                    fontSize: 9.5,
                                    color: 'var(--color-ec-text-secondary)',
                                }}>Distancia máx. entrada → SL (%)</span>
                                <input
                                    type="number"
                                    min={0.1}
                                    step={5}
                                    value={risk.cangrejo_max_sl_dist_pct ?? ''}
                                    placeholder="50"
                                    title="Si la estructura deja el stop más lejos, se aprieta hasta este porcentaje — y ahí se sale de verdad."
                                    onChange={(e) => onChange({
                                        ...risk,
                                        cangrejo_max_sl_dist_pct: e.target.value === '' ? null : Number(e.target.value),
                                    })}
                                    style={{
                                        width: 92,
                                        padding: '4px 6px',
                                        fontSize: 11,
                                        backgroundColor: 'var(--color-ec-bg-sidebar)',
                                        border: '0.5px solid var(--color-ec-border)',
                                        borderRadius: 4,
                                        color: 'var(--color-ec-text-primary)',
                                        fontFamily: 'var(--color-ec-mono)',
                                        textAlign: 'right',
                                    }}
                                />
                            </label>
                        ) : (
                            <label style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
                                <span style={{
                                    fontFamily: 'var(--color-ec-sans)',
                                    fontSize: 9.5,
                                    color: 'var(--color-ec-text-secondary)',
                                }}>De mi cuenta, perder máx. por trade (%)</span>
                                <input
                                    type="number"
                                    min={0.1}
                                    max={100}
                                    step={0.5}
                                    value={risk.cangrejo_max_loss_at_sl_pct ?? ''}
                                    placeholder="3"
                                    title="Sobre tu CUENTA ENTERA. El stop no se mueve: lo que se encoge es el tamaño."
                                    onChange={(e) => onChange({
                                        ...risk,
                                        cangrejo_max_loss_at_sl_pct: e.target.value === '' ? null : Number(e.target.value),
                                    })}
                                    style={{
                                        width: 92,
                                        padding: '4px 6px',
                                        fontSize: 11,
                                        backgroundColor: 'var(--color-ec-bg-sidebar)',
                                        border: '0.5px solid var(--color-ec-border)',
                                        borderRadius: 4,
                                        color: 'var(--color-ec-text-primary)',
                                        fontFamily: 'var(--color-ec-mono)',
                                        textAlign: 'right',
                                    }}
                                />
                            </label>
                        )}
                    </div>
                )}

                {/* La frase que traduce el número a lo que va a pasar. Es el
                    motivo de simplificar a dos modos: cuatro topes sueltos no
                    se podían explicar en una línea. */}
                <span style={{
                    fontFamily: 'var(--color-ec-sans)',
                    fontSize: 10,
                    color: 'var(--color-ec-text-secondary)',
                    fontStyle: 'italic',
                    marginLeft: 18,
                    marginTop: 6,
                    lineHeight: '1.3',
                }}>
                    {!risk.cangrejo_active
                        ? ''
                        : (risk.cangrejo_mode ?? 'perdida') === 'recorrido'
                            ? (risk.cangrejo_max_sl_dist_pct
                                ? `El stop nunca queda a más del ${risk.cangrejo_max_sl_dist_pct}% de tu entrada: si la estructura lo pone más lejos, se aprieta y SALES AHÍ. Cambia dónde sales, no cuánto pones.`
                                : 'Cambia DÓNDE sales: aprieta el stop lejano hasta el porcentaje que pongas. El tamaño no se toca.')
                            : (risk.cangrejo_max_loss_at_sl_pct
                                ? `Si salta el stop no pierdes más del ${risk.cangrejo_max_loss_at_sl_pct}% de la cuenta: el stop se queda donde dice la estructura y lo que se encoge es el tamaño. Cambia cuánto pones, no dónde sales.`
                                : 'Cambia CUÁNTO pones: encoge el tamaño para que el stop nunca cueste más de ese % de la cuenta. El stop no se mueve.')}
                </span>
            </div>


            {/* ── Cortacircuitos de pérdida diaria ──────────────────────────
                No es un stop: es un gobernador de riesgo de la SESIÓN entera.
                Va aquí, debajo del stop fijo, porque es donde el usuario lo
                busca, pero con tarjeta propia para que no se confunda con la
                tolerancia por operación. */}
            <div style={{
                display: 'flex',
                flexDirection: 'column',
                gap: 16,
                padding: '20px 0',
                backgroundColor: 'transparent',
                // borderBottom, no borderTop: es la convencion del resto de
                // tarjetas de este panel. Con borderTop salia linea doble
                // arriba (la de Stop Loss Fijo mas la mia) y ninguna abajo.
                borderBottom: '0.5px solid var(--color-ec-border)',
            }}>
                <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between' }}>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                            <div style={{ width: 3, height: 14, borderRadius: 1, backgroundColor: 'var(--color-ec-loss)' }} />
                            <h2 style={{
                                fontFamily: 'var(--color-ec-sans)',
                                fontSize: 13,
                                fontWeight: 700,
                                textTransform: 'uppercase',
                                letterSpacing: '0.08em',
                                color: 'var(--color-ec-text-high)',
                                margin: 0,
                            }}>Límite de pérdida diaria</h2>
                        </div>
                        <span style={{
                            fontFamily: 'var(--color-ec-sans)',
                            fontSize: 10,
                            fontWeight: 400,
                            color: 'var(--color-ec-text-muted)',
                            marginTop: 2,
                        }}>Si la sesión acumula esta pérdida, deja de operar hasta el día siguiente</span>
                    </div>
                    <div className="flex items-center gap-2">
                        <span style={{
                            fontFamily: 'var(--color-ec-sans)',
                            fontSize: 10,
                            fontWeight: 700,
                            color: 'var(--color-ec-text-muted)',
                        }}>{tope.enabled ? 'ON' : 'OFF'}</span>
                        <div
                            className={`w-8 h-4 rounded-full relative cursor-pointer transition-colors ${tope.enabled ? 'bg-ec-loss/70' : 'bg-muted'}`}
                            onClick={() => setTope({ enabled: !tope.enabled })}
                        >
                            <div className={`absolute top-0.5 w-3 h-3 rounded-full bg-white transition-all shadow-sm ${tope.enabled ? 'left-4.5' : 'left-0.5'}`}></div>
                        </div>
                    </div>
                </div>

                {tope.enabled && (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }} className="animate-in fade-in duration-200">
                        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                            <select
                                value={tope.unit}
                                onChange={(e) => setTope({ unit: e.target.value as 'CASH' | 'PCT' })}
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
                                    width: '150px',
                                }}
                            >
                                <option value="CASH">$ fijos</option>
                                <option value="PCT">% del capital</option>
                            </select>

                            <div style={{ position: 'relative', width: '120px' }}>
                                <input
                                    type="number"
                                    step={tope.unit === 'PCT' ? 0.1 : 50}
                                    min={0}
                                    value={tope.value ?? ''}
                                    onChange={(e) => setTope({ value: e.target.value === '' ? ('' as unknown as number) : parseFloat(e.target.value) })}
                                    onBlur={() => {
                                        const v = parseFloat(String(tope.value));
                                        setTope({ value: isNaN(v) || v < 0 ? 0 : v });
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
                                <span className="absolute right-3 top-1/2 -translate-y-1/2 text-[10px] font-bold text-muted-foreground/40">
                                    {tope.unit === 'PCT' ? '%' : '$'}
                                </span>
                            </div>
                        </div>

                        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                            <span style={{
                                fontFamily: 'var(--color-ec-sans)',
                                fontSize: 10,
                                fontWeight: 700,
                                textTransform: 'uppercase',
                                letterSpacing: '0.05em',
                                color: 'var(--color-ec-text-secondary)',
                            }}>
                                Posiciones abiertas al saltar
                            </span>
                            <select
                                value={tope.on_open_positions}
                                onChange={(e) => setTope({ on_open_positions: e.target.value as 'LET_RUN' | 'CLOSE_ALL' })}
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
                                    width: '100%',
                                }}
                            >
                                <option value="LET_RUN">Dejarlas correr hasta su salida normal</option>
                                <option value="CLOSE_ALL">Cerrarlas en el momento del corte</option>
                            </select>
                        </div>

                        <div style={{
                            marginTop: 2,
                            paddingTop: 10,
                            borderTop: '0.5px dotted var(--color-ec-border)',
                            display: 'flex',
                            gap: 6,
                            alignItems: 'flex-start',
                        }}>
                            <Info size={12} style={{ color: 'var(--color-ec-copper)', flexShrink: 0, marginTop: 1 }} />
                            <span style={{
                                fontFamily: 'var(--color-ec-sans)',
                                fontSize: 10,
                                lineHeight: 1.5,
                                color: 'var(--color-ec-text-muted)',
                            }}>
                                Cuenta la pérdida <strong>ya realizada</strong> de la sesión, según van cerrando
                                las operaciones. Al cruzar el límite no se abre nada más ese día: ni entradas
                                nuevas, ni reentradas, ni añadidos de pirámide.
                                {tope.unit === 'PCT' && ' El % se mide sobre el capital con el que abrió el día.'}
                                <br />
                                <strong style={{ color: 'var(--color-ec-warning)' }}>No puede evitar que una sola
                                operación se pase del límite de golpe</strong> — sólo impide la siguiente. Y si en
                                ese día todas las posiciones cierran a la vez (p. ej. una estrategia que aguanta al
                                cierre de sesión), no queda nada abierto que cortar y el día puede acabar por debajo
                                del límite. Los días en que eso ocurra salen marcados en los resultados.
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
                                        const defaultVal = newType === RiskType.TIME ? 30 : (newType === 'Hour' ? '15:30' : 6.0);
                                        onChange({
                                            ...risk,
                                            take_profit: {
                                                ...risk.take_profit,
                                                type: newType,
                                                value: defaultVal
                                            }
                                        });
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
                                    <option value="Hour">Hora específica</option>
                                </select>
                                <div className="relative" style={{ width: '120px' }}>
                                    <input
                                        type={risk.take_profit.type === 'Hour' ? 'time' : 'number'}
                                        step={risk.take_profit.type === 'Hour' ? '60' : (risk.take_profit.type === RiskType.TIME ? '1' : '0.1')}
                                        value={risk.take_profit.type === 'Hour' && risk.take_profit.value ? String(risk.take_profit.value).split(':').slice(0, 2).join(':') : (risk.take_profit.value ?? '')}
                                        onChange={(e) => updateRiskSetting('take_profit', 'value', e.target.value === '' ? '' : e.target.value)}
                                        onBlur={() => {
                                            if (risk.take_profit.type === 'Hour') {
                                                if (!risk.take_profit.value) {
                                                    updateRiskSetting('take_profit', 'value', '15:30');
                                                }
                                            } else {
                                                const val = parseFloat(String(risk.take_profit.value));
                                                const isTime = risk.take_profit.type === RiskType.TIME;
                                                const defaultVal = isTime ? 30 : 6.0;
                                                updateRiskSetting('take_profit', 'value', isNaN(val) ? defaultVal : val);
                                            }
                                        }}
                                        onFocus={(e) => e.target.select()}
                                        style={{
                                            backgroundColor: 'var(--color-ec-bg-sidebar)',
                                            border: '0.5px solid var(--color-ec-border)',
                                            borderRadius: 5,
                                            padding: risk.take_profit.type === 'Hour' ? '7px 10px' : '7px 30px 7px 10px',
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
                                    {risk.take_profit.type !== 'Hour' && (
                                        <span className="absolute right-3 top-1/2 -translate-y-1/2 text-[10px] font-bold text-muted-foreground/40">
                                            {risk.take_profit.type === RiskType.TIME ? 'min' : '%'}
                                        </span>
                                    )}
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
                                                                    value={valStr.startsWith('HOUR:') ? valStr.substring(5).split(':').slice(0, 2).join(':') : '15:30'}
                                                                    onChange={(e) => {
                                                                        updatePartial(idx, 'distance_pct', `HOUR:${e.target.value || '15:30'}`);
                                                                    }}
                                                                    style={{
                                                                        width: 65,
                                                                        backgroundColor: 'var(--color-ec-bg-sidebar)',
                                                                        border: '0.5px solid var(--color-ec-border)',
                                                                        borderRadius: 4,
                                                                        padding: '4px 2px 4px 5px',
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

            {/* Otros parámetros Card */}
            <div style={{
                display: 'flex',
                flexDirection: 'column',
                gap: 16,
                padding: '20px 0',
                backgroundColor: 'transparent',
            }}>
                <div style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    paddingBottom: (risk.exclude_days_active) ? 12 : 0,
                    borderBottom: (risk.exclude_days_active) ? '0.5px solid var(--color-ec-border)' : 'none',
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
                            }}>Otros parámetros</h2>
                        </div>
                        <span style={{
                            fontFamily: 'var(--color-ec-sans)',
                            fontSize: 10,
                            fontWeight: 400,
                            color: 'var(--color-ec-text-muted)',
                            marginTop: 2,
                        }}>Configura qué días o meses del año no deseas que se ejecute la estrategia</span>
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <span style={{
                            fontFamily: 'var(--color-ec-sans)',
                            fontSize: 10,
                            fontWeight: 700,
                            color: 'var(--color-ec-text-muted)',
                        }}>{risk.exclude_days_active ? 'YES' : 'NO'}</span>
                        <div
                            className={`w-8 h-4 rounded-full relative cursor-pointer transition-colors ${risk.exclude_days_active ? 'bg-[var(--color-ec-copper)]' : 'bg-muted'}`}
                            onClick={() => {
                                onChange({
                                    ...risk,
                                    exclude_days_active: !risk.exclude_days_active
                                });
                            }}
                        >
                            <div className={`absolute top-0.5 w-3 h-3 rounded-full bg-white transition-all shadow-sm ${risk.exclude_days_active ? 'left-4.5' : 'left-0.5'}`}></div>
                        </div>
                    </div>
                </div>

                {risk.exclude_days_active && (
                    <>
                        {/* Exclude days */}
                        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }} className="animate-in fade-in duration-200">
                            <label style={{
                                fontFamily: 'var(--color-ec-sans)',
                                fontSize: 11,
                                fontWeight: 600,
                                color: 'var(--color-ec-text-secondary)',
                                textTransform: 'uppercase',
                                letterSpacing: '0.05em',
                            }}>Excluir Días de la Semana</label>
                            <div style={{ display: 'flex', gap: 8, width: '100%', marginTop: 4 }}>
                                {["L", "M", "X", "J", "V"].map((day, idx) => {
                                    const isExcluded = (risk.exclude_days || []).includes(idx);
                                    return (
                                        <button
                                            key={day}
                                            type="button"
                                            onClick={() => {
                                                const current = risk.exclude_days || [];
                                                const next = current.includes(idx)
                                                    ? current.filter(d => d !== idx)
                                                    : [...current, idx];
                                                onChange({ ...risk, exclude_days: next });
                                            }}
                                            style={{
                                                flex: 1,
                                                padding: '10px 0',
                                                borderRadius: 5,
                                                fontSize: 12,
                                                fontWeight: 700,
                                                fontFamily: 'var(--color-ec-sans)',
                                                cursor: 'pointer',
                                                transition: 'all 150ms ease',
                                                backgroundColor: isExcluded ? 'rgba(201, 77, 63, 0.15)' : 'var(--color-ec-bg-surface)',
                                                border: isExcluded ? '1px solid var(--color-ec-loss)' : '0.5px solid var(--color-ec-border)',
                                                color: isExcluded ? 'var(--color-ec-loss)' : 'var(--color-ec-text-muted)',
                                            }}
                                            onMouseEnter={(e) => {
                                                if (!isExcluded) {
                                                    e.currentTarget.style.borderColor = 'var(--color-ec-text-secondary)';
                                                    e.currentTarget.style.color = 'var(--color-ec-text-primary)';
                                                }
                                            }}
                                            onMouseLeave={(e) => {
                                                if (!isExcluded) {
                                                    e.currentTarget.style.borderColor = 'var(--color-ec-border)';
                                                    e.currentTarget.style.color = 'var(--color-ec-text-muted)';
                                                }
                                            }}
                                        >
                                            {day}
                                        </button>
                                    );
                                })}
                            </div>
                        </div>

                        {/* Exclude months */}
                        <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 8 }} className="animate-in fade-in duration-200">
                            <label style={{
                                fontFamily: 'var(--color-ec-sans)',
                                fontSize: 11,
                                fontWeight: 600,
                                color: 'var(--color-ec-text-secondary)',
                                textTransform: 'uppercase',
                                letterSpacing: '0.05em',
                            }}>Excluir Meses del Año</label>
                            <div style={{
                                display: 'grid',
                                gridTemplateColumns: 'repeat(4, 1fr)',
                                gap: 8,
                                width: '100%',
                                marginTop: 4
                            }}>
                                {["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"].map((month, idx) => {
                                    const isExcluded = (risk.exclude_months || []).includes(idx);
                                    return (
                                        <button
                                            key={month}
                                            type="button"
                                            onClick={() => {
                                                const current = risk.exclude_months || [];
                                                const next = current.includes(idx)
                                                    ? current.filter(m => m !== idx)
                                                    : [...current, idx];
                                                onChange({ ...risk, exclude_months: next });
                                            }}
                                            style={{
                                                padding: '8px 0',
                                                borderRadius: 5,
                                                fontSize: 10,
                                                fontWeight: 700,
                                                fontFamily: 'var(--color-ec-sans)',
                                                cursor: 'pointer',
                                                transition: 'all 150ms ease',
                                                backgroundColor: isExcluded ? 'rgba(201, 77, 63, 0.15)' : 'var(--color-ec-bg-surface)',
                                                border: isExcluded ? '1px solid var(--color-ec-loss)' : '0.5px solid var(--color-ec-border)',
                                                color: isExcluded ? 'var(--color-ec-loss)' : 'var(--color-ec-text-muted)',
                                                textAlign: 'center',
                                            }}
                                            onMouseEnter={(e) => {
                                                if (!isExcluded) {
                                                    e.currentTarget.style.borderColor = 'var(--color-ec-text-secondary)';
                                                    e.currentTarget.style.color = 'var(--color-ec-text-primary)';
                                                }
                                            }}
                                            onMouseLeave={(e) => {
                                                if (!isExcluded) {
                                                    e.currentTarget.style.borderColor = 'var(--color-ec-border)';
                                                    e.currentTarget.style.color = 'var(--color-ec-text-muted)';
                                                }
                                            }}
                                        >
                                            {month}
                                        </button>
                                    );
                                })}
                            </div>
                        </div>
                    </>
                )}
            </div>

        </div>
    );
};


export const RiskManagementComponent = React.memo(RiskManagementComponentInner);
RiskManagementComponent.displayName = "RiskManagementComponent";
