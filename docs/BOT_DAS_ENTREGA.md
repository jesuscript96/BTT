# Bot de ejecución en DAS: entrega de la fase de código (27-sep-2026)

Este documento resume cómo ha quedado el paquete `backend/app/bot_das/`, cómo se ha verificado, cómo se arranca en fase sombra, qué queda por hacer y qué decisiones necesitan confirmación de Jaume. El diseño está en `docs/BOT_DAS_ARQUITECTURA.md` (§0-§14 y los cambios de §15) y las reglas en `docs/BOT_EJECUCION_REGLAS.md`.

## 1. Qué hay

- **Código:** `backend/app/bot_das/` (≈36.000 líneas): tres procesos independientes (`supervisor` → `vigilante` → `ejecutor`), un `decisor` puro que es el único que muta el estado, reglas puras por módulo (`precios`, `entrada`, `capital`, `stops`, `salidas`, `rechazos`, `halts`, `exclusiones`, `cisne_negro`, `locates`, `reconciliacion`, `vigilancia`), protocolo CMD API de DAS + cliente TCP + simulador de DAS, diario write-ahead, configuración del cuadro (fichero atómico con hash), avisos y comandos de Telegram, fuentes de señal (en proceso, por tubería desde `bot.py`, por grabación), referencia de Massive por REST y `herramientas/comprobar_das.py` para el primer día.
- **Tests:** `backend/tests/bot_das/` (≈32.000 líneas; 4.920 tests en verde, 1 saltado a propósito: el «dorado» hasta que exista un día grabado esperado). Sin red, sin DuckDB, sin credenciales; con un simulador de DAS en `127.0.0.1`.
- **Nada existente del repo se ha tocado**, salvo dos excepciones en `.gitignore` para que los `.json` del paquete y de sus fixtures se versionen. El bot de alertas, `bot.py` y los tres ficheros del motor compartido siguen intactos.
- **Commits en `sailor-rama-desarrollo`** (sin push): `c3a07c9b` construcción · `3f7f4f97` primera ronda de correcciones · `f66e1377` segunda ronda y §15 · el commit de esta entrega (tercera ronda, arreglos del director y este documento).

## 2. Cómo se ha verificado (por capas)

1. **Tests** de cada módulo (tablas de casos que citan la regla) y de integración con el simulador de DAS (entrada → fills → stops → stop dispara → limpieza; sombra sin ningún comando mutante; write-ahead antes del envío; reinicio a mitad de día sin reentrar ni recomprar).
2. **Revisión independiente** en 16 grupos (reglas del libro, riesgos de §13, contratos entre unidades, tests, seguridad, cobertura regla a regla): 152 hallazgos (8 críticos, 46 altos, 60 medios, 38 bajos), todos tratados.
3. **Tres rondas de corrección** por propietario de fichero, cada una seguida de **verificadores adversarios** que intentaron refutar cada arreglo (así salieron las regresiones que cerraron las rondas 2 y 3).
4. **Lectura dirigida del director (Fable)** sobre los caminos que tocan dinero: `stops.py` (banda, limpieza que nunca deja la cuenta larga, venta del exceso, plan idempotente), emisor del cliente (candado de sombra, purga por versión, orden dentro de cada serie), plan B del vigilante, salida de un halt por OPEN con reducción previa de los stops, guardas de las salidas por temporizador y la regla de «cerrar todo» con la cifra de DAS. Se encontró y corrigió un fallo que los tests no veían (las entradas del bot van con lado `SS` y la limpieza solo miraba `S`).
5. **Seguridad:** ninguna credencial ni cuenta real en código ni fixtures; sombra protegida por dos candados de código (`EnvioProhibido` antes de encolar + `ClienteSombra`) y por `BOT_DAS_PERMITIR_ORDENES=1` en el `.env` para las fases con dinero; sin `httpx` ni `websockets`; importar el paquete no abre red ni ficheros; los secretos se filtran del log y del diario por valor literal.

## 3. Lo que solo se puede comprobar con DAS real (primer día, `comprobar_das.py`)

