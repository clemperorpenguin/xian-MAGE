/*
 * Tests for article root finding.
 *
 * Browser-free — operates on NodeSummary trees built by test/helpers/tree.ts,
 * which measures text and link text the way the live-DOM walker does.
 */

import { describe, it, expect } from 'vitest';
import { findArticleRoot } from '../src/core/dom/article';
import { linkDensity } from '../src/core/dom/tree';
import { buildFixture, prose } from './helpers/tree';

/** A link-only navigation block: <nav><ul><li><a>…</a></li>…</ul></nav>. */
function navigation(className = 'sidebar') {
  return {
    tag: 'nav',
    className,
    children: [
      {
        tag: 'ul',
        children: ['Home', 'Archive', 'About us', 'Contact', 'Subscribe now'].map(label => ({
          tag: 'li',
          children: [{ tag: 'a', text: label }],
        })),
      },
    ],
  };
}

describe('findArticleRoot', () => {
  it('should find the article element when present and non-trivial', () => {
    const { root, ids } = buildFixture({
      tag: 'div',
      className: 'page',
      children: [
        navigation(),
        {
          tag: 'article',
          className: 'post',
          children: [
            { tag: 'h1', text: 'A headline for the piece' },
            { tag: 'p', text: prose(200) },
            { tag: 'p', text: prose(300) },
          ],
        },
        { tag: 'footer', className: 'footer', children: [{ tag: 'a', text: 'Terms of service' }] },
      ],
    });

    expect(findArticleRoot(root)).toBe(ids.get('article')![0]);
  });

  it('should return null when no article content exists', () => {
    const { root } = buildFixture({
      tag: 'div',
      className: 'search-page',
      children: [
        { tag: 'div', className: 'result', children: [{ tag: 'a', text: 'A result' }] },
        { tag: 'div', className: 'result', children: [{ tag: 'a', text: 'Another' }] },
      ],
    });

    expect(findArticleRoot(root)).toBeNull();
  });

  it('should handle an empty tree gracefully', () => {
    const { root } = buildFixture({ tag: 'div' });
    expect(findArticleRoot(root)).toBeNull();
  });

  it('should score navigation as navigation, not prose', () => {
    // The walker measures link text over the subtree. When textLength was own
    // text only, a <nav> full of <li><a> had textLength 0, linkDensity fell
    // through its zero guard to 0, and pure navigation scored as clean prose.
    const { root, ids } = buildFixture({
      tag: 'div',
      className: 'page',
      children: [
        navigation(),
        { tag: 'div', className: 'body', children: [{ tag: 'p', text: prose(400) }] },
      ],
    });

    const nav = root.children[0];
    expect(linkDensity(nav)).toBeGreaterThan(0.9);
    expect(findArticleRoot(root)).not.toBe(ids.get('nav')![0]);
  });

  it('should prefer comma-dense prose over longer boilerplate', () => {
    // Readability's comma term. It used to count commas in the *string form of
    // the text length* ("500"), which is always zero, so length alone decided.
    const commaRich = 'One, two, three, four, five, six, seven, eight, nine, ten, '.repeat(4);
    const { root, ids } = buildFixture({
      tag: 'div',
      children: [
        { tag: 'section', children: [{ tag: 'p', text: commaRich }] },
        { tag: 'section', children: [{ tag: 'p', text: 'x'.repeat(500) }] },
      ],
    });

    expect(findArticleRoot(root)).toBe(ids.get('p')![0]);
  });
});
