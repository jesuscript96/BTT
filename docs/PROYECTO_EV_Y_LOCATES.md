# Rolling EV, y si compensa comprar locates

> **Estado: PROYECTO, sin implementar.** Lo pidió Jaume el 2026-09-03 para
> decidirlo a primera hora del 4. Aquí está la auditoría de lo que hay, el
> diseño de lo que falta y **las decisiones que hacen falta antes de escribir
> código**. Nada de esto está tocado todavía.

## Por qué importa

El uso final no es mirar un gráfico bonito: es decidir **si merece la pena
comprar los locates de una acción**. Si el fade que la acción tiene que hacer
solo para pagar el alquiler es mayor que lo que la estrategia gana de media, esa
operación pierde dinero antes de empezar.

```
fade necesario (%) = coste del locate por acción / precio de entrada × 100
merece la pena  ⟺  EV (%) > fade necesario (%)
```

---

## 1. Auditoría: el gráfico actual tiene dos problemas

`frontend/src/components/backtester/RollingEVChart.tsx` calcula la esperanza de
la forma correcta —`P(gana)×media_gana − P(pierde)×media_pierde`— pero con dos
pegas.

### 1.1 El modo «días» hace MEDIA DE MEDIAS (grave)

Agrupa por día, saca el EV de cada día y luego promedia esos EV. Un día con una
operación pesa **lo mismo** que uno con diez. Comprobado:

| | |
|---|---|
| lunes: 1 trade que gana 1,0R | EV del día `+1,000 R` |
| martes: 10 trades que pierden 0,2R | EV del día `−0,200 R` |
| **modo DÍAS** (media de medias) | **`+0,400 R`** |
| **modo TRADES** (los 11 juntos) | **`−0,091 R`** ← el de verdad |

No es un decimal: cambia **el signo**. Un mes con muchos días flojos de una sola
operación ganadora se pinta como rentable.

> **Jaume sospechaba lo contrario** («en semanas va bien, en trades no sé»). Es
> al revés: **el modo por trades es el correcto** y el de días es el sesgado.

**Arreglo:** ponderar por número de operaciones, o directamente calcular el EV
sobre todos los trades de la ventana de días (que es lo que ya hace el modo
trades). Son dos líneas.

### 1.2 El resultado está en R, no en % — y para locates hace falta el %

Los dos modos promedian `r_multiple`. Eso responde a «cuántos riesgos gano por
operación», que está muy bien para valorar la estrategia, pero **no se puede
comparar con un coste por acción**. El locate se paga en dólares por acción; el
EV en R no dice nada del precio.

**Esto no es un bug**: el gráfico hace lo que dice hacer. Falta la otra medida.

---

## 2. Lo que hay que añadir: EV en % del precio de entrada

```
r_pct del trade = (salida − entrada) / entrada × 100     (signo según el lado)

EV% = P(gana) × media(r_pct | gana) − P(pierde) × |media(r_pct | pierde)|
```

### Decisión pendiente: qué costes lleva dentro

**El EV que se compara con el locate tiene que ser neto de comisiones y
slippage, pero BRUTO de locates.** Si se le restan los locates, el cálculo se
muerde la cola: estarías usando un EV que ya los pagó para decidir si pagarlos.

> ✅ **Comprobado el 2026-09-03: ya está bien.** `portfolio_sim.py:1225-1239`
> deja el `pnl` de cada trade **sin** locates y guarda el coste aparte, en
> `pnl_with_locates`. Como `r_multiple` sale del `pnl`, el gráfico actual es ya
> bruto de locates y sirve tal cual. Una incógnita menos.

> ⚠️ **Lo que sí hay que evitar: calcular el `%` a partir de `r_multiple`.** El
> motor lo guarda **redondeado a dos decimales**
> (`robustness_service.py:146`), y sobre operaciones pequeñas ese redondeo se
> come justo el margen que estamos midiendo — un fade del 1,19 % contra un EV
> del 2,4 % no admite ruido de ese tamaño. El `%` hay que sacarlo de
> `entry_price` y `exit_price`, que están completos.

---

## 3. La pantalla: EV vs fade necesario

Una tabla pequeña, en el mismo sitio que el gráfico:

| | |
|---|---|
| EV de la estrategia | `+2,4 %` |
| Precio medio de entrada | `0,84 $` |
| Coste del locate por acción | `0,010 $` ← lo teclea Jaume |
| **Fade necesario** | **`1,19 %`** |
| **Veredicto** | **compensa** (margen `+1,21 pp`) |

