# Alarmas del Screener — plan por fases

> **Estado:** F1 construida (esta rama). F2–F6 pendientes.
> **Principio:** cada fase llega a producción y se puede probar sola. Ninguna
> depende de que se construya la siguiente.

---

## Qué es esto y qué NO es

Un sistema que vigila el mercado en vivo y avisa cuándo se cumplen unas
condiciones que configura el usuario. **No manda órdenes, no sabe si hay acciones
prestables y no valida si la estrategia gana dinero.**

**Es independiente del backtester por decisión de diseño.** No importa nada de
`app/backtester/`, `app/services/strategy_engine.py` ni `app/services/indicators.py`.
Tiene su propia aritmética de VWAP, EMA y máximos de premarket. Consecuencia
asumida: un resultado de alarmas y un resultado de backtest **no son directamente
comparables** y no deben presentarse como si lo fueran.

**Amplía las alarmas sonoras que ya existían** (`Screener.tsx`, commit a445b34):
aquellas viven en el navegador, solo ven la tabla abierta y no saben de barras.
Sus reglas (`{field, op:"gte", value}`) son un caso degenerado del modelo nuevo y
se aceptan sin traducción — ver los alias en `services/alarms/fields.py`.

---

## F1 · La alarma existe y avisa ✅

Configurar alarmas desde el Screener, encenderlas y apagarlas, y recibirlas por
Telegram y en el navegador.

- Motor sobre el stream `A.*` que el live screener ya consume (una sola conexión
  a Massive: la cuenta no admite dos).
- Barras de 1 minuto ancladas a las 04:00 ET, con backfill REST al empezar a
  vigilar un ticker (resuelve también el arranque en frío a media sesión).
- Vocabulario de ~34 campos, instantáneos y de barra. El modo de disparo se
  **deduce** de los campos usados; el usuario no lo elige.
- Universo pegajoso, ventana horaria, enfriamiento por ticker.
- Filtro de splits del día.
- Sizing en el aviso: stop, acciones y locates. Dos modos (riesgo y nominal).
- Telegram: vinculación por deep-link de un solo uso, aviso de prueba, detección
  de bloqueo.
- Registro de todas las señales en BD **desde el día uno**, aunque el panel llegue
  en F2: sin esto, F3 arrancaría con el historial vacío.

**Cómo se prueba:** configuras una alarma, pulsas *Probar* para confirmar el canal,
y esperas. Durante F1 **tu chat de Telegram es el historial** — de ahí que Telegram
no fuese opcional en esta fase.

---

## F2 · El historial se ve

Panel de señales dentro del Screener: qué disparó, cuándo, a qué precio y por qué.
Auditar la alarma con datos en vez de con memoria de Telegram.

- Panel de historial (la API `GET /api/alarms/events/list` ya existe desde F1).
- Eventos LULD (halts): marcar el ticker como no operable.
- Aviso visible cuando el motor arranca a media sesión con premarket incompleto.

**Decisión abierta:** cuando salta la condición y el ticker está en halt,
¿silenciamos el aviso o lo mandamos marcado?

---

## F3 · Marcar y medir

La fase que decide si existe F5.

- Botones «La tomé» / «Paso» en el mensaje de Telegram (inline keyboard) y en el
  panel.
- Precio provisional (el del aviso) vs confirmado (el que teclea el usuario).
- Rendimiento a **doble columna**: todas las señales frente a las tomadas.

> Las dos columnas contestan preguntas distintas y hacen falta las dos. La de
> todas las señales **debe incluirlas todas** o deja de ser una medición: si solo
> mides las que tomaste, la muestra está sesgada por tu propia selección. La
> resta de las dos dice si la discreción del trader suma o resta.

**Decisión abierta:** si nunca confirmas que entraste y el precio llega al stop
teórico, ¿avisamos igual?

---

## F4 · Alarmas de precio manual

Armar a mano «avísame si XYZ toca 3,85». Cubre el stop sin necesidad de tracker.
Técnicamente ya cabe en el modelo actual (`price >= X` + watchlist); lo que falta
es el atajo de un clic desde la ficha del ticker.

---

## F5 · Tracker de posición

Máquina de estados: confirmas la entrada y el sistema vigila stop, hora de salida,
ventana de piramidación y reentradas.

**Solo si F3 dice que merece la pena.** Si el hueco entre el cierre teórico de la
barra y el precio real de entrada se come el edge, esta fase no se construye.

---

## F6 · Journal

El estado de cuenta real (P&L, win rate, expectancy sobre operaciones reales) es
el [Journal](../manual-prd/PRD_EJEMPLO_JOURNAL.md), no este módulo. Las alarmas se
enchufan a él pre-rellenando una entrada cuando marcas una señal como tomada.

---

## Riesgos vivos

| Riesgo | Estado |
|---|---|
| Splits fingiendo ser runners (25,3% de los gaps ≥100% de 2026) | Cubierto en F1 |
| Halts (LULD) | F2 |
| El aviso llega tras el cierre de la barra | Decisión de diseño; se mide en F3 |
| El backend caído a las 4:00 ET (10:00 España) | **Sin resolver** — hace falta vigilancia y aviso de caída |
| Arranque en frío a media sesión | Cubierto por el backfill de F1; el aviso visible es F2 |

---

## Decisiones que siguen abiertas

1. **Unidad del dollar volume de la 1B.** «> 0,5» — ¿0,5M USD por barra de un
   minuto, o acumulado del día? El campo está y acepta el número que se le ponga,
   pero el valor correcto sigue sin confirmar.
2. **Sizing de la 1B.** «Size por distancia a Stop Loss» dice riesgo; «Se entra
   con 300» dice nominal. Con entrada 3,42 y stop 3,85 salen **697 acciones**
   (riesgo 300 $) frente a **88** (nominal 300 $): 8x de diferencia. El motor
   soporta los dos modos (`risk_usd` y `notional_usd`); falta decidir cuál es el
   de la estrategia.
3. **Audiencia.** El Screener está gateado a Admin (`screener.access`), así que
   las alarmas caen detrás de esa puerta. Abrirlo a más usuarios es decisión de
   producto.
4. **Vigilancia del servidor** a la apertura del premarket.
