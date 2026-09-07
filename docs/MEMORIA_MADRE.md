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

## 2026-08-27 (noche, 4ª parte) — Guard de SL estructural invalidado + fallback "Previous Max" (Álvaro)

**Bug grave del motor, corregido.** Un hard stop de Market Structure que al
entrar quedaba en el lado GANADOR del precio (ej. corto con el PMH ya roto
porque la acción saltó en RTH) disparaba `high >= SL` en la propia vela y
hacía fill al precio del nivel — fuera del rango de la vela — contando un
beneficio instantáneo imposible. Run manual de RTH 2.3: **540/1.261 trades
eran fills fantasma y aportaban el 87 % del PnL** (WR 70,7 / PF 3,78 →
real: ~49 % / ~1,36). Ejemplo: NITO 2025-01-03, tres cortos a ~3,1 con "SL"
en 2,48 saliendo en 0 velas a 2,48.

**Semántica nueva** (paridad Python↔JIT bit a bit, `dfa6e51`):

- **Guard siempre activo**: nivel invalidado = premisa muerta = **no se
  entra** (corto exige SL > entrada; largo 0 < SL < entrada). Stops
  porcentuales intactos.
- **`hard_stop.fallback_value`** (ej. "Previous Max" = último alto antes de
  entrar, mismo offset): rescata el stop en **reentradas**.
- **`hard_stop.fallback_first_entry: true`**: rescata también la primera
  entrada.
- Si el respaldo también queda invalidado → no se entra. `hard_stop` sigue
  siendo dict libre: cero migraciones.
- NO era look-ahead: `pm_high` ya era causal; el bug era stop en lado
  inválido + fill imposible.

Tocado: `portfolio_sim(_jit).py`, `sim_dispatch.py` (tabla de códigos HS_*
compartida), `backtest_service.py` (secuencial) y `backtest_signals.py`
(slab/paralelo). UI: apartado "Si el nivel ya está rebasado al entrar" en
`RiskManagement.tsx` (desplegable + checkbox, textos por nivel y bias).
`c79993d`: `stop_loss` pintado como línea en el chart de análisis por trade,
regla de medición estilo TradingView, y fix de hidratación de fechas en
`InlineDatasetBuilder` (fechas a nivel de módulo rompían SSR al cruzar
medianoche).

Tests: `test_hs_invalid_sl_guard.py` (30: semántica, espejo largo, paridad
JIT, invariante de lado, 3 e2e por `run_backtest`) + grid de paridad
ampliado con fallback → 37/37 ✓.

**AVISO de comparabilidad**: todo run anterior a esta fecha con SL de Market
Structure está inflado. No comparar curvas nuevas contra runs viejos. PRD
completo para Jaime (con prompt para su IA incluido):
`docs/PRD_GUARD_SL_ESTRUCTURAL_FALLBACK_20260827.md`.

Operativa de esta sesión: el `--reload` de uvicorn VOLVIÓ a no disparar ni
una recarga en todo un log de 9.000 líneas (misma sintomatología que la
nota de la 3ª parte) — tras tocar código backend, reinicio manual
obligatorio; el backend quedó arrancado y verificado
(`DISABLE_GCS_SYNC=true` en el log).

## 2026-08-27 (noche, 5ª parte) — Rescate del indicador Current Gap (%) (Álvaro)

El indicador **Current Gap (%)** de la lógica de entrada (hecho el 18/08,
`6631056`) se quedó huérfano en `alvaro-prereset-8b7959f` cuando la rama se
recreó: no existía en `alvaro-rama-desarrollo`. Rescatado con cherry-pick
(`e04d95e`, autoría y mensaje originales conservados).

Semántica (recordatorio): `Current_Gap[t] = (close[t] − prev_close) /
prev_close × 100` — gap VIVO vela a vela contra el cierre de ayer, a
diferencia de PM High Gap (%) (máximo del premarket congelado a las 09:30)
sigue al precio todo el día y baja si el precio baja. Condición `>= X` solo
cierta en velas que están AHORA a X% sobre ayer. Misma cadena de fallback
de `prev_close` que PM High Gap, evaluación por vela + fill en la apertura
siguiente (look-ahead prevention), paridad legacy (`indicators.py`) ↔
nativa (`strategy_engine._ri_current_gap`, no gatea a legacy).

Conflictos del cherry-pick resueltos en `ConditionBuilder.tsx` e
`indicatorValidation.ts`: HEAD había añadido Squeeze a los mismos checks de
"indicador de porcentaje" donde el commit añadía Current Gap — conviven los
tres (PM High Gap, Squeeze, Current Gap) como standalone con sufijo %.

Verificado: 111 tests en verde (semántica original + paridad N2A del
catálogo completo), tsc limpio, backend reiniciado y con la línea de
seguridad en el log.

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

## 2026-08-29 (tarde) — Cambios entregados en `alvaro-rama-desarrollo` listos para revisión de Jaime → `staging`

> Rama `alvaro-rama-desarrollo` pusheada a origin. NADA de esto está en
> `staging` todavía: si Jaime lo ve adecuado, integra (merge/PR) y pushea.
> El detalle local del incidente que motivó el fix 1 está en la memoria
> local de Álvaro (`.zcode/`, fuera del repo por diseño); aquí solo lo que
> afecta al equipo.

### 1. Commit `9c0cb85` — fix(datasets): rechazar universos sin reglas y acotar pre-cache

Protege la máquina (local y prod) de datasets "universo entero":

- **`POST /api/queries/` con `rules: []` → 422** con mensaje accionable.
  Antes, un dataset sin reglas materializaba TODO el mercado (~1,4M
  pares/año) y su pre-cache streameaba el lago completo en background —
  frames BROAD de 3,3GB por mes en el mismo proceso que los backtests.
- **Cap de pre-cache**: `_precache_dataset_intraday` salta con estado
  `skipped_too_broad` si el dataset supera `PRECACHE_MAX_PAIRS` (env,
  default 50.000). El dataset sigue siendo usable; los backtests traen los
  datos on demand.
- La dedup de `create_saved_query` trata `skipped_too_broad` como
  `completed`: re-guardar filtros idénticos no repaga la materialización.
- `InlineStrategyBuilder`: el alert de error muestra el mensaje real del
  backend (antes era genérico).
- Verificado end-to-end: rules:[] → 422; dataset 1,38M pares → skip sin
  stream; datasets válidos → dedup 200 OK.

### 2. Commit `8063e0a` — feat(universo+metricas): filtros Gap -1 compartidos + rachas por día

- **`qualifying_windows.py` (nuevo)**: definición ÚNICA de columnas LAG 1
  (Gap -1) y LEAD 1/2 (Gap +1/+2) compartida por las tres vías del universo:
  materialización de datasets (`query.py`), qualifying local (`data_service.py`)
  y qualifying GCS (`gcs_cache.py`). Antes una vía podía no materializar la
  columna y la regla se ignoraba en silencio o mataba la query.
- **Guard en `_can_use_hot_cache`** (`data_service.py`): las reglas
  `lead_*`/`lag_*` ya no entran al hot-cache y caen a la vía autoritativa
  (más lenta, correcta). Es el guard fail-safe del HALLAZGO 01 — el fix de
  fondo (evaluar rules tras los shifts) sigue ABIERTO.
- **Wizard/InlineDatasetBuilder**: sección GAP-1 DAY en el configurador
  (métricas `lag_*_1` del día anterior al gap).
- **Métricas nuevas**: `max_consecutive_winning_days` /
  `max_consecutive_losing_days` — PnL diario neto de locates, solo días con
  trades cuentan, día plano (pnl==0) cuenta como perdedor. Y el backtester
  ahora recompute TODAS las rachas en la ventana IS (antes heredaba
  silenciosamente los valores del periodo completo con el filtro activo).
- **Tests**: `test_prev_day_universe_filters.py` +
  `test_daily_streak_metrics.py` — 14/14 pasando.
- `.gitignore`: `/*.log` y `.zcode/` (locales por diseño, dejan de ensuciar
  el status).

### 3. Pendientes conocidos, NO incluidos en estos commits (reportados, sin tocar)

- Cancel de backtest no interrumpe el mes en curso (job "cancelado" sigue y
  compite con el relanzamiento).
- Futures huérfanos del ThreadPool del stream intradía sobreviven al
  abandono del generador (meses BROAD siguen masticando en background).
- GCS listing HTTP 403 reintentado una vez por partición de mes (el fallo no
  se cachea; fallback a disco funciona).
- HALLAZGO 02 (abajo): inconsistencia de semántica de "PM High Gap (%)"
  entre vías del motor.

### [HALLAZGO · 2026-08-29 · 02] "PM High Gap (%)" significa cosas distintas según la vía del motor
- **Reporta:** ZCode (para Álvaro; afecta a todo el equipo)
- **Severidad:** inconsistencia
- **Dónde:** `backend/app/backtester/engine.py:784-797` vs
  `backend/app/services/indicators.py:~1290` y
  `backend/app/services/strategy_engine.py:~160`
- **Qué observé:** la vía `engine.py` calcula PM High Gap como
  `(PMH_final_del_día − apertura_de_ayer) / apertura_de_ayer`, mientras que
  `indicators.py` y `strategy_engine.py` (la vía rápida que corre los
  backtests) usan `(PMH_acumulado_causal − cierre_de_ayer) / cierre_de_ayer`.
  Dos denominadores distintos y PMH final vs corriendo: el mismo número no
  representa lo mismo.
- **Cómo reproducir:** leer las tres implementaciones citadas; contrastar el
  valor de la condición "PM High Gap (%)" de una misma estrategia en cada vía.
- **Evidencia:** código citado (semántica divergente, sin ejecución cruzada
  aún — marcado como inconsistencia estructural).
- **Hipótesis de causa:** HIPÓTESIS — `engine.py` es vía legado que quedó
  sin actualizar cuando el indicador se hizo causal en las otras vías.
- **Impacto:** backtests que pasen por la vía de `engine.py` ven un PMH Gap
  distinto (y con PMH final = look-ahead intradía) que por la vía rápida.
  Además bloquea/confunde el uso de "PM High Gap (%)" como target dinámico
  (gap-vs-gap) hasta que las vías converjan.
- **Código tocado:** NINGUNO (confirmado)
- **Estado:** ABIERTO

### 6. Adoptados los dos commits de Álvaro del 30-ago

Jaume da el visto bueno y entran por cherry-pick suelto (nunca merge de la rama:
son 30 commits con conflicto seguro en el documento). Autoría de Álvaro
conservada.

| Commit aquí | Original | Qué trae |
|---|---|---|
| `e872c70` | `9c0cb85` | rechazar universos sin reglas + cap de pre-cache |
| `54186e2` | `8063e0a` | filtros Gap −1 compartidos por las tres vías + rachas por día |

**El único conflicto fue `docs/MEMORIA_MADRE.md`**, como estaba previsto. Se
resolvió **conservando los dos lados**: las entradas de Álvaro del 29-ago están
ahora al final, bajo una cabecera que explica que llegaron por cherry-pick y por
eso van fuera de orden cronológico.

**Verificación de que no corrompe nada:**
- Los 14 tests que traen sus commits (`test_prev_day_universe_filters.py` y
  `test_daily_streak_metrics.py`): **14/14 en verde** aquí.
- Suite completa antes y después de los cherry-picks: **el conjunto de fallos es
  IDÉNTICO** (los mismos 103, todos dependientes del lago local y de GCS). Los
  pases suben de 384 a 400 = sus 14 tests + 2 míos del modo `full`.
- `tsc --noEmit`: 0 errores.
- Comprobado en la app en marcha: la sección **«GAP-1 DAY»** aparece en el
  configurador de dataset con sus siete métricas (Open price, Open PM price, PM
  High Gap, Premarket total volume, Gap, RTH Total volume, Bar RTH Range).

**Consecuencia que conviene tener presente:** cualquier dataset que use una regla
`Gap −1` deja de pasar por el hot-cache y va por la vía autoritativa, más lenta.
Es deliberado y es lo correcto — por el camino rápido ese filtro **se ignoraba en
silencio** y el universo salía sin filtrar.

**Sigue ABIERTO el HALLAZGO 02 de Álvaro** («PM High Gap (%)» significa cosas
distintas en `engine.py` y en la vía rápida). No se ha tocado: arreglarlo cambia
los backtests viejos, y es una decisión de producto que Jaume no ha tomado.

### 7. RSI y MACD, y dos borrados grandes

**RSI y las tres líneas del MACD, expuestos.** Sorpresa al mirarlo: el backend
**ya los calculaba** —y hasta por la vía rápida— y el gráfico **ya los pintaba**.
Lo único que faltaba era que aparecieran en el desplegable de condiciones. Y
«MACD Signal» / «MACD Histogram» tampoco estaban en el enum del BACKEND, así que
guardar una estrategia con ellos habría devuelto 422 (el fallo de Darvas otra
vez). Las tres líneas son **nombres distintos, no un parámetro**: así las tiene
el motor. `macd_line` de `IndicatorConfig` queda marcado como ajuste fantasma —
no lo lee nadie, no conectarle UI.

**Borrado `app/backtester/engine.py` (1.905 líneas).** Código muerto: nadie
instanciaba `BacktestEngine`, y este documento y dos módulos ya lo decían. Se
van con él siete scripts y dos tests. Lo único vivo que tenía —
`find_elapsed_time_condition/minutes`, que solo leen la definición de la
estrategia— se movió a `backtest_service.py`.

> **Para Álvaro:** con esto, el **HALLAZGO 02** (el «PM High Gap (%)» divergente
> entre vías) **queda cerrado por desaparición de una de las dos vías**. La que
> tenía el look-ahead y el denominador raro era justo `engine.py`. Ya no hay dos
> semánticas: solo queda la causal.
>
> **Aviso honesto:** `swing_option` se queda **sin ningún test**. El que había
> probaba `engine.run()`, o sea una implementación que no se ejecuta — era
> confianza falsa, pero conviene saber que ahora no hay red.

**Borrado el modo Wizard (7.044 + 347 líneas).** Jaume solo usa el modo libre.
«Nueva Estrategia» y «Configurar» entran directos al constructor; desaparecen la
pantalla de elección y el modo `wizard`. Dos detalles que había que atar:

1. Las sesiones guardadas con `mode: 'wizard'` se traducen a `'builder'` al
   restaurar. Sin eso la página quedaría en un modo inexistente y el cajón no se
   abriría nunca.
2. **El tutorial guiado usaba el Wizard en 6 de sus 9 pasos.** No se ha perdido:
   se rehízo sobre el constructor libre con las anclas que este **ya tenía**
   (`st-bias`, `st-sessions`, `st-entry`, `st-risk`), comprobadas en el DOM.

Total del día: **10.400 líneas menos**, sin una sola regresión (mismo conjunto
de 103 fallos de entorno antes y después).

