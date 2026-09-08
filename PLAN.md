# RST → MAGE: Borrow Review & Rebuild Report

**Status:** Report + open questions. Implementation plan to follow once questions are answered.
**Date:** 2026-09-05
**Repos:** `/var/home/clem/src/testing/RSTGameTranslation` (reference) · `/var/home/clem/src/xian-vl` (target)

---

## Context

MAGE's live in-place translation ("Lens") is shipped but experimental and gated off by
default (`KEY_EXPERIMENTAL_LIVE`, `apps/mage-client/src/mage/settings_keys.py:61`). Its
ceiling is set by one architectural choice: **a single VLM call does detection, reading
and translation together** (`packages/xian-vl/src/xian/grounding.py:ground_and_translate`).
That costs ~1–5 s per changed frame against a 700 ms tick, which the repo's own roadmap
already names as the blocker:

> *"Remaining: a local ONNX text-detection pass to supply boxes (sub-second end to end,
> with the LLM only translating the recognized lines), which would make this genuinely
> real-time."* — `docs/ROADMAP.md:113`

RSTGameTranslation is a mature Windows implementation of exactly that architecture —
cheap local OCR, geometric block reconstruction, one batched LLM call for text only — and
it has been tuned against real games for several release cycles. This report extracts what
is worth taking, what is not, and what has to be measured before committing.

**Licence:** RST's `LICENSE.md` is the full GPLv3 text (the README's "BSD-style
attribution" line is wrong). xian-vl is GPL-3.0-or-later. Borrowing logic is clean;
attribution in `NOTICE`/headers is the only obligation.

---

## 1. What RST actually does

### 1.1 Loop shape — poll, latch, throttle

| Mechanism | Value | Where |
|---|---|---|
| Capture tick | `DispatcherTimer` @ **250 ms** | `src/MainWindow.xaml.cs:371-374` |
| OCR-in-flight latch | `_bOCRCheckIsWanted` — one OCR at a time, never queued | `src/MainWindow.xaml.cs:92-98` |
| Hard floor between OCR calls | **200 ms** (`_minOcrInterval`) | `src/Logic.cs:26-27, 2162` |
| Single-shot mode | `isStopOCR` latch when auto-OCR off | `src/MainWindow.xaml.cs:92-98` |

Capture is GPU-native (Windows Graphics Capture → D3D11 staging texture → Bitmap,
`src/GraphicsCaptureService.cs`, `src/Direct3D11Helper.cs`), with cursor capture disabled
and the yellow capture border suppressed. The last frame is cached and re-served when
`TryGetNextFrame()` has nothing new, so the poll never stalls.

**Notably: RST does no pixel-level change detection at all.** Every permitted tick runs
OCR. All savings come *after* OCR, on the text.

### 1.2 Change detection — on text, not pixels

This is the single most important difference from MAGE. `Logic.ProcessReceivedTextJsonData`
(`src/Logic.cs:540-763`) runs three gates in order:

1. **Confidence filters.** Characters below `GetMinLetterConfidence()` (0.1) are dropped
   before grouping; lines below `GetMinLineConfidence()` (0.2) are dropped after grouping
   (`src/Logic.cs:1615`).
2. **Ignore phrases.** User-configured exact / contains / regex patterns strip fixed HUD
   chrome *before* the hash is computed, so a always-on-screen label never registers as
   change (`src/Logic.cs:1092-1241`).
3. **Content hash + fuzzy similarity + settle time** (`src/Logic.cs:586-643`):
   - `GenerateContentHash` — block count + each fragment lowercased, punctuation-stripped,
     `|`-joined. Cheap, order-sensitive, *not* a pixel hash (`src/Logic.cs:1678-1715`).
   - `IsTextSimilar(threshold=0.75)` — language-aware fuzzy match (`src/Logic.cs:774-931`):
     CJK uses character-set overlap (40%) + character-trigram Dice (50%) + length ratio
     (10%); space-delimited languages use stop-word-stripped keyword Dice, then bigram
     Dice, then Jaccard word overlap, first-to-clear-threshold wins. Strings under 5 chars
     fall back to exact match.
   - **Settle time** (default **0.15 s**, `src/ConfigManager.cs:3102`): when text changes,
     it is *not* translated. It is timestamped. Only when the *same* new text is still
     there after the settle window does translation fire. A wall-clock debounce that
     absorbs OCR jitter and typewriter-style text reveals without a frame counter.

### 1.3 Block detection — engine-agnostic, character-first

`CharacterBlockDetectionManager` (`src/BlockDetectionManager.cs:1-1479`) rebuilds
characters → words → lines → paragraphs itself, deliberately *not* trusting the OCR
engine's own line segmentation. To make that possible, the OCR layer **fabricates
per-character quads** by linearly interpolating across each recognised word's box
(`app/webserver/RapidOCR/process_image_rapidocr.py:479-561`; the same trick in
`src/OneOCRManager.cs:553-620`).

Every threshold is a base pixel value × one global `blockPower` scale (default **5.0**,
calibrated for ~20 px text):

| Stage | Rule | Base |
|---|---|---|
| char→word | horizontal gap (halved+floored at 5 px for non-CJK) | 2.0 px |
| char→line | vertical alignment tolerance | 4.0 px |
| word→line split | large horizontal gap **or** `> 10 × avg char size` | 40 px |
| line→para | `centerDistance > normalSpacing × 2.5 + 7` | 7 px |
| line→para | indentation, unless plausibly centre-aligned | 20 px |
| line→para | font-size delta, or ratio outside [0.7, 1.3] | 5 px |

`normalSpacing = avgLineSize × GetLineSpacingFactor()` (0.63) — expected spacing derived
from font size, not a constant. Vertical/tategaki is auto-detected for East-Asian sources
from four signals (median char aspect, region aspect, tall-char fraction, columnar layout)
and flips all axis logic plus right-to-left column order (`src/BlockDetectionManager.cs:268-332`).

