/*
 * M2 — Compose: triple-space trigger for input/textarea/[contenteditable].
 *
 * Bridge side (DOM + messaging).  Core trigger state machine in
 * core/compose/state.ts.
 */

import { ComposeState, composeTrigger, INITIAL_STATE, DEFAULT_COMPOSE_CONFIG as CORE_DEFAULT_COMPOSE_CONFIG, ComposeTriggerConfig } from '../../core/compose/state';

export interface ComposeConfig {
  enabled: boolean;
  trigger: ComposeTriggerConfig;
  targetLang: string;       // May differ from reading target
}

export const DEFAULT_COMPOSE_CONFIG: ComposeConfig = {
  enabled: false,
  trigger: CORE_DEFAULT_COMPOSE_CONFIG,
  targetLang: 'English',
};

/**
 * Attach keydown listener to editable elements.
 *
 * Returns an undo function.
 */
export function attachCompose(
  config: ComposeConfig = DEFAULT_COMPOSE_CONFIG,
  onTranslate: (text: string, targetLang: string) => Promise<string>,
): () => void {
  if (!config.enabled) return () => {};

  let state: ComposeState = INITIAL_STATE;

  const EDITOR_SELECTORS = 'input:not([type]), input[type="text"], input[type="search"], textarea, [contenteditable]';

  function onKeyDown(e: KeyboardEvent) {
    const target = e.target as HTMLElement;
    if (!target.matches(EDITOR_SELECTORS)) return;

    const result = composeTrigger(state, e.key, performance.now(), config.trigger);
    state = result.state;

    if (result.fired) {
      e.preventDefault();

      const value = getEditorValue(target);
      if (!value.trim()) return;

      // Remove the three trailing spaces that triggered
      const cleaned = value.replace(/   +$/, '');
      setEditorValue(target, cleaned);

      onTranslate(cleaned, config.targetLang)
        .then(translated => {
          replaceWithTranslation(target, cleaned, translated);
        })
        .catch(() => {
          // Restore original on failure
          setEditorValue(target, value);
        });
    }
  }

  document.addEventListener('keydown', onKeyDown);

  return () => {
    document.removeEventListener('keydown', onKeyDown);
  };
}

function getEditorValue(el: HTMLElement): string {
  if (el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement) {
    return el.value;
  }
  return el.textContent || '';
}

function setEditorValue(el: HTMLElement, value: string): void {
  if (el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement) {
    el.value = value;
  } else {
    el.textContent = value;
  }
}

function replaceWithTranslation(el: HTMLElement, original: string, translated: string): void {
  // Use execCommand for undo-stack compatibility where available
  if (el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement) {
    el.value = translated;
    // Dispatch input event so React/Vue see the change
    el.dispatchEvent(new Event('input', { bubbles: true, cancelable: true }));
  } else if (el.isContentEditable) {
    const sel = window.getSelection();
    if (sel) {
      sel.selectAllChildren(el);
      document.execCommand('insertText', false, translated);
    }
  }
}
