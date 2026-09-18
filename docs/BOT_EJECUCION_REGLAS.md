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
- Estado: BORRADOR (12-sep). Pendiente: (a) confirmar con el socio; (b) RTH: Jaume cree que igual, no lo tiene claro; (c) RESUELTO el 14-sep (Jaume lo ha comprobado): un stop NO puede llevar tres triggers, pero SÍ se pueden dejar puestos TRES stop limit a la vez, cada uno con su trigger y su límite (el de arriba con más margen). Los tres residen en DAS desde la entrada: no hay que cancelar y reponer nada durante el evento. Consecuencia: R-C-11 (limpieza de stops sobrantes); (d) cómo se define «no consigue cerrar» en cada nivel (tiempo o precio que supera el límite) → C5; (e) condiciones de cisne negro → G1/G2.
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

### R-C-11 · Tres stops residentes: ajuste de cantidades y limpieza (no quedarse largo)
- Situación: hay tres stop limit puestos a la vez (N1, N2, N3) sobre un corto. Si cada uno lleva la cantidad completa y se ejecutan varios, se compraría de más y la cuenta quedaría LARGA sin querer.
- Detección: cada fill de cualquiera de los tres stops, confirmado por DAS.
- Acción: (1) con cada fill, reducir la cantidad de los stops que quedan a las acciones que siguen en corto (procedimiento de R-C-07); (2) en cuanto la posición quede a cero (se ha salido entera por N1, o por N1 + N2), CANCELAR inmediatamente todos los stops pendientes; (3) si pese a todo se ejecuta un stop de más y aparece una posición LARGA, cerrarla a mercado inmediatamente y avisar.
- Quién la ejecuta: ejecutor + vigilante (comprobar que no hay stops huérfanos ni posición larga).
- Parámetros: ninguno.
- Si la acción falla: la cancelación no se confirma → vigilante vigila el fill de más y aplica (3). Aviso en todo caso.
- Prueba: tabla de casos (sale todo en N1 / en N1+N2 / parcial en cada uno; carrera fill-cancelación) y demo.
- Estado: BORRADOR (14-sep). [API]: si DAS permite ligar los tres stops (OCO) para que se cancelen solos, mejor; si no, lo hace el bot.
- Origen: C1 (aclaración de Jaume del 14-sep tras comprobar DAS).

**MEDIDO el 15-sep (libro NBBO, `libro_entradas`): el riesgo de que dos stops residentes se compren encima.** Tras tocar el trigger 1, el ask llega a un segundo trigger situado a +1,1 % en menos de 0,2 s en el 55 % (1B) / 65 % (2B) de los stops normales, y en el 92 % de los fogonazos: ningún bot cancela tan rápido. Con el segundo trigger más lejos baja: a +5 %, 14 % / 24 % en 0,5 s; a +10 %, 6 % / 8 %; a +20-30 %, 2-6 % (en fogonazos 40-70 %). Consecuencia: tres stops residentes con la posición entera y triggers pegados (0,1 / 3 / 50 % de margen a +0 / +1,1 / +3,1 %) dejarían la cuenta LARGA más de la mitad de las veces. Propuesta (no decidida): UNA orden residente (trigger N1, límite +1-3 %) y la escalada al 50 % la hace el vigilante sustituyendo la orden colgada (1-2 % de los casos; no hay carrera porque la orden colgada no se está ejecutando); o DOS residentes solo si la segunda está a ≥ +20-30 % y con R-C-11 activa; o TRES si DAS ofrece OCO/bracket o «solo cerrar posición» [API, prioritario]. Nota de Jaume: en DAS estas órdenes limitadas son las «limitP» (confirmar en el PDF).

**DECIDIDO el 15-sep (Jaume): margen del primer stop = 3 %.** Diseño en curso (pendiente de fijar la distancia del trigger de emergencia): (1) UNA orden residente en N1 con límite +3 %; (2) UNA orden residente de EMERGENCIA con límite +50 % y trigger más arriba (Jaume baraja +10 % en vez de +20 %: sale antes en un squeeze rápido a cambio de algo más de riesgo de doble compra, 6-8 % frente a 2-6 %); el límite es solo un techo: compra al ask del momento, no al +50 %. (3) Entre las dos, si la primera se cuelga, el VIGILANTE la sustituye por otra con límite ancho en ~0,5 s y sale al ask de ese momento; la emergencia residente es el seguro para cuando el bot está muerto. (4) La lógica de cisne negro (no cerrar, esperar) solo la puede aplicar el bot vivo: si decide que es cisne negro, es él quien retira o mantiene las residentes; una residente por sí sola no distingue squeeze de cisne negro. (5) Tras cualquier ejecución de stop, el vigilante comprueba la posición neta: cancela las órdenes de ese lote que sobren y, si hay acciones compradas de más (posición larga en un lote que es corto), las vende al bid al instante y lo registra como incidente (R-C-11). (6) Varias estrategias: mismo nivel de stop → UNA orden con la suma de acciones; niveles distintos → una orden por lote; cada orden lleva en el diario su lote; la suma de órdenes nunca supera la posición (se formaliza en el área E).

**DECIDIDO el 15-sep (Jaume), estructura de los stops residentes (sustituye a lo de «tres stops» de R-C-01/R-C-02):**
1. **Stop principal**: trigger en el nivel de la estrategia (L, p. ej. 10,00), limitP con límite L + 3 % (10,30). Compra al ask del momento; en condiciones normales sale en el propio nivel o pegado.
2. **Stop de emergencia**: trigger un 10 % por encima del límite del principal (10,30 × 1,10 ≈ 11,33), limitP con límite +50 % sobre su trigger (≈ 17). También compra al ask del momento; el 50 % es solo techo. Lleva la posición ENTERA.
3. **Cisne negro: la decisión de «no cerrar y esperar» la tiene el STOP, no el bot.** Si es cisne negro, el precio pasa del límite de emergencia con la orden sin ejecutar (corto al descubierto); cuando el precio vuelve, la orden de emergencia se ejecuta en su límite al bajar, o si no, cierra el humano a la media hora. PENDIENTE (más adelante): reglas del bot en esa espera en función del % devuelto. Dato (`cierre_forzado.csv`, fogonazos del lago): con salto ≥ 100 % el precio vuelve por debajo de +100 % sobre el precio previo en 30 min en el 96 % [IC95 88-99] de los casos (mediana 1,2 min) y por debajo de +50 % en el 86 % [74-93]; con salto ≥ 500 %, 75 % [41-93] y 62 % [31-86]. El límite de emergencia queda ≈ +86 % sobre la entrada (1,10 × 1,13 × 1,5), así que en ~9 de cada 10 fogonazos la orden se ejecuta sola al volver y el humano solo entra en el resto.
4. **Limpieza estricta (R-C-11, PRIORIDAD: proteger, no añadir riesgo).** Tras cualquier ejecución: (a) si la posición neta del lote queda a CERO, cancelar al instante TODAS las órdenes de ese lote (incluida la principal si está colgada: si no se cancela, se ejecuta al volver el precio y deja la cuenta larga); (b) si queda LARGA (compras de más), vender al bid SOLO el exceso: ejemplo, 100 cortas, el principal cubre 20, la emergencia (100) cubre 100 → largo 20 → se venden 20, JAMÁS 100 (dejaría 80 cortas al descubierto en pleno squeeze); (c) si sigue CORTA, mantener o reponer el stop que falte. Siempre sobre la posición neta real de DAS, nunca sobre la cantidad inicial del stop.

