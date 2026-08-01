"use client";

/**
 * Guarda de página del portal de API. La página es un Server Component (tiene
 * `metadata`), así que la comprobación de tier vive aquí.
 *
 * Sin esto, el sidebar escondía el enlace pero /developers se alcanzaba tecleando
 * la URL, y la consola muestra claves y facturación. El backend ya rechaza
 * (403) los /api/console/* sin `api.portal.access`; esto es lo que evita que el
 * usuario vea una consola rota en vez de un mensaje.
 */
import { ApiConsole } from "@/components/developers/ApiConsole";
import LockedFeature from "@/components/LockedFeature";
import { useEntitlements } from "@/lib/entitlements";

export default function ApiConsoleGuard() {
  const { can, loading } = useEntitlements();
  // `can()` es optimista mientras carga: sin esta guarda pintaríamos la consola
  // un instante y la cambiaríamos por LockedFeature al llegar el tier.
  if (loading) return null;
  if (!can("api.portal.access")) {
    return <LockedFeature feature="api.portal.access" requiredTier="Admin" />;
  }
  return <ApiConsole />;
}
