
import React from 'react';
import { PlusCircle, Trash2, AlertTriangle, Wand2 } from 'lucide-react';
import { RiskManagement, ScheduledExitRule } from '@/types/strategy';
import { cargarSchedExits, estadoSchedExits, suscribirSchedExits } from '@/lib/api_schedexits';

interface Props {
    risk: RiskManagement;
    onChange: (risk: RiskManagement) => void;
}

/** Fuentes admitidas en V1 (nombres EXACTOS del motor). */
const FUENTES = ['Bar Close', 'VWAP', 'Prev. Bar High', 'Prev. Bar Low'] as const;

const COMPARADORES: { v: string; t: string }[] = [
    { v: 'GREATER_THAN_OR_EQUAL', t: '≥' },
    { v: 'GREATER_THAN', t: '>' },
    { v: 'LESS_THAN_OR_EQUAL', t: '≤' },
    { v: 'LESS_THAN', t: '<' },
];

const ACCIONES: { v: ScheduledExitRule['action']; t: string }[] = [
    { v: 'close_pct', t: 'Cerrar % de la posición' },
    { v: 'move_stop', t: 'Mover el stop (break-even)' },
    { v: 'none', t: 'Nada (solo marcar)' },
];

const inputStyle: React.CSSProperties = {
    backgroundColor: 'var(--color-ec-bg-sidebar)',
    border: '0.5px solid var(--color-ec-border)',
    borderRadius: 5,
    color: 'var(--color-ec-text-primary)',
    padding: '5px 8px',
    fontSize: 12,
    fontFamily: 'var(--color-ec-sans)',
};

function textoRegla(r: ScheduledExitRule): string {
    const [h, m] = (r.hour || '00:00').split(':');
    const cond = r.condition?.conditions?.[0];
    const condTxt = cond
        ? `${cond.source?.name} ${COMPARADORES.find(c => c.v === cond.comparator)?.t ?? cond.comparator} ${
              typeof cond.target === 'number' ? cond.target : cond.target?.name ?? ''
          }`
        : 'siempre';
    if (r.action === 'close_pct') {
        return `A las ${h}:${m}, si ${condTxt} → cerrar el ${r.close_pct ?? 100} % de la posición restante.`;
    }
    if (r.action === 'move_stop') {
        const off = r.stop_offset_pct ?? 0;
        return `A las ${h}:${m}, si ${condTxt} → mover el stop a la entrada${off ? ` ${off > 0 ? '+' : ''}${off} %` : ' (break-even)'}.`;
    }
    return `A las ${h}:${m}, si ${condTxt} → nada (evaluación informativa).`;
}

const horaRegla = (r: ScheduledExitRule) => (r.hour || '').trim();

/** Horas HH:MM de los parciales por HORA de la estrategia (para el aviso de choque). */
function horasParcialesHORA(risk: RiskManagement): string[] {
    return (risk.partial_take_profits || [])
        .map((p) => String(p.distance_pct ?? ''))
        .filter((d) => d.startsWith('HOUR:'))
        .map((d) => {
            const p = d.split(':');
            return `${p[1]?.padStart(2, '0')}:${p[2]?.padStart(2, '0')}`;
        });
}

