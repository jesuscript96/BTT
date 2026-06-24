# Edgecute Design System v2.0

**Antes de tocar UI:** usa los primitivos de `@/components/ui` o los tokens. Nunca
escribas hex/px sueltos. Referencia completa: `docs/DESIGN_SYSTEM.md`. Styleguide
vivo: ruta `/design-system`.

## Fuentes
- General Sans: SOLO Fontshare — `api.fontshare.com/v2/css?f[]=general-sans@400,500,600,700`. NUNCA Google Fonts (falla en silencio).
- Fraunces: Google Fonts. Mono: ui-monospace/SFMono/Menlo.

## Tokens (definidos en globals.css; mirror TS en components/ui/tokens.ts)
Color `--color-ec-*`: copper #D87A3D · copper-bright #E89C6A · copper-text #1A0A00 ·
bg-sidebar #101213 · bg-base #16181A · bg-surface #1C1E21 · bg-elevated #232528 ·
surface-hover #232528 · border #2C2F33 · text-muted #6A6D72 · text-secondary #8A8D92 ·
text-primary #D4D2CF · text-high #E4E2DF · profit #4A9D7F · loss #C94D3F ·
warning #C9A23F · info #5B8BB0. Fuentes: `--color-ec-sans|serif|mono`.
Espaciado `--ec-space-1..12` (4px grid). Radio `--ec-radius-xs/sm/md/lg/xl/pill` = 4/5/7/8/12/9999.
Borde hairline 0.5px (acento 2px). Sombra `--ec-shadow-sm/md/lg/xl`; foco `--ec-ring-copper`.
Z `--ec-z-sticky10/dropdown50/overlay90/modal100/toast120/tooltip130`.
Motion `--ec-ease` + `--ec-dur-fast/base/slow/slower` (120/150/250/400).

## Isotipo
SIEMPRE SVG con coords exactas (usa `<Isotipo/>`), NUNCA divs. viewBox 0 0 90 90, cuadrado
#D87A3D rx8, barras x20 y18 w52 h10 / y40 w38 / y62 w52 en `var(--color-ec-bg-base)`
(se invierten con el tema). Topbar 24×24. Lockup gap 10px.

## Tipografía
Page title: Fraunces 600 32–38px text-high. Section: Fraunces 600 24–26px.
Card title: Fraunces 500 17px. Body/UI: General Sans 400 13px text-primary.
Filter value: General Sans 600 15px (NUNCA Fraunces). Label/eyebrow: General Sans 700
9px UPPER ls2px text-muted. Button: General Sans 600 13px (brand CTA 700 11px UPPER ls1.2px).
Datos/código: mono 12.5px. Fraunces italic SOLO énfasis, nunca titular completo.

## Iconografía
lucide-react, stroke 1.5px, tamaños 14/16/18/20. Sin otra librería ni emojis en UI de producto.

## Componentes (`@/components/ui`)
Button/IconButton · Card+Eyebrow/CardTitle/CardMeta · Field/Input/Textarea/Select ·
Pill/Badge/StatusBadge/MethodBadge · Dropdown+MenuItem/MenuLabel/MenuSeparator · Modal ·
Tabs · SegmentedControl · Stepper/Wizard · Tooltip · Table/Th/Td/Tr ·
Spinner/Loading/LoadingDots/ErrorBox/EmptyState/Skeleton · ToastProvider+useToast · Logo/Isotipo/Wordmark.

- Button primary = cobre + texto copper-text. secondary/ghost/danger/subtle para el resto.
- Input sobre bg-sidebar, foco anillo cobre. Label 9px upper.
- Dropdown/Modal: cierran con click-fuera + Esc; item activo con riel cobre.
- Tabs estilo carpeta (borde inferior cobre 2px en activa).

## Patrones UX/UI
- **Wizards: pasos SIEMPRE arriba en horizontal, nunca riel lateral.** Usa `<Wizard>`/`<Stepper>`.
- Modal: acción primaria a la derecha del footer, cancelar ghost a su izquierda.
- Tablas: header upper 9px, números en mono, P&L coloreado.
- Estados vacíos con `<EmptyState>` (icono+título+acción); nunca pantalla en blanco.
- Foco visible (anillo cobre) en todos los controles.

## Reglas críticas
1. Primary: texto #1A0A00, NUNCA blanco.
2. Fraunces italic solo énfasis.
3. Card destacada: fondo/borde cobre; texto NUNCA en cobre.
4. Isotipo SIEMPRE SVG exacto.
5. General Sans SIEMPRE Fontshare.
6. Filter values General Sans 600, nunca Fraunces.
7. Cobre = solo marca/eyebrow/foco/selección.
8. Sin hex/px sueltos: tokens o primitivos.
9. Iconos lucide 1.5px, sin emojis en UI.
10. z-index: usar escala `--ec-z-*`.

## Tema claro
`html.light` reescribe solo neutros (cobre/P&L no cambian). Toggle:
`document.documentElement.classList.toggle('light')`.

## Deuda conocida — NO replicar (migrar a primitivos)
- `strategy-builder/WizardStrategyBuilder.tsx`: stepper en riel lateral → pasos arriba.
- `DatasetModals.tsx`: tema claro (bg-white/zinc/blue) → `<Modal>`+`<Field>`.
- `backtester/IndicatorDropdown.tsx`: chips pastel Tailwind → tokens/`<Badge>`.
- `developers/ui.tsx`: primitivos locales del portal dev (su btnPrimary usa texto blanco, viola regla 1). Código nuevo usa `@/components/ui`.
