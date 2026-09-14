# REGLAS del bot de ejecución en DAS (Sage Trading)

> **Qué es este fichero.** El libro de reglas que dirigirá al bot de ejecución.
> Es el documento que el código tiene que obedecer y el que se lee cuando algo
> sale mal para saber qué debía haber pasado. Abierto el 2026-09-12. Se
> construye contestando el banco de preguntas de `BOT_EJECUCION_PREGUNTAS.md`:
> cada pregunta contestada se convierte en una regla de aquí (o en un «no
> aplica» razonado), con su número y su estado.
>
> Las conclusiones del estudio de cisnes negros (`Informe_cisnes_negros_premercado.pdf`,
> `Resumen_ejecutivo_riesgos.pdf`) NO son reglas hasta que se escriban aquí con
> su número. Regla de trabajo: nada entra sin fecha y sin estado.

---

## 0. Cómo se escribe una regla

Cada regla lleva un identificador `R-<ÁREA>-<nn>` (las áreas son las letras del
banco de preguntas: A señal, B entrada, C stop, D salidas, E capital compartido,
F halts, G disparos de precio, H locates, I riesgo y cortacircuitos, J
infraestructura, K estado y reconciliación, L calendario, M control humano, N
registro, O pruebas y despliegue, P backtester vs vivo, Q seguridad).

Plantilla (todos los campos, aunque sea para poner «ninguno»):

```
### R-X-nn · Título corto
- Situación: cuándo aplica. Condición observable y medible, no una intención.
- Detección: qué dato la dispara y de dónde sale (DAS, feed de Massive, reloj, diario).
- Acción: qué hace el bot, en orden, y en cuánto tiempo.
- Quién la ejecuta: guarda pura / ejecutor / reconciliación / supervisor / humano.
- Parámetros: nombre, valor por defecto y dónde vive (JSON de la estrategia o cuadro de mandos).
- Si la acción falla: plan B (degradación) y aviso.
- Prueba: cómo se verifica (tabla de casos, simulacro, sesión sombra, canario).
- Estado: borrador / decidida (fecha) / depende del PDF (pregunta X) / descartada (por qué).
- Origen: pregunta del banco (p. ej. C5) y dato del estudio que la sustenta.
```

Criterios para que una regla sea válida:

1. Se puede comprobar con una tabla de casos sin mercado delante.
2. Dice qué pasa cuando la propia regla no se puede cumplir.
3. No depende de que un humano esté mirando, salvo que lo diga expresamente.
4. Un parámetro no es una regla: la regla dice qué se hace con el parámetro.
5. Si dos reglas chocan, gana la más restrictiva; si no está claro, se escribe
   una tercera que lo resuelva.

## 1. Principios marco (decisiones ya tomadas por Jaume el 5-sep-2026)

No son reglas numeradas: son el marco que ninguna regla puede contradecir.
Cualquiera se puede rebajar, pero por escrito y con fecha.

- **M1.** Bot DISTINTO al de avisos. Reutiliza su código, es otro proceso.
- **M2.** Por fases, cada fase con sus pruebas; no se pasa a la siguiente hasta
  que la anterior funciona. Eficacia y cero errores antes que velocidad.
- **M3.** Posición objetivo, no traducción evento→orden: el motor dice qué
  posición debería haber; el ejecutor acerca la real a la objetivo dentro de límites.
- **M4.** Cinco capas con interfaz mínima: señal, guarda pura, ejecutor,
  reconciliación, diario + supervisor.
- **M5.** Invariante: ninguna posición sin stop residente en el bróker.
- **M6.** Invariante: la orden va antes que cualquier registro que pueda bloquearse.
- **M7.** Invariante: la posición real (DAS) manda sobre la teórica, siempre.
- **M8.** Telegram solo para lo que importa: entradas, salidas, datos concretos
  y errores. Las prealertas no van a Telegram (sirven para procesos internos).
- **M9.** Tamaño por fracción del volumen reciente desde el principio.
- **M10.** Premercado = órdenes límite (en PM no hay órdenes a mercado).
  Matiz de Jaume (12-sep): la idea de «asegurar la salida aunque sea a peor
  precio» NO es un principio: depende de si es PM o RTH, puede no interesar, y
  choca con el fogonazo, donde a veces se quiere NO cerrar. Cómo se sale y a
  qué precio se decide regla a regla en las áreas C, D y G.
- **M11.** La exposición al riesgo viaja en el JSON de la estrategia y tiene
  cuadro de mandos propio.
