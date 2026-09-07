# Xian-VL — Core Vision-Language orchestration engine.
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

"""The text-level change gate."""

import pytest

from xian.text_gate import SettleGate, content_hash, text_similarity


class FakeClock:
    """A clock the test drives, so settle behaviour needs no sleeping."""

    def __init__(self):
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


# ── content hash ─────────────────────────────────────────────────────

def test_the_hash_ignores_case_and_punctuation():
    """Exactly the noise a recognizer produces on identical pixels."""
    assert content_hash(["Hello, world!"]) == content_hash(["hello world"])


def test_the_hash_is_sensitive_to_order():
    assert content_hash(["a line", "b line"]) != content_hash(["b line", "a line"])


def test_the_hash_is_sensitive_to_line_count():
    """One extra line is a changed screen even if every old line survived."""
    assert content_hash(["one"]) != content_hash(["one", "two"])


# ── similarity ───────────────────────────────────────────────────────

def test_identical_text_is_identical():
    assert text_similarity("the door is locked", "the door is locked") == 1.0


def test_one_misread_glyph_still_counts_as_the_same_line():
    """The gate's whole job: absorb recognizer jitter on unchanged text."""
    assert text_similarity("the ancient door is locked", "the ancient door is locked") >= 0.75


def test_a_different_sentence_is_not_similar():
    assert text_similarity("the door is locked", "you have received a key") < 0.75


def test_cjk_similarity_uses_characters_not_words():
    """No spaces to split on, so a word-based measure returns nothing useful.

    One misread glyph in a line of dialogue scores ~0.95 and is absorbed.
    """
    assert text_similarity("王国的守卫拒绝让你通过这座桥", "王国的守卫拒绝让你通过这座析") >= 0.75


def test_a_short_cjk_line_is_judged_strictly():
    """One character in seven is a seventh of the meaning.

    Short lines are where a changed glyph is most likely to *be* the change —
    a quantity, a name, a door number — so the metric deliberately does not
    reach the threshold there.  It is the long lines that need the tolerance.
    """
    assert text_similarity("这扇门被锁住了", "这扇门被锁佳了") < 0.75


def test_cjk_reordering_is_not_similar():
    """Character-set overlap alone would call these identical; trigrams do not."""
    assert text_similarity("王を殺した勇者", "勇者を殺した王") < 0.75


def test_short_strings_fall_back_to_exact_match():
    """Two three-character strings share bigrams by accident."""
    assert text_similarity("abc", "abd") == 0.0
    assert text_similarity("abc", "abc") == 1.0


def test_empty_text_is_similar_to_nothing():
    assert text_similarity("", "something") == 0.0


# ── the settle gate ──────────────────────────────────────────────────

def test_new_text_is_not_translated_until_it_settles():
    clock = FakeClock()
    gate = SettleGate(settle_seconds=0.15, clock=clock)

    assert gate.should_translate(["a new line of dialogue"]) is False

    clock.advance(0.2)
    assert gate.should_translate(["a new line of dialogue"]) is True


def test_a_reveal_fires_once_at_the_end_and_not_during():
    """Typewriter text must not be translated a fragment at a time.

    Each tick sees different text, so the settle window restarts and nothing
    is sent; only once the reveal has finished and the same text survives the
    window does one translation go out.
    """
    clock = FakeClock()
    gate = SettleGate(settle_seconds=0.15, clock=clock)
    full = "the quick brown fox jumps"

    for length in range(5, len(full), 5):
        clock.advance(0.1)
        assert gate.should_translate([full[:length]]) is False

    clock.advance(0.1)
    assert gate.should_translate([full]) is False  # first sight of the whole line
    clock.advance(0.2)
    assert gate.should_translate([full]) is True


def test_settled_text_fires_exactly_once():
    clock = FakeClock()
    gate = SettleGate(settle_seconds=0.15, clock=clock)

    gate.should_translate(["a line of dialogue"])
    clock.advance(0.2)
    assert gate.should_translate(["a line of dialogue"]) is True

    for _ in range(5):
        clock.advance(0.7)
        assert gate.should_translate(["a line of dialogue"]) is False


def test_jitter_on_accepted_text_does_not_refire():
    """The frame the gate is protecting against: same screen, different read."""
    clock = FakeClock()
    gate = SettleGate(settle_seconds=0.15, clock=clock)

    gate.should_translate(["the ancient door is locked"])
    clock.advance(0.2)
    assert gate.should_translate(["the ancient door is locked"]) is True

    clock.advance(0.7)
    assert gate.should_translate(["the ancient door is locked"]) is False


def test_a_real_change_fires_again():
    clock = FakeClock()
    gate = SettleGate(settle_seconds=0.15, clock=clock)

    gate.should_translate(["the door is locked"])
    clock.advance(0.2)
    gate.should_translate(["the door is locked"])

    clock.advance(0.7)
    assert gate.should_translate(["you have received a rusty key"]) is False
    clock.advance(0.2)
    assert gate.should_translate(["you have received a rusty key"]) is True


def test_reset_forces_the_next_frame_through():
    """What a manual retry needs: clear the gate and read again."""
    clock = FakeClock()
    gate = SettleGate(settle_seconds=0.0, clock=clock)

    assert gate.should_translate(["a line of dialogue"]) is True
    assert gate.should_translate(["a line of dialogue"]) is False

    gate.reset()
    assert gate.should_translate(["a line of dialogue"]) is True


def test_zero_settle_time_fires_immediately():
    gate = SettleGate(settle_seconds=0.0, clock=FakeClock())

    assert gate.should_translate(["a line of dialogue"]) is True
