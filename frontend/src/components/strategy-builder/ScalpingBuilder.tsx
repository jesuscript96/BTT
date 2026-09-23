import React from 'react';
import { ScalpingConfig, ScalpingLadder, Timeframe, initialScalpingLadder } from '@/types/strategy';
import { GroupDisplay } from './ConditionBuilder';
import InfoTooltip from '@/components/backtester/InfoTooltip';
import { color, font } from '@/components/ui/tokens';

/**
 * Scalping (2026-09-12; vocabulario de trading y esquema 2026-09-23): muchas
 * operaciones cortas dentro de una ventana.
 *
 * Apartado con ON/OFF, entre la Salida Lógica y la Piramidación. Cambia lo
 * que significan los dos bloques de arriba:
 *  - La Entrada Lógica ya no entra: ABRE la ventana de scalping.
 *  - La Salida Lógica la CIERRA (y cierra la operación que hubiera abierta).
 *  - Dentro de la ventana, cada cumplimiento nuevo del GATILLO (el mismo
 *    editor de condiciones que entrada/salida) es una entrada, sin límite de
 *    reentradas. Stop loss y take profit son los de la estrategia.
 *  - Modo simple: entra-sale-entra-sale con el tamaño fijado.
 *  - Modo con escalera: dentro de cada operación actúa una ESCALERA mecánica
 *    (distancia entre niveles, piramidar/tomar parcial a favor, promediar/
 *    reducir en contra, posición mínima/máxima, rango, repetir niveles).
 *
 * Apagado, la definición NO lleva la clave `scalping` y la estrategia es
 * exactamente la de siempre (regla nº1 del repo).
 *
 * Diseño: filas «etiqueta | control», sin cajas dentro de cajas (petición de
 * Jaume: sobrio), una frase-resumen en vivo bajo el header y, en modo
 * escalera, un esquema SVG del ladder con los valores del formulario. Las
 * claves del bloque (`step_pct`, `favor_action`, `core_amount`, `rearm`…)
 * son el formato persistido: NO se renombran.
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
    <div style={{ display: 'grid', gridTemplateColumns: '172px 1fr', alignItems: 'center', columnGap: 12, minHeight: 32 }}>
        <span style={label}>{title}<InfoTooltip text={help} position="top" width={300} /></span>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>{children}</div>
    </div>
);

const num = (v: string, min = 0) => (v === '' ? 0 : Math.max(min, Number(v)));

/** Números «bonitos» para textos: sin ceros de ruido (1, no 1.0; 0.5, no 0.50). */
const fmtN = (v: number | undefined | null) => {
    const x = Number(v);
    if (!Number.isFinite(x)) return '0';
    return String(Math.round(x * 100) / 100);
};

const mono: React.CSSProperties = { fontFamily: font.mono };

/** Cantidad de la escalera en texto corto: «50 $» o «10 % pos. inicial». */
const cant = (n: number | undefined, u: 'usd' | 'pct' | undefined) =>
    `${fmtN(n)} ${u === 'usd' ? '$' : '% pos. inicial'}`;

/* ── La frase-resumen: qué hará la estrategia, en una sola línea viva ── */
function resumenScalping(c: ScalpingConfig): string {
    const cap = c.capital_pct ?? 100;
    const min = c.max_minutes ?? 0;
    const cd = c.cooldown_bars ?? 0;
    let s = `La entrada lógica abre la ventana y la salida lógica la cierra. Dentro, cada gatillo abre una operación con el ${fmtN(cap)} % de la cifra del panel, que cierra por objetivo o stop`;
    if (min > 0) s += ` o a los ${fmtN(min)} min`;
    s += '.';
    if (cd > 0) s += ` Antes de reentrar, espera ${fmtN(cd)} ${cd === 1 ? 'vela' : 'velas'}.`;
    if ((c.mode ?? 'simple') === 'complex' && c.ladder) {
        const l = c.ladder;
        const acc = (a: string, n: number, u: 'usd' | 'pct', vAdd: string, vReduce: string) =>
            a === 'none' ? 'no hace nada' : `${a === 'add' ? vAdd : vReduce} ${cant(n, u)}`;
        const lims: string[] = [];
        if (l.core_amount > 0) lims.push(`posición mín ${cant(l.core_amount, l.core_unit)}`);
        if (l.cap_amount > 0) lims.push(`posición máx ${cant(l.cap_amount, l.cap_unit)}`);
        if (l.max_travel_pct > 0) lims.push(`hasta ±${fmtN(l.max_travel_pct)} % de la entrada`);
        lims.push(l.rearm ? 'cada nivel opera en cada cruce (grid)' : 'cada nivel una sola vez');
        s += ` Escalera: cada ${fmtN(l.step_pct)} % a favor ${acc(l.favor_action, l.favor_amount, l.favor_unit, 'piramida', 'toma parcial de')}; cada ${fmtN(l.step_pct)} % en contra ${acc(l.contra_action, l.contra_amount, l.contra_unit, 'promedia', 'reduce')}${lims.length ? `; ${lims.join(', ')}` : ''}.`;
    }
    return s;
}

