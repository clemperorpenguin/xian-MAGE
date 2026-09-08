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

"""Which surface layer the app runs: the classic one, or the new one.

``XianApp.__init__`` builds the classic shell inline, as it always has — the
tray icon, the command OSD, the leader-key listener, the familiar.  This module
is called at the end of that, and either leaves it exactly as it is or stands
the new UI up in front of it, turning off the parts it supersedes.

Additive on purpose.  Extracting the classic wiring into a class of its own
would touch several hundred lines of a file that works, to no benefit: the
classic shell has to end up byte-identical in behaviour, and the surest way to
achieve that is not to move it.
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import QObject

from mage.settings_keys import KEY_NEW_UI, is_true

logger = logging.getLogger(__name__)

__all__ = ["ClassicShell", "NewShell", "install_shell"]


class Shell(QObject):
    """What the rest of the app is allowed to ask a shell for."""

    def exclude_regions(self) -> list:
        """Rectangles masked out of every live frame before it is read."""
        return []

    def on_translation(self, original: str, translated: str) -> None:
        """A line was translated somewhere; show it if this shell has a place."""

    def teardown(self) -> None:
        """Release anything the shell owns."""


class ClassicShell(Shell):
    """The tray, the OSD and the leader key — everything as it was.

    Deliberately empty: the wiring already happened in ``XianApp.__init__``.
    This exists so the app always has a shell object to ask, rather than
    checking a setting at every call site.
    """


class NewShell(Shell):
    """Translation boxes and the orb, instead of the hotkeys and the OSD."""

    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self._voice_worker = None
        self._chat_worker = None
        self._picker = None

        from mage.ui.new.boxes import BoxManager
        from mage.ui.new.orb import Orb, OrbPanel, OrbState

        self._OrbState = OrbState

        # Every command is a click now, so the leader double-tap and its
        # letters are not armed.  The overlay-toggle gesture is left alone: it
        # is the escape hatch when a fullscreen game holds the pointer, and
        # there is no clickable substitute for that.
        listener = getattr(app, "hotkey_listener", None)
        if listener is not None and hasattr(listener, "set_command_mode_enabled"):
            listener.set_command_mode_enabled(False)

        self.boxes = BoxManager(app, parent=self)
        self.orb = Orb(app=app)
        self.panel = OrbPanel(app=app)
        self.panel.hide()

        self.orb.clicked.connect(self._toggle_panel)
        self.orb.mic_toggled.connect(self.set_microphone)
        self.panel.mic_toggled.connect(self.set_microphone)
        self.panel.message_sent.connect(self._on_message)
        self.panel.add_box_requested.connect(self.add_box)
        self.panel.settings_requested.connect(app._open_settings)
        self.panel.notes_requested.connect(app.toggle_notes)

        self.boxes.load()
        self.boxes.start_all()
        self.orb.show()

    # ── boxes ────────────────────────────────────────────────────────

    def exclude_regions(self) -> list:
        return self.boxes.exclude_regions()

    def add_box(self) -> None:
        """Drag a rectangle on a dimmed screen; every one drawn becomes a box.

        Reuses the cinematic selector, which already collects a list of
        rectangles and confirms them — the gesture is right, only what happens
        afterwards is different.
        """
        from mage.ui.lens import CinematicLensOverlay

        if self._picker is not None:
            return
        self._picker = CinematicLensOverlay()
        self._picker.confirmed.connect(self._on_boxes_drawn)
        self._picker.closed.connect(self._on_picker_closed)
        self._picker.showFullScreen()

    def _on_boxes_drawn(self, rects) -> None:
        for rect in rects:
            self.boxes.add_box(rect)
        self._on_picker_closed()

    def _on_picker_closed(self) -> None:
        picker, self._picker = self._picker, None
        if picker is not None:
            picker.close()
            picker.deleteLater()

    # ── the log ──────────────────────────────────────────────────────

    def on_translation(self, original: str, translated: str) -> None:
        self.panel.add_translation(original, translated)

    # ── chat ─────────────────────────────────────────────────────────

    def _toggle_panel(self) -> None:
        if self.panel.isVisible():
            self.panel.hide()
        else:
            self.panel.show_near(self.orb)

    def _on_message(self, text: str) -> None:
        """Answer in the panel, through the same worker the sidebar uses."""
        from mage.settings_keys import KEY_SOURCE_LANG
        from mage.ui.chat_sidebar import ChatWorker
        from shared_types import constants

        if self._chat_worker is not None and self._chat_worker.isRunning():
            self.panel.add_message("mage", "…")
            return

        self.orb.set_state(self._OrbState.TRANSLATING)
        self._chat_worker = ChatWorker(
            self.app.processor,
            text,
            self.app.settings.value(KEY_SOURCE_LANG, constants.DEFAULT_SOURCE_LANG),
        )
        self._chat_worker.result_ready.connect(self._on_chat_result)
        self._chat_worker.start()

    def _on_chat_result(self, response: str) -> None:
        self.panel.add_message("mage", response)
        self.orb.set_state(self._OrbState.IDLE)

    # ── voice ────────────────────────────────────────────────────────

    def set_microphone(self, active: bool) -> None:
        self.orb.set_mic_active(active)
        self.panel.set_mic_active(active)
        if active:
            self._start_voice()
        else:
            self._stop_voice()

    def _start_voice(self) -> None:
        from mage.settings_keys import KEY_SOURCE_LANG, KEY_TARGET_LANG
        from mage.workers import OrbVoiceWorker
        from shared_types import constants

        if self._voice_worker is not None:
            return
        self._voice_worker = OrbVoiceWorker(
            self.app.processor,
            source_lang=self.app.settings.value(KEY_SOURCE_LANG, constants.DEFAULT_SOURCE_LANG),
            target_lang=self.app.settings.value(KEY_TARGET_LANG, constants.DEFAULT_TARGET_LANG),
        )
        self._voice_worker.utterance.connect(self._on_utterance)
        self._voice_worker.status.connect(self.panel.set_status)
        self._voice_worker.error.connect(self._on_voice_error)
        self._voice_worker.start()

    def _stop_voice(self) -> None:
        worker, self._voice_worker = self._voice_worker, None
        if worker is None:
            return
        worker.stop()
        # The recorder only notices between chunks, so a capture in flight can
        # outlive this; hand cleanup to finished() rather than dropping the
        # last reference to a running QThread.
        if not worker.wait(2000):
            worker.finished.connect(worker.deleteLater)
        self.panel.set_status("")

    def _on_utterance(self, transcript: str, translated: str) -> None:
        self.panel.add_translation(transcript, translated, kind="voice")

    def _on_voice_error(self, message: str) -> None:
        logger.error("orb voice error: %s", message)
        self.panel.add_message("mage", message)
        self.set_microphone(False)

    # ── teardown ─────────────────────────────────────────────────────

    def teardown(self) -> None:
        self._stop_voice()
        self.boxes.stop_all()
        self.boxes.save()
        for widget in (self.panel, self.orb):
            widget.close()
            widget.deleteLater()


def install_shell(app) -> Shell:
    """Return the shell the settings ask for, having wired it up.

    A failure here must not take the app down with it: the classic shell is
    always a working fallback, and a user who cannot start is a user who
    cannot switch the setting back.
    """
    if not is_true(app.settings.value(KEY_NEW_UI, "false")):
        return ClassicShell(app)

    try:
        return NewShell(app)
    except Exception as exc:
        logger.error("could not start the new UI; falling back to the classic one: %s", exc)
        return ClassicShell(app)
