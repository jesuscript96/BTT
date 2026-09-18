# PRD — Picos y valles enumerados (patrones de estructura: hombro-cabeza-hombro y familia)

- **Fecha:** 2026-09-18
- **Autor:** Álvaro (necesidad y decisión) + Claude Opus 5 (análisis del motor,
  medición y redacción)
- **Aplica sobre:** `alvaro-rama-desarrollo` a la altura de `5f2aba8` (con el
  fix del SL por lote `fa1bc89` ya integrado y verificado)
- **Tipo:** funcionalidad nueva (3 indicadores). No arregla ningún bug.
- **Severidad:** ninguna — hoy no hay nada roto, hay algo que **no se puede
  expresar**.
- **No toca el bot de avisos** ni `market_frame.py` ni la página de Alertas.
  Añade nombres nuevos a `indicators.py`; no cambia el comportamiento de ningún
  indicador existente.
- **Reglas del repo vigentes:** trabajo en la rama de quien lo aplique,
  integración a `staging` por merge, `main` intocable, confirmación explícita
  antes de cualquier `push`.

---

## 1. Resumen en una frase

El motor sabe encontrar los giros del precio, pero **solo deja leer el último**;
se pide que lleve una lista de los últimos N giros (precio, hora y volumen de
cada uno) para poder comparar unos con otros, que es lo que define un
hombro-cabeza-hombro, un doble techo o una divergencia de estructura.

---

## 2. Qué existe hoy (verificado, no supuesto)

### 2.1 El ladrillo ya está y funciona

`Ultimo pivote` — `indicators.py:1835`, kernel `_ultimo_pivote(h, l, day_id, win, alto)`:

- Parámetros de estrategia: `pivot_window` (velas de confirmación a cada lado) y
  `swing_dir` (`"up"` = techo, `"down"` = suelo).
- Devuelve el **precio** del último giro confirmado, como serie escalonada.
- Es **causal**: el pivote centrado en `i - win` se confirma en la barra `i`.
  Mira hacia atrás, nunca hacia delante.
- Comparación **estricta** (`>` / `<`): un doble techo exacto no cuenta como
  pivote nuevo. Es deliberado y está documentado en el propio código.
- Vale `NaN` hasta el primer pivote del día y **se reinicia cada día**.

### 2.2 La maquinaria de enumerar también está — pero encerrada

`_detect_triangles_numba` — `indicators.py:469` — ya recorre una ventana
`tri_lookback`, marca **todos** los swing highs y lows, exige `min_pivots` de
cada tipo y les ajusta una recta por mínimos cuadrados con R². Es decir: el
motor **ya sabe listar pivotes**. Lo único que expone hacia fuera es un booleano
("hay triángulo") para tres geometrías fijas.

### 2.3 Lo que NO se puede hacer, y por qué

El lenguaje de condiciones compara **serie en la barra `t` contra serie en la
barra `t`**. Un pivote no vive en el tiempo, vive en un **índice de eventos**.
`Ultimo pivote` colapsa la secuencia entera a su último elemento.

El `offset` **no sirve** de sustituto: es `series.shift(N)` en **velas**
(`indicators.py:1226`), no en pivotes. `Ultimo pivote` con `offset=30` no es "el
pivote anterior", es "qué valía el último pivote hace 30 velas". Coincide con el
pivote anterior solo por casualidad. **Prohibido usarlo para esto.**

Consecuencia práctica: *"el último techo está muy por debajo del techo
anterior"* — el corazón de un hombro-cabeza-hombro — **no es expresable hoy de
ninguna manera.**

---

## 3. Qué NO es esto (leer antes de tocar nada)

Tres confusiones probables, las tres verificadas:

