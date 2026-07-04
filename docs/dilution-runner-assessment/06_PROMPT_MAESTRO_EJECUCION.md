# 06 — Prompt Maestro de Ejecución (Guion para el Loop de IA)

Este documento contiene el plan de ejecución secuencial atómico y comandos de prueba que guiarán a la IA en la implementación de la v2.0 de Evaluación de Dilución y Runner.

---

## 0. Contexto Obligatorio (Leer antes de empezar)
Para implementar esta funcionalidad, se deben auditar y modificar los siguientes archivos:
*   **Base de datos:** [database.py](file:///Users/jvch/Desktop/AutomatoWebs/BTT/backend/app/database.py)
*   **Balance & Filings BE:** [ticker_analysis.py](file:///Users/jvch/Desktop/AutomatoWebs/BTT/backend/app/routers/ticker_analysis.py)
*   **Edgie API Gateway:** [assistant.py](file:///Users/jvch/Desktop/AutomatoWebs/BTT/backend/app/routers/assistant.py)
*   **UI Ticker Analysis:** [TickerAnalysis.tsx](file:///Users/jvch/Desktop/AutomatoWebs/BTT/frontend/src/components/TickerAnalysis.tsx)
*   **Edgie ChatBot UI:** [ChatBot.tsx](file:///Users/jvch/Desktop/AutomatoWebs/BTT/frontend/src/components/ChatBot.tsx) y [ChatBotAgentic.tsx](file:///Users/jvch/Desktop/AutomatoWebs/BTT/frontend/src/components/ChatBotAgentic.tsx)

---

## 1. Restricciones No Negociables
1.  **TDD (Test-Driven Development):** Para cada cambio en el backend, escribir el test unitario *antes* del código.
2.  **KISS (Keep It Simple, Stupid):** Reutilizar los endpoints y componentes existentes siempre que sea posible. No reescribir lógica de cálculo compleja si ya existe en pandas.
3.  **Mantener JIT Compilable:** No modificar `backtester/engine.py` ni realizar cambios que afecten la compilación de Numba.
4.  **No commitear bases de datos:** `.duckdb` y archivos `.log` deben permanecer fuera del control de versiones.

---

## 2. Secuenciación Atómica (Tareas)

### EPIC 1: Backend - Persistencia y Balance de Datos

#### Tarea 1.1: Inicialización de la Tabla de Bancos en DuckDB
*   **Acción:** En `backend/app/database.py`, en la función de inicialización de la conexión o similar, agregar la sentencia DDL para crear la tabla `dilution_banks_registry` si no existe.
*   **Verificación:** Ejecutar `python -c "from app.database import get_user_db_connection; con=get_user_db_connection(); print(con.execute('DESCRIBE dilution_banks_registry').fetchall())"`.
*   **Commit:** `feat(db): crear tabla dilution_banks_registry en DuckDB`

#### Tarea 1.2: Extensión de Endpoint de Balance Sheet
*   **Acción:** En `backend/app/routers/ticker_analysis.py`, modificar `get_ticker_balance_sheet()` para extraer del DataFrame `quarterly_balance_sheet` las columnas `Stockholders Equity` y `Share Capital` (o `Common Stock Shares Outstanding`) e incluirlas como `equity_history` y `shares_outstanding_history` en la respuesta JSON.
*   **Verificación:** Ejecutar `pytest tests/test_ticker_analysis.py -k "balance_sheet"`.
*   **Commit:** `feat(api): extender balance sheet trimestral con equity y shares outstanding`

#### Tarea 1.3: Interceptación y Registro en Gateway de Asistente
*   **Acción:** En `backend/app/routers/assistant.py`, en la función `chat` (cuando `stream=False` y el origen es el reporte de dilución), procesar el texto devuelto de DeepSeek. Si contiene el JSON `<edgie_metrics>`, parsearlo, extraer la clave `hired_banks` y registrar cada banco en `dilution_banks_registry` en DuckDB.
*   **Verificación:** Añadir test en `backend/tests/test_assistant_interceptor.py` que valide el parseo e inserción en base de datos. Ejecutar `pytest tests/test_assistant_interceptor.py`.
*   **Commit:** `feat(assistant): registrar agentes dilusores en DuckDB desde respuesta LLM`

---

### EPIC 2: Frontend - Estructura Visual y Modificaciones de UI

#### Tarea 2.1: Implementación de Pestañas en Filings
*   **Acción:** En `frontend/src/components/TickerAnalysis.tsx`, añadir un estado de pestaña seleccionado (`activeSecTab`). Renderizar un Tab Bar con opciones "Filings" y "Balance". Si se selecciona "Balance", mostrar la tabla con el histórico de yfinance (`cash`, `debt`, `working capital`, `equity`, `shares outstanding`).
*   **Verificación:** Ejecutar `npm run build` en la carpeta frontend y probar que no haya errores de compilación de TypeScript.
*   **Commit:** `feat(ui): añadir pestaña balance sheet trimestral en filings`

#### Tarea 2.2: Reducción del Tamaño de Cards de Métricas
*   **Acción:** En `TickerAnalysis.tsx`, modificar los estilos en línea de las tres cards iniciales (Dilution Probability, Cash Runway, Float) para reducir sus márgenes, padding a `10px`, tamaño de letra de labels a `8px`, y tamaño de la cifra principal a `18px`.
*   **Verificación:** Comprobar la UI visualmente.
*   **Commit:** `style(ui): reducir dimensiones de cards de métricas de dilución`

#### Tarea 2.3: Tabla de Ownership y Warrants en el Reporte de Edgie
*   **Acción:** En `TickerAnalysis.tsx`, modificar el renderizado de `aiAnalysis` para leer `aiMetrics.ownership_list` y renderizarlo en una tabla al inicio de la sección cualitativa, ordenando personas primero y luego instituciones. Renderizar también una sección de warrants si `warrants_triggers` no está vacío.
*   **Verificación:** Probar con un JSON mock en la UI.
*   **Commit:** `feat(ui): renderizar tabla de ownership y warrants estructurada`

---

### EPIC 3: Edgie - Prompts y Eventos de Chat

#### Tarea 3.1: Actualización del System Prompt de Edgie
*   **Acción:** En `TickerAnalysis.tsx`, actualizar el `systemPrompt` (línea 2088) agregando las reglas detalladas de dilución extrema (Baby Shelf, convertible notes, warrants price triggers, compliance Nasdaq, e identificación de placement agents). Prohibir explícitamente predicciones basadas en patrones de vela.
*   **Verificación:** Comprobar que el prompt actualizado compila y se envía correctamente en el payload.
*   **Commit:** `feat(prompt): actualizar system prompt de Edgie con reglas avanzadas de dilución`

#### Tarea 3.2: Evitar Notificaciones Duplicadas en ChatBot
*   **Acción:** En `ChatBot.tsx` y `ChatBotAgentic.tsx`, modificar el listener del evento `ticker-loaded`. Usar una referencia `lastNotifiedTickerRef` para asegurar que el mensaje *"Edgie ha cargado exitosamente..."* se imprima únicamente una vez cuando el ticker cambie o cuando la carga esté completa, y no en cada evento intermedio de carga progresiva.
*   **Verificación:** Seleccionar un ticker en la UI y comprobar que el mensaje del bot solo aparezca una vez.
*   **Commit:** `fix(chatbot): evitar notificaciones redundantes de carga de ticker`

#### Tarea 3.3: Registro de la Herramienta Global `ticker_get_analysis`
*   **Acción:** En `ChatBotAgentic.tsx` / `ChatBot.tsx` (o un layouts manager global), registrar de forma permanente la herramienta `ticker_get_analysis` utilizando `assistantBus.registerAction`. Implementar el handler para que realice fetches concurrentes (`Promise.all`) a las rutas de ticker analysis del backend y compile el JSON final de resultados del ticker.
*   **Verificación:** Invocar el comando de chat y corroborar mediante logs que recupera la información completa sin errores. Ejecutar `npm run build` en el frontend.
*   **Commit:** `feat(chatbot): registrar herramienta global ticker_get_analysis en el AssistantBus`

---


## 3. Comandos de Verificación
*   **Backend unit tests:** `cd backend && pytest tests/`
*   **Frontend linting:** `cd frontend && npm run lint`
*   **Frontend production build:** `cd frontend && npm run build`
