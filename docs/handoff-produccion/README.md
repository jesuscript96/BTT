# Handoff a producción — canal permanente Álvaro → Edgecute

> **Para:** Edgecute (Adrian). **De:** Álvaro.
> **Rama:** `alvaro/handoff-produccion` — **canal permanente** de entrega de
> mejoras validadas en mi entorno que quiero que lleguen a clientes.
> **Contenido:** solo documentación (PRDs listos para ejecutar + referencias).
> **No contiene código de implementación** ni nada de mi montaje local.
>
> **Flujo:** implementáis cada PRD sobre `develop` con vuestros PRs normales;
> el salto `develop → main` sigue siendo de Adrian, como siempre.

---

## Modelo de uso (esta rama vive largo plazo)

- **Cada tanda de mejoras = una carpeta fechada** `AAAA-MM-DD-<tema>/` con sus
  PRDs (autocontenidos: problema, evidencia, anclas al código de `develop`,
  spec, plan atómico, tests, DoD) y su `reference/`.
- **Este README es el índice vivo**: estado de cada tanda y de cada PRD.
- La rama se mantiene sobre `develop`; si `develop` avanza mucho, la
  sincronizo yo desde mi lado (es docs, conflicto improbable). Vosotros no
  necesitáis mergear esta rama: **leedla e implementad**. Si preferís dejar
  trazabilidad, podéis mergearla como PR de docs cuando una tanda termine.
- En `reference/` puede haber **parches de mi implementación**: son
  referencia de comportamiento exacto, **no apliquéis con `git apply`** (mi
  rama lleva cambios previos que hacen que no apliquen limpio — cada PRD lo
  detalla). Los archivos **nuevos** (p.ej. tests) sí son copiables tal cual;
  cada PRD lo indica expresamente.

## Tanda actual

### [`2026-08-21-fees-y-calendario/`](2026-08-21-fees-y-calendario/) — base `develop` @ `e368839`

| PRD | Tipo | Estado | Nota |
|-----|------|--------|------|
| [`PRD_01_fees_por_ejecucion.md`](2026-08-21-fees-y-calendario/PRD_01_fees_por_ejecucion.md) | 🐛 fix motor (backend) | **Pendiente de implementar** | Alta: comisiones incorrectas hoy con `fees > 0`. ⚠️ BREAKING en FLAT (relabel UI obligatorio). Incluye `reference/test_fees.py` copiable tal cual (spec ejecutable). |
| [`PRD_02_calendario_retorno_real.md`](2026-08-21-fees-y-calendario/PRD_02_calendario_retorno_real.md) | 🐛 fix presentación (frontend) | **Pendiente de implementar** | Alta: el calendario abre en beneficio bruto; una perdedora neta se ve ganadora. Solo TSX, sin tocar motor. |

Ambas son **independientes** (PRs separados, cualquier orden).

## Qué NO va en este canal (a propósito)

Nada de mi montaje local puede colar: migración GCS → lago local (rutas de mi
máquina), qualifying bygap (perf opt-in por `.env`), mi kanban personal
(`MEMORIA.md`, `PROXIMOS_ITEMS.md`), o features sin decisión (métricas
`sl_dist_pct_*`, trailing break-even desacoplado, parciales fade, chart,
export CSV).

### Candidatos para próximas tandas (si os interesan, pedidlos)

1. **Fix reparto de locates** (commits `2a51b94`+`8896ece`+`de14125` en mi
   rama): el locate diario se imputa entero al primer short → falsea win rate
   y R por trade. Bug de motor real, PRD ejecutable en mi rama
   (`docs/fix-locates-attribution/PRD.md`).
2. **Fix MAX DD $ del tab OOS** (commit `5741202`): el patrón running-peak
   de la T3 del PRD_02 aplicado al tab OOS.

## Verificación rápida de mi entorno de referencia

- Los commits de referencia viven en `origin/alvaro-rama-desarrollo`
  (fees: `77236d2`). Para inspeccionarlos:
  ```bash
  git remote set-branches --add origin alvaro-rama-desarrollo
  git fetch origin alvaro-rama-desarrollo
  git show 77236d2 --stat
  ```
- Las anclas de cada PRD están **verificadas contra `develop` @ `e368839`**.
  Si `develop` avanzó, re-localizad por expresión (`fees * 2`,
  `abs(gross_pnl) * fees`, `useState<...>("profits")`,
  `reduce((acc, r) => acc * (1 + r / 100)`, `(p.value / 100) * initCash`),
  no por número de línea.
