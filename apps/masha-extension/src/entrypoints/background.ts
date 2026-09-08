/*
 * Background service worker (WXT).
 *
 * Owns everything that must live off the page: the context-menu triggers, the
 * Lemonade call, the bridge calls, and cross-origin image fetching. A content
 * script's own `fetch` is judged by the page's CORS policy rather than the
 * extension's, so this is the only place in MASHA that talks to the network.
 */

import { getConfig } from '../utils/config';
import { LRUCache } from '../core/cache';
import { translatePage } from '../core/pipeline';
import { Segment } from '../core/segment';
import { translate } from '../core/translator';
import { BridgeHealth, MashaConfig, SelectionContext } from '../platform/bridge';

const MENU_ID = 'masha-translate';
const IMAGE_MENU_ID = 'masha-translate-image';

// --- Message types ---
interface TranslateMessage {
  type: 'MASHA_TRANSLATE';
  payload: SelectionContext;
}

interface HoverMessage {
  type: 'MASHA_HOVER_TRANSLATE';
  nodeId: string;
  text: string;
}

/** One loose string — compose, a subtitle cue, an OCR block. */
interface TranslateTextMessage {
  type: 'MASHA_TRANSLATE_TEXT';
  text: string;
  /** Overrides the reading target — compose translates the other way. */
  targetLang?: string;
}

interface TranslatePageMessage {
  type: 'MASHA_TRANSLATE_PAGE';
  segments: Segment[];
  pageContext: string;
}

interface FetchImageMessage {
  type: 'MASHA_FETCH_IMAGE';
  src: string;
}

interface OcrMessage {
  type: 'MASHA_OCR';
  image: string;
  sourceLang: string;
  mode: 'text' | 'comic';
}

interface OcrRenderMessage {
  type: 'MASHA_OCR_RENDER';
  image: string;
  blocks: Array<{ quad: unknown; translated: string }>;
}

interface HealthMessage {
  type: 'MASHA_BRIDGE_HEALTH';
}

interface DocumentJobMessage {
  type: 'MASHA_DOCUMENT_JOB';
  filename: string;
  /** Base64 file bytes. `sendMessage` is JSON — an ArrayBuffer arrives as {}. */
  data: string;
  sourceLang: string;
  targetLang: string;
}

interface DocumentPollMessage {
  type: 'MASHA_DOCUMENT_POLL';
  jobId: string;
}

interface GlossaryGetMessage {
  type: 'MASHA_GLOSSARY_GET';
}

interface GlossarySetMessage {
  type: 'MASHA_GLOSSARY_SET';
  source: string;
  target: string;
}

interface CacheLookupMessage {
  type: 'MASHA_CACHE_LOOKUP';
  sourceText: string;
  sourceLang: string;
  targetLang: string;
}

interface CacheStoreMessage {
  type: 'MASHA_CACHE_STORE';
  entries: Array<{ sourceText: string; sourceLang: string; targetLang: string; translated: string }>;
}

type BridgeMessage =
  | TranslateMessage
  | HoverMessage
  | TranslateTextMessage
  | TranslatePageMessage
  | FetchImageMessage
  | OcrMessage
  | OcrRenderMessage
  | HealthMessage
  | DocumentJobMessage
  | DocumentPollMessage
  | GlossaryGetMessage
  | GlossarySetMessage
  | CacheLookupMessage
  | CacheStoreMessage;

// --- Shared state ---

/**
 * Tier-1 translation cache, for the life of the worker.
 *
 * The bridge's SQLite store is tier 2 and is shared with MAGE and Luduan; this
 * one exists so that a page full of repeated boilerplate does not become a
 * page full of HTTP round trips.
 */
const memoryCache = new LRUCache(2000);

/** The glossary, and the epoch that says when it last changed. */
let glossaryCache: { terms: Record<string, string>; epoch: number; fetchedAt: number } | null = null;
const GLOSSARY_TTL_MS = 60_000;

/** What the bridge last said it could do, and when it said it. */
let healthCache: { health: BridgeHealth; probedAt: number } | null = null;
const HEALTH_TTL_MS = 30_000;

