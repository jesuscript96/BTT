# Arquitectura definitiva del bot de ejecución en DAS — paquete `backend/app/bot_das/`

Fecha: 26-sep-2026. Estado: DOCUMENTO DE CONSTRUCCIÓN (lo que se codifica es esto; el libro de reglas `docs/BOT_EJECUCION_REGLAS.md` sigue siendo la fuente de las reglas y este documento dice DÓNDE vive cada una).

Fuentes cotejadas hoy sobre el disco (rutas absolutas, líneas comprobadas el 26-sep): `D:\Backtester\backend\app\services\bot_alerts_engine.py` (l.58-117 `Evento`; l.549-602 `estimar_por_estrategia`, filas SIN `strategy_id`; l.1208-1210 `acciones = float(round(acciones))`), `bot_alerts_feed.py` (l.177-187 `vela_de_mensaje`: `timestamp` = campo `s`, INICIO del minuto), `bot_alerts_alerta_proceso.py` (l.62-65: los `Evento` viajan picklados enteros, `entrada_idx` incluido), `bot_alerts_runner.py` (l.212-250 `estimacion_locates`), `bot_alerts_telegram.py` (l.30, 257, 402, 459: usa `httpx`, origen de la fuga de tokens de la memoria), `bot_alerts_calendario.py` (l.273-334 `festivo/media_sesion/hay_sesion/ultima_sesion/franja_de_mercado`), `locates_gate.py` (l.81-95 `ev_fijo_para_precio`; l.119-131 `fade_necesario_pct`/`paquetes_marginales` = `ceil(qty/100)`, NO la regla H6; l.159-190 `evaluar` sin coste acumulado), `portfolio_sim.py` (literales de `exit_reason`, l.745-2265: `Halt`, `Halt (atrapado)`, `BS`, `Signal`, `SL`, `Trailing`, `TP`, `Partial TP (EOD)`, `Partial TP (Time)`, `Partial TP (Hour)`, `Partial TP`, `BS Manual`, `Time Limit`, `Daily Limit`, `EOD`, `Pyramid Lot Stop`, `Escalera`, `Pyramid Reduce`), `D:\bot_senales\grabador.py` (l.26-40: `AM_AAAA-MM-DD.jsonl.gz`, SIN spread), `D:\bot_senales\bot_ejecucion\referencia_das_api_2026\manual_2026.txt` (L243-255 LOGIN, L618-624 STOPLMTP, L1436-1458 `%IORDER/%IPOS/%ITRADE`, L1472-1490 estados de conexión, L1701-1720 `%SLRET`), `backend/tests/conftest.py` (carga `.env`, `sys.path` a `backend`, importa `duckdb` y `app.database`; `tests/` NO tiene `__init__.py`). No existe `backend/app/bot_das/`. Nada de lo existente se modifica.

---

## 0. Resumen en 10 líneas

1. Un paquete nuevo `backend/app/bot_das/` con TRES procesos independientes (`supervisor` → `vigilante` → `ejecutor`), cada uno con cerrojo de instancia única y latido por fichero (R-J-04 v2); ningún fichero existente del repo se toca y el bot de alertas sigue igual.
2. **Un solo hilo decide**: el `Decisor` del ejecutor muta el estado; todas las reglas del libro son funciones PURAS `(estado, mensaje, ahora) → [Accion]` en `reglas/`, probadas con tablas de casos sin DAS.
3. La señal se calcula UNA vez (mismos `Evento` del hijo de alertas) y entra por una `FuenteSenales` con tres adaptadores: en proceso, por tubería (desde `bot.py`, bandera futura) y por grabación (replay).
4. DAS se habla por `protocolo.py` (puro, cubre las 29 ambigüedades del manual) y `cliente.py` (socket, cuotas, reconexión); un `simulador_das.py` habla el mismo protocolo para los tests.
5. Dinero: toda orden lleva token entero de 32 bits con origen/día/secuencia; el diario es write-ahead con `fsync` ANTES del `send` y se relee al arrancar (H-2); precios en `Decimal` y acciones en `int` con validación en el constructor.
6. Stops: tras cada fill, UN principal por nivel y UNA emergencia STOPLMTP (+3/+13/+63 sumados sobre L), plan idempotente que netea con las órdenes del vigilante y versión del objetivo por ticker para que ningún `REPLACE` viejo salga después de un fill.
7. El vigilante corre aparte con conexión watch (`LOGIN … 1`), repone el par si el ejecutor calla > 3 s, y avisa por ping externo cada 60 s.
8. Fases: `sombra` (prohibido a nivel de código enviar mutantes: `EnvioProhibido` + `ClienteSombra`) y `canario`/`real`, que además exigen `BOT_DAS_PERMITIR_ORDENES=1` en el `.env` del VPS.
9. Configuración del cuadro por fichero atómico con versión y hash (H-4), campos en caliente y solo-apagado (CM2), historial al diario (CM3); alarmas al grupo A y avisos del grupo B por una cola en hilo aparte (misma velocidad con o sin alarmas, medida).
10. Se DIFIERE: frontend de la pestaña «Ejecución», las 8 líneas de `bot.py`, el asistente IA de Telegram y el envío real al grupo A (queda codificado con interruptor apagado); todo lo demás se implementa en 7 lotes paralelizables (§12).

**Respuesta a las dos preguntas de Jaume (26-sep).** (a) Sí hace falta un vigilante de procesos INTERNO además del vigilante de posiciones de DAS: es el `supervisor` de R-J-04 (relanza en 1/2/5/10 s, mata al colgado a los 3 s, cerrojo de instancia única) más el ping externo de R-J-05; el `vigilante` de R-C-08 vigila POSICIONES y stops, no procesos. Son dos cosas distintas y las dos están en este diseño. (b) Si un día no hace falta el grupo A: se pone `alertas_grupo_a.activo=false` y `prealerta_simple=false` en el fichero del cuadro y quedan exactamente radar, ejecutor, diario, vigilante y avisos del grupo B; nada más cambia porque el grupo A ya está aislado en `avisos.py` detrás de un interruptor (R-M-05).

---

## 1. Árbol de ficheros y responsabilidad de cada uno

```
backend/app/bot_das/
├── __init__.py                 # VERSION = "2026.09.26" (R-O-01: va al diario en cada arranque). Nada más: importar no ejecuta nada.
├── tipos.py                    # TODO el modelo de datos: dataclasses, enums, constantes por defecto del libro, tick. Sin I/O. Lo importan todos.
├── protocolo.py                # CMD API de DAS, PURO: formatear comandos, parsear líneas, normalizar posiciones. Sin sockets, sin reloj.
├── cliente.py                  # Socket TCP a DAS: hilo lector, hilo emisor con cuotas y versión de serie, reconexión, candado de sombra (EnvioProhibido), ClienteSombra.
├── simulador_das.py            # Servidor TCP que habla el protocolo (tests, «DAS falso», emparejador con modelo de spread). `python -m app.bot_das.simulador_das`.
├── tokens.py                   # Tokens enteros de 32 bits: origen + día del año + secuencia; validación de propiedad por día.
├── reloj.py                    # Hora ET, reloj simulado para replay, desvío SNTP y veredicto (R-J-07).
├── cerrojo.py                  # Instancia única por fichero (R-J-04 c), latido por fichero (R-J-04 b) y HiloVigilado (hilos de borde que se relanzan).
├── diario.py                   # Write-ahead JSONL por día y POR PROCESO, lector tolerante, `reconstruir` puro (R-N-01, H-2, M6).
├── config.py                   # Fichero del cuadro: lectura atómica, hash, versión, caliente/apagado, hash del motor, puente provisional desde el backend (H-4, H-6, CM1-CM4).
├── avisos.py                   # Cola + hilo de envío; niveles 1/2/3; Telegram A y B (urllib, sin httpx), correo, SMS; FiltroSecretos (R-M-01/02/05, R-J-08, R-Q-01).
├── comandos.py                 # Telegram entrante y botones del cuadro: parseo, chat_id autorizados, dos pasos, «SI» (R-M-04, R-Q-01).
├── fuente_senales.py           # Protocol FuenteSenales + FuenteEnProceso, FuenteTuberia, FuenteGrabacion (importa pandas SOLO en las dos primeras clases, perezosamente).
├── enlace_bot_alertas.py       # El lado de bot.py: EnlaceEjecutor (cliente de la tubería). Integración futura con bandera BOT_DAS_ENLACE=1.
├── mercado_das.py              # Libro de $Quote incremental, estado del símbolo, LDLU, suscripciones con tope (R-A-06.3, R-C-09.3, R-F-02, A7).
├── referencia_massive.py       # REST de Massive (list_date, sic_code, type, splits) con caché diaria. NUNCA websocket (R-A-03, R-A-06.4).
├── decisor.py                  # El libro de posiciones y el despachador PURO: (EstadoBot, Mensaje, ahora) → [Accion]. H-5 (try/except por ticker) vive aquí.
├── ejecutor.py                 # Proceso ejecutor: una cola, hilos de borde vigilados, bucle, temporizadores, latido, fase, cerrojo, política del write-ahead.
├── vigilante.py                # Proceso vigilante: conexión watch, plan B, neteo, ping externo, cerrojo, diario propio.
├── supervisor.py               # Proceso raíz: ventana R-L-01, arranque DAS→vigilante→ejecutor, relanzar 1/2/5/10 s, colgado 3 s, disco, huérfanos.
├── herramientas/
│   ├── __init__.py
│   └── comprobar_das.py        # Guion del PRIMER DÍA con DAS real: cierra los 6 puntos abiertos de 2h (L196) y guarda fixtures crudas.
└── reglas/                     # LÓGICA PURA. Sin I/O, sin `time`, sin `datetime.now()`, sin logging. Una función por regla; cada una cita su regla en el docstring.
    ├── __init__.py
    ├── precios.py              # Decimal: ticks, redondeos, punto medio hacia arriba, techos, tramo y ruta por hora (R-B-01, regla 612, tabla de rutas).
    ├── entrada.py              # Guardas (15, en orden) + máquina de estados de la entrada v3 (R-B-01/02/03/04/05, B11-B20 bis, R-A-01, R-I-04, R-E-01, R-C-09, R-F-04 b).
    ├── stops.py                # Niveles STOPLMTP, conjunto deseado, plan idempotente con versión, limpieza R-C-11, reasignación, protección (R-C-01 v3, R-C-04/06/07/10.4/11, R-F-02).
    ├── salidas.py              # Clasificación COMPLETA de exit_reason, hora/EOD, TP parcial, cerrar todo, prioridad, reentradas (R-D-02/03/04/06/07/08, D10/D13, R-L-01, R-E-03).
    ├── halts.py                # k, banda, decisión de reapertura, OPEN un minuto antes con guardia, PM, T1/T12 (R-F-01..06, R-G-02, B18, EP-2).
    ├── cisne_negro.py          # Activación, informe de 16 campos, cadencia 1×5 luego 5, límites (R-G-01, R-G-03).
    ├── rechazos.py             # Catálogo, 2 reintentos, pausa por ticker, cubierta/no cubierta, reintento de stop (R-B-07, R-C-03, EP-1).
    ├── catalogo_rechazos.json  # Textos de Send_Rej conocidos → tratamiento (tabla C de la KB; se completa en canario).
    ├── capital.py              # Margen por tramo, BP, tope 1×/0,5×, orden de llegada (2c, R-I-01, R-E-02).
    ├── locates.py              # Paquetes 100/30 % (H6), EV con coste TOTAL acumulado (solo ev_fijo_para_precio), escalonado, cerrojo, tope 3 %, parcial (R-H-01..05, EP-9).
    ├── exclusiones.py          # SPAC/IPO/split/lista negra/OPA, símbolo que no casa (R-A-03 v2, R-A-04).
    ├── reconciliacion.py       # Diario+fills vs DAS: 5 casos, barrido adaptativo, caducidad (R-C-10, R-K-01/02/03, R-M-03).
    └── vigilancia.py           # Lo que comprueba el vigilante: un principal + una emergencia, plan B, bucles, margen, fallback (R-C-07/08/11, R-H-02/03, 2c, R-J-05).

backend/tests/bot_das/            # SIN __init__.py (como tests/): pytest inserta este directorio en sys.path y `import canal_falso` funciona.
├── conftest.py                 # Fixtures propias: reloj simulado, config de ejemplo cargada, simulador en 127.0.0.1:0, directorio temporal del bot. NUNCA usa `real_db`.
├── canal_falso.py              # Grabadora de acciones que implementa el Protocol CanalOrdenes (para probar reglas/decisor sin simulador ni socket).
├── fixtures/
│   ├── lineas_das.txt          # Una línea cruda por caso (§10): %ORDER 15/19 campos y con tipo «SLP: 2.97 2.99», %OrderAct notas vacías/número final, $Quote parcial, $IssueStatus sin TA, %SLRET con/sin cuenta, SLRouteMinChargeRet con/sin $, las 12 líneas de conexión, %IORDER, %IPOS, %ITRADE, #buyingpower bp,nbp.
│   ├── config_ejemplo.json     # El fichero del cuadro con TODOS los defaults vigentes (§7).
│   ├── AM_recorte.jsonl.gz     # 3 tickers × 40 velas del formato de grabador.py.
│   ├── guion_replay_ejemplo.json # Modelo de spread + halts + fills declarados para el replay (§10).
│   ├── diario_medio_dia_ejecutor.jsonl / diario_medio_dia_vigilante.jsonl
│   └── esperado_AAAA-MM-DD.jsonl # «versión anterior» del test dorado (se añade con el primer día grabado).
├── test_das_tipos.py, test_das_tokens.py, test_das_reloj_cerrojo.py, test_das_protocolo.py, test_das_cliente.py, test_das_simulador.py,
├── test_das_diario.py, test_das_config.py, test_das_avisos.py, test_das_comandos.py, test_das_mercado.py, test_das_referencia.py,
├── test_das_reglas_precios.py, test_das_reglas_entrada.py, test_das_reglas_stops.py, test_das_reglas_salidas.py, test_das_reglas_halts.py,
├── test_das_reglas_cisne_negro.py, test_das_reglas_rechazos.py, test_das_reglas_capital.py, test_das_reglas_locates.py, test_das_reglas_exclusiones.py,
├── test_das_reglas_reconciliacion.py, test_das_reglas_vigilancia.py, test_das_decisor.py, test_das_fuente_senales.py, test_das_ejecutor.py,
├── test_das_vigilante.py, test_das_supervisor.py, test_das_seguridad.py (secretos, sombra, pandas) y test_das_replay_dias.py (slow).
```

Nombres de test con prefijo `test_das_` para no chocar por nombre base con los `test_bot_alerts_*` de `tests/` (pytest sin `__init__.py` exige nombres base únicos). El `conftest.py` raíz importa `duckdb` y `app.database` al cargar; es inofensivo (no abre conexión al importar) pero ningún test de `bot_das/` puede pedir `real_db`.

