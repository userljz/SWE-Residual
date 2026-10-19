"""SWE-Residual modification: scrub credentials without damaging task artifacts."""

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any


def sensitive(key: str) -> bool:
    key = key.lower().replace("-", "_")
    return key in {
        "authorization",
        "password",
        "secret",
        "token",
        "api_key",
        "credential",
    } or key.endswith(("_api_key", "_token", "_secret", "_password"))


def _credentials(values: Iterable[str]) -> list[str]:
    return sorted(
        {s for s in values if len(s) >= 12 and s != "[REDACTED]"},
        key=len,
        reverse=True,
    )


def redact(value: Any, credentials: Iterable[str] = ()) -> Any:
    """Remove credential fields and known long secrets from structured logs."""
    if isinstance(value, dict):
        return {
            k: "[REDACTED]"
            if sensitive(k) and isinstance(v, str) and v
            else redact(v, credentials)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [redact(v, credentials) for v in value]
    if isinstance(value, str):
        for secret in _credentials(credentials):
            value = value.replace(secret, "[REDACTED]")
    return value


def secrets_in(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            if sensitive(key) and isinstance(child, str):
                found.update(_credentials([child]))
            else:
                found.update(secrets_in(child))
    elif isinstance(value, list):
        for child in value:
            found.update(secrets_in(child))
    return found


def scrub_directory(root: Path, credentials: Iterable[str] = ()) -> None:
    """Preserve patch bytes; redact JSON fields and known secrets in logs.

    Short placeholders never act as substrings. Symlinks and unreadable files
    are left alone. Raw artifacts still require an audit before publication.
    """
    credentials = _credentials(credentials)
    for path in root.rglob("*"):
        if not path.is_file() or path.is_symlink() or path.suffix == ".patch":
            continue
        if path.suffix not in {".json", ".jsonl", ".txt", ".log", ".yaml", ".yml"}:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        try:
            if path.suffix == ".json":
                original = json.loads(text)
                clean = redact(original, credentials)
                if clean != original:
                    path.write_text(
                        json.dumps(clean, ensure_ascii=False, indent=2) + "\n"
                    )
            elif path.suffix == ".jsonl":
                rows = [json.loads(line) for line in text.splitlines() if line.strip()]
                clean = [redact(row, credentials) for row in rows]
                if clean != rows:
                    path.write_text(
                        "".join(
                            json.dumps(row, ensure_ascii=False) + "\n" for row in clean
                        )
                    )
            else:
                clean = text
                for secret in credentials:
                    clean = clean.replace(secret, "[REDACTED]")
                if clean != text:
                    path.write_text(clean)
        except json.JSONDecodeError:
            # Interrupted writes can leave JSON-shaped files incomplete.
            # Replace only known long secrets; never repair or parse the data.
            clean = text
            for secret in credentials:
                clean = clean.replace(secret, "[REDACTED]")
            if clean != text:
                try:
                    path.write_text(clean)
                except (OSError, UnicodeError):
                    continue
        except (OSError, UnicodeError):
            continue
