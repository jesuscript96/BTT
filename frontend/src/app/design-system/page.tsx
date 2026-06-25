"use client";

import React, { useState } from "react";
import {
  Search, Plus, Trash2, Download, Settings, Bell, ChevronDown, Filter,
  Sun, Moon, BarChart3, KeyRound,
} from "lucide-react";
import {
  color, font, radius, space, shadow, iconSize,
  Logo, Isotipo,
  Button, IconButton,
  Card, Eyebrow, CardTitle, CardMeta,
  Field, Input, Textarea, Select,
  Pill, Badge, StatusBadge, MethodBadge,
  Dropdown, MenuItem, MenuLabel, MenuSeparator,
  Modal, Tabs, SegmentedControl,
  Stepper, Wizard, type Step,
  Tooltip, Table, Th, Td, Tr,
  Spinner, Loading, LoadingDots, ErrorBox, EmptyState, Skeleton,
  ToastProvider, useToast,
} from "@/components/ui";

// ── page-local layout helpers ───────────────────────────────────────────────
function Section({ id, title, subtitle, children }: { id: string; title: string; subtitle?: string; children: React.ReactNode }) {
  return (
    <section id={id} style={{ scrollMarginTop: 24, marginBottom: 56 }}>
      <div style={{ marginBottom: 18 }}>
        <h2 style={{ fontFamily: font.serif, fontSize: 24, fontWeight: 600, color: color.textHigh, letterSpacing: "-0.3px" }}>{title}</h2>
        {subtitle && <p style={{ fontFamily: font.sans, fontSize: 13, color: color.textSecondary, marginTop: 4 }}>{subtitle}</p>}
      </div>
      {children}
    </section>
  );
}

function Row({ children, label }: { children: React.ReactNode; label?: string }) {
  return (
    <div style={{ marginBottom: 16 }}>
      {label && <div style={{ fontFamily: font.sans, fontSize: 9, fontWeight: 700, textTransform: "uppercase", letterSpacing: "2px", color: color.textMuted, marginBottom: 8 }}>{label}</div>}
      <div style={{ display: "flex", flexWrap: "wrap", gap: 12, alignItems: "center" }}>{children}</div>
    </div>
  );
}

function Swatch({ name, value }: { name: string; value: string }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6, width: 124 }}>
      <div style={{ height: 52, borderRadius: radius.md, background: value, border: `0.5px solid ${color.border}` }} />
      <div>
        <div style={{ fontFamily: font.sans, fontSize: 11, fontWeight: 600, color: color.textPrimary }}>{name}</div>
        <code style={{ fontFamily: font.mono, fontSize: 10, color: color.textMuted }}>{value.replace("var(--color-ec-", "--").replace(")", "")}</code>
      </div>
    </div>
  );
}

const WIZARD_STEPS: Step[] = [
  { key: "universe", label: "Universo" },
  { key: "entry", label: "Entrada" },
  { key: "exit", label: "Salida" },
  { key: "risk", label: "Riesgo" },
  { key: "review", label: "Revisión" },
];