Aclaraciones de Jaume (15-sep): la venta del exceso SOLO se hace si la posición neta es LARGA (acciones compradas); si por cualquier error lo que queda es corto, NO se vende nada. La orden de emergencia lleva la posición entera porque tiene que poder cubrirlo todo si el principal falla. PENDIENTES PRIORITARIOS, con datos: (i) qué hacer si tras la limpieza sigue quedando algo corto (mantener / reponer stop); (ii) qué hace el bot a la VUELTA de un cisne negro (cuándo cerrar mientras el precio devuelve; hoy: la orden de emergencia se ejecuta sola al cruzar su límite en ~9 de cada 10, humano a la media hora en el resto).

**REGLA FIJADA (Jaume, 16-sep) y NOTA DE DATOS para el repaso final.** La estructura de dos stops residentes (principal +3 %, emergencia a +10 % del límite del principal con +50 %) y la limpieza estricta quedan FIJADAS. Cifras en las que se apoya (`36_analisis_libro_entradas.py`, NBBO consolidado, 15-sep; solo operaciones que salen por stop; 1B = PM, 2B = RTH):
| Margen del limitP | Se ejecuta al instante | En 60 s | Colgado | Slippage sobre el nivel (mediana / p95 / p99) |
|---|---|---|---|---|
| +0 % (justo en el nivel) | 71 % / 77 % | 96 % / 97 % | 1-3 % | −0,6 / 0,0 / 0,0 |
| +1 % | 88 % / 89 % | 98 % | 1-2 % | +0,1 / +0,8 / +1,0 |
| **+3 % (principal)** | **95 % / 91 %** | **98-99 %** | **1-2 % [IC95 0-5]** | **+0,3 / +2,2 / +2,8** |
| +10 % | 100 % / 95 % | 99-100 % | 0-1 % | +0,7 / +5,9 / +8,8 |
| **+50 % (emergencia), en fogonazos** | **86 %** | **97 % (5 min)** | **1 % [0-5]** | **+8,8 / +42 / +47** |
| +50 % en stops normales | 100 % | 100 % | 0 % | +0,7 / +7,6 / +16 |
Camino del ask tras el disparo (stops normales): máximo a 60 s mediana +4-5 % sobre el nivel, p90 +16-20 %. En fogonazos el ask ya está +20 % (mediana) sobre el nivel en el disparo. Riesgo de que una segunda orden residente se dispare antes de que el bot cancele (0,5 s): a +1 % del primero, 55-65 %; a +5 %, 14-24 %; a +10 %, 6-8 %; a +20-30 %, 2-6 %; en fogonazos 40-70 %. Vuelta del cisne negro: con salto ≥ 100 % el precio vuelve por debajo de +100 % en 30 min en el 96 % [88-99] y por debajo de +50 % en el 86 % [74-93] (mediana 1-2 min); ≥ 500 %: 75 % [41-93] y 62 % [31-86].

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

**PENDIENTE G3 (14-sep), decisión importante, volver a preguntar:** tope de pérdida por posición y cómo distinguir cisne negro de squeeze. Lo que hay: (1) el tercer trigger N3 hace de tope por posición; no habrá una capa más por posición. (2) Lo que distingue cisne negro de squeeze es el TIEMPO, no el tamaño: si pasados 5-10 minutos de superar N3 el precio sigue arriba (y con volumen), no es fogonazo, es squeeze y se cierra a mercado; si ha vuelto, era fogonazo y se espera (Jaume prefiere 5-10 min a segundos). (3) Un tope de CUENTA como último cinturón («nunca más de X % de la cuenta en una posición, pase lo que pase»), que cierra aunque parezca fogonazo; se gestiona desde el cuadro de mandos. Riesgo que Jaume quiere meditar: un tope del 20 % de la cuenta y el bot confundiendo cisne negro con squeeze normal.

### Área F · Halts

### R-F-01 · Halt de volatilidad (LULD) con posición dentro
- Situación: el bot está en corto y la acción entra en halt de subida (limit up). k = halts UP del mismo ticker ACUMULADOS en todo el RTH del día (también los anteriores a la entrada del bot); los halts DOWN no cuentan.
- Detección: estado de halt, precio de reapertura, bandas limit up / limit down y primera vela de 1 min tras reabrir. Massive NO da las bandas; se cree que DAS sí [API F1, F11: confirmar].
- Acción, dos escenarios:
  1. **Reabre con el stop POR ENCIMA del precio**: se MANTIENE la posición mientras k < 3. Con k = 3, cierre a MERCADO en cuanto reabra. Siempre que k = 2 (ya ha habido dos halts, da igual cuándo entramos), si el precio se acerca a un 3-5 % del limit up, se SALE A MERCADO antes de que pare para evitar el tercero (Jaume, 15-sep: antes 2-3 %); si no da tiempo y para, se aplica lo anterior: mercado al reabrir.
  2. **Stop POR DEBAJO del precio** (se lo ha saltado o por cualquier otra causa): se SALE sí o sí, a MERCADO al reabrir, sin tope de subida. Solo se REENTRA si la estrategia lo dice Y la primera vela de 1 min tras la reapertura sube menos de un 6 % Y k < 3. (Dato de Jaume: si la primera vela tras reabrir supera el 6 %, la probabilidad de que encadene otro halt es > 80 %.) Tras reentrar se aplica la misma lógica con el nuevo stop: con k = 1, escenario 1 normal; con k = 2, la salida a mercado a 3-5 % de la banda y mercado al reabrir si para.
- Quién la ejecuta: ejecutor (órdenes preparadas para la reapertura) + vigilante (recuento k y distancia a la banda) + guarda (reentrada).
- Parámetros: k máximo = 3; distancia a la banda para salir con k = 2: 3-5 %, salida a mercado; primera vela máxima para reentrar: 6 %; ruta de salida en reapertura (pendiente PDF).
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

**I1 (pérdida diaria máxima), decidido el 14-sep: NO HAY cortacircuito de pérdida diaria en el bot, de momento.** No habrá reglas de pérdida máxima diaria más allá de lo que marque cada estrategia y de las reglas de proceso de este libro. Si algún día se pone, se contaría realizado + latente. El bot no se apaga «por que sí»: se controla por Telegram, pero no hay apagado automático por pérdida. Datos: Sage ofrece autoliquidación en RTH, no en PM. Pendiente de volver a preguntar más adelante.

### R-I-01 · Capital disponible manda: entrar con lo que quede
- Situación: llega una señal de entrada y hay que dimensionarla.
- Detección: capital libre de la cuenta (DAS, buying power [API E6]) frente al tamaño que pide la estrategia (riesgo fijo del cuadro de mandos).
- Acción: no hay tope de número de posiciones: lo limita el capital. Si no queda capital libre, no se entra. Si queda solo una parte (la estrategia pide el 2 % y queda el 1 %), se entra con lo que quede (el 1 %).
- Quién la ejecuta: guarda (dimensionado).
- Parámetros: ninguno propio; el tamaño por estrategia y por pirámide viene del cuadro de mandos.
- Si la acción falla: capital libre no se puede leer de DAS → no se entra (enlaza con K11).
- Prueba: tabla de casos (libre ≥ pedido / parcial / cero).
- Estado: BORRADOR (14-sep).
- Origen: I5. Directriz de Jaume del 14-sep.

