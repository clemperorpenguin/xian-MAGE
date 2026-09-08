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
  /** Own text length, excluding descendants'. */
  textLength: number;
  /** Text length inside <a> descendants (for link-density test). */
  linkTextLength: number;
  /** Child nodes (recursive). */
  children: NodeSummary[];
}

/** Build a flat list of all leaf text-bearing nodes, indexed by id. */
export interface NodeTableEntry {
  id: number;
  /** The text content (normalised whitespace). */
  text: string;
}

/**
 * Collect all text-bearing leaf nodes into a flat table, keyed by the same
 * ids used in the tree. This is the serialised "text content" of the page.
 */
export function buildNodeTable(root: NodeSummary): NodeTableEntry[] {
  const table: NodeTableEntry[] = [];
  let nextId = 0;

  function walk(node: NodeSummary) {
    if (node.children.length === 0 && node.textLength > 0) {
      table.push({ id: node.id, text: '' }); // placeholder — filled by the content script
    }
    for (const child of node.children) {
      walk(child);
    }
  }

  walk(root);
  return table;
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
