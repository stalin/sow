"""Load timestamped seed and task modules from disk."""

from __future__ import annotations

import hashlib
import importlib.util
import re
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

from sow.errors import SowModuleError

_FILENAME = re.compile(r"^(?P<version>\d{14})_(?P<name>[a-z0-9_]+)\.py$")


@dataclass(frozen=True)
class SowModule:
    """A discovered seed or task file."""

    kind: str
    version: str
    name: str
    path: Path
    checksum: str
    module: ModuleType
    repeatable: bool


def discover(directory: Path, kind: str) -> list[SowModule]:
    """Return modules in ``directory`` sorted by version.

    Files that do not match ``YYYYMMDDHHMMSS_name.py`` are ignored. A missing
    directory yields an empty list.
    """
    if not directory.is_dir():
        return []
    found: list[SowModule] = []
    for path in sorted(directory.glob("*.py")):
        match = _FILENAME.match(path.name)
        if match is None:
            continue
        module = load_module(path)
        found.append(
            SowModule(
                kind=kind,
                version=match.group("version"),
                name=match.group("name"),
                path=path,
                checksum=file_checksum(path),
                module=module,
                repeatable=kind == "task" and bool(getattr(module, "REPEATABLE", False)),
            )
        )
    return found


def file_checksum(path: Path) -> str:
    """Return the SHA-256 hex digest of a file."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_module(path: Path) -> ModuleType:
    """Import ``path`` as a fresh module."""
    digest = file_checksum(path)[:12]
    module_name = f"sow_dynamic_{path.stem}_{digest}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise SowModuleError(f"Cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        raise SowModuleError(f"Cannot import {path}: {exc}") from exc
    return module
