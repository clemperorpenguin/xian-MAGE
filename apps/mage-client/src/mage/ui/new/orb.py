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

"""The orb: one object that is the log, the chat and the microphone.

Under the classic UI these are three surfaces reached by three chords after a
double-tap. Here they are three faces of one thing you can see and click, and
the orb's own appearance carries the status a HUD would otherwise need a row
of indicators for.

The log is a *view* over data the app already writes — every box translation
goes through ``processor.record_event`` regardless — not a second store. That
matters for the chat: the recent translations are already in the scroll-back,
so "what did that last line mean?" needs no attachment step.

A new widget rather than a new familiar species. The familiar is a classic-UI
feature with its own art, states and conjure system, and coupling this to
1500 lines of that would make each one harder to change. The new shell simply
does not construct a familiar, so only one creature is ever on screen.
"""

from __future__ import annotations

import html
import logging
import time

from PyQt6.QtCore import QPoint, QRect, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen, QRadialGradient
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from mage.ui.overlay_base import MageOverlayWindow
from shared_types.state import t

logger = logging.getLogger(__name__)

__all__ = ["Orb", "OrbPanel", "OrbState"]

ORB_SIZE = 56


class OrbState:
    IDLE = "idle"
    LISTENING = "listening"
    READING = "reading"
    TRANSLATING = "translating"
    SPEAKING = "speaking"


_STATE_COLORS = {
    OrbState.IDLE: QColor(120, 140, 190),
    OrbState.LISTENING: QColor(120, 210, 140),
    OrbState.READING: QColor(250, 200, 90),
    OrbState.TRANSLATING: QColor(190, 140, 250),
    OrbState.SPEAKING: QColor(250, 140, 170),
}


class Orb(MageOverlayWindow):
    """A small always-on-top circle. Click it; everything is behind it."""

    clicked = pyqtSignal()
    mic_toggled = pyqtSignal(bool)

    def __init__(self, app=None, parent=None):
        super().__init__("orb", app=app, parent=parent)
        self.setFixedSize(ORB_SIZE, ORB_SIZE)
        self.state = OrbState.IDLE
        self.mic_active = False
        self._pulse = 0.0
        self._dragged = False

        # One timer for every animation the orb has; it only runs while there
        # is something to animate, so an idle orb costs nothing.
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(t("newui.orb.tooltip"))

    def set_state(self, state: str) -> None:
        self.state = state
        if state == OrbState.IDLE and not self.mic_active:
            self._timer.stop()
            self._pulse = 0.0
        elif not self._timer.isActive():
            self._timer.start(60)
        self.update()

    def set_mic_active(self, active: bool) -> None:
        self.mic_active = active
        self.set_state(OrbState.LISTENING if active else OrbState.IDLE)

    def _tick(self) -> None:
        self._pulse = (self._pulse + 0.08) % 1.0
        self.update()

    # ── input ────────────────────────────────────────────────────────

    def mousePressEvent(self, event):
        self._dragged = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        self._dragged = True
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        # A click that moved the orb was a drag, and opening the panel on it
        # makes the orb feel like it goes off in your hand.
        if not self._dragged and event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()

    def mouseDoubleClickEvent(self, event):
        self.mic_active = not self.mic_active
        self.set_mic_active(self.mic_active)
        self.mic_toggled.emit(self.mic_active)

    # ── painting ─────────────────────────────────────────────────────

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = _STATE_COLORS.get(self.state, _STATE_COLORS[OrbState.IDLE])
        center = self.rect().center()
        radius = ORB_SIZE / 2 - 6

        gradient = QRadialGradient(float(center.x()), float(center.y()), radius)
        gradient.setColorAt(0.0, color.lighter(140))
        gradient.setColorAt(1.0, color.darker(160))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(gradient)
        painter.drawEllipse(center, int(radius), int(radius))

        if self.state == OrbState.LISTENING:
            # A ring breathing outward: the orb is taking input from you.
            alpha = int(200 * (1.0 - self._pulse))
            ring = QColor(color)
            ring.setAlpha(alpha)
            painter.setPen(QPen(ring, 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(center, int(radius + self._pulse * 6), int(radius + self._pulse * 6))
        elif self.state in (OrbState.READING, OrbState.TRANSLATING):
            # An arc going round: the orb is busy on your behalf.
            painter.setPen(QPen(color.lighter(160), 3))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            span = int(self._pulse * 5760)
            painter.drawArc(self.rect().adjusted(4, 4, -4, -4), span, 1440)


class OrbPanel(MageOverlayWindow):
    """The log, the chat box and the controls — one panel, three faces."""

    message_sent = pyqtSignal(str)
    mic_toggled = pyqtSignal(bool)
    add_box_requested = pyqtSignal()
    settings_requested = pyqtSignal()
    notes_requested = pyqtSignal()

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

        self._add_box_button = QPushButton(t("newui.orb.button.add_box"))
        self._add_box_button.clicked.connect(self.add_box_requested)
        self._notes_button = QPushButton(t("newui.orb.button.notes"))
        self._notes_button.clicked.connect(self.notes_requested)
        self._settings_button = QPushButton(t("newui.orb.button.settings"))
        self._settings_button.clicked.connect(self.settings_requested)
        for button in (self._add_box_button, self._notes_button, self._settings_button):
            header.addWidget(button)
        layout.addLayout(header)

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
