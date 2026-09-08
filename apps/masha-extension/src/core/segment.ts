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

import { hasBlockDescendant, NodeSummary } from './dom/tree';

export interface Segment {
  /**
   * Stable id: `${nodeId}:${hash}`, plus `#${chunk}` when a long block was
   * split. `nodeId` comes from the element's `data-masha-node` attribute, so
   * it survives insertions elsewhere in the document; `hash` covers the text,
   * so an edited block is re-translated rather than left stale.
   */
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
 * Split a single sentence that is on its own longer than the budget.
 */
function hardSplit(text: string, maxChars: number): string[] {
  if (text.length <= maxChars) return [text];
  const pieces: string[] = [];
  for (let i = 0; i < text.length; i += maxChars) {
    pieces.push(text.slice(i, i + maxChars));
  }
  return pieces;
}

/**
 * Split a long block at sentence boundaries.
 * Returns array of chunks, each ≤ maxChars.
 */
export function splitLongBlock(text: string, maxChars: number): string[] {
  if (text.length <= maxChars) return [text];

  // Each match is one sentence *including* its terminator and trailing space,
  // so re-joining the chunks reproduces the original spacing.
  const sentences = text.match(/[^.!?。！？]*[.!?。！？]+\s*|[^.!?。！？]+$/g) ?? [text];

  const chunks: string[] = [];
  let current = '';

  for (const sentence of sentences) {
    for (const piece of hardSplit(sentence, maxChars)) {
      if (current !== '' && current.length + piece.length > maxChars) {
        chunks.push(current.trim());
        current = '';
      }
      current += piece;
    }
  }

  if (current.trim() !== '') chunks.push(current.trim());

  return chunks.filter(chunk => chunk.length > 0);
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

  /**
   * The text function returns a node's *whole subtree*, so emitting both a
   * container and its children would send the same prose once per level of
   * nesting. Only the innermost block is a segment.
   */
  const isContainer = (node: NodeSummary) =>
    hasBlockDescendant(node, tag => policy.skipTags.has(tag));

  function walk(node: NodeSummary) {
    // Skip tags that should never be translated
    if (policy.skipTags.has(node.tag)) return;

    // A container: its text belongs to the blocks underneath it.
    if (isContainer(node)) {
      for (const child of node.children) walk(child);
      return;
    }

    // Determine the kind
    let kind: Segment['kind'] = 'block';
    if (HEADING_TAGS.has(node.tag)) kind = 'heading';
    if (node.tag === 'li') kind = 'listitem';
    if (node.tag === 'figcaption' || node.tag === 'caption') kind = 'caption';
    if (node.tag === 'blockquote') kind = 'quote';

    const nodeText = text(node.id);
    if (!shouldTranslate(nodeText, policy)) return;

    const baseId = `${node.id}:${hashStr(nodeText)}`;
    const chunks = splitLongBlock(nodeText, policy.maxChars);

    chunks.forEach((chunk, index) => {
      if (!shouldTranslate(chunk, policy)) return;
      segments.push({
        id: chunks.length > 1 ? `${baseId}#${index}` : baseId,
        text: chunk,
        kind,
        order: order++,
      });
    });
  }

  walk(nodes);

  // Sort by document order
  segments.sort((a, b) => a.order - b.order);

  return segments;
}

/** The node id a segment (or chunk) belongs to — the part before the colon. */
export function segmentNodeId(segmentId: string): number | null {
  const parsed = Number.parseInt(segmentId.split(':')[0], 10);
  return Number.isInteger(parsed) ? parsed : null;
}

/** The chunk index of a segment id, or 0 when the block was not split. */
export function segmentChunkIndex(segmentId: string): number {
  const hash = segmentId.indexOf('#');
  if (hash === -1) return 0;
  const parsed = Number.parseInt(segmentId.slice(hash + 1), 10);
  return Number.isInteger(parsed) ? parsed : 0;
}
