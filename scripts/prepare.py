"""Verify benchmark files and prepare Docker environments from a Git checkout."""

import argparse
import hashlib
import json
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


def digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(8 * 1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text())


def rows(path):
    return [
        json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()
    ]


def verify_files(root, benchmark):
    manifest = read_json(root / "SHA256SUMS.json")
    selected = [
        (name, expected)
        for name, expected in manifest.items()
        if name.startswith(f"assets/{benchmark}/") or name.startswith("metadata/")
    ]
    if not selected:
        raise ValueError("No benchmark assets found in checksum manifest")

    def verify_entry(item):
        name, expected = item
        path = root / name
        if not path.is_file():
            raise ValueError(f"Missing asset: {name}. Fetch the complete Git checkout.")
        if digest(path) != expected:
            raise ValueError(f"Changed asset: {name}")
        return 1

    with ThreadPoolExecutor(max_workers=8) as executor:
        return sum(executor.map(verify_entry, selected))


def validate_repository(repository):
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*/[a-z0-9][a-z0-9._-]*", repository):
        raise ValueError("Use a Docker Hub repository in lowercase: account/repository")
    return repository


def residual_images(root):
    catalog = read_json(root / "assets/tb21/catalog.json")
    recorded = read_json(root / "assets/tb21/image-manifest.json")
    state_ids = {entry["image_id"]: state_id for state_id, entry in catalog.items()}
    if len(state_ids) != len(catalog):
        raise ValueError("Duplicate image references in Residual catalog")
    result = {}
    for entry in recorded:
        reference = entry["public_reference"]
        state_id = state_ids.get(reference)
        if state_id is None:
            raise ValueError(f"Unexpected Residual image reference: {reference}")
        if state_id in result:
            raise ValueError(f"Duplicate Residual image: {state_id}")
        if catalog[state_id]["image_id"] != reference:
            raise ValueError(f"Residual catalog/image mismatch: {state_id}")
        config = entry["public_config_sha256"]
        if not re.fullmatch(r"[0-9a-f]{64}", config):
            raise ValueError(f"Invalid image config digest: {state_id}")
        manifest_digest = entry.get("public_manifest_digest")
        if manifest_digest and not re.fullmatch(
            r"sha256:[0-9a-f]{64}", manifest_digest
        ):
            raise ValueError(f"Invalid image manifest digest: {state_id}")
        result[state_id] = {
            "state_id": state_id,
            "task": catalog[state_id]["task"],
            "local_reference": reference,
            "image_id": f"sha256:{config}",
            "manifest_digest": manifest_digest,
            "tag": f"fs31-{state_id}-v1",
        }
    if len(result) != 31 or set(result) != set(catalog):
        raise ValueError("Expected the exact 31 formal Residual states")
    return [result[key] for key in sorted(result)]


def clean_actions(root):
    entries = read_json(root / "assets/tb21/clean-images.json")
    catalog = read_json(root / "assets/tb21/clean-catalog.json")
    if len(entries) != 20 or len({entry["task"] for entry in entries}) != 20:
        raise ValueError("Expected 20 official Clean base images")
    actions = []
    for entry in entries:
        reference = entry["image_reference"]
        if not re.fullmatch(r"alexgshaw/[a-z0-9._-]+@sha256:[0-9a-f]{64}", reference):
            raise ValueError("Clean base must be a pinned official image")
        if catalog[entry["task"]]["image_reference"] != reference:
            raise ValueError("Clean image manifest and catalog disagree")
        actions.append(["docker", "pull", reference])
    return actions


def residual_actions(root, repository=None, registry_manifest=None):
    images = residual_images(root)
    path = registry_manifest or root / "assets/tb21/dockerhub-images.json"
    published = read_json(path) if Path(path).is_file() else {"images": []}
    mapped = {entry["state_id"]: entry for entry in published["images"]}
    if len(mapped) != len(published["images"]):
        raise ValueError("Duplicate states in Docker Hub publication manifest")
    if repository:
        repository = validate_repository(repository)
    actions = []
    for image in images:
        entry = mapped.get(image["state_id"], {})
        remote = entry.get("image_reference")
        # An explicitly selected repository takes priority over another publisher's manifest.
        if repository and (not remote or remote.split("@")[0] != repository):
            remote = f"{repository}:{image['tag']}"
        if not remote:
            raise ValueError(
                "Residual images await Docker Hub publication. After publishing, use "
                "--docker-repository account/repository or the completed registry manifest. "
                "For the existing offline export, use --archive /path/to/images.tar.gz."
            )
        if "@" in remote:
            repo, sha = remote.split("@", 1)
            validate_repository(repo)
            if not re.fullmatch(r"sha256:[0-9a-f]{64}", sha):
                raise ValueError("Invalid published image digest")
        elif not repository or remote != f"{repository}:{image['tag']}":
            raise ValueError("Published images must be pinned by registry digest")
        if entry.get("image_id") and entry["image_id"] != image["image_id"]:
            raise ValueError(
                f"Published manifest changes source image: {image['state_id']}"
            )
        expected_manifest = (
            remote.split("@", 1)[1] if "@" in remote else image.get("manifest_digest")
        )
        actions.append(
            {**image, "manifest_digest": expected_manifest, "remote_reference": remote}
        )
    return actions


