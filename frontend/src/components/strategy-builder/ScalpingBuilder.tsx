import React from 'react';
import { ScalpingConfig, Timeframe } from '@/types/strategy';
import { GroupDisplay } from './ConditionBuilder';

/**
 * Scalping (2026-09-12): muchas operaciones cortas dentro de una ventana.
 *
 * Apartado con ON/OFF, colocado entre la Salida Lógica y la Piramidación.
 * Cambia lo que significan los dos bloques de arriba:
 *  - La Entrada Lógica ya no entra: ABRE la ventana de scalping.
 *  - La Salida Lógica la CIERRA (y cierra la operación que hubiera abierta).
 *  - Dentro de la ventana, cada cumplimiento nuevo del GATILLO (el mismo
 *    editor de condiciones que entrada/salida) es una entrada, sin límite de
 *    reentradas.
 *  - El stop loss y el take profit son los de la estrategia, sin cambios.
 *  - Además, cada operación se cierra a los N minutos y hay una pausa de K
 *    velas entre una salida y la siguiente entrada.
 *
 * Apagado, la definición NO lleva la clave `scalping` y la estrategia es
 * exactamente la de siempre (regla nº1 del repo).
 */

interface Props {
    config: ScalpingConfig;
    onChange: (config: ScalpingConfig) => void;
}

const TIMEFRAMES: Timeframe[] = [Timeframe.M1, Timeframe.M5, Timeframe.M15];

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

const labelStyle: React.CSSProperties = {
    fontFamily: 'var(--color-ec-sans)',
    fontSize: 10,
    fontWeight: 600,
    color: 'var(--color-ec-text-muted)',
    whiteSpace: 'nowrap',
};

