import asyncio
import hashlib
import json
import sys
from types import SimpleNamespace

import pytest

from swe_residual.metrics import load_records, summarize
from swe_residual.policy import verify_task
from swe_residual.redaction import scrub_directory
from swe_residual.tb21.tb21_utils import (
    FirstRequestGuard,
    HostCommandTransportTimeout,
    bounded_execute,
)


def test_placeholder_does_not_change_patch_task_id_or_conversation(tmp_path):
    patch = b"diff --git a/test.py b/test.py\n+import testing\n"
    (tmp_path / "model.patch").write_bytes(patch)
    original = {
        "task_name": "testem-bail-on-test-failure",
        "api_key": "test",
        "messages": [{"role": "user", "content": "run the tests"}],
    }
    (tmp_path / "result.json").write_text(json.dumps(original))
    scrub_directory(tmp_path, {"test"})
    result = json.loads((tmp_path / "result.json").read_text())
    assert result["api_key"] == "[REDACTED]"
    assert result["task_name"] == original["task_name"]
    assert result["messages"] == original["messages"]
    assert (tmp_path / "model.patch").read_bytes() == patch


def test_task_equal_metric_and_duplicate_attempt_rejection():
    rows = [
        {
            "model": "model",
            "benchmark": "tb21",
            "condition": "residual",
            "instance": str(i),
            "task": task,
            "reward": reward,
        }
        for i, (task, reward) in enumerate([("a", 1), ("a", 0), ("b", 0)])
    ]
    assert summarize(rows)[0]["task_equal_pass_rate"] == 0.25
    assert summarize(rows)[0]["instance_pass_rate"] == pytest.approx(1 / 3)
    with pytest.raises(ValueError, match="Multiple attempts"):
        summarize(rows + [rows[0]])
    rows[0]["reward"] = None
    assert summarize(rows)[0]["task_equal_pass_rate"] is None


def test_missing_attempts_remain_in_the_planned_cohort(tmp_path):
    common = {
        "model": "model",
        "effort": None,
        "benchmark": "tb21",
        "condition": "residual",
    }
    (tmp_path / "selection.json").write_text(
        json.dumps(
            dict(
                common,
                instances=[
                    {"instance": "a", "task": "a"},
                    {"instance": "b", "task": "b"},
                ],
            )
        )
    )
    (tmp_path / "a").mkdir()
    (tmp_path / "a/score.json").write_text(
        json.dumps(dict(common, instance="a", task="a", reward=1))
    )
    result = summarize(load_records(tmp_path))[0]
    assert result["instances"] == 2 and result["unscored"] == 1
    assert result["task_equal_pass_rate"] is None


def test_verifier_guard_rejects_changed_or_unapproved_package(tmp_path):
    task = tmp_path / "task"
    (task / "tests").mkdir(parents=True)
    (task / "task.toml").write_text('[task]\nname="mteb-retrieve"\n')
    (task / "instruction.md").write_text("Original instruction")
    (task / "tests/test.sh").write_text("Offline verifier")
    hashes = {
        p: hashlib.sha256((task / p).read_bytes()).hexdigest()
        for p in ["instruction.md", "tests/test.sh"]
    }
    manifest = tmp_path / "manifest.json"
    data = {
        "tasks": {
            "mteb-retrieve": {"offline_profile": "cpu-v1", "files_sha256": hashes}
        }
    }
    manifest.write_text(json.dumps(data))
    assert verify_task(task, manifest)["checked_files"] == 2
    (task / "tests/test.sh").write_text("Old online installer")
    with pytest.raises(ValueError, match="mismatch"):
        verify_task(task, manifest)
    data["tasks"]["mteb-retrieve"]["offline_profile"] = None
    manifest.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="approved pinned CPU verifier runtime"):
        verify_task(task, manifest)


def test_first_request_rejects_source_history_before_backend_call():
    calls = []

    async def call(*args, **kwargs):
        calls.append((args, kwargs))
        return "response"

    guard = FirstRequestGuard(SimpleNamespace(call=call))
    with pytest.raises(RuntimeError, match="Prior conversation"):
        asyncio.run(
            guard.call(
                "prompt", message_history=[{"role": "user", "content": "source"}]
            )
        )
    assert not calls
    assert asyncio.run(guard.call("prompt", message_history=[])) == "response"
    assert (
        asyncio.run(
            guard.call(
                "next",
                message_history=[{"role": "assistant", "content": "own response"}],
            )
        )
        == "response"
    )


def test_host_transport_timeout_is_not_agent_budget_timeout():
    with pytest.raises(HostCommandTransportTimeout):
        asyncio.run(
            bounded_execute(
                None, [sys.executable, "-c", "import time; time.sleep(3)"], timeout=0.05
            )
        )
    assert not issubclass(HostCommandTransportTimeout, TimeoutError)
