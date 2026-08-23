from __future__ import annotations

import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path


def safe_workspace_slug(value: str) -> str:
    """Return a filesystem-safe, bounded human-readable workspace prefix."""
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-.")
    return slug[:60] or "artifact"


def allocate_workspace(root: Path, value: str) -> Path:
    """Atomically allocate an isolated workspace below *root*.

    Timestamp-only workspace names can collide when two CLI/API processes start
    during the same clock tick. ``mkdtemp`` performs the final directory
    creation atomically and adds an unpredictable suffix, so concurrent runs
    cannot accidentally share logs, outputs, or scientific evidence.
    """
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    prefix = f"{safe_workspace_slug(value)}-{stamp}-"
    return Path(tempfile.mkdtemp(prefix=prefix, dir=root))
