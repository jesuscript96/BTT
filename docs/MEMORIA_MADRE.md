# Memoria madre

> **Qué es esto (renombrado el 2026-08-26).** Este documento pasa a ser el
> registro cronológico PRINCIPAL del repo BTT: aquí se reportan las auditorías
> y cambios que se vayan haciendo, para Sailor y para el socio por igual.
> Sustituye al antiguo `docs/MEMORIA.md` de `staging` — esa rama se vació y se
> igualó a `sailor-rama-desarrollo` el 2026-08-26, así que este es ahora el
> único que existe.
>
> Se sigue escribiendo hacia abajo, sin editar lo anterior — igual que su
> hermano `Base de datos Backtester/docs/MEMORIA.md` (fuera de este repo, para
> el proyecto del lago de datos). El detalle numérico de cada sesión del
> backtester vive aquí; el del lago, allí.
>
> **Nota histórica:** hasta el 2026-08-26 este fichero se llamaba
> `CAMBIOS_SAILOR_PARA_STAGING.md` y era "una nota para que el otro
> desarrollador decida qué adoptar, no una petición de merge". Las entradas de
> antes de esa fecha se escribieron con ese espíritu — léanse con ese matiz.

---

## 2026-08-22

### 1. Comisiones `FLAT`: de $/operación a $/ACCIÓN, cobrado en los dos lados

**Esto sí afecta a producción y hay que acordarlo.**

Antes: `fee_amount = fees * 2`, una cantidad fija por operación que **ignoraba el
número de acciones**. Con `fees=0,003` y 10.000 acciones cobraba 1 céntimo.

Ahora: `fee_amount = fees * acciones * 2`. Es decir, `fees` es **$ por acción**,
y se cobra una vez en la compra y otra en la venta.

Ejemplo: 0,003 $/acción con 100 acciones → 0,30 $ al comprar + 0,30 $ al vender
= 0,60 $.

Tocado en los CUATRO motores que deben ir en paridad: `portfolio_sim_jit.py`,
`portfolio_sim.py`, `portfolio_lab_engine.py`, `portfolio_lab_scaling.py`
(14 sitios). `PERCENT` no se toca.

Verificado sobre 396 trades reales: `0,003 × 18.970,43 acciones × 2 = 113,82 $`,
y la diferencia de PnL contra la misma corrida sin comisiones es 113,82 $.

**Nota sobre el desacuerdo previo:** staging había redefinido `FLAT` como
`fees × qty` (por acción, un solo lado). Esto va en la misma dirección pero
cobrando los dos lados, que es como factura un bróker real.

### 2. Bug: las comisiones de las salidas PARCIALES se cobraban pero no se reportaban

En una salida parcial, la comisión se restaba del `pnl` pero se registraba como
`0` (`r_fees[k] = 0.0` en el JIT; la clave `fees` directamente ausente en el
motor Python). El agrupador de ejecuciones de `backtest_service` suma los
`fees` de cada tramo, así que la de los parciales se perdía.

Los dos motores mentían igual, así que estaba en paridad y no saltaba ningún
test. Con comisiones fijas de céntimos era invisible; con comisiones por acción
era el **34 %** de las comisiones totales (mostraba 75 $ de 114 $).

Corregido en `portfolio_sim_jit.py`, `portfolio_sim.py` y `sim_dispatch.py`.
**Solo afecta al informe**, no al PnL, que siempre estuvo bien.

### 3. Sortino: downside deviation canónica

`backtest_service.py` calculaba el Sortino con `np.std` de **solo los retornos
negativos**, que los mide alrededor de su propia media en vez de alrededor de
cero y no divide por el total. Dos sesgos que lo inflan. Cambiado a
`sqrt(mean(min(ret,0)²))` sobre todas las observaciones, que es lo que ya hacía
el módulo de portfolio — antes la misma estrategia mostraba dos Sortinos
distintos en dos páginas de la misma app.

Métrica de presentación: no cambia ni un trade ni un dólar de PnL.

### 4. `build_screener_query`: los booleanos reventaban la consulta

`require_shortable` / `exclude_dilution` son interruptores de la interfaz, no
columnas de `daily_metrics`. Pero `float(True)` vale 1.0, así que se colaban por
el camino numérico y generaban `require_shortable >= 1.0` →
`BinderException` que tumbaba la consulta entera. Los `None` ya caían solos por
el `except`; los booleanos no. Una línea: `if isinstance(v, bool): continue`.

Cualquier dataset guardado con esos filtros fallaba al recalcular sus pares.

### 5. El sondeo del backtest reintentaba para siempre

El registro de trabajos vive en memoria. Si el proceso se reinicia con un
backtest en marcha, el `job_id` desaparece y el frontend recibe un 404
permanente — que el `catch` trataba como «error de red pasajero», reintentando
cada 500 ms indefinidamente. Ahora se toleran 3 seguidos (carrera al crear el
trabajo) y luego se para con un mensaje claro.

---

## Lo que es SOLO del entorno local de Sailor

Está todo detrás de `LAKE_UPDATE_ENABLED`, que en producción va apagado.

- **`backend/app/services/lake_db_loader.py`** (nuevo) y los cambios en
  `routers/lake_update.py`: el botón de actualizar el lago local ahora cierra
  la cadena entera — carga el Parquet en `local_data.duckdb` desde el propio
  backend (sin cerrarlo), amplía la ventana de fechas de los datasets que iban
  al día, y añade los días nuevos al caché por ticker.
- **`routers/query.py`**: `_populate_dataset_pairs` partido en
  `_compute_dataset_pairs` + `_insert_dataset_pairs`. Sin cambio de
  comportamiento; permite calcular los pares una vez y reutilizarlos.
  `_insert_dataset_pairs` ahora devuelve las filas realmente añadidas.

**Dos cosas de aquí sí podrían interesar en producción**, porque el mismo patrón
existe allí:

1. `intraday_1m_optimized` **se queda vieja en silencio** cuando se reprocesa un
   mes, y el motor la prioriza sobre la cruda. `gcs_cache.py` lo documenta como
   runbook manual y nada lo hace cumplir. Aquí costó 41 ticker-días descartados
   sin ningún aviso. En local se ha descartado la copia entera; en producción
   habría que automatizar su regeneración o el guardián.
2. El **caché por ticker-mes** tiene el mismo problema un nivel más abajo: se
   escribe una vez y no se revisa aunque el mes crezca.

## 2026-08-24

### Botón de apagado del entorno local (`ShutdownButton`)

**Solo local, apagado por defecto en producción.** Botón redondo de encendido en
la esquina inferior derecha que cierra backend (8010) y frontend (3000) de una
vez, con confirmación previa. Existe porque el arranque local se hace ahora con
un acceso directo del escritorio y las dos consolas quedan minimizadas: sin esto
hay que ir a buscarlas, y un puerto que queda ocupado por un zombi sirve código
viejo sin avisar.

Ficheros nuevos: `backend/app/routers/local_control.py`,
`frontend/src/components/ShutdownButton.tsx`.

Compartidos tocados, mínimo: `backend/app/main.py` (+4 líneas: import y
`include_router`) y `frontend/src/components/LayoutShell.tsx` (+4: import y
`<ShutdownButton />`).

Gating igual que `lake_update`: `LOCAL_SHUTDOWN_ENABLED` (default `false`) +
`LOCAL_SHUTDOWN_SCRIPT`. Sin las dos, `GET /api/local-control/status` responde
`{"disponible": false}` —y entonces el componente devuelve `null`, no pinta
nada— y el `POST /shutdown` responde 503. En producción no existe ninguna de las
dos variables ni el script, así que el módulo es inerte.

El trabajo sucio lo hace un script de PowerShell fuera del repo
(`D:\lanzador_btt\apagar_btt.ps1`), no el backend: uno de los procesos que hay
que matar es el propio backend.

**Trampa medida, por si alguien replica el patrón de lanzar un proceso que va a
matar a su padre:** con `subprocess.DETACHED_PROCESS`, `powershell.exe` se queda
sin consola, **sale con código 0 sin ejecutar una sola línea** y no deja error en
ninguna parte. Parecía que el apagado fallaba y en realidad nunca empezaba. Con
`CREATE_NO_WINDOW` funciona. El script escribe además su propio
`apagar_btt.log`, porque el proceso que podría contar lo que pasó es justo una de
las víctimas.

### Monte Carlo Bootstrap: bloque de perdidas y simulador de fondeo

Dos secciones nuevas al final del panel de Monte Carlo, pensadas para decidir si
una estrategia pasa una prueba de fondeo (limites de perdida diaria, drawdown y
minimos de operaciones).

**1. Perdidas, dia a dia.** Peor sesion y racha perdedora maxima (simulado
contra real), media y mediana de ganancia y perdida por sesion y por trade, y
dos cajas con slider: probabilidad de perder X dolares en una sesion y
probabilidad de un drawdown de X%. El modelo es **ECDF empirica** —se cuenta que
fraccion de los casos queda por debajo del umbral, sin ajustar ninguna normal— y
asi se dice en pantalla.

Para que los sliders no obliguen a re-simular, el backend devuelve la ECDF
comprimida en **rejillas de 501 cuantiles** (`losses.grids`): 4 KB en vez de los
400 KB que costaria mandar 50.000 simulaciones, y el navegador resuelve
cualquier umbral interpolando.

Se distinguen dos preguntas que se confunden con facilidad y que en la interfaz
van separadas: la probabilidad de que **una sesion cualquiera** pierda X, y la
de que **al menos una sesion de la corrida entera** lo haga. Para un limite
diario manda la segunda.

Aviso incluido en la propia UI: el bootstrap **no puede generar un dia peor que
el peor dia real**, porque solo baraja lo que ya ocurrio. Con tamaño de posicion
fijo (modo aditivo) las tres cifras de "peor sesion" salen identicas por
construccion; no es un bug.

**2. Simulador de fondeo** (`services/robustness_funding.py`, endpoint
`POST /api/robustness/funding`). Recorre cada simulacion **sesion a sesion y para
en el primer evento**: mirar el drawdown maximo y el retorno final por separado
da un resultado equivocado, porque quien revienta el limite diario en la sesion 8
nunca llega al objetivo. Reglas configurables: perdida diaria medida **desde el
balance de apertura del dia**, drawdown **trailing desde el maximo** (en % del
pico o en $ fijos), objetivo en %, minimos de sesiones y de operaciones, y plazo
conmutable entre infinito y un numero fijo de sesiones. Devuelve el reparto en
cuatro desenlaces: pasa / rompe limite diario / rompe drawdown / sin resolver.

Se evalua por partida doble: por **cierre diario** (exacto) y por **MAE**, que
suma la excursion adversa de las operaciones del dia para estimar el peor punto
intradia. El MAE es una **cota pesimista** —supone que todas las operaciones
tocaron su peor punto a la vez— y en la UI se presenta como tal. La diferencia
entre las dos lecturas es lo interesante: si la de MAE se hunde, la estrategia
pasa el fondeo solo porque los dias malos se recuperan antes del cierre.

Ficheros nuevos: `backend/app/services/robustness_funding.py`,
`frontend/src/lib/robustez/loss_stats.ts`,
`frontend/src/components/robustez/charts/MonteCarloExtras.tsx`.
Tocados: `services/robustness_mc.py` (bloque `losses`, aditivo al payload),
`routers/robustness.py` (endpoint nuevo + campo `unit` en `/montecarlo`),
`lib/api_robustez.ts`, `modules/useMonteCarlo.tsx`.

Nada de esto cambia el resultado de ningun backtest ni toca los motores: solo
lee la corrida guardada. El campo `unit` de `/montecarlo` tiene default y no
rompe clientes antiguos.

**3. Los dos bloques se montan tambien en el Monte Carlo del modelo** de
Portfolio (`ScalingSection`), sobre la serie diaria de la cartera combinada. Por
eso `LossesSection` y `FundingSection` reciben datos sueltos y no un
`RobustezRun`: el portfolio no tiene trades individuales ni MAE. Los huecos se
ocultan solos — alli no sale la fila "por trade" ni la tarjeta de MAE, y el pie
lo dice. `realLossStatsFromDaily` construye el lado real a partir de la serie
diaria ya calculada.

En el portfolio el mando de riesgo se reetiqueta a "Multiplicador de exposicion"
(`riskLabel`/`riskHint`): el riesgo por trade ya esta dentro del modelo, asi que
ahi ese numero escala la serie entera.

**Estilo**: sin tarjetas. Se reutilizan `InlineStats` y `DataTable`, y todas las
explicaciones viven dentro de un `?` en vez de ocupar media pantalla. De paso se
convirtieron a `InlineStats` los dos `TileGrid` que ya existian en el panel de
Monte Carlo ("cuanto drawdown hay que tragar" y "rango de escenarios").

Por que la tabla de medias solo tiene filas REALES: el bootstrap remuestrea los
mismos pasos con reemplazo, asi que la distribucion de un paso cualquiera es la
real y su media y mediana coinciden salvo ruido de muestreo (medido: $326,13
simulado contra $326,95 real). Lo que si aporta el Monte Carlo son los extremos
y las probabilidades, que estan en los otros bloques. Queda explicado en el `?`.

La fila "peor sesion en % del capital" si merece columnas simuladas y no es
redundante: en modo compuesto el % esta acotado por el peor dia real pero los
dolares no —la misma R duele mas cuando la cuenta ha crecido—, y en modo aditivo
pasa justo lo contrario. Verificado en pantalla con los dos modos.

### Borrado definitivo de estrategias desde el baul del Portfolio

Boton **borrar** en cada fila del baul generico (solo ahi: en los cuadros
Portfolio e Incubadora se mantiene «x quitar», que no borra nada). Confirmacion
en dos pasos dentro de la propia fila, sin modal, porque las filas son finas y un
solo clic se da sin querer.

**Por que un endpoint nuevo y no el `DELETE /api/strategies/{id}` existente:**
aquel solo quita la fila de `strategies` y deja las corridas en
`backtest_results`. Como cada corrida arrastra su `results_json` de varios MB,
borrar a medias no resuelve el problema que lo motivo — que el baul crezca sin
freno. `DELETE /api/portfolio-lab/strategies/{id}` limpia las cuatro capas:
`strategies`, sus corridas, `portfolio_lab_assignments` y
`portfolio_lab_monitor`.

**Corridas de cartera: tambien se borran** (decision del usuario, "ni rastro").
Una fila de `backtest_results` puede referirse a varias estrategias. Si se borra
una de ellas, esa corrida combinada desaparece — las OTRAS estrategias no se
tocan, siguen en el baul con sus propias corridas, pero ese resultado conjunto ya
no seria reproducible. Motivo de fondo: el id no vive solo en la columna
`strategy_ids`, tambien va dentro de `results_json.backtest_params.strategy_id`,
asi que conservar la fila y limpiar la columna seguiria dejando rastro. Un
endpoint de preview (`GET .../deletion-preview`) dice cuantas son ANTES de
confirmar.