### [HALLAZGO · 2026-08-29 · 02 → RESUELTO POR BORRADO] "PM High Gap (%)" divergente entre vías del motor
- **Reporta/cierra:** ZCode (para Álvaro)
- **Resuelto por:** `92edadc` en `staging` (borrado del motor viejo) + merge `da4a1b7` en `alvaro-rama-desarrollo`. `backend/app/backtester/engine.py` (la vía que calculaba el gap con apertura de ayer + PMH final del día) YA NO EXISTE. Solo quedan `indicators.py` y `strategy_engine.py`, que ya coincidían (cierre de ayer + PMH acumulado causal).
- **Verificación post-merge:** `ls backend/app/backtester/` → solo `__init__.py`, `backtest_validator.py`, `portfolio.py`. Tests del feature Gap -1/rachas: 14/14 pasando sobre el árbol mergeado. Backend reloaded con el código nuevo y API 200.
- **Estado:** RESUELTO (por eliminación de la vía divergente; merge `da4a1b7`)

## 2026-09-01

### Investigación: «Bar Close [t-5] > PM High» — el NÚCLEO evalúa correcto

Petición de Álvaro: «¿es verdad que la condición "bar close 5 velas atrás > PMH"
funciona mal? ¿hay algún bug?». Verificado el camino completo por lectura de
código + repro sintética (`backend/scratch/test_offset_pmh_repro.py`, fichero
efímero de un uso):

- La condición viaja como `source={"name":"Bar Close","offset":5}` vs
  `target={"name":"PM High"}`. `compute_indicator` hace `result.shift(5)`
  (`indicators.py:981`), PMH es el running causal del premarket
  (`_pm_running_series`, congelado tras las 09:30). Con offset la estrategia
  cae SIEMPRE en la vía clásica (`_cfg_native_ok` marca `has_special` en
  `strategy_engine.py:509`; el dispatch nativo ignora el offset, por eso el
  gate). `compile_strategy_def` no pierde el campo.
- Repro 1m día completo (720 barras): señal del motor = `close[i-5] > PMH[i]`
  con **0 mismatches**. Idem sin offset, idem frame solo-RTH (PMH cae a la
  constante de `daily_stats`, causal en RTH), idem a 5m (offset=5 ⇒ 25 min,
  unidades = velas del timeframe de la condición, coherente con el label).

**Conclusión: no hay bug en la evaluación de la condición en sí.** Lo que sí
hay son dos salvedades, registradas como hallazgos abajo: semántica de "vela"
con datos dispersos (01) y contaminación de sesiones en modo swing (02).

### [HALLAZGO · 2026-09-01 · 01] «Bars Back» cuenta FILAS dispersas, no MINUTOS — en premarket la ventana real varía por ticker
- **Reporta:** ZCode (para Álvaro)
- **Severidad:** duda (semántica de diseño, no bug de cálculo)
- **Dónde:** `backend/app/services/indicators.py:981` (`result.shift(offset)`)
- **Qué observé:** `offset` («Bars Back (X)» en la UI, `[t-N]` en el label) se
  aplica con `shift(N)` sobre las filas del df del día. Las velas del lago son
  dispersas (solo minutos con operaciones; documentado para Squeeze en la
  entrada del 2026-08-26: huecos de hasta 37 min en premarket). Resultado: en
  un ticker con huecos, "5 velas atrás" puede mirar el cierre de hace 8, 15 o
  30 minutos de reloj, y la ventana difiere entre tickers y tramos del día.
  Squeeze se resolvió por reloj (asof sobre timestamps) precisamente por esto;
  el offset genérico no.
- **Cómo reproducir:** cualquier condición `Bar Close` con offset>=2 sobre un
  ticker con premarket iliquido; comparar `close.shift(N)` contra el cierre de
  hace N*tf minutos de reloj — divergen en cuanto hay huecos.
- **Evidencia:** repro sintética `backend/scratch/test_offset_pmh_repro.py`
  (datos continuos: 0 mismatches — el shift es correcto por filas); la
  dispersión del lago real está medida en la entrada de Squeeze
  (MEMORIA_MADRE 2026-08-26 §1).
- **Impacto:** si Álvaro lee «5 velas atrás» como «hace 5 minutos», la
  condición parece "funcionar mal" en premarket/illiquidos aunque el motor haga
  exactamente lo que el label dice. En RTH denso casi nunca se nota. Decidir:
  mantener filas (documentar) o pasar el offset a asof por reloj (como
  Squeeze; CAMBIA resultados de estrategias guardadas).
- **Código tocado:** NINGUNO (confirmado)
- **Estado:** ABIERTO

### [HALLAZGO · 2026-09-01 · 02] Modo swing: PMH/PML/RTH-High/Low/Open acumulan A TRAVÉS de los días concatenados
- **Reporta:** ZCode (para Álvaro)
- **Severidad:** inconsistencia
- **Dónde:** `backend/app/services/indicators.py:1123-1171` (`_pm_running_series`/`_rth_running_series` usan minutos-del-día + `fmax.accumulate` sobre el frame ENTERO) + `backend/app/services/backtest_signals.py:450-457` (concat de días del swing)
- **Qué observé:** en swing, `_preprocess_pair` concatena gap-day + días
  posteriores en un solo frame y `translate_strategy` evalúa sobre él. Las
  series de sesión enmascaran por minutos-del-día y acumulan sin cortar por
  fecha: en el día 2, "PM High" vale max(PMH día 1, PMH día 2) — no el PMH de
  NI un día concreto. Ídem RTH High/Low. Las ENTRADAS del día 2+ se suprimen
  (máscara `is_subsequent_np`), pero las SALIDAS y cualquier condición evaluada
  en días posteriores ven la serie mezclada; y `close.shift(5)` en las primeras
  barras del día 2 lee las últimas velas del día 1.
- **Cómo reproducir:** `backend/scratch/test_swing_pmh.py` (efímero): día 1 con
  PMH 10.47 y día 2 con PMH ~10.2 concatenados → `compute_indicator("PM High")`
  en el día 2 devuelve 10.47 (el del día 1); `RTH High` día 2 devuelve el RTH
  high del día 1.
- **Evidencia:** salida del repro: `PMH día2 09:31 = 10.4700` (per-día sería
  ~10.20), `PMH día2 12:00 = 10.4700`, `RTH High día2 12:00 = 10.3200` (es el
  high RTH del día 1).
- **Hipótesis de causa:** HIPÓTESIS — las series de sesión se diseñaron para
  frames de un solo día (el caso no-swing es el 99% del uso) y nadie cortó el
  accumulate por fecha al introducir la concatenación swing. Nota: para un
  swing corto abierto el día del gap, anclar salidas al PMH del DÍA DEL GAP
  sería defendible como semántica; el máx mezclado no corresponde a ninguna de
  las dos lecturas (si el día 2 supera al 1, la serie se salta al PMH del día
  2). Los stops estructurales del simulador (`pm_highs` de `arrays_out`) usan
  la misma serie acumulada.
- **Impacto:** estrategias swing cuyas SALIDAS (o stops de estructura)
  referencien PMH/PML/RTH-High/Low: en días 2+ se comparan contra niveles que
  no son los de ningún día real. Con la condición de esta investigación como
  SALIDA («close 5 velas atrás > PMH») en swing, sí "funciona mal".
- **Código tocado:** NINGUNO (confirmado)
- **Estado:** ABIERTO

### Receta (sin código): setup «First Red Day» — racha de gaps en días PREVIOS al operado

Petición de Álvaro: filtrar que los 2 días anteriores al día operado hayan tenido
cada uno un gap grande (>= 25%). Verificado contra el código (2026-09-01):

- Las `rules` de universo solo tienen LAG 1 filtrable (`lag_gap_pct_1`,
  `lag_pmh_gap_pct_1`, etc., `qualifying_windows.PREV_DAY_LAG_SOURCES`). LAG 2
  existe en stage-2 solo para OHLCV/pm_high (`lag_rth_*_2`, `lag_pm_high_2`),
  NO para gap_pct/pmh_gap_pct → «el gap de hace 2 días» no es regla directa.
- **Inversión del ancla**: anclar el dataset en el ÚLTIMO día de subida T-1
  (rules: `pmh_gap_pct >= 25` + `lag_pmh_gap_pct_1 >= 25`) y poner la estrategia
  `apply_day: gap_1_day` → opera T. `_remap_trading_day` re-escribe
  yesterday_*/rth_*/pm_high/gap_pct al día operado con semántica correcta
  (yesterday_close = cierre de T-1). Selecciona exactamente los mismos días que
  «T-1 y T-2 gappearon y opero T».
- Reglas AND-only: «(gap_pct O pmh_gap_pct) >= 25 por día» NO es expresable en
  un dataset; elegir una métrica o lanzar variantes.
- Precaución look-ahead: postgap_preconditions con `day: 'gap_1_day'` usan la
  métrica DIARIA completa del día operado (cierre de T): como filtro de universo
  en backtest es conocimiento del futuro. El "día rojo" debe decidirse con
  condiciones intradía, no con el cierre.

## 2026-08-31 (tarde) — Bloque «Modelos avanzados»: XGBoost como filtro

Petición de Jaume: poder aplicar un modelo a una estrategia existente y ver el
resultado **fuera de muestra** como si fuera un backtest normal. Modo filtro
terminado; el modo «estrategia» (el modelo decidiendo solo) queda declarado en
la interfaz pero devuelve un aviso de que no está implementado.

### Cómo está montado, y por qué así

**Entrenar y probar son la MISMA `run_backtest`, llamada dos veces con
universos distintos.** De ahí salen tres propiedades sin escribir código:

- Lo que se devuelve —equity, trades, métricas, gráfico— es el periodo de
  prueba y nada más: al motor simplemente no se le dan los días de
  entrenamiento. No hay que filtrar métricas a posteriori.
- El entrenamiento no puede contaminarse: literalmente no ha visto esos días.
- Si alguien cambia el motor, las dos pasadas cambian igual.

Por eso el bloque tiene **sus propias fechas** y no reutiliza el deslizador
IS/OOS del panel: ese reparte UN backtest en dos tramos y las métricas que
enseña son las del IS. La interfaz avisa de que hay que dejarlo al 100 % IS.

**El punto de contacto con el motor es UNO:** una máscara sobre `entries_arr`,
en el mismo sitio donde ya filtra el swing. El modelo solo QUITA entradas,
nunca añade, así que el peor caso posible es operar menos. Simulador, gestión
de riesgo, métricas, gráfico y Walk Forward quedan intactos.

Va **después** del filtro de swing, a petición de Jaume: con swing el frame
abarca varios días y es el swing quien impide abrir en los posteriores. Si el
modelo corriera antes, juzgaría señales que el swing va a descartar igualmente.

### El hallazgo: el HMM de librería tiene look-ahead

`predict` (Viterbi) y `predict_proba` (forward-backward) de `hmmlearn` miran la
secuencia **entera**: el estado que asignan a las 09:35 está calculado sabiendo
lo que pasó a las 15:00 de ese mismo día. **Da igual con qué periodo se haya
entrenado** — el futuro entra por la inferencia, no por el entrenamiento.

Por eso la recursión hacia delante está escrita a mano. Hay un test que lo
demuestra recalculando con el día cortado, y **otro que comprueba que la función
de la librería SÍ falla esa prueba**, para que nadie la sustituya por comodidad
dentro de seis meses.

### Decisiones de diseño que no son evidentes

- **Se eligen indicadores, no rangos.** Encontrar los cortes («RSI > 68 con
  volumen alto») es exactamente lo que hace un árbol de decisión; dárselos
  hechos es hacerle el trabajo peor y le impide encontrar uno mejor.
- **Los niveles de precio entran como distancia en %.** Un VWAP crudo haría que
  el modelo memorizara «18,40 dólares», que no se traslada a otro ticker.
- **Las señales que no llegaron a operarse se descartan**, no se etiquetan como
  perdedoras: «no se ejecutó» no es «salió mal».
- **El recuento de señales vetadas lo lleva el propio modelo**, gratis. Correr
  la prueba otra vez sin modelo solo para restar es un backtest entero más, así
  que esa comparación va apagada por defecto.
- **La configuración se valida antes de cargar un solo dato**, y sus errores van
  como 400 con el texto: el diagnóstico del frontend pinta los 5xx como
  `Response Data: {}` y parecen un error mudo.

### Tiempos, medidos

El modelo es prácticamente gratis; **el coste es el lago**. XGBoost con 1.000
operaciones tarda 0,13 s; el HMM sobre un millón de velas, 15 s; la inferencia
por vela, 0,2 ms. **Un backtest con modelo ≈ 2× uno normal**, por las dos
pasadas.

### Verificación y dependencias

30 tests nuevos. Suite completa sin regresiones, `tsc` limpio, bloque
comprobado en la app. **No se ha corrido todavía un backtest real de punta a
punta** con el bloque activo (hace falta dataset y minutos de lago).

Tres dependencias nuevas: `xgboost`, `scikit-learn`, `hmmlearn`. Comprobado con
un simulacro previo que **no tocan numpy, pandas ni scipy** — solo añaden.

### Lo que falta

1. El modo «estrategia» (standalone).
2. **Persistencia del modelo entrenado.** Hoy se entrena en cada backtest, así
   que una estrategia guardada con modelo no puede reproducir un run viejo.
   Haría falta versionar los binarios y que la estrategia guarde el id.

### Modo «estrategia» completado, con guardas

Jaume fijó la especificación y es la buena: **el stop lo pone él, no el modelo.**
El etiquetado (`label_triple_barrier`) simula desde cada vela con **su** stop y
**su** take profit —los mismos valores que `_parse_risk_management` le entrega
al simulador, no una interpretación aparte— y mira qué pasa primero: toca
objetivo (buena), toca stop (mala), o se acaba el plazo (el signo de lo que
llevara). Empate en la misma vela: gana el stop, que es lo pesimista.

**Por qué no el atajo fácil.** La tentación es etiquetar con «¿subió un X% en N
minutos?». Eso **ignora el camino**: una vela desde la que el precio primero cae
un 20% —stop saltado, estás fuera— y luego sube saldría marcada como BUENA. El
modelo aprendería a buscar justo esas y en real comerías stop tras stop mientras
el backtest presume de aciertos. Hay un test dedicado a ese caso concreto.

**Las guardas, que también las pidió él.** En modo «estrategia» el backtest se
para ANTES de cargar un solo dato si están activas la lógica de entrada, la de
salida, la piramidación o el swing: todas ponen entradas, y el resultado sería
una mezcla de dos sistemas de la que no se sabría de quién es el mérito. El
mensaje dice cuál sobra y ofrece la alternativa. Y se exige un stop configurado.

**Lo que sí se respeta, tal cual:** stop, take profit total y parcial, trailing,
salida por hora, límite de pérdida diaria, reentradas, locates, comisiones y
slippage. Lo aplica el simulador de siempre, exactamente igual que en cualquier
otra estrategia.

**Una decisión que se tomó sin preguntar, por si algún día chirría:** las
SALIDAS no las da el modelo, vienen de la gestión de riesgo. Un modelo de salida
necesitaría su propia etiqueta («¿fue bueno salir aquí?»), que es un segundo
problema de modelado entero.

**Dos detalles de implementación que no son evidentes:** el motor se salta los
días sin señales, y en este modo no hay señales de las reglas — ese atajo se
desactiva solo en este modo. Y el día se **muestrea** (~120 velas de las ~700)
para entrenar: con miles de días, guardarlas todas son cientos de megas y la
vela 301 no enseña nada que no enseñara la 300.

