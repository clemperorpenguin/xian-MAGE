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

"""Everything you can configure, arranged by what you came here to do.

There were four tabs, and one of them — "Features" — had grown to seventeen
controls with nothing in common: two hotkeys, the live translation tuning, the
session memory, the familiar, the overlay's opacity and text size, and the
developer toggle, in one flat column.  A tab whose name does not predict its
contents is a tab you have to read end to end every time.

Five now, each named for a task rather than for a part of the program:

    Translation  what the words become — languages, model, style, and the
                 live reader that produces them
    Overlay      what you see — opacity, text size, where the windows sit
    Server       where the models run
    Assistant    the orb, its voice, and what it remembers
    Advanced     hotkeys and developer options

Inside a tab, related rows sit under a heading rather than running together,
because a form of eleven rows reads as eleven unrelated decisions.

Three settings are gone rather than moved: the leader key and the dialogue
delay drove the old letter-menu interface, and the "experimental live
translation" checkbox gated a live overlay the translation boxes never
consulted.  All three had stopped controlling anything, which is worse than
missing: a setting that lies costs the user the time they spend believing it.
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import Qt, QSettings, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSlider,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from mage.settings_keys import (
    DEFAULT_LIVE_ENGINE,
    KEY_API_MODEL,
    KEY_API_URL,
    KEY_AUTO_CONTINUE,
    KEY_AUTO_SPEAK,
    KEY_BACKEND_PREFERENCE,
    KEY_COLLECTION_TIER,
    KEY_FAMILIAR_ENABLED,
    KEY_FAMILIAR_TTS,
    KEY_FAMILIAR_TYPE,
    KEY_GPU_UTIL,
    KEY_IGNORE_PHRASES,
    KEY_LIVE_ENGINE,
    KEY_LIVE_INTERVAL_MS,
    KEY_MAX_TOKENS,
    KEY_MEMORY_ENABLED,
    KEY_MEMORY_RETENTION_DAYS,
    KEY_MODE,
    KEY_NPU_POWER_MODE,
    KEY_OCR_DETECTOR,
    KEY_OVERLAY_TOGGLE_KEY,
    KEY_SOURCE_LANG,
    KEY_STYLES,
    KEY_TARGET_LANG,
    KEY_TARGET_WINDOW_TITLE,
    KEY_TRANSLATION_MODEL,
    KEY_UI_LANG,
    LIVE_ENGINE_GROUNDING,
    LIVE_ENGINE_OCR,
    is_true,
    normalized_api_url_from_settings,
    parse_styles,
)
from mage.ui.theme import accent_hex, accent_hover_hex
from mage.utils.window_binder import WindowBinder
from shared_types import constants
from shared_types.enums import SourceLanguage, TargetLanguage, TranslationMode, TranslationStyle
from shared_types.state import state, t
from xian.collections import COLLECTIONS, get_collection
from xian.lemonade_url import normalize_lemonade_api_base_url, should_warn_http_to_non_loopback

logger = logging.getLogger(__name__)

__all__ = ["SettingsDialog"]

_STYLE_SHEET = """
    QDialog { background: #1e1e1e; color: #eee; }
    QLabel, QCheckBox { color: #ccc; }
    QLineEdit, QComboBox, QSpinBox, QPlainTextEdit {
        background: #2a2a2a; color: #eee; border: 1px solid #555;
        border-radius: 4px; padding: 4px;
    }
    QPushButton {
        background: %s; color: white; border: none;
        padding: 6px 16px; border-radius: 4px; font-weight: bold;
    }
    QPushButton:hover { background: %s; }
    QTabWidget::pane { border: 1px solid #555; background: #1e1e1e; }
    QTabBar::tab { background: #2a2a2a; color: #ccc; padding: 8px 16px; border: 1px solid #555; }
    QTabBar::tab:selected { background: %s; color: white; }
"""


def _heading(form: QFormLayout, key: str, *, first: bool = False) -> QLabel:
    """A section title inside a tab.

    Spaced above rather than below: the gap is what tells you the heading
    belongs to what follows it, and the first one has nothing to be spaced
    away from.
    """
    label = QLabel(t(key))
    label.setStyleSheet(
        "font-weight: bold; color: #9aa0b5; %s" % ("" if first else "margin-top: 10px;")
    )
    form.addRow(label)
    return label


class SettingsDialog(QDialog):
    """Everything configurable, in five tabs named for what you came to do."""

    layout_edit_requested = pyqtSignal()

    #: Set on save when the collection tier changed, so the caller installs it.
    tier_changed = False

    def __init__(self, settings: QSettings, models: list, parent=None, app=None):
        super().__init__(parent)
        self.setWindowTitle(t("settings.dialog.title"))
        self.setMinimumWidth(480)
        self.settings = settings
        self.app = app
        self._models = models or []

        main_layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        main_layout.addWidget(self.tabs)

        self.tabs.addTab(self._translation_tab(), t("settings.tab.translation"))
        self.tabs.addTab(self._overlay_tab(), t("settings.tab.overlay"))
        self.tabs.addTab(self._server_tab(), t("settings.tab.server"))
        self.tabs.addTab(self._assistant_tab(), t("settings.tab.assistant"))
        self.tabs.addTab(self._advanced_tab(), t("settings.tab.advanced"))

        btn_row = QHBoxLayout()
        save_btn = QPushButton(t("settings.button.save"))
        save_btn.clicked.connect(self._save)
        cancel_btn = QPushButton(t("settings.button.cancel"))
        cancel_btn.clicked.connect(self.reject)
        btn_row.addStretch()
        btn_row.addWidget(save_btn)
        btn_row.addWidget(cancel_btn)
        main_layout.addLayout(btn_row)

        self.setStyleSheet(_STYLE_SHEET % (accent_hex(), accent_hover_hex(), accent_hex()))

        # Applied last: it hides rows across two tabs, so every row has to
        # exist before it runs.
        self._update_dev_visibility(self.dev_options_cb.isChecked())

    # ── Translation ──────────────────────────────────────────────────

    def _translation_tab(self) -> QWidget:
        """What the words become.

        The live reader lives here rather than under a "features" heading
        because reading the screen and translating what was read are one
        operation to everybody except the code.
        """
        settings = self.settings
        tab = QWidget()
        form = QFormLayout(tab)

        _heading(form, "settings.heading.languages", first=True)

        self.source_lang_combo = QComboBox()
        self.source_lang_combo.addItems([e.value for e in SourceLanguage])
        self.source_lang_combo.setCurrentText(settings.value(KEY_SOURCE_LANG, constants.DEFAULT_SOURCE_LANG))
        form.addRow(t("settings.label.source_language"), self.source_lang_combo)

        self.lang_combo = QComboBox()
        self.lang_combo.addItems([e.value for e in TargetLanguage])
        self.lang_combo.setCurrentText(settings.value(KEY_TARGET_LANG, constants.DEFAULT_TARGET_LANG))
        form.addRow(t("settings.label.target_language"), self.lang_combo)

        self.mode_combo = QComboBox()
        self.mode_combo.addItems([e.value for e in TranslationMode])
        self.mode_combo.setCurrentText(settings.value(KEY_MODE, constants.DEFAULT_MODE))
        form.addRow(t("settings.label.mode"), self.mode_combo)

        # Text translation is Hy-MT2 or nothing: the prompts are its own
        # published instruction formats and the pipeline is shaped around it,
        # so the choice here is which size, not which model.
        from xian.translate import TRANSLATION_MODEL, TRANSLATION_MODELS

        self.translation_model_combo = QComboBox()
        for model_id in TRANSLATION_MODELS:
            self.translation_model_combo.addItem(t(f"settings.option.translation_model.{model_id}"), model_id)
        tm_idx = self.translation_model_combo.findData(settings.value(KEY_TRANSLATION_MODEL, TRANSLATION_MODEL))
        if tm_idx >= 0:
            self.translation_model_combo.setCurrentIndex(tm_idx)
        self.translation_model_combo.setToolTip(t("settings.tooltip.translation_model"))
        form.addRow(t("settings.label.translation_model"), self.translation_model_combo)

        style_layout = QVBoxLayout()
        self.style_checkboxes = {}
        saved_styles = parse_styles(settings)
        for style in TranslationStyle:
            cb = QCheckBox(style.value)
            if style.value in saved_styles:
                cb.setChecked(True)
            self.style_checkboxes[style.value] = cb
            style_layout.addWidget(cb)
        form.addRow(t("settings.label.styles"), style_layout)

        _heading(form, "settings.heading.live_translation")

        self.live_engine_combo = QComboBox()
        self.live_engine_combo.addItem(t("settings.option.live_engine.grounding"), LIVE_ENGINE_GROUNDING)
        self.live_engine_combo.addItem(t("settings.option.live_engine.ocr"), LIVE_ENGINE_OCR)
        engine_idx = self.live_engine_combo.findData(settings.value(KEY_LIVE_ENGINE, DEFAULT_LIVE_ENGINE))
        if engine_idx >= 0:
            self.live_engine_combo.setCurrentIndex(engine_idx)
        self.live_engine_combo.setToolTip(t("settings.tooltip.live_engine"))
        form.addRow(t("settings.label.live_engine"), self.live_engine_combo)

        self.live_interval_spin = QSpinBox()
        self.live_interval_spin.setRange(200, 5000)
        self.live_interval_spin.setSingleStep(100)
        self.live_interval_spin.setSuffix(" ms")
        self.live_interval_spin.setValue(
            int(settings.value(KEY_LIVE_INTERVAL_MS, constants.DEFAULT_LIVE_INTERVAL_MS))
        )
        self.live_interval_spin.setToolTip(t("settings.tooltip.live_interval"))
        form.addRow(t("settings.label.live_interval"), self.live_interval_spin)

        self.ocr_detector_combo = QComboBox()
        self.ocr_detector_combo.addItem(t("settings.option.ocr_detector.mobile"), "PP-OCRv5_mobile_det")
        self.ocr_detector_combo.addItem(t("settings.option.ocr_detector.server"), "PP-OCRv5_server_det")
        detector_idx = self.ocr_detector_combo.findData(settings.value(KEY_OCR_DETECTOR, "PP-OCRv5_mobile_det"))
        if detector_idx >= 0:
            self.ocr_detector_combo.setCurrentIndex(detector_idx)
        self.ocr_detector_combo.setToolTip(t("settings.tooltip.ocr_detector"))
        form.addRow(t("settings.label.ocr_detector"), self.ocr_detector_combo)

        self.ignore_phrases_edit = QPlainTextEdit()
        self.ignore_phrases_edit.setPlainText(settings.value(KEY_IGNORE_PHRASES, "") or "")
        self.ignore_phrases_edit.setFixedHeight(70)
        self.ignore_phrases_edit.setToolTip(t("settings.tooltip.ignore_phrases"))
        form.addRow(t("settings.label.ignore_phrases"), self.ignore_phrases_edit)

        # Only the local reader has a detector or a filter list to configure.
        def _sync_ocr_rows(_=None):
            is_ocr = self.live_engine_combo.currentData() == LIVE_ENGINE_OCR
            self.ocr_detector_combo.setEnabled(is_ocr)
            self.ignore_phrases_edit.setEnabled(is_ocr)

        self.live_engine_combo.currentIndexChanged.connect(_sync_ocr_rows)
        _sync_ocr_rows()

        _heading(form, "settings.heading.behaviour")

        self.auto_continue_cb = QCheckBox(t("settings.checkbox.auto_continue"))
        self.auto_continue_cb.setChecked(is_true(settings.value(KEY_AUTO_CONTINUE, "false")))
        form.addRow(self.auto_continue_cb)

        return tab

    # ── Overlay ──────────────────────────────────────────────────────

    def _overlay_tab(self) -> QWidget:
        """What you see, and where it sits."""
        settings = self.settings
        tab = QWidget()
        form = QFormLayout(tab)

        _heading(form, "settings.heading.appearance", first=True)

        opacity_row = QHBoxLayout()
        self.opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self.opacity_slider.setRange(20, 100)
        self.opacity_slider.setSingleStep(5)
        self.opacity_slider.setPageStep(10)
        opacity_val = int(settings.value("overlay_opacity", 85))
        self.opacity_slider.setValue(opacity_val)
        self.opacity_value_label = QLabel(f"{opacity_val}%")
        self.opacity_value_label.setFixedWidth(36)
        self.opacity_slider.valueChanged.connect(lambda v: self.opacity_value_label.setText(f"{v}%"))
        opacity_row.addWidget(self.opacity_slider)
        opacity_row.addWidget(self.opacity_value_label)
        form.addRow(t("settings.label.overlay_opacity"), opacity_row)

        self.text_size_spin = QSpinBox()
        self.text_size_spin.setRange(8, 24)
        self.text_size_spin.setValue(int(settings.value("overlay_text_size", 13)))
        form.addRow(t("settings.label.text_size"), self.text_size_spin)

        self.ui_lang_combo = QComboBox()
        self.ui_lang_combo.addItems(["en", "zh", "ja", "ko", "ru", "es", "ar", "hi", "vi"])
        self.ui_lang_combo.setCurrentText(settings.value(KEY_UI_LANG, "en"))
        form.addRow(t("settings.label.ui_language"), self.ui_lang_combo)

        _heading(form, "settings.heading.placement")

        preset_layout = QHBoxLayout()
        self.preset_combo = QComboBox()
        presets = settings.value("layout_presets_list", ["Default"])
        if not isinstance(presets, list):
            presets = ["Default"]
        self.preset_combo.addItems(presets)
        current_preset = settings.value("layout_preset", "Default")
        idx = self.preset_combo.findText(current_preset)
        if idx >= 0:
            self.preset_combo.setCurrentIndex(idx)

        self.add_preset_btn = QPushButton("+")
        self.add_preset_btn.setFixedWidth(30)
        self.add_preset_btn.clicked.connect(self._add_preset)

        self.del_preset_btn = QPushButton("-")
        self.del_preset_btn.setFixedWidth(30)
        self.del_preset_btn.clicked.connect(self._del_preset)

        self.edit_layout_btn = QPushButton(t("settings.button.edit_layout"))
        self.edit_layout_btn.clicked.connect(self._on_edit_layout)

        preset_layout.addWidget(self.preset_combo)
        preset_layout.addWidget(self.add_preset_btn)
        preset_layout.addWidget(self.del_preset_btn)
        preset_layout.addWidget(self.edit_layout_btn)
        form.addRow(t("settings.label.layout_preset"), preset_layout)

        self.target_window_combo = QComboBox()
        self.target_window_combo.setEditable(True)
        self.target_window_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.target_window_combo.addItem(t("settings.option.none_overlay"), "")
        try:
            for title in WindowBinder.get_active_window_titles():
                self.target_window_combo.addItem(title, title)
        except Exception as e:
            logger.error("Could not fetch active window titles: %s", e)

        current_title = settings.value(KEY_TARGET_WINDOW_TITLE, "")
        if current_title:
            idx = self.target_window_combo.findData(current_title)
            if idx >= 0:
                self.target_window_combo.setCurrentIndex(idx)
            else:
                self.target_window_combo.addItem(current_title, current_title)
                self.target_window_combo.setCurrentText(current_title)
        else:
            self.target_window_combo.setCurrentIndex(0)
        form.addRow(t("settings.label.target_window_title"), self.target_window_combo)

        return tab

    # ── Server ───────────────────────────────────────────────────────

    def _server_tab(self) -> QWidget:
        """Where the models run, and how much of the machine they get."""
        settings = self.settings
        tab = QWidget()
        form = QFormLayout(tab)

        _heading(form, "settings.heading.connection", first=True)

        self.url_edit = QLineEdit()
        self.url_edit.setText(normalized_api_url_from_settings(settings))
        form.addRow(t("settings.label.server_url"), self.url_edit)

        self.model_combo = QComboBox()
        self.model_combo.setEditable(True)
        if self._models:
            self.model_combo.addItems(self._models)
        self.model_combo.setCurrentText(settings.value(KEY_API_MODEL, constants.DEFAULT_MODEL))
        form.addRow(t("settings.label.model"), self.model_combo)

        # Which Xian collection to install. Picking one here re-registers it
        # and points the model above at it; the model field stays editable for
        # anyone who would rather drive a model of their own choosing.
        self.tier_combo = QComboBox()
        for tier, collection in COLLECTIONS.items():
            label = f"{t(f'settings.option.collection.{tier.value}')} — {collection.size_gb:.1f} GB"
            self.tier_combo.addItem(label, tier.value)
        self._initial_tier = settings.value(KEY_COLLECTION_TIER, constants.DEFAULT_COLLECTION_TIER)
        tier_idx = self.tier_combo.findData(self._initial_tier)
        if tier_idx >= 0:
            self.tier_combo.setCurrentIndex(tier_idx)
        self.tier_combo.setToolTip(t("settings.tooltip.collection_tier"))
        form.addRow(t("settings.label.collection_tier"), self.tier_combo)

        _heading(form, "settings.heading.hardware")

        self.tokens_spin = QSpinBox()
        self.tokens_spin.setRange(256, 32768)
        self.tokens_spin.setValue(int(settings.value(KEY_MAX_TOKENS, constants.DEFAULT_MAX_TOKENS)))
        form.addRow(t("settings.label.max_tokens"), self.tokens_spin)

        self.gpu_combo = QComboBox()
        self.gpu_combo.addItems(["Default", "0.5", "0.75"])
        self.gpu_combo.setCurrentText(settings.value(KEY_GPU_UTIL, constants.DEFAULT_GPU_MEMORY_UTILIZATION))
        form.addRow(t("settings.label.gpu_memory_utilization"), self.gpu_combo)

        # Accelerator choice. Only text and speech can move to the NPU — the
        # vision model always runs on the GPU, so this never affects how fast
        # the screen is read.
        self.backend_combo = QComboBox()
        for pref in constants.BACKEND_PREFERENCES:
            self.backend_combo.addItem(t(f"settings.option.backend.{pref}"), pref)
        b_idx = self.backend_combo.findData(
            settings.value(KEY_BACKEND_PREFERENCE, constants.DEFAULT_BACKEND_PREFERENCE)
        )
        if b_idx >= 0:
            self.backend_combo.setCurrentIndex(b_idx)
        self.backend_combo.setToolTip(t("settings.tooltip.backend_preference"))
        form.addRow(t("settings.label.backend_preference"), self.backend_combo)

        self.npu_power_combo = QComboBox()
        for mode in constants.NPU_POWER_MODES:
            self.npu_power_combo.addItem(t(f"settings.option.npu_power.{mode}"), mode)
        p_idx = self.npu_power_combo.findData(settings.value(KEY_NPU_POWER_MODE, constants.DEFAULT_NPU_POWER_MODE))
        if p_idx >= 0:
            self.npu_power_combo.setCurrentIndex(p_idx)
        npu_available = bool(self.app and self.app.processor.router.npu_available())
        self.npu_power_combo.setEnabled(npu_available)
        if not npu_available:
            self.npu_power_combo.setToolTip(t("settings.tooltip.npu_unavailable"))
        form.addRow(t("settings.label.npu_power_mode"), self.npu_power_combo)

        return tab

    # ── Assistant ────────────────────────────────────────────────────

    def _assistant_tab(self) -> QWidget:
        """The orb, its voice, and what it remembers."""
        settings = self.settings
        tab = QWidget()
        form = QFormLayout(tab)
        self._assistant_form = form

        _heading(form, "settings.heading.memory", first=True)

        self.memory_enabled_cb = QCheckBox(t("settings.checkbox.memory_enabled"))
        self.memory_enabled_cb.setToolTip(t("settings.tooltip.memory_enabled"))
        self.memory_enabled_cb.setChecked(is_true(settings.value(KEY_MEMORY_ENABLED, "true")))
        form.addRow(self.memory_enabled_cb)

        memory_row = QHBoxLayout()
        self.memory_retention_spin = QSpinBox()
        self.memory_retention_spin.setRange(1, 365)
        self.memory_retention_spin.setSuffix(" d")
        self.memory_retention_spin.setValue(
            int(settings.value(KEY_MEMORY_RETENTION_DAYS, constants.DEFAULT_MEMORY_RETENTION_DAYS))
        )
        memory_row.addWidget(self.memory_retention_spin, 1)
        self.clear_memory_btn = QPushButton(t("settings.button.clear_memory"))
        self.clear_memory_btn.clicked.connect(self._on_clear_memory_clicked)
        memory_row.addWidget(self.clear_memory_btn)
        form.addRow(t("settings.label.memory_retention"), memory_row)

        _heading(form, "settings.heading.voice")

        self.auto_speak_cb = QCheckBox(t("settings.checkbox.auto_speak"))
        self.auto_speak_cb.setChecked(is_true(settings.value(KEY_AUTO_SPEAK, "false")))
        form.addRow(self.auto_speak_cb)

        self.familiar_tts_cb = QCheckBox(t("settings.checkbox.familiar_tts"))
        self.familiar_tts_cb.setChecked(is_true(settings.value(KEY_FAMILIAR_TTS, "false")))
        form.addRow(self.familiar_tts_cb)

        self.live_voice_raid_cb = QCheckBox(t("settings.checkbox.live_voice_raid"))
        self.live_voice_raid_cb.setChecked(is_true(settings.value("live_voice_raid", "false")))
        form.addRow(self.live_voice_raid_cb)

        self.live_raid_lore_save_cb = QCheckBox(t("settings.checkbox.live_raid_lore_save"))
        self.live_raid_lore_save_cb.setChecked(is_true(settings.value("live_raid_lore_save", "false")))
        form.addRow(self.live_raid_lore_save_cb)

        self._familiar_heading = _heading(form, "settings.heading.familiar")

        self.familiar_enabled_cb = QCheckBox(t("settings.checkbox.familiar_enabled"))
        self.familiar_enabled_cb.setChecked(is_true(settings.value(KEY_FAMILIAR_ENABLED, "false")))
        form.addRow(self.familiar_enabled_cb)

        self.familiar_type_combo = QComboBox()
        for species in ("wizard", "witch", "cat", "owl", "lemonfae", "custom"):
            self.familiar_type_combo.addItem(t(f"familiar.species.{species}"), species)
        ft_idx = self.familiar_type_combo.findData(settings.value(KEY_FAMILIAR_TYPE, "wizard"))
        if ft_idx >= 0:
            self.familiar_type_combo.setCurrentIndex(ft_idx)
        fam_type_row = QHBoxLayout()
        fam_type_row.addWidget(self.familiar_type_combo, 1)
        self.conjure_btn = QPushButton(t("familiar.conjure.button"))
        self.conjure_btn.clicked.connect(self._on_conjure_clicked)
        fam_type_row.addWidget(self.conjure_btn)
        self.fam_type_row = fam_type_row
        form.addRow(t("settings.label.familiar_type"), fam_type_row)

        return tab

    # ── Advanced ─────────────────────────────────────────────────────

    def _advanced_tab(self) -> QWidget:
        """The two things left that are neither a task nor a preference."""
        settings = self.settings
        tab = QWidget()
        form = QFormLayout(tab)

        _heading(form, "settings.heading.hotkeys", first=True)

        # The one gesture with no clickable substitute: a fullscreen game
        # holding the pointer leaves nothing to click.
        self.overlay_toggle_combo = QComboBox()
        self.overlay_toggle_combo.addItem("Right Shift", "rshift")
        self.overlay_toggle_combo.addItem("Right Ctrl", "rctrl")
        self.overlay_toggle_combo.addItem("Right Alt", "ralt")
        self.overlay_toggle_combo.addItem("Super", "super")
        t_idx = self.overlay_toggle_combo.findData(
            settings.value(KEY_OVERLAY_TOGGLE_KEY, constants.DEFAULT_OVERLAY_TOGGLE_KEY)
        )
        if t_idx >= 0:
            self.overlay_toggle_combo.setCurrentIndex(t_idx)
        self.overlay_toggle_combo.setToolTip(t("settings.tooltip.overlay_toggle_key"))
        form.addRow(t("settings.label.overlay_toggle_key"), self.overlay_toggle_combo)

        _heading(form, "settings.heading.developer")

        self.dev_options_cb = QCheckBox(t("settings.checkbox.dev_options"))
        self.dev_options_cb.setChecked(is_true(settings.value("developer_options", "false")))
        self.dev_options_cb.toggled.connect(self._update_dev_visibility)
        form.addRow(self.dev_options_cb)

        return tab

    # ── layout presets ───────────────────────────────────────────────

    def _add_preset(self):
        name, ok = QInputDialog.getText(
            self, t("settings.prompt.layout_preset.new"), t("settings.prompt.layout_preset.new")
        )
        if not ok:
            return
        name = name.strip()
        if not name:
            QMessageBox.critical(self, "Error", t("settings.error.layout_preset.invalid"))
            return
        presets = [self.preset_combo.itemText(i) for i in range(self.preset_combo.count())]
        if name in presets:
            QMessageBox.critical(self, "Error", t("settings.error.layout_preset.exists"))
            return

        presets.append(name)
        self.settings.setValue("layout_presets_list", presets)
        self.preset_combo.addItem(name)
        self.preset_combo.setCurrentText(name)

    def _del_preset(self):
        current = self.preset_combo.currentText()
        if current == "Default":
            QMessageBox.critical(self, "Error", "The Default preset cannot be deleted.")
            return

        choice = QMessageBox.question(
            self,
            "Delete Preset",
            f"Are you sure you want to delete the layout preset '{current}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if choice != QMessageBox.StandardButton.Yes:
            return

        presets = [self.preset_combo.itemText(i) for i in range(self.preset_combo.count())]
        presets.remove(current)
        self.settings.setValue("layout_presets_list", presets)
        self.settings.remove(f"layout/{current}")

        idx = self.preset_combo.findText(current)
        if idx >= 0:
            self.preset_combo.removeItem(idx)
        self.preset_combo.setCurrentText("Default")

    # ── the buttons ──────────────────────────────────────────────────

    def _save(self):
        normalized = normalize_lemonade_api_base_url(self.url_edit.text().strip())
        if should_warn_http_to_non_loopback(normalized):
            choice = QMessageBox.warning(
                self,
                t("settings.warn.http_remote.title"),
                t("settings.warn.http_remote.body"),
                QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Save,
            )
            if choice == QMessageBox.StandardButton.Cancel:
                return
        self.url_edit.setText(normalized)

        settings = self.settings
        settings.setValue(KEY_API_URL, normalized)
        settings.setValue(KEY_API_MODEL, self.model_combo.currentText())

        # A changed tier names a different collection, so it also decides the
        # model — otherwise the combo above would keep pointing at the old one.
        selected_tier = self.tier_combo.currentData()
        self.tier_changed = selected_tier != self._initial_tier
        settings.setValue(KEY_COLLECTION_TIER, selected_tier)
        if self.tier_changed:
            settings.setValue(KEY_API_MODEL, get_collection(selected_tier).name)

        settings.setValue(KEY_MAX_TOKENS, self.tokens_spin.value())
        settings.setValue(KEY_GPU_UTIL, self.gpu_combo.currentText())
        settings.setValue(KEY_BACKEND_PREFERENCE, self.backend_combo.currentData())
        settings.setValue(KEY_NPU_POWER_MODE, self.npu_power_combo.currentData())

        settings.setValue(KEY_SOURCE_LANG, self.source_lang_combo.currentText())
        settings.setValue(KEY_TARGET_LANG, self.lang_combo.currentText())
        settings.setValue(KEY_MODE, self.mode_combo.currentText())
        settings.setValue(KEY_TRANSLATION_MODEL, self.translation_model_combo.currentData())
        settings.setValue(KEY_STYLES, [s for s, cb in self.style_checkboxes.items() if cb.isChecked()])
        settings.setValue(KEY_LIVE_ENGINE, self.live_engine_combo.currentData())
        settings.setValue(KEY_LIVE_INTERVAL_MS, self.live_interval_spin.value())
        settings.setValue(KEY_OCR_DETECTOR, self.ocr_detector_combo.currentData())
        settings.setValue(KEY_IGNORE_PHRASES, self.ignore_phrases_edit.toPlainText())
        settings.setValue(KEY_AUTO_CONTINUE, "true" if self.auto_continue_cb.isChecked() else "false")

        settings.setValue("overlay_opacity", self.opacity_slider.value())
        settings.setValue("overlay_text_size", self.text_size_spin.value())
        ui_lang = self.ui_lang_combo.currentText()
        settings.setValue(KEY_UI_LANG, ui_lang)
        state.load_locale(ui_lang)
        settings.setValue("layout_preset", self.preset_combo.currentText())
        settings.setValue(KEY_TARGET_WINDOW_TITLE, self._target_window_title())

        settings.setValue(KEY_MEMORY_ENABLED, "true" if self.memory_enabled_cb.isChecked() else "false")
        settings.setValue(KEY_MEMORY_RETENTION_DAYS, self.memory_retention_spin.value())
        settings.setValue(KEY_AUTO_SPEAK, "true" if self.auto_speak_cb.isChecked() else "false")
        settings.setValue(KEY_FAMILIAR_TTS, "true" if self.familiar_tts_cb.isChecked() else "false")
        settings.setValue("live_voice_raid", "true" if self.live_voice_raid_cb.isChecked() else "false")
        settings.setValue("live_raid_lore_save", "true" if self.live_raid_lore_save_cb.isChecked() else "false")
        settings.setValue(KEY_FAMILIAR_ENABLED, "true" if self.familiar_enabled_cb.isChecked() else "false")
        settings.setValue(KEY_FAMILIAR_TYPE, self.familiar_type_combo.currentData())

        settings.setValue(KEY_OVERLAY_TOGGLE_KEY, self.overlay_toggle_combo.currentData())
        settings.setValue("developer_options", "true" if self.dev_options_cb.isChecked() else "false")
        self.accept()

    def _target_window_title(self) -> str:
        """The window to follow, or empty for "stay where you are put"."""
        value = self.target_window_combo.currentText().strip()
        if (
            self.target_window_combo.currentIndex() == 0
            or value == t("settings.option.none_overlay")
            or value == "None (Standard Overlay Mode)"
        ):
            return ""
        return value

    def _on_edit_layout(self):
        self.layout_edit_requested.emit()
        self.accept()

    def _on_clear_memory_clicked(self):
        """'Clear memory': erase the whole play history."""
        confirm = QMessageBox.question(
            self,
            t("settings.button.clear_memory"),
            t("settings.confirm.clear_memory"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        if self.app is not None:
            self.app.clear_session_memory()

    def _on_conjure_clicked(self):
        """'Conjure…': generate via the app, then select the custom species."""
        if self.app is not None and self.app.conjure_familiar():
            idx = self.familiar_type_combo.findData("custom")
            if idx >= 0:
                self.familiar_type_combo.setCurrentIndex(idx)

    def _update_dev_visibility(self, checked):
        """Hide the half-finished things unless the user asked to see them."""
        self.live_voice_raid_cb.setVisible(checked)
        self.live_raid_lore_save_cb.setVisible(checked)
        # The familiar is developer-only while its art is in progress.
        self._familiar_heading.setVisible(checked)
        self.familiar_enabled_cb.setVisible(checked)
        self.familiar_tts_cb.setVisible(checked)
        self._assistant_form.setRowVisible(self.fam_type_row, checked)
