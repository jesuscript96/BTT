import React from 'react';
import { PyramidingConfig, PyramidLevel, Timeframe, emptyPyramidLevel } from '@/types/strategy';
import { GroupDisplay } from './ConditionBuilder';

/**
 * Piramidación (2026-08-22): gestión dinámica de la posición.
 *
 * Apartado con ON/OFF, colocado entre la Salida Lógica y el Stop Loss Fijo
 * (petición del usuario, solo en la modalidad libre). Cada "pirámide" es un
 * grupo de condiciones EXACTAMENTE igual que los de entrada/salida — mismo
 * GroupDisplay, mismos indicadores, mismos AND/OR anidados — más la acción
 * (añadir/quitar) y su % de capital.
 *
 * Semántica (decidida por el usuario, ver MEMORIA §9):
 *  - Añadir  = % del EQUITY de la cuenta en ese momento.
 *  - Quitar  = % de la POSICIÓN FLOTANTE en ese momento.
 *  - Cada nivel dispara UNA vez por trade; la reentrada lo rearma.
 *  - TP/SL/parciales corren en paralelo: se llevan lo que esto no quite.
 *  - Los niveles de SL/TP quedan anclados a la entrada ORIGINAL.
 */

interface Props {
    config: PyramidingConfig;
    onChange: (config: PyramidingConfig) => void;
}

const TIMEFRAMES: Timeframe[] = [Timeframe.M1, Timeframe.M5, Timeframe.M15, Timeframe.M30, Timeframe.H1];

const selectStyle: React.CSSProperties = {
    backgroundColor: 'var(--color-ec-bg-sidebar)',
    border: '0.5px solid var(--color-ec-border)',
    borderRadius: 5,
    padding: '5px 8px',
    fontSize: 'var(--ec-fs-select)',
    fontWeight: 500,
    color: 'var(--color-ec-text-primary)',
    fontFamily: 'var(--color-ec-sans)',
    outline: 'none',
    cursor: 'pointer',
};

