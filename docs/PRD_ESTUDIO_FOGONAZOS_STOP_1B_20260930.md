# PRD — Estudio «Fogonazos vs stop de la 1B»: ¿nos protege el StopLimitP donde lo ponemos?

> **Para:** GLM (ZCode), conversación nueva, con la API de Databento conectada.
> **Pide:** Álvaro (2026-09-30). La pregunta es de Álvaro y Jaume.
> **Tu rol:** PRUEBAS Y ANÁLISIS → aplica el **§ Protocolo de hallazgos — REPORTAR,
> NO ARREGLAR** de `AGENTS.md`. **Cero cambios de código del repo.**
> **Rama:** `alvaro-rama-desarrollo`. Jamás `main`. Sin commit ni push sin OK explícito.
> **Forma de trabajo:** por fases, con checkpoints (CP). En cada CP **paras**,
> enseñas números concretos y **esperas el OK de Álvaro**.

---

## 1. La pregunta de negocio

Operamos la **1B** en corto en premercado. Nos da miedo el **fogonazo** (lo que
llamamos «black swan»): el precio sube **+100 % en menos de 1 minuto** con la
posición abierta. Queremos saber si **nuestro protocolo de stop nos saca de
verdad** en esos eventos y si **cambiar dónde ponemos el stop** nos protege más
o da prácticamente igual.

**Cómo ponemos hoy el stop en DAS Trader:** una orden **StopLimitP** con:
- **Trigger** `T` = Previous Max **+10 %** (el stop estructural de la 1B).
- **Precio límite (execution price)** `L` = **1,5 × T** (un 50 % por encima del
  trigger, para darle margen al precio para ejecutarse y sacarnos).

**Lo que creemos que hace DAS (y hay que comprobar con datos):** al tocarse `T`,
DAS envía en el acto una orden límite de compra a `L`, que se ejecuta al **mejor
precio disponible**, no a `L`. Ejemplo: `T` = 10 $, `L` = 15 $ → se ejecuta en
~10,05 $.

**La pregunta concreta:** en los fogonazos de +100 % en < 1 min que nos pillaron
dentro (o nos habrían pillado), **¿en qué % de casos nos habríamos salido, a qué
precio y con cuánta pérdida**, si el trigger hubiera estado en:

| Variante | Trigger `T` | Límite `L` |
|---|---|---|
| **V0 (lo de hoy, referencia)** | PM × 1,10 | 1,5 × T |
| V1 | PM (el Previous Max exacto) | 1,5 × T |
| V2 | PM × 0,99 (PM −1 %) | 1,5 × T |
| V3 | PM × 0,95 (PM −5 %) | 1,5 × T |

¿Estamos más protegidos con alguno o todos se comportan parecido?

**Y el otro lado, sin el cual no hay decisión:** un stop más cerca salta más en
días normales. La respuesta final tiene que ser un **balance por año**: lo que
un stop más cercano ahorra en fogonazos frente a lo que cuesta en el resto de
operaciones.

---

## 2. Lo que YA sabemos — léelo antes de nada y NO lo redescubras

1. **`AGENTS.md` entero** (reglas duras, zona cerrada, protocolo de hallazgos).
2. **Informe v4 de Jaume «Cisnes negros en premercado»**: texto extraído en
   `.tmp_rehalt/bswans_halts_texto.txt` (PDF en
   `C:\Users\Alvaro\Downloads\Telegram Desktop\BSwans y Halts.pdf`). Lo esencial:
   - **Prints tardíos:** de 5.360 fogonazos aparentes en la cinta, solo 294
     existieron en el libro; **el 93 % eran prints publicados con retraso**
     (dark pools). Filtro: publicados < 10 ms después de ejecutarse. **Un stop
     que dispare por «último precio» puede saltar por un fogonazo que no existió.**
   - **§6: el precio CAMINA, no salta.** Stops limitados escalonados con banda
     del 10 %: en +20 % el precio caminó por la banda en 257 de 274 fogonazos;
     en +100 %, en 51 de los 56 que llegaron. ENSC (+4.800 % en 39 s) operó
     27.000 acciones dentro de la banda +20 %. **Trampa:** un limitado disparado
     y no ejecutado se queda colgado y se ejecuta «a la vuelta», a un precio que
     ya no tiene sentido.
   - **§7: cruce con la 1B** (backtest de 3.024 trades, ene-2025→ago-2026):
     solo **7 fogonazos cayeron dentro de una posición** (≥ +50 %); ~4-5 de
     ellos ≥ +100 % (PLYX, SLGB, GLE, AEHL, LGHL ≈ +99 %). Todos salieron por
     SL con −22 % a −65 %. OJO: esos resultados son del MOTOR, que asume
     ejecución al precio del stop; lo real está por medir (esto es este estudio).
   - **§8: informe del socio:** fills reales de stop-limit en 454 stops del
     diario: **mediana ×1,007 del trigger, p95 ×1,07**. Propone límite ancho
     ×1,4-2,0.
