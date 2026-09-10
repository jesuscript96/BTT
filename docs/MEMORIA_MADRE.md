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

## 2026-09-07 · La regla de los céntimos estaba en el motor equivocado

Salió de una revisión de Álvaro (`PRD_MODULO_ROBUSTEZ.md` §2.2) que Jaume trajo
al chat. **No era un problema del precio medio de entrada**, que es lo que se
sospechaba: `mueve_bastante` usa `avg_entry_price` a propósito y está bien. El
fallo era del dominio en el que se reconstruye la curva.

### El fallo

`min_move_cents` vivía SOLO en `what_if_service`, y ese servicio reconstruye la
equity **sumando dólares**. Con `risk_type = PERCENT` —3 % del capital vivo—
los dólares de cada trade dependen del balance que hubiera ese día: quitar
trades y volver a sumar el resto rompe el vínculo con el capital. Medido por
Álvaro sobre 3.544 trades: quitando el mejor 10 %, la curva aditiva acababa en
**−84.411 $** (dinero negativo) donde la recompuesta da 2.617 $, o sea −73,8 %.

La regla de la mesa es ese mismo caso y peor: **descarta ganadores de forma
sistemática**, no un 10 % puntual. La dirección del error importa — pintaba la
regla mucho más letal de lo que sería en la cuenta real.

### Lo que se ha hecho

1. **`_recomponer_por_dia` en `what_if_service`.** El PnL de cada día escala
   por `capital_filtrado(día) / capital_original(día)`. Es recomponer en R sin
   necesitar la distancia al stop: R = pnl/riesgo y el riesgo es un % del
   capital, así que el % se cancela. Se escala **por día y no por trade**
   porque el motor compone por día.
2. **Solo se activa con `risk_type: "PERCENT"`,** que ahora manda la página
   (lo tenía en un prop y no lo enviaba). Sin ese dato se asume riesgo fijo y
   todo se comporta como siempre: la corrección no puede activarse sola.
3. **El día que reventaría la cuenta se recorta hasta dejarla en cero** y el
   recorte se reparte entre sus trades, para que el PnL de los trades cuadre
   con la curva. Sin eso el equity se iba a negativo por detrás.
4. **La regla se portó a `robustness_stress`**, que es el motor que ya
   trabajaba en R, con su campo en el panel de Robustez. La función
   `mueve_bastante` se **importa** del What-if: es una sola regla, y escribirla
   dos veces es garantizar que un día las dos pantallas discrepen.
5. **El filtro pasó a ir DESPUÉS de los límites de actividad** en los dos
   motores. Iba antes, así que un ganador corto liberaba su hueco de
   «Máx. trades/día» y dejaba entrar en su lugar a un trade posterior que nunca
   se llegó a operar. El trade existió: ocupó su plaza aunque no lo abonen.

**Invariante fijada con test:** sin ningún filtro los dos capitales coinciden
día a día, el factor es 1,0 exacto y la curva sale idéntica a la de partida.
Es la misma propiedad que se rompió el 4-sep con `dd_threshold`.

`test_what_if_recomposicion.py`, `test_robustez_stress_centimos.py` y un caso
nuevo en `test_what_if_centimos.py` (el hueco del día).

### Lo que sigue sin cubrir

- El `pnl > 0` que decide si un trade es ganador es el **bruto**, antes de
  locates. Un trade de +8 $ con 20 $ de locate se juzga como ganador.
- Los locates no se arrastran al What-if (ya estaba documentado en
  `_day_results_de`), así que la lectura sigue siendo bruta.
- Los parciales sí van bien: cada parcial es su propio trade con su
  `exit_price`, o sea que la regla se aplica **por ejecución**, que es como la
  aplica una mesa.

### El What-if salía MEJOR que el original: los locates

Jaume lo vio en pantalla el mismo día: con la regla de los 10 céntimos puesta,
824 trades → 780, y el PnL **subía** de 5.000 $ a 6.724 $. Una regla que solo
QUITA ganadores no puede mejorar nada.

No era la regla ni la recomposición —las dos son monótonas: quitar un ganador
no puede subir la curva—. Era que **las dos curvas no medían lo mismo**:

    curva del backtest   NETA de locates  (`_compute_global_equity_and_drawdown`
                                           recibe `locates_fee_by_date`)
    curva del What-if    BRUTA            (el locate no está en el pnl de
                                           ningún trade y no llegaba)

La diferencia era la factura de alquiler entera: ~1.700 $ en esa corrida. Es el
mismo fallo que tuvo el calendario en agosto, en otra pantalla.

**Arreglado:** los locates viajan por par `TICKER|FECHA` (`locates_by_pair`,
que la página saca de `day_results`) y se cobran **enteros si sobrevive algún
trade de ese ticker ese día**, cero si no sobrevive ninguno. No es un reparto
aproximado: el locate se cobra una vez por ticker-día, así que o se alquiló o no.
No se reescalan con la recomposición —una curva más pequeña habría alquilado
menos paquetes—, que es el lado conservador.

**La pregunta que caza esta familia entera de fallos:** cuando dos curvas se
pintan juntas para compararlas, ¿están hechas con los mismos costes? Aquí no lo
estaban, y el error tenía signo — siempre a favor de la simulación.

### HALLAZGO SIN ARREGLAR: el techo del híbrido depende del OTRO interruptor

**No se ha tocado. Decisión de Jaume el 7-sep: nada de stops, distancias ni
híbrido — el motor lo comparte el bot en vivo y se revalida con él.** Queda
apuntado para cuando toque.

`portfolio_sim` hace `if hybrid_stop and size_by_sl:`, y el nivel de pirámide
tiene el techo **anidado dentro** de su rama `size_by_sl`. Consecuencia: una
definición con el híbrido encendido y «Shares por SL» apagado se dimensiona
**sin techo, sin error y sin log**.

El builder impide esa combinación (encender el híbrido fuerza `size_by_sl`).
**El panel del genético no la impedía**: su checkbox solo escribía
`hybrid_stop`, y su ayuda prometía lo contrario — «Implica Shares por SL, así
que lo activa solo». No saltaba porque el defecto viene en `true`; bastaba con
desmarcar «Shares por SL» y dejar el híbrido puesto para correr un genético
entero sin techo creyéndolo puesto. **Eso sí se ha arreglado** (el checkbox
escribe los dos campos), que era el único sitio por donde entraba la
combinación rota.

`sim_dispatch` ya rutea mirando `hybrid_stop` a secas, así que la combinación
llega al motor Python: el día que se arregle, el arreglo la alcanza. Sería
cambiar las dos condiciones por `hybrid_stop` a secas — el techo es una GUARDA,
no una opción del modo por SL.

**Nota de nombre:** «stop híbrido» no es un stop — es un modo de calcular
ACCIONES, con el mismo stop de siempre. En el desplegable de la pirámide ya se
llama por su nombre (`mv` / `sl` / `híbrido`); en la entrada sigue siendo un
interruptor por razones históricas.
### [VERIFICADO · 2026-09-07 · MAE] «MAX MAE 169,56%» en G&E RTH 2026 — NO es bug: excursión real, verificada contra velas (duda de Álvaro resuelta con evidencia)
- **Plantea:** Álvaro («esto del MAE tiene que estar mal»)
- **Verifica:** ZCode (para Álvaro)
- **Qué se vio:** panel Aggregate con MAX MAE 169,56 % y avg 13,76 % en la corrida G&E RTH 2026 (autosave `6e53853b`, 518 trades; lanzada con risk_r=1 $, sin size_by_sl).
- **Verificación:** el trade top (RGNT 2026-06-09, short a 2,4299 a las 09:37, stop estructural 7,33 = PM max, EOD) — consultado el parquet del lago: máximo ALTO entre 09:37-10:59 = 6,55 → (6,55−2,4299)/2,4299 = **169,56 % exacto**. La ventana es correcta: el máximo pre-entrada (7,33, premarket) NO cuenta. El motor (`portfolio_sim.py`, cota al precio de stop/TP solo en la vela de salida) calcula lo que dicen las velas.
- **Por qué asusta:** la estrategia shortea fondos profundos tras fades del 60-70 % con el stop en el MÁXIMO VIEJO → stop al 150-200 % de la entrada. En % del precio la excursión parece apocalíptica; **en R todas las MAE grandes son ≤1 R** (RGNT 0,84 R; HKIT 0,84 R; PAVS/EHGO/SPHL 1,00 R = SL). 17/518 trades >50 %, 3 >100 %.
- **MEJORA (opcional) para Jaume:** mostrar el MAE también en R (mae_r = mae_pct / distancia_al_stop_pct) junto al porcentual — en estrategias de stop lejano el porcentual solo engaña; en R se lee el riesgo real flotado.
- **Código tocado:** NINGUNO (confirmado)
- **Estado:** CERRADO (verificado, no bug)

