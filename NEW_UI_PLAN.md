# MAGE — OCR Pipeline Rebuild + New UI

**Branch:** `new_UI`
**Date:** 2026-09-07
**Status:** Implementation plan. Supersedes `PLAN.md` Phases 1–2; restates and replaces Phase 3.

Two independent tasks share one branch because they meet in one place — the live
translation loop — and because the second only makes sense once the first has made a
translation cheap enough to fire from a click instead of a hotkey.

| | |
|---|---|
| **Task 1** | Rebuild the OCR + translation pipeline: PP-OCRv5 detection, per-script PP-OCRv5 recognition, OpenCV DB postprocessing and crop rectification, docTR/EasyOCR line grouping, Hy-MT2 translation through Lemonade. |
| **Task 2** | A second UI — persistent translation **boxes** and an **orb** (log · chat · push-to-talk) — selectable in Settings. The existing UI stays exactly as it is. |

---

## 0. What this changes about `PLAN.md`

`PLAN.md` is the RST borrow review and remains the reference for *why* each borrowed
algorithm exists. Its Phase 1 (automated bake-off) and Phase 2 (read the results) are
**cancelled**: the reader and the translator are now decided by fiat rather than by
measurement.

| `PLAN.md` decision | Status here |
|---|---|
| **D-1** selectable engine, grounding stays default | **Kept.** OCR-first ships as a second live engine; grounding stays the one-shot bubble path and the fallback. |
| **D-2** reader chosen by bake-off | **Replaced.** Reader is PP-OCRv5 detection + per-script PP-OCRv5 recognition, driven directly through ONNX Runtime. |
| **D-3** per-line Hy-MT2, fanned out, cache-first | **Kept, and pinned.** `Hy-MT2-1.8B-GGUF-Q4_K_M`, hard-coded. |
| **D-4** comparative metrics, no ground truth | **Narrowed** to a regression benchmark (§1.11) rather than a bake-off. |
| **D-5** feature scope (exclude regions, ignore phrases, window-follow, memoised font fit, retry, status, `game_info`, prompt templates) | **Kept, re-homed.** Several of these become gestures in the new UI instead of settings (§2.3). |

Everything in `PLAN.md` §4 "Do not borrow" and "Explicitly keep from MAGE" still holds.
The measured bars from §3 still hold: **342 ms** is what the retired OCR sidecar cost to
detect and read a region-sized frame (`packages/xian-vl/tests/test_grounding_benchmark.py:48-51`),
and **~1.0 s** is what one grounding call costs today. Task 1 has to stay under the first
number and beat the second on cost per minute of gameplay.

---

# Part 1 — The OCR + translation pipeline

## 1.1 Runtime: ONNX Runtime, not `paddlepaddle`

We use **PaddleOCR's models**, not PaddleOCR's Python package.

The request is for OpenCV DBNet contour postprocessing and OpenCV crop rectification. The
`paddleocr` package owns both of those internally — installing it and then reimplementing
its postprocess is the worst of both. Add to that: `paddlepaddle` is a ~1 GB wheel with no
ROCm story on Fedora, it would be a second inference runtime in a process that already
talks to Lemonade, and it drags in its own OpenCV.

The runtime we need is **already resident in the workspace venv, undeclared and
unimported**:

```
.venv/lib/python3.13/site-packages/
  onnxruntime          1.28.0
  cv2                  opencv-python 5.0.0.93
  pyclipper            1.4.0
  shapely              2.1.2
  rapidocr_onnxruntime 1.4.4   ← reference only, see below
```

**Actions:**

- Declare an optional extra on `packages/xian-vl/pyproject.toml`:
  `ocr = ["onnxruntime>=1.20", "opencv-python-headless>=4.10", "pyclipper>=1.3", "shapely>=2.0"]`,
  and make `mage-client` depend on `xian-vl[ocr]`. Run `uv sync` (AGENTS.md §1).
- **`opencv-python-headless`, not `opencv-python`.** The resident build ships its own Qt
  platform plugins; loading them inside a PyQt6 process is a known source of
  `xcb`/`wayland` plugin conflicts and duplicate-symbol crashes. Headless has no GUI
  module and nothing we need lives there.
- **`rapidocr_onnxruntime` is not a dependency.** It bundles only `ch_PP-OCRv4_det_infer.onnx`
  and `ch_PP-OCRv4_rec_infer.onnx` (verified in the venv) — v4, Chinese only, no per-script
  recognizers. It stays useful as a *reading* reference for the same postprocess we are
  writing, and RST's tuning of it (`process_image_rapidocr.py:106-185`) is where our
  preprocessing constants come from. Remove it from the venv once the extra is declared so
  it cannot be imported by accident.

## 1.2 Models and how they arrive