async function bridgeFetch(config: MashaConfig, path: string, init?: RequestInit): Promise<Response> {
  return fetch(`${config.bridgeUrl}${path}`, init);
}

/**
 * Ask the bridge what it can do.
 *
 * MASHA hides the features whose backend says no, so a missing bridge — or one
 * built without the OCR extra — is a smaller set of buttons rather than a
 * button that fails when pressed.
 */
async function bridgeHealth(config: MashaConfig, force = false): Promise<BridgeHealth> {
  const now = Date.now();
  if (!force && healthCache && now - healthCache.probedAt < HEALTH_TTL_MS) {
    return healthCache.health;
  }

  let health: BridgeHealth = { reachable: false, ocr: false, documents: false };
  try {
    // Short: the bridge is on loopback, so it either answers at once or is
    // not running, and the popup should not sit waiting on it.
    const response = await bridgeFetch(config, '/health', {
      signal: AbortSignal.timeout(500),
    });
    if (response.ok) {
      const body = await response.json();
      health = {
        reachable: true,
        version: body.version,
        ocr: Boolean(body.ocr),
        documents: Boolean(body.documents),
      };
    }
  } catch {
    // Not running, or too slow to be useful. Both mean "no".
  }

  healthCache = { health, probedAt: now };
  return health;
}

/** The shared glossary, refreshed at most once a minute. */
async function loadGlossary(config: MashaConfig): Promise<Record<string, string>> {
  const now = Date.now();
  if (glossaryCache && now - glossaryCache.fetchedAt < GLOSSARY_TTL_MS) {
    return glossaryCache.terms;
  }
  try {
    const response = await bridgeFetch(config, '/glossary', { signal: AbortSignal.timeout(1500) });
    if (!response.ok) throw new Error(String(response.status));
    const body = await response.json();
    glossaryCache = { terms: body.terms || {}, epoch: body.epoch ?? 0, fetchedAt: now };
  } catch {
    // No bridge, no glossary. Translation without one is the old behaviour,
    // not a failure.
    glossaryCache = { terms: {}, epoch: 0, fetchedAt: now };
  }
  return glossaryCache.terms;
}

/** The current glossary epoch — cache rows older than this are stale. */
function glossaryEpoch(): number {
  return glossaryCache?.epoch ?? 0;
}

async function handleTranslate(payload: SelectionContext): Promise<string> {
  const config = await getConfig();
  return translate(fetch as any, config, {
    selection: payload.text,
    context: payload.context,
    sourceLang: config.sourceLang,
    targetLang: config.targetLang,
    styles: config.styles,
    glossary: await loadGlossary(config),
    expertise: config.expertise || undefined,
  });
}

async function handleTranslateText(text: string, targetLang?: string): Promise<string> {
  const config = await getConfig();
  const target = targetLang || config.targetLang;

  const cached = memoryCache.get(text, config.sourceLang, target, glossaryEpoch());
  if (cached) return cached;

  const translated = await translate(fetch as any, config, {
    selection: text,
    context: '',
    sourceLang: config.sourceLang,
    targetLang: target,
    styles: config.styles,
    glossary: await loadGlossary(config),
    expertise: config.expertise || undefined,
  });

  memoryCache.set({
    sourceText: text,
    sourceLang: config.sourceLang,
    targetLang: target,
    translated,
    epoch: glossaryEpoch(),
  });
  return translated;
}

/** Bridge cache lookups for a batch of segments, a few at a time. */
async function bridgeCacheHits(
  config: MashaConfig,
  segments: Segment[],
): Promise<Map<string, string>> {
  const hits = new Map<string, string>();
  const CONCURRENCY = 8;

  for (let i = 0; i < segments.length; i += CONCURRENCY) {
    const slice = segments.slice(i, i + CONCURRENCY);
    await Promise.all(slice.map(async (segment) => {
      try {
        const translated = await handleCacheLookup(
          segment.text, config.sourceLang, config.targetLang, config,
        );
        if (translated) hits.set(segment.id, translated);
      } catch {
        // A cache that is not answering is a cache miss.
      }
    }));
  }
  return hits;
}

/**
 * Translate a whole page.
 *
 * Segments already known are answered from cache without a request; the rest
 * go through the batching pipeline, and each one is streamed to the tab as it
 * lands so the page fills in from the top.
 */