## 2026-08-31 (noche) — Auditoría del bloque de modelos: DOS fugas, resultados inválidos

Jaume corrió un backtest con el modelo y los números salieron «una auténtica
locura». Pidió auditoría antes de creérselos. **Tenía razón: había dos fallos
reales**, los dos introducidos con el bloque el mismo día. La auditoría se hizo
primero en SOLO LECTURA (reproducciones contra el código instalado, sin tocar
un fichero, con un backtest suyo aún en cola) y después se aplicaron los
arreglos. Commit `09db5f7`.

### Fuga 1 — el HMM sabía el volumen del futuro (la que infló la curva)

`hmm_observations` normalizaba el volumen de cada vela por la **media del día
entero** (`np.nanmean`). La vela de las 07:00 quedaba escalada por el volumen
que llegaría por la tarde. Medido con dos días idénticos hasta la vela 330 (uno
con spike de volumen posterior, otro sin él): **la probabilidad de estado que ve
XGBoost en la misma vela difiere hasta en 0,86** de un máximo de 1.

En este universo eso no es un matiz: el volumen total del día es LA información
(¿va a ser un pump monstruo o va a morirse?). El modelo la explotaba y el
backtest salía espectacular — e irreproducible en vivo, porque a las 07:00 ese
dato no existe. Arreglo: volumen relativo a la **media acumulada hasta t**.

### Fuga 2 — con sesión RTH, las etiquetas se emparejaban con la vela equivocada

Los hooks del modelo corrían **antes** del recorte de sesión: la señal quedaba
indexada sobre el día completo (premarket incluido) y el trade del simulador
sobre el frame recortado — ~330 velas de desfase. Las parejas señal-trade no se
encontraban nunca, **sin error y sin aviso**: el modelo entrenaba con parejas
rotas o descartaba casi todo. Arreglo: los hooks van después del recorte y del
`candle_delay` (mismo espacio de índices que los trades), las features se siguen
calculando sobre el día completo, y la máscara de sesión traduce entre los dos
espacios.

### Blindaje adicional

- **Slab y paralelo quedan excluidos cuando hay modelo**: sus caminos no tienen
  los hooks y lo habrían ignorado en silencio (un resultado etiquetado como
  «filtrado» sin haber filtrado nada).
- Test de causalidad **de punta a punta**: el score completo (features + HMM +
  XGBoost) del día cortado en la vela k coincide con el prefijo del score del
  día entero. Más los dos tests de regresión de cada fuga.

### La regla que queda

> **Cualquier backtest con modelo anterior a `09db5f7` es inválido.** Con HMM
> activado llevaba la fuga 1; con sesión recortada, la 2. Re-lanzar.

### El motor principal, verificado intacto

Sin el bloque, `parse_config` devuelve `None` y la llamada a `run_backtest` es
idéntica a la de siempre. Suite completa: el mismo conjunto de 103 fallos de
entorno que antes de que el bloque existiera (comparado en cada paso). Y en
verde, nombrados: `sim_jit_equivalence`, `n2a_native`, `n2a_e2e`,
`current_gap`, `fade_indicators`, `max_reentries`, `daily_loss_limit`,
`daily_limit_sequential`, `locates`, `pm_lookahead` — **157 tests del camino
secuencial de punta a punta**.

---

## 2026-09-01 — Bot de alertas en vivo, y `staging` igualada a `sailor`

### 📣 Para Álvaro: `staging` se ha reiniciado hoy

`staging` apunta ahora a `93da17d`, el mismo commit que
`sailor-rama-desarrollo`. **No se ha perdido trabajo:** los 8 commits que
`staging` tenía y `sailor` no (el borrado del motor viejo, RSI/MACD, «% Session
Fade», los filtros Gap−1, el fix de datasets y los dos de memoria) **ya estaban
en `sailor` con otro hash** — se habían subido por las dos vías. Se comprobó uno
a uno por mensaje antes de forzar.

Etiqueta de rescate en el remoto, por si acaso:
`staging-antes-del-reinicio-2026-09-01` → `9ba2308`.

### Lo que trae esta sesión: el bot de alertas

Proyecto **propio de Sailor**, aislado del producto: un bot que lleva las
estrategias del portfolio a avisos en tiempo real por Telegram y a una página
nueva (`/bot-alertas`). Ejecución manual — el bot avisa, la orden la mete una
persona.

**Casi todo es código nuevo y separado** (`bot_alerts_*.py`, `market_frame.py`,
`CuadroMandos.tsx`). Solo tres cosas tocan lo existente:

1. **`backtest_service.py`, −58 líneas.** La fórmula que construye el frame
   (HOD/LOD, máximos de premercado acumulados, Previous Max/Min) se extrajo a
   `app/services/market_frame.py` porque el bot la necesita igual y la tenía
   COPIADA fuera del repo. **El comportamiento no cambia**: verificado idéntico
   bit a bit —los 15 arrays, 150 ticker-días, 76.385 barras— y con la suite
   completa antes y después (455 pasan / 103 fallan / 13 errores, los mismos).

   > `backtest_signals._compute_signals_for_pair` conserva SU versión en numpy
   > puro. **No se unificaron a propósito**: son fórmulas distintas de lo mismo
   > (`cummax` de pandas vs `np.maximum.accumulate`, que difieren ante NaN) con
   > su paridad ya verificada aparte. Fundirlas sería un cambio de
   > comportamiento disfrazado de limpieza.

2. **`main.py` y `Sidebar.tsx`**: registrar la página nueva. Inocuo.

3. **Borrado de la página del Screener** (`Screener.tsx` y su ruta, −2.078
   líneas). ⚠️ **Ojo, Álvaro:** el screener figura en todos los planes de
   `entitlements/policy.py`. Se retiró porque en esta línea de trabajo no se usa
   y Sailor lo decidió así. **El SERVICIO se conserva**
   (`live_screener_service.py` y `/api/screener/live`): mantiene por ticker el
   cierre de ayer, el máximo de premercado y el volumen acumulado desde el
   WebSocket, que es justo lo que necesita el bot. **Si esto llega a producción,
   hay que reponer la página.**

### Dos hallazgos que valen para todo el proyecto

**El volumen del WebSocket por segundo se queda corto.** Construir velas sumando
los agregados `A` da los precios bien pero **al volumen le falta entre un 1,5 %
y un 4,6 %** (medido con AAPL/TSLA/NVDA/SPY): el proveedor cuenta operaciones
—bloques fuera de secuencia, lotes sueltos— que no aparecen ahí. Hay que usar
`AM`, el agregado por minuto, que llega ya cerrado y oficial: 20 velas, 20
idénticas al REST. Importa para cualquier cosa que decida con volumen.

**`get_user_db_connection(read_only=True)` ignora el parámetro** y abre todas
las conexiones en escritura (`database.py:11-15`). Como DuckDB solo admite un
escritor, **una página que consulta cada 2 s bloquea las escrituras**: medido,
un POST esperando más de 60 s hasta agotar el tiempo, y con la página cerrada
0,2 s. Y si se llenan los hilos del servidor esperando, **deja de responder a
todo, incluido `/docs`**, aunque el proceso siga vivo — eso es lo que parecía
que el backend «se caía». Aquí se resolvió con caché en memoria; **cualquier
módulo nuevo que consulte a menudo se va a encontrar lo mismo.**

### Documentación

`docs/BOT_ALERTAS_MODOS_DE_FALLO.md` — mapa de caídas, decisiones de diseño y
lo que hará falta antes de conectar la API de un bróker (reconciliación,
idempotencia de órdenes, interruptor de emergencia). Se escribió pensando en esa
conversación futura.

---

## 2026-09-02

### 🚨 AVISO PARA ÁLVARO Y SU IA — Alertas es zona cerrada

**El bot de avisos en vivo y la página de Alertas los llevan Jaume y Sailor en
exclusiva por ahora. No se tocan, no se arrancan, no se configuran y no se
descargan para probarlos.** Está también como regla de oro nº 6 en `AGENTS.md`,
en `CLAUDE.md` y en `.agent/ALVARO_DEV_BRANCH.md`, con la lista de ficheros.

No es celo de código. Son tres razones concretas y ninguna se arregla teniendo
cuidado:

1. **Opera con dinero real.** Los avisos salen a un grupo de Telegram y Jaume
   pone las órdenes a mano con ellos. Un cambio que altere una condición no
   rompe un test: le hace entrar en una operación que no era.
2. **La cuenta de datos en vivo admite UNA sola conexión.** Arrancar el bot en
   otra máquina **echa al de Jaume y lo deja sordo**, sin que ninguno de los dos
   vea un error — el bot sigue diciendo «conectado». Pasó hoy mismo con una
   prueba de nada.
3. **Está en desarrollo activo** y sin cobertura suficiente. Lo que parece
   código muerto o mejorable suele ser una decisión medida, y el porqué está en
   los comentarios.

**Traerlo por `staging` no es tocarlo**: esos ficheros llegarán en el merge y no
hay que hacer nada con ellos. La única excepción de lectura/escritura es
`backend/app/services/market_frame.py`, compartido a propósito con el backtester
(fórmula verificada bit a bit sobre 150 ticker-días): leerlo, sin problema;
**cambiarlo, avisando antes**, porque mueve las señales en vivo aunque los
backtests sigan en verde. Si algo de Alertas bloquea una tarea legítima, se
habla con Jaume — la decisión es suya, no del agente.

### El radar vigila las condiciones de CADA estrategia, no un umbral inventado

**Cómo estaba mal.** El radar filtraba por el precio ACTUAL contra el cierre de
ayer, con un umbral puesto a ojo (30 %). Pero `PM High Gap %` —la condición de
1B— es un **máximo acumulado que no baja**. Un ticker que hizo +80 % y retrocedió
a +22 % sigue cumpliendo, y el radar lo descartaba. En gaps en corto retroceder
tras el máximo es lo NORMAL: el fallo afectaba al caso típico, no a uno raro.

**Cómo está ahora** (`bot_alerts_mercado.py`, `bot_alerts_universo.py`,
`RadarPorEstrategia`): el bot se suscribe a `AM.*` (mercado entero), acumula por
ticker máximo de premercado, volumen y precio, y evalúa **el filtro de universo
de cada estrategia activa**. Admitido un ticker, no sale hasta cambiar de día.
Cada candidato lleva de qué estrategia viene y por qué regla.

**Lo que se puede y no se puede saber antes de las 09:30:** `PM High Gap %`,
`Current Gap %`, `Premarket Volume`, `Volume`, `Price` y `Previous Close`, sí.
**`Open Gap %` NO existe antes de la apertura**, así que 2.1B y 3B no son
vigilables en premercado — y el bot lo dice al arrancar en vez de ignorarlas en
silencio. Lo que no se sabe calcular se declara NO EVALUABLE y el ticker no
entra: dar por cumplida una condición sin comprobarla haría avisar de lo que no
toca.

**Bug grave arreglado: el cierre de ayer.** El bot llamaba a
`build_market_frame` con `daily_stats` VACÍO, y el código cae a un valor de
emergencia: **usa el primer precio de hoy como cierre de ayer**. Sin error, sin
log. Medido con SGLD: PM High Gap salía 50,4 % cuando el real era 525 %.
Arreglado pidiendo el snapshot (`prevDay.c`). **Verificado que `prevDay.c` es el
cierre RTH y no el after-hours**: SGLD cerró RTH en 5,08 y after-hours en 17,30;
el campo da 5,08.

### Prealertas: la vela se mira cada segundo del 50 al 59

El backtest entra al `open` de la vela siguiente a la señal, o sea en el instante
en que la vela de señal cierra. Avisar al cierre deja **margen cero** para poner
la orden a mano. La prealerta evalúa la vela a medias y avisa antes.

Estaba mirando **una sola vez**, en el segundo 50. Eso dejaba escapar las señales
que se completan después, y ésas llegaban al cierre sin margen. Medido sobre el
tick data del lago:

| | captura | margen | falsas alarmas |
|---|---|---|---|
| solo el segundo 50 | 12/14 (86 %) | 10 s | 3 de 8 |
| del 50 al 59 | **14/14 (100 %)** | 9,4 s de media, 6 s el peor | 3 de 9 |

Captura todas, el margen apenas baja y **no añade falsas alarmas** — el riesgo
era una condición que se cumple en el 52 y deja de cumplirse en el 58, y no pasó
ni una vez en 2.959 velas de premercado. El máximo sigue siendo 10 s; el peor
caso teórico es 1 s, pero medido ninguna bajó de 6.

**Detalle de implementación que parece menor y no lo es:** el minuto se marca
como avisado desde **el bot, al publicar**, no dentro de `aplicar()`. Marcarlo
dentro haría volver a mirar una sola vez, y **no lo notaría nadie**: el bot
seguiría avisando, solo que menos. Hay tests que lo fijan
(`backend/tests/test_bot_alerts_prealertas.py`), incluido uno para que un mismo
aviso no se repita ocho veces en el minuto.

**El volumen de la vela parcial sale de `av`, no de sumar los `v`.** Sumar los
agregados por segundo deja fuera operaciones (hasta un 4,6 % menos) y 1B decide
con dollar volume acumulado. `av` es el volumen acumulado del día, ya oficial:
restándole el que había al empezar el minuto sale el del minuto exacto. Si no
viene `av` el volumen se declara 0 en vez de aproximarlo — un volumen corto haría
cumplir la condición más tarde de lo que toca, y eso es peor que no prealertar.

### Dos cosas que valen para cualquiera que trabaje en este repo

**Editar código del backend con `--reload` puesto tumba lo que dependa de él.**
Cada fichero guardado reinicia uvicorn; durante el reinicio devuelve 500 y luego
deja de aceptar conexiones unos segundos. Los «cuelgues del backend» que se
llevaban investigando días eran esto, provocado desde el propio editor.
Confirmado por descarte: cuatro horas sin un solo error en cuanto se dejó de
tocar código, con el bot procesando 528 velas.

**Un comentario no es una garantía.** `hidratar()` decía «no genera avisos: lo
que ya pasó, pasó» y no estaba implementado: el bot avisó a las 20:28 de
operaciones de las 14:27 y salieron a Telegram. Está arreglado (se llama al
motor con el frame hidratado y se descartan los eventos, para marcarlos como
vistos), pero la lección es general.

## 2026-09-02 — Merge de `staging` en `alvaro-rama-desarrollo` SIN el bot de alertas

Merge de `origin/staging` (`6db5a36`, staging reescrita sobre la historia de
sailor el 2026-09-01). Trae: bloque «Modelos avanzados» (XGBoost+HMM, modo
filtro), el fix de las DOS fugas de la auditoría (`09db5f7`), modo
«estrategia» con guardas, `market_frame.py` (fórmula del frame extraída de
`backtest_service`, compartida con el bot), y las entradas de memoria de
Sailor/Jaume.

