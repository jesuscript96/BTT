# 07 — Decisiones Abiertas

Este documento recopila las decisiones de producto pendientes de firma por el PM y los defaults técnicos adoptados de forma reversible.

---

## A. Decisiones de Producto (Dueño: Jesús / Jaume)

### 1. Política de Gating y Monetización (DIFERIDA)
*   **Pregunta:** ¿Qué partes de la integración de Stocktwits estarán disponibles para usuarios "Free" y cuáles restringidas al tier "Pro"?
*   **Impacto:** Afecta a si mostramos anuncios, modales de suscripción o bloqueamos endpoints enteros en el backend.
*   **Estado:** **Diferida por Jesús.**
*   **Recomendación del Agente:** El backend expondrá un decorador o hook genérico de Clerk (`@require_pro_tier`) en los endpoints del router `routers/social.py`. Para el MVP, todos los endpoints quedarán públicos y la restricción se activará cambiando la configuración del decorador en el futuro sin modificar código interno.

### 2. Idioma de las Explicaciones de Tendencia
*   **Pregunta:** La API oficial de Stocktwits devuelve los resúmenes y boletines de "Why It's Trending" y "Chart Art" exclusivamente en **Inglés**. ¿Debemos traducirlos automáticamente en el backend?
*   **Impacto:** Añadiría dependencias de librerías de traducción (ej: DeepL o servicios de LLM), aumentando latencia y coste.
*   **Estado:** Abierto.
*   **Recomendación del Agente:** Mantener el contenido nativo en inglés en el MVP. Los traders de small caps y analistas técnicos están acostumbrados a la terminología en inglés. Considerar traducción automática vía LLM para una Fase 2.

---

## B. Defaults Técnicos Reversibles (Adoptados por la IA)

### 1. Umbral de Likes para el Filtro de Spam
*   **Default adoptado:** Solo mostrar mensajes en el feed de debate (`StocktwitsStream`) que posean `likes_count >= 2`.
*   **Razón:** Minimizar el ruido masivo de bots en tickers calientes.
*   **Reversibilidad:** Muy alta. Es un simple parámetro configurable `MIN_LIKES_THRESHOLD` en `stocktwits_service.py` que se puede bajar a 0 o subir en segundos.

### 2. TTL (Time-To-Live) de Caché SWR
*   **Default adoptado:**
    *   Radar de Trending: 3 minutos.
    *   Sentimiento a 15m: 5 minutos.
    *   Catalizador (Why): 10 minutos.
    *   RSS de Newsletter: 30 minutos.
*   **Razón:** Balancear frescura de datos frente a consumo de Rate Limit de la API externa.
*   **Reversibilidad:** Alta. Los TTLs están definidos en variables globales en `stocktwits_service.py` y se pueden migrar a variables de entorno `.env` en producción.
