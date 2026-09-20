"use client";

// Paso 5 de «En crudo», «Cuenta real» (20-sep-2026, tarde; Jaume: «esta parte
// sería solo para comprobar la paridad entre lo simulado y lo real, y que me
// diga según mi histórico cuánto debería apostar si hemos puesto freno y los
// % de cada estrategia»). Sin Kelly: el total lo pone el paso 4 (la suma de
// los % de la rotación o del paso 1) y el freno se aplica a la curva REAL.
//
// El fichero: el export de DAS («Transactions», una fila por fill) en .csv o
// .xlsx, o un CSV con fecha y PnL. Los fills se agrupan en operaciones por
// símbolo-día (PnL = ventas − compras) y de ahí sale el PnL diario real, que
// es lo único que se usa: la curva real (capital inicial + PnL acumulado)
// para compararla con los caminos del paso 3 y para el estado del freno.

import React, { useState } from "react";
import { color, font } from "@/components/ui/tokens";
import { ErrorBox } from "@/components/robustez/shared";
import { kellyCuentaReal, type KellyRealOut, type RawBrakeIn, type RawCaminosOut, type RawOut } from "@/lib/api_portfolio_lab";
import { Btn, Nota, Num, Row, Sec, Stat, Toggle, control, n, pct, usd } from "./hoja";
import { LinesChart } from "./CrudoCharts";
import { realSobreCaminos } from "./CaminosLocates";

