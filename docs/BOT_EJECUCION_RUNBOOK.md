# RUNBOOK del bot de ejecución — qué hacer en una emergencia (BORRADOR, 19-sep-2026)

> Una página. Para el socio o para Jaume un mal día. No hace falta entender el bot.
> Versión preliminar: se cierra al final, con el PDF del bróker y los nombres reales de comandos,
> botones y teléfonos. Rellenar los huecos marcados con [ ].

## 0. Datos a mano

| Qué | Dónde |
|---|---|
| Teléfono del bróker (Sage Trading) | [ ] |
| Usuario del panel del VPS (reiniciar / apagar la máquina) | [ ] proveedor: [ ] |
| Acceso RDP al VPS (usuario propio) | [ ] |
| Grupo de Telegram del bot y chat_id autorizados | [ ] |
| Diario del bot (ficheros por día) | [ ] ruta en el VPS |
| Cuadro de mandos del bot | [ ] dirección |

## 1. Antes de tocar nada: mirar (2 minutos)

1. Telegram: último aviso del bot y su nivel (1 informativo, 2 aviso, 3 MÁXIMO). Manda `/estado` y `/salud`.
2. Si el bot no contesta a `/estado` en 30 s: el bot está caído o sin conexión. Pasa al nivel B.
3. Si contesta: lee qué posiciones hay (`/posiciones`) y qué órdenes vivas (`/ordenes`). Toda posición debe tener su stop puesto en DAS. Si alguna no lo tiene, es una emergencia.

## 2. Actuar, del más suave al más fuerte. Parar en el primero que resuelva.

**Nivel A — Telegram (el bot está vivo)**
- Solo dejar de abrir nuevas: `/pausar`. Las posiciones abiertas se siguen gestionando. Para volver: `/reanudar`.
- Cerrar una posición concreta: `/cerrar TICKER SI`. Cerrar todo: `/cerrar_todo SI`. El bot cierra los cortos al ask y los largos al bid, cancela las órdenes de esas posiciones y lo registra.
- Apagar el bot del todo (tomar el control humano): `/apagar`. A partir de aquí, las posiciones solo las protegen los stops que ya están en DAS.
- Cuando haya intervenido una persona y el bot deba seguir: `/sigue`.

**Nivel B — Panel del proveedor del VPS (el bot no responde)**
- Entra en el panel y REINICIA la máquina. Al arrancar, DAS, el vigilante y el ejecutor se levantan solos, en ese orden, y el bot reconcilia antes de hacer nada. Debe volver a contestar por Telegram en unos minutos.
- Si prefieres que NO haga nada al arrancar: APAGA la máquina desde el panel y pasa al nivel C.

**Nivel C — Escritorio remoto (RDP) y DAS a mano**
- Entra al VPS con tu usuario. Si el bot sigue corriendo y no quieres que actúe, ciérralo (icono / ventana del bot) o apaga la máquina.
- Abre DAS: revisa posiciones y órdenes. Cierra a mano lo que haga falta (cubrir cortos comprando al ask). Antes de cerrar una posición a mano, cancela sus órdenes vivas para no comprar de más.

**Nivel D — El bróker**
- Si DAS no funciona o no puedes entrar: llama al bróker y pide cerrar las posiciones. Ten a mano número de cuenta y símbolos.

## 3. Situaciones concretas

| Si ves… | Haz… |
|---|---|
| Aviso MÁXIMO «posición sin stop» | `/estado`; si el bot vive, ya lo está reintentando; si no consigue ponerlo, `/cerrar TICKER SI` o nivel C. |
| Aviso MÁXIMO «cisne negro» (precio disparado, orden de emergencia sin ejecutar) | NO cerrar a mercado a ciegas. El precio suele volver en minutos; la orden de emergencia se ejecuta sola al volver. Si a la media hora sigue arriba, decide con Jaume. |
| Aviso «compras de más / posición larga» | El bot las vende solo. Comprueba con `/posiciones` que no queda nada largo. |
| Aviso «DAS caído» | El bot reconecta solo cada 30 s y avisa cada 5 min. Si dura más de 15 min, nivel B. Los stops residentes protegen mientras tanto. |
| Aviso «feed de Massive caído» | El bot no abre nuevas y mantiene las abiertas con sus stops. Nada que hacer salvo vigilar. |
| «Halt» en una posición | No se puede hacer nada hasta que reabra. El bot tiene la orden preparada. Si es T12 (Nasdaq pide información), pasa a control humano: es cuestión de días. |
| Fin de día (EOD de una estrategia) con posición abierta | Aviso MÁXIMO: cerrar a mano (nivel C) o `/cerrar TICKER SI`. |
| No llega ningún «estoy vivo» y no hay avisos | La máquina puede estar apagada: nivel B. |

## 4. Después de la emergencia

- Anota en Telegram qué hiciste y a qué hora (queda en el diario).
- No reanudes el bot sin `/sigue` o sin que Jaume lo revise.
- Si actuaste a mano en DAS, el bot lo detecta, protege y se pausa: es normal; `/sigue` cuando esté todo claro.

*Versión 0.1 (borrador). Nombres de comandos, botones y rutas: provisionales hasta el repaso final con el PDF.*
