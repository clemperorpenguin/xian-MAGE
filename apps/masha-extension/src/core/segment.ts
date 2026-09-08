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
 * Browser-free core — see core/constants.ts.
 *
 * Page segmentation: split a serialised node tree into translatable segments.
 *
 * A block is the unit, never a sentence — translating a sentence without its
 * paragraph loses exactly the context that makes MASHA worth using.
 */

import { NodeSummary } from './dom/tree';

export interface Segment {
  /** Stable id within a page load: `${nodeId}:${hash}`. */
  id: string;
  /** Normalised, whitespace-collapsed text. */
  text: string;
  /** Semantic kind of the segment. */
  kind: 'block' | 'heading' | 'listitem' | 'caption' | 'quote';
  /** Document order, for reading-order batching. */
  order: number;
}

export interface SegmentPolicy {
  /** Minimum characters — "OK" is not worth a request. */
  minChars: number;
  /** Longer blocks are split at sentence ends. */
  maxChars: number;
  /** Tags whose content should never be translated. */
  skipTags: Set<string>;
  /** If true, skip text that looks like numeric data. */
  skipIfNumeric: boolean;
}

export const DEFAULT_SEGMENT_POLICY: SegmentPolicy = {
  minChars: 3,
  maxChars: 1200,
  skipTags: new Set(['code', 'pre', 'kbd', 'samp', 'var', 'script', 'style', 'svg', 'math']),
  skipIfNumeric: true,
};

/** Tags that are themselves block-level containers (not leaf text). */
const BLOCK_TAGS = new Set([
  'p', 'div', 'section', 'article', 'main', 'header', 'footer', 'nav',
  'blockquote', 'figure', 'figcaption', 'li', 'td', 'th', 'h1', 'h2', 'h3',
  'h4', 'h5', 'h6',
]);

/** Heading tags for kind classification. */
const HEADING_TAGS = new Set(['h1', 'h2', 'h3', 'h4', 'h5', 'h6']);

/**
 * Simple hash for segment id generation.
 */
function hashStr(s: string): string {
  let hash = 0;
  for (let i = 0; i < s.length; i++) {
    hash = ((hash << 5) - hash) + s.charCodeAt(i);
    hash |= 0;
  }
  return hash.toString(16);
}

/**
 * Check if text should be translated under the given policy.
 */
export function shouldTranslate(text: string, policy: SegmentPolicy = DEFAULT_SEGMENT_POLICY): boolean {
  const trimmed = text.trim();
  if (trimmed.length < policy.minChars) return false;

  if (policy.skipIfNumeric) {
    // Skip if text is entirely numeric, a number with currency, or a measurement
    const numericPattern = /^[\d\s,.%$¥€£₹₩₽¥₫₿°\'"]+$/;
    if (numericPattern.test(trimmed)) return false;
  }

  return true;
}

/**
 * Split a long block at sentence boundaries.
 * Returns array of chunks, each ≤ maxChars.
 */
export function splitLongBlock(text: string, maxChars: number): string[] {
  if (text.length <= maxChars) return [text];

  const chunks: string[] = [];
  const sentenceEnds = /[.!?。！？]+/g;
  let lastIndex = 0;
  let match;

  while ((match = sentenceEnds.exec(text)) !== null) {
    const end = match.index + match[0].length;
    if (end - lastIndex <= maxChars) continue;

    // Push the chunk up to this sentence end
    const chunk = text.slice(lastIndex, end).trim();
    if (chunk.length >= 1) chunks.push(chunk);
    lastIndex = end;

    // If we've accumulated enough, break
    if (chunks.length > 0 && chunks.join('').length >= maxChars * 2) break;
  }

  // Remaining text
  const remaining = text.slice(lastIndex).trim();
  if (remaining.length >= 1) chunks.push(remaining);

  // If splitting didn't produce multiple chunks, force split at maxChars
  if (chunks.length <= 1 && text.length > maxChars) {
    chunks.length = 0;
    for (let i = 0; i < text.length; i += maxChars) {
      chunks.push(text.slice(i, i + maxChars).trim());
    }
  }

  return chunks;
}

/**
 * Convert a serialised node tree into translatable segments.
 *
 * @param nodes - The root NodeSummary from the page walk.
 * @param text - A function that maps node id → text content (from the node table).
 * @param policy - Segmentation policy.
 */
export function toSegments(
  nodes: NodeSummary,
  text: (id: number) => string,
  policy: SegmentPolicy = DEFAULT_SEGMENT_POLICY,
): Segment[] {
  const segments: Segment[] = [];
  let order = 0;

  function walk(node: NodeSummary) {
    // Skip tags that should never be translated
    if (policy.skipTags.has(node.tag)) return;

    // Determine the kind
    let kind: Segment['kind'] = 'block';
    if (HEADING_TAGS.has(node.tag)) kind = 'heading';
    if (node.tag === 'li') kind = 'listitem';
    if (node.tag === 'figcaption' || node.tag === 'caption') kind = 'caption';
    if (node.tag === 'blockquote') kind = 'quote';

    const nodeText = text(node.id);
    if (shouldTranslate(nodeText, policy)) {
      const id = `${node.id}:${hashStr(nodeText)}`;
      segments.push({
        id,
        text: nodeText,
        kind,
        order: order++,
      });
    }

    // Recurse into children for deeper segmentation
    for (const child of node.children) {
      walk(child);
    }
  }

  walk(nodes);

  // Sort by document order
  segments.sort((a, b) => a.order - b.order);

  return segments;
}
