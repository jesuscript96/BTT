"""
Calculation functions for trading metrics.
All calculations follow formulas from Documentacion_calculos.
"""
import pandas as pd
import numpy as np
from typing import Dict, Optional

# ============================================
# Session Helpers
# ============================================

def get_pm_session(df: pd.DataFrame) -> pd.DataFrame:
    """
    Filter DataFrame for Pre-Market session (04:00-09:30 ET).
    
    Args:
        df: DataFrame with 'timestamp' column
        
    Returns:
        DataFrame filtered to PM hours
    """
    times = df['timestamp'].dt.time
    pm_start = pd.Timestamp("04:00").time()
    pm_end = pd.Timestamp("09:30").time()
    return df[(times >= pm_start) & (times < pm_end)]


def get_rth_session(df: pd.DataFrame) -> pd.DataFrame:
    """
    Filter DataFrame for Regular Trading Hours (09:30-16:00 ET).
    
    Args:
        df: DataFrame with 'timestamp' column
        
    Returns:
        DataFrame filtered to RTH hours
    """
    times = df['timestamp'].dt.time
    rth_start = pd.Timestamp("09:30").time()
    rth_end = pd.Timestamp("16:00").time()
    return df[(times >= rth_start) & (times < rth_end)]


# ============================================
# Daily Metrics (from daily_metrics table)
# ============================================

def calculate_gap(daily_df: pd.DataFrame) -> pd.DataFrame:
    """
    Calculate gap metrics using prev_close from daily_metrics.
    
    Formulas: 
        gap_at_open_pct: ((open - prev_close) / prev_close) * 100
        pmh_gap_pct: ((pm_high - prev_close) / prev_close) * 100
    
    Args:
        daily_df: DataFrame with columns: ticker, date, open, close, pm_high (if available)
        
    Returns:
        DataFrame with added columns: prev_close, gap_at_open_pct, pmh_gap_pct
    """
    daily_df = daily_df.sort_values(['ticker', 'date'])
    daily_df['prev_close'] = daily_df.groupby('ticker')['close'].shift(1)
    
    # Gap at Open %
    daily_df['gap_at_open_pct'] = np.where(
        daily_df['prev_close'].notna() & (daily_df['prev_close'] > 0),
        ((daily_df['open'] - daily_df['prev_close']) / daily_df['prev_close'] * 100),
        0.0
    )
    
    # PM High Gap % (if pm_high is provided in daily_df)
    if 'pm_high' in daily_df.columns:
        daily_df['pmh_gap_pct'] = np.where(
            daily_df['prev_close'].notna() & (daily_df['prev_close'] > 0) & (daily_df['pm_high'] > 0),
            ((daily_df['pm_high'] - daily_df['prev_close']) / daily_df['prev_close'] * 100),
            0.0
        )
    else:
        daily_df['pmh_gap_pct'] = 0.0
        
    return daily_df


def calculate_volatility(daily_df: pd.DataFrame) -> pd.DataFrame:
    """
    Calculate RTH Run %, Range %, and Low Spike < Prev Close.
    
    Formulas:
        rth_run_pct: ((high - open) / open) * 100
        rth_range_pct: ((high - low) / low) * 100
        low_spike_lt_prev_close: low < prev_close (bool cast to int)
    """
    # RTH Run % (Open to High)
    daily_df['rth_run_pct'] = np.where(
        daily_df['open'] > 0,
        ((daily_df['high'] - daily_df['open']) / daily_df['open'] * 100),
        0.0
    )
    
    # RTH Range % (Low to High)
    daily_df['rth_range_pct'] = np.where(
        daily_df['low'] > 0,
        ((daily_df['high'] - daily_df['low']) / daily_df['low'] * 100),
        0.0
    )
    
    # Low Spike < Prev Close
    if 'prev_close' in daily_df.columns:
        daily_df['low_spike_lt_prev_close'] = (
            (daily_df['low'] < daily_df['prev_close']) & daily_df['prev_close'].notna()
        ).astype(int)
    else:
        daily_df['low_spike_lt_prev_close'] = 0
        
    return daily_df


def calculate_day_return(daily_df: pd.DataFrame) -> pd.DataFrame:
    """
    Calculate Day Return % (open → close).
    """
    daily_df['day_return_pct'] = np.where(
        daily_df['open'] > 0,
        ((daily_df['close'] - daily_df['open']) / daily_df['open'] * 100),
        0.0
    )
    return daily_df


def calculate_fades(daily_df: pd.DataFrame) -> pd.DataFrame:
    """
    Calculate PM High Fade % and RTH Fade %.
    
    Formulas:
        pmh_fade_to_open_pct: ((open - pm_high) / pm_high) * 100
        rth_fade_to_close_pct: ((close - high) / high) * 100
    """
    # PM High Fade %
    if 'pm_high' in daily_df.columns:
        daily_df['pmh_fade_to_open_pct'] = np.where(
            (daily_df['pm_high'] > 0),
            ((daily_df['open'] - daily_df['pm_high']) / daily_df['pm_high'] * 100),
            0.0
        )
    else:
        daily_df['pmh_fade_to_open_pct'] = 0.0
        
    # RTH Fade %
    daily_df['rth_fade_to_close_pct'] = np.where(
        (daily_df['high'] > 0),
        ((daily_df['close'] - daily_df['high']) / daily_df['high'] * 100),
        0.0
    )
    return daily_df


