#!/bin/bash
# Reuse an audited runtime, or install the exact public dependency versions.
set -euo pipefail
tests_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
runtime_root="${TB21_VERIFIER_RUNTIME_ROOT:-/opt/tb21-verifier}"
log_dir="${TB21_VERIFIER_LOG_DIR:-/logs/verifier}"
mkdir -p "$runtime_root" "$log_dir"
profile="$tests_dir/runtime-profile.json"
profile_hash="$(sha256sum "$profile" | cut -d ' ' -f 1)"
venv="$runtime_root/venvs/$profile_hash"

audit() {
    "$1" -I "$tests_dir/runtime_audit.py" \
        --profile "$profile" --output "$log_dir/runtime-policy.json" >&2
}

# The second candidate supports environments prepared by previous local runs.
for candidate in "$venv/bin/python" "$runtime_root/venv/bin/python"; do
    if [ -x "$candidate" ] && audit "$candidate"; then
        echo 'VERIFIER_RUNTIME_REUSED: pinned Python and package versions match' >&2
        printf '%s\n' "$candidate"
        exit 0
    fi
done

echo 'VERIFIER_RUNTIME_INSTALL: preparing pinned dependencies from public sources' >&2
if command -v uv >/dev/null 2>&1; then
    uv_bin="$(command -v uv)"
elif [ -x "$runtime_root/bin/uv" ]; then
    uv_bin="$runtime_root/bin/uv"
elif [ -x "$runtime_root/uv-bootstrap/bin/uv" ]; then
    uv_bin="$runtime_root/uv-bootstrap/bin/uv"
else
    installer="$runtime_root/uv-0.9.5-installer.sh"
    installer_url='https://astral.sh/uv/0.9.5/install.sh'
    if command -v curl >/dev/null 2>&1; then
        curl --fail --location --retry 3 "$installer_url" --output "$installer" >&2
    elif command -v wget >/dev/null 2>&1; then
        wget -O "$installer" "$installer_url" >&2
    elif command -v python3 >/dev/null 2>&1; then
        python3 -m venv "$runtime_root/uv-bootstrap" >&2
        "$runtime_root/uv-bootstrap/bin/python" -m pip --isolated install \
            --disable-pip-version-check --no-deps --only-binary=:all: \
            --index-url https://pypi.org/simple uv==0.9.5 >&2
        uv_bin="$runtime_root/uv-bootstrap/bin/uv"
    elif command -v apt-get >/dev/null 2>&1 && [ "$(id -u)" = 0 ]; then
        apt-get update >&2
        DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends curl ca-certificates >&2
        curl --fail --location --retry 3 "$installer_url" --output "$installer" >&2
    else
        echo 'VERIFIER_BOOTSTRAP_ERROR: install curl or wget to bootstrap uv' >&2
        exit 70
    fi
    if [ -z "${uv_bin:-}" ]; then
        UV_UNMANAGED_INSTALL="$runtime_root/bin" sh "$installer" >&2
        uv_bin="$runtime_root/bin/uv"
    fi
fi

read -r python_version < "$tests_dir/runtime-python.txt"
export UV_PYTHON_INSTALL_DIR="$runtime_root/python"
export UV_CACHE_DIR="$runtime_root/download-cache"
export UV_LINK_MODE=copy
# Distribution must work without the publisher's private package mirrors.
unset UV_INDEX UV_DEFAULT_INDEX UV_INDEX_URL UV_EXTRA_INDEX_URL UV_FIND_LINKS
unset PIP_INDEX_URL PIP_EXTRA_INDEX_URL PIP_FIND_LINKS
"$uv_bin" --no-config venv --python "$python_version" --allow-existing "$venv" >&2
py="$venv/bin/python"
"$uv_bin" --no-config pip sync --python "$py" --only-binary :all: \
    --default-index https://pypi.org/simple "$tests_dir/runtime-requirements.txt" >&2
if [ -f "$tests_dir/runtime-torch-requirements.txt" ]; then
    "$uv_bin" --no-config pip install --python "$py" --no-deps --only-binary :all: \
        --default-index https://download.pytorch.org/whl/cpu \
        -r "$tests_dir/runtime-torch-requirements.txt" >&2
fi
audit "$py"
echo 'VERIFIER_RUNTIME_INSTALLED: dependency audit passed' >&2
printf '%s\n' "$py"
