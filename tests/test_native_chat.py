"""Offline checks for native Chat history, protocol and agent compatibility."""

import asyncio
import copy
import importlib
import json
from types import SimpleNamespace

import httpx
import pytest
from harbor.llms.base import ContextLengthExceededError, OutputLengthExceededError
from openai import BadRequestError

from swe_residual.run import agent_config
from swe_residual.tb21.agents import (
    FreshCleanTerminus,
    PracticalTerminus,
    _NativeChatAgent,
)
from swe_residual.tb21.model_api import (
    NativeDSV41Chat,
    NativeKimiChat,
)
from swe_residual.tb21.tb21_utils import FirstRequestGuard

ADAPTERS = [NativeKimiChat, NativeDSV41Chat]


def backend():
    return SimpleNamespace(
        _canonical_model_name="test-model",
        _temperature=1.0,
        _reasoning_effort="max",
        _api_base="https://example.invalid/v1",
        get_model_context_limit=lambda: 922000,
        get_model_output_limit=lambda: 16384,
    )


def response(finish_reason="stop", usage=True):
    message = {
        "role": "assistant",
        "content": "run a command",
        "reasoning_content": "this agent's own reasoning",
    }
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=message["content"],
                    model_dump=lambda **kwargs: dict(message),
                ),
                finish_reason=finish_reason,
            )
        ],
        model="test-model",
        usage=(
            SimpleNamespace(
                prompt_tokens=12,
                completion_tokens=7,
                prompt_tokens_details=SimpleNamespace(cached_tokens=3),
                completion_tokens_details=SimpleNamespace(reasoning_tokens=5),
            )
            if usage
            else None
        ),
    )


def adapter_with_client(adapter_type, reply=None, error=None):
    calls = []

    async def create(**kwargs):
        calls.append(copy.deepcopy(kwargs))
        if error is not None:
            raise error
        return reply if reply is not None else response()

    adapter = adapter_type(backend())
    adapter.client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )
    return adapter, calls


def call(adapter, prompt="task", history=None):
    return asyncio.run(
        adapter.call(
            prompt,
            message_history=history,
            api_key="offline-test-key",
            timeout=17,
            num_retries=1,
            previous_response_id="must-not-be-sent",
            max_output_tokens=99,
            store=True,
            include=["not-a-chat-parameter"],
        )
    )


@pytest.mark.parametrize("adapter_type", ADAPTERS)
def test_multiround_preserves_native_reasoning_and_request_parameters(adapter_type):
    adapter, calls = adapter_with_client(adapter_type)
    first = call(adapter)
    history = [
        {"role": "user", "content": "task"},
        {"role": "assistant", "content": first.content},
    ]
    second = call(adapter, "next", history)
    assert calls[0]["messages"] == [{"role": "user", "content": "task"}]
    assert calls[1]["messages"][1]["reasoning_content"] == "this agent's own reasoning"
    assert calls[1]["messages"][-1] == {"role": "user", "content": "next"}
    assert calls[1] == {
        "model": "test-model",
        "temperature": 1.0,
        "reasoning_effort": "max",
        "max_tokens": 16384,
        "stream": False,
        "messages": calls[1]["messages"],
    }
    assert second.reasoning_content == "this agent's own reasoning"
    assert second.usage.prompt_tokens == 12
    assert second.usage.completion_tokens == 7
    assert second.usage.cache_tokens == 3
    protocol = second.extra["responses_protocol"]
    assert protocol["native_history_reused"] is True
    assert protocol["input_reasoning_messages"] == 1
    assert protocol["reasoning_tokens"] == 5


@pytest.mark.parametrize("adapter_type", ADAPTERS)
def test_truncated_history_keeps_each_models_existing_behavior(adapter_type):
    adapter, calls = adapter_with_client(adapter_type)
    first = call(adapter)
    history = [
        {"role": "user", "content": "task"},
        {"role": "assistant", "content": first.content},
        {"role": "assistant", "content": ""},
    ]
    result = call(adapter, "after truncation", history)
    messages = calls[-1]["messages"]
    protocol = result.extra["responses_protocol"]
    if adapter_type is NativeKimiChat:
        assert messages[1]["reasoning_content"] == "this agent's own reasoning"
        assert len(messages) == 3
        assert protocol["native_prefix_messages"] == 2
        assert protocol["empty_assistant_placeholders_removed"] == 1
        assert protocol["native_history_reused"] is True
    else:
        assert "reasoning_content" not in messages[1]
        assert messages[2] == {"role": "assistant", "content": ""}
        assert protocol["native_history_reused"] is False
        assert "native_prefix_messages" not in protocol


def test_kimi_keeps_empty_assistant_messages_with_tool_calls():
    adapter, _ = adapter_with_client(NativeKimiChat)
    history = [{"role": "assistant", "content": ""}]
    native = {"role": "assistant", "content": "", "tool_calls": [{"id": "tool"}]}
    adapter.native[adapter.key(history)] = [native]
    messages, protocol = adapter._prepare_messages(history)
    assert messages == [native]
    assert protocol["empty_assistant_placeholders_removed"] == 0


