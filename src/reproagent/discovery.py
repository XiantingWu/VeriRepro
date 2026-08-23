from __future__ import annotations

import json
import re
from bisect import bisect_left
from itertools import islice
from pathlib import Path
from typing import Any

from .models import DiscoveryResult, PaperDocument, RepositoryCandidate, RepositoryEvidence

_GITHUB_REPO = re.compile(
    r"https?://(?:www\.)?github\.com/(?P<owner>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+)",
    re.IGNORECASE,
)
_DATASET_URL = re.compile(
    r"https?://(?:www\.)?(?:huggingface\.co/datasets|kaggle\.com/datasets|zenodo\.org/(?:record|records)|figshare\.com/articles/dataset|osf\.io)/[^\s)\]}>,;]+",
    re.IGNORECASE,
)

_CONTEXT_RULES = (
    ("our code", 9),
    ("source code", 8),
    ("code is available", 8),
    ("code available", 7),
    ("official implementation", 8),
    ("official repository", 8),
    ("implementation", 4),
    ("repository", 3),
    ("released at", 4),
    ("available at", 3),
    ("project page", 2),
)
_MAX_EVIDENCE_PER_REPOSITORY = 8
_CONTEXT_RADIUS = 180
_MAX_REPOSITORY_OCCURRENCES = 512
_MAX_REPOSITORY_CANDIDATES = 128
_MAX_CONTEXT_OCCURRENCES_PER_PHRASE = 512
_MAX_DATASET_URLS = 256
_MAX_ANNOTATION_LINKS = 512
_MAX_ANNOTATION_URL_LENGTH = 4096


def _unique(items: list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(items))


def _canonical_repo(match: re.Match[str]) -> str:
    owner = match.group("owner")
    repo = match.group("repo").rstrip(".,;:)").removesuffix(".git")
    return f"https://github.com/{owner}/{repo}"


def _canonical_repo_from_url(url: str) -> str | None:
    match = _GITHUB_REPO.search(url)
    return _canonical_repo(match) if match else None


def _nearest_repository_index(position: int, centers: list[int]) -> int:
    """Return the nearest repository occurrence in logarithmic time."""
    if not centers:
        raise ValueError("repository centers must not be empty")
    insertion = bisect_left(centers, position)
    candidates: list[int] = []
    if insertion < len(centers):
        candidates.append(insertion)
    if insertion > 0:
        candidates.append(insertion - 1)
    return min(candidates, key=lambda index: (abs(position - centers[index]), index))


