# BANCO DE PREGUNTAS del bot de ejecución — qué puede salir mal

> **Qué es este fichero.** Lista de preguntas para pensarlas una a una antes de
> escribir código. Cada pregunta contestada se convierte en una regla numerada
> de `BOT_EJECUCION_REGLAS.md` (o en un «no aplica» razonado). Abierto el
> 2026-09-12. Se marcan con `[ ]` las pendientes y `[x]` las contestadas, con la
> regla que salió (`→ R-C-03`).
>
> Marcas: **[API]** = no se puede contestar sin el PDF del API de DAS; se
> repasa el día que llegue (lista consolidada al final, apartado R). **[dato]** =
> el estudio de cisnes o el backtester ya dan una cifra que ayuda; está apuntada
> al lado. Sin marca = se puede decidir ya con lo que sabemos.
>
> Orden de ataque previsto, por riesgo: C y G, luego F, I, B, H, J y K, y después
> el resto. Un área por día está bien; no hace falta contestar todo de golpe.

---

## A. Señal y datos antes de la orden

- [ ] A1. ¿Cuánto tiempo es válida una señal? Si el ejecutor la recibe 3 s, 30 s o 3 min tarde, ¿se ejecuta, se recalcula o se descarta?
- [ ] A2. ¿A qué distancia entre el precio de la señal y el precio actual se invalida la entrada (en % y en múltiplos del spread)?
- [ ] A3. Si el feed de Massive se retrasa o se corta a media señal, ¿con qué retraso máximo se permite ABRIR? ¿Y con cuál solo se GESTIONA lo abierto?
- [ ] A4. El bot decide con datos de Massive y ejecuta contra precios de DAS. Cuando difieren (prints tardíos, dark pool), ¿cuál manda para entrar y cuál para el stop? **[dato]** el 93 % de los «fogonazos» del crudo eran prints tardíos que están en la cinta y en las velas, no en el libro.
- [ ] A5. ¿Cómo se filtra un print erróneo (un tick fuera de rango)? ¿Un solo tick puede disparar una entrada o una salida?
- [ ] A6. ¿Qué pasa si el reloj del PC o del VPS se desvía? ¿Sincronización de hora obligatoria y comprobada al arrancar?
- [ ] A7. ¿Qué se hace con una señal en un símbolo que DAS no reconoce igual (cambio de ticker, sufijos, ADR)?
- [ ] A8. ¿Puede la estrategia dar señal en un ticker con split o contrasplit ese día o el siguiente? ¿Cómo lo sabe el bot (Nasdaq Daily List)?
- [ ] A9. Dos señales de la misma estrategia en el mismo minuto para el mismo ticker (duplicado por reconexión del feed): ¿cómo se detecta y cuál se ignora?
- [ ] A10. ¿El bot debe conocer eventos programados (FOMC, resultados, SEC) o eso es tarea humana antes de la sesión?
- [ ] A11. ¿Hay lista negra de tickers a mano? ¿Quién la mantiene y cuándo se aplica (antes de la señal o al ejecutar)?
- [ ] A12. Si la hidratación por REST al entrar al radar falla o llega incompleta, ¿se opera sin histórico o se espera a tenerlo?
- [ ] A13. ¿Qué pasa si la estrategia usa un indicador que en vivo no existe (tabla de Overhead, métricas RTH antes de las 09:30)? ¿Se bloquea la estrategia entera o solo la señal?

## B. Enviar la orden de entrada