- **M12.** Producción en VPS Windows con DAS dentro; desarrollo en el PC de
  Jaume; el VPS es lo último pero se prepara pronto. El socio puede pausar,
  apagar y reiniciar.
- **M13.** Guardas diseñadas para las dos sesiones (PM y RTH) desde el inicio.

## 2. Puntos abiertos que condicionan varias reglas (no decididos)

- **Stop limitado vs stop de mercado** (P2). Recordárselo a Jaume. Datos en
  el informe v5 §11 y v6 §13.
- **Guarda de fogonazo**: no ejecutar si el precio subió más de X % en Y s;
  esperar N s. Datos en el informe §9 y resumen «Riesgo 1».
- **Exposición por ticker** (P3): 3-4 % barajado, nada decidido.
- **Locates pronto y barato vs en prealerta** (P4).
- **Cadena de LULD como aviso** (P10): 1 de cada 300 días con ≥ 5 LULD acaba en T12.

## 3. Reglas

*(Ninguna todavía. Se van añadiendo por área a medida que se contesta el banco
de preguntas. Orden previsto de ataque, por riesgo: C y G (stop y disparos),
F (halts), I (cortacircuitos), B (entrada), H (locates), J y K (infraestructura
y reconciliación), después el resto.)*

### Área C · Stop y protección

### R-C-01 · Stop en tres niveles con límite, y cuarto nivel «cisne negro»
- Situación: el bot abre un corto. Aplica desde el fill de entrada hasta el cierre.
- Detección: el precio toca cada nivel (trigger). Cómo detecta DAS o el bot el toque (último precio, bid/ask) → C6 [API].
- Acción: tres triggers escalonados por encima de la entrada (N1 < N2 < N3), cada uno con orden de compra LIMITADA (cubrir = comprar, se paga el ask). El límite se pone por encima del ask para asegurar la salida: en N1 y N2 muy poco por encima; en N3 (emergencia, el precio ya se ha disparado mucho) bastante más por encima. Si N1 no consigue cerrar, entra N2; si N2 no, N3. Si el precio pasa de largo N3 sin llenarse, y se cumplen unas condiciones por definir (área G), se considera cisne negro y el bot NO cierra: espera del orden de media hora y se reevalúa.
- Quién la ejecuta: ejecutor (colocar y sustituir órdenes) + guarda (condiciones de cisne negro).
- Parámetros: N1, N2, N3 en % sobre la entrada (o según estructura); margen del límite sobre el ask en cada nivel, en % (pequeño en N1/N2, grande en N3); espera tras pasar N3 (≈ 30 min). Nunca precios fijos: todo en % porque depende del precio de cada acción. Valores: los da Jaume, van al cuadro de mandos.
- Si la acción falla: N3 sin llenar y sin condiciones de cisne negro → por definir (C5).
- Prueba: tabla de casos con precio caminando por N1, N2, N3 y pasando de largo; réplica en sombra.
- Estado: BORRADOR (12-sep). Pendiente: (a) confirmar con el socio; (b) RTH: Jaume cree que igual, no lo tiene claro; (c) [API, PRIORITARIO] la idea de Jaume es UN solo stop con varios triggers (los tres niveles dentro de la misma orden), porque un evento así va muy rápido y no da tiempo a que el bot cancele y reponga tres stops; hay que confirmar con el PDF si DAS lo admite. Si no lo admite, se decide entonces cómo hacerlo; (d) cómo se define «no consigue cerrar» en cada nivel (tiempo o precio que supera el límite) → C5; (e) condiciones de cisne negro → G1/G2.
- Origen: C1. Directriz de Jaume del 12-sep.

### R-C-02 · Paso de un nivel de stop al siguiente
- Situación: el precio ha tocado un trigger (N1 o N2) y la orden limitada de ese nivel no ha comprado todo.
- Detección: por PRECIO: el precio supera el trigger siguiente. Si no se compró nada, o se compró solo una parte (p. ej. 300 de 1.000), es porque el precio ha pasado por encima; lo que queda en corto pasa a intentar cerrar en el siguiente nivel. No hay criterio de tiempo.
- Acción: lo no cubierto se cierra con las condiciones del siguiente nivel (su trigger y su margen sobre el ask). Tras N3, aplica lo de R-C-01 (cisne negro, espera).
- Quién la ejecuta: idealmente DAS (un stop con varios triggers); si no, el ejecutor.
- Parámetros: los de R-C-01.
- Si la acción falla: por definir con el PDF.
- Prueba: tabla de casos (se compra todo / nada / parte) en cada nivel.
- Estado: BORRADOR (12-sep). NO SE PUEDE CERRAR hasta saber cómo funcionan los stops en DAS [API]: si admite varios triggers en un stop, si hacen falta varios stops, o si el bot tiene que vigilar el precio y cerrar a mercado él mismo.
- Origen: C5. Directriz de Jaume del 12-sep. Aclaración: el ÚNICO criterio de tiempo en los stops es el de después del tercer nivel (cisne negro, espera de media hora), y se especifica en el bloque de contingencias, no aquí.

