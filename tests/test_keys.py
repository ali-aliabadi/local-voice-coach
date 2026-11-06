"""A pool of Gemini keys: a refused key rests and the request moves on to the next."""

import asyncio

import httpx
import openai
import pytest

from coach import keys, llm, settings, vault


def refused(kind=openai.RateLimitError, message="Please retry in 30s."):
    status = 429 if kind is openai.RateLimitError else 401
    response = httpx.Response(status, request=httpx.Request("POST", "http://model"))
    return kind(message, response=response, body=None)


def endpoint(key):
    return llm.Endpoint(llm._client("https://model.test", key), "flash", {})


A = "AIzaSy" + "a" * 33
B = "AIzaSy" + "b" * 33


def test_the_app_and_environment_make_one_pool_in_order(monkeypatch):
    vault.add_key(A)
    settings._store("gemini_api_key", f"{B}, c")  # the old Settings field still counts
    monkeypatch.setenv("GEMINI_API_KEYS", "c,d\ne")
    assert keys.pool() == [A, B, "c", "d", "e"]


def test_a_refused_key_hands_the_request_to_the_next(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEYS", "first,second")
    tried = []

    async def call(ep):
        tried.append(ep.client.api_key)
        if ep.client.api_key == "first":
            raise refused()
        return "answered"

    assert asyncio.run(keys.rotating(endpoint("first"), call)) == "answered"
    assert tried == ["first", "second"]
    assert keys.current() == "second"  # the first rests for the 30s it was told


@pytest.mark.parametrize("kind", [openai.AuthenticationError, openai.RateLimitError])
def test_with_every_key_resting_the_caller_sees_the_error(monkeypatch, kind):
    monkeypatch.setenv("GEMINI_API_KEYS", "first,second")

    async def call(_ep):
        raise refused(kind)

    with pytest.raises(kind):
        asyncio.run(keys.rotating(endpoint("first"), call))


def test_a_resting_key_is_not_tried_first(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEYS", "first,second")
    keys.rest("first", refused(message="Please retry in 3h."))
    used = []

    async def call(ep):
        used.append(ep.client.api_key)
        return "ok"

    asyncio.run(keys.rotating(endpoint("first"), call))
    assert used == ["second"]
    assert llm.endpoint_for(llm.backends.BY_KEY["flash-lite"]).client.api_key == "second"


def test_a_key_outside_the_pool_is_not_rotated(monkeypatch):
    """LM Studio's placeholder key, or one edited out of Settings mid-session."""
    monkeypatch.setenv("GEMINI_API_KEYS", "first,second")

    async def call(_ep):
        raise refused()

    with pytest.raises(openai.RateLimitError):
        asyncio.run(keys.rotating(endpoint("lm-studio"), call))
