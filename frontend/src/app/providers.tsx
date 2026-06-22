'use client'

import posthog from 'posthog-js'
import { PostHogProvider } from 'posthog-js/react'
import { ReactNode } from 'react'

if (typeof window !== 'undefined') {
  const key = process.env.NEXT_PUBLIC_POSTHOG_KEY
  const host = process.env.NEXT_PUBLIC_POSTHOG_HOST || 'https://us.i.posthog.com'

  if (key && !key.startsWith('placeholder_')) {
    posthog.init(key, {
      api_host: host,
      capture_pageview: false, // Deshabilitar autoguardado de vistas para Next.js App Router (se gestiona en PostHogPageView)
      capture_pageleave: true,
    })
  } else {
    console.info('PostHog está cargado pero no inicializado (clave omitida o placeholder).')
  }
}

export function PHProvider({ children }: { children: ReactNode }) {
  return <PostHogProvider client={posthog}>{children}</PostHogProvider>
}
