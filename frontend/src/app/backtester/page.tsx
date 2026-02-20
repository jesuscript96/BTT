"use client";

import React, { useState, useEffect } from 'react';
import { useSearchParams } from 'next/navigation';
import { ExecutionPanel } from '@/components/backtester/ExecutionPanel';
import { BacktestDashboard } from '@/components/backtester/BacktestDashboard';
import { BacktestResult } from '@/types/backtest';

interface PrefillData {
    strategy_id: string;
    strategy_name: string;
    dataset_id: string | null;
}

export default function BacktesterPage() {
    const searchParams = useSearchParams();
    const [currentResult, setCurrentResult] = useState<BacktestResult | null>(null);
    const [isLoading, setIsLoading] = useState(false);
    const [prefillData, setPrefillData] = useState<PrefillData | null>(null);

    useEffect(() => {
        if (searchParams.get('prefill') === 'true') {
            try {
                const raw = sessionStorage.getItem('backtester_prefill');
                if (raw) {
                    setPrefillData(JSON.parse(raw));
                    sessionStorage.removeItem('backtester_prefill');
                }
            } catch (e) {
                console.error('Failed to read prefill data:', e);
            }
        }
    }, [searchParams]);

    const handleBacktestComplete = (result: BacktestResult) => {
        setCurrentResult(result);
        setIsLoading(false);
    };

    const handleBacktestStart = () => {
        setIsLoading(true);
    };

    return (
        <div className="flex h-screen bg-background transition-colors duration-300">
            {/* Execution Panel - Sidebar */}
            <ExecutionPanel
                onBacktestStart={handleBacktestStart}
                onBacktestComplete={handleBacktestComplete}
                isLoading={isLoading}
                prefillData={prefillData}
            />

            {/* Main Dashboard */}
            <main className="flex-1 overflow-auto bg-background/50">
                {currentResult ? (
                    <BacktestDashboard result={currentResult} />
                ) : (
                    <div className="flex items-center justify-center h-full">
                        <div className="text-center p-8">
                            <h2 className="text-3xl font-black text-foreground mb-4 uppercase tracking-tighter">
                                Backtester
                            </h2>
                            <p className="text-muted-foreground max-w-sm mx-auto">
                                Configure your backtest in the panel and click &quot;Run Backtest&quot; to begin your quantitative analysis
                            </p>
                            <div className="mt-8 p-6 bg-card border border-border rounded-2xl border-dashed">
                                <p className="text-xs text-muted-foreground uppercase font-bold tracking-widest">Ready for deployment</p>
                            </div>
                        </div>
                    </div>
                )}
            </main>
        </div>
    );
}
