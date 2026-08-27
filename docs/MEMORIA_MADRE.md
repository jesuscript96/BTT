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

## 2026-08-26 (tarde) — Fix de gaps por split en el lago + carga incremental del DuckDB + fix de "Days"

### 1. Fix del gap diario por split (el dato, no la app)

El universo del backtester leía el gap en crudo: cada split/reverse-split entraba
como gap gigante falso (NVDA 2024-06-10 = -89,89%; 2.123 ticker-días falsos con
`pmh>=50`, el 9,4% del universo short). Corregido en el lago (proyecto
`cangrejo_data`, PRD_FIX_gaps_falsos_splits): los 3 gaps (`gap_pct`,
`gap_at_open_pct`, `pmh_gap_pct`) dividen por `close_prev_adj = prev_close *
product(split_from/split_to)` del día. `daily_metrics`, bygap y
`local_data.duckdb` regenerados y verificados (NVDA pasa a +1,08; universo
`pmh>=50` de 22.676 → 20.997).

**Consecuencia para comparar backtests viejos/nuevos:** los candidatos fantasma
por split ya no existen. Con el dataset típico (`pmh>=20`, `close>=$1`) en 2025
eran 361 pares de 8.462 (-4,3%); en todo el histórico, 1.824 pares. Curvas
antiguas con más trades incluían shorts contra gaps que nunca ocurrieron.

En ESTE repo (commits `19979bc` + `6c05066` en `alvaro-rama-desarrollo`):
`lake_db_loader._alinear_pmh_gap_pct` y la migración de arranque de `init_db.py`
usan la misma fórmula ajustada (antes reescribían `pmh_gap_pct` en crudo en cada
carga/arranque y re-corrompían la tabla). La tabla `splits` del DuckDB local
pasa a 4 columnas (`split_from`/`split_to` incluidas): con eso arranca sin el
`[WARN] Failed to load splits cache` y el filtro anti-reverse-split del
screener vuelve a funcionar. OJO: anti-join con `NOT EXISTS`, no con
`(a,b) NOT IN (SELECT x,y)` — el venv del backend lleva DuckDB 1.1.3 y no lo
soporta.

### 2. Carga incremental del DuckDB en el ETL diario (adiós a la reescritura de 58 GB)

`etl_to_edgecute.py --incremental --load` ya no hace DROP+CREATE+INSERT de las
~3.000 M de filas: carga SOLO los meses tocados (DELETE por rango + INSERT del
parquet, transaccional, espejo de `cargar_meses_en_duckdb`). El paso ETL del
diario pasa de 30-40 min a ~2 min (medido en la run manual del 26/08:
pipeline completo 8/8 pasos en 18,2 min). La recarga completa queda como
herramienta de reparación (`--full --load` o FASE 3 de `reparar_lago.py`).
El bygap se regenera como paso final del diario (`regenerar_bygap.py`, 34 s).

### 3. Fix de "Days" en Aggregate Results (el único cambio de código de esta tanda aparte de los de arriba)

`Days` contaba **ticker-días** (`len(day_results)`), no sesiones: un año
mostraba "1460 días" (≈5,8 candidatos/día). Ahora cuenta **fechas de calendario
únicas** (`backtest_service.py`, `_aggregate_metrics`). Efecto lateral
intencionado: `Avg Ret/Day` y `Avg R/Day` pasan a ser por SESIÓN (denominador
correcto). Verificado sobre una estrategia con ventana de un año: Days
1460 → 250. La pestaña "Dias" de la lista sigue listando ticker-días (es su
naturaleza).

### 4. PENDIENTES para coordinar (reportados, NO tocados)

