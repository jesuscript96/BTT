"use client";

/**
 * Lectura del token de sesión de Clerk, esperando a que Clerk termine de cargar.
 *
 * Antes leíamos `window.Clerk.session` directamente. Si la primera petición salía
 * antes de que Clerk.js hidratase, `session` era undefined, la petición iba SIN
 * cabecera Authorization, el backend respondía 401 y el interceptor de 401 hacía
 * `window.location.href = "/sign-in"` — se pintaba el login un instante y, cuando
 * Clerk acababa de cargar y veía la sesión, devolvía al usuario al dashboard.
 *
 * `Clerk.loaded` es true cuando el bootstrap de `Clerk.load()` ha terminado, así
 * que basta con esperarlo antes de pedir el token.
 *
 * Vive en su propio módulo (y no en api.ts) porque lo usan tanto api.ts como
 * api_backtester.ts, y api.ts ya importa de api_backtester.ts — compartirlo desde
 * cualquiera de los dos crearía un import circular.
 */

type ClerkGlobal = {
  loaded?: boolean;
  status?: "degraded" | "error" | "loading" | "ready";
  session?: { getToken: () => Promise<string | null> } | null;
};

const CLERK_READY_TIMEOUT_MS = 10_000;
const POLL_INTERVAL_MS = 50;

function clerkGlobal(): ClerkGlobal | undefined {
  if (typeof window === "undefined") return undefined;
  return (window as unknown as { Clerk?: ClerkGlobal }).Clerk;
}

/**
 * Espera a que Clerk esté cargado. Devuelve la instancia (o null) sin lanzar:
 * si Clerk nunca carga, tras el timeout seguimos adelante sin token y la petición
 * fallará con un 401 legítimo en vez de colgarse.
 */
export async function waitForClerk(
  timeoutMs = CLERK_READY_TIMEOUT_MS,
): Promise<ClerkGlobal | null> {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    const clerk = clerkGlobal();
    // `status === "error"` = Clerk no va a cargar nunca; no tiene sentido esperar.
    if (clerk?.loaded || clerk?.status === "error") return clerk;
    if (Date.now() >= deadline) return clerk ?? null;
    await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL_MS));
  }
}

export async function getClerkToken(): Promise<string | null> {
  if (typeof window === "undefined") return null;
  try {
    const clerk = await waitForClerk();
    const token = await clerk?.session?.getToken?.();
    return token ?? null;
  } catch {
    return null;
  }
}
