# Added for SWE-Residual; see the repository UPSTREAM.md.
"""Privilege-separated command environment for Mini-SWE-Agent.

The Mini-SWE controller keeps its dependencies and credentials as root while
every model-generated command is executed as a dedicated unprivileged user.
"""

from __future__ import annotations

import os
import shlex
from typing import Any

from minisweagent.environments.local import (  # ty: ignore[unresolved-import]
    LocalEnvironment,
    LocalEnvironmentConfig,
    _run,
)


class PrivilegeSeparatedLocalEnvironmentConfig(LocalEnvironmentConfig):
    """Configuration for an action environment that drops OS privileges."""

    user: str


class PrivilegeSeparatedLocalEnvironment(LocalEnvironment):
    """Run each model-generated command under ``user`` with no new privileges."""

    def __init__(
        self,
        *,
        config_class: type[
            PrivilegeSeparatedLocalEnvironmentConfig
        ] = PrivilegeSeparatedLocalEnvironmentConfig,
        **kwargs,
    ) -> None:
        super().__init__(config_class=config_class, **kwargs)
        self.config: PrivilegeSeparatedLocalEnvironmentConfig

    def execute(
        self, action: dict[str, Any], cwd: str = "", *, timeout: int | None = None
    ) -> dict[str, Any]:
        command = action.get("command", "")
        user = self.config.user
        wrapped_command = shlex.join(
            [
                "/usr/bin/setpriv",
                f"--reuid={user}",
                f"--regid={user}",
                "--init-groups",
                "--no-new-privs",
                "/bin/bash",
                "-lc",
                command,
            ]
        )
        cwd = cwd or self.config.cwd or os.getcwd()

        # Do not inherit the controller's API keys, proxy credentials, HOME, or
        # PYTHONPATH. Only a small set of harmless process settings plus the
        # task-specific environment configured for model actions is exposed.
        safe_names = ("LANG", "LC_ALL", "LC_CTYPE", "TERM", "TMPDIR", "TZ")
        env = {name: os.environ[name] for name in safe_names if name in os.environ}
        env.update(self.config.env)

        try:
            result = _run(
                wrapped_command,
                cwd,
                env,
                timeout or self.config.timeout,
            )
            output = {
                "output": result.stdout,
                "returncode": result.returncode,
                "exception_info": "",
            }
        except Exception as exc:
            raw_output = getattr(exc, "output", None)
            raw_output = (
                raw_output.decode("utf-8", errors="replace")
                if isinstance(raw_output, bytes)
                else (raw_output or "")
            )
            output = {
                "output": raw_output,
                "returncode": -1,
                "exception_info": f"An error occurred while executing the command: {exc}",
                "extra": {"exception_type": type(exc).__name__, "exception": str(exc)},
            }

        self._check_finished(output)
        return output
