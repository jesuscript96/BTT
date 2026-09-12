import React from 'react';
import { ScalpingConfig, ScalpingLadder, Timeframe, initialScalpingLadder } from '@/types/strategy';
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
                        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                            <span style={labelStyle}>Modo:</span>
                            <select
                                value={config.mode || 'simple'}
                                onChange={(e) => onChange({ ...config, mode: e.target.value as 'simple' | 'complex', ladder: config.ladder || initialScalpingLadder })}
                                style={selectStyle}
                                title={'Simple: entra-sale-entra-sale, siempre con la cantidad de «Capital por entrada».\n'
                                    + 'Complejo: dentro de cada scalp actúa una ESCALERA: por cada paso de X % que se mueve el precio, añade o quita una cantidad, entre un suelo (core) y un techo (tope).'}
                            >
                                <option value="simple">Simple</option>
                                <option value="complex">Complejo (escalera)</option>
                            </select>
                        </div>
                    </div>

                    {/* La escalera del modo complejo */}
                    {config.mode === 'complex' && (() => {
                        const l = config.ladder || initialScalpingLadder;
                        const setL = (patch: Partial<ScalpingLadder>) => onChange({ ...config, ladder: { ...l, ...patch } });
                        const num = (v: string, min = 0) => (v === '' ? 0 : Math.max(min, Number(v)));
                        const Q = ({ text }: { text: string }) => (
                            <span title={text} style={{
                                display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                                width: 13, height: 13, borderRadius: 7, fontSize: 9, fontWeight: 700,
                                border: '0.5px solid var(--color-ec-border)', color: 'var(--color-ec-text-muted)',
                                cursor: 'help', marginLeft: 2, fontFamily: 'var(--color-ec-sans)',
                            }}>?</span>
                        );
                        const lado = (titulo: string, ayuda: string, action: 'add' | 'reduce' | 'none', amount: number, unit: 'usd' | 'pct',
                                      patch: (a: 'add' | 'reduce' | 'none', n: number, u: 'usd' | 'pct') => void) => (
                            <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
                                <span style={{ ...labelStyle, width: 92 }}>{titulo}<Q text={ayuda} /></span>
                                <select value={action} onChange={(e) => patch(e.target.value as any, amount, unit)} style={selectStyle}
                                    title="Qué hace la escalera en cada paso en esta dirección">
                                    <option value="add">Añadir</option>
                                    <option value="reduce">Quitar</option>
                                    <option value="none">Nada</option>
                                </select>
                                {action !== 'none' && (
                                    <>
                                        <input type="number" min={0} step={1} value={amount ?? ''}
                                            onChange={(e) => patch(action, num(e.target.value), unit)}
                                            onFocus={(e) => e.target.select()}
                                            style={{ ...selectStyle, width: 64, cursor: 'text' }}
                                            title="Cuánto se añade o se quita en cada paso" />
                                        <select value={unit} onChange={(e) => patch(action, amount, e.target.value as any)} style={selectStyle}
                                            title="$ = cantidad fija en dólares · % = porcentaje de la posición INICIAL del scalp (fijo: cada escalón el mismo tamaño)">
                                            <option value="pct">% de la inicial</option>
                                            <option value="usd">$ fijos</option>
                                        </select>
                                    </>
                                )}
                            </div>
                        );
                        return (
                            <div style={{
                                border: '0.5px solid var(--color-ec-border)', borderLeft: '2px solid var(--color-ec-copper)',
                                borderRadius: 6, padding: '10px 12px', display: 'flex', flexDirection: 'column', gap: 8,
                            }}>
                                <span style={{
                                    fontFamily: 'var(--color-ec-sans)', fontSize: 10, fontWeight: 700,
                                    color: 'var(--color-ec-text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em',
                                }}>Escalera</span>
                                <div style={{ display: 'flex', alignItems: 'center', gap: 14, flexWrap: 'wrap' }}>
                                    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                                        <span style={labelStyle}>Paso<Q text="Cada cuánto actúa la escalera: % de movimiento del precio desde el ÚLTIMO nivel ejecutado (no desde la entrada), así los escalones son regulares. Ejemplo: 1 = cada 1 %." /></span>
                                        <input type="number" min={0.01} step={0.1} value={l.step_pct ?? ''}
                                            onChange={(e) => setL({ step_pct: num(e.target.value) })} onFocus={(e) => e.target.select()}
                                            style={{ ...selectStyle, width: 58, cursor: 'text' }} />
                                        <span style={labelStyle}>%</span>
                                    </div>
                                    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                                        <span style={labelStyle}>Recorrido máx.<Q text="Hasta qué % desde el precio de la PRIMERA entrada del scalp actúa la escalera. Más allá no añade ni quita: la posición queda en manos de la salida principal (salida lógica, stop, take profit, tiempo). Manda sobre el paso. 0 = sin límite." /></span>
                                        <input type="number" min={0} step={0.5} value={l.max_travel_pct ?? ''}
                                            onChange={(e) => setL({ max_travel_pct: num(e.target.value) })} onFocus={(e) => e.target.select()}
                                            style={{ ...selectStyle, width: 58, cursor: 'text' }} />
                                        <span style={labelStyle}>%</span>
                                    </div>
                                    <label style={{ ...labelStyle, display: 'flex', alignItems: 'center', gap: 4, cursor: 'pointer' }}>
                                        <input type="checkbox" checked={!!l.rearm} onChange={(e) => setL({ rearm: e.target.checked })} />
                                        Rearmar niveles<Q text="Apagado (opción A): cada nivel de precio se ejecuta UNA vez por scalp y por dirección (añadir al bajar a un nivel no gasta el quitar al volver a subir por él, pero una segunda bajada al mismo nivel ya no añade). Encendido (opción B, grid): cada nivel opera CADA VEZ que el precio lo cruza de nuevo (vende al subir, recompra al bajar...), siempre entre el core y el tope. Ojo: en small caps con spread y locates, aquí es donde se ven los costes." />
                                    </label>
                                </div>
                                {lado('A favor:', 'Qué hacer por cada paso que el precio se mueve A FAVOR de la posición (arriba en largo, abajo en corto), medido desde el último nivel ejecutado. «Quitar» = tomar parciales a favor; «Añadir» = piramidar a favor.',
                                    l.favor_action, l.favor_amount, l.favor_unit, (a, n, u) => setL({ favor_action: a, favor_amount: n, favor_unit: u }))}
                                {lado('En contra:', 'Qué hacer por cada paso que el precio se mueve EN CONTRA (abajo en largo, arriba en corto), medido desde el último nivel ejecutado. «Añadir» = promediar / martingala (ojo: el stop en % se mide sobre el precio medio, así que cada añadido en contra ALEJA el stop y el riesgo en $ crece); «Quitar» = reducir en contra.',
                                    l.contra_action, l.contra_amount, l.contra_unit, (a, n, u) => setL({ contra_action: a, contra_amount: n, contra_unit: u }))}
                                <div style={{ display: 'flex', alignItems: 'center', gap: 14, flexWrap: 'wrap' }}>
                                    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                                        <span style={labelStyle}>Core (suelo)<Q text="Capital que SIEMPRE se conserva: al quitar, la posición nunca baja de aquí. 0 = se puede quitar todo; entonces el scalp queda cerrado y el siguiente gatillo abre otro desde cero. Lo que quede lo cierra la salida principal." /></span>
                                        <input type="number" min={0} step={1} value={l.core_amount ?? ''}
                                            onChange={(e) => setL({ core_amount: num(e.target.value) })} onFocus={(e) => e.target.select()}
                                            style={{ ...selectStyle, width: 64, cursor: 'text' }} />
                                        <select value={l.core_unit} onChange={(e) => setL({ core_unit: e.target.value as any })} style={selectStyle}
                                            title="$ = valor de posición en dólares · % = porcentaje de la posición INICIAL del scalp">
                                            <option value="pct">% de la inicial</option>
                                            <option value="usd">$</option>
                                        </select>
                                    </div>
                                    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                                        <span style={labelStyle}>Tope (techo)<Q text="Capital máximo de la posición: al añadir, nunca se pasa de aquí. 0 = sin techo propio (manda la caja disponible, como siempre). Con «añadir a favor» y core > 0, el core no interviene: solo manda este tope." /></span>
                                        <input type="number" min={0} step={1} value={l.cap_amount ?? ''}
                                            onChange={(e) => setL({ cap_amount: num(e.target.value) })} onFocus={(e) => e.target.select()}
                                            style={{ ...selectStyle, width: 64, cursor: 'text' }} />
                                        <select value={l.cap_unit} onChange={(e) => setL({ cap_unit: e.target.value as any })} style={selectStyle}
                                            title="$ = valor de posición en dólares · % = porcentaje de la posición INICIAL del scalp">
                                            <option value="pct">% de la inicial</option>
                                            <option value="usd">$</option>
                                        </select>
                                    </div>
                                </div>
                                <span style={{ fontFamily: 'var(--color-ec-sans)', fontSize: 9.5, color: 'var(--color-ec-text-muted)', lineHeight: 1.5 }}>
                                    Cada nivel se ejecuta al precio del nivel (como una orden limitada que descansa ahí) en la vela cuyo máximo o mínimo lo toca.
                                    El stop loss y el take profit en % se miden sobre el <b>precio medio</b> de la posición. La salida principal
                                    (salida lógica, stop, take profit, tiempo) siempre cierra todo lo que haya.
                                </span>
                            </div>
                        );
                    })()}

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
