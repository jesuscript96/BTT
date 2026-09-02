"use client";
// TEMPORAL — verificación de render del panel de alarmas. Se borra tras la prueba.
import { AlarmsPanel } from "@/components/screener/AlarmsPanel";
export default function Preview() {
  return (
    <div style={{ padding: 24, maxWidth: 620, margin: "0 auto",
                  background: "var(--color-ec-bg-base)", minHeight: "100vh" }}>
      <AlarmsPanel />
    </div>
  );
}
