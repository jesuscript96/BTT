// Estado de la SALIDA PROGRAMADA CONDICIONAL. La UI ofrece la sección SOLO
// si el backend dice enabled=true (SCHEDULED_EXITS_ENABLED, default OFF):
// sin flag, la sección no aparece y el motor queda bit-idéntico a hoy.
import { API_BASE } from "./api";

let _estado: { enabled: boolean } | null = null;
let _cargando: Promise<void> | null = null;
const _suscriptores = new Set<() => void>();

function avisar() {
  _suscriptores.forEach((fn) => fn());
}

/** Suscribirse a cambios de estado (para re-render de la sección). */
export function suscribirSchedExits(fn: () => void): () => void {
  _suscriptores.add(fn);
  return () => _suscriptores.delete(fn);
}

/** Dispara la carga (una sola vez por sesión) y avisa a los suscriptores. */
export function cargarSchedExits(): Promise<void> {
  if (!_cargando) {
    _cargando = fetch(`${API_BASE}/scheduled-exits`)
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        _estado = d && typeof d === "object" ? { enabled: !!d.enabled } : { enabled: false };
      })
      .catch(() => {
        _estado = { enabled: false };
      })
      .finally(avisar);
  }
  return _cargando;
}

/** El último estado conocido (null = todavía sin responder). */
export function estadoSchedExits() {
  return _estado;
}
