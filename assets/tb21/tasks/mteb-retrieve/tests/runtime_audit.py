"""Validate a verifier runtime without installing packages or using the network."""

import argparse
import importlib.metadata as metadata
import json
import sys
from pathlib import Path


class BootstrapPolicyError(RuntimeError):
    pass


def validate_inventory(actual, expected, cuda_version=None):
    def norm(value):
        return value.lower().replace("_", "-")

    actual = {norm(key): value for key, value in actual.items()}
    expected = {norm(key): value for key, value in expected.items()}
    unexpected = set(actual) - set(expected)
    missing = set(expected) - set(actual)
    wrong = {key: (actual[key], value) for key, value in expected.items()
             if key in actual and actual[key] != value}
    gpu = [key for key in actual if key.startswith("nvidia-")
           or key in ("triton", "cuda-python", "cuda-bindings")]
    if gpu:
        raise BootstrapPolicyError("GPU packages forbidden in CPU verifier: " + ", ".join(sorted(gpu)))
    if unexpected or missing or wrong:
        raise BootstrapPolicyError(
            f"Runtime lock mismatch: unexpected={sorted(unexpected)} "
            f"missing={sorted(missing)} wrong={wrong}"
        )
    if "torch" in actual and (not actual["torch"].endswith("+cpu") or cuda_version is not None):
        raise BootstrapPolicyError(
            f"CPU-only torch required; installed={actual['torch']}, torch.version.cuda={cuda_version}"
        )
    return {"passed": True, "packages": actual, "torch_cuda_version": cuda_version, "cpu_only": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, default=Path("/tests/runtime-profile.json"))
    parser.add_argument("--output", type=Path, default=Path("/logs/verifier/runtime-policy.json"))
    args = parser.parse_args()
    expected = json.loads(args.profile.read_text())
    actual = {distribution.metadata["Name"]: distribution.version
              for distribution in metadata.distributions()}
    cuda = None
    if "torch" in expected["packages"]:
        import torch

        cuda = torch.version.cuda
    result = validate_inventory(actual, expected["packages"], cuda)
    result.update(profile=expected["profile"], python=sys.version.split()[0])
    if result["python"] != expected["python"]:
        raise BootstrapPolicyError("Unexpected verifier Python version")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print("CPU_VERIFIER_POLICY_OK profile=" + expected["profile"])


if __name__ == "__main__":
    main()