### R-C-03 · Posición sin stop puesto en DAS
- Situación: hay posición abierta y DAS no tiene el stop aceptado: justo tras la entrada, o porque DAS lo ha rechazado o cancelado.
- Detección: el ejecutor no recibe la confirmación del stop, o la reconciliación ve posición sin stop.
- Acción: (1) volver a intentar poner el stop, hasta 5 intentos; (2) avisar al humano (Telegram o lo que se decida) si no se consigue; (3) si tras los 5 intentos sigue sin stop, cerrar la posición en ese momento, SIEMPRE QUE el precio no haya subido más de un 100 % desde que se intentó poner el primer stop (ventana de 5 minutos). Si ha subido más del 100 %, no se cierra: se trata como cisne negro (contingencias).
- Quién la ejecuta: ejecutor (reintentos y cierre) + supervisión (aviso).
- Parámetros: intentos = 5; ventana = 5 min; subida máxima para cerrar = 100 %. Separación entre intentos: por definir.
- Si la acción falla: el cierre tampoco se ejecuta → aviso urgente, humano.
- Prueba: simulacro con DAS rechazando el stop (demo o sombra).
- Estado: BORRADOR (12-sep). El punto (3) (cerrar tras 5 intentos con el tope del 100 %) NO está claro para Jaume: volver a preguntárselo cuando llegue el PDF.
- Origen: C4. Directriz de Jaume del 12-sep.

### R-C-04 · El stop desaparece a mitad de la posición
- Situación: el stop estaba aceptado en DAS y deja de estarlo (cancelado por halt, rechazo tardío, error).
- Detección: dos vías a la vez: (a) el aviso de cancelación que envíe DAS; (b) comprobación activa cada segundo de que el stop sigue puesto, si no resulta costosa para el API [API: cuota de mensajes].
- Acción: la misma lógica de R-C-03 (reintentar hasta 5 veces, avisar al humano, cierre condicionado). Excepción: si la causa es un HALT, no se puede hacer nada hasta la reapertura y entra la regla de halts (área F): con dos halts seguidos se cierra a mercado en cuanto reabra, con rutas concretas por definir; y habrá un protocolo aparte para cuando el precio se acerque a una banda LULD (limit up / limit down).
- Quién la ejecuta: reconciliación (detección) + ejecutor (R-C-03).
- Parámetros: intervalo de comprobación = 1 s (ajustable si el API lo penaliza).
- Si la acción falla: igual que R-C-03.
- Prueba: cancelar el stop a mano en demo/sombra y medir cuánto tarda el bot en verlo y reponerlo.
- Estado: BORRADOR (12-sep). Depende de F (halts) y de la cuota del API.
- Origen: C7. Directriz de Jaume del 12-sep.

### R-C-05 · Stop que se mueve (trailing, break-even)
- Situación: una estrategia recalcula el nivel del stop mientras la posición está abierta. Hoy NINGUNA estrategia lo hace; la regla queda escrita para cuando exista una.
- Detección: nuevo nivel calculado por el motor al cierre de cada vela de 1 minuto (el stop se mueve como mucho una vez por minuto y por posición).
- Acción: (1) poner primero el stop nuevo y después quitar el viejo (un instante con dos stops). (2) Si DAS no permite dos stops sobre la misma posición [API], quitar el viejo y poner el nuevo inmediatamente después, aceptando un instante sin stop, que queda cubierto por R-C-03 (posición sin stop) si el nuevo no se acepta.
- Quién la ejecuta: ejecutor.
- Parámetros: frecuencia = 1 vela de 1 min. Ninguno más.
- Si la acción falla: el nuevo no se acepta → R-C-03; el viejo no se puede quitar teniendo el nuevo → aviso, y nunca dejar dos stops activos más de un instante (riesgo de cubrir el doble).
- Prueba: tabla de casos (nuevo aceptado / rechazado; viejo cancelado / no) y sombra con una estrategia de trailing.
- Estado: BORRADOR (13-sep). Sin uso hasta que haya una estrategia que mueva el stop. Depende del PDF: dos stops a la vez en DAS.
- Origen: C8. Directriz de Jaume del 13-sep.

