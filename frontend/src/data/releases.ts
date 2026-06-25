/**
 * Release notes feed for the "What's new" popup.
 *
 * MAINTENANCE: each time you ship something, add ONE entry at the TOP of the
 * array. The popup shows the latest release once per user (tracked in Clerk
 * `unsafeMetadata.lastSeenReleaseId`) — it never shows again until you add a new
 * entry with a new `id`.
 */
export interface Release {
  id: string;            // unique & stable, e.g. "2026-06-23"
  date: string;          // human date, e.g. "23 jun 2026"
  title: string;         // headline, e.g. "Habéis pedido X, lo hemos hecho"
  items: string[];       // bullets describing what's new
  requestedByYou?: boolean; // show the "esto lo pedisteis vosotros" badge
}

export const RELEASES: Release[] = [
  {
    id: "2026-06-23",
    date: "23 jun 2026",
    title: "Novedades en Edgecute",
    items: [
      "Nuevo: vota qué construimos primero desde el botón “Feedback” de la barra lateral.",
      "Hemos mejorado el seguimiento de uso para priorizar mejor el roadmap.",
    ],
    requestedByYou: true,
  },
];

/** The release the popup compares against. RELEASES[0] must be the newest. */
export const LATEST_RELEASE: Release | undefined = RELEASES[0];