def _rank_repositories(text: str, matches: list[tuple[str, int, int]]) -> tuple[RepositoryCandidate, ...]:
    by_url: dict[str, dict[str, object]] = {}
    lowered = text.lower()
    centers = [(start + end) // 2 for _, start, end in matches]
    phrase_occurrences: dict[str, list[int]] = {
        phrase: [
            match.start() + len(phrase) // 2
            for match in islice(
                re.finditer(re.escape(phrase), lowered),
                _MAX_CONTEXT_OCCURRENCES_PER_PHRASE,
            )
        ]
        for phrase, _ in _CONTEXT_RULES
    }

    for occurrence_index, (url, start, end) in enumerate(matches):
        record = by_url.setdefault(
            url,
            {"score": 0, "occurrences": 0, "reasons": [], "first": start},
        )
        record["occurrences"] = int(record["occurrences"]) + 1
        record["score"] = int(record["score"]) + 1
        reasons: list[str] = record["reasons"]  # type: ignore[assignment]

        center = centers[occurrence_index]
        for phrase, weight in _CONTEXT_RULES:
            attributed = False
            for phrase_center in phrase_occurrences[phrase]:
                if abs(phrase_center - center) > 320:
                    continue
                if _nearest_repository_index(phrase_center, centers) != occurrence_index:
                    continue
                attributed = True
                break
            if attributed:
                record["score"] = int(record["score"]) + weight
                if phrase not in reasons:
                    reasons.append(phrase)

        if start < min(len(text), 12_000):
            record["score"] = int(record["score"]) + 2
            if "early-paper link" not in reasons:
                reasons.append("early-paper link")

    ranked = [
        RepositoryCandidate(
            url=url,
            score=int(record["score"]),
            occurrences=int(record["occurrences"]),
            reasons=tuple(record["reasons"]),  # type: ignore[arg-type]
        )
        for url, record in by_url.items()
    ]
    ranked.sort(
        key=lambda item: (
            -item.score,
            -item.occurrences,
            int(by_url[item.url]["first"]),
            item.url.lower(),
        )
    )
    return tuple(ranked[:_MAX_REPOSITORY_CANDIDATES])


def discover_artifacts(text: str) -> DiscoveryResult:
    repository_matches: list[tuple[str, int, int]] = []
    for match in islice(_GITHUB_REPO.finditer(text), _MAX_REPOSITORY_OCCURRENCES):
        repository_matches.append((_canonical_repo(match), match.start(), match.end()))

    ranked = _rank_repositories(text, repository_matches)
    datasets = [
        match.group(0).rstrip(".,;:)")
        for match in islice(_DATASET_URL.finditer(text), _MAX_DATASET_URLS)
    ]
    return DiscoveryResult(
        github_repositories=tuple(item.url for item in ranked),
        dataset_urls=_unique(datasets),
        repository_candidates=ranked,
    )


def _annotation_links(paper: PaperDocument) -> list[tuple[str, int]]:
    raw = paper.metadata.get("annotation_links")
    if not isinstance(raw, list):
        return []
    links: list[tuple[str, int]] = []
    for item in raw:
        if len(links) >= _MAX_ANNOTATION_LINKS:
            break
        if not isinstance(item, dict):
            continue
        url = item.get("url")
        page = item.get("page")
        if not isinstance(url, str) or not url.strip():
            continue
        normalized_url = url.strip()
        if len(normalized_url) > _MAX_ANNOTATION_URL_LENGTH:
            continue
        try:
            page_number = int(page)
        except (TypeError, ValueError):
            page_number = 0
        links.append((normalized_url, page_number))
    return links


def _paper_pages(paper: PaperDocument) -> list[str]:
    raw = paper.metadata.get("pages")
    if isinstance(raw, list) and all(isinstance(item, str) for item in raw):
        return list(raw)
    return [paper.text]


def _visible_ranking_text(paper: PaperDocument) -> str:
    """Return visible/search text without accidentally promoting annotation-only URLs.

    Normal ``resolve_paper`` documents keep pure page text in metadata while
    ``paper.text`` may additionally contain URI annotations for deterministic
    discovery. Prefer page text when it already contains GitHub evidence. For
    caller-constructed PaperDocument objects whose pages omit otherwise visible
    text, fall back to ``paper.text`` after removing known annotation URLs.
    """
    page_text = "\n".join(_paper_pages(paper))
    if _GITHUB_REPO.search(page_text):
        return page_text

    fallback = paper.text
    for raw_url, _ in _annotation_links(paper):
        fallback = fallback.replace(raw_url, " ")
    return fallback if _GITHUB_REPO.search(fallback) else page_text


def _context_snippet(text: str, start: int, end: int) -> str:
    left = max(0, start - _CONTEXT_RADIUS)
    right = min(len(text), end + _CONTEXT_RADIUS)
    return re.sub(r"\s+", " ", text[left:right]).strip()


def _evidence_for_repository(paper: PaperDocument, repository: str) -> tuple[RepositoryEvidence, ...]:
    evidence: list[RepositoryEvidence] = []
    seen: set[tuple[str, int | None, str]] = set()

    for page_number, page_text in enumerate(_paper_pages(paper), start=1):
        for match in _GITHUB_REPO.finditer(page_text):
            if _canonical_repo(match).lower() != repository.lower():
                continue
            anchor = RepositoryEvidence(
                source="page_text",
                page=page_number,
                context=_context_snippet(page_text, match.start(), match.end()),
            )
            key = (anchor.source, anchor.page, anchor.context)
            if key not in seen:
                seen.add(key)
                evidence.append(anchor)
            if len(evidence) >= _MAX_EVIDENCE_PER_REPOSITORY:
                return tuple(evidence)

    for raw_url, page_number in _annotation_links(paper):
        canonical = _canonical_repo_from_url(raw_url)
        if canonical is None or canonical.lower() != repository.lower():
            continue
        anchor = RepositoryEvidence(
            source="pdf_annotation",
            page=page_number if page_number > 0 else None,
            context=raw_url,
        )
        key = (anchor.source, anchor.page, anchor.context)
        if key not in seen:
            seen.add(key)
            evidence.append(anchor)
        if len(evidence) >= _MAX_EVIDENCE_PER_REPOSITORY:
            break
    return tuple(evidence)


def discover_paper_artifacts(paper: PaperDocument) -> DiscoveryResult:
    """Discover and rank paper artifacts while retaining page-level provenance.

    Visible extracted page text is the primary ranking surface. PDF URI
    annotations are considered separately and conservatively so an invisible
    link cannot override strongly grounded visible-text evidence. Evidence
    anchors are attached after ranking and never fed into LLM quote grounding.
    Candidate/occurrence budgets keep hostile or pathological PDFs from turning
    discovery and downstream model context into unbounded host work.
    """
    visible_text = _visible_ranking_text(paper)
    base = discover_artifacts(visible_text)
    by_url: dict[str, dict[str, Any]] = {
        candidate.url: {
            "score": candidate.score,
            "occurrences": candidate.occurrences,
            "reasons": list(candidate.reasons),
            "order": index,
        }
        for index, candidate in enumerate(base.repository_candidates)
    }
    dataset_urls = list(base.dataset_urls)
    next_order = len(by_url)

    for raw_url, page_number in _annotation_links(paper):
        repository = _canonical_repo_from_url(raw_url)
        if repository and repository not in by_url:
            score = 1
            reasons = ["PDF link annotation"]
            if 0 < page_number <= 2:
                score += 2
                reasons.append("early-page annotation")
            by_url[repository] = {
                "score": score,
                "occurrences": 1,
                "reasons": reasons,
                "order": next_order,
            }
            next_order += 1

        dataset_match = _DATASET_URL.search(raw_url)
        if dataset_match and len(dataset_urls) < _MAX_DATASET_URLS:
            dataset_urls.append(dataset_match.group(0).rstrip(".,;:)"))

    preliminary = [
        RepositoryCandidate(
            url=url,
            score=int(record["score"]),
            occurrences=int(record["occurrences"]),
            reasons=tuple(record["reasons"]),
        )
        for url, record in by_url.items()
    ]
    preliminary.sort(
        key=lambda item: (
            -item.score,
            -item.occurrences,
            int(by_url[item.url]["order"]),
            item.url.lower(),
        )
    )
    selected = preliminary[:_MAX_REPOSITORY_CANDIDATES]
    ranked = tuple(
        RepositoryCandidate(
            url=item.url,
            score=item.score,
            occurrences=item.occurrences,
            reasons=item.reasons,
            evidence=_evidence_for_repository(paper, item.url),
        )
        for item in selected
    )
    return DiscoveryResult(
        github_repositories=tuple(item.url for item in ranked),
        dataset_urls=_unique(dataset_urls)[:_MAX_DATASET_URLS],
        repository_candidates=ranked,
    )


def write_discovery(discovery: DiscoveryResult, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "github_repositories": list(discovery.github_repositories),
        "dataset_urls": list(discovery.dataset_urls),
        "repository_candidates": [
            {
                "url": item.url,
                "score": item.score,
                "occurrences": item.occurrences,
                "reasons": list(item.reasons),
                "evidence": [
                    {"source": anchor.source, "page": anchor.page, "context": anchor.context}
                    for anchor in item.evidence
                ],
            }
            for item in discovery.repository_candidates
        ],
    }
    destination.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return destination
