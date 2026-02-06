"use client";

import React, { useEffect, useState } from 'react';
import { Strategy } from '@/types/strategy';
import { Loader2, Trash2 } from 'lucide-react';

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
            const response = await fetch('http://localhost:8000/api/strategies/');
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
            const response = await fetch(`http://localhost:8000/api/strategies/${id}`, {
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
            <div className="bg-red-50 border border-red-200 rounded-lg p-4 text-red-700 text-sm">
                Error loading strategies: {error}
            </div>
        );
    }

    if (strategies.length === 0) {
        return (
            <div className="bg-zinc-50 border border-zinc-200 rounded-lg p-8 text-center">
                <p className="text-zinc-500 text-sm font-medium">No strategies created yet. Create your first one above!</p>
            </div>
        );
    }

    return (
        <div className="bg-white border border-zinc-200 rounded-xl shadow-sm overflow-hidden">
            <div className="px-6 py-4 border-b border-zinc-200">
                <h3 className="text-sm font-black text-zinc-900 uppercase tracking-widest">Saved Strategies</h3>
                <p className="text-xs text-zinc-500 mt-1">{strategies.length} strateg{strategies.length === 1 ? 'y' : 'ies'} found</p>
            </div>

            <div className="overflow-x-auto">
                <table className="w-full">
                    <thead className="bg-zinc-50 border-b border-zinc-200">
                        <tr>
                            <th className="px-6 py-3 text-left text-[10px] font-black text-zinc-500 uppercase tracking-widest">Name</th>
                            <th className="px-6 py-3 text-left text-[10px] font-black text-zinc-500 uppercase tracking-widest">Description</th>
                            <th className="px-6 py-3 text-left text-[10px] font-black text-zinc-500 uppercase tracking-widest">Entry Groups</th>
                            <th className="px-6 py-3 text-left text-[10px] font-black text-zinc-500 uppercase tracking-widest">Created</th>
                            <th className="px-6 py-3 text-right text-[10px] font-black text-zinc-500 uppercase tracking-widest">Actions</th>
                        </tr>
                    </thead>
                    <tbody className="divide-y divide-zinc-100">
                        {strategies.map((strategy) => (
                            <tr key={strategy.id} className="hover:bg-zinc-50 transition-colors">
                                <td className="px-6 py-4">
                                    <div className="text-sm font-bold text-zinc-900">{strategy.name}</div>
                                </td>
                                <td className="px-6 py-4">
                                    <div className="text-sm text-zinc-600 max-w-md truncate">
                                        {strategy.description || <span className="text-zinc-400 italic">No description</span>}
                                    </div>
                                </td>
                                <td className="px-6 py-4">
                                    <div className="text-sm text-zinc-600">
                                        {strategy.entry_logic?.length || 0} group{strategy.entry_logic?.length !== 1 ? 's' : ''}
                                    </div>
                                </td>
                                <td className="px-6 py-4">
                                    <div className="text-sm text-zinc-600">
                                        {strategy.created_at ? new Date(strategy.created_at).toLocaleDateString() : 'N/A'}
                                    </div>
                                </td>
                                <td className="px-6 py-4 text-right">
                                    <button
                                        onClick={() => strategy.id && handleDelete(strategy.id)}
                                        className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-bold text-red-600 hover:bg-red-50 rounded-lg transition-colors"
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
