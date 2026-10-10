"""Talking to models: message shape, errors, rate limits and overload."""

import asyncio
import itertools
from types import SimpleNamespace
from typing import ClassVar

import httpx
import openai
import pytest

from coach import backends, llm
from coach.llm import conversation, retry_after

FLASH = llm.Endpoint(llm._client("https://model.test", "key"), "flash", {})  # never called
SYS = {"role": "system", "content": "sys"}
ASSISTANT = {"role": "assistant", "content": "Tell me about yourself."}
USER = {"role": "user", "content": "I built a payment service."}


def alternates(messages):
    body = [m["role"] for m in messages if m["role"] != "system"]
    return body[0] == "user" and all(a != b for a, b in itertools.pairwise(body))


@pytest.mark.parametrize(
    "messages",
    [
        [SYS, ASSISTANT, USER],  # the partner opened
        [SYS, USER, ASSISTANT, USER],  # already fine
        [SYS, USER, USER],  # two of ours in a row
        [SYS, ASSISTANT, USER, ASSISTANT, USER],  # rebuilt from the database
    ],
)
def test_messages_alternate_for_local_chat_templates(messages):
    """LM Studio's jinja templates reject anything but strict alternation."""
    assert alternates(conversation(messages))


def test_the_partners_opening_is_kept_not_dropped():
    sent = conversation([SYS, ASSISTANT, USER])
    assert any(ASSISTANT["content"] in str(m.get("content")) for m in sent)


def test_one_system_message():
    assert len([m for m in conversation([SYS, SYS, USER]) if m["role"] == "system"]) == 1


def test_an_error_reads_as_the_servers_words_not_the_sdks_wrapper():
    class RejectedError(Exception):
        body: ClassVar = [{"error": {"message": "No models loaded."}}]

    said = asyncio.run(llm.explain(FLASH, RejectedError("Error code: 400")))
    assert said == "flash: No models loaded."


@pytest.mark.parametrize(
    ("message", "seconds"),
    [
        ("Please retry in 33.876060542s.", 33.876060542),
        ("Please retry in 3h35m42.5s.", 3 * 3600 + 35 * 60 + 42.5),
        ("Please retry in 2m.", 120),
        ("no hint", None),
    ],
)
def test_retry_after(message, seconds):
    assert retry_after(message) == seconds


def test_an_overloaded_model_is_waited_out_and_said_so(monkeypatch):
    """A 503, "high demand", passes: wait it out. The study sheet was once lost to one."""
    waits: list[str] = []

    async def overloaded_once(_ep, _messages, _max_tokens=None):
        if not waits:
            response = httpx.Response(503, request=httpx.Request("POST", "http://model"))
            raise openai.InternalServerError("high demand", response=response, body=None)
        return llm.Reply("fine", 1.0)

    async def no_wait(_seconds):
        waits.append(llm.waiting)

    monkeypatch.setattr(llm, "complete", overloaded_once)
    monkeypatch.setattr(asyncio, "sleep", no_wait)
    reply = asyncio.run(llm.patiently(FLASH, []))
    assert reply.text == "fine"
    assert waits == ["flash is busy, trying again in 30s"]
    assert llm.waiting == "", "cleared once it is past"


def test_a_daily_quota_is_reported_not_waited_for(monkeypatch):
    async def used_up(_ep, _messages, _max_tokens=None):
        response = httpx.Response(429, request=httpx.Request("POST", "http://model"))
        raise openai.RateLimitError("Please retry in 3h2m.", response=response, body=None)

    monkeypatch.setattr(llm, "complete", used_up)
    with pytest.raises(RuntimeError, match="used up its free requests"):
        asyncio.run(llm.patiently(FLASH, []))


def test_a_spent_budget_is_written_by_a_local_model_instead(monkeypatch):
    """A spending cap says no "retry in": it was waited on for three minutes, then lost the
    study sheet. A model LM Studio is serving writes it instead, at once."""
    asked: list[str] = []

    async def capped(ep, _messages, _max_tokens=None):
        asked.append(ep.model)
        if ep.model == "flash":
            response = httpx.Response(429, request=httpx.Request("POST", "http://model"))
            message = "Your billing account has exceeded its monthly spending cap"
            raise openai.RateLimitError(message, response=response, body=None)
        return llm.Reply("written here", 1.0)

    async def never(_seconds):
        raise AssertionError("a spent budget is not waited for")

    monkeypatch.setattr(llm, "complete", capped)
    monkeypatch.setattr(asyncio, "sleep", never)
    loaded = {"liquid/lfm2.5-1.2b", "google/gemma-4-e4b", "prism-ml/bonsai-27b"}
    monkeypatch.setattr(backends, "lm_studio_models", lambda _timeout=1.5: loaded)
    assert asyncio.run(llm.patiently(FLASH, [])).text == "written here"
    assert asked == ["flash", "prism-ml/bonsai-27b"], "an analysis model, not the weakest"


def test_without_lm_studio_a_spent_budget_says_so(monkeypatch):
    async def capped(_ep, _messages, _max_tokens=None):
        response = httpx.Response(429, request=httpx.Request("POST", "http://model"))
        raise openai.RateLimitError("exceeded its spending cap", response=response, body=None)

    monkeypatch.setattr(llm, "complete", capped)
    with pytest.raises(RuntimeError, match="run out of quota or budget"):
        asyncio.run(llm.patiently(FLASH, []))


def test_a_client_is_built_without_an_api_key():
    """The pages that tell you to add a key must load before you have one."""
    assert llm._client("https://model.test", "").api_key


def test_a_client_is_kept_per_server_and_key_and_closed_on_shutdown():
    """Each holds a connection pool: one per call left them all open."""
    first = llm._client("https://model.test", "key")
    assert llm._client("https://model.test", "key") is first
    assert llm._client("https://model.test", "other") is not first  # an edited key
    asyncio.run(llm.close())
    assert first.is_closed()
    assert llm._client("https://model.test", "key") is not first


def test_a_reply_is_spoken_in_whole_sentences_never_cut_at_a_comma(monkeypatch):
    """Cutting the first sentence at its first comma got the first sound out 0.8s sooner,
    but Kokoro voices each piece as its own utterance: the partner audibly stopped
    mid-sentence, then started again, in 21 of 26 replies of a real session."""
    tokens = ["Oh, nice", " one, getting home", " so early. What", " did you do after?"]

    async def streamed():
        for token in tokens[1:]:
            yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=token))])

    async def first_words(_ep, _messages, _max_tokens):
        return streamed(), tokens[0]

    async def spoken():
        return [c async for kind, c in llm.stream_sentences(FLASH, []) if kind == "sentence"]

    monkeypatch.setattr(llm, "_first_words", first_words)
    assert asyncio.run(spoken()) == [
        "Oh, nice one, getting home so early.",
        "What did you do after?",
    ]
