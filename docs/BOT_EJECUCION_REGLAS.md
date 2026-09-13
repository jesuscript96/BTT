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

### Área G · El precio se dispara

### Área F · Halts

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
