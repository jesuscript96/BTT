from fastapi import APIRouter, HTTPException
from typing import Optional
import yfinance as yf
import feedparser
import pandas as pd
import numpy as np
from datetime import datetime

router = APIRouter(
    prefix="/api/ticker-analysis",
    tags=["ticker-analysis"]
)

import threading
from datetime import timedelta

# Cache for ticker analysis data (15 minutes TTL)
_analysis_cache = {}
_analysis_cache_lock = threading.Lock()
ANALYSIS_CACHE_TTL = timedelta(minutes=15)

# Cache for SEC filings data (30 minutes TTL)
_filings_cache = {}
_filings_cache_lock = threading.Lock()
FILINGS_CACHE_TTL = timedelta(minutes=30)

# Caches for split endpoints (15 minutes TTL)
_chart_cache = {}
_chart_cache_lock = threading.Lock()
CHART_CACHE_TTL = timedelta(minutes=15)

_balance_sheet_cache = {}
_balance_sheet_cache_lock = threading.Lock()
BALANCE_SHEET_CACHE_TTL = timedelta(minutes=15)

_gap_stats_cache = {}
_gap_stats_cache_lock = threading.Lock()
GAP_STATS_CACHE_TTL = timedelta(minutes=15)

def safe_float(val):
    try:
        if val is None: return None
        f = float(val)
        if np.isnan(f) or np.isinf(f): return None
        return f
    except:
        return None

def scrape_knowthefloat(ticker: str) -> dict:
    import requests
    import urllib3
    import re
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    url = f"https://knowthefloat.com/ticker/{ticker}"
    try:
        r = requests.get(url, headers=headers, verify=False, timeout=3)
        if r.status_code != 200:
            return {}
            
        html = r.text
        sources = [
            {"name": "Yahoo Finance", "img": "yahooFinance.png"},
            {"name": "Finviz", "img": "finviz.png"},
            {"name": "Wall Street Journal", "img": "wsj.png"},
            {"name": "Dilution Tracker", "img": "dt.png"}
        ]
        
        results = {}
        for src in sources:
            parts = html.split(src["img"])
            if len(parts) > 1:
                card_text = parts[1][:1200]
                
                # Float
                float_val = ""
                float_match = re.search(r'class="float-section"[^>]*>\s*<h3>Float</h3>\s*<p>([^<]*)</p>', card_text, re.DOTALL | re.IGNORECASE)
                if float_match:
                    float_val = float_match.group(1).strip()
                
                # Short %
                short_val = ""
                short_match = re.search(r'class="short-percent-section"[^>]*>\s*<h3>Short % of Float</h3>\s*<p>([^<]*)</p>', card_text, re.DOTALL | re.IGNORECASE)
                if short_match:
                    short_val = short_match.group(1).strip()
                    
                # Outstanding
                out_val = ""
                out_match = re.search(r'class="outstanding-shares-section"[^>]*>\s*<h3>Oustanding Shares</h3>\s*<p>([^<]*)</p>', card_text, re.DOTALL | re.IGNORECASE)
                if out_match:
                    out_val = out_match.group(1).strip()
                    
                results[src["name"]] = {
                    "float": float_val,
                    "short_percent": short_val,
                    "outstanding": out_val
                }
        return results
    except Exception as e:
        print(f"Error scraping knowthefloat for {ticker}: {e}")
        return {}

def safe_mean(series):
    if series is None or len(series) == 0:
        return None
    val = series.mean()
    if pd.isna(val) or np.isnan(val) or np.isinf(val):
        return None
    return float(val)

