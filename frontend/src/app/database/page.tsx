'use client'

import { useState, useEffect } from 'react'
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
  Minus
} from 'lucide-react'
import { 
  getStrategies, 
  getQueries, 
  getSavedBacktests, 
  deleteStrategy, 
  deleteQuery 
} from '@/lib/api'

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

export default function TrunkPage() {
  const router = useRouter()
  const [strategies, setStrategies] = useState<any[]>([])
  const [incubatorStrategies, setIncubatorStrategies] = useState<any[]>([])
  const [datasets, setDatasets] = useState<any[]>([])
  const [backtests, setBacktests] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  
  const [selectedStrategyId, setSelectedStrategyId] = useState<string | null>(null)
  const [showChart, setShowChart] = useState(false)
  
  const [deletingId, setDeletingId] = useState<string | null>(null)
  const [deletingType, setDeletingType] = useState<'strategy' | 'dataset' | null>(null)

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

  // Reset showChart when strategy selection changes
  useEffect(() => {
    setShowChart(false)
  }, [selectedStrategyId])

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
      
      if (strategiesData.length > 0) {
        setSelectedStrategyId(strategiesData[0].id ?? null)
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
        if (selectedStrategyId === id) {
          const remaining = strategies.filter(s => s.id !== id)
          setSelectedStrategyId(remaining.length > 0 ? remaining[0].id : null)
        }
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

  // Resolves stats for a strategy (only keeping the last 6 months)
  const getStats = (strat: any) => {
    const realBt = backtests.find(bt => {
      const ids = bt.strategy_ids || []
      return ids.includes(strat.id)
    })

    if (realBt) {
      let curve: number[] = []
      let period = 'N/A'
      let avgRDay = 0
      try {
        const results = typeof realBt.results_json === 'string' 
          ? JSON.parse(realBt.results_json) 
          : realBt.results_json
        const rawCurve = results?.equity_curve || []
        
        // Filter by date for the last 6 months if timestamps are present
        if (rawCurve.length > 0 && rawCurve[0].timestamp) {
          const sorted = [...rawCurve].sort((a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime())
          const latestTime = new Date(sorted[sorted.length - 1].timestamp).getTime()
          const sixMonthsAgo = latestTime - (6 * 30.5 * 24 * 60 * 60 * 1000) // approx 6 months in ms
          const filtered = sorted.filter(item => new Date(item.timestamp).getTime() >= sixMonthsAgo)
          
          // Use filtered or fallback to last 120 points
          const finalCurve = filtered.length >= 5 ? filtered : sorted.slice(-120)
          curve = finalCurve.map((c: any) => c.balance || 0)
        } else {
          curve = rawCurve.map((c: any) => c.balance || 0).slice(-120)
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
        const totalR = realBt.total_return_r || 0
        const uniqueDays = new Set(trades.map((t: any) => t.entry_time?.split('T')[0])).size
        avgRDay = uniqueDays > 0 ? totalR / uniqueDays : 0
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
        isValidated: realBt.is_validated !== undefined ? realBt.is_validated : (realBt.win_rate >= 50 && realBt.sharpe_ratio > 1.5)
      }
    }

    // Pre-seeded fallback
    const key = strat.id || ''
    const name = strat.name || ''
    if (key === 'mock_strategy_1' || name === 'VWAP Reclaim Long') {
      return { ...MOCK_STRATEGY_STATS['mock_strategy_1'], isReal: false }
    }
    if (key === 'mock_strategy_2' || name === 'Opening Range Breakdown Short') {
      return { ...MOCK_STRATEGY_STATS['mock_strategy_2'], isReal: false }
    }
    if (key === 'mock_strategy_3' || name === 'EMA 9/20 Cross Long') {
      return { ...MOCK_STRATEGY_STATS['mock_strategy_3'], isReal: false }
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
      isValidated: false
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
      tags.push({ label: 'Rules', value: `${filters.rules.length} custom`, icon: '⚙️' })
    }

    return tags
  }

  // Get current active strategy details
  const activeStrategy = strategies.find(s => s.id === selectedStrategyId)
  const activeStats = activeStrategy ? getStats(activeStrategy) : null

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

  const sampledCurve = activeStats ? getSampledCurve(activeStats.equityCurve) : []
  const slicedStats = activeStats ? getSlicedStats(sampledCurve, activeStats) : null

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
                <th style={{ padding: '6px 10px', fontSize: 8, fontWeight: 700, textTransform: 'uppercase', color: 'var(--color-ec-text-muted)' }}>Period OOS</th>
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
                const isSelected = strat.id === selectedStrategyId
                const isPositive = stats.winRate ? stats.winRate >= 50 : true
                
                return (
                  <tr
                    key={strat.id}
                    onClick={() => setSelectedStrategyId(strat.id)}
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
                    <td style={{ padding: '6px 10px' }}>
                      <div style={{ fontWeight: 600, fontSize: 12, color: 'var(--color-ec-text-high)' }}>{strat.name}</div>
                      {strat.description && (
                        <div style={{ fontSize: 9, color: 'var(--color-ec-text-muted)', marginTop: 1, textOverflow: 'ellipsis', overflow: 'hidden', whiteSpace: 'nowrap', maxWidth: 120 }}>
                          {strat.description}
                        </div>
                      )}
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
                    <td style={{ padding: '6px 10px', fontSize: 9, color: 'var(--color-ec-text-muted)', whiteSpace: 'nowrap' }}>
                      {stats.period}
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
                      <span
                        style={{
                          fontSize: 8,
                          fontWeight: 700,
                          padding: '1px 5px',
                          borderRadius: 0,
                          textTransform: 'uppercase',
                          backgroundColor: stats.isValidated ? 'rgba(74, 157, 127, 0.12)' : 'rgba(201, 77, 63, 0.12)',
                          color: stats.isValidated ? 'var(--color-ec-profit)' : 'var(--color-ec-loss)',
                          border: stats.isValidated ? '0.5px solid rgba(74, 157, 127, 0.25)' : '0.5px solid rgba(201, 77, 63, 0.25)'
                        }}
                      >
                        {stats.isValidated ? 'YES' : 'NO'}
                      </span>
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
            TRUNK REPOSITORY
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
            {activeStrategy ? (
              <>
                {/* Details Header */}
                <div>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                    <span style={{ fontSize: 8, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '1px', color: 'var(--color-ec-copper)' }}>
                      STRATEGY REPORT
                    </span>
                    <span 
                      style={{ 
                        fontSize: 8, 
                        fontWeight: 700, 
                        padding: '1px 5px', 
                        borderRadius: 0, // Straight corners
                        textTransform: 'uppercase',
                        backgroundColor: activeStrategy.bias === 'short' ? 'rgba(201, 77, 63, 0.15)' : 'rgba(74, 157, 127, 0.15)',
                        color: activeStrategy.bias === 'short' ? 'var(--color-ec-loss)' : 'var(--color-ec-profit)',
                        border: activeStrategy.bias === 'short' ? '0.5px solid rgba(201, 77, 63, 0.3)' : '0.5px solid rgba(74, 157, 127, 0.3)'
                      }}
                    >
                      {activeStrategy.bias}
                    </span>
                  </div>
                  <h2 style={{ fontFamily: "'Fraunces', serif", fontSize: 18, fontWeight: 600, color: 'var(--color-ec-text-high)', margin: '4px 0 0 0' }}>
                    {activeStrategy.name}
                  </h2>
                </div>

                {/* Side-by-Side metrics (Title on left, value on right) and chart */}
                <div style={{ display: 'flex', flexDirection: 'row', gap: 14, alignItems: 'stretch', marginTop: 10 }}>
                  
                  {/* Left Column: Metrics directly on background (Title and value in one line) */}
                  <div style={{ flex: '0 0 140px', display: 'flex', flexDirection: 'column', gap: 6 }}>
                    {slicedStats ? (
                      <>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '0.5px solid rgba(44, 47, 51, 0.25)', paddingBottom: 4 }}>
                          <span style={{ fontSize: 7, fontWeight: 700, color: 'var(--color-ec-text-muted)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>TOTAL PROFIT</span>
                          <span style={{ fontSize: 10, fontWeight: 700, color: slicedStats.profit >= 0 ? 'var(--color-ec-profit)' : 'var(--color-ec-loss)' }}>
                            {slicedStats.profit >= 0 ? '+' : ''}${slicedStats.profit.toFixed(1)}
                          </span>
                        </div>
                        
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '0.5px solid rgba(44, 47, 51, 0.25)', paddingBottom: 4 }}>
                          <span style={{ fontSize: 7, fontWeight: 700, color: 'var(--color-ec-text-muted)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>CAGR</span>
                          <span style={{ fontSize: 9, fontWeight: 600, color: 'var(--color-ec-text-high)' }}>
                            {((slicedStats.profit / 10000) * 100).toFixed(2)}%
                          </span>
                        </div>

                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '0.5px solid rgba(44, 47, 51, 0.25)', paddingBottom: 4 }}>
                          <span style={{ fontSize: 7, fontWeight: 700, color: 'var(--color-ec-text-muted)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>PERIOD</span>
                          <span style={{ fontSize: 9, fontWeight: 600, color: 'var(--color-ec-text-high)' }}>
                            {activeStats?.period}
                          </span>
                        </div>

                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '0.5px solid rgba(44, 47, 51, 0.25)', paddingBottom: 4 }}>
                          <span style={{ fontSize: 7, fontWeight: 700, color: 'var(--color-ec-text-muted)', textTransform: 'uppercase', letterSpacing: '0.5px' }}># TRADES</span>
                          <span style={{ fontSize: 9, fontWeight: 700, color: 'var(--color-ec-profit)' }}>
                            {slicedStats.trades}
                          </span>
                        </div>

                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '0.5px solid rgba(44, 47, 51, 0.25)', paddingBottom: 4 }}>
                          <span style={{ fontSize: 7, fontWeight: 700, color: 'var(--color-ec-text-muted)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>AVG R/DAY</span>
                          <span style={{ fontSize: 9, fontWeight: 600, color: 'var(--color-ec-profit)' }}>
                            {activeStats?.avgRDay != null ? `${activeStats.avgRDay.toFixed(2)} R` : '—'}
                          </span>
                        </div>

                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '0.5px solid rgba(44, 47, 51, 0.25)', paddingBottom: 4 }}>
                          <span style={{ fontSize: 7, fontWeight: 700, color: 'var(--color-ec-text-muted)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>SHARPE</span>
                          <span style={{ fontSize: 9, fontWeight: 600, color: 'var(--color-ec-text-high)' }}>
                            {slicedStats.sharpe.toFixed(2)}
                          </span>
                        </div>

                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '0.5px solid rgba(44, 47, 51, 0.25)', paddingBottom: 4 }}>
                          <span style={{ fontSize: 7, fontWeight: 700, color: 'var(--color-ec-text-muted)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>PROFIT FAC.</span>
                          <span style={{ fontSize: 9, fontWeight: 600, color: 'var(--color-ec-text-high)' }}>
                            {slicedStats.profitFactor.toFixed(2)}
                          </span>
                        </div>

                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '0.5px solid rgba(44, 47, 51, 0.25)', paddingBottom: 4 }}>
                          <span style={{ fontSize: 7, fontWeight: 700, color: 'var(--color-ec-text-muted)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>WIN %</span>
                          <span style={{ fontSize: 9, fontWeight: 600, color: 'var(--color-ec-text-high)' }}>
                            {slicedStats.winRate.toFixed(1)}%
                          </span>
                        </div>

                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '0.5px solid rgba(44, 47, 51, 0.25)', paddingBottom: 4 }}>
                          <span style={{ fontSize: 7, fontWeight: 700, color: 'var(--color-ec-text-muted)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>DRAWDOWN</span>
                          <span style={{ fontSize: 9, fontWeight: 600, color: 'var(--color-ec-loss)' }}>
                            -${slicedStats.maxDdVal.toFixed(1)}
                          </span>
                        </div>

                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '0.5px solid rgba(44, 47, 51, 0.25)', paddingBottom: 4 }}>
                          <span style={{ fontSize: 7, fontWeight: 700, color: 'var(--color-ec-text-muted)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>% DRAWDOWN</span>
                          <span style={{ fontSize: 9, fontWeight: 600, color: 'var(--color-ec-loss)' }}>
                            {slicedStats.maxDd.toFixed(2)}%
                          </span>
                        </div>

                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                          <span style={{ fontSize: 7, fontWeight: 700, color: 'var(--color-ec-text-muted)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>VALIDATED</span>
                          <span style={{ fontSize: 8, fontWeight: 700, padding: '1px 4px', textTransform: 'uppercase', backgroundColor: slicedStats.isValidated ? 'rgba(74, 157, 127, 0.12)' : 'rgba(201, 77, 63, 0.12)', color: slicedStats.isValidated ? 'var(--color-ec-profit)' : 'var(--color-ec-loss)', border: slicedStats.isValidated ? '0.5px solid rgba(74, 157, 127, 0.25)' : '0.5px solid rgba(201, 77, 63, 0.25)' }}>
                            {slicedStats.isValidated ? 'PASSED' : 'FAILED'}
                          </span>
                        </div>
                      </>
                    ) : (
                      <div style={{ fontSize: 10, color: 'var(--color-ec-text-muted)', fontStyle: 'italic' }}>No stats</div>
                    )}
                  </div>

                  {/* Thin vertical dividing line */}
                  <div style={{ width: '0.5px', backgroundColor: 'var(--color-ec-border)', alignSelf: 'stretch', margin: '0 4px' }} />

                  {/* Right Column: Chart / Load Button Placeholder */}
                  <div style={{ flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'center' }}>
                    {!showChart ? (
                      <button
                        onClick={() => setShowChart(true)}
                        style={{
                          background: 'rgba(28, 30, 33, 0.2)',
                          border: '0.5px solid var(--color-ec-border)',
                          borderRadius: 0, // Straight corners
                          color: 'var(--color-ec-copper)',
                          padding: '8px 12px',
                          fontSize: 9,
                          fontWeight: 700,
                          textTransform: 'uppercase',
                          letterSpacing: '0.5px',
                          cursor: 'pointer',
                          height: 120,
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                          textAlign: 'center',
                          transition: 'all 150ms ease'
                        }}
                        onMouseEnter={e => {
                          e.currentTarget.style.backgroundColor = 'rgba(216, 122, 61, 0.05)'
                          e.currentTarget.style.borderColor = 'var(--color-ec-copper)'
                        }}
                        onMouseLeave={e => {
                          e.currentTarget.style.backgroundColor = 'rgba(28, 30, 33, 0.2)'
                          e.currentTarget.style.borderColor = 'var(--color-ec-border)'
                        }}
                      >
                        Cargar Gráfico
                      </button>
                    ) : (
                      <div>
                        <div style={{ fontSize: 8, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.5px', color: 'var(--color-ec-text-muted)', marginBottom: 6 }}>
                          Equity & Drawdown (Last 6M)
                        </div>
                        <DetailedEquityChart points={sampledCurve} />
                        {activeStats?.winRate && (
                          <div style={{ textAlign: 'center', marginTop: 4, fontSize: 7, color: 'var(--color-ec-text-muted)', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.5px' }}>
                            {activeStats?.isReal ? 'Live Backtest Session' : 'Sample Preset Simulation'}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              </>
            ) : (
              <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', color: 'var(--color-ec-text-muted)', textAlign: 'center', padding: 20 }}>
                <Activity size={24} style={{ opacity: 0.3, marginBottom: 8 }} />
                <h4 style={{ fontSize: 12, color: 'var(--color-ec-text-high)', margin: 0 }}>No Strategy Selected</h4>
                <p style={{ fontSize: 10, margin: '4px 0 0 0' }}>Select a strategy from the repository list to load the detailed audit report</p>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
