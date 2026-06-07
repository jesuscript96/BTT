import type { CandleData } from "./api_backtester";
import { type Time } from "lightweight-charts";

// ---------------------------------------------------------------------------
// Shared types
// ---------------------------------------------------------------------------

export interface IndicatorDataPoint {
    time: Time;
    value: number;
}

export interface MACDDataPoint {
    time: Time;
    macd: number;
    signal: number;
    histogram: number;
}

export interface BandDataPoint {
    time: Time;
    upper: number;
    middle: number;
    lower: number;
}

export interface IchimokuDataPoint {
    time: Time;
    tenkan: number | null;
    kijun: number | null;
    senkouA: number | null;
    senkouB: number | null;
    chikou: number | null;
}

export interface StochasticDataPoint {
    time: Time;
    k: number;
    d: number;
}

export interface DMIDataPoint {
    time: Time;
    plusDI: number;
    minusDI: number;
    adx: number;
}

export interface HeikinAshiDataPoint {
    time: Time;
    open: number;
    high: number;
    low: number;
    close: number;
}

// ---------------------------------------------------------------------------
// Utility helpers
// ---------------------------------------------------------------------------

function sortAndDedup(data: CandleData[]): CandleData[] {
    const sorted = [...data].sort((a, b) => a.time - b.time);
    return sorted.filter((c, i) => i === 0 || c.time !== sorted[i - 1].time);
}

function smaArray(values: number[], period: number): (number | null)[] {
    const result: (number | null)[] = new Array(values.length).fill(null);
    if (values.length < period) return result;
    let sum = 0;
    for (let i = 0; i < period; i++) sum += values[i];
    result[period - 1] = sum / period;
    for (let i = period; i < values.length; i++) {
        sum += values[i] - values[i - period];
        result[i] = sum / period;
    }
    return result;
}

function emaArray(values: number[], period: number): (number | null)[] {
    const result: (number | null)[] = new Array(values.length).fill(null);
    if (values.length < period) return result;
    const k = 2 / (period + 1);
    let sum = 0;
    for (let i = 0; i < period; i++) sum += values[i];
    let ema = sum / period;
    result[period - 1] = ema;
    for (let i = period; i < values.length; i++) {
        ema = (values[i] - ema) * k + ema;
        result[i] = ema;
    }
    return result;
}

// ---------------------------------------------------------------------------
// 1. Simple Moving Average (SMA)
// ---------------------------------------------------------------------------
export function calculateSMA(data: CandleData[], period: number): IndicatorDataPoint[] {
    const result: IndicatorDataPoint[] = [];
    if (data.length < period || period <= 0) return result;
    const sorted = sortAndDedup(data);
    let sum = 0;
    for (let i = 0; i < sorted.length; i++) {
        sum += sorted[i].close;
        if (i >= period) sum -= sorted[i - period].close;
        if (i >= period - 1) {
            result.push({ time: sorted[i].time as Time, value: sum / period });
        }
    }
    return result;
}

// ---------------------------------------------------------------------------
// 2. Exponential Moving Average (EMA)
// ---------------------------------------------------------------------------
export function calculateEMA(data: CandleData[], period: number): IndicatorDataPoint[] {
    const result: IndicatorDataPoint[] = [];
    if (data.length < period || period <= 0) return result;
    const sorted = sortAndDedup(data);
    const k = 2 / (period + 1);
    let sum = 0;
    for (let i = 0; i < period; i++) sum += sorted[i].close;
    let ema = sum / period;
    result.push({ time: sorted[period - 1].time as Time, value: ema });
    for (let i = period; i < sorted.length; i++) {
        ema = (sorted[i].close - ema) * k + ema;
        result.push({ time: sorted[i].time as Time, value: ema });
    }
    return result;
}

// ---------------------------------------------------------------------------
// 3. Weighted Moving Average (WMA)
// ---------------------------------------------------------------------------
export function calculateWMA(data: CandleData[], period: number): IndicatorDataPoint[] {
    const result: IndicatorDataPoint[] = [];
    if (data.length < period || period <= 0) return result;
    const sorted = sortAndDedup(data);
    const denom = (period * (period + 1)) / 2;
    for (let i = period - 1; i < sorted.length; i++) {
        let wsum = 0;
        for (let j = 0; j < period; j++) {
            wsum += sorted[i - period + 1 + j].close * (j + 1);
        }
        result.push({ time: sorted[i].time as Time, value: wsum / denom });
    }
    return result;
}

