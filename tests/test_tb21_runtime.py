"""Offline regressions for the consolidated TB2.1 agents and environments."""

import ast
import asyncio
import copy
import importlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from harbor.agents.terminus_2 import Terminus2

from swe_residual import run
from swe_residual.tb21.agents import FreshCleanTerminus, PracticalTerminus
from swe_residual.tb21.environment import (
    ResidualEnvironment,
    RetainedFailureEnvironment,
    SnapshotEnvironment,
)
from swe_residual.tb21.model_api import StatelessResponses
from swe_residual.tb21.tb21_utils import HostCommandTransportTimeout


def bare_agent(agent_type, tmp_path):
    agent = agent_type.__new__(agent_type)
    agent.logs_dir = tmp_path / "agent"
    agent.logs_dir.mkdir()
    return agent


def bare_environment(environment_type, tmp_path, kind="filesystem"):
    environment = environment_type.__new__(environment_type)
    environment.entry = {"kind": kind}
    environment.instance = {"name": "test-instance", "state_root": "/test-state"}
    environment.trial_paths = SimpleNamespace(agent_dir=tmp_path / "agent")
    environment.default_user = "root"
    environment._merge_env = lambda env: env
    return environment


@pytest.mark.parametrize("agent_type", [FreshCleanTerminus, PracticalTerminus])
def test_initial_input_and_instruction_reach_the_original_loop(
    agent_type, tmp_path, monkeypatch
):
    received = []

    async def original_loop(self, prompt, chat, instruction=""):
        received.append((prompt, chat, instruction))
        return "finished"

    monkeypatch.setattr(Terminus2, "_run_agent_loop", original_loop)
    agent = bare_agent(agent_type, tmp_path)
    chat = SimpleNamespace(_messages=[])
    assert (
        asyncio.run(agent._run_agent_loop("task and current terminal", chat, "task"))
        == "finished"
    )
    assert received == [("task and current terminal", chat, "task")]
    proof = json.loads((tmp_path / "initial-context-proof.json").read_text())
    visible = json.loads((tmp_path / "model-visible-initial-messages.json").read_text())
    assert proof["api_history_message_count"] == 0
    assert proof["prior_response_id"] is None
    assert visible == [{"role": "user", "content": "task and current terminal"}]
    assert proof["messages"] == visible
    if agent_type is FreshCleanTerminus:
        assert proof["condition"] == "clean_start"
    else:
        assert "condition" not in proof


@pytest.mark.parametrize("agent_type", [FreshCleanTerminus, PracticalTerminus])
def test_source_conversation_is_rejected_before_the_agent_loop(
    agent_type, tmp_path, monkeypatch
):
    received = []

    async def original_loop(*args, **kwargs):
        received.append(args)

    monkeypatch.setattr(Terminus2, "_run_agent_loop", original_loop)
    agent = bare_agent(agent_type, tmp_path)
    with pytest.raises(RuntimeError, match="empty"):
        asyncio.run(
            agent._run_agent_loop(
                "task", SimpleNamespace(_messages=[{"role": "user", "content": "old"}])
            )
        )
    assert received == []
    assert not (tmp_path / "model-visible-initial-messages.json").exists()


@pytest.mark.parametrize("agent_type", [FreshCleanTerminus, PracticalTerminus])
@pytest.mark.parametrize("confirmed_logout", [True, False])
def test_only_confirmed_shell_logout_allows_verification_to_continue(
    agent_type, confirmed_logout, tmp_path, monkeypatch
):
    async def original_loop(*args, **kwargs):
        raise RuntimeError("no server running on /tmp/tmux")

    monkeypatch.setattr(Terminus2, "_run_agent_loop", original_loop)
    agent = bare_agent(agent_type, tmp_path)
    (agent.logs_dir / "terminus_2.pane").write_text(
        "\x1b[0mlogout\n" if confirmed_logout else "some other terminal failure\n"
    )
    chat = SimpleNamespace(_messages=[])
    if confirmed_logout:
        assert asyncio.run(agent._run_agent_loop("task", chat)) is None
        record = json.loads((tmp_path / "agent-terminal-exit.json").read_text())
        assert record["verifier_must_run"] is True
        assert record["model_retried"] is False
    else:
        with pytest.raises(RuntimeError, match="no server"):
            asyncio.run(agent._run_agent_loop("task", chat))
        assert not (tmp_path / "agent-terminal-exit.json").exists()


def test_environment_uses_bounded_host_transport(tmp_path):
    environment = bare_environment(SnapshotEnvironment, tmp_path, "runtime")
    with pytest.raises(HostCommandTransportTimeout):
        asyncio.run(
            environment._execute(
                [sys.executable, "-c", "import time; time.sleep(3)"], timeout=0.05
            )
        )


def test_missing_cwd_retries_only_the_unstarted_command(tmp_path, monkeypatch):
    calls = []

    async def execute(self, args, data=None, timeout=300):
        calls.append((list(args), data, timeout))
        if len(calls) == 1:
            return 1, b"", b"chdir to cwd: no such file or directory"
        return 0, b"/tmp\n", b""

    monkeypatch.setattr(SnapshotEnvironment, "_execute", execute)
    environment = bare_environment(RetainedFailureEnvironment, tmp_path)
    command = [
        "docker",
        "exec",
        "--workdir",
        "/removed",
        "test-instance",
        "bash",
        "-c",
        "pwd",
    ]
    result = asyncio.run(environment._execute(command))
    assert result == (0, b"/tmp\n", b"")
    assert calls[0][0] == command
    assert calls[1][0] == command[:3] + ["/tmp"] + command[4:]
    assert command[3] == "/removed"
    record = json.loads((tmp_path / "infrastructure-cwd-fallback.json").read_text())
    assert record["task_files_restored"] is False
    assert record["fallback_returncode"] == 0


