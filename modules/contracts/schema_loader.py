"""Helpers for loading contract resources from a repo checkout or frozen bundle."""

from __future__ import annotations

import json
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable


def resolve_contract_resource(
    relative_path: str | Path,
    *,
    search_roots: Iterable[Path] | None = None,
) -> Path:
    """Resolve a contract resource from a repo checkout or bundled runtime."""

    candidate_path = Path(relative_path)
    roots = [Path(root) for root in (search_roots or _default_search_roots())]
    for root in roots:
        candidate = root / candidate_path
        if candidate.exists():
            return candidate
    searched = ", ".join(str(root / candidate_path) for root in roots)
    raise FileNotFoundError(f"Harness contract resource was not found: {searched}")


@lru_cache(maxsize=1)
def load_task_envelope_schema() -> dict[str, Any]:
    """Load the canonical TaskEnvelope schema once for validation helpers."""

    schema_path = resolve_contract_resource(Path("schemas") / "task_envelope.schema.json")
    return json.loads(schema_path.read_text(encoding="utf-8"))


def _default_search_roots() -> list[Path]:
    roots: list[Path] = []
    bundled_root = getattr(sys, "_MEIPASS", None)
    if bundled_root:
        roots.append(Path(str(bundled_root)))
    roots.append(Path(__file__).resolve().parents[2])
    return roots