// ---------------------------------------------------------------------------
// 4. VWAP (uses backend precomputed, fallback to frontend calc)
// ---------------------------------------------------------------------------
export function calculateVWAP(data: CandleData[]): IndicatorDataPoint[] {
    const result: IndicatorDataPoint[] = [];
    if (data.length === 0) return result;
    const sorted = sortAndDedup(data);

    // Try backend precomputed first
    const hasBackend = sorted.some(c => c.vwap != null);
    if (hasBackend) {
        for (const c of sorted) {
            if (c.vwap != null) result.push({ time: c.time as Time, value: c.vwap });
        }
        return result;
    }

    // Fallback: compute from OHLCV (single-day reset)
    let cumTPV = 0, cumVol = 0, currentDay = "";
    for (const c of sorted) {
        const dateStr = typeof c.time === "number"
            ? new Date(c.time * 1000).toISOString().split("T")[0]
            : String(c.time).split("T")[0];
        if (dateStr !== currentDay) { cumTPV = 0; cumVol = 0; currentDay = dateStr; }
        const tp = (c.high + c.low + c.close) / 3;
        cumTPV += tp * c.volume;
        cumVol += c.volume;
        if (cumVol > 0) result.push({ time: c.time as Time, value: cumTPV / cumVol });
    }
    return result;
}

// ---------------------------------------------------------------------------
// 5. Linear Regression
// ---------------------------------------------------------------------------
export function calculateLinearRegression(data: CandleData[], period: number): IndicatorDataPoint[] {
    const result: IndicatorDataPoint[] = [];
    if (data.length < period || period < 2) return result;
    const sorted = sortAndDedup(data);
    for (let i = period - 1; i < sorted.length; i++) {
        let sumX = 0, sumY = 0, sumXY = 0, sumX2 = 0;
        for (let j = 0; j < period; j++) {
            const x = j;
            const y = sorted[i - period + 1 + j].close;
            sumX += x; sumY += y; sumXY += x * y; sumX2 += x * x;
        }
        const slope = (period * sumXY - sumX * sumY) / (period * sumX2 - sumX * sumX);
        const intercept = (sumY - slope * sumX) / period;
        result.push({ time: sorted[i].time as Time, value: intercept + slope * (period - 1) });
    }
    return result;
}

// ---------------------------------------------------------------------------
// 6. Zig Zag
// ---------------------------------------------------------------------------
export function calculateZigZag(data: CandleData[], reversalPct: number): IndicatorDataPoint[] {
    if (data.length < 2) return [];
    const sorted = sortAndDedup(data);
    const threshold = reversalPct / 100;

    interface Pivot { idx: number; value: number; type: "high" | "low" }
    const pivots: Pivot[] = [];

    let lastPivot: Pivot = { idx: 0, value: sorted[0].close, type: "high" };
    let trend: "up" | "down" = "up";

    for (let i = 1; i < sorted.length; i++) {
        const high = sorted[i].high;
        const low = sorted[i].low;

        if (trend === "up") {
            if (high > lastPivot.value) {
                lastPivot = { idx: i, value: high, type: "high" };
            } else if (low <= lastPivot.value * (1 - threshold)) {
                pivots.push(lastPivot);
                lastPivot = { idx: i, value: low, type: "low" };
                trend = "down";
            }
        } else {
            if (low < lastPivot.value) {
                lastPivot = { idx: i, value: low, type: "low" };
            } else if (high >= lastPivot.value * (1 + threshold)) {
                pivots.push(lastPivot);
                lastPivot = { idx: i, value: high, type: "high" };
                trend = "up";
            }
        }
    }
    pivots.push(lastPivot);

    return pivots.map(p => ({
        time: sorted[p.idx].time as Time,
        value: p.value,
    }));
}

