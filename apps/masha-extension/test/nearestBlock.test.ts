/*
 * Tests for nearestTranslatableBlock.
 *
 * Browser-free core test.
 */

import { describe, it, expect } from 'vitest';
import { nearestTranslatableBlock } from '../src/core/nearestBlock';
import { NodeSummary } from '../src/core/dom/tree';

function makeTree(): NodeSummary {
  return {
    id: 0,
    tag: 'div',
    className: '',
    elementId: '',
    textLength: 0,
    linkTextLength: 0,
    commas: 0,
    children: [
      {
        id: 1,
        tag: 'nav',
        className: '',
        elementId: '',
        textLength: 10,
        linkTextLength: 10,
        commas: 0,
        children: [],
      },
      {
        id: 3,
        tag: 'article',
        className: '',
        elementId: '',
        textLength: 200,
        linkTextLength: 10,
        commas: 5,
        children: [
          {
            id: 2,
            tag: 'a',
            className: '',
            elementId: '',
            textLength: 5,
            linkTextLength: 5,
            commas: 0,
            children: [],
          },
          {
            id: 4,
            tag: 'p',
            className: '',
            elementId: '',
            textLength: 100,
            linkTextLength: 0,
            commas: 2,
            children: [],
          },
          {
            id: 5,
            tag: 'code',
            className: '',
            elementId: '',
            textLength: 50,
            linkTextLength: 0,
            commas: 0,
            children: [],
          },
        ],
      },
    ],
  };
}

describe('nearestTranslatableBlock', () => {
  const skipTags = new Set(['code', 'pre', 'kbd', 'samp', 'var', 'script', 'style', 'svg', 'math']);
  const tree = makeTree();

  it('should find the paragraph from a paragraph node', () => {
    const result = nearestTranslatableBlock(tree, 4, 3, skipTags);
    expect(result).not.toBeNull();
    expect(result!.id).toBe(4);
  });

  it('should return null for code nodes', () => {
    const result = nearestTranslatableBlock(tree, 5, 3, skipTags);
    expect(result).toBeNull();
  });

  it('should walk up to article from a nav link', () => {
    const result = nearestTranslatableBlock(tree, 2, 3, skipTags);
    expect(result).not.toBeNull();
    // The nav itself has textLength 10 but it's short; article has 200
    expect(result!.id).toBe(3);
  });

  it('should return null for nodes with insufficient text', () => {
    // Nav has only 10 chars of text
    const result = nearestTranslatableBlock(tree, 1, 50, skipTags);
    expect(result).toBeNull();
  });
});