**Ficheros de disco.** El `id` de una corrida ES el `job_id` con el que se
guardo, asi que en `data/btt_job_results` hay un `.result` y un `.equity` con ese
nombre. Se borran tambien: eran 138 MB para siete trabajos en la maquina de
Sailor, y sin esto no los borra nadie.

`portfolio_lab_real_pnl` no se toca: va por fecha, es el PnL real del usuario y
no pertenece a ninguna estrategia.

Ficheros: `services/portfolio_lab_service.py` (`delete_strategy_everywhere`),
`routers/portfolio_lab.py` (endpoint), `lib/api_portfolio_lab.ts`,
`components/portfolio/BaulTab.tsx`, `StrategyShelf.tsx` (prop `danger` en
`ShelfAction`), `app/portfolio/page.tsx`.

Verificado con una DuckDB **en memoria** y un directorio de resultados temporal
—nunca contra `users.duckdb` ni contra los ficheros reales— cubriendo corrida
propia, duplicada, de cartera y ajena, sus ficheros, asignaciones, monitor, que
`portfolio_lab_real_pnl` queda intacta y que **no queda ninguna fila que mencione
el id**, ni en la columna ni dentro del JSON. En vivo se comprobo el 404 y el
flujo de confirmacion + cancelar, sin llegar a borrar.

Nota operativa: DuckDB **no encoge el fichero** al borrar filas. El espacio se
reutiliza internamente, pero `users.duckdb` no baja de tamaño solo.

### Cortacircuitos de perdida diaria en el Backtester

**Esto toca el motor y hay que acordarlo.** Bloque nuevo en `risk_management`:

    "daily_loss_limit": {"enabled": bool, "unit": "CASH"|"PCT",
                         "value": float, "on_open_positions": "LET_RUN"|"CLOSE_ALL"}

Cuando la perdida REALIZADA acumulada de una sesion cruza el umbral, la
estrategia deja de abrir riesgo nuevo ese dia: ni entradas, ni reentradas, ni
añadidos de piramide. `PCT` se mide sobre el capital de apertura del dia.
`CLOSE_ALL` ademas liquida lo que siguiera abierto, con `exit_reason` nuevo
`"Daily Limit"` (codigo 10 en el mapa del JIT).

**Apagado por defecto**: sin el bloque, o con `enabled=false`, el motor se
comporta exactamente como antes. Verificado: 103 fallidos / 307 pasados en la
suite CON y SIN los cambios — cero rotos.

**Donde vive la decision y por que.** El instante del corte (T) lo calcula
`backtest_signals.simulate_and_accumulate`, no el simulador: es el unico sitio
que ve el PnL de TODOS los tickers de la sesion. El simulador solo obedece dos
parametros nuevos (`no_new_risk_after`, `force_close_at`, en nanosegundos),
implementados en paridad en `portfolio_sim.py` y en el kernel JIT.

**La trampa del orden.** `signals_sorted` va por `(fecha, ticker)`, o sea que
dentro de un dia los tickers van ALFABETICAMENTE. Cortar siguiendo el bucle
daria un resultado plausible y falso: mataria a los tickers del final del
abecedario en vez de a los que habrian entrado mas tarde. T se calcula
ordenando los cierres por HORA REAL de salida. Hay un test dedicado
(`test_el_corte_va_por_hora_real_no_por_orden_alfabetico`) que falla si alguien
lo "simplifica".

**Por que el corte es EXACTO y no una aproximacion.** Dentro de un dia el motor
dimensiona todas las posiciones sobre el balance de apertura de la sesion
(`compounding_cash` solo se mueve al cambiar de dia) y cada ticker-dia se simula
con su propio efectivo derivado de esa misma base: no compiten entre si. Por
tanto descartar un ticker no altera el tamaño de los demas, **ni siquiera con
`size_by_sl`**, donde cada trade tiene una exposicion distinta. Eso permite
re-simular solo los tickers afectados en vez de rehacer el dia entero.

**Limitacion que hay que decir en voz alta:** el corte no puede impedir que UNA
sola operacion se pase del limite (un hueco que atraviesa el stop). Solo impide
la siguiente. El backtest devuelve `daily_limit_log` con esos casos
(`overshoot > 0`) y la UI los marca.

**Bug de fondo encontrado de paso:** `risk_management.max_drawdown_daily` existe
en el esquema y la interfaz lo pinta como "Max DD Diario: X%" en tres sitios
(`BacktestPanel`, `StrategiesTable`, `formatStrategy`), pero **ningun motor lo
lee**. Es un ajuste fantasma: quien lo configure cree tener un limite diario y
no tiene nada. NO se ha activado ni migrado, porque hacerlo cambiaria en
silencio el resultado de estrategias ya guardadas. Decision pendiente: o se
implementa, o se quita de la UI.

Ficheros: `services/portfolio_sim.py`, `services/portfolio_sim_jit.py`,
`services/sim_dispatch.py`, `services/backtest_signals.py`,
`services/backtest_service.py`, `schemas/strategy.py`,
`tests/test_daily_loss_limit.py` (nuevo, 9 casos),
`components/strategy-builder/RiskManagement.tsx`,
`components/backtester/ResultsTabs.tsx`, `lib/api_backtester.ts`,
`types/strategy.ts`.

### Drawdown: dos bugs corregidos (AFECTA A METRICAS REPORTADAS)

**1. El Max DD de la tarjeta no correspondia al grafico.** En
`_aggregate_metrics` era `min(global_max_dd, worst_day_dd)`, mezclando la caida
de la curva de equity de CIERRE (lo que dibuja `global_drawdown`) con la peor
excursion INTRADIA de una sola sesion. Los dos son a escala de cuenta —cada
ticker-dia se simula con el capital completo— pero miden cosas distintas, y el
min() daba un numero que no corresponde a ningun punto de la curva. Ademas
contaminaba **Calmar** y **DD/Return**.

Saltaba cuanto mas pequeña era la cuenta frente al riesgo por trade: con
`risk_type=FIXED` y `risk_r=1200` sobre 10.000$, cada operacion es un 12% de la
cuenta y un dia con reentradas la hunde intradia mucho mas que la curva de
cierres. Sintoma real: ventana 2019->2026 con Max DD -38% y un grafico que nunca
bajaba de ~-20%; la misma estrategia en 2024->2026 si cuadraba.

`max_drawdown_pct` pasa a ser SOLO la curva de la cuenta. El intradia se
conserva en un campo nuevo `worst_intraday_dd_pct`. **Cambia el Max DD reportado
y persistido** en corridas con cuenta pequeña — hay que coordinarlo.

**2. El grafico dibujaba mal el drawdown en $ y en R.** En `EquityCurveTab` y
`OOSDegradationTab` se calculaba `(dd% / 100) * initCash`, pero el % es respecto
al **pico movil** de la equity, no al capital inicial. Subestimaba la caida en
cuanto la cuenta componia, y el error crecia con lo que hubiera crecido —
la misma estrategia se dibujaba distinta segun la ventana. Medido: pintaba
-5.631$ donde lo correcto eran -7.624$ (1,35x). Corregido en los 8 sitios con un
helper que usa el pico movil. **El modo `%` no cambia.**

**NO es bug** (queda dicho para no volver a investigarlo): que el mismo dia
muestre distinto DD% segun la ventana. Con riesgo FIJO en dolares la misma
perdida en $ es un % distinto segun lo que haya crecido la cuenta. Con PERCENT
el % es invariante.

### Cortacircuitos de perdida diaria: no se aplicaba en el camino secuencial

El limite estaba SOLO en `simulate_and_accumulate` (caminos SLAB y PARALLEL).
`run_backtest` tiene un TERCER camino —el bucle secuencial, que llama a
`simulate()` directo— y es **el que corre por defecto** sin
`BTT_SLAB_STREAM_ENABLED` ni `BACKTEST_PARALLEL_WORKERS`. Resultado: el ajuste no
hacia nada y el usuario veia resultados identicos con y sin el.

Mismo patron que la piramidacion (§10.2). **Regla: al tocar el motor, comprobar
los TRES caminos.**

Arreglado con un buffer por dia en el bucle secuencial, activo solo si el tope
esta encendido (apagado -> camino byte-identico). Red de seguridad:
`test_run_backtest_slab_equivalence` (secuencial vs slab) sigue pasando.
Regresion nueva: `tests/test_daily_limit_sequential.py`.

Matiz por diseño: si todas las posiciones cierran a la vez (holds a EOD) no queda
nada abierto que cortar y los trades no cambian, aunque el mecanismo si corre y
la bitacora `daily_limit_log` se rellena.

### Indicadores nuevos: Acum. Dollar Volume y Dollar Volume

- **`Dollar Volume`**: volumen x cierre de la vela actual, sin acumular.
- **`Accumulated Dollar Volume`** (UI: "Acum. Dollar Volume"): suma acumulada
  desde el inicio de sesion de (volumen x cierre) de CADA vela. Es exactamente
  el `cumsum` del anterior.

Replicados en las 13 capas (enum, mapa de nombres, computo, motor legacy,
catalogo publico, registro del grafico, calculo del grafico, ConditionBuilder,
Wizard, validacion, colores, alias del asistente). Verificados por la via del
motor real (`translate_strategy`).

Suite: 103 fallidos / 321 pasados, los mismos 103 preexistentes del baseline.
Cero regresiones.

### Graficos: dos fallos de representacion (solo frontend)

