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
        <div style={{
      display: 'flex',
      height: '100dvh',
      backgroundColor: 'var(--color-ec-bg-base)',
      overflow: 'hidden',
    }}>
            {/* Left Panel - Configuration */}
            <div style={{
              width: 280,
              flexShrink: 0,
              borderRight: '0.5px solid var(--color-ec-border)',
              backgroundColor: 'var(--color-ec-bg-sidebar)',
              overflowY: 'auto',
              overflowX: 'hidden',
              scrollbarWidth: 'none',
            }}>
                <ConfigurationPanel
                    config={searchConfig}
                    onChange={setSearchConfig}
                />
            </div>

            {/* Center Panel - Results */}
            <div style={{
              flex: 1,
              overflowY: 'auto',
              overflowX: 'hidden',
              backgroundColor: 'var(--color-ec-bg-base)',
              minWidth: 0,
            }}>
                <ResultsPanel
                    searchConfig={searchConfig}
                    passCriteria={passCriteria}
                    onPassCriteriaChange={setPassCriteria}
                />
            </div>

            {/* Right Panel - Risk Management */}
            <div style={{
              width: 280,
              flexShrink: 0,
              borderLeft: '0.5px solid var(--color-ec-border)',
              backgroundColor: 'var(--color-ec-bg-sidebar)',
              overflowY: 'auto',
              overflowX: 'hidden',
              scrollbarWidth: 'none',
            }}>
                <RiskManagementPanel
                    config={riskConfig}
                    onChange={setRiskConfig}
                />
            </div>
        </div>
    )
}
