/*
 * Tests for the audio subtitle path's wire format.
 *
 * These three helpers are where MASHA meets Lemonade's `WS /realtime`
 * contract — the URL shape, and 16 kHz mono PCM16 as the only audio format it
 * accepts. Everything else in that module needs a real <video>.
 */

import { describe, it, expect } from 'vitest';
import { downsampleTo16k, encodePcm16, realtimeUrl } from '../../src/entrypoints/content/subtitles/audio';

describe('realtimeUrl', () => {
  it('should upgrade the scheme and keep the /v1 prefix', () => {
    expect(realtimeUrl('http://localhost:13305/v1', 'Whisper-Tiny'))
      .toBe('ws://localhost:13305/v1/realtime?model=Whisper-Tiny');
  });

  it('should use wss for an https server', () => {
    expect(realtimeUrl('https://box.local:13305/v1', 'Whisper-Tiny'))
      .toBe('wss://box.local:13305/v1/realtime?model=Whisper-Tiny');
  });

  it('should not double the slash on a trailing-slash base', () => {
    expect(realtimeUrl('http://localhost:13305/v1/', 'Whisper-Tiny'))
      .toBe('ws://localhost:13305/v1/realtime?model=Whisper-Tiny');
  });
});

describe('downsampleTo16k', () => {
  it('should leave audio already at or below 16 kHz alone', () => {
    const input = new Float32Array([0.1, 0.2, 0.3]);
    expect(downsampleTo16k(input, 16000)).toBe(input);
  });

  it('should reduce 48 kHz by three', () => {
    const input = new Float32Array(300).fill(0.5);
    expect(downsampleTo16k(input, 48000)).toHaveLength(100);
  });

  it('should average each window rather than decimate', () => {
    // Two samples per output at 32 kHz: alternating ±1 must average to 0, not
    // alias to a constant +1.
    const input = new Float32Array(8);
    for (let i = 0; i < input.length; i++) input[i] = i % 2 === 0 ? 1 : -1;
    const output = downsampleTo16k(input, 32000);
    expect(output).toHaveLength(4);
    for (const sample of output) expect(sample).toBeCloseTo(0, 5);
  });
});

describe('encodePcm16', () => {
  it('should emit two little-endian bytes per sample', () => {
    const encoded = encodePcm16(new Float32Array([0, 1, -1]));
    const bytes = Uint8Array.from(atob(encoded), (c) => c.charCodeAt(0));
    expect(bytes).toHaveLength(6);
    // 0 → 0x0000, +1 → 0x7fff, -1 → 0x8000, low byte first.
    expect([...bytes]).toEqual([0x00, 0x00, 0xff, 0x7f, 0x00, 0x80]);
  });

  it('should clamp samples outside [-1, 1]', () => {
    const bytes = Uint8Array.from(atob(encodePcm16(new Float32Array([4, -4]))), (c) => c.charCodeAt(0));
    expect([...bytes]).toEqual([0xff, 0x7f, 0x00, 0x80]);
  });
});