async function handleTranslatePage(
  segments: Segment[],
  pageContext: string,
  tabId: number | undefined,
): Promise<{ segmentCount: number; successCount: number }> {
  const config = await getConfig();
  const glossary = await loadGlossary(config);
  const epoch = glossaryEpoch();

  function send(id: string, translated: string): void {
    if (tabId === undefined) return;
    chrome.tabs.sendMessage(tabId, { type: 'MASHA_SEGMENT', id, translated }).catch(() => {
      // The tab navigated away mid-translation.
    });
  }

  let successCount = 0;
  const misses: Segment[] = [];

  for (const segment of segments) {
    const cached = memoryCache.get(segment.text, config.sourceLang, config.targetLang, epoch);
    if (cached) {
      send(segment.id, cached);
      successCount++;
    } else {
      misses.push(segment);
    }
  }

  // Tier 2 — shared with MAGE and Luduan, and only worth asking when the
  // bridge is actually up.
  let remaining = misses;
  if (misses.length > 0 && (await bridgeHealth(config)).reachable) {
    const hits = await bridgeCacheHits(config, misses);
    if (hits.size > 0) {
      for (const [id, translated] of hits) {
        send(id, translated);
        successCount++;
      }
      remaining = misses.filter((segment) => !hits.has(segment.id));
    }
  }

  const textById = new Map(remaining.map((segment) => [segment.id, segment.text]));
  const fresh: Array<{ sourceText: string; sourceLang: string; targetLang: string; translated: string }> = [];

  await translatePage(fetch as any, {
    segments: remaining,
    config,
    glossary,
    pageContext,
    expertise: config.expertise || undefined,
    onSegment: (id, translated) => {
      send(id, translated);
      successCount++;
      const sourceText = textById.get(id);
      if (!sourceText) return;
      memoryCache.set({
        sourceText,
        sourceLang: config.sourceLang,
        targetLang: config.targetLang,
        translated,
        epoch,
      });
      fresh.push({
        sourceText,
        sourceLang: config.sourceLang,
        targetLang: config.targetLang,
        translated,
      });
    },
    onError: () => {
      // Reported per segment by count: the page shows what landed.
    },
  });

  if (fresh.length > 0 && (await bridgeHealth(config)).reachable) {
    await handleCacheStore(fresh).catch(() => {});
  }

  return { segmentCount: segments.length, successCount };
}

/** Base64 for arbitrary bytes, in chunks so a large image cannot blow the stack. */
function bytesToBase64(bytes: Uint8Array): string {
  const CHUNK = 0x8000;
  let binary = '';
  for (let i = 0; i < bytes.length; i += CHUNK) {
    binary += String.fromCharCode(...bytes.subarray(i, i + CHUNK));
  }
  return btoa(binary);
}

function base64ToBytes(base64: string): Uint8Array<ArrayBuffer> {
  // Tolerate a full data: URL as well as bare base64.
  const payload = base64.includes(',') ? base64.slice(base64.indexOf(',') + 1) : base64;
  const binary = atob(payload);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return bytes;
}

async function handleFetchImage(src: string): Promise<string | null> {
  try {
    const resp = await fetch(src);
    if (!resp.ok) return null;
    // No FileReader in an MV3 service worker — its global scope has neither
    // FileReader nor a DOM, so readAsDataURL would throw ReferenceError and
    // every cross-origin image would silently come back null.
    const bytes = new Uint8Array(await resp.arrayBuffer());
    const mime = resp.headers.get('content-type') || 'application/octet-stream';
    return `data:${mime};base64,${bytesToBase64(bytes)}`;
  } catch {
    return null;
  }
}

async function handleOcr(
  image: string,
  sourceLang: string,
  mode: 'text' | 'comic',
): Promise<{ blocks: unknown[]; size: unknown }> {
  const config = await getConfig();
  const response = await bridgeFetch(config, '/ocr', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ image, source_lang: sourceLang, mode }),
  });
  if (response.status === 501) {
    throw new Error('The bridge has no OCR engine — install the xian-vl[ocr] extra.');
  }
  if (!response.ok) throw new Error(`OCR failed: ${response.status}`);
  return response.json();
}

