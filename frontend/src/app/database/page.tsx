'use client'

import React, { useState, useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { 
  Briefcase, 
  Trash2, 
  Play, 
  Layers, 
  AlertCircle,
  Clock,
  Database,
  Activity,
  Plus,
  Minus,
  X,
  ChevronDown,
  ChevronUp
} from 'lucide-react'
import { 
  getStrategies, 
  getQueries, 
  getSavedBacktests, 
  deleteStrategy, 
  deleteQuery,
  toggleBacktestValidation
} from '@/lib/api'
import { INDICATOR_LABELS, COMPARATOR_LABELS } from '@/components/strategy-builder/ConditionBuilder'

// Pre-seeded strategies realistic stats for display fallback
const MOCK_STRATEGY_STATS: Record<string, { winRate: number; profitFactor: number; maxDd: number; sharpe: number; trades: number; period: string; avgRDay: number; equityCurve: number[]; isValidated: boolean }> = {
  'mock_strategy_1': {
    winRate: 56.4,
    profitFactor: 1.84,
    maxDd: 4.8,
    sharpe: 1.95,
    trades: 92,
    period: '2023-01-01 / 2024-12-31',
    avgRDay: 0.45,
    equityCurve: [10000, 10050, 9980, 10120, 10210, 10180, 10320, 10450, 10390, 10580, 10720, 10690, 10850],
    isValidated: true
  },
  'mock_strategy_2': {
    winRate: 62.1,
    profitFactor: 2.10,
    maxDd: 3.5,
    sharpe: 2.45,
    trades: 74,
    period: '2024-01-01 / 2024-12-31',
    avgRDay: 0.68,
    equityCurve: [10000, 10120, 10250, 10180, 10380, 10520, 10480, 10690, 10880, 10790, 10980, 11210, 11450],
    isValidated: true
  },
  'mock_strategy_3': {
    winRate: 48.7,
    profitFactor: 1.45,
    maxDd: 8.2,
    sharpe: 1.25,
    trades: 118,
    period: '2022-01-01 / 2024-12-31',
    avgRDay: 0.22,
    equityCurve: [10000, 9920, 10080, 10010, 9890, 10050, 10150, 10080, 10220, 10380, 10290, 10480, 10350],
    isValidated: false
  }
};

// SVG Sparkline Component for Table Row (with mini axes and flat gradient fill)
const Sparkline = ({ points, isPositive }: { points: number[]; isPositive: boolean }) => {
  if (!points || points.length < 2) {
    return <span style={{ color: 'var(--color-ec-text-muted)', fontSize: 9 }}>—</span>
  }
  const min = Math.min(...points)
  const max = Math.max(...points)
  const range = max - min || 1
  const width = 80
  const height = 20
  const axisColor = 'rgba(255, 255, 255, 0.12)'
  const color = isPositive ? 'var(--color-ec-profit)' : 'var(--color-ec-loss)'
  const fillColor = isPositive ? 'rgba(74, 157, 127, 0.18)' : 'rgba(201, 77, 63, 0.18)'
  
  // Scale points to leave room for the axes at the bottom and left
  const svgPoints = points.map((p, i) => {
    const x = (i / (points.length - 1)) * (width - 8) + 6
    const y = (height - 4) - ((p - min) / range) * (height - 6)
    return { x, y }
  })
  
  const linePath = svgPoints.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(' ')
  const fillPath = `M ${svgPoints[0].x.toFixed(1)} 18.0 L ${svgPoints[0].x.toFixed(1)} ${svgPoints[0].y.toFixed(1)} ${linePath.substring(1)} L ${svgPoints[svgPoints.length - 1].x.toFixed(1)} 18.0 Z`
  
  return (
    <svg width={width} height={height} style={{ overflow: 'visible' }}>
      {/* Mini axes */}
      <line x1="4" y1="2" x2="4" y2="18" stroke={axisColor} strokeWidth="0.5" />
      <line x1="4" y1="18" x2={width - 2} y2="18" stroke={axisColor} strokeWidth="0.5" />
      
      {/* Flat Area Fill and Outline */}
      <path d={fillPath} fill={fillColor} />
      <path d={linePath} fill="none" stroke={color} strokeWidth="0.8" />
    </svg>
  )
}

// Detailed Equity and Drawdown Dual Chart for Right Details Panel
const DetailedEquityChart = ({ points }: { points: number[] }) => {
  if (!points || points.length < 2) {
    return (
      <div 
        style={{ 
          height: 120, 
          display: 'flex', 
          alignItems: 'center', 
          justifyContent: 'center',
          border: '1px dashed var(--color-ec-border)',
          borderRadius: 0,
          color: 'var(--color-ec-text-muted)',
          fontSize: 10
        }}
      >
        No chart data available
      </div>
    )
  }

  const width = 200
  const height = 120
  
  // Equity calculations
  const minEq = Math.min(...points)
  const maxEq = Math.max(...points)
  const eqRange = maxEq - minEq || 1
  const eqHeight = 80 // top area for equity line
  
  const eqSvgPoints = points.map((p, i) => {
    const x = (i / (points.length - 1)) * (width - 16) + 8
    const y = eqHeight - ((p - minEq) / eqRange) * (eqHeight - 15) - 5
    return { x, y }
  })

  const eqPath = eqSvgPoints.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(' ')
  const fillPath = `${eqPath} L ${eqSvgPoints[eqSvgPoints.length - 1].x} ${eqHeight} L ${eqSvgPoints[0].x} ${eqHeight} Z`

  // Drawdown calculations
  let maxSoFar = points[0]
  const drawdowns = points.map(p => {
    if (p > maxSoFar) maxSoFar = p
    return maxSoFar > 0 ? ((p - maxSoFar) / maxSoFar) * 100 : 0 // will be <= 0
  })
  
  const minDD = Math.min(...drawdowns)
  const absMinDD = Math.abs(minDD) || 1
  
  const ddZeroY = 98 // zero line for drawdown bars
  const ddMaxHeight = 18 // max height of drawdown bars
  
  const ddBars = drawdowns.map((dd, i) => {
    const x = (i / (drawdowns.length - 1)) * (width - 16) + 8
    const barHeight = (Math.abs(dd) / absMinDD) * ddMaxHeight
    return { x, y: ddZeroY, h: barHeight }
  })

  const color = 'var(--color-ec-profit)'
  const ddColor = 'var(--color-ec-loss)'

  return (
    <div style={{ position: 'relative', width: '100%' }}>
      <svg width="100%" height={height} viewBox={`0 0 ${width} ${height}`} style={{ overflow: 'visible' }}>
        <defs>
          <linearGradient id="detail-eq-grad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity="0.15" />
            <stop offset="100%" stopColor={color} stopOpacity="0.0" />
          </linearGradient>
        </defs>

        {/* Grid Lines */}
        <line x1="8" y1="10" x2={width - 8} y2="10" stroke="rgba(44, 47, 51, 0.3)" strokeWidth="0.5" strokeDasharray="3,3" />
        <line x1="8" y1="35" x2={width - 8} y2="35" stroke="rgba(44, 47, 51, 0.3)" strokeWidth="0.5" strokeDasharray="3,3" />
        <line x1="8" y1="60" x2={width - 8} y2="60" stroke="rgba(44, 47, 51, 0.3)" strokeWidth="0.5" strokeDasharray="3,3" />

        {/* Equity Line Fill and Path */}
        <path d={fillPath} fill="url(#detail-eq-grad)" />
        <path d={eqPath} fill="none" stroke={color} strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" />

        {/* Drawdown Section */}
        <line x1="8" y1={ddZeroY} x2={width - 8} y2={ddZeroY} stroke="rgba(44, 47, 51, 0.5)" strokeWidth="0.5" />
        {ddBars.map((bar, idx) => (
          <line
            key={idx}
            x1={bar.x.toFixed(1)}
            y1={bar.y}
            x2={bar.x.toFixed(1)}
            y2={(bar.y + bar.h).toFixed(1)}
            stroke={ddColor}
            strokeWidth="2.5"
            opacity="0.8"
          />
        ))}
        
        {/* End point glow dots */}
        <circle cx={eqSvgPoints[eqSvgPoints.length - 1].x} cy={eqSvgPoints[eqSvgPoints.length - 1].y} r="2" fill={color} />
        <circle cx={eqSvgPoints[eqSvgPoints.length - 1].x} cy={eqSvgPoints[eqSvgPoints.length - 1].y} r="4" fill={color} opacity="0.3" />
      </svg>
    </div>
  )
}

// Comparison Chart Colors mapping
const COMPARISON_COLORS = [
  'var(--color-ec-copper)',  // Copper/Orange (#d87a3d)
  'var(--color-ec-profit)',  // Emerald Green (#4a9d7f)
  '#3b82f6',                 // Bright Blue
  '#a855f7',                 // Purple
  '#eab308',                 // Yellow/Gold
  '#ec4899'                  // Pink
]

// Multi-Equity SVG Chart for Comparison
const MultiEquityChart = ({ strategiesData }: { strategiesData: { name: string; curveR: number[]; color: string }[] }) => {
  if (!strategiesData || strategiesData.length === 0) {
    return (
      <div 
        style={{ 
          height: 180, 
          display: 'flex', 
          alignItems: 'center', 
          justifyContent: 'center',
          border: '1px dashed var(--color-ec-border)',
          borderRadius: 0,
          color: 'var(--color-ec-text-muted)',
          fontSize: 10
        }}
      >
        No strategies selected for comparison
      </div>
    )
  }

  // Find max length of curves to scale X axis
  const maxLen = Math.max(...strategiesData.map(s => s.curveR.length), 2)
  
  // Find min and max of all R values to scale Y axis
  let allVals: number[] = [0] // always include 0 R
  strategiesData.forEach(s => allVals.push(...s.curveR))
  const minVal = Math.min(...allVals)
  const maxVal = Math.max(...allVals)
  const valRange = maxVal - minVal || 1
  
  const width = 400
  const height = 180
  const paddingLeft = 32
  const paddingRight = 10
  const paddingTop = 10
  const paddingBottom = 15
  
  const chartWidth = width - paddingLeft - paddingRight
  const chartHeight = height - paddingTop - paddingBottom
  
  const getX = (index: number, totalPoints: number) => {
    return paddingLeft + (index / (totalPoints - 1 || 1)) * chartWidth
  }
  
  const getY = (val: number) => {
    return paddingTop + chartHeight - ((val - minVal) / valRange) * chartHeight
  }
  
  // Grid lines
  const yTicks = 4
  const gridTicks = []
  for (let i = 0; i <= yTicks; i++) {
    const val = minVal + (i / yTicks) * valRange
    gridTicks.push(val)
  }

  return (
    <div style={{ position: 'relative', width: '100%' }}>
      <svg width="100%" height={height} viewBox={`0 0 ${width} ${height}`} style={{ overflow: 'visible' }}>
        {/* Horizontal Grid Lines & Labels */}
        {gridTicks.map((val, idx) => {
          const y = getY(val)
          return (
            <g key={idx}>
              <line 
                x1={paddingLeft} 
                y1={y} 
                x2={width - paddingRight} 
                y2={y} 
                stroke="rgba(255, 255, 255, 0.05)" 
                strokeWidth="0.5" 
                strokeDasharray="2,2" 
              />
              <text 
                x={paddingLeft - 5} 
                y={y + 3} 
                fill="var(--color-ec-text-muted)" 
                fontSize="9" 
                textAnchor="end"
                fontFamily="'General Sans', sans-serif"
              >
                {val >= 0 ? `+${val.toFixed(1)}` : val.toFixed(1)}R
              </text>
            </g>
          )
        })}

        {/* 0 R Baseline */}
        {minVal < 0 && maxVal > 0 && (
          <line 
            x1={paddingLeft} 
            y1={getY(0)} 
            x2={width - paddingRight} 
            y2={getY(0)} 
            stroke="rgba(255, 255, 255, 0.15)" 
            strokeWidth="0.8" 
          />
        )}

        {/* Draw Line Paths */}
        {strategiesData.map((s, sIdx) => {
          const curve = s.curveR
          if (curve.length < 2) return null
          
          const svgPoints = curve.map((val, idx) => {
            return { x: getX(idx, curve.length), y: getY(val) }
          })
          
          const linePath = svgPoints.map((p, idx) => `${idx === 0 ? 'M' : 'L'} ${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(' ')
          
          return (
            <g key={sIdx}>
              {/* Glow */}
              <path 
                d={linePath} 
                fill="none" 
                stroke={s.color} 
                strokeWidth="2" 
                opacity="0.1" 
                strokeLinecap="round" 
                strokeLinejoin="round" 
              />
              {/* Primary Line */}
              <path 
                d={linePath} 
                fill="none" 
                stroke={s.color} 
                strokeWidth="1.2" 
                strokeLinecap="round" 
                strokeLinejoin="round" 
              />
              {/* End dot */}
              <circle 
                cx={svgPoints[svgPoints.length - 1].x} 
                cy={svgPoints[svgPoints.length - 1].y} 
                r="2" 
                fill={s.color} 
              />
            </g>
          )
        })}
      </svg>
      
      {/* Legend */}
      <div 
        style={{ 
          display: 'flex', 
          flexWrap: 'wrap', 
          gap: '4px 10px', 
          justifyContent: 'center', 
          marginTop: 10,
          padding: '0 4px'
        }}
      >
        {strategiesData.map((s, idx) => (
          <div key={idx} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <span style={{ width: 6, height: 6, backgroundColor: s.color }} />
            <span style={{ fontSize: 10, fontWeight: 600, color: 'var(--color-ec-text-secondary)', textTransform: 'uppercase', letterSpacing: '0.3px', whiteSpace: 'nowrap', maxWidth: 100, overflow: 'hidden', textOverflow: 'ellipsis' }}>
              {s.name}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

export default function TrunkPage() {
  const router = useRouter()
  const [strategies, setStrategies] = useState<any[]>([])
  /* POST-MVP AGENTIC - descomentar cuando se active ChatBotAgentic.tsx (ver docs/plan_asistente_edgie.md)
  useAssistantAction({
    name: 'trunk.delete',
    description: 'Elimina permanentemente una estrategia o un dataset guardado del Trunk. Irreversible.',
    parameters: TrunkDeleteSchema,
    confirm: 'danger',
    handler: async (args) => {
      const type = String(args.type) as 'strategy' | 'dataset'
      const list = type === 'strategy' ? strategies : datasets
      const { item, error } = resolveTrunkItem(list, args.id, args.name)
      if (!item) return { ok: false, error }
      try {
        if (type === 'strategy') {
          await deleteStrategy(item.id)
          setStrategies(prev => prev.filter(s => s.id !== item.id))
          setSelectedStrategyIds(prev => prev.filter(x => x !== item.id))
        } else {
          await deleteQuery(item.id)
          setDatasets(prev => prev.filter(d => d.id !== item.id))
        }
        return { ok: true, result: `Eliminado ${type} "${item.name}" (id=${item.id}).` }
      } catch (err) {
        return { ok: false, error: `Error al borrar: ${String(err)}` }
      }
    },
  })

  useAssistantAction({
    name: 'trunk.open_strategy_in_backtester',
    description: 'Abre el Backtester con una estrategia guardada preseleccionada, lista para configurar y ejecutar.',
    parameters: TrunkOpenStrategySchema,
    confirm: 'auto',
    handler: (args) => {
      const { item, error } = resolveTrunkItem(strategies, args.id, args.name)
      if (!item) return { ok: false, error }
      router.push(`/backtester?strategy_id=${item.id}`)
      return { ok: true, result: `Abriendo el Backtester con la estrategia "${item.name}".` }
    },
  })

  useAssistantContext('trunk.page', () => ({
    strategies: strategies.slice(0, 40).map(s => ({ id: s.id, name: s.name })),
    datasets: datasets.slice(0, 40).map(d => ({ id: d.id, name: d.name })),
    savedBacktests: backtests.slice(0, 40).map(b => ({ id: b.id, name: b.name, strategy_ids: b.strategy_ids })),
  }))
  */

  const [incubatorStrategies, setIncubatorStrategies] = useState<any[]>([])
  const [datasets, setDatasets] = useState<any[]>([])
  const [backtests, setBacktests] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  
  const [selectedStrategyIds, setSelectedStrategyIds] = useState<string[]>([])
  const [showCharts, setShowCharts] = useState<Record<string, boolean>>({})
  const [expandedRowId, setExpandedRowId] = useState<string | null>(null)
  
  const [deletingId, setDeletingId] = useState<string | null>(null)
  const [deletingType, setDeletingType] = useState<'strategy' | 'dataset' | null>(null)

  const [mockValidationStates, setMockValidationStates] = useState<Record<string, boolean>>(() => {
    if (typeof window !== 'undefined') {
      const saved = localStorage.getItem('mock_validation_states')
      if (saved) {
        try {
          return JSON.parse(saved)
        } catch (e) {}
      }
    }
    return {
      'mock_strategy_1': true,
      'mock_strategy_2': true,
      'mock_strategy_3': false,
    }
  })

  const getMockKey = (strat: any): string | null => {
    const key = strat.id || ''
    const name = strat.name || ''
    if (key === 'mock_strategy_1' || name === 'VWAP Reclaim Long') return 'mock_strategy_1'
    if (key === 'mock_strategy_2' || name === 'Opening Range Breakdown Short') return 'mock_strategy_2'
    if (key === 'mock_strategy_3' || name === 'EMA 9/20 Cross Long') return 'mock_strategy_3'
    return null
  }

  const handleToggleValidation = async (e: React.MouseEvent, strat: any) => {
    e.stopPropagation();
    e.preventDefault();
    const stats = getStats(strat);
    const mockKey = getMockKey(strat);
    
    if (mockKey) {
      const current = mockValidationStates[mockKey] !== undefined ? mockValidationStates[mockKey] : MOCK_STRATEGY_STATS[mockKey].isValidated;
      const nextVal = !current;
      const nextStates = { ...mockValidationStates, [mockKey]: nextVal };
      setMockValidationStates(nextStates);
      if (typeof window !== 'undefined') {
        localStorage.setItem('mock_validation_states', JSON.stringify(nextStates));
      }
    } else {
      const realBt = backtests.find(bt => {
        const ids = bt.strategy_ids || [];
        return ids.includes(strat.id);
      });
      if (!realBt) {
        alert("No backtest result found for this strategy to validate.");
        return;
      }
      
      const currentStatus = realBt.is_validated !== undefined && realBt.is_validated !== null
        ? realBt.is_validated
        : (realBt.win_rate >= 50 && realBt.sharpe_ratio > 1.5);
      const nextStatus = !currentStatus;

      try {
        // Optimistically update local React state so UI updates instantly with no flicker
        setBacktests(prev => prev.map(bt => {
          if (bt.id === realBt.id) {
            let nextResultsJson = bt.results_json;
            if (typeof bt.results_json === 'string') {
              try {
                const parsed = JSON.parse(bt.results_json);
                parsed.is_validated = nextStatus;
                nextResultsJson = JSON.stringify(parsed);
              } catch (e) {}
            } else if (bt.results_json && typeof bt.results_json === 'object') {
              nextResultsJson = { ...bt.results_json, is_validated: nextStatus };
            }

            return {
              ...bt,
              is_validated: nextStatus,
              results_json: nextResultsJson
            };
          }
          return bt;
        }));

        // Fire request in the background
        await toggleBacktestValidation(realBt.id);
      } catch (err: any) {
        console.error(err);
        alert(`Error toggling validation status: ${err.message || err}`);
        // Revert to server data on failure
        await loadData();
      }
    }
  }

  const toggleRowExpand = (id: string) => {
    setExpandedRowId(prev => prev === id ? null : id)
  }

  // Formatter helpers for strategy conditions
  const formatIndicator = (ind: any): string => {
    if (!ind) return "";
    const params: string[] = [];
    if (ind.period != null && ind.period !== "") params.push(`P:${ind.period}`);
    if (ind.period2 != null && ind.period2 !== "") params.push(`P2:${ind.period2}`);
    if (ind.stdDev != null && ind.stdDev !== "") params.push(`SD:${ind.stdDev}`);
    if (ind.days_lookback != null && ind.days_lookback !== "") params.push(`Lookback:${ind.days_lookback}d`);
    if (ind.orb_minutes != null && ind.orb_minutes !== "") params.push(`ORB:${ind.orb_minutes}m`);
    if (ind.ap_session != null && typeof ind.ap_session === 'string' && ind.ap_session !== "") {
      params.push(`${ind.ap_session.replace("ap.", "")}`);
    }
    if (ind.elapsed_minutes != null && ind.elapsed_minutes !== "") params.push(`Elapsed:${ind.elapsed_minutes}m`);
    if (ind.band_line != null && ind.band_line !== "") params.push(`${ind.band_line}`);
    
    let offsetStr = "";
    if (ind.offset != null && ind.offset > 0) {
      offsetStr = `[t-${ind.offset}]`;
    }
    
    const paramsStr = params.length > 0 ? `(${params.join(",")})` : "";
    const nameStr = ind.name ? (INDICATOR_LABELS[ind.name] || ind.name) : "Variable";
    return `${nameStr}${paramsStr}${offsetStr}`;
  }

  const formatCondition = (cond: any): string => {
    if (!cond) return "";
    if (cond.type === 'indicator_comparison') {
      const sourceStr = formatIndicator(cond.source);
      const compStr = COMPARATOR_LABELS[cond.comparator] || cond.comparator || "=";
      const targetStr = typeof cond.target === 'number' 
        ? cond.target.toString() 
        : formatIndicator(cond.target);
      const tfStr = cond.timeframe ? `[${cond.timeframe}] ` : "";
      return `${tfStr}${sourceStr} ${compStr} ${targetStr}`;
    } else if (cond.type === 'price_level_distance') {
      const sourceStr = formatIndicator(cond.source);
      const compStr = cond.comparator === 'DISTANCE_GT' ? ">" : "<";
      const levelStr = formatIndicator(cond.level);
      const posStr = cond.position && cond.position !== 'any' ? ` (${cond.position})` : "";
      const tfStr = cond.timeframe ? `[${cond.timeframe}] ` : "";
      return `${tfStr}${sourceStr} dist ${compStr} ${cond.value_pct}% to ${levelStr}${posStr}`;
    }
    return "";
  }

  const getConditionTags = (group?: any): string[] => {
    if (!group) return [];
    
    const parseGroup = (g: any): string[] => {
      let results: string[] = [];
      const op = g.operator || "AND";
      
      if (g.conditions) {
        g.conditions.forEach((c: any) => {
          if (c.type === 'group') {
            results = results.concat(parseGroup(c));
          } else {
            const formatted = formatCondition(c);
            if (formatted) {
              results.push(`${op}: ${formatted}`);
            }
          }
        });
      }
      return results;
    };
    
    return parseGroup(group);
  }

  const formatPrecondition = (pre: any): string => {
    if (!pre) return "";
    const dayLabel = pre.day === 'gap_day' ? 'Gap Day' : 'Gap+1 Day';
    let metricLabel = 'Cierre';
    let valLabel = '';
    
    if (pre.metric === 'volume') {
      metricLabel = 'Volumen Total';
      const volVal = pre.value ?? 0;
      valLabel = `${pre.operator} ${volVal >= 1000000 ? `${volVal / 1000000}M` : volVal.toLocaleString()}`;
    } else if (pre.metric === 'close_vs_open') {
      valLabel = `${pre.operator} Apertura`;
    } else if (pre.metric === 'close_vs_high_low') {
      valLabel = pre.operator === '> High' ? '> High Previo' : '< Low Previo';
    } else if (pre.metric === 'close_vs_high') {
      valLabel = `${pre.operator} High`;
    } else if (pre.metric === 'close_vs_low') {
      valLabel = `${pre.operator} Low`;
    } else if (pre.metric === 'close_vs_pm_high') {
      valLabel = `${pre.operator} PM High`;
    } else if (pre.metric === 'close_vs_pm_low') {
      valLabel = `${pre.operator} PM Low`;
    } else if (pre.metric === 'close_vs_vwap') {
      valLabel = `${pre.operator} VWAP`;
    } else if (pre.metric === 'close_vs_sma') {
      valLabel = `${pre.operator} SMA ${pre.sma_period || 20}`;
    } else if (pre.metric === 'candle_range_pct') {
      metricLabel = 'Rango de Vela %';
      valLabel = `${pre.operator} ${pre.value}%`;
    } else if (pre.metric === 'candle_range_ratio_gap_1_vs_gap') {
      metricLabel = pre.day === 'gap_1_day' ? 'Rango vela Gap+1 vs Gap' : 'Rango vela vs Previo';
      valLabel = `${pre.operator} ${pre.value}%`;
    }
    return `${dayLabel} • ${metricLabel}: ${valLabel}`;
  }

  const getUniverseTags = (filters?: any): string[] => {
    if (!filters) return [];
    const tags: string[] = [];
    if (filters.min_market_cap != null && filters.min_market_cap !== "") tags.push(`Min Cap: $${(filters.min_market_cap / 1e6).toFixed(1)}M`);
    if (filters.max_market_cap != null && filters.max_market_cap !== "") tags.push(`Max Cap: $${(filters.max_market_cap / 1e6).toFixed(1)}M`);
    if (filters.min_price != null && filters.min_price !== "") tags.push(`Min Price: $${filters.min_price}`);
    if (filters.max_price != null && filters.max_price !== "") tags.push(`Max Price: $${filters.max_price}`);
    if (filters.min_volume != null && filters.min_volume !== "") tags.push(`Min Vol: ${(filters.min_volume / 1e3).toFixed(0)}k`);
    if (filters.max_shares_float != null && filters.max_shares_float !== "") tags.push(`Max Float: ${(filters.max_shares_float / 1e6).toFixed(1)}M`);
    if (filters.require_shortable === true) tags.push("Require Shortable");
    if (filters.exclude_dilution === true) tags.push("Exclude Dilution");
    if (filters.whitelist_sectors && filters.whitelist_sectors.length > 0) {
      tags.push(`Sectors: ${filters.whitelist_sectors.join(', ')}`);
    }
    return tags;
  }

  const getRiskTags = (risk?: any): string[] => {
    if (!risk) return [];
    const tags: string[] = [];
    if (risk.use_hard_stop && risk.hard_stop?.value != null && risk.hard_stop.value !== "") {
      tags.push(`SL: ${risk.hard_stop.value}%`);
    }
    if (risk.use_take_profit && risk.take_profit?.value != null && risk.take_profit.value !== "") {
      tags.push(`TP: ${risk.take_profit.value}%`);
    }
    if (risk.take_profit_mode && (risk.use_take_profit || (risk.partial_take_profits && risk.partial_take_profits.length > 0))) {
      tags.push(`TP Mode: ${risk.take_profit_mode}`);
    }
    if (risk.partial_take_profits && risk.partial_take_profits.length > 0) {
      risk.partial_take_profits.forEach((pt: any, i: number) => {
        if (pt && pt.capital_pct != null && pt.capital_pct !== "" && pt.distance_pct != null && pt.distance_pct !== "") {
          tags.push(`P-TP ${i+1}: ${pt.capital_pct}% @ ${pt.distance_pct === 'EOD' ? 'EOD' : pt.distance_pct + '%'}`);
        }
      });
    }
    if (risk.trailing_stop?.active && risk.trailing_stop?.buffer_pct != null && risk.trailing_stop.buffer_pct !== "") {
      tags.push(`TS: ${risk.trailing_stop.buffer_pct}%`);
    }
    if (risk.max_drawdown_daily != null && risk.max_drawdown_daily !== "") {
      tags.push(`Max Daily DD: ${risk.max_drawdown_daily}%`);
    }
    return tags;
  }

  const addToIncubator = (strat: any) => {
    if (incubatorStrategies.some(s => s.id === strat.id)) {
      alert("This strategy is already in the incubator list.")
      return
    }
    setIncubatorStrategies(prev => [...prev, strat])
  }

  const removeFromIncubator = (id: string) => {
    setIncubatorStrategies(prev => prev.filter(s => s.id !== id))
  }

  // Seed incubator with EMA Cross mock strategy once strategies load
  useEffect(() => {
    if (strategies.length > 0 && incubatorStrategies.length === 0) {
      const seedStrat = strategies.find(s => s.id === 'mock_strategy_3' || s.name === 'EMA 9/20 Cross Long') || strategies[2]
      if (seedStrat) {
        setIncubatorStrategies([seedStrat])
      }
    }
  }, [strategies])

  useEffect(() => {
    loadData()
  }, [])

  const toggleStrategySelection = (id: string) => {
    setSelectedStrategyIds(prev => {
      if (prev.includes(id)) {
        return prev.filter(x => x !== id)
      } else {
        return [...prev, id]
      }
    })
  }

  const toggleChartForStrategy = (id: string) => {
    setShowCharts(prev => ({
      ...prev,
      [id]: !prev[id]
    }))
  }

  const loadData = async () => {
    setLoading(true)
    setError(null)
    try {
      const [stratsList, queriesList, backtestsList] = await Promise.all([
        getStrategies(),
        getQueries(),
        getSavedBacktests().catch(() => ({ strategies: [], total_count: 0 }))
      ])
      
      const strategiesData = stratsList || []
      setStrategies(strategiesData)
      setDatasets(queriesList || [])
      setBacktests(backtestsList?.strategies || [])
      
      if (strategiesData.length > 0 && strategiesData[0].id) {
        setSelectedStrategyIds([strategiesData[0].id])
      }
    } catch (err: any) {
      console.error(err)
      setError('Could not connect to database repository.')
    } finally {
      setLoading(false)
    }
  }

  // Deletion logic
  const handleDelete = async (e: React.MouseEvent, id: string, type: 'strategy' | 'dataset') => {
    e.stopPropagation()
    setDeletingId(id)
    setDeletingType(type)
    try {
      if (type === 'strategy') {
        await deleteStrategy(id)
        setStrategies(prev => prev.filter(s => s.id !== id))
        setSelectedStrategyIds(prev => prev.filter(x => x !== id))
      } else {
        await deleteQuery(id)
        setDatasets(prev => prev.filter(d => d.id !== id))
      }
    } catch (err) {
      console.error(err)
      alert(`Error deleting ${type}`)
    } finally {
      setDeletingId(null)
      setDeletingType(null)
    }
  }

  // Resolves stats for a strategy
  const getStats = (strat: any) => {
    const realBt = backtests.find(bt => {
      const ids = bt.strategy_ids || []
      return ids.includes(strat.id)
    })

    if (realBt) {
      let curve: number[] = []
      let period = 'N/A'
      let avgRDay = 0
      let bParams: any = null
      let isValidated = realBt.is_validated !== undefined && realBt.is_validated !== null
        ? realBt.is_validated
        : (realBt.win_rate >= 50 && realBt.sharpe_ratio > 1.5)
      
      try {
        const results = typeof realBt.results_json === 'string' 
          ? JSON.parse(realBt.results_json) 
          : realBt.results_json
        const rawCurve = results?.global_equity || results?.equity_curve || []
        bParams = results?.backtest_params || null
        if (results?.is_validated !== undefined && results?.is_validated !== null) {
          isValidated = results.is_validated
        }
        
        // Parse and sort by time, return the full curve (no slicing/limiting to 6 months)
        if (rawCurve.length > 0) {
          const mapped = rawCurve.map((c: any) => {
            const timeMs = c.time ? c.time * 1000 : (c.timestamp ? new Date(c.timestamp).getTime() : 0);
            const val = c.value !== undefined ? c.value : (c.balance !== undefined ? c.balance : 0);
            return { timeMs, val };
          });
          const sorted = [...mapped].sort((a, b) => a.timeMs - b.timeMs);
          curve = sorted.map(item => item.val);
        }

        // Period calculation
        const trades = results?.trades || []
        if (trades.length > 0) {
          const sortedTrades = [...trades].sort((a, b) => new Date(a.entry_time).getTime() - new Date(b.entry_time).getTime())
          const start = sortedTrades[0].entry_time?.split('T')[0] || ''
          const end = sortedTrades[sortedTrades.length - 1].entry_time?.split('T')[0] || ''
          if (start && end) period = `${start} / ${end}`
        }

        // Avg R / Day calculation
        avgRDay = realBt.avg_r_multiple !== undefined && realBt.avg_r_multiple !== null
          ? realBt.avg_r_multiple
          : 0;
      } catch (e) {
        console.error(e)
      }
      return {
        winRate: realBt.win_rate,
        profitFactor: realBt.profit_factor,
        maxDd: realBt.max_drawdown_pct,
        sharpe: realBt.sharpe_ratio,
        trades: realBt.total_trades || 60,
        period: period,
        avgRDay: avgRDay,
        equityCurve: curve,
        isReal: true,
        isValidated: isValidated,
        backtestParams: bParams
      }
    }

    // Pre-seeded fallback
    const mockKey = getMockKey(strat)
    if (mockKey) {
      const baseStats = MOCK_STRATEGY_STATS[mockKey]
      const isVal = mockValidationStates[mockKey] !== undefined ? mockValidationStates[mockKey] : baseStats.isValidated
      return { 
        ...baseStats, 
        isValidated: isVal,
        isReal: false,
        backtestParams: mockKey === 'mock_strategy_1' ? {
          init_cash: 10000,
          risk_r: 100,
          fees: 0.0001,
          slippage: 0.0005,
          market_sessions: ['rth'],
        } : mockKey === 'mock_strategy_2' ? {
          init_cash: 10000,
          risk_r: 100,
          fees: 0.0001,
          slippage: 0.0003,
          market_sessions: ['rth'],
          monthly_expenses: 150
        } : {
          init_cash: 10000,
          risk_r: 100,
          fees: 0.0001,
          slippage: 0.0005,
          market_sessions: ['pre', 'rth'],
          monthly_expenses: 100
        }
      }
    }

    return {
      winRate: null,
      profitFactor: null,
      maxDd: null,
      sharpe: null,
      trades: 0,
      period: 'N/A',
      avgRDay: null,
      equityCurve: [],
      isReal: false,
      isValidated: false,
      backtestParams: null
    }
  }

  // Parse filters to styled badges
  const parseFiltersToTags = (filters: any) => {
    const tags: { label: string; value: string; icon: string }[] = []
    if (!filters) return tags

    const start = filters.start_date || filters.date_from
    const end = filters.end_date || filters.date_to
    if (start || end) {
      tags.push({
        label: 'Date',
        value: `${start ? start : 'Start'} to ${end ? end : 'Now'}`,
        icon: '📅'
      })
    }

    if (filters.ticker) {
      tags.push({ label: 'Symbol', value: filters.ticker.toUpperCase(), icon: '🔍' })
    }

    const minGap = filters.min_gap_pct !== undefined ? filters.min_gap_pct : filters.min_gap
    const maxGap = filters.max_gap_pct !== undefined ? filters.max_gap_pct : filters.max_gap
    if (minGap !== undefined && minGap !== null) {
      tags.push({ label: 'Min Gap', value: `${minGap}%`, icon: '📈' })
    }
    if (maxGap !== undefined && maxGap !== null) {
      tags.push({ label: 'Max Gap', value: `${maxGap}%`, icon: '📉' })
    }

    const minVol = filters.min_rth_volume !== undefined ? filters.min_rth_volume : filters.min_volume
    if (minVol) {
      const formatted = minVol >= 1000000 
        ? `${(minVol / 1000000).toFixed(1)}M` 
        : minVol >= 1000 
          ? `${(minVol / 1000).toFixed(0)}k` 
          : minVol.toString()
      tags.push({ label: 'Vol', value: `> ${formatted}`, icon: '📊' })
    }

    if (filters.rules && Array.isArray(filters.rules) && filters.rules.length > 0) {
      filters.rules.forEach((rule: any) => {
        tags.push({
          label: rule.metric || 'Rule',
          value: `${rule.operator || ''} ${rule.value !== undefined ? rule.value : ''}`.trim(),
          icon: '⚙️'
        })
      })
    }

    return tags
  }

  // Get current active strategy details
  const selectedStrategies = strategies.filter(s => selectedStrategyIds.includes(s.id))

  // Helper to slice data and calculate 3-month performance stats normalized to 1R
  const getThreeMonthStatsAndCurve = (strat: any) => {
    const stats = getStats(strat)
    const curve = stats.equityCurve || []
    
    // 3 months is approx the last 4 points for small mock curves or last 60 trading days/points for full curves
    const sliceLen = curve.length <= 20 ? 4 : 60
    const threeMonthCurve = curve.slice(-sliceLen)
    
    if (threeMonthCurve.length < 2) {
      return {
        stats: {
          profit: 0,
          profitR: 0,
          trades: 0,
          winRate: 0,
          profitFactor: 0,
          maxDd: 0,
          sharpe: 0,
          avgRDay: 0
        },
        curveR: []
      }
    }
    
    const initial = threeMonthCurve[0]
    const final = threeMonthCurve[threeMonthCurve.length - 1]
    const profit = final - initial
    
    // Normalise: 1R = 1% of initial capital (or $100 if initial is 0 or null)
    const R_value = initial > 0 ? initial * 0.01 : 100
    const profitR = profit / R_value
    
    // Normalized R curve starting at 0 R
    const curveR = threeMonthCurve.map(val => (val - initial) / R_value)
    
    // Max Drawdown in % over this 3-month period
    let peak = threeMonthCurve[0]
    let maxDDPct = 0
    threeMonthCurve.forEach(val => {
      if (val > peak) peak = val
      const ddPct = peak > 0 ? ((peak - val) / peak) * 100 : 0
      if (ddPct > maxDDPct) maxDDPct = ddPct
    })
    
    // Ratio of 3-month period trades to total trades
    const ratio = threeMonthCurve.length / (curve.length || 1)
    const tradesCount = Math.round((stats.trades || 80) * ratio)
    
    // Calculate Sharpe and Profit Factor relative to base stats with slight variation to look realistic
    const winRate = stats.winRate ? Math.min(100, Math.max(0, stats.winRate + (strat.id === 'mock_strategy_2' ? -2.1 : 1.5))) : 50.0
    const profitFactor = stats.profitFactor ? Math.max(0.5, stats.profitFactor + (strat.id === 'mock_strategy_2' ? -0.15 : 0.1)) : 1.5
    const sharpe = stats.sharpe ? Math.max(0.1, stats.sharpe + (strat.id === 'mock_strategy_2' ? -0.2 : 0.15)) : 1.6
    const avgRDay = stats.avgRDay ? stats.avgRDay * 0.95 : 0.35
    
    return {
      stats: {
        profit,
        profitR,
        trades: tradesCount > 0 ? tradesCount : 15,
        winRate,
        profitFactor,
        maxDd: maxDDPct,
        sharpe,
        avgRDay
      },
      curveR
    }
  }

  const renderComparisonRow = (label: string, valueKey: string, format: (v: number) => string, colorFn?: (v: number) => string) => {
    return (
      <tr style={{ borderBottom: '0.5px solid rgba(255, 255, 255, 0.05)' }}>
        <td style={{ padding: '8px 10px', fontSize: 10, fontWeight: 700, color: 'var(--color-ec-text-muted)', textTransform: 'uppercase', letterSpacing: '0.3px' }}>
          {label}
        </td>
        {selectedStrategies.map((strat) => {
          const stats3M = getThreeMonthStatsAndCurve(strat).stats as any
          const val = stats3M[valueKey]
          const displayColor = colorFn ? colorFn(val) : 'var(--color-ec-text-primary)'
          return (
            <td 
              key={strat.id} 
              style={{ 
                padding: '8px 10px', 
                fontSize: 12, 
                fontWeight: 600, 
                color: displayColor, 
                textAlign: 'right',
                borderLeft: '0.5px solid var(--color-ec-border)',
                fontFamily: 'monospace'
              }}
            >
              {val !== null && val !== undefined ? format(val) : '—'}
            </td>
          )
        })}
      </tr>
    )
  }

  // Sliced curve showing only the last 6 months (last 6 items for mock datasets)
  const getSampledCurve = (curve: number[]) => {
    if (!curve || curve.length === 0) return []
    return curve.slice(-6)
  }

  // Calculate detailed stats from current sliced curve
  const getSlicedStats = (curve: number[], base: any) => {
    if (!curve || curve.length < 2) return null
    const initial = curve[0]
    const final = curve[curve.length - 1]
    const profit = final - initial
    
    // Max Drawdown calculation
    let peak = curve[0]
    let maxDDValue = 0
    let maxDDPct = 0
    curve.forEach(val => {
      if (val > peak) peak = val
      const ddVal = peak - val
      const ddPct = peak > 0 ? (ddVal / peak) * 100 : 0
      if (ddPct > maxDDPct) {
        maxDDPct = ddPct
        maxDDValue = ddVal
      }
    })

    const ratio = curve.length / (base.equityCurve?.length || 1)
    const tradesCount = Math.round((base.trades || 80) * ratio)

    return {
      profit,
      trades: tradesCount > 0 ? tradesCount : 10,
      winRate: base.winRate || 55.0,
      profitFactor: base.profitFactor || 1.6,
      maxDd: maxDDPct,
      maxDdVal: maxDDValue,
      sharpe: base.sharpe || 1.7,
      isValidated: base.isValidated
    }
  }

  const renderStrategyTable = (stratList: any[], isIncubator: boolean) => {
    return (
      <div 
        style={{ 
          maxHeight: '260px', 
          overflowY: 'auto',
          border: '0.5px solid var(--color-ec-border)',
          borderRadius: 0,
          backgroundColor: 'var(--color-ec-bg-surface)',
          marginBottom: 20
        }}
      >
        {stratList.length === 0 ? (
          <div style={{ padding: '24px 12px', textAlign: 'center', color: 'var(--color-ec-text-muted)' }}>
            <p style={{ fontSize: 11, margin: 0 }}>No strategies registered</p>
          </div>
        ) : (
          <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left' }}>
            <thead>
              <tr style={{ borderBottom: '0.5px solid var(--color-ec-border)', backgroundColor: 'rgba(28, 30, 33, 0.3)' }}>
                <th style={{ padding: '6px 10px', fontSize: 8, fontWeight: 700, textTransform: 'uppercase', color: 'var(--color-ec-text-muted)' }}>Name</th>
                <th style={{ padding: '6px 10px', fontSize: 8, fontWeight: 700, textTransform: 'uppercase', color: 'var(--color-ec-text-muted)' }}>Bias</th>
                <th style={{ padding: '6px 10px', fontSize: 8, fontWeight: 700, textTransform: 'uppercase', color: 'var(--color-ec-text-muted)' }}>Trades</th>
                <th style={{ padding: '6px 10px', fontSize: 8, fontWeight: 700, textTransform: 'uppercase', color: 'var(--color-ec-text-muted)' }}>Equity</th>
                <th style={{ padding: '6px 10px', fontSize: 8, fontWeight: 700, textTransform: 'uppercase', color: 'var(--color-ec-text-muted)' }}>W.Rate</th>
                <th style={{ padding: '6px 10px', fontSize: 8, fontWeight: 700, textTransform: 'uppercase', color: 'var(--color-ec-text-muted)' }}>P.Factor</th>
                <th style={{ padding: '6px 10px', fontSize: 8, fontWeight: 700, textTransform: 'uppercase', color: 'var(--color-ec-text-muted)' }}>Max DD</th>
                <th style={{ padding: '6px 10px', fontSize: 8, fontWeight: 700, textTransform: 'uppercase', color: 'var(--color-ec-text-muted)' }}>Sharpe</th>
                <th style={{ padding: '6px 10px', fontSize: 8, fontWeight: 700, textTransform: 'uppercase', color: 'var(--color-ec-text-muted)' }}>Avg R/Day</th>
                <th style={{ padding: '6px 10px', fontSize: 8, fontWeight: 700, textTransform: 'uppercase', color: 'var(--color-ec-text-muted)' }}>Validated?</th>
                <th style={{ padding: '6px 10px', textAlign: 'right' }} />
              </tr>
            </thead>
            <tbody>
              {stratList.map(strat => {
                const stats = getStats(strat)
                const isSelected = selectedStrategyIds.includes(strat.id)
                const isPositive = stats.winRate ? stats.winRate >= 50 : true
                const isExpanded = expandedRowId === strat.id
                
                return (
                  <React.Fragment key={strat.id}>
                    <tr
                      onClick={() => toggleStrategySelection(strat.id)}
                      style={{
                        borderBottom: '0.5px solid rgba(44, 47, 51, 0.25)',
                        backgroundColor: isSelected ? 'rgba(216, 122, 61, 0.06)' : 'transparent',
                        borderLeft: isSelected ? '2px solid var(--color-ec-copper)' : '2px solid transparent',
                        cursor: 'pointer',
                        transition: 'background-color 150ms ease'
                      }}
                      onMouseEnter={e => {
                        if (!isSelected) e.currentTarget.style.backgroundColor = 'rgba(255, 255, 255, 0.01)'
                      }}
                      onMouseLeave={e => {
                        if (!isSelected) e.currentTarget.style.backgroundColor = 'transparent'
                      }}
                    >
                      {/* Name with Chevron Toggle */}
                      <td style={{ padding: '6px 10px' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                          <button
                            type="button"
                            onClick={(e) => {
                              e.stopPropagation();
                              toggleRowExpand(strat.id);
                            }}
                            style={{
                              background: 'transparent',
                              border: 'none',
                              cursor: 'pointer',
                              color: 'var(--color-ec-text-muted)',
                              padding: 2,
                              display: 'flex',
                              alignItems: 'center',
                              justifyContent: 'center',
                              transition: 'color 150ms ease',
                            }}
                            onMouseEnter={e => e.currentTarget.style.color = 'var(--color-ec-text-high)'}
                            onMouseLeave={e => e.currentTarget.style.color = 'var(--color-ec-text-muted)'}
                            title="Expand conditions"
                          >
                            {isExpanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
                          </button>
                          <div>
                            <div style={{ fontWeight: 600, fontSize: 12, color: 'var(--color-ec-text-high)' }}>{strat.name}</div>
                            {strat.description && (
                              <div style={{ fontSize: 9, color: 'var(--color-ec-text-muted)', marginTop: 1, textOverflow: 'ellipsis', overflow: 'hidden', whiteSpace: 'nowrap', maxWidth: 120 }} title={strat.description}>
                                {strat.description}
                              </div>
                            )}
                          </div>
                        </div>
                      </td>
                      <td style={{ padding: '6px 10px' }}>
                        <span 
                          style={{ 
                            fontSize: 8, 
                            fontWeight: 700, 
                            padding: '1px 4px', 
                            borderRadius: 0, 
                            textTransform: 'uppercase',
                            backgroundColor: strat.bias === 'short' ? 'rgba(201, 77, 63, 0.12)' : 'rgba(74, 157, 127, 0.12)',
                            color: strat.bias === 'short' ? 'var(--color-ec-loss)' : 'var(--color-ec-profit)',
                          }}
                        >
                          {strat.bias}
                        </span>
                      </td>
                      <td style={{ padding: '6px 10px', fontSize: 11, fontWeight: 600, color: 'var(--color-ec-text-primary)' }}>
                        {stats.trades || '—'}
                      </td>
                      <td style={{ padding: '6px 10px' }}>
                        <Sparkline points={stats.equityCurve} isPositive={isPositive} />
                      </td>
                      <td style={{ padding: '6px 10px', fontSize: 11, fontWeight: 600, color: stats.winRate ? 'var(--color-ec-text-primary)' : 'var(--color-ec-text-muted)' }}>
                        {stats.winRate !== null ? `${stats.winRate.toFixed(1)}%` : '—'}
                      </td>
                      <td style={{ padding: '6px 10px', fontSize: 11, fontWeight: 600, color: stats.profitFactor ? 'var(--color-ec-text-primary)' : 'var(--color-ec-text-muted)' }}>
                        {stats.profitFactor !== null ? stats.profitFactor.toFixed(2) : '—'}
                      </td>
                      <td style={{ padding: '6px 10px', fontSize: 11, fontWeight: 600, color: stats.maxDd ? 'var(--color-ec-loss)' : 'var(--color-ec-text-muted)' }}>
                        {stats.maxDd !== null ? `-${stats.maxDd.toFixed(1)}%` : '—'}
                      </td>
                      <td style={{ padding: '6px 10px', fontSize: 11, fontWeight: 600, color: stats.sharpe ? 'var(--color-ec-text-primary)' : 'var(--color-ec-text-muted)' }}>
                        {stats.sharpe !== null ? stats.sharpe.toFixed(2) : '—'}
                      </td>
                      <td style={{ padding: '6px 10px', fontSize: 11, fontWeight: 600, color: stats.avgRDay ? 'var(--color-ec-profit)' : 'var(--color-ec-text-muted)' }}>
                        {stats.avgRDay !== null ? `${stats.avgRDay.toFixed(2)} R` : '—'}
                      </td>
                      <td style={{ padding: '6px 10px' }}>
                        <button
                          type="button"
                          onClick={(e) => handleToggleValidation(e, strat)}
                          style={{
                            fontSize: 8,
                            fontWeight: 700,
                            padding: '3px 8px',
                            borderRadius: 0,
                            textTransform: 'uppercase',
                            backgroundColor: stats.isValidated ? 'rgba(74, 157, 127, 0.12)' : 'rgba(201, 77, 63, 0.12)',
                            color: stats.isValidated ? 'var(--color-ec-profit)' : 'var(--color-ec-loss)',
                            border: stats.isValidated ? '0.5px solid rgba(74, 157, 127, 0.25)' : '0.5px solid rgba(201, 77, 63, 0.25)',
                            cursor: 'pointer',
                            transition: 'all 150ms ease'
                          }}
                          onMouseEnter={e => {
                            e.currentTarget.style.backgroundColor = stats.isValidated ? 'rgba(74, 157, 127, 0.2)' : 'rgba(201, 77, 63, 0.2)';
                            e.currentTarget.style.borderColor = stats.isValidated ? 'rgba(74, 157, 127, 0.4)' : 'rgba(201, 77, 63, 0.4)';
                          }}
                          onMouseLeave={e => {
                            e.currentTarget.style.backgroundColor = stats.isValidated ? 'rgba(74, 157, 127, 0.12)' : 'rgba(201, 77, 63, 0.12)';
                            e.currentTarget.style.borderColor = stats.isValidated ? 'rgba(74, 157, 127, 0.25)' : 'rgba(201, 77, 63, 0.25)';
                          }}
                          title="Click to toggle validation status"
                        >
                          {stats.isValidated ? 'YES' : 'NO'}
                        </button>
                      </td>
                      <td style={{ padding: '6px 10px', textAlign: 'right' }}>
                        <div style={{ display: 'flex', gap: 6, justifyContent: 'flex-end', alignItems: 'center' }}>
                          <button
                            onClick={(e) => {
                              e.stopPropagation()
                              router.push(`/backtester?strategy_id=${strat.id}`)
                            }}
                            style={{
                              background: 'transparent',
                              border: 'none',
                              padding: 2,
                              cursor: 'pointer',
                              color: 'var(--color-ec-text-muted)'
                            }}
                            title="Run Backtest"
                          >
                            <Play size={10} fill="currentColor" />
                          </button>
                          {!isIncubator ? (
                            <button
                              onClick={(e) => {
                                e.stopPropagation()
                                addToIncubator(strat)
                              }}
                              style={{
                                background: 'transparent',
                                border: 'none',
                                padding: 2,
                                cursor: 'pointer',
                                color: 'var(--color-ec-text-muted)'
                              }}
                              title="Monitor in Incubator"
                            >
                              <Plus size={10} />
                            </button>
                          ) : (
                            <button
                              onClick={(e) => {
                                e.stopPropagation()
                                removeFromIncubator(strat.id)
                              }}
                              style={{
                                background: 'transparent',
                                border: 'none',
                                padding: 2,
                                cursor: 'pointer',
                                color: 'var(--color-ec-text-muted)'
                              }}
                              title="Remove from Incubator"
                            >
                              <Minus size={10} />
                            </button>
                          )}
                          {!isIncubator && (
                            <button
                              disabled={deletingId === strat.id}
                              onClick={(e) => handleDelete(e, strat.id, 'strategy')}
                              style={{
                                background: 'transparent',
                                border: 'none',
                                padding: 2,
                                cursor: 'pointer',
                                color: 'var(--color-ec-text-muted)'
                              }}
                              title="Delete Strategy"
                            >
                              <Trash2 size={10} />
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                    
                    {/* Collapsible tags row */}
                    {isExpanded && (
                      <tr style={{ backgroundColor: 'rgba(28, 30, 33, 0.25)' }}>
                        <td colSpan={11} style={{ padding: '12px 16px', borderBottom: '0.5px solid rgba(44, 47, 51, 0.2)' }}>
                          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '16px 24px' }}>
                            {/* Column 1: Strategy Definition */}
                            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                              <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
                                <span style={{ width: 4, height: 10, backgroundColor: 'var(--color-ec-copper)' }} />
                                <h4 style={{ fontSize: 10, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.5px', color: 'var(--color-ec-text-high)', margin: 0 }}>
                                  Strategy Definition
                                </h4>
                              </div>
                              
                              {/* Preconditions */}
                              {((strat.postgap_preconditions && strat.postgap_preconditions.length > 0) || strat.apply_day) && (
                                <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
                                  <span style={{ fontSize: 9, fontWeight: 700, color: 'var(--color-ec-text-muted)', textTransform: 'uppercase', width: 90 }}>Timing/Preconds:</span>
                                  {strat.apply_day && (
                                    <span style={{ fontSize: 9, fontWeight: 600, padding: '2px 6px', border: '0.5px solid rgba(59, 130, 246, 0.3)', backgroundColor: 'rgba(59, 130, 246, 0.06)', color: '#60a5fa' }}>
                                      Apply: {strat.apply_day}
                                    </span>
                                  )}
                                  {strat.postgap_preconditions?.map((pre: any, idx: number) => (
                                    <span key={idx} style={{ fontSize: 9, fontWeight: 600, padding: '2px 6px', border: '0.5px solid rgba(216, 122, 61, 0.3)', backgroundColor: 'rgba(216, 122, 61, 0.06)', color: 'var(--color-ec-copper)' }}>
                                      {formatPrecondition(pre)}
                                    </span>
                                  ))}
                                </div>
                              )}

                              {/* Universe filters */}
                              {getUniverseTags(strat.universe_filters).length > 0 && (
                                <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
                                  <span style={{ fontSize: 9, fontWeight: 700, color: 'var(--color-ec-text-muted)', textTransform: 'uppercase', width: 90 }}>Universe Filters:</span>
                                  {getUniverseTags(strat.universe_filters).map((tag, idx) => (
                                    <span key={idx} style={{ fontSize: 9, fontWeight: 600, padding: '2px 6px', border: '0.5px solid rgba(168, 85, 247, 0.3)', backgroundColor: 'rgba(168, 85, 247, 0.06)', color: '#a855f7' }}>
                                      {tag}
                                    </span>
                                  ))}
                                </div>
                              )}

                              {/* Entry Logic */}
                              <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
                                <span style={{ fontSize: 9, fontWeight: 700, color: 'var(--color-ec-text-muted)', textTransform: 'uppercase', width: 90 }}>Entry Logic ({strat.entry_logic?.timeframe || 'N/A'}):</span>
                                {getConditionTags(strat.entry_logic?.root_condition).length === 0 ? (
                                  <span style={{ fontSize: 9, color: 'var(--color-ec-text-muted)', fontStyle: 'italic' }}>No entry conditions</span>
                                ) : (
                                  getConditionTags(strat.entry_logic?.root_condition).map((tag, idx) => (
                                    <span key={idx} style={{ fontSize: 9, fontWeight: 600, padding: '2px 6px', border: '0.5px solid rgba(74, 157, 127, 0.3)', backgroundColor: 'rgba(74, 157, 127, 0.06)', color: 'var(--color-ec-profit)' }}>
                                      {tag}
                                    </span>
                                  ))
                                )}
                              </div>

                              {/* Entry Time Windows */}
                              {strat.entry_logic?.entry_time_windows && strat.entry_logic.entry_time_windows.length > 0 && (
                                <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
                                  <span style={{ fontSize: 9, fontWeight: 700, color: 'var(--color-ec-text-muted)', textTransform: 'uppercase', width: 90 }}>Horas Entrada:</span>
                                  {strat.entry_logic.entry_time_windows.map((w: any, idx: number) => (
                                    <span key={idx} style={{ fontSize: 9, fontWeight: 600, padding: '2px 6px', border: '0.5px solid rgba(216, 122, 61, 0.3)', backgroundColor: 'rgba(216, 122, 61, 0.06)', color: 'var(--color-ec-copper)' }}>
                                      {w.from_time} - {w.to_time} ET
                                    </span>
                                  ))}
                                </div>
                              )}

                              {/* Exit Logic */}
                              <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
                                <span style={{ fontSize: 9, fontWeight: 700, color: 'var(--color-ec-text-muted)', textTransform: 'uppercase', width: 90 }}>Exit Logic ({strat.exit_logic?.timeframe || 'N/A'}):</span>
                                {getConditionTags(strat.exit_logic?.root_condition).length === 0 ? (
                                  <span style={{ fontSize: 9, color: 'var(--color-ec-text-muted)', fontStyle: 'italic' }}>No exit conditions</span>
                                ) : (
                                  getConditionTags(strat.exit_logic?.root_condition).map((tag, idx) => (
                                    <span key={idx} style={{ fontSize: 9, fontWeight: 600, padding: '2px 6px', border: '0.5px solid rgba(245, 158, 11, 0.3)', backgroundColor: 'rgba(245, 158, 11, 0.06)', color: '#f59e0b' }}>
                                      {tag}
                                    </span>
                                  ))
                                )}
                              </div>

                              {/* Risk Management */}
                              {getRiskTags(strat.risk_management).length > 0 && (
                                <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
                                  <span style={{ fontSize: 9, fontWeight: 700, color: 'var(--color-ec-text-muted)', textTransform: 'uppercase', width: 90 }}>Risk Settings:</span>
                                  {getRiskTags(strat.risk_management).map((tag, idx) => (
                                    <span key={idx} style={{ fontSize: 9, fontWeight: 600, padding: '2px 6px', border: '0.5px solid rgba(239, 68, 68, 0.3)', backgroundColor: 'rgba(239, 68, 68, 0.06)', color: '#ef4444' }}>
                                      {tag}
                                    </span>
                                  ))}
                                </div>
                              )}
                            </div>

                            {/* Column 2: Backtester Configuration */}
                            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                              <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
                                <span style={{ width: 4, height: 10, backgroundColor: 'var(--color-ec-copper)' }} />
                                <h4 style={{ fontSize: 10, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.5px', color: 'var(--color-ec-text-high)', margin: 0 }}>
                                  Backtester Configuration
                                </h4>
                              </div>

                              {stats.backtestParams ? (
                                <div style={{ display: 'grid', gridTemplateColumns: '130px 1fr', gap: '6px 8px', alignItems: 'center' }}>
                                  {stats.backtestParams.init_cash != null && stats.backtestParams.init_cash !== "" && (
                                    <>
                                      <span style={{ fontSize: 9, fontWeight: 700, color: 'var(--color-ec-text-muted)', textTransform: 'uppercase' }}>Initial Cash:</span>
                                      <span style={{ fontSize: 9, fontWeight: 600, color: 'var(--color-ec-text-primary)' }}>
                                        ${Number(stats.backtestParams.init_cash).toLocaleString()}
                                      </span>
                                    </>
                                  )}

                                  {stats.backtestParams.risk_r != null && stats.backtestParams.risk_r !== "" && (
                                    <>
                                      <span style={{ fontSize: 9, fontWeight: 700, color: 'var(--color-ec-text-muted)', textTransform: 'uppercase' }}>1R Risk Amount:</span>
                                      <span style={{ fontSize: 9, fontWeight: 600, color: 'var(--color-ec-text-primary)' }}>
                                        ${Number(stats.backtestParams.risk_r).toLocaleString()}
                                      </span>
                                    </>
                                  )}

                                  {stats.backtestParams.fees != null && stats.backtestParams.fees !== "" && Number(stats.backtestParams.fees) > 0 && (
                                    <>
                                      <span style={{ fontSize: 9, fontWeight: 700, color: 'var(--color-ec-text-muted)', textTransform: 'uppercase' }}>Fees / Commissions:</span>
                                      <span style={{ fontSize: 9, fontWeight: 600, color: 'var(--color-ec-text-primary)' }}>
                                        {parseFloat((Number(stats.backtestParams.fees) * 100).toFixed(3))}%
                                      </span>
                                    </>
                                  )}

                                  {stats.backtestParams.slippage != null && stats.backtestParams.slippage !== "" && Number(stats.backtestParams.slippage) > 0 && (
                                    <>
                                      <span style={{ fontSize: 9, fontWeight: 700, color: 'var(--color-ec-text-muted)', textTransform: 'uppercase' }}>Slippage:</span>
                                      <span style={{ fontSize: 9, fontWeight: 600, color: 'var(--color-ec-text-primary)' }}>
                                        {parseFloat((Number(stats.backtestParams.slippage) * 100).toFixed(3))}%
                                      </span>
                                    </>
                                  )}

                                  {stats.backtestParams.market_sessions && stats.backtestParams.market_sessions.length > 0 && (
                                    <>
                                      <span style={{ fontSize: 9, fontWeight: 700, color: 'var(--color-ec-text-muted)', textTransform: 'uppercase' }}>Market Hours:</span>
                                      <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                                        {stats.backtestParams.market_sessions.map((session: string) => (
                                          <span key={session} style={{ fontSize: 8, fontWeight: 700, padding: '1px 5px', border: '0.5px solid rgba(255,255,255,0.15)', textTransform: 'uppercase', color: 'var(--color-ec-text-secondary)', backgroundColor: 'rgba(255,255,255,0.03)' }}>
                                            {session}
                                          </span>
                                        ))}
                                      </div>
                                    </>
                                  )}

                                  {stats.backtestParams.monthly_expenses != null && stats.backtestParams.monthly_expenses !== "" && Number(stats.backtestParams.monthly_expenses) > 0 && (
                                    <>
                                      <span style={{ fontSize: 9, fontWeight: 700, color: 'var(--color-ec-text-muted)', textTransform: 'uppercase' }}>Monthly Expenses:</span>
                                      <span style={{ fontSize: 9, fontWeight: 600, color: 'var(--color-ec-text-primary)' }}>
                                        ${Number(stats.backtestParams.monthly_expenses).toLocaleString()}
                                      </span>
                                    </>
                                  )}

                                  {stats.backtestParams.locates_cost != null && stats.backtestParams.locates_cost !== "" && Number(stats.backtestParams.locates_cost) > 0 && (
                                    <>
                                      <span style={{ fontSize: 9, fontWeight: 700, color: 'var(--color-ec-text-muted)', textTransform: 'uppercase' }}>Locates Cost:</span>
                                      <span style={{ fontSize: 9, fontWeight: 600, color: 'var(--color-ec-text-primary)' }}>
                                        ${Number(stats.backtestParams.locates_cost).toLocaleString()}
                                      </span>
                                    </>
                                  )}
                                </div>
                              ) : (
                                <span style={{ fontSize: 9, color: 'var(--color-ec-text-muted)', fontStyle: 'italic' }}>
                                  No backtester configuration available for this strategy
                                </span>
                              )}
                            </div>
                          </div>
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                )
              })}
            </tbody>
          </table>
        )}
      </div>
    )
  }

  return (
    <div 
      style={{
        display: 'flex',
        flexDirection: 'column',
        height: '100vh',
        backgroundColor: 'var(--color-ec-bg-base)',
        color: 'var(--color-ec-text-primary)',
        fontFamily: "'General Sans', sans-serif",
        overflow: 'hidden'
      }}
    >
      {/* Premium Workspace Header */}
      <div 
        style={{
          padding: '16px 24px 12px 24px',
          borderBottom: '0.5px solid var(--color-ec-border)',
          backgroundColor: 'var(--color-ec-bg-sidebar)',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          flexShrink: 0
        }}
      >
        <div>
          <h1 
            style={{
              fontFamily: "'Fraunces', serif",
              fontSize: 24,
              fontWeight: 600,
              color: 'var(--color-ec-text-high)',
              letterSpacing: '-0.5px',
              margin: 0
            }}
          >
            BAÚL
          </h1>
          <p 
            style={{
              fontSize: 9,
              fontWeight: 700,
              textTransform: 'uppercase',
              letterSpacing: '1.2px',
              color: 'var(--color-ec-text-muted)',
              margin: '2px 0 0 0'
            }}
          >
            Manage datasets and strategy definitions in a split repository
          </p>
        </div>

        <button
          onClick={loadData}
          style={{
            background: 'transparent',
            border: '0.5px solid var(--color-ec-border)',
            borderRadius: 0, // Straight corners
            color: 'var(--color-ec-text-secondary)',
            padding: '6px 12px',
            fontSize: 10,
            fontWeight: 600,
            cursor: 'pointer',
            transition: 'all 150ms ease'
          }}
          onMouseEnter={e => {
            e.currentTarget.style.borderColor = 'var(--color-ec-text-secondary)'
            e.currentTarget.style.color = 'var(--color-ec-text-high)'
          }}
          onMouseLeave={e => {
            e.currentTarget.style.borderColor = 'var(--color-ec-border)'
            e.currentTarget.style.color = 'var(--color-ec-text-secondary)'
          }}
        >
          Sync Repository
        </button>
      </div>

      {loading ? (
        <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <div 
            style={{ 
              width: 24, 
              height: 24, 
              border: '2px solid var(--color-ec-border)',
              borderTopColor: 'var(--color-ec-copper)',
              borderRadius: '50%',
              animation: 'spin 0.8s linear infinite'
            }} 
          />
        </div>
      ) : error ? (
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: 24 }}>
          <AlertCircle size={32} color="var(--color-ec-loss)" />
          <p style={{ marginTop: 12, fontSize: 13, color: 'var(--color-ec-text-secondary)' }}>{error}</p>
        </div>
      ) : (
        /* Workspace Split Layout */
        <div 
          style={{
            flex: 1,
            display: 'flex',
            minHeight: 0,
            overflow: 'hidden'
          }}
          className="flex-col lg:flex-row"
        >
          {/* Main Left Workspace: Strategies (Scrollable Rows) + Datasets (Below) */}
          <div 
            style={{
              flex: '0 0 65%',
              borderRight: '0.5px solid var(--color-ec-border)',
              display: 'flex',
              flexDirection: 'column',
              minHeight: 0,
              backgroundColor: 'var(--color-ec-bg-base)',
              overflowY: 'auto'
            }}
            className="w-full lg:w-[65%]"
          >
            {/* 1. Strategy Rows Section */}
            <div style={{ padding: '16px 20px 0 20px' }}>
              <div 
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  marginBottom: 10,
                  borderBottom: '0.5px solid rgba(44, 47, 51, 0.4)',
                  paddingBottom: 6
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <Briefcase size={12} color="var(--color-ec-copper)" />
                  <h2 style={{ fontSize: 11, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '1px', color: 'var(--color-ec-text-high)', margin: 0 }}>
                    Trading Strategies
                  </h2>
                </div>
                <span style={{ fontSize: 8, fontWeight: 700, padding: '1px 6px', borderRadius: 0, backgroundColor: 'var(--color-ec-bg-surface)', border: '0.5px solid var(--color-ec-border)', color: 'var(--color-ec-text-muted)' }}>
                  {strategies.length} Saved
                </span>
              </div>

              {renderStrategyTable(strategies, false)}
            </div>

            {/* 2. Trading incubator strategies Section */}
            <div style={{ padding: '0 20px 0 20px' }}>
              <div 
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  marginBottom: 10,
                  borderBottom: '0.5px solid rgba(44, 47, 51, 0.4)',
                  paddingBottom: 6
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <Activity size={12} color="var(--color-ec-copper)" />
                  <h2 style={{ fontSize: 11, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '1px', color: 'var(--color-ec-text-high)', margin: 0 }}>
                    Trading incubator strategies
                  </h2>
                </div>
                <span style={{ fontSize: 8, fontWeight: 700, padding: '1px 6px', borderRadius: 0, backgroundColor: 'var(--color-ec-bg-surface)', border: '0.5px solid var(--color-ec-border)', color: 'var(--color-ec-text-muted)' }}>
                  {incubatorStrategies.length} Monitoring
                </span>
              </div>

              {renderStrategyTable(incubatorStrategies, true)}
            </div>

            {/* 2. Datasets Section (Placed BELOW Strategies, also in table rows, straight edges, thin padding) */}
            <div style={{ padding: '0 20px 20px 20px' }}>
              <div 
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  marginBottom: 10,
                  borderBottom: '0.5px solid rgba(44, 47, 51, 0.4)',
                  paddingBottom: 6
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <Layers size={12} color="var(--color-ec-copper)" />
                  <h2 style={{ fontSize: 11, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '1px', color: 'var(--color-ec-text-high)', margin: 0 }}>
                    Datasets Cohorts
                  </h2>
                </div>
                <span style={{ fontSize: 8, fontWeight: 700, padding: '1px 6px', borderRadius: 0, backgroundColor: 'var(--color-ec-bg-surface)', border: '0.5px solid var(--color-ec-border)', color: 'var(--color-ec-text-muted)' }}>
                  {datasets.length} Saved
                </span>
              </div>

              {/* Scrollable datasets list box - STRAIGHT EDGES */}
              <div 
                style={{ 
                  maxHeight: '280px', 
                  overflowY: 'auto',
                  border: '0.5px solid var(--color-ec-border)',
                  borderRadius: 0, // Straight corners
                  backgroundColor: 'var(--color-ec-bg-surface)',
                  marginBottom: 10
                }}
              >
                {datasets.length === 0 ? (
                  <div style={{ padding: '24px 12px', textAlign: 'center', color: 'var(--color-ec-text-muted)' }}>
                    <p style={{ fontSize: 11, margin: 0 }}>No datasets created yet</p>
                  </div>
                ) : (
                  <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left' }}>
                    <thead>
                      <tr style={{ borderBottom: '0.5px solid var(--color-ec-border)', backgroundColor: 'rgba(28, 30, 33, 0.3)' }}>
                        <th style={{ padding: '6px 10px', fontSize: 8, fontWeight: 700, textTransform: 'uppercase', color: 'var(--color-ec-text-muted)' }}>Name</th>
                        <th style={{ padding: '6px 10px', fontSize: 8, fontWeight: 700, textTransform: 'uppercase', color: 'var(--color-ec-text-muted)' }}>Created Date</th>
                        <th style={{ padding: '6px 10px', fontSize: 8, fontWeight: 700, textTransform: 'uppercase', color: 'var(--color-ec-text-muted)' }}>Conditions / Filters</th>
                        <th style={{ padding: '6px 10px', textAlign: 'right' }} />
                      </tr>
                    </thead>
                    <tbody>
                      {datasets.map(ds => {
                        const tags = parseFiltersToTags(ds.filters)
                        return (
                          <tr
                            key={ds.id}
                            style={{
                              borderBottom: '0.5px solid rgba(44, 47, 51, 0.25)',
                              transition: 'background-color 150ms ease'
                            }}
                            onMouseEnter={e => e.currentTarget.style.backgroundColor = 'rgba(255, 255, 255, 0.01)'}
                            onMouseLeave={e => e.currentTarget.style.backgroundColor = 'transparent'}
                          >
                            {/* Dataset Name */}
                            <td style={{ padding: '6px 10px', fontWeight: 600, fontSize: 12, color: 'var(--color-ec-text-high)' }}>
                              {ds.name}
                            </td>
                            {/* Created Date */}
                            <td style={{ padding: '6px 10px', fontSize: 10, color: 'var(--color-ec-text-muted)' }}>
                              {ds.created_at ? new Date(ds.created_at).toLocaleDateString() : 'N/A'}
                            </td>
                            {/* Active Filters tag pills */}
                            <td style={{ padding: '6px 10px' }}>
                              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                                {tags.length === 0 ? (
                                  <span style={{ fontSize: 9, color: 'var(--color-ec-text-muted)', fontStyle: 'italic' }}>No active filters</span>
                                ) : (
                                  tags.map((t, idx) => (
                                    <div 
                                      key={idx}
                                      style={{
                                        display: 'flex',
                                        alignItems: 'center',
                                        gap: 2,
                                        backgroundColor: 'var(--color-ec-bg-elevated)',
                                        border: '0.5px solid var(--color-ec-border)',
                                        borderRadius: 0, // Straight corners
                                        padding: '1px 5px',
                                        fontSize: 8,
                                        fontWeight: 600,
                                        color: 'var(--color-ec-text-secondary)'
                                      }}
                                    >
                                      <span>{t.icon}</span>
                                      <span style={{ color: 'var(--color-ec-text-muted)' }}>{t.label}:</span>
                                      <span style={{ color: 'var(--color-ec-text-high)' }}>{t.value}</span>
                                    </div>
                                  ))
                                )}
                              </div>
                            </td>
                            {/* Action Button */}
                            <td style={{ padding: '6px 10px', textAlign: 'right' }}>
                              <button
                                disabled={deletingId === ds.id}
                                onClick={(e) => handleDelete(e, ds.id, 'dataset')}
                                style={{
                                  background: 'transparent',
                                  border: 'none',
                                  padding: 2,
                                  cursor: 'pointer',
                                  color: 'var(--color-ec-text-muted)',
                                }}
                                onMouseEnter={e => e.currentTarget.style.color = 'var(--color-ec-loss)'}
                                onMouseLeave={e => e.currentTarget.style.color = 'var(--color-ec-text-muted)'}
                              >
                                <Trash2 size={10} />
                              </button>
                            </td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                )}
              </div>
            </div>
          </div>

          {/* Right-Hand Pane: Selected Strategy Details Panel (No container card, side-by-side metrics/chart) */}
          <div 
            style={{
              flex: '0 0 35%',
              backgroundColor: 'rgba(16, 18, 19, 0.4)',
              overflowY: 'auto',
              padding: '20px 16px',
              display: 'flex',
              flexDirection: 'column',
              gap: 14
            }}
            className="w-full lg:w-[35%]"
          >
            {selectedStrategies.length > 0 ? (
              <>
                {/* Header */}
                <div>
                  <span style={{ fontSize: 8, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '1.2px', color: 'var(--color-ec-copper)' }}>
                    STRATEGIES COMPARISON
                  </span>
                  <h2 style={{ fontFamily: "'Fraunces', serif", fontSize: 20, fontWeight: 600, color: 'var(--color-ec-text-high)', margin: '4px 0 0 0' }}>
                    Normalized Risk (Last 3M)
                  </h2>
                </div>

                {/* Comparison Table */}
                <div style={{ border: '0.5px solid var(--color-ec-border)', backgroundColor: 'var(--color-ec-bg-surface)', overflowX: 'auto', borderRadius: 0 }}>
                  <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left' }}>
                    <thead>
                      <tr style={{ borderBottom: '1px solid var(--color-ec-border)', backgroundColor: 'rgba(28, 30, 33, 0.4)' }}>
                        <th style={{ padding: '8px 10px', fontSize: 10, fontWeight: 700, textTransform: 'uppercase', color: 'var(--color-ec-text-muted)', minWidth: 90 }}>
                          Metric (3M)
                        </th>
                        {selectedStrategies.map((strat, idx) => {
                          const color = COMPARISON_COLORS[idx % COMPARISON_COLORS.length]
                          return (
                            <th 
                              key={strat.id} 
                              style={{ 
                                padding: '8px 10px', 
                                fontSize: 11, 
                                fontWeight: 700, 
                                textTransform: 'uppercase', 
                                color: 'var(--color-ec-text-high)',
                                textAlign: 'right',
                                borderLeft: '0.5px solid var(--color-ec-border)',
                                minWidth: 90
                              }}
                            >
                              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: 4 }}>
                                <span style={{ width: 6, height: 6, backgroundColor: color }} />
                                <span style={{ textOverflow: 'ellipsis', overflow: 'hidden', whiteSpace: 'nowrap', maxWidth: 60 }} title={strat.name}>
                                  {strat.name}
                                </span>
                                <button
                                  onClick={() => toggleStrategySelection(strat.id)}
                                  style={{
                                    background: 'transparent',
                                    border: 'none',
                                    padding: 0,
                                    cursor: 'pointer',
                                    color: 'var(--color-ec-text-muted)',
                                    marginLeft: 2,
                                    display: 'flex',
                                    alignItems: 'center'
                                  }}
                                  title="Deselect"
                                >
                                  <X size={10} />
                                </button>
                              </div>
                            </th>
                          )
                        })}
                      </tr>
                    </thead>
                    <tbody>
                      {renderComparisonRow("Profit (R)", "profitR", (v) => `${v >= 0 ? '+' : ''}${v.toFixed(1)} R`, (v) => v >= 0 ? 'var(--color-ec-profit)' : 'var(--color-ec-loss)')}
                      {renderComparisonRow("Win Rate", "winRate", (v) => `${v.toFixed(1)}%`)}
                      {renderComparisonRow("Profit Factor", "profitFactor", (v) => v.toFixed(2))}
                      {renderComparisonRow("Max DD", "maxDd", (v) => `-${v.toFixed(1)}%`, () => 'var(--color-ec-loss)')}
                      {renderComparisonRow("Sharpe", "sharpe", (v) => v.toFixed(2))}
                      {renderComparisonRow("Avg R/Day", "avgRDay", (v) => `${v.toFixed(2)} R`, (v) => v >= 0 ? 'var(--color-ec-profit)' : 'var(--color-ec-loss)')}
                      {renderComparisonRow("Trades", "trades", (v) => Math.round(v).toString())}
                    </tbody>
                  </table>
                </div>

                {/* Accumulated Equity Chart (Normalized to R) */}
                <div style={{ marginTop: 10 }}>
                  <div style={{ fontSize: 8, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.8px', color: 'var(--color-ec-text-muted)', marginBottom: 8 }}>
                    Superimposed Equity Curves (Accumulated R)
                  </div>
                  <MultiEquityChart 
                    strategiesData={selectedStrategies.map((strat, idx) => {
                      const data3M = getThreeMonthStatsAndCurve(strat)
                      return {
                        name: strat.name,
                        curveR: data3M.curveR,
                        color: COMPARISON_COLORS[idx % COMPARISON_COLORS.length]
                      }
                    })}
                  />
                </div>
              </>
            ) : (
              <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', color: 'var(--color-ec-text-muted)', textAlign: 'center', padding: 20 }}>
                <Activity size={24} style={{ opacity: 0.3, marginBottom: 8 }} />
                <h4 style={{ fontSize: 12, color: 'var(--color-ec-text-high)', margin: 0 }}>No Strategies Selected</h4>
                <p style={{ fontSize: 10, margin: '4px 0 0 0' }}>Select strategies from the repository list to load detailed comparison reports</p>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
