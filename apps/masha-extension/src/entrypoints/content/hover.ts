/*
 * M2 — Hover-to-translate.
 *
 * Listens for mouseover, finds the nearest block-level ancestor that
 * segmentation would accept, and injects a translation on dwell.
 *
 * Bridge side (DOM + messaging).  Core policy lives in core/nearestBlock.ts.
 */

import { PlatformBridge } from '../../platform/bridge';

export interface HoverConfig {
  mode: 'off' | 'hover' | 'shift' | 'alt' | 'ctrl';
  dwellMs: number;          // 300
}

/** What to do with a translation once it comes back. */
export type HoverRenderer = (block: HTMLElement, translation: string) => void;

export const DEFAULT_HOVER_CONFIG: HoverConfig = {
  mode: 'off',
  dwellMs: 300,
};

/**
 * Attach hover listeners to the page.
 *
 * Returns an undo function that removes the listeners.
 */
export function attachHover(
  bridge: PlatformBridge,
  config: HoverConfig = DEFAULT_HOVER_CONFIG,
  render: HoverRenderer = showBubble,
): () => void {
  if (config.mode === 'off') return () => {};

  let dwellTimer: ReturnType<typeof setTimeout> | null = null;
  let currentTarget: HTMLElement | null = null;

  function isModifierHeld(e: MouseEvent): boolean {
    switch (config.mode) {
      case 'shift': return e.shiftKey;
      case 'alt':   return e.altKey;
      case 'ctrl':  return e.ctrlKey;
      default:      return true; // 'hover' — no modifier needed
    }
  }

  function onMouseOver(e: MouseEvent) {
    if (!isModifierHeld(e)) {
      clearDwell();
      return;
    }

    const target = e.target as HTMLElement;
    if (target === currentTarget) return;

    // Drop the timer queued for the element the pointer just left. Without
    // this a single mouse sweep leaves one pending timer per element it
    // crossed, and every one of them fires a translation request.
    clearDwell();
    currentTarget = target;

    // Debounce: wait for dwell before translating
    dwellTimer = setTimeout(() => {
      dwellTimer = null;
      const block = findTranslatableAncestor(target);
      if (!block) return;

      // Signal the background to translate this single block
      // (reuses the page-translation pipeline with one segment)
      chrome.runtime.sendMessage(
        {
          type: 'MASHA_HOVER_TRANSLATE',
          nodeId: block.dataset.mashaNodeId || block.id || '',
          text: block.textContent || '',
        },
        (response) => {
          // Reading lastError is what stops Chrome logging an unchecked error
          // when the background went away mid-flight.
          if (chrome.runtime.lastError) return;
          if (target !== currentTarget) return;   // pointer has moved on
          if (response?.success && response.translation) {
            render(block, response.translation);
          }
        },
      );
    }, config.dwellMs);
  }

  function clearDwell() {
    if (dwellTimer) {
      clearTimeout(dwellTimer);
      dwellTimer = null;
    }
    currentTarget = null;
  }

  document.addEventListener('mouseover', onMouseOver as EventListener);

  return () => {
    document.removeEventListener('mouseover', onMouseOver as EventListener);
    clearDwell();
    removeBubble();
  };
}

const BUBBLE_ID = 'masha-hover-bubble';

function removeBubble(): void {
  document.getElementById(BUBBLE_ID)?.remove();
}

/**
 * Default renderer: a floating bubble pinned under the hovered block.
 *
 * Only one is ever on the page — a new translation replaces the last.
 */
function showBubble(block: HTMLElement, translation: string): void {
  removeBubble();

  const rect = block.getBoundingClientRect();
  const bubble = document.createElement('div');
  bubble.id = BUBBLE_ID;
  bubble.textContent = translation;
  bubble.style.cssText = `
    position: absolute; z-index: 2147483647;
    left: ${rect.left + window.scrollX}px;
    top: ${rect.bottom + window.scrollY + 4}px;
    max-width: ${Math.max(rect.width, 240)}px;
    padding: 6px 8px; border-radius: 4px;
    background: rgba(20, 20, 20, 0.92); color: #fff;
    font: 14px/1.4 system-ui, sans-serif;
    pointer-events: none;
  `;
  document.body.appendChild(bubble);
}

/**
 * Walk up from `el` to the nearest block-level ancestor with meaningful text.
 */
function findTranslatableAncestor(el: HTMLElement): HTMLElement | null {
  let current = el;
  const SKIP_TAGS = new Set(['code', 'pre', 'kbd', 'samp', 'var', 'script', 'style', 'svg', 'math']);

  while (current) {
    if (SKIP_TAGS.has(current.tagName.toLowerCase())) return null;
    const text = current.textContent || '';
    if (text.trim().length >= 3) return current;
    current = current.parentElement as HTMLElement;
  }

  return null;
}