@pytest.mark.parametrize("adapter_type", ADAPTERS)
def test_sdk_client_configuration_is_preserved(adapter_type, monkeypatch):
    fake_adapter, calls = adapter_with_client(adapter_type)
    clients = []

    def make_client(**kwargs):
        clients.append(kwargs)
        return fake_adapter.client

    monkeypatch.setattr("swe_residual.tb21.model_api.AsyncOpenAI", make_client)
    adapter = adapter_type(backend())
    call(adapter)
    call(adapter, "next")
    assert clients == [
        {
            "api_key": "offline-test-key",
            "base_url": "https://example.invalid/v1",
            "timeout": 17,
            "max_retries": 1,
        }
    ]
    assert len(calls) == 2


@pytest.mark.parametrize("adapter_type", ADAPTERS)
def test_output_limit_keeps_exception_and_does_not_store_partial_history(adapter_type):
    adapter, _ = adapter_with_client(adapter_type, response("length"))
    with pytest.raises(OutputLengthExceededError, match=adapter.endpoint_name):
        call(adapter)
    assert adapter.native == {}


@pytest.mark.parametrize("adapter_type", ADAPTERS)
def test_missing_usage_and_unexpected_finish_reason(adapter_type):
    adapter, _ = adapter_with_client(adapter_type, response(usage=False))
    assert call(adapter).usage is None
    adapter, _ = adapter_with_client(adapter_type, response("content_filter"))
    with pytest.raises(RuntimeError, match="Unexpected " + adapter.endpoint_name):
        call(adapter)
    assert adapter.native == {}


@pytest.mark.parametrize(
    "kind", ["success", "context", "bad_request", "runtime", "cancel"]
)
def test_kimi_request_audit_keeps_success_and_error_behavior(kind, tmp_path):
    request = httpx.Request("POST", "https://example.invalid/v1/chat/completions")
    error = None
    if kind in {"context", "bad_request"}:
        error = BadRequestError(
            "context_length_exceeded" if kind == "context" else "invalid parameter",
            response=httpx.Response(400, request=request),
            body=None,
        )
    elif kind == "runtime":
        error = RuntimeError("offline failure")
    elif kind == "cancel":
        error = asyncio.CancelledError()
    adapter, _ = adapter_with_client(NativeKimiChat, error=error)
    adapter.audit_owner = SimpleNamespace(logs_dir=tmp_path)
    if kind == "success":
        call(adapter)
    else:
        expected = ContextLengthExceededError if kind == "context" else type(error)
        with pytest.raises(expected):
            call(adapter)
    text = (tmp_path / "api-request-audit.jsonl").read_text()
    events = [json.loads(line) for line in text.splitlines()]
    assert [event["event"] for event in events] == (
        ["started", "returned"]
        if kind == "success"
        else ["started"]
        if kind == "context"
        else ["started", "error"]
    )
    assert len({event["request_id"] for event in events}) == 1
    assert events[0]["request_timeout_seconds"] == 17
    assert events[0]["sdk_max_retries"] == 1
    assert "offline-test-key" not in text
    assert "this agent's own reasoning" not in text


@pytest.mark.parametrize("adapter_type", ADAPTERS)
def test_agent_adapter_keeps_guard_and_observer(adapter_type, tmp_path):
    observed = SimpleNamespace(base=backend(), owner=SimpleNamespace(logs_dir=tmp_path))
    original_guard = FirstRequestGuard(observed)

    class ExistingAgent:
        def _init_llm(self, *args, **kwargs):
            return original_guard

    class AdaptedAgent(_NativeChatAgent, ExistingAgent):
        native_chat_type = adapter_type

    guard = AdaptedAgent()._init_llm(use_responses_api=False)
    assert guard is original_guard
    assert guard.delegate is observed
    assert isinstance(observed.base, adapter_type)
    if adapter_type is NativeKimiChat:
        assert observed.base.audit_owner is observed.owner
    with pytest.raises(AssertionError):
        AdaptedAgent()._init_llm(use_responses_api=True)


@pytest.mark.parametrize("api", ["kimi", "dsv41"])
@pytest.mark.parametrize("condition", ["clean", "residual"])
def test_launcher_resolves_consolidated_agents(api, condition):
    args = SimpleNamespace(
        benchmark="tb21",
        api=api,
        condition=condition,
        effort="max",
        model="test-model",
        base_url="https://example.invalid/v1",
        api_timeout=17,
        max_output_tokens=16384,
        agent_seconds=None,
    )
    config = agent_config(args, "offline-test-key")
    module_name, class_name = config["import_path"].split(":")
    assert module_name == "swe_residual.tb21.agents"
    agent_type = getattr(importlib.import_module(module_name), class_name)
    assert issubclass(
        agent_type, FreshCleanTerminus if condition == "clean" else PracticalTerminus
    )
    assert agent_type.native_chat_type is (
        NativeKimiChat if api == "kimi" else NativeDSV41Chat
    )
