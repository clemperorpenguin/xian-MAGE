#!/usr/bin/env python3
# Xian-VL Scripts — Development and automation scripts.
# Copyright (C) 2026  Clementine Pendragon <clem@pendragon.systems>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

import hashlib
import json
import logging
import sys
from pathlib import Path
import urllib.request
import urllib.error

from PyQt6.QtCore import QSettings

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

# Resolved in main(); module import must not touch the network (importing this
# module, or running --help, would otherwise probe the Lemonade server).
LEMONADE_URL = ""
MODEL = ""

#: The translator.  Pinned: see get_lemonade_config.
MODEL_ID = "Hy-MT2-7B-GGUF-Q4_K_M"

def get_lemonade_config():
    """The server to talk to, and the model to talk to it with.

    The model is pinned rather than read from settings.  Everything below is
    written against Hy-MT2's published instruction formats, and a general chat
    model asked the same questions answers them in prose that lands in a
    locale file.  The 7B rather than the 1.8B because this is an offline batch
    job where quality is the only axis that matters — nobody is waiting on a
    tick.
    """
    settings = QSettings("Xian", "VideoGameTranslator")
    api_url = settings.value("api_url", "http://localhost:13305/v1")

    if not api_url.endswith("/chat/completions"):
        if not api_url.endswith("/"):
            api_url += "/"
        api_url += "chat/completions"

    return api_url, MODEL_ID


TARGET_LANGUAGES = {
    "zh": "Chinese",
    "ja": "Japanese",
    "ko": "Korean",
    "ru": "Russian",
    "es": "Spanish",
    "ar": "Arabic",
    "hi": "Hindi",
    "vi": "Vietnamese"
}

# One string per request.  Hy-MT2 is a machine-translation model: asked for a
# JSON object of many keys it translates the request itself, so there is no
# batching to tune here — only how many of these single requests are in flight.
MAX_IN_FLIGHT = 8
MAX_RETRIES = 3


def _source_digest(entry) -> str:
    """Fingerprint the English text a translation was produced from."""
    value = entry.get("value", "") if isinstance(entry, dict) else str(entry)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _digest_path(locales_dir: Path, lang_code: str) -> Path:
    return locales_dir / f"{lang_code}.source-hash.json"


def _load_digests(locales_dir: Path, lang_code: str) -> dict:
    path = _digest_path(locales_dir, lang_code)
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _stale_keys(en_data: dict, existing: dict, digests: dict) -> dict:
    """Keys that are missing a translation, or whose English source changed.

    Without the digest sidecar an edited English string would keep its stale
    translation forever, because the key itself is still present.
    """
    out = {}
    for key, entry in en_data.items():
        if key not in existing:
            out[key] = entry
        elif digests.get(key) not in (None, _source_digest(entry)):
            out[key] = entry
    return out


#: Hy-MT2's published default instruction format.
DEFAULT_TEMPLATE = (
    "Translate the following text into {target_lang}. Note that you should only output "
    "the translated result without any additional explanation:\n\n{source_text}"
)

#: Its background-information format.  en.json carries a `context` line for
#: every string saying where it is used, which is exactly what this slot is
#: for: "Open" on a button and "Open" as a status word want different words in
#: most languages, and the context is the only thing that distinguishes them.
CONTEXT_TEMPLATE = (
    "[Background Information]\n{background_text}\n\n"
    "Please translate the following text into {target_lang}, taking the provided "
    "background information into consideration.\n\n"
    "[Source Text]\n{source_text}"
)


def build_prompt(entry, target_lang_name: str) -> str:
    """One user turn, in the model's own format.

    No system prompt: an MT model translates instructions rather than
    following them, so anything put there comes back as part of the string.
    """
    if isinstance(entry, dict):
        value = entry.get("value", "")
        context = (entry.get("context") or "").strip()
    else:
        value, context = str(entry), ""

    if context:
        return CONTEXT_TEMPLATE.format(
            background_text=context, target_lang=target_lang_name, source_text=value
        )
    return DEFAULT_TEMPLATE.format(target_lang=target_lang_name, source_text=value)


def _translate_one(entry, target_lang_name: str) -> str:
    """Translate a single UI string, returning the model's bare output."""
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": build_prompt(entry, target_lang_name)}],
        "temperature": 0.0,
        "max_tokens": 512,
    }

    req = urllib.request.Request(
        LEMONADE_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )

    with urllib.request.urlopen(req, timeout=120.0) as response:
        result = json.loads(response.read().decode("utf-8"))
        return (result["choices"][0]["message"]["content"] or "").strip()