**Decisión de Álvaro: el bot de alertas queda EXCLUIDO de esta rama** (zona
cerrada de Jaume/Sailor, ver `AGENTS.md` § zona cerrada). Excluidos del merge y
a excluir también en futuros merges de staging: `backend/app/services/bot_alerts_*.py`,
`backend/app/routers/bot_alerts.py`, `backend/tests/test_bot_alerts_*.py`,
`frontend/src/app/bot-alertas/`, `frontend/src/components/bot-alertas/`,
`frontend/src/lib/api_bot_alerts.ts`, `docs/BOT_ALERTAS_MODOS_DE_FALLO.md`.
También se revirtió el registro del router en `main.py` y el link del Sidebar.
Se CONSERVA: `market_frame.py` (lo importa `backtest_service`), el servicio del
screener y **la página del Screener** (staging la retiró como parte del proyecto
del bot; sin el bot, Álvaro se queda con el Screener).

Conflictos resueltos: `backtest_service.py` (import de `market_frame`, lado
staging) y esta memoria (ambos lados conservados). Lo nuestro que staging no
adoptó se conserva solo (warmup de indicadores, splits en `init_db.py`
con `LAKE_PREV_CLOSE_YA_AJUSTADO`, «Últimas pruebas» en Portfolio,
`subphase_profiler.py`): staging no lo tocó desde la base del merge.

## 2026-09-02 (2ª sesión) — Retirada de la página del Screener (cambio de decisión)

Álvaro decide que la página del Screener no le hace falta ahora mismo. En el
merge de esta mañana se había CONSERVADO a propósito (staging la retiró como
parte del bot de alertas, que aquí está excluido); ahora se retira también aquí,
alineando la rama con staging en este punto:

- `frontend/src/app/screener/page.tsx` y `frontend/src/components/Screener.tsx`
  movidos a `_archive/frontend-screener-20260902/` (no borrados, regla de oro 5).
- Link del Sidebar retirado (con comentario explicativo in situ).
- El SERVICIO backend se conserva intacto (`live_screener_service`,
  `/api/screener/live`, `/api/screener/daily`): igual que en staging. El
  endpoint de DATOS `/market/screener` lo siguen usando Ticker Analysis
  (`page.tsx` home) y `analysis/[ticker]/[date]` — NO tocar.
- Verificado: `tsc --noEmit` 0 errores, `GET /screener` → 404, `/` → 200.

## 2026-09-03 — Descarga de trades en CSV en la pestaña Trades del Backtester

Petición de Álvaro: quería recuperar la "opción de descargar en CSV los trades
de una estrategia". Investigado el historial completo (todas las ramas, reflog,
commits colgantes, pre-Wizard, develop/main): esa opción NUNCA existió en la
app — lo que existía era (a) su script propio `analisis/paso2_estrategia_fade_pm.py`
que exporta trades con pandas, y (b) el export de datos de mercado de la home,
llevaba oculto desde la época MVP (`HIDDEN FOR MVP`, `page.tsx:232`). Así que
se implementa de cero:

- Botón "CSV" (icono download) en la cabecera de la pestaña Trades, junto a
  los totales. Exporta TODOS los trades del run en orden cronológico (no la
  ventana filtrada de la tabla). Sin backend: serializa en cliente.
- Formato pensado para analizar después: separador ';' + decimales con punto +
  BOM UTF-8 + CRLF (Excel-ES con doble clic, pandas con `sep=';'`). Una sola
  fila de cabecera, sin bloques de resumen.
- 22 columnas: nº, ticker, fecha ISO, día de la semana, dirección, hora
  entrada/salida, duración en minutos, tamaño, precio entrada (fill real y
  precio medio — difieren con piramidación), precio salida, stop loss, PnL,
  comisiones, retorno %, R, MAE %, MFE %, gap %, motivo de salida, ejecuciones.
  Precios/tamaños a 4 decimales sin ceros de relleno (hay tickers subdólar).
- Nombre de fichero: `<estrategia>_trades_<n>_<fecha-hora>.csv` (el nombre lo
  pasa ResultsTabs desde `activeStrategy`).
- Verificado: `tsc --noEmit` 0 errores; la lógica exacta del builder ejecutada
  contra los 2.799 trades reales del run auto-guardado 3aff85df (Definitiva
  2.3): 2.799 filas, 22 columnas, 0 filas rotas.

## 📣 2026-09-03 — Para Jaime: botón «CSV» en la pestaña Trades (REPORTE — solo en rama de Álvaro)

> Petición de Álvaro. **NADA de esto está en `staging`**: ni pusheado a la rama
> remota, ni PR, ni merge. Vive SOLO en `alvaro-rama-desarrollo`, commit
> `0e14921`. La integración a `staging`, por PR, cuando Álvaro/Jaime lo decidan.
> Este reporte viaja en la memoria para que quede constancia del cambio.

**Qué se ha hecho.** Botón «CSV» (icono descarga) en la cabecera de la
pestaña Trades del Backtester, junto a los totales. Exporta TODOS los trades
del run en orden cronológico (no la ventana filtrada de la tabla), generado
íntegramente en cliente — **sin cambios de backend**.

**Por qué.** Álvaro recordaba una opción así pero nunca existió en la app: se
buscó en todas las ramas (incluidas backups de Álvaro), reflog, commits
colgantes, pre-borrado-del-Wizard, `develop` y `main` — nada. Lo que existía:
su script propio `analisis/paso2_estrategia_fade_pm.py` (export con pandas) y
el export de datos de mercado de la home, oculto desde la época MVP
(`HIDDEN FOR MVP`, `page.tsx:232`). Así que se implementó de cero.

**Ficheros tocados (solo 2 + esta memoria):**
- `frontend/src/components/backtester/tabs/TradesTab.tsx` — builder del CSV,
  botón y descarga (Blob en cliente).
- `frontend/src/components/backtester/ResultsTabs.tsx` — pasa el nombre de la
  estrategia para el nombre del fichero (una línea).

**Formato del CSV** (pensado para analizar después): separador `;` + decimales
con punto + BOM UTF-8 + CRLF → Excel-ES con doble clic, pandas con `sep=';'`.
22 columnas con unidades en cabecera: nº, ticker, fecha ISO, día de la semana,
dirección, hora entrada/salida, duración (min), tamaño, precio entrada (fill
real Y precio medio ponderado — difieren con piramidación), precio salida,
stop loss, PnL, comisiones, retorno %, R, MAE %, MFE %, gap %, motivo de
salida, ejecuciones. Precios/tamaños a 4 decimales sin ceros de relleno
(tickers subdólar). Fichero: `<estrategia>_trades_<n>_<fechahora>.csv`.

**Verificación.** `tsc --noEmit` 0 errores. El builder exacto ejecutado contra
los 2.799 trades reales del run auto-guardado `3aff85df` (Definitiva 2.3):
2.799 filas, 22 columnas, 0 filas rotas.

**Para revisar (Jaime):** `git show 0e14921` en la rama de Álvaro cuando esté
pusheada — el diff es pequeño y autónomo (no toca motor ni backend).

### [HALLAZGO · 2026-09-04 · 01] «Nueva Estrategia» hereda los parámetros del borrador anterior — el fix de Adrian (fdb0b7c) se perdió con el reinicio de staging
- **Reporta:** ZCode (para Álvaro)
- **Severidad:** bug
- **Dónde:** `frontend/src/app/backtester/page.tsx`, handler `onNewStrategy` (~línea 1293): el reset de `activeStrategy`/`builderDraft`/`draftStrategy` está tras el gate `if (hadSavedOrLoaded)`.
- **Qué observé:** con un BORRADOR sin guardar como estado previo, pulsar «Nueva Estrategia» NO limpia nada y el constructor abre con los parámetros de la estrategia anterior. Con una estrategia guardada cargada sí resetea (por eso en la verificación del 2026-09-03 no se vio: arrancó con «Estrategia 1B» auto-cargada).
- **Cómo reproducir:** Backtester → crear/modificar una estrategia SIN guardar (borrador) → pulsar «Nueva Estrategia» → el constructor abre heredando los parámetros del borrador en vez de en blanco.
- **Evidencia:** el código actual es idéntico (en lógica) al pre-fix de `fdb0b7c` (Adrian Garcia, 2026-08-21, «fix(backtester): "Nueva Estrategia" arranca siempre en blanco (Config. libre heredaba la anterior)», reportado por cliente). Ese commit está en `main` y `develop` pero NO en `staging` ni en `alvaro-rama-desarrollo` (verificado con `git merge-base --is-ancestor`): el reinicio de staging del 2026-09-01 (base sailor) no descendía de él.
- **Hipótesis de causa:** la reconstrucción de staging desde `sailor-rama-desarrollo` dejó fuera fixes de la línea develop/main; este es uno (puede que no el único — merece un barrido `git log main ^staging` para ver qué más se perdió).
- **Impacto:** UX confusa y riesgo de correr backtests con parámetros heredados sin querer. Afecta a staging y a la rama de Álvaro por igual.
- **Arreglo conocido:** adaptar `fdb0b7c` — quitar el gate y resetear SIEMPRE al abrir (el diff original refería modos `builder_choice`/`wizard` que ya no existen; hay que adaptarlo a `builder`/`config` actuales). Decisión de Álvaro: aplicarlo en su rama o pedirlo a Jaume para staging.
- **Código tocado:** NINGUNO (confirmado)
- **Estado:** ABIERTO

### [HALLAZGO · 2026-09-04 · 01 → FIX EN RAMA ÁLVARO] «Nueva Estrategia» heredaba el borrador anterior
- **Aplica/cierra (en esta rama):** ZCode con OK explícito de Álvaro. Adaptación del fix original de Adrian `fdb0b7c`: fuera el gate `hadSavedOrLoaded` — al ABRIR «Nueva Estrategia» se resetea SIEMPRE (`activeStrategy`/`builderDraft`/`draftStrategy`/`loadedStrategyId` a null → modo `builder`); si ya estaba abierto, colapsa a `config` como antes. Mismos pasos que el fix de Adrian, sin las referencias a `builder_choice`/`wizard` (modos ya borrados).
- **Verificación:** `tsc --noEmit` 0 errores. Repro visual no posible en esta sesión (navegador embebido inestable): verificada la lógica por lectura — el reset ya no depende de `loadedStrategyId`, así que el caso "borrador sin guardar" queda cubierto igual que el de estrategia guardada. Pendiente confirmación de Álvaro en uso normal.
- **Sigue ABIERTO PARA `staging`** (y por tanto para producción vía develop→main si el fix no se recoge allí): la línea sailor/staging no contiene `fdb0b7c` ni este cambio. Que Jaume lo recoja de aquí o reaplique `fdb0b7c` adaptado.

### [HALLAZGO · 2026-09-04 · 02 → FIX EN RAMA ÁLVARO] Tras «Nueva Estrategia» el desplegable conservaba el último nombre — segunda cara del fix perdido
- **Reporta/aplica:** ZCode (para Álvaro, con su OK de continuar el fix en su rama). Mismo origen que el 01: el reset de la página no alcanzaba al estado INTERNO de `BacktestPanel`.
- **Dónde:** `frontend/src/components/backtester/BacktestPanel.tsx` — el efecto que sincroniza `activeStrategy` → `selectedStrategy` solo cubría el camino de CARGA (prop con id); cuando «Nueva Estrategia» pone `activeStrategy=null` (+ `builderDraft=null`, ver `computedActiveStrategy`), el panel conservaba su `selectedStrategy` anterior y el desplegable seguía mostrando «Estrategia 1B» (y su resumen debajo).
- **Fix:** (1) rama `else` en el efecto — si la prop queda sin id y había ref previa, `setSelectedStrategy("")` y ref a null (guardado por la ref, no toca la restauración de sessionStorage ni el borrador `[Borrador]` id="draft"); (2) opción placeholder `value=""` ("cargar estrategia guardada…") en el `<select>` cuando no hay selección — sin ella el navegador pintaba la primera estrategia como si estuviera elegida.
- **Casos borde verificados por lectura:** restauración de sesión (ref vacía al montar → no limpiado espurio), borrador nuevo (id "draft" → rama if intacta), edición de guardada (el draft conserva el id real → sin cambio), corrida de borrador → vuelve a `[Borrador]` como antes.
- **Verificación:** `tsc --noEmit` 0 errores. Confirmación visual pendiente de Álvaro (navegador embebido inestable en esta sesión).
- **Sigue ABIERTO PARA `staging`** junto al 01.
- **Código tocado:** solo `BacktestPanel.tsx` (en rama de Álvaro, como el del 01)
- **Estado:** ABIERTO (para staging) / arreglado en rama Álvaro

## 📣 2026-09-04 — Para Jaime: modo «R» en el Calendar del Backtester (REPORTE — solo en rama de Álvaro)

Petición de Álvaro: ver el calendario de resultados en múltiplos de R, no solo
en dinero. **Solo en `alvaro-rama-desarrollo`** (sin push a staging/PR/merge
por ahora); commit de referencia en la rama.

**Qué se ha hecho.** Cuarto modo de vista «R» en la pestaña Calendar
(`CalendarTab.tsx`, solo frontend): junto a Profits / Gastos / Profits−Gastos.
Muestra la SUMA de `r_multiple` por día/semana/mes (mismo criterio que el pnl
neto: sin locates, `r_multiple` del trade). Formato «+1.25R» / «-0.32R»,
coloreado verde/rojo por signo igual que los modos monetarios, tooltips del
día y de la semana con el valor en R, y totales mensuales en R. Los gastos
fijos mensuales NO se mezclan en este modo (no tienen sentido en múltiplos de
R). El modal de detalle del día sigue mostrando PnL $ y avg R por trade, que
ya los tenía.

**Verificación.** `tsc --noEmit` 0 errores. Cálculo replicado contra los 2.799
trades reales del run `3aff85df`: 393 días con trades, suma por día = R total
del run (150.57R), coherencia exacta.
---

## 2026-09-03 / 04

Sesión larga: el bot operó en vivo por primera vez y de ahí salieron dos bugs
del MOTOR (no del bot) que afectan a cualquier backtest con piramidación.

### 1. ⚠️ BUG DEL MOTOR: las pirámides se saltaban `entry_time_windows`

**Afecta a todo backtest con piramidación y ventana de entradas.** La ventana se
aplicaba solo a `entries`; `_evaluate_pyramid_levels` no la miraba, así que un
nivel podía disparar a cualquier hora de la sesión.

Visto en vivo el 3-sep: GELS piramidó a las **08:08 ET** teniendo la ventana de
entradas cerrada a las 08:00. Jaume confirmó que esa ventana es global —
entradas **y** pirámides.

Medido sobre un frame de prueba: **59 señales de pirámide fuera de ventana
antes, 0 después**, y las 241 legítimas intactas. Sin `entry_time_windows` nada
cambia.

> **Los resultados guardados de estrategias con pirámide + ventana ya no
> coinciden.** No es opinable: era un bug.

### 2. Stop híbrido: tercer modo de dimensionado

Además de valor de mercado y distancia al stop. Va por SL, pero topando la
exposición:

```
techo en dólares = (% de cuenta asumible × capital) / % del evento
```

Resuelve el punto ciego del modo por SL: con el stop muy ceñido el tamaño se
dispara. Medido — cuenta de 10.000 $, riesgo 300 $, stop al 1 %: **30.000
acciones, tres veces la cuenta expuesta**; un hueco del 1.000 % en contra deja
debiendo dinero. Con techo al 50 % ante un evento del 1.000 %, esas 30.000 se
quedan en 500. **Recorta, no anula.**