function Showcase() {
  const toast = useToast();
  const [modalOpen, setModalOpen] = useState(false);
  const [tab, setTab] = useState("performance");
  const [seg, setSeg] = useState("curl");
  const [wizStep, setWizStep] = useState(1);
  const [theme, setTheme] = useState<"dark" | "light">("dark");

  const toggleTheme = () => {
    const next = theme === "dark" ? "light" : "dark";
    document.documentElement.classList.toggle("light", next === "light");
    setTheme(next);
  };

  return (
    <div style={{ maxWidth: 920, margin: "0 auto", padding: "32px 32px 120px" }}>
      {/* Header */}
      <header style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
        <Logo size={34} />
        <Button variant="ghost" size="sm" leftIcon={theme === "dark" ? <Moon size={14} /> : <Sun size={14} />} onClick={toggleTheme}>
          {theme === "dark" ? "Dark" : "Light"}
        </Button>
      </header>
      <Eyebrow>Design System v2.0</Eyebrow>
      <h1 style={{ fontFamily: font.serif, fontSize: 38, fontWeight: 600, color: color.textHigh, letterSpacing: "-0.5px", margin: "6px 0 8px" }}>
        Edgecute <span style={{ fontStyle: "italic" }}>styleguide</span>
      </h1>
      <p style={{ fontFamily: font.sans, fontSize: 14, color: color.textSecondary, maxWidth: 560, marginBottom: 40 }}>
        Tokens y componentes canónicos. Todo lo que se construya debe partir de aquí. Cambia el tema arriba a la derecha para verificar que los neutros se adaptan y el cobre/P&L no.
      </p>

      {/* COLORS */}
      <Section id="color" title="Color" subtitle="Cobre = marca. Verde/rojo = P&L. Estos nunca cambian entre temas; solo los neutros.">
        <Row label="Marca">
          <Swatch name="copper" value={color.copper} />
          <Swatch name="copper-bright" value={color.copperBright} />
          <Swatch name="copper-text" value={color.copperText} />
        </Row>
        <Row label="Superficies">
          <Swatch name="bg-sidebar" value={color.bgSidebar} />
          <Swatch name="bg-base" value={color.bgBase} />
          <Swatch name="bg-surface" value={color.bgSurface} />
          <Swatch name="bg-elevated" value={color.bgElevated} />
          <Swatch name="border" value={color.border} />
        </Row>
        <Row label="Texto">
          <Swatch name="text-high" value={color.textHigh} />
          <Swatch name="text-primary" value={color.textPrimary} />
          <Swatch name="text-secondary" value={color.textSecondary} />
          <Swatch name="text-muted" value={color.textMuted} />
        </Row>
        <Row label="Semántico">
          <Swatch name="profit" value={color.profit} />
          <Swatch name="loss" value={color.loss} />
          <Swatch name="warning" value={color.warning} />
          <Swatch name="info" value={color.info} />
        </Row>
      </Section>

      {/* TYPOGRAPHY */}
      <Section id="type" title="Tipografía" subtitle="Fraunces (serif) para títulos · General Sans para UI/cuerpo · mono para datos/código.">
        <Card>
          <div style={{ fontFamily: font.serif, fontSize: 38, fontWeight: 600, color: color.textHigh, letterSpacing: "-0.5px" }}>Fraunces 600 · 38px</div>
          <div style={{ fontFamily: font.serif, fontSize: 24, fontWeight: 600, color: color.textHigh, marginTop: 8 }}>Fraunces 600 · 24px — section title</div>
          <div style={{ fontFamily: font.serif, fontSize: 17, fontWeight: 500, color: color.textHigh, marginTop: 8 }}>Fraunces 500 · 17px — card title <span style={{ fontStyle: "italic" }}>énfasis</span></div>
          <hr style={{ border: "none", borderTop: `0.5px solid ${color.border}`, margin: "16px 0" }} />
          <div style={{ fontFamily: font.sans, fontSize: 13, color: color.textPrimary }}>General Sans 400 · 13px — body / UI text por defecto.</div>
          <div style={{ fontFamily: font.sans, fontSize: 15, fontWeight: 600, color: color.textPrimary, marginTop: 6 }}>General Sans 600 · 15px — valores de filtro (nunca Fraunces).</div>
          <div style={{ fontFamily: font.sans, fontSize: 9, fontWeight: 700, textTransform: "uppercase", letterSpacing: "2px", color: color.textMuted, marginTop: 8 }}>General Sans 700 · 9px · upper — labels</div>
          <code style={{ display: "block", fontFamily: font.mono, fontSize: 12.5, color: color.copper, marginTop: 10 }}>mono · 12.5px — 1,284.50 · GET /v1/backtest</code>
        </Card>
      </Section>

      {/* CARDS */}
      <Section id="cards" title="Cards" subtitle="Normal vs destacada (riel cobre). El título de una card destacada nunca va en cobre.">
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
          <Card>
            <Eyebrow>Bloomberg</Eyebrow>
            <CardTitle style={{ marginTop: 6 }}>Fed mantiene tipos sin cambios</CardTitle>
            <CardMeta style={{ marginTop: 8 }}>hace 2 h · Macro</CardMeta>
          </Card>
          <Card featured>
            <Eyebrow bright>Edgecute</Eyebrow>
            <CardTitle featured style={{ marginTop: 6 }}>Tu estrategia superó el OOS</CardTitle>
            <CardMeta style={{ marginTop: 8 }}>PF 1.84 · degradación 6%</CardMeta>
          </Card>
        </div>
      </Section>

      {/* SCALES */}
      <Section id="scales" title="Espaciado, radio y elevación" subtitle="Rejilla base 4px. Bordes hairline 0.5px. Sombras profundas en dark.">
        <Row label="Espaciado">
          {(["1", "2", "3", "4", "5", "6", "8"] as const).map((k) => (
            <div key={k} style={{ textAlign: "center" }}>
              <div style={{ width: space[k], height: 24, background: color.copper, borderRadius: 2 }} />
              <div style={{ fontFamily: font.mono, fontSize: 10, color: color.textMuted, marginTop: 4 }}>{k}</div>
            </div>
          ))}
        </Row>
        <Row label="Radio">
          {(["xs", "sm", "md", "lg", "xl"] as const).map((k) => (
            <div key={k} style={{ textAlign: "center" }}>
              <div style={{ width: 52, height: 52, background: color.bgElevated, border: `0.5px solid ${color.border}`, borderRadius: radius[k] }} />
              <div style={{ fontFamily: font.mono, fontSize: 10, color: color.textMuted, marginTop: 4 }}>{k}</div>
            </div>
          ))}
        </Row>
        <Row label="Elevación">
          {(["sm", "md", "lg", "xl"] as const).map((k) => (
            <div key={k} style={{ textAlign: "center" }}>
              <div style={{ width: 72, height: 52, background: color.bgSurface, borderRadius: radius.md, boxShadow: shadow[k] }} />
              <div style={{ fontFamily: font.mono, fontSize: 10, color: color.textMuted, marginTop: 8 }}>{k}</div>
            </div>
          ))}
        </Row>
      </Section>

      {/* ICONOGRAPHY */}
      <Section id="icons" title="Iconografía" subtitle="lucide-react, stroke 1.5px. Tamaños 14 / 16 / 18 / 20.">
        <Row>
          {[Search, Plus, Trash2, Download, Settings, Bell, Filter, BarChart3, KeyRound].map((Icon, i) => (
            <div key={i} style={{ width: 40, height: 40, display: "grid", placeItems: "center", background: color.bgSurface, border: `0.5px solid ${color.border}`, borderRadius: radius.md, color: color.textSecondary }}>
              <Icon size={iconSize.lg} strokeWidth={1.5} />
            </div>
          ))}
        </Row>
      </Section>

      {/* BUTTONS */}
      <Section id="buttons" title="Botones" subtitle="Primary = cobre, texto #1A0A00 (nunca blanco). Secondary/ghost/danger para el resto.">
        <Row label="Variantes">
          <Button variant="primary" leftIcon={<Plus size={14} />}>Primary</Button>
          <Button variant="secondary">Secondary</Button>
          <Button variant="ghost">Ghost</Button>
          <Button variant="subtle">Subtle</Button>
          <Button variant="danger" leftIcon={<Trash2 size={14} />}>Danger</Button>
        </Row>
        <Row label="Tamaños · estados">
          <Button size="sm">Small</Button>
          <Button size="md">Medium</Button>
          <Button size="lg">Large</Button>
          <Button loading>Loading</Button>
          <Button disabled>Disabled</Button>
          <Button variant="primary" uppercase>Brand CTA</Button>
          <IconButton label="Ajustes"><Settings size={16} /></IconButton>
        </Row>
      </Section>

      {/* FORMS */}
      <Section id="forms" title="Formularios" subtitle="Inputs sobre la superficie más oscura, foco con anillo cobre. Labels 9px upper.">
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, maxWidth: 560 }}>
          <Field label="Ticker" hint="Símbolo del subyacente"><Input placeholder="AAPL" defaultValue="AAPL" /></Field>
          <Field label="Capital" required><Input placeholder="10000" type="number" /></Field>
          <Field label="Timeframe"><Select defaultValue="1d"><option value="1m">1 min</option><option value="1h">1 hora</option><option value="1d">Diario</option></Select></Field>
          <Field label="Error" error="Campo obligatorio"><Input invalid placeholder="…" /></Field>
          <Field label="Notas" style={{ gridColumn: "1 / -1" }}><Textarea rows={3} placeholder="Comentarios de la estrategia…" /></Field>
        </div>
      </Section>

      {/* BADGES */}
      <Section id="badges" title="Badges, pills y tags">
        <Row label="Pills">
          <Pill tone="neutral">Neutral</Pill><Pill tone="good">Profit</Pill><Pill tone="bad">Loss</Pill>
          <Pill tone="warning">Warning</Pill><Pill tone="info">Info</Pill><Pill tone="copper">Pro</Pill>
        </Row>
        <Row label="Badges sólidos · API">
          <Badge tone="good">Activo</Badge><Badge tone="bad">Error</Badge><Badge tone="warning">Beta</Badge>
          <MethodBadge method="GET" /><MethodBadge method="POST" /><MethodBadge method="DELETE" />
          <StatusBadge status={200} /><StatusBadge status={404} />
        </Row>
      </Section>

      {/* DROPDOWN */}
      <Section id="dropdown" title="Dropdowns y menús" subtitle="Popover sobre bg-surface, sombra lg, ítem activo con riel cobre. Cierra con click-fuera y Esc.">
        <Dropdown trigger={({ open, toggle }) => (
          <Button variant="secondary" onClick={toggle} rightIcon={<ChevronDown size={14} style={{ transform: open ? "rotate(180deg)" : undefined, transition: "transform 150ms" }} />}>Indicadores</Button>
        )}>
          <MenuLabel>Tendencia</MenuLabel>
          <MenuItem active checkable onSelect={() => {}}>EMA</MenuItem>
          <MenuItem checkable onSelect={() => {}}>SMA</MenuItem>
          <MenuItem checkable onSelect={() => {}}>VWAP</MenuItem>
          <MenuSeparator />
          <MenuItem danger icon={<Trash2 size={14} />} onSelect={() => {}}>Quitar todos</MenuItem>
        </Dropdown>
      </Section>

      {/* TABS */}
      <Section id="tabs" title="Tabs y segmented" subtitle="Tabs estilo carpeta (borde inferior cobre). Segmented para toggles compactos.">
        <Tabs
          tabs={[{ id: "performance", label: "Performance" }, { id: "trades", label: "Trades" }, { id: "charts", label: "Charts" }, { id: "calendar", label: "Calendar" }]}
          value={tab}
          onChange={setTab}
        />
        <div style={{ padding: 18, border: `0.5px solid ${color.border}`, borderTop: "none", background: color.bgSurface, fontFamily: font.sans, fontSize: 13, color: color.textSecondary }}>
          Contenido de la pestaña <b style={{ color: color.textHigh }}>{tab}</b>.
        </div>
        <div style={{ marginTop: 16 }}>
          <SegmentedControl options={[{ id: "curl", label: "cURL" }, { id: "js", label: "JavaScript" }, { id: "py", label: "Python" }]} value={seg} onChange={setSeg} />
        </div>
      </Section>

      {/* WIZARD — steps on top */}
      <Section id="wizard" title="Wizard · steps ENCIMA" subtitle="Regla UX: los pasos van arriba en horizontal, nunca en un riel lateral.">
        <Card padded={false} style={{ overflow: "hidden", height: 320 }}>
          <Wizard
            steps={WIZARD_STEPS}
            current={wizStep}
            completed={new Set([0])}
            onStepClick={setWizStep}
            onBack={() => setWizStep((s) => Math.max(0, s - 1))}
            onNext={() => setWizStep((s) => Math.min(WIZARD_STEPS.length - 1, s + 1))}
          >
            <div style={{ fontFamily: font.serif, fontSize: 22, color: color.textHigh, marginBottom: 8 }}>{WIZARD_STEPS[wizStep].label}</div>
            <p style={{ fontFamily: font.sans, fontSize: 13, color: color.textSecondary }}>Contenido del paso {wizStep + 1}. La barra de progreso y los pasos están <b style={{ color: color.copper }}>encima</b> del contenido.</p>
          </Wizard>
        </Card>
        <div style={{ marginTop: 16 }}>
          <Stepper steps={WIZARD_STEPS} current={2} completed={new Set([0, 1])} />
        </div>
      </Section>

      {/* OVERLAYS */}
      <Section id="overlays" title="Modales, tooltips y toasts">
        <Row>
          <Button variant="secondary" onClick={() => setModalOpen(true)}>Abrir modal</Button>
          <Tooltip content="Tooltip sobre fondo elevado con borde hairline."><Button variant="ghost">Hover tooltip</Button></Tooltip>
          <Button variant="ghost" onClick={() => toast({ title: "Backtest completado", description: "1,284 trades · PF 1.84", tone: "good" })}>Toast éxito</Button>
          <Button variant="ghost" onClick={() => toast({ title: "Sin conexión", description: "Reintentando…", tone: "bad" })}>Toast error</Button>
        </Row>
        <Modal
          open={modalOpen}
          onClose={() => setModalOpen(false)}
          eyebrow="Dataset"
          title="Guardar dataset"
          footer={<><Button variant="ghost" onClick={() => setModalOpen(false)}>Cancelar</Button><Button variant="primary" onClick={() => setModalOpen(false)}>Guardar</Button></>}
        >
          <Field label="Nombre del dataset"><Input autoFocus placeholder="p.ej. Small Cap Gappers" /></Field>
        </Modal>
      </Section>

      {/* DATA */}
      <Section id="data" title="Tablas">
        <Card padded={false}>
          <Table>
            <thead><Tr><Th>Estrategia</Th><Th>Trades</Th><Th>Win %</Th><Th>PF</Th><Th>Estado</Th></Tr></thead>
            <tbody>
              {[["ORB Momentum", "1,284", "58%", "1.84", "good"], ["Mean Reversion", "642", "47%", "0.92", "bad"], ["Gap & Go", "913", "53%", "1.31", "good"]].map((r, i) => (
                <Tr key={i} hoverable>
                  <Td style={{ color: color.textHigh, fontWeight: 600 }}>{r[0]}</Td>
                  <Td style={{ fontFamily: font.mono }}>{r[1]}</Td>
                  <Td style={{ fontFamily: font.mono }}>{r[2]}</Td>
                  <Td style={{ fontFamily: font.mono, color: r[4] === "good" ? color.profit : color.loss }}>{r[3]}</Td>
                  <Td><Pill tone={r[4] as "good" | "bad"}>{r[4] === "good" ? "OK" : "Descartar"}</Pill></Td>
                </Tr>
              ))}
            </tbody>
          </Table>
        </Card>
      </Section>

      {/* STATES */}
      <Section id="states" title="Estados: carga, vacío, error">
        <Row>
          <Spinner /><Loading /><LoadingDots />
        </Row>
        <div style={{ display: "grid", gap: 12, marginTop: 8 }}>
          <ErrorBox>Error 500: no se pudo ejecutar el backtest. Revisa los parámetros del universo.</ErrorBox>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            <Skeleton width={220} height={18} /><Skeleton width={320} /><Skeleton width={280} />
          </div>
          <Card>
            <EmptyState icon={<BarChart3 size={36} strokeWidth={1.25} />} title="Sin resultados" description="Ajusta los filtros del screener para ver estrategias." action={<Button variant="primary" size="sm" leftIcon={<Plus size={14} />}>Nueva búsqueda</Button>} />
          </Card>
        </div>
      </Section>

      <footer style={{ display: "flex", alignItems: "center", gap: 10, paddingTop: 24, borderTop: `0.5px solid ${color.border}`, color: color.textMuted, fontFamily: font.sans, fontSize: 12 }}>
        <Isotipo size={18} /> Edgecute Design System · ver <code style={{ fontFamily: font.mono }}>docs/DESIGN_SYSTEM.md</code>
      </footer>
    </div>
  );
}

export default function DesignSystemPage() {
  return (
    <ToastProvider>
      <Showcase />
    </ToastProvider>
  );
}
