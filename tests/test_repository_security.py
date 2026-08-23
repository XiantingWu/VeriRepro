from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from reproagent import repository


def test_repository_url_is_canonicalized() -> None:
    assert (
        repository.validate_repository_url("https://www.github.com/Acme/Paper-Code.git")
        == "https://github.com/Acme/Paper-Code"
    )


@pytest.mark.parametrize(
    "url",
    [
        "git@github.com:acme/paper.git",
        "ssh://git@github.com/acme/paper.git",
        "file:///tmp/paper",
        "ext::sh -c id",
        "https://github.com/acme/paper/issues",
        "https://user:pass@github.com/acme/paper",
        "https://github.com/acme/paper?x=1",
    ],
)
def test_repository_url_rejects_unsafe_transports_and_shapes(url: str) -> None:
    with pytest.raises(repository.RepositorySecurityError):
        repository.validate_repository_url(url)


@pytest.mark.parametrize(
    "ref",
    [
        "--upload-pack=evil",
        "main..evil",
        "main@{1}",
        "feature//double",
        "refs/heads/main.lock.",
        "main with spaces",
    ],
)
def test_repository_ref_rejects_unsafe_values(ref: str) -> None:
    with pytest.raises(repository.RepositorySecurityError):
        repository.validate_repository_ref(ref)


def test_clone_uses_hardened_git_protocol_configuration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[list[str]] = []

    def fake_run(command, **kwargs):
        del kwargs
        commands.append(list(command))
        return SimpleNamespace(returncode=0, stderr="", stdout="")

    monkeypatch.setattr(repository.subprocess, "run", fake_run)
    destination = tmp_path / "repo"
    result = repository.clone_repository(
        "https://github.com/acme/paper.git",
        destination,
        ref="v1.2.3",
    )

    assert result == destination
    assert commands[0][:5] == [
        "git",
        "-c",
        "protocol.file.allow=never",
        "-c",
        "protocol.ext.allow=never",
    ]
    assert "filter.lfs.smudge=cat" in commands[0]
    assert "filter.lfs.process=" in commands[0]
    assert "filter.lfs.required=false" in commands[0]
    assert "https://github.com/acme/paper" in commands[0]
    assert "--no-tags" in commands[0]
    assert commands[1][-1] == "v1.2.3"


def test_host_inspection_ignores_symlinked_dependency_and_manifest(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    outside_requirements = tmp_path / "outside-requirements.txt"
    outside_requirements.write_text("torch\nsecret-host-package\n", encoding="utf-8")
    outside_manifest = tmp_path / "outside-manifest.yaml"
    outside_manifest.write_text(
        "version: 1\nexperiment:\n  command: python malicious.py\n",
        encoding="utf-8",
    )

    (repo / "requirements.txt").symlink_to(outside_requirements)
    (repo / "verirepro.yaml").symlink_to(outside_manifest)
    (repo / "reproduce.py").write_text("print('safe')\n", encoding="utf-8")

    profile = repository.inspect_repository(repo)
    assert "requirements.txt" not in profile.dependency_files
    assert profile.manifest_path is None
    assert profile.stacks == ("Python",)
    assert profile.suggested_command == "python reproduce.py"


def test_host_inspection_ignores_symlinked_python_metadata(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside-pyproject.toml"
    outside.write_text(
        "[project]\nname='secret'\nversion='1'\nrequires-python='==3.9'\n",
        encoding="utf-8",
    )
    (repo / "pyproject.toml").symlink_to(outside)

    profile = repository.inspect_repository(repo)
    assert profile.python_requirement is None
    assert profile.dependency_strategy == "none"
    assert "pyproject.toml" not in profile.dependency_files


def test_read_text_with_repo_root_refuses_outside_file(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("do-not-read", encoding="utf-8")
    assert repository._read_text(outside, root=repo) == ""
