"use client";

import { useEffect, useState } from "react";
import type { Dataset, Strategy, PrecacheStatus } from "@/lib/api_backtester";
import { fetchDatasets, fetchStrategies, fetchPrecacheStatus } from "@/lib/api_backtester";

export interface BacktestPanelParams {
  dataset_id: string;
  init_cash: number;
  risk_r: number;
  risk_type: string;
  fixed_ratio_delta: number;
  size_by_sl: boolean;
  fees: number;
  fee_type: string;
  slippage: number;
  start_date: string;
  end_date: string;
  market_sessions: string[];
  custom_start_time: string;
  custom_end_time: string;
  locates_cost: number;
  monthly_expenses: number;
  look_ahead_prevention: boolean;
}

interface BacktestPanelProps {
  refreshTrigger?: number;
  onNewStrategy: () => void;
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
  onParamsChange?: (params: BacktestPanelParams) => void;
  loading: boolean;
  isDarkMode?: boolean;
  onNewDataset: () => void;
  datasetRefreshTrigger?: number;
  pendingDatasetSelect?: string;
}

export default function BacktestPanel({
  refreshTrigger,
  onNewStrategy,
  onNewDataset,
  datasetRefreshTrigger,
  pendingDatasetSelect,
  onRun,
  onParamsChange,
  loading,
  isDarkMode = false
}: BacktestPanelProps) {
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
  const lookAheadPrevention = true;
  const [riskType, setRiskType] = useState<"FIXED" | "PERCENT" | "KELLY" | "FIXED_RATIO">("FIXED");
  const [fixedRatioDelta, setFixedRatioDelta] = useState(500);
  const [sizeBySl, setSizeBySl] = useState(false);
  const [feeType, setFeeType] = useState<"PERCENT" | "FLAT">("PERCENT");
  const [loadingData, setLoadingData] = useState(true);
  const [hoveredBtn, setHoveredBtn] = useState<string | null>(null);
  const [activeBtn, setActiveBtn] = useState<string | null>(null);
  const [loadError, setLoadError] = useState(false);
  const [precacheStatus, setPrecacheStatus] = useState<PrecacheStatus | null>(null);

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

  useEffect(() => {
    if (!refreshTrigger) return;
    fetchStrategies()
      .then((s) => setStrategies(s))
      .catch((e) => console.error("Error refreshing strategies:", e));
  }, [refreshTrigger]);

  useEffect(() => {
    if (!datasetRefreshTrigger) return;
    fetchDatasets()
      .then((d) => {
        setDatasets(d);
        if (pendingDatasetSelect) {
          setSelectedDataset(pendingDatasetSelect);
        }
      })
      .catch((e) => console.error("Error refreshing datasets:", e));
  }, [datasetRefreshTrigger, pendingDatasetSelect]);

  useEffect(() => {
    if (!selectedDataset) {
      setPrecacheStatus(null);
      return;
    }

    let isMounted = true;
    let timer: NodeJS.Timeout | null = null;

    const checkStatus = async () => {
      try {
        const statusData = await fetchPrecacheStatus(selectedDataset);
        if (!isMounted) return;

        setPrecacheStatus(statusData);

        if (statusData.status === "running") {
          timer = setTimeout(checkStatus, 1500);
        }
      } catch (err) {
        console.error("Error fetching precache status:", err);
        if (isMounted) {
          timer = setTimeout(checkStatus, 3000);
        }
      }
    };

    checkStatus();

    return () => {
      isMounted = false;
      if (timer) clearTimeout(timer);
    };
  }, [selectedDataset]);

  useEffect(() => {
    onParamsChange?.({
      dataset_id: selectedDataset,
      init_cash: initCash,
      risk_r: riskR,
      risk_type: riskType,
      fixed_ratio_delta: fixedRatioDelta,
      size_by_sl: sizeBySl,
      fees: feeType === "PERCENT" ? fees / 100 : fees,
      fee_type: feeType,
      slippage: slippage / 100,
      start_date: startDate,
      end_date: endDate,
      market_sessions: marketSessions,
      custom_start_time: customStartTime,
      custom_end_time: customEndTime,
      locates_cost: useLocates ? locatesCost : 0,
      monthly_expenses: useMonthlyExpenses ? monthlyExpenses : 0,
      look_ahead_prevention: lookAheadPrevention,
    });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    selectedDataset, initCash, riskR, riskType, fixedRatioDelta, sizeBySl,
    fees, feeType, slippage, startDate, endDate, marketSessions,
    customStartTime, customEndTime, useLocates, locatesCost,
    useMonthlyExpenses, monthlyExpenses, lookAheadPrevention,
  ]);

  const handleRun = () => {
    if (!selectedDataset || !selectedStrategy) return;
    if (precacheStatus?.status === "running") {
      alert(`Espera a que se cargue el dataset (progreso: ${precacheStatus.percent}%)`);
      return;
    }
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
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      gap: 16,
    }}>
      {/* CONFIGURACIÓN */}
      <h2 style={{
        fontFamily: 'var(--color-ec-sans)',
        fontSize: 14,
        fontWeight: 700,
        textTransform: 'uppercase',
        letterSpacing: '0.12em',
        color: 'var(--color-ec-text-high)',
        marginBottom: 4,
      }}>
        CONFIGURACIÓN
      </h2>

      {loadError && (
        <div className="flex items-center gap-2" style={{
          backgroundColor: 'color-mix(in srgb, var(--color-ec-loss) 10%, transparent)',
          border: '0.5px solid color-mix(in srgb, var(--color-ec-loss) 30%, transparent)',
          borderRadius: 5,
          padding: '8px 12px',
          marginBottom: 4,
        }}>
          <span style={{
            fontFamily: 'var(--color-ec-sans)',
            fontSize: 11,
            color: 'var(--color-ec-loss)',
            flex: 1,
          }}>Error al conectar con el servidor</span>
          <button
            onClick={loadData}
            className="text-xs font-medium underline hover:no-underline cursor-pointer"
            style={{ color: 'var(--color-ec-loss)' }}
          >
            Reintentar
          </button>
        </div>
      )}

      <div className="space-y-3">
        <div>
          <label style={{
            display: 'block',
            fontFamily: 'var(--color-ec-sans)',
            fontSize: 9,
            fontWeight: 700,
            textTransform: 'uppercase',
            letterSpacing: '0.12em',
            color: 'var(--color-ec-text-muted)',
            marginBottom: 5,
          }}>
            Cargar Dataset Guardado
          </label>
          {loadingData ? (
            <div className="h-9 bg-gray-100 rounded animate-pulse" />
          ) : (
            <select
              value={selectedDataset}
              onChange={(e) => setSelectedDataset(e.target.value)}
              style={{
                backgroundColor: 'var(--color-ec-bg-elevated)',
                border: '0.5px solid var(--color-ec-border)',
                borderRadius: 5,
                padding: '7px 10px',
                fontFamily: 'var(--color-ec-sans)',
                fontSize: 12,
                fontWeight: 500,
                color: 'var(--color-ec-text-primary)',
                outline: 'none',
                width: '100%',
                cursor: 'pointer',
              }}
            >
              {datasets.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.name} {d.pair_count > 0 ? `(${d.pair_count} pares)` : ""}
                </option>
              ))}
            </select>
          )}
          <button
            type="button"
            onClick={onNewDataset}
            onMouseEnter={() => setHoveredBtn("dataset")}
            onMouseLeave={() => { setHoveredBtn(null); setActiveBtn(null); }}
            onMouseDown={() => setActiveBtn("dataset")}
            onMouseUp={() => setActiveBtn(null)}
            style={{
              width: '100%',
              padding: '8px 0',
              borderRadius: 5,
              fontSize: 11,
              fontWeight: 700,
              letterSpacing: '1px',
              textTransform: 'uppercase',
              cursor: 'pointer',
              border: hoveredBtn === "dataset" ? '0.5px solid transparent' : '0.5px solid var(--color-ec-copper)',
              backgroundColor: hoveredBtn === "dataset" ? 'var(--color-ec-copper)' : 'transparent',
              color: hoveredBtn === "dataset" ? 'var(--color-ec-copper-text)' : 'var(--color-ec-copper)',
              fontFamily: 'var(--color-ec-sans)',
              marginTop: 6,
              marginBottom: 2,
              boxShadow: hoveredBtn === "dataset" ? '0 0 12px rgba(216, 122, 61, 0.35)' : 'none',
              transform: activeBtn === "dataset" ? 'scale(0.98)' : hoveredBtn === "dataset" ? 'scale(1.015)' : 'scale(1)',
              transition: 'all 150ms cubic-bezier(0.4, 0, 0.2, 1)',
            }}
          >
            + NUEVO DATASET
          </button>
          {precacheStatus && precacheStatus.status === "running" && (
            <div style={{
              marginTop: 8,
              padding: '8px 10px',
              backgroundColor: 'var(--color-ec-bg-elevated)',
              border: '0.5px solid var(--color-ec-border)',
              borderRadius: 5,
              display: 'flex',
              flexDirection: 'column',
              gap: 5,
            }}>
              <div style={{
                display: 'flex',
                justifyContent: 'space-between',
                fontFamily: 'var(--color-ec-sans)',
                fontSize: 9,
                fontWeight: 700,
                textTransform: 'uppercase',
                letterSpacing: '0.08em',
                color: 'var(--color-ec-copper)',
              }}>
                <span>Cargando dataset...</span>
                <span>{precacheStatus.percent}%</span>
              </div>
              <div style={{
                height: 4,
                backgroundColor: 'rgba(216, 122, 61, 0.15)',
                borderRadius: 2,
                overflow: 'hidden',
              }}>
                <div style={{
                  height: '100%',
                  width: `${precacheStatus.percent}%`,
                  backgroundColor: 'var(--color-ec-copper)',
                  borderRadius: 2,
                  transition: 'width 300ms cubic-bezier(0.4, 0, 0.2, 1)',
                }} />
              </div>
              <div style={{
                fontFamily: 'var(--color-ec-sans)',
                fontSize: 9,
                color: 'var(--color-ec-text-muted)',
                textAlign: 'right',
              }}>
                {precacheStatus.current} / {precacheStatus.total} pares
              </div>
            </div>
          )}
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 12 }}>
          <label style={{
            display: 'block',
            fontFamily: 'var(--color-ec-sans)',
            fontSize: 9,
            fontWeight: 700,
            textTransform: 'uppercase',
            letterSpacing: '0.12em',
            color: 'var(--color-ec-text-muted)',
          }}>
            cargar estrategia guardada
          </label>
          {loadingData ? (
            <div className="h-9 bg-gray-100 rounded animate-pulse" />
          ) : (
            <select
              value={selectedStrategy}
              onChange={(e) => setSelectedStrategy(e.target.value)}
              style={{
                backgroundColor: 'var(--color-ec-bg-elevated)',
                border: '0.5px solid var(--color-ec-border)',
                borderRadius: 5,
                padding: '7px 10px',
                fontFamily: 'var(--color-ec-sans)',
                fontSize: 12,
                fontWeight: 500,
                color: 'var(--color-ec-text-primary)',
                outline: 'none',
                width: '100%',
                cursor: 'pointer',
              }}
            >
              {strategies.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
          )}
          {selectedStrat?.description && (
            <span style={{
              fontFamily: 'var(--color-ec-sans)',
              fontSize: 10,
              color: 'var(--color-ec-text-secondary)',
              fontStyle: 'italic',
              marginTop: 4,
              lineHeight: '1.3',
              display: 'block',
            }}>{selectedStrat.description}</span>
          )}
          
          <button
            type="button"
            onClick={onNewStrategy}
            onMouseEnter={() => setHoveredBtn("strategy")}
            onMouseLeave={() => { setHoveredBtn(null); setActiveBtn(null); }}
            onMouseDown={() => setActiveBtn("strategy")}
            onMouseUp={() => setActiveBtn(null)}
            style={{
              width: '100%',
              padding: '8px 0',
              borderRadius: 5,
              fontSize: 11,
              fontWeight: 700,
              letterSpacing: '1px',
              textTransform: 'uppercase',
              cursor: 'pointer',
              border: hoveredBtn === "strategy" ? '0.5px solid transparent' : '0.5px solid var(--color-ec-copper)',
              backgroundColor: hoveredBtn === "strategy" ? 'var(--color-ec-copper)' : 'transparent',
              color: hoveredBtn === "strategy" ? 'var(--color-ec-copper-text)' : 'var(--color-ec-copper)',
              fontFamily: 'var(--color-ec-sans)',
              marginTop: 4,
              marginBottom: 8,
              boxShadow: hoveredBtn === "strategy" ? '0 0 12px rgba(216, 122, 61, 0.35)' : 'none',
              transform: activeBtn === "strategy" ? 'scale(0.98)' : hoveredBtn === "strategy" ? 'scale(1.015)' : 'scale(1)',
              transition: 'all 150ms cubic-bezier(0.4, 0, 0.2, 1)',
            }}
          >
            + Nueva Estrategia
          </button>
        </div>

        <div style={{
          display: 'grid',
          gridTemplateColumns: '1fr 1fr',
          gap: 8,
          marginBottom: 8,
        }}>
          <div>
            <label style={{
              display: 'block',
              fontFamily: 'var(--color-ec-sans)',
              fontSize: 9,
              fontWeight: 700,
              textTransform: 'uppercase',
              letterSpacing: '0.12em',
              color: 'var(--color-ec-text-muted)',
              marginBottom: 5,
            }}>
              Capital ($)
            </label>
            <input
              type="number"
              value={initCash}
              onChange={(e) => setInitCash(Number(e.target.value))}
              style={{
                backgroundColor: 'var(--color-ec-bg-elevated)',
                border: '0.5px solid var(--color-ec-border)',
                borderRadius: 5,
                padding: '7px 10px',
                fontFamily: 'var(--color-ec-sans)',
                fontSize: 12,
                fontWeight: 500,
                color: 'var(--color-ec-text-primary)',
                outline: 'none',
                width: '100%',
              }}
            />
          </div>
          <div>
            <div style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              marginBottom: 5,
            }}>
              <label style={{
                display: 'block',
                fontFamily: 'var(--color-ec-sans)',
                fontSize: 9,
                fontWeight: 700,
                textTransform: 'uppercase',
                letterSpacing: '0.12em',
                color: 'var(--color-ec-text-muted)',
              }}>
                1R
              </label>
              <select
                value={riskType}
                onChange={(e) => setRiskType(e.target.value as "FIXED" | "PERCENT" | "KELLY")}
                style={{
                  backgroundColor: 'transparent',
                  border: 'none',
                  outline: 'none',
                  fontFamily: 'var(--color-ec-sans)',
                  fontSize: 9,
                  fontWeight: 600,
                  color: 'var(--color-ec-copper)',
                  cursor: 'pointer',
                }}
              >
                <option value="FIXED">Fijo ($)</option>
                <option value="PERCENT">% Eq</option>
                <option value="KELLY">Kelly</option>
              </select>
            </div>
            <div className="flex gap-2">
              <input
                type="number"
                step={riskType === "PERCENT" ? "0.1" : "1"}
                value={riskR}
                onChange={(e) => setRiskR(Number(e.target.value))}
                style={{
                  backgroundColor: 'var(--color-ec-bg-elevated)',
                  border: '0.5px solid var(--color-ec-border)',
                  borderRadius: 5,
                  padding: '7px 10px',
                  fontFamily: 'var(--color-ec-sans)',
                  fontSize: 12,
                  fontWeight: 500,
                  color: 'var(--color-ec-text-primary)',
                  outline: 'none',
                  width: '100%',
                }}
              />
            </div>
          </div>
        </div>

        <div style={{
          display: 'grid',
          gridTemplateColumns: '1fr 1fr',
          gap: 8,
        }}>
          <div>
            <div style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              marginBottom: 5,
            }}>
              <label style={{
                display: 'block',
                fontFamily: 'var(--color-ec-sans)',
                fontSize: 9,
                fontWeight: 700,
                textTransform: 'uppercase',
                letterSpacing: '0.12em',
                color: 'var(--color-ec-text-muted)',
              }}>
                Fees {feeType === "PERCENT" ? "(%)" : "($)"}
              </label>
              <select
                value={feeType}
                onChange={(e) => setFeeType(e.target.value as "PERCENT" | "FLAT")}
                style={{
                  backgroundColor: 'transparent',
                  border: 'none',
                  outline: 'none',
                  fontFamily: 'var(--color-ec-sans)',
                  fontSize: 9,
                  fontWeight: 600,
                  color: 'var(--color-ec-copper)',
                  cursor: 'pointer',
                }}
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
              style={{
                backgroundColor: 'var(--color-ec-bg-elevated)',
                border: '0.5px solid var(--color-ec-border)',
                borderRadius: 5,
                padding: '7px 10px',
                fontFamily: 'var(--color-ec-sans)',
                fontSize: 12,
                fontWeight: 500,
                color: 'var(--color-ec-text-primary)',
                outline: 'none',
                width: '100%',
              }}
            />
          </div>
          <div>
            <label style={{
              display: 'block',
              fontFamily: 'var(--color-ec-sans)',
              fontSize: 9,
              fontWeight: 700,
              textTransform: 'uppercase',
              letterSpacing: '0.12em',
              color: 'var(--color-ec-text-muted)',
              marginBottom: 5,
            }}>
              Slippage (%)
            </label>
            <input
              type="number"
              step="0.01"
              value={slippage}
              onChange={(e) => setSlippage(Number(e.target.value))}
              style={{
                backgroundColor: 'var(--color-ec-bg-elevated)',
                border: '0.5px solid var(--color-ec-border)',
                borderRadius: 5,
                padding: '7px 10px',
                fontFamily: 'var(--color-ec-sans)',
                fontSize: 12,
                fontWeight: 500,
                color: 'var(--color-ec-text-primary)',
                outline: 'none',
                width: '100%',
              }}
            />
          </div>
        </div>

        <div style={{
          display: 'flex',
          flexDirection: 'column',
          gap: 8,
          paddingTop: 16,
          marginTop: 12,
          borderTop: '0.5px solid var(--color-ec-border)',
        }}>
          <div style={{
            display: 'flex',
            alignItems: 'center',
            gap: 8,
          }}>
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={useLocates}
                onChange={() => setUseLocates(!useLocates)}
                className="w-4 h-4 rounded border-[var(--border)] text-[var(--accent)] focus:ring-[var(--accent)]"
              />
              <span style={{
                fontFamily: 'var(--color-ec-sans)',
                fontSize: 11,
                fontWeight: 500,
                color: 'var(--color-ec-text-secondary)',
              }}>Locates estimados $/100</span>
            </label>
            {useLocates && (
              <input
                type="number"
                step="0.01"
                value={locatesCost}
                onChange={(e) => setLocatesCost(Number(e.target.value))}
                className="w-20 border border-[var(--color-ec-border)]"
                style={{
                  backgroundColor: 'var(--color-ec-bg-elevated)',
                  borderRadius: 5,
                  padding: '6px 8px',
                  fontFamily: 'var(--color-ec-sans)',
                  fontSize: 11,
                  color: 'var(--color-ec-text-primary)',
                  outline: 'none',
                }}
              />
            )}
          </div>

          <div style={{
            display: 'flex',
            alignItems: 'center',
            gap: 8,
          }}>
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={useMonthlyExpenses}
                onChange={() => setUseMonthlyExpenses(!useMonthlyExpenses)}
                className="w-4 h-4 rounded border-[var(--border)] text-[var(--accent)] focus:ring-[var(--accent)]"
              />
              <span style={{
                fontFamily: 'var(--color-ec-sans)',
                fontSize: 11,
                fontWeight: 500,
                color: 'var(--color-ec-text-secondary)',
              }}>Gastos fijos mensuales ($)</span>
            </label>
            {useMonthlyExpenses && (
              <input
                type="number"
                step="1"
                value={monthlyExpenses}
                onChange={(e) => setMonthlyExpenses(Number(e.target.value))}
                className="w-20 border border-[var(--color-ec-border)]"
                style={{
                  backgroundColor: 'var(--color-ec-bg-elevated)',
                  borderRadius: 5,
                  padding: '6px 8px',
                  fontFamily: 'var(--color-ec-sans)',
                  fontSize: 11,
                  color: 'var(--color-ec-text-primary)',
                  outline: 'none',
                }}
              />
            )}
          </div>

          <div style={{
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            paddingTop: 4,
          }}>
            <div className="flex flex-col">
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={sizeBySl}
                  onChange={() => setSizeBySl(!sizeBySl)}
                  className="w-4 h-4 rounded border-[var(--border)] text-[var(--accent)] focus:ring-[var(--accent)]"
                />
                <span style={{
                  fontFamily: 'var(--color-ec-sans)',
                  fontSize: 11,
                  fontWeight: 500,
                  color: 'var(--color-ec-text-secondary)',
                }}>Size por Distancia al SL</span>
              </label>
              <span style={{
                fontFamily: 'var(--color-ec-sans)',
                fontSize: 10,
                color: 'var(--color-ec-text-secondary)',
                fontStyle: 'italic',
                marginLeft: 24,
                marginTop: 4,
                lineHeight: '1.3',
              }}>
                Calcula nº Shares usando el Riesgo dividido por la distancia real al Stop Loss
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* RANGO DE FECHAS */}
      <div style={{
        display: 'flex',
        flexDirection: 'column',
        gap: 6,
        paddingTop: 16,
        borderTop: '0.5px solid var(--color-ec-border)',
      }}>
        <h2 style={{
          fontFamily: 'var(--color-ec-sans)',
          fontSize: 9,
          fontWeight: 700,
          textTransform: 'uppercase',
          letterSpacing: '0.15em',
          color: 'var(--color-ec-text-muted)',
          marginBottom: 4,
        }}>
          Rango de fechas IS-OOS
        </h2>
        <div style={{
          display: 'grid',
          gridTemplateColumns: '1fr 1fr',
          gap: 8,
        }}>
          <div>
            <label style={{
              display: 'block',
              fontFamily: 'var(--color-ec-sans)',
              fontSize: 9,
              fontWeight: 700,
              textTransform: 'uppercase',
              letterSpacing: '0.12em',
              color: 'var(--color-ec-text-muted)',
              marginBottom: 5,
            }}>
              Desde
            </label>
            <input
              type="date"
              value={startDate}
              min={selectedDs?.min_date || "2020-01-01"}
              max={endDate || selectedDs?.max_date || "2030-12-31"}
              onChange={(e) => setStartDate(e.target.value)}
              className="w-full border border-[var(--border)]"
              style={{
                backgroundColor: 'var(--color-ec-bg-elevated)',
                borderRadius: 5,
                padding: '6px 8px',
                fontFamily: 'var(--color-ec-sans)',
                fontSize: 11,
                fontWeight: 400,
                color: 'var(--color-ec-text-primary)',
                outline: 'none',
                width: '100%',
              }}
            />
          </div>
          <div>
            <label style={{
              display: 'block',
              fontFamily: 'var(--color-ec-sans)',
              fontSize: 9,
              fontWeight: 700,
              textTransform: 'uppercase',
              letterSpacing: '0.12em',
              color: 'var(--color-ec-text-muted)',
              marginBottom: 5,
            }}>
              Hasta
            </label>
            <input
              type="date"
              value={endDate}
              min={startDate || selectedDs?.min_date || "2020-01-01"}
              max={selectedDs?.max_date || "2030-12-31"}
              onChange={(e) => setEndDate(e.target.value)}
              className="w-full border border-[var(--border)]"
              style={{
                backgroundColor: 'var(--color-ec-bg-elevated)',
                borderRadius: 5,
                padding: '6px 8px',
                fontFamily: 'var(--color-ec-sans)',
                fontSize: 11,
                fontWeight: 400,
                color: 'var(--color-ec-text-primary)',
                outline: 'none',
                width: '100%',
              }}
            />
          </div>
        </div>
      </div>

      {/* SESIÓN DE MERCADO */}
      <div style={{
        display: 'flex',
        flexDirection: 'column',
        gap: 6,
        paddingTop: 16,
        borderTop: '0.5px solid var(--color-ec-border)',
      }}>
        <h2 style={{
          fontFamily: 'var(--color-ec-sans)',
          fontSize: 9,
          fontWeight: 700,
          textTransform: 'uppercase',
          letterSpacing: '0.15em',
          color: 'var(--color-ec-text-muted)',
          marginBottom: 4,
        }}>
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
              <div style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                gap: 8,
              }}>
                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={marketSessions.includes(session.id)}
                    onChange={() => toggleSession(session.id)}
                    className="w-4 h-4 rounded border-[var(--border)] text-[var(--accent)] focus:ring-[var(--accent)]"
                  />
                  <span style={{
                    fontFamily: 'var(--color-ec-sans)',
                    fontSize: 11,
                    fontWeight: 500,
                    color: 'var(--color-ec-text-secondary)',
                  }}>{session.label}</span>
                </label>
                {session.time && (
                  <span style={{
                    fontFamily: 'var(--color-ec-sans)',
                    fontSize: 10,
                    fontWeight: 400,
                    color: 'var(--color-ec-text-muted)',
                  }}>{session.time}</span>
                )}
              </div>

              {session.id === "custom" && marketSessions.includes("custom") && (
                <div className="grid grid-cols-2 gap-2 mt-3 pl-6">
                  <div>
                    <label style={{
                      display: "block",
                      fontFamily: "var(--color-ec-sans)",
                      fontSize: 11,
                      fontWeight: 500,
                      color: "var(--color-ec-text-secondary)",
                      fontStyle: "italic",
                      marginBottom: 4,
                    }}>Desde</label>
                    <input
                      type="time"
                      value={customStartTime}
                      onChange={(e) => setCustomStartTime(e.target.value)}
                      style={{
                        backgroundColor: 'var(--color-ec-bg-elevated)',
                        border: '0.5px solid var(--color-ec-border)',
                        borderRadius: 5,
                        padding: '6px 10px',
                        fontFamily: 'var(--color-ec-sans)',
                        fontSize: 11,
                        fontWeight: 500,
                        color: 'var(--color-ec-text-primary)',
                        outline: 'none',
                        width: '100%',
                      }}
                    />
                  </div>
                  <div>
                    <label style={{
                      display: "block",
                      fontFamily: "var(--color-ec-sans)",
                      fontSize: 11,
                      fontWeight: 500,
                      color: "var(--color-ec-text-secondary)",
                      fontStyle: "italic",
                      marginBottom: 4,
                    }}>Hasta</label>
                    <input
                      type="time"
                      value={customEndTime}
                      onChange={(e) => setCustomEndTime(e.target.value)}
                      style={{
                        backgroundColor: 'var(--color-ec-bg-elevated)',
                        border: '0.5px solid var(--color-ec-border)',
                        borderRadius: 5,
                        padding: '6px 10px',
                        fontFamily: 'var(--color-ec-sans)',
                        fontSize: 11,
                        fontWeight: 500,
                        color: 'var(--color-ec-text-primary)',
                        outline: 'none',
                        width: '100%',
                      }}
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
        onMouseEnter={() => setHoveredBtn("run")}
        onMouseLeave={() => { setHoveredBtn(null); setActiveBtn(null); }}
        onMouseDown={() => setActiveBtn("run")}
        onMouseUp={() => setActiveBtn(null)}
        style={{
            backgroundColor: 'var(--color-ec-copper)',
            color: 'var(--color-ec-copper-text)',
            border: 'none',
            borderRadius: 5,
            padding: '9px 16px',
            fontFamily: "'General Sans', sans-serif",
            fontSize: 11,
            fontWeight: 700,
            letterSpacing: '1.2px',
            textTransform: 'uppercase',
            cursor: loading || !selectedDataset || !selectedStrategy ? 'not-allowed' : 'pointer',
            width: '100%',
            marginTop: 8,
            opacity: loading || !selectedDataset || !selectedStrategy ? 0.5 : 1,
            boxShadow: hoveredBtn === "run" && !loading && selectedDataset && selectedStrategy ? '0 0 14px rgba(216, 122, 61, 0.5)' : 'none',
            transform: activeBtn === "run" && !loading && selectedDataset && selectedStrategy ? 'scale(0.98)' : hoveredBtn === "run" && !loading && selectedDataset && selectedStrategy ? 'scale(1.015)' : 'scale(1)',
            transition: 'all 150ms cubic-bezier(0.4, 0, 0.2, 1)',
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
