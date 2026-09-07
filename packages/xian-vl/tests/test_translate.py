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

"""Per-line translation through the pinned Hy-MT2 model."""

import asyncio
from types import SimpleNamespace

import pytest

from xian.translate import (
    BATCH_SEPARATOR,
    TRANSLATION_MODEL,
    LineTranslator,
    TranslationModelUnavailable,
    build_translation_prompt,
)


class FakeCompletions:
    """Records every request and answers from a scripted table."""

    def __init__(self, answers=None, fail=False):
        self.answers = answers or {}
        self.fail = fail
        self.requests = []
        self.concurrent = 0
        self.peak_concurrent = 0

    async def create(self, *, model, messages, **kwargs):
        self.concurrent += 1
        self.peak_concurrent = max(self.peak_concurrent, self.concurrent)
        try:
            self.requests.append({"model": model, "messages": messages})
            await asyncio.sleep(0)
            if self.fail:
                raise RuntimeError("backend refused")
            prompt = messages[-1]["content"]
            body = prompt.split(":\n", 1)[1]
            answer = self.answers.get(body, f"[{body}]")
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=answer))])
        finally:
            self.concurrent -= 1


def fake_processor(answers=None, *, installed=(TRANSLATION_MODEL,), fail=False, routed="Some-Chat-Model"):
    completions = FakeCompletions(answers, fail=fail)
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    processor = SimpleNamespace(
        client=client,
        router=SimpleNamespace(downloaded_model_ids=list(installed)),
        get_translation_model_name=lambda: routed,
    )
    return processor, completions


# ── the prompt ───────────────────────────────────────────────────────

def test_the_prompt_is_one_bare_user_turn():
    """Hy-MT2 translates instructions rather than following them.

    Anything resembling a system prompt comes back translated into the target
    language and painted onto the screen.
    """
    processor, completions = fake_processor()
    translator = LineTranslator(processor=processor)

    asyncio.run(translator.translate_lines(["门"], "Chinese", "English"))

    messages = completions.requests[0]["messages"]
    assert len(messages) == 1
    assert messages[0]["role"] == "user"


def test_the_prompt_names_the_source_language():
    """One short line is often too little to tell Chinese from Japanese."""
    assert "from Chinese into English" in build_translation_prompt("门", "Chinese", "English")


def test_an_automatic_source_language_is_left_out():
    prompt = build_translation_prompt("门", "auto", "English")

    assert "auto" not in prompt
    assert "into English" in prompt


# ── the fan-out ──────────────────────────────────────────────────────

def test_every_line_gets_its_own_request():
    processor, completions = fake_processor({"一": "one", "二": "two", "三": "three"})
    translator = LineTranslator(processor=processor)

    result = asyncio.run(translator.translate_lines(["一", "二", "三"], "Chinese", "English"))

    assert result == ["one", "two", "three"]
    assert len(completions.requests) == 3


def test_results_come_back_in_the_caller_s_order():
    """They are gathered concurrently; the overlay indexes them positionally."""
    processor, _ = fake_processor({"a": "A", "b": "B", "c": "C"})
    translator = LineTranslator(processor=processor)

    assert asyncio.run(translator.translate_lines(["c", "a", "b"], "zh", "en")) == ["C", "A", "B"]


def test_concurrency_is_bounded():
    """A screen of thirty lines must not open thirty sockets at once."""
    processor, completions = fake_processor()
    translator = LineTranslator(processor=processor, concurrency=4)

    asyncio.run(translator.translate_lines([str(index) for index in range(20)], "zh", "en"))

    assert completions.peak_concurrent <= 4


def test_nothing_to_translate_makes_no_requests():
    processor, completions = fake_processor()

    assert asyncio.run(LineTranslator(processor=processor).translate_lines([], "zh", "en")) == []
    assert completions.requests == []


def test_a_blank_line_is_passed_through_untouched():
    processor, completions = fake_processor()

    result = asyncio.run(LineTranslator(processor=processor).translate_lines(["  "], "zh", "en"))

    assert result == ["  "]
    assert completions.requests == []


# ── failure ──────────────────────────────────────────────────────────

def test_a_failed_line_falls_back_to_its_source():
    """A blank overlay box over live text is worse than the original text."""
    processor, _ = fake_processor(fail=True)

    result = asyncio.run(LineTranslator(processor=processor).translate_lines(["门"], "zh", "en"))

    assert result == ["门"]