async function handleOcrRender(
  image: string,
  blocks: Array<{ quad: unknown; translated: string }>,
): Promise<string> {
  const config = await getConfig();
  const response = await bridgeFetch(config, '/ocr/render', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ image, blocks }),
  });
  if (!response.ok) throw new Error(`Render failed: ${response.status}`);
  const result = await response.json();
  return result.image;
}

async function handleDocumentJob(
  filename: string,
  data: string,
  sourceLang: string,
  targetLang: string,
): Promise<string> {
  const config = await getConfig();
  const blob = new Blob([base64ToBytes(data)]);
  const form = new FormData();
  form.append('file', blob, filename);
  form.append('source_lang', sourceLang);
  form.append('target_lang', targetLang);
  form.append('bilingual', 'true');

  const resp = await bridgeFetch(config, '/documents', { method: 'POST', body: form });
  if (!resp.ok) throw new Error(`Document job failed: ${resp.status}`);
  const result = await resp.json();
  return result.job_id;
}

async function handleDocumentPoll(jobId: string): Promise<{ status: string; progress: number }> {
  const config = await getConfig();
  const resp = await bridgeFetch(config, `/documents/${jobId}`);
  if (!resp.ok) throw new Error(`Job not found: ${resp.status}`);
  const result = await resp.json();
  return { status: result.status, progress: result.progress };
}

async function handleGlossaryGet(): Promise<Record<string, string>> {
  const config = await getConfig();
  return loadGlossary(config);
}

async function handleGlossarySet(source: string, target: string): Promise<void> {
  const config = await getConfig();
  await bridgeFetch(config, '/glossary', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ source, target }),
  });
  // A changed glossary changes every prompt, so nothing translated under the
  // old one may be served from cache.
  glossaryCache = null;
}

async function handleCacheLookup(
  sourceText: string,
  sourceLang: string,
  targetLang: string,
  known?: MashaConfig,
): Promise<string | null> {
  const config = known ?? await getConfig();
  const params = new URLSearchParams({
    source_text: sourceText,
    source_lang: sourceLang,
    target_lang: targetLang,
    epoch: String(glossaryEpoch()),
  });
  const resp = await bridgeFetch(config, `/cache?${params}`);
  if (!resp.ok) return null;
  const result = await resp.json();
  return result.found ? result.translated : null;
}

async function handleCacheStore(
  entries: Array<{ sourceText: string; sourceLang: string; targetLang: string; translated: string }>,
): Promise<void> {
  const config = await getConfig();
  await bridgeFetch(config, '/cache', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      entries: entries.map(e => ({
        source_text: e.sourceText,
        source_lang: e.sourceLang,
        target_lang: e.targetLang,
        translated: e.translated,
        epoch: glossaryEpoch(),
      })),
    }),
  });
}

