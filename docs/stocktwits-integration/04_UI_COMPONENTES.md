# 04 — UI y Componentes

Este documento define la representación visual y el comportamiento de la interfaz para las funcionalidades de Stocktwits.

---

## 1. Mapa de Pantallas e Integración Visual

```
PANTALLA 1: SCREENER (Pestaña "Radar de Momentum")
+------------------------------------------------------------+
|  [Screener de Mercado]  [Historial]  [Radar de Momentum]   |
+------------------------------------------------------------+
| FILTRADO POR DEFECTO: Small Caps (< $2,000M)               |
|                                                            |
| TICKER | COMPAÑÍA   | CAP. MERCADO | TREND SCORE | SENTIM.  |
|--------|------------|--------------|-------------|----------|
| CRWD   | CrowdStr.. | $1,850M      | 92.4        | 82% Bull |
| XYZ    | XYZ Biotech| $450M        | 87.1        | 52% Neut |
+------------------------------------------------------------+
```

```
PANTALLA 2: TICKER ANALYSIS (Panel Lateral & Pestañas de Debate)
+------------------------------------------------------------+
| Ticker: CRWD                                               |
| +---------------------+   +-----------------------------+  |
| | Sentimiento (15m)   |   | Why It's Trending (Catalyst)|  |
| |    [ Velocímetro ]  |   | "CrowdStrike beats earnings |  |
| |     85% Bullish     |   |  and raises guidance..."    |  |
| +---------------------+   +-----------------------------+  |
|                                                            |
|  [ Gráfico de Precios ]                                    |
|                                                            |
|  [News & Events]   [SEC Filings]   [Debate Stocktwits (MVP)]|
|  +------------------------------------------------------+  |
|  | @TraderJoe (Bullish) - 5 likes                       |  |
|  | "CRWD volume is surging in premarket. Squeeze..."    |  |
|  +------------------------------------------------------+  |
+------------------------------------------------------------+
```

---

## 2. Componentes a Reutilizar e Integrar

*   **`Screener` (`frontend/src/components/Screener.tsx`):** Añadir una pestaña llamada "Radar de Momentum" en la navegación principal. Reusará el componente `DataGrid` de la tabla principal pero configurado para consumir `/api/market/social/trending`.
*   **`NewsFeed` (`frontend/src/components/NewsFeed.tsx`):** Reusar la estructura de rejilla para la página de "Newsletters", consumiendo `/api/market/social/newsletter` e inyectando las imágenes del feed en tarjetas con estilo del Design System.
*   **`TickerAnalysis` (`frontend/src/components/TickerAnalysis.tsx`):**
    *   Añadir el widget **`SentimentGauge`** y la caja **`WhyTrendingBox`** en el panel informativo superior de estadísticas de ticker (junto al volumen pre-market).
    *   Añadir una pestaña **`StocktwitsStreamTab`** en el panel de pestañas de resultados inferiores.

---

## 3. Especificación de Componentes Nuevos

### Componente A: `SentimentGauge` (Widget Termómetro/Velocímetro)
*   **Descripción:** Un semicírculo o barra circular interactiva que muestra el sentimiento a 15m.
*   **Comportamiento Visual:**
    *   Aguja o arco de color según el score:
        *   `sentiment_score > 55` -> Color verde (`--ec-profit`).
        *   `sentiment_score < 45` -> Color rojo (`--ec-loss`).
        *   Entre `45` y `55` -> Color gris/apagado (`--ec-text-muted`).
*   **Los 4 Estados Obligatorios:**
    1.  **Loading:** Animación circular difuminada (Skeleton) del velocímetro con etiqueta *"Midiendo vibración social..."*.
    2.  **Empty:** Arco gris en 50% con mensaje *"Poco debate social"*.
    3.  **Error:** Arco gris con borde punteado rojo y mensaje *"Sentimiento no disponible"*.
    4.  **Success:** Render completo del score y etiqueta (`85% Bullish`).

### Componente B: `StocktwitsStreamTab` (Feed de Debate Limpio)
*   **Descripción:** Feed de posts filtrados de Stocktwits.
*   **Interacciones:**
    *   Click en el avatar o nombre de usuario abre el perfil de Stocktwits en pestaña nueva.
    *   Incrustar un pequeño badge de sentimiento (`Bullish` en verde, `Bearish` en rojo) si el usuario lo declaró al postear.
*   **Los 4 Estados Obligatorios:**
    1.  **Loading:** Lista de 5 tarjetas de carga en esqueleto gris con efecto pulso.
    2.  **Empty:** Icono de chat apagado con mensaje *"Sin debate relevante hoy. Filtrado de spam activo."*
    3.  **Error:** Caja de error con icono de alerta y botón *"Reintentar cargar debate"*.
    4.  **Success:** Render de los posts ordenados por likes en orden descendente.

---

## 4. Estilos y Tokens del Design System

Los componentes se adaptarán a las directrices de [.agent/EDGECUTE_DESIGN_SYSTEM.md](file:///Users/jvch/Desktop/AutomatoWebs/BTT/.agent/EDGECUTE_DESIGN_SYSTEM.md):

*   **Fondo:** Las tarjetas de tweets/newsletter usarán `--ec-bg-surface` (`#1C1E21`) y en hover cambiarán a `--ec-bg-elevated` para dar interactividad.
*   **Bordes:** Línea fina de `0.5px` usando `--ec-border` (`#2C2F33`).
*   **Tipografía:**
    *   Nombres de usuario y tags de sentimiento: **General Sans 600** (`11px` o `12px` en mayúsculas).
    *   Cuerpo del post y newsletters: **General Sans 400** (`13px` o `14px`) para alta legibilidad.
    *   Títulos de newsletter/catalizador: **Fraunces** con serif y peso medio (`16px` o `18px`).
*   **P&L (Sentimiento):**
    *   Bullish / Alcista: `--ec-profit` (`#4A9D7F`).
    *   Bearish / Bajista: `--ec-loss` (`#C94D3F`).
