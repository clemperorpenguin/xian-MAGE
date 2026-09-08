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

"""PP-OCRv5 text recognition: batched CRNN forward passes and a CTC decode.

Adapted from PaddleOCR's recognition preprocessing and ``CTCLabelDecode``.

Two details carry most of the performance and most of the correctness:

* **Crops are batched in aspect-ratio order.**  Every crop in a batch is padded
  to the batch's widest, so an unsorted batch pads a 4:1 crop out to a 40:1
  crop's width and spends most of its compute on padding.  Sorting first makes
  each batch internally similar.

* **The blank index and the space are inferred from the model, not assumed.**
  The character dictionary shipped with a recognizer does not say whether the
  network was trained with a trailing space class, and a charset off by one
  decodes to fluent-looking nonsense rather than to an error — the worst
  possible failure, because nothing downstream can tell it is wrong.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import cv2
import numpy as np

logger = logging.getLogger(__name__)

__all__ = ["RecognizeConfig", "TextRecognizer", "ctc_greedy_decode"]


@dataclass(slots=True)
class RecognizeConfig:
    """Input geometry and batching for the recognizer."""

    #: PP-OCRv5 recognition input height.
    image_height: int = 48
    #: Crops per forward pass.  PaddleOCR's default; larger batches help less
    #: than they cost once the padding is accounted for.
    batch_size: int = 6
    #: Widest crop, as a multiple of the height, before it is squeezed.  A
    #: single very long line otherwise sets the padded width for its batch.
    max_width_ratio: float = 25.0
    #: Lines below this confidence are dropped by the engine.
    min_confidence: float = 0.0


def _resize_for_batch(crop: np.ndarray, height: int, padded_width: int) -> np.ndarray:
    """Resize one crop to the batch height and left-align it in the padding."""
    crop_h, crop_w = crop.shape[:2]
    ratio = crop_w / max(crop_h, 1)
    resized_w = max(min(int(np.ceil(height * ratio)), padded_width), 1)

    resized = cv2.resize(crop, (resized_w, height), interpolation=cv2.INTER_LINEAR)
    normalized = resized.astype(np.float32).transpose(2, 0, 1) / 255.0
    normalized = (normalized - 0.5) / 0.5

    padded = np.zeros((3, height, padded_width), dtype=np.float32)
    padded[:, :, :resized_w] = normalized
    return padded


def ctc_greedy_decode(predictions: np.ndarray, charset: list[str]) -> tuple[str, float]:
    """Collapse one sequence of per-timestep class probabilities into text.

    Repeats and blanks are dropped, in that order — a repeated character in the
    source survives only when a blank separates its two timesteps, which is
    what CTC blanks are for.  Confidence is the mean probability over the
    timesteps that contributed a character, not over the whole sequence: a long
    padded tail of confident blanks would otherwise flatter every short line.
    """
    indices = predictions.argmax(axis=1)
    probabilities = predictions.max(axis=1)

    characters: list[str] = []
    kept: list[float] = []
    previous = -1
    for position, index in enumerate(indices):
        if index != previous and index != 0 and index < len(charset):
            characters.append(charset[index])
            kept.append(float(probabilities[position]))
        previous = int(index)

    confidence = float(np.mean(kept)) if kept else 0.0
    return "".join(characters), confidence


class TextRecognizer:
    """One PP-OCRv5 recognizer — one script — and its character dictionary."""

    def __init__(self, session, characters: list[str], config: RecognizeConfig | None = None):
        self.session = session
        self.config = config or RecognizeConfig()
        self._characters = characters
        self._input_name = session.get_inputs()[0].name
        self._charset: list[str] | None = None

    def _build_charset(self, num_classes: int) -> list[str]:
        """Reconcile the dictionary with the network's actual output width.

        ``blank`` always takes index 0.  A model trained with a space class
        carries one more output than the dictionary explains, and that is the
        only reliable signal that it has one.
        """
        charset = ["<blank>"] + list(self._characters)
        extra = num_classes - len(charset)
        if extra == 1:
            charset.append(" ")
        elif extra != 0:
            logger.warning(
                "recognizer output width %d does not match its %d-character dictionary "
                "(off by %d); text may decode incorrectly",
                num_classes,
                len(self._characters),
                extra,
            )
            charset.extend([""] * max(extra, 0))
        return charset

    def recognize(self, crops: list[np.ndarray]) -> list[tuple[str, float]]:
        """Read a list of rectified crops, returning ``(text, confidence)``.

        Results come back in the caller's order, not in the aspect-sorted order
        the batches ran in.
        """
        if not crops:
            return []

        order = sorted(range(len(crops)), key=lambda i: crops[i].shape[1] / max(crops[i].shape[0], 1))
        results: list[tuple[str, float]] = [("", 0.0)] * len(crops)
        height = self.config.image_height

        for start in range(0, len(order), self.config.batch_size):
            batch_indices = order[start : start + self.config.batch_size]

            widest_ratio = max(crops[i].shape[1] / max(crops[i].shape[0], 1) for i in batch_indices)
            widest_ratio = min(max(widest_ratio, 1.0), self.config.max_width_ratio)
            padded_width = max(int(np.ceil(height * widest_ratio / 8) * 8), 16)

            batch = np.stack([_resize_for_batch(crops[i], height, padded_width) for i in batch_indices])
            outputs = self.session.run(None, {self._input_name: np.ascontiguousarray(batch)})
            predictions = np.asarray(outputs[0])

            if self._charset is None:
                self._charset = self._build_charset(predictions.shape[-1])

            for position, index in enumerate(batch_indices):
                results[index] = ctc_greedy_decode(predictions[position], self._charset)

        return results