### The set

| Role | Model | Notes |
|---|---|---|
| Detection | `PP-OCRv5_mobile_det` | Default. `PP-OCRv5_server_det` selectable as the quality option. |
| Recognition — CJK+EN | `PP-OCRv5_mobile_rec` | Simplified + Traditional Chinese, English, Japanese, handwriting. The default. |
| Recognition — Latin | `latin_PP-OCRv5_mobile_rec` | Non-English Latin scripts. |
| Recognition — Korean | `korean_PP-OCRv5_mobile_rec` | |
| Recognition — East Slavic | `eslav_PP-OCRv5_mobile_rec` | ru / uk / be. |
| Orientation (optional) | `PP-LCNet_x1_0_textline_ori` | 180° textline flip. Off by default — game text is rarely upside down and it is a third session per crop batch. |

Each recognizer needs its character dictionary shipped alongside the weights.

### Script routing

`xian/ocr/scripts.py` maps `KEY_SOURCE_LANG` to a recognizer:

```
zh, zh-CN, zh-TW, ja, en, auto  -> PP-OCRv5_mobile_rec
ko                              -> korean_PP-OCRv5_mobile_rec
ru, uk, be                      -> eslav_PP-OCRv5_mobile_rec
fr, de, es, it, pt, vi, ...     -> latin_PP-OCRv5_mobile_rec
```

`auto` resolves to the CJK+EN recognizer, which is the only one that covers Latin *and*
CJK. A second pass that re-reads with a script-specific recognizer when the first pass's
Unicode-block distribution disagrees with the chosen model is a **follow-up, not v1** — it
doubles the recognition cost for a case the user can fix by setting the source language.

### Getting ONNX weights — the honest problem

PaddleOCR publishes inference models as `.pdmodel` + `.pdiparams`. There is no official
ONNX release for the v5 line. Two routes:

1. **Vendor an export script** — `scripts/export_ppocr_onnx.py` downloads the official
   inference tarballs from the pinned PaddleOCR URLs, runs `paddle2onnx` in a throwaway
   `uv run --with` environment (never in the workspace venv), and writes ONNX + sha256 to
   a local cache. **Recommended.** Provenance is ours, the conversion is reproducible, and
   nothing at runtime depends on a third party's re-upload.
2. **Pull pre-exported ONNX from a mirror** — faster to stand up, but the artefact's
   provenance is someone else's and the URL can rot.

Take route 1, and treat the export as a one-time build step whose *output* is what the
catalog points at. **This is the single largest unknown in Part 1** — budget a day for it,
and verify each exported recognizer against a handful of corpus frames before trusting the
catalog checksums.

### The downloader

`xian/ocr/models.py`, borrowing `PLAN.md` borrow 22 wholesale (RST `WhisperModelDownloader.cs`):

- Hard-coded catalog: `(model_id, url, exact byte size, sha256, script, quality tag)`, so
  the picker shows sizes with no network round trip.
- Stage to `<name>.part`; resume with HTTP `Range`; verify `Content-Length` **and** sha256;
  **atomic rename only after verification**; delete on mismatch rather than leaving a
  half-file that segfaults ONNX Runtime. Three retries with backoff, cancel on window close.
- Cache at `~/.cache/xian-vl/ocr/<model_id>/`.
- Progress through a new `OcrModelDownloadWorker` shaped exactly like `ModelPullWorker`
  (`apps/mage-client/src/mage/workers.py:735`), so the existing progress UI is reused.

## 1.3 Module layout

```
packages/xian-vl/src/xian/ocr/
  __init__.py       PaddleOcrEngine, Line, Quad  — the whole public surface
  base.py           Line / Quad dataclasses, Reader protocol
  models.py         catalog + resumable verified downloader
  scripts.py        source language -> recognizer
  preprocess.py     OpenCV: adaptive enhancement + detector input normalisation
  detect.py         DBNet session + OpenCV contour postprocess
  rectify.py        OpenCV perspective crop rectification
  recognize.py      per-script CTC sessions, aspect-sorted batching, greedy decode
  grouping.py       docTR reading order + EasyOCR paragraph merge
  engine.py         PaddleOcrEngine — sessions held once, reused
```

It lives in `xian`, not `mage`, so Luduan's scanned-PDF and comics roadmap items
(`docs/ROADMAP.md:49-54`) can reuse it. Nothing in `xian/ocr/` imports PyQt6.

## 1.4 `preprocess.py` — OpenCV

**Frame-level adaptive enhancement** (borrow 9, RST `process_image_rapidocr.py:106-160`).
Auto-detected on the grayscale statistics of the crop:

