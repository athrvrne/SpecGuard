"""Provider tests. No live model is ever called.

Both providers are exercised against a fake transport so the request shape and
the response extraction are pinned without a network round trip or an API key.
"""

import pytest

from specguard.llm.claude import ClaudeProvider
from specguard.llm.ollama import OllamaProvider
from specguard.llm.provider import LLMProvider


# --- fakes ------------------------------------------------------------------


class _Block:
    def __init__(self, type_, text=""):
        self.type = type_
        self.text = text


class _Response:
    def __init__(self, content, stop_reason="end_turn"):
        self.content = content
        self.stop_reason = stop_reason


class FakeMessages:
    def __init__(self, response):
        self.response = response
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return self.response


class FakeAnthropic:
    def __init__(self, response):
        self.messages = FakeMessages(response)


def claude(response) -> tuple[ClaudeProvider, FakeAnthropic]:
    client = FakeAnthropic(response)
    return ClaudeProvider(client=client), client


# --- Claude -----------------------------------------------------------------


def test_claude_satisfies_the_provider_protocol():
    provider, _ = claude(_Response([_Block("text", "[]")]))
    assert isinstance(provider, LLMProvider)


def test_claude_defaults_to_the_current_opus_model():
    provider, client = claude(_Response([_Block("text", "[]")]))
    provider.complete("sys", "user")

    assert client.messages.kwargs["model"] == "claude-opus-5"


def test_claude_sends_the_system_prompt_separately_from_the_user_turn():
    provider, client = claude(_Response([_Block("text", "[]")]))
    provider.complete("you are a test engineer", "endpoint: GET /pets")

    assert client.messages.kwargs["system"] == "you are a test engineer"
    assert client.messages.kwargs["messages"] == [
        {"role": "user", "content": "endpoint: GET /pets"}
    ]


def test_claude_sends_no_sampling_parameters():
    # temperature / top_p / top_k are rejected outright on this model family.
    provider, client = claude(_Response([_Block("text", "[]")]))
    provider.complete("sys", "user")

    assert not {"temperature", "top_p", "top_k"} & set(client.messages.kwargs)


def test_claude_joins_only_the_text_blocks():
    response = _Response([_Block("thinking"), _Block("text", "[1,"), _Block("text", "2]")])
    provider, _ = claude(response)

    assert provider.complete("sys", "user") == "[1,2]"


def test_claude_returns_empty_on_a_refusal_rather_than_indexing_into_content():
    provider, _ = claude(_Response([], stop_reason="refusal"))
    assert provider.complete("sys", "user") == ""


def test_claude_max_tokens_leaves_room_for_thinking():
    # Thinking is on by default on this model and max_tokens caps thinking plus
    # response together, so a tight budget truncates the JSON mid-array.
    provider, client = claude(_Response([_Block("text", "[]")]))
    provider.complete("sys", "user")

    assert client.messages.kwargs["max_tokens"] >= 16000


def test_claude_model_is_overridable():
    client = FakeAnthropic(_Response([_Block("text", "[]")]))
    ClaudeProvider(client=client, model="claude-sonnet-5").complete("sys", "user")

    assert client.messages.kwargs["model"] == "claude-sonnet-5"


# --- Ollama -----------------------------------------------------------------


class FakePost:
    def __init__(self, payload):
        self.payload = payload
        self.url = None
        self.json_body = None

    def __call__(self, url, json=None, timeout=None):
        self.url = url
        self.json_body = json
        return FakeHTTPResponse(self.payload)


class FakeHTTPResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_ollama_satisfies_the_provider_protocol():
    assert isinstance(OllamaProvider(post=FakePost({})), LLMProvider)


def test_ollama_posts_to_the_local_chat_endpoint():
    post = FakePost({"message": {"content": "[]"}})
    OllamaProvider(post=post).complete("sys", "user")

    assert post.url == "http://localhost:11434/api/chat"


def test_ollama_sends_system_and_user_as_separate_messages():
    post = FakePost({"message": {"content": "[]"}})
    OllamaProvider(post=post).complete("sys", "user")

    assert post.json_body["messages"] == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "user"},
    ]


def test_ollama_does_not_stream():
    post = FakePost({"message": {"content": "[]"}})
    OllamaProvider(post=post).complete("sys", "user")

    assert post.json_body["stream"] is False


def test_ollama_returns_the_message_content():
    post = FakePost({"message": {"content": "[{}]"}})
    assert OllamaProvider(post=post).complete("sys", "user") == "[{}]"


def test_ollama_returns_empty_on_an_unexpected_payload():
    assert OllamaProvider(post=FakePost({"error": "model not found"})).complete("s", "u") == ""


def test_ollama_host_is_overridable():
    post = FakePost({"message": {"content": "[]"}})
    OllamaProvider(host="http://gpu-box:11434", post=post).complete("sys", "user")

    assert post.url == "http://gpu-box:11434/api/chat"


# --- construction -----------------------------------------------------------


def test_get_provider_returns_the_named_implementation():
    from specguard.llm import get_provider

    assert isinstance(get_provider("ollama"), OllamaProvider)


def test_get_provider_returns_none_when_no_model_is_wanted():
    from specguard.llm import get_provider

    assert get_provider(None) is None
    assert get_provider("none") is None


def test_an_unknown_provider_name_is_rejected():
    from specguard.llm import get_provider

    with pytest.raises(ValueError, match="claude"):
        get_provider("gpt")
