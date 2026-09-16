"use client";

import type { DayCandles, MultiDayCandles, Strategy, TradeRecord, EquityPoint } from "@/lib/api_backtester";
import Chart from "@/components/backtester/Chart";

/**
 * El grafico de «Analisis por trade», extraido para poder pintarlo en DOS
 * sitios: su propia pestaña y, en version compacta, dentro del visor modal
 * que abre el click en un ticker (Trades y Calendario). GapsDelTicker
 * tambien lo reutiliza, desplegado bajo su fila.
 *
 * POR QUE UN COMPONENTE Y NO COPIAR EL BLOQUE. Los datos (velas, equity,
 * trades del dia) los carga el PADRE cuando se pide un dia; aqui solo se
 * pintan. Duplicar el bloque habria dejado dos sitios que enseñan lo mismo y
 * que se desincronizan en cuanto se toque uno — el patron que ya ha mordido en
 * este repo con las listas de indicadores.
 *
 * `compacto` solo baja las alturas: dentro del visor modal no hacen falta
 * los 520 px de la pestaña completa.
 */
interface PanelAnalisisTradeProps {
    dayCandles: DayCandles | null;
    multiDayCandles?: MultiDayCandles | null;
    activeStrategy?: Strategy | null;
    currentTrades: TradeRecord[];
    currentEquity: EquityPoint[];
    candlesLoading: boolean;
    equityLoading?: boolean;
    loadProgress: number;
    compacto?: boolean;
}

export default function PanelAnalisisTrade({
    dayCandles,
    multiDayCandles = null,
    activeStrategy,
    currentTrades,
    currentEquity,
    candlesLoading,
    equityLoading,
    loadProgress,
    compacto = false,
}: PanelAnalisisTradeProps) {
    const alturaMin = compacto ? 380 : 520;

    return (
        <div style={{ minHeight: alturaMin, display: "flex", flexDirection: "column", position: "relative" }}>

            {candlesLoading && (
                <div
                    style={{
                        display: "flex",
                        flexDirection: "column",
                        alignItems: "center",
                        justifyContent: "center",
                        flex: 1,
                        minHeight: alturaMin,
                        gap: 16,
                    }}
                >
                    <div style={{ width: 240 }}>
                        <div
                            style={{
                                display: "flex",
                                justifyContent: "space-between",
                                alignItems: "center",
                                marginBottom: 6,
                                fontFamily: "var(--color-ec-sans)",
                                fontSize: 10,
                                fontWeight: 600,
                                textTransform: "uppercase",
                                letterSpacing: "0.08em",
                                color: "var(--color-ec-text-secondary)",
                            }}
                        >
                            <span>Cargando trade</span>
                            <span
                                style={{
                                    fontFamily: "var(--color-ec-mono)",
                                    color: "var(--color-ec-copper)",
                                    fontWeight: 700,
                                }}
                            >
                                {Math.round(loadProgress)}%
                            </span>
                        </div>
                        <div
                            style={{
                                height: 4,
                                width: "100%",
                                backgroundColor: "var(--color-ec-bg-sidebar)",
                                borderRadius: 2,
                                overflow: "hidden",
                            }}
                        >
                            <div
                                style={{
                                    height: "100%",
                                    width: `${loadProgress}%`,
                                    backgroundColor: "var(--color-ec-copper)",
                                    borderRadius: 2,
                                    transition: "width 150ms ease-out",
                                }}
                            />
                        </div>
                    </div>
                </div>
            )}

            {!candlesLoading && equityLoading && (
                <div
                    style={{
                        fontSize: 10,
                        color: "var(--color-ec-text-muted)",
                        fontFamily: "var(--color-ec-sans)",
                        marginBottom: 4,
                        textAlign: "center",
                    }}
                >
                    Cargando equity…
                </div>
            )}

            {!candlesLoading && dayCandles && dayCandles.candles.length > 0 && (
                <Chart
                    candles={dayCandles.candles}
                    multiDayCandles={multiDayCandles}
                    activeStrategy={activeStrategy}
                    trades={currentTrades}
                    equity={currentEquity}
                    ticker={dayCandles.ticker}
                    date={dayCandles.date}
                />
            )}

            {!candlesLoading && (!dayCandles || dayCandles.candles.length === 0) && (
                <div
                    style={{
                        display: "flex",
                        flexDirection: "column",
                        alignItems: "center",
                        justifyContent: "center",
                        flex: 1,
                        minHeight: alturaMin,
                    }}
                >
                    <p className="text-[10px] text-[var(--muted)] text-center font-mono">
                        {compacto
                            ? "No hay velas para este trade."
                            : "Selecciona un dia en el panel lateral para ver el analisis del trade."}
                    </p>
                </div>
            )}
        </div>
    );
}
