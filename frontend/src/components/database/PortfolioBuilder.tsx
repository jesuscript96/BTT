'use client'

/**
 * PortfolioBuilder — PRD_portfolio_FIX_metricas_UI_ANTIGRAVITY (Part 2: UI).
 *
 * F1 Constructor: multi-select 2+ saved strategies, % equity per strategy,
 *   shared range, exposure cap → POST /api/portfolio/run.
 * F2 Results (REBUILT): full-width, date-axis equity chart + hover tooltip,
 *   metric cards with tooltips, readable correlation matrix, combined-vs-
 *   standalone table with diversification highlight, per-strategy contribution.
 * F3 Live sliders: weight change → POST /api/portfolio/recombine (debounced).
 * F4 Save: POST /api/portfolio/save → persists into backtest_results.
 *
 * Layout rule (PRD U2): when a result exists the builder collapses to a narrow
 * sidebar and the results take the remaining width with a single page scroll
 * (no internal box-scroll on the tables). Metric numbers come from the backend
 * (which now reuses the normal backtester's metrics — PRD Part 1).
 */
import React, { useCallback, useEffect, useRef, useState } from 'react'
import { Play, Save, Layers, AlertCircle, Activity, Check, Info, Database } from 'lucide-react'
import {
    runPortfolio,
    recombinePortfolio,
    getPortfolioStatus,
    getPortfolioResult,
    savePortfolio,
    type PortfolioResult,
    type PortfolioMetrics,
    type PortfolioItem,
} from '@/lib/api'

// Same palette as the Baúl comparison chart.
const STRAT_COLORS = [
    'var(--color-ec-copper)',
    'var(--color-ec-profit)',
    '#3b82f6',
    '#a855f7',
    '#eab308',
    '#ec4899',
]

const fmtPct = (v: number | null | undefined, digits = 2) =>
    v === null || v === undefined || Number.isNaN(v) ? '—' : `${v.toFixed(digits)}%`

const fmtNum = (v: number | null | undefined, digits = 2) =>
    v === null || v === undefined || Number.isNaN(v) ? 'N/A' : v.toFixed(digits)

const fmtMoney = (v: number | null | undefined) =>
    v === null || v === undefined || Number.isNaN(v)
        ? '—'
        : `$${v.toLocaleString('en-US', { maximumFractionDigits: 0 })}`

