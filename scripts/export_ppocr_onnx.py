#!/usr/bin/env python3
# Xian-VL Scripts — Development and automation scripts.
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

"""Export the PP-OCRv5 inference models to ONNX.

PaddleOCR publishes PP-OCRv5 as Paddle inference models — ``inference.json``
plus ``inference.pdiparams`` — and has never published an ONNX release for the
v5 line.  ``xian.ocr`` drives the models directly through ONNX Runtime, so the
conversion has to happen somewhere, and doing it here means the provenance is
ours: this script names the exact upstream URL for every file and records the
checksum of everything it produces.

Two things are deliberate:

* **paddlepaddle never enters the workspace venv.**  ``paddle2onnx`` imports
  ``paddle``, which is a very large dependency for a one-time build step and a
  second inference runtime in a process that already has ONNX Runtime.  The
  conversion is shelled out to a throwaway ``uv run --with`` environment, and
  this script itself needs nothing the workspace does not already have.

* **The character dictionary comes out of the same tarball as the weights.**
  It is embedded in ``inference.yml`` under ``PostProcess.character_dict``, so
  a recognizer and its dictionary can never drift apart the way they do when
  the dictionary is fetched separately from the PaddleOCR source tree.

Run it once, then commit the manifest it writes to ``xian/ocr/catalog.json`` so
the runtime downloader has checksums to verify against.

    uv run --package mage-client python scripts/export_ppocr_onnx.py
    uv run --package mage-client python scripts/export_ppocr_onnx.py --only PP-OCRv5_mobile_det
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

import yaml

#: Where PaddleOCR publishes the official Paddle 3.0 inference models.
BASE_URL = "https://paddle-model-ecology.bj.bcebos.com/paddlex/official_inference_model/paddle3.0.0"

#: The models ``xian.ocr`` can use.  ``role`` decides what the exporter has to
#: pull out of the tarball: a recognizer carries a character dictionary, a
#: detector does not.
MODELS: dict[str, dict] = {
    "PP-OCRv5_mobile_det": {"role": "det", "scripts": [], "quality": "fast"},
    "PP-OCRv5_server_det": {"role": "det", "scripts": [], "quality": "accurate"},
    "PP-OCRv5_mobile_rec": {"role": "rec", "scripts": ["cjk"], "quality": "fast"},
    "PP-OCRv5_server_rec": {"role": "rec", "scripts": ["cjk"], "quality": "accurate"},
    "latin_PP-OCRv5_mobile_rec": {"role": "rec", "scripts": ["latin"], "quality": "fast"},
    "korean_PP-OCRv5_mobile_rec": {"role": "rec", "scripts": ["korean"], "quality": "fast"},
    "eslav_PP-OCRv5_mobile_rec": {"role": "rec", "scripts": ["eslav"], "quality": "fast"},
}

#: The conversion environment.  Pinned to 3.12 because paddlepaddle publishes
#: no 3.13 wheel, which is precisely why it is not allowed near the workspace.
CONVERT_CMD = [
    "uv", "run", "--python", "3.12", "--no-project",
    "--with", "paddlepaddle", "--with", "paddle2onnx", "--with", "packaging",
    "paddle2onnx",
]

DEFAULT_OUT = Path.home() / ".cache" / "xian-vl" / "ocr"
CATALOG_PATH = Path(__file__).resolve().parents[1] / "packages/xian-vl/src/xian/ocr/catalog.json"


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(url: str, dest: Path) -> None:
    """Fetch to a ``.part`` file and rename only once it is complete.

    The same discipline the runtime downloader uses, for the same reason: a
    truncated model file does not raise, it segfaults inside the ONNX Runtime
    session two steps later.
    """
    part = dest.with_suffix(dest.suffix + ".part")
    print(f"  fetching {url}")
    with urllib.request.urlopen(url, timeout=120) as response, part.open("wb") as out:
        shutil.copyfileobj(response, out)
    part.replace(dest)


def export_one(model_id: str, spec: dict, out_root: Path, work: Path) -> dict:
    print(f"[{model_id}]")
    out_dir = out_root / model_id
    out_dir.mkdir(parents=True, exist_ok=True)

    tar_url = f"{BASE_URL}/{model_id}_infer.tar"
    tar_path = work / f"{model_id}_infer.tar"
    if not tar_path.exists():
        download(tar_url, tar_path)

    with tarfile.open(tar_path) as archive:
        archive.extractall(work, filter="data")
    src = work / f"{model_id}_infer"

    onnx_path = out_dir / "model.onnx"
    print("  converting to ONNX")
    result = subprocess.run(
        CONVERT_CMD + [
            "--model_dir", str(src),
            "--model_filename", "inference.json",
            "--params_filename", "inference.pdiparams",
            "--save_file", str(onnx_path),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not onnx_path.exists():
        raise RuntimeError(f"paddle2onnx failed for {model_id}:\n{result.stdout[-2000:]}\n{result.stderr[-2000:]}")

    entry = {
        "id": model_id,
        "role": spec["role"],
        "scripts": spec["scripts"],
        "quality": spec["quality"],
        "source_url": tar_url,
        "onnx": {"name": "model.onnx", "bytes": onnx_path.stat().st_size, "sha256": sha256_of(onnx_path)},
    }

    if spec["role"] == "rec":
        config = yaml.safe_load((src / "inference.yml").read_text(encoding="utf-8"))
        characters = config.get("PostProcess", {}).get("character_dict")
        if not characters:
            raise RuntimeError(f"{model_id}: inference.yml carries no PostProcess.character_dict")
        dict_path = out_dir / "dict.txt"
        # One character per line, no trailing strip: some entries *are* spaces,
        # and a dictionary off by one index decodes to convincing gibberish
        # rather than to an error.
        dict_path.write_text("\n".join(characters) + "\n", encoding="utf-8")
        entry["dict"] = {
            "name": "dict.txt",
            "bytes": dict_path.stat().st_size,
            "sha256": sha256_of(dict_path),
            "characters": len(characters),
        }
        shape = config.get("PreProcess", {}).get("transform_ops", [])
        for op in shape:
            if "RecResizeImg" in op:
                entry["input_shape"] = op["RecResizeImg"]["image_shape"]

    print(f"  ok — {entry['onnx']['bytes'] / 1e6:.1f} MB")
    return entry


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", action="append", help="export just this model id (repeatable)")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="where the exported models land")
    parser.add_argument("--catalog", type=Path, default=CATALOG_PATH, help="manifest to write")
    args = parser.parse_args()

    wanted = args.only or list(MODELS)
    unknown = [m for m in wanted if m not in MODELS]
    if unknown:
        parser.error(f"unknown model(s): {', '.join(unknown)}")

    catalog: dict[str, dict] = {}
    if args.catalog.exists():
        catalog = json.loads(args.catalog.read_text(encoding="utf-8")).get("models", {})

    failed: list[str] = []
    with tempfile.TemporaryDirectory(prefix="ppocr-export-") as tmp:
        work = Path(tmp)
        for model_id in wanted:
            try:
                catalog[model_id] = export_one(model_id, MODELS[model_id], args.out, work)
            except Exception as exc:  # one bad model must not lose the others
                print(f"  FAILED: {exc}", file=sys.stderr)
                failed.append(model_id)

    args.catalog.parent.mkdir(parents=True, exist_ok=True)
    args.catalog.write_text(
        json.dumps({"base_url": BASE_URL, "models": dict(sorted(catalog.items()))}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"\nwrote {args.catalog} — {len(catalog)} model(s)")
    if failed:
        print(f"failed: {', '.join(failed)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
