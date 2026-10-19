"""Verify frozen task packages before any model or environment setup."""

import hashlib
import json
import tomllib
from pathlib import Path

PINNED_RUNTIME_TASKS = {
    "mteb-retrieve",
    "torch-pipeline-parallelism",
    "protein-assembly",
}


def verify_task(task_path, manifest_path, expected_name=None):
    root = Path(task_path)
    name = tomllib.loads((root / "task.toml").read_text())["task"]["name"].split("/")[
        -1
    ]
    if expected_name is not None and name != expected_name:
        raise ValueError("Task identity differs from the catalog")
    manifest_path = Path(manifest_path)
    manifest = json.loads(manifest_path.read_text())
    record = manifest["tasks"].get(name)
    if record is None:
        raise ValueError(f"Task is absent from the frozen verifier manifest: {name}")
    if name in PINNED_RUNTIME_TASKS and not (
        record.get("runtime_profile") or record.get("offline_profile")
    ):
        raise ValueError(f"An approved pinned CPU verifier runtime is required: {name}")
    expected = {
        p: h
        for p, h in record["files_sha256"].items()
        if p.startswith("tests/") or p == "instruction.md"
    }
    if (
        not expected
        or "instruction.md" not in expected
        or not any(p.startswith("tests/") for p in expected)
    ):
        raise ValueError("The manifest must include the instruction and tests")
    for relative, digest in expected.items():
        path = (root / relative).resolve()
        if not path.is_relative_to(root.resolve()):
            raise ValueError("Verifier manifest path escapes its task")
        if (
            not path.is_file()
            or hashlib.sha256(path.read_bytes()).hexdigest() != digest
        ):
            raise ValueError(f"Frozen instruction/verifier mismatch: {name}/{relative}")
    return {
        "task": name,
        "checked_files": len(expected),
        "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
    }
