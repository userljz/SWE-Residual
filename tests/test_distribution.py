"""Distribution checks use recorded metadata and mocked Docker operations."""

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


prepare = load_script("prepare")
publish = load_script("publish_docker")


def test_formal_dataset_counts_and_privacy():
    counts = {
        "deepswe-residual.jsonl": 165,
        "deepswe-clean.jsonl": 90,
        "tb21-fs31-residual.jsonl": 31,
        "tb21-fs31-clean.jsonl": 20,
    }
    for name, count in counts.items():
        entries = prepare.rows(ROOT / "metadata" / name)
        assert len(entries) == count
        assert len({row["asset_id"] for row in entries}) == count
        assert all((ROOT / row["task_package"]).is_dir() for row in entries)
        assert all(
            not any(key.startswith("evaluation_") for key in row) for row in entries
        )
    usage = prepare.rows(ROOT / "metadata/token-usage.jsonl")
    assert len(usage) == 196
    assert not any("reward" in row or "exception" in row for row in usage)


def test_docker_publication_has_exact_unique_formal_states():
    plan = publish.publication_plan(ROOT, "example/swe-residual-tb21")
    assert len(plan) == 31
    assert len({image["push_reference"] for image in plan}) == 31
    assert {image["state_id"] for image in plan} == set(
        prepare.read_json(ROOT / "assets/tb21/catalog.json")
    )
    assert not {"r013", "r036"} & {image["state_id"] for image in plan}


def test_explicit_repository_keeps_source_identity_and_local_tags():
    images = prepare.residual_images(ROOT)
    actions = prepare.residual_actions(ROOT, "example/swe-residual-tb21")
    assert len(actions) == len(images) == 31
    for action, original in zip(actions, images):
        assert action["image_id"] == original["image_id"]
        assert action["local_reference"] == original["local_reference"]
        assert (
            action["remote_reference"] == f"example/swe-residual-tb21:{original['tag']}"
        )


def test_completed_manifest_prefers_digest(tmp_path):
    images = prepare.residual_images(ROOT)
    manifest = tmp_path / "published.json"
    manifest.write_text(
        json.dumps(
            {
                "images": [
                    {
                        **image,
                        "image_reference": "example/swe-residual-tb21@sha256:"
                        + f"{index:064x}",
                    }
                    for index, image in enumerate(images)
                ]
            }
        )
    )
    actions = prepare.residual_actions(ROOT, registry_manifest=manifest)
    assert all("@sha256:" in action["remote_reference"] for action in actions)
    assert all(
        action["manifest_digest"] == action["remote_reference"].split("@")[1]
        for action in actions
    )


def test_manifest_cannot_change_recorded_state(tmp_path):
    images = prepare.residual_images(ROOT)
    manifest = tmp_path / "published.json"
    images[0]["image_id"] = "sha256:" + "0" * 64
    manifest.write_text(
        json.dumps(
            {
                "images": [
                    {
                        **image,
                        "image_reference": "example/swe-residual-tb21@sha256:"
                        + f"{index:064x}",
                    }
                    for index, image in enumerate(images)
                ]
            }
        )
    )
    with pytest.raises(ValueError, match="changes source image"):
        prepare.residual_actions(ROOT, registry_manifest=manifest)


def test_wrong_pulled_image_stops_before_retagging(monkeypatch):
    commands = []

    def fake_run(command, **kwargs):
        commands.append(command)
        return SimpleNamespace(
            stdout=json.dumps({"Id": "sha256:" + "0" * 64}), returncode=0
        )

    monkeypatch.setattr(prepare.subprocess, "run", fake_run)
    action = prepare.residual_actions(ROOT, "example/swe-residual-tb21")[0]
    with pytest.raises(ValueError, match="does not match"):
        prepare.execute_residual(action)
    assert [command[1] for command in commands] == ["pull", "image"]
    assert not any(command[1] == "tag" for command in commands)


@pytest.mark.parametrize("store", ["classic", "containerd"])
def test_identity_supports_both_recorded_digest_types(monkeypatch, store):
    config = "sha256:" + "1" * 64
    manifest = "sha256:" + "2" * 64
    inspected = (
        {"Id": config}
        if store == "classic"
        else {"Id": manifest, "Descriptor": {"digest": manifest}}
    )
    monkeypatch.setattr(
        prepare.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout=json.dumps(inspected)),
    )
    prepare.check_image_identity("example/recorded:state", config, manifest)


def test_containerd_identity_requires_an_approved_manifest(monkeypatch):
    config = "sha256:" + "1" * 64
    manifest = "sha256:" + "2" * 64
    inspected = {"Id": manifest, "Descriptor": {"digest": manifest}}
    monkeypatch.setattr(
        prepare.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout=json.dumps(inspected)),
    )
    with pytest.raises(ValueError, match="does not match"):
        prepare.check_image_identity("example/recorded:state", config)
    with pytest.raises(ValueError, match="does not match"):
        prepare.check_image_identity(
            "example/recorded:state", config, "sha256:" + "3" * 64
        )


def test_clean_only_uses_twenty_official_pinned_images():
    actions = prepare.clean_actions(ROOT)
    assert len(actions) == 20
    assert all(command[:2] == ["docker", "pull"] for command in actions)
    assert all(
        command[2].startswith("alexgshaw/") and "@sha256:" in command[2]
        for command in actions
    )


def test_no_docker_archive_in_git_dataset_manifest():
    sums = prepare.read_json(ROOT / "SHA256SUMS.json")
    assert "assets/tb21/images.tar.gz" not in sums
    assert not (ROOT / "assets/tb21/images.tar.gz").exists()
    assert not any(
        name.endswith(("/runtime.tar.gz", "/runtime.sha256")) for name in sums
    )


def test_changed_asset_is_rejected(tmp_path):
    asset = tmp_path / "assets/tb21/test.bin"
    asset.parent.mkdir(parents=True)
    asset.write_bytes(b"modified-state")
    (tmp_path / "SHA256SUMS.json").write_text(
        json.dumps({"assets/tb21/test.bin": "0" * 64})
    )
    with pytest.raises(ValueError, match="Changed asset"):
        prepare.verify_files(tmp_path, "tb21")


@pytest.mark.parametrize(
    "repository",
    [
        "https://docker.io/example/repo",
        "Example/repo",
        "example/repo:latest",
        "example",
    ],
)
def test_invalid_repositories_are_rejected(repository):
    with pytest.raises(ValueError, match="lowercase"):
        publish.publication_plan(ROOT, repository)
