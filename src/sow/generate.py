"""Write new seed and task modules."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from sow.errors import SowError
from sow.templates import render_module

_SLUG = re.compile(r"[^a-z0-9]+")
_VALID_SLUG = re.compile(r"[a-z0-9_]+")


def generate_file(
    *,
    kind: str,
    name: str,
    directory: Path,
    async_mode: bool,
    now: datetime | None = None,
) -> Path:
    """Create a timestamped module and return its path."""
    if kind not in {"seed", "task"}:
        raise SowError(f"Unknown kind {kind!r}. Expected 'seed' or 'task'.")
    slug = slugify(name)
    moment = now if now is not None else datetime.now(timezone.utc)
    version = moment.strftime("%Y%m%d%H%M%S")
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{version}_{slug}.py"
    if path.exists():
        raise SowError(f"{path} already exists.")
    source = render_module(kind=kind, name=slug, version=version, async_mode=async_mode)
    path.write_text(source, encoding="utf-8")
    return path


def slugify(name: str) -> str:
    """Turn a generator argument into a filename slug."""
    slug = _SLUG.sub("_", name.strip().lower()).strip("_")
    if not slug or _VALID_SLUG.fullmatch(slug) is None:
        raise SowError(
            f"Invalid name {name!r}. Use letters, numbers, spaces, or hyphens."
        )
    if len(slug) > 200:
        raise SowError(f"Invalid name {name!r}. Use at most 200 characters.")
    return slug
