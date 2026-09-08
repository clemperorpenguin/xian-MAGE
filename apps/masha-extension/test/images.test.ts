/*
 * Tests for image/comic translation.
 *
 * Browser-free — tests the core image translation flow using mock fetch.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { translateImage, DEFAULT_IMAGE_CONFIG } from '../src/entrypoints/content/images';

/** Mock FileReader for Node.js test environment. */
function mockFileReader() {
  (globalThis as any).FileReader = class MockFileReader {
    onloadend: (() => void) | null = null;
    result: string | null = null;

    readAsDataURL(blob: Blob) {
      this.result = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPj/AAADBQEARFQ0VgAAAABJRU5ErkJggg==';
      this.onloadend?.();
    }
  };
}

/** Mock document.querySelectorAll for Node. */
function mockDocument() {
  (globalThis as any).document = {
    querySelectorAll: () => [],
    images: [],
  };
}

/** Helper: create a mock fetch. */
function mockImageFetch(mockFetch: any) {
  mockFetch.mockImplementation(async (url: string) => {
    // OCR endpoint — must come before generic http:// check
    if (typeof url === 'string' && url.includes('/ocr') && !url.includes('/render')) {
      return {
        ok: true,
        json: async () => ({
          blocks: [
            { quad: { x1: 0, y1: 0, x2: 100, y2: 0, x3: 100, y3: 20, x4: 0, y4: 20 }, text: 'Hi', confidence: 0.9 },
            { quad: { x1: 0, y1: 20, x2: 100, y2: 20, x3: 100, y3: 40, x4: 0, y4: 40 }, text: 'Hello world', confidence: 0.95 },
          ],
        }),
      };
    }
    // Translation endpoint
    if (typeof url === 'string' && url.includes('/chat/completions')) {
      return {
        ok: true,
        json: async () => ({ choices: [{ message: { content: 'Bonjour le monde' } }] }),
      };
    }
    // Image fetch: return a blob that FileReader will handle
    if (typeof url === 'string' && (url.startsWith('https://') || url.startsWith('http://'))) {
      return {
        ok: true,
        blob: async () => new Blob(['fake-png-bytes'], { type: 'image/png' }),
      };
    }
    return { ok: true, json: async () => ({}) };
  });
}

describe('translateImage', () => {
  beforeEach(() => {
    mockFileReader();
    mockDocument();
  });

  it('should handle OCR blocks with short text (pass through)', { timeout: 10000 }, async () => {
    const onProgress = vi.fn();

    const mockFetch = vi.fn();
    mockImageFetch(mockFetch);

    globalThis.fetch = mockFetch;
    globalThis.chrome = { runtime: { id: 'test', sendMessage: vi.fn() } } as any;

    await translateImage('https://example.com/img.png', DEFAULT_IMAGE_CONFIG, onProgress);

    expect(onProgress).toHaveBeenCalled();
  });

  it('should handle missing bridge gracefully', { timeout: 10000 }, async () => {
    const mockFetch = vi.fn();
    // OCR check must come before generic http check
    mockFetch.mockImplementation(async (url: string) => {
      if (typeof url === 'string' && url.includes('/ocr')) {
        return { ok: false, status: 503, statusText: 'Unavailable' };
      }
      if (typeof url === 'string' && (url.startsWith('https://') || url.startsWith('http://'))) {
        return {
          ok: true,
          blob: async () => new Blob(['fake-png'], { type: 'image/png' }),
        };
      }
      return { ok: true, json: async () => ({}) };
    });

    globalThis.fetch = mockFetch;

    try {
      await translateImage('https://example.com/img.png', DEFAULT_IMAGE_CONFIG);
      expect.fail('Should have thrown');
    } catch (err) {
      expect((err as Error).message).toContain('OCR failed');
    }
  });
});
