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

- [x] A1. → R-B-04 (provisional: 60 s desde el cierre de la vela, con la puerta del 3 %). ¿Cuánto tiempo es válida una señal? Si el ejecutor la recibe 3 s, 30 s o 3 min tarde, ¿se ejecuta, se recalcula o se descarta?
- [x] A2. → R-A-01 (no se entra; X provisional 1 %). ¿A qué distancia entre el precio de la señal y el precio actual se invalida la entrada (en % y en múltiplos del spread)?
- [x] A3. → R-D-05 (sin feed: no abrir, mantener, aviso); el umbral de segundos en J2. Si el feed de Massive se retrasa o se corta a media señal, ¿con qué retraso máximo se permite ABRIR? ¿Y con cuál solo se GESTIONA lo abierto?
- [x] A4. → R-C-09 + R-A-02 (Massive para señales, DAS para vigilar; prints fantasma tapados por R-B-01 y disparo por ask). El bot decide con datos de Massive y ejecuta contra precios de DAS. Cuando difieren (prints tardíos, dark pool), ¿cuál manda para entrar y cuál para el stop? **[dato]** el 93 % de los «fogonazos» del crudo eran prints tardíos que están en la cinta y en las velas, no en el libro.
- [x] A5. → R-A-02 (paridad; medir en sombra; filtrar en lago y bot a la vez si hace falta). ¿Cómo se filtra un print erróneo (un tick fuera de rango)? ¿Un solo tick puede disparar una entrada o una salida?
- [x] A6. → R-J-07 (desvío > 2 s = no operar). ¿Qué pasa si el reloj del PC o del VPS se desvía? ¿Sincronización de hora obligatoria y comprobada al arrancar?
- [x] A7. → R-A-04 (tabla de equivalencias diaria; si no casa, no se opera y avisa). ¿Qué se hace con una señal en un símbolo que DAS no reconoce igual (cambio de ticker, sufijos, ADR)?
- [x] A8. → R-A-03 (Daily List de Nasdaq cada mañana; filtro del radar). ¿Puede la estrategia dar señal en un ticker con split o contrasplit ese día o el siguiente? ¿Cómo lo sabe el bot (Nasdaq Daily List)?
- [x] A9. → R-A-05 (id estable heredado; repetidas se ignoran). Dos señales de la misma estrategia en el mismo minuto para el mismo ticker (duplicado por reconexión del feed): ¿cómo se detecta y cuál se ignora?
- [x] A10. → tarea humana, sin regla. ¿El bot debe conocer eventos programados (FOMC, resultados, SEC) o eso es tarea humana antes de la sesión?
- [x] A11. → R-A-03 (lista negra manual en el cuadro de mandos + exclusiones automáticas). ¿Hay lista negra de tickers a mano? ¿Quién la mantiene y cuándo se aplica (antes de la señal o al ejecutar)?
- [x] A12. → R-A-04 (no operar hasta tener histórico; reintentar). Si la hidratación por REST al entrar al radar falla o llega incompleta, ¿se opera sin histórico o se espera a tenerlo?
- [x] A14. → R-A-03 (IPO por list_date, SPAC por SIC 6770; OPA: noticias + banda de precio, estudio pendiente). **(Añadida por Jaume, 19-sep)** Acciones en FUSIÓN / ADQUISICIÓN (OPA con precio clavado), y también **IPOs / relistings y SPACs**: ¿el bot no entra? ¿Cómo lo detecta? Jaume: la mayoría (IPO, relisting, SPAC) se pueden sacar de Massive; las OPAs no, y se verá cómo abordarlas. **[dato]** auditoría del 19-sep (otra sesión): 340 OPAs 2019→2026; 1A entra en el 47 % y pierde (PF 0,72/0,25), 1B no entra; filtro propuesto sin código.
- [x] A13. → R-A-04 (bloqueo de la estrategia + aviso). ¿Qué pasa si la estrategia usa un indicador que en vivo no existe (tabla de Overhead, métricas RTH antes de las 09:30)? ¿Se bloquea la estrategia entera o solo la señal?

## B. Enviar la orden de entrada

