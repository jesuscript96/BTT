# Preguntas para el bróker (Sage) y el manual del API de DAS · 2026-09-22

Listado limpio para el día que pidamos el PDF del API. Referencias entre paréntesis: pregunta del banco o punto del apartado R.

## 1. Conexión y sesión del API / 1. API connection and session

1. **ES:** ¿El API de DAS (CMD API) está disponible en nuestra cuenta? ¿Qué versión del manual es la vigente? Necesitamos el PDF actualizado; el que hemos visto es de noviembre de 2021.  
   **EN:** Is the DAS CMD API enabled on our account? Which manual version is current? We need the up-to-date PDF; the one we have seen is from November 2021.  *(2b)*

2. **ES:** ¿Cuántas conexiones simultáneas admite una cuenta? Si abrimos DAS en otro ordenador, ¿se desconecta el bot? ¿Existe un modo de solo lectura («watch») además del de operar?  
   **EN:** How many simultaneous connections does one account allow? If we open DAS on another computer, does the bot get disconnected? Is there a read-only ("watch") mode besides trading mode?  *(J11, C12, R-10)*

3. **ES:** ¿La sesión caduca de noche? ¿Hay que volver a iniciar sesión antes de las 04:00 ET? ¿Hay doble factor (2FA) y se puede automatizar el reinicio de sesión?  
   **EN:** Does the session expire overnight? Do we need to log in again before 4:00 AM ET? Is there two-factor authentication, and can re-login be automated?  *(J15, J3)*

4. **ES:** ¿Cuál es el límite de mensajes o peticiones por segundo del API, y qué pasa al superarlo (rechazo, desconexión)? ¿Hay límite de órdenes por día?  
   **EN:** What is the API rate limit (messages or requests per second) and what happens when it is exceeded (rejection, disconnection)? Is there a daily order limit?  *(J18, R-11)*

5. **ES:** ¿Existe una cuenta demo o de simulación con el mismo API? ¿Cómo se configura y qué diferencias tiene con la real (fills, locates, datos)?  
   **EN:** Is there a demo or simulation account with the same API? How is it set up, and how does it differ from the live account (fills, locates, market data)?  *(O1, R-12)*

6. **ES:** ¿Qué NO se puede hacer por el API (transferencias, cambios de cuenta, etc.)?  
   **EN:** What can NOT be done through the API (transfers, account changes, etc.)?  *(Q6)*

## 2. Órdenes / 2. Orders

1. **ES:** ¿Podemos asignar nuestro propio identificador (token) a cada orden y recibirlo en todas las respuestas (aceptada, rechazada, ejecutada, cancelada)? ¿Qué pasa si no recibimos respuesta: cómo consultamos el estado de una orden concreta para no duplicarla?  
   **EN:** Can we attach our own identifier (token) to every order and get it back in all responses (accepted, rejected, filled, cancelled)? If we get no response, how do we query one specific order's status so we do not duplicate it?  *(B5, B16, R-1)*

2. **ES:** Lista completa de motivos de rechazo de una orden y el formato exacto en que se devuelven (sin locate, sin capital, halt, precio fuera de banda, lote, ruta cerrada, etc.).  
   **EN:** Full list of order rejection reasons and the exact format in which they are returned (no locate, insufficient buying power, halt, price outside band, lot size, route closed, etc.).  *(B4, R-5, R-14)*

3. **ES:** Lista completa de códigos de log y de error que puede devolver el API (órdenes, locates, conexión), con su significado.  
   **EN:** Full list of log and error codes the API can return (orders, locates, connection), with their meaning.  *(R-14)*

4. **ES:** Tipos de orden y tiempos en vigor admitidos por el API: mercado, límite, stop-market, stop-limit, trailing, ocultas; DAY, DAY+ (extended hours), IOC, GTC. ¿Cuáles funcionan en premercado y after-hours?  
   **EN:** Order types and time-in-force supported by the API: market, limit, stop-market, stop-limit, trailing, hidden; DAY, DAY+ (extended hours), IOC, GTC. Which ones work in pre-market and after-hours?  *(B7, B17, R-3)*

5. **ES:** ¿Existen órdenes OCO o bracket (una cancela la otra) por el API? Si no, ¿se pueden ligar dos órdenes de alguna forma?  
   **EN:** Are OCO or bracket orders (one cancels the other) available through the API? If not, is there any way to link two orders?  *(D1, R-3)*