El coste del locate se teclea porque cambia por acción y por día; no está en
ningún sitio del que se pueda leer.

**Decisión pendiente:** ¿el precio de entrada es el medio de los backtests, o
uno que se teclee también? Lo primero es más automático; lo segundo sirve para
una acción concreta que estás mirando ahora.

---

## 4. Preguntárselo al bot por Telegram

Va sobre el mismo mecanismo que el otro pendiente de Telegram (consultar el
estado de una posición): **hoy el bot solo emite, no recibe**.

### Arquitectura

```
bot.py
  └── tarea asyncio aparte: getUpdates (long polling, ~30 s)
        │   aislada con try/except: un fallo suyo NO puede tumbar
        │   el bucle de velas
        ├── filtra por chat_id  ← solo responden Jaume y su socio
        └── despacha comandos
              /locate TICKER COSTE   -> ¿compensa?
              /estado TICKER         -> el otro pendiente
```

Unas 40 líneas. Lo único delicado es que **es la primera vez que el bot acepta
entradas del exterior**: filtrar por `chat_id` no es opcional.

### De dónde sale cada dato

| dato | fuente |
|---|---|
| EV de la estrategia | del backtest, ya calculado (§2) |
| precio actual | el frame en vivo, ya está |
| coste del locate | lo escribe Jaume en el mensaje |

**Decisión pendiente:** el EV de una estrategia cambia con cada backtest. ¿El
bot usa el último calculado, uno guardado a mano como «EV oficial», o Jaume lo
mete en el mensaje? Lo tercero es lo más simple y lo más honesto: el bot no
puede saber qué backtest consideras válido.

---

## 5. Decisiones — TODAS TOMADAS (2026-09-03, de noche)

1. **Modo «días»: se arregla.** Jaume: «coger los últimos 30 días y usar el
   cálculo en base a los trades que ha habido esos días, independientemente de
   si han sido 1, 3 o 33». Es exactamente quitar la media de medias.
2. ~~¿Bruto de locates?~~ Ya lo es.
3. **El precio NO se teclea: entra en vivo.** Ver §6.
4. **El EV se mete A MANO**, en la app y en el comando. El bot no puede saber
   qué backtest consideras válido.

---

## 6. Lo que Jaume quiere de verdad: en vivo, sobre lo que el bot ya vigila

No es una calculadora estática. Es una **decisión que se toma mientras la acción
se mueve**, sobre los tickers que el radar ya está siguiendo (los que pasan el
filtro de gap). El peor escenario es que el gap se quede en el 50 %, así que el
candidato ya está identificado.

**En la app**, junto a cada ticker vigilado:

```
MIMI   0,8422 $   locate [ 0,010 ] $   EV [ 2,4 ] %      ← se teclean los dos
       fade necesario 1,19 %  ·  EV 2,40 %
       ► VENTAJA MATEMÁTICA POSITIVA        (se actualiza con cada tick)
                                             [ OK ] ← congela el seguimiento
```

El precio llega por el WebSocket que **ya alimenta el cuadro de mandos**, así
que el veredicto se recalcula solo. El botón detiene el seguimiento cuando ya
has decidido.

**En Telegram** no puede ser continuo, así que el comando toma una foto:

```
/EVF MIMI
→ MIMI a 0,8422 $ · locate 0,010 $ · EV 2,4 %
  fade necesario 1,19 %
  VENTAJA MATEMÁTICA POSITIVA — <frase desenfadada>
```

Jaume lo pidió con guasa («compra a mansalva, ándale wei», «quieto capitán, que
están muy caras»), con **varias frases rotando**. Pero el veredicto en sí va
SIEMPRE con las mismas palabras: `VENTAJA MATEMÁTICA POSITIVA` o `NEGATIVA`. La
broma acompaña; no sustituye al dato.

### El tamaño NO entra en la fórmula (y por qué)

```
compensa ⟺ N × precio × EV% > N × coste   →   precio × EV% > coste_por_acción
```

El número de acciones **se cancela**: si el fade no llega para un locate,
tampoco para mil. Lo mismo con los pennies — salen más acciones, pero el coste
sube en la misma proporción.

**La excepción son los paquetes de 100**, que se cobran redondeando hacia
arriba:

| posición | paquetes | coste real por acción (locate a 1 $/paquete) |
|---|---|---|
| 150 acciones | 2 | `0,0133 $` (+33 % sobre el nominal) |
| 1.647 acciones | 17 | `0,0103 $` (ruido) |

Con las posiciones de Jaume (1.600-2.000 acciones) da igual, pero en una
posición chica decide, así que el cálculo lo lleva.
