/*
 * M3 — Profile registry.
 *
 * Browser-free core.  Returns the first matching profile for a URL, or null.
 */

import { SiteProfile, ProfileRegistry } from './types';

/** Built-in profiles covering the most common page types. */
const BUILTIN_PROFILES: SiteProfile[] = [
  // Search engine results
  {
    match: /google\.com\/search/i,
    articleSelector: '#search',
    segmentSelectors: ['[data-hveid] h3', '[data-hveid] span'],
    skipSelectors: ['.g-blk', '.ad', '#foot'],
    observeSelector: '#search',
  },
  {
    match: /bing\.com\/search/i,
    articleSelector: '#results',
    segmentSelectors: ['.b_algo h2', '.b_algo .b_caption'],
    skipSelectors: ['.b_ad', '#b_pivot'],
    observeSelector: '#results',
  },
  {
    match: /duckduckgo\.com/i,
    articleSelector: '.results',
    segmentSelectors: ['.result__title', '.result__body'],
    skipSelectors: ['.result--ad', '.result--suggestion'],
    observeSelector: '.results',
  },

  // Social media timelines
  {
    match: /twitter\.com|x\.com/i,
    articleSelector: '[data-testid="tweet"]',
    segmentSelectors: ['[data-testid="tweetText"]'],
    skipSelectors: ['[data-testid="caret"]', '[data-testid="retweet"]', '.css-1dbjc4n'],
    observeSelector: '[aria-label="Timeline"]',
  },
  {
    match: /reddit\.com/i,
    articleSelector: 'shreddit-post, .Post',
    segmentSelectors: ['shreddit-post .text, .Post h3, .Post ._3ZxME'],
    skipSelectors: ['shreddit-post-vote, .vote, ._1wzYk'],
    observeSelector: 'shreddit-feed, ._3zH_8',
  },

  // News sites (generic)
  {
    match: /news|article|story|entry/i,
    articleSelector: 'article, [role="main"], .article, .story, .entry, .post, .content',
    segmentSelectors: ['h1, h2, h3, p, li, td'],
    skipSelectors: ['.sidebar', '.footer', '.promo', '.related', '.share', '.cookie', '.ad'],
    inject: 'after',
  },
];

/**
 * Find the first matching profile for a URL, or `null` if no profile matches.
 */
export function profileFor(
  url: string,
  registry: ProfileRegistry = { profiles: BUILTIN_PROFILES },
): SiteProfile | null {
  for (const profile of registry.profiles) {
    if (profile.match.test(url)) {
      return profile;
    }
  }
  return null;
}

export { BUILTIN_PROFILES };