def calculate_daily_metrics(daily_df: pd.DataFrame) -> pd.DataFrame:
    """
    Calculate all daily metrics at once.
    """
    daily_df = calculate_gap(daily_df)
    daily_df = calculate_volatility(daily_df)
    daily_df = calculate_day_return(daily_df)
    daily_df = calculate_fades(daily_df)
    return daily_df


# ============================================
# Intraday Metrics (from intraday_1m table)
# ============================================

def calculate_pm_metrics(intraday_df: pd.DataFrame) -> Dict[str, float]:
    """
    Calculate Pre-Market metrics from intraday_1m data.
    
    Returns:
        - pm_high: Highest price in PM session
        - pm_volume: Total volume in PM session
        - pmh_fade_to_open_pct: Fade from PM high to RTH open
    
    Args:
        intraday_df: DataFrame with 1-minute bars for a single day
        
    Returns:
        Dictionary with PM metrics
    """
    pm_session = get_pm_session(intraday_df)
    rth_session = get_rth_session(intraday_df)
    
    pm_high = float(pm_session['high'].max()) if not pm_session.empty else 0.0
    pm_volume = float(pm_session['volume'].sum()) if not pm_session.empty else 0.0
    rth_open = float(rth_session.iloc[0]['open']) if not rth_session.empty else 0.0
    
    pmh_fade = 0.0
    if pm_high > 0 and rth_open > 0:
        pmh_fade = ((rth_open - pm_high) / pm_high * 100)
    
    return {
        'pm_high': pm_high,
        'pm_volume': pm_volume,
        'pmh_fade_to_open_pct': pmh_fade
    }


def calculate_mx_returns(intraday_df: pd.DataFrame) -> Dict[str, float]:
    """
    Calculate returns at specific minutes after open (M15, M30, M60, M180).
    
    Formula: ((price_at_Mx - rth_open) / rth_open) * 100
    
    Args:
        intraday_df: DataFrame with 1-minute bars for a single day
        
    Returns:
        Dictionary with M15, M30, M60, M180 returns
    """
    rth_session = get_rth_session(intraday_df)
    
    if rth_session.empty:
        return {
            'm15_return_pct': 0.0,
            'm30_return_pct': 0.0,
            'm60_return_pct': 0.0,
            'm180_return_pct': 0.0
        }
    
    rth_open = float(rth_session.iloc[0]['open'])
    rth_session = rth_session.copy()
    rth_session['minutes_since_open'] = (
        (rth_session['timestamp'] - rth_session['timestamp'].iloc[0]).dt.total_seconds() / 60
    )
    
    def get_return_at(minutes: int) -> float:
        snapshot = rth_session[rth_session['minutes_since_open'] <= minutes]
        if snapshot.empty:
            return 0.0
        price_at = float(snapshot.iloc[-1]['close'])
        return ((price_at - rth_open) / rth_open * 100) if rth_open > 0 else 0.0
    
    return {
        'm15_return_pct': get_return_at(15),
        'm30_return_pct': get_return_at(30),
        'm60_return_pct': get_return_at(60),
        'm180_return_pct': get_return_at(180)
    }


def calculate_spike_metrics(intraday_df: pd.DataFrame) -> Dict[str, float]:
    """
    Calculate high/low spike percentages.
    
    Formula High: ((rth_high - rth_open) / rth_open) * 100
    Formula Low: ((rth_low - rth_open) / rth_open) * 100
    
    Args:
        intraday_df: DataFrame with 1-minute bars for a single day
        
    Returns:
        Dictionary with high_spike_pct and low_spike_pct
    """
    rth_session = get_rth_session(intraday_df)
    
    if rth_session.empty:
        return {'high_spike_pct': 0.0, 'low_spike_pct': 0.0}
    
    rth_open = float(rth_session.iloc[0]['open'])
    rth_high = float(rth_session['high'].max())
    rth_low = float(rth_session['low'].min())
    
    high_spike = ((rth_high - rth_open) / rth_open * 100) if rth_open > 0 else 0.0
    low_spike = ((rth_low - rth_open) / rth_open * 100) if rth_open > 0 else 0.0
    
    return {
        'high_spike_pct': high_spike,
        'low_spike_pct': low_spike
    }


def calculate_intraday_metrics(intraday_df: pd.DataFrame) -> Dict[str, float]:
    """
    Calculate all intraday metrics at once.
    
    Args:
        intraday_df: DataFrame with 1-minute bars for a single day
        
    Returns:
        Dictionary with all intraday metrics
    """
    metrics = {}
    metrics.update(calculate_pm_metrics(intraday_df))
    metrics.update(calculate_mx_returns(intraday_df))
    metrics.update(calculate_spike_metrics(intraday_df))
    return metrics
