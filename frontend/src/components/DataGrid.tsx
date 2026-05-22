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
                <thead className="bg-muted text-[10px] uppercase font-black text-muted-foreground sticky top-0 tracking-widest z-10">
                    <tr>
                        <th className="px-4 py-3 sticky left-0 bg-muted z-20 border-b border-border w-12 text-center">
                            View
                        </th>
                        {columns.map((col) => (
                            <th key={col} className="px-4 py-3 whitespace-nowrap border-b border-border">
                                {col.replace(/_/g, " ")}
                            </th>
                        ))}
                    </tr>
                </thead>
                <tbody className="divide-y divide-border/50">
                    {visibleData.map((row, i) => (
                        <tr key={i} className="hover:bg-accent/50 transition-colors group">
                            <td className="px-4 py-3 sticky left-0 bg-background group-hover:bg-accent/50 z-10 border-r border-border/50 text-center">
                                <button
                                    onClick={() => {
                                        const url = `/analysis/${row.ticker}/${row.date}`;
                                        window.open(url, '_blank', 'noreferrer');
                                    }}
                                    className="p-1.5 hover:bg-blue-500/10 rounded-lg text-blue-500 transition-colors flex items-center justify-center w-full"
                                    title="View Intraday Chart in New Window"
                                >
                                    <Eye className="w-4 h-4" />
                                </button>
                            </td>
                            {columns.map((col) => (
                                <td key={`${i}-${col}`} className="px-4 py-3 whitespace-nowrap text-foreground/90 font-medium">
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
                <div className="flex items-center justify-center gap-3 p-3 text-sm font-medium text-muted-foreground border-t border-border">
                    <button
                        onClick={() => setPage(p => Math.max(0, p - 1))}
                        disabled={page === 0}
                        className="px-3 py-1 rounded bg-card border border-border hover:bg-muted disabled:opacity-30 transition-colors"
                    >← Anterior</button>
                    <span>{page * PAGE_SIZE + 1}-{Math.min((page + 1) * PAGE_SIZE, data.length)} de {data.length.toLocaleString()}</span>
                    <button
                        onClick={() => setPage(p => p + 1)}
                        disabled={(page + 1) * PAGE_SIZE >= data.length}
                        className="px-3 py-1 rounded bg-card border border-border hover:bg-muted disabled:opacity-30 transition-colors"
                    >Siguiente →</button>
                </div>
            )}
        </div>
    );
};