def get_gap_stats_all_days(ticker: str) -> dict:
    ticker = ticker.upper()
    df = pd.DataFrame()
    
    # 1. Try to query database daily_metrics
    try:
        from app.database import get_db_connection
        con = get_db_connection()
        df = con.execute("SELECT * FROM daily_metrics WHERE ticker = ? ORDER BY timestamp ASC", [ticker]).fetchdf()
    except Exception as e:
        print(f"Error querying daily_metrics for {ticker}: {e}")
        
    # 2. If empty, fallback to yfinance
    if df.empty:
        try:
            session = get_yfinance_session()
            stock = yf.Ticker(ticker, session=session)
            hist = stock.history(period="5y")
            if not hist.empty:
                df = hist.reset_index()
                # Rename columns to match daily_metrics if needed, or map them
                df = df.rename(columns={
                    'Date': 'timestamp', 
                    'Datetime': 'timestamp',
                    'Open': 'open',
                    'High': 'high',
                    'Low': 'low',
                    'Close': 'close',
                    'Volume': 'volume'
                })
        except Exception as e:
            print(f"Error fetching yfinance history fallback for {ticker}: {e}")
            
    if df.empty:
        empty_stats = {
            "source": "none",
            "gap_days_count": 0,
            "high_rth_spike_avg": None,
            "low_rth_spike_avg": None,
            "pm_fade_avg": None,
            "rthh_fade_avg": None,
            "neg_close_freq": None,
            "close_above_pmh_freq": None,
            "close_below_vwap_freq": None
        }
        return {
            "gap_stats": empty_stats,
            "gap_stats_plus_1": empty_stats,
            "gap_stats_plus_2": empty_stats
        }

    # Ensure chronologically sorted
    if 'timestamp' in df.columns:
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df = df.sort_values('timestamp').reset_index(drop=True)
    
    # Calculate gap_pct if not exists
    if 'gap_pct' not in df.columns or df['gap_pct'].isnull().all():
        if 'close' in df.columns and 'open' in df.columns:
            df['prev_close'] = df['close'].shift(1)
            df['gap_pct'] = (df['open'] - df['prev_close']) / df['prev_close'] * 100
        else:
            df['gap_pct'] = 0.0

    # Locate gap day indices (gap_pct >= 20.0)
    gap_indices = df[df['gap_pct'] >= 20.0].index.tolist()

    def compute_stats_for_offset(offset):
        target_indices = [idx + offset for idx in gap_indices if idx + offset < len(df)]
        if not target_indices:
            return {
                "source": "database" if 'pmh_gap_pct' in df.columns else "yfinance",
                "gap_days_count": 0,
                "high_rth_spike_avg": None,
                "low_rth_spike_avg": None,
                "pm_fade_avg": None,
                "rthh_fade_avg": None,
                "neg_close_freq": None,
                "close_above_pmh_freq": None,
                "close_below_vwap_freq": None
            }
        
        sub_df = df.loc[target_indices].copy()
        
        has_rth = all(col in sub_df.columns for col in ['rth_open', 'rth_high', 'rth_low', 'rth_close'])
        if has_rth:
            o = sub_df['rth_open']
            h = sub_df['rth_high']
            l = sub_df['rth_low']
            c = sub_df['rth_close']
        else:
            o = sub_df['open']
            h = sub_df['high']
            l = sub_df['low']
            c = sub_df['close']
            
        high_spike = (h - o) / o * 100
        low_spike = (o - l) / o * 100
        rthh_fade = (h - c) / h * 100
        neg_close = (c < o).astype(float) * 100
        
        mid_point = (h + l) / 2.0
        close_below_vwap = (c < mid_point).astype(float) * 100
        
        pm_fade = None
        close_above_pmh = None
        
        if 'pm_high' in sub_df.columns:
            pm_h = sub_df['pm_high']
            pm_fade = (pm_h - o) / pm_h * 100
            pm_fade = pm_fade.mask(pm_h <= 0, None)
            
            close_above_pmh = (c > pm_h).astype(float) * 100
            close_above_pmh = close_above_pmh.mask(pm_h <= 0, None)
            
        return {
            "source": "database" if has_rth else "yfinance",
            "gap_days_count": len(sub_df),
            "high_rth_spike_avg": safe_mean(high_spike),
            "low_rth_spike_avg": safe_mean(low_spike),
            "pm_fade_avg": safe_mean(pm_fade),
            "rthh_fade_avg": safe_mean(rthh_fade),
            "neg_close_freq": safe_mean(neg_close),
            "close_above_pmh_freq": safe_mean(close_above_pmh),
            "close_below_vwap_freq": safe_mean(close_below_vwap)
        }

    return {
        "gap_stats": compute_stats_for_offset(0),
        "gap_stats_plus_1": compute_stats_for_offset(1),
        "gap_stats_plus_2": compute_stats_for_offset(2)
    }