def test_lost_terminal_preserves_the_failure_container(tmp_path, monkeypatch):
    calls = []

    async def execute(self, args, data=None, timeout=300):
        calls.append(list(args))
        if args[:2] == ["docker", "exec"]:
            return 1, b"", b"tmux: no server running on /tmp/tmux"
        return 0, b"", b""

    monkeypatch.setattr(SnapshotEnvironment, "_execute", execute)
    environment = bare_environment(RetainedFailureEnvironment, tmp_path)
    asyncio.run(environment._execute(["docker", "exec", "test-instance", "tmux"]))
    asyncio.run(environment.stop())
    assert calls[-1] == ["docker", "stop", "--time", "5", "test-instance"]
    assert not any(command[:2] == ["docker", "rm"] for command in calls)
    record = json.loads((tmp_path / "retained-failure-container.json").read_text())
    assert record["container"] == "test-instance"


def test_normal_filesystem_completion_cleans_up(tmp_path, monkeypatch):
    calls = []

    async def execute(self, args, data=None, timeout=300):
        calls.append(list(args))
        return 0, b"", b""

    monkeypatch.setattr(SnapshotEnvironment, "_execute", execute)
    environment = bare_environment(RetainedFailureEnvironment, tmp_path)
    asyncio.run(environment.stop())
    assert calls == [["docker", "rm", "-f", "test-instance"]]


@pytest.mark.parametrize("kind", ["filesystem", "runtime"])
def test_exec_keeps_user_workdir_env_and_timeout(kind, tmp_path, monkeypatch):
    calls = []

    async def execute(self, args, data=None, timeout=300):
        calls.append((list(args), timeout))
        return 0, b"output\n", b""

    monkeypatch.setattr(SnapshotEnvironment, "_execute", execute)
    environment = bare_environment(ResidualEnvironment, tmp_path, kind)
    result = asyncio.run(
        environment.exec(
            "printf output",
            cwd="/app",
            env={"FLAG": "value"},
            timeout_sec=7,
            user="root",
        )
    )
    prefix = (
        ["docker", "exec", "--workdir", "/app", "--user", "root"]
        if kind == "filesystem"
        else ["runc", "--root", "/test-state", "exec", "--cwd", "/app", "--user", "0"]
    )
    assert calls == [
        (
            prefix
            + [
                "--env",
                "FLAG=value",
                "test-instance",
                "timeout",
                "--kill-after=5",
                "7",
                "bash",
                "-c",
                "printf output",
            ],
            22,
        )
    ]
    assert result.return_code == 0
    assert result.stdout == "output\n"


def test_responses_preserves_encrypted_reasoning_across_own_turns():
    calls = []
    output = [
        {"type": "reasoning", "encrypted_content": "opaque", "summary": []},
        {
            "type": "message",
            "role": "assistant",
            "content": [{"type": "output_text", "text": "command"}],
        },
    ]
    reply = SimpleNamespace(
        output=output,
        model="test-model",
        status="completed",
        reasoning=SimpleNamespace(effort="max"),
        usage=SimpleNamespace(
            input_tokens=12,
            output_tokens=7,
            input_tokens_details=SimpleNamespace(cached_tokens=3),
        ),
    )

    async def create(**kwargs):
        calls.append(copy.deepcopy(kwargs))
        return reply

    backend = SimpleNamespace(
        _canonical_model_name="test-model",
        _temperature=1.0,
        _reasoning_effort="max",
        _api_base="https://example.invalid/v1",
        get_model_context_limit=lambda: 922000,
        get_model_output_limit=lambda: 16384,
    )
    adapter = StatelessResponses(backend)
    adapter.client = SimpleNamespace(responses=SimpleNamespace(create=create))
    first = asyncio.run(adapter.call("task", api_key="offline-test-key"))
    history = [
        {"role": "user", "content": "task"},
        {"role": "assistant", "content": first.content},
    ]
    second = asyncio.run(
        adapter.call("next", message_history=history, api_key="offline-test-key")
    )
    assert calls[1]["input"][1]["encrypted_content"] == "opaque"
    assert calls[1]["store"] is False
    assert calls[1]["include"] == ["reasoning.encrypted_content"]
    assert second.usage.prompt_tokens == 12
    assert second.usage.cache_tokens == 3
    assert second.extra["responses_protocol"]["native_history_reused"] is True


@pytest.mark.parametrize("api", ["chat", "responses"])
@pytest.mark.parametrize("condition", ["clean", "residual"])
def test_common_launcher_routes_resolve(api, condition):
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
    config = run.agent_config(args, "offline-test-key")
    module_name, class_name = config["import_path"].split(":")
    resolved = getattr(importlib.import_module(module_name), class_name)
    assert resolved is (
        FreshCleanTerminus if condition == "clean" else PracticalTerminus
    )


def test_literal_environment_route_resolves():
    tree = ast.parse(Path(run.__file__).read_text())
    paths = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value.startswith("swe_residual.tb21.")
        and ":" in node.value
    ]
    assert paths
    for path in paths:
        module_name, class_name = path.split(":")
        assert getattr(importlib.import_module(module_name), class_name) is (
            RetainedFailureEnvironment
        )