### [FEATURE · 2026-09-07 · ESTILO CANGREJO] Nueva tarjeta de Risk Management: acotar cada trade "o por recorrido del SL, o por pérdida máxima" — para Jaume y su IA
- **Propone/decide:** Álvaro (implementado por ZCode en SU rama, a la espera del flujo habitual)
- **Qué es:** tarjeta "Estilo Cangrejo" en el builder, debajo de todo lo del Stop Loss, con DOS modos EXCLUYENTES ("debe ser o una u otra", decisión de Álvaro): **(A) Recorrido máx. del SL** — el stop estructural/% nunca queda a más de D% del entry: se aprieta y la salida real pasa a ser el stop apretado (cambia DÓNDE sales); **(B) Pérdida máx. por trade** — el stop no se toca, se encoge el tamaño para que llegar al SL no cueste más de X% de la cuenta (cambia CUÁNTO pones). Son techos: solo recortan, nunca agrandan, sobre el sizing activo (MV/por SL/híbrido). Exclusivos con el Stop Loss Híbrido de Jaume: la UI los apaga mutuamente y si un payload trae ambos, el motor arbitra a favor de Cangrejo. **La lógica del híbrido NO se ha tocado.**
- **Por qué:** con SL por market structure la distancia cambia en cada entrada y con el mismo MV unos stops cuestan poco y otros muchísimo (el motivo original de Álvaro). La primera versión de la tarjeta (4 topes: distancia, pérdida, MV entrada, MV pirámide) resultó poco intuitiva en pruebas con la Estrategia 1B y se simplificó a estos dos modos por decisión de Álvaro.
- **PRD completo (el porqué y los detalles):** `docs/PRD_ESTILO_CANGREJO.md` — subido también a staging con esta entrada para que se pueda leer sin esperar al merge.
- **Dónde (código, en `alvaro-rama-desarrollo`):** `backend/app/schemas/strategy.py`, `backend/app/services/{portfolio_sim,sim_dispatch,backtest_signals,backtest_service,backtest_orchestrator}.py`, `backend/tests/test_estilo_cangrejo.py` (19 tests), `frontend/src/types/strategy.ts`, `frontend/src/components/strategy-builder/RiskManagement.tsx`. El bot de alertas: INTACTO (ningún fichero de su zona).
- **Verificación:** suite completa backend 733 passed; auditoría independiente del 2026-09-07 contra el código anterior (123 comparaciones de invarianza en 25 escenarios + 400 configs fuzz, cero divergencias incl. JIT; recortes exactos; plumbing punta a punta con captura de kwargs reales; el incidente "backtest idéntico con Cangrejo ON" reproducido por HTTP y explicado: con riesgo 0,5% y topes al 5% no pueden morder — correcto, no bug).
- **Avisos para el que integre:** (1) con Cangrejo activo la simulación va SIEMPRE al motor Python (kernel Numba no lo implementa, como el híbrido); (2) el fix del dispatcher del 2026-09-07 hace que `hybrid_capital` llegue al motor también con Cangrejo sin híbrido — relevante para el bot cuando lo use; (3) `cangrejo_max_mv_entry_pct`/`cangrejo_max_mv_pyr_pct` siguen admitidos por el motor pero INERTES (sin UI) por si vuelven.
- **Código tocado:** solo lo listado arriba, en rama de Álvaro. Nada de staging salvo este documento y esta entrada.
- **Estado:** IMPLEMENTADO EN RAMA ÁLVARO — pendiente de PR a staging por el flujo habitual.

### [FEATURE · 2026-09-07/08 · OVERHEAD] «Overhead last X days»: el techo que dejó un día pasado, con su volumen y ajustado por splits — sustituye a «High/Low of last X days»
- **Pide/decide:** Jaume (implementado por Claude en `sailor-rama-desarrollo`)
- **Qué es:** el indicador busca el día MÁS EXTREMO de los últimos X días de cotización (el del máximo más alto o el del mínimo más bajo) y, **sobre ESE día**, se elige qué precio es el nivel (High/Low/Open/Close) y si su volumen tiene que ser mayor o menor que el **acumulado de hoy hasta la vela**. Dos pasos y en ese orden: primero el máximo, DESPUÉS su volumen — si el máximo lo hizo un día flojo la señal se descarta, **no** se baja al siguiente techo (decisión explícita de Jaume). Con la condición de volumen puesta, el nivel puede aparecer y desaparecer durante el día, porque el volumen de hoy va creciendo.
- **Por qué el ajuste por splits no es opcional:** el lago guarda precios CRUDOS. Con un contrasplit 20:1 el nivel salía 20 veces por debajo del precio y «Close cruza por encima» se cumplía en la primera vela del día, siempre, sin error y sin log. Caso testigo GCTK (reverse 20:1 el 2026-02-04): máximo crudo 0,1115 → 2,23 en escala post-split. Medido sobre los días de gap ≥20 %: cae un split dentro de la ventana en el **4,3 % de los casos a 30 días, 11,0 % a 6 meses y 16,9 % a un año**. Se guarda precio crudo + factor acumulado y se ajusta AL LEER, relativo al día del trade; el volumen también, dividiendo.
- **De dónde salen los datos:** tabla NUEVA y aparte, `D:/lago_backtester/overhead/daily_overhead.parquet` (268 MB, 19,3 M filas, 23.272 tickers, 2019→2026), que genera `backend/scripts/construir_daily_overhead.py` en 98 s. **No toca el lago ni `daily_metrics`.** Se lee con `read_parquet` de disco, así que no abre `local_data.duckdb` y no compite por el cerrojo de DuckDB. Solo se carga si la estrategia usa el indicador. Ruta en `OVERHEAD_DAILY_PARQUET` (backend/.env). Velas DIARIAS de sesión regular: **sin premercado ni after** — decisión de Jaume, con la consecuencia avisada y aceptada de que el techo de un runner que hizo su pico a las 08:00 no está.
- **AVISO DE MANTENIMIENTO:** la tabla **no se regenera sola**. Al entrar días nuevos al lago hay que volver a lanzar el script o se queda vieja EN SILENCIO.
- **También:** «Recorrido (%)» = `(cierre − apertura) / apertura × 100` **con signo** (`> 3` sube más de un 3 %, `< -2` cae más de un 2 %). Es «Candle Range %» sin el `abs()`. De paso se corrigen las dos descripciones de «Candle Range %» —la interfaz decía «High vs Low» y el genético «de máximo a mínimo»— que eran falsas: el motor calcula el CUERPO, sin mechas.
- **Dónde (código):** `backend/app/{schemas/strategy.py, services/{indicators,strategy_engine,backtest_service,advanced_model,optimization_service}.py, api_public/modules/backtest/catalog.py}`, `genetico/catalogo.py`, `frontend/src/{types/strategy.ts, lib/{indicatorValidation.ts,assistant/schemas.ts}, components/strategy-builder/ConditionBuilder.tsx}`, `backend/scripts/construir_daily_overhead.py`, `backend/tests/test_overhead_last_x_days.py` (22 tests, no necesitan la tabla real: inyectan un ticker en la caché).
- **Avisos para el que integre:** (1) el **bot de alertas NO puede usar el Overhead** hasta que tenga acceso a esa tabla — backtestearía bien y en vivo no daría señal, sin error; (2) `test_genetico_catalogo` se salta este nivel a propósito (su ticker sintético da todo-NaN, que ahí es lo correcto); (3) los nombres «High/Low of last X days» siguen existiendo por compatibilidad, comparten motor y solo fijan otros defectos.
- **Verificación:** 819 tests backend en verde, `tsc --noEmit` limpio. Probado por la vía del motor real (`translate_strategy`) con datos del lago, no solo por `compute_indicator`. **Jaume lo probó el 2026-09-07 y lo dio por bueno.**
- **Estado:** SUBIDO a `sailor-rama-desarrollo` (`b14a5c2`).

