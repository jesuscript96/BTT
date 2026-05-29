import React from "react";
import { Eye } from "lucide-react";

interface DataGridProps {
    data: any[];
    isLoading: boolean;
    onViewDay?: (row: any) => void;
}

export const DataGrid: React.FC<DataGridProps> = ({ data, isLoading, onViewDay }) => {
    const [page, setPage] = React.useState(0);
    const PAGE_SIZE = 100;
    const visibleData = data.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);

    React.useEffect(() => { setPage(0); }, [data]);
    if (isLoading) {
        return (
            <div className="flex items-center justify-center p-20 text-ec-text-secondary">
                Loading data...
            </div>
        );
    }

    if (data.length === 0) {
        return (
            <div className="flex items-center justify-center p-20 text-ec-text-secondary">
                No records found.
            </div>
        );
    }

    // Auto-detect columns from first row (excluding internal enrichment if needed, but we want most)
    const columns = Object.keys(data[0]);

    return (
        <div className="overflow-x-auto w-full bg-background transition-colors duration-300 relative">
            <table className="w-full text-left text-sm text-foreground/80 border-collapse">
                <thead style={{ background: 'var(--color-ec-bg-elevated)', fontSize: 9, textTransform: 'uppercase', fontWeight: 700, color: 'var(--color-ec-text-muted)', letterSpacing: '1.5px', position: 'sticky', top: 0, zIndex: 10 }}>
                    <tr>
                        <th style={{ padding: '8px 12px', position: 'sticky', left: 0, background: 'var(--color-ec-bg-elevated)', zIndex: 20, borderBottom: '0.5px solid var(--color-ec-border)', width: 48, textAlign: 'center' }}>
                            View
                        </th>
                        {columns.map((col) => (
                            <th key={col} style={{ padding: '8px 12px', whiteSpace: 'nowrap', borderBottom: '0.5px solid var(--color-ec-border)' }}>
                                {col.replace(/_/g, " ")}
                            </th>
                        ))}
                    </tr>
                </thead>
                <tbody className="divide-y divide-border/50">
                    {visibleData.map((row, i) => (
                        <tr key={i} style={{ transition: 'background 150ms' }} className="hover:bg-[var(--color-ec-bg-elevated)] group">
                            <td style={{ padding: '8px 12px', position: 'sticky', left: 0, background: 'var(--color-ec-bg-base)', zIndex: 10, borderRight: '0.5px solid var(--color-ec-border)', textAlign: 'center' }} className="group-hover:bg-[var(--color-ec-bg-elevated)]">
                                <button
                                    onClick={() => {
                                        const url = `/analysis/${row.ticker}/${row.date}`;
                                        window.open(url, '_blank', 'noreferrer');
                                    }}
                                    style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--color-ec-text-secondary)', padding: 4, borderRadius: 5 }}
                                    title="View Intraday Chart in New Window"
                                    onMouseEnter={(e) => { (e.currentTarget as HTMLButtonElement).style.background = 'var(--color-ec-bg-elevated)'; }}
                                    onMouseLeave={(e) => { (e.currentTarget as HTMLButtonElement).style.background = 'none'; }}
                                >
                                    <Eye className="w-4 h-4" />
                                </button>
                            </td>
                            {columns.map((col) => (
                                <td key={`${i}-${col}`} style={{ padding: '8px 12px', whiteSpace: 'nowrap', color: 'var(--color-ec-text-primary)', fontWeight: 500, fontSize: 12 }}>
                                    {typeof row[col] === 'number'
                                        ? row[col].toLocaleString(undefined, { maximumFractionDigits: 2 })
                                        : row[col]
                                    }
                                </td>
                            ))}
                        </tr>
                    ))}
                </tbody>
            </table>
            {data.length > PAGE_SIZE && (
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 12, padding: 10, fontSize: 12, fontWeight: 500, color: 'var(--color-ec-text-muted)', borderTop: '0.5px solid var(--color-ec-border)' }}>
                    <button
                        onClick={() => setPage(p => Math.max(0, p - 1))}
                        disabled={page === 0}
                        style={{ padding: '4px 8px', borderRadius: 5, background: 'var(--color-ec-bg-surface)', border: '0.5px solid var(--color-ec-border)', color: 'var(--color-ec-text-secondary)', cursor: page === 0 ? 'default' : 'pointer', opacity: page === 0 ? 0.3 : 1 }}
                    >← Anterior</button>
                    <span>{page * PAGE_SIZE + 1}-{Math.min((page + 1) * PAGE_SIZE, data.length)} de {data.length.toLocaleString()}</span>
                    <button
                        onClick={() => setPage(p => p + 1)}
                        disabled={(page + 1) * PAGE_SIZE >= data.length}
                        style={{ padding: '4px 8px', borderRadius: 5, background: 'var(--color-ec-bg-surface)', border: '0.5px solid var(--color-ec-border)', color: 'var(--color-ec-text-secondary)', cursor: (page + 1) * PAGE_SIZE >= data.length ? 'default' : 'pointer', opacity: (page + 1) * PAGE_SIZE >= data.length ? 0.3 : 1 }}
                    >Siguiente →</button>
                </div>
            )}
        </div>
    );
};
