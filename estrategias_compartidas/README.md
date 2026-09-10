# Estrategias compartidas (Álvaro ↔ Sailor)

Carpeta git-tracked para compartir estrategias del backtester entre
desarrolladores. **Un JSON por estrategia**, dentro de la subcarpeta de cada
uno (`alvaro/`, `sailor/`). El transporte es **git**: la app no sube nada sola.

## Cómo funciona

1. **Compartir** — en el backtester, pestaña **"Compartidas"** (bajo el chart,
   a la derecha de "Charts + Optimization IS"), sección *"Compartir una tuya"*:
   botón **Compartir** junto a cada estrategia guardada. Eso escribe (o
   actualiza) un JSON en tu subcarpeta de este directorio.
2. **Que el otro lo vea** — commitea este directorio en tu rama e intégralo a
   `staging` como siempre. Nada viaja hasta que tú haces push.
3. **Importar** — tu socio hace pull, abre la pestaña "Compartidas" y pulsa
   **Importar copia** sobre la tuya. La copia queda en SUS estrategias
   guardadas (copia nueva cada vez; re-importar no actualiza, crea otra) y
   aparece en el desplegable *"cargar estrategia guardada…"* del backtester.

**Nada automático:** solo generan fichero las estrategias en las que pulses
"Compartir". Tus pruebas y borradores nunca salen de tu local.

## Convenciones

- Nombre de fichero: `slug-del-nombre--XXXX.json` (`XXXX` = 4 primeros chars
  del id origen). Re-compartir una estrategia sobreescribe su mismo fichero →
  diff limpio al actualizar.
- Formato del JSON: `format_version`, `shared_by`, `shared_at`,
  `source_strategy_id`, `name`, `description`, `definition` (exactamente el
  `definition` que guarda la tabla `strategies`).

## Setup una vez por dev (en `backend/.env`, que NO se commitea)

```dotenv
SHARED_STRATEGIES_OWNER=alvaro   # sailor en su caso
```

Sin esa variable los ficheros caen en `dev/` — funciona, pero no separa.

## Nota

Los `*.json` están ignorados globalmente por el `.gitignore`; este directorio
tiene una negación explícita (`!estrategias_compartidas/**/*.json`) para que
estos ficheros SÍ se commiteen. No muevas la carpeta sin tocar esa excepción.