### [BUG · 2026-09-08 · GENÉTICO] Modo «mejorar»: las guardas DESPLAZABAN los índices y cada gen escribía en la condición equivocada — 1.721 operaciones se quedaban en 21
- **Detecta:** Jaume («todo a fitness 0,00 … has tocado algo del genético»). **Diagnostica y arregla:** Claude.
- **Qué pasaba:** `afinar.a_definicion` metía las guardas al PRINCIPIO del grupo raíz y DESPUÉS escribía los genes. Pero las rutas de los genes son POSICIONALES (`entry_logic.root_condition.conditions.4.source.offset`) y salen de `extract_parameters` sobre la estrategia SIN guardas: con 4 guardas, cada gen caía 4 posiciones más allá. En la corrida de Jaume, el gen «PM High Gap (%) Target Value = 50» aterrizaba en la guarda `Bar Close > 0,7` y la dejaba en **`Bar Close > 50`**. Sus acciones valen 1-7 $: la estrategia pasaba de 1.721 operaciones a 21, toda la población caía por debajo del `min_trades` y la corrida entera daba fitness 0. **Sin excepción, sin log y sin nada raro en pantalla.**
- **Arreglo:** `_meter_guardas` se llama al FINAL, tras el bucle de genes. **Las guardas siguen existiendo y aplicándose igual** — lo único que cambia es el orden. Verificado: la línea base pasa de 21 a **1.669** operaciones (los ~50 que faltan hasta 1.721 los filtran las guardas, que es su trabajo).
- **CÓMO DESCARTAR QUE EL FALLO SEA DEL MOTOR (vale para cualquier duda futura):** correr `estrategia_base` del `config.json` de la corrida por `run_backtest` con `evaluador.parametros_backtest`, y comparar con lo que saca `afinar.a_definicion(afinar.desde_semilla(cfg), cfg)`. Si los dos números no coinciden, el fallo está en la traducción, no en el motor. Aquí dio 1.721 vs 21.
- **Además, un `offset` en CERO ya es afinable.** `_add` lo tiraba por la regla general de «valor 0 = función desactivada», correcta para un stop pero no para un offset (0 = «esta misma vela»). Por eso «Bar Close < Prev. Bar Low» (objetivo con offset 0) no aparecía en el genético mientras que «Low Bar» con offset 1 sí, siendo el mismo dato escrito de dos maneras. **Lo ganan también el optimizador 3D y el Walk Forward**, que beben del mismo `extract_parameters`. Ojo a la cuenta: `Prev. Bar Low` YA es la vela anterior, así que el offset suma encima (0 = la anterior, 9 = diez atrás).
- **Dónde (código):** `genetico/afinar.py`, `backend/app/services/optimization_service.py`, `backend/tests/{test_genetico_guardas_no_desplazan_los_genes.py, test_offset_cero_es_afinable.py}` (13 tests).
- **Aviso de nombre:** el test se llama «no_desplazan» porque va de DESPLAZAR posiciones, **no** de quitar guardas. Se renombró desde «no_corren» porque Jaume lo leyó como «quitar».
- **Verificación:** 819 tests backend en verde, `tsc` limpio.
- **Estado:** SUBIDO a `sailor-rama-desarrollo` (`a9f6dd4`).

### [FEATURE · 2026-09-08 · ESTILO CANGREJO] Implementado en `sailor` desde el PRD, + bot de alertas, + genético, + kernel Numba
- **Pide:** Jaume («vamos a integrarlo nosotros también … que lo reconozca el bot de alertas y el genético … añadimos también la gestión con numba»). **Implementa:** Claude.
- **EL CÓDIGO DE ÁLVARO NUNCA LLEGÓ.** `git fetch --all --prune` el 2026-09-08: `origin/alvaro-rama-desarrollo` está en el **30-ago** y el único objeto "cangrejo" de todo el repo es `docs/PRD_ESTILO_CANGREJO.md`. No había nada que mergear: esto es una **implementación desde el PRD**, no la integración de su rama. Cuando Álvaro suba la suya habrá que contrastarla (ver las tres divergencias de abajo).
- **Qué hace:** lo del PRD §2, sin cambios de semántica. Modo A `cangrejo_max_sl_dist_pct` (aprieta el stop lejano y la salida real pasa a ser el apretado); Modo B `cangrejo_max_loss_at_sl_pct` (encoge el tamaño para que el SL no cueste más de ese % de la cuenta). Techos: solo recortan. Excluyentes con el híbrido y arbitraje a favor de Cangrejo en el motor.
- **TRES DIVERGENCIAS CONSCIENTES con el PRD** — contrastarlas con Álvaro antes de dar por buena ninguna comparación de resultados:
  1. **VA POR EL KERNEL NUMBA.** El PRD dice que con Cangrejo la simulación cae SIEMPRE al motor Python. Aquí los dos modos se han portado al JIT: `portfolio_sim_jit.py` recibe `cangrejo_active / cangrejo_max_sl_dist / cangrejo_max_loss_pct / cangrejo_capital` (floats con centinela `0.0 = off`, porque numba no admite `Optional` sin disparar una firma por combinación). Era el motivo del encargo: con Cangrejo forzando Python, una corrida del genético se multiplicaba. Medido: **×1,7 en un ticker-día de 390 velas**, y sobre todo ya no hay caída al motor lento. El híbrido SÍ sigue yendo al Python (no se ha portado); con los dos encendidos el híbrido está muerto, así que el kernel es válido y el dispatcher no desvía.
  2. **El Modo B TAMBIÉN topa los añadidos de pirámide.** El PRD solo habla de entradas y reentradas. Sin esto el techo se esquiva entero en cuanto la estrategia piramida — se entra con 300 $ topados y se añaden 5.000 $ sin mirar, que es exactamente el fallo que no da error. La pérdida al stop de la posición completa es separable (`|avg−stop|×size + |add_px−stop|×add`), así que el cupo del añadido sale sin recalcular el precio medio. Tres tests.
  3. **El Modo B no exige `size_by_sl`** (el híbrido sí). Es un techo sobre el sizing que haya, y con sizing por valor de mercado es justo donde la pérdida al stop se descontrola.
- **BOT DE ALERTAS: SÍ SE HA TOCADO** (el PRD lo dejaba intacto). Tres cosas, y las tres hacían falta o el aviso habría dicho una cosa y el backtest otra, sin error: (a) `_kwargs_simulate` pasa los tres campos al simulador interno, con `hybrid_capital` como base del Modo B — su `init_cash` es el nominal de 1e9 y sobre eso el techo no recortaría nunca; (b) el aviso da el stop **APRETADO** por el Modo A, que es donde el motor sale de verdad; (c) `calcular_acciones` aplica el Modo B en las DOS ramas (con y sin `size_by_sl`). `_hibrido_de` devuelve `None` con Cangrejo activo: el mismo arbitraje que el motor. `/watch` no deja activar el Modo B sin capital.
- **GENÉTICO: NO es un gen, y a propósito.** Va en el panel de la corrida (modo explorar) y sale de la estrategia (modo mejorar), como el híbrido. Dejar que la corrida mueva el % del Modo A sería buscar en el histórico el recorte que mejor queda — y ese número cambia DÓNDE se sale, así que el sobreajuste es inmediato.
- **Dónde (código):** `backend/app/schemas/strategy.py`, `backend/app/services/{portfolio_sim,portfolio_sim_jit,sim_dispatch,backtest_signals,backtest_service,backtest_orchestrator,bot_alerts_engine,bot_alerts_service,strategy_explain}.py`, `backend/app/routers/bot_alerts.py`, `genetico/{cromosoma,evaluador}.py`, `backend/tests/test_estilo_cangrejo.py` (36 tests), `frontend/src/{types/strategy.ts, lib/{api_genetico,api_bot_alerts}.ts, components/{strategy-builder/RiskManagement.tsx, bot-alerts/CuadroMandos.tsx}, app/genetico/page.tsx}`.
- **Verificación:** 36 tests propios; **855 passed / 88 skipped** en `backend/tests`; `tsc --noEmit` limpio; auditoría aleatoria de **400 configuraciones** Python↔JIT con los dos modos, series y parámetros al azar → **cero divergencias**, más 94 comprobaciones de invarianza con Cangrejo apagado. La regla nº1 del PRD (sin campos = resultado idéntico) tiene test propio, y también el caso «lo activé y da lo mismo»: con los topes por encima del sizing que ya hay, no muerden — es correcto, no un bug.
- **PARA QUE EL BOT LO USE HAY QUE REINICIARLO.** `D:\bot_senales\bot.py` hace `sys.path.insert(0, BACKEND)` e importa del backend, así que un bot ya en marcha sigue con el código viejo. Y al relanzarlo, acordarse de volver a encender el interruptor: arranca en «Parado».
- **Estado:** en `sailor-rama-desarrollo`, sin commitear todavía (pendiente de que Jaume lo pruebe).