def test_a_failed_line_is_not_cached():
    """Caching a failure would make it permanent for the rest of the session."""
    processor, _ = fake_processor(fail=True)
    translator = LineTranslator(processor=processor)

    asyncio.run(translator.translate_lines(["门"], "zh", "en"))

    assert len(translator.cache) == 0


# ── the cache ────────────────────────────────────────────────────────

def test_a_repeated_line_is_not_requested_twice():
    processor, completions = fake_processor({"门": "door"})
    translator = LineTranslator(processor=processor)

    asyncio.run(translator.translate_lines(["门"], "zh", "en"))
    result = asyncio.run(translator.translate_lines(["门"], "zh", "en"))

    assert result == ["door"]
    assert len(completions.requests) == 1


def test_only_the_uncached_lines_are_requested():
    processor, completions = fake_processor({"门": "door", "窗": "window"})
    translator = LineTranslator(processor=processor)

    asyncio.run(translator.translate_lines(["门"], "zh", "en"))
    completions.requests.clear()
    result = asyncio.run(translator.translate_lines(["门", "窗"], "zh", "en"))

    assert result == ["door", "window"]
    assert len(completions.requests) == 1


# ── model resolution ─────────────────────────────────────────────────

def test_the_pinned_model_is_used():
    processor, completions = fake_processor()

    asyncio.run(LineTranslator(processor=processor).translate_lines(["门"], "zh", "en"))

    assert completions.requests[0]["model"] == TRANSLATION_MODEL


def test_a_missing_model_fails_with_something_actionable():
    """Quietly using a different model turns into a quality bug report."""
    processor, _ = fake_processor(installed=["Some-Chat-Model"])

    with pytest.raises(TranslationModelUnavailable) as caught:
        asyncio.run(LineTranslator(processor=processor).translate_lines(["门"], "zh", "en"))

    assert TRANSLATION_MODEL in str(caught.value)


def test_the_fallback_is_opt_in():
    processor, completions = fake_processor(installed=["Some-Chat-Model"], routed="Some-Chat-Model")
    translator = LineTranslator(processor=processor, allow_fallback=True)

    asyncio.run(translator.translate_lines(["门"], "zh", "en"))

    assert completions.requests[0]["model"] == "Some-Chat-Model"


def test_an_undiscovered_server_is_not_treated_as_a_missing_model():
    """An empty model list means discovery has not run yet, not that the
    model is absent — failing there breaks a first tick that would work."""
    processor, completions = fake_processor(installed=[])

    asyncio.run(LineTranslator(processor=processor).translate_lines(["门"], "zh", "en"))

    assert completions.requests[0]["model"] == TRANSLATION_MODEL


# ── glossary ─────────────────────────────────────────────────────────

def test_the_glossary_is_enforced_on_the_output():
    """Hy-MT2 takes no system prompt, so term consistency cannot be asked for."""
    processor, _ = fake_processor({"李云": "Li Yun the swordsman"})
    translator = LineTranslator(processor=processor, glossary={"Li Yun": "Cloud Li"})

    result = asyncio.run(translator.translate_lines(["李云"], "zh", "en"))

    assert result == ["Cloud Li the swordsman"]


def test_a_longer_glossary_term_wins_over_a_shorter_one():
    processor, _ = fake_processor({"x": "Jade Sword Sect"})
    translator = LineTranslator(
        processor=processor,
        glossary={"Jade Sword": "Bibao", "Jade Sword Sect": "Bibao Clan"},
    )

    assert asyncio.run(translator.translate_lines(["x"], "zh", "en")) == ["Bibao Clan"]


# ── the batched fallback ─────────────────────────────────────────────

def test_the_batched_path_sends_one_request():
    """Kept for a backend that will not serve the fan-out concurrently."""
    joined = BATCH_SEPARATOR.join(["一", "二"])
    processor, completions = fake_processor({joined: BATCH_SEPARATOR.join(["one", "two"])})
    translator = LineTranslator(processor=processor, batched=True)

    result = asyncio.run(translator.translate_lines(["一", "二"], "zh", "en"))

    assert result == ["one", "two"]
    assert len(completions.requests) == 1


def test_a_batch_that_loses_a_separator_falls_back_whole():
    """Index-mapped splitting misaligns every line after a dropped separator,
    which paints confident, wrong translations over live text."""
    joined = BATCH_SEPARATOR.join(["一", "二", "三"])
    processor, _ = fake_processor({joined: BATCH_SEPARATOR.join(["one", "two"])})
    translator = LineTranslator(processor=processor, batched=True)

    assert asyncio.run(translator.translate_lines(["一", "二", "三"], "zh", "en")) == ["一", "二", "三"]
