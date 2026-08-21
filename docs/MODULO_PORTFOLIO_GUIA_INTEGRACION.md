# Módulo Portfolio — guía de integración

**Autor del módulo:** rama `sailor-rama-desarrollo` (Jaume + Claude).
**Fecha:** 2026-08-21.
**Estado:** funcionando y verificado en local; **apagado por defecto** en esta rama.

Este documento es para la IA (o la persona) que vaya a trabajar con el módulo en
`staging`. Explica qué es, cómo encenderlo, de qué depende, qué NO se ha traído
a propósito, y los puntos que hay que acordar entre las dos ramas.

---

## 1. Qué es

Una página nueva, `/portfolio`, para **estudiar varias estrategias como una sola
cartera**: cuánto rinden juntas, cuánto se solapan, qué drawdown esperar del
conjunto, cuánto riesgo asignar a cada una, y cómo se compara todo eso con la
operativa real del trader.

El principio de diseño es el mismo que el de Robustez: **se trabaja SOBRE LAS
CORRIDAS YA GUARDADAS**. No re-ejecuta backtests (salvo en la Monitorización,
que sí lo hace explícitamente y bajo petición). Cada estrategia se normaliza a
un dominio común — R por trade, sin costes — y desde ahí la combinación, la
correlación y la re-aplicación de costes son reconstrucción pura.

### Las tres pestañas

**Baúl** — inventario de estrategias con dos cuadros de destino: *Portfolio*
(las que se estudian juntas) e *Incubadora* (listas para operar, en
observación). Al desplegar una fila se ven TODAS sus condiciones (universo,
entrada, salida, riesgo, ejecución) y un minigráfico de sus últimos 6 meses
simulados.

**Portfolio** — con tres sub-vistas:
- *Imagen general*: la unión lineal de N estrategias con pesos iguales. Curvas
  por estrategia + combinada (ejes $/%/R × fecha/trades), drawdown, calendario
  de PnL, métricas, correlación por pares, VaR/CVaR y Monte Carlo por día.
- *Modelos (Escalado y Pesos)*: el motor de asignación de riesgo (§3).
- *Comparativa*: los 5 modelos frente a frente sobre los mismos datos, con
  análisis fino del que elijas (VaR/CVaR, Monte Carlo, calendario).

**Monitorización** — fichas por estrategia con sus últimos 6 meses
**re-ejecutados bajo demanda** con sus parámetros guardados, y el drawdown
actual frente al máximo teórico. Debajo, *Control en tiempo real*: se importa
el CSV de transacciones del bróker, se calcula la curva real y su drawdown, se
le aplica el modelo de escalado elegido, se reparten los pesos de hoy entre las
estrategias normalizadas, y se superpone la equity real contra el portfolio
simulado del mismo tramo para cazar divergencias.

---

## 2. Cómo encenderlo

Está gated en los dos lados, con el mismo patrón que Robustez. **Por defecto
está apagado**: si no se tocan las variables, esta rama se comporta exactamente
igual que antes de este commit.

```bash
# backend/.env
PORTFOLIO_LAB_ENABLED=true

# frontend/.env.local
NEXT_PUBLIC_PORTFOLIO_ENABLED=true
```

Sin la variable del backend, todos los endpoints responden 503. Sin la del
frontend, la entrada del menú no aparece.

### Tablas

El módulo crea **tres tablas propias** en `users.duckdb`, de forma perezosa y
solo cuando está activo. No se toca `init_db.py` ni el esquema compartido: en
producción estas tablas simplemente no existen.

| Tabla | Para qué |
|---|---|
| `portfolio_lab_assignments` | qué estrategia está en qué cuadro (portfolio/incubadora) |
| `portfolio_lab_monitor` | instantáneas de los últimos 6 meses por estrategia |
| `portfolio_lab_real_pnl` | PnL diario real importado del bróker |

El DDL corre **una vez por proceso y bajo su propio cerrojo**: DuckDB lanza
`Catalog write-write conflict` si dos hilos entran a la vez al mismo
`CREATE TABLE`, incluso con `IF NOT EXISTS`. Está resuelto en
`portfolio_lab_service._ensure_once()`.

---

## 3. Los modelos de asignación de riesgo

