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
 * Content-script side — walks the live DOM to produce a serialisable
 * NodeSummary tree and a parallel node table of text content.
 */

import { NodeSummary } from '../../core/dom/tree';

export interface WalkResult {
  /** The serialisable node tree. */
  root: NodeSummary;
  /** Flat table of text content, indexed by node id. */
  nodeTable: Map<number, string>;
}

/** Tags whose text content should never be included. */
const SKIP_TAGS = new Set(['script', 'style', 'svg', 'math', 'code', 'pre', 'kbd', 'samp', 'var']);

/** Tags that are block-level containers. */
const BLOCK_TAGS = new Set([
  'p', 'div', 'section', 'article', 'main', 'header', 'footer', 'nav',
  'blockquote', 'figure', 'figcaption', 'li', 'td', 'th', 'h1', 'h2', 'h3',
  'h4', 'h5', 'h6', 'ul', 'ol', 'table', 'tbody', 'thead', 'tr', 'span',
]);

/** Walk the live DOM starting from `document.body`. */
export function walkPage(): WalkResult {
  const nodeTable = new Map<number, string>();
  let nextId = 0;

  function walkNode(el: Element): NodeSummary {
    const id = nextId++;
    const tag = el.tagName.toLowerCase();

    // Skip tags entirely
    if (SKIP_TAGS.has(tag)) {
      return {
        id,
        tag,
        role: el.getAttribute('role') ?? undefined,
        className: '',
        elementId: '',
        textLength: 0,
        linkTextLength: 0,
        children: [],
      };
    }

    // Compute text lengths
    let ownTextLength = 0;
    let linkTextLength = 0;

    // Walk child nodes for text
    for (const child of el.childNodes) {
      if (child.nodeType === Node.TEXT_NODE) {
        const text = child.textContent?.trim() || '';
        ownTextLength += text.length;
      }
    }

    // For link density, count text inside <a> descendants
    if (tag !== 'a') {
      const links = el.querySelectorAll('a');
      for (const link of links) {
        const text = link.textContent?.trim() || '';
        linkTextLength += text.length;
      }
    } else {
      // This node is itself a link
      const text = el.textContent?.trim() || '';
      linkTextLength = text.length;
    }

    // Recurse into child elements (not text nodes)
    const children: NodeSummary[] = [];
    for (const child of el.children) {
      children.push(walkNode(child));
    }

    // Store the full text content for this node id
    const fullText = el.textContent?.trim() || '';
    nodeTable.set(id, fullText);

    return {
      id,
      tag,
      role: el.getAttribute('role') ?? undefined,
      className: el.className || '',
      elementId: el.id || '',
      textLength: ownTextLength,
      linkTextLength,
      children,
    };
  }

  const root = walkNode(document.body);
  return { root, nodeTable };
}

/**
 * Find a node in the table by id.
 */
export function getNodeText(nodeTable: Map<number, string>, id: number): string {
  return nodeTable.get(id) || '';
}
