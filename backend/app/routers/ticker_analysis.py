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
        r = requests.get(url, headers=headers, verify=False, timeout=5)
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

def get_gap_stats(ticker: str, daily_history: list[dict]) -> dict:
    ticker = ticker.upper()
    
    # 1. Try GCS hot cache in memory
    try:
        from app.services.cache_service import get_hot_daily_cache
        df_hot = get_hot_daily_cache()
        if df_hot is not None and not df_hot.empty:
            ticker_gcs = df_hot[df_hot['ticker'] == ticker]
            if not ticker_gcs.empty:
                high_spike = ticker_gcs['rth_run_pct']
                low_spike = (ticker_gcs['rth_open'] - ticker_gcs['rth_low']) / ticker_gcs['rth_open'] * 100
                pm_fade = (ticker_gcs['pm_high'] - ticker_gcs['rth_open']) / ticker_gcs['pm_high'] * 100
                rthh_fade = (ticker_gcs['rth_high'] - ticker_gcs['rth_close']) / ticker_gcs['rth_high'] * 100
                
                neg_close = (ticker_gcs['rth_close'] < ticker_gcs['prev_close']).astype(float) * 100
                close_above_pmh = (ticker_gcs['rth_close'] > ticker_gcs['pm_high']).astype(float) * 100
                
                mid_point = (ticker_gcs['rth_high'] + ticker_gcs['rth_low']) / 2.0
                close_below_vwap = (ticker_gcs['rth_close'] < mid_point).astype(float) * 100
                
                return {
                    "source": "database_hot_cache",
                    "gap_days_count": len(ticker_gcs),
                    "high_rth_spike_avg": safe_mean(high_spike),
                    "low_rth_spike_avg": safe_mean(low_spike),
                    "pm_fade_avg": safe_mean(pm_fade),
                    "rthh_fade_avg": safe_mean(rthh_fade),
                    "neg_close_freq": safe_mean(neg_close),
                    "close_above_pmh_freq": safe_mean(close_above_pmh),
                    "close_below_vwap_freq": safe_mean(close_below_vwap)
                }
    except Exception as e:
        print(f"Error calculating stats from hot cache: {e}")
        
    # 2. Fallback to daily_history (1y from yfinance)
    if daily_history:
        try:
            df = pd.DataFrame(daily_history)
            if not df.empty and 'close' in df.columns:
                df['prev_close'] = df['close'].shift(1)
                df['gap_pct'] = (df['open'] - df['prev_close']) / df['prev_close'] * 100
                
                # Filter for gap days (abs(gap) >= 2.0%)
                gap_yf = df[df['gap_pct'].abs() >= 2.0].copy()
                if not gap_yf.empty:
                    high_spike = (gap_yf['high'] - gap_yf['open']) / gap_yf['open'] * 100
                    low_spike = (gap_yf['open'] - gap_yf['low']) / gap_yf['open'] * 100
                    rthh_fade = (gap_yf['high'] - gap_yf['close']) / gap_yf['high'] * 100
                    
                    neg_close = (gap_yf['close'] < gap_yf['prev_close']).astype(float) * 100
                    
                    mid_point = (gap_yf['high'] + gap_yf['low']) / 2.0
                    close_below_vwap = (gap_yf['close'] < mid_point).astype(float) * 100
                    
                    return {
                        "source": "yfinance_1y_history",
                        "gap_days_count": len(gap_yf),
                        "high_rth_spike_avg": safe_mean(high_spike),
                        "low_rth_spike_avg": safe_mean(low_spike),
                        "pm_fade_avg": None,
                        "rthh_fade_avg": safe_mean(rthh_fade),
                        "neg_close_freq": safe_mean(neg_close),
                        "close_above_pmh_freq": None,
                        "close_below_vwap_freq": safe_mean(close_below_vwap)
                    }
        except Exception as e:
            print(f"Error calculating stats from daily_history: {e}")
            
    return {
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

@router.get("/{ticker}")
def get_ticker_analysis(ticker: str):
    try:
        ticker = ticker.upper()
        import requests
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        
        session = requests.Session()
        session.verify = False
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        })
        
        stock = yf.Ticker(ticker, session=session)
        info = stock.info

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
            "working_capital": None # Calculated below if possible, or from balance sheet
        }

        # --- Performance ---
        # Note: yfinance info often has 52WeekChange, but specific periods might need history
        # Let's fetch 1y history to calculate exact performance
        hist = stock.history(period="1y")
        
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

        # --- Charts (Sparklines from Balance Sheet) ---
        # yfinance balance sheet is annual or quarterly. Let's get quarterly for more points.
        bs = stock.quarterly_balance_sheet
        charts = {
            "cash_history": [],
            "debt_history": [],
            "working_capital_history": []
        }

        if not bs.empty:
            # Transpose to have dates as index
            bs_T = bs.T.sort_index()
            
            # Helper to extract series
            def get_series(key_pattern):
                # Try exact match or contains
                col = next((c for c in bs_T.columns if key_pattern in str(c).lower()), None)
                if col:
                    return [{"date": str(d.date()), "value": safe_float(v)} for d, v in bs_T[col].items()]
                return []

            charts["cash_history"] = get_series("cash") # "CashAndCashEquivalents" usually
            charts["debt_history"] = get_series("debt") # "TotalDebt"
            
            # Working Capital = Current Assets - Current Liabilities
            if "Total Current Assets" in bs_T.columns and "Total Current Liabilities" in bs_T.columns:
                wc = bs_T["Total Current Assets"] - bs_T["Total Current Liabilities"]
                charts["working_capital_history"] = [{"date": str(d.date()), "value": safe_float(v)} for d, v in wc.items()]
            elif "Working Capital" in bs_T.columns:
                charts["working_capital_history"] = get_series("working capital")

        # Refine Financials if info was missing
        if financials["working_capital"] is None and charts["working_capital_history"]:
             financials["working_capital"] = charts["working_capital_history"][-1]["value"]

        # --- Scrape KnowTheFloat ---
        know_the_float = scrape_knowthefloat(ticker)

        # --- Gap Day Statistics ---
        gap_stats = get_gap_stats(ticker, daily_history)

        return {
            "profile": profile,
            "market": market,
            "financials": financials,
            "performance": perf,
            "charts": charts,
            "daily_history": daily_history,
            "know_the_float": know_the_float,
            "gap_stats": gap_stats
        }

    except Exception as e:
        print(f"Error fetching ticker analysis for {ticker}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{ticker}/sec-filings")
def get_sec_filings(ticker: str):
    """
    Fetches latest filings from SEC EDGAR RSS feed.
    No API key required.
    """
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
        response = requests.get(rss_url, headers=headers, verify=False)
        
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

        return filings

    except Exception as e:
        print(f"Error fetching SEC filings for {ticker}: {e}")
        # Return empty structure rather than 500 to not break entire dashboard
        return {k: [] for k in ["financials", "prospectuses", "news", "ownership", "proxies", "others"]}
