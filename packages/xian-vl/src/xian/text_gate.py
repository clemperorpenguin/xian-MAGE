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

"""Deciding whether the *text* on screen has changed.

Adapted from RSTGameTranslation's ``Logic.cs``.

This is the mechanism the whole OCR-first architecture rests on.  A perceptual
hash can only answer "did the pixels move", and in a game the pixels move
constantly — particle effects, an animated HUD, a blinking cursor, a scrolling
combat log — while the dialogue sits still.  Once reading is cheap enough to do
on every tick, the question can be asked about the text instead, and the
expensive half (translation) fires on a small fraction of frames.

Three gates in order, each cheaper than the one after it:

1. **Content hash** — an exact-match check that ignores case and punctuation.
2. **Fuzzy similarity** — absorbs the jitter a recognizer has on identical
   input, where one glyph in twenty lines comes back different.
3. **Settle time** — text that is still being revealed is timestamped, not
   translated, and only fires once it has stopped changing.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Callable, Iterable, Sequence

__all__ = [
    "DEFAULT_SETTLE_SECONDS",
    "DEFAULT_SIMILARITY",
    "SettleGate",
    "content_hash",
    "text_similarity",
]

#: Similarity at or above which two readings are "the same text".  RST's
#: shipped value, and it has to tolerate a recognizer disagreeing with itself
#: about one glyph in a screen of text.
DEFAULT_SIMILARITY = 0.75

#: How long new text must persist before it is worth translating.  Absorbs
#: typewriter-style reveals and mid-transition frames.
DEFAULT_SETTLE_SECONDS = 0.15

#: Below this length the fuzzy metrics are meaningless — two three-character
#: strings share bigrams by accident — so it falls back to exact match.
_MIN_FUZZY_LENGTH = 5

_PUNCTUATION = re.compile(r"[^\w\s]", re.UNICODE)
_WHITESPACE = re.compile(r"\s+")

#: Stripped before keyword comparison so "the door is locked" and "door
#: locked" register as the same line.
_STOP_WORDS = frozenset(
    """a an the and or but if then than that this these those is are was were be been being
    am do does did to of in on at by for with from into over under as it its his her their
    my your our not no yes you i he she they we""".split()
)


def _normalize(text: str) -> str:
    return _WHITESPACE.sub(" ", _PUNCTUATION.sub("", text.lower())).strip()


def content_hash(lines: Sequence[str]) -> str:
    """A cheap, order-sensitive fingerprint of what is on screen.

    Deliberately not a pixel hash and deliberately not a cryptographic one: it
    exists to be compared for equality against the previous frame's, and to be
    stable under the case and punctuation noise a recognizer produces.
    """
    normalized = [_normalize(line) for line in lines]
    return f"{len(normalized)}|" + "|".join(normalized)


def _is_cjk(text: str) -> bool:
    """True when most of the text is ideographic or kana.

    Drives which similarity metric is used: CJK has no word boundaries, so
    every word-based measure returns nonsense for it.
    """
    counted = [character for character in text if not character.isspace()]
    if not counted:
        return False
    cjk = sum(
        1
        for character in counted
        if "぀" <= character <= "ヿ" or "一" <= character <= "鿿" or "가" <= character <= "힯"
    )
    return cjk / len(counted) > 0.3


def _dice(left: Iterable, right: Iterable) -> float:
    """Sørensen–Dice over two collections of n-grams."""
    first, second = set(left), set(right)
    if not first and not second:
        return 1.0
    if not first or not second:
        return 0.0
    return 2 * len(first & second) / (len(first) + len(second))


def _ngrams(text: str, size: int) -> list[str]:
    return [text[index : index + size] for index in range(max(len(text) - size + 1, 0))]


def _cjk_similarity(left: str, right: str) -> float:
    """Character-set overlap, character trigrams, and length agreement.

    The weights are RST's.  Trigrams carry most of it because they capture
    order, which a set comparison throws away — "王を殺した" and "殺した王を"
    have identical character sets and different meanings.
    """
    overlap = _dice(set(left), set(right))
    trigrams = _dice(_ngrams(left, 3), _ngrams(right, 3))
    length_ratio = min(len(left), len(right)) / max(len(left), len(right), 1)
    return 0.4 * overlap + 0.5 * trigrams + 0.1 * length_ratio


def _latin_similarity(left: str, right: str, threshold: float) -> float:
    """Three measures, first to clear the threshold wins.

    Not an average: each catches a different kind of near-match, and averaging
    them lets two failures drown the one that was right.
    """
    left_words = [word for word in left.split() if word not in _STOP_WORDS]
    right_words = [word for word in right.split() if word not in _STOP_WORDS]

    keyword_dice = _dice(left_words, right_words)
    if keyword_dice >= threshold:
        return keyword_dice

    bigram_dice = _dice(_ngrams(left, 2), _ngrams(right, 2))
    if bigram_dice >= threshold:
        return bigram_dice

    first, second = set(left.split()), set(right.split())
    union = first | second
    jaccard = len(first & second) / len(union) if union else 1.0
    return max(keyword_dice, bigram_dice, jaccard)


def text_similarity(left: str, right: str, *, threshold: float = DEFAULT_SIMILARITY) -> float:
    """How alike two readings are, on a language-appropriate measure.

    ``threshold`` is passed in rather than applied here because the Latin path
    is first-to-clear: it needs to know what it is trying to clear.
    """
    left, right = _normalize(left), _normalize(right)
    if left == right:
        return 1.0
    if not left or not right:
        return 0.0
    if len(left) < _MIN_FUZZY_LENGTH or len(right) < _MIN_FUZZY_LENGTH:
        return 0.0  # exact match already ruled out above

    if _is_cjk(left) or _is_cjk(right):
        return _cjk_similarity(left, right)
    return _latin_similarity(left, right, threshold)


@dataclass
class SettleGate:
    """Holds new text until it stops changing, then releases it once.

    The clock is injected so settle behaviour is deterministic under test —
    a gate that can only be tested by sleeping is a gate nobody tests.
    """

    similarity_threshold: float = DEFAULT_SIMILARITY
    settle_seconds: float = DEFAULT_SETTLE_SECONDS
    clock: Callable[[], float] = time.monotonic

    _accepted: str | None = field(default=None, init=False)
    _pending: str | None = field(default=None, init=False)
    _pending_since: float = field(default=0.0, init=False)

    @property
    def accepted(self) -> str | None:
        """The last text this gate released."""
        return self._accepted

    def reset(self) -> None:
        """Forget everything — the escape hatch behind a manual retry."""
        self._accepted = None
        self._pending = None
        self._pending_since = 0.0

    def should_translate(self, lines: Sequence[str]) -> bool:
        """True at most once per settled change of on-screen text."""
        current = content_hash(lines)

        if self._accepted is not None:
            if current == self._accepted:
                self._pending = None
                return False
            if text_similarity(current, self._accepted, threshold=self.similarity_threshold) >= self.similarity_threshold:
                # Recognizer jitter on unchanged text, not a real change.
                self._pending = None
                return False

        now = self.clock()
        if self._pending != current:
            # Something new: restart the settle window.  Deliberately an exact
            # comparison, not a fuzzy one — text that is still being revealed
            # is *similar* to itself frame over frame, and letting it inherit
            # the previous timestamp would fire mid-reveal, which is the case
            # the settle window exists to prevent.
            self._pending = current
            self._pending_since = now

        if now - self._pending_since < self.settle_seconds:
            return False

        self._accepted = current
        self._pending = None
        return True
