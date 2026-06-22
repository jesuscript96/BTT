"use client";

import React, { useCallback, useEffect, useState, type CSSProperties } from "react";
import {
  LayoutDashboard, KeyRound, Activity as ActivityIcon, CreditCard, FlaskConical,
  BookOpen, Plus, Trash2, Copy, Check, ArrowUpRight, AlertTriangle,
} from "lucide-react";
import {
  consoleApi, type Overview, type KeyInfo, type UsageReport, type Billing,
  type CreatedKey, type Activity,
} from "@/lib/api_console";

// ── shared styles (match the Edgecute design tokens) ────────────────────────
const card: CSSProperties = {
  background: "var(--color-ec-bg-surface)",
  border: "0.5px solid var(--color-ec-border)",
  borderRadius: 8,
  padding: 20,
};
const label: CSSProperties = {
  fontSize: 11, textTransform: "uppercase", letterSpacing: 0.5,
  color: "var(--color-ec-text-secondary)",
};
const big: CSSProperties = { fontSize: 26, fontWeight: 700, color: "var(--color-ec-text-high)" };
const btn: CSSProperties = {
  display: "inline-flex", alignItems: "center", gap: 6, padding: "8px 14px",
  borderRadius: 6, fontSize: 13, fontWeight: 600, cursor: "pointer", border: "none",
  background: "var(--color-ec-bg-elevated)", color: "var(--color-ec-text-primary)",
};
const btnPrimary: CSSProperties = { ...btn, background: "var(--color-ec-copper)", color: "#fff" };
const btnDanger: CSSProperties = { ...btn, background: "transparent", color: "var(--color-ec-loss)", border: "0.5px solid var(--color-ec-border)" };

function fmtDate(ts: number | null | undefined): string {
  if (!ts) return "—";
  return new Date(ts * 1000).toLocaleString();
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      style={{ ...btn, padding: "6px 10px" }}
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text);
          setCopied(true);
          setTimeout(() => setCopied(false), 1500);
        } catch { /* clipboard unavailable */ }
      }}
    >
      {copied ? <Check size={14} /> : <Copy size={14} />} {copied ? "Copiado" : "Copiar"}
    </button>
  );
}

function Stat({ label: l, value }: { label: string; value: React.ReactNode }) {
  return (
    <div style={card}>
      <div style={label}>{l}</div>
      <div style={big}>{value}</div>
    </div>
  );
}

