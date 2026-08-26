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

## Cambios de sesiones anteriores pendientes de coordinar

- **Comisiones `PERCENT`**: se cobran sobre el NOCIONAL de cada lado
  (entrada + salida), no sobre `|PnL|`. Un breakeven también paga comisión.
- **El Baúl (`/database`) y el `PortfolioBuilder` viejo están borrados** en esta
  rama.
