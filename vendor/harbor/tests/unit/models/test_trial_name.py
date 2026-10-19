# Added for SWE-Residual; see the repository UPSTREAM.md.
import re
from pathlib import Path

from harbor.models.trial.config import TaskConfig, TrialConfig


def test_generated_trial_name_is_docker_repository_safe() -> None:
    config = TrialConfig(
        task=TaskConfig(
            path=Path("Lightning-AI__pytorch-lightning.126fa6f1.test_data.c8b292af.lv1")
        )
    )

    assert config.trial_name == config.trial_name.lower()
    assert re.fullmatch(r"[a-z0-9][a-z0-9_.-]*", config.trial_name)
    assert len(config.trial_name.split("__")[-1]) == 7
