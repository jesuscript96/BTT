import feedparser
import sys
import requests

ticker = "AAPL"
if len(sys.argv) > 1:
    ticker = sys.argv[1]

rss_url = f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={ticker}&type=&dateb=&owner=exclude&start=0&count=40&output=atom"
print(f"Fetching with requests: {rss_url}")

headers = {'User-Agent': 'MyStrategyBuilder/1.0 (contact@mystrategybuilder.fun)'}

try:
    response = requests.get(rss_url, headers=headers)
    print(f"Requests Status: {response.status_code}")
    
    d = feedparser.parse(response.content)

    print(f"Entries found: {len(d.entries)}")

    if d.entries:
        print("First entry title:", d.entries[0].title)
    else:
        print("No entries found.")
except Exception as e:
    print(f"Requests failed: {e}")