- **Cherry-pick del fix de fees `cd455ae`** ("cobra el lado de entrada en la 1ª
  ejecución que liquida la posición" — ITEM 4 del reporte Sailor). NO está en
  esta rama; vive en `alvaro-prereset-8b7959f`. La versión actual tiene ese bug
  activo: cierres 100% vía parciales pagan un solo lado de comisión → resultados
  ligeramente sobreestimados en estrategias con parciales. Con él van sus tests
  (`test_fees.py`, `test_bygap_parity.py`, `test_fade_partials.py`,
  `test_current_gap_semantics.py`, `test_trail_break_even.py` — 901 líneas,
  tampoco están).
- **`alvaro-prereset-8b7959f` además contiene** la `MEMORIA.md` antigua (981
  líneas), la carpeta `ALVARO_CAMBIOS/`, el Darvas Box y 2 merges de staging
  que la rama actual no tiene. Recuperación pendiente de acordar.

### 5. PRD para Sailor con todo el paquete de hoy

`docs/PRD_FIX_SPLITS_GAPS_Y_PIPELINE_20260826.md` — el fix de gaps por split
(lago + backend), la carga incremental del DuckDB, el fix de "Days" y cómo
verificar cada cosa en 5 minutos. Solo los arreglos que afectan a ambos;
nada de estrategias ni curvas concretas. `BACKTEST_STRICT_COMPLETENESS=true`
ya está activo en el `.env` local de Alvaro (recomendado en todos).

### 6. PRÓXIMOS ARREGLOS (propuesta): tablas de precalculados para acelerar la carga

Medido el 26/08 con los `[TIMING]` del motor: de una run de ~86 s, el
**stream_build se lleva ~83 s (95 %)** — el bucle que por cada ticker-día lee
las velas, las **resamplea** (1m→5m/15m según la estrategia) y **recalcula los
indicadores en Python** (rolling/groupby) antes de simular. El qualifying ya no
es el problema (3,5 s frío, ms en caché; el bygap materializado hizo su
trabajo). La idea es aplicar el MISMO patrón del bygap a lo que se recalcula
en cada run:

1. **Velas 5m/15m precalculadas en el lago** — el resample 1m→Nmin se haría
   una vez en el ETL (parquet por ticker-mes), no en cada backtest.
2. **Indicadores estándar precalculados por (ticker, día)** — solo los de
   parámetros FIJOS de uso común (EMA rápidas/lentas típicas, Accum Volume,
   RVOL, PM high/low vs open...). Los de parámetros libres del usuario
   (Squeeze con ventana variable, etc.) seguirían calculándose en vivo: la
   tabla no puede llevar todas las combinaciones.
3. **Precarga del universo** — extender el `[PRECACHE]` actual para que tras
   cada actualización del lago queden en caché los ticker-días candidatos más
   frecuentes (hoy solo calienta lo que acaba de usar cada dataset).

**Puntos a decidir juntos:** qué indicadores entran (lista cerrada inicial),
dónde viven (lago `cangrejo_data` vs caché del backend), la invalidación tras
cada update del diario (el bygap ya lo resuelve regenerándose en 34 s — estas
tablas seguirían el mismo paso final), y el coste de disco (estimación
inicial: ~1,5-2× el intradía para velas 5m + indicadores).

**Impacto esperado:** si el resample+indicadores son la mitad del stream_build
(por medir con un profiler fino antes de empezar), una run típica pasaría de
~3,5 min en frío a ~1,5 min, y las re-runs de optimización (que repiten el
mismo cálculo decenas de veces por rejilla) serían el mayor beneficiado.
Primer paso propuesto: medir con profiler 5-10 ticker-días para partir el
stream_build en (lectura / resample / indicadores / simulación) y decidir con
datos qué tabla paga su coste.

### 7. Fix del padding de meses: agosto "no existía" para el loader y la caché

Síntoma: un backtest rechazado por completitud — "10 de 4.977 ticker-días sin
intradía", todos del 17-20/08, pese a que el lago tenía las velas. Causa raíz:
**las particiones del lago van sin cero (`month=8`, como las escribe DuckDB) y
los globs de `lake_db_loader` iban con cero (`month=08`)** → el mes no
resolvía y tres cosas fallaban EN SILENCIO: `cargar_meses_en_duckdb` se saltaba
la carga del mes, `anadir_dias_al_cache` reportaba "ya estaba al día" sin
mirar nada (167 ficheros de caché de agosto quedados en el día 14 — residuo
del incidente del 21/08), y la carga incremental nueva del ETL tampoco encontraba
el parquet. Arreglado probando ambos paddings (igual que hacía el resolvedor de
velas). Tras el fix: agosto cargado en `local_data.duckdb` (tabla al 25/08) y
caché reparada (+224.279 velas en 167 ficheros). NOTA: si se invoca
`anadir_dias_al_cache` fuera del backend, `CACHE_DIR=.cache/intraday` es
RELATIVO al cwd de `backend/` — exportarlo absoluto.

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

## Estado actual de la rama Álvaro respecto a los datos (2026-08-27)

| Elemento | Estado |
|---|---|
| Gaps ajustados por split | ✅ Corregido (`19979bc`, `6c05066`). Nuestro `prev_close` es CRUDO y se ajusta al calcular en `_alinear_pmh_gap_pct`. **NO portar a Sailor**: su lago ya ajusta dentro de la columna → doble ajuste |
| `init_db.py` / `_alinear_pmh_gap_pct` | Ajuste de split ACTIVO — necesario en este lago. Interruptor `LAKE_PREV_CLOSE_YA_AJUSTADO` (default off) para el otro lago — ver entrada del 27/08 (tarde) |
| Tabla `splits` | ✅ Corregida a 4 columnas (tenía 2; daba `[WARN] split_from not found`) |
| Junctions `cold_storage/splits` y `/tickers` | ✅ Creados (no existían; el reload se saltaba en silencio) |
| Padding de meses en particiones | ✅ El glob prueba ambos (`month=8` y `month=08`) — `8777d17` |
| "Days" / `avg_r_per_day` | ✅ Corregido a sesiones de calendario (converge con staging) |
| Carga incremental del DuckDB | ✅ Propia: 30-40 min → 2,2 min |
| `BACKTEST_STRICT_COMPLETENESS` | ✅ Encendido (`true`) en el `.env` local de Álvaro |
| Perf al lanzar backtest | `stream_build` = 95% del run (medido 26/08). PRD en `docs/PRD_PERF_BACKTEST_STREAMBUILD_20260827.md`, pendiente de atacar |
| Sync con `staging` | ✅ Mergeado (`347e127`): la rama contiene los 2 commits de Jaime |
| Suite de tests | 103 fallos / 321 pasan / 15 errores (medido 27/08 en esta máquina, tal cual). NF/NP idénticos al baseline de Sailor; casi todos los fallos son `daily_metrics does not exist` (los tests esperan la BD remota, no el lago local). Los +2 errores vs sus 13: colección de 2 tests obsoletos (`test_backtest_engine.py` importa `Condition`, `test_backtest_integration.py` importa `filter_market_data_by_interval_and_dates` — nombres ya inexistentes). Sin cambios de código |

Regla que se lleva de aquí: los dos lagos llegan al mismo resultado por caminos
distintos (Álvaro ajusta el split al calcular, Sailor dentro de la columna del
ETL). Antes de adoptar un fix de datos del otro lado, verificar en qué capa
aplica cada lago el ajuste — los parches NO son intercambiables.

> **2026-08-27**: divergencias rama Álvaro vs `staging` medidas y clasificadas
> para triaje de Jaime (qué adoptar / no adoptar / ya convergido, con diffs) →
> `docs/DIVERGENCIAS_ALVARO_VS_STAGING_20260827.md`.

## 2026-08-27 (tarde) — `LAKE_PREV_CLOSE_YA_AJUSTADO`: el mismo backend para los dos lagos

Implementada la propuesta textual de Sailor (§ "Por qué sus parches de splits
NO se pueden adoptar aquí", alternativa conservadora): una variable de entorno
que apaga el recálculo de `pmh_gap_pct` donde el ETL ya ajusta el split.

- **Qué hace**: con `LAKE_PREV_CLOSE_YA_AJUSTADO=true`, los DOS sitios que
  recalculan con factor de split se apagan enteros — la migración de arranque
  de `init_db.py` (de paso desaparece el UPDATE de 19,2 M de filas no-op en
  cada arranque de la máquina de Sailor) y `_alinear_pmh_gap_pct` en la carga
  mensual. `pmh_gap_pct` se queda tal y como lo escribió el ETL, y ni se lee
  ni se exige el parquet de splits en ese modo.
- **Por qué así**: en el lago de Sailor la columna `prev_close` ya lleva el
  factor horneado; recalcular ahí con factor es el doble ajuste (NVDA 1,08% →
  910,77%) y recalcular sin factor es un no-op que reescribe 19 M de filas.
  Confiar en el ETL era su propuesta PREFERIDA; esto es esa propuesta, pero
  opt-in.
- **Apagada por defecto (regla R7)**: en el lago de esta rama (`cangrejo_data`)
  `prev_close` es CRUDO y el ajuste hace falta. Sin poner la variable, ni una
  línea cambia de comportamiento en la máquina de Álvaro (los tests del camino
  default lo fijan: el día de split sale 1,0% con factor, -89,9% sin).
- **⚠️ COORDINAR**: cuando esto llegue a `staging`, **Sailor debe añadir
  `LAKE_PREV_CLOSE_YA_AJUSTADO=true` a su `backend/.env`** — sin ella, su lago
  sufriría el doble ajuste al primer arranque.
- **Tests**: `tests/test_lake_prev_close_ya_ajustado.py` (nuevo, 5 casos: los
  dos sitios × default/flag, y el contrato del `RuntimeError` sin parquet de
  splits; todo con DuckDB en memoria + lago de mentira, nada de la BD remota).
  Suite completa: **103 fallos / 326 pasan / 15 errores** — los mismos 103+15
  del baseline, +5 verdes nuevos, 0 regresiones.

Ficheros: `app/init_db.py`, `app/services/lake_db_loader.py`
(`_alinear_pmh_gap_pct` gana un parámetro `log` opcional para avisar sin
lanzar el mensaje al vacío).

## 2026-08-27 (noche) — Profiler fino de `stream_build`: el PRD de perf cambia de alcance

Ejecutado el §7 del `docs/PRD_PERF_BACKTEST_STREAMBUILD_20260827.md` (ver ahí
las tablas completas). Instrumentación nueva: `backend/app/services/subphase_profiler.py`,
gated tras `BACKTEST_PROFILE_SUBPHASES=1` (**apagado por defecto**, R7), con
hooks de solo-medición en `backtest_service` / `strategy_engine` / `indicators`.
Con la var en off, cero cambio de comportamiento.

**Qué se midió** (3 runs, 9-10 ticker-días, estrategias y datasets de Álvaro
sin tocar, completitud 100 %):

- **El resample es barato**: ~3 ms/ticker-día (7 % del stream_build caliente)
  en estrategia multi-tf; 0 en todo-1m. **Las "velas Nm precalculadas" dejan
  de ser la v1 del PRD.**
- **Los "indicadores" del run frío (2,35 s) eran compilación única del
  proceso**, no cálculo: días siguientes 0,1 ms. En caliente el coste real es
  overhead pandas por llamada (~1-2 ms), no el math → la tabla de indicadores
  fijos tampoco paga sin cambiar el camino de consumo.
- **`fetch` (lectura del stream) es recurrente por run y por mes**: ~0,33-0,9 s
  por mes aunque el proceso ya lo haya leído. 24 meses ≈ 8-20 s por run.
- **La simulación es irrelevante (0,1-0,8 %) y NO es Numba**: el default es
  `BACKTEST_NUMBA_SIM=0` (kernel Python). La casuística "kernel Numba" del
  PRD §2 era errónea para la config por defecto.
- **Extrapolación verificada**: 4.855 pares × ~13 ms + 24 meses × ~0,35 s ≈
  los 86 s medidos el 26/08. El modelo cierra.

**Orden de ataque recomendado (todo ya existe en el repo, gated)**: 1) warmup
de indicadores al arrancar (mata los 2,35 s del 1.er run), 2) `BTT_SLAB_STREAM_ENABLED`
(fetch mensual), 3) path nativo N2a por defecto en estrategias simples (mata
el overhead pandas de translate, ~7 ms/día). Precalculados: solo si tras eso
sigue doliendo, y como columnas por (ticker, día), no como velas Nm.

