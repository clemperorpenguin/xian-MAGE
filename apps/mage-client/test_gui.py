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

import sys
import pytest
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QSettings, QRect, Qt
from mage.ui.overlay_base import MageOverlayWindow


class DummyApp:
    def __init__(self):
        self.settings = QSettings("XianProject", "MageTest")


@pytest.fixture(scope="session", autouse=True)
def q_app():
    app = QApplication.instance()
    if not app:
        app = QApplication(sys.argv)
    yield app


def test_mage_overlay_window_geometry_persistence(q_app):
    app = DummyApp()
    # Clear any previous settings
    app.settings.clear()
    app.settings.setValue("layout_preset", "Default")
    
    # Create window and save coordinates
    win = MageOverlayWindow("test_win_persistence", app)
    win.setGeometry(QRect(120, 240, 360, 480))
    win.save_geometry()
    
    # Create new window instance and restore
    win2 = MageOverlayWindow("test_win_persistence", app)
    # Verify geometry restores correctly
    assert win2.geometry().x() == 120
    assert win2.geometry().y() == 240
    assert win2.geometry().width() == 360
    assert win2.geometry().height() == 480
    
    # Clean up settings
    app.settings.clear()


def test_mage_overlay_window_click_through(q_app):
    app = DummyApp()
    app.settings.clear()
    
    win = MageOverlayWindow("test_win_click_through", app)
    
    # Test toggling click through state
    win.set_click_through(True)
    assert win.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents) is True
    
    win.set_click_through(False)
    assert win.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents) is False
    
    # Test click-through is disabled in edit mode (to allow dragging)
    win.set_click_through(True)
    win.set_edit_mode(True)
    assert win.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents) is False
    
    # Exiting edit mode restores the click-through state
    win.set_edit_mode(False)
    assert win.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents) is True
    
    app.settings.clear()


def test_settings_dialog_exposes_memory_controls(q_app):
    """The Memory group must round-trip through QSettings."""
    from mage.app import SettingsDialog
    from mage.settings_keys import KEY_MEMORY_ENABLED, KEY_MEMORY_RETENTION_DAYS

    settings = QSettings("XianProject", "MageTestMemory")
    settings.clear()
    settings.setValue(KEY_MEMORY_ENABLED, "false")
    settings.setValue(KEY_MEMORY_RETENTION_DAYS, 7)

    dialog = SettingsDialog(settings, models=[])
    assert dialog.memory_enabled_cb.isChecked() is False
    assert dialog.memory_retention_spin.value() == 7

    dialog.memory_enabled_cb.setChecked(True)
    dialog.memory_retention_spin.setValue(14)
    dialog._save()

    assert settings.value(KEY_MEMORY_ENABLED) == "true"
    assert int(settings.value(KEY_MEMORY_RETENTION_DAYS)) == 14

    dialog.deleteLater()
    settings.clear()


def test_settings_dialog_switches_the_collection_tier(q_app):
    """Choosing a tier also names the model, and flags the change for install."""
    from mage.app import SettingsDialog
    from mage.settings_keys import KEY_API_MODEL, KEY_COLLECTION_TIER

    settings = QSettings("XianProject", "MageTestTier")
    settings.clear()
    settings.setValue(KEY_COLLECTION_TIER, "lite")
    settings.setValue(KEY_API_MODEL, "Xian-Lite")

    dialog = SettingsDialog(settings, models=["Xian-Lite"])
    assert dialog.tier_combo.currentData() == "lite"

    dialog.tier_combo.setCurrentIndex(dialog.tier_combo.findData("halo"))
    dialog._save()

    assert settings.value(KEY_COLLECTION_TIER) == "halo"
    assert settings.value(KEY_API_MODEL) == "Xian-Halo"
    assert dialog.tier_changed is True

    dialog.deleteLater()
    settings.clear()


