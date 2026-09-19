"use client";

// Paso 5 de «En crudo»: la CUENTA REAL (Jaume, 19-sep-2026). «Volcar mi
// operativa real, lo que gano y pierdo, calcular Kelly ahí y que me dé cuánto
// debo apostar en el siguiente periodo; y en base a esa cantidad distribuir
// los pesos sobre las estrategias según las Kellys del backtest.»
//
// El CSV trae el PnL neto por día (o por trade: se suman). No hace falta saber
// de qué estrategia viene cada trade: la Kelly del TOTAL sale de la cuenta
// real y el reparto entre estrategias sale de las Kellys del backtest (paso 4).

import React, { useMemo, useState } from "react";
import { color, font } from "@/components/ui/tokens";
import { ErrorBox } from "@/components/robustez/shared";
import { kellyCuentaReal, type KellyRealOut, type RawOut } from "@/lib/api_portfolio_lab";
import { Btn, Nota, Num, Row, Sec, Stat, Toggle, colorSerie, control, n, pct, tdNum, tdTxt, thL, thR, usd } from "./hoja";
import type { EscCfg } from "./modelo";

export interface FilaReal { date: string; pnl: number }

/** Lee un CSV (coma, punto y coma o tabulador) y saca fecha + PnL por fila.
 *  Cabeceras que entiende: fecha/date/día; pnl/p&l/neto/net/profit/beneficio/
 *  resultado/realized. Sin cabecera: primera columna fecha, segunda PnL.
 *  Fechas: AAAA-MM-DD o DD/MM/AAAA. Números: «1.234,56» o «1,234.56». */
export function parseCsvReal(texto: string): { filas: FilaReal[]; aviso: string | null } {
  const lineas = texto.split(/\r?\n/).map((l) => l.trim()).filter(Boolean);
  if (!lineas.length) return { filas: [], aviso: null };
  const sep = (lineas[0].match(/;/g) || []).length >= (lineas[0].match(/,/g) || []).length
    ? ((lineas[0].match(/\t/g) || []).length > (lineas[0].match(/;/g) || []).length ? "\t" : ";")
    : ",";
  const celdas = (l: string) => l.split(sep).map((c) => c.trim().replace(/^"|"$/g, ""));
  const cab = celdas(lineas[0]).map((c) => c.toLowerCase());
  const iFecha = cab.findIndex((c) => /fecha|date|d[ií]a/.test(c));
  const iPnl = cab.findIndex((c) => /p&l|pnl|neto|\bnet\b|profit|beneficio|resultado|realized|ganancia/.test(c));
  const conCabecera = iFecha >= 0 || iPnl >= 0;
  const cF = iFecha >= 0 ? iFecha : 0;
  const cP = iPnl >= 0 ? iPnl : 1;
  const numero = (s: string): number => {
    let t = s.replace(/[$€\s]/g, "");
    if (t.includes(".") && t.includes(",")) {
      t = t.lastIndexOf(",") > t.lastIndexOf(".") ? t.replace(/\./g, "").replace(",", ".") : t.replace(/,/g, "");
    } else if (t.includes(",")) {
      t = t.replace(",", ".");
    }
    const v = Number(t);
    return Number.isFinite(v) ? v : NaN;
  };
  const fecha = (s: string): string | null => {
    let m = s.match(/^(\d{4})-(\d{2})-(\d{2})/);
    if (m) return `${m[1]}-${m[2]}-${m[3]}`;
    m = s.match(/^(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})/);
    if (m) {
      let a = Number(m[1]), b = Number(m[2]);
      // DD/MM (español) salvo que el primero no pueda ser un día.
      if (a > 12 && b <= 12) { /* DD/MM */ } else if (b > 12 && a <= 12) { const t = a; a = b; b = t; }
      return `${m[3]}-${String(b).padStart(2, "0")}-${String(a).padStart(2, "0")}`;
    }
    return null;
  };
  const filas: FilaReal[] = [];
  let malas = 0;
  for (const l of lineas.slice(conCabecera ? 1 : 0)) {
    const c = celdas(l);
    const d = fecha(c[cF] ?? "");
    const v = numero(c[cP] ?? "");
    if (!d || !Number.isFinite(v)) { malas += 1; continue; }
    filas.push({ date: d, pnl: v });
  }
  return { filas, aviso: malas ? `${malas} filas sin fecha o sin PnL legibles se han saltado.` : null };
}

