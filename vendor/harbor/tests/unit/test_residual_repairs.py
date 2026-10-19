"""SWE-Residual regression tests for the modifications to vendored Harbor."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from harbor.agents.installed.mini_swe_agent import MiniSweAgent
from harbor.agents.installed.mini_swe_agent_compat import repair_extensions
from harbor.models.job.config import RetryConfig
from harbor.models.trial.config import TrialConfig
from harbor.trial.queue import TrialQueue
from harbor.trial.trial import Trial


def test_default_trial_scrubber_preserves_patch_and_short_placeholder(tmp_path):
    patch_bytes = b"diff --git a/test.py b/test.py\n+import testing\n"
    (tmp_path / "model.patch").write_bytes(patch_bytes)
    secret = "fake-long-provider-key-for-unit-test"
    data = {
        "task_name": "testem-bail-on-test-failure",
        "api_key": "test",
        "messages": [{"content": "run the tests"}, {"content": secret}],
    }
    (tmp_path / "result.json").write_text(json.dumps(data))
    (tmp_path / "agent.log").write_text("test " + secret)
    (tmp_path / "incomplete.json").write_text('{"content": "' + secret)
    trial = SimpleNamespace(
        config=SimpleNamespace(
            model_dump=lambda **kwargs: {"agent": {"kwargs": {"api_key": secret}}},
            verifier=SimpleNamespace(env={}),
        ),
        agent=SimpleNamespace(extra_env={"MSWEA_API_KEY": "test"}),
        task=SimpleNamespace(config=SimpleNamespace(verifier=SimpleNamespace(env={}))),
        paths=SimpleNamespace(trial_dir=tmp_path),
    )
    Trial._scrub_jobs_dir(trial)
    clean = json.loads((tmp_path / "result.json").read_text())
    assert clean["api_key"] == "[REDACTED]"
    assert clean["task_name"] == data["task_name"]
    assert clean["messages"][0] == data["messages"][0]
    assert clean["messages"][1]["content"] == "[REDACTED]"
    assert (tmp_path / "agent.log").read_text() == "test [REDACTED]"
    assert secret not in (tmp_path / "incomplete.json").read_text()
    assert (tmp_path / "model.patch").read_bytes() == patch_bytes


@pytest.mark.asyncio
@pytest.mark.parametrize("collision", [False, True])
async def test_retry_preserves_failed_attempt_and_refuses_collision(
    tmp_path, collision
):
    directory = tmp_path / "trial"
    archive = tmp_path / "trial.failed-1"
    if collision:
        archive.mkdir()
        (archive / "existing.txt").write_text("keep")
    calls = []

    async def create(config):
        directory.mkdir()
        calls.append(config)
        (directory / "agent.log").write_text("failed" if len(calls) == 1 else "success")
        return SimpleNamespace(
            paths=SimpleNamespace(trial_dir=directory),
            run=AsyncMock(
                return_value=SimpleNamespace(
                    exception_info=SimpleNamespace(exception_type="TransientError")
                    if len(calls) == 1
                    else None
                )
            ),
        )

    queue = TrialQueue(1, RetryConfig(max_retries=1, min_wait_sec=0, max_wait_sec=0))
    queue._setup_hooks = MagicMock()
    config = TrialConfig(task={"path": tmp_path}, trial_name="trial")
    with patch.object(Trial, "create", side_effect=create):
        if collision:
            with pytest.raises(RuntimeError, match="already exists"):
                await queue._execute_trial_with_retries(config)
            assert len(calls) == 1
            assert (directory / "agent.log").read_text() == "failed"
            assert (archive / "existing.txt").read_text() == "keep"
        else:
            result = await queue._execute_trial_with_retries(config)
            assert result.exception_info is None
            assert (archive / "agent.log").read_text() == "failed"
            assert (directory / "agent.log").read_text() == "success"


def test_extension_alias_is_conditional_and_preserves_original(tmp_path):
    original = tmp_path / "module.cpython-313-x86_64-linux-musl.so"
    alias = tmp_path / "module.cpython-313-x86_64-linux-gnu.so"
    original.write_bytes(b"extension")
    musl = [".cpython-313-x86_64-linux-musl.so", ".so"]
    gnu = [".cpython-313-x86_64-linux-gnu.so", ".so"]
    repair_extensions(tmp_path, musl)
    assert not alias.exists()
    repair_extensions(tmp_path, gnu)
    assert alias.is_symlink() and alias.read_bytes() == original.read_bytes()
    repair_extensions(tmp_path, gnu)
    assert original.read_bytes() == b"extension"
    protected = tmp_path / "other.cpython-313-x86_64-linux-gnu.so"
    protected.write_bytes(b"keep")
    (tmp_path / "other.cpython-313-x86_64-linux-musl.so").write_bytes(b"other")
    repair_extensions(tmp_path, gnu)
    assert protected.read_bytes() == b"keep"


@pytest.mark.asyncio
async def test_installer_reuses_preinstalled_tool_without_writes(tmp_path):
    import subprocess

    home = tmp_path / "home"
    binary = home / ".local/bin"
    binary.mkdir(parents=True)
    (home / ".bashrc").write_text('export PATH="$HOME/.local/bin:$PATH"\n')
    for name in ["uv", "mini-swe-agent"]:
        target = binary / name
        target.write_text(
            "#!/bin/sh\nexit 0\n"
            if name == "mini-swe-agent"
            else "#!/bin/sh\nexit 99\n"
        )
        target.chmod(0o755)
    agent = MiniSweAgent(logs_dir=tmp_path)
    assert agent._command_user is None
    agent.ensure_system_dependencies = AsyncMock()
    agent.exec_as_agent = AsyncMock()
    env = AsyncMock()
    await agent.install(env)
    command = agent.exec_as_agent.call_args.kwargs["command"]
    result = subprocess.run(
        ["bash", "-c", command],
        env={"HOME": str(home), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert (binary / "uv").read_text().endswith("exit 99\n")
    assert "litellm[proxy]" not in command


@pytest.mark.asyncio
async def test_command_user_uses_configured_task_directory(tmp_path):
    agent = MiniSweAgent(
        logs_dir=tmp_path,
        command_user="harboragent",
        config={"environment": {"cwd": "/app"}},
    )
    agent.ensure_system_dependencies = AsyncMock()
    agent.exec_as_agent = AsyncMock()
    agent.exec_as_root = AsyncMock()
    await agent.install(AsyncMock())
    assert (
        "chown -R harboragent:harboragent /app"
        in agent.exec_as_root.call_args_list[0].kwargs["command"]
    )
    with pytest.raises(ValueError, match="task directory"):
        MiniSweAgent(
            logs_dir=tmp_path,
            command_user="harboragent",
            config={"environment": {"cwd": "/"}},
        )


def test_incomplete_log_that_cannot_be_written_does_not_abort_scrubbing(
    tmp_path, monkeypatch
):
    from harbor.utils.redaction import scrub_directory

    secret = "fake-long-provider-key-for-unit-test"
    target = tmp_path / "incomplete.json"
    target.write_text('{"key": "' + secret)
    original_write = Path.write_text

    def denied(path, text, *args, **kwargs):
        if path == target:
            raise PermissionError("read-only artifact")
        return original_write(path, text, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", denied)
    scrub_directory(tmp_path, {secret})
    assert target.read_text().endswith(secret)


@pytest.mark.asyncio
async def test_archive_failure_aborts_retry_without_deletion(tmp_path, monkeypatch):
    directory = tmp_path / "trial"
    directory.mkdir()
    (directory / "agent.log").write_text("keep failed evidence")
    trial = SimpleNamespace(
        paths=SimpleNamespace(trial_dir=directory),
        run=AsyncMock(
            return_value=SimpleNamespace(
                exception_info=SimpleNamespace(exception_type="TransientError")
            )
        ),
    )
    queue = TrialQueue(1, RetryConfig(max_retries=1))
    queue._setup_hooks = MagicMock()
    original_rename = Path.rename

    def denied(path, target):
        if path == directory:
            raise PermissionError("archive unavailable")
        return original_rename(path, target)

    monkeypatch.setattr(Path, "rename", denied)
    config = TrialConfig(task={"path": tmp_path}, trial_name="trial")
    with patch.object(Trial, "create", return_value=trial) as create:
        with pytest.raises(RuntimeError, match="retry aborted"):
            await queue._execute_trial_with_retries(config)
        create.assert_awaited_once()
    assert (directory / "agent.log").read_text() == "keep failed evidence"
