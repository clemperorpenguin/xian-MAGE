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

"""The local-OCR live engine: what it reads, and when it calls the network.

The gate is the whole point of this engine, so most of these tests are about
the calls that *do not* happen.
"""

import asyncio
import os
import sys

import numpy as np
import pytest
from PIL import Image
from PyQt6.QtCore import QRect

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from mage.live_ocr import LiveOcrWorker  # noqa: E402
from xian.filters import IgnoreRule, TextFilter  # noqa: E402
from xian.ocr.base import Line  # noqa: E402
from xian.text_gate import SettleGate  # noqa: E402


def _line(x, y, width, height, text, confidence=0.95) -> Line:
    quad = np.array(
        [[x, y], [x + width, y], [x + width, y + height], [x, y + height]],
        dtype=np.float32,
    )
    return Line(quad=quad, text=text, confidence=confidence)


class FakeEngine:
    """Returns scripted lines and counts how often it was asked."""

    def __init__(self, *frames):
        self.frames = list(frames)
        self.reads = 0

    def set_source_language(self, language):
        self.language = language

    def read(self, image):
        self.reads += 1
        index = min(self.reads - 1, len(self.frames) - 1)
        return list(self.frames[index])


class FakeTranslator:
    """Records every batch of lines it was asked to translate."""

    def __init__(self):
        self.calls = []
        self.glossary = {}

    async def translate_lines(self, texts, source_lang, target_lang):
        self.calls.append(list(texts))
        return [f"<{text}>" for text in texts]


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class Worker(LiveOcrWorker):
    """_translate_frame without a QThread or an event loop of its own."""

    def __init__(self, engine, translator, *, text_filter=None, gate=None, excludes=()):
        self.source_lang = "Chinese"
        self.target_lang = "English"
        self._engine = engine
        self._translator = translator
        self._filter = text_filter or TextFilter()
        self._gate = gate or SettleGate(settle_seconds=0.0, clock=FakeClock())
        self._glossary_terms = {}
        self._exclude_regions = list(excludes)
        self._detector_model = None
        self._served_rect = QRect(0, 0, 400, 300)
        self.processor = None


def frame(width=400, height=300):
    return Image.new("RGB", (width, height), (30, 30, 30))


def run(worker):
    return asyncio.run(worker._translate_frame(frame()))


# ── reading and grouping ─────────────────────────────────────────────

def test_a_read_line_becomes_a_translated_region():
    translator = FakeTranslator()
    worker = Worker(FakeEngine([_line(10, 10, 200, 24, "这扇门被锁住了")]), translator)

    regions = run(worker)

    assert [r.original for r in regions] == ["这扇门被锁住了"]
    assert [r.translated for r in regions] == ["<这扇门被锁住了>"]


def test_a_two_line_subtitle_is_translated_as_one_unit():
    """Sent as two requests it comes back as two half-sentences translated
    without each other, which reads worse than either half deserved."""
    translator = FakeTranslator()
    engine = FakeEngine([_line(10, 10, 200, 24, "上一句"), _line(10, 40, 200, 24, "下一句")])

    run(Worker(engine, translator))

    assert translator.calls == [["上一句\n下一句"]]


def test_cjk_fragments_on_one_line_are_joined_without_a_space():
    translator = FakeTranslator()
    engine = FakeEngine([_line(10, 10, 60, 24, "你好"), _line(74, 10, 60, 24, "世界")])

    run(Worker(engine, translator))

    assert translator.calls == [["你好世界"]]


def test_latin_fragments_on_one_line_keep_their_space():
    translator = FakeTranslator()
    engine = FakeEngine([_line(10, 10, 60, 24, "hello"), _line(74, 10, 60, 24, "world")])

    run(Worker(engine, translator))

    assert translator.calls == [["hello world"]]


def test_an_empty_read_translates_nothing():
    translator = FakeTranslator()

    assert run(Worker(FakeEngine([]), translator)) is None
    assert translator.calls == []


# ── the gate ─────────────────────────────────────────────────────────

def test_unchanged_text_is_not_translated_again():
    """The mechanism the whole engine exists for: the pixels may be moving,
    but if the text has not changed there is nothing to ask the network."""
    translator = FakeTranslator()
    lines = [_line(10, 10, 200, 24, "这扇门被锁住了")]
    worker = Worker(FakeEngine(lines, lines, lines), translator)

    run(worker)
    assert run(worker) is None
    assert run(worker) is None
    assert len(translator.calls) == 1


def test_changed_text_is_translated_again():
    translator = FakeTranslator()
    worker = Worker(
        FakeEngine(
            [_line(10, 10, 200, 24, "这扇门被锁住了")],
            [_line(10, 10, 200, 24, "你找到了一把生锈的钥匙")],
        ),
        translator,
    )

    run(worker)
    run(worker)

    assert len(translator.calls) == 2


