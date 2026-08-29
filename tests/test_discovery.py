import json
from pathlib import Path

import pytest

from reproagent.discovery import (
    _annotation_links,
    _canonical_repo_from_url,
    _nearest_repository_index,
    _visible_ranking_text,
    discover_artifacts,
    discover_paper_artifacts,
    write_discovery,
)
from reproagent.models import PaperDocument, PaperReference


def _paper(*, text: str, pages: list[str], annotations: list[dict[str, object]]):
    return PaperDocument(
        reference=PaperReference(raw="paper.pdf", kind="local-pdf", identifier="paper.pdf"),
        pdf_path=Path("paper.pdf"),
        text=text,
        metadata={"pages": pages, "annotation_links": annotations},
    )


def test_discovery_canonicalizes_and_ranks_official_repository():
    text = (
        "Our code is available at https://github.com/example/official.git. "
        "A baseline uses https://github.com/example/baseline. "
        "Dataset: https://huggingface.co/datasets/example/demo."
    )
    result = discover_artifacts(text)
    assert result.github_repositories[0] == "https://github.com/example/official"
    assert "https://huggingface.co/datasets/example/demo" in result.dataset_urls


def test_discovery_deduplicates_repository_and_dataset_urls():
    text = (
        "Our code: https://github.com/example/project. "
        "Mirror mention https://github.com/example/project.git. "
        "Data https://zenodo.org/records/123/file and https://zenodo.org/records/123/file."
    )
    result = discover_artifacts(text)
    assert result.github_repositories == ("https://github.com/example/project",)
    assert result.repository_candidates[0].occurrences == 2
    assert result.dataset_urls == ("https://zenodo.org/records/123/file",)


def test_canonical_repo_rejects_non_github_url():
    assert _canonical_repo_from_url("https://example.com/a/b") is None


def test_nearest_repository_index_is_stable_and_rejects_empty_input():
    assert _nearest_repository_index(14, [10, 30]) == 0
    with pytest.raises(ValueError, match="must not be empty"):
        _nearest_repository_index(1, [])


def test_annotation_parser_filters_invalid_entries_and_normalizes_page():
    paper = _paper(
        text="paper",
        pages=["paper"],
        annotations=[
            {"url": " https://github.com/example/project ", "page": "2"},
            {"url": "", "page": 1},
            {"url": 123, "page": 1},
            "ignore",
        ],
    )
    assert _annotation_links(paper) == [("https://github.com/example/project", 2)]


def test_visible_text_does_not_promote_annotation_only_repo_over_page_text():
    page_repo = "https://github.com/example/visible"
    annotation_repo = "https://github.com/example/hidden"
    paper = _paper(
        text=f"Visible code {page_repo}\n{annotation_repo}",
        pages=[f"Our official repository is {page_repo}"],
        annotations=[{"url": annotation_repo, "page": 1}],
    )
    assert annotation_repo not in _visible_ranking_text(paper)
    assert page_repo in _visible_ranking_text(paper)


def test_annotation_only_repository_and_dataset_are_discovered_with_provenance():
    repository = "https://github.com/example/annotation-repo"
    dataset = "https://huggingface.co/datasets/example/annotation-data"
    paper = _paper(
        text="No visible repository URL",
        pages=["No visible repository URL"],
        annotations=[
            {"url": repository, "page": 1},
            {"url": dataset, "page": 2},
        ],
    )
    result = discover_paper_artifacts(paper)
    assert result.github_repositories == (repository,)
    assert dataset in result.dataset_urls
    candidate = result.repository_candidates[0]
    assert "PDF link annotation" in candidate.reasons
    assert "early-page annotation" in candidate.reasons
    assert candidate.evidence[0].source == "pdf_annotation"
    assert candidate.evidence[0].page == 1


def test_visible_repository_evidence_retains_page_context():
    repository = "https://github.com/example/official"
    paper = _paper(
        text=f"Our code is available at {repository}",
        pages=["Introduction", f"Our code is available at {repository} for reproduction."],
        annotations=[],
    )
    result = discover_paper_artifacts(paper)
    evidence = result.repository_candidates[0].evidence
    assert evidence
    assert evidence[0].source == "page_text"
    assert evidence[0].page == 2
    assert repository in evidence[0].context


def test_write_discovery_serializes_rank_and_evidence(tmp_path: Path):
    repository = "https://github.com/example/official"
    result = discover_paper_artifacts(
        _paper(
            text=f"Our code is available at {repository}",
            pages=[f"Our code is available at {repository}"],
            annotations=[],
        )
    )
    destination = write_discovery(result, tmp_path / "nested/discovery.json")
    payload = json.loads(destination.read_text(encoding="utf-8"))
    assert payload["github_repositories"] == [repository]
    assert payload["repository_candidates"][0]["evidence"][0]["source"] == "page_text"
