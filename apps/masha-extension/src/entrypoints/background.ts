/*
 * Background service worker (WXT).
 *
 * Owns the platform pieces that must live off the page: the context-menu
 * trigger, the Lemonade HTTP call, bridge communication, and cross-origin
 * image fetching.
 */

import { getConfig, setConfig } from '../utils/config';
import { translate } from '../core/translator';
import { SelectionContext, MashaConfig, PageTranslationOutcome } from '../platform/bridge';
import { normalizeLemonadeBaseUrl } from '../utils/lemonadeUrl';

const MENU_ID = 'masha-translate';

// Bridge base URL (configurable)
const BRIDGE_URL = 'http://127.0.0.1:13306';

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

interface FetchImageMessage {
  type: 'MASHA_FETCH_IMAGE';
  src: string;
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
  | FetchImageMessage
  | DocumentJobMessage
  | DocumentPollMessage
  | GlossaryGetMessage
  | GlossarySetMessage
  | CacheLookupMessage
  | CacheStoreMessage;

async function handleTranslate(payload: SelectionContext): Promise<string> {
  const config = await getConfig();
  return translate(fetch as any, config, {
    selection: payload.text,
    context: payload.context,
    sourceLang: config.sourceLang,
    targetLang: config.targetLang,
    styles: config.styles,
  });
}

async function handleHoverTranslate(text: string): Promise<string> {
  const config = await getConfig();
  return translate(fetch as any, config, {
    selection: text,
    context: '',
    sourceLang: config.sourceLang,
    targetLang: config.targetLang,
    styles: config.styles,
  });
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

async function handleDocumentJob(
  filename: string,
  data: string,
  sourceLang: string,
  targetLang: string,
): Promise<string> {
  const blob = new Blob([base64ToBytes(data)]);
  const form = new FormData();
  form.append('file', blob, filename);
  form.append('source_lang', sourceLang);
  form.append('target_lang', targetLang);
  form.append('bilingual', 'true');

  const resp = await fetch(`${BRIDGE_URL}/documents`, {
    method: 'POST',
    body: form,
  });
  const result = await resp.json();
  return result.job_id;
}

async function handleDocumentPoll(jobId: string): Promise<{ status: string; progress: number }> {
  const resp = await fetch(`${BRIDGE_URL}/documents/${jobId}`);
  const result = await resp.json();
  return { status: result.status, progress: result.progress };
}

async function handleGlossaryGet(): Promise<Record<string, string>> {
  const resp = await fetch(`${BRIDGE_URL}/glossary`);
  const result = await resp.json();
  return result.terms || {};
}

async function handleGlossarySet(source: string, target: string): Promise<void> {
  await fetch(`${BRIDGE_URL}/glossary`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ source, target }),
  });
}

async function handleCacheLookup(
  sourceText: string,
  sourceLang: string,
  targetLang: string,
): Promise<string | null> {
  const params = new URLSearchParams({ source_text: sourceText, source_lang: sourceLang, target_lang: targetLang });
  const resp = await fetch(`${BRIDGE_URL}/cache?${params}`);
  const result = await resp.json();
  return result.found ? result.translated : null;
}

async function handleCacheStore(
  entries: Array<{ sourceText: string; sourceLang: string; targetLang: string; translated: string }>,
): Promise<void> {
  await fetch(`${BRIDGE_URL}/cache`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      entries: entries.map(e => ({
        source_text: e.sourceText,
        source_lang: e.sourceLang,
        target_lang: e.targetLang,
        translated: e.translated,
        epoch: 0,
      })),
    }),
  });
}

export default defineBackground(() => {
  // Register the right-click trigger
  chrome.runtime.onInstalled.addListener(() => {
    chrome.contextMenus.removeAll(() => {
      chrome.contextMenus.create({
        id: MENU_ID,
        title: 'Translate with MASHA',
        contexts: ['selection'],
      });
    });
  });

  // Context-menu click → ask the page's content script
  chrome.contextMenus.onClicked.addListener((info, tab) => {
    if (info.menuItemId !== MENU_ID || !tab?.id) return;
    chrome.tabs.sendMessage(tab.id, { type: 'MASHA_TRIGGER' }).catch(() => {});
  });

  // All runtime messages
  chrome.runtime.onMessage.addListener(
    (message: BridgeMessage, sender, sendResponse) => {
      if (sender.id !== chrome.runtime.id) {
        sendResponse({ success: false, error: 'Invalid sender' });
        return;
      }

      try {
        switch (message.type) {
          case 'MASHA_TRANSLATE': {
            handleTranslate((message as TranslateMessage).payload)
              .then((translation) => sendResponse({ success: true, translation }))
              .catch((error) => sendResponse({ success: false, error: String(error) }));
            return true;
          }

          case 'MASHA_HOVER_TRANSLATE': {
            const msg = message as HoverMessage;
            handleHoverTranslate(msg.text)
              .then((translation) => sendResponse({ success: true, translation }))
              .catch((error) => sendResponse({ success: false, error: String(error) }));
            return true;
          }

          case 'MASHA_FETCH_IMAGE': {
            const msg = message as FetchImageMessage;
            handleFetchImage(msg.src)
              .then((dataUrl) => sendResponse({ success: true, dataUrl }))
              .catch((error) => sendResponse({ success: false, error: String(error) }));
            return true;
          }

          case 'MASHA_DOCUMENT_JOB': {
            const msg = message as DocumentJobMessage;
            handleDocumentJob(msg.filename, msg.data, msg.sourceLang, msg.targetLang)
              .then((jobId) => sendResponse({ success: true, jobId }))
              .catch((error) => sendResponse({ success: false, error: String(error) }));
            return true;
          }

          case 'MASHA_DOCUMENT_POLL': {
            const msg = message as DocumentPollMessage;
            handleDocumentPoll(msg.jobId)
              .then((status) => sendResponse({ success: true, ...status }))
              .catch((error) => sendResponse({ success: false, error: String(error) }));
            return true;
          }

          case 'MASHA_GLOSSARY_GET': {
            handleGlossaryGet()
              .then((terms) => sendResponse({ success: true, terms }))
              .catch((error) => sendResponse({ success: false, error: String(error) }));
            return true;
          }

          case 'MASHA_GLOSSARY_SET': {
            const msg = message as GlossarySetMessage;
            handleGlossarySet(msg.source, msg.target)
              .then(() => sendResponse({ success: true }))
              .catch((error) => sendResponse({ success: false, error: String(error) }));
            return true;
          }

          case 'MASHA_CACHE_LOOKUP': {
            const msg = message as CacheLookupMessage;
            handleCacheLookup(msg.sourceText, msg.sourceLang, msg.targetLang)
              .then((translated) => sendResponse({ success: true, translated }))
              .catch((error) => sendResponse({ success: false, error: String(error) }));
            return true;
          }

          case 'MASHA_CACHE_STORE': {
            const msg = message as CacheStoreMessage;
            handleCacheStore(msg.entries)
              .then(() => sendResponse({ success: true }))
              .catch((error) => sendResponse({ success: false, error: String(error) }));
            return true;
          }

          default:
            sendResponse({ success: false, error: 'Unknown message type' });
        }
      } catch (error) {
        sendResponse({ success: false, error: String(error) });
      }
    },
  );
});
