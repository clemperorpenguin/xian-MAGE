# MASHA — Implementation Plan

**Scope:** everything in [README.md](README.md) that is not marked ✅.
**Date:** 2026-09-08.

MASHA today is 719 lines that do one thing well: translate a selection with the
surrounding page as context. This plan takes it to a full browsing translator —
bilingual pages, hover, compose, subtitles, images, comics and documents —
without giving up the two properties that make it worth using: **everything
local**, and **a browser-free core**.

**One caveat, stated once.** This document specifies all seven milestones to
implementation level. The later ones will drift: M6 is a long way behind M1 and
the ground will have moved by the time anyone reaches it. Treat M1–M2 as
buildable as written, M3–M5 as a firm design, and M6–M7 as intent with enough
detail to argue with.

---

## 0. What exists, and what must not break

```
src/
├── core/        constants.ts · prompt.ts · translator.ts      (browser-free)
├── platform/    bridge.ts — PlatformBridge, MashaConfig, SelectionContext
├── utils/       config.ts · lemonadeUrl.ts
└── entrypoints/ background.ts · content.ts · popup/
```

Two invariants govern every addition below.

**`core/` never imports a browser API.** It is what a Falkon plugin
reimplements (`docs/FALKON.md`), and it is the only part testable without a
browser. Everything in this plan therefore splits the same way: *policy* goes
in `core/` and takes plain data; *the DOM, storage, network and media* go
behind the bridge.

**`PlatformBridge` is the only seam.** It grows from 7 methods to roughly 20
across this plan. Each addition is optional-with-a-default where a platform
might not have it, so a Falkon plugin can ship without subtitle support rather
than not ship.

A third rule earned in the Xian repo and adopted here:

**Nothing is reimplemented that already exists in Python.** `packages/xian-vl`
has a measured PP-OCRv5 pipeline, a text change-gate, a translation cache and a
glossary. Luduan has document handling. MASHA calls them; it does not carry a
second copy in TypeScript.

---

## 1. Architecture

### 1.1 One hub

Every model call — text, vision, speech — goes to **Lemonade**. That is the
ecosystem's existing pattern (`docs/AI_ARCHITECTURE.md` §1) and MASHA does not
get an exception. The endpoints this plan uses, all of which Lemonade already
serves:

| Need | Endpoint |
|---|---|
| Translation, vision-language | `POST /v1/chat/completions` |
| Subtitle audio, one shot | `POST /v1/audio/transcriptions` |
| Subtitle audio, live | `WS /realtime` |
| Long document runs | `POST /v1/jobs` + pause/resume/interrupt |
| What is installed | `GET /v1/models`, `GET /v1/health` |

### 1.2 One bridge service

Two things Lemonade cannot do: run PP-OCRv5's detector and get quads back, and
parse a PDF's layout. Both exist in Python in this repository. So MASHA gets a
small local service — **the Xian bridge** — that exposes them and nothing else.

New workspace member: `packages/xian-bridge`.

```
packages/xian-bridge/
├── pyproject.toml          depends on xian-vl[ocr], luduan, fastapi, uvicorn
└── src/xian_bridge/
    ├── __main__.py         uvicorn entry; --host 127.0.0.1 --port 13306
    ├── app.py              routes + CORS for extension origins only
    ├── ocr.py              wraps xian.ocr.PaddleOcrEngine
    ├── documents.py        wraps the Luduan pipeline
    └── glossary.py         wraps VLProcessor.load_glossary_from_wiki
```

| Route | Body | Returns |
|---|---|---|
| `GET /health` | — | `{version, ocr: bool, documents: bool}` |
| `POST /ocr` | `{image: base64, source_lang, mode: "text"\|"comic"}` | `{blocks: [{quad, text, confidence}], size}` |
| `POST /ocr/render` | `{image, blocks: [{quad, translated}]}` | `{image: base64}` — inpainted result |
| `POST /documents` | multipart file + `{source_lang, target_lang, bilingual}` | `{job_id}` |
| `GET /documents/{id}` | — | `{status, progress, pages_done, download_url?}` |
| `POST /documents/{id}/pause\|resume\|cancel` | — | `{status}` |
| `GET /glossary` | — | `{terms: {source: target}}` |

Three things about it:

