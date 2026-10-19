#!/usr/bin/env bash
set -euo pipefail
repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd -- "$repo_dir"
# Supply both projects to one resolver so Harbor must come from this checkout.
python -m pip install -e ./vendor/harbor -e '.[dev]'
python scripts/check_install.py
