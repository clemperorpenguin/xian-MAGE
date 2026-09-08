<!--
 Masha — Browser extension selection translator.
 Copyright (C) 2026  Clementine Pendragon <clem@pendragon.systems>
 Licensed under the GNU General Public License v3.0 or later.
-->

# Porting MASHA to Falkon (and other non-WebExtension browsers)

Falkon (KDE, built on QtWebEngine) does **not** implement the WebExtensions API
— there is no `chrome.*`/`browser.*` runtime. So MASHA cannot be loaded there as
a WXT extension; Falkon needs a **separate plugin** written against its own
system (C++ or Python via [PyFalkon]). This document is the contract for that
port.

It was written when MASHA was a selection translator and the whole contract was
six methods. M1–M7 have happened since. The port is still not a rewrite of the
translation logic, but it is no longer small, and this document now says so.

## What you reuse for free

1. **`src/core/` is browser-free.** Nothing under it imports a platform API, by
   rule, and that rule is what makes it readable as a specification. It is
   ~1,750 lines across fourteen files — not the ~150 this document used to
   claim.
2. **Three of those files already exist in Python.** `constants.ts`,
   `prompt.ts` and `translator.ts` (~340 lines) trace back to
   `shared_types/constants.py` and `xian/pipeline.py`. A Python plugin should
   import those rather than re-derive them.

   Read "mirror" as "same shape, same intent", not "same values": MASHA
   defaults to `Auto` where MAGE defaults to `Chinese`, because a browser is
   not a game, and MASHA has constants (`DEFAULT_BRIDGE_URL`,
   `MAX_CONTEXT_CHARS`, `DEFAULT_ASR_MODEL`) that MAGE has no use for.

## What you must port

The other eleven files — about 1,400 lines — have **no Python counterpart
anywhere in the monorepo**. They are the browser half of MASHA's thinking, and
a Falkon port has to bring them across:

| Module | Lines | What it decides |
| --- | --- | --- |
| `dom/article.ts` + `dom/tree.ts` | 300 | Which part of a page is the article, by link density and text score |
| `segment.ts` | 215 | Where a block starts and ends, and the stable id it carries |
| `pipeline.ts` | 251 | Batching by character budget, marker validation, concurrency |
| `profiles/` | 110 | Per-site selector overrides, matched on the URL |
| `lang.ts` | 140 | Script detection — "is this already in the target language?" |
| `cache.ts` | 116 | Cache keys and LRU eviction |
| `subtitles/cue.ts` | 118 | Cue merging, non-speech skipping, lookahead |
| `compose/state.ts` | 98 | The triple-space trigger state machine |
| `nearestBlock.ts` | 59 | The hover unit |

Port them to Python next to the plugin, and the two implementations will drift.
Port them to Python *inside `packages/xian-vl`* and the drift is at least
visible — and MAGE gets an article finder it does not have yet.

## What you must implement

`PlatformBridge` in [`src/platform/bridge.ts`](../src/platform/bridge.ts) is the
seam. It is **24 methods** now, but they arrive in tiers, and a port is useful
long before it is complete.

One thing is easier in Falkon than in the browser MASHA was written for: the
WXT build cannot implement this interface as a single class, because an MV3
extension has no one process that can hold the DOM, storage and the network at
once — it is spread across `background.ts`, `content.ts` and the popup. A
Falkon plugin *is* one process, so there the interface can be what it looks
like: one object.

### Tier 1 — selection translation (seven methods)

This alone is a working translator, and it is the port worth doing first.

| Method | WXT realization | Falkon equivalent |
| --- | --- | --- |
| `getConfig` / `setConfig` | `chrome.storage.local` | Falkon `Settings` / a JSON file |
| `onTranslateCommand` | `chrome.contextMenus` + `tabs.sendMessage` | Falkon context-menu plugin hook |
| `getSelectionContext` | DOM selection + nearest block `innerText` | injected JS via `QWebEnginePage.runJavaScript` |
| `showOverlay` | injected `<div>` overlay | injected JS overlay (same HTML/CSS) |
| `replaceSelection` | input `value` splice | injected JS on the focused input |
| `showError` | injected `<div>` | injected JS |