3. **`docs/MEMORIA_BOT_EJECUCION.md`**, entradas del 7-sep y 11-sep, sobre todo
   **«7-sep (noche, 3): el stop de 1B — nivel, mercado vs limitado, tamaño
   (informe v5)»**. Jaume YA comparó **−1 % bajo el PM vs +10 % vs +30/40 %**
   sobre 2.715 trades de la 1B con ticks: **+10 % gana en conjunto** (4,3 %
   medio/op, 63 % ganadoras, salta el 30 %); **−1 % salta el 50 %**, 3,6 %
   medio, 47 % ganadoras. Modelo de ejecución que usó: consumir el 50 % de cada
   print de la cinta.
4. **`docs/BOT_EJECUCION_PREGUNTAS.md`**, preguntas **19 y 22**: lo que NO sabemos
   de DAS (qué print dispara el StopLimitP, si el feed es consolidado, si un
   print tardío lo dispara). Sigue pendiente del bróker.
5. **`docs/datos/halts_databento/LEEME.md`** (halts de Nasdaq, trampas conocidas).

**Qué aporta este estudio que no está hecho:**
(a) condicionado a **fogonazos de +100 % en ≤ 60 s** con la posición abierta,
no al agregado de todos los trades; (b) los niveles **PM, PM −1 % y PM −5 %**
frente al +10 %; (c) la **mecánica concreta del StopLimitP** (límite ×1,5,
disparo por último precio, latencia, ejecución parcial, colgados); (d) el
**balance seguro-vs-coste** con el motor real sobre el CSV actual (2024-2026).

Los scripts y ficheros de Jaume están en `D:\bot_senales\estudio_cisnes`, en SU
máquina y dentro de la **zona cerrada**: **no intentes acceder**. Si te ahorran
trabajo su lista de fogonazos, `cruce_1b_flash.csv` o `stops_1b_sim.parquet`,
pídeselos a Álvaro para que se los pida a Jaume.

**HIPÓTESIS a confirmar o tumbar (no la des por buena):** si el precio camina,
en un fogonazo cualquier nivel se ejecuta cerca de su `T`, así que un stop más
bajo pierde menos en el fogonazo pero salta mucho más en días normales. Si es
así, la pregunta real es el balance, no la protección.

---

## 3. Definiciones exactas (no las reinterpretes; si algo no cuadra, para y pregunta)

- **Horas:** siempre **ET (America/New_York)**. Databento da UTC en ns →
  convierte con zona por nombre (horario de verano incluido).
- **La 1B** (estrategia «Estrategia 1B - Modelización Sobri 3»): corto;
  sesión custom de premercado; **entradas 04:02-08:00 ET**, salida EOD ≤ 08:45;
  parciales por hora; 1 añadido de pirámide (mismo stop); reentradas máx 2.
  **Toda la exposición es premercado → no hay LULD**, pero sí puede haber halts
  T1. Confirma la configuración exacta leyendo la estrategia en el baúl
  (`5ed17d89` o sus copias C1/C2/C4/C5, ver
  `docs/INFORME_ESTUDIO_1B_SOBRI3_20260924.md` §6).
- **Stop actual:** `hard_stop = {type: "Market Structure (HOD/LOD)", value:
  "Previous Max", offset_pct: 10}`, **anclado a la entrada**.
- **PM (Previous Max):** máximo corrido del día **hasta la vela ANTERIOR a la
  señal** (`backend/app/services/market_frame.py` ~l.100;
  `portfolio_sim.py::_structural_level`). En el CSV: **PM = `Stop loss ($)` /
  1,10**. Verifícalo contra las velas M1 del lago en una muestra de 50 trades.
  (`market_frame.py` lo comparte el bot: **solo lectura**.)
