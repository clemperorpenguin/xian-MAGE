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
 *
 * Node identity lives on the element, in `data-masha-node`, not in walk order:
 * a comment loading above the article renumbers every positional id after it,
 * which would strand every translation already on the page.
 */

import { NodeSummary, commaCount } from '../../core/dom/tree';

export interface WalkResult {
  /** The serialisable node tree. */
  root: NodeSummary;
  /** Flat table of text content, indexed by node id. */
  nodeTable: Map<number, string>;
  /** The live element behind each node id — how translations find their anchor. */
  elements: Map<number, Element>;
}

/** Attribute carrying a node's stable id across re-walks. */
export const NODE_ID_ATTR = 'data-masha-node';

/** Tags whose text content should never be included. */
const SKIP_TAGS = new Set([
  'script', 'style', 'svg', 'math', 'code', 'pre', 'kbd', 'samp', 'var',
  // MASHA's own injections — walking them would translate the translation.
  'masha-tr',
]);

/**
 * Monotonic id source. Never reset: ids handed out before an undo must not be
 * handed out again afterwards, or a stale <masha-tr> would claim a new element.
 */
let nextNodeId = 0;

/** The element's stable node id, assigning and recording one on first sight. */
function nodeIdFor(el: Element): number {
  const existing = el.getAttribute(NODE_ID_ATTR);
  if (existing !== null) {
    const parsed = Number.parseInt(existing, 10);
    if (Number.isInteger(parsed)) return parsed;
  }
  const id = nextNodeId++;
  el.setAttribute(NODE_ID_ATTR, String(id));
  return id;
}

/** Walk the live DOM starting from `document.body`. */
export function walkPage(root?: Element): WalkResult {
  const nodeTable = new Map<number, string>();
  const elements = new Map<number, Element>();

  function walkNode(el: Element): NodeSummary {
    const id = nodeIdFor(el);
    const tag = el.tagName.toLowerCase();
    elements.set(id, el);

    // Skip tags entirely
    if (SKIP_TAGS.has(tag)) {
      nodeTable.set(id, '');
      return {
        id,
        tag,
        role: el.getAttribute('role') ?? undefined,
        className: '',
        elementId: '',
        textLength: 0,
        linkTextLength: 0,
        commas: 0,
        children: [],
      };
    }

    // Text of this node and everything under it. Link text is measured over
    // the same subtree so linkDensity() compares like with like.
    const fullText = el.textContent?.trim() || '';

    let linkTextLength = 0;
    if (tag === 'a') {
      linkTextLength = fullText.length;
    } else {
      for (const link of el.querySelectorAll('a')) {
        linkTextLength += (link.textContent?.trim() || '').length;
      }
    }

    // Recurse into child elements (not text nodes)
    const children: NodeSummary[] = [];
    for (const child of el.children) {
      children.push(walkNode(child));
    }

    // Store the full text content for this node id
    nodeTable.set(id, fullText);

    return {
      id,
      tag,
      role: el.getAttribute('role') ?? undefined,
      className: el.className || '',
      elementId: el.id || '',
      textLength: fullText.length,
      linkTextLength,
      commas: commaCount(fullText),
      children,
    };
  }

  const tree = walkNode(root ?? document.body);
  return { root: tree, nodeTable, elements };
}

/**
 * Find a node in the table by id.
 */
export function getNodeText(nodeTable: Map<number, string>, id: number): string {
  return nodeTable.get(id) || '';
}