- [x] B1. → R-B-01 FIJADA (al bid si <3 %, escalera 1/2/3 % en 60 s si no; tope 3 %). Si al enviar el precio ya se ha movido, ¿se pone un límite a qué distancia (ask/bid ± X % o X ticks)? ¿Se persigue al precio hasta un tope y luego se abandona?
- [x] B2. → absorbida por R-B-01 (sin reenvíos: la escalera es la persecución; a los 60 s se cancela). ¿Cuántas veces se reintenta una entrada no ejecutada y con qué separación? ¿Tras el último intento se descarta la señal para el día?
- [x] B3. → R-B-02 (sigue con R-B-01 hasta el minuto; se acepta lo que haya; sin mínimo). Ejecución parcial: ¿se acepta el resto, se cancela el resto y se protege lo lleno, o hay un mínimo por debajo del cual no compensa (comisión mínima, paquetes de locate de 100)?
- [ ] B4. Orden rechazada: ¿qué motivos puede dar el bróker (sin locate, sin buying power, halt, precio fuera de banda, lote, ruta cerrada) y hay una respuesta distinta por motivo? **[API]**
- [ ] B5. Orden enviada sin respuesta (timeout): ¿se asume no enviada, enviada, o se consulta el estado antes de reintentar? ¿Cómo se evita la orden doble? **[API: identificador de orden propio]**
- [x] B6. → R-B-03 (se suman cantidades en una orden, escalera reiniciada, lotes por estrategia en el diario). ¿Puede haber dos órdenes vivas del mismo lado sobre el mismo ticker? ¿Cerrojo por ticker mientras haya una orden en vuelo?
- [ ] B7. Ruta: ¿cuál por defecto, cuál en premercado, cuál cuando urge salir, y quién decide el cambio? **[API: rutas, horarios y tipos de orden por ruta]**
- [x] B8. → R-B-05 (acumulado del día; se mide siempre, tope desactivado). Tamaño frente a liquidez: ¿tope de acciones por orden como fracción del volumen reciente y del tamaño visible en el ask/bid? ¿Se trocea la orden en tramos?
- [ ] B9. Precio por debajo de 1 $: ¿decimales admitidos y cómo se redondea el límite? **[API]**
- [ ] B10. ¿Lote máximo por orden del bróker y cómo se parte? **[API]**
- [x] B11. → sin excepciones en PM (R-B-01). Orden límite en premercado que no se ejecuta en N s: ¿se recoloca, se cancela o se deja viva hasta una hora?
- [x] B12. → R-B-04 (en el instante del cierre de la vela i, por ticks; = open de i+1 del backtest). ¿Se entra en la vela siguiente (i+1) como el backtester o al instante? Si el precio de i+1 ya está peor que el tope de entrada, ¿se salta?
- [x] B13. → mejor: se acepta; peor por fallo: avisar y mantener con stop. Si el fill llega a un precio mucho mejor o peor del esperado (más de X %), ¿se avisa, se recalcula el tamaño o se cierra?
- [x] B14. → R-B-01 (suelo bid + 0,01 en SSR); cómo se lee la bandera [API]. Antes de vender en corto, ¿el bot comprueba SSR (solo se puede vender por encima del bid)? ¿Cómo lo sabe? **[API]**
- [ ] B15. Locate aceptado y DAS rechaza el corto igualmente: ¿qué se hace y cómo se registra? **[API]**
- [ ] B16. Cancelación no confirmada: ¿se asume viva? Cancelación confirmada y después llega un fill (carrera): ¿cómo se reconcilia? **[API]**
- [ ] B17. ¿Órdenes ocultas o iceberg? ¿Aportan algo en small caps o no? **[API]**
- [x] B18. → sí: halt cancela la escalera; al reabrir, nueva solo si «dentro» (R-F-04). Orden de entrada que sigue viva cuando llega un halt: ¿se cancela siempre antes de la reapertura?
- [x] B19. → sí se entra; escalera con suelo bid + 0,01 (R-B-01); bandera SSR [API]. ¿Se entra en una acción que ya está en SSR? (idea de Jaume: no, favorecen squeezes). ¿Regla fija o parámetro?
- [x] B20. → R-B-01: tope 3 % por distancia último precio→bid (FIJADO el 16-sep; la guarda por spread descartada). ¿Se entra si el spread supera X % del precio? ¿Y si el tamaño del bid es menor que la orden?

## C. Stop y protección de la posición

- [x] C1. → R-C-01 + R-C-11 (tres stop limit residentes; RTH y socio pendientes). Tipo de stop por defecto: ¿mercado, limitado o limitado con banda ancha? ¿Distinto en premercado y en sesión? **[dato]** el precio camina: un limitado a +20 % se ejecutó en 654 de 678 casos; un stop a mercado de 300 $ se ejecutó una vez contra un print suelto a 5,6× el nivel; el limitado lo tapa. (P2, PUNTO ABIERTO)
- [ ] C2. ¿El stop vive en el servidor de DAS o en el bot? Si vive en el bot, ¿qué protege la posición cuando el bot muere? **[API]**
- [ ] C3. ¿Los stops de DAS disparan en premercado? ¿Con qué precio: último, bid/ask, print tardío? **[API]**
- [x] C4. → R-C-03 (borrador; el cierre tras 5 intentos se repregunta con el PDF). ¿Cuánto tiempo puede estar una posición sin stop residente? Pasados N s, ¿se cierra a mercado?
- [x] C5. → R-C-02 (borrador, bloqueado por el PDF: triggers en DAS). Stop limitado disparado y no ejecutado en N s porque el precio siguió subiendo: ¿se recoloca más arriba, se convierte a mercado o se aplica la espera de fogonazo?
- [x] C6. → decidido (nota bajo R-C-09): el stop dispara por ask/bid («Ask + 0,01»); pendiente solo la sintaxis en el API. Stop disparado por un print suelto tardío: ¿se puede pedir un stop que mire bid/ask en vez del último precio? ¿Lo permite DAS? **[API]**
- [x] C7. → R-C-04 (borrador; depende de F). Si DAS rechaza o cancela el stop (por ejemplo tras un halt), ¿quién se entera, en cuánto tiempo y qué hace?
- [x] C8. → R-C-05 (borrador; sin estrategia que lo use aún). Stop que se mueve (trailing, break-even): ¿lo mueve el bot cancelando y reponiendo, o DAS? Si entre cancelar y reponer el precio cruza el nivel, ¿qué pasa?
- [x] C9. → R-C-06 (borrador; con varias estrategias cambia, área E). Pirámide: ¿un stop por lote o uno único para la posición? ¿Cómo se actualiza al añadir?
- [x] C10. → R-C-07 (borrador; plan B si falla la reducción, post-PDF). Take profit parcial: ¿se reduce el stop a las acciones restantes en el mismo instante? ¿Y si la reducción falla?
- [ ] C11. ¿Hay tope de órdenes stop vivas en la cuenta o en la plataforma? **[API]**
- [x] C12. → R-C-08 (borrador; vigilante aparte; criterios cerrar/no cerrar pendientes; dos conexiones [API]). ¿Stop mental del bot por encima del residente, para actuar si el residente no funciona? ¿A qué distancia?
- [x] C13. → R-C-09 (borrador). El stop de estructura del backtester es TEXTO: ¿quién lo traduce a un nivel numérico en vivo y con qué datos?
- [x] C14. → R-C-10 (borrador; traspaso humano↔bot pendiente). Al reiniciar el bot, ¿se adopta el stop que hay en DAS o se sustituye por el que calcula? Si difieren, ¿cuál gana?
- [ ] C15. ¿Distancia mínima del stop al precio para que DAS lo acepte y para que un spread ancho no lo dispare al colocarlo? **[API]**
- [ ] C16. Posición atrapada (halt, T12) con el stop cancelado por la plataforma: ¿se recoloca solo al reabrir? **[API: qué hace DAS con los stops en un halt]**

## D. Salidas, take profit y pirámides

