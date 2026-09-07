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

"""The source-text translation cache."""

import pytest

from xian.translation_cache import TranslationCache


def test_a_repeated_line_is_a_hit():
    cache = TranslationCache()
    cache.put("这扇门被锁住了", "Chinese", "English", "The door is locked.")

    assert cache.get("这扇门被锁住了", "Chinese", "English") == "The door is locked."


def test_an_unseen_line_is_a_miss():
    assert TranslationCache().get("unseen", "Chinese", "English") is None


def test_a_changed_target_language_misses():
    """Reusing a result across a language change answers in the wrong one."""
    cache = TranslationCache()
    cache.put("门", "Chinese", "English", "door")

    assert cache.get("门", "Chinese", "French") is None


def test_a_changed_source_language_misses():
    cache = TranslationCache()
    cache.put("門", "Chinese", "English", "door")

    assert cache.get("門", "Japanese", "English") is None


def test_surrounding_whitespace_does_not_change_the_key():
    """The recognizer's leading and trailing spaces vary between reads."""
    cache = TranslationCache()
    cache.put("the door is locked", "English", "French", "la porte est fermée")
    assert cache.get("  the door is locked  ", "English", "French") == "la porte est fermée"


def test_language_names_are_matched_case_insensitively():
    cache = TranslationCache()
    cache.put("door", "english", "french", "porte")

    assert cache.get("door", "English", "French") == "porte"


def test_the_oldest_entry_is_evicted_first():
    cache = TranslationCache(capacity=2)
    cache.put("a", "zh", "en", "A")
    cache.put("b", "zh", "en", "B")
    cache.put("c", "zh", "en", "C")

    assert cache.get("a", "zh", "en") is None
    assert cache.get("c", "zh", "en") == "C"


def test_a_hit_refreshes_an_entry():
    cache = TranslationCache(capacity=2)
    cache.put("a", "zh", "en", "A")
    cache.put("b", "zh", "en", "B")
    cache.get("a", "zh", "en")
    cache.put("c", "zh", "en", "C")

    assert cache.get("a", "zh", "en") == "A"
    assert cache.get("b", "zh", "en") is None


def test_empty_translations_are_not_stored():
    """A blank result is a failure, and caching it makes it permanent."""
    cache = TranslationCache()
    cache.put("door", "zh", "en", "   ")

    assert len(cache) == 0


def test_hit_rate_reports_what_the_gate_is_saving():
    cache = TranslationCache()
    cache.put("door", "zh", "en", "porte")
    cache.get("door", "zh", "en")
    cache.get("window", "zh", "en")

    assert cache.hit_rate == 0.5


def test_capacity_must_be_positive():
    with pytest.raises(ValueError):
        TranslationCache(capacity=0)
