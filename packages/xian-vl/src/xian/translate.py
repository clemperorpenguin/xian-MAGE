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

"""Line translation through Hy-MT2.

The OCR pipeline's other half.  Once a local reader supplies text and boxes,
the network is only asked to translate — no geometry, no JSON schema, no
instruction-following — which is a far lower bar and is why a 1.8B model is
enough for it.

Two things about Hy-MT2 shape this whole module:

* **It is a machine-translation model, so it gets no system prompt.**  Told to
  "translate to English, keeping proper nouns consistent", it translates that
  sentence.  The request is a bare user turn and nothing else.

* **Which means the glossary cannot ride along in the prompt**, the way it does
  on the grounding path.  Term consistency is instead handled deterministically
  here — substituted into the source before the call and enforced on the way
  back — and by the cache, which makes a recurring name translate once.  What
  is genuinely lost is cross-line context: a pronoun the previous line resolved
  will not be resolved here.  That is the price of the architecture and it is
  documented rather than hidden.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field

from xian.translation_cache import TranslationCache

logger = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_CONCURRENCY",
    "LineTranslator",
    "TRANSLATION_MODEL",
    "TranslationModelUnavailable",
    "build_translation_prompt",
]

#: The pinned line translator.  A specific model rather than a routed one: the
#: prompt shape, the absence of a system turn and the per-line fan-out are all
#: tuned to this model's behaviour, and silently running them against whatever
#: the router picked would produce quality problems that look like OCR problems.
TRANSLATION_MODEL = "Hy-MT2-1.8B-GGUF-Q4_K_M"

#: In-flight requests.  Local serving may or may not parallelise; see
#: ``batched`` below for what happens when it does not.
DEFAULT_CONCURRENCY = 8

#: Separator for the batched fallback path.  Long and punctuation-heavy so no
#: translator rewrites it and no source text contains it.
BATCH_SEPARATOR = "\n##|||##\n"


class TranslationModelUnavailable(RuntimeError):
    """The pinned translation model is not installed on the server."""


def build_translation_prompt(text: str, source_lang: str, target_lang: str) -> str:
    """The entire request.  One turn, no system prompt, no instructions.

    Naming the source language is worth the tokens even when the model can
    detect it: a single recognized line is often too short to disambiguate
    Chinese from Japanese, and the wrong guess produces confident nonsense.
    """
    source = (source_lang or "").strip()
    if not source or source.lower() in ("auto", "detect", "automatic"):
        return f"Translate the following into {target_lang}:\n{text}"
    return f"Translate the following from {source} into {target_lang}:\n{text}"


@dataclass
class LineTranslator:
    """Translates recognized lines, cache-first, one request per line.

    Holds the cache, so a translator that lives as long as a live session
    accumulates hits across it.
    """

    processor: object
    model: str = TRANSLATION_MODEL
    concurrency: int = DEFAULT_CONCURRENCY
    #: Fall back to the router's choice when the pin is missing.  Off by
    #: default: a quiet substitution is how a user ends up debugging
    #: translation quality that has nothing to do with the model they think
    #: they are running.
    allow_fallback: bool = False
    #: One request carrying every line, split on a separator.  Kept because
    #: the fan-out's advantage depends on the server actually serving
    #: concurrently, which a single-slot backend does not; see the plan's
    #: risk 4.  Off by default.
    batched: bool = False
    cache: TranslationCache = field(default_factory=TranslationCache)
    glossary: dict[str, str] = field(default_factory=dict)
    max_tokens: int = 512

    _semaphore: asyncio.Semaphore | None = field(default=None, init=False, repr=False)
    _resolved: str | None = field(default=None, init=False, repr=False)

    # ── model resolution ─────────────────────────────────────────────

    def resolve_model(self) -> str:
        """The model id to send to, or an error that says what to install."""
        if self._resolved is not None:
            return self._resolved

        router = getattr(self.processor, "router", None)
        installed = list(getattr(router, "downloaded_model_ids", []) or []) if router else []

        if not installed or self.model in installed:
            # An empty list means discovery has not run, not that the model is
            # absent; failing there would break a first tick that would have
            # worked.
            self._resolved = self.model
            return self._resolved

        if self.allow_fallback and hasattr(self.processor, "get_translation_model_name"):
            fallback = self.processor.get_translation_model_name()
            logger.warning("%s is not installed; falling back to %s", self.model, fallback)
            self._resolved = fallback
            return self._resolved

        raise TranslationModelUnavailable(
            f"{self.model} is not installed on the server. "
            f"Install it from Settings, or run: lemonade-server pull {self.model}"
        )

    # ── glossary ─────────────────────────────────────────────────────

    def _apply_glossary(self, text: str) -> str:
        """Rewrite known terms in the *output*.

        Applied after translation rather than before: substituting into the
        source hands the model a target-language token mid-sentence, which it
        then dutifully translates back.  Longest term first, so a two-word
        entry is not half-matched by a one-word one.
        """
        if not self.glossary:
            return text
        for source_term, target_term in sorted(self.glossary.items(), key=lambda item: -len(item[0])):
            if not source_term or not target_term:
                continue
            text = re.sub(re.escape(source_term), target_term, text, flags=re.IGNORECASE)
        return text

    # ── requests ─────────────────────────────────────────────────────

    async def _complete(self, prompt: str) -> str:
        client = self.processor.client
        response = await client.chat.completions.create(
            model=self.resolve_model(),
            messages=[{"role": "user", "content": prompt}],
            max_tokens=self.max_tokens,
            temperature=0.0,
        )
        return (response.choices[0].message.content or "").strip()

    async def _translate_one(self, text: str, source_lang: str, target_lang: str) -> str:
        async with self._semaphore:
            try:
                raw = await self._complete(build_translation_prompt(text, source_lang, target_lang))
            except TranslationModelUnavailable:
                # A configuration problem, not a transient one: it is the same
                # for every line and the user has to act on it.
                raise
            except Exception as exc:
                logger.warning("translation failed for %r: %s", text[:40], exc)
                return text  # the source is a better overlay than a blank one
        return self._apply_glossary(raw) or text

    async def _translate_batched(self, texts: list[str], source_lang: str, target_lang: str) -> list[str]:
        """One request for every line, split back by separator.

        Index-mapped, so a dropped separator misaligns everything after it —
        which is why the length is checked and the whole batch falls back to
        the source rather than painting shifted translations.
        """
        joined = BATCH_SEPARATOR.join(texts)
        try:
            raw = await self._complete(build_translation_prompt(joined, source_lang, target_lang))
        except Exception as exc:
            logger.warning("batched translation failed: %s", exc)
            return list(texts)

        parts = [part.strip() for part in raw.split(BATCH_SEPARATOR.strip())]
        if len(parts) != len(texts):
            logger.warning("batched translation returned %d parts for %d lines", len(parts), len(texts))
            return list(texts)
        return [self._apply_glossary(part) or original for part, original in zip(parts, texts)]

    async def translate_lines(self, texts: list[str], source_lang: str, target_lang: str) -> list[str]:
        """Translate every line, returning one result per input in order."""
        if not texts:
            return []

        results: list[str | None] = [None] * len(texts)
        pending: list[int] = []
        for index, text in enumerate(texts):
            if not text.strip():
                results[index] = text
                continue
            cached = self.cache.get(text, source_lang, target_lang)
            if cached is not None:
                results[index] = cached
            else:
                pending.append(index)

        if pending:
            # Up front, and outside the per-line error handling: a missing
            # model is the same answer for every line, and letting it fall
            # through the fan-out's fallback turns a fixable configuration
            # error into a screen of untranslated text with a warning in a log
            # nobody is reading.
            self.resolve_model()

            if self._semaphore is None:
                self._semaphore = asyncio.Semaphore(self.concurrency)

            missing = [texts[index] for index in pending]
            if self.batched:
                translated = await self._translate_batched(missing, source_lang, target_lang)
            else:
                translated = await asyncio.gather(
                    *(self._translate_one(text, source_lang, target_lang) for text in missing)
                )

            for index, translation in zip(pending, translated):
                results[index] = translation
                if translation != texts[index]:
                    # A result identical to its source is either an untranslated
                    # failure or a proper noun; caching it would make a failure
                    # permanent for the rest of the session.
                    self.cache.put(texts[index], source_lang, target_lang, translation)

        return [result if result is not None else text for result, text in zip(results, texts)]
