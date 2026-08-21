"use client";

// Control en tiempo real (F3): tu operativa REAL como fuente de decision.
//
//  1. Importas tus reports del broker (CSV de transacciones tipo DAS: se
//     detecta la cabecera "Trade Date"/"Net Amt" y se agrega el PnL por dia;
//     tambien acepta lineas simples "fecha, pnl").
//  2. Sobre TU curva: metricas, drawdown, y el ESCALADO que elijas (compound,
//     fix ratio, kelly con su fraccion, o por drawdown) te dice el size de hoy.
//  3. Sobre las estrategias normalizadas que marques: el reparto de pesos de
//     HOY (iguales, HRP, momentum, EV o drawdown).
//
// Estetica sobria a proposito: filas finas y datos, sin tarjetas gordas.

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { color, font, radius } from "@/components/ui/tokens";
import {
  DataTable,
  ErrorBox,
  Field,
  NumberInput,
  RunButton,
  SectionHead,
  Segmented,
  Select,
} from "@/components/robustez/shared";
import { fmt } from "@/components/robustez/shared";
import { Help } from "@/components/robustez/help";
import { DrawdownRibbon } from "@/components/robustez/charts/BasicCharts";
import { InlineStats } from "./StatSheet";
import { SERIES_PALETTE } from "./charts/PortfolioCurves";
import { OverlayRealSim } from "./charts/OverlayRealSim";
import {
  clearRealPnl,
  getRealPnl,
  listPortfolioStrategies,
  runPortfolioScaling,
  runRealControl,
  runWeightsNow,
  saveRealPnl,
  type PortfolioStrategy,
  type RealControlOut,
  type ScalingOut,
  type WeightModel,
  type WeightsNowOut,
} from "@/lib/api_portfolio_lab";

/* ── Parser de importacion: broker (DAS) o lineas simples ────────── */

/** Divide una linea CSV respetando comillas: un importe como "1,234.56" es UN
 *  campo, no dos. Sin esto las columnas se desplazaban y el dia sumaba mal. */
function splitCsv(line: string): string[] {
  const out: string[] = [];
  let cur = "";
  let inQ = false;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (ch === '"') {
      if (inQ && line[i + 1] === '"') {
        cur += '"';
        i++;
      } else inQ = !inQ;
    } else if (ch === "," && !inQ) {
      out.push(cur);
      cur = "";
    } else cur += ch;
  }
  out.push(cur);
  return out;
}