**De paso**: `origin/feat/resample-memo` YA está contenida en esta rama
(`17fdec3` es ancestro de HEAD) — el PRD §5 lo daba como "candidata a mergear".
Nada que hacer.

Operativa de la sesión: el backend local de Álvaro (8010) se reinició para
arrancarlo con la var del profiler (estaba idle, verificado; `DISABLE_GCS_SYNC=true`
confirmado en el log de arranque). Al terminar se **restauró** el backend
habitual (`--reload`, sin la var) y se verificó sano y sin líneas SUBPHASE.

## 2026-08-27 (noche, 2ª parte) — «Últimas pruebas» en Portfolio: los runs ya no se pierden

Pedida por Álvaro: "que las últimas pruebas se queden guardadas para darles al
click". El diagnóstico: el backend YA auto-guardaba cada backtest exitoso en
`backtest_results` (modo `auto`, retención 50, `f16dfd8`) — lo que se borró el
21/08 (`48abb88`) fue solo la UI («Últimas pruebas» del antiguo Baúl
`/database`). Lo que faltaba: endpoints ligeros y una pantalla.

**Backend** (`strategy_search.py` + `backtest.py`):
- `GET /api/strategy-search/recent` — listado LIGERO (sin `results_json`, que
  en `/list` hace pesar respuestas decenas de MB): metadatos + métricas tipadas
  + label por `json_extract`.