- **It binds to loopback only, and its CORS allowlist is extension origins.**
  A service that can OCR arbitrary images and is reachable from any page is a
  data-exfiltration primitive; it is not one that answers `Origin: https://…`.
- **It translates through Lemonade**, not itself. One hub is the whole point.
- **It is optional.** MASHA detects it at startup (`GET /health`, 300 ms
  timeout) and hides the features that need it when it is absent, rather than
  offering a button that fails.

### 1.3 Where the work runs

```
   ┌──────────────┐   selection, page text, subtitles     ┌───────────────┐
   │  MASHA       │ ────────────────────────────────────► │  Lemonade     │
   │  extension   │ ◄──────────────────────────────────── │  :13305       │
   └──────┬───────┘             translations              └───────▲───────┘
          │                                                       │
          │ images, documents                                     │ translation
          ▼                                                       │
   ┌──────────────┐                                               │
   │ Xian bridge  │ ──────────────────────────────────────────────┘
   │ :13306       │
   └──────────────┘
```

---

## 2. M1 — Bilingual pages

The headline feature and the largest single lift. Everything after it reuses
its segmentation, its cache and its injection.

### 2.1 Finding the article

Adapted from Readability's scoring, but operating on a **serialisable node
tree** rather than on the DOM, so the algorithm lives in `core/` and can be
tested against fixtures with no browser.

`core/dom/tree.ts`

```ts
export interface NodeSummary {
  id: number;              // index into the content script's node table
  tag: string;             // lowercased tagName
  role?: string;
  className: string;
  elementId: string;
  textLength: number;      // own text, excluding descendants' 
  linkTextLength: number;  // text inside <a>, for the link-density test
  children: NodeSummary[];
}
```

`core/dom/article.ts`

```ts
export interface ArticleConfig {
  minTextLength: number;        // 25 — below this a node scores nothing
  linkDensityCeiling: number;   // 0.5 — above this it is navigation, not prose
  ancestorDepth: number;        // 3 — how far a paragraph's score propagates up
  topCandidateSlack: number;    // 0.75 — siblings within this fraction join in
}

export function findArticleRoot(root: NodeSummary, config?: ArticleConfig): number | null;
```

Scoring, per Readability: every node with `textLength ≥ minTextLength` scores
`1 + commaCount + min(floor(textLength / 100), 3)`; the score propagates to
ancestors divided by depth; a node's final score is scaled by
`1 - linkDensity`. Negative-weight class/id patterns (`comment`, `sidebar`,
`footer`, `promo`, `share`, `related`) subtract, positive ones (`article`,
`content`, `post`, `entry`, `story`) add. `<article>` and
`role="main"` short-circuit the whole search when present and non-trivial —
which on a modern site is most of the time.

Returning `null` is a real answer: it means "no article here", and the caller
falls back to translating the visible viewport only.

### 2.2 Segmentation

`core/segment.ts`

```ts
export interface Segment {
  id: string;              // stable within a page load: `${nodeId}:${hash}`
  text: string;            // normalised, whitespace-collapsed
  kind: 'block' | 'heading' | 'listitem' | 'caption' | 'quote';
  order: number;           // document order, for reading-order batching
}

export interface SegmentPolicy {
  minChars: number;        // 3 — "OK" is not worth a request
  maxChars: number;        // 1200 — longer blocks are split at sentence ends
  skipTags: Set<string>;   // code, pre, kbd, samp, var, script, style, svg, math
  skipIfNumeric: boolean;  // true — "2024", "3.14", "$19.99" are not translations
}

export function toSegments(nodes: NodeSummary[], text: (id: number) => string,
                           policy?: SegmentPolicy): Segment[];
export function shouldTranslate(text: string, policy: SegmentPolicy): boolean;
export function splitLongBlock(text: string, maxChars: number): string[];
```

The rules that matter, and why:

- **A block is the unit, never a sentence.** A sentence translated without its
  paragraph loses exactly the context that makes MASHA worth using.
- **Code is never translated.** `pre`, `code`, `kbd`, `samp` and anything inside
  them are skipped outright. Translating a code sample is worse than leaving it.
- **Text already in the target language is skipped**, decided by
  `core/lang.ts::looksLikeTargetLanguage` — a script-block histogram, not a
  model call. Cheap and good enough to skip the English half of a bilingual page.
