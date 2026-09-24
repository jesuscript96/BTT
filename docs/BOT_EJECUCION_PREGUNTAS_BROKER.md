# Preguntas NETEADAS para DAS y Sage · 2026-09-24

Tras el repaso de Jaume (PDF «Preguntas API y Broker», 24-sep): las de negro las contestó él o esperan al PDF; las de rojo van a DAS; las de azul a Sage.

## Para DAS (API)

1. **ES:** ¿Existe una cuenta demo o de simulación que funcione con el mismo API? ¿Cómo se accede y se configura? ¿Ese acceso lo da DAS o el bróker?  
   **EN:** Is there a demo or simulation account that works with the same API? How is it accessed and set up? Is that access provided by DAS or by the broker?

2. **ES:** ¿Se puede modificar una orden viva (precio, cantidad) sin cancelarla y volver a enviarla (comando REPLACE o equivalente)?  
   **EN:** Can a live order be modified (price, quantity) without cancelling and resubmitting it (REPLACE command or equivalent)?

3. **ES:** Rutas: ¿cuáles operan en premercado desde las 04:00 y cuáles en after-hours? ¿Cuál recomiendan para salir con urgencia? ¿Qué es exactamente la ruta SMAT y a qué ruta manda cada tipo de orden? Entendemos que esto puede ser del bróker, pero por si saben algo.  
   **EN:** Routes: which ones work in pre-market from 4:00 AM and which in after-hours? Which one do you recommend for urgent exits? What exactly is the SMAT route and where does it send each order type? We understand this may be a broker matter, but in case you know.

4. **ES:** La orden PEG MID (pegada al punto medio): ¿qué rutas la admiten? ¿Funciona en premercado? ¿Se considera «agregar» liquidez y no «remover»? ¿Admite precio límite y Display=0?  
   **EN:** The PEG MID order (pegged to the midpoint): which routes support it? Does it work in pre-market? Is it treated as adding liquidity rather than removing? Does it accept a limit price and Display=0?

5. **ES:** La plataforma tiene órdenes OCO, Trigger Orders (WithTrigger) y Stop Range. ¿Están disponibles por el API? ¿Un Trigger Order dispara con una ejecución parcial de la orden principal o solo cuando está completa?  
   **EN:** The platform has OCO orders, Trigger Orders (WithTrigger) and Stop Range. Are they available through the API? Does a Trigger Order fire on a partial fill of the primary order or only when it is fully executed?

6. **ES:** Los ajustes de la plataforma que abren ventanas de confirmación (Send Order Confirm, Same Order in 10 seconds, Price Check, aviso de stop demasiado lejos, Fast Stop Limit Order): ¿afectan a las órdenes enviadas por el API? ¿Cómo dejarlos desactivados para el bot, por el API o en el perfil?  
   **EN:** Platform settings that open confirmation pop-ups (Send Order Confirm, Same Order in 10 seconds, Price Check, stop-too-far warning, Fast Stop Limit Order): do they affect orders sent through the API? How do we keep them disabled for the bot, via the API or in the profile?

7. **ES:** ¿Se pueden tener dos órdenes stop de compra vivas sobre la misma posición corta a la vez (una principal y una de emergencia), cada una con su cantidad?  
   **EN:** Can we have two live buy-stop orders on the same short position at the same time (a main one and an emergency one), each with its own quantity?

8. **ES:** Órdenes durante un halt: ¿acepta el API una orden a mercado o límite mientras la acción está parada y la envía al cruce de reapertura? ¿Se puede cancelar antes de la reapertura? ¿Qué mensajes devuelve el API en ese caso?  
   **EN:** Orders during a halt: does the API accept a market or limit order while the stock is halted and route it to the reopening cross? Can it be cancelled before the reopening? What messages does the API return in that case?

9. **ES:** [Propuesta de añadir] ¿El API admite órdenes «post only» / «add liquidity only» (por ejemplo ARCA ALO), que se rechazan o recolocan en vez de ejecutarse contra el libro? ¿Con qué sintaxis?  
   **EN:** [Proposed addition] Does the API support "post only" / "add liquidity only" orders (e.g. ARCA ALO) that are rejected or repriced instead of executing against the book? What is the syntax?

## Para Sage

1. **ES:** ¿Dos órdenes stop de compra vivas sobre la misma posición corta retienen buying power cada una? ¿Se valora la orden al precio límite?  
   **EN:** Do two live buy-stop orders on the same short position each reserve buying power? Is the order valued at its limit price?

2. **ES:** ¿Qué pasa con un stop cuando la acción entra en halt? ¿Se cancela, se mantiene, se ejecuta al reabrir? ¿Cambia según la ruta a la que se envió (SMAT o ruta directa)?  
   **EN:** What happens to a stop when the stock is halted? Is it cancelled, kept, or executed at the reopening? Does it depend on the route it was sent to (SMAT or a direct route)?