### R-C-06 · Stop al piramidar (una sola estrategia)
- Situación: la estrategia añade un lote a una posición abierta (p. ej. 1.000 → 1.500 acciones).
- Detección: fill del lote nuevo confirmado por DAS.
- Acción: UN solo stop para toda la posición: se MODIFICA el existente para que cubra las 1.500 acciones (procedimiento de R-C-05: primero el nuevo, luego el viejo; si no se puede, viejo y nuevo). El nivel lo dice la estrategia; lo más probable es que sea sobre el precio de la primera entrada. Los tres triggers de R-C-01 se recalculan sobre ese nivel.
- Quién la ejecuta: ejecutor.
- Parámetros: nivel del stop tras piramidar = el que defina la estrategia (por defecto, sobre la entrada).
- Si la acción falla: mientras el stop no cubra las 1.500, hay acciones sin stop → R-C-03 sobre el lote descubierto.
- Prueba: tabla de casos con 1, 2 y 3 lotes; sombra con una estrategia con pirámide.
- Estado: BORRADOR (13-sep). AVISO: esta regla vale para UNA estrategia. Con dos o más estrategias sobre el mismo ticker puede haber niveles de stop distintos y cambia; se aborda en el área E.
- Origen: C9. Directriz de Jaume del 13-sep.

### R-C-07 · Stop al cerrar una parte por take profit
- Situación: un take profit parcial cierra parte de la posición (p. ej. 1.500 → 1.000 acciones) y el stop sigue puesto para 1.500.
- Detección: fill del parcial confirmado por DAS.
- Acción: reducir el stop a las acciones que quedan (1.000) nada más confirmarse el cierre parcial. Un stop mayor que la posición, si salta, compra de más y deja la cuenta LARGA sin querer: eso se evita siempre. El nivel del stop NO se mueve: se queda donde estaba salvo que la estrategia diga otra cosa.
- Quién la ejecuta: ejecutor.
- Parámetros: ninguno.
- Si la acción falla (DAS no acepta la reducción): POR DECIDIR tras el PDF. Las dos opciones son posibles: (a) dejar el stop grande un momento, (b) quitar el stop y aplicar R-C-03. Jaume cree que no hará falta quitarlo: probablemente DAS deja cambiar solo la cantidad del stop [API].
- Prueba: tabla de casos (parcial 1 de 2, 2 de 2; reducción aceptada / rechazada).
- Estado: BORRADOR (13-sep). Pendiente post-PDF: el plan B cuando la reducción falla.
- Origen: C10. Directriz de Jaume del 13-sep.

**Pendiente para meditar con el PDF (Jaume, 13-sep), no es regla:** en una emergencia en la que la posición está «al descubierto» (sin stop, por un problema con el stop u órdenes que no se ejecutan) y el precio se acerca al nivel que tenía el stop, cerrar a partir de un X % de distancia hacia ese nivel. Choca con la lógica de cisne negro (no cerrar cuando se dispara); hay que meditarlo con toda la información del PDF. Enlaza con C12 (stop mental) y con las contingencias del área G.