**El techo es de VALOR, no de acciones.** Con 100 $ de techo se compran 100
acciones a 1 $ pero 200 a 0,50 $. Confundirlo multiplica la exposición por el
precio.

Los dos porcentajes viven en la **estrategia** (decisión de Jaume: afecta
directamente al resultado del backtest); el **capital**, en el cuadro de mandos
del bot, que no conoce la cuenta real. Se aplica por separado a entrada y a
pirámide, cada una con sus porcentajes.

**⚠️ Aviso para quien toque el motor: el kernel Numba NO implementa el techo.**
Una estrategia híbrida se rutea SIEMPRE al motor Python, igual que se hace con
la piramidación. Sin ese ruteo, y con `BACKTEST_NUMBA_SIM=1`, el techo se pierde
**en silencio** en todo backtest sin pirámides.

### 3. La pirámide tiene ahora su propio modo de tamaño

Independiente del de la entrada: un añadido puede ir por distancia al stop
aunque la entrada vaya por valor de mercado. **El mismo añadido sale a 3, 150 o
5 acciones según el modo** — hasta ahora iba siempre por valor de mercado y no
había forma de cambiarlo.

Esto salió de una observación de Jaume en vivo: con el mismo stop, su pirámide
arriesgaba **146 $ donde la entrada arriesgaba 300 $**, porque una se
dimensionaba por stop y la otra por capital.

### 4. Rolling EV: el modo «días» hacía MEDIA DE MEDIAS

Sacaba el EV de cada día y promediaba esos EV, así que **un día con una
operación pesaba igual que uno con diez**:

| | |
|---|---|
| lunes: 1 trade que gana 1,0R | EV del día `+1,000 R` |
| martes: 10 trades de −0,2R | EV del día `−0,200 R` |
| modo DÍAS (media de medias) | **`+0,400 R`** |
| modo TRADES (los 11 juntos) | **`−0,091 R`** ← el real |

Cambiaba **el signo**: un mes de días flojos con una ganadora suelta se pintaba
como rentable. Ahora la ventana de N días coge todas las operaciones de esos
días. El modo por trades ya era correcto y no cambia (verificado: diferencia 0).

### 5. Bot de alertas

- **Prealertas del segundo 50 al 59** (antes solo el 50). Medido sobre tick
  data: de 86 % a 100 % de captura, margen de 10 s a 9,4 s de media.
- **Prealertas huérfanas arregladas**: los agregados por segundo tardan ~3 s, así
  que el tick del segundo 59 llegaba DESPUÉS de cerrar su vela y nadie la
  confirmaba ni descartaba — se quedaba en ámbar para siempre.
- **El bot ya ESCUCHA**: `/evf TICKER COSTE EV%` por Telegram dice si compensan
  los locates. Solo responde al chat configurado, los comandos solo LEEN, y
  nada de lo que llegue puede tumbar el bucle de velas.
- **Desplegable de condiciones** en el cuadro de mandos: lo que el motor aplica
  DE VERDAD, incluida la configuración guardada que NO se usa y por qué. Sobre
  la 1B real saca tres: trailing y swing (con su `active: false`, inofensivos) y
  **dos take profit parciales que se encenderían cambiando OTRO campo**.

### 6. Auditoría del guardado de estrategias: es FIEL

A petición de Jaume. Round-trip sobre la 1B real: **370 campos, 0 perdidos, 0
inventados, 0 alterados**. El guardado no corrompe nada. Lo que faltaba era
poder **ver** qué parte de lo guardado está viva — de ahí el desplegable.

### Dos cosas que valen para cualquiera en este repo

**El patrón de las TRES CAPAS sigue mordiendo.** Se documentó en §4 de este
mismo documento y aun así se volvió a caer en él el mismo día: se escribió el
código que LEE cuatro campos nuevos y no el que los ESCRIBE. Un `lv.get("x")`
que siempre devuelve `None` no falla, no avisa, y no sale en los tests que no lo
cubren. Salió en una auditoría posterior, no en la suite.

**`r_multiple` viene REDONDEADO A DOS DECIMALES.** Cualquier cálculo que
compare márgenes finos (un fade del 1,19 % contra un EV del 2,4 %) tiene que
salir de `entry_price`/`exit_price`, no de ahí.

---

## 2026-09-04 (tarde/noche) — Prealertas medidas, dos bugs silenciosos y el genético ampliado

Sesión de después del cierre. Lo importante son **tres bugs que no daban ningún
error** y un estudio que cambia un parámetro que llevaba semanas puesto a ojo.

### 1. La ventana de la prealerta pasa del segundo 50 al 44

Medido sobre 30 días y 33 entradas de tick data, más 25.408 mensajes de latencia
del feed en vivo. Dos cosas que no se sabían cuando se eligió el 50:

- **La señal se cumple mucho antes de lo que se creía.** Mediana en el
  **segundo 17**, y 9 de 33 ya cumplían en el 5. Se esperaba al 50 para ver algo
  que en la mitad de los casos llevaba treinta segundos hecho.
- **La latencia se come el margen.** El agregado por segundo tarda ~3,7 s de
  mediana (p99 4,1 s, con un pico de **9,8 s**). Un aviso del segundo 50 no daba
  los 10 s que prometía: daba **7,8 s** hasta la alerta de verdad, y 0,2 s en el
  pico.

| ventana | margen mediana | de cada N avisos, 1 opera |
|---|---|---|
| 50-59 | 7,8 s | 2,3 |
| **44-59** | **13,8 s** | **3,6** |
| 30-59 | 27,8 s | 4,5 |

La captura NO cambia (32 de 33 en todas): lo único que se compra adelantando es
tiempo. Se eligió el 44 y no el 30 —que es donde el estudio pone el óptimo—
porque la cuenta de falsas del estudio no cuadró con el primer día en vivo
(predecía ~4 y hubo 0), así que el número absoluto no es de fiar todavía.

Tres cosas que ninguna ventana arregla: 4 de 33 señales se cumplen de verdad
tarde (segundos 54, 55 y 59) y llegarán siempre con menos de 5 s; una de ellas
llega después que su propia alerta y la descarta `marcar_cerrada`.

El medidor quedó en `D:\bot_senales\medir_ventanas_comparadas.py`.

### 2. `MACD Signal` y `MACD Histogram` eran SIEMPRE NaN

`_ema_core` siembra con la media de los primeros `window` valores. Sobre precios
está bien, pero también se aplica a la SALIDA de otro indicador: la señal del
MACD es una EMA de la línea MACD, y esa empieza con `slow-1` NaN (25 con el 26
por defecto). La suma salía NaN, la siembra salía NaN, y como cada valor depende
del anterior se propagaba hasta el final:

    MACD            -> 275 valores de 300
    MACD Signal     ->   0 de 300
    MACD Histogram  ->   0 de 300

Una comparación contra NaN da False, así que **cualquier estrategia con «MACD
Signal» o «MACD Histogram» no operaba nunca**, sin error ni log. Al DI+/DI− del
ADX le pasaba lo mismo. Arreglado saltando los NaN de cabecera antes de sembrar;
sin NaN el resultado es idéntico. Comprobado contra la batería entera: arregla 2
tests y no rompe ninguno.

### 3. El What-if recortaba trades sin que nadie se lo pidiera

`dd_threshold` venía por defecto en 5 y `size_mgmt_type` en `"dd"`, y la página
no manda ninguno de los dos. Resultado: **toda simulación, sin marcar nada,
recortaba a la mitad el tamaño de cada trade abierto con más de un 5 % de
drawdown encima**. Según dónde cayeran las pérdidas eso podía MEJORAR la curva —
y entonces el What-if «sin filtros» salía mejor que el original, que es
imposible. Lo detectó Jaume mirando la pantalla, no la suite.

La regla que faltaba, ahora fijada con un test: **un What-if sin opciones
devuelve la curva de partida**. Al apagarlo salió un segundo fallo que el
default tapaba: la media del modo `sma` se calculaba también en modo `dd`, y con
período 0 dividía entre cero.

### 4. Un backtest que falla dejaba el dataset BLOQUEADO

Son dos almacenes. El POST siembra `backtest_progress[dataset_id]` en `running`
antes de lanzar el hilo, pero el estado del job vive en `backtest_jobs`, y al
fallar solo se actualizaba ese. Si el job moría pronto —definición mal formada,
falta de memoria— ese `running` se quedaba para siempre y todo intento posterior
devolvía `already_running` apuntando a un job muerto. **Solo se arreglaba
reiniciando el backend.** Encontrado por accidente midiendo el consumo de RAM.

### 5. Genético: de 7 indicadores a 26, y las ramas que no se probaban

Catálogo agrupado en seis familias con pestañas y ayuda por indicador. **Por
defecto siguen marcados solo los siete de la v1**: los demás están para elegir,
no para llevarlos todos.

Y el hallazgo, que salió de una pregunta de Jaume: **el lado DERECHO de las
condiciones se armaba con `params: {}`**, sin sortear nada. Mientras los niveles
eran precios sueltos (VWAP, PM High) no se notaba; al meter Darvas, Donchian,
Bollinger, SMA y EMA, todos habrían salido siempre con el periodo por defecto y
la banda de arriba — ofrecer «Darvas Box» habría sido ofrecer «Darvas por arriba
con 3 velas».

Preguntó si pasaba con más, y pasaba: MACD iba siempre con 12/26/9 y las
Bollinger con 2 desviaciones. Auditado indicador a indicador contra el motor y
convertido en test permanente, que ahora lo detecta solo.

**El test no lo caza todo, y conviene saberlo:** compara sobre una serie
sintética, y los cinco parámetros de los triángulos salían «sin efecto» ahí
porque esa serie no llega a formar triángulos. Los añadió Jaume de memoria.

Nuevo en riesgo: stop híbrido, stop mínimo %, take profit mínimo % y take
profits parciales con las tres variantes del motor. Ojo con `take_profit_mode`:
el motor **ignora `partial_take_profits` en modo "Full" en silencio**.

### 6. Bot de alertas: `/estado` y el diario

`/estado radar` y `/estado TICKER` en Telegram, de solo lectura. Y un **diario**
al final del cuadro de mandos con las incidencias y el log, con botón de copiar:
va enganchado al logger RAÍZ, así que recoge lo que registre cualquiera —el
socket, httpx, un error sin capturar— sin ir añadiendo llamadas.

### Lo que vale para cualquiera en este repo

**Tres de los cuatro bugs de hoy no daban ningún error.** Una condición contra
NaN, un default que nadie manda, un `params: {}` vacío: ninguno lanza, ninguno
aparece en un log, y los tres cambian resultados que se miran para decidir con
dinero. El patrón se repite — lo que no falla ruidosamente hay que buscarlo a
propósito.

**El backend hay que arrancarlo con el venv**, no con el Python global: le falta
`jose` y revienta al importar, pero el error solo sale en stderr y parece que se
cuelga. Y `--reload` no recoge los cambios de forma fiable si queda un proceso
viejo con el puerto.

### 7. Calendario del backtester: en dinero o en R

Los tres modos de siempre (profits, gastos, profits−gastos) se pueden leer en
dólares o en múltiplos de riesgo. Son DOS EJES, no un cuarto modo.

Con riesgo FIJO, 1 R es el «Riesgo fijo $» del panel. Con riesgo PORCENTUAL —que
al principio dejé fuera de más— la R no desaparece, cambia: el motor arriesga
ese % del balance de **apertura del día**, así que 1 R es constante DENTRO de un
día y solo cambia de un día a otro. Es la misma cuenta que ya hacía `r_precise`
en `robustness_service.py`, verificada allí contra una corrida real.

La conversión va POR DÍA, no al pintar: la R de una semana es la suma de las R
de sus días. Con 10.000 $ al 2 % y tres días de +200/−100/+450 salen 2,738 R
sumando por día y 2,750 R dividiendo al final, y esa diferencia crece con la
cuenta.

No se usa `r_multiple` del trade: así los GASTOS también se leen en R, y se
evita arrastrar su redondeo a dos decimales.

**Aviso:** Jaume pidió traer esto de la rama de Álvaro, pero NO está en el
remoto — el `CalendarTab.tsx` es idéntico en `sailor`, `staging` y
`alvaro-rama-desarrollo`. Lo tendrá en local. Esto está escrito de cero y puede
quedar distinto a lo suyo.

### 8. Dos parciales no pueden caer en el mismo sitio

Primera corrida del genético con los take profits parciales puestos, y salió
esto: `Parciales: 25% a las 12:00, 33% a las 12:00`. El motor los aplica en
orden, así que el segundo salta justo detrás del primero: cierra más posición de
golpe y gasta un gen en algo que no añade ninguna decisión. Corregido.

---

## Pendientes para el 2026-09-05

1. **Ver la ventana 44-59 en vivo.** Es su primer premercado. Medir cuántas
   prealertas se confirman y cuántas no: el estudio predice ~2,7 avisos en balde
   por cada bueno, pero su cuenta de falsas NO cuadró con el día 4 (predecía ~4
   y hubo 0), así que el número absoluto está por confirmar. Si el ruido es
   tolerable, el siguiente escalón es 40-59 (17,8 s de margen).

2. **Auditar el calendario en R** con datos reales. Quedó sin verificar en
   pantalla —el genético tenía la máquina— y Jaume quiere repasarlo.

3. **El aviso de cancelación de la prealerta.** Ahora una prealerta solo se
   confirma o descarta al CERRAR la vela; si la señal se rompe en el segundo 50
   se sigue mirando el gráfico sin saberlo. Avisar en el momento en que se cae
   convertiría el ruido de adelantar la ventana en información, y es lo que
   haría cómodo bajar al 40 o al 30.

4. **Los 119 tests que fallan**, que siguen ahí y son de antes de esta sesión.

5. **Del genético:** `parar_a_las` no venía configurada en la corrida de la
   noche del 4 — con el bot de alertas arrancando a las 10:00 (hora española)
   hay que ponerla siempre. Y con `min_trades` a 1.000 los individuos daban
   fitness 0 con 729 trades: un suelo por encima de lo que el dataset da deja al
   genético sin gradiente, todo a cero y cruzando al azar.

---

## 2026-09-06 — Sesión personalizada, ventana de entrada y barrido por franjas

Reportado por Jaume sobre `RTH prueba 1`: «le pongo sesión personalizada y horas
de entrada y no me hace caso — salen trades a las 15:30 y barras de EV hasta las
13:30». Diagnosticado sobre la corrida real guardada (2.688 trades, 11:46).

### 1. La sesión personalizada NO se ignoraba: se SUMABA

La definición tenía `market_sessions: ['rth', 'custom']` con custom 04:00-12:00.
El motor hace la **unión** de todas las sesiones marcadas
(`_get_market_sessions_mask`, `mask |= ...`), así que la sesión efectiva era
04:00-16:00. De ahí los 1.077 cierres en la hora de las 15: son EOD en la última
vela de RTH.

