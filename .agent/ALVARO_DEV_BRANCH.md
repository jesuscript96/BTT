# Git Branch Rules — Álvaro

Aplica cuando el desarrollador es Álvaro.

## Rama de trabajo — `alvaro-rama-desarrollo`

Álvaro trabaja y commitea en su rama personal **`alvaro-rama-desarrollo`**.
La rama **conjunta** con Sailor es **`staging`**: ahí se integra el trabajo de
los dos para estar sincronizados, sin tocar `main`.

## Flujo diario
1. `git branch --show-current` — verificar rama.
2. Ponerte en tu rama: `git checkout alvaro-rama-desarrollo`.
3. **Traer lo último de la conjunta antes de trabajar:**
   `git fetch && git merge origin/staging` (así tienes los avances de Sailor).
4. Hacer cambios y commit a `alvaro-rama-desarrollo`.
5. Push a la rama personal: **autorización permanente** (Álvaro, 22-sep-2026:
   «a mi rama siempre, a staging nunca lo empujes») — no hace falta pedir OK
   para cada push a `alvaro-rama-desarrollo`. Tras cada push:
   `git push origin alvaro-rama-desarrollo`.

## Compartir tu trabajo (integrar a `staging`)
Cuando tu avance esté listo para que lo tenga Sailor:
```
git checkout staging
git pull origin staging
git merge alvaro-rama-desarrollo
git push origin staging          # (tras confirmación)
```
(O por Pull Request contra `staging` si preferís revisión.)

**La IA NUNCA empuja a `staging`** (regla fija de Álvaro, 22-sep-2026): la
integración la hacen Álvaro/Jaime con el procedimiento porta-verja documentado
en `docs/MEMORIA_MADRE.md` (TRABAJO 18-09·4 y ESTADO 22-09·1).

## Prohibido
- Tocar `main` (push / commit / merge). Es producción con clientes de pago.
- Push / commit directo a `develop`.
- **🚨 Tocar el bot de avisos en vivo o la página de Alertas.** Ni modificarlos,
  ni arrancarlos, ni configurarlos, **ni descargarlos para probarlos**. Los
  llevan Jaume y Sailor en exclusiva por ahora. Dos motivos que no se arreglan
  teniendo cuidado: los avisos van a un Telegram con el que Jaume **opera de
  verdad**, y la cuenta de datos en vivo **admite una sola conexión** — si
  arrancas el bot en tu equipo dejas sordo el suyo y ninguno de los dos ve un
  error. Ficheros afectados y la única excepción (`market_frame.py`, compartido
  con el backtester): sección «Zona cerrada» de `AGENTS.md`.

  Cuando te llegue trabajo de Sailor por `staging`, esos ficheros vendrán en el
  merge — es normal y no hay que hacer nada con ellos. **Traerlos no es tocarlos:
  no los arranques ni los configures.** Si algo de ahí te bloquea una tarea
  legítima, díselo a Jaume; la decisión es suya, no del agente.

### 🪨 REGLA EN PIEDRA — el bot en la rama de Álvaro (fijada por Álvaro, 2026-09-25)

El código del bot está en esta rama **dormido**: llega con los merges de
`staging` y **aquí nunca se ejecuta**. El bot vive y opera SOLO con Jaume.
Ninguna IA ni persona se salta esto, por ningún motivo:

1. **Nunca se arranca el bot en el equipo de Álvaro.** Ni `arrancar_bot.bat`,
   ni `D:\bot_senales\`, ni ningún proceso `bot_alerts_*`, ni «para probar un
   momento». Una sola conexión a Massive: arrancarlo aquí deja sordo el de Jaume.
2. **En `backend/.env` de Álvaro, `BOT_ALERTS_ENABLED` y `BOT_ALERTS_TELEGRAM`
   no se ponen nunca a `true`** (por defecto están apagados; se dejan sin poner).
3. **Los ficheros del bot NO se borran ni se excluyen de esta rama.** Si se
   borraran, el día que algo de aquí llegue a `staging` borraría el bot de Jaume.
   Se quedan tal cual `staging`.
4. **En un merge de `staging`, cualquier conflicto en la zona del bot se resuelve
   cogiendo la versión de `staging` literal.** Nunca se edita a mano.
5. **Ningún cambio del bot sale de esta rama.** Si una tarea pide tocarlo: parar y
   preguntar a Jaume.

## Seguridad en local (imprescindible)
- `backend/.env` con `DISABLE_GCS_SYNC=true` y `LIVE_SCREENER_ENABLED=false`.
- Nunca commitear `.env`, `.env.local`, `gcs-key.json`, `*.duckdb*`, `data/`, `.cache/`.
- Guía completa: `docs/GUIA_DEV_LOCAL_Y_DEVELOP_PARA_IA.md`.
