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

"""One place that builds a translator, so every path uses the same one.

Text translation in MAGE goes through Hy-MT2 and nothing else.  That is not a
preference: the prompts in :mod:`xian.translate` are Hy-MT2's own published
instruction formats, the per-line fan-out and the cache are shaped around it,
and a translation quietly served by some other model produces quality problems
that read as OCR problems.

Built here rather than at each call site because there are several — the boxes,
the orb's microphone, a one-off translation — and a setting honoured by two of
the three is worse than one honoured by none.
"""

from __future__ import annotations

import logging

from mage.settings_keys import KEY_STYLES, KEY_TRANSLATION_MODEL
from xian.translate import TRANSLATION_MODEL, LineTranslator

logger = logging.getLogger(__name__)

__all__ = ["make_translator", "translation_model_for", "translation_style_for"]


def translation_model_for(settings) -> str:
    """The configured Hy-MT2, or the default one."""
    if settings is None:
        return TRANSLATION_MODEL
    return settings.value(KEY_TRANSLATION_MODEL, TRANSLATION_MODEL) or TRANSLATION_MODEL


def translation_style_for(settings) -> str | None:
    """The user's translation styles, as Hy-MT2's style template wants them.

    Several styles become one comma-joined phrase: the template takes a single
    ``target_style``, and the model reads a list in one slot perfectly well.
    """
    if settings is None:
        return None
    raw = settings.value(KEY_STYLES, [])
    if isinstance(raw, str):
        styles = [part.strip() for part in raw.split(",") if part.strip()]
    elif isinstance(raw, (list, tuple)):
        styles = [str(part).strip() for part in raw if str(part).strip()]
    else:
        styles = []
    return ", ".join(styles) or None


def make_translator(settings, processor, *, glossary: dict[str, str] | None = None) -> LineTranslator:
    """A translator carrying the user's model, style and glossary."""
    return LineTranslator(
        processor=processor,
        model=translation_model_for(settings),
        style=translation_style_for(settings),
        glossary=dict(glossary or {}),
    )