- [ ] D1. Take profit: ¿límite residente en DAS unido al stop (OCO/bracket) o gestionado por el bot? ¿DAS lo admite? **[API]**
- [x] D2. → R-D-03 (resto al ask con techo 3 %; si no, stops + aviso; stops ajustados a lo que queda). Take profit ejecutado a medias y el precio vuelve: ¿se deja el resto o se cancela?
- [x] D3. → R-D-01 (escalera de compra 1/2/3 % en 60 s y luego al ask; sin doble compra). Salida por hora de la estrategia: ¿límite, mercado, o límite y a los N s mercado? ¿Y si no hay liquidez?
- [x] D4. → R-D-02 (EOD por estrategia, margen, aviso máximo y botón «control humano»). Cierre forzoso de fin de día: ¿a qué hora, con qué margen antes del cierre, y qué pasa si no se consigue (posición overnight no deseada)? **[dato]** quien aguanta al cierre se lleva el T12 a casa (INHD, TENK).
- [x] D5. → R-D-07 (prioridad al take profit, al ask; luego la entrada). Ejemplo de Jaume: se reduce por take profit y luego OTRA estrategia añade capital al mismo ticker. ¿Se permite? ¿Es nueva posición con su stop? ¿Se prohíbe añadir durante X min tras una reducción?
- [x] D6. → R-D-04 (según la estrategia; locate reutilizado si se puede; excepción halt). Reentradas: ¿cuántas por ticker y día? ¿Cuenta como el backtester (−1 es trampa)? ¿Reutiliza el locate?
- [x] D7. → R-D-05 (mantener con stops, no abrir, aviso de emergencia). Salida por deterioro de datos (feed caído): ¿cerrar todo o mantener con el stop residente?
- [x] D8. → R-F-01 caso 4 (con 2 halts, salir a 2-3 % de la banda). Salida anticipada por aviso de halts (cadena de LULD) o por acercarse a la banda: **[dato]** salir a X % de la banda no vale como automatismo (2 % de acierto); una cadena de ≥ 5 LULD acaba en T12 1 de cada 300.
- [ ] D9. Salida rechazada (ruta cerrada, sin liquidez): ¿cambio de ruta automático y cuántos intentos? **[API]**
- [x] D10. → igual que R-D-01, sin más. Salida por tramos por liquidez: ¿se acepta cerrar en varios trozos y cuánto se espera entre ellos?
- [x] D11. → R-D-06 (solo con «cerrar todo» de Telegram: ask para cortos, bid para largos). ¿El bot puede cerrar una posición que abrió Jaume a mano? (ver K5)
- [x] D12. → R-D-02 (aviso máximo por lote; humano; sin after-hours). Posición que queda abierta por error después de la hora: ¿aviso inmediato, cierre automático en after-hours o esperar al humano?
- [x] D13. → mismo protocolo que las entradas (R-B-01/02/03). Pirámide: ¿cada nivel es una orden nueva con su guarda, o el ejecutor la trata como cambio de posición objetivo? ¿Qué pasa si el nivel 2 se llena y el 1 no?
- [x] D14. → R-D-03. Take profit parcial cuando la liquidez es pequeña: ¿se sacrifica el parcial y se sale entero?

## E. Varias estrategias, mismo ticker, capital compartido

- [x] E1. → lotes por estrategia + R-B-03 + R-C-06/R-C-11 + R-D-03. Dos estrategias, mismo ticker, mismo lado: DAS netea en una sola posición. ¿Cómo reparte el bot fills, stops y PnL entre las dos?
- [x] E2. → R-E-01 (prohibido hasta nuevo aviso). Dos estrategias, lados opuestos: ¿prohibido, o la segunda cierra la primera? (con neteo, una compra sobre un corto lo cubre)
- [x] E3. → sin tope: lo controla el reparto del cuadro de mandos. ¿Tope de capital por ticker sumando estrategias? Si no cabe, ¿cede la última en llegar o la de menor EV?
- [x] E4. → R-I-01 + R-E-02 (capital libre, orden de llegada; pirámide sin dinero no se hace). ¿Tope de capital total y por sesión (PM frente a RTH)? ¿Reserva para pirámides ya previstas?
- [x] E5. → R-E-02 (orden de llegada; lo que sobre; sin proporcional). Señales simultáneas en tickers distintos sin capital para todas: ¿prioridad por orden de llegada, por EV o por riesgo?
- [ ] E6. **RECORDAR: pedir a Jaume las reglas de margen/buying power de su bróker con el PDF (17-sep).** Buying power distinto en PM, intradía y overnight: ¿cómo lo sabe el bot y cómo lo respeta? **[API]**
- [x] E7. → R-E-03 (botones en el cuadro de mandos: cerrar y reiniciar / esperar al fin del día). Si una estrategia se retira o cambia de versión, ¿qué pasa con sus posiciones vivas?
- [x] E8. → unidad propia por estrategia y por pirámide; el bot la interpreta según la estrategia. Estrategias con distinto riesgo por operación: ¿unidad de riesgo común o por estrategia? (afecta a congelar el motor)
- [x] E9. → a la primera que da señal; el sobrante a la siguiente; si falta, se compra más. ¿El locate es de la posición o de la estrategia? Si dos estrategias lo usan, ¿quién paga?

## F. Halts

