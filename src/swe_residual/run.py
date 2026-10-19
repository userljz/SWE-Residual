"""Run one explicitly selected attempt per benchmark instance."""

import argparse
import asyncio
import hashlib
import json
import os
import re
import tomllib
from pathlib import Path

from .policy import verify_task
from .redaction import redact, trial_class


def trial_name(instance):
    """Use a Docker-safe label while retaining distinct instance identities."""
    prefix = re.sub(r"[^a-z0-9_.-]", "-", instance.lower()).strip("._-")[:47]
    digest = hashlib.sha256(instance.encode()).hexdigest()[:12]
    return f"{prefix or 'trial'}-{digest}"


def task_packages(root):
    root = Path(root).resolve()
    return (
        [root]
        if (root / "task.toml").is_file()
        else sorted(p.parent for p in root.glob("*/task.toml"))
    )


def selected_entries(args):
    if args.benchmark == "tb21" and args.condition == "residual":
        if args.catalog is None:
            raise ValueError("TB2.1 residual evaluation requires a catalog")
        catalog = json.loads(args.catalog.read_text())
        entries = []
        for key, entry in sorted(catalog.items()):
            raw = Path(entry.get("task_path", args.tasks / key))
            path = raw if raw.is_absolute() else args.catalog.parent / raw
            entries.append((key, path.resolve(), entry["task"]))
        return entries
    if args.benchmark == "deepswe" and args.condition == "residual" and not args.subset:
        raise ValueError(
            "DeepSWE residual runs require --subset to identify the source state"
        )
    return [
        ((args.subset + "--" + p.name) if args.subset else p.name, p, None)
        for p in task_packages(args.tasks)
    ]


def agent_config(args, api_key):
    command_user = getattr(args, "command_user", None)
    if command_user and args.benchmark != "deepswe":
        raise ValueError("--command-user is supported only for DeepSWE")
    if args.benchmark == "deepswe":
        if args.api not in {"chat", "responses"}:
            raise ValueError("DeepSWE uses --api chat or --api responses")
        model_kwargs = {
            "api_key": api_key,
            "api_base": args.base_url,
            "temperature": 1.0,
            "timeout": args.api_timeout,
            "num_retries": 2,
        }
        if args.api == "responses":
            model_kwargs.update(
                max_output_tokens=args.max_output_tokens,
                store=False,
                include=["reasoning.encrypted_content"],
            )
            if args.effort:
                model_kwargs["reasoning"] = {"effort": args.effort}
        else:
            model_kwargs["max_tokens"] = args.max_output_tokens
            if args.effort:
                model_kwargs["reasoning_effort"] = args.effort
        return {
            "name": "mini-swe-agent",
            "model_name": args.model,
            "override_timeout_sec": args.agent_seconds or 10800,
            "kwargs": {
                "version": "2.4.6",
                "command_user": command_user,
                "config": {
                    "environment": {"cwd": "/app", "timeout": 120},
                    "model": {
                        "model_class": "litellm_response"
                        if args.api == "responses"
                        else "litellm",
                        "model_kwargs": model_kwargs,
                    },
                },
            },
        }
    pairs = {
        "chat": (
            "agents:PracticalTerminus",
            "agents:FreshCleanTerminus",
        ),
        "responses": (
            "agents:PracticalTerminus",
            "agents:FreshCleanTerminus",
        ),
        "kimi": ("agents:KimiResidual", "agents:KimiClean"),
        "dsv41": ("agents:DSV41Residual", "agents:DSV41Clean"),
    }
    if args.api in {"kimi", "dsv41"} and args.effort != "max":
        raise ValueError("The archived native Kimi/DSV41 adapters require --effort max")
    module = pairs[args.api][args.condition == "clean"]
    call = {
        "api_key": api_key,
        (
            "max_output_tokens" if args.api == "responses" else "max_tokens"
        ): args.max_output_tokens,
        "timeout": args.api_timeout,
        "num_retries": 2,
        "stream": False,
    }
    if args.api == "responses":
        call.update(store=False, include=["reasoning.encrypted_content"])
    kwargs = {
        "api_base": args.base_url,
        "temperature": 1.0,
        "use_responses_api": args.api == "responses",
        "store_all_messages": True,
        "record_terminal_session": True,
        "model_info": {
            "max_input_tokens": 922000,
            "max_output_tokens": args.max_output_tokens,
            "input_cost_per_token": 0.0,
            "output_cost_per_token": 0.0,
        },
        "llm_call_kwargs": call,
    }
    if args.effort:
        kwargs["reasoning_effort"] = args.effort
    result = {
        "import_path": "swe_residual.tb21." + module,
        "model_name": args.model,
        "kwargs": kwargs,
    }
    if args.agent_seconds:
        result["override_timeout_sec"] = args.agent_seconds
    return result


def preflight(args):
    entries = selected_entries(args)
    if not entries:
        raise ValueError("No task packages found")
    if args.benchmark == "tb21" and args.verifier_manifest is None:
        raise ValueError("TB2.1 requires --verifier-manifest before any model calls")
    for _, path, name in entries:
        if not (path / "instruction.md").is_file():
            raise ValueError(f"Missing task instruction: {path}")
        if args.benchmark == "tb21":
            verify_task(path, args.verifier_manifest, name)
    if args.output.exists():
        raise ValueError("Output already exists; use a new directory for each attempt")
    return entries