- [ ] B1. Si al enviar el precio ya se ha movido, ¿se pone un límite a qué distancia (ask/bid ± X % o X ticks)? ¿Se persigue al precio hasta un tope y luego se abandona?
- [ ] B2. ¿Cuántas veces se reintenta una entrada no ejecutada y con qué separación? ¿Tras el último intento se descarta la señal para el día?
- [ ] B3. Ejecución parcial: ¿se acepta el resto, se cancela el resto y se protege lo lleno, o hay un mínimo por debajo del cual no compensa (comisión mínima, paquetes de locate de 100)?
- [ ] B4. Orden rechazada: ¿qué motivos puede dar el bróker (sin locate, sin buying power, halt, precio fuera de banda, lote, ruta cerrada) y hay una respuesta distinta por motivo? **[API]**
- [ ] B5. Orden enviada sin respuesta (timeout): ¿se asume no enviada, enviada, o se consulta el estado antes de reintentar? ¿Cómo se evita la orden doble? **[API: identificador de orden propio]**
- [ ] B6. ¿Puede haber dos órdenes vivas del mismo lado sobre el mismo ticker? ¿Cerrojo por ticker mientras haya una orden en vuelo?
- [ ] B7. Ruta: ¿cuál por defecto, cuál en premercado, cuál cuando urge salir, y quién decide el cambio? **[API: rutas, horarios y tipos de orden por ruta]**
- [ ] B8. Tamaño frente a liquidez: ¿tope de acciones por orden como fracción del volumen reciente y del tamaño visible en el ask/bid? ¿Se trocea la orden en tramos?
- [ ] B9. Precio por debajo de 1 $: ¿decimales admitidos y cómo se redondea el límite? **[API]**
- [ ] B10. ¿Lote máximo por orden del bróker y cómo se parte? **[API]**
- [ ] B11. Orden límite en premercado que no se ejecuta en N s: ¿se recoloca, se cancela o se deja viva hasta una hora?
- [ ] B12. ¿Se entra en la vela siguiente (i+1) como el backtester o al instante? Si el precio de i+1 ya está peor que el tope de entrada, ¿se salta?
- [ ] B13. Si el fill llega a un precio mucho mejor o peor del esperado (más de X %), ¿se avisa, se recalcula el tamaño o se cierra?
- [ ] B14. Antes de vender en corto, ¿el bot comprueba SSR (solo se puede vender por encima del bid)? ¿Cómo lo sabe? **[API]**
- [ ] B15. Locate aceptado y DAS rechaza el corto igualmente: ¿qué se hace y cómo se registra? **[API]**
- [ ] B16. Cancelación no confirmada: ¿se asume viva? Cancelación confirmada y después llega un fill (carrera): ¿cómo se reconcilia? **[API]**
- [ ] B17. ¿Órdenes ocultas o iceberg? ¿Aportan algo en small caps o no? **[API]**
- [ ] B18. Orden de entrada que sigue viva cuando llega un halt: ¿se cancela siempre antes de la reapertura?
- [ ] B19. ¿Se entra en una acción que ya está en SSR? (idea de Jaume: no, favorecen squeezes). ¿Regla fija o parámetro?
- [ ] B20. ¿Se entra si el spread supera X % del precio? ¿Y si el tamaño del bid es menor que la orden?

## C. Stop y protección de la posición

- [ ] C1. Tipo de stop por defecto: ¿mercado, limitado o limitado con banda ancha? ¿Distinto en premercado y en sesión? **[dato]** el precio camina: un limitado a +20 % se ejecutó en 654 de 678 casos; un stop a mercado de 300 $ se ejecutó una vez contra un print suelto a 5,6× el nivel; el limitado lo tapa. (P2, PUNTO ABIERTO)
- [ ] C2. ¿El stop vive en el servidor de DAS o en el bot? Si vive en el bot, ¿qué protege la posición cuando el bot muere? **[API]**
- [ ] C3. ¿Los stops de DAS disparan en premercado? ¿Con qué precio: último, bid/ask, print tardío? **[API]**
- [ ] C4. ¿Cuánto tiempo puede estar una posición sin stop residente? Pasados N s, ¿se cierra a mercado?
- [ ] C5. Stop limitado disparado y no ejecutado en N s porque el precio siguió subiendo: ¿se recoloca más arriba, se convierte a mercado o se aplica la espera de fogonazo?
- [ ] C6. Stop disparado por un print suelto tardío: ¿se puede pedir un stop que mire bid/ask en vez del último precio? ¿Lo permite DAS? **[API]**
- [ ] C7. Si DAS rechaza o cancela el stop (por ejemplo tras un halt), ¿quién se entera, en cuánto tiempo y qué hace?
- [ ] C8. Stop que se mueve (trailing, break-even): ¿lo mueve el bot cancelando y reponiendo, o DAS? Si entre cancelar y reponer el precio cruza el nivel, ¿qué pasa?
- [ ] C9. Pirámide: ¿un stop por lote o uno único para la posición? ¿Cómo se actualiza al añadir?
- [ ] C10. Take profit parcial: ¿se reduce el stop a las acciones restantes en el mismo instante? ¿Y si la reducción falla?
- [ ] C11. ¿Hay tope de órdenes stop vivas en la cuenta o en la plataforma? **[API]**
- [ ] C12. ¿Stop mental del bot por encima del residente, para actuar si el residente no funciona? ¿A qué distancia?
- [ ] C13. El stop de estructura del backtester es TEXTO: ¿quién lo traduce a un nivel numérico en vivo y con qué datos?
- [ ] C14. Al reiniciar el bot, ¿se adopta el stop que hay en DAS o se sustituye por el que calcula? Si difieren, ¿cuál gana?
- [ ] C15. ¿Distancia mínima del stop al precio para que DAS lo acepte y para que un spread ancho no lo dispare al colocarlo? **[API]**
- [ ] C16. Posición atrapada (halt, T12) con el stop cancelado por la plataforma: ¿se recoloca solo al reabrir? **[API: qué hace DAS con los stops en un halt]**

