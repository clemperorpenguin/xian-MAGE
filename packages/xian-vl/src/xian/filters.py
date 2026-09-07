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

"""Dropping text before it reaches the change gate.

Adapted from RSTGameTranslation's ``Logic.cs``.

Placement is the whole point: these run *before* the content hash, not after.
A permanently-visible HUD label that the recognizer reads slightly differently
every frame would otherwise change the hash on every tick and defeat the gate
entirely — the filter has to remove it before the frame is fingerprinted, not
merely before it is painted.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

__all__ = ["DEFAULT_LINE_CONFIDENCE", "IgnoreRule", "TextFilter"]

#: A whole line below this mean confidence is noise, not text.  RST's value.
DEFAULT_LINE_CONFIDENCE = 0.2

#: Longest line an ignore regex is run against.  There is no portable way to
#: time out a regex in Python, and a user-supplied pattern with nested
#: quantifiers can hang the worker thread; capping the input is the practical
#: defence, since real on-screen lines are far shorter than this.
MAX_REGEX_INPUT = 2000


@dataclass(slots=True)
class IgnoreRule:
    """One user-configured pattern that removes a line before it is hashed."""

    pattern: str
    #: "exact", "contains" or "regex".
    kind: str = "contains"
    _compiled: re.Pattern | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.kind == "regex":
            try:
                self._compiled = re.compile(self.pattern, re.IGNORECASE)
            except re.error as exc:
                # A bad pattern disables that rule; it must never take the
                # whole live loop down with it.
                logger.error("ignoring unusable filter pattern %r: %s", self.pattern, exc)
                self._compiled = None

    def matches(self, text: str) -> bool:
        if self.kind == "exact":
            return text.strip().casefold() == self.pattern.strip().casefold()
        if self.kind == "regex":
            if self._compiled is None:
                return False
            return bool(self._compiled.search(text[:MAX_REGEX_INPUT]))
        return self.pattern.casefold() in text.casefold()


@dataclass
class TextFilter:
    """Confidence floors plus ignore rules, applied to a frame's lines."""

    min_confidence: float = DEFAULT_LINE_CONFIDENCE
    rules: list[IgnoreRule] = field(default_factory=list)

    @classmethod
    def from_settings(cls, raw: str | list | None, *, min_confidence: float = DEFAULT_LINE_CONFIDENCE) -> "TextFilter":
        """Build from the settings value, which is a newline-separated list.

        A line may be prefixed ``regex:`` or ``exact:``; anything else is a
        substring match, which is what almost every user wants and should not
        have to spell.
        """
        if not raw:
            return cls(min_confidence=min_confidence)
        entries = raw.splitlines() if isinstance(raw, str) else [str(item) for item in raw]

        rules: list[IgnoreRule] = []
        for entry in entries:
            entry = entry.strip()
            if not entry:
                continue
            kind = "contains"
            for prefix in ("regex:", "exact:"):
                if entry.lower().startswith(prefix):
                    kind = prefix[:-1]
                    entry = entry[len(prefix) :].strip()
                    break
            if entry:
                rules.append(IgnoreRule(pattern=entry, kind=kind))
        return cls(min_confidence=min_confidence, rules=rules)

    def keeps(self, text: str, confidence: float) -> bool:
        """True when this line should reach the gate."""
        if not text.strip():
            return False
        if confidence < self.min_confidence:
            return False
        return not any(rule.matches(text) for rule in self.rules)

    def apply(self, lines):
        """Filter any sequence of objects carrying ``.text`` and ``.confidence``."""
        return [line for line in lines if self.keeps(line.text, line.confidence)]