6. **ES:** ¿Se puede modificar una orden viva (precio, cantidad) sin cancelarla y volver a enviarla (comando REPLACE)?  
   **EN:** Can a live order be modified (price, quantity) without cancelling and resubmitting it (REPLACE command)?  *(R-2)*

7. **ES:** Cancelación: si no llega confirmación, ¿la orden sigue viva? Si se confirma la cancelación y después llega una ejecución, ¿cómo se resuelve?  
   **EN:** Cancellation: if no confirmation arrives, is the order still live? If the cancellation is confirmed and then a fill arrives, how is that resolved?  *(B16)*

8. **ES:** Rutas disponibles: cuáles operan en premercado (desde las 04:00), cuáles en after-hours, coste de cada una (añadir/quitar liquidez), y cuál recomiendan para salir con urgencia. ¿Qué es exactamente la ruta SMAT?  
   **EN:** Available routes: which ones work in pre-market (from 4:00 AM), which in after-hours, cost of each (adding/removing liquidity), and which one you recommend for urgent exits. What exactly is the SMAT route?  *(B7, D9, R-4)*

9. **ES:** Precios por debajo de 1 $: ¿cuántos decimales admite el límite y cómo se redondea? ¿Hay tamaño máximo de orden y cómo se parte?  
   **EN:** Prices below $1: how many decimals does a limit price accept and how is it rounded? Is there a maximum order size, and how should it be split?  *(B9, B10, R-6)*

## 3. Stops / 3. Stops

1. **ES:** Las órdenes stop y stop-limit, ¿viven en el servidor de DAS o del bróker, o en nuestro ordenador? Es decir, ¿siguen activas si nuestro programa o nuestra conexión se caen?  
   **EN:** Do stop and stop-limit orders live on the DAS/broker server or on our computer? In other words, do they stay active if our program or our connection goes down?  *(C2)*

2. **ES:** ¿Con qué precio dispara un stop: último precio, bid, ask? ¿Se puede elegir? ¿Disparan en premercado y after-hours?  
   **EN:** Which price triggers a stop: last, bid, or ask? Can we choose? Do stops trigger in pre-market and after-hours?  *(C3, C6, R-2)*

3. **ES:** ¿Qué pasa con un stop cuando la acción entra en halt? ¿Se cancela, se mantiene, se ejecuta al reabrir?  
   **EN:** What happens to a stop when the stock is halted? Is it cancelled, kept, or executed at the reopening?  *(C16)*

4. **ES:** ¿Hay distancia mínima entre el precio actual y el stop para que sea aceptado? ¿Hay límite de órdenes stop vivas por cuenta o por símbolo?  
   **EN:** Is there a minimum distance between the current price and the stop for it to be accepted? Is there a limit on live stop orders per account or per symbol?  *(C15, C11)*

5. **ES:** ¿Se pueden tener dos órdenes stop de compra sobre la misma posición corta a la vez (una principal y una de emergencia), cada una con su cantidad?  
   **EN:** Can we have two buy-stop orders on the same short position at the same time (a main one and an emergency one), each with its own quantity?  *(C1, R-C-11)*

## 4. Datos de mercado por el API / 4. Market data through the API

1. **ES:** ¿Cuántos símbolos admite a la vez el Level 1 y el Time & Sales por el API? ¿Depende del plan de datos contratado?  
   **EN:** How many symbols can be subscribed at once to Level 1 and Time & Sales through the API? Does it depend on the market data plan?  *(R-18)*

2. **ES:** ¿El feed de precios es consolidado de todas las bolsas (SIP) o solo Nasdaq? ¿Qué operaciones excluye el Time & Sales (lotes sueltos, prints tardíos, condiciones)?  
   **EN:** Is the price feed consolidated across all exchanges (SIP) or Nasdaq only? Which trades does Time & Sales exclude (odd lots, late prints, conditions)?  *(R-19)*

3. **ES:** ¿El API indica si una acción está en halt y el motivo (LULD, T1, T12)? ¿Y las bandas LULD? ¿Con qué latencia?  
   **EN:** Does the API indicate whether a stock is halted and why (LULD, T1, T12)? Does it provide the LULD bands? With what latency?  *(F1, F9, R-8)*

4. **ES:** ¿El API indica si una acción está en SSR (restricción de ventas en corto)? Si no, ¿cómo lo sabemos antes de enviar la orden?  
   **EN:** Does the API indicate whether a stock is under SSR (short sale restriction)? If not, how can we know before sending the order?  *(B14, F2, R-8)*

