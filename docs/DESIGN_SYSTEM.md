# Edgecute Design System v2.0

> Sistema de diseño canónico de Edgecute. **Cualquier UI nueva o modificada debe
> partir de aquí.** No se escriben hex/px sueltos en componentes: se usan los
> _tokens_ (CSS vars) o los _primitivos_ (`@/components/ui`).

**Tres fuentes de verdad, en orden:**

| Capa | Dónde | Para qué |
|------|-------|----------|
| **Tokens** | `frontend/src/app/globals.css` (vars CSS) + `frontend/src/components/ui/tokens.ts` (mirror TS) | valores: color, tipografía, espaciado, radio, sombra, z-index, motion |
| **Primitivos** | `frontend/src/components/ui/` | componentes reutilizables: Button, Card, Modal, Wizard… |
| **Styleguide vivo** | ruta `/design-system` en la app | ver todo renderizado y probar el tema claro/oscuro |

La regla rápida y operativa para agentes/IDE está en
`.cursor/rules/edgecute-design-system.mdc` y `.agent/EDGECUTE_DESIGN_SYSTEM.md`
(versión condensada de este documento).

---

## 1. Fundamentos de marca

- **Cobre `#D87A3D`** es **solo marca**: isotipo, eyebrow/“source”, foco, acentos
  de selección. No es un color de relleno genérico ni de texto de cuerpo.
- **Verde/rojo (`profit`/`loss`)** son **solo P&L** y semántica de éxito/error.
- **Neutros** (superficies y texto) hacen todo el trabajo de layout.
- Entre tema oscuro y claro **solo cambian los neutros**. Cobre y P&L se mantienen.

### Fuentes
- **General Sans** — UI y cuerpo. Cargar **solo desde Fontshare**
  (`api.fontshare.com/v2/css?f[]=general-sans@400,500,600,700`). **Nunca** desde
  Google Fonts: falla en silencio.
- **Fraunces** — títulos (serif). Desde Google Fonts.
- **mono** — datos numéricos y código (`ui-monospace, SFMono-Regular, Menlo…`).

### Isotipo
- **Siempre** SVG con coordenadas exactas — nunca con `div`s. Usa `<Isotipo />`.
- `viewBox 0 0 90 90`, cuadrado `#D87A3D` `rx 8`.
- Barras: sup `x20 y18 w52 h10` · centro `x20 y40 w38 h10` · inf `x20 y62 w52 h10`.
- Las barras usan `var(--color-ec-bg-base)` → se invierten solas entre temas.
- Tamaño en topbar: **24×24**. Lockup con wordmark: gap **10px**.

---

## 2. Tokens

### Color (`--color-ec-*`)
| Token | Dark | Uso |
|-------|------|-----|
| `copper` | `#D87A3D` | marca, foco, selección |
| `copper-bright` | `#E89C6A` | hover de cobre |
| `copper-text` | `#1A0A00` | **texto sobre cobre** (nunca blanco) |
| `bg-sidebar` | `#101213` | sidebar + fondo de inputs |
| `bg-base` | `#16181A` | fondo de página |
| `bg-surface` | `#1C1E21` | cards, paneles, popovers |
| `bg-elevated` | `#232528` | hover, headers internos, chips |
| `surface-hover` | `#232528` | estado hover de superficies |
| `border` | `#2C2F33` | bordes / separadores (hairline) |
| `text-high` | `#E4E2DF` | títulos |
| `text-primary` | `#D4D2CF` | cuerpo |
| `text-secondary` | `#8A8D92` | secundario |
| `text-muted` | `#6A6D72` | labels, placeholders |
| `profit` | `#4A9D7F` | ganancia / éxito |
| `loss` | `#C94D3F` | pérdida / error |
| `warning` | `#C9A23F` | aviso |
| `info` | `#5B8BB0` | informativo |

Tema claro: `html.light` reescribe los neutros (ver `globals.css`).
Toggle: `document.documentElement.classList.toggle('light')`.

### Tipografía — escala
| Rol | Familia | Tamaño / peso |
|-----|---------|---------------|
| Page title (h1) | Fraunces | 600 · 32–38px · `text-high` |
| Section title (h2) | Fraunces | 600 · 24–26px |
| Card / news title | Fraunces | 500 · 17px |
| Body / UI | General Sans | 400 · 13px · `text-primary` |
| Filter value | General Sans | 600 · 15px (**nunca Fraunces**) |
| Label / eyebrow | General Sans | 700 · 9px · UPPER · ls 2px · `text-muted` |
| Button | General Sans | 600 · 13px (brand CTA: 700 · 11px · UPPER · ls 1.2px) |
| Mono / datos | mono | 12.5px |

> _Fraunces italic_ solo para palabras de énfasis, **nunca** un titular entero.

### Espaciado — rejilla 4px
`--ec-space-1..12` → `4 8 12 16 20 24 32 40 48`. Padding de card: `16px 18px`.
Gap de sección en pantalla: 24px.

### Radio
`xs 4` (chips) · `sm 5` (botones, inputs) · `md 7` (cards, segmented) ·
`lg 8` (dropdowns, code) · `xl 12` (modales) · `pill 9999`.

### Bordes
Hairline **0.5px** por defecto. Acento **2px** (tab activa, riel de card destacada).

### Elevación (`--ec-shadow-*`)
`sm` sutil · `md` popover pequeño · `lg 0 10px 30px /.6` (dropdowns) ·
`xl` (modales). Foco: `--ec-ring-copper` = `0 0 0 2px rgba(216,122,61,.35)`.