// ---------------------------------------------------------------------------
// 7. Ichimoku Clouds
// ---------------------------------------------------------------------------
export function calculateIchimoku(
    data: CandleData[],
    tenkanPeriod: number = 9,
    kijunPeriod: number = 26,
    senkouBPeriod: number = 52,
    displacement: number = 26
): IchimokuDataPoint[] {
    const sorted = sortAndDedup(data);
    const n = sorted.length;
    if (n === 0) return [];

    const midpoint = (arr: CandleData[], start: number, len: number): number | null => {
        if (start < 0 || start + len > arr.length) return null;
        let hi = -Infinity, lo = Infinity;
        for (let i = start; i < start + len; i++) {
            if (arr[i].high > hi) hi = arr[i].high;
            if (arr[i].low < lo) lo = arr[i].low;
        }
        return (hi + lo) / 2;
    };

    // 1. Calculate raw values at each index i
    const tenkanRaw: (number | null)[] = new Array(n).fill(null);
    const kijunRaw: (number | null)[] = new Array(n).fill(null);
    const senkouBRaw: (number | null)[] = new Array(n).fill(null);

    for (let i = 0; i < n; i++) {
        tenkanRaw[i] = i >= tenkanPeriod - 1 ? midpoint(sorted, i - tenkanPeriod + 1, tenkanPeriod) : null;
        kijunRaw[i] = i >= kijunPeriod - 1 ? midpoint(sorted, i - kijunPeriod + 1, kijunPeriod) : null;
        senkouBRaw[i] = i >= senkouBPeriod - 1 ? midpoint(sorted, i - senkouBPeriod + 1, senkouBPeriod) : null;
    }

    const result: IchimokuDataPoint[] = [];

    // The result should cover all original timestamps + displacement future ones
    const totalPoints = n + displacement;

    for (let i = 0; i < totalPoints; i++) {
        let time: Time;
        if (i < n) {
            time = sorted[i].time as Time;
        } else {
            // Generate future time (assuming 1-min candles, displacement is minutes)
            const lastTime = sorted[n - 1].time as number;
            time = (lastTime + (i - n + 1) * 60) as unknown as Time;
        }

        // Tenkan/Kijun: plotted at current time
        const tenkan = i < n ? tenkanRaw[i] : null;
        const kijun = i < n ? kijunRaw[i] : null;

        // Senkou A/B: calculated at (i - displacement), plotted at i
        const sourceIdx = i - displacement;
        let senkouA: number | null = null;
        let senkouB: number | null = null;
        if (sourceIdx >= 0 && sourceIdx < n) {
            const t = tenkanRaw[sourceIdx];
            const k = kijunRaw[sourceIdx];
            if (t !== null && k !== null) senkouA = (t + k) / 2;
            senkouB = senkouBRaw[sourceIdx];
        }

        // Chikou: Plot current close displacement periods ago
        // So at index i, value is close from (i + displacement)
        const chikouIdx = i + displacement;
        let chikou: number | null = null;
        if (chikouIdx >= 0 && chikouIdx < n) {
            chikou = sorted[chikouIdx].close;
        }

        result.push({ time, tenkan, kijun, senkouA, senkouB, chikou });
    }

    return result;
}

// ---------------------------------------------------------------------------
// 8. Parabolic SAR
// ---------------------------------------------------------------------------
export function calculateParabolicSAR(
    data: CandleData[],
    minAF: number = 0.02,
    maxAF: number = 0.2
): IndicatorDataPoint[] {
    const sorted = sortAndDedup(data);
    if (sorted.length < 2) return [];

    const result: IndicatorDataPoint[] = [];
    let isLong = sorted[1].close > sorted[0].close;
    let af = minAF;
    let ep = isLong ? sorted[0].high : sorted[0].low;
    let sar = isLong ? sorted[0].low : sorted[0].high;

    result.push({ time: sorted[0].time as Time, value: sar });

    for (let i = 1; i < sorted.length; i++) {
        const prevSar = sar;
        sar = prevSar + af * (ep - prevSar);

        if (isLong) {
            sar = Math.min(sar, sorted[i - 1].low);
            if (i >= 2) sar = Math.min(sar, sorted[i - 2].low);
            if (sorted[i].low < sar) {
                isLong = false;
                sar = ep;
                ep = sorted[i].low;
                af = minAF;
            } else {
                if (sorted[i].high > ep) {
                    ep = sorted[i].high;
                    af = Math.min(af + minAF, maxAF);
                }
            }
        } else {
            sar = Math.max(sar, sorted[i - 1].high);
            if (i >= 2) sar = Math.max(sar, sorted[i - 2].high);
            if (sorted[i].high > sar) {
                isLong = true;
                sar = ep;
                ep = sorted[i].high;
                af = minAF;
            } else {
                if (sorted[i].low < ep) {
                    ep = sorted[i].low;
                    af = Math.min(af + minAF, maxAF);
                }
            }
        }

        result.push({ time: sorted[i].time as Time, value: sar });
    }
    return result;
}