- **Variante inválida:** si `T` ≤ precio de entrada (el stop cae en el lado
  ganador), esa variante no existe para ese trade (el motor tampoco entraría:
  `_sl_side_valid`). Cuéntalo aparte, no lo mezcles.
- **Prints limpios:** mismo criterio que el lago (el premercado de
  `intraday_1m` ya viene limpio): **< 10 ms entre ejecución y publicación**.
  Documenta qué campos de Databento usas para eso.
- **Fogonazo:** existen `t0 < t1` con `t1 − t0 ≤ 60 s` y `P(t1)/P(t0) ≥ 2,0`
  sobre prints **limpios**, **con la posición abierta** (`t0` ≥ entrada y ≤
  salida).
  - **«Que no sea el fogonazo que crea el gap»:** solo cuentan los que empiezan
    **después de la entrada**, con el PM ya fijado. Los anteriores a la entrada
    son los que forman el PM → fuera (Jaume contó 97 así).
  - **Etiqueta «puro»** si devuelve ≥ 70 % del salto en los 60 s siguientes al
    máximo (definición de Jaume); si no, **«subida real rápida»**. Se reportan
    por separado.
  - **Fantasma:** salto que solo existe contando prints tardíos o prints
    sueltos (≤ 10 operaciones). No es un fogonazo real, **pero puede disparar un
    StopLimitP que mire el último precio**: se analiza aparte (§5, Fase 3).
  - **Sensibilidad:** repetir el recuento con +50 % en ≤ 60 s (umbral de Jaume).

---

## 4. Modelo de la orden StopLimitP (lo que hay que simular)

No sabemos al 100 % cómo dispara DAS → **se parametriza, no se asume**:

- **Disparo (3 variantes):**
  - **D1 — último print, cualquiera** (incluidos tardíos). Es lo que creemos
    que hace DAS («LimitP dispara por último precio»), pendiente del bróker.
  - **D2 — último print limpio.**
  - **D3 — ask (NBBO) ≥ T.**
- **Latencia DAS → bolsa:** 0 / 250 ms / 1 s (el stop vive en el servidor de
  DAS, no es una orden nativa de la bolsa).
- **Ejecución:** límite de compra a `L`, ejecutable al instante contra lo que
  haya a la venta ≤ `L`:
  - **E1 (cinta, como Jaume v5):** desde disparo + latencia, nos quedamos el
    **50 % del tamaño de cada print** a precio ≤ `L` hasta completar.
  - **E2 (libro, contraste):** barrido del ask disponible ≤ `L` con el libro
    (MBP-10 de Nasdaq si está contratado: solo Nasdaq, pesimista en liquidez).
- **Remanente no ejecutado:** queda colgado a `L`. Mide cuándo y a qué precio
  se ejecuta «a la vuelta» y el pico máximo mientras estuvo colgado. **No
  simules cancelaciones ni recolocaciones**: eso sería una regla, y aquí solo
  se mide.
- **Tamaño de la posición:** pregunta a Álvaro en el CP0 su tamaño real típico.
  Además, rejilla de nocional **1.000 / 3.000 / 10.000 / 30.000 $** (cubre
  también el efecto del añadido de pirámide).

---

## 5. Fases

### Fase 0 — Terreno (sin gastar un céntimo)

1. Lecturas del §2.
2. **CSV de la estrategia:**
   `C:\Users\Alvaro\Downloads\estrategia-1b-modelizaci-n-sobri-3_trades_4473_202609231053.csv`
   (4.473 trades, 2024-01-02 → 2026-09-01, separador `;`, UTF-8 con BOM,
   1.220 SL / 3.253 EOD). Columnas: `Ticker, Fecha, Hora entrada, Hora salida,
   Precio entrada ($), Precio medio entrada ($), Precio salida ($), Stop loss ($),
   PnL ($), R múltiplo, MAE (%), MFE (%), Gap (%), Motivo de salida,
   Ejecuciones`…
3. **Reproduce el CSV con el motor** (mismo nº de trades, mismo nº de SL, mismo
   PnL): así identificas qué estrategia del baúl y qué dataset lo generaron (lo
   necesitas en la Fase 4). Si no cuadra, **PARA**.
4. Verifica en el código qué significa `Hora entrada` (¿vela de señal o de
   ejecución? Con `look_ahead_prevention` se entra a la apertura de la vela
   siguiente). Para ticks, la entrada es el `HH:MM:00` de la vela de ejecución.
