# MAGE — Gaming HUD for real-time screen translation.
# Copyright (C) 2026  Clementine Pendragon <clem@pendragon.systems>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
#
# Contact: clem@pendragon.systems (Clementine Pendragon, c/o Xian Project Development)

"""The local reader, against real game frames.

Two numbers decide whether this engine was worth building, and neither can be
had from synthetic images:

* **What a read costs.**  The bar is the retired OCR sidecar's measured
  342 ms to detect and read a region-sized frame
  (``test_grounding_benchmark.py``), because that is the cost that has to fit
  inside a 700 ms tick alongside the paint.

* **How many translation calls a sequence of frames actually issues.**  This
  is the whole architectural claim: a perceptual hash fires whenever the pixels
  move, and a text gate only when the text does.  The ratio between them is
  what the rebuild rests on.

Every measurement goes out through ``record_property`` as well as an
assertion, so a regression shows up as a changed number rather than only as a
failure.

Skips without the screenshot corpus (see :mod:`benchmark_corpus`), and without
the exported PP-OCRv5 models (see ``scripts/export_ppocr_onnx.py``).
"""

from __future__ import annotations

import os
import statistics
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from benchmark_corpus import corpus_paths, strict_budget  # noqa: E402

pytestmark = pytest.mark.benchmark

#: What the retired OCR sidecar cost to detect and read a region-sized frame.
#: The bar this engine had to clear to be worth building.
SIDECAR_READ_MS = 342.0

#: A region-sized frame, in megapixels.  Live mode reads a locked region, not
#: a whole desktop, and the two are an order of magnitude apart in cost.
REGION_MEGAPIXELS = 1.5


def _engine():
    cv2 = pytest.importorskip("cv2")
    pytest.importorskip("onnxruntime")
    from xian.ocr import PaddleOcrEngine

    engine = PaddleOcrEngine(source_language="Chinese")
    if not engine.available():
        pytest.skip("PP-OCRv5 models not exported; run scripts/export_ppocr_onnx.py")
    engine.warm()
    return engine, cv2


def _frames(cv2, *, region_only=False):
    for path in corpus_paths():
        image = cv2.imread(str(path))
        if image is None:
            continue
        if region_only and image.shape[0] * image.shape[1] > REGION_MEGAPIXELS * 1e6:
            continue
        yield path, image


def test_a_region_sized_frame_is_read_inside_the_sidecar_budget(record_property):
    """The number that justifies the engine's existence."""
    engine, cv2 = _engine()

    timings = []
    for _path, image in _frames(cv2, region_only=True):
        started = time.perf_counter()
        engine.read(image)
        timings.append((time.perf_counter() - started) * 1000)

    if not timings:
        pytest.skip("corpus has no region-sized frames")

    median = statistics.median(timings)
    record_property("region_read_ms_median", round(median, 1))
    record_property("region_read_ms_max", round(max(timings), 1))
    record_property("region_frames", len(timings))

    budget = SIDECAR_READ_MS if strict_budget() else SIDECAR_READ_MS * 3
    assert median < budget


def test_the_whole_corpus_is_read_without_falling_over(record_property):
    """Includes full-desktop captures, which are the worst case by a distance:
    five megapixels and well over a hundred lines, none of which live mode
    sees because it reads a locked region."""
    engine, cv2 = _engine()

    timings = []
    line_counts = []
    for _path, image in _frames(cv2):
        started = time.perf_counter()
        lines = engine.read(image)
        timings.append((time.perf_counter() - started) * 1000)
        line_counts.append(len(lines))

    record_property("corpus_read_ms_median", round(statistics.median(timings), 1))
    record_property("corpus_read_ms_max", round(max(timings), 1))
    record_property("corpus_lines_median", statistics.median(line_counts))

    assert sum(line_counts) > 0


def test_the_reader_finds_text_on_every_frame(record_property):
    """A frame that reads as empty paints nothing, which looks exactly like
    the overlay being broken."""
    engine, cv2 = _engine()

    empty = [path.name for path, image in _frames(cv2) if not engine.read(image)]

    record_property("frames_with_no_text", len(empty))
    assert not empty


def test_reading_the_same_frame_twice_gives_the_same_text(record_property):
    """The property the text gate is built on.

    A reader whose output jitters between identical inputs changes the content
    hash every tick, and the gate then holds nothing back — which would make
    this engine strictly worse than the one it is beside.
    """
    engine, cv2 = _engine()
    from xian.text_gate import content_hash

    identical = 0
    total = 0
    for _path, image in _frames(cv2, region_only=True):
        first = content_hash([line.text for line in engine.read(image)])
        second = content_hash([line.text for line in engine.read(image)])
        identical += first == second
        total += 1

    if not total:
        pytest.skip("corpus has no region-sized frames")

    rate = identical / total
    record_property("identical_reread_rate", round(rate, 3))
    assert rate >= 0.9


def test_the_text_gate_issues_fewer_calls_than_the_pixel_gate(record_property):
    """The central claim, replayed over the corpus in capture order.

    The pixel gate counts frames whose *pixels* differ; the text gate counts
    frames whose *text* differs.  Every frame in the gap is a translation call
    that no longer happens.
    """
    engine, cv2 = _engine()
    import imagehash
    from PIL import Image

    from mage.live_common import DEFAULT_CHANGE_THRESHOLD, LIVE_HASH_SIZE
    from xian.ocr.grouping import group_lines
    from xian.text_gate import SettleGate

    class Clock:
        def __init__(self):
            self.now = 0.0

        def __call__(self):
            self.now += 0.7  # one tick
            return self.now

    gate = SettleGate(settle_seconds=0.0, clock=Clock())

    pixel_calls = 0
    text_calls = 0
    previous_hash = None

    for _path, image in _frames(cv2):
        pil = Image.fromarray(image[:, :, ::-1])
        current = imagehash.phash(pil, hash_size=LIVE_HASH_SIZE)
        if previous_hash is None or abs(current - previous_hash) > DEFAULT_CHANGE_THRESHOLD:
            pixel_calls += 1
        previous_hash = current

        blocks = group_lines(engine.read(image), space_delimited=False)
        if gate.should_translate([block.text for block in blocks]):
            text_calls += 1

    record_property("pixel_gate_calls", pixel_calls)
    record_property("text_gate_calls", text_calls)
    record_property("call_ratio", round(pixel_calls / max(text_calls, 1), 2))

    # The corpus is 33 mostly-distinct stills rather than a play sequence, so
    # this is a floor and not the real-world figure: consecutive frames of
    # actual play repeat their text far more than these do.
    assert text_calls <= pixel_calls
