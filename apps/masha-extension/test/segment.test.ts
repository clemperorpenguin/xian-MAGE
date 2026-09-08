/*
 * Tests for page segmentation.
 *
 * Browser-free — operates on plain text and on NodeSummary fixtures built by
 * test/helpers/tree.ts, which reproduces what the live-DOM walker emits.
 */

import { describe, it, expect } from 'vitest';
import {
  shouldTranslate,
  splitLongBlock,
  toSegments,
  segmentChunkIndex,
  segmentNodeId,
  DEFAULT_SEGMENT_POLICY,
} from '../src/core/segment';
import { buildFixture, prose } from './helpers/tree';

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

  it('should keep every chunk within maxChars', () => {
    // The old implementation only cut once a span already exceeded the budget
    // and then bailed out after two chunks, so the tail came back whole:
    // 10,500 chars at maxChars 1200 produced a final chunk of ~8,000.
    const long = prose(10_500);
    const result = splitLongBlock(long, 1200);

    expect(result.length).toBeGreaterThan(2);
    for (const chunk of result) {
      expect(chunk.length).toBeLessThanOrEqual(1200);
    }
  });

  it('should preserve the text across chunks', () => {
    const long = prose(5000);
    const rejoined = splitLongBlock(long, 900).join(' ').replace(/\s+/g, ' ').trim();
    expect(rejoined).toBe(long.replace(/\s+/g, ' ').trim());
  });
});

describe('toSegments', () => {
  it('should skip code tags', () => {
    const { root, textOf } = buildFixture({
      tag: 'div',
      children: [
        { tag: 'code', text: 'const x = 1;' },
        { tag: 'p', text: 'This is a real paragraph.' },
      ],
    });

    const segments = toSegments(root, textOf);
    expect(segments.length).toBe(1); // only the <p>
    expect(segments[0].text).toBe('This is a real paragraph.');
  });

  it('should preserve document order', () => {
    const { root, textOf } = buildFixture({
      tag: 'div',
      children: [
        { tag: 'p', text: 'First paragraph.' },
        { tag: 'p', text: 'Second paragraph.' },
      ],
    });

    const segments = toSegments(root, textOf);
    expect(segments.length).toBe(2);
    expect(segments[0].text).toBe('First paragraph.');
    expect(segments[1].text).toBe('Second paragraph.');
  });

  it('should emit only the innermost block, never its ancestors', () => {
    // The walker's node table holds each element's *whole subtree* text, so an
    // implementation that emits every node sends this paragraph four times —
    // once for the body, the div, the p and the span — and bills for each.
    const { root, textOf } = buildFixture({
      tag: 'body',
      children: [
        {
          tag: 'div',
          children: [{ tag: 'p', children: [{ tag: 'span', text: 'Hello world, this is prose.' }] }],
        },
      ],
    });

    const segments = toSegments(root, textOf);
    expect(segments.length).toBe(1);
    expect(segments[0].text).toBe('Hello world, this is prose.');
  });

  it('should keep inline markup with its paragraph', () => {
    const { root, textOf } = buildFixture({
      tag: 'p',
      text: 'A sentence with ',
      children: [
        { tag: 'em', text: 'emphasis' },
        { tag: 'span', text: ' and a tail.' },
      ],
    });

    const segments = toSegments(root, textOf);
    expect(segments.length).toBe(1);
    expect(segments[0].text).toBe('A sentence with emphasis and a tail.');
  });

  it('should segment each list item separately', () => {
    const { root, textOf } = buildFixture({
      tag: 'ul',
      children: [
        { tag: 'li', text: 'First item of the list.' },
        { tag: 'li', text: 'Second item of the list.' },
      ],
    });

    const segments = toSegments(root, textOf);
    expect(segments.map(s => s.text)).toEqual([
      'First item of the list.',
      'Second item of the list.',
    ]);
    expect(segments.every(s => s.kind === 'listitem')).toBe(true);
  });

  it('should classify headings', () => {
    const { root, textOf } = buildFixture({
      tag: 'article',
      children: [
        { tag: 'h1', text: 'The headline goes here' },
        { tag: 'p', text: 'And the body follows it.' },
      ],
    });

    const segments = toSegments(root, textOf);
    expect(segments.map(s => s.kind)).toEqual(['heading', 'block']);
  });

  it('should chunk a block longer than maxChars into ordered segments', () => {
    const { root, textOf } = buildFixture({ tag: 'p', text: prose(3000) });

    const segments = toSegments(root, textOf, { ...DEFAULT_SEGMENT_POLICY, maxChars: 1000 });

    expect(segments.length).toBeGreaterThan(1);
    for (const segment of segments) {
      expect(segment.text.length).toBeLessThanOrEqual(1000);
    }
    // Chunks share one node and one text hash, and carry their order in the id.
    const nodeIds = new Set(segments.map(s => segmentNodeId(s.id)));
    expect(nodeIds.size).toBe(1);
    expect(segments.map(s => segmentChunkIndex(s.id))).toEqual(segments.map((_, i) => i));
  });
});

describe('segment ids', () => {
  it('should carry the node id through to the injector', () => {
    const { root, textOf, ids } = buildFixture({
      tag: 'div',
      children: [{ tag: 'p', text: 'A paragraph worth translating.' }],
    });

    const [segment] = toSegments(root, textOf);
    expect(segmentNodeId(segment.id)).toBe(ids.get('p')![0]);
    expect(segmentChunkIndex(segment.id)).toBe(0);
  });

  it('should change when the text changes, so an edited block is re-sent', () => {
    const before = buildFixture({ tag: 'p', text: 'The original sentence.' });
    const after = buildFixture({ tag: 'p', text: 'The edited sentence.' });

    const [first] = toSegments(before.root, before.textOf);
    const [second] = toSegments(after.root, after.textOf);

    expect(segmentNodeId(first.id)).toBe(segmentNodeId(second.id));
    expect(first.id).not.toBe(second.id);
  });
});
