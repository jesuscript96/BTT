"use client";

// Paso 5 de «En crudo»: la CUENTA REAL (Jaume, 19/20-sep-2026). «Volcar mi
// operativa real, calcular Kelly ahí (la normal y corriente, a la fracción que
// digamos) y que me diga, con un tope, el % que debo destinar al día
// siguiente; y justo debajo el reparto por estrategia de lo simulado en el
// paso 4, ponderado a ese Kelly real.»
//
// El CSV es el export de DAS («Transactions», una fila por fill) o uno
// sencillo con fecha y PnL. El backend lo lee: por simbolo-dia saca el PnL neto
// y el valor de la posicion, y con eso la R de cada operacion sin necesitar
// stops (retorno sobre la posicion). No hace falta saber de que estrategia
// viene cada trade: el total sale de la cuenta real y el reparto, de las
// Kellys del backtest (paso 4).

import React, { useMemo, useState } from "react";
import { color, font } from "@/components/ui/tokens";
import { ErrorBox } from "@/components/robustez/shared";
import { kellyCuentaReal, type KellyRealOut, type RawBrakeIn, type RawOut } from "@/lib/api_portfolio_lab";
import { Btn, Nota, Num, Row, Sec, Stat, Toggle, colorSerie, control, n, pct, tdNum, tdTxt, thL, thR, usd } from "./hoja";

