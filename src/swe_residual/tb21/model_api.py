"""Responses and native Chat interfaces for a fresh model conversation."""

import hashlib
import json
import time
import uuid

from harbor.llms.base import (
    BaseLLM,
    ContextLengthExceededError,
    LLMResponse,
    OutputLengthExceededError,
)
from harbor.models.metric import UsageInfo
from openai import AsyncOpenAI, BadRequestError


class StatelessResponses(BaseLLM):
    """Retain complete native output, including encrypted reasoning, with store=false."""

    def __init__(self, delegate):
        self.base = delegate
        self.native = {}
        self.audit = []
        self.client = None

    def get_model_context_limit(self):
        return self.base.get_model_context_limit()

    def get_model_output_limit(self):
        return self.base.get_model_output_limit()

    @staticmethod
    def key(messages):
        return hashlib.sha256(
            json.dumps(
                messages, sort_keys=True, ensure_ascii=False, default=str
            ).encode()
        ).hexdigest()

    async def call(
        self,
        prompt,
        message_history=None,
        response_format=None,
        logging_path=None,
        **kwargs,
    ):
        history = message_history or []
        kwargs.pop("previous_response_id", None)
        history_key = self.key(history)
        hit = history_key in self.native
        items = (
            list(self.native[history_key])
            if hit
            else [{"role": m["role"], "content": m.get("content", "")} for m in history]
        )
        items.append({"role": "user", "content": prompt})
        params = dict(
            model=self.base._canonical_model_name,
            temperature=self.base._temperature,
            max_output_tokens=self.get_model_output_limit(),
            reasoning={"effort": self.base._reasoning_effort},
            store=False,
            include=["reasoning.encrypted_content"],
            stream=False,
        )
        params.update(kwargs)
        params["input"] = items
        params.pop("max_tokens", None)
        params.pop("previous_response_id", None)
        api_key = params.pop("api_key")
        timeout = params.pop("timeout", 300)
        retries = params.pop("num_retries", 2)
        if self.client is None:
            self.client = AsyncOpenAI(
                api_key=api_key,
                base_url=self.base._api_base,
                timeout=timeout,
                max_retries=retries,
            )
        try:
            response = await self.client.responses.create(**params)
        except BadRequestError as e:
            if any(
                x in str(e).lower()
                for x in [
                    "context_length_exceeded",
                    "maximum context length",
                    "input is too long",
                ]
            ):
                raise ContextLengthExceededError(str(e)) from e
            raise
        output = [
            x.model_dump(exclude_none=True) if hasattr(x, "model_dump") else dict(x)
            for x in response.output
        ]
        text = "".join(
            part.get("text", "")
            for item in output
            if item.get("type") == "message"
            for part in item.get("content", [])
            if part.get("type") == "output_text"
        )
        thinking = (
            "\n".join(
                part.get("text", "")
                for item in output
                if item.get("type") == "reasoning"
                for part in item.get("summary", [])
            )
            or None
        )
        if (
            getattr(response, "status", None) == "incomplete"
            and getattr(getattr(response, "incomplete_details", None), "reason", None)
            == "max_output_tokens"
        ):
            raise OutputLengthExceededError(
                "Response reached configured output-token limit",
                truncated_response=text,
            )
        next_history = history + [
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": text},
        ]
        self.native[self.key(next_history)] = items + output
        record = {
            "history_messages": len(history),
            "native_history_reused": hit,
            "input_reasoning_items": sum(x.get("type") == "reasoning" for x in items),
            "output_reasoning_items": sum(x.get("type") == "reasoning" for x in output),
            "encrypted_output_items": sum(
                bool(x.get("encrypted_content")) for x in output
            ),
            "store": params["store"],
            "reasoning_effort": params["reasoning"]["effort"],
            "response_model": response.model,
            "response_effort": getattr(
                getattr(response, "reasoning", None), "effort", None
            ),
        }
        self.audit.append(record)
        u = response.usage
        usage = (
            UsageInfo(
                prompt_tokens=u.input_tokens,
                completion_tokens=u.output_tokens,
                cache_tokens=getattr(u.input_tokens_details, "cached_tokens", 0) or 0,
                cost_usd=getattr(u, "cost_usd", 0) or 0,
            )
            if u
            else None
        )
        return LLMResponse(
            content=text,
            reasoning_content=thinking,
            model_name=response.model,
            usage=usage,
            extra={"responses_protocol": record},
        )