Formato real del `%ORDER` de una STOPLMTP (campo Type) y si `REPLACE` conserva el pre/post; semántica del `share` en `REPLACE` (abierta o total; interruptor `stops.replace_share_es_abierta`, defecto «abierta»); qué recibe la conexión de vigilancia (`LOGIN … 1`) y si puede enviar (si no, el plan B es relanzar el ejecutor en 1 s); `GET SymStatus X` / `GET LDLU X` con símbolo; BP retenido por los dos stops (EP-3); PostOnly en SAGEREB/SMAT; ruta OPEN durante un halt; textos reales de rechazo (el catálogo es provisional); signo de `%POS` en cortos; si V y VWAP del `$Quote` incluyen el premercado; latencia real del socket.

## 4. Cómo arrancarlo en fase sombra

Variables del `.env` del VPS (leídas en la llamada, nunca al importar): `DAS_API_HOST` (defecto 127.0.0.1), `DAS_API_PORT`, `DAS_USUARIO`, `DAS_CLAVE`, `DAS_CUENTA`, `DAS_EXE` (opcional: ruta de DAS para que el supervisor lo lance), `BOT_DAS_DIR` (defecto `D:\bot_senales\bot_ejecucion\vivo\`), `BOT_DAS_FUENTE` (`tuberia` por defecto | `proceso` | `grabacion=<ruta>`), `BOT_DAS_AUTHKEY` (obligatoria para la tubería), `BOT_DAS_TUBERIA` (defecto 127.0.0.1:8765), `BOT_DAS_PING_URL` (opcional), `BOT_DAS_CHAT_IDS` (chat ids autorizados), `TELEGRAM_BOT_TOKEN_B` y `TELEGRAM_CHAT_ID_B` (grupo B, nuevo bot), `TELEGRAM_BOT_TOKEN_A`/`TELEGRAM_CHAT_ID_A` (opcional), `SMTP_HOST/PORT/USER/PASS/TO` (opcional), `SMS_PROVEEDOR` (opcional), `MASSIVE_BOT_API_KEY` (la de siempre), `BOT_ALERTS_API` (para el puente de configuración). **`BOT_DAS_PERMITIR_ORDENES=1` NO se pone hasta el canario.**

```bash
cd D:\Backtester\backend && .venv\Scripts\python.exe -m app.bot_das.config exportar
```
crea el fichero del cuadro (`config/bot_das_config.json`, fase `sombra`) a partir de las estrategias vigiladas del bot de alertas.

```bash
cd D:\Backtester\backend && .venv\Scripts\python.exe -m app.bot_das.supervisor
```
arranca los tres procesos (el ejecutor y el vigilante también se pueden arrancar sueltos con `-m app.bot_das.ejecutor` / `-m app.bot_das.vigilante`). El primer día: `-m app.bot_das.herramientas.comprobar_das` (cada paso pide confirmación por consola).

```bash
cd D:\Backtester\backend && .venv\Scripts\python.exe -m pytest tests/bot_das -q
```

## 5. Siguientes pasos

1. Credenciales del API de DAS (Sage): activación por el portal + cuestionario; al `.env` del VPS. Crear el bot y el grupo B de Telegram.
2. Primer día con DAS en sombra: `comprobar_das.py` pasos 1-9; rellenar `catalogo_rechazos.json`, `stops.tipo_esperado_en_order`, `tecnicos.get_con_simbolo`, `stops.replace_share_es_abierta`; guardar el `%ORDER` real como fixture.
3. Una semana de sombra con `FuenteGrabacion`/`FuenteEnProceso` (sin tocar `bot.py`); vigilar `senal_a_orden_ms` con y sin grupo A y la paridad de señales con el bot de alertas.
4. Las 8 líneas de `bot.py` con `BOT_DAS_ENLACE=1` (diferido §11.3) cuando la sombra esté limpia.
5. Canario mínimo (1-100 acciones, una estrategia) con `BOT_DAS_PERMITIR_ORDENES=1`.
6. Diferidos: pestaña «Ejecución» del cuadro (hoy: `estado/foto.json` y `estado/comandos.jsonl`), asistente de IA en Telegram, envío al grupo A desde el nuevo bot, proveedor de SMS, copia del diario fuera del VPS.
7. Preguntas pendientes a DAS/Sage: ¿`REPLACE` sobre STOPLMTP conserva el pre/post?; ¿la cuota del `SLPRICEINQUIRE` (1 cada 3 s) es global o por símbolo?; ¿`GET BP` ya descuenta el margen por símbolo?; pedir «Always allow unwind positions».

## 6. Riesgos residuales conocidos (no bloquean la sombra)

- El plazo de 60 s de una orden `SENDING` huérfana en el apagado nocturno se mide sobre `foto.json`, que un ejecutor recién relanzado puede tardar en reescribir.
- El tope T1 tras reabrir se vuelve a mirar una vez a los 2 s; si el primer print llega más tarde, lo cubre el control humano de R-F-05 por aviso.
- Los parámetros marcados PROVISIONAL (venta del exceso 2 %/3 vueltas, separación 2 s de los reintentos de stop, espera 1 s tras `GET BP`, tolerancia 0,5 % de la banda para contar un halt UP) se miden en sombra y canario.

## 7. Decisiones que necesitan tu confirmación (cada una lleva el DEFECTO ya implementado)

### A. Dinero y stops
1. **CONFIRMADA (28-sep).** Venta del exceso cuando la cuenta queda larga (R-C-11): sale a bid × (1 − 2 %) (Jaume: más margen; el límite solo acota lo peor, llena al mejor precio del libro) y se persigue al bid cada 1 s hasta 3 veces; después aviso máximo «vender a mano».
2. **CONFIRMADA (28-sep).** Salida de un halt por OPEN (R-F-01 esc. 2): al mandar la orden por Q acciones se REDUCEN antes principal y emergencia en Q (a 0 se cancelan) y se reponen si la orden se rechaza o no llena 2 s tras reabrir. Alternativa: dejar los stops y no usar OPEN. *Desde el 29-sep (decisión 36) se reduce EL stop de cada nivel, del L más alto al más bajo, por Q en total.*
3. **CONFIRMADA (28-sep).** T1 y T12 llevan el MISMO protocolo (DAS no los distingue; la duración ya no pasa a control humano). Halt H (T1/T12, sin hora de fin): la orden por OPEN es un LÍMITE a precio_parada × 3,5 (el tope del 250 %); si reabre más arriba no llena y pasa a control humano.
4. **CAMBIADA (28-sep, Jaume).** Cisne negro y halt a la vez: si el halt es T1/T12 (`H`, el único posible en premercado) manda su protocolo (límite a parada × 3,5) aunque el ticker esté en cisne negro; el «cierra el humano» de R-G-01 queda solo para la pausa LULD (`P`) de RTH. El bot recuerda si el halt era LULD para aplicar lo mismo al reabrir.
5. **SIN OBJETO (29-sep, decisión 36).** ~~Stops bajo la banda LULD: si el disparo del principal recortado queda ≥ el de la emergencia, se quita el principal (solo emergencia). Si solo se ACERCAN (p. ej. a +1,4 %), hoy se mantienen los dos. ¿Fijamos una distancia mínima (p. ej. 2 %) por debajo de la cual también se quita el principal?~~ Con un solo stop por nivel no hay par que se solape: bajo la banda el stop se recorta (disparo = min(L, banda × (1 − margen)), límite = disparo + 50 %) y ya está. Si dos niveles quedan con el mismo disparo recortado, siguen siendo dos órdenes con SUS acciones (nunca compran dos veces las mismas).
6. **CAMBIADA (29-sep, decisión 36).** Tras 5 rechazos seguidos al reponer un stop (R-C-03): con el stop único esas acciones quedan **SIN stop** (ya no hay emergencia detrás). El ejecutor deja de reponer el stop de ESE nivel (los de los demás niveles se siguen creando y reduciendo), avisa nivel **MÁXIMO** («STOP SIN PONER… el bot NO cierra») y pasa el ticker a **CONTROL HUMANO**; **no cierra a ciegas** (EP-1). El **vigilante** (plan B) lo sigue intentando: respeta la separación de 2 s y el tope de 5 rechazos en `stops.ventana_min`, y en cuanto esos rechazos salen de la ventana vuelve a intentarlo. ¿Vale, o el punto (3) del borrador (cerrar salvo subida > 100 %)?
7. Vigilante con el ejecutor muerto y la cuenta LARGA: vende él mismo el exceso (R-C-11 lo asigna también al vigilante).
8. TP parcial cuando nuestro lote es menor que el del backtest (capital, locates, fill a medias): se cierran las acciones LITERALES del evento (tope: lo que hay) y se anota la proporción. Alternativa: la misma PROPORCIÓN.
9. Día de «alto riesgo» (tope corto 0,5 × equity, 2c): hoy nunca se activa; el criterio es configurable (`entrada.alto_riesgo_si`, vacío). ¿Qué criterio?
10. Posición abierta A MANO con tu propio stop: el bot pone además su protección al 25 %. ¿Cuenta tu stop como cobertura?
36. **DECIDIDA (29-sep, Jaume): STOP ÚNICO (R-C-01 v4).** *Qué:* por cada nivel de stop L de la posición, UN stop residente STOPLMTP de compra con disparo EN L (redondeado arriba al tick) y límite L + `stops.limite_pct` (defecto **50**, sumado sobre L: L × 1,50; p. ej. L = 10 → 10,00 / 15,00); cantidad = las acciones cortas de los lotes de ese nivel. Desaparecen el principal (L + 3 %) y la emergencia (L + 13 % / L + 63 %), las claves `principal_limite_pct`, `emergencia_disparo_pct` y `emergencia_limite_pct` (un cuadro que las traiga NO carga: «cuadro de DOS stops… usa stops.limite_pct») y `Lote.principal_consumido`. *Por qué:* DAS reserva buying power por cada stop de compra residente (lo confirmaste) y el par complicaba halts, reducciones y reconciliación. *Estudio:* `D:\bot_senales\estudio_cisnes\40d/40e_fogonazos_un_stop*.py` (tabla en `BOT_EJECUCION_REGLAS.md`, «UN solo stop frente a DOS (29-sep)»): un único stop con disparo en L y límite ancho sale en la subida de los fogonazos igual que el par (98 %) con la misma cola máxima. *Consecuencias implementadas:* cisne negro = precio por encima del límite del PRIMER stop que salta (el del L más bajo) sin que haya llenado; ya no hay «principal rebasado» que reasignar; las compras de cierre (salida del halt, cierre humano) bajan los stops del L más alto al más bajo; las acciones que sobran sobre los lotes van al stop del L más alto; la protección de posiciones desconocidas y el `/stop` manual llevan también el límite a +50 %; el ensanche del límite en halts de premercado (E1-04) queda sin efecto (el límite ya es más ancho; se conserva como red para un límite estrecho); la cuenta y el bloqueo de R-C-03 van por nivel; D5 queda sin objeto y D6 cambia (arriba).
37. Con el stop único, D6 (5 rechazos al reponer el stop): la posición queda SIN stop → aviso máximo + el ticker pasa al humano + el vigilante sigue intentando reponerlo en cada pasada; no se cierra a ciegas. ¿Vale? (implementado así)
38. Cisne negro con stop único: se declara cuando el precio está por encima del límite (L + 50 %) del PRIMER stop que salta sin que haya llenado. ¿Confirmas la definición?
39. Ensanche del límite del stop en halts de PM (R-F-06 / E1-04): sin objeto con el límite +50 %; queda sin efecto. ¿OK?
40. Medir en sombra el coste del límite ancho en los stops NORMALES: contar los que llenan más de un 5 % sobre el nivel (referencia P12: con +3 % p90 +2,0 % y p99 +2,8 %; con +50 % p90 +4,6 % y p99 +16 %).
41. Respaldo por software del stop único. DECISIÓN PROVISIONAL (29-sep noche): de momento NO hay respaldo automático; solo el stop +50 % y, si se dispara y no llena, AVISO al humano. ABIERTA: simulación `40g_fogonazos_respaldo.py` (122 fogonazos sin arranque, 50 k): stop +50 % solo → media 2,59 %, máx 6,25 % de la cuenta; con respaldo instantáneo hasta +100 % → 2,92 % / 10,63 % (paga el pico en DGLY, SOAR, CBAY, ELTX y el precio vuelve en segundos); con retardo de 30 s → 2,76 % / 10,86 %. Argumento de Jaume para meterlo igualmente: un cisne negro es lo que nunca ha pasado; que se quede arriba puede ocurrir. ¿Aviso solo, o respaldo con retardo largo (≥ 1 min) como seguro contra el que no vuelve?
42. Límite de la protección de posiciones desconocidas y del `/stop` manual: ahora +50 % (antes +3 %). ¿Lo confirmas?
43. Un stop adoptado que no casa con ningún nivel (p. ej. uno viejo del vigilante): hoy se infiere como protección y convive con el stop del nivel (cobertura por encima de la posición hasta que la limpieza o R-C-11 lo resuelven). ¿Cancelarlo en el plan?
45. **DECIDIDA (30-sep, Jaume): UN SOLO NIVEL de stop por ticker.** Todas las estrategias llevan el mismo nivel de stop (definido dentro de cada una) y el stop único (+50 %) aglutina la posición total de cada momento (tras TPs y reducciones). Una señal cuyo nivel no coincide con el de los lotes vivos del ticker NO mete orden y avisa (comprobación 12b de `evaluar_senal`, motivo «nivel de stop distinto»). PENDIENTE para más adelante: cómo llevar varias estrategias con stops de distinto nivel.
44. Config del ensayo (`D:ot_senalesot_ejecucion\ensayo\configot_das_config.json`): le falta `locates.espera_intento_s` (10) para cargar; el trabajador no tenía permiso para escribirla. Añadirla a mano (y recalcular el hash) antes de repetir el ensayo.

### B. Entradas y salidas
11. B20 bis (distancia último-bid ≤ 5 %): arranca ENCENDIDA a 5 % (`null` la apaga).
12. PostOnly rechazado en el agregar: pasa directo al cruce de R-B-01 v3 (sin reintento ni pausa).
13. «Signal / Trailing / Time Limit / Escalera» del motor: como TP (60 s al punto medio, cruce con techo 3 %); «Partial TP (Hour)» y «(Time)» al ask con persecución.
14. Salida SL del motor con la posición aún abierta en DAS: no se persigue; se anota «divergencia» y aviso nivel 2.
15. «Cerrar todo» agotado (3 intentos al 5 %): el bot retira su última orden y repone los stops antes de avisarte.
16. Reentradas: con `max_reentries = N > 0` manda N aunque `accept_reentries` sea false; −1 → manda `accept_reentries`; 0 → ninguna.

### C. Locates
17. ≤ 30 acciones (o resto ≤ 30 en una recompra): hoy se compra 1 paquete de 100 igualmente. ¿O no se entra?
18. Varias rutas contestan al `SLPRICEINQUIRE`: hoy se compra en la PRIMERA cuyo EV compensa; tú dijiste «la más barata», que exige esperar una ventana corta (p. ej. 1 s). ¿Esperamos?
19. Ruta de locate que rechaza (Rejected/Declined): se para esa estrategia todo el día. ¿1-2 reintentos antes?
20. Pirámides con `times` > 1: se localiza la cantidad del nivel UNA vez.
21. Cuota del `SLPRICEINQUIRE` (1 cada 3 s): tratada como GLOBAL; con 10 tickers en el radar el último espera 30 s. ¿Preguntar a DAS si es por símbolo?
34. **DECIDIDA (29-sep, Jaume): regla MARGINAL del último paquete.** El último paquete de locates se compra si lo que ganan las acciones extra paga el paquete entero: extra × precio × EV/100 ≥ 100 × precio del locate (en el límite, compra). Sin precio del locate (primera consulta) → el 30 % de siempre. El primer paquete y el veredicto global (EV contra el fade del coste total) no cambian. Sustituye al 30 % de H6 cuando se conoce el precio (afecta a la 17).
35. **DECIDIDA (29-sep, Jaume): locates por FASES enlazados con la señal.** ESTRICTO (29-sep tarde): la PRIMERA señal principal del día de la pareja consume la única oportunidad aunque se descarte antes de mirar locates (retraso, pausa, exclusión); se anota `senal_principal_posterior` y se MIDE EN SOMBRA cuántas se pierden. Espera del intento único: `locates.espera_intento_s` = 10 s. A (radar, sin señal): cada 3 s y compra cuando compensa; se para al cerrar la ventana de entrada de la estrategia (fin de ventana + vela + caducidad), al salir del radar (30 min sin fila), con N cubierto o con el tope del 3 %; N se recalcula al precio actual con cada fila del radar. B (señal de entrada): con locates entra (parciales: con lo que hay y pasa a C); sin locates, UN intento en ese momento (compra solo «a tiro», precio ≥ señal × (1 − 3 %), el mismo 3 % de R-B-01, y si compensa); si no compra → pareja parada el día, `locate_perdida_entrada` y aviso 2. La PRIMERA señal principal del día de cada pareja es la única oportunidad: las siguientes se anotan `senal_perdida_por_locates` (salvo reentrada tras haber entrado y salido). C (dentro): sigue a por lo de las pirámides cada 3 s sin mirar «a tiro»; en la pirámide que no tiene todo, UN intento y entra con lo que haya (si no compra, parada el día). D (cerrada): sin consultas hasta una reentrada. Dudas resueltas por lo conservador: la señal espera su intento como mucho la caducidad (60 s); «salir del radar» = 30 min sin fila; cualquier salida (no solo el stop) hace legítima la reentrada, que decide `accept_reentries`/`max_reentries`.

### D. Operativa, cuadro y avisos
22. Estrategias nuevas en el fichero del cuadro (puente `config exportar`): llegan con `ejecutar=true` (plantilla). Recomiendo `ejecutar=false` hasta que las actives tú.
23. Estrategia con EV nulo en el cuadro: recibe el 4 % de la plantilla. ¿O no ejecuta?
24. Botones del cuadro: el bot ejecuta lo que llega por `comandos.jsonl` sin más confirmación (también /cerrar_todo). ¿La pestaña «Ejecución» pedirá «¿seguro?» antes de escribirlo?
25. Fichero del cuadro roto con último bueno en CANARIO/REAL: arranca en SOMBRA forzada con aviso 3. ¿O no arrancar?
26. En sombra el vigilante mira la cuenta REAL: una posición manual tuya daría un aviso 3 por minuto y ticker. ¿Lo bajamos a nivel 1 en sombra?
27. Un hijo que sale de forma ordenada sin que el supervisor lo pida (Ctrl+C): se deja parado con aviso 3. ¿O se relanza?
28. Estado hacia la app en fase 1: solo `estado/foto.json` y `estado/comandos.jsonl` (sin endpoints nuevos). ¿Suficiente para sombra y canario?
33. **DECIDIDA (29-sep, Jaume): R-M-03 por ticker.** Una orden o posición ajena (intervención humana) en X ya NO pausa todo el bot: X pasa a CONTROL_HUMANO (motivo «intervención humana», `intervencion_humana`), se protege lo descubierto como antes y aviso nivel 3 «X en manos del humano hasta /sigue X»; el resto de tickers sigue entrando. `/sigue X` devuelve X a NORMAL; `/sigue` a secas levanta todos. Además `/pausar X` (dos pasos) pausa solo las entradas y pirámides de X (stops y salidas siguen) y `/sigue X` la levanta.

### E. Datos y referencias
29. k de halts anteriores a la entrada del bot: hoy solo lo que DAS cuenta en RTH y el diario. ¿Fuente externa (lago/Massive)?
30. Splits del día: Massive REST (ya tenemos clave); sin dato no se excluye y se avisa. ¿O Nasdaq Daily List?
31. «Acum. Dollar Volume» del modo de seguridad = V × VWAP del `$Quote` de DAS. ¿Vale la aproximación?
32. Banda de OPA: «todo el rango de 30 min ≤ 1,5 % bajo el máximo de PM» (lo hecho) o «ventana de 30 min con rango propio ≤ 1,5 % después del máximo». Es solo un aviso.
