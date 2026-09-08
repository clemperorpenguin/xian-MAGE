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

"""Where the PP-OCRv5 ONNX models live, and how they get there.

PaddleOCR has never published an ONNX release for the v5 line, so the weights
are produced locally by ``scripts/export_ppocr_onnx.py``, which writes both the
models and ``catalog.json`` — the manifest this module verifies against.

That leaves two ways a model can be present:

* **Exported locally.**  The default.  ``scripts/export_ppocr_onnx.py`` fills
  the cache directly and records a checksum for every file it wrote.
* **Fetched from a distribution base URL**, set with ``XIAN_OCR_BASE_URL``.
  There is no default value: pointing this at a host is a deliberate act, and
  a wrong default would silently download someone else's weights.

The download path is RST's ``WhisperModelDownloader`` discipline — stage to
``.part``, resume with HTTP ``Range``, verify size *and* checksum, rename only
after verification, delete on mismatch.  It is worth that care here for a
specific reason: a truncated ONNX file does not raise when it is opened, it
faults inside the runtime several steps later, and the traceback points
somewhere else entirely.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import urllib.request
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

__all__ = [
    "CATALOG",
    "ModelNotAvailable",
    "cache_dir",
    "catalog",
    "ensure_model",
    "model_dir",
    "model_files",
    "verify_model",
]

CATALOG = Path(__file__).with_name("catalog.json")

#: Progress callback: ``(filename, fraction_complete)``.
ProgressCallback = Callable[[str, float], None]


class ModelNotAvailable(RuntimeError):
    """A model is not in the cache and there is nowhere to fetch it from."""


def cache_dir() -> Path:
    """Where exported models live.  Overridable for tests and for packaging."""
    override = os.environ.get("XIAN_OCR_CACHE")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".cache" / "xian-vl" / "ocr"


def catalog() -> dict[str, dict]:
    """The manifest of exportable models, keyed by model id.

    Empty when nothing has been exported yet, which is a normal first-run
    state and not an error — the engine turns it into an actionable message.
    """
    if not CATALOG.exists():
        return {}
    try:
        return json.loads(CATALOG.read_text(encoding="utf-8")).get("models", {})
    except (OSError, ValueError) as exc:
        logger.error("OCR model catalog is unreadable: %s", exc)
        return {}


def model_dir(model_id: str) -> Path:
    return cache_dir() / model_id


def model_files(model_id: str) -> dict[str, dict]:
    """The files one model consists of: its ONNX, and a dictionary if it reads."""
    entry = catalog().get(model_id, {})
    return {key: entry[key] for key in ("onnx", "dict") if key in entry}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_model(model_id: str) -> bool:
    """True when every file the catalog lists is present and matches.

    Checks size first because it is free, and only then the checksum, which
    reads the whole file.
    """
    files = model_files(model_id)
    if not files:
        return False

    directory = model_dir(model_id)
    for spec in files.values():
        path = directory / spec["name"]
        if not path.exists() or path.stat().st_size != spec["bytes"]:
            return False
        if _sha256(path) != spec["sha256"]:
            logger.error("checksum mismatch for %s; deleting", path)
            path.unlink(missing_ok=True)
            return False
    return True


def _download(url: str, dest: Path, spec: dict, progress: ProgressCallback | None) -> None:
    """Fetch one file, resuming a partial download and verifying the result."""
    part = dest.with_suffix(dest.suffix + ".part")
    have = part.stat().st_size if part.exists() else 0
    total = spec["bytes"]

    if have > total:  # a stale part from a different revision of the file
        part.unlink()
        have = 0

    if have < total:
        request = urllib.request.Request(url)
        if have:
            request.add_header("Range", f"bytes={have}-")
        with urllib.request.urlopen(request, timeout=60) as response, part.open("ab" if have else "wb") as out:
            while chunk := response.read(1 << 20):
                out.write(chunk)
                have += len(chunk)
                if progress:
                    progress(spec["name"], min(have / total, 1.0))

    size = part.stat().st_size
    if size != total:
        part.unlink(missing_ok=True)
        raise ModelNotAvailable(f"{dest.name}: expected {total} bytes, got {size}")
    if _sha256(part) != spec["sha256"]:
        part.unlink(missing_ok=True)
        raise ModelNotAvailable(f"{dest.name}: checksum mismatch")

    # Only now does the file take the name anything else will open.
    part.replace(dest)


def ensure_model(model_id: str, *, progress: ProgressCallback | None = None) -> Path:
    """Return the directory holding ``model_id``, fetching it if it is missing.

    Raises :class:`ModelNotAvailable` with a message that says what to run,
    because "no such file" from three frames deep inside ONNX Runtime is not a
    thing anyone can act on.
    """
    entry = catalog().get(model_id)
    if entry is None:
        raise ModelNotAvailable(
            f"{model_id} is not in the OCR model catalog. "
            f"Run: uv run --package mage-client python scripts/export_ppocr_onnx.py --only {model_id}"
        )

    directory = model_dir(model_id)
    if verify_model(model_id):
        return directory

    base_url = os.environ.get("XIAN_OCR_BASE_URL", "").rstrip("/")
    if not base_url:
        raise ModelNotAvailable(
            f"{model_id} is not in {directory}. "
            f"Run: uv run --package mage-client python scripts/export_ppocr_onnx.py --only {model_id}\n"
            "(or set XIAN_OCR_BASE_URL to a host serving the exported models)"
        )

    directory.mkdir(parents=True, exist_ok=True)
    for spec in model_files(model_id).values():
        target = directory / spec["name"]
        if target.exists() and target.stat().st_size == spec["bytes"] and _sha256(target) == spec["sha256"]:
            continue
        logger.info("downloading %s/%s", model_id, spec["name"])
        _download(f"{base_url}/{model_id}/{spec['name']}", target, spec, progress)

    return directory