/** parseFloat tolerante al separador de miles: "1,234.56" -> 1234.56 */
function toNum(raw: string | undefined): number {
  if (raw == null) return NaN;
  return parseFloat(raw.replace(/["\s]/g, "").replace(/,(?=\d{3}(\D|$))/g, ""));
}

function parseImport(text: string): {
  rows: Array<{ date: string; pnl: number }>;
  source: "broker" | "simple";
  skipped: number;
} {
  const lines = text.split(/\r?\n/).filter((l) => l.trim());
  const headIdx = lines.findIndex((l) => l.includes("Trade Date") && l.includes("Net Amt"));
  if (headIdx >= 0) {
    const cols = splitCsv(lines[headIdx]).map((c) => c.trim());
    const iDate = cols.indexOf("Trade Date");
    const iNet = cols.indexOf("Net Amt");
    const iType = cols.indexOf("Entry Type");
    const byDay = new Map<string, number>();
    let skipped = 0;
    for (const line of lines.slice(headIdx + 1)) {
      const parts = splitCsv(line);
      if (parts.length < cols.length - 1) {
        skipped++;
        continue;
      }
      // Filas que no son operaciones (depositos, intereses...) se ignoran a
      // proposito: no son "descartadas", simplemente no son trades.
      if (iType >= 0 && parts[iType]?.trim() !== "TRD") continue;
      const d = (parts[iDate] || "").trim().slice(0, 10);
      const net = toNum(parts[iNet]);
      if (!/^\d{4}-\d{2}-\d{2}$/.test(d) || !Number.isFinite(net)) {
        skipped++;
        continue;
      }
      byDay.set(d, (byDay.get(d) || 0) + net);
    }
    // Convenio del broker: compras positivas, ventas negativas
    // -> el PnL del dia es MENOS la suma de importes netos.
    const rows = Array.from(byDay.entries())
      .map(([date, sum]) => ({ date, pnl: Math.round(-sum * 100) / 100 }))
      .sort((a, b) => a.date.localeCompare(b.date));
    return { rows, source: "broker", skipped };
  }
  const rows: Array<{ date: string; pnl: number }> = [];
  let skipped = 0;
  for (const line of lines) {
    const parts = line.trim().split(/[;\t]|,(?!\d{3}(\D|$))/).map((x) => x.trim());
    if (parts.length < 2) {
      skipped++;
      continue;
    }
    const d = parts[0].slice(0, 10);
    const v = toNum(parts[1]);
    if (/^\d{4}-\d{2}-\d{2}$/.test(d) && Number.isFinite(v)) rows.push({ date: d, pnl: v });
    else skipped++;
  }
  return { rows, source: "simple", skipped };
}

const SCALE_LABELS: Record<string, string> = {
  compound: "% lineal del capital (compound)",
  fixed_ratio: "Fix ratio (Ryan Jones)",
  kelly: "Kelly sobre tu curva",
  dd: "Por drawdown de tu curva",
};

const W_LABELS: Record<string, string> = {
  equal: "Iguales",
  hrp: "HRP (López de Prado)",
  momentum: "Momentum",
  ev: "EV normalizado",
  dd: "Sensible al drawdown",
};

export function ControlTiempoReal() {
  const [real, setReal] = useState<Array<{ date: string; pnl: number }>>([]);
  const [csv, setCsv] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  // parametros de la cuenta real
  const [capital, setCapital] = useState(10000);
  const [baseRisk, setBaseRisk] = useState(100);

  // escalado sobre la curva real
  const [model, setModel] = useState<"compound" | "fixed_ratio" | "kelly" | "dd">("kelly");
  const [pct, setPct] = useState(1);
  const [delta, setDelta] = useState(500);
  const [kellyMult, setKellyMult] = useState(0.5);
  const [ddFloor, setDdFloor] = useState(0.25);
  const [lookback, setLookback] = useState(90);
  const [cap, setCap] = useState(0);
  const [ctl, setCtl] = useState<RealControlOut | null>(null);
  const [ctlRunning, setCtlRunning] = useState(false);

  // superposicion del portfolio simulado sobre el tramo real
  const [ovModel, setOvModel] = useState<"fixed" | "percent" | "fixed_ratio" | "kelly" | "combinatoria">("fixed");
  const [ovBase, setOvBase] = useState(100);
  const [ovPct, setOvPct] = useState(1);
  const [ovDelta, setOvDelta] = useState(500);
  const [ovKmult, setOvKmult] = useState(0.5);
  const [ovSlip, setOvSlip] = useState(0);
  const [ovLoc, setOvLoc] = useState(0);
  const [ovFees, setOvFees] = useState(0);
  const [ovOut, setOvOut] = useState<ScalingOut | null>(null);
  const [ovRunning, setOvRunning] = useState(false);

  // pesos de ahora
  const [strategies, setStrategies] = useState<PortfolioStrategy[]>([]);
  const [checked, setChecked] = useState<Record<string, boolean>>({});
  const [wModel, setWModel] = useState<WeightModel>("hrp");
  const [wLookback, setWLookback] = useState(90);
  const [wOut, setWOut] = useState<WeightsNowOut | null>(null);
  const [wRunning, setWRunning] = useState(false);

  const loadRows = useCallback(async () => {
    try {
      setReal((await getRealPnl()).rows);
    } catch {
      /* el error de red general ya lo enseña la pestaña */
    }
  }, []);

  useEffect(() => {
    loadRows();
    listPortfolioStrategies()
      .then((list) => {
        const withRun = list.filter((s) => s.run);
        setStrategies(withRun);
        setChecked((prev) => {
          const next: Record<string, boolean> = {};
          for (const s of withRun) next[s.id] = prev[s.id] ?? s.buckets.includes("portfolio");
          return next;
        });
      })
      .catch(() => {});
  }, [loadRows]);

  // El capital inicial entra en TODOS los cálculos ya hechos (curva real,
  // recomendación de size y superposición). Si cambia, lo anterior deja de
  // ser válido: se limpia en vez de mostrar cifras de dos configuraciones
  // mezcladas (la «Divergencia» llegaba a saltar el importe entero).
  useEffect(() => {
    setCtl(null);
    setOvOut(null);
  }, [capital]);

  const doImport = async (text: string) => {
    setMsg(null);
    setError(null);
    const { rows, source, skipped } = parseImport(text);
    if (!rows.length) {
      setMsg("No he reconocido filas. Acepto el CSV de transacciones del bróker o líneas «2026-08-21, 154.20».");
      return;
    }
    try {
      const r = await saveRealPnl(rows);
      const aviso = skipped > 0 ? ` · ${skipped} línea${skipped === 1 ? "" : "s"} ilegible${skipped === 1 ? "" : "s"} descartada${skipped === 1 ? "" : "s"}` : "";
      setMsg(
        (source === "broker"
          ? `Report del bróker importado: ${rows.length} días agregados (${r.total} en total).`
          : `Guardadas ${r.saved} filas (${r.total} en total).`) + aviso,
      );
      setCsv("");
      loadRows();
      // Los resultados calculados con la curva ANTERIOR ya no valen.
      setCtl(null);
      setOvOut(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo guardar");
    }
  };

  const runControl = async () => {
    setCtlRunning(true);
    setError(null);
    try {
      setCtl(
        await runRealControl({
          initial_capital: capital,
          base_risk: baseRisk,
          model,
          pct,
          delta,
          kelly_mult: kellyMult,
          dd_floor: ddFloor,
          lookback_days: lookback,
          cap_global_pct: cap,
        }),
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo calcular");
    } finally {
      setCtlRunning(false);
    }
  };

  const runOverlay = async () => {
    const ids = strategies.filter((s) => checked[s.id]).map((s) => s.id);
    if (!ids.length || real.length < 2 || ovRunning) return;
    setOvRunning(true);
    setError(null);
    try {
      // El portfolio simulado "empieza a la vez" que tu curva: mismo tramo y
      // mismo capital inicial, con el MODELO de escalado que elijas (pesos
      // iguales, rebalanceo diario) y los costes que le pongas.
      setOvOut(
        await runPortfolioScaling({
          strategy_ids: ids,
          init_cash: capital,
          fees: ovFees,
          fee_type: "FLAT",
          slippage_pct: ovSlip,
          locates_cost: ovLoc,
          monthly_expenses: 0,
          start_date: real[0].date,
          end_date: real[real.length - 1].date,
          rebalance: "D",
          lookback_days: 90,
          cap_global_pct: 0,
          scaling: { model: ovModel, base_risk: ovBase, pct: ovPct, delta: ovDelta, kelly_mult: ovKmult, threshold_equity: capital * 2 },
          weighting: { model: "equal", floor: 0.1, cap_strat_pct: 0 },
        }),
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo simular el portfolio del tramo");
    } finally {
      setOvRunning(false);
    }
  };

  const runWeights = async () => {
    const ids = strategies.filter((s) => checked[s.id]).map((s) => s.id);
    if (!ids.length) return;
    setWRunning(true);
    setError(null);
    try {
      setWOut(await runWeightsNow({ strategy_ids: ids, lookback_days: wLookback, model: wModel, floor: 0.1 }));
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudieron calcular los pesos");
    } finally {
      setWRunning(false);
    }
  };

  const m = ctl?.metrics;
  const rec = ctl?.recommendation;
  const eqPoints = useMemo(
    () =>
      ctl
        ? ctl.dates.map((d, i) => ({ time: Math.floor(Date.parse(`${d}T00:00:00Z`) / 1000), value: ctl.equity[i] }))
        : [],
    [ctl],
  );

  return (
    <div>
      <SectionHead
        title="Control en tiempo real"
        hint="Tu operativa real como fuente de decisión: importa tus reports, mira tu curva y tu drawdown, y deja que el modelo que elijas te diga el size de hoy — y el reparto de pesos entre tus estrategias normalizadas."
      />
      {error && (
        <div style={{ marginBottom: 12 }}>
          <ErrorBox>{error}</ErrorBox>
        </div>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "minmax(280px, 340px) minmax(0, 1fr)", gap: 18, alignItems: "start" }}>
        {/* ── Configuracion ── */}
        <div style={{ display: "flex", flexDirection: "column", gap: 13 }}>
          <div style={{ fontSize: 10.5, letterSpacing: "0.1em", textTransform: "uppercase", color: color.textHigh, fontFamily: font.sans, fontWeight: 600, display: "flex", alignItems: "center", gap: 6 }}>
            Importar operativa
            <Help title="Importar operativa" width={360}>
              Acepta dos formatos: el <strong>CSV de transacciones de tu bróker</strong> (el
              «Transactions» de DAS: se detecta solo, se filtran los fills y se agrega el PnL por
              día) o <strong>líneas simples</strong> «2026-08-21, 154.20». Puedes importar varios
              ficheros: los días se van acumulando, y re-importar un día ya existente lo
              sobrescribe (no lo duplica). Todo queda guardado entre sesiones.
            </Help>
          </div>
          <input
            ref={fileRef}
            type="file"
            accept=".csv,.txt"
            style={{ display: "none" }}
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (!f) return;
              const reader = new FileReader();
              reader.onload = () => doImport(String(reader.result || ""));
              reader.readAsText(f);
              e.target.value = "";
            }}
          />
          <button
            type="button"
            onClick={() => fileRef.current?.click()}
            style={{ padding: "7px 12px", fontSize: 11.5, fontFamily: font.sans, border: `0.5px solid ${color.border}`, borderRadius: radius.sm, background: "transparent", color: color.textSecondary, cursor: "pointer", textAlign: "left" }}
          >
            Subir CSV del bróker (Transactions)…
          </button>
          <textarea
            value={csv}
            onChange={(e) => setCsv(e.target.value)}
            placeholder={"…o pega aquí el contenido del CSV,\no líneas simples:\n2026-08-21, 154.20"}
            rows={4}
            style={{ background: color.bgBase, border: `0.5px solid ${color.border}`, borderRadius: radius.sm, color: color.textHigh, fontFamily: font.mono, fontSize: 11, padding: "8px 10px", resize: "vertical", outline: "none" }}
          />
          <div style={{ display: "flex", gap: 8 }}>
            <div style={{ flex: 1 }}>
              <RunButton onClick={() => doImport(csv)} disabled={!csv.trim()} label="Importar" />
            </div>
            {real.length > 0 && (
              <button
                type="button"
                onClick={async () => {
                  await clearRealPnl();
                  setReal([]);
                  setCtl(null);
                  setOvOut(null);
                  setMsg("Borrado.");
                }}
                style={{ padding: "6px 12px", fontSize: 11, fontFamily: font.sans, border: `0.5px solid ${color.border}`, borderRadius: radius.sm, background: "transparent", color: color.textSecondary, cursor: "pointer" }}
              >
                Borrar
              </button>
            )}
          </div>
          {msg && <span style={{ fontSize: 10.5, fontFamily: font.sans, color: color.textMuted }}>{msg}</span>}
          <span style={{ fontSize: 10.5, fontFamily: font.sans, color: color.textMuted }}>
            {real.length} días importados{real.length ? ` (${real[0].date} → ${real[real.length - 1].date})` : ""}
          </span>

          <div style={{ borderTop: `0.5px solid ${color.border}`, paddingTop: 12, fontSize: 10.5, letterSpacing: "0.1em", textTransform: "uppercase", color: color.textHigh, fontFamily: font.sans, fontWeight: 600, display: "flex", alignItems: "center", gap: 6 }}>
            Escalado sobre tu curva
            <Help title="Escalado sobre tu curva" width={360}>
              El modelo lee TU historial importado (no un backtest) y te dice cuánto arriesgar por
              trade hoy. Kelly estima media÷varianza de tus R diarias (PnL del día ÷ tu riesgo base)
              en la ventana; fix ratio escala por beneficio acumulado; drawdown te reduce el size
              cuanto más hundida esté tu curva; % lineal es la referencia simple.
            </Help>
          </div>
          <Field label="Capital inicial de la cuenta ($)" hint="con el que empezó el historial importado">
            <NumberInput value={capital} onChange={setCapital} min={100} step={500} />
          </Field>
          <Field
            label="Tu riesgo base actual ($/trade)"
            hint="lo que arriesgas HOY: es tu referencia de comparación (el ×N del resultado) y la unidad de R para Kelly y fix ratio. OJO: los modelos % y Kelly recomiendan sobre el CAPITAL, no sobre esta cifra"
          >
            <NumberInput value={baseRisk} onChange={setBaseRisk} min={1} step={25} />
          </Field>
          <Field label="Modelo">
            <Select
              value={model}
              onChange={setModel}
              options={Object.entries(SCALE_LABELS).map(([value, label]) => ({ value: value as typeof model, label }))}
            />
          </Field>
          {model === "compound" && (
            <Field label="% del capital por trade" hint="la referencia simple: arriesgar siempre este % del capital vivo">
              <NumberInput value={pct} onChange={setPct} min={0.1} step={0.25} />
            </Field>
          )}
          {model === "fixed_ratio" && (
            <Field label="Delta ($)" hint="beneficio que te exige para subir un escalón de size; menos del ~10% de tu cuenta = agresivo, más del 25% = prudente">
              <NumberInput value={delta} onChange={setDelta} min={50} step={100} />
            </Field>
          )}
          {model === "kelly" && (
            <>
              <Field label="Fracción de Kelly">
                <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                  <Segmented
                    value={String(kellyMult) as "0.25" | "0.5" | "1"}
                    onChange={(v) => setKellyMult(parseFloat(v))}
                    options={[
                      { value: "0.25", label: "¼" },
                      { value: "0.5", label: "½" },
                      { value: "1", label: "Óptima" },
                    ]}
                  />
                  <div style={{ width: 80 }}>
                    <NumberInput value={kellyMult} onChange={setKellyMult} min={0.05} max={1} step={0.05} />
                  </div>
                  <Help title="Fracción de Kelly" width={340}>
                    Kelly calcula el % de capital que habría maximizado el crecimiento de TU curva en
                    la ventana (media ÷ varianza de tus R diarias). Como toda Kelly sobre historial,
                    sobreapuesta: usa fracciones (½ o ¼), hay un techo interno del 25%, y tu tope
                    corta por encima de todo. Si no hay muestra (~20 sesiones) o el edge reciente es
                    negativo, te lo dice en vez de inventarse un número.
                  </Help>
                </div>
              </Field>
              <Field label="Ventana (días)" hint="cuánto historial tuyo mira Kelly. Mínimo ~20 SESIONES de mercado (≈30 días civiles); con menos, cae al % base y te avisa">
                <NumberInput value={lookback} onChange={setLookback} min={20} step={10} />
              </Field>
            </>
          )}
          {model === "dd" && (
            <Field label="Suelo del multiplicador" hint="en tu peor drawdown, el size no baja de esta fracción de tu riesgo base">
              <NumberInput value={ddFloor} onChange={setDdFloor} min={0} max={1} step={0.05} />
            </Field>
          )}
          <Field label="Tope MÁXIMO (% del capital · 0 = sin tope)" hint="techo duro: si el modelo pide más, se aplica tu tope y el exceso no se despliega">
            <NumberInput value={cap} onChange={setCap} min={0} step={0.5} />
          </Field>
          <RunButton onClick={runControl} loading={ctlRunning} disabled={real.length < 2} label="Calcular mi size" loadingLabel="Calculando…" />

          <div style={{ borderTop: `0.5px solid ${color.border}`, paddingTop: 12, fontSize: 10.5, letterSpacing: "0.1em", textTransform: "uppercase", color: color.textHigh, fontFamily: font.sans, fontWeight: 600, display: "flex", alignItems: "center", gap: 6 }}>
            Pesos del portfolio hoy
            <Help title="Pesos de hoy" width={340}>
              Sobre las estrategias normalizadas que marques, con el historial de la ventana elegida:
              el método te dice qué % del riesgo destinar HOY a cada una. Independiente de tu curva
              real — la señal sale de las estrategias, tu curva solo decide el size global.
            </Help>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
            {strategies.map((s) => (
              <label key={s.id} style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 11.5, fontFamily: font.sans, color: color.textPrimary, cursor: "pointer" }}>
                <input
                  type="checkbox"
                  checked={!!checked[s.id]}
                  onChange={(e) => setChecked((c) => ({ ...c, [s.id]: e.target.checked }))}
                  style={{ accentColor: "var(--color-ec-copper)" }}
                />
                <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{s.name}</span>
                {s.normalization && !s.normalization.normalized && (
                  <span style={{ fontSize: 9, color: color.warning, flexShrink: 0 }}>ámbar</span>
                )}
              </label>
            ))}
          </div>
          <Field label="Método">
            <Select
              value={wModel}
              onChange={setWModel}
              options={Object.entries(W_LABELS).map(([value, label]) => ({ value: value as WeightModel, label }))}
            />
          </Field>
          <Field label="Ventana (días)" hint="HRP, momentum, EV y drawdown necesitan ~20 SESIONES de mercado en la ventana (≈30 días civiles). Con menos, caen a pesos iguales y te lo dicen">
            <NumberInput value={wLookback} onChange={setWLookback} min={30} step={30} />
          </Field>
          <RunButton
            onClick={runWeights}
            loading={wRunning}
            disabled={!strategies.some((s) => checked[s.id])}
            label="Calcular pesos de hoy"
            loadingLabel="Calculando…"
          />
        </div>

        {/* ── Resultados ── */}
        <div style={{ display: "flex", flexDirection: "column", gap: 20, minWidth: 0 }}>
          {rec && (
            <div style={{ borderLeft: `2px solid ${color.copper}`, background: color.bgSurface, borderRadius: `0 ${radius.md} ${radius.md} 0`, padding: "10px 14px", display: "flex", flexWrap: "wrap", alignItems: "baseline", gap: "4px 22px" }}>
              <span style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 10, letterSpacing: "0.1em", textTransform: "uppercase", color: color.copper, fontFamily: font.sans }}>
                Size de hoy · {SCALE_LABELS[rec.model]}
                <Help title="Cómo leerlo" width={330}>
                  Lo que el modelo te dice que arriesgues <strong>por trade, hoy</strong>, dado tu
                  historial: en $ y como % de tu capital actual. El «×N sobre tu riesgo base» es la
                  traducción práctica: ×1,20 = sube el size un 20%; ×0,80 = bájalo un 20%; ×1,00 =
                  quédate como estás. Si algo lo recortó (techo de kelly o tu tope), la nota en
                  ámbar dice cuánto pedía en crudo.
                </Help>
              </span>
              <span style={{ fontSize: 19, fontFamily: font.mono, color: color.textHigh }}>{fmt.money(rec.x, 0)}/trade</span>
              <span style={{ fontSize: 12, fontFamily: font.mono, color: color.textSecondary }}>= {fmt.pct(rec.x_pct)} del capital</span>
              {rec.vs_base != null && (
                <span style={{ fontSize: 12, fontFamily: font.mono, color: rec.vs_base >= 1 ? color.profit : color.loss }}>
                  ×{rec.vs_base.toFixed(2)} sobre tus {fmt.money(baseRisk, 0)} actuales{" "}
                  <span style={{ fontFamily: font.sans, fontSize: 11 }}>
                    ({rec.vs_base >= 1.02 ? `súbete un ${((rec.vs_base - 1) * 100).toFixed(0)}%` : rec.vs_base <= 0.98 ? `bájate un ${((1 - rec.vs_base) * 100).toFixed(0)}%` : "quédate como estás"})
                  </span>
                </span>
              )}
              {rec.note && <span style={{ fontSize: 10.5, fontFamily: font.sans, color: color.warning, width: "100%" }}>{rec.note}</span>}
            </div>
          )}

          {m && (
            <InlineStats
              items={[
                { label: "PnL total", value: fmt.money(m.total_pnl, 0), tone: m.total_pnl >= 0 ? color.profit : color.loss },
                { label: "Retorno", value: fmt.pct(m.return_pct), tone: m.return_pct >= 0 ? color.profit : color.loss, help: "Sobre el capital inicial que has puesto en la configuración." },
                { label: "DD máx", value: fmt.pct(m.max_dd_pct), tone: color.loss, help: "Tu peor caída desde un máximo de la cuenta, en todo el historial importado." },
                { label: "DD actual", value: fmt.pct(m.dd_now_pct), tone: m.dd_now_pct < -0.01 ? color.loss : color.textMuted, help: "A cuánto estás HOY de tu último máximo. 0% = en máximos." },
                { label: "Días verdes", value: fmt.pct(m.win_days_pct, 1), help: "Porcentaje de sesiones con PnL positivo." },
                { label: "Media/día", value: fmt.money(m.avg_day, 0) },
                { label: "Mejor / peor", value: `${fmt.money(m.best_day, 0)} / ${fmt.money(m.worst_day, 0)}` },
                { label: "Sharpe diario", value: fmt.num(m.sharpe_d), help: "Media diaria dividida por su ruido, anualizada. Con pocas sesiones es MUY inestable: no le hagas caso hasta tener 30-40 días." },
                { label: "Sesiones", value: fmt.int(m.n_days) },
              ]}
            />
          )}

          {ctl ? (
            <DrawdownRibbon equity={eqPoints} />
          ) : (
            <div style={{ fontSize: 12, fontFamily: font.sans, color: color.textMuted, padding: "18px 4px", lineHeight: 1.6 }}>
              Importa tu operativa y pulsa <strong>Calcular mi size</strong>: verás tu curva con su
              drawdown, tus métricas y la recomendación del modelo.
            </div>
          )}

          {real.length > 0 && (
            <DataTable
              columns={["Fecha", "PnL"]}
              rows={real.slice(-6).map((r) => [r.date, <span key="p" style={{ color: r.pnl >= 0 ? color.profit : color.loss }}>{fmt.money(r.pnl, 2)}</span>])}
            />
          )}

          {/* ── Portfolio simulado superpuesto sobre tu tramo ── */}
          {real.length >= 2 && (
            <div>
              <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 10, letterSpacing: "0.1em", textTransform: "uppercase", color: color.copper, fontFamily: font.sans, marginBottom: 8 }}>
                Tu curva vs portfolio simulado
                <Help title="Real vs simulado" width={360}>
                  Corre el portfolio de las estrategias marcadas (las del bloque de pesos) sobre{" "}
                  <strong>exactamente tu tramo</strong> ({real[0].date} → {real[real.length - 1].date})
                  y con tu mismo capital inicial, aplicándole los costes que pongas aquí. Superpone
                  equity y drawdown: si tu curva se separa de la simulada, ahí está la divergencia
                  que investigar (ejecución, disciplina, costes reales…).
                </Help>
              </div>
              <div style={{ display: "flex", alignItems: "flex-end", gap: 10, flexWrap: "wrap", marginBottom: 10 }}>
                <Field label="modelo de escalado">
                  <div style={{ width: 190 }}>
                    <Select
                      value={ovModel}
                      onChange={setOvModel}
                      options={[
                        { value: "fixed", label: "$ fijo por trade" },
                        { value: "percent", label: "% lineal del capital" },
                        { value: "fixed_ratio", label: "Fix ratio" },
                        { value: "kelly", label: "Kelly" },
                        { value: "combinatoria", label: "Combinatoria" },
                      ]}
                    />
                  </div>
                </Field>
                {(ovModel === "fixed" || ovModel === "fixed_ratio" || ovModel === "combinatoria") && (
                  <Field label="base $/trade">
                    <div style={{ width: 80 }}>
                      <NumberInput value={ovBase} onChange={setOvBase} min={1} step={25} />
                    </div>
                  </Field>
                )}
                {ovModel === "percent" && (
                  <Field label="% capital">
                    <div style={{ width: 70 }}>
                      <NumberInput value={ovPct} onChange={setOvPct} min={0.1} step={0.25} />
                    </div>
                  </Field>
                )}
                {(ovModel === "fixed_ratio" || ovModel === "combinatoria") && (
                  <Field label="delta $">
                    <div style={{ width: 80 }}>
                      <NumberInput value={ovDelta} onChange={setOvDelta} min={50} step={100} />
                    </div>
                  </Field>
                )}
                {(ovModel === "kelly" || ovModel === "combinatoria") && (
                  <Field label="fracción kelly">
                    <div style={{ width: 70 }}>
                      <NumberInput value={ovKmult} onChange={setOvKmult} min={0.05} max={1} step={0.05} />
                    </div>
                  </Field>
                )}
                <Field label="comisión $/lado">
                  <div style={{ width: 80 }}>
                    <NumberInput value={ovFees} onChange={setOvFees} min={0} step={0.05} />
                  </div>
                </Field>
                <Field label="slippage %">
                  <div style={{ width: 80 }}>
                    <NumberInput value={ovSlip} onChange={setOvSlip} min={0} step={0.01} />
                  </div>
                </Field>
                <Field label="locates $/100">
                  <div style={{ width: 80 }}>
                    <NumberInput value={ovLoc} onChange={setOvLoc} min={0} step={0.5} />
                  </div>
                </Field>
                <div style={{ width: 130 }}>
                  <RunButton onClick={runOverlay} loading={ovRunning} disabled={!strategies.some((s) => checked[s.id])} label="Superponer" loadingLabel="Simulando…" />
                </div>
              </div>
              {ovModel === "kelly" && (
                <p style={{ margin: "-4px 0 10px", fontSize: 10, fontFamily: font.sans, color: color.textMuted }}>
                  Ojo: Kelly necesita ~20 sesiones de historial DENTRO del tramo; en tramos cortos
                  caerá al % base y te lo dirá.
                </p>
              )}
              {ovOut ? (
                <>
                  <OverlayRealSim
                    realDates={real.map((r) => r.date)}
                    realEquity={real.reduce<number[]>((acc, r) => {
                      acc.push((acc.length ? acc[acc.length - 1] : capital) + r.pnl);
                      return acc;
                    }, [])}
                    simDates={ovOut.calendar}
                    simEquity={ovOut.equity}
                  />
                  <div style={{ marginTop: 8 }}>
                    <InlineStats
                      items={[
                        { label: "Final real", value: fmt.money(capital + real.reduce((a, r) => a + r.pnl, 0), 0), tone: real.reduce((a, r) => a + r.pnl, 0) >= 0 ? color.profit : color.loss },
                        { label: "Final simulado", value: fmt.money(ovOut.metrics.final_equity, 0), tone: ovOut.metrics.final_equity >= capital ? color.profit : color.loss },
                        {
                          label: "Divergencia",
                          value: fmt.money(capital + real.reduce((a, r) => a + r.pnl, 0) - ovOut.metrics.final_equity, 0),
                          help: "Real menos simulado, en $. Positiva = lo estás haciendo mejor que el modelo; negativa = peor (ejecución, disciplina, costes reales…).",
                        },
                        { label: "DD máx simulado", value: fmt.pct(ovOut.metrics.max_drawdown_pct), tone: color.loss },
                      ]}
                    />
                  </div>
                </>
              ) : (
                <p style={{ margin: 0, fontSize: 11, fontFamily: font.sans, color: color.textMuted }}>
                  Marca las estrategias en el bloque de pesos y pulsa <strong>Superponer</strong>.
                </p>
              )}
            </div>
          )}

          {wOut && (
            <div>
              <div style={{ fontSize: 10, letterSpacing: "0.1em", textTransform: "uppercase", color: color.copper, fontFamily: font.sans, marginBottom: 8 }}>
                Pesos de hoy · {W_LABELS[wModel]} · {wOut.window.from} → {wOut.window.to} ({wOut.window.sessions} sesiones)
              </div>
              {wOut.fallback && (
                <div style={{ fontSize: 10.5, fontFamily: font.sans, color: color.warning, marginBottom: 6 }}>
                  Sin muestra suficiente en la ventana: pesos IGUALES a la fuerza. Amplía la ventana.
                </div>
              )}
              <div style={{ display: "flex", flexDirection: "column", gap: 4, maxWidth: 640 }}>
                {wOut.strategies.map((s, i) => {
                  const w = (wOut.weights[i] || 0) * 100;
                  return (
                    <div key={s.strategy_id} style={{ display: "flex", alignItems: "center", gap: 10 }}>
                      <span style={{ fontSize: 11, fontFamily: font.sans, color: color.textPrimary, width: 220, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", flexShrink: 0 }}>
                        {s.name}
                      </span>
                      <div style={{ flex: 1, height: 7, background: color.bgElevated, borderRadius: radius.pill, overflow: "hidden" }}>
                        <div style={{ width: `${Math.min(100, w)}%`, height: "100%", background: SERIES_PALETTE[i % SERIES_PALETTE.length], opacity: 0.8 }} />
                      </div>
                      <span style={{ fontSize: 12, fontFamily: font.mono, color: color.textHigh, width: 54, textAlign: "right", flexShrink: 0 }}>
                        {w.toFixed(1)}%
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
