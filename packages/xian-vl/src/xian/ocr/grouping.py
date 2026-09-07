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

"""Assemble detected quads into reading order, lines, and blocks.

The detector returns quads in whatever order the contours came out; none of
them know they are part of a sentence.  Three stages fix that, and each is
adapted from a different project because each solved a different half of it:

* **Reading order and line assembly — docTR** (``DocumentBuilder._sort_boxes``
  and ``_resolve_lines``).  docTR expresses its line-break distance as a
  fraction of *page width*, which means nothing for a screen region of
  arbitrary size, so here the unit is the local median box height instead.

* **Blocks — EasyOCR** (``get_paragraph``).  A free merge that absorbs a line
  into a paragraph when it is close enough to the paragraph's running bounds.
  EasyOCR uses the *maximum* box height as the merge radius; on a game screen
  one oversized title then sets the radius for everything and swallows
  unrelated HUD text, so here it is the median.

* **Vertical text — RSTGameTranslation** (``BlockDetectionManager``).  Detected
  from the quads rather than from the text, and it flips both the axis roles
  and the column order.

The block, not the line, is the translation unit: a two-line subtitle sent as
two requests comes back as two half-sentences translated without each other.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass

import cv2
import numpy as np

from xian.ocr.base import Block, Line, quad_height
from xian.ocr.detect import order_quad

__all__ = ["GroupingConfig", "group_lines", "is_vertical", "median_text_size", "merge_row"]


@dataclass(slots=True)
class GroupingConfig:
    """Distances, all in multiples of the median line height.

    Expressing them relative to the text rather than to the region is what
    makes one set of constants work for a 480p subtitle strip and a 4K panel.
    """

    #: How far a box's centre may sit from a line's before it starts a new one.
    line_band: float = 0.6
    #: A backwards x jump this large ends the line even at the same height.
    line_break_x: float = 2.0
    #: Horizontal reach when merging lines into a block.
    block_x_gap: float = 1.2
    #: Vertical reach when merging lines into a block.  Smaller than the
    #: horizontal one: paragraphs are separated vertically, so being generous
    #: here is what merges two unrelated stacked panels.
    block_y_gap: float = 0.8
    #: Aspect at which one quad looks like a column of text.
    vertical_aspect: float = 1.5
    #: Fraction of quads that must look vertical for the frame to be vertical.
    vertical_fraction: float = 0.5


def median_text_size(lines: list[Line], *, vertical: bool = False) -> float:
    """The unit every threshold is expressed in: text size across the reading
    direction.

    For horizontal text that is the line height.  For tategaki it is the column
    *width* — a vertical line is as tall as the paragraph, so measuring its
    height would produce a unit the size of the whole block and merge the
    entire screen into one.

    Median, not mean and not maximum: a title twice the size of the body text
    must not widen the merge radius for everything else, and neither must one
    spurious full-height contour.
    """
    if not lines:
        return 1.0
    sizes = [max(line.width if vertical else line.height, 1.0) for line in lines]
    return float(statistics.median(sizes))


def is_vertical(lines: list[Line], config: GroupingConfig | None = None) -> bool:
    """True when this looks like tategaki — vertical CJK in columns.

    Measured on the quads, not on the characters: the detector sees the shape
    of a column before anything has been recognized, and a recognizer given a
    column reads it as a very tall single glyph and returns noise.
    """
    config = config or GroupingConfig()
    if not lines:
        return False
    tall = sum(1 for line in lines if line.height / max(line.width, 1.0) >= config.vertical_aspect)
    return tall / len(lines) > config.vertical_fraction


def merge_row(lines: list[Line], *, space_delimited: bool) -> Line:
    """Collapse detections that share a baseline into one line.

    The quad is the minimum-area rectangle over every corner, so a row that
    slopes slightly keeps its slope instead of being squared off to its bounds.
    """
    if len(lines) == 1:
        return lines[0]

    points = np.vstack([line.quad for line in lines]).astype(np.float32)
    quad = order_quad(cv2.boxPoints(cv2.minAreaRect(points)))
    separator = " " if space_delimited else ""
    return Line(
        quad=quad,
        text=separator.join(line.text for line in lines),
        confidence=min(line.confidence for line in lines),
    )


def _sort_boxes(lines: list[Line], *, vertical: bool, rtl: bool) -> list[Line]:
    """docTR's reading-order sort, with the axes swapped for tategaki."""
    if vertical:
        # Columns first, right to left; then top to bottom inside a column.
        return sorted(lines, key=lambda line: (-line.center[0], line.center[1]))
    if rtl:
        return sorted(lines, key=lambda line: (line.center[1], -line.center[0]))
    return sorted(lines, key=lambda line: (line.center[1], line.center[0]))