## D. Salidas, take profit y pirámides

- [ ] D1. Take profit: ¿límite residente en DAS unido al stop (OCO/bracket) o gestionado por el bot? ¿DAS lo admite? **[API]**
- [ ] D2. Take profit ejecutado a medias y el precio vuelve: ¿se deja el resto o se cancela?
- [ ] D3. Salida por hora de la estrategia: ¿límite, mercado, o límite y a los N s mercado? ¿Y si no hay liquidez?
- [ ] D4. Cierre forzoso de fin de día: ¿a qué hora, con qué margen antes del cierre, y qué pasa si no se consigue (posición overnight no deseada)? **[dato]** quien aguanta al cierre se lleva el T12 a casa (INHD, TENK).
- [ ] D5. Ejemplo de Jaume: se reduce por take profit y luego OTRA estrategia añade capital al mismo ticker. ¿Se permite? ¿Es nueva posición con su stop? ¿Se prohíbe añadir durante X min tras una reducción?
- [ ] D6. Reentradas: ¿cuántas por ticker y día? ¿Cuenta como el backtester (−1 es trampa)? ¿Reutiliza el locate?
- [ ] D7. Salida por deterioro de datos (feed caído): ¿cerrar todo o mantener con el stop residente?
- [ ] D8. Salida anticipada por aviso de halts (cadena de LULD) o por acercarse a la banda: **[dato]** salir a X % de la banda no vale como automatismo (2 % de acierto); una cadena de ≥ 5 LULD acaba en T12 1 de cada 300.
- [ ] D9. Salida rechazada (ruta cerrada, sin liquidez): ¿cambio de ruta automático y cuántos intentos? **[API]**
- [ ] D10. Salida por tramos por liquidez: ¿se acepta cerrar en varios trozos y cuánto se espera entre ellos?
- [ ] D11. ¿El bot puede cerrar una posición que abrió Jaume a mano? (ver K5)
- [ ] D12. Posición que queda abierta por error después de la hora: ¿aviso inmediato, cierre automático en after-hours o esperar al humano?
- [ ] D13. Pirámide: ¿cada nivel es una orden nueva con su guarda, o el ejecutor la trata como cambio de posición objetivo? ¿Qué pasa si el nivel 2 se llena y el 1 no?
- [ ] D14. Take profit parcial cuando la liquidez es pequeña: ¿se sacrifica el parcial y se sale entero?

## E. Varias estrategias, mismo ticker, capital compartido

- [ ] E1. Dos estrategias, mismo ticker, mismo lado: DAS netea en una sola posición. ¿Cómo reparte el bot fills, stops y PnL entre las dos?
- [ ] E2. Dos estrategias, lados opuestos: ¿prohibido, o la segunda cierra la primera? (con neteo, una compra sobre un corto lo cubre)
- [ ] E3. ¿Tope de capital por ticker sumando estrategias? Si no cabe, ¿cede la última en llegar o la de menor EV?
- [ ] E4. ¿Tope de capital total y por sesión (PM frente a RTH)? ¿Reserva para pirámides ya previstas?
- [ ] E5. Señales simultáneas en tickers distintos sin capital para todas: ¿prioridad por orden de llegada, por EV o por riesgo?
- [ ] E6. Buying power distinto en PM, intradía y overnight: ¿cómo lo sabe el bot y cómo lo respeta? **[API]**
- [ ] E7. Si una estrategia se retira o cambia de versión, ¿qué pasa con sus posiciones vivas?
- [ ] E8. Estrategias con distinto riesgo por operación: ¿unidad de riesgo común o por estrategia? (afecta a congelar el motor)
- [ ] E9. ¿El locate es de la posición o de la estrategia? Si dos estrategias lo usan, ¿quién paga?

