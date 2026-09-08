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

"""Installing the interface.

There used to be two surface layers and a setting to choose between them.
There is one now, so what these check is that it comes up, that the leader key
and its letter menu do not, and that the one gesture with no clickable
substitute still does.
"""

import os
import sys

import pytest
from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QApplication, QWidget

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from mage.capture.hotkeys import _CommandModeCore  # noqa: E402
from mage.ui.shell import NewShell, Shell, install_shell  # noqa: E402


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

    def __init__(self):
        super().__init__()
        self.settings = QSettings("XianProject", "MageShellTest")
        self.settings.clear()
        self.hotkey_listener = FakeListener()
        self.processor = object()
        self.opened_settings = 0
        self.toggled_notes = 0

    def _open_settings(self):
        self.opened_settings += 1

    def toggle_notes(self):
        self.toggled_notes += 1


@pytest.fixture
def new_app():
    app = FakeApp()
    yield app
    app.settings.clear()


# ── installing ───────────────────────────────────────────────────────

def test_the_interface_comes_up(new_app):
    shell = install_shell(new_app)
    try:
        assert isinstance(shell, NewShell)
    finally:
        shell.teardown()


def test_a_broken_interface_does_not_take_the_app_down(new_app, monkeypatch):
    """A bare shell answers the questions the app asks of it and nothing
    else — a poor experience, but a running one."""
    import mage.ui.new.boxes as boxes

    def explode(*args, **kwargs):
        raise RuntimeError("no")

    monkeypatch.setattr(boxes, "BoxManager", explode)

    shell = install_shell(new_app)

    assert type(shell) is Shell
    assert shell.exclude_regions() == []


# ── the hotkeys ──────────────────────────────────────────────────────

def test_the_shell_disarms_command_mode(new_app):
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

def test_the_panel_buttons_reach_the_app(new_app):
    shell = install_shell(new_app)
    try:
        shell.panel.settings_requested.emit()
        shell.panel.notes_requested.emit()
    finally:
        shell.teardown()

    assert new_app.opened_settings == 1
    assert new_app.toggled_notes == 1