### [BUG + FEATURE · 2026-09-08 · BOT DE ALERTAS] El aviso dimensionaba SIN el stop, y `/evf` ignoraba que los locates van en paquetes de 100
- **Detecta el de los locates:** Jaume («yo cuando pago locates no es por unidad, es por paquetes»). **Detecta el del tamaño:** Claude, al comprobar si `/evf` y el aviso daban lo mismo con la configuración real. No daban.
- **EL BUG GORDO (el del tamaño).** El aviso sacaba su stop con `nivel_stop`, que devuelve `None` para todo lo que no sea `Market Structure` — a propósito, porque en el backtest ese caso lo resuelve el simulador desde `sl_stop`. Pero al llegar a `calcular_acciones` ese `None` hacía caer el tamaño a `riesgo / precio` en vez de `riesgo / distancia`: **el aviso dejaba de dimensionar por riesgo aunque la estrategia tuviera «Shares por SL» encendido**, sin error y sin log. Medido con «RTH prueba 1» (stop 25 %, riesgo 300 $) sobre WYHG a 5,22 $: el aviso daba **57 acciones arriesgando 75 $** donde el motor dimensiona **230 arriesgando 300**. Factor 4. Afectaba a CUALQUIER estrategia con «Shares por SL» y stop de porcentaje; con stop estructural no pasaba, y por eso «1B 50k» estaba bien y no se había visto.
- **Arreglo:** `stop_estimado` resuelve todos los tipos y el aviso lo usa — estructura por `nivel_stop`, y todo lo demás como `precio × (1 ∓ sl_stop)`. **`sl_stop` SE PASA, NO SE RECALCULA**: es la fracción que ya calcula `translate_strategy` y la misma que aplica el simulador. Rehacerla a mano (lo que hacía la primera versión) sale mal en «Fixed Amount», donde el motor divide el importe entre el PRIMER CIERRE DEL DÍA y no entre el precio de ahora.
- **`/EVF` CON PAQUETES DE 100.** Los locates se alquilan en paquetes de 100 y se pagan enteros, así que el coste real por acción operada es `ceil(n/100) × 100 × coste / n` y **no es lineal**. La cabecera del módulo justificaba ignorarlo («el tamaño no entra, se cancela»), cierto solo con múltiplos exactos de 100. La cuenta existía pero colgada de un 4º parámetro opcional y sin documentar: no se usaba nunca. Ahora `/evf TICKER COSTE` a secas da un veredicto **por estrategia**, con las acciones estimadas al precio del momento. Con WYHG a 5,22 y locate 0,258, pasar de **300 a 301 acciones da la vuelta al veredicto** (+1,06 pp → −0,57 pp).
- **REGLA QUE NO SE PUEDE ROMPER:** el tamaño de `/evf` es una ESTIMACIÓN al precio de consulta y **no debe** coincidir con el del aviso — el aviso sale de su propia vela y es la orden que se teclea en el bróker. Igualarlos daría un tamaño de entrada equivocado (decisión explícita de Jaume). La consulta es de solo lectura y no llama al motor de señales.
- **Los otros dos avisos no tenían el problema:** el de pirámide saca las acciones de `pyr_executions` y el de salida de los trades, o sea del propio simulador. La entrada era el único sitio con un cálculo PARALELO, y por eso el único que podía divergir.
- **Dónde:** `bot_alerts_engine.py` (`stop_estimado`, `estimar_por_estrategia`, `_cangrejo_de`, `_tope_cangrejo_acciones`), `bot_alerts_runner.py` (`estimacion_locates`), `bot_alerts_comandos.py`, `bot_alerts_service.py`, `routers/bot_alerts.py`, y el cableado en `D:\bot_senales\bot.py` (fuera de git).
- **Verificación:** `test_bot_tamano_todos_los_stops.py` (14 tests) cruza el tamaño del aviso contra el que abre `portfolio_sim` DE VERDAD, para cada tipo de stop (porcentaje, importe fijo, ATR, estructura) × cada modo (valor de mercado, por distancia al SL, híbrido, Cangrejo A y B). Más `test_evf_paquetes_de_100.py` (23). Suite: **904 passed, 115 skipped**.
- **OJO AL AUDITAR:** la UI solo ofrece DOS tipos de stop (`%` y `Market Structure`). `Fixed Amount` y `ATR Multiplier` existen en el enum y en el motor pero **el desplegable no los ofrece**: son inalcanzables, otro ajuste fantasma como el «Max DD Diario».
- **Los 27 tests saltados:** vinieron de `staging` al igualar las ramas. Tres ficheros prueban motor de Álvaro que aquí no está (`trail_activation`, parciales por fade, atribución de fees) — la huella de la norma «el socio sube documentos, no motor», funcionando. El cuarto (`test_bygap_parity`) NO es eso: necesita `local_data.duckdb` en exclusiva y falla con el backend levantado.
- **Estado:** SUBIDO a `sailor-rama-desarrollo` y a `staging`, las dos en `356019d` e idénticas.

### [FEATURE · 2026-09-08 · PESTAÑA EDGE] «¿Se está erosionando el edge?» — pestaña nueva en los resultados del backtester (Jaume + Claude)
- **Origen:** en 1B, salir a las 08:30 gana más que a las 09:00 y hace un año era al revés. ¿Ruido o cambio de régimen? Con PF modesto hacen falta cientos o miles de operaciones para distinguirlo por el PnL; la pestaña mide cosas con más señal por observación.
- **Dónde va:** entre «Análisis por trade» y «Charts + Optimization IS», y **NO dentro de Optimization** a propósito: aquella responde «¿cuál es el mejor valor?» y siempre devuelve uno; esta responde «¿debo cambiar algo?» y su respuesta correcta suele ser NO.
- **Cuatro fases:** ¿se puede leer? (comparabilidad y muestra) → ¿ha cambiado el edge? (expectancy por periodo CON intervalo de confianza, descomposición ganadoras/perdedoras, concentración de la cola con la expectancy debajo, oportunidad contra edge) → ¿dónde y por qué? (curva de valor marginal por hora, MFE/MAE con líneas de tendencia y ratio, tiempo hasta el MFE, barridos de TP y SL sin correr nada, envolvente Monte Carlo del drawdown) → ¿cambio algo? (delta PAREADO entre dos horas con veredicto de tres estados: CAMBIAR / CUIDADO / SIN CAMBIOS, según cuántas de las tres llaves se cumplen).
- **Decisiones de método:** todo en R; el barrido de SL empieza en el 1 % (por debajo la vela de un minuto no tiene resolución y salen R imposibles); `return_pct` NO es el % de precio (va sobre capital en riesgo) y se reconstruye `movePct` desde los precios; la comparación de horas es pareada (solo el tramo A→B, varianza mucho menor). Regla de las tres llaves para tocar un parámetro; al cambiar, con encogimiento (al punto medio).
- **El recorrido minuto a minuto** (curva, delta y tiempo hasta MFE) va por un endpoint aditivo `POST /api/edge/recorrido` que relee la caché de velas — **no toca el motor**. Contrafactual: solo se prolongan las salidas por EOD/Time Limit; al prolongar, el stop original SIGUE puesto; el horizonte alarga, nunca recorta; tras cerrar el valor se arrastra. Devuelve solo agregados.
- **Diseño (Jaume):** cuadrado y sobrio como el genético; cada «?» con Qué ves · Por ejemplo (con las cifras de la corrida abierta) · Para qué sirve · Cómo leerlo (TODAS las combinaciones) · Ojo. **Regla que se incumplió y se corrigió:** un escenario solo puede describir algo que se vea en SU gráfico. Selector de periodos compartido por los tres gráficos de líneas; la rampa de color se calcula sobre la lista completa o los colores bailan.
- **Hallazgo en `RTH prueba 1`:** el punto donde deja de compensar aguantar se adelantó de las 14:05 (2021) a las 11:45 (2026) y el tiempo hasta el MFE bajó de 100 a 34 min; el delta 11:45→14:15 ganaba en 2021-23 y desde 2024 ya no — pero el margen de 2026 aún cruza el cero: veredicto CUIDADO, no CAMBIAR. Justo el caso para el que existe.
- **Trampas:** los separadores `──` en comentarios .ts/.tsx tumban el dev server de Next (panic en `next-code-frame`); `API_BASE` ya termina en `/api`; la agregación del recorrido se densifica sobre rejilla de 5 min o es O(n³).
- **Dónde:** `frontend/src/components/backtester/tabs/{EdgeTab.tsx, edge/calc.ts, edge/charts.tsx}`, `ResultsTabs.tsx`, `lib/api_edge.ts`; `backend/app/services/edge_service.py`, `routers/edge.py`, 2 líneas en `main.py`.
- **Estado:** SUBIDO a `sailor` y `staging` (`1ee4ee9`, `b16356b`).

