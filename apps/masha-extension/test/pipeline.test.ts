/*
 * Tests for the page translation pipeline.
 *
 * Browser-free — uses a mock fetch function to simulate Lemonade responses.
 */

import { describe, it, expect, vi } from 'vitest';
import { translatePage } from '../src/core/pipeline';
import { Segment } from '../src/core/segment';
import { MashaConfig } from '../src/platform/bridge';
import { FetchFn } from '../src/core/translator';

interface Call {
  url: string;
  init: { method: string; headers: Record<string, string>; body: string; signal?: AbortSignal };
}

/** A mock fetch that records what it was asked to send. */
function makeMockFetch(responseText: string): { fetch: FetchFn; calls: Call[] } {
  const calls: Call[] = [];
  const fetch: FetchFn = async (url, init) => {
    calls.push({ url, init });
    return {
      ok: true,
      statusText: 'OK',
      json: async () => ({ choices: [{ message: { content: responseText } }] }),
    };
  };
  return { fetch, calls };
}

/** The messages the pipeline put on the wire for one call. */
function messagesOf(call: Call): { role: string; content: string }[] {
  return JSON.parse(call.init.body).messages;
}

function makeConfig(overrides: Partial<MashaConfig> = {}): MashaConfig {
  return {
    serverUrl: 'http://localhost:13305/v1',
    sourceLang: 'Auto',
    targetLang: 'English',
    styles: [],
    ...overrides,
  };
}

function marked(pairs: [string, string][]): string {
  return pairs
    .map(([id, text]) => `<<<MASHA_SEGMENT_${id}>>>\n${text}\n<<<MASHA_SEGMENT_${id}>>>`)
    .join('\n');
}

const TWO_SEGMENTS: Segment[] = [
  { id: '1:abc', text: 'Hello world.', kind: 'block', order: 0 },
  { id: '2:def', text: 'How are you?', kind: 'block', order: 1 },
];

describe('translatePage', () => {
  it('should process segments and call onSegment for each', async () => {
    const onSegment = vi.fn();
    const onError = vi.fn();
    const { fetch } = makeMockFetch(marked([
      ['1:abc', 'Bonjour le monde.'],
      ['2:def', 'Comment allez-vous ?'],
    ]));

    await translatePage(fetch, {
      segments: TWO_SEGMENTS,
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
    const onSegment = vi.fn();
    const onError = vi.fn();

    await translatePage(makeMockFetch('No markers here.').fetch, {
      segments: [{ id: '1:abc', text: 'Hello.', kind: 'block', order: 0 }],
      config: makeConfig(),
      concurrency: 1,
      batchChars: 1500,
      onSegment,
      onError,
    });

    expect(onError).toHaveBeenCalled();
    expect(onSegment).not.toHaveBeenCalled();
  });

  it('should keep the segments a batch did return', async () => {
    // One mangled marker used to throw, and the catch reported every segment
    // in the batch as failed — nine good translations lost with the bad one.
    const onSegment = vi.fn();
    const onError = vi.fn();
    const { fetch } = makeMockFetch(marked([['2:def', 'Comment allez-vous ?']]));

    await translatePage(fetch, {
      segments: TWO_SEGMENTS,
      config: makeConfig(),
      batchChars: 1500,
      onSegment,
      onError,
    });

    expect(onSegment).toHaveBeenCalledTimes(1);
    expect(onSegment).toHaveBeenCalledWith('2:def', 'Comment allez-vous ?');
    expect(onError).toHaveBeenCalledTimes(1);
    expect(onError.mock.calls[0][0]).toBe('1:abc');
  });

  it('should tell the model to preserve the markers it keys on', async () => {
    // The batch protocol matches responses back by marker. A prompt that only
    // says "output ONLY the translation" gets a marker-free answer, and then
    // every segment on the page fails to parse.
    const { fetch, calls } = makeMockFetch(marked([['1:abc', 'x'], ['2:def', 'y']]));

    await translatePage(fetch, {
      segments: TWO_SEGMENTS,
      config: makeConfig(),
      onSegment: vi.fn(),
      onError: vi.fn(),
    });

    const [system, user] = messagesOf(calls[0]);
    expect(system.role).toBe('system');
    expect(system.content).toContain('<<<MASHA_SEGMENT_id>>>');
    expect(system.content).toMatch(/Reproduce every marker line EXACTLY/);
    expect(user.content).toContain('<<<MASHA_SEGMENT_1:abc>>>');
  });

  it('should normalize the server URL the way the selection path does', async () => {
    const { fetch, calls } = makeMockFetch(marked([['1:abc', 'x']]));

    await translatePage(fetch, {
      segments: [TWO_SEGMENTS[0]],
      config: makeConfig({ serverUrl: 'http://localhost:13305' }),
      onSegment: vi.fn(),
      onError: vi.fn(),
    });

    expect(calls[0].url).toBe('http://localhost:13305/v1/chat/completions');
  });

  it('should strip reasoning tags and stray quoting from translations', async () => {
    const onSegment = vi.fn();
    const { fetch } = makeMockFetch(
      marked([['1:abc', '<think>the user wants French</think>"Bonjour le monde."']]),
    );

    await translatePage(fetch, {
      segments: [TWO_SEGMENTS[0]],
      config: makeConfig(),
      onSegment,
      onError: vi.fn(),
    });

    expect(onSegment).toHaveBeenCalledWith('1:abc', 'Bonjour le monde.');
  });

  it('should pass the glossary through to the prompt', async () => {
    const { fetch, calls } = makeMockFetch(marked([['1:abc', 'x']]));

    await translatePage(fetch, {
      segments: [TWO_SEGMENTS[0]],
      config: makeConfig(),
      glossary: { 悟空: 'Wukong' },
      onSegment: vi.fn(),
      onError: vi.fn(),
    });

    const [system, user] = messagesOf(calls[0]);
    expect(user.content).toContain('悟空 → Wukong');
    expect(system.content).toContain('GLOSSARY is binding');
  });

  it('should respect the abort signal', async () => {
    const controller = new AbortController();
    controller.abort();

    const onSegment = vi.fn();
    const onError = vi.fn();

    await translatePage(makeMockFetch('Translated text.').fetch, {
      segments: [TWO_SEGMENTS[0]],
      config: makeConfig(),
      signal: controller.signal,
      onSegment,
      onError,
    });

    expect(onSegment).not.toHaveBeenCalled();
    expect(onError).not.toHaveBeenCalled();
  });

  it('should hand the abort signal to fetch so in-flight requests cancel', async () => {
    const controller = new AbortController();
    const { fetch, calls } = makeMockFetch(marked([['1:abc', 'x']]));

    await translatePage(fetch, {
      segments: [TWO_SEGMENTS[0]],
      config: makeConfig(),
      signal: controller.signal,
      onSegment: vi.fn(),
      onError: vi.fn(),
    });

    expect(calls[0].init.signal).toBe(controller.signal);
  });

  it('should stop painting the page once aborted mid-flight', async () => {
    const controller = new AbortController();
    const onSegment = vi.fn();
    const onError = vi.fn();

    const fetch: FetchFn = async () => {
      controller.abort(); // the user hits stop while this request is open
      return {
        ok: true,
        statusText: 'OK',
        json: async () => ({
          choices: [{ message: { content: marked([['1:abc', 'Bonjour.']]) } }],
        }),
      };
    };

    await translatePage(fetch, {
      segments: [TWO_SEGMENTS[0]],
      config: makeConfig(),
      signal: controller.signal,
      onSegment,
      onError,
    });

    expect(onSegment).not.toHaveBeenCalled();
  });
});