def get_yfinance_session():
    import requests
    import urllib3
    from requests.adapters import HTTPAdapter
    
    class TimeoutHTTPAdapter(HTTPAdapter):
        def __init__(self, *args, **kwargs):
            self.timeout = kwargs.pop('timeout', 5)
            super().__init__(*args, **kwargs)
        def send(self, request, **kwargs):
            kwargs['timeout'] = kwargs.get('timeout', self.timeout)
            return super().send(request, **kwargs)
            
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    
    session = requests.Session()
    session.verify = False
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    })
    
    adapter = TimeoutHTTPAdapter(timeout=5)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session

@router.get("/{ticker}")
def get_ticker_analysis(ticker: str):
    ticker = ticker.upper()
    now = datetime.now()
    
    # Cache lookup
    with _analysis_cache_lock:
        if ticker in _analysis_cache:
            cached_data, expiry = _analysis_cache[ticker]
            if now < expiry:
                print(f"[CACHE] Returning cached ticker analysis for {ticker}")
                return cached_data

    try:
        session = get_yfinance_session()
        stock = yf.Ticker(ticker, session=session)
        info = {}
        try:
            info = stock.info
            if not isinstance(info, dict):
                info = {}
        except Exception as e:
            print(f"[WARN] Failed to fetch yfinance info for {ticker}: {e}")

        # --- Profile ---
        profile = {
            "sector": info.get("sector"),
            "industry": info.get("industry"),
            "website": info.get("website"),
            "description": info.get("longBusinessSummary"),
            "employees": info.get("fullTimeEmployees"),
            "address": info.get("address1"),
            "city": info.get("city"),
            "state": info.get("state"),
            "country": info.get("country"),
            "exchange": info.get("exchange"),
            "name": info.get("longName"),
            "logo_url": f"https://logo.clearbit.com/{info.get('website').replace('https://', '').replace('http://', '').split('/')[0]}" if info.get("website") else None
        }

        # --- Market ---
        market = {
            "market_cap": info.get("marketCap"),
            "shares_outstanding": info.get("sharesOutstanding"),
            "float_shares": info.get("floatShares"),
            "held_percent_institutions": info.get("heldPercentInstitutions"),
            "held_percent_insiders": info.get("heldPercentInsiders"),
            "price": info.get("currentPrice") or info.get("previousClose") # Fallback
        }

        # --- Financials (Snapshot) ---
        financials = {
            "ebitda": info.get("ebitda"),
            "eps": info.get("trailingEps"),
            "enterprise_value": info.get("enterpriseValue"),
            "cash": info.get("totalCash"),
            "total_debt": info.get("totalDebt"),
            "working_capital": None # Loaded via balance-sheet endpoint
        }

        res = {
            "profile": profile,
            "market": market,
            "financials": financials
        }
        with _analysis_cache_lock:
            _analysis_cache[ticker] = (res, now + ANALYSIS_CACHE_TTL)
        return res

    except Exception as e:
        print(f"Error fetching ticker analysis for {ticker}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{ticker}/chart")