- **A block longer than `maxChars` is split at sentence boundaries** and
  reassembled after translation, so one enormous paragraph does not blow the
  context window.

### 2.3 Injection

`entrypoints/content/inject.ts` — bridge side, because it is all DOM.

Each translation is inserted as a **custom element with a shadow root**:

```html
<p data-masha-id="42:9f3c">…original…</p>
<masha-tr data-masha-for="42:9f3c"><!-- #shadow-root --></masha-tr>
```

- **A shadow root**, so the site's CSS cannot restyle the translation and
  MASHA's CSS cannot leak onto the site. This is the difference between working
  on every site and working on the ten that were tested.
- **`display` copied from the source block**, so a translated `<li>` still sits
  in the list and a translated table cell stays in its cell.
- **`data-masha-id` on the source** makes the whole operation idempotent:
  re-running skips what is already done, and *undo* is
  `document.querySelectorAll('masha-tr').forEach(n => n.remove())` plus
  stripping the attributes.
- **`lang` and `dir` set from the target language**, so an Arabic or Hebrew
  translation under a left-to-right original lays out correctly.

### 2.4 The request pipeline

`core/pipeline.ts` — browser-free, `fetch` injected as it already is in
`translator.ts`.

```ts
export interface PageTranslateOptions {
  segments: Segment[];
  config: MashaConfig;
  glossary?: Record<string, string>;
  concurrency?: number;      // 4
  batchChars?: number;       // 1500 — target payload per request
  signal?: AbortSignal;
  onSegment: (id: string, translated: string) => void;   // stream to the page
  onError: (id: string, error: Error) => void;
}

export async function translatePage(fetchFn: FetchFn, opts: PageTranslateOptions): Promise<void>;
```

- **Batched by character budget, not by count.** Twelve short list items and one
  long paragraph should not be one request each.
- **Batches carry an explicit index marker per segment** and are validated on
  return; a batch whose markers do not come back intact is *retried once
  per-segment* rather than mapped positionally. Positional mapping after a
  dropped delimiter paints the wrong translation under the wrong paragraph, and
  it is silent — the failure mode this design exists to avoid.
- **Reading order.** Batches are built in document order so the visible top of
  the page is translated first.
- **Concurrency 4**, tunable. Above that a local server queues anyway and the
  first paragraph takes longer to appear.
- **`onSegment` streams**: each segment is injected the moment it returns, so
  the page fills in from the top rather than all at once at the end.

### 2.5 Caching

`core/cache.ts` — a port of the LRU in `packages/xian-vl/src/xian/translation_cache.py`,
keyed identically on `(text, sourceLang, targetLang)`.

Two tiers:
- **In-memory**, per tab, for the current page.
- **`chrome.storage.local`**, bounded to ~5 MB with LRU eviction, so revisiting
  an article or paging through a forum thread is free.

The key deliberately excludes style and glossary, and the store is *versioned*
by them instead: changing either bumps a `cacheEpoch` that invalidates
everything. Keying on them would multiply the cache; versioning gets the same
correctness for one integer.

### 2.6 Dynamic pages

`entrypoints/content/observer.ts`

A `MutationObserver` on the article root, debounced 400 ms, feeding new nodes
through the same segmentation. Infinite-scroll feeds and SPA route changes are
the normal case, not an edge case.

Guards: MASHA's own `masha-tr` insertions are filtered out of the observer's
records — an observer that reacts to its own writes is an infinite loop, and it
is the single most likely bug in this milestone.

### 2.7 Files

| File | Purpose |
|---|---|
| `core/dom/tree.ts` | `NodeSummary` |
| `core/dom/article.ts` | `findArticleRoot` |
| `core/segment.ts` | `toSegments`, `shouldTranslate`, `splitLongBlock` |
| `core/lang.ts` | `looksLikeTargetLanguage`, script histogram |
| `core/pipeline.ts` | `translatePage`, batching, marker validation |
| `core/cache.ts` | LRU, `cacheEpoch` |
| `entrypoints/content/walk.ts` | DOM → `NodeSummary[]` + node table |
| `entrypoints/content/inject.ts` | `masha-tr`, shadow styling, undo |
| `entrypoints/content/observer.ts` | mutation handling |
| `platform/bridge.ts` | +`translatePage()`, +`undoPageTranslation()`, +`getPageTree()` |