- [ ] F1. ¿Cómo sabe el bot que hay halt: L1 de DAS, ausencia de prints, fuente externa (Nasdaq Trader)? ¿Con qué latencia? **[API]**
- [x] F2. → R-F-01 (borrador; ruta de salida pendiente PDF). Halt con posición dentro: ¿DAS cancela el stop residente? ¿Se prepara orden para la reapertura, límite o mercado en la subasta? **[API]**
- [x] F3. → R-F-04 (cancelar y reevaluar al reabrir). Halt con orden de entrada en vuelo: ¿se cancela siempre?
- [x] F4. → R-F-01 (reabre por encima del stop → mercado; por debajo → nada). Reapertura: ¿precio de referencia para decidir si salir (stop saltado, reabre por encima)? ¿Se sale en el primer print o se espera N s? **[dato]** el SL en la vela de reapertura se llena de mediana −3 % y p90 +4,8 % peor que el nivel, máx +14,5 %.
- [x] F5. → R-F-01 (3 halts up seguidos = cierre a mercado al reabrir) y R-F-03 (sin reentrada). Cadena de LULD (≥ 5 en el día): ¿no ampliar, reducir o cerrar? **[dato]** 6+ halts llegan de mediana a ×2 y no vuelven; PAVS 7 halts ×13.
- [x] F6. → R-F-05. T1 (noticia pendiente) con posición: puede durar horas. ¿Aviso y esperar? ¿Y si dura hasta el cierre?
- [x] F7. → R-F-05 (aviso y control humano). T12 con posición: capital bloqueado días, locate que sigue corriendo, posible buy-in. ¿Cómo se contabiliza y quién avisa al socio?
- [x] F8. → R-F-06 (límite removiendo liquidez, ruta rápida pendiente PDF). Halt en premercado (raro, existe: NEXI): ¿mismas reglas que en sesión?
- [ ] F9. ¿Tratamiento distinto para LULD, T1, T12 y halts de otras bolsas? **[API: códigos que entrega DAS]**
- [x] F10. → decidido: sí se entra en SSR; sin regla de salida por SSR. SSR activado a mitad de sesión: no afecta a cubrir, sí a abrir cortos nuevos. ¿Cómo se sabe y cuál es la regla? **[API]**
- [x] F11. → R-F-02 (stop 1-2 % bajo la banda si queda por encima; la banda llega como dato, confirmar [API]). Bandas LULD: ¿DAS las da? Si no, ¿se calculan (5/10/20 % según precio y hora)? **[API]**
- [x] F12. → decidido: se opera normal; el calendario ya está en el sistema. Media sesión o cierre anticipado: ¿el bot lo sabe y adelanta el cierre forzoso?
- [x] F13. → R-F-04 (se guarda; X % de la primera vela pendiente de estudio). Halt en el minuto de la señal (la señal se generó con la vela anterior al halt): ¿se ejecuta a la reapertura o se anula?

## G. El precio se dispara

- [x] G1. → R-G-01 (protocolo: informar cada 5 min, cierra el humano). Fogonazo (sube ≥ X % en ≤ Y s y devuelve): ¿el bot no ejecuta el stop y espera N s? ¿Con qué X, Y, N? **[dato]** con 3 % por ticker, cerrar en el pico pierde de media el 14 % (peor 145 %); esperar 30 s, 2,6 % (p95 5,8 %); a 5 min p95 7,2 %. 1 de cada 10 saltos ≥ 100 % no vuelve en PM.
- [x] G2. → R-G-01 (información del informe, no disparador). ¿Cómo distingue en vivo fogonazo de subida real: segundos sostenidos por encima de X % del salto, operaciones, volumen? ¿Con qué datos, si el NBBO de DAS avisa poco?
- [x] G3. → R-G-01 (humano). Pérdida máxima absoluta por posición: por encima de +Z % sobre la entrada, ¿cierre a mercado pase lo que pase? ¿Z distinto en PM y en RTH?
- [x] G4. → R-G-01 (humano). Squeeze lento (sube y no devuelve en 5-30 min): ¿salida por tiempo desde el pico? **[dato]** esperar más de 1 min no baja el p95; en ≥ 500 %, 5 de 8 vuelven en menos de 2 min y TNON, XHG y GRYP no.
- [x] G5. → R-C-01 (limitP con techo; nunca mercado sin techo). Orden basura en el libro (25 $, 10.000 $): ¿cómo se protege un cierre a mercado? ¿Siempre limitado con banda? **[dato]** 7 de 56 disparos tenían una orden basura en los 10 niveles.
- [x] G6. → R-G-01 (/cerrar TICKER N SI). Cierre por tramos durante un pico: ¿la mitad al +50 % y el resto cuando devuelve?
- [x] G7. → R-G-01 (dato del informe; humano). Si la pérdida latente de una posición supera la pérdida diaria, ¿se cierra esa posición o todo?
- [ ] G8. Buy-in del bróker (te obligan a cubrir): ¿cómo se entera el bot y cómo lo contabiliza? **[API]**
- [x] G9. → R-A-01 + R-B-01 (tope 3 %: no se entra). El precio se dispara con una orden de ENTRADA viva (aún no dentro): ¿se cancela por distancia al precio de señal (A2) o se deja?
- [x] G10. → R-G-01 (4): se registra cada fogonazo. ¿Se registra cada fogonazo visto en vivo (con o sin posición) para calibrar X, Y, N con datos propios?

## H. Locates y préstamo

