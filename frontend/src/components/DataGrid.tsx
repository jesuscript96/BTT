import React from "react";

interface DataGridProps {
    data: any[];
    isLoading: boolean;
}

export const DataGrid: React.FC<DataGridProps> = ({ data, isLoading }) => {
    if (isLoading) {
        return (
            <div className="flex items-center justify-center p-20 text-zinc-500">
                Loading data...
            </div>
        );
    }

    if (data.length === 0) {
        return (
            <div className="flex items-center justify-center p-20 text-zinc-500">
                No records found.
            </div>
        );
    }

    // Auto-detect columns from first row
    const columns = Object.keys(data[0]);

    return (
        <div className="overflow-x-auto w-full bg-background transition-colors duration-300">
            <table className="w-full text-left text-sm text-foreground/80">
                <thead className="bg-muted text-[10px] uppercase font-black text-muted-foreground sticky top-0 tracking-widest z-10">
                    <tr>
                        {columns.map((col) => (
                            <th key={col} className="px-4 py-3 whitespace-nowrap border-b border-border">
                                {col.replace(/_/g, " ")}
                            </th>
                        ))}
                    </tr>
                </thead>
                <tbody className="divide-y divide-border/50">
                    {data.map((row, i) => (
                        <tr key={i} className="hover:bg-accent/50 transition-colors">
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
        </div>
    );
};
