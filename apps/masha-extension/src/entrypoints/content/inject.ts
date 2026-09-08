/*
 * Masha — Browser extension selection translator.
 * Copyright (C) 2026  Clementine Pendragon <clem@pendragon.systems>
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with this program.  If not, see <https://www.gnu.org/licenses/>.
 *
 * Contact: clem@pendragon.systems (Clementine Pendragon, c/o Xian Project Development)
 */

/*
 * Content-script side — injects translations into the page.
 *
 * Each translation is inserted as a custom <masha-tr> element with a shadow
 * root, so the site's CSS cannot restyle the translation and MASHA's CSS
 * cannot leak onto the site.
 *
 * Source elements are found by the `data-masha-node` id the walker stamped on
 * them, and are marked with `data-masha-id` (node id + text hash) once
 * translated — that mark is what the observer's "have I seen this?" filter
 * reads, so injecting and de-duplicating stay in step.
 *
 * Idempotent: re-running skips what is already done. Undo removes all
 * <masha-tr> elements and strips MASHA's attributes.
 */

import { segmentChunkIndex, segmentNodeId } from '../../core/segment';
import { NODE_ID_ATTR } from './walk';

/** Attribute marking a source element as translated (node id + text hash). */
export const SOURCE_ID_ATTR = 'data-masha-id';

const SHADOW_STYLE = `
  :host {
    display: block;
    margin: 0;
    padding: 4px 0;
  }
  :host([dir="rtl"]) {
    direction: rtl;
    text-align: right;
  }
  :host([dir="ltr"]) {
    direction: ltr;
    text-align: left;
  }
  .masha-tr-content {
    font-size: inherit;
    font-family: inherit;
    line-height: inherit;
    color: #1e293b;
    background: #f1f5f9;
    border-radius: 4px;
    padding: 2px 6px;
    display: inline-block;
    max-width: 100%;
    word-wrap: break-word;
  }
`;

/** CSS injected into the page for <masha-tr> elements. */
const PAGE_STYLE = `
  masha-tr {
    display: block;
    contain: content;
    isolation: isolate;
  }
`;

let styleInjected = false;

/**
 * Chunk texts already painted into a <masha-tr>, so a long block split across
 * several requests reassembles in order however the responses arrive.
 */
const renderedChunks = new WeakMap<Element, { content: HTMLElement; chunks: Map<number, string> }>();

/** Inject the page-level style once. */
function ensurePageStyle(): void {
  if (styleInjected) return;
  const style = document.createElement('style');
  style.textContent = PAGE_STYLE;
  document.head.appendChild(style);
  styleInjected = true;
}

/** The part of a segment id shared by every chunk of one block. */
function baseSegmentId(segmentId: string): string {
  const hash = segmentId.indexOf('#');
  return hash === -1 ? segmentId : segmentId.slice(0, hash);
}

/** Find the element a segment id refers to, via its stable walk id. */
export function findSource(segmentId: string): Element | null {
  const nodeId = segmentNodeId(segmentId);
  if (nodeId === null) return null;
  return document.querySelector(`[${NODE_ID_ATTR}="${nodeId}"]`);
}

/**
 * Inject a translation for a single segment.
 *
 * Creates a <masha-tr> shadow-rooted element right after the source element,
 * and copies display from the source so a translated <li> still sits in the list.
 *
 * @param segmentId - The segment id (`nodeId:hash`, optionally `#chunk`).
 * @param translatedText - The translated text to inject.
 * @param lang - BCP47 language tag for the translation.
 * @param dir - 'ltr' | 'rtl' direction.
 * @returns true when the translation was placed on the page.
 */
export function injectTranslation(
  segmentId: string,
  translatedText: string,
  lang: string = 'en',
  dir: 'ltr' | 'rtl' = 'ltr',
): boolean {
  ensurePageStyle();

  const source = findSource(segmentId);
  if (!source) return false;

  const baseId = baseSegmentId(segmentId);
  const chunkIndex = segmentChunkIndex(segmentId);

  // Reuse the sibling <masha-tr> when it belongs to this same block — a split
  // block arrives as several chunks that share one anchor.
  const sibling = source.nextElementSibling;
  let tr: Element | null =
    sibling?.tagName === 'MASHA-TR' && sibling.getAttribute('data-masha-for') === baseId
      ? sibling
      : null;

  if (tr) {
    const state = renderedChunks.get(tr);
    if (!state) return false; // a <masha-tr> from a previous page load
    if (state.chunks.get(chunkIndex) === translatedText) return true; // already done
    state.chunks.set(chunkIndex, translatedText);
    state.content.textContent = orderedText(state.chunks);
    return true;
  }

  if (sibling?.tagName === 'MASHA-TR') return false; // anchored to a stale block

  // Get the source's display property
  const display = getComputedStyle(source).display;

  // Create the custom element
  tr = document.createElement('masha-tr');
  tr.setAttribute('data-masha-for', baseId);
  (tr as HTMLElement).lang = lang;
  (tr as HTMLElement).dir = dir;

  // Shadow root
  const shadow = tr.attachShadow({ mode: 'closed' });

  // Apply styles
  const style = document.createElement('style');
  style.textContent = SHADOW_STYLE;
  shadow.appendChild(style);

  // Content wrapper
  const content = document.createElement('div');
  content.className = 'masha-tr-content';
  const chunks = new Map<number, string>([[chunkIndex, translatedText]]);
  content.textContent = orderedText(chunks);
  shadow.appendChild(content);
  renderedChunks.set(tr, { content, chunks });

  // Copy display from source
  (tr as HTMLElement).style.display = display;

  // Insert after the source element
  source.insertAdjacentElement('afterend', tr);

  // Mark the source so the observer stops re-reporting it as new content
  markSource(baseId, source);

  return true;
}

/** Join the chunks of one block back together in document order. */
function orderedText(chunks: Map<number, string>): string {
  return [...chunks.entries()]
    .sort((a, b) => a[0] - b[0])
    .map(([, text]) => text)
    .join(' ');
}

/**
 * Mark a source element as translated (sets data-masha-id).
 */
export function markSource(sourceId: string, element: Element): void {
  element.setAttribute(SOURCE_ID_ATTR, sourceId);
}

/**
 * Remove all injected translations and strip source markers.
 */
export function undoAll(): void {
  document.querySelectorAll('masha-tr').forEach(n => n.remove());
  document.querySelectorAll(`[${SOURCE_ID_ATTR}]`).forEach(n => n.removeAttribute(SOURCE_ID_ATTR));
  document.querySelectorAll(`[${NODE_ID_ATTR}]`).forEach(n => n.removeAttribute(NODE_ID_ATTR));
}
