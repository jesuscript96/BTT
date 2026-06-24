"use client";

/**
 * Frontend entitlements hook.
 *
 * Reads tier + policy + usage from GET /api/users/me/entitlements (Phase 1
 * backend) and exposes can/limit/used/remaining helpers. A module-level cache
 * dedupes the fetch across components (SWR-lite, no extra dependency).
 *
 * Optimistic by design: while loading, on error, or for unknown features the
 * helpers default to "allowed / unlimited" so the UI is never blocked during
 * the MVP (everything is open). Real restrictions only appear once the backend
 * policy returns non-permissive values.
 */
import { useEffect, useState } from "react";

import { apiRequest } from "@/lib/api";

export type FeatureValue = boolean | number;

export interface Entitlements {
  tier: string;
  entitlements: Record<string, FeatureValue>;
  usage: Record<string, number>;
}

// API_BASE already ends with /api, so the path is relative to that.
const ENDPOINT = "/users/me/entitlements";

// Optimistic fallback used while loading or on error (MVP: all open).
const OPTIMISTIC: Entitlements = { tier: "Free", entitlements: {}, usage: {} };

// ─── Shared cache (dedupe one fetch across all mounted components) ──────────
let _cache: Entitlements | null = null;
let _inflight: Promise<Entitlements> | null = null;
const _subscribers = new Set<(e: Entitlements) => void>();

function fetchEntitlements(): Promise<Entitlements> {
  if (_inflight) return _inflight;
  _inflight = apiRequest<Entitlements>(ENDPOINT)
    .then((data) => {
      _cache = data;
      _subscribers.forEach((fn) => fn(data));
      return data;
    })
    .finally(() => {
      _inflight = null;
    });
  return _inflight;
}

export interface UseEntitlements {
  data: Entitlements;
  loading: boolean;
  tier: string;
  isAdmin: () => boolean;
  can: (feature: string) => boolean;
  limit: (feature: string) => number;
  used: (feature: string) => number;
  remaining: (feature: string) => number;
  refresh: () => Promise<void>;
}

export function useEntitlements(): UseEntitlements {
  const [data, setData] = useState<Entitlements | null>(_cache);
  const [loading, setLoading] = useState<boolean>(_cache === null);

  useEffect(() => {
    let active = true;
    const onUpdate = (e: Entitlements) => {
      if (active) setData(e);
    };
    _subscribers.add(onUpdate);

    if (_cache) {
      setData(_cache);
      setLoading(false);
    } else {
      fetchEntitlements().finally(() => {
        if (active) setLoading(false);
      });
    }

    return () => {
      active = false;
      _subscribers.delete(onUpdate);
    };
  }, []);

  const eff = data ?? OPTIMISTIC;

  const can = (feature: string): boolean => {
    const v = eff.entitlements[feature];
    if (v === undefined) return true; // optimistic: loading / unknown feature
    if (typeof v === "boolean") return v;
    return v === -1 || v > 0; // numeric: unlimited or has remaining quota
  };

  const limit = (feature: string): number => {
    const v = eff.entitlements[feature];
    return typeof v === "number" ? v : -1; // unknown / boolean -> unlimited
  };

  const used = (feature: string): number => eff.usage[feature] ?? 0;

  const remaining = (feature: string): number => {
    const lim = limit(feature);
    if (lim === -1) return Infinity;
    return Math.max(0, lim - used(feature));
  };

  const isAdmin = (): boolean => eff.tier === "Admin";

  const refresh = async (): Promise<void> => {
    _cache = null;
    await fetchEntitlements();
  };

  return {
    data: eff,
    loading,
    tier: eff.tier,
    isAdmin,
    can,
    limit,
    used,
    remaining,
    refresh,
  };
}
