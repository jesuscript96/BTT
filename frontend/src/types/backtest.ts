// Backtest types
export interface BacktestRequest {
    strategy_ids: string[];
    weights: Record<string, number>;
    dataset_filters: any; // FilterRequest from Market Analysis
    query_id?: string;
    commission_per_share: number;
    locate_cost_per_100: number;
    slippage_pct: number;
    lookahead_prevention: boolean;
    initial_capital: number;
    risk_per_trade_r: number;
    market_interval: 'PM' | 'RTH' | 'AM';
    date_from: string;
    date_to: string;
    max_holding_minutes: number;
}

export interface BacktestResponse {
    run_id: string;
    status: string;
    message: string;
    results?: BacktestResult;
}

export interface BacktestResult {
    run_id: string;
    strategy_ids: string[];
    strategy_names: string[];
    weights: Record<string, number>;
    initial_capital: number;
    final_balance: number;
    total_return_pct: number;
    total_return_r: number;
    total_trades: number;
    winning_trades: number;
    losing_trades: number;
    win_rate: number;
    avg_r_multiple: number;
    max_drawdown_pct: number;
    max_drawdown_value: number;
    sharpe_ratio: number;
    equity_curve: EquityPoint[];
    drawdown_series: DrawdownPoint[];
    trades: Trade[];
    r_distribution: Record<string, number>;
    ev_by_time: Record<string, number>;
    ev_by_day: Record<string, number>;
    monthly_returns: Record<string, number>;
    correlation_matrix?: Record<string, Record<string, number>>;
    monte_carlo?: MonteCarloResult;
    executed_at: string;
}

export interface EquityPoint {
    timestamp: string;
    balance: number;
    open_positions?: number;
}

export interface DrawdownPoint {
    timestamp: string;
    drawdown_pct: number;
    drawdown_value: number;
    peak: number;
}

export interface Trade {
    id: string;
    strategy_id: string;
    strategy_name: string;
    ticker: string;
    entry_time: string;
    entry_price: number;
    exit_time?: string;
    exit_price?: number;
    stop_loss: number;
    take_profit: number;
    position_size: number;
    r_multiple?: number;
    fees: number;
    exit_reason?: string;
}

export interface MonteCarloResult {
    worst_drawdown_pct: number;
    best_final_balance: number;
    worst_final_balance: number;
    median_final_balance: number;
    percentile_5: number;
    percentile_25: number;
    percentile_75: number;
    percentile_95: number;
    probability_of_ruin: number;
}

export interface StrategySelection {
    strategy_id: string;
    name: string;
    weight: number;
}
