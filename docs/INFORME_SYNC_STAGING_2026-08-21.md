# Informe — Sync con staging (2026-08-21, noche)

> **Para:** revisión por IA / cualquier desarrollador.
> **De:** sesión Álvaro × Claude. **Rama:** `alvaro-rama-desarrollo`.
> **Objetivo del informe:** poder auditar qué se hizo, con qué evidencia y
> qué queda pendiente, sin leer toda la MEMORIA.

---

## 1. Contexto

- `origin/staging` tenía **6 commits** que `alvaro-rama-desarrollo` no tenía;
  la rama de Álvaro tenía **28** que staging no tenía. Merge-base: `20a8372`.
- Los 6 de staging: módulo de robustez de Sailor (`2378237`, 30 ficheros
  nuevos, +9.953 líneas), su aplicación del fix de locates
  (`5019a4c`+`1c34580`+`5687be5`), copia del PRD de locates (`143a7cb`) y
  carpeta `ALVARO_CAMBIOS/` con documentación de Álvaro (`d423046`).

## 2. Acciones ejecutadas

1. **Dry-run del merge** en worktree desechable → **0 conflictos**.
2. **Merge real `38298f1`** (origin/staging → alvaro-rama-desarrollo).
   - Incidencia resuelta: los renames STAGED del WIP (backend/scripts →
     `backend/_archive/scripts_gcs_2026-08/`) bloqueaban el merge por estado
     de índice (no de contenido). Solución: `git restore --staged` de esos
     paths → merge → re-stage idéntico. **Verificado: 12 entradas A/R
     intactas, el disco no se tocó, ningún WIP entró en el merge.**
3. Verificaciones post-merge (§3).
4. MEMORIA actualizada con inventario priorizado de los 28 commits.

## 3. Evidencias de verificación

| Comprobación | Resultado |
|---|---|
| Conflicto de merge | **0** (auto-merge de `portfolio_sim.py` y `sim_dispatch.py`) |
| Fix de locates: ¿el de Sailor difiere del nuestro? | **No** — el merge dejó nuestros 4 ficheros (`portfolio_sim.py`, `sim_dispatch.py`, `test_locates.py`, PRD) **byte a byte idénticos** (diff `1a04176..38298f1` vacío en esos paths) |
| `pytest tests/test_locates.py tests/test_sim_jit_equivalence.py` | **12/12 passed** (venv backend) |
| `tsc --noEmit` (frontend, robustez incluido) | **0 errores** |
| Neto del merge | 33 ficheros, +10.280 líneas (todo de staging, nada del WIP local) |

## 4. Estado y pendiente

- ✅ Merge commiteado y verificado en `alvaro-rama-desarrollo`.
- ⏳ Push de la rama (merge + docs) — inmediato tras este informe.
- ⏳ **Merge `alvaro-rama-desarrollo` → `staging`** (Sailor recibiría los 28
  commits): **pendiente OK explícito de Álvaro**. Ejecución por worktree
  (el working tree principal lleva WIP GCS sin commitear que no debe
  mezclarse). El orden/prioridad de esos commits está inventariado en
  `docs/MEMORIA.md` (entrada "Sync con staging": 🔴 Urgente-bug / 🟡 Feature
  validada / 🟢 Infra / 📄 Docs).
- Nota: la carpeta `ALVARO_CAMBIOS/` (copia de docs que hizo Sailor) queda
  duplicada intencionadamente con `docs/MEMORIA.md` (el original vivo).

## 5. Prueba runtime (hecha el misma noche — ver MEMORIA "noche 2" y "noche 5")

- Módulo de robustez probado en navegador con backend del merge: **funciona**
  (lista estrategias reales, auto-análisis, 11 endpoints 200, recalcula al
  cambiar estrategia).
- ~~Bug de selección por clic~~ — **RETRACTADO** (MEMORIA "noche 5"): era un
  artefacto del input automatizado del navegador de pruebas (desfase/ clicks
  contaminados), no un bug de la página. Código revisado y correcto; con
  ratón real y con teclado funciona bien. Nada que arreglar.
