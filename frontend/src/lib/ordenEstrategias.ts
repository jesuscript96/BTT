// Orden manual de las estrategias en las listas (Baul, Portfolio «En crudo»,
// Robustez): el usuario las sube o baja con dos botones y el orden se
// recuerda en el navegador (localStorage). Es UN orden para todas las listas:
// una estrategia que subes en el baul sube tambien en las demas. Las que no
// esten en el orden guardado (nuevas) van detras, en el orden en que llegan.
//
// Vive en el navegador y no en la base porque es una comodidad de lectura de
// una sola persona en una sola maquina; no cambia nada de lo que hace el bot.

const CLAVE = "btt.orden_estrategias";

export function leerOrden(): string[] {
  try {
    const raw = window.localStorage.getItem(CLAVE);
    const v = raw ? JSON.parse(raw) : [];
    return Array.isArray(v) ? v.filter((x) => typeof x === "string") : [];
  } catch {
    return [];
  }
}

export function guardarOrden(ids: string[]): void {
  try {
    window.localStorage.setItem(CLAVE, JSON.stringify(ids));
  } catch {
    // sin almacenamiento (ventana privada, etc.): el orden dura la sesion
  }
}

/** Aplica el orden guardado a una lista: primero las conocidas, en su orden;
 *  despues las nuevas, tal como vienen. */
export function aplicarOrden<T extends { id: string }>(items: T[], orden: string[]): T[] {
  if (!orden.length) return items;
  const pos = new Map(orden.map((id, i) => [id, i] as [string, number]));
  const conocidas = items.filter((x) => pos.has(x.id)).sort((a, b) => pos.get(a.id)! - pos.get(b.id)!);
  const nuevas = items.filter((x) => !pos.has(x.id));
  return [...conocidas, ...nuevas];
}

/** Sube (-1) o baja (+1) `id` UNA posicion dentro de la lista visible
 *  `visibles` (los ids tal como se ven en ese cuadro, ya ordenados), y
 *  devuelve el orden completo nuevo: se intercambia con su vecino visible en
 *  el orden global, asi que mover en un cuadro que es un subconjunto (el
 *  Portfolio del baul) no descoloca las que no se ven. */
export function moverEnOrden(ordenCompleto: string[], visibles: string[], id: string, dir: -1 | 1): string[] | null {
  const k = visibles.indexOf(id);
  const vecino = visibles[k + dir];
  if (k < 0 || !vecino) return null;
  const orden = [...ordenCompleto];
  const a = orden.indexOf(id);
  const b = orden.indexOf(vecino);
  if (a < 0 || b < 0) return null;
  orden[a] = vecino;
  orden[b] = id;
  return orden;
}
