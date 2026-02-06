import pandas as pd
import numpy as np
from app.database import get_db_connection

def process_daily_metrics(df):
    """
    Takes a DataFrame of 1-minute bars for a single ticker and calculates 
    daily metrics based on Notion definitions.
    """
    if df.empty:
        return pd.DataFrame()
        
    df = df.sort_values('timestamp')
    df['date'] = df['timestamp'].dt.date
    
    daily_results = []
    
    # We need the previous day's close for Gap %
    # Since we process in batches, we'll try to get it from the group or previous group
    prev_close = None
    
    for date, group in df.groupby('date'):
        # Identify Sessions (Eastern Time assumed or consistent with data)
        # 04:00 - 09:30 (PM)
        # 09:30 - 16:00 (RTH)
        times = group['timestamp'].dt.time
        pm_session = group[(times >= pd.Timestamp("04:00").time()) & (times < pd.Timestamp("09:30").time())]
        rth_session = group[(times >= pd.Timestamp("09:30").time()) & (times < pd.Timestamp("16:00").time())]
        
        if rth_session.empty:
            # Still update prev_close for next day if RTH exists but this day is missing it
            if not group.empty:
                prev_close = group.iloc[-1]['close']
            continue
            
        rth_open = float(rth_session.iloc[0]['open'])
        rth_close = float(rth_session.iloc[-1]['close'])
        rth_high = float(rth_session['high'].max())
        rth_low = float(rth_session['low'].min())
        rth_volume = float(rth_session['volume'].sum())
        
        # Calculation Logic
        gap_pct = 0.0
        if prev_close is not None:
            gap_pct = ((rth_open - prev_close) / prev_close) * 100
            
        # PM High & Fade
        pm_high = pm_session['high'].max() if not pm_session.empty else 0.0
        pm_volume = pm_session['volume'].sum() if not pm_session.empty else 0.0
        pm_fade = 0.0
        if pm_high > 0:
            pm_fade = ((rth_open - pm_high) / pm_high) * 100
            
        # New Metrics
        # Open < VWAP
        open_vwap = rth_session.iloc[0]['vwap']
        open_lt_vwap = rth_open < open_vwap if not pd.isna(open_vwap) else False
        
        # PM High Break
        pm_high_break = rth_high > pm_high if pm_high > 0 else False
        
        # Timed Returns
        def get_return_at(minutes):
            limit_time = (pd.Timestamp(f"{date} 09:30") + pd.Timedelta(minutes=minutes)).time()
            snapshot = rth_session[rth_session['timestamp'].dt.time <= limit_time]
            if not snapshot.empty:
                price_at = snapshot.iloc[-1]['close']
                return float(((price_at - rth_open) / rth_open) * 100), price_at
            return 0.0, rth_open

        m15_ret, m15_price = get_return_at(15)
        m30_ret, m30_price = get_return_at(30)
        m60_ret, m60_price = get_return_at(60)

        metric = {
            'ticker': group.iloc[0]['ticker'],
            'date': date,
            'rth_open': rth_open,
            'rth_high': rth_high,
            'rth_low': rth_low,
            'rth_close': rth_close,
            'rth_volume': rth_volume,
            'gap_at_open_pct': float(gap_pct),
            'pm_high': float(pm_high),
            'pm_volume': float(pm_volume),
            'pmh_fade_to_open_pct': float(pm_fade),
            'rth_run_pct': float(((rth_close - rth_open) / rth_open) * 100),
            'high_spike_pct': float(((rth_high - rth_open) / rth_open) * 100),
            'low_spike_pct': float(((rth_low - rth_open) / rth_open) * 100),
            'rth_fade_to_close_pct': float(((rth_close - rth_high) / rth_high) * 100) if rth_high > 0 else 0.0,
            'open_lt_vwap': bool(open_lt_vwap),
            'pm_high_break': bool(pm_high_break),
            'm15_return_pct': m15_ret,
            'm30_return_pct': m30_ret,
            'm60_return_pct': m60_ret,
            'close_lt_m15': bool(rth_close < m15_price),
            'close_lt_m30': bool(rth_close < m30_price),
            'close_lt_m60': bool(rth_close < m60_price),
            'hod_time': rth_session.loc[rth_session['high'].idxmax()]['timestamp'].strftime("%H:%M"),
            'lod_time': rth_session.loc[rth_session['low'].idxmin()]['timestamp'].strftime("%H:%M"),
            'close_direction': 'green' if rth_close > rth_open else 'red'
        }
        
        daily_results.append(metric)
        prev_close = rth_close # Update for next iteration
        
    return pd.DataFrame(daily_results)