### 2.8 Tests

`core/` is browser-free, so all of this is testable with `vitest` and no
browser. Add `vitest` + a `test/fixtures/` directory of saved HTML.

- `article.test.ts` — a Wikipedia article, a news page, a forum thread and a
  search results page, each asserting the chosen root; a page with no article
  returns `null`.
- `segment.test.ts` — code blocks skipped; numerics skipped; a 4000-char
  paragraph splits at sentence ends and reassembles; list items keep order.
- `pipeline.test.ts` — batching respects the character budget; a batch with a
  dropped marker falls back per-segment and never mis-maps; `onSegment` fires
  in document order; abort stops in-flight work.
- `cache.test.ts` — hit/miss, eviction, epoch invalidation.
- `lang.test.ts` — CJK, Cyrillic, Arabic and Latin pages classified correctly.

### 2.9 Acceptance

- A 60-paragraph article is fully bilingual, first paragraph visible within
  2 s of the click, with no layout shift on the original content.
- Re-running on the same page adds nothing and removes nothing.
- Undo restores the DOM to byte-identical original markup.
- An infinite-scroll feed translates new posts as they arrive, indefinitely,
  with no observer loop and no memory growth beyond the cache bound.

---

## 3. M2 — Hover, and compose

Small next to M1, and entirely built on it.

### 3.1 Hover to translate

`entrypoints/content/hover.ts`

- `mouseover` (passive, throttled 60 ms) → walk up to the nearest block-level
  ancestor that segmentation would have accepted → highlight it faintly.
- The configured modifier held (default: none — hover alone, with a 300 ms
  dwell) triggers a single-segment `translatePage` call and injects the same
  `masha-tr` element used everywhere else.
- Config: `hoverMode: 'off' | 'hover' | 'shift' | 'alt' | 'ctrl'`,
  `hoverDwellMs: 300`.

Reuses the cache, so hovering a paragraph on an already-translated page is
instant and free.

### 3.2 Compose: triple space

`entrypoints/content/compose.ts`

- A `keydown` listener on `input`, `textarea` and `[contenteditable]`.
- Three `Space` presses within `composeWindowMs` (default 900) with no other
  key between them triggers translation of the field's current value.
- The three spaces are removed, the value is replaced with the translation, and
  the caret is restored to the end. An `input` event is dispatched afterwards so
  React and Vue controlled components see the change — without it the framework
  overwrites the translation on its next render, which is most of the sites
  worth using this on.
- **Undo must work.** The replacement goes through `document.execCommand('insertText')`
  where available so the browser's own undo stack keeps the original; only where
  that fails does it fall back to direct value assignment plus a one-step
  in-extension undo (Ctrl+Z within 5 s restores).
- Config: `composeEnabled`, `composeTrigger: 'triple-space' | 'off'`,
  `composeTargetLang` (may differ from the reading target — you read Japanese
  into English but write English into Japanese).

### 3.3 Tests

- `compose.test.ts` (core half) — the trigger state machine: three spaces fire;
  three spaces with a letter between them do not; spaces outside the window do
  not; the trigger resets after firing.
- Hover: the ancestor-selection rule is a `core/` function
  (`nearestTranslatableBlock(NodeSummary[], id)`) and is tested there.

---

## 4. M3 — Site profiles

Generic segmentation is right most of the time and wrong on exactly the sites
people use most, because a search result page, a timeline and a comment thread
are not articles.

`core/profiles/` — one module per profile, all data, no DOM:

```ts
export interface SiteProfile {
  match: RegExp;                    // against location.href
  articleSelector?: string;         // override findArticleRoot entirely
  segmentSelectors?: string[];      // treat these as blocks regardless of scoring
  skipSelectors?: string[];         // never translate these
  observeSelector?: string;         // narrower mutation root for feeds
  inject?: 'after' | 'append' | 'title-attr';
  rtlAware?: boolean;
}
```

Profiles to ship: a general search engine profile (result title + snippet, not
the URL or the ad label), a timeline profile (post body, not handles, counts or
timestamps), a threaded-discussion profile (comment bodies, preserving nesting),
and a news profile (headline, standfirst, body; not the cookie banner).