**1. La curva de equity tumbaba la pagina entera.** `lightweight-charts` lanza
EXCEPCION —no un aviso— si un punto supera ±90.071.992.547.409,91 (2^53/100).
Una estrategia que compone lo alcanza legitimamente: 1,0066x por operacion sobre
3.500 operaciones son 9,7e9 veces el capital, y con 10.000$ la curva llega a 96
billones. El backtest esta bien; lo que fallaba es que al pintarlo se caia la
vista entera (probablemente tambien la causa del "al darle a Trades no cargan
los graficos": un error de render se lleva el arbol por delante).

Nuevo `lib/chartSafeValue.ts` en las 11 series de `EquityCurveTab` y
`OOSDegradationTab`: recorta al limite, convierte NaN/Infinity a 0 y **avisa en
pantalla**. No se recorta en silencio a proposito.

**2. Las marcas de piramide redondeaban las acciones a 0.** Se pintaban con
`toFixed(0)`, asi que 0,083 acciones salian como "+0" y parecia que el añadido
no se habia ejecutado. **El motor nunca truncaba**: entrada
(`risk_amount / dist`) y añadido (`add_cash / add_px`) son fraccionarios. Era
solo la etiqueta. Ahora se muestran decimales segun la magnitud.

NO se añadio la cantidad a la marca de ENTRADA: el `size` del trade es la
posicion FINAL (entrada + añadidos - parciales) y ponerlo en la flecha de
entrada seria engañoso. El motor no registra ejecucion de tipo "entry".

**OJO AL INTEGRAR:** el commit `5741202` de Alvaro (MAX DD $ desde el pico) toca
el mismo fichero `OOSDegradationTab.tsx` con el mismo proposito que el fix del
drawdown en $/R de Sailor. Revisar la resolucion del merge en esa pestaña.

### Indicadores nuevos: Acum. Dollar Volume y Dollar Volume

- **`Dollar Volume`**: volumen x cierre de la vela actual, sin acumular.
- **`Accumulated Dollar Volume`** (UI: "Acum. Dollar Volume"): suma acumulada de
  (volumen x cierre) de CADA vela. Es el `cumsum` del anterior.

Replicados en las 13 capas y verificados por la via del motor real
(`translate_strategy`). Sirven para filtrar acciones iliquidas tipo "codigo de
barras".

**Correccion (2026-08-26): esto NO es un pendiente y el aviso de abajo era
falso.** Se dijo que, al no estar en `_RAW_INDICATOR_DISPATCH`, con N2a activo
devolverian NaN en silencio. No es asi: `_extract_indicator_plan` gatea POR
ESTRATEGIA (`_cfg_native_ok` marca `has_special=True`) cualquier indicador que no
este en el dispatch, y esa estrategia entera se va al camino clasico — correcta,
solo que sin el acelerón. Es la red que se puso en `fix/n2a-parity` el
2026-07-06 justo para matar la clase de bug "0 trades en silencio".
Comprobado en runtime el 26-ago: `Dollar Volume`, `Acum. Dollar Volume`,
`Squeeze` y `Darvas Box` dan `has_special=True`; `SMA` da `False` y va nativo.
Meterlos en el dispatch seria solo una optimizacion, nunca una correccion.

## 2026-08-26

### 1. Indicador nuevo: `Squeeze` (spike de precio en una ventana de reloj)

Mide cuanto se ha movido el precio respecto al de hace X **minutos de reloj**.
Se usa como cifra, no como nivel: solo se puede enfrentar a un numero
(`indicatorValidation.ts` con lista de destinos vacia, igual que los de volumen).

Dos parametros, ambos en la propia condicion:
- `range_minutes` — la ventana, en MINUTOS (se reutiliza el campo que ya existia
  para "Range of Time").
- `squeeze_direction` — `"up"` o `"down"` (campo NUEVO de `IndicatorConfig`).

**Semantica, fijada por el usuario:** mide **punta a punta**, cierre actual
contra el cierre de hace X minutos, y el valor sale **siempre positivo en la
direccion elegida** (con "down" se devuelve la caida en positivo) para que la
condicion se lea igual arriba que abajo: `Squeeze > 10` es "se ha disparado mas
de un 10%". Consecuencia asumida: un zigzag dentro de la ventana cuenta el neto
(100 -> 110 -> 104,5 -> 114,95 son +15%), pero una caida seguida de una subida
dentro de la MISMA ventana se compensan (100 -> 90 -> 105 son +5%, no +16,7%).

**Lo que no es obvio y es el nucleo de la implementacion:** la ventana se
resuelve **por reloj con un asof hacia atras sobre los timestamps**, no contando
barras. Las velas del lago son **dispersas** — solo existe el minuto que tuvo
operaciones — asi que "5 velas atras" seria una ventana distinta en cada ticker
y en cada tramo del dia (en premarket hay huecos de decenas de minutos). La
referencia es el ultimo cierre CONOCIDO en `t - X min`: si el simbolo no cotizo
en ese hueco el precio no cambio, y el spike aparece entero en la primera vela
nueva, que es justo lo que se ve en el grafico. Vale `NaN` mientras la ventana
empieza antes de la primera vela del dia (comparar contra NaN da False: sin
referencia, no hay senal — mismo convenio que Darvas).

Replicado en las 14 capas de un indicador nuevo, incluido el dibujo en "Analisis
por trade" (panel propio, valor CON signo y linea en 0).

**Paridad backend contra grafico verificada**, que es la trampa que costo una
vuelta con Darvas: se compilo `indicators.ts` con `tsc` y se ejecuto en node
contra la salida de Python sobre las MISMAS velas — 433 velas con premarket
disperso (huecos de hasta 37 min), un spike vertical y una meseta plana para
forzar empates, ventanas de 1, 2, 5, 15 y 60 min: **0 diferencias, desvio
0,000e+00**. Si se toca una de las dos implementaciones hay que tocar la otra y
repetir esto; esta anotado en el comentario de ambas.

Va por el camino clasico (no esta en `_RAW_INDICATOR_DISPATCH`), que es correcto
por construccion — ver la correccion del apartado de Dollar Volume.

### 2. Tope de locates: `max_locates` (limita el TAMANO, no el coste)

**Esto toca el motor y hay que acordarlo.**

Campo nuevo de ejecucion, `max_locates` (0 = sin tope, comportamiento identico al
de siempre). Es el maximo de paquetes de 100 acciones que se esta dispuesto a
alquilar por ticker-dia; en **CORTO** recorta el tamano a `max_locates * 100`
acciones. **Recorta la posicion, no anula el trade.** En largo no hace nada.

El porque: la factura del dia es `ceil(max_corto_del_dia / 100) * coste`, asi que
con precios bajos el numero de locates se dispara. Con 1.000 $ de exposicion a
5 $ hacen falta 2 locates; a 0,50 $ hacen falta 20. Topar cada entrada topa la
factura del dia entero, porque el cobro se calcula sobre el maximo del dia.

Medido, con tope 5 y locate a 1 $/paquete:

| Precio | Sin tope | Con tope 5 |
|---|---|---|
| 5,00 $ | 200 acc. · 2 paquetes · 2 $ | igual (no llega al tope) |
| 0,50 $ | 2.000 acc. · 20 paquetes · **20 $** | 500 acc. (250 $) · 5 paquetes · **5 $** |

**Detalles que no son obvios:**
- El cupo cuenta **entrada MAS anadidos de piramide**, porque un anadido en corto
  sube el maximo del dia y con el la factura. Si un anadido no cabe entero se
  recorta, y queda anotado en la bitacora de ejecuciones como
  `recortado_por_locates` (igual que el tope de caja).
- Aplicado en los DOS simuladores que deben ir en paridad bit a bit
  (`portfolio_sim.py` y el kernel `portfolio_sim_jit.py`, con su envoltorio
  `sim_dispatch.py`) y enhebrado por los TRES caminos de `run_backtest` (slab,
  paralelo y secuencial). **Paridad Python contra JIT verificada: 20/20
  combinaciones de precio x tope identicas, tolerancia 0.**
- En el Laboratorio de Portfolio solo lo recibe el monitor en tiempo real, que
  es lo unico que vuelve a simular. `combine` y `scaling` trabajan sobre los
  trades YA guardados, cuyo tamano viene topado de su corrida original;
  recortarlos ahi a posteriori falsearia el PnL, porque el tope cambia el
  TAMANO, no el coste.
- La rejilla locates x slippage de Robustez barre el COSTE del locate; el cupo de
  acciones se mantiene fijo en todos los puntos.

**De paso, comprobado y confirmado** (habia duda): el locate se cobra **UNA sola
vez por ticker-dia**, no una al abrir y otra al cerrar, y un solo locate cubre
todos los shorts de ese ticker ese dia (se calcula sobre el maximo en corto del
dia, no por trade).

### 3. Optimizacion: el take profit por TIEMPO y por HORA ya se pueden barrer

En la superficie 2D/3D solo se podia optimizar el take profit por **distancia
(%)**. Los otros dos tipos que la interfaz deja configurar no llegaban:

- **Por hora** (`take_profit.type = "Hour"`, valor `"15:30"`): `float("15:30")`
  reventaba y `extract_parameters` lo **descartaba en silencio**. Ni aparecia en
  la lista.
- **Por tiempo** (`type = "Time"`, valor en minutos): si aparecia, pero con
  rangos y paso de PORCENTAJE (paso 0,5 = medios minutos), o sea inservible.
- Lo mismo en los parciales, cuyo disparo puede ser `"TIME:30"`, `"HOUR:15:30"`
  o `"EOD"`: solo se barria el numerico.

Ahora los tres se extraen con sus unidades. Como el optimizador solo sabe mover
numeros, **por tiempo se barren minutos enteros** y **por hora, minutos desde
medianoche** (09:30 = 570), y al escribir cada punto de la rejilla se devuelve la
forma ORIGINAL del valor (`_encode_tp_value`: `"15:45"`, `"HOUR:16:00"`,
`"TIME:60"`). La decision se toma releyendo la forma que tiene HOY el valor en la
definicion, asi que **un valor originalmente numerico pasa de largo** y ningun
parametro de los que ya funcionaban cambia de comportamiento.

Los parametros llevan ahora un campo `unit` (`"minutes"`, `"time_of_day"` o
`null`) para que la interfaz sepa pintarlos: con `time_of_day` el rango se elige
con dos selectores de HORA y los ejes del grafico (2D y 3D) muestran HH:MM en vez
de "570", con el globo del raton en hora via `customdata`. `"EOD"` no es
optimizable: no hay numero que mover, solo se ofrece su Capital %.

Verificado de punta a punta sobre la estrategia real del usuario (que cierra por
`Hora: 09:00`): ahora sale "Take Profit (Hora de cierre)", valor 540, barrido
07:00-11:00 a saltos de 5 min, y cada punto de la rejilla llega al motor como
`tp_time_limit='HOUR:HH:MM'` correcto.

### Regresion

Suite completa antes y despues de los tres cambios: **103 fallos / 321 pasan /
13 errores en ambos casos, 0 rotos**. Los fallos son preexistentes de este
entorno (sin acceso a GCS: 403). `tsc --noEmit` del frontend, 0 errores.

## 2026-08-26 (noche) — Auditoría del reporte de splits/gaps de Álvaro

**Origen:** Álvaro reporta desde `staging` que cada split entraba como gap falso
(NVDA 2024-06-10 = −89,89 %; 2.123 ticker-días contaminados, el 9,4 % del
universo short) y pide aplicar su fix (`19979bc`, `6c05066`, `40920cc`) más
regenerar `local_data.duckdb`. Se audita ANTES de tocar nada.

### Veredicto: el bug de splits NO es nuestro — y su parche nos ROMPERÍA

Su diagnóstico es correcto **para su lago** (`cangrejo_data`), que guarda el
`prev_close` CRUDO y ajusta al calcular. **El nuestro no**: el ETL
(`fase6_etl_edgecute.py`, paso 2/3) hornea el ajuste DENTRO de la propia
columna, desde la especificación original (§6B.2):

```sql
o.prev_oficial * COALESCE(f.split_factor, 1.0) AS prev_close
```

Los tres gaps (`gap_pct`, `gap_at_open_pct`, `pmh_gap_pct`) dividen por esa
columna ya ajustada. Verificado sobre los datos reales del lago:

| NVDA | prev_close | pm_high | pmh_gap |
|---|---|---|---|
| 2024-06-07 | 1209,98 | 1219,00 | 0,75 % |
| **2024-06-10** (split 1→10) | **120,888** | 122,19 | **1,08 %** |
| 2024-06-11 | 121,79 | 122,53 | 0,61 % |

**1,08 % exacto**, que es justo el valor que su PRD manda comprobar. El
`prev_close` del día del split es 120,888 (ya dividido entre 10), no 1209,98.

Contaminación medida en TODO nuestro lago (19,2 M filas):

- 3.343 ticker-días caen en día de split.
- **111** pasan de verdad el filtro `pmh_gap>=50` (gaps reales).
- **2.643** pasarían si el gap fuera crudo → son los fantasma que **no
  tenemos**. Peor gap falso evitado: **154.722 %** — el MISMO máximo que
  reporta él, lo que confirma que la fuente (Polygon) y su diagnóstico cuadran.

### ⚠️ Aplicar su parche nos habría corrompido datos correctos

`19979bc` reescribe `pmh_gap_pct` en los días de split como
`(pm_high − prev_close × factor) / (prev_close × factor)`. Sobre nuestra
columna, que YA lleva el factor dentro, eso es un **doble ajuste**:

| NVDA 2024-06-10 | valor |
|---|---|
| gap actual nuestro | **1,08 %** (correcto) |
| gap si aplicamos su parche | **910,77 %** (falso) |

A escala: reescribiría **3.343 ticker-días**, metería **436 candidatos falsos
nuevos** en `pmh_gap>=50` y crearía un gap falso máximo de **19.312 %**. Es
decir, nos habría inyectado exactamente el bug que él arregló.

**Regla que se lleva de aquí:** antes de adoptar un fix de datos del otro lado,
comprobar en QUÉ capa aplica cada lago el ajuste. Los dos pipelines llegan al
mismo resultado por caminos distintos y los parches no son intercambiables.

### Lo que sí se ha comprobado y NO hace falta tocar

- **`init_db.py:339`** (el `UPDATE` de arranque sobre TODA la tabla con la
  fórmula "cruda") y **`_alinear_pmh_gap_pct`**: se ejecutó su fórmula literal
  contra los 19.237.937 registros con `prev_close > 0` → **0 filas cambiarían,
  desvío máximo 0,0**. Son no-ops aquí, porque aplican la misma fórmula sobre
  una columna ya ajustada. *Apunte de eficiencia, no de corrección:* ese UPDATE
  reescribe 19,2 M filas en CADA arranque sin cambiar un solo valor.
- **Tabla `splits`**: la nuestra ya tiene las 4 columnas
  (`ticker`, `execution_date`, `split_from`, `split_to`), 28.145 filas. El
  `[WARN] split_from not found` que él tuvo no nos afecta.
- **Padding de meses (`8777d17`)**: las particiones de NUESTRO lago van CON
  cero (`month=01`), las suyas sin (`month=8`). Su bug no es nuestro; su fix
  (probar ambos paddings) sería inocuo y algo más robusto, pero no urge.

### Lo que SÍ era nuestro y se ha arreglado

**"Days" contaba ticker-días, no sesiones de calendario.**
`_aggregate_metrics` hacía `total_days = len(day_results)`, y `day_results`
trae una entrada por (fecha, ticker): una sesión con 6 candidatos sumaba 6.
Lo delata que la otra rama del MISMO `if` (cuando no hay `day_results`) ya
contaba fechas únicas — era una incoherencia, no un diseño.

Arreglado contando fechas únicas, con la **misma implementación que su
`40920cc`** (incluido el `[:10]` que normaliza por si la fecha llegara como
timestamp) para que las dos ramas converjan sin conflicto.

**Cambio de semántica a tener en cuenta:** `total_days` ("Days") y
`avg_r_per_day` pasan a ser POR SESIÓN, así que no son comparables con
resultados anteriores. `avg_return_per_day_pct` **no** cambia: se calcula
aparte, sobre un rango de fechas denso, y nunca usó ese denominador.

Verificado con caso a mano (2 sesiones × 5 ticker-días → Days=2, los 5 trades
intactos, `avg_r_per_day` 5R/2=2,5) y con fecha en formato timestamp.
Suite completa: **103 fallos / 321 pasan / 13 errores, idéntico al baseline.**

### Pendiente de decisión del usuario

- **`BACKTEST_STRICT_COMPLETENESS`**: el guardián existe en nuestro código
  (`backtest_orchestrator.py`) pero NO está en nuestro `.env`, así que corre en
  `false` (avisa en el log, no rechaza). Ponerlo a `true` hace que un backtest
  con datos incompletos falle con 503 en vez de devolver un resultado parcial.
  Es más seguro, pero **puede hacer fallar backtests que hoy salen adelante**,
  así que no se ha tocado: es decisión suya.
- **Su fix de fees (`cd455ae`, ITEM 4)** sigue solo en
  `alvaro-prereset-8b7959f`, fuera de staging. Pendiente de coordinar.

### Meses en el aire: el hueco deja de ser mudo (26/08, cierre)

Petición del usuario tras la auditoría: *"lo del tema de que se queden meses en
el aire no me gusta, lo ideal es que funcione bien y que además no dé error
503"*. O sea: que no falten datos, no que el motor grite.

Había DOS silencios distintos, y ninguno se arregla con el 503:

1. **`cargar_meses_en_duckdb` se saltaba un mes sin decir nada.** El `continue`
   del glob era mudo: si el parquet del mes no estaba, la tabla se quedaba con
   el hueco y el resumen de la actualización no lo mencionaba. Ahora ese caso
   **se registra** (`[CARGA] SIN PARQUET EN EL LAGO: <tabla> <año>-<mes>`) y va
   en el resumen como `sin_parquet`, así que la actualización diaria lo reporta.
   De paso, el glob prueba los **dos paddings** (`month=01` y `month=1`): el
   nuestro va con cero, pero DuckDB por defecto escribe sin él, y basta con
   regenerar el lago de otra forma para que el mes "deje de existir".
   Probado con un lago de mentira: resuelve con cero, sin cero, y devuelve
   "no está" cuando de verdad no está.

2. **El backtest descartaba ticker-días sin intradía y el aviso moría en el log
   del servidor.** El motor ya calculaba `data_completeness` y la metía en el
   resultado, pero **el frontend no la miraba**: un resultado parcial tenía
   exactamente la misma pinta que uno completo. Ahora, cuando no llega al 100 %,
   sale un aviso en la cabecera de resultados — *"se han operado N de M
   ticker-días candidatos (X %), faltan K sin intradía — el resultado es
   parcial"*, con la muestra de los que faltan en el tooltip.

**Decisión: NO se activa `BACKTEST_STRICT_COMPLETENESS`.** Con el aviso visible
ya no hace falta bloquear: el resultado parcial sigue siendo útil y ahora se
sabe que lo es. El interruptor sigue ahí por si algún día se quiere el rechazo
duro.

Suite: 103 fallos / 321 pasan / 13 errores, idéntico al baseline. `tsc`, 0
errores.

## Seguimiento Sailor ↔ Álvaro — quién tenía qué bien (2026-08-26)

> **Para qué es esta tabla.** Llevar la cuenta, en un solo sitio, de qué parte
> del pipeline estaba correcta en cada rama. No es un marcador: sirve para que,
> ante el próximo reporte cruzado, se sepa de entrada **en qué capa trabaja cada
> lago** antes de adoptar un parche del otro lado. Se actualiza cada vez que uno
> de los dos audite o corrija algo del otro.

| Asunto | Rama Sailor | Rama Álvaro | Nota |
|---|---|---|---|
| **Ajuste de split en el gap** | ✅ Correcto desde el origen | ❌ Roto, corregido el 26/08 (`19979bc` + lado lago) | Capas distintas: ver abajo |
| **`prev_close` en `daily_metrics`** | ✅ Ya ajustado dentro de la columna | ❌ Crudo; se ajusta al calcular | **Origen de la incompatibilidad** |
| **Tabla `splits` con 4 columnas** | ✅ Ya las tenía (28.145 filas) | ❌ Tenía 2; `[WARN] split_from not found` | Corregido por él |
| **Padding de meses en particiones** | ✅ Con cero (`month=01`), globs OK | ❌ Sin cero (`month=8`) vs globs con cero → agosto "no existía" | `8777d17`; su bug, no el nuestro |
| **"Days" cuenta sesiones** | ❌ Contaba ticker-días | ❌ Contaba ticker-días | **Bug COMPARTIDO**, corregido en los dos (`40920cc` / este commit) |
| **Junctions `cold_storage/splits` y `/tickers`** | ✅ Existen | ❌ No existían; el reload se saltaba en silencio | Corregido por él |
| **Carga incremental del DuckDB** | ⬜ No la tenemos | ✅ Suya, 30-40 min → 2,2 min | Mejora suya, interesante para nosotros |
| **Guardián de completitud** | ⬜ Existe, apagado (`false`) | ✅ Encendido (`true`) | Decisión pendiente del usuario |

### Lo que teníamos bien y él ha tenido que corregir

**El gap ajustado por split.** Nuestro ETL (`fase6_etl_edgecute.py`, paso 2/3)
hornea el ajuste DENTRO de la columna desde la especificación original (§6B.2):

```sql
o.prev_oficial * COALESCE(f.split_factor, 1.0) AS prev_close
```

Los tres gaps dividen por esa columna. Verificado sobre datos reales:
**NVDA 2024-06-10 (split 1→10) = 1,08 %** con `prev_close` = 120,888. En todo
el lago, 3.343 ticker-días caen en día de split y solo **111** pasan de verdad
`pmh_gap>=50`; con la fórmula cruda serían **2.643**, con un gap falso máximo de
**154.722 %** — el mismo número que él reporta, misma fuente de datos.

También estaba ya bien: la tabla `splits` a 4 columnas, los junctions del
`cold_storage`, y el padding de meses de las particiones.

### ⚠️ Por qué sus parches de splits NO se pueden adoptar aquí

Su `19979bc` recalcula el gap del día de split como
`(pm_high − prev_close × factor) / (prev_close × factor)`. Sobre nuestra
columna, que **ya lleva el factor**, eso es un doble ajuste:

| NVDA 2024-06-10 | valor |
|---|---|
| gap actual nuestro | **1,08 %** (correcto) |
| gap si aplicásemos su parche | **910,77 %** (falso) |

A escala reescribiría 3.343 ticker-días, metería **436 candidatos fantasma
nuevos** en `pmh_gap>=50` y crearía un gap falso máximo de **19.312 %**.

Y no es hipotético: nuestro `.env` tiene
`LOCAL_LAKE_DIR=D:/lago_backtester/parquet/edgecute` y ahí existe
`cold_storage/splits/data.parquet`, así que su código **encontraría el fichero
y aplicaría el factor** en cada carga mensual y en cada arranque.

**El problema de fondo es que el mismo código no puede servir a los dos lagos
tal cual está.** Propuesta para converger (a discutir entre los dos, NO
aplicada): que el backend **deje de recalcular `pmh_gap_pct`** y confíe en el
valor del ETL, que en ambos lagos ya es correcto. Eso serviría a los dos y de
paso quitaría el `UPDATE` de 19,2 M filas que hoy corre en cada arranque sin
cambiar un solo valor. Alternativa más conservadora: una variable de entorno
tipo `LAKE_PREV_CLOSE_YA_AJUSTADO` que apague el factor donde no haga falta,
siguiendo la regla R7 (cambios apagados por defecto).

### El bug que teníamos LOS DOS

**"Days" contaba ticker-días, no sesiones de calendario.**
`_aggregate_metrics` hacía `total_days = len(day_results)`, con una entrada por
(fecha, ticker): una sesión con 6 candidatos sumaba 6. Corregido en las dos
ramas, y **con la misma implementación** (fechas únicas + `[:10]`) para que
converjan sin conflicto.

**Cambia la semántica:** "Days" y `avg_r_per_day` pasan a ser POR SESIÓN y no
son comparables con resultados anteriores. `avg_return_per_day_pct` no cambia
(se calcula aparte sobre un rango de fechas denso).

### Estado actual de la rama Sailor

| Elemento | Estado |
|---|---|
| Gaps ajustados por split | ✅ Correctos desde el origen — **no tocar** |
| `init_db.py` / `_alinear_pmh_gap_pct` | Fórmula "cruda", pero **no-op aquí**: 0 filas cambiadas sobre 19.237.937, desvío 0,0 |
| "Days" / `avg_r_per_day` | ✅ Corregido a sesiones de calendario |
| Indicador `Squeeze` | ✅ En producción local (§2026-08-26) |
| Tope de locates (`max_locates`) | ✅ En producción local (§2026-08-26) |
| Optimización TP por tiempo/hora | ✅ Incluido el panel lateral, que mostraba minutos crudos (517) en vez de la hora (08:37) |
| `BACKTEST_STRICT_COMPLETENESS` | ⬜ Apagado **a propósito**: el aviso de completitud ya se ve en la interfaz, no hace falta el 503 |
| Meses que falten en el lago | ✅ Ya no se saltan en silencio: se registran y salen en el resumen de la actualización |
| Suite de tests | 103 fallos / 321 pasan / 13 errores — **idéntico al baseline**, 0 regresiones |
| Divergencia con `staging` | `staging` lleva 7 commits suyos encima; **su fix de splits no se puede mergear tal cual** (ver arriba) |

## Cambios de sesiones anteriores pendientes de coordinar

- **Comisiones `PERCENT`**: se cobran sobre el NOCIONAL de cada lado
  (entrada + salida), no sobre `|PnL|`. Un breakeven también paga comisión.
- **El Baúl (`/database`) y el `PortfolioBuilder` viejo están borrados** en esta
  rama.

---

## 2026-08-27 — Renombrado, horizonte, y dos campos que se caían en silencio

### 1. Renombrar estrategias desde el listado (`ae7dbb6`)

Nuevo `PATCH /api/strategies/{id}/name`: toca **solo** `name` y `updated_at`,
con el mismo `scope_clause` que el resto. Hacía falta uno propio porque el
`PUT` existente exige el `StrategyCreate` entero, y los listados del Baúl y de
Robustez no tienen la definición a mano. Lápiz inline (`RenameableName` en
`robustez/shared.tsx`) en las tres estanterías del Baúl y en el listado de
Robustez.

**Trampa:** la fila es un `role="button"` que escucha Espacio para desplegarse.
El input tiene que **cortar la propagación del keydown** o no se pueden
escribir espacios en el nombre.

### 2. Probabilidad de ruina y objetivo por horizonte (`7ee4e48`)

Bloque nuevo dentro de *Rango de escenarios posibles*. El `prob_ruin_pct` de
esa sección se mide sobre el horizonte **completo** del backtest, que no elige
el usuario; aquí el horizonte es la variable. `run_horizon` acumula el
histograma del PRIMER paso en que cada trayectoria toca cada nivel, así que no
hay que guardar la matriz `sims × días` entera.

**⚠️ NO es una prueba de fondeo.** Nació llamándose "estudio de paso de pruebas
de fondeo" y confundió: el usuario comparó su 70% con el 17% de
`FundingSection`. **Las dos cifras eran correctas.** Aquí el suelo es FIJO
(un % bajo el capital inicial) y no hay límite de pérdida diaria ni drawdown
trailing. Renombrado y advertido en la propia interfaz.

Auditoría de `FundingSection` con 5 casos de comportamiento conocido (aprueba
en la sesión 8, rotura de DD en la 7, límite diario en la 1, mínimos, suma de
desenlaces = 100): **correcto, no había fallo ahí**.

### 3. FIX: la cuenta base del fondeo no reescalaba en aditivo (`7ee4e48`)

En modo **aditivo** los valores son PnL en **dólares** de la cuenta con la que
se corrió el backtest. Cambiar "cuenta base" no los tocaba: solo encogía los
umbrales, que son % de la cuenta. Se simulaba una cuenta de 25.000 moviéndose
como si operase 50.000.

| Cuenta base | Antes | Ahora |
|---|---|---|
| 25.000 $ | 0,7 % | 3,2 % |
| 50.000 $ | 3,2 % | 3,2 % |
| 100.000 $ | 24,1 % | 3,2 % |

Invariante, como debe ser con reglas en porcentaje. En compuesto no se toca
nada (los R-múltiplos son proporciones): verificado idéntico bit a bit. Solo
afecta a backtests de riesgo **FIJO**, que son los que llegan en aditivo.

### 4. FIX: `size_by_sl` y `pyramiding` se perdían (`2282509`)

Los dos son el patrón de las **TRES CAPAS**, cada uno cayéndose en una distinta:

- **`size_by_sl`** ("Cálculo de Shares por Distancia al SL") no estaba
  declarado en el esquema `RiskManagement`. Pydantic va con `extra="ignore"`:
  el frontend lo mandaba bien, el esquema lo tiraba **sin error, sin log y sin
  422**, y la estrategia salía siempre con la opción desactivada. **Capa 2.**
- **`pyramiding`** es clave de **primer nivel**, y de los seis sitios de
  `page.tsx` que rearman el borrador **solo dos** la conservaban. Por eso una
  estrategia con pirámide perdía su configuración al reabrir el panel.
  **Capa 1.** `risk_management` no sufría esto porque los seis bloques acaban
  en `...(def.risk_management || {})`.

**⬜ Pendiente:** puede haber más campos igual. Falta una pasada comparando lo
que emite el constructor contra lo que declara el esquema, en vez de irlos
descubriendo de uno en uno.

### 5. Glob de la caché: adoptado el ítem 2 de Álvaro (`27e8076`)

`anadir_dias_al_cache` se quedó con `month={m:02d}` fijo cuando se arregló el
del cargador principal (`919ea1c`). Con una partición `month=8` el glob no
resolvía, el `continue` era mudo y la caché **se saltaba el mes entero sin
dejar rastro**. Espejo exacto de `919ea1c`, más el log que allí sí se puso.

Implementado aquí en vez de aceptar su cherry-pick: cinco líneas, patrón ya
conocido, y así no se arrastra nada más de su rama. **Decirle que no hace
falta parche.**

Su **ítem 1** (ajuste de split de `pmh_gap_pct`) **NO se adopta**, de acuerdo
con su propia recomendación: nuestro `prev_close` ya viene ajustado del ETL y
doblaría el ajuste. **Ítems 3 y 4** ya convergidos.

### Suite

**103 fallos / 321 pasan — idéntico al baseline, 0 regresiones.** Los 15
errores frente a los 13 anotados antes son 2 fallos de **recolección
preexistentes**: `test_backtest_engine.py` y `test_backtest_integration.py`
importan `filter_market_data_by_interval_and_dates`, que desapareció en el
refactor `2e383a5`. Ningún commit de esta sesión toca `routers/backtest.py`.
Se lanza con `--continue-on-collection-errors`, y el intérprete es
`backend/.venv/Scripts/python.exe` (el Python del sistema no tiene pytest).

### Fuera del repo: avisos del screener a Telegram

Userscript de Tampermonkey que lee la tabla de `app.edgecute.com/screener` y
avisa por Telegram cuando entra un ticker nuevo con `Change % > 50`, o cuando
uno que ya estaba lo cruza. **Vive fuera del repo**, dentro de Tampermonkey.

Tres cosas que costaron la tarde y conviene no repetir:

1. **Chrome (MV3) tiene apagado por defecto un permiso por extensión llamado
   «Permitir scripts de usuario»** (`chrome://extensions` → Detalles). Sin él
   Tampermonkey lista los scripts y **los da por activos, pero no ejecuta
   ninguno**, en silencio absoluto. **Comprobar esto ANTES que el código.**
2. Las cabeceras de la tabla llevan `text-transform: uppercase` e `innerText`
   devuelve el texto **ya transformado**: llegan como `TICKER`, `PRICE`.
3. `fmtPct` antepone `+` a los positivos y la celda de `Change %` puede traer
   una marca `▲`/`▼`. Un lector que exigiera que la celda entera fuese un
   número devolvía `null` **siempre**.

El screener no hace polling: va por **WebSocket** (`/screener/live`, top-50
1×/s) y la app ya tiene alarmas propias (`matchesRules`, entrantes y cruces con
cooldown). Ambas vías se descartaron a petición del usuario, que quería algo
independiente que solo mirase la pantalla.

---

## 2026-08-27 (tarde) — Fills fantasma del SL estructural + arreglos de la sesión

### 1. ⚠️ ADOPTADO de Álvaro: el SL estructural invalidado (`eb550d0`, `a2282b4`)

Cherry-pick limpio de `dfa6e51` y `c79993d` de `alvaro-rama-desarrollo`. Base
común `919ea1c` y **cero solape**: ninguno de sus 14 ficheros lo habíamos
tocado nosotros.

**El bug (lo teníamos igual).** Un stop de Market Structure que al entrar
quedaba en el lado ganador —un corto con el PMH ya rebasado— dejaba el SL por
DEBAJO de la entrada. En `portfolio_sim.py` el corto comprueba
`price_for_sl >= trade_sl_price` y rellena a `min(SL, high)`: la condición se
cumplía en la **propia vela de entrada** y vendía a un precio que la vela nunca
tocó. Beneficio garantizado, sin riesgo, contado como salida "SL".

En su run de RTH 2.3: **el 43 % de los trades eran fills fantasma y aportaban
el 87 % del PnL** (PF 3,78 → 1,36 al arreglarlo).

**🚨 CUALQUIER RUN GUARDADO ANTES DEL 2026-08-27 CON SL DE MARKET STRUCTURE
ESTÁ INFLADO Y NO ES COMPARABLE.** Mismo aviso de semántica que el fix de
splits. No comparar curvas nuevas contra runs viejos.

**La semántica nueva:** guard siempre activo (no configurable) que valida el
lado del nivel al precio REAL de entrada; si está invalidado, **no se entra**.
Más dos campos opcionales en `hard_stop`: `fallback_value` (rescata
REENTRADAS con otro nivel, típicamente "Previous Max", aplicando el mismo
offset) y `fallback_first_entry` (extiende el rescate a la primera entrada).
Si el respaldo también está invalidado, no se entra. Los stops porcentuales no
se tocan.

**Verificado por nuestra parte, no solo por sus tests:**
- Sus 37 tests: 37/37 ✓.
- Suite completa: **103 fallos / 354 pasan / 15 errores** contra el baseline de
  103/321/15 → mismos fallos, mismos errores, **+33 tests nuevos**. 0 regresiones.
- Reproducción propia del escenario NITO: corto a 3,20 con PMH en 2,48 → **0
  trades** sin respaldo; con `Previous Max` (3,60) + `fallback_first_entry` →
  1 trade con SL en 3,60, por encima de la entrada. ✓
- Paridad Python↔JIT confirmada por lectura: `_sl_side_valid` en
  `portfolio_sim.py` y su espejo con `hs_fallback_code` en
  `portfolio_sim_jit.py`, con tabla de códigos compartida en `sim_dispatch.py`.
- Los campos viajan por los DOS caminos: `backtest_service.py` (secuencial) y
  `backtest_signals.py` (slab/paralelo).

**Pendiente de producto:** re-optimizar con el motor honesto. Cada trade
rescatado por el respaldo puede perder toda la distancia hasta ese último alto.

### 2. Walk Forward: las horas ya no se piden ni se pintan en minutos (`6d5ea81`, `93dd847`)

El fix de `1a1c3b4` tocó solo `OptimizationSurfaceTab`; Walk Forward se quedó
fuera. Y dentro de WFO hubo que hacerlo **dos veces**: primero las casillas de
entrada, y luego —porque no barrí todos los sitios de golpe— los ejes de la
matriz 3D y del mapa de calor, sus globos de ratón (vía `customdata`, porque
`%{x}` lee el valor crudo), la columna "mejor valor" por ventana, y el valor
recomendado y la columna de valores del análisis por parámetro.

La causa raíz: el backend YA mandaba `unit`, pero `OptimizableParam` de
`api_robustez.ts` no lo declaraba. **Mismo patrón de campo mudo que
`size_by_sl`, esta vez en el tipo del cliente.**

### 3. Monte Carlo: el histograma tumbaba la simulación (`eab99cb`)

"Too many bins for data range". `_safe_hist` tenía dos agujeros, **anteriores a
esta sesión**: el guard miraba el rango ABSOLUTO cuando numpy falla por el
ancho de bin relativo a la magnitud, y con `inf`/`nan` el propio plan B
reventaba al calcular `lo - pad` sobre un valor no finito. Lo dispara el
interés compuesto cuando una trayectoria desborda la equity. Verificado con 10
formas de entrada.

### 4. La barra de desenlaces del fondeo decía "días" sin decirlo (`c9e7031`)

"rompe límite diario 88 %" se leía como "el 88 % de mis días", que es falso
(son el 16 %). El 88 % son las **corridas** que acaban rotas, y basta UN día
malo para tumbar una. Costó media conversación deshacer el malentendido.
Ahora la barra dice "De cada 100 **intentos** de fondeo (no de días)".

**Dato para tener a mano:** con la corrida real del usuario (275 sesiones,
cuenta 50k, 1.500 $/trade), 44 sesiones cierran perdiendo más de 1.000 $. Al
partir su calendario REAL en tramos seguidos de 20 sesiones, **las 256 ventanas
posibles contienen al menos un día que rompe** el límite. La simulación no
exagera: se queda corta.

### 5. Descartado a petición del usuario

Separar "cuenta base" y "tamaño de posición" en el panel de fondeo. Queda como
está: la casilla de cuenta **escala el tamaño con ella**, así que cambiarla no
mueve la probabilidad. Es correcto pero contraintuitivo — si vuelve a
preguntar, es esto.

---

## 📣 Para Álvaro (y su IA) — respuesta de Sailor, 2026-08-27

Escrito para que lo leáis directamente. Todo lo de abajo está ya en `staging`
(commit `9ef1de9`), así que si partís de ahí lo tenéis.

### 1. Vuestro fix del SL estructural: ADOPTADO y verificado ✅

Cherry-pick de `dfa6e51` y `c79993d` sobre `sailor-rama-desarrollo`. Base común
`919ea1c`, **cero conflictos**: ninguno de vuestros 14 ficheros lo habíamos
tocado nosotros. Están en staging como `eb550d0` y `a2282b4`.

**Confirmamos que teníamos el mismo bug**, verificado leyendo nuestro código
antes de aplicar nada: `portfolio_sim.py` calculaba el SL estructural sin
validar el lado, y el corto rellenaba con `min(SL, high)` cumpliéndose la
condición en la propia vela de entrada.

No nos fiamos solo de vuestros tests — esto es lo que medimos por nuestra parte:

| Comprobación | Resultado |
|---|---|
| `test_hs_invalid_sl_guard.py` + `test_sim_jit_equivalence.py` | **37/37** ✓ |
| Suite completa (con `--continue-on-collection-errors`) | **103F / 354P / 15E** |
| Baseline previo nuestro | 103F / **321P** / 15E |
| Veredicto | 0 regresiones, **+33 tests** |
| Reproducción propia (escenario NITO) | corto a 3,20 con PMH 2,48 → **0 trades**; con `Previous Max` (3,60) + `fallback_first_entry` → 1 trade, SL 3,60 **por encima** de la entrada ✓ |
| Paridad Python↔JIT | Confirmada por lectura: `_sl_side_valid` ↔ `hs_fallback_code`, tabla compartida en `sim_dispatch.py` |
| Los campos llegan al simulador | Sí, por los **dos** caminos: `backtest_service` (secuencial) y `backtest_signals` (slab/paralelo) |

Los 2 errores de recolección extra respecto a vuestra cuenta son
**preexistentes y nuestros**: `test_backtest_engine.py` y
`test_backtest_integration.py` importan
`filter_market_data_by_interval_and_dates`, que desapareció en el refactor
`2e383a5`. No tienen que ver con vuestro cambio.

Aviso interno propagado: cualquier corrida guardada nuestra anterior al 27/08
con SL de Market Structure queda marcada como inflada y no comparable.

### 2. Vuestro informe de divergencias: ítem 2 — YA RESUELTO, no mandéis parche ✅

El glob de `anadir_dias_al_cache` con padding fijo lo confirmamos y **lo
arreglamos por nuestra cuenta** en `27e8076`, antes de que llegara vuestro
cherry-pick. Mismo enfoque que `919ea1c` (prueba `{m:02d}` y `str(m)`), más el
log que allí sí pusimos y aquí faltaba: un mes sin parquet ya no se salta mudo.

Lo implementamos nosotros en vez de aceptar el cherry-pick por ser cinco líneas
de un patrón ya conocido, y así no arrastrar nada más de la rama. **No hace
falta que preparéis el parche.**

### 3. Ítem 1 (split de `pmh_gap_pct`): NO adoptado — coincidimos con vosotros ✅

De acuerdo con vuestra propia recomendación. Nuestro `prev_close` ya viene
ajustado del ETL y aplicarlo aquí doblaría el ajuste (el NVDA 2024-06-10 →
910,77 % falso). Queda cerrado formalmente por ambas partes.

### 4. Ítems 3 y 4: convergidos, sin acción ✅

"Days por sesión" y el glob del cargador principal ya estaban en staging con
nuestros SHAs (`7415eed` y `919ea1c`).

### 5. Lo que os llega nuevo de nuestra parte en este push

Nada de esto toca el motor de simulación, así que no debería chocaros:

- **Renombrar estrategias** desde el Baúl y desde Robustez (`PATCH
  /api/strategies/{id}/name`, solo `name` + `updated_at`).
- **Dos campos que se caían mudos** (`2282509`): `size_by_sl` no estaba
  declarado en el esquema `RiskManagement` y pydantic lo tiraba con
  `extra="ignore"`; `pyramiding` se perdía en 4 de los 6 sitios de `page.tsx`
  que rearman el borrador. **Ojo si tenéis estrategias guardadas con "Cálculo
  de Shares por Distancia al SL": hasta hoy esa opción no se persistía.**
- **Monte Carlo**: `_safe_hist` tumbaba la simulación con "Too many bins for
  data range" cuando el compuesto desbordaba la equity a `inf` (`eab99cb`).
- **Walk Forward**: los parámetros de hora se pedían y se pintaban en minutos
  crudos (510 en vez de 08:30), tanto en las casillas como en la matriz 3D,
  el mapa de calor y las tablas (`6d5ea81`, `93dd847`).
- **Robustez**: bloque nuevo de probabilidad de ruina/objetivo **por
  horizonte**, y fix del reescalado de la cuenta base en la prueba de fondeo,
  que en modo aditivo encogía los umbrales pero no el tamaño de las apuestas
  (`7ee4e48`).

### 6. Lo que abre vuestro cambio, y que compartimos

Coincidimos con vuestra nota final: **hay que re-optimizar con el motor
honesto**. Cada trade rescatado por el respaldo puede perder toda la distancia
hasta ese último alto, así que los parámetros buenos de antes no tienen por qué
seguir siéndolo. Nosotros vamos a relanzar nuestras estrategias con SL
estructural antes de sacar ninguna conclusión.

---

## 2026-08-28 — Resumen de estrategia guardada, dos fixes de Álvaro adoptados, y tres auditorías medidas

Sesión mixta: un arreglo propio, la adopción de dos parches del socio, y tres
diagnósticos con números que NO tocan código. Lo que no se arregló queda
listado al final con su porqué.

### 1. El resumen de una estrategia guardada anunciaba parciales que no existían

**Síntoma del usuario:** en el desplegable de una estrategia guardada (Robustez
y Portfolio) el take profit salía bien, pero debajo aparecía «TP parciales» con
la configuración de una versión ANTERIOR de esa misma estrategia, ya
sobrescrita. Sospechaba que el guardado no sobrescribía bien.

**El guardado sobrescribe bien.** En `users.duckdb` hay una sola fila para esa
estrategia, sin duplicados, y `PUT /api/strategies/{id}` reescribe la
definición entera, no hace merge. Comprobado con `updated_at`.

Lo que sí pasa es que el JSON **arrastra** `partial_take_profits` de la versión
vieja: el builder conserva el array en memoria al volver de «Parcial» a
«Completo» (para que no pierdas la configuración si cambias de idea) y lo manda
tal cual. **El motor lo ignora** — `strategy_engine.py:820` y `:1379` solo lo
leen si `tp_mode == "Partial"`, y `optimization_service.py:485` tampoco expone
esos parámetros fuera de ese modo. Los backtests eran correctos.

El fallo estaba solo en el texto: `lib/robustez/formatStrategy.ts` pintaba la
línea mirando únicamente si el array existía. Ahora usa **la misma puerta que
el motor** (`use_take_profit is not False`, luego `tp_mode == "Partial"`), y
además muestra «desactivado» cuando no hay TP, como ya hacía el hard stop.

De paso, en esa misma línea, el disparo de un parcial por hora se pintaba como
`30% a +HOUR:09:00%`. Ahora: `30% a las 09:00`. Los cuatro formatos que
reconoce `_parse_partial_tps` (%, `TIME:`, `HOUR:`, `EOD`) se traducen.

Un solo fichero, usado por `robustez/StrategyPicker.tsx` y
`portfolio/StrategyShelf.tsx`. `tsc` limpio; verificado ejecutando `riskLines`
contra la definición literal guardada en la base de datos.

**Decisión consciente: NO se limpia el array al guardar.** Borrarlo en modo
Completo haría perder la configuración de parciales al recargar la estrategia.
Queda como está a propósito.

### 2. Adoptados los dos fixes de Álvaro (`2aefb06` y `764277e`) — teníamos los dos

Cherry-pick limpio de los dos, sin modificarlos.

- **Darvas Box en el enum del schema.** El indicador estaba en el motor
  (`indicators.py`, canónico «Darvas Box» + alias) y en el frontend
  (`IndicatorType.DARVAS_BOX`), pero **no** en `schemas/strategy.py`. El
  backtest corría y el guardado devolvía 422. Es exactamente el patrón de «un
  campo se cae en silencio si no está declarado en las tres capas».
  Verificado: una estrategia con condición Darvas ya valida, y un indicador
  inventado sigue rebotando (contraprueba).
- **«Guardar como nueva estrategia»** en el modal de sobrescritura.

`tsc` limpio tras los dos.

### 3. Auditoría: por qué un backtest tardó ~13 minutos

Medido en vivo con `py-spy` sobre el proceso del backend (tres volcados de pila)
y con las marcas de tiempo de la caché.

| Tramo | Coste | Evitable |
|---|---|---|
| Datos en frío (dataset nuevo → 25 meses de parquet crudo) | ~7 min | Sí: relanzar el mismo dataset |
| Piramidación → motor Python en las dos mitades | ~3 min | Sí: quitarla si la prueba no la necesita |
| Sin paralelismo | multiplica todo | No, hoy |

- **Datos en frío.** El dataset se creó a las 13:18 → universo nuevo → tickers
  que no estaban en la caché por ticker-mes (`D:\tmp\btt_intraday_cache`; ojo:
  `CACHE_DIR` está definido DOS veces en `gcs_cache.py`, líneas 37 y 799, y
  gana la segunda). Escribió ~5.700 ficheros entre las 13:22 y las 13:29,
  leyendo a ~100 MB/s. La barra de progreso no se mueve durante ese tramo
  porque solo cuenta pares ya simulados.
- **Piramidación.** Confirmado por pila:
  `_evaluate_pyramid_levels → _resample_if_needed → pandas resample.agg`.
  Dos puertas ya documentadas en el código la echan del camino rápido:
  `strategy_engine.py:414` (fuerza `has_special=True` → nada de path nativo) y
  `sim_dispatch.py:44` (con niveles de pirámide siempre `portfolio_sim`, nunca
  el kernel Numba, aunque `BACKTEST_NUMBA_SIM=1`). Es el P3 conocido.
- **Un núcleo de veinte — esto NO estaba apuntado.** `backtest_signals.py:765`
  (y las otras dos vías del fichero) exigen `fork` / `forkserver`. En esta
  máquina `multiprocessing.get_all_start_methods()` devuelve **`['spawn']`**,
  así que **ninguna** vía paralela se activa: cae siempre al bucle secuencial
  en línea. Además hay un segundo cerrojo antes: `BACKTEST_PARALLEL_WORKERS`
  vale 1 por defecto (opt-in explícito, por riesgo de OOM en BROAD).
  Ritmo medido del bucle: **39,6 pares/s** (de 4.960 a 6.743 en 45 s).

  Matiz honesto: el propio código deja escrito que con spawn «a 1.200 pares el
  spawn cuesta más que el trabajo» — pero eso se midió con el camino rápido,
  donde cada par es baratísimo. Con piramidación el coste por par es otro orden
  de magnitud y la cuenta puede darse la vuelta. **Sin medir. No tocar el motor
  hasta medirlo.**

### 4. Auditoría del slippage: la unidad es correcta y el coste cuadra al milímetro

El usuario sospechaba que el slippage degradaba demasiado. **No hay bug.**

**Unidad.** `BacktestPanel.tsx:696` y `:792` envían `slippage / 100`; el motor
aplica `slip = precio × slippage` (`portfolio_sim_jit.py:650` y `:592`).
Escribir 1 en la casilla «Slippage (%)» = 1% peor en la entrada y 1% peor en
cada salida. Es lo que la etiqueta promete.

**Prueba aritmética** sobre tres runs de la misma estrategia con las **mismas
1.883 operaciones** (solo cambia el slippage):

| Slippage | R media | PF |
|---|---|---|
| 0,05 % | +0,243 | 1,701 |
| 0,50 % | +0,195 | 1,546 |
| 1,00 % | +0,145 | 1,391 |

Coste calculado a mano operación a operación: 0,005 / 0,050 / 0,097 R. Caídas
reales de R media: 0,048 y 0,050. **Cuadra.**

**La fórmula que lo explica:** `coste en R = 2 × slippage ÷ distancia al stop`.
Con stops al ~23% (Previous Max + 10%), un 1% de slippage cuesta ~0,09 R contra
una ventaja bruta de +0,24 R: se lleva el 40%. Con un stop al 2%, el mismo 1%
costaría **1 R por operación**. La sensibilidad no es al slippage, es al
cociente. Y con piramidación y TP parciales **se paga en cada añadido y en cada
salida parcial**, no dos veces por operación.

**Trampa metodológica detectada en los runs del usuario:** los backtests «sin
slippage» se corrieron con `risk_r=1` y los «con slippage» con `risk_r=300`.
Además, con `risk_r=1` la columna `r_multiple` deja de ser R y pasa a ser
dólares (`r_multiple = pnl / risk_r`). Para comparar costes hay que mover una
sola variable y mirar R media o PF, nunca el % de retorno (se mueve con el
capital inicial: dos runs idénticos daban +681% y +136% simplemente por 10.000$
contra 50.000$ — los mismos 68.154$ ganados).

### 5. Aclarado (sin cambio): la guarda del SL estructural consume el flanco de señal

Sobre el bloque «Si el nivel ya está rebasado al entrar» de `eb550d0`.

`Previous Max` es `cummax(high).shift(1)` — el máximo del día hasta la vela
anterior, no un pivote. Con offset +10%, en corto el nivel se considera
rebasado solo si el precio de entrada supera `Previous Max × 1,10`.

Lo que conviene tener claro: al saltarse la entrada, el código hace
`prev_signal = current_signal; continue`, y las entradas disparan por flanco
(`is_signal_trigger = current_signal and not prev_signal`). Es decir, **el
disparo se consume**: aunque en la vela siguiente el Previous Max ya se haya
puesto al día y el stop fuera válido, no entra. Hace falta que la condición se
apague y se vuelva a encender. En una estrategia de gaps, donde la buena del
día puede ser una sola señal, eso puede costar el día entero.

La entrada saltada **no** gasta reentrada (`total_trades` no sube).

Pendiente ofrecido y no ejecutado: medir cuántas señales se pierden hoy
(correr la misma estrategia con y sin respaldo y comparar el nº de
operaciones). Las entradas saltadas no dejan rastro; solo se ven por ausencia.

### 6. Encontrado y NO arreglado (a la espera de decisión)

- **Trampa de ×100 latente.** En `app/backtester/page.tsx:500` y `:545` el
  valor por defecto es `slippage: p?.slippage ?? 0.01` — 0,01 en unidades del
  MOTOR, o sea 1%, mientras que el valor por defecto del panel es 0,01 **en la
  casilla**, o sea 0,01%. Cien veces. Lo mismo con `fees ?? 0.01`. **No
  dispara hoy**: `p` es `panelParamsRef.current`, que el panel rellena al
  montarse. Es una trampa esperando un cambio en el orden de carga.
- **Trabajo muerto en cada mes del stream.** `db/gcs_cache.py:1298` hace
  `n_groups = len(grouped)` y **no usa** `n_groups` en ninguna parte. Ese
  `len()` sobre un groupby materializa el índice de todos los grupos del mes.
  Se paga en los 25 meses para nada.

---

## 2026-08-29 — Dos adopciones de Álvaro, la marca de entrada del gráfico, y tres auditorías con datos

Sesión de mañana. Tres cambios de código y cuatro diagnósticos medidos. Como
siempre, lo que NO se tocó va al final con su porqué.

### 1. Adoptados dos commits de Álvaro (`e04d95e` y `a08f01e`)

Cherry-pick limpio, sin modificarlos, con su autoría.

- **`e04d95e` — indicador «Current Gap (%)»**. El gap VIVO: a cuánto está el
  precio de la vela respecto al cierre de ayer, actualizándose barra a barra.
  A diferencia de «PM High Gap (%)», que se congela al acabar el premarket y
  no se entera si el precio se desploma. Trae 4 pruebas propias.
- **`a08f01e` — watchdog del backend local** (`run_backend_forever.bat`). Si
  8010 está libre arranca uvicorn y lo revive a los 30 s si muere; si está
  ocupado espera 60 s sin duplicar.
  ⚠️ **Hoy no hace nada**: es un fichero del repo, y el `.vbs` que Álvaro usa
  para registrarlo como tarea programada es local suyo. Si algún día se activa
  en la máquina de Jaume, **chocará con el lanzador del escritorio**: el
  «Forzado de apagado» mataría el backend y el watchdog lo resucitaría 30 s
  después. Hay que ajustar uno de los dos ANTES de activarlo.

**Verificación:** el cambio de Current Gap es puramente aditivo (un valor nuevo
en el enum, una función nueva y una entrada en el dispatch); no toca ni una
línea de ningún camino existente. 4 pruebas nuevas + 117 de paridad del motor +
`tsc` limpio. El arreglo de Darvas del 28-ago sobrevive intacto en el mismo
fichero.

### 2. Borrado `test_backtest_engine.py` — roto desde febrero

No se podía ni recolectar: importaba `Condition` y `Operator` de
`app.schemas.strategy`, dos nombres que ya no existen. **Rompía la recolección
de pytest entera**, así que se llevaba por delante cualquier tanda que lo
incluyera.

Sus 10 pruebas apuntan a `app.backtester.engine.BacktestEngine`, que el propio
código marca como **MUERTO** en dos sitios (`routers/portfolio.py:15` y
`services/portfolio_service.py:7`). Último commit que lo tocó: `d969d4f`,
2026-02-08. Siete meses sin ejecutarse: no se pierde cobertura porque no había.

Tras borrarlo la suite recolecta **474 pruebas**. Queda **otro igual**:
`test_backtest_integration.py` (6 pruebas, 2026-02-22, mismo motor muerto y una
función que ya no existe en ningún sitio). Pendiente de decisión.

### 3. La marca de ENTRADA del gráfico mostraba el tamaño del primer parcial

**Salió de una pregunta del usuario** («¿por qué piramida dos veces si dije
una?»). La respuesta a eso era que no piramidaba dos veces —eran **dos trades**,
porque una reentrada rearma la pirámide entera— pero al cuadrar las cantidades
apareció esto.

`_build_executions` tomaba `run[0]["size"]` como tamaño de la entrada. `run[0]`
es el PRIMER LEG del trade, y con TP parciales ese leg es la cantidad del primer
parcial, no la posición abierta.

Medido (corrida con parciales 60/40): **CNEY 2024-09-11 abrió 1.666,67 acciones**
(riesgo 300 $ ÷ 0,18 $ de distancia al stop) **y la marca decía 1.000** — justo
el 60 % del primer parcial. Sumando las marcas parecía que **el 86 % de los
trades cerraban más acciones de las que abrían**.

**NO había error de dinero.** La función es informativa y no alimenta ninguna
métrica. Comprobado reconstruyendo el PnL de CNEY a mano: 1.000 acc a 0,999
(+111 $) + 666,67 acc a 1,29 (−120 $) − 0,11 $ de comisiones = **−9,11 $**,
idéntico al `pnl` guardado. La posición real siempre fue la correcta.

Arreglado con la identidad del propio motor (`sum(legs) = inicial + añadidos`,
las reducciones de pirámide se cancelan solas porque también emiten leg).
Un trade de un solo leg da el mismo número que antes → las estrategias sin
parciales ni pirámide no cambian nada. 121 pruebas verdes.

> **Regla para quien venga:** las marcas del gráfico **no son fuente de verdad
> para cantidades**. El `pnl` del trade sí. Ante una discrepancia, reconstruir
> el PnL con precios y tamaños antes de gritar «bug del motor».

### 4. Medido: en premarket, «Previous Max» NUNCA está por encima del PMH

Sobre **3.246 ticker-días y 72.449 velas de premarket**:

```
Previous Max  ==  PMH  →  66.919 velas  (92,4 %)
Previous Max  <   PMH  →   5.530 velas  ( 7,6 %)
Previous Max  >   PMH  →        0 velas  ( NUNCA )
```

No es casualidad de la muestra, es aritmética: el PMH es el máximo acumulado
**incluyendo la vela actual** y Previous Max es el mismo máximo **una vela por
detrás** (`cummax(high).shift(1)`). Persigue al PMH sin adelantarlo nunca. Los
datos empiezan a las 04:00, que es justo cuando arranca el premarket, así que
durante el PM los dos recorren las mismas barras.

**Consecuencia práctica, y es importante:** en una estrategia que solo entra en
premarket, poner **Previous Max como respaldo del PMH no puede rescatar
absolutamente nada**. En un corto el stop debe quedar POR ENCIMA de la entrada;
si el PMH no llega, Previous Max llega menos. El desplegable «si el nivel ya
está rebasado al entrar» y su casilla están **inertes** en ese tipo de
estrategia, marcados o sin marcar.

Y lo mismo con HOD de respaldo: durante el premarket, el máximo del día **es**
el PMH.

Medido también al revés, por si la intuición decía otra cosa: con Previous Max
como stop principal se pierden **más** entradas, no menos (0,141 % de las velas
contra 0,065 % con PMH; 27 casos que el PMH salva y Previous Max no, y **cero**
al revés).

**Dónde SÍ sirve la función:** en estrategias que entran en RTH, donde el PMH se
congela a las 09:30 y el máximo del día sigue subiendo — ahí los dos niveles se
separan de verdad y el respaldo rescata.

### 5. Revisado el Walk Forward: barre bien, pero tiene tres huecos

El usuario sospechaba que «solo le devuelve el valor que ya tiene». **El barrido
funciona**: construye la rejilla entera, corre un backtest real por combinación
y ventana, y se queda con el máximo. Comprobada la sospecha más obvia —que la
caché de señales congelara los parámetros de riesgo entre combinaciones— y **no
pasa**: la caché guarda solo entradas/salidas y **vuelve a leer la gestión de
riesgo en cada combinación**.

Pero hay tres huecos reales:

1. **Con un stop de estructura no se puede optimizar NADA del stop.** El
   generador de parámetros hace `float(hs.get("value"))` y, como el valor es
   texto (`"Previous Max"`), descarta el hard stop entero. **Y el `offset_pct`
   —el margen del 10 %, que es la perilla más interesante— no se ofrece
   tampoco.** Nadie lo conectó.
2. **El eje de tiempo no se redondea a minutos enteros.** El optimizador normal
   sí lo hace (`is_int` para `minutes`/`time_of_day`); `robustness_wfo._axis`
   no. Con un rango estrecho y muchos pasos, varias combinaciones se escriben
   como el mismo `HH:MM` → se pagan backtests para probar lo mismo.
3. **`_param_analysis` solo analiza el PRIMER parámetro** (`best_params[0]`).
   Si se barren dos, el segundo se optimiza pero no sale recomendación.

### 6. El lanzador solo mira el puerto 3000

Reportado como «la app no arranca». **No estaba rota**: `next dev` encontró la
3000 ocupada por un resto de la sesión anterior, se mudó sola a la **3001** y
siguió funcionando. El lanzador (`D:\lanzador_btt\arrancar_btt.ps1`) tiene
`$PuertoWeb = 3000` fijo, esperó 180 s en una puerta por la que no iba a llegar
nadie y dio por muerto un frontend vivo. Su propio log de apagado lo delataba:
*"puerto 3000: ya estaba libre"*.

Dos puntos flojos, los dos de una línea: **solo mira la 3000** (no detecta la
puerta real) y **no comprueba que quede libre al apagar** (de ahí el resto
arrastrado). El script vive fuera del repo, a propósito.

### 7. Encontrado y NO arreglado

- `test_backtest_integration.py`, roto igual que su hermano (§2).
- Los tres huecos del Walk Forward (§5). Los dos primeros salen de la misma
  carencia de fondo: **`hard_stop.value` guarda texto en vez de un nivel con
  parámetros**, y de ahí que ni se pueda optimizar ni se pueda elegir la sesión
  de referencia. Merecen un PRD propio, no parches.
- **El nivel del stop no se puede medir por sesión.** Los niveles (`hod`,
  `prev_high`…) se calculan sobre el día ENTERO desde las 04:00 y luego solo se
  recortan a la sesión elegida; nunca se recalculan. En una estrategia de RTH,
  «Previous Max» ya lleva dentro todo el máximo del premarket. La maquinaria
  existe (`RTH High`/`RTH Low`/`High/Low from x time` funcionan en la lógica de
  entrada) pero **no está enchufada al stop**. Conectarlo obliga a ampliar la
  firma del simulador, que va en paridad bit a bit Python↔JIT: no es un parche.
- Los dos puntos flojos del lanzador (§6).

---

## 📣 2026-08-29 — REINICIO DE `staging`: se ha igualado a `sailor-rama-desarrollo`

**Decisión de Jaume, tomada con la lista de consecuencias delante.** Es la
segunda vez que se hace: la primera fue el 2026-08-26 (ver la cabecera de este
documento). `staging` pasa a ser una **copia exacta** de
`sailor-rama-desarrollo`, y este documento es el de Sailor.

**Álvaro: nada de lo tuyo se ha perdido, pero sí se ha quitado de `staging`.**
Todo sigue en tu rama y, además, en una etiqueta puesta a propósito antes de
tocar nada:

```
staging-antes-del-reinicio-2026-08-29  ->  f1555b6
```

Con eso recuperas el estado exacto que tenía `staging` justo antes
(`git checkout staging-antes-del-reinicio-2026-08-29`, o cherry-pick suelto de
lo que quieras devolver). **Revísalo y reintegra lo que consideres**: la idea no
es descartar tu trabajo, es partir de una base común y que tú decidas qué vuelve.

### Qué había en `staging` que no está en esta base — 18 commits

**a) Cuatro que YA están, con otro SHA. No hay nada que hacer.**