class NativeReasoningChat(BaseLLM):
    """Share request handling, native-message storage, usage and error mapping."""

    endpoint_name = ""

    def __init__(self, base):
        self.base = base
        self.native = {}
        self.client = None

    def get_model_context_limit(self):
        return self.base.get_model_context_limit()

    def get_model_output_limit(self):
        return self.base.get_model_output_limit()

    @staticmethod
    def key(messages):
        return hashlib.sha256(
            json.dumps(
                messages, sort_keys=True, ensure_ascii=False, default=str
            ).encode()
        ).hexdigest()

    @staticmethod
    def _context_error(error):
        return any(
            text in str(error).lower()
            for text in [
                "context_length_exceeded",
                "maximum context length",
                "input is too long",
            ]
        )

    def _native_history(self, history, preserve_prefix=False):
        key = self.key(history)
        hit = key in self.native
        prefix_length = len(history) if hit else 0
        if not hit and preserve_prefix:
            for length in range(len(history), 0, -1):
                candidate = self.key(history[:length])
                if candidate in self.native:
                    key, hit, prefix_length = candidate, True, length
                    break
        messages = list(self.native[key]) if hit else []
        messages += [
            {"role": message["role"], "content": message.get("content", "")}
            for message in history[prefix_length:]
        ]
        return messages, hit, prefix_length

    def _prepare_messages(self, history):
        messages, hit, _ = self._native_history(history)
        return messages, {"native_history_reused": hit}

    async def _request(self, params, messages, timeout, retries):
        return await self.client.chat.completions.create(**params, messages=messages)

    def _extra_protocol(self, params, timeout, retries):
        return {}

    async def call(
        self,
        prompt,
        message_history=None,
        response_format=None,
        logging_path=None,
        **kwargs,
    ):
        history = message_history or []
        messages, history_protocol = self._prepare_messages(history)
        messages.append({"role": "user", "content": prompt})
        params = {
            "model": self.base._canonical_model_name,
            "temperature": self.base._temperature,
            "reasoning_effort": self.base._reasoning_effort,
            "max_tokens": self.get_model_output_limit(),
            "stream": False,
        }
        params.update(kwargs)
        for key in ["previous_response_id", "max_output_tokens", "store", "include"]:
            params.pop(key, None)
        api_key = params.pop("api_key")
        timeout = params.pop("timeout", 300)
        retries = params.pop("num_retries", 2)
        assert params["reasoning_effort"] == "max" and params["temperature"] == 1.0
        if self.client is None:
            self.client = AsyncOpenAI(
                api_key=api_key,
                base_url=self.base._api_base,
                timeout=timeout,
                max_retries=retries,
            )
        try:
            response = await self._request(params, messages, timeout, retries)
        except BadRequestError as error:
            if self._context_error(error):
                raise ContextLengthExceededError(
                    f"{self.endpoint_name} endpoint context limit exceeded"
                ) from error
            raise

        choice = response.choices[0]
        native = choice.message.model_dump(exclude_none=True)
        text = choice.message.content or ""
        thinking = native.get("reasoning_content") or None
        if choice.finish_reason == "length":
            raise OutputLengthExceededError(
                f"{self.endpoint_name} response reached output-token limit",
                truncated_response=text,
            )
        if choice.finish_reason not in ["stop", "tool_calls"]:
            raise RuntimeError(
                f"Unexpected {self.endpoint_name} finish_reason: "
                + str(choice.finish_reason)
            )
        next_history = history + [
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": text},
        ]
        self.native[self.key(next_history)] = messages + [native]
        usage = response.usage
        usage_info = (
            UsageInfo(
                prompt_tokens=usage.prompt_tokens,
                completion_tokens=usage.completion_tokens,
                cache_tokens=getattr(
                    getattr(usage, "prompt_tokens_details", None), "cached_tokens", 0
                )
                or 0,
                cost_usd=getattr(usage, "cost_usd", 0) or 0,
            )
            if usage
            else None
        )
        protocol = {
            "api": "chat/completions",
            "requested_effort": params["reasoning_effort"],
            "history_messages": len(history),
            **history_protocol,
            "input_reasoning_messages": sum(
                bool(message.get("reasoning_content")) for message in messages
            ),
            "reasoning_tokens": getattr(
                getattr(usage, "completion_tokens_details", None),
                "reasoning_tokens",
                None,
            ),
            "reasoning_chars": len(thinking or ""),
            "response_model": response.model,
            "finish_reason": choice.finish_reason,
            "temperature": params["temperature"],
            "max_tokens": params["max_tokens"],
            **self._extra_protocol(params, timeout, retries),
        }
        return LLMResponse(
            content=text,
            reasoning_content=thinking,
            model_name=response.model,
            usage=usage_info,
            extra={"responses_protocol": protocol},
        )


