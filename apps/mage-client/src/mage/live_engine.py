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

"""Which live engine actually runs, given the setting and the machine.

Two engines translate a locked region: a vision model that reads and
translates in one call, and the local PP-OCRv5 reader that sends only text.
The setting says which one the user wants.  This says which one they can have.

The difference matters because PP-OCRv5 has never had a published ONNX
release, so its weights exist only once somebody has run
``scripts/export_ppocr_onnx.py`` — which, on a fresh install, nobody has.  A
box built on the reader before that happens fails on its first read, in a
worker thread, on a tick, where all the user sees is a border turning red and
no text ever arriving.  The vision model needs nothing exported and is already
loaded for chat and grounding, so that is what an unprepared machine gets,
with one line saying why.

Resolved here rather than at each call site because there are two — the boxes
and the classic live lens — and an engine chosen one way in one place and
another way in the other is how the boxes came to ignore the setting entirely.
"""

from __future__ import annotations

import logging
import os

from mage.settings_keys import (
    DEFAULT_LIVE_ENGINE,
    KEY_LIVE_ENGINE,
    KEY_OCR_DETECTOR,
    KEY_SOURCE_LANG,
    LIVE_ENGINE_GROUNDING,
    LIVE_ENGINE_OCR,
)

logger = logging.getLogger(__name__)

__all__ = ["ocr_models_ready", "resolve_live_engine"]

#: Said once per run, not once per box: five boxes starting together would
#: otherwise report the same missing weights five times.
_warned = False


def ocr_models_ready(settings) -> bool:
    """Whether the local reader has the weights it needs, on disk, intact.

    Checks the two models a read actually loads — the detector, and the
    recognizer for the configured source language — rather than the catalog as
    a whole, because a machine that exported one script's weights and not
    another's is a machine that works for Chinese and not for Korean.

    A configured distribution host counts as ready: fetching is then
    ``ensure_model``'s job, and refusing here would fall back to the vision
    model for a download that was going to succeed.
    """
    if os.environ.get("XIAN_OCR_BASE_URL", "").strip():
        return True

    try:
        from xian.ocr.engine import DEFAULT_DETECTOR
        from xian.ocr.models import verify_model
        from xian.ocr.scripts import SCRIPTS, recognizer_script_for
    except ImportError as exc:
        # The OCR extra is optional; without it there is no reader at all.
        logger.info("local OCR is not installed (%s)", exc)
        return False

    detector = (settings.value(KEY_OCR_DETECTOR, "") if settings else "") or DEFAULT_DETECTOR
    source = settings.value(KEY_SOURCE_LANG, "") if settings else ""
    recognizer = SCRIPTS[recognizer_script_for(source)]

    return verify_model(detector) and verify_model(recognizer)


def resolve_live_engine(settings) -> str:
    """The engine to build a live worker with.

    Returns one of :data:`~mage.settings_keys.LIVE_ENGINE_OCR` or
    :data:`~mage.settings_keys.LIVE_ENGINE_GROUNDING`.  The vision model is
    never second-guessed — it is always available — so the only substitution
    made here is away from a reader that cannot read.
    """
    global _warned

    choice = (settings.value(KEY_LIVE_ENGINE, DEFAULT_LIVE_ENGINE) if settings else DEFAULT_LIVE_ENGINE)
    if choice != LIVE_ENGINE_OCR:
        return LIVE_ENGINE_GROUNDING
    if ocr_models_ready(settings):
        return LIVE_ENGINE_OCR

    if not _warned:
        _warned = True
        logger.warning(
            "The local OCR weights are not exported, so live translation is using the "
            "vision model instead. To use the local reader, run: "
            "uv run --package mage-client python scripts/export_ppocr_onnx.py"
        )
    return LIVE_ENGINE_GROUNDING