### R-C-08 · Vigilancia constante del precio: el «vigilante» (segundo proceso)
- Situación: siempre que haya una posición abierta, con o sin stop puesto en DAS.
- Detección: un proceso APARTE del ejecutor (el «jefe» o vigilante) mira de forma continua: (a) el precio de DAS (no el de Massive) contra los niveles de cada posición; (b) que el stop siga puesto en DAS (R-C-04); (c) que el ejecutor esté vivo (latido). No participa en las órdenes normales, así que no añade latencia.
- Acción: si el precio pasa del nivel y DAS no ha ejecutado, o la posición está al descubierto, el vigilante ACTÚA (manda él la orden) según criterios por fijar: habrá situaciones en las que cierra y otras en las que NO debe cerrar (p. ej. el precio ha pasado los tres triggers incluido el de emergencia y se asume cisne negro: no ejecutar). Siempre avisa por Telegram.
- Quién la ejecuta: vigilante (proceso propio).
- Parámetros: por fijar: frecuencia de lectura del precio; criterios cerrar / no cerrar; distancia X % al nivel para el caso «al descubierto» (pendiente de C10).
- Si la acción falla: el vigilante no puede mandar la orden → aviso urgente, humano. Si el vigilante muere, el ejecutor lo detecta y avisa (y viceversa).
- Prueba: matar el ejecutor con posición abierta en sombra/demo y comprobar que el vigilante ve, actúa y avisa; simulacro de precio que pasa el nivel sin fill.
- Estado: BORRADOR (13-sep). Decidido: vigilancia constante y proceso aparte. Pendiente: los criterios de cuándo cierra y cuándo no (con el PDF y las contingencias). Dos requisitos [API]: (1) que DAS admita DOS conexiones a la vez con el mismo login (ejecutor y vigilante); si no, el vigilante depende del ejecutor y pierde sentido en el caso de que el ejecutor sea el roto; (2) cerrojo por posición para que vigilante y ejecutor no se pisen (cuando el vigilante toma el mando de una posición, el ejecutor no la toca).
- Origen: C12. Directriz de Jaume del 13-sep. Nota de Jaume: cree que DAS solo admite UNA conexión al API; se confirma con la clave y el PDF.

### R-C-09 · Stop de estructura: quién calcula el nivel y con qué datos
- Situación: la estrategia usa un stop de estructura (máximo del premercado, máximo de N velas, etc.), que en el backtester es un texto que el motor traduce a un nivel.
- Detección: el nivel lo calcula el MOTOR COMPARTIDO con el backtester, con los datos de Massive (igual que el bot de alertas, que funciona bien así); el ejecutor recibe un número. Paridad con el backtest: lo que hace el bot es lo que se midió.
- Acción: (1) entradas, señales y niveles: datos de Massive. (2) Vigilancia del precio, posiciones y órdenes: datos de DAS. (3) Caso extremo: si al ir a entrar el nivel de estructura queda por DEBAJO del precio actual (no debería pasar: el nivel se actualiza solo y subiría), NO se entra.
- Quién la ejecuta: motor (nivel) + guarda (caso extremo) + ejecutor.
- Parámetros: ninguno.
- Si la acción falla: sin nivel calculable (datos incompletos) → no se entra (enlaza con A12).
- Prueba: comparar en sombra el nivel calculado en vivo con el que da el backtester para el mismo ticker-día (paridad, como se hizo con las alertas: 73 ticker-días, cero divergencias).
- Estado: BORRADOR (13-sep). Aviso conocido: Massive incluye prints tardíos y de dark pool; un máximo de PM puede venir de un print que no estuvo en el libro. No se filtra (paridad con el backtester), pero es una fuente de diferencia entre nivel y precio real que se medirá en sombra.
- Origen: C13. Directriz de Jaume del 13-sep.

**Prints tardíos y dark pool (cerrado con Jaume, 13-sep).** Qué son: operaciones hechas fuera del libro que la cinta publica más tarde (de 20 ms a segundos); llegan en tiempo real como un print más, con hora de ejecución vieja. Nuestra orden nunca se ejecuta contra ellos; el único riesgo es que un stop que dispare por «último precio» se dispare por uno. Solución, sin esperar nada (prioridad: ejecutar en milisegundos, mínimo slippage):
1. **El stop residente en DAS dispara por el ASK (corto) / BID (largo), no por último precio.** DECIDIDO: Jaume recuerda que DAS admite stops del tipo «Ask + 0,01», que obligan a reconocer el ask. Un print de dark pool no mueve el ask. PENDIENTE de contrastar con el PDF: cómo se escribe ese disparo en el comando del API (no si existe, sino la sintaxis) → C6.
2. **El vigilante** mira el ask/bid de DAS (lo más simple) o, si lee el feed de operaciones de Massive, aplica el filtro del lago: ignorar prints con más de 10 ms entre ejecución y publicación (el feed trae las dos horas; las velas de 1 min no). Filtro por print, instantáneo.
3. NO se espera N segundos ni N prints para disparar (idea retirada: sube el slippage). La única espera es la decisión de cisne negro DESPUÉS del tercer trigger.
4. El nivel de estructura se sigue calculando con Massive sin filtrar (paridad con el backtester).

