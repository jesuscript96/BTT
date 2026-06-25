# 06 — Prompt Maestro de Ejecución

Este documento sirve como el guion exacto de entrada para el agente de ejecución automática (Claude Code / Cursor) en modo *goal* o *loop*.

---

## 0. Contexto Obligatorio (Léelo antes de empezar)

Antes de realizar cualquier cambio, lee completos los siguientes archivos para entender los contratos, estilos y la infraestructura de caché:
*   [00_INDEX.md](file:///Users/jvch/Desktop/AutomatoWebs/BTT/docs/stocktwits-integration/00_INDEX.md)
*   [01_VIABILIDAD.md](file:///Users/jvch/Desktop/AutomatoWebs/BTT/docs/stocktwits-integration/01_VIABILIDAD.md)
*   [02_PRD.md](file:///Users/jvch/Desktop/AutomatoWebs/BTT/docs/stocktwits-integration/02_PRD.md)
*   [03_CONTRATO_DATOS.md](file:///Users/jvch/Desktop/AutomatoWebs/BTT/docs/stocktwits-integration/03_CONTRATO_DATOS.md)
*   [04_UI_COMPONENTES.md](file:///Users/jvch/Desktop/AutomatoWebs/BTT/docs/stocktwits-integration/04_UI_COMPONENTES.md)
*   [05_ARQUITECTURA.md](file:///Users/jvch/Desktop/AutomatoWebs/BTT/docs/stocktwits-integration/05_ARQUITECTURA.md)
*   [07_DECISIONES_ABIERTAS.md](file:///Users/jvch/Desktop/AutomatoWebs/BTT/docs/stocktwits-integration/07_DECISIONES_ABIERTAS.md)
*   [.agent/EDGECUTE_DESIGN_SYSTEM.md](file:///Users/jvch/Desktop/AutomatoWebs/BTT/.agent/EDGECUTE_DESIGN_SYSTEM.md)
*   [backend/app/routers/ticker_analysis.py](file:///Users/jvch/Desktop/AutomatoWebs/BTT/backend/app/routers/ticker_analysis.py) (para reusar el patrón de caché SWR)

---

## 1. Restricciones Globales No Negociables

1.  **Test Primero (TDD):** Para cada tarea de backend, escribe primero el test unitario en `backend/tests/test_social.py` que falle, luego implementa la lógica en producción hasta que el test esté en verde.
2.  **No Modificar el Motor de Backtesting:** Queda prohibido alterar cualquier archivo en `backend/app/backtester/` o las tablas relacionales históricas de mercado.
3.  **Sin Secretos en el Repositorio:** El token de autenticación de Stocktwits se leerá mediante variables de entorno en el servidor. Nunca commitear archivos `.env` ni credenciales hardcodeadas.
4.  **No Borrar Código:** Si se refactoriza algo del componente de noticias existente, mover el código antiguo a una carpeta `_archive/` o comentarlo limpiamente con explicaciones.

---

## 2. Secuenciación Atómica (EPICs y Tareas)

### EPIC 1: Capa de Ingesta y Caché Backend (TDD)
*   **Tarea 1.1: Test unitario de Stocktwits Service.**
    *   *Acción:* Crear `backend/tests/test_social.py`. Mockear respuestas HTTP de Stocktwits para los endpoints de Trending, Sentiment, Why Trending, Streams y RSS.
    *   *Verificación:* `cd backend && pytest tests/test_social.py -k Tarea1` (debe fallar).
*   **Tarea 1.2: Implementar cliente de API y Caché SWR.**
    *   *Acción:* Crear `backend/app/services/stocktwits_service.py`. Implementar llamadas con Basic Auth usando `STOCKTWITS_API_KEY` and `STOCKTWITS_API_SECRET`. Añadir la lógica de caché DuckDB asíncrona (SWR) usando los locks definidos en `database.py`.
    *   *Verificación:* `cd backend && pytest tests/test_social.py` (debe pasar a verde).
*   **Tarea 1.3: Definición de routers y contratos Pydantic.**
    *   *Acción:* Crear `backend/app/routers/social.py`. Registrar los 5 endpoints definidos en el contrato de datos. Importar y registrar el router en `backend/app/main.py`.
    *   *Verificación:* `cd backend && python -c "import app.routers.social"`.

### EPIC 2: Componentes y Consumo Frontend
*   **Tarea 2.1: Actualizar API Client en Frontend.**
    *   *Acción:* Modificar `frontend/src/lib/api.ts` para exponer las funciones `getSocialTrending()`, `getSocialSentiment(symbol)`, `getSocialSummary(symbol)`, `getSocialStream(symbol)` y `getSocialNewsletter()`.
    *   *Verificación:* `cd frontend && npm run build` (debe compilar sin errores de tipo TypeScript).
*   **Tarea 2.2: Componente `SentimentGauge` & `WhyTrendingBox`.**
    *   *Acción:* Crear los componentes en React usando los tokens del design system. Integrar los 4 estados (loading/empty/error/success).
    *   *Verificación:* Renderizado local y cobertura de estados mockeados.
*   **Tarea 2.3: Componente `StocktwitsStream` & `RadarMomentum`.**
    *   *Acción:* Crear las interfaces para la tabla del Radar en el Screener y el feed de debate limpio en las pestañas del Ticker.
    *   *Verificación:* `cd frontend && npm run lint`.

### EPIC 3: Integración de Pantallas y Verificación
*   **Tarea 3.1: Montaje en TickerAnalysis y Screener.**
    *   *Acción:* Inyectar los componentes creados en `TickerAnalysis.tsx` (caja de catalizador, velocímetro, pestaña de Debate) y `Screener.tsx` (pestaña de Radar de Momentum).
    *   *Verificación:* Arrancar servidores y probar interactividad.
    *   *Verificación global:* `cd frontend && npm run build` y `cd backend && pytest tests/`.

---

## 3. Definition of Done (DoD)

### Por Tarea Atómica:
*   [ ] Test unitario escrito previamente que valida los casos de éxito y fallo.
*   [ ] Comando de verificación de la tarea ejecutado y reportado en verde.
*   [ ] Código limpio sin warnings de linter (flake8 / eslint).
*   [ ] Commit convencional (`feat(social): ...` o `test(social): ...`).

### DoD Global (Listo para Entrega):
*   [ ] Los 5 endpoints del backend devuelven payloads correctos y gestionan la caché DuckDB.
*   [ ] No se ha inyectado ninguna credencial en el repo.
*   [ ] El build del frontend (`npm run build`) compila con éxito.
*   [ ] La interfaz se ve fluida, responde en <300ms y respeta los colores/fuentes del design system.
*   [ ] Se gestiona correctamente el estado vacío o offline si la API externa cae.

---

## 4. Comandos de Verificación Exactos

```bash
# Servidor Backend
cd backend && source .venv/bin/activate
pytest tests/test_social.py -v              # Ejecutar tests de Stocktwits
uvicorn app.main:app --reload --port 8000   # Arrancar backend local

# Cliente Frontend
cd frontend
npm run lint                                # Verificar linter
npm run build                               # Compilación producción (Crítico)
```