class NativeDSV41Chat(NativeReasoningChat):
    """Use complete native histories; summarized histories start a new chain."""

    endpoint_name = "DSV41"


class NativeKimiChat(NativeReasoningChat):
    """Also recover native prefixes after truncation and audit API requests."""

    endpoint_name = "Kimi"

    def _prepare_messages(self, history):
        messages, hit, prefix_length = self._native_history(
            history, preserve_prefix=True
        )

        # Harbor truncation can leave an empty assistant placeholder.
        def empty_assistant(message):
            return (
                message.get("role") == "assistant"
                and not message.get("content")
                and not message.get("tool_calls")
            )

        empty_removed = sum(empty_assistant(message) for message in messages)
        messages = [message for message in messages if not empty_assistant(message)]
        return messages, {
            "native_history_reused": hit,
            "native_prefix_messages": prefix_length,
            "empty_assistant_placeholders_removed": empty_removed,
        }

    def audit(self, record):
        owner = getattr(self, "audit_owner", None)
        if owner is not None:
            with (owner.logs_dir / "api-request-audit.jsonl").open("a") as log:
                log.write(json.dumps(record) + "\n")

    def _audit_error(self, request_id, began, error):
        self.audit(
            {
                "event": "error",
                "time": time.time(),
                "request_id": request_id,
                "error_type": type(error).__name__,
                "elapsed": time.time() - began,
            }
        )

    async def _request(self, params, messages, timeout, retries):
        request_id = uuid.uuid4().hex
        began = time.time()
        self.audit(
            {
                "event": "started",
                "time": began,
                "request_id": request_id,
                "stream": params.get("stream"),
                "request_timeout_seconds": timeout,
                "sdk_max_retries": retries,
                "message_count": len(messages),
                "request_characters": sum(
                    len(str(message.get("content") or ""))
                    + len(str(message.get("reasoning_content") or ""))
                    for message in messages
                ),
                "max_tokens": params["max_tokens"],
                "reasoning_effort": params["reasoning_effort"],
            }
        )
        try:
            response = await super()._request(params, messages, timeout, retries)
            self.audit(
                {
                    "event": "returned",
                    "time": time.time(),
                    "request_id": request_id,
                    "elapsed": time.time() - began,
                    "finish_reason": response.choices[0].finish_reason,
                    "response_model": response.model,
                    "prompt_tokens": getattr(response.usage, "prompt_tokens", None),
                    "completion_tokens": getattr(
                        response.usage, "completion_tokens", None
                    ),
                    "reasoning_tokens": getattr(
                        getattr(response.usage, "completion_tokens_details", None),
                        "reasoning_tokens",
                        None,
                    ),
                }
            )
            return response
        except BadRequestError as error:
            # Preserve the existing context-error mapping and audit behavior.
            if not self._context_error(error):
                self._audit_error(request_id, began, error)
            raise
        except BaseException as error:
            self._audit_error(request_id, began, error)
            raise

    def _extra_protocol(self, params, timeout, retries):
        return {
            "stream": params.get("stream"),
            "request_timeout_seconds": timeout,
            "sdk_max_retries": retries,
        }