No era un bug del motor sino del selector: cuatro casillas independientes en las
que «Horas personalizadas» convivía con «Regular Hours» sin que nada avisara.
**Ahora «Horas personalizadas» es EXCLUYENTE** con pre/rth/post en
`InlineStrategyBuilder`. Y para las estrategias ya guardadas con las dos
marcadas, el resumen de `BacktestPanel` pinta un aviso rojo con la sesión REAL
(«se suman: 04:00-16:00»), porque hasta ahora leía «Personalizado (04:00-12:00)»
mientras el backtest corría hasta las 16:00.

### 2. BUG DEL MOTOR: la ventana de entrada no miraba la vela de RELLENO

`entry_time_windows` se aplicaba a la vela de la **señal**, pero con
`look_ahead_prevention` el simulador compra en la apertura de la vela
**siguiente** (`eff_entry_idx = i + 1`, `portfolio_sim`). Nadie comprobaba el
reloj ahí.

En un ticker líquido eso es un minuto de desfase. En los **warrants con velas
dispersas** —una vela por minuto NEGOCIADO, no por minuto de reloj— la "vela
siguiente" a las 11:29 podía ser la de las 13:45. Con ventana 09:30-11:30 la
corrida tenía 41 entradas en el cubo de las 11:30 (casi todas las 11:31) y 5
sueltas a las 12:11, 12:30, 13:01 y 13:45. Ninguna daba error ni salía en ningún
log: el patrón de `btt-bugs-que-no-dan-error`.

Corregido con `strategy_engine.apply_entry_fill_window`, llamada **después** del
recorte de sesión y del `candle_delay` (el único espacio de índices en el que
`i + 1` es de verdad la vela de compra), en los dos sitios que generan señales:
`backtest_service` (secuencial) y `backtest_signals` (paralelo + slab). Se
aplica también a las pirámides, por la misma regla de 2026-09-03: un añadido es
una entrada.

**Ventana ESTRICTA por decisión de Jaume:** si el límite está en 11:30 y la
señal salta en la vela de 11:30, la compra caería en la de 11:31 y NO se coge.
Esto retira también las entradas de 11:31. Impacto en PnL de aquella corrida:
1,6 $ sobre 354 $ — corregirlo no cambia la estrategia, cambia que el gráfico
deje de mentir sobre a qué hora se entra. **Las corridas anteriores al 6-sep no
son comparables con las nuevas.**

De paso, las tres copias del bucle que parseaba `from_time`/`to_time` (legacy,
nativo N2a y la nueva) se unificaron en `build_entry_time_mask`.

### 3. Los límites horarios ya se pueden OPTIMIZAR

`entry_logic.entry_time_windows.N.from_time` / `.to_time` no aparecían en el
optimizador 3D: los valores son texto («09:30»), `float()` revienta y `_add` los
descartaba sin decir nada. Ahora se extraen como parámetros `time_of_day` (se
barren en minutos desde medianoche, ±2 h recortado a 04:00-20:00, paso 5) y al
escribir cada punto se devuelven como «HH:MM» — `_needs_hhmm_reencode` amplía lo
que antes solo hacía el take profit por hora. El frontend no necesitó cambios:
`unit === "time_of_day"` ya pintaba selectores de hora.

### 4. EV barriendo la ventana de entrada (gráfico nuevo)

El gráfico «EV por Tiempo» agrupa los trades QUE HUBO por su hora de entrada; si
hay límite horario, fuera de él no hay nada que ver. Se añade un conmutador
**Trades / Barrido**: el segundo lanza un backtest por franja (09:30-10:00,
10:00-10:30…) y compara el EV de cada una — `EntryWindowSweepChart`.

Va por el mismo motor que el optimizador, con un añadido general a `ParamConfig`:
**`linked_paths` / `linked_offsets`**, un eje que escribe además en otras rutas
sumándoles un desplazamiento. Así la ventana se mueve DE UNA PIEZA con una sola
dimensión de rejilla: N corridas, no N². Sin esas claves el comportamiento de un
eje es exactamente el de siempre.

También se hizo **recursiva la limpieza de NaN** del resultado: solo se limpiaba
la rejilla de 2 dimensiones, y con 1 eje los `NaN` salían crudos — `NaN` no es
JSON válido y el navegador reventaba al parsear, sin ningún error en el backend.

### 5. MEDIDO: el 29 % de los trades son WARRANTS, y pierden

Los tickers de la fuga (ONMDW, ISPOW, GMBLW, RVSNW…) son warrants. Cruzando los
2.688 trades contra `massive.tickers`:

| tipo | trades | % | PnL |
|---|---|---|---|
| CS | 1.748 | 65,0 % | +426,79 |
| **WARRANT** | **776** | **28,9 %** | **−62,14** |
| ADRC | 119 | 4,4 % | +6,04 |
| RIGHT / ETF / UNIT / PFD / ETS | 32 | 1,2 % | −12,14 |
| sin referencia | 13 | 0,5 % | −4,09 |

El 31,6 % de los trades NO son acción común, y entre todos restan ~77 $ de un
resultado de 354 $. `daily_metrics` no lleva columna de tipo de instrumento, por
eso entran; pero la vista `massive.tickers` (ticker, name, type) YA está
registrada en el DuckDB del backend (`database.py`) y en el lago local, así que
el filtro es viable sin infraestructura nueva. **Pendiente de decidir con Jaume**
si va como filtro de universo opt-in o como default, y qué se hace con los
tickers sin referencia. El screener en vivo y `bot_alerts_radar` ya filtran por
`TIPOS = ("CS", "ADRC")`.

### 5b. IMPLEMENTADO el mismo día: filtro de tipo de instrumento

Decisión de Jaume: **por defecto para todas las estrategias**, tipos permitidos
`CS` + `ADRC` (los mismos que el screener en vivo y `bot_alerts_radar`), y los
tickers **sin fila en la referencia se QUEDAN** — la referencia es de hoy y un
ticker legítimo deslistado en 2024 no tiene fila; excluirlos sería un sesgo de
supervivencia al revés.

`data_service._filtrar_tipo_instrumento`, aplicado en `fetch_qualifying_data` —
el envoltorio cacheado — en sus **tres** salidas (acierto de Redis, acierto de
disco y cálculo). Va DESPUÉS de cachear a propósito: la caché guarda el universo
crudo, así que la escotilla `BACKTEST_ALLOW_ALL_INSTRUMENT_TYPES=1` sigue
funcionando sin invalidarla y una caché escrita antes de hoy también se filtra.

La referencia se lee una vez y se cachea en proceso, con tres intentos:
`massive.tickers` → `tickers` → el parquet del lago con una conexión DuckDB **en
memoria propia** (si el fallo es que el lago está abierto por otro proceso,
`get_db_connection` fallaría también en el respaldo). **Si no se puede leer, NO
se filtra** y se loguea en ERROR: quedarse sin referencia no puede vaciar el
universo en silencio.

⚠️ Esto cambia el resultado de TODAS las corridas anteriores al 2026-09-06.

### 5c. El filtro llega también al buscador y a los datasets

Jaume: «que los oculten porque no voy a operar nunca un warrant». La MISMA
función (`_filtrar_tipo_instrumento`) se aplica ahora en tres sitios, no en tres
copias de la regla:

1. `fetch_qualifying_data` — el universo del backtest.
2. `routers/data.py` `/api/data/filter` — el buscador de tickers. Va **antes**
   de `get_dashboard_stats` y de la serie agregada, para que la tabla y las
   métricas de arriba cuadren entre sí. Esa consulta no lleva `LIMIT`, así que
   filtrar sobre el resultado es exacto.
3. `routers/query.py` `_compute_dataset_pairs` — los pares (ticker, día) de un
   dataset, tras el `drop_duplicates`.

**Lo que NO se tocó, a propósito:** `/api/data/tickers` (el autocompletado de la
referencia) sigue devolviendo todo — se usa también para mirar un ticker suelto
en Análisis, donde ver un warrant no molesta.

⚠️ **Los datasets ya creados guardan sus pares en `dataset_pairs` y siguen
contando los días de warrant.** El backtest ya no los opera (lo filtra el
qualifying), pero el número de días del selector no bajará hasta que el dataset
se vuelva a crear. El genético no se ve afectado: usa `qualifying.feather`, que
sale de `fetch_qualifying_data` (ver el comentario de `_escribir_qualifying`).

---

## 2026-09-06 (tarde) · Locates en el calendario, suelo de precio y lectura neta del barrido

### 6. El calendario era la ÚNICA vista que ignoraba los locates

Jaume: «veo que de mayo a junio he ganado dinero y en la curva de equity con
gastos claramente estoy perdiendo». No era impresión suya. Medido sobre su
corrida, el desfase entre el calendario y la curva era **exactamente el coste de
locates, mes a mes y al céntimo**:

| mes | calendario | curva c/gastos | desfase | locates |
|---|---|---|---|---|
| 2026-01 | +427,27 | +139,27 | 288,00 | 288 |
| **2026-05** | **+195,82** | **−188,18** | **384,00** | **384** |
| 2026-06 | +4.823,65 | +3.849,65 | 974,00 | 974 |
| 2026-08 | +3.161,50 | +2.531,50 | 630,00 | 630 |

Causa: `CalendarTab` construía sus casillas con `t.pnl`, que es el PnL **antes**
del alquiler de acciones — el locate viaja aparte porque se cobra una vez por
ticker-día, no por operación. La curva de equity con gastos sí lo descuenta, y
el `total_pnl` que reporta el motor también (11.698,79 − 3.604 = 8.094,79). El
calendario era el único sitio que no.

**Los gastos fijos SÍ estaban** — si hubieran faltado, el desfase de mayo habría
sido 684 y no 384.

Ahora: «Gastos» = comisiones + locates + fijos; «Profits - Gastos» = pnl −
locates − fijos; «Profits» sin tocar (bruto antes de costes). Verificado contra
`global_equity_expenses`: **cuadra al céntimo en los nueve meses**.

Matiz de atribución: al repartir el locate por operación, un día con varias
entradas en el mismo ticker puede cargárselo entero a una de ellas. Los totales
de día, semana y mes son exactos; el reparto intradía es aproximado.

### 7. Suelo de precio en el universo: 0,10 $

`universe_filters.min_price` / `max_price` están declarados en el esquema y la
interfaz los enseña, pero **`_build_where_clause` nunca los ha leído**: no han
filtrado nada jamás. Misma familia que los 45 filtros del buscador.

Por eso el suelo va aparte y siempre activo (`_filtrar_precio_minimo`), medido
sobre `open` — la primera cotización del día, que es **causal**; usar `close` o
`high` sería mirar el futuro. Los días sin precio se quedan, igual que los
tickers sin ficha. Escotilla `BACKTEST_MIN_PRICE=0`.

Las dos reglas del universo viven ahora en `_filtrar_universo`, que usan el
backtest, el buscador y los pares de un dataset. Para los pares, `open` viaja en
el SELECT y se descarta después (`dataset_pairs` solo guarda ticker+date).

Lo motivó la operación de OPPr a $0,0005: 636.873 acciones y 6.369 $ de locates
sobre una posición de 300 $, que se llevó 7.000 $ de una cuenta de 10.000.

### 8. Barrido de EV: lectura BRUTA y NETA

`expectancy` del motor divide el PnL **antes** de locates: 46,42 $ frente a
32,12 $ reales en la corrida de Jaume, un 45 % de más. Se añade `total_pnl` al
detalle de cada punto de la rejilla y un conmutador **Bruto / Neto** en el
gráfico. **El defecto se queda en Bruto** a propósito, por petición explícita de
no cambiar lo que ya había; el globo enseña las dos lecturas más el dinero total
de la franja. Ninguna de las dos lleva los gastos fijos del mes.

### 9. Espaciado del barrido

Los conmutadores `Trades / Barrido` y `15m/30m/60m/120m` estaban pegados entre sí
y al borde de su caja, y los minutos se leían como un continuo. `gap-1`,
`p-[3px]` y más ancho interior; `Barrer`/`Cancelar` con margen a los lados.

---

## 2026-09-06 (noche) · El genético gana un segundo modo: MEJORAR una estrategia

Petición de Jaume: «el genético busca estrategias, pero ¿podría optimizar UNA
con todos sus parámetros? En el 3D optimizo uno o dos; ¿y si tiene cinco o
seis? Quiero la combinación más ROBUSTA, no la que más dinero da». Y una
condición: **el modo explorador no se toca, se le añade otro al lado.**

### 10. Dos especies de cromosoma, un solo motor

`genetico/especie.py` decide, según `config["modo"]`, qué módulo provee
`aleatorio / mutar / cruzar / huella / receta / a_definicion`:

    explorar (por defecto) -> cromosoma.py   el de siempre, intacto
    mejorar                -> afinar.py      NUEVO

**Por qué un cromosoma nuevo y no reutilizar el del explorador.**
`cromosoma.a_definicion()` va en un solo sentido y hardcodea `exit_logic: None`,
`postgap_preconditions: None`, `apply_day`, `timeframe: 1m` y trailing/swing
apagados. Convertir una estrategia hecha a mano a ese cromosoma le arrancaría la
mitad de su definición **en silencio**. En `afinar.py` el individuo ES la
definición: se parte de la semilla intacta y solo se escriben las rutas
marcadas. Hay un test por cada cosa que debe sobrevivir.

Los genes salen de **`extract_parameters`**, el mismo del optimizador 3D — ya
sabe leer los indicadores y sus parámetros con rango, paso y unidad — y se
escriben con `_set_nested_value`, que reescribe "HH:MM" donde toca. Se le añaden
los que ese extractor no cubre: **sesión de mercado** (un gen categórico que
escribe tres claves) y **reentradas**. Comprobado sobre `RTH prueba 1`: saca el
objetivo del % Fade, el del Elapsed Time, el periodo Y el objetivo del RVOL, las
dos puntas de la ventana horaria, stop, take profit, reentradas y sesión.

**El rango lo elige el usuario**, como en el 3D; el backend solo propone ±2
escalones.

### 11. La robustez es un EJE APARTE, no otra métrica

Dos desplegables en vez de uno: **qué mides** (los mismos EV·√N, PF, Sharpe… del
explorador) y **cómo lo agregas**:

- `valor` — lo de siempre, y el defecto.
- `peor_trozo` — parte el IS en tramos con el mismo número de días de mercado y
  puntúa con el peor. **No cuesta ni un backtest más**: una corrida ya devuelve
  el día a día.
- `media_menos_sigma` — media − λ·σ entre tramos.
- `vecindario` — el «robust plateau» del 3D en N dimensiones, usando los
  individuos YA evaluados de la caché. También gratis.

La agregación solo se ofrece en modo mejorar. El explorador no la ve y su
`config` no la lleva, así que corre exactamente igual que antes.

### 12. Tres trampas que se cerraron por el camino

**La sesión la pisaba el panel.** `evaluador.parametros_backtest` pasa
`market_sessions` a `run_backtest` **por argumento**, y el argumento gana sobre
la definición. En modo mejorar eso habría hecho que la corrida entera evaluara
el horario del explorador en vez del de la estrategia — y sin ningún error. Con
definición, ahora mandan la definición y sus genes (también `size_by_sl` y el
stop híbrido).