## F. Halts

- [ ] F1. ¿Cómo sabe el bot que hay halt: L1 de DAS, ausencia de prints, fuente externa (Nasdaq Trader)? ¿Con qué latencia? **[API]**
- [ ] F2. Halt con posición dentro: ¿DAS cancela el stop residente? ¿Se prepara orden para la reapertura, límite o mercado en la subasta? **[API]**
- [ ] F3. Halt con orden de entrada en vuelo: ¿se cancela siempre?
- [ ] F4. Reapertura: ¿precio de referencia para decidir si salir (stop saltado, reabre por encima)? ¿Se sale en el primer print o se espera N s? **[dato]** el SL en la vela de reapertura se llena de mediana −3 % y p90 +4,8 % peor que el nivel, máx +14,5 %.
- [ ] F5. Cadena de LULD (≥ 5 en el día): ¿no ampliar, reducir o cerrar? **[dato]** 6+ halts llegan de mediana a ×2 y no vuelven; PAVS 7 halts ×13.
- [ ] F6. T1 (noticia pendiente) con posición: puede durar horas. ¿Aviso y esperar? ¿Y si dura hasta el cierre?
- [ ] F7. T12 con posición: capital bloqueado días, locate que sigue corriendo, posible buy-in. ¿Cómo se contabiliza y quién avisa al socio?
- [ ] F8. Halt en premercado (raro, existe: NEXI): ¿mismas reglas que en sesión?
- [ ] F9. ¿Tratamiento distinto para LULD, T1, T12 y halts de otras bolsas? **[API: códigos que entrega DAS]**
- [ ] F10. SSR activado a mitad de sesión: no afecta a cubrir, sí a abrir cortos nuevos. ¿Cómo se sabe y cuál es la regla? **[API]**
- [ ] F11. Bandas LULD: ¿DAS las da? Si no, ¿se calculan (5/10/20 % según precio y hora)? **[API]**
- [ ] F12. Media sesión o cierre anticipado: ¿el bot lo sabe y adelanta el cierre forzoso?
- [ ] F13. Halt en el minuto de la señal (la señal se generó con la vela anterior al halt): ¿se ejecuta a la reapertura o se anula?

## G. El precio se dispara

- [ ] G1. Fogonazo (sube ≥ X % en ≤ Y s y devuelve): ¿el bot no ejecuta el stop y espera N s? ¿Con qué X, Y, N? **[dato]** con 3 % por ticker, cerrar en el pico pierde de media el 14 % (peor 145 %); esperar 30 s, 2,6 % (p95 5,8 %); a 5 min p95 7,2 %. 1 de cada 10 saltos ≥ 100 % no vuelve en PM.
- [ ] G2. ¿Cómo distingue en vivo fogonazo de subida real: segundos sostenidos por encima de X % del salto, operaciones, volumen? ¿Con qué datos, si el NBBO de DAS avisa poco?
- [ ] G3. Pérdida máxima absoluta por posición: por encima de +Z % sobre la entrada, ¿cierre a mercado pase lo que pase? ¿Z distinto en PM y en RTH?
- [ ] G4. Squeeze lento (sube y no devuelve en 5-30 min): ¿salida por tiempo desde el pico? **[dato]** esperar más de 1 min no baja el p95; en ≥ 500 %, 5 de 8 vuelven en menos de 2 min y TNON, XHG y GRYP no.
- [ ] G5. Orden basura en el libro (25 $, 10.000 $): ¿cómo se protege un cierre a mercado? ¿Siempre limitado con banda? **[dato]** 7 de 56 disparos tenían una orden basura en los 10 niveles.
- [ ] G6. Cierre por tramos durante un pico: ¿la mitad al +50 % y el resto cuando devuelve?
- [ ] G7. Si la pérdida latente de una posición supera la pérdida diaria, ¿se cierra esa posición o todo?
- [ ] G8. Buy-in del bróker (te obligan a cubrir): ¿cómo se entera el bot y cómo lo contabiliza? **[API]**
- [ ] G9. El precio se dispara con una orden de ENTRADA viva (aún no dentro): ¿se cancela por distancia al precio de señal (A2) o se deja?
- [ ] G10. ¿Se registra cada fogonazo visto en vivo (con o sin posición) para calibrar X, Y, N con datos propios?

