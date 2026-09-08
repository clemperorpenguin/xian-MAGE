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
 * Serialisable node tree. A flattened view of the DOM that carries only the
 * signals the article-finder and segmenter need: tag, role, class names,
 * text lengths and link density. No references, no closures, no DOM — so it
 * can be serialised, cached, and tested with no browser.
 */

/** A single node in the serialisable tree. Index into the content script's node table. */
export interface NodeSummary {
  /** Index into the content script's node table (assigned during walk). */
  id: number;
  /** Lowercased tagName. */
  tag: string;
  /** ARIA role, if set. */
  role?: string;
  /** Full className string (space-separated). */
  className: string;
  /** The element's id attribute. */
  elementId: string;
  /**
   * Text length of the node *including* its descendants.
   *
   * Subtree-inclusive on purpose: ``linkTextLength`` is measured over the same
   * subtree, and a ratio between two different scopes is not a link density.
   */
  textLength: number;
  /** Text length inside <a> descendants (for link-density test). */
  linkTextLength: number;
  /** Commas in the node's text — Readability's prose signal. */
  commas: number;
  /** Child nodes (recursive). */
  children: NodeSummary[];
}

/**
 * Tags that are block-level containers rather than leaf text.
 *
 * Shared by the segmenter and the article finder: both need to know where the
 * innermost block sits — one to translate it, the other to score it.
 */
export const BLOCK_TAGS = new Set([
  'p', 'div', 'section', 'article', 'main', 'header', 'footer', 'nav',
  'blockquote', 'figure', 'figcaption', 'li', 'td', 'th', 'h1', 'h2', 'h3',
  'h4', 'h5', 'h6', 'ul', 'ol', 'dl', 'dt', 'dd', 'table', 'thead', 'tbody',
  'tfoot', 'tr', 'aside', 'form', 'fieldset', 'details', 'summary',
]);

/**
 * Does this node contain another block?
 *
 * A node's text covers its whole subtree, so a node with block descendants is
 * a container: its text belongs to the blocks underneath it, not to itself.
 *
 * @param skip - Optional predicate for subtrees to ignore entirely.
 */
export function hasBlockDescendant(
  node: NodeSummary,
  skip?: (tag: string) => boolean,
): boolean {
  for (const child of node.children) {
    if (skip?.(child.tag)) continue;
    if (BLOCK_TAGS.has(child.tag)) return true;
    if (hasBlockDescendant(child, skip)) return true;
  }
  return false;
}

/**
 * Count commas in text (for Readability-style scoring).
 * Browser-free — operates on plain text.
 */
export function commaCount(text: string): number {
  let count = 0;
  for (let i = 0; i < text.length; i++) {
    if (text[i] === ',') count++;
  }
  return count;
}

/**
 * Calculate link density for a node: ratio of link text to total text.
 */
export function linkDensity(node: NodeSummary): number {
  if (node.textLength === 0) return 0;
  return node.linkTextLength / node.textLength;
}