5. Verifica PM = `Stop loss ($)` / 1,10 en 50 trades contra el lago.

**CP0:** confirmación de estrategia y dataset + verificación del PM + **lista de
campos que el motor rellenará por defecto en la Fase 4, con su valor y si
afectan al resultado** (regla de `AGENTS.md`) + tamaño real de Álvaro.

### Fase 1 — Censo de candidatos (sin gastar)

- **Nivel A (trades reales del CSV):** precribado con velas M1 del lago dentro
  de cada posición abierta: `max(high[i], high[i+1]) / low[i] ≥ 1,8`
  (permisivo a propósito: la M1 no ve dentro del minuto).
- **Nivel B (universo, para tener muestra):** con +100 % en ≤ 60 s el Nivel A
  va a dar ~5 eventos en 20 meses. Amplía a los **ticker-días del dataset de la
  1B** (haya trade o no) con fogonazo entre 04:00 y 08:45, con el precio ya
  ≥ +20 % sobre el cierre anterior al arrancar y ≥ 15 min de premercado con
  operaciones antes del arranque (PM «bien definido»). **Posición hipotética:**
  corto abierto al precio de arranque `p0`, con PM = máximo corrido hasta el
  arranque. Solo casos con `p0 ≤ PM × 0,95` (las cuatro variantes válidas; la
  entrada típica de la 1B está ~13 % bajo el PM).
- **Sanity check:** en ene-2025→ago-2026 tu Nivel A a ≥ +50 % debería rondar
  los 7 de Jaume. Si sale muy distinto, explica por qué antes de seguir.

**CP1:** tabla de conteo (A y B, por año, a +100 % y +50 %) + nº de ticker-días
a descargar + **coste estimado de Databento** (`metadata.get_cost`). Si el
Nivel A queda en < 10 eventos a +100 %, dilo claro: A es anecdótico y la
conclusión se apoyará en B. **No descargues nada antes del OK.**

### Fase 2 — Confirmación con ticks (gasta, tras el OK)

- **Databento:** la API key está en el entorno. **Nunca la imprimas ni la
  commitees.** Descubre qué hay contratado (`metadata.list_datasets`,
  `list_schemas`). Lo ideal es cinta consolidada + NBBO; si solo hay
  `XNAS.ITCH` (trades, mbp-1, mbp-10, como usó Jaume), di qué cobertura se
  pierde: prints de otras bolsas y de TRF/dark pools, que es justo donde viven
  los prints tardíos, y sin ellos D1 no se puede evaluar. Si hace falta
  completar la cinta con otra fuente (p. ej. Massive, la del lago), **propónlo
  y pregunta**.
- **Tope de gasto: 25 $ acumulados.** Cualquier petición que lo supere: para y
  pide OK. (Referencia: los estudios de Jaume costaron ~5 $.)
- **Ventana por evento:** Nivel A de entrada −5 min a salida +30 min; Nivel B
  de `t0` −15 min a `t0` +30 min (para ver la ejecución «a la vuelta»).
- Guarda en `.tmp_fogonazos/databento/` (parquet). **Datos con licencia: no se
  commitean y no salen del equipo.**
- Clasifica cada candidato: **real puro / real subida / fantasma / no
  confirmado**. Por evento: `t0`, hora del máximo, precio de arranque, máximo,
  % de salto, segundos hasta el máximo, segundos por encima de la mitad del
  salto, % devuelto en 60 s, nº de prints y, si hay libro, dólares a la venta.
  Cruza con el parquet de halts (solo Nasdaq).

**CP2:** tabla de eventos confirmados.

### Fase 3 — Simulación del StopLimitP (el corazón del estudio)

Para cada evento × variante (V0-V3) × disparo (D1-D3) × latencia × tamaño:

- **¿Saltó antes del fogonazo?** (ruido normal: ya estabas fuera). Hora y
  pérdida.
- **% de acciones ejecutadas** a 1 s / 5 s / 60 s / fin de ventana.
- **VWAP de ejecución**; **deslizamiento** = VWAP / T − 1.
- **Pérdida** en % de la posición = VWAP / entrada − 1, y en **R de
  referencia** = (VWAP − entrada) / (T_V0 − entrada). 1R es lo que planeamos
  perder con el stop de hoy.
- **Colgados:** nº de casos, acciones, precio y hora de la ejecución «a la
  vuelta», pico máximo mientras estuvo colgado.
