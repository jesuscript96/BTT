# 01 — Viabilidad y Análisis de Rendimiento

Este documento evalúa la viabilidad técnica, los requisitos de rendimiento y el diseño del **Registro de Bancos Dilusores** propuesto por el usuario.

---

## 1. Análisis de Rendimiento (Tiempos de Análisis)

El análisis exhaustivo de filings de la SEC (10-K, 10-Q, S-1, 424B, 8-K, 6-K) en tiempo real plantea retos debido al tamaño de los documentos y la latencia de la red. Evaluamos los tiempos estimado para cada enfoque:

### Opción A: Descarga y Análisis de Texto Completo en Tiempo Real (No Viable)
*   **Proceso:** Descargar los documentos HTML/TXT completos desde SEC EDGAR, extraer texto, pasarlo a un LLM.
*   **Tiempo Estimado:** 15–30 segundos por consulta de ticker (bloqueante, inaceptable para la UI).
*   **Riesgo:** Bloqueos de IP por parte de la SEC por exceso de raspado (Web Scraping).

### Opción B: Enfoque Híbrido Basado en Metadata y LLM On-Demand (Viable - **Recomendado**)
*   **Proceso:**
    1.  **Carga Inicial de la UI (Instántanea):** Se consume el endpoint de yfinance (`/balance-sheet`) y el feed RSS de la SEC (`/sec-filings`) que ya están implementados. Ambos tardan **< 1.5 segundos** y usan caché en memoria (SWR) de 2 horas.
    2.  **Carga de Tabla de Balance (Instántanea):** El front procesa la respuesta de `/balance-sheet` para dibujar la tabla de tendencias trimestrales directamente.
    3.  **Procesamiento de Dilución (Asíncrono, 3-5 segundos):** Al hacer clic en "Re-procesar datos", se envía un prompt al LLM (DeepSeek) con las métricas cuantitativas pre-calculadas (Float, Shares Outstanding, Cash, Debt, etc.) y los metadatos de los últimos 20 filings (títulos y fechas).
*   **Tiempo Total de Espera:** 3–5 segundos para el reporte de Edgie AI (representado con un único loader en el frontend).

---

## 2. Registro de Bancos Dilusores (Base de Datos)

El usuario solicita registrar los bancos de inversión o agentes de colocación (ej. *Maxim Group, H.C. Wainwright*) asociados a emisiones dilutivas de las empresas analizadas para aumentar el scoring de riesgo.

### 2.1 Factibilidad Técnica e Implementación KISS
*   **Viabilidad:** **Alta**.
*   **Diseño Técnico:**
    1.  Añadir un campo `dilution_agents` en el JSON de salida estructurado del LLM (`<edgie_metrics>`).
    2.  Cuando Edgie procese el prompt de análisis, extraerá los nombres de los bancos mencionados en las secciones de Underwriting/Plan of Distribution de los filings recientes.
    3.  Al recibir la respuesta en el backend, se inserta una fila en una nueva tabla DuckDB (`dilution_banks_registry`) con la estructura: `(ticker, bank_name, form_type, date, timestamp)`.
    4.  Cuando se solicita un nuevo análisis, el backend consulta el conteo histórico de diluciones asociadas a ese banco en la base de datos y lo inyecta como contexto en el prompt para elevar el scoring de riesgo.

### 2.2 Utilidad y Control de Falsos Positivos
*   **Utilidad:** **Muy Alta**. En small caps, la presencia de bancos específicos es un indicador predictivo excelente de "dilución flash".
*   **Falsos Positivos:** Existe riesgo de registrar un banco que fue contratado para propósitos no dilusores (ej. asesoría de fusiones).
*   **Mitigación:** Configurar el prompt del LLM para que **únicamente** extraiga nombres de bancos cuando aparezcan listados específicamente en:
    *   Sección *Underwriting / Plan of Distribution* de formularios **S-1, F-1, S-3, F-3**.
    *   Prospectos definitivos **424B (424B3, 424B4, 424B5)**.
    *   Acuerdos ATM o líneas de crédito de capital en **8-K o 6-K** (Exhibits 4.1 o 10.1).

---

## 3. Riesgos y Mitigaciones Técnicas

| Riesgo | Impacto | Mitigación |
|---|---|---|
| Latencia del LLM en horas pico | Retraso en carga del reporte | Implementar timeout estricto de 10s en backend y botón de reintento. |
| Inexistencia de datos de float en yfinance | Error en el cálculo de float % | Usar el float disponible en el hot cache diario del screener (`daily_metrics`) como fallback. |
| Formato inconsistente de nombres de bancos (ej. "HC Wainwright" vs "H.C. Wainwright & Co.") | Duplicados en BD | Normalizar strings en backend (quitar puntuación, sufijos "Co.", "LLC" y pasar a mayúsculas) antes de guardar en DuckDB. |

---

## 4. Veredicto

**VIABLE BAJO EL ENFOQUE HÍBRIDO (KISS).**  
La implementación no requiere un scraper complejo de PDFs de la SEC. Reutiliza el flujo actual del LLM DeepSeek extendiendo su prompt e introduciendo una tabla DuckDB simple para el registro persistente de agentes dilusores.
