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
    currentTarget = target;

    // Debounce: wait for dwell before translating
    dwellTimer = setTimeout(() => {
      if (!currentTarget) return;
      const block = findTranslatableAncestor(currentTarget);
      if (!block) return;

      // Signal the background to translate this single block
      // (reuses the page-translation pipeline with one segment)
      chrome.runtime.sendMessage({
        type: 'MASHA_HOVER_TRANSLATE',
        nodeId: block.dataset.mashaNodeId || block.id || '',
        text: block.textContent || '',
      });
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
  };
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