// ---------------------------------------------------------------------------
// 9. Donchian Channel
// ---------------------------------------------------------------------------
export function calculateDonchian(data: CandleData[], period: number): BandDataPoint[] {
    const sorted = sortAndDedup(data);
    const result: BandDataPoint[] = [];
    if (sorted.length < period) return result;
    for (let i = period - 1; i < sorted.length; i++) {
        let hi = -Infinity, lo = Infinity;
        for (let j = i - period + 1; j <= i; j++) {
            if (sorted[j].high > hi) hi = sorted[j].high;
            if (sorted[j].low < lo) lo = sorted[j].low;
        }
        result.push({ time: sorted[i].time as Time, upper: hi, lower: lo, middle: (hi + lo) / 2 });
    }
    return result;
}

// ---------------------------------------------------------------------------
// 10. Bollinger Bands
// ---------------------------------------------------------------------------
export function calculateBollingerBands(data: CandleData[], period: number, stdDev: number): BandDataPoint[] {
    const sorted = sortAndDedup(data);
    const result: BandDataPoint[] = [];
    if (sorted.length < period) return result;
    for (let i = period - 1; i < sorted.length; i++) {
        let sum = 0;
        for (let j = i - period + 1; j <= i; j++) sum += sorted[j].close;
        const mean = sum / period;
        let sqSum = 0;
        for (let j = i - period + 1; j <= i; j++) sqSum += (sorted[j].close - mean) ** 2;
        const sd = Math.sqrt(sqSum / period);
        result.push({
            time: sorted[i].time as Time,
            upper: mean + stdDev * sd,
            middle: mean,
            lower: mean - stdDev * sd,
        });
    }
    return result;
}

// ---------------------------------------------------------------------------
// 11. Opening Range
// ---------------------------------------------------------------------------
export function calculateOpeningRange(data: CandleData[], minutes: number): BandDataPoint[] {
    const sorted = sortAndDedup(data);
    if (sorted.length === 0) return [];

    // Group candles by date
    const dailyCandles = new Map<string, CandleData[]>();
    for (const c of sorted) {
        const d = new Date((c.time as number) * 1000);
        const dateStr = `${d.getUTCFullYear()}-${d.getUTCMonth() + 1}-${d.getUTCDate()}`;
        if (!dailyCandles.has(dateStr)) dailyCandles.set(dateStr, []);
        dailyCandles.get(dateStr)!.push(c);
    }

    const result: BandDataPoint[] = [];

    for (const c of sorted) {
        const d = new Date((c.time as number) * 1000);
        const dateStr = `${d.getUTCFullYear()}-${d.getUTCMonth() + 1}-${d.getUTCDate()}`;
        const group = dailyCandles.get(dateStr) || [];
        
        // Find ORB high and low for this day
        // RTH session starts at 9:30 AM (570 minutes)
        const sessionStart = 570;
        const orbEnd = sessionStart + minutes;
        
        const orbCandles = group.filter(x => {
            const xd = new Date((x.time as number) * 1000);
            const xm = xd.getUTCHours() * 60 + xd.getUTCMinutes();
            return xm >= sessionStart && xm < orbEnd;
        });

        if (orbCandles.length === 0) {
            result.push({ time: c.time as Time, upper: NaN, lower: NaN, middle: NaN });
            continue;
        }

        let hi = -Infinity, lo = Infinity;
        for (const oc of orbCandles) {
            if (oc.high > hi) hi = oc.high;
            if (oc.low < lo) lo = oc.low;
        }
        const mid = (hi + lo) / 2;

        // The indicator is only plotted after the ORB window has completed
        const cm = d.getUTCHours() * 60 + d.getUTCMinutes();
        if (cm >= orbEnd && cm < 960) { // 960 is 16:00 (RTH end)
            result.push({ time: c.time as Time, upper: hi, lower: lo, middle: mid });
        } else {
            result.push({ time: c.time as Time, upper: NaN, lower: NaN, middle: NaN });
        }
    }

    return result;
}