| El tuyo | El nuestro |
|---|---|
| `dfa6e51` SL estructural: fills fantasma | `eb550d0` |
| `c79993d` SL del trade pintado en el chart | `a2282b4` |
| `40920cc` Days cuenta sesiones de calendario | `7415eed` |
| `8777d17` globs de mes con/sin cero | `27e8076` + `919ea1c` |

**b) Tres RECHAZADOS por acuerdo de las dos partes. No los devuelvas.**

`19979bc` y `6c05066` (split del gap de PMH) y `970ea9f`
(`LAKE_PREV_CLOSE_YA_AJUSTADO`). Aquí **doblarían el ajuste**: nuestro
`prev_close` ya viene ajustado del ETL, y aplicarlo otra vez da gaps falsos (el
caso NVDA 2024-06-10 → 910,77 %). Ya lo cerramos formalmente los dos el 27-ago.

**c) Tres de código que Jaume ha decidido NO adoptar, a sabiendas.**

- `dfb9f04` — profiler fino de sub-fases de `stream_build`
- `bcc75ba` — warmup de indicadores al arrancar
- `8cd3ad9` — pestaña «Últimas pruebas»

Se le listaron uno a uno con lo que hacía cada uno y dijo que no. **No es un
olvido ni un accidente del reinicio.** Si crees que alguno debe volver, es
conversación, no bug.

