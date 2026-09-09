# PROXIMOS ITEMS — Guía de pendientes (Álvaro)

> **Qué es este doc:** la lista de bugs a arreglar y features a hacer, con su
> spec técnica lista para ejecutar. Nacido de la auditoría del backtester del
> 2026-08-21.
>
> **Flujo (obligatorio):**
> 1. Cuando un item se **ejecuta**, se **borra de este doc** y se **registra en
>    `docs/MEMORIA.md`** (entrada del día con qué se hizo y dónde se dejó).
> 2. Las ideas sin decisión van a `docs/POSIBLES_ARREGLOS.md`, no aquí. Si se
>    deciden, suben a este doc con su spec.
> 3. Ninguna IA ejecuta nada de aquí por su cuenta: se trabaja cuando Álvaro
>    lo ordena, un item por vez.
>
> **Rama:** `alvaro-rama-desarrollo`. Reglas de la casa aplican (tests primero,
> paridad Python↔JIT, look_ahead_prevention, nunca `main`).
>
> **2026-08-21:** ejecutados los 3 items de la auditoría — ITEM 3 (fix MAX
> DD $ OOS, commit `5741202`), ITEM 1 (trailing break-even + tests, commit
> `59a869d`) e ITEM 2 (fees por-fill con spec corregida A/B/C; ver MEMORIA del
> día).
>
> **2026-08-22:** ejecutado el ITEM 4 (bug fees: cierre 100% vía parciales no
> pagaba el lado de entrada; detectado al cotejar el reporte de Sailor) —
> commit `cd455ae`, diseño de mínima superficie dirigido por el revisor. Este
> doc queda solo con el Backlog congelado.

---

## Backlog CONGELADO — detectado en auditoría, NO tocar por ahora

*Decisiones de Álvaro 2026-08-21: no se usan hoy / no duelen hoy. Se listan
para que no se pierdan; desbloquear solo con orden explícita.*

1. **Look-ahead en indicadores**: `Ret % PM` (PMH final desde las 04:00,
   `indicators.py:1573-1577`), `AM Open` (`:1306-1315`), `Pivot Points` en
   modo `gap_day` (fallback a rth_high/low finales de hoy, `:691-707`),
   `Day Open` (`:1107-1110`), `offset` negativo sin validar (`:849`).
   *Congelado: Álvaro no usa estos indicadores ahora.*
2. **Stop ATR Multiplier con ATR del día completo** (media incluye futuro,
   `strategy_engine.py:1284-1288` y `:716-724`). *Congelado por lo mismo.*
3. **Path paralelo/slab sin agrupar parciales** y sin campos
   prev_max/fade (`backtest_signals.py:839-879,1051` vs
   `backtest_service.py:771`). Tests ya rojos: `test_accum_fast_equivalence`,
   `test_n2a_e2e_equivalence` (×2). *Solo importa si se activan
   `BACKTEST_PARALLEL_WORKERS>1` / `BTT_SLAB_STREAM_ENABLED` en Linux.*
4. **Tests decaídos**: `test_candle_delay` (semántica pre-2026-08-17, cuando
   `look_ahead_prevention` pasó a default True — el motor es el coherente,
   actualizar el test), `test_backtest_engine` + `test_backtest_integration`
   (imports muertos), `test_backtest_golden` (solo servidor),
   `test_prefetch_parity` (migración local). *Arreglarlos la próxima vez que
   se toque el motor, no antes.*