Manga mode adds greedy speech-bubble unioning with thresholds adaptive to *median*
paragraph height/width, plus a validator that breaks apart runaway merges
(>80% page width / >35% height / >10 paragraphs).

### 1.4 Translation — one call per screen, text only

Default (non-manga) path joins **every** on-screen block into a single string with a
literal `##|||##` separator, sends it as one block with `id: "999"`, and splits the reply
back by index (`src/Logic.cs:2680-2690`). One round trip per screen state, no coordinates
in flight, no per-block calls. Request body (`src/Logic.cs:2723-2741`):

```json
{ "source_language": "...", "target_language": "...",
  "text_blocks": [{"id": "999", "text": "a##|||##b##|||##c"}],
  "previous_context": ["...up to 20 prior source texts..."],
  "game_info": "free-text user description of the game" }
```

The prompt is a **user-editable file per backend** (`app/gemini_config.txt`,
`chatgpt_config.txt`, `ollama_config.txt`; defaults at `src/ConfigManager.cs:217-347`) and
is explicitly an *OCR-repair* prompt: "Reconstruct FIRST … fix merged words, jumbled
characters, and OCR artifacts … Translate SECOND". No structured-output API, no schema —
prompt discipline plus defensive parsing.

Multi-key round-robin failover on 401/403/429/quota, capped at 3 retries
(`src/GeminiTranslationService.cs:22-45`, `src/ConfigManager.cs:3043-3059`).

Context sent to the LLM: `previous_context` = the last N source texts
(`GetMaxContextPieces()` — code fallback 3, but the shipped `config.txt` writes 20;
`src/ConfigManager.cs:553, 2020`) filtered by `GetMinContextSize()`.

**No translation cache and no glossary exist in RST** (the `translation_cache.json`
mentioned in `.github/copilot-instructions.md` is stale — nothing reads or writes it).

### 1.5 OCR abstraction

One JSON shape — `{status, results:[{rect:[[x,y]×4], text, confidence, is_character}], …}` —
served by five interchangeable backends:

- **In-process:** OneOCR (P/Invoke into bundled `oneocr.dll`, pipeline created once and
  reused) and Windows.Media.Ocr.
- **Subprocess + TCP socket:** EasyOCR (:9999), PaddleOCR (:9998), RapidOCR (:9997).
  Command is plaintext `read_image|{lang}|{engine}|{charLevel}|{hdr}`; the **image is not
  sent over the socket** — capture already wrote it to `webserver/image_to_process.png`.
  Response framing is decimal byte count + `\r\n` + UTF-8 JSON.
  Lifecycle: preflight checks, spawn, poll the port for up to 90 s, `netstat`-based
  force-kill on teardown (`src/OcrServerManager.cs`, `src/SocketManager.cs`).

RapidOCR runs PP-OCRv4 detection + PP-OCRv5 recognition, mobile models, ONNX Runtime, with
HDR-aware preprocessing (auto-detected CLAHE + bilateral filter + sharpen when
`std < 40` or `mean > 200` or `mean < 55`) and optional upscaling of small crops
(`app/webserver/RapidOCR/process_image_rapidocr.py:106-185`).

### 1.6 Interface and features

**Overlay.** `MonitorWindow` *is* the overlay — a transparent, topmost, `WindowStyle=None`
window holding a `Canvas IsHitTestVisible="False"` onto which one `Border`+`TextBlock` per
block is absolutely positioned (`src/MonitorWindow.xaml:60-66`, `:556-568`). Two Win32
tricks matter:

- `WS_EX_TRANSPARENT | WS_EX_LAYERED` → click-through.
- **`SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE)`** (`src/MonitorWindow.xaml.cs:145-154`)
  → the overlay is **invisible to screen capture**. It never appears in a stream/recording,
  and — critically for us — **it cannot contaminate the app's own next capture.** This is a
  structurally cleaner solution to the exact problem MAGE solves with paint-box masking
  (`live_lens.py:491-518`). Windows 10 falls back to click-through only.

Font auto-fit is a bounded binary search (max 8 iterations) measuring `DesiredSize` against
the original OCR box, clamped to configurable min/max (10–68 pt), **memoised in a static
dict keyed by `{textLen}_{w}_{h}_{minFont}_{maxFont}`** capped at 100 entries
(`src/TextObject.cs:245-372`). When `IsAutoSetOverlayBackground()` is on, the box background
is the dominant colour sampled *from the screenshot under the box*
(`ColorUtils.GetDominantColor` — grid sample every `min(w,h)/10` px, quantised to 3 bits per
channel, modal bucket) with a luminance-derived contrasting text colour — so overlays blend
with the game art with no per-game styling.

**Region and window selection.** Drag-rectangle selector per monitor with live size readout;
returns a `TranslationAreaInfo` carrying bounds + screen index + **the DPI scale captured at
selection time** (`src/TextObject.cs:21-40`). Up to **5 saved areas** recalled with Alt+1…5,
persisted per **game profile**. Window capture enumerates top-level windows with icons
(`WindowSelectorPopup`), and the window rect is **re-queried on every 250 ms tick**
(`src/MainWindow.xaml.cs:1998-2020`) so the capture follows a moved/resized window with no
user action; window-closed is detected and handled.

**Exclude regions** — up to 5 sub-rectangles masked out of the bitmap *before* OCR
(`ApplyExcludeRegionsMask`). Combined with ignore-phrases, this is how RST stops an animated
minimap or a ticking clock from firing the change gate every frame.

