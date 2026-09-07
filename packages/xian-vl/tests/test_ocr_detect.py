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

"""The DB contour postprocess, against synthetic probability maps.

No weights are needed to test any of this, which is the point of keeping the
postprocess separate from the session: the geometry is where the mistakes are,
and a synthetic map makes every one of them visible.
"""

import numpy as np
import pytest

from xian.ocr.detect import DetectConfig, boxes_from_probability_map, order_quad, unclip


def probability_map(rect, *, value=1.0, size=(200, 300)):
    """A map that is ``value`` inside ``rect`` and zero everywhere else."""
    x1, y1, x2, y2 = rect
    prob = np.zeros(size, dtype=np.float32)
    prob[y1:y2, x1:x2] = value
    return prob


def test_a_rectangle_comes_back_as_one_quad():
    quads = boxes_from_probability_map(probability_map((50, 60, 200, 90)))

    assert len(quads) == 1
    assert quads[0].shape == (4, 2)


def test_the_recovered_box_contains_the_region_it_was_found_in():
    """DBNet predicts a shrunk region; the postprocess grows it back out.

    So the box must cover the source rectangle, never sit inside it — a box
    that undershoots clips the first and last glyph off every line.
    """
    rect = (50, 60, 200, 90)
    quad = boxes_from_probability_map(probability_map(rect))[0]

    x1, y1, x2, y2 = rect
    assert quad[:, 0].min() <= x1
    assert quad[:, 1].min() <= y1
    assert quad[:, 0].max() >= x2
    assert quad[:, 1].max() >= y2


def test_unclip_grows_by_area_over_perimeter():
    """The expansion is a specific distance, not a percentage."""
    quad = np.array([[0, 0], [100, 0], [100, 20], [0, 20]], dtype=np.float32)
    # area 2000, perimeter 240, ratio 1.5 -> 12.5px in every direction.
    expanded = unclip(quad, 1.5)

    assert expanded is not None
    assert expanded[:, 0].min() == pytest.approx(-12.5, abs=1.5)
    assert expanded[:, 0].max() == pytest.approx(112.5, abs=1.5)


def test_a_faint_region_is_rejected_by_the_box_threshold():
    """Above the binarisation threshold, below the score threshold.

    This is the gate that keeps a compression artefact or a gradient edge from
    becoming a text box, and it is separate from the binarisation on purpose.
    """
    faint = probability_map((50, 60, 200, 90), value=0.35)

    assert boxes_from_probability_map(faint) == []
    assert len(boxes_from_probability_map(faint, config=DetectConfig(box_thresh=0.3))) == 1


def test_a_region_thinner_than_min_size_is_dropped():
    assert boxes_from_probability_map(probability_map((50, 60, 200, 62))) == []


def test_max_candidates_caps_the_work_on_a_noisy_frame():
    """A frame producing thousands of contours is noise, and must not be slow."""
    prob = np.zeros((200, 300), dtype=np.float32)
    for row in range(0, 200, 4):
        for column in range(0, 300, 4):
            prob[row : row + 2, column : column + 2] = 1.0

    quads = boxes_from_probability_map(prob, config=DetectConfig(max_candidates=10, min_size=1))

    assert len(quads) <= 10


def test_boxes_are_scaled_back_into_source_pixels():
    """The detector works at its own resolution and must undo it."""
    prob = probability_map((50, 60, 200, 90))

    plain = boxes_from_probability_map(prob)[0]
    scaled = boxes_from_probability_map(prob, scale_x=2.0, scale_y=3.0)[0]

    assert scaled[:, 0].max() == pytest.approx(plain[:, 0].max() * 2.0, rel=1e-3)
    assert scaled[:, 1].max() == pytest.approx(plain[:, 1].max() * 3.0, rel=1e-3)


def test_boxes_are_clamped_to_the_source_image():
    """Unclip can push a box off the edge of a region that is all text."""
    quad = boxes_from_probability_map(
        probability_map((0, 0, 300, 30)),
        source_size=(300, 200),
    )[0]

    assert quad[:, 0].min() >= 0
    assert quad[:, 1].min() >= 0
    assert quad[:, 0].max() <= 300
    assert quad[:, 1].max() <= 200


def test_an_empty_map_finds_nothing():
    assert boxes_from_probability_map(np.zeros((100, 100), dtype=np.float32)) == []


def test_order_quad_puts_the_corners_clockwise_from_top_left():
    """cv2.boxPoints makes no promise about where it starts, and every stage
    downstream assumes it does."""
    shuffled = np.array([[100, 50], [10, 50], [100, 10], [10, 10]], dtype=np.float32)

    ordered = order_quad(shuffled)

    assert ordered.tolist() == [[10, 10], [100, 10], [100, 50], [10, 50]]


def test_a_squeezed_probability_map_is_accepted():
    """Sessions hand back (1, 1, H, W); callers should not have to care."""
    prob = probability_map((50, 60, 200, 90))[np.newaxis, np.newaxis, ...]

    assert len(boxes_from_probability_map(prob)) == 1
