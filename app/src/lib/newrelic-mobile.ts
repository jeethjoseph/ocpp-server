// lib/newrelic-mobile.ts
// New Relic Browser Agent for Capacitor mobile app
// Capacitor apps run web code in WebView, so we use the Browser agent (not native SDK)

import { BrowserAgent } from '@newrelic/browser-agent/loaders/browser-agent'

let browserAgent: BrowserAgent | null = null

/**
 * Initialize New Relic Browser agent for Capacitor mobile app
 * Enables distributed tracing to connect mobile app requests to backend traces
 */
export function initNewRelicMobile() {
  // Already initialized guard
  if (browserAgent) {
    console.log('New Relic Mobile: Already initialized')
    return
  }

  // Check if monitoring is enabled
  const licenseKey = import.meta.env.VITE_NEW_RELIC_BROWSER_LICENSE_KEY
  if (!licenseKey) {
    console.log('New Relic Mobile: Disabled (no license key)')
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
        applicationID: import.meta.env.VITE_NEW_RELIC_APPLICATION_ID,
        sa: 1,
      },
      loader_config: {
        accountID: import.meta.env.VITE_NEW_RELIC_ACCOUNT_ID,
        trustKey: import.meta.env.VITE_NEW_RELIC_TRUST_KEY,
        agentID: import.meta.env.VITE_NEW_RELIC_AGENT_ID,
        licenseKey: licenseKey,
        applicationID: import.meta.env.VITE_NEW_RELIC_APPLICATION_ID,
      },
    }

    browserAgent = new BrowserAgent(config)
    console.log('✅ New Relic Mobile agent initialized (Browser agent for Capacitor)')
    console.log('   Distributed Tracing: ENABLED')
    console.log('   Application ID:', import.meta.env.VITE_NEW_RELIC_APPLICATION_ID)
  } catch (error) {
    console.error('❌ Failed to initialize New Relic Mobile agent:', error)
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
 * @param eventName - Name of the event (e.g., "ChargingStarted", "ScanComplete")
 * @param attributes - Event attributes/metadata
 */
export function trackEvent(eventName: string, attributes?: Record<string, any>) {
  if (!browserAgent) return

  try {
    browserAgent.addPageAction(eventName, attributes)
    console.log(`📊 Tracked event: ${eventName}`, attributes)
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
    console.log(`👤 Set user context: ${userId}`)
  } catch (error) {
    console.error('Failed to set user context:', error)
  }
}

/**
 * Track charging session context
 *
 * @param chargerId - Charger ID
 * @param transactionId - Transaction ID (optional)
 */
export function setChargingContext(chargerId: string, transactionId?: string) {
  if (!browserAgent) return

  try {
    browserAgent.setCustomAttribute('chargerId', chargerId)
    if (transactionId) {
      browserAgent.setCustomAttribute('transactionId', transactionId)
    }
    console.log(`⚡ Set charging context: ${chargerId}`)
  } catch (error) {
    console.error('Failed to set charging context:', error)
  }
}
