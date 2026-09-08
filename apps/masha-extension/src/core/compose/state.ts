/*
 * M2 — Compose trigger state machine.
 *
 * Browser-free core. No DOM, no platform API.
 *
 * The trigger: three Space presses within `windowMs` with no other key
 * between them.  Resets on any non-Space key, timeout, or successful fire.
 */

export interface ComposeState {
  /** Monotonic timestamp of the most recent Space press (0 if none). */
  lastSpaceAt: number;
  /** Number of consecutive Space presses within the window. */
  count: number;
  /** The window start timestamp (0 if no window is open). */
  windowStart: number;
}

export interface ComposeTriggerConfig {
  windowMs: number;      // 900 — max gap between first and third space
  trigger: 'triple-space' | 'off';
}

export const DEFAULT_COMPOSE_CONFIG: ComposeTriggerConfig = {
  windowMs: 900,
  trigger: 'triple-space',
};

export const INITIAL_STATE: ComposeState = {
  lastSpaceAt: 0,
  count: 0,
  windowStart: 0,
};

/**
 * Advance the state machine on a keydown event.
 *
 * Returns `{ fired: true, elapsed }` when three spaces have landed within the
 * window; `{ fired: false, state: … }` with the new state otherwise.
 */
export function composeTrigger(
  state: ComposeState,
  key: string,
  now: number,
  config: ComposeTriggerConfig = DEFAULT_COMPOSE_CONFIG,
): { fired: boolean; state: ComposeState; elapsed?: number } {
  if (config.trigger === 'off') {
    return { fired: false, state: INITIAL_STATE };
  }

  // Any non-Space key resets immediately
  if (key !== ' ') {
    return { fired: false, state: INITIAL_STATE };
  }

  // First space — open a window
  if (state.count === 0) {
    const next: ComposeState = {
      lastSpaceAt: now,
      count: 1,
      windowStart: now,
    };
    return { fired: false, state: next };
  }

  // Subsequent space — check if within the window
  const elapsed = now - state.windowStart;

  if (elapsed > config.windowMs) {
    // Window expired — reset and count this as the first of a new window
    const next: ComposeState = {
      lastSpaceAt: now,
      count: 1,
      windowStart: now,
    };
    return { fired: false, state: next };
  }

  const newCount = state.count + 1;
  if (newCount >= 3) {
    // FIRE!
    return {
      fired: true,
      state: INITIAL_STATE,
      elapsed: now - state.windowStart,
    };
  }

  // Count 2 — still waiting for the third
  return {
    fired: false,
    state: {
      lastSpaceAt: now,
      count: newCount,
      windowStart: state.windowStart,
    },
  };
}
