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
5. Antes de push, pedir confirmación al usuario. Tras OK:
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

## Seguridad en local (imprescindible)
- `backend/.env` con `DISABLE_GCS_SYNC=true` y `LIVE_SCREENER_ENABLED=false`.
- Nunca commitear `.env`, `.env.local`, `gcs-key.json`, `*.duckdb*`, `data/`, `.cache/`.
- Guía completa: `docs/GUIA_DEV_LOCAL_Y_DEVELOP_PARA_IA.md`.
