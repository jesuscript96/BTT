# 05 — Arquitectura y Diseño Técnico

Este documento detalla la arquitectura de integración, flujo de datos y persistencia del módulo de Dilución y Runner.

---

## 1. Diseño de Base de Datos (Persistencia de Bancos Dilusores)

Para registrar qué bancos son contratados para diluir y calcular el riesgo ponderado, se creará una tabla en el archivo local de DuckDB (`users.duckdb`).

### 1.1 Esquema de Tabla SQL
```sql
CREATE TABLE IF NOT EXISTS dilution_banks_registry (
    ticker VARCHAR NOT NULL,
    bank_name VARCHAR NOT NULL,
    form_type VARCHAR NOT NULL,
    date_filed DATE,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 1.2 Inicialización de la Tabla
La tabla se creará automáticamente en la inicialización de la app (en `backend/app/database.py` o mediante una llamada `con.execute(...)` al obtener la conexión en el router de `assistant.py`).

---

## 2. Flujo de Datos del Análisis de Dilución

El flujo sigue el patrón KISS y evita dependencias lentas externas en tiempo de ejecución:

```
[UI Component: TickerAnalysis]
        │
        ▼ (Hacer clic en "Re-procesar datos")
[Trigger API Call: POST /api/assistant/chat]
        │  (Inyecta context: profile, yfinance, filings list, y top dilution banks de BD)
        ▼
[Backend Router: assistant.py]
        │
        ▼ (Llama a DeepSeek API)
[LLM: DeepSeek]
        │
        ▼ (Retorna reporte con tags <edgie_metrics>...</edgie_metrics>)
[Backend Router: assistant.py]
        │  (Intercepta respuesta, parsea JSON, extrae bank_name e inserta en DuckDB)
        ▼
[DuckDB: users.duckdb]
        │
        ▼ (Retorna JSON final + Reporte Markdown a UI)
[UI Component: TickerAnalysis] -> Renders metrics cards, balance table, ownership table & report.
```

---

## 3. Modificaciones al Prompt del LLM (System Prompt)

El `systemPrompt` (hoy definido en `frontend/src/components/TickerAnalysis.tsx:2088`) se migrará idealmente a una plantilla en backend o se mantendrá en el frontend con instrucciones estrictas de mercado.

### 3.1 Nuevas Instrucciones Críticas para Edgie:
1.  **Exclusión de Patrones de Velas:** *"Evitar valorar patrones de velas como indicios de dilución (ej: martillo invertido o gap-up con mecha larga). Enfocarse estrictamente en niveles de precios estructurales derivados de warrants y límites regulatorios Nasdaq."*
2.  **Identificación y Extracción de Bancos:** *"Extraer los nombres normalizados de los bancos de inversión mencionados en los formularios S-1, F-1, 424B, o 8-K/6-K (ATM) como Placement Agents o Underwriters, y devolverlos en la clave `hired_banks`."*
3.  **Formato de Salida:** *"Escribir el reporte Markdown en español comenzando inmediatamente con un apartado de máximo 2 párrafos titulado 'Resumen' con conclusiones prácticas y niveles de precio críticos para el trader. Luego, colocar un título 'Desarrollo de las conclusiones' con los detalles adicionales."*
4.  **Cálculo de Baby Shelf y Nasdaq:** *"Aplicar las reglas de la SEC (Baby Shelf 33.3% si float < $75M basado en el precio máximo de cierre de 60 días) y los límites de Nasdaq ($1.00 deficiencia, $0.10 muerte súbita, MVLS $35M, Stockholders' Equity $2.5M) para calificar la propensión al Pump & Dump motivado por necesidad de cumplir regulaciones."*

---

## 4. Registro y Ejecución de la Herramienta Global del Asistente

Para garantizar el acceso global de Edgie a los datos de Ticker Analysis sin importar la navegación de la UI:

### 4.1 Registro en el Layout Principal (LayoutShell)
*   En lugar de registrar la acción en `TickerAnalysis.tsx` (que se destruye al desmontar la vista), la acción `ticker_get_analysis` se registra en el montaje del componente global `LayoutShell.tsx` o directamente dentro de `ChatBotAgentic.tsx` / `ChatBot.tsx` al inicializar el `AssistantBus`.
*   Esto asegura que la herramienta esté siempre en la lista devuelta por `assistantBus.getToolsManifest()` y disponible para el LLM en todo momento.

### 4.2 Ejecución de Consultas Concurrentes en Background
*   El handler de `ticker_get_analysis` en TypeScript realiza consultas paralelas utilizando `Promise.all` hacia los endpoints existentes del backend:
    *   `GET /api/ticker-analysis/{ticker}` (Profile, Market, Financials, Gap Stats)
    *   `GET /api/ticker-analysis/{ticker}/sec-filings` (Filings list)
    *   `GET /api/ticker-analysis/{ticker}/balance-sheet` (Balance trends)
    *   `GET /api/ticker-analysis/{ticker}/finviz-news` (News list)
*   Una vez obtenidas todas las respuestas en background (tiempo aproximado < 1.5s debido a la concurrencia y cachés), el handler compila y retorna el objeto estructurado definido en el doc 03.

