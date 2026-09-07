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

"""Perspective rectification of a detected quad."""

import numpy as np
import pytest

from xian.ocr.preprocess import MIN_CROP_HEIGHT, upscale_small_crop
from xian.ocr.rectify import rectify


def gradient_image(width=400, height=300):
    """An image whose pixels encode their own coordinates.

    Makes it possible to assert *what* was sampled, not merely that something
    of the right shape came back.
    """
    image = np.zeros((height, width, 3), dtype=np.uint8)
    image[:, :, 0] = np.linspace(0, 255, width, dtype=np.uint8)[np.newaxis, :]
    image[:, :, 1] = np.linspace(0, 255, height, dtype=np.uint8)[:, np.newaxis]
    return image


def test_an_axis_aligned_quad_comes_back_at_its_own_size():
    quad = np.array([[50, 40], [250, 40], [250, 90], [50, 90]], dtype=np.float32)

    crop = rectify(gradient_image(), quad, upscale=False)

    assert crop.shape[:2] == (50, 200)


def test_a_rotated_quad_is_measured_along_its_edges_not_its_bounds():
    """A diagonal line's bounding box is much longer than the line is.

    Sizing from the bounds stretches the text horizontally and the recognizer
    reads the result as a different string.
    """
    quad = np.array([[100, 100], [200, 150], [180, 190], [80, 140]], dtype=np.float32)

    crop = rectify(gradient_image(), quad, upscale=False)

    expected_width = round(np.linalg.norm(quad[0] - quad[1]))
    assert crop.shape[1] == pytest.approx(expected_width, abs=1)
    assert crop.shape[1] < 200 - 80  # narrower than the bounding box


def test_a_tall_crop_is_rotated_upright():
    """Vertical CJK text arrives as a column and the recognizer reads rows."""
    quad = np.array([[100, 50], [140, 50], [140, 250], [100, 250]], dtype=np.float32)

    crop = rectify(gradient_image(), quad, upscale=False)

    assert crop.shape[1] > crop.shape[0]


def test_a_crop_just_under_the_vertical_threshold_is_left_alone():
    """1.5 is a real boundary: a wide single glyph must not be rotated."""
    quad = np.array([[100, 50], [140, 50], [140, 105], [100, 105]], dtype=np.float32)

    crop = rectify(gradient_image(), quad, upscale=False)

    assert crop.shape[0] > crop.shape[1]


def test_a_short_crop_is_upscaled_for_the_recognizer():
    small = np.zeros((12, 80, 3), dtype=np.uint8)

    assert upscale_small_crop(small).shape[:2] == (24, 160)


def test_a_tall_enough_crop_is_not_upscaled():
    tall = np.zeros((MIN_CROP_HEIGHT, 80, 3), dtype=np.uint8)

    assert upscale_small_crop(tall).shape[:2] == (MIN_CROP_HEIGHT, 80)


def test_a_malformed_quad_is_refused():
    with pytest.raises(ValueError):
        rectify(gradient_image(), np.array([[0, 0], [10, 0], [10, 10]], dtype=np.float32))