## H. Locates y préstamo

- [ ] H1. ¿Cuándo se pide el locate: en prealerta (44-59), al confirmar la señal, o cuando el ticker «salta» pronto porque es más barato? (P4)
- [ ] H2. ¿Cuánto se paga como máximo por acción y como % del beneficio esperado? ¿Se descarta la operación si el locate supera X % del EV? **[dato]** la puerta por EV ya existe en el backtester (`PROYECTO_EV_Y_LOCATES.md`).
- [ ] H3. Locate parcial (dan 500 de 1.000): ¿se opera con menos, se pide a otro proveedor o se descarta?
- [ ] H4. Locate comprado y operación que no se da: ¿coste hundido aceptado? ¿Tope diario de locates «desperdiciados»?
- [ ] H5. Tope diario y por operación de gasto en locates. **[dato]** una operación se llevó 7.000 $ de 10.000 en el backtest.
- [ ] H6. Paquetes de 100: ¿se ajusta el tamaño de la posición al múltiplo del locate? **[dato]** se cobra por paquetes enteros, no es lineal.
- [ ] H7. ¿Los locates caducan al cierre? ¿Sirven para reentradas el mismo día? ¿Se pueden devolver y con qué reembolso? **[API]**
- [ ] H8. El precio del locate cambia entre la consulta y la aceptación: ¿se acepta hasta +X %? **[API]**
- [ ] H9. Varios proveedores: ¿se elige el más barato automáticamente? **[API]**
- [ ] H10. ETB (no hace falta locate): ¿cómo se sabe y se salta el paso? HTB imposible: ¿se descarta la señal y se registra? **[API]**
- [ ] H11. ¿Hay locates en premercado a cualquier hora (04:00)? ¿A qué hora empieza el servicio? **[API]**
- [ ] H12. Locate aceptado y luego halt o T12: ¿coste del préstamo por días? ¿Quién lo vigila?
- [ ] H13. Registro de cada locate (precio, hora, usado o no) para alimentar la puerta por EV con datos reales.
- [ ] H14. Dividendos con corto: si por error queda una posición overnight en fecha ex-dividendo, ¿quién lo detecta?
- [ ] H15. ¿Tope de locates «en reserva» a la vez (comprados y sin usar) para no quemar la cuenta en prealertas?

## I. Capital, riesgo y cortacircuitos

- [ ] I1. Pérdida diaria máxima: ¿valor, se cuenta realizada + latente, quién corta (bot, ajustes de riesgo de DAS, ambos), y qué se hace al cortar (cerrar todo, cancelar todo, bloquear hasta mañana)? **[API: ajustes de riesgo de la cuenta]**
- [ ] I2. Pérdida máxima por operación y por ticker-día.
- [ ] I3. Racha: ¿N pérdidas seguidas paran el día? ¿Una semana en negativo reduce el tamaño?
- [ ] I4. Exposición total y por ticker (P3: 3-4 % barajado): ¿sobre qué capital, el equity del día, el inicial o un mínimo fijado?
- [ ] I5. Número máximo de posiciones simultáneas y de órdenes vivas.
- [ ] I6. Fracción máxima del volumen reciente (M9): ¿de qué ventana y qué múltiplo? ¿Se aplica también a la salida?
- [ ] I7. Cuenta muy en negativo en premercado: ¿qué hace Sage? (P1) ¿Y el bot: deja de abrir por debajo de X de equity?
- [ ] I8. PDT y mínimos de cuenta: ¿el bot vigila el número de day trades y el equity mínimo?
- [ ] I9. Llamada de margen: ¿reacciona el bot o es humano? **[API]**
- [ ] I10. Escalón inicial (canario): ¿1 acción, 100 $, 1 % del tamaño final? ¿Quién autoriza subir y con qué criterio?
- [ ] I11. ¿Reducción automática del tamaño tras días malos o tamaño fijo hasta que un humano lo cambie?
- [ ] I12. Los topes viven en el JSON de la estrategia y en el cuadro de mandos: si difieren, ¿cuál manda? ¿Se pueden cambiar en caliente y desde dónde?
- [ ] I13. Un tope que se supera por un fill peor de lo esperado (no por decisión): ¿se corrige al instante o se tolera hasta la salida?
- [ ] I14. ¿Los cortacircuitos se prueban cada día en seco (simulacro) o solo cuando saltan?

