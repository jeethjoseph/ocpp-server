'use client'

// Client component to initialize New Relic Browser agent
// Must be a client component because it uses useEffect
// Uses dynamic import to prevent SSR issues with BrowserAgent

import { useEffect } from 'react'

export default function NewRelicInitializer() {
  useEffect(() => {
    // Dynamic import ensures BrowserAgent is only loaded on client-side
    import('@/lib/newrelic-browser').then(({ initNewRelic }) => {
      initNewRelic()
    }).catch((error) => {
      console.error('Failed to load New Relic Browser agent:', error)
    })
  }, [])

  // This component doesn't render anything
  return null
}