- `GET /api/strategy-search/{id}` — payload completo de un run (incluye
  `backtest_params` + snapshot de `strategy_definition` + `global_equity`).
  Patrón rescatado del router legacy desmontado `_backtest_btt_legacy.py`.
- `_autosave_success` ahora conserva `day_results` (solo dropea
  `equity_curves`): la reapertura muestra calendario y selección de día. Los
  runs guardados ANTES de este cambio no tienen day_results (calendario vacío).

**Frontend**: 4ª sub-pestaña «Últimas pruebas» en `/portfolio`
(`RecentRunsTab.tsx`). Al pulsar «abrir» se pide el payload por id y se
escribe en `sessionStorage['backtester_results_state']` — la clave que
`/backtester` YA restaura al montar — y se navega a `/backtester`: el run se
repinta (métricas/trades/calendario/equity global) sin tocar su página.
Degradación conocida: equity POR DÍA solo mientras el job viva (~1 h).
Borrado con confirmación en dos pasos en la propia fila.

**Fix de paso**: el 503 del guardián de memoria era invisible en la UI — el
catch leía `detail` como string y el guard manda `{code, message}` (objeto).
Nuevo helper `apiErrorMessage` en `backtester/page.tsx` para los dos catches.

**Verificado** (navegador real): tabla con los runs del 27/08, «abrir» →
backtester repinta exactamente las métricas del run (2281 trades / 56,5 % /
PF 1,32 / Sharpe 3,29). Tests: `test_strategy_search_recent.py` (5) +
regresión motor 116 pasan. Nota operativa: el `--reload` de uvicorn se colgó
una vez al recargar con el backend cargado (worker viejo siguió sirviendo);
reinicio limpio del backend si algún cambio no aparece.