function ActivityList({ items }: { items: Activity[] }) {
  if (!items.length) return <div style={{ color: "var(--color-ec-text-muted)", fontSize: 13 }}>Sin actividad todavía.</div>;
  return (
    <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
      <thead>
        <tr>
          {["Fecha", "Módulo", "Acción", "Ticker-días", "Trades", "Key"].map((h) => (
            <th key={h} style={{ textAlign: "left", padding: "8px 10px", borderBottom: "0.5px solid var(--color-ec-border)", color: "var(--color-ec-text-secondary)", fontWeight: 500 }}>{h}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {items.map((a, i) => (
          <tr key={i}>
            <td style={td}>{fmtDate(a.ts)}</td>
            <td style={td}>{a.module}</td>
            <td style={td}>{a.action}</td>
            <td style={td}>{a.ticker_days}</td>
            <td style={td}>{a.trades}</td>
            <td style={{ ...td, fontFamily: "monospace" }}>{a.key_prefix}…</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
const td: CSSProperties = { padding: "8px 10px", borderBottom: "0.5px solid var(--color-ec-border)", color: "var(--color-ec-text-primary)" };

// ── tabs ─────────────────────────────────────────────────────────────────────
type TabId = "overview" | "keys" | "usage" | "billing" | "playground" | "docs";
const TABS: Array<{ id: TabId; label: string; icon: React.ReactNode }> = [
  { id: "overview", label: "Resumen", icon: <LayoutDashboard size={16} /> },
  { id: "keys", label: "API Keys", icon: <KeyRound size={16} /> },
  { id: "usage", label: "Uso", icon: <ActivityIcon size={16} /> },
  { id: "billing", label: "Facturación", icon: <CreditCard size={16} /> },
  { id: "playground", label: "Playground", icon: <FlaskConical size={16} /> },
  { id: "docs", label: "Docs", icon: <BookOpen size={16} /> },
];

export function ApiConsole() {
  const [tab, setTab] = useState<TabId>("overview");
  return (
    <div style={{ padding: "28px 32px", maxWidth: 1100, margin: "0 auto", fontFamily: "var(--font-sans)" }}>
      <h1 style={{ fontFamily: "var(--font-serif)", fontSize: 26, color: "var(--color-ec-text-high)", margin: 0 }}>
        Edgecute API
      </h1>
      <p style={{ color: "var(--color-ec-text-secondary)", marginTop: 4, fontSize: 14 }}>
        Gestiona tus API keys, uso, facturación y prueba la API.
      </p>

      <div style={{ display: "flex", gap: 4, margin: "20px 0", borderBottom: "0.5px solid var(--color-ec-border)" }}>
        {TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            style={{
              display: "flex", alignItems: "center", gap: 7, padding: "10px 14px",
              background: "transparent", border: "none", cursor: "pointer", fontSize: 13,
              fontWeight: tab === t.id ? 600 : 500,
              color: tab === t.id ? "var(--color-ec-text-high)" : "var(--color-ec-text-secondary)",
              borderBottom: tab === t.id ? "2px solid var(--color-ec-copper)" : "2px solid transparent",
            }}
          >
            {t.icon} {t.label}
          </button>
        ))}
      </div>

      {tab === "overview" && <OverviewTab onGoKeys={() => setTab("keys")} />}
      {tab === "keys" && <KeysTab />}
      {tab === "usage" && <UsageTab />}
      {tab === "billing" && <BillingTab />}
      {tab === "playground" && <PlaygroundTab />}
      {tab === "docs" && <DocsTab />}
    </div>
  );
}

// ── Overview ─────────────────────────────────────────────────────────────────
function OverviewTab({ onGoKeys }: { onGoKeys: () => void }) {
  const [data, setData] = useState<Overview | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { consoleApi.overview().then(setData).catch((e) => setErr(String(e.message))); }, []);
  if (err) return <ErrorBox msg={err} />;
  if (!data) return <Loading />;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px,1fr))", gap: 12 }}>
        <Stat label="Plan" value={data.plan.name} />
        <Stat label={`Ticker-días (${data.usage_period.label})`} value={data.usage_period.ticker_days} />
        <Stat label="Backtests" value={data.usage_period.runs} />
        <Stat label="API keys activas" value={data.keys.active} />
      </div>

      <div style={card}>
        <div style={{ ...label, marginBottom: 10 }}>Primeros pasos</div>
        {data.onboarding.map((s) => (
          <div key={s.id} style={{ display: "flex", alignItems: "center", gap: 10, padding: "6px 0", fontSize: 14, color: "var(--color-ec-text-primary)" }}>
            <span style={{
              width: 18, height: 18, borderRadius: "50%", display: "inline-flex", alignItems: "center", justifyContent: "center",
              background: s.done ? "var(--color-ec-profit)" : "transparent", border: s.done ? "none" : "1px solid var(--color-ec-border)",
            }}>{s.done ? <Check size={12} color="#fff" /> : null}</span>
            <span style={{ textDecoration: s.done ? "line-through" : "none", color: s.done ? "var(--color-ec-text-muted)" : "var(--color-ec-text-primary)" }}>{s.label}</span>
          </div>
        ))}
        {data.keys.total === 0 && (
          <button style={{ ...btnPrimary, marginTop: 10 }} onClick={onGoKeys}><Plus size={15} /> Crear API key</button>
        )}
      </div>

      <div style={card}>
        <div style={{ ...label, marginBottom: 12 }}>Actividad reciente</div>
        <ActivityList items={data.activity} />
      </div>
    </div>
  );
}

// ── API Keys ─────────────────────────────────────────────────────────────────
function KeysTab() {
  const [keys, setKeys] = useState<KeyInfo[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [newLabel, setNewLabel] = useState("");
  const [isTest, setIsTest] = useState(true);
  const [created, setCreated] = useState<CreatedKey | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    consoleApi.listKeys().then((r) => setKeys(r.keys)).catch((e) => setErr(String(e.message)));
  }, []);
  useEffect(load, [load]);

  const create = async () => {
    setBusy(true);
    try {
      const res = await consoleApi.createKey(newLabel.trim() || null, isTest);
      setCreated(res);
      setCreating(false);
      setNewLabel("");
      load();
    } catch (e) { setErr(String((e as Error).message)); } finally { setBusy(false); }
  };

  const revoke = async (id: string) => {
    if (!window.confirm("¿Revocar esta API key? Las apps que la usen dejarán de funcionar.")) return;
    try { await consoleApi.revokeKey(id); load(); } catch (e) { setErr(String((e as Error).message)); }
  };

  if (err) return <ErrorBox msg={err} />;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {created && (
        <div style={{ ...card, border: "1px solid var(--color-ec-copper)", background: "var(--color-ec-bg-elevated)" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, color: "var(--color-ec-copper-text)", fontWeight: 600, marginBottom: 8 }}>
            <AlertTriangle size={16} /> Copia tu API key ahora — no se mostrará otra vez.
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <code style={{ flex: 1, fontFamily: "monospace", fontSize: 13, padding: "10px 12px", background: "var(--color-ec-bg-base)", borderRadius: 6, color: "var(--color-ec-text-high)", overflowX: "auto" }}>{created.token}</code>
            <CopyButton text={created.token} />
          </div>
          <button style={{ ...btn, marginTop: 10 }} onClick={() => setCreated(null)}>Hecho</button>
        </div>
      )}

      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div style={{ color: "var(--color-ec-text-secondary)", fontSize: 13 }}>
          Las keys autentican tu app contra la API. <code>ek_test_</code> = sandbox; <code>ek_live_</code> = producción.
        </div>
        {!creating && <button style={btnPrimary} onClick={() => setCreating(true)}><Plus size={15} /> Nueva key</button>}
      </div>

      {creating && (
        <div style={{ ...card, display: "flex", gap: 12, alignItems: "flex-end", flexWrap: "wrap" }}>
          <div style={{ flex: 1, minWidth: 200 }}>
            <div style={label}>Etiqueta (opcional)</div>
            <input value={newLabel} onChange={(e) => setNewLabel(e.target.value)} placeholder="p.ej. Mi app local"
              style={{ width: "100%", marginTop: 6, padding: "9px 11px", borderRadius: 6, border: "0.5px solid var(--color-ec-border)", background: "var(--color-ec-bg-base)", color: "var(--color-ec-text-high)", fontSize: 13 }} />
          </div>
          <label style={{ display: "flex", alignItems: "center", gap: 7, fontSize: 13, color: "var(--color-ec-text-primary)" }}>
            <input type="checkbox" checked={isTest} onChange={(e) => setIsTest(e.target.checked)} /> Sandbox (ek_test_)
          </label>
          <button style={btnPrimary} disabled={busy} onClick={create}>{busy ? "Creando…" : "Crear"}</button>
          <button style={btn} onClick={() => setCreating(false)}>Cancelar</button>
        </div>
      )}

      {!keys ? <Loading /> : keys.length === 0 ? (
        <div style={{ ...card, color: "var(--color-ec-text-muted)" }}>Aún no tienes API keys.</div>
      ) : (
        <div style={card}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <thead><tr>
              {["Key", "Etiqueta", "Tipo", "Estado", "Creada", "Último uso", ""].map((h) => (
                <th key={h} style={{ textAlign: "left", padding: "8px 10px", borderBottom: "0.5px solid var(--color-ec-border)", color: "var(--color-ec-text-secondary)", fontWeight: 500 }}>{h}</th>
              ))}
            </tr></thead>
            <tbody>
              {keys.map((k) => (
                <tr key={k.id}>
                  <td style={{ ...td, fontFamily: "monospace" }}>{k.prefix}…</td>
                  <td style={td}>{k.label ?? "—"}</td>
                  <td style={td}>{k.is_test ? "sandbox" : "live"}</td>
                  <td style={{ ...td, color: k.status === "active" ? "var(--color-ec-profit)" : "var(--color-ec-loss)" }}>{k.status}</td>
                  <td style={td}>{fmtDate(k.created_at)}</td>
                  <td style={td}>{fmtDate(k.last_used_at)}</td>
                  <td style={td}>{k.status === "active" && <button style={btnDanger} onClick={() => revoke(k.id)}><Trash2 size={14} /> Revocar</button>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ── Usage ────────────────────────────────────────────────────────────────────
function UsageTab() {
  const [data, setData] = useState<UsageReport | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { consoleApi.usage().then(setData).catch((e) => setErr(String(e.message))); }, []);
  if (err) return <ErrorBox msg={err} />;
  if (!data) return <Loading />;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px,1fr))", gap: 12 }}>
        <Stat label="Backtests (mes)" value={data.this_month.runs} />
        <Stat label="Ticker-días (mes)" value={data.this_month.ticker_days} />
        <Stat label="Ticker-días (total)" value={data.all_time.ticker_days} />
        <Stat label="Trades (total)" value={data.all_time.trades} />
      </div>
      <div style={card}>
        <div style={{ ...label, marginBottom: 12 }}>Actividad</div>
        <ActivityList items={data.activity} />
      </div>
    </div>
  );
}

// ── Billing ──────────────────────────────────────────────────────────────────
function BillingTab() {
  const [data, setData] = useState<Billing | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { consoleApi.billing().then(setData).catch((e) => setErr(String(e.message))); }, []);
  if (err) return <ErrorBox msg={err} />;
  if (!data) return <Loading />;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
      <div style={{ ...card, display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 12 }}>
        <div>
          <div style={label}>Plan actual</div>
          <div style={big}>{data.plan.name}</div>
          <div style={{ color: "var(--color-ec-text-secondary)", fontSize: 13, marginTop: 4 }}>
            Límite: {data.plan.limits.max_ticker_days_per_run.toLocaleString()} ticker-días/backtest · {data.plan.limits.rate_limit_rpm} req/min
          </div>
        </div>
        <a href={data.upgrade_url ?? undefined} target="_blank" rel="noreferrer"
          style={{ ...btnPrimary, opacity: data.upgrade_url ? 1 : 0.6, pointerEvents: data.upgrade_url ? "auto" : "none", textDecoration: "none" }}>
          Mejorar plan <ArrowUpRight size={15} />
        </a>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px,1fr))", gap: 12 }}>
        <Stat label="Ticker-días (mes)" value={data.usage_this_month.ticker_days} />
        <Stat label="Backtests (mes)" value={data.usage_this_month.runs} />
      </div>

      <div style={card}>
        <div style={{ ...label, marginBottom: 12 }}>Facturas</div>
        {data.invoices.length === 0 ? (
          <div style={{ color: "var(--color-ec-text-muted)", fontSize: 13 }}>{data.stripe.note}</div>
        ) : null}
      </div>
    </div>
  );
}