// ---------------------------------------------------------------------------
// 12. RSI
// ---------------------------------------------------------------------------
export function calculateRSI(data: CandleData[], period: number): IndicatorDataPoint[] {
    const result: IndicatorDataPoint[] = [];
    const sorted = sortAndDedup(data);
    if (sorted.length <= period || period <= 0) return result;

    let sumGain = 0, sumLoss = 0;
    for (let i = 1; i <= period; i++) {
        const diff = sorted[i].close - sorted[i - 1].close;
        if (diff >= 0) sumGain += diff; else sumLoss += Math.abs(diff);
    }
    let avgGain = sumGain / period;
    let avgLoss = sumLoss / period;

    const rsiVal = avgLoss === 0 ? 100 : 100 - (100 / (1 + avgGain / avgLoss));
    result.push({ time: sorted[period].time as Time, value: rsiVal });

    for (let i = period + 1; i < sorted.length; i++) {
        const diff = sorted[i].close - sorted[i - 1].close;
        const gain = diff >= 0 ? diff : 0;
        const loss = diff < 0 ? Math.abs(diff) : 0;
        avgGain = (avgGain * (period - 1) + gain) / period;
        avgLoss = (avgLoss * (period - 1) + loss) / period;
        const rsi = avgLoss === 0 ? 100 : 100 - (100 / (1 + avgGain / avgLoss));
        result.push({ time: sorted[i].time as Time, value: rsi });
    }
    return result;
}

// ---------------------------------------------------------------------------
// 13. Stochastic Oscillator
// ---------------------------------------------------------------------------
export function calculateStochastic(
    data: CandleData[],
    kPeriod: number = 14,
    dPeriod: number = 3,
    dSlow: number = 3
): StochasticDataPoint[] {
    const sorted = sortAndDedup(data);
    if (sorted.length < kPeriod) return [];

    // Raw %K
    const rawK: number[] = [];
    for (let i = kPeriod - 1; i < sorted.length; i++) {
        let hi = -Infinity, lo = Infinity;
        for (let j = i - kPeriod + 1; j <= i; j++) {
            if (sorted[j].high > hi) hi = sorted[j].high;
            if (sorted[j].low < lo) lo = sorted[j].low;
        }
        const denom = hi - lo;
        rawK.push(denom !== 0 ? ((sorted[i].close - lo) / denom) * 100 : 50);
    }

    // Smooth %K with dSlow SMA
    const smoothK = smaArray(rawK, dSlow);

    // %D = SMA of smoothK
    const validSK = smoothK.filter(v => v !== null) as number[];
    const dLine = smaArray(validSK, dPeriod);

    const result: StochasticDataPoint[] = [];
    let skOffset = 0;
    for (let i = 0; i < smoothK.length; i++) {
        if (smoothK[i] === null) continue;
        const kVal = smoothK[i]!;
        const dVal = dLine[skOffset] ?? kVal;
        const timeIdx = kPeriod - 1 + i;
        if (timeIdx < sorted.length) {
            result.push({ time: sorted[timeIdx].time as Time, k: kVal, d: dVal });
        }
        skOffset++;
    }
    return result;
}

// ---------------------------------------------------------------------------
// 14. Momentum
// ---------------------------------------------------------------------------
export function calculateMomentum(data: CandleData[], period: number): IndicatorDataPoint[] {
    const sorted = sortAndDedup(data);
    const result: IndicatorDataPoint[] = [];
    if (sorted.length <= period) return result;
    for (let i = period; i < sorted.length; i++) {
        result.push({ time: sorted[i].time as Time, value: sorted[i].close - sorted[i - period].close });
    }
    return result;
}

// ---------------------------------------------------------------------------
// 15. CCI (Commodity Channel Index)
// ---------------------------------------------------------------------------
export function calculateCCI(data: CandleData[], period: number): IndicatorDataPoint[] {
    const sorted = sortAndDedup(data);
    const result: IndicatorDataPoint[] = [];
    if (sorted.length < period) return result;
    for (let i = period - 1; i < sorted.length; i++) {
        let sum = 0;
        const tps: number[] = [];
        for (let j = i - period + 1; j <= i; j++) {
            const tp = (sorted[j].high + sorted[j].low + sorted[j].close) / 3;
            tps.push(tp);
            sum += tp;
        }
        const mean = sum / period;
        let meanDev = 0;
        for (const tp of tps) meanDev += Math.abs(tp - mean);
        meanDev /= period;
        const cci = meanDev !== 0 ? (tps[tps.length - 1] - mean) / (0.015 * meanDev) : 0;
        result.push({ time: sorted[i].time as Time, value: cci });
    }
    return result;
}

