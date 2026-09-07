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

"""Local OCR: PP-OCRv5 through ONNX Runtime, with OpenCV owning the geometry.

The live overlay's second engine.  Where ``xian.grounding`` asks one vision
model to detect, read and translate in a single call, this package does the
detecting and reading locally and leaves only the translation to the network —
which is what makes the translation call skippable when the *text* has not
changed, rather than only when the pixels have not.

Imports are lazy: the extra (``xian-vl[ocr]``) is optional, and importing
``xian`` on a machine that never switches engines must not require it.
"""

from xian.ocr.base import Block, Line, Quad, Reader, quad_bounds, quad_height, quad_width
from xian.ocr.detect import DetectConfig
from xian.ocr.recognize import RecognizeConfig

__all__ = [
    "Block",
    "DetectConfig",
    "Line",
    "PaddleOcrEngine",
    "Quad",
    "Reader",
    "RecognizeConfig",
    "quad_bounds",
    "quad_height",
    "quad_width",
]


def __getattr__(name: str):
    """Defer the engine import until something actually asks for it."""
    if name == "PaddleOcrEngine":
        from xian.ocr.engine import PaddleOcrEngine

        return PaddleOcrEngine
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