// ── Playground ───────────────────────────────────────────────────────────────
const SAMPLE = JSON.stringify({
  name: "VWAP fade short", bias: "short", apply_day: "gap_day",
  entry_logic: { timeframe: "1m", root_condition: { type: "group", operator: "AND",
    conditions: [{ type: "indicator_comparison", source: { name: "Bar Close" }, comparator: "CROSSES_BELOW", target: { name: "VWAP" } }] } },
  risk_management: { use_hard_stop: true, hard_stop: { type: "Percentage", value: 3.0 } },
}, null, 2);

function PlaygroundTab() {
  const [text, setText] = useState(SAMPLE);
  const [result, setResult] = useState<{ valid: boolean; errors: Array<{ path: string; message: string }> } | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const validate = async () => {
    setErr(null); setResult(null); setBusy(true);
    let parsed: unknown;
    try { parsed = JSON.parse(text); } catch { setErr("JSON inválido."); setBusy(false); return; }
    try { setResult(await consoleApi.playgroundValidate(parsed)); }
    catch (e) { setErr(String((e as Error).message)); } finally { setBusy(false); }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div style={{ color: "var(--color-ec-text-secondary)", fontSize: 13 }}>
        Valida una estrategia contra el esquema real (sin ejecutar nada, sin gastar uso).
      </div>
      <textarea value={text} onChange={(e) => setText(e.target.value)} spellCheck={false}
        style={{ width: "100%", minHeight: 280, fontFamily: "monospace", fontSize: 12.5, padding: 14, borderRadius: 8,
          border: "0.5px solid var(--color-ec-border)", background: "var(--color-ec-bg-base)", color: "var(--color-ec-text-high)" }} />
      <div><button style={btnPrimary} disabled={busy} onClick={validate}>{busy ? "Validando…" : "Validar estrategia"}</button></div>
      {err && <ErrorBox msg={err} />}
      {result && (
        <div style={{ ...card, border: `1px solid ${result.valid ? "var(--color-ec-profit)" : "var(--color-ec-loss)"}` }}>
          <div style={{ fontWeight: 600, color: result.valid ? "var(--color-ec-profit)" : "var(--color-ec-loss)", marginBottom: result.valid ? 0 : 10 }}>
            {result.valid ? "✓ Estrategia válida" : "✗ Estrategia inválida"}
          </div>
          {!result.valid && result.errors.map((e, i) => (
            <div key={i} style={{ fontSize: 13, color: "var(--color-ec-text-primary)", padding: "3px 0" }}>
              <code style={{ color: "var(--color-ec-copper-text)" }}>{e.path}</code>: {e.message}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Docs ─────────────────────────────────────────────────────────────────────
const MCP_SNIPPET = `{
  "mcpServers": {
    "edgecute": {
      "command": "npx",
      "args": ["-y", "@edgecute/mcp"],
      "env": { "EDGECUTE_API_KEY": "ek_test_…" }
    }
  }
}`;

function DocsTab() {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div style={card}>
        <div style={{ ...label, marginBottom: 8 }}>Documentación</div>
        <p style={{ color: "var(--color-ec-text-primary)", fontSize: 14, marginTop: 0 }}>
          Construye tu app en local con el MCP de Edgecute en Cursor / Claude Code; en runtime tu app
          llama a la API directamente.
        </p>
        <a href="https://docs.edgecute.com" target="_blank" rel="noreferrer" style={{ ...btnPrimary, textDecoration: "none" }}>
          Abrir documentación <ArrowUpRight size={15} />
        </a>
      </div>
      <div style={card}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
          <div style={label}>Instalar el MCP (.cursor/mcp.json)</div>
          <CopyButton text={MCP_SNIPPET} />
        </div>
        <pre style={{ margin: 0, fontFamily: "monospace", fontSize: 12.5, padding: 14, borderRadius: 8, overflowX: "auto",
          background: "var(--color-ec-bg-base)", color: "var(--color-ec-text-high)" }}>{MCP_SNIPPET}</pre>
      </div>
    </div>
  );
}

// ── shared small bits ────────────────────────────────────────────────────────
function Loading() { return <div style={{ color: "var(--color-ec-text-muted)", fontSize: 13, padding: 20 }}>Cargando…</div>; }
function ErrorBox({ msg }: { msg: string }) {
  return <div style={{ ...card, border: "0.5px solid var(--color-ec-loss)", color: "var(--color-ec-loss)", fontSize: 13 }}>{msg}</div>;
}
