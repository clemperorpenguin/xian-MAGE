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

"""The orb and its panel: the log, the chat box and the microphone."""

import os
import sys

import pytest
from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QApplication, QWidget

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from mage.ui.new.orb import Orb, OrbPanel, OrbState  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def q_app():
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


class FakeApp(QWidget):
    def __init__(self):
        super().__init__()
        self.settings = QSettings("XianProject", "MageOrbTest")
        self.settings.clear()


@pytest.fixture
def app():
    app = FakeApp()
    yield app
    app.settings.clear()


@pytest.fixture
def panel(app):
    panel = OrbPanel(app=app)
    yield panel
    panel.close()


@pytest.fixture
def orb(app):
    orb = Orb(app=app)
    yield orb
    orb.close()


# ── the log ──────────────────────────────────────────────────────────

def test_a_translation_reaches_the_log(panel):
    panel.add_translation("这扇门被锁住了", "The door is locked.")

    body = panel._log.toPlainText()

    assert "这扇门被锁住了" in body
    assert "The door is locked." in body


def test_the_log_keeps_source_and_translation_together(panel):
    """Both, because the point of the log is checking one against the other."""
    panel.add_translation("门", "door")

    assert len(panel._entries) == 1
    assert "门" in panel._entries[0] and "door" in panel._entries[0]


def test_a_spoken_line_is_marked_differently_from_a_read_one(panel):
    panel.add_translation("read", "read out", kind="screen")
    panel.add_translation("heard", "heard out", kind="voice")

    assert "🎙" in panel._entries[1]
    assert "🎙" not in panel._entries[0]


def test_the_log_is_bounded(panel):
    """The session store keeps the history; this is a window onto it."""
    for index in range(panel.MAX_ENTRIES + 40):
        panel.add_translation(f"line {index}", f"translated {index}")

    assert len(panel._entries) == panel.MAX_ENTRIES
    assert "line 0" not in panel._log.toPlainText()


def test_markup_in_a_translation_is_escaped(panel):
    """Recognized text is arbitrary and lands in a rich-text widget."""
    panel.add_translation("<b>bold</b>", "<script>x</script>")

    assert "<script>" not in panel._log.toHtml()
    assert "<script>x</script>" in panel._log.toPlainText()


# ── chat ─────────────────────────────────────────────────────────────

def test_sending_a_message_emits_it_and_echoes_it(panel):
    sent = []
    panel.message_sent.connect(sent.append)
    panel._input.setText("what does that say?")

    panel._send()

    assert sent == ["what does that say?"]
    assert "what does that say?" in panel._log.toPlainText()
    assert panel._input.text() == ""


def test_an_empty_message_is_not_sent(panel):
    sent = []
    panel.message_sent.connect(sent.append)
    panel._input.setText("   ")

    panel._send()

    assert sent == []


# ── the microphone ───────────────────────────────────────────────────

def test_the_mic_button_reports_both_ways(panel):
    toggles = []
    panel.mic_toggled.connect(toggles.append)

    panel._mic_button.setChecked(True)
    panel._mic_button.setChecked(False)

    assert toggles == [True, False]


def test_setting_the_mic_state_does_not_echo_back(panel):
    """The shell sets both surfaces from one signal; a button that re-emitted
    on being told would loop."""
    toggles = []
    panel.mic_toggled.connect(toggles.append)

    panel.set_mic_active(True)

    assert toggles == []
    assert panel._mic_button.isChecked() is True


# ── the orb itself, which is the familiar ────────────────────────────

def test_the_orb_is_the_familiar(orb):
    """They were two creatures for the same screen."""
    from mage.ui.familiar_pet import FamiliarPet

    assert isinstance(orb, FamiliarPet)


def test_the_orb_wears_the_species_from_settings(app):
    from mage.settings_keys import KEY_FAMILIAR_TYPE
    from mage.ui.familiar_pet import FamiliarSpecies
    from mage.ui.new.orb import Orb

    app.settings.setValue(KEY_FAMILIAR_TYPE, "owl")
    orb = Orb(app=app)
    try:
        assert orb.species is FamiliarSpecies.OWL
    finally:
        orb.close()


def test_working_holds_the_familiar_s_casting_pose(orb):
    """The familiar already had a state for "a translation is running"; the
    orb asks for that rather than inventing a second vocabulary."""
    from mage.ui.familiar_pet import FamiliarState

    orb.set_state(OrbState.TRANSLATING)

    assert orb._state is FamiliarState.CAST


def test_going_idle_releases_the_casting_pose(orb):
    from mage.ui.familiar_pet import FamiliarState

    orb.set_state(OrbState.TRANSLATING)
    orb.set_state(OrbState.IDLE)

    assert orb._state is FamiliarState.IDLE


def test_a_failure_makes_the_familiar_sad(orb):
    from mage.ui.familiar_pet import FamiliarState

    orb.set_failed("no microphone")

    assert orb._state is FamiliarState.SAD


def test_speaking_puts_the_text_in_the_bubble(orb):
    """For what has no box of its own — speech, and the orb's own answers."""
    orb.speak("The door is locked.", original="这扇门被锁住了")

    assert orb._bubble.isVisible()


def test_the_mic_shows_on_the_orb(orb):
    orb.set_mic_active(True)

    assert orb.mic_active is True
    assert orb.state == OrbState.LISTENING


def test_turning_the_mic_off_returns_the_orb_to_idle(orb):
    orb.set_mic_active(True)
    orb.set_mic_active(False)

    assert orb.mic_active is False
    assert orb.state == OrbState.IDLE


def test_a_click_opens_the_panel_and_a_drag_does_not(orb):
    """The familiar already tells the two apart; the orb only changes what a
    click means — the chat sidebar it used to open is gone."""
    from PyQt6.QtCore import QPointF, Qt
    from PyQt6.QtGui import QMouseEvent

    opened = []
    orb.clicked.connect(lambda: opened.append(True))

    def event(kind):
        return QMouseEvent(
            kind, QPointF(5, 5), QPointF(5, 5),
            Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
        )

    orb._dragging_user = True
    orb.mouseReleaseEvent(event(QMouseEvent.Type.MouseButtonRelease))
    assert opened == []

    orb._dragging_user = False
    orb.mouseReleaseEvent(event(QMouseEvent.Type.MouseButtonRelease))
    assert opened == [True]


def test_a_double_click_toggles_the_microphone(orb):
    from PyQt6.QtCore import QPointF, Qt
    from PyQt6.QtGui import QMouseEvent

    toggles = []
    orb.mic_toggled.connect(toggles.append)

    event = QMouseEvent(
        QMouseEvent.Type.MouseButtonDblClick, QPointF(5, 5), QPointF(5, 5),
        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
    )
    orb.mouseDoubleClickEvent(event)
    orb.mouseDoubleClickEvent(event)

    assert toggles == [True, False]


def test_a_species_member_survives_being_resolved_again():
    """`str()` on an enum member is "FamiliarSpecies.OWL", not "owl".

    _species_from_settings hands __init__ a member, so without this every
    start resolved to a wizard whatever the user had chosen.
    """
    from mage.ui.familiar_pet import FamiliarSpecies

    assert FamiliarSpecies.from_value(FamiliarSpecies.OWL) is FamiliarSpecies.OWL
    assert FamiliarSpecies.from_value("owl") is FamiliarSpecies.OWL
    assert FamiliarSpecies.from_value("nonsense") is FamiliarSpecies.WIZARD
