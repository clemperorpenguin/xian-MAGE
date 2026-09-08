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

"""Choosing between the classic surface layer and the new one.

The contract the whole feature rests on: turning the new UI *off* has to leave
the classic one exactly as it was.
"""

import os
import sys

import pytest
from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QApplication, QWidget

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from mage.capture.hotkeys import _CommandModeCore  # noqa: E402
from mage.settings_keys import KEY_NEW_UI  # noqa: E402
from mage.ui.shell import ClassicShell, NewShell, install_shell  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def q_app():
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


class FakeListener:
    def __init__(self):
        self.command_mode_enabled = True

    def set_command_mode_enabled(self, enabled):
        self.command_mode_enabled = enabled


class FakeApp(QWidget):
    """Only what a shell is allowed to touch."""

    def __init__(self, new_ui: bool):
        super().__init__()
        self.settings = QSettings("XianProject", "MageShellTest")
        self.settings.clear()
        self.settings.setValue(KEY_NEW_UI, "true" if new_ui else "false")
        self.hotkey_listener = FakeListener()
        self.processor = object()
        self.opened_settings = 0
        self.toggled_notes = 0

    def _open_settings(self):
        self.opened_settings += 1

    def toggle_notes(self):
        self.toggled_notes += 1


@pytest.fixture
def classic_app():
    app = FakeApp(new_ui=False)
    yield app
    app.settings.clear()


@pytest.fixture
def new_app():
    app = FakeApp(new_ui=True)
    yield app
    app.settings.clear()


# ── which shell ──────────────────────────────────────────────────────

def test_the_setting_off_gives_the_classic_shell(classic_app):
    assert isinstance(install_shell(classic_app), ClassicShell)


def test_the_setting_on_gives_the_new_shell(new_app):
    shell = install_shell(new_app)
    try:
        assert isinstance(shell, NewShell)
    finally:
        shell.teardown()


def test_a_broken_new_shell_falls_back_to_the_classic_one(new_app, monkeypatch):
    """A user who cannot start is a user who cannot switch the setting back."""
    import mage.ui.new.boxes as boxes

    def explode(*args, **kwargs):
        raise RuntimeError("no")

    monkeypatch.setattr(boxes, "BoxManager", explode)

    assert isinstance(install_shell(new_app), ClassicShell)


# ── the hotkeys ──────────────────────────────────────────────────────

def test_the_classic_shell_leaves_command_mode_armed(classic_app):
    install_shell(classic_app)

    assert classic_app.hotkey_listener.command_mode_enabled is True


def test_the_new_shell_disarms_command_mode(new_app):
    """No more hotkey soup: every command is a click."""
    shell = install_shell(new_app)
    try:
        assert new_app.hotkey_listener.command_mode_enabled is False
    finally:
        shell.teardown()


def test_a_disarmed_leader_does_nothing():
    core = _CommandModeCore()
    core.command_mode_enabled = False

    for now in (1.0, 1.2):
        signal = core.on_key_press(
            "device", now=now, is_modifier=True, is_leader=True,
            is_overlay_toggle=False, is_escape=False, is_grave=False,
        )

    assert signal is None
    assert core.command_mode_active is False


def test_the_overlay_toggle_survives_a_disarmed_command_mode():
    """The one gesture the new UI keeps: hide everything when a fullscreen
    game has the pointer and there is nothing left to click."""
    core = _CommandModeCore()
    core.command_mode_enabled = False

    core.on_key_press(
        "device", now=1.0, is_modifier=True, is_leader=False,
        is_overlay_toggle=True, is_escape=False, is_grave=False,
    )
    signal = core.on_key_press(
        "device", now=1.2, is_modifier=True, is_leader=False,
        is_overlay_toggle=True, is_escape=False, is_grave=False,
    )

    assert signal == "toggle_overlays"


def test_an_armed_leader_still_opens_command_mode():
    """The classic path must be untouched by the flag existing."""
    core = _CommandModeCore()

    core.on_key_press(
        "device", now=1.0, is_modifier=True, is_leader=True,
        is_overlay_toggle=False, is_escape=False, is_grave=False,
    )
    signal = core.on_key_press(
        "device", now=1.2, is_modifier=True, is_leader=True,
        is_overlay_toggle=False, is_escape=False, is_grave=False,
    )

    assert signal == "command_mode_started"


# ── what the shell exposes ───────────────────────────────────────────

def test_the_classic_shell_excludes_nothing(classic_app):
    """It has no gesture for exclusions, so the live worker must get none."""
    assert install_shell(classic_app).exclude_regions() == []


def test_the_panel_buttons_reach_the_app(new_app):
    shell = install_shell(new_app)
    try:
        shell.panel.settings_requested.emit()
        shell.panel.notes_requested.emit()
    finally:
        shell.teardown()

    assert new_app.opened_settings == 1
    assert new_app.toggled_notes == 1