### R-I-02 · El tamaño lo fija el cuadro de mandos, nunca el bot
- Situación: cualquier decisión de tamaño: entrada, cada nivel de pirámide, capital por estrategia, escalón del canario.
- Detección: valores del cuadro de mandos.
- Acción: el bot aplica el riesgo fijo que Jaume ponga en el cuadro de mandos para cada estrategia y cada piramidación. El bot NO decide tamaños ni escalones; subir o bajar el escalón del canario lo hace Jaume cambiando el valor.
- Quién la ejecuta: guarda.
- Parámetros: todos en el cuadro de mandos.
- Si la acción falla: sin valor en el cuadro de mandos → no se entra.
- Prueba: tabla de casos.
- Estado: BORRADOR (14-sep).
- Origen: I10. Directriz de Jaume del 14-sep.

### R-I-03 · Cambios en caliente: el cuadro de mandos manda siempre
- Situación: se cambia un parámetro (riesgo, tope, margen) a media sesión.
- Detección: nuevo valor en el cuadro de mandos.
- Acción: el bot lo aplica en la SIGUIENTE señal (no reabre ni recalcula lo ya abierto salvo que otra regla lo diga). Si el JSON de la estrategia y el cuadro de mandos difieren, manda el cuadro de mandos, siempre.
- Quién la ejecuta: guarda.
- Parámetros: —
- Si la acción falla: el bot no puede leer el cuadro de mandos → sigue con el último valor conocido y avisa.
- Prueba: cambiar un valor en sombra y comprobar que la siguiente señal lo usa; registrar quién cambió qué (M9).
- Estado: BORRADOR (14-sep).
- Origen: I12. Directriz de Jaume del 14-sep.

**Nota de Jaume (14-sep) para las áreas C/D/E:** la gestión de stops y posiciones habrá que hacerla bien por ESTRATEGIA, porque cada una meterá cantidades distintas a mercado. Se irá viendo.

### Área B · Entrada

**B1 (precio que se mueve al enviar), ABIERTA el 14-sep, forma decidida y números en blanco.** Forma: entrada en corto con orden LÍMITE al bid menos un margen (remover liquidez con techo), en PM y en RTH; a mercado solo en casos contados por definir. Si el bid sube (a favor), se recoloca al nuevo bid tantas veces como haga falta mientras la señal siga vigente. Si baja (en contra), se persigue hasta una tolerancia sobre el precio de la señal y luego se abandona. Variante SSR: un tick por encima del bid (agrega liquidez) [API: cómo indica DAS el SSR]. Margen y tolerancia en % con suelo de 1 céntimo, distintos por sesión, al cuadro de mandos. Los VALORES salen del estudio de abajo, no a ojo: el spread del 6 % y los libros de 1-7 k$ del estudio de cisnes son de días de fogonazo, no de entradas normales.

**RESULTADOS DEL ESTUDIO P12 (15-sep, `35_descargar_libro_entradas.py` + `36_analisis_libro_entradas.py`, NBBO EQUS.MINI, 890 ventanas, 0,80 $).** Muestra: 260 entradas y 180 stops de 1B (PM), 170 entradas y 130 stops de 2B (RTH), 150 fogonazos. Sin cotización consolidada antes de ~05:30 ET (70 entradas de 1B sin libro). Slippage = precio conseguido frente al precio del backtester (open de la vela i+1); negativo = peor para el corto. Tablas completas en `libro_entradas_resumen.txt`.
- **Entrada PM (1B)**: spread mediano 3,9 % (p75 9,5 %, p90 22 %); el bid en el segundo de la señal está de mediana −0,8 % bajo el precio del backtester (p10 −8,9 %). REMOVER al bid: ejecutado al llegar 89-96 % según margen; slippage mediana −0,9 %, media −3,2 % [IC95 −4,2, −2,3]. AGREGAR en el ask: solo 33 % ejecutado en 30 s y la media con fallback es igual o peor (−3,4 %): en PM agregar NO compensa. **La media la manda el spread**: con spread > 10 % (25 % de las entradas) slippage mediana −5,5 %, media −9,4 %; con spread ≤ 5 % (56 % de las entradas) mediana −0,57 %, media −0,98 % [p10 −2,1 %]. El margen bajo el bid (0 / 0,3 / 0,7 / 1,5 %) apenas cambia el slippage (−0,84 → −0,95 mediana) y sube la ejecución al llegar de 89 % a 96 %.
- **Entrada RTH (2B)**: spread mediano 1,2 %; bid vs backtester −0,6 % (p10 −2,2 %). REMOVER al bid: 92-98 % al llegar, slippage mediana −0,55 %, media −0,89 % [−1,05, −0,73]. AGREGAR en el ask: 69 % ejecutado en 30 s (77 % en 60 s), slippage mediana +0,08 %, media −0,39 % [−0,72, −0,08] con fallback al bid a los 30 s: **ahorra ≈ 0,5 puntos de media frente a remover**, más la comisión. En el medio: 78 % en 30 s, media −0,65 %.
- **Tamaño**: dólares en el bid en el segundo de la señal, mediana 331 $ (PM) / 848 $ (RTH); una orden de 300 $ cabe entera el 53 % / 73 %; una de 3.000 $ el 6 % / 17 %. A partir de unos cientos de dólares la orden se llena en varios tramos.
- **Stops normales (1B y 2B), disparo por ask, compra limitada a L·(1+M)**: el ask en el disparo está de mediana +0,3/+0,7 % sobre L (p90 +3-4,5 %, p99 +24/+90 %). Camino tras el disparo: máximo del ask a 60 s mediana +4-5 % sobre L, p90 +16-20 %. Con M = 3 %: ejecutado al instante 91-95 %, en 60 s 98-99 %, colgado 1-2 % [IC95 0-5]; slippage sobre L mediana +0,3 %, p95 +2,1-2,3 %, p99 +2,8 %. Con M = 10 %: al instante 95-100 %, colgado 0-1 %, p95 +5-6 %, p99 +9 %. Con M = 0 (limitado justo en L): 71-77 % al instante, 96-97 % en 60 s, 1-3 % colgado.
- **Fogonazos (stop a +10 % sobre el precio previo)**: el ask ya está +20 % sobre L de mediana en el disparo (p90 +88 %), spread 25 %. M = 10 %: 54 % al instante, 85 % en 5 min, 15 % colgado [10-23]. M = 30 %: 70 % / 97 % / 3 % colgado [1-8], slippage p95 +29 %. M = 50 %: 86 % / 99 % / 1 %, p95 +42 %. Y con limitado en L (M = 0): 71 % se ejecuta dentro de 5 min a precio ≤ L porque el precio VUELVE: esa es la base de «no cerrar y esperar» del cisne negro.

