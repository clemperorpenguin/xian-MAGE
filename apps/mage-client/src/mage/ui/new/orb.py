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

"""The orb: the familiar, doing the job the hotkeys used to do.

The orb and the familiar were two creatures for the same screen, so they are
one now.  The familiar already had a body, five species, a conjure system that
authors new ones, a speech bubble, and — the part that made the merge obvious —
a state for *a translation is running*, one for *it finished* and one for *it
failed*.  All the orb ever added on top of that was a status colour and a
click.

So the orb is a :class:`~mage.ui.familiar_pet.FamiliarPet` with three things
bolted on:

* **A click opens the panel** — the log, the chat and the microphone — where
  the familiar used to open the chat sidebar.
* **A double-click listens.**  While it does, the orb wears a ring, because a
  microphone that is on and does not look on is how people talk to a machine
  that is not listening.
* **Working states map onto the familiar's own.**  Reading and translating are
  ``CAST``, a failure is ``SAD``.  Nothing new had to be invented for it.

Right-click still opens the familiar's menu, so species and Conjure… are where
they always were.

The panel's log is a *view* over what ``record_event`` already writes, not a
second store.  That is what lets the chat answer questions about lines that are
already in its scroll-back.  Box translations go to the log and are painted in
place by the overlay; the speech bubble is kept for the things that have no box
of their own — what the orb heard, and what it says back.
"""

from __future__ import annotations

import html
import logging
import time

from PyQt6.QtCore import QPoint, QRect, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from mage.ui.familiar_pet import FamiliarPet, FamiliarState
from mage.ui.overlay_base import MageOverlayWindow
from shared_types.state import t

logger = logging.getLogger(__name__)

__all__ = ["Orb", "OrbPanel", "OrbState"]


class OrbState:
    """What the orb is doing.  Mostly an alias for how the familiar feels."""

    IDLE = "idle"
    LISTENING = "listening"
    READING = "reading"
    TRANSLATING = "translating"
    SPEAKING = "speaking"


#: Orb states that mean "working".  The familiar already holds a casting pose
#: for exactly this, with its own timing, so the orb asks for that rather than
#: setting a mood behind its back.
_BUSY_STATES = frozenset({OrbState.READING, OrbState.TRANSLATING})

#: Ring colour while listening.  Not the species accent: this says something
#: about the microphone, not about the creature wearing it.
_LISTENING_RING = QColor(120, 210, 140)

#: How fast the listening ring breathes, in radians per behaviour tick.
_RING_SPEED = 0.12