**`mutar` podía devolver un clon.** El `tocado = True` marcaba «lo intenté», no
«cambió», y `_vecino` sortea de toda la rejilla un 30 % de las veces. Un clon ya
está en la caché, así que la generación se quedaba sin individuos nuevos que
evaluar y el genético se estancaba sin dar ni un aviso. Lo cazó
`test_mutar_siempre_cambia_algo`.

**Las guardas y el operador OR.** En modo mejorar las guardas fijas se meten
delante de la lógica de entrada, pero solo si la raíz es un AND: colarlas dentro
de un OR las convertiría en «o esto o la guarda», lo contrario de una guarda. Si
la raíz es OR, se envuelve en un AND.

### 13. Otras decisiones

- **La definición se CONGELA al lanzar** (`estrategia_base` en el `config.json`
  de la corrida). Si el usuario edita la estrategia a media noche, los
  individuos ya evaluados y los que quedan partirían de bases distintas.
- **La generación 0 lleva la estrategia TAL CUAL** como línea base, más
  mutaciones suyas de radio creciente (60 % del cupo) y luego aleatorios. Sin la
  línea base no se puede saber si el genético ha mejorado algo.
- Todos los genes empiezan **desmarcados**: marcar por defecto sería mover cosas
  que nadie ha pedido.

25 tests nuevos en `test_genetico_afinar.py`. 731 en total, `tsc` limpio.

### 14. Modo mejorar, segunda tanda: parciales variables, pirámide y dataset

**Parciales como ESTRUCTURA, no solo como número.** Petición de Jaume: «quiero
probar qué pasa si añado 3 o 5 parciales, ya sea por hora, minutos o distancia…
aunque modifique la estrategia». Se resuelve con dos tipos de gen:

- `parciales.n` — cuántos niveles (0 a 5). Cero es una opción legítima: es la
  comparación contra no ponerlos.
- `parciales.{i}.nivel` — un gen CATEGÓRICO por nivel, con la lista completa de
  disparadores (`pct:6`, `hora:10:30`, `tiempo:30`) construida con las mismas
  rejillas que usa el explorador.

Encajarlo así, y no como cuatro genes por nivel (tipo + valor% + valor hora +
valor minutos), lo deja en 1 + N casillas en vez de 1 + 4N, y hace que «un
escalón» signifique algo para la mutación.

**El capital se reparte a partes iguales** y el último se lleva el resto: el
motor exige que sumen exactamente 100 % o deja posición sin cerrar. Repartir así
lo garantiza sin meter N dimensiones más de sobreajuste; para repartos
desiguales están los genes de ruta `partial_take_profits.i.capital_pct`.

**Si hay estructura, las rutas de parciales se ignoran.** No es solo evitar que
dos genes se peleen: `_encode_tp_value` relee la forma NUEVA, así que escribir
un 6 sobre un nivel recién puesto a `"HOUR:10:30"` daría `"HOUR:00:06"` — un
disparador que nadie ha pedido, sin ningún error.

**PIRAMIDACIÓN: `extract_parameters` no la miraba.** Una estrategia con pirámide
tenía sus niveles congelados tanto en el genético como en el optimizador 3D. Se
conservaban (la definición se copia entera) pero no había forma de moverlos, y
el tamaño de un añadido pesa tanto como el de la entrada. Ahora salen tres
cosas por nivel: `capital_pct`, `times` y los umbrales de SU condición, que van
por la misma maquinaria que las de entrada y salida. **Esto también se lo lleva
el optimizador 3D**, que hasta hoy tampoco podía tocar una pirámide.

**El dataset lo trae la estrategia.** Al elegirla en modo mejorar se carga solo
su `dataset_id`. Elegirlo a mano era una forma fácil de evaluar la estrategia
sobre otro universo del que se construyó y no enterarse: el número sale, solo
que no es el de esa estrategia. Se puede cambiar después, y si se cambia, la
página avisa. Si la estrategia no tiene dataset guardado (usa filtros de
universo), lo dice y no toca nada.

740 tests (34 en `test_genetico_afinar.py`), `tsc` limpio.

### 15. La sesión, en tres genes (no en una casilla)

Jaume, sobre la primera versión: «me refería a elegir entre qué horas quiero que
mire, quizás quiero ver si cerrando a las 11 es mejor que a las 12; si solo
puedo poner tick en sesión de mercado no sé qué baremos está usando». Tenía
razón: con un solo gen categórico de sesión eso no se puede barrer.

Ahora son tres: `__sesion_tipo__` (categórico), `__sesion_desde__` y
`__sesion_hasta__` (horas, en minutos desde medianoche, con rango y paso como
cualquier otro gen). Reglas, cada una tapando un agujero:

1. Si el gen de TIPO está marcado, manda él.
2. Si NO lo está pero sí alguna HORA, la sesión pasa a personalizada. Dejarla en
   RTH haría que el barrido no cambiara nada: N corridas dando el mismo número,
   sin error.
3. La punta que no se barre se queda en la que tenga hoy la estrategia.
4. Fuera de personalizada las horas se BORRAN (el lío de la unión de sesiones).
5. Un cierre anterior a la apertura recorta el día a cero velas: el genético lo
   descarta solo (nota 0), pero no se escribe una sesión imposible.

### 16. Indicador nuevo: «Open Gap (%)», y las 8 capas que hizo falta tocar

Pedido como guarda del genético: «añade también lo de gap de apertura mínimo,
por si no quiero solo ver el de PM». No existía: el motor solo tenía
«PM High Gap (%)» (máximo de premercado vs cierre de ayer) y «Current Gap (%)»
(precio vivo vs cierre de ayer). El gap de apertura solo vivía como columna del
lago, para filtrar universos.

**Es CAUSAL a propósito: NaN antes de las 09:30.** El dato existe
(`gap_at_open_pct`) y devolverlo constante todo el día habría sido trivial —
pero es LOOKAHEAD: una estrategia que entra a las 08:00 estaría usando la
apertura de las 09:30. El NaN de la mañana no es un fallo, es la corrección.
Mismo criterio que «% Session Fade».

Capas tocadas: `indicators.py` (legacy) · `strategy_engine.py`
(`_ri_open_gap` + dispatch nativo, con test de paridad) · `schemas/strategy.py`
(`IndicatorType`) · `api_public/.../catalog.py` · `types/strategy.ts` ·
`indicatorValidation.ts` · `ConditionBuilder.tsx` (es-porcentaje, es-medida,
desplegable, etiqueta y ayuda) · `genetico/catalogo.py` (la guarda, que sale en
los DOS modos).

De esas, **`indicatorValidation.ts` la cazó TypeScript** — es la única de las
ocho que da error en vez de caerse en silencio.

⚠️ **Una capa NO se ha tocado, a propósito:** el bot de avisos en vivo
(`bot_alerts_universo.py`) tiene su propio mapa de nombres y es zona cerrada
(AGENTS.md). Una estrategia que use «Open Gap (%)» funciona en el backtest pero
**el bot todavía no la entiende**. Queda para Jaume y Sailor.

### 17. El genético ya no pide dataset: lo definen las guardas y las fechas

Jaume: «yo meto las guardas y el rango de fechas donde quiero analizar; que
cargue un dataset en base a eso, no hace falta ni quiero que tengamos que
cargar ningún dataset aquí… las guardas que fijamos son como filtros también de
universo». Vale para los DOS modos.

**Se pudo hacer porque el dataset solo servía para producir el `qualifying`**:
`datos.preparar` lo usa y a partir de ahí el `dataset_id` es solo metadato; las
velas salen de los pares del propio qualifying.

`fetch_qualifying_data` acepta ahora `filtros` explícitos (sin ellos, se
comporta exactamente igual que siempre). El router traduce cada guarda a una
columna diaria, y **cada traducción es una COTA SUPERIOR de su guarda intradía,
así que nunca quita un día que la guarda habría dejado pasar**:

| guarda | columna | por qué es segura |
|---|---|---|
| `Bar Close > X` | `high > X` | si una vela cierra sobre X, el máximo del día también. **`open` NO valdría**: una acción abre a 0,05 y se va a 5 |
| `Dollar Volume > X` | `volume * high > X` | Σ(precio·vol) ≤ high·Σvol |
| `Accumulated Dollar Volume > X` | `volume * high > X` | igual |
| `PM High Gap (%) > X` | `pmh_gap_pct > X` | el PMH final ≥ el acumulado |
| `Open Gap (%) > X` | `gap_at_open_pct > X` | exacto, es constante |

Las guardas **siguen corriendo vela a vela** dentro de la estrategia: esto solo
evita cargar días que no pueden pasarlas nunca.

**Tope de 60.000 ticker-días y contador en vivo.** Sin una guarda que acote, el
universo es el lago entero: medido, precio > 0,7 y dollar volume > 1 M sobre
2019-2024 dan **7.461.580 ticker-días**. Marcando además PM High Gap ≥ 50 bajan
a **7.800**. La página lo enseña antes de lanzar y el backend lo rechaza por
encima del tope — mejor un error que decir «lanzada» y dejarla muriendo sola.

El contador es un `count` directo sobre el parquet materializado, con DuckDB en
memoria: **4,7 s** frente a los más de 30 que tardaba construyendo el qualifying
entero con sus 32 ventanas LAG/LEAD para dar un número.

**Cabo suelto conocido:** al guardar un ganador desde la tabla, la estrategia se
guarda SIN dataset atado (la corrida ya no tiene uno). El aviso lo dice y el
universo se elige al abrirla en el Backtester.

### 18. Rectificación: las guardas NO son el universo

Jaume, sobre §17: «una guarda puede ser una guarda, pero si te digo que el close
sea mayor que 7 **no** te estoy diciendo que solo incluyamos acciones por encima
de 7, te estoy diciendo que solo quiero ENTRAR cuando la estrategia supera 7…
intenta no transformar nada, no hacer equivalencias ni cosas raras».

Tenía razón. La traducción guarda→columna de §17 era matemáticamente segura
(cotas superiores) pero conceptualmente equivocada: mezclaba dos cosas que el
usuario tiene separadas en la cabeza, y le obligaba a razonar sobre
equivalencias para saber qué iba a correr. **Retirada.**

Ahora:

- **Las guardas son guardas**: condiciones de entrada, vela a vela. Nada más.
- **El universo se define aparte**, en su propio cuadro, con las MISMAS opciones
  que al crear un dataset en el Backtester — se reutiliza `InlineDatasetBuilder`
  entero, con una prop nueva `soloFiltros` que se salta el modal del nombre y no
  crea ningún dataset. Cero divergencia de opciones y cero traducciones: los
  filtros viajan en `cfg["universo"]` con la forma exacta que ya entiende
  `_build_where_clause`.

Se conservan de §17 el contador en vivo y el tope de 60.000, que sí eran útiles.

**El contador cae a la vía lenta con reglas de Gap−1.** El parquet materializado
no lleva `lag_pmh_gap_pct` ni sus hermanas — se calculan al vuelo en la vía
completa. Un universo con Gap−1 reventaba el count rápido con un Binder Error y
devolvía un 500; ahora se registra y se recalcula por la vía buena.

**Lección:** cuando una simplificación exige explicarle al usuario una
equivalencia para que entienda qué va a correr, la simplificación es el problema.

### 19. Universo con el estilo de la página, y el tope de parciales

Tres retoques pedidos por Jaume sobre el modo mejorar:

**1. El nº de parciales manda sobre las filas.** Si el rango de «Cuántos
parciales» llega a 2, marcar el disparador del 4º no haría nada: el gen viajaría
y `a_definicion` lo ignoraría — un ajuste fantasma sin error, como el Max DD
Diario. Ahora esas filas salen deshabilitadas («por encima del máximo de
parciales») y además se filtran del config, por si el máximo baja después.

**2. Se va la sección «Datos».** Tenía nombre + IS desde/hasta, y el cuadro de
universo llevaba SU propio rango de fechas: dos sitios para el mismo periodo,
pidiendo contradecirse. Ahora hay un solo cuadro, **Universo**, con el nombre de
la corrida, el periodo IS y los filtros. Jaume: «no te compliques, ese rango de
fechas global es el IS».

**3. El selector, con el estilo de la página.** Estaba embebido
`InlineDatasetBuilder` entero y desentonaba con el resto (`Sec`/`Row`/`Sel`/
`Num`). Ahora es nativo: sección + métrica + operador + valor + «Añadir», y las
condiciones puestas como fichas con «×».

**Sin duplicar el catálogo.** Las métricas, sus descripciones, la traducción a
columnas del lago y el armado del objeto de filtros se han sacado a
`lib/universoFiltros.ts`, que ahora usan LAS DOS pantallas —
`InlineDatasetBuilder` importa de ahí. Dos listas de métricas no darían error:
una se quedaría corta y nadie lo notaría.

Detalle: al añadir una condición que repite sección + métrica + signo, se
SUSTITUYE la anterior. Dos reglas contradictorias sobre lo mismo dejarían el
universo vacío sin decir por qué.

### 20. Tres ajustes fantasma en el panel de riesgo del modo mejorar

Jaume: «en riesgo veo la opción de reentradas y arriba también me deja
activarlas. En modo estrategia la opción de riesgo para reentradas no debería
estar».

Tenía razón, y no era solo una. En modo mejorar, **reentradas, «shares por SL» y
stop híbrido salen de la DEFINICIÓN de la estrategia**
(`evaluador.parametros_backtest` los lee de ahí, ver §12). Los controles del
panel del explorador seguían pintados y **no hacían nada**: se tocaban, no
pasaba nada y nadie avisaba — el patrón del Max DD Diario.

Ahora esos tres solo se pintan en modo explorar; en mejorar, una línea explica
de dónde salen y recuerda que las reentradas se pueden mover como gen.

Lo cubre `test_en_modo_mejorar_el_riesgo_del_panel_no_pisa_a_la_estrategia`:
con el panel diciendo lo contrario que la estrategia, mandan la estrategia y su
híbrido, y las reentradas ni siquiera viajan como argumento.

### 21. El KeyError que la pantalla no podía enseñar

Al quitar el dataset (§17-19) se cambió el router y la página, pero se quedó
`genetico/corrida.py` haciendo `config["dataset_id"]`. Resultado: la corrida
moría a los tres segundos con un `KeyError` y **en la pantalla no salía nada** —
Jaume: «sigue en marcha no? parece que no haga nada».

Es el modo de fallo propio de esta arquitectura: el genético es un **proceso
externo**, así que su traceback acaba en `salida.txt` dentro del directorio de
la corrida, y la página solo ve que `estado.json` no aparece. Sin abrir ese
fichero no hay forma de saber que ha reventado.

**Dónde mirar cuando una corrida «no hace nada»**, por este orden:

    <corrida>/salida.txt   el traceback del proceso, si murió
    <corrida>/log.txt      el avance; en la fase de velas escribe cada 12 meses
    <corrida>/estado.json  lo que lee la página; NO existe hasta que arranca

Ojo con confundir «muerta» con «cargando»: la preparación de datos es lo primero
y lo más lento (medido en la corrida del 6-sep: 72 meses en ~3,5 min, una línea
de log cada 12). Hasta que no acaba, `estado.json` no existe y la página está en
blanco con todo funcionando.