- [x] H1. → R-H-01 (pronto y barato: al entrar en el radar; se compra cuando el EV da ventaja). ¿Cuándo se pide el locate: en prealerta (44-59), al confirmar la señal, o cuando el ticker «salta» pronto porque es más barato? (P4)
- [x] H2. → R-H-01 (cálculo de EV existente; se actualiza el precio hasta que haya ventaja). ¿Cuánto se paga como máximo por acción y como % del beneficio esperado? ¿Se descarta la operación si el locate supera X % del EV? **[dato]** la puerta por EV ya existe en el backtester (`PROYECTO_EV_Y_LOCATES.md`).
- [x] H3. → R-H-04 (se opera con lo que hay y se sigue buscando). Locate parcial (dan 500 de 1.000): ¿se opera con menos, se pide a otro proveedor o se descarta?
- [x] H4. → coste hundido aceptado; tope R-H-03 (3 % de la cuenta). Locate comprado y operación que no se da: ¿coste hundido aceptado? ¿Tope diario de locates «desperdiciados»?
- [x] H5. → R-H-03: nunca más del 3 % de la cuenta. Tope diario y por operación de gasto en locates. **[dato]** una operación se llevó 7.000 $ de 10.000 en el backtest.
- [ ] H6. Paquetes de 100: ¿se ajusta el tamaño de la posición al múltiplo del locate? **[dato]** se cobra por paquetes enteros, no es lineal. **PREGUNTAR A JAUME (lo pidió el 15-sep): ¿a partir de cuántas acciones de excedente merece la pena pagar un paquete de locate más?** Ejemplo: el cálculo pide 105 acciones → 2 locates; pagar un locate por 5 acciones es tirar el dinero, así que se juega con 100 y se sacrifican esas 5. Hay que fijar el umbral (en acciones o en % del paquete, o en coste del locate frente al beneficio esperado de esas acciones).
- [ ] H7. ¿Los locates caducan al cierre? ¿Sirven para reentradas el mismo día? ¿Se pueden devolver y con qué reembolso? **[API]**
- [ ] H8. El precio del locate cambia entre la consulta y la aceptación: ¿se acepta hasta +X %? **[API]**
- [ ] H9. Varios proveedores: ¿se elige el más barato automáticamente? **[API]**
- [ ] H10. ETB (no hace falta locate): ¿cómo se sabe y se salta el paso? HTB imposible: ¿se descarta la señal y se registra? **[API]**
- [ ] H11. ¿Hay locates en premercado a cualquier hora (04:00)? ¿A qué hora empieza el servicio? **[API]**
- [x] H12. → avisar; lo gestiona el humano con el bróker. Locate aceptado y luego halt o T12: ¿coste del préstamo por días? ¿Quién lo vigila?
- [x] H13. → R-H-01 (registrado). Registro de cada locate (precio, hora, usado o no) para alimentar la puerta por EV con datos reales.
- [x] H14. → no aplica: sin posiciones overnight (R-D-02). Dividendos con corto: si por error queda una posición overnight en fecha ex-dividendo, ¿quién lo detecta?
- [ ] H16. **(Añadida por Jaume, 16-sep, problema real del socio)** Al hacer «inquire» de locates el bróker no devuelve nada, o no hay locates disponibles para esa acción: ¿qué hace el bot? ¿Reintenta (cuántas veces, cada cuánto), prueba otro proveedor, descarta la señal y lo registra, avisa? ¿Y si la falta de locates llega en una PIRÁMIDE con posición ya abierta? **[API: qué respuesta da DAS cuando no hay locates]**
- [x] H15. → R-H-03. ¿Tope de locates «en reserva» a la vez (comprados y sin usar) para no quemar la cuenta en prealertas?

## I. Capital, riesgo y cortacircuitos

- [x] I1. → decidido: SIN cortacircuito diario de momento (solo lo que marque la estrategia); repreguntar más adelante. Pérdida diaria máxima: ¿valor, se cuenta realizada + latente, quién corta (bot, ajustes de riesgo de DAS, ambos), y qué se hace al cortar (cerrar todo, cancelar todo, bloquear hasta mañana)? **[API: ajustes de riesgo de la cuenta]**
- [x] I2. → sin tope propio del bot: lo marca la estrategia (I1). Pérdida máxima por operación y por ticker-día.
- [x] I3. → sin regla; manda la estrategia. Racha: ¿N pérdidas seguidas paran el día? ¿Una semana en negativo reduce el tamaño?
- [x] I4. → reparto del cuadro de mandos (E3) + margen real de Sage (2c). Exposición total y por ticker (P3: 3-4 % barajado): ¿sobre qué capital, el equity del día, el inicial o un mínimo fijado?
- [x] I5. → R-I-01 (lo limita el capital; se entra con lo que quede). Número máximo de posiciones simultáneas y de órdenes vivas.
- [x] I6. → R-B-05 (acumulado del día, tope desactivado). Fracción máxima del volumen reciente (M9): ¿de qué ventana y qué múltiplo? ¿Se aplica también a la salida?
- [x] I7. → bot: capital libre = BP real (R-I-01, 2c); qué hace Sage: pregunta al bróker (apartado R 16). Cuenta muy en negativo en premercado: ¿qué hace Sage? (P1) ¿Y el bot: deja de abrir por debajo de X de equity?
- [x] I8. → pregunta al bróker (PDT con < 25 k$, apartado R 16). PDT y mínimos de cuenta: ¿el bot vigila el número de day trades y el equity mínimo?
- [ ] I9. Llamada de margen: ¿reacciona el bot o es humano? **[API]**
- [x] I10. → R-I-02 (tamaños y escalones en el cuadro de mandos, no el bot). Escalón inicial (canario): ¿1 acción, 100 $, 1 % del tamaño final? ¿Quién autoriza subir y con qué criterio?
- [x] I11. → R-I-02 (tamaño fijo hasta que el humano lo cambie). ¿Reducción automática del tamaño tras días malos o tamaño fijo hasta que un humano lo cambie?
- [x] I12. → R-I-03 (siguiente señal; cuadro de mandos manda). Los topes viven en el JSON de la estrategia y en el cuadro de mandos: si difieren, ¿cuál manda? ¿Se pueden cambiar en caliente y desde dónde?
- [x] I13. → B13 (mantener con stop y avisar). Un tope que se supera por un fill peor de lo esperado (no por decisión): ¿se corrige al instante o se tolera hasta la salida?
- [x] I14. → R-O-02 (tablas de casos y días grabados antes de cada versión). ¿Los cortacircuitos se prueban cada día en seco (simulacro) o solo cuando saltan?

## J. Infraestructura: VPS, luz, comunicaciones