## 2026-08-27 (noche, 3ª parte) — Warmup de indicadores + A/B del pipeline slab: -37 % pero DIVERGE

Álvaro pidió "que los backtests vayan más rápido" (su idea: precalcular
gap%/PMH-gap). Con los números del profiler, su idea apuntaba a la fase ya
materializada — el ataque real fue otro:

**Hecho y commiteado — warmup de indicadores al arrancar**
(`indicators.warmup_indicators` + hilo daemon en `main.py`, opt-out
`BTT_INDICATOR_WARMUP=0`): mata los 2,35 s de compilación del primer
ticker-día del primer backtest tras cada arranque. En frío mide 0,5-0,9 s y
corre en background al arrancar.

**A/B/C medido** (enero 2025 del dataset 8777, 81 pares, misma estrategia,
backend reiniciado por condición; logs `ab_a|b|c.log`):

| Condición | Señales | Trades |
|---|---|---|
| A secuencial (defaults) | 1.871 ms | **29** |
| B `BTT_SLAB_STREAM_ENABLED=1` | 1.182 ms (**-37 %**) | **37** |
| C B + `BTT_N2A_NATIVE_ENABLED=1` | 1.214 ms | **37** |

- El pipeline slab (incluso con fetch legacy por no haber slabs construidos)
  es un 37 % más rápido en señales… **pero produce 37 trades donde el
  secuencial produce 29** — paridad rota entre caminos del MISMO motor.
  Sospecha: reentradas/partial-TPs (días con 2 trades). El modo slab además
  rompe el reconciliador de completitud (reporta 0 % porque `_tracked_stream`
  nunca se consume) y con `BACKTEST_STRICT_COMPLETENESS=true` de Álvaro el
  run se rechaza con 503 — el guardián funcionó como debe.
- N2A no se pudo aislar (solo aplica dentro del pipeline slab); mismo 37.

**Plan para staging en `docs/PRD_PERF_BACKTESTS_STAGING_SAILOR_20260827.md`**:
warmup mergeable ya; slab/N2A bloqueados hasta arreglar la paridad (repro
incluido en el PRD). Rechazado con números: velas Nm, tabla de indicadores
fijos y Numba-sim por rendimiento.

Operativa: los reinicios del backend durante el A/B dejaron un worker
huérfano sirviendo con socket heredado (PID muerto en netstat) — matar el
hijo `multiprocessing.spawn` lo libera. Backend restaurado al final
(`--reload`, defaults) y verificado.

## Cambios de sesiones anteriores pendientes de coordinar

- **Comisiones `PERCENT`**: se cobran sobre el NOCIONAL de cada lado
  (entrada + salida), no sobre `|PnL|`. Un breakeven también paga comisión.
- **El Baúl (`/database`) y el `PortfolioBuilder` viejo están borrados** en esta
  rama.
