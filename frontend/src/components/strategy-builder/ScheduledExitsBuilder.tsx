
import React from 'react';
import { PlusCircle, Trash2, Info } from 'lucide-react';
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
    backgroundColor: 'var(--color-ec-bg-secondary, #1c1c1e)',
    border: '1px solid var(--color-ec-border, #333)',
    borderRadius: 6,
    color: 'inherit',
    padding: '6px 8px',
    fontSize: 13,
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

export const ScheduledExitsBuilder: React.FC<Props> = ({ risk, onChange }) => {
    const [enabled, setEnabled] = React.useState<boolean>(estadoSchedExits()?.enabled ?? false);

    React.useEffect(() => {
        cargarSchedExits();
        return suscribirSchedExits(() => setEnabled(!!estadoSchedExits()?.enabled));
    }, []);

    if (!enabled) return null;

    const reglas = risk.scheduled_exits || [];

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

    const patchRegla = (i: number, patch: Partial<ScheduledExitRule>) =>
        setReglas(reglas.map((r, j) => (j === i ? { ...r, ...patch } : r)));

    const patchCond = (i: number, patch: Partial<{
        source: string; comparator: string; targetIsNum: boolean; targetNum: number; targetInd: string;
    }>) => {
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

    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12, padding: '20px 0', borderBottom: '0.5px solid var(--color-ec-border)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <Info size={15} opacity={0.6} />
                <span style={{ fontWeight: 600 }}>Salidas programadas condicionales</span>
                <span style={{ opacity: 0.55, fontSize: 12 }}>
                    «A una hora, si se cumple una condición → acción sobre lo que quede abierto»
                </span>
            </div>

            {reglas.map((r, i) => {
                const c = r.condition?.conditions?.[0];
                const targetIsNum = typeof c?.target === 'number';
                return (
                    <div key={i} style={{
                        border: '1px solid var(--color-ec-border)', borderRadius: 10, padding: 12,
                        display: 'flex', flexDirection: 'column', gap: 10,
                    }}>
                        <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                            <span style={{ fontSize: 12, opacity: 0.7 }}>Hora</span>
                            <input
                                type="time" value={r.hour} style={{ ...inputStyle, width: 100 }}
                                onChange={(e) => patchRegla(i, { hour: e.target.value || '08:30' })}
                            />
                            <span style={{ fontSize: 12, opacity: 0.7 }}>· Si</span>
                            <select style={inputStyle} value={c?.source?.name ?? 'Bar Close'}
                                    onChange={(e) => patchCond(i, { source: e.target.value })}>
                                {FUENTES.map((f) => <option key={f} value={f}>{f}</option>)}
                            </select>
                            <select style={{ ...inputStyle, width: 60 }} value={c?.comparator ?? 'GREATER_THAN_OR_EQUAL'}
                                    onChange={(e) => patchCond(i, { comparator: e.target.value })}>
                                {COMPARADORES.map((x) => <option key={x.v} value={x.v}>{x.t}</option>)}
                            </select>
                            {targetIsNum ? (
                                <input type="number" step="any" style={{ ...inputStyle, width: 90 }}
                                       value={Number(c?.target ?? 0)}
                                       onChange={(e) => patchCond(i, { targetNum: Number(e.target.value) })} />
                            ) : (
                                <select style={inputStyle} value={(c?.target as { name: string })?.name ?? 'VWAP'}
                                        onChange={(e) => patchCond(i, { targetInd: e.target.value })}>
                                    {FUENTES.map((f) => <option key={f} value={f}>{f}</option>)}
                                </select>
                            )}
                            <select style={{ ...inputStyle, width: 40 }} title="Tipo de objetivo"
                                    value={targetIsNum ? 'num' : 'ind'}
                                    onChange={(e) => patchCond(i, { targetIsNum: e.target.value === 'num' })}>
                                <option value="ind">indicador</option>
                                <option value="num">número</option>
                            </select>
                            <span style={{ fontSize: 12, opacity: 0.7 }}>→</span>
                            <select style={{ ...inputStyle, width: 210 }} value={r.action}
                                    onChange={(e) => patchRegla(i, { action: e.target.value as ScheduledExitRule['action'] })}>
                                {ACCIONES.map((a) => <option key={a.v} value={a.v}>{a.t}</option>)}
                            </select>
                            {r.action === 'close_pct' && (
                                <input type="number" min={1} max={100} style={{ ...inputStyle, width: 70 }}
                                       title="% del tamaño restante a cerrar"
                                       value={r.close_pct ?? 100}
                                       onChange={(e) => patchRegla(i, { close_pct: Math.max(1, Math.min(100, Number(e.target.value) || 100)) })} />
                            )}
                            {r.action === 'move_stop' && (
                                <input type="number" step="any" style={{ ...inputStyle, width: 70 }}
                                       title="Stop a entrada +/- este % (0 = break-even)"
                                       value={r.stop_offset_pct ?? 0}
                                       onChange={(e) => patchRegla(i, { stop_offset_pct: Number(e.target.value) || 0 })} />
                            )}
                            <button
                                title="Quitar regla" onClick={() => setReglas(reglas.filter((_, j) => j !== i))}
                                style={{ marginLeft: 'auto', background: 'none', border: 'none', cursor: 'pointer', color: 'inherit' }}>
                                <Trash2 size={15} opacity={0.7} />
                            </button>
                        </div>
                        <div style={{ fontSize: 12.5, opacity: 0.8, fontStyle: 'italic' }}>
                            {textoRegla(r)}
                        </div>
                    </div>
                );
            })}

            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <button
                    onClick={() => setReglas([...reglas, nuevaRegla()])}
                    style={{
                        display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer',
                        background: 'none', border: '1px dashed var(--color-ec-border)',
                        borderRadius: 8, color: 'inherit', padding: '7px 12px', fontSize: 13,
                    }}>
                    <PlusCircle size={15} /> Añadir regla
                </button>
                {reglas.length === 0 && (
                    <span style={{ fontSize: 12, opacity: 0.5 }}>
                        Cada regla se evalúa una vez por operación, en la primera vela de esa hora o después.
                    </span>
                )}
            </div>
        </div>
    );
};
