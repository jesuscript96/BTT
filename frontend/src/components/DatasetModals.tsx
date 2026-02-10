"use client";

import React, { useState, useEffect } from "react";
import { X, Save, FolderOpen, Trash2 } from "lucide-react";

import { API_URL } from '@/config/constants';

export const SaveDatasetModal = ({ isOpen, onClose, filters, rules }: any) => {
    const [name, setName] = useState("");
    const [isSaving, setIsSaving] = useState(false);

    if (!isOpen) return null;

    const handleSave = async () => {
        if (!name.trim()) return;
        setIsSaving(true);
        try {
            const res = await fetch(`${API_URL}/queries/`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    name,
                    filters: { ...filters, rules }
                }),
            });
            if (res.ok) {
                onClose();
                setName("");
            }
        } catch (error) {
            console.error("Error saving dataset:", error);
        } finally {
            setIsSaving(false);
        }
    };

    return (
        <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/50 backdrop-blur-sm p-4">
            <div className="bg-white rounded-2xl shadow-2xl w-full max-w-md overflow-hidden border border-zinc-200">
                <div className="p-6 border-b border-zinc-100 flex items-center justify-between bg-zinc-50">
                    <h3 className="text-lg font-black text-zinc-800 uppercase tracking-tight">Save Dataset</h3>
                    <button onClick={onClose} className="p-2 hover:bg-zinc-200 rounded-full transition-colors">
                        <X className="h-5 w-5 text-zinc-500" />
                    </button>
                </div>
                <div className="p-8 space-y-4">
                    <div className="space-y-2">
                        <label className="text-[10px] font-black text-zinc-400 uppercase tracking-widest pl-1">Dataset Name</label>
                        <input
                            autoFocus
                            type="text"
                            value={name}
                            onChange={(e) => setName(e.target.value)}
                            placeholder="e.g., Small Cap Top Gappers"
                            className="w-full bg-zinc-50 border border-zinc-200 rounded-xl px-4 py-3 text-sm focus:border-blue-500 focus:ring-2 focus:ring-blue-500/10 outline-none transition-all font-medium"
                        />
                    </div>
                </div>
                <div className="p-6 bg-zinc-50 border-t border-zinc-100 flex justify-end gap-3">
                    <button onClick={onClose} className="px-6 py-2.5 text-sm font-bold text-zinc-500 hover:text-zinc-700 transition-colors">Cancel</button>
                    <button
                        onClick={handleSave}
                        disabled={isSaving || !name.trim()}
                        className="bg-blue-600 hover:bg-blue-700 text-white px-8 py-2.5 rounded-xl text-sm font-black tracking-tight transition-all shadow-lg active:scale-95 disabled:opacity-50 flex items-center gap-2"
                    >
                        <Save className="h-4 w-4" />
                        {isSaving ? "Saving..." : "Save Dataset"}
                    </button>
                </div>
            </div>
        </div>
    );
};

export const LoadDatasetModal = ({ isOpen, onClose, onLoad }: any) => {
    const [queries, setQueries] = useState<any[]>([]);
    const [isLoading, setIsLoading] = useState(true);

    useEffect(() => {
        if (isOpen) {
            fetchQueries();
        }
    }, [isOpen]);

    const fetchQueries = async () => {
        setIsLoading(true);
        try {
            const res = await fetch(`${API_URL}/queries/`);
            if (res.ok) {
                const data = await res.json();
                setQueries(data);
            }
        } catch (error) {
            console.error("Error fetching datasets:", error);
        } finally {
            setIsLoading(false);
        }
    };

    const handleDelete = async (id: string, e: React.MouseEvent) => {
        e.stopPropagation();
        if (!confirm("Delete this dataset?")) return;
        try {
            await fetch(`${API_URL}/queries/${id}`, { method: "DELETE" });
            setQueries(prev => prev.filter(q => q.id !== id));
        } catch (error) {
            console.error("Error deleting dataset:", error);
        }
    };

    if (!isOpen) return null;

    return (
        <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/50 backdrop-blur-sm p-4">
            <div className="bg-white rounded-2xl shadow-2xl w-full max-w-2xl overflow-hidden border border-zinc-200">
                <div className="p-6 border-b border-zinc-100 flex items-center justify-between bg-zinc-50">
                    <h3 className="text-lg font-black text-zinc-800 uppercase tracking-tight">Load Dataset</h3>
                    <button onClick={onClose} className="p-2 hover:bg-zinc-200 rounded-full transition-colors">
                        <X className="h-5 w-5 text-zinc-500" />
                    </button>
                </div>
                <div className="p-4 max-h-[60vh] overflow-y-auto scrollbar-thin scrollbar-track-zinc-100 scrollbar-thumb-zinc-300">
                    {isLoading ? (
                        <div className="p-12 text-center text-zinc-400 font-bold uppercase tracking-widest text-xs animate-pulse">Loading Datasets...</div>
                    ) : queries.length === 0 ? (
                        <div className="p-12 text-center text-zinc-400 font-bold uppercase tracking-widest text-xs">No saved datasets found</div>
                    ) : (
                        <div className="grid grid-cols-1 gap-2">
                            {queries.map((q) => (
                                <div
                                    key={q.id}
                                    onClick={() => {
                                        onLoad(q.filters);
                                        onClose();
                                    }}
                                    className="group p-4 rounded-xl border border-zinc-100 hover:border-blue-400 hover:bg-blue-50/50 cursor-pointer transition-all flex items-center justify-between shadow-sm"
                                >
                                    <div className="flex items-center gap-4">
                                        <div className="p-2.5 bg-zinc-100 group-hover:bg-blue-100 rounded-xl transition-colors">
                                            <FolderOpen className="h-5 w-5 text-zinc-500 group-hover:text-blue-600" />
                                        </div>
                                        <div>
                                            <div className="font-bold text-zinc-800 text-sm">{q.name}</div>
                                            <div className="text-[10px] text-zinc-400 font-black uppercase tracking-widest">
                                                {new Date(q.created_at).toLocaleDateString()}
                                            </div>
                                        </div>
                                    </div>
                                    <button
                                        onClick={(e) => handleDelete(q.id, e)}
                                        className="p-2 opacity-0 group-hover:opacity-100 text-zinc-300 hover:text-red-500 hover:bg-red-50 rounded-lg transition-all"
                                    >
                                        <Trash2 className="h-4 w-4" />
                                    </button>
                                </div>
                            ))}
                        </div>
                    )}
                </div>
                <div className="p-6 bg-zinc-50 border-t border-zinc-100 flex justify-end">
                    <button onClick={onClose} className="px-6 py-2.5 text-sm font-bold text-zinc-500 hover:text-zinc-700 transition-colors">Close</button>
                </div>
            </div>
        </div>
    );
};
