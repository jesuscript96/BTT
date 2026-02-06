"use client";

import React, { useState } from 'react';
import { StrategyForm } from '@/components/strategy-builder/StrategyForm';
import { StrategiesTable } from '@/components/strategy-builder/StrategiesTable';

export default function NewStrategyPage() {
    const [refreshTrigger, setRefreshTrigger] = useState(0);

    const handleStrategySaved = () => {
        setRefreshTrigger(prev => prev + 1);
    };

    return (
        <div className="space-y-8 pb-12">
            <StrategyForm onStrategySaved={handleStrategySaved} />

            <div className="px-2">
                <StrategiesTable refreshTrigger={refreshTrigger} />
            </div>
        </div>
    );
}