Disco del bot (fuera de git, `BOT_DAS_DIR`, defecto `D:\bot_senales\bot_ejecucion\vivo\`): `config/bot_das_config.json` (lo escribe la app o el puente `config exportar`), `config/ultimo_bueno.json`, `diario/diario_ejecutor_AAAA-MM-DD.jsonl`, `diario/diario_vigilante_AAAA-MM-DD.jsonl`, `estado/latido_ejecutor`, `estado/latido_vigilante`, `estado/latido_supervisor`, `estado/cerrojo_{ejecutor,vigilante,supervisor}.lock`, `estado/pid_{…}`, `estado/comandos.jsonl` (botones del cuadro), `estado/foto.json` (panel 4.4, lo publica el ejecutor cada 2 s), `estado/orden_supervisor.jsonl` (peticiones del vigilante al supervisor: «relanza el ejecutor»), `cache/referencia_AAAA-MM-DD.json`, `logs/bot_das_{proceso}_AAAA-MM-DD.log`.

Lo que se REUTILIZA del bot de alertas importándolo (nunca copiándolo): `bot_alerts_engine.Evento` (viaja picklado), `bot_alerts_cliente.id_evento` (R-A-05), `bot_alerts_runner.RunnerAlertas` (solo dentro de `FuenteEnProceso`/`FuenteGrabacion`), `bot_alerts_telegram.agrupar/formatear_grupo` (formato del grupo A: funciones puras), `bot_alerts_calendario.hay_sesion/franja_de_mercado/media_sesion`, `bot_alerts_diario.Diario` (handler de log para el panel), `locates_gate.ev_fijo_para_precio/rangos_ev_normalizados` (NO `evaluar`, ver §3 `reglas/locates`). NO se reutiliza `ProcesoHijo` para ejecutor ni vigilante: son procesos independientes con supervisor propio (R-J-04), no hijos de `bot.py`.

---

## 2. `tipos.py` completo

```python
"""Todo lo que viaja entre módulos del bot de ejecución en DAS.

QUÉ HACE. Dataclasses, enumeraciones y constantes por defecto del libro de
reglas. Sin lógica salvo la validación de los constructores y la regla del
tick, que es la única aritmética que necesita todo el mundo.

POR QUÉ EN UN SOLO FICHERO. El decisor, el diario, el vigilante y los tests
hablan del mismo objeto; un campo nuevo se ve aquí y en ningún otro sitio.
Los módulos de `reglas/` importan de aquí y de nada más.

LAS TRAMPAS.
  * Precios en `Decimal`, nunca `float`: 10 * 1.03 = 10.299999… y DAS recibe
    «10.3» o nada. Todo precio que entra por el socket se construye con
    `Decimal(cadena)` y todo el que sale pasa por `protocolo.formatear_precio`,
    que LANZA si no está al tick (injerto A §8.1).
  * Acciones en `int`. El `Evento` del motor trae `acciones` como float
    redondeado (`bot_alerts_engine.py` l.1208-1210); la conversión a int se
    hace UNA vez en `reglas.entrada.qty_final` y `OrdenNueva` rechaza lo demás.
  * `neta` de una posición es SIGNADA en todo el bot: corto = negativo. Lo que
    DAS envíe en `%POS` (signo no documentado) lo normaliza `protocolo`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
from enum import Enum, IntEnum
from typing import Any, Optional

# ── constantes por defecto del libro (VIGENTES; los defaults del cuadro salen de aquí) ──
STOP_PRINCIPAL_LIMITE_PCT = Decimal("3")        # R-C-01 v3 (23-sep): límite del principal = L + 3 %
STOP_EMERGENCIA_DISPARO_PCT = Decimal("13")     # R-C-01 v3: disparo de la emergencia = L + 13 %
STOP_EMERGENCIA_LIMITE_PCT = Decimal("63")      # R-C-01 v3: límite de la emergencia = L + 63 %
STOP_PROTECCION_PCT = Decimal("25")             # R-C-10 (4): 20-30 % para posiciones desconocidas
STOP_MARGEN_BAJO_LIMIT_UP_PCT = Decimal("1.5")  # R-F-02: 1-2 % bajo la banda
ENTRADA_AGREGAR_S = 60                          # R-B-01 v3: hasta 60 s agregando en el punto medio
ENTRADA_TOPE_CAIDA_BID_PCT = Decimal("3")       # R-B-01 v3: no cruzar si el bid cayó > 3 %
ENTRADA_CRUCE_BAJO_BID_PCT = Decimal("0.5")     # R-B-01 v3: cruzar a bid × (1 − 0,5 %)
ENTRADA_CADUCIDAD_S = 60                        # R-B-04
ENTRADA_RETRASO_MAX_PCT = Decimal("1")          # R-A-01 (provisional)
ENTRADA_DISTANCIA_ULTIMO_BID_PCT = Decimal("5") # B20 bis (PROVISIONAL, pregunta 1 a Jaume)
ENTRADA_REINTENTOS_RECHAZO = 2                  # R-B-07
SALIDA_ANTICIPO_S = 60                          # R-D-08 / R-D-02
EOD_COMPROBAR_DESPUES_S = 30                    # R-D-02
TP_TECHO_ASK_PCT = Decimal("3")                 # R-D-03 v2
CERRAR_TODO_TECHO_PCT = Decimal("5")            # R-D-06
CERRAR_TODO_REINTENTOS = 2                      # R-D-06
PERSEGUIR_ASK_MAX = 3                           # F5 (corrección del juez): a la hora, como mucho 3 REPLACE de precio
HALT_K_MAX = 3                                  # R-F-01
HALT_DISTANCIA_BANDA_K2_PCT = Decimal("4")      # R-F-01: 3-5 %
HALT_PRIMERA_VELA_MAX_PCT = Decimal("6")        # R-F-01 esc. 2 / R-F-03 / R-F-04
HALT_T1_SUBIDA_MAX_PCT = Decimal("250")         # R-F-05
HALT_ENVIAR_ANTES_FIN_S = 60                    # R-F-01 (22/24-sep)
LOCATES_TOPE_GASTO_PCT = Decimal("3")           # R-H-03
LOCATES_UMBRAL_ULTIMO_PAQUETE_PCT = Decimal("30")  # H6
LOCATES_INQUIRE_S = 3.0                         # manual L2000 (1 cada 3 s)
MODO_SEGURIDAD_PRECIO_MIN = Decimal("5")        # R-I-04
MODO_SEGURIDAD_DOLLAR_VOLUME_MIN = Decimal("2000000")  # R-I-04
FEED_PREALERTA_S = 30                           # R-J-01
FEED_EMERGENCIA_S = 60                          # R-J-01
DAS_RECONEXION_S = (2.0, 4.0, 8.0, 16.0)        # R-J-02 (luego 30 s sin parar)
DAS_RECONEXION_TOPE_S = 30.0
DAS_AVISO_CADA_S = 300                          # R-J-02 (3)
RELANZAR_S = (1.0, 2.0, 5.0, 10.0)              # R-J-04 v2 (luego cada 10 s)
LATIDO_S = 1.0                                  # R-J-04 v2
COLGADO_S = 3.0                                 # R-J-04 v2
PING_EXTERNO_S = 60                             # R-J-05
PING_FALLOS_ALARMA = 3                          # R-J-05
RELOJ_NEGARSE_S = 2.0                           # R-J-07
RELOJ_AVISO_S = 0.5                             # R-J-07
DISCO_MIN_GB = 5                                # R-J-07
BARRIDO_TRAS_FILL_S = 1.0                       # R-K-01 (21-sep)
BARRIDO_CON_POSICIONES_S = 2.0
BARRIDO_SIN_NADA_S = 10.0
BARRIDO_VENTANA_TRAS_FILL_S = 60.0
RECONCILIACION_CADUCA_S = 30.0                  # R-K-03
BS_PRIMEROS_INFORMES = 5                        # R-G-01 v2 (22-sep): 1 min × 5, luego cada 5 min
BS_CADENCIA_INICIAL_S = 60
BS_CADENCIA_DESPUES_S = 300
FILTRO_PRINTS_MS = 20                           # R-A-06
IPO_DIAS = 30                                   # R-A-03 v2
SPAC_SIC = ("6770",)                            # R-A-03 v2
OPA_BANDA_MIN = 30                              # R-A-03 v2
OPA_RANGO_MAX_PCT = Decimal("1.5")
OPA_DOLARES_MIN = Decimal("100000")
STOP_REINTENTOS = 5                             # R-C-03 (1)
STOP_VENTANA_MIN = 5                            # R-C-03 (3) — solo se registra, NO se cierra (prima R-B-07/EP-1)
STOP_COMPROBACION_S = 1.0                       # R-C-04
STOP_DEBOUNCE_S = 0.3                           # técnico (F1.6): coalescer REPLACE de stops; NUNCA en el primer fill
PLAN_B_LATIDO_S = 3.0                           # vigilancia: actúa si el ejecutor calla > 3 s
PLAN_B_DESCUBIERTA_S = 5.0                      # vigilancia: o si una posición lleva > 5 s descubierta con el ejecutor vivo
MAX_LV1 = 100                                   # manual L1996: símbolos Lv1 por defecto
COLA_AVISOS_TOPE = 10_000
COLA_SALIDA_TOPE = 1_000

# ── enumeraciones ──────────────────────────────────────────────────────
class Fase(str, Enum):
    SOMBRA = "sombra"; CANARIO = "canario"; REAL = "real"        # R-O-03 (demo DESCARTADA 24-sep)

class Lado(str, Enum):
    COMPRA = "B"; VENTA = "S"; CORTO = "SS"                       # manual L671-694

class TipoOrden(str, Enum):
    LIMITE = "LMT"; MERCADO = "MKT"; STOP_LIMITE_PP = "STOPLMTP"  # manual L618-624

class EstadoOrden(str, Enum):                                     # manual L379-405, conjunto CERRADO
    CLOSED = "Closed"; HOLD = "Hold"; SENDING = "Sending"; ACCEPTED = "Accepted"; CANCELED = "Canceled"
    REJECTED = "Rejected"; EXECUTED = "Executed"; PARTIAL = "Partial"; TRIGGERED = "Triggered"; DESCONOCIDO = "?"

class Proposito(str, Enum):        # por qué existe una orden nuestra (va al diario; el vigilante lo infiere si no lo tiene)
    ENTRADA_AGREGAR = "entrada_agregar"; ENTRADA_CRUCE = "entrada_cruce"
    STOP_PRINCIPAL = "stop_principal"; STOP_EMERGENCIA = "stop_emergencia"; STOP_PROTECCION = "stop_proteccion"
    TP_AGREGAR = "tp_agregar"; TP_CRUCE = "tp_cruce"
    HORA_AGREGAR = "hora_agregar"; HORA_ASK = "hora_ask"            # R-D-08 (salida por hora y EOD)
    SALIDA_MOTOR_AGREGAR = "salida_motor_agregar"; SALIDA_MOTOR_CRUCE = "salida_motor_cruce"  # Signal/Trailing/Time Limit (pregunta 3 a Jaume)
    HALT_OPEN = "halt_open"; HALT_PM_LIMITE = "halt_pm_limite"; HALT_BANDA = "halt_banda"
    VENTA_EXCESO = "venta_exceso"; CIERRE_HUMANO = "cierre_humano"; CIERRE_REINICIO = "cierre_reinicio"  # R-E-03
    DESCONOCIDA = "desconocida"

class Origen(IntEnum):             # primer dígito del token
    EJECUTOR = 1; VIGILANTE = 2; EJECUTOR_LOCATE = 3

class Nivel(IntEnum):              # R-M-01
    INFO = 1; AVISO = 2; MAXIMO = 3

class Grupo(str, Enum):            # R-M-05
    A = "A"; B = "B"

class EstadoLote(str, Enum):
    ABRIENDO = "abriendo"; ABIERTO = "abierto"; CERRANDO = "cerrando"; CERRADO = "cerrado"; CANCELADO = "cancelado"

class FaseIntento(str, Enum):
    AGREGANDO = "agregando"; CANCELANDO = "cancelando"; CRUZANDO = "cruzando"; TERMINADO = "terminado"

class ClaseSalida(str, Enum):      # ver reglas.salidas.clasificar (cubre TODOS los literales de portfolio_sim.py)
    TP = "tp"; HORA = "hora"; EOD = "eod"; STOP = "stop"; STOP_LOTE = "stop_lote"; REDUCE = "reduce"
    MOTOR = "motor"                # Signal / Trailing / Time Limit / Escalera / "?" → como R-D-03 (pregunta 3 a Jaume)
    HALT = "halt"; BS = "bs"; DAILY_LIMIT = "daily_limit"          # Daily Limit → se ignora + aviso (I1: sin cortacircuito)

class EstadoTicker(str, Enum):
    NORMAL = "normal"; PAUSADO = "pausado"; BS = "cisne_negro"; SIN_SIMBOLO = "sin_simbolo"; HALT = "halt"; CONTROL_HUMANO = "control_humano"

# ── tick: la única aritmética compartida (regla 612 y < 1 $ a 0,0001) ──
TICK_GE_1 = Decimal("0.01")
TICK_LT_1 = Decimal("0.0001")

def tick_de(precio: Decimal) -> Decimal:
    """Tamaño de tick: ≥ 1 $ céntimos; < 1 $ diezmilésimas."""
    return TICK_GE_1 if precio >= 1 else TICK_LT_1

def en_tick(precio: Decimal) -> bool:
    """True si `precio` es múltiplo exacto de su tick (lo exige OrdenNueva)."""
    return precio > 0 and (precio % tick_de(precio)) == 0

def al_tick(precio: Decimal, arriba: bool) -> Decimal:
    """Redondea al tick hacia ARRIBA (venta al punto medio) o ABAJO (compra)."""
    t = tick_de(precio)
    return (precio / t).to_integral_value(rounding=ROUND_CEILING if arriba else ROUND_FLOOR) * t

# ── lo que llega de DAS ya parseado (protocolo.py) ────────────────────
@dataclass(frozen=True)
class MensajeDAS:                  # base; `cruda` SIEMPRE se conserva para el diario
    cruda: str

@dataclass(frozen=True)
class MsgOrden(MensajeDAS):        # %ORDER / %IORDER (manual L343-405); 15 o 19 campos
    id: int; token: Optional[int]; ticker: str; lado: str; tipo: str; qty: int; lvqty: int; cxlqty: int
    precio: Decimal; ruta: str; estado: EstadoOrden; hora: str; origoid: int; cuenta: str; trader: str
    order_src: Optional[str]; tif: Optional[str]; pref: Optional[str]; watch: bool

@dataclass(frozen=True)
class MsgOrderAct(MensajeDAS):     # %OrderAct (L434-494); `lado` normalizado a B/S/SS; `notas` texto libre
    id: int; accion: str; lado: str; ticker: str; qty: int; precio: Decimal; ruta: str; hora: str; notas: str; token: Optional[int]

@dataclass(frozen=True)
class MsgTrade(MensajeDAS):        # %TRADE (L495-539, 8 u 11 campos) y %ITRADE (L1444-1458: OTRO orden de campos, rama de parser propia)
    id: int; ticker: str; lado: str; qty: int; precio: Decimal; ruta: str; hora: str; id_orden: int
    liq: Optional[str]; ecn_fee: Optional[Decimal]; pl: Optional[Decimal]; cuenta: Optional[str]; trader: Optional[str]; watch: bool

@dataclass(frozen=True)
class MsgPos(MensajeDAS):          # %POS / %IPOS (L256-323). `qty_cruda` tal cual; `neta` SIGNADA (corto < 0) por protocolo.normalizar_pos
    ticker: str; tipo: int; qty_cruda: int; neta: int; avg: Decimal; init_qty: int; init_precio: Decimal
    realizado: Decimal; creada: str; no_realizado: Optional[Decimal]; watch: bool

@dataclass(frozen=True)
class MsgQuote(MensajeDAS):        # $Quote: PARCHE (L1268-1269), solo las claves presentes; valores sin convertir
    ticker: str; campos: dict[str, str]

@dataclass(frozen=True)
class MsgBP(MensajeDAS):
    bp: Decimal; bp_overnight: Decimal

@dataclass(frozen=True)
class MsgShortInfo(MensajeDAS):    # $SHORTINFO (L1017-1030); reg_sho opcional
    ticker: str; shortable: bool; short_size: int; marginable: bool; tasa_larga: Decimal; tasa_corta: Decimal; prohibido: bool; reg_sho: Optional[bool]

@dataclass(frozen=True)
class MsgStInfoEx(MensajeDAS):     # $STINFOEX (L1064-1078): texto libre → {"ConcLong": 200, "ConcShr": 50}
    ticker: str; valores: dict[str, Decimal]; texto: str

@dataclass(frozen=True)
class MsgLDLU(MensajeDAS):
    ticker: str; limit_down: Decimal; limit_up: Decimal

@dataclass(frozen=True)
class MsgIssueStatus(MensajeDAS):  # $IssueStatus / $SymStatus (L1101-1133); TA ausente = normal
    ticker: str; ssr: Optional[bool]; ta: Optional[str]; tat: Optional[str]

@dataclass(frozen=True)
class MsgAccountInfo(MensajeDAS):  # $AccountInfo (L1143-1158), 10 números
    open_eq: Decimal; curr_eq: Decimal; realizado: Decimal; no_realizado: Decimal; net: Decimal
    htb: Decimal; sec: Decimal; finra: Decimal; ecn: Decimal; comision: Decimal

@dataclass(frozen=True)
class MsgSLRet(MensajeDAS):        # %SLRET (L1701-1720); cuenta opcional; notas con espacios
    tipo: int; ticker: str; precio: Decimal; tamano: int; ruta: str; notas: str; cuenta: Optional[str]

@dataclass(frozen=True)
class MsgSLOrder(MensajeDAS):      # %SLOrder (L1722-1795)
    id: int; ticker: str; pedidas: int; abiertas: int; localizadas: int; precio: Decimal; estado: str; ruta: str; hora: str
    limite: Optional[Decimal]; token: Optional[int]; notas: str

@dataclass(frozen=True)
class MsgSLReuse(MensajeDAS):
    ticker: str; reutilizable: bool

@dataclass(frozen=True)
class MsgSLAvail(MensajeDAS):
    cuenta: str; ticker: str; disponibles: int

@dataclass(frozen=True)
class MsgSLMinCharge(MensajeDAS):  # con o sin `$` (L1833-1836)
    ruta: str; minimo: Decimal

@dataclass(frozen=True)
class MsgRouteStatus(MensajeDAS):
    ruta: str; habilitada: bool

@dataclass(frozen=True)
class MsgConexion(MensajeDAS):     # las 12 líneas de L1472-1490, comparadas ENTERAS
    servidor: str; evento: str     # ("OrderServer", "Lost Connection")

@dataclass(frozen=True)
class MsgMarcador(MensajeDAS):     # "#POS", "#POSEND", "#Order", "#OrderEnd", "#Trade", "#TradeEnd", "#SLOrder", "#SLOrderEnd", "#buyingpower"
    nombre: str

@dataclass(frozen=True)
class MsgTS(MensajeDAS):           # $T&S (L1317-1360); condicion como entero (presunción, se valida en canario)
    ticker: str; precio: Decimal; volumen: int; flag: str; hora: str; bolsa: str; lado: str; condicion: int

@dataclass(frozen=True)
class MsgBar(MensajeDAS):          # $Bar (L1373-1435): High Low Open Close (en ese orden)
    ticker: str; cuando: str; high: Decimal; low: Decimal; open: Decimal; close: Decimal; volumen: int; min_type: Optional[int]

@dataclass(frozen=True)
class MsgIntMsg(MensajeDAS):       # $INTMSG multilínea acumulado por el parser con estado
    campos: dict[str, str]

@dataclass(frozen=True)
class MsgInformativo(MensajeDAS):  # ECHO, CLIENT, $TopLst, $Lv2 y cualquier `#…` no listado: se registran y nada más
    palabra: str

@dataclass(frozen=True)
class MsgDesconocido(MensajeDAS):
    palabra: str

# ── lo que envía el bot (protocolo.py lo serializa) ────────────────────
@dataclass(frozen=True)
class OrdenNueva:
    token: int; lado: Lado; ticker: str; ruta: str; qty: int; tipo: TipoOrden
    precio: Optional[Decimal] = None; stop: Optional[Decimal] = None   # STOPLMTP: stop = disparo, precio = límite
    tif: str = "DAY+"; post_only: bool = False; pref: Optional[str] = None
    proposito: Proposito = Proposito.DESCONOCIDA; lote_id: Optional[str] = None; nivel: Optional[Decimal] = None
    version: int = 0                # versión del objetivo del ticker (stops); el emisor descarta versiones viejas

    def __post_init__(self) -> None:
        """Injerto A §8.2: nada sale hacia DAS con acciones fraccionarias ni precios fuera del tick."""
        if type(self.qty) is not int or self.qty <= 0:
            raise ValueError(f"qty debe ser int > 0, no {self.qty!r}")
        if not (-(2**31) <= self.token <= 2**31 - 1):
            raise ValueError(f"token fuera de int32: {self.token}")
        if self.tipo is TipoOrden.LIMITE and (self.precio is None or not en_tick(self.precio)):
            raise ValueError(f"límite fuera del tick: {self.precio}")
        if self.tipo is TipoOrden.STOP_LIMITE_PP:
            if self.stop is None or self.precio is None or not en_tick(self.stop) or not en_tick(self.precio):
                raise ValueError(f"STOPLMTP fuera del tick: stop={self.stop} límite={self.precio}")
            if self.lado is Lado.COMPRA and self.precio < self.stop:
                raise ValueError("compra STOPLMTP con límite por debajo del disparo")
        if self.tipo is TipoOrden.MERCADO and (self.precio is not None or self.stop is not None):
            raise ValueError("MKT no lleva precio")
        if self.post_only and self.tipo is not TipoOrden.LIMITE:
            raise ValueError("PostOnly solo con límite")

# ── mercado visto desde DAS (mercado_das.py) ───────────────────────────
@dataclass
class Cotizacion:
    ticker: str
    bid: Optional[Decimal] = None; ask: Optional[Decimal] = None; bsz: Optional[int] = None; asz: Optional[int] = None
    last: Optional[Decimal] = None; volumen: Optional[int] = None; vwap: Optional[Decimal] = None
    hi: Optional[Decimal] = None; lo: Optional[Decimal] = None
    hora_servidor: Optional[str] = None; actualizada_en: Optional[float] = None   # monotónico

@dataclass
class EstadoSimbolo:
    ticker: str
    ssr: Optional[bool] = None; ta: Optional[str] = None; tat: Optional[str] = None
    limit_down: Optional[Decimal] = None; limit_up: Optional[Decimal] = None; consultado_en: Optional[float] = None
    halt_desde: Optional[datetime] = None; k_halts_up: int = 0; precio_parada: Optional[Decimal] = None   # R-F-01
    orden_open_enviada: bool = False                                                                     # injerto A §8.23
    shortable: Optional[bool] = None; tasa_corta: Optional[Decimal] = None; reg_sho: Optional[bool] = None

# ── señal (fuente_senales.py) ──────────────────────────────────────────
@dataclass(frozen=True)
class Senal:
    clase: str                     # "evento" | "radar" | "hidratado" | "latido_feed" | "dia_nuevo"
    ticker: Optional[str]; id: Optional[str]                    # id = bot_alerts_cliente.id_evento(evento) (R-A-05)
    evento: Any = None             # bot_alerts_engine.Evento, tal cual (entrada_idx INCLUIDO: viaja picklado)
    momento: Any = None; recibida_en: float = 0.0; recuperada: bool = False
    estimacion: Optional[list] = None   # radar: filas de runner.estimacion_locates + "strategy_id" añadido por la fuente
    precio_radar: Optional[Decimal] = None
    feed: Optional[dict] = None         # latido_feed: {"ultima_vela_en": epoch, "vivo": bool}
    origen: str = "tuberia"        # "tuberia" | "proceso" | "grabacion"

# ── estado del ejecutor (decisor.py) ───────────────────────────────────
@dataclass
class Orden:                       # nuestra vista de una orden (token = clave; el id de DAS llega después)
    token: int; ticker: str; lado: Lado; tipo: TipoOrden; qty: int; precio: Optional[Decimal]; stop: Optional[Decimal]; ruta: str
    proposito: Proposito; lote_id: Optional[str]; nivel: Optional[Decimal]; origen: Origen
    id_das: Optional[int] = None; estado: EstadoOrden = EstadoOrden.SENDING; lvqty: int = 0; llenas: int = 0; cxlqty: int = 0
    tipo_das_crudo: Optional[str] = None; enviada_en: float = 0.0; ultima_act: float = 0.0; notas: str = ""
    version: int = 0; intentos: int = 0; primer_intento_en: float = 0.0

@dataclass
class Fill:
    id_trade: int; token: Optional[int]; id_orden: Optional[int]; ticker: str; lado: str; qty: int; precio: Decimal
    ruta: str; hora: str; liq: Optional[str]; ecn_fee: Optional[Decimal]; simulado: bool = False

@dataclass
class Lote:                        # una estrategia dentro de un ticker (R-B-03: N lotes, una orden)
    id: str                        # = id_evento de la entrada: ticker|strategy_id|momento[:19]|entrada
    strategy_id: str; estrategia: str; ticker: str; direccion: str
    pedidas: int; llenas: int = 0; precio_medio: Decimal = Decimal("0"); nivel_stop: Optional[Decimal] = None
    riesgo_usd: Decimal = Decimal("0"); estado: EstadoLote = EstadoLote.ABRIENDO; reentrada_n: int = 0; entrada_idx: Optional[int] = None
    nivel_piramide: Optional[int] = None; hora_salida: Optional[str] = None; eod: Optional[str] = None
    tp_pendiente: int = 0; principal_consumido: bool = False   # R-C-11 (c): tras un fill del principal no se repone
    version_estrategia: str = ""   # R-E-03: hash de la definición con la que nació el lote

@dataclass
class IntentoEntrada:              # máquina de estados de R-B-01 v3 para UN ticker
    ticker: str; lotes: list[str]; qty_total: int; bid_senal: Decimal; ask_senal: Decimal; precio_senal: Decimal
    t_cierre_vela: float; t_limite: float
    fase: FaseIntento = FaseIntento.AGREGANDO; token_agregar: Optional[int] = None; token_cruce: Optional[int] = None
    llenas: int = 0; canceladas: int = 0; reintento_cruce: int = 0; motivo_fin: Optional[str] = None
    cfg_congelada: Optional[dict] = None   # riesgo 18: el intento conserva la config con la que nació

@dataclass
class EstadoBS:                    # R-G-01
    activado_en: float; primer_stop: Decimal; emergencia_limite: Decimal; max_visto: Decimal
    informes: int = 0; ultimo_informe: float = 0.0; silenciado: bool = False; perdido_realizado: Decimal = Decimal("0")

@dataclass
class PosicionTicker:
    ticker: str; lotes: dict[str, Lote] = field(default_factory=dict)
    neta_fills: int = 0            # verdad INMEDIATA: suma signada de fills por token (corrección 2 del juez)
    neta_das: Optional[int] = None # lo último que dijo %POS / GET POSITIONS (reconciliación); None = no visto
    avg_das: Optional[Decimal] = None; tipo_das: Optional[int] = None; neta_das_en: Optional[float] = None
    estado: EstadoTicker = EstadoTicker.NORMAL; motivo_estado: str = ""; desde: Optional[float] = None
    bs: Optional[EstadoBS] = None; intento: Optional[IntentoEntrada] = None
    senal_guardada_halt: Optional[Senal] = None                  # R-F-04 (b)
    sin_reentrada_hasta_sigue: bool = False                      # R-G-03, R-F-03
    intervencion_humana: bool = False                            # R-K-02 / R-M-03
    version_stops: int = 0                                       # injerto A §8.6: sube con cada fill; invalida REPLACE viejos
    descubierta_desde: Optional[float] = None
    persecuciones_ask: int = 0

    @property
    def neta(self) -> int:
        """La neta OPERATIVA: fills (inmediata). Si neta_das discrepa, la reconciliación manda un barrido antes de tocar la emergencia."""
        return self.neta_fills

@dataclass
class Locate:                      # R-H
    ticker: str; strategy_id: str; pedidas: int; localizadas: int = 0; precio_accion: Decimal = Decimal("0"); coste: Decimal = Decimal("0")
    id_das: Optional[int] = None; token: Optional[int] = None; estado: str = "buscando"; usadas: int = 0
    reutilizable: Optional[bool] = None; comprado_en: Optional[float] = None; ultimo_inquire_en: Optional[float] = None; compras: int = 0

@dataclass
class Cuenta:
    bp: Optional[Decimal] = None; bp_overnight: Optional[Decimal] = None; equity: Optional[Decimal] = None
    htb_hoy: Decimal = Decimal("0"); leida_en: Optional[float] = None; bp_reservado: Decimal = Decimal("0")   # R-E-02

@dataclass
class EstadoBot:                   # TODO lo que el decisor sabe. Se reconstruye del diario + DAS al arrancar (H-2).
    fase: Fase; dia: date; vigilando: bool = True; pausa_global: bool = False; control_humano: bool = False
    senales_vistas: set[str] = field(default_factory=set)
    posiciones: dict[str, PosicionTicker] = field(default_factory=dict)
    ordenes: dict[int, Orden] = field(default_factory=dict)            # por token
    id_a_token: dict[int, int] = field(default_factory=dict)
    fills: dict[int, list[Fill]] = field(default_factory=dict)         # por token (libro de fills, verdad inmediata)
    ordenes_ajenas: dict[int, MsgOrden] = field(default_factory=dict)  # token no nuestro u orderSrc ≠ CMDAPI (R-K-02)
    locates: dict[tuple[str, str], Locate] = field(default_factory=dict)  # (ticker, strategy_id)
    gasto_locates_dia: Decimal = Decimal("0"); locates_deshabilitados: bool = False   # R-H-03 / R-H-02
    cuenta: Cuenta = field(default_factory=Cuenta)
    das_conectado: bool = False; das_logon: dict[str, Optional[bool]] = field(default_factory=dict)
    reconciliacion_ok_en: Optional[float] = None; ultima_respuesta_barrido_en: Optional[float] = None
    feed_ultima_vela_en: Optional[float] = None
    modo_degradado: set[str] = field(default_factory=set)              # {"feed", "das", "reconciliacion", "disco"} (R-J-03 + corrección 4)
    ultimo_fill_en: Optional[float] = None
    config_version: int = 0; ultimo_seq_token: int = 0
    rutas_habilitadas: dict[str, bool] = field(default_factory=dict)   # GET RouteStatus del primer día
    qty_corto_negativa: Optional[bool] = None                          # injerto A §8.8: se confirma el primer día

# ── acciones que devuelve el decisor (el ejecutor las EJECUTA en orden) ─
@dataclass(frozen=True)
class Accion:
    pass

@dataclass(frozen=True)
class EnviarOrden(Accion):
    orden: OrdenNueva; serie: Optional[str] = None                     # serie = f"stops:{ticker}" → el emisor descarta versión < vigente

@dataclass(frozen=True)
class Cancelar(Accion):
    id_das: int; token: Optional[int]; motivo: str

@dataclass(frozen=True)
class CancelarTicker(Accion):      # CANCEL ALLSYMB
    ticker: str; motivo: str

@dataclass(frozen=True)
class Reemplazar(Accion):
    id_das: int; token: int; qty: int; stop: Optional[Decimal]; precio: Optional[Decimal]; motivo: str
    version: int = 0; serie: Optional[str] = None

@dataclass(frozen=True)
class InvalidarSerie(Accion):      # sube la versión vigente de una serie en el emisor (tras un fill de stop)
    serie: str; version: int

@dataclass(frozen=True)
class Consultar(Accion):           # "GET BP", "GET SymStatus X", "GET LDLU X", "POSREFRESH", "SLReuseQuery X", ...
    comando: str

@dataclass(frozen=True)
class Suscribir(Accion):
    ticker: str; alta: bool

@dataclass(frozen=True)
class LocateInquire(Accion):
    ticker: str; qty: int; ruta: str

@dataclass(frozen=True)
class LocateComprar(Accion):
    ticker: str; qty: int; ruta: str; token: int

@dataclass(frozen=True)
class LocateOferta(Accion):
    id_das: int; aceptar: bool

@dataclass(frozen=True)
class Avisar(Accion):
    nivel: Nivel; grupo: Grupo; texto: str; clave: Optional[str] = None

@dataclass(frozen=True)
class Anotar(Accion):
    tipo: str; datos: dict

@dataclass(frozen=True)
class Programar(Accion):
    clave: str; en_s: float; datos: dict = field(default_factory=dict)

@dataclass(frozen=True)
class Desprogramar(Accion):
    clave: str

@dataclass(frozen=True)
class PublicarFoto(Accion):        # estado/foto.json (panel 4.4)
    pass

@dataclass(frozen=True)
class PedirAlSupervisor(Accion):   # estado/orden_supervisor.jsonl: {"relanzar": "ejecutor"} (fallback del vigilante)
    peticion: str

@dataclass(frozen=True)
class Salir(Accion):               # el proceso termina con este código (reloj > 2 s, hash del motor, doble instancia)
    codigo: int; motivo: str

# ── mensajes de la cola del ejecutor (todo entra por aquí) ─────────────
@dataclass(frozen=True)
class Mensaje:
    pass

@dataclass(frozen=True)
class SenalRecibida(Mensaje):
    senal: Senal

@dataclass(frozen=True)
class DeDAS(Mensaje):
    msg: MensajeDAS; simulado: bool = False

@dataclass(frozen=True)
class Tic(Mensaje):
    pass

@dataclass(frozen=True)
class Temporizador(Mensaje):
    clave: str; datos: dict

@dataclass(frozen=True)
class ComandoRecibido(Mensaje):
    comando: "Comando"

@dataclass(frozen=True)
class ConfigNueva(Mensaje):
    config: "Config"; aviso: Optional[str]

@dataclass(frozen=True)
class ConexionDAS(Mensaje):
    conectado: bool; motivo: str

@dataclass(frozen=True)
class HiloCaido(Mensaje):          # un hilo de borde murió y se relanzó (HiloVigilado)
    nombre: str; error: str; relanzado: bool

# ── configuración (config.py la carga; el esquema es el de §7) ─────────
@dataclass(frozen=True)
class EstrategiaConfig:
    strategy_id: str; name: str; origen: str; ejecutar: bool; avisar_grupo_a: bool
    riesgo_usd: Decimal; riesgos_piramide: list[Optional[Decimal]]; riesgo_piramide_usd: Optional[Decimal]
    ev_pct: Decimal; ev_rangos: list[dict]; excluir_ipo: bool; al_desactivar: str
    hora_fin_sesion: Optional[str]; ventana_entradas: list[dict]; hora_salida: Optional[str]   # de definition (CM4)
    accept_reentries: bool; max_reentries: int; niveles_piramide: list[dict]; es_rth: bool
    definition_hash: str; definition: dict

@dataclass(frozen=True)
class Config:
    schema_version: int; config_version: int; sha256: str; motor_hash: str; estrategias_hash: str; generado_at: str
    fase: Fase; vigilando: bool; horario: dict; modo_seguridad: dict; lista_negra: list[str]; pausar_entradas: bool
    locates: dict; entrada: dict; salidas: dict; stops: dict; halts: dict; exclusiones: dict; rutas: dict; tecnicos: dict
    alertas_grupo_a: dict; estrategias: dict[str, EstrategiaConfig]
    cuenta_das: str                # nombre literal de la cuenta (SLAvailQuery lo exige); viene del .env, NO del fichero

@dataclass(frozen=True)
class Comando:                     # comandos.py
    nombre: str; args: list[str]; chat_id: int; requiere: str; id: str; texto: str

@dataclass(frozen=True)
class Aviso:                       # avisos.py
    nivel: Nivel; grupo: Grupo; texto: str; clave: Optional[str]; creado_en: float

@dataclass(frozen=True)
class Registro:                    # diario.py
    v: int; seq: int; t: str; proceso: str; tipo: str; datos: dict
```

Notas del modelo. (a) `Evento.cuenta` ≠ `None` (multicuenta del bot de alertas) se anota y se ignora: el ejecutor opera UNA cuenta (`Config.cuenta_das`, del `.env`). (b) El `id` del `Lote` es el `id_evento` de su entrada; la salida o pirámide del motor se casa con el lote vivo por `(ticker, strategy_id)` y, si hay reentradas del mismo día, por `entrada_idx` como desempate (SÍ viaja por la tubería: `bot_alerts_alerta_proceso.py` l.62-65 pickla el `Evento` entero; solo se pierde por el camino del backend, `evento_a_dict`). (c) `Orden.proposito/nivel/lote_id` se conocen porque el ejecutor escribió la intención en su diario antes de enviar; el vigilante los lee de ese diario y, si una orden nuestra no está (la puso él mismo o el diario del ejecutor no llega), los INFIERE: `STOPLMTP` de compra con disparo ≈ L (±1 tick) → principal; disparo ≈ L·1,13 → emergencia; otro → `STOP_PROTECCION`. (d) `neta` signada: corto negativo en TODO el bot; `MsgPos.neta` la fija `protocolo.normalizar_pos` a partir de `tipo == 3` y `abs()`, y `EstadoBot.qty_corto_negativa` guarda lo que se observó el primer día (`herramientas/comprobar_das.py`).

---

## 3. Contratos de cada módulo

Convenciones comunes a todos: `from __future__ import annotations`; identificadores sin tildes; docstring de módulo «QUÉ HACE / POR QUÉ ESTÁ AQUÍ / LAS TRAMPAS»; cada función cita la regla que implementa; `except Exception as exc:  # noqa: BLE001` solo en fronteras (red, fichero, callback, mensaje) y siempre con la regla escrita al lado; las funciones de red NUNCA lanzan y distinguen `None` (no se pudo preguntar) de `[]`/`False` (respuesta real); env vars leídas en la llamada, nunca al importar; nada se ejecuta al importar un módulo.

### 3.1 `protocolo.py` (puro; API-2h; especificación §1-§5)

```python
FIN_LINEA = "\r\n"                      # §5.1: no documentado; se envía \r\n; al leer se acepta \n y se descarta \r
CODIFICACION = "latin-1"                # decode(errors="replace"): las notas del bróker pueden traer no-ASCII
MUTANTES = frozenset({"NEWORDER", "CANCEL", "REPLACE", "COMPLEXORDER", "SCRIPT", "GSCRIPT",
                      "SLNEWORDER", "SLOFFEROPERATION", "SLCANCELORDER"})     # R-O-03: sombra los prohíbe
ESTADOS_ORDEN = frozenset(e.value for e in EstadoOrden if e is not EstadoOrden.DESCONOCIDO)
CONEXION_LITERALES: dict[str, tuple[str, str]]   # las 12 líneas de L1472-1490 → (servidor, evento); comparación ENTERA (§5.26)
LADOS = {"B": "B", "BUY": "B", "S": "S", "SELL": "S", "SS": "SS", "SHRT": "SS", "SHORT": "SS"}   # §5.5

class PrecioFueraDeTick(ValueError): ...

def formatear_precio(p: Decimal) -> str
    # ÚNICA salida de precios al socket (injerto A §8.1). LANZA PrecioFueraDeTick si `not en_tick(p)`.
    # Sin notación científica, sin ceros de más: Decimal("10.30") → "10.3"; Decimal("0.1234") → "0.1234".
def es_mutante(linea: str) -> bool
    # primera palabra, insensible a mayúsculas; además «SLPRICEINQUIRE … ALLROUTE» cuenta como mutante (§5.22: crea órdenes Offered en rutas tipo 1)
def cmd_login(usuario: str, clave: str, cuenta: str, watch: bool) -> str        # "LOGIN u c acc 1|0" (L243-251)
def cmd_neworder(o: OrdenNueva) -> str
    # LMT:      "NEWORDER {token} {lado} {ticker} {ruta} {qty} {precio}[ PostOnly] TIF={tif}[ Pref=…]"   (L543-547, L767-770)
    # MKT:      "NEWORDER {token} {lado} {ticker} {ruta} {qty} MKT TIF={tif}"                           (L549-553)
    # STOPLMTP: "NEWORDER {token} {lado} {ticker} {ruta} {qty} STOPLMTP {stop} {precio} TIF={tif}"      (L618-624)
def cmd_cancel(id_das: int) -> str; def cmd_cancel_all() -> str; def cmd_cancel_allsymb(ticker: str) -> str   # L802-816, L226-229
def cmd_replace(id_das: int, qty: int, tipo: TipoOrden, precio: Optional[Decimal], stop: Optional[Decimal]) -> str
    # LMT → "REPLACE id qty precio"; STOPLMTP → "REPLACE id qty STOPLMT stop precio" (§5.6: NO documentado para STOPLMTP; se verifica después con tipo_conserva_pp)
def cmd_get(nombre: str, arg: Optional[str] = None) -> str
    # nombres admitidos (conjunto cerrado, si no ValueError): BP, SHORTINFO, LDLU, SymStatus, AccountInfo, POSITIONS, ORDERS, TRADES, LOCATES, RouteStatus, INTMSGS; y "POSREFRESH", "ECHO", "CLIENT" como comandos sueltos
def cmd_sb(ticker: str, canal: str = "Lv1") -> str; def cmd_unsb(ticker: str, canal: str = "Lv1") -> str
def cmd_return_full_lv1(si: bool) -> str
def cmd_sl_inquire(ticker: str, qty: int, ruta: str) -> str                    # ruta por defecto en el bot: "ALLROUTEWTTYPE1"
def cmd_sl_neworder(ticker: str, qty: int, ruta: str, token: int) -> str
def cmd_sl_offer(id_das: int, aceptar: bool) -> str; def cmd_sl_cancel(id_das: int) -> str
def cmd_sl_reuse(ticker: str) -> str; def cmd_sl_avail(cuenta: str, ticker: str) -> str; def cmd_sl_min_charge(ruta: str) -> str
def cmd_quit() -> str

class Parser:                                  # con estado SOLO para $INTMSG (multilínea) y los bloques #…/#…End
    def __init__(self, es_nuestro: Callable[[int], bool], watch: bool = False) -> None
    def parsear(self, linea: str) -> MensajeDAS  # NUNCA lanza; lo que no entiende → MsgDesconocido; palabra clave insensible a mayúsculas
    @property def en_bloque(self) -> Optional[str]   # "POS" | "Order" | "Trade" | "SLOrder" | None (§5.11: los marcadores son opcionales)
def parsear(linea: str, es_nuestro=lambda t: True) -> MensajeDAS   # atajo sin estado para tests
def normalizar_pos(ticker: str, tipo: int, qty_cruda: int, qty_corto_negativa: Optional[bool]) -> int
    # injerto A §8.8: neta signada. tipo == 3 (corto) → -abs(qty_cruda); tipo 1/2 → abs(qty_cruda). `qty_corto_negativa` solo se registra
    # (lo confirma comprobar_das.py el primer día); la normalización NO depende de él, por eso es segura en los dos casos.
def redactar(linea: str) -> str                 # "LOGIN u ***** acc 0"; también tapa el token de Telegram si apareciera (R-Q-01)
```

Detalles del parser que fijan comportamiento (cada uno con su línea en `fixtures/lineas_das.txt`):
- `%ORDER`/`%IORDER` (§5.2): se localizan desde la DERECHA `hora` (`HH:MM:SS`) y `estado` (∈ `ESTADOS_ORDEN`) por patrón; delante de `estado` se anclan `qty lvqty cxlqty precio ruta`; `tipo` = todo lo que quede entre `lado` y `qty` (puede llevar espacios: «SLP: 2.97 2.99»); detrás de `hora`: `origoid cuenta trader` y, si hay 3 campos más, `orderSrc TIF Pref` (15 o 19 campos, L343-352 y L930-932). `token` se acepta solo si `es_nuestro(token)`; si no, `token=None` y la orden es ajena.
- `%OrderAct` (§5.3-5.5): `split(" ", 8)` sin colapsar; último campo entero y `es_nuestro` → token; el resto recortado → `notas` (puede quedar vacío: dos espacios en L934). Lado por `LADOS`; valor desconocido se conserva tal cual y se registra.
- `%TRADE` 8 u 11 campos (L508-513); `%ITRADE` rama PROPIA: `Account tradeID symbol Side TradeShares TradePrice route exeTime orderID Trader` (L1444-1458) → `MsgTrade(watch=True, cuenta=…, trader=…)`.
- `%POS`/`%IPOS`: 8 o 9 campos (`Unrealized` opcional, L267-281); `neta` por `normalizar_pos`.
- `$Quote`: `dict` de `clave:valor` con claves desconocidas conservadas (§5.19); NO se convierten aquí (lo hace `mercado_das`).
- `$IssueStatus` y `$SymStatus` ambas (§5.9); `TA`/`TAT` ausentes = normal.
- `SLRouteMinChargeRet` con o sin `$` (§5.10); `%SLRET` con `Account` opcional y `Notes` con espacios; `%SLOrder` con `token` opcional y `notas` al final.
- `#POS #POSEND #Order #OrderEnd #Trade #TradeEnd #SLOrder #SLOrderEnd #buyingpower` → `MsgMarcador` (se ignora lo que siga a la palabra clave, §5.13-5.14).
- Las 12 líneas de conexión se comparan enteras contra `CONEXION_LITERALES` (dos llevan espacio: `Missing heartbeat`, `Lost Connection`).
- `$STINFOEX`: regex tolerante `(\w+):\s*([\d.]+)%` (§5.21). `$T&S`: `condicion` entero decimal (presunción §5.20). `$Bar`: High Low Open Close (§3.13).

### 3.2 `cliente.py` (red; R-J-02, R-O-03, cuotas manual L1996-2016)

```python
class EnvioProhibido(RuntimeError): ...        # R-O-03: en sombra no sale NINGÚN comando mutante (primer candado)
class CuotaComandos:                           # puro (reloj inyectado), ventana deslizante; se prueba con RelojSimulado
    def __init__(self, reloj, ordenes_s: int = 50, cancel_min: int = 100, replace_min: int = 100, locate_min: int = 100, inquire_s: float = LOCATES_INQUIRE_S, margen: float = 0.9) -> None
    def espera_para(self, linea: str) -> float # segundos a esperar antes de enviar (0.0 si cabe); trabaja al 90 % del límite (riesgo 22)
    def anotar(self, linea: str) -> None
class PlanReconexion:                          # puro; R-J-02 (2): 2, 4, 8, 16 y luego 30 s sin parar
    def __init__(self, esperas: tuple[float, ...] = DAS_RECONEXION_S, tope: float = DAS_RECONEXION_TOPE_S) -> None
    def siguiente(self) -> float; def reiniciar(self) -> None
    @property def intentos(self) -> int
class ClienteDAS:
    def __init__(self, host: str, puerto: int, usuario: str, clave: str, cuenta: str, watch: bool, solo_lectura: bool,
                 al_mensaje: Callable[[MensajeDAS], None], al_estado: Callable[[bool, str], None], reloj,
                 cuota: Optional[CuotaComandos] = None, timeout_s: float = 5.0, parser: Optional[Parser] = None) -> None
    def conectar(self) -> bool                 # abre el socket, arranca los dos hilos (HiloVigilado), manda LOGIN; True si el socket abrió (no hay «login OK» documentado, §1)
    def cerrar(self) -> None                   # QUIT si se puede, cierra, para hilos
    def enviar(self, linea: str, serie: Optional[str] = None, version: int = 0) -> None
        # NO bloquea: encola. Lanza EnvioProhibido si solo_lectura y es_mutante(linea). Cola con tope COLA_SALIDA_TOPE:
        # llena → aviso nivel 2 y el hilo emisor sigue; el principal NUNCA se bloquea (se descarta la línea más vieja de la misma serie si la hay, si no se espera 50 ms y se reintenta una vez).
    def invalidar(self, serie: str, version: int) -> None   # injerto A §8.6: el emisor descarta líneas de `serie` con versión < `version` (REPLACE de stops ya obsoletos tras un fill)
    @property def conectado(self) -> bool
    @property def ultimo_recibido_en(self) -> Optional[float]
    @property def logon(self) -> dict[str, Optional[bool]]   # {"OrderServer": True/False/None, "QuoteServer": …} por MsgConexion
    @property def hilos_vivos(self) -> bool     # los dos HiloVigilado están vivos (lo mira el latido del ejecutor)
    @staticmethod
    def desde_env(watch: bool, solo_lectura: bool, **kw) -> "ClienteDAS"
        # DAS_API_HOST (defecto 127.0.0.1), DAS_API_PORT (obligatorio), DAS_USUARIO, DAS_CLAVE, DAS_CUENTA (obligatorios).
        # SEGUNDO CANDADO (corrección 15): solo_lectura=False exige BOT_DAS_PERMITIR_ORDENES=1 en el entorno; si falta → RuntimeError con texto claro.
class ClienteSombra:                           # R-O-03 sombra: lecturas al DAS real, mutantes a un emparejador interno
    def __init__(self, real: ClienteDAS, emparejador: "Emparejador", al_mensaje: Callable[[MensajeDAS, bool], None]) -> None
    def enviar(self, linea: str, serie=None, version=0) -> None    # mutante → emparejador.recibir(linea) → mensajes sintéticos con simulado=True; resto → real.enviar
    conectar / cerrar / invalidar / conectado / logon / hilos_vivos → delegan en `real`
```
Hilo lector (`das-lector`): `recv(4096)` con timeout 1 s, buffer, parte por `\n`, quita `\r`, decodifica `latin-1`; cada línea → `parser.parsear` → `al_mensaje` (que SOLO encola). EOF/`OSError` → `al_estado(False, motivo)`. Hilo emisor (`das-emisor`): saca de la cola, descarta si `serie` invalidada, espera `cuota.espera_para`, `sendall((linea + FIN_LINEA).encode())`, `cuota.anotar`. Nada se loguea sin `redactar`. Ambos hilos son `HiloVigilado` (§3.6).

### 3.3 `simulador_das.py` (tests, «DAS falso», replay)

```python
@dataclass class ModeloSpread: pct: Decimal = Decimal("0.5"); minimo_ticks: int = 1; tamano_bid: int = 500; tamano_ask: int = 500   # injerto A §8.24
class LibroSimulado:            # cotizaciones, posiciones, órdenes, trades, locates; determinista
    def cotizar(self, ticker: str, bid: Decimal, ask: Decimal, last: Optional[Decimal] = None, volumen: int = 0, vwap: Optional[Decimal] = None) -> list[str]   # líneas $Quote a emitir
    def desde_vela(self, ticker: str, vela: dict, spread: ModeloSpread) -> list[str]    # replay: close → last; bid/ask = close ∓ spread (grabador.py no trae spread)
    def halt(self, ticker: str, ta: str, tat: str) -> None; def reabrir(self, ticker: str, precio: Decimal) -> None
    def bandas(self, ticker: str, ld: Decimal, lu: Decimal) -> None; def ssr(self, ticker: str, activo: bool) -> None
    def rechazar_siguiente(self, notas: str, accion: str = "Send_Rej") -> None
    def llenar_parcial(self, fraccion: Decimal) -> None                # próximas órdenes se llenan a esta fracción
    def ordenes(self) -> list[dict]; def posiciones(self) -> dict[str, int]; def trades(self) -> list[dict]; def locates(self) -> list[dict]
class Emparejador:              # motor de cruce: PURO salvo el reloj; lo usan SimuladorDAS y ClienteSombra
    def __init__(self, libro: LibroSimulado, reloj, variante_order: int = 19, tipo_stop_crudo: str = "SLP",
                 replace_conserva_pp: bool = True, latencia_s: float = 0.0, qty_corto_negativa: bool = False,
                 orden_mensajes: tuple[str, ...] = ("OrderAct", "TRADE", "POS")) -> None
        # `orden_mensajes` permuta el orden %OrderAct/%TRADE/%POS (NO documentado, §5.12): los tests del decisor se corren con las 6 permutaciones
    def recibir(self, linea: str) -> list[str]  # NEWORDER/CANCEL/REPLACE/SL* → líneas %OrderAct/%ORDER/%TRADE/%POS/%SLOrder/%SLRET
    def tic(self) -> list[str]                  # dispara stops por último print (last ≥ stop), llena órdenes que reposan
class SimuladorDAS:             # servidor TCP en un hilo; N conexiones (normal y watch); LOGIN → volcado #POS/#Order/#Trade
    def __init__(self, libro: LibroSimulado, reloj, host: str = "127.0.0.1", puerto: int = 0, usuarios: Optional[dict[str, str]] = None) -> None
    def arrancar(self) -> tuple[str, int]; def parar(self) -> None
    def cortar(self, cual: str = "todas") -> None            # simula R-J-02 (EOF)
    def emitir(self, linea: str, a_watch: bool = False) -> None
    def recibidas(self) -> list[str]                          # comandos que llegaron (para asertar «ningún mutante» en sombra)
def main(argv) -> int          # python -m app.bot_das.simulador_das --puerto 9800 --guion fichero.json
```
Reglas de cruce: venta límite se llena si `precio ≤ bid` (con PostOnly: `Send_Rej "PostOnly would cross"`), si no reposa y se llena cuando `bid ≥ precio`; compra límite simétrica con `ask`; `MKT` al `ask`/`bid`; `STOPLMTP` de compra se dispara cuando `last ≥ stop` y pasa a límite; parciales por `llenar_parcial` o por tamaño del libro; ruta `OPEN` durante halt se acepta y se llena al precio de `reabrir` (EP-2, configurable a rechazo). La conexión watch recibe `%IORDER/%IPOS/%ITRADE` de todo. Los usuarios del simulador son inventados en el test (`{"prueba": "prueba"}`): las credenciales de ejemplo del manual (L246-247) NO se usan ni como fixture.

### 3.4 `tokens.py` (R-A-05, R-C-07 «quién la puso»)

```python
MAX_TOKEN = 2**31 - 1
MAX_SEQ = 99_999
def componer(origen: Origen, dia_del_anyo: int, seq: int) -> int
    # origen·10^8 + dia·10^5 + seq; seq ∈ [1, 99_999]; máximo 3·10^8 + 366·10^5 + 99_999 = 336_699_999 < MAX_TOKEN (corrección 9 del juez)
def descomponer(token: int) -> Optional[tuple[Origen, int, int]]   # None si no cuadra con el esquema
def es_nuestro(token: Optional[int], hoy: date) -> bool
    # A PROPÓSITO rechaza tokens de AYER: las órdenes DAY+ caducan a las 20:00 (2f.5); una orden con token de ayer que siga viva es AJENA para el bot de hoy y la trata R-K-02 (protección + aviso), nunca la adopta.
class GeneradorTokens:
    def __init__(self, origen: Origen, hoy: date, ultimo_seq: int = 0) -> None    # ultimo_seq viene del diario (H-2)
    def siguiente(self) -> int          # lanza TokensAgotados pasado MAX_SEQ (aviso nivel 3: no se opera más ese día)
    def cambiar_dia(self, hoy: date) -> None
```

### 3.5 `reloj.py` (R-J-07, R-L-03)

```python
ET = ZoneInfo("America/New_York")
class Reloj:
    def ahora(self) -> datetime            # aware, ET
    def mono(self) -> float                # time.monotonic()
    def hoy(self) -> date; def epoch(self) -> float
class RelojSimulado(Reloj):
    def __init__(self, inicio: datetime) -> None; def avanzar(self, s: float) -> None; def fijar(self, dt: datetime) -> None
def desvio_sntp(servidor: str = "time.windows.com", timeout_s: float = 3.0) -> Optional[float]   # UDP stdlib; None si no contesta
def veredicto_reloj(desvio: Optional[float], negarse_s: float = RELOJ_NEGARSE_S, aviso_s: float = RELOJ_AVISO_S) -> tuple[bool, Optional[str]]   # (puede_operar, aviso); None → (True, "sin SNTP")
def a_hora_et(hhmm: str, dia: date) -> datetime
def hora_das_a_et(hhmmss: str, hoy: date) -> datetime   # riesgo 10: los HH:MM:SS de %ORDER se combinan con `hoy`
```

### 3.6 `cerrojo.py` (R-J-04 b, c; injerto A §8.11)

```python
class CerrojoInstancia:
    def __init__(self, ruta: Path) -> None
    def adquirir(self) -> bool             # msvcrt.locking(LK_NBLCK) sobre 1 byte; escribe el PID; el SO lo libera si el proceso muere
    def soltar(self) -> None
    @staticmethod def pid_guardado(ruta: Path) -> Optional[int]
class Latido:
    def __init__(self, ruta: Path, reloj, cada_s: float = LATIDO_S) -> None
    def tocar(self, todo_vivo: bool = True) -> None   # escribe epoch en tmp + os.replace, como mucho cada `cada_s`; con todo_vivo=False NO escribe (el supervisor lo verá viejo y relanzará)
    @staticmethod def edad(ruta: Path, ahora_epoch: float) -> Optional[float]   # None si no existe
class HiloVigilado:                        # equivalente al `tarea_vigilada` de A: registra, avisa nivel 2 y relanza
    def __init__(self, nombre: str, cuerpo: Callable[[], None], al_caida: Callable[[str, str, bool], None], max_relanzos: int = 5, espera_s: float = 1.0) -> None
    def arrancar(self) -> None; def parar(self) -> None
    @property def vivo(self) -> bool; @property def caidas(self) -> int
```

### 3.7 `diario.py` (R-N-01, H-2, M6, R-A-05; correcciones 3 y 4 del juez)

```python
FSYNC = frozenset({"orden_intencion", "orden_enviada", "cancel_intencion", "replace_intencion", "locate_intencion", "cierre_humano", "lote"})
class DiarioNoDisponible(RuntimeError): ...
class Diario:
    def __init__(self, directorio: Path, reloj, proceso: str, version_codigo: str, fase: Fase) -> None   # proceso ∈ {"ejecutor","vigilante","supervisor"} → diario_{proceso}_AAAA-MM-DD.jsonl
    def abrir_dia(self, dia: date) -> None                    # cabecera `arranque`: version, fase, motor_hash, config_version, pid (R-O-01)
    def anotar(self, tipo: str, **datos) -> int
        # write-ahead: json + "\n", flush; fsync si tipo ∈ FSYNC. Devuelve seq. NUNCA lanza hacia fuera: si el disco falla,
        # `degradado = True`, se guarda el registro en `pendientes` (tope 1.000) y se reintenta abrir el fichero en cada llamada.
    @property def seq(self) -> int; @property def degradado(self) -> bool
    def cerrar(self) -> None
class LectorDiario:
    def __init__(self, directorio: Path) -> None
    def leer(self, dia: date, procesos: tuple[str, ...] = ("ejecutor", "vigilante")) -> list[Registro]   # une los dos ficheros ordenados por (t, proceso, seq); tolera la última línea partida
    def seguir(self, dia: date, proceso: str, desde_seq: int) -> list[Registro]   # para el vigilante: lo nuevo del ejecutor desde seq
def reconstruir(registros: Iterable[Registro], hoy: date) -> EstadoBot
    # PURO (H-2). Reproduce: senales_vistas, lotes y su estado, ordenes por token (último estado conocido), fills por token y neta_fills,
    # ultimo_seq_token (por origen), locates (comprados/usados/coste, gasto del día), pausas por ticker, BS, intervenciones, config_version,
    # tickers con sin_reentrada_hasta_sigue. Idempotente: reconstruir(reconstruir) == reconstruir.
```
Política cuando el write-ahead falla (corrección 4): con `diario.degradado` el decisor NO emite `EnviarOrden` de `ENTRADA_*`, pirámides `add` ni `LocateComprar` (`modo_degradado.add("disco")`, aviso nivel 3 una vez, `senal_descartada("diario no escribible")`); SÍ salen stops, cancelaciones, `VENTA_EXCESO`, cierres (hora/EOD/humano) y `Reemplazar` de stops: proteger la posición manda sobre registrar (M6 + H-2). Test en `test_das_ejecutor.py`: `anotar` que falla → 0 `NEWORDER SS`, los `NEWORDER B STOPLMTP` siguen saliendo.

### 3.8 `config.py` (H-4, H-6, CM1-CM4, R-O-01, R-I-03, R-L-02)

```python
CALIENTE: frozenset[str]        # rutas con punto de §7 marcadas [C]
FICHEROS_MOTOR = ("app/services/strategy_engine.py", "app/services/market_frame.py", "app/services/portfolio_sim.py")   # memoria «tres ficheros compartidos»
class ConfigInvalida(ValueError): errores: list[str]
def hash_canonico(obj: Any) -> str                        # sha256 de json.dumps(sort_keys=True, separators=(",",":"), ensure_ascii=False)
def motor_hash(base: Path) -> str                         # sha256 de los tres ficheros concatenados (H-6)
def escribir_atomico(ruta: Path, obj: dict) -> None       # calcula `sha256` del resto, tmp en el MISMO directorio + os.replace
def validar(crudo: dict) -> list[str]                     # esquema, sha256, rangos (0 < principal_limite_pct < emergencia_disparo_pct < emergencia_limite_pct; k_max ≥ 1; tope_gasto ∈ (0, 10]; horas HH:MM; fase ∈ Fase)
def cargar(ruta: Path, cuenta_das: str) -> Config         # lanza ConfigInvalida con la lista de errores
def cargar_con_respaldo(ruta: Path, ultimo_bueno: Path, cuenta_das: str) -> tuple[Config, Optional[str]]   # H-4: si falla → último bueno + texto de aviso; si tampoco → ConfigInvalida
def guardar_ultimo_bueno(cfg_cruda: dict, ultimo_bueno: Path) -> None
def extraer_estrategia(v: dict) -> EstrategiaConfig       # de la fila del cuadro + definition: hora_fin_sesion, ventana_entradas, hora_salida, reentradas, niveles; es_rth = ventana entera ≥ 09:30
def diferencias(vieja: Config, nueva: Config) -> list[tuple[str, Any, Any, bool]]   # (ruta, antes, despues, caliente)
def aplicar(actual: Config, nueva: Config, bot_encendido: bool, hay_posiciones: bool) -> tuple[Config, list[str]]   # CM2: aplica [C]; [A] solo con bot apagado y sin posiciones; devuelve las rutas rechazadas (aviso 2 + CM3)
def comprobar_coherencia(e: EstrategiaConfig) -> list[str]  # R-L-02: ventana ⊂ sesión, hora_salida ≤ fin de sesión, sesión «sumada» sospechosa (memoria)
class VigilanteConfig:                                    # HiloVigilado: mtime cada 1 s → al_cambio(Config, aviso)
    def __init__(self, ruta: Path, ultimo_bueno: Path, cuenta_das: str, al_cambio: Callable[[Config, Optional[str]], None]) -> None
    def arrancar(self) -> None; def parar(self) -> None
def exportar_desde_backend(url_base: str, destino: Path, defaults: Path) -> Config
    # PUENTE PROVISIONAL hasta que exista /api/bot-das: GET /api/bot-alerts/vigiladas (urllib) + defaults de config_ejemplo.json → fichero H-4 con motor_hash calculado
def main(argv) -> int                                     # python -m app.bot_das.config exportar|validar|hash [--ruta …]
```

### 3.9 `avisos.py` (R-M-01, R-M-02, R-M-05, R-J-08, R-Q-01; injerto A §8.20)

```python
class Canal(Protocol):
    nombre: str; niveles: frozenset[Nivel]; grupos: frozenset[Grupo]
    def enviar(self, texto: str) -> bool               # bloqueante, 1 intento, NUNCA lanza
class CanalTelegram(Canal):
    def __init__(self, token: str, chat_id: str, grupo: Grupo, niveles: frozenset[Nivel], timeout_s: float = 10.0) -> None
    # urllib.request (stdlib), NO httpx: la URL lleva el token y httpx la loguea (memoria «httpx filtra tokens»). SSL con el almacén de Windows como bot_alerts_telegram l.41-62.
class CanalCorreo(Canal):     def __init__(self, smtp_host: str, smtp_puerto: int, usuario: str, clave: str, destino: str, niveles=frozenset({Nivel.AVISO, Nivel.MAXIMO})) -> None   # smtplib
class CanalSMS(Canal):        def __init__(self, proveedor: "ProveedorSMS", niveles=frozenset({Nivel.MAXIMO})) -> None
class ProveedorSMSNulo:       def enviar(self, texto: str) -> bool     # loguea y devuelve True; R-M-02 proveedor [PENDIENTE]
class ColaAvisos:
    def __init__(self, canales: list[Canal], reloj, tope: int = COLA_AVISOS_TOPE, reintentos: int = 3, espera_reintento_s: float = 2.0) -> None
    def poner(self, aviso: Aviso) -> None              # put_nowait; nunca bloquea; dedupe por `clave` en ventana de 60 s; tope superado → cuenta perdidos
    def arrancar(self) -> None; def parar(self, espera_s: float = 30.0) -> None
    @property def pendientes(self) -> int; @property def perdidos(self) -> int; @property def vivo(self) -> bool
def canales_desde_env(cfg: Config) -> list[Canal]      # TELEGRAM_BOT_TOKEN_B / TELEGRAM_CHAT_ID_B (grupo B, obligatorios fuera de tests); TELEGRAM_BOT_TOKEN_A / TELEGRAM_CHAT_ID_A (grupo A, opcional); SMTP_HOST/PORT/USER/PASS/TO; SMS_PROVEEDOR
def texto_grupo_a(eventos: list) -> list[str]          # = [bot_alerts_telegram.formatear_grupo(g) for g in bot_alerts_telegram.agrupar(eventos)] (reutilizado; mismo formato que hoy)
def texto_fill(lote: Lote, fill: Fill, cfg: Config, fase: Fase) -> str    # cada aviso del grupo B lleva la fase delante: «[SOMBRA]», «[CANARIO]», «[REAL]» (R-O-03)
def texto_rechazo(orden: Orden, notas: str, pos: PosicionTicker) -> str
def texto_informe_bs(pos, cot, bs, stops, cuenta, ahora_et, eod, franja) -> str   # delega en reglas.cisne_negro.informe
class FiltroSecretos(logging.Filter):
    def __init__(self, secretos: Iterable[str]) -> None   # corrección 8: se construye con los VALORES literales de TELEGRAM_BOT_TOKEN_A/B, DAS_CLAVE, BOT_DAS_AUTHKEY, MASSIVE_BOT_API_KEY, SMTP_PASS (los que existan, longitud ≥ 6)
    def filter(self, record: logging.LogRecord) -> bool   # sustituye en `msg` Y en cada `args` por "*****"; además la forma URL `bot\d+:[A-Za-z0-9_-]+`
    def limpiar(self, texto: str) -> str                  # lo usa el diario en `anotar` (los `notas` de DAS o un comando de Telegram podrían traer un secreto)
def instalar_logging(proceso: str, directorio_logs: Path, secretos: Iterable[str]) -> None   # fichero por proceso y día, FiltroSecretos en el handler raíz, `httpx` y `urllib3` a WARNING
```

### 3.10 `comandos.py` (R-M-04, R-M-06 hueco, R-Q-01)

```python
CONSULTA = frozenset({"estado", "posiciones", "ordenes", "locates", "estrategias", "detalle", "salud", "log"})
DOS_PASOS = frozenset({"pausar", "reanudar", "sigue", "modo_seguridad", "desactivar", "activar", "apagar", "encender", "reanudar_ticker", "reanudar_todo", "parar_avisos", "reanudar_avisos", "control_humano", "cerrar_y_reiniciar", "esperar_fin_dia"})
CON_SI = frozenset({"cerrar_todo", "cerrar", "cancelar_ordenes", "stop"})
def parsear(texto: str, chat_id: int, autorizados: frozenset[int]) -> Optional[Comando]   # None si no autorizado (se registra el intento) o no es comando (→ R-M-06 más adelante)
class Confirmaciones:                                   # dos pasos con caducidad
    def __init__(self, reloj, ttl_s: float = 60.0) -> None
    def pedir(self, c: Comando) -> str                  # «Confirma con /confirmar <id>» (id de 4 cifras)
    def confirmar(self, chat_id: int, texto: str) -> Optional[Comando]
def responder_consulta(c: Comando, estado: EstadoBot, cfg: Config, mercado: "MercadoDAS", ahora: float) -> str   # PURO; un formato por comando de R-M-04
class ReceptorTelegram:                                 # HiloVigilado de getUpdates (urllib, long polling 25 s) → al_comando(Comando); filtra por chat_id ANTES de parsear
    def __init__(self, token: str, autorizados: frozenset[int], al_comando: Callable[[Comando], None], reloj) -> None
    def arrancar(self) -> None; def parar(self) -> None
class LectorComandosFichero:                            # estado/comandos.jsonl (botones del cuadro): {"id","comando","args","quien","t"}; id único → idempotente (se guarda `ultimo_id` en estado/comandos_leidos)
    def __init__(self, ruta: Path, al_comando: Callable[[Comando], None], reloj) -> None
    def arrancar(self) -> None; def parar(self) -> None
```

### 3.11 `fuente_senales.py` y `enlace_bot_alertas.py`

```python
class FuenteSenales(Protocol):
    def arrancar(self) -> None; def parar(self) -> None
    def salud(self) -> dict        # {"viva": bool, "ultimo_en": epoch, "origen": str}
class FuenteEnProceso(FuenteSenales):     # RunnerAlertas local; para tests, replay y un futuro sin bot.py. IMPORTA pandas/runner DENTRO de __init__ (injerto A §8.25)
    def __init__(self, estrategias: list[dict], destino: Callable[[Senal], None], reloj) -> None
    def hidratar(self, ticker: str, velas: list[dict], stats: Optional[dict] = None) -> None   # → runner.hidratar → Senal("hidratado") + Senal("evento") por Evento
    def vela(self, ticker: str, vela: dict) -> None                                             # → runner.nueva_vela → Senal("evento") por Evento (id = id_evento)
    def radar(self, ticker: str, precio: Decimal) -> None
        # → runner.estimacion_locates(ticker, float(precio)) → filas SIN strategy_id (engine l.549-602). CORRECCIÓN 6: la fuente casa cada fila por `nombre`
        # contra {e["name"]: e["strategy_id"] for e in runner.motor.estrategias} y AÑADE "strategy_id"; nombres repetidos → la fila se descarta y Avisar(2) una vez al día.
    def dia_nuevo(self) -> None
class FuenteTuberia(FuenteSenales):       # multiprocessing.connection.Listener; bot.py conecta con EnlaceEjecutor. NO importa pandas.
    def __init__(self, direccion: tuple[str, int] | str, authkey: bytes, destino: Callable[[Senal], None], reloj, motor_hash_esperado: str, version_minima: str) -> None
    # mensajes (dict con "t"): "hola" {version, motor_hash} (si el hash no coincide → se rechaza la conexión y Avisar(3)) |
    # "eventos" {ticker, minuto, timestamp, eventos:[Evento], recuperada} | "hidratado" {ticker, n_velas, eventos, prev_close} |
    # "radar" {candidatos:[{ticker, precio, estimacion(con strategy_id)}]} | "latido" {ultima_vela_en, feed_vivo} | "dia_nuevo"
    # Un `Evento` sin `tipo`/`ticker`/`strategy_id`/`momento` (pickle de otra versión) → señal descartada + Avisar(2) (riesgo 15).
class FuenteGrabacion(FuenteEnProceso):   # lee grabaciones/AM_AAAA-MM-DD.jsonl.gz (grabador.py l.29) y avanza un RelojSimulado
    def __init__(self, ruta_am: Path, estrategias: list[dict], destino, reloj: RelojSimulado, guion: Optional["Guion"] = None,
                 tickers: Optional[set[str]] = None, hidratar_desde: Optional[Callable[[str], list[dict]]] = None) -> None
    def reproducir(self, hasta: Optional[datetime] = None, paso: Optional[Callable[[datetime, dict], None]] = None) -> int
        # velas aplicadas; `paso(t, vela)` deja al test alimentar el LibroSimulado (desde_vela con el ModeloSpread del guion) y meter fills/halts declarados
@dataclass class Guion: spread: ModeloSpread; halts: list[dict]; rechazos: list[dict]; fills_parciales: list[dict]   # injerto A §8.24; se carga de fixtures/guion_replay_ejemplo.json

# enlace_bot_alertas.py — lo que bot.py llamaría (DIFERIDO, bandera BOT_DAS_ENLACE=1). No importa nada de bot_das salvo tipos.
class EnlaceEjecutor:
    def __init__(self, direccion=None, authkey=None, tope: int = 2000, version: str = VERSION, motor_hash: str = "") -> None   # BOT_DAS_TUBERIA (defecto ("127.0.0.1", 8765)), BOT_DAS_AUTHKEY (obligatoria)
    def arrancar(self) -> None; def parar(self) -> None
    def eventos(self, ticker: str, minuto: str, timestamp, eventos: list, recuperada: bool) -> None   # encola y vuelve (corre en el hilo lector del padre: BARATO)
    def hidratado(self, ticker: str, n_velas: int, eventos: list, prev_close) -> None
    def radar(self, candidatos: list[dict], nombre_a_id: dict[str, str]) -> None   # añade strategy_id por nombre (corrección 6)
    def latido(self, ultima_vela_en: float, feed_vivo: bool) -> None; def dia_nuevo(self) -> None
```
Parche futuro en `bot.py` (NO se hace ahora; 8 líneas, DIFERIDO §11): crear `enlace` tras l.523 si `BOT_DAS_ENLACE=1`; en `_de_la_alerta` (l.463) y `_hidratado` (l.475) llamar `enlace.eventos/hidratado` ANTES de `avisar_telegram`; en el ciclo del radar `enlace.radar(radar_proc.candidatos(), …)`; en el latido de 5 s `enlace.latido(...)`; en el `finally` (l.1370) `enlace.parar()`.

### 3.12 `mercado_das.py` (R-A-06.3, R-C-09.3, R-F-02, A7, R-I-04, R-B-05)

```python
class MercadoDAS:
    def __init__(self, reloj, max_lv1: int = MAX_LV1) -> None
    def aplicar(self, msg: MensajeDAS) -> Optional[str]              # MsgQuote (parche: solo claves presentes, Decimal(cadena)), MsgIssueStatus, MsgLDLU, MsgShortInfo; devuelve el ticker tocado
    def cotizacion(self, ticker: str) -> Optional[Cotizacion]
    def simbolo(self, ticker: str) -> EstadoSimbolo
    def fresca(self, ticker: str, ahora: float, max_s: float = 5.0) -> bool   # bid y ask presentes y actualizada_en reciente
    def dollar_volume(self, ticker: str) -> Optional[Decimal]        # V × VWAP de $Quote (desde las 4 AM) → R-I-04 (pregunta 9 a Jaume: aproximación)
    def marcar_halt(self, ticker: str, msg: MsgIssueStatus, ahora: datetime, last: Optional[Decimal], franja: str) -> Optional[str]   # "halt"|"reapertura"|None; k += 1 si UP (last ≥ limit_up·(1−ε)) y franja == "RTH"
    def suscripciones(self, necesarios: set[str]) -> tuple[list[str], list[str]]   # (alta, baja) respetando max_lv1; prioridad posiciones > intentos > radar
    def sin_cotizacion_desde(self, ticker: str, suscrito_en: float, ahora: float, max_s: float = 5.0) -> bool   # A7: símbolo que no casa
    def foto(self) -> dict
```

### 3.13 `referencia_massive.py` (R-A-03 v2; REST, nunca WS; corrección 17)

```python
@dataclass(frozen=True) class Ficha: ticker: str; list_date: Optional[date]; sic_code: Optional[str]; tipo: Optional[str]; market_cap: Optional[Decimal]; nombre: str
class Referencia:
    def __init__(self, clave: str, cache_dir: Path, reloj, timeout_s: float = 8.0, abrir: Callable = urllib.request.urlopen) -> None   # MASSIVE_BOT_API_KEY (misma variable que bot_alerts_feed.clave_bot); `abrir` inyectable para tests
    def ficha(self, ticker: str) -> Optional[Ficha]                   # /v3/reference/tickers/{t}; caché por día; None = no se pudo (A12: no se opera, se reintenta)
    def splits_de_hoy(self, hoy: date) -> Optional[set[str]]          # /v3/reference/splits?execution_date=hoy; None = no se pudo → el decisor NO excluye y Avisar(2) una vez (nunca «excluir todo»); la Nasdaq Daily List del libro queda como alternativa (pregunta 6)
```

### 3.14 `reglas/precios.py` (R-B-01 redondeo, regla 612, tabla de rutas; injerto A §8.1)

Todo en `Decimal`; la entrada `float` (del `Evento`) se convierte con `Decimal(str(x))` en UNA función (`de_float`) y nunca se opera con `float`.
```python
def de_float(x: float | int | str) -> Decimal                     # Decimal(str(x)); NaN/inf → ValueError
def redondear_arriba(p: Decimal) -> Decimal; def redondear_abajo(p: Decimal) -> Decimal   # al_tick(p, True/False) de tipos
def punto_medio_arriba(bid: Decimal, ask: Decimal) -> Decimal      # ceil((bid+ask)/2 al tick): spread 1 tick → ask; 2 ticks → bid + 1 tick (R-B-01 v3, 24-sep)
def punto_medio_abajo(bid: Decimal, ask: Decimal) -> Decimal       # para compras (TP / salida por hora agregando)
def con_techo(precio: Decimal, pct: Decimal, arriba: bool) -> Decimal   # precio·(1 ± pct/100) redondeado hacia el lado PERMISIVO (arriba para compras, abajo para ventas)
def bajo_bid(bid: Decimal, pct: Decimal) -> Decimal               # bid·(1 − pct/100) redondeado abajo (cruce R-B-01)
def tramo(precio: Decimal) -> str                                   # "ge_1" | "lt_1"
def ruta(cfg_rutas: dict, accion: str, precio: Decimal, hora_et: datetime) -> str   # accion ∈ {"agregar","cruzar","stop","halt"}; EDGA solo desde 07:00 (antes MIAX) según la tabla de rutas
def distancia_pct(a: Decimal, b: Decimal) -> Decimal               # (a − b)/b·100
def subida_pct(desde: Decimal, hasta: Decimal) -> Decimal
```

### 3.15 `reglas/entrada.py` (R-B-01 v3, R-B-02/03/04/05, B11/B13/B18/B19/B20 bis, R-A-01, R-I-04, R-E-01, R-C-09, R-F-04 b, R-D-04, R-G-03, H-5)

```python
@dataclass(frozen=True) class Veredicto: ok: bool; motivo: str; qty: int = 0; guardar_para_reapertura: bool = False; avisar: bool = False
def evaluar_senal(estado: EstadoBot, cfg: Config, senal: Senal, cot: Optional[Cotizacion], simb: EstadoSimbolo, ficha: Optional[Ficha],
                  splits_hoy: Optional[set[str]], franja: str, ahora: float, ahora_et: datetime, diario_degradado: bool) -> Veredicto
    # ORDEN FIJO de comprobación (cada una un motivo distinto, cada una una fila del test):
    #  1 repetida: senal.id ∈ senales_vistas (R-A-05)          2 vigilando=False / pausa_global / control_humano (R-M-03, R-D-02)
    #  3 estrategia no está o ejecutar=False (CM2)            4 ticker PAUSADO / BS / SIN_SIMBOLO / CONTROL_HUMANO (R-B-07, R-G-03, A7)
    #  5 lado opuesto a un lote abierto (R-E-01)               6 exclusiones (R-A-03 v2) → reglas.exclusiones.excluida
    #  7 halt en curso → guardar_para_reapertura (R-F-04 b, B18)   8 sin cotización fresca de DAS → no (R-B-01 «sin cotización no se entra»)
    #  9 modo seguridad: last ≥ 5 $ y V·VWAP ≥ 2 M$ (R-I-04)   10 retraso |last − precio_senal|/precio_senal > 1 % (R-A-01)
    # 11 (último − bid)/último > D (B20 bis, cfg.entrada.distancia_max_ultimo_bid_pct; None = apagada)
    # 12 nivel de stop L ≤ last → no (R-C-09); L None → no (A12)   13 caducidad: ahora > t_cierre_vela + caducidad_senal_s (R-B-04)
    # 14 reentrada prohibida: puede_reentrar (R-D-04), tras stop+halt (R-F-03), BS sin /sigue (R-G-03), estrategia con lote vivo y al_desactivar (R-E-03)
    # 15 diario degradado → no (corrección 4)                 16 locate: qty = min(pedidas, localizadas − usadas) (R-H-04); 0 → no
def t_cierre_vela(momento) -> float
    # epoch del CIERRE de la vela = momento + 60 s. CORRECTO porque `vela_de_mensaje` (bot_alerts_feed.py l.177-187) pone timestamp = campo `s`
    # (INICIO del minuto) y `Evento.momento = frame["timestamp"].iloc[i]` (engine l.1027), naive ET (runner l.40). Test explícito: si la fuente
    # cambiara a `e` (fin), la caducidad de R-B-04 se correría 60 s sin error → el test compara con la vela de la fixture AM_recorte.
def qty_de_evento(acciones: Optional[float]) -> int              # int(round(Decimal(str(acciones)))); None o ≤ 0 → 0 (ÚNICO sitio donde el float del Evento se convierte)
def qty_final(qty_senal: int, locates_libres: int, capital_qty: int, fraccion_max: Optional[Decimal], volumen_acum: Optional[int]) -> tuple[int, Decimal]   # (qty, fracción registrada) R-B-05, R-I-01, R-E-02
def abrir_intento(pos: PosicionTicker, lotes: list[Lote], cot: Cotizacion, precio_senal: Decimal, t_cierre: float, cfg: Config, ahora: float) -> IntentoEntrada   # t_limite = t_cierre + entrada.agregar_s; cfg_congelada
def orden_agregar(intento: IntentoEntrada, cot: Cotizacion, cfg: Config, token: int, hora_et: datetime) -> OrdenNueva   # SS qty punto_medio_arriba PostOnly TIF=DAY+ ruta agregar; con SSR el punto medio ya está ≥ bid + 1 tick (B19)
def sumar_senal(intento: IntentoEntrada, lote: Lote) -> tuple[IntentoEntrada, list[Accion]]   # R-B-03: Cancelar la viva, sumar, reiniciar con el total; MISMO t_limite
def al_vencer(intento: IntentoEntrada, cot: Cotizacion, cfg: Config) -> tuple[FaseIntento, Optional[str]]   # CANCELANDO si hay orden viva; luego CRUZANDO o TERMINADO("bid cayó > 3 %")
def resto_a_cruzar(intento: IntentoEntrada) -> int                # qty_total − llenas − (pendiente vivo); SOLO tras Canceled/cxlqty (corrección/injerto 5): nunca a partir de lo pedido
def orden_cruce(intento: IntentoEntrada, resto: int, cot: Cotizacion, cfg: Config, token: int, hora_et: datetime) -> Optional[OrdenNueva]   # SS resto a bajo_bid(bid, 0,5 %) ruta cruzar; None si bid < bid_senal·(1 − 3 %)
def repartir_fill(lotes: list[Lote], qty: int, precio: Decimal) -> list[tuple[str, int]]   # R-B-03 proporcional a lo pedido, resto al primero; enteros; suma == qty
def cerrar_intento(intento: IntentoEntrada, lotes: list[Lote]) -> list[Lote]   # llenas 0 → CANCELADO; > 0 → ABIERTO con precio_medio (R-B-02)
def fill_peor_de_lo_permitido(precio_fill: Decimal, bid_senal: Decimal, tope_pct: Decimal) -> bool   # B13 → aviso, se mantiene
def es_piramide_add(evento) -> bool; def es_piramide_reduce(evento) -> bool   # accion_piramide ∈ {"add"} / {"reduce","lot_stop","lot_tp"} (D13: las add siguen R-B-01)
```

### 3.16 `reglas/stops.py` (R-C-01 v3, R-C-04, R-C-06, R-C-07, R-C-10.4, R-C-11, R-F-02; injertos A §8.6 y §8.7; corrección 2 y 3)

```python
@dataclass(frozen=True) class NivelesStop: principal_disparo: Decimal; principal_limite: Decimal; emergencia_disparo: Decimal; emergencia_limite: Decimal; bajo_banda: bool
def niveles(L: Decimal, cfg_stops: dict, limit_up: Optional[Decimal] = None) -> NivelesStop
    # SUMADOS sobre L (23-sep): disparo L, límite L·(1+3 %), emergencia L·(1+13 %) / L·(1+63 %); redondeo ARRIBA al tick.
    # R-F-02: si un disparo ≥ limit_up → disparo = limit_up·(1 − margen) redondeado abajo, límite = disparo·(1+3 %); bajo_banda=True.
@dataclass(frozen=True) class StopDeseado: proposito: Proposito; nivel: Decimal; qty: int; disparo: Decimal; limite: Decimal
def conjunto_deseado(pos: PosicionTicker, cfg_stops: dict, limit_up: Optional[Decimal]) -> list[StopDeseado]
    # Sobre pos.neta (fills). Corto neto n = −neta > 0: UN principal por nivel L distinto con la suma de `llenas` de los lotes de ese nivel
    # (solo lotes con principal_consumido=False; suma capada a n), UNA emergencia con n entera sobre el L más alto. n ≤ 0 → [].
def inferir_proposito(o: MsgOrden | Orden, niveles_lotes: list[Decimal], cfg_stops: dict) -> Proposito
    # corrección 3: una STOPLMTP de COMPRA nuestra que no está en el diario del ejecutor (la puso el vigilante): disparo ≈ L (±1 tick) → STOP_PRINCIPAL;
    # disparo ≈ L·1,13 (±1 tick) → STOP_EMERGENCIA; otra cosa → STOP_PROTECCION
def plan(pos: PosicionTicker, vivas: list[Orden], cfg_stops: dict, limit_up: Optional[Decimal], tokens: Callable[[], int],
         hora_et: datetime, ruta_stop: str, version: int) -> list[Accion]
    # IDEMPOTENTE. deseado ↔ vivas (mismo propósito y nivel ±1 tick, CUALQUIER Origen: aquí está el NETEO de R-C-07):
    # falta → EnviarOrden(STOPLMTP B, serie=f"stops:{ticker}", version); qty distinta → Reemplazar(version) + Programar("replace_verificar"); sobrante → Cancelar la MÁS NUEVA.
    # Precondición (corrección 2): si pos.neta_das is not None y ≠ pos.neta_fills → devuelve [Consultar("GET POSITIONS"), Programar("stops_plan", 0.5)] y NO toca la emergencia
    # (una emergencia con más acciones que el corto real deja la cuenta LARGA, R-C-11 b).
def limpieza_tras_fill_stop(pos: PosicionTicker, vivas: list[Orden], cot: Cotizacion, tokens, cfg, hora_et: datetime, version: int) -> list[Accion]
    # R-C-11, por EVENTO. Siempre empieza por InvalidarSerie(f"stops:{ticker}", version) (injerto §8.6).
    # neta == 0 → CancelarTicker; neta > 0 (LARGA) → EnviarOrden(S neta al bid, ruta cruzar, VENTA_EXCESO) + Avisar(2) + Anotar("incidente") (vende SOLO la neta larga, JAMÁS la cantidad inicial);
    # neta < 0 (sigue corta) → marcar principal_consumido en el lote de ese nivel y plan() (cancela el principal, Reemplazar la emergencia a −neta; si DAS la cancela/rechaza → reponer).
def reasignar_principal_rebasado(pos, vivas, cot, cfg_stops, tokens, hora_et, ruta_stop, version) -> list[Accion]
    # R-C-01 decisión (a): ask > límite del principal de un nivel sin fill → Cancelar y sumar su qty al principal del nivel superior; si era el más alto → principal nuevo (disparo ask, límite ask·1,03)
def tipo_conserva_pp(tipo_das_crudo: Optional[str], patron_esperado: str) -> Optional[bool]   # 2h.8: tras REPLACE; None = aún sin %ORDER; patrón viene de cfg.stops.tipo_esperado_en_order (se fija el primer día con comprobar_das.py)
def stop_proteccion(ticker: str, qty: int, es_corta: bool, last: Decimal, pct: Decimal, token: int, ruta: str, version: int) -> OrdenNueva   # R-C-10 (4): +pct sobre last si corta / −pct si larga, STOPLMTP con límite +3 %
def descubiertas(pos: PosicionTicker, vivas: list[Orden]) -> int   # acciones netas cortas sin emergencia viva (Accepted/Partial) que las cubra; > 0 dispara R-C-03 y el plan B
def cantidad_cancelada(act: MsgOrderAct | MsgOrden) -> int         # injerto §8.7: SIEMPRE de `%OrderAct Canceled qty` / `%ORDER cxlqty`, nunca de lo pedido
```

### 3.17 `reglas/salidas.py` (R-D-02, R-D-03 v2, R-D-04, R-D-06, R-D-07, R-D-08, D10/D13, R-L-01, R-E-03; corrección 5 y 11)

```python
LITERALES_EXIT_REASON: dict[str, ClaseSalida] = {
    "TP": TP, "Partial TP": TP, "Partial TP (Hour)": HORA, "Partial TP (EOD)": EOD, "Partial TP (Time)": EOD, "EOD": EOD,
    "SL": STOP, "Pyramid Lot Stop": STOP_LOTE, "Pyramid Reduce": REDUCE, "Escalera": MOTOR,
    "Signal": MOTOR, "Trailing": MOTOR, "Time Limit": MOTOR, "?": MOTOR,
    "Halt": HALT, "Halt (atrapado)": HALT, "BS": BS, "BS Manual": BS, "Daily Limit": DAILY_LIMIT,
}   # portfolio_sim.py l.745-2265 + engine l.1142 ("?"). Un test extrae con regex TODOS los literales del fichero y exige que estén aquí.
def clasificar(motivo: Optional[str]) -> ClaseSalida             # desconocido → MOTOR + Anotar("salida_desconocida") (nunca lanza)
def tratamiento(clase: ClaseSalida, pos: PosicionTicker, lote: Lote, vivas: list[Orden]) -> str
    # TP → F4 (R-D-03). HORA/EOD → solo se anota (manda el reloj del ejecutor, R-D-08). REDUCE/STOP_LOTE → como TP con la qty del evento.
    # STOP (el backtester cerró por SL) con la posición aún abierta en DAS → "divergencia": NO perseguir; Anotar("divergencia_sl") + Avisar(2); la STOPLMTP residente manda (pregunta 4 a Jaume).
    # MOTOR (Signal/Trailing/Time Limit/Escalera/?) → "como_tp" PROVISIONAL: agregar 60 s en el punto medio y cruzar al ask con techo 3 % (R-D-03), Avisar(1) (pregunta 3 a Jaume).
    # HALT/BS → se anotan (el ejecutor tiene sus propias reglas F/G). DAILY_LIMIT → "ignorar" + Avisar(2) una vez al día (I1: sin cortacircuito).
def horas_de_salida(e: EstrategiaConfig, dia: date) -> tuple[Optional[datetime], datetime]   # (hora_salida, eod) en ET; eod = hora_fin_sesion
def ultimo_eod(estrategias: Iterable[EstrategiaConfig], dia: date) -> Optional[datetime]     # R-L-01: apagado = último EOD + 30 s
def temporizadores_lote(lote: Lote, e: EstrategiaConfig, dia: date, cfg_salidas: dict) -> list[Programar]   # "hora_agregar" (t−60 s), "hora_ask" (t), "eod_comprobar" (t+30 s), por lote
def orden_hora_agregar(lote: Lote, qty: int, cot: Cotizacion, cfg: Config, token: int, hora_et, proposito: Proposito) -> OrdenNueva   # B punto_medio_abajo PostOnly ruta agregar
def orden_al_ask(lote: Lote, qty: int, cot: Cotizacion, cfg: Config, token: int, hora_et, techo_pct: Optional[Decimal], proposito: Proposito) -> OrdenNueva   # techo None = SIN tope (R-D-08); 3 % (R-D-03); 5 % (R-D-06)
def perseguir_ask(orden: Orden, cot: Cotizacion, persecuciones: int, max_persecuciones: int = PERSEGUIR_ASK_MAX) -> Optional[Reemplazar]
    # corrección 11: a la hora, si no llena en 1 s, REPLACE de precio al ask nuevo (no Cancelar + nueva: la cuota de 100 CANCEL/min es compartida con los stops); como mucho 3; después manda eod_comprobar (+30 s → control humano)
def tp_parcial(lote: Lote, evento_qty: int, cot: Cotizacion, cfg: Config, token, hora_et) -> tuple[OrdenNueva, Programar]   # R-D-03 (1): B punto medio PostOnly + Programar("tp_cruce", 60)
def tp_al_vencer(lote: Lote, resto: int, cot: Cotizacion, cfg: Config, token, hora_et) -> tuple[Optional[OrdenNueva], Optional[Avisar]]   # cruce con techo 3 % sobre `last` DE ESE MOMENTO; ask > last·1,03 → (None, Avisar(2,"limbo"))
def prioridad(senales: list[Senal]) -> list[Senal]                 # R-D-07: salidas/TP → pirámides reduce/lot_* → pirámides add → entradas
def cerrar_todo(posiciones: dict[str, PosicionTicker], cot_de: Callable[[str], Optional[Cotizacion]], cfg, tokens, hora_et, proposito: Proposito) -> list[Accion]   # R-D-06: CancelarTicker + orden al ask/bid con techo 5 %; incluye manuales (neta_das)
def comprobar_eod(lote: Lote, pos: PosicionTicker) -> Optional[Avisar]   # R-D-02: +30 s con acciones vivas → Avisar(3) «EOD sin cerrar: control humano»
def puede_reentrar(e: EstrategiaConfig, lote_anterior: Optional[Lote], pos: PosicionTicker) -> tuple[bool, str]   # R-D-04: accept_reentries / max_reentries (−1 = manda accept_reentries; 0 = ninguna), R-F-03, R-G-03
def al_desactivar(e_vieja: EstrategiaConfig, e_nueva: Optional[EstrategiaConfig], lotes_vivos: list[Lote], cot_de, cfg, tokens, hora_et) -> list[Accion]
    # R-E-03 (flujo F14): "esperar_fin_dia" (defecto) → nada: el lote sigue con la definición vieja hasta su EOD; la nueva empieza mañana.
    # "cerrar_y_reiniciar" → como R-D-08 para los lotes vivos (agregar 60 s, luego al ask sin tope), Anotar + Avisar(1); la nueva versión opera desde la siguiente señal.
```

### 3.18 `reglas/halts.py` (R-F-01..06, R-G-02, B18, EP-2; injerto A §8.23)

```python
def es_halt(simb: EstadoSimbolo) -> bool                         # TA ∈ {"H","P"}
def fin_previsto(simb: EstadoSimbolo, ahora_et: datetime) -> Optional[datetime]   # P: TAT + 5 min (manual L1120); H: None (sin hora)
def al_entrar_en_halt(pos: PosicionTicker, vivas: list[Orden], simb: EstadoSimbolo, cot, franja: str) -> list[Accion]   # B18/R-F-04 a: Cancelar entradas vivas; R-G-02: Avisar(2) con tipo, hora, precio de parada, posición, stop, k, bandas
def decidir_reapertura(pos, simb, stops: NivelesStop, cot: Cotizacion, cfg_halts: dict, franja: str, duracion_min: float) -> str
    # "mantener" | "cerrar_mercado" | "cerrar_limite_pm" | "control_humano"
    # esc.1 stop por ENCIMA del precio de reapertura (o del último conocido): mantener si k < 3; k == 3 → cerrar. esc.2 stop por DEBAJO → cerrar sí o sí.
    # T1 (halt largo sin P): subida desde precio_parada > 250 % → control_humano. T12: mismo protocolo que T1 (Jaume 28-sep); cfg["t12_min"] se valida pero no decide (defecto 240) [PENDIENTE fuente externa].
    # franja == "premercado" → cerrar_limite_pm (R-F-06).
def cerca_de_banda(cot: Cotizacion, simb: EstadoSimbolo, k: int, cfg_halts: dict) -> bool   # k == 2 y ask ≥ limit_up·(1 − dist) → salir a mercado ANTES de que pare (ruta cruzar, HALT_BANDA)
def orden_reapertura(pos, qty: int, cot, decision: str, cfg, token: int, hora_et) -> OrdenNueva   # "cerrar_mercado" → B OPEN qty MKT (EP-2); "cerrar_limite_pm" → B límite ask·(1 + margen_pm) ruta cruzar
def momento_envio_open(fin: Optional[datetime], ahora_et: datetime, antes_s: int = HALT_ENVIAR_ANTES_FIN_S) -> float
    # injerto A §8.23: segundos hasta fin − 60 s; devuelve 0 (= AHORA) si el fin es desconocido, ya pasó o falta < 1 min
def debe_enviar_open(simb: EstadoSimbolo) -> bool                # guardia: not simb.orden_open_enviada (evita reenviar si $IssueStatus se repite y halt_decidir se reprograma)
def puede_reentrar_tras_halt(primera_vela_pct: Optional[Decimal], k: int, cfg_halts: dict) -> bool   # < 6 % y k < 3 (R-F-01 esc.2, R-F-03, R-F-04)
def senal_guardada_valida(senal: Senal, primera_vela_pct: Optional[Decimal], cfg_halts: dict) -> bool   # R-F-04 (b): X % [PENDIENTE] → cfg["primera_vela_max_senal_guardada_pct"], defecto 6
def primera_vela_pct(precio_reapertura: Decimal, cierre_primera_vela: Decimal) -> Decimal
```

### 3.19 `reglas/cisne_negro.py` (R-G-01, R-G-03)

```python
def se_activa(pos: PosicionTicker, stops: NivelesStop, vivas: list[Orden], cot: Cotizacion) -> bool   # last > emergencia_limite y −neta > 0 y la emergencia no se ha llenado del todo (aclaración 24-sep)
def activar(pos: PosicionTicker, stops: NivelesStop, ahora: float) -> EstadoBS
def toca_informe(bs: EstadoBS, ahora: float, cfg_tec: dict) -> bool          # 60 s × 5, luego cada 300 s; silenciado → False
def informe(pos, bs, stops, cot, simb, cuenta: Cuenta, ahora_et: datetime, eod: Optional[datetime], franja: str, fills: list[Fill]) -> str
    # los 16 campos de R-G-01 (2): stop normal y emergencia, bid/ask, minutos desde el evento, acciones al descubierto, % pérdida latente del trade, % y $ sobre la cuenta (con lo ya perdido),
    # máx % subida vs primer stop, % actual vs primer stop, pérdida ejecutada en $ y %, comandos, halts (solo RTH: distancia a banda, k), minutos desde el máximo y si lleva N min bajando, minutos hasta EOD, estado de la emergencia
def acciones_durante_bs(pos, vivas: list[Orden], cfg, version: int) -> list[Accion]   # R-G-03: SOLO Reemplazar qty de la emergencia a −neta; NUNCA reponer, ni mover, ni EnviarOrden
def al_cerrar(pos, dentro_de_emergencia: bool) -> tuple[Optional[Avisar], bool]   # (3): «POSICIÓN SACADA CON ÉXITO DENTRO DEL MARGEN DEL STOP DE EMERGENCIA» si cerró dentro; marca sin_reentrada_hasta_sigue
def fogonazo_visto(cot_hist: list[tuple[float, Decimal]], umbral_pct: Decimal) -> Optional[dict]   # R-G-01 (4): máximo, duración, devolución → diario (con o sin posición)
def cierre_humano(pos, vivas, cot, n: Optional[int], cfg, tokens, hora_et) -> list[Accion]   # /cerrar X [N] SI durante BS: Cancelar la emergencia ANTES (R-G-03.3) y luego orden_al_ask techo 5 % (R-D-06)
```

### 3.20 `reglas/rechazos.py` (R-B-07, R-C-03, EP-1)

```python
@dataclass(frozen=True) class Tratamiento: conocido: bool; clave: str; accion: str    # "recalcular_bp" | "recomprar_locate" | "subir_tick_ssr" | "reintentar" | "ninguna"
def cargar_catalogo(ruta: Path) -> list[dict]                     # [{clave, regex, accion, nivel}] de catalogo_rechazos.json
def clasificar(notas: str, catalogo: list[dict]) -> Tratamiento    # regex insensible a mayúsculas; desconocido → conocido=False
def decidir(orden: Orden, tratamiento: Tratamiento, pos: PosicionTicker, vivas: list[Orden], cfg, tokens, cot, hora_et) -> list[Accion]
    # SIEMPRE Avisar(B) con texto literal + orden + estado del ticker (nivel 2 si cubierta, 3 si no); conocido y orden.intentos < 2 → reintento con tratamiento y token NUEVO;
    # si no: descubiertas()==0 → pausa ticker (stops y salidas siguen; entradas no) + Avisar(2); > 0 → Avisar(3) «CONTROL HUMANO», el bot NO cierra (EP-1). Todo Anotar("rechazo").
    # Locate de un solo uso consumido NO es desconocido: estado que lleva el bot → "recomprar_locate" (F9).
def reintento_stop(orden: Orden, cfg_stops: dict, ahora: float) -> Optional[Programar]
    # R-C-03 (1)-(2): hasta 5 con separación cfg["separacion_reintentos_s"] (defecto 2 s [PENDIENTE]); Avisar(3) al agotarlos; el punto (3) «cerrar tras 5 intentos» NO se implementa (prima R-B-07/EP-1);
    # la ventana de 5 min y el 100 % se calculan y se anotan para el informe.
def tras_cancel_o_replace_rej(orden: Orden) -> list[Accion]        # injerto §8.7: CancelRej/ReplaceRej → Avisar(2) + Consultar("GET ORDERS") + Programar("barrido", 0) (barrido inmediato)
```

### 3.21 `reglas/capital.py` (2c, R-I-01, R-E-02)

```python
def margen_inicial_corto(precio: Decimal, qty: int, tasa_simbolo: Optional[Decimal]) -> Decimal   # < 5 $: máx(2,50·qty, 100 %·valor); ≥ 5 $: máx(5·qty, 30 %·valor); shortMarginRate (0 = defecto) si exige más
def margen_mantenimiento(precio: Decimal, qty: int) -> Decimal                                     # tramos < 2,50 / 2,50-4,99 / 5-16,66 / ≥ 16,67
def acciones_que_caben(qty_pedida: int, precio: Decimal, cuenta: Cuenta, tasa_simbolo: Optional[Decimal], exposicion_corta_usd: Decimal, alto_riesgo: bool, ahora: float, max_edad_s: float = RECONCILIACION_CADUCA_S) -> tuple[int, str]
    # R-I-01: BP no legible (leida_en None o edad > 30 s, R-K-03) → (0, "sin BP"); tope corto total 1× equity (0,5× alto riesgo); cabe parte → lo que quepa; R-E-02 orden de llegada: descuenta de cuenta.bp_reservado hasta el próximo GET BP
def reservar(cuenta: Cuenta, margen: Decimal) -> None; def liberar_reservas(cuenta: Cuenta) -> None   # se liberan con cada MsgBP
def exposicion_corta(posiciones: dict[str, PosicionTicker], cot_de) -> Decimal
def requiere_mas_margen(precio_antes: Decimal, precio_ahora: Decimal) -> bool     # cambio de tramo hacia arriba (2c: el vigilante avisa)
```

### 3.22 `reglas/locates.py` (R-H-01..05, EP-9, H6; corrección 1 y 10)

```python
def paquetes(qty: int, umbral_ultimo_pct: Decimal = LOCATES_UMBRAL_ULTIMO_PAQUETE_PCT) -> tuple[int, int]
    # H6 (21-sep): paquetes de 100 por lo bajo; el último SOLO si se usa MÁS del 30 %. Devuelve (n_paquetes, qty_ajustada = min(qty, n·100)).
    # 1.230 → (12, 1.200); 1.240 → (13, 1.240); 1.200 → (12, 1.200); 50 → (1, 50); 30 → (1, 30)?? → 30 % EXACTO no es «más del 30 %»: hoy (1, 30) por el mínimo de 1 paquete (pregunta 2 a Jaume); qty ≤ 0 → (0, 0).
def cantidad_a_localizar(e: EstrategiaConfig, estimacion: list[dict], precio: Decimal) -> int   # entrada + pirámides «add» al precio actual (riesgos_piramide del cuadro): usa `acciones` de la fila con fila["strategy_id"] == e.strategy_id (añadido por la fuente)
def veredicto_ev(e: EstrategiaConfig, precio: Decimal, qty: int, precio_accion_locate: Decimal, coste_ya_pagado: Decimal) -> dict
    # CORRECCIÓN 1: NO usa locates_gate.evaluar (paquetes_marginales = ceil(qty/100) contradice H6 y no admite coste acumulado). Reutiliza SOLO locates_gate.ev_fijo_para_precio(e.ev_pct, e.ev_rangos, precio)
    # y calcula: n, qty_aj = paquetes(qty); coste_nuevo = n·100·precio_accion; fade_pct = (coste_ya_pagado + coste_nuevo) / (qty_aj·precio) · 100 (R-H-05: el coste TOTAL entra en el EV);
    # entra = ev > fade. Devuelve {entra, ev_pct, fade_pct, margen_pct, paquetes, qty_ajustada, coste_nuevo, coste_total, ev_origen}.
def siguiente_paso(loc: Optional[Locate], e: EstrategiaConfig, ticker: str, precio: Decimal, ahora: float, cfg_loc: dict, gasto_dia: Decimal, equity: Optional[Decimal], deshabilitado: bool, ret: Optional[MsgSLRet], tokens) -> list[Accion]
    # máquina: buscando → LocateInquire(ALLROUTEWTTYPE1) cada 3 s (una consulta GLOBAL cada 3 s: CuotaComandos serializa; pregunta 7) → con %SLRET tipo 1, veredicto_ev.entra y not tope_superado → LocateComprar (cerrojo R-H-02: una compra por (ticker, estrategia, día))
    # → esperando → Located/parcial (R-H-04: seguir buscando el resto con coste total) → hecho. hora_limite → "parado". AlreadyShortable (RetType 2) → "no_hace_falta". deshabilitado → [].
def tope_superado(gasto_dia: Decimal, coste_nuevo: Decimal, equity: Optional[Decimal], pct: Decimal) -> bool   # R-H-03; equity None → True (sin cuenta no se compra)
def compra_repetida(locates: dict, ticker: str, strategy_id: str) -> bool     # R-H-02: segunda compra Located no pedida → deshabilitar el módulo entero
def asignar_a_lote(locates: dict, ticker: str, qty: int, strategy_id: str) -> list[tuple[str, int]]   # E9: primero a la estrategia que da señal; sobrantes a la siguiente
def caducados(locates: dict) -> list[Locate]                                   # no usados al cerrar el día → «caducados» (coste hundido)
def tras_reentrada(loc: Locate, reuse: Optional[MsgSLReuse]) -> str            # EP-9: Yes → reutiliza; No → vuelve a "buscando" con coste total
```

### 3.23 `reglas/exclusiones.py` (R-A-03 v2, R-A-04)

```python
def excluida(ticker: str, e: EstrategiaConfig, ficha: Optional[Ficha], splits_hoy: Optional[set[str]], lista_negra: list[str], hoy: date, cfg_ex: dict) -> Optional[str]
    # lista negra → "lista_negra"; ficha.sic_code ∈ SPAC_SIC → "spac" (siempre); e.es_rth y e.excluir_ipo y list_date > hoy − 30 d → "ipo"; ticker ∈ splits_hoy → "split";
    # ficha None → "sin_ficha" (A12: no se opera, se reintenta); splits_hoy None → NO excluye (corrección 17; el aviso lo pone el decisor una vez)
def banda_opa(muestras: list[tuple[float, Decimal, Decimal, Decimal]], max_pm: Decimal, cfg_ex: dict) -> bool   # (t, hi, lo, dólares) 30 min con rango ≤ 1,5 % y ≥ 100 k$ → AVISO (no salida)
def simbolo_das(ticker_massive: str) -> str                       # A7: identidad hoy; la equivalencia se aprende con MercadoDAS.sin_cotizacion_desde y se anota ("simbolo_no_casa")
```

### 3.24 `reglas/reconciliacion.py` (R-C-10, R-K-01/02/03, R-M-03; corrección 2)

```python
@dataclass(frozen=True) class Discrepancia: ticker: str; caso: int; detalle: str     # 1 coincide · 2 stop difiere · 3 sin stop · 4 desconocida (ajena) · 5 diario dice abierta y DAS no · 6 neta_fills ≠ neta_das
def comparar(estado: EstadoBot, pos_das: dict[str, MsgPos], ord_das: dict[int, MsgOrden], hoy: date, cfg) -> list[Discrepancia]   # orderSrc ≠ "CMDAPI" o token no nuestro (es_nuestro con hoy) → ajena (R-K-02)
def acciones(discrepancias: list[Discrepancia], estado, cot_de, cfg, tokens, hora_et, ruta_stop) -> list[Accion]
    # 1 nada · 2/3 → stops.plan() · 4 → stop_proteccion + Avisar(3) + pausa_global hasta /sigue (R-M-03) · 5 → lote CERRADO + Avisar(2) · 6 → neta_fills := neta_das (DAS manda, M7) + Anotar("discrepancia") + Avisar(2) + plan()
def cadencia_barrido(estado: EstadoBot, ahora: float, cfg_tec: dict) -> float   # 1 s si ahora − ultimo_fill_en < 60 o hay intento vivo; 2 s con posiciones; 10 s sin nada (R-K-01)
def comandos_barrido(tras_fill: bool) -> list[Consultar]          # GET POSITIONS, GET ORDERS, GET BP, GET LOCATES (+ GET TRADES tras fill)
def barrido_caducado(ultima_respuesta_en: Optional[float], ahora: float, tolerancia_s: float = RECONCILIACION_CADUCA_S) -> bool   # R-K-03 → modo_degradado.add("reconciliacion")
class AcumuladorVolcado:                                           # junta %POS/%ORDER/%TRADE entre marcadores (o 500 ms sin marcadores, §5.11) y entrega la foto completa
    def aplicar(self, msg: MensajeDAS, ahora: float) -> Optional[tuple[dict, dict, list]]
```

### 3.25 `reglas/vigilancia.py` (R-C-07 plan B, R-C-08, R-C-11 c, R-H-02/03, R-J-03, R-J-05, 2c; corrección 16)

```python
@dataclass(frozen=True) class Foto: posiciones: dict[str, MsgPos]; ordenes: dict[int, MsgOrden]; lotes: dict[str, list[Lote]]; latido_ejecutor_s: Optional[float]; cotizaciones: dict[str, Cotizacion]; gasto_locates: Decimal; compras_locate: list[Registro]; equity: Optional[Decimal]
def comprobar(foto: Foto, cfg: Config, ahora: float, tokens, hora_et, ruta_stop, puede_enviar: bool) -> list[Accion]
    # (a) por posición corta (neta_das < 0): exactamente UN principal por nivel (si no consumido) y UNA emergencia con qty = −neta → stops.plan() con Origen.VIGILANTE e inferir_proposito para las suyas.
    #     ACTÚA solo si latido_ejecutor_s is None o > PLAN_B_LATIDO_S, o si la posición lleva descubierta > PLAN_B_DESCUBIERTA_S con el ejecutor vivo. Si no toca actuar → solo Anotar.
    # (b) sobrantes → Cancelar la más nueva · (c) posición sin lote en ningún diario → stop_proteccion + Avisar(3) (R-C-10.4).
    # (d) R-H-02: dos Located para (ticker, estrategia, día) → Avisar(3) + Anotar("locates_deshabilitar") · R-H-03: gasto > 3 % de equity → ídem.
    # (e) 2c: margen de mantenimiento total > equity·cfg.tecnicos.vigilante.margen_aviso (defecto 0,8) → Avisar(2).
    # (f) precio pasó el nivel sin fill (R-C-08 a): SOLO aviso; cerrar queda [PENDIENTE] tras cfg.tecnicos.vigilante.cerrar_si_descubierta=False.
    # (g) corrección 16: si puede_enviar=False (la conexión de acción no pudo abrirse o el envío falló) y hay que reponer → Avisar(3) + PedirAlSupervisor("relanzar ejecutor") (plan B de R-C-07 vía relanzamiento a 1 s).
def debe_hacer_ping(watch_conectado: bool, latido_ejecutor_s: Optional[float], dentro_de_ventana: bool) -> bool   # R-J-05: silencio = alarma; fuera de ventana no se pinga
```

### 3.26 `decisor.py` (H-5; el ÚNICO que muta `EstadoBot`)

```python
class Decisor:
    def __init__(self, cfg: Config, estado: EstadoBot, mercado: MercadoDAS, referencia: Optional[Referencia], tokens: GeneradorTokens, catalogo_rechazos: list[dict], diario_degradado: Callable[[], bool]) -> None
    def procesar(self, msg: Mensaje, ahora: float, ahora_et: datetime) -> list[Accion]
        # despacho por tipo; cada rama que toca un ticker va en try/except → Anotar("excepcion", traceback), pos.estado = PAUSADO(motivo="excepcion"), Avisar(2), y el bucle sigue (H-5)
    def _senal(self, s: Senal, ahora, ahora_et) -> list[Accion]     # evento (salidas.prioridad → entrada / pirámide / salida), radar (locates), hidratado, latido_feed (R-J-01), dia_nuevo
    def _de_das(self, m: MensajeDAS, simulado: bool, ahora, ahora_et) -> list[Accion]
        # MsgOrderAct: Accept/Sending → estado; Execute → Fill al libro por token, neta_fills, version_stops += 1, InvalidarSerie, stops (F2); Canceled → cxlqty por cantidad_cancelada; Send_Rej → rechazos; CancelRej/ReplaceRej → tras_cancel_o_replace_rej
        # MsgTrade → Fill si no visto (dedupe por id_trade). MsgPos → neta_das (+ discrepancia 6 si ≠ neta_fills). MsgOrden → estado/tipo_das_crudo/ajenas. MsgQuote → mercado + BS/halt/banda/reasignar. MsgIssueStatus/LDLU/ShortInfo. MsgBP/AccountInfo → cuenta. MsgSL* → locates. MsgConexion → das_logon. MsgRouteStatus → rutas_habilitadas.
    def _temporizador(self, clave: str, datos: dict, ahora, ahora_et) -> list[Accion]
        # "cruce", "cancel_espera", "cruce_espera", "stops_ajustar", "stops_plan", "replace_verificar", "tp_cruce", "tp_espera_entrada", "hora_agregar", "hora_ask", "perseguir_ask", "eod_comprobar", "halt_decidir", "simstatus", "barrido", "bs_informe", "locate_inquire:X:S", "stop_reintento", "das_reconectar", "das_aviso", "foto"
    def _comando(self, c: Comando, ahora, ahora_et) -> list[Accion]
    def _config(self, nueva: Config, aviso: Optional[str], ahora) -> list[Accion]   # config.aplicar + Anotar("config_cambio") por diferencia (CM3) + al_desactivar (R-E-03) por estrategia que pasa a ejecutar=False o cambia definition_hash
    def _tic(self, ahora, ahora_et) -> list[Accion]                  # feed 30/60 s, DAS caído cada 5 min, reconciliación caducada, suscripciones, foto cada 2 s, disco
    def foto(self) -> dict                                            # panel 4.4
```

### 3.27 `ejecutor.py`, `vigilante.py`, `supervisor.py`, `herramientas/comprobar_das.py`

```python
# ejecutor.py
class Ejecutor:
    def __init__(self, cfg: Config, cliente: ClienteDAS | ClienteSombra, fuente: FuenteSenales, diario: Diario, avisos: ColaAvisos, mercado: MercadoDAS,
                 decisor: Decisor, reloj: Reloj, latido: Latido, cerrojo: CerrojoInstancia, receptores: list, config_watch: Optional[VigilanteConfig], ruta_estado: Path) -> None
    def arrancar(self) -> int          # F12: cerrojo → reloj (R-J-07) → motor_hash (H-6) → diario.abrir_dia → reconstruir (H-2) → conectar DAS → reconciliación ANTES de nada (R-J-02.5) → fuente.arrancar. Devuelve 0 o el código de Salir.
    def correr(self) -> int            # bucle: msg = cola.get(timeout=0.2) o Tic; acciones = decisor.procesar; ejecutar en orden; temporizadores (heap); latido.tocar(todo_vivo=hilos críticos vivos)
    def ejecutar(self, a: Accion) -> None
        # EnviarOrden: Anotar(orden_intencion, fsync) → [política corrección 4] → cliente.enviar(serie, version) → Anotar(orden_enviada); EnvioProhibido (sombra) → Anotar(orden_simulada) (no debería llegar: ClienteSombra desvía antes; si llega es un bug y se avisa 3)
        # Cancelar/Reemplazar igual con cancel_intencion/replace_intencion; InvalidarSerie → cliente.invalidar; Avisar → avisos.poner (+ Anotar("aviso")); Anotar → diario; Programar/Desprogramar → heap; Consultar/Suscribir/Locate* → cliente.enviar; PublicarFoto → estado/foto.json atómico; Salir → código
    def parar(self) -> None            # fuente, cliente, avisos.parar(30), diario.cerrar, cerrojo.soltar
def construir_desde_env(cfg: Config, reloj: Reloj, base: Path) -> Ejecutor
    # fase SOMBRA → ClienteDAS(solo_lectura=True) envuelto en ClienteSombra(Emparejador); CANARIO/REAL → ClienteDAS(solo_lectura=False) que EXIGE BOT_DAS_PERMITIR_ORDENES=1 (corrección 15)
    # fuente: BOT_DAS_FUENTE = tuberia (defecto; NO importa pandas) | proceso | grabacion=<ruta>
def main(argv) -> int                  # python -m app.bot_das.ejecutor [--config ruta] [--fuente tuberia|proceso|grabacion=ruta]; instala logging con FiltroSecretos ANTES de nada

# vigilante.py
class VigilanteDAS:
    def __init__(self, cfg: Config, watch: ClienteDAS, abrir_accion: Callable[[], Optional[ClienteDAS]], lector: LectorDiario, diario: Diario, avisos: ColaAvisos, reloj, latido: Latido, cerrojo, ruta_latido_ejecutor: Path, ping: Optional["PingExterno"], ruta_orden_supervisor: Path) -> None
    def correr(self) -> int            # cada 1 s: aplicar mensajes watch al libro (Parser propio, watch=True); Foto desde libro + lector.seguir(ejecutor); acciones = vigilancia.comprobar(..., puede_enviar); ejecutar con abrir_accion() (LOGIN normal bajo demanda; None → puede_enviar=False); ping cada 60 s si debe_hacer_ping; latido.tocar()
class PingExterno:
    def __init__(self, url: str, reloj, cada_s: float = PING_EXTERNO_S, abrir=urllib.request.urlopen) -> None   # BOT_DAS_PING_URL; sin URL → no pinga y avisa 2 una vez
    def tocar_si_toca(self, ahora: float) -> None

# supervisor.py
class PlanRelanzamiento:               # esperas (1, 2, 5, 10) y luego 10 s; se reinicia tras 300 s estable (R-J-04 v2)
class Supervisor:
    def __init__(self, cfg_ruta: Path, reloj, avisos: ColaAvisos, python: str, cwd: Path, das_exe: Optional[Path], ruta_estado: Path, diario: Diario) -> None
    def ventana(self, hoy: date) -> tuple[Optional[datetime], Optional[datetime]]   # R-L-01: cfg.horario.encender (defecto 03:55) → último EOD + 30 s; hay_sesion() del calendario; (None, None) = sin mercado
    def correr(self) -> int            # cerrojo; bucle 0,5 s: dentro de ventana → asegurar DAS (tasklist; si falta y hay das_exe → lanzar + Avisar(3) «LOGIN/2FA a mano», EP-7) → vigilante → ejecutor; latido con edad > COLGADO_S → terminate + relanzar; fuera → parar hijos; disco < 5 GB → aviso; lee estado/orden_supervisor.jsonl (peticiones del vigilante); al arrancar mata por PID guardado si el cerrojo está tomado por un proceso sin latido (riesgo 20)
    def lanzar(self, modulo: str) -> subprocess.Popen   # [python, "-m", f"app.bot_das.{modulo}"], cwd=backend, creationflags=CREATE_NEW_PROCESS_GROUP; entorno heredado (el .env lo carga cada hijo)

# herramientas/comprobar_das.py — el PRIMER DÍA con DAS real, en fase SOMBRA salvo los pasos marcados (canario mínimo, 1 acción)
def main(argv) -> int
    # 1 GET RouteStatus → lista y aviso de las rutas de la tabla que falten (SAGEREB, SAGEPRO, EDGA, MIAX, STOP/SMAT, OPEN)
    # 2 GET SymStatus X y GET LDLU X CON y SIN símbolo → qué contesta (§5.8) → escribe cfg.tecnicos.get_con_simbolo
    # 3 (canario, 1 acción) NEWORDER STOPLMTP → guarda la línea %ORDER CRUDA en fixtures/lineas_das.txt y fija cfg.stops.tipo_esperado_en_order
    # 4 (canario) REPLACE de cantidad sobre esa STOPLMTP → ¿conserva pre/post? (2h.8)
    # 5 (canario) PostOnly en SAGEREB y SMAT → aceptado/rechazado con el texto literal
    # 6 (canario) GET BP antes/después de poner principal + emergencia → BP retenido por los dos stops (EP-3)
    # 7 conexión watch: qué llega (%OrderAct? $Quote? marcadores?) y si una segunda conexión normal puede enviar (R-C-08)
    # 8 %POS de un corto de 1 acción → signo de qty (qty_corto_negativa)
    # 9 SLPRICEINQUIRE ALLROUTEWTTYPE1 de 100 → %SLRET real y SLRouteMinCharge ALLROUTE
    # Todo al diario `comprobacion_das` y a un informe de texto; NADA de esto se ejecuta solo: cada paso pide confirmación por consola.
```

---

## 4. Protocolo: comandos y mensajes

Fuente: `manual_2026.txt` (M), cotejado con la especificación del protocolo (§1-§5). Los literales entre comillas invertidas son los del manual.

### 4.1 Comando que enviamos → función de `protocolo.py`

| Comando (literal del manual) | Función | Cuándo lo usa el bot | Cita M |
|---|---|---|---|
| `LOGIN Trader Password Account 1/0` | `cmd_login(usuario, clave, cuenta, watch)` | ejecutor `0`; vigilante `1` (watch) | L243-255 |
| `NEWORDER token b/s symbol route share price [PostOnly] TIF=DAY+` | `cmd_neworder(OrdenNueva(tipo=LIMITE))` | entrada agregar/cruce, TP, salidas, venta de exceso, cierre humano | L543-547, L709-728, L767-770 |
| `NEWORDER token b/s symbol route share MKT TIF=DAY` | `cmd_neworder(tipo=MERCADO)` | solo reapertura tras halt por ruta `OPEN` (R-F-01, EP-2) | L549-553 |
| `NEWORDER token b/s symbol route share STOPLMTP StopPrice Price TIF=DAY+` | `cmd_neworder(tipo=STOP_LIMITE_PP)` | principal, emergencia, protección (ruta `STOP`/`SMAT`) | L618-624, L698-707 |
| `CANCEL orderid` | `cmd_cancel(id_das)` | cancelar agregar antes del cruce, stops sobrantes, TP | L802-806 |
| `CANCEL ALL` | `cmd_cancel_all()` | solo `/cerrar_todo SI` | L808-810 |
| `CANCEL ALLSYMB ticker` | `cmd_cancel_allsymb(ticker)` | limpieza R-C-11 con neta 0; cierre de lote; halt | L226-229, L812-816 |
| `REPLACE orderid share price` | `cmd_replace(id, qty, LIMITE, precio, None)` | perseguir al ask (máx. 3) | L819-825 |
| `REPLACE orderid share STOPLMT StopPrice Price` | `cmd_replace(id, qty, STOP_LIMITE_PP, precio, stop)` | ajustar cantidad de stops (R-C-07/11, R-G-03); NO documentado para STOPLMTP → `replace_verificar` | L850-854 |
| `GET BP` | `cmd_get("BP")` | barrido; antes de cada entrada; EP-3 | L988-1004 |
| `GET SHORTINFO Symbol` | `cmd_get("SHORTINFO", X)` | al entrar en el radar (tasa, shortable, RegSho) | L1005-1016 |
| `GET LDLU [Symbol]` | `cmd_get("LDLU", X)` | con Lv1 suscrito; en RTH con posición (R-F-02); argumento presunto (§5.8) | L1091-1093 |
| `GET SymStatus [Symbol]` | `cmd_get("SymStatus", X)` | cada 1 s con posición/intento; SSR al entrar; argumento presunto (§5.8) | L1095-1108 |
| `GET AccountInfo` | `cmd_get("AccountInfo")` | barrido lento, resumen diario, informe BS | L1134-1158 |
| `GET POSITIONS` / `GET ORDERS` / `GET TRADES` / `GET LOCATES` | `cmd_get("POSITIONS")` … | barrido R-K-01 | L1160-1170 |
| `POSREFRESH` | `cmd_get("POSREFRESH")` | tras reconexión (R-J-02.5) | L326-330 |
| `GET RouteStatus` | `cmd_get("RouteStatus")` | al arrancar (rutas reales de Sage) | L1558-1574 |
| `GET INTMSGS` | `cmd_get("INTMSGS")` | al arrancar y cada hora (mensajes del bróker) | L1611-1617 |
| `SB Symbol Lv1` / `UNSB Symbol Lv1` | `cmd_sb(X)` / `cmd_unsb(X)` | posiciones, intentos, radar (≤ 100) | L1172-1247 |
| `ReturnFullLv1 NO` | `cmd_return_full_lv1(False)` | al conectar (parche incremental, `mercado_das` lo maneja) | L1529-1534 |
| `SLPRICEINQUIRE Symbol LocateShares ALLROUTEWTTYPE1` | `cmd_sl_inquire(X, qty, "ALLROUTEWTTYPE1")` | R-H-01 cada 3 s (se evita `ALLROUTE`: crea órdenes `Offered`, §5.22) | L1648-1670 |
| `SLNEWORDER Symbol LocateShares Route token` | `cmd_sl_neworder(X, qty, ruta, token)` | compra (tokens `Origen.EJECUTOR_LOCATE`) | L1671-1685 |
| `SLOFFEROPERATION locateOrderId Accept|Reject` | `cmd_sl_offer(id, aceptar)` | rutas tipo 1 | L1692-1700 |
| `SLCANCELORDER locateOrderId` | `cmd_sl_cancel(id)` | hora límite de intentos | L1686-1691 |
| `SLReuseQuery Symbol` | `cmd_sl_reuse(X)` | al comprar y tras cada reentrada (EP-9) | L1810-1817 |
| `SLAvailQuery Account Symbol` | `cmd_sl_avail(cuenta, X)` | parcial (R-H-04) | L1796-1803 |
| `SLRouteMinCharge ALLROUTE` | `cmd_sl_min_charge("ALLROUTE")` | al arrancar (entra en el EV) | L1823-1832 |
| `ECHO` / `CLIENT` / `QUIT` | `cmd_get("ECHO")`, `cmd_get("CLIENT")`, `cmd_quit()` | sonda de vida; diagnóstico; cierre | L1459-1471, L1619-1621 |

NO se usan (y `es_mutante` los prohíbe en sombra igualmente): `COMPLEXORDER`, `SCRIPT`, `GSCRIPT` (OCO/Trigger solo por script, descartados 2h.9), `SB tms` (inunda), `SB Lv2`, `SB TopList`, `SB DAYCHART/MINCHART` (la señal viene de Massive, R-A-06).

### 4.2 Mensaje que recibimos → dataclass

| Palabra clave (literal) | Dataclass | Campos y trampas | Cita M |
|---|---|---|---|
| `%ORDER id token symb b/s mkt/lmt qty lvqty cxlqty price route status time origoid account trader orderSrc TIF Pref` | `MsgOrden(watch=False)` | 15 o 19 campos; `mkt/lmt` puede llevar espacios (anclaje por `status`+`time`); `status` ∈ 9 valores | L343-405, L930-932 |
| `%IORDER …` | `MsgOrden(watch=True)` | «Same definition with %ORDER» | L1436-1440 |
| `%OrderAct id ActionType B/S symbol qty price route time notes token` | `MsgOrderAct` | `ActionType` ∈ {`Sending`,`Send_Rej`,`Accept`,`Canceling`,`Canceled`,`CancelRej`,`TimeOut`,`Execute`,`Close`,`Replaced`,`Replacing`,`ReplaceRej`}; lado `Buy`/`Shrt`; `notes` vacío = dos espacios | L434-494, L934-944 |
| `%TRADE id symb b/s qty price route time orderid Liq EcnFee PL` | `MsgTrade(watch=False)` | 8 u 11 campos | L495-539 |
| `%ITRADE Account tradeID symbol Side TradeShares TradePrice route exeTime orderID Trader` | `MsgTrade(watch=True)` | OTRO orden de campos: rama propia | L1444-1458 |
| `%POS Symbol Type Quantity AvgCost InitQuantity InitPrice Realized CreateTime [Unrealized]` | `MsgPos(watch=False)` | `Type` 1 cash / 2 margin / 3 short; signo de `Quantity` no documentado → `normalizar_pos` | L256-323 |
| `%IPOS …` | `MsgPos(watch=True)` | | L1441-1443 |
| `#POS`, `#POSEND`, `#Order`, `#OrderEnd`, `#Trade`, `#TradeEnd`, `#SLOrder`, `#SLOrderEnd`, `#buyingpower bp,nbp` | `MsgMarcador` | se ignora lo que siga a la palabra clave | L257-276, L332-346, L507, L999, L1722 |
| `BP CurrentBP CurrentOverNightBP` | `MsgBP` | | L993-1004 |
| `$SHORTINFO Symbol shortable shortsize Marginable longMarginRate shortMarginRate ShortProhibited [RegSho]` | `MsgShortInfo` | `RegSho` opcional | L1017-1063 |
| `$STINFOEX symbol extendedInfo` | `MsgStInfoEx` | texto libre (`ConcLong: 200%,ConcShr: 50%;`) | L1064-1078 |
| `$LDLU symbol limitDown limitUp` | `MsgLDLU` | si no llega nada = sin dato (timeout corto, no error) | L1079-1090 |
| `$IssueStatus symbol SSR:Y/N TA:H/P/Q/T TAT:HH:MM:SS` (o `$SymStatus`) | `MsgIssueStatus` | `TA` ausente = normal | L1101-1133 |
| `$AccountInfo OpenEQ CurrEQ RealizedPL UnrealizedPL NetPL HTBCost SecFee FINRAFee ECNFee Commission` | `MsgAccountInfo` | 10 números | L1143-1158 |
| `$Quote symbol A: Asz: B: Bsz: V: L: Hi: Lo: op: ycl: tcl: PE: VWAP: T:` | `MsgQuote` | PARCHE: solo claves presentes; desconocidas conservadas | L1248-1316 |
| `$T&S symbol price volume flag time Exchange B/S/I condition` | `MsgTS` | no suscrito por el bot; parser preparado (bit 5 = válido para último precio) | L1317-1360 |
| `$Bar symbol date High Low Open Close Volume [MinType]` | `MsgBar` | no suscrito; HLOC | L1373-1435 |
| `$RouteStatus ROUTE Enabled/Disabled` | `MsgRouteStatus` | sin marcador de fin | L1567-1574 |
| `$INTMSG Send Time:` / `From:` / `To:` / `Title:` / `Msg:` | `MsgIntMsg` | multilínea; `\t` = salto en `Msg`; `Msg` es la última parte | L1575-1610 |
| `%SLRET RetType Symbol OfferPrice OfferSize Route Notes [Account]` | `MsgSLRet` | `RetType` 1 normal / 2 fallo (`Notes` = motivo, p. ej. `AlreadyShortable`) | L1701-1720 |
| `%SLOrder locateOrderID symbol shares openshares exeshares exeprice status route time lmtPrice [token] notes` | `MsgSLOrder` | `status` ∈ {`Pending`,`Waiting`,`Located`,`Offered`,`Canceled`,`Rejected`,`Closed`,`Declined`} | L1722-1795 |
| `$SLAvailQueryRet Account Symbol AvailableLocateShares` | `MsgSLAvail` | | L1804-1809 |
| `$SLReuseQueryRet Symbol Yes/No` | `MsgSLReuse` | | L1818-1822 |
| `SLRouteMinChargeRet Route $minCharge` (con o sin `$` delante) | `MsgSLMinCharge` | 0 = sin mínimo | L1833-1838 |
| `#OrderServer:Logon:Successful` … `#OrderServer:Lost Connection` (12 líneas) | `MsgConexion` | comparación entera | L1472-1490 |
| `$TopLst`, `$Lv2`, respuestas de `ECHO`/`CLIENT`, cualquier `#…` no listado | `MsgInformativo` | se registran | L1361-1370, L1536-1557 |
| lo demás | `MsgDesconocido` | nunca se lanza | — |

### 4.3 Las 29 ambigüedades y dónde se resuelven

§5.1 `\r\n` → `FIN_LINEA`/lector · §5.2 tipo con espacios → parser anclado + fixture + paso 3 de `comprobar_das` · §5.3 opcionales → parse por número de campos · §5.4 notas/token → `es_nuestro` · §5.5 `Buy`/`Shrt` → `LADOS` · §5.6 REPLACE STOPLMTP → `tipo_conserva_pp` + `replace_verificar` · §5.7 precio de disparo → canario (F2, medido) · §5.8 GET con símbolo → `cfg.tecnicos.get_con_simbolo` + `comprobar_das` paso 2 · §5.9 `$IssueStatus`/`$SymStatus` → parser · §5.10 `SLRouteMinChargeRet` → parser · §5.11 volcados sin marcadores → `AcumuladorVolcado` · §5.12 cierre no comunicado / signo → `neta_fills` + barrido + `normalizar_pos` · §5.13-14 marcadores/`#buyingpower` → `MsgMarcador` · §5.15 sin acuse de sintaxis → todo comando con `Programar` de comprobación + barrido · §5.16 `GTC=DAY+` → siempre `TIF=` · §5.17 GTD con segundos → no se usa · §5.18 token int32 → `tokens.py` · §5.19 `$Quote` incremental → `MercadoDAS` · §5.20 `condition` → entero, canario · §5.21 `$STINFOEX` → regex · §5.22 `ALLROUTE` → `ALLROUTEWTTYPE1` + `es_mutante` · §5.23 `Account` → `Config.cuenta_das` del `.env` · §5.24 watch → `comprobar_das` paso 7 y parser tolerante · §5.25 `ECHO`/`CLIENT` → `MsgInformativo` · §5.26 estados con espacio → comparación entera · §5.27 rutas → `GET RouteStatus` + `rutas_habilitadas` · §5.28 decimales → `formatear_precio` (LANZA) · §5.29 cuotas → `CuotaComandos` al 90 %.

---

## 5. Flujos de secuencia

Notación: `→` llamada; `⇒` acción devuelta por el decisor y ejecutada por el ejecutor; «diario» = `Anotar`.

**F1. Entrada v3 (R-B-01/02/04, R-A-01, R-I-04, R-C-09, R-H-04, R-I-01, R-M-05).**
1. `FuenteTuberia` recibe `{"t":"eventos", eventos:[Evento entrada Short]}` → `SenalRecibida(Senal(id=id_evento))` en la cola. Si `cfg.alertas_grupo_a.activo` y `e.avisar_grupo_a` ⇒ `Avisar(1, A, texto_grupo_a([ev]))` INMEDIATO y antes de cualquier guarda (el socio recibe lo mismo que hoy; `put_nowait`, microsegundos).
2. `Decisor._senal` → diario `senal` → `entrada.evaluar_senal` (16 comprobaciones en ese orden). `ok=False` ⇒ diario `senal_descartada(motivo)` + `Avisar(1, B)` si `avisar`; fin. `guardar_para_reapertura` ⇒ `pos.senal_guardada_halt = s`.
3. `qty_de_evento` → `capital.acciones_que_caben` (reserva BP) + `locates.asignar_a_lote` → `entrada.qty_final` (fracción de volumen al diario `metrica`). `qty == 0` ⇒ descartada y `liberar` reserva.
4. Si `pos.intento` vivo → F3 (R-B-03). Si no: `abrir_intento` (`t_cierre = t_cierre_vela(momento)`, `t_limite = t_cierre + 60 s`) → `orden_agregar` ⇒ `Anotar(lote, fsync)`, `EnviarOrden(SS qty punto_medio_arriba PostOnly ruta agregar TIF=DAY+)`, `Programar("cruce", t_limite − ahora)`, `Suscribir(ticker)` si no lo estaba, `Programar("simstatus", 1)`.
5. Ejecutor: `orden_intencion` (fsync) → (política de disco) → `cliente.enviar` → `orden_enviada`. DAS: `%OrderAct Sending/Accept` + `%ORDER Accepted` ⇒ `id_a_token`, estado. Latencia orden→Accept al diario `metrica` (J18); `senal_a_orden_ms` (R-M-05).
6. Fills: `%OrderAct Execute` (y `%TRADE`, dedupe por `id_trade`) → `Fill` al libro por token, `neta_fills`, `version_stops += 1` ⇒ `InvalidarSerie` → `repartir_fill` entre lotes → **PRIMER fill ⇒ F2 al instante (sin debounce)**; fills siguientes ⇒ `Programar("stops_ajustar", STOP_DEBOUNCE_S)` (coalesce: técnico, `stops.debounce_s`, justificación 100 REPLACE/min; la red de seguridad es el barrido a 1 s de R-K-01) y un ajuste final al cerrar el intento. `fill_peor_de_lo_permitido` ⇒ `Avisar(2)` y se mantiene (B13).
7. `Temporizador("cruce")`: `al_vencer` → si hay orden viva ⇒ `Cancelar(agregar)` + `Programar("cancel_espera", 0.5)`; el resto se calcula SOLO tras `%OrderAct Canceled` (`cantidad_cancelada`) o, si no llega, tras `GET ORDERS` (`cxlqty`): nunca de lo pedido. Luego `orden_cruce`: `bid_ahora ≥ bid_senal·0,97` ⇒ `EnviarOrden(SS resto bajo_bid(bid, 0,5 %) ruta cruzar)` + `Programar("cruce_espera", 2)`; si no ⇒ `senal_descartada("bid cayó > 3 %")` + `Avisar(1)` + `cerrar_intento` con lo llenado.
8. `Temporizador("cruce_espera")`: sin fill completo y `reintento_cruce == 0` ⇒ `Cancelar` + (tras `Canceled`) un reintento con el bid nuevo si sigue dentro del 3 %; si no ⇒ `cerrar_intento` (lo que haya con su stop proporcional, R-B-02; 0 llenas → CANCELADO). B11: en PM tampoco hay excepciones.
9. Al cerrar el intento ⇒ `Avisar(1, B, texto_fill)` (llenas, precio medio, slippage vs `precio_senal` al diario), `salidas.temporizadores_lote`, `Desprogramar("cruce*")`, `Programar("barrido", 0)`.

**F2. Stops STOPLMTP y limpieza (R-C-01 v3, R-C-11, R-C-06/07, R-F-02, 2h.8; injertos §8.6/§8.7; corrección 2).**
1. Tras cada fill de entrada/pirámide/TP y tras cada `Canceled/Rejected` de un stop: `stops.plan(pos, vivas, cfg.stops, limit_up, tokens, hora_et, ruta, version=pos.version_stops)`. Precondición: si `neta_das` conocida ≠ `neta_fills` ⇒ `Consultar("GET POSITIONS")` + `Programar("stops_plan", 0.5)` y NO se toca la emergencia. Si cuadra ⇒ `EnviarOrden(B STOPLMTP disparo=L límite=L·1,03 qty=Σ lotes(L), serie="stops:X")` por nivel + `EnviarOrden(B STOPLMTP L_max·1,13 / L_max·1,63 qty=−neta)`. Idempotente: si ya existen (de cualquier `Origen`, incl. VIGILANTE) no duplica; qty distinta ⇒ `Reemplazar(version)` + `Programar("replace_verificar", 1.0, {token})`.
2. `Temporizador("replace_verificar")`: `tipo_conserva_pp(orden.tipo_das_crudo, patrón)` → `False` ⇒ `Cancelar` + `EnviarOrden` nueva (2h.8); `None` (sin `%ORDER` aún) ⇒ reprogramar hasta 3 veces; luego `Avisar(2)`.
3. Fill de un stop (`Execute` con token de propósito `STOP_*`): `limpieza_tras_fill_stop` ⇒ `InvalidarSerie("stops:X", version+1)` (cualquier `Reemplazar` viejo en la cola de salida se descarta); neta 0 ⇒ `CancelarTicker` (al instante, decenas de ms); neta LARGA ⇒ `EnviarOrden(S neta al bid, ruta cruzar, VENTA_EXCESO)` + `Avisar(2)` + diario `incidente` (vende SOLO la neta larga: 100 cortas, principal 20, emergencia 100 → larga 20 → vende 20, JAMÁS 100); sigue CORTA ⇒ `principal_consumido=True` → `plan()` cancela el principal y reemplaza la emergencia a `−neta`. Siempre exactamente una emergencia.
4. `$Quote`: `reasignar_principal_rebasado` (ask > límite del principal sin fill) ⇒ cancelar y sumar al nivel superior / principal nuevo al ask + 3 %.
5. `$LDLU` nuevo o al colocar: `niveles(..., limit_up)` baja el disparo bajo la banda (R-F-02); si DAS rechaza ⇒ F8 sobre un stop = R-C-03 (`reintento_stop`, 5 intentos) y, si sigue descubierta, plan B del vigilante (F13).
6. R-C-04: `Temporizador("barrido")` cada 1 s con posiciones (F10) compara `conjunto_deseado` con las `%ORDER` vivas ⇒ `plan()` repone; `%OrderAct Canceled` de un stop no pedido por nosotros ⇒ `plan()` inmediato + `Avisar(2)`.

**F3. Fill parcial y varias señales (R-B-02, R-B-03).** Segunda señal de otra estrategia con intento vivo: `sumar_senal` ⇒ `Cancelar(agregar)`, nuevo lote en `intento.lotes`, `qty_total += qty`, y al confirmarse `Canceled` (cantidad por `cantidad_cancelada`) se REINICIA desde F1.4 con el total; MISMO `t_limite` (la caducidad es de la primera señal). `repartir_fill` proporcional a lo pedido. Al vencer, cada lote queda con sus `llenas` y `plan()` pone un principal por nivel (dos estrategias, dos L) y una emergencia sobre el L más alto (EP-6 se mide en canario).

**F4. Take profit parcial (R-D-03 v2, R-D-07, R-C-07).**
1. `Senal` con `Evento salida` (`clasificar(motivo) == TP`) o pirámide `reduce/lot_tp` → lote por `(ticker, strategy_id)` (+ `entrada_idx` si hay reentradas); qty = `qty_de_evento` (tope `lote.llenas − lote.tp_pendiente`).
2. `salidas.prioridad`: si en la misma tanda hay una entrada de otra estrategia ⇒ TP primero **al ask** (`orden_al_ask techo=None`, remover) y la entrada espera al fill/cancel del TP (`Programar("tp_espera_entrada")`). Sin conflicto ⇒ `tp_parcial`: `EnviarOrden(B qty punto_medio_abajo PostOnly ruta agregar)` + `Programar("tp_cruce", 60)`.
3. Cada fill ⇒ `plan()` reduce los stops a lo que queda (R-C-07). `Temporizador("tp_cruce")`: `tp_al_vencer` → cruce con techo 3 % sobre `last` de ese momento; `ask > last·1,03` ⇒ `Avisar(2, "limbo")`, sin perseguir. Compra de más por fogonazo ⇒ F2.3 (venta del exceso).

**F5. Salida por hora y EOD (R-D-08, R-D-02; corrección 11).** `temporizadores_lote` al abrir el lote: `hora_agregar` (t − 60 s) ⇒ `EnviarOrden(B punto medio PostOnly, HORA_AGREGAR)`; `hora_ask` (t) ⇒ `Cancelar` lo vivo y, tras `Canceled`, `orden_al_ask(techo=None, HORA_ASK)`; sin fill en 1 s ⇒ `perseguir_ask` → `Reemplazar(precio=ask nuevo)` como mucho 3 veces (nada de `CANCEL` + nueva: la cuota de 100/min es compartida con los stops); `eod_comprobar` (t + 30 s) ⇒ `comprobar_eod` → `Avisar(3, "EOD sin cerrar: control humano")` + `pos.estado = CONTROL_HUMANO` (el ticker deja de abrir; los stops siguen). Los `Evento salida` con `clasificar ∈ {HORA, EOD}` solo se anotan: el reloj del ejecutor manda. Cierre completo ⇒ `CancelarTicker` + lote CERRADO + `Avisar(1)` + `liberar_reservas`.

**F6. Halt con ruta OPEN (R-F-01/04/05/06, R-G-02, B18, EP-2; injerto §8.23).**
1. `Temporizador("simstatus")` cada 1 s para tickers con posición/intento ⇒ `Consultar("GET SymStatus X")`; `MsgIssueStatus TA:H|P` → `mercado.marcar_halt` → `halts.al_entrar_en_halt` ⇒ `Cancelar` entradas vivas (B18), `Avisar(2, R-G-02 con LDLU)`, `pos.estado = HALT`, `Programar("halt_decidir", momento_envio_open(fin_previsto, ahora))`.
2. `Temporizador("halt_decidir")` (un minuto antes del fin previsto, o al instante si < 1 min, sin hora o ya pasado): `decidir_reapertura` → `"cerrar_mercado"` y `debe_enviar_open` ⇒ `EnviarOrden(B OPEN qty MKT, HALT_OPEN)` + `simb.orden_open_enviada = True` (EP-2: `Send_Rej` ⇒ F8 y reintento al reabrir por ruta cruzar al ask); `"cerrar_limite_pm"` ⇒ límite ask·(1 + margen_pm) ruta cruzar; `"control_humano"` (T1 > 250 %, T12) ⇒ `Avisar(3)` + `CONTROL_HUMANO` para ese ticker; `"mantener"` ⇒ nada. Un `$IssueStatus` repetido reprograma `halt_decidir` pero la guardia impide una segunda MKT.
3. Reapertura (`TA:T|Q` o cotización viva): segundo `Avisar(2)` con precio y lo hecho; `orden_open_enviada = False`; k actualizado; `senal_guardada_halt` ⇒ `senal_guardada_valida` (primera vela < X %, k < 3) ⇒ F1; reentradas por `puede_reentrar_tras_halt`. Con k = 2 y `cerca_de_banda` en RTH ⇒ salida a mercado por ruta cruzar (`HALT_BANDA`) antes de que pare.

**F7. Cisne negro (R-G-01, R-G-03).** `$Quote` con posición: `se_activa` ⇒ `activar` → `Avisar(3, informe, clave="bs:X")` (Telegram + correo + SMS por niveles), `Programar("bs_informe", 60)`, `pos.estado = BS`, `Anotar(bs)`. Cada `Temporizador("bs_informe")`: `toca_informe` ⇒ `Avisar(3, informe)` y reprogramar (60 s × 5, luego 300 s). Mientras: `acciones_durante_bs` (SOLO `Reemplazar` qty de la emergencia a `−neta`; `plan()` desactivado para ese ticker; NO reponer si DAS cancela). `/cerrar X SI` ⇒ `cierre_humano`: `Cancelar(emergencia)` → `orden_al_ask` techo 5 % × 3 (R-D-06). Cierre dentro de la emergencia ⇒ `al_cerrar` → `Avisar(3, "SACADA CON ÉXITO…")`; `sin_reentrada_hasta_sigue = True`. `/parar_avisos X BS` ⇒ `bs.silenciado`. `fogonazo_visto` con o sin posición ⇒ diario. Si la emergencia o el principal cierran TODA la posición ⇒ no hay protocolo (R-G-03): el ticker sigue operable.

**F8. Rechazo y pausa (R-B-07, R-C-03, EP-1).** `MsgOrderAct Send_Rej` → `rechazos.clasificar(notas)` → `decidir` ⇒ `Avisar(2|3, texto literal + orden + estado)` SIEMPRE; conocido e `intentos < 2` ⇒ tratamiento (`recalcular_bp` → `Consultar("GET BP")` y reenviar; `recomprar_locate` → F9; `subir_tick_ssr` → precio + 1 tick) con token NUEVO; si no: `descubiertas() == 0` ⇒ `PAUSADO` (stops y salidas siguen) + `Avisar(2)`; `> 0` ⇒ `Avisar(3, "CONTROL HUMANO")`, sin cierre. `Send_Rej` de un STOP ⇒ `reintento_stop` hasta 5 (separación 2 s [PENDIENTE]); el vigilante repone en paralelo si pasa `PLAN_B_DESCUBIERTA_S`. `/reanudar X` o `comandos.jsonl {"comando":"reanudar_ticker"}` ⇒ NORMAL. `CancelRej`/`ReplaceRej` ⇒ `tras_cancel_o_replace_rej` (aviso 2 + `GET ORDERS` + barrido inmediato).

**F9. Locates escalonados (R-H-01/02/03/04/05, EP-9; corrección 1 y 6).** `Senal(clase="radar", estimacion con strategy_id)` → por estrategia cuya condición previa cumple: `cantidad_a_localizar` → `siguiente_paso` ⇒ `LocateInquire(X, qty, "ALLROUTEWTTYPE1")` + `Programar("locate_inquire:X:S", 3.0)` (`CuotaComandos` serializa a una consulta cada 3 s en total; con 10 tickers el último espera 30 s: pregunta 7). `MsgSLRet tipo 1` → `veredicto_ev` (EV fijo por tramo con `ev_fijo_para_precio`; fade con `paquetes()` H6 y coste TOTAL acumulado) y `tope_superado` ⇒ `LocateComprar(SLNEWORDER X qty_ajustada ruta token)`; `MsgSLOrder Offered` ⇒ `LocateOferta(Accept)` si el EV sigue ok; `Located` ⇒ `localizadas`, `gasto_locates_dia += coste`, `Anotar(locate_estado)`; parcial ⇒ sigue buscando el resto (R-H-04). Segunda estrategia que cruza su umbral ⇒ compra propia con su EV. Reentrada ⇒ `Consultar("SLReuseQuery X")` → `No` ⇒ `tras_reentrada` vuelve a buscar con coste total. `compra_repetida` ⇒ `locates_deshabilitados = True` + `Avisar(3)`. Al cerrar el día `caducados` al diario.

**F10. Reconciliación (R-K-01/02/03, R-C-10).** `Temporizador("barrido")` con `cadencia_barrido` ⇒ `comandos_barrido()`; respuestas por `AcumuladorVolcado` ⇒ `comparar` → `acciones`: caso 2/3 ⇒ `plan()`; caso 4 (orderSrc ≠ CMDAPI o token ajeno, incl. tokens de AYER) ⇒ `stop_proteccion` + `Avisar(3)` + `pausa_global` hasta `/sigue` (R-M-03); caso 5 ⇒ lote CERRADO + `Avisar(2)`; caso 6 ⇒ `neta_fills := neta_das` + `Anotar(discrepancia)` + `Avisar(2)` + `plan()`. `barrido_caducado` (30 s sin respuesta con socket vivo) ⇒ `modo_degradado.add("reconciliacion")` (no abrir) + `Avisar(2)`; al volver ⇒ barrido completo + `Avisar(1, "recuperado")`. SIEMPRE un barrido tras cada fill, cancelación, `CancelRej` y reconexión.

**F11. Caída y relanzamiento (R-J-01/02/03/04/05).** (a) DAS: EOF o `MsgConexion Lost Connection/Missing heartbeat` → `ConexionDAS(False)` ⇒ `Avisar(3)` a la primera, `modo_degradado.add("das")` (no abrir, no gestionar: stops residentes), `Programar("das_reconectar", PlanReconexion.siguiente())` 2/4/8/16/30 s; `Programar("das_aviso", 300)` mientras siga; `#OrderServer:Logon:Failed` ⇒ `Avisar(3, "LOGIN/2FA a mano")` (EP-7). Al conectar ⇒ F12 completo ANTES de enviar nada. (b) Feed: `Senal(latido_feed)` cada 5 s desde bot.py; `Tic` mide `ahora − feed_ultima_vela_en` en horario de mercado: > 30 s ⇒ diario `feed` (prealerta interna); > 60 s ⇒ `Avisar(3)` + `modo_degradado.add("feed")` (mantener con stops, no abrir, vigilancia con precio de DAS: R-D-05). (c) Ejecutor muerto/colgado: supervisor ve `Latido.edad > 3 s` ⇒ `terminate()` + `PlanRelanzamiento` (1/2/5/10 s) + `Avisar(3)`; el vigilante gestiona mientras (F13). (d) Vigilante muerto ⇒ supervisor relanza + `Avisar(2)`; el ejecutor sigue abriendo. (e) Doble instancia ⇒ `adquirir() == False` → `Salir(3)` + `Avisar(3)`. (f) Ping externo: `debe_hacer_ping` False ⇒ silencio ⇒ alarma del servicio a los 3 min. (g) Hilo de borde muerto ⇒ `HiloVigilado` lo relanza (máx. 5) y `HiloCaido` en la cola ⇒ `Avisar(2)`; si no revive, `latido.tocar(todo_vivo=False)` ⇒ el supervisor relanza el ejecutor entero (injerto §8.11).

**F12. Arranque con posiciones (R-C-10, R-J-06/07, H-2/H-6, R-O-01).** `Ejecutor.arrancar`: cerrojo → `desvio_sntp` → `veredicto_reloj` (> 2 s ⇒ `Salir(2)`, > 0,5 s avisa) → `cargar_con_respaldo` → `motor_hash(base) == cfg.motor_hash` (si no ⇒ `Avisar(3)` + `Salir(4)`) → `diario.abrir_dia` (versión, hashes) → `reconstruir(LectorDiario.leer(hoy))` (los dos diarios) → `cliente.conectar()` → el LOGIN devuelve `#POS…#POSEND/#Order…/#Trade…` → `comparar` → 6 casos ⇒ acciones (stops, protección, avisos) → `Consultar("GET RouteStatus")`, `GET BP`, `GET AccountInfo`, `GET INTMSGS`, `SLRouteMinCharge ALLROUTE` → solo entonces `fuente.arrancar()` y `vigilando` efectivo. Stops caducados a las 20:00 tras halt multi-día quedan cubiertos por el caso 3.

**F13. Reinicio a mitad de mañana (H-2, R-C-07 neteo; corrección 3).** El supervisor relanza; F12 corre: `reconstruir` devuelve `senales_vistas` (no se reentra en señal ya operada), lotes con `llenas`, `ultimo_seq_token` (no se reutiliza un token), locates comprados/usados (no se recompra), pausas y BS; los temporizadores de salida se REPROGRAMAN desde `temporizadores_lote` (son de reloj, no de estado); `plan()` ADOPTA las órdenes con `Origen.VIGILANTE` (propósito por `inferir_proposito` si no están en el diario del ejecutor; mismo propósito + nivel ⇒ satisfacen el deseado; no se duplican); intentos que quedaron a medias se cierran (`cerrar_intento`) con lo que DAS diga que llenó (`%TRADE` del volcado por token).

**F14. Estrategia desactivada o versión nueva con lote vivo (R-E-03).** `ConfigNueva` ⇒ `diferencias` detecta `ejecutar: true→false` o `definition_hash` distinto en una estrategia con lotes vivos ⇒ `salidas.al_desactivar`: `esperar_fin_dia` (defecto) ⇒ nada (el lote sigue con la copia vieja en `EstrategiaConfig` congelada en el lote hasta su EOD; la nueva empieza mañana); `cerrar_y_reiniciar` (botón o `/cerrar_y_reiniciar` en dos pasos) ⇒ salida como R-D-08 (agregar 60 s, luego al ask sin tope, `CIERRE_REINICIO`) + `Avisar(1)` y la versión nueva opera desde la siguiente señal. Un cambio de `definition_hash` con el bot encendido es `[A]`: `config.aplicar` lo rechaza y avisa; solo los botones de R-E-03 lo resuelven.

---

## 6. Concurrencia y arranque

### 6.1 Procesos, hilos y colas

| Proceso | Hilos | Colas | Quién decide |
|---|---|---|---|
| `supervisor` (raíz) | principal (bucle 0,5 s); `avisos-envio` | `ColaAvisos` propia | nadie: solo lanza, mide latidos y para |
| `ejecutor` | **principal = el ÚNICO que muta `EstadoBot`** (`Decisor`); `das-lector` (socket → cola); `das-emisor` (cola de salida con `CuotaComandos` y descarte por serie/versión); `fuente-tuberia` (Listener → cola); `config-vigia` (mtime 1 s → cola); `telegram-recibo` (getUpdates → cola); `comandos-fichero` (jsonl → cola); `avisos-envio` (Telegram A/B, correo, SMS). Todos los de borde son `HiloVigilado`. | `cola: queue.Queue[Mensaje]` **sin tope** (una señal no se tira jamás; DAS produce decenas de líneas/s como mucho; aviso 2 si > 10.000); `cliente._salida` (tope 1.000); `ColaAvisos` (tope 10.000, cuenta perdidos) | `Decisor.procesar` en el hilo principal, sin locks: ningún otro hilo toca `EstadoBot` |
| `vigilante` | principal (bucle 1 s, `vigilancia.comprobar`); `das-lector` (watch); `das-lector-accion` (normal, bajo demanda); `avisos-envio` | cola de mensajes watch; `ColaAvisos` | principal |

Decisiones y por qué:
- **Sin asyncio.** El único socket con ritmo propio es DAS (texto por líneas): un hilo lector bloqueante es más simple de probar y de matar que un bucle de eventos, y el bot de alertas ya demostró (23-sep) que lo que importa es que el hilo que decide no compute en el lector. El GIL no es problema: el principal hace aritmética de milisegundos; los demás esperan en I/O.
- **Un solo mutador.** Los hilos de borde hacen `cola.put(Mensaje)` y vuelven. Las `reglas/*` reciben objetos que solo el principal usa. Los tests del decisor son secuenciales y deterministas (reloj inyectado).
- **Temporizadores** = heap `(cuando_mono, clave, datos)` en el hilo principal, revisado en cada vuelta (≤ 200 ms de granularidad; los plazos de 60 s no necesitan más; la limpieza R-C-11 va por EVENTO, no por temporizador). `Programar` con una clave ya existente la sustituye.
- **Orden de ejecución de acciones** = orden de la lista. `EnviarOrden` siempre va precedida por su `Anotar(orden_intencion)` con `fsync` (M6/H-2): < 5 ms en NVMe, decenas de veces al día.
- **Versión del objetivo de stops** (injerto §8.6): `pos.version_stops` sube en cada `Execute`; cada `EnviarOrden`/`Reemplazar` de stops lleva `serie="stops:X"` y `version`; `InvalidarSerie` llega al emisor ANTES que el siguiente plan; el emisor descarta lo obsoleto. Así un `REPLACE` con la cantidad anterior nunca sale después del fill.
- **Cerrojo ejecutor↔vigilante** (R-C-08.2) sin lock compartido: (1) el vigilante solo ACTÚA si el latido del ejecutor tiene > 3 s o una posición lleva descubierta > 5 s; (2) el conjunto deseado es idempotente y neutral al `Origen`: si los dos ponen el mismo stop, el siguiente `plan()` cancela la más nueva; (3) el token dice quién la puso.
- **Procesos con `subprocess.Popen`** (no `multiprocessing`): cada uno es un intérprete con su cerrojo, su latido y su `main`; el spawn de Windows no reimporta nada del padre (desaparece la trampa `__mp_main__` de `bot.py` l.124-128). `CREATE_NEW_PROCESS_GROUP` permite `terminate()` limpio. Si el supervisor muere, ejecutor y vigilante SIGUEN (protegen la posición) y el ping externo alarma a los 3 min; el supervisor al volver mata por PID a lo que no lata.
- **Latidos por fichero** (`os.replace` cada 1 s): sobreviven a tuberías rotas; los lee el supervisor, el vigilante (plan B) y el cuadro. `Latido.tocar(todo_vivo)` solo escribe si TODOS los hilos críticos del ejecutor (`das-lector`, `das-emisor`, `fuente-tuberia`, `avisos-envio`) están vivos: un ejecutor con el lector muerto se ve «colgado» y se relanza (injerto §8.11).
- **Tubería de señales** = `multiprocessing.connection` (stdlib, pickle, `authkey` HMAC obligatoria: `BOT_DAS_AUTHKEY`): `Evento` viaja como hoy por `Pipe`. Un solo cliente (`bot.py`); si el ejecutor se relanza, `EnlaceEjecutor` reconecta cada 5 s y conserva hasta 2.000 mensajes.
- **Grupo A a la misma velocidad** (R-M-05): `Avisar` es `put_nowait`; el hilo `avisos-envio` hace HTTP. Métrica en sombra `metrica{"senal_a_orden_ms"}` con y sin `alertas_grupo_a.activo`; si difieren de forma medible (> 1 ms de mediana) se pasa el envío a un PROCESO con `mp.Queue` (corrección 18; el libro L1081 dice literalmente «proceso aparte»).
- **pandas fuera del ejecutor** (injerto §8.25): con `BOT_DAS_FUENTE=tuberia` el ejecutor no importa `pandas` ni `RunnerAlertas`; `test_das_seguridad.py` lo comprueba con `sys.modules`.

### 6.2 Orden de arranque (R-L-01, R-J-06, R-J-02.5)

1. `supervisor` (tarea programada de Windows o `.bat` fuera del repo): cerrojo → `instalar_logging` → `cargar_con_respaldo` → `ventana(hoy)`; fuera de ventana o sin sesión (`hay_sesion`) duerme y comprueba cada 30 s.
2. Dentro de ventana: asegurar DAS (si `DAS_EXE` y no está en `tasklist` → lanzar y `Avisar(3, "LOGIN/2FA a mano")`, EP-7); esperar hasta que el puerto del API acepte conexión (sonda `ECHO`) con aviso cada 5 min.
3. Lanzar `vigilante` → esperar su latido (≤ 10 s) → lanzar `ejecutor`. El vigilante arranca antes para que una posición heredada tenga vigilancia mientras el ejecutor reconcilia.
4. `ejecutor.arrancar` = F12: nada sale a DAS hasta terminar la reconciliación.
5. Apagado: al `último EOD + 30 s` el supervisor manda `SIGTERM` (`terminate` en Windows; antes escribe `estado/orden_supervisor.jsonl {"parar": true}` que el ejecutor lee en el `Tic` y cierra ordenado: `fuente`, `cliente.cerrar` con `QUIT`, `avisos.parar(30)`, `diario.cerrar`). Sin posiciones overnight (L4): si a esa hora queda posición ⇒ `Avisar(3)` y NO se apaga (control humano).
6. Cerrojo de instancia única (R-J-04 c): `estado/cerrojo_{proceso}.lock` con `msvcrt.locking`; segunda instancia → `Salir(3)` + `Avisar(3)`. El `.bat` de arranque y la tarea programada NO son parte del repo (memoria «acceso directo de arranque»).

---

## 7. Configuración: el fichero del cuadro (H-4, CM1-CM4)

Ruta: `BOT_DAS_DIR/config/bot_das_config.json`. Lo escribe la app (pestaña «Ejecución», DIFERIDA) o, hasta entonces, `python -m app.bot_das.config exportar` (puente: `GET /api/bot-alerts/vigiladas` + defaults). Escritura: `tmp` en el mismo directorio + `os.replace` (atómico en Windows). `sha256` = hash canónico (`sort_keys`, `separators=(",",":")`, `ensure_ascii=False`) de todo salvo el propio campo. El bot valida `schema_version` y `sha256`; si falla usa `config/ultimo_bueno.json` y avisa nivel 2; detecta cambios por `mtime` (1 s) y `config_version` creciente; aplica en caliente solo `[C]`; un `[A]` distinto del cargado al arrancar NO se aplica, se avisa y se anota (CM3). Chat ids, credenciales y `DAS_CUENTA` van en el `.env`, NUNCA aquí (R-Q-01).

Marcas: **[C]** en caliente (siguiente señal) · **[A]** solo con bot apagado y sin posiciones · **[T]** técnico (= [A]). Los valores son los VIGENTES (la sección 4 del libro tiene valores obsoletos que aquí NO se copian: stops 10 %/+3 %/×1,10/+50 %, salida por hora 1/2/3 %, vigilante 30 s/10 s, cadencia BS 5 min, prints 10-20 ms, fase «demo»).

```json
{
  "schema_version": 1,
  "config_version": 42,
  "generado_at": "2026-09-26T10:15:03-04:00",
  "generado_por": "cuadro:jaume",
  "motor_hash": "sha256:<strategy_engine.py + market_frame.py + portfolio_sim.py>",
  "estrategias_hash": "sha256:<bloque estrategias>",
  "sha256": "<hash canónico del resto>",

  "fase": "sombra",                                        // [A] sombra | canario | real (R-O-03). Salir de sombra exige ADEMÁS BOT_DAS_PERMITIR_ORDENES=1 en el .env
  "vigilando": true,                                       // [C] interruptor global
  "pausar_entradas": false,                                // [C] /pausar
  "horario": { "tz": "America/New_York", "encender": "03:55", "apagar": null },   // [C] null = último EOD + 30 s (R-L-01)
  "modo_seguridad": { "activo": false, "precio_min": 5.0, "acum_dollar_volume_min": 2000000 },   // [C] R-I-04
  "lista_negra": [],                                       // [C] R-A-03

  "locates": {
    "tope_gasto_pct_cuenta": 3.0,                          // [C] R-H-03
    "hora_limite_intentos": null,                          // [C] R-H-01.5 ("HH:MM" ET o null)
    "umbral_ultimo_paquete_pct": 30,                       // [A] H6
    "inquiry_intervalo_s": 3,                              // [T] manual L2000
    "ruta_inquire": "ALLROUTEWTTYPE1"                      // [T] §5.22
  },
  "entrada": {
    "agregar_s": 60,                                       // [A] R-B-01 v3
    "nivel": "punto_medio_redondeo_arriba",                // [A]
    "post_only": true,                                     // [A] 24-sep
    "tope_caida_bid_pct": 3.0,                             // [A]
    "cruce_bajo_bid_pct": 0.5,                             // [A]
    "cruce_espera_s": 2,                                   // [T] un reintento con el bid nuevo
    "caducidad_senal_s": 60,                               // [A] R-B-04
    "distancia_max_ultimo_bid_pct": 5.0,                   // [A] B20 bis PROVISIONAL (null = apagada) — pregunta 1
    "retraso_max_senal_pct": 1.0,                          // [A] R-A-01 provisional
    "fraccion_max_volumen_acum": null,                     // [A] R-B-05 desactivado
    "reintentos_rechazo_conocido": 2,                      // [A] R-B-07
    "alto_riesgo_si": []                                   // [C] 2c consecuencia 2 (tope corto 0,5×): criterios de «alto riesgo»; vacío = nunca (pregunta a Jaume)
  },
  "salidas": {
    "por_hora": { "anticipo_s": 60, "nivel": "punto_medio", "al_ask_sin_tope": true, "perseguir_ask_max": 3, "perseguir_ask_s": 1 },   // [A] R-D-08 + corrección 11
    "eod": { "lanzar_antes_s": 60, "comprobar_despues_s": 30 },                     // [A] R-D-02
    "tp_parcial": { "agregar_s": 60, "techo_ask_pct": 3.0 },                        // [A] R-D-03 v2
    "cerrar_todo": { "techo_pct": 5.0, "reintentos": 2 },                            // [A] R-D-06
    "salida_motor": "como_tp",                                                       // [A] Signal/Trailing/Time Limit/Escalera/? — pregunta 3 (como_tp | ignorar)
    "sl_motor_con_posicion_abierta": "no_perseguir"                                  // [A] pregunta 4
  },
  "stops": {
    "tipo": "STOPLMTP",                                    // [A]
    "principal_limite_pct": 3.0,                           // [A] R-C-01 v3 (SUMADO sobre L)
    "emergencia_disparo_pct": 13.0,                        // [A]
    "emergencia_limite_pct": 63.0,                         // [A]
    "proteccion_desconocidas_pct": 25.0,                   // [A] R-C-10 (4): 20-30 %
    "margen_bajo_limit_up_pct": 1.5,                       // [A] R-F-02: 1-2 %
    "reintentos": 5, "separacion_reintentos_s": 2, "ventana_min": 5, "subida_max_cierre_pct": 100,   // [A] R-C-03 (el cierre NO se implementa; separación PENDIENTE)
    "comprobacion_s": 1,                                   // [T] R-C-04
    "debounce_s": 0.3,                                     // [T] F1.6: coalescer REPLACE tras fills sucesivos; nunca en el primer fill
    "tipo_esperado_en_order": null,                        // [T] patrón del campo Type de %ORDER para STOPLMTP (lo fija comprobar_das.py el primer día)
    "ruta": "STOP"                                         // [A] STOP | SMAT (tabla de rutas 2h)
  },
  "halts": {
    "k_max": 3, "distancia_banda_k2_pct": 4.0, "primera_vela_max_reentrada_pct": 6.0,   // [A] R-F-01
    "primera_vela_max_senal_guardada_pct": 6.0,            // [A] R-F-04 (b) X % PENDIENTE (defecto = 6)
    "t1_subida_max_cierre_pct": 250,                       // [A] R-F-05
    "t12_min": 240,                                        // sin efecto desde el 28-sep (T1 y T12, mismo protocolo); se valida por compatibilidad
    "ruta_reapertura": "OPEN", "enviar_antes_fin_halt_s": 60,   // [A] EP-2
    "margen_limite_pm_pct": 5.0                            // [A] R-F-06 PENDIENTE (más ancho que +3 %)
  },
  "exclusiones": {
    "spac_sic": ["6770"], "ipo_dias": 30, "split_del_dia": true,                     // [A] R-A-03 v2
    "fuente_splits": "massive",                            // [A] massive | nasdaq_daily_list — pregunta 6
    "opa_banda": { "minutos": 30, "rango_max_pct": 1.5, "dolares_min": 100000 }     // [A] aviso, no salida
  },
  "rutas": {                                               // [A] nombres SIN sufijo L/M (2h); comprobar con GET RouteStatus el primer día
    "agregar": { "ge_1": "SAGEREB", "lt_1": "MIAX" },
    "cruzar":  { "ge_1": "SAGEPRO", "lt_1_desde_0700": "EDGA", "lt_1_antes_0700": "MIAX" },
    "stop": "STOP", "halt": "OPEN"
  },
  "tecnicos": {                                            // [T]
    "barrido_s": { "tras_fill": 1, "ventana_tras_fill_s": 60, "con_posiciones": 2, "sin_nada": 10 },   // R-K-01
    "reconciliacion_fallida_s": 30,                        // R-K-03
    "feed": { "prealerta_s": 30, "emergencia_s": 60 },     // R-J-01
    "das_reconexion_s": [2, 4, 8, 16, 30], "das_aviso_cada_min": 5,   // R-J-02
    "vigilante": { "relanzar_s": [1, 2, 5, 10], "colgado_s": 3, "latido_s": 1, "ping_externo_s": 60, "ping_fallos_alarma": 3,
                   "plan_b_latido_s": 3, "plan_b_descubierta_s": 5, "cerrar_si_descubierta": false, "margen_aviso": 0.8 },   // R-J-04 v2, R-J-05, R-C-08
    "reloj": { "negarse_s": 2.0, "aviso_s": 0.5, "sntp": "time.windows.com" }, "disco_min_gb": 5,   // R-J-07
    "cisne_negro_informes": { "primeros": 5, "cadencia_inicial_s": 60, "cadencia_despues_s": 300 },   // R-G-01 v2
    "filtro_prints_ms": 20,                                // R-A-06 (lo aplica el bot de alertas; aquí solo se registra)
    "get_con_simbolo": true,                               // §5.8 (lo fija comprobar_das.py)
    "max_lv1": 100, "cuotas": { "ordenes_s": 50, "cancel_min": 100, "replace_min": 100, "locate_min": 100, "margen": 0.9 },
    "cola_aviso_umbral": 10000, "foto_cada_s": 2
  },
  "alertas_grupo_a": {                                     // [C] pestaña Alertas (R-M-05). Todo false = quedan radar, ejecutor, diario, vigilante y grupo B
    "activo": false, "prealerta_simple": false, "prealerta_freno_min": 5, "prealerta_ticks": false
  },

  "estrategias": [
    {
      "strategy_id": "…", "name": "…", "origen": "portfolio",
      "ejecutar": true,                                    // [C] grupo B
      "avisar_grupo_a": false,                             // [C]
      "riesgo_usd": 300, "riesgo_piramide_usd": null, "riesgos_piramide": [200, null],   // [C] 4.4b
      "capital_usd": null, "ev_pct": 4.0, "ev_rangos": [{"lo": 0, "hi": 0.5, "ev_pct": null}],   // [C]
      "cuentas": null,                                     // [C] se conserva por compatibilidad con el grupo A; el ejecutor opera UNA cuenta
      "excluir_ipo": true,                                 // [C] R-A-03 v2 (on por defecto en RTH, off en PM)
      "al_desactivar": "esperar_fin_dia",                  // [C] R-E-03: esperar_fin_dia | cerrar_y_reiniciar
      "definition_hash": "sha256:…",                       // [A] R-O-01 / R-E-03: si cambia con bot vivo → no se aplica, aviso, botones
      "definition": { "…estrategia NORMALIZADA (sin slippage/locates/gastos), CM4…" }
    }
  ]
}
```

`CALIENTE` (config.py) = exactamente las rutas marcadas [C]. `validar()` rechaza: `principal_limite_pct ≥ emergencia_disparo_pct`, `emergencia_disparo_pct ≥ emergencia_limite_pct`, `k_max < 1`, `tope_gasto_pct_cuenta ∉ (0, 10]`, horas mal formadas, `fase` fuera de `Fase`, `riesgo_usd ≤ 0` en una estrategia con `ejecutar=true`, rutas vacías. `comprobar_coherencia` (R-L-02) avisa por estrategia: ventana de entradas fuera de la sesión, `hora_salida` posterior al fin de sesión, sesión «sumada» (memoria: la sesión se SUMA, no sustituye).

Fuera del fichero de configuración: los **comandos** (botones) van en `estado/comandos.jsonl` con `id` único (idempotente: `{"id","comando","args","quien","t"}`), y el **estado** del bot (posiciones, órdenes, BP, locates, tickers pausados, señales del día, feed/DAS/vigilante, última reconciliación, cola de avisos) lo publica el ejecutor en `estado/foto.json` cada 2 s (panel 4.4 de solo lectura; en fase 1 no hay endpoints nuevos: pregunta 8). Historial CM3: cada diferencia aplicada o rechazada va al diario como `config_cambio {ruta, antes, despues, caliente, aplicado, quien}`.

---

## 8. Diario: formato JSONL y relectura (R-N-01, H-2, M6)

Un fichero por día Y POR PROCESO (corrección 3: dos procesos en `append` sobre el mismo fichero mezclan líneas): `diario/diario_ejecutor_2026-09-26.jsonl`, `diario/diario_vigilante_2026-09-26.jsonl`, `diario/diario_supervisor_2026-09-26.jsonl`. Cada línea es un objeto JSON (`ensure_ascii=False`, sin saltos) con la cabecera común y `datos` por tipo:

```json
{"v":1,"seq":184,"t":"2026-09-26T09:31:02.417-04:00","mono":1234.567,"proceso":"ejecutor","tipo":"orden_intencion","ticker":"XYZ",
 "datos":{"token":100200184,"lado":"SS","qty":1200,"tipo_orden":"LMT","precio":"3.4500","stop":null,"ruta":"SAGEREB","post_only":true,"tif":"DAY+",
          "proposito":"entrada_agregar","lote_id":"XYZ|abc123|2026-09-26 09:30:00|entrada","nivel":"3.9000","version":0,"origen":1,
          "senal_id":"XYZ|abc123|2026-09-26 09:30:00|entrada","precio_senal":"3.4300","bid":"3.44","ask":"3.46","last":"3.45","distancia_ultimo_bid_pct":"0.29",
          "regla":"R-B-01 v3","linea":"NEWORDER 100200184 SS XYZ SAGEREB 1200 3.45 PostOnly TIF=DAY+"}}
```

Reglas del formato: `Decimal` se serializa como CADENA (nunca float); `t` es la hora ET aware; `mono` el monotónico (latencias); `ticker` fuera de `datos` cuando aplica; `cruda` (la línea de DAS tal cual) SIEMPRE en `orden_act`, `orden_estado`, `fill`, `pos`, `rechazo`; los secretos pasan por `FiltroSecretos.limpiar` (los `notes` de DAS o un texto de Telegram podrían traerlos).

Tipos de registro y su `datos` mínimo:

| tipo | cuándo | datos | fsync |
|---|---|---|---|
| `arranque` | `abrir_dia` | `version, fase, motor_hash, config_version, estrategias_hash, pid, reloj_desvio_s` (R-O-01) | sí |
| `config` / `config_cambio` | carga / cada diferencia (CM3) | `config_version, sha256` / `ruta, antes, despues, caliente, aplicado, quien` | no |
| `senal` / `senal_repetida` / `senal_descartada` | F1.2 | `senal_id, tipo, strategy_id, momento, precio, acciones, stop, entrada_idx, origen, recibida_en, latencia_ms` / + `motivo` | no |
| `lote` | F1.4 y cada cambio de estado | `lote_id, strategy_id, pedidas, llenas, precio_medio, nivel_stop, estado, reentrada_n, entrada_idx, version_estrategia` | sí |
| `orden_intencion` / `orden_enviada` / `orden_simulada` | antes del `send` / tras el `send` / sombra | ver ejemplo; `orden_simulada` lleva `fills_simulados` | sí / sí / no |
| `cancel_intencion` / `replace_intencion` | antes de CANCEL/REPLACE | `id_das, token, qty, stop, precio, version, motivo` | sí |
| `orden_act` / `orden_estado` / `fill` / `pos` | cada `%OrderAct` / `%ORDER` / `Execute`+`%TRADE` / `%POS` | campos parseados + `cruda`; `fill`: `id_trade, token, qty, precio, liq, ecn_fee, neta_fills_tras` | no |
| `stop_plan` | cada `plan()` | `version, deseado[], vivas[], acciones[]` | no |
| `incidente` / `discrepancia` / `divergencia_sl` | R-C-11 b, F10 caso 6, salida SL del motor | `detalle, neta_fills, neta_das` | no |
| `locate_inquire` / `locate_intencion` / `locate_estado` / `locates_caducados` | F9 | `strategy_id, qty, qty_ajustada, paquetes, precio_accion, coste_nuevo, coste_total, ev_pct, fade_pct, entra, id_das, estado, localizadas, usadas` | no / sí / no / no |
| `halt` / `bs` / `bs_informe` / `fogonazo` | F6 / F7 | `ta, tat, k, precio_parada, decision, fin_previsto` / `primer_stop, emergencia_limite, max_visto, informes` | no |
| `rechazo` / `pausa` / `reanudar` | F8 | `notas (cruda), tratamiento, intentos, cubierta, accion` | no |
| `comando` / `aviso` | comandos.py / cada `Avisar` | `nombre, args, chat_id, requiere, confirmado` / `nivel, grupo, clave, texto` | no (`cierre_humano` sí) |
| `reconciliacion` | F10/F12 | `caso[], acciones[], duracion_ms` | no |
| `metrica` | varias | `nombre ∈ {senal_a_orden_ms, orden_a_accept_ms, slippage_vs_senal_pct, fraccion_volumen, retraso_senal_pct, barrido_ms}, valor, ticker` (J18, R-B-05, R-A-01, R-M-05) | no |
| `excepcion` | H-5 | `ticker, donde, traceback` | no |
| `das_conexion` / `feed` / `hilo_caido` / `disco` | F11 | `conectado, motivo, intento` / `sin_velas_s` / `nombre, error, relanzado` / `libre_gb` | no |
| `comprobacion_das` | herramientas | `paso, comando, respuesta_cruda, conclusion` | no |
| `vigilancia` (solo vigilante) | cada barrido con acción | `ticker, faltan[], sobran[], acciones[], latido_ejecutor_s, puede_enviar` | sí si envía |

Relectura (`reconstruir`, PURO, H-2): se leen los dos diarios del día ordenados por `(t, proceso, seq)` y se reproduce el estado: `senales_vistas` ← `senal`/`senal_repetida`/`senal_descartada`; lotes ← último `lote` por `lote_id`; órdenes ← `orden_intencion` (+ `orden_enviada`/`orden_estado`/`orden_act` para el último estado; una `orden_intencion` sin `orden_enviada` se trata como «puede haber salido»: la reconciliación la casa por token); `fills` y `neta_fills` ← `fill` (dedupe por `id_trade`); `ultimo_seq_token` por origen ← máximo de `token`; locates ← `locate_estado`; `gasto_locates_dia` ← suma de `coste_nuevo` con `estado=Located`; pausas/BS/`sin_reentrada_hasta_sigue`/`intervencion_humana` ← `pausa`/`bs`/`reanudar`/`comando sigue`; `config_version` ← último `config`. La última línea partida (crash a medio `write`) se tolera y se anota `diario_linea_partida`. `reconstruir(reconstruir(x)) == reconstruir(x)`.

Copia fuera del VPS y parquet histórico: tarea del supervisor al apagar (`robocopy` a `BOT_DAS_COPIA`), fuera del alcance de los tests.

---

## 9. Fases sombra / canario / real (R-O-03)

| Fase | Qué hace | Candados |
|---|---|---|
| `sombra` | Todo el camino (señal → decisión → diario → avisos) con DAS conectado en solo lectura (`LOGIN`, `SB`, `GET`); los mutantes van al `Emparejador` interno y producen fills SIMULADOS (`simulado=True`, `orden_simulada` en el diario); mide latencias, slippage teórico, paridad de señales, estabilidad. | (1) `ClienteDAS(solo_lectura=True).enviar` lanza `EnvioProhibido` para todo `MUTANTES` (incluido `SLPRICEINQUIRE … ALLROUTE`); (2) `ClienteSombra` desvía los mutantes ANTES de llegar al cliente; (3) `construir_desde_env` no puede construir `solo_lectura=False` si `cfg.fase == SOMBRA`. Test: un día entero de replay y `simulador.recibidas()` sin ningún mutante. |
| `canario` | Dinero real, lotes de 1-100 acciones, una estrategia; Jaume sube el tamaño por el cuadro (riesgo por estrategia [C]). | `ClienteDAS(solo_lectura=False)` exige `BOT_DAS_PERMITIR_ORDENES=1` en el entorno del VPS (`.env`, nunca en el fichero del cuadro): el cuadro por sí solo NO puede pasar de sombra a dinero (corrección 15). Cambiar de fase exige bot apagado y sin posiciones (`[A]`). |
| `real` | Igual que canario con tamaño normal. | Los mismos. |

Cada aviso del grupo B lleva la fase delante (`[SOMBRA] …`); el `foto.json` también. Demo: DESCARTADA (24-sep). `herramientas/comprobar_das.py` se ejecuta el primer día en sombra y, los pasos marcados, con 1 acción en canario.

Prohibición por código, no por configuración: `es_mutante` es una función pura con test exhaustivo (todas las palabras de `MUTANTES` en mayúsculas, minúsculas y mezcladas, con espacios delante, y `SLPRICEINQUIRE … ALLROUTE`); `ClienteDAS.enviar` la consulta ANTES de encolar; no existe ningún otro camino hacia el socket (`_salida` es privada y el emisor solo lee de ella).

---

## 10. Plan de tests

Todos en `backend/tests/bot_das/`, sin red externa, sin DuckDB, sin credenciales (los tests que las necesitarían se saltan con motivo); reloj simulado; `SimuladorDAS` en `127.0.0.1:0`; `canal_falso.CanalFalso` para probar reglas y decisor sin socket. Cada tabla de casos del libro es un `pytest.mark.parametrize` cuyo `id` cita la regla. `conftest.py` propio: `reloj` (RelojSimulado a las 09:30 ET), `cfg` (config_ejemplo.json cargada), `dir_bot` (tmp_path con la estructura de §1), `simulador` (arrancado y parado), `libro`, `tokens`, `estado_vacio`, `cotizacion(bid, ask)`.

`canal_falso.py`:
```python
class CanalOrdenes(Protocol):        # lo que el ejecutor necesita de un cliente (ClienteDAS y ClienteSombra lo cumplen)
    def enviar(self, linea: str, serie: Optional[str] = None, version: int = 0) -> None
    def invalidar(self, serie: str, version: int) -> None
    @property def conectado(self) -> bool
class CanalFalso(CanalOrdenes):      # grabadora: `lineas`, `series_invalidadas`; `responder_con(lineas)` inyecta respuestas sintéticas
```

| Fichero | Qué demuestra (regla) |
|---|---|
| `test_das_tipos.py` | `OrdenNueva.__post_init__` rechaza qty float/0/bool, precio fuera de tick, STOPLMTP con límite < disparo, MKT con precio, PostOnly sin límite; `al_tick` arriba/abajo con 0.0001/0.9999/1.0/1.005; constantes por defecto = tabla de reglas vigentes (R-C-01 v3, R-J-04 v2, R-G-01 v2, R-A-06) — el test CITA la regla junto a cada valor (riesgo 21) |
| `test_das_tokens.py` | composición/descomposición; máximo 336_699_999 < MAX_INT; no colisión entre orígenes; `es_nuestro` rechaza tokens de ayer y de otro esquema; `GeneradorTokens` continúa desde `ultimo_seq`; `TokensAgotados` |
| `test_das_reloj_cerrojo.py` | `veredicto_reloj` (0,4 / 0,6 / 2,1 s / None); `RelojSimulado`; `hora_das_a_et`; `CerrojoInstancia` doble adquisición en dos subprocesos (`python -c`); `Latido.edad`; `tocar(todo_vivo=False)` no escribe; `HiloVigilado` relanza un cuerpo que lanza y para tras 5 caídas |
| `test_das_protocolo.py` | parse de CADA línea de `lineas_das.txt` (incl. `%IORDER`, `%IPOS`, `%ITRADE` con su orden de campos, `#buyingpower`); `%ORDER` 15 y 19 campos y tipo «SLP: 2.97 2.99»; `%OrderAct` notas vacías / con número final que NO es nuestro token; `Buy`/`Shrt`; `$Quote` parcial; `$IssueStatus` sin TA y `$SymStatus`; `%SLRET` con/sin cuenta; `SLRouteMinChargeRet` con/sin `$`; las 12 líneas de conexión; `$INTMSG` multilínea; `$STINFOEX`; `parsear` NUNCA lanza (fuzz con 5.000 líneas aleatorias y truncadas); `cmd_neworder` produce EXACTAMENTE los literales del manual (L543-547, L549-553, L618-624, L767-770); `cmd_replace` STOPLMTP → `STOPLMT`; `es_mutante` exhaustivo; `formatear_precio` lanza fuera de tick y nunca produce notación científica; `normalizar_pos` con tipo 3 y qty ±100 → −100; `redactar` |
| `test_das_cliente.py` | contra `SimuladorDAS`: LOGIN, volcado, líneas partidas en varios `recv`, `\r\n` y `\n`; `solo_lectura` lanza `EnvioProhibido` para cada mutante y deja pasar `GET/SB`; `CuotaComandos` (51 órdenes en 1 s → espera; 101 CANCEL/min; inquire < 3 s; margen 0,9); `PlanReconexion` 2/4/8/16/30; corte (`cortar`) → `al_estado(False)` y reconexión; `invalidar` descarta un REPLACE encolado con versión vieja y deja pasar el nuevo; cola de salida llena no bloquea al principal; `ClienteSombra` deriva mutantes al `Emparejador` y `simulador.recibidas()` no contiene ningún mutante; `desde_env` sin `BOT_DAS_PERMITIR_ORDENES` no construye `solo_lectura=False` |
| `test_das_simulador.py` | cruce límite/PostOnly/MKT/STOPLMTP, parciales, watch recibe `%IORDER/%IPOS/%ITRADE`, `rechazar_siguiente`, halt/reabrir, ruta OPEN en halt, variantes de `%ORDER`, las 6 permutaciones de `orden_mensajes`, `desde_vela` con `ModeloSpread` |
| `test_das_diario.py` | write-ahead: tras `anotar(orden_intencion)` el fichero ya lo tiene aunque el proceso muera (`os._exit` en subproceso); última línea partida se tolera; `reconstruir` sobre los dos diarios de `fixtures` ⇒ senales_vistas, lotes, tokens, fills/neta_fills, locates, pausas, BS; idempotencia; disco no escribible → `degradado=True`, `pendientes` y no lanza; `Decimal` como cadena; `FiltroSecretos.limpiar` aplicado a `notas` |
| `test_das_config.py` | `escribir_atomico` + `cargar` roundtrip; hash alterado → `ConfigInvalida` y `cargar_con_respaldo` devuelve último bueno + aviso; `diferencias` marca caliente/apagado según `CALIENTE`; `aplicar` rechaza `[A]` con posiciones y acepta `[C]`; `comprobar_coherencia` (sesión sumada, ventana fuera de sesión); `motor_hash` cambia si cambia un byte (copia temporal de los tres ficheros); `validar` rechaza cada combinación imposible; `exportar_desde_backend` con un servidor HTTP local falso; `VigilanteConfig` detecta un `os.replace` |
| `test_das_avisos.py` | `poner` no bloquea con un canal que tarda 10 s (medido < 1 ms); orden conservado; reintentos; dedupe por clave; enrutado por nivel (1 → TG; 2 → + correo; 3 → + SMS); grupo A solo si activo; `FiltroSecretos` borra el VALOR literal del token y de la clave de DAS en `msg` y en `args`; `CanalTelegram` contra un servidor HTTP local (sin red) y el log capturado no contiene el token |
| `test_das_comandos.py` | autorización por chat_id (no autorizado → None y registro); dos pasos con caducidad; «SI» obligatorio; `responder_consulta` para cada comando de R-M-04 sobre un `EstadoBot` de ejemplo; `LectorComandosFichero` idempotente por id |
| `test_das_mercado.py` | `$Quote` parcial no borra bid/ask; `fresca`; `dollar_volume`; `marcar_halt` cuenta k solo UP en RTH; `suscripciones` con tope 100 y prioridad; `sin_cotizacion_desde` |
| `test_das_referencia.py` | `Referencia` con `abrir` falso: caché por día; `ficha` None si falla; `splits_de_hoy` None si falla (y el decisor no excluye) |
| `test_das_reglas_precios.py` | `punto_medio_arriba` (spread 1 tick → ask; 2 → bid + 1; < 1 $ a 0,0001); `punto_medio_abajo`; `con_techo` lado permisivo; `bajo_bid`; `ruta` por tramo/hora (EDGA antes de 07:00 → MIAX; stop → STOP; halt → OPEN); `de_float` con NaN → error; nunca aparece `float` en los resultados |
| `test_das_reglas_entrada.py` | tabla de 16 motivos de `evaluar_senal`, uno por fila; `t_cierre_vela` contra la vela de `AM_recorte` (momento = `s`, cierre = +60 s); `qty_de_evento` (float 1199.0 → 1199; None → 0); `qty_final`; `al_vencer` con bid −2,9 % (cruza) y −3,1 % (no); `resto_a_cruzar` solo tras `Canceled`; `orden_cruce` a bid·0,995; `repartir_fill` 400 de 1.000 entre 600/400 pedidas (suma exacta); `sumar_senal` conserva `t_limite`; `cerrar_intento` 0/parcial; B13; B19 con SSR; modo seguridad 4,99 $ / 5,00 $ y 1,99 M$ / 2,00 M$; diario degradado → no entra |
| `test_das_reglas_stops.py` | `niveles(10)` = 10 / 10,30 / 11,30 / 16,30; con `limit_up=10.5` baja el disparo bajo la banda; `conjunto_deseado` con 2 lotes/2 niveles y neta capada; `plan` idempotente (dos veces = 0 acciones), adopta órdenes VIGILANTE por `inferir_proposito`, cancela la más nueva si hay dos emergencias, devuelve `GET POSITIONS` y NO toca la emergencia si `neta_das ≠ neta_fills`; `limpieza_tras_fill_stop` neta 0 / larga 20 (vende 20, JAMÁS 100) / corta 80, siempre con `InvalidarSerie` primero; `reasignar_principal_rebasado`; `tipo_conserva_pp`; `descubiertas`; `stop_proteccion` corta/larga; `cantidad_cancelada` usa `cxlqty` y no `qty` |
| `test_das_reglas_salidas.py` | `LITERALES_EXIT_REASON` cubre TODOS los literales `exit_reason` de `portfolio_sim.py` (el test los extrae con regex del fichero real) y `"?"`; `tratamiento` para cada `ClaseSalida` (SL con posición abierta → divergencia sin orden; Daily Limit → ignorar + aviso; MOTOR → como TP); `temporizadores_lote` t−60/t/t+30; `perseguir_ask` máx. 3 y por REPLACE; `tp_al_vencer` dentro/fuera del 3 %; `prioridad`; `cerrar_todo` incluye manuales; `puede_reentrar` (−1/0/N × true/false); `ultimo_eod` con dos estrategias; `al_desactivar` esperar/cerrar |
| `test_das_reglas_halts.py` | matriz k = 1/2/3 × stop encima/debajo × PM/RTH × vela </≥ 6 %; `momento_envio_open` (P con TAT → fin − 60 s; H sin hora → 0; fin pasado → 0); `debe_enviar_open` impide la segunda MKT tras `$IssueStatus` repetido; T1 > 250 % → control humano; `senal_guardada_valida`; `cerca_de_banda` |
| `test_das_reglas_cisne_negro.py` | `se_activa` solo pasado el límite de emergencia con corto vivo; cadencia 60 × 5 luego 300 (reloj simulado 40 min); `informe` contiene los 16 campos; `acciones_durante_bs` nunca produce `EnviarOrden`; `al_cerrar`; `cierre_humano` cancela la emergencia antes |
| `test_das_reglas_rechazos.py` | cada entrada del catálogo casa su propio texto; desconocido → cubierta pausa / no cubierta nivel 3 sin `EnviarOrden`; 2 reintentos y no 3, con token nuevo; `reintento_stop` 5 y para; `tras_cancel_o_replace_rej` → barrido |
| `test_das_reglas_capital.py` | márgenes por tramo (0,9 $, 3 $, 5 $, 20 $); tope 1×/0,5×; BP viejo (> 30 s) → 0; orden de llegada (2 señales, cabe 1,5: la segunda recibe el resto); `requiere_mas_margen` |
| `test_das_reglas_locates.py` | `paquetes(1230) == (12, 1200)`, `(1240) == (13, 1240)`, `(1200) == (12, 1200)`, `(50) == (1, 50)`, `(0) == (0, 0)`; `veredicto_ev` con coste TOTAL (la segunda compra se rechaza si el total no compensa) y usando `ev_fijo_para_precio` por tramo; tope 3 %; cerrojo por (ticker, estrategia, día); parcial sigue buscando; `asignar_a_lote` E9; `cantidad_a_localizar` casa por `strategy_id`; máquina completa con `%SLRET/%SLOrder` sintéticos incl. `Offered` y `AlreadyShortable`; `tras_reentrada` |
| `test_das_reglas_exclusiones.py` | SPAC siempre; IPO solo RTH y solo con casilla; split; lista negra; `sin_ficha`; `splits_hoy=None` no excluye; `banda_opa` |
| `test_das_reglas_reconciliacion.py` | los 6 casos; `orderSrc="Montage"` y token de AYER → caso 4; `cadencia_barrido` 1/2/10; `barrido_caducado`; `AcumuladorVolcado` con y sin marcadores |
| `test_das_reglas_vigilancia.py` | ejecutor vivo → 0 acciones aunque falte un stop (hasta 5 s); ejecutor muerto → repone par con `Origen.VIGILANTE`; dos emergencias → cancela la nueva; posición sin lote → protección + nivel 3; dos `Located` mismo día → deshabilitar; `puede_enviar=False` → `PedirAlSupervisor`; `debe_hacer_ping` |
| `test_das_decisor.py` | **escenarios enteros en seco** con `CanalFalso` y mensajes DAS sintéticos, en las 6 permutaciones de `%OrderAct/%TRADE/%POS`: F1 completa → secuencia EXACTA de acciones; F2 fill parcial del principal; F3; F4; F5 con persecución; F6 halt; F7 BS; F8 rechazo; F9 locates; F10; F14; H-5: un `Evento` con `precio=None` ⇒ pausa de ese ticker y el siguiente se procesa; señal repetida ⇒ 0 órdenes (R-A-05); multicuenta ignorada; señal Long con corto abierto ⇒ descartada (R-E-01); `config` en caliente entre mensajes y el intento vivo conserva su copia; un fill mientras hay un `Reemplazar` pendiente ⇒ `InvalidarSerie` precede al nuevo plan |
| `test_das_fuente_senales.py` | `FuenteEnProceso` con las velas de `test_bot_alerts_procesos._velas` produce el mismo `Evento` que `RunnerAlertas` directo; `radar` añade `strategy_id` por nombre y descarta nombres repetidos; `FuenteTuberia` + `EnlaceEjecutor` en dos procesos: 5.000 mensajes sin pérdida, reconexión tras matar el Listener, `hola` con hash distinto se rechaza; `FuenteGrabacion` reproduce `AM_recorte` en orden de tiempo con el `Guion` |
| `test_das_ejecutor.py` | ejecutor real + `SimuladorDAS` + `FuenteGrabacion` en fase CANARIO (simulador, `BOT_DAS_PERMITIR_ORDENES=1` en el entorno del test): entrada → fills → stops residentes → stop dispara → limpieza, comprobado en `simulador.ordenes()`; fase SOMBRA: `simulador.recibidas()` sin NINGÚN mutante y diario con `orden_simulada`; write-ahead visible antes del `NEWORDER`; `anotar` que falla → 0 `NEWORDER SS` y los `NEWORDER B STOPLMTP` siguen; reinicio a mitad (matar y relanzar en subproceso) ⇒ no reentra ni recompra (H-2); `senal_a_orden_ms` con y sin grupo A |
| `test_das_vigilante.py` | vigilante + simulador con conexión watch: posición sin stop y latido del ejecutor viejo ⇒ par repuesto en < 2 s; luego ejecutor arranca y `plan()` adopta (0 órdenes nuevas); diario del vigilante separado; sin conexión de acción ⇒ `PedirAlSupervisor` escrito |
| `test_das_supervisor.py` | con `python -c` como hijos falsos: relanza en 1/2/5/10 s; mata al colgado a los 3 s (hijo que deja de tocar el latido); ventana R-L-01 con festivo (`hay_sesion`); doble instancia no arranca; lee `orden_supervisor.jsonl`; huérfano con cerrojo tomado y sin latido → lo mata por PID |
| `test_das_seguridad.py` | (1) importar `app.bot_das.ejecutor` con `BOT_DAS_FUENTE=tuberia` en un subproceso limpio y `pandas not in sys.modules`; (2) grep de los VALORES de `TELEGRAM_BOT_TOKEN_*`, `DAS_CLAVE`, `BOT_DAS_AUTHKEY`, `MASSIVE_BOT_API_KEY` (valores inventados en el test) sobre el log Y el diario de un día de replay: 0 apariciones; (3) `MUTANTES` completo y `es_mutante` con variantes; (4) ningún módulo de `bot_das` contiene literales que parezcan credenciales (regex `bot\d{6,}:`, `sk-`, `AKIA`) |
| `test_das_replay_dias.py` (`@pytest.mark.slow`) | R-O-02: días grabados reales de `D:\bot_senales\grabaciones` si existen (se salta si no) contra el ejecutor en seco con un `Guion` (spread declarado); el test DORADO compara con `esperado_AAAA-MM-DD.jsonl` señales, decisiones (motivos), tokens y secuencia de acciones — NO precios de fill (injerto §8.24) |

**Lo que NO se puede probar sin DAS real (sombra y canario, `comprobar_das.py`):** formato real de `%ORDER` para STOPLMTP (§5.2) y si `REPLACE` conserva pre/post (2h.8); precio que dispara STOPLMTP (2h.2); nombres de rutas de Sage (`GET RouteStatus`) y tarifas/horarios PM; PostOnly en SAGEREB/SMAT y venta en el punto medio por SAGEREBL; ruta OPEN durante halt (EP-2); BP retenido por los dos stops (EP-3); qué recibe la conexión watch y si una segunda normal puede enviar (R-C-08); textos reales de `Send_Rej` (catálogo); `SLPRICEINQUIRE`/rutas tipo 1/`SLReuseQuery` reales; latencia socket↔DAS; LOGIN con 2FA (EP-7); `GET SymStatus X`/`GET LDLU X` con símbolo (§5.8); signo de `%POS` en cortos; reset de `$Quote` tras las 20:00; desvío del reloj del VPS; arranque automático de DAS.

---

## 11. Cobertura regla → módulo.función → test, y lo DIFERIDO

### 11.1 Reglas FIJADAS (todas las del checklist)

| Regla | Módulo.función | Test |
|---|---|---|
| MARCO M1-M13 | M1 procesos propios (`supervisor/ejecutor/vigilante`); M3 `stops.conjunto_deseado` (posición objetivo); M4 capas = `fuente_senales` / `reglas.entrada` / `ejecutor` / `reglas.reconciliacion` / `diario`+`supervisor`; M5-M6 `ejecutor.ejecutar` (write-ahead) + `stops.plan`; M7 `reconciliacion.acciones` caso 6; M9 `entrada.qty_final`; M10 `precios.ruta`+`entrada.orden_agregar` (límite en PM); M11 `config.py`; M13 `precios.ruta` por hora | `test_das_ejecutor`, `test_das_reglas_stops`, `test_das_reglas_reconciliacion`, `test_das_reglas_entrada` |
| API-2c (margen Sage) | `capital.margen_inicial_corto/margen_mantenimiento/acciones_que_caben/requiere_mas_margen`; `vigilancia.comprobar` (e) | `test_das_reglas_capital`, `test_das_reglas_vigilancia` |
| API-2e/2f/2g/2h | `protocolo.py` entero; `tokens.es_nuestro` (DAY+ caduca 20:00); `stops.tipo_conserva_pp` (REPLACE); `cmd_neworder` PostOnly; rutas sin sufijo (`precios.ruta`); `CuotaComandos`; `orderSrc` en `reconciliacion.comparar`; `MsgTrade.liq/ecn_fee`; `cmd_login(watch)`; `herramientas/comprobar_das` (6 puntos abiertos) | `test_das_protocolo`, `test_das_cliente`, `test_das_reglas_stops`, `test_das_reglas_reconciliacion` |
| R-C-01 v3 | `stops.niveles` (+3/+13/+63 sumados), `stops.conjunto_deseado` (un principal por nivel, una emergencia), `stops.plan`, `stops.reasignar_principal_rebasado` (decisión a) | `test_das_reglas_stops`, `test_das_decisor` F2 |
| R-C-11 | `stops.limpieza_tras_fill_stop` (neta 0 / larga / corta), `stops.cantidad_cancelada`, `decisor._de_das` (por evento) | `test_das_reglas_stops` (vende 20, jamás 100), `test_das_decisor` F2.3, `test_das_ejecutor` |
| R-C-07 plan B | `vigilancia.comprobar` (a)-(b), `stops.plan` neteo por propósito+nivel con `inferir_proposito`, `tokens` (quién la puso) | `test_das_reglas_vigilancia`, `test_das_vigilante` (repone y el ejecutor adopta) |
| R-C-10 (uso en J/K) | `reconciliacion.comparar/acciones` (casos 1-6), `stops.stop_proteccion`, `ejecutor.arrancar` F12 | `test_das_reglas_reconciliacion`, `test_das_ejecutor` (reinicio) |
| R-G-01 | `cisne_negro.se_activa/activar/toca_informe/informe` (16 campos), `avisos` niveles 3 (TG+correo+SMS), `fogonazo_visto` | `test_das_reglas_cisne_negro`, `test_das_decisor` F7 |
| R-G-03 | `cisne_negro.acciones_durante_bs` (solo qty), `cierre_humano` (cancela emergencia antes), `PosicionTicker.sin_reentrada_hasta_sigue`, `salidas.puede_reentrar` | `test_das_reglas_cisne_negro`, `test_das_reglas_salidas` |
| R-G-02 | `halts.al_entrar_en_halt` (aviso con tipo/hora/precio/posición/stop/k/bandas), reapertura en `decisor` (segundo aviso) | `test_das_reglas_halts`, `test_das_decisor` F6 |
| G3/G4/G6/G7 | información en `cisne_negro.informe` (minutos desde el máximo, si lleva bajando); ninguna decisión automática (`cerrar_si_descubierta=false`) | `test_das_reglas_cisne_negro` (no `EnviarOrden`) |
| F10 / F12 | SSR: `entrada.evaluar_senal` no filtra por SSR y `orden_agregar` ya va ≥ bid + 1 tick (B19); medias sesiones: `salidas.horas_de_salida` + `calendario.media_sesion` en `supervisor.ventana` | `test_das_reglas_entrada` (SSR), `test_das_supervisor` |
| I1 / I3 | `salidas.tratamiento(DAILY_LIMIT) == "ignorar"`; ninguna regla de racha en `entrada.evaluar_senal` | `test_das_reglas_salidas` |
| R-I-04 | `entrada.evaluar_senal` paso 9 con `mercado.dollar_volume`; `comandos` `/modo_seguridad`; config `[C]` | `test_das_reglas_entrada` (4,99/5,00 $; 1,99/2,00 M$), `test_das_comandos` |
| R-B-01 v3 | `precios.punto_medio_arriba`, `entrada.abrir_intento/orden_agregar/al_vencer/orden_cruce/resto_a_cruzar`, `decisor._temporizador("cruce","cruce_espera")` | `test_das_reglas_precios`, `test_das_reglas_entrada`, `test_das_decisor` F1 |
| R-B-07 | `rechazos.cargar_catalogo/clasificar/decidir`, `catalogo_rechazos.json`, `EstadoTicker.PAUSADO`, `comandos` `/reanudar`, `LectorComandosFichero` | `test_das_reglas_rechazos`, `test_das_decisor` F8 |
| TABLA-RUTAS | `precios.ruta`, `config.rutas`, `EstadoBot.rutas_habilitadas` (GET RouteStatus), `comprobar_das` paso 1 | `test_das_reglas_precios` |
| R-B-02 | `entrada.cerrar_intento`, `entrada.repartir_fill`, F1.8 | `test_das_reglas_entrada`, `test_das_decisor` F3 |
| R-B-04 | `entrada.t_cierre_vela` (momento = inicio de vela), `evaluar_senal` paso 13, `Config.entrada.caducidad_senal_s` | `test_das_reglas_entrada` (contra `AM_recorte`) |
| B11 / B13 / B18 / B19 | B11 F1.8 (PM sin excepciones); B13 `entrada.fill_peor_de_lo_permitido`; B18 `halts.al_entrar_en_halt` (cancela entradas); B19 `orden_agregar` + `MsgIssueStatus.ssr`/`MsgShortInfo.reg_sho` | `test_das_reglas_entrada`, `test_das_reglas_halts` |
| R-B-05 | `entrada.qty_final` (fracción medida, tope desactivado), diario `metrica fraccion_volumen` | `test_das_reglas_entrada` |
| R-B-03 | `entrada.sumar_senal`, `repartir_fill`, `IntentoEntrada.lotes`, `stops.conjunto_deseado` por nivel | `test_das_reglas_entrada`, `test_das_decisor` F3 |
| R-H-01 | `locates.siguiente_paso` (inquire cada 3 s, `ALLROUTEWTTYPE1`), `veredicto_ev` (EV por tramo + fade con paquetes H6 + coste total), `cantidad_a_localizar`, `CuotaComandos.inquire_s`, `MsgSLMinCharge` en el EV | `test_das_reglas_locates`, `test_das_decisor` F9, `test_das_cliente` (cuota) |
| R-H-05 | `locates.siguiente_paso` por (ticker, estrategia) con su propio EV; `paquetes` sobre cada compra; `asignar_a_lote` (E9); `caducados` | `test_das_reglas_locates` |
| R-H-02 | cerrojo en `siguiente_paso` (una compra por ticker-estrategia-día), `compra_repetida` → `locates_deshabilitados`, `vigilancia.comprobar` (d) | `test_das_reglas_locates`, `test_das_reglas_vigilancia` |
| R-H-03 | `locates.tope_superado`, `EstadoBot.gasto_locates_dia`, `vigilancia.comprobar` (d) | `test_das_reglas_locates`, `test_das_reglas_vigilancia` |
| R-H-04 | `locates.siguiente_paso` parcial (sigue buscando el resto), `entrada.evaluar_senal` paso 16 (`localizadas − usadas`) | `test_das_reglas_locates`, `test_das_reglas_entrada` |
| R-J-01 | `decisor._tic` (feed 30 s diario / 60 s aviso 3 + degradado), `Senal(latido_feed)` | `test_das_decisor` |
| R-J-02 | `cliente.PlanReconexion` (2/4/8/16/30), `decisor` `ConexionDAS` (aviso 3, cada 5 min, `Logon:Failed` → 2FA a mano), F12 antes de enviar nada, `CONEXION_LITERALES` | `test_das_cliente` (corte y reconexión), `test_das_decisor` F11 |
| R-J-04 v2 | `supervisor.PlanRelanzamiento` (1/2/5/10), `Latido` (1 s) + `COLGADO_S` (3 s), `CerrojoInstancia` (instancia única), `HiloVigilado` | `test_das_supervisor`, `test_das_reloj_cerrojo` |
| R-J-05 | `vigilante.PingExterno` (60 s), `vigilancia.debe_hacer_ping` (silencio = alarma); SAI: fuera del código | `test_das_reglas_vigilancia`, `test_das_vigilante` |
| R-J-06 | `supervisor.correr` (DAS → vigilante → ejecutor, reconciliación antes de nada), `subprocess` en la misma máquina; VPS/RDP/Windows Update: fuera del código (runbook) | `test_das_supervisor` |
| R-J-07 | `reloj.desvio_sntp/veredicto_reloj` (2 s se niega, 0,5 s avisa), `supervisor` disco < 5 GB, rotación de logs por día (`instalar_logging`), latencia J18 en `metrica` | `test_das_reloj_cerrojo`, `test_das_supervisor` |
| R-J-08 | `ColaAvisos` (cola + reintentos + `perdidos`), `avisos` correo/SMS para nivel 3, log y `foto.json` siempre | `test_das_avisos` |
| R-J-03 (tabla degradado) | `EstadoBot.modo_degradado` {feed, das, reconciliacion, disco} consultado en `entrada.evaluar_senal` y `decisor._tic`; vigilante gestiona con DAS caído para el ejecutor | `test_das_decisor` (una fila por modo) |
| R-K-01 | `reconciliacion.cadencia_barrido` (1/2/10 s), `comandos_barrido`, barrido tras fill/cancel/reconexión en `decisor` | `test_das_reglas_reconciliacion`, `test_das_decisor` F10 |
| R-K-02 | `reconciliacion.comparar` (orderSrc ≠ CMDAPI o token ajeno → caso 4), `tokens.es_nuestro` | `test_das_reglas_reconciliacion` |
| R-K-03 | `reconciliacion.barrido_caducado` (30 s) → `modo_degradado`, `capital.acciones_que_caben` (BP viejo → 0) | `test_das_reglas_reconciliacion`, `test_das_reglas_capital` |
| R-A-01 | `entrada.evaluar_senal` paso 10, `metrica retraso_senal_pct` | `test_das_reglas_entrada` |
| R-A-02 | lo aplica el bot de alertas (fuera de este paquete); aquí solo `config.tecnicos.filtro_prints_ms` registrado y `MsgTS.condicion` bit 5 en el parser (sin uso) | `test_das_protocolo` ($T&S) |
| R-A-03 v2 | `exclusiones.excluida` (lista negra, SPAC, IPO solo RTH con casilla, split), `exclusiones.banda_opa` (aviso), `referencia_massive.Referencia` | `test_das_reglas_exclusiones`, `test_das_referencia` |
| R-A-04 (A7/A10/A12/A13) | A7 `mercado.sin_cotizacion_desde` + `exclusiones.simbolo_das` + `SIN_SIMBOLO`; A12 `excluida("sin_ficha")` y L None; A13/H-6 `config.motor_hash` + `ejecutor.arrancar` (`Salir(4)`); A10 humano | `test_das_mercado`, `test_das_config`, `test_das_ejecutor` |
| R-A-05 | `Senal.id = id_evento`, `EstadoBot.senales_vistas` (reconstruido del diario), `tokens`, `evaluar_senal` paso 1 | `test_das_decisor` (señal repetida ⇒ 0 órdenes), `test_das_diario` |
| R-A-06 | la señal llega ya calculada con la vela oficial (`FuenteSenales`, mismos `Evento`); precios de ejecución de DAS (`mercado_das`); UNA conexión a Massive (`referencia_massive` es REST; ningún websocket en el paquete); radar en `Senal(clase="radar")` | `test_das_fuente_senales` (paridad con `RunnerAlertas`), `test_das_seguridad` (grep de `websockets` en el paquete = 0) |
| R-D-08 (sustituye R-D-01) | `salidas.temporizadores_lote/orden_hora_agregar/orden_al_ask(techo=None)/perseguir_ask` | `test_das_reglas_salidas`, `test_das_decisor` F5 |
| R-D-02 | `salidas.horas_de_salida` (EOD por estrategia), `comprobar_eod` (+30 s → nivel 3 + control humano), botón/comando `control_humano` | `test_das_reglas_salidas`, `test_das_comandos` |
| R-D-03 v2 | `salidas.tp_parcial/tp_al_vencer` (agregar 60 s, cruzar techo 3 %, limbo), `stops.plan` reduce, `limpieza` vende exceso | `test_das_reglas_salidas`, `test_das_decisor` F4 |
| R-D-04 | `salidas.puede_reentrar` (−1 / 0 / N), `locates.tras_reentrada` (SLReuseQuery), excepciones R-F-03/R-G-03 | `test_das_reglas_salidas`, `test_das_reglas_locates` |
| R-D-05 | `modo_degradado("feed")`: no abrir, mantener con stops, vigilante con precio de DAS, aviso 3 | `test_das_decisor` |
| D13 / D10 | pirámides `add` por `entrada.*` (mismo protocolo); D10 `orden_al_ask` al final del minuto sin límite distinto | `test_das_decisor` (pirámide add), `test_das_reglas_salidas` |
| R-D-06 | `salidas.cerrar_todo` (CancelarTicker + ask/bid con techo 5 %, 2 reintentos, incluye manuales), `comandos` `/cerrar_todo SI`, `/cerrar X [N] SI` | `test_das_reglas_salidas`, `test_das_comandos` |
| R-D-07 | `salidas.prioridad` (TP al ask antes que la entrada de otra), `tp_espera_entrada` | `test_das_reglas_salidas`, `test_das_decisor` F4.2 |
| R-E-01 | `entrada.evaluar_senal` paso 5 | `test_das_reglas_entrada`, `test_das_decisor` |
| R-E-02 | `capital.acciones_que_caben` + `reservar` (orden de llegada, sin reparto proporcional) | `test_das_reglas_capital` |
| R-E-03 | `salidas.al_desactivar`, `decisor._config` (F14), `Lote.version_estrategia`, comandos `cerrar_y_reiniciar`/`esperar_fin_dia` | `test_das_reglas_salidas`, `test_das_decisor` F14 |
| R-L-01 | `supervisor.ventana` (03:55 → último EOD + 30 s, `hay_sesion`), `salidas.ultimo_eod`, ping solo dentro de ventana | `test_das_supervisor`, `test_das_reglas_salidas` |
| R-L-02 | `config.comprobar_coherencia`, `extraer_estrategia` (misma lectura del JSON que el backtester: `definition` normalizada) | `test_das_config` |
| R-M-01 | `Nivel` (1/2/3), `avisos.ColaAvisos`, resumen diario (`decisor._tic` al último EOD: operaciones, resultado por estrategia, incidentes, coste de locates, slippage de `GET AccountInfo`), `/detalle` | `test_das_avisos`, `test_das_comandos` |
| R-M-05 | `Avisar(grupo=A)` inmediato en F1.1 detrás de `alertas_grupo_a.activo` y `avisar_grupo_a`; `texto_grupo_a` reutiliza `formatear_grupo`; cola en hilo aparte; `metrica senal_a_orden_ms` con/sin grupo A | `test_das_ejecutor` (latencias iguales), `test_das_avisos` |
| PREALERTA-SIMPLE | interruptor `alertas_grupo_a.prealerta_simple` (apagado); la prealerta simple se genera en el bot de alertas, no aquí (DIFERIDO con el grupo A) | `test_das_config` (campo [C]) |
| R-M-02 | `avisos.CanalTelegram` (1-3), `CanalCorreo` (2-3), `CanalSMS` (3, `ProveedorSMSNulo` hasta elegir) | `test_das_avisos` (enrutado por nivel) |
| R-M-03 | `reconciliacion.acciones` caso 4 (protección + aviso 3 + `pausa_global`), `/sigue` | `test_das_reglas_reconciliacion`, `test_das_comandos` |
| R-M-04 | `comandos.CONSULTA/DOS_PASOS/CON_SI`, `parsear`, `Confirmaciones`, `responder_consulta`; coherencia tras cierre por Telegram en `decisor._comando` (registrar cerrado, `CancelarTicker`, desprogramar salidas) | `test_das_comandos`, `test_das_decisor` |
| M7 / M8 | sin confirmación antes de operar (ninguna `Avisar` bloquea); M8 = `/modo_seguridad on` o `/apagar` | `test_das_decisor` |
| R-N-01 | `diario.Diario/LectorDiario/reconstruir`, tipos de registro §8, `FSYNC` | `test_das_diario` |
| R-O-01 | `diario.abrir_dia` (versión, hashes), `config.motor_hash`, `ejecutor.arrancar` se niega si no coincide; cambios `[A]` solo apagado | `test_das_diario`, `test_das_config`, `test_das_ejecutor` |
| R-O-02 | `FuenteGrabacion` + `Guion`, `test_das_replay_dias` (dorado por señales/decisiones/tokens), `VERSION` por fecha | `test_das_replay_dias`, `test_das_fuente_senales` |
| R-O-03 | `Fase`, `ClienteDAS(solo_lectura)` + `EnvioProhibido`, `ClienteSombra`, `BOT_DAS_PERMITIR_ORDENES`, fase en cada aviso | `test_das_cliente`, `test_das_ejecutor` (sombra sin mutantes), `test_das_seguridad` |
| ÁREA P | estrategia NORMALIZADA en `config.extraer_estrategia`; `metrica slippage_vs_senal_pct` y `locate_estado.precio_accion` para recalibrar (P4); sin parada por divergencia (P7); P8 = H-6 | `test_das_config`, `test_das_diario` |
| R-Q-01 | credenciales solo por `.env` (`desde_env`, `canales_desde_env`); `FiltroSecretos` (valores literales) en log y diario; `comandos` solo chat_id autorizados; `redactar`; ningún literal en el código (`test_das_seguridad`) | `test_das_seguridad`, `test_das_avisos`, `test_das_comandos` |
| CM1-CM4 | CM1 `config.VigilanteConfig` (fichero, no backend) + `cargar_con_respaldo`; CM2 `CALIENTE`/`aplicar`; CM3 `config_cambio` al diario; CM4 `extraer_estrategia` solo lee `definition` | `test_das_config` |
| H-2 / H-4 / H-5 / H-6 | H-2 `reconstruir` + `ejecutor.arrancar`; H-4 `escribir_atomico`/`validar`/`ultimo_bueno`; H-5 `decisor.procesar` try/except por ticker; H-6 `motor_hash` | `test_das_diario`, `test_das_config`, `test_das_decisor` (H-5), `test_das_ejecutor` |

### 11.2 Borradores y propuestas que se implementan con defecto conservador (no FIJADAS)

| Regla | Dónde | Defecto |
|---|---|---|
| R-C-03 | `rechazos.reintento_stop` (5 intentos, separación 2 s); el punto 3 (cerrar tras 5) NO se implementa | prima R-B-07/EP-1: control humano |
| R-C-04 | barrido 1 s (`STOP_COMPROBACION_S`) + `plan()` tras `Canceled` no pedido | — |
| R-C-05 | sin uso (ninguna estrategia mueve el stop); `plan()` con nivel nuevo pondría primero y quitaría después por construcción | — |
| R-C-06 | `conjunto_deseado` suma lotes del mismo nivel y `Reemplazar` la cantidad | — |
| R-C-08 | `vigilante.py` con watch + acción bajo demanda; `cerrar_si_descubierta=false` | solo avisa |
| R-C-09 | L viene en `Evento.stop` (motor compartido); `evaluar_senal` paso 12 | — |
| R-F-01..06 | `reglas/halts.py` completo; `primera_vela_max_senal_guardada_pct=6`, `t12_min=240`, `margen_limite_pm_pct=5` | PENDIENTES marcados |
| R-I-01 / R-I-02 / R-I-03 | `capital.acciones_que_caben`; riesgo solo del cuadro (`EstrategiaConfig.riesgo_usd`); `config.aplicar` | — |
| B20 bis | `evaluar_senal` paso 11 con `distancia_max_ultimo_bid_pct=5` | encendida (pregunta 1) |
| R-M-06 (PROPUESTA) | NO se implementa ahora (§11.3) | — |
| INVENTARIO §4 | defaults corregidos en `config_ejemplo.json` (§7) | — |

### 11.3 DIFERIDO (con motivo)

| Qué | Motivo |
|---|---|
| Frontend de la pestaña «Ejecución» en `CuadroMandos.tsx`, router `routers/bot_das.py`, tablas `bot_das_*` y cliente `api_bot_das.ts` | Toca ficheros existentes del repo (prohibido en este lote) y el bot no depende del backend en caliente (CM1): hasta entonces `python -m app.bot_das.config exportar` escribe el fichero y los botones van por `estado/comandos.jsonl` y Telegram. |
| Las 8 líneas de `bot.py` con `BOT_DAS_ENLACE=1` (`EnlaceEjecutor`) | `bot.py` vive fuera de git (`D:\bot_senales`) y está en producción con el bot de alertas; se activa cuando el ejecutor pase la sombra con `FuenteGrabacion` y `FuenteEnProceso`. `enlace_bot_alertas.py` queda escrito y probado en dos procesos. |
| Asistente de IA en Telegram (R-M-06) | El libro lo fija «después del canario»; `comandos.parsear` devuelve `None` para texto libre, que es el gancho. |
| Envío real al grupo A y prealerta simple | El grupo A lo sigue sirviendo el bot de alertas actual hasta que se retire (R-M-05); aquí queda `Avisar(grupo=A)` codificado y medido con `alertas_grupo_a.activo=false`. La prealerta simple se genera en el motor de alertas, fuera de este paquete. |
| Proveedor de SMS (R-M-02) y SAI (R-J-05) | Decisiones de compra de Jaume; `ProveedorSMSNulo` mantiene el contrato. |
| Copia del diario fuera del VPS y parquet histórico | Tarea del supervisor al apagar (`robocopy`), sin test. |
| Nasdaq Daily List como fuente de splits | Pregunta 6; `referencia_massive.splits_de_hoy` es la fuente por defecto. |

---

## 12. Orden de implementación en LOTES paralelizables

Regla de reparto (injerto A §7): nadie importa de un lote ajeno salvo `tipos.py`, `tokens.py`, `reloj.py` y los `Protocol` (`CanalOrdenes` en `canal_falso.py`, `FuenteSenales`, `Canal`); los módulos existentes de `bot_alerts_*` y `locates_gate` se importan, nunca se copian. Cada lote entrega sus tests EN VERDE (`pytest backend/tests/bot_das -k <lote>`) y ningún fichero fuera de su lista. Lote 0 primero; A-F en paralelo; G cuando A-F pasan; H con DAS real.

| Lote | Ficheros a crear | Puede leer (además de los suyos) | Contrato que debe cumplir | Tests que entrega |
|---|---|---|---|---|
| **0 · Cimientos** (secuencial, corto) | `bot_das/__init__.py`, `tipos.py`, `tokens.py`, `reloj.py`, `cerrojo.py`, `tests/bot_das/conftest.py`, `tests/bot_das/canal_falso.py`, `tests/bot_das/fixtures/config_ejemplo.json` | `bot_alerts_engine.Evento` (solo para tipar), este documento §2, §7 | §2 literal; `OrdenNueva.__post_init__`; `al_tick`; tokens 336_699_999; `HiloVigilado`; `config_ejemplo.json` con TODOS los defaults de §7 | `test_das_tipos`, `test_das_tokens`, `test_das_reloj_cerrojo` |
| **A · Protocolo y red** | `protocolo.py`, `cliente.py`, `simulador_das.py`, `fixtures/lineas_das.txt`, `fixtures/guion_replay_ejemplo.json` | manual `manual_2026.txt`, especificación §1-§5 | §3.1-3.3 y §4; `parsear` nunca lanza; `formatear_precio` lanza; `EnvioProhibido`; `invalidar`; `ModeloSpread`; 6 permutaciones de mensajes; `%ITRADE` rama propia; `normalizar_pos` | `test_das_protocolo`, `test_das_cliente`, `test_das_simulador` |
| **B · Persistencia y configuración** | `diario.py`, `config.py`, `fixtures/diario_medio_dia_ejecutor.jsonl`, `fixtures/diario_medio_dia_vigilante.jsonl` | `bot_alerts_service.vigiladas` (contrato del puente), memoria «tres ficheros» | §3.7-3.8, §7, §8; write-ahead con fsync; `degradado`; `reconstruir` puro e idempotente sobre DOS diarios; `escribir_atomico`; `motor_hash`; `CALIENTE` = [C] de §7 | `test_das_diario`, `test_das_config` |
| **C · Avisos y comandos** | `avisos.py`, `comandos.py` | `bot_alerts_telegram.agrupar/formatear_grupo` (importados), l.41-62 (SSL) | §3.9-3.10; `urllib` (sin httpx); `FiltroSecretos` con valores literales sobre `msg`+`args`+diario; `poner` < 1 ms; dos pasos; «SI» | `test_das_avisos`, `test_das_comandos` |
| **D · Reglas de dinero** | `reglas/__init__.py`, `reglas/precios.py`, `reglas/entrada.py`, `reglas/stops.py`, `reglas/salidas.py`, `reglas/capital.py`, `reglas/rechazos.py`, `reglas/catalogo_rechazos.json` | `portfolio_sim.py` (literales), `bot_alerts_engine.py` l.1027 y l.1208-1210, `bot_alerts_feed.py` l.177-187, tabla C de la KB | §3.14-3.17, §3.20-3.21; todo `Decimal`; funciones PURAS (sin reloj, sin I/O); `LITERALES_EXIT_REASON` completo; `plan()` idempotente con precondición `neta_das ≠ neta_fills`; `limpieza` con `InvalidarSerie`; `paquetes` no está aquí (lote E) | `test_das_reglas_precios`, `_entrada`, `_stops`, `_salidas`, `_capital`, `_rechazos` |
| **E · Reglas de contexto** | `reglas/halts.py`, `reglas/cisne_negro.py`, `reglas/locates.py`, `reglas/exclusiones.py`, `reglas/reconciliacion.py`, `reglas/vigilancia.py`, `mercado_das.py`, `referencia_massive.py` | `locates_gate.ev_fijo_para_precio/rangos_ev_normalizados` (NO `evaluar`), `bot_alerts_runner.estimacion_locates` (forma de las filas), manual L1079-1133 | §3.12-3.13, §3.18-3.19, §3.22-3.25; `paquetes` H6 (1.230 → 12; 1.240 → 13); coste TOTAL en el EV; `momento_envio_open` + `debe_enviar_open`; `splits_hoy=None` no excluye; `inferir_proposito` (lo usa `vigilancia`, importa de `reglas.stops` — la ÚNICA importación entre lotes D→E, declarada aquí) | `test_das_reglas_halts`, `_cisne_negro`, `_locates`, `_exclusiones`, `_reconciliacion`, `_vigilancia`, `test_das_mercado`, `test_das_referencia` |
| **F · Fuentes de señal** | `fuente_senales.py`, `enlace_bot_alertas.py`, `fixtures/AM_recorte.jsonl.gz` | `bot_alerts_runner.RunnerAlertas`, `bot_alerts_cliente.id_evento`, `bot_alerts_alerta_proceso.py` l.40-51 (protocolo de referencia), `grabador.py` (formato), `tests/test_bot_alerts_procesos._velas` | §3.11; pandas SOLO dentro de `FuenteEnProceso/FuenteGrabacion`; `radar` añade `strategy_id` por nombre; `hola` con `motor_hash`; `authkey` obligatoria; `Guion` | `test_das_fuente_senales` |
| **G · Integración** (1-2 personas, tras A-F) | `decisor.py`, `ejecutor.py`, `vigilante.py`, `supervisor.py`, `herramientas/__init__.py`, `herramientas/comprobar_das.py`, `fixtures/esperado_AAAA-MM-DD.jsonl` (vacío hasta el primer día grabado) | todo el paquete | §3.26-3.27, §5 (F1-F14), §6, §9; un solo hilo muta; write-ahead antes del `send`; política de disco; `Latido.tocar(todo_vivo)`; `PedirAlSupervisor`; sombra sin mutantes; `senal_a_orden_ms` con/sin grupo A; pandas ausente en modo tubería | `test_das_decisor`, `test_das_ejecutor`, `test_das_vigilante`, `test_das_supervisor`, `test_das_seguridad`, `test_das_replay_dias` |
| **H · Primer día con DAS** (fuera de tests; con claves en el `.env` del VPS) | ninguno (rellena `catalogo_rechazos.json`, `tipo_esperado_en_order`, `get_con_simbolo`, `qty_corto_negativa`, `lineas_das.txt` con el `%ORDER` real) | — | `comprobar_das.py` pasos 1-9 con confirmación por consola; sombra 1 semana; canario 1-2 semanas | los fixtures nuevos entran en `test_das_protocolo` |

Dependencias reales: D y E importan solo de `tipos/tokens/reloj` (y E de `reglas.stops.inferir_proposito`); C y B son independientes; F depende de `tipos` y del bot de alertas existente; G importa de todos. Con `canal_falso.py`, los tests de D/E/G-decisor corren sin A.

Criterio de «hecho» de cada lote: (1) tests en verde; (2) `python -c "import app.bot_das.<modulo>"` no ejecuta nada ni abre red; (3) docstring de módulo con QUÉ/POR QUÉ/TRAMPAS; (4) ninguna cadena que parezca credencial; (5) revisión cruzada por otro lote leyendo solo este documento.

---

## 13. Riesgos de código y mitigación

| # | Riesgo | Mitigación en el diseño |
|---|---|---|
| 1 | `%ORDER` con `Type` de varias palabras desplaza campos y el bot lee `qty` mal (posición mal dimensionada SIN error) | parser anclado por `estado`+`hora` desde la derecha (§5.2); `tipo_das_crudo` al diario; test con «SLP: 2.97 2.99»; `comprobar_das` paso 3 guarda el primer STOPLMTP real como fixture |
| 2 | Token confundido con un número final de `notes` | `tokens.es_nuestro` valida origen/día/rango antes de aceptarlo; si no casa → `token=None` y se cruza por `id_das` |
| 3 | Orden enviada y proceso muerto antes de anotarla → al arrancar, orden «desconocida» propia | `orden_intencion` con fsync ANTES del `send`; la reconciliación casa por token (nuestro) aunque falte `orden_enviada` |
| 4 | Doble envío por reintento de red o por señal repetida (R-A-05) | `senales_vistas` reconstruido del diario; un token por intento; `plan()` idempotente; `Cancelar` espera `Canceled` antes del cruce |
| 5 | Carrera fill↔cancelación: el cruce se envía por más de lo que queda ⇒ más corto de lo pedido | `resto_a_cruzar` solo tras `Canceled` (`cantidad_cancelada` de `qty`/`cxlqty`) o `GET ORDERS`; nunca de lo pedido (injerto §8.7); si aun así sobra ⇒ `VENTA_EXCESO` solo si neta LARGA |
| 6 | Quedarse LARGO tras principal + emergencia (R-C-11 b) | `limpieza_tras_fill_stop` por evento en decenas de ms; vende SOLO la neta positiva; barrido de control a 1 s |
| 7 | Un `REPLACE` de stop con la cantidad ANTERIOR sale después del fill (carrera emisor↔fill) | versión del objetivo por ticker (`version_stops`), `serie="stops:X"` en cada orden/replace, `InvalidarSerie` antes del nuevo plan, el emisor descarta versiones viejas (injerto §8.6); test con REPLACE encolado y fill intermedio |
| 8 | Orden entre `%OrderAct Execute`, `%TRADE` y `%POS` NO documentado: la neta de `%POS` llega tarde o antes | libro de fills por token = verdad inmediata (`neta_fills`); `%POS` solo reconcilia (caso 6); `plan()` NO toca la emergencia si discrepan y pide `GET POSITIONS` (corrección 2); el simulador permuta los 3 mensajes en los tests |
| 9 | Signo de `Quantity` en cortos no documentado | `normalizar_pos` por `tipo == 3` con `abs()`: correcto con signo positivo o negativo; `qty_corto_negativa` se registra el primer día (injerto §8.8) |
| 10 | Sombra que envía una orden real por un camino no previsto | dos candados de código (`EnvioProhibido` + `ClienteSombra`) más la llave de entorno `BOT_DAS_PERMITIR_ORDENES` para las fases con dinero; test de un día entero sin mutantes |
| 11 | Bucle de stops/REPLACE (100/min) o de locates | `CuotaComandos` al 90 %; `plan()` cancela la más nueva y nunca crea si ya hay; `compra_repetida` deshabilita locates; el vigilante avisa nivel 3; persecución al ask limitada a 3 REPLACE |
| 12 | Precios en coma flotante (10·1,03 = 10,299999…), notación científica, acciones fraccionarias | `Decimal(str(x))` en `precios.de_float`; `formatear_precio` LANZA fuera de tick; `OrdenNueva.__post_init__` exige `int > 0`; `qty_de_evento` es el único punto de conversión (injertos §8.1-8.2) |
| 13 | Zonas horarias: `Evento.momento` naive ET, reloj del VPS, `%ORDER` con `HH:MM:SS` sin fecha | `reloj.py` es el único que crea `datetime`; `hora_das_a_et`; `t_cierre_vela` probado contra la fixture; test del cambio de día |
| 14 | Reloj desviado (memoria: 0,6 s/día) falsea latencias y caducidades | `desvio_sntp` al arrancar y cada hora; > 2 s se niega; latencias con `mono()` |
| 15 | `$Quote` parcial interpretado como bid/ask nulos → «sin cotización» → señales perdidas | libro incremental; `fresca()` mira `actualizada_en`; test explícito |
| 16 | Excepción en un ticker deja sordo al bot (H-5) | try/except por rama y ticker en `Decisor`; `Anotar(excepcion)`; ticker pausado; test con `precio=None` |
| 17 | Cola sin tope crece si DAS inunda | no se suscribe `tms`; Lv1 ≤ 100; tamaño de cola en la foto; aviso 2 si > 10.000 |
| 18 | pickle entre versiones distintas de `Evento` (bot.py viejo vs paquete nuevo) | `hola{version, motor_hash}`; campos leídos con `getattr(ev, "x", None)`; campo obligatorio ausente ⇒ señal descartada + aviso 2 |
| 19 | `multiprocessing.connection` sin `authkey` acepta a cualquiera en localhost | `BOT_DAS_AUTHKEY` obligatoria (sin ella la tubería no arranca) |
| 20 | Fuga de secretos en logs o diario (httpx, LOGIN, `notes`) | sin httpx en el paquete (urllib); `FiltroSecretos` con los VALORES literales sobre `msg`+`args`; `redactar()`; `limpiar` en el diario; test grep sobre log y diario de un replay (corrección 8) |
| 21 | Config en caliente aplicada a medias (riesgo cambia con un intento vivo) | `aplicar` devuelve la config completa y el decisor la sustituye ENTRE mensajes; el intento conserva `cfg_congelada`; el lote conserva `version_estrategia` |
| 22 | Diario del vigilante desfasado o dos procesos escribiendo el mismo fichero | un diario por proceso; `LectorDiario.seguir` por `seq`; sin diario del ejecutor el vigilante trata toda posición como desconocida (protección 20-30 %); `inferir_proposito` para las suyas |
| 23 | El write-ahead falla (disco lleno, fichero bloqueado) y el bot sigue abriendo sin registro | `degradado` → no entradas/pirámides/locates, sí stops/cancelaciones/cierres; aviso 3; test (corrección 4) |
| 24 | Salida del motor no contemplada (`Signal`, `Trailing`, `Time Limit`, `?`) queda sin tratar | `LITERALES_EXIT_REASON` completo y test que lee `portfolio_sim.py`; desconocido → MOTOR + `salida_desconocida`; tratamiento provisional «como TP» (pregunta 3) |
| 25 | Radar sin `strategy_id`: locates comprados para la estrategia equivocada | la fuente casa por `nombre` y añade `strategy_id`; nombres repetidos → fila descartada + aviso (corrección 6); `cantidad_a_localizar` casa por id |
| 26 | `subprocess` hijos huérfanos si el supervisor muere (memoria «puerto 8010 huérfanos») | hijos con cerrojo propio (no arrancan dos); el supervisor al arrancar mata por PID guardado si el cerrojo está tomado por un proceso sin latido; los hijos NO son daemon: siguen protegiendo la posición |
| 27 | Halt sin hora de fin: `halt_decidir` en el pasado o MKT enviada dos veces | `momento_envio_open` devuelve 0 si desconocido/pasado; `debe_enviar_open` + `orden_open_enviada` (injerto §8.23) |
| 28 | Replay sin spread da fills no comparables | `ModeloSpread` declarado en el `Guion`; el dorado compara señales/decisiones/tokens, no precios (injerto §8.24) |
| 29 | pandas en el ejecutor (import lento, GIL) | `FuenteTuberia` por defecto; imports perezosos; `test_das_seguridad` (1) |
| 30 | Un hilo de borde muere en silencio y el ejecutor sigue «vivo» sin leer DAS | `HiloVigilado` relanza y avisa; `Latido.tocar(todo_vivo=False)` cuando un hilo crítico no revive → el supervisor relanza el ejecutor (injerto §8.11) |
| 31 | El vigilante no puede enviar (segunda conexión normal no admitida, 2e.1) y una posición queda descubierta | `puede_enviar=False` → aviso 3 + `PedirAlSupervisor("relanzar ejecutor")` (1 s) (corrección 16); se comprueba el primer día (paso 7) |
| 32 | Reglas con valores obsoletos de la sección 4 del libro | defaults en `tipos.py` y `config_ejemplo.json` con los VIGENTES y un test que cita la regla junto a cada valor; `validar()` rechaza combinaciones imposibles |
| 33 | Puntos abiertos codificados como si fueran reglas | cada [PENDIENTE] es un parámetro con defecto conservador y citado en §14; R-C-03.3 y el cierre del vigilante NO se implementan |
| 34 | Locates: `locates_gate.evaluar` cobra 13 paquetes donde H6 dice 12 y no admite coste acumulado | `veredicto_ev` propio con `paquetes()` H6 y coste total; solo se reutiliza `ev_fijo_para_precio` (corrección 1); test 1.230/1.240 |
| 35 | `splits_de_hoy` falla y se excluye todo (o nada se avisa) | `None` → no excluir + aviso 2 una vez (corrección 17) |
| 36 | Cuota de `SLPRICEINQUIRE` global: con 10 tickers en el radar el último espera 30 s | `CuotaComandos.inquire_s` serializa; se mide en sombra la cola de inquires; pregunta 7 a Jaume/DAS (¿por símbolo?) |

---

## 14. Preguntas abiertas para Jaume (solo las que bloquean el código)

1. **B20 bis (D = 5 %)**: R-B-01 v3 no la menciona y el libro no la retira. Se implementa como `entrada.distancia_max_ultimo_bid_pct` (null = apagada). ¿Arranca ENCENDIDA a 5 % o apagada?
2. **Locates ≤ 30 acciones**: H6 dice «el último paquete solo si se usa MÁS del 30 %» y H-7 «locates siempre ≥ 100». Con 30 acciones exactas (30 % justo) hoy `paquetes` devuelve (1, 30) por el mínimo de un paquete. ¿Es eso, o con ≤ 30 no se entra?
3. **Salidas del motor `Signal` / `Trailing` / `Time Limit` / `Escalera` / `?`**: los flujos del libro cubren TP, hora, EOD, stop, halts y BS. Propuesta codificada como `salidas.salida_motor = "como_tp"` (agregar 60 s en el punto medio, cruzar al ask con techo 3 %, R-D-03). ¿Vale, o se ignoran?
4. **Salida `SL` del motor con la posición aún abierta en DAS** (el backtester habría cerrado y la STOPLMTP residente no ha disparado): el diseño NO persigue, registra `divergencia_sl` y avisa nivel 2. ¿Confirmas?
5. **Política cuando el diario no puede escribirse**: no salen entradas, pirámides ni compras de locate; sí stops, cancelaciones, ventas de exceso y cierres. ¿Confirmas?
6. **Fuente de splits del día**: Massive `/v3/reference/splits` (ya tenemos la clave) o Nasdaq Daily List (el libro la nombra; requiere descarga y parseo). Por defecto Massive; sin dato no se excluye y se avisa.
7. **Cuota del `SLPRICEINQUIRE`**: el manual dice «1 cada 3 s» sin aclarar si es global o por símbolo. El diseño arranca en la conservadora (global): con 10 tickers en el radar, el último espera 30 s. ¿Preguntar a DAS o aceptar la espera?
8. **Estado hacia la app en fase 1**: solo `estado/foto.json` y `estado/comandos.jsonl` (sin endpoints nuevos, sin tocar el backend). ¿Suficiente para sombra y canario?
9. **Modo de seguridad con `V × VWAP` de `$Quote` de DAS** como «Acum. Dollar Volume» (Massive no llega al ejecutor en fase 1). ¿Vale la aproximación?
10. **`GET LDLU` / `GET SymStatus` con símbolo**: el manual no lo muestra; se asume `GET SymStatus XYZ` y se comprueba el primer día. Si no admiten símbolo, la única forma es suscribir Lv1 y esperar la respuesta suelta. ¿De acuerdo con comprobarlo así (paso 2 de `comprobar_das.py`)?
11. **Vigilante y envío de órdenes**: si DAS no admite una segunda conexión normal (2e.1: «una cuenta = un usuario = una máquina»), el plan B de R-C-07 solo vale vía relanzar el ejecutor en 1 s (corrección 16). ¿Aceptas ese fallback como definitivo si el paso 7 confirma que no puede enviar?
12. **Separación entre los 5 reintentos de stop (R-C-03)**: defecto 2 s. ¿Otro valor?

Lo que NO pregunto porque ya está decidido en el libro y aquí se aplica tal cual: márgenes +3/+13/+63; R-B-01 v3 con PostOnly y redondeo arriba; demo descartada; I1 sin cortacircuito; cadencia BS 1 min × 5; vigilante 1/2/5/10 s; IPO < 30 d solo RTH; OPA = aviso.

---

## 15. Cambios decididos tras la revisión del código (27-sep-2026)

El paquete se construyó según §1-§12 y después pasó una revisión independiente en 16 grupos (reglas del libro, riesgos de §13, contratos entre unidades, tests, seguridad y cobertura regla a regla): 152 hallazgos, 8 críticos y 46 altos, corregidos y verificados por un segundo agente. Donde el arreglo exigía una decisión, el director la tomó con el criterio «nunca cuenta larga ni descubierta, nunca órdenes duplicadas, nunca un aviso perdido». Estas decisiones PREVALECEN sobre §3 y §5 donde choquen:

- **Ajustes de construcción (a)-(h):** `Ficha`, `NivelesStop` y `StopDeseado` viven en `tipos.py`; `reglas/precios.py` es del lote 0; `entrada.evaluar_senal` recibe `exclusion: Optional[str]` (la calcula el decisor con `exclusiones.excluida`); no existe `avisos.texto_informe_bs`; `cisne_negro` usa `salidas.orden_al_ask`; el literal `Lot TP (n/m)` de `portfolio_sim.py` es TP; las firmas reales mandan; el diario recibe el limpiador de secretos por inyección.
- **Stops (R-C-01 v3 / R-C-11 / R-F-02):** bajo la banda, todo principal cuyo disparo quede ≥ disparo de la emergencia se elimina (solo emergencia); `reasignar_principal_rebasado` exige `last > límite` (el ask solo no basta); la venta del exceso descuenta las `VENTA_EXCESO` en vuelo, cancela una a una las compras y las ventas de ENTRADA vivas (nunca `CANCEL ALLSYMB` con una venta de exceso viva), sale a `bid × (1 − 1 %)` y se persigue con `exceso_verificar` cada 1 s hasta 3 veces, luego aviso 3 «vender a mano»; con `neta_das ≠ neta_fills` del mismo signo, `plan` solo BAJA cantidades con `n = min(−neta_fills, −neta_das)`; un `NEWORDER` purgado por versión en el emisor vuelve al decisor como `OrdenDescartada` (CLOSED + replan al instante).
- **Halts (R-F-01/05/06):** al enviar `HALT_OPEN`/`HALT_BANDA` por Q acciones se reducen antes principal y emergencia en Q (a 0 → cancelar) y `plan()` los restaura si la orden se rechaza o no llena 2 s tras la reapertura; en un halt H (no LULD) la orden por OPEN es un LÍMITE a `precio_parada × (1 + 250 %)`, nunca MKT, y el tope T1 se vuelve a medir con el `last` real tras reabrir; con cisne negro activo el bot no cierra en la reapertura (avisa nivel 3); en PM con decisión «mantener» los stops límite se ensanchan (`margen_limite_pm_pct`); k se siembra desde el diario y el `simstatus` cubre en RTH también los tickers del radar suscritos; `TA:Q` es «parado» salvo que lleguen prints nuevos durante 5 s.
- **Decisor:** una sola guarda para toda salida por temporizador (no BS, no HALT, no control manual/humano, no `modo_degradado` «reconciliacion»/«das»; se reprograma a 0,5 s, nunca se descarta); la cantidad de toda salida por lote se capa a `min(libres, −neta − compras vivas del ticker)`; el intento de entrada se cancela cuando la posición queda plana o un lote del intento cierra (R-D-07 solo entre estrategias distintas); la Referencia de Massive vive en un hilo aparte con caché (el decisor nunca hace red); `/sigue X`, `/parar_avisos X BS` y `/stop X P SI` funcionan como pide el libro; agotar R-C-03 bloquea solo la reposición de ese propósito.
- **Salidas (R-D-03/06/07/08):** `cerrar_todo` en dos pasos (cancelar → enviar tras el `Canceled` por la neta de ese momento), un temporizador por ticker, con discrepancia de netas cierra el mínimo del mismo signo, y al agotar cancela su orden viva antes de avisar; «Partial TP (Hour)», «Partial TP (Time)» y «Time Limit» se ejecutan como salida por hora con la cantidad del evento; `tp_cruce` es por orden; la tanda de una vela se ordena con `salidas.prioridad` en la fuente; un agregar rechazado por PostOnly pasa directo al cruce.
- **Entrada y capital:** tercer límite `caben_equity` (margen inicial de Sage contra el equity, no solo contra el BP); la comprobación 16 usa la regla de `locates.asignar_a_lote` (sobrantes de otras estrategias y ETB); en la reapertura de un halt se salta también el filtro de retraso R-A-01; reentradas alineadas con `salidas.puede_reentrar` (−1 / 0 / N).
- **Persistencia y avisos:** `reconstruir` cuenta los fills anotados antes del `%TRADE`, no machaca la intención con `orden_simulada`, rellena `ordenes_ajenas` y `k`; el offset de Telegram se persiste con hash del token y caducidad de 6 días y la deduplicación es por `update_id` entregados; todo texto variable a Telegram va escapado y `CanalTelegram` reenvía sin formato ante un 400; el emisor no se bloquea en cabeza por cuota (respeta el orden dentro de cada serie e id).
- **Fuentes y procesos:** por la tubería viajan solo primitivos (nada de pandas en el ejecutor, tampoco en la primera señal) y la versión del enlace se exige en el «hola»; el arranque mide SNTP y conecta en un hilo auxiliar tocando el latido; fuera de la ventana con posición el supervisor sigue relanzando hijos; el proceso de DAS se comprueba cada 30 s; el vigilante con el ejecutor muerto y la cuenta larga vende el exceso (pendiente de confirmar por Jaume).

Las decisiones que Jaume debe confirmar o cambiar están en el resumen de entrega (venta del exceso 1 %/3 vueltas; reducir stops al salir por OPEN; no cerrar en halt con cisne negro; PostOnly → cruce; el vigilante vende el exceso; k de halts anteriores a la entrada; límite T1 por OPEN a ×3,5; y las 12 preguntas de §14).

---

*Fin del documento. El paquete existe en disco (`backend/app/bot_das/`, tests en `backend/tests/bot_das/`) y sigue §1-§12 con los cambios de §15.*
