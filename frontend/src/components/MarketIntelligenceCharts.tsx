"use client";

import React, { useEffect, useState } from "react";
import { getScreener } from "@/lib/api";
import {
  ResponsiveContainer,
  ScatterChart,
  Scatter,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  BarChart,
  Bar,
  Cell,
  PieChart,
  Pie,
  Legend,
  AreaChart,
  Area
} from "recharts";
import { Activity, TrendingDown, Percent, BarChart3, Database } from "lucide-react";

interface ScreenerRecord {
  ticker: string;
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  gap_at_open_pct: number;
  rth_run_pct: number;
  day_return_pct: number;
  pmh_gap_pct: number;
  pmh_fade_pct: number;
  rth_fade_pct: number;
}

export const MarketIntelligenceCharts: React.FC = () => {
  const [data, setData] = useState<ScreenerRecord[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const loadMarketData = async () => {
      try {
        // Fetch up to 1000 records of gap data to analyze
        const res = await getScreener("limit=1000&min_gap_at_open_pct=5") as any;
        const records = Array.isArray(res) ? res : res.records || [];
        setData(records);
      } catch (err) {
        console.error("Error loading market intelligence data:", err);
      } finally {
        setLoading(false);
      }
    };
    loadMarketData();
  }, []);

  if (loading) {
    return (
      <div style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        height: "100%",
        minHeight: "400px",
        color: "var(--color-ec-text-muted)"
      }}>
        <div style={{
          width: 32,
          height: 32,
          border: "3px solid var(--color-ec-border)",
          borderTop: "3px solid var(--color-ec-copper)",
          borderRadius: "50%",
          animation: "spin 1s linear infinite",
          marginBottom: 16
        }} />
        <span style={{
          fontFamily: "'General Sans', sans-serif",
          fontSize: 10,
          fontWeight: 700,
          textTransform: "uppercase",
          letterSpacing: 2
        }}>
          Analyzing Market Datasets...
        </span>
        <style dangerouslySetInnerHTML={{ __html: `
          @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
          }
        `}} />
      </div>
    );
  }

  // --- Process Data for Charts ---

  // 1. Scatter Plot Data: Gap % vs Day Return %
  const scatterData = data.map(r => ({
    x: Number(r.gap_at_open_pct.toFixed(2)),
    y: Number(r.day_return_pct.toFixed(2)),
    ticker: r.ticker,
    date: r.date
  }));

  // 2. Bar Chart Data: Distribution of Gap Sizes
  const gapRanges = [
    { label: "5-10%", min: 5, max: 10, count: 0 },
    { label: "10-15%", min: 10, max: 15, count: 0 },
    { label: "15-20%", min: 15, max: 20, count: 0 },
    { label: "20-30%", min: 20, max: 30, count: 0 },
    { label: "30%+", min: 30, max: Infinity, count: 0 }
  ];

  data.forEach(r => {
    const gap = r.gap_at_open_pct;
    for (const range of gapRanges) {
      if (gap >= range.min && gap < range.max) {
        range.count++;
        break;
      }
    }
  });

  // 3. Pie Chart Data: Success of Fade (Closed Red vs Green)
  let closedRedCount = 0;
  let closedGreenCount = 0;
  data.forEach(r => {
    if (r.day_return_pct < 0) {
      closedRedCount++;
    } else {
      closedGreenCount++;
    }
  });

  const totalClosed = closedRedCount + closedGreenCount;
  const pieData = [
    { name: "Closed Red (Faded)", value: closedRedCount, percentage: totalClosed ? ((closedRedCount / totalClosed) * 100).toFixed(1) : 0 },
    { name: "Closed Green", value: closedGreenCount, percentage: totalClosed ? ((closedGreenCount / totalClosed) * 100).toFixed(1) : 0 }
  ];

  // 4. Area Chart Data: Average Intraday Fade Profile (simulated from metrics)
  // Let's bucket the metrics into return cohorts
  const returnCohorts = [
    { name: "Gap Open", value: 0 },
    { name: "PMH Gap", value: data.reduce((acc, r) => acc + r.pmh_gap_pct, 0) / (data.length || 1) },
    { name: "PM Fade", value: -data.reduce((acc, r) => acc + r.pmh_fade_pct, 0) / (data.length || 1) },
    { name: "Day Return", value: data.reduce((acc, r) => acc + r.day_return_pct, 0) / (data.length || 1) }
  ];

  return (
    <div style={{
      width: "100%",
      display: "flex",
      flexDirection: "column",
      gap: "24px",
      padding: "16px 0",
      boxSizing: "border-box"
    }}>
      {/* Metrics Row */}
      <div style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
        gap: "16px"
      }}>
        <div style={statCardStyle}>
          <div style={statHeaderStyle}>
            <span style={statTitleStyle}>FADE SUCCESS RATE</span>
            <TrendingDown size={14} color="var(--color-ec-copper)" />
          </div>
          <span style={statValueStyle}>
            {totalClosed ? ((closedRedCount / totalClosed) * 100).toFixed(1) : "0.0"}%
          </span>
          <span style={statDescStyle}>Of gap ups closed red (negative return)</span>
        </div>

        <div style={statCardStyle}>
          <div style={statHeaderStyle}>
            <span style={statTitleStyle}>AVG OPENING GAP</span>
            <Percent size={14} color="var(--color-ec-copper)" />
          </div>
          <span style={statValueStyle}>
            {(data.reduce((acc, r) => acc + r.gap_at_open_pct, 0) / (data.length || 1)).toFixed(2)}%
          </span>
          <span style={statDescStyle}>Average gap size across sample</span>
        </div>

        <div style={statCardStyle}>
          <div style={statHeaderStyle}>
            <span style={statTitleStyle}>AVG DAY RETURN</span>
            <Activity size={14} color="var(--color-ec-copper)" />
          </div>
          <span style={{ ...statValueStyle, color: "var(--color-ec-loss)" }}>
            {(data.reduce((acc, r) => acc + r.day_return_pct, 0) / (data.length || 1)).toFixed(2)}%
          </span>
          <span style={statDescStyle}>Average day return from open to close</span>
        </div>

        <div style={statCardStyle}>
          <div style={statHeaderStyle}>
            <span style={statTitleStyle}>SAMPLE SIZE</span>
            <Database size={14} color="var(--color-ec-copper)" />
          </div>
          <span style={statValueStyle}>{data.length}</span>
          <span style={statDescStyle}>Active records analyzed</span>
        </div>
      </div>

      {/* Grid for Charts */}
      <div style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fit, minmax(400px, 1fr))",
        gap: "20px"
      }}>
        {/* Chart 1: Scatter Plot */}
        <div style={chartContainerStyle}>
          <div style={chartHeaderStyle}>
            <h3 style={chartTitleStyle}>Gap % vs. Day Return %</h3>
            <span style={chartSubtitleStyle}>Real-time correlation of gap size and EOD fade</span>
          </div>
          <div style={{ height: "300px", width: "100%" }}>
            <ResponsiveContainer width="100%" height="100%">
              <ScatterChart margin={{ top: 10, right: 10, bottom: 10, left: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--color-ec-border)" vertical={false} />
                <XAxis
                  type="number"
                  dataKey="x"
                  name="Gap"
                  unit="%"
                  stroke="var(--color-ec-text-muted)"
                  fontSize={9}
                  tickLine={false}
                  axisLine={false}
                />
                <YAxis
                  type="number"
                  dataKey="y"
                  name="Return"
                  unit="%"
                  stroke="var(--color-ec-text-muted)"
                  fontSize={9}
                  tickLine={false}
                  axisLine={false}
                />
                <Tooltip
                  cursor={{ strokeDasharray: "3 3", stroke: "var(--color-ec-copper)" }}
                  content={({ active, payload }) => {
                    if (active && payload && payload.length) {
                      const dataPoint = payload[0].payload;
                      return (
                        <div style={tooltipStyle}>
                          <div style={{ fontWeight: 600, color: "var(--color-ec-text-high)", marginBottom: 4 }}>
                            {dataPoint.ticker} ({dataPoint.date})
                          </div>
                          <div>Gap: <span style={{ color: "var(--color-ec-text-primary)" }}>{dataPoint.x}%</span></div>
                          <div>Return: <span style={{ color: dataPoint.y < 0 ? "var(--color-ec-loss)" : "var(--color-ec-profit)" }}>{dataPoint.y}%</span></div>
                        </div>
                      );
                    }
                    return null;
                  }}
                />
                <Scatter name="Tickers" data={scatterData} fill="var(--color-ec-copper-bright)" fillOpacity={0.6} />
              </ScatterChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Chart 2: Distribution of Gaps */}
        <div style={chartContainerStyle}>
          <div style={chartHeaderStyle}>
            <h3 style={chartTitleStyle}>Distribution of Gap Sizes</h3>
            <span style={chartSubtitleStyle}>Frequency count of tickers by gap percentage</span>
          </div>
          <div style={{ height: "300px", width: "100%" }}>
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={gapRanges} margin={{ top: 10, right: 10, bottom: 10, left: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--color-ec-border)" vertical={false} />
                <XAxis
                  dataKey="label"
                  stroke="var(--color-ec-text-muted)"
                  fontSize={9}
                  tickLine={false}
                  axisLine={false}
                />
                <YAxis
                  stroke="var(--color-ec-text-muted)"
                  fontSize={9}
                  tickLine={false}
                  axisLine={false}
                />
                <Tooltip
                  contentStyle={tooltipStyle}
                  labelStyle={{ color: "var(--color-ec-text-muted)", fontWeight: 600 }}
                />
                <Bar dataKey="count" fill="var(--color-ec-copper)">
                  {gapRanges.map((entry, index) => (
                    <Cell
                      key={`cell-${index}`}
                      fill={index % 2 === 0 ? "var(--color-ec-copper)" : "var(--color-ec-copper-bright)"}
                    />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Chart 3: Pie Chart Outcome */}
        <div style={chartContainerStyle}>
          <div style={chartHeaderStyle}>
            <h3 style={chartTitleStyle}>Fade Success Outcomes</h3>
            <span style={chartSubtitleStyle}>Comparison of red close vs. green close events</span>
          </div>
          <div style={{ height: "300px", width: "100%", display: "flex", alignItems: "center", justifyContent: "center" }}>
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={pieData}
                  cx="50%"
                  cy="45%"
                  innerRadius={60}
                  outerRadius={80}
                  paddingAngle={5}
                  dataKey="value"
                >
                  <Cell fill="var(--color-ec-loss)" />
                  <Cell fill="var(--color-ec-profit)" />
                </Pie>
                <Tooltip
                  content={({ active, payload }) => {
                    if (active && payload && payload.length) {
                      const dataPoint = payload[0].payload;
                      return (
                        <div style={tooltipStyle}>
                          <div style={{ fontWeight: 600, color: "var(--color-ec-text-high)" }}>{dataPoint.name}</div>
                          <div>Count: <span style={{ color: "var(--color-ec-text-primary)" }}>{dataPoint.value}</span></div>
                          <div>Percentage: <span style={{ color: "var(--color-ec-text-primary)" }}>{dataPoint.percentage}%</span></div>
                        </div>
                      );
                    }
                    return null;
                  }}
                />
                <Legend
                  verticalAlign="bottom"
                  height={36}
                  iconType="circle"
                  formatter={(value, entry: any) => (
                    <span style={{
                      fontFamily: "'General Sans', sans-serif",
                      fontSize: 10,
                      fontWeight: 600,
                      color: "var(--color-ec-text-muted)",
                      textTransform: "uppercase"
                    }}>
                      {value} ({entry.payload.percentage}%)
                    </span>
                  )}
                />
              </PieChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Chart 4: Average Fade Progression */}
        <div style={chartContainerStyle}>
          <div style={chartHeaderStyle}>
            <h3 style={chartTitleStyle}>Average Fade Signature</h3>
            <span style={chartSubtitleStyle}>Mean return trajectory relative to Pre-Market High</span>
          </div>
          <div style={{ height: "300px", width: "100%" }}>
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={returnCohorts} margin={{ top: 10, right: 10, bottom: 10, left: 0 }}>
                <defs>
                  <linearGradient id="fadeGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="var(--color-ec-copper)" stopOpacity={0.3}/>
                    <stop offset="95%" stopColor="var(--color-ec-copper)" stopOpacity={0}/>
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--color-ec-border)" vertical={false} />
                <XAxis
                  dataKey="name"
                  stroke="var(--color-ec-text-muted)"
                  fontSize={9}
                  tickLine={false}
                  axisLine={false}
                />
                <YAxis
                  stroke="var(--color-ec-text-muted)"
                  fontSize={9}
                  tickLine={false}
                  axisLine={false}
                  tickFormatter={(v) => `${v.toFixed(1)}%`}
                />
                <Tooltip contentStyle={tooltipStyle} />
                <Area
                  type="monotone"
                  dataKey="value"
                  stroke="var(--color-ec-copper)"
                  strokeWidth={2}
                  fillOpacity={1}
                  fill="url(#fadeGrad)"
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>
    </div>
  );
};