**d) Ocho de documentación tuya**, incluidos dos bloques de este mismo fichero
(«2026-08-27 noche, 4ª parte» y «5ª parte»). Están en la etiqueta. Si quieres
que vuelvan a `MEMORIA_MADRE.md`, se pegan al final y ya: el documento es
append-only, no hay conflicto real.

### Lo que sí te llevas de esta base

Además de todo lo del 27, 28 y 29 que hay documentado más arriba, **dos commits
tuyos que adoptamos tal cual, con tu autoría intacta**:

- `2aefb06` — Darvas Box en el enum del schema (teníamos el mismo fallo)
- `764277e` — «Guardar como nueva estrategia»
- `e04d95e` — indicador Current Gap (%)
- `a08f01e` — watchdog del backend local

### Por qué se ha hecho así

Los dos documentos habían divergido 373/329 líneas y cualquier fusión
conflictaba en medio. Jaume prefirió una base común limpia y que la reconciliación
la hagas tú mirando la etiqueta, en vez de arrastrar una fusión a ciegas. Queda
dicho para que nadie lo lea como un descuido dentro de seis meses.

---

## 2026-08-30 — Walk Forward: el eje de tiempo que repetía backtests y el análisis que desaparecía con dos parámetros

Tres huecos quedaron apuntados el 29-ago en el **modo Completo** del Walk
Forward. El barrido en sí **no estaba roto** (eso ya se auditó y quedó limpio:
la caché de señales vuelve a leer la gestión de riesgo en cada combinación). Hoy
se cierran el 2 y el 3. **El 1 sigue abierto** — con un stop de estructura no se
puede optimizar nada del stop, porque el generador hace `float(hs["value"])` y
`"Previous Max"` es texto; merece PRD porque toca la firma del simulador.

