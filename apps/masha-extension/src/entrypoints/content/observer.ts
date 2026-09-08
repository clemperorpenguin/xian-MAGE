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
 * Content-script side — MutationObserver for dynamic pages.
 *
 * Watches the article root (or document.body) for new nodes added by
 * infinite-scroll feeds and SPA route changes, and feeds them through the
 * same segmentation pipeline.
 *
 * Guard: MASHA's own <masha-tr> insertions are filtered out of the observer's
 * records — an observer that reacts to its own writes is an infinite loop.
 */

import { walkPage, getNodeText, WalkResult } from './walk';
import { toSegments, Segment } from '../../core/segment';

export type NewSegmentsCallback = (segments: Segment[]) => void;

const OBSERVER_DEBOUNCE_MS = 400;

/**
 * Create a MutationObserver that watches for new translatable content.
 *
 * @param root - The element to observe (defaults to document.body).
 * @param callback - Called with new segments after debounce.
 * @returns A function to stop observing.
 */
export function observePage(
  root?: Element,
  callback?: NewSegmentsCallback,
): () => void {
  const target = root || document.body;
  let debounceTimer: ReturnType<typeof setTimeout> | null = null;
  let lastKnownLength = 0;

  const observer = new MutationObserver((records) => {
    // Filter out mutations from MASHA's own injections
    const relevant = records.filter(record => {
      // Skip if the mutation involves a <masha-tr> element
      if (record.target instanceof Element && record.target.tagName === 'MASHA-TR') {
        return false;
      }
      // Skip additions that are masha-tr elements
      if (record.type === 'childList') {
        for (const node of record.addedNodes) {
          if (node instanceof Element && node.tagName === 'MASHA-TR') {
            return false;
          }
        }
      }
      return true;
    });

    if (relevant.length === 0) return;

    // Debounce
    if (debounceTimer) clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => {
      debounceTimer = null;

      // Walk the page again and find new segments
      const walkResult = walkPage();
      const segments = toSegments(
        walkResult.root,
        (id) => getNodeText(walkResult.nodeTable, id),
      );

      // Filter to only new segments (those not seen before)
      const newSegments = segments.filter(s => {
        const source = document.querySelector(`[data-masha-id="${s.id}"]`);
        return !source;
      });

      if (newSegments.length > 0 && callback) {
        callback(newSegments);
      }
    }, OBSERVER_DEBOUNCE_MS);
  });

  observer.observe(target, {
    childList: true,
    subtree: true,
    characterData: false, // don't care about text changes
  });

  return () => {
    observer.disconnect();
    if (debounceTimer) clearTimeout(debounceTimer);
  };
}