// --- Styles ---

const statCardStyle: React.CSSProperties = {
  background: "var(--color-ec-bg-surface)",
  border: "0.5px solid var(--color-ec-border)",
  borderRadius: 8,
  padding: "16px 20px",
  display: "flex",
  flexDirection: "column",
  gap: 4,
  boxShadow: "0 2px 8px rgba(0, 0, 0, 0.1)"
};

const statHeaderStyle: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  width: "100%"
};

const statTitleStyle: React.CSSProperties = {
  fontFamily: "'General Sans', sans-serif",
  fontSize: 8,
  fontWeight: 700,
  textTransform: "uppercase",
  letterSpacing: "1.5px",
  color: "var(--color-ec-text-muted)"
};

const statValueStyle: React.CSSProperties = {
  fontFamily: "'General Sans', sans-serif",
  fontSize: 22,
  fontWeight: 600,
  color: "var(--color-ec-text-high)",
  letterSpacing: "-0.5px",
  margin: "4px 0"
};

const statDescStyle: React.CSSProperties = {
  fontFamily: "'General Sans', sans-serif",
  fontSize: 9,
  fontWeight: 500,
  color: "var(--color-ec-text-muted)"
};

const chartContainerStyle: React.CSSProperties = {
  background: "var(--color-ec-bg-surface)",
  border: "0.5px solid var(--color-ec-border)",
  borderRadius: 8,
  padding: "20px",
  display: "flex",
  flexDirection: "column",
  gap: 16,
  boxShadow: "0 2px 12px rgba(0, 0, 0, 0.15)"
};

const chartHeaderStyle: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 2
};

const chartTitleStyle: React.CSSProperties = {
  fontFamily: "'Fraunces', serif",
  fontSize: 16,
  fontWeight: 500,
  color: "var(--color-ec-text-high)",
  margin: 0
};

const chartSubtitleStyle: React.CSSProperties = {
  fontFamily: "'General Sans', sans-serif",
  fontSize: 9,
  fontWeight: 600,
  textTransform: "uppercase",
  letterSpacing: "0.5px",
  color: "var(--color-ec-text-muted)"
};

const tooltipStyle: React.CSSProperties = {
  backgroundColor: "var(--color-ec-bg-surface)",
  border: "1px solid var(--color-ec-border)",
  borderRadius: 6,
  padding: "8px 12px",
  fontFamily: "'General Sans', sans-serif",
  fontSize: 11,
  color: "var(--color-ec-text-primary)",
  boxShadow: "0 4px 12px rgba(0, 0, 0, 0.3)"
};
