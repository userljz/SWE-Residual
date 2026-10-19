"""Pinned runtime admission and CPU validation must also hold for downloaded environments."""

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from swe_residual.policy import verify_task


def test_downloaded_runtime_profile_is_admitted_before_execution(tmp_path):
    task = tmp_path / "task"
    (task / "tests").mkdir(parents=True)
    (task / "task.toml").write_text('[task]\nname="terminal-bench/mteb-retrieve"\n')
    (task / "instruction.md").write_text("Task instruction")
    (task / "tests/test.sh").write_text("Pinned runtime bootstrap")
    hashes = {
        name: hashlib.sha256((task / name).read_bytes()).hexdigest()
        for name in ["instruction.md", "tests/test.sh"]
    }
    manifest = tmp_path / "manifest.json"
    record = {
        "runtime_profile": "approved-pinned-cpu-v2",
        "offline_profile": None,
        "files_sha256": hashes,
    }
    manifest.write_text(json.dumps({"tasks": {"mteb-retrieve": record}}))
    assert verify_task(task, manifest)["checked_files"] == 2
    record["runtime_profile"] = None
    manifest.write_text(json.dumps({"tasks": {"mteb-retrieve": record}}))
    with pytest.raises(ValueError, match="approved pinned CPU verifier runtime"):
        verify_task(task, manifest)


@pytest.fixture
def audit():
    root = Path(__file__).resolve().parents[1]
    path = root / "assets/tb21/tasks/torch-pipeline-parallelism/tests/runtime_audit.py"
    spec = importlib.util.spec_from_file_location("runtime_audit_for_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "actual,cuda",
    [
        ({"torch": "2.7.0"}, None),
        ({"torch": "2.7.0+cpu"}, "12.4"),
        ({"torch": "2.7.0+cpu", "nvidia-cublas-cu12": "12.4"}, None),
        ({}, None),
    ],
)
def test_runtime_cache_is_rejected_when_versions_or_cpu_policy_differ(
    audit, actual, cuda
):
    with pytest.raises(audit.BootstrapPolicyError):
        audit.validate_inventory(actual, {"torch": "2.7.0+cpu"}, cuda)
