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
 * Content-script side — injects translations into the page.
 *
 * Each translation is inserted as a custom <masha-tr> element with a shadow
 * root, so the site's CSS cannot restyle the translation and MASHA's CSS
 * cannot leak onto the site.
 *
 * Idempotent: re-running skips what is already done. Undo removes all
 * <masha-tr> elements and strips data-masha-id attributes.
 */

const SHADOW_STYLE = `
  :host {
    display: block;
    margin: 0;
    padding: 4px 0;
  }
  :host([dir="rtl"]) {
    direction: rtl;
    text-align: right;
  }
  :host([dir="ltr"]) {
    direction: ltr;
    text-align: left;
  }
  .masha-tr-content {
    font-size: inherit;
    font-family: inherit;
    line-height: inherit;
    color: #1e293b;
    background: #f1f5f9;
    border-radius: 4px;
    padding: 2px 6px;
    display: inline-block;
    max-width: 100%;
    word-wrap: break-word;
  }
`;

/** CSS injected into the page for <masha-tr> elements. */
const PAGE_STYLE = `
  masha-tr {
    display: block;
    contain: content;
    isolation: isolate;
  }
`;

let styleInjected = false;

/** Inject the page-level style once. */
function ensurePageStyle(): void {
  if (styleInjected) return;
  const style = document.createElement('style');
  style.textContent = PAGE_STYLE;
  document.head.appendChild(style);
  styleInjected = true;
}

/**
 * Inject a translation for a single segment.
 *
 * Creates a <masha-tr> shadow-rooted element right after the source element,
 * and copies display from the source so a translated <li> still sits in the list.
 *
 * @param sourceSelector - CSS selector for the source element (e.g. [data-masha-id="42:9f3c"])
 * @param translatedText - The translated text to inject.
 * @param lang - BCP47 language tag for the translation.
 * @param dir - 'ltr' | 'rtl' direction.
 */
export function injectTranslation(
  sourceId: string,
  translatedText: string,
  lang: string = 'en',
  dir: 'ltr' | 'rtl' = 'ltr',
): void {
  ensurePageStyle();

  // Find the source element
  const source = document.querySelector(`[data-masha-id="${sourceId}"]`);
  if (!source) return;

  // Check if already translated
  const existing = source.nextElementSibling;
  if (existing?.tagName === 'MASHA-TR') return; // already done

  // Get the source's display property
  const display = getComputedStyle(source).display;

  // Create the custom element
  const tr = document.createElement('masha-tr');
  tr.setAttribute('data-masha-for', sourceId);
  tr.lang = lang;
  tr.dir = dir;

  // Shadow root
  const shadow = tr.attachShadow({ mode: 'closed' });

  // Apply styles
  const style = document.createElement('style');
  style.textContent = SHADOW_STYLE;
  shadow.appendChild(style);

  // Content wrapper
  const content = document.createElement('div');
  content.className = 'masha-tr-content';
  content.textContent = translatedText;
  shadow.appendChild(content);

  // Copy display from source
  tr.style.display = display;

  // Insert after the source element
  source.insertAdjacentElement('afterend', tr);
}

/**
 * Mark a source element as translated (sets data-masha-id).
 */
export function markSource(sourceId: string, element: Element): void {
  element.setAttribute('data-masha-id', sourceId);
}

/**
 * Remove all injected translations and strip source markers.
 */
export function undoAll(): void {
  document.querySelectorAll('masha-tr').forEach(n => n.remove());
  document.querySelectorAll('[data-masha-id]').forEach(n => n.removeAttribute('data-masha-id'));
}
