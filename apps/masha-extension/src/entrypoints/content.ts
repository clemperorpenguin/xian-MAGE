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
 * Content script (WXT) — the composition root for everything page-facing.
 *
 * It owns no behaviour of its own. Each feature lives in `content/`, is turned
 * on by a setting, and hands back a detach function; this file decides which
 * are on, routes the messages that arrive from the background, and re-applies
 * the set whenever the settings change.
 *
 * The model is never called from here. A content script's `fetch` is judged by
 * the page's CORS policy, not the extension's, so every request goes to the
 * background worker.
 */

import { getConfig } from '../utils/config';
import { MashaConfig } from '../platform/bridge';
import { attachComicReader } from './content/comic';
import { attachCompose } from './content/compose';
import { attachHover } from './content/hover';
import { translateImage, DEFAULT_IMAGE_CONFIG } from './content/images';
import {
  applySegment,
  isPageTranslated,
  translateCurrentPage,
  undoPageTranslation,
} from './content/page';
import { showError, showNotice, translateSelection } from './content/selection';
import { attachSubtitles } from './content/subtitles';

/** Translate a lone string through the background worker. */
async function translateText(text: string, targetLang?: string): Promise<string> {
  const response = await chrome.runtime.sendMessage({
    type: 'MASHA_TRANSLATE_TEXT',
    text,
    targetLang,
  });
  if (!response?.success) throw new Error(response?.error || 'Translation failed.');
  return response.translation as string;
}

export default defineContentScript({
  matches: ['<all_urls>'],
  main() {
    /** Detach functions for the features currently switched on. */
    let detachers: Array<() => void> = [];

    function detachFeatures(): void {
      for (const detach of detachers) {
        try {
          detach();
        } catch {
          // A feature that fails to clean up must not block the others.
        }
      }
      detachers = [];
    }

    /** Turn on exactly the features the settings ask for, and nothing else. */
    function attachFeatures(config: MashaConfig): void {
      detachFeatures();

      if (config.hoverMode !== 'off') {
        detachers.push(attachHover({ mode: config.hoverMode, dwellMs: 300 }));
      }

      if (config.composeEnabled) {
        detachers.push(attachCompose(
          {
            enabled: true,
            trigger: { windowMs: 900, trigger: 'triple-space' },
            targetLang: config.targetLang,
          },
          (text, targetLang) => translateText(text, targetLang),
        ));
      }

      if (config.subtitlesEnabled) {
        detachers.push(attachSubtitles(
          {
            serverUrl: config.serverUrl,
            asrModel: config.asrModel,
            audio: config.audioSubtitlesEnabled,
          },
          (text) => translateText(text),
        ));
      }

      if (config.comicsEnabled) {
        detachers.push(attachComicReader(
          { rtl: config.comicRtl, lookahead: 2 },
          {
            ...DEFAULT_IMAGE_CONFIG,
            mode: 'comic',
            sourceLang: config.sourceLang,
            targetLang: config.targetLang,
          },
        ));
      }
    }

    getConfig().then(attachFeatures);

    // The popup writes settings; every open tab picks them up without a reload.
    chrome.storage.onChanged.addListener((changes, area) => {
      if (area !== 'local' || !changes.config) return;
      getConfig().then(attachFeatures);
    });

    async function runPageTranslation(): Promise<void> {
      try {
        const { segmentCount, successCount } = await translateCurrentPage();
        if (segmentCount === 0) showNotice('Nothing on this page to translate.');
        else showNotice(`Translated ${successCount} of ${segmentCount} blocks.`);
      } catch (error) {
        showError(error instanceof Error ? error.message : 'Page translation failed.');
      }
    }

    async function runImageTranslation(src: string, config: MashaConfig): Promise<void> {
      try {
        await translateImage(src, {
          ...DEFAULT_IMAGE_CONFIG,
          mode: 'text',
          sourceLang: config.sourceLang,
          targetLang: config.targetLang,
        });
      } catch (error) {
        showError(error instanceof Error ? error.message : 'Image translation failed.');
      }
    }

    // Commands relayed from the background: the context menu, and the popup.
    chrome.runtime.onMessage.addListener((message: any, _sender, sendResponse) => {
      switch (message?.type) {
        case 'MASHA_TRIGGER':
          translateSelection();
          return false;

        case 'MASHA_PAGE_TRANSLATE':
          runPageTranslation();
          return false;

        case 'MASHA_PAGE_UNDO':
          undoPageTranslation();
          showNotice('Translations removed.');
          return false;

        case 'MASHA_PAGE_STATE':
          sendResponse({ translated: isPageTranslated() });
          return false;

        // One translated block, streamed while the rest of the page is still
        // in flight — this is what makes a long page fill in from the top.
        case 'MASHA_SEGMENT':
          applySegment(message.id, message.translated);
          return false;

        case 'MASHA_IMAGE_TRANSLATE':
          getConfig().then((config) => runImageTranslation(message.src, config));
          return false;

        default:
          return false;
      }
    });
  },
});
