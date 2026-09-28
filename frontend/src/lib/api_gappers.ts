// Estado del indicador «Gappers activos (+X %)» (7.2b). La UI lo ofrece SOLO
// si el backend dice enabled=true (GAPPERS_ACTIVE_ENABLED, default OFF): sin
// flag, el indicador no aparece y el motor queda igual que hoy.
import { API_BASE } from "./api";

let _estado: { enabled: boolean; levels: number[]; table_ok: boolean } | null = null;
let _cargando: Promise<void> | null = null;
const _suscriptores = new Set<() => void>();

function avisar() {
  _suscriptores.forEach((fn) => fn());
}

/** Suscribirse a cambios de estado (para re-render del selector). */
export function suscribirGappers(fn: () => void): () => void {
  _suscriptores.add(fn);
  return () => _suscriptores.delete(fn);
}

/** Dispara la carga (una sola vez por sesión) y avisa a los suscriptores. */
export function cargarGappersActive(): Promise<void> {
  if (!_cargando) {
    _cargando = fetch(`${API_BASE}/gappers-active`)
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        _estado = d && typeof d === "object"
          ? { enabled: !!d.enabled, levels: Array.isArray(d.levels) ? d.levels : [], table_ok: !!d.table_ok }
          : { enabled: false, levels: [], table_ok: false };
      })
      .catch(() => {
        _estado = { enabled: false, levels: [], table_ok: false };
      })
      .finally(avisar);
  }
  return _cargando;
}

/** El último estado conocido (null = todavía sin responder). */
export function estadoGappersActive() {
  return _estado;
}
