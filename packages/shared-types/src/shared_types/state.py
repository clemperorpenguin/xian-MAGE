# Xian-VL Shared Types — Canonical model definitions and constants.
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

import json
import logging
import sys
import threading
from pathlib import Path
from typing import Dict, Any

logger = logging.getLogger(__name__)

class RuntimeState:
    """Shared runtime state holding the JSON-backed translation manager."""
    
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(RuntimeState, cls).__new__(cls)
                cls._instance._init_state()
            return cls._instance

    def _init_state(self):
        self.ui_language: str = "en"
        self._locale_data: Dict[str, Any] = {}
        # en.json is the reference dictionary every other locale is generated
        # from, so it is always at least as complete as the active one.  Held
        # separately as the fallback, because a key added since the last
        # `localize.cli` run would otherwise render as its own identifier —
        # a button reading "newui.orb.button.send".
        self._fallback_data: Dict[str, Any] = {}
        # Locate the locales directory — path differs between dev and frozen builds
        if getattr(sys, 'frozen', False):
            # PyInstaller bundles locales into _MEIPASS/locales via --add-data
            base = Path(getattr(sys, '_MEIPASS', Path(sys.executable).parent))
            self.locales_dir = base / "locales"
        else:
            # Dev mode: __file__ is .../packages/shared-types/src/shared_types/state.py
            current_dir = Path(__file__).resolve().parent
            self.locales_dir = current_dir.parent.parent / "locales"
        self._fallback_data = self._read_locale("en")
        self.load_locale(self.ui_language)

    def _read_locale(self, lang: str) -> Dict[str, Any]:
        """Read one locale file, or an empty dict if it cannot be read."""
        locale_path = self.locales_dir / f"{lang}.json"
        if not locale_path.exists():
            logger.warning("Locale file not found: %s", locale_path)
            return {}
        try:
            with open(locale_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error("Failed to load locale %s: %s", lang, e)
            return {}

    def load_locale(self, lang: str):
        """Load JSON strings for a given language."""
        self.ui_language = lang
        self._locale_data = self._read_locale(lang)
        if self._locale_data:
            logger.info("Loaded locale data for %s", lang)
        if not self._fallback_data:
            self._fallback_data = self._read_locale("en")

    @staticmethod
    def _string_for(data: Dict[str, Any], key: str) -> str | None:
        """Pull one string out of a locale dictionary, whatever its shape."""
        val = data.get(key)
        # en.json carries {"value": ..., "context": ...} so the translator has
        # something to work from; generated locales are flat key to string.
        if isinstance(val, dict) and "value" in val:
            val = val.get("value")
        return val if isinstance(val, str) and val else None

    def t(self, key: str) -> str:
        """Translate a given key, falling back to English, then to the key."""
        resolved = self._string_for(self._locale_data, key)
        if resolved is not None:
            return resolved

        # Untranslated is not ideal; showing the user a dotted identifier is
        # worse, and that is what happens to every string added between one
        # `localize.cli` run and the next.
        resolved = self._string_for(self._fallback_data, key)
        return resolved if resolved is not None else key

# Global instance for easy access
state = RuntimeState()

def t(key: str) -> str:
    """Global translation helper function."""
    return state.t(key)