**Valores recomendados para B1 y para los márgenes de los triggers (provisionales, al cuadro de mandos, a afinar en sombra):**
1. Entrada PM: límite al bid − 0,5 % (remover con techo). No agregar. Persecución en contra hasta 2 % del precio de señal. Slippage asumible: mediana −0,6 %, media −1 % SI se filtra el spread.
2. **Guarda de spread (B20)**: no entrar con spread > 5 % del precio en el segundo de la señal (deja fuera el 44 % de las entradas de 1B de la muestra; sin ella la media del slippage se va a −3 % y la cola a −10/−20 %). Hay que medir qué parte del PnL de 1B viene de esas entradas antes de fijarlo.
3. Entrada RTH: agregar en el ask (o en el medio) durante 10-30 s; si no se ejecuta, cruzar al bid − 0,3 %. Slippage asumible: media −0,4 % [−0,7, −0,1] frente a −0,9 % remover.
4. Trigger N1: límite L1 + 3 % (p95 de slippage +2,2 %, colgado 1-2 %). Trigger N2: límite L2 + 10 % (colgado ≤ 1 %, p95 +6 %). Trigger N3 (emergencia): límite L3 + 30-50 % (en fogonazos 3 % / 1 % colgado, p95 +29 / +42 %). El margen solo cuesta cuando el precio salta: con M = 3 % la mediana de slippage es +0,3 %.
5. Cisne negro: un limitado en L se ejecuta en 5 min en el 71 % de los fogonazos a precio ≤ L; la espera tiene base en PM.

### R-B-01 · Orden de entrada en corto: al bid si está cerca, escalera si está lejos, nunca más del 3 %
- Situación: la estrategia da señal de entrada (o de pirámide) y el bot envía la orden. Vale para PM y RTH.
- Detección: último precio cruzado (el que usa el backtester) y bid de DAS en el segundo de la señal. Tope T = 3 %.
- Acción:
  1. **Bid a menos del 3 % del último precio** (80 de cada 100 señales de 1B, 94 de 2B): venta límite (limitP) a bid × (1 − 0,5 %), al instante. Se ejecuta AL BID (el mejor precio disponible en ese momento); el 0,5 % es solo el techo por si el bid se mueve durante el envío. Sin espera.
  2. **Bid a más del 3 %**: no se cruza. Se deja una venta límite AGREGANDO liquidez en ESCALERA (Jaume, 16-sep): a −1 % del último precio; a los 10 s, a −2 %; a los 20 s, a −3 %, y ahí se queda lo que resta del minuto; si a los 60 s sigue sin ejecutarse, se cancela y NO se entra. Se cancela antes en cuanto la estrategia deje de decir «dentro».
  3. Nunca se vende por debajo del último precio × (1 − 3 %). El 3 % es un tope, no un precio: solo se llega a él si no hay nadie más arriba.
- Quién la ejecuta: ejecutor (guarda: distancia último→bid).
- Parámetros (cuadro de mandos): tope T = 3 %; techo de la rama 1 = 0,5 %; escalones 1 / 2 / 3 %; cambio de escalón cada 10 s; el tercero espera hasta completar 60 s. Ruta: ARCA en PM; en RTH, SAGEPRO si en sombra llena igual de rápido que ARCA, si no ARCA.
- Si la acción falla: sin cotización (libro vacío, antes de ~05:30 ET en muchos valores) → no se entra. Orden de la rama 1 no ejecutada porque el bid cayó más del 0,5 % durante el envío → pasa a la rama 2 (escalera) desde el escalón que corresponda.
- Prueba: sombra, midiendo slippage real frente al precio del backtester y % de señales que se quedan fuera.
- Estado: FIJADA (Jaume, 16-sep) salvo la ruta (sombra) y el ajuste fino de tiempos con fills reales.
- Origen: B1, B2 (queda absorbida: no hay reenvíos, la escalera es la persecución), B20. Estudio P12 (`36`/`37` y cálculos del 16-sep).
- Tiempo total de la escalera (medido el 16-sep, 1B, señales que van a la escalera): 10 s → entran el 39 % (12 de cada 100 señales fuera); 20 s → 55 % (9 fuera); 30 s → 63 % (7 fuera); 45 s → 71 % (6 fuera); 60 s → 74 % (5 fuera); 90-120 s → 74-76 % (5 fuera). Más de 60 s no aporta; menos de 30 s pierde el doble de señales. Se fija 60 s.

### R-B-02 · Entrada ejecutada a medias
- Situación: la orden de entrada se ejecuta solo en parte (p. ej. 400 de 1.000) porque en el bid no había más. Frecuente: en PM una orden de 300 $ cabe entera el 53 % de las veces; de 3.000 $, el 6 %.
- Detección: fill parcial confirmado por DAS.
- Acción: el resto (600) sigue con la misma lógica de R-B-01 (al nuevo bid si está a menos del 3 % del último precio; si no, escalera), como máximo hasta completar el minuto desde la señal y sin pasar nunca del 3 %. Al minuto, se acepta la posición que haya (400) con su stop proporcional (R-C-01) y se cancela lo pendiente. No hay mínimo por debajo del cual no compense quedarse: se entra siempre que se pueda y con lo que se pueda.
- Quién la ejecuta: ejecutor.
- Parámetros: los de R-B-01.
- Si la acción falla: lo no ejecutado se cancela; la posición parcial queda protegida por su stop.
- Prueba: sombra (recuento de parciales y tamaño medio conseguido frente al pedido).
- Estado: FIJADA (Jaume, 16-sep). Pendiente futuro: regla específica para tamaños muy grandes.
- Origen: B3.

- B18 (Jaume, 16-sep): si llega un HALT con la escalera viva, se cancela; al reabrir, entrada nueva desde cero SOLO si las reglas dicen «dentro» (R-F-04, primera vela < 6 %, k < 3).

### R-B-04 · Cuándo se envía la entrada: en el instante en que cierra la vela de la señal
- Situación: la estrategia evalúa la señal con la vela i (cerrada). El backtester entra al open de i+1 (regla anti look-ahead).
- Detección: el bot construye la vela i en tiempo real con el feed de operaciones de Massive (no espera a la vela agregada AM, que llega con retraso) y evalúa la señal EN EL INSTANTE en que termina el minuto (t = cierre de i, que es el mismo instante que la apertura de i+1).
- Acción: la orden sale en ese instante (decenas de milisegundos después del cierre). Es el mismo momento en que el backtester entra, así que hay paridad, y es lo antes que se puede sin mirar el futuro: «milisegundos ANTES del cierre» no es posible sin adivinar el cierre (el último print del minuto puede cambiar la señal), y romper eso rompería la paridad con el backtest.
- Caducidad de la señal: si por un retraso del feed o del bot la orden no ha podido salir en el instante, la señal sigue valiendo dentro del mismo minuto (los 60 s de R-B-01) siempre que se cumpla la puerta del 3 %; pasado el minuto, caduca (enlaza con A1, PROVISIONAL).
- Quién la ejecuta: motor (señal por ticks) + ejecutor.
- Parámetros: caducidad = 60 s desde el cierre de la vela (provisional).
- Si la acción falla: sin ticks (feed caído) → se usa la vela AM al llegar, y la señal se trata como «tardía» (caducidad).
- Prueba: comparar en sombra la hora de envío con el cierre de la vela (latencia señal→orden) y la señal calculada por ticks con la de la vela AM (paridad).
- Estado: FIJADA (Jaume, 16-sep), caducidad provisional.
- Origen: B12, A1.