- **NO son los `Pivot Points` clásicos.** En este motor ya existen
  `Pivot Points` / `PP` / `R1` / `S1` / `R2` / `S2` (`strategy_engine.py:279`,
  fórmula en `indicators.py:998`): niveles fijos sacados del máximo, mínimo y
  cierre de **ayer**, constantes durante todo el día. **No tienen nada que ver**
  con lo que se pide aquí. Por eso este PRD los llama **picos y valles**, no
  "pivotes", en el nombre de cara al usuario.
- **NO es el Zig Zag.** `Zig Zag` está en el enum (`schemas/strategy.py`) y en el
  catálogo que se sirve por API (`api_public/modules/backtest/catalog.py`),
  **pero no tiene implementación**: cae al `return pd.Series(np.nan)` del final
  de `_compute_raw` (`indicators.py:3122`). Por UI no es alcanzable (el builder
  no lo ofrece); por JSON/API sí, y daría 0 trades en silencio. Está **fuera del
  alcance** de este PRD — se reporta aparte como hallazgo.
- **NO se pide tocar `_ultimo_pivote` ni los triángulos.** Los dos siguen
  existiendo con su comportamiento actual. Lo nuevo se construye **al lado**,
  reutilizando el mismo criterio de detección.

---

## 4. Qué se pide

Tres indicadores nuevos que comparten **un único kernel**: una pasada que
detecta los giros exactamente igual que hoy y va guardando los últimos `M`
confirmados en un búfer circular por día.

| Indicador | Devuelve |
|---|---|
| **`Pico`** (con `swing_dir` se convierte en valle) | el **precio** del giro nº N contando hacia atrás |
| **`Edad del pico`** | **minutos de reloj** transcurridos desde que se formó ese giro |
| **`Volumen del pico`** | el **volumen** de la vela de ese giro |

### 4.1 Parámetros

| Campo | Valores | Defecto | Significado |
|---|---|---|---|
| `swing_dir` | `"up"` \| `"down"` | `"up"` | techo (pico) o suelo (valle) |
| `pivot_window` | entero ≥ 1 | `3` | velas de confirmación a cada lado |
| `pivot_rank` | entero ≥ 1 | `1` | **nuevo**: 1 = el último confirmado, 2 = el anterior, 3 = el de antes… |

`pivot_rank = 1` debe dar **exactamente lo mismo** que `Ultimo pivote` con los
mismos `swing_dir` y `pivot_window`. Eso es un test, no una aspiración (§8).

### 4.2 Contrato de comportamiento (obligatorio, hereda de `_ultimo_pivote`)

1. **Causalidad.** El giro centrado en `i - pivot_window` se confirma en la
   barra `i` y **no antes**. Ningún indicador de esta familia puede consultar
   datos posteriores a la barra que evalúa. Es la razón de ser del retardo y no
   se negocia.
2. **Comparación estricta** (`>` / `<`), igual que hoy: en un tramo plano no
   puede ser cada vela su propio pivote.
3. **Reinicio diario.** La lista se vacía al cambiar de día (`day_id`). El
   patrón tiene que caber dentro de una sesión. **Decisión de Álvaro,
   2026-09-18: es lo que se quiere.** No se pide modo multi-día.
4. **`NaN` cuando no hay dato.** Si todavía no se han confirmado `pivot_rank`
   giros ese día, el indicador vale `NaN` y la condición **no dispara**. Nunca un
   `0`, nunca el último disponible, nunca el de ayer.
5. **Profundidad.** `M` (tamaño del búfer) ≥ 8. `pivot_rank > M` → `NaN`, no
   error.
6. **La edad va en minutos de reloj**, no en número de velas. Las velas del lago
   son dispersas (premarket ilíquido) y "20 velas atrás" es una ventana distinta
   en cada ticker. Mismo criterio que ya siguen `Squeeze`, `Reg. Slope` y
   `Retroceso (%)`.

---

## 5. ⚠️ Los cuatro sitios donde un parámetro nuevo se pierde EN SILENCIO

