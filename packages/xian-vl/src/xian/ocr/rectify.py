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

"""Turn a detected quad into an upright rectangle the recognizer can read.

Adapted from PaddleOCR's ``get_rotate_crop_image``.

This is the step that makes the detector's non-axis-aligned output useful.  A
dialogue panel rendered in perspective, a rotated nameplate, a banner following
a curve — the detector finds the quad, and the recognizer never learns that any
of that happened, because it only ever sees a rectangle.
"""

from __future__ import annotations

import cv2
import numpy as np

from xian.ocr.preprocess import upscale_small_crop

__all__ = ["VERTICAL_ASPECT", "rectify"]

#: Height-to-width ratio at which a crop is read as vertical text and rotated
#: upright.  PaddleOCR's constant.  Below it a tall crop is more likely to be a
#: single wide glyph than a column of text.
VERTICAL_ASPECT = 1.5


def rectify(image: np.ndarray, quad: np.ndarray, *, upscale: bool = True) -> np.ndarray:
    """Perspective-correct the region under ``quad`` into an upright crop.

    ``quad`` is four points clockwise from top-left, in source pixels.  The
    output width and height are taken from the quad's own longest opposing
    edges rather than from its bounding box, so a rotated line comes out at its
    true length instead of stretched to the diagonal.
    """
    points = np.asarray(quad, dtype=np.float32)
    if points.shape != (4, 2):
        raise ValueError(f"expected 4 corner points, got {points.shape}")

    width = int(round(max(np.linalg.norm(points[0] - points[1]), np.linalg.norm(points[3] - points[2]))))
    height = int(round(max(np.linalg.norm(points[0] - points[3]), np.linalg.norm(points[1] - points[2]))))
    width, height = max(width, 1), max(height, 1)

    target = np.array([[0, 0], [width, 0], [width, height], [0, height]], dtype=np.float32)
    transform = cv2.getPerspectiveTransform(points, target)
    crop = cv2.warpPerspective(
        image,
        transform,
        (width, height),
        borderMode=cv2.BORDER_REPLICATE,
        flags=cv2.INTER_CUBIC,
    )

    # Vertical text: the crop is a column, and the recognizer reads rows.
    # Counter-clockwise, because CJK columns read top-to-bottom and that is the
    # direction that puts the first character on the left after the rotation.
    if crop.shape[0] * 1.0 / max(crop.shape[1], 1) >= VERTICAL_ASPECT:
        crop = cv2.rotate(crop, cv2.ROTATE_90_COUNTERCLOCKWISE)

    return upscale_small_crop(crop) if upscale else crop