### R-C-10 · Stop al arrancar el bot con posiciones ya abiertas
- Situación: el bot arranca (reinicio, caída y relanzamiento) y DAS tiene posiciones abiertas.
- Detección: reconciliación al arrancar: posiciones y órdenes de DAS contra el diario del bot.
- Acción, por casos:
  1. Posición conocida con stop en DAS que COINCIDE con el que calcula el bot: nada.
  2. Posición conocida con stop en DAS que DIFIERE: manda el que calcula el bot AHORA (si difiere es porque durante la caída no se pudo mover). Se sustituye con R-C-05.
  3. Posición conocida SIN stop: R-C-03 con el stop que corresponda a la estrategia y a la cantidad, y aviso del incidente para rastrear el fallo.
  4. Posición que el bot NO reconoce (no está en su diario, p. ej. abierta a mano): aviso INMEDIATO de que hay una posición flotante desconocida sobre la que hay que actuar, y stop de protección a cierta distancia: por encima si es corta, por debajo si es larga (orientativo 20-30 %, parámetro).
- Quién la ejecuta: reconciliación + ejecutor.
- Parámetros: distancia del stop de protección para posiciones desconocidas (20-30 %).
- Si la acción falla: R-C-03.
- Prueba: arrancar el bot en sombra/demo con cada uno de los cuatro casos preparados.
- Estado: BORRADOR (13-sep).
- Origen: C14. Directriz de Jaume del 13-sep.

**PENDIENTE (Jaume, 13-sep): traspaso humano ↔ bot.** Cuando actuamos nosotros sobre una posición (cerrarla a mano a mercado, quitar el stop de protección que puso el bot), hace falta una forma de decirle al bot «esto lo he hecho yo, sigue con lo tuyo» para que no lo trate como incidente ni lo deshaga. Sin resolver; enlaza con K5 y M6.

### Área G · El precio se dispara

### Área F · Halts

### R-F-01 · Halt de volatilidad (LULD) con posición dentro
- Situación: el bot está en corto y la acción entra en halt de subida (limit up). k = halts UP del mismo ticker ACUMULADOS en todo el RTH del día (también los anteriores a la entrada del bot); los halts DOWN no cuentan.
- Detección: estado de halt, precio de reapertura, bandas limit up / limit down y primera vela de 1 min tras reabrir. Massive NO da las bandas; se cree que DAS sí [API F1, F11: confirmar].
- Acción, dos escenarios:
  1. **Reabre con el stop POR ENCIMA del precio**: se MANTIENE la posición mientras k < 3. Con k = 3, cierre a MERCADO en cuanto reabra. Con k = 2, si el precio se acerca a un 2-3 % del limit up, se SALE antes de que pare (evitar el tercer halt).
  2. **Stop POR DEBAJO del precio** (se lo ha saltado o por cualquier otra causa): se SALE sí o sí, a MERCADO al reabrir, sin tope de subida. Solo se REENTRA si la estrategia lo dice Y la primera vela de 1 min tras la reapertura sube menos de un 6 % Y k < 3. (Dato de Jaume: si la primera vela tras reabrir supera el 6 %, la probabilidad de que encadene otro halt es > 80 %.)
- Quién la ejecuta: ejecutor (órdenes preparadas para la reapertura) + vigilante (recuento k y distancia a la banda) + guarda (reentrada).
- Parámetros: k máximo = 3; distancia a la banda para salir con k = 2: 2-3 %; primera vela máxima para reentrar: 6 %; ruta de salida en reapertura (pendiente PDF).
- Si la acción falla: la orden de cierre en la reapertura no se llena → R-C-01/R-C-02 (niveles) y R-C-03 (sin stop, si DAS lo canceló en el halt).
- Prueba: replicar sobre los halts de 2B con status exacto (24_status_estrategias.py) y tabla de casos (k = 1, 2, 3; stop encima/debajo; primera vela < / ≥ 6 %).
- Estado: BORRADOR (14-sep, reescrita tras los datos de `34_tras_reapertura.py`). TODO el área F se repasa con el PDF (fuente de halts y bandas, rutas, qué hace DAS con los stops en un halt). Nota: los máximos de ×10-×44 del histórico son de días con 7-40 halts encadenados, no de lo que pasa tras el tercero; con salida en k = 3 el 90 % de los días con ≥ 3 halts queda por debajo de +144 % sobre el primer halt.
- Origen: F2, F5, D8. Directrices de Jaume del 14-sep.

