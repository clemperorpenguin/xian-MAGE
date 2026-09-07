# Xian-VL — Core Vision-Language orchestration engine.
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

"""The reader: detection, rectification and recognition behind one call.

Sessions are built once and held for the life of the process.  Building an
ONNX Runtime session costs a large fraction of a tick, and the engine is shared
across every translation box on screen, so it is also the thing that has to be
kept off each other's toes — hence the lock.  ``read`` is synchronous and
expects to be called from a worker thread (``asyncio.to_thread``), never from
the Qt main thread.
"""

from __future__ import annotations

import logging
import os
import threading

import numpy as np

from xian.ocr.base import Line
from xian.ocr.detect import DetectConfig, TextDetector
from xian.ocr.models import ModelNotAvailable, ensure_model
from xian.ocr.preprocess import enhance
from xian.ocr.recognize import RecognizeConfig, TextRecognizer
from xian.ocr.rectify import rectify
from xian.ocr.scripts import SCRIPTS, recognizer_script_for

logger = logging.getLogger(__name__)

__all__ = ["DEFAULT_DETECTOR", "PaddleOcrEngine"]

DEFAULT_DETECTOR = "PP-OCRv5_mobile_det"


def _session_options(threads: int | None):
    """Bound ONNX Runtime's thread pool.

    Left unbounded it takes every core, and a recognition batch then competes
    with the compositor while a game is running — which shows up as the
    overlay stuttering rather than as the reader being slow, so it is easy to
    misdiagnose.
    """
    import onnxruntime as ort

    options = ort.SessionOptions()
    options.intra_op_num_threads = threads or max(1, (os.cpu_count() or 4) // 2)
    options.inter_op_num_threads = 1
    options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    return options


class PaddleOcrEngine:
    """PP-OCRv5 detection plus a per-script recognizer.

    Recognizers are loaded on demand and kept: switching source language mid
    session is cheap the second time, and a user who reads two languages should
    not pay a session build on every alternation.
    """

    def __init__(
        self,
        *,
        detector_model: str = DEFAULT_DETECTOR,
        source_language: str | None = None,
        detect_config: DetectConfig | None = None,
        recognize_config: RecognizeConfig | None = None,
        threads: int | None = None,
        providers: list[str] | None = None,
    ):
        self.detector_model = detector_model
        self.detect_config = detect_config or DetectConfig()
        self.recognize_config = recognize_config or RecognizeConfig()
        self.script = recognizer_script_for(source_language)
        self._threads = threads
        self._providers = providers or ["CPUExecutionProvider"]
        self._detector: TextDetector | None = None
        self._recognizers: dict[str, TextRecognizer] = {}
        # A plain lock, not an asyncio one: read() runs in a worker thread and
        # several boxes can reach it at the same time.
        self._lock = threading.Lock()

    # ── model loading ────────────────────────────────────────────────

    def _make_session(self, model_id: str):
        import onnxruntime as ort

        directory = ensure_model(model_id)
        path = directory / "model.onnx"
        logger.info("loading OCR model %s", model_id)
        return ort.InferenceSession(str(path), _session_options(self._threads), providers=self._providers)

    def _detector_for(self) -> TextDetector:
        if self._detector is None:
            self._detector = TextDetector(self._make_session(self.detector_model), self.detect_config)
        return self._detector

    def _recognizer_for(self, script: str) -> TextRecognizer:
        if script not in self._recognizers:
            model_id = SCRIPTS[script]
            directory = ensure_model(model_id)
            characters = (directory / "dict.txt").read_text(encoding="utf-8").split("\n")
            # The dictionary is written one character per line with a trailing
            # newline; that final empty string is not a class.
            if characters and characters[-1] == "":
                characters.pop()
            self._recognizers[script] = TextRecognizer(
                self._make_session(model_id), characters, self.recognize_config
            )
        return self._recognizers[script]

    def set_source_language(self, source_language: str | None) -> None:
        self.script = recognizer_script_for(source_language)

    def available(self) -> bool:
        """True when the models this engine needs are present and verified."""
        from xian.ocr.models import verify_model

        return verify_model(self.detector_model) and verify_model(SCRIPTS[self.script])

    def warm(self) -> None:
        """Build the sessions ahead of the first tick."""
        with self._lock:
            self._detector_for()
            self._recognizer_for(self.script)

    # ── the read ─────────────────────────────────────────────────────

    def read(self, image: np.ndarray, *, enhance_input: bool = True) -> list[Line]:
        """Detect and recognize every line in a BGR image.

        Returns lines in detector order; grouping decides reading order.
        """
        if image is None or image.size == 0:
            return []

        with self._lock:
            detector = self._detector_for()
            recognizer = self._recognizer_for(self.script)

            source = enhance(image) if enhance_input else image
            quads = detector.detect(source)
            if not quads:
                return []

            crops = [rectify(source, quad) for quad in quads]
            recognized = recognizer.recognize(crops)

        lines: list[Line] = []
        for quad, (text, confidence) in zip(quads, recognized):
            if not text.strip():
                continue
            if confidence < self.recognize_config.min_confidence:
                continue
            lines.append(Line(quad=quad, text=text, confidence=confidence))
        return lines

    def close(self) -> None:
        with self._lock:
            self._detector = None
            self._recognizers.clear()