// ---------------------------------------------------------------------------
// 16. ROC (Rate of Change)
// ---------------------------------------------------------------------------
export function calculateROC(data: CandleData[], period: number): IndicatorDataPoint[] {
    const sorted = sortAndDedup(data);
    const result: IndicatorDataPoint[] = [];
    if (sorted.length <= period) return result;
    for (let i = period; i < sorted.length; i++) {
        const prev = sorted[i - period].close;
        result.push({ time: sorted[i].time as Time, value: prev !== 0 ? ((sorted[i].close - prev) / prev) * 100 : 0 });
    }
    return result;
}

// ---------------------------------------------------------------------------
// 17. MACD
// ---------------------------------------------------------------------------
export function calculateMACD(
    data: CandleData[],
    fast: number = 12,
    slow: number = 26,
    signalPeriod: number = 9
): MACDDataPoint[] {
    const sorted = sortAndDedup(data);
    if (sorted.length < slow) return [];
    const closes = sorted.map(c => c.close);

    const fastEMA = emaArray(closes, fast);
    const slowEMA = emaArray(closes, slow);

    const macdLine: { time: Time; value: number }[] = [];
    for (let i = 0; i < sorted.length; i++) {
        if (fastEMA[i] !== null && slowEMA[i] !== null) {
            macdLine.push({ time: sorted[i].time as Time, value: fastEMA[i]! - slowEMA[i]! });
        }
    }

    if (macdLine.length < signalPeriod) return [];

    const macdVals = macdLine.map(m => m.value);
    const k = 2 / (signalPeriod + 1);
    let sum = 0;
    for (let i = 0; i < signalPeriod; i++) sum += macdVals[i];
    let ema = sum / signalPeriod;

    const result: MACDDataPoint[] = [];
    for (let i = signalPeriod - 1; i < macdLine.length; i++) {
        if (i === signalPeriod - 1) {
            // first signal value
        } else {
            ema = (macdVals[i] - ema) * k + ema;
        }
        result.push({
            time: macdLine[i].time,
            macd: macdVals[i],
            signal: ema,
            histogram: macdVals[i] - ema,
        });
    }
    return result;
}

