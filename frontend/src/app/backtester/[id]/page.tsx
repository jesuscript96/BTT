"use client";

import React, { useState, useEffect } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { BacktestDashboard } from '@/components/backtester/BacktestDashboard';
import { BacktestResult } from '@/types/backtest';
import { Loader2, ArrowLeft } from 'lucide-react';
import { API_URL } from '@/config/constants';


export default function BacktestResultPage() {
    const { id } = useParams();
    const router = useRouter();
    const [result, setResult] = useState<BacktestResult | null>(null);
    const [isLoading, setIsLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        if (id) {
            fetchResult();
        }
    }, [id]);

    const fetchResult = async () => {
        setIsLoading(true);
        setError(null);
        try {
            const response = await fetch(`${API_URL}/backtest/results/${id}`);
            if (!response.ok) {
                throw new Error(`Failed to fetch results: ${response.statusText}`);
            }
            const data = await response.json();
            setResult(data);
        } catch (err) {
            console.error("Error fetching backtest result:", err);
            setError(err instanceof Error ? err.message : "Failed to load results");
        } finally {
            setIsLoading(false);
        }
    };

    if (isLoading) {
        return (
            <div className="flex flex-col items-center justify-center h-screen bg-background text-foreground">
                <Loader2 className="w-10 h-10 animate-spin text-blue-500 mb-4" />
                <p className="text-muted-foreground font-medium uppercase tracking-widest text-xs">Loading Results...</p>
            </div>
        );
    }

    if (error || !result) {
        return (
            <div className="flex flex-col items-center justify-center h-screen bg-background text-foreground p-4">
                <div className="bg-card border border-red-500/20 rounded-2xl p-8 max-w-md w-full text-center shadow-lg">
                    <h2 className="text-xl font-bold text-red-500 mb-4">Error Loading Results</h2>
                    <p className="text-muted-foreground mb-8">{error || "Backtest run not found"}</p>
                    <button
                        onClick={() => router.push('/backtester')}
                        className="bg-muted hover:bg-muted-foreground/10 text-foreground px-6 py-3 rounded-xl font-bold transition-all flex items-center gap-2 mx-auto"
                    >
                        <ArrowLeft className="w-4 h-4" />
                        Back to Backtester
                    </button>
                </div>
            </div>
        );
    }

    return (
        <div className="h-screen bg-background flex flex-col transition-colors duration-300">
            <header className="bg-card border-b border-border px-6 py-3 flex items-center justify-between">
                <button
                    onClick={() => router.push('/backtester')}
                    className="text-muted-foreground hover:text-foreground transition-colors flex items-center gap-2 text-sm font-medium"
                >
                    <ArrowLeft className="w-4 h-4" />
                    Back to Selection
                </button>
                <div className="text-[10px] font-black text-muted-foreground uppercase tracking-widest bg-muted px-3 py-1 rounded-full border border-border">
                    Run ID: {id}
                </div>
            </header>
            <div className="flex-1 overflow-hidden">
                <BacktestDashboard result={result} />
            </div>
        </div>
    );
}
