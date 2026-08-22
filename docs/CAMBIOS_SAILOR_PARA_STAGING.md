# Cambios de la rama de Sailor — nota para staging

> **Qué es esto.** Un resumen de lo que se ha tocado en
> `sailor-rama-desarrollo`, escrito para que el otro desarrollador decida qué
> quiere adoptar y qué no. **No es una petición de merge.** Buena parte de esto
> es específico del entorno local de Sailor (lago de datos propio en `D:`,
> 16 GB de RAM) y no tiene por qué tener sentido en producción.
>
> El detalle completo, con números medidos y los callejones sin salida, está en
> `Base de datos Backtester/docs/MEMORIA.md` (fuera de este repo).

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

## Cambios de sesiones anteriores pendientes de coordinar

- **Comisiones `PERCENT`**: se cobran sobre el NOCIONAL de cada lado
  (entrada + salida), no sobre `|PnL|`. Un breakeven también paga comisión.
- **El Baúl (`/database`) y el `PortfolioBuilder` viejo están borrados** en esta
  rama.
