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

"""Reading order, line assembly and block merging."""

import numpy as np

from xian.ocr.base import Line
from xian.ocr.grouping import GroupingConfig, group_lines, is_vertical, median_text_size


def line(x, y, width, height, text="x", confidence=0.9) -> Line:
    quad = np.array(
        [[x, y], [x + width, y], [x + width, y + height], [x, y + height]],
        dtype=np.float32,
    )
    return Line(quad=quad, text=text, confidence=confidence)


def test_two_words_on_one_baseline_stay_on_one_line():
    blocks = group_lines([line(10, 10, 40, 20, "hello"), line(60, 12, 40, 20, "world")])

    assert len(blocks) == 1
    assert blocks[0].text == "hello world"


def test_cjk_lines_are_joined_without_a_space():
    """An inserted space is a visible error in Chinese and Japanese."""
    blocks = group_lines(
        [line(10, 10, 40, 20, "你好"), line(52, 10, 40, 20, "世界")],
        space_delimited=False,
    )

    assert blocks[0].text == "你好世界"


def test_lines_a_paragraph_break_apart_become_separate_blocks():
    """1.5x the line height between two lines is a paragraph break.

    Real subtitle line pitch is nearer 1.2x, which leaves a gap well under the
    merge radius; this one is deliberately past it.
    """
    blocks = group_lines([line(10, 10, 60, 20, "first"), line(10, 60, 60, 20, "second")])

    assert [block.text for block in blocks] == ["first", "second"]


def test_a_paragraph_merges_into_one_block():
    """Three consecutive lines of a subtitle are one translation unit."""
    lines = [line(10, 10 + row * 26, 120, 20, f"row{row}") for row in range(3)]

    blocks = group_lines(lines)

    assert len(blocks) == 1
    assert blocks[0].text == "row0\nrow1\nrow2"


def test_two_distant_paragraphs_stay_apart():
    lines = [line(10, 10, 80, 20, "top"), line(10, 300, 80, 20, "bottom")]

    assert len(group_lines(lines)) == 2


def test_one_oversized_box_does_not_drag_the_merge_radius():
    """EasyOCR sizes its merge radius off the tallest box on the page.

    A game screen almost always has one — a title, a damage number, a boss
    nameplate — and with the maximum as the unit it reaches far enough to
    swallow unrelated HUD text into the dialogue block.  The median does not
    move.
    """
    body = [line(10, 10 + row * 26, 120, 20, f"row{row}") for row in range(3)]
    title = line(400, 400, 300, 120, "TITLE")
    unrelated = line(10, 250, 80, 20, "hud")

    blocks = group_lines(body + [title, unrelated])

    assert median_text_size(body + [title, unrelated]) == 20
    texts = {block.text for block in blocks}
    assert "row0\nrow1\nrow2" in texts
    assert "hud" in texts


def test_reading_order_is_top_to_bottom_then_left_to_right():
    lines = [
        line(200, 100, 60, 20, "d"),
        line(10, 10, 60, 20, "a"),
        line(200, 10, 60, 20, "b"),
        line(10, 100, 60, 20, "c"),
    ]

    blocks = group_lines(lines, config=GroupingConfig(block_x_gap=0.1, block_y_gap=0.1))
    read = " ".join(block.text for block in blocks).replace("\n", " ")

    assert read.split() == ["a", "b", "c", "d"]


def test_vertical_text_is_detected_from_the_quads():
    columns = [line(300 - column * 40, 20, 24, 200, f"c{column}") for column in range(3)]

    assert is_vertical(columns)


def test_vertical_columns_read_right_to_left():
    """Tategaki starts at the right-hand column."""
    columns = [line(100, 20, 24, 200, "left"), line(200, 20, 24, 200, "right")]

    blocks = group_lines(columns, space_delimited=False)
    read = " ".join(block.text for block in blocks).replace("\n", " ")

    assert read.split() == ["right", "left"]


def test_horizontal_text_is_not_read_as_vertical():
    rows = [line(10, 10 + row * 26, 200, 20, f"r{row}") for row in range(3)]

    assert not is_vertical(rows)


def test_right_to_left_orders_a_line_from_the_right():
    """MAGE ships an Arabic locale; a line of it reads the other way."""
    lines = [line(10, 10, 60, 20, "second"), line(100, 10, 60, 20, "first")]

    blocks = group_lines(lines, rtl=True)

    assert blocks[0].text == "first second"


def test_empty_and_blank_lines_are_dropped():
    assert group_lines([]) == []
    assert group_lines([line(10, 10, 40, 20, "   ")]) == []


def test_a_block_reports_the_worst_confidence_of_its_lines():
    """A block is only as trustworthy as its least certain line."""
    blocks = group_lines(
        [line(10, 10, 40, 20, "sure", confidence=0.99), line(55, 10, 40, 20, "maybe", confidence=0.4)]
    )

    assert blocks[0].confidence == 0.4