def get_dashboard_stats(filtered_df):
    """
    Generate stats for the dashboard from the filtered records.
    """
    if filtered_df.empty:
        return {}
        
    stats = {
        'count': len(filtered_df),
        'averages': {
            'gap_at_open_pct': float(filtered_df['gap_at_open_pct'].mean()) if 'gap_at_open_pct' in filtered_df else 0,
            'pmh_fade_to_open_pct': float(filtered_df['pmh_fade_to_open_pct'].mean()) if 'pmh_fade_to_open_pct' in filtered_df else 0,
            'rth_run_pct': float(filtered_df['rth_run_pct'].mean()) if 'rth_run_pct' in filtered_df else 0,
            'high_spike_pct': float(filtered_df['high_spike_pct'].mean()) if 'high_spike_pct' in filtered_df else 0,
            'low_spike_pct': float(filtered_df['low_spike_pct'].mean()) if 'low_spike_pct' in filtered_df else 0,
            'rth_fade_to_close_pct': float(filtered_df['rth_fade_to_close_pct'].mean()) if 'rth_fade_to_close_pct' in filtered_df else 0,
            'm15_return_pct': float(filtered_df['m15_return_pct'].mean()) if 'm15_return_pct' in filtered_df else 0,
            'm30_return_pct': float(filtered_df['m30_return_pct'].mean()) if 'm30_return_pct' in filtered_df else 0,
            'm60_return_pct': float(filtered_df['m60_return_pct'].mean()) if 'm60_return_pct' in filtered_df else 0,
            'open_lt_vwap': float((filtered_df['open_lt_vwap'] == True).mean() * 100) if 'open_lt_vwap' in filtered_df else 0,
            'pm_high_break': float((filtered_df['pm_high_break'] == True).mean() * 100) if 'pm_high_break' in filtered_df else 0,
            'close_direction_red': float((filtered_df['close_direction'] == 'red').mean() * 100) if 'close_direction' in filtered_df else 0,
            'close_lt_m15': float((filtered_df['close_lt_m15'] == True).mean() * 100) if 'close_lt_m15' in filtered_df else 0,
            'close_lt_m30': float((filtered_df['close_lt_m30'] == True).mean() * 100) if 'close_lt_m30' in filtered_df else 0,
            'close_lt_m60': float((filtered_df['close_lt_m60'] == True).mean() * 100) if 'close_lt_m60' in filtered_df else 0,
            'avg_volume': float(filtered_df['rth_volume'].mean()) if 'rth_volume' in filtered_df else 0,
            'avg_pm_volume': float(filtered_df['pm_volume'].mean()) if 'pm_volume' in filtered_df else 0,
            'avg_open_price': float(filtered_df['rth_open'].mean()) if 'rth_open' in filtered_df else 0,
            'avg_close_price': float(filtered_df['rth_close'].mean()) if 'rth_close' in filtered_df else 0,
            'avg_pmh_price': float(filtered_df['pm_high'].mean()) if 'pm_high' in filtered_df else 0,
        },
        'distributions': {
            'hod_time': filtered_df['hod_time'].value_counts().head(20).to_dict() if 'hod_time' in filtered_df else {},
            'lod_time': filtered_df['lod_time'].value_counts().head(20).to_dict() if 'lod_time' in filtered_df else {},
            'close_direction': filtered_df['close_direction'].value_counts().to_dict() if 'close_direction' in filtered_df else {},
        }
    }
    return stats

def get_aggregate_time_series(ticker_date_pairs):
    """
    For a list of (ticker, date), calculate the average % change from RTH open 
    at each minute of the day.
    """
    if not ticker_date_pairs:
        return []
        
    con = get_db_connection()
    
    # Simple approach: fetch all data for these pairs and aggregate in pandas
    # In a massive dataset, we would use a optimized SQL query.
    
    # ticker_date_pairs is a list of tuples or list of dicts from the filtered records
    
    all_series = []
    
    for item in ticker_date_pairs[:10]: # Limit to 10 for performance in this iteration
        ticker = item['ticker']
        date = item['date']
        
        # Fetch 1m data for this day
        df = con.execute("SELECT timestamp, open, close FROM historical_data WHERE ticker = ? AND CAST(timestamp AS DATE) = ?", 
                         [ticker, date]).fetch_df()
        
        if df.empty:
            continue
            
        df = df.sort_values('timestamp')
        # Filter RTH
        rth = df[(df['timestamp'].dt.time >= pd.Timestamp("09:30").time()) & 
                 (df['timestamp'].dt.time < pd.Timestamp("16:00").time())]
        
        if rth.empty:
            continue
            
        open_price = rth.iloc[0]['open']
        rth['pct_change'] = ((rth['close'] - open_price) / open_price) * 100
        rth['time_str'] = rth['timestamp'].dt.strftime("%H:%M")
        
        all_series.append(rth[['time_str', 'pct_change']])
        
    con.close()
    
    if not all_series:
        return []
        
    combined = pd.concat(all_series)
    agg = combined.groupby('time_str')['pct_change'].mean().reset_index()
    
    return agg.rename(columns={'time_str': 'time', 'pct_change': 'value'}).to_dict(orient="records")