def test_a_misread_glyph_does_not_count_as_a_change():
    """The recognizer disagrees with itself about one character in a screen
    of text; without the fuzzy comparison that is a re-translation per tick."""
    translator = FakeTranslator()
    worker = Worker(
        FakeEngine(
            [_line(10, 10, 300, 24, "王国的守卫拒绝让你通过这座桥")],
            [_line(10, 10, 300, 24, "王国的守卫拒绝让你通过这座析")],
        ),
        translator,
    )

    run(worker)
    assert run(worker) is None
    assert len(translator.calls) == 1


def test_text_is_not_translated_until_it_settles():
    clock = FakeClock()
    translator = FakeTranslator()
    lines = [_line(10, 10, 200, 24, "这扇门被锁住了")]
    worker = Worker(
        FakeEngine(lines, lines),
        translator,
        gate=SettleGate(settle_seconds=0.15, clock=clock),
    )

    assert run(worker) is None
    clock.advance(0.2)
    assert run(worker) is not None


def test_resetting_the_gate_forces_a_pass():
    """What a manual retry needs when the gate holds text the user can see
    is wrong."""
    translator = FakeTranslator()
    lines = [_line(10, 10, 200, 24, "这扇门被锁住了")]
    worker = Worker(FakeEngine(lines, lines), translator)
    worker._clean_hash = object()

    run(worker)
    worker.reset_gate()

    assert run(worker) is not None
    assert len(translator.calls) == 2
    assert worker._clean_hash is None


# ── filtering ────────────────────────────────────────────────────────

def test_a_low_confidence_line_never_reaches_the_gate():
    translator = FakeTranslator()
    engine = FakeEngine([
        _line(10, 10, 200, 24, "real text", confidence=0.9),
        _line(10, 200, 200, 24, "n0!se", confidence=0.05),
    ])

    run(Worker(engine, translator, text_filter=TextFilter(min_confidence=0.2)))

    assert translator.calls == [["real text"]]


def test_an_ignored_phrase_is_removed_before_the_hash():
    """A permanent HUD label the recognizer reads differently each frame would
    otherwise change the content hash on every tick and defeat the gate."""
    translator = FakeTranslator()
    engine = FakeEngine([
        _line(10, 10, 200, 24, "这扇门被锁住了"),
        _line(10, 200, 200, 24, "HP 431/500"),
    ])
    text_filter = TextFilter(rules=[IgnoreRule(pattern="HP", kind="contains")])

    run(Worker(engine, translator, text_filter=text_filter))

    assert translator.calls == [["这扇门被锁住了"]]


def test_a_frame_of_nothing_but_ignored_text_translates_nothing():
    translator = FakeTranslator()
    engine = FakeEngine([_line(10, 10, 200, 24, "HP 431/500")])
    text_filter = TextFilter(rules=[IgnoreRule(pattern="HP", kind="contains")])

    assert run(Worker(engine, translator, text_filter=text_filter)) is None
    assert translator.calls == []


# ── exclude regions ──────────────────────────────────────────────────

def test_excluded_rectangles_are_blanked_before_anything_looks_at_the_frame(monkeypatch):
    """Masked in the captured frame itself, so the change gate — which hashes
    whatever _grab returns — cannot see the excluded pixels either."""
    from mage import live_common

    captured = Image.new("RGB", (400, 300), (255, 255, 255))
    monkeypatch.setattr(live_common.LiveWorkerBase, "_grab", lambda self: captured.copy())

    worker = Worker(FakeEngine([]), FakeTranslator(), excludes=[QRect(100, 100, 80, 40)])
    result = worker._grab()

    assert result.getpixel((140, 120)) == (0, 0, 0)
    assert result.getpixel((10, 10)) == (255, 255, 255)


def test_a_frame_with_no_exclusions_is_passed_straight_through(monkeypatch):
    from mage import live_common

    captured = Image.new("RGB", (400, 300), (255, 255, 255))
    monkeypatch.setattr(live_common.LiveWorkerBase, "_grab", lambda self: captured)

    worker = Worker(FakeEngine([]), FakeTranslator())

    assert worker._grab() is captured


# ── overlap ──────────────────────────────────────────────────────────

def test_stacked_boxes_are_suppressed_before_painting():
    """A detector stacks boxes on tightly-packed UI just as a vision model
    does, and the overlay fills before it draws."""
    translator = FakeTranslator()
    engine = FakeEngine([
        _line(10, 10, 200, 24, "front"),
        _line(12, 11, 198, 23, "front again"),
    ])

    regions = run(Worker(engine, translator))

    assert len(regions) == 1