Dos ejes independientes que se recalculan en cada rebalanceo (D/W/M), **siempre
con datos estrictamente anteriores a la fecha del rebalanceo** (cero mirada al
futuro):

**Escalado global** — cuánto se arriesga por trade según el estado de la cuenta:
`fixed` ($ fijo), `percent` (% del capital vivo), `fixed_ratio` (Ryan Jones,
escalones por delta de beneficio), `kelly` (f* = media/varianza de la R diaria
del portfolio ponderado en la ventana, por una fracción configurable) y
`combinatoria` (fix ratio bajo un umbral de equity, Kelly por encima).

**Ponderación** — cómo se reparte ese riesgo entre las estrategias vivas:
`equal`, `hrp` (Hierarchical Risk Parity de López de Prado, **usa scipy**),
`momentum`, `ev` (expectancy por trade de la ventana) y `dd` (multiplicador
`1 − DD_actual/DD_máx` con suelo).

**Semántica:** riesgo de la estrategia *i* = `X · n_vivas · w_i`, de modo que
con pesos iguales el resultado coincide EXACTAMENTE con la imagen general.
Los topes (`cap_global_pct`, `cap_strat_pct`) **recortan sin redistribuir**: el
exceso se queda sin desplegar.

**Aviso sobre Kelly:** la f* estimada sobre backtest sobreapuesta de forma
sistemática — en las pruebas pedía el 65-131% del capital por unidad de R y
fundía la cuenta incluso a ½ Kelly. Hay un **techo interno duro del 25%**
(`KELLY_CEILING`), y el panel avisa siempre de cuánto pedía en crudo y qué lo
recortó. No quitar ese techo sin entender por qué está.

---

## 4. Ficheros

**Backend, nuevos** (ninguno toca código existente):
```
backend/app/routers/portfolio_lab.py          endpoints, gating, validación
backend/app/services/portfolio_lab_service.py normalización + tablas
backend/app/services/portfolio_lab_engine.py  motor lineal + métricas
backend/app/services/portfolio_lab_scaling.py modelos de escalado y pesos
```

**Frontend, nuevos:**
```
frontend/src/app/portfolio/page.tsx
frontend/src/components/portfolio/**          (12 ficheros)
frontend/src/lib/api_portfolio_lab.ts
```

**Modificados (mínimo imprescindible):**
```
backend/app/main.py                           +4 líneas: import y include_router
frontend/src/components/Sidebar.tsx           +15 líneas: entrada gated
frontend/src/components/robustez/StrategyPicker.tsx        4 funciones pasan a export
frontend/src/components/robustez/charts/MonteCarloCharts.tsx  SpaghettiChart acepta xLabel
```

Los dos cambios en Robustez son **puramente aditivos**: exportar funciones que
ya existían y añadir un prop opcional con valor por defecto. No cambian el
comportamiento de Robustez.

### Dependencias

El módulo **reutiliza** (no duplica) piezas que ya están en esta rama:
`robustness_service` (listado de corridas, `attach_precise_r`),
`robustness_mc.run_bootstrap`, `optimization_service` (progreso de trabajos),
`backtest_orchestrator` (solo la Monitorización), y en el frontend los
componentes compartidos de `components/robustez/`. Verificado: **todas existen
en staging** y el módulo compila con `tsc --noEmit` sin errores contra este
código.

Requiere `scipy` (para HRP). Ya está declarado en los requisitos del backend.

---

## 5. Lo que NO se ha traído a propósito

Estas cosas existen en `sailor-rama-desarrollo` pero **se han dejado fuera
deliberadamente** para no romper nada aquí:

1. **El borrado de la página Baúl (`/database`).** En la rama de Jaume,
   Portfolio la reemplaza y se eliminó. **Aquí el Baúl sigue intacto**, y la
   entrada de Portfolio se ha añadido *además* de la suya. Decidid vosotros si
   queréis mantener las dos o no.

2. **El cambio de comisiones PERCENT.** En la rama de Jaume se corrigió el
   cálculo de `abs(gross_pnl) * fees` a `% del NOCIONAL por lado`
   (`(entry + exit) * size * fees`), porque el modelo antiguo hacía que un
   trade en tablas pagara ~$0 de comisión moviera las acciones que moviera.
   **Aquí NO se toca** `portfolio_sim.py` ni `portfolio_sim_jit.py` porque
   staging ya tiene su propio modelo por fill (commit `77236d2`). Ver §6.

