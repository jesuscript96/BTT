"use client";

/**
 * EV BARRIENDO LA VENTANA DE ENTRADA (6-sep-2026, petición de Jaume).
 *
 * El gráfico «EV por Tiempo» de al lado mide una cosa distinta: agrupa los
 * trades QUE HUBO por su hora de entrada. Si la estrategia tiene un límite
 * horario de 09:30 a 11:30, ahí no hay nada que ver fuera de esa franja — y lo
 * que se quiere saber es justo lo contrario: qué habría pasado con OTRA franja.
 *
 * Esto lanza N backtests, uno por franja (09:30-10:00, 10:00-10:30, …), y pinta
 * el EV de cada uno. Va por el mismo motor que el optimizador 3D: un solo eje
 * de rejilla con `linked_paths`, que mueve las dos puntas de la ventana de una
 * pieza. N corridas, no N².
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Cell, ReferenceLine,
} from "recharts";
import { Loader2, Play, X } from "lucide-react";
import {
  runOptimizationSurface, fetchOptimizationResult, cancelOptimization,
  type OptimizationParamConfig, type OptimizationResult,
} from "@/lib/api_backtester";

interface Props {
  strategyId: string;
  strategyDefinition?: Record<string, any>;
  datasetId: string;
  backtestParams?: Record<string, unknown>;
  isDarkMode?: boolean;
}

const ANCHOS = [15, 30, 60, 120];

/** "09:30" -> 570. null si no tiene forma de hora. */
function aMinutos(txt: unknown): number | null {
  const m = /^(\d{1,2}):(\d{2})$/.exec(String(txt ?? "").trim());
  if (!m) return null;
  const h = Number(m[1]);
  const mi = Number(m[2]);
  if (h > 23 || mi > 59) return null;
  return h * 60 + mi;
}

