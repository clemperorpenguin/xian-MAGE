/*
 * Tests for the translation cache.
 *
 * Browser-free — pure LRU logic, no storage dependency.
 */

import { describe, it, expect } from 'vitest';
import { LRUCache } from '../src/core/cache';

describe('LRUCache', () => {
  it('should store and retrieve entries', () => {
    const cache = new LRUCache(100);
    cache.set({
      sourceText: 'Hello',
      sourceLang: 'Auto',
      targetLang: 'English',
      translated: 'Bonjour',
      epoch: 0,
    });

    const result = cache.get('Hello', 'Auto', 'English', 0);
    expect(result).toBe('Bonjour');
  });

  it('should return null for a cache miss', () => {
    const cache = new LRUCache(100);
    const result = cache.get('nonexistent', 'Auto', 'English', 0);
    expect(result).toBeNull();
  });

  it('should evict LRU entries when over capacity', () => {
    const cache = new LRUCache(3);
    cache.set({ sourceText: 'A', sourceLang: 'en', targetLang: 'fr', translated: 'A_TR', epoch: 0 });
    cache.set({ sourceText: 'B', sourceLang: 'en', targetLang: 'fr', translated: 'B_TR', epoch: 0 });
    cache.set({ sourceText: 'C', sourceLang: 'en', targetLang: 'fr', translated: 'C_TR', epoch: 0 });
    cache.set({ sourceText: 'D', sourceLang: 'en', targetLang: 'fr', translated: 'D_TR', epoch: 0 });

    expect(cache.get('A', 'en', 'fr', 0)).toBeNull(); // evicted
    expect(cache.get('B', 'en', 'fr', 0)).toBe('B_TR');
    expect(cache.get('C', 'en', 'fr', 0)).toBe('C_TR');
    expect(cache.get('D', 'en', 'fr', 0)).toBe('D_TR');
  });

  it('should reject stale entries (epoch mismatch)', () => {
    const cache = new LRUCache(100);
    cache.set({
      sourceText: 'Hello',
      sourceLang: 'Auto',
      targetLang: 'English',
      translated: 'Bonjour',
      epoch: 0,
    });

    expect(cache.get('Hello', 'Auto', 'English', 1)).toBeNull(); // epoch 1 > 0
    expect(cache.get('Hello', 'Auto', 'English', 0)).toBe('Bonjour');
  });
});
