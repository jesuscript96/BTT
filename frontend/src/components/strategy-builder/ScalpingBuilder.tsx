import React from 'react';
import { ScalpingConfig, ScalpingLadder, Timeframe, initialScalpingLadder } from '@/types/strategy';
import { GroupDisplay } from './ConditionBuilder';
import InfoTooltip from '@/components/backtester/InfoTooltip';

/**
 * Scalping (2026-09-12): muchas operaciones cortas dentro de una ventana.
 *
 * Apartado con ON/OFF, entre la Salida Lógica y la Piramidación. Cambia lo
 * que significan los dos bloques de arriba:
 *  - La Entrada Lógica ya no entra: ABRE la ventana de scalping.
 *  - La Salida Lógica la CIERRA (y cierra la operación que hubiera abierta).
 *  - Dentro de la ventana, cada cumplimiento nuevo del GATILLO (el mismo
 *    editor de condiciones que entrada/salida) es una entrada, sin límite de
 *    reentradas. Stop loss y take profit son los de la estrategia.
 *  - Modo simple: entra-sale-entra-sale con la cantidad fijada.
 *    Modo complejo: dentro de cada scalp actúa una ESCALERA mecánica (paso,
 *    añadir/quitar a favor y en contra, core, tope, recorrido, rearmar).
 *
 * Apagado, la definición NO lleva la clave `scalping` y la estrategia es
 * exactamente la de siempre (regla nº1 del repo).
 *
 * Diseño: filas «etiqueta | control», sin cajas dentro de cajas, con el mismo
 * (?) de ayuda que usa el resto de la aplicación (petición de Jaume: sobrio).
 */

interface Props {
    config: ScalpingConfig;
    onChange: (config: ScalpingConfig) => void;
}

const TIMEFRAMES: Timeframe[] = [Timeframe.M1, Timeframe.M5, Timeframe.M15];

const control: React.CSSProperties = {
    backgroundColor: 'var(--color-ec-bg-sidebar)',
    border: '0.5px solid var(--color-ec-border)',
    borderRadius: 5,
    padding: '0 10px',
    height: 32,
    fontSize: 12,
    fontWeight: 500,
    color: 'var(--color-ec-text-primary)',
    fontFamily: 'var(--color-ec-sans)',
    outline: 'none',
    cursor: 'pointer',
};

const input: React.CSSProperties = { ...control, cursor: 'text', width: 72, textAlign: 'right' };

const label: React.CSSProperties = {
    fontFamily: 'var(--color-ec-sans)',
    fontSize: 11,
    fontWeight: 600,
    color: 'var(--color-ec-text-secondary)',
    display: 'inline-flex',
    alignItems: 'center',
    whiteSpace: 'nowrap',
};

const unit: React.CSSProperties = {
    fontFamily: 'var(--color-ec-sans)',
    fontSize: 11,
    color: 'var(--color-ec-text-muted)',
    whiteSpace: 'nowrap',
};

const sectionTitle: React.CSSProperties = {
    fontFamily: 'var(--color-ec-sans)',
    fontSize: 10,
    fontWeight: 700,
    textTransform: 'uppercase',
    letterSpacing: '0.08em',
    color: 'var(--color-ec-text-muted)',
    paddingBottom: 6,
    borderBottom: '0.5px solid var(--color-ec-border)',
    display: 'flex',
    alignItems: 'center',
};

/** Una fila de la tabla de parámetros: etiqueta a la izquierda, controles a la derecha. */
const Row = ({ title, help, children }: { title: string; help: string; children: React.ReactNode }) => (
    <div style={{ display: 'grid', gridTemplateColumns: '150px 1fr', alignItems: 'center', columnGap: 12, minHeight: 32 }}>
        <span style={label}>{title}<InfoTooltip text={help} position="top" width={300} /></span>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>{children}</div>
    </div>
);

const num = (v: string, min = 0) => (v === '' ? 0 : Math.max(min, Number(v)));

