from fastapi import APIRouter, HTTPException
import feedparser
from pydantic import BaseModel
from typing import List
import asyncio
from datetime import datetime
import time

router = APIRouter()

class NewsItem(BaseModel):
    title: str
    link: str
    published: str
    source: str
    summary: str

# RSS Feeds targeting Small Caps / Market News
RSS_FEEDS = [
    {
        "url": "https://finance.yahoo.com/news/rssindex",
        "source": "Yahoo Finance"
    },
    {
        "url": "https://www.investing.com/rss/news_25.rss", # Stock Market News
        "source": "Investing.com"
    },
     {
        "url": "https://feeds.content.dowjones.com/public/rss/mw_topstories",
        "source": "MarketWatch"
    }
]

async def fetch_feed(feed_url, source_name):
    try:
        # Run feedparser in a thread pool since it's blocking IO
        # Add timeout to prevent hanging the whole news feed
        feed = await asyncio.wait_for(
            asyncio.to_thread(feedparser.parse, feed_url),
            timeout=3.0
        )
        news_items = []
        if not hasattr(feed, 'entries'):
            return []
            
        for entry in feed.entries[:5]: # Get top 5 from each
            summary = entry.get('summary', '') or entry.get('description', '')
            published = entry.get('published', '') or entry.get('updated', datetime.now().strftime("%a, %d %b %Y %H:%M:%S GMT"))

            news_items.append(NewsItem(
                title=entry.title,
                link=entry.link,
                published=published,
                source=source_name,
                summary=summary
            ))
        return news_items
    except asyncio.TimeoutError:
        print(f"Timeout fetching feed {feed_url}")
        return []
    except Exception as e:
        print(f"Error fetching feed {feed_url}: {e}")
        return []

@router.get("/market/news", response_model=List[NewsItem])
async def get_market_news():
    tasks = [fetch_feed(feed['url'], feed['source']) for feed in RSS_FEEDS]
    results = await asyncio.gather(*tasks)
    
    # Flatten list
    all_news = [item for sublist in results for item in sublist]
    
    # Sort by date ? (Parsing dates from varied RSS is tricky, might just shuffle or interleave)
    # For now, let's just return them. 
    # Attempt simple sort if 'published' is standard, but RSS dates vary wildly.
    # Let's just limit to reasonable amount
    return all_news[:15]
