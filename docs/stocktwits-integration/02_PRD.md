# 02 — Product Requirement Document (PRD)

## 1. Visión en una Frase
Ofrecer a los traders de Small Caps un panel de inteligencia social y de momentum integrado, agregando las señales de Stocktwits de forma curada, limpia de spam y optimizada en rendimiento.

---

## 2. Usuarios y Necesidades

| Perfil | Necesidad | Cómo lo sirve esta feature |
|---|---|---|
| **Intraday Small Cap Trader** | Encontrar acciones baratas de alta volatilidad antes de que exploten. | **Radar de Momentum:** Filtra tickers con volumen y tracción social en las últimas horas de capitalización < $2B. |
| **Catalyst Trader** | Entender inmediatamente por qué una Small Cap está subiendo un 30% en Pre-Market. | **Why It's Trending:** Muestra el catalizador fundamental resumido por los editores de Stocktwits en lenguaje natural. |
| **Momentum Scalper** | Medir si el interés social se está acelerando en el gráfico de 1 o 5 minutos. | **Sentiment Gauge:** Entrega un termómetro dinámico a 15m con volumen de mensajes para alertar picos de momentum alcista. |
| **Swing Trader / Chartist** | Descubrir configuraciones técnicas elaboradas por analistas profesionales de Stocktwits. | **Newsletter & Chart Art:** Acceso a boletines Chart Art y The DailyRip integrados de forma nativa. |

---

## 3. Jobs-to-be-Done (JTBD)

1. **Cuando** veo que una Small Cap está subiendo con volumen en Pre-Market, **quiero** saber de inmediato por qué está en tendencia (catalizador), **para** decidir si me coloco en short o long en la apertura.
2. **Cuando** estoy operando un trade intradía en un breakout de resistencia, **quiero** monitorizar si la masa social en Stocktwits está entrando en euforia alcista o pánico bajista en los últimos 15 minutos, **para** gestionar mi salida de forma agresiva.
3. **Cuando** no hay volatilidad obvia en mi lista de seguimiento clásica, **quiero** escanear un radar que me diga qué Small Caps están ganando interés social de forma inusual, **para** añadirlas a mi watchlist del día.

---

## 4. Alcance del MVP (Lo que SÍ se construye ahora)

### A. Radar de Momentum Social
*   Pantalla/vista que consulta `symbols_enhanced.json`.
*   Filtro estricto del backend: solo tickers con capitalización menor a `$2,000M USD`.
*   Visualización de tabla con columnas: Ticker, Nombre, Market Cap, Daily Volume, Trending Score y Sentimiento actual.

### B. Módulo Ticker Social Catalyst ("Why?") & Sentiment
*   Integración en el panel de detalle de Ticker (`TickerAnalysis.tsx`).
*   Muestra la explicación resumida del catalizador (`summary` del endpoint `/trending/{symbol}.json`).
*   Termómetro visual de Sentimiento a 15 minutos (velocímetro alcista/bajista de 0 a 100 con etiqueta Bullish/Bearish) y volumen de mensajes a 15m (Low/Medium/High) obtenidos de `/sentiment/v2/{symbol}/detail`.

### C. Zona de Debate Limpia (Clean Stream)
*   Pestaña "Debate Stocktwits" debajo del gráfico.
*   Muestra el feed obtenido de `/trending_messages/symbol/{symbol}`.
*   Visualización de mensajes estructurados (usuario, avatar, cuerpo, fecha, contador de likes e indicador de sentimiento alcista/bajista si el usuario lo marcó).

### D. Newsletters & Chart Art
*   Visualizador RSS para el boletín `/news/v2/newsletter/rss`.
*   Filtro y renderizado limpio del HTML para Chart Art y The DailyRip, aislando imágenes de análisis técnico.

---

## 5. Fase 2 (NO se construye ahora - Condiciona el MVP)

*   **Historial de Sentimiento Social en Gráfico:** Mostrar una curva temporal de sentimiento social a 15 minutos superpuesta en el gráfico intradía del ticker.
    *   *Decisión en MVP:* El backend al consultar `/sentiment/v2/{symbol}/detail` guardará un registro histórico `{ticker, timestamp, sentiment_score, message_volume}` en la tabla `ticker_analysis_cache` de DuckDB. Esto asegura que la Fase 2 tenga datos históricos acumulados listos para pintar sin tener que rediseñar la persistencia.
*   **Alertas Push de Sentimiento:** Enviar notificaciones si el sentimiento sube de 50 a >85 con volumen High en 15m.
    *   *Decisión en MVP:* Las APIs del backend deben devolver la bandera de volumen y sentimiento tipificadas con enums o enteros normalizados (`0-100`) para que las reglas de alertas del backend en el futuro puedan evaluarlos fácilmente.

---

## 6. Fuera de Alcance (Explícito)

*   **Publicación de Mensajes / Interacción Social:** El usuario no puede loguearse con sus credenciales personales de Stocktwits ni escribir mensajes, dar likes o responder a hilos desde Edgecute. La integración es de **solo lectura**.
*   **Monetización Activa en el Front:** Restringir el Radar o el Termómetro en base a suscripciones del usuario (Clerk Tiers) no se codificará en la UI en esta fase. Se deja preparado el middleware de backend con placeholders.
*   **Seguimiento de Tickers fuera de Small Caps:** El Radar omitirá por diseño del backend cualquier acción de mediana/alta capitalización (> $2B), impidiendo configuraciones del usuario para saltarse este filtro.

---

## 7. Glosario de Dominio (Nomenclatura)

*   `trending_score` (float): Puntaje de tendencia social calculado por la API de Stocktwits.
*   `sentiment_score` (int, 1-100): Puntuación de sentimiento donde 1 es extremadamente bajista (Bearish), 50 es neutral y 100 es extremadamente alcista (Bullish). *Mapeado de la clave `sentiment` de la API de Stocktwits*.
*   `message_volume_score` (int, 1-100): Puntuación normalizada del volumen de mensajes en 15m.
*   `message_volume_label` (string, LOW/MEDIUM/HIGH): Etiqueta textual del volumen de mensajes en 15m.
*   `why_trending_summary` (string): Resumen sintético en lenguaje natural del catalizador del ticker.
*   `likes_count` (int): Cantidad de me gustas de una publicación social en Stocktwits.

---

## 8. Métricas de Éxito de la Feature

1.  **Tiempo de Carga de UI (LCP):** < 300ms en el renderizado del Radar de Momentum y widgets de Ticker debido al uso de la caché DuckDB local.
2.  **Tasa de Spam Percibida:** < 5% de quejas de usuarios sobre bots en la pestaña de Debate debido a los filtros de likes mínimos.
3.  **Adopción:** > 60% de los traders que consultan Ticker Analysis interactúan con la pestaña de Debate o ven el Termómetro de Sentimiento durante sus sesiones activas de pre-mercado.

---

## 9. Principios de Diseño para el Agente

*   **Consistencia de Colores:** Usar estrictamente `--ec-profit` (verde) para sentimiento alcista (>55), `--ec-loss` (rojo) para sentiment bajista (<45) y `--ec-text-muted` (gris) para neutral (45-55).
*   **Consistencia Tipográfica:** Todos los valores numéricos y tablas del Radar deben usar la fuente **General Sans** con pesos 600/700. Los títulos de newsletters o catalizadores pueden usar **Fraunces** para un aire editorial premium.
*   **Resiliencia en Vacío:** Si un ticker no tiene actividad social suficiente, mostrar el estado vacío con la ilustración del logo de Stocktwits y un mensaje elegante: *"Tracción social baja en los últimos 15 minutos. Sin catalizadores detectados."*
