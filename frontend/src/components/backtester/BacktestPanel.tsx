"use client";

import { useEffect, useState } from "react";
import type { Dataset, Strategy } from "@/lib/api_backtester";
import { fetchDatasets, fetchStrategies } from "@/lib/api_backtester";

interface BacktestPanelProps {
  onRun: (params: {
    dataset_id: string;
    strategy_id: string;
    init_cash: number;
    risk_r: number;
    fees: number;
    slippage: number;
    start_date?: string;
    end_date?: string;
    market_sessions?: string[];
    custom_start_time?: string;
    custom_end_time?: string;
    locates_cost?: number;
    look_ahead_prevention?: boolean;
    risk_type?: string;
    size_by_sl?: boolean;
    fee_type?: string;
    monthly_expenses?: number;
    fixed_ratio_delta?: number;
  }) => void;
  loading: boolean;
  isDarkMode?: boolean;
}

export default function BacktestPanel({ onRun, loading, isDarkMode = false }: BacktestPanelProps) {
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [strategies, setStrategies] = useState<Strategy[]>([]);
  const [selectedDataset, setSelectedDataset] = useState("");
  const [selectedStrategy, setSelectedStrategy] = useState("");
  const [initCash, setInitCash] = useState(10000);
  const [riskR, setRiskR] = useState(100);
  const [fees, setFees] = useState(0.01);
  const [slippage, setSlippage] = useState(0.01);
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [marketSessions, setMarketSessions] = useState<string[]>(["rth"]);
  const [customStartTime, setCustomStartTime] = useState("09:30");
  const [customEndTime, setCustomEndTime] = useState("16:00");
  const [locatesCost, setLocatesCost] = useState(0);
  const [useLocates, setUseLocates] = useState(false);
  const [useMonthlyExpenses, setUseMonthlyExpenses] = useState(false);
  const [monthlyExpenses, setMonthlyExpenses] = useState(0);
  const [lookAheadPrevention, setLookAheadPrevention] = useState(true);
  const [riskType, setRiskType] = useState<"FIXED" | "PERCENT" | "KELLY" | "FIXED_RATIO">("FIXED");
  const [fixedRatioDelta, setFixedRatioDelta] = useState(500);
  const [sizeBySl, setSizeBySl] = useState(false);
  const [feeType, setFeeType] = useState<"PERCENT" | "FLAT">("PERCENT");
  const [loadingData, setLoadingData] = useState(true);
  const [loadError, setLoadError] = useState(false);

  const loadData = async () => {
    setLoadingData(true);
    setLoadError(false);
    let failed = false;
    try {
      const d = await fetchDatasets();
      setDatasets(d);
      if (d.length > 0) {
        setSelectedDataset(d[0].id);
        if (d[0].min_date) setStartDate(d[0].min_date);
        if (d[0].max_date) setEndDate(d[0].max_date);
      }
    } catch (e) {
      console.error("Error loading datasets:", e);
      failed = true;
    }
    try {
      const s = await fetchStrategies();
      setStrategies(s);
      if (s.length > 0) setSelectedStrategy(s[0].id);
    } catch (e) {
      console.error("Error loading strategies:", e);
      failed = true;
    }
    setLoadError(failed);
    setLoadingData(false);
  };

  useEffect(() => {
    loadData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const ds = datasets.find(d => d.id === selectedDataset);
    if (ds) {
      if (ds.min_date) setStartDate(ds.min_date);
      if (ds.max_date) setEndDate(ds.max_date);
    }
  }, [selectedDataset, datasets]);

  const handleRun = () => {
    if (!selectedDataset || !selectedStrategy) return;
    onRun({
      dataset_id: selectedDataset,
      strategy_id: selectedStrategy,
      init_cash: initCash,
      risk_r: riskR,
      fees: feeType === "PERCENT" ? fees / 100 : fees,
      fee_type: feeType,
      slippage: slippage / 100,
      start_date: startDate,
      end_date: endDate,
      market_sessions: marketSessions,
      custom_start_time: marketSessions.includes("custom") ? customStartTime : undefined,
      custom_end_time: marketSessions.includes("custom") ? customEndTime : undefined,
      locates_cost: useLocates ? locatesCost : 0,
      monthly_expenses: useMonthlyExpenses ? monthlyExpenses : 0,
      look_ahead_prevention: lookAheadPrevention,
      risk_type: riskType,
      fixed_ratio_delta: riskType === "FIXED_RATIO" ? fixedRatioDelta : 500,
      size_by_sl: sizeBySl,
    });
  };

  const toggleSession = (session: string) => {
    setMarketSessions(prev =>
      prev.includes(session)
        ? prev.filter(s => s !== session)
        : [...prev, session]
    );
  };

  const selectedStrat = strategies.find((s) => s.id === selectedStrategy);
  const selectedDs = datasets.find((d) => d.id === selectedDataset);

  return (
    <div className="space-y-4">
      {/* CONFIGURACIÓN */}
      <div className="space-y-4">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-[var(--muted)]">
          Configuración
        </h2>

        {loadError && (
          <div className="flex items-center gap-2 bg-red-50 border border-red-200 rounded-md px-3 py-2">
            <span className="text-xs text-red-600 flex-1">Error al conectar con el servidor</span>
            <button
              onClick={loadData}
              className="text-xs font-medium text-red-700 underline hover:no-underline"
            >
              Reintentar
            </button>
          </div>
        )}

        <div className="space-y-3">
          <div>
            <label className="block text-xs font-medium mb-1 text-[var(--muted)]">
              Dataset
            </label>
            {loadingData ? (
              <div className="h-9 bg-gray-100 rounded animate-pulse" />
            ) : (
              <select
                value={selectedDataset}
                onChange={(e) => setSelectedDataset(e.target.value)}
                className="w-full border border-[var(--border)] rounded-md px-3 py-2 text-sm bg-[var(--card-muted-bg)] focus:outline-none focus:ring-2 focus:ring-[var(--accent)]"
              >
                {datasets.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.name} {d.pair_count > 0 ? `(${d.pair_count} pares)` : ""}
                  </option>
                ))}
              </select>
            )}
          </div>

          <div>
            <label className="block text-xs font-medium mb-1 text-[var(--muted)]">
              Estrategia
            </label>
            {loadingData ? (
              <div className="h-9 bg-gray-100 rounded animate-pulse" />
            ) : (
              <select
                value={selectedStrategy}
                onChange={(e) => setSelectedStrategy(e.target.value)}
                className="w-full border border-[var(--border)] rounded-md px-3 py-2 text-sm bg-[var(--card-muted-bg)] focus:outline-none focus:ring-2 focus:ring-[var(--accent)]"
              >
                {strategies.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
              </select>
            )}
            {selectedStrat?.description && (
              <p className="text-xs text-[var(--muted)] mt-1">{selectedStrat.description}</p>
            )}
          </div>

          <div className="grid grid-cols-2 gap-2 mb-2">
            <div>
              <label className="block text-xs font-medium mb-1 text-[var(--muted)]">
                Capital ($)
              </label>
              <input
                type="number"
                value={initCash}
                onChange={(e) => setInitCash(Number(e.target.value))}
                className="w-full border border-[var(--border)] rounded-md px-3 py-2 text-sm bg-[var(--card-muted-bg)] focus:outline-none focus:ring-2 focus:ring-[var(--accent)]"
              />
            </div>
            <div>
              <div className="flex items-center justify-between mb-1">
                <label className="block text-xs font-medium text-[var(--muted)] truncate pr-2">
                  Riesgo 1R
                </label>
                <select
                  value={riskType}
                  onChange={(e) => setRiskType(e.target.value as "FIXED" | "PERCENT" | "KELLY" | "FIXED_RATIO")}
                  className="text-[10px] bg-transparent text-[var(--muted)] hover:text-[var(--foreground)] outline-none cursor-pointer"
                >
                  <option value="FIXED">Fijo ($)</option>
                  <option value="PERCENT">% Eq</option>
                  <option value="KELLY">Kelly</option>
                  <option value="FIXED_RATIO">Fixed Ratio</option>
                </select>
              </div>
              <div className="flex gap-2">
                <input
                  type="number"
                  step={riskType === "PERCENT" ? "0.1" : "1"}
                  value={riskR}
                  onChange={(e) => setRiskR(Number(e.target.value))}
                  className="w-full border border-[var(--border)] rounded-md px-3 py-2 text-sm bg-[var(--card-muted-bg)] focus:outline-none focus:ring-2 focus:ring-[var(--accent)]"
                />
                {riskType === "FIXED_RATIO" && (
                  <input
                    type="number"
                    step="50"
                    placeholder="Delta ($)"
                    value={fixedRatioDelta}
                    onChange={(e) => setFixedRatioDelta(Number(e.target.value))}
                    title="Delta ($) requerido para +1 unidad de riesgo"
                    className="w-20 border border-[var(--border)] rounded-md px-2 py-2 text-sm bg-[var(--card-muted-bg)] focus:outline-none focus:ring-2 focus:ring-[var(--accent)]"
                  />
                )}
              </div>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-2">
            <div>
              <div className="flex items-center justify-between mb-1">
                <label className="block text-xs font-medium text-[var(--muted)]">
                  Fees {feeType === "PERCENT" ? "(%)" : "($)"}
                </label>
                <select
                  value={feeType}
                  onChange={(e) => setFeeType(e.target.value as "PERCENT" | "FLAT")}
                  className="text-[10px] bg-transparent text-[var(--muted)] hover:text-[var(--foreground)] outline-none cursor-pointer"
                >
                  <option value="PERCENT">%</option>
                  <option value="FLAT">$</option>
                </select>
              </div>
              <input
                type="number"
                step="0.01"
                value={fees}
                onChange={(e) => setFees(Number(e.target.value))}
                className="w-full border border-[var(--border)] rounded-md px-3 py-2 text-sm bg-[var(--card-muted-bg)] focus:outline-none focus:ring-2 focus:ring-[var(--accent)]"
              />
            </div>
            <div>
              <label className="block text-xs font-medium mb-1 text-[var(--muted)]">
                Slippage (%)
              </label>
              <input
                type="number"
                step="0.01"
                value={slippage}
                onChange={(e) => setSlippage(Number(e.target.value))}
                className="w-full border border-[var(--border)] rounded-md px-3 py-2 text-sm bg-[var(--card-muted-bg)] focus:outline-none focus:ring-2 focus:ring-[var(--accent)]"
              />
            </div>
          </div>

          <div className="pt-1 space-y-3">
            <div className="flex items-center justify-between">
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={useLocates}
                  onChange={() => setUseLocates(!useLocates)}
                  className="w-4 h-4 rounded border-[var(--border)] text-[var(--accent)] focus:ring-[var(--accent)]"
                />
                <span className="text-xs font-medium text-[var(--muted)]">Locates $/100</span>
              </label>
              {useLocates && (
                <input
                  type="number"
                  step="0.01"
                  value={locatesCost}
                  onChange={(e) => setLocatesCost(Number(e.target.value))}
                  className="w-20 border border-[var(--border)] rounded-md px-2 py-1 text-xs bg-[var(--card-muted-bg)] focus:outline-none focus:ring-2 focus:ring-[var(--accent)]"
                />
              )}
            </div>

            <div className="flex items-center justify-between">
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={useMonthlyExpenses}
                  onChange={() => setUseMonthlyExpenses(!useMonthlyExpenses)}
                  className="w-4 h-4 rounded border-[var(--border)] text-[var(--accent)] focus:ring-[var(--accent)]"
                />
                <span className="text-xs font-medium text-[var(--muted)]">Gastos fijos mensuales ($)</span>
              </label>
              {useMonthlyExpenses && (
                <input
                  type="number"
                  step="1"
                  value={monthlyExpenses}
                  onChange={(e) => setMonthlyExpenses(Number(e.target.value))}
                  className="w-20 border border-[var(--border)] rounded-md px-2 py-1 text-xs bg-[var(--card-muted-bg)] focus:outline-none focus:ring-2 focus:ring-[var(--accent)]"
                />
              )}
            </div>

            <div className="flex items-center justify-between pt-1">
              <div className="flex flex-col">
                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={sizeBySl}
                    onChange={() => setSizeBySl(!sizeBySl)}
                    className="w-4 h-4 rounded border-[var(--border)] text-[var(--accent)] focus:ring-[var(--accent)]"
                  />
                  <span className="text-xs font-medium text-[var(--muted)]">Size por Distancia al SL</span>
                </label>
                <span className="text-[10px] text-[var(--muted)] mt-1 ml-6 leading-tight">
                  Calcula nº Shares usando el Riesgo dividido por la distancia real al Stop Loss
                </span>
              </div>
            </div>

            <div className="flex items-center justify-between pt-2 mt-1 border-t border-[var(--border)]">
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={lookAheadPrevention}
                  onChange={() => setLookAheadPrevention(!lookAheadPrevention)}
                  className="w-4 h-4 rounded border-[var(--border)] text-[var(--accent)] focus:ring-[var(--accent)]"
                />
                <span className="text-xs font-medium text-[var(--muted)]">Look Ahead Prevention</span>
              </label>
              <span className="text-[10px] text-[var(--muted)]">
                {lookAheadPrevention ? "ON" : "OFF"}
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* RANGO DE FECHAS */}
      <div className="space-y-1.5">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-[var(--muted)]">
          Rango de fechas
        </h2>
        <div className="grid grid-cols-2 gap-2">
          <div>
            <label className="block text-[10px] font-medium mb-1 text-[var(--muted)]">
              Desde
            </label>
            <input
              type="date"
              value={startDate}
              min={selectedDs?.min_date}
              max={endDate || selectedDs?.max_date}
              onChange={(e) => setStartDate(e.target.value)}
              className="w-full border border-[var(--border)] rounded-md px-2 py-1.5 text-xs bg-[var(--card-muted-bg)] focus:outline-none focus:ring-2 focus:ring-[var(--accent)]"
            />
          </div>
          <div>
            <label className="block text-[10px] font-medium mb-1 text-[var(--muted)]">
              Hasta
            </label>
            <input
              type="date"
              value={endDate}
              min={startDate || selectedDs?.min_date}
              max={selectedDs?.max_date}
              onChange={(e) => setEndDate(e.target.value)}
              className="w-full border border-[var(--border)] rounded-md px-2 py-1.5 text-xs bg-[var(--card-muted-bg)] focus:outline-none focus:ring-2 focus:ring-[var(--accent)]"
            />
          </div>
        </div>
      </div>

      {/* SESIÓN DE MERCADO */}
      <div className="pt-1.5 space-y-1.5">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-[var(--muted)]">
          Sesión de mercado
        </h2>
        <div className="space-y-2">
          {[
            { id: "pre", label: "Pre-Market", time: "04:00 - 09:30 ET" },
            { id: "rth", label: "Regular Hours", time: "09:30 - 16:00 ET" },
            { id: "post", label: "After-Market", time: "16:00 - 20:00 ET" },
            { id: "custom", label: "Horas personalizadas (ET)", time: "" },
          ].map((session) => (
            <div key={session.id} className="space-y-2">
              <div className="flex items-center justify-between">
                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={marketSessions.includes(session.id)}
                    onChange={() => toggleSession(session.id)}
                    className="w-4 h-4 rounded border-[var(--border)] text-[var(--accent)] focus:ring-[var(--accent)]"
                  />
                  <span className="text-xs text-[var(--muted)]">{session.label}</span>
                </label>
                {session.time && (
                  <span className="text-[10px] text-[var(--muted)]">{session.time}</span>
                )}
              </div>

              {session.id === "custom" && marketSessions.includes("custom") && (
                <div className="grid grid-cols-2 gap-2 mt-2 pl-6">
                  <div>
                    <label className="block text-[10px] font-medium mb-1 text-[var(--muted)]">Desde</label>
                    <input
                      type="time"
                      value={customStartTime}
                      onChange={(e) => setCustomStartTime(e.target.value)}
                      className="w-full border border-[var(--border)] rounded-md px-2 py-1 text-[10px] bg-[var(--card-muted-bg)]"
                    />
                  </div>
                  <div>
                    <label className="block text-[10px] font-medium mb-1 text-[var(--muted)]">Hasta</label>
                    <input
                      type="time"
                      value={customEndTime}
                      onChange={(e) => setCustomEndTime(e.target.value)}
                      className="w-full border border-[var(--border)] rounded-md px-2 py-1 text-[10px] bg-[var(--card-muted-bg)]"
                    />
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      </div>

      <button
        onClick={handleRun}
        disabled={loading || !selectedDataset || !selectedStrategy}
        style={{
            background: 'var(--color-ec-copper)',
            color: 'var(--color-ec-copper-text)',
            border: 'none',
            borderRadius: 5,
            padding: '9px 16px',
            fontFamily: "'General Sans', sans-serif",
            fontSize: 11,
            fontWeight: 700,
            letterSpacing: '1.2px',
            textTransform: 'uppercase',
            cursor: 'pointer',
            width: '100%',
        }}
      >
        {loading ? (
          <span className="flex items-center justify-center gap-2">
            <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
            Ejecutando...
          </span>
        ) : (
          "Ejecutar Backtest"
        )}
      </button>
    </div>
  );
}