def get_ticker_chart(ticker: str):
    ticker = ticker.upper()
    now = datetime.now()
    
    with _chart_cache_lock:
        if ticker in _chart_cache:
            cached_data, expiry = _chart_cache[ticker]
            if now < expiry:
                return cached_data

    try:
        session = get_yfinance_session()
        stock = yf.Ticker(ticker, session=session)
        hist = pd.DataFrame()
        try:
            hist = stock.history(period="5y")
        except Exception as e:
            print(f"[WARN] Failed to fetch yfinance history for {ticker}: {e}")
        
        perf = {}
        daily_history = []
        if not hist.empty:
            current = hist["Close"].iloc[-1]
            def get_ret(days):
                if len(hist) > days:
                    prev = hist["Close"].iloc[-days-1]
                    return ((current - prev) / prev) * 100
                return None
            
            perf["1w"] = get_ret(5)
            perf["1m"] = get_ret(21)
            perf["3m"] = get_ret(63)
            perf["6m"] = get_ret(126)
            perf["1y"] = get_ret(252)
            
            # YTD
            ytd_start = hist[hist.index.year == datetime.now().year]
            if not ytd_start.empty:
                start_price = ytd_start["Close"].iloc[0]
                perf["ytd"] = ((current - start_price) / start_price) * 100
            else:
                 perf["ytd"] = None

            # Extract daily history for chart
            try:
                hist_reset = hist.reset_index()
                date_col = 'Date' if 'Date' in hist_reset.columns else hist_reset.columns[0]
                for _, r in hist_reset.iterrows():
                    dt = r[date_col]
                    if hasattr(dt, 'strftime'):
                        date_str = dt.strftime('%Y-%m-%d')
                    else:
                        date_str = str(dt)[:10]
                    
                    daily_history.append({
                        "time": date_str,
                        "open": safe_float(r.get('Open')),
                        "high": safe_float(r.get('High')),
                        "low": safe_float(r.get('Low')),
                        "close": safe_float(r.get('Close')),
                        "volume": safe_float(r.get('Volume'))
                    })
            except Exception as e:
                print(f"Error extracting daily history for {ticker}: {e}")

        res = {
            "daily_history": daily_history,
            "performance": perf
        }
        with _chart_cache_lock:
            _chart_cache[ticker] = (res, now + CHART_CACHE_TTL)
        return res
    except Exception as e:
        print(f"Error fetching chart for {ticker}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{ticker}/balance-sheet")
def get_ticker_balance_sheet(ticker: str):
    ticker = ticker.upper()
    now = datetime.now()
    
    with _balance_sheet_cache_lock:
        if ticker in _balance_sheet_cache:
            cached_data, expiry = _balance_sheet_cache[ticker]
            if now < expiry:
                return cached_data

    try:
        session = get_yfinance_session()
        stock = yf.Ticker(ticker, session=session)
        bs = pd.DataFrame()
        try:
            bs = stock.quarterly_balance_sheet
        except Exception as e:
            print(f"[WARN] Failed to fetch yfinance quarterly balance sheet for {ticker}: {e}")
        charts = {
            "cash_history": [],
            "debt_history": [],
            "working_capital_history": []
        }
        working_capital = None

        if not bs.empty:
            bs_T = bs.T.sort_index()
            
            def get_series(key_pattern):
                col = next((c for c in bs_T.columns if key_pattern in str(c).lower()), None)
                if col:
                    return [{"date": str(d.date()), "value": safe_float(v)} for d, v in bs_T[col].items()]
                return []

            charts["cash_history"] = get_series("cash")
            charts["debt_history"] = get_series("debt")
            
            if "Total Current Assets" in bs_T.columns and "Total Current Liabilities" in bs_T.columns:
                wc = bs_T["Total Current Assets"] - bs_T["Total Current Liabilities"]
                charts["working_capital_history"] = [{"date": str(d.date()), "value": safe_float(v)} for d, v in wc.items()]
            elif "Working Capital" in bs_T.columns:
                charts["working_capital_history"] = get_series("working capital")

            if charts["working_capital_history"]:
                 working_capital = charts["working_capital_history"][-1]["value"]

        res = {
            "charts": charts,
            "working_capital": working_capital
        }
        with _balance_sheet_cache_lock:
            _balance_sheet_cache[ticker] = (res, now + BALANCE_SHEET_CACHE_TTL)
        return res
    except Exception as e:
        print(f"Error fetching balance sheet for {ticker}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{ticker}/gap-stats")
