/*
 * M1 + M3 — Bilingual page translation.
 *
 * Bridge side. Walks the page, decides what counts as the article (a site
 * profile when one matches, the generic scorer otherwise), turns it into
 * segments, and hands those to the background worker — which owns the model
 * call. Translations stream back one segment at a time and are injected under
 * their source block.
 *
 * The page is never rewritten: every translation is a sibling <masha-tr>.
 */

import { clampContext } from '../../core/prompt';
import { profileFor } from '../../core/profiles/registry';
import { SiteProfile } from '../../core/profiles/types';
import { NodeSummary } from '../../core/dom/tree';
import { findArticleRoot } from '../../core/dom/article';
import { Segment, segmentNodeId, toSegments } from '../../core/segment';
import { getConfig } from '../../utils/config';
import { injectTranslation, undoAll } from './inject';
import { observePage } from './observer';
import { getNodeText, walkPage, NODE_ID_ATTR } from './walk';

/** Languages whose translations must be laid out right-to-left. */
const RTL_LANGS = new Set(['Arabic', 'Hebrew', 'Persian', 'Urdu']);

/** Language name → BCP47 tag, for the `lang` attribute on the translation. */
const LANG_TAGS: Record<string, string> = {
  Arabic: 'ar', Chinese: 'zh', English: 'en', French: 'fr', German: 'de',
  Hebrew: 'he', Hindi: 'hi', Japanese: 'ja', Korean: 'ko', Persian: 'fa',
  Russian: 'ru', Spanish: 'es', Urdu: 'ur', Vietnamese: 'vi',
};

/** Everything one translated page needs to keep, and to undo. */
interface PageSession {
  lang: string;
  dir: 'ltr' | 'rtl';
  stopObserver: (() => void) | null;
}

let session: PageSession | null = null;

/** True while a translated page is on screen. */
export function isPageTranslated(): boolean {
  return session !== null;
}

/** The NodeSummary carrying a given node id, or null. */
function findSummary(root: NodeSummary, id: number): NodeSummary | null {
  if (root.id === id) return root;
  for (const child of root.children) {
    const found = findSummary(child, id);
    if (found) return found;
  }
  return null;
}

/** The live element a segment id points at. */
function elementFor(segment: Segment): Element | null {
  const nodeId = segmentNodeId(segment.id);
  if (nodeId === null) return null;
  return document.querySelector(`[${NODE_ID_ATTR}="${nodeId}"]`);
}

/**
 * The segments to translate on this page.
 *
 * A profile's `segmentSelectors` replace the article scorer outright — that is
 * the point of a profile, since a search results page or a timeline has no
 * article for the scorer to find.
 */
function collectSegments(profile: SiteProfile | null): Segment[] {
  let segments: Segment[];

  if (profile?.segmentSelectors?.length) {
    segments = [];
    let order = 0;
    for (const selector of profile.segmentSelectors) {
      for (const element of document.querySelectorAll(selector)) {
        const walk = walkPage(element);
        for (const segment of toSegments(walk.root, (id) => getNodeText(walk.nodeTable, id))) {
          segments.push({ ...segment, order: order++ });
        }
      }
    }
  } else {
    const scope = profile?.articleSelector
      ? document.querySelector(profile.articleSelector) ?? undefined
      : undefined;
    const walk = walkPage(scope);

    // Without a profile scope, score the tree for the article root and
    // translate only that — navigation and comment chrome are not the page.
    let tree = walk.root;
    if (!scope) {
      const articleId = findArticleRoot(walk.root);
      const article = articleId === null ? null : findSummary(walk.root, articleId);
      if (article) tree = article;
    }
    segments = toSegments(tree, (id) => getNodeText(walk.nodeTable, id));
  }

  if (profile?.skipSelectors?.length) {
    const skip = profile.skipSelectors.join(', ');
    segments = segments.filter((segment) => !elementFor(segment)?.closest(skip));
  }

  // De-duplicate: overlapping profile selectors can match the same block twice.
  const seen = new Set<string>();
  return segments.filter((segment) => {
    if (seen.has(segment.id)) return false;
    seen.add(segment.id);
    return true;
  });
}

/** Title plus the opening prose, as disambiguation context for every batch. */
function pageContext(segments: Segment[]): string {
  const opening = segments.slice(0, 2).map((s) => s.text).join(' ');
  return clampContext([document.title, opening].filter(Boolean).join('\n'));
}

/** Hand a batch of segments to the background and wait for it to finish. */
async function requestTranslation(segments: Segment[]): Promise<number> {
  if (segments.length === 0) return 0;
  const response = await chrome.runtime.sendMessage({
    type: 'MASHA_TRANSLATE_PAGE',
    segments,
    pageContext: pageContext(segments),
  });
  if (!response?.success) throw new Error(response?.error || 'Page translation failed.');
  return response.successCount ?? 0;
}

/**
 * Paint one translated segment.
 *
 * Called for each `MASHA_SEGMENT` the background streams back, so the page
 * fills in from the top while later batches are still in flight.
 */
export function applySegment(segmentId: string, translated: string): void {
  if (!session) return;
  injectTranslation(segmentId, translated, session.lang, session.dir);
}

/**
 * Translate the current page, then keep translating what the page adds.
 *
 * Returns the segment counts so the caller can say what happened.
 */
export async function translateCurrentPage(): Promise<{ segmentCount: number; successCount: number }> {
  const config = await getConfig();
  const profile = profileFor(location.href);

  if (!session) {
    session = {
      lang: LANG_TAGS[config.targetLang] || 'en',
      dir: RTL_LANGS.has(config.targetLang) ? 'rtl' : 'ltr',
      stopObserver: null,
    };
  }

  const segments = collectSegments(profile);
  const successCount = await requestTranslation(segments);

  // Infinite-scroll feeds and SPA route changes bring their own content; the
  // observer feeds it through the same path rather than making the user press
  // the button again.
  if (!session.stopObserver) {
    const observeRoot = profile?.observeSelector
      ? document.querySelector(profile.observeSelector) ?? undefined
      : undefined;
    session.stopObserver = observePage(observeRoot, (fresh) => {
      requestTranslation(fresh).catch(() => {
        // A failed batch of late-arriving content is not worth an alert.
      });
    });
  }

  return { segmentCount: segments.length, successCount };
}

/** Remove every translation and stop watching the page. */
export function undoPageTranslation(): void {
  session?.stopObserver?.();
  session = null;
  undoAll();
}
