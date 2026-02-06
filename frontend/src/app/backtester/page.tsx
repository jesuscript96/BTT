"use client";

import React, { useState } from 'react';
import { ExecutionPanel } from '@/components/backtester/ExecutionPanel';
import { BacktestDashboard } from '@/components/backtester/BacktestDashboard';
import { BacktestResult } from '@/types/backtest';

export default function BacktesterPage() {
    const [currentResult, setCurrentResult] = useState<BacktestResult | null>(null);
    const [isLoading, setIsLoading] = useState(false);

    const handleBacktestComplete = (result: BacktestResult) => {
        setCurrentResult(result);
        setIsLoading(false);
    };

    const handleBacktestStart = () => {
        setIsLoading(true);
    };

    return (
        <div className="flex h-screen bg-gray-50">
            {/* Execution Panel - Sidebar */}
            <ExecutionPanel
                onBacktestStart={handleBacktestStart}
                onBacktestComplete={handleBacktestComplete}
                isLoading={isLoading}
            />

            {/* Main Dashboard */}
            <main className="flex-1 overflow-auto">
                {currentResult ? (
                    <BacktestDashboard result={currentResult} />
                ) : (
                    <div className="flex items-center justify-center h-full">
                        <div className="text-center">
                            <h2 className="text-2xl font-semibold text-gray-900 mb-2">
                                Backtester Pro
                            </h2>
                            <p className="text-gray-500">
                                Configure your backtest in the panel and click "Run Backtest" to begin
                            </p>
                        </div>
                    </div>
                )}
            </main>
        </div>
    );
}