def get_ticker_gap_stats(ticker: str):
    ticker = ticker.upper()
    now = datetime.now()
    
    with _gap_stats_cache_lock:
        if ticker in _gap_stats_cache:
            cached_data, expiry = _gap_stats_cache[ticker]
            if now < expiry:
                return cached_data

    try:
        know_the_float = scrape_knowthefloat(ticker)
        all_stats = get_gap_stats_all_days(ticker)

        res = {
            "know_the_float": know_the_float,
            "gap_stats": all_stats["gap_stats"],
            "gap_stats_plus_1": all_stats["gap_stats_plus_1"],
            "gap_stats_plus_2": all_stats["gap_stats_plus_2"]
        }
        with _gap_stats_cache_lock:
            _gap_stats_cache[ticker] = (res, now + GAP_STATS_CACHE_TTL)
        return res
    except Exception as e:
        print(f"Error fetching gap stats for {ticker}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{ticker}/sec-filings")
def get_sec_filings(ticker: str):
    """
    Fetches latest filings from SEC EDGAR RSS feed.
    No API key required.
    """
    ticker = ticker.upper()
    now = datetime.now()
    with _filings_cache_lock:
        if ticker in _filings_cache:
            cached_data, expiry = _filings_cache[ticker]
            if now < expiry:
                print(f"[CACHE] Returning cached SEC filings for {ticker}")
                return cached_data

    try:
        # SEC RSS Feed URL pattern
        # CIKS are usually mapped, but searching by Ticker works on this endpoint often, 
        # or we might need to lookup CIK from yfinance info if ticker lookup fails.
        # Let's try direct ticker first. 
        # Updated RSS link format: https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={ticker}&type=&dateb=&owner=exclude&start=0&count=40&output=atom
        
        rss_url = f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={ticker}&type=&dateb=&owner=exclude&start=0&count=40&output=atom"
        
        # User-Agent is required by SEC
        # Using requests to handle SSL/User-Agent better than feedparser's internal urllib
        import requests
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        headers = {'User-Agent': 'MyStrategyBuilder/1.0 (contact@mystrategybuilder.fun)'}
        response = requests.get(rss_url, headers=headers, verify=False, timeout=5)
        
        feed = feedparser.parse(response.content)

        filings = {
            "financials": [],   # 10-K, 10-Q
            "prospectuses": [], # 424B
            "news": [],         # 8-K
            "ownership": [],    # SC 13G, SC 13D, Forms 3, 4, 5
            "proxies": [],      # DEF 14A
            "others": []
        }

        for entry in feed.entries:
            # Entry title usually format: "8-K - Current report filling" or "10-Q"
            # Category term usually has the form type
            form_type = entry.get('term', 'Unknown').upper()
            if not form_type or form_type == 'UNKNOWN':
                 # Fallback to parsing title
                 form_type = entry.title.split('-')[0].strip().upper()

            item = {
                "type": form_type,
                "title": entry.title,
                "date": entry.updated.split('T')[0], # 2023-10-27T...
                "link": entry.link
            }

            if form_type in ['10-K', '10-Q', '20-F', '40-F']:
                filings["financials"].append(item)
            elif '424B' in form_type or 'S-1' in form_type or 'F-1' in form_type:
                filings["prospectuses"].append(item)
            elif '8-K' in form_type or '6-K' in form_type:
                filings["news"].append(item)
            elif '13G' in form_type or '13D' in form_type or form_type in ['3', '4', '5']:
                filings["ownership"].append(item)
            elif '14A' in form_type:
                filings["proxies"].append(item)
            else:
                filings["others"].append(item)

        with _filings_cache_lock:
            _filings_cache[ticker] = (filings, now + FILINGS_CACHE_TTL)
        return filings

    except Exception as e:
        print(f"Error fetching SEC filings for {ticker}: {e}")
        # Return empty structure rather than 500 to not break entire dashboard
        return {k: [] for k in ["financials", "prospectuses", "news", "ownership", "proxies", "others"]}
