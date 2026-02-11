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

@router.get("/{ticker}")
def get_ticker_analysis(ticker: str):
    try:
        ticker = ticker.upper()
        stock = yf.Ticker(ticker)
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


        return {
            "profile": profile,
            "market": market,
            "financials": financials,
            "performance": perf,
            "charts": charts
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
        headers = {'User-Agent': 'MyStrategyBuilder/1.0 (contact@mystrategybuilder.fun)'}
        response = requests.get(rss_url, headers=headers)
        
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