`core/profiles/registry.ts::profileFor(url): SiteProfile | null`, tested with a
URL table. Profiles are **data, and overridable by the user** in the options
page, so a site that changes its markup does not require a release.

---

## 5. M4 — Subtitles

Two shapes: a video with a subtitle track, and a video without one.

### 5.1 Track path (preferred, cheap)

`entrypoints/content/subtitles/track.ts`

- Find `<video>`, read `video.textTracks`; set the chosen track's `mode` to
  `'hidden'` so cues fire without the browser rendering them.
- On `cuechange`, translate the active cue — with a **lookahead** of the next
  `prefetchCues` (default 5) so the translation is ready before the cue is due.
- Render into an overlay positioned over the player, not into the track: the
  original stays where the site drew it, the translation goes beneath.
- Cue-level cache keyed on cue text; a rewatched or looping section costs nothing.

### 5.2 Audio path (fallback)

`entrypoints/content/subtitles/audio.ts`

- Capture with `MediaElementAudioSourceNode` → `AudioWorklet` → 16 kHz mono PCM.
- Stream to Lemonade's `WS /realtime` (port from `GET /v1/health`'s
  `websocket_port`), translate each finalised utterance, render like the track path.
- **Only on explicit opt-in per site.** Capturing page audio silently is not
  something an extension should ever do.

### 5.3 Meetings

The same audio path, with two differences: the overlay is a running transcript
panel rather than two lines over a video, and speaker changes break the
transcript into turns (from the meeting DOM where the site exposes an active
speaker, otherwise by silence gap).

### 5.4 Files and tests

`core/subtitles/cue.ts` — `mergeCues`, `shouldTranslateCue`, the lookahead
window, and the timing policy. All browser-free and unit-tested:
cue merging joins a sentence split across two cues; a cue that is only
`[Music]` or a speaker label is skipped; the lookahead never reorders.

---

## 6. M5 — Images and comics

This is where the bridge earns its existence. The pipeline is the one already
measured in `packages/xian-vl/src/xian/ocr/` — 110 ms median on a region-sized
frame — rather than a second implementation in WASM.

### 6.1 Flow

