// lib/newrelic-browser.ts
// New Relic Browser Agent for distributed tracing from frontend to backend

import { BrowserAgent } from '@newrelic/browser-agent/loaders/browser-agent'

let browserAgent: BrowserAgent | null = null

/**
 * Initialize New Relic Browser agent for frontend monitoring
 * Enables distributed tracing to connect frontend requests to backend traces
 *
 * Note: This module should only be imported client-side. The parent component
 * should be loaded with next/dynamic and { ssr: false } to prevent SSR issues.
 */
export function initNewRelic() {
  // Server-side guard
  if (typeof window === 'undefined') {
    console.log('New Relic Browser: Skipping initialization (server-side)')
    return
  }

  // Already initialized guard
  if (browserAgent) {
    console.log('New Relic Browser: Already initialized')
    return
  }

  // Check if monitoring is enabled - all required env vars must be present
  const licenseKey = process.env.NEXT_PUBLIC_NEW_RELIC_BROWSER_LICENSE_KEY
  const applicationID = process.env.NEXT_PUBLIC_NEW_RELIC_APPLICATION_ID
  const accountID = process.env.NEXT_PUBLIC_NEW_RELIC_ACCOUNT_ID
  const trustKey = process.env.NEXT_PUBLIC_NEW_RELIC_TRUST_KEY
  const agentID = process.env.NEXT_PUBLIC_NEW_RELIC_AGENT_ID

  if (!licenseKey || !applicationID || !accountID || !trustKey || !agentID) {
    console.log('New Relic Browser: Disabled (missing required configuration)')
    return
  }

  try {
    const config = {
      init: {
        distributed_tracing: { enabled: true }, // ⭐ Critical for end-to-end tracing
        privacy: { cookies_enabled: true },
        ajax: { deny_list: [] }, // Track all AJAX requests
      },
      info: {
        beacon: 'bam.nr-data.net',
        errorBeacon: 'bam.nr-data.net',
        licenseKey: licenseKey,
        applicationID: applicationID,
        sa: 1,
      },
      loader_config: {
        accountID: accountID,
        trustKey: trustKey,
        agentID: agentID,
        licenseKey: licenseKey,
        applicationID: applicationID,
      },
    }

    browserAgent = new BrowserAgent(config)
    console.log('✅ New Relic Browser agent initialized')
    console.log('   Distributed Tracing: ENABLED')
    console.log('   Application ID:', process.env.NEXT_PUBLIC_NEW_RELIC_APPLICATION_ID)
  } catch (error) {
    console.error('❌ Failed to initialize New Relic Browser agent:', error)
  }
}

/**
 * Get the browser agent instance
 * Used to manually track events or add custom attributes
 */
export function getBrowserAgent() {
  return browserAgent
}

/**
 * Track a custom event in New Relic
 *
 * @param eventName - Name of the event (e.g., "ChargingStarted")
 * @param attributes - Event attributes/metadata
 */
export function trackEvent(eventName: string, attributes?: Record<string, string | number | boolean>) {
  if (!browserAgent) return

  try {
    browserAgent.addPageAction(eventName, attributes)
  } catch (error) {
    console.error('Failed to track event:', error)
  }
}

/**
 * Set user context for tracking
 *
 * @param userId - User ID
 * @param email - User email (optional)
 */
export function setUserContext(userId: string, email?: string) {
  if (!browserAgent) return

  try {
    browserAgent.setCustomAttribute('userId', userId)
    if (email) {
      browserAgent.setCustomAttribute('userEmail', email)
    }
  } catch (error) {
    console.error('Failed to set user context:', error)
  }
}