### 1. El eje de un parámetro entero repetía combinaciones

`robustness_wfo._axis()` generaba el eje con `np.linspace` crudo. El decimal se
perdía después, al escribir el valor: `_encode_tp_value` → `_minutos_a_hhmm`
hace `int(round(...))`. Resultado: valores distintos del eje colapsaban en el
mismo minuto y **se pagaban backtests para probar exactamente lo mismo**, sin
aviso — la barra de progreso contaba todos.

Medido: barrer una hora de cierre de **15:30 a 15:35 en 10 pasos** daba 10
combinaciones para **6 horas distintas**. Con 5 ventanas, 20 de los 55 backtests
anunciados eran duplicados exactos.

Y el gasto no era lo peor. Los duplicados entraban en la tabla de mesetas como
**filas separadas con puntuación idéntica**, y como la meseta es una media móvil
de tres vecinos, cada valor tenía de vecino a su propio gemelo: la curva salía
más lisa de lo que era y **aparentaba una meseta que no existía**. La
recomendación quedaba sesgada hacia «estable».

El optimizador normal (`run_optimization_grid`) ya lo hacía bien: redondea a
entero y deduplica con `sorted(set(...))`. Ahora `_axis` aplica **la misma
regla**, y el conjunto de claves enteras —que estaba escrito palabra por palabra
en dos sitios— vive en un único `_INT_PARAM_KEYS` en `optimization_service.py`.

