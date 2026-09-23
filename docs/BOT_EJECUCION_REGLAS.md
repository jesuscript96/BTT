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

## 2b. Lo que ya sabemos del CMD API de DAS (manual oficial, revisión 2021-11-10, encontrado el 19-sep)

Fuente: «Frontend CMD API Manual» de DAS (15 páginas) incluido en el repositorio de un tercero
(github.com/misantroop/das-bridge), que Jaume trajo SOLO como contexto: NO se copia código de ese repo;
el bot se escribe desde este libro. Copia de referencia en D:/bot_senales/bot_ejecucion/referencia_das_bridge/.
**AVISO (Jaume, 19-sep): el manual es de 2021 y NO sabemos si está al día; DAS puede haber cambiado cosas.
Nada de este apartado es definitivo: TODO se coteja con el PDF oficial que dé el bróker.**

**Lo que dice el manual (pasa de [API] a «sabido según el manual de 2021, a cotejar»):**
1. **Token de orden propio (B5)**: NEWORDER lleva un «token» numérico que elige el cliente y vuelve en cada %ORDER → idempotencia posible. Al hacer LOGIN el servidor manda TODAS las posiciones, órdenes y trades (#POS…#POSEND, #Order…#OrderEnd, #Trade…#TradeEnd) y POSREFRESH pide las posiciones: la reconciliación de R-C-10 y R-K-01 está soportada.
2. **Tipos de orden**: MKT, límite, PEG (MID/AGG/PRIM/LAST), STOPMKT (precio de disparo), **STOPLMT (precio de disparo + precio límite: es nuestro limitP con techo)**, STOPTRAILING, STOPRANGE / STOPRANGEMKT (banda baja-alta), oculta/iceberg con Display=0/num (B17: existe). **NO hay OCO ni bracket en el CMD API** → la limpieza de stops la hace el bot (R-C-11), como estaba previsto; el diseño «una principal + una emergencia» se mantiene. **No hay comando REPLACE en este manual** (el repo lo usa; puede ser de una versión posterior): mover un stop sería cancelar y reponer → cotejar.
3. **Vigencia (TIF)**: DAY, DAY+ (extendido; es el valor por defecto), IOC, GTC, AtOpen, AtClose, FOK → premercado cubierto con DAY+.
4. **Rutas**: la orden lleva la ruta (ARCA, INET, …). El manual dice que «algunas rutas pueden no admitir stops» y que SMAT (ruta propia de DAS) los admite todos. MATIZ (Jaume, 19-sep): eso NO quiere decir que ARCA / EDGA / SAGEPRO no los admitan; el repo está pensado para horario de mercado y nosotros operamos también en PM, donde las bolsas no suelen guardar stops. Lo probable es que el stop viva en el servidor de DAS y, al dispararse, salga como límite por la ruta indicada. **PENDIENTE PDF/bróker: qué rutas admiten STOPLMT (y en PM), y el tipo «limitP» que Jaume conoce.** Las rutas preferidas siguen siendo las de Sage (ARCA en PM, SAGEPRO/ARCA en RTH, EDGA para agregar).
5. **Cancelación**: CANCEL orderid y CANCEL ALL (base de «cerrar todo», R-D-06).
6. **Estados de orden**: Hold, Sending, Accepted, Canceled, Rejected, Executed (parcial o total), Triggered, Closed; y acciones %OrderAct: Sending, Send_Rej (rechazo, con campo «notes» con el motivo), Accept, Canceling, Canceled, CancelRej (cancelación rechazada: la carrera de B16), TimeOut, Execute (con precio y acciones del fill), Close → B4 y B16 tienen soporte; los textos concretos de «notes» se piden al bróker (apartado R, punto 14).
7. **Buying power (E6, R-I-01)**: GET BP devuelve el BP intradía y el BP overnight de la cuenta.
8. **GET SHORTINFO símbolo** → shortable Y/N, **shortsize (tamaño máximo de un corto por orden: B10)**, marginable Y/N, tasas de margen largo/corto del símbolo (0 = por defecto, 100 = 100 % en efectivo) → H10 (ETB/HTB) y el margen «alto riesgo» de Sage se pueden leer por símbolo.
9. **Datos**: SB símbolo Lv1 → $Quote con ask, tamaño del ask, bid, tamaño del bid, último, volumen, máximo, mínimo, apertura, cierre de ayer, VWAP y hora; SB tms → time & sales con bandera de condición (bit 5 = válido para último precio: los prints «tardíos / odd lot» se pueden filtrar); SB Lv2 (INET/ARCA/BATS). **$LDLU símbolo limitDown limitUp llega con Lv1 → F11: las bandas LULD vienen por el API.** Las velas de minuto del API llegan con 30 s de retraso (se construyen con time & sales): confirma que la señal va por Massive (R-B-04).
10. **Límites por conexión**: 50 símbolos en Lv1/T&S, 10 en Lv2, 50 en gráficos. El vigilante solo necesita Lv1 de las posiciones abiertas: cabe. El radar (~300 tickers) va por Massive, no por DAS.
11. **Varias conexiones**: el comando CLIENT «devuelve el número de clientes conectados» y LOGIN admite modo «watch» (1 = solo lectura, recibe %IORDER/%IPOS/%ITRADE) → el API parece admitir más de una conexión al mismo DAS: el vigilante podría tener la suya (R-C-08 requisito 1). Cotejar si una segunda conexión normal puede enviar órdenes.
12. **Locates**: SLPRICEINQUIRE símbolo acciones ruta/ALLROUTE → %SLRET tipo 1 con **precio POR ACCIÓN** y tamaño ofrecido (0 = no hay acciones para localizar), o tipo 2 = fallo con motivo (p. ej. «Already Shortable» = ETB, no hace falta locate). SLNEWORDER para pedir; SLCANCELORDER; SLOFFEROPERATION id Accept/Reject (rutas «tipo 1», con oferta que hay que aceptar); %SLOrder con estados Sending, Waiting, Located, Offered, Canceled, Rejected, Closed, Declined; SLAvailQuery cuenta símbolo → acciones disponibles. → H16 tiene respuesta técnica: «no hay» = tamaño 0 o tipo 2; el «tipo de ruta de locate» de Sage (0 o 1) es pregunta al bróker.
13. **Estado de conexión**: mensajes #OrderServer / #QuoteServer Logon/Connect Successful/Failed → R-J-02 puede detectar la caída del servidor de órdenes aunque el socket local siga vivo (R-K-03).

**Sigue SIN respuesta en el manual (se mantiene [API] / pregunta al bróker):**
- Por qué precio dispara un STOPLMT (último, bid, ask): el manual remite a «los campos del montage» → C6 pendiente de sintaxis (Jaume recuerda «Ask + 0,01» en el montage).
- Bandera de **SSR** y estado de **HALT**: no aparecen en $Quote ni en T&S → F1 y F10 pendientes (fuente externa: Nasdaq Trader / Databento en vivo, o el rechazo de la orden).
- Cuotas de mensajes (J18), 2FA y sesión de noche (J15), un login por cuenta (J11), REPLACE, órdenes «solo cerrar». Menores: formato de los decimales bajo 1 $ en NEWORDER (B9; DAS trabaja con 4 decimales en todo lo que muestra). **Demo: SÍ existe (Jaume, 19-sep) → O1 resuelta.**

## 2c. Reglas de margen de Sage (página pública, leída el 19-sep) y qué implican con 10-12 k$

Cuenta relevante: **SageTrader Pro** (depósito inicial 3.000 $, mantener 2.000 $): buying power total 4× el equity; largo máximo 2×; **corto máximo 1× el equity; cortos «de alto riesgo» 0,5× el equity**. Margen inicial de cortos (Reg T): precio < 5 $ → el mayor de 2,50 $/acción o el 100 % del valor; ≥ 5 $ → el mayor de 5 $/acción o el 30 %. Mantenimiento (FINRA 4210) de cortos: < 2,50 $ → 2,50 $/acción; 2,50-4,99 $ → 100 % del valor; 5-16,66 $ → 5 $/acción; ≥ 16,67 $ → 30 %. La página NO habla de PDT, intradía vs overnight, PM, llamadas de margen ni concentración. **Autoliquidación (Jaume, 19-sep): SOLO existe en horario de mercado; en premercado NO pueden autoliquidar.**

Consecuencias para el bot (cuenta de 10-12 k$, todo cortos en small caps):
1. **El «capital libre» de R-I-01 no es el nominal: es el margen.** Un corto de 1.000 acciones a 1 $ (1.000 $ nominales) exige 2.500 $ de margen (2,50 $/acción). Con 10 k$, el corto máximo a 1 $ sería ≈ 4.000 acciones (4.000 $ nominales), y la mitad si el valor es «alto riesgo». El bot debe calcular el margen exigido de cada orden por tramo de precio ANTES de enviarla y dimensionar con GET BP y la tasa del símbolo de GET SHORTINFO, no con el nominal.
2. **Tope de exposición corta total: 1× el equity (0,5× en «alto riesgo»)** sumando todas las estrategias. Encaja con E3 (reparto del cuadro de mandos), pero el bot lo comprueba contra el BP real.
3. **Orden rechazada por margen**: llegará como Send_Rej con motivo → guarda previa + tratamiento del rechazo (B4).
4. **Posición que cambia de tramo**: un corto abierto a 5,20 $ que baja a 4,90 $ pasa del 30 % al 100 % de mantenimiento (y a 2,50 $/acción bajo 2,50 $): el margen exigido SUBE cuando la operación va a favor. Con posiciones pequeñas no importa; con tamaño puede disparar la autoliquidación del bróker. El vigilante debería vigilar el margen de mantenimiento total frente al equity.

**PREGUNTAS AL BRÓKER (se suman al apartado R):** qué valores son «alto riesgo» (lista o criterio: precio, float, HTB); si el BP que devuelve GET BP ya descuenta estas reglas por símbolo; cómo y a qué hora autoliquida en RTH y qué avisa antes; qué pasa con un corto abierto en PM que supera el margen; si aplican PDT (con 10-12 k$, por debajo de 25 k$, aplicaría: ¿3 day trades en 5 días?); llamadas de margen y plazos.

## 2d. Lo que dice la base de conocimiento pública de DAS (dastrader.com, leída el 23-sep; informe completo en `bot_ejecucion/referencia_das_kb/INFORME_KB_DAS.md`)
Responde total o parcialmente 35 de las 42 preguntas, casi siempre para la plataforma, no para el API. Lo que cambia o confirma:
1. **API**: hace falta pasar la certificación de DAS (no viene con la suscripción), TAMBIÉN para la cuenta demo; se factura por el bróker desde el día en que se pide activar, no al aprobar; desde ~100 $/mes (Basic CMD), sube con símbolos y órdenes/día. Cuotas = órdenes por DÍA y símbolos simultáneos (100/150/250 según nivel), no peticiones por segundo. Sin Level 2 por el API. El CMD API exige DAS Pro abierto y logueado; el .NET API no. Locates por API: consultar, precio y comprar. → PEDIR LA CERTIFICACIÓN YA; la fase demo no empieza hasta aprobarla.
2. **Stops**: «STOP price is triggered off the last print in between the BID and ASK price (Bid ≤ Last ≤ Ask). It does not use the print in the Time and Sales»: un print fuera del spread no dispara hasta que las cotizaciones lo alcanzan. No dice si es el stop normal o el LimitP ni nada de PM. **Halt**: los stops en el smart router de DAS (SMAT) «trigger normally after trading resumes» y los nuevos se aceptan sin disparar hasta reabrir; los enviados a una ruta concreta (ARCAS) quedan a la política de la ruta → los stops residentes van al SMAT.
3. **Órdenes durante un halt** (R-F-01): una orden a mercado nueva «will be sent to the configured route and handled by the route»; para límites «confer with your broker on which routes will accept». NO garantiza que entre en el cruce de reapertura → probar en demo ruta por ruta.
4. **La plataforma tiene OCO y Trigger Orders** (la secundaria sale al llenarse la principal; solo si «fully executed», una entrada a medias no la dispara) y Stop Range. Pega del OCO: la pata nueva «requires buying power». Si el API los expone es pregunta viva.
5. **Controles de riesgo del bróker** (`risk-control`): MaxLoss/Total Loss/Max Unreal → «all new orders will be rejected» ese día; por posición «Position Unreal Loss» / «Pos Mkt Px deviate» → «no more trades for this symbol» salvo «Always allow unwind positions»; topes Max Ord Cap, Max Pos Val, Max num of open orders per symbol/side, Max short position shares, Low Price max short, Min/Max stock price, Symbols/Route Control, Max Total Locate Fee. Auto Stop del bróker solo en RTH; puede haber «Unwind all SHORT at 3:59PM».
6. **BP**: precio < 5 $ exige 100 % (o 50 %) en efectivo; orden a mercado retiene un 5 % extra (10 % en simulador).
7. **SSR**: código SSR en el montage; corto solo ≥ bid + 0,01 (el punto medio de R-B-01 cumple). Códigos de estado del símbolo: H halted, P paused, Q/T resumed, S shortable, HTB. Condiciones de T&S que NO cuentan para último precio ni velas: C, G, H, I, M, N, P, Q, R, U, V, W, Z, 3, 4, 7.
8. **Locates**: válidos solo el mismo día; «locate shares cannot be greater than an inquire shares»; estados Waiting/Offered/Located/Canceled/Rejected; se puede cancelar tras aceptar.
9. **Sesión**: 2FA opcional (TOTP); dos redes de servidores de órdenes (.org Hibernia / .net Cogent) que hay que mantener; «Auto Balance Quote Server»; latencia buena hasta 500 ms; DAS recomienda VPS EC2 en NY/NJ. Reloj: sincroniza con NIST cada 10 min; los logs locales usan la hora del PC.
10. **GUI**: ajustes que abren ventanas («Send Order Confirm», «Same Order in 10 seconds», «Price Check», stop «too low or too high», «Enable Fast Stop Limit Order») → desactivar en el perfil del bot y preguntar si afectan al API. Rutas con sufijo L/M/S; «Don't automatically load route list». «Auto Save Trade» cada N s = fuente de reconciliación sin gastar cuota.
11. **Suscriptor profesional**: usar capital de otros o repartir beneficios pasa los datos a tarifa profesional; revisar el cuestionario antes de pedir el API.

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

**LimitP / StopLimitP (comprobado el 22-sep en el vídeo de Ocean Securities que pasó Jaume, «How to Use LimitP Stop Orders in DAS Trader Pro»):** en DAS Trader Pro existe el tipo de orden **StopLimitP («LimitP»)**: un stop limit que **dispara SOLO cuando el ÚLTIMO PRECIO CRUZADO toca el nivel**, no el bid/ask; pensado para premercado y after-hours, donde el spread ancho dispararía en falso un stop normal. Consecuencias para el libro: (1) hasta hoy el libro decía «disparo por ask» (C6) y el estudio de fogonazos se simuló así; con LimitP el disparo es por PRINT, así que se ha repetido el estudio con disparo por último precio (`40b_fogonazos_disparo_last.py`, resultados abajo); (2) el filtro de prints tardíos (R-A-02) pasa a ser relevante también para los stops: un print tardío o suelto podría disparar (o retrasar) un LimitP; (3) PREGUNTA al bróker [R-22]: si el API expone StopLimitP además de STOPLMT (el manual 2021 solo lista STOPLMT), cuál es el disparo de cada uno (último / bid / ask) y cuál conviene en PM. Jaume lo llama LimitP porque así aparece literal en las opciones de DAS Pro; es el nombre bueno. **Resultado de repetir el estudio con disparo por ÚLTIMO PRECIO (`40b`, 241 fogonazos, 10 k, 10 % por posición): sale en la subida el 86 % (por ask era el 96 %), en la bajada el 13 % (4 %), y quedan 2 posiciones SIN CERRAR a la media hora (TNON y ZEO): en TNON el último precio saltó de 7,02 a 35 $ en un solo print, los dos stops dispararon con el precio ya por encima de sus límites y no llenaron nada; cerrar a la media hora a 55,60 $ costaba el 80 % de la cuenta. Con disparo por ask ese mismo caso salía por el principal a 6,93 $ (1,3 % de la cuenta) porque el ask CAMINA antes de que se cruce el print. Pérdida media sobre la cuenta 3,6 % (2,6 % por ask), p90 7,0 % (6,2 %). Conclusión: para la protección contra fogonazos el disparo por ASK es claramente mejor; el disparo por último precio (LimitP) evita disparos en falso por spread ancho pero llega tarde en el fogonazo. DECISIÓN PENDIENTE (con el PDF): qué disparo usa STOPLMT por el API; si se puede elegir, principal y emergencia por ask/bid, y medir en sombra cuántos disparos en falso produce el ask con spreads anchos en PM (coste: salir antes de tiempo de un corto bueno y reentrar). Si solo hay LimitP, hay que rediseñar la emergencia (p. ej. stop a mercado en vez de límite, o vigilante que dispare por ask).** **Matiz de Jaume (22-sep, tarde): el stop limit normal NO funciona en premercado (probado por ellos); LimitP SÍ. Y TNON y ZEO son arranques del día (ZEO: 04:07, gap previo 40 %, 2.035 $ negociados antes), donde ninguna estrategia está dentro. Comprobado: sobre los 122 fogonazos «dentro de un gap ya hecho», LimitP sale en la subida el 95 % (ask 99 %), pérdida media 2,8 % (2,3 %), p90 6,3 % (6,1 %), máximo 8,4 % (igual); y en los 7 fogonazos donde 1B estaba dentro de verdad, con LimitP los 7 salen en la subida igual que por ask (6 por el principal al 10-13 %, LGHL por la emergencia al 65 %). Conclusión: para nuestra exposición real LimitP cubre prácticamente lo mismo; la diferencia grande por ask solo aparece en los arranques del día, donde no estamos. Por tanto: en PM los stops van en LimitP (disparo por último precio); la pregunta R-22 sigue para saber si el API lo expone y si en RTH conviene otro disparo.**

**Varias estrategias con NIVELES de stop distintos sobre el mismo ticker (Jaume, 22-sep; PROPUESTA a decidir):** de inicio todas comparten el mismo par (3 % / 50 %). Cuando haya estrategias con niveles distintos (p. ej. A al Previous Max y B a +10 % de su entrada): UN stop principal POR NIVEL con las acciones de las estrategias que comparten ese nivel (si dos coinciden, un solo principal con la suma). Para la emergencia, dos opciones:
(a) **Una sola emergencia con TODA la posición, por encima del principal más alto** (lo que propone Jaume como simple). Problema del «limbo»: si el precio pasa de largo el principal más BAJO (B) sin llenarlo, las acciones de B quedan cubiertas solo por una emergencia calculada sobre A: con A en 10 $ (principal 11,00/11,33, emergencia 12,46/18,70) y B en 9 $ (principal 9,90/10,20), las acciones de B no tienen nada entre 10,20 y 12,46 y su techo real es 18,70 = +108 % sobre SU entrada, no +87 %.
(b) **Un PAR por nivel (principal + emergencia), compartido por las estrategias del mismo nivel.** Con dos niveles son 4 órdenes; nadie queda en limbo porque cada emergencia está a la distancia prevista de su principal. Coste: más órdenes que netear (R-C-11 ya trabaja por eventos y con token por orden, así que es mecánico) y un caso nuevo: una emergencia baja que dispara mientras la posición del nivel alto sigue viva se limita a SUS acciones, no toca las otras.
**DECISIÓN de Jaume (22-sep): (a).** Un principal (3 %) por nivel de stop y UNA sola emergencia (50 %) con toda la posición, por encima del principal más alto; motivo: con muchos stops los márgenes pueden solaparse (una emergencia de un nivel cayendo dentro del margen del principal de otro) y liarse. Consecuencia aceptada: las estrategias de nivel más bajo tienen un techo mayor que el +87 % mientras no llegue la emergencia. **Mitigación FIJADA (Jaume, 22-sep):** si el precio pasa de largo el LÍMITE del principal de un nivel sin llenarlo (lo ve el vigilante, R-C-03/04), ese principal se cancela y sus acciones se SUMAN al principal del siguiente nivel por encima (el de A): B sale al nivel de A. Si el principal rebasado era ya el más alto (no hay otro encima), sus acciones se recolocan como principal nuevo al ask del momento + 3 %. Siempre una sola emergencia con toda la posición. Escenario raro; regla sencilla.

**Qué es el «+87 %» (Jaume, 22-sep):** los márgenes se ENCADENAN, no se suman. Principal: disparo +10 % sobre la entrada; límite +3 % sobre el disparo → 1,10 × 1,03 = +13,3 %. Emergencia: disparo +10 % sobre el LÍMITE del principal → 1,133 × 1,10 = +24,6 %; límite +50 % sobre SU disparo → 1,246 × 1,50 = **+86,9 % sobre la entrada**. El «+10 % de disparo» del ejemplo NO es una regla: el disparo del principal es el NIVEL DE STOP DE LA ESTRATEGIA, esté donde esté (Previous Max, +10 %, ATR…). La cadena general: principal = nivel de la estrategia, límite = nivel × 1,03; emergencia: disparo = límite del principal × 1,10, límite = disparo × 1,50. Con el stop al Previous Max a +25 % de la entrada, el techo sale 1,25 × 1,03 × 1,10 × 1,50 = +112 % sobre la entrada. El «87 %» era solo el caso del ejemplo con stop a +10 %. Alternativa si se quiere un techo más corto: medir el 50 % sobre el límite del principal (+70 % en el ejemplo). El estudio de fogonazos está hecho con el +87 %; con un techo más bajo llenan menos en los saltos grandes (más COLA) a cambio de una pérdida máxima menor: se puede repetir el estudio con el techo que elija Jaume en minutos (`40_`, parámetro MARG2).

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

**Decidido el 20-sep (Jaume) para el caso «sigue quedando algo corto»** (ej.: 100 cortas, el principal cubre 40, la emergencia 30, quedan 30 cortas y las dos órdenes vivas con cantidades viejas): (1) se CANCELA el stop principal (su momento pasó: está por debajo del precio y probablemente DAS no dejaría recolocarlo); (2) la orden de EMERGENCIA se AJUSTA a las acciones que quedan (30) si DAS permite cambiar la cantidad in situ [API/bróker: confirmar]; (3) si DAS cancela o rechaza la emergencia, se REPONE una nueva con el mismo trigger y límite por las acciones que quedan; (4) SIEMPRE EXACTAMENTE UNA orden de emergencia por posición: el vigilante lo comprueba (nunca 1.000 stops iguales al mismo nivel; riesgo de bucle); (5) si no se llega a ajustar o reponer a tiempo y al bajar el precio la emergencia compra de más (las 70 viejas), el exceso LARGO se vende al instante al bid, como siempre (R-C-11). Pregunta 2 (qué se toca durante el protocolo de cisne negro) PENDIENTE de contestar.
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
- **Plan B FIJADO (Jaume, 21-sep): el vigilante REPONE.** Si el ejecutor está caído (o tarda) y una posición se queda sin stop, o un stop desaparece, el vigilante pone él mismo el par principal + emergencia con los valores del libro y avisa. Y NETEA: cuando el ejecutor vuelve y quiere poner sus stops, primero lee las órdenes vivas en DAS; si ya hay un stop del vigilante sobre esa posición, lo ADOPTA (lo registra como suyo) en vez de poner otro. El vigilante, en cada barrido, comprueba que por posición hay exactamente UN principal y UNA emergencia con la cantidad correcta: sobrantes → cancelar el más nuevo; faltantes → reponer. Cada orden lleva en su token quién la puso (ejecutor/vigilante) para que el neteo sea inequívoco. Nunca dos stops del mismo tipo sobre la misma posición más que un instante (riesgo de cubrir el doble, R-C-11).
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

### R-G-01 · Protocolo de cisne negro: el bot NO decide; informa cada 5 minutos y cierra el humano
- Situación: el precio ha pasado del límite de la orden de emergencia (R-C-01) sin ejecutarla: quedan acciones cortas al descubierto.
- Principio (Jaume, 20-sep): el bot NO coloca órdenes que persigan al precio en mitad de un fogonazo o squeeze (la volatilidad podría sacarnos a un precio extremo) ni toma decisiones de cierre: un error de código o la falta de liquidez lo harían contraproducente. En el peor escenario cierra el HUMANO, vigilando de la mano del bot. La orden de emergencia sigue puesta: si el precio vuelve a su límite, se ejecuta sola.
- Acción: (1) ALERTA MÁXIMA por Telegram, SMS y correo en el instante. (2) Cada 5 minutos, mensaje por Telegram con este formato:

  «Posible BS <TICKER>»
  - Precio del stop normal y del de emergencia.
  - Precio en el momento del mensaje (y bid / ask).
  - Minutos desde el evento.
  - Al descubierto: acciones cortas que no se han podido cerrar en el stop de emergencia.
  - % de pérdida sobre el trade (latente, al precio actual).
  - % de pérdida sobre la cuenta, total (contando lo ya perdido en los stops), también en $.
  - Máximo % de subida de la acción respecto al PRIMER stop desde que empezó el movimiento (para saber ante qué fogonazo estamos: 100, 200, 1.000 %…).
  - % actual de la acción respecto al primer stop (el slippage que nos comeríamos si cerramos ahora).
  - Pérdida ya ejecutada del trade, en $ y %: lo perdido en las acciones que sí salieron por el stop normal y por el de emergencia.
  - Recordatorio de comandos: /cerrar TICKER SI (cierra TODA la posición al ask con techo), /cerrar TICKER N SI (cierra SOLO N acciones y deja el resto: es el cierre por tramos de G6, decidido por el humano), /estado TICKER, /parar_avisos TICKER BS (deja de mandar SOLO el mensaje de 5 min de ESE evento de ESE ticker; todo lo demás sigue igual, y un evento nuevo vuelve a arrancar el ciclo), /reanudar_avisos TICKER BS.
  Datos añadidos (aprobados por Jaume, 20-sep): halts (SOLO en sesión de mercado: si está parada, distancia a la banda LULD, halts que lleva el día k), minutos desde el máximo del movimiento y si lleva N minutos bajando, minutos hasta el EOD de la estrategia, y estado de la orden de emergencia (sigue viva, su precio límite). No incluidos: volumen 5 min, spread, conexión DAS (van en /salud y /estado).
  (3) Si el fogonazo se cierra DENTRO del stop de emergencia, se manda el mismo informe UNA sola vez con la frase «POSICIÓN SACADA CON ÉXITO DENTRO DEL MARGEN DEL STOP DE EMERGENCIA».
  (4) Todo fogonazo visto en vivo (con o sin posición) se registra en el diario con su máximo, duración y devolución, para recalibrar los umbrales con datos propios (G10).
- Quién la ejecuta: vigilante (informes y registro) + humano (decisión y cierre por Telegram).
- Parámetros: cadencia de informes: CADA MINUTO los 5 primeros minutos y después cada 5 min, mismo mensaje (Jaume, 22-sep; antes «cada 5 min»).
- Si la acción falla: sin Telegram → correo y SMS con el mismo informe (R-M-02).
- Prueba: simular el protocolo con un día grabado de fogonazo (R-O-02) y comprobar formato y cadencia.
- Estado: FIJADA (Jaume, 20-sep). Sustituye a la «espera de media hora» de R-C-01 como procedimiento: no hay plazo fijo, el humano decide cuándo. Origen: G1, G2, G3, G4, G6, G7, G10.

**Caso real AEMD 17-sep-2026 (estudio 20-sep, `38_aemd_bs.py`, Databento 0,03 $): qué habría hecho el protocolo.** A las 06:43:38 el ask pasó de 4,4 a 14,0 $ en UN segundo (pico 13,90, +230 % sobre 4,2; libro Nasdaq de 8 k$ a 129 k$ en el ask) y a los 2 minutos estaba en 6-7; segundo empujón 06:54-06:56 hasta 9,50. En los 30 min del evento se negociaron 168 k acciones (1 M $). Corto hipotético en 5,80 con posición del 10 % de la cuenta, stop principal +10 % (6,38 / límite 6,57), emergencia 7,23 / límite 10,84:
- **Comerse el fogonazo de las 06:43 de lleno** (hipotético: el precio nunca estuvo en 5,80 antes; sirve como caso extremo): el principal NO llena nada (el ask saltó los dos triggers en un segundo); la emergencia llena TODO en los minutos siguientes al volver el precio bajo 10,84: precio medio 9,80 (cuenta 10 k) a 8,78 (100 k). Pérdida 69 % del trade = 6,9 % de la cuenta (10 k); 51 % = 5,1 % (100 k). Con cuentas de 200 k a 2 M (3.400 a 34.000 acciones) la emergencia también llena entera dentro de la media hora (precio medio 8,7 → 7,9) porque el precio se quedó horas en 6-8 con volumen: **no se encontró el capital a partir del cual no se sale**; el límite práctico lo pone la paciencia (hasta 30 min) más que el libro. Sin necesidad de cierre humano a la media hora en ningún tamaño.
- **Entrada real en 5,80 tras el fogonazo (06:44) con stop +10 %**: el principal dispara a las 06:44:06 en la subida a 6,81 y llena TODO en todos los tamaños a 6,24-6,36: pérdida 7,5-9,7 % del trade, 0,75-0,97 % de la cuenta. Un stop normal.
- **Con stop +30 % (para comerse el segundo empujón a 9,50)**: el principal dispara a las 06:45:58 (7,54) y llena todo a 7,3-7,5: 26-29 % del trade, 2,6-2,9 % de la cuenta. La emergencia no hizo falta.
- **Entrada en la vela ANTERIOR al fogonazo (4,22, cierre de la 06:42), stop +10 % (4,64 / límite 4,78; emergencia 5,26 / límite 7,89)**: el ask tocó 4,64 unos segundos antes del salto y en el libro había ≈ 1.190 acciones dentro del límite: hasta 50 k$ de cuenta (1.184 acciones) el PRINCIPAL llena todo a 4,56-4,65 (pérdida 8-10 % del trade, 0,8-1,0 % de la cuenta). Con 100 k (2.369 acciones) el principal llena la mitad y la EMERGENCIA el resto al volver el precio, a 5,75 de media (22 % del trade, 2,2 % de la cuenta). Con 500 k (11.848 acciones) la emergencia llena todo pero a 7,05 (61 % del trade, 6,1 % de la cuenta). Se sale siempre dentro de la emergencia; lo que crece con el tamaño es el precio. (Cifras de la primera pasada con fotos de 1 s; con fotos de 100 ms el principal llena todo en todos los tamaños a 4,55-4,74: ver conclusión corregida más abajo.)
- Aviso metodológico: libro solo Nasdaq (el consolidado tiene más), fotos por segundo, se consume el 100 % de lo mostrado en el disparo y el 50 % después. Los precios medios de los tamaños grandes bajan porque la orden espera hasta 30 min y llena en la bajada.

### R-G-03 · Durante el protocolo de cisne negro: solo se ajusta la cantidad; sin reentrada hasta que el humano lo diga
- Situación: protocolo R-G-01 activo (precio por encima del límite de la emergencia, acciones al descubierto).
- Acción sobre la orden de emergencia (Jaume, 20-sep): (1) SOLO se le baja la CANTIDAD a las acciones que realmente quedan cortas, si DAS permite cambiarla in situ [confirmar con DAS/PDF]; nada más: ni límite, ni trigger, ni perseguir al precio. (2) NO se repone si DAS la cancela durante el evento: si DAS la ha eliminado es deliberado (queda registrado en el diario), la alerta sigue y decide el humano; además DAS probablemente no deja crear un stop por debajo del precio actual. (3) Si el humano manda /cerrar TICKER SI, el bot CANCELA antes la emergencia para que no compre ella también (R-M-04).
- Reentrada: tras un cisne negro en un ticker, NO se reentra en ese ticker hasta que el humano lo autorice (/sigue TICKER). Dato para tenerlo en cuenta: en el estudio, las operaciones de 1B que entraron DESPUÉS de un fogonazo (247, mediana 13 min después) rindieron +15 % de mediana frente a +8 % del conjunto; la autorización humana decide caso a caso.
- Estado: FIJADA (Jaume, 20-sep). Origen: pregunta 2 del repaso de stops; reentrada tras BS.
- Nota (1.3): reponer la emergencia si DAS la cancela o rechaza vale para OPERATIVA NORMAL (fuera del protocolo); dentro del protocolo, no.

**Caso real PLYX 17-feb-2026 (`39_plyx_bs.py`, libro Nasdaq ya descargado):** máximo del PM 3,85 a las 06:02; entrada hipotética un 5 % por debajo (3,657, tocado ese mismo minuto); fogonazo a las 06:34:39-06:35:44 de 3,3 a 52,97 en Nasdaq (76,29 en el consolidado), +1.348 % sobre la entrada; el libro Nasdaq en el ask pasó de 4.805 $ (60 s antes) a 616 $ en el disparo y 0 $ en el pico. Stops +10 %: principal 4,02 / 4,14; emergencia 4,56 / 6,84. Los dos triggers se tocan con 0,2 s de diferencia; el principal NO llena nada; la emergencia llena TODO al volver el precio, a 6,40 de media en todos los tamaños (de 273 a 13.672 acciones: había una oferta grande en 6,40): **pérdida 75 % del trade = 7,5 % de la cuenta con posición del 10 %** (2,25 % con posición del 3 %). El mínimo del ask en los 30 min siguientes fue 3,97 (por debajo de la entrada): la emergencia compra en el primer nivel dentro de su límite al volver, no espera a que baje más. En el backtest, 1B tuvo PLYX dentro ese día y el motor lo cerró «al nivel» del stop (−22 a −65 %): el motor es optimista en fogonazos. Negociado en 30 min: 49 k acciones, 403 k $.
**Caso real SLGB 9-jun-2026 (mismo script, TK=SLGB), CORREGIDO con fotos del libro de 100 ms** (la primera pasada, con una foto por segundo, se perdía el tramo en que el ask CAMINÓ): máximo del PM 1,40; entrada 1,33; fogonazo 06:33:03-06:33:59 de 1,36 a 12,66. El ask fue 1,46 → 1,55 → 1,57 → 1,87 → 1,96 en unos 4 segundos, con 2.400-6.500 acciones ofrecidas dentro de nuestros límites en esas décimas, y DESPUÉS saltó a 13,30. Principal (1,463 / 1,507): 0 llenas (las 3.400 acciones ≤ 1,507 desaparecen en la misma décima de segundo; con la latencia de DAS no se llega). Emergencia (1,66 / 2,49): llena TODO **en la subida, en los primeros segundos**, a 1,80 de media con 751 acciones (cuenta 10 k) → pérdida 35 % del trade = 3,5 % de la cuenta; con 20-500 k, a 2,0-2,1 (51-60 % del trade, 5-6 % de la cuenta). Cuadra con la experiencia del compañero de Jaume (salió de SLGB con el 10 % de 10 k, stop +10 % y emergencia a +30-40 %).
**Los tres casos con fotos de 100 ms:** AEMD con entrada antes del fogonazo (4,22): el ask caminó de 4,4 a 4,8 unas décimas antes de saltar y el PRINCIPAL llena todo en todos los tamaños a 4,55-4,74 (pérdida 8-12 % del trade, 0,8-1,2 % de la cuenta, incluso con 500 k). PLYX: nada camina, libro a 0 $, solo la emergencia en la bajada a 6,40 (75 % del trade). SLGB: el principal no llega, la emergencia sale en la subida (35-60 %).
**Estudio por tamaño sobre TODOS los fogonazos registrados (`40_fogonazos_por_tamano.py`, 20-sep, muestra ampliada): 251 fogonazos 2019-2026 (55 con salto ≥ 100 %, 196 de 50-100 %) con libro Nasdaq de 10 niveles y 30 min tras el pico (descarga `41_…`, 1,47 $). 3 excluidos porque el libro Nasdaq nunca llegó al trigger (OTLK, RGC, BQ: el fogonazo se cruzó en otras bolsas); 40 sin cobertura.** Corto abierto ANTES del fogonazo al último precio, posición 10 % de la cuenta, stops del libro (principal +10 % / límite +3 %; emergencia +10 % sobre ese límite / +50 %), disparo por ask, latencia DAS 200 ms, fotos de 100 ms, 100 % de lo mostrado al llegar la orden y 50 % en cada foto posterior.
| Cuenta | Sale en la SUBIDA | Sale en la BAJADA | No sale en 30 min | Pérdida sobre la cuenta: media / mediana / p90 / máx | Pérdida sobre el trade: mediana / p90 |
|---|---|---|---|---|---|
| 10 k | 96 % | 4 % | 0 % | 2,6 / 1,3 / 6,2 / 8,3 % | 13 / 62 % |
| 20 k | 96 % | 4 % | 0 % | 2,8 / 1,5 / 6,2 / 8,4 % | 15 / 62 % |
| 50 k | 93 % | 7 % | 0 % | 2,9 / 2,4 / 6,4 / 8,4 % | 24 / 64 % |
| 100 k | 90 % | 10 % | 0 % | 3,0 / 2,6 / 6,5 / 8,4 % | 27 / 65 % |
| 500 k | 83 % | 16 % | 0-1 % | 3,2 / 3,0 / 6,7 / 8,4 % | 30 / 67 % |
Solo saltos ≥ 100 % (55): subida 91 % (10 k) → 73 % (500 k); bajada 9 → 27 %; sin salir 0 %; pérdida sobre la cuenta media 2,6-3,5 %, p90 5,9-7,0 %, máx 8,3 %.
Lecturas: (1) con la emergencia puesta NADIE se queda dentro a los 30 min (1 caso de 251 con 500 k); (2) con cuentas pequeñas se sale en la subida el 96 %, y aun con 500 k el 83 %; (3) pérdida sobre la cuenta con el 10 % por posición: media 2,6-3,2 %, mediana 1,3-3,0 %, peor 10 % ≈ 6,2-6,7 %, máximo 8,4 % (MODD 11-feb-2022: la emergencia compró casi en su techo); con el 3 % por posición dividir por 3,3: media ≈ 0,8-1 %, máximo ≈ 2,5 %; (4) la mediana sube con el tamaño (1,3 % → 3 %) porque la orden grande termina de llenarse más arriba. Cautelas: libro solo Nasdaq (conservador), fotos de 100 ms, consumo del 50 % por foto hasta 30 min (generoso en tamaños grandes), latencia fija 200 ms (medir en sombra). 
Complemento (20-sep, misma muestra): ¿quién saca? Con 10 k basta el principal en el 49 % y la emergencia interviene en el 51 % (con 100 k: 40/60; con 500 k: 32/68); en el 47 % de los fogonazos el principal no llena NADA y la emergencia se lleva toda la posición, y siempre llenó. ¿Y sin ningún stop? Cubrir en el pico: pérdida sobre el trade mediana 59 %, p90 194 %, máx 4.836 % (ENSC 11-may-2026); sobre la cuenta con 10 % por posición: 5,9 / 19 / 484 %. Cubrir a la media hora del pico: 10 / 99 / 779 % sobre el trade (TNON); solo en el 33 % de los casos el precio está ya por debajo de la entrada a la media hora. 5 de 251 fogonazos saltan más del 1.000 % (ENSC, CIIT, PLYX, TNON, XHG): con el 10 % por posición cada uno se lleva más que la cuenta entera. Vuelta tras el pico (20-sep, fogonazos_vuelta_30min.csv): a los 30 min del pico el ask está por debajo de la entrada solo en el 33 %, por debajo del límite del principal (+13 %) en el 55 % y por debajo del límite de la emergencia (+87 % sobre la entrada: el 50 % se mide sobre el trigger de la emergencia, no sobre la entrada) en el 88 %; 29 casos (12 %) siguen por encima del +87 % a la media hora, y en saltos > 300 % son el 36 %. TNON 13-sep-2024 (gráfico en bot_ejecucion/TNON_2024-09-13_dia.png): pico 130 $ a las 04:10, +763 % a la media hora, +981 % a la hora, +139 % a las 3 h, cierre +24 %; la emergencia (11,48 $) no se habría llenado en la bajada hasta las 09:07. Lección: la emergencia debe llenarse en la SUBIDA (en los 251 lo hizo siempre); si no, el techo sigue siendo su límite (+87 % del trade, 8,7 % de la cuenta con el 10 %), pero la espera puede ser de horas. Día entero de los 29 lentos (fogonazos_vuelta_dia.csv, velas 1 min Nasdaq): 27 vuelven bajo el límite de la emergencia ese mismo día (la mayoría en el minuto siguiente al pico; los lentos: TNON 4,9 h, ZEO 3,5 h) y 2 NO vuelven nunca ese día (GRYP 12-may-2025 cierra +145 %, HYFM 3-ago-2026 +140 %). Bajo el límite del principal solo vuelven 20 de 29. Total muestra: 249 de 251 bajan del +87 % el mismo día; NO todos. Sesgo conservador del estudio: supone el corto ya abierto justo antes del fogonazo; el 22 % de los fogonazos (56) arrancan antes de las 04:15 (TNON a las 04:10, con 4 min de datos). CORREGIDO el 21-sep: 1B sí entra a las 04:03-04:05 cuando ya hay volumen; lo que descarta TNON/GRYP/HYFM es la falta de volumen previo, no la hora. GRYP y HYFM (los 2 que no vuelven): no son fogonazos dentro de un gap ya hecho, son el ARRANQUE del movimiento del día. GRYP 12-may-2025: cierre anterior 0,49, a las 06:30 cotiza 0,55 (+16 %) con 177 k$ negociados en 2,5 h; salta a 4,91 y se queda entre 1,4 y 2,9 todo el día; cierre 1,40 (+147 % sobre la entrada supuesta = 14,7 % de la cuenta con el 10 %). HYFM 3-ago-2026: cierre anterior 0,55, DOS velas de PM con 22 k$ negociados antes del salto a 4,12; cierre 16:00 2,04 (+172 %, 17,2 % de la cuenta). Ninguna estrategia entra ahí (gap < 20 %, < 1 $, sin volumen): igual que TNON, no cuentan como exposición real. El corto real de esas dos sería el fade posterior (GRYP 2,5 → 1,4; HYFM 3,1 → 2,0), ganador. Criba de arranques (21-sep, informe v11 sección «Quitando los fogonazos de arranque»): exigiendo ANTES del fogonazo gap ≥ 20 %, ≥ 100 k$ negociados y ≥ 15 min de PM quedan 122 de 251 (129 son arranques: 113 sin volumen previo, 56 antes de las 04:15; TNON, ENSC y MODD fuera). Sobre los 122: subida 99 % (10 k) → 93 % (500 k); pérdida sobre la cuenta media 2,3-3,0 %, mediana 1,2 %, p90 6,0-6,5 %, máx 8,3-8,4 % (DGLY, MNTS); la emergencia interviene en el 37 % (51 % en la general). El máximo NO baja. Criba aproximada (gap/volumen/hora), no las condiciones exactas de cada estrategia. **Exposición REAL de 1B (21-sep, cruce_1b_flash.csv, corrida 1B ene-2025→ago-2026):** de los fogonazos de la muestra en ese periodo, 1B estaba DENTRO en 7 (PLYX, SLGB, GLE, AEHL, NIVF, LGHL, GVH) y entró DESPUÉS del fogonazo, en el fade, en 57 (media +5,2 %, 64 % ganadores). CIIT NO la operó. OJO: 4 de los 7 son entradas de 1B a las 04:03-04:05 con fogonazo a las 04:08-04:23 (AEHL, NIVF, GVH, LGHL): 1B SÍ entra en los primeros minutos del PM, así que la criba «antes de las 04:15 no hay señal» NO vale para 1B; lo que distingue es el volumen previo (esas cuatro ya llevaban 140-480 k$ negociados en 3-5 min). Protocolo sobre esos 7 con 10 k: todos salen en la subida; 6 por el principal al 9-12 % del trade (≈ 1 % de la cuenta); LGHL por la emergencia al 65 % (6,5 % de la cuenta; con 100 k sale en la bajada, 5,5 %). **Jaume lo preguntará en el futuro: esta tabla es la referencia para fijar la exposición por posición.** También en el informe de fogonazos v11.

**Conclusión corregida:** que se salga «en la subida» depende de si el ask CAMINA unas décimas o segundos antes de saltar. Cuando camina (AEMD, SLGB), el principal o la emergencia cogen la salida en los primeros segundos y la pérdida queda en el 8-35 % del trade con posición pequeña; cuando salta en seco (PLYX, libro vacío), solo queda la emergencia en la bajada (75 %). La resolución de la simulación y la latencia real de DAS (100-300 ms) marcan la diferencia: en sombra hay que medir esa latencia. En todos los casos y tamaños se sale dentro del +50 %.

**Aclaración (Jaume, 20-sep):** «pillar el stop en la subida» solo pasa cuando el precio CAMINA (la mayoría de los stops normales: principal llena al instante 91-95 %); en AEMD y PLYX el ask saltó los dos triggers en el mismo segundo y solo actúa la emergencia, en la bajada.

**Entrada que cae en el arranque de un cisne negro (Jaume, 20-sep): SIN guardas nuevas.** (1) Si el fill de entrada llega y el ask salta antes de que DAS acepte los stops: R-C-03 (reintentos, aviso) y, con el trigger ya por debajo del precio, protocolo R-G-01. (2) Si la escalera está agregando y el precio sube, la venta pendiente se ejecuta en mitad de la subida: se ACEPTA sin guarda (nada de «cancelar la escalera si el ask sube X % en Y s»: complejiza y puede ser peligroso). Razón con datos: se entra a mejor precio que la señal, y los fogonazos devuelven el 83-98 % del salto en 10-30 s; al cabo de un rato se pierde menos o incluso se gana. Los stops y el protocolo hacen su trabajo.

### R-G-02 · Aviso de halt (PM y RTH)
- Situación: una acción con posición abierta (o con orden de entrada viva) entra en halt, en premercado o en sesión.
- Acción: mensaje por Telegram en el momento (nivel Aviso), breve: ticker, tipo de halt si se conoce (LULD / T1 / T12), hora, precio de parada, posición y stop, k (halts del día) y bandas LULD si es en sesión. Al reabrir, segundo mensaje con precio de reapertura y qué hizo el bot (R-F-01). Sin ciclo de 5 minutos.
- Estado: FIJADA (Jaume, 20-sep). Origen: F, petición del 20-sep.

**G3, G4, G6 y G7 (20-sep): sin decisión automática del bot.** El tope de pérdida por posición, la salida por tiempo, el cierre por tramos y la relación con la pérdida del día son decisiones del HUMANO dentro del protocolo R-G-01, con los datos del informe. G2 (fogonazo vs squeeze) queda como INFORMACIÓN del informe (minutos desde el máximo, si lleva bajando), no como disparador.

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
- **Cómo se sale «al reabrir» (Jaume, 22-sep, de su socio):** la orden de salida a MERCADO se envía DURANTE el halt, no al reabrir: así entra en el cruce de reapertura y no se pierden milisegundos. Momento (regla, Jaume 22-sep): si el halt tiene más de un minuto de espera, la orden se manda UN MINUTO ANTES del fin previsto; si el halt es de menos de un minuto (o la reapertura no tiene hora), en cuanto se decida salir / al abrir. Jaume confirma que DAS acepta órdenes durante el halt; hay que PROBAR qué devuelve el API (log) en demo. Aplica a todos los casos del libro en que la decisión es «fuera al reabrir» (k = 3, k = 2 a 3-5 % de la banda, T1 > 250 %). [API R-23: si DAS acepta órdenes durante el halt y las manda al cruce de reapertura.] **KB de DAS (23-sep): una orden a mercado nueva durante el halt «will be sent to the configured route and handled by the route»; NO garantiza el cruce de reapertura. Probar en demo ruta por ruta antes de fijar el minuto antes.**
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

### R-B-01 · Orden de entrada en corto (y piramidaciones): un minuto AGREGANDO en el punto medio y, si no, cruzar al bid con tope del 3 %
- Situación: la estrategia da señal de entrada (o de pirámide) y el bot envía la orden. Vale para PM y RTH.
- Detección: bid y ask de DAS en el instante de la señal (t0); bid de la señal = referencia del tope.
- Acción (**FIJADA por Jaume el 22-sep, sustituye a las dos ramas anteriores: rama rápida al bid + escalera**):
  1. **Agregar.** Venta límite en el PUNTO MEDIO entre bid y ask (bid + 1 tick si el spread es de 2 ticks o menos), que descansa en el libro AGREGANDO liquidez, hasta 60 s (= la caducidad de la señal, R-B-04). Se cancela antes si la estrategia deja de decir «dentro».
  2. **Cruzar con tope.** Si a los 60 s no ha llenado (entera o en parte), lo que quede se CRUZA al bid (venta límite a bid × (1 − 0,5 %), removiendo) SOLO si el bid no ha caído más del 3 % respecto al bid de la señal.
  3. **No entrar.** Si el bid ha caído más del 3 %, se cancela y NO se entra: la señal se ha ido sin nosotros y no se persigue.
  Lo ejecutado agregando se descuenta; la orden de cruce lleva solo el resto (control de posición neta, R-C-11). Con SSR la venta ya tiene que ir por encima del bid: mismo camino.
- Medido (22-sep, `42_` y `43_agregar_vs_remover_entrada.py`, 349 entradas reales de 1B/2B con libro NBBO): llena agregando el 71 %; pierde el 11 % de las señales; valor esperado por señal +1,45 % frente a cruzar al instante (contando las perdidas al 4,2 % del trade medio de 1B). Alternativas medidas: 20 s +0,95 %; tope 2 % +1,38 % (pierde el 15 %); al ask en vez del punto medio, peor; «siempre agregar sin cruzar», negativo (pierde el 14 %, y son las mejores señales: bid −5 a −8 % al minuto). Cautelas: llenado supuesto en el primer print a nuestro precio o mejor (optimista), sin re-pegar la orden si el libro se mueve.
- Principio (Jaume, 22-sep): **se AGREGA siempre** (entradas, pirámides, take profits, salidas con hora conocida donde se pueda), **excepto los stops y las situaciones delicadas** (cerrar todo, TP a medias con rebote, prioridad TP-entrada, halts, cisne negro), que remueven.
- Quién la ejecuta: ejecutor (guarda: distancia bid de la señal → bid actual).
- Parámetros (cuadro de mandos): espera agregando = 60 s; nivel = punto medio (bid + 1 tick con spread ≤ 2 ticks); tope de slippage al cruzar = 3 %; techo del cruce = 0,5 %. Ruta al agregar: EDGA de 07:00 en adelante (paga −0,0027 $/acción), ARCA de 04:00 a 07:00 (−0,002); al cruzar, ARCA en PM y SAGEPRO en RTH si en sombra llena igual de rápido.
- Si la acción falla: sin cotización (libro vacío) → no se entra. El cruce no llena porque el bid se movió durante el envío → se reintenta una vez con el bid nuevo si sigue dentro del 3 %; si no, no se entra.
- Prueba: sombra, midiendo % que llena agregando, precio medio frente al bid de la señal, % de señales perdidas y su valor; afinar los 60 s y el 3 % con fills reales.
- Estado: FIJADA (Jaume, 22-sep). Historia: 16-sep rama rápida al bid + escalera −1/−2/−3 %; 22-sep mañana «agregar 2 s y cruzar»; 22-sep tarde esta versión, con datos.
- Origen: B1, B2, B19; pregunta de Jaume del 22-sep tras lo del socio («siempre agrega»).

**Qué es agregar, exactamente (duda de Jaume, 22-sep):** agregar no es un precio concreto, es que la orden NO se ejecute al llegar y se quede en el libro. Una venta se ejecuta al llegar si su precio es ≤ el mejor bid (es «marketable»: remueve). Cualquier venta con precio > mejor bid se queda esperando: agrega. Por tanto, para vender agregando vale el punto medio, el ask o ask + 0,01; bid − 0,01 NO agrega (cruza el bid y remueve). El punto medio tiene ventaja: mejora el mercado (pasa a ser el nuevo mejor ask), va el primero en la cola y es lo primero que un comprador se lleva; ask + 0,01 queda detrás de todo el ask y llena mucho menos. Restricción: en acciones de 1 $ o más el precio va en céntimos (regla 612), así que el punto medio se redondea al céntimo; con spread de 1 céntimo no hay punto medio y la orden se pone AL ASK (se une al ask, sigue agregando). Por debajo de 1 $ se admiten 0,0001 $. El rebate (ARCA −0,002, EDGA −0,0027) se cobra en cualquier orden que descanse y se ejecute pasivamente, esté donde esté. Con SSR la venta tiene que ir por encima del bid: el punto medio cumple.

**¿DAS «entiende» agregar? (Jaume, 22-sep):** DAS no decide si una orden agrega o remueve; envía la orden límite con su precio a la ruta (ARCA/EDGA) y es la BOLSA la que, al recibirla, la ejecuta si es marketable (remueve) o la deja descansar (agrega). No hay margen mínimo que dar: basta con que el precio esté por encima del mejor bid al llegar. El riesgo real es de TIEMPO: si entre nuestra foto del libro y la llegada de la orden (≈ 100-300 ms) el bid sube hasta nuestro precio, la orden se vuelve marketable y remueve. Dos remedios: (1) las bolsas tienen órdenes «post only» / «add liquidity only» (ARCA ALO) que se rechazan o recolocan en vez de remover: PREGUNTA al bróker si el API de DAS las expone [R-20]. (2) El manual 2021 SÍ tiene la orden **PEG MID** (`NEWORDER token SS símbolo ruta acciones PEG MID [precio límite]`): una orden pegada al punto medio que la propia bolsa recoloca cuando el libro se mueve, con precio límite opcional. Es exactamente «agregar en el punto medio» y además re-pega sola (lo que la simulación no hacía). Pendiente [R-21]: qué rutas la admiten, si en premercado, y qué tarifa lleva (en algunas bolsas las pegged al punto medio cobran un rebate menor o incluso comisión, distinto de una límite normal). Si PEG MID paga rebate y funciona en PM, es la orden de R-B-01; si no, límite normal en el punto medio con re-pegado por el bot cada segundo.

**Hotkeys del socio (22-sep, captura de Jaume):** `ROUTE=SAGEPROL;Price=Ask;Share=N;TIF=DAY;SELL=Send` para entrar en corto (venta límite AL ASK = agrega, se une al ask) y `ROUTE=SAGEPROL;Price=Bid-0.05;...` «Kill» para entrar rápido (venta límite 5 céntimos POR DEBAJO del bid = cruza y remueve con colchón fijo de 5 c). Es la misma idea que R-B-01: agregar por defecto y cruzar con colchón cuando urge; diferencias: él agrega al ask (nosotros en el punto medio, que llena más según los datos) y su colchón es fijo (0,05 $) en vez del 0,5 % del bid. Ruta SAGEPROL = la ruta límite de Sage (SAGEPRO), la gratis en RTH. TIF=DAY: en PM haría falta DAY+ (o la ruta lo maneja) [confirmar con el bróker]. LimitP en DAS Pro es el TIPO de stop (StopLimitP, disparo por último precio); para las entradas lo que cuenta es la expresión del precio límite (Ask, Bid-0.05, punto medio…), no el tipo.

### R-B-07 · DAS rechaza una orden: catálogo de motivos, reintentos, pausa por ticker y botón «reanudar» (FIJADA en su forma, Jaume 23-sep)
- Situación: DAS o el bróker devuelven un rechazo (%OrderAct Send_Rej con su campo «notes») o no responden (B5).
- Detección: el texto literal del motivo se compara con el CATÁLOGO de motivos. El catálogo no nace vacío: (1) la tabla C del informe de la KB (≈ 30 mensajes y controles: BP, not shortable, SSR, MaxLoss, Position Unreal Loss, Max Ord Cap, Symbols/Route Control, PDT, horario, halt…); (2) los «notes» del manual del API cuando llegue; (3) en DEMO se PROVOCAN a propósito los rechazos previsibles (sin BP, sin locate, locate consumido, SSR al bid, precio fuera de rango, ruta cerrada, símbolo en halt, orden duplicada) para capturar el texto exacto de cada uno; (4) en sombra y canario, cada texto nuevo se clasifica y se añade antes de seguir. Principio: «desconocido» = no está en el catálogo, pero el catálogo se llena ANTES del dinero real, no a golpes.
- Caso concreto de Jaume: locates de un solo uso ya consumidos → no es un error desconocido, es un estado que el bot debe llevar él mismo (locates comprados − usados por ticker); si intenta entrar sin locate disponible, la acción es RECOMPRAR con su EV (R-H-01/R-H-05), no avisar al humano.
- Acción: (1) **Aviso a Telegram SIEMPRE con el texto literal de DAS** (el campo «notes»), la orden que se intentó y el estado del ticker; que se pueda leer lo que dice DAS sin abrir el montage [API: confirmar que el texto llega por el API igual que en el montage]. (2) **Motivo conocido**: hasta 2 reintentos con el tratamiento del catálogo (recalcular BP, recomprar locate, subir un tick sobre el bid con SSR…); si tras 2 sigue rechazando, se trata como el punto 3. (3) **Motivo desconocido o conocido persistente**: si la posición de ese ticker está CUBIERTA (entrada con sus stops principal y emergencia vivos) → aviso nivel 2 y el ticker pasa a PAUSADO: no se envía ninguna orden nueva en ese ticker (entradas, pirámides, reposiciones no urgentes) hasta que el humano lo reanude; los stops y las salidas de protección siguen; el resto de tickers funciona normal. Si la posición NO está cubierta (sin stop aceptado) → R-C-03 y aviso nivel 3, CONTROL HUMANO: el bot NO intenta cerrar al ask por su cuenta (Jaume, 23-sep: podría ser justo un cisne negro en el que no hay que cerrar al ask). Qué hace el bot mientras el humano decide: escenario pendiente EP-1 (sección 5). (4) Cada rechazo, conocido o no, al diario con texto literal, orden, hora y tratamiento aplicado.
- **Cuadro de mandos y Telegram**: panel «Tickers pausados» con el motivo literal y la hora; botón **«Reanudar ticker»** (y comando `/reanudar TICKER`) que quita la pausa y pone a cero el contador, para cuando el humano ha arreglado el problema a mano en DAS; botón «Reanudar todo». Arreglarlo a mano en el DAS del VPS (por escritorio remoto) no tira la sesión del bot porque es la misma instancia; desde otro ordenador sí.
- Pedir a Sage: «Always allow unwind positions» en la cuenta del bot y la lista de controles activos (Account Risk Params).
- Parámetros: reintentos con motivo conocido = 2; la pausa es por ticker y solo la quita el humano.
- Prueba: en demo, provocar cada rechazo del catálogo y comprobar texto recibido, tratamiento, pausa y reanudación.
- Estado: FIJADA en su forma (Jaume, 23-sep); el catálogo se rellena en demo. Origen: pregunta de Jaume del 23-sep; tabla C del informe de la KB.

### R-B-02 · Entrada ejecutada a medias
- Situación: la orden de entrada se ejecuta solo en parte (p. ej. 400 de 1.000) porque en el bid no había más. Frecuente: en PM una orden de 300 $ cabe entera el 53 % de las veces; de 3.000 $, el 6 %.
- Detección: fill parcial confirmado por DAS.
- Acción: el resto (600) sigue con la misma lógica de R-B-01 (al nuevo bid si está a menos del 3 % del último precio; si no, escalera), como máximo hasta completar el minuto desde la señal y sin pasar nunca del 3 %. Al minuto, se acepta la posición que haya (400) con su stop proporcional (R-C-01) y se cancela lo pendiente. No hay mínimo por debajo del cual no compense quedarse: se entra siempre que se pueda y con lo que se pueda.
- Quién la ejecuta: ejecutor.
- Parámetros: los de R-B-01 (60 s agregando en el punto medio, tope 3 %).
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
- Parámetros: los de R-B-01 (60 s agregando en el punto medio, tope 3 %).
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

**H6 · Paquetes de 100 y excedente (FIJADA, Jaume 21-sep):** se tira POR LO BAJO. Del último paquete de 100 solo se compra si se van a usar MÁS del 30 % de sus acciones: si la posición pide 1.230, el paquete 13 se usaría al 30 % → NO se compra, se «sacrifican» esas 30 y la posición se ajusta a 1.200; si pide 1.240 (40 %) → SÍ se compran las 100 y sobran 60. El coste de TODOS los locates, incluido el último paquete a medio usar, entra en el cálculo del EV que decide si se entra. Parámetro: umbral de uso del último paquete = 30 % (cuadro de mandos).
**Recompra (FIJADA, Jaume 21-sep):** si el bróker solo tiene parte de lo pedido (p. ej. 2 paquetes de 100 y hacen falta 300), se busca el resto INMEDIATAMENTE una segunda vez con el mismo tope de EV; si tampoco se cubre, se entra con lo localizado (R-H-04).

### R-H-05 · Cuántos locates comprar cuando varias estrategias pueden entrar (PROPUESTA, 22-sep, a decidir por Jaume)
- Situación: al entrar una acción en el radar se compran locates pronto y barato (R-H-01), pero no se sabe cuántas estrategias van a dar señal ese día (a veces ninguna, a veces tres) ni, por tanto, cuántas acciones harán falta.
- Opciones estudiadas: (A) **Máximo teórico**: comprar en el radar la suma de los tamaños de todas las estrategias activas sobre ese ticker. Nunca falta locate y es lo más barato por acción, pero se paga mucho locate que caduca sin usarse (una estrategia que entra el 47 % de los días desperdicia el resto). (B) **Base + ampliación**: comprar en el radar solo la BASE (el tamaño de la estrategia más probable o el común a todas) y AMPLIAR cuando otra estrategia esté a punto de entrar (prealerta del segundo 44-59 de la vela, que ya existe), con el precio del locate de ese momento y su propio EV. (C) **Solo en la señal**: no comprar nada hasta que haya señal. Cero desperdicio, pero el locate más caro y la entrada más lenta.
- Recomendación: **(B)**. El EV se calcula POR ESTRATEGIA sobre SUS acciones: la base carga con el coste de sus locates; cada ampliación se decide con el precio de locate del momento contra el EV de la estrategia que la pide; si esa ampliación no tiene EV positivo, esa estrategia no entra y las demás siguen. Los paquetes de 100 se rellenan por lo bajo con la regla del 30 % (H6) sobre la suma de lo que se va a usar. Los locates no usados son coste hundido: cuentan en el tope diario del 3 % y se registran en el diario como «locates caducados» para medirlos.
- Lo que decide entre A y B, y se mide en SOMBRA: (1) la tasa de conversión radar → señal por estrategia (qué % de las acciones en radar acaban dando señal) y (2) cuánto sube el precio del locate entre la entrada en el radar y el momento de la señal (P4). Si el locate apenas sube y la conversión es baja, gana B con base pequeña; si el locate se encarece mucho a lo largo de la mañana, gana A.
- **FIJADA (Jaume, 22-sep): compra ESCALONADA por la condición de radar de cada estrategia.** En cuanto una acción cumple la condición previa (de radar) de una estrategia, se compran los locates de ESA estrategia: entrada + todas sus piramidaciones «add» (con el riesgo de cada nivel del cuadro), a su EV. Si la acción sigue subiendo y cumple la condición previa de otra estrategia, se buscan y compran los de esa otra, con su propio EV. Caso real: la estrategia A (gap PM > 50 %, dos pirámides) va siempre; la B (gap PM > 150 %, sin pirámide) implica la A, así que A se compra a los 50 % y B se añade al cruzar el 150 %. Las pirámides se localizan CON la entrada porque ocurren más tarde, con el locate más caro. Los paquetes de 100 por lo bajo (30 %) sobre la suma de cada compra. Lo de medir en sombra (conversión y deriva del precio) sigue valiendo para afinar.
- Estado: FIJADA (Jaume, 22-sep). Origen: pregunta de Jaume del 22-sep.

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

### R-J-01 · Caída del feed de Massive: prealerta a 30 s, emergencia a 60 s
- Situación: en horario de mercado dejan de llegar ticks y velas de Massive.
- Detección: latido del feed.
- Acción: a los 30 s sin datos, PREALERTA; a los 60 s, ALERTA DE EMERGENCIA y modo degradado de R-D-05 (no abrir, mantener con stops, vigilante con precio de DAS). Se sigue monitorizando: si vuelve el feed, aviso de recuperación y se reanuda.
- Quién la ejecuta: supervisor + vigilante.
- Parámetros: 30 s / 60 s.
- Si la acción falla: —
- Prueba: simulacro cortando el feed.
- Estado: FIJADA (Jaume, 18-sep).
- Origen: J2, A3.

### R-J-02 · Caída de la conexión con DAS o de la aplicación DAS
- Situación: el socket con DAS se cae, o la aplicación DAS se cierra o pierde la sesión.
- Detección: latido del socket / proceso de DAS.
- Acción: (1) AVISO MÁXIMO a la primera. (2) Reconexión automática constante: reintento a los 2 s, 4, 8, 16 y después cada 30 s sin parar (relanzar DAS y reloguear si es la aplicación [API: 2FA]). (3) Mientras siga caída, aviso máximo cada 5 minutos. (4) En el cuadro de mandos, botón para deshabilitar el bot (apagarlo) si el humano decide tomar el control. (5) Al reconectar: aviso de recuperación y reconciliación completa (R-C-10) ANTES de enviar nada. Mientras tanto, lo único que protege son los stops residentes en el servidor de DAS.
- Quién la ejecuta: supervisor.
- Parámetros: cadencia 2/4/8/16/30 s; aviso cada 5 min.
- Si la acción falla: —
- Prueba: simulacro matando DAS y cortando el socket en demo/sombra.
- Estado: FIJADA (Jaume, 18-sep).
- Origen: J3, J4, J15.

### R-J-04 · El bot se cae, se cuelga o se duplica
- Situación: (a) el ejecutor o el vigilante muere por excepción; (b) sigue vivo pero sin latido (colgado); (c) se arranca una segunda instancia.
- Detección: supervisor (proceso) y latido cruzado ejecutor↔vigilante; cerrojo de instancia única.
- Acción (tiempos v2, Jaume 22-sep: «30 s es mucho»): (a) muerto → el supervisor recibe la salida del proceso AL INSTANTE y lo relanza en 1 s; si vuelve a morir seguido, espera 2, 5 y 10 s entre intentos (para no entrar en bucle) y sigue cada 10 s sin límite; lo que tarde en volver a operar es el propio arranque (cargar, conectar a DAS, reconciliar: a MEDIR, objetivo < 10 s); AVISO desde el primer momento (log + Telegram, como todo) y aviso al recuperarse; al volver, reconciliación (R-C-10) antes de nada. (b) colgado → latido cada 1 s; a los 3 s sin latido se mata y se relanza (antes 10 s); reintento igual que (a), avisando de lo que pasa. (c) CERROJO DE INSTANCIA ÚNICA obligatorio en los DOS procesos: al arrancar, si ya hay otra instancia viva, la nueva NO arranca y avisa; el humano conserva el control manual del primero para apagarlo cuando quiera.
- Quién la ejecuta: supervisor.
- Parámetros: relanzar 1 s (luego 2/5/10 s si encadena caídas); colgado 3 s sin latido (latido 1 s). Antes: 30 s / 10 s.
- Si la acción falla: si ejecutor y vigilante mueren a la vez → R-J-05.
- Prueba: matar cada proceso, colgarlo (bloqueo artificial) y lanzar dos veces, en sombra.
- Estado: FIJADA (Jaume, 18-sep).
- Origen: J7, J8, J9.

### R-J-05 · Vigilante externo (latido) y SAI
- Situación: se apaga la máquina entera (luz, VPS caído): nadie dentro puede avisar.
- Detección: el vigilante manda un «ping» silencioso cada 60 s a un servicio externo de vigilancia; el servicio da la ALARMA (Telegram + el panel de avisos del cuadro de mandos, que son los mismos logs) cuando faltan 3 pings seguidos (3 min) en horario de mercado. Nada se dice mientras todo va bien.
- Acción: alarma → control humano (los stops residentes protegen mientras tanto).
- Quién la ejecuta: servicio externo + humano.
- Parámetros: latido 60 s; alarma a los 3 fallos.
- SAI (fase PC): Jaume se compra un SAI; el PC Y EL ROUTER enchufados a él. Protección real: los stops residentes. **PENDIENTE: comprar el SAI** (line-interactive 700-1000 VA con USB: APC Back-UPS BX, Eaton 3S o CyberPower, ≈ 100-150 €).
- Estado: FIJADA (Jaume, 18-sep).
- Origen: J17, J1.

### R-J-06 · VPS: uno, Windows, DAS dentro; actualizaciones solo con todo apagado
- Situación: producción en el VPS (M12). De momento UN solo VPS y una sola infraestructura (la de Jaume). Futuro apuntado: el socio podría tener su propio bot con la misma arquitectura, duplicando el VPS o corriendo dos juegos de procesos en uno; no se aborda ahora.
- Acción: (1) el socio puede actuar en emergencias sin Jaume: apagar el bot (botón / Telegram) y reiniciar el VPS desde el panel del proveedor. (2) Actualizaciones de Windows SOLO con todo apagado (VPS, bot, DAS); nunca con el bot o DAS encendidos; reinicios automáticos desactivados. (3) Al reiniciar el VPS: arranque automático en orden DAS → vigilante → ejecutor, y reconciliación completa (R-C-10) antes de enviar nada. (4) Fase PC: router lejos del PC → segundo SAI pequeño para el router o hotspot del móvil como conexión de respaldo con menor prioridad en Windows.
- Estado: FIJADA (Jaume, 18-sep). Origen: J10, J20, J1.

**VPS o PC: qué hace falta para que el bot funcione (Jaume, 22-sep):** el bot son dos procesos (ejecutor + vigilante) que hablan con DAS por un socket LOCAL: tienen que correr en la MISMA máquina que DAS. El cuadro de mandos (app del backtester) puede estar en otra máquina: el bot lee un fichero, no la app. Como DAS admite un login por cuenta, solo puede haber UNA máquina operando a la vez: si todo está montado en el PC de casa y Jaume quiere operar desde el portátil, habría que instalar DAS + bot en el portátil y apagar el de casa (posible, no cómodo). Con VPS, el portátil solo se conecta por escritorio remoto para mirar; el bot sigue en el VPS. Exposición a ataques: el riesgo real de un VPS es el escritorio remoto abierto a internet; se cubre con contraseña larga, doble factor, RDP solo desde tus IPs o por VPN, sin ningún otro servicio expuesto y actualizaciones con todo apagado (R-J-06); el PC de casa tiene sus propios riesgos (luz, fibra, alguien tocando). Recomendación: sombra y demo en el PC con SAI; VPS endurecido antes del canario.

### R-J-07 · Reloj, disco y actualización de DAS
- Reloj: todo en hora de Nueva York; al arrancar se comprueba la sincronización; si el reloj se desvía más de 2 s, el bot se NIEGA a operar y avisa; por debajo, solo aviso si pasa de 0,5 s. Jaume (22-sep): sin hiperestrictez, los umbrales se validan en vivo. (J12)
- Disco: rotación diaria de logs y diario; aviso si quedan menos de 5 GB libres. (J13)
- Actualización forzada de DAS: tarea HUMANA. El supervisor detecta que DAS no arranca o pide actualizar, AVISA, y lo actualiza una persona; nunca automático. (J14)
- Estado: FIJADA (Jaume, 18-sep).

**J18 (Jaume, 18-sep): latencia: PENDIENTE para el repaso final** (nunca ha operado con el API de DAS; sin referencia para fijar un umbral). Lo importante es la información que devuelvan DAS y el bróker cuando una orden no entra, cuando no deja por margen, etc.: lista de códigos y respuestas [API, apartado R punto 14]. El bot mide y registra la latencia orden→confirmación desde el primer día.

### R-J-08 · Telegram caído
- Situación: Telegram no responde o rechaza los envíos.
- Acción: el bot sigue operando con normalidad; los avisos quedan siempre en el log y en el panel de avisos del cuadro de mandos; los envíos a Telegram se encolan y se reintentan. Canal de EMERGENCIA alternativo por decidir: propuesta, correo electrónico (gratuito, sin depender de Telegram) para los avisos de nivel máximo, y como segundo escalón un SMS o una llamada automática (servicios de pago por uso, unos céntimos por mensaje) solo para el nivel máximo.
- Estado: FIJADA en su lógica (Jaume, 18-sep); canal alternativo por decidir en el área M (M4).
- Origen: J19.

### R-J-03 · Tabla del modo degradado
| Qué falla | Abrir nuevas | Gestionar abiertas | Stops | Aviso |
|---|---|---|---|---|
| Nada | sí | sí | residentes en DAS | normal |
| Feed de Massive | no | sí, con precio de DAS | residentes | prealerta 30 s, emergencia 60 s (R-J-01) |
| Conexión con DAS | no | no: solo actúan los stops ya puestos en el servidor de DAS | residentes | máximo a la primera + cada 5 min, reconexión constante (R-J-02) |
| El ejecutor (bot) | no | el vigilante | residentes | emergencia + relanzar |
| El vigilante | sí, con aviso | el ejecutor | residentes | aviso + relanzar |
| Telegram | sí | sí | residentes | por canal alternativo (M4) |
- Estado: FIJADA (Jaume, 18-sep). Origen: J16.

### Área K · Estado y reconciliación

### R-K-01 · Reconciliación con DAS: por eventos al instante y barrido completo cada 2 s
- Situación: marcha normal del bot.
- Detección: (1) DAS empuja los cambios (fills, cancelaciones, posiciones) al instante: el estado del bot se actualiza con cada evento sin esperar. (2) Además, BARRIDO completo (posiciones, órdenes vivas, cuenta) cada 2 s mientras haya posiciones u órdenes vivas en horario de mercado, cada 10 s si no hay nada abierto, y SIEMPRE tras cada fill, cada cancelación y cada reconexión. El vigilante ya comprueba los stops cada segundo (R-C-04).
- Acción: cualquier diferencia entre el diario y DAS → R-C-10 (casos 1-4).
- Quién la ejecuta: reconciliación.
- Parámetros: 2 s / 10 s (cuadro de mandos). **Matiz (21-sep):** el barrido NO es el mecanismo que evita quedarse largo (eso lo hace el evento de fill de DAS en decenas de ms, R-C-11); es la foto de control. Cadencia ADAPTATIVA: 1 s durante los 60 s siguientes a cualquier fill o disparo de stop y mientras haya una entrada en escalera; 2 s con posiciones abiertas en calma; 10 s sin nada abierto. Carga: un barrido son 2-3 peticiones; a 2 s son ~1,5 peticiones/s, muy por debajo del límite que recuerda Jaume (~500 peticiones cada 5 s; 5.000 órdenes/día) [API: confirmar cuotas].
- Si la acción falla: R-K-03.
- Prueba: sombra; medir latencia del barrido y que no compita con el envío de órdenes.
- Estado: FIJADA (Jaume, 19-sep). Nota: cada segundo también cabría en cuota; se elige 2 s porque el instante lo dan los eventos y el barrido es solo la red de seguridad; si en sombra se ve que el barrido no molesta, se puede bajar a 1 s.
- Origen: K1.

### R-K-02 · La cuenta es del bot; el humano solo interviene en emergencias
- Situación: Jaume NO opera a mano en la cuenta del bot. Solo puede cerrar o netear posiciones en una emergencia (y a malas, apagar antes el bot y tomar el mando).
- Acción: el bot trata toda posición u orden que no esté en su diario como intervención humana de emergencia: aviso, stop de protección (R-C-10 caso 4) y no la deshace. Pendiente el traspaso humano↔bot (marcar «esto lo he hecho yo») ya apuntado.
- Estado: FIJADA (Jaume, 19-sep). Origen: K5, D11.

### R-K-03 · La reconciliación falla con el socket vivo
- Situación: DAS no contesta a la consulta de posiciones/órdenes/cuenta pero la conexión sigue viva.
- Acción: se sigue operando con el último estado bueno durante 30 s; pasados, se pasa a «no abrir nuevas» (las abiertas se gestionan con los stops residentes y los eventos que sí lleguen) y AVISO (importante). Al volver la reconciliación, barrido completo y aviso de recuperación.
- Parámetros: 30 s.
- Estado: FIJADA (Jaume, 19-sep). Origen: K11.

### R-I-04 · «Modo trading de seguridad» (PENDIENTE de diseñar)
- Idea de Jaume (19-sep): un interruptor en el cuadro de mandos que, activado a voluntad (viaje, no poder estar pendiente), BLOQUEA la entrada en cualquier acción que cumpla condiciones de riesgo: float < X, market cap < Y, precio nominal < Z, y otras condiciones que se definan. Las posiciones abiertas se gestionan igual; solo se restringen las entradas.
- Pendiente: lista de condiciones y valores, y si el modo también reduce el tamaño. Datos ya medidos (otra sesión, 19-sep): NO hay float ni market cap «seguros» (fogonazos y operaciones de 1A son la misma población; cap ≥ 20 M conserva solo el 18 % del retorno de 1A). Lo que sí separa: **precio ≥ 3 $** (quita 22 de 32 monstruos ≥ ×2,5 y conserva el 76 % del retorno de 1A; ≥ 5 $: 26 de 32, 56 %) y la liquidez previa (dólares acumulados > 1 M quita el 81 %), con acciones en circulación ≥ 2-3 M como red (caso VLCN). Propuesta de «modo vacaciones» de esa sesión, sin implementar: tamaño ½, liquidez, ≥ 2-3 M acciones, SIC 6770 e IPO fuera, banda clavada → salir. **Valores de Jaume (19-sep) SOLO para este modo, activado por él desde el cuadro de mandos: precio > 5 $ y dollar volume acumulado > 2 M $.** Massive da market_cap y acciones en circulación a la fecha por REST.
- **Diseño (21-sep, Jaume): es un FILTRO, no un tamaño reducido: si la señal no cumple los criterios, NO se entra.** SIN suelo permanente en el bot (Jaume, 21-sep): el mínimo de dollar volume lo dicta CADA ESTRATEGIA en sus condiciones (normalmente siempre lleva uno); el dato de apoyo: 8 de los 9 fogonazos que salieron en la bajada tenían < 3.000 $ negociados antes. Lo que sí existe es el MODO DE SEGURIDAD, interruptor del cuadro para cuando Jaume no pueda estar pendiente: precio ≥ 5 $ y Acum. Dollar Volume ≥ 2 M$ (los que Jaume apuntó el 19-sep; datos: precio ≥ 5 $ quita 26 de 32 monstruos y conserva el 56 % del retorno de 1A; > 1 M$ acumulado quita el 81 %). Las posiciones abiertas se gestionan igual en los dos casos. Valores FIJADOS por Jaume (21-sep): precio ≥ 5 $ y Acum. Dollar Volume ≥ 2 M$.
- Estado: FIJADA (Jaume, 21-sep). Origen: idea del 19-sep; enlaza con A11 (lista negra) y M9.

### Área A · Señal y datos

### R-A-01 · Señal que llega tarde: no se entra
- Situación: por retraso del bot o del feed, el último precio se ha alejado del precio con el que se generó la señal más de X %.
- Acción: NO se entra (además del tope del 3 % de R-B-01). No debería pasar: la captura de la señal es instantánea (R-B-04). Se registra el retraso para medirlo en sombra.
- Parámetros: X (cuadro de mandos; provisional 1 %).
- Estado: FIJADA (Jaume, 19-sep). Origen: A2.

### R-A-02 · Prints tardíos y de dark pool en las señales
- Situación: la cinta de Massive incluye prints de dark pool y tardíos: son ejecuciones REALES pero hechas fuera del libro y publicadas con retraso; su precio NO es accesible para nosotros. Pueden alterar el máximo, mínimo o cierre de una vela y con ello una señal o un nivel de estructura. En el estudio, el 93 % de los «fogonazos» de la cinta eran de este tipo.
- Detección: el feed de operaciones de Massive trae las dos horas (ejecución y publicación): filtrar es comparar dos números por tick, coste cero de rapidez. La cinta de DAS marca con la bandera de condición si un print vale para el último precio.
- Acción (Jaume, 19-sep): Massive no «miente»: publica TODOS los prints, también los hechos fuera del libro y publicados tarde. (1) El bot construye sus velas en vivo con el feed de operaciones DESCARTANDO los prints con más de 10-20 ms entre ejecución y publicación (el mismo filtro del estudio de fogonazos; el umbral exacto se fija midiendo); coste de latencia: cero (comparar dos horas por tick). (2) Para NO perder la paridad, las velas del lago de los tickers candidatos (los únicos que dan señal) se reconstruyen desde los ticks con el MISMO filtro y se mide cuántas señales cambian (área P); hasta entonces, la protección real son R-B-01 (tope 3 %: si la señal viene de un print fantasma el bid está lejos) y el disparo de los stops por ask.
- Latencia: NINGUNA (Jaume preguntó dos veces, 19-sep): el filtro es comparar dos marcas de tiempo por cada tick antes de sumarlo a la vela, microsegundos, y ocurre en la construcción de la vela, no en el envío de la orden; además usa el feed de operaciones, que es MÁS rápido que las velas agregadas de Massive. Cero efecto en el slippage.
- Estado: FIJADA en su lógica (Jaume, 19-sep); umbral (10 o 20 ms) y reconstrucción del lago pendientes (área P). Origen: A5, A4.

### R-A-04 · Símbolos, duplicados, eventos, histórico e indicadores
- **A7, símbolos distintos entre Massive y DAS** (clases de acciones, sufijos): tabla de equivalencias mantenida por el bot, construida ANTES de operar y actualizada cada día (bajas, vueltas a cotizar). Si un símbolo no casa, no se opera y se avisa. No debe haber equivalencias corruptas.
- **A10, eventos programados** (FOMC, resultados): tarea humana; sin regla en el bot.
- **A12, histórico incompleto al entrar en el radar**: no se opera ese ticker hasta tener el histórico; se reintenta la carga.
- **A13, indicador que en vivo no existe o no se entiende igual que en el backtest**: el bot tiene que ENTENDER cada indicador exactamente como el backtester desde el arranque; si no puede, AVISA antes de operar nada y esa estrategia queda BLOQUEADA hasta que se arregle entre nosotros.
- Estado: FIJADAS (Jaume, 19-sep). Origen: A7, A10, A12, A13.

### R-A-05 · Señales duplicadas por reconexión del feed
- Situación: Massive reenvía velas o ticks ya recibidos tras una reconexión y el motor evalúa el mismo minuto dos veces.
- Acción: cada evento lleva un identificador estable (ticker | estrategia | minuto | tipo), heredado del bot de avisos; un evento repetido se IGNORA. Nunca dos órdenes por la misma cosa. La idempotencia llega hasta DAS con el token de orden (B5).
- Estado: FIJADA (Jaume, 19-sep). Origen: A9.

### R-A-03 · Splits, contrasplits, IPOs recientes, SPACs y OPAs: exclusiones del radar
- Situación: valores que no deben entrar aunque den señal.
- Detección: (1) Splits / contrasplits del día: lista de acciones corporativas de Nasdaq (Daily List) consultada cada mañana antes del PM; el lago ya anula esos días, y el radar tendrá filtro. (2) IPO / relisting reciente: Massive /v3/reference/tickers/{t} devuelve list_date (fecha de salida a bolsa): no entrar si lleva cotizando menos de X días (Jaume: p. ej. un mes). (3) SPAC: el mismo endpoint da sic_code y sic_description; las SPAC son SIC 6770 «Blank Checks». (4) OPA / fusión con precio clavado: Massive NO lo da directamente. Dos vías a estudiar: noticias de Massive (/v2/reference/news, palabras clave «to be acquired», «definitive agreement», «merger») y la heurística de precio que propone Jaume: tras un gap grande el precio se queda horas en una banda estrecha; medir en el lago la anchura de esa banda en las 340 OPAs de la auditoría del 19-sep para fijar el umbral y usarlo como SALIDA de seguridad (si estamos dentro y el precio se clava, salir).
- Acción: lista NEGRA manual en el cuadro de mandos (Jaume mete tickers a mano, p. ej. OPAs conocidas) + exclusiones automáticas configurables del radar (IPO < X días, SPAC, split del día) + salida de seguridad por «precio clavado» (pendiente de estudio).
- Parámetros: X días de IPO (provisional 30); banda de OPA: desde el máximo de PM, 30 min con rango ≤ 1,5 % y ≥ 100 k $ negociados.
- **El estudio de la banda YA ESTÁ HECHO (otra sesión, 19-sep, memoria «auditoría mergers»):** con esa señal se detecta el 58 % de las OPAs antes de las 09:00 con un 0,8 % de falsos positivos en 522 gaps normales; se dispara sobre todo DESPUÉS de haber entrado → es regla de SALIDA de seguridad, no de veto. Las OPAs que no la disparan (el precio sube en escalera hacia la oferta) son las que hacen daño (4 stops de 1A). Noticias de Massive: PARCIALES (varias OPAs sin noticia el día del gap) → Jaume: inviables como filtro; el dato técnico de las velas es el primer filtro, y las noticias, si acaso, secundario. Massive SÍ da en el momento sic_code (6770 = SPAC), type (UNIT/WARRANT/ADRC), list_date, market_cap y acciones en circulación a la fecha.
- **Riesgo real de entrar en una OPA que la señal no detecta (el 40 % restante), según la auditoría:** 1A entró en 159 de 340 OPAs; resultado total −5,3 R en 163 operaciones: «dinero muerto, no agujero». Antes de clavarse PF 0,72; después PF 0,25 con el 88 % de las operaciones a ±1 %. Solo 4 stops (entradas tempranas mientras el precio sube en escalera hacia la oferta) y algunas de −9/−15 % sin stop. El peor caso es un stop normal (1 R) y capital parado horas; NO es riesgo de cola: en las OPAs el precio se clava, no se dispara. Los fogonazos siguen siendo el peligro, no las OPAs. Además, en el 26 % hubo un halt T1 ~35 min ANTES del gap (no se está dentro). **¿Y una OPA que se «clave» a una distancia enorme (+1.000 %)?** El gap de la OPA ocurre antes de que entremos (es lo que nos hace entrar); una vez dentro, lo que puede pasar es que el precio siga subiendo en escalera hacia el precio de la oferta (los 4 stops de 1A, −9/−15 % sin stop). El caso de cola de verdad es una OPA ANUNCIADA con la posición abierta: halt T1 y reapertura al precio de la oferta; eso ya está cubierto por R-F-05 con datos: en 8 años el T1 que más alto reabrió en horario fue +329 % (CAPR) y +475 % en after-hours (ABVX); mercado al reabrir hasta +250 %, por encima alerta máxima y humano.
- Estado: FIJADA (Jaume, 19 y 20-sep): lista negra manual + IPO < 30 días + SPAC (SIC 6770) + split del día fuera. **OPAs (decidido el 20-sep): la banda clavada (30 min ≤ 1,5 % desde el máximo de PM, ≥ 100 k $) es un AVISO por Telegram, no una salida automática: Jaume mira el gráfico y sale a mano si ve que es una OPA.** Base: en una OPA clavada el precio no se mueve el resto de la sesión (sin riesgo de cola; en la auditoría el peor caso fue un stop normal y dinero parado) y la liquidez sobra (spread 0,085 % tras clavarse, más $ negociados que la media). Origen: A8, A11, A14.

### Área D · Salidas y pirámides

### R-D-01 · Salida por hora de la estrategia: un minuto antes agregando en el punto medio y, a la hora, al ask (v2, 22-sep; la escalera de abajo es la versión del 17-sep, sustituida por R-D-08)
- Situación: la estrategia manda salir por hora (cierre de la estrategia, «Partial TP (Hour)», salida por tiempo). Se compra para cubrir.
- Detección: reloj de la estrategia (hora de salida definida en su JSON) y ask/último precio de DAS.
- Acción: misma lógica que la entrada pero al revés. Escalera de COMPRA agregando liquidez: +1 % sobre el último precio; a los 10 s, +2 %; a los 20 s, +3 %, y ahí hasta completar el minuto. Si al minuto no se ha ejecutado (entera o en parte), lo que quede se compra AL ASK (remover) para asegurar la salida. Lógica estricta «si / si no»: lo ejecutado en la escalera se DESCUENTA y la orden al ask lleva solo el resto; jamás se compra dos veces la misma cantidad (mismo control que R-C-11: posición neta real).
- Quién la ejecuta: ejecutor + vigilante (comprobación de posición neta tras la salida).
- Parámetros: escalones 1/2/3 %; cambio cada 10 s; tiempo total 60 s (los de R-B-01, compartidos).
- Si la acción falla: la orden al ask no se ejecuta (sin liquidez) → R-C-03 (aviso, reintentos) y aviso máximo si llega al EOD de la estrategia (R-D-02).
- Prueba: tabla de casos (ejecuta en escalón 1/2/3, parcial + resto al ask, nada + todo al ask); sombra.
- Estado: FIJADA (Jaume, 17-sep).
- Origen: D3.

**Matiz de liquidez en las salidas (22-sep):** en una compra para cubrir, AGREGAR es dejar la orden por DEBAJO del ask (al bid o entre bid y ask) y esperar; REMOVER es comprar al ask. La escalera de R-D-01 (+1/+2/+3 % sobre el último) solo agrega cuando el ask está lejos (más de un 1 % por encima del último); si el ask está cerca, el primer escalón ya lo cruza y remueve al instante con techo del 1 %. Así que hoy, de las salidas: el TAKE PROFIT agrega (orden en su nivel, cobra rebate); la salida por hora agrega solo con spread ancho; EOD, cerrar todo, TP a medias, prioridad de R-D-07 y todos los stops REMUEVEN. **R-D-08 (FIJADA, Jaume 22-sep): salidas con hora conocida (salida por hora y EOD) AGREGANDO.** Un minuto ANTES de la hora se pone la compra para cubrir en el PUNTO MEDIO bid-ask, agregando (misma mecánica que R-B-01 al revés). Al llegar la hora, lo que no haya llenado se cruza AL ASK, sin tope: la hora de salida no se negocia. Sustituye a la escalera +1/+2/+3 % de R-D-01, que queda como historia. El TP sigue agregando en su nivel. Se mide en sombra igual que la entrada. Los stops quedan fuera de esto: siempre remueven.

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
- Acción (v2, Jaume 22-sep: mismo patrón que la entrada, agregar primero): (1) el resto (200) se pone como compra AGREGANDO en el punto medio bid-ask hasta 60 s; si no llena, lo que quede se cruza AL ASK con TECHO del 3 % sobre el último precio DE ESE MOMENTO (no el de hace un minuto; misma protección que el stop principal). Redacción anterior (17-sep): directamente al ask con techo 3 %. (2) Si NO se ejecuta porque el precio se ha ido más del 3 %, NO se persigue: la posición sigue en manos de sus dos stops residentes (principal y emergencia), que ya llevan la lógica de squeeze y cisne negro. Nunca una compra a mercado sin techo en ese momento (libro posiblemente vacío). (3) Si no se ejecuta, AVISO al humano: la posición puede quedar en el «limbo» entre el límite y el stop hasta que el precio vuelva a uno de los dos. (4) El bot ajusta en todo momento la cantidad de los stops a la posición que queda «en el aire» (R-C-07: reducir el stop a lo que sigue en corto). (5) Si por un fogonazo se ejecutan compras de más y quedan acciones LARGAS, se venden al instante (R-C-11).
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
- Acción: el bot cierra TODAS las posiciones de la cuenta, incluidas las que no abrió él (manuales): los cortos comprando AL ASK y los largos vendiendo AL BID (remover, rápido). Cancela antes las órdenes vivas de cada posición para no comprar/vender de más (R-C-11). **Techo (Jaume, 20-sep): 5 % sobre el ask (o bajo el bid) del momento; si no entra, reintenta DOS veces más con el 5 % desde el precio de ese momento; si sigue sin entrar, AVISO con el precio actual y decide Jaume.** Mismo procedimiento para /cerrar TICKER SI y /cerrar TICKER N SI.
- Quién la ejecuta: ejecutor por orden del humano.
- Parámetros: techo 5 %; reintentos 2.
- Si la acción falla: aviso con la lista de lo que sigue abierto y su precio actual.
- Prueba: simulacro en demo/sombra con posiciones del bot y manuales.
- Estado: FIJADA (Jaume, 17 y 20-sep).
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

**E3 (Jaume, 18-sep): sin tope por ticker.** La exposición por ticker la controla el reparto del cuadro de mandos: si se quiere un 6 % máximo en total con tres estrategias, se asigna un 2 % a cada una; es imposible acumular más de lo previsto en un solo valor.

### R-E-02 · Sin capital para todas: orden de llegada
- Situación: varias señales (o pirámides) a la vez y no hay capital libre para todas.
- Detección: capital libre de DAS frente a lo pedido (R-I-01).
- Acción: por ORDEN DE LLEGADA. La primera entra entera; la siguiente recibe el capital que sobre (si sobra algo, solo eso); si no queda nada, no entra. Lo mismo con las pirámides: si no hay dinero, no se piramida. Sin reparto proporcional.
- Quién la ejecuta: guarda.
- Parámetros: ninguno.
- Si la acción falla: —
- Prueba: tabla de casos.
- Estado: FIJADA (Jaume, 18-sep).
- Origen: E5, E4.

### R-E-03 · Estrategia desactivada o cambiada de versión con posiciones vivas
- Situación: se desactiva una estrategia en el cuadro de mandos, o se carga una versión nueva, mientras tiene un lote abierto.
- Detección: cambio en el cuadro de mandos con lote vivo.
- Acción: el cuadro de mandos muestra en ese momento los botones para elegir: «cerrar posiciones y reiniciar con la nueva estrategia» (cierre con R-D-01 y arranque de la versión nueva) o «esperar a que la estrategia antigua termine el día» (el lote se gestiona hasta su salida normal con las reglas de la versión vieja; la nueva empieza al día siguiente). Nada automático: lo elige el humano.
- Quién la ejecuta: cuadro de mandos + ejecutor.
- Parámetros: ninguno.
- Si la acción falla: sin elección del humano → se espera a que termine el día (opción segura).
- Prueba: sombra.
- Estado: FIJADA (Jaume, 18-sep).
- Origen: E7, O4.

**E8 (Jaume, 18-sep): cada estrategia y cada pirámide tiene su propia unidad de riesgo.** El cuadro de mandos solo registra el número (como el cuadro actual de las alarmas); cómo se usa lo dicta la estrategia: p. ej. la entrada por distancia al stop y riesgo normal (market value) y las pirámides en dólares fijos. El bot interpreta el riesgo según lo que diga cada estrategia.

**E9 (Jaume, 18-sep): el locate se carga a la PRIMERA estrategia que da señal;** si sobran acciones del paquete, a la siguiente; si faltan, se compran más (R-H-01, coste total acumulado). En principio no debería faltar: se compran al principio previendo las acciones necesarias.

### R-D-07 · Take profit de una estrategia y entrada de otra en el mismo instante
- Situación: en el mismo minuto (o instante) coinciden un take profit de la estrategia A y una entrada de la estrategia B en el mismo ticker. Muy raro, pero previsto.
- Acción: PRIORIDAD al take profit: primero se ejecuta el take profit de A, después la entrada de B, una tras otra, nunca juntas. Si se detectan a la vez, el take profit se tira AL ASK (remover) para que sea lo más rápido posible, porque libera buying power y margen para la entrada. Añadir en un ticker tras una reducción está permitido sin más; no hay veto temporal.
- Estado: FIJADA (Jaume, 19-sep). Origen: D5.

**I3 (Jaume, 19-sep): sin regla de racha; manda la estrategia. El bot solo está ajustado para límites estrictos por stop loss y las reglas de proceso de este libro.**

**Recordatorio del área E (ya decidido en C, B y D):** un lote por estrategia en el diario; entradas simultáneas sumadas en una orden (R-B-03); stop único si coinciden en nivel, uno por lote si difieren (R-C-06 + nota de R-C-11); take profits por lote (R-D-03); la suma de órdenes nunca supera la posición.

### Área L · Calendario

**Resueltas de rebote:** L1 ventanas por estrategia (JSON); L2 festivos y medias sesiones por el calendario de Massive (F12); L3 horario de verano (R-J-07, todo en ET); L4 sin posiciones overnight (R-D-02); L7 eventos macro = tarea humana (A10).

### R-L-01 · Horario de encendido: solo PM y la parte de sesión que interese
- Situación: el bot NO está encendido las 24 horas (Jaume, 19-sep).
- Acción: el supervisor arranca DAS → vigilante → ejecutor antes de las 04:00 ET de cada día de mercado (con reconciliación) y los apaga tras el último EOD de las estrategias activas más el margen de R-D-02. Fines de semana y festivos: apagado. El latido externo (R-J-05) solo vigila dentro de la ventana de encendido.
- Parámetros: hora de arranque y de apagado (cuadro de mandos; hoy PM y parte de RTH).
- Estado: FIJADA (Jaume, 19-sep). Origen: L5.

### R-L-02 · Ventana horaria de cada estrategia: revisión manual + comprobación del bot
- Situación: trampa conocida del backtester: la sesión «se sumaba» (RTH + personalizada corría hasta las 16:00); corregido en la interfaz, pero las estrategias antiguas guardadas pueden seguir así.
- Acción: el bot interpreta el JSON EXACTAMENTE como el backtester (paridad). Antes de estrenar cada estrategia, Jaume revisa a mano su ventana horaria; el bot, al cargarla, comprueba coherencia (ventana, EOD, sesión) y avisa si ve algo raro.
- Estado: FIJADA (Jaume, 19-sep). Origen: L6.

### Área M · Control humano

### R-M-01 · Tres niveles de aviso, resumen diario y comando de detalle
- Niveles: **Informativo** (entradas, salidas, pirámides, take profits); **Aviso** (incidentes que el bot resolvió solo: stop repuesto, entrada parcial, locate no disponible, reconexión); **Máximo** (necesita humano: posición sin stop, DAS caído, cisne negro, posición desconocida, compras de más, EOD sin cerrar, bucle de locates). Sin prealertas en este bot (M8).
- Todo aviso va a la vez a Telegram, al log y al panel de avisos del cuadro de mandos (mismos mensajes).
- Resumen al cierre de cada día: operaciones, resultado por estrategia, incidentes, coste de locates, slippage medido.
- Comando de Telegram «detalle» para pedir la explicación completa de cualquier aviso o incidente (sobre todo de los niveles Aviso y Máximo).
- Estado: FIJADA (Jaume, 19-sep). Origen: M2, M3.

**R-M-05 · Un solo bot, una sola cuenta de Massive: el ejecutor también manda las alarmas (Jaume, 22-sep, FIJADA en su forma).** No hacen falta dos cuentas de Massive ni dos bots: el bot de ejecución consume el feed UNA vez y, por cada señal, hace dos cosas: envía la orden (si la estrategia está activa para operar) y publica la alarma en un grupo de Telegram distinto del de los fills, para el socio que no opera con bot. Las prealertas (segundo 44-59) son opcionales por interruptor: si meten ruido, solo las alarmas de vela cerrada. El bot de alarmas actual (D:/bot_senales) se RETIRA: se reutiliza su código (radar, velas por ticks, prealertas, Telegram) dentro del ejecutor, pero alarmas y prealertas salen de la estructura del bot nuevo. PRIORIDAD: siempre la ejecución; alarmas y prealertas son secundarias: se encolan y las envía un hilo aparte DESPUÉS de despachar la orden, así no añaden ni un milisegundo al bot; para el socio la alarma llega igual que hoy (el envío a Telegram tarda 0,2-0,5 s y va en paralelo). Todos operan las mismas estrategias (Jaume): no hay divergencia entre bot y alarmas. **Exigencia (Jaume, 22-sep): el bot tiene que ser EXACTAMENTE igual de rápido con alarmas que sin ellas.** Diseño: el ejecutor solo deja la señal en una cola en memoria (microsegundos) y sigue; un proceso aparte lee la cola y manda Telegram; si Telegram va lento o cae, la cola crece y el ejecutor ni se entera. Prueba en sombra: medir la latencia señal→orden con las alarmas encendidas y apagadas; tienen que salir iguales. Las alarmas salen a la misma velocidad que hoy o antes, porque la vela se cierra con ticks. Canales de Telegram: (1) alarmas de señales, para los socios; (2) operativa del bot (fills, stops, avisos, comandos), solo Jaume; (3) emergencias nivel 3.

### R-M-02 · Canales: Telegram siempre; correo y SMS para el nivel Máximo
- Reparto FIJADO (Jaume, 19-sep): Telegram → niveles 1, 2 y 3 (en cola con reintentos, R-J-08). Correo (Gmail) → niveles 2 y 3. SMS → SOLO nivel 3 (Máximo); llega por red móvil, no necesita Internet en el móvil de Jaume. Sin llamada de voz.
- SMS: servicio de pago por uso, sin suscripción mensual: Amazon SNS (≈ 0,05-0,10 € por SMS a España, sin cuota) o Twilio (parecido por mensaje; puede exigir alquilar un número ≈ 1 €/mes salvo remitente alfanumérico). Coste real esperado: céntimos al mes, porque el nivel Máximo es raro. El envío lo hace el bot por Internet desde el VPS; solo la recepción va por red móvil.
- Estado: FIJADA en su lógica (Jaume, 19-sep); proveedor de SMS por elegir (preferencia: sin suscripción). Origen: M4, J19.

### R-M-03 · Intervención humana detectada: proteger, avisar y pausar entradas
- Situación: aparece en DAS una orden o posición que no es del bot (Jaume o el socio han actuado a mano, en emergencia).
- Acción: el bot AVISA (log + Telegram), protege la posición (R-C-10 caso 4) y SE PONE EN PAUSA de nuevas entradas hasta que un humano le diga «sigue» (comando de Telegram o botón del cuadro de mandos). Las posiciones propias siguen gestionándose. Esto resuelve el traspaso humano↔bot que estaba pendiente: la señal de «esto lo he hecho yo» es el propio «sigue».
- Estado: FIJADA (Jaume, 19-sep). Origen: M6, K5, pendiente de R-C-10.

### R-M-04 · Comandos de Telegram (lista acordada el 19-sep)
- Solo desde los dos chat_id autorizados (Jaume y socio). Los de consulta van sin confirmación; los de acción sobre el bot con confirmación en dos pasos; los de acción sobre el mercado con «SI» explícito.
- Consulta: /estado (encendido o pausado, posiciones por estrategia, PnL del día, últimos incidentes); /posiciones (cada lote: entrada, stop, take profit, PnL latente); /ordenes (órdenes vivas en DAS); /locates (comprados hoy, precio, usados o no, gasto frente al 3 %); /estrategias (activas, ventana, tamaño); /detalle id; /salud (conexiones Massive/DAS/servidor de órdenes, latido, latencia, reloj); /log n.
- Acción sobre el bot: /pausar y /reanudar (no abrir nuevas); /sigue (tras intervención humana, R-M-03); /modo_seguridad on|off (R-I-04); /desactivar y /activar estrategia; /apagar («control humano») y /encender (arranca con reconciliación).
- Acción sobre el mercado: /cerrar_todo SI; /cerrar ticker SI (ask para cortos, bid para largos); /cancelar_ordenes ticker SI (deja la posición sin órdenes vivas para actuar a mano); /stop ticker precio SI (mover el stop a mano).
- **Coherencia tras un cierre por Telegram (Jaume, 19-sep):** cuando se cierra una posición o un lote por Telegram, el bot lo REGISTRA como cerrado y CANCELA todas las órdenes asociadas a ese lote (stops, take profits, escaleras) y desactiva sus salidas por hora: nunca ejecutar un take profit ni una salida por hora sobre una posición que ya no existe (compraría a mercado sin posición). Todo se comprueba contra la posición neta real de DAS (R-C-11).
- Estado: FIJADA en su lista (Jaume, 19-sep); runbook borrador en docs/BOT_EJECUCION_RUNBOOK.md. Origen: M1, M5.

**M7 (Jaume, 19-sep): el bot NO pide confirmación humana antes de operar; es autónomo dentro de sus reglas. Las primeras semanas se va con capital mínimo o en demo (se concreta en el área O).**
**M8 (Jaume, 19-sep): día en que ni Jaume ni el socio pueden vigilar: se apaga el bot ese día o se pone en «modo trading de seguridad» (R-I-04).**

### Área N · Registro y contabilidad

### R-N-01 · El diario
- Qué se guarda por cada decisión: hora exacta, estrategia y lote, señal y sus datos (precio, bid, ask, distancia), regla aplicada, orden enviada (token, tipo, precio, ruta), respuesta de DAS (aceptada, rechazada con motivo, fill con precio y cantidad), stops puestos y cambiados, locates (precio, cantidad, usado o no), avisos emitidos, y las métricas de ejecución (slippage frente al backtester, latencia orden→confirmación, fracción del volumen).
- Cómo: ficheros por día, escritos ANTES de enviar y DESPUÉS de la respuesta (M6); texto (JSONL) para el día en curso y, si crece, parquet para el histórico (ocupa poco). Los precios que vio el bot se guardan también, para poder reproducir cualquier día sin el feed (los del lago llegan con la actualización, pero el diario guarda los que el bot usó en el instante). Copia fuera del VPS siempre (Q4). Conservación: todo.
- Comisiones, tasas y PnL neto: NO hace falta que el bot los calcule ni los cuadre con el bróker (lo tiene el bróker); se REGISTRAN por tener base de datos, sin regla de cuadre.
- Métricas de ejecución: en el resumen DIARIO (R-M-01), no en el cuadro de mandos (no inundarlo; el cuadro se repasa al final).
- Estado: FIJADA (Jaume, 19-sep). Origen: N1-N6.

### Área O · Pruebas y despliegue

**O2 y O3 (Jaume, 19-sep): el orden sombra → demo → canario y el número de sesiones de cada fase se DECIDEN AL FINAL, con todo hecho; puede hacer falta más o menos. Las fases y criterios del 5-sep siguen como referencia.**

### R-O-01 · Cambios solo con el bot apagado, y versión registrada
- Los cambios de código y de estrategias se hacen SIEMPRE con todo el bot apagado (fuera de la ventana de R-L-01): apagar del todo, actualizar, reiniciar. Nunca en caliente. El bot escribe en el diario, en cada arranque, la versión de código y el hash y fecha del JSON de estrategias con que arranca.
- Estado: FIJADA (Jaume, 19-sep). Origen: O4, O5.

### R-O-02 · Repetición de un día grabado y vuelta atrás (PROPUESTA, pendiente de Jaume)
- Antes de estrenar cada versión: (1) pasar las tablas de casos de las reglas de este libro; (2) REPETIR un día grabado (las grabaciones del bot de avisos) contra el ejecutor EN SECO (sin DAS: decide y escribe en el diario, no envía), comparando con la versión anterior; sirve además para provocar casos raros (halt, fogonazo, entrada a medias) que el canario quizá no muestre. (3) Vuelta atrás: cada versión de bot y de estrategias etiquetada con fecha; mando de «volver a la anterior» en el arranque, en minutos.
- Estado: FIJADA (Jaume, 19-sep): repetición de días grabados obligatoria (dejará el bot de avisos encendido más tiempo para grabar más días y probar todo antes de entrar en vivo) y vuelta atrás formal con versiones guardadas por fecha (ocupan poco). Origen: O7, O8.

**O9 (Jaume, 19-sep):** lo que solo se puede probar con dinero (locates reales, rechazos, halts) se descubre en el canario a tamaño mínimo y cada caso nuevo se anota en el libro; pero no todo aparecerá en el canario (hay casos raros) y no es plan alargarlo mucho → por eso importa la repetición de días grabados (R-O-02).

### Área P · Backtester vs vivo

**P1 y P5 (Jaume, 19-sep):** el backtester se deja como está (llena los stops en reaperturas al nivel, no modela halts ni SSR); se MIDE en sombra la diferencia real y solo se toca el motor si es relevante (igual que con los prints tardíos, R-A-02).
**Comisiones para backtests de 1B (22-sep, sobre 3.024 trades reales de 1B ene-2025→ago-2026, precio de entrada mediana 3,59 $, 9 % por debajo de 1 $):** ida y vuelta TODO removiendo (entrada rama rápida + salida al ask + SEC/TAF): mediana 0,19 %, media 0,27 %, p90 0,65 %, ponderado por nocional 0,26 %; con la entrada agregando (escalera): media 0,07 %. Recomendación para backtests: **0,25 % por trade completo** (conservador; 0,12 % por lado si el parámetro es por lado), aparte del slippage (≈ 0,3 % que baraja Jaume; medido 0,9 % PM / 0,6 % RTH en el estudio de entradas) y de los locates. En 1B el 71 % de las salidas son EOD y el 29 % SL: casi todas remueven. **P2 y P3 (19-sep):** el backtester no tiene slippage de base: lo pone quien lo configura. Recomendación para EVALUAR estrategias (no regla del bot): usar los valores medidos (1 % PM, 0,7 % RTH) hasta tener los reales de la sombra. Al bot le entra la estrategia normalizada: solo reglas, sin comisiones ni slippage.
**P4 (Jaume, 19-sep):** el bot registra cada precio real de locate con fecha (R-H-01) y con eso se recalibra la banda de locates del backtester cada cierto tiempo; a futuro, modelar «ciclos» de precios de locates. De momento, registrar basta.
**P6:** resuelto en R-A-02 (mismo filtro de prints en lago y bot cuando se decida).
**P7 (Jaume, 19-sep):** SIN criterio de parada automática por divergencia. El bot registra el slippage medio (R-N-01); si se fuera de madre, tocaría buscar estrategias nuevas, y eso no es cosa del bot.
**P8:** resuelto en R-A-04 (indicador que no existe en vivo → estrategia bloqueada + aviso).

### Área Q · Seguridad

### R-Q-01 · Seguridad (todo FIJADO, Jaume, 19-sep)
- Credenciales de DAS, token de Telegram y claves solo en el .env del VPS, fuera del repo.
- Acceso al VPS con usuario propio para Jaume y otro para el socio; RDP solo por VPN o con IP fija.
- Comandos de Telegram solo desde los dos chat_id autorizados (Jaume y socio), con confirmación en los que cambian algo.
- La fuga del token de Telegram en los logs (httpx), aplazada hasta ahora, se ARREGLA ANTES de pasar a dinero real.
- Copias del diario y del estado fuera del VPS (R-N-01).
- El bot no tiene ningún permiso de mover dinero ni cambiar ajustes de cuenta [API: confirmar que el CMD API no lo permite o cómo se bloquea].
- Origen: Q1-Q6.

## 4. Registro de cambios

| Fecha | Qué | Quién |
|---|---|---|
| 2026-09-12 | Se abre el fichero con el formato, los principios marco y el índice de áreas. Ninguna regla aún. | Jaume + Claude |

### R-A-06 · Datos de Massive: la SEÑAL con la vela oficial de minuto; los ticks para prealertas y precios; una sola conexión
- Situación: qué dato de Massive decide la señal y con qué retraso. **CORREGIDA el 22-sep con lo medido en el chat del bot de alertas** (memoria `btt-radar-en-proceso-y-vela-oficial`): la métrica que daba «3 s» medía el canal de agregados por SEGUNDO (`A.`), que sí llega 3,1 s tarde, pero la señal no sale de ahí.
- Medido (21/22-sep): vela OFICIAL de minuto (`AM.`) 1,49 s tras cerrar el minuto con cliente ligero, ~1,9 s en el bot; último print del minuto (`T.`) a +0,26-0,95 s; velas PROPIAS construidas con ticks: cerradas a +1,0 s pero con **el 43 % de los cierres distintos del oficial** (mediana 0,43 %, hasta 5,7 %) porque Massive publica los dark pools del propio minuto hasta 6 s tarde, y a las 04:00 la cinta vuelca en bloque las operaciones de la noche (prints tardíos de horas). 2 s de retraso mueven el precio un 0,42 % de mediana pero con signo 0,00 %: ruido, no coste.
- Acción (FIJADA, Jaume 22-sep: «1-2 s es asumible»): (1) la SEÑAL de entrada y las ALARMAS se deciden con la vela OFICIAL de Massive (`AM.`), la misma que usa el backtester: paridad por construcción, ~2 s tras el cierre del minuto. (2) Los ticks (`T.`) y cotizaciones (`Q.`) se usan para las PREALERTAS (segundo 44-59) y para anticipar, nunca para decidir la señal. Filtro de prints tardíos en los ticks: `t − pt > 20 ms` → fuera (R-A-02). (3) Los precios de ejecución (bid/ask al enviar, puerta, vigilancia) salen de DAS, en tiempo real. (4) **UNA sola conexión al socket de Massive por máquina**, compartida por radar (proceso aparte, tubería), ejecutor y alarmas; **NUNCA abrir otro websocket con el bot encendido**: el 22-sep una sonda de medición (la mía, `_lat_ws.py`, 13:34) abrió una 4.ª conexión y provocó 5 cortes 1008 (~4 min sin datos en el bot de alertas). (5) Radar en dos capas: Massive mercado entero → las que saltan (≤ 50) al radar de DAS. (6) El radar barre en un PROCESO aparte, no en un hilo: un hilo que calcula bloquea al lector del socket (GIL; medido 11 s sin leer por un barrido de 5,8 s).
- Parámetros: ninguno.
- Prueba: en sombra, latencia de la vela oficial y de los ticks cada día en el diario; paridad de señales con el backtester 100 %.
- Estado: FIJADA (Jaume, 22-sep). Historia: 21-sep propuse ticks para la señal; el otro chat lo probó y lo apagó por la paridad.
- KB de DAS (23-sep): el Level 1 por API admite 100/150/250 símbolos según nivel (no 50); no hay Level 2 por el API; sin libro no hay lógica de colas en el vigilante, solo NBBO.
- Origen: pregunta de Jaume del 21-sep; medidas del chat del bot de alertas (21/22-sep).
- **Variante DAS (21-sep; cautela 22-sep):** construir las velas del radar desde el Time & Sales de DAS sería aún más rápido, pero tiene el MISMO problema de paridad que las velas propias por ticks (dark pools y prints tardíos publicados después): solo vale si en sombra las velas salen idénticas a las oficiales de Massive. Hoy la señal va con la oficial. Condiciones: (a) que el tope de símbolos del Level 1 por API (≈ 50 según el manual) cubra el radar del día [API R-18]; (b) que las velas salgan IGUALES que las de Massive, que son las del backtester (feed consolidado de todas las bolsas, mismas exclusiones de prints) [API R-19]; (c) Massive queda para el radar, los cierres de ayer y como respaldo de velas si DAS cae. Decisión: en SOMBRA se construyen por las dos vías a la vez y se comparan varios días; si coinciden y caben, manda DAS; si no, Massive con ticks.

### R-O-03 · Fases de puesta en marcha: sombra → demo → canario (FIJADA, Jaume 21-sep)
| Fase | Duración | Qué se hace | Para pasar a la siguiente |
|---|---|---|---|
| Sombra | 1 semana de mercado | Bot con datos reales y DAS conectado, SIN enviar órdenes. Mide latencia por canal (Massive T/Q, DAS), slippage teórico contra el libro, paridad de señales con el backtester, estabilidad de los procesos. | Cero caídas sin recuperación automática; paridad de señales 100 %; latencias registradas en el diario. |
| Demo | 1 semana | Mismo bot contra la cuenta DEMO de DAS: órdenes reales con dinero falso. Fills, stops residentes (principal + emergencia), cancelaciones, limpieza de R-C-11, EOD, y los simulacros del runbook que se puedan PROVOCAR (matar DAS, cortar feed, matar ejecutor/vigilante, doble instancia, Telegram caído). | Los simulacros provocables superados; ninguna posición larga no deseada; reconciliación sin diferencias. **Aviso de Jaume (21-sep): las casuísticas del libro son muy amplias y una semana de mercado NO las cubre todas (halts, fogonazos, OPAs…); es posible entrar a real sin haberlas visto en demo. Por eso lo que valida el resto es el CÓDIGO: tests unitarios de cada regla con casos grabados (repetición de días, R-O-02) antes de la demo, no la demo.** Pendiente: cómo se configura la cuenta demo en DAS/Sage [API]. |
| Canario | 1-2 semanas (Jaume lo va diciendo) | Dinero real, tamaño mínimo, una estrategia. | Jaume sube el tamaño cambiando el riesgo en el cuadro (R-I-02); criterio orientativo: sin intervención humana no prevista durante la fase. |
- La FASE se gestiona desde el cuadro de mandos: selector sombra / demo / real, visible siempre en la cabecera y en cada aviso de Telegram (para no confundir un fill de demo con uno real). Cambiar de fase exige bot apagado y sin posiciones (R-O-01). En «sombra» el ejecutor tiene prohibido enviar órdenes a nivel de código, no solo de configuración.
- Origen: repaso final del 21-sep.

## 5. Escenarios pendientes (no urgentes para el funcionamiento básico; se deciden más adelante)
Escenarios que se han detectado y NO están decididos del todo. No bloquean el bot: en todos ellos la respuesta provisional es «aviso nivel 3 y control humano». Se revisan con el PDF, en demo o cuando Jaume quiera.

| Id | Escenario | Estado provisional | Qué falta decidir |
|---|---|---|---|
| EP-1 | Posición corta SIN stop aceptado (DAS rechaza o cancela el stop y los reintentos de R-C-03 fallan) y el motivo es un bloqueo por símbolo/cuenta o desconocido | Aviso nivel 3, control humano; el bot NO cierra al ask por su cuenta (podría ser un cisne negro donde no toca cerrar al ask) | Qué hace el bot mientras el humano no responde: ¿nada? ¿informe cada minuto como en R-G-01? ¿un tope de tiempo o de precio a partir del cual sí cierra? ¿distinguir «squeeze normal» de «fogonazo» con el criterio de tiempo de G3 (5-10 min arriba = squeeze)? |
| EP-2 | Orden a mercado enviada durante un halt: la KB dice que «la maneja la ruta» y no garantiza el cruce de reapertura (R-F-01) | Se mantiene «un minuto antes» como diseño | Probar en demo ruta por ruta (SMAT, ARCA, SAGEPRO); si alguna la rechaza o la deja colgada, elegir ruta o enviar al reabrir |
| EP-3 | Dos stops de compra residentes retienen BP dos veces o chocan con «Max Ord Cap» / «Max Pos Val» valorados al límite (+87 %) | Pregunta al bróker (KB) | Si retienen BP doble: bajar el límite de la emergencia, o ponerla solo cuando el principal falle (con la latencia que eso añade), o pedir excepción a Sage |
| EP-4 | Trigger Order del API (stop pegado a la entrada) solo dispara con la entrada «fully executed»: una entrada llenada a medias (R-B-02) no tendría stop automático | El bot pone los stops él mismo tras cada fill parcial (diseño actual) | Si el API expone Trigger Orders, decidir si se usan solo cuando la entrada llena entera |
| EP-5 | Techo de la emergencia: 50 % sobre su disparo (+87 % con stop a +10 %; +112 % con stop al Previous Max a +25 %) frente a medirlo sobre el límite del principal (+70 %) | Se mantiene el 50 % sobre el disparo (lo medido en el estudio) | Jaume decide si quiere un techo más corto; repetir el estudio de fogonazos con el valor elegido |
| EP-6 | Limbo entre niveles con varias estrategias: rara vez el precio rebasa el principal de B sin llenarlo y sin llegar al de A | Sumar las acciones de B al principal de A (fijado) | Comprobar en demo el neteo de cantidades cuando A y B tienen fills parciales a la vez |
| EP-7 | 2FA en la cuenta del bot: activarlo impide el relogin automático de R-J-02 salvo guardando el secreto TOTP en el VPS | Sin decidir | Pregunta al bróker (KB); decidir entre seguridad de la cuenta y relogin automático |
| EP-8 | Suscriptor profesional: con socios que aportan capital o reparten beneficios los datos pasan a tarifa profesional | Sin decidir | Revisar el cuestionario de DAS antes de pedir el API |

## 4. Cuadro de mandos: inventario (borrador del 20-sep, en repaso con Jaume)

Todo lo que el libro dice «va al cuadro de mandos», recogido en un sitio. Tres columnas: qué es, valor hoy, de dónde sale. Regla de oro (R-I-03): si el JSON de la estrategia y el cuadro difieren, manda el cuadro. El bot lee el cuadro en la siguiente señal, nunca reabre lo ya abierto.

### 4.1 Por estrategia (una fila por estrategia activa, hasta 20)
| Campo | Valor hoy | Origen |
|---|---|---|
| Activa (sí/no) + botones al desactivar (cancelar entradas / dejar salidas) | — | R-E-03 |
| Tamaño: riesgo fijo por entrada y por cada piramidación (unidad de la estrategia) | lo pone Jaume | R-I-02 |
| EV mínimo del locate para entrar (por rango de precio si aplica) | de la puerta por EV del backtester | R-H-01 |
| Hora EOD y hora de fin de ventana de entrada | JSON | R-D-02 |
| Reentradas (accept_reentries / max_reentries; −1 = sin tope numérico) | JSON | R-D-04 |
| Niveles de stop N1 / N2 / N3 en % o estructura + márgenes del límite (3 % / 50 %) | 10 % / +3 % / ×1,10 / +50 % | R-C-01 |
| Take profit (parciales y cómo reduce el stop) | JSON | R-C-05, R-D-03 |
| Sesiones permitidas (PM / RTH) y ruta por sesión | ARCA PM; RTH SAGEPRO o ARCA (sombra) | R-B-01 |

### 4.2 Globales de la cuenta
| Campo | Valor hoy | Origen |
|---|---|---|
| Tope de gasto en locates sobre la cuenta (por día) | 3 % | R-H-03 |
| Entrada: espera agregando · nivel · tope de slippage al cruzar · techo del cruce | 60 s · punto medio · 3 % · 0,5 % | R-B-01 |
| Salida por hora: escalera y tiempos | 1/2/3 % · 10 s · 60 s | R-D-01 |
| Caducidad de una señal sin llenar | 60 s | R-B-04 |
| Fracción máxima del volumen acumulado | desactivado | R-B-05 |
| Techo «cerrar todo» y reintentos | 5 % · 2 | R-D-06 |
| Halts: k máximo, distancia a la banda con k = 2, vela máxima para reentrar, T1 tope | 3 · 3-5 % · 6 % · 250 % | R-F-01, R-F-05 |
| Margen del stop bajo limit up | 1-2 % | R-F-02 |
| Stop de protección para posiciones desconocidas al arrancar | 20-30 % | R-C-10 |
| Exclusiones: días de IPO, banda de OPA (min, rango, $) | 30 d · 30 min ≤ 1,5 % ≥ 100 k $ | R-A-03 |
| Modo trading de seguridad (precio mín., $ acumulados) | > 5 $ · > 2 M $ (pendiente) | R-I-04 |
| Horas de encendido y apagado | PM + parte RTH | R-L-01 |
| Fase: sombra / demo / real | sombra | R-O-03 |
| Tickers pausados por rechazo (motivo literal, hora) + botón «Reanudar ticker» / «Reanudar todo» | — | R-B-07 |
| Modo de seguridad (interruptor): precio ≥ 5 $, Acum. Dollar Volume ≥ 2 M$ | apagado | R-I-04 |

### 4.3 Técnicos (raramente se tocan)
| Campo | Valor hoy | Origen |
|---|---|---|
| Barrido de reconciliación / posiciones | 2 s / 10 s | R-K-01 |
| Feed: prealerta / emergencia | 30 s / 60 s | R-J-01 |
| Reconexión DAS y aviso | 2/4/8/16/30 s · 5 min | R-J-02 |
| Vigilante: relanzar / colgado / latido | 30 s / 10 s / 60 s ×3 | R-J-03, R-J-05 |
| Reloj y disco | 2 s · 5 GB | R-J-07 |
| Cadencia de informes en cisne negro | 5 min | R-G-01 |
| Comprobación del stop tras aviso DAS | 1 s | R-C-04 |
| Filtro de prints tardíos | 10-20 ms | R-A-02 |
| Intentos y ventana del stop rechazado | 5 · 5 min · 100 % | R-C-03 |

### 4.4 Lo que el cuadro muestra (solo lectura)
Posiciones y órdenes vivas con su estado (principal / emergencia / TP), BP y equity de DAS, locates comprados hoy y gasto acumulado frente al tope, señales del día y qué pasó con cada una (entró / caducó / rechazada), estado del feed, de DAS y del vigilante, última reconciliación, y el botón «Control humano» por estrategia.

### 4.4b Piramidaciones en el cuadro (comprobado 22-sep)
El cuadro del bot de señales YA tiene una casilla de riesgo por cada piramidación de la estrategia, en el orden de su definición (desde el 16-sep: lista `riesgos_piramide`, una por nivel; si una casilla va vacía cae al riesgo de pirámide global). La lista incluye también los pasos «reduce» (salidas parciales), que no piden riesgo. El cuadro del bot de ejecución hereda esto tal cual: tantas casillas como pirámides tenga cada estrategia, y el locate de cada estrategia se dimensiona con entrada + suma de sus «add» (R-H-05).

### 4.5 Decisiones tomadas
- **CM1 (21-sep, FIJADA):** el cuadro vive DENTRO de la app del backtester, como ampliación del panel del bot de señales. Condición: el bot NO llama al backend en caliente; la app escribe un fichero de configuración al guardar, el bot lo lee y lo guarda en su disco; si el backend cae, sigue con el último conocido y avisa (R-I-03).
- **CM2 (21-sep, FIJADA):** en caliente, con efecto en la siguiente señal: activar/desactivar estrategia, riesgo por entrada y pirámide, EV mínimo del locate, tope diario de locates, umbrales del modo de seguridad, horas de encendido/apagado, hora EOD (si hay que cerrar antes, se usa el botón o /cerrar, no el parámetro) y todos los botones de intervención. Solo con el bot apagado y sin posiciones: niveles y márgenes de stops, puerta del 3 %/techo 0,5 %/escalera y tiempos, reglas de halts, exclusiones, caducidad de la señal (60 s), fracción de volumen y todos los técnicos. Bajar un tamaño en caliente solo afecta a entradas siguientes; reducir lo abierto es un botón de cierre parcial.

- **CM3 (21-sep, FIJADA):** historial de cambios del cuadro: cada cambio va al diario del bot con fecha y hora, campo, valor anterior, valor nuevo y quién lo hizo; el cuadro enseña los últimos cambios.
- **CM4 (21-sep, FIJADA por Jaume):** en el cuadro SOLO se ajusta lo operativo: EV mínimo del locate (fijo o por rango de precio), activación de cada estrategia, topes (locates, seguridad, exposición), riesgo por entrada y por piramidación, y los botones. TODO lo que define la estrategia (condiciones, tipo de stop y sus variables, sesiones, EOD, reentradas, TP) se cambia en el backtester y se sobrescribe la exportación al bot. Las estrategias llegan al bot NORMALIZADAS: sin slippage, sin locates ni gastos, para que no haya fricción entre los datos del backtester y los del bot. Un dato, un sitio.

**Preguntas del inventario: CM1-CM4 respondidas el 21-sep (arriba).**
