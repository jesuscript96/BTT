"use client";

import React, { useState, useEffect, useRef } from 'react';
import {
    Send, X, Settings, RotateCcw, MessageSquareCode, AlertCircle, Paperclip, FileText, Check
} from 'lucide-react';

interface ChatMessage {
    role: 'user' | 'assistant' | 'system';
    content: string;
}

interface AttachedFile {
    name: string;
    content: string;
}

// Utility to format large financial numbers into readable strings
const formatValue = (num: number | null | undefined, isCurrency = true) => {
    if (num === null || num === undefined) return 'N/A';
    const isNeg = num < 0;
    const absNum = Math.abs(num);
    let formatted = '';
    
    if (absNum >= 1e9) formatted = `${(absNum / 1e9).toFixed(2)} B`;
    else if (absNum >= 1e6) formatted = `${(absNum / 1e6).toFixed(2)} M`;
    else if (absNum >= 1e3) formatted = `${(absNum / 1e3).toFixed(2)} K`;
    else formatted = absNum.toFixed(2);
    
    const prefix = isCurrency ? '$ ' : '';
    return isNeg ? `-${prefix}${formatted}` : `${prefix}${formatted}`;
};

// Custom Robot SVG Avatar Component
const RobotAvatar = ({ size = 32, glowing = false }) => (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
        <rect x="6" y="9" width="20" height="15" rx="3.5" fill="#1C1E21" stroke={glowing ? "var(--color-ec-copper-bright)" : "var(--color-ec-border)"} strokeWidth="1.5"/>
        <rect x="3" y="14" width="3" height="5" rx="1.5" fill="#2C2F33" stroke={glowing ? "var(--color-ec-copper)" : "var(--color-ec-border)"} strokeWidth="1"/>
        <rect x="26" y="14" width="3" height="5" rx="1.5" fill="#2C2F33" stroke={glowing ? "var(--color-ec-copper)" : "var(--color-ec-border)"} strokeWidth="1"/>
        <path d="M16 9V5M16 5C17.1046 5 18 4.10457 18 3C18 1.89543 17.1046 1 16 1C14.8954 1 14 1.89543 14 3C14 4.10457 14.8954 5 16 5Z" fill="var(--color-ec-copper)"/>
        {/* Pulsating Eyes */}
        <circle cx="11" cy="15" r="2.5" fill={glowing ? "var(--color-ec-copper-bright)" : "var(--color-ec-text-muted)"} style={{ animation: glowing ? 'edge-eye-pulse 1.5s infinite alternate' : 'none' }}/>
        <circle cx="21" cy="15" r="2.5" fill={glowing ? "var(--color-ec-copper-bright)" : "var(--color-ec-text-muted)"} style={{ animation: glowing ? 'edge-eye-pulse 1.5s infinite alternate' : 'none' }}/>
        {/* LED Grid Mouth */}
        <rect x="11" y="19" width="10" height="2" rx="1" fill="#2C2F33" stroke={glowing ? "var(--color-ec-copper)" : "var(--color-ec-border)"} strokeWidth="0.5"/>
    </svg>
);

