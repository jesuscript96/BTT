"use client";

import React, { useMemo, useState } from "react";
import { X } from "lucide-react";

/**
 * Calculadora de locates — determinista, fuera de Edgie (decisión de producto).
 *
 * Fórmula estándar (los locates se compran SIEMPRE en paquetes de 100):
 *   stop_distance = SL - Entry            (o Entry × SL% si el stop viene en %)
 *   shares        = Riesgo / stop_distance   (sin redondear: 37.5 es válido)
 *   paquetes      = ceil(shares / 100)       (nunca hacia abajo)
 *   coste_total   = paquetes × coste_paquete
 *   fade_$        = coste_total / shares
 *   fade_%        = fade_$ / Entry × 100  → % de fade solo para cubrir el locate
 */

const inputStyle: React.CSSProperties = {
    width: "100%",
    height: 34,
    backgroundColor: "var(--color-ec-bg-base)",
    border: "1px solid var(--color-ec-border)",
    borderRadius: 6,
    padding: "0 10px",
    color: "var(--color-ec-text-high)",
    fontSize: 13,
    fontFamily: "ui-monospace, monospace",
    outline: "none",
};

const labelStyle: React.CSSProperties = {
    fontSize: 10,
    fontWeight: 600,
    color: "var(--color-ec-text-secondary)",
    marginBottom: 4,
    display: "block",
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

const num = (s: string): number | null => {
    const v = parseFloat(s.replace(",", "."));
    return Number.isFinite(v) ? v : null;
};

export function LocatesCalculator({ onClose }: { onClose: () => void }) {
    const [riesgo, setRiesgo] = useState("");
    const [entry, setEntry] = useState("");
    const [slMode, setSlMode] = useState<"pct" | "abs">("pct");
    const [sl, setSl] = useState("");
    const [costePaquete, setCostePaquete] = useState("");

    const result = useMemo(() => {
        const r = num(riesgo);
        const e = num(entry);
        const s = num(sl);
        const c = num(costePaquete);
        if (r == null || e == null || s == null || c == null) return null;
        if (r <= 0 || e <= 0 || c < 0) return { error: "Revisa los datos: riesgo y entry deben ser positivos." };

        const stopDistance = slMode === "pct" ? e * (s / 100) : s - e;
        if (stopDistance <= 0) {
            return { error: slMode === "pct" ? "El % de stop debe ser mayor que 0." : "En un short el stop debe estar por encima del entry." };
        }

        const shares = r / stopDistance;               // sin redondear
        const paquetes = Math.ceil(shares / 100);      // siempre hacia arriba
        const costeTotal = paquetes * c;
        const fadeUsd = costeTotal / shares;
        const fadePct = (fadeUsd / e) * 100;

        return { stopDistance, shares, paquetes, costeTotal, fadeUsd, fadePct };
    }, [riesgo, entry, sl, slMode, costePaquete]);

    const row = (label: string, value: string) => (
        <div style={{ display: "flex", justifyContent: "space-between", padding: "5px 0", borderBottom: "1px solid color-mix(in srgb, var(--color-ec-border) 40%, transparent)" }}>
            <span style={{ fontSize: 11, color: "var(--color-ec-text-secondary)" }}>{label}</span>
            <span style={{ fontSize: 12, fontWeight: 600, color: "var(--color-ec-text-high)", fontFamily: "ui-monospace, monospace" }}>{value}</span>
        </div>
    );

    return (
        <div
            onClick={onClose}
            style={{
                position: "fixed", inset: 0, zIndex: 200,
                backgroundColor: "rgba(0,0,0,0.55)",
                display: "flex", alignItems: "center", justifyContent: "center",
            }}
        >
            <div
                onClick={(e) => e.stopPropagation()}
                style={{
                    width: 360, maxWidth: "calc(100vw - 32px)",
                    backgroundColor: "var(--color-ec-bg-surface)",
                    border: "1px solid var(--color-ec-border)",
                    borderRadius: 10, padding: 18,
                    display: "flex", flexDirection: "column", gap: 12,
                    fontFamily: "'General Sans', sans-serif",
                }}
            >
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                    <span style={{ fontSize: 9, fontWeight: 700, color: "var(--color-ec-copper)", textTransform: "uppercase", letterSpacing: "1.5px" }}>
                        Calculadora de locates
                    </span>
                    <button onClick={onClose} style={{ background: "none", border: "none", color: "var(--color-ec-text-secondary)", cursor: "pointer", display: "flex", padding: 2 }}>
                        <X size={15} />
                    </button>
                </div>

                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
                    <Field label="Riesgo ($)" value={riesgo} onChange={setRiesgo} placeholder="60" />
                    <Field label="Entry ($)" value={entry} onChange={setEntry} placeholder="4.00" />
                    <div>
                        <span style={labelStyle}>
                            Stop loss
                            <span
                                onClick={() => setSlMode(slMode === "pct" ? "abs" : "pct")}
                                style={{ marginLeft: 6, color: "var(--color-ec-copper)", cursor: "pointer", fontWeight: 700 }}
                                title="Cambiar entre % y precio absoluto"
                            >
                                {slMode === "pct" ? "% arriba" : "$ absoluto"}
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
                    <Field label="Coste paquete 100 ($)" value={costePaquete} onChange={setCostePaquete} placeholder="15" />
                </div>

                {result && "error" in result && (
                    <div style={{ fontSize: 11, color: "var(--color-ec-loss)" }}>{result.error}</div>
                )}

                {result && !("error" in result) && (
                    <div style={{ display: "flex", flexDirection: "column" }}>
                        {row("Stop distance", `$${result.stopDistance.toFixed(2)}`)}
                        {row("Shares", result.shares.toFixed(1))}
                        {row("Paquetes de locates", `${result.paquetes} (${result.paquetes * 100} locates)`)}
                        {row("Coste total locates", `$${result.costeTotal.toFixed(2)}`)}
                        {row("Coste por share", `$${result.fadeUsd.toFixed(3)}`)}
                        <div style={{
                            marginTop: 10, padding: "10px 12px", borderRadius: 6,
                            border: "1px solid var(--color-ec-copper)",
                            backgroundColor: "color-mix(in srgb, var(--color-ec-copper) 8%, transparent)",
                            fontSize: 12, color: "var(--color-ec-text-high)", lineHeight: 1.45,
                        }}>
                            Necesitas un <strong>{result.fadePct.toFixed(2)}% de fade</strong> solo para cubrir el locate.
                        </div>
                    </div>
                )}

                <span style={{ fontSize: 9, color: "var(--color-ec-text-muted)" }}>
                    Los locates se compran siempre en paquetes de 100; el número de paquetes se redondea hacia arriba.
                </span>
            </div>
        </div>
    );
}