## J. Infraestructura: VPS, luz, comunicaciones

- [ ] J1. Se va la luz en casa (fase PC): ¿SAI? ¿Cuánto aguanta? ¿Bastan los stops residentes?
- [ ] J2. Se corta Internet en casa: ¿4G de respaldo? ¿A partir de cuántos segundos sin feed se pasa a «no abrir, solo gestionar» y cuántos a «cerrar todo»?
- [ ] J3. Se cae la conexión bot↔DAS (socket local): ¿reconexión automática, cuántos intentos, qué pasa con las órdenes en vuelo? **[API]**
- [ ] J4. Se cae DAS (la aplicación): ¿el supervisor la relanza y reloguea sola? ¿Hay 2FA que lo impida? **[API]**
- [ ] J5. Se cae Sage o el servidor de DAS: ¿teléfono del bróker, app móvil, plan de cierre manual? (runbook)
- [ ] J6. Se cae Massive: ¿fuente alternativa (L1 de DAS) solo para gestionar lo abierto?
- [ ] J7. Se cae el bot (excepción): ¿supervisor, tiempo máximo caído, reconciliación al volver, aviso por Telegram?
- [ ] J8. Bot colgado sin morir (latido parado): ¿quién lo mata y lo relanza?
- [ ] J9. Dos instancias del bot a la vez (dos PIDs, relanzar sin matar): ¿cerrojo de instancia única?
- [ ] J10. VPS: proveedor, ubicación (cerca de NY), Windows Update forzado (ventana de mantenimiento fuera de mercado), reinicios, una sola sesión RDP, coste.
- [ ] J11. Un solo login de DAS por cuenta: si Jaume abre DAS en casa, expulsa al bot. ¿Segunda cuenta? (P1) **[API]**
- [ ] J12. Reloj y zona horaria del VPS (todo en ET; DST distinto al de España).
- [ ] J13. Disco lleno por logs y diario: ¿rotación y tope?
- [ ] J14. Actualización forzada de DAS: ¿cómo se detecta y quién la hace?
- [ ] J15. Sesión de DAS que caduca de noche: ¿relogin antes de las 04:00 y comprobación? **[API]**
- [ ] J16. Modo degradado: tabla de qué se permite en cada estado (todo bien / sin feed / sin DAS / sin bot / sin Telegram).
- [ ] J17. Vigilante externo: si el bot no da señal de vida en N min, ¿alguien recibe aviso aunque el propio bot esté muerto?
- [ ] J18. Latencia: ¿se mide ida y vuelta orden→confirmación y a partir de cuánto no se opera?
- [ ] J19. Caída del proveedor de Telegram: ¿el bot sigue operando o se pausa por falta de canal de aviso?
- [ ] J20. Reinicio del VPS por el panel del proveedor (el socio): ¿arranque automático de DAS y bot con reconciliación antes de nada?

## K. Estado y reconciliación

- [ ] K1. Fuente de la verdad: DAS. ¿Cada cuántos segundos se reconcilia y qué se compara (posiciones, órdenes vivas, cuenta)?
- [ ] K2. Posición en DAS que el bot no conoce: ¿aviso y no tocar, o adoptar con stop?
- [ ] K3. Posición que el bot cree tener y DAS no: ¿se limpia el estado y se avisa?
- [ ] K4. Órdenes vivas que el bot no conoce: ¿cancelar o dejar?
- [ ] K5. Operaciones manuales de Jaume en la misma cuenta: ¿cuenta separada, o etiqueta que el bot respeta? ¿«Cerrar todo» cierra también las manuales?
- [ ] K6. Reinicio a media sesión: ¿qué se recupera del disco (posiciones, órdenes, locates, señales ya ejecutadas) y qué se rehidrata del feed?
- [ ] K7. Idempotencia por id de evento (`ticker|estrategia|momento|tipo`): si la misma señal se reevalúa tras un reinicio, ¿se reconoce como ya ejecutada?
- [ ] K8. ¿El diario JSONL se escribe antes de enviar la orden y después de la respuesta, siempre, aunque el disco esté lento?
- [ ] K9. Divergencia entre fills del diario y los de DAS al final del día: ¿tolerancia y quién la revisa?
- [ ] K10. Cambio de día: ¿cuándo «cierra» el día el bot y se resetean contadores (pérdida diaria, reentradas, locates)?
- [ ] K11. Si la reconciliación misma falla (DAS no contesta), ¿el bot sigue operando con el último estado bueno o se para?