/* ── El esquema de la escalera: un ladder simbólico con los valores vivos ──
 * No está a escala: los niveles se dibujan equidistantes (máx. 3 por lado) y
 * el rango, si recorta, se marca con una línea discontinua. Texto jamás en
 * cobre (regla del sistema de diseño); el cobre es solo la línea de entrada. */
const EsquemaEscalera: React.FC<{ l: ScalpingLadder }> = ({ l }) => {
    const W = 480, dy = 16;
    const L = 44, LX = 56, RX = 252, TX = 264;
    const paso = Math.max(0.01, l.step_pct || 0);
    const rango = l.max_travel_pct || 0;
    const maxN = rango > 0 ? Math.floor(rango / paso + 1e-9) : Infinity;
    const niv = Math.max(0, Math.min(3, maxN));
    const recortado = maxN > niv;                    // hay niveles que no se dibujan
    const y0 = (recortado ? 26 : 14) + niv * dy;     // línea de ENTRADA
    const yBot = y0 + niv * dy + (recortado ? 10 : 0);
    const H = yBot + 30;

    const favorOn = l.favor_action !== 'none' && l.favor_amount > 0;
    const contraOn = l.contra_action !== 'none' && l.contra_amount > 0;
    const verbo = (a: string, vAdd: string, vReduce: string) => (a === 'add' ? vAdd : vReduce);
    const favorTxt = favorOn
        ? `${verbo(l.favor_action, 'Piramidar', 'Tomar parcial')} ${cant(l.favor_amount, l.favor_unit)}`
        : 'la escalera no actúa';
    const contraTxt = contraOn
        ? `${verbo(l.contra_action, 'Promediar', 'Reducir')} ${cant(l.contra_amount, l.contra_unit)}`
        : 'la escalera no actúa';

    const yF = y0 - Math.max(1, niv) * dy / 2 + 2;
    const yC = y0 + Math.max(1, niv) * dy / 2 + 2;

    const nota: string[] = [];
    if (l.core_amount > 0) nota.push(`posición mín ${cant(l.core_amount, l.core_unit)}`);
    if (l.cap_amount > 0) nota.push(`posición máx ${cant(l.cap_amount, l.cap_unit)}`);
    nota.push(l.rearm ? 'cada nivel opera en cada cruce (grid)' : 'cada nivel una sola vez');
    nota.push('stop y objetivo sobre el precio medio');

    return (
        <div style={{ padding: '8px 10px 2px', background: 'var(--color-ec-bg-surface)', border: '0.5px solid var(--color-ec-border)', borderRadius: 5 }}>
            <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Esquema de la escalera del scalping"
                 style={{ display: 'block', width: '100%', height: 'auto', fontFamily: font.sans }}>
                {/* niveles a favor (arriba) y en contra (abajo) */}
                {Array.from({ length: niv }, (_, i) => i + 1).map((k) => (
                    <React.Fragment key={k}>
                        {[y0 - k * dy, y0 + k * dy].map((y, idx) => (
                            <React.Fragment key={idx}>
                                <line x1={LX} y1={y} x2={RX} y2={y} stroke={color.border} strokeWidth={1} strokeDasharray="2 3" />
                                <text x={L} y={y + 3.5} fill={color.textSecondary} fontSize={9.5} textAnchor="end" style={mono}>
                                    {`${idx === 0 ? '+' : '−'}${fmtN(k * paso)} %`}
                                </text>
                            </React.Fragment>
                        ))}
                    </React.Fragment>
                ))}
                {/* el rango recorta más allá de los niveles dibujados */}
                {recortado && [y0 - niv * dy - 10, y0 + niv * dy + 10].map((y, idx) => (
                    <React.Fragment key={idx}>
                        <line x1={LX} y1={y} x2={RX} y2={y} stroke={color.textMuted} strokeWidth={1} strokeDasharray="3 3" />
                        {idx === 0 && (
                            <text x={RX} y={y - 3} fill={color.textMuted} fontSize={9} textAnchor="end" style={mono}>
                                {rango > 0 ? `rango ±${fmtN(rango)} %` : 'más niveles…'}
                            </text>
                        )}
                    </React.Fragment>
                ))}
                {/* la entrada: la única línea cobre del esquema */}
                <line x1={LX} y1={y0} x2={RX} y2={y0} stroke={color.copper} strokeWidth={1.6} />
                <text x={RX + 6} y={y0 + 3.5} fill={color.textHigh} fontSize={9.5} fontWeight={700} letterSpacing="0.08em">ENTRADA</text>
                {/* qué pasa a cada lado */}
                <text x={TX} y={yF - 4} fontSize={9} fontWeight={700} letterSpacing="0.08em"
                      fill={favorOn ? color.profit : color.textMuted}>A FAVOR (+)</text>
                <text x={TX} y={yF + 9} fontSize={11} fill={favorOn ? color.textPrimary : color.textMuted}>{favorTxt}</text>
                <text x={TX} y={yC - 4} fontSize={9} fontWeight={700} letterSpacing="0.08em"
                      fill={contraOn ? color.warning : color.textMuted}>EN CONTRA (−)</text>
                <text x={TX} y={yC + 9} fontSize={11} fill={contraOn ? color.textPrimary : color.textMuted}>{contraTxt}</text>
                {contraOn && l.contra_action === 'add' && (
                    <text x={TX} y={yC + 22} fontSize={9} fill={color.warning}>cada promedio aleja el stop</text>
                )}
                <text x={LX} y={H - 9} fill={color.textMuted} fontSize={9.5}>{nota.join(' · ')}</text>
            </svg>
        </div>
    );
};