### [FEATURE · 2026-09-08 · LOCATES] Locates ALEATORIOS por ticker-día + PUERTA DE ENTRADA POR EV en sombra (Jaume + Claude)
- **Por qué:** el precio fijo por paquete no es la realidad; la cola es brutal (una sola operación se llevó 7.000 $). Y en vivo Jaume decide si entra según el `/evf`: fade necesario contra EV.
- **Fase 1 — sorteo.** `locates_random.py`: precio del paquete de 100 sorteado **por ticker-día** (las reentradas y pirámides reutilizan el locate, como ya cobra el motor), **determinista por hash de (semilla, ticker, fecha)** — no depende del orden de proceso, dos corridas con la misma semilla dan lo mismo —, centro en escala log del precio de la acción entre 0,10 $ (suelo del universo) y 30 $, lognormal σ 0,35 recortado al rango. Sin anclas del usuario: solo el rango, «que se distribuya solo». Referencia: la primera vela del frame (04:00), causal. Fuerza la vía secuencial y no toca el motor. Medido con rango 1-10: 0,30 $ → 2-3,9; 3 $ → 4,6-9; 15 $ → 6,4-10. En `RTH prueba 1` los locates a 1-10 se comían casi todo el beneficio (stop al 25 % = muchos paquetes).
- **Fase 2 — la puerta.** `locates_gate.py` + `simulate(ev_gate=None)`: la cuenta del `/evf` trade a trade con **paquetes enteros y coste MARGINAL** (la reentrada que cabe en lo alquilado pasa gratis). **EV «en sombra» a DOS PASADAS:** la primera sin puerta da lo que rinden TODAS las señales en % de precio (cortos, bruto de locates); la segunda solo entra si el EV rodante (N trades o N días, con EV por defecto mientras no hay historia) de la sombra cerrada ANTES de ese instante cubre el fade. Jaume lo eligió sabiendo que en vivo tendrá el EV de lo ejecutado (con su sesgo: si rechazas no entra información nueva); esa variante queda como conmutador futuro. Con `ev_gate=None` el motor es byte a byte el de siempre.
- **E2E en `RTH prueba 1`** (rango 1-10, semilla 2, ventana 30 trades, EV defecto 2 %): 1.943 señales en sombra, 5.228 evaluaciones (una rechazada se consume y puede volver a saltar), 1.067 aceptadas / 4.161 rechazadas. **Con puerta +1.975 $ y maxDD −12,4 %; sin puerta +1.771 $ y −13,3 %, con un 45 % menos de operaciones.**
- **TRAMPA QUE COSTÓ UNA CORRIDA: el kernel numba está ACTIVO en esta máquina** (`BACKTEST_NUMBA_SIM=1` en `backend/.env`). `sim_dispatch` mandaba al JIT, que no conoce `ev_gate`: cada ticker-día fallaba y la corrida acababa con CERO trades sin error en pantalla. Arreglado con el mismo desvío que la piramidación. **Todo parámetro nuevo de `simulate` necesita su desvío en `sim_dispatch` o su porte al JIT.**
- **UI:** bloque «Costes opcionales» reorganizado (Fijo|Aleatorio, rango, semilla, puerta con Trades|Días, ventana, EV por defecto, mín. trades, todo con «?» largos); en Trades, columnas Locate/100, EV%, Fade% y resumen deduplicado por ticker-día. Con el modo activo el locate se pega a cada trade (`locate_pkg_price`, `locates_fee_day`, `ev_gate_*`).
- **Fase 3:** la banda de N semillas quedó HECHA la misma noche (entrada siguiente); pendiente solo el conmutador «EV de lo ejecutado».
- **Dónde:** `backend/app/services/{locates_random,locates_gate,backtest_service,backtest_orchestrator,portfolio_sim,sim_dispatch}.py`; `frontend/src/{components/backtester/{BacktestPanel,ResultsTabs,tabs/TradesTab}.tsx, lib/api_backtester.ts, app/backtester/page.tsx}`. Pruebas sintéticas: sorteo (8), puerta (6).
- **Estado:** SUBIDO a `sailor` y `staging` en `d43133a`.

### [PRD · 2026-09-08 · MÉTRICAS Y OOS] PRD de Álvaro revisado: las 4 cosas eran ciertas; Jaume aprobó las 4 y quedaron hechas
- **Dos matices de Jaume que NO son bug:** correr todo el rango con IS < 100 es a propósito (quiere ver el OOS con las mismas condiciones; el navegador recorta al pintar); y la curva punteada «con gastos» SÍ existe — lo que iba bruto de gastos fijos eran los números de la tarjeta.
- **P1 IS/OOS persistido:** `is_percent` entra en `BacktestRequest` (Pydantic lo tiraba) y `metricas_segmento.py` calcula `is_metrics`/`oos_metrics` con el MISMO corte que el navegador (índice de equity `floor(len·is/100)`, trades por `entry_time_epoch`, días por medianoche UTC, PnL neto de locates por día). Con IS 100, nulos. El motor sigue corriendo todo.
- **P2 Return/Calmar:** `total_return_pct` pasa a NETO de gastos fijos (`total_return_pct_gross` conserva el bruto); `calmar_ratio` = CAGR neto / |maxDD| (sin anualizar por debajo de 30 días; `calmar_ratio_total` conserva el antiguo). Tooltips dicen lo que se calcula y enseñan los dos. El memo IS del navegador calcula lo mismo. `expectancy` sigue bruta de locates a propósito (decisión anterior).
- **P3:** `total_return_r` (ΣR) en `aggregate_metrics`: la columna y el filtro «beneficio neto mínimo» del buscador iban siempre a 0.
- **P4:** `backtest_params` guarda las fechas EJECUTADAS (`rango_efectivo`: lo resuelto por `_resolve_filters` y primer/último día simulado); lo tecleado queda en `*_pedido`.
- **Para Álvaro (no está en su PRD):** el optimizador corta el IS por nº de fechas (`optimization_service.py:997`) y la UI/servidor por índice de equity — dos definiciones a unificar; las fechas raras del P4 vienen de que `_resolve_filters` sustituye el rango pedido; el Modo B de Cangrejo aplica también a pirámides (divergencia consciente).
- **Verificación:** 3 pruebas sintéticas; Jaume lo vio funcionar por encima con IS 90 la noche del 8 y **quiere revisarlo con calma el 9**. Ni un trade cambia.
- **Estado:** SUBIDO a `sailor` y `staging` en `d43133a`.