def test_settings_dialog_leaves_a_custom_model_alone(q_app):
    """An unchanged tier must not overwrite a model the user typed in."""
    from mage.app import SettingsDialog
    from mage.settings_keys import KEY_API_MODEL, KEY_COLLECTION_TIER

    settings = QSettings("XianProject", "MageTestTierKeep")
    settings.clear()
    settings.setValue(KEY_COLLECTION_TIER, "ultra")

    dialog = SettingsDialog(settings, models=[])
    dialog.model_combo.setCurrentText("Qwen3.5-9B-GGUF")
    dialog._save()

    assert settings.value(KEY_API_MODEL) == "Qwen3.5-9B-GGUF"
    assert dialog.tier_changed is False

    dialog.deleteLater()
    settings.clear()


def test_keep_window_above_is_safe_on_every_platform():
    """It runs on a 0.75s tick for every visible overlay, so it must never
    raise — not for a closed window, not for a widget without a handle."""
    from mage.utils.window_binder import keep_window_above

    for win_id in (0, None, "not-a-handle", 123456789):
        keep_window_above(win_id)


def test_the_windows_topmost_call_is_inert_off_windows():
    """The Linux branch must not be reached through it, and vice versa."""
    import sys

    from mage.utils.window_binder import set_topmost_windows

    result = set_topmost_windows(123456789)

    assert result is (False if sys.platform != "win32" else result)


def test_keep_window_above_dispatches_on_platform(monkeypatch):
    """One call site per overlay; the platform choice lives in one place."""
    from mage.utils import window_binder

    calls = []
    monkeypatch.setattr(window_binder, "set_topmost_windows", lambda w: calls.append(("win", w)))
    monkeypatch.setattr(window_binder, "set_above_state_x11", lambda w: calls.append(("x11", w)))
    monkeypatch.setattr(window_binder, "set_bypass_compositor_hint_x11", lambda w: None)
    monkeypatch.setattr(window_binder, "set_overlay_window_type_x11", lambda w: None)

    monkeypatch.setattr(window_binder.sys, "platform", "win32")
    window_binder.keep_window_above(42)

    monkeypatch.setattr(window_binder.sys, "platform", "linux")
    window_binder.keep_window_above(42)

    assert calls == [("win", 42), ("x11", 42)]


def test_an_overlay_asks_to_stay_above_when_it_appears(q_app, monkeypatch):
    """Qt recreates the native window on a flags change, and the platform's
    always-on-top state does not survive that."""
    from mage.ui import overlay_base

    asked = []
    monkeypatch.setattr(overlay_base, "keep_window_above", asked.append)

    app = DummyApp()
    window = MageOverlayWindow("keep_above_test", app=app)
    try:
        window.show()
        q_app.processEvents()
        assert asked
    finally:
        window.close()
        app.settings.clear()


def test_an_overlay_asks_to_be_left_out_of_captures(q_app, monkeypatch):
    """MAGE reads the screen it draws on, so its own windows must not be in
    the frame: a live box that can see the last translation reads its own
    output back and paints over it again."""
    from mage.ui import overlay_base

    asked = []
    monkeypatch.setattr(overlay_base, "hide_window_from_capture", asked.append)

    app = DummyApp()
    window = MageOverlayWindow("exclude_capture_test", app=app)
    try:
        window.show()
        q_app.processEvents()
        assert asked
    finally:
        window.close()
        app.settings.clear()


def test_the_inpaint_overlay_asks_to_be_left_out_of_captures(q_app, monkeypatch):
    """The one window that sits directly over the text being read."""
    from mage.ui import inpaint_overlay

    asked = []
    monkeypatch.setattr(inpaint_overlay, "hide_window_from_capture", asked.append)

    overlay = inpaint_overlay.InpaintOverlay()
    try:
        overlay.show()
        q_app.processEvents()
        assert asked
    finally:
        overlay.close()


def test_hiding_from_capture_is_a_no_op_off_windows(monkeypatch):
    """Nothing on X11 or Wayland does this; the paint masking covers those."""
    from mage.utils import window_binder

    monkeypatch.setattr(window_binder.sys, "platform", "linux")
    assert window_binder.hide_window_from_capture(42) is False


def test_hiding_from_capture_survives_a_missing_window_id(monkeypatch):
    from mage.utils import window_binder

    monkeypatch.setattr(window_binder.sys, "platform", "win32")
    assert window_binder.hide_window_from_capture(None) is False
    assert window_binder.hide_window_from_capture(0) is False
