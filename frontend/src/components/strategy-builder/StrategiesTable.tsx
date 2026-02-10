"use client";

import React, { useEffect, useState } from 'react';
import { Strategy } from '@/types/strategy';
import { Loader2, Trash2 } from 'lucide-react';
import { API_URL } from '@/config/constants';

interface Props {
    refreshTrigger?: number;
}

export const StrategiesTable = ({ refreshTrigger }: Props) => {
    const [strategies, setStrategies] = useState<Strategy[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    const fetchStrategies = async () => {
        setLoading(true);
        setError(null);
        try {
            const response = await fetch(`${API_URL}/strategies/`);
            if (!response.ok) throw new Error('Failed to fetch strategies');
            const data = await response.json();
            setStrategies(data);
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Unknown error');
        } finally {
            setLoading(false);
        }
    };

    const handleDelete = async (id: string) => {
        if (!confirm('Are you sure you want to delete this strategy?')) return;

        try {
            const response = await fetch(`${API_URL}/strategies/${id}`, {
                method: 'DELETE'
            });
            if (!response.ok) throw new Error('Failed to delete');
            fetchStrategies(); // Refresh list
        } catch (err) {
            alert('Error deleting strategy');
        }
    };

    useEffect(() => {
        fetchStrategies();
    }, [refreshTrigger]);

    if (loading) {
        return (
            <div className="flex items-center justify-center py-12">
                <Loader2 className="w-6 h-6 animate-spin text-zinc-400" />
            </div>
        );
    }

    if (error) {
        return (
            <div className="bg-red-500/10 border border-red-500/20 rounded-xl p-4 text-red-500 text-sm font-bold">
                Error loading strategies: {error}
            </div>
        );
    }

    if (strategies.length === 0) {
        return (
            <div className="bg-muted/30 border border-border rounded-xl p-8 text-center transition-all">
                <p className="text-muted-foreground/60 text-[10px] font-black uppercase tracking-widest">No strategies created yet. Create your first one above!</p>
            </div>
        );
    }

    return (
        <div className="bg-card border border-border rounded-xl shadow-sm overflow-hidden transition-all">
            <div className="px-6 py-5 border-b border-border/50">
                <h3 className="text-[10px] font-black text-foreground uppercase tracking-widest">Saved Strategies</h3>
                <p className="text-[10px] text-muted-foreground/50 font-black uppercase tracking-widest mt-1.5">{strategies.length} strateg{strategies.length === 1 ? 'y' : 'ies'} found</p>
            </div>

            <div className="overflow-x-auto">
                <table className="w-full">
                    <thead className="bg-muted/30 border-b border-border/50">
                        <tr>
                            <th className="px-6 py-3 text-left text-[10px] font-black text-muted-foreground uppercase tracking-widest opacity-60">Name</th>
                            <th className="px-6 py-3 text-left text-[10px] font-black text-muted-foreground uppercase tracking-widest opacity-60">Description</th>
                            <th className="px-6 py-3 text-left text-[10px] font-black text-muted-foreground uppercase tracking-widest opacity-60">Entry Groups</th>
                            <th className="px-6 py-3 text-left text-[10px] font-black text-muted-foreground uppercase tracking-widest opacity-60">Created</th>
                            <th className="px-6 py-3 text-right text-[10px] font-black text-muted-foreground uppercase tracking-widest opacity-60">Actions</th>
                        </tr>
                    </thead>
                    <tbody className="divide-y divide-border/30">
                        {strategies.map((strategy) => (
                            <tr key={strategy.id} className="hover:bg-muted/20 transition-colors group">
                                <td className="px-6 py-4">
                                    <div className="text-sm font-bold text-foreground">{strategy.name}</div>
                                </td>
                                <td className="px-6 py-4">
                                    <div className="text-sm text-muted-foreground font-medium max-w-md truncate opacity-80">
                                        {strategy.description || <span className="text-muted-foreground/30 italic">No description</span>}
                                    </div>
                                </td>
                                <td className="px-6 py-4">
                                    <div className="text-[10px] font-black text-muted-foreground uppercase tracking-widest opacity-60">
                                        {strategy.entry_logic?.length || 0} group{strategy.entry_logic?.length !== 1 ? 's' : ''}
                                    </div>
                                </td>
                                <td className="px-6 py-4">
                                    <div className="text-[10px] font-black text-muted-foreground uppercase tracking-widest opacity-60">
                                        {strategy.created_at ? new Date(strategy.created_at).toLocaleDateString() : 'N/A'}
                                    </div>
                                </td>
                                <td className="px-6 py-4 text-right">
                                    <button
                                        onClick={() => strategy.id && handleDelete(strategy.id)}
                                        className="inline-flex items-center gap-1.5 px-3 py-1.5 text-[10px] font-black text-red-500/60 uppercase tracking-widest hover:text-red-500 hover:bg-red-500/10 rounded-lg transition-all opacity-0 group-hover:opacity-100"
                                    >
                                        <Trash2 className="w-3 h-3" />
                                        Delete
                                    </button>
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
        </div>
    );
};