### [VERIFICADO · 2026-09-08 · CANGREJO EN EL BOT] El bot de alertas SÍ aplica los dos modos en entrada y pirámides (solo lectura, nada que cambiar)
- Entrada: `calcular_acciones` aprieta el stop (Modo A, el aviso da el APRETADO) y topa las acciones (Modo B) sobre la distancia ya apretada, con el capital del cuadro de mandos; también sin `size_by_sl`. Pirámides: el bot no dimensiona, toma `size` de `pyr_executions` del simulador Python, al que pasa los tres campos y `hybrid_capital` real → Modo B con el presupuesto que queda, Modo A por el stop apretado. `/watch` bloquea el Modo B sin capital; `limpiar_inactivo` no toca los campos. Bot y programa apagados la noche del 8: mañana arrancan de cero con todo lo de hoy.

### [FEATURE · 2026-09-08 · BANDA DE LOCATES] Monte Carlo sobre la semilla de los locates, SIN volver a correr (Jaume + Claude)
- **La pregunta:** «entre qué dos curvas voy a acabar según me toquen los locates». Respuesta en segundos gracias a un atajo: sin puerta por EV, cambiar la semilla NO cambia ni un trade, solo lo que cuesta cada ticker-día. Con la corrida abierta se recalcula la factura para N semillas (`ceil(máx. corto del día/100) × precio_locate(ref, min, max, semilla, ticker, fecha)`) y de ahí salen N curvas de equity por fecha (PnL de los cierres del día menos factura del día; neta de locates, bruta de gastos fijos, igual que la curva principal).
- **Dónde va:** CUARTA sub-pestaña de «Charts + Optimization IS» (Charts | What if and Stress test | **Banda de locates** | Optimization Surface). Bloque propio, `BandaLocates.tsx`; la equity/drawdown de siempre NO se toca. Endpoint aditivo `POST /api/locates/banda` (`routers/locates.py` + `services/locates_banda.py`), recibe trades compactos + rango + N + semilla base + semilla actual; devuelve percentiles por fecha (p10/p50/p90/min/max), finales y peor caída por semilla, y la curva de la semilla de la corrida. Tope 200 semillas.
- **Qué se ve:** abanico p10–p90, mediana, mejor/peor, tu semilla en blanco; curva «sin locates» en un check apagado por defecto (con +11.819 $ brutos aplastaba la banda); cifras «acabas entre / mediana / peor semilla / peor caída / factura media / tu semilla con su percentil»; histograma de la peor caída por semilla (reutiliza `Histograma` del Edge, que ahora admite un pie opcional); veredicto en texto por anchura relativa de la banda (<10 % poco, <40 % relevante, si no enorme) y por lo que se llevan de media.
- **CUADRE con el motor:** la semilla de la corrida reproduce EXACTAMENTE lo que dio el motor (`RTH prueba 1`, semilla 2: +1.975 $ y −12,4 %). **Trampa que rompió el cuadre la primera vez:** `result.locates_random.min/max` es el resumen de lo SORTEADO (su min es el mínimo observado, 1,52), no el rango configurado (1,0): prerrellenar con él sobrecargaba 361 $. El rango sale de `backtest_params.locates_random_min/max`.
- **Con puerta por EV es APROXIMACIÓN y la pantalla lo avisa:** la puerta dejó entrar los trades baratos BAJO ESA semilla; al mantenerlos y cambiar el precio, tu semilla sale arriba del todo (percentil 98 en la prueba). No es fallo. La versión exacta (una pasada por semilla, ~10 semillas) queda para más adelante si la quiere.
- **Lectura de `RTH prueba 1` con 50 semillas:** acabas entre +1.067 y +1.363 $, mediana +1.195 $, peor +967 $, peor caída −15,2 %, factura media −10.605 $. La banda es estrecha (297 $, 2,5 %): la suerte con la semilla pesa poco; lo que pesa es la media, que se lleva el 89,7 % del edge bruto.
- **Detalles de UI que pidió Jaume:** separador entre sub-pestañas (se coló detrás en vez de delante); cifras de millones desbordaban la casilla por un `nowrap` — ahora «acabas entre» va en dos líneas y el resto parte en vez de pisar. El reloader de uvicorn se volvió a quedar colgado al guardar el backend (worker de las 19:29 con código de las 21:21): matar padre e hijo y arrancar limpio.
- **Pruebas:** 4 sintéticas (orden min≤p10≤p50≤p90≤max≤bruta, determinismo y semilla reproducible, solo cortos pagan y paquetes enteros sobre el máximo del día, 200 semillas). `tsc` limpio.
- **Estado:** SUBIDO a `sailor` y `staging` en `a9066dc`.


---

## 2026-09-09 · La mañana que el bot no dio alertas: cinco fallos a la vez, ninguno con error

Jaume se fue toda la mañana con el bot «funcionando» y perdió acciones que debían
haber saltado. Su socio lo vio en un vistazo. **Yo le dije dos veces que todo iba
bien mirando que el proceso estuviera vivo y el feed conectado, sin comprobar lo
único que decidía si habría alertas: qué acciones miraba y contra qué cierre.**

Los cinco fallos son independientes y ninguno daba excepción ni log. Están en
`8ca10fb`, subido a `sailor` y `staging`.

### [BUG · UNIVERSO] Se miraban 1.457 acciones de 5.693, desde el 4-sep

`cargar_universo()` pagina la lista de tickers y el cursor de la página siguiente
viene DENTRO de `next_url`. El código pasaba el cursor en la URL y la clave en
`params`, y **httpx 0.28 SUSTITUYE la query de la URL por `params` en vez de
fusionarla**: se perdía el cursor y la paginación moría en la primera página.

    python del venv    ->  5.693 acciones
    python global      ->  1.457 acciones

**El bot arranca con el Python GLOBAL** (`arrancar_bot.bat`), que es el que tiene
httpx 0.28.1. Empezó el 4-sep-2026 a las 11:52, la hora exacta a la que se cambió
el `.bat` de intérprete. Cuatro días de mercado. **Lo rompí yo.**

«Ayer funcionaba» era casualidad: ARBE, BNC y WYHG estaban dentro de esa cuarta
parte; YMAT y FGL, fuera. Arreglado pegando la clave a la URL, **y con aviso**: si
carga menos de 3.000 acciones ahora hace `logger.error`.

### [BUG · CIERRE DE AYER] Era el de tres sesiones atrás

`cierres_de_ayer()` usaba `prevDay.c` del snapshot del mercado, y **ese campo
depende de la hora a la que preguntes**:

    a las 01:15 NY  ->  prevDay.c de YQ = 2,92   (cierre del VIERNES 4)
    a las 04:20 NY  ->  prevDay.c de YQ = 3,79   (cierre del MARTES 8)

Y se pedía una sola vez al arrancar. Con 2,92 YQ daba un gap del 61 % y entraba en
1B; con 3,79 daba 24 % y no debía. Y al revés: gaps buenos que no llegaban al
umbral. **Jaume no se creyó la explicación y tenía razón**: el cierre del martes
existe desde el martes a las 16:00; el dato no faltaba, se pedía por la puerta
equivocada.

Ahora se pide por fecha explícita con `aggs/grouped/locale/us/market/stocks/{fecha}`:
~12.500 cierres oficiales en UNA llamada, y no depende de cuándo preguntes.

**Trampa que costó encontrar:** ese endpoint responde también para una sesión A
MEDIAS. El 9-sep a las 11:53 de Nueva York, con el mercado abierto, pedir «los
cierres del 9» devolvía 11.149 filas y YQ a 4,20 — el precio de ese instante, no su
cierre. Por eso se exige un mínimo de 8.000 filas antes de aceptar un día.

### [BUG · BOTÓN] «Vigilar» no encendía nada

Solo escribía `vigilando=True` en la base y esperaba a que el bot lo leyera. Si el
proceso no existía, no pasaba nada — y la página lo pintaba igual. Ese día el bot
murió al arrancar (07:01) porque el backend (06:58) todavía estaba abriendo los
63 GB, y Jaume empezó la jornada creyendo que vigilaba.

Ahora `POST /api/bot-alerts/estado` comprueba el latido y **arranca el bot** si no
lo hay, devolviendo `proceso_vivo`, `arrancado_ahora` y un `aviso`. **Al apagar NO
se mata el proceso**: apagar es «deja de operar», y matarlo perdería el máximo de
premercado acumulado, que es la condición de 1B.

