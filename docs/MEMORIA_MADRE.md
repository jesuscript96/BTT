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

## 2026-08-29 — ⚠️ BUG PERSONAL de Álvaro (rama `alvaro-rama-desarrollo`) — NO NECESARIAMENTE LO NECESITA SAILOR (Jaime)

> Nota para mí mismo / mi IA, por si vuelvo a necesitarlo. Solo un detalle roza
> al equipo (marcado abajo). El análisis exhaustivo está en mi local
> (`.zcode/MEMORIA_ALVARO_LOCAL.md`, no commiteado).

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