// ---------------------------------------------------------------------------
// 18. DMI (Directional Movement Index) with ADX
// ---------------------------------------------------------------------------
export function calculateDMI(
    data: CandleData[],
    diPeriod: number = 14,
    adxPeriod: number = 14
): DMIDataPoint[] {
    const sorted = sortAndDedup(data);
    if (sorted.length < diPeriod + 1) return [];

    const n = sorted.length;
    const trArr: number[] = [sorted[0].high - sorted[0].low];
    const plusDM: number[] = [0];
    const minusDM: number[] = [0];

    for (let i = 1; i < n; i++) {
        const tr = Math.max(
            sorted[i].high - sorted[i].low,
            Math.abs(sorted[i].high - sorted[i - 1].close),
            Math.abs(sorted[i].low - sorted[i - 1].close)
        );
        trArr.push(tr);

        const upMove = sorted[i].high - sorted[i - 1].high;
        const downMove = sorted[i - 1].low - sorted[i].low;
        plusDM.push(upMove > downMove && upMove > 0 ? upMove : 0);
        minusDM.push(downMove > upMove && downMove > 0 ? downMove : 0);
    }

    // Smoothed with Wilder's method
    const smooth = (arr: number[], period: number): number[] => {
        const res: number[] = [];
        let sum = 0;
        for (let i = 0; i < period; i++) sum += arr[i];
        res.push(sum);
        for (let i = period; i < arr.length; i++) {
            res.push(res[res.length - 1] - res[res.length - 1] / period + arr[i]);
        }
        return res;
    };

    const sTR = smooth(trArr, diPeriod);
    const sPlusDM = smooth(plusDM, diPeriod);
    const sMinusDM = smooth(minusDM, diPeriod);

    const diValues: { time: Time; plusDI: number; minusDI: number; dx: number }[] = [];
    for (let i = 0; i < sTR.length; i++) {
        const pdi = sTR[i] !== 0 ? (sPlusDM[i] / sTR[i]) * 100 : 0;
        const mdi = sTR[i] !== 0 ? (sMinusDM[i] / sTR[i]) * 100 : 0;
        const diSum = pdi + mdi;
        const dx = diSum !== 0 ? (Math.abs(pdi - mdi) / diSum) * 100 : 0;
        const timeIdx = diPeriod - 1 + i;
        if (timeIdx < n) {
            diValues.push({ time: sorted[timeIdx].time as Time, plusDI: pdi, minusDI: mdi, dx });
        }
    }

    // ADX = smoothed average of DX
    const result: DMIDataPoint[] = [];
    if (diValues.length < adxPeriod) return diValues.map(d => ({ ...d, adx: d.dx }));

    let adxSum = 0;
    for (let i = 0; i < adxPeriod; i++) adxSum += diValues[i].dx;
    let adx = adxSum / adxPeriod;

    for (let i = 0; i < diValues.length; i++) {
        if (i < adxPeriod - 1) {
            result.push({ time: diValues[i].time, plusDI: diValues[i].plusDI, minusDI: diValues[i].minusDI, adx: 0 });
        } else if (i === adxPeriod - 1) {
            result.push({ time: diValues[i].time, plusDI: diValues[i].plusDI, minusDI: diValues[i].minusDI, adx });
        } else {
            adx = (adx * (adxPeriod - 1) + diValues[i].dx) / adxPeriod;
            result.push({ time: diValues[i].time, plusDI: diValues[i].plusDI, minusDI: diValues[i].minusDI, adx });
        }
    }
    return result;
}

// ---------------------------------------------------------------------------
// 19. Williams %R
// ---------------------------------------------------------------------------
export function calculateWilliamsR(data: CandleData[], period: number): IndicatorDataPoint[] {
    const sorted = sortAndDedup(data);
    const result: IndicatorDataPoint[] = [];
    if (sorted.length < period) return result;
    for (let i = period - 1; i < sorted.length; i++) {
        let hi = -Infinity, lo = Infinity;
        for (let j = i - period + 1; j <= i; j++) {
            if (sorted[j].high > hi) hi = sorted[j].high;
            if (sorted[j].low < lo) lo = sorted[j].low;
        }
        const denom = hi - lo;
        result.push({ time: sorted[i].time as Time, value: denom !== 0 ? ((hi - sorted[i].close) / denom) * -100 : 0 });
    }
    return result;
}

// ---------------------------------------------------------------------------
// 20. ADX (standalone)
// ---------------------------------------------------------------------------
export function calculateADX(data: CandleData[], period: number): IndicatorDataPoint[] {
    const dmi = calculateDMI(data, period, period);
    return dmi.filter(d => d.adx > 0).map(d => ({ time: d.time, value: d.adx }));
}

// ---------------------------------------------------------------------------
// 21. ATR
// ---------------------------------------------------------------------------
export function calculateATR(data: CandleData[], period: number = 14): IndicatorDataPoint[] {
    const sorted = sortAndDedup(data);
    const result: IndicatorDataPoint[] = [];
    if (sorted.length < period + 1 || period <= 0) return result;

    const tr: number[] = [sorted[0].high - sorted[0].low];
    for (let i = 1; i < sorted.length; i++) {
        tr.push(Math.max(
            sorted[i].high - sorted[i].low,
            Math.abs(sorted[i].high - sorted[i - 1].close),
            Math.abs(sorted[i].low - sorted[i - 1].close)
        ));
    }

    let sum = 0;
    for (let i = 0; i < period; i++) sum += tr[i];
    let atr = sum / period;
    result.push({ time: sorted[period - 1].time as Time, value: atr });

    for (let i = period; i < tr.length; i++) {
        atr = (atr * (period - 1) + tr[i]) / period;
        result.push({ time: sorted[i].time as Time, value: atr });
    }
    return result;
}