## L. Horario y calendario

- [ ] L1. Ventanas de operación por estrategia (PM 04:00-09:30, RTH) y ventanas prohibidas (primeros N s tras las 09:30, últimos N min).
- [ ] L2. Festivos y medias sesiones: ¿fuente (Massive) y qué hace el bot ese día?
- [ ] L3. Horario de verano: todo en ET; ¿el bot lo comprueba solo?
- [ ] L4. ¿Se permite alguna posición overnight? Si no, hora límite dura de cierre y margen.
- [ ] L5. Fin de semana y días sin operar: ¿apagado o vigilante en marcha?
- [ ] L6. La sesión de la estrategia se SUMA, no sustituye (trampa conocida del backtester): ¿el bot lee la sesión como el backtester o la corrige?
- [ ] L7. Días con evento macro conocido: ¿lista manual de no operar?

## M. Control humano y avisos

- [ ] M1. Comandos de Telegram: `/estado`, `/pausar` (no abrir), `/cerrar_todo SI`, `/reanudar`. ¿Quién está autorizado (chat_id)? ¿Confirmación en dos pasos?
- [ ] M2. Qué se avisa (entradas, salidas, errores, reconciliación fallida, latido perdido) y qué no (prealertas). (M8)
- [ ] M3. ¿Silencio si todo va bien? ¿Resumen al cierre del día?
- [ ] M4. Si Telegram falla: ¿canal alternativo (correo, SMS)?
- [ ] M5. Socio: qué puede hacer sin Jaume (pausar, apagar el VPS, cerrar todo en DAS) y runbook de una página.
- [ ] M6. Si un humano opera en DAS por RDP mientras el bot corre, ¿el bot lo detecta y se pausa?
- [ ] M7. ¿Se pide confirmación humana para algo (primera operación del día, tamaño mayor que X) o nunca?
- [ ] M8. Guardia: ¿alguien mira el premercado cada día? ¿Qué pasa si nadie puede?
- [ ] M9. ¿Cómo se cambia un parámetro en caliente y cómo queda registrado quién lo cambió?

## N. Registro, contabilidad y auditoría

- [ ] N1. Diario JSONL: qué campos por decisión (señal, guarda, orden, respuesta, fill, stop, locate, reconciliación).
- [ ] N2. Comisiones, ECN, tasas SEC/FINRA, locates, plataforma: ¿el bot calcula el PnL neto o se toma de DAS?
- [ ] N3. Reconciliación diaria del PnL con el extracto del bróker: tolerancia y proceso.
- [ ] N4. Métricas de ejecución: slippage real frente a la señal, tiempo señal→fill, % de rechazos, por ruta y por hora.
- [ ] N5. ¿Basta el diario para reproducir cada decisión de un día concreto sin el feed?
- [ ] N6. Exportación fiscal y conservación de los diarios.

## O. Pruebas, sombra, canario y despliegue

- [ ] O1. ¿Hay demo o paper en DAS con Sage? Si no, ¿la sombra sustituye del todo? **[API]**
- [ ] O2. Sombra: ¿cómo se comparan las órdenes calculadas con los fills manuales de Jaume (exportación de DAS)?
- [ ] O3. Canario: tamaño, duración, criterios de salida (ya en la submemoria) y quién decide subir de escalón.
- [ ] O4. Versionado de estrategias: JSON con hash y fecha; ¿cómo se despliega una versión nueva sin tocar el bot en marcha? **[dato]** el bot de avisos lee las estrategias UNA vez al arrancar.
- [ ] O5. Cambios de código con el bot vivo: prohibidos en mercado. ¿Ventana de despliegue y comprobación de arranque limpio?
- [ ] O6. Pruebas de la guarda con tablas (función pura); simulacro de reconexión; simulacro completo del socio.
- [ ] O7. ¿Repetición de un día grabado contra el ejecutor en seco antes de cada versión?
- [ ] O8. Vuelta atrás: ¿cómo se recupera la versión anterior en 5 min?
- [ ] O9. ¿Qué se prueba con dinero real que no se puede probar de otra forma (locates, rechazos, halts)? ¿Cómo se fuerza?

