# Filtrado de instrumentos en el WebSocket de Massive

Guía de implementación para recibir **solo acciones americanas (CS) y ADR comunes (ADRC)**, excluyendo ETFs, warrants y cualquier otro instrumento.

---

## 1. Objetivo

| Criterio | Regla |
|---|---|
| Incluir | `CS` (Common Stock) + `ADRC` (American Depository Receipt Common) |
| Excluir | ETF, ETN, ETV, ETS, FUND, SP, WARRANT, ADRW, RIGHT, ADRR, UNIT, BOND, PFD, y cualquier otro |
| Mercado | Solo `stocks` (excluye OTC automáticamente) y locale US |

---

## 2. Principio clave

El WebSocket de Massive **no incluye el tipo de instrumento** en los mensajes (solo `sym`, precios, volumen y timestamps). El clúster de `stocks` mezcla acciones, ETFs, warrants, ADRs, etc.

Por lo tanto, **el filtro se aplica al momento de suscribir, no por mensaje.** Si solo se suscribe a símbolos que ya pasaron el allow-list, nunca llega un ETF ni un warrant. El backend no gasta recursos filtrando tick por tick.

> Regla de oro: el allow-list es una **lista blanca**. Lo que no esté explícitamente permitido (CS + ADRC) queda fuera. Esto garantiza cero fuga de ETFs/warrants.

---

## 3. Arquitectura

```
Frontend (React)  ──WS propio──►  Backend worker  ──WS──►  Massive
   pide símbolos                  - allow-list (Set en memoria)
   recibe barras AM               - 1 sola conexión a Massive
                                   - suscribe solo: watchlist ∩ allow-list
                                   - retransmite al front
```

Reglas de la arquitectura:

- El socket a Massive **vive en el backend**. Razones: (a) Massive permite una sola conexión concurrente por clase de activo; (b) la API key no puede exponerse en el navegador.
- El frontend solo se conecta al backend, pide símbolos y pinta lo que llega. No filtra ni conoce la key.
- Suscripción **dirigida por watchlist**: solo se suscribe a lo que el usuario está viendo, no a los ~7-8k símbolos del universo. Esto mantiene la carga baja.
- Feed por defecto: **`AM` (agregados por minuto)**. Mucho menor volumen que trades (`T`) o quotes (`Q`). Usar `T`/`Q` solo si es indispensable.

---

## 4. Construcción del allow-list

Se arma desde el endpoint REST de tickers, pidiendo solo los tipos permitidos y activos. Se pagina con `next_url`.

```
GET {REST}/v3/reference/tickers?market=stocks&type=CS&active=true&limit=1000&apiKey=KEY
GET {REST}/v3/reference/tickers?market=stocks&type=ADRC&active=true&limit=1000&apiKey=KEY
```

- `market=stocks` ya excluye OTC.
- Se guarda el campo `ticker` de cada resultado en un `Set` en memoria.
- Tamaño aproximado: ~7-8k strings ≈ 100 KB. No requiere base de datos para el MVP.

Opcional (producción): cachear el snapshot en un JSON o tabla de Supabase para sobrevivir reinicios sin volver a pegarle al REST en frío.

---

## 5. Flujo del WebSocket

### 5.1 Conexión y autenticación

```
1. Abrir conexión:   wss://socket.massive.com/stocks   (CONFIRMAR host real-time vs delayed)
2. Autenticar:       { "action": "auth", "params": "API_KEY" }
3. Esperar status:   { "ev": "status", "status": "auth_success" }
```

### 5.2 Suscripción (aquí ocurre el filtro)

Solo se suscriben los símbolos que cumplen **ambas** condiciones: están en el watchlist del cliente **y** están en el allow-list.

```json
{ "action": "subscribe", "params": "AM.AAPL,AM.MSFT,AM.BABA" }
```

- Formato del canal: `FEED.SIMBOLO` → ej. `AM.AAPL`.
- Enviar en lotes (~1000 símbolos por mensaje) si el watchlist es grande.

