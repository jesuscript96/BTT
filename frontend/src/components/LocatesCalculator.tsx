"use client";

import React, { useMemo, useState } from "react";

/**
 * Calculadora de locates — determinista, inline en el panel de detalle del Screener.
 * Fuera de Edgie (decisión de producto). El Entry se pre-rellena con el precio ya
 * cargado del ticker; el resto (riesgo, stop, coste del paquete) los pone el usuario.
 *
 * Fórmula estándar (los locates se compran SIEMPRE en paquetes de 100):
 *   stop_distance = SL - Entry            (o Entry × SL% si el stop viene en %)
 *   shares        = Riesgo / stop_distance   (sin redondear: 37.5 es válido)
 *   paquetes      = ceil(shares / 100)       (nunca hacia abajo)
 *   coste_total   = paquetes × coste_paquete
 *   fade_$        = coste_total / shares
 *   fade_%        = fade_$ / Entry × 100  → % de fade solo para cubrir el locate
 *
 * El componente se remonta por ticker (key={selectedTicker} en el padre), así que
 * el Entry inicial se refresca al cambiar de ticker.
 */

const inputStyle: React.CSSProperties = {
    width: "100%",
    height: 30,
    backgroundColor: "var(--color-ec-bg-base)",
    border: "1px solid var(--color-ec-border)",
    borderRadius: 5,
    padding: "0 8px",
    color: "var(--color-ec-text-high)",
    fontSize: 12,
    fontFamily: "ui-monospace, monospace",
    outline: "none",
};

const labelStyle: React.CSSProperties = {
    fontSize: 9,
    fontWeight: 600,
    color: "var(--color-ec-text-secondary)",
    marginBottom: 3,
    display: "block",
};

const num = (s: string): number | null => {
    const v = parseFloat(s.replace(",", "."));
    return Number.isFinite(v) ? v : null;
};

const Field = ({ label, value, onChange, placeholder }: {
    label: string; value: string; onChange: (v: string) => void; placeholder?: string;
}) => (
    <div>
        <span style={labelStyle}>{label}</span>
        <input
            type="text"
            inputMode="decimal"
            value={value}
            placeholder={placeholder}
            onChange={(e) => onChange(e.target.value)}
            style={inputStyle}
        />
    </div>
);

export function LocatesCalculator({ initialEntry }: { initialEntry?: number | null }) {
    const [riesgo, setRiesgo] = useState("");
    const [entry, setEntry] = useState(initialEntry != null ? String(initialEntry) : "");
    const [slMode, setSlMode] = useState<"pct" | "abs">("pct");
    const [sl, setSl] = useState("");
    const [costePaquete, setCostePaquete] = useState("");

    const result = useMemo(() => {
        const r = num(riesgo);
        const e = num(entry);
        const s = num(sl);
        const c = num(costePaquete);
        if (r == null || e == null || s == null || c == null) return null;
        if (r <= 0 || e <= 0 || c < 0) return { error: "Riesgo y entry deben ser positivos." };

        const stopDistance = slMode === "pct" ? e * (s / 100) : s - e;
        if (stopDistance <= 0) {
            return { error: slMode === "pct" ? "El % de stop debe ser mayor que 0." : "El stop debe estar por encima del entry (short)." };
        }

        const shares = r / stopDistance;               // sin redondear
        const paquetes = Math.ceil(shares / 100);      // siempre hacia arriba
        const costeTotal = paquetes * c;
        const fadeUsd = costeTotal / shares;
        const fadePct = (fadeUsd / e) * 100;

        return { stopDistance, shares, paquetes, costeTotal, fadeUsd, fadePct };
    }, [riesgo, entry, sl, slMode, costePaquete]);

    const row = (label: string, value: string) => (
        <div style={{ display: "flex", justifyContent: "space-between", padding: "4px 0", borderBottom: "1px solid color-mix(in srgb, var(--color-ec-border) 40%, transparent)" }}>
            <span style={{ fontSize: 10, color: "var(--color-ec-text-secondary)" }}>{label}</span>
            <span style={{ fontSize: 11, fontWeight: 600, color: "var(--color-ec-text-high)", fontFamily: "ui-monospace, monospace" }}>{value}</span>
        </div>
    );

    return (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
                <Field label="Riesgo ($)" value={riesgo} onChange={setRiesgo} placeholder="60" />
                <Field label="Entry ($)" value={entry} onChange={setEntry} placeholder="4.00" />
                <div>
                    <span style={labelStyle}>
                        Stop
                        <span
                            onClick={() => setSlMode(slMode === "pct" ? "abs" : "pct")}
                            style={{ marginLeft: 5, color: "var(--color-ec-copper)", cursor: "pointer", fontWeight: 700 }}
                            title="Cambiar entre % arriba y precio absoluto"
                        >
                            {slMode === "pct" ? "% arriba" : "$ abs"}
                        </span>
                    </span>
                    <input
                        type="text"
                        inputMode="decimal"
                        value={sl}
                        placeholder={slMode === "pct" ? "40" : "5.60"}
                        onChange={(e) => setSl(e.target.value)}
                        style={inputStyle}
                    />
                </div>
                <Field label="Coste paq. 100 ($)" value={costePaquete} onChange={setCostePaquete} placeholder="15" />
            </div>

            {result && "error" in result && (
                <div style={{ fontSize: 10, color: "var(--color-ec-loss)" }}>{result.error}</div>
            )}

            {result && !("error" in result) && (
                <div style={{ display: "flex", flexDirection: "column" }}>
                    {row("Shares", result.shares.toFixed(1))}
                    {row("Paquetes", `${result.paquetes} (${result.paquetes * 100} locates)`)}
                    {row("Coste total", `$${result.costeTotal.toFixed(2)}`)}
                    <div style={{
                        marginTop: 8, padding: "8px 10px", borderRadius: 5,
                        border: "1px solid var(--color-ec-copper)",
                        backgroundColor: "color-mix(in srgb, var(--color-ec-copper) 8%, transparent)",
                        fontSize: 11, color: "var(--color-ec-text-high)", lineHeight: 1.4,
                    }}>
                        Necesitas un <strong>{result.fadePct.toFixed(2)}% de fade</strong> solo para cubrir el locate.
                    </div>
                </div>
            )}

            <span style={{ fontSize: 8, color: "var(--color-ec-text-muted)" }}>
                Locates en paquetes de 100; el nº de paquetes se redondea hacia arriba.
            </span>
        </div>
    );
}