export const PyramidingBuilder = React.memo(({ config, onChange }: Props) => {
    const active = config.active === true;

    const setLevel = (idx: number, lv: PyramidLevel) => {
        const levels = config.levels.slice();
        levels[idx] = lv;
        onChange({ ...config, levels });
    };

    const removeLevel = (idx: number) => {
        onChange({ ...config, levels: config.levels.filter((_, i) => i !== idx) });
    };

    // El contador que pidió el usuario: cuánto llevamos añadido y cuánto
    // quitado. Los añadidos se suman en % del equity. Las quitas son % de la
    // posición FLOTANTE y se encadenan: dos quitas del 50% dejan el 25%, así
    // que lo honesto es mostrar el total efectivo 1 - prod(1 - pct).
    const adds = config.levels.filter(l => l.action === 'add');
    const reduces = config.levels.filter(l => l.action === 'reduce');
    // cada nivel puede disparar `times` veces: los añadidos se multiplican y
    // las quitas se encadenan tambien por sus repeticiones
    const totalAddPct = adds.reduce((s, l) => s + (l.capital_pct || 0) * Math.max(1, l.times || 1), 0);
    const totalReducePct = (1 - reduces.reduce(
        (p, l) => p * Math.pow(1 - Math.min(100, l.capital_pct || 0) / 100, Math.max(1, l.times || 1)), 1)) * 100;

    return (
        <div style={{
            display: 'flex',
            flexDirection: 'column',
            gap: 16,
            padding: '20px 0',
            backgroundColor: 'transparent',
            borderBottom: '0.5px solid var(--color-ec-border)',
        }}>
            {/* Header — mismo patrón que Stop Loss Fijo / Take Profit */}
            <div style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                paddingBottom: active ? 12 : 0,
                borderBottom: active ? '0.5px solid var(--color-ec-border)' : 'none',
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
                        }}>Piramidación</h2>
                    </div>
                    <span style={{
                        fontFamily: 'var(--color-ec-sans)',
                        fontSize: 10,
                        fontWeight: 400,
                        color: 'var(--color-ec-text-muted)',
                        marginTop: 2,
                    }}>Añade o reduce tamaño con la posición abierta, por condiciones lógicas</span>
                </div>
                <div className="flex items-center gap-2">
                    <span style={{
                        fontFamily: 'var(--color-ec-sans)',
                        fontSize: 10,
                        fontWeight: 700,
                        color: 'var(--color-ec-text-muted)',
                    }}>{active ? 'ON' : 'OFF'}</span>
                    <div
                        className={`w-8 h-4 rounded-full relative cursor-pointer transition-colors ${active ? 'bg-ec-copper/70' : 'bg-muted'}`}
                        onClick={() => onChange({ ...config, active: !active })}
                    >
                        <div className={`absolute top-0.5 w-3 h-3 rounded-full bg-white transition-all shadow-sm ${active ? 'left-4.5' : 'left-0.5'}`}></div>
                    </div>
                </div>
            </div>

            {active && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }} className="animate-in fade-in duration-200">
                    {/* Timeframe del bloque + contador */}
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 8 }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                                <span style={{ fontFamily: 'var(--color-ec-sans)', fontSize: 10, fontWeight: 600, color: 'var(--color-ec-text-muted)' }}>Timeframe:</span>
                                <select
                                    value={config.timeframe}
                                    onChange={(e) => onChange({ ...config, timeframe: e.target.value as Timeframe })}
                                    style={selectStyle}
                                >
                                    {TIMEFRAMES.map(tf => <option key={tf} value={tf}>{tf}</option>)}
                                </select>
                            </div>
                            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                                <span style={{ fontFamily: 'var(--color-ec-sans)', fontSize: 10, fontWeight: 600, color: 'var(--color-ec-text-muted)' }}>Modo:</span>
                                <select
                                    value={config.mode || 'individual'}
                                    onChange={(e) => onChange({ ...config, mode: e.target.value as 'individual' | 'sequential' })}
                                    style={selectStyle}
                                    title={(config.mode || 'individual') === 'individual'
                                        ? 'Cada pirámide vigila su condición en paralelo, sin depender de las demás.'
                                        : 'Cada pirámide solo se arma cuando la anterior ya ha disparado al menos una vez.'}
                                >
                                    <option value="individual">Individual</option>
                                    <option value="sequential">Secuencial</option>
                                </select>
                            </div>
                        </div>
                        {/* El contador pedido por el usuario */}
                        {config.levels.length > 0 && (
                            <span style={{
                                fontFamily: 'var(--color-ec-sans)',
                                fontSize: 10,
                                fontWeight: 600,
                                color: 'var(--color-ec-copper)',
                            }}>
                                Añadidos: +{totalAddPct.toFixed(1)}% del equity
                                {' · '}Quitas: −{totalReducePct.toFixed(1)}% de la posición
                                {totalReducePct < 100 ? ' (el resto lo cierra TP/SL/EOD)' : ''}
                            </span>
                        )}
                    </div>

                    {/* Niveles */}
                    {config.levels.map((lv, idx) => (
                        <div key={idx} style={{
                            border: '0.5px solid var(--color-ec-border)',
                            borderLeft: '2px solid var(--color-ec-copper)',
                            borderRadius: 6,
                            padding: '10px 12px',
                            display: 'flex',
                            flexDirection: 'column',
                            gap: 10,
                        }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                                <span style={{
                                    fontFamily: 'var(--color-ec-sans)', fontSize: 10, fontWeight: 700,
                                    color: 'var(--color-ec-text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em',
                                }}>Pirámide {idx + 1}</span>
                                <select
                                    value={lv.action}
                                    onChange={(e) => setLevel(idx, { ...lv, action: e.target.value as 'add' | 'reduce' })}
                                    style={selectStyle}
                                >
                                    <option value="add">Añadir</option>
                                    <option value="reduce">Quitar</option>
                                </select>
                                <input
                                    type="number"
                                    min={0.1}
                                    step={0.1}
                                    value={lv.capital_pct ?? ''}
                                    onChange={(e) => setLevel(idx, { ...lv, capital_pct: e.target.value === '' ? 0 : Number(e.target.value) })}
                                    onFocus={(e) => e.target.select()}
                                    style={{ ...selectStyle, width: 72, cursor: 'text' }}
                                    title={lv.action === 'add'
                                        ? '% del equity de la cuenta que se añade a la posición'
                                        : '% de la posición flotante que se cierra'}
                                />
                                <span style={{ fontFamily: 'var(--color-ec-sans)', fontSize: 10, color: 'var(--color-ec-text-muted)' }}>
                                    {lv.action === 'add' ? '% del equity' : '% de la posición'}
                                </span>
                                <span style={{ fontFamily: 'var(--color-ec-sans)', fontSize: 10, fontWeight: 600, color: 'var(--color-ec-text-muted)', marginLeft: 6 }}>Veces:</span>
                                <input
                                    type="number"
                                    min={1}
                                    max={100}
                                    step={1}
                                    value={lv.times ?? 1}
                                    onChange={(e) => setLevel(idx, { ...lv, times: e.target.value === '' ? 1 : Math.max(1, Math.floor(Number(e.target.value))) })}
                                    onFocus={(e) => e.target.select()}
                                    style={{ ...selectStyle, width: 52, cursor: 'text' }}
                                    title="Cuántas veces puede disparar esta pirámide por trade (cada cumplimiento nuevo de la condición cuenta una vez)"
                                />
                                <button
                                    type="button"
                                    onClick={() => removeLevel(idx)}
                                    style={{
                                        marginLeft: 'auto',
                                        background: 'transparent',
                                        border: 'none',
                                        color: 'var(--color-ec-loss)',
                                        cursor: 'pointer',
                                        fontSize: 11,
                                        fontFamily: 'var(--color-ec-sans)',
                                    }}
                                    title="Eliminar esta pirámide"
                                >✕ eliminar</button>
                            </div>
                            {/* El MISMO editor de grupos que entrada/salida: AND/OR,
                                anidados, todos los indicadores y comparadores. */}
                            <GroupDisplay
                                group={lv.root_condition}
                                onChange={(g) => setLevel(idx, { ...lv, root_condition: g })}
                                accentColor="amber"
                                parentTimeframe={config.timeframe}
                            />
                        </div>
                    ))}

                    <button
                        type="button"
                        onClick={() => onChange({ ...config, levels: [...config.levels, emptyPyramidLevel()] })}
                        style={{
                            alignSelf: 'flex-start',
                            backgroundColor: 'transparent',
                            border: '0.5px dashed var(--color-ec-copper)',
                            borderRadius: 5,
                            padding: '6px 12px',
                            fontSize: 11,
                            fontWeight: 600,
                            fontFamily: 'var(--color-ec-sans)',
                            color: 'var(--color-ec-copper)',
                            cursor: 'pointer',
                        }}
                    >+ Añadir pirámide</button>

                    <span style={{ fontFamily: 'var(--color-ec-sans)', fontSize: 9.5, color: 'var(--color-ec-text-muted)', lineHeight: 1.5 }}>
                        {(config.mode || 'individual') === 'individual'
                            ? 'Cada pirámide es INDEPENDIENTE: vigila su condición en paralelo, sin depender de las demás (la numeración es solo orden).'
                            : 'Modo SECUENCIAL: cada pirámide solo se arma cuando la anterior ya ha disparado al menos una vez.'}
                        {' '}Dispara hasta las «veces» indicadas, contando cada cumplimiento nuevo de la condición, siempre después de la
                        entrada; una reentrada lo rearma todo. El stop y el take profit no se recalculan al añadir (quedan anclados a la
                        entrada original) y corren en paralelo: cierran lo que las quitas no se hayan llevado.
                    </span>
                </div>
            )}
        </div>
    );
});
PyramidingBuilder.displayName = "PyramidingBuilder";
