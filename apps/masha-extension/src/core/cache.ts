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
 * Browser-free core — see core/constants.ts.
 *
 * Three-tier translation cache:
 *   1. In-memory LRU (per tab, for the current page).
 *   2. chrome.storage.local LRU (~5 MB, persists across tabs/sessions).
 *   3. Shared with MAGE via the bridge (SQLite-backed, cross-application).
 *
 * The key is (text, sourceLang, targetLang). Excludes style and glossary;
 * those are versioned via cacheEpoch instead.
 */

export interface CacheEntry {
  sourceText: string;
  sourceLang: string;
  targetLang: string;
  translated: string;
  /** Epoch — style/glossary version; rows from an older epoch are ignored. */
  epoch: number;
}

/**
 * Simple LRU cache for in-memory use (Tier 1).
 */
export class LRUCache {
  private maxEntries: number;
  private entries: Map<string, CacheEntry> = new Map();

  constructor(maxEntries: number = 500) {
    this.maxEntries = maxEntries;
  }

  /** Build the cache key. */
  static key(text: string, sourceLang: string, targetLang: string): string {
    return `${text}|${sourceLang}|${targetLang}`;
  }

  /** Get an entry. Returns null on miss or epoch mismatch. */
  get(text: string, sourceLang: string, targetLang: string, epoch: number = 0): string | null {
    const key = LRUCache.key(text, sourceLang, targetLang);
    const entry = this.entries.get(key);
    if (!entry) return null;
    if (entry.epoch < epoch) return null; // stale
    // Move to front (LRU)
    this.entries.delete(key);
    this.entries.set(key, entry);
    return entry.translated;
  }

  /** Set an entry. Evicts LRU if over capacity. */
  set(entry: CacheEntry): void {
    const key = LRUCache.key(entry.sourceText, entry.sourceLang, entry.targetLang);
    this.entries.set(key, entry);

    if (this.entries.size > this.maxEntries) {
      const first = this.entries.keys().next().value;
      if (first) this.entries.delete(first);
    }
  }

  /** Current size. */
  get size(): number {
    return this.entries.size;
  }
}

/**
 * Tier 2 cache — wraps chrome.storage.local with LRU eviction.
 * This is a stub for the browser-free core; the actual storage integration
 * lives in the content script / background worker.
 */
export class PersistentCache {
  private memory: LRUCache;
  private epoch: number;

  constructor(maxEntries: number = 2000, epoch: number = 0) {
    this.memory = new LRUCache(maxEntries);
    this.epoch = epoch;
  }

  /** Get from memory (tier 1). */
  get(text: string, sourceLang: string, targetLang: string): string | null {
    return this.memory.get(text, sourceLang, targetLang, this.epoch);
  }

  /** Set in memory (tier 1). Will be persisted by the platform layer. */
  set(entry: CacheEntry): void {
    entry.epoch = this.epoch;
    this.memory.set(entry);
  }

  /** Update the cache epoch (invalidates all stale entries). */
  setEpoch(newEpoch: number): void {
    this.epoch = newEpoch;
  }
}
