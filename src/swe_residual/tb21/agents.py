"""Terminus-2 agents for matched clean and residual evaluations."""

import asyncio
import json
import re
import shlex
import shutil
import time
import uuid
from pathlib import Path

from harbor.agents.terminus_2 import Terminus2
from harbor.agents.terminus_2.tmux_session import TmuxSession

from .model_api import NativeDSV41Chat, NativeKimiChat, StatelessResponses
from .tb21_utils import FirstRequestGuard, ObservedLLM, record_initial_context

INSTALL = "if command -v apt-get >/dev/null 2>&1; then if ! command -v tmux >/dev/null 2>&1 || ! command -v asciinema >/dev/null 2>&1; then DEBIAN_FRONTEND=noninteractive apt-get -o Acquire::Retries=2 -o Acquire::http::Timeout=15 -o Acquire::https::Timeout=15 -o Acquire::ForceIPv4=true update && DEBIAN_FRONTEND=noninteractive apt-get -o Acquire::Retries=2 -o Acquire::http::Timeout=15 -o Acquire::https::Timeout=15 -o Acquire::ForceIPv4=true install -y tmux asciinema || exit $?; fi; tmux -V && asciinema --version; fi"


class StableTerminus(Terminus2):
    def _init_llm(self, *args, **kwargs):
        llm = super()._init_llm(*args, **kwargs)
        return StatelessResponses(llm) if kwargs.get("use_responses_api") else llm

    async def setup(self, environment):
        script = (
            'set -o pipefail; { echo "[$(date -Is)] recording setup start"; set -x; '
            + INSTALL
            + '; rc=$?; set +x; echo "[$(date -Is)] recording setup exit=$rc"; exit $rc; } 2>&1 | tee /logs/agent/recording-tools-install.log'
        )
        result = await environment.exec(
            command="bash -c " + shlex.quote(script), user="root", timeout_sec=300
        )
        if result.return_code:
            raise RuntimeError(
                "Recording tool setup failed; full output in recording-tools-install.log"
            )
        await Terminus2.setup(self, environment)


class MotherTerminus(Terminus2):
    async def setup(self, environment):
        self.residual_environment = environment
        entry = environment.entry
        if entry["kind"] == "runtime":
            r = await environment.exec("tmux has-session -t terminus-2", timeout_sec=10)
            if r.return_code:
                raise RuntimeError("Inherited terminal is absent")
            self._session = TmuxSession(
                session_name="terminus-2",
                environment=environment,
                logging_path=Path("/logs/agent/terminus_2.pane"),
                local_asciinema_recording_path=None,
                remote_asciinema_recording_path=None,
                user="root",
            )
        else:
            await super().setup(environment)
            shell = (
                json.loads(Path(entry["shell_state"]).read_text())
                if entry.get("shell_state")
                else {"cwd": entry["cwd"], "exported_environment": {}}
            )
            commands = [
                "export " + k + "=" + shlex.quote(v)
                for k, v in shell["exported_environment"].items()
            ]
            commands += ["cd " + shlex.quote(shell["cwd"])]
            # Only shell state is restored; no source commands or training are rerun.
            marker = "/tmp/.tb21-ready-" + uuid.uuid4().hex
            commands += ["printf ready > " + shlex.quote(marker)]
            await self._session.send_keys(
                "; ".join(commands) + "\n", block=False, min_timeout_sec=0.2
            )
            for _ in range(100):
                r = await environment.exec(
                    "test -f " + shlex.quote(marker), timeout_sec=10
                )
                if r.return_code == 0:
                    break
                await asyncio.sleep(0.1)
            else:
                raise RuntimeError("Shell state restore did not finish")
            await environment.exec("rm -f " + shlex.quote(marker), timeout_sec=10)
        # Historical read dependencies receive only this source's visible prefix.
        if entry["kind"] == "filesystem":
            await environment.exec("tmux pipe-pane -t terminus-2", timeout_sec=10)
        if entry.get("log_bundle"):
            await asyncio.to_thread(
                shutil.copytree,
                entry["log_bundle"],
                environment.trial_paths.agent_dir,
                dirs_exist_ok=True,
            )
        shutil.copy2(
            entry["prefix"], environment.trial_paths.agent_dir / "trajectory.json"
        )
        if entry["kind"] == "filesystem":
            await environment.exec(
                "tmux pipe-pane -t terminus-2 'cat >> /logs/agent/terminus_2.pane'",
                timeout_sec=10,
            )
        self.initial_terminal = await self._session.capture_pane()
        r = await environment.exec(
            'tmux list-panes -t terminus-2 -F "#{pane_current_path}"', timeout_sec=10
        )
        if entry["kind"] == "filesystem" and r.stdout.strip() != entry["cwd"]:
            raise RuntimeError("Restored cwd mismatch")

    async def _run_agent_loop(self, initial_prompt, chat, original_instruction=""):
        if chat._messages:
            raise RuntimeError(
                "Source conversation must not be supplied to the new agent"
            )
        return await Terminus2._run_agent_loop(
            self, initial_prompt, chat, original_instruction
        )


