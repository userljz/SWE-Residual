"""Shared TB2.1 conversation checks, audit records and host-command helpers."""

import asyncio
import json
import subprocess
import tempfile
import time

from harbor.llms.base import BaseLLM


class HostCommandTransportTimeout(RuntimeError):
    pass


async def bounded_execute(self, args, data=None, timeout=300):
    with (
        tempfile.TemporaryFile() as stdout,
        tempfile.TemporaryFile() as stderr,
        tempfile.TemporaryFile() as source,
    ):
        if data is not None:
            source.write(data)
            source.seek(0)
        proc = subprocess.Popen(
            args,
            stdin=source if data is not None else subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
        )
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        try:
            while proc.poll() is None:
                if loop.time() >= deadline:
                    raise HostCommandTransportTimeout(
                        f"Host command transport exceeded {timeout}s; whole-agent budget was not exhausted by this check"
                    )
                await asyncio.sleep(0.05)
            stdout.seek(0)
            stderr.seek(0)
            return proc.returncode, stdout.read(), stderr.read()
        except BaseException:
            if proc.poll() is None:
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
            try:
                await asyncio.to_thread(proc.wait, timeout=5)
            except (subprocess.TimeoutExpired, ProcessLookupError):
                pass
            raise


def run_host_command(args, timeout=900, **kw):
    r = subprocess.run(args, capture_output=True, text=True, timeout=timeout, **kw)
    if r.returncode:
        raise RuntimeError(" ".join(args[:3]) + ": " + r.stderr[-3000:])
    return r.stdout.strip()


class FirstRequestGuard(BaseLLM):
    def __init__(self, delegate):
        self.delegate = delegate
        self.first_request = True

    def get_model_context_limit(self):
        return self.delegate.get_model_context_limit()

    def get_model_output_limit(self):
        return self.delegate.get_model_output_limit()

    async def call(self, *args, **kwargs):
        if self.first_request:
            history = kwargs.get("message_history", args[1] if len(args) > 1 else None)
            if history:
                raise RuntimeError(
                    "Prior conversation is prohibited on the first model request"
                )
            if kwargs.get("previous_response_id"):
                raise RuntimeError(
                    "Prior response id is prohibited on the first model request"
                )
            self.first_request = False
        return await self.delegate.call(*args, **kwargs)


class ObservedLLM(BaseLLM):
    def __init__(self, base, owner):
        self.base = base
        self.owner = owner

    def get_model_context_limit(self):
        return self.base.get_model_context_limit()

    def get_model_output_limit(self):
        return self.base.get_model_output_limit()

    async def call(self, *args, **kwargs):
        start = time.time()
        try:
            result = await self.base.call(*args, **kwargs)
        except Exception as exc:
            self.record(
                {
                    "time": time.time(),
                    "success": False,
                    "error_type": type(exc).__name__,
                    "elapsed": time.time() - start,
                }
            )
            raise
        self.record(
            {
                "time": time.time(),
                "success": bool(result.content),
                "content_chars": len(result.content or ""),
                "elapsed": time.time() - start,
                "protocol": (getattr(result, "extra", None) or {}).get(
                    "responses_protocol"
                ),
            }
        )
        return result

    def record(self, entry):
        # Counts and protocol flags only; never persist request credentials here.
        with (self.owner.logs_dir / "model-call-audit.jsonl").open("a") as f:
            f.write(json.dumps(entry, default=str) + "\n")


def record_initial_context(logs_dir, initial_prompt, condition=None):
    """Save the first model input outside the container's agent-log mount."""
    proof = {
        "api_history_message_count": 0,
        "prior_response_id": None,
        "input_mode": "standard_task_prompt_and_current_terminal",
        "environment_history_scrubbed": False,
    }
    if condition is not None:
        proof["condition"] = condition
    proof["messages"] = [{"role": "user", "content": initial_prompt}]
    artifacts = [
        ("initial-context-proof.json", proof),
        ("model-visible-initial-messages.json", proof["messages"]),
    ]
    # Keep the original write order for each evaluation condition.
    if condition is None:
        artifacts.reverse()
    for name, content in artifacts:
        (logs_dir.parent / name).write_text(
            json.dumps(content, ensure_ascii=False, indent=2)
        )