class Orb(FamiliarPet):
    """The familiar, wired to the panel instead of to the chat sidebar."""

    clicked = pyqtSignal()
    mic_toggled = pyqtSignal(bool)

    def __init__(self, app=None, parent=None, species=None):
        super().__init__(app=app, parent=parent, species=species)
        self.state = OrbState.IDLE
        self.mic_active = False
        self._ring_phase = 0.0

    # ── status ───────────────────────────────────────────────────────

    def set_state(self, state: str) -> None:
        """Say what the orb is doing, in the familiar's own vocabulary."""
        self.state = state
        if state in _BUSY_STATES:
            # on_thinking, not _set_state: it also calls the familiar home from
            # wherever it has wandered and holds the pose for a minimum time,
            # so a fast translation still reads as one rather than flickering.
            self.on_thinking()
        elif state == OrbState.IDLE and self._state is FamiliarState.CAST:
            self._set_state(FamiliarState.IDLE)
        self.update()

    def set_failed(self, message: str = "") -> None:
        """Something the user asked for did not work, and should look like it."""
        self.state = OrbState.IDLE
        self.on_error(message)

    def speak(self, text: str, original: str = "") -> None:
        """Put something in the familiar's speech bubble.

        For what has no box of its own: what the orb heard, and what it says
        back.  Box translations are painted in place, and a bubble repeating
        every recognized line would cover the game.
        """
        self.state = OrbState.SPEAKING
        self.on_result(text, original=original, with_bubble=True)

    def set_mic_active(self, active: bool) -> None:
        self.mic_active = active
        self.set_state(OrbState.LISTENING if active else OrbState.IDLE)

    # ── input ────────────────────────────────────────────────────────

    def mouseReleaseEvent(self, event):
        """A click opens the panel; a drag just moves the familiar.

        The base class discriminates the two and then opens the chat sidebar,
        which under the new UI is a surface that no longer exists.
        """
        if event.button() == Qt.MouseButton.LeftButton and not self._dragging_user:
            self.clicked.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return super().mouseDoubleClickEvent(event)
        self.set_mic_active(not self.mic_active)
        self.mic_toggled.emit(self.mic_active)
        event.accept()

    # ── painting ─────────────────────────────────────────────────────

    def _on_behaviour_tick(self):
        super()._on_behaviour_tick()
        if self.mic_active:
            self._ring_phase += _RING_SPEED

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self.mic_active:
            return

        # Drawn after the familiar so it reads as something the creature is
        # wearing rather than part of it.
        import math

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        swell = (math.sin(self._ring_phase) + 1.0) / 2.0
        ring = QColor(_LISTENING_RING)
        ring.setAlpha(int(90 + 110 * swell))
        painter.setPen(QPen(ring, 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        radius = int(self.width() * 0.30 + swell * 5)
        painter.drawEllipse(self.rect().center(), radius, radius)
        painter.end()


class OrbPanel(MageOverlayWindow):
    """The log, the chat box and the controls — one panel, three faces."""

    message_sent = pyqtSignal(str)
    mic_toggled = pyqtSignal(bool)
    add_box_requested = pyqtSignal()
    translate_once_requested = pyqtSignal()
    settings_requested = pyqtSignal()
    notes_requested = pyqtSignal()
    box_mode_cycled = pyqtSignal(str)
    box_removed = pyqtSignal(str)
    boxes_cleared = pyqtSignal()

    #: Entries kept in the view. The session store keeps the real history;
    #: this is a window onto the recent end of it.
    MAX_ENTRIES = 200

    def __init__(self, app=None, parent=None):
        super().__init__("orb_panel", app=app, parent=parent)
        self.setMinimumSize(QSize(360, 320))
        self.resize(400, 420)
        self._entries: list[str] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        header = QHBoxLayout()
        self._title = QLabel(t("newui.orb.title"))
        self._title.setStyleSheet("font-weight: bold; color: #ddd;")
        header.addWidget(self._title, 1)

        self._once_button = QPushButton(t("newui.orb.button.translate_once"))
        self._once_button.setToolTip(t("newui.orb.tooltip.translate_once"))
        self._once_button.clicked.connect(self.translate_once_requested)
        self._add_box_button = QPushButton(t("newui.orb.button.add_box"))
        self._add_box_button.clicked.connect(self.add_box_requested)
        self._notes_button = QPushButton(t("newui.orb.button.notes"))
        self._notes_button.clicked.connect(self.notes_requested)
        self._settings_button = QPushButton(t("newui.orb.button.settings"))
        self._settings_button.clicked.connect(self.settings_requested)
        for button in (self._once_button, self._add_box_button, self._notes_button, self._settings_button):
            header.addWidget(button)
        layout.addLayout(header)

        # Every box on screen, reachable without touching it.  A box is a
        # frame around a piece of the game and mostly a hole, so its own
        # controls only appear when the pointer finds that frame — which is
        # not a thing to depend on when the alternative is a box that cannot
        # be changed or deleted at all.
        self._boxes_row = QHBoxLayout()
        self._boxes_row.setSpacing(4)
        self._boxes_label = QLabel(t("newui.orb.label.boxes"))
        self._boxes_label.setStyleSheet("color: #8a8a9e; font-size: 11px;")
        self._boxes_row.addWidget(self._boxes_label)
        self._boxes_row.addStretch(1)
        self._clear_boxes_button = QPushButton(t("newui.orb.button.clear_boxes"))
        self._clear_boxes_button.setToolTip(t("newui.orb.tooltip.clear_boxes"))
        self._clear_boxes_button.clicked.connect(self.boxes_cleared)
        self._boxes_row.addWidget(self._clear_boxes_button)
        self._box_widgets: list[QWidget] = []
        layout.addLayout(self._boxes_row)

        self._log = QTextBrowser()
        self._log.setOpenExternalLinks(False)
        layout.addWidget(self._log, 1)

        row = QHBoxLayout()
        self._mic_button = QPushButton(t("newui.orb.button.mic"))
        self._mic_button.setCheckable(True)
        self._mic_button.toggled.connect(self.mic_toggled)
        row.addWidget(self._mic_button)

        self._input = QLineEdit()
        self._input.setPlaceholderText(t("newui.orb.input.placeholder"))
        self._input.returnPressed.connect(self._send)
        row.addWidget(self._input, 1)

        self._send_button = QPushButton(t("newui.orb.button.send"))
        self._send_button.clicked.connect(self._send)
        row.addWidget(self._send_button)
        layout.addLayout(row)

        self.setStyleSheet(
            "QWidget { background: rgba(18,18,26,235); color: #e6e6e6; border-radius: 10px; }"
            "QTextBrowser, QLineEdit { background: rgba(10,10,16,220); border: 1px solid #3a3a4a;"
            " border-radius: 6px; padding: 4px; }"
            "QPushButton { background: rgba(40,40,58,230); border: 1px solid #4a4a5e;"
            " border-radius: 6px; padding: 4px 10px; }"
            "QPushButton:hover { background: rgba(60,60,86,240); }"
            "QPushButton:checked { background: rgba(60,140,90,240); }"
        )

    # ── the boxes ────────────────────────────────────────────────────

    def set_boxes(self, entries: list[tuple[str, str, str]]) -> None:
        """Rebuild the row from ``(box_id, label, mode)`` triples.

        Rebuilt wholesale rather than diffed: there are at most five of them,
        and a row that is regenerated cannot drift out of step with the boxes
        it describes.
        """
        for widget in self._box_widgets:
            self._boxes_row.removeWidget(widget)
            widget.deleteLater()
        self._box_widgets = []

        self._boxes_label.setText(
            t("newui.orb.label.boxes") if entries else t("newui.orb.label.no_boxes")
        )
        self._clear_boxes_button.setEnabled(bool(entries))

        # Inserted before the stretch and the clear button, so they stay right.
        position = 1
        for box_id, label, mode in entries:
            chip = QPushButton(f"{label} · {mode}")
            chip.setToolTip(t("newui.orb.tooltip.cycle_mode"))
            chip.clicked.connect(lambda _checked=False, i=box_id: self.box_mode_cycled.emit(i))
            remove = QPushButton("✕")
            remove.setFixedWidth(22)
            remove.setToolTip(t("newui.orb.tooltip.remove_box"))
            remove.clicked.connect(lambda _checked=False, i=box_id: self.box_removed.emit(i))
            for widget in (chip, remove):
                self._boxes_row.insertWidget(position, widget)
                self._box_widgets.append(widget)
                position += 1

    # ── the log ──────────────────────────────────────────────────────

    def _append(self, body: str) -> None:
        self._entries.append(body)
        if len(self._entries) > self.MAX_ENTRIES:
            self._entries = self._entries[-self.MAX_ENTRIES :]
        self._log.setHtml("".join(self._entries))
        self._log.verticalScrollBar().setValue(self._log.verticalScrollBar().maximum())

    def add_translation(self, original: str, translated: str, *, kind: str = "screen") -> None:
        """One entry per translated line, whether it was read or heard."""
        stamp = time.strftime("%H:%M:%S")
        marker = "🎙" if kind == "voice" else "▣"
        self._append(
            f'<div style="margin-bottom:6px">'
            f'<span style="color:#7a7a90;font-size:10px">{marker} {stamp}</span><br>'
            f'<span style="color:#9aa0b5">{html.escape(original)}</span><br>'
            f'<span style="color:#e8e8f0">{html.escape(translated)}</span></div>'
        )

    def add_message(self, sender: str, text: str) -> None:
        color = "#7fd4ff" if sender == "you" else "#c9a7ff"
        self._append(
            f'<div style="margin-bottom:6px"><span style="color:{color};font-weight:bold">'
            f"{html.escape(sender)}:</span> {html.escape(text)}</div>"
        )

    def set_mic_active(self, active: bool) -> None:
        if self._mic_button.isChecked() != active:
            self._mic_button.blockSignals(True)
            self._mic_button.setChecked(active)
            self._mic_button.blockSignals(False)

    def set_status(self, key: str) -> None:
        self._title.setText(t(key) if key else t("newui.orb.title"))

    def _send(self) -> None:
        text = self._input.text().strip()
        if not text:
            return
        self._input.clear()
        self.add_message("you", text)
        self.message_sent.emit(text)

    def show_near(self, orb: QWidget) -> None:
        """Open beside the orb, nudged back on screen if it would hang off."""
        geometry = orb.geometry()
        target = QRect(geometry.right() + 8, geometry.top(), self.width(), self.height())
        screen = self.screen() or orb.screen()
        if screen is not None:
            available = screen.availableGeometry()
            if target.right() > available.right():
                target.moveLeft(geometry.left() - self.width() - 8)
            if target.bottom() > available.bottom():
                target.moveTop(available.bottom() - self.height())
            if target.top() < available.top():
                target.moveTop(available.top())
            if target.left() < available.left():
                target.moveLeft(available.left())
        self.move(QPoint(target.left(), target.top()))
        self.show()
        self.raise_()
