# MAGE — Gaming HUD for real-time screen translation.
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

"""Canonical QSettings keys for the Mage client, and how to read them.

Centralizes key names to avoid typos and drift across files.  The few readers
that live here too are the ones whose *interpretation* has to be shared — a
boolean QSettings stores as a string on one platform and a bool on another, a
URL that has to be normalised the same way everywhere.
"""

from shared_types import constants


def normalized_api_url_from_settings(settings) -> str:
    """The Lemonade base URL as stored, put in canonical form.

    Beside the keys rather than beside its callers because there are five of
    them, in three modules, and a URL normalised on the way in but not on the
    way out is a health check that passes against a server the requests never
    reach.
    """
    from xian.lemonade_url import normalize_lemonade_api_base_url

    return normalize_lemonade_api_base_url(str(settings.value(KEY_API_URL, constants.DEFAULT_API_URL)))


def parse_styles(settings) -> list[str]:
    """The saved translation styles as a list.

    QSettings hands back a list on one platform and a comma-joined string on
    another; every reader has to accept both.
    """
    raw = settings.value(KEY_STYLES, constants.DEFAULT_STYLES)
    if isinstance(raw, str):
        return [style.strip() for style in raw.split(",") if style.strip()]
    return raw if isinstance(raw, list) else []


def is_true(value) -> bool:
    """Read a QSettings boolean.

    QSettings round-trips booleans as the strings "true"/"false" on some
    platforms and as real bools on others, so every read has to accept both.
    """
    return value is True or value == "true"

KEY_API_URL = "api_url"
KEY_API_MODEL = "api_model"
KEY_SOURCE_LANG = "source_lang"
KEY_TARGET_LANG = "target_lang"
KEY_MODE = "mode"
KEY_STYLES = "styles"
KEY_MAX_TOKENS = "max_tokens"
KEY_LEADER_KEY = "leader_key"
KEY_OVERLAY_TOGGLE_KEY = "overlay_toggle_key"
KEY_GPU_UTIL = "gpu_memory_utilization"
KEY_DIALOGUE_DELAY = "dialogue_delay"
KEY_AUTO_CONTINUE = "auto_continue"
KEY_AUTO_SPEAK = "auto_speak"
KEY_TARGET_WINDOW_TITLE = "target_window_title"
KEY_UI_LANG = "ui_lang"
KEY_FAMILIAR_ENABLED = "familiar_enabled"
KEY_FAMILIAR_TTS = "familiar_tts"
KEY_FAMILIAR_TYPE = "familiar_type"
KEY_FAMILIAR_CUSTOM_RECIPE = "familiar_custom_recipe"
KEY_MEMORY_ENABLED = "memory_enabled"
KEY_MEMORY_RETENTION_DAYS = "memory_retention_days"
KEY_BACKEND_PREFERENCE = "backend_preference"
KEY_NPU_POWER_MODE = "npu_power_mode"
KEY_LIVE_INTERVAL_MS = "live_interval_ms"
KEY_COLLECTION_TIER = "collection_tier"

# Continuous in-place translation. Off by default: it is the newer of the
# two architectures and still experimental.
KEY_EXPERIMENTAL_LIVE = "experimental_live_mode"

# Which engine drives live mode.
#
# "grounding" is one vision call that detects, reads and translates together —
# no local models, ~1s per changed frame.  "ocr" reads locally with PP-OCRv5
# and sends only text, which is slower per frame but calls the network on a
# fraction of the ticks, because it can tell whether the *text* changed rather
# than only whether the pixels did.
KEY_LIVE_ENGINE = "live_engine"
LIVE_ENGINE_GROUNDING = "grounding"
LIVE_ENGINE_OCR = "ocr"
#: The local reader, which is what the translation boxes were built around and
#: what they have always run whatever this said.  It falls back to the vision
#: model on a machine whose weights are not exported — see
#: :mod:`mage.live_engine` — so this default costs an unprepared machine
#: nothing.
DEFAULT_LIVE_ENGINE = LIVE_ENGINE_OCR

# Detection model for the OCR engine: PP-OCRv5_mobile_det or _server_det.
KEY_OCR_DETECTOR = "ocr_detector"

# Which Hy-MT2 to translate text with.  Every text translation in the app uses
# one of the two; the prompts are Hy-MT2's own published formats and nothing
# else is offered, because running them against another model produces quality
# problems that read as OCR problems.
KEY_TRANSLATION_MODEL = "translation_model"

# Newline-separated phrases stripped before the change gate sees a frame.
# Each may be prefixed "regex:" or "exact:"; anything else is a substring.
KEY_IGNORE_PHRASES = "ignore_phrases"