export default defineBackground(() => {
  // Register the right-click triggers
  chrome.runtime.onInstalled.addListener(async () => {
    const config = await getConfig();
    chrome.contextMenus.removeAll(() => {
      chrome.contextMenus.create({
        id: MENU_ID,
        title: 'Translate with MASHA',
        contexts: ['selection'],
      });
      chrome.contextMenus.create({
        id: IMAGE_MENU_ID,
        title: 'Translate this image with MASHA',
        contexts: ['image'],
        visible: config.imagesEnabled,
      });
    });
  });

  // The image entry follows its setting rather than waiting for a reinstall.
  chrome.storage.onChanged.addListener((changes, area) => {
    if (area !== 'local' || !changes.config) return;
    getConfig().then((config) => {
      chrome.contextMenus.update(IMAGE_MENU_ID, { visible: config.imagesEnabled });
    });
  });

  // Context-menu click → ask the page's content script
  chrome.contextMenus.onClicked.addListener((info, tab) => {
    if (!tab?.id) return;
    if (info.menuItemId === MENU_ID) {
      chrome.tabs.sendMessage(tab.id, { type: 'MASHA_TRIGGER' }).catch(() => {});
    } else if (info.menuItemId === IMAGE_MENU_ID && info.srcUrl) {
      chrome.tabs.sendMessage(tab.id, { type: 'MASHA_IMAGE_TRANSLATE', src: info.srcUrl }).catch(() => {});
    }
  });

  // All runtime messages
  chrome.runtime.onMessage.addListener(
    (message: BridgeMessage, sender, sendResponse) => {
      if (sender.id !== chrome.runtime.id) {
        sendResponse({ success: false, error: 'Invalid sender' });
        return;
      }

      const fail = (error: unknown) => sendResponse({ success: false, error: String(error) });

      try {
        switch (message.type) {
          case 'MASHA_TRANSLATE': {
            handleTranslate((message as TranslateMessage).payload)
              .then((translation) => sendResponse({ success: true, translation }))
              .catch(fail);
            return true;
          }

          case 'MASHA_HOVER_TRANSLATE': {
            const msg = message as HoverMessage;
            handleTranslateText(msg.text)
              .then((translation) => sendResponse({ success: true, translation }))
              .catch(fail);
            return true;
          }

          case 'MASHA_TRANSLATE_TEXT': {
            const msg = message as TranslateTextMessage;
            handleTranslateText(msg.text, msg.targetLang)
              .then((translation) => sendResponse({ success: true, translation }))
              .catch(fail);
            return true;
          }

          case 'MASHA_TRANSLATE_PAGE': {
            const msg = message as TranslatePageMessage;
            handleTranslatePage(msg.segments, msg.pageContext, sender.tab?.id)
              .then((outcome) => sendResponse({ success: true, ...outcome }))
              .catch(fail);
            return true;
          }

          case 'MASHA_FETCH_IMAGE': {
            const msg = message as FetchImageMessage;
            handleFetchImage(msg.src)
              .then((dataUrl) => sendResponse({ success: true, dataUrl }))
              .catch(fail);
            return true;
          }

          case 'MASHA_OCR': {
            const msg = message as OcrMessage;
            handleOcr(msg.image, msg.sourceLang, msg.mode)
              .then((result) => sendResponse({ success: true, result }))
              .catch(fail);
            return true;
          }

          case 'MASHA_OCR_RENDER': {
            const msg = message as OcrRenderMessage;
            handleOcrRender(msg.image, msg.blocks)
              .then((image) => sendResponse({ success: true, image }))
              .catch(fail);
            return true;
          }

          case 'MASHA_BRIDGE_HEALTH': {
            getConfig()
              .then((config) => bridgeHealth(config, true))
              .then((health) => sendResponse({ success: true, health }))
              .catch(fail);
            return true;
          }

          case 'MASHA_DOCUMENT_JOB': {
            const msg = message as DocumentJobMessage;
            handleDocumentJob(msg.filename, msg.data, msg.sourceLang, msg.targetLang)
              .then((jobId) => sendResponse({ success: true, jobId }))
              .catch(fail);
            return true;
          }

          case 'MASHA_DOCUMENT_POLL': {
            const msg = message as DocumentPollMessage;
            handleDocumentPoll(msg.jobId)
              .then((status) => sendResponse({ success: true, ...status }))
              .catch(fail);
            return true;
          }

          case 'MASHA_GLOSSARY_GET': {
            handleGlossaryGet()
              .then((terms) => sendResponse({ success: true, terms }))
              .catch(fail);
            return true;
          }

          case 'MASHA_GLOSSARY_SET': {
            const msg = message as GlossarySetMessage;
            handleGlossarySet(msg.source, msg.target)
              .then(() => sendResponse({ success: true }))
              .catch(fail);
            return true;
          }

          case 'MASHA_CACHE_LOOKUP': {
            const msg = message as CacheLookupMessage;
            handleCacheLookup(msg.sourceText, msg.sourceLang, msg.targetLang)
              .then((translated) => sendResponse({ success: true, translated }))
              .catch(fail);
            return true;
          }

          case 'MASHA_CACHE_STORE': {
            const msg = message as CacheStoreMessage;
            handleCacheStore(msg.entries)
              .then(() => sendResponse({ success: true }))
              .catch(fail);
            return true;
          }

          default:
            sendResponse({ success: false, error: 'Unknown message type' });
        }
      } catch (error) {
        fail(error);
      }
    },
  );
});
