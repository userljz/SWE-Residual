"""Filesystem and runtime-snapshot environments, including failure handling."""

import asyncio
import fcntl
import hashlib
import io
import json
import os
import shlex
import shutil
import subprocess
import tarfile
import time
import tomllib
import uuid
from pathlib import Path

from harbor.environments.base import BaseEnvironment, ExecResult
from harbor.environments.capabilities import (
    EnvironmentCapabilities,
    EnvironmentResourceCapabilities,
)

from .tb21_utils import bounded_execute, run_host_command

B = Path(os.environ.get("SWE_RESIDUAL_RUNTIME_ROOT", "runs/runtime")).resolve()


def restore(snapshot, dest, name, network_container=None, bind_overrides=None):
    assert name.startswith("swe-residual-runtime-")
    snapshot = Path(snapshot).resolve()
    dest = Path(dest).resolve()
    dest.mkdir(parents=True, exist_ok=False)
    manifest = json.loads((snapshot / "manifest.json").read_text())
    root = dest / "rootfs"
    root.mkdir()
    cache = snapshot.parent / (
        "restore-base-" + hashlib.sha256(str(snapshot).encode()).hexdigest()[:12]
    )
    cache.mkdir(exist_ok=True)
    with (cache / "extract.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        lower = cache / "rootfs"
        lower.mkdir(exist_ok=True)
        if not (cache / "ready.json").exists():
            run_host_command(
                [
                    "tar",
                    "--numeric-owner",
                    "-xf",
                    str(snapshot / "rootfs.tar"),
                    "-C",
                    str(lower),
                ],
                timeout=1800,
            )
            (cache / "ready.json").write_text(
                json.dumps(
                    {"snapshot": str(snapshot), "bytes": manifest["rootfs_bytes"]}
                )
            )
        seal = json.loads((cache / "ready.json").read_text())
        if seal != {"snapshot": str(snapshot), "bytes": manifest["rootfs_bytes"]}:
            raise RuntimeError("Restore cache identity mismatch")
        if subprocess.run(
            ["mountpoint", "-q", str(lower)], capture_output=True
        ).returncode:
            run_host_command(["mount", "--bind", str(lower), str(lower)])
        run_host_command(["mount", "-o", "remount,bind,ro", str(lower)])
    upper = dest / "upper"
    upper.mkdir()
    work = dest / "overlay-work"
    work.mkdir()
    run_host_command(
        [
            "mount",
            "-t",
            "overlay",
            "overlay",
            "-o",
            f"lowerdir={lower},upperdir={upper},workdir={work}",
            str(root),
        ]
    )
    cfg = json.loads((snapshot / "source-config.json").read_text())
    cfg["root"]["path"] = str(root)
    cfg["linux"]["cgroupsPath"] = "/" + name
    cfg.pop("hooks", None)
    for b in manifest["binds"]:
        source = snapshot / b["path"]
        target = Path(
            (bind_overrides or {}).get(
                b["destination"], dest / "binds" / str(b["index"])
            )
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, target, symlinks=True, dirs_exist_ok=True)
        else:
            shutil.copy2(source, target)
        cfg["mounts"][b["index"]]["source"] = str(target)
    for ns in cfg["linux"]["namespaces"]:
        ns.pop("path", None)
        if ns["type"] == "network" and network_container:
            assert network_container.startswith("swe-residual-runtime-")
            pid = json.loads(
                run_host_command(["docker", "inspect", network_container])
            )[0]["State"]["Pid"]
            ns["path"] = f"/proc/{pid}/ns/net"
    if network_container:
        anchor = json.loads(run_host_command(["docker", "inspect", network_container]))[
            0
        ]
        for m in cfg["mounts"]:
            if m["destination"] == "/etc/resolv.conf":
                shutil.copy2(anchor["ResolvConfPath"], m["source"])
    (dest / "config.json").write_text(json.dumps(cfg, indent=2))
    (dest / "work").mkdir()
    state = dest.parent / "runc-state"
    args = [
        "runc",
        "--root",
        str(state),
        "restore",
        "-d",
        "--empty-ns",
        "network",
        "--shell-job",
        "--file-locks",
        "--image-path",
        str(snapshot / "checkpoint"),
        "--work-path",
        str(dest / "work"),
        "--bundle",
        str(dest),
        name,
    ]
    with (dest / "restore-stdio.log").open("wb") as log:
        p = subprocess.run(
            args, stdin=subprocess.DEVNULL, stdout=log, stderr=log, timeout=300
        )
    if p.returncode:
        raise RuntimeError(
            (dest / "restore-stdio.log").read_text(errors="replace")[-3000:]
        )
    pid = json.loads(run_host_command(["runc", "--root", str(state), "state", name]))[
        "pid"
    ]
    run_host_command(["nsenter", "-t", str(pid), "-n", "ip", "link", "set", "lo", "up"])
    if network_container:
        anchor = json.loads(run_host_command(["docker", "inspect", network_container]))[
            0
        ]
        apid = anchor["State"]["Pid"]
        if (
            os.stat(f"/proc/{apid}/ns/net").st_ino
            != os.stat(f"/proc/{pid}/ns/net").st_ino
        ):
            net = next(iter(anchor["NetworkSettings"]["Networks"].values()))
            run_host_command(
                [
                    "nsenter",
                    "-t",
                    str(apid),
                    "-n",
                    "ip",
                    "link",
                    "set",
                    "eth0",
                    "netns",
                    str(pid),
                ]
            )
            run_host_command(
                ["nsenter", "-t", str(pid), "-n", "ip", "link", "set", "eth0", "up"]
            )
            run_host_command(
                [
                    "nsenter",
                    "-t",
                    str(pid),
                    "-n",
                    "ip",
                    "addr",
                    "replace",
                    f"{net['IPAddress']}/{net['IPPrefixLen']}",
                    "dev",
                    "eth0",
                ]
            )
            run_host_command(
                [
                    "nsenter",
                    "-t",
                    str(pid),
                    "-n",
                    "ip",
                    "route",
                    "replace",
                    "default",
                    "via",
                    net["Gateway"],
                ]
            )
    result = {
        "name": name,
        "state_root": str(state),
        "bundle": str(dest),
        "snapshot": str(snapshot),
        "restored_at": time.time(),
    }
    (dest / "restore.json").write_text(json.dumps(result, indent=2))
    return result


class SnapshotEnvironment(BaseEnvironment):
    def __init__(self, *args, residual_id, **kwargs):
        self.residual_id = residual_id
        self.entry = json.loads(Path(os.environ["TB_CATALOG_PATH"]).read_text())[
            residual_id
        ]
        self.instance = None
        self.anchor = None
        super().__init__(*args, **kwargs)
        if (
            self.task_env_config.cpus != self.entry["cpus"]
            or self.task_env_config.memory_mb != self.entry["memory_mb"]
        ):
            raise ValueError(
                "Requested task resources differ from frozen source resources"
            )

    @staticmethod
    def type():
        return "tb21-runtime-snapshot"

    @property
    def capabilities(self):
        return EnvironmentCapabilities(mounted=True, disable_internet=True)

    @classmethod
    def resource_capabilities(cls):
        return EnvironmentResourceCapabilities(cpu_limit=True, memory_limit=True)

    def _validate_definition(self):
        if self.entry.get("kind") != "runtime" or not self.entry.get("clone_validated"):
            raise ValueError("Runtime snapshot has not passed clone validation")
        task = tomllib.loads((self.environment_dir.parent / "task.toml").read_text())
        if task.get("task", {}).get("name", "").split("/")[-1] != self.entry["task"]:
            raise ValueError("Task identity differs from frozen snapshot task")

    async def start(self, force_build=False):
        name = (
            "swe-residual-runtime-harbor-"
            + self.residual_id
            + "-"
            + uuid.uuid4().hex[:10]
        )
        dest = B / "harbor-instances" / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not self._network_disabled:
            self.anchor = name + "-net"
            await asyncio.to_thread(
                run_host_command,
                [
                    "docker",
                    "run",
                    "-d",
                    "--name",
                    self.anchor,
                    "--network",
                    "bridge",
                    "alpine:latest",
                    "sleep",
                    "infinity",
                ],
            )
        overrides = {
            "/logs/agent": str(self.trial_paths.agent_dir),
            "/logs/verifier": str(self.trial_paths.verifier_dir),
            "/logs/artifacts": str(self.trial_paths.artifacts_dir),
        }
        self.instance = await asyncio.to_thread(
            restore,
            self.entry["snapshot"],
            dest,
            name,
            network_container=self.anchor,
            bind_overrides=overrides,
        )
        (self.trial_paths.agent_dir.parent / "starting-point.json").write_text(
            json.dumps(
                {
                    "residual_id": self.residual_id,
                    "snapshot": self.entry["snapshot"],
                    "runtime": self.instance,
                    "scope": "reconstructed runtime starting point",
                },
                indent=2,
            )
        )

    def prefix(self):
        return ["runc", "--root", self.instance["state_root"]]

    _execute = bounded_execute

    async def exec(self, command, cwd=None, env=None, timeout_sec=None, user=None):
        args = self.prefix() + ["exec"]
        if cwd:
            args += ["--cwd", cwd]
        user = self._resolve_user(user)
        if user is not None:
            if str(user) not in ("root", "0"):
                raise ValueError(
                    "This snapshot adapter currently supports the source root user only"
                )
            args += ["--user", "0"]
        for k, v in (self._merge_env(env) or {}).items():
            args += ["--env", f"{k}={v}"]
        args += [self.instance["name"]]
        if timeout_sec:
            args += ["timeout", "--kill-after=5", str(timeout_sec)]
        args += ["bash", "-c", command]
        rc, o, e = await self._execute(
            args, timeout=(timeout_sec + 15) if timeout_sec else 3600
        )
        return ExecResult(
            return_code=rc,
            stdout=o.decode(errors="replace"),
            stderr=e.decode(errors="replace"),
        )

    async def upload_file(self, source_path, target_path):
        cmd = (
            "mkdir -p "
            + shlex.quote(str(Path(target_path).parent))
            + "; cat > "
            + shlex.quote(str(target_path))
        )
        rc, o, e = await self._execute(
            self.prefix() + ["exec", self.instance["name"], "bash", "-c", cmd],
            Path(source_path).read_bytes(),
        )
        if rc:
            raise RuntimeError(e.decode())

    async def upload_dir(self, source_dir, target_dir):
        data = await asyncio.to_thread(
            subprocess.check_output, ["tar", "-C", str(source_dir), "-cf", "-", "."]
        )
        cmd = (
            "mkdir -p "
            + shlex.quote(str(target_dir))
            + "; tar -xf - -C "
            + shlex.quote(str(target_dir))
        )
        rc, o, e = await self._execute(
            self.prefix() + ["exec", self.instance["name"], "bash", "-c", cmd], data
        )
        if rc:
            raise RuntimeError(e.decode())

    async def download_file(self, source_path, target_path):
        rc, o, e = await self._execute(
            self.prefix() + ["exec", self.instance["name"], "cat", str(source_path)]
        )
        if rc:
            raise RuntimeError(e.decode())
        target = Path(target_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(o)

    async def download_dir(self, source_dir, target_dir):
        rc, o, e = await self._execute(
            self.prefix()
            + [
                "exec",
                self.instance["name"],
                "tar",
                "-C",
                str(source_dir),
                "-cf",
                "-",
                ".",
            ]
        )
        if rc:
            raise RuntimeError(e.decode())
        target = Path(target_dir)
        target.mkdir(parents=True, exist_ok=True)
        with tarfile.open(fileobj=io.BytesIO(o)) as archive:
            archive.extractall(target, filter="data")

    async def stop(self, delete=True):
        if self.instance:
            await asyncio.to_thread(
                run_host_command,
                self.prefix() + ["delete", "--force", self.instance["name"]],
            )
            await asyncio.to_thread(
                run_host_command,
                ["umount", str(Path(self.instance["bundle"]) / "rootfs")],
            )
        if self.anchor:
            await asyncio.to_thread(
                run_host_command, ["docker", "rm", "-f", self.anchor]
            )


class ResidualEnvironment(SnapshotEnvironment):
    def __init__(self, *args, residual_id, **kwargs):
        self.residual_id = residual_id
        catalog = Path(os.environ["TB_CATALOG_PATH"]).resolve()
        self.entry = json.loads(catalog.read_text())[residual_id]
        for key in ["snapshot", "prefix", "shell_state", "log_bundle"]:
            if self.entry.get(key) and not Path(self.entry[key]).is_absolute():
                self.entry[key] = str(catalog.parent / self.entry[key])
        self.instance = None
        self.anchor = None
        BaseEnvironment.__init__(self, *args, **kwargs)
        if (
            self.task_env_config.cpus != self.entry["cpus"]
            or self.task_env_config.memory_mb != self.entry["memory_mb"]
        ):
            raise ValueError("Source task resource mismatch")

    @staticmethod
    def type():
        return "tb21-residual-mother"

    def _validate_definition(self):
        if not self.entry["clone_validated"]:
            raise ValueError("Clone validation pending")
        task = tomllib.loads((self.environment_dir.parent / "task.toml").read_text())
        if task["task"]["name"].split("/")[-1] != self.entry["task"]:
            raise ValueError("Source task identity mismatch")

    async def start(self, force_build=False):
        if self.entry["kind"] == "runtime":
            await super().start(force_build=force_build)
            return
        name = "tb21-eval-" + self.residual_id + "-" + uuid.uuid4().hex[:10]
        self.instance = {"name": name, "kind": "filesystem"}
        args = [
            "docker",
            "run",
            "-d",
            "--name",
            name,
            "--label",
            "swe-residual.owned=true",
            "--network",
            "none" if self._network_disabled else "bridge",
            "--cpus",
            str(self.entry["cpus"]),
            "--memory",
            str(self.entry["memory_mb"]) + "m",
            "--workdir",
            self.entry["cwd"],
            "--user",
            "root",
        ]
        for k, v in (self._merge_env(None) or {}).items():
            args += ["--env", f"{k}={v}"]
        for src, dst in [
            (self.trial_paths.agent_dir, "/logs/agent"),
            (self.trial_paths.verifier_dir, "/logs/verifier"),
            (self.trial_paths.artifacts_dir, "/logs/artifacts"),
        ]:
            src.mkdir(parents=True, exist_ok=True)
            args += ["--mount", f"type=bind,src={src},dst={dst}"]
        args += [
            "--entrypoint",
            "/bin/sh",
            self.entry["image_id"],
            "-c",
            "sleep infinity",
        ]
        rc, o, e = await self._execute(args)
        if rc:
            raise RuntimeError(e.decode()[-1200:])
        (self.trial_paths.agent_dir.parent / "starting-point.json").write_text(
            json.dumps(
                {
                    k: self.entry[k]
                    for k in [
                        "id",
                        "kind",
                        "image_id",
                        "source_sha256",
                        "historical_exactness",
                    ]
                },
                indent=2,
            )
        )

    def prefix(self):
        return ["docker"] if self.entry["kind"] == "filesystem" else super().prefix()

    async def _execute(self, args, data=None, timeout=300):
        if data is not None and args[:2] == ["docker", "exec"]:
            args = args[:2] + ["-i"] + args[2:]
        return await super()._execute(args, data, timeout)

    async def exec(self, command, cwd=None, env=None, timeout_sec=None, user=None):
        if self.entry["kind"] == "runtime":
            return await super().exec(command, cwd, env, timeout_sec, user)
        args = ["docker", "exec"]
        if cwd:
            args += ["--workdir", str(cwd)]
        user = self._resolve_user(user)
        if user is not None:
            args += ["--user", str(user)]
        for k, v in (self._merge_env(env) or {}).items():
            args += ["--env", f"{k}={v}"]
        args += [self.instance["name"]]
        if timeout_sec:
            args += ["timeout", "--kill-after=5", str(timeout_sec)]
        args += ["bash", "-c", command]
        rc, o, e = await self._execute(
            args, timeout=(timeout_sec + 15) if timeout_sec else 3600
        )
        return ExecResult(
            return_code=rc,
            stdout=o.decode(errors="replace"),
            stderr=e.decode(errors="replace"),
        )

    async def stop(self, delete=True):
        if self.entry["kind"] == "runtime":
            return await super().stop(delete=delete)
        if self.instance:
            rc, o, e = await self._execute(
                ["docker", "rm", "-f", self.instance["name"]]
            )
            if rc and b"No such container" not in e:
                raise RuntimeError(e.decode())


class RetainedFailureEnvironment(ResidualEnvironment):
    """Preserve a failed filesystem instance when the agent loses its terminal."""

    async def _execute(self, args, data=None, timeout=300):
        rc, out, err = await super()._execute(args, data, timeout)
        if (
            rc
            and args[:2] == ["docker", "exec"]
            and b"chdir to cwd" in (out + err)
            and b"no such file or directory" in (out + err)
        ):
            fallback = list(args)
            if "--workdir" in fallback:
                fallback[fallback.index("--workdir") + 1] = "/tmp"
            else:
                fallback = fallback[:2] + ["--workdir", "/tmp"] + fallback[2:]
            rc, out, err = await super()._execute(fallback, data, timeout)
            p = self.trial_paths.agent_dir.parent / "infrastructure-cwd-fallback.json"
            p.write_text(
                json.dumps(
                    {
                        "reason": "Configured cwd removed or renamed by agent; original exec never started.",
                        "fallback_workdir": "/tmp",
                        "task_files_restored": False,
                        "fallback_returncode": rc,
                    },
                    indent=2,
                )
            )
        if (
            rc
            and b"tmux" in err
            and (b"no server running" in err or b"no sessions" in err)
        ):
            self._lost_terminal = True
        return rc, out, err

    async def stop(self, delete=True):
        if (
            getattr(self, "_lost_terminal", False)
            and self.entry["kind"] == "filesystem"
            and self.instance
        ):
            await super()._execute(
                ["docker", "stop", "--time", "5", self.instance["name"]]
            )
            p = self.trial_paths.agent_dir.parent / "retained-failure-container.json"
            p.write_text(
                json.dumps(
                    {
                        "container": self.instance["name"],
                        "reason": "Terminal disappeared during agent execution; retain filesystem for diagnosis and verifier-only recovery.",
                    },
                    indent=2,
                )
            )
            return
        return await super().stop(delete=delete)
