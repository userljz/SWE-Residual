"""SWE-Residual modification: alias musl extensions only when Python needs it."""

import sys
from importlib.machinery import EXTENSION_SUFFIXES
from pathlib import Path


def repair_extensions(root: Path, suffixes: list[str] | None = None) -> None:
    """Keep original modules and refuse to replace an existing alias.

    Called by the newly installed tool's interpreter. Pre-mounted installs are
    not modified. Interpreters that already accept the musl suffix need no fix.
    """
    suffixes = EXTENSION_SUFFIXES if suffixes is None else suffixes
    if any("-linux-musl.so" in suffix for suffix in suffixes):
        return
    for source in root.rglob("*-linux-musl.so"):
        target = source.with_name(
            source.name.replace("-linux-musl.so", "-linux-gnu.so")
        )
        if not any(target.name.endswith(s) for s in suffixes if s != ".so"):
            continue
        if target.exists() or target.is_symlink():
            continue
        target.symlink_to(source.name)


if __name__ == "__main__":
    repair_extensions(Path(sys.argv[1]))