Esta sección es el motivo principal de que este PRD exista. El repo ya ha
tropezado con esta clase de fallo varias veces (los comentarios de
`_compute_from_config` y del propio enum lo dicen literalmente: *"mismo fallo que
ya tuvieron otros indicadores"*). `pivot_rank` tiene que declararse en **los
cuatro**, o el indicador calculará con el defecto sin error, sin log y sin 422:

1. **`IndicatorConfig`** en `schemas/strategy.py:311` — pydantic va con
   `extra="ignore"`: un campo sin declarar se tira sin avisar.
2. **La clave de caché de `compute_indicator`** (`indicators.py:1184`) — si
   `pivot_rank` no entra en la clave, `rank=1` y `rank=2` **comparten
   resultado**. Este es el fallo más peligroso del lote: la estrategia leería
   tres veces el mismo pivote y el hombro-cabeza-hombro saldría siempre
   verdadero.
3. **`_compute_from_config`** en `strategy_engine.py:1920` — si no se reenvía, el
   parámetro no llega al indicador.
4. **`catalog.py`**, diccionario `_PARAMS` — para que la API y los agentes lo
   descubran.

---

## 6. El hombro-cabeza-hombro, escrito entero

Con lo anterior, el patrón sale con los comparadores **que ya existen**, sin
inventar nada. En el momento de la rotura, los picos confirmados hacia atrás son:
`rank 1` = hombro derecho, `rank 2` = cabeza, `rank 3` = hombro izquierdo.

```
1. Pico(rank=1) < Pico(rank=2) x 0,97        hombro derecho MUY por debajo de la cabeza
2. Pico(rank=2) > Pico(rank=3) x 1,02        la cabeza asoma sobre el hombro izquierdo
3. |Pico(1) - Pico(3)| < 1,5 %               los dos hombros a la misma altura
4. |Valle(1) - Valle(2)| < 1 %               la clavicula, plana
5. Edad del pico(rank=3) < 90 min            las tres cimas caben en hora y media
6. Bar Close CRUZA POR DEBAJO Valle(rank=1)  <- LA ENTRADA
```

En JSON del motor:

```json
{
  "operator": "AND",
  "conditions": [
    {"type": "indicator_comparison",
     "source": {"name": "Pico", "swing_dir": "up", "pivot_window": 5, "pivot_rank": 1},
     "comparator": "LESS_THAN",
     "target": {"name": "Pico", "swing_dir": "up", "pivot_window": 5, "pivot_rank": 2,
                "multiplier": 0.97}},

    {"type": "indicator_comparison",
     "source": {"name": "Pico", "swing_dir": "up", "pivot_window": 5, "pivot_rank": 2},
     "comparator": "GREATER_THAN",
     "target": {"name": "Pico", "swing_dir": "up", "pivot_window": 5, "pivot_rank": 3,
                "multiplier": 1.02}},

    {"type": "price_level_distance",
     "source": {"name": "Pico", "swing_dir": "up", "pivot_window": 5, "pivot_rank": 1},
     "level":  {"name": "Pico", "swing_dir": "up", "pivot_window": 5, "pivot_rank": 3},
     "comparator": "DISTANCE_LT", "value_pct": 1.5, "position": "any"},

    {"type": "price_level_distance",
     "source": {"name": "Pico", "swing_dir": "down", "pivot_window": 5, "pivot_rank": 1},
     "level":  {"name": "Pico", "swing_dir": "down", "pivot_window": 5, "pivot_rank": 2},
     "comparator": "DISTANCE_LT", "value_pct": 1.0, "position": "any"},

    {"type": "indicator_comparison",
     "source": {"name": "Edad del pico", "swing_dir": "up", "pivot_window": 5,
                "pivot_rank": 3},
     "comparator": "LESS_THAN", "target": 90},

    {"type": "indicator_comparison",
     "source": {"name": "Bar Close"},
     "comparator": "CROSSES_BELOW",
     "target": {"name": "Pico", "swing_dir": "down", "pivot_window": 5, "pivot_rank": 1}}
  ]
}
```

Notas de diseño sobre esto:

- **"Mucho menor" se normaliza en %, no en ATR.** El motor sabe multiplicar un
  indicador por una constante (`multiplier`), pero **no sabe sumar ni restar dos
  indicadores entre sí**. `Pico(1) < Pico(2) - 1,5 x ATR` no es expresable. Si
  algún día se quiere, es otro PRD.
- **La simetría temporal fina tampoco es expresable** por la misma razón
  (`|edad(3) - edad(2)| ~ |edad(2) - edad(1)|` necesita resta). La condición 5 es
  el sustituto realista: acota el patrón entero a una ventana de tiempo, que es
  el grueso del filtro.
- **`pivot_window` es el parámetro a barrer con el genético.** Pequeño (2-3): te
  enteras rápido pero cualquier temblor cuenta como hombro. Grande (8-10): solo
  giros de verdad, pero llegas tarde. Su coste en tiempo es **cero** (§7), así
  que se puede barrer libremente.
- **El campo `timeframe` de cada condición ya existe** (`1m`/`5m`/`15m`/`30m`/`1h`).
  La misma definición evaluada a otra escala sale gratis — que es exactamente la
  idea fractal de la que salió esta petición. **Excepción: `1d` no funciona** con
  esta familia, porque con el reinicio diario cada barra sería un día nuevo y el
  indicador daría `NaN` siempre. Documentarlo; si molesta, rechazar `1d` con un
  error explícito en vez de devolver `NaN` mudo.

---

## 7. Rendimiento — medido, no estimado

Medición del 2026-09-18 sobre datos sintéticos (un día de 960 velas de 1m), solo
generación de señales, sin carga de datos. Script efímero en scratchpad, no
versionado. Una sola máquina.

Coste por ticker-día de una estrategia completa:

| | ms / ticker-día |
|---|---|
| Sin pivotes, carril nativo | 0,04 |
| **La misma**, carril legacy | 0,43 |
| Con pivotes, carril legacy | **2,43** |

Coste de cada indicador por separado, mismo día:

```
  EMA(20)              0,022 ms
  RSI(14)              0,023 ms
  Previous max         0,527 ms   <- un indicador corriente, ya en uso
  Ultimo pivote w=3    0,372 ms
  Ultimo pivote w=5    0,382 ms
  Ultimo pivote w=10   0,354 ms
  Triangle Symmetric   0,186 ms
```

Dos conclusiones:

1. **El indicador de pivotes cuesta menos que `Previous max`.** El "58x más
   lento" del carril legacy es 58x casi nada: 12 s de más en un backtest de 5.000
   ticker-días, cuando ~95 % del tiempo de un backtest real se va en cargar datos
   (`stream_build`, ver `PRD_PERF_BACKTEST_STREAMBUILD_20260827.md`).
2. **El tamaño de la ventana no cuesta nada** (3, 5 y 10 valen igual). El
   genético puede barrer `pivot_window` sin penalización.

### 7.1 Dos fases, en este orden. No a la vez.

**Fase 1 — lento y correcto. Es todo el alcance obligatorio de este PRD.**
El indicador NO se registra en `_RAW_INDICATOR_DISPATCH`. Cualquier estrategia
que lo use cae al carril legacy por el gate `has_special`
(`strategy_engine.py:944`), que es donde el parámetro sí viaja completo. Para
backtests normales el coste es irrelevante.

**Fase 2 — rápido. Solo si el genético lo pide, y solo después de que la Fase 1
esté verificada.** Ahí el 2,43 ms contra 0,04 ms sí importa: multiplicado por
miles de individuos es la diferencia entre minutos y horas.

> **⚠️ La Fase 2 tiene una trampa que hay que arreglar ANTES de tocar nada.**
>
> La clave de deduplicación del carril rápido es
> `f"{name}|{tf}|{period}|{period2}|{period3}|{std_dev}"` —
> `strategy_engine.py:879` y `strategy_engine.py:1706`. **No incluye
> `swing_dir`, ni `pivot_window`, ni `pivot_rank`, ni `offset`, ni
> `multiplier`.** Si alguien registra estos indicadores en el dispatch nativo sin
> ampliar esa clave, `Pico(rank=1)`, `Pico(rank=2)` y `Valle(rank=1)` llevarían
> **la misma etiqueta**, el motor los tomaría por el mismo cálculo y les daría
> **el mismo array**. La estrategia leería suelos donde pide techos y el
> hombro-cabeza-hombro daría siempre verdadero. Sin error, sin log, sin aviso.
>
> Hoy no ocurre porque nada de esto está en el carril rápido. Ocurriría el día
> que se optimice. **Orden obligatorio: primero ampliar la clave, después
> registrar.**

---

## 8. Tests exigibles

Todos con datos sintéticos, sin DuckDB ni GCS, al estilo de
`test_n2a_native_equivalence.py`:

1. **Paridad con lo que ya hay:** `Pico(rank=1)` ≡ `Ultimo pivote`, mismos
   `swing_dir` y `pivot_window`, tolerancia 0.
2. **Orden correcto:** serie fabricada con giros conocidos en precios
   distinguibles (p. ej. 10 → 12 → 11 → 15 → 13 → 14); comprobar que `rank` 1, 2
   y 3 devuelven los tres techos esperados **y en el orden correcto**.
3. **Sin lookahead:** para cada barra `t`, el valor calculado sobre `df[:t+1]`
   debe ser idéntico al calculado sobre el día entero. Innegociable, y para los
   tres indicadores de la familia.
4. **`NaN` honesto:** con menos de `pivot_rank` giros confirmados el valor es
   `NaN` y la condición no dispara. Comprobar explícitamente el arranque del día.
5. **Reinicio diario:** frame de dos días; el primer giro del día 2 no puede
   heredar nada del día 1.
6. **Empates:** tramo plano → ningún pivote nuevo (comparación estricta).
7. **`pivot_rank` viaja entero:** una estrategia con `rank=1` y otra con `rank=2`
   deben dar señales distintas. Es el test que caza el fallo de la clave de caché
   del §5.2.
8. **Coste:** que el tiempo del indicador no dependa de `pivot_window`
   (confirmación de la medición del §7).

---

## 9. Riesgos y qué NO se toca

- **No se toca el bot de avisos ni `market_frame.py`.** `indicators.py` es
  compartido con `bot_alerts_engine.py`, pero añadir **nombres nuevos** no altera
  el resultado de ningún indicador existente. Si la implementación acabara
  modificando `_ultimo_pivote`, `_detect_triangles_numba` o cualquier kernel ya
  en uso, **parar y avisar a Jaume** antes de seguir: eso sí movería las señales
  en vivo.
- **No se toca el schema de datos** ni el Parquet del lago.
- **Numba:** el kernel nuevo va compilado (`@njit(cache=True)`) como el resto.
  Recordar el aviso de `indicators.py:511`: un índice negativo dentro de un
  `njit` sin `boundscheck` **no da IndexError, mata el proceso entero sin
  traceback**. Acotar el índice del búfer circular explícitamente; es el mismo
  fallo que tumbó las corridas del genético durante dos noches en septiembre.

---

## 10. Decisiones ya tomadas por Álvaro (2026-09-18)

- **El patrón es intradía, dentro del mismo día.** El reinicio diario está bien.
- **`1d` no hace falta.** Que quede documentado que no funciona.
- **El retardo de confirmación se acepta tal cual.** Prefiere llegar tarde a
  incurrir en lookahead. No se admite ninguna variante "sin confirmar".
- **Antes rendimiento honesto que rendimiento rápido.** Fase 1 obligatoria,
  Fase 2 opcional y posterior.
