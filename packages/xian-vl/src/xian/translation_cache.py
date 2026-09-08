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

"""A translation cache keyed on the source text.

Neither MAGE nor RST had one, and it is nearly free once OCR produces stable
strings rather than a vision model producing fresh prose each time.  A re-opened
menu, a repeated NPC line, a tooltip hovered twice: zero inference.

The key includes the language pair and nothing else, which is a narrower key
than the bubble path's phash cache needs.  That is a property of the translator
rather than an oversight — Hy-MT2 takes no mode, no styles and no glossary, so
there is nothing else in the request that could change the answer.  If the
translator is ever swapped for one that does take them, this key has to grow
with it, for the reason ``pipeline.py`` already documents: reusing a result
across a settings change answers the wrong question convincingly.
"""

from __future__ import annotations

from collections import OrderedDict

__all__ = ["TranslationCache"]

DEFAULT_CAPACITY = 2048


class TranslationCache:
    """A bounded LRU over ``(text, source, target) -> translation``."""

    def __init__(self, capacity: int = DEFAULT_CAPACITY):
        if capacity < 1:
            raise ValueError("capacity must be at least 1")
        self.capacity = capacity
        self._entries: OrderedDict[tuple[str, str, str], str] = OrderedDict()
        self.hits = 0
        self.misses = 0

    @staticmethod
    def _key(text: str, source_lang: str, target_lang: str) -> tuple[str, str, str]:
        # Whitespace-insensitive: the recognizer's leading and trailing spaces
        # vary between reads of identical text, and a key that changed with
        # them would miss on every second frame.
        return text.strip(), (source_lang or "").casefold(), (target_lang or "").casefold()

    def get(self, text: str, source_lang: str, target_lang: str) -> str | None:
        key = self._key(text, source_lang, target_lang)
        if key not in self._entries:
            self.misses += 1
            return None
        self._entries.move_to_end(key)
        self.hits += 1
        return self._entries[key]

    def put(self, text: str, source_lang: str, target_lang: str, translation: str) -> None:
        if not text.strip() or not translation.strip():
            return
        key = self._key(text, source_lang, target_lang)
        self._entries[key] = translation
        self._entries.move_to_end(key)
        while len(self._entries) > self.capacity:
            self._entries.popitem(last=False)

    def clear(self) -> None:
        self._entries.clear()
        self.hits = 0
        self.misses = 0

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return self.hits / total if total else 0.0

    def __len__(self) -> int:
        return len(self._entries)

    def __contains__(self, key: tuple[str, str, str]) -> bool:
        return self._key(*key) in self._entries
