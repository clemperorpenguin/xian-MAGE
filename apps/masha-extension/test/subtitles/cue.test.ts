/*
 * Tests for subtitle cue processing.
 *
 * Browser-free core test.
 */

import { describe, it, expect } from 'vitest';
import { shouldTranslateCue, mergeCues, lookaheadWindow, Cue, DEFAULT_SUBTITLE_POLICY } from '../../src/core/subtitles/cue';

describe('shouldTranslateCue', () => {
  it('should skip short cues', () => {
    expect(shouldTranslateCue('OK')).toBe(false);
    expect(shouldTranslateCue('Hi')).toBe(false);
  });

  it('should skip music indicators', () => {
    expect(shouldTranslateCue('[Music]')).toBe(false);
    expect(shouldTranslateCue('♪')).toBe(false);
    expect(shouldTranslateCue('♫')).toBe(false);
  });

  it('should skip applause indicators', () => {
    expect(shouldTranslateCue('[Applause]')).toBe(false);
  });

  it('should accept dialogue cues', () => {
    expect(shouldTranslateCue('Hello, how are you?')).toBe(true);
    expect(shouldTranslateCue('I am fine, thank you.')).toBe(true);
  });
});

describe('mergeCues', () => {
  it('should merge cues with small gaps and no terminal punctuation', () => {
    const cues: Cue[] = [
      { id: '1', text: 'Hello, how are', startMs: 1000, endMs: 3000 },
      { id: '2', text: 'you today?', startMs: 3050, endMs: 5000 },
    ];

    const merged = mergeCues(cues);
    expect(merged.length).toBe(1);
    expect(merged[0].text).toBe('Hello, how are you today?');
  });

  it('should not merge cues separated by terminal punctuation', () => {
    const cues: Cue[] = [
      { id: '1', text: 'Hello.', startMs: 1000, endMs: 3000 },
      { id: '2', text: 'How are you?', startMs: 3050, endMs: 5000 },
    ];

    const merged = mergeCues(cues);
    expect(merged.length).toBe(2);
  });

  it('should not merge cues with large gaps', () => {
    const cues: Cue[] = [
      { id: '1', text: 'Hello', startMs: 1000, endMs: 3000 },
      { id: '2', text: 'world', startMs: 5000, endMs: 7000 }, // gap > 100
    ];

    const merged = mergeCues(cues);
    expect(merged.length).toBe(2);
  });

  it('should handle empty cue list', () => {
    expect(mergeCues([])).toEqual([]);
  });

  it('should handle a single cue', () => {
    const cues: Cue[] = [{ id: '1', text: 'Hello', startMs: 0, endMs: 1000 }];
    const merged = mergeCues(cues);
    expect(merged.length).toBe(1);
    expect(merged[0].text).toBe('Hello');
  });
});

describe('lookaheadWindow', () => {
  it('should return the next N cues', () => {
    const window = lookaheadWindow(0, 10);
    expect(window).toEqual([0, 1, 2, 3, 4]);
  });

  it('should clamp to the end of the cue list', () => {
    const window = lookaheadWindow(8, 10);
    expect(window).toEqual([8, 9]);
  });

  it('should return empty for out-of-range index', () => {
    const window = lookaheadWindow(15, 10);
    expect(window).toEqual([]);
  });
});