export function PasoCuentaReal({ m }: { m: {
  out: RawOut | null; capital: number;
  /** Los pesos con los que se reparte el total real: los % del paso 1 (o el reparto B). */
  pesos: Array<{ name: string; kelly_pct: number; basis: "risk" | "capital" }>;
  origenPesos: string;
  /** El freno por caida del paso 4 (null = sin freno): se aplica a la curva REAL del CSV. */
  brake: RawBrakeIn | null;
} }) {
  const { capital, pesos, origenPesos, brake } = m;
  const [csv, setCsv] = useState("");
  // Fichero elegido (20-sep, Jaume: «meterle el csv o excel en archivo»). Un
  // CSV/TXT se lee aquí y va como texto (se ve en la caja); un Excel va en
  // base64 y lo lee el backend (openpyxl).
  const [fichero, setFichero] = useState<{ name: string; size: number; b64: string | null } | null>(null);
  const [arrastrando, setArrastrando] = useState(false);
  const [riskMode, setRiskMode] = useState<"notional" | "pct" | "usd">("notional");
  const [riskValue, setRiskValue] = useState<number>(1);
  const [capitalInicial, setCapitalInicial] = useState<number>(capital > 0 ? capital : 10000);
  const [capitalSig, setCapitalSig] = useState<number>(capital > 0 ? capital : 10000);
  const [ventana, setVentana] = useState<number>(0);
  const [base, setBase] = useState<"clasica" | "exacta">("clasica");
  const [mult, setMult] = useState<number>(0.5);
  const [capSuma, setCapSuma] = useState<number>(10);
  const [capEst, setCapEst] = useState<number>(0);
  const [res, setRes] = useState<KellyRealOut | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const estrategias = useMemo(() => pesos.filter((p) => p.kelly_pct > 0), [pesos]);
  const hoy = estrategias.length > 0;
  const lineas = csv.trim() ? csv.trim().split(/\r?\n/).length : 0;
  const esDas = /symbol/i.test(csv.slice(0, 400)) && /net amt/i.test(csv.slice(0, 400));

  const cargarFichero = (f: File | undefined | null) => {
    if (!f) return;
    setRes(null); setError(null);
    const ext = (f.name.split(".").pop() || "").toLowerCase();
    if (ext === "xlsx" || ext === "xlsm" || ext === "xls") {
      const r = new FileReader();
      r.onload = () => {
        const dataUrl = String(r.result || "");
        const b64 = dataUrl.includes(",") ? dataUrl.slice(dataUrl.indexOf(",") + 1) : dataUrl;
        setCsv("");
        setFichero({ name: f.name, size: f.size, b64 });
      };
      r.readAsDataURL(f);
      return;
    }
    const r = new FileReader();
    r.onload = () => {
      setCsv(String(r.result || ""));
      setFichero({ name: f.name, size: f.size, b64: null });
    };
    r.readAsText(f);
  };
  const onFile = (e: React.ChangeEvent<HTMLInputElement>) => {
    cargarFichero(e.target.files?.[0]);
    e.target.value = "";
  };
  const quitarFichero = () => { setFichero(null); setCsv(""); setRes(null); };
  const hayEntrada = !!(fichero?.b64) || !!csv.trim();

  const calcular = async () => {
    if (!hayEntrada || running) return;
    setRunning(true); setError(null);
    try {
      const o = await kellyCuentaReal({
        csv_text: fichero?.b64 ? undefined : csv,
        file_b64: fichero?.b64 ?? undefined,
        filename: fichero?.b64 ? fichero.name : undefined,
        risk_mode: riskMode, risk_value: riskMode === "notional" ? 1 : riskValue, capital_inicial: capitalInicial,
        kelly_mult: mult, cap_pct: capSuma, cap_strategy_pct: capEst, lookback_days: ventana, kelly_base: base,
        estrategias, capital_siguiente: capitalSig, brake,
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
            <strong>Qué meter</strong>: el fichero del export de DAS («Transactions»: una fila por fill, con Trade Date,
            Side, Symbol, Qty, Price, comisiones y Net Amt) en .csv o en Excel (.xlsx), o un CSV sencillo con
            <em>fecha</em> y <em>PnL neto</em> por día o por operación. También vale pegar el contenido. Con el de DAS, cada operación es un símbolo-día: PnL = ventas − compras (con las
            tasas dentro) y valor de la posición = lo mayor de lo comprado y lo vendido.
            <br /><br />
            <strong>Unidad de la R</strong>: «posición» = PnL ÷ valor de la posición de cada operación (no hace falta
            stop; es lo que trae DAS y la misma unidad que el crudo cuando la estrategia va por capital); «% del
            equity» o «$ fijos» = el riesgo por trade que usabas, si operabas por stop.
            <br /><br />
            <strong>Kelly</strong>: «clásica» = p − q/b por operación (la de toda la vida); «exacta» = la que maximiza el
            crecimiento de la R diaria. × la fracción, y topada = el riesgo TOTAL por trade del siguiente periodo. Debajo,
            ese total repartido entre las estrategias del paso 4 en proporción a sus Kellys del backtest (tope por
            estrategia opcional). No hace falta saber de qué estrategia viene cada trade real.
          </>
        }>
          {/* El fichero (CSV o Excel) es la entrada: elegir o arrastrar. */}
          <div
            onDragOver={(e) => { e.preventDefault(); setArrastrando(true); }}
            onDragLeave={() => setArrastrando(false)}
            onDrop={(e) => { e.preventDefault(); setArrastrando(false); cargarFichero(e.dataTransfer.files?.[0]); }}
            style={{
              border: `1px dashed ${arrastrando ? color.copper : color.border}`, background: arrastrando ? "rgba(184, 115, 51, 0.06)" : color.bgElevated,
              padding: "10px 12px", display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap",
            }}
          >
            <label style={{ display: "inline-flex", alignItems: "center", height: 28, padding: "0 12px", cursor: "pointer", fontSize: 11.5, fontWeight: 600, fontFamily: font.sans, color: "#1A0A00", background: color.copper, border: `1px solid ${color.copper}`, whiteSpace: "nowrap" }}>
              Elegir fichero…
              <input type="file" accept=".csv,.txt,.xlsx,.xlsm,.xls,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" onChange={onFile} style={{ display: "none" }} />
            </label>
            {fichero ? (
              <span style={{ display: "inline-flex", alignItems: "center", gap: 8, fontSize: 11, fontFamily: font.sans, color: color.textSecondary }}>
                <span style={{ fontFamily: font.mono, color: color.textHigh }}>{fichero.name}</span>
                <span style={{ color: color.textMuted }}>{fichero.size >= 1024 * 1024 ? `${n(fichero.size / 1024 / 1024, 1)} MB` : `${n(fichero.size / 1024, 0)} KB`}{fichero.b64 ? " · Excel, lo lee el backend" : lineas ? ` · ${n(lineas, 0)} líneas · ${esDas ? "formato DAS (fills)" : "formato fecha;pnl"}` : ""}</span>
                <Btn onClick={quitarFichero}>quitar</Btn>
              </span>
            ) : (
              <span style={{ fontSize: 10.5, fontFamily: font.sans, color: color.textMuted }}>
                el export de DAS (Transactions) en <strong>.csv</strong> o <strong>.xlsx</strong>, o un CSV con fecha y PnL · o arrástralo aquí
              </span>
            )}
          </div>
          {/* Pegar, como alternativa (y como vista del CSV cargado). */}
          {!fichero?.b64 && (
            <details open={!fichero && !!csv.trim()} style={{ marginTop: 6 }}>
              <summary style={{ fontSize: 10.5, fontFamily: font.sans, color: color.textMuted, cursor: "pointer", userSelect: "none" }}>
                {fichero ? "ver o editar el contenido" : "o pega aquí el contenido"}
                {!fichero && lineas > 0 && <span style={{ marginLeft: 8, color: color.textSecondary }}>{n(lineas, 0)} líneas · {esDas ? "formato DAS (fills)" : "formato fecha;pnl"}</span>}
              </summary>
              <textarea
                value={csv}
                onChange={(e) => { setCsv(e.target.value); if (fichero) setFichero(null); }}
                placeholder={"Pega aquí el export de DAS (Transactions) o un CSV con:\nfecha;pnl\n2026-08-03;125,40\n2026-08-04;-80,00"}
                spellCheck={false}
                style={{ ...control, width: "100%", minHeight: 100, marginTop: 6, fontFamily: font.mono, fontSize: 11, resize: "vertical", padding: 8 }}
              />
            </details>
          )}
          <div style={{ marginTop: 10 }}>
            <Row label="Unidad de la R">
              <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                <div style={{ width: 300 }}><Toggle value={riskMode} onChange={setRiskMode} options={[{ value: "notional", label: "posición (DAS)" }, { value: "pct", label: "% del equity" }, { value: "usd", label: "$ fijos" }]} /></div>
                {riskMode !== "notional" && (
                  <>
                    <div style={{ width: 80 }}><Num value={riskValue} onChange={(v) => setRiskValue(Number(v) || 0)} min={0} step={riskMode === "pct" ? 0.25 : 25} /></div>
                    <span style={{ fontSize: 10.5, fontFamily: font.sans, color: color.textMuted }}>{riskMode === "pct" ? "% del equity del día · capital al empezar" : "$ por trade"}</span>
                    {riskMode === "pct" && <div style={{ width: 100 }}><Num value={capitalInicial} onChange={(v) => setCapitalInicial(Number(v) || 0)} min={0} step={1000} /></div>}
                  </>
                )}
              </div>
            </Row>
            <Row label="Kelly">
              <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                <div style={{ width: 180 }}><Toggle value={base} onChange={setBase} options={[{ value: "clasica", label: "clásica" }, { value: "exacta", label: "exacta" }]} /></div>
                <span style={{ fontSize: 10.5, fontFamily: font.sans, color: color.textMuted }}>× fracción</span>
                <div style={{ width: 64 }}><Num value={mult} onChange={(v) => setMult(Math.max(0.01, Number(v) || 0))} min={0.01} max={3} step={0.05} /></div>
                <span style={{ fontSize: 10.5, fontFamily: font.sans, color: color.textMuted }}>· tope</span>
                <div style={{ width: 64 }}><Num value={capSuma} onChange={(v) => setCapSuma(Number(v) || 0)} min={0} step={0.5} /></div>
                <span style={{ fontSize: 10.5, fontFamily: font.sans, color: color.textMuted }}>% (0 = sin tope)</span>
              </div>
            </Row>
            <Row label="Ventana">
              <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                <div style={{ width: 70 }}><Num value={ventana} onChange={(v) => setVentana(Math.max(0, Math.round(Number(v) || 0)))} min={0} step={30} /></div>
                <span style={{ fontSize: 10.5, fontFamily: font.sans, color: color.textMuted }}>días (0 = toda la historia del CSV)</span>
              </div>
            </Row>
            <Row label="Reparto" help={`El total real se reparte entre las estrategias en proporción a ${origenPesos}. Tope por estrategia opcional.`}>
              <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                <span style={{ fontSize: 10.5, fontFamily: font.sans, color: color.textMuted }}>por estrategia ≤</span>
                <div style={{ width: 64 }}><Num value={capEst} onChange={(v) => setCapEst(Number(v) || 0)} min={0} step={0.25} /></div>
                <span style={{ fontSize: 10.5, fontFamily: font.sans, color: color.textMuted }}>% · capital para los $</span>
                <div style={{ width: 100 }}><Num value={capitalSig} onChange={(v) => setCapitalSig(Number(v) || 0)} min={0} step={1000} /></div>
              </div>
            </Row>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 12, padding: "12px 0 4px" }}>
            <Btn primary onClick={calcular} disabled={running || !hayEntrada}>{running ? "Calculando…" : "Calcular con mi cuenta"}</Btn>
            <span style={{ fontSize: 10.5, fontFamily: font.sans, color: hoy ? color.textMuted : color.warning }}>
              {hoy ? `reparto según ${origenPesos} (${estrategias.length} estrategias)` : "sin estrategias con % > 0 en el paso 1, sale el total pero no el reparto"}
            </span>
          </div>
          {error && <div style={{ marginTop: 8 }}><ErrorBox>{error}</ErrorBox></div>}
        </Sec>

        <Sec title="Siguiente periodo según tu cuenta" help={<>Arriba, lo que dice tu cuenta: operaciones, % de ganadoras, ganancia y pérdida medias, la Kelly (clásica y exacta), lo que pide tras la fracción y lo aplicado tras el tope: el riesgo TOTAL por trade. Si el freno del paso 4 está puesto y tu cuenta real está en caída, el total va × el multiplicador. Debajo, cada estrategia con su peso (el de la rotación del paso 4 o el % del paso 1), su proporción y lo que le toca en % y en $. <strong>La tarjeta del final es la respuesta</strong>: cuánto exponer en total y cuánto a cada estrategia.</>}>
          {!res ? (
            <Nota>Elige el fichero de DAS (.csv o .xlsx), o pega el CSV, y pulsa <strong>Calcular con mi cuenta</strong>.</Nota>
          ) : (
            <>
              {res.csv && (
                <Nota>
                  {res.csv.formato === "das" ? `DAS: ${n(res.csv.n_fills, 0)} fills → ${n(res.csv.n_ops, 0)} operaciones` : `${n(res.csv.n_ops, 0)} filas`} · {n(res.dias, 0)} días ({res.desde ?? "—"} → {res.hasta ?? "—"}) · PnL {usd(res.pnl_total)}
                  {res.csv.aviso ? ` · ${res.csv.aviso}` : ""}
                </Nota>
              )}
              <div style={{ display: "flex", flexWrap: "wrap", gap: "2px 12px", padding: "4px 0" }}>
                {res.ops && <Stat label="Operaciones" value={n(res.ops.n, 0)} sub={`${pct(res.ops.win_rate, 0)} ganadoras · media ${res.risk_mode === "notional" ? `+${pct(res.ops.ganancia_media * 100, 1)} / −${pct(res.ops.perdida_media * 100, 1)} de la posición` : `+${usd(res.ops.ganancia_media)} / −${usd(res.ops.perdida_media)}`}`} />}
                <Stat label="Kelly clásica" value={res.kelly_clasica_pct == null ? "—" : pct(res.kelly_clasica_pct, 1)} sub="p − q/b por operación" tone={res.kelly_base === "clasica" ? "profit" : undefined} help="p = % de operaciones ganadoras; b = ganancia media / pérdida media. f = p − (1 − p)/b." />
                <Stat label="Kelly exacta" value={res.kelly_exacta_pct == null ? "—" : pct(res.kelly_exacta_pct, 1)} sub={`R diaria: media ${n(res.r_media_dia, 2)} · peor ${n(res.r_peor_dia, 2)}`} tone={res.kelly_base === "exacta" ? "profit" : undefined} help="La f que maximiza la media de log(1 + f·R diaria). Con pocos días y un peor día pequeño sale enorme: no es una recomendación." />
                <Stat label={`× ${n(res.kelly_mult, 2)} → pide`} value={res.total_pedido_pct == null ? "—" : pct(res.total_pedido_pct, 2)} sub={res.nota || `sobre la Kelly ${res.kelly_base === "clasica" ? "clásica" : "exacta"}`} />
                <Stat big label="Riesgo total por trade" value={res.total_pct == null ? "—" : pct(res.total_pct, 2)} sub={res.total_pct == null ? "" : `${usd(res.total_usd)} sobre ${usd(res.capital_siguiente)}${res.capped ? " · manda el tope" : ""}`} tone={res.total_pct == null ? undefined : "profit"} />
              </div>
              {res.nota && <Nota tone="warning">{res.nota}</Nota>}
              {res.freno && (
                <Nota tone={res.freno.frenado ? "warning" : undefined}>
                  Freno por caída sobre tu cuenta real: {res.freno.frenado ? <>PUESTO (×{n(res.freno.mult, 2)}): tu cuenta está a {pct(res.freno.dd_pct)} de su máximo ({usd(res.freno.peak)})</> : <>quitado: tu cuenta está a {pct(res.freno.dd_pct)} de su máximo</>}
                  {res.freno.episodios > 0 ? ` · en el histórico del CSV se habría frenado ${n(res.freno.episodios, 0)} ${res.freno.episodios === 1 ? "vez" : "veces"} (${n(res.freno.dias_frenado, 0)} días)` : ""}.
                </Nota>
              )}
              {res.per_strategy.length > 0 && (
                <table style={{ width: "100%", borderCollapse: "collapse", marginTop: 6 }}>
                  <thead>
                    <tr>
                      <th style={thL}>Estrategia</th>
                      <th style={thR}>Peso (paso 4)</th>
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
              {res.total_pct != null && (() => {
                const mult = res.freno?.frenado ? res.freno.mult : 1;
                const totalFinal = res.total_pct * mult;
                const usdFinal = (res.total_usd ?? 0) * mult;
                return (
                  <div style={{ marginTop: 10, border: `1px solid ${color.copper}`, background: "rgba(184, 115, 51, 0.06)", padding: "8px 12px" }}>
                    <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: "1px", textTransform: "uppercase", color: color.copper, fontFamily: font.sans, marginBottom: 4 }}>
                      Siguiente periodo — lo que toca poner en tu cuenta
                    </div>
                    <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                      <Stat big label="Exposición total por trade" value={pct(totalFinal, 2)} sub={`${usd(usdFinal)} sobre ${usd(res.capital_siguiente)}${mult < 1 ? ` · con el freno ×${n(mult, 2)}` : ""}`} tone="profit" />
                      {res.per_strategy.map((p, i) => (
                        <Stat key={p.name + i} label={p.name.length > 22 ? `${p.name.slice(0, 21)}…` : p.name} value={p.risk_pct == null ? "—" : pct(p.risk_pct * mult, 2)} sub={`${p.risk_usd == null ? "—" : usd(p.risk_usd * mult)} · ${p.basis === "capital" ? "en posición" : "en riesgo al stop"}`} />
                      ))}
                    </div>
                    <div style={{ fontSize: 10.5, fontFamily: font.sans, color: color.textMuted, marginTop: 4, lineHeight: 1.5 }}>
                      El total sale de tu operativa real (Kelly {res.kelly_base === "clasica" ? "clásica" : "exacta"} × {n(res.kelly_mult, 2)}, topada al {pct(res.cap_pct, 1)}{mult < 1 ? ", × el freno" : ""}); el reparto entre estrategias, de {origenPesos}. La unidad de cada una es la de su backtest: «riesgo» (lo que pierde si salta el stop) o «posición» (% del capital metido en la operación).
                    </div>
                  </div>
                );
              })()}
            </>
          )}
        </Sec>
      </div>
    </div>
  );
}