export const ScalpingBuilder = React.memo(({ config, onChange }: Props) => {
    const active = config.active === true;
    const sinGatillo = active && config.root_condition.conditions.length === 0;
    const complejo = config.mode === 'complex';
    const l = config.ladder || initialScalpingLadder;
    const setL = (patch: Partial<ScalpingLadder>) => onChange({ ...config, ladder: { ...l, ...patch } });

    const lado = (
        title: string, help: string,
        action: ScalpingLadder['favor_action'], amount: number, un: ScalpingLadder['favor_unit'],
        patch: (a: ScalpingLadder['favor_action'], n: number, u: ScalpingLadder['favor_unit']) => void,
    ) => (
        <Row title={title} help={help}>
            <select value={action} onChange={(e) => patch(e.target.value as ScalpingLadder['favor_action'], amount, un)} style={control}>
                <option value="add">Añadir</option>
                <option value="reduce">Quitar</option>
                <option value="none">Nada</option>
            </select>
            {action !== 'none' && (
                <>
                    <input type="number" min={0} step={1} value={amount ?? ''}
                        onChange={(e) => patch(action, num(e.target.value), un)}
                        onFocus={(e) => e.target.select()} style={input} />
                    <select value={un} onChange={(e) => patch(action, amount, e.target.value as ScalpingLadder['favor_unit'])} style={control}>
                        <option value="pct">% de la posición inicial</option>
                        <option value="usd">$ fijos</option>
                    </select>
                </>
            )}
        </Row>
    );

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
                        <div style={{ width: 3, height: 14, borderRadius: 1, backgroundColor: 'var(--color-ec-copper)' }} />
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
                    <span style={{ fontFamily: 'var(--color-ec-sans)', fontSize: 10, fontWeight: 400, color: 'var(--color-ec-text-muted)', marginTop: 2 }}>
                        La entrada lógica abre la ventana, la salida lógica la cierra; dentro, cada gatillo es una operación
                    </span>
                </div>
                <div className="flex items-center gap-2">
                    <span style={{ fontFamily: 'var(--color-ec-sans)', fontSize: 10, fontWeight: 700, color: 'var(--color-ec-text-muted)' }}>{active ? 'ON' : 'OFF'}</span>
                    <div
                        className={`w-8 h-4 rounded-full relative cursor-pointer transition-colors ${active ? 'bg-ec-copper/70' : 'bg-muted'}`}
                        onClick={() => onChange({ ...config, active: !active })}
                    >
                        <div className={`absolute top-0.5 w-3 h-3 rounded-full bg-white transition-all shadow-sm ${active ? 'left-4.5' : 'left-0.5'}`}></div>
                    </div>
                </div>
            </div>

            {active && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }} className="animate-in fade-in duration-200">
                    {/* ── Parámetros generales ── */}
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                        <Row title="Modo" help={'Simple: entra-sale-entra-sale, siempre con la cantidad de «Capital por entrada».\n\nComplejo: dentro de cada scalp actúa una escalera: por cada paso de X % que se mueve el precio, añade o quita una cantidad, entre un suelo (core) y un techo (tope).'}>
                            <select
                                value={config.mode || 'simple'}
                                onChange={(e) => onChange({ ...config, mode: e.target.value as 'simple' | 'complex', ladder: config.ladder || initialScalpingLadder })}
                                style={control}
                            >
                                <option value="simple">Simple</option>
                                <option value="complex">Complejo (escalera)</option>
                            </select>
                        </Row>
                        <Row title="Timeframe del gatillo" help="Timeframe en el que se evalúan las condiciones del gatillo.">
                            <select value={config.timeframe} onChange={(e) => onChange({ ...config, timeframe: e.target.value as Timeframe })} style={control}>
                                {TIMEFRAMES.map(tf => <option key={tf} value={tf}>{tf}</option>)}
                            </select>
                        </Row>
                        <Row title="Capital por entrada" help={'% de la cifra de capital / riesgo del panel de la izquierda que usa CADA scalp. 100 = la cifra entera, como cualquier entrada normal.\n\nSi el panel dice 100 $ fijos y aquí pones 10, cada scalp va con 10 $; si el panel dice 1 % de la cuenta, cada scalp va con el 10 % de ese 1 %. Vale igual por valor de mercado, por distancia al stop o híbrido.'}>
                            <input type="number" min={1} max={100} step={1} value={config.capital_pct ?? ''}
                                onChange={(e) => onChange({ ...config, capital_pct: e.target.value === '' ? 100 : Math.max(0.01, Math.min(100, Number(e.target.value))) })}
                                onFocus={(e) => e.target.select()} style={input} />
                            <span style={unit}>% de la cifra del panel</span>
                        </Row>
                        <Row title="Salida por tiempo" help="Minutos desde la entrada. Si en ese tiempo no ha tocado ni el objetivo ni el stop, se sale. 0 = sin salida por tiempo propia (manda el take profit por tiempo de la estrategia, si lo tiene).">
                            <input type="number" min={0} step={1} value={config.max_minutes ?? ''}
                                onChange={(e) => onChange({ ...config, max_minutes: num(e.target.value) })}
                                onFocus={(e) => e.target.select()} style={input} />
                            <span style={unit}>min</span>
                        </Row>
                        <Row title="Pausa tras salir" help="Velas que hay que esperar tras una salida antes de volver a entrar, aunque el gatillo se cumpla. 0 = ninguna.">
                            <input type="number" min={0} step={1} value={config.cooldown_bars ?? ''}
                                onChange={(e) => onChange({ ...config, cooldown_bars: e.target.value === '' ? 0 : Math.max(0, Math.floor(Number(e.target.value))) })}
                                onFocus={(e) => e.target.select()} style={input} />
                            <span style={unit}>velas</span>
                        </Row>
                    </div>

                    {/* ── Escalera (modo complejo) ── */}
                    {complejo && (
                        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                            <span style={sectionTitle}>Escalera</span>
                            <Row title="Paso" help="Cada cuánto actúa la escalera: % de movimiento del precio desde el ÚLTIMO nivel ejecutado (no desde la entrada), así los escalones son regulares. Ejemplo: 1 = cada 1 %.">
                                <input type="number" min={0.01} step={0.1} value={l.step_pct ?? ''}
                                    onChange={(e) => setL({ step_pct: num(e.target.value) })} onFocus={(e) => e.target.select()} style={input} />
                                <span style={unit}>%</span>
                            </Row>
                            {lado('A favor', 'Qué hacer por cada paso que el precio se mueve A FAVOR de la posición (arriba en largo, abajo en corto), medido desde el último nivel ejecutado.\n\n«Quitar» = tomar parciales a favor. «Añadir» = piramidar a favor.',
                                l.favor_action, l.favor_amount, l.favor_unit, (a, n, u) => setL({ favor_action: a, favor_amount: n, favor_unit: u }))}
                            {lado('En contra', 'Qué hacer por cada paso que el precio se mueve EN CONTRA (abajo en largo, arriba en corto), medido desde el último nivel ejecutado.\n\n«Añadir» = promediar / martingala. Ojo: el stop en % se mide sobre el precio medio, así que cada añadido en contra ALEJA el stop y el riesgo en $ crece. «Quitar» = reducir en contra.',
                                l.contra_action, l.contra_amount, l.contra_unit, (a, n, u) => setL({ contra_action: a, contra_amount: n, contra_unit: u }))}
                            <Row title="Core (suelo)" help={'Capital que SIEMPRE se conserva: al quitar, la posición nunca baja de aquí.\n\n0 = se puede quitar todo; entonces el scalp queda cerrado y el siguiente gatillo abre otro desde cero. Lo que quede lo cierra la salida principal.'}>
                                <input type="number" min={0} step={1} value={l.core_amount ?? ''}
                                    onChange={(e) => setL({ core_amount: num(e.target.value) })} onFocus={(e) => e.target.select()} style={input} />
                                <select value={l.core_unit} onChange={(e) => setL({ core_unit: e.target.value as ScalpingLadder['core_unit'] })} style={control}>
                                    <option value="pct">% de la posición inicial</option>
                                    <option value="usd">$</option>
                                </select>
                            </Row>
                            <Row title="Tope (techo)" help={'Capital máximo de la posición: al añadir, nunca se pasa de aquí.\n\n0 = sin techo propio (manda la caja disponible, como siempre). Con «añadir a favor» y core > 0, el core no interviene: solo manda este tope.'}>
                                <input type="number" min={0} step={1} value={l.cap_amount ?? ''}
                                    onChange={(e) => setL({ cap_amount: num(e.target.value) })} onFocus={(e) => e.target.select()} style={input} />
                                <select value={l.cap_unit} onChange={(e) => setL({ cap_unit: e.target.value as ScalpingLadder['cap_unit'] })} style={control}>
                                    <option value="pct">% de la posición inicial</option>
                                    <option value="usd">$</option>
                                </select>
                            </Row>
                            <Row title="Recorrido máximo" help="Hasta qué % desde el precio de la PRIMERA entrada del scalp actúa la escalera. Más allá no añade ni quita: la posición queda en manos de la salida principal (salida lógica, stop, take profit, tiempo). Manda sobre el paso. 0 = sin límite.">
                                <input type="number" min={0} step={0.5} value={l.max_travel_pct ?? ''}
                                    onChange={(e) => setL({ max_travel_pct: num(e.target.value) })} onFocus={(e) => e.target.select()} style={input} />
                                <span style={unit}>% desde la entrada</span>
                            </Row>
                            <Row title="Rearmar niveles" help={'Apagado (opción A): cada nivel de precio se ejecuta UNA vez por scalp y por dirección (añadir al bajar a un nivel no gasta el quitar al volver a subir por él, pero una segunda bajada al mismo nivel ya no añade).\n\nEncendido (opción B, grid): cada nivel opera CADA VEZ que el precio lo cruza de nuevo (vende al subir, recompra al bajar...), siempre entre el core y el tope. En small caps con spread y locates, aquí es donde se ven los costes.'}>
                                <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6, cursor: 'pointer' }}>
                                    <input type="checkbox" checked={!!l.rearm} onChange={(e) => setL({ rearm: e.target.checked })} />
                                    <span style={unit}>{l.rearm ? 'Sí: cada nivel opera cada vez que se cruza (grid)' : 'No: cada nivel una vez por scalp y dirección'}</span>
                                </label>
                            </Row>
                            <span style={{ ...unit, lineHeight: 1.5, whiteSpace: 'normal' }}>
                                Cada nivel se ejecuta al precio del nivel en la vela que lo toca. El stop loss y el take profit en % se miden sobre el
                                precio medio de la posición. La salida principal (salida lógica, stop, take profit, tiempo) siempre cierra todo.
                            </span>
                        </div>
                    )}

                    {/* ── Gatillo ── */}
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                        <span style={sectionTitle}>
                            Gatillo de cada operación
                            <InfoTooltip position="top" width={300} text="El mismo editor de condiciones que entrada y salida. Se entra en la apertura de la vela siguiente a la que cumple el gatillo. Un gatillo que se cumpla varias velas seguidas cuenta UNA vez: hace falta que deje de cumplirse y vuelva a cumplirse. Las horas de entrada de la Entrada Lógica también valen para cada operación." />
                        </span>
                        <GroupDisplay
                            group={config.root_condition}
                            onChange={(g) => onChange({ ...config, root_condition: g })}
                            accentColor="amber"
                            parentTimeframe={config.timeframe}
                        />
                        {sinGatillo && (
                            <span style={{ fontFamily: 'var(--color-ec-sans)', fontSize: 11, color: 'var(--color-ec-loss)' }}>
                                Sin condiciones en el gatillo el scalping no se aplica: la estrategia corre como una normal.
                            </span>
                        )}
                    </div>
                </div>
            )}
        </div>
    );
});
ScalpingBuilder.displayName = "ScalpingBuilder";