export function ChatBot() {
    const [isOpen, setIsOpen] = useState(false);
    const [showSettings, setShowSettings] = useState(false);
    const [apiKey, setApiKey] = useState('');
    const [input, setInput] = useState('');
    const [isGenerating, setIsGenerating] = useState(false);
    const [activeTicker, setActiveTicker] = useState<string | null>(null);
    const [tickerData, setTickerData] = useState<any | null>(null);
    const [attachedFile, setAttachedFile] = useState<AttachedFile | null>(null);
    
    const [messages, setMessages] = useState<ChatMessage[]>([]);

    const messagesEndRef = useRef<HTMLDivElement>(null);
    const fileInputRef = useRef<HTMLInputElement>(null);

    // Initial conversation message
    const initWelcomeMessage = (tickerName: string | null) => {
        const welcomeText = tickerName 
            ? `Hola, soy **Edgie**, tu asistente robótico de trading en Edgecute. He cargado la base de conocimiento para **${tickerName}** (perfil, métricas, gap stats, SEC filings y noticias). También puedes arrastrar o adjuntar archivos (CSV, TXT, JSON) usando el icono de clip. ¿Qué deseas analizar hoy?`
            : "Hola, soy **Edgie**, tu asistente robótico de trading en Edgecute. Estoy listo para ayudarte a analizar datos financieros, interpretar filings de la SEC o simular estrategias. Carga un ticker en **Ticker Analysis** o adjunta un archivo local (`.txt`, `.csv`, `.json`) con el clip para empezar. ¿Qué analizamos hoy?";
        
        setMessages([
            { role: 'assistant', content: welcomeText }
        ]);
    };

    // Load API key and check for cached ticker on mount
    useEffect(() => {
        if (typeof window !== 'undefined') {
            const savedKey = localStorage.getItem('DEEPSEEK_API_KEY') || '';
            setApiKey(savedKey);

            // Initialize active ticker if already loaded
            const lastTicker = (window as any).__lastLoadedTicker;
            if (lastTicker) {
                setActiveTicker(lastTicker.ticker);
                setTickerData(lastTicker);
                initWelcomeMessage(lastTicker.ticker);
            } else {
                initWelcomeMessage(null);
            }
        }
    }, []);

    // Listen for ticker-loaded custom window events
    useEffect(() => {
        const handleTickerLoaded = (e: Event) => {
            const customEvent = e as CustomEvent;
            const payload = customEvent.detail;
            if (payload && payload.ticker) {
                setActiveTicker(payload.ticker);
                setTickerData(payload);
                
                // Add a system notification in the chat
                setMessages(prev => [
                    ...prev,
                    { 
                        role: 'system', 
                        content: `Edgie ha cargado exitosamente la base de conocimiento de **${payload.ticker}**.` 
                    }
                ]);
            }
        };

        window.addEventListener('ticker-loaded', handleTickerLoaded);
        return () => window.removeEventListener('ticker-loaded', handleTickerLoaded);
    }, []);

    // Scroll to bottom when messages list updates
    useEffect(() => {
        messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }, [messages, isGenerating]);

    const handleSaveApiKey = (e: React.FormEvent) => {
        e.preventDefault();
        if (typeof window !== 'undefined') {
            localStorage.setItem('DEEPSEEK_API_KEY', apiKey.trim());
            setShowSettings(false);
            
            setMessages(prev => [
                ...prev,
                { role: 'system', content: "Clave API de DeepSeek guardada. Edgie está en línea." }
            ]);
        }
    };

    const handleResetChat = () => {
        setAttachedFile(null);
        initWelcomeMessage(activeTicker);
    };

    // FileReader handle for user attachments (text files, logs, CSVs, JSONs)
    const handleFileClick = () => {
        fileInputRef.current?.click();
    };

    const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
        const file = e.target.files?.[0];
        if (!file) return;

        const reader = new FileReader();
        reader.onload = (event) => {
            const text = event.target?.result as string;
            setAttachedFile({
                name: file.name,
                content: text
            });

            setMessages(prev => [
                ...prev,
                { 
                    role: 'system', 
                    content: `Archivo adjunto **${file.name}** (${(file.size / 1024).toFixed(1)} KB) cargado en la memoria de Edgie.` 
                }
            ]);
        };
        reader.readAsText(file);
        // Clear input value so same file can be uploaded again
        e.target.value = '';
    };

    // Custom formatter for basic markdown rendering (bolds, paragraphs, lists)
    const renderBoldText = (text: string) => {
        const parts = text.split('**');
        return parts.map((part, index) => {
            if (index % 2 === 1) {
                return <strong key={index} style={{ color: 'var(--color-ec-text-high)', fontWeight: 600 }}>{part}</strong>;
            }
            return part;
        });
    };

    const renderMessageContent = (content: string) => {
        // Strip out file content attachments block from showing in user bubbles to keep chat clean
        let displayContent = content;
        if (content.startsWith('[Archivo adjunto:')) {
            const lines = content.split('\n');
            const fileHeader = lines[0];
            const queryLines = lines.filter(l => !l.startsWith('`') && l !== fileHeader && !displayContent.includes(l));
            displayContent = `${fileHeader}\n\n${queryLines.join('\n').trim()}`;
        }

        return displayContent.split('\n').map((line, idx) => {
            if (line.startsWith('### ')) {
                return <h4 key={idx} style={{ color: 'var(--color-ec-copper-bright)', fontSize: 13, fontWeight: 700, margin: '10px 0 4px 0', fontFamily: 'var(--font-sans)' }}>{line.replace('### ', '')}</h4>;
            }
            if (line.startsWith('## ')) {
                return <h3 key={idx} style={{ color: 'var(--color-ec-copper-bright)', fontSize: 14, fontWeight: 700, margin: '14px 0 6px 0', fontFamily: 'var(--font-sans)' }}>{line.replace('## ', '')}</h3>;
            }
            if (line.startsWith('- ') || line.startsWith('* ')) {
                const text = line.substring(2);
                return (
                    <ul key={idx} style={{ margin: '3px 0 3px 14px', paddingLeft: 0, listStyleType: 'disc' }}>
                        <li style={{ fontSize: 12, color: 'var(--color-ec-text-primary)', lineHeight: 1.4 }}>{renderBoldText(text)}</li>
                    </ul>
                );
            }
            if (line.trim() === '') {
                return <div key={idx} style={{ height: '6px' }} />;
            }
            return <p key={idx} style={{ fontSize: 12, color: 'var(--color-ec-text-primary)', lineHeight: 1.4, margin: '4px 0' }}>{renderBoldText(line)}</p>;
        });
    };

    const handleSend = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!input.trim() || isGenerating) return;

        const userText = input.trim();
        setInput('');

        // Prepare query content (append attached file if present)
        let queryContent = userText;
        if (attachedFile) {
            queryContent = `[Archivo adjunto: "${attachedFile.name}"]\n\`\`\`\n${attachedFile.content}\n\`\`\`\n\n${userText}`;
            setAttachedFile(null); // Clear attachment reference
        }

        // 1. Add user message to state
        const newMessages = [...messages, { role: 'user', content: queryContent } as ChatMessage];
        setMessages(newMessages);

        // 2. Check for API key (BYO key only — stored in localStorage; no public env fallback)
        const currentKey = apiKey.trim();
        if (!currentKey) {
            setMessages(prev => [
                ...prev,
                { 
                    role: 'system', 
                    content: "Error: No se ha configurado la API Key de DeepSeek. Haz clic en el icono del engranaje en la parte superior para añadir tu clave de DeepSeek y activar a Edgie." 
                }
            ]);
            return;
        }

        setIsGenerating(true);

        try {
            // 3. Build system prompt using active ticker knowledge base
            let systemPrompt = 
                "You are Edgie, an advanced autonomous financial analysis robot and trading assistant integrated into the Edgecute platform.\n" +
                "Your role is to help professional traders evaluate market data, inspect gap statistics, interpret balance sheets, scan SEC filings, and summarize news.\n" +
                "Be analytical, precise, and structured. Avoid boilerplate trading disclaimers unless strictly necessary, and focus on delivering high-fidelity quantitative analysis.\n" +
                "Always respond in Spanish, matching the language the user speaks. Use clean Markdown formatting.";

            if (activeTicker && tickerData) {
                const profile = tickerData.data?.profile || {};
                const market = tickerData.data?.market || {};
                const financials = tickerData.data?.financials || {};
                const gapStats = tickerData.data?.gap_stats || {};
                const gapStats1 = tickerData.data?.gap_stats_plus_1 || {};
                const gapStats2 = tickerData.data?.gap_stats_plus_2 || {};
                const filings = tickerData.filings || {};
                const news = tickerData.finvizNews || [];

                systemPrompt += `\n\nYou are currently analyzing ticker: **${activeTicker.toUpperCase()}**.`;
                systemPrompt += `\nHere is the loaded knowledge base for ${activeTicker.toUpperCase()} retrieved from the application:`;

                systemPrompt += `\n\n### Company Profile`;
                systemPrompt += `\n- Name: ${profile.name || 'N/A'}`;
                systemPrompt += `\n- Sector/Industry: ${profile.sector || 'N/A'} / ${profile.industry || 'N/A'}`;
                if (profile.description) {
                    systemPrompt += `\n- Description: ${profile.description.substring(0, 350)}...`;
                }

                systemPrompt += `\n\n### Market Metrics`;
                systemPrompt += `\n- Price: $${market.price || 'N/A'}`;
                systemPrompt += `\n- Market Cap: ${formatValue(market.market_cap)}`;
                systemPrompt += `\n- Float Shares: ${formatValue(market.float_shares, false)}`;
                systemPrompt += `\n- Shares Outstanding: ${formatValue(market.shares_outstanding, false)}`;
                if (market.held_percent_insiders !== undefined && market.held_percent_insiders !== null) {
                    systemPrompt += `\n- Insider Ownership: ${(market.held_percent_insiders * 100).toFixed(2)}%`;
                }
                if (market.held_percent_institutions !== undefined && market.held_percent_institutions !== null) {
                    systemPrompt += `\n- Institutional Ownership: ${(market.held_percent_institutions * 100).toFixed(2)}%`;
                }

                systemPrompt += `\n\n### Financial Snapshot`;
                systemPrompt += `\n- Enterprise Value: ${formatValue(financials.enterprise_value)}`;
                systemPrompt += `\n- Cash: ${formatValue(financials.cash)}`;
                systemPrompt += `\n- Total Debt: ${formatValue(financials.total_debt)}`;
                systemPrompt += `\n- EBITDA: ${formatValue(financials.ebitda)}`;
                systemPrompt += `\n- EPS: ${financials.eps !== undefined && financials.eps !== null ? financials.eps.toFixed(2) : 'N/A'}`;
                systemPrompt += `\n- Working Capital: ${formatValue(financials.working_capital)}`;

                systemPrompt += `\n\n### Gap Statistics (historical average behavior on +20% gap days)`;
                systemPrompt += `\n- Offset 0 (Gap day itself): Gap days count: ${gapStats.gap_days_count || 0}, High Spike Avg: ${gapStats.high_rth_spike_avg != null ? gapStats.high_rth_spike_avg.toFixed(2) + '%' : 'N/A'}, Low Spike Avg: ${gapStats.low_rth_spike_avg != null ? gapStats.low_rth_spike_avg.toFixed(2) + '%' : 'N/A'}, Negative Close Freq: ${gapStats.neg_close_freq != null ? gapStats.neg_close_freq.toFixed(2) + '%' : 'N/A'}, Close below VWAP Freq: ${gapStats.close_below_vwap_freq != null ? gapStats.close_below_vwap_freq.toFixed(2) + '%' : 'N/A'}`;
                systemPrompt += `\n- Offset +1 (Day after gap): High Spike Avg: ${gapStats1.high_rth_spike_avg != null ? gapStats1.high_rth_spike_avg.toFixed(2) + '%' : 'N/A'}, Negative Close Freq: ${gapStats1.neg_close_freq != null ? gapStats1.neg_close_freq.toFixed(2) + '%' : 'N/A'}`;
                systemPrompt += `\n- Offset +2 (Two days after gap): High Spike Avg: ${gapStats2.high_rth_spike_avg != null ? gapStats2.high_rth_spike_avg.toFixed(2) + '%' : 'N/A'}, Negative Close Freq: ${gapStats2.neg_close_freq != null ? gapStats2.neg_close_freq.toFixed(2) + '%' : 'N/A'}`;

                if (filings && Object.keys(filings).length > 0) {
                    systemPrompt += `\n\n### Recent SEC Filings`;
                    Object.entries(filings).forEach(([category, items]: [string, any]) => {
                        if (Array.isArray(items) && items.length > 0) {
                            const summaryItems = items.slice(0, 3).map(item => `${item.type} (${item.date})`);
                            systemPrompt += `\n- ${category.charAt(0).toUpperCase() + category.slice(1)}: ${summaryItems.join(', ')}`;
                        }
                    });
                }

                if (news && news.length > 0) {
                    systemPrompt += `\n\n### Recent News Titles`;
                    news.slice(0, 8).forEach((item: any) => {
                        systemPrompt += `\n- [${item.date} ${item.time}] ${item.title} (Source: ${item.source || 'Unknown'})`;
                    });
                }

                if (tickerData.secCompanyFacts && tickerData.secCompanyFacts.facts) {
                    systemPrompt += `\n\n### SEC EDGAR Company Facts (XBRL)`;
                    systemPrompt += `\n- CIK: ${tickerData.secCompanyFacts.cik || 'N/A'}`;
                    systemPrompt += `\n- Entity Name: ${tickerData.secCompanyFacts.company_name || 'N/A'}`;
                    systemPrompt += `\n- Historical Facts:`;
                    
                    const facts = tickerData.secCompanyFacts.facts;
                    Object.entries(facts).forEach(([conceptName, factObj]: [string, any]) => {
                        const label = factObj.label || conceptName;
                        const history = factObj.history || [];
                        if (history.length > 0) {
                            const historyStr = history.map((h: any) => {
                                const periodInfo = h.period ? ` (${h.period} ${h.year || ''})` : '';
                                return `${h.date}${periodInfo}: ${formatValue(h.value, h.unit === 'USD')}`;
                            }).join(' | ');
                            systemPrompt += `\n  * ${conceptName} (${label}): ${historyStr}`;
                        }
                    });
                }
            }

            // 4. Map message history into DeepSeek API format (excluding system notifications)
            const apiMessages = [
                { role: 'system', content: systemPrompt },
                ...newMessages
                    .filter(m => m.role !== 'system')
                    .map(m => ({ role: m.role, content: m.content }))
            ];

            // 5. Query DeepSeek API directly
            const response = await fetch('https://api.deepseek.com/chat/completions', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${currentKey}`
                },
                body: JSON.stringify({
                    model: 'deepseek-chat',
                    messages: apiMessages,
                    temperature: 0.2
                })
            });

            if (!response.ok) {
                const errData = await response.json().catch(() => ({}));
                const errMsg = errData.error?.message || `HTTP error ${response.status}`;
                throw new Error(errMsg);
            }

            const data = await response.json();
            const reply = data.choices?.[0]?.message?.content || 'No he recibido respuesta de DeepSeek.';

            setMessages(prev => [
                ...prev,
                { role: 'assistant', content: reply }
            ]);

        } catch (error: any) {
            console.error('Error contacting DeepSeek:', error);
            setMessages(prev => [
                ...prev,
                { 
                    role: 'system', 
                    content: `Error al conectar con DeepSeek: ${error.message || 'Error de red o CORS'}.` 
                }
            ]);
        } finally {
            setIsGenerating(false);
        }
    };

    return (
        <>
            {/* Pulsating eye and robot status animations styles */}
            <style dangerouslySetInnerHTML={{ __html: `
                @keyframes edge-glow {
                    0% { box-shadow: 0 0 10px rgba(216, 122, 61, 0.4), 0 8px 32px rgba(0, 0, 0, 0.4); }
                    100% { box-shadow: 0 0 20px rgba(216, 122, 61, 0.7), 0 8px 32px rgba(0, 0, 0, 0.4); }
                }
                @keyframes edge-eye-pulse {
                    0% { opacity: 0.6; transform: scale(0.9); }
                    100% { opacity: 1; transform: scale(1.1); }
                }
                @keyframes dot-blink {
                    0% { opacity: 0.2; }
                    50% { opacity: 1; }
                    100% { opacity: 0.2; }
                }
            ` }} />

            {/* Floating Robot Toggle Button */}
            <button
                onClick={() => setIsOpen(!isOpen)}
                style={{
                    position: 'fixed',
                    bottom: '24px',
                    right: '24px',
                    width: '60px',
                    height: '60px',
                    borderRadius: '50%',
                    backgroundColor: 'var(--color-ec-bg-surface)',
                    border: isOpen ? '1.5px solid var(--color-ec-copper-bright)' : '1px solid var(--color-ec-border)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    cursor: 'pointer',
                    zIndex: 9999,
                    transition: 'all 200ms cubic-bezier(0.16, 1, 0.3, 1)',
                    animation: isOpen ? 'none' : 'edge-glow 2s infinite alternate',
                    outline: 'none'
                }}
                className="hover:scale-105 active:scale-95"
            >
                <RobotAvatar size={34} glowing={isOpen} />
            </button>

            {/* Chatbot Window (Edgie) */}
            {isOpen && (
                <div
                    style={{
                        position: 'fixed',
                        bottom: '96px',
                        right: '24px',
                        width: '460px',
                        height: '660px',
                        maxWidth: 'calc(100vw - 48px)',
                        maxHeight: 'calc(100vh - 120px)',
                        backgroundColor: 'var(--color-ec-bg-surface)',
                        border: '1.5px solid var(--color-ec-border)',
                        borderRadius: '16px',
                        boxShadow: '0 20px 50px rgba(0, 0, 0, 0.7), 0 0 1px 1px rgba(216, 122, 61, 0.15)',
                        display: 'flex',
                        flexDirection: 'column',
                        overflow: 'hidden',
                        zIndex: 9998,
                        fontFamily: 'var(--font-sans)',
                    }}
                >
                    {/* Header */}
                    <div
                        style={{
                            height: '60px',
                            backgroundColor: 'var(--color-ec-bg-sidebar)',
                            borderBottom: '1px solid var(--color-ec-border)',
                            padding: '0 18px',
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'space-between',
                            flexShrink: 0
                        }}
                    >
                        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                            <RobotAvatar size={30} glowing={true} />
                            <div>
                                <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                                    <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--color-ec-text-high)', letterSpacing: '0.2px' }}>
                                        Edgie
                                    </span>
                                    <span style={{ 
                                        fontSize: 8, 
                                        fontWeight: 800, 
                                        color: '#ffffff', 
                                        backgroundColor: 'var(--color-ec-copper)', 
                                        padding: '1px 5px', 
                                        borderRadius: '3px',
                                        textTransform: 'uppercase',
                                        letterSpacing: '0.5px'
                                    }}>
                                        Assistant
                                    </span>
                                </div>
                                <div style={{ display: 'flex', alignItems: 'center', gap: 4, marginTop: 2 }}>
                                    <span style={{ width: 5, height: 5, borderRadius: '50%', backgroundColor: 'var(--color-ec-profit)', boxShadow: '0 0 6px var(--color-ec-profit)' }} />
                                    <span style={{ fontSize: 9, fontWeight: 600, color: 'var(--color-ec-text-muted)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
                                        {activeTicker ? `Cargado: ${activeTicker}` : "En línea"}
                                    </span>
                                </div>
                            </div>
                        </div>

                        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                            <button
                                onClick={handleResetChat}
                                title="Reiniciar conversación"
                                style={{ background: 'none', border: 'none', color: 'var(--color-ec-text-muted)', cursor: 'pointer', display: 'flex', padding: 4 }}
                                className="hover:text-[var(--color-ec-text-high)] transition-colors"
                            >
                                <RotateCcw size={15} />
                            </button>
                            <button
                                onClick={() => setShowSettings(!showSettings)}
                                title="Configurar API Key"
                                style={{ 
                                    background: 'none', 
                                    border: 'none', 
                                    color: showSettings ? 'var(--color-ec-copper-bright)' : 'var(--color-ec-text-muted)', 
                                    cursor: 'pointer', 
                                    display: 'flex', 
                                    padding: 4 
                                }}
                                className="hover:text-[var(--color-ec-text-high)] transition-colors"
                            >
                                <Settings size={15} />
                            </button>
                            <button
                                onClick={() => setIsOpen(false)}
                                style={{ background: 'none', border: 'none', color: 'var(--color-ec-text-muted)', cursor: 'pointer', display: 'flex', padding: 4 }}
                                className="hover:text-[var(--color-ec-text-high)] transition-colors"
                            >
                                <X size={15} />
                            </button>
                        </div>
                    </div>

                    {/* Settings Panel */}
                    {showSettings ? (
                        <div
                            style={{
                                flex: 1,
                                padding: '24px',
                                backgroundColor: 'var(--color-ec-bg-surface)',
                                display: 'flex',
                                flexDirection: 'column',
                                gap: '18px'
                            }}
                        >
                            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                                <span style={{ fontSize: 10, fontWeight: 700, color: 'var(--color-ec-copper)', textTransform: 'uppercase', letterSpacing: '1px' }}>
                                    Parámetros del Copiloto Edgie
                                </span>
                                <p style={{ fontSize: 12, color: 'var(--color-ec-text-secondary)', lineHeight: 1.5 }}>
                                    Ingresa tu clave de DeepSeek para conectar a Edgie directamente a la API de lenguaje natural. Se guarda localmente y no sale de tu ordenador.
                                </p>
                            </div>

                            <form onSubmit={handleSaveApiKey} style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
                                <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                                    <label style={{ fontSize: 10, color: 'var(--color-ec-text-primary)', fontWeight: 700 }}>DEEPSEEK_API_KEY</label>
                                    <input
                                        type="password"
                                        placeholder="sk-..."
                                        value={apiKey}
                                        onChange={(e) => setApiKey(e.target.value)}
                                        style={{
                                            backgroundColor: 'var(--color-ec-bg-sidebar)',
                                            border: '1px solid var(--color-ec-border)',
                                            borderRadius: '8px',
                                            padding: '10px 14px',
                                            fontSize: 12,
                                            color: 'var(--color-ec-text-high)',
                                            outline: 'none',
                                            width: '100%',
                                            boxSizing: 'border-box'
                                        }}
                                    />
                                </div>

                                <div style={{ display: 'flex', gap: '10px', marginTop: 8 }}>
                                    <button
                                        type="submit"
                                        style={{
                                            flex: 1,
                                            backgroundColor: 'var(--color-ec-copper)',
                                            color: '#ffffff',
                                            border: 'none',
                                            borderRadius: '8px',
                                            padding: '10px',
                                            fontSize: 12,
                                            fontWeight: 600,
                                            cursor: 'pointer'
                                        }}
                                        className="hover:bg-[var(--color-ec-copper-bright)] transition-colors"
                                    >
                                        Activar Robot
                                    </button>
                                    <button
                                        type="button"
                                        onClick={() => setShowSettings(false)}
                                        style={{
                                            flex: 1,
                                            backgroundColor: 'transparent',
                                            color: 'var(--color-ec-text-secondary)',
                                            border: '1px solid var(--color-ec-border)',
                                            borderRadius: '8px',
                                            padding: '10px',
                                            fontSize: 12,
                                            fontWeight: 600,
                                            cursor: 'pointer'
                                        }}
                                        className="hover:bg-[var(--color-ec-bg-sidebar)] hover:text-white transition-colors"
                                    >
                                        Cancelar
                                    </button>
                                </div>
                            </form>

                            <div style={{ marginTop: 'auto', display: 'flex', alignItems: 'center', gap: 8, color: 'var(--color-ec-text-muted)', fontSize: 11 }}>
                                <AlertCircle size={14} style={{ color: 'var(--color-ec-copper)' }} />
                                <span>Tus credenciales están guardadas de forma segura en `localStorage`.</span>
                            </div>
                        </div>
                    ) : (
                        /* Chat Messages & Input Area */
                        <>
                            {/* Messages Container */}
                            <div
                                style={{
                                    flex: 1,
                                    overflowY: 'auto',
                                    padding: '18px',
                                    display: 'flex',
                                    flexDirection: 'column',
                                    gap: '14px',
                                    backgroundColor: 'var(--color-ec-bg-surface)'
                                }}
                                className="custom-scrollbar"
                            >
                                {messages.map((msg, index) => {
                                    if (msg.role === 'system') {
                                        return (
                                            <div
                                                key={index}
                                                style={{
                                                    backgroundColor: 'rgba(216, 122, 61, 0.06)',
                                                    border: '1px solid rgba(216, 122, 61, 0.15)',
                                                    borderRadius: '8px',
                                                    padding: '10px 14px',
                                                    fontSize: 11,
                                                    color: 'var(--color-ec-text-secondary)',
                                                    display: 'flex',
                                                    gap: 8,
                                                    alignItems: 'flex-start',
                                                    lineHeight: 1.4
                                                }}
                                            >
                                                <AlertCircle size={13} style={{ color: 'var(--color-ec-copper)', flexShrink: 0, marginTop: 2 }} />
                                                <span>{msg.content}</span>
                                            </div>
                                        );
                                    }

                                    const isUser = msg.role === 'user';
                                    return (
                                        <div
                                            key={index}
                                            style={{
                                                alignSelf: isUser ? 'flex-end' : 'flex-start',
                                                maxWidth: '88%',
                                                display: 'flex',
                                                gap: 8,
                                                alignItems: 'flex-start'
                                            }}
                                        >
                                            {!isUser && (
                                                <div style={{ marginTop: 2, flexShrink: 0 }}>
                                                    <RobotAvatar size={24} glowing={true} />
                                                </div>
                                            )}
                                            
                                            <div
                                                style={{
                                                    backgroundColor: isUser ? 'rgba(216, 122, 61, 0.12)' : 'var(--color-ec-bg-elevated)',
                                                    border: isUser ? '1px solid var(--color-ec-copper)' : '1px solid var(--color-ec-border)',
                                                    borderRadius: isUser ? '14px 14px 2px 14px' : '14px 14px 14px 2px',
                                                    padding: '10px 14px',
                                                    boxShadow: '0 2px 12px rgba(0, 0, 0, 0.15)'
                                                }}
                                            >
                                                {renderMessageContent(msg.content)}
                                            </div>
                                        </div>
                                    );
                                })}

                                {isGenerating && (
                                    <div style={{ alignSelf: 'flex-start', display: 'flex', gap: 8, alignItems: 'flex-start' }}>
                                        <div style={{ flexShrink: 0, marginTop: 2 }}>
                                            <RobotAvatar size={24} glowing={true} />
                                        </div>
                                        <div style={{
                                            backgroundColor: 'var(--color-ec-bg-elevated)',
                                            border: '1px solid var(--color-ec-border)',
                                            borderRadius: '14px 14px 14px 2px',
                                            padding: '10px 14px',
                                            fontSize: 12,
                                            color: 'var(--color-ec-text-muted)',
                                            display: 'flex',
                                            alignItems: 'center',
                                            gap: 8
                                        }}>
                                            <span style={{ fontSize: 11, fontStyle: 'italic' }}>
                                                {activeTicker ? `Edgie procesando datos de ${activeTicker}...` : "Edgie procesando consulta..."}
                                            </span>
                                            <div style={{ display: 'flex', gap: 3 }}>
                                                <span style={{ width: 4, height: 4, borderRadius: '50%', backgroundColor: 'var(--color-ec-copper)', animation: 'dot-blink 1.2s infinite' }} />
                                                <span style={{ width: 4, height: 4, borderRadius: '50%', backgroundColor: 'var(--color-ec-copper)', animation: 'dot-blink 1.2s infinite 0.3s' }} />
                                                <span style={{ width: 4, height: 4, borderRadius: '50%', backgroundColor: 'var(--color-ec-copper)', animation: 'dot-blink 1.2s infinite 0.6s' }} />
                                            </div>
                                        </div>
                                    </div>
                                )}
                                <div ref={messagesEndRef} />
                            </div>

                            {/* Attached File Preview Badge (Above Input Bar) */}
                            {attachedFile && (
                                <div style={{
                                    backgroundColor: 'var(--color-ec-bg-elevated)',
                                    borderTop: '1px solid var(--color-ec-border)',
                                    padding: '8px 16px',
                                    display: 'flex',
                                    alignItems: 'center',
                                    justifyContent: 'space-between',
                                    flexShrink: 0
                                }}>
                                    <div style={{ display: 'flex', alignItems: 'center', gap: 6, minWidth: 0 }}>
                                        <FileText size={14} style={{ color: 'var(--color-ec-copper)' }} />
                                        <span style={{ 
                                            fontSize: 11, 
                                            color: 'var(--color-ec-text-primary)', 
                                            overflow: 'hidden', 
                                            textOverflow: 'ellipsis', 
                                            whiteSpace: 'nowrap',
                                            fontWeight: 600
                                        }}>
                                            {attachedFile.name}
                                        </span>
                                    </div>
                                    <button 
                                        onClick={() => setAttachedFile(null)}
                                        style={{ background: 'none', border: 'none', color: 'var(--color-ec-text-muted)', cursor: 'pointer', display: 'flex', padding: 2 }}
                                        className="hover:text-white"
                                    >
                                        <X size={14} />
                                    </button>
                                </div>
                            )}

                            {/* Chat Input form */}
                            <form
                                onSubmit={handleSend}
                                style={{
                                    height: '64px',
                                    backgroundColor: 'var(--color-ec-bg-sidebar)',
                                    borderTop: '1px solid var(--color-ec-border)',
                                    display: 'flex',
                                    alignItems: 'center',
                                    padding: '0 16px',
                                    gap: 10,
                                    flexShrink: 0
                                }}
                            >
                                {/* Hidden File Input */}
                                <input 
                                    type="file" 
                                    ref={fileInputRef} 
                                    onChange={handleFileUpload} 
                                    style={{ display: 'none' }}
                                    accept=".txt,.csv,.json,.xml,.tsv,.log"
                                />
                                
                                <button
                                    type="button"
                                    onClick={handleFileClick}
                                    title="Adjuntar archivo (.txt, .csv, .json)"
                                    disabled={isGenerating}
                                    style={{
                                        background: 'none',
                                        border: 'none',
                                        color: attachedFile ? 'var(--color-ec-copper)' : 'var(--color-ec-text-secondary)',
                                        cursor: isGenerating ? 'default' : 'pointer',
                                        display: 'flex',
                                        padding: 6
                                    }}
                                    className="hover:text-[var(--color-ec-text-high)] transition-colors"
                                >
                                    <Paperclip size={16} />
                                </button>

                                <input
                                    type="text"
                                    placeholder={activeTicker ? `Pregunta a Edgie sobre ${activeTicker}...` : "Pregúntale a Edgie..."}
                                    value={input}
                                    onChange={(e) => setInput(e.target.value)}
                                    disabled={isGenerating}
                                    style={{
                                        flex: 1,
                                        height: '38px',
                                        backgroundColor: 'var(--color-ec-bg-base)',
                                        border: '1px solid var(--color-ec-border)',
                                        borderRadius: '8px',
                                        padding: '0 14px',
                                        color: 'var(--color-ec-text-high)',
                                        fontSize: 12,
                                        outline: 'none'
                                    }}
                                    className="focus:border-[var(--color-ec-copper)] transition-colors"
                                />
                                
                                <button
                                    type="submit"
                                    disabled={isGenerating || !input.trim()}
                                    style={{
                                        width: '38px',
                                        height: '38px',
                                        borderRadius: '8px',
                                        backgroundColor: input.trim() && !isGenerating ? 'var(--color-ec-copper)' : 'rgba(255, 255, 255, 0.03)',
                                        border: 'none',
                                        display: 'flex',
                                        alignItems: 'center',
                                        justifyContent: 'center',
                                        color: input.trim() && !isGenerating ? '#ffffff' : 'var(--color-ec-text-muted)',
                                        cursor: input.trim() && !isGenerating ? 'pointer' : 'default',
                                        transition: 'all 150ms ease'
                                    }}
                                >
                                    <Send size={15} />
                                </button>
                            </form>
                        </>
                    )}
                </div>
            )}
        </>
    );
}
