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

"""Which PP-OCRv5 recognizer reads which script.

PP-OCRv5 ships one recognizer per script family rather than one model that
covers everything, so the source language has to pick one.  The CJK model is
the only one that also covers Latin, which makes it the right default and the
right answer for "auto".
"""

from __future__ import annotations

__all__ = ["SCRIPTS", "DEFAULT_SCRIPT", "recognizer_script_for"]

#: script -> the recognizer model id that reads it.
SCRIPTS: dict[str, str] = {
    "cjk": "PP-OCRv5_mobile_rec",
    "latin": "latin_PP-OCRv5_mobile_rec",
    "korean": "korean_PP-OCRv5_mobile_rec",
    "eslav": "eslav_PP-OCRv5_mobile_rec",
}

#: Simplified and Traditional Chinese, Japanese, English and handwriting all
#: live in the CJK recognizer, which also carries the full Latin alphabet.
#: Anything unrecognised lands here, because a model that reads too much is a
#: far cheaper mistake than one that reads none of the script in front of it.
DEFAULT_SCRIPT = "cjk"

#: Language tag prefix -> script.  Matched on the part before any region
#: subtag, so "zh-CN", "zh_TW" and "zh" all resolve the same way.
_LANGUAGE_SCRIPTS: dict[str, str] = {
    "zh": "cjk",
    "ja": "cjk",
    "en": "cjk",
    "ko": "korean",
    "ru": "eslav",
    "uk": "eslav",
    "be": "eslav",
    "fr": "latin",
    "de": "latin",
    "es": "latin",
    "it": "latin",
    "pt": "latin",
    "nl": "latin",
    "pl": "latin",
    "cs": "latin",
    "tr": "latin",
    "vi": "latin",
    "id": "latin",
    "ms": "latin",
    "sv": "latin",
    "da": "latin",
    "no": "latin",
    "fi": "latin",
    "hu": "latin",
    "ro": "latin",
}

#: Names the settings dialog stores, rather than tags.  MAGE writes the
#: language's English name into QSettings, not its ISO code.
_NAME_SCRIPTS: dict[str, str] = {
    "chinese": "cjk",
    "simplified chinese": "cjk",
    "traditional chinese": "cjk",
    "japanese": "cjk",
    "english": "cjk",
    "korean": "korean",
    "russian": "eslav",
    "ukrainian": "eslav",
    "belarusian": "eslav",
    "french": "latin",
    "german": "latin",
    "spanish": "latin",
    "italian": "latin",
    "portuguese": "latin",
    "dutch": "latin",
    "polish": "latin",
    "czech": "latin",
    "turkish": "latin",
    "vietnamese": "latin",
    "indonesian": "latin",
    "swedish": "latin",
    "romanian": "latin",
}


def recognizer_script_for(source_language: str | None) -> str:
    """Resolve a source-language setting to a recognizer script.

    Accepts what the settings actually hold — a tag like ``zh-CN`` or a name
    like ``Chinese`` — and falls back to the CJK recognizer for ``auto``, for
    an empty value, and for anything unknown.
    """
    if not source_language:
        return DEFAULT_SCRIPT

    value = source_language.strip().lower()
    if value in ("auto", "detect", "automatic"):
        return DEFAULT_SCRIPT

    if value in _NAME_SCRIPTS:
        return _NAME_SCRIPTS[value]

    tag = value.replace("_", "-").split("-")[0]
    return _LANGUAGE_SCRIPTS.get(tag, DEFAULT_SCRIPT)
