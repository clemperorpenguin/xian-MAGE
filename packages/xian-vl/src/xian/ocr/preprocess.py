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

"""OpenCV preprocessing, in two unrelated jobs that share a file.

**Enhancement** is about the picture: game capture is HDR-tonemapped, often
very dark or very bright, and frequently low-contrast behind a translucent
dialogue panel.  The trigger conditions and filter constants are RST's, tuned
against exactly this input (``process_image_rapidocr.py:106-160``).

**Detector input preparation** is about the model: PP-OCRv5's detector wants a
particular size, layout and normalisation, and the scale factors have to come
back out so boxes can be mapped to source pixels.
"""

from __future__ import annotations

import cv2
import numpy as np

__all__ = [
    "DETECTOR_MEAN",
    "DETECTOR_STD",
    "enhance",
    "needs_enhancement",
    "prepare_detector_input",
    "upscale_small_crop",
]

#: ImageNet statistics, which is what PP-OCRv5's detector was trained against.
DETECTOR_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
DETECTOR_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)

#: Below this standard deviation the image is flat — a dialogue panel washing
#: out the text behind it, or a night scene.
_FLAT_STD = 40.0
#: Outside this intensity band the image is blown out or crushed.
_BRIGHT_MEAN = 200.0
#: Outside this intensity band the image is blown out or crushed.
_DARK_MEAN = 55.0

#: A rectified crop shorter than this recognizes badly; the recognizer's
#: accuracy falls off sharply under roughly 20px of glyph height, and subtitle
#: text at 1080p routinely lands here.
MIN_CROP_HEIGHT = 24


def needs_enhancement(image: np.ndarray) -> bool:
    """True when the image is flat, blown out, or crushed.

    Deliberately cheap — two reductions over a grayscale copy — because it runs
    on every tick and its whole purpose is to skip work on the frames that do
    not need it.
    """
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    mean = float(gray.mean())
    std = float(gray.std())
    return std < _FLAT_STD or mean > _BRIGHT_MEAN or mean < _DARK_MEAN


def enhance(image: np.ndarray, *, force: bool | None = None) -> np.ndarray:
    """Lift text out of a difficult frame.

    ``force`` overrides the auto-detection in both directions, for callers that
    have already measured or that want the cheap path unconditionally.
    """
    apply_heavy = needs_enhancement(image) if force is None else force
    if not apply_heavy:
        # Still worth a light pass: a touch of contrast and a median filter
        # kill the compression speckle that turns into spurious contours.
        out = cv2.convertScaleAbs(image, alpha=1.1, beta=0)
        return cv2.medianBlur(out, 3)

    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
    lightness, a, b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
    lightness = clahe.apply(lightness)
    out = cv2.cvtColor(cv2.merge((lightness, a, b)), cv2.COLOR_LAB2BGR)

    # Edge-preserving denoise before sharpening, so the sharpen amplifies
    # glyph edges rather than the noise CLAHE has just made more visible.
    out = cv2.bilateralFilter(out, 5, 50, 50)

    blurred = cv2.GaussianBlur(out, (0, 0), 3.0)
    return cv2.addWeighted(out, 1.5, blurred, -0.5, 0)


def prepare_detector_input(
    image: np.ndarray,
    *,
    limit_side_len: int = 960,
) -> tuple[np.ndarray, float, float]:
    """Resize and normalise a BGR image into the detector's input tensor.

    Returns ``(tensor, scale_x, scale_y)``, where the scales map detector-space
    coordinates back to source pixels.  They are returned separately and are
    not equal: the resize preserves aspect ratio but the pad to a multiple of
    32 does not, and collapsing them into one number is how boxes end up
    subtly offset on non-square regions.
    """
    height, width = image.shape[:2]
    if height == 0 or width == 0:
        raise ValueError("cannot prepare an empty image")

    ratio = min(limit_side_len / max(height, width), 1.0) if max(height, width) > limit_side_len else 1.0
    resize_h = max(int(round(height * ratio / 32)) * 32, 32)
    resize_w = max(int(round(width * ratio / 32)) * 32, 32)

    resized = cv2.resize(image, (resize_w, resize_h), interpolation=cv2.INTER_LINEAR)
    tensor = resized.astype(np.float32) / 255.0
    tensor = (tensor - DETECTOR_MEAN) / DETECTOR_STD
    tensor = tensor.transpose(2, 0, 1)[np.newaxis, ...]

    return np.ascontiguousarray(tensor), width / resize_w, height / resize_h


def upscale_small_crop(crop: np.ndarray, *, min_height: int = MIN_CROP_HEIGHT) -> np.ndarray:
    """Double a crop that is too short for the recognizer to read reliably."""
    if crop.shape[0] >= min_height:
        return crop
    return cv2.resize(crop, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