export function PasoCuentaReal({ m }: { m: {
  out: RawOut | null; outEsc: RawOut | null; esc: EscCfg; capital: number;
} }) {
  const { outEsc, esc, capital } = m;
  const [csv, setCsv] = useState("");
  const [riskMode, setRiskMode] = useState<"usd" | "pct">("pct");
  const [riskValue, setRiskValue] = useState<number>(1);
  const [capitalInicial, setCapitalInicial] = useState<number>(capital > 0 ? capital : 10000);
  const [capitalSig, setCapitalSig] = useState<number>(capital > 0 ? capital : 10000);
  const [ventana, setVentana] = useState<number>(esc.lookback_days || 90);
  const [mult, setMult] = useState<number>(esc.kelly_mult || 0.5);
  const [capEst, setCapEst] = useState<number>(esc.cap_strategy_pct ?? 2);
  const [capSuma, setCapSuma] = useState<number>(esc.cap_pct ?? 5);
  const [res, setRes] = useState<KellyRealOut | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const parsed = useMemo(() => parseCsvReal(csv), [csv]);
  const hoy = outEsc?.scaling?.today ?? null;
  const estrategias = useMemo(() => (hoy ? hoy.per_strategy.map((p) => ({ name: p.name, kelly_pct: p.kelly_pct ?? 0, basis: p.basis ?? "risk" })) : []), [hoy]);
  const dias = useMemo(() => Array.from(new Set(parsed.filas.map((f) => f.date))).sort(), [parsed]);
  const pnlTotal = parsed.filas.reduce((a, f) => a + f.pnl, 0);

  const onFile = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (!f) return;
    const r = new FileReader();
    r.onload = () => setCsv(String(r.result || ""));
    r.readAsText(f);
  };

  const calcular = async () => {
    if (!parsed.filas.length || running) return;
    setRunning(true); setError(null);
    try {
      const o = await kellyCuentaReal({
        rows: parsed.filas, risk_mode: riskMode, risk_value: riskValue, capital_inicial: capitalInicial,
        kelly_mult: mult, cap_pct: capSuma, cap_strategy_pct: capEst, lookback_days: ventana,
        estrategias, capital_siguiente: capitalSig,
      });
      setRes(o);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setRunning(false);
    }
  };

  return (
    <div>
      <div style={{ display: "grid", gridTemplateColumns: "minmax(380px, 1fr) minmax(0, 1fr)", gap: 14, alignItems: "start" }}>
        <Sec title="Tu cuenta" help={
          <>
            <strong>Qué pegar</strong>: un CSV con una fila por día (o por trade: se suman por día) con la <em>fecha</em> y el
            <em> PnL neto</em> en $. Cabeceras que entiende: fecha/date, pnl/neto/profit/beneficio/resultado. Sin cabecera:
            primera columna fecha, segunda PnL. Fechas AAAA-MM-DD o DD/MM/AAAA; números con coma o punto.
            <br /><br />
            <strong>Riesgo por trade usado</strong>: lo que arriesgabas por operación en ese periodo, para pasar el PnL de
            cada día a R (PnL del día ÷ riesgo por trade). Si ibas con un % del equity, pon el % y el capital con el que
            empezaste; el equity de cada día se reconstruye acumulando el PnL. Sin este dato no hay Kelly: la R es lo
            que la hace comparable con las estrategias.
            <br /><br />
            <strong>Lo que sale</strong>: la Kelly exacta de tu R diaria real (ventana de N días; 0 = toda la historia), ×
            la fracción y topada = el riesgo TOTAL por trade del siguiente periodo. Y ese total repartido entre las
            estrategias del paso 4 en proporción a sus Kellys del backtest (tope por estrategia primero, tope de la
            suma después). No hace falta saber de qué estrategia viene cada trade real.
          </>
        }>
          <textarea
            value={csv}
            onChange={(e) => setCsv(e.target.value)}
            placeholder={"fecha;pnl\n2026-08-03;125,40\n2026-08-04;-80,00\n…"}
            spellCheck={false}
            style={{ ...control, width: "100%", minHeight: 120, fontFamily: font.mono, fontSize: 11, resize: "vertical", padding: 8 }}
          />
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 6, flexWrap: "wrap" }}>
            <input type="file" accept=".csv,.txt,text/csv" onChange={onFile} style={{ fontSize: 11, fontFamily: font.sans, color: color.textSecondary }} />
            <span style={{ fontSize: 10.5, fontFamily: font.sans, color: parsed.filas.length ? color.textSecondary : color.textMuted }}>
              {parsed.filas.length ? `${parsed.filas.length} filas · ${dias.length} días · ${dias[0]} → ${dias[dias.length - 1]} · PnL ${usd(pnlTotal)}` : "pega el CSV o elige el fichero"}
            </span>
            {parsed.aviso && <span style={{ fontSize: 10.5, fontFamily: font.sans, color: color.warning }}>{parsed.aviso}</span>}
          </div>
          <div style={{ marginTop: 10 }}>
            <Row label="Riesgo por trade usado">
              <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                <div style={{ width: 170 }}><Toggle value={riskMode} onChange={setRiskMode} options={[{ value: "pct", label: "% del equity" }, { value: "usd", label: "$ fijos" }]} /></div>
                <div style={{ width: 80 }}><Num value={riskValue} onChange={(v) => setRiskValue(Number(v) || 0)} min={0} step={riskMode === "pct" ? 0.25 : 25} /></div>
                <span style={{ fontSize: 10.5, fontFamily: font.sans, color: color.textMuted }}>{riskMode === "pct" ? "% del equity del día" : "$ por trade"}</span>
                {riskMode === "pct" && (
                  <>
                    <span style={{ fontSize: 10.5, fontFamily: font.sans, color: color.textMuted }}>· capital al empezar</span>
                    <div style={{ width: 100 }}><Num value={capitalInicial} onChange={(v) => setCapitalInicial(Number(v) || 0)} min={0} step={1000} /></div>
                  </>
                )}
              </div>
            </Row>
            <Row label="Ventana">
              <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                <div style={{ width: 70 }}><Num value={ventana} onChange={(v) => setVentana(Math.max(0, Math.round(Number(v) || 0)))} min={0} step={30} /></div>
                <span style={{ fontSize: 10.5, fontFamily: font.sans, color: color.textMuted }}>días (0 = toda la historia)</span>
              </div>
            </Row>
            <Row label="Fracción y topes">
              <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                <div style={{ width: 64 }}><Num value={mult} onChange={(v) => setMult(Math.max(0.01, Number(v) || 0))} min={0.01} max={3} step={0.05} /></div>
                <span style={{ fontSize: 10.5, fontFamily: font.sans, color: color.textMuted }}>× Kelly · por estrategia ≤</span>
                <div style={{ width: 64 }}><Num value={capEst} onChange={(v) => setCapEst(Number(v) || 0)} min={0} step={0.25} /></div>
                <span style={{ fontSize: 10.5, fontFamily: font.sans, color: color.textMuted }}>% · suma ≤</span>
                <div style={{ width: 64 }}><Num value={capSuma} onChange={(v) => setCapSuma(Number(v) || 0)} min={0} step={0.5} /></div>
                <span style={{ fontSize: 10.5, fontFamily: font.sans, color: color.textMuted }}>% (0 = sin tope)</span>
              </div>
            </Row>
            <Row label="Capital siguiente periodo">
              <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                <div style={{ width: 110 }}><Num value={capitalSig} onChange={(v) => setCapitalSig(Number(v) || 0)} min={0} step={1000} /></div>
                <span style={{ fontSize: 10.5, fontFamily: font.sans, color: color.textMuted }}>$ · para los $ por trade</span>
              </div>
            </Row>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 12, padding: "12px 0 4px" }}>
            <Btn primary onClick={calcular} disabled={running || !parsed.filas.length}>{running ? "Calculando…" : "Calcular con mi cuenta"}</Btn>
            <span style={{ fontSize: 10.5, fontFamily: font.sans, color: hoy ? color.textMuted : color.warning }}>
              {hoy ? `reparto por las Kellys del paso 4 (${estrategias.length} estrategias)` : "sin el paso 4 calculado, sale el total pero no el reparto por estrategia"}
            </span>
          </div>
          {error && <div style={{ marginTop: 8 }}><ErrorBox>{error}</ErrorBox></div>}
        </Sec>

        <Sec title="Siguiente periodo según tu cuenta" help="La Kelly exacta de tu R diaria real (la f que maximiza la media de log(1 + f·R)), su aproximación μ/σ² al lado, lo que pide tras la fracción y lo aplicado tras los topes: el riesgo TOTAL por trade. Debajo, cada estrategia con su Kelly del backtest, su proporción en la suma y lo que le toca en % y en $ del capital que has puesto. «Peor día» en R: lo que costaría ese día con el riesgo elegido es peor día × riesgo.">
          {!res ? (
            <Nota>Pega tu CSV y pulsa <strong>Calcular con mi cuenta</strong>.</Nota>
          ) : (
            <>
              <div style={{ display: "flex", flexWrap: "wrap", gap: "2px 12px", padding: "4px 0" }}>
                <Stat label="Días" value={n(res.dias_con_operaciones, 0)} sub={`con operaciones · ventana ${res.desde ?? "—"} → ${res.hasta ?? "—"} (${n(res.dias_ventana, 0)} días)`} />
                <Stat label="R por día" value={`${n(res.r_media_dia, 2)} R`} sub={`peor ${n(res.r_peor_dia, 1)} R · mejor ${n(res.r_mejor_dia, 1)} R · ${n(res.r_total_ventana, 0)} R en la ventana`} />
                <Stat label="Kelly real" value={res.kelly_raw_pct == null ? "—" : pct(res.kelly_raw_pct, 2)} sub={res.kelly_raw_pct == null ? (res.nota || "sin muestra") : `× ${n(res.kelly_mult, 2)} = ${pct(res.total_pedido_pct, 2)}${res.kelly_quad_pct != null ? ` · aprox. μ/σ² ${pct(res.kelly_quad_pct, 1)}` : ""}`} />
                <Stat big label="Riesgo total por trade" value={res.total_pct == null ? "—" : pct(res.total_pct, 2)} sub={res.total_pct == null ? "" : `${usd(res.total_usd)} sobre ${usd(res.capital_siguiente)} · si entran todas a la vez${res.capped ? " · manda el tope de la suma" : res.capped_strategy ? " · manda el tope por estrategia" : ""}`} tone={res.total_pct == null ? undefined : "profit"} />
              </div>
              {res.nota && <Nota tone="warning">{res.nota}</Nota>}
              {res.per_strategy.length > 0 && (
                <table style={{ width: "100%", borderCollapse: "collapse", marginTop: 6 }}>
                  <thead>
                    <tr>
                      <th style={thL}>Estrategia</th>
                      <th style={thR}>Kelly backtest</th>
                      <th style={thR}>Proporción</th>
                      <th style={{ ...thR, color: color.copper }}>% por trade</th>
                      <th style={thR}>$ por trade</th>
                    </tr>
                  </thead>
                  <tbody>
                    {res.per_strategy.map((p, i) => (
                      <tr key={p.name + i}>
                        <td style={tdTxt}><span style={{ display: "inline-flex", alignItems: "center", gap: 8 }}><span style={{ width: 10, height: 10, background: colorSerie(i), display: "inline-block" }} />{p.name}</span></td>
                        <td style={tdNum}>{pct(p.kelly_pct, 2)}</td>
                        <td style={{ ...tdNum, color: color.textMuted }}>{pct(p.share * 100, 0)}</td>
                        <td style={{ ...tdNum, color: color.textHigh, fontWeight: 600 }}>{p.risk_pct == null ? "—" : pct(p.risk_pct, 2)}<span style={{ fontSize: 9.5, color: color.textMuted, fontWeight: 400, marginLeft: 4 }}>{p.basis === "capital" ? "posición" : "riesgo"}</span></td>
                        <td style={{ ...tdNum, color: color.textHigh }}>{p.risk_usd == null ? "—" : usd(p.risk_usd)}</td>
                      </tr>
                    ))}
                    <tr>
                      <td style={{ ...tdTxt, borderTop: `1px solid ${color.border}`, color: color.copper, fontWeight: 600 }}>Suma</td>
                      <td style={{ ...tdNum, borderTop: `1px solid ${color.border}` }} />
                      <td style={{ ...tdNum, borderTop: `1px solid ${color.border}` }}>100 %</td>
                      <td style={{ ...tdNum, borderTop: `1px solid ${color.border}`, color: color.copper, fontWeight: 600 }}>{res.total_pct == null ? "—" : pct(res.total_pct, 2)}</td>
                      <td style={{ ...tdNum, borderTop: `1px solid ${color.border}`, color: color.copper }}>{res.total_usd == null ? "—" : usd(res.total_usd)}</td>
                    </tr>
                  </tbody>
                </table>
              )}
              <p style={{ margin: "8px 0 0", fontSize: 10.5, fontFamily: font.sans, color: color.textMuted, lineHeight: 1.5 }}>
                El total sale de TU cuenta (fills, slippage y locates reales incluidos); el reparto, de lo que dice el backtest de cada estrategia en su ventana. Si una estrategia sale a 0 en el backtest, no recibe nada. La unidad de cada una es la de su backtest: «riesgo» (al stop) o «posición» (% del capital metido).
              </p>
            </>
          )}
        </Sec>
      </div>
    </div>
  );
}
