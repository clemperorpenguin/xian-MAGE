/*
 * Tests for the compose trigger state machine.
 *
 * Browser-free core test.
 */

import { describe, it, expect } from 'vitest';
import { composeTrigger, INITIAL_STATE, DEFAULT_COMPOSE_CONFIG } from '../../src/core/compose/state';

describe('composeTrigger', () => {
  it('should fire on three consecutive spaces within the window', () => {
    let state = INITIAL_STATE;
    const T0 = 1000;

    // First space
    const r1 = composeTrigger(state, ' ', T0);
    expect(r1.fired).toBe(false);
    state = r1.state;
    expect(state.count).toBe(1);

    // Second space
    const r2 = composeTrigger(state, ' ', T0 + 100);
    expect(r2.fired).toBe(false);
    state = r2.state;
    expect(state.count).toBe(2);

    // Third space — fire
    const r3 = composeTrigger(state, ' ', T0 + 200);
    expect(r3.fired).toBe(true);
    expect(r3.state).toBe(INITIAL_STATE); // reset after fire
  });

  it('should reset on any non-Space key', () => {
    let state = composeTrigger(INITIAL_STATE, ' ', 1000).state;
    expect(state.count).toBe(1);

    const result = composeTrigger(state, 'a', 1100);
    expect(result.fired).toBe(false);
    expect(result.state).toBe(INITIAL_STATE);
  });

  it('should reset the window if it expires between spaces', () => {
    let state = composeTrigger(INITIAL_STATE, ' ', 1000).state;
    expect(state.count).toBe(1);

    // Wait beyond windowMs
    const result = composeTrigger(state, ' ', 2000); // 1000ms gap > 900ms window
    expect(result.fired).toBe(false);
    expect(result.state.count).toBe(1); // restarted as first of new window
    expect(result.state.windowStart).toBe(2000);
  });

  it('should not fire when trigger is off', () => {
    const result = composeTrigger(INITIAL_STATE, ' ', 1000, { ...DEFAULT_COMPOSE_CONFIG, trigger: 'off' });
    expect(result.fired).toBe(false);
    expect(result.state).toBe(INITIAL_STATE);
  });

  it('should not fire with fewer than three spaces', () => {
    let state = composeTrigger(INITIAL_STATE, ' ', 1000).state;
    state = composeTrigger(state, ' ', 1050).state;
    expect(state.count).toBe(2);
    // Never fired — no third space
  });
});
