/*
 * Tests for the site profile registry.
 *
 * Browser-free core test — pure URL matching.
 */

import { describe, it, expect } from 'vitest';
import { profileFor, BUILTIN_PROFILES } from '../../src/core/profiles/registry';
import { ProfileRegistry } from '../../src/core/profiles/types';

describe('profileFor', () => {
  it('should match Google search', () => {
    const profile = profileFor('https://www.google.com/search?q=test');
    expect(profile).not.toBeNull();
    expect(profile!.articleSelector).toBe('#search');
  });

  it('should match Bing search', () => {
    const profile = profileFor('https://www.bing.com/search?q=test');
    expect(profile).not.toBeNull();
    expect(profile!.articleSelector).toBe('#results');
  });

  it('should match DuckDuckGo', () => {
    const profile = profileFor('https://duckduckgo.com/?q=test');
    expect(profile).not.toBeNull();
    expect(profile!.articleSelector).toBe('.results');
  });

  it('should match Twitter/X', () => {
    const profile = profileFor('https://twitter.com/someuser/status/123');
    expect(profile).not.toBeNull();
    expect(profile!.articleSelector).toBe('[data-testid="tweet"]');
  });

  it('should match Reddit', () => {
    const profile = profileFor('https://www.reddit.com/r/test/comments/123/');
    expect(profile).not.toBeNull();
    expect(profile!.articleSelector).toBe('shreddit-post, .Post');
  });

  it('should return null for unrecognised URLs', () => {
    const profile = profileFor('https://example.com/');
    expect(profile).toBeNull();
  });

  it('should respect registry ordering (first match wins)', () => {
    const custom: ProfileRegistry = {
      profiles: [
        { match: /example/, articleSelector: '#first' },
        { match: /example/, articleSelector: '#second' },
      ],
    };
    const profile = profileFor('https://example.com/', custom);
    expect(profile!.articleSelector).toBe('#first');
  });

  it('should handle empty registry', () => {
    const profile = profileFor('https://google.com/search', { profiles: [] });
    expect(profile).toBeNull();
  });
});