export const ScalpingBuilder = React.memo(({ config, onChange }: Props) => {
    const active = config.active === true;
    const sinGatillo = active && config.root_condition.conditions.length === 0;

    return (
        <div style={{
            display: 'flex',
            flexDirection: 'column',
            gap: 16,
            padding: '20px 0',
            backgroundColor: 'transparent',
            borderBottom: '0.5px solid var(--color-ec-border)',
        }}>
            {/* Header — mismo patrón que Piramidación / Stop Loss Fijo */}
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
                        }}>Scalping</h2>
                    </div>
                    <span style={{
                        fontFamily: 'var(--color-ec-sans)',
                        fontSize: 10,
                        fontWeight: 400,
                        color: 'var(--color-ec-text-muted)',
                        marginTop: 2,
                    }}>Muchas operaciones cortas entre la entrada lógica (abre) y la salida lógica (cierra)</span>
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
                    {/* Qué cambia al encenderlo: hay que decirlo aquí, porque
                        los bloques de arriba se ven igual pero significan otra cosa. */}
                    <span style={{ fontFamily: 'var(--color-ec-sans)', fontSize: 9.5, color: 'var(--color-ec-text-muted)', lineHeight: 1.5 }}>
                        Con el scalping encendido, la <b>Entrada Lógica</b> ya no entra: <b>abre la ventana</b>. La <b>Salida Lógica</b>{' '}
                        <b>la cierra</b> (y cierra la operación que hubiera abierta). Dentro de la ventana, cada cumplimiento nuevo del gatillo
                        es una entrada, sin límite de reentradas. El stop loss y el take profit son los de la estrategia, sin cambios.
                    </span>

                    {/* Parámetros */}
                    <div style={{ display: 'flex', alignItems: 'center', gap: 14, flexWrap: 'wrap' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                            <span style={labelStyle}>Timeframe del gatillo:</span>
                            <select
                                value={config.timeframe}
                                onChange={(e) => onChange({ ...config, timeframe: e.target.value as Timeframe })}
                                style={selectStyle}
                            >
                                {TIMEFRAMES.map(tf => <option key={tf} value={tf}>{tf}</option>)}
                            </select>
                        </div>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                            <span style={labelStyle}>Salir a los:</span>
                            <input
                                type="number"
                                min={0}
                                step={1}
                                value={config.max_minutes ?? ''}
                                onChange={(e) => onChange({ ...config, max_minutes: e.target.value === '' ? 0 : Math.max(0, Number(e.target.value)) })}
                                onFocus={(e) => e.target.select()}
                                style={{ ...selectStyle, width: 58, cursor: 'text' }}
                                title="Minutos desde la entrada. Si en ese tiempo no ha tocado ni el objetivo ni el stop, se sale. 0 = sin salida por tiempo propia (manda el take profit por tiempo de la estrategia, si lo tiene)."
                            />
                            <span style={labelStyle}>min</span>
                        </div>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                            <span style={labelStyle}>Pausa tras salir:</span>
                            <input
                                type="number"
                                min={0}
                                step={1}
                                value={config.cooldown_bars ?? ''}
                                onChange={(e) => onChange({ ...config, cooldown_bars: e.target.value === '' ? 0 : Math.max(0, Math.floor(Number(e.target.value))) })}
                                onFocus={(e) => e.target.select()}
                                style={{ ...selectStyle, width: 48, cursor: 'text' }}
                                title="Velas que hay que esperar tras una salida antes de volver a entrar, aunque el gatillo se cumpla. 0 = ninguna."
                            />
                            <span style={labelStyle}>velas</span>
                        </div>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                            <span style={labelStyle}>Capital por entrada:</span>
                            <input
                                type="number"
                                min={1}
                                max={100}
                                step={1}
                                value={config.capital_pct ?? ''}
                                onChange={(e) => onChange({ ...config, capital_pct: e.target.value === '' ? 100 : Math.max(0.01, Math.min(100, Number(e.target.value))) })}
                                onFocus={(e) => e.target.select()}
                                style={{ ...selectStyle, width: 58, cursor: 'text' }}
                                title={'% de la cifra de capital / riesgo del panel de la izquierda que usa CADA scalp.\n'
                                    + '100 = la cifra entera, como cualquier entrada normal. Si el panel dice 100 $ fijos y aquí pones 10, cada scalp va con 10 $;\n'
                                    + 'si el panel dice 1 % de la cuenta, cada scalp va con el 10 % de ese 1 %. Vale igual por valor de mercado, por distancia al stop o híbrido.'}
                            />
                            <span style={labelStyle}>% de la cifra del panel</span>
                        </div>
                    </div>

                    {/* El gatillo */}
                    <div style={{
                        border: '0.5px solid var(--color-ec-border)',
                        borderLeft: `2px solid ${sinGatillo ? 'var(--color-ec-loss)' : 'var(--color-ec-copper)'}`,
                        borderRadius: 6,
                        padding: '10px 12px',
                        display: 'flex',
                        flexDirection: 'column',
                        gap: 10,
                    }}>
                        <span style={{
                            fontFamily: 'var(--color-ec-sans)', fontSize: 10, fontWeight: 700,
                            color: 'var(--color-ec-text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em',
                        }}>Gatillo de cada operación</span>
                        {/* El MISMO editor de grupos que entrada/salida: AND/OR,
                            anidados, todos los indicadores y comparadores. */}
                        <GroupDisplay
                            group={config.root_condition}
                            onChange={(g) => onChange({ ...config, root_condition: g })}
                            accentColor="amber"
                            parentTimeframe={config.timeframe}
                        />
                        {sinGatillo && (
                            <span style={{ fontFamily: 'var(--color-ec-sans)', fontSize: 10, color: 'var(--color-ec-loss)' }}>
                                Sin condiciones en el gatillo el scalping NO se aplica: la estrategia corre como una normal.
                            </span>
                        )}
                    </div>

                    <span style={{ fontFamily: 'var(--color-ec-sans)', fontSize: 9.5, color: 'var(--color-ec-text-muted)', lineHeight: 1.5 }}>
                        Va vela a vela: se entra en la apertura de la vela siguiente a la del gatillo, y el objetivo o el stop se dan por
                        tocados cuando el máximo o el mínimo de una vela los alcanza (si una misma vela toca los dos, se asume el stop).
                        Un gatillo que se cumpla varias velas seguidas cuenta UNA vez: hace falta que deje de cumplirse y vuelva a cumplirse.
                        Las horas de entrada de la Entrada Lógica también valen para cada operación.
                    </span>
                </div>
            )}
        </div>
    );
});
ScalpingBuilder.displayName = "ScalpingBuilder";
