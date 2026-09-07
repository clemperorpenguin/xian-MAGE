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

"""Canonical QSettings keys for the Mage client.

Centralizes key names to avoid typos and drift across files.
"""


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
DEFAULT_LIVE_ENGINE = LIVE_ENGINE_GROUNDING

# Detection model for the OCR engine: PP-OCRv5_mobile_det or _server_det.
KEY_OCR_DETECTOR = "ocr_detector"

# Newline-separated phrases stripped before the change gate sees a frame.
# Each may be prefixed "regex:" or "exact:"; anything else is a substring.
KEY_IGNORE_PHRASES = "ignore_phrases"

# The new UI: translation boxes and the orb, instead of the tray, the command
# OSD and the leader-key hotkeys.  Off by default; the classic shell is
# untouched by it.
KEY_NEW_UI = "new_ui"
