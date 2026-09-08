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

"""PP-OCRv5 text detection: a DBNet forward pass, then OpenCV.

The network's whole output is a single-channel probability map — "how likely is
this pixel to be inside a text region".  Turning that into quads is contour
work, and it is done here with OpenCV rather than inside a framework, adapted
from PaddleOCR's ``DBPostProcess``:

    threshold -> findContours -> minAreaRect -> score by mean probability
              -> unclip -> minAreaRect -> order corners -> scale to source

The unclip step is the one that is not obvious.  DBNet is trained to predict a
*shrunk* version of each text region, because adjacent lines would otherwise
merge into one blob; the postprocess has to grow each contour back out by the
same rule, which is an offset proportional to area over perimeter.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import cv2
import numpy as np
import pyclipper
from shapely.geometry import Polygon

from xian.ocr.preprocess import prepare_detector_input

logger = logging.getLogger(__name__)

__all__ = ["DetectConfig", "TextDetector", "boxes_from_probability_map", "order_quad", "unclip"]


@dataclass(slots=True)
class DetectConfig:
    """Thresholds for the contour postprocess.

    PaddleOCR's defaults, and a dataclass rather than module constants because
    they are the first thing to move on real input.  Game text on a busy
    background is exactly the case that wants ``box_thresh`` nearer 0.45, and
    the person who needs that should not be editing this file.
    """

    #: Probability above which a pixel is inside a text region.
    thresh: float = 0.3
    #: Mean probability a candidate box must reach to survive.
    box_thresh: float = 0.6
    #: How far to grow each shrunk contour back out.
    unclip_ratio: float = 1.5
    #: Contours to consider at all.  A cap, not a target — a frame that
    #: produces more than this is noise, not text.
    max_candidates: int = 1000
    #: Shortest side, in detector pixels, a box may have.
    min_size: int = 3
    #: Long side the input is resized to before detection.
    limit_side_len: int = 960


def order_quad(points: np.ndarray) -> np.ndarray:
    """Order four corners clockwise from top-left.

    ``cv2.boxPoints`` gives no guarantee about where it starts, and every stage
    downstream — rectification, grouping, the vertical-text test — assumes a
    fixed corner order.
    """
    ordered = points[np.argsort(points[:, 0])]
    left, right = ordered[:2], ordered[2:]
    left = left[np.argsort(left[:, 1])]
    right = right[np.argsort(right[:, 1])]
    return np.array([left[0], right[0], right[1], left[1]], dtype=np.float32)


def _box_score(prob_map: np.ndarray, quad: np.ndarray) -> float:
    """Mean probability inside ``quad``.

    Masked to the quad rather than to its bounding box: a rotated line's box
    is mostly background, and scoring against it drags every diagonal box
    below the threshold.
    """
    height, width = prob_map.shape[:2]
    x1 = int(np.clip(np.floor(quad[:, 0].min()), 0, width - 1))
    x2 = int(np.clip(np.ceil(quad[:, 0].max()), 0, width - 1))
    y1 = int(np.clip(np.floor(quad[:, 1].min()), 0, height - 1))
    y2 = int(np.clip(np.ceil(quad[:, 1].max()), 0, height - 1))
    if x2 < x1 or y2 < y1:
        return 0.0

    mask = np.zeros((y2 - y1 + 1, x2 - x1 + 1), dtype=np.uint8)
    shifted = quad.copy()
    shifted[:, 0] -= x1
    shifted[:, 1] -= y1
    cv2.fillPoly(mask, [shifted.astype(np.int32)], 1)
    if not mask.any():
        return 0.0
    return float(cv2.mean(prob_map[y1 : y2 + 1, x1 : x2 + 1], mask)[0])


def unclip(quad: np.ndarray, ratio: float) -> np.ndarray | None:
    """Grow a shrunk contour back out by ``area * ratio / perimeter``.

    Returns the expanded polygon, or ``None`` when the offset collapses it —
    which happens for degenerate contours and must not raise, because it is a
    normal outcome on a noisy frame.
    """
    polygon = Polygon(quad)
    if polygon.length <= 0:
        return None
    distance = polygon.area * ratio / polygon.length

    offset = pyclipper.PyclipperOffset()
    offset.AddPath(quad.astype(np.int64).tolist(), pyclipper.JT_ROUND, pyclipper.ET_CLOSEDPOLYGON)
    expanded = offset.Execute(distance)
    if not expanded:
        return None

    # An offset can split a pinched contour into several rings; the text is in
    # the largest of them.
    largest = max(expanded, key=lambda path: abs(Polygon(path).area) if len(path) >= 3 else 0.0)
    if len(largest) < 3:
        return None
    return np.asarray(largest, dtype=np.float32)


def boxes_from_probability_map(
    prob_map: np.ndarray,
    *,
    config: DetectConfig | None = None,
    scale_x: float = 1.0,
    scale_y: float = 1.0,
    source_size: tuple[int, int] | None = None,
) -> list[np.ndarray]:
    """The whole OpenCV postprocess, separated from the model.

    Split out so it can be tested against a synthetic probability map with no
    weights present, which is most of what there is to get wrong here.
    """
    config = config or DetectConfig()
    if prob_map.ndim != 2:
        prob_map = prob_map.squeeze()
    if prob_map.ndim != 2:
        raise ValueError(f"expected a single-channel probability map, got shape {prob_map.shape}")

    bitmap = (prob_map > config.thresh).astype(np.uint8)
    contours, _ = cv2.findContours(bitmap, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)

    quads: list[np.ndarray] = []
    for contour in contours[: config.max_candidates]:
        if len(contour) < 3:
            continue

        rect = cv2.minAreaRect(contour)
        if min(rect[1]) < config.min_size:
            continue

        points = order_quad(cv2.boxPoints(rect))
        if _box_score(prob_map, points) < config.box_thresh:
            continue

        expanded = unclip(points.reshape(-1, 2), config.unclip_ratio)
        if expanded is None:
            continue

        rect = cv2.minAreaRect(expanded)
        if min(rect[1]) < config.min_size + 2:
            continue

        quad = order_quad(cv2.boxPoints(rect))
        quad[:, 0] *= scale_x
        quad[:, 1] *= scale_y
        if source_size is not None:
            width, height = source_size
            quad[:, 0] = np.clip(quad[:, 0], 0, width)
            quad[:, 1] = np.clip(quad[:, 1], 0, height)
        quads.append(quad)

    return quads


class TextDetector:
    """A PP-OCRv5 detection session plus its postprocess.

    The session is constructed once and reused.  Building one costs tens to
    hundreds of milliseconds, which is most of a tick, so it must never happen
    inside the loop.
    """

    def __init__(self, session, config: DetectConfig | None = None):
        self.session = session
        self.config = config or DetectConfig()
        self._input_name = session.get_inputs()[0].name

    def detect(self, image: np.ndarray) -> list[np.ndarray]:
        """Find every text quad in a BGR image, in source pixels."""
        height, width = image.shape[:2]
        tensor, scale_x, scale_y = prepare_detector_input(image, limit_side_len=self.config.limit_side_len)

        outputs = self.session.run(None, {self._input_name: tensor})
        prob_map = np.asarray(outputs[0])[0]
        if prob_map.ndim == 3:
            prob_map = prob_map[0]

        return boxes_from_probability_map(
            prob_map,
            config=self.config,
            scale_x=scale_x,
            scale_y=scale_y,
            source_size=(width, height),
        )