### 5.3 Recepción

```json
{ "ev": "AM", "sym": "AAPL", "o": 189.1, "c": 189.4, "h": 189.6, "l": 188.9, "v": 12500, "s": 1700000000000, "e": 1700000060000 }
```

- `c` = cierre del minuto, `o/h/l` = apertura/máx/mín, `v` = volumen, `s/e` = inicio/fin (Unix ms).
- Retransmitir cada barra solo a los clientes que miran ese `sym`.

### 5.4 Validación defensiva (segunda capa)

Aunque la suscripción ya filtra, antes de retransmitir se descarta cualquier mensaje cuyo `sym` no esté en el allow-list. Protege contra reutilización de símbolos (un ticker delistado que el exchange reasigna luego a un ETF).

```js
if (!allowlist.has(ev.sym)) continue; // descartar
```

---

## 6. Mantenimiento sin gaps

Para que con el tiempo no se cuele nada ni se pierdan altas válidas:

1. **Refresco diario** del allow-list (cron, 1 vez al día, idealmente pre-mercado). Captura IPOs, delistings y reclasificaciones.
2. **Diff y reconciliación**: tras cada refresco, comparar contra los símbolos suscritos. Si un símbolo dejó de ser `CS`/`ADRC` o quedó inactivo → desuscribir y sacarlo del allow-list.
3. **Reemplazo completo del Set**, no merge ciego. Nunca pisar un allow-list bueno con uno vacío (si el REST falla, conservar el anterior).
4. **Fail-closed ante tipos desconocidos**: si un ticker llega con `type` vacío o ambiguo, se excluye por defecto y se registra para revisión. Prioriza "cero ETF/warrant" sobre completitud.
5. **Re-suscribir al reconectar**: tras una reconexión y `auth_success`, volver a enviar la suscripción del watchlist vigente.

---

## 7. Configuración

| Variable | Valor sugerido | Nota |
|---|---|---|
| `MASSIVE_WS` | `wss://socket.massive.com/stocks` | **Confirmar** host real-time vs delayed |
| `MASSIVE_REST` | `https://api.massive.com` | **Confirmar** en dashboard |
| `API_KEY` | env `MASSIVE_KEY` | Nunca en el frontend |
| `FEED` | `AM` | Cambiar a `T`/`Q` solo si se necesita |
| `ALLOWED_TYPES` | `["CS", "ADRC"]` | No agregar más sin revisar |
| `MAX_WATCH_PER_CLIENT` | `50` | Tope para controlar carga en MVP |

---

## 8. Checklist de implementación

- [ ] Worker backend con una sola conexión a Massive (auth + reconexión).
- [ ] `buildAllowlist()` que pagina CS + ADRC activos y llena el `Set`.
- [ ] Servidor WS para el frontend que recibe `{ action: "watch", symbols: [...] }`.
- [ ] Filtro del watchlist contra el allow-list antes de suscribir.
- [ ] Suscripción dirigida (solo símbolos en pantalla) en feed `AM`.
- [ ] Validación defensiva `allowlist.has(sym)` antes de retransmitir.
- [ ] Reconciliación de suscripciones al conectar/desconectar clientes.
- [ ] Cron de refresco diario del allow-list.
- [ ] Re-suscripción tras reconexión.

---

## 9. Por confirmar antes de producción

- **Host wss exacto** (real-time vs feed con 15 min de retraso) y si la auth es por mensaje `auth` o por header.
- **Límite de tamaño** del mensaje de suscripción, para dimensionar los lotes.
- Decisión sobre tipos frontera: `ADRP` (ADR preferente), `NYRS`, `GDR`, `OS` (empresas extranjeras listadas en US que no son ADR técnico). Baseline actual: **solo CS + ADRC**.
- Aviso de Massive: si el cliente consume lento, el servidor puede desconectar. Procesar rápido y, si se usa `T`/`Q`, vigilar el volumen.
