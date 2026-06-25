# 01 — Viabilidad de la Integración de Stocktwits

## 1. Restricciones Técnicas

### A. Límites de Peticiones (Rate Limits)
*   **Riesgo:** La API oficial de Stocktwits impone límites estrictos por dirección IP o por credenciales (Basic Auth). Si las llamadas se hicieran de forma directa por cada cliente en el frontend, agotaríamos la cuota en minutos.
*   **Mitigación:** Toda llamada a Stocktwits se canalizará a través del backend en un servicio centralizado. Se implementará una base de datos local (`users.duckdb`, tabla `ticker_analysis_cache`) como almacén temporal.
*   **Estrategia SWR (Stale-While-Revalidate):**
    *   Si se solicita información de un ticker o del Radar, se lee DuckDB y se devuelve al cliente de forma inmediata (<10ms).
    *   Asíncronamente en un hilo daemon, si la marca temporal de actualización supera el TTL del recurso, se consulta la API de Stocktwits y se actualiza la base de datos local.
    *   **TTLs Propuestos:**
        *   **Radar de Momentum** (`symbols_enhanced.json`): 3 minutos.
        *   **Termómetro de Sentimiento** (`/sentiment/v2/{symbol}/detail`): 5 minutos.
        *   **Explicación de Tendencia** (`/symbols/trending/{symbol}.json`): 10 minutos.
        *   **Zona de Debate** (`/trending_messages/symbol/{symbol}`): 3 minutos.
        *   **Newsletter/Chart Art** (`/news/v2/newsletter/rss`): 30 minutos.

### B. Latencia y Payload
*   **Latencia de Red:** Las llamadas a `api-gw-prd.stocktwits.com` pueden añadir entre 200ms y 1.2s de latencia. Si se hicieran de forma síncrona en el request-response loop del backend, degradarían severamente la experiencia de usuario (INP - Interaction to Next Paint).
*   **Mitigación:** La API del backend para Stocktwits devolverá inmediatamente la información en caché (incluso si está obsoleta/stale) garantizando una respuesta síncrona de <50ms.
*   **Payload:** Los streams de Stocktwits pueden ser muy pesados si traen imágenes u objetos anidados complejos. El backend filtrará y mapeará los JSONs para entregar al frontend únicamente el subconjunto de campos necesarios (ver `03_CONTRATO_DATOS.md`), reduciendo el tamaño del payload en un 80%.

---

## 2. Riesgos y Mitigaciones de Negocio/Seguridad

*   **Exposición de Credenciales (Basic Auth):**
    *   *Riesgo:* Guardar las credenciales en texto plano en el código o mandarlas al frontend comprometería nuestra cuenta de desarrollador.
    *   *Mitigación:* Autenticación Basic Auth inyectada exclusivamente del lado del servidor usando variables de entorno (`STOCKTWITS_API_KEY` y `STOCKTWITS_API_SECRET`). Ninguna credencial llega jamás al cliente.
*   **Filtro de Ruido y Bots (Spam en Small Caps):**
    *   *Riesgo:* Las Small Caps calientes sufren de esquemas "Pump & Dump" y spam masivo automatizado en redes.
    *   *Mitigación:* No se expondrá el stream crudo de Stocktwits. Para la "Zona de Debate Limpia", el endpoint del backend filtrará únicamente mensajes que tengan `likes_count >= 2` o que Stocktwits catalogue como `trending_messages`. Se implementará un filtro para excluir posts que mencionen más de 3 tickers o contengan enlaces externos sospechosos.

---

## 3. Aislamiento y No-Regresiones

*   **Aislamiento del Motor de Backtesting:**
    *   Esta feature es de índole "News & Social" y de análisis en tiempo real. **No** se modificará ninguna clase en `backend/app/backtester/` ni se alterará la lógica JIT.
    *   Los datos históricos de sentimiento se guardarán en la base de datos de usuario runtime (`users.duckdb`), no en el almacén de datos históricos (`market_data.db` o Parquets de GCS). Esto garantiza aislamiento total y cero riesgo de romper simulaciones de backtests.
*   **Aislamiento de Errores (Resiliencia):**
    *   Si la API de Stocktwits sufre una caída (502/504 Bad Gateway) o las credenciales expiran, el backend **no** devolverá un error HTTP 500 al cliente.
    *   En su lugar, el sistema devolverá de forma silenciosa la última versión cacheada en DuckDB. Si no hay datos previos en caché, se devolverá un payload vacío válido (`[]` o estructura vacía con códigos de advertencia controlados), evitando caídas de la interfaz.

---

## 4. Veredicto

**VIABLE CON CONDICIONES (VEREDICTO APROBADO)**

La integración es altamente viable y beneficiosa, siempre que se sigan estrictamente las condiciones de caché asíncrona SWR, aislamiento del núcleo JIT del backtester y sanitización estricta del stream en el backend.
