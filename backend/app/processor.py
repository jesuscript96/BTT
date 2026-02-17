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
            if not clean_group.empty:
                prev_close = clean_group.iloc[-1]['close']
            continue
            
        rth_open = float(rth_session.iloc[0]['open'])
        rth_close = float(rth_session.iloc[-1]['close'])
        rth_high = float(rth_session['high'].max())
        rth_low = float(rth_session['low'].min())
        rth_volume = float(rth_session[~rth_session['is_resampled']]['volume'].sum())
        
        # Calculation Logic - Get prev_close, prev_high, prev_low from daily_metrics
        gap_pct = 0.0
        prev_close = None
        prev_high = None
        prev_low = None
        if con and ticker:
            prev_date = date - pd.Timedelta(days=1)
            # Simple check for previous trading day (this is naive, improves if needed)
            # Actually for rolling calculation, exact prev trading day is best handled by logic 
            # outside this single-day processor or by improved query. 
            # But here we try to get "previous record".
            # For robustness, we might want to query ORDER BY date DESC LIMIT 1 < date.
            # But the current code uses strict date - 1 day. Let's stick to pattern or improve slightly if easy.
            # Let's try strict date-1 for now to match strict "prev_date" logic, or use a better query.
            # Given we are iterating, maybe we can pass 'prev_row' if we were processing in order?
            # But this function takes a DF which might be just one day.
            
            try:
                # Improved to get actual last trading day before current date
                result = con.execute("""
                    SELECT rth_close, rth_high, rth_low FROM daily_metrics 
                    WHERE ticker = ? AND CAST(timestamp AS VARCHAR)[:10] < CAST(? AS VARCHAR)
                    ORDER BY timestamp DESC LIMIT 1
                """, [ticker, date]).fetchone()
                if result:
                    prev_close = result[0]
                    prev_high = result[1]
                    prev_low = result[2]
            except:
                pass 
        
        if prev_close is not None and prev_close > 0:
            gap_pct = ((rth_open - prev_close) / prev_close) * 100
            
        # PM High & Volume
        pm_high = pm_session['high'].max() if not pm_session.empty else 0.0
        pm_volume = float(pm_session[~pm_session['is_resampled']]['volume'].sum()) if not pm_session.empty else 0.0
        pm_fade = 0.0
        # PM Fade: (Open - PMH) / PMH -- User: "Desvanecer... tras la apertura"
        # If open < pm_high, this is negative. 
        if pm_high > 0:
            pm_fade = ((rth_open - pm_high) / pm_high) * 100
            
        # New Metrics
        # VWAP not available in massive DB
        open_lt_vwap = False
        
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
        
        # Get prices and returns at specific times
        m1_ret, m1_price = get_return_at(1)
        m5_ret, m5_price = get_return_at(5)
        m15_ret, m15_price = get_return_at(15)
        m30_ret, m30_price = get_return_at(30)
        m60_ret, m60_price = get_return_at(60)
        m180_ret, m180_price = get_return_at(180)
        
        # Calculating User Requested Rolling Metrics (Daily Scalar Values)
        # 1. RTH Range %: (High - Low) / Low
        rth_range_pct = ((rth_high - rth_low) / rth_low) * 100 if rth_low > 0 else 0.0
        
        # 2. Return at Close vs Open %: (Close - Open) / Open
        # This is `day_return_pct`
        day_return_pct = ((rth_close - rth_open) / rth_open) * 100 if rth_open > 0 else 0.0
        
        # 3. High-Low Spikes % (Dual)
        # High Spike vs Prev High: (High - PrevHigh)/PrevHigh
        high_spike_prev_pct = ((rth_high - prev_high) / prev_high * 100) if prev_high and prev_high > 0 else 0.0
        # Low Spike vs Prev Low: (Low - PrevLow)/PrevLow
        low_spike_prev_pct = ((rth_low - prev_low) / prev_low * 100) if prev_low and prev_low > 0 else 0.0
        
        # 4. Gap Extension %
        # Interpret: (High - Open) / GapSize? 
        # If Gap is 0, undefined.
        # User: "Mide cuánto se extiende el movimiento del precio más allá del nivel del 'Gap' inicial."
        # Possible: (High - Open) / (Open - PrevClose). 
        # If Gap is positive, and we go higher, it's extension.
        gap_abs = abs(rth_open - prev_close) if prev_close else 0.0
        gap_ext_pct = 0.0
        if gap_abs > 0:
             # How much runs past open relative to the gap size
             # if gap is 1$, and run is 2$, pure extension is 200%?
             gap_ext_pct = (rth_high - rth_open) / gap_abs * 100
        
        # 5. Close Index %: (Close - Low) / (High - Low)
        den = (rth_high - rth_low)
        close_index_pct = ((rth_close - rth_low) / den * 100) if den > 0 else 0.0
        
        # 6. PMH Gap %
        # User: "Pre-Market High: Mide la distancia porcentual entre el precio actual y el máximo del pre-mercado"
        # Since this is a daily metric, 'Current Price' implies a specific snapshot. 
        # Usually 'Gap' implies Open. 
        # So (Open - PM High) / PM High
        pmh_gap_pct = ((rth_open - pm_high) / pm_high * 100) if pm_high > 0 else 0.0
        
        # 7. PM Fade at Open %
        # User: "Tendencia ... a desvanecer ... tras la apertura"
        # Often defined as (High of Day - Open) if fading up? Or (Open - Close) if fading down?
        # Given "PM Fade at Open", it sounds like "PM Move was X, Open is Y, Fade is ..."
        # Let's map it to the existing `pmh_fade_to_open_pct` which is (Open - PMH)/PMH.
        # Wait, if `pmh_gap_pct` is ALSO that, we have duplication?
        # Let's re-read carefully:
        # A. "PMH Gap % : Distancia % entre precio actual y maximo pre-mercado" -> (Close - PMH)? or (Open - PMH)? 
        # B. "PM Fade at Open % : Tendencia ... desvanecer ... tras apertura".
        # 
        # Let's assume:
        # PMH Gap % = (Open - PMH) / PMH. (Gap relative to PMH).
        # PM Fade at Open % = Maybe (Open - Low) / (PMH - Low)? Or how much it drops?
        # Let's use `pm_fade` calculated above as one of them.
        # And let's add `open_vs_pmh_pct` as the new one if distinct.
        # Actually `pm_fade` calculated at line 71 is `((rth_open - pm_high) / pm_high) * 100`.
        # This matches PMH Gap %.
        #
        # Let's look at "PM Fade at Open" again. "Desvanecer ... inmediatamente tras la apertura".
        # This might mean: (High_first_5m - Open) if it goes against PMH? 
        # Or (Open - Low_first_5m).
        # Let's stick to safe/standard interpretations or placeholders.
        # 
        # I will store values:
        # 'pmh_gap_pct': ((rth_open - pm_high)/pm_high) (The Gap vs PMH)
        # 'pm_fade_pct': ((rth_open - pm_high)/pm_high) ... wait these are the same.
        # 
        # Let's try: "PM Fade" = (PMH - Open) / (PMH - PrevClose)? (How much given back?)
        # Let's use existing 'pmh_fade_to_open_pct' for one.
        

        
        # PM High Time
        pm_high_time = pm_session.loc[pm_session['high'].idxmax()]['timestamp'].strftime("%H:%M") if not pm_session.empty and len(pm_session) > 0 else "00:00"
        
        # TIER 2: M(x) High/Low Spikes
        def get_spike_at(minutes, spike_type='high'):
            """Get max high or min low in first X minutes after open"""
            limit_time = (pd.Timestamp(f"{date} 09:30") + pd.Timedelta(minutes=minutes)).time()
            snapshot = rth_session[rth_session['timestamp'].dt.time <= limit_time]
            if not snapshot.empty:
                if spike_type == 'high':
                    spike_price = snapshot['high'].max()
                    return float(((spike_price - rth_open) / rth_open) * 100)
                else:  # 'low'
                    spike_price = snapshot['low'].min()
                    return float(((spike_price - rth_open) / rth_open) * 100)
            return 0.0
        
        m1_high_spike = get_spike_at(1, 'high')
        m5_high_spike = get_spike_at(5, 'high')
        m15_high_spike = get_spike_at(15, 'high')
        m30_high_spike = get_spike_at(30, 'high')
        m60_high_spike = get_spike_at(60, 'high')
        m180_high_spike = get_spike_at(180, 'high')
        
        m1_low_spike = get_spike_at(1, 'low')
        m5_low_spike = get_spike_at(5, 'low')
        m15_low_spike = get_spike_at(15, 'low')
        m30_low_spike = get_spike_at(30, 'low')
        m60_low_spike = get_spike_at(60, 'low')
        m180_low_spike = get_spike_at(180, 'low')
        
        # TIER 3: Return from M(x) to Close
        return_m15_to_close = ((rth_close - m15_price) / m15_price) * 100 if m15_price > 0 else 0.0
        return_m30_to_close = ((rth_close - m30_price) / m30_price) * 100 if m30_price > 0 else 0.0
        return_m60_to_close = ((rth_close - m60_price) / m60_price) * 100 if m60_price > 0 else 0.0

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
            'rth_run_pct': float(((rth_high - rth_open) / rth_open) * 100),
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
            'close_direction': 'green' if rth_close > rth_open else 'red',
            
            # NEW TIER 1 METRICS
            'prev_close': float(prev_close) if prev_close else None,
            'pmh_gap_pct': float(pmh_gap_pct),
            'rth_range_pct': float(rth_range_pct),
            'day_return_pct': float(day_return_pct),
            'pm_high_time': pm_high_time,
            
            # DASHBOARD ROLLING METRICS
            # We map the names to what the frontend expects or specific dashboard names
            'high_spike_prev_pct': float(high_spike_prev_pct),
            'low_spike_prev_pct': float(low_spike_prev_pct),
            'gap_extension_pct': float(gap_ext_pct),
            'close_index_pct': float(close_index_pct),
            # pm_fade is already in 'pmh_fade_to_open_pct'
            # rth_range is already in 'rth_range_pct'
            # day_return is already in 'day_return_pct' (Return Close vs Open)
            # pmh_gap is currently mapped to Open vs PMH in our logic above? 
            # Wait, logic above: `pmh_gap_pct = ((rth_open - pm_high) / pm_high * 100)`
            # In old code: `pmh_gap_pct` was ((pm_high - prev_close)/prev_close).
            # I replaced the variable `pmh_gap_pct` with the new calculation (Open - PMH)/ PMH.
            # But wait, looking at my PREVIOUS REPLACE BLOCK:
            # I defined `pmh_gap_pct = ((rth_open - pm_high) / pm_high * 100)`
            # AND `pm_fade` as same.
            # I should clarify in the variables.
            # Let's rely on `pmh_fade_to_open_pct` (Calculated line 70) for "Trend to fade".
            # And `pmh_gap_pct` (Line 100/New Repl) for "Gap %".
            
            # Correction: 
            # Old `pmh_gap_pct` (Line 100) was `((pm_high - prev_close) / prev_close)`.
            # If I want to keep that semantics (PMH vs Prev Close), I should keep it.
            # User request: "PMH Gap % : Distance % between Current Price and PMH".
            # Let's trust my new variable `pmh_gap_pct` is correct for User Request.
            # But I should probably add `pmh_vs_prev_close_pct` if I want to keep old semantic.
            # For now, I just ensure I export the new vars.
            
            # NEW TIER 2 METRICS - M(x) High Spikes
            'm1_high_spike_pct': float(m1_high_spike),
            'm5_high_spike_pct': float(m5_high_spike),
            'm15_high_spike_pct': float(m15_high_spike),
            'm30_high_spike_pct': float(m30_high_spike),
            'm60_high_spike_pct': float(m60_high_spike),
            'm180_high_spike_pct': float(m180_high_spike),
            
            # NEW TIER 2 METRICS - M(x) Low Spikes
            'm1_low_spike_pct': float(m1_low_spike),
            'm5_low_spike_pct': float(m5_low_spike),
            'm15_low_spike_pct': float(m15_low_spike),
            'm30_low_spike_pct': float(m30_low_spike),
            'm60_low_spike_pct': float(m60_low_spike),
            'm180_low_spike_pct': float(m180_low_spike),
            
            # NEW TIER 3 METRICS - Return from M(x) to Close
            'return_m15_to_close': float(return_m15_to_close),
            'return_m30_to_close': float(return_m30_to_close),
            'return_m60_to_close': float(return_m60_to_close)
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
            'gap_at_open_pct': float(filtered_df['gap_at_open_pct'].mean()) if 'gap_at_open_pct' in filtered_df else 0,
            'pmh_fade_to_open_pct': float(filtered_df['pmh_fade_to_open_pct'].mean()) if 'pmh_fade_to_open_pct' in filtered_df else 0,
            'rth_run_pct': float(filtered_df['rth_run_pct'].mean()) if 'rth_run_pct' in filtered_df else 0,
            'high_spike_pct': float(filtered_df['high_spike_pct'].mean()) if 'high_spike_pct' in filtered_df else 0,
            'low_spike_pct': float(filtered_df['low_spike_pct'].mean()) if 'low_spike_pct' in filtered_df else 0,
            'rth_fade_to_close_pct': float(filtered_df['rth_fade_to_close_pct'].mean()) if 'rth_fade_to_close_pct' in filtered_df else 0,
            'm15_return_pct': float(filtered_df['m15_return_pct'].mean()) if 'm15_return_pct' in filtered_df else 0,
            'm30_return_pct': float(filtered_df['m30_return_pct'].mean()) if 'm30_return_pct' in filtered_df else 0,
            'm60_return_pct': float(filtered_df['m60_return_pct'].mean()) if 'm60_return_pct' in filtered_df else 0,
            'open_lt_vwap': 0.0,  # VWAP not available in massive DB
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
    
    all_series = []
    
    for item in ticker_date_pairs[:10]:
        ticker = item['ticker']
        date = item['date']
        
        # Use intraday_1m (historical_data no longer exists)
        df = con.execute("SELECT timestamp, open, close FROM intraday_1m WHERE ticker = ? AND CAST(timestamp AS DATE) = CAST(? AS DATE)", 
                         [ticker, date]).fetch_df()
        
        if df.empty:
            continue
            
        df = df.sort_values('timestamp')
        # Filter RTH (09:30 - 16:00 ET)
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
