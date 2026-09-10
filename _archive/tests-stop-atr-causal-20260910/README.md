# test_stop_atr_causal.py — archivado (2026-09-10, merge staging → alvaro)

Este test cubría la versión de ÁLVARO del fix causal del stop ATR Multiplier
(`fe40b65`: nivel fijado en la entrada con el ATR de la **vela de señal**).

Ese mismo look-ahead lo arregló Jaume en paralelo con otro diseño
(`1ed3d7e`, ya en staging): nivel en la **barra de entrada** con
`entry ± k·ATR[i]`, sin entrada si aún no hay ATR (con respaldo % configurable
de `033d9cb`), ATR unificado a Wilder y paridad Python↔JIT↔bot verificada.

Decisión de Álvaro (2026-09-10 tarde): nos quedamos con la versión de Jaume
para mantener backtest ↔ bot idénticos. Este test quedó obsoleto porque
comprueba la semántica vieja (p. ej. "NaN → 5 % alrededor de la entrada",
que ahora es "NaN → no se entra") y fallaría en verde contra el motor nuevo.

La cobertura causal vive ahora en:
- `backend/tests/test_n2a_native_equivalence.py` (guardia: ninguna de las dos
  vías vuelve a colapsar el ATR a una fracción — versión de Jaume).
- `backend/tests/test_bot_tamano_todos_los_stops.py` en staging (cruza bot ↔
  simulador; excluido de la rama de Álvaro por la zona cerrada de alertas).

Si algún día se quiere un test local equivalente, hay que escribirlo contra
la semántica de `1ed3d7e`, no reactivar este.
