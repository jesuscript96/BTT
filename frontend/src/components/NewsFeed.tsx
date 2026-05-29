import React, { useEffect, useState } from 'react';
import { getMarketNews } from '@/lib/api';
import { Newspaper, ExternalLink, Clock } from 'lucide-react';

interface NewsItem {
    title: string;
    link: string;
    published: string;
    source: string;
    summary: string;
}

const CARD_STYLE: React.CSSProperties = {
    background: 'var(--color-ec-bg-surface)',
    border: '0.5px solid var(--color-ec-border)',
    borderRadius: 7,
    padding: '16px 18px',
    transition: 'background 150ms ease',
    display: 'flex',
    flexDirection: 'column',
    gap: 10,
};

const SOURCE_STYLE: React.CSSProperties = {
    fontFamily: "'General Sans', sans-serif",
    fontSize: 9,
    fontWeight: 700,
    textTransform: 'uppercase',
    letterSpacing: '2.5px',
    color: 'var(--color-ec-copper)',
};

const TITLE_STYLE: React.CSSProperties = {
    fontFamily: "'Fraunces', serif",
    fontSize: 17,
    fontWeight: 500,
    color: 'var(--color-ec-text-high)',
    lineHeight: 1.4,
};

const META_STYLE: React.CSSProperties = {
    fontFamily: "'General Sans', sans-serif",
    fontSize: 10,
    fontWeight: 500,
    color: 'var(--color-ec-text-muted)',
    display: 'flex',
    alignItems: 'center',
    gap: 5,
};

const CARD_HOVER: React.CSSProperties = {
    background: 'var(--color-ec-bg-elevated)',
};

export const NewsFeed: React.FC = () => {
    const [news, setNews] = useState<NewsItem[]>([]);
    const [loading, setLoading] = useState(true);
    const [hoverIdx, setHoverIdx] = useState<number | null>(null);

    useEffect(() => {
        const fetchNews = async () => {
            try {
                const data = await getMarketNews();
                setNews(data as NewsItem[]);
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
                    <Newspaper className="w-8 h-8 text-[var(--color-ec-text-muted)]" style={{ opacity: 0.5 }} />
                    <span className="text-xs font-bold uppercase tracking-widest text-[var(--color-ec-text-muted)]" style={{ opacity: 0.5 }}>
                        Loading Market Intel...
                    </span>
                </div>
            </div>
        );
    }

    return (
        <div className="h-full w-full overflow-y-auto pr-2 custom-scrollbar">
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12, padding: 20 }}>
                {news.map((item, idx) => (
                    <a
                        key={idx}
                        href={item.link}
                        target="_blank"
                        rel="noopener noreferrer"
                        style={{
                            ...CARD_STYLE,
                            ...(hoverIdx === idx ? CARD_HOVER : {}),
                            textDecoration: 'none',
                        }}
                        onMouseEnter={() => setHoverIdx(idx)}
                        onMouseLeave={() => setHoverIdx(null)}
                    >
                        <span style={SOURCE_STYLE}>
                            {item.source}
                        </span>

                        <h3 style={{
                            ...TITLE_STYLE,
                            overflow: 'hidden',
                            display: '-webkit-box',
                            WebkitLineClamp: 2,
                            WebkitBoxOrient: 'vertical',
                        }}>
                            {item.title}
                        </h3>

                        <p style={{
                            fontFamily: "'General Sans', sans-serif",
                            fontSize: 13,
                            fontWeight: 400,
                            color: 'var(--color-ec-text-primary)',
                            lineHeight: 1.5,
                            overflow: 'hidden',
                            display: '-webkit-box',
                            WebkitLineClamp: 3,
                            WebkitBoxOrient: 'vertical',
                        }}>
                            {item.summary.replace(/<[^>]*>?/gm, '')}
                        </p>

                        <div style={META_STYLE}>
                            <Clock size={13} color="var(--color-ec-text-muted)" />
                            <span>{new Date(item.published).toLocaleString()}</span>
                        </div>
                    </a>
                ))}
            </div>

            {news.length === 0 && (
                <div className="flex h-full items-center justify-center text-[var(--color-ec-text-muted)] text-xs">
                    No news available at the moment.
                </div>
            )}
        </div>
    );
};