Primera versión mal: lanzaba PowerShell con `subprocess.run` y timeout de 25 s en un
endpoint síncrono, y **bloqueaba el backend entero**. Jaume lo detectó en minutos. Se
mira por el latido, no por la lista de procesos.

### [FEATURE · CALENDARIO] Festivos de NYSE, medias sesiones y horario de verano

Lo pidió Jaume. El bot está pensado para no apagarse nunca, así que no le vale con
«son las 10:30»: un jueves de Acción de Gracias decía «RTH» y se quedaba esperando
velas que no iban a llegar, sin forma de distinguir ese silencio de una avería.

**No hace falta copiar la lista de NYSE a mano.** Massive la expone en
`/v1/marketstatus/upcoming`, con las medias sesiones y su hora exacta.

`bot_alerts_calendario.py` usa **dos fuentes a propósito**: las reglas se calculan en
el módulo, **sin red y para cualquier año** —porque el bot arranca con el Python
global y cada dependencia nueva ahí es una que puede faltar, que es exactamente cómo
se rompió el universo el día 4—, y Massive se pide **una vez al día en otro hilo** y
solo puede añadir o corregir, para lo que ninguna regla predice (el huracán Sandy
cerró el mercado dos días en 2012).

**Cotejado: 12/12 en estado contra la lista oficial y 25/25 contra datos reales** del
mercado (festivo = 0 filas, media sesión ≈ 11.600, día entero ≈ 12.500).

**LA TRAMPA DEL 31 DE DICIEMBRE.** La regla general pasa un festivo en sábado al
viernes anterior, **pero NYSE tiene la excepción de que ese viernes no sea el último
día de negociación del año**. O sea que con Año Nuevo en sábado, el 31 SE NEGOCIA:

    31-dic-2021 (viernes, 1-ene-2022 en sábado)  ->  11.151 cierres. HUBO SESIÓN.
    31-dic-2010 (ídem)                           ->   7.401 cierres. HUBO SESIÓN.

La tenía mal y la cazó un test. No es un detalle: ese 31 es justo el cierre contra el
que se miden los gaps del primer día de enero.

**El horario de verano ya estaba resuelto, pero no por donde parecía.** Todo se
cuenta en hora de Nueva York, así que la apertura son las 09:30 haga el horario que
haga y al bot no le afecta. A quien opera desde España sí: los cambios no caen el
mismo día (EEUU 2º domingo de marzo → 1er domingo de noviembre; España último domingo
de marzo → último domingo de octubre), y en 2026 quedan **dos ventanas —del 9 al 28
de marzo y del 26 de octubre al 1 de noviembre— en que el mercado abre a las 14:30 de
España y no a las 15:30**.

Al engancharlo, `cierres_de_ayer()` va directo a la sesión buena en vez de tantear día
a día, y eso arregló **un falso positivo**: con Labor Day el salto era de 4 días y
saltaba un `logger.error` rojo sin que pasara nada.

### [BUG · CONEXIÓN] Una de cada cuarenta peticiones al backend se perdía

El cliente del bot reutiliza las conexiones. **Pregunta cada 5 segundos
(`INTERVALO_ESTADO`) y el keep-alive de uvicorn son 5 segundos**: uno reutiliza la
conexión justo cuando el otro la está cerrando.

**El hueco lo es todo, y por eso buscarlo mal no encuentra nada.** Medido contra el
backend real, 16 clientes en paralelo:

    huecos de 12 s (pasado el límite)  ->   0 fallos de  18
    huecos de  5 s (en el límite)      ->  19 fallos de 832   (2,3 %)
    ídem, con reintento                ->   0 fallos de 832

Mi primer intento usó 12 segundos, salió limpio, **y me hizo dar por buena una
explicación equivocada delante de Jaume**. Con huecos cómodos el cliente ve el socket
cerrado y abre otro tan tranquilo; la carrera solo existe justo en el borde.

No era cosmético: `debe_vigilar()` devuelve `None` al fallar y el bot se queda como
estaba, así que un fallo justo al pulsar «Vigilar» retrasaba el interruptor un ciclo
entero. Es la queja de Jaume de «le doy y no se entera».

Falla **siempre la primera petición después del hueco**, que en el bot es el GET del
estado: de 832 peticiones, 19 fallos y los 19 en el GET. Se reintentan también los
POST por prudencia (cualquier reordenación futura dejaría el hueco delante de uno), y
es seguro: `/eventos` hace `INSERT OR REPLACE` con id estable **y no manda Telegram**
—los avisos los manda el bot—; el resto sobrescribe estado. Los timeout NO se
reintentan: ya han esperado 8 segundos y repetirlos dejaría al bot parado 16.

### [FEATURE · TELEGRAM] Las señales de salida dicen cuántas acciones cerrar

Lo pidió Jaume: «si solo cierro un 25 %, me gustaría que me dijera cuántas acciones
son ese 25 %». Ahora el aviso distingue CIERRE POS. de CIERRE PARCIAL y añade:

    Acciones a cerrar: 507
    (25 % de 2.028 · quedan 1.521)

Sin eso había que echar la cuenta a mano con el mercado abierto.

### Lo que hay que aprender de esto

**Comprobar el bot es mirar QUÉ mira, no si respira.** Proceso vivo + feed conectado +
Telegram OK no significa nada. Lo que hay que mirar:

    universo de N acciones     -> tiene que rondar 5.700
    N cierres de ayer cargados -> tiene que rondar 5.500
    del dia AAAA-MM-DD         -> tiene que ser la ULTIMA SESION

Y **reproducir un fallo intermitente exige las condiciones exactas**, no unas
parecidas: 12 segundos en vez de 5 convirtieron un 2,3 % en un 0 % y me llevaron a una
conclusión falsa que tuve que retirar.

**Falsa alarma que conviene no repetir:** al mirar los procesos vi dos uvicorn en el
8010 y avisé de que se peleaban por el puerto. No era cierto — uno es de 4 MB y el
otro de 392 MB con 49 hilos, padre e hijo, **un solo backend**. Lo que delata cuál
sirve de verdad es la memoria, no el nombre del intérprete.

**Estado:** 69 tests nuevos (59 del calendario, 10 del reintento). **973 pasan, 0
fallan.** SUBIDO a `sailor` y `staging` en `8ca10fb`. `D:\bot_senales\bot.py` va
aparte porque vive fuera de git y no entra en los commits.

### [CORRECCIÓN · 2026-09-09 · EL BOTÓN] Seguía sin encender a la primera, y lo encontró una revisión posterior

Una revisión multiagente del cambio de arriba sacó **26 hallazgos; 18 se
refutaron y quedaron 8**. Uno era grave, y estaba justo en lo que yo había dado
por arreglado y contado como resuelto.

**`cambiar_estado` guarda `vigilando=True` y lanza el `.bat`. Pero `bot.py`
llama a `dejar_parado()` nada más arrancar**, así que entre 10 y 40 segundos
después de pulsar —lo que tarda en importar pandas y pedir las estrategias—
llegaba su POST poniendo el interruptor en `False`. La página se volvía sola a
«Parado» y el bot se quedaba **vivo pero mudo**. Había que pulsar **dos veces**;
la segunda funcionaba porque ya había proceso y no se relanzaba.

Ese apagado no sobra: existe para que dejar el interruptor encendido un día no
haga que el bot se ponga a vigilar solo al día siguiente. Lo que fallaba es que
no distinguía quién lo había lanzado.

**Y explica lo que vi el 9-sep a las 17:50 y leí mal.** Jaume pulsó el botón, el
bot arrancó, y cuando miré el estado el interruptor decía `False`. Lo interpreté
como «todavía no le ha dado» y di el arreglo por bueno. Estaba viendo el bug.

Arreglado con la variable de entorno `BOT_ALERTS_ARRANCADO_POR_LA_PAGINA`, que
el backend pone al lanzar el `.bat` y `bot.py` mira antes de apagarse. Va por
entorno y no por argumento del `.bat` para no tocar el lanzador, que es de Jaume
y vive fuera del repo. Comprobado en el log real, los dos caminos.

**Los otros tres de código:**