// ---------------------------------------------------------------------------
// 22. OBV (On Balance Volume)
// ---------------------------------------------------------------------------
export function calculateOBV(data: CandleData[]): IndicatorDataPoint[] {
    const sorted = sortAndDedup(data);
    if (sorted.length === 0) return [];
    const result: IndicatorDataPoint[] = [];
    let obv = 0;
    result.push({ time: sorted[0].time as Time, value: obv });
    for (let i = 1; i < sorted.length; i++) {
        if (sorted[i].close > sorted[i - 1].close) obv += sorted[i].volume;
        else if (sorted[i].close < sorted[i - 1].close) obv -= sorted[i].volume;
        result.push({ time: sorted[i].time as Time, value: obv });
    }
    return result;
}

// ---------------------------------------------------------------------------
// 23. Accumulation/Distribution
// ---------------------------------------------------------------------------
export function calculateAccDist(data: CandleData[]): IndicatorDataPoint[] {
    const sorted = sortAndDedup(data);
    if (sorted.length === 0) return [];
    const result: IndicatorDataPoint[] = [];
    let ad = 0;
    for (const c of sorted) {
        const denom = c.high - c.low;
        const clv = denom !== 0 ? ((c.close - c.low) - (c.high - c.close)) / denom : 0;
        ad += clv * c.volume;
        result.push({ time: c.time as Time, value: ad });
    }
    return result;
}

// ---------------------------------------------------------------------------
// 24. Volume (plain bars)
// ---------------------------------------------------------------------------
export function calculateVolume(data: CandleData[]): { time: Time; value: number; color: string }[] {
    const sorted = sortAndDedup(data);
    return sorted.map(c => ({
        time: c.time as Time,
        value: c.volume,
        color: c.close >= c.open ? "rgba(16,185,129,0.5)" : "rgba(239,68,68,0.5)",
    }));
}

// ---------------------------------------------------------------------------
// 25. RVOL (Relative Volume – simplified intraday)
// ---------------------------------------------------------------------------
export function calculateRVOL(data: CandleData[], period: number = 14): IndicatorDataPoint[] {
    const sorted = sortAndDedup(data);
    const result: IndicatorDataPoint[] = [];
    if (sorted.length < period) return result;
    const volumes = sorted.map(c => c.volume);
    for (let i = period - 1; i < sorted.length; i++) {
        let sum = 0;
        for (let j = i - period + 1; j <= i; j++) sum += volumes[j];
        const avg = sum / period;
        result.push({ time: sorted[i].time as Time, value: avg !== 0 ? volumes[i] / avg : 1 });
    }
    return result;
}

// ---------------------------------------------------------------------------
// 26. Accumulated Volume
// ---------------------------------------------------------------------------
export function calculateAccumulatedVolume(data: CandleData[]): IndicatorDataPoint[] {
    const sorted = sortAndDedup(data);
    let cum = 0;
    return sorted.map(c => { cum += c.volume; return { time: c.time as Time, value: cum }; });
}

// ---------------------------------------------------------------------------
// 27. Heikin-Ashi
// ---------------------------------------------------------------------------
export function calculateHeikinAshi(data: CandleData[]): HeikinAshiDataPoint[] {
    const sorted = sortAndDedup(data);
    if (sorted.length === 0) return [];
    const result: HeikinAshiDataPoint[] = [];

    let prevHA = {
        open: (sorted[0].open + sorted[0].close) / 2,
        close: (sorted[0].open + sorted[0].high + sorted[0].low + sorted[0].close) / 4,
    };
    result.push({
        time: sorted[0].time as Time,
        open: prevHA.open,
        close: prevHA.close,
        high: Math.max(sorted[0].high, prevHA.open, prevHA.close),
        low: Math.min(sorted[0].low, prevHA.open, prevHA.close),
    });

    for (let i = 1; i < sorted.length; i++) {
        const haClose = (sorted[i].open + sorted[i].high + sorted[i].low + sorted[i].close) / 4;
        const haOpen = (prevHA.open + prevHA.close) / 2;
        const haHigh = Math.max(sorted[i].high, haOpen, haClose);
        const haLow = Math.min(sorted[i].low, haOpen, haClose);
        result.push({ time: sorted[i].time as Time, open: haOpen, high: haHigh, low: haLow, close: haClose });
        prevHA = { open: haOpen, close: haClose };
    }
    return result;
}
