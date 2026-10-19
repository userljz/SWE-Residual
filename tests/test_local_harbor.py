"""Offline checks for local Harbor selection and the optional command user."""

from importlib.metadata import version
from pathlib import Path
from types import SimpleNamespace

import harbor
import pytest
from harbor.trial.trial import Trial

from swe_residual.redaction import trial_class
from swe_residual.run import agent_config


def test_launcher_uses_the_modified_base_trial_from_this_checkout():
    expected = Path(__file__).resolve().parents[1] / "vendor/harbor/src/harbor"
    assert Path(harbor.__file__).resolve().parent == expected.resolve()
    assert version("harbor") == "0.21.0+residual.1"
    assert trial_class() is Trial


@pytest.mark.parametrize("command_user", [None, "harboragent"])
def test_deepswe_command_user_is_explicit_and_default_off(command_user):
    args = SimpleNamespace(
        benchmark="deepswe",
        api="chat",
        base_url="https://example.invalid/v1",
        api_timeout=300,
        max_output_tokens=16384,
        effort=None,
        agent_seconds=None,
        model="openai/test-model",
        command_user=command_user,
    )
    result = agent_config(args, "offline-test-key")
    assert result["kwargs"]["command_user"] == command_user
    assert result["kwargs"]["config"]["environment"]["cwd"] == "/app"


def test_tb21_rejects_the_deepswe_command_user_switch():
    args = SimpleNamespace(benchmark="tb21", command_user="harboragent")
    with pytest.raises(ValueError, match="only for DeepSWE"):
        agent_config(args, "offline-test-key")


def test_explicit_trial_labels_are_docker_safe_and_keep_distinct_instances():
    import re
    from swe_residual.run import trial_name

    instances = [
        "Lightning-AI__pytorch-lightning",
        "lightning-ai__pytorch-lightning",
        "!!!",
        "long-prefix-" * 8 + "a",
        "long-prefix-" * 8 + "b",
    ]
    labels = [trial_name(instance) for instance in instances]
    assert len(set(labels)) == len(instances)
    assert all(re.fullmatch(r"[a-z0-9][a-z0-9_.-]*", label) for label in labels)
    assert all(len(label) <= 60 for label in labels)
    assert labels == [trial_name(instance) for instance in instances]