## 5. Locates (préstamo de acciones para cortos) / 5. Locates (stock borrow for shorts)

1. **ES:** ¿Qué comandos del API hay para consultar precio y disponibilidad de locates, comprarlos y aceptar o rechazar la oferta? ¿Qué devuelve cuando no hay acciones disponibles?  
   **EN:** Which API commands exist to query locate price and availability, buy locates, and accept or reject the offer? What is returned when no shares are available?  *(H16, R-7, R-15)*

2. **ES:** El precio del locate, ¿se indica por acción o por paquete de 100? ¿Se cobra por paquetes enteros?  
   **EN:** Is the locate price quoted per share or per 100-share lot? Is it charged in whole lots?  *(H1, R-15)*

3. **ES:** ¿Los locates caducan al cierre del día? ¿Sirven para volver a entrar en la misma acción el mismo día (reentradas)? ¿Se pueden devolver y con qué reembolso?  
   **EN:** Do locates expire at the end of the day? Can they be reused to re-enter the same stock the same day? Can they be returned, and with what refund?  *(H7)*

4. **ES:** ¿A qué hora empieza el servicio de locates? ¿Hay locates desde las 04:00 ET?  
   **EN:** At what time does the locate service start? Are locates available from 4:00 AM ET?  *(H11)*

5. **ES:** ¿Hay varios proveedores de locates? ¿El API elige el más barato o hay que elegir ruta? ¿Cómo se sabe si una acción es ETB (no necesita locate)?  
   **EN:** Are there several locate providers? Does the API pick the cheapest or do we choose a route? How do we know a stock is ETB (no locate needed)?  *(H9, H10)*

6. **ES:** Si el precio del locate cambia entre la consulta y la aceptación, ¿qué precio se aplica?  
   **EN:** If the locate price changes between the quote and the acceptance, which price applies?  *(H8)*

7. **ES:** Con el locate aceptado, ¿puede DAS rechazar igualmente la orden de venta en corto? ¿En qué casos?  
   **EN:** With a locate accepted, can DAS still reject the short sale order? In which cases?  *(B15)*

## 6. Margen, capital y cuenta / 6. Margin, buying power and account

1. **ES:** ¿Qué devuelve exactamente la consulta de buying power (intradía, overnight, premercado)? ¿Ya descuenta el margen especial de cada símbolo?  
   **EN:** What exactly does the buying power query return (intraday, overnight, pre-market)? Does it already account for each symbol's special margin requirement?  *(E6, I1, R-9)*

2. **ES:** ¿Con qué criterio se clasifica un valor como «alto riesgo» a efectos de margen para cortos, y cómo podemos consultarlo por el API antes de operar?  
   **EN:** By what criteria is a stock classified as "high risk" for short margin purposes, and how can we query it through the API before trading?  *(2c, R-16)*

3. **ES:** Autoliquidación: ¿a qué hora y con qué aviso se liquida una posición por margen? ¿Solo en sesión regular?  
   **EN:** Auto-liquidation: at what time and with what notice is a position liquidated for margin? Only during regular hours?  *(2c, R-16)*

4. **ES:** Llamadas de margen y buy-in forzoso (obligación de cubrir un corto): ¿cómo se comunican y con qué plazo? ¿Se ven por el API?  
   **EN:** Margin calls and forced buy-ins (being forced to cover a short): how are they communicated and with what notice? Are they visible through the API?  *(I9, G8)*

5. **ES:** Regla PDT (pattern day trader) con cuenta por debajo de 25.000 $: ¿cómo la aplican?  
   **EN:** PDT (pattern day trader) rule with an account below $25,000: how do you apply it?  *(R-16)*

## 7. Halts largos y costes / 7. Long halts and costs

1. **ES:** Si un corto queda atrapado en un halt de varios días (T12), ¿qué comisiones, coste de préstamo (hard-to-borrow) o cargos por locate se cobran por cada día? ¿Puede haber buy-in forzoso durante el halt?  
   **EN:** If a short is stuck in a multi-day halt (T12), what commissions, hard-to-borrow fees or locate charges are billed per day? Can there be a forced buy-in during the halt?  *(R-17)*

2. **ES:** Comisiones y tarifas de rutas actualizadas (confirmar las de la web: comisión por acción, añadir/quitar liquidez por ruta, horarios).  
   **EN:** Current commissions and route fees (confirm the ones on the website: per-share commission, add/remove liquidity by route, hours).  *(B7)*