**Efecto colateral que hubo que cerrar:** la pantalla anunciaba
`ventanas × (pasos+1)` backtests y al deduplicar se corren menos. El router
cuenta ahora con los ejes de verdad y la línea previa dice «Hasta N».

### 2. Con dos parámetros, el análisis por valor desaparecía ENTERO

`robustness_wfo.py:325` hacía `_param_analysis(...) if len(param_configs) == 1
else None`, y la pantalla escondía el bloque completo al recibir `null`. Barrer
dos parámetros costaba `ventanas × pasos₁ × pasos₂` backtests y **no daba
recomendación para ninguno de los dos**: ni valor recomendado, ni tabla por
valor, ni estabilidad, ni el aviso de «el óptimo cayó en el borde del rango».

El guardia no era un descuido: `_param_analysis` estaba escrito en una sola
dimensión (recorría `values`, comparaba `params[0]` y `best_params[0]`), así que
apagarlo evitaba analizar el primero ignorando que el segundo se movía.

Ahora recibe la **posición del parámetro** dentro de la combinación. Con uno
devuelve **el mismo diccionario que antes, campo por campo** (comprobado contra
`HEAD`). Con varios, cada eje se lee **marginalizando** sobre los demás: la
puntuación de un valor es la media de todas las combinaciones que lo contienen.
Se devuelve `param_analyses` (uno por eje) y se conserva `param_analysis` con la
forma de siempre.

**Limitación asumida y escrita en el docstring:** marginalizar mezcla en `std`
la dispersión entre ventanas con la que introduce el otro parámetro al moverse,
y una **interacción** (un parámetro que solo funciona acompañado de cierto valor
del otro) no se ve en una fila. Para eso hay que mirar la rejilla entera.

### 3. La meseta se degeneraba en ejes cortos — fallo preexistente

Encontrado de paso, existía desde el principio. Los extremos promediaban solo
los dos vecinos que tenían, y eso los hacía **incomparables** con los de dentro
(dos sumandos frente a tres):

| Medias por valor | Meseta (antes) | Recomendaba |
|---|---|---|
| `0,1 · 1,1` | `0,6 · 0,6` | el primero — **el peor**, siempre, con 2 valores |
| `0,2 · 1,0 · 0,2` | `0,6 · 0,47 · 0,6` | el primero — **el peor** |
| `0,1 · 0,9 · 1,0 · 0,2` | `0,5 · 0,67 · 0,7 · 0,6` | el tercero — correcto |

Arreglado: fuera de la rejilla se supone que el eje sigue **plano** (el extremo
se repite a sí mismo), con lo que todos promedian tres sumandos; y a igualdad de
meseta gana el que de verdad puntúa mejor. Los tres casos aciertan ahora, y el
caso realista de 4+ valores **recomienda exactamente lo mismo que antes**.

### 4. La pantalla ya deja barrer dos parámetros

Hasta hoy el formulario mandaba siempre uno (`params: [{ ...sel }]`), así que el
hueco 2 solo se alcanzaba llamando a la API a mano. Ahora hay un **segundo
parámetro opcional**, que excluye de su lista el que ya está elegido y se suelta
solo si el primero pasa a ser ese mismo. El aviso de coste escala con el
producto de los dos ejes.

También se corrigió algo latente: la **unidad** de cada eje viaja ahora con el
resultado (`param_configs[].unit`). Antes salía del formulario, que solo conoce
la del parámetro seleccionado en ese momento — con dos, el segundo se habría
pintado con la unidad del primero (un `810` crudo en vez de `13:30`).

### Verificación

- **11 tests nuevos** en `backend/tests/test_wfo_axis_and_analysis.py`, entre
  ellos la paridad del eje entero con la fórmula del optimizador y el análisis
  marginal de dos ejes con puntuación aditiva (comprobable a mano).
- `tsc --noEmit` limpio y `eslint` con **exactamente los mismos avisos
  preexistentes** que antes de tocar nada.
- **Barrido real en la pantalla**, estrategia «2.1B 50K (normalizada)»:
  6 ventanas × (Parcial 1 Distancia %, 2 pasos) × (Parcial 2 Hora de cierre,
  13:30–13:31 en 6 pasos). El formulario anunció **«Hasta 78 backtests»** y la
  barra de progreso mostró **30** — los 6 pasos de la hora deduplicados a 2.
  Antes habrían corrido los 78.

### Ficheros

`backend/app/services/robustness_wfo.py` · `backend/app/services/optimization_service.py`
`backend/app/routers/robustness.py` · `backend/tests/test_wfo_axis_and_analysis.py`
`frontend/src/components/robustez/modules/useWfo.tsx`
`frontend/src/components/robustez/charts/WfoCharts.tsx` · `frontend/src/lib/api_robustez.ts`

---

## 📣 2026-08-30 — Para Álvaro: qué lleva `sailor` que `staging` todavía no

`staging` se igualó a `sailor-rama-desarrollo` el 29-ago. Desde entonces esta
rama ha sumado **cinco cosas**. Ninguna toca la lógica de simulación salvo donde
se dice; están listadas para que decidas cuáles adoptar.

| # | Commit | Qué es | ¿Riesgo? |
|---|---|---|---|
| 1 | `d033c07` | Borrado `test_backtest_integration.py` | Ninguno |
| 2 | `401f9a6` | «Shares por Distancia al SL» también con stop en % | Bajo, ver abajo |
| 3 | `3e91992` | Walk Forward: eje que repetía backtests + análisis que desaparecía | Ninguno fuera del WFO |
| 4 | `3e8739d` | Documentación de lo anterior | — |
| 5 | *(este commit)* | Quitado el bloque «nivel rebasado al entrar» de la UI | Ninguno, ver abajo |

### 1. `test_backtest_integration.py` borrado

Gemelo de `test_backtest_engine.py` (borrado en `157435c`): no se podía ni
recolectar desde febrero. Importa `app.backtester.engine.BacktestEngine`, que el
propio código marca como muerto. No cubría nada que siguiera vivo.

### 2. «Cálculo de Shares por Distancia al SL» también con el stop en %

**Es el único de los cinco que cambia resultados**, y solo si activas el
interruptor con un stop en %.

Antes el interruptor solo estaba disponible con stop de *Market Structure*: con
«%» el bloque salía atenuado y sin clic, y encima cambiar el tipo de stop a «%»
apagaba `size_by_sl` en silencio. No había motivo técnico: **los dos motores ya
lo calculaban igual** para cualquier stop que dé un nivel de precio
(`portfolio_sim.py` y `portfolio_sim_jit.py:722`), con `size = riesgo /
abs(entrada − stop)`. Con «%» la distancia es `entrada × pct`, que es el
dimensionado clásico de "arriesgo X con un stop del Y %".

Comprobado en los dos motores con un caso sintético (entrada 10 $, stop 2 %,
riesgo 100 $): Python y JIT dan **500,0000 acciones** exactas. Paridad intacta.
Las estrategias guardadas no cambian: el interruptor sigue apagado por defecto.

### 3. Walk Forward — dos huecos cerrados

Detalle completo en la entrada del 30-ago más arriba. En resumen: el eje de un
parámetro entero no se redondeaba ni deduplicaba (15:30–15:35 en 10 pasos daba
solo 6 horas distintas → **20 backtests duplicados de 50**, y las mesetas salían
falsamente lisas porque cada valor tenía de vecino a su gemelo); y con dos
parámetros el análisis por valor desaparecía entero. **Contenido en
`robustness_wfo.py` y su pantalla; no toca el motor de simulación.**

### 5. Quitado el bloque «Si el nivel ya está rebasado al entrar»

`frontend/src/components/strategy-builder/RiskManagement.tsx`. Era el bloque que
permitía elegir un **nivel de respaldo** cuando el stop estructural queda del
lado ganador de la entrada. Se quita a petición de Jaume: comprobado que no
aportaba.

**No se ha tocado el motor.** `_structural_level`, `_sl_side_valid` y toda la
lógica de respaldo (`hs_fallback_value`, `hs_fallback_first`) siguen exactamente
igual en `portfolio_sim.py` y en el JIT. Se ha quitado **solo la interfaz**.

**Por qué esto no deja un ajuste fantasma:** se revisaron las cuatro estrategias
guardadas y **ninguna tiene `fallback_value`** (dos tienen `fallback_first_entry:
true`, pero el simulador exige el valor para activar nada:
`if hs_fallback_value and (...)`). Así que no hay estrategia cuyo comportamiento
dependa de un ajuste que ya no se puede ver. Si algún día se quiere devolver,
está en el historial y el motor lo sigue soportando.

Verificado con `tsc --noEmit`: **0 errores**. La prop `bias` se mantiene en la
interfaz para no romper a los llamadores, pero ya no se usa.

### Aparte: el motor es causal — medido, no supuesto

Trabajo de Jaume para un proyecto propio de avisos en vivo. **No aporta código a
este repo**, pero el hallazgo sí interesa aquí porque es una propiedad del motor
compartido.

Se comparó `translate_strategy` evaluando el **día entero** (como hace
`run_backtest`) contra el mismo motor evaluando **vela a vela**, quedándose solo
con el último valor de cada evaluación. Si difirieran, el motor estaría usando
información futura en esa vela.

**73 ticker-días, entre 2019 y 2026, cero divergencias:**

| Estrategia | Camino ejercitado | Días | Divergencias |
|---|---|---|---|
| 1B 50k | premercado, ventana de entrada, VWAP y acumulados | 49 | **0** |
| 2.1B 50K | RTH, piramidación, stop estructural | 24 | **0** |

Incluye días con más de 400 velas de señal. Esto confirma que los acumulados
causales que se metieron en su día (PM High/Low, RTH High/Low/Open, PM High Gap)
están bien: **ninguno filtra futuro**. Es una red de seguridad que conviene
volver a pasar si alguien toca los indicadores de sesión.

## 2026-08-31 — Dos indicadores de caída, y tres decisiones de rama

### 1. Indicadores nuevos: «% Session Fade» y «% Fade»

Los pidió Jaume para operar el desinflado de los gaps. Los dos devuelven un
**porcentaje de CAÍDA en positivo**, para que la condición se lea igual que se
dice en voz alta («se desinfló más de un 20%» → `% Fade > 20`). Negativo
significa que el precio está por encima de la referencia.

**`% Session Fade`** — caída de una sesión ENTERA, congelada. Parámetro
`session_ref`:

| Modo | Fórmula | Existe a partir de |
|---|---|---|
| `pm` | `(PM High − apertura de mercado) / PM High × 100` | 09:30 |
| `rth` | `(máx. RTH − apertura del After) / máx. RTH × 100` | 16:00 |
| `full` | `(máx. del día 04:00-16:00 − apertura del After) / máx. × 100` | 16:00 |

El modo `full` mide el **desinflado real del día**, sin que importe si el máximo
se hizo en premarket o en la sesión regular. Cuando el máximo del día es el PM
High —lo normal en un gap que se muere— `full` y `rth` dan números muy
distintos, y `full` es el que describe lo que pasó de verdad.

**Es causal sin necesidad de trucos**, y conviene entender por qué: la apertura
de la sesión siguiente es NaN hasta que esa sesión abre, y para entonces el
máximo de referencia ya está cerrado y no puede cambiar. Antes de ese instante
el indicador no existe y cualquier condición que lo use evalúa False. No se
puede saber el fade del premercado a las 07:00, y el indicador lo refleja.

**`% Fade`** — caída VIVA, con una referencia que se reancla sola. Parámetro
`fade_ref`:

- `previous_max` → `(máximo previo − close) / máximo previo × 100`. Usa
  `ap_session` igual que «Previous Max», y el mismo `shift(1)` (el máximo no
  incluye la barra actual). Cada máximo nuevo devuelve el fade a cero.
- `vwap_cross` → `(VWAP de la vela del último cruce − close) / ese VWAP × 100`.
  La referencia es el VWAP **de la vela en que el precio cruzó**, no el VWAP
  vivo: por eso el fade sigue creciendo aunque el VWAP también baje. Se reancla
  en cada cruce nuevo. NaN antes del primer cruce del día.

