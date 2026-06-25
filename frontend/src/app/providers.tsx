'use client'

import posthog from 'posthog-js'
import { PostHogProvider } from 'posthog-js/react'
import { ReactNode } from 'react'

if (typeof window !== 'undefined') {
  const key = process.env.NEXT_PUBLIC_POSTHOG_KEY

  if (key && !key.startsWith('placeholder_')) {
    posthog.init(key, {
      // Ingest through our own domain (see rewrites in next.config.ts) so
      // ad-blockers don't drop events.
      api_host: '/ingest',
      ui_host: 'https://us.posthog.com',
      capture_pageview: false, // App Router: las vistas se gestionan en PostHogPageView
      capture_pageleave: true,
      // Solo crear perfiles de personas para usuarios identificados (no infla MAU
      // con anónimos). La identificación la hace PostHogIdentify con el user de Clerk.
      person_profiles: 'identified_only',
    })
  } else {
    console.info('PostHog está cargado pero no inicializado (clave omitida o placeholder).')
  }
}

export function PHProvider({ children }: { children: ReactNode }) {
  return <PostHogProvider client={posthog}>{children}</PostHogProvider>
}