class ResidualTerminus(MotherTerminus, StableTerminus):
    """Inherited environment, matched model protocol, and health telemetry."""

    def _init_llm(self, *args, **kwargs):
        return ObservedLLM(super()._init_llm(*args, **kwargs), self)

    async def _run_agent_loop(self, *args, **kwargs):
        try:
            return await super()._run_agent_loop(*args, **kwargs)
        except RuntimeError as exc:
            import re

            pane = self.logs_dir / "terminus_2.pane"
            tail = pane.read_text(errors="replace")[-20000:] if pane.exists() else ""
            tail = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", tail).strip()
            confirmed_logout = bool(re.search(r"(?:^|[\r\n])logout\s*$", tail))
            if "no server running on" not in str(exc) or not confirmed_logout:
                raise
            (self.logs_dir.parent / "agent-terminal-exit.json").write_text(
                json.dumps(
                    {
                        "time": time.time(),
                        "reason": "Model command exited interactive shell; observed logout followed by missing tmux.",
                        "agent_execution_ended": True,
                        "verifier_must_run": True,
                        "model_retried": False,
                        "pending_commands_replayed": False,
                    },
                    indent=2,
                )
            )
            # Return ends this solve attempt; Harbor next runs the unchanged verifier.
            return


class StandardInitialPrompt(MotherTerminus):
    async def _run_agent_loop(self, initial_prompt, chat, original_instruction=""):
        if chat._messages:
            raise RuntimeError(
                "The new agent must start with an empty API conversation"
            )
        record_initial_context(self.logs_dir, initial_prompt)
        # Use the standard task prompt and current terminal with fresh history.
        return await Terminus2._run_agent_loop(
            self, initial_prompt, chat, original_instruction
        )


class PracticalTerminus(ResidualTerminus, StandardInitialPrompt):
    """Retain old setup and exception handling; bypass explicit history injection.

    MRO: Practical -> ResidualTerminus (existing logout handling) ->
    StandardInitialPrompt -> MotherTerminus (unchanged setup) -> StableTerminus.
    No files, terminal buffers, shell history, processes, or application logs are
    cleared. Later turns retain this new agent's own conversation as usual.
    """

    def _init_llm(self, *args, **kwargs):
        return FirstRequestGuard(super()._init_llm(*args, **kwargs))


class FreshCleanTerminus(StableTerminus):
    def _init_llm(self, *args, **kwargs):
        return FirstRequestGuard(ObservedLLM(super()._init_llm(*args, **kwargs), self))

    async def _run_agent_loop(self, initial_prompt, chat, original_instruction=""):
        if chat._messages:
            raise RuntimeError(
                "Clean start must have an empty initial API conversation"
            )
        record_initial_context(self.logs_dir, initial_prompt, condition="clean_start")
        try:
            return await super()._run_agent_loop(
                initial_prompt, chat, original_instruction
            )
        except RuntimeError as exc:
            pane = self.logs_dir / "terminus_2.pane"
            tail = pane.read_text(errors="replace")[-20000:] if pane.exists() else ""
            tail = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", tail).strip()
            if "no server running on" not in str(exc) or not re.search(
                r"(?:^|[\r\n])logout\s*$", tail
            ):
                raise
            (self.logs_dir.parent / "agent-terminal-exit.json").write_text(
                json.dumps(
                    {
                        "time": time.time(),
                        "reason": "Observed model shell logout",
                        "agent_execution_ended": True,
                        "verifier_must_run": True,
                        "model_retried": False,
                    },
                    indent=2,
                )
            )


class _NativeChatAgent:
    """Replace only the backend, keeping the shared guard and agent behavior."""

    native_chat_type = None

    def _init_llm(self, *args, **kwargs):
        assert kwargs.get("use_responses_api") is not True
        guard = super()._init_llm(*args, **kwargs)
        observed = guard.delegate
        observed.base = self.native_chat_type(observed.base)
        if isinstance(observed.base, NativeKimiChat):
            observed.base.audit_owner = observed.owner
        return guard


class KimiResidual(_NativeChatAgent, PracticalTerminus):
    native_chat_type = NativeKimiChat


class KimiClean(_NativeChatAgent, FreshCleanTerminus):
    native_chat_type = NativeKimiChat


class DSV41Residual(_NativeChatAgent, PracticalTerminus):
    native_chat_type = NativeDSV41Chat


class DSV41Clean(_NativeChatAgent, FreshCleanTerminus):
    native_chat_type = NativeDSV41Chat
