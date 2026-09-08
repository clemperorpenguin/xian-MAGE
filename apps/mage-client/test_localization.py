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

"""String lookup across locales.

Lives here rather than beside shared-types because the root pytest config
collects only ``packages/xian-vl/tests`` and ``apps/mage-client``, and the
locale runtime is what every MAGE label goes through.
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from shared_types.state import state  # noqa: E402


@pytest.fixture(autouse=True)
def english_afterwards():
    yield
    state.load_locale("en")


def _english() -> dict:
    with open(state.locales_dir / "en.json", encoding="utf-8") as handle:
        return json.load(handle)


def test_a_translated_key_resolves_in_its_own_language():
    state.load_locale("zh")

    assert state.t("settings.dialog.title") != _english()["settings.dialog.title"]["value"]


def test_an_untranslated_key_falls_back_to_english():
    """Every string added between one localize.cli run and the next is in this
    state, and a button labelled "newui.orb.button.send" is not a fallback."""
    state.load_locale("zh")

    assert state.t("newui.orb.button.send") == "Send"


def test_a_key_in_no_locale_at_all_returns_itself():
    state.load_locale("zh")

    assert state.t("nothing.defines.this") == "nothing.defines.this"


def test_english_reads_the_value_out_of_the_reference_structure():
    """en.json carries {"value", "context"}; the generated locales are flat."""
    state.load_locale("en")

    assert state.t("settings.dialog.title") == _english()["settings.dialog.title"]["value"]


def test_an_unknown_language_still_serves_english():
    state.load_locale("qq")

    assert state.t("newui.orb.button.send") == "Send"


@pytest.mark.parametrize("lang", ["zh", "ja", "ko", "ru", "es", "ar", "hi", "vi"])
def test_no_locale_ever_shows_a_raw_key_for_a_defined_string(lang):
    """The property that matters: whatever the locale is missing, the user
    sees words."""
    state.load_locale(lang)

    raw = [key for key in _english() if state.t(key) == key and " " not in key]

    assert raw == []
