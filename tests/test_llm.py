"""Talking to models: message shape, errors, rate limits and overload."""

import asyncio
import types

import httpx
import openai
import pytest

from coach import llm
from coach.llm import conversation, retry_after

SYS = {"role": "system", "content": "sys"}
ASSISTANT = {"role": "assistant", "content": "Tell me about yourself."}
USER = {"role": "user", "content": "I built a payment service."}


def alternates(messages):
    body = [m["role"] for m in messages if m["role"] != "system"]
    return body[0] == "user" and all(a != b for a, b in zip(body, body[1:], strict=False))


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
    assert any(ASSISTANT["content"] in m["content"] for m in conversation([SYS, ASSISTANT, USER]))


def test_one_system_message():
    assert len([m for m in conversation([SYS, SYS, USER]) if m["role"] == "system"]) == 1


def test_an_error_reads_as_the_servers_words_not_the_sdks_wrapper():
    class Rejected(Exception):
        body = [{"error": {"message": "No models loaded."}}]

    said = asyncio.run(llm.explain(llm.Endpoint(None, "m", {}), Rejected("Error code: 400")))
    assert said == "m: No models loaded."


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
    waits = []

    async def overloaded_once(_ep, _messages, _max_tokens=None):
        if not waits:
            response = httpx.Response(503, request=httpx.Request("POST", "http://model"))
            raise openai.InternalServerError("high demand", response=response, body=None)
        return llm.Reply("fine", 1.0)

    async def no_wait(_seconds):
        waits.append(llm.waiting)

    monkeypatch.setattr(llm, "complete", overloaded_once)
    monkeypatch.setattr(asyncio, "sleep", no_wait)
    reply = asyncio.run(llm.patiently(types.SimpleNamespace(model="flash"), []))
    assert reply.text == "fine" and waits == ["flash is busy, trying again in 30s"]
    assert llm.waiting == "", "cleared once it is past"


def test_a_daily_quota_is_reported_not_waited_for(monkeypatch):
    async def used_up(_ep, _messages, _max_tokens=None):
        response = httpx.Response(429, request=httpx.Request("POST", "http://model"))
        raise openai.RateLimitError("Please retry in 3h2m.", response=response, body=None)

    monkeypatch.setattr(llm, "complete", used_up)
    with pytest.raises(RuntimeError, match="used up its free requests"):
        asyncio.run(llm.patiently(types.SimpleNamespace(model="flash"), []))


def test_a_client_is_built_without_an_api_key():
    """The pages that tell you to add a key must load before you have one."""
    assert llm._client("https://model.test", "").api_key


def test_a_client_is_kept_per_server_and_key_and_closed_on_shutdown():
    """Each holds a connection pool: one per call left them all open."""
    first = llm._client("https://model.test", "key")
    assert llm._client("https://model.test", "key") is first
    assert llm._client("https://model.test", "other") is not first  # an edited key
    asyncio.run(llm.close())
    assert first.is_closed() and llm._client("https://model.test", "key") is not first