- **La petición de cierres bloqueaba el bucle de eventos.** El refresco al
  cambiar de día llamaba a `cierres_de_ayer()` de forma síncrona dentro de
  `async def bucle()`: una petición HTTP de hasta un minuto congelando el
  proceso entero, feed del websocket incluido. **Lo metí yo ese mismo día.**
  Ahora va por `asyncio.to_thread`.
- **La lista oficial se daba por pedida antes de llegar.** `_pedido_el` se
  marcaba antes de lanzar la petición, así que un timeout dejaba el proceso 24
  horas solo con las reglas y sin decirlo. Ahora se marca al llegar, con suelo
  de 10 minutos entre intentos (`franja_de_mercado()` se llama en cada latido:
  sin suelo sería una petición cada 5 segundos) y una línea de log cuando entra.
- **Un error viejo se colaba como si fuera de los cierres.** `ultimo_error` lo
  comparten el universo, el barrido y `cierres_de_ayer()`, y el bot lo imprime
  como «OJO con los cierres» justo después de esa llamada.

**Y cuatro huecos de tests**, que es donde más útil salió la revisión:
`cierres_de_ayer()` —la mitad del cambio del día— **no tenía ninguno**; la
traducción del JSON de Massive tampoco (romper el literal `early-close`
convierte toda media sesión en cierre entero, y la lista oficial manda sobre las
reglas); el ritmo del refresco diario no se comprobaba; y un test era
tautológico —miraba el 2 de julio, una fecha que la regla no genera nunca—.

También salió **código muerto mío**: una guarda para la víspera del 4 de Julio
que no puede alcanzarse nunca, porque las dos condiciones anteriores ya cubren
los dos casos posibles. Fuera, y escrito para que nadie añada una tercera.

**Lo que hay que aprender:** el arreglo del botón lo di por bueno **mirando que
el bot arrancara**, que es la misma clase de error que cometí por la mañana —
comprobar que respira en vez de comprobar qué hace—. Y el estado que lo delataba
lo tuve delante y lo leí como si fuera lo esperado.

**Estado:** 992 tests pasan, 0 fallan (eran 973). `faca7d6` en `sailor` y
`staging`.

### [FEATURE · 2026-09-10 · BANDA DE LOCATES] Bootstrap al lado de la banda: «¿ganaría igual con otro histórico?» (Jaume + Claude)
- **La pregunta de Jaume:** si el Monte Carlo de las semillas se puede llevar más lejos «para asegurarnos sí o sí de que la estrategia soporta esas comisiones independientemente del histórico que ocupe». Sí, pero **no sobre las tres curvas p10/p50/p90**: son percentiles fecha a fecha, no escenarios (ninguna semilla vive la curva p10), y remuestrearlas sería promediar promedios.
- **La distinción que lo hace funcionar:** hay que volver a las OPERACIONES, y **con reemplazo, no reordenando**. Una permutación suma los mismos números en otro orden → el resultado final es idéntico por construcción y solo cambia el drawdown (eso ya lo hace `envolventeDD` del Edge). Para que el resultado se mueva hay que sacar una MUESTRA distinta.
- **La unidad es el ticker-día**, no la operación: el locate se alquila por día y las reentradas y pirámides comparten paquete. Sorteando operaciones sueltas se rompe la aritmética de los paquetes.
- **Implementación** (`locates_banda.bootstrap`): matriz de coste [semilla de precio × ticker-día] reutilizando las MISMAS semillas de la banda, y luego puro numpy — cada réplica elige una fila de precios y N índices con reemplazo. Réplicas por trozos para acotar memoria y eje X submuestreado a 400 pasos. 500 réplicas × 600 unidades en 0,26 s. Devuelve percentiles por paso, el **% de historias que acaban ganando (con y sin locates)**, percentiles del resultado y el drawdown. Es un extra del endpoint: si falla, la banda se devuelve igual.
- **Lo que enseña, y es el motivo de existir:** la banda de semillas sale estrecha SIEMPRE (cientos de sorteos independientes que se compensan al sumarlos) y la gente decide con ella. En la prueba sintética: ancho 299 $ por el precio contra 4.630 $ por la racha, y **100 % de historias ganan sin locates contra 16 % con ellos**. La incertidumbre que importa no es la que se estaba midiendo.
- **DOS AVISOS que van escritos en la pantalla, no solo aquí:** (1) el bootstrap supone que todas las operaciones salen de la misma bolsa — si el edge se ha degradado (y la pestaña Edge dice que sí), mezcla 2021 con 2026 y da una respuesta OPTIMISTA; (2) **caída máxima ≠ pérdida final**: una historia puede hundirse un 77 % por el camino y acabar ganando porque los días buenos le llegan después. Lo que significa de verdad es que esa cuenta no llega viva a la recuperación. Y el simulador reparte el mismo dinero por operación de principio a fin: no encoge el tamaño cuando la cuenta baja.
- **Lección de diseño (la pilló Jaume):** dos filas de cifras con las mismas etiquetas («Acabas entre», «Mediana») son ilegibles aunque cada número sea correcto — y encima el p5 salía dos veces en la misma fila. Arreglado con **franjas numeradas ① y ② que repiten el número de su gráfico**, cero cifras repetidas, y etiquetas que dicen qué son en vez de citar el percentil («Lo más probable», «Lo que pagas de alquiler», «Caída máxima por el camino»).
- **Dónde:** `backend/app/services/locates_banda.py` (+ `bootstrap`, `_unidades`, `_dd_filas`), `backend/app/routers/locates.py` (`n_replicas`), `frontend/src/{lib/api_locates.ts, components/backtester/BandaLocates.tsx}`. Pruebas: 6 sintéticas + la llamada real al endpoint.
- **Y otra vez el `--reload` colgado** (worker de las 15:30 sirviendo código de las 15:48): la señal fue que el endpoint devolvía la banda pero `bootstrap` venía a `None` SIN error, porque el router viejo no tenía ese bloque. Matar padre e hijo y arrancar limpio.
- **Estado:** SUBIDO a `sailor` (`b57beb6` + `34a7006`). **A `staging` NO**: ha divergido, ver la entrada siguiente.

### [AVISO · 2026-09-10 · RAMAS] `staging` ya no admite push directo desde sailor: Álvaro ha metido las estrategias compartidas
- `origin/staging` tiene **4 commits que sailor no tiene** (`6c4c3a7` pestaña «Compartidas», `7e9fef6` y `a302026` estrategias de Álvaro, `2ddec25` su guía para nosotros), y sailor tiene 11 que staging no tiene. El `git push origin sailor:staging` de siempre sería rechazado, y forzarlo **borraría el trabajo de Álvaro**. Hay que integrar antes.
- **Su feature, revisada de verdad (no solo leída):** el traversal está cerrado en serio (regex tanto en el nombre de fichero como en la subcarpeta del dev), el import reusa el `POST /api/strategies/` existente sin tocar schema, y el transporte es git — la app solo lee y escribe ficheros, nunca sube nada sola.
- **Comprobación que su guía no menciona y que aquí es la que muerde:** importar una estrategia con un `definition` que use algo que nuestra rama no tenga se caería EN SILENCIO ([[listas blancas en tres capas]]). Contrastados los 14 tipos de «G&E GENETICO - La Buena» contra nuestra rama: **están todos**, incluido `cangrejo_mode: 'perdida'`, que es valor válido de nuestro `Literal`. Se puede importar sin miedo.
- **Su guía está desfasada en un punto:** dice `cherry-pick 6c4c3a7 7e9fef6`, pero `a302026` sustituye a `7e9fef6` (renombra el JSON: «La Buena» reemplaza a «10k»). Lo correcto es `6c4c3a7` + `a302026`.
- **Lo que costará:** conflicto seguro en `ResultsTabs.tsx` (él añade la pestaña «Compartidas», nosotros la sub-pestaña «Banda de locates») y probablemente en `main.py` (nosotros metimos el router de locates). Los dos triviales. Y hace falta `SHARED_STRATEGIES_OWNER=sailor` en `backend/.env` (que no se commitea) o las compartidas de Jaume caen en `dev/`.
- **Ojo al importar:** el JSON lleva el `dataset_id` de Álvaro, que no existe en la base de Jaume. Hay que reasignarlo a mano tras importar.

