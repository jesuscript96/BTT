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
            <div style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                padding: '80px',
                color: 'var(--color-ec-text-secondary)',
                fontFamily: "'General Sans', sans-serif",
                fontSize: '12px',
                fontWeight: 600,
                letterSpacing: '1px',
                textTransform: 'uppercase'
            }}>
                Loading records...
            </div>
        );
    }

    if (data.length === 0) {
        return (
            <div style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                padding: '80px',
                color: 'var(--color-ec-text-secondary)',
                fontFamily: "'General Sans', sans-serif",
                fontSize: '12px',
                fontWeight: 600,
                letterSpacing: '1px',
                textTransform: 'uppercase'
            }}>
                No records found.
            </div>
        );
    }

    // Auto-detect columns from first row
    const columns = Object.keys(data[0]);

    return (
        <div style={{
            overflowX: 'auto',
            width: '100%',
            backgroundColor: 'var(--color-ec-bg-surface)',
            position: 'relative',
        }}>
            {/* Header: Title and records count */}
            <div style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                padding: '12px 16px',
                borderBottom: '1px solid var(--color-ec-border)',
                backgroundColor: 'var(--color-ec-bg-surface)',
            }}>
                <span style={{
                    fontFamily: "'Fraunces', serif",
                    fontSize: '14px',
                    fontWeight: 600,
                    color: 'var(--color-ec-text-high)',
                }}>
                    Scanned Records
                </span>
                <span style={{
                    fontFamily: "'General Sans', sans-serif",
                    fontSize: '10px',
                    fontWeight: 600,
                    color: 'var(--color-ec-text-muted)',
                    textTransform: 'uppercase',
                    letterSpacing: '0.5px'
                }}>
                    Showing {Math.min(data.length, (page + 1) * PAGE_SIZE).toLocaleString()} of {data.length.toLocaleString()} records
                </span>
            </div>

            {/* Table */}
            <table style={{
                width: '100%',
                textAlign: 'left',
                borderCollapse: 'collapse',
                fontFamily: "'General Sans', sans-serif",
            }}>
                <thead>
                    <tr style={{
                        backgroundColor: 'var(--color-ec-bg-elevated)',
                        fontSize: '9px',
                        textTransform: 'uppercase',
                        fontWeight: 700,
                        color: 'var(--color-ec-text-muted)',
                        letterSpacing: '1px',
                        position: 'sticky',
                        top: 0,
                        zIndex: 10,
                    }}>
                        <th style={{
                            padding: '10px 16px',
                            position: 'sticky',
                            left: 0,
                            backgroundColor: 'var(--color-ec-bg-elevated)',
                            zIndex: 20,
                            borderBottom: '1px solid var(--color-ec-border)',
                            width: '48px',
                            textAlign: 'center',
                        }}>
                            View
                        </th>
                        {columns.map((col) => (
                            <th key={col} style={{
                                padding: '10px 16px',
                                whiteSpace: 'nowrap',
                                borderBottom: '1px solid var(--color-ec-border)',
                            }}>
                                {col.replace(/_/g, " ")}
                            </th>
                        ))}
                    </tr>
                </thead>
                <tbody style={{
                    backgroundColor: 'var(--color-ec-bg-surface)',
                }}>
                    {visibleData.map((row, i) => (
                        <tr
                            key={i}
                            style={{
                                borderBottom: '1px solid color-mix(in srgb, var(--color-ec-border) 40%, transparent)',
                                transition: 'background-color 150ms ease',
                            }}
                            onMouseEnter={(e) => {
                                e.currentTarget.style.backgroundColor = 'var(--color-ec-bg-elevated)';
                                const firstCell = e.currentTarget.firstElementChild as HTMLElement;
                                if (firstCell) firstCell.style.backgroundColor = 'var(--color-ec-bg-elevated)';
                            }}
                            onMouseLeave={(e) => {
                                e.currentTarget.style.backgroundColor = 'transparent';
                                const firstCell = e.currentTarget.firstElementChild as HTMLElement;
                                if (firstCell) firstCell.style.backgroundColor = 'var(--color-ec-bg-base)';
                            }}
                        >
                            <td style={{
                                padding: '8px 16px',
                                position: 'sticky',
                                left: 0,
                                backgroundColor: 'var(--color-ec-bg-base)',
                                zIndex: 10,
                                borderRight: '1px solid var(--color-ec-border)',
                                textAlign: 'center',
                                transition: 'background-color 150ms ease',
                            }}>
                                <button
                                    onClick={() => {
                                        const url = `/analysis/${row.ticker}/${row.date}`;
                                        window.open(url, '_blank', 'noreferrer');
                                    }}
                                    style={{
                                        background: 'none',
                                        border: 'none',
                                        cursor: 'pointer',
                                        color: 'var(--color-ec-text-secondary)',
                                        padding: '4px',
                                        borderRadius: '4px',
                                        display: 'inline-flex',
                                        alignItems: 'center',
                                        justifyContent: 'center',
                                        transition: 'all 150ms ease',
                                    }}
                                    title="View Intraday Chart in New Window"
                                    onMouseEnter={(e) => {
                                        e.currentTarget.style.color = 'var(--color-ec-copper)';
                                        e.currentTarget.style.backgroundColor = 'rgba(216, 122, 61, 0.1)';
                                    }}
                                    onMouseLeave={(e) => {
                                        e.currentTarget.style.color = 'var(--color-ec-text-secondary)';
                                        e.currentTarget.style.backgroundColor = 'transparent';
                                    }}
                                >
                                    <Eye style={{ width: 14, height: 14 }} />
                                </button>
                            </td>
                            {columns.map((col) => {
                                const val = row[col];
                                const isNumber = typeof val === 'number';
                                
                                let cellColor = 'var(--color-ec-text-primary)';
                                let fontWeight = 500;

                                if (col.toLowerCase() === 'ticker') {
                                    fontWeight = 700;
                                    cellColor = 'var(--color-ec-text-high)';
                                } else if (isNumber) {
                                    const colLower = col.toLowerCase();
                                    if (
                                        colLower.includes('change') || 
                                        colLower.includes('profit') || 
                                        colLower.includes('gain') || 
                                        colLower.includes('loss') || 
                                        colLower.includes('pct') || 
                                        colLower.includes('run') || 
                                        colLower.includes('fade') || 
                                        colLower.includes('spike')
                                    ) {
                                        if (val > 0) cellColor = 'var(--color-ec-profit)';
                                        else if (val < 0) cellColor = 'var(--color-ec-loss)';
                                    }
                                }

                                return (
                                    <td key={`${i}-${col}`} style={{
                                        padding: '8px 16px',
                                        whiteSpace: 'nowrap',
                                        color: cellColor,
                                        fontWeight: fontWeight,
                                        fontSize: '11px',
                                    }}>
                                        {isNumber
                                            ? val.toLocaleString(undefined, { maximumFractionDigits: 2 })
                                            : val
                                        }
                                    </td>
                                );
                            })}
                        </tr>
                    ))}
                </tbody>
            </table>

            {/* Pagination */}
            {data.length > PAGE_SIZE && (
                <div style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    gap: '16px',
                    padding: '12px',
                    fontSize: '11px',
                    fontWeight: 600,
                    color: 'var(--color-ec-text-secondary)',
                    borderTop: '1px solid var(--color-ec-border)',
                    backgroundColor: 'var(--color-ec-bg-surface)',
                    fontFamily: "'General Sans', sans-serif",
                }}>
                    <button
                        onClick={() => setPage(p => Math.max(0, p - 1))}
                        disabled={page === 0}
                        style={{
                            padding: '6px 12px',
                            borderRadius: '4px',
                            background: 'var(--color-ec-bg-elevated)',
                            border: '1px solid var(--color-ec-border)',
                            color: page === 0 ? 'var(--color-ec-text-muted)' : 'var(--color-ec-text-primary)',
                            cursor: page === 0 ? 'not-allowed' : 'pointer',
                            opacity: page === 0 ? 0.4 : 1,
                            transition: 'all 150ms ease',
                        }}
                        onMouseEnter={(e) => {
                            if (page !== 0) {
                                e.currentTarget.style.borderColor = 'var(--color-ec-copper)';
                                e.currentTarget.style.color = 'var(--color-ec-copper-bright)';
                            }
                        }}
                        onMouseLeave={(e) => {
                            e.currentTarget.style.borderColor = 'var(--color-ec-border)';
                            e.currentTarget.style.color = page === 0 ? 'var(--color-ec-text-muted)' : 'var(--color-ec-text-primary)';
                        }}
                    >
                        ← Anterior
                    </button>
                    
                    <span style={{ letterSpacing: '0.5px' }}>
                        {page * PAGE_SIZE + 1} - {Math.min((page + 1) * PAGE_SIZE, data.length)} de {data.length.toLocaleString()}
                    </span>
                    
                    <button
                        onClick={() => setPage(p => p + 1)}
                        disabled={(page + 1) * PAGE_SIZE >= data.length}
                        style={{
                            padding: '6px 12px',
                            borderRadius: '4px',
                            background: 'var(--color-ec-bg-elevated)',
                            border: '1px solid var(--color-ec-border)',
                            color: (page + 1) * PAGE_SIZE >= data.length ? 'var(--color-ec-text-muted)' : 'var(--color-ec-text-primary)',
                            cursor: (page + 1) * PAGE_SIZE >= data.length ? 'not-allowed' : 'pointer',
                            opacity: (page + 1) * PAGE_SIZE >= data.length ? 0.4 : 1,
                            transition: 'all 150ms ease',
                        }}
                        onMouseEnter={(e) => {
                            if ((page + 1) * PAGE_SIZE < data.length) {
                                e.currentTarget.style.borderColor = 'var(--color-ec-copper)';
                                e.currentTarget.style.color = 'var(--color-ec-copper-bright)';
                            }
                        }}
                        onMouseLeave={(e) => {
                            e.currentTarget.style.borderColor = 'var(--color-ec-border)';
                            e.currentTarget.style.color = (page + 1) * PAGE_SIZE >= data.length ? 'var(--color-ec-text-muted)' : 'var(--color-ec-text-primary)';
                        }}
                    >
                        Siguiente →
                    </button>
                </div>
            )}
        </div>
    );
};
