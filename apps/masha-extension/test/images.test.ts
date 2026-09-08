/*
 * Tests for image/comic translation.
 *
 * Browser-free — the module talks to the background worker rather than the
 * network (an MV3 content script has no cross-origin fetch of its own), so the
 * seam under test is `chrome.runtime.sendMessage`.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { translateImage, DEFAULT_IMAGE_CONFIG } from '../src/entrypoints/content/images';

const PNG = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPj/AAADBQEARFQ0VgAAAABJRU5ErkJggg==';

/** A background that answers the way the real one does. */
function mockBackground(overrides: Record<string, unknown> = {}) {
  const sendMessage = vi.fn(async (message: any) => {
    if (message.type in overrides) return overrides[message.type];
    switch (message.type) {
      case 'MASHA_FETCH_IMAGE':
        return { success: true, dataUrl: PNG };
      case 'MASHA_OCR':
        return {
          success: true,
          result: {
            blocks: [
              { quad: { x1: 0, y1: 0, x2: 100, y2: 0, x3: 100, y3: 20, x4: 0, y4: 20 }, text: 'Hi', confidence: 0.9 },
              { quad: { x1: 0, y1: 20, x2: 100, y2: 20, x3: 100, y3: 40, x4: 0, y4: 40 }, text: 'Hello world', confidence: 0.95 },
            ],
          },
        };
      case 'MASHA_TRANSLATE_TEXT':
        return { success: true, translation: 'Bonjour le monde' };
      case 'MASHA_OCR_RENDER':
        return { success: true, image: PNG };
      default:
        return { success: false, error: `unexpected ${message.type}` };
    }
  });
  (globalThis as any).chrome = { runtime: { id: 'test', sendMessage } };
  return sendMessage;
}

/** Mock the parts of `document` the renderer touches. */
function mockDocument() {
  (globalThis as any).document = {
    querySelectorAll: () => [],
    images: [],
  };
}

describe('translateImage', () => {
  beforeEach(() => {
    mockDocument();
  });

  it('should translate each OCR block through the background', async () => {
    const sendMessage = mockBackground();
    const onProgress = vi.fn();

    await translateImage('https://example.com/img.png', DEFAULT_IMAGE_CONFIG, onProgress);

    expect(onProgress).toHaveBeenCalled();
    // "Hi" is under the three-character floor and is passed through, so only
    // the longer block costs a model call.
    const translated = sendMessage.mock.calls.filter(
      ([message]: [any]) => message.type === 'MASHA_TRANSLATE_TEXT',
    );
    expect(translated).toHaveLength(1);
    expect(translated[0][0].text).toBe('Hello world');
  });

  it('should surface a bridge that has no OCR engine', async () => {
    mockBackground({
      MASHA_OCR: { success: false, error: 'The bridge has no OCR engine' },
    });

    await expect(
      translateImage('https://example.com/img.png', DEFAULT_IMAGE_CONFIG),
    ).rejects.toThrow(/no OCR engine/);
  });

  it('should give up quietly when the image cannot be fetched', async () => {
    const sendMessage = mockBackground({
      MASHA_FETCH_IMAGE: { success: true, dataUrl: null },
    });

    await translateImage('https://example.com/img.png', DEFAULT_IMAGE_CONFIG);

    // Nothing to OCR means nothing else is asked of the background.
    expect(sendMessage.mock.calls.map(([m]: [any]) => m.type)).toEqual(['MASHA_FETCH_IMAGE']);
  });
});
