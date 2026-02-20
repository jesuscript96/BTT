import React, { useEffect, useState } from 'react';
import { API_URL } from '@/config/constants';
import { Newspaper, ExternalLink, Clock } from 'lucide-react';

interface NewsItem {
    title: string;
    link: string;
    published: string;
    source: string;
    summary: string;
}

export const NewsFeed: React.FC = () => {
    const [news, setNews] = useState<NewsItem[]>([]);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        const fetchNews = async () => {
            try {
                const res = await fetch(`${API_URL}/market/news`);
                if (res.ok) {
                    const data = await res.json();
                    setNews(data);
                }
            } catch (err) {
                console.error("Failed to fetch news", err);
            } finally {
                setLoading(false);
            }
        };

        fetchNews();
    }, []);

    if (loading) {
        return (
            <div className="h-full w-full flex items-center justify-center">
                <div className="flex flex-col items-center gap-3 animate-pulse">
                    <Newspaper className="w-8 h-8 text-muted-foreground/50" />
                    <span className="text-xs font-bold uppercase tracking-widest text-muted-foreground/50">Loading Market Intel...</span>
                </div>
            </div>
        );
    }

    return (
        <div className="h-full w-full overflow-y-auto pr-2 custom-scrollbar">
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 pb-20">
                {news.map((item, idx) => (
                    <a
                        key={idx}
                        href={item.link}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="group flex flex-col justify-between p-5 bg-background border border-border/40 hover:border-blue-500/50 transition-all duration-300 hover:bg-muted/5 rounded-sm relative overflow-hidden"
                    >
                        <div className="absolute top-0 left-0 w-0.5 h-full bg-blue-500 opacity-0 group-hover:opacity-100 transition-opacity" />

                        <div className="flex flex-col gap-3">
                            <div className="flex items-center justify-between">
                                <span className="text-[10px] font-black uppercase tracking-widest text-blue-500">{item.source}</span>
                                <ExternalLink className="w-3 h-3 text-muted-foreground opacity-0 group-hover:opacity-100 transition-opacity" />
                            </div>

                            <h3 className="text-sm font-bold text-foreground leading-snug group-hover:text-blue-500 transition-colors line-clamp-2">
                                {item.title}
                            </h3>

                            <p className="text-xs text-muted-foreground line-clamp-3 leading-relaxed">
                                {item.summary.replace(/<[^>]*>?/gm, '')}
                            </p>
                        </div>

                        <div className="mt-4 pt-3 border-t border-border/20 flex items-center gap-2">
                            <Clock className="w-3 h-3 text-muted-foreground" />
                            <span className="text-[10px] text-muted-foreground font-medium truncate">
                                {new Date(item.published).toLocaleString()}
                            </span>
                        </div>
                    </a>
                ))}
            </div>

            {news.length === 0 && (
                <div className="flex h-full items-center justify-center text-muted-foreground text-xs">
                    No news available at the moment.
                </div>
            )}
        </div>
    );
};