### Z-index (`--ec-z-*`)
`sticky 10` · `dropdown 50` · `overlay 90` · `modal 100` · `toast 120` · `tooltip 130`.
**No** inventes z-index sueltos; usa la escala.

### Motion (`--ec-*`)
`ease cubic-bezier(.22,1,.36,1)` · duraciones `fast 120 · base 150 · slow 250 ·
slower 400`. Respetar `prefers-reduced-motion` (ya global en `globals.css`).

### Iconografía
`lucide-react`, **stroke 1.5px**. Tamaños 14 / 16 / 18 / 20. No mezclar otra
librería de iconos ni emojis dentro de UI de producto.

---

## 3. Componentes (`@/components/ui`)

Importar siempre desde el barrel: `import { Button, Modal } from "@/components/ui"`.

| Componente | Notas clave |
|-----------|-------------|
| `Button` / `IconButton` | `variant`: primary·secondary·ghost·danger·subtle. Primary = cobre + `copper-text`. `uppercase` solo para CTA de marca/auth. |
| `Card` + `Eyebrow` `CardTitle` `CardMeta` | normal vs `featured` (riel cobre 2px). Título de card destacada **nunca** en cobre. |
| `Field` `Input` `Textarea` `Select` | input sobre `bg-sidebar`, foco = anillo cobre. Label 9px upper. `Select` nativo; menús ricos → `Dropdown`. |
| `Pill` `Badge` `StatusBadge` `MethodBadge` | `tone`: neutral·good·bad·warning·info·copper. |
| `Dropdown` + `MenuItem` `MenuLabel` `MenuSeparator` | popover `bg-surface`, sombra lg, item activo con riel cobre. Cierra con click-fuera + Esc. |
| `Modal` | centrado, `bg-surface`, radio xl, backdrop blur, Esc + click-fuera, bloquea scroll. Header con `eyebrow`/`title`, slot `footer`. |
| `Tabs` | estilo carpeta, borde inferior cobre 2px en activa. |
| `SegmentedControl` | toggle compacto, un relleno activo. |
| `Stepper` / `Wizard` | **pasos SIEMPRE arriba en horizontal**. `Wizard` = stepper + barra progreso + contenido + footer Back/Next. |
| `Tooltip` | burbuja `bg-elevated` + hairline; hover/focus. |
| `Table` `Th` `Td` `Tr` | separadores hairline, header upper 9px, `Tr hoverable`. |
| `Spinner` `Loading` `LoadingDots` `ErrorBox` `EmptyState` `Skeleton` | estados de carga/vacío/error. |
| `ToastProvider` + `useToast()` | montar el provider una vez; `toast({ title, tone })`. |
| `Logo` `Isotipo` `Wordmark` | marca. |

---

## 4. Patrones UX/UI

- **Wizards: los pasos van ENCIMA**, en horizontal, no en un riel lateral. Usa
  `<Wizard>` / `<Stepper>`. (El antiguo `WizardStrategyBuilder` usa riel lateral
  y debe migrarse — ver §6.)
- **Modales**: una acción primaria a la derecha del footer; cancelar como `ghost`
  a su izquierda. Cierre por Esc y backdrop salvo confirmaciones destructivas.
- **Dropdowns/menús**: cierran con click-fuera y Esc; el item seleccionado lleva
  riel cobre + check.
- **Tablas**: header en mayúsculas 9px, valores numéricos en mono, P&L coloreado.
- **Foco visible**: todos los controles muestran anillo cobre en `:focus-visible`.
- **Estados vacíos**: nunca una pantalla en blanco — usa `<EmptyState>` con icono,
  título (Fraunces) y una acción.
- **Carga**: skeletons para contenido estructurado; spinner/dots para acciones.

---

## 5. Reglas críticas (no romper)

1. Botón primary: texto **`#1A0A00`**, **nunca** blanco.
2. _Fraunces italic_ solo para énfasis, nunca un titular completo.
3. Card destacada: destaca con fondo+borde cobre; el **texto nunca va en cobre**.
4. Isotipo: **siempre** SVG con coordenadas exactas (`<Isotipo/>`).
5. General Sans: **siempre** desde Fontshare.
6. Filter values: **siempre** General Sans 600, nunca Fraunces.
7. El cobre es **solo** marca / eyebrow / foco / selección.
8. Nada de hex o px sueltos en componentes: tokens o primitivos.
9. Iconos: lucide, stroke 1.5px. Sin emojis en UI de producto.
10. z-index: usar la escala `--ec-z-*`.

---

## 6. Deuda conocida (migrar a tokens/primitivos)

Detectado al construir v2.0. Pendiente de migrar; **no replicar** estos patrones:

- **`components/strategy-builder/WizardStrategyBuilder.tsx`** — stepper en **riel
  lateral** (190px). Debe pasar a pasos arriba (`<Wizard>`).
- **`components/DatasetModals.tsx`** — tema claro (`bg-white`, `zinc-*`,
  `blue-500`) que contradice el sistema. Migrar a `<Modal>` + `<Field>`/`<Input>`.
- **`components/backtester/IndicatorDropdown.tsx`** — chips de indicador con
  colores pastel de Tailwind (`bg-amber-50`…). Migrar a tokens / `<Badge>`.
- **`components/developers/ui.tsx`** — primitivos locales del portal dev (anteceden
  a `@/components/ui`); su `btnPrimary` usa texto blanco (viola la regla 1). El
  código nuevo debe usar `@/components/ui`.

> Antes había ~300 usos de `var(--color-ec-sans|serif|mono)` que **no estaban
> definidos** en `globals.css` (la tipografía caía al default del navegador).
> v2.0 define esos alias; quedan corregidos automáticamente.
