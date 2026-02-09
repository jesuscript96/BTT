'use client'

import { useState } from 'react'
import ConfigurationPanel from '@/components/database/ConfigurationPanel'
import ResultsPanel from '@/components/database/ResultsPanel'
import RiskManagementPanel from '@/components/database/RiskManagementPanel'

export default function DatabasePage() {
    const [searchConfig, setSearchConfig] = useState({
        mode: 'Consecutive Red',
        space: '3',
        datasetId: '',
        dateFrom: '',
        dateTo: ''
    })

    const [passCriteria, setPassCriteria] = useState({
        minTrades: 0,
        minWinRate: 0,
        minProfitFactor: 0,
        minExpectedValue: 0,
        minNetProfit: 0
    })

    const [riskConfig, setRiskConfig] = useState({
        stopLoss: { enabled: false, type: 'percent', value: 5 },
        takeProfit: { enabled: false, type: 'percent', value: 5 },
        partials: {
            enabled: false,
            tp1: { percent: 20, rMultiple: 1 },
            tp2: { percent: 30, rMultiple: 2 },
            tp3: { percent: 50, rMultiple: 3 }
        },
        trailingStop: { enabled: false, activation: 1, trail: 0.5 }
    })

    return (
        <div className="flex h-screen bg-background overflow-hidden transition-colors duration-300">
            {/* Left Panel - Configuration */}
            <div className="w-80 border-r border-border flex-shrink-0 overflow-y-auto bg-sidebar/30">
                <ConfigurationPanel
                    config={searchConfig}
                    onChange={setSearchConfig}
                />
            </div>

            {/* Center Panel - Results */}
            <div className="flex-1 overflow-y-auto bg-background/50">
                <ResultsPanel
                    searchConfig={searchConfig}
                    passCriteria={passCriteria}
                    onPassCriteriaChange={setPassCriteria}
                />
            </div>

            {/* Right Panel - Risk Management */}
            <div className="w-80 border-l border-border flex-shrink-0 overflow-y-auto bg-sidebar/30">
                <RiskManagementPanel
                    config={riskConfig}
                    onChange={setRiskConfig}
                />
            </div>
        </div>
    )
}
