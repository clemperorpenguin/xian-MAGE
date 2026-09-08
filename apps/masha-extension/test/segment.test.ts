/*
 * Tests for page segmentation.
 *
 * Browser-free — operates on plain text and NodeSummary fixtures.
 */

import { describe, it, expect } from 'vitest';
import { shouldTranslate, splitLongBlock, toSegments, SegmentPolicy, DEFAULT_SEGMENT_POLICY } from '../src/core/segment';
import { NodeSummary } from '../src/core/dom/tree';

describe('shouldTranslate', () => {
  it('should skip text shorter than minChars', () => {
    expect(shouldTranslate('OK', { ...DEFAULT_SEGMENT_POLICY, minChars: 3 })).toBe(false);
    expect(shouldTranslate('Hi', { ...DEFAULT_SEGMENT_POLICY, minChars: 3 })).toBe(false);
  });

  it('should accept text longer than minChars', () => {
    expect(shouldTranslate('Hello world', { ...DEFAULT_SEGMENT_POLICY, minChars: 3 })).toBe(true);
  });

  it('should skip numeric text when skipIfNumeric is true', () => {
    expect(shouldTranslate('2024', { ...DEFAULT_SEGMENT_POLICY, skipIfNumeric: true })).toBe(false);
    expect(shouldTranslate('3.14', { ...DEFAULT_SEGMENT_POLICY, skipIfNumeric: true })).toBe(false);
    expect(shouldTranslate('$19.99', { ...DEFAULT_SEGMENT_POLICY, skipIfNumeric: true })).toBe(false);
  });

  it('should translate text with numbers and letters', () => {
    expect(shouldTranslate('Page 42 of the report', { ...DEFAULT_SEGMENT_POLICY, skipIfNumeric: true })).toBe(true);
  });
});

describe('splitLongBlock', () => {
  it('should return a single chunk for short text', () => {
    const result = splitLongBlock('Short text.', 1200);
    expect(result).toEqual(['Short text.']);
  });

  it('should split a long block at sentence boundaries', () => {
    const long = 'This is the first sentence. This is the second sentence. And this is the third.';
    const result = splitLongBlock(long, 40);
    expect(result.length).toBeGreaterThan(1);
    expect(result.join('').length).toBeLessThanOrEqual(long.length);
  });

  it('should force-split if no sentence boundaries exist', () => {
    const long = 'a'.repeat(2000);
    const result = splitLongBlock(long, 500);
    expect(result.length).toBe(4); // 2000 / 500 = 4
  });
});

describe('toSegments', () => {
  it('should skip code tags', () => {
    const tree: NodeSummary = {
      id: 0,
      tag: 'div',
      className: '',
      elementId: '',
      textLength: 0,
      linkTextLength: 0,
      role: undefined,
      children: [
        {
          id: 1,
          tag: 'code',
          className: '',
          elementId: '',
          textLength: 50,
          linkTextLength: 0,
          role: undefined,
          children: [],
        },
        {
          id: 2,
          tag: 'p',
          className: '',
          elementId: '',
          textLength: 100,
          linkTextLength: 0,
          role: undefined,
          children: [],
        },
      ],
    };

    const textFn = (id: number) => {
      if (id === 1) return 'const x = 1;';
      if (id === 2) return 'This is a real paragraph.';
      return '';
    };

    const segments = toSegments(tree, textFn);
    expect(segments.length).toBe(1); // only the <p>
    expect(segments[0].text).toBe('This is a real paragraph.');
  });

  it('should preserve document order', () => {
    const tree: NodeSummary = {
      id: 0,
      tag: 'div',
      className: '',
      elementId: '',
      textLength: 0,
      linkTextLength: 0,
      role: undefined,
      children: [
        {
          id: 1,
          tag: 'p',
          className: '',
          elementId: '',
          textLength: 50,
          linkTextLength: 0,
          role: undefined,
          children: [],
        },
        {
          id: 2,
          tag: 'p',
          className: '',
          elementId: '',
          textLength: 60,
          linkTextLength: 0,
          role: undefined,
          children: [],
        },
      ],
    };

    const textFn = (id: number) => {
      if (id === 1) return 'First paragraph.';
      if (id === 2) return 'Second paragraph.';
      return '';
    };
    const segments = toSegments(tree, textFn);
    expect(segments.length).toBe(2);
    expect(segments[0].text).toBe('First paragraph.');
    expect(segments[1].text).toBe('Second paragraph.');
  });
});
