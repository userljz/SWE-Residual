"""Publish the 31 recorded Residual images and record their Docker Hub digests."""

import argparse
import json
import re
import subprocess
from pathlib import Path

from prepare import (
    check_image_identity,
    digest,
    read_json,
    residual_images,
    validate_repository,
)


def publication_plan(root, repository):
    repository = validate_repository(repository)
    return [
        {**image, "push_reference": f"{repository}:{image['tag']}"}
        for image in residual_images(root)
    ]


def write_manifest(root, path, manifest):
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(content)
    temporary.replace(path)
    try:
        relative = path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return
    sums = root / "SHA256SUMS.json"
    if sums.is_file():
        checksums = read_json(sums)
        checksums[relative] = digest(path)
        sums.write_text(
            json.dumps(checksums, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument(
        "--repository", required=True, help="Docker Hub account/repository"
    )
    parser.add_argument(
        "--archive", type=Path, help="Load the existing export before publication"
    )
    parser.add_argument("--output", type=Path, help="Digest manifest output path")
    parser.add_argument(
        "--push",
        action="store_true",
        help="Execute the printed Docker publication plan",
    )
    args = parser.parse_args()
    root = args.root.resolve()
    try:
        plan = publication_plan(root, args.repository)
        if not args.push:
            print(
                json.dumps(
                    {
                        "archive_to_load": str(args.archive) if args.archive else None,
                        "repository": args.repository,
                        "images": plan,
                    },
                    indent=2,
                )
            )
            return
        if args.archive:
            expected = read_json(root / "assets/tb21/image-archive.json")["sha256"]
            if not args.archive.is_file() or digest(args.archive) != expected:
                raise ValueError("Archive does not match the recorded 31-image export")
            subprocess.run(
                ["docker", "load", "-i", str(args.archive.resolve())], check=True
            )
        # Check every state before uploading the first image.
        for image in plan:
            check_image_identity(
                image["local_reference"],
                image["image_id"],
                image.get("manifest_digest"),
            )
        manifest = {
            "schema_version": 1,
            "repository": args.repository,
            "publication_status": "in_progress",
            "images": [
                {key: value for key, value in image.items() if key != "push_reference"}
                | {"image_reference": None, "registry_digest": None}
                for image in plan
            ],
        }
        output = (args.output or root / "assets/tb21/dockerhub-images.json").resolve()
        for index, image in enumerate(plan):
            reference = image["push_reference"]
            subprocess.run(
                ["docker", "tag", image["local_reference"], reference], check=True
            )
            print(f"Publishing {image['state_id']}: {reference}", flush=True)
            pushed = subprocess.run(
                ["docker", "push", reference],
                capture_output=True,
                text=True,
                check=True,
            )
            matches = re.findall(
                r"\bdigest:\s*(sha256:[0-9a-f]{64})", pushed.stdout + pushed.stderr
            )
            if not matches:
                raise ValueError(
                    f"Docker push succeeded but returned no registry digest: {reference}"
                )
            registry_digest = matches[-1]
            manifest["images"][index]["registry_digest"] = registry_digest
            manifest["images"][index]["image_reference"] = (
                f"{args.repository}@{registry_digest}"
            )
            manifest["publication_status"] = (
                "complete" if index + 1 == len(plan) else "in_progress"
            )
            write_manifest(root, output, manifest)
            print(f"Published {index + 1}/31: {registry_digest}", flush=True)
        print(f"Completed digest manifest: {output}")
        print(
            "Commit the completed manifest and SHA256SUMS.json to make pinned downloads available."
        )
    except (ValueError, KeyError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
