/*
 * Tests for article root finding.
 *
 * Browser-free — operates on serialisable NodeSummary trees built from
 * fixture data rather than the live DOM.
 */

import { describe, it, expect } from 'vitest';
import { findArticleRoot, DEFAULT_ARTICLE_CONFIG } from '../src/core/dom/article';
import { NodeSummary } from '../src/core/dom/tree';

/** Build a simple article-like tree. */
function makeArticleTree(): NodeSummary {
  return {
    id: 0,
    tag: 'div',
    className: 'page',
    elementId: '',
    textLength: 0,
    linkTextLength: 0,
    role: undefined,
    children: [
      {
        id: 1,
        tag: 'nav',
        className: 'sidebar',
        elementId: '',
        textLength: 50,
        linkTextLength: 40,
        role: undefined,
        children: [],
      },
      {
        id: 2,
        tag: 'article',
        className: 'post',
        elementId: '',
        textLength: 500,
        linkTextLength: 20,
        role: undefined,
        children: [
          {
            id: 3,
            tag: 'h1',
            className: '',
            elementId: '',
            textLength: 30,
            linkTextLength: 0,
            role: undefined,
            children: [],
          },
          {
            id: 4,
            tag: 'p',
            className: '',
            elementId: '',
            textLength: 200,
            linkTextLength: 5,
            role: undefined,
            children: [],
          },
          {
            id: 5,
            tag: 'p',
            className: '',
            elementId: '',
            textLength: 300,
            linkTextLength: 10,
            role: undefined,
            children: [],
          },
        ],
      },
      {
        id: 6,
        tag: 'footer',
        className: 'footer',
        elementId: '',
        textLength: 30,
        linkTextLength: 25,
        role: undefined,
        children: [],
      },
    ],
  };
}

/** Build a page with no article (search results). */
function makeSearchPage(): NodeSummary {
  return {
    id: 0,
    tag: 'div',
    className: 'search-page',
    elementId: '',
    textLength: 0,
    linkTextLength: 0,
    role: undefined,
    children: [
      {
        id: 1,
        tag: 'div',
        className: 'result',
        elementId: '',
        textLength: 20,
        linkTextLength: 15,
        role: undefined,
        children: [],
      },
      {
        id: 2,
        tag: 'div',
        className: 'result',
        elementId: '',
        textLength: 15,
        linkTextLength: 12,
        role: undefined,
        children: [],
      },
    ],
  };
}

describe('findArticleRoot', () => {
  it('should find the article element when present and non-trivial', () => {
    const tree = makeArticleTree();
    const rootId = findArticleRoot(tree);
    expect(rootId).toBe(2); // the <article> node
  });

  it('should return null when no article content exists', () => {
    const tree = makeSearchPage();
    const rootId = findArticleRoot(tree);
    expect(rootId).toBeNull();
  });

  it('should short-circuit on <article> tag', () => {
    const tree = makeArticleTree();
    const rootId = findArticleRoot(tree);
    expect(rootId).toBe(2);
  });

  it('should handle an empty tree gracefully', () => {
    const empty: NodeSummary = {
      id: 0,
      tag: 'div',
      className: '',
      elementId: '',
      textLength: 0,
      linkTextLength: 0,
      role: undefined,
      children: [],
    };
    expect(findArticleRoot(empty)).toBeNull();
  });
});
