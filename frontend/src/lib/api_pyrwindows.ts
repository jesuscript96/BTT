// Estado de la FRANJA HORARIA PROPIA POR NIVEL DE PIRÁMIDE. La UI ofrece el
// campo SOLO si el backend dice enabled=true (PYRAMID_LEVEL_WINDOWS_ENABLED,
// default OFF): sin flag, el campo no aparece y el motor queda bit-idéntico.
import { API_BASE } from "./api";

let _estado: { enabled: boolean } | null = null;
let _cargando: Promise<void> | null = null;
const _suscriptores = new Set<() => void>();

function avisar() {
  _suscriptores.forEach((fn) => fn());
}

/** Suscribirse a cambios de estado (para re-render del campo). */
export function suscribirPyrWindows(fn: () => void): () => void {
  _suscriptores.add(fn);
  return () => _suscriptores.delete(fn);
}

/** Dispara la carga (una sola vez por sesión) y avisa a los suscriptores. */
export function cargarPyrWindows(): Promise<void> {
  if (!_cargando) {
    _cargando = fetch(`${API_BASE}/pyramid-level-windows`)
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
export function estadoPyrWindows() {
  return _estado;
}
