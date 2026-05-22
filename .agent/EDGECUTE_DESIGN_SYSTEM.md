# Edgecute Design System v1.0

## Fuentes
- General Sans: SOLO desde Fontshare — api.fontshare.com/v2/css?f[]=general-sans@400,500,600,700
- Fraunces: desde Google Fonts
- NUNCA cargar General Sans desde Google Fonts — fallará silenciosamente

## Variables CSS (Dark Theme — default)
--ec-copper: #D87A3D
--ec-copper-bright: #E89C6A
--ec-copper-text: #1A0A00
--ec-bg-sidebar: #101213
--ec-bg-base: #16181A
--ec-bg-surface: #1C1E21
--ec-bg-elevated: #232528
--ec-border: #2C2F33
--ec-text-muted: #6A6D72
--ec-text-secondary: #8A8D92
--ec-text-primary: #D4D2CF
--ec-text-high: #E4E2DF
--ec-profit: #4A9D7F
--ec-loss: #C94D3F
--ec-sans: 'General Sans', sans-serif
--ec-serif: 'Fraunces', serif

## Isotipo
- SIEMPRE como SVG con coordenadas exactas — NUNCA con divs
- viewBox 0 0 90 90, fondo #D87A3D rx 8
- Barras: sup x:20 y:18 w:52 h:10 | centro x:20 y:40 w:38 h:10 | inf x:20 y:62 w:52 h:10
- Barras en #16181a sobre dark, #F5F4F1 sobre light
- Tamaño en topbar: 24×24px SIEMPRE

## Logo lockup
- General Sans 700, 17px, letter-spacing -0.6px
- Gap isotipo-texto: 10px

## Tipografía
- Page title (h1): Fraunces 600, 32-38px, #E4E2DF
- News title: Fraunces 500, 17px
- Fraunces italic: SOLO palabras de énfasis, NUNCA titular completo
- Body/UI: General Sans 400, 13px, #D4D2CF
- Buttons: General Sans 700, 11px uppercase ls 1.2px
- Filter labels: General Sans 700, 9px uppercase ls 2px, #6A6D72
- Filter values: General Sans 600, 15px, #D4D2CF — NUNCA Fraunces

## Botones
Primary:
- bg #D87A3D hover #E89C6A
- texto #1A0A00 — NUNCA #FFFFFF
- border-radius 5px, padding 9px 16px
- font General Sans 700 11px uppercase ls 1.2px

Secondary:
- bg #1C1E21, border 0.5px solid #2C2F33
- texto #8A8D92 hover #D4D2CF
- padding 9px 13px, General Sans 600 11px uppercase

Icon button: 32×32px square, mismo estilo que secondary, icono 14×14px stroke 1.5px

## Inputs
- bg #101213, border 0.5px solid #2C2F33, border-radius 5px
- padding 8px 11px
- font General Sans 400 12px #D4D2CF
- placeholder #8A8D92

## Cards
Normal:
- bg #1C1E21, border 0.5px solid #2C2F33, border-radius 7px, padding 16px 18px
- Source: General Sans 700 9px upper ls 2.5px #D87A3D
- Title: Fraunces 500 17px #E4E2DF
- Meta: General Sans 500 10px #6A6D72
- Hover: bg #232528

Destacada:
- bg #232528, border 0.5px solid #D87A3D, left border 2px #D87A3D
- Title: Fraunces 600, color #F0EEEA — NUNCA #D87A3D
- Source: #E89C6A

## Reglas críticas
1. Botón primary: texto SIEMPRE #1A0A00, NUNCA blanco
2. Fraunces italic: SOLO palabras de énfasis, nunca titular completo
3. Card destacada: fondo+borde para destacar, texto NUNCA en cobre
4. Isotipo: SIEMPRE SVG con coordenadas exactas
5. General Sans: SIEMPRE desde Fontshare
6. Filter values: SIEMPRE General Sans 600, NUNCA Fraunces
7. El cobre (#D87A3D) es SOLO para marca y eyebrow source

## Light Theme
html.light sobreescribe solo neutros — cobre y P&L no cambian
--ec-bg-sidebar: #EDEDEA | --ec-bg-base: #F5F4F1 | --ec-bg-surface: #FAFAF8
--ec-bg-elevated: #FFFFFF | --ec-border: #D6D4CE
--ec-text-muted: #95918A | --ec-text-secondary: #75726C
--ec-text-primary: #2C2A26 | --ec-text-high: #1A1815
Isotipo en light: barras fill #F5F4F1
Toggle: document.documentElement.classList.toggle('light')
