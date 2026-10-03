"use client";

import { useState } from "react";
import { Cpu } from "lucide-react";

import CuadroMandos from "@/components/bot-alerts/CuadroMandos";
import EjecucionDas from "@/components/bot-alerts/EjecucionDas";
import { color, font } from "@/components/ui";

type Pestana = "alertas" | "ejecucion";

export default function BotAlertasPage() {
  const [pestana, setPestana] = useState<Pestana>("alertas");

  const elegir = (p: Pestana) => setPestana(p);

  const tab = (p: Pestana, texto: string) => (
    <button
      onClick={() => elegir(p)}
      style={{
        fontFamily: font.sans, fontSize: 10.5, fontWeight: 600, letterSpacing: "0.08em",
        textTransform: "uppercase", padding: "6px 14px", cursor: "pointer", background: "transparent",
        border: "none", borderBottom: `2px solid ${pestana === p ? color.copper : "transparent"}`,
        color: pestana === p ? color.textHigh : color.textMuted,
      }}
    >{texto}</button>
  );

  return (
    <>
      <div style={{
        maxWidth: 1680, margin: "0 auto", padding: "14px 26px 0", display: "flex", gap: 6,
        borderBottom: `0.5px solid ${color.border}`,
      }}>
        {tab("alertas", "Alertas")}
        {tab("ejecucion", "Ejecución")}
      </div>
      {/* Las alertas siguen MONTADAS al cambiar de pestaña: el sonido y la conexión en vivo no se cortan. */}
      <div style={{ display: pestana === "alertas" ? "block" : "none" }}>
        <CuadroMandos />
      </div>
      {pestana === "ejecucion" && (
        <div style={{ padding: "20px 26px 60px", maxWidth: 1680, margin: "0 auto" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 14 }}>
            <Cpu style={{ width: 19, height: 19, color: color.copper, strokeWidth: 1.5 }} />
            <h1 style={{ fontSize: 24, fontFamily: font.serif, color: color.textHigh, margin: 0, fontWeight: 400 }}>
              Bot de ejecución (DAS)
            </h1>
          </div>
          <EjecucionDas />
        </div>
      )}
    </>
  );
}
