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

"""Continuous translation of a locked region, by one vision call.

The original live engine, and still the default.  ``ground_and_translate``
detects, reads and translates in a single request, which is why it needs no
local models and why it costs what it costs.  Everything around the call —
the tick, the gate, the carry, the painting — lives in :mod:`mage.live_common`
and is shared with the OCR engine.
"""

from __future__ import annotations

import logging

from PIL import Image

from mage.live_common import (
    CHANGE_THRESHOLD_RATIO,
    DEFAULT_CHANGE_THRESHOLD,
    DEFAULT_INTERVAL_MS,
    LIVE_HASH_SIZE,
    MAX_CAPTURE_FAILURES,
    PAINT_MASK_PADDING,
    REGION_CHANGE_THRESHOLD,
    REGION_COMPARE_SIZE,
    LiveRegion,
    LiveWorkerBase,
    phash_distance,
    region_difference,
    regions_signature,
    sample_background,
)

logger = logging.getLogger(__name__)

__all__ = [
    "CHANGE_THRESHOLD_RATIO",
    "DEFAULT_CHANGE_THRESHOLD",
    "DEFAULT_INTERVAL_MS",
    "LIVE_HASH_SIZE",
    "MAX_CAPTURE_FAILURES",
    "PAINT_MASK_PADDING",
    "REGION_CHANGE_THRESHOLD",
    "REGION_COMPARE_SIZE",
    "LiveLensWorker",
    "LiveRegion",
    "phash_distance",
    "region_difference",
    "regions_signature",
    "sample_background",
]


class LiveLensWorker(LiveWorkerBase):
    """Polls a screen region and emits translated, positioned text."""

    async def _translate_frame(self, frame: Image.Image):
        """Produce located, translated regions for one frame.

        One vision call does detection, reading and translation together.
        Measured against the local-OCR sidecar this replaced: ~1.0s versus
        ~2.25s for OCR plus a separate batch translation, with the first line
        on screen at ~460ms rather than after the whole chain.
        """
        glossary = await self._glossary()

        from xian.grounding import ground_and_translate

        # Paint each line as the model describes it rather than waiting for the
        # whole screen: on a busy frame the last box can be seconds behind the
        # first, and a partly-translated overlay is useful immediately.
        def publish_partial(regions):
            self._publish(regions, frame)

        return await ground_and_translate(
            self.processor, frame, self.source_lang, self.target_lang,
            glossary=glossary, on_region=publish_partial,
        )
