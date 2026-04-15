"""Local environment helpers for native Harness development."""

from __future__ import annotations

import os
from pathlib import Path


def _strip_wrapping_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def load_local_env_file(path: str | Path, *, override: bool = False) -> tuple[str, ...]:
    """Load simple KEY=VALUE pairs from a local env file into process env.

    This is intentionally narrow. It supports the local repo convention and avoids
    bringing in another dependency just to remove repetitive shell export steps.
    """

    env_path = Path(path)
    if not env_path.exists():
        return ()

    loaded: list[str] = []
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        normalized_key = key.strip()
        if not normalized_key:
            continue

        if normalized_key in os.environ and not override:
            continue

        os.environ[normalized_key] = _strip_wrapping_quotes(value.strip())
        loaded.append(normalized_key)

    return tuple(loaded)


def load_repo_root_env(*, override: bool = False) -> tuple[str, ...]:
    """Load the repo-root `.env.local` file for native local development."""

    repo_root = Path(__file__).resolve().parents[1]
    return load_local_env_file(repo_root / ".env.local", override=override)


__all__ = ["load_local_env_file", "load_repo_root_env"]
