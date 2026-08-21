# PRD 00 — Plan de subida a main (léeme primero)

> **Para:** Adri (Edgecute). **De:** Álvaro. **Fecha:** 2026-08-21.
> **Qué es esto:** el mapa de esta tanda — qué tiene que llegar a `main`, en
> qué orden, cómo verificar que nada se rompe y qué NO hacer. Los detalles
> finos están en el PRD_01 y el PRD_02; aquí solo el plan. Escrito para que
> pueda leerlo cualquiera, incluido Álvaro 😉

---

## 1. Resumen en palabras simples (qué llega a clientes hoy y está mal)

1. **Las comisiones se calculan mal (PRD_01, backend).** El motor trata cada
   trade como si fuera una única ejecución de tamaño irrelevante:
   - Modo **$**: cobra una cantidad **fija por trade** — da igual 10 acciones
     que 1.000. Un broker real cobra por acción ejecutada.
   - Modo **%**: cobra un porcentaje del **beneficio** — un trade que cierra
     a cero paga **cero comisión**, siendo que se ejecutaron entrada y salida.
   - Además un trade real son **varias ejecuciones** (entrada, N parciales,
     cierre) y cada una debe pagar su comisión.
2. **El calendario pinta un mundo que no es el real (PRD_02, frontend).**
   - Abre en "Profits" = beneficio **bruto** (con las comisiones devueltas):
     una estrategia **perdedora se ve ganadora** por defecto.
   - El PnL% del grid mensual dispara números imposibles (caso real: YTD
     +3133% con RETURN real +27.67%).
   - Las métricas en $ usan un capital desincronizado (default 10.000
     hardcodeado; al lanzar desde el builder no llegaban los parámetros
     tecleados).

## 2. Qué se pide exactamente

**Dos PRs a `develop`** (son independientes: PRs separados, cualquier orden):

| PR | Qué | Dónde |
|----|-----|-------|
| A | Implementar **PRD_02** (calendario/retorno real) | Solo frontend (TSX/TS) |
| B | Implementar **PRD_01** (comisiones por ejecución) | Motor Python + kernel Numba + 2 labels de UI |

Después, con los dos en `develop` y verificados: **subida a `main` en tu
cadencia normal**. La decisión y ejecución de `develop → main` es tuya, como
siempre — este documento no te la delega, solo te da el contexto.

## 3. Orden recomendado (sugerencia, no obligación)

1. **PRD_02 primero**: es 1–2 h de frontend, cero riesgo de motor, y el
   usuario deja de ver números mentirosos de inmediato.
2. **PRD_01 después**: toca el motor financiero, exige paridad Python↔JIT y
   tiene un cambio de significado (FLAT pasa de $/trade a **$/share**) que
   merece su nota de release.
3. Con ambos en `develop`, **un solo salto a `main`** con la nota de release
   del §6.

## 4. Cómo verificar que no se rompe nada (checklist antes de `main`)

**PRD_02 (frontend):**
- [ ] `tsc --noEmit` limpio.
- [ ] Los 6 escenarios manuales del PRD_02 §4 (perdedora neta en rojo, YTD%
      ≈ RETURN, DD$ coherente, parámetros tecleados llegan, recarga mantiene
      la base, Days únicos).
- No cambia ningún número que produzca el backend: es presentación.

**PRD_01 (motor):**
- [ ] Copiar `reference/test_fees.py` a `backend/tests/` → 6/6 verde (es la
      especificación ejecutable; primero se ve en rojo, así se comprueba que
      testea algo).
- [ ] `test_sim_jit_equivalence.py` completo sin regresiones.
- [ ] **Smoke de identidad**: mismo backtest con `fees = 0` antes y después
      del cambio → resultados **idénticos** (con fees=0 el modelo nuevo
      cobra 0, igual que el viejo). Con `fees > 0`, un trade simple sin
      parciales debe pagar exactamente `2 × fees × size`.
- [ ] `grep -rn "fees \* 2\|abs(gross_pnl)" backend/app/services/` → sin
      resultados en los puntos de fee.

**Global (en develop, antes del salto a main):**
- [ ] Un backtest end-to-end de humo (estrategia simple con parciales y
      fees > 0): corre, genera trades, calendario y curva coherentes.

## 5. Qué NO hacer (guardarraíles para no romper nada)

1. **No mergear ni cherry-pickear mis ramas** (`alvaro-rama-desarrollo`):
   llevan features sin decidir y cosas de mi montaje local. El cherry-pick
   del fix de fees sobre develop **conflictúa en `portfolio_sim.py`**
   (verificado): está construido sobre trailing/locates/parciales que
   develop no tiene. Por eso este canal es de PRDs.
2. **No `git apply` de los `reference/*.patch`**: son referencia de
   comportamiento exacto, no parches aplicables (sus contextos no existen en
   develop). Lo único copiable tal cual es `reference/test_fees.py`
   (archivo nuevo, sin dependencias).
3. **No cambiar schema de BD, ni la API, ni el significado de los campos**
   `fees` / `fee_type`: viajan igual que hoy.
4. **Preservar los quirks del PRD_01 §3.4**: los trades parciales sin clave
   `fees`, los locates intactos. Están verificados como comportamiento
   contractual del resto del sistema; tocarlos rompe consistencias asumidas.
5. **Paridad Python↔JIT bit-idéntica**: el helper nuevo debe hacer las
   operaciones en el mismo orden en los dos paths (regla del motor).

## 6. Nota de release sugerida (para clientes)

> **Backtester más honesto.** Hemos corregido el modelo de comisiones: ahora
> se cobran **por ejecución** (entrada, parciales y salida), como haría un
> broker real. El modo de comisión en $ pasa a significar **$ por acción y
> lado** (antes era una cantidad fija por trade, independiente del tamaño);
> los backtests guardados con comisión $ mostrarán números distintos — los
> nuevos son los correctos. Además, el calendario ahora abre mostrando el
> resultado **neto** (antes abría en bruto) y el % mensual se calcula sobre
> la equity real de cada periodo.

## 7. FAQ

- **¿Cambian los backtests guardados?** PRD_02 no toca números. PRD_01: en
  PERCENT apenas (ahora los trades planos y parciales pagan lo que deben); en
  FLAT cambia el significado ($/trade → $/share) y los números cambian — de
  ahí el relabel de UI y la nota de release.
- **¿Pueden subir a main por separado?** Sí, son independientes.
- **¿Riesgo de romper producción?** PRD_02 es solo presentación. PRD_01 toca
  el motor pero está acotado a los puntos de fee, con tests de aceptación
  incluidos y la checklist del §4.
- **¿Dónde pregunto?** A Álvaro directamente. Cada PRD es autocontenido; si
  algo no cuadra con la spec, parar y preguntar antes de improvisar.