## P. Backtester frente a vivo

- [ ] P1. Fills en reaperturas: el motor llena al nivel, el vivo al open. ¿Se mide y se corrige el motor o se acepta?
- [ ] P2. Liquidez infinita del motor: ¿tope de fracción de volumen también en el backtest para que sean comparables? **[dato]** 1B: 152× el volumen de la vela.
- [ ] P3. Ventana de entrada i+1 y slippage como fracción: ¿el bot replica o mejora? ¿Cómo se compara luego?
- [ ] P4. Locates aleatorios en el backtester frente a reales: ¿se registra el precio real para recalibrar la distribución?
- [ ] P5. Halts y SSR no están en el motor: ¿el bot los añade como guarda aparte (tabla auxiliar de halts), y el backtester después?
- [ ] P6. Prints tardíos en las velas AM: ¿la señal en vivo se calcula con la misma cinta que el backtest?
- [ ] P7. ¿Cuándo se para el bot por divergencia con el backtest (acierto, slippage p95, frecuencia de señales)?
- [ ] P8. Indicadores del backtester que no existen en vivo (Overhead, métricas RTH antes de las 09:30): ¿lista cerrada y bloqueo?

## Q. Seguridad

- [ ] Q1. Credenciales de DAS y token de Telegram en `.env`, fuera del repo. ¿Quién tiene acceso al VPS y con qué usuario?
- [ ] Q2. Comandos de Telegram solo desde chat_id autorizados: ¿qué pasa si roban el teléfono?
- [ ] Q3. La fuga de tokens de httpx en los logs (aplazada): ¿se arregla antes del VPS con dinero real?
- [ ] Q4. Copias del diario y del estado fuera del VPS.
- [ ] Q5. RDP expuesto a Internet: ¿VPN o IP fija?
- [ ] Q6. ¿Puede el bot enviar dinero o cambiar ajustes de la cuenta por API? Si sí, ¿cómo se le impide? **[API]**

---

## R. Consolidado: lo que hay que saber sí o sí del API de DAS

Para repasar el día que llegue el PDF, en este orden:

1. Identificador de orden propio del cliente (idempotencia) y consulta de estado de una orden. (B5, B16)
2. Stops residentes en el servidor: si existen, si disparan en premercado, con qué precio (último, bid/ask), qué pasa con ellos en un halt, distancia mínima y tope de stops vivos. (C2, C3, C6, C11, C15, C16)
3. Tipos de orden y de vigencia admitidos: mercado, límite, stop, stop límite, trailing, OCO/bracket, oculta; DAY/IOC/extendido. (B7, B17, D1)
4. Rutas: cuáles admiten premercado, cuáles urgen para salir, coste por ruta. (B7, D9)
5. Motivos de rechazo que devuelve, y en qué formato. (B4)
6. Lotes máximos, decimales por debajo de 1 $, redondeo. (B9, B10)
7. Locates: consultar, aceptar, devolver, proveedores, caducidad, precio que cambia, ETB/HTB, horario del servicio. (B15, H7-H11)
8. Cómo llegan halt, motivo (LULD/T1/T12), bandas LULD y SSR por el L1. (F1, F2, F9, F10, F11, B14)
9. Buying power por tramo (PM, intradía, overnight), llamada de margen, buy-in, ajustes de riesgo de la cuenta. (E6, I1, I9, G8)
10. Socket: reconexión, relogin, caducidad de sesión de noche, 2FA, un solo login por cuenta. (J3, J4, J11, J15)
11. Cuota y límite de mensajes por segundo. (J18)
12. Demo o paper. (O1)
13. Qué NO puede hacer el API (transferencias, ajustes de cuenta). (Q6)

## Registro

| Fecha | Qué |
|---|---|
| 2026-09-12 | Se abre el banco con 17 áreas y el consolidado para el PDF. Ninguna contestada. |
