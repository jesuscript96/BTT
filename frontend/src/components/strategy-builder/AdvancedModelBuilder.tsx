"use client";

import React from "react";
import { IndicatorType, IndicatorConfig } from "@/types/strategy";
import {
    INDICATOR_CATEGORIES, INDICATOR_LABELS, IndicatorParams,
    getDefaultParamsForIndicator,
} from "./ConditionBuilder";

/** Configuración del bloque «Modelos avanzados». Viaja tal cual al backend. */
export interface AdvancedModelConfig {
    active: boolean;
    mode: "filter" | "standalone";
    train_from: string;
    train_to: string;
    test_from: string;
    test_to: string;
    threshold: number;
    features: IndicatorConfig[];
    hmm_enabled: boolean;
    hmm_states: number;
    compare_without_model: boolean;
}

export const initialAdvancedModel: AdvancedModelConfig = {
    active: false,
    mode: "filter",
    train_from: "",
    train_to: "",
    test_from: "",
    test_to: "",
    // 0,5 es "el modelo cree que va a salir bien". Subirlo es lo que hace la
    // estrategia más selectiva; es la palanca principal de este bloque.
    threshold: 0.5,
    features: [],
    hmm_enabled: false,
    hmm_states: 3,
    compare_without_model: false,
};

interface Props {
    config: AdvancedModelConfig;
    onChange: (c: AdvancedModelConfig) => void;
}

const ETIQUETA: React.CSSProperties = {
    fontFamily: 'var(--color-ec-sans)', fontSize: 10, fontWeight: 700,
    color: 'var(--color-ec-text-muted)', textTransform: 'uppercase',
    letterSpacing: '0.06em',
};

const CAMPO: React.CSSProperties = {
    backgroundColor: 'var(--color-ec-bg-sidebar)',
    border: '0.5px solid var(--color-ec-border)',
    borderRadius: 5, padding: '5px 10px',
    fontSize: 'var(--ec-fs-select)', fontWeight: 500,
    color: 'var(--color-ec-text-primary)',
    fontFamily: 'var(--color-ec-sans)', outline: 'none',
};

/** Los indicadores que se pueden usar como feature: los mismos del constructor
 *  de condiciones. Se excluyen los de patrón (triángulos), que no son un número
 *  con el que un árbol pueda partir. */
const FEATURES_DISPONIBLES: IndicatorType[] = Object.values(INDICATOR_CATEGORIES)
    .flat()
    .filter((n) => ![
        IndicatorType.TRIANGLE_ASCENDING,
        IndicatorType.TRIANGLE_DESCENDING,
        IndicatorType.TRIANGLE_SYMMETRIC,
    ].includes(n));