export const ScalpingBuilder = React.memo(({ config, onChange }: Props) => {
    const active = config.active === true;
    const sinGatillo = active && config.root_condition.conditions.length === 0;
    const complejo = (config.mode ?? 'simple') === 'complex';
    const l = config.ladder || initialScalpingLadder;
    const setL = (patch: Partial<ScalpingLadder>) => onChange({ ...config, ladder: { ...l, ...patch } });

    const ModoBtn = ({ on, onClick, title, sub }: { on: boolean; onClick: () => void; title: string; sub: string }) => (
        <button type="button" onClick={onClick} className={on ? 'bg-ec-copper/10' : undefined}
            style={{
                flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 1,
                padding: '6px 8px', borderRadius: 5, cursor: 'pointer', outline: 'none',
                border: `1px solid ${on ? 'var(--color-ec-copper)' : 'var(--color-ec-border)'}`,
                background: on ? undefined : 'var(--color-ec-bg-sidebar)',
                color: on ? 'var(--color-ec-text-high)' : 'var(--color-ec-text-secondary)',
                fontFamily: 'var(--color-ec-sans)', fontSize: 11.5, fontWeight: 600,
            }}>
            {title}
            <span style={{ fontSize: 9.5, fontWeight: 400, color: 'var(--color-ec-text-muted)' }}>{sub}</span>
        </button>
    );

    const lado = (
        title: string, help: string,
        action: ScalpingLadder['favor_action'], amount: number, un: ScalpingLadder['favor_unit'],
        patch: (a: ScalpingLadder['favor_action'], n: number, u: ScalpingLadder['favor_unit']) => void,
        opciones: { value: ScalpingLadder['favor_action']; label: string }[],
    ) => (
        <Row title={title} help={help}>
            <select value={action} onChange={(e) => patch(e.target.value as ScalpingLadder['favor_action'], amount, un)} style={control}>
                {opciones.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
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
                    {/* ── Frase-resumen: lo que hará, siempre a la vista ── */}
                    <div style={{
                        display: 'flex', gap: 10, padding: '8px 12px',
                        background: 'var(--color-ec-bg-surface)',
                        border: '0.5px solid var(--color-ec-border)',
                        borderLeft: '2px solid var(--color-ec-copper)',
                        borderRadius: 5,
                    }}>
                        <span style={{ fontFamily: 'var(--color-ec-sans)', fontSize: 11, lineHeight: 1.55, color: 'var(--color-ec-text-secondary)' }}>
                            {resumenScalping(config)}
                        </span>
                    </div>

                    {/* ── Parámetros generales ── */}
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                        <Row title="Modo" help={'Simple: entra y sale, siempre con el tamaño de «Tamaño de cada operación».\n\nCon escalera: dentro de cada operación actúa una escalera: por cada nivel de precio que toca el movimiento, piramida o toma parcial a favor, promedia o reduce en contra, entre una posición mínima y una máxima.'}>
                            <div style={{ display: 'flex', gap: 6, flex: 1 }}>
                                <ModoBtn on={!complejo} onClick={() => onChange({ ...config, mode: 'simple' })} title="Simple" sub="entra y sale" />
                                <ModoBtn on={complejo} onClick={() => onChange({ ...config, mode: 'complex', ladder: config.ladder || initialScalpingLadder })} title="Con escalera" sub="piramidar · parciales · promediar" />
                            </div>
                        </Row>
                        <Row title="Timeframe del gatillo" help="Timeframe en el que se evalúan las condiciones del gatillo.">
                            <select value={config.timeframe} onChange={(e) => onChange({ ...config, timeframe: e.target.value as Timeframe })} style={control}>
                                {TIMEFRAMES.map(tf => <option key={tf} value={tf}>{tf}</option>)}
                            </select>
                        </Row>
                        <Row title="Tamaño de cada operación" help={'% de la cifra de capital / riesgo del panel de la izquierda que usa CADA operación. 100 = la cifra entera, como cualquier entrada normal.\n\nSi el panel dice 100 $ fijos y aquí pones 10, cada operación va con 10 $; si el panel dice 1 % de la cuenta, cada operación va con el 10 % de ese 1 %. Vale igual por valor de mercado, por distancia al stop o híbrido.'}>
                            <input type="number" min={1} max={100} step={1} value={config.capital_pct ?? ''}
                                onChange={(e) => onChange({ ...config, capital_pct: e.target.value === '' ? 100 : Math.max(0.01, Math.min(100, Number(e.target.value))) })}
                                onFocus={(e) => e.target.select()} style={input} />
                            <span style={unit}>% de la cifra del panel</span>
                        </Row>
                        <Row title="Cierre por tiempo" help={'Minutos desde la entrada: si en ese tiempo no ha tocado ni el objetivo ni el stop, se sale (un «time stop»). 0 = sin cierre por tiempo propio.\n\nCon valor mayor que 0 PISA el take profit «Tiempo» de la estrategia: manda el de aquí.'}>
                            <input type="number" min={0} step={1} value={config.max_minutes ?? ''}
                                onChange={(e) => onChange({ ...config, max_minutes: num(e.target.value) })}
                                onFocus={(e) => e.target.select()} style={input} />
                            <span style={unit}>min</span>
                        </Row>
                        <Row title="Espera antes de reentrar" help="Velas que hay que esperar tras una salida antes de volver a entrar, aunque el gatillo se cumpla. 0 = ninguna.">
                            <input type="number" min={0} step={1} value={config.cooldown_bars ?? ''}
                                onChange={(e) => onChange({ ...config, cooldown_bars: e.target.value === '' ? 0 : Math.max(0, Math.floor(Number(e.target.value))) })}
                                onFocus={(e) => e.target.select()} style={input} />
                            <span style={unit}>velas</span>
                        </Row>
                    </div>

                    {/* ── Escalera (modo con escalera) ── */}
                    {complejo && (
                        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                            <span style={sectionTitle}>Escalera</span>
                            <EsquemaEscalera l={l} />
                            <div style={{ height: 8 }} />
                            <Row title="Distancia entre niveles" help="Cada cuánto actúa la escalera: % de movimiento del precio desde el ÚLTIMO nivel ejecutado (no desde la entrada), así los escalones son regulares. Ejemplo: 1 = cada 1 %.">
                                <input type="number" min={0.01} step={0.1} value={l.step_pct ?? ''}
                                    onChange={(e) => setL({ step_pct: num(e.target.value) })} onFocus={(e) => e.target.select()} style={input} />
                                <span style={unit}>%</span>
                            </Row>
                            {lado('Por cada nivel a favor (+)', 'Qué hacer por cada nivel que el precio se mueve A FAVOR de la posición (arriba en largo, abajo en corto), medido desde el último nivel ejecutado.\n\n«Tomar parcial» = vender una parte con ganancia. «Piramidar» = añadir a la posición ganadora.',
                                l.favor_action, l.favor_amount, l.favor_unit, (a, n, u) => setL({ favor_action: a, favor_amount: n, favor_unit: u }),
                                [
                                    { value: 'add', label: 'Piramidar (añadir)' },
                                    { value: 'reduce', label: 'Tomar parcial (quitar)' },
                                    { value: 'none', label: 'Nada' },
                                ])}
                            {lado('Por cada nivel en contra (−)', 'Qué hacer por cada nivel que el precio va EN CONTRA (abajo en largo, arriba en corto), medido desde el último nivel ejecutado.\n\n«Promediar» = añadir más barato para bajar el precio medio (martingala). Ojo: el stop en % se mide sobre el precio medio, así que cada promedio ALEJA el stop y el riesgo en $ crece. «Reducir» = recortar la posición en pérdida.',
                                l.contra_action, l.contra_amount, l.contra_unit, (a, n, u) => setL({ contra_action: a, contra_amount: n, contra_unit: u }),
                                [
                                    { value: 'add', label: 'Promediar (añadir)' },
                                    { value: 'reduce', label: 'Reducir (quitar)' },
                                    { value: 'none', label: 'Nada' },
                                ])}
                            <Row title="Posición mínima" help={'Capital que SIEMPRE se conserva: al quitar, la posición nunca baja de aquí.\n\n0 = se puede quitar todo; entonces la operación queda cerrada y el siguiente gatillo abre otra desde cero. Lo que quede lo cierra la salida principal.'}>
                                <input type="number" min={0} step={1} value={l.core_amount ?? ''}
                                    onChange={(e) => setL({ core_amount: num(e.target.value) })} onFocus={(e) => e.target.select()} style={input} />
                                <select value={l.core_unit} onChange={(e) => setL({ core_unit: e.target.value as ScalpingLadder['core_unit'] })} style={control}>
                                    <option value="pct">% de la posición inicial</option>
                                    <option value="usd">$</option>
                                </select>
                            </Row>
                            <Row title="Posición máxima" help={'Capital máximo de la posición: al añadir, nunca se pasa de aquí.\n\n0 = sin techo propio (manda la caja disponible, como siempre). Con «piramidar» y posición mínima > 0, la mínima no interviene: solo manda este máximo.'}>
                                <input type="number" min={0} step={1} value={l.cap_amount ?? ''}
                                    onChange={(e) => setL({ cap_amount: num(e.target.value) })} onFocus={(e) => e.target.select()} style={input} />
                                <select value={l.cap_unit} onChange={(e) => setL({ cap_unit: e.target.value as ScalpingLadder['cap_unit'] })} style={control}>
                                    <option value="pct">% de la posición inicial</option>
                                    <option value="usd">$</option>
                                </select>
                            </Row>
                            <Row title="Rango de la escalera" help="Hasta qué % desde el precio de la PRIMERA entrada de la operación actúa la escalera. Más allá no añade ni quita: la posición queda en manos de la salida principal (salida lógica, stop, objetivo, tiempo). Manda sobre la distancia entre niveles. 0 = sin límite.">
                                <input type="number" min={0} step={0.5} value={l.max_travel_pct ?? ''}
                                    onChange={(e) => setL({ max_travel_pct: num(e.target.value) })} onFocus={(e) => e.target.select()} style={input} />
                                <span style={unit}>% desde la entrada</span>
                            </Row>
                            <Row title="Repetir niveles" help={'«Una vez por nivel»: cada nivel de precio se ejecuta UNA vez por operación y por dirección (piramidar al subir a un nivel no gasta el tomar parcial al volver a bajar por él, pero una segunda subida al mismo nivel ya no añade).\n\n«Grid (siempre)»: cada nivel opera CADA VEZ que el precio lo cruza de nuevo (vende al subir, recompra al bajar…). En small caps con spread y locates, aquí es donde se ven los costes.'}>
                                {([[false, 'Una vez por nivel'], [true, 'Grid (siempre)']] as const).map(([val, txt]) => (
                                    <button key={String(val)} type="button" onClick={() => setL({ rearm: val })}
                                        className={l.rearm === val ? 'bg-ec-copper/10' : undefined}
                                        style={{
                                            height: 28, padding: '0 12px', borderRadius: 5, cursor: 'pointer', outline: 'none',
                                            border: `1px solid ${l.rearm === val ? 'var(--color-ec-copper)' : 'var(--color-ec-border)'}`,
                                            background: l.rearm === val ? undefined : 'var(--color-ec-bg-sidebar)',
                                            color: l.rearm === val ? 'var(--color-ec-text-high)' : 'var(--color-ec-text-secondary)',
                                            fontFamily: 'var(--color-ec-sans)', fontSize: 11,
                                            fontWeight: l.rearm === val ? 600 : 500,
                                        }}>
                                        {txt}
                                    </button>
                                ))}
                            </Row>
                            <span style={{ ...unit, lineHeight: 1.5, whiteSpace: 'normal' }}>
                                Cada nivel se ejecuta al precio del nivel en la vela que lo toca. El stop loss y el take profit en % se miden sobre el
                                precio medio de la posición. La salida principal (salida lógica, stop, objetivo, tiempo) siempre cierra todo.
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
