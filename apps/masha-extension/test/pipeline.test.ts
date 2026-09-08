/*
 * Tests for the page translation pipeline.
 *
 * Browser-free — uses a mock fetch function to simulate Lemonade responses.
 */

import { describe, it, expect, vi } from 'vitest';
import { translatePage, PageTranslateOptions } from '../src/core/pipeline';
import { Segment } from '../src/core/segment';
import { MashaConfig } from '../src/platform/bridge';
import { FetchFn } from '../src/core/translator';

function makeMockFetch(responseText: string): FetchFn {
  return async (input: string, init: { method: string; headers: Record<string, string>; body: string }) => {
    return {
      ok: true,
      statusText: 'OK',
      json: async () => ({
        choices: [{ message: { content: responseText } }],
      }),
    };
  };
}

function makeConfig(): MashaConfig {
  return {
    serverUrl: 'http://localhost:13305/v1',
    sourceLang: 'Auto',
    targetLang: 'English',
    styles: [],
  };
}

describe('translatePage', () => {
  it('should process segments and call onSegment for each', async () => {
    const segments: Segment[] = [
      { id: '1:abc', text: 'Hello world.', kind: 'block', order: 0 },
      { id: '2:def', text: 'How are you?', kind: 'block', order: 1 },
    ];

    const onSegment = vi.fn();
    const onError = vi.fn();

    // Build a response with markers
    const responseText = `<<<MASHA_SEGMENT_1:abc>>>
Bonjour le monde.
<<<MASHA_SEGMENT_1:abc>>>
<<<MASHA_SEGMENT_2:def>>>
Comment allez-vous ?
<<<MASHA_SEGMENT_2:def>>>`;

    await translatePage(makeMockFetch(responseText), {
      segments,
      config: makeConfig(),
      concurrency: 2,
      batchChars: 1500,
      onSegment,
      onError,
    });

    expect(onSegment).toHaveBeenCalledTimes(2);
    expect(onSegment).toHaveBeenCalledWith('1:abc', 'Bonjour le monde.');
    expect(onSegment).toHaveBeenCalledWith('2:def', 'Comment allez-vous ?');
    expect(onError).not.toHaveBeenCalled();
  });

  it('should handle a missing marker gracefully via onError', async () => {
    const segments: Segment[] = [
      { id: '1:abc', text: 'Hello.', kind: 'block', order: 0 },
    ];

    const onSegment = vi.fn();
    const onError = vi.fn();

    // Response missing the marker
    await translatePage(makeMockFetch('No markers here.'), {
      segments,
      config: makeConfig(),
      concurrency: 1,
      batchChars: 1500,
      onSegment,
      onError,
    });

    expect(onError).toHaveBeenCalled();
    expect(onSegment).not.toHaveBeenCalled();
  });

  it('should respect the abort signal', async () => {
    const segments: Segment[] = [
      { id: '1:abc', text: 'Hello.', kind: 'block', order: 0 },
    ];

    const controller = new AbortController();
    controller.abort();

    const onSegment = vi.fn();
    const onError = vi.fn();

    await translatePage(makeMockFetch('Translated text.'), {
      segments,
      config: makeConfig(),
      signal: controller.signal,
      onSegment,
      onError,
    });

    expect(onSegment).not.toHaveBeenCalled();
    expect(onError).not.toHaveBeenCalled();
  });
});