### R-F-02 · Stop por encima del limit up: bajar el stop bajo la banda
- Situación: al colocar (o recalcular) el stop, el nivel queda POR ENCIMA del precio de limit up (la banda LULD superior, que se recibe como dato [API F11]).
- Detección: comparar el nivel del stop con la banda superior vigente cada vez que se coloca o se mueve el stop y cada vez que la banda cambia.
- Acción: si el stop está por debajo de la banda, nada. Si está por encima o coincide, colocar el stop un 1-2 % POR DEBAJO de la banda, para evitar a toda costa entrar en el halt con la posición abierta.
- Quién la ejecuta: guarda (cálculo) + ejecutor (recolocar con R-C-05).
- Parámetros: margen bajo la banda = 1-2 % (cuadro de mandos).
- Si la acción falla: no se puede recolocar → R-C-03.
- Prueba: tabla de casos con bandas de 5/10/20 % y stops a distintas distancias; comprobar en sombra cuántas veces actúa.
- Estado: BORRADOR (14-sep). Depende de que DAS entregue la banda [API].
- Origen: F11 (y decisión del 5-sep sobre bandas LULD). Directriz de Jaume del 14-sep.

### R-F-03 · Sin reentrada tras salir por stop y halt
- Situación: la posición se cerró por stop y la acción entró en halt (antes o después de la salida).
- Detección: salida por stop registrada en el diario + halt detectado en el mismo ticker.
- Acción: la estrategia NO vuelve a entrar en ese ticker salvo que se cumplan las tres condiciones de R-F-01 escenario 2: la estrategia lo pide, la primera vela de 1 min tras la reapertura sube < 6 %, y k < 3.
- Quién la ejecuta: guarda.
- Parámetros: primera vela máxima 6 %; k < 3.
- Si la acción falla: —
- Prueba: tabla de casos.
- Estado: BORRADOR (14-sep). Condición fijada el 14-sep.
- Origen: F5 / D6. Directriz de Jaume del 14-sep.

### R-F-04 · Orden de entrada y halt
- Situación: (a) hay una orden de entrada enviada y sin ejecutar cuando la acción se para; (b) la señal se genera con la vela justo anterior al halt y la acción ya está parada cuando el bot va a enviar.
- Detección: estado de halt (DAS) + orden viva en DAS / señal pendiente en el diario.
- Acción: (a) se CANCELA la entrada; al reabrir se reevalúa la estrategia y, si en ese momento manda estar dentro, se entra. (b) la señal se GUARDA y se ejecuta al reabrir si las condiciones de la estrategia siguen valiendo Y la primera vela tras la reapertura no ha subido más de un X % (X por decidir con un estudio).
- Quién la ejecuta: ejecutor (cancelar) + motor/guarda (reevaluar).
- Parámetros: X % de subida máxima de la primera vela tras reabrir: PENDIENTE (estudio).
- Si la acción falla: la cancelación no se confirma antes de la reapertura → tratar como posición nueva si se llena (R-F-01 aplica desde ese momento).
- Prueba: tabla de casos; sombra.
- Estado: BORRADOR (14-sep). Pendiente: X % (estudio) y confirmación con el PDF.
- Origen: F3 y F13. Directriz de Jaume del 14-sep.