async def evaluate(args, entries):
    from harbor.models.trial.config import TrialConfig

    if args.catalog:
        os.environ["TB_CATALOG_PATH"] = str(args.catalog.resolve())
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("Set OPENAI_API_KEY")
    args.output.mkdir(parents=True, exist_ok=False)
    plan = {
        "benchmark": args.benchmark,
        "condition": args.condition,
        "model": args.model,
        "effort": args.effort,
        "instances": [],
    }
    for key, path, _ in entries:
        task_name = tomllib.loads((path / "task.toml").read_text())["task"][
            "name"
        ].split("/")[-1]
        plan["instances"].append({"instance": key, "task": task_name})
    (args.output / "selection.json").write_text(json.dumps(plan, indent=2) + "\n")
    agent = agent_config(args, api_key)
    Trial = trial_class()
    semaphore = asyncio.Semaphore(args.concurrency)

    async def one(key, path, name):
        async with semaphore:
            if args.benchmark == "tb21":
                policy = verify_task(path, args.verifier_manifest, name)
            else:
                policy = None
            safe_name = trial_name(key)
            environment = {"type": "docker", "delete": True}
            if args.benchmark == "tb21" and args.condition == "residual":
                environment = {
                    "import_path": "swe_residual.tb21.environment:RetainedFailureEnvironment",
                    "delete": True,
                    "kwargs": {"residual_id": key},
                }
            multiplier = (
                1.0
                if args.benchmark == "deepswe" or args.agent_seconds
                else args.agent_multiplier
            )
            cfg = TrialConfig(
                task={"path": path},
                trial_name=safe_name,
                trials_dir=args.output,
                agent=agent,
                environment=environment,
                agent_timeout_multiplier=multiplier,
                verifier_timeout_multiplier=1.0,
            )
            trial = await Trial.create(cfg)
            task_name = tomllib.loads((path / "task.toml").read_text())["task"][
                "name"
            ].split("/")[-1]
            ledger = {
                "benchmark": args.benchmark,
                "condition": args.condition,
                "instance": key,
                "task": task_name,
                "model": args.model,
                "api": args.api,
                "effort": args.effort,
                "command_user": args.command_user,
                "agent_seconds": trial._agent_timeout_sec,
                "verifier_seconds": trial._verifier_timeout_sec,
                "policy": policy,
            }
            (trial.paths.trial_dir / "protocol.json").write_text(
                json.dumps(ledger, indent=2) + "\n"
            )
            result = await trial.run()
            ledger["reward"] = (
                (result.verifier_result.rewards or {}).get("reward")
                if result.verifier_result
                else None
            )
            ledger["exception"] = (
                result.exception_info.exception_type if result.exception_info else None
            )
            ledger["scored"] = ledger["reward"] in [0, 1]
            (trial.paths.trial_dir / "score.json").write_text(
                json.dumps(redact(ledger), indent=2) + "\n"
            )

    async with asyncio.TaskGroup() as group:
        for entry in entries:
            group.create_task(one(*entry))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("benchmark", choices=["deepswe", "tb21"])
    p.add_argument("--condition", choices=["clean", "residual"], required=True)
    p.add_argument("--tasks", type=Path, required=True)
    p.add_argument("--catalog", type=Path)
    p.add_argument("--subset", choices=["dsv4", "qwen38_27b", "glm53"])
    p.add_argument("--verifier-manifest", type=Path)
    p.add_argument("--model", required=True)
    p.add_argument(
        "--api", choices=["chat", "responses", "kimi", "dsv41"], default="chat"
    )
    p.add_argument("--effort")
    p.add_argument(
        "--command-user", help="Optional DeepSWE command user; disabled by default"
    )
    p.add_argument(
        "--base-url",
        default=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
    )
    p.add_argument("--api-timeout", type=float, default=300)
    p.add_argument("--max-output-tokens", type=int, default=16384)
    p.add_argument("--agent-seconds", type=float)
    p.add_argument("--agent-multiplier", type=float, default=3.0)
    p.add_argument("--concurrency", type=int, default=1)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    if (
        args.concurrency < 1
        or args.api_timeout <= 0
        or args.agent_multiplier <= 0
        or args.max_output_tokens < 1
    ):
        p.error("Concurrency, budgets and output limits must be positive")
    if args.agent_seconds is not None and args.agent_seconds <= 0:
        p.error("Agent seconds must be positive")
    entries = preflight(args)
    agent_config(args, "")
    if args.dry_run:
        print(
            json.dumps(
                {
                    "benchmark": args.benchmark,
                    "condition": args.condition,
                    "instances": len(entries),
                    "model": args.model,
                    "api": args.api,
                    "effort": args.effort,
                    "command_user": args.command_user,
                },
                indent=2,
            )
        )
        return
    asyncio.run(evaluate(args, entries))


if __name__ == "__main__":
    main()