- [x] J1. → R-J-05 (SAI con PC y router; PENDIENTE comprarlo). Se va la luz en casa (fase PC): ¿SAI? ¿Cuánto aguanta? ¿Bastan los stops residentes?
- [x] J2. → R-J-01 (30 s prealerta, 60 s emergencia). Se corta Internet en casa: ¿4G de respaldo? ¿A partir de cuántos segundos sin feed se pasa a «no abrir, solo gestionar» y cuántos a «cerrar todo»?
- [x] J3. → R-J-02 (aviso máximo, reconexión 2/4/8/16/30 s, aviso cada 5 min). Se cae la conexión bot↔DAS (socket local): ¿reconexión automática, cuántos intentos, qué pasa con las órdenes en vuelo? **[API]**
- [x] J4. → R-J-02 (relanzar y reloguear; 2FA [API]). Se cae DAS (la aplicación): ¿el supervisor la relanza y reloguea sola? ¿Hay 2FA que lo impida? **[API]**
- [x] J5. → runbook (teléfono del bróker, app, cierre manual). Se cae Sage o el servidor de DAS: ¿teléfono del bróker, app móvil, plan de cierre manual? (runbook)
- [x] J6. → R-D-05 (precio de DAS para gestionar lo abierto). Se cae Massive: ¿fuente alternativa (L1 de DAS) solo para gestionar lo abierto?
- [x] J7. → R-J-04 (relanzar cada 30 s, aviso). Se cae el bot (excepción): ¿supervisor, tiempo máximo caído, reconciliación al volver, aviso por Telegram?
- [x] J8. → R-J-04 (10 s). Bot colgado sin morir (latido parado): ¿quién lo mata y lo relanza?
- [x] J9. → R-J-04 (cerrojo obligatorio). Dos instancias del bot a la vez (dos PIDs, relanzar sin matar): ¿cerrojo de instancia única?
- [x] J10. → R-J-06. VPS: proveedor, ubicación (cerca de NY), Windows Update forzado (ventana de mantenimiento fuera de mercado), reinicios, una sola sesión RDP, coste.
- [ ] J11. Un solo login de DAS por cuenta: si Jaume abre DAS en casa, expulsa al bot. ¿Segunda cuenta? (P1) **[API]**
- [x] J12. → R-J-07 (ET; desvío > 2 s = no operar). Reloj y zona horaria del VPS (todo en ET; DST distinto al de España).
- [x] J13. → R-J-07 (rotación diaria; aviso < 5 GB). Disco lleno por logs y diario: ¿rotación y tope?
- [x] J14. → R-J-07 (humano; el bot avisa). Actualización forzada de DAS: ¿cómo se detecta y quién la hace?
- [ ] J15. Sesión de DAS que caduca de noche: ¿relogin antes de las 04:00 y comprobación? **[API]**
- [x] J16. → R-J-03 (tabla). Modo degradado: tabla de qué se permite en cada estado (todo bien / sin feed / sin DAS / sin bot / sin Telegram).
- [x] J17. → R-J-05 (ping 60 s, alarma a los 3 min). Vigilante externo: si el bot no da señal de vida en N min, ¿alguien recibe aviso aunque el propio bot esté muerto?
- [ ] J18. **PENDIENTE para el repaso final (Jaume, 18-sep): sin referencia hasta operar con el API.** Latencia: ¿se mide ida y vuelta orden→confirmación y a partir de cuánto no se opera?
- [x] J19. → R-J-08 (sigue operando, reintenta; canal alternativo en M4: correo + SMS/llamada para el nivel máximo). Caída del proveedor de Telegram: ¿el bot sigue operando o se pausa por falta de canal de aviso?
- [x] J20. → R-J-06 (DAS → vigilante → ejecutor + reconciliación). Reinicio del VPS por el panel del proveedor (el socio): ¿arranque automático de DAS y bot con reconciliación antes de nada?

## K. Estado y reconciliación

- [x] K1. → R-K-01 (eventos al instante + barrido cada 2 s / 10 s; tras fill y reconexión). Fuente de la verdad: DAS. ¿Cada cuántos segundos se reconcilia y qué se compara (posiciones, órdenes vivas, cuenta)?
- [x] K2. → R-C-10 caso 4. Posición en DAS que el bot no conoce: ¿aviso y no tocar, o adoptar con stop?
- [x] K3. → R-C-10 caso 3 / R-K-01. Posición que el bot cree tener y DAS no: ¿se limpia el estado y se avisa?
- [x] K4. → R-C-10 + R-C-11 (cancelar las del lote que sobren; las desconocidas: aviso). Órdenes vivas que el bot no conoce: ¿cancelar o dejar?
- [x] K5. → R-K-02 (no opera a mano en la cuenta del bot; solo emergencias). Operaciones manuales de Jaume en la misma cuenta: ¿cuenta separada, o etiqueta que el bot respeta? ¿«Cerrar todo» cierra también las manuales?
- [x] K6. → R-C-10 (reconciliación al arrancar) + R-A-05. Reinicio a media sesión: ¿qué se recupera del disco (posiciones, órdenes, locates, señales ya ejecutadas) y qué se rehidrata del feed?
- [x] K7. → R-A-05 (id estable) + token de orden. Idempotencia por id de evento (`ticker|estrategia|momento|tipo`): si la misma señal se reevalúa tras un reinicio, ¿se reconoce como ya ejecutada?
- [x] K8. → R-N-01 (antes y después, M6). ¿El diario JSONL se escribe antes de enviar la orden y después de la respuesta, siempre, aunque el disco esté lento?
- [x] K9. → sin cuadre (R-N-01); se registra. Divergencia entre fills del diario y los de DAS al final del día: ¿tolerancia y quién la revisa?
- [x] K10. → R-L-01 (el día cierra al apagar tras el último EOD; contadores por día). Cambio de día: ¿cuándo «cierra» el día el bot y se resetean contadores (pérdida diaria, reentradas, locates)?
- [x] K11. → R-K-03 (30 s con el último estado bueno, luego no abrir + aviso). Si la reconciliación misma falla (DAS no contesta), ¿el bot sigue operando con el último estado bueno o se para?

## L. Horario y calendario

- [x] L1. → JSON de la estrategia (R-L-02). Ventanas de operación por estrategia (PM 04:00-09:30, RTH) y ventanas prohibidas (primeros N s tras las 09:30, últimos N min).
- [x] L2. → calendario de Massive (F12). Festivos y medias sesiones: ¿fuente (Massive) y qué hace el bot ese día?
- [x] L3. → R-J-07. Horario de verano: todo en ET; ¿el bot lo comprueba solo?
- [x] L4. → no (R-D-02). ¿Se permite alguna posición overnight? Si no, hora límite dura de cierre y margen.
- [x] L5. → R-L-01 (encendido solo PM + parte de RTH; apagado fuera). Fin de semana y días sin operar: ¿apagado o vigilante en marcha?
- [x] L6. → R-L-02 (paridad + revisión manual + comprobación del bot). La sesión de la estrategia se SUMA, no sustituye (trampa conocida del backtester): ¿el bot lee la sesión como el backtester o la corrige?
- [x] L7. → tarea humana (A10). Días con evento macro conocido: ¿lista manual de no operar?

## M. Control humano y avisos