/** 570 -> "09:30". */
function aHora(mins: number): string {
  const m = ((Math.round(mins) % 1440) + 1440) % 1440;
  return `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;
}

/** Rango de reloj que cubre la sesión de la corrida. Es el terreno del barrido. */
function rangoDeSesion(params: Record<string, unknown> | undefined): [number, number] {
  const sesiones = (params?.market_sessions as string[] | undefined) || ["rth"];
  const PRESETS: Record<string, [number, number]> = {
    pre: [240, 570], rth: [570, 960], post: [960, 1200],
  };
  const rangos: [number, number][] = [];
  for (const s of sesiones) {
    if (s === "custom") {
      const a = aMinutos(params?.custom_start_time) ?? 570;
      const b = aMinutos(params?.custom_end_time) ?? 960;
      rangos.push([a, b]);
    } else if (PRESETS[s]) {
      rangos.push(PRESETS[s]);
    }
  }
  if (!rangos.length) return [570, 960];
  return [
    Math.min(...rangos.map((r) => r[0])),
    Math.max(...rangos.map((r) => r[1])),
  ];
}

export default function EntryWindowSweepChart({
  strategyId, strategyDefinition, datasetId, backtestParams = {}, isDarkMode = false,
}: Props) {
  // Ancho por defecto: el de la ventana que ya tiene la estrategia, si tiene.
  const anchoActual = useMemo(() => {
    const w = (strategyDefinition?.entry_logic?.entry_time_windows || [])[0];
    const a = aMinutos(w?.from_time);
    const b = aMinutos(w?.to_time);
    if (a === null || b === null || b <= a) return 30;
    const diff = b - a;
    return ANCHOS.reduce((mejor, x) => (Math.abs(x - diff) < Math.abs(mejor - diff) ? x : mejor), 30);
  }, [strategyDefinition]);

  const [ancho, setAncho] = useState(anchoActual);
  // BRUTO vs NETO (6-sep-2026). `expectancy` del motor divide el PnL ANTES del
  // alquiler de acciones: en la corrida de Jaume eso eran 3.604 $ de 11.699 $,
  // o sea un 45 % de EV de mas. `total_pnl` si lleva comisiones Y locates
  // descontados. Se dejan las DOS lecturas y manda el usuario; el defecto se
  // queda en «bruto» para no cambiarle el grafico que ya conocia.
  const [metrica, setMetrica] = useState<"bruto" | "neto">("bruto");
  const [cargando, setCargando] = useState(false);
  const [progreso, setProgreso] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [resultado, setResultado] = useState<OptimizationResult | null>(null);
  const [taskId, setTaskId] = useState<string | null>(null);
  const pollRef = useRef<number | null>(null);

  useEffect(() => setAncho(anchoActual), [anchoActual]);

  // Al desmontar, dejar de preguntar. Sin esto el intervalo sobrevive al tab.
  useEffect(() => () => {
    if (pollRef.current) window.clearInterval(pollRef.current);
  }, []);

  const [desdeSesion, hastaSesion] = useMemo(
    () => rangoDeSesion(backtestParams), [backtestParams]);

  /** Los comienzos de cada franja. Tope de 24 para no lanzar 60 backtests. */
  const inicios = useMemo(() => {
    const out: number[] = [];
    for (let t = desdeSesion; t + ancho <= hastaSesion && out.length < 24; t += ancho) {
      out.push(t);
    }
    return out;
  }, [desdeSesion, hastaSesion, ancho]);

  const sondear = useCallback((id: string) => {
    let fallos = 0;
    const iv = window.setInterval(async () => {
      try {
        const res: any = await fetchOptimizationResult(id);
        fallos = 0;
        if (res && res.status === "running") {
          setProgreso(Number(res.progress) || 0);
          return;
        }
        window.clearInterval(iv);
        pollRef.current = null;
        setTaskId(null);
        setProgreso(100);
        setResultado(res as OptimizationResult);
        setCargando(false);
      } catch (e: any) {
        fallos++;
        if (fallos >= 5) {
          window.clearInterval(iv);
          pollRef.current = null;
          setTaskId(null);
          setError(e?.response?.data?.detail || e?.message || "Error recuperando el barrido");
          setCargando(false);
        }
      }
    }, 900);
    pollRef.current = iv;
  }, []);

  const lanzar = async () => {
    if (!inicios.length) {
      setError("La sesión de la estrategia no da para ninguna franja de ese ancho.");
      return;
    }
    setCargando(true);
    setError(null);
    setResultado(null);
    setProgreso(0);

    const id = `evwin_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`;

    // La definición que se manda LLEVA la ventana sembrada aunque la estrategia
    // no tenga ninguna: sin ella la ruta `entry_time_windows.0.from_time` no
    // existe y el barrido escribiría en el vacío — sin error y sin aviso, con
    // las 24 franjas dando exactamente el mismo número.
    const definicion = JSON.parse(JSON.stringify(strategyDefinition || {}));
    definicion.entry_logic = definicion.entry_logic || {};
    definicion.entry_logic.entry_time_windows = [
      { from_time: aHora(inicios[0]), to_time: aHora(inicios[0] + ancho) },
    ];

    const eje: OptimizationParamConfig = {
      id: "entry_window_sweep",
      label: "Franja de entrada",
      path: "entry_logic.entry_time_windows.0.from_time",
      min: inicios[0],
      max: inicios[inicios.length - 1],
      steps: inicios.length,
      values: inicios,
      linked_paths: ["entry_logic.entry_time_windows.0.to_time"],
      linked_offsets: [ancho],
    };

    try {
      await runOptimizationSurface({
        strategy_id: strategyId,
        strategy_definition: definicion,
        dataset_id: datasetId,
        metric: "expectancy",
        param_configs: [eje],
        task_id: id,
        ...backtestParams,
      });
      setTaskId(id);
      sondear(id);
    } catch (e: any) {
      setError(e?.response?.data?.detail || e?.message || "No se pudo lanzar el barrido");
      setCargando(false);
    }
  };

  const cancelar = async () => {
    if (taskId) {
      try { await cancelOptimization(taskId); } catch { /* el barrido ya habrá muerto */ }
    }
    if (pollRef.current) window.clearInterval(pollRef.current);
    pollRef.current = null;
    setTaskId(null);
    setCargando(false);
    setProgreso(0);
  };

  const datos = useMemo(() => {
    if (!resultado) return [];
    const valores = resultado.params?.[0]?.values || [];
    return valores.map((v: number, i: number) => {
      const det: any = resultado.details?.[i] || {};
      const n = Number(det.total_trades ?? 0);
      const bruto = Number(det.expectancy ?? 0);
      // Sin operaciones no hay media que valga: 0, no una division por cero.
      const neto = n > 0 ? Number(det.total_pnl ?? 0) / n : 0;
      return {
        franja: `${aHora(v)}-${aHora(v + ancho)}`,
        ev: metrica === "neto" ? neto : bruto,
        bruto,
        neto,
        total: Number(det.total_pnl ?? 0),
        trades: n,
        pf: Number(det.profit_factor ?? 0),
      };
    });
  }, [resultado, ancho, metrica]);

  const gridColor = isDarkMode ? "rgba(255,255,255,0.06)" : "rgba(0,0,0,0.06)";
  const tickColor = isDarkMode ? "#8A8D92" : "#6A6D72";
  const tooltipBg = isDarkMode ? "#1A1C1E" : "#2A2C2E";
  const verde = isDarkMode ? "rgba(74,157,110,0.9)" : "#4A9D6E";
  const rojo = isDarkMode ? "rgba(200,80,70,0.9)" : "#C85046";

  return (
    <div className="flex flex-col h-full">
      <div className="px-4 pt-1 pb-3 flex items-center gap-3 flex-wrap">
        <span className="text-[9px] text-[var(--color-ec-text-muted)] uppercase tracking-wider">Ancho</span>
        {/* `gap-1` entre botones y `p-[3px]` en la caja: sin eso los cuadros se
            tocaban entre si y con el borde, y los minutos parecian un continuo. */}
        <div className="flex items-center gap-1 bg-[var(--color-ec-bg-elevated)] rounded border border-[var(--color-ec-border)] h-[24px] p-[3px]">
          {ANCHOS.map((a) => (
            <button
              key={a}
              onClick={() => setAncho(a)}
              disabled={cargando}
              className={`px-2.5 text-[9px] font-mono rounded-sm transition-colors ${
                ancho === a
                  ? "bg-[var(--color-ec-copper)] text-[var(--color-ec-copper-text)]"
                  : "text-[var(--color-ec-text-secondary)]"
              }`}
            >
              {a}m
            </button>
          ))}
        </div>
        <div className="flex items-center gap-1 bg-[var(--color-ec-bg-elevated)] rounded border border-[var(--color-ec-border)] h-[24px] p-[3px]">
          {([["bruto", "Bruto"], ["neto", "Neto"]] as const).map(([id, txt]) => (
            <button
              key={id}
              onClick={() => setMetrica(id)}
              title={id === "neto"
                ? "PnL total ÷ operaciones: comisiones y locates ya descontados"
                : "Expectancy del motor: ANTES del coste de locates"}
              className={`px-2.5 text-[9px] font-mono rounded-sm transition-colors ${
                metrica === id
                  ? "bg-[var(--color-ec-copper)] text-[var(--color-ec-copper-text)]"
                  : "text-[var(--color-ec-text-secondary)]"
              }`}
            >
              {txt}
            </button>
          ))}
        </div>
        <span className="text-[9px] text-[var(--color-ec-text-muted)] font-mono">
          {inicios.length} franjas · {aHora(desdeSesion)}-{aHora(hastaSesion)}
        </span>
        {!cargando ? (
          <button
            onClick={lanzar}
            className="ml-auto mx-1 inline-flex items-center gap-1.5 px-3.5 h-[24px] rounded text-[9px] font-bold uppercase tracking-wider bg-[var(--color-ec-copper)] text-[var(--color-ec-copper-text)]"
          >
            <Play size={9} /> Barrer
          </button>
        ) : (
          <button
            onClick={cancelar}
            className="ml-auto mx-1 inline-flex items-center gap-1.5 px-3.5 h-[24px] rounded text-[9px] font-bold uppercase tracking-wider border border-[var(--color-ec-border)] text-[var(--color-ec-text-secondary)]"
          >
            <X size={9} /> Cancelar
          </button>
        )}
      </div>

      <div className="flex-1 px-4 pb-4 min-h-0">
        {error && (
          <p className="text-[10px] text-[var(--color-ec-loss)] pt-2">{error}</p>
        )}
        {cargando && (
          <div className="h-full flex flex-col items-center justify-center gap-2 text-[var(--color-ec-text-muted)]">
            <Loader2 size={16} className="animate-spin" />
            <span className="text-[10px] font-mono">
              {inicios.length} backtests · {progreso.toFixed(0)}%
            </span>
          </div>
        )}
        {!cargando && !resultado && !error && (
          <div className="h-full flex items-center justify-center px-6">
            <p className="text-[10px] text-[var(--color-ec-text-muted)] text-center leading-relaxed">
              Lanza un backtest por cada franja horaria y compara su EV.
              El gráfico de al lado solo mide los trades que YA hubo; este mide
              los que habría con otro límite horario de entrada.
              <br /><br />
              <b>Neto</b> descuenta comisiones y locates; <b>Bruto</b> es la
              expectancy del motor, que va antes del coste de locates. Ninguno
              de los dos lleva los gastos fijos del mes.
            </p>
          </div>
        )}
        {!cargando && resultado && (
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={datos} margin={{ top: 16, right: 16, bottom: 16, left: 16 }}>
              <CartesianGrid stroke={gridColor} vertical={false} />
              <XAxis
                dataKey="franja"
                tick={{ fontSize: 9, fill: tickColor, fontFamily: "monospace" }}
                axisLine={false} tickLine={false} minTickGap={12} interval="preserveStartEnd"
              />
              <YAxis
                tick={{ fontSize: 10, fill: tickColor, fontFamily: "monospace" }}
                axisLine={false} tickLine={false}
                tickFormatter={(v: number) => `$${v.toFixed(0)}`}
              />
              <Tooltip
                contentStyle={{ fontSize: "10px", backgroundColor: tooltipBg, border: "1px solid var(--border)", borderRadius: 2, fontFamily: "monospace", color: "#fff" }}
                itemStyle={{ color: "#fff" }}
                labelStyle={{ color: "#aaa" }}
                formatter={(_value: any, _n: any, p: any) => {
                  const d = p?.payload || {};
                  return [
                    `neto $${Number(d.neto ?? 0).toFixed(2)} · bruto $${Number(d.bruto ?? 0).toFixed(2)}` +
                    `  ·  ${d.trades ?? 0} trades  ·  total $${Number(d.total ?? 0).toFixed(0)}` +
                    `  ·  PF ${Number(d.pf ?? 0).toFixed(2)}`,
                    "EV",
                  ];
                }}
                cursor={{ fill: "rgba(120,113,108,0.04)" }}
              />
              <ReferenceLine y={0} stroke="#6A6D72" strokeWidth={0.5} />
              <Bar dataKey="ev" radius={[1, 1, 0, 0]}>
                {datos.map((d, i) => (
                  <Cell key={i} fill={d.ev >= 0 ? verde : rojo} fillOpacity={isDarkMode ? 0.75 : 1} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        )}
      </div>
    </div>
  );
}
