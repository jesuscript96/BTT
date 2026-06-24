import posthog from 'posthog-js'

/**
 * Single source of truth for the analytics event taxonomy.
 *
 * Add new submodule interactions here and call `track(EVENTS.X)` at the action
 * site. Keeping every event name in one place makes the taxonomy auditable and
 * easy to evolve without grepping the whole codebase.
 */
export const EVENTS = {
  BACKTEST_RUN: 'backtest_run',
  STRATEGY_CREATED: 'strategy_created',
  STRATEGY_SEARCH_RUN: 'strategy_search_run',
  DATASET_CREATED: 'dataset_created',
  SCREENER_FILTER_APPLIED: 'screener_filter_applied',
  TICKER_ANALYSIS_OPENED: 'ticker_analysis_opened',
  API_KEY_CREATED: 'api_key_created',
  ASSISTANT_MESSAGE_SENT: 'assistant_message_sent',
  FEEDBACK_SUBMITTED: 'feedback_submitted',
  ROADMAP_VOTED: 'roadmap_voted',
  WHATSNEW_VIEWED: 'whatsnew_viewed',
} as const

export type EventName = (typeof EVENTS)[keyof typeof EVENTS]

/** Capture a named event. No-op on the server. */
export function track(event: EventName | string, props?: Record<string, unknown>): void {
  if (typeof window === 'undefined') return
  try {
    posthog.capture(event, props)
  } catch {
    // analytics must never break the app
  }
}