The selection-capture and overlay JS lifts almost verbatim from
[`src/entrypoints/content/selection.ts`](../src/entrypoints/content/selection.ts)
— QtWebEngine runs the same DOM APIs. (It lived in `content.ts` when this
document first said so; that file is now the composition root.)

### Tier 2 — bilingual pages

`getPageTree`, `translatePage`, `undoPageTranslation`, `getSiteProfile`. This is
the tier that needs the ported `dom/`, `segment.ts` and `pipeline.ts`, and it
carries three DOM contracts a port must honour **exactly** or translations
strand themselves — see below.

### Tier 3 — the rest, each independent of the others

`attachHover`, `attachCompose`, `attachTrackSubtitles`, `attachAudioSubtitles`,
`translateImage`, `attachComicReader`, `startDocumentJob`, `getDocumentStatus`,
`getBridgeHealth`, `getGlossary`, `setGlossaryEntry`, `cacheLookup`,
`cacheStore`.

Nothing in tier 3 depends on anything else in tier 3, so pick the ones your
users want. Each attaches, hands back a detach function, and is otherwise on its
own — see `src/entrypoints/content.ts` for how thin the wiring is once that
shape holds.

## Contracts a port must honour exactly

Three pieces of state live in the page's DOM rather than in the plugin, so a
port that invents its own spelling for them cannot interoperate with a page
MASHA already touched — and, more importantly, gets its own undo wrong.

* **`data-masha-node`** — a monotonic id stamped on an element the first time it
  is walked. Identity must live on the element, never in walk order: a comment
  widget loading above the article renumbers every positional id after it and
  strands every translation already on the page. Ids are never reused, even
  after an undo.
* **`<masha-tr>`** — one translation per source block, inserted as the *next
  sibling*, with a closed shadow root and `data-masha-for` set to the segment's
  base id. The page is never rewritten, so undo is exact and the site's CSS
  cannot restyle the translation. Chunks of a long block share one `<masha-tr>`
  and are reassembled by chunk index, not arrival order.
* **`data-masha-id`** on the source element once its translation lands — this is
  what the mutation observer's "have I already seen this?" filter reads, so
  injection and de-duplication stay in step.

One thing that does **not** port cleanly: `SiteProfile.match` is a JavaScript
`RegExp`. The patterns are host-anchored —

```js
/^https?:\/\/([a-z0-9-]+\.)*(twitter|x)\.com(\/|$)/i
```

— and need re-expressing in the host language's regex dialect, not
transliterating character by character. Getting this wrong is quiet: the
unanchored `/twitter\.com|x\.com/i` this started as also matched `netflix.com`,
`matrix.com` and `phoenix.com`, handing Twitter's selectors to every one of them
and translating nothing.

## The bridge

OCR, document jobs, the shared glossary and the shared cache are not the
browser's work. They live in `packages/xian-bridge`, a loopback HTTP service on
`127.0.0.1:13306`, and the WebExtension reaches them over HTTP because it has no
other choice.

**A Python plugin has a choice.** It can call the same endpoints, or it can
`import xian.ocr` and `xian.pipeline` directly and skip the hop. Prefer the
direct import for OCR — it is the same engine the bridge itself calls, one
process fewer, and no base64 round trip for every image.

Either way, honour the capability probe: `GET /health` reports `ocr` and
`documents`, and MASHA shows only the features whose backend says yes. A feature
whose backend is missing should be absent, not present and broken.

## Network note

Route every model and bridge call from the **plugin process**, never from page
JS. Two independent reasons, either of which is sufficient:

1. **Cross-origin.** In MV3 a content script's `fetch` is judged by the *page's*
   CORS policy rather than the extension's. MASHA learned this the hard way —
   its image path called Lemonade and the bridge directly and could not have
   worked on any real site. Whatever QtWebEngine's equivalent rule turns out to
   be, the plugin process is the side that is definitely allowed.
2. **Mixed content.** A page-context `fetch` to a local `http://` node from an
   `https://` page is blocked outright.

[PyFalkon]: https://api.kde.org/falkon/pyfalkon/
