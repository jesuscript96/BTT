'use client'

import { usePathname, useSearchParams } from 'next/navigation'
import { useEffect } from 'react'
import { usePostHog } from 'posthog-js/react'

export default function PostHogPageView() {
  const pathname = usePathname()
  const searchParams = useSearchParams()
  const posthog = usePostHog()

  useEffect(() => {
    // Captura vistas de página manualmente solo si PostHog está inicializado correctamente
    if (pathname && posthog && typeof window !== 'undefined') {
      // Verificar si posthog está inicializado antes de registrar la vista
      const isInitialized = !!posthog.get_property('$device_id')
      if (isInitialized) {
        let url = window.origin + pathname
        if (searchParams && searchParams.toString()) {
          url = url + `?${searchParams.toString()}`
        }

        posthog.capture('$pageview', {
          $current_url: url,
        })
      }
    }
  }, [pathname, searchParams, posthog])

  return null
}
