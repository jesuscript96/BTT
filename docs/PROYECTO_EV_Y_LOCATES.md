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

## 5. Resumen de decisiones para Jaume

1. **¿Arreglo el modo «días» del gráfico?** Cambia los números que has visto
   hasta ahora, a peor en las rachas de días flojos con pocas operaciones.
2. ~~¿El EV% se calcula bruto de locates?~~ **Resuelto**: ya lo es, el `pnl`
   del motor no los lleva dentro.
3. **¿Precio de entrada medio del backtest, o tecleado?**
4. **¿El EV para Telegram lo da el bot o lo escribes tú en el mensaje?**

Con esas cuatro respuestas, lo de §2 y §3 es media mañana y lo de §4 va junto
con el otro comando de Telegram.