`corrida.py` usa ahora `config.get("dataset_id") or ""`, y `datos.preparar`
lanza un error que se entiende si de verdad no hay ni qualifying ni dataset.
`test_genetico_sin_dataset.py` vigila las dos mitades del contrato — y lee solo
el CÓDIGO, porque el comentario que explica el fallo contiene el mismo literal.

## 2026-09-07 — Merge de `staging` en `alvaro-rama-desarrollo` SIN el bot de alertas (2º merge de exclusión)

Merge de `origin/staging` (`c8e1883`; 62 commits de Jaume desde `6db5a36`).
Trae: el paquete `genetico/` completo (optimizador genético de estrategias,
con router `/api/genetico` y página `/genetico`, ambos APAGADOS por defecto
vía `GENETICO_ENABLED` / `NEXT_PUBLIC_GENETICO_ENABLED`), stop híbrido con
techo de parciales al 40 %, margen de stop de estructura en el optimizador
(3D, WFO y genético), ventana de entrada estricta y sesión excluyente,
parciales variables y piramidación con dimensionado propio, locates en el
calendario, Rolling EV, `strategy_explain.py` (qué hace DE VERDAD una
estrategia frente a su JSON), what-if de céntimos de las mesas de fondeo,
primitivo UI `Panel`, y los docs `MEMORIA_BOT_EJECUCION.md`,
`PROYECTO_EV_Y_LOCATES.md` y `PROYECTO_TELEGRAM_ESTADO.md`.

**Bot de alertas: EXCLUIDO otra vez** (decisión fijada en la entrada del
2026-09-02): los 14 ficheros de la zona cerrada que trae staging quedaron
fuera (6 `bot_alerts_*.py` modificados, `bot_alerts_comandos.py` y
`bot_alerts_diario.py` nuevos, sus tests, `CuadroMandos.tsx` y
`api_bot_alerts.ts` y el router). Ni un fichero ni una referencia queda en
la rama; `market_frame.py` ni se tocó (staging no lo modificó). Sin `.env`
ni secretos trackeados en staging (verificado con `git ls-tree`).
`strategy_explain.py` (nuevo de staging) importa `bot_alerts_universo`
perezosamente DENTRO de un try/except puesto a propósito por Jaume («para
no atar este módulo al bot»): sin el bot devuelve `{}` y no rompe nada;
aquí solo lo invoca el router excluido, así que queda dormido e inofensivo.

Conflictos resueltos:
- `MEMORIA_MADRE.md` — ambos lados conservados (nuestras entradas + las de Jaume).
- `Sidebar.tsx` — nuestro estado (sin Screener ni Alertas) + el link
  «Genético» gated de staging (import `Dna`, sin `Radio` — era del link de
  Alertas que aquí no existe).
- `CalendarTab.tsx` — adoptada la versión de STAGING (lectura en dinero o en
  R de los tres modos, riesgo porcentual y locates en el calendario). SUPERA
  al modo «R» local del commit `2f19fe7`, que queda retirado en la práctica:
  mantener las dos versiones re-conflictuaría cada merge y la de staging es
  la que vive en la rama conjunta. El botón CSV de Trades y los fixes de
  «Nueva Estrategia» (`2c4e5eb`, `e29652c`) SIGUEN: esos ficheros
  auto-fusionaron y se comprobó que los cambios locales siguen presentes.

Verificación: `tsc --noEmit` 0 errores; `compileall` de `backend/app` y
`genetico` OK; pytest `test_stop_hibrido` + `test_genetico_*` 112/113 (el
único fallo es ambiental, ver hallazgo de abajo); `test_strategy_api` +
`test_backtest_dataset_bloqueado` 8/8. OJO al lanzar pytest: `database.py`
abre `local_data.duckdb` RELATIVO al cwd — desde la raíz del repo conecta a
una BD vacía y falla sin que nada esté roto; lanzar desde `backend/`.
`backend/.env` intacto (des trackeado, el merge no lo toca).

### [HALLAZGO · 2026-09-07 · 01] El paquete `genetico` tiene rutas por defecto en `D:/` — la suite falla en cualquier PC que no sea la de Jaume
- **Reporta:** ZCode (para Álvaro)
- **Severidad:** bug (ambiental — en la máquina de Jaume no falla)
- **Dónde:** `genetico/entorno.py:15` (`BTT_GENETICO_DIR` por defecto `D:/tmp/btt_genetico`, con `os.makedirs(DIR_TRABAJO)` dentro de `preparar()`) y `genetico/datos.py:35` (lago por defecto `D:/lago_backtester/parquet/...`)
- **Qué observé:** al llegar por el merge de staging, `backend/tests/test_genetico_sin_dataset.py::test_sin_qualifying_y_sin_dataset_el_error_lo_explica` falla en este equipo con `FileNotFoundError: [WinError 3] El sistema no puede encontrar la ruta especificada: 'D:/'` — no hay unidad D:. Los otros 112 tests del mismo lote pasan.
- **Cómo reproducir:** `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_genetico_sin_dataset.py -q` (desde la raíz del repo, sin `BTT_GENETICO_DIR` definido)
- **Evidencia:** `1 failed, 112 passed in 6.47s`; el traceback termina en `os.makedirs(name='D:/', exist_ok=True)` alcanzado desde `genetico/entorno.py` (`DIR_TRABAJO`). Confirmed: ni `.env` ni variables del entorno definen `BTT_GENETICO_DIR` aquí.
- **Hipótesis de causa:** HIPÓTESIS — Jaume desarrolla con el lago y el scratch en su unidad `D:`; el default del `os.getenv` apunta a SU máquina en vez de a una ruta portable (relativa al repo o temporal). `datos.py` además trae el lago `D:/lago_backtester/...` hardcodeado en el propio literal.
- **Impacto:** el genético no puede ejecutarse en la máquina de Álvaro sin definir `BTT_GENETICO_DIR` (y la ruta del lago); 1 test rojo fuera de la máquina de Jaume. No afecta al arranque normal: router y página están gated OFF por defecto.
- **Código tocado:** NINGUNO (confirmado) — el código llega verbatim del merge de staging; no se ha modificado para arreglarlo
- **Estado:** ABIERTO

### [HALLAZGO · 2026-09-07 · 02] Warmup JIT de indicadores huérfano desde el merge del 2026-09-02 — main.py llama a una función que ya no existe
- **Reporta:** ZCode (para Álvaro)
- **Severidad:** bug (menor; degrada con WARN, no rompe)
- **Dónde:** `backend/app/main.py:195-196` (caller) frente a `backend/app/services/indicators.py` (la función ya no está)
- **Qué observé:** al arrancar el backend tras el merge del 2026-09-07, el log saca `[JIT] warmup de indicadores falló (no crítico): cannot import name 'warmup_indicators' from 'app.services.indicators'`. El caller vive en `main.py` (introducido por `bcc75ba`, perf(jit)), pero `def warmup_indicators` NO existe ni en `indicators.py` del base `6db5a36`, ni del pre-merge `2f19fe7`, ni de staging `c8e1883` — solo en `bcc75ba` original. Ya faltaba en el merge anterior `13ce154` (2026-09-02): o sea, el warmup no ocurre desde entonces.
- **Cómo reproducir:** arrancar el backend y mirar el log de arranque (WARN `[JIT] warmup de indicadores falló`).
- **Evidencia:** `git grep -c "def warmup_indicators" bcc75ba -- backend/app/services/indicators.py` → 1; el mismo grep en `13ce154`, `6db5a36`, `2f19fe7` y `c8e1883` → 0. Caller presente en `main.py:195` en todos los HEAD recientes.
- **Hipótesis de causa:** HIPÓTESIS — el merge del 2026-09-02 tomó el `indicators.py` de staging (que no descendía del warmup) y el caller de `main.py` sobrevivió al auto-merge. El WARN viene de ahí, no del merge del 2026-09-07 (pre y post-merge están iguales).
- **Impacto:** el primer backtest de cada arranque paga el coste JIT de los indicadores en vez de calentarlo en background. Sin efecto en resultados.
- **Código tocado:** NINGUNO (confirmado) — reportado, no arreglado (reintegrar el warmup o retirar el caller es decisión de Álvaro/Jaume, y habría que adaptarlo al catálogo nuevo de indicadores de staging)
- **Estado:** ABIERTO

### [HALLAZGO · 2026-09-07 · 03] El calendario en R convierte con el 1R del PANEL EN VIVO, no con el de la corrida ejecutada — descuadre de 100× demostrado
- **Reporta:** ZCode (para Álvaro)
- **Severidad:** bug (números R falsos al reabrir una corrida cuyo 1R de lanzamiento difiere del campo actual del panel; con la corrida recién lanzada y el panel sin tocar, cuadra)
- **Dónde:** `frontend/src/components/backtester/ResultsTabs.tsx:291-292` — pasa `riskR={riskR}` (estado VIVO del panel, `BacktestPanel.tsx:420`) junto a `riskType={backtestParams?.risk_type}` (parámetros GUARDADOS de la corrida). Fuentes mezcladas. El consumidor es `CalendarTab.tsx` (`puedeR`, `valorRPorDia`), que divide el PnL del día entre ese `riskR`.
- **Qué observé:** Álvaro veía «1 R = $100» y un mes a +0.02 R en el calendario de una corrida cargada. La corrida (autosave `041b2fc7`, «Doble Techo 1», 2.472 trades) se lanzó con `risk_r: 1.0, risk_type: FIXED, size_by_sl: false` (leído de `backtest_params` persistido por `_autosave_success`): posiciones de ~1 $ nocional (CHOW 2026-01-02: size 0.970874 = 1/entry_price) y `r_multiple = pnl/1`. El calendario dividía entre el 100 $ del panel → sus R salían 100× más pequeñas que los `r_multiple` del propio motor (marzo: +0.02 R pintado vs +2.15 R sumando r_multiple). El motor NO está en causa: re-lanzando la misma petición con `risk_r: 100` por API, los tamaños son de cientos de acciones y `r_multiple = pnl/100` exacto (control `b5d7a02e`).
- **Cómo reproducir:** lanzar una corrida con 1R=1 $ (FIXED), cambiar el campo 1R del panel a 100, mirar el calendario en R: la etiqueta dice «1 R = $100» y los números R del calendario son 100× menores que la suma de `r_multiple` de los trades de esa misma corrida.
- **Evidencia:** suma marzo 2026 de la corrida 041b2fc7: Σ r_multiple = +2.15 R; Σ (pnl/100) = +0.02 R (lo pintado). Params de la corrida en `GET /api/strategy-search/041b2fc7` → `backtest_params.risk_r = 1.0`. Control con `risk_r=100`: CHOW size 764.94, pnl 119.03 → r_multiple 1.19 = pnl/100 ✓.
- **Hipótesis de causa:** HIPÓTESIS — al adoptar la lectura en R de staging (unidad $/R de CalendarTab) no se cableó `riskR` desde los `backtest_params` guardados de la corrida cargada (donde ya viaja `risk_type`), sino del estado vivo del panel. Con la sesión restaurada o un autosave reabierto, el 1R de lanzamiento y el del panel divergen y la conversión miente sin error.
- **Impacto:** cualquier R del calendario (y tooltips/semanas/meses) leída de una corrida cuyo 1R de ejecución no coincida con el campo actual es falsa en la proporción entre ambos. No afecta a los `r_multiple` de la pestaña Trades (los calcula el motor con el riesgo de la corrida). La corrida inspeccionada, además, corrió con posiciones de ~1 $ (1R=1 $, tamaño por valor de mercado): su PnL en dólares no es evaluable como estrategia.
- **Código tocado:** NINGUNO (confirmado) — cablear `riskR` desde `backtest_params` (o etiquetar la unidad con el 1R de la corrida) es el arreglo propuesto; lo aplica el dueño del código
- **Estado:** ABIERTO

### [HALLAZGO · 2026-09-07 · 04] `r_multiple` divide TODO el PnL (pirámides incluidas) entre el riesgo INICIAL — Rs absurdas cuando las pirámides dimensionan aparte; y `total_return_r` del autosave es siempre 0
- **Reporta:** ZCode (para Álvaro)
- **Severidad:** inconsistencia (semántica de R con piramidación) + bug menor (métrica siempre 0)
- **Dónde:** `backend/app/services/backtest_service.py:1251` y `_compute_r_multiple` (1462-1470): `r_multiple = pnl_total_del_trade / risk_unit_dollar` con `risk_unit_dollar = risk_r` de la corrida. Piramidación: `portfolio_sim.py` (niveles con `amount_usd` fijo y dimensionado propio). Secundario: `backend/app/routers/strategy_search.py:42` (`aggregate.get("total_return_r", 0)`).
- **Qué observé:** corrida 2ee9c294 («1B Sobri», 1.217 trades) lanzada con `risk_r=1.0, FIXED, size_by_sl=true`; la estrategia piramida «Añade 300$» por nivel. Nocional de los trades: mediana 301 $ (las pirámides mandan; la entrada inicial con riesgo de 1 $ es minúscula). El motor reparte: Rs de +192.6R / −237.7R por trade, media +9.84R, **suma +11.974R** — una cifra sin significado: el PnL lo generan pirámides de 300 $ pero el divisor es el riesgo inicial de 1 $. El «retorno» del gráfico (+119.74 %, 10.000→21.974 $) es real en dólares y lo explican las pirámides. Y en «Últimas pruebas» TODAS las corridas (incluidas las buenas) listan R=0.0.
- **Cómo reproducir:** 1B Sobri (tiene pirámide «Añade 300$» + tamaño por SL) con 1R=1 $ FIXED, 2026-01-01→2026-08-25; mirar la columna R de Trades y el R de Últimas pruebas.
- **Evidencia:** trades 2ee9c294: JWEL 2026-08-10 nocional 352 $, pnl −237.73, R −237.7 (SL); MAMO 2026-02-03 nocional 325 $, pnl +192.56, R +192.6 (EOD); Σ r_multiple = +11.974R; riesgo implícito pnl/R mediana = 1.0000. Aggregate de la misma corrida: `avg_profit_factor 2.0557, total_return_pct 119.74` — sin ninguna clave `total_return_r` → `strategy_search.py:42` cae al 0.
- **Hipótesis de causa:** HIPÓTESIS — (a) la R se definió como «pnl del trade / riesgo de la unidad» antes de que las pirámides dimensionaran por su cuenta (amount_usd fijo / tamaño propio), y nadie revisó el divisor; con pirámides el riesgo real del trade es inicial + añadidos. (b) el escritor del autosave espera una clave que el agregado nunca produjo bajo ese nombre (renombrado en algún momento o nunca existió).
- **Impacto:** toda métrica en R de corridas con piramidación en dólares fijos es inservible (columna R de Trades, avg R del modal del calendario, ranking del genético si usa r_multiple). Con riesgo «normal» (100 $) los números parecen razonables pero mezclan la misma escala. Últimas pruebas no muestra R de ninguna corrida y su filtro por R no filtra.
- **Código tocado:** NINGUNO (confirmado) — decidir el divisor correcto (riesgo acumulado real del trade, o excluir pirámides de la R) es decisión de diseño de Jaume/Álvaro
- **Estado:** ABIERTO