export const AdvancedModelBuilder = React.memo(({ config, onChange }: Props) => {
    const active = config.active === true;
    const set = (patch: Partial<AdvancedModelConfig>) => onChange({ ...config, ...patch });

    const addFeature = () => {
        const usadas = new Set(config.features.map((f) => f.name));
        const libre = FEATURES_DISPONIBLES.find((n) => !usadas.has(n)) ?? IndicatorType.RSI;
        set({ features: [...config.features, { name: libre, ...getDefaultParamsForIndicator(libre) } as IndicatorConfig] });
    };
    const setFeature = (i: number, v: IndicatorConfig) =>
        set({ features: config.features.map((f, j) => (j === i ? v : f)) });
    const delFeature = (i: number) =>
        set({ features: config.features.filter((_, j) => j !== i) });

    const solapan = !!(config.train_to && config.test_from && config.train_to >= config.test_from);

    return (
        <div style={{
            display: 'flex', flexDirection: 'column', gap: 16, padding: '20px 0',
            backgroundColor: 'transparent',
            borderBottom: '0.5px solid var(--color-ec-border)',
        }}>
            {/* Cabecera — mismo patrón que Piramidación / Stop Loss Fijo */}
            <div style={{
                display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                paddingBottom: active ? 12 : 0,
                borderBottom: active ? '0.5px solid var(--color-ec-border)' : 'none',
            }}>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <div style={{ width: 3, height: 14, borderRadius: 1, backgroundColor: 'var(--color-ec-copper)' }} />
                        <h2 style={{
                            fontFamily: 'var(--color-ec-sans)', fontSize: 13, fontWeight: 700,
                            textTransform: 'uppercase', letterSpacing: '0.08em',
                            color: 'var(--color-ec-text-high)', margin: 0,
                        }}>Modelos avanzados</h2>
                    </div>
                    <span style={{
                        fontFamily: 'var(--color-ec-sans)', fontSize: 10, fontWeight: 400,
                        color: 'var(--color-ec-text-muted)', marginTop: 2,
                    }}>Entrena un modelo en un periodo y mide el resultado en otro</span>
                </div>
                <div className="flex items-center gap-2">
                    <span style={{ ...ETIQUETA, letterSpacing: 'normal' }}>{active ? 'ON' : 'OFF'}</span>
                    <div
                        className={`w-8 h-4 rounded-full relative cursor-pointer transition-colors ${active ? 'bg-ec-copper/70' : 'bg-muted'}`}
                        onClick={() => set({ active: !active })}
                    >
                        <div className={`absolute top-0.5 w-3 h-3 rounded-full bg-white transition-all shadow-sm ${active ? 'left-4.5' : 'left-0.5'}`}></div>
                    </div>
                </div>
            </div>

            {active && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }} className="animate-in fade-in duration-200">

                    {/* El aviso que evita el malentendido más probable */}
                    <div style={{
                        padding: '8px 10px', borderRadius: 5,
                        border: '0.5px solid var(--color-ec-copper)',
                        backgroundColor: 'color-mix(in srgb, var(--color-ec-copper) 8%, transparent)',
                        fontFamily: 'var(--color-ec-sans)', fontSize: 10, lineHeight: 1.45,
                        color: 'var(--color-ec-text-primary)',
                    }}>
                        Este bloque usa <strong>sus propias fechas</strong>, no el deslizador IS/OOS
                        del panel. Deja ese deslizador al <strong>100&nbsp;% IS</strong> o los dos
                        repartos se pisarán. Lo que verás en el gráfico y en las métricas es
                        <strong> solo el periodo de prueba</strong>: el entrenamiento corre por detrás.
                    </div>

                    {/* Modo */}
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
                        <span style={ETIQUETA}>Qué se aplica</span>
                        <select
                            value={config.mode}
                            onChange={(e) => set({ mode: e.target.value as "filter" | "standalone" })}
                            style={{ ...CAMPO, width: '100%', cursor: 'pointer' }}
                        >
                            <option value="filter">XGBoost sobre esta estrategia (filtra sus entradas)</option>
                            <option value="standalone">HMM + features + XGBoost como estrategia (el modelo pone las entradas)</option>
                        </select>
                        {config.mode === "standalone" && (
                            <span style={{ fontSize: 10, color: 'var(--color-ec-text-muted)', fontFamily: 'var(--color-ec-sans)', lineHeight: 1.4 }}>
                                Las entradas las decide el modelo, así que hay que tener
                                <strong> apagadas la lógica de entrada, la de salida, la piramidación
                                y el swing</strong> — si no, el backtest se detiene y te dice cuál
                                sobra. <strong>Necesita un stop configurado</strong>: es lo que se usa
                                para decidir si una entrada fue buena. Se sale por tu stop, tu take
                                profit o tu hora, como en cualquier otra estrategia.
                            </span>
                        )}
                    </div>

                    {/* Periodos */}
                    <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
                        <div style={{ flex: '1 1 200px', display: 'flex', flexDirection: 'column', gap: 5 }}>
                            <span style={ETIQUETA}>Entrenamiento</span>
                            <div style={{ display: 'flex', gap: 6 }}>
                                <input type="date" value={config.train_from} style={{ ...CAMPO, flex: 1 }}
                                    onChange={(e) => set({ train_from: e.target.value })} />
                                <input type="date" value={config.train_to} style={{ ...CAMPO, flex: 1 }}
                                    onChange={(e) => set({ train_to: e.target.value })} />
                            </div>
                        </div>
                        <div style={{ flex: '1 1 200px', display: 'flex', flexDirection: 'column', gap: 5 }}>
                            <span style={ETIQUETA}>Prueba (lo que verás)</span>
                            <div style={{ display: 'flex', gap: 6 }}>
                                <input type="date" value={config.test_from} style={{ ...CAMPO, flex: 1 }}
                                    onChange={(e) => set({ test_from: e.target.value })} />
                                <input type="date" value={config.test_to} style={{ ...CAMPO, flex: 1 }}
                                    onChange={(e) => set({ test_to: e.target.value })} />
                            </div>
                        </div>
                    </div>
                    {solapan && (
                        <span style={{ fontSize: 10, color: '#ef4444', fontFamily: 'var(--color-ec-sans)' }}>
                            El entrenamiento se solapa con la prueba. Si el modelo entrena con días
                            que luego se le miden, el resultado no significa nada.
                        </span>
                    )}

                    {/* Umbral */}
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
                        <span style={ETIQUETA}>Umbral de confianza — {config.threshold.toFixed(2)}</span>
                        <input
                            type="range" min={0} max={1} step={0.01} value={config.threshold}
                            onChange={(e) => set({ threshold: Number(e.target.value) })}
                            style={{ width: '100%', accentColor: 'var(--color-ec-copper)' }}
                        />
                        <span style={{ fontSize: 10, color: 'var(--color-ec-text-muted)', fontFamily: 'var(--color-ec-sans)', lineHeight: 1.4 }}>
                            Solo entra si el modelo da al menos esta probabilidad de que la operación
                            salga bien. <strong>Es la palanca de «operar poco y fino»</strong>: 0,50
                            apenas filtra; 0,75 deja pasar bastante menos; 0,85 muy pocas.
                        </span>
                    </div>

                    {/* Features */}
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                        <span style={ETIQUETA}>Qué mira el modelo</span>
                        <span style={{ fontSize: 10, color: 'var(--color-ec-text-muted)', fontFamily: 'var(--color-ec-sans)', lineHeight: 1.4 }}>
                            Se eligen <strong>indicadores, no rangos</strong>: el modelo busca solo
                            los cortes («RSI por encima de 68 con volumen alto»), y encuentra
                            combinaciones que a mano no escribirías. Los que son un nivel de precio
                            (VWAP, medias, máximos) entran como <strong>distancia en&nbsp;%</strong>,
                            para que valgan igual en una acción de 2&nbsp;$ que en una de 200.
                        </span>
                        {config.features.map((f, i) => (
                            <div key={i} style={{ display: 'flex', gap: 6, alignItems: 'center', width: '100%' }}>
                                <select
                                    value={f.name}
                                    onChange={(e) => {
                                        const n = e.target.value as IndicatorType;
                                        setFeature(i, { name: n, ...getDefaultParamsForIndicator(n) } as IndicatorConfig);
                                    }}
                                    style={{ ...CAMPO, flex: '1 1 150px', minWidth: 130, cursor: 'pointer' }}
                                >
                                    {FEATURES_DISPONIBLES.map((n) => (
                                        <option key={n} value={n}>{INDICATOR_LABELS[n] || n}</option>
                                    ))}
                                </select>
                                <div style={{ flex: '1 1 160px' }}>
                                    <IndicatorParams value={f} onChange={(v) => setFeature(i, v)} hideOffset />
                                </div>
                                <button type="button" onClick={() => delFeature(i)}
                                    title="Quitar esta feature"
                                    style={{ ...CAMPO, cursor: 'pointer', padding: '5px 9px', color: 'var(--color-ec-text-muted)' }}>×</button>
                            </div>
                        ))}
                        <button type="button" onClick={addFeature}
                            style={{ ...CAMPO, cursor: 'pointer', alignSelf: 'flex-start', fontWeight: 600 }}>
                            + Añadir indicador
                        </button>
                    </div>

                    {/* HMM */}
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                        <label style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer' }}>
                            <input type="checkbox" checked={config.hmm_enabled}
                                onChange={(e) => set({ hmm_enabled: e.target.checked })} />
                            <span style={ETIQUETA}>Añadir estados de mercado (HMM)</span>
                        </label>
                        <span style={{ fontSize: 10, color: 'var(--color-ec-text-muted)', fontFamily: 'var(--color-ec-sans)', lineHeight: 1.4 }}>
                            Busca por su cuenta <strong>{config.hmm_states} estados</strong> en el
                            movimiento del precio (uno tranquilo, uno de subida fuerte, uno de caída)
                            y le pasa al modelo en cuál cree que está cada vela. Él no sabe cómo se
                            llaman: solo encuentra los grupos, y luego te decimos cuál es cuál.
                            Se calcula <strong>solo con el pasado</strong> de cada vela.
                        </span>
                        {config.hmm_enabled && (
                            <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                                <span style={{ fontSize: 10, color: 'var(--color-ec-text-muted)', fontFamily: 'var(--color-ec-sans)' }}>Estados:</span>
                                <input type="number" min={2} max={6} value={config.hmm_states}
                                    onChange={(e) => set({ hmm_states: Math.max(2, Math.min(6, Number(e.target.value) || 3)) })}
                                    style={{ ...CAMPO, width: 70 }} />
                            </div>
                        )}
                    </div>

                    {/* Comparación opcional */}
                    <label style={{ display: 'flex', alignItems: 'flex-start', gap: 8, cursor: 'pointer' }}>
                        <input type="checkbox" checked={config.compare_without_model}
                            onChange={(e) => set({ compare_without_model: e.target.checked })}
                            style={{ marginTop: 2 }} />
                        <span style={{ fontSize: 10, color: 'var(--color-ec-text-muted)', fontFamily: 'var(--color-ec-sans)', lineHeight: 1.4 }}>
                            Comparar contra la estrategia <strong>sin modelo</strong> en el mismo
                            periodo. Útil para saber si el modelo aporta algo — pero
                            <strong> cuesta un backtest entero más</strong> de espera. El número de
                            señales que veta ya sale sin activar esto.
                        </span>
                    </label>
                </div>
            )}
        </div>
    );
});
AdvancedModelBuilder.displayName = "AdvancedModelBuilder";
