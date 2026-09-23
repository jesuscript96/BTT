import { IndicatorType } from "@/types/strategy";

/**
 * Nombres de indicador que el MOTOR acepta pero el constructor no conoce.
 *
 * El backend tiene una tabla de alias (indicators.py, `_UI_TO_INTERNAL` y los
 * nombres internos en crudo): «Close» es «Bar Close», «Último pivote» con
 * acento es «Ultimo pivote», «Pre-Market High» es «PM High»… Un JSON escrito a
 * mano o generado fuera del constructor (las estrategias compartidas de Álvaro,
 * el genético) llega con esos nombres, el backtest los corre bien, y el
 * constructor los enseña como texto suelto: sin icono de ayuda, sin
 * parámetros (la ventana y la dirección del pivote no salen) y, al editar la
 * condición, el destino se cae a «Fixed Value» porque el nombre no está en la
 * lista de destinos permitidos. Jaume lo vio el 18-sep con la «1B Modelización
 * Sobri 3» de Álvaro: «Último pivote > Último pivote» sin saber cuál era alto y
 * cuál bajo.
 *
 * Se normaliza al CARGAR la definición en el constructor; al guardar ya salen
 * los nombres canónicos.
 */
const ALIAS: Record<string, IndicatorType> = {
    "Close": IndicatorType.BAR_CLOSE,
    "Open": IndicatorType.BAR_OPEN,
    "High": IndicatorType.HIGH_BAR,
    "Low": IndicatorType.LOW_BAR,
    "Pre-Market High": IndicatorType.PM_HIGH,
    "Pre-Market Low": IndicatorType.PM_LOW,
    "Prev. Close Bar": IndicatorType.PREV_BAR_CLOSE,
    "Prev. Open Bar": IndicatorType.PREV_BAR_OPEN,
    "Prev. High Bar": IndicatorType.PREV_BAR_HIGH,
    "Prev. Low Bar": IndicatorType.PREV_BAR_LOW,
    "Último pivote": IndicatorType.LAST_PIVOT,
    "Overhead": IndicatorType.OVERHEAD_X_DAYS,
    "Elapsed Time from Last High": IndicatorType.ELAPSED_TIME_LAST_HIGH,
    "Darvas": IndicatorType.DARVAS_BOX,
    "Caja Darvas": IndicatorType.DARVAS_BOX,
};

const CANONICOS = new Set<string>(Object.values(IndicatorType));

/** El nombre canónico del constructor para un nombre que venga de fuera; el
 *  mismo nombre si ya es canónico o no se reconoce. */
export function nombreCanonico(nombre: string): string {
    if (CANONICOS.has(nombre)) return nombre;
    return ALIAS[nombre] ?? nombre;
}

/** Recorre una definición entera (entrada, salida, pirámides, pasos del
 *  camino…) y pone el nombre canónico en cada lado de cada condición. Devuelve
 *  una copia; no toca nada más. */
export function normalizaNombresIndicadores<T>(def: T): T {
    // Solo los LADOS de una condición (source / target / level): el resto de
    // `name` de una definición (el nombre de la estrategia, features de un
    // modelo…) no se toca.
    const LADOS = new Set(["source", "target", "level"]);
    const visita = (x: unknown): unknown => {
        if (Array.isArray(x)) return x.map(visita);
        if (x && typeof x === "object") {
            const o = x as Record<string, unknown>;
            const salida: Record<string, unknown> = {};
            for (const [k, v] of Object.entries(o)) {
                if (LADOS.has(k) && v && typeof v === "object" && !Array.isArray(v) && typeof (v as Record<string, unknown>).name === "string") {
                    const lado = visita(v) as Record<string, unknown>;
                    lado.name = nombreCanonico(lado.name as string);
                    salida[k] = lado;
                } else {
                    salida[k] = visita(v);
                }
            }
            return salida;
        }
        return x;
    };
    return visita(def) as T;
}