```
std < 40  or  mean > 200  or  mean < 55   ->  CLAHE(clip=2.5, tiles=8x8)
                                              + bilateralFilter(5, 50, 50)
                                              + unsharp mask
otherwise                                 ->  convertScaleAbs contrast + medianBlur(3)
```

The trigger conditions are exactly RST's, tuned against HDR game capture, which is the
same input we have.

**Detector input normalisation.** Resize keeping aspect so the long side is
`limit_side_len` (960 for mobile det), then pad both dimensions up to a multiple of 32.
Normalise with the Paddle mean/std (`[0.485,0.456,0.406]` / `[0.229,0.224,0.225]`), HWC→CHW,
add batch axis. Keep the `(scale_x, scale_y)` so boxes map back to source pixels exactly.

## 1.5 `detect.py` — DBNet + OpenCV contour postprocess

The session returns a single-channel probability map. Everything after it is OpenCV, and
this is the part being written rather than imported:

1. `bitmap = prob > thresh` (0.3).
2. `cv2.findContours(bitmap.astype(uint8), RETR_LIST, CHAIN_APPROX_SIMPLE)`, capped at
   `max_candidates` (1000).
3. Per contour: `cv2.minAreaRect` → reject if `min(w,h) < min_size` (3 px).
4. **Score** = mean probability inside the contour: zero mask, `cv2.fillPoly` the contour,
   `cv2.mean(prob, mask)`. Reject below `box_thresh` (0.6).
5. **Unclip**: offset the polygon outward by `area * unclip_ratio / perimeter` using
   `pyclipper.PyclipperOffset(JT_ROUND, ET_CLOSEDPOLYGON)`, with `shapely` for the area and
   perimeter. `unclip_ratio` 1.5.
6. `cv2.minAreaRect` → `cv2.boxPoints` on the unclipped polygon; order the four corners
   clockwise from top-left (sort by x, then resolve the two left and two right points by y).
7. Scale back into source-image pixels; clamp to bounds.

These are PaddleOCR's `DBPostProcess` defaults. They are **not** module constants — they
go in a `DetectConfig` dataclass, because game text on a busy background is exactly the
case where `box_thresh` wants to drop to ~0.45, and the person who needs to change it
should not be editing a module.

Output: `list[Quad]`, four points each, source pixels.

## 1.6 `rectify.py` — OpenCV crop rectification

Paddle's `get_rotate_crop_image`, written out:

