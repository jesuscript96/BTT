import pandas as pd
import numpy as np
from app.database import get_db_connection

def process_daily_metrics(df, con=None):
    """
    Takes a DataFrame of 1-minute bars for a single ticker and calculates 
    daily metrics based on Notion definitions.
    
    Args:
        df: DataFrame with 1-minute bars
        con: Database connection to query prev_close from daily_metrics
    """
    if df.empty:
        return pd.DataFrame()
        
    df = df.sort_values('timestamp')
    df['date'] = df['timestamp'].dt.date
    
    daily_results = []
    ticker = df.iloc[0]['ticker'] if not df.empty else None
    
    for date, group in df.groupby('date'):
        # Identify Sessions (Eastern Time assumed or consistent with data)
        # 03:00 - 08:30 (PM)
        # 09:30 - 16:00 (RTH)
        # Clean group for summation: remove exact duplicates and identify resampled fillers
        clean_group = group.drop_duplicates(subset=['timestamp']).sort_values('timestamp')
        clean_group['is_resampled'] = (clean_group['volume'] == clean_group['volume'].shift(1)) & \
                                     (clean_group['close'] == clean_group['close'].shift(1))
        
        c_times = clean_group['timestamp'].dt.time
        pm_session = clean_group[(c_times >= pd.Timestamp("04:00").time()) & (c_times < pd.Timestamp("09:30").time())]
        rth_session = clean_group[(c_times >= pd.Timestamp("09:30").time()) & (c_times < pd.Timestamp("16:00").time())]
        
        if rth_session.empty:
            # Still update prev_close for next day if RTH exists but this day is missing it
            if not clean_group.empty and con:
                 # Logic for prev close not critical if no RTH
                 pass
            continue
            
        rth_open = float(rth_session.iloc[0]['open'])
        rth_close = float(rth_session.iloc[-1]['close'])
        rth_high = float(rth_session['high'].max())
        rth_low = float(rth_session['low'].min())
        rth_volume = float(rth_session[~rth_session['is_resampled']]['volume'].sum())
        
        # Calculation Logic - Get prev_close
        gap_pct = 0.0
        prev_close = None
        
        if con and ticker:
            try:
                # Improved to get actual last trading day before current date
                result = con.execute("""
                    SELECT close FROM daily_metrics 
                    WHERE ticker = ? AND CAST(timestamp AS VARCHAR)[:10] < CAST(? AS VARCHAR)
                    ORDER BY timestamp DESC LIMIT 1
                """, [ticker, date]).fetchone()
                if result:
                    prev_close = result[0]
            except:
                pass 
        
        if prev_close is not None and prev_close > 0:
            gap_pct = ((rth_open - prev_close) / prev_close) * 100
            
        # PM High & Volume
        pm_high = pm_session['high'].max() if not pm_session.empty else 0.0
        pm_volume = float(pm_session[~pm_session['is_resampled']]['volume'].sum()) if not pm_session.empty else 0.0
        
        # PMH Gap %: Open vs PM High
        pmh_gap_pct = ((rth_open - pm_high) / pm_high * 100) if pm_high > 0 else 0.0
        
        # PM Fade: (PMH - Open) / PMH
        pmh_fade_pct = ((pm_high - rth_open) / pm_high * 100) if pm_high > 0 else 0.0
        
        # PM High Time
        pm_high_time = pm_session.loc[pm_session['high'].idxmax()]['timestamp'].strftime("%H:%M") if not pm_session.empty and len(pm_session) > 0 else None
        
        # PM Low Time 
        pm_low = pm_session['low'].min() if not pm_session.empty else 0.0
        pm_low_time = pm_session.loc[pm_session['low'].idxmin()]['timestamp'].strftime("%H:%M") if not pm_session.empty and len(pm_session) > 0 else None

        # Timed Returns
        def get_return_at(minutes):
            limit_time = (pd.Timestamp(f"{date} 09:30") + pd.Timedelta(minutes=minutes)).time()
            snapshot = rth_session[rth_session['timestamp'].dt.time <= limit_time]
            if not snapshot.empty:
                return float(((snapshot.iloc[-1]['close'] - rth_open) / rth_open) * 100)
            return 0.0
        
        m15_ret = get_return_at(15)
        m30_ret = get_return_at(30)
        m60_ret = get_return_at(60)
        m180_ret = get_return_at(180)
        
        # RTH Run/Fade/Range
        rth_run_pct = ((rth_high - rth_open) / rth_open) * 100 if rth_open > 0 else 0.0
        rth_fade_pct = ((rth_close - rth_high) / rth_high) * 100 if rth_high > 0 else 0.0
        rth_range_pct = ((rth_high - rth_low) / rth_low) * 100 if rth_low > 0 else 0.0
        day_return_pct = ((rth_close - rth_open) / rth_open) * 100 if rth_open > 0 else 0.0

        # Close 15:59
        close_1559_row = rth_session[rth_session['timestamp'].dt.time == pd.Timestamp("15:59").time()]
        close_1559 = float(close_1559_row.iloc[-1]['close']) if not close_1559_row.empty else rth_close
        
        last_close = float(clean_group.iloc[-1]['close'])

        metric = {
            'ticker': group.iloc[0]['ticker'],
            'volume': float(clean_group['volume'].sum()),
            'open': float(clean_group.iloc[0]['open']),
            'close': float(clean_group.iloc[-1]['close']),
            'high': float(clean_group['high'].max()),
            'low': float(clean_group['low'].min()),
            'timestamp': pd.Timestamp(date),
            'transactions': 0,
            
            # Pre-Market
            'pm_volume': float(pm_volume),
            'pm_high': float(pm_high),
            'pm_low': float(pm_low),
            'pm_high_time': pm_high_time,
            'pm_low_time': pm_low_time,
            'gap_pct': float(gap_pct),
            'pmh_gap_pct': float(pmh_gap_pct),
            'pmh_fade_pct': float(pmh_fade_pct),
            
            # RTH
            'rth_volume': float(rth_volume),
            'rth_open': rth_open,
            'rth_high': rth_high,
            'rth_low': rth_low,
            'rth_close': rth_close,
            'hod_time': rth_session.loc[rth_session['high'].idxmax()]['timestamp'].strftime("%H:%M"),
            'lod_time': rth_session.loc[rth_session['low'].idxmin()]['timestamp'].strftime("%H:%M"),
            'rth_run_pct': float(rth_run_pct),
            'rth_fade_pct': float(rth_fade_pct),
            'rth_range_pct': float(rth_range_pct),
            
            # Returns
            'm15_return_pct': float(m15_ret),
            'm30_return_pct': float(m30_ret),
            'm60_return_pct': float(m60_ret),
            'm180_return_pct': float(m180_ret),
            
            # Closing
            'close_1559': float(close_1559),
            'last_close': float(last_close),
            'day_return_pct': float(day_return_pct),
            'prev_close': float(prev_close) if prev_close else None,
            'eod_volume': 0 
        }
        
        daily_results.append(metric)
        
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
            'gap_at_open_pct': float(filtered_df['gap_pct'].mean()) if 'gap_pct' in filtered_df else 0,
            'pmh_fade_to_open_pct': float(filtered_df['pmh_fade_pct'].mean()) if 'pmh_fade_pct' in filtered_df else 0,
            'rth_run_pct': float(filtered_df['rth_run_pct'].mean()) if 'rth_run_pct' in filtered_df else 0,
            'rth_fade_to_close_pct': float(filtered_df['rth_fade_pct'].mean()) if 'rth_fade_pct' in filtered_df else 0,
            'm15_return_pct': float(filtered_df['m15_return_pct'].mean()) if 'm15_return_pct' in filtered_df else 0,
            'm30_return_pct': float(filtered_df['m30_return_pct'].mean()) if 'm30_return_pct' in filtered_df else 0,
            'm60_return_pct': float(filtered_df['m60_return_pct'].mean()) if 'm60_return_pct' in filtered_df else 0,
            
            'avg_volume': float(filtered_df['rth_volume'].mean()) if 'rth_volume' in filtered_df else 0,
            'avg_pm_volume': float(filtered_df['pm_volume'].mean()) if 'pm_volume' in filtered_df else 0,
            'avg_open_price': float(filtered_df['rth_open'].mean()) if 'rth_open' in filtered_df else 0,
            'avg_close_price': float(filtered_df['rth_close'].mean()) if 'rth_close' in filtered_df else 0,
            'avg_pmh_price': float(filtered_df['pm_high'].mean()) if 'pm_high' in filtered_df else 0,
        },
        'distributions': {
            'hod_time': filtered_df['hod_time'].value_counts().head(20).to_dict() if 'hod_time' in filtered_df else {},
            'lod_time': filtered_df['lod_time'].value_counts().head(20).to_dict() if 'lod_time' in filtered_df else {},
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
    all_series = []
    
    for item in ticker_date_pairs[:10]:
        ticker = item['ticker']
        date = item['date']
        
        df = con.execute("SELECT timestamp, open, close FROM intraday_1m WHERE ticker = ? AND CAST(timestamp AS DATE) = CAST(? AS DATE)", 
                         [ticker, date]).fetch_df()
        
        if df.empty:
            continue
            
        df = df.sort_values('timestamp')
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