- [x] M1. → R-M-04 (lista de comandos y coherencia tras cierre). Comandos de Telegram: `/estado`, `/pausar` (no abrir), `/cerrar_todo SI`, `/reanudar`. ¿Quién está autorizado (chat_id)? ¿Confirmación en dos pasos?
- [x] M2. → R-M-01 (tres niveles). Qué se avisa (entradas, salidas, errores, reconciliación fallida, latido perdido) y qué no (prealertas). (M8)
- [x] M3. → R-M-01 (resumen diario + comando detalle). ¿Silencio si todo va bien? ¿Resumen al cierre del día?
- [x] M4. → R-M-02 (correo + SMS de pago por uso para el nivel Máximo). Si Telegram falla: ¿canal alternativo (correo, SMS)?
- [x] M5. → runbook borrador (docs/BOT_EJECUCION_RUNBOOK.md), definitivo al final. Socio: qué puede hacer sin Jaume (pausar, apagar el VPS, cerrar todo en DAS) y runbook de una página.
- [x] M6. → R-M-03 (proteger, avisar, pausar entradas hasta «sigue»). Si un humano opera en DAS por RDP mientras el bot corre, ¿el bot lo detecta y se pausa?
- [x] M7. → no; capital mínimo o demo al principio. ¿Se pide confirmación humana para algo (primera operación del día, tamaño mayor que X) o nunca?
- [x] M8. → apagar ese día o modo de seguridad (R-I-04). Guardia: ¿alguien mira el premercado cada día? ¿Qué pasa si nadie puede?
- [x] M9. → R-I-03 (siguiente señal, cuadro de mandos manda) + R-N-01 (quién cambió qué). ¿Cómo se cambia un parámetro en caliente y cómo queda registrado quién lo cambió?

## N. Registro, contabilidad y auditoría

- [x] N1. → R-N-01. Diario JSONL: qué campos por decisión (señal, guarda, orden, respuesta, fill, stop, locate, reconciliación).
- [x] N2. → R-N-01. Comisiones, ECN, tasas SEC/FINRA, locates, plataforma: ¿el bot calcula el PnL neto o se toma de DAS?
- [x] N3. → R-N-01. Reconciliación diaria del PnL con el extracto del bróker: tolerancia y proceso.
- [x] N4. → R-N-01. Métricas de ejecución: slippage real frente a la señal, tiempo señal→fill, % de rechazos, por ruta y por hora.
- [x] N5. → R-N-01. ¿Basta el diario para reproducir cada decisión de un día concreto sin el feed?
- [x] N6. → R-N-01. Exportación fiscal y conservación de los diarios.

## O. Pruebas, sombra, canario y despliegue

- [x] O1. → SÍ hay demo (Jaume, 19-sep); cómo se accede por API, con el PDF. ¿Hay demo o paper en DAS con Sage? Si no, ¿la sombra sustituye del todo? **[API]**
- [x] O2. → decisión al final. Sombra: ¿cómo se comparan las órdenes calculadas con los fills manuales de Jaume (exportación de DAS)?
- [x] O3. → decisión al final. Canario: tamaño, duración, criterios de salida (ya en la submemoria) y quién decide subir de escalón.
- [x] O4. → R-O-01. Versionado de estrategias: JSON con hash y fecha; ¿cómo se despliega una versión nueva sin tocar el bot en marcha? **[dato]** el bot de avisos lee las estrategias UNA vez al arrancar.
- [x] O5. → R-O-01. Cambios de código con el bot vivo: prohibidos en mercado. ¿Ventana de despliegue y comprobación de arranque limpio?
- [x] O6. → R-O-02 + simulacros de R-J-02/R-J-04/R-J-06. Pruebas de la guarda con tablas (función pura); simulacro de reconexión; simulacro completo del socio.
- [x] O7. → R-O-02 fijada. ¿Repetición de un día grabado contra el ejecutor en seco antes de cada versión?
- [x] O8. → R-O-02 fijada (versiones por fecha). Vuelta atrás: ¿cómo se recupera la versión anterior en 5 min?
- [x] O9. → canario a tamaño mínimo + repetición de días grabados. ¿Qué se prueba con dinero real que no se puede probar de otra forma (locates, rechazos, halts)? ¿Cómo se fuerza?

## P. Backtester frente a vivo

- [x] P1. → se mide en sombra; motor intacto. Fills en reaperturas: el motor llena al nivel, el vivo al open. ¿Se mide y se corrige el motor o se acepta?
- [x] P2. → recomendación de evaluación, no regla. Liquidez infinita del motor: ¿tope de fracción de volumen también en el backtest para que sean comparables? **[dato]** 1B: 152× el volumen de la vela.
- [x] P3. → idem P2. Ventana de entrada i+1 y slippage como fracción: ¿el bot replica o mejora? ¿Cómo se compara luego?
- [x] P4. → registrar locates reales y recalibrar. Locates aleatorios en el backtester frente a reales: ¿se registra el precio real para recalibrar la distribución?
- [x] P5. → se mide en sombra. Halts y SSR no están en el motor: ¿el bot los añade como guarda aparte (tabla auxiliar de halts), y el backtester después?
- [x] P6. → R-A-02. Prints tardíos en las velas AM: ¿la señal en vivo se calcula con la misma cinta que el backtest?
- [x] P7. → sin parada automática; solo registro. ¿Cuándo se para el bot por divergencia con el backtest (acierto, slippage p95, frecuencia de señales)?
- [x] P8. → R-A-04. Indicadores del backtester que no existen en vivo (Overhead, métricas RTH antes de las 09:30): ¿lista cerrada y bloqueo?

## Q. Seguridad

- [x] Q1. → R-Q-01. Credenciales de DAS y token de Telegram en `.env`, fuera del repo. ¿Quién tiene acceso al VPS y con qué usuario?
- [x] Q2. → R-Q-01. Comandos de Telegram solo desde chat_id autorizados: ¿qué pasa si roban el teléfono?
- [x] Q3. → R-Q-01 (antes de dinero real). La fuga de tokens de httpx en los logs (aplazada): ¿se arregla antes del VPS con dinero real?
- [x] Q4. → R-Q-01. Copias del diario y del estado fuera del VPS.
- [x] Q5. → R-Q-01. RDP expuesto a Internet: ¿VPN o IP fija?
- [x] Q6. → R-Q-01 [API]. ¿Puede el bot enviar dinero o cambiar ajustes de la cuenta por API? Si sí, ¿cómo se le impide? **[API]**

