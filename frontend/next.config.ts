import type { NextConfig } from "next";
import path from "path";

const nextConfig: NextConfig = {
  // Root inference fix: without this, Next/Tailwind resolve packages from the
  // GIT root (edgecute_app/) instead of frontend/ — "Can't resolve 'tailwindcss'"
  // retried in an infinite compile loop that pegs CPU/RAM.
  outputFileTracingRoot: path.resolve(__dirname),
  turbopack: {
    root: path.resolve(__dirname),
  },
  // Reverse-proxy PostHog through our own domain (/ingest) so ad-blockers don't
  // drop analytics. Paired with api_host: '/ingest' in providers.tsx.
  skipTrailingSlashRedirect: true,
  async rewrites() {
    return [
      { source: "/ingest/static/:path*", destination: "https://us-assets.i.posthog.com/static/:path*" },
      { source: "/ingest/:path*", destination: "https://us.i.posthog.com/:path*" },
    ];
  },
};

export default nextConfig;