def check_image_identity(reference, expected, manifest_digest=None):
    """Check the recorded config ID, or its verified manifest on containerd stores."""
    result = subprocess.run(
        ["docker", "image", "inspect", "--format", "{{json .}}", reference],
        check=True,
        capture_output=True,
        text=True,
    )
    inspected = json.loads(result.stdout)
    descriptor = inspected.get("Descriptor") or {}
    config_matches = inspected.get("Id") == expected
    # Docker 29's containerd store reports a manifest digest as Id. The manifest
    # digest must be independently recorded and verified against the source config.
    manifest_matches = bool(manifest_digest) and (
        inspected.get("Id") == manifest_digest == descriptor.get("digest")
    )
    if not (config_matches or manifest_matches):
        raise ValueError(
            f"Image identity does not match the recorded Residual state: {reference}"
        )


def execute_residual(action):
    remote = action["remote_reference"]
    subprocess.run(["docker", "pull", remote], check=True)
    check_image_identity(remote, action["image_id"], action.get("manifest_digest"))
    subprocess.run(["docker", "tag", remote, action["local_reference"]], check=True)


def archive_actions(root, archive):
    manifest = read_json(root / "assets/tb21/image-archive.json")
    return manifest, ["docker", "load", "-i", str(archive)]


def deepswe_actions(root, condition, subset):
    residual = rows(root / "metadata/deepswe-residual.jsonl")
    selected = [row for row in residual if not subset or row["generator_key"] == subset]
    actions = []
    if condition in {"all", "clean"}:
        clean = rows(root / "metadata/deepswe-clean.jsonl")
        selected_tasks = {row["task"] for row in selected}
        references = {
            row["image_reference"]
            for row in clean
            if not subset or row["task"] in selected_tasks
        }
        actions.extend(["docker", "pull", ref] for ref in sorted(references))
    if condition in {"all", "residual"}:
        for row in selected:
            context = root / row["task_package"] / "environment"
            actions.append(
                [
                    "docker",
                    "build",
                    "--network",
                    "none",
                    "-t",
                    row["image_reference"],
                    str(context),
                ]
            )
    return actions


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument("--benchmark", choices=["deepswe", "tb21"], required=True)
    parser.add_argument(
        "--condition", choices=["all", "residual", "clean"], default="all"
    )
    parser.add_argument("--subset", choices=["dsv4", "qwen38_27b", "glm53"])
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print commands without Docker operations",
    )
    parser.add_argument(
        "--docker-repository",
        help="Published Docker Hub repository: account/repository",
    )
    parser.add_argument(
        "--registry-manifest", type=Path, help="Completed Docker Hub digest manifest"
    )
    parser.add_argument(
        "--archive", type=Path, help="Optional existing 31-image offline export"
    )
    args = parser.parse_args()
    root = args.root.resolve()
    try:
        if args.verify_only:
            print(
                f"Dataset file checksums verified: {verify_files(root, args.benchmark)}"
            )
            return
        clean, residual, load = [], [], None
        if args.benchmark == "tb21":
            if args.condition in {"all", "clean"}:
                clean = clean_actions(root)
            if args.condition in {"all", "residual"}:
                if args.archive:
                    archive_info, load = archive_actions(root, args.archive.resolve())
                else:
                    residual = residual_actions(
                        root, args.docker_repository, args.registry_manifest
                    )
            if args.dry_run:
                print(
                    json.dumps(
                        {
                            "benchmark": "tb21",
                            "clean_commands": clean,
                            "archive_command": load,
                            "residual_images": residual,
                        },
                        indent=2,
                    )
                )
                return
            verify_files(root, args.benchmark)
            if load:
                archive = args.archive.resolve()
                if not archive.is_file() or digest(archive) != archive_info["sha256"]:
                    raise ValueError(
                        "Offline archive does not match the recorded export"
                    )
                subprocess.run(load, check=True)
                for image in residual_images(root):
                    check_image_identity(
                        image["local_reference"],
                        image["image_id"],
                        image.get("manifest_digest"),
                    )
            for action in residual:
                execute_residual(action)
            for command in clean:
                subprocess.run(command, check=True)
            print(
                "TB2.1 preparation complete. The harness prepares recording tools before model execution."
            )
            return
        commands = deepswe_actions(root, args.condition, args.subset)
        if args.dry_run:
            print(json.dumps({"benchmark": "deepswe", "commands": commands}, indent=2))
            return
        verify_files(root, args.benchmark)
        for command in commands:
            if command[1] == "build":
                reference = command[command.index("-t") + 1]
                if (
                    subprocess.run(
                        ["docker", "image", "inspect", reference], capture_output=True
                    ).returncode
                    == 0
                ):
                    continue
            subprocess.run(command, check=True)
        print("DeepSWE preparation complete; Residual patches remain uncommitted.")
    except (ValueError, KeyError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