---

## R. Consolidado: lo que hay que saber sí o sí del API de DAS

**19-sep: apareció el manual oficial del CMD API (rev. 2021-11) en el repo das-bridge; lo que dice está en el libro de reglas, apartado 2b. Es de 2021 y PUEDE ESTAR DESFASADO: todo se coteja con el PDF del bróker.** Para repasar el día que llegue el PDF, en este orden:

1. Identificador de orden propio: SEGÚN EL MANUAL 2021 existe (token en NEWORDER; %OrderAct con Send_Rej / CancelRej / TimeOut). Cotejar y pedir los textos de «notes». (B5, B16)
2. Stops: SEGÚN EL MANUAL 2021 hay STOPLMT (disparo + límite) por la ruta SMAT (admite todos los stops). PENDIENTE: por qué precio dispara (último/bid/ask, C6), si dispara en PM (C3), qué pasa en un halt (C16), distancia mínima (C15), tope de stops vivos (C11), si existe REPLACE.
3. Tipos de orden: SEGÚN EL MANUAL 2021: MKT, límite, PEG, STOPMKT, STOPLMT, STOPTRAILING, STOPRANGE, oculta (Display=0); TIF DAY, DAY+, IOC, GTC, AtOpen, AtClose, FOK. **NO hay OCO/bracket** → limpieza por el bot (R-C-11). Cotejar. (B7, B17, D1)
4. Rutas: cuáles admiten premercado, cuáles urgen para salir, coste por ruta. (B7, D9)
5. Motivos de rechazo que devuelve, y en qué formato. (B4)
6. Lotes máximos, decimales por debajo de 1 $, redondeo. (B9, B10)
7. Locates: SEGÚN EL MANUAL 2021 hay juego completo de comandos (SLPRICEINQUIRE con precio POR ACCIÓN y tamaño 0 = no hay; SLNEWORDER; SLOFFEROPERATION Accept/Reject; SLAvailQuery; estados %SLOrder; «Already Shortable» = ETB). PENDIENTE: tipo de ruta de locate de Sage (0 o 1), nombres de rutas, caducidad, devolución, horario. (B15, H7-H11, H16)
8. Bandas LULD: SEGÚN EL MANUAL 2021 llegan ($LDLU con Lv1). PENDIENTE: halt y motivo, y bandera SSR: NO están en $Quote ni T&S → fuente externa o rechazo de orden. (F1, F2, F9, F10, B14)
9. Buying power: SEGÚN EL MANUAL 2021: GET BP (intradía y overnight) y GET SHORTINFO (shortable, tamaño máximo por orden, tasas de margen del símbolo). PENDIENTE: reglas de margen de Sage en detalle (apartado 2c del libro), autoliquidación, PDT, buy-in. (E6, I1, I9, G8)
10. Socket: SEGÚN EL MANUAL 2021 hay mensajes de estado de OrderServer/QuoteServer, modo «watch» (solo lectura) y comando CLIENT (número de clientes conectados → varias conexiones posibles). PENDIENTE: si una segunda conexión normal puede enviar órdenes, relogin, 2FA, sesión de noche, un login por cuenta. (J3, J4, J11, J15, C12)
11. Cuota y límite de mensajes por segundo. (J18)
12. Demo o paper. (O1)
13. Qué NO puede hacer el API (transferencias, ajustes de cuenta). (Q6)
14. **Lista completa de códigos de LOG y de ERROR que puede devolver el API** (órdenes, locates, conexión), para poder detectarlos y tratarlos uno a uno (Jaume, 16-sep).
15. Unidades del precio del locate (por acción o por paquete de 100) y cómo se compra (comando, confirmación, qué devuelve si no hay). (H1, H16)

## Registro

| Fecha | Qué |
|---|---|
| 2026-09-12 | Se abre el banco con 17 áreas y el consolidado para el PDF. Ninguna contestada. |
16. **Reglas de margen de Sage (19-sep, apartado 2c del libro):** qué valores son «alto riesgo» (criterio), si GET BP ya descuenta el margen por símbolo, autoliquidación en RTH (hora, aviso), corto en PM que supera el margen, PDT con cuenta < 25 k$, llamadas de margen.

17. **[Sage] Halt largo (T12) con un corto dentro: ¿qué comisión, coste de préstamo (hard-to-borrow) o cargo por locate cobran por cada día que la posición siga atrapada? ¿Hay buy-in forzoso? (Jaume, 20-sep: RECORDÁRSELO al preguntar al bróker.)*
18. **[API] Datos por API: ¿cuántos símbolos admite a la vez el Level 1 y el Time & Sales ($Quote / $T&S)? ¿Depende del plan de datos contratado? (Jaume, 21-sep: para construir las velas del radar desde DAS.)**
19. **[API/Sage] ¿El feed de precios de DAS es consolidado de todas las bolsas (SIP) o solo Nasdaq? ¿Qué operaciones excluye del Time & Sales (lotes sueltos, prints tardíos, condiciones)? Necesario para que las velas del bot coincidan con las del backtester (Massive).**
20. **[API] ¿El API admite órdenes «post only» / «add liquidity only» (ARCA ALO, EDGA post-only), que se rechazan o recolocan en vez de remover? ¿Con qué sintaxis?**
21. **[API/Sage] Orden PEG MID del manual 2021 (pegada al punto medio): ¿qué rutas la admiten, funciona en premercado, cobra el mismo rebate que una límite que descansa o tiene tarifa propia? ¿Admite precio límite y Display=0?**
22. **[API] StopLimitP («LimitP», dispara por ÚLTIMO PRECIO): ¿existe por el API además de STOPLMT? ¿Cuál es el precio de disparo de cada uno (último / bid / ask) y cuál recomiendan en premercado? ¿Un print tardío o fuera de secuencia puede dispararlo?***