### R-F-05 · Halts largos: T1 (noticia) y T12 (Nasdaq pide información)
- Situación: la posición está dentro cuando la acción entra en un halt que no es de volatilidad.
- Detección: motivo del halt (T1 / T12) por DAS o fuente externa [API F9].
- Acción: (a) **T1**: misma lógica de reapertura que R-F-01: reabre por debajo del stop → nada; por encima → mercado, salvo que la subida supere el 250 %, en cuyo caso no se cierra y se manda alerta máxima por Telegram para que cierre un humano. (b) **T12**: el bot AVISA y el control pasa al humano; el bot no hace nada más con esa posición.
- Quién la ejecuta: ejecutor + vigilante (aviso); humano en T12 y en el caso > 1.000 %.
- Parámetros: subida máxima de reapertura para cierre automático en T1 = 250 % (Jaume: 1.000 → 500 → 250 el 14-sep, a la vista de los datos: ningún T1 continuó más de ×2,2 tras reabrir). En LULD no hay tope: manda k (R-F-01).
- Si la acción falla: —
- Prueba: replicar sobre los T1/T12 del histórico (fichas_t12_t1.csv, t1_sin_reabrir_detalle.csv).
- Estado: BORRADOR (14-sep). Datos de referencia (8 años, todo el mercado, `34_tras_reapertura.py`, 14-sep):
  - T1 que reabren ≥ +70 % sobre el precio de parada (32 casos en horario 04:00-16:00; el mayor CAPR 3-dic-2025 +329 %; ABVX 22-jul-2025 +475 % fue en after-hours: paró a las 16:01 y reabrió a las 18:30, fuera del horario del bot): DESPUÉS de reabrir suben de mediana un +5 % más (p90 +62 %); 11 de 32 subieron más de un 20 % adicional y 13 cerraron por debajo de la reapertura. La mayor subida adicional tras un T1 fue SMMT 30-may-2024, +113 % (en 60 min), luego BGXX +104 % y BENEW +90 %. Ninguna llegó a doblar y media la reapertura. Un umbral del 250 % en T1 solo habría dejado sin cerrar automáticamente CAPR 3-dic-2025 (+329 %), que después cerró un 2 % por debajo de la reapertura.
  - LULD: la reapertura en sí casi no salta (mediana +0,1 %, p99 +34 %, máx +309 % MKD 2020). El peligro es la CADENA después: entre los que reabren ≥ +100 % (26), la subida adicional mediana es +25 %, p90 +274 %, máx +673 % (CCG 18-sep-2023); AIRE 23-oct-2023 reabrió +100 % y subió otro +1.151 %. Y los que más subieron tras reabrir lo hicieron desde reaperturas PLANAS: ATXG 31-ago-2022 (+4.449 % tras un halt que reabrió −23 %), QMMM 9-sep-2025 (+3.305 %), INHD 8-jun-2026 (+2.451 %), ZJYL, LTRPB. Conclusión: para T1 el umbral de «no cerrar» puede ser bajo (nada continuó más de ×2,1); para LULD lo que manda es el recuento de halts (R-F-01), no el salto de reapertura.
- Origen: F6 y F7. Directriz de Jaume del 14-sep.

### R-F-06 · Halt en premercado
- Situación: la posición está dentro y la acción entra en halt (T1/T12; en PM no hay LULD) y reabre en premercado.
- Detección: igual que R-F-05.
- Acción: misma lógica que R-F-01/R-F-05, con una diferencia: en PM no existen órdenes a mercado. Si el bot tiene que cerrar, pone una orden LÍMITE en la ruta más rápida (lista de rutas preferibles: PDF), REMOVIENDO liquidez (límite que cruza el ask) para salir lo antes posible. Si ya hay un stop limit puesto y se entra en T1/T12 en PM, ese stop se cambia por otro que remueva más liquidez (límite más alejado sobre el ask) para poder salir en cuanto reabra. Si el halt reabre ya en RTH, aplica lo de R-F-01/R-F-05 tal cual.
- Quién la ejecuta: ejecutor.
- Parámetros: margen sobre el ask del límite de salida en PM tras halt (más ancho que el de N1/N2); ruta rápida (PDF).
- Si la acción falla: R-C-02 (siguiente nivel) / R-C-03.
- Prueba: caso NEXI 2026 (T12 en PM que reabrió el mismo día) y tabla de casos.
- Estado: BORRADOR (14-sep). Rutas pendientes del PDF.
- Origen: F8. Directriz de Jaume del 14-sep.

**F10 (SSR), decidido el 14-sep:** SÍ se entra en acciones en SSR. No hay regla de seguridad por SSR (el área F fija criterios de salida, no de entrada). Matiz de Jaume para el área H: habrá acciones cuyos locates sean de UN SOLO USO (cada corto obliga a comprar otro paquete); ahí el cálculo del fade / EV frente al coste del locate se repite CADA VEZ que se piden locates, no una vez por día. Queda B19 y el área H.

**F12 (medias sesiones), decidido el 14-sep:** se opera normal. El calendario ya está en las estrategias, en la actualización de datos y en el sistema; el bot hereda la hora de cierre de ese día sin regla aparte.

### Área I · Riesgo y cortacircuitos

### Área B · Entrada

### Área H · Locates

### Área J · Infraestructura

### Área K · Estado y reconciliación

### Área A · Señal y datos

### Área D · Salidas y pirámides

### Área E · Capital compartido entre estrategias

### Área L · Calendario

### Área M · Control humano

### Área N · Registro y contabilidad

### Área O · Pruebas y despliegue

### Área P · Backtester vs vivo

### Área Q · Seguridad

## 4. Registro de cambios

| Fecha | Qué | Quién |
|---|---|---|
| 2026-09-12 | Se abre el fichero con el formato, los principios marco y el índice de áreas. Ninguna regla aún. | Jaume + Claude |
