from __future__ import annotations

import pytest

from scripts.release_checks.action_pin import (
    ActionPinResolutionError,
    resolve_action_ref_commit,
)


def _payload(object_type: str, sha: str) -> dict[str, dict[str, str]]:
    return {"object": {"type": object_type, "sha": sha}}


def test_resolves_lightweight_tag_ref_to_commit() -> None:
    commit = "c" * 40

    assert resolve_action_ref_commit(_payload("commit", commit), {}) == commit


def test_resolves_annotated_tag_ref_to_commit() -> None:
    tag_object = "a" * 40
    commit = "c" * 40

    assert (
        resolve_action_ref_commit(
            _payload("tag", tag_object),
            {tag_object: _payload("commit", commit)},
        )
        == commit
    )


def test_resolves_nested_annotated_tags_to_commit() -> None:
    outer_tag = "a" * 40
    inner_tag = "b" * 40
    commit = "c" * 40

    assert (
        resolve_action_ref_commit(
            _payload("tag", outer_tag),
            {
                outer_tag: _payload("tag", inner_tag),
                inner_tag: _payload("commit", commit),
            },
        )
        == commit
    )


def test_rejects_unsupported_object_type() -> None:
    with pytest.raises(ActionPinResolutionError, match="unsupported object type"):
        resolve_action_ref_commit(_payload("tree", "d" * 40), {})


def test_rejects_blob_object_type() -> None:
    with pytest.raises(ActionPinResolutionError, match="unsupported object type"):
        resolve_action_ref_commit(_payload("blob", "d" * 40), {})


def test_rejects_malformed_sha() -> None:
    with pytest.raises(ActionPinResolutionError, match="invalid object SHA"):
        resolve_action_ref_commit(_payload("commit", "not-a-sha"), {})


def test_rejects_excessive_tag_recursion() -> None:
    outer_tag = "a" * 40
    inner_tag = "b" * 40
    commit = "c" * 40

    with pytest.raises(ActionPinResolutionError, match="depth exceeded"):
        resolve_action_ref_commit(
            _payload("tag", outer_tag),
            {
                outer_tag: _payload("tag", inner_tag),
                inner_tag: _payload("commit", commit),
            },
            max_tag_depth=1,
        )


def test_rejects_tag_cycle() -> None:
    first_tag = "a" * 40
    second_tag = "b" * 40

    with pytest.raises(ActionPinResolutionError, match="cycle"):
        resolve_action_ref_commit(
            _payload("tag", first_tag),
            {
                first_tag: _payload("tag", second_tag),
                second_tag: _payload("tag", first_tag),
            },
        )
