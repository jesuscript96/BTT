"use client";

import React, { useState, useEffect } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { BacktestDashboard } from '@/components/backtester/BacktestDashboard';
import { BacktestResult } from '@/types/backtest';
import { Loader2, ArrowLeft } from 'lucide-react';

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api";

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
            <div className="flex flex-col items-center justify-center h-screen bg-gray-50 text-gray-900">
                <Loader2 className="w-10 h-10 animate-spin text-blue-600 mb-4" />
                <p className="text-gray-500 font-medium uppercase tracking-widest text-xs">Loading Results...</p>
            </div>
        );
    }

    if (error || !result) {
        return (
            <div className="flex flex-col items-center justify-center h-screen bg-gray-50 text-gray-900 p-4">
                <div className="bg-white border border-red-200 rounded-2xl p-8 max-w-md w-full text-center shadow-lg">
                    <h2 className="text-xl font-bold text-red-600 mb-4">Error Loading Results</h2>
                    <p className="text-gray-500 mb-8">{error || "Backtest run not found"}</p>
                    <button
                        onClick={() => router.push('/backtester')}
                        className="bg-gray-100 hover:bg-gray-200 text-gray-900 px-6 py-3 rounded-xl font-bold transition-all flex items-center gap-2 mx-auto"
                    >
                        <ArrowLeft className="w-4 h-4" />
                        Back to Backtester
                    </button>
                </div>
            </div>
        );
    }

    return (
        <div className="h-screen bg-gray-50 flex flex-col">
            <header className="bg-white border-b border-gray-200 px-6 py-3 flex items-center justify-between">
                <button
                    onClick={() => router.push('/backtester')}
                    className="text-gray-500 hover:text-gray-900 transition-colors flex items-center gap-2 text-sm font-medium"
                >
                    <ArrowLeft className="w-4 h-4" />
                    Back to Selection
                </button>
                <div className="text-[10px] font-black text-gray-500 uppercase tracking-widest bg-gray-100 px-3 py-1 rounded-full border border-gray-200">
                    Run ID: {id}
                </div>
            </header>
            <div className="flex-1 overflow-hidden">
                <BacktestDashboard result={result} />
            </div>
        </div>
    );
}
