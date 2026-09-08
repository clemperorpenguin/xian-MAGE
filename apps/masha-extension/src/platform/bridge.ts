/*
 * Masha — Browser extension selection translator.
 * Copyright (C) 2026  Clementine Pendragon <clem@pendragon.systems>
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with this program.  If not, see <https://www.gnu.org/licenses/>.
 *
 * Contact: clem@pendragon.systems (Clementine Pendragon, c/o Xian Project Development)
 */

/*
 * The platform seam. Everything browser-specific lives behind this interface;
 * the browser-free `core/` knows nothing about it. A future Falkon plugin
 * reimplements ONLY this contract in Python (PyFalkon settings, its context-menu
 * hook, QWebEngine JS injection). See docs/FALKON.md.
 */

import { DEFAULT_LEMONADE_URL, DEFAULT_SOURCE_LANG, DEFAULT_TARGET_LANG } from '../core/constants';

/** Persisted user configuration. */
export interface MashaConfig {
  /** OpenAI-compatible Lemonade base URL (normalized to end in ``/v1``). */
  serverUrl: string;
  /** ``"Auto"`` or an explicit source language name. */
  sourceLang: string;
  targetLang: string;
  /** The model to use for translation (default Xian-Ultra). */
  model?: string;
  /** Optional stylistic register terms. */
  styles: string[];
}

export const DEFAULT_CONFIG: MashaConfig = {
  serverUrl: DEFAULT_LEMONADE_URL,
  sourceLang: DEFAULT_SOURCE_LANG,
  targetLang: DEFAULT_TARGET_LANG,
  model: undefined,
  styles: [],
};

/** A captured selection plus the surrounding page context for the model. */
export interface SelectionContext {
  /** The text to translate. */
  text: string;
  /** Surrounding page text (title + section), reference only. */
  context: string;
  /** True when the selection lives in an editable <input>/<textarea>. */
  isEditable: boolean;
}

export interface TranslationOutcome {
  selection: string;
  translation: string;
  /** Editable selections are replaced in place; others use the overlay. */
  isEditable: boolean;
}

/** Outcome for a page-level translation (bilingual page mode). */
export interface PageTranslationOutcome {
  /** Total segments translated. */
  segmentCount: number;
  /** Number of segments that succeeded. */
  successCount: number;
}

/**
 * The full surface a platform must provide. Implement this once per platform
 * (WXT for Chrome/Firefox today; PyFalkon later) and the rest is reused.
 */
export interface PlatformBridge {
  /** Load persisted config, falling back to {@link DEFAULT_CONFIG}. */
  getConfig(): Promise<MashaConfig>;
  setConfig(config: Partial<MashaConfig>): Promise<void>;

  /** Register the user-facing trigger (context-menu entry / hotkey). */
  onTranslateCommand(handler: () => void | Promise<void>): void;

  /** Capture the current selection and surrounding page context. */
  getSelectionContext(): SelectionContext | null;

  /** Show a non-destructive overlay near the selection (read-only text). */
  showOverlay(outcome: TranslationOutcome): void;
  /** Show a transient error near the selection. */
  showError(message: string): void;

  /** Replace the selection in place (editable inputs only). */
  replaceSelection(text: string): void;

  // --- M1: Bilingual pages ---

  /** Walk the live DOM and return a serialisable node tree + text table. */
  getPageTree(): Promise<{ root: any; nodeTable: Map<number, string> }>;

  /**
   * Translate the current page and inject bilingual <masha-tr> elements.
   * Returns after all segments have been processed.
   */
  translatePage(config: MashaConfig): Promise<PageTranslationOutcome>;

  /** Remove all injected translations and restore original DOM. */
  undoPageTranslation(): Promise<void>;

  // --- M2: Hover + Compose ---

  /** Attach hover-to-translate listeners (passive, throttled). */
  attachHover(config?: { mode: string; dwellMs: number }): Promise<() => void>;
  /** Attach compose trigger (triple-space). */
  attachCompose(config?: { enabled: boolean; targetLang: string }): Promise<() => void>;

  // --- M3: Site profiles ---

  /** Get the matching site profile for the current URL, or null. */
  getSiteProfile(): Promise<{ profile: any | null }>;

  // --- M4: Subtitles ---

  /** Attach subtitle translation to video elements with text tracks. */
  attachTrackSubtitles(): Promise<() => void>;
  /** Attach audio-capture subtitle translation (basic, opt-in). */
  attachAudioSubtitles(serverUrl: string, targetLang: string): Promise<() => void>;

  // --- M5: Images + Comics ---

  /** Translate text in a single image via OCR + LLM. */
  translateImage(imgSrc: string, mode: 'text' | 'comic'): Promise<void>;
  /** Attach comic reader (scroll-triggered image translation). */
  attachComicReader(): Promise<() => void>;

  // --- M6: Documents ---

  /** Start a document translation job. */
  startDocumentJob(file: Blob, filename: string): Promise<{ jobId: string }>;
  /** Poll a document job's status. */
  getDocumentStatus(jobId: string): Promise<{ status: string; progress: number }>;

  // --- M7: Glossary + Cache ---

  /** Load the shared glossary (from bridge + user overrides). */
  getGlossary(): Promise<Record<string, string>>;
  /** Add or update a glossary entry. */
  setGlossaryEntry(source: string, target: string): Promise<void>;
  /** Look up a translation in the shared cache. */
  cacheLookup(sourceText: string, sourceLang: string, targetLang: string): Promise<string | null>;
  /** Store translations in the shared cache. */
  cacheStore(entries: Array<{ sourceText: string; translated: string }>): Promise<void>;
}
