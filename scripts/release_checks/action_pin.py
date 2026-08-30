"""Pure helpers for resolving annotated GitHub Action tag references."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

PYPI_PUBLISH_ACTION = "pypa/gh-action-pypi-publish"
PYPI_PUBLISH_ACTION_VERSION = "v1.14.2"
PYPI_PUBLISH_ACTION_TAG_OBJECT_SHA = "a892a5a61159132606e93a2fa6f4358831b04d26"
PYPI_PUBLISH_ACTION_COMMIT_SHA = "dc37677b2e1c63e2034f94d8a5b11f265b73ba33"
PYPI_PUBLISH_ACTION_IMAGE = f"ghcr.io/{PYPI_PUBLISH_ACTION}:{PYPI_PUBLISH_ACTION_COMMIT_SHA}"
MAX_TAG_DEREFERENCE_DEPTH = 8

_GIT_SHA = re.compile(r"^[0-9a-fA-F]{40}$")


class ActionPinResolutionError(ValueError):
    """Raised when a GitHub ref cannot be resolved to a commit safely."""


def _object_record(payload: Any, *, label: str) -> tuple[str, str]:
    if not isinstance(payload, Mapping):
        raise ActionPinResolutionError(f"{label} payload must be an object")
    obj = payload.get("object")
    if not isinstance(obj, Mapping):
        raise ActionPinResolutionError(f"{label} payload is missing an object")

    object_type = obj.get("type")
    object_sha = obj.get("sha")
    if not isinstance(object_type, str) or object_type not in {"commit", "tag"}:
        raise ActionPinResolutionError(f"{label} has unsupported object type")
    if not isinstance(object_sha, str) or not _GIT_SHA.fullmatch(object_sha):
        raise ActionPinResolutionError(f"{label} has an invalid object SHA")
    return object_type, object_sha.lower()


def resolve_action_ref_commit(
    ref_payload: Mapping[str, Any],
    tag_payloads: Mapping[str, Mapping[str, Any]],
    *,
    max_tag_depth: int = MAX_TAG_DEREFERENCE_DEPTH,
) -> str:
    """Resolve a GitHub ref payload to its final commit SHA.

    ``ref_payload`` and ``tag_payloads`` are deterministic API-shaped fixtures;
    this helper deliberately performs no network access. Annotated tags are
    followed until a commit is reached, with bounded depth and cycle checks.
    """

    if (
        isinstance(max_tag_depth, bool)
        or not isinstance(max_tag_depth, int)
        or not 0 <= max_tag_depth <= MAX_TAG_DEREFERENCE_DEPTH
    ):
        raise ActionPinResolutionError("max_tag_depth is outside the safe bound")

    object_type, object_sha = _object_record(ref_payload, label="ref")
    seen_tags: set[str] = set()
    for depth in range(max_tag_depth + 1):
        if object_type == "commit":
            return object_sha
        if object_sha in seen_tags:
            raise ActionPinResolutionError("tag dereference cycle detected")
        if depth >= max_tag_depth:
            raise ActionPinResolutionError("tag dereference depth exceeded")
        seen_tags.add(object_sha)
        nested_payload = tag_payloads.get(object_sha)
        if nested_payload is None:
            raise ActionPinResolutionError(f"missing tag payload for {object_sha}")
        object_type, object_sha = _object_record(nested_payload, label=f"tag {object_sha}")

    raise ActionPinResolutionError("tag dereference depth exceeded")
