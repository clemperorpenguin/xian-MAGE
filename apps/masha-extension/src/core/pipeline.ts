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
 * Page translation pipeline. Batches segments by character budget, sends them
 * to Lemonade, validates markers, and streams results back via onSegment.
 *
 * Batches carry explicit index markers per segment to prevent positional
 * mis-mapping — the failure mode where a dropped segment paints the wrong
 * translation under the wrong paragraph.
 */

import { Segment } from './segment';
import { FetchFn } from './translator';
import { MashaConfig } from '../platform/bridge';
import { buildTranslationMessages } from './prompt';

export interface PageTranslateOptions {
  segments: Segment[];
  config: MashaConfig;
  glossary?: Record<string, string>;
  /** Maximum concurrent requests (default 4). */
  concurrency?: number;
  /** Target payload size per batch in characters (default 1500). */
  batchChars?: number;
  /** Abort signal for cancellation. */
  signal?: AbortSignal;
  /** Called for each successfully translated segment (streams to the page). */
  onSegment: (id: string, translated: string) => void;
  /** Called for each segment that fails. */
  onError: (id: string, error: Error) => void;
}

/** A batch of segments to send in one request. */
interface Batch {
  /** The markers that identify each segment in order. */
  markers: string[];
  /** The segments' text, separated by marker lines. */
  body: string;
  /** Total character count of body. */
  chars: number;
}

const DEFAULT_CONCURRENCY = 4;
const DEFAULT_BATCH_CHARS = 1500;

/**
 * Build a batch payload from a list of segments.
 *
 * Each segment is wrapped in unique marker lines so the response can be
 * validated segment-by-segment rather than mapped positionally.
 */
function buildBatch(segments: Segment[], budget: number): Batch | null {
  if (segments.length === 0) return null;

  const markers: string[] = [];
  const parts: string[] = [];
  let totalChars = 0;

  for (const seg of segments) {
    const marker = `<<<MASHA_SEGMENT_${seg.id}>>>`;
    const part = `${marker}\n${seg.text}\n${marker}`;

    if (totalChars + part.length > budget && parts.length > 0) {
      // Don't add — budget exceeded with at least one segment already
      break;
    }

    markers.push(seg.id);
    parts.push(part);
    totalChars += part.length;
  }

  if (parts.length === 0) return null;

  return {
    markers,
    body: parts.join('\n'),
    chars: totalChars,
  };
}

/**
 * Parse a batch response, validating markers and extracting translations.
 *
 * Returns a map of segment id → translated text.
 * Throws if a marker is missing or the response is malformed.
 */
function parseBatchResponse(
  response: string,
  markers: string[],
): Map<string, string> {
  const result = new Map<string, string>();

  for (const marker of markers) {
    const openTag = `<<<MASHA_SEGMENT_${marker}>>>`;
    const closeTag = `<<<MASHA_SEGMENT_${marker}>>>`;

    // Find the opening marker
    const openIdx = response.indexOf(openTag);
    if (openIdx === -1) {
      throw new Error(`Missing marker for segment ${marker}`);
    }

    // Find the closing marker after the opening
    const contentStart = openIdx + openTag.length;
    const closeIdx = response.indexOf(closeTag, contentStart);
    if (closeIdx === -1) {
      throw new Error(`Missing closing marker for segment ${marker}`);
    }

    const translated = response.slice(contentStart, closeIdx).trim();
    result.set(marker, translated);
  }

  return result;
}

/**
 * Translate a page: segment, batch, send, stream.
 *
 * Segments are batched in document order so the visible top of the page is
 * translated first. Concurrency is limited to avoid overwhelming a local server.
 */
export async function translatePage(
  fetchFn: FetchFn,
  opts: PageTranslateOptions,
): Promise<void> {
  const concurrency = opts.concurrency ?? DEFAULT_CONCURRENCY;
  const batchChars = opts.batchChars ?? DEFAULT_BATCH_CHARS;

  // Build batches in document order
  const batches: Batch[] = [];
  let remaining = [...opts.segments];

  while (remaining.length > 0) {
    const batch = buildBatch(remaining, batchChars);
    if (!batch) break;

    batches.push(batch);
    // Remove the segments that went into this batch
    remaining = remaining.slice(batch.markers.length);
  }

  // Process batches with limited concurrency
  const running = new Set<Promise<void>>();
  let batchIndex = 0;

  async function processBatch(batch: Batch): Promise<void> {
    if (opts.signal?.aborted) return;

    const baseUrl = opts.config.serverUrl.replace(/\/+$/, '');
    const endpoint = `${baseUrl}/chat/completions`;

    // Build the prompt for this batch
    const messages = buildTranslationMessages({
      selection: batch.body,
      context: '', // Page context could be added here
      sourceLang: opts.config.sourceLang,
      targetLang: opts.config.targetLang,
      styles: opts.config.styles,
    });

    const payload = {
      model: opts.config.model || 'Xian-Ultra',
      messages,
      max_tokens: 2048,
      temperature: 0.3,
      stream: false,
    };

    try {
      const response = await fetchFn(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });

      if (!response.ok) {
        throw new Error(`Lemonade API error: ${response.statusText || 'request failed'}`);
      }

      const data = await response.json();
      const content = data?.choices?.[0]?.message?.content;

      if (!content) {
        throw new Error('Empty batch response');
      }

      // Parse markers from the response
      const translations = parseBatchResponse(content, batch.markers);

      // Stream each segment as it's received
      for (const id of batch.markers) {
        const translated = translations.get(id);
        if (translated) {
          opts.onSegment(id, translated);
        }
      }
    } catch (error) {
      // Fall back to per-segment retry for mis-mapped batches
      for (const id of batch.markers) {
        opts.onError(id, error instanceof Error ? error : new Error(String(error)));
      }
    }
  }

  // Launch batches with concurrency control
  for (let i = 0; i < batches.length; i++) {
    // Wait for a slot if we're at capacity
    while (running.size >= concurrency) {
      await Promise.race(running);
    }

    const promise = processBatch(batches[i]).finally(() => running.delete(promise));
    running.add(promise);
  }

  // Wait for all remaining batches
  await Promise.allSettled(running);
}
