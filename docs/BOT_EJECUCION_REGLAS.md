# REGLAS del bot de ejecución en DAS (Sage Trading)

> **Qué es este fichero.** El libro de reglas que dirigirá al bot de ejecución.
> Es el documento que el código tiene que obedecer y el que se lee cuando algo
> sale mal para saber qué debía haber pasado. Abierto el 2026-09-12. Se
> construye contestando el banco de preguntas de `BOT_EJECUCION_PREGUNTAS.md`:
> cada pregunta contestada se convierte en una regla de aquí (o en un «no
> aplica» razonado), con su número y su estado.
>
> Las conclusiones del estudio de cisnes negros (`Informe_cisnes_negros_premercado.pdf`,
> `Resumen_ejecutivo_riesgos.pdf`) NO son reglas hasta que se escriban aquí con
> su número. Regla de trabajo: nada entra sin fecha y sin estado.

---

## 0. Cómo se escribe una regla

Cada regla lleva un identificador `R-<ÁREA>-<nn>` (las áreas son las letras del
banco de preguntas: A señal, B entrada, C stop, D salidas, E capital compartido,
F halts, G disparos de precio, H locates, I riesgo y cortacircuitos, J
infraestructura, K estado y reconciliación, L calendario, M control humano, N
registro, O pruebas y despliegue, P backtester vs vivo, Q seguridad).

Plantilla (todos los campos, aunque sea para poner «ninguno»):

```
### R-X-nn · Título corto
- Situación: cuándo aplica. Condición observable y medible, no una intención.
- Detección: qué dato la dispara y de dónde sale (DAS, feed de Massive, reloj, diario).
- Acción: qué hace el bot, en orden, y en cuánto tiempo.
- Quién la ejecuta: guarda pura / ejecutor / reconciliación / supervisor / humano.
- Parámetros: nombre, valor por defecto y dónde vive (JSON de la estrategia o cuadro de mandos).
- Si la acción falla: plan B (degradación) y aviso.
- Prueba: cómo se verifica (tabla de casos, simulacro, sesión sombra, canario).
- Estado: borrador / decidida (fecha) / depende del PDF (pregunta X) / descartada (por qué).
- Origen: pregunta del banco (p. ej. C5) y dato del estudio que la sustenta.
```

Criterios para que una regla sea válida:

1. Se puede comprobar con una tabla de casos sin mercado delante.
2. Dice qué pasa cuando la propia regla no se puede cumplir.
3. No depende de que un humano esté mirando, salvo que lo diga expresamente.
4. Un parámetro no es una regla: la regla dice qué se hace con el parámetro.
5. Si dos reglas chocan, gana la más restrictiva; si no está claro, se escribe
   una tercera que lo resuelva.

## 1. Principios marco (decisiones ya tomadas por Jaume el 5-sep-2026)

No son reglas numeradas: son el marco que ninguna regla puede contradecir.
Cualquiera se puede rebajar, pero por escrito y con fecha.

- **M1.** Bot DISTINTO al de avisos. Reutiliza su código, es otro proceso.
- **M2.** Por fases, cada fase con sus pruebas; no se pasa a la siguiente hasta
  que la anterior funciona. Eficacia y cero errores antes que velocidad.
- **M3.** Posición objetivo, no traducción evento→orden: el motor dice qué
  posición debería haber; el ejecutor acerca la real a la objetivo dentro de límites.
- **M4.** Cinco capas con interfaz mínima: señal, guarda pura, ejecutor,
  reconciliación, diario + supervisor.
- **M5.** Invariante: ninguna posición sin stop residente en el bróker.
- **M6.** Invariante: la orden va antes que cualquier registro que pueda bloquearse.
- **M7.** Invariante: la posición real (DAS) manda sobre la teórica, siempre.
- **M8.** Telegram solo para lo que importa: entradas, salidas, datos concretos
  y errores. Las prealertas no van a Telegram (sirven para procesos internos).
- **M9.** Tamaño por fracción del volumen reciente desde el principio.
- **M10.** Premercado = órdenes límite. Para salir, asegurar la salida aunque
  sea a peor precio.
- **M11.** La exposición al riesgo viaja en el JSON de la estrategia y tiene
  cuadro de mandos propio.
- **M12.** Producción en VPS Windows con DAS dentro; desarrollo en el PC de
  Jaume; el VPS es lo último pero se prepara pronto. El socio puede pausar,
  apagar y reiniciar.
- **M13.** Guardas diseñadas para las dos sesiones (PM y RTH) desde el inicio.

## 2. Puntos abiertos que condicionan varias reglas (no decididos)

- **Stop limitado vs stop de mercado** (P2). Recordárselo a Jaume. Datos en
  el informe v5 §11 y v6 §13.
- **Guarda de fogonazo**: no ejecutar si el precio subió más de X % en Y s;
  esperar N s. Datos en el informe §9 y resumen «Riesgo 1».
- **Exposición por ticker** (P3): 3-4 % barajado, nada decidido.
- **Locates pronto y barato vs en prealerta** (P4).
- **Cadena de LULD como aviso** (P10): 1 de cada 300 días con ≥ 5 LULD acaba en T12.

## 3. Reglas

*(Ninguna todavía. Se van añadiendo por área a medida que se contesta el banco
de preguntas. Orden previsto de ataque, por riesgo: C y G (stop y disparos),
F (halts), I (cortacircuitos), B (entrada), H (locates), J y K (infraestructura
y reconciliación), después el resto.)*

### Área C · Stop y protección

### Área G · El precio se dispara

### Área F · Halts

### Área I · Riesgo y cortacircuitos

### Área B · Entrada

### Área H · Locates

### Área J · Infraestructura

### Área K · Estado y reconciliación

### Área A · Señal y datos

### Área D · Salidas y pirámides

### Área E · Capital compartido entre estrategias

### Área L · Calendario

### Área M · Control humano

### Área N · Registro y contabilidad

### Área O · Pruebas y despliegue

### Área P · Backtester vs vivo

### Área Q · Seguridad

## 4. Registro de cambios

| Fecha | Qué | Quién |
|---|---|---|
| 2026-09-12 | Se abre el fichero con el formato, los principios marco y el índice de áreas. Ninguna regla aún. | Jaume + Claude |
