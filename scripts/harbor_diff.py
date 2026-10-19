"""Regenerate the review diff against the recorded Harbor upstream commit."""

import argparse
import difflib
import io
import os
import subprocess
import tarfile
from pathlib import Path

UPSTREAM_COMMIT = "f03db62fd2ed2ed1f79aefe024cfcbc68a0d759e"


def make_diff(upstream: Path, vendor: Path) -> str:
    archive = subprocess.check_output(["git", "archive", UPSTREAM_COMMIT], cwd=upstream)
    with tarfile.open(fileobj=io.BytesIO(archive)) as bundle:
        original = {
            entry.name: entry.linkname.encode()
            if entry.issym()
            else bundle.extractfile(entry).read()
            for entry in bundle
            if entry.isfile() or entry.issym()
        }
    # DirEntry type information avoids a separate stat call per source file.
    current = {}
    excluded = {".git", ".venv", "__pycache__", ".pytest_cache", ".ruff_cache"}

    def collect(directory):
        for entry in os.scandir(directory):
            if entry.name in excluded:
                continue
            path = Path(entry.path)
            if entry.is_symlink():
                current[str(path.relative_to(vendor))] = os.readlink(path).encode()
            elif entry.is_dir(follow_symlinks=False):
                collect(path)
            elif entry.is_file(follow_symlinks=False):
                current[str(path.relative_to(vendor))] = None

    collect(vendor)
    chunks = []
    for name in sorted(set(original) | set(current)):
        old = original.get(name, b"")
        path = vendor / name
        new = b""
        if name in current:
            link = current[name]
            new = link if link is not None else path.read_bytes()
        if old == new:
            continue
        # Local modifications are text. Fail explicitly if that changes.
        before, after = old.decode("utf-8"), new.decode("utf-8")
        chunks.append(f"diff --git a/{name} b/{name}\n")
        if name not in original:
            chunks.append("new file mode 100644\n")
        elif name not in current:
            chunks.append("deleted file mode 100644\n")
        chunks.extend(
            difflib.unified_diff(
                before.splitlines(keepends=True),
                after.splitlines(keepends=True),
                fromfile=f"a/{name}" if name in original else "/dev/null",
                tofile=f"b/{name}" if name in current else "/dev/null",
            )
        )
    return "".join(chunks)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    result = make_diff(args.upstream, repo / "vendor/harbor")
    output = repo / "patches/changes-from-upstream.patch"
    if args.check:
        if output.read_text() != result:
            raise SystemExit("Review diff does not match the vendored source")
        print("Review diff matches vendored source")
    else:
        output.write_text(result)
        print(f"Wrote {output}")


if __name__ == "__main__":
    main()
