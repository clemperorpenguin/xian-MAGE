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
 * Article root finder. Adapted from Readability's scoring algorithm, but
 * operating on a serialisable NodeSummary tree rather than the live DOM.
 *
 * Scoring per node:
 *   base = 1 + commaCount + min(floor(textLength / 100), 3)
 *   only innermost blocks score; the score propagates to ancestors, divided
 *   by depth (scoring containers too would double-count their own children,
 *   and hand the page root the highest score every time)
 *   final score scaled by (1 - linkDensity)
 *   negative-weight classes subtract, positive ones add
 *
 * <article> and role="main" short-circuit when present and non-trivial.
 */

import { hasBlockDescendant, NodeSummary, linkDensity } from './tree';

export interface ArticleConfig {
  /** Below this length a node scores nothing. */
  minTextLength: number;
  /** Above this link density the node is considered navigation, not prose. */
  linkDensityCeiling: number;
  /** How far a paragraph's score propagates up (ancestor depth). */
  ancestorDepth: number;
  /** Siblings within this fraction of the top candidate join in. */
  topCandidateSlack: number;
}

export const DEFAULT_ARTICLE_CONFIG: ArticleConfig = {
  minTextLength: 25,
  linkDensityCeiling: 0.5,
  ancestorDepth: 3,
  topCandidateSlack: 0.75,
};

/** Class/id patterns that indicate non-content regions. */
// `ad` is anchored: unanchored it also matches header, reader, shadow,
// breadcrumb and load-more, which cancels their positive weight.
const NEGATIVE_PATTERNS = /comment|sidebar|footer|promo|share|related|menu|nav|widget|\bad(?:s|vert(?:isement)?s?)?\b/i;
const POSITIVE_PATTERNS = /article|content|post|entry|story|main|body|page/i;

/**
 * Score a single node and propagate to ancestors.
 */
function scoreNode(
  node: NodeSummary,
  scores: Map<number, number>,
  ancestors: NodeSummary[],
  config: ArticleConfig,
): void {
  if (node.textLength < config.minTextLength) return;

  const base = 1 + node.commas + Math.min(Math.floor(node.textLength / 100), 3);
  const scaled = base * (1 - linkDensity(node));

  if (scaled <= 0) return;

  // Propagate score to ancestors
  for (let depth = 1; depth <= config.ancestorDepth && depth <= ancestors.length; depth++) {
    const ancestor = ancestors[ancestors.length - depth];
    const existing = scores.get(ancestor.id) ?? 0;
    scores.set(ancestor.id, existing + scaled / depth);
  }
}

/**
 * Apply positive/negative class/id weight adjustments.
 */
function adjustForClassId(node: NodeSummary, score: number): number {
  let adjusted = score;

  if (NEGATIVE_PATTERNS.test(node.className) || NEGATIVE_PATTERNS.test(node.elementId)) {
    adjusted -= 10;
  }
  if (POSITIVE_PATTERNS.test(node.className) || POSITIVE_PATTERNS.test(node.elementId)) {
    adjusted += 10;
  }

  return adjusted;
}

/**
 * Find the root node of the article content in a page's serialisable tree.
 *
 * Returns the id of the best candidate, or null if no article is found.
 */
export function findArticleRoot(
  root: NodeSummary,
  config: ArticleConfig = DEFAULT_ARTICLE_CONFIG,
): number | null {
  // Short-circuit: <article> or role="main" when present and non-trivial
  function checkShortcut(node: NodeSummary): NodeSummary | null {
    if (node.tag === 'article' && node.textLength >= config.minTextLength) return node;
    if (node.role === 'main' && node.textLength >= config.minTextLength) return node;
    for (const child of node.children) {
      const found = checkShortcut(child);
      if (found) return found;
    }
    return null;
  }

  const shortcut = checkShortcut(root);
  if (shortcut) return shortcut.id;

  // Collect all nodes and their ancestors for scoring
  const scores = new Map<number, number>();
  const ancestorStack: NodeSummary[] = [];

  function walk(node: NodeSummary) {
    // Skip nodes with high link density
    if (linkDensity(node) > config.linkDensityCeiling) {
      // Still recurse into children
      for (const child of node.children) walk(child);
      return;
    }

    ancestorStack.push(node);
    if (!hasBlockDescendant(node)) {
      scoreNode(node, scores, ancestorStack, config);
    }

    for (const child of node.children) walk(child);
    ancestorStack.pop();
  }

  walk(root);

  if (scores.size === 0) return null;

  // Find the top candidate
  let bestId: number | null = null;
  let bestScore = -Infinity;

  for (const [id, rawScore] of scores) {
    const node = findNodeById(root, id);
    if (!node) continue;
    const adjusted = adjustForClassId(node, rawScore);
    if (adjusted > bestScore) {
      bestScore = adjusted;
      bestId = id;
    }
  }

  if (bestId === null || bestScore <= 0) return null;

  // Gather siblings of the best candidate within the slack threshold
  const threshold = bestScore * config.topCandidateSlack;
  const bestNode = findNodeById(root, bestId);
  if (!bestNode) return bestId;

  // bestNode is guaranteed non-null here from the findNodeById check
  // (the check above returns bestId early if not found, so this is safe)

  // If the best node has siblings that also score well, combine them
  // by returning the parent that contains all of them
  // (simplified: return the best id; the caller can expand from there)
  return bestId;
}

/**
 * Find a node by its id in the tree (linear search — acceptable for small trees).
 */
function findNodeById(root: NodeSummary, targetId: number): NodeSummary | null {
  if (root.id === targetId) return root;
  for (const child of root.children) {
    const found = findNodeById(child, targetId);
    if (found) return found;
  }
  return null;
}