- B11 (Jaume, 16-sep): en premercado NO hay excepciones: la escalera termina el minuto y se cancela, igual que en sesión, salvo que se especifique en el futuro.
- B13 (Jaume, 16-sep): fill a precio MEJOR que el último precio → se acepta, se registra y ya. Fill PEOR de lo que la regla permite (fallo de DAS o de la orden) → se AVISA y se MANTIENE la posición con su stop; no se cierra por eso.
- B19, SSR (Jaume, 16-sep, opción 2): con la restricción de venta en corto activa, la venta solo puede ejecutarse por encima del bid, así que la rama 1 (al bid) no existe: se aplica la MISMA escalera de siempre con un suelo: ningún escalón por debajo de bid + 0,01 $ (o bid + 1 tick). El bot necesita saber si el valor está en SSR ese día [API: bandera SSR en el L1 de DAS]. Nota de Jaume: la SSR no siempre viene de una caída del 10 %; a veces el valor «aparece» en SSR y no hay locates, o son de un solo uso: se trata en el área H (locates).

### R-B-05 · Tamaño frente al volumen: medido siempre, tope desactivado de momento
- Situación: cualquier orden de entrada o pirámide.
- Detección: volumen ACUMULADO del día de la acción hasta ese instante (elección de Jaume frente a las últimas N velas) y tamaño pedido por el cuadro de mandos.
- Acción: el bot calcula y registra en el diario la fracción (tamaño / acumulado del día) de cada orden. El TOPE está DESACTIVADO por defecto (parámetro del cuadro de mandos, «sin límite»): con los tamaños actuales no hace falta. Si se activa, la orden se recorta al tope y se entra con lo que quepa (como R-I-01); lo que no quepa se gestiona con la ejecución parcial (R-B-02) y el slippage, aunque se mueva el precio.
- Quién la ejecuta: guarda + diario.
- Parámetros: fracción máxima del acumulado del día (por defecto desactivado).
- Si la acción falla: sin volumen acumulado (primeros minutos del PM) → se registra 0 y no se limita.
- Prueba: revisar en sombra la distribución de la fracción registrada.
- Estado: FIJADA (Jaume, 16-sep) como «medir, no limitar». El TOPE queda como PENDIENTE DE DECISIÓN A FUTURO: no para ahora ni para la primera implementación; solo cuando los tamaños lo pidan. Cumple M9 (preparado desde el inicio) sin actuar.
- Origen: B8.

- Principio (Jaume, 16-sep): el algoritmo intenta SIEMPRE el mejor precio disponible, acercándose al 0 % de slippage; el 3 % es el peor caso admitido, no un objetivo. Slippage mediano esperado con todo junto: ≈ 0,9 % en PM, ≈ 0,6 % en RTH.

### R-B-03 · Varias entradas del mismo ticker a la vez (una estrategia esperando y llegan otras)
- Situación: la orden de entrada de una estrategia sigue viva (escalera, hasta 60 s) y OTRAS estrategias (pueden ser 20 a la vez: A y B son solo nombres de ejemplo), o sus pirámides, piden entrar en el mismo ticker. La pirámide de una estrategia nunca coincide con su propia base: solo se piramida con la base ya dentro.
- Detección: nueva señal sobre un ticker con orden de entrada viva.
- Acción: se SUMAN las cantidades de todas las estrategias en una sola orden de venta y la escalera se REINICIA desde el primer escalón con el total. El bot registra en el diario qué parte pertenece a cada estrategia (un lote por estrategia, N lotes), para repartir después fills, stops y take profits (áreas C y E).
- Quién la ejecuta: ejecutor + diario.
- Parámetros: los de R-B-01.
- Si la acción falla: fill parcial → R-B-02, repartiendo lo ejecutado entre lotes en proporción a lo pedido.
- Prueba: tabla de casos; sombra.
- Estado: FIJADA (Jaume, 16-sep). Caso raro: si coinciden, coinciden a la vez (la escalera no dura más de un minuto).
- Origen: B6.

- Resultado esperado (muestra P12): 1B entra en el 95 % de las señales, 62 % con slippage ≤ 1 %, media 1,1 %; se pierden 5 de cada 100 señales (13 % del bruto de la muestra, 9 casos con el bid a 4-28 % del último precio). 2B entra en el 100 %, 75 % con ≤ 1 %, media 0,78 %.

**B20, guarda de spread: PROVISIONAL, a confirmar en el repaso final y en sombra.** No entrar si (ask − bid) / bid > 5 % en el segundo de la señal. Motivo (`37_slippage_asumible.py`, 16-sep): en 1B el 47 % de las entradas tienen slippage peor que −1 % frente al backtester y el 25 % tienen spread > 10 % con slippage medio −9 %; con spread ≤ 5 % quedan el 56 % de las entradas de 1B (94 % de 2B) con slippage medio −1,0 % (2B −0,75 %). AVISO: las entradas de spread ancho de 1B son de las MÁS rentables en bruto (62 % del beneficio bruto está en entradas con slippage > 1 %, +5,3 % medio/op): el backtester las llena a un precio que no existe, y su rentabilidad NETA real no se sabe hasta la sombra. La muestra (190 ops) no permite fijar el umbral con confianza: el neto por 100 operaciones con filtro 5 % es +198 [IC95 −15, +401] frente a +86 [−220, +384] sin filtro. Slippage que aguanta cada estrategia (esperanza neta = retorno medio bruto − slippage): 1B se queda a cero con 3,5 % y pierde la mitad del edge con 1,7 %; 2B a cero con 3,1 %, mitad con 1,6 %. El «no más del 1 %» de Jaume deja el 70 % del edge.

**B20 bis (16-sep): guarda por DISTANCIA último precio → bid, mejor que por spread.** El bot conoce en el segundo de la señal el último precio cruzado (el que usa el backtester) y el bid; la distancia entre ambos ES el slippage que va a tener. Regla candidata: no entrar si (último − bid) / último > D. Resultados (muestra P12):
| D | 1B: entran | slip ≤ 0,5 % | slip ≤ 1 % | slip > 2 % | slip medio | bruto que se pierde | neto/100 ops [IC95] |
|---|---|---|---|---|---|---|---|
| 1 % | 56 % | 50 % | 91 % | 6 % | −0,75 % | 39 % | +207 [+5, +436] |
| 2 % | 72 % | 39 % | 72 % | 6 % | −0,91 % | 28 % | +227 [−1, +464] |
| 3 % | 80 % | 35 % | 65 % | 15 % | −1,05 % | 37 % | +172 [−93, +433] |
| **5 %** | **86 %** | **33 %** | **61 %** | **21 %** | **−1,24 %** | **25 %** | **+199 [−48, +456]** |
| sin filtro | 100 % | 28 % | 53 % | 32 % | −3,22 % | 0 % | +86 [−213, +393] |
2B: con D = 3 % entran el 94 % (slip medio −0,77 %, 73 % con ≤ 1 %); con 5 %, el 99 %. Jaume quiere exprimir 1B en PM sin sacrificar tantas entradas: la guarda por distancia con D = 5 % entra en 86 de cada 100 (frente a 56 con spread ≤ 5 % o 43 con spread ≤ 3 %) y corta la cola (nada por encima del 5 % de slippage por construcción). Preferible a la guarda por spread. PROVISIONAL (Jaume, 16-sep): D = 5 % en las DOS sesiones, al cuadro de mandos; se afina en sombra y en el repaso final. A menor D, menos entradas y más bruto fuera (1 % → 39 % fuera; 2 % → 28 %; 5 % → 25 %), pero el NETO apenas cambia entre 2 y 5 % (zona plana).