Un detalle que costó pensar: en el cruce del VWAP, un NaN a cualquiera de los
dos lados **no cuenta como cruce**. Sin ese guardia, la primera vela con volumen
(el VWAP pasa de NaN a número) se contaría como un cruce falso y anclaría ahí.

**Las 17 capas tocadas** (el mapa completo, por si sirve para el siguiente):

- Backend: `schemas/strategy.py` (enum + `fade_ref`), `services/indicators.py`
  (3 helpers nuevos + 2 ramas de cálculo), `backtester/engine.py` (motor
  legacy), `services/strategy_engine.py` (reenvío del parámetro en
  `_compute_from_config` — si falta, el parámetro se pierde en silencio),
  `api_public/.../catalog.py`.
- Frontend: `types/strategy.ts`, `ConditionBuilder.tsx` (categoría, etiqueta,
  descripción, defectos y los dos selectores), `WizardStrategyBuilder.tsx`,
  `indicatorRegistry.ts`, `lib/indicators.ts`, `Chart.tsx`,
  `IndicatorDropdown.tsx`, `indicatorValidation.ts`, `assistant/schemas.ts`,
  `assistant/strategyGuard.ts`, `InlineStrategyBuilder.tsx`,
  `StrategiesTable.tsx`.

No hacen falta en `optimization_service.py`: sus dos parámetros son texto, no
números, así que no hay nada que barrer.

**Van por el camino clásico a propósito.** Ninguno está en
`_RAW_INDICATOR_DISPATCH`, así que una estrategia que los use da
`has_special=True` y se va entera a la vía legacy: **correcta, solo que sin el
acelerón**. Meterlos en el dispatch sería una optimización, nunca una
corrección.

**De propina, una limpieza.** El mismo `if` de «este indicador es un
porcentaje» estaba copiado literal en **cinco sitios** de cuatro ficheros, y ya
se habían desincronizado: Squeeze llevaba el sufijo `%` en el resumen del
`ConditionBuilder` pero no en el del wizard, el de la tabla ni el del
`InlineStrategyBuilder`. Ahora hay dos predicados exportados,
`isPercentIndicator` e `isMeasureIndicator`, y las cinco copias los usan. Efecto
lateral visible: **Squeeze ya muestra el `%` en los cuatro resúmenes**.

### 2. Verificación

- **`backend/tests/test_fade_indicators.py`, 15 tests.** Aritmética de los
  cuatro modos, causalidad, reanclaje, y **paridad `services/indicators.py` ↔
  `backtester/engine.py`** (incluido un día aleatorio de 480 velas, no solo
  casos escritos a mano).
- **Paridad gráfico ↔ backend, medida.** La regla del repo tras lo de Darvas.
  540 velas dispersas de un día real (35% de minutos ausentes, velas con volumen
  0), los cuatro modos: **1.441 valores comparados, cero divergencias**, y los
  NaN caen exactamente en las mismas velas. Se comparó el JS **compilado del
  fichero real**, no una copia a mano.
- `tsc --noEmit`: 0 errores. Suite del backend: **sin regresiones** (los 103
  fallos de este árbol son los mismos con y sin el cambio — dependen del lago
  local y de GCS; se comprobó con `git stash`).

**Ojo con una trampa al medir esto:** `test_run_backtest_slab_equivalence` pasa
en un worktree limpio y falla en el árbol de trabajo, porque depende del estado
local del lago. Parece una regresión y no lo es. La única forma honesta de
comparar es con el mismo árbol, no con dos.

### 3. `Previous max` / `Previous min`: bucle por barra → vectorizado

Los dos hacían un bucle Python barra a barra. Ahora comparten helper
(`_previous_extreme_series`) con `% Fade`, para que no puedan divergir. **La
equivalencia está medida**, no supuesta: un test compara el resultado nuevo
contra una copia literal del bucle viejo, sobre 200 velas aleatorias y en las
tres sesiones (`ap.PM`, `ap.RTH`, `ap.AM`). Ni un decimal de diferencia — los
backtests viejos siguen dando lo mismo.

### 4. Para Álvaro: tres commits que Jaume descarta

De la lista de cosas que quedaban por traer de la rama de Álvaro,
**Jaume descarta estos tres**, hoy, a conciencia. Se anotan aquí por si alguna
vez algo no cuadra entre las dos ramas y el rastro lleva por aquí:

| Commit | Qué era | Por qué no |
|---|---|---|
| `dfb9f04` | profiler fino de sub-fases de `stream_build` (gated) | No le aporta |
| `bcc75ba` | warmup de indicadores al arrancar | No le aporta |
| `8cd3ad9` | pestaña «Últimas pruebas» (reabrir runs auto-guardados) | No le aporta |

**No están en ninguna rama viva.** Salen de la etiqueta
`staging-antes-del-reinicio-2026-08-29` → `f1555b6` si algún día se quieren.
Esto no es un juicio sobre el código: es que Jaume no los necesita.

### 5. Walk Forward: el hueco del stop estructural se cierra como «no aplica»

Quedaba abierto que **con un stop de estructura no se puede optimizar nada del
stop**, porque el generador hace `float(hs["value"])` y el valor es texto
(`"Previous Max"`). Se había apuntado que merecía un PRD.

**Jaume lo cierra: no lo merece.** Un stop por «Premarket High» o «Previous Max»
es un **punto fijo del gráfico** — no hay nada que barrer, porque el nivel
siempre va a ser el mismo. Optimizar tiene sentido para un stop en %, y eso ya
funciona. Queda fuera de alcance por decisión de producto, no por dificultad.

---

## 📣 2026-08-29 — Entradas de Álvaro, traídas con los cherry-picks del 31-ago

> Estas dos secciones vienen de `alvaro-rama-desarrollo` junto con los commits
> `9c0cb85` y `8063e0a`. Se conservan tal cual las escribió él. Están fuera de
> orden cronológico a propósito: llegaron por cherry-pick el 31-ago, después de
> que aquí ya se hubieran escrito las sesiones del 29, 30 y 31.

- **Lo único que roza al equipo:** el lago de ORIGEN
  (`gs://strategybuilderbbdd/cold_storage/daily_metrics`) acumula desde el
  2022-07-12 **1.032 filas con `ticker IS NULL`** (una por día de bolsa hasta
  hoy). Parece un instrumento real que perdió su símbolo en la ingesta (días
  con rango +86 %/+117 % — perfil BTT — invisibles para
  screener/datasets/backtests de todos, prod incluida). Pendiente del dueño del
  lago: depurar en origen e identificar el instrumento.
- La rama de Álvaro trae un fix defensivo (commit `def8a9b`): la reconciliación
  de completitud del orquestador excluye esas filas fantasma y las reporta como
  `phantom_ticker_days`, para que `BACKTEST_STRICT_COMPLETENESS=true` no
  rechace datasets enteros por dato corrupto del lago.
- Menor, ABIERTO: la caché de qualifying en disco usa `:` en el nombre de
  fichero (`data_service.py:639/695`) → en Windows vive en un NTFS ADS;
  funciona por accidente.

### [HALLAZGO · 2026-08-29 · 01] Hot-cache RAM ignora en silencio las reglas lead_/lag_ (Gap ±N) y calcula sus shifts sobre un subconjunto prefiltrado
- **Reporta:** ZCode (para Álvaro)
- **Severidad:** inconsistencia
- **Dónde:** `backend/app/services/data_service.py:1043` (rules evaluadas antes de calcular las columnas shift, bloque de `:1045` en adelante) y `:500` (`_can_use_hot_cache`); origen del prefiltrado en `backend/app/services/cache_service.py:200` (`WHERE gap_pct >= 10.0`).
- **Qué observé:** en la vía hot-cache RAM, `_evaluate_rules_on_df` se ejecuta ANTES de que existan las columnas `lead_*`/`lag_*` (se calculan después con `groupby().shift()`), y su guard `field in df.columns` descarta la regla sin aviso ni log. Además, esos shifts se calculan sobre el DataFrame YA filtrado por gap/fechas — y el hot cache base ya viene prefiltrado `gap_pct >= 10` — así que los "días adyacentes" del hot-cache no son los días adyacentes reales del ticker en el lago.
- **Cómo reproducir:** backtest en un entorno con `DB_PROVIDER != local` (prod/staging) usando un dataset que active el hot-cache (`min_gap_pct >= 5`, o regla `Open Gap % >= 5` / `PMH Gap % >= 20`) y que ADEMÁS lleve reglas `lead_*` (filtros Gap+1/Gap+2 de "Añadir filtro de mercado"). El filtro lead se ignora y el universo sale más grande. En local NO ocurre: con `provider=local` y custom rules el flujo va por la vía autoritativa (DuckDB).
- **Evidencia:** lectura de código: `data_service.py:1043` (`result = _evaluate_rules_on_df(result, rules)`) precede al bloque `:1045` "Compute LEAD/LAG columns if they don't exist in the hot cache", cuyo propio comentario dice "The hot_cache_daily_gaps.parquet doesn't have these columns pre-computed". Tests que fijan el guard nuevo: `backend/tests/test_prev_day_universe_filters.py::TestHotCacheGuard` (10/10 pass).
- **Hipótesis de causa:** HIPÓTESIS — el hot-cache se diseñó para reglas del propio día del gap; el soporte de reglas `lead_*` llegó después sin recolocar la evaluación de rules respecto al cálculo de shifts.
- **Impacto:** backtests de prod con gap ≥ 5% + reglas Gap+1/+2 (y, desde hoy, Gap−1) pueden recibir un universo SIN ese filtro aplicado — mismo patrón de no-determinismo silencioso que el 70R↔137R documentado en el propio `data_service.py`. También afecta al re-anclaje `apply_day=gap_1_day/gap_2_day` que usa esos shifts (universo hot-cache).
- **Código tocado:** solo un guard fail-safe en `_can_use_hot_cache` (`data_service.py:500`, rama `alvaro-rama-desarrollo`, incluido en el plan que Álvaro aprobó): las reglas `lead_*`/`lag_*` ya NO entran al hot-cache y caen a la vía GCS autoritativa (más lenta, correcta). El fix de fondo (evaluar rules tras los shifts, o excluir esa vía del re-anclaje) queda para el dueño del código.
- **Estado:** ABIERTO

## 2026-08-29 — FEATURE «Gap −1» (filtros de mercado del día anterior) — SOLO EN rama `alvaro-rama-desarrollo`, NO APLICADA A STAGING

> Reporte de lo modificado, a petición de Álvaro. La IA NO aplica nada a
> staging (ni merge ni push — la integración la hace Álvaro por PR, como manda
> AGENTS.md). El código vive sin commitear en la rama de Álvaro hasta que él
> decida. Relacionado: HALLAZGO · 2026-08-29 · 01 (justo arriba), que salió
> durante este trabajo.

**Qué es.** Cuarta opción de día en «Añadir filtro de mercado» (en los tres
builders: Config. libre, Wizard y Constructor de Datasets): **Gap −1 = día
anterior al gap (D−1)**, combinable con los 7 parámetros existentes. Permite
pedir universos tipo «volumen RTH del día anterior ≥ X», «el día anterior
cerró RTH por encima/debajo de $Y», gap %, PMH gap %, primer precio PM y
rango RTH de D−1. Cada regla viaja como columna `lag_<col>_1` (mismo
mecanismo que los `lead_*_1/_2` de Gap+1/+2). Causal: el día anterior al gap
es información conocida antes de operar.

**Ficheros tocados** (los tres primeros existen porque TODAS las vías tienen
que materializar las columnas `lag_`, o la regla casca o se ignora):
- `backend/app/services/qualifying_windows.py` (NUEVO): definición ÚNICA de
  los LAG 1, consumida por las tres vías para que no puedan divergir.
- `backend/app/routers/query.py` (`_compute_dataset_pairs`): la subquery de
  materialización de pares solo calculaba LEADs; ahora se genera desde
  `qualifying_windows`. Sin esto, crear un dataset con regla `lag_*` fallaba
  con Binder Error y el dataset quedaba sin pares.
- `backend/app/services/data_service.py` y `backend/app/db/gcs_cache.py`:
  LAG 1 que faltaban en el stage-2 del qualifying (vía local y vía GCS). En
  GCS, si el WHERE lleva reglas `lag_`, se leen también los paths del año
  anterior para que el primer día del rango tenga su día anterior real (el
  predicate externo sigue acotando el RESULTADO al rango pedido).
- `data_service.py` `_can_use_hot_cache` — **GUARD, ojo Sailor**: las reglas
  `lead_*`/`lag_*` ya NO pasan por el hot-cache RAM (allí se ignoraban en
  silencio — ver HALLAZGO 01). Efecto: en prod, un dataset gap ≥ 5% con reglas
  lead_/lag_ ahora cae a la vía GCS autoritativa (más lenta, correcta). Cambia
  comportamiento TAMBIÉN para los lead_ existentes, no solo para Gap −1.
- Frontend: `InlineStrategyBuilder.tsx` y `WizardStrategyBuilder.tsx` (opción
  de día + mapeo a `lag_*_1` + etiquetas legibles «… día anterior» en los
  chips), `InlineDatasetBuilder.tsx` (sección GAP-1 DAY).

**Semántica de las etiquetas de precio con Gap −1**: «Precio RTH ($)» es el
CIERRE RTH del día anterior (`lag_rth_close_1`, cierre de sesión regular
~16:00 ET; en el Wizard el label heredado dice «Precio Apertura RTH ($)» —
engañoso, la métrica es el cierre; renombrarlo pendiente de decisión de
Álvaro). «Precio PM ($)» es el PRIMER precio operado del premarket de D−1
(`lag_open_1`), no una apertura RTH (que no existe como parámetro).

**Compatibilidad**: nada se rompe — estrategias y datasets guardados intactos
(las rules son JSON opaco; las subquerys solo AÑADEN columnas), motor de
backtest, Numba y schema de BD sin tocar. Nota operativa: si algún entorno
usa `QUALIFYING_WINDOWED_PARQUET`, regenerar ese parquet tras integrar
(default OFF).

**Verificación**: `backend/tests/test_prev_day_universe_filters.py` 10/10
(incluida ejecución real del SQL de materialización sobre un mini-lago DuckDB
in-memory: filtra bien y el primer día de cada ticker con LAG NULL queda
fuera); `tsc --noEmit` limpio; 107 tests del motor OK (`test_backtest_golden`
falla por entorno — HTTP 403 de GCS sin credenciales — y se verificó con
stash que falla igual SIN estos cambios). UI verificada en navegador en los
tres builders (opción nueva presente; flujo completo probado en Config.
libre: Gap −1 + Vol. RTH → chip «volumen rth día anterior >= 1M»).

**Pendiente de Álvaro**: commit + push en SU rama (la IA no pushea sin OK
explícito) e integración a staging por PR cuando él decida. El fix de fondo
del hot-cache sigue ABIERTO (HALLAZGO 01); lo único tocado al respecto es el
guard fail-safe descrito arriba.
