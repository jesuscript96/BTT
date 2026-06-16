import requests
from bs4 import BeautifulSoup
import urllib3
import re

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def parse_finviz_number(val: str):
    if not val or val == '-':
        return None
    val = val.strip().upper()
    multiplier = 1.0
    if val.endswith('K'):
        multiplier = 1e3
        val = val[:-1]
    elif val.endswith('M'):
        multiplier = 1e6
        val = val[:-1]
    elif val.endswith('B'):
        multiplier = 1e9
        val = val[:-1]
    elif val.endswith('T'):
        multiplier = 1e12
        val = val[:-1]
    try:
        return float(val) * multiplier
    except ValueError:
        return None

def test_scrape(ticker):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    url = f"https://finviz.com/quote.ashx?t={ticker}"
    print(f"Fetching {url}...")
    r = requests.get(url, headers=headers, verify=False, timeout=10)
    if r.status_code != 200:
        return None
        
    soup = BeautifulSoup(r.text, 'html.parser')
    snapshot_table = soup.find('table', class_=re.compile(r'snapshot-table|table-snapshot|snapshot'))
    if not snapshot_table:
        tables = soup.find_all('table')
        for idx, t in enumerate(tables):
            txt = t.text
            if "Shs Outstand" in txt or "Market Cap" in txt:
                snapshot_table = t
                break
                
    if not snapshot_table:
        return None
        
    tds = snapshot_table.find_all('td')
    data = {}
    for i in range(len(tds) - 1):
        label = tds[i].text.strip()
        val = tds[i+1].text.strip()
        if label in ["Market Cap", "Shs Outstand", "Shs Float"]:
            data[label] = parse_finviz_number(val)
            
    print("Extracted numeric data:", data)
    return data

if __name__ == "__main__":
    test_scrape("SOAR")