def _translate_with_retries(key: str, entry, target_lang_name: str) -> tuple[str, str | None]:
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            text = _translate_one(entry, target_lang_name)
            if text:
                return key, text
            logging.error("  %s attempt %d — empty translation", key, attempt)
        except urllib.error.URLError as e:
            logging.error("  %s attempt %d — connection error: %s", key, attempt, e)
        except (KeyError, json.JSONDecodeError) as e:
            logging.error("  %s attempt %d — unreadable response: %s", key, attempt, e)
        except Exception as e:
            logging.error("  %s attempt %d — unexpected error: %s", key, attempt, e)
    logging.warning("  %s FAILED after %d attempts — leaving it untranslated", key, MAX_RETRIES)
    return key, None


def translate_strings(en_data: dict, target_lang_name: str) -> dict:
    """Translate every entry, a request at a time, several at once.

    A key that fails is left out rather than guessed at: the runtime falls
    back to the English string, which is a worse experience than a
    translation and a much better one than a wrong translation nobody knows
    is wrong.
    """
    from concurrent.futures import ThreadPoolExecutor

    total = len(en_data)
    done = 0
    merged: dict = {}

    with ThreadPoolExecutor(max_workers=MAX_IN_FLIGHT) as pool:
        futures = [
            pool.submit(_translate_with_retries, key, entry, target_lang_name)
            for key, entry in en_data.items()
        ]
        for future in futures:
            key, text = future.result()
            done += 1
            if text:
                merged[key] = text
            if done % 25 == 0 or done == total:
                logging.info("  %d/%d translated", done, total)

    return merged


def main():
    global LEMONADE_URL, MODEL
    LEMONADE_URL, MODEL = get_lemonade_config()

    current_dir = Path(__file__).resolve().parent
    locales_dir = current_dir.parent.parent.parent / "shared-types" / "locales"
    en_path = locales_dir / "en.json"

    if not en_path.exists():
        logging.error("Source file not found: %s", en_path)
        sys.exit(1)

    with open(en_path, "r", encoding="utf-8") as f:
        en_data = json.load(f)

    target_langs = TARGET_LANGUAGES
    if len(sys.argv) > 1:
        lang_arg = sys.argv[1].lower()
        if lang_arg in TARGET_LANGUAGES:
            target_langs = {lang_arg: TARGET_LANGUAGES[lang_arg]}
        else:
            logging.error(
                "Unknown language code: %s. Valid codes are: %s",
                lang_arg, ", ".join(TARGET_LANGUAGES.keys()),
            )
            sys.exit(1)

    for lang_code, lang_name in target_langs.items():
        out_path = locales_dir / f"{lang_code}.json"
        logging.info("Generating translations for %s (%s)...", lang_name, lang_code)

        # Load existing translations so we only fill gaps / update changed keys
        existing: dict = {}
        if out_path.exists():
            try:
                with open(out_path, "r", encoding="utf-8") as f:
                    existing = json.load(f)
            except (json.JSONDecodeError, OSError):
                existing = {}

        digests = _load_digests(locales_dir, lang_code)
        keys_to_translate = _stale_keys(en_data, existing, digests)

        if not keys_to_translate:
            logging.info(
                "  All %d keys already translated — skipping %s.",
                len(en_data), lang_name,
            )
            continue

        logging.info(
            "  %d new/changed keys to translate (out of %d total).",
            len(keys_to_translate), len(en_data),
        )

        translated = translate_strings(keys_to_translate, lang_name)
        if translated:
            merged = {**existing, **translated}
            # Preserve the key order from en.json
            ordered = {k: merged[k] for k in en_data if k in merged}
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(ordered, f, ensure_ascii=False, indent=2)
                f.write("\n")

            # Record what each translation was made from, so a later edit to the
            # English string is detected as drift rather than silently kept.
            digests.update({k: _source_digest(en_data[k]) for k in translated if k in en_data})
            with open(_digest_path(locales_dir, lang_code), "w", encoding="utf-8") as f:
                json.dump({k: digests[k] for k in en_data if k in digests}, f, indent=2)
                f.write("\n")

            logging.info(
                "  Successfully wrote %s (%d/%d keys).",
                out_path, len(ordered), len(en_data),
            )
        else:
            logging.warning("  Skipped %s due to translation failure.", lang_name)

if __name__ == "__main__":
    main()
