/*
 * M3 — Site profile types.
 *
 * Browser-free core.  Profiles are data, not DOM.
 */

export interface SiteProfile {
  /** Regex matched against `location.href`. */
  match: RegExp;
  /** Override `findArticleRoot` entirely with a CSS selector. */
  articleSelector?: string;
  /** Treat these selectors as blocks regardless of scoring. */
  segmentSelectors?: string[];
  /** Never translate these selectors. */
  skipSelectors?: string[];
  /** Narrower mutation root for feed-style pages. */
  observeSelector?: string;
  /** Injection position relative to the source block. */
  inject?: 'after' | 'append' | 'title-attr';
  /** Whether to set `dir="rtl"` on translations. */
  rtlAware?: boolean;
}

export interface ProfileRegistry {
  /** Ordered list of profiles; first match wins. */
  profiles: SiteProfile[];
}