1. Content script collects the image (`fetch` the `src` as a blob; for
   cross-origin images without CORS, ask the background to fetch it with the
   extension's host permissions).
2. `POST /ocr` to the bridge → blocks with quads.
3. Translate the block texts through Lemonade, batched, glossary applied.
4. Either:
   - **overlay mode** — draw translations in a positioned `<canvas>` layer above
     the image, boxes and background sampled as MAGE's `InpaintOverlay` does; or
   - **render mode** — `POST /ocr/render` and swap in the returned image.
5. A toggle returns the original; the original `src` is never discarded.

Overlay mode is the default: it is instant, it is reversible, and it does not
re-encode the user's image.

### 6.2 Comics

`mode: "comic"` on the bridge changes the grouping, not the reading:

- Speech balloons are found as connected light regions with dark text, and each
  balloon is one translation unit — a bubble split across three detector boxes
  is one sentence, and translating the three separately produces three
  fragments.
- Panel order is right-to-left, top-to-bottom for manga; left-to-right for
  webtoons and Western comics; taken from a per-site profile with a manual
  override, because guessing wrong reverses the story.
- Vertical text is already handled: `xian.ocr.grouping` detects tategaki from
  quad aspect and flips column order.

### 6.3 Whole-page comic mode

A reader page is a column of images. Comic mode translates them **as the reader
scrolls**, with an `IntersectionObserver` and a two-image lookahead, because a
chapter is eighty images and translating all of them up front is a minute of
waiting for a page the reader will spend ten seconds on.

---

## 7. M6 — Documents

### 7.1 Entry points

- The popup's **Translate a file…** picker.
- A context-menu entry on links to `.pdf`, `.epub`, `.txt`, `.srt`, `.ass`, `.vtt`.
- Chrome's built-in PDF viewer is opaque to content scripts; MASHA offers to
  open the file in its own viewer page rather than pretending to translate in place.

### 7.2 Server-side jobs

Documents go to the bridge, which runs them as **Lemonade jobs**
(`POST /v1/jobs`) rather than as one long HTTP request. This is what makes
"close the browser and come back" possible: the job has pause, interrupt,
resume and query, and it survives client disconnect and server restart.

The extension polls `GET /documents/{id}` and shows progress in the popup. A
job survives the tab that started it.

### 7.3 Per format

| Format | Handling | Where it lives |
|---|---|---|
| **TXT / SRT / ASS / VTT** | Parse, translate each cue/paragraph, re-emit. Bilingual output interleaves; timing is never touched. | New, in the bridge |
| **HTML** | The M1 segmentation, run headless over the file. | Reuses `core/segment.ts` |
| **EPUB** | Per-chapter XHTML, spine and manifest preserved. | ✅ **Luduan already does this** (`ebooklib` + BeautifulSoup) |
| **PDF, text layer** | Extract spans with positions; translate; re-lay-out with the translated text fitted to the original box, shrinking to fit as `_draw_fitted_text` does. | 🔜 **Luduan has this planned** |
| **PDF, scanned** | Page → `xian.ocr` → blocks → translate → render onto the page image. | 🔜 **Luduan has this planned** |
| **Comics (CBZ/CBR/CB7)** | Archive of page images → the M5 comic path. | 🔜 **Luduan has this planned** |

**This milestone is mostly not MASHA's to build.** Luduan's README already
lists text-layer PDF, scanned PDF and comic archives as planned, against the
same `xian` vision pipeline. Building any of it a second time behind the bridge
would be the exact duplication §0 forbids.

So M6 is, in order: **(a)** the formats nobody owns yet — TXT, subtitle files,
HTML; **(b)** a bridge route that hands EPUB straight to Luduan's existing
pipeline; **(c)** the PDF and comic work done *in Luduan*, with the bridge
exposing it. If M6 is reached before Luduan gets there, the code still lands in
Luduan and MASHA calls it — the browser is a front end for this feature, not a
second implementation of it.

Bilingual output for paged formats is a facing-page or interleaved-paragraph
choice; for EPUB it is a per-paragraph interleave, which is what makes a
bilingual e-reader actually readable.

### 7.4 The honest part

Complex PDF — multi-column with floating figures, tables spanning pages,
inline mathematics — is a research problem, not a milestone. The plan here is:
handle single- and two-column text-layer PDFs well, handle scanned pages via
OCR, and **detect and refuse** the cases that will produce a mangled document
rather than producing one. A document that comes back saying "this PDF has
structure MASHA cannot preserve; translate as plain text instead?" is a better
product than one that silently scrambles a table.

---

## 8. M7 — Glossary, expertise, context

Cross-cutting, and small because the work is already done elsewhere.

### 8.1 Glossary

`GET /glossary` on the bridge returns the wiki glossary MAGE already builds
(`VLProcessor.load_glossary_from_wiki`) — source term → canonical target term.
MASHA merges it with a user list from the options page.

Injection follows what the Xian repo settled on: terms **relevant to the
current text only**, capped, longest-first, rendered as reference pairs ahead of
the request. Sending five hundred irrelevant pairs with every paragraph is how
a glossary makes translation worse.

### 8.2 Expertise

A `domain` string in config, injected into the system prompt as a role. Ships
with a short list (medicine, law, software, finance, games, academia) and a
free-text field. Per-site overrides live in the site profile, so a medical
journal is always translated by the doctor.

### 8.3 Context

Already MASHA's differentiator for selections; M1 extends it to pages. Each
batch carries the page title and the article's opening paragraph as reference —
capped as `MAX_CONTEXT_CHARS` already caps selection context. A translated
paragraph knows what the article is about.

---

## 9. Cross-cutting

### 9.1 Permissions

Today: `storage`, `contextMenus`, `<all_urls>`.

Adding: `activeTab`, `scripting`, `webNavigation` (SPA route changes),
`offscreen` (Chrome, for audio capture), `downloads` (translated documents).

`<all_urls>` is already the widest possible host permission and does not widen.
But an extension that reads every page should say so precisely: the options page
gets a **plain-language permissions section** explaining what is read, what is
sent, and where — with the honest answer that everything goes to a server on
this machine, and that MASHA is unusable if that server is not running.

### 9.2 Failure

Every feature degrades to *the page as it was*:

- Lemonade unreachable → one dismissible notice, no retry storm, features
  requiring it greyed rather than failing on click.
- Bridge absent → images, comics and documents hidden entirely.
- A segment that fails → its original stays, marked faintly; the rest of the
  page still translates. One bad paragraph must not lose the article.

### 9.3 Performance budgets

| Operation | Budget |
|---|---|
| Article detection + segmentation, 200-block page | < 50 ms |
| First translated paragraph visible | < 2 s |
| Hover translation, cache hit | < 16 ms (one frame) |
| Compose replacement | < 1.5 s |
| Cue lookahead | ready ≥ 1 cue ahead at 1× playback |

### 9.4 Testing

- **`core/` — vitest**, no browser. Every algorithm above lands here.
- **Integration — Playwright** against saved page fixtures, checking injection,
  idempotence, undo, and the observer loop guard.
- **Bridge — pytest**, in `packages/xian-bridge/tests/`, reusing the existing
  `xian.ocr` fixtures.
- **A corpus**, as MAGE has one: twenty saved pages across the profile classes,
  asserting article detection and segment counts. Article detection is exactly
  the kind of heuristic that regresses invisibly.

### 9.5 Localisation

MASHA's own UI is currently English-only. It should route through the same
`packages/shared-types/locales` dictionaries the rest of the ecosystem uses,
generated by `localize.cli`. Deferred to after M2 but noted so the strings are
not hardcoded on the way there.

---

## 10. Sequencing

| # | Milestone | Depends on | Ships |
|---|---|---|---|
| **M0** | Bridge skeleton + health detection + vitest harness | — | Nothing user-visible; unblocks everything |
| **M1** | Bilingual pages | M0 (harness only) | The headline feature |
| **M2** | Hover + compose | M1 | The daily-use features |
| **M3** | Site profiles | M1 | Search, social, news, forums |
| **M4** | Subtitles: track path, then audio, then meetings | M1 cache | Video |
| **M5** | Images, then comics | M0 bridge | Images and manga |
| **M6** | Documents: text formats, then EPUB via Luduan, then PDF *in* Luduan | M0 bridge, M1 segmentation, Luduan's roadmap | Files |
| **M7** | Glossary, expertise, page context | M1 | Quality across everything |

M7 is last in the table and should be pulled forward the moment M1 lands: it is
the smallest milestone and it improves every other one.

---

## 11. Risks

1. **Article detection is a heuristic and will be wrong.** Mitigated by site
   profiles, a corpus test, and a visible "translate everything instead"
   escape hatch. It will still be wrong sometimes.
2. **Framework-controlled inputs fight the compose feature.** Dispatching
   `input` events covers React and Vue; some editors (CodeMirror, ProseMirror,
   Slate) need their own handling and are explicitly out of scope for M2.
3. **The observer loop.** An observer that sees its own injections is an
   infinite loop that pins a core. Guarded, and tested for directly.
4. **Positional batch mapping.** Called out in §2.4 because it is the failure
   that produces confident, wrong output with no error — the same trap the MAGE
   pipeline hit.
5. **Local models are slower than cloud APIs.** A 60-paragraph page against a
   1.8B model on a modest GPU is not instant. Streaming injection is the
   mitigation: the reader starts reading before the page finishes.
6. **The bridge is an attack surface.** Loopback-only, extension-origin CORS, no
   filesystem paths accepted from the client — only uploaded bytes.
7. **Scope.** Seven milestones is a long road, and M6 in particular is large
   enough to be its own project. M1–M3 is a coherent, shippable product on its
   own; everything after is genuinely optional.

---

## 12. Open questions

- **Does the bridge ship with MAGE, or separately?** Reusing MAGE's install
  means one thing to run; a standalone service means MASHA works without MAGE.
- **Who builds PDF — Luduan or the bridge?** This plan says Luduan, and the
  bridge exposes it. Worth confirming, because it makes M6 largely a
  scheduling question about Luduan rather than work on MASHA.
- **Does the comic bubble-grouping live in `xian.ocr` or in Luduan?** MASHA's
  M5 and Luduan's comic-archive item want the same code. `xian.ocr.grouping`
  is the natural home; it already owns tategaki detection.
- **Should the disk cache be shared with MAGE's `SessionStore`?** A term
  translated in a game and on its wiki page are the same term.
- **How much of the audio path is worth building** before Lemonade's realtime
  transcription is exercised at length? M4's audio half is the least certain
  estimate in this document.