---

## 6. Puntos a acordar entre las dos ramas

**a) Semántica de las comisiones FLAT.** Staging redefinió FLAT como
`fees × acciones` ($/acción). La rama de Jaume mantiene `fees × 2` ($/trade).
En PERCENT los dos modelos coinciden en el total; **en FLAT no**. Esto dará
números distintos y conflicto al mergear las ramas. Hay que decidir cuál es la
convención buena y unificar.

**b) El fallback silencioso de `data_service.py`.** El informe
`INFORME_FIX_NODETERMINISMO_BACKTEST_2026-08-21.md` de esta rama lo documenta:
el `except` que cae al hot-cache prefiltrado por `gap_pct>=10`. En la rama de
Jaume **no se dispara** porque `daily_metrics` es una tabla persistente, pero
el código está igual de presente. Cuando la migración GCS→parquet llegue a esa
rama, **el fail-fast (`1ec8ce9`) tiene que viajar con ella** o heredará el
70R↔137R.

**c) Sortino.** El módulo Portfolio calcula la downside deviation canónica
(`sqrt(mean(min(ret,0)²))` sobre todas las observaciones).
`backtest_service.py:1240-1242` usa la std de solo los días perdedores
alrededor de su propia media, que da 0 — es decir, "no medible" — para curvas
con pérdidas muy uniformes. **No se ha tocado** por ser motor compartido, pero
conviene decidir si se unifica.

**d) Anualización del Sharpe.** Mismo caso: el módulo anualiza con la
frecuencia efectiva de la serie en vez de con 252 fijo, porque el calendario
solo contiene días con operaciones y anualizar con 252 infla el Sharpe
~1/√(fracción activa). El motor compartido no se ha tocado.

---

## 7. Cómo se ha verificado

- **Paridad exacta a 6 decimales** entre el motor de escalado y la imagen
  general en los dos casos ancla: `fixed $100` → 304,420878% en ambos;
  `percent 3%` con rebalanceo diario → 699.805,793146% en ambos.
- **Validación cruzada de la normalización**: combinar las corridas originales
  (con costes, reconstruidas por la tubería de normalización) da 305,14%;
  combinar copias re-corridas de verdad sin costes da 304,42%. El desvío del
  0,24% es exactamente el margen esperado de la reconstrucción aproximada del
  slippage.
- **Revisión adversaria multi-agente** (4 lentes de revisión + un escéptico por
  hallazgo intentando refutarlo): 7 hallazgos confirmados y corregidos, 3
  refutados. Entre los corregidos: el DDL sin cerrojo, el import de PnL no
  atómico, los trades fantasma con riesgo 0, el Sortino no canónico y la
  anualización.
- `tsc --noEmit` sin errores **contra el código de staging**, no solo contra el
  de origen.

---

## 8. Notas prácticas

- **Estrategias normalizadas.** El módulo funciona mejor con corridas guardadas
  sin costes y con riesgo FIJO (el importe da igual, se renormaliza a R=1). Las
  que no lo estén entran igualmente — el motor las normaliza al vuelo y las
  marca en ámbar — pero el slippage solo se puede reconstruir de forma
  aproximada, así que el resultado es ligeramente menos exacto.
- **Ventanas mínimas.** HRP, momentum, EV, drawdown y Kelly necesitan ~20
  sesiones de mercado dentro de la ventana. Con menos, caen a un
  comportamiento seguro (pesos iguales / % base) **y lo avisan en pantalla**.
  Si aparecen pesos 50/50 sospechosos, es esto.
- **La Monitorización es trabajo pesado**: re-ejecuta un backtest de 6 meses por
  estrategia, secuencialmente, ~20-40 s cada una. Hay un guardián de un solo
  trabajo a la vez (409 si ya hay uno). El resultado queda guardado entre
  sesiones: solo se recalcula al pulsar el botón.
- **Importación del bróker**: el parser detecta el CSV de transacciones tipo DAS
  (cabecera `Trade Date` / `Net Amt`), filtra las filas `TRD` y agrega el PnL
  por día como `−Σ Net Amt` (convenio del bróker: compras positivas, ventas
  negativas). Respeta campos entrecomillados y separadores de miles. También
  acepta líneas simples `fecha, pnl`.