- `w = max(‖p0−p1‖, ‖p2−p3‖)`, `h = max(‖p0−p3‖, ‖p1−p2‖)`.
- `cv2.getPerspectiveTransform(quad, [[0,0],[w,0],[w,h],[0,h]])`.
- `cv2.warpPerspective(..., (w,h), borderMode=BORDER_REPLICATE, flags=INTER_CUBIC)`.
- If `h / w >= 1.5`, the text is vertical: `cv2.rotate(..., ROTATE_90_COUNTERCLOCKWISE)`.
- **Small-crop upscale** (RST's, `process_image_rapidocr.py:160-185`): if the rectified
  height is under 24 px, `cv2.resize` ×2 with `INTER_CUBIC` before recognition. Game
  subtitle text at 1080p routinely lands here and the recognizer's accuracy falls off a
  cliff below ~20 px.

This is where a warped or perspective-projected UI panel stops being a problem: the
detector's quad is not axis-aligned, and the recognizer only ever sees an upright rectangle.

## 1.7 `recognize.py` — per-script CTC

- Crops sorted by aspect ratio, batched in groups of 6, each batch padded to its own max
  width at a fixed height of 48 (PP-OCRv5 rec input is 3×48×W). Sorting by aspect is
  Paddle's trick and it matters: unsorted batches pad a 4:1 crop out to a 40:1 crop's width.
- Normalise to `[-1, 1]`, NCHW.
- One `ort.InferenceSession` per recognizer, constructed lazily and **cached for the
  process lifetime** — session construction is tens to hundreds of milliseconds and must
  never land inside a tick.
- Greedy CTC decode against the script's char dict, collapsing repeats and blanks.
  Confidence = mean of the per-timestep max probabilities over the kept timesteps.
- `intra_op_num_threads = max(1, cpu_count // 2)`, `inter_op_num_threads = 1`. Recognition
  must not starve the compositor while a game is running.

## 1.8 `grouping.py` — line and block assembly, from docTR and EasyOCR

The detector returns quads in arbitrary order. Three stages, each named for its source:

**Stage 1 — reading order (docTR).** `doctr/models/builder.py::DocumentBuilder._sort_boxes`:
sort by y-centre, and within a tolerance band by x. Straight port.

**Stage 2 — lines (docTR).** `_resolve_lines`: walk the sorted boxes; start a new line when
the next box's y-centre leaves the current line's vertical band, or when x jumps backwards
by more than the break distance. **Adaptation:** docTR's `paragraph_break` is a fraction of
*page width* (default 0.035), which is meaningless for a region crop of arbitrary size.
Use the current line's own median box height as the unit instead — a new line when the
y-centre delta exceeds 0.5× that height, a break when x regresses by more than 2× it.

**Stage 3 — blocks (EasyOCR).** `easyocr/utils.py::get_paragraph`: a free-merge loop that
absorbs a box into a paragraph when it falls within `x_ht` horizontally and `y_ht`
vertically of the paragraph's running bounds, then orders within the paragraph.
**Adaptation:** EasyOCR takes the **maximum** box height as its unit, so a single oversized
title box sets the merge radius for the whole screen and swallows unrelated HUD text. Use
the **median** line height (`PLAN.md` borrow 12, RST's `avgTextHeight` auto-calibration).
Keep EasyOCR's `mode='rtl'` branch — it is what makes Arabic and Hebrew order correctly,
and MAGE already ships an `ar` locale.

**Vertical / tategaki.** Detected from the quads, not the text: if more than half the quads
have `h/w > 1.5`, flip the axis roles in stages 2 and 3 and order columns right-to-left
(RST `BlockDetectionManager.cs:268-332`).

**Joining.** Text within a line joins with `""` for CJK sources and `" "` otherwise; lines
within a block join with `"\n"`, and the block is what gets translated — so a two-line
subtitle is one translation unit, not two half-sentences.

**We do not port RST's char→word stage.** `PLAN.md` Q-E1 established that it exists only
to undo per-engine line segmentation; we own one engine and its line boxes are ours.

**Licensing.** PaddleOCR, docTR and EasyOCR are all Apache-2.0 — compatible one-way into
GPL-3.0-or-later. Each ported module's header must name the upstream file it is adapted
from, and the branch adds a root `NOTICE` file (there is none today) listing all three plus
RST's GPLv3 borrows. This is not optional and it is not a documentation task — do it in the
commit that adds the code.

## 1.9 Translation — Hy-MT2 1.8B through Lemonade

New `packages/xian-vl/src/xian/translate.py`.

```python
TRANSLATION_MODEL = "Hy-MT2-1.8B-GGUF-Q4_K_M"   # pinned
```

- `translate_lines(lines, source_lang, target_lang) -> list[str]` — one request per line,
  fanned out with `asyncio.gather` over a `Semaphore(8)`, cache-first, submitted through
  `processor.engine.submit` (AGENTS.md §2.3).
- **Prompt framing.** Hy-MT2 is a machine-translation model: a bare user message,
  `"Translate the following from {src} to {tgt}:\n{text}"`, **no system prompt**. An MT
  model translates instructions rather than following them — this is the same reason
  `omni_router.is_translation_only_model` exists.
- **Missing model is a loud, actionable failure**, not a silent fallback: if
  `/api/v1/models` does not list the pin, raise with the model id and offer a one-click
  pull through the existing `ModelPullWorker`. A quiet fallback to the chat model is how a
  user ends up debugging translation quality that has nothing to do with the OCR rebuild.

### Consequence that must be stated: no context in the prompt

Because there is no system prompt, the glossary and `GameStateAssembler`'s session digest
**cannot ride along** — a real regression against the grounding path, where they do.
Mitigation, in order:

1. **Deterministic glossary substitution.** Apply the wiki glossary
   (`VLProcessor.load_glossary_from_wiki`, `pipeline.py:311`; `xian/dictionary.py`) as a
   pre-pass on the source line and a post-pass on the output. Proper nouns stay consistent
   without asking the model to be told about them.
2. **The cache.** A recurring NPC name is translated once and reused, so consistency
   follows from `translation_cache` rather than from context.
3. **The escape hatch.** D-1's engine selector — a user who needs context-aware translation
   switches back to grounding.

Cross-line pronoun resolution is genuinely lost. Say so in the docs.

### Router hygiene (do this first — it is small and independent)

- `packages/xian-vl/src/xian/omni_router.py:49` — add `"hy-mt2"`, `"hunyuan-mt"` to
  `TRANSLATION_KEYWORDS`, so a user who selects Hy-MT2 as their main model has it claim
  only the `translation` modality instead of displacing the chat planner.
- Extend `packages/xian-vl/tests/test_npu_routing.py` beside the existing
  `translategemma-4b-FLM` case (`:162-173`).
- Reconnect `VLProcessor.get_translation_model_name()` (`pipeline.py:272`) — it exists,
  has **no caller**, and is a leftover from the retired sidecar. It becomes the resolution
  path, with `TRANSLATION_MODEL` as the override.

### `xian/translation_cache.py`

LRU keyed on `(text, source_lang, target_lang)`. Simpler than `PLAN.md` §3.3's key,
because Hy-MT2 takes no mode, styles or glossary — there is nothing else in the request to
key on. If persistence into `SessionStore` is wanted later (`PLAN.md` Q-C3), the key is
already stable enough for it.

## 1.10 Gating — `xian/text_gate.py`

Ported from `PLAN.md` §3.3 with RST's shipped constants, since there is no bake-off to
derive them from:

| Constant | Value | Source |
|---|---|---|
| Letter confidence floor | 0.1 | RST `Logic.cs:1615` |
| Line confidence floor | 0.2 | RST `Logic.cs:1615` |
| Text similarity threshold | 0.75 | RST `Logic.cs:774` |
| Settle time | 0.15 s | RST `ConfigManager.cs:3102` |

- `content_hash(lines)` — block count + each fragment lowercased, punctuation-stripped,
  `|`-joined (RST `Logic.cs:1678-1715`).
- `text_similarity(a, b, lang)` — CJK: char-set overlap 0.4 + char-trigram Dice 0.5 +
  length ratio 0.1. Latin: stop-word-stripped keyword Dice → bigram Dice → Jaccard, first
  to clear wins. Exact match under 5 chars.
- `SettleGate` — changed text is timestamped, not translated; it fires only when the same
  text survives the settle window. **Injected clock**, which is what makes it testable.
- `filters.py` — ignore phrases (exact / contains / regex with a timeout) applied *before*
  the content hash, matching RST's placement (`Logic.cs:1092-1241`).

**The phash gate stays** as a pre-OCR filter (`PLAN.md` Q-C1). It costs ~1 ms and skips a
read that costs two orders of magnitude more; there is no argument for removing it.

## 1.11 The worker — `apps/mage-client/src/mage/live_ocr.py`

```
grab
  -> mask exclude regions           (before everything, so they never reach the hash)
  -> mask own painted overlay       (live_lens.py:491-518, kept verbatim)
  -> phash gate                     -> unchanged? sleep
  -> preprocess (adaptive)
  -> detect  (DBNet + OpenCV postprocess)
  -> rectify + recognize (per-script, batched)
  -> confidence filter, ignore phrases
  -> group   (docTR order/lines, EasyOCR blocks)
  -> content hash + similarity + settle   -> unchanged text? carry, sleep
  -> cache lookup
  -> translate misses (Hy-MT2 fan-out)
  -> merge with carry, publish
```

Emits the **same** `regions_ready(list[LiveRegion], QRect, float)` signal as
`LiveLensWorker`, so `XianApp._on_live_regions` (`app.py:1007`), `InpaintOverlay` and the
session recorder are untouched.

**Refactor, don't duplicate.** Extract from `live_lens.py` into a shared base or module:
`sample_background`, `region_difference`, `regions_signature`,
`_boxes_describe_the_same_text`, `_boxes_conflict`, `_mask_painted`, `_masked_hash`,
`_surviving_regions`, `_reuse_translations`, `_merge_with_carry`, the single-flight latch
and the capture-failure counter. Every one of these was earned against a real failure and
none of them should be rewritten.

`app.py:930` (`start_live_lens`) dispatches on a new `KEY_LIVE_ENGINE` setting; everything
else in that method — the `FrameStream`, the `InpaintOverlay`, the teardown dance in
`stop_live_lens` — is engine-agnostic already.

New settings keys in `settings_keys.py`: `KEY_LIVE_ENGINE`, `KEY_OCR_DET_MODEL`,
`KEY_IGNORE_PHRASES`, `KEY_GAME_INFO`.

## 1.12 Threading

Non-negotiable, per AGENTS.md §2: ONNX sessions run inside `asyncio.to_thread` on the
`xian-async-engine` loop, never on the Qt main thread. `PaddleOcrEngine` holds an
`asyncio.Lock` — with multiple boxes (§2.3) several workers share one engine and must not
enter a session concurrently.

## 1.13 Tests

New, in the existing style:

| File | Covers |
|---|---|
| `packages/xian-vl/tests/test_ocr_detect.py` | DB postprocess on a synthetic probability map: a known rectangle recovers within 2 px; `box_thresh` rejects a low-confidence blob; unclip widens by the expected ratio; `max_candidates` caps. |
| `packages/xian-vl/tests/test_ocr_rectify.py` | A synthetic rotated crop rectifies upright; the `h/w ≥ 1.5` rule rotates; sub-24 px crops upscale. |
| `packages/xian-vl/tests/test_ocr_grouping.py` | docTR band test splits lines 1.5 heights apart and keeps two words on one line; EasyOCR merge joins a 3-line paragraph; **one oversized box does not drag the median radius**; tategaki flips column order. |
| `packages/xian-vl/tests/test_translate.py` | Per-line fan-out with a mocked client; the pin is respected; a missing model raises with the model id; glossary substitution round-trips. |
| `packages/xian-vl/tests/test_text_gate.py` | Similarity on known CJK and Latin pairs; settle with an injected clock; hash stability under case and punctuation noise. |
| `packages/xian-vl/tests/test_translation_cache.py` | Hit/miss; a language change misses. |
| `apps/mage-client/test_live_ocr.py` | Single-flight holds; carry survives a failed translate; the cache prevents a second call for repeated text; exclude regions are masked before hashing. |
| `apps/mage-client/test_live_ocr_benchmark.py` | `@pytest.mark.benchmark`, skips without the corpus. `record_property` for detect / rectify+recognize / group latency, lines per frame, and calls-per-sequence against the phash-only baseline. |

**Acceptance bar:** detect + rectify + recognize on a region-sized corpus frame at
**≤ 350 ms** median, so the whole read fits inside a 700 ms tick with room for the paint.
If it lands over, the first lever is `limit_side_len` 960 → 736 on the detector, then the
`_server_det` → `_mobile_det` choice, then batch size. Do not reach for a smaller
recognizer first — recognition quality is what the whole rebuild is buying.

---

# Part 2 — The new UI

**Principle:** the classic UI is not touched. Not refactored, not "cleaned up on the way
past". A new shell is added beside it and a setting picks one. Anything that has to change
in a shared file changes by *addition*.

## 2.1 The switch

- `KEY_NEW_UI = "new_ui"` in `settings_keys.py`, default off.
- A checkbox in the **Features** tab beside `experimental_live_cb` (`app.py:331`), with the
  same "restart to apply" note the experimental toggles use.
- New `apps/mage-client/src/mage/ui/shell.py`:

  ```python
  def install_shell(app) -> Shell:
      """Wire up whichever surface layer the settings ask for."""
  ```

  `ClassicShell` performs exactly today's wiring — tray, `CommandOSD`, full hotkey
  listener, familiar — by calling the existing methods. `NewShell` wires the orb and the
  box manager. `XianApp.__init__` calls `install_shell(self)` where it currently builds
  those pieces inline; the classic path must come out byte-identical in behaviour.
- New files live under `apps/mage-client/src/mage/ui/new/`. Nothing in that directory is
  imported unless the setting is on.

**Hotkeys under the new shell** (per decision): `create_hotkey_listener` is started with
command mode **not armed** — `_CommandModeCore.COMMANDS` is empty and the leader double-tap
does nothing. The **overlay-toggle double-tap survives** as the one global gesture: it is
the panic key for hiding every overlay when a fullscreen game has the pointer, and there is
no clickable substitute for that. `CommandOSD` is never constructed.

This needs a small, additive change in `capture/hotkeys.py`: a `command_mode_enabled` flag
on `_CommandModeCore` checked at the top of the leader branch. Two lines, no behaviour
change when true.

## 2.2 Part one — box selections

`ui/new/boxes.py`.

A **box** is a persistent, named rectangle on the screen that the user places once and
leaves there. It is not the current one-shot lens selection.

- **`TranslationBox(MageOverlayWindow)`** — the base class (`ui/overlay_base.py`) already
  gives drag, click-through, multi-monitor clamping, edit mode, and geometry persistence
  keyed by `window_id` (`:122`, `:142`). Each box takes `window_id = f"box_{n}"` and gets
  all of that for free.
- **Creation**: one full-screen dimmed picker, drag to draw. Reuse `CinematicLensOverlay`
  (`ui/lens.py:250-380`) — it already collects a list of rects, draws them, and confirms.
- **Modes**, cycled from a hover toolbar on the box itself — no modifiers, no chords:

  | Mode | Behaviour |
  |---|---|
  | **Live** | Ticks continuously, paints in place. The Part 1 pipeline. |
  | **Once** | Reads and translates on click, then holds. Replaces dialogue mode. |
  | **Ignore** | Masked out of every other box's frame before the reader. Replaces "exclude regions" (`PLAN.md` borrow 15) — same feature, no settings page. |
  | **Off** | Present, remembered, inert. |

- **Up to 5 boxes** (RST parity, borrow 18). Each drives one `LiveOcrWorker` and one
  `InpaintOverlay` bound to its rect. **Boxes tick round-robin against one shared
  `PaddleOcrEngine`**, so five boxes cost five reads spread across five ticks rather than
  five concurrent ONNX sessions fighting for the same cores.
- **State is visible on the box**: a 2 px border whose colour says idle / reading /
  translating / settled. This is `PLAN.md` borrow 24 (status LEDs) placed where the user is
  already looking.
- **Persistence**: `QSettings` under `boxes/<preset>` as JSON —
  `{id, x, y, w, h, screen, mode, source, target}` — tied to the existing layout-preset
  system (`app.py:151-179`), so a user's box layout is per-game the way their overlay layout
  already is.
- **Window-follow** (`PLAN.md` borrow 19, D-5): if a target window is bound, poll
  `WindowBinder.get_geometry()` on the tick and translate the box rects by the delta, using
  the machinery already in `_align_overlays_to_target` / `_translate_overlays_by_delta`
  (`app.py:2676`, `:2700`). X11/Windows only, as `WindowBinder` already is.

## 2.3 Part two — the orb

`ui/new/orb.py`. A new widget on `MageOverlayWindow`. **`FamiliarPet` is untouched** and
remains a classic-UI feature.

A small always-on-top circle, draggable anywhere, position persisted. Click to expand into
one panel with three faces:

### Logger
The running feed of every translation the boxes produced — source above target,
timestamped, scrollable. Right-click for copy / speak / add-to-notes (into the existing
`NotesSidebar`). Backed by `SessionStore` through `processor.record_event` (`pipeline.py:395`),
so this is a *view* over data the app already writes, not a second store. Clearing the view
does not clear session memory; that stays in Settings where it is.

### Chat agent
A text input at the bottom of the same panel, sending through `VLProcessor.process_chat`
(`pipeline.py:1245`) — **reusing `ChatWorker`** (`ui/chat_sidebar.py:111`), not a second
implementation. The orb's advantage over the sidebar is that the box translations are
already in its scroll-back: "what did that last line mean?" needs no attachment step.

### Speech → text → translate
Push-to-talk: press and hold the orb (or click the mic pip to latch).

- Capture with `ContinuousAudioStreamer` (`capture/audio.py:148`) — already handles the
  PipeWire/PulseAudio recorder discovery.
- Transcribe with `LemonadeClient.transcribe` (`lemonade_client.py:150`), ASR model from
  `router.asr()`, exactly as `RaidWorker._translate_loop` (`workers.py:594`) does.
- Translate the transcript through Part 1's `translate_lines`.
- Both lines land in the logger. Optional TTS through `LemonadeClient.tts` (`:173`) and the
  existing `SerialAudioPlayer`.

Implement as a **new `OrbVoiceWorker`**, not by reusing `RaidWorker`: RaidWorker is a
continuous three-stage pipeline with its own queues and TTS consumer, and push-to-talk is a
different shape. Borrow its structure, not its instance.

**Follow-up, do not build in v1:** Lemonade's realtime WS transcription endpoint
(`lemonade/docs/api/openai.md#ws-realtime`; discover the port from `/v1/health`'s
`websocket_port` field) would give partial transcripts while the button is held. It adds a
`websockets` dependency and a second audio path — worth it later, not now.

### Orb visual state
Idle (dim) · listening (pulsing ring) · reading (arc spinner) · translating (second arc) ·
speaking. One object carries the whole system's status.

## 2.4 What replaces the hotkey soup

| Today | New UI |
|---|---|
| double-tap Shift → `c` (lens) | Place a box; set **Once** or **Live** |
| double-tap Shift → `a` (chat) | Click the orb → type |
| double-tap Shift → `s` (settings) | Orb → gear |
| double-tap Shift → `m` (cinematic) | Box mode **Live** + orb mic latched |
| double-tap Shift → `t` (how to say) | Orb → type, prefix-free |
| double-tap Shift → `r` (raid) | Hold the orb, or latch the mic pip |
| double-tap Shift → `n` (notes) | Orb → notes tab |
| backtick (cinematic capture) | Click the box |
| Alt+1…5 (RST saved areas) | The boxes *are* the saved areas |
| **double-tap RShift (hide all)** | **unchanged — the one surviving gesture** |

## 2.5 Localization

Every user-facing string goes into `packages/shared-types/locales/en.json` with both
`value` and `context` (AGENTS.md §3), then `uv run -m localize.cli` regenerates the nine
target locales. Roughly 35 new keys under `newui.box.*`, `newui.orb.*`, plus
`settings.checkbox.new_ui` and `settings.tooltip.new_ui`. **No hardcoded strings** — the
guardrail applies to the new shell exactly as it does to the old one.

## 2.6 Tests

Following `apps/mage-client/test_gui.py`'s session-scoped `QApplication` fixture:

| File | Covers |
|---|---|
| `apps/mage-client/test_new_ui_shell.py` | The setting selects the shell; classic wiring is unchanged when off; command mode is not armed when on; the overlay toggle still fires under both. |
| `apps/mage-client/test_boxes.py` | Geometry persistence round-trips per layout preset; the 5-box cap; an **Ignore** box masks the frame before the reader; round-robin never runs two reads at once. |
| `apps/mage-client/test_orb.py` | Log appends on `regions_ready`; `ChatWorker` is reused rather than reimplemented; push-to-talk start/stop transitions; no widget touched off the main thread. |

---

# Sequencing

Each milestone is a self-contained, revertible commit on `new_UI`, and each leaves the
tree shippable.

| # | Milestone | Depends on | Notes |
|---|---|---|---|
| **M0** | Branch, `ocr` extra declared, `uv sync`, root `NOTICE`, GPL headers on new files (`scripts/add_gpl_headers.py`) | — | Also the two-line `omni_router` keyword fix + its test. Small, independent, do it first. |
| **M1** | `xian/ocr/`: models catalog + downloader, preprocess, detect, rectify, recognize. Headless. | M0 | Includes `scripts/export_ppocr_onnx.py`. Prove it against corpus stills with a throwaway script before wiring anything. |
| **M2** | `grouping.py`, `text_gate.py`, `filters.py`, `translation_cache.py`, `translate.py` | M1 | Still headless. `test_live_ocr_benchmark.py` proves the ≤ 350 ms bar here. |
| **M3** | `live_ocr.py` + the `live_lens.py` refactor + `KEY_LIVE_ENGINE` in the **classic** settings | M2 | **Shippable on its own.** Task 1 is complete and usable with the old UI. |
| **M4** | `ui/shell.py`, `KEY_NEW_UI`, `ui/new/boxes.py` | M3 | Boxes work; the orb is not there yet; the panic key still hides everything. |
| **M5** | `ui/new/orb.py` — logger, then chat, then voice, in that order | M4 | Three commits, not one. |
| **M6** | Docs, localization pass, QA checklist | M5 | See below. |

**M6 documentation:** `docs/ROADMAP.md:113` closes ("a local text-detection pass to supply
boxes"). `docs/AI_ARCHITECTURE.md` §4 gains the second payload lifecycle.
`docs/PERFORMANCE.md` gains the M2 numbers. `docs/QA_CHECKLIST.md` gains a **2×2 matrix** —
{classic, new} UI × {grounding, OCR} engine — because that is four combinations and the
checklist is the only place that will catch a regression in the one nobody uses.
`README.md` gains the feature and the Apache-2.0 attributions.

---

# Risks

1. **PP-OCRv5 ONNX provenance (§1.2).** The largest unknown in the branch. No official ONNX
   release exists; we export. Mitigate by pinning exact upstream inference-model URLs plus
   sha256, vendoring the export script, and verifying each recognizer against corpus frames
   before the catalog is trusted. If `paddle2onnx` cannot express a v5 op, the fallback is
   PP-OCRv4 recognition (which `rapidocr_onnxruntime` proves exports cleanly) with v5
   detection — worse, but not blocked.
2. **`opencv-python` vs PyQt6 plugin conflict.** Use `-headless`. If a transitive dependency
   drags the full build back in, pin it out explicitly.
3. **Hy-MT2 1.8B quality on game text, with no context in the prompt (§1.9).** Mitigated by
   deterministic glossary substitution and the cache; the real escape hatch is D-1's engine
   selector. Cross-line pronoun resolution is lost and that is a genuine regression.
4. **Per-line fan-out may not parallelise.** A single-slot llama.cpp backend serialises the
   `gather`, and per-line loses its main advantage. `PLAN.md` M9 would have measured this
   and no longer will — so **keep a batched-single-call path behind a flag** in
   `translate.py` from day one rather than discovering the problem in M3.
5. **Detection on stylised game fonts and low-contrast HUD.** `box_thresh` is tunable and
   preprocessing is adaptive, but a fantasy display face on a parchment texture is a real
   failure mode the grounding VLM handles better. The engine selector is the answer.
6. **Four UI × engine combinations to QA.** Explicit in the checklist (M6). Resist adding a
   fifth axis.
7. **Two overlay systems on screen.** The orb and the familiar must never both be visible;
   the new shell simply does not construct the familiar.

---

# Open questions

- **Q1** — ONNX weights: export ourselves (recommended) or accept a mirror? Decides a day
  of M1.
- **Q2** — Should boxes auto-follow a bound window by default, or only when the user asks?
  Following is better when it works and confusing when `WindowBinder` returns stale
  geometry on Wayland.
- **Q3** — Does the orb replace the tray menu under the new shell, or sit beside it? Tray
  is the only surface that survives every overlay being hidden.
- **Q4** — `PLAN.md` Q-C5 (a Wayland equivalent of `WDA_EXCLUDEFROMCAPTURE`) is still open
  and still worth a short spike; own-overlay masking works, but excluding our surfaces from
  the PipeWire stream would delete a whole class of problem.