**R-B-01, rama 2 (16-sep, propuesta con datos): cuando el bid está a más del 5 % del último precio, NO se descarta: se deja una venta límite AGREGANDO liquidez, en escalera.** En 1B es el 14 % de las señales (distancia mediana 13 %, p90 28 %). Medido sobre esas 27 entradas: una venta límite fija a −X % bajo el último precio se ejecuta en 60 s el 78 % (−1 %), 81 % (−2 y −3 %), 85 % (−4 %), 89 % (−5 %); es decir, el precio SUBE hasta casi el último precio en la mayoría de los casos, así que una orden fija a −5 % regala slippage (se ejecuta a −5 % por definición). ESCALERA: −1 % en t0, −2 % a los 15 s, −3 % a los 30 s, −4 % a los 45 s, −5 % a los 60 s, cancelar a los 120 s o en cuanto la estrategia deje de decir «dentro» (en 1B, su condición dura 1 minuto): se ejecuta el 85 %, slippage medio −1,9 %, 13 de 23 al −1 %, tiempo mediano 11 s. Esas entradas rinden +7,2 % bruto de media (+2,2 % neto incluso con −5 %). Rama 1 (distancia ≤ 5 %): remover al bid ejecuta AL BID, slippage mediana −0,8 %, media −1,2 %; el techo del 0,5 % no se paga salvo que el bid se mueva durante el envío. Tiempos de la escalera: PROVISIONALES, a fijar con datos (Jaume).

**Foto completa con puerta 3 % + escalera hasta −3 % (16-sep), sobre TODAS las señales de la muestra:**
| | 1B (190) | 2B (159) |
|---|---|---|
| Entran | 95 % | 100 % |
| Con slippage ≤ 0,5 % | 28 % | 41 % |
| Con slippage ≤ 1 % | 62 % | 75 % |
| Entre 1 y 2 % | 20 % | 18 % |
| Entre 2 y 3 % | 11 % | 8 % |
| No entran | 5 % | 0 % |
| Slippage medio de las que entran | 1,1 % (mediana 0,86 %, p90 2,3 %) | 0,78 % (mediana 0,61 %, p90 1,8 %) |
(Un caso de 1B sale con 11 % en la simulación por el «fallback a los 30 s» del script; con la regla real la orden descansa en su límite y nunca pasa del 3 %.) Frente a la puerta 5 %: entran 98 %, media 1,24 %.

**Nota metodológica:** el «slippage» aquí es la diferencia entre el precio de entrada del backtester (open de la vela i+1) y el bid real en ese segundo. No es que el bot pague de más: es que el backtester era optimista. La corrección de fondo es que el backtester llene al bid (o al open menos un spread estimado) en vez de al open; el lago no tiene bid/ask, así que se calibra en sombra y luego se aplica al motor (área P).