export const ScheduledExitsBuilder: React.FC<Props> = ({ risk, onChange }) => {
    const [enabled, setEnabled] = React.useState<boolean>(estadoSchedExits()?.enabled ?? false);

    React.useEffect(() => {
        cargarSchedExits();
        return suscribirSchedExits(() => setEnabled(!!estadoSchedExits()?.enabled));
    }, []);

    if (!enabled) return null;

    const reglas = risk.scheduled_exits || [];
    const on = reglas.length > 0;

    const setReglas = (nuevas: ScheduledExitRule[]) =>
        onChange({ ...risk, scheduled_exits: nuevas });

    const nuevaRegla = (): ScheduledExitRule => ({
        hour: '08:30',
        condition: {
            type: 'group', operator: 'AND',
            conditions: [{
                type: 'indicator_comparison',
                source: { name: 'Bar Close' },
                comparator: 'GREATER_THAN_OR_EQUAL',
                target: { name: 'VWAP' },
                timeframe: '1m',
            }],
        },
        action: 'close_pct',
        close_pct: 100,
        stop_offset_pct: 0,
    });

    const plantillaVWAP = () => setReglas([
        {
            hour: '08:30',
            condition: {
                type: 'group', operator: 'AND',
                conditions: [{
                    type: 'indicator_comparison',
                    source: { name: 'Bar Close' },
                    comparator: 'GREATER_THAN_OR_EQUAL',
                    target: { name: 'VWAP' },
                    timeframe: '1m',
                }],
            },
            action: 'close_pct', close_pct: 100, stop_offset_pct: 0,
        },
        {
            hour: '08:30',
            condition: {
                type: 'group', operator: 'AND',
                conditions: [{
                    type: 'indicator_comparison',
                    source: { name: 'Bar Close' },
                    comparator: 'LESS_THAN',
                    target: { name: 'VWAP' },
                    timeframe: '1m',
                }],
            },
            action: 'close_pct', close_pct: 50, stop_offset_pct: 0,
        },
    ]);

    const toggleOn = () => {
        if (on) {
            setReglas([]);
        } else {
            setReglas([nuevaRegla()]);
        }
    };

    const patchRegla = (i: number, patch: Partial<ScheduledExitRule>) =>
        setReglas(reglas.map((r, j) => (j === i ? { ...r, ...patch } : r)));

    const patchCond = (
        i: number,
        patch: Partial<{
            source: string; comparator: string; targetIsNum: boolean; targetNum: number; targetInd: string;
        }>,
    ) => {
        setReglas(reglas.map((r, j) => {
            if (j !== i || !r.condition?.conditions?.length) return r;
            const c = { ...r.condition.conditions[0] };
            if (patch.source !== undefined) c.source = { name: patch.source };
            if (patch.comparator !== undefined) c.comparator = patch.comparator;
            if (patch.targetIsNum !== undefined) {
                c.target = patch.targetIsNum ? 0 : { name: 'VWAP' };
            } else if (patch.targetNum !== undefined) {
                c.target = patch.targetNum;
            } else if (patch.targetInd !== undefined) {
                c.target = { name: patch.targetInd };
            }
            return { ...r, condition: { ...r.condition, conditions: [c] } };
        }));
    };

    // Aviso de choque: parcial por HORA a la misma hora que una regla.
    const horasHito = horasParcialesHORA(risk);
    const choques = Array.from(new Set(
        reglas.map(horaRegla).filter((h) => h && horasHito.includes(h)),
    ));

    return (
        <div style={{
            display: 'flex',
            flexDirection: 'column',
            gap: 16,
            padding: '20px 0',
            backgroundColor: 'transparent',
            borderBottom: '0.5px solid var(--color-ec-border)',
        }}>
            {/* Header (patrón de las secciones vecinas: barra lateral cobre + UPPER + ON/OFF) */}
            <div style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                paddingBottom: on ? 12 : 0,
                borderBottom: on ? '0.5px solid var(--color-ec-border)' : 'none',
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
                        }}>Salidas Programadas Condicionales</h2>
                    </div>
                    <span style={{
                        fontFamily: 'var(--color-ec-sans)',
                        fontSize: 10,
                        fontWeight: 400,
                        color: 'var(--color-ec-text-muted)',
                        marginTop: 2,
                        maxWidth: 520,
                        lineHeight: 1.5,
                    }}>
                        Gestiona la posición a una hora concreta según cómo esté el precio. Ej.: a las
                        08:30, si el precio está por encima del VWAP, cierra el 100 %; si está por
                        debajo, cierra el 50 % y deja correr el resto. Las reglas se evalúan en orden,
                        una vez por operación, en la primera vela de esa hora.
                    </span>
                </div>
                <div className="flex items-center gap-2">
                    <span style={{
                        fontFamily: 'var(--color-ec-sans)',
                        fontSize: 10,
                        fontWeight: 700,
                        color: 'var(--color-ec-text-muted)',
                    }}>{on ? 'ON' : 'OFF'}</span>
                    <div
                        className={`w-8 h-4 rounded-full relative cursor-pointer transition-colors ${on ? 'bg-[var(--color-ec-copper)]/70' : 'bg-muted'}`}
                        onClick={toggleOn}
                    >
                        <div className={`absolute top-0.5 w-3 h-3 rounded-full bg-white transition-all shadow-sm ${on ? 'left-4.5' : 'left-0.5'}`}></div>
                    </div>
                </div>
            </div>

            {/* Body */}
            {on && (
                <div className="space-y-3 animate-in fade-in duration-200">
                    {choques.map((h) => (
                        <div
                            key={`choque-${h}`}
                            className="flex items-center gap-2 p-2 rounded-lg border"
                            style={{
                                backgroundColor: 'color-mix(in srgb, var(--color-ec-copper) 6%, transparent)',
                                borderColor: 'color-mix(in srgb, var(--color-ec-copper) 25%, transparent)',
                            }}
                        >
                            <AlertTriangle size={13} style={{ color: 'var(--color-ec-copper)', flexShrink: 0 }} />
                            <span style={{
                                fontFamily: 'var(--color-ec-sans)',
                                fontSize: 10,
                                fontWeight: 600,
                                color: 'var(--color-ec-text-primary)',
                            }}>
                                Ojo: tienes también un parcial a las {h}. Se aplican los dos.
                            </span>
                        </div>
                    ))}

                    {reglas.map((r, i) => {
                        const c = r.condition?.conditions?.[0];
                        const targetIsNum = typeof c?.target === 'number';
                        return (
                            <div key={i} style={{
                                backgroundColor: 'var(--color-ec-bg-elevated)',
                                border: '0.5px solid var(--color-ec-border)',
                                borderRadius: 7,
                                padding: 12,
                                display: 'flex',
                                flexDirection: 'column',
                                gap: 10,
                            }}>
                                <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
                                    <span style={{
                                        fontFamily: 'var(--color-ec-sans)', fontSize: 9, fontWeight: 700,
                                        textTransform: 'uppercase', letterSpacing: '0.1em',
                                        color: 'var(--color-ec-text-muted)',
                                    }}>Regla {i + 1} · Hora</span>
                                    <input
                                        type="time" value={r.hour} style={{ ...inputStyle, width: 92 }}
                                        onChange={(e) => patchRegla(i, { hour: e.target.value || '08:30' })}
                                    />
                                    <span style={{ fontSize: 11, color: 'var(--color-ec-text-muted)' }}>· Si</span>
                                    <select style={inputStyle} value={c?.source?.name ?? 'Bar Close'}
                                            onChange={(e) => patchCond(i, { source: e.target.value })}>
                                        {FUENTES.map((f) => <option key={f} value={f}>{f}</option>)}
                                    </select>
                                    <select style={{ ...inputStyle, width: 54 }} value={c?.comparator ?? 'GREATER_THAN_OR_EQUAL'}
                                            onChange={(e) => patchCond(i, { comparator: e.target.value })}>
                                        {COMPARADORES.map((x) => <option key={x.v} value={x.v}>{x.t}</option>)}
                                    </select>
                                    {targetIsNum ? (
                                        <input type="number" step="any" style={{ ...inputStyle, width: 84 }}
                                               value={Number(c?.target ?? 0)}
                                               onChange={(e) => patchCond(i, { targetNum: Number(e.target.value) })} />
                                    ) : (
                                        <select style={inputStyle} value={(c?.target as { name: string })?.name ?? 'VWAP'}
                                                onChange={(e) => patchCond(i, { targetInd: e.target.value })}>
                                            {FUENTES.map((f) => <option key={f} value={f}>{f}</option>)}
                                        </select>
                                    )}
                                    <select style={{ ...inputStyle, width: 36 }} title="Tipo de objetivo"
                                            value={targetIsNum ? 'num' : 'ind'}
                                            onChange={(e) => patchCond(i, { targetIsNum: e.target.value === 'num' })}>
                                        <option value="ind">ind.</option>
                                        <option value="num">nº</option>
                                    </select>
                                    <span style={{ fontSize: 11, color: 'var(--color-ec-text-muted)' }}>→</span>
                                    <select style={{ ...inputStyle, width: 200 }} value={r.action}
                                            onChange={(e) => patchRegla(i, { action: e.target.value as ScheduledExitRule['action'] })}>
                                        {ACCIONES.map((a) => <option key={a.v} value={a.v}>{a.t}</option>)}
                                    </select>
                                    {r.action === 'close_pct' && (
                                        <input type="number" min={1} max={100} style={{ ...inputStyle, width: 62 }}
                                               title="% del tamaño restante a cerrar"
                                               value={r.close_pct ?? 100}
                                               onChange={(e) => patchRegla(i, { close_pct: Math.max(1, Math.min(100, Number(e.target.value) || 100)) })} />
                                    )}
                                    {r.action === 'move_stop' && (
                                        <input type="number" step="any" style={{ ...inputStyle, width: 62 }}
                                               title="Stop a entrada +/- este % (0 = break-even)"
                                               value={r.stop_offset_pct ?? 0}
                                               onChange={(e) => patchRegla(i, { stop_offset_pct: Number(e.target.value) || 0 })} />
                                    )}
                                    <button
                                        title="Quitar regla" onClick={() => setReglas(reglas.filter((_, j) => j !== i))}
                                        style={{ marginLeft: 'auto', background: 'none', border: 'none', cursor: 'pointer', color: 'var(--color-ec-text-muted)' }}>
                                        <Trash2 size={14} />
                                    </button>
                                </div>
                                {/* Resumen legible resaltado en cobre */}
                                <div style={{
                                    padding: '7px 10px',
                                    borderRadius: 5,
                                    backgroundColor: 'color-mix(in srgb, var(--color-ec-copper) 8%, transparent)',
                                    border: '0.5px solid color-mix(in srgb, var(--color-ec-copper) 22%, transparent)',
                                    fontFamily: 'var(--color-ec-sans)',
                                    fontSize: 12,
                                    fontWeight: 600,
                                    color: 'var(--color-ec-copper-bright, #E89C6A)',
                                    lineHeight: 1.45,
                                }}>
                                    {textoRegla(r)}
                                </div>
                            </div>
                        );
                    })}

                    {/* Acciones: plantilla + añadir (botón principal cobre) */}
                    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center', marginTop: 4 }}>
                        <button
                            onClick={() => setReglas([...reglas, nuevaRegla()])}
                            style={{
                                display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer',
                                backgroundColor: 'var(--color-ec-copper)',
                                color: 'var(--color-ec-copper-text, #1A0A00)',
                                border: 'none',
                                borderRadius: 5,
                                fontFamily: 'var(--color-ec-sans)',
                                fontSize: 10,
                                fontWeight: 700,
                                textTransform: 'uppercase',
                                letterSpacing: '0.1em',
                                padding: '8px 14px',
                            }}
                        >
                            <PlusCircle size={13} /> Añadir regla
                        </button>
                        <button
                            onClick={plantillaVWAP}
                            title="Rellena las dos reglas del ejemplo: ≥ VWAP → cerrar 100 %; < VWAP → cerrar 50 %"
                            style={{
                                display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer',
                                backgroundColor: 'transparent',
                                color: 'var(--color-ec-text-muted)',
                                border: '0.5px dashed var(--color-ec-border)',
                                borderRadius: 5,
                                fontFamily: 'var(--color-ec-sans)',
                                fontSize: 10,
                                fontWeight: 700,
                                textTransform: 'uppercase',
                                letterSpacing: '0.1em',
                                padding: '8px 12px',
                            }}
                            onMouseEnter={(e) => {
                                e.currentTarget.style.borderColor = 'var(--color-ec-copper)';
                                e.currentTarget.style.color = 'var(--color-ec-copper)';
                            }}
                            onMouseLeave={(e) => {
                                e.currentTarget.style.borderColor = 'var(--color-ec-border)';
                                e.currentTarget.style.color = 'var(--color-ec-text-muted)';
                            }}
                        >
                            <Wand2 size={13} /> Usar plantilla VWAP 08:30
                        </button>
                    </div>
                </div>
            )}
        </div>
    );
};
