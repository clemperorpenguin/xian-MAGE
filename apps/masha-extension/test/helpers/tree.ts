/*
 * A NodeSummary builder that mirrors what the live-DOM walker actually
 * produces (entrypoints/content/walk.ts).
 *
 * This exists because the first round of fixtures encoded the *intended*
 * contract instead of the real one — containers reporting no text, textLength
 * measured over a different scope than linkTextLength — and so the suites went
 * green over two bugs that made page translation unusable. Anything that
 * changes walk.ts's output shape has to change here too.
 */

import { NodeSummary, commaCount } from '../../src/core/dom/tree';
import { DEFAULT_SEGMENT_POLICY } from '../../src/core/segment';

/** Tags the walker refuses to look inside. Mirrors walk.ts's SKIP_TAGS. */
const SKIP_TAGS = new Set([
  'script', 'style', 'svg', 'math', 'code', 'pre', 'kbd', 'samp', 'var', 'masha-tr',
]);

/** A page fragment, written the way the markup reads. */
export interface FixtureNode {
  tag: string;
  /** Text this element contributes directly (not via children). */
  text?: string;
  className?: string;
  elementId?: string;
  role?: string;
  children?: FixtureNode[];
}

export interface Fixture {
  root: NodeSummary;
  /** The node table the content script hands to toSegments. */
  textOf: (id: number) => string;
  /** Node id by tag — for asserting which element a segment came from. */
  ids: Map<string, number[]>;
}

/** Text of a fragment and everything under it, as `Element.textContent` sees it. */
function subtreeText(node: FixtureNode): string {
  const own = node.text ?? '';
  const below = (node.children ?? []).map(subtreeText).join('');
  return own + below;
}

/** Text inside <a> descendants, matching the walker's querySelectorAll('a'). */
function linkText(node: FixtureNode): string {
  if (node.tag === 'a') return subtreeText(node).trim();
  return (node.children ?? []).map(linkText).join('');
}

/** Build the tree and node table a walk of this fragment would produce. */
export function buildFixture(fragment: FixtureNode): Fixture {
  const table = new Map<number, string>();
  const ids = new Map<string, number[]>();
  let nextId = 0;

  function build(node: FixtureNode): NodeSummary {
    const id = nextId++;
    ids.set(node.tag, [...(ids.get(node.tag) ?? []), id]);

    if (SKIP_TAGS.has(node.tag)) {
      table.set(id, '');
      return {
        id,
        tag: node.tag,
        role: node.role,
        className: '',
        elementId: '',
        textLength: 0,
        linkTextLength: 0,
        commas: 0,
        children: [],
      };
    }

    const text = subtreeText(node).trim();
    const children = (node.children ?? []).map(build);
    table.set(id, text);

    return {
      id,
      tag: node.tag,
      role: node.role,
      className: node.className ?? '',
      elementId: node.elementId ?? '',
      // Subtree-inclusive, exactly as the walker measures it — and measured
      // over the same subtree as linkTextLength, or link density is nonsense.
      textLength: text.length,
      linkTextLength: linkText(node).length,
      commas: commaCount(text),
      children,
    };
  }

  const root = build(fragment);
  return { root, textOf: (id: number) => table.get(id) ?? '', ids };
}

/** Sentence-shaped filler of roughly `chars` characters. */
export function prose(chars: number): string {
  const sentence = 'The rain in Spain falls mainly on the plain, they say. ';
  return sentence.repeat(Math.ceil(chars / sentence.length)).slice(0, chars);
}

export { DEFAULT_SEGMENT_POLICY };