~~ESTUDIO PENDIENTE~~ (hecho el 15-sep): Muestra: 300-500 ticker-días al azar de las entradas reales de 1B (PM, run 8b773d84) y 2B (RTH, run 6023ec78) + los ticker-días de fogonazo y de cadena de halts como grupo «no normal». Datos: NBBO consolidado de Databento (EQUS.MINI mbp-1, 2023+) con operaciones, 1-3 $ (OK de Jaume dado el 14-sep). Medir: (1) en el segundo de la señal y los 10 siguientes: spread (cts y %), acciones en el bid, movimiento a 1/5/10 s, probabilidad de ejecución y coste de un límite al bid, bid −0,3 %, bid −0,7 %, y en el ask → margen y tolerancia de B1, y de rebote el slippage «asumible»; (2) en el cruce del stop: segundos de +0 a +1/+3/+5/+10 % sobre el nivel y margen sobre el ask que habría bastado para ejecutar el 90/95/99 % de los stop limit, normal y fogonazo por separado → márgenes de N1, N2, N3. Contrastar con los fills reales del socio (stop-limit ×1,007 del trigger, 95 % ≤ ×1,07) y con los fills de DAS de Jaume (tarea P7). Script nuevo en `D:ot_senales\estudio_cisnes\`.

### Área H · Locates

### R-H-01 · El locate se pide PRONTO Y BARATO, y se compra cuando el EV lo justifica
- Situación: una acción entra en el radar (premarket high gap ≥ X según el radar). Es cuando el locate está más barato, aunque el trade aún no se dé. **Regla clave del sistema (Jaume, 16-sep).**
- Detección: entrada en el radar. El bot pregunta (inquire) el precio del locate de esa acción. Se cree que el precio se da POR ACCIÓN, no por paquete de 100 [API: confirmar; si es por paquete, se recalcula].
- Acción: (1) enfrentar el precio del locate con el EV de la estrategia que marque el cuadro de mandos, con el MISMO cálculo que ya existe para «¿hay ventaja matemática?» (`PROYECTO_EV_Y_LOCATES.md`, puerta por EV, /evf). (2) Si NO hay ventaja matemática, el bot sigue actualizando el precio del locate de forma continua HASTA que encuentre un precio que, cruzado con el EV, dé ventaja positiva. (3) En ese momento COMPRA los locates y deja de actualizar, salvo que después haga falta más (pirámide, segunda estrategia, locates de un solo uso ya consumidos). (4) Todo registrado en el diario: precio, hora, cantidad, comprado o no, usado o no (H13).
- Quién la ejecuta: módulo de locates (proceso interno; la prealerta y el radar sirven para esto, no van a Telegram, M8).
- Parámetros: EV por estrategia (cuadro de mandos); frecuencia de actualización del precio [por decidir]; cantidad a localizar [por decidir: la del tamaño del cuadro de mandos al precio actual].
- Si la acción falla: el inquire no devuelve nada, no hay locates, la compra no se ejecuta (botón/vía que no funciona): POR DEFINIR, cada caso medido y previsto (H16). Se repasa entero con el PDF.
- Prueba: sombra: registrar precios de locate por hora desde la entrada en el radar y comparar con el precio en el momento de la señal (P4).
- Estado: FIJADA en su lógica (Jaume, 16-sep). TODO el proceso (localización, inquire, actualización, compra, errores) se REPASA con el PDF. Añadir a la lista de preguntas al bróker: unidades del precio del locate, lista de códigos de log y de error del API para poder detectarlos.
- Origen: H1, H2, H13. Decisión del 5-sep («pronto y barato») confirmada el 16-sep.

**Concreción de R-H-01 (Jaume, 16-sep):**
1. **Frecuencia**: actualizar el precio LO MÁS RÁPIDO que permita el API, en paralelo para cada acción que salte al radar, desde el instante en que salta (cada una a su hora). [API: cuota de inquires]. El RADAR tiene que ser configurable desde el cuadro de mandos: no solo por % de subida; también por precio, volumen y lo que se quiera.
2. **PARADA (riesgo de cola): en cuanto se compran los locates que tocan para una acción, el bot DEJA de actualizar y NO compra más para esa acción**, salvo que más adelante los pida otra estrategia o haga falta por lo que sea. Hay que asegurar que nunca entre en un bucle de actualizar y comprar sin control. → R-H-02.
3. **Cantidad**: las acciones que dicte la estrategia al precio de ese momento (es la base del cálculo de EV). Paquetes de 100, tirando POR LO BAJO: si el excedente sobre el paquete no supera el 20 %, no se compra el paquete extra (110 → 1 paquete; 130 → 2 paquetes). **El umbral del 20 % queda PENDIENTE de decidir al final** (H6), como los demás pendientes; el proceso general es este.
4. **Si el precio cambia mucho antes de la señal** y harían falta más locates para el tamaño de la estrategia: de base, SOLO se compran al principio aunque el precio se mueva. Marco para la decisión pendiente: si hiciera falta más de un paquete adicional (p. ej. 100 comprados y ahora 190 necesarios), se compraría otro SOLO si el EV sigue siendo positivo contando el COSTE TOTAL de todos los locates ya pagados más el nuevo, no el nuevo en exclusiva. **PENDIENTE de decidir más adelante.**
5. **Hasta cuándo**: se sigue intentando hasta conseguir un precio con ventaja; el cuadro de mandos podrá fijar un tiempo o una hora límite de intentos.
6. **Tope de gasto en locates (medida de emergencia)**: el gasto en locates NUNCA debe superar el 3 % de la cuenta. → R-H-03.

### R-H-02 · Parada del proceso de locates: comprar una vez y no volver a comprar
- Situación: el módulo de locates ha comprado los paquetes necesarios para una acción.
- Detección: confirmación de compra del locate por DAS.
- Acción: se marca la acción como «localizada» con la cantidad comprada; se DETIENE la actualización de precios y queda PROHIBIDA cualquier compra adicional para esa acción, salvo petición explícita nueva (otra estrategia, pirámide que lo requiera, locates de un solo uso consumidos), que pasa otra vez por el cálculo de EV con el coste total acumulado. Cerrojo por acción y por día.
- Quién la ejecuta: módulo de locates + vigilante (comprueba que no hay compras repetidas).
- Parámetros: ninguno.
- Si la acción falla: si se detecta una segunda compra no pedida → parar el módulo de locates entero y avisar.
- Prueba: tabla de casos; sombra con recuento de compras por acción y día (debe ser 1 salvo peticiones nuevas).
- Estado: FIJADA (Jaume, 16-sep).
- Origen: H1 (riesgo de cola señalado por Jaume).

### R-H-03 · Tope de gasto en locates: 3 % de la cuenta
- Situación: cualquier compra de locates.
- Detección: gasto acumulado en locates (del día) frente al valor de la cuenta.
- Acción: no se compra ningún locate que haga superar el 3 % de la cuenta en gasto de locates. Medida de emergencia; aviso cuando se alcance.
- Quién la ejecuta: guarda del módulo de locates + el VIGILANTE (Jaume, 16-sep): el bot que vigila por encima debe controlar al que ejecuta y, si este falla y no para de comprar locates sin control, es el vigilante quien CORTA esas compras (deshabilita el módulo de locates y avisa). Un bucle de compra de locates es un riesgo de cola muy grande.
- Parámetros: 3 % (cuadro de mandos). Ventana: por día (a confirmar en el repaso).
- Si la acción falla: —
- Prueba: tabla de casos.
- Estado: FIJADA (Jaume, 16-sep).
- Origen: H4, H5, H15.

### R-H-04 · Locate parcial: se opera con lo que hay y se sigue buscando
- Situación: se piden 200 y el bróker solo ofrece 100 (o menos de lo necesario).
- Detección: respuesta del inquire / de la compra con cantidad menor.
- Acción: se compran las que hay (si el EV lo justifica) y se opera con esa cantidad. El módulo sigue buscando el resto con el mismo proceso de R-H-01 (actualizar precio hasta que haya disponibles y con ventaja), y si aparecen se compran, siempre bajo R-H-02 (petición explícita, coste total acumulado) y R-H-03 (tope 3 %).
- Quién la ejecuta: módulo de locates.
- Parámetros: los de R-H-01.
- Si la acción falla: no aparecen más → se sigue solo con lo comprado.
- Prueba: tabla de casos; sombra.
- Estado: FIJADA (Jaume, 16-sep).
- Origen: H3.

**H12 (Jaume, 16-sep): locate con la posición atrapada (halt largo, T12): basta con AVISAR; en la práctica ni hace falta, el humano lo gestiona con el bróker, que le va informando día a día.**

### Área J · Infraestructura

### Área K · Estado y reconciliación

### Área A · Señal y datos

### Área D · Salidas y pirámides

### R-D-01 · Salida por hora de la estrategia: escalera de compra y, si no, al ask
- Situación: la estrategia manda salir por hora (cierre de la estrategia, «Partial TP (Hour)», salida por tiempo). Se compra para cubrir.
- Detección: reloj de la estrategia (hora de salida definida en su JSON) y ask/último precio de DAS.
- Acción: misma lógica que la entrada pero al revés. Escalera de COMPRA agregando liquidez: +1 % sobre el último precio; a los 10 s, +2 %; a los 20 s, +3 %, y ahí hasta completar el minuto. Si al minuto no se ha ejecutado (entera o en parte), lo que quede se compra AL ASK (remover) para asegurar la salida. Lógica estricta «si / si no»: lo ejecutado en la escalera se DESCUENTA y la orden al ask lleva solo el resto; jamás se compra dos veces la misma cantidad (mismo control que R-C-11: posición neta real).
- Quién la ejecuta: ejecutor + vigilante (comprobación de posición neta tras la salida).
- Parámetros: escalones 1/2/3 %; cambio cada 10 s; tiempo total 60 s (los de R-B-01, compartidos).
- Si la acción falla: la orden al ask no se ejecuta (sin liquidez) → R-C-03 (aviso, reintentos) y aviso máximo si llega al EOD de la estrategia (R-D-02).
- Prueba: tabla de casos (ejecuta en escalón 1/2/3, parcial + resto al ask, nada + todo al ask); sombra.
- Estado: FIJADA (Jaume, 17-sep).
- Origen: D3.

### R-D-02 · Fin de día (EOD) POR ESTRATEGIA y botón «control humano»
- Situación: llega el EOD de una estrategia. OJO: el EOD es la hora FINAL de cada estrategia (p. ej. una estrategia de 8:00 a 9:00 tiene EOD a las 9:00), no las 09:30 ni las 16:00. Cada estrategia tiene el suyo.
- Detección: reloj + posiciones abiertas del LOTE de esa estrategia (no de otras).
- Acción: (1) al EOD de la estrategia se cierra lo que quede de su lote con R-D-01. (2) Como R-D-01 puede tardar hasta un minuto más el ask, se da un MARGEN de unos segundos después del EOD antes de comprobar; pasado el margen, si quedan posiciones de ese lote sin cerrar → AVISO MÁXIMO y control humano. (3) Los avisos son POR ESTRATEGIA teniendo en cuenta las demás: si A cierra a las 11 y B a las 12, a las 11 solo se comprueba el lote de A; las posiciones de B no son alarma hasta su EOD. (4) Cuadro de mandos: botón **«Control humano»** que deshabilita el bot (lo apaga) para que las operaciones las hagamos nosotros a mano.
- Quién la ejecuta: ejecutor + vigilante (comprobación por lote) + humano.
- Parámetros (Jaume, 17-sep): la salida de EOD se LANZA 60 s ANTES de la hora de EOD (la escalera termina justo en el EOD y el ask sale en ese instante) y la comprobación se hace 30 s DESPUÉS del EOD. EOD por estrategia (JSON).
- Si la acción falla: —
- Prueba: tabla de casos con dos estrategias de EOD distinto; sombra.
- Estado: FIJADA (Jaume, 17-sep). Sin intentos en after-hours: aviso y humano.
- Origen: D4, D12.

### R-D-03 · Take profit ejecutado a medias y el precio rebota
- Situación: la orden de take profit (compra agregando en el nivel) se ejecuta en parte (300 de 500) y el precio se da la vuelta hacia arriba.
- Detección: fill parcial del take profit + precio por encima del nivel.
- Acción: (1) el resto (200) se cierra con una compra limitP al ask con TECHO del 3 % sobre el último precio (misma protección que el stop principal); en un rebote normal se ejecuta al instante. (2) Si NO se ejecuta porque el precio se ha ido más del 3 %, NO se persigue: la posición sigue en manos de sus dos stops residentes (principal y emergencia), que ya llevan la lógica de squeeze y cisne negro. Nunca una compra a mercado sin techo en ese momento (libro posiblemente vacío). (3) Si no se ejecuta, AVISO al humano: la posición puede quedar en el «limbo» entre el límite y el stop hasta que el precio vuelva a uno de los dos. (4) El bot ajusta en todo momento la cantidad de los stops a la posición que queda «en el aire» (R-C-07: reducir el stop a lo que sigue en corto). (5) Si por un fogonazo se ejecutan compras de más y quedan acciones LARGAS, se venden al instante (R-C-11).
- Quién la ejecuta: ejecutor + vigilante (posición neta, aviso).
- Parámetros: techo 3 % (el de R-C-01).
- Si la acción falla: —
- Prueba: tabla de casos (parcial + rebote pequeño / rebote > 3 % / fogonazo); sombra.
- Estado: FIJADA (Jaume, 17-sep).
- Origen: D2, D14.

### R-D-04 · Reentradas
- Situación: la estrategia vuelve a dar señal en un ticker del que ya se salió ese día (por stop, take profit u hora).
- Detección: señal nueva + historial del día en el diario + parámetros de la estrategia (accept_reentries / max_reentries, como en el backtester).
- Acción: se reentra siempre que la estrategia lo permita y esté dentro de sus límites horarios; si llega su EOD sin take profit, se cierra como en el backtest (R-D-02). Única excepción: tras stop con halt (R-F-03). Locate: se REUTILIZA el ya comprado si el bróker lo permite; si no (locates de un solo uso / SSR), vuelve a pasar por R-H-01 y solo se compra si el EV sigue siendo positivo con el coste total acumulado.
- Quién la ejecuta: guarda (mismo if/elif que el backtester y el bot de avisos: paridad) + módulo de locates.
- Parámetros: los de la estrategia. OJO al centinela: max_reentries = −1 NO es «ninguna» ni «ilimitadas»: significa «sin tope numérico, manda accept_reentries»; 0 es «ninguna». La interfaz escribe −1 al encender el interruptor y 0 al apagarlo.
- Si la acción falla: sin locate disponible → no se reentra, se registra.
- Prueba: tabla de casos (−1 / 0 / N con accept_reentries true/false); paridad con el backtest.
- Estado: FIJADA (Jaume, 17-sep).
- Origen: D6.

### R-D-05 · Se cae el feed de Massive con posiciones abiertas (DAS vivo)
- Situación: el bot deja de recibir datos de Massive (señales y salidas por estrategia imposibles) pero DAS sigue vivo.
- Detección: latido del feed (sin ticks ni velas más de N segundos, parámetro).
- Acción: se MANTIENEN las posiciones con sus stops residentes (el vigilante sigue viendo el precio de DAS y las salidas por hora son de reloj), NO se abren nuevas, y AVISO DE EMERGENCIA inmediato al humano para pasar a control humano.
- Quién la ejecuta: vigilante + supervisor.
- Parámetros: segundos sin feed para declarar caída (por fijar en J2).
- Si la acción falla: si además cae DAS → área J (J3/J4).
- Prueba: simulacro cortando el feed en sombra.
- Estado: FIJADA (Jaume, 17-sep).
- Origen: D7, A3.

**D13 (Jaume, 17-sep): las entradas de las pirámides siguen el MISMO protocolo que las entradas normales (R-B-01/02/03); no hay regla de orden entre niveles.**

**D10 (Jaume, 17-sep): salida por tramos por falta de liquidez: se acepta sin más, igual que R-D-01 (lo que quede al ask al final del minuto); sin límite de tiempo distinto para salidas grandes.**

### R-D-06 · «Cerrar todo» desde Telegram (incluye posiciones manuales)
- Situación: el humano manda por Telegram el comando «cerrar todo» (con confirmación, M1).
- Detección: comando autorizado por chat_id.
- Acción: el bot cierra TODAS las posiciones de la cuenta, incluidas las que no abrió él (manuales): los cortos comprando AL ASK y los largos vendiendo AL BID (remover, rápido). Cancela antes las órdenes vivas de cada posición para no comprar/vender de más (R-C-11). Techo del límite: por decidir (propuesta: el mismo 3 % y, si algo no entra, aviso inmediato con lo que queda).
- Quién la ejecuta: ejecutor por orden del humano.
- Parámetros: techo (por decidir).
- Si la acción falla: aviso con la lista de lo que sigue abierto.
- Prueba: simulacro en demo/sombra con posiciones del bot y manuales.
- Estado: FIJADA en su lógica (Jaume, 17-sep); techo pendiente.
- Origen: D11, M1.

**RECORDATORIO para el día del PDF (Jaume, 17-sep): pedirle las REGLAS DE MARGEN / BUYING POWER de su bróker.** Tiene reglas particulares (margen intradía, PM, autoliquidación en RTH) que pueden afectar a la ejecución y habrá que configurar cosas en función de ellas. → área E (E6) y R-I-01.

### Área E · Capital compartido entre estrategias

### R-E-01 · Lados opuestos sobre el mismo ticker: prohibido
- Situación: una estrategia está corta en un ticker y otra da señal de LARGO en el mismo ticker (o viceversa).
- Detección: señal de sentido contrario al lote abierto en ese ticker.
- Acción: PROHIBIDO hasta nuevo aviso: la señal contraria se descarta y se registra. Una compra sobre un corto solo puede venir de un stop, de un take profit o de una compra de emergencia para netear la posición (R-C-11); nunca de una entrada de otra estrategia.
- Quién la ejecuta: guarda.
- Parámetros: ninguno.
- Si la acción falla: —
- Prueba: tabla de casos.
- Estado: FIJADA (Jaume, 18-sep). Hoy todas las estrategias son cortas.
- Origen: E2.

**Recordatorio del área E (ya decidido en C, B y D):** un lote por estrategia en el diario; entradas simultáneas sumadas en una orden (R-B-03); stop único si coinciden en nivel, uno por lote si difieren (R-C-06 + nota de R-C-11); take profits por lote (R-D-03); la suma de órdenes nunca supera la posición.

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
