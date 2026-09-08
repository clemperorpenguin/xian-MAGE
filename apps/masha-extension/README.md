# MASHA — Multilingual Access & Site Handling Assistant 🌐

MASHA is a browser extension that translates the web **on your own machine**.
Every model call goes to a local [Lemonade Server]; no page you read, no
document you open and no image you translate leaves the computer it is on.

It is a spoke of the [Xian ecosystem](../../README.md): MAGE translates games,
Luduan translates books, MASHA translates the browser. They share one model
hub, one glossary, and one set of prompts, so a term translated one way in a
game is translated the same way on a wiki page about it.

**Status legend** — this README describes where MASHA is going as well as where
it is. Nothing here is aspirational without saying so.

| | |
|---|---|
| ✅ | works today — install the extension and use it |
| 🔨 | partly there; the entry says what is missing |
| 📋 | planned — see [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) |

Everything below except documents is switched on in the popup and off by
default. A translator that started rewriting pages and capturing audio the
moment it was installed would not be one you would install; the reading
features are one toggle each, and the ones marked *needs the bridge* also need
the [local service](#the-bridge) running.

---

## 📰 Reading the web

- ✅ **Selection translation.** Select anything, right-click → *Translate with
  MASHA*. The translation appears in a bubble beside it with **Show original**
  and **Copy**; the page itself is never rewritten.

- ✅ **Context-aware by default.** MASHA sends the page title and the
  surrounding section to the model as *reference*, and asks it to translate
  only your selection. This is the whole reason it exists: a snippet
  translator sees `banco` and guesses, while MASHA can see that the paragraph
  is about a park and answer "bench" — or about interest rates and answer
  "bank". The same discipline resolves pronouns, gendered agreement,
  honorifics and domain jargon.

- ✅ **Compose in your own language.** In any editable field, a selection is
  replaced in place rather than shown in a bubble, so you can write in one
  language and send in another.

- ✅ **Bilingual pages.** *Translate this page* in the popup: read the
  translation *underneath* each paragraph rather than instead of it. MASHA
  finds the article and leaves the navigation, adverts and comment chrome
  alone, so the page still looks like the page. Original and translation together is the
  point: it is how you read something and learn the language at the same time.
  A feed that loads more as you scroll keeps being translated; *Undo* puts the
  page back.

- ✅ **Hover to translate.** Point at a paragraph, hold the modifier, and its
  translation appears below it. The paragraph is the unit — never the word,
  never the sentence — because a paragraph carries enough context to be
  translated correctly and enough meaning to be worth reading.

- ✅ **Triple-space to send.** Type in your language in any input box and press
  space three times; MASHA replaces what you typed with the translation. Search
  in a language you do not write, argue on a forum in one you do not speak.

- ✅ **Site profiles.** Search results, social timelines and news sites each
  have a shape, and the generic article-finder does not fit all of them. MASHA
  ships tuned profiles for the handful of sites people actually read all day.

## 📚 Documents

- 📋 **PDF, with the layout intact.** Columns stay columns, tables stay tables,
  figures stay where they were. Text that only exists as pixels is read with
  the same OCR engine MAGE uses on game screens.

- 🔨 **EPUB, TXT, HTML, and subtitle files** (SRT/ASS/VTT), bilingual or
  translation-only, as you choose. Pick a file in the popup and watch the job
  run. The bridge parses all five formats and reassembles them; what it does
  not do yet is call the model, so the output comes back marked `[translated]`
  rather than translated. *Needs the bridge.*

- 🔨 **Long documents survive the trip.** A four-hundred-page book is a job on
  the server, not a tab you must not close. The job and its pause/resume/cancel
  controls are the bridge's, and the popup shows progress — what is missing is
  the buttons for them, and a job list that outlives the popup being closed.

## 🎞 Video and voice

- ✅ **Bilingual subtitles** on the major video sites. Where a site publishes a
  subtitle track MASHA translates that; where it does not — and only if you ask
  — it captures the audio, streams it to Lemonade's realtime Whisper socket at
  the 16 kHz mono PCM16 that endpoint requires, and translates the transcript.
  Capturing the audio leaves playback audible: the tap is a branch of the
  graph, not a diversion of it.

- 📋 **Live meetings.** Running captions for calls, translated as they are
  spoken, so a meeting in a language you are still learning is a meeting you
  can attend.

## 🏞 Images and comics

- ✅ **Any image on any page.** Right-click it. MASHA reads the text out of it
  and paints the translation back over the original, matching the background so
  the result still reads as artwork rather than as a page of subtitles.
  *Needs the bridge, with its OCR engine.*

- ✅ **Manga, manhwa and comics.** Panels are translated as you scroll, in
  reading order — right-to-left for manga, which is the default. Lines are
  grouped into blocks before translation, so a two-line balloon is one request
  that reads as one sentence rather than two halves translated in the dark.
  A chapter is readable the day it is posted rather than the month it is
  scanlated. *Needs the bridge, with its OCR engine.*

## 🧠 Getting the words right

- ✅ **Style.** Tell MASHA the register you want and it carries it into every
  translation.

- ✅ **Glossary.** The names, places and terms you care about, translated your
  way, every time — shared with MAGE and Luduan, so the whole ecosystem agrees
  with itself. Add terms in the popup. Editing one invalidates the cache rather
  than leaving yesterday's wording on the page. *Needs the bridge.*

- ✅ **Domain expertise.** Point MASHA at a field — medicine, law, a particular
  game — and it translates like someone who knows it.

- ✅ **Translated once, everywhere.** Repeated text is answered from memory, and
  from the store MAGE and Luduan share, before it is answered by the model.

---

## Why local

Every feature above runs against a Lemonade server on your own machine.

That is not only a privacy position, though it is that too: a browser extension
that translates everything you read is the single most sensitive piece of
software you could install, and MASHA is built so that the question of what it
uploads has the answer *nothing*.

It is also what makes the rest affordable. Translating every paragraph of every
page you read would be ruinous metered against a cloud API; against a model on
your own GPU it is free, so MASHA can translate generously — whole pages,
whole documents, every frame of a subtitle track.

## Requirements

- A running [Lemonade Server] (default `http://localhost:13305/v1`).
- A translation model. MASHA defaults to the `Xian-Ultra` collection that MAGE
  registers; if it is not installed, pick any model in the popup.
- For images, comics, documents and the shared glossary: **the bridge running**
  (below). Everything else — pages, hover, compose, selections, subtitles —
  needs only Lemonade.
- For audio subtitles: a Whisper model Lemonade can load (`Whisper-Tiny` by
  default; change it in the popup).
- Every feature past selection translation is **off until you turn it on** in
  the popup.

## The bridge

OCR, document jobs, the shared glossary and the shared translation cache are
not things a browser extension can do for itself, so they live in a small local
service, `packages/xian-bridge`, on `127.0.0.1:13306`:

```bash
uv run -m xian_bridge          # --host / --port to override
```

📋 MAGE will start it, so there is one thing to install rather than two. Until
then, run it yourself with the line above.

MASHA probes `GET /health` when you open the popup and shows only what the
bridge says it can do — a missing bridge is a shorter popup rather than a
button that fails when pressed. OCR is the backend that varies: it needs
`xian-vl[ocr]` (PP-OCRv5 through ONNX Runtime), and without that extra `/ocr`
answers `501` and `/health` says `"ocr": false`, rather than handing back
placeholder text for the model to dutifully translate.

The service listens where every page in your browser can reach it, so it also
checks the `Host` and `Origin` headers on every request; see the module
docstring in `xian_bridge/app.py` for what each guard is for and what is still
open by design.

## Browser support

| Browser | Status | Build |
| --- | --- | --- |
| Chrome / Edge / Chromium | ✅ Supported | `npm run build` (chrome-mv3) |
| Firefox | ✅ Supported | `npm run build:firefox` (firefox-mv2) |
| Falkon | ⛔ Not as an extension | needs a plugin — see [docs/FALKON.md](docs/FALKON.md) |

Falkon (QtWebEngine) does not implement the WebExtensions API. The code is
arranged so a Falkon plugin reimplements one interface
(`src/platform/bridge.ts`) and reuses the browser-free `src/core/` logic
unchanged.

## Development

```bash
cd apps/masha-extension
npm install
npm run compile        # type-check
npm test               # vitest — the browser-free core
npm run build          # chrome-mv3 -> dist/chrome-mv3
npm run build:firefox  # firefox-mv2 -> dist/firefox-mv2
npm run dev            # live-reload dev build
```

The bridge's own tests run from the repository root:

```bash
uv run pytest packages/xian-bridge/tests
```

### Install (developer mode)

- **Chrome/Edge**: `chrome://extensions` → Developer mode → **Load unpacked** →
  `dist/chrome-mv3`.
- **Firefox**: `about:debugging` → This Firefox → **Load Temporary Add-on** →
  `dist/firefox-mv2/manifest.json`.

## Configuration

The popup is the whole of MASHA's UI. It sets the Lemonade URL, the source and
target language, style terms and domain expertise; it switches the reading
features on and off one at a time; it starts a document job and shows its
progress; and it adds glossary terms. Settings persist through
`chrome.storage`, and every open tab picks up a change without a reload.

## Architecture

```
src/
├── core/          # browser-free: prompt builder, translator, batch pipeline,
│   │              #   segmentation, cache keys, language detection
│   ├── compose/   #   the triple-space trigger state machine
│   ├── dom/       #   article finding, framework-free
│   ├── profiles/  #   per-site selectors, matched on the URL
│   └── subtitles/ #   cue policy and merging
├── platform/      # bridge.ts — the one interface a platform implements
├── utils/         # config + Lemonade URL helpers
└── entrypoints/
    ├── background.ts   # the only code that touches the network
    ├── content.ts      # composition root: which features are on, and routing
    ├── content/        #   selection, page, hover, compose, subtitles,
    │                   #   images, comic — each returns its own detach
    └── popup/          # the settings and controls for all of it
```

Three rules follow from where the code sits:

* **Only the background talks to the network.** An MV3 content script's `fetch`
  is judged by the *page's* CORS policy, not the extension's, so a call to
  Lemonade or to the bridge from a content script fails on most of the web.
  Every request in `content/` is a message to the worker.
* **Every feature returns a detach function.** `content.ts` holds them, and
  drops and re-attaches the set whenever settings change — which is why a
  toggle in the popup takes effect in an already-open tab.
* **Page translations are siblings, never rewrites.** Each one is a
  shadow-rooted `<masha-tr>` after its source block, anchored by a stable
  `data-masha-node` id, so undo is exact and the site's CSS cannot reach in.

Two rules hold the *port* together, and every feature above is built around
them:

1. **`core/` never touches a browser API.** It is the unit a Falkon plugin
   reimplements, and it is the only part that can be unit-tested without a
   browser.
2. **`PlatformBridge` is the only seam.** Anything that needs the DOM, storage
   or the network is named there. The WXT build realises that contract across
   `background.ts`, `content.ts` and the popup rather than as a single class —
   an MV3 extension has no one process that can hold all three — so the
   interface is the checklist a port works through, not a base class it
   extends.

`core/` mirrors the Python sources in `packages/xian-vl` and
`packages/shared-types`; [docs/FALKON.md](docs/FALKON.md) is the porting
contract.

## Licence

GPL-3.0-or-later, like the rest of the ecosystem. See [LICENSE](../../LICENSE).

[Lemonade Server]: https://lemonade-server.ai/