**Chat box** — a separate draggable, resizable, semi-transparent history window
(`RichTextBox` of original/translated pairs, not per-speaker), with a Both/Translated/Source
mode cycle, font size controls, borderless mode, auto-clear timer, right-click Copy/Speak,
and its own options dialog with live preview (Apply/Cancel staging, unlike the rest of the
app's write-through config).

**Settings** — 12 tabs (Language · OCR & Screen · OCR Settings · Context & Overlay ·
Ignore Phrases · Exclude Regions · Translation · TTS · Hot Keys · Audio · Clipboard ·
Game Profile). Storage is a flat `key=value` `config.txt` plus one small editable text file
per LLM service for its prompt, plus a `Profiles/` folder. **Write-through and
hot-reloaded**: every setter saves immediately, every consumer reads live — no Apply button,
no restart.

**Hotkeys** — 14 defaults, all Alt+letter (G start/stop, Q select area, F overlay,
C chatbox, B show area, K audio, P settings, L log, V swap languages, R clear areas,
H clear selected, T retry translation, X exclude regions, 1–5 saved areas), user-remappable
live. Delivery is **triple-redundant**: `RegisterHotKey`/`WM_HOTKEY`, a `WH_KEYBOARD_LL`
hook, *and* 30 ms `GetAsyncKeyState` polling, with a 250 ms per-function dedup reservation
so the three paths don't triple-fire (`src/KeyboardShortcuts.cs:297-364, 585-805`) —
defensive against fullscreen/anti-cheat input grabs. MAGE's evdev/pynput split is the same
idea for the same reason.

**Onboarding** — themed splash with a GitHub-hosted version check, then a 5-step quickstart
wizard (Welcome → Language → OCR engine → Translation service → Summary) on first run,
re-launchable from the toolbar. Status LEDs in the main window for Start / Audio / OCR /
Overlay state.

**Model downloads** — one shared pattern worth copying wholesale
(`src/WhisperModelDownloader.cs`): stage to `*.part`, resume via HTTP `Range`, verify
against `Content-Length`, **atomic rename only after verification**, delete on mismatch
rather than leaving a half-file that crashes native inference, 3 retries with backoff,
cancel on window close, and a hard-coded catalog of `(filename, exact byte size, quality
tag, recommended)` so the picker shows sizes without a network round trip.

**TTS/STT** — TTS fires automatically on each new translation (gated on "started" so it
never speaks stale text after Stop), serialised through a single-consumer queue with
duplicate suppression, with an option to strip a leading `"Speaker: "` prefix. STT captures
**system audio output** (`WasapiLoopbackCapture` — the game's sound, not the mic) with
energy VAD in 30 ms frames, 300 ms pre-roll, 250 ms trailing silence, a bounded channel to a
single decoder, then aggressive cleanup: repeat-collapse for stuck decoders, a regex denylist
for hallucinated filler ("thank you for watching", `[Music]`, CJK subtitle boilerplate), and
substring dedup against the last 5 lines. Accepted lines enter the *same* text-object
pipeline as OCR via a 500 ms batch timer — so audio and screen text share context, history
and TTS. MAGE's Raid/Cinematic modes are the equivalent, but the VAD, hallucination denylist
and dedup are more developed in RST.

---

## 2. What MAGE does today

| Stage | MAGE | File |
|---|---|---|
| Capture | `QScreenCapture` session (PipeWire/XCB/WGC/AVFoundation) with `grim -g` / spectacle / GNOME DBus screenshot fallback | `capture/stream.py`, `capture/screen.py` |
| Tick | 700 ms, single-flight, drops overlapping ticks | `live_lens.py:363-428` |
| Change gate | `imagehash.phash(hash_size=16)`, Hamming > 21, with own-overlay boxes masked out of both frames | `live_lens.py:72-105, 491-526` |
| Region retention | 32×32 grey crop, mean abs intensity diff ≤ 6.0 → keep prior translation | `live_lens.py:88-105, 447-489` |
| Detect+read+translate | one streamed VLM call, JSON array of `{box,original,translated}`, boxes normalised 0–1000 | `grounding.py:503-596` |
| Box hygiene | drop frame-sized (>80%), drop containers (≥2 children), largest-first overlap suppression (>50%) | `grounding.py:389-427` |
| Paint | click-through `InpaintOverlay`, background sampled from a band *outside* each box, font shrunk to fit then word-wrapped | `ui/inpaint_overlay.py`, `live_lens.py:132-170` |
| Memory | SQLite + FTS5 with per-character CJK segmentation, rolling LLM digest | `xian/session_store.py`, `xian/game_state.py` |
| Telemetry | TTFT / throughput / VRAM ring buffers, Markdown + JSONL export | `mage/telemetry.py` |

MAGE's engineering *quality* here is high and several of its mechanisms have no RST
counterpart — the masked change gate, per-region carry, streamed box-by-box painting,
and the whole calibrated-against-a-real-corpus test discipline
(`benchmark_corpus.py`, `test_live_lens_benchmark.py`).

---

## 3. The central finding

MAGE **already tried** a local OCR sidecar and retired it. The measurement is recorded in
`packages/xian-vl/tests/test_grounding_benchmark.py:48-51`:

> *"What the removed OCR sidecar cost on a region-sized frame: **~342 ms to detect and
> read**, plus a separate batch translation (**~1.9 s** measured on a small NPU model).
> Kept as the historical bar this path had to clear."* — vs. **~1.0 s** for one grounding
> call, first line painted at ~460 ms.

Read that again: **OCR was not the slow part.** 342 ms is comfortably inside a 700 ms tick.
The sidecar lost because the *translation* call after it cost 1.9 s, and it was paid on
**every changed frame** — exactly as often as the grounding call, because the change gate
was pixel-based and knew nothing about whether the *text* had changed.

That is precisely the gap RST closes, and it closes it with three mechanisms MAGE has none
of:

1. **Text-level change gating.** Once OCR is cheap, you can compare *strings* rather than
   pixels. A frame whose pixels moved (particle effects, an animated HUD, a blinking
   cursor, a scrolling combat log) but whose dialogue is unchanged costs **342 ms and zero
   inference** instead of a full VLM round trip.
2. **Settle-time debounce.** Text that is mid-reveal is never sent at all.
3. **A translation cache keyed on source text** — which neither project has, and which is
   nearly free once OCR gives you stable strings. A re-entered menu, a repeated NPC line,
   a tooltip re-hovered: zero inference.

The hypothesis this report exists to test:

> **With OCR supplying text and boxes, the translation call fires on a small fraction of
> ticks rather than all of them. The comparison that retired the sidecar measured
> per-changed-frame cost; the number that matters is cost per *unit of gameplay*, and on
> that axis the sidecar architecture has never been measured.**

Phase 1 exists to measure exactly that, against the real corpus, before a line of
production code is written.

Secondary benefits that fall out of the same change and do not depend on the timing result:

- **Boxes come from a detector, not a generative model.** Every failure mode
  `grounding.py` defends against — frame-sized boxes, container boxes, duplicate boxes,
  `bbox_2d` vs `box` key drift, truncated JSON arrays, unbalanced braces from small models
  (`grounding.py:170-197`) — is a symptom of asking an LLM to emit geometry. A detector
  returns quads or it errors.
- **Small models become usable.** `_warn_if_nothing_translated` (`live_lens.py:586-611`)
  exists because a 4B model answers the grounding prompt with an empty ```json fence and
  all twelve lines silently fall through to their source text. Plain text-in/text-out
  translation is a far lower bar.
- **The NPU becomes useful for live mode.** `docs/ROADMAP.md:82-93` is explicit that there
  is no NPU vision backend on Linux, so grounding is GPU-locked. A text-only translation
  call routes to FastFlowLM today.

---

## 4. Borrow list, ranked

### Tier 1 — take, pending Phase 1 confirmation

| # | Borrow | From | Into |
|---|---|---|---|
| 1 | **Local OCR stage** (RapidOCR ONNX; `rapidocr_onnxruntime`, `onnxruntime`, `cv2` are already resident in the venv but undeclared and unimported) | `app/webserver/RapidOCR/` | new `packages/xian-vl/src/xian/ocr/` |
| 2 | **Text-level change gate** — normalised content hash + language-aware fuzzy similarity | `Logic.cs:774-931, 1678-1715` | `live_lens.py`, replacing/augmenting the phash gate |
| 3 | **Settle-time debounce** | `Logic.cs:586-643` | `live_lens.py` |
| 4 | **Text-keyed translation cache** (LRU + optional persist) | *neither project has this* | `xian/` — new |
| 5 | **Batched single-call translation** with a separator contract | `Logic.cs:2680-2690` | new `xian/batch_translate.py` |
| 6 | **Character-level box synthesis** so block grouping is engine-agnostic | `process_image_rapidocr.py:479-561` | OCR adapter |
| 7 | **Geometric block reconstruction** (char→word→line→para, scale-driven thresholds, tategaki detection) | `BlockDetectionManager.cs` | new `xian/blocks.py` |
| 8 | **Confidence + ignore-phrase pre-filters** before hashing | `Logic.cs:1092-1241, 1615` | OCR adapter |

### Tier 2 — pipeline extras, independent of the timing result

| # | Borrow | From |
|---|---|---|
| 9 | **HDR/low-contrast adaptive preprocessing** (auto CLAHE + bilateral + sharpen on `std<40 ∨ mean>200 ∨ mean<55`) | `process_image_rapidocr.py:106-160` |
| 10 | **`game_info` free-text field** — user describes the game once, injected into every prompt. MAGE has no equivalent (verified: no `game_info` anywhere in the Python tree) | `Logic.cs:2726` |
| 11 | **User-editable prompt templates**, one small text file per backend | `app/*_config.txt` |
| 12 | **Auto-calibrated block scale** from median text height (`avgTextHeight/20.0`) | `BlockDetectionManager.cs:1591` |
| 13 | **Clipboard-monitor translation path** (300 ms debounce) — trivial on Linux, orthogonal feature | `ClipboardMonitor.cs` |
| 14 | **STT hardening**: energy VAD with pre-roll/trailing-silence, repeat-collapse for stuck decoders, hallucination denylist, substring dedup over the last N lines, batch-before-translate timer | `localWhisperService.cs:36-69, 780-808`; `Logic.cs:1889-1953` |

### Tier 3 — interface and feature gaps MAGE has today

| # | Borrow | Why it matters |
|---|---|---|
| 15 | **Exclude regions** — sub-rectangles masked out of the frame *before* OCR | Directly serves the change gate: an animated minimap or a ticking clock stops firing it. MAGE has nothing like this. |
| 16 | **Ignore phrases** (exact / contains / regex), applied *before* the content hash | Same reason. Static HUD chrome never registers as change. MAGE has nothing like this. |
| 17 | **`WDA_EXCLUDEFROMCAPTURE`-equivalent** — make the overlay invisible to capture | Structurally cleaner than MAGE's paint-box masking, *and* keeps overlays out of the user's stream/recording. Needs a Wayland/PipeWire answer — see Q C5. |
| 18 | **Saved areas 1–5 + named game profiles** | MAGE re-selects a region every session. |
| 19 | **Live window-rect re-query each tick** so capture follows a moved/resized window | MAGE's `WindowBinder` exists but is X11/Windows only and is not wired into the live loop's rect. |
| 20 | **Memoised font-fit** keyed by `(len, w, h, min, max)` | MAGE's `_draw_fitted_text` re-runs the shrink loop on every paint of every box. |
| 21 | **Dominant-colour sampling from under the box** for background/text colour | Complements MAGE's outside-band sampling; better where a box sits on a busy background. |
| 22 | **Resumable, verified, atomic model downloads** (`.part` + Range + `Content-Length` check + rename) with a hard-coded size catalog | MAGE's `ModelPullWorker` streams SSE from Lemonade but has no local-model download path; an OCR model download needs exactly this. |
| 23 | **Retry-current-translation** that bypasses all gates | Users need an escape hatch when the gate wrongly holds. |
| 24 | **Quickstart wizard + status LEDs** for start/OCR/overlay/audio state | MAGE's first run drops the user at a tray icon. |
| 25 | **Write-through, no-Apply-button config** | MAGE's `QSettings` is already write-through; the pattern to copy is the *per-backend editable prompt file*, not the storage. |

### Do **not** borrow

- **Image-over-disk IPC** (`image_to_process.png` written every tick). MAGE's in-memory
  `FrameStream` is strictly better; an OCR stage should run in-process or over a Unix
  socket with the buffer, never via a file.
- **Index-based response mapping.** RST maps translations onto blocks by array position
  after splitting on `##|||##`; a dropped separator silently misaligns the whole screen.
  Use ID-keyed mapping with a length check and per-block fallback.
- **The subprocess-per-OCR-engine architecture.** MAGE is already Python; import the
  library.
- **Swallow-all exception handling** (RST's own AI guide flags this,
  `.github/copilot-instructions.md:29`).
- **The 3351-line `Logic.cs` / 5516-line `SettingsWindow.xaml.cs` shape.** Port the
  algorithms, not the structure.

### Explicitly keep from MAGE

Own-overlay masking in the change gate (`live_lens.py:491-518` — replaced a hide-and-regrab
that cost 270 ms/frame and flickered); per-region carry and `_reuse_translations`
(stops wording shimmer); streamed progressive painting; `suppress_overlapping_regions`
(still needed — a detector produces stacked boxes too); session memory; telemetry;
the corpus-benchmark test discipline.

---

## 5. Decisions taken

| # | Decision |
|---|---|
| **D-1** | **Selectable engine.** OCR-first ships as a *second* live engine beside grounding, chosen in Settings. `live_lens.py` dispatches to one of two pipelines. Grounding stays the default until Phase 1 says otherwise, and remains the one-shot bubble path. |
| **D-2** | **Reader chosen by Phase 1 bake-off**, from four candidates: RapidOCR ONNX (in-process), `HunyuanOCR-1.5-GGUF-Updated-Q4_K_M` and `PaddleOCR-VL-1.6-GGUF-Q4_K_M` (both already downloaded on the local Lemonade), and current Qwen-VL grounding as baseline. |
| **D-3** | **Translator: per-line to Hy-MT2, fanned out concurrently, cache-first.** `Hy-MT2-1.8B-GGUF-Q4_K_M` and `Hy-MT2-7B-GGUF-Q4_K_M` are both downloaded locally. No separator contract, no JSON parsing, per-line cache keys fall out naturally. |
| **D-4** | **Phase 1 metrics are purely comparative** — no hand-labelled ground truth. Call count, latency, stability, geometry sanity, cross-reader agreement. |
| **D-5** | **Feature scope:** exclude regions + ignore phrases; window-follow + memoised font fit; retry + status indicators; `game_info` + editable prompt templates. All ship with the rebuild. |

### Consequences worth stating

- **Hy-MT2 is translation-only.** Both variants are labelled `['chat','custom']` on the
  server, so MAGE's router currently treats them as *chat planners* — they would displace
  a real planner if selected. `TRANSLATION_KEYWORDS`
  (`packages/xian-vl/src/xian/omni_router.py:49`) must learn `hy-mt2` / `hunyuan-mt` so
  `is_translation_only_model` claims only the `translation` modality for them.
- **`VLProcessor.get_translation_model_name()` already exists** (`pipeline.py:272`) and has
  **no caller** — a leftover from the retired sidecar. The rebuild reconnects it rather
  than inventing a new resolution path.
- **`PaddleOCR-VL-1.6-GGUF-Q4_K_M` carries no `vision` label**, so `router.vision()` will
  not select it. Phase 1 addresses it by explicit model id; Phase 3 needs either a label
  override or a `_PRODUCT_MODALITIES` entry (`omni_router.py:81`) if it wins.
- **No cross-line context** in the per-line translator. `GameStateAssembler`'s session
  digest and the glossary still apply as a system prompt, so recurring names stay
  consistent, but a pronoun resolved by the previous line will not be.
- Left open, to be resolved by Phase 1 evidence rather than up front: whether the phash
  gate survives as a pre-OCR filter (**Q-C1**), whether the cache persists into
  `SessionStore` (**Q-C3**), whether a Wayland equivalent of `WDA_EXCLUDEFROMCAPTURE`
  exists (**Q-C5**), and how much of RST's char→word→line→paragraph hierarchy is needed
  when the reader already returns line boxes (**Q-E1**).

---

# Implementation Plan

Three phases. **Phase 1 is run independently by the user's local agent** and touches no
production code. Phase 2 turns its numbers into decisions. Phase 3 implements.

---

## Phase 1 — Automated bake-off (run independently)

**Goal:** produce the numbers that decide the reader, the translator, the gate thresholds,
and whether OCR-first beats grounding at all. **No edits to any existing file.** Everything
lands in a new `scripts/bakeoff/` directory.

**Preconditions:** Lemonade running on `:13305` with `HunyuanOCR-1.5-GGUF-Updated-Q4_K_M`,
`PaddleOCR-VL-1.6-GGUF-Q4_K_M`, `Hy-MT2-1.8B-GGUF-Q4_K_M`, `Hy-MT2-7B-GGUF-Q4_K_M` and a
general VLM downloaded (all confirmed present). Corpus at `../game_screenshots` (33 frames)
resolved via the existing `benchmark_corpus.py`. Add `rapidocr-onnxruntime`, `onnxruntime`
and `opencv-python` with `uv add --script` or a bake-off-local `--with` — **do not** touch
`pyproject.toml`.

### 1.0 — Optional but recommended: a sequence corpus

The gate metrics (§1.4) need *consecutive* frames; the current corpus is 33 stills that are
only incidentally sequential. A 2–3 minute capture at 700 ms intervals during actual play
(one dialogue-heavy scene, one busy combat scene) into `../game_frames_seq/` would make
every gate number real rather than approximate. If skipped, §1.4 falls back to the corpus's
consecutive same-size pairs and the results are directional only — say so in the report.

### 1.1 — `scripts/bakeoff/readers.py`

One protocol, four adapters. Each returns `list[Line]` where
`Line = (box: tuple[int,int,int,int], text: str, confidence: float | None)` in **source-image
pixel coordinates**.

| Adapter | Implementation |
|---|---|
| `RapidOcrReader` | `rapidocr_onnxruntime.RapidOCR`, engine constructed once and reused (RST's `initialize_ocr_engine` pattern). Mirror RST's params: `Global.text_score=0.7`, PP-OCRv4 det + PP-OCRv5 rec, `ModelType.MOBILE`, ONNX Runtime. CPU. |
| `HunyuanOcrReader` | `POST /v1/chat/completions`, `model="HunyuanOCR-1.5-GGUF-Updated-Q4_K_M"`, image + a prompt asking for line text **with boxes**. Try its native spotting format first; fall back to the grounding prompt from `xian/grounding.py:503`. Parse with the existing `parse_regions`. |
| `PaddleVlReader` | Same, `model="PaddleOCR-VL-1.6-GGUF-Q4_K_M"`, explicit id (no `vision` label). |
| `GroundingReader` | Baseline. Calls `xian.grounding.ground_and_translate` unchanged — note it reads *and* translates, so its latency is not comparable to A–C alone; it is the end-to-end bar. |

Reuse rather than reimplement: `xian.grounding.preprocess_for_grounding`,
`VLProcessor.encode_image`, `parse_regions`, `suppress_overlapping_regions`, and
`benchmark_corpus.corpus_paths`.

### 1.2 — `scripts/bakeoff/translators.py`

`translate(lines: list[str], src, tgt) -> list[str]`.

- `HyMt2PerLine(model)` for both 1.8B and 7B — one request per line, fanned out with
  `asyncio.gather` on a bounded semaphore (start at 8), plain "translate to X" framing.
- `GeneralLlmBatch(model)` — RST's contract for comparison: join with `##|||##`, one call,
  the reconstruct-then-translate prompt from `src/ConfigManager.cs:217-347`, split by index.

### 1.3 — `scripts/bakeoff/gates.py` and `cache.py`

Standalone ports of RST's logic, written so Phase 3 can lift them into
`packages/xian-vl/src/xian/` unchanged:

- `content_hash(lines)` — RST `Logic.cs:1678-1715`: count + each fragment lowercased,
  punctuation-stripped, `|`-joined.
- `text_similarity(a, b, lang)` — RST `Logic.cs:774-931`. CJK: char-set overlap 0.4 +
  char-trigram Dice 0.5 + length ratio 0.1. Latin: stop-word-stripped keyword Dice → bigram
  Dice → Jaccard, first to clear wins. Exact match under 5 chars.
- `SettleGate(similarity_threshold, settle_seconds)` — RST `Logic.cs:586-643`. Because the
  replay is not real-time, drive it with an injected clock so settle behaviour is
  deterministic.
- `TranslationCache` — LRU keyed on `(text, src, tgt)`.

### 1.4 — `scripts/bakeoff/run_bakeoff.py`

Emits `bakeoff-results.json` (machine-readable, every raw sample) and `bakeoff-report.md`
(tables). Measurements:

**Reader quality and cost — per reader, per frame**

- **M1 Latency** — median / p95 / max, cold call excluded and reported separately.
- **M2 Yield** — lines detected, total characters, mean confidence.
- **M3 Geometry sanity** — count of frame-sized boxes (>80% cover), container boxes, and
  overlapping pairs >50%, measured by running `drop_frame_sized_regions`,
  `drop_container_regions` and `suppress_overlapping_regions` and counting what each drops.
  *This is the "does a detector give cleaner geometry than a generative model" question,
  answerable with no labels.*
- **M4 Cross-reader agreement** — normalised character-level similarity of each reader's
  concatenated text against every other reader's. Where three agree and one diverges, the
  divergent one is the suspect. Report the matrix, not a verdict.
- **M5 ⭐ Stability** — read each frame twice, and once for each perturbation in
  `test_live_lens_benchmark._recaptures` (re-encode, cursor blink, one-pixel drift, gamma
  drift). Report the fraction of reads whose `content_hash` is *identical* and the mean
  `text_similarity` across repeats. **A reader whose text jitters between identical frames
  defeats the text gate entirely — this metric can disqualify a candidate on its own.**

**The central hypothesis — gate replay**

- **M6 ⭐⭐ Calls per sequence.** Replay the frame sequence four ways and count how many
  translation calls each issues:
  (a) today's phash gate (`live_lens.DEFAULT_CHANGE_THRESHOLD`, hash_size 16);
  (b) text gate alone (hash + similarity ≥ 0.75);
  (c) text gate + settle (0.15 s);
  (d) text gate + settle + translation cache.
  Also report calls *missed* — frames where the text genuinely changed and the gate held.
  **The ratio (a)/(d) is the number the whole rebuild rests on.**
- **M7 Threshold sweep** — similarity ∈ {0.60, 0.70, 0.75, 0.80, 0.85, 0.90, 0.95} ×
  settle ∈ {0, 0.15, 0.3, 0.5} s. Emit calls-issued against changes-missed for each cell,
  so Phase 2 picks from a surface rather than a guess.
- **M8 Cache hit rate** over the sequence, and unique-lines / total-lines.

**Translator cost**

- **M9** Per-line Hy-MT2 latency (1.8B and 7B): single line, and wall-clock for a fan-out
  of N ∈ {1, 5, 10, 20} concurrent lines. Sweep the semaphore bound {4, 8, 16} — local
  serving may not parallelise, and if it does not, per-line loses its main advantage.
- **M10** Batched general-LLM latency for the same N, plus separator-integrity failures
  (reply separator count ≠ request count).
- **M11 Non-fallback rate** — fraction of lines whose translation differs from its source.
  Mirrors `test_grounding_benchmark.test_translations_are_not_silent_fallbacks`; catches a
  model that silently echoes input.

**End to end**

- **M12** Wall-clock per *changed* frame for each (reader × translator) pair, against the
  grounding baseline recorded at ~1.0 s and the retired sidecar's ~2.25 s.
- **M13 ⭐⭐ Projected cost per minute of gameplay:**
  `(60000 / tick_ms) × read_cost_ms + calls_per_minute_from_M6 × translate_cost_ms`,
  tabulated for every combination at tick = 700 ms and at the lowest tick each reader could
  sustain. **This is the decisive comparison — it is the axis on which the sidecar was
  never measured.**

**Spike (cheap, separate)**

- **S1** Does xdg-desktop-portal / PipeWire offer any way to exclude a surface from a
  ScreenCast stream (Q-C5)? A short written finding, not code.

### 1.5 — Deliverables back to Phase 2

`bakeoff-results.json`, `bakeoff-report.md`, the S1 finding, and a one-paragraph note on
anything that failed to run (a reader that errored, a model that would not load) — a
candidate that cannot be made to work is itself a result.

---

## Phase 2 — Read the results, fix the design

No code. Turn Phase 1's numbers into the Phase 3 specification, using decision rules fixed
*now* so the reading is not post-hoc:

1. **Go / no-go on OCR-first.** Proceed if M13's best combination beats the grounding
   baseline by **≥ 2×** on cost-per-minute *and* M6 (a)/(d) ≥ **3×**. If it beats it by less
   than 2×, ship the engine but leave grounding the default and say so. If it loses,
   stop — and the report should then say which stage was the cost, because the answer is
   probably "the reader", and a fifth candidate may be worth a look.
2. **Reader.** Disqualify anything failing M5 (identical-hash rate below ~0.9 makes the text
   gate unusable). Among survivors, rank on M3 geometry sanity, then M1 latency, then M4
   agreement. Record why the losers lost.
3. **Translator.** Per-line Hy-MT2 unless M9 shows the fan-out does not parallelise and
   lands worse than M10's single batched call — in which case fall back to batched
   general-LLM and keep Hy-MT2 as a selectable option.
   Choose 1.8B vs 7B on M9 latency against M11 non-fallback rate.
4. **Thresholds.** Read similarity and settle off the M7 surface: the cell with the fewest
   calls issued at **zero** changes missed, then step one notch more permissive for safety
   margin. Errors here are asymmetric in the same way `live_lens.py:99-104` already
   argues — a dropped-but-still-valid translation costs one re-read; a missed change paints
   the wrong words over live text.
5. **Open questions closed by evidence:** Q-C1 (does phash survive as a pre-OCR filter —
   yes if M1 read cost is material relative to tick budget), Q-C3 (cache persistence — yes
   if M8 shows a high repeat rate across frames), Q-C5 (from S1), Q-E1 (paragraph merging —
   needed only if M3 shows the winning reader emits fragmented line boxes).
6. **Write the Phase 3 spec** as a short amendment to this file: chosen reader, chosen
   translator, threshold constants, and any borrow moved in or out of scope.

---

## Phase 3 — Implementation in xian-vl

Ordered so each step is independently testable and the shipped path never breaks.

### 3.1 Model routing (small, do first)

- `packages/xian-vl/src/xian/omni_router.py:49` — add `hy-mt2`, `hunyuan-mt` to
  `TRANSLATION_KEYWORDS` so both Hy-MT2 variants claim only the `translation` modality
  instead of displacing the chat planner. If PaddleOCR-VL wins §1.1, add an entry to
  `_PRODUCT_MODALITIES` (`:81`) so `paddleocr`/`hunyuanocr` imply `vision`.
- Extend `packages/xian-vl/tests/test_npu_routing.py` — it already asserts translation-only
  routing for `translategemma-4b-FLM` (`:162-173`); add the Hy-MT2 cases beside it.
- Settings: a translation-model selector, defaulting to `router.translation()`.

### 3.2 The OCR stage — `packages/xian-vl/src/xian/ocr/`

Lives in `xian`, not `mage`, so Luduan's scanned-PDF and comics roadmap items
(`docs/ROADMAP.md:49-54`) can reuse it. Promote the Phase 1 adapters:

- `ocr/base.py` — the `Line` dataclass and `Reader` protocol.
- `ocr/<winner>.py` — the chosen adapter, engine constructed once and reused.
- `ocr/preprocess.py` — RST's adaptive HDR path (borrow 9): auto-detect on
  `std < 40 ∨ mean > 200 ∨ mean < 55`, then CLAHE (clip 2.5, tiles 8×8) + bilateral
  (5, 50, 50) + sharpen; plain contrast+median otherwise. Plus upscaling of small crops.
- If a local ONNX reader won: model files download with RST's pattern (borrow 22) — stage
  to `.part`, HTTP `Range` resume, verify against `Content-Length`, **atomic rename only
  after verification**, delete on mismatch. Wire progress into the existing
  `ModelPullWorker` UI shape (`workers.py:735`).

### 3.3 Gating, blocks and cache — `packages/xian-vl/src/xian/`

- `text_gate.py` — `content_hash`, `text_similarity`, `SettleGate`, promoted from Phase 1
  with the Phase 2 constants. Keep the injected clock; it is what makes it testable.
- `translation_cache.py` — LRU keyed on `(text, source_lang, target_lang, mode, styles,
  glossary_version)`. **The key must include the settings**, for the reason
  `pipeline.py:201-203` already documents: reusing a result across a language change
  answers in the wrong language. Persistence into `SessionStore` only if Phase 2 says so.
- `blocks.py` — only if Phase 2 finds it needed. Port RST's line→paragraph rules
  (`BlockDetectionManager.cs:751-956`) with `normalSpacing = avgLineSize × 0.63`, and
  auto-calibrate the scale from median detected text height rather than RST's fixed global
  5.0 (borrow 12). Char→word grouping is almost certainly unnecessary — RST fabricates
  character boxes only to undo per-engine line segmentation, and we standardise on one
  reader.
- `filters.py` — ignore phrases (exact / contains / regex with a timeout) applied
  **before** the content hash, matching RST's placement (`Logic.cs:1092-1241`), plus
  confidence floors (letter 0.1, line 0.2).

### 3.4 The second live engine — `apps/mage-client/src/mage/`

- `live_ocr.py` — the new pipeline: `capture → mask exclude-regions → [phash pre-gate?] →
  read → filter → group → text gate → cache lookup → translate misses → paint`. Emits the
  **same `regions_ready(list[LiveRegion], QRect, scale)` signal** as `LiveLensWorker`, so
  the overlay, the carry logic and the session recorder are untouched.
- `live_lens.py` — refactor the shared parts out (`sample_background`,
  `region_difference`, `regions_signature`, `_boxes_describe_the_same_text`,
  `_boxes_conflict`, the carry/retention machinery) into a base class or a small module
  both workers import. **Preserve every mechanism the current file earned**: own-overlay
  masking, single-flight, carry-during-inference, `_reuse_translations`,
  `_warn_if_nothing_translated`, signature-based repaint suppression.
- `app.py` — dispatch on the new `live_engine` setting when starting live mode
  (`start_live_lens`, `:930-969`).
- `settings_keys.py` — `KEY_LIVE_ENGINE`, `KEY_TRANSLATION_MODEL`, `KEY_IGNORE_PHRASES`,
  `KEY_EXCLUDE_REGIONS`, `KEY_GAME_INFO`.

### 3.5 Features (D-5)

- **Exclude regions** — sub-rectangles stored per bound window, drawn with the existing
  `LensOverlayWindow` selection UX, masked out of the frame *before* the reader and before
  hashing.
- **Ignore phrases** — a Settings list editor over `filters.py`.
- **Window-follow** — poll `WindowBinder.get_geometry()` on the live tick and move the
  bound rect with it (`utils/window_binder.py:490`); it exists but is not wired into the
  live loop's rect today. X11/Windows only, as `WindowBinder` already is.
- **Memoised font fit** — cache in `ui/inpaint_overlay.py:_draw_fitted_text` keyed on
  `(len(text), w, h)`, bounded, cleared on font-setting change (RST's `TextObject.cs:245`).
- **Retry** — a hotkey and OSD action that clears the gate state and forces one pass
  (RST's `Logic.cs:310-340`).
- **Status indicators** — surface reading / translating / settling in the OSD and tray.
- **`game_info`** — a free-text Settings field, injected into the translation system
  prompt alongside the existing `GameStateAssembler` block.
- **Editable prompt templates** — one small text file per role under the app data dir,
  seeded from the built-in defaults, read live.

### 3.6 Documentation

`docs/ROADMAP.md:113` closes ("a local text-detection pass to supply boxes"). Update
`docs/AI_ARCHITECTURE.md` §4 with the second payload lifecycle, `docs/PERFORMANCE.md` with
the Phase 1 numbers, `README.md` features, and `docs/QA_CHECKLIST.md` §3 with live-engine
switching, exclude regions and ignore phrases. Attribution for the borrowed algorithms
(GPL-3 → GPL-3) in `README.md` and in each ported module's header.

---

## Verification

**Unit / integration** — `uv run pytest` stays green. New tests, following the existing
style:

- `packages/xian-vl/tests/test_text_gate.py` — similarity metrics against known CJK and
  Latin pairs; settle behaviour with an injected clock; hash stability under punctuation
  and case noise.
- `packages/xian-vl/tests/test_translation_cache.py` — hit/miss, and that a language, mode
  or glossary change misses.
- `packages/xian-vl/tests/test_ocr_reader.py` — adapter contract with a mocked engine;
  box coordinates land in source-image pixel space.
- `packages/xian-vl/tests/test_npu_routing.py` — extended for Hy-MT2 (§3.1).
- `apps/mage-client/test_live_ocr.py` — the worker loop with a fake reader and fake
  translator: single-flight holds, carry survives a failed translate, the cache prevents a
  second call for repeated text, exclude regions are masked before hashing.

**Benchmark** — `apps/mage-client/test_live_ocr_benchmark.py`, marked `benchmark`, skipping
without the corpus, in the established pattern: assert the calls-per-sequence ratio and the
per-tick read latency that Phase 2 fixed, with `record_property` for every number so a
regression is visible as a changed value rather than only a failure.

**Manual** — `./mage.sh`, Settings → Features → Live engine → *Local OCR*, then the
`docs/QA_CHECKLIST.md` §3 items plus: overlay does not flicker on a static screen; a
dialogue advance is picked up within one tick; re-opening a menu paints instantly from
cache; an excluded minimap region does not trigger re-translation; window-follow keeps the
region on a moved window; retry forces a pass. Compare against the same scenes on the
grounding engine — the switch makes that an A/B in the running app, which is the point of
D-1.

---

## Appendix: key file index

**RST** — `src/Logic.cs:540-763` (gates), `:774-931` (similarity), `:1678-1715` (hash),
`:2602-2741` (translate); `src/BlockDetectionManager.cs:399-956` (grouping),
`:1058-1345` (manga); `src/MainWindow.xaml.cs:92-98, 371-374, 1998` (loop);
`src/OcrServerManager.cs`, `src/SocketManager.cs` (OCR IPC);
`app/webserver/RapidOCR/process_image_rapidocr.py:106-185, 479-561` (preprocess, char boxes);
`src/ConfigManager.cs:217-347` (prompts), `:1622, 3102` (thresholds).

**MAGE** — `apps/mage-client/src/mage/live_lens.py` (whole live loop);
`packages/xian-vl/src/xian/grounding.py` (VLM detect+translate);
`packages/xian-vl/src/xian/pipeline.py:588-628` (bubble prompt), `:467-480` (phash cache);
`apps/mage-client/src/mage/capture/{screen,stream}.py`;
`apps/mage-client/src/mage/ui/inpaint_overlay.py`;
`packages/xian-vl/src/xian/{session_store,game_state}.py`;
`apps/mage-client/src/mage/telemetry.py`;
`benchmark_corpus.py`, `apps/mage-client/test_live_lens_benchmark.py`,
`packages/xian-vl/tests/test_grounding_benchmark.py`, `scripts/benchmark_live_pipeline.py`.
