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

"""The shapes every stage of the OCR pipeline passes along.

Coordinates are **source-image pixels** everywhere in this package.  The
detector works in its own resized space and the recognizer in a rectified crop,
but both convert back before they return, so nothing downstream ever has to ask
which space a number is in — that question is what made the old grounding path's
box handling fragile.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, Sequence, runtime_checkable

import numpy as np

__all__ = ["Block", "Line", "Quad", "Reader", "quad_bounds", "quad_height", "quad_width"]

#: Four corner points, clockwise from top-left, in source-image pixels.
Quad = np.ndarray


def quad_bounds(quad: Quad) -> tuple[int, int, int, int]:
    """The axis-aligned bounding box of a quad, as ``(x1, y1, x2, y2)``."""
    xs, ys = quad[:, 0], quad[:, 1]
    return int(xs.min()), int(ys.min()), int(np.ceil(xs.max())), int(np.ceil(ys.max()))


def quad_width(quad: Quad) -> float:
    """Width along the text direction, not along the x axis.

    A rotated line's bounding box is wider than the line is, which is why the
    grouping thresholds measure the quad rather than its bounds.
    """
    top = np.linalg.norm(quad[1] - quad[0])
    bottom = np.linalg.norm(quad[2] - quad[3])
    return float(max(top, bottom))


def quad_height(quad: Quad) -> float:
    """Height across the text direction."""
    left = np.linalg.norm(quad[3] - quad[0])
    right = np.linalg.norm(quad[2] - quad[1])
    return float(max(left, right))


@dataclass(slots=True)
class Line:
    """One recognized text line, with the quad the detector found it in."""

    quad: Quad
    text: str
    confidence: float

    @property
    def box(self) -> tuple[int, int, int, int]:
        return quad_bounds(self.quad)

    @property
    def height(self) -> float:
        return quad_height(self.quad)

    @property
    def width(self) -> float:
        return quad_width(self.quad)

    @property
    def center(self) -> tuple[float, float]:
        return float(self.quad[:, 0].mean()), float(self.quad[:, 1].mean())


@dataclass(slots=True)
class Block:
    """Lines that belong together — a paragraph, a subtitle, one speech bubble.

    The block, not the line, is the translation unit.  A two-line subtitle sent
    as two requests comes back as two half-sentences translated without each
    other, which reads worse than either half deserved.
    """

    lines: list[Line] = field(default_factory=list)
    #: True when the block reads top-to-bottom in columns (tategaki).
    vertical: bool = False

    @property
    def text(self) -> str:
        return "\n".join(line.text for line in self.lines)

    @property
    def confidence(self) -> float:
        if not self.lines:
            return 0.0
        return sum(line.confidence for line in self.lines) / len(self.lines)

    @property
    def box(self) -> tuple[int, int, int, int]:
        boxes = [line.box for line in self.lines]
        return (
            min(b[0] for b in boxes),
            min(b[1] for b in boxes),
            max(b[2] for b in boxes),
            max(b[3] for b in boxes),
        )


@runtime_checkable
class Reader(Protocol):
    """What the live worker needs from an OCR engine, and nothing more.

    Kept narrow on purpose: the grounding path and the OCR path both feed the
    same overlay, and a reader that could only be swapped by rewriting the
    worker would defeat the point of having two engines.
    """

    def read(self, image: np.ndarray) -> Sequence[Line]:
        """Detect and recognize every text line in a BGR image."""
        ...