const fmtDate = (epoch: number) => {
    const d = new Date(epoch * 1000)
    return d.toLocaleDateString('en-US', {
        day: '2-digit',
        month: 'short',
        year: '2-digit',
        timeZone: 'UTC',
    })
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

/** Color for a correlation cell: -1 (green = good diversification) → +1 (red). */
function corrColor(c: number): string {
    if (c === null || c === undefined || Number.isNaN(c)) return 'transparent'
    const alpha = 0.32
    if (c >= 0) return `rgba(201, 77, 63, ${Math.max(0, c) * alpha})`
    return `rgba(74, 157, 127, ${Math.max(0, -c) * alpha})`
}

// ─── Tooltips (PRD U7) ──────────────────────────────────────────────────
const TOOLTIP_CSS = `
.pf-tip { position: relative; display: inline-flex; align-items: center; cursor: help; }
.pf-tip__bubble {
  position: absolute; bottom: calc(100% + 6px); left: 50%; transform: translateX(-50%);
  background: var(--color-ec-bg-sidebar, #111); color: var(--color-ec-text-secondary, #ccc);
  border: 0.5px solid var(--color-ec-border, #333); padding: 6px 8px; border-radius: 3px;
  width: max-content; max-width: 250px; font-size: 9px; line-height: 1.4; font-weight: 500;
  text-transform: none; letter-spacing: 0; white-space: normal; text-align: left;
  visibility: hidden; opacity: 0; transition: opacity 120ms ease; pointer-events: none; z-index: 50;
  box-shadow: 0 4px 14px rgba(0,0,0,0.4);
}
.pf-tip:hover .pf-tip__bubble { visibility: visible; opacity: 1; }
`

const METRIC_INFO: Record<string, string> = {
    total_return_pct: 'Net % gain/loss on the initial cash over the whole period.',
    max_drawdown_pct: 'Largest peak-to-trough drop of the equity curve (negative %).',
    sharpe: 'Risk-adjusted return, annualized. Higher = better. Unreliable with few trades.',
    calmar: 'Total return ÷ |max drawdown|. High = efficient return per unit of risk taken.',
    profit_factor: 'Gross profit ÷ gross loss. Above 1 means profitable.',
    win_rate: '% of closed trades that ended in profit.',
    sortino: 'Like Sharpe but only penalizes downside volatility.',
    total_trades: 'Number of closed trades in the period.',
    final_equity: 'Equity at the end of the period ($).',
}

const InfoDot = ({ text }: { text: string }) => (
    <span className="pf-tip" style={{ marginLeft: 4 }}>
        <Info size={11} color="var(--color-ec-text-muted)" strokeWidth={2.5} />
        <span className="pf-tip__bubble">{text}</span>
    </span>
)

const SectionTitle = ({ children, tip }: { children: React.ReactNode; tip?: string }) => (
    <div
        style={{
            fontSize: 10,
            fontWeight: 700,
            textTransform: 'uppercase',
            letterSpacing: '0.8px',
            color: 'var(--color-ec-text-muted)',
            marginBottom: 8,
            display: 'flex',
            alignItems: 'center',
        }}
    >
        {children}
        {tip && <InfoDot text={tip} />}
    </div>
)

// ─── Combined equity SVG chart: date X-axis + $ Y-axis + hover tooltip ────
const EquityChart = ({
    curve,
    color,
}: {
    curve: { time: number; value: number }[]
    color: string
}) => {
    const [hover, setHover] = useState<{ i: number } | null>(null)

    if (!curve || curve.length < 2) {
        return (
            <div
                style={{
                    height: 240,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    border: '1px dashed var(--color-ec-border)',
                    color: 'var(--color-ec-text-muted)',
                    fontSize: 11,
                }}
            >
                No equity data
            </div>
        )
    }

    const vals = curve.map((p) => p.value)
    const times = curve.map((p) => p.time)
    const tMin = Math.min(...times)
    const tMax = Math.max(...times)
    const minV = Math.min(...vals)
    const maxV = Math.max(...vals)
    const rangeV = maxV - minV || 1
    const rangeT = tMax - tMin || 1
    const W = 820
    const H = 250
    const padL = 64
    const padR = 16
    const padT = 14
    const padB = 30
    const x = (t: number) => padL + ((t - tMin) / rangeT) * (W - padL - padR)
    const y = (v: number) => padT + (1 - (v - minV) / rangeV) * (H - padT - padB)

    // Drawdown (%) at each point — shown in the hover tooltip.
    let peak = -Infinity
    const ddAt = vals.map((v) => {
        peak = Math.max(peak, v)
        return peak > 0 ? ((v - peak) / peak) * 100 : 0
    })

    const linePath = curve
        .map((p, i) => `${i === 0 ? 'M' : 'L'} ${x(p.time).toFixed(1)} ${y(p.value).toFixed(1)}`)
        .join(' ')
    const baseY = y(minV)
    const fillPath = `M ${x(times[0]).toFixed(1)} ${baseY.toFixed(1)} ${linePath.substring(1)} L ${x(
        times[times.length - 1],
    ).toFixed(1)} ${baseY.toFixed(1)} Z`
    const isUp = vals[vals.length - 1] >= vals[0]
    const ticks = Array.from({ length: 5 }, (_, k) => tMin + (k / 4) * rangeT)

    const onMove = (e: React.MouseEvent<SVGSVGElement>) => {
        const rect = e.currentTarget.getBoundingClientRect()
        const px = ((e.clientX - rect.left) / rect.width) * W
        let best = 0
        let bd = Infinity
        for (let i = 0; i < times.length; i++) {
            const d = Math.abs(x(times[i]) - px)
            if (d < bd) {
                bd = d
                best = i
            }
        }
        setHover({ i: best })
    }

    const hp = hover ? curve[hover.i] : null
    const hpDD = hover ? ddAt[hover.i] : 0

    return (
        <div style={{ position: 'relative', width: '100%' }}>
            <svg
                width="100%"
                viewBox={`0 0 ${W} ${H}`}
                style={{ overflow: 'visible', display: 'block' }}
                onMouseMove={onMove}
                onMouseLeave={() => setHover(null)}
            >
                {[0, 0.25, 0.5, 0.75, 1].map((f) => {
                    const gy = padT + f * (H - padT - padB)
                    const gv = maxV - f * rangeV
                    return (
                        <g key={f}>
                            <line
                                x1={padL}
                                y1={gy}
                                x2={W - padR}
                                y2={gy}
                                stroke="rgba(255,255,255,0.06)"
                                strokeWidth="0.5"
                            />
                            <text
                                x={padL - 8}
                                y={gy + 3}
                                textAnchor="end"
                                fontSize="9"
                                fill="var(--color-ec-text-muted)"
                                fontFamily="monospace"
                            >
                                {fmtMoney(gv)}
                            </text>
                        </g>
                    )
                })}
                {ticks.map((t, k) => (
                    <text
                        key={k}
                        x={x(t)}
                        y={H - 10}
                        textAnchor="middle"
                        fontSize="9"
                        fill="var(--color-ec-text-muted)"
                        fontFamily="monospace"
                    >
                        {fmtDate(t)}
                    </text>
                ))}
                <path d={fillPath} fill={isUp ? 'rgba(74,157,127,0.14)' : 'rgba(201,77,63,0.14)'} />
                <path d={linePath} fill="none" stroke={color} strokeWidth="1.6" />
                {hp && (
                    <>
                        <line
                            x1={x(hp.time)}
                            y1={padT}
                            x2={x(hp.time)}
                            y2={H - padB}
                            stroke="rgba(255,255,255,0.2)"
                            strokeWidth="0.5"
                            strokeDasharray="2 2"
                        />
                        <circle
                            cx={x(hp.time)}
                            cy={y(hp.value)}
                            r="3.2"
                            fill={color}
                            stroke="var(--color-ec-bg-base)"
                            strokeWidth="1"
                        />
                    </>
                )}
                <circle cx={x(times[times.length - 1])} cy={y(vals[vals.length - 1])} r="2.5" fill={color} />
            </svg>
            {hp && hover && (
                <div
                    style={{
                        position: 'absolute',
                        left: `${(x(hp.time) / W) * 100}%`,
                        top: y(hp.value),
                        transform: 'translate(-50%, -135%)',
                        background: 'var(--color-ec-bg-sidebar)',
                        border: '0.5px solid var(--color-ec-border)',
                        padding: '5px 8px',
                        fontSize: 10,
                        fontFamily: 'monospace',
                        whiteSpace: 'nowrap',
                        pointerEvents: 'none',
                        zIndex: 20,
                    }}
                >
                    <div style={{ color: 'var(--color-ec-text-muted)', fontSize: 9 }}>{fmtDate(hp.time)}</div>
                    <div style={{ color: 'var(--color-ec-text-high)' }}>{fmtMoney(hp.value)}</div>
                    <div style={{ color: 'var(--color-ec-loss)', fontSize: 9 }}>DD {hpDD.toFixed(2)}%</div>
                </div>
            )}
        </div>
    )
}

// ─── Correlation matrix (readable: full labels + legend) ─────────────────
const CorrelationMatrix = ({ matrix, labels }: { matrix: number[][]; labels: string[] }) => {
    if (!matrix || matrix.length < 2) {
        return (
            <div style={{ fontSize: 11, color: 'var(--color-ec-text-muted)' }}>
                Need 2+ strategies for correlation.
            </div>
        )
    }
    return (
        <div>
            <div
                style={{
                    display: 'flex',
                    gap: 16,
                    marginBottom: 12,
                    fontSize: 9,
                    color: 'var(--color-ec-text-muted)',
                    flexWrap: 'wrap',
                    alignItems: 'center',
                }}
            >
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}>
                    <span style={{ width: 12, height: 12, background: 'rgba(74,157,127,0.5)', display: 'inline-block' }} />
                    green = diversifies (negative)
                </span>
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}>
                    <span style={{ width: 12, height: 12, background: 'rgba(201,77,63,0.5)', display: 'inline-block' }} />
                    red = correlated (positive)
                </span>
            </div>
            <div style={{ overflowX: 'auto' }}>
                <table style={{ borderCollapse: 'collapse', width: '100%', fontSize: 11 }}>
                    <thead>
                        <tr>
                            <th style={{ padding: '8px 10px' }}></th>
                            {labels.map((l, j) => (
                                <th
                                    key={j}
                                    style={{
                                        padding: '8px 10px',
                                        fontSize: 10,
                                        fontWeight: 700,
                                        color: STRAT_COLORS[j % STRAT_COLORS.length],
                                        textAlign: 'center',
                                        whiteSpace: 'nowrap',
                                    }}
                                    title={l}
                                >
                                    {l}
                                </th>
                            ))}
                        </tr>
                    </thead>
                    <tbody>
                        {matrix.map((row, i) => (
                            <tr key={i}>
                                <td
                                    style={{
                                        padding: '8px 12px 8px 0',
                                        fontSize: 10,
                                        fontWeight: 700,
                                        color: STRAT_COLORS[i % STRAT_COLORS.length],
                                        whiteSpace: 'nowrap',
                                    }}
                                    title={labels[i]}
                                >
                                    {labels[i]}
                                </td>
                                {row.map((c, j) => (
                                    <td
                                        key={j}
                                        style={{
                                            padding: '11px 14px',
                                            textAlign: 'center',
                                            fontFamily: 'monospace',
                                            fontSize: 12,
                                            fontWeight: 600,
                                            backgroundColor: corrColor(c),
                                            color: 'var(--color-ec-text-high)',
                                            border: '0.5px solid rgba(255,255,255,0.04)',
                                        }}
                                    >
                                        {c.toFixed(2)}
                                    </td>
                                ))}
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
        </div>
    )
}

interface Props {
    strategies: any[]
}

export default function PortfolioBuilder({ strategies }: Props) {
    const [selectedIds, setSelectedIds] = useState<string[]>([])
    const [weights, setWeights] = useState<Record<string, number>>({})
    const [weightUnit, setWeightUnit] = useState<'pct' | 'usd'>('pct')
    const [initCash, setInitCash] = useState(10000)
    const [maxExposure, setMaxExposure] = useState(100)
    const [sizingMode, setSizingMode] = useState<'fixed' | 'daily_compound'>('fixed')

    const [result, setResult] = useState<PortfolioResult | null>(null)
    const [portfolioId, setPortfolioId] = useState<string | null>(null)
    const [running, setRunning] = useState(false)
    const [progress, setProgress] = useState(0)
    const [error, setError] = useState<string | null>(null)
    const [saving, setSaving] = useState(false)
    const [savedMsg, setSavedMsg] = useState<string | null>(null)

    // Refs for the debounced recombine (need latest values inside the timeout).
    const weightsRef = useRef(weights)
    const weightUnitRef = useRef(weightUnit)
    const sizingModeRef = useRef(sizingMode)
    const recombineTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
    const portfolioIdRef = useRef<string | null>(null)
    const resultsRef = useRef<HTMLDivElement>(null)
    useEffect(() => {
        weightsRef.current = weights
    }, [weights])
    useEffect(() => {
        weightUnitRef.current = weightUnit
    }, [weightUnit])
    useEffect(() => {
        sizingModeRef.current = sizingMode
    }, [sizingMode])
    useEffect(() => {
        portfolioIdRef.current = portfolioId
    }, [portfolioId])

    // U6: scroll the results into view when a result lands.
    useEffect(() => {
        if (result && resultsRef.current) {
            resultsRef.current.scrollIntoView({ behavior: 'smooth', block: 'start' })
        }
    }, [result])

    const activeStrategies = strategies.filter((s) => !s.in_incubator)

    const toggleStrategy = (id: string) => {
        setSelectedIds((prev) => {
            const next = prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]
            setWeights((w) => {
                const nw = { ...w }
                if (!next.includes(id)) delete nw[id]
                else if (nw[id] === undefined) nw[id] = 5
                return nw
            })
            return next
        })
    }

    const totalWeight = selectedIds.reduce((s, id) => s + (weights[id] || 0), 0)
    const canBuild = selectedIds.length >= 2 && !running

    // Convert existing weights when switching % ↔ $ so values stay meaningful.
    const switchWeightUnit = (unit: 'pct' | 'usd') => {
        if (unit === weightUnit) return
        setWeights((prev) => {
            const next: Record<string, number> = {}
            for (const [id, w] of Object.entries(prev)) {
                next[id] =
                    unit === 'usd'
                        ? Math.round((w / 100) * initCash) // % → $
                        : Math.round(((w / (initCash || 1)) * 100) * 10) / 10 // $ → %
            }
            return next
        })
        setWeightUnit(unit)
    }

    // ── F1: build portfolio (sync or async) ──
    const pollJob = useCallback(async (jobId: string) => {
        for (let i = 0; i < 600; i++) {
            await sleep(1000)
            const st = await getPortfolioStatus(jobId)
            setProgress(st.percent || 0)
            if (st.status === 'succeeded') {
                const r = (await getPortfolioResult(jobId)) as PortfolioResult
                setPortfolioId(r.portfolio_id || portfolioIdRef.current)
                portfolioIdRef.current = r.portfolio_id || portfolioIdRef.current
                setResult(r)
                return
            }
            if (st.status === 'failed') {
                throw new Error(st.error || 'Portfolio run failed')
            }
        }
        throw new Error('Portfolio run timed out')
    }, [])

    const handleBuild = useCallback(async () => {
        if (!canBuild) return
        setRunning(true)
        setError(null)
        setResult(null)
        setSavedMsg(null)
        setProgress(0)
        try {
            const items: PortfolioItem[] = selectedIds.map((id) => ({
                strategy_id: id,
                pct_equity: weightsRef.current[id] ?? (weightUnitRef.current === 'usd' ? initCash / selectedIds.length : 5),
                weight_unit: weightUnitRef.current,
            }))
            const res = await runPortfolio({
                source: 'saved', // sum the SAVED runs (Baúl) — nothing is re-run
                dataset_id: null,
                date_from: null,
                date_to: null,
                items,
                init_cash: initCash,
                max_total_exposure_pct: maxExposure,
                sizing_mode: sizingModeRef.current,
            })
            // Async path: 202 + job_id → poll.
            if (
                res &&
                typeof res === 'object' &&
                'job_id' in res &&
                (res as { status: string }).status === 'running'
            ) {
                const acc = res as { job_id: string; portfolio_id: string }
                setPortfolioId(acc.portfolio_id)
                portfolioIdRef.current = acc.portfolio_id
                await pollJob(acc.job_id)
            } else {
                const r = res as PortfolioResult
                setPortfolioId(r.portfolio_id)
                portfolioIdRef.current = r.portfolio_id
                setResult(r)
            }
        } catch (e) {
            setError(e instanceof Error ? e.message : String(e))
        } finally {
            setRunning(false)
        }
    }, [canBuild, selectedIds, initCash, maxExposure, pollJob])

    // ── F3: live recombine on slider change (debounced ~150ms) ──
    const handleWeightChange = (id: string, pct: number) => {
        setWeights((prev) => ({ ...prev, [id]: pct }))
        const pfId = portfolioIdRef.current
        if (!pfId || !result) return // only after the first build
        if (recombineTimer.current) clearTimeout(recombineTimer.current)
        recombineTimer.current = setTimeout(async () => {
            try {
                const items: PortfolioItem[] = selectedIds.map((sid) => ({
                    strategy_id: sid,
                    pct_equity: weightsRef.current[sid] ?? 5,
                    weight_unit: weightUnitRef.current,
                }))
                const r = await recombinePortfolio({
                    portfolio_id: pfId,
                    items,
                    init_cash: initCash,
                    max_total_exposure_pct: maxExposure,
                    sizing_mode: sizingModeRef.current,
                })
                setResult(r)
            } catch {
                /* keep last good result on transient error */
            }
        }, 150)
    }

    useEffect(() => {
        return () => {
            if (recombineTimer.current) clearTimeout(recombineTimer.current)
        }
    }, [])

    // ── F4: save ──
    const handleSave = async () => {
        if (!result || !portfolioId) return
        setSaving(true)
        setSavedMsg(null)
        try {
            await savePortfolio({
                portfolio_id: portfolioId,
                result: result as unknown as Record<string, unknown>,
                label: result.label,
            })
            setSavedMsg('Saved to Baúl ✓')
        } catch (e) {
            setSavedMsg(`Save failed: ${e instanceof Error ? e.message : String(e)}`)
        } finally {
            setSaving(false)
        }
    }

    const labelFor = (sid: string) =>
        result?.strategy_names?.[sid] || activeStrategies.find((s) => s.id === sid)?.name || sid
    const agg = result?.aggregate_metrics

    const inputStyle: React.CSSProperties = {
        background: 'var(--color-ec-bg-base)',
        border: '0.5px solid var(--color-ec-border)',
        color: 'var(--color-ec-text-primary)',
        padding: '5px 8px',
        fontSize: 11,
        fontFamily: 'monospace',
        width: '100%',
        outline: 'none',
    }
    const sectionLabel: React.CSSProperties = {
        fontSize: 8,
        fontWeight: 700,
        textTransform: 'uppercase',
        letterSpacing: '1px',
        color: 'var(--color-ec-text-muted)',
        marginBottom: 5,
    }
    const cardStyle: React.CSSProperties = {
        border: '0.5px solid var(--color-ec-border)',
        backgroundColor: 'var(--color-ec-bg-surface)',
        padding: '14px 16px',
    }

    // Type-safe row definitions for the combined-vs-standalone table.
    const cmpRows: {
        label: string
        key: keyof PortfolioMetrics
        fmt: (v: number | null | undefined) => string
        col: (v: number | null | undefined) => string
        showSum: boolean
    }[] = [
            {
                label: 'Total Return %',
                key: 'total_return_pct',
                fmt: (v) => fmtPct(v),
                col: (v) => ((v ?? 0) >= 0 ? 'var(--color-ec-profit)' : 'var(--color-ec-loss)'),
                showSum: true,
            },
            { label: 'Max Drawdown %', key: 'max_drawdown_pct', fmt: (v) => fmtPct(v), col: () => 'var(--color-ec-loss)', showSum: true },
            { label: 'Sharpe', key: 'sharpe', fmt: (v) => fmtNum(v), col: () => 'var(--color-ec-text-high)', showSum: false },
            { label: 'Calmar', key: 'calmar', fmt: (v) => fmtNum(v), col: () => 'var(--color-ec-text-high)', showSum: false },
            { label: 'Profit Factor', key: 'profit_factor', fmt: (v) => fmtNum(v), col: () => 'var(--color-ec-text-high)', showSum: false },
            { label: 'Win Rate %', key: 'win_rate', fmt: (v) => fmtPct(v, 1), col: () => 'var(--color-ec-text-high)', showSum: false },
            { label: 'Trades', key: 'total_trades', fmt: (v) => String(v ?? 0), col: () => 'var(--color-ec-text-high)', showSum: true },
        ]

    // Diversification benefit: combined maxDD is less negative than the sum of standalones.
    const combinedDD = agg?.max_drawdown_pct ?? 0
    const sumDD = result
        ? result.strategy_order.reduce(
            (s, sid) => s + (result.standalone?.[sid]?.aggregate_metrics?.max_drawdown_pct ?? 0),
            0,
        )
        : 0
    const diversified = result && combinedDD > sumDD

    return (
        <div style={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0 }}>
            <style>{TOOLTIP_CSS}</style>
            {/* Header */}
            <div
                style={{
                    padding: '16px 24px 12px 24px',
                    borderBottom: '0.5px solid var(--color-ec-border)',
                    backgroundColor: 'var(--color-ec-bg-sidebar)',
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    flexShrink: 0,
                }}
            >
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                    <Layers size={18} color="var(--color-ec-copper)" />
                    <div>
                        <h1
                            style={{
                                fontFamily: "'Fraunces', serif",
                                fontSize: 22,
                                fontWeight: 600,
                                color: 'var(--color-ec-text-high)',
                                letterSpacing: '-0.5px',
                                margin: 0,
                            }}
                        >
                            Portfolio
                        </h1>
                        <p
                            style={{
                                fontSize: 9,
                                fontWeight: 700,
                                textTransform: 'uppercase',
                                letterSpacing: '1.2px',
                                color: 'var(--color-ec-text-muted)',
                                margin: '2px 0 0 0',
                            }}
                        >
                            Combine 2+ strategies weighted by % equity · diversification-aware
                        </p>
                    </div>
                </div>
            </div>

            {/* Split: constructor (collapses when results exist) | results (full width, page scroll) */}
            <div style={{ flex: 1, display: 'flex', minHeight: 0, overflow: 'hidden' }} className="flex-col lg:flex-row">
                {/* ─── LEFT: constructor ─── */}
                <div
                    style={{
                        flex: result ? '0 0 300px' : '0 0 42%',
                        borderRight: '0.5px solid var(--color-ec-border)',
                        overflowY: 'auto',
                        padding: '16px 18px',
                        display: 'flex',
                        flexDirection: 'column',
                        gap: 14,
                        backgroundColor: 'var(--color-ec-bg-base)',
                    }}
                    className={result ? 'w-full lg:w-[300px]' : 'w-full lg:w-[42%]'}
                >
                    {/* Strategy multi-select + weights */}
                    <div>
                        <div style={{ ...sectionLabel, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                            <span>Strategies ({selectedIds.length} · need ≥2)</span>
                            <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                                {selectedIds.length > 0 && (
                                    <span style={{ color: totalWeight > 100 ? 'var(--color-ec-loss)' : 'var(--color-ec-text-muted)' }}>
                                        {weightUnit === 'pct' ? `Σ ${totalWeight.toFixed(1)}%` : `Σ $${totalWeight.toLocaleString(undefined, { maximumFractionDigits: 0 })}`}
                                    </span>
                                )}
                                {/* Unit toggle: % equity | $ fijo */}
                                <span style={{ display: 'flex', border: '0.5px solid var(--color-ec-border)' }}>
                                    {(['pct', 'usd'] as const).map((u) => (
                                        <button
                                            key={u}
                                            onClick={() => switchWeightUnit(u)}
                                            style={{
                                                padding: '2px 7px',
                                                fontSize: 9,
                                                fontWeight: 700,
                                                cursor: 'pointer',
                                                border: 'none',
                                                color: weightUnit === u ? 'var(--color-ec-copper)' : 'var(--color-ec-text-muted)',
                                                backgroundColor: weightUnit === u ? 'rgba(216,122,61,0.08)' : 'transparent',
                                            }}
                                        >
                                            {u === 'pct' ? '% eq' : '$ fijo'}
                                        </button>
                                    ))}
                                </span>
                            </span>
                        </div>
                        <div
                            style={{
                                display: 'flex',
                                flexDirection: 'column',
                                gap: 4,
                                maxHeight: 280,
                                overflowY: 'auto',
                                border: '0.5px solid var(--color-ec-border)',
                                padding: 4,
                            }}
                        >
                            {activeStrategies.length === 0 && (
                                <div style={{ padding: 12, fontSize: 10, color: 'var(--color-ec-text-muted)' }}>
                                    No strategies available.
                                </div>
                            )}
                            {activeStrategies.map((s) => {
                                const checked = selectedIds.includes(s.id)
                                const color = STRAT_COLORS[selectedIds.indexOf(s.id) % STRAT_COLORS.length]
                                return (
                                    <div
                                        key={s.id}
                                        onClick={() => toggleStrategy(s.id)}
                                        style={{
                                            display: 'flex',
                                            alignItems: 'center',
                                            gap: 8,
                                            padding: '5px 6px',
                                            cursor: 'pointer',
                                            backgroundColor: checked ? 'rgba(216,122,61,0.08)' : 'transparent',
                                            borderLeft: checked ? `2px solid ${color}` : '2px solid transparent',
                                        }}
                                    >
                                        <input type="checkbox" checked={checked} readOnly style={{ accentColor: 'var(--color-ec-copper)' }} />
                                        <span
                                            style={{
                                                fontSize: 10,
                                                fontWeight: 600,
                                                color: 'var(--color-ec-text-secondary)',
                                                flex: 1,
                                                overflow: 'hidden',
                                                textOverflow: 'ellipsis',
                                                whiteSpace: 'nowrap',
                                            }}
                                            title={s.name}
                                        >
                                            {s.name}
                                        </span>
                                        {checked && (
                                            <span style={{ display: 'flex', alignItems: 'center', gap: 4 }} onClick={(e) => e.stopPropagation()}>
                                                {weightUnit === 'pct' && (
                                                    <input
                                                        type="range"
                                                        min={0}
                                                        max={50}
                                                        step={0.5}
                                                        value={weights[s.id] ?? 5}
                                                        onChange={(e) => handleWeightChange(s.id, parseFloat(e.target.value))}
                                                        style={{ width: 64, accentColor: 'var(--color-ec-copper)' }}
                                                    />
                                                )}
                                                <input
                                                    type="number"
                                                    min={0}
                                                    step={weightUnit === 'pct' ? 0.5 : 500}
                                                    value={weights[s.id] ?? (weightUnit === 'pct' ? 5 : Math.round(initCash / Math.max(1, selectedIds.length)))}
                                                    onChange={(e) => handleWeightChange(s.id, parseFloat(e.target.value) || 0)}
                                                    style={{ ...inputStyle, width: weightUnit === 'pct' ? 48 : 76, padding: '3px 4px', fontSize: 10 }}
                                                />
                                                <span style={{ fontSize: 9, color: 'var(--color-ec-text-muted)' }}>{weightUnit === 'pct' ? '%' : '$'}</span>
                                            </span>
                                        )}
                                    </div>
                                )
                            })}
                        </div>
                    </div>

                    {/* Info: saved-results model (2026-08-14) */}
                    <div style={{ padding: '8px 10px', border: '0.5px solid var(--color-ec-border)', backgroundColor: 'var(--color-ec-bg-surface)' }}>
                        <div style={{ fontSize: 8, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.8px', color: 'var(--color-ec-text-muted)', marginBottom: 4, display: 'flex', alignItems: 'center' }}>
                            Backtests guardados
                            <InfoDot text="El portfolio NO re-corrE estrategias: suma las curvas de PnL diarias del último backtest GUARDADO de cada estrategia (su dataset, periodo y costes ya están dentro). El DD se calcula sobre la curva total sumada." />
                        </div>
                        <p style={{ fontSize: 9, color: 'var(--color-ec-text-secondary)', margin: 0, lineHeight: 1.4 }}>
                            Cada estrategia aporta su último backtest guardado en el Baúl. El portfolio es la suma de curvas — nada se vuelve a correr, es instantáneo.
                        </p>
                    </div>

                    <div style={{ display: 'flex', gap: 8 }}>
                        <div style={{ flex: 1 }}>
                            <div style={{ ...sectionLabel, display: 'flex', alignItems: 'center' }}>
                                Initial cash ($)
                            </div>
                            <input type="number" value={initCash} min={100} step={1000} onChange={(e) => setInitCash(parseFloat(e.target.value) || 10000)} style={inputStyle} />
                        </div>
                        <div style={{ flex: 1 }}>
                            <div style={{ ...sectionLabel, display: 'flex', alignItems: 'center' }}>
                                Max exposure (%)
                                <InfoDot text="Tope de exposición DENTRO de cada estrategia (% de equity). Nunca entre estrategias: ninguna puede desplazar a otra." />
                            </div>
                            <input type="number" value={maxExposure} min={1} max={400} step={10} onChange={(e) => setMaxExposure(parseFloat(e.target.value) || 100)} style={inputStyle} />
                        </div>
                    </div>

                    {/* Sizing mode (restored 2026-08-14): how the weight base evolves */}
                    <div>
                        <div style={{ ...sectionLabel, display: 'flex', alignItems: 'center' }}>
                            Sizing
                            <InfoDot text="Lineal (ver R): cada trade se dimensiona sobre el capital INICIAL — sin componer, visión limpia en R. Compounding diario rebalanceado: cada estrategia re-dimensiona sobre su equity al inicio de cada día (la base rueda una vez al día, nunca intradía)." />
                        </div>
                        <div style={{ display: 'flex', gap: 6 }}>
                            {([['fixed', 'Lineal — ver R'], ['daily_compound', 'Compounding diario']] as const).map(([mode, label]) => (
                                <button
                                    key={mode}
                                    onClick={() => setSizingMode(mode)}
                                    style={{
                                        flex: 1,
                                        padding: '6px 8px',
                                        fontSize: 10,
                                        fontWeight: 700,
                                        cursor: 'pointer',
                                        border: sizingMode === mode ? '1px solid var(--color-ec-copper)' : '0.5px solid var(--color-ec-border)',
                                        color: sizingMode === mode ? 'var(--color-ec-copper)' : 'var(--color-ec-text-muted)',
                                        backgroundColor: sizingMode === mode ? 'rgba(216,122,61,0.08)' : 'transparent',
                                    }}
                                >
                                    {label}
                                </button>
                            ))}
                        </div>
                    </div>

                    {error && (
                        <div style={{ display: 'flex', gap: 6, alignItems: 'flex-start', padding: '8px 10px', border: '0.5px solid var(--color-ec-loss)', backgroundColor: 'rgba(201,77,63,0.08)' }}>
                            <AlertCircle size={13} color="var(--color-ec-loss)" style={{ flexShrink: 0, marginTop: 1 }} />
                            <span style={{ fontSize: 10, color: 'var(--color-ec-loss)' }}>{error}</span>
                        </div>
                    )}

                    <button
                        onClick={handleBuild}
                        disabled={!canBuild}
                        style={{
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            gap: 7,
                            padding: '9px 14px',
                            border: 'none',
                            borderRadius: 0,
                            cursor: canBuild ? 'pointer' : 'not-allowed',
                            fontSize: 11,
                            fontWeight: 700,
                            textTransform: 'uppercase',
                            letterSpacing: '1px',
                            color: 'var(--color-ec-bg-base)',
                            backgroundColor: canBuild ? 'var(--color-ec-copper)' : 'var(--color-ec-border)',
                            transition: 'opacity 150ms ease',
                        }}
                    >
                        {running ? <Activity size={13} className="animate-spin" /> : <Play size={13} />}
                        {running ? `Construyendo… ${progress.toFixed(0)}%` : 'Construir portfolio'}
                    </button>

                    {running && (
                        <div style={{ height: 3, background: 'var(--color-ec-border)', overflow: 'hidden' }}>
                            <div
                                style={{
                                    height: '100%',
                                    width: `${progress}%`,
                                    background: 'var(--color-ec-copper)',
                                    transition: 'width 200ms ease',
                                }}
                            />
                        </div>
                    )}
                </div>

                {/* ─── RIGHT: results (full width, single page scroll) ─── */}
                <div
                    ref={resultsRef}
                    style={{
                        flex: 1,
                        overflowY: 'auto',
                        padding: '18px 24px 28px 24px',
                        display: 'flex',
                        flexDirection: 'column',
                        gap: 18,
                        backgroundColor: 'rgba(16,18,19,0.4)',
                    }}
                >
                    {!result ? (
                        <div
                            style={{
                                flex: 1,
                                display: 'flex',
                                flexDirection: 'column',
                                alignItems: 'center',
                                justifyContent: 'center',
                                color: 'var(--color-ec-text-muted)',
                                textAlign: 'center',
                                padding: 20,
                            }}
                        >
                            <Layers size={28} style={{ opacity: 0.3, marginBottom: 10 }} />
                            <h4 style={{ fontSize: 12, color: 'var(--color-ec-text-high)', margin: 0 }}>No portfolio yet</h4>
                            <p style={{ fontSize: 10, margin: '6px 0 0 0' }}>
                                Select 2+ strategies, set their % equity, and hit “Construir portfolio”.
                            </p>
                        </div>
                    ) : (
                        <>
                            {/* R4: partial-TP aggregation — rows vs positions transparency */}
                            {result.input_rows_per_strategy && result.positions_per_strategy && (() => {
                                const _rows = Object.values(result.input_rows_per_strategy).reduce((a, b) => a + (b || 0), 0);
                                const _pos = Object.values(result.positions_per_strategy).reduce((a, b) => a + (b || 0), 0);
                                return (_rows > 0 && _rows > _pos) ? (
                                    <div style={{ display: 'flex', gap: 6, alignItems: 'flex-start', padding: '8px 10px', border: '0.5px solid var(--color-ec-border)', backgroundColor: 'rgba(255,255,255,0.02)' }}>
                                        <span style={{ fontSize: 10, color: 'var(--color-ec-text-secondary)' }}>
                                            Parciales agrupados por entrada: <strong>{_rows.toLocaleString()}</strong> filas → <strong>{_pos.toLocaleString()}</strong> posiciones (cada entrada se dimensiona una sola vez).
                                        </span>
                                    </div>
                                ) : null;
                            })()}
                            {/* R3 T6: exposure-cap skips + sanity warnings */}
                            {result.skipped_by_cap !== undefined && result.skipped_by_cap > 0 && (
                                <div style={{ display: 'flex', gap: 6, alignItems: 'flex-start', padding: '8px 10px', border: '0.5px solid var(--color-ec-copper)', backgroundColor: 'rgba(216,122,61,0.08)' }}>
                                    <AlertCircle size={13} color="var(--color-ec-copper)" style={{ flexShrink: 0, marginTop: 1 }} />
                                    <span style={{ fontSize: 10, color: 'var(--color-ec-text-secondary)' }}>
                                        <strong>{result.skipped_by_cap}</strong> trade(s) descartados por el tope de exposición de su propia estrategia (el tope se aplica dentro de cada estrategia, nunca entre estrategias)
                                        {' '}({((result.skipped_by_cap / Math.max(1, result.trades_entrada_totales ?? result.skipped_by_cap)) * 100).toFixed(1)}% del total). Considera subir el tope si son legítimos.
                                    </span>
                                </div>
                            )}
                            {result.sanity_warnings && result.sanity_warnings.length > 0 && (
                                <div style={{ display: 'flex', gap: 6, alignItems: 'flex-start', padding: '8px 10px', border: '0.5px solid var(--color-ec-loss)', backgroundColor: 'rgba(201,77,63,0.08)' }}>
                                    <AlertCircle size={13} color="var(--color-ec-loss)" style={{ flexShrink: 0, marginTop: 1 }} />
                                    <div style={{ fontSize: 10, color: 'var(--color-ec-loss)' }}>
                                        {result.sanity_warnings.map((w, i) => (<div key={i}>{w}</div>))}
                                    </div>
                                </div>
                            )}
                            {/* Saved runs used (source of each curve) */}
                            {result.saved_runs && Object.keys(result.saved_runs).length > 0 && (
                                <div style={{ display: 'flex', gap: 6, alignItems: 'flex-start', padding: '8px 10px', border: '0.5px solid var(--color-ec-border)', backgroundColor: 'rgba(255,255,255,0.02)' }}>
                                    <Database size={13} color="var(--color-ec-text-muted)" style={{ flexShrink: 0, marginTop: 1 }} />
                                    <span style={{ fontSize: 10, color: 'var(--color-ec-text-secondary)', lineHeight: 1.6 }}>
                                        Curvas sumadas desde backtests guardados:
                                        {result.strategy_order.map((sid) => {
                                            const m = result.saved_runs?.[sid]
                                            if (!m) return null
                                            return (
                                                <span key={sid}>
                                                    {' '}<strong>{labelFor(sid)}</strong>{' '}
                                                    ({m.date_from || '?'} → {m.date_to || '?'} · {m.n_trades?.toLocaleString()} trades · guardado {String(m.executed_at || '').slice(0, 16)})
                                                </span>
                                            )
                                        })}
                                    </span>
                                </div>
                            )}
                            {/* Combined equity */}
                            <section>
                                <SectionTitle tip="Equity = initial cash + cumulative realized PnL$. Each trade is sized as % equity × current account, so the curve compounds. Hover for date / equity / drawdown.">
                                    Combined equity — {fmtMoney(agg?.final_equity ?? initCash)} from {fmtMoney(initCash)}{' '}
                                    <span style={{ color: (agg?.total_return_pct ?? 0) >= 0 ? 'var(--color-ec-profit)' : 'var(--color-ec-loss)' }}>
                                        ({fmtPct(agg?.total_return_pct ?? 0)})
                                    </span>
                                </SectionTitle>
                                <div style={cardStyle}>
                                    <EquityChart curve={result.equity_curve} color="var(--color-ec-copper)" />
                                </div>
                            </section>

                            {/* Metrics card */}
                            <section>
                                <SectionTitle>Aggregate metrics</SectionTitle>
                                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 8 }}>
                                    {[
                                        { l: 'Total Return', k: 'total_return_pct', v: fmtPct(agg?.total_return_pct ?? 0), c: (agg?.total_return_pct ?? 0) >= 0 ? 'var(--color-ec-profit)' : 'var(--color-ec-loss)' },
                                        { l: 'Max Drawdown', k: 'max_drawdown_pct', v: fmtPct(agg?.max_drawdown_pct ?? 0), c: 'var(--color-ec-loss)' },
                                        { l: 'Sharpe', k: 'sharpe', v: fmtNum(agg?.sharpe ?? 0), c: 'var(--color-ec-text-high)' },
                                        { l: 'Calmar', k: 'calmar', v: fmtNum(agg?.calmar ?? null), c: 'var(--color-ec-text-high)' },
                                        { l: 'Profit Factor', k: 'profit_factor', v: fmtNum(agg?.profit_factor ?? 0), c: 'var(--color-ec-text-high)' },
                                        { l: 'Win Rate', k: 'win_rate', v: fmtPct(agg?.win_rate ?? 0, 1), c: 'var(--color-ec-text-high)' },
                                        { l: 'Trades', k: 'total_trades', v: String(agg?.total_trades ?? 0), c: 'var(--color-ec-text-high)' },
                                        { l: 'Final Equity', k: 'final_equity', v: fmtMoney(agg?.final_equity ?? initCash), c: 'var(--color-ec-text-high)' },
                                    ].map((m) => (
                                        <div key={m.l} style={cardStyle}>
                                            <div style={{ fontSize: 8, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.5px', color: 'var(--color-ec-text-muted)', display: 'flex', alignItems: 'center' }}>
                                                {m.l}
                                                {METRIC_INFO[m.k] && <InfoDot text={METRIC_INFO[m.k]} />}
                                                {m.k === 'sharpe' && agg?.sharpe_note && (
                                                    <span style={{ marginLeft: 4, color: 'var(--color-ec-copper)' }} title="Few trades: this ratio is unreliable">⚠</span>
                                                )}
                                            </div>
                                            <div style={{ fontSize: 18, fontWeight: 700, color: m.c, fontFamily: 'monospace', marginTop: 4 }}>{m.v}</div>
                                        </div>
                                    ))}
                                </div>
                            </section>

                            {/* Correlation matrix */}
                            <section>
                                <SectionTitle tip="Pearson correlation of DAILY PnL$. Two strategies on the same gap universe can correlate even when they trade at different hours — this does NOT measure intraday overlap.">
                                    Correlation matrix (daily PnL$)
                                </SectionTitle>
                                <div style={cardStyle}>
                                    <CorrelationMatrix matrix={result.correlation} labels={result.strategy_order.map(labelFor)} />
                                </div>
                            </section>

                            {/* Combined vs standalone */}
                            <section>
                                <SectionTitle tip="Each strategy's standalone is simulated at the SAME % equity as in the portfolio, so the only difference vs Combined is diversification. 'Sum standalone' adds the per-strategy columns.">
                                    Combined vs each strategy standalone{' '}
                                    {diversified && (
                                        <span style={{ marginLeft: 6, padding: '2px 6px', fontSize: 8, color: 'var(--color-ec-profit)', border: '0.5px solid var(--color-ec-profit)', textTransform: 'none', letterSpacing: 0 }}>
                                            ✓ diversification: combined DD {fmtPct(combinedDD)} {'>'} sum {fmtPct(sumDD)}
                                        </span>
                                    )}
                                </SectionTitle>
                                <div style={cardStyle}>
                                    <div style={{ overflowX: 'auto' }}>
                                        <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'right', minWidth: 520 }}>
                                            <thead>
                                                <tr style={{ borderBottom: '1px solid var(--color-ec-border)' }}>
                                                    <th style={{ padding: '8px 10px', fontSize: 9, fontWeight: 700, textTransform: 'uppercase', color: 'var(--color-ec-text-muted)', textAlign: 'left' }}>Metric</th>
                                                    <th style={{ padding: '8px 12px', fontSize: 11, fontWeight: 700, color: 'var(--color-ec-copper)', textAlign: 'right' }}>Combined</th>
                                                    {result.strategy_order.map((sid, j) => (
                                                        <th key={sid} style={{ padding: '8px 12px', fontSize: 11, fontWeight: 700, color: STRAT_COLORS[j % STRAT_COLORS.length], textAlign: 'right' }} title={labelFor(sid)}>
                                                            {labelFor(sid)}
                                                        </th>
                                                    ))}
                                                    <th style={{ padding: '8px 12px', fontSize: 9, fontWeight: 700, color: 'var(--color-ec-text-muted)', textAlign: 'right' }}>Sum standalone</th>
                                                </tr>
                                            </thead>
                                            <tbody>
                                                {cmpRows.map((row) => {
                                                    const cv = (agg?.[row.key] as number | null | undefined) ?? null
                                                    const standalones = result.strategy_order.map(
                                                        (sid) => (result.standalone?.[sid]?.aggregate_metrics?.[row.key] as number | null | undefined) ?? null,
                                                    )
                                                    const sumVal = standalones.reduce<number>((s, v) => s + (v ?? 0), 0)
                                                    const isDDRow = row.key === 'max_drawdown_pct'
                                                    return (
                                                        <tr key={row.label} style={{ borderBottom: '0.5px solid rgba(255,255,255,0.04)' }}>
                                                            <td style={{ padding: '8px 10px', fontSize: 10, fontWeight: 700, color: 'var(--color-ec-text-muted)', textTransform: 'uppercase', textAlign: 'left' }}>
                                                                {row.label}
                                                            </td>
                                                            <td
                                                                style={{
                                                                    padding: '8px 12px',
                                                                    fontSize: 13,
                                                                    fontWeight: 700,
                                                                    color: row.col(cv),
                                                                    fontFamily: 'monospace',
                                                                    backgroundColor: isDDRow && diversified ? 'rgba(74,157,127,0.10)' : 'transparent',
                                                                }}
                                                            >
                                                                {row.fmt(cv)}
                                                            </td>
                                                            {result.strategy_order.map((sid) => {
                                                                const sv = (result.standalone?.[sid]?.aggregate_metrics?.[row.key] as number | null | undefined) ?? null
                                                                return (
                                                                    <td key={sid} style={{ padding: '8px 12px', fontSize: 12, fontWeight: 600, color: 'var(--color-ec-text-secondary)', fontFamily: 'monospace' }}>
                                                                        {row.fmt(sv)}
                                                                    </td>
                                                                )
                                                            })}
                                                            <td style={{ padding: '8px 12px', fontSize: 11, fontWeight: 700, color: 'var(--color-ec-text-muted)', fontFamily: 'monospace' }}>
                                                                {row.showSum ? row.fmt(sumVal) : '—'}
                                                            </td>
                                                        </tr>
                                                    )
                                                })}
                                            </tbody>
                                        </table>
                                    </div>
                                </div>
                            </section>

                            {/* Per-strategy contribution */}
                            <section>
                                <SectionTitle tip="How much each strategy contributed to the combined return ($ and %), its position size, and its standalone max drawdown. The % contributions add up to the combined total return.">
                                    Per-strategy contribution
                                </SectionTitle>
                                <div style={cardStyle}>
                                    <div style={{ overflowX: 'auto' }}>
                                        <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'right', minWidth: 560 }}>
                                            <thead>
                                                <tr style={{ borderBottom: '1px solid var(--color-ec-border)' }}>
                                                    <th style={{ padding: '8px 10px', fontSize: 9, fontWeight: 700, textTransform: 'uppercase', color: 'var(--color-ec-text-muted)', textAlign: 'left' }}>Strategy</th>
                                                    <th style={{ padding: '8px 10px', fontSize: 9, fontWeight: 700, textTransform: 'uppercase', color: 'var(--color-ec-text-muted)', textAlign: 'right' }}>
                                                        % Equity
                                                    </th>
                                                    <th style={{ padding: '8px 10px', fontSize: 9, fontWeight: 700, textTransform: 'uppercase', color: 'var(--color-ec-text-muted)', textAlign: 'right' }}>Trades</th>
                                                    <th style={{ padding: '8px 10px', fontSize: 9, fontWeight: 700, textTransform: 'uppercase', color: 'var(--color-ec-text-muted)', textAlign: 'right' }}>Return contr. %</th>
                                                    <th style={{ padding: '8px 10px', fontSize: 9, fontWeight: 700, textTransform: 'uppercase', color: 'var(--color-ec-text-muted)', textAlign: 'right' }}>Return $</th>
                                                    <th style={{ padding: '8px 10px', fontSize: 9, fontWeight: 700, textTransform: 'uppercase', color: 'var(--color-ec-text-muted)', textAlign: 'right' }}>Max DD %</th>
                                                    <th style={{ padding: '8px 10px', fontSize: 9, fontWeight: 700, textTransform: 'uppercase', color: 'var(--color-ec-text-muted)', textAlign: 'right' }}>Win %</th>
                                                </tr>
                                            </thead>
                                            <tbody>
                                                {result.strategy_order.map((sid, j) => {
                                                    const ps = result.per_strategy?.[sid]
                                                    const contrib = ps?.return_contribution_pct ?? 0
                                                    const maxContrib = Math.max(
                                                        0.0001,
                                                        ...result.strategy_order.map((s) => Math.abs(result.per_strategy?.[s]?.return_contribution_pct ?? 0)),
                                                    )
                                                    return (
                                                        <tr key={sid} style={{ borderBottom: '0.5px solid rgba(255,255,255,0.04)' }}>
                                                            <td style={{ padding: '8px 10px', fontSize: 11, fontWeight: 700, color: STRAT_COLORS[j % STRAT_COLORS.length], textAlign: 'left' }}>{labelFor(sid)}</td>
                                                            <td style={{ padding: '8px 10px', fontSize: 11, fontFamily: 'monospace', color: 'var(--color-ec-text-secondary)' }}>{((ps?.pct_equity ?? 0) * 100).toFixed(1)}%</td>
                                                            <td style={{ padding: '8px 10px', fontSize: 11, fontFamily: 'monospace', color: 'var(--color-ec-text-secondary)' }}>{ps?.trades ?? 0}</td>
                                                            <td style={{ padding: '8px 10px', fontFamily: 'monospace' }}>
                                                                <div style={{ display: 'flex', alignItems: 'center', gap: 8, justifyContent: 'flex-end' }}>
                                                                    <div style={{ width: 70, height: 6, background: 'rgba(255,255,255,0.06)' }}>
                                                                        <div style={{ width: `${Math.min(100, (Math.abs(contrib) / maxContrib) * 100)}%`, height: '100%', background: contrib >= 0 ? 'var(--color-ec-profit)' : 'var(--color-ec-loss)' }} />
                                                                    </div>
                                                                    <span style={{ fontSize: 11, color: contrib >= 0 ? 'var(--color-ec-profit)' : 'var(--color-ec-loss)', minWidth: 52, textAlign: 'right' }}>{fmtPct(contrib)}</span>
                                                                </div>
                                                            </td>
                                                            <td style={{ padding: '8px 10px', fontSize: 11, fontFamily: 'monospace', color: 'var(--color-ec-text-secondary)' }}>{fmtMoney(ps?.return_contribution_dollars ?? 0)}</td>
                                                            <td style={{ padding: '8px 10px', fontSize: 11, fontFamily: 'monospace', color: 'var(--color-ec-loss)' }}>{fmtPct(ps?.max_drawdown_pct ?? 0)}</td>
                                                            <td style={{ padding: '8px 10px', fontSize: 11, fontFamily: 'monospace', color: 'var(--color-ec-text-secondary)' }}>{fmtNum(ps?.win_rate ?? 0, 1)}%</td>
                                                        </tr>
                                                    )
                                                })}
                                            </tbody>
                                        </table>
                                    </div>
                                </div>
                            </section>

                            {/* Save */}
                            <section style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 2 }}>
                                <button
                                    onClick={handleSave}
                                    disabled={saving}
                                    style={{
                                        display: 'flex',
                                        alignItems: 'center',
                                        gap: 7,
                                        padding: '8px 14px',
                                        border: '0.5px solid var(--color-ec-copper)',
                                        borderRadius: 0,
                                        cursor: saving ? 'wait' : 'pointer',
                                        fontSize: 10,
                                        fontWeight: 700,
                                        textTransform: 'uppercase',
                                        letterSpacing: '1px',
                                        color: 'var(--color-ec-copper)',
                                        backgroundColor: 'transparent',
                                    }}
                                >
                                    {saving ? <Activity size={12} className="animate-spin" /> : <Save size={12} />}
                                    {saving ? 'Guardando…' : 'Guardar en el Baúl'}
                                </button>
                                {savedMsg && (
                                    <span style={{ fontSize: 10, color: savedMsg.includes('failed') ? 'var(--color-ec-loss)' : 'var(--color-ec-profit)', display: 'flex', alignItems: 'center', gap: 4 }}>
                                        {!savedMsg.includes('failed') && <Check size={12} />}
                                        {savedMsg}
                                    </span>
                                )}
                            </section>
                        </>
                    )}
                </div>
            </div>
        </div>
    )
}