export function PasoCuentaReal({ m }: { m: {
  out: RawOut | null; capital: number;
  /** El % por trade de cada estrategia para el siguiente periodo (la rotación del paso 4 o los % del paso 1). */
  pesos: Array<{ name: string; kelly_pct: number; basis: "risk" | "capital" }>;
  origenPesos: string;
  /** El freno por caida del paso 4 (null = sin freno): se aplica a la curva REAL del CSV. */
  brake: RawBrakeIn | null;
  /** Los caminos del paso 3 (si se han simulado): la curva real se pinta encima. */
  caminos: RawCaminosOut | null;
} }) {
  const { capital, pesos, origenPesos, brake, caminos } = m;
  const [rangoIdx, setRangoIdx] = useState(0);
  const [csv, setCsv] = useState("");
  // Fichero elegido: un CSV/TXT se lee aquí y va como texto (se puede ver en
  // la caja); un Excel va en base64 y lo lee el backend (openpyxl).
  const [fichero, setFichero] = useState<{ name: string; size: number; b64: string | null } | null>(null);
  const [arrastrando, setArrastrando] = useState(false);
  const [capitalInicial, setCapitalInicial] = useState<number>(capital > 0 ? capital : 10000);
  const [capitalSig, setCapitalSig] = useState<number>(capital > 0 ? capital : 10000);
  const [res, setRes] = useState<KellyRealOut | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const lineas = csv.trim() ? csv.trim().split(/\r?\n/).length : 0;
  const esDas = /symbol/i.test(csv.slice(0, 400)) && /net amt/i.test(csv.slice(0, 400));
  const totalPesos = pesos.reduce((a, p) => a + (p.kelly_pct > 0 ? p.kelly_pct : 0), 0);

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
      // El backend agrupa los fills en operaciones y devuelve el PnL diario
      // (serie), el estado del freno sobre la curva real y las cifras del CSV.
      // Lo de Kelly que también calcula no se enseña (Jaume, 20-sep).
      const o = await kellyCuentaReal({
        csv_text: fichero?.b64 ? undefined : csv,
        file_b64: fichero?.b64 ?? undefined,
        filename: fichero?.b64 ? fichero.name : undefined,
        risk_mode: "notional", risk_value: 1, capital_inicial: capitalInicial,
        kelly_mult: 1, cap_pct: 0, cap_strategy_pct: 0, lookback_days: 0, kelly_base: "clasica",
        estrategias: [], capital_siguiente: capitalSig, brake,
      });
      setRes(o);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setRunning(false);
    }
  };

  const multFreno = res?.freno ? (res.freno.frenado ? res.freno.mult : 1) : null;
  const filaCard = (titulo: string, mult: number, sub: string) => (
    <div style={{ display: "flex", flexWrap: "wrap", gap: 4, alignItems: "flex-start" }}>
      <Stat big label={titulo} value={pct(totalPesos * mult, 2)} sub={`${usd(capitalSig * totalPesos * mult / 100)} sobre ${usd(capitalSig)} · ${sub}`} tone="profit" />
      {pesos.map((p, i) => (
        <Stat key={p.name + i} label={p.name.length > 22 ? `${p.name.slice(0, 21)}…` : p.name} value={pct(p.kelly_pct * mult, 2)} sub={`${usd(capitalSig * p.kelly_pct * mult / 100)} · ${p.basis === "capital" ? "en posición" : "en riesgo al stop"}`} />
      ))}
    </div>
  );

  return (
    <div>
      <div style={{ display: "grid", gridTemplateColumns: "minmax(380px, 1fr) minmax(0, 1fr)", gap: 14, alignItems: "start" }}>
        <Sec title="Tu cuenta" help={
          <>
            <strong>Qué meter</strong>: el fichero del export de DAS («Transactions»: una fila por fill, con Trade Date,
            Side, Symbol, Qty, Price, comisiones y Net Amt) en .csv o en Excel (.xlsx), o un CSV sencillo con
            <em>fecha</em> y <em>PnL neto</em> por día o por operación. También vale pegar el contenido.
            <br /><br />
            <strong>Qué se hace con él</strong>: los fills se agrupan en operaciones por símbolo y día (PnL = lo vendido − lo
            comprado, con las tasas dentro) y de ahí sale tu PnL de cada día. Con eso: (1) tu curva real (capital inicial + PnL
            acumulado) se pinta encima de los caminos del paso 3, para ver si lo que ganas es lo que dice la simulación; (2) se
            mira si tu cuenta está en caída para el freno del paso 4; (3) la tarjeta final te dice cuánto poner el siguiente
            periodo: la suma de los % del paso 4 (la rotación, o los % del paso 1) y el % de cada estrategia, sin freno y con freno.
            No hace falta saber de qué estrategia viene cada trade real.
          </>
        }>
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
            <Row label="Capital" help="Con el que empezó el CSV (para la curva real y la caída del freno) y con el que vas a operar el siguiente periodo (para pasar los % a dólares).">
              <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                <span style={{ fontSize: 10.5, fontFamily: font.sans, color: color.textMuted }}>al empezar el CSV</span>
                <div style={{ width: 100 }}><Num value={capitalInicial} onChange={(v) => setCapitalInicial(Number(v) || 0)} min={0} step={1000} /></div>
                <span style={{ fontSize: 10.5, fontFamily: font.sans, color: color.textMuted }}>· el siguiente periodo</span>
                <div style={{ width: 100 }}><Num value={capitalSig} onChange={(v) => setCapitalSig(Number(v) || 0)} min={0} step={1000} /></div>
              </div>
            </Row>
            <Row label="Freno" help="El del paso 4. Con freno, se recorre tu curva real con la misma regla (frena a partir de −X %, suelta al volver a −Y %) y se ve si ahora mismo estaría puesto.">
              <span style={{ fontSize: 11, fontFamily: font.sans, color: brake ? color.textHigh : color.textMuted }}>{brake ? `frena a partir de −${n(brake.dd_pct, 0)} % → ×${n(brake.mult, 2)} hasta −${n(brake.exit_dd_pct, 0)} %` : "sin freno (enciéndelo en el paso 4 si lo quieres)"}</span>
            </Row>
            <Row label="Pesos" help="Los % por trade de cada estrategia para el siguiente periodo: los de la rotación del paso 4 si la has calculado (lo que toca poner), si no los % del paso 1.">
              <span style={{ fontSize: 11, fontFamily: font.sans, color: color.textHigh }}>{pesos.map((p) => `${p.name.length > 14 ? `${p.name.slice(0, 13)}…` : p.name} ${n(p.kelly_pct, 2)} %`).join(" · ")} <span style={{ color: color.textMuted }}>= {n(totalPesos, 2)} % · {origenPesos}</span></span>
            </Row>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 12, padding: "12px 0 4px" }}>
            <Btn primary onClick={calcular} disabled={running || !hayEntrada}>{running ? "Calculando…" : "Calcular con mi cuenta"}</Btn>
          </div>
          {error && <div style={{ marginTop: 8 }}><ErrorBox>{error}</ErrorBox></div>}
        </Sec>

        <Sec title="Tu cuenta real frente a la simulación" help={<>Lo que dice tu CSV (operaciones, días, PnL, % de ganadoras) y tu curva real (capital inicial + PnL diario) encima de la banda p05–p95 de los caminos del paso 3, en los días que coinciden, las dos a 0 % el primer día real. Si tu curva va por dentro de la banda, lo que ganas es lo que dice la simulación con los locates de ese rango; si va por debajo de la p05, o los locates te salen más caros que el rango, o hay algo más (slippage, fills, algo que no está en el backtest).</>}
          right={res && caminos && caminos.rangos.length > 1 ? <div style={{ width: Math.min(420, 110 * caminos.rangos.length) }}><Toggle value={String(Math.min(rangoIdx, caminos.rangos.length - 1))} onChange={(v) => setRangoIdx(Number(v))} options={caminos.rangos.map((x, k) => ({ value: String(k), label: `${n(x.lo, 1)}–${n(x.hi, 1)} $` }))} /></div> : undefined}
        >
          {!res ? (
            <Nota>Elige el fichero de DAS (.csv o .xlsx), o pega el CSV, y pulsa <strong>Calcular con mi cuenta</strong>.</Nota>
          ) : (
            <>
              <div style={{ display: "flex", flexWrap: "wrap", gap: "2px 12px", padding: "4px 0" }}>
                {res.csv && <Stat label="Fichero" value={res.csv.formato === "das" ? `${n(res.csv.n_fills, 0)} fills → ${n(res.csv.n_ops, 0)} ops` : `${n(res.csv.n_ops, 0)} filas`} sub={`${n(res.dias, 0)} días · ${res.desde ?? "—"} → ${res.hasta ?? "—"}`} />}
                <Stat label="PnL del CSV" value={usd(res.pnl_total)} sub={`equity final ${usd(res.equity_final)}`} tone={(res.pnl_total ?? 0) >= 0 ? "profit" : "loss"} />
                {res.ops && <Stat label="Operaciones" value={n(res.ops.n, 0)} sub={`${pct(res.ops.win_rate, 0)} ganadoras · media +${pct(res.ops.ganancia_media * 100, 1)} / −${pct(res.ops.perdida_media * 100, 1)} de la posición`} />}
                {res.freno && <Stat label="Freno sobre tu cuenta" value={res.freno.frenado ? `PUESTO ×${n(res.freno.mult, 2)}` : "quitado"} sub={`a ${pct(res.freno.dd_pct)} de tu máximo (${usd(res.freno.peak)})${res.freno.episodios > 0 ? ` · en el CSV se habría frenado ${n(res.freno.episodios, 0)} ${res.freno.episodios === 1 ? "vez" : "veces"}` : ""}`} tone={res.freno.frenado ? "warning" : undefined} />}
              </div>
              {res.csv?.aviso && <Nota tone="warning">{res.csv.aviso}</Nota>}
              {caminos ? (() => {
                const real: Array<{ date: string; equity: number }> = [];
                let acc = capitalInicial;
                for (const f of res.serie) { acc += f.pnl; real.push({ date: f.date, equity: acc }); }
                const k = Math.min(rangoIdx, caminos.rangos.length - 1);
                const g = realSobreCaminos(caminos, k, real);
                const r = caminos.rangos[k];
                return !g ? (
                  <Nota>Tu CSV ({res.desde ?? "—"} → {res.hasta ?? "—"}) y la simulación ({caminos.calendar[0]} → {caminos.calendar[caminos.calendar.length - 1]}) no comparten al menos dos días: no hay tramo que comparar. Corre las estrategias hasta hoy y vuelve a calcular el paso 1.</Nota>
                ) : (
                  <>
                    <Nota>{n(g.dias, 0)} días en común ({g.desde} → {g.hasta}) · rango de locates {n(r.lo, 2)}–{n(r.hi, 2)} $ · {n(r.seeds, 0)} caminos.</Nota>
                    <LinesChart labels={g.labels} series={g.series} band={g.band} yFormat={(v) => `${n(v, 1)} %`} hoverFormat={(v) => `${n(v, 2)} %`} height={240} titulo="RETORNO DESDE EL PRIMER DÍA REAL" />
                  </>
                );
              })() : (
                <Nota>Para ver tu curva sobre las bandas, simula antes los <strong>caminos según los locates</strong> en el paso 3.</Nota>
              )}
            </>
          )}
        </Sec>
      </div>

      {res && (
        <div style={{ marginTop: 10, border: `1px solid ${color.copper}`, background: "rgba(184, 115, 51, 0.06)", padding: "8px 12px" }}>
          <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: "1px", textTransform: "uppercase", color: color.copper, fontFamily: font.sans, marginBottom: 4 }}>
            Siguiente periodo — lo que toca poner en tu cuenta
          </div>
          {filaCard("Sin freno: exposición total por trade", 1, `la suma de los % de ${origenPesos}`)}
          {multFreno != null && (
            <div style={{ marginTop: 6, paddingTop: 6, borderTop: `1px solid ${color.border}` }}>
              {filaCard("Con freno: exposición total por trade", multFreno, multFreno < 1 ? `el freno está PUESTO: × ${n(multFreno, 2)} (tu cuenta a ${pct(res.freno?.dd_pct)} de su máximo)` : `el freno está quitado (tu cuenta a ${pct(res.freno?.dd_pct)} de su máximo): lo mismo`)}
            </div>
          )}
          <div style={{ fontSize: 10.5, fontFamily: font.sans, color: color.textMuted, marginTop: 4, lineHeight: 1.5 }}>
            El total y el reparto salen del paso 4 ({origenPesos}); «con freno» aplica la regla del paso 4 a tu curva real. La unidad de cada estrategia es la de su backtest: «riesgo» (lo que pierde si salta el stop) o «posición» (% del capital metido en la operación).
          </div>
        </div>
      )}
    </div>
  );
}
