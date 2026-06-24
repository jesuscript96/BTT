'use client'

import { useEffect } from 'react'
import { useUser } from '@clerk/nextjs'
import { usePostHog } from 'posthog-js/react'

/**
 * Links PostHog events to the signed-in Clerk user.
 *
 * Without this, every event is anonymous (device_id only) and you cannot answer
 * "how does a given user use the app" or segment by tier. On sign-out we reset
 * so the next user on the same device is not merged into the previous identity.
 */
export default function PostHogIdentify() {
  const { user, isLoaded } = useUser()
  const posthog = usePostHog()

  useEffect(() => {
    if (!isLoaded || !posthog) return

    if (user) {
      posthog.identify(user.id, {
        email: user.primaryEmailAddress?.emailAddress,
        name: user.fullName,
        tier: (user.publicMetadata?.tier as string) ?? 'Free',
        created_at: user.createdAt,
      })
    } else {
      posthog.reset()
    }
  }, [isLoaded, user, posthog])

  return null
}