- **Fantasmas (D1):** ¿cuántas veces nos habría sacado un print que no existía
  y a qué precio real?
- Nivel A y Nivel B por separado; puros y subidas reales por separado.
- **Validación del modelo de ejecución (obligatoria):** simula también las
  salidas por SL **normales** (sin fogonazo) de una muestra de ~200 trades del
  Nivel A (incluye su coste en la estimación del CP1). El deslizamiento
  simulado debe parecerse al real del diario (mediana ×1,007, p95 ×1,07). Si
  sale muy distinto, **para y repórtalo**: el modelo estaría mal.

**CP3:** tabla resumen por variante.

### Fase 4 — El otro lado: coste en días normales (motor real)

- Backtests con **el motor real** (`POST /api/backtest` / jobs del
  orquestador), mismo dataset y rango que el CSV, **`look_ahead_prevention:
  true`**, **todos los campos explícitos**, cambiando **solo**
  `risk_management.hard_stop.offset_pct` ∈ {10, 0, −1, −5}.
- **Offsets negativos:** `portfolio_sim.py` aplica `val_struct × (1 + signo ×
  offset / 100)` sin validar el signo en `hard_stop` (`lot_stop` sí rechaza
  negativos). Comprueba en la salida que `Stop loss ($)` = PM × (1 + offset).
  Si la API o el esquema lo rechazan, o el resultado no cuadra, **PARA y dilo:
  no improvises**.
- Por variante y año (2024 / 2025 / 2026): nº de trades (cambian: trades con
  stop inválido que desaparecen y reentradas distintas), % SL, Exp R, PnL,
  máx. DD, MAR.
- **Sanity vs Jaume v5:** el −1 % debería saltar bastante más que el +10 %
  (él midió 50 % vs 30 %).
- **Balance final:** PnL del motor por variante **+ corrección por ticks** de
  los trades con fogonazo (sustituir el fill a `T` que asume el motor por el
  VWAP simulado de la Fase 3). ¿Compensa, año a año?

### Fase 5 — Entrega

- **`docs/INFORME_FOGONAZOS_STOP_1B_<fecha>.md`**, en lenguaje llano. Arriba,
  la respuesta en 5 líneas: ¿nos salimos? ¿a qué precio? ¿qué nivel protege
  más? ¿compensa en el año? ¿es cierto lo de «T = 10, L = 15 → ejecuta a
  10,05»? Luego las tablas y esta chuleta:

  | Stop | Fogonazo: % salida completa ≤ 5 s | desliz. mediana / p95 | pérdida mediana / p95 (R) | colgados | Días normales: % SL | Exp R | PnL/año | Balance neto/año vs V0 |
  |---|---|---|---|---|---|---|---|---|

- **Entrada al final de `docs/MEMORIA_MADRE.md`** (formato habitual). Cualquier
  bug o incoherencia, en formato `[HALLAZGO · …]`.
- **Lista de preguntas para el bróker/DAS** que los datos no pueden responder
  (qué print dispara, ruta en premercado, qué hace con el stop en un halt),
  enlazadas con las preguntas 19 y 22 de `BOT_EJECUCION_PREGUNTAS.md`.
- Resultado negativo o muestra insuficiente **también se entrega**: saber que
  da igual dónde se pone el stop es información operativa.

---

## 6. Reglas (resumen; manda `AGENTS.md`)

- Cero cambios de código. Scripts efímeros en **`.tmp_fogonazos/`**, y
  **nunca** `git add` de carpetas `.tmp_*`.
- **Zona cerrada:** bot de alertas y `D:\bot_senales\` no se tocan.
  `market_frame.py` solo en lectura.
- Backend local: el log debe mostrar `DISABLE_GCS_SYNC=true`; si no aparece,
  **para**. No abras `local_data.duckdb` con otro proceso mientras corre el
  backend. Lago en solo lectura.
- Backtests solo con el motor real, nunca réplicas. Antes de lanzarlos, la
  lista de campos por defecto (CP0).
- Si un dato contradice este PRD (p. ej. el stop del CSV no es PM × 1,10),
  **para y reporta con evidencia**.
- Números reales, nunca suposiciones. Lo que sea hipótesis, márcalo
  literalmente como **HIPÓTESIS**.
- Avisa antes de cualquier operación de > 10 GB o > 1 hora.
