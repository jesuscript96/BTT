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

// ── CAMINO DE CONDICIONES (PRD 2026-09-16) ──
// Un nivel puede declarar una cadena ORDENADA de condiciones en vez de una
// sola: engancha el último paso = dispara. Los helpers de aquí son la única
// definición de "es camino" / "es válido" que usan el builder y los dos
// puntos que serializan el payload (StrategyForm e InlineStrategyBuilder
// llevan su copia local de `nivelValido`, igual que hacen con el resto).
const GRUPO_VACIO = (): any => ({ type: "group", operator: "AND", conditions: [] });

const esCamino = (l: PyramidLevel) => Array.isArray(l.steps);

export const nivelPiramideValido = (l: PyramidLevel) => esCamino(l)
    ? (l.steps!.length >= 2 && l.steps!.every(s => (s?.conditions?.length ?? 0) > 0))
    : ((l.root_condition?.conditions?.length ?? 0) > 0);

// El nivel-camino NO viaja con root_condition: son mutuamente excluyentes y
// el backend rebota con 422 un nivel con ambas.
export const nivelPiramideParaPayload = (l: PyramidLevel): PyramidLevel =>
    esCamino(l) ? { ...l, root_condition: undefined } : l;

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

    // ── Camino: conmutador, pasos y reordenación ▲▼ ──
    const toggleCamino = (idx: number, on: boolean) => {
        const lv = config.levels[idx];
        if (on) {
            // El 1er paso arranca con la condición que ya tenía el nivel (si
            // la había) y el 2º vacío. La condición única deja de viajar.
            const primero = (lv.root_condition?.conditions?.length ?? 0) > 0
                ? JSON.parse(JSON.stringify(lv.root_condition))
                : GRUPO_VACIO();
            setLevel(idx, {
                ...lv,
                steps: [primero, GRUPO_VACIO()],
                same_bar: lv.same_bar ?? true,
            });
        } else {
            // Al apagar vuelve el editor único. Si la definición cargada era
            // camino, la condición única arranca vacía (los pasos no se
            // colapsan: se pierden al apagar el camino, como cualquier otro
            // campo que se deja de usar).
            setLevel(idx, {
                ...lv,
                steps: undefined,
                same_bar: undefined,
                root_condition: lv.root_condition ?? GRUPO_VACIO(),
            });
        }
    };

    const setPaso = (idx: number, p: number, grupo: any) => {
        const lv = config.levels[idx];
        const steps = lv.steps!.slice();
        steps[p] = grupo;
        setLevel(idx, { ...lv, steps });
    };

    const addPaso = (idx: number) => {
        const lv = config.levels[idx];
        setLevel(idx, { ...lv, steps: [...lv.steps!, GRUPO_VACIO()] });
    };

    const removePaso = (idx: number, p: number) => {
        const lv = config.levels[idx];
        if ((lv.steps?.length ?? 0) <= 2) return;   // mínimo 2 pasos
        setLevel(idx, { ...lv, steps: lv.steps!.filter((_, i) => i !== p) });
    };

    const movePaso = (idx: number, p: number, dir: -1 | 1) => {
        const lv = config.levels[idx];
        const steps = lv.steps!.slice();
        const destino = p + dir;
        if (destino < 0 || destino >= steps.length) return;
        [steps[p], steps[destino]] = [steps[destino], steps[p]];
        setLevel(idx, { ...lv, steps });
    };

    // El contador que pidió el usuario: cuánto llevamos añadido y cuánto
    // quitado. Los añadidos se suman en % del equity. Las quitas son % de la
    // posición FLOTANTE y se encadenan: dos quitas del 50% dejan el 25%, así
    // que lo honesto es mostrar el total efectivo 1 - prod(1 - pct).
    // Los niveles en % y los niveles en $ NO se pueden sumar entre si, asi que
    // cada unidad lleva su propio total y solo se muestra la que exista.
    const isUsd = (l: PyramidLevel) => (l.unit ?? 'pct') === 'usd';
    const adds = config.levels.filter(l => l.action === 'add' && !isUsd(l));
    const reduces = config.levels.filter(l => l.action === 'reduce' && !isUsd(l));
    const addsUsd = config.levels.filter(l => l.action === 'add' && isUsd(l));
    const reducesUsd = config.levels.filter(l => l.action === 'reduce' && isUsd(l));
    // cada nivel puede disparar `times` veces: los añadidos se multiplican y
    // las quitas se encadenan tambien por sus repeticiones
    const totalAddPct = adds.reduce((s, l) => s + (l.capital_pct || 0) * Math.max(1, l.times || 1), 0);
    const totalReducePct = (1 - reduces.reduce(
        (p, l) => p * Math.pow(1 - Math.min(100, l.capital_pct || 0) / 100, Math.max(1, l.times || 1)), 1)) * 100;
    // en dolares si se suman: son cantidades fijas
    const totalAddUsd = addsUsd.reduce((s, l) => s + (l.capital_pct || 0) * Math.max(1, l.times || 1), 0);
    const totalReduceUsd = reducesUsd.reduce((s, l) => s + (l.capital_pct || 0) * Math.max(1, l.times || 1), 0);

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
                                {'Añadidos: '}
                                {[
                                    totalAddPct > 0 ? `+${totalAddPct.toFixed(1)}% del equity` : null,
                                    totalAddUsd > 0 ? `+$${totalAddUsd.toFixed(0)}` : null,
                                ].filter(Boolean).join(' y ') || '+0'}
                                {' · Quitas: '}
                                {[
                                    reduces.length > 0 ? `−${totalReducePct.toFixed(1)}% de la posición` : null,
                                    totalReduceUsd > 0 ? `−$${totalReduceUsd.toFixed(0)} de posición` : null,
                                ].filter(Boolean).join(' y ') || '−0'}
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
                            {/* Cabecera: el título y el botón de eliminar en su
                                propia línea. Antes iba todo en una sola fila y
                                en un panel estrecho el `wrap` descolocaba el
                                campo "Veces" a la línea de abajo, desalineado. */}
                            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                                <span style={{
                                    fontFamily: 'var(--color-ec-sans)', fontSize: 10, fontWeight: 700,
                                    color: 'var(--color-ec-text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em',
                                }}>Pirámide {idx + 1}</span>
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
                                        padding: 0,
                                    }}
                                    title="Eliminar esta pirámide"
                                >✕ eliminar</button>
                            </div>
                            {/* Controles, todos en una fila que sí cabe. */}
                            <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
                                <select
                                    value={lv.action}
                                    onChange={(e) => {
                                        const a = e.target.value as 'add' | 'reduce';
                                        // Al pasar a Quitar, el SL de lote se retira:
                                        // un reduce cierra, no abre lotes, y la clave
                                        // en un nivel reduce rebota con 422 al guardar.
                                        setLevel(idx, a === 'reduce'
                                            ? { ...lv, action: a, lot_stop: null }
                                            : { ...lv, action: a });
                                    }}
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
                                    style={{ ...selectStyle, width: 62, cursor: 'text' }}
                                    title={(lv.unit ?? 'pct') === 'usd'
                                        ? (lv.action === 'add'
                                            ? 'Dólares fijos que se añaden a la posición, convertidos a acciones al precio de la barra'
                                            : 'Dólares de posición que se cierran, convertidos a acciones al precio de la barra')
                                        : (lv.action === 'add'
                                            ? '% del equity de la cuenta que se añade a la posición'
                                            : '% de la posición flotante que se cierra')}
                                />
                                <select
                                    value={lv.unit ?? 'pct'}
                                    onChange={(e) => setLevel(idx, { ...lv, unit: e.target.value as 'pct' | 'usd' })}
                                    style={selectStyle}
                                    title="Si la cantidad es un porcentaje o una cifra fija en dólares"
                                >
                                    <option value="pct">%</option>
                                    <option value="usd">$</option>
                                </select>
                                {/* MODO DE TAMAÑO DEL AÑADIDO, independiente del de
                                    la entrada. Hasta el 2026-09-04 la pirámide iba
                                    SIEMPRE por valor de mercado y no había forma de
                                    cambiarlo: con el mismo stop, el añadido acababa
                                    arriesgando una fracción de lo que arriesga la
                                    entrada (medido en vivo con MIMI: 146 $ frente a
                                    300 $) sin que nada lo dijera. */}
                                {lv.action === 'add' && (
                                    <select
                                        value={lv.hybrid_stop ? 'hibrido' : lv.size_by_sl ? 'sl' : 'mv'}
                                        onChange={(e) => {
                                            const m = e.target.value;
                                            setLevel(idx, {
                                                ...lv,
                                                size_by_sl: m !== 'mv',
                                                hybrid_stop: m === 'hibrido',
                                            });
                                        }}
                                        style={selectStyle}
                                        title={'Cómo se convierte la cantidad en acciones:\n'
                                            + '· Valor de mercado — se divide por el precio (como siempre)\n'
                                            + '· Distancia al stop — la cantidad es la PÉRDIDA máxima\n'
                                            + '· Híbrido — por stop, pero con techo de exposición'}
                                    >
                                        <option value="mv">por valor de mercado</option>
                                        <option value="sl">por distancia al stop</option>
                                        <option value="hibrido">híbrido (stop + techo)</option>
                                    </select>
                                )}
                                {lv.action === 'add' && lv.hybrid_stop && (
                                    <>
                                        <input
                                            type="number" min={1} step={100}
                                            value={lv.hybrid_black_swan_pct ?? ''}
                                            placeholder="evento %"
                                            title="El peor movimiento en contra que quieres contemplar, en %."
                                            onChange={(e) => setLevel(idx, { ...lv, hybrid_black_swan_pct: e.target.value === '' ? null : Number(e.target.value) })}
                                            style={{ ...selectStyle, width: 76, cursor: 'text' }}
                                        />
                                        <input
                                            type="number" min={1} max={100} step={5}
                                            value={lv.hybrid_max_loss_pct ?? ''}
                                            placeholder="cuenta %"
                                            title="Cuánto de tu CUENTA ENTERA aceptas perder si eso pasa, en %. Repártelo con el de la entrada."
                                            onChange={(e) => setLevel(idx, { ...lv, hybrid_max_loss_pct: e.target.value === '' ? null : Number(e.target.value) })}
                                            style={{ ...selectStyle, width: 76, cursor: 'text' }}
                                        />
                                    </>
                                )}
                                {/* Texto corto: el detalle completo está en el
                                    tooltip del campo de la cantidad.
                                    OJO: con el modo por stop la cantidad deja de
                                    ser capital y pasa a ser PÉRDIDA MÁXIMA. Decir
                                    "fijos" ahí engañaría sobre lo que se teclea. */}
                                <span style={{ fontFamily: 'var(--color-ec-sans)', fontSize: 10, color: 'var(--color-ec-text-muted)', whiteSpace: 'nowrap' }}>
                                    {lv.action === 'add' && lv.size_by_sl
                                        ? 'de pérdida máxima'
                                        : (lv.unit ?? 'pct') === 'usd'
                                            ? (lv.action === 'add' ? 'fijos' : 'de posición')
                                            : (lv.action === 'add' ? 'del equity' : 'de la posición')}
                                </span>
                                <span style={{ fontFamily: 'var(--color-ec-sans)', fontSize: 10, fontWeight: 600, color: 'var(--color-ec-text-muted)', marginLeft: 4, whiteSpace: 'nowrap' }}>Veces:</span>
                                <input
                                    type="number"
                                    min={1}
                                    max={100}
                                    step={1}
                                    value={lv.times ?? 1}
                                    onChange={(e) => setLevel(idx, { ...lv, times: e.target.value === '' ? 1 : Math.max(1, Math.floor(Number(e.target.value))) })}
                                    onFocus={(e) => e.target.select()}
                                    style={{ ...selectStyle, width: 48, cursor: 'text' }}
                                    title="Cuántas veces puede disparar esta pirámide por trade (cada cumplimiento nuevo de la condición cuenta una vez)"
                                />
                            </div>
                            {/* ── SL DEL LOTE (PRD 2026-09-15) ──
                                Solo en niveles Añadir: cada ejecución del nivel
                                lleva su propio cinturón, que al romperse cierra
                                SOLO ese lote (el stop del trade sigue mandando
                                sobre el conjunto). Mismo vocabulario que el SL
                                de la estrategia; el backend resuelve los
                                nombres vía normaliza_lot_stop. */}
                            {lv.action === 'add' && (
                                <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
                                    <span style={{ fontFamily: 'var(--color-ec-sans)', fontSize: 10, fontWeight: 600, color: 'var(--color-ec-text-muted)', whiteSpace: 'nowrap' }}>SL del lote:</span>
                                    <select
                                        value={lv.lot_stop?.mode ?? ''}
                                        onChange={(e) => {
                                            const m = e.target.value;
                                            setLevel(idx, {
                                                ...lv,
                                                lot_stop: m === '' ? null
                                                    : m === 'pct'
                                                        ? { mode: 'pct', pct: lv.lot_stop?.pct ?? 2.5 }
                                                        : { mode: 'structure', level: lv.lot_stop?.level ?? 'Ultimo pivote alto', offset_pct: lv.lot_stop?.offset_pct ?? 0.5 },
                                            });
                                        }}
                                        style={selectStyle}
                                        title={
                                            "Stop propio de CADA añadido de este nivel.\n" +
                                            "Al romperse cierra SOLO ese lote, con su PnL contra su precio de entrada;\n" +
                                            "el stop del trade sigue mandando sobre el conjunto (misma vela: manda el global).\n" +
                                            "% — distancia fija desde el precio del lote.\n" +
                                            "Estructura — un nivel del día, congelado en la vela de señal del añadido.\n" +
                                            "Sin cinturón (—), el lote vive y muere con el stop del trade, como siempre.\n" +
                                            "Si con el modo por distancia al stop la distancia que dimensiona el añadido\n" +
                                            "es la de ESTE SL, el lote arriesga exactamente lo que el nivel declara."
                                        }
                                    >
                                        <option value="">—</option>
                                        <option value="pct">%</option>
                                        <option value="structure">estructura</option>
                                    </select>
                                    {lv.lot_stop?.mode === 'pct' && (
                                        <>
                                            <input
                                                type="number" min={0.1} step={0.1}
                                                value={lv.lot_stop.pct ?? ''}
                                                onChange={(e) => setLevel(idx, { ...lv, lot_stop: { mode: 'pct', pct: e.target.value === '' ? 0 : Number(e.target.value) } })}
                                                onFocus={(e) => e.target.select()}
                                                style={{ ...selectStyle, width: 62, cursor: 'text' }}
                                                title="Distancia % desde el precio de entrada del lote (lado perdedor según el bias)."
                                            />
                                            <span style={{ fontFamily: 'var(--color-ec-sans)', fontSize: 10, color: 'var(--color-ec-text-muted)', whiteSpace: 'nowrap' }}>de holgura</span>
                                        </>
                                    )}
                                    {lv.lot_stop?.mode === 'structure' && (
                                        <>
                                            <select
                                                value={lv.lot_stop.level ?? 'Ultimo pivote alto'}
                                                onChange={(e) => setLevel(idx, { ...lv, lot_stop: { ...lv.lot_stop!, mode: 'structure', level: e.target.value } })}
                                                style={selectStyle}
                                                title="El nivel del día vigente en la vela de señal del añadido (mismos niveles que el SL de la estrategia)."
                                            >
                                                <option value="Ultimo pivote alto">Último pivote alto</option>
                                                <option value="Ultimo pivote bajo">Último pivote bajo</option>
                                                <option value="Previous Max">Previous Max</option>
                                                <option value="HOD">HOD</option>
                                                <option value="LOD">LOD</option>
                                            </select>
                                            {(lv.lot_stop.level === 'Ultimo pivote alto' || lv.lot_stop.level === 'Ultimo pivote bajo') && (
                                                <input
                                                    type="number" min={1} step={1}
                                                    value={lv.lot_stop.pivot_window ?? ''}
                                                    placeholder="3"
                                                    onChange={(e) => setLevel(idx, { ...lv, lot_stop: { ...lv.lot_stop!, mode: 'structure', pivot_window: e.target.value === '' ? undefined : Math.max(1, Math.floor(Number(e.target.value))) } })}
                                                    onBlur={(e) => {
                                                        const v = parseInt(e.target.value, 10);
                                                        setLevel(idx, { ...lv, lot_stop: { ...lv.lot_stop!, mode: 'structure', pivot_window: isNaN(v) ? 3 : v } });
                                                    }}
                                                    onFocus={(e) => e.target.select()}
                                                    style={{ ...selectStyle, width: 56, cursor: 'text' }}
                                                    title="Velas de confirmación del pivote (3 por defecto). Mientras no haya pivote confirmado, el añadido NO se ejecuta: sin cinturón no hay lote."
                                                />
                                            )}
                                            <input
                                                type="number" min={0} step={0.1}
                                                value={lv.lot_stop.offset_pct ?? ''}
                                                placeholder="0"
                                                onChange={(e) => setLevel(idx, { ...lv, lot_stop: { ...lv.lot_stop!, mode: 'structure', offset_pct: e.target.value === '' ? 0 : Number(e.target.value) } })}
                                                onFocus={(e) => e.target.select()}
                                                style={{ ...selectStyle, width: 56, cursor: 'text' }}
                                                title="Holgura en % que ALEJA el stop del precio (arriba en corto, abajo en largo)."
                                            />
                                            <span style={{ fontFamily: 'var(--color-ec-sans)', fontSize: 10, color: 'var(--color-ec-text-muted)', whiteSpace: 'nowrap' }}>+ % holgura</span>
                                        </>
                                    )}
                                </div>
                            )}
                            {/* ── CAMINO DE CONDICIONES (PRD 2026-09-16) ──
                                Cadena ORDENADA: cada paso es el mismo editor
                                de condiciones de siempre; el nivel dispara al
                                engancharse el ÚLTIMO. OFF (default) = un solo
                                bloque, como siempre. */}
                            <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                                <span style={{ fontFamily: 'var(--color-ec-sans)', fontSize: 10, fontWeight: 600, color: 'var(--color-ec-text-muted)', whiteSpace: 'nowrap' }}>Camino (condiciones en secuencia)</span>
                                <div
                                    className={`w-8 h-4 rounded-full relative cursor-pointer transition-colors ${esCamino(lv) ? 'bg-ec-copper/70' : 'bg-muted'}`}
                                    onClick={() => toggleCamino(idx, !esCamino(lv))}
                                    title={'OFF: una única condición, como siempre.\nON: cadena ordenada de condiciones — primero se cumple la 1ª, luego la 2ª\n(aunque la 1ª ya no se cumpla)… y al engancharse la ÚLTIMA se ejecuta\nla acción. Los pasos intermedios no operan: solo abren la puerta.'}
                                >
                                    <div className={`absolute top-0.5 w-3 h-3 rounded-full bg-white transition-all shadow-sm ${esCamino(lv) ? 'left-4.5' : 'left-0.5'}`}></div>
                                </div>
                                {esCamino(lv) && (
                                    <>
                                        <span style={{ fontFamily: 'var(--color-ec-sans)', fontSize: 10, color: 'var(--color-ec-text-muted)', marginLeft: 6, whiteSpace: 'nowrap' }}>Permitir completar en la misma vela</span>
                                        <div
                                            className={`w-8 h-4 rounded-full relative cursor-pointer transition-colors ${(lv.same_bar ?? true) ? 'bg-ec-copper/70' : 'bg-muted'}`}
                                            onClick={() => setLevel(idx, { ...lv, same_bar: !(lv.same_bar ?? true) })}
                                            title={'ON (default): el camino puede completarse en la MISMA vela — con pasos\nsimultáneos equivale al AND clásico.\nOFF: el paso siguiente solo puede engancharse en la vela posterior o más\ntarde (≥1 vela entre enganches).'}
                                        >
                                            <div className={`absolute top-0.5 w-3 h-3 rounded-full bg-white transition-all shadow-sm ${(lv.same_bar ?? true) ? 'left-4.5' : 'left-0.5'}`}></div>
                                        </div>
                                    </>
                                )}
                            </div>
                            {esCamino(lv) ? (
                                <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                                    {(lv.steps ?? []).map((paso, p) => (
                                        <div key={p} style={{
                                            border: '0.5px solid var(--color-ec-border)',
                                            borderRadius: 6,
                                            padding: '8px 10px',
                                            display: 'flex',
                                            flexDirection: 'column',
                                            gap: 8,
                                        }}>
                                            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                                                <span style={{
                                                    fontFamily: 'var(--color-ec-sans)', fontSize: 10, fontWeight: 700,
                                                    color: 'var(--color-ec-text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em',
                                                }}>{`${p + 1}º paso`}</span>
                                                {/* ▲▼: reordenar pasos. El orden ES la semántica del
                                                    camino (mismo patrón que Portfolio/Robustez). */}
                                                <button
                                                    type="button"
                                                    disabled={p === 0}
                                                    onClick={() => movePaso(idx, p, -1)}
                                                    title="Subir el paso un puesto"
                                                    style={{
                                                        width: 18, height: 18, padding: 0,
                                                        border: '0.5px solid var(--color-ec-border)', borderRadius: 5,
                                                        background: 'transparent', color: 'var(--color-ec-text-secondary)',
                                                        cursor: p === 0 ? 'default' : 'pointer',
                                                        opacity: p === 0 ? 0.25 : 1, fontSize: 9, lineHeight: 1,
                                                        fontFamily: 'var(--color-ec-sans)',
                                                    }}
                                                >▲</button>
                                                <button
                                                    type="button"
                                                    disabled={p === (lv.steps!.length - 1)}
                                                    onClick={() => movePaso(idx, p, 1)}
                                                    title="Bajar el paso un puesto"
                                                    style={{
                                                        width: 18, height: 18, padding: 0,
                                                        border: '0.5px solid var(--color-ec-border)', borderRadius: 5,
                                                        background: 'transparent', color: 'var(--color-ec-text-secondary)',
                                                        cursor: p === (lv.steps!.length - 1) ? 'default' : 'pointer',
                                                        opacity: p === (lv.steps!.length - 1) ? 0.25 : 1, fontSize: 9, lineHeight: 1,
                                                        fontFamily: 'var(--color-ec-sans)',
                                                    }}
                                                >▼</button>
                                                <button
                                                    type="button"
                                                    disabled={(lv.steps?.length ?? 0) <= 2}
                                                    onClick={() => removePaso(idx, p)}
                                                    style={{
                                                        marginLeft: 'auto',
                                                        background: 'transparent', border: 'none',
                                                        color: 'var(--color-ec-loss)', cursor: (lv.steps?.length ?? 0) <= 2 ? 'default' : 'pointer',
                                                        fontSize: 11, fontFamily: 'var(--color-ec-sans)', padding: 0,
                                                        opacity: (lv.steps?.length ?? 0) <= 2 ? 0.25 : 1,
                                                    }}
                                                    title="Quitar este paso (mínimo 2)"
                                                >✕</button>
                                            </div>
                                            {/* Cada paso: el MISMO editor de grupos que entrada/salida. */}
                                            <GroupDisplay
                                                group={paso}
                                                onChange={(g) => setPaso(idx, p, g)}
                                                accentColor="amber"
                                                parentTimeframe={config.timeframe}
                                            />
                                        </div>
                                    ))}
                                    <button
                                        type="button"
                                        onClick={() => addPaso(idx)}
                                        style={{
                                            alignSelf: 'flex-start',
                                            backgroundColor: 'transparent',
                                            border: '0.5px dashed var(--color-ec-copper)',
                                            borderRadius: 5,
                                            padding: '4px 10px',
                                            fontSize: 10,
                                            fontWeight: 600,
                                            fontFamily: 'var(--color-ec-sans)',
                                            color: 'var(--color-ec-copper)',
                                            cursor: 'pointer',
                                        }}
                                    >+ Añadir paso</button>
                                    {/* El front avisa; el back blinda con 422. */}
                                    {!nivelPiramideValido(lv) && (
                                        <span style={{ fontFamily: 'var(--color-ec-sans)', fontSize: 10, fontWeight: 600, color: 'var(--color-ec-loss)' }}>
                                            El camino necesita al menos 2 pasos y ninguno vacío — así no se puede guardar.
                                        </span>
                                    )}
                                </div>
                            ) : (
                                /* El MISMO editor de grupos que entrada/salida: AND/OR,
                                   anidados, todos los indicadores y comparadores. */
                                <GroupDisplay
                                    group={lv.root_condition ?? GRUPO_VACIO()}
                                    onChange={(g) => setLevel(idx, { ...lv, root_condition: g })}
                                    accentColor="amber"
                                    parentTimeframe={config.timeframe}
                                />
                            )}
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
                        {' '}Con «SL del lote», cada añadido de ese nivel trae su propio cinturón: al romperse cierra SOLO ese lote (con
                        PnL contra su precio de entrada) y el stop del trade sigue mandando sobre el conjunto; si el nivel no se puede
                        resolver al añadir (p. ej. pivote sin confirmar), el añadido no se ejecuta.
                        {' '}Con «Camino», la condición única se sustituye por una CADENA ordenada: cada paso engancha cuando le toca
                        (aunque los anteriores ya no se cumplan) y la acción se ejecuta al engancharse el último; los pasos cuentan solo
                        desde la entrada, y con más de una «vez» el camino se recorre entero una vez por cada disparo.
                    </span>
                </div>
            )}
        </div>
    );
});
PyramidingBuilder.displayName = "PyramidingBuilder";