def _resolve_lines(
    lines: list[Line],
    unit: float,
    config: GroupingConfig,
    *,
    vertical: bool,
    rtl: bool,
) -> list[list[Line]]:
    """docTR's line walk: extend the current line, or start a new one."""
    rows: list[list[Line]] = []
    current: list[Line] = []
    # Along-axis position and across-axis position, so one walk serves both
    # orientations.
    across = (lambda line: line.center[0]) if vertical else (lambda line: line.center[1])
    along = (lambda line: line.center[1]) if vertical else (lambda line: line.center[0])

    for line in lines:
        if not current:
            current = [line]
            continue

        reference = current[-1]
        same_line = abs(across(line) - across(reference)) <= unit * config.line_band
        # A large jump *backwards* along the reading direction is a wrap, even
        # when the two boxes sit at the same height — two columns of a menu.
        direction = -1.0 if (rtl and not vertical) else 1.0
        regressed = direction * (along(line) - along(reference)) < -unit * config.line_break_x

        if same_line and not regressed:
            current.append(line)
        else:
            rows.append(current)
            current = [line]

    if current:
        rows.append(current)
    return rows


def _merge_blocks(
    rows: list[Line],
    unit: float,
    config: GroupingConfig,
    *,
    vertical: bool,
) -> list[list[Line]]:
    """EasyOCR's free merge, with a median-derived radius."""
    x_reach = unit * config.block_x_gap
    y_reach = unit * config.block_y_gap
    if vertical:
        # Columns of one paragraph sit side by side, so the generous axis flips.
        x_reach, y_reach = y_reach, x_reach

    blocks: list[list[Line]] = []
    bounds: list[tuple[float, float, float, float]] = []

    for row in rows:
        x1, y1, x2, y2 = row.box
        for index, (bx1, by1, bx2, by2) in enumerate(bounds):
            near_x = x1 <= bx2 + x_reach and x2 >= bx1 - x_reach
            near_y = y1 <= by2 + y_reach and y2 >= by1 - y_reach
            if near_x and near_y:
                blocks[index].append(row)
                bounds[index] = (min(bx1, x1), min(by1, y1), max(bx2, x2), max(by2, y2))
                break
        else:
            blocks.append([row])
            bounds.append((x1, y1, x2, y2))

    return blocks


def group_lines(
    lines: list[Line],
    *,
    config: GroupingConfig | None = None,
    space_delimited: bool = True,
    rtl: bool = False,
) -> list[Block]:
    """Turn loose detections into blocks, in reading order.

    ``space_delimited`` decides how detections on one baseline are joined —
    with a space for Latin and Cyrillic, with nothing for CJK, where an
    inserted space is a visible error.
    """
    config = config or GroupingConfig()
    lines = [line for line in lines if line.text.strip()]
    if not lines:
        return []

    vertical = is_vertical(lines, config)
    unit = median_text_size(lines, vertical=vertical)

    ordered = _sort_boxes(lines, vertical=vertical, rtl=rtl)
    rows = [
        merge_row(row, space_delimited=space_delimited)
        for row in _resolve_lines(ordered, unit, config, vertical=vertical, rtl=rtl)
    ]

    blocks = []
    for member_lines in _merge_blocks(rows, unit, config, vertical=vertical):
        blocks.append(Block(lines=member_lines, vertical=vertical))
    return blocks
