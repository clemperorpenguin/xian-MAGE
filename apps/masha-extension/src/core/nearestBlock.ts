/*
 * M2 — Nearest translatable block for hover.
 *
 * Browser-free core. Given a NodeSummary id (from mouse position), walk up
 * the tree to find the nearest ancestor that segmentation would accept.
 */

import { NodeSummary } from './dom/tree';

/**
 * Walk from `nodeId` upward through the tree until a node whose text would
 * pass `shouldTranslate` is found, or return `null`.
 *
 * Returns the *deepest* qualifying ancestor (closest to the target element),
 * skipping non-content tags (code, pre, script, etc.) and link-heavy nodes
 * (`<a>`, `<nav>`) whose text is mostly link text.
 */
export function nearestTranslatableBlock(
  root: NodeSummary,
  nodeId: number,
  minTextLength: number,
  skipTags: Set<string>,
): { id: number; node: NodeSummary } | null {
  const path: NodeSummary[] = [];
  findPath(root, nodeId, path);

  // path[0] = target, path[last] = root — iterate deepest first
  for (const node of path) {
    // Hard skip for these tags
    if (skipTags.has(node.tag)) return null;

    // Skip <a> and <nav> when most text is link text (navigation, not content)
    const linkRatio =
      node.textLength > 0 ? node.linkTextLength / node.textLength : 0;
    const isLinkHeavy =
      (node.tag === 'a' || node.tag === 'nav') && linkRatio > 0.5;

    if (node.textLength >= minTextLength && !isLinkHeavy) {
      return { id: node.id, node };
    }
  }

  return null;
}

/** Walk the tree to build an ancestor path to `targetId`. */
function findPath(node: NodeSummary, targetId: number, out: NodeSummary[]): boolean {
  if (node.id === targetId) {
    out.push(node);
    return true;
  }
  for (const child of node.children) {
    if (findPath(child, targetId, out)) {
      out.push(node);
      return true;
    }
  }
  return false;
}
