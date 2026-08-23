from __future__ import annotations

import ipaddress
import os
import re
import shutil
import socket
from pathlib import Path
from urllib.parse import quote, urljoin, urlparse

import requests
from pypdf import PdfReader

from .models import PaperDocument, PaperReference

_ARXIV_ID = re.compile(r"^(?P<id>\d{4}\.\d{4,5}(?:v\d+)?)$")
_DOI = re.compile(r"^(?P<doi>10\.\d{4,9}/\S+)$", re.IGNORECASE)
_USER_AGENT = "VeriRepro/0.5 (computational research reproducibility tool)"
_REDIRECT_CODES = {301, 302, 303, 307, 308}
_DEFAULT_MAX_PDF_BYTES = 200 * 1024 * 1024
_MAX_PDF_ANNOTATION_LINKS = 512
_MAX_PDF_ANNOTATION_URL_LENGTH = 4096


class SourceResolutionError(RuntimeError):
    pass


def _max_pdf_bytes() -> int:
    raw = os.getenv("VERIREPRO_MAX_PDF_BYTES", "").strip()
    if not raw:
        return _DEFAULT_MAX_PDF_BYTES
    try:
        value = int(raw)
    except ValueError as exc:
        raise SourceResolutionError("VERIREPRO_MAX_PDF_BYTES must be an integer") from exc
    if value <= 0:
        raise SourceResolutionError("VERIREPRO_MAX_PDF_BYTES must be positive")
    return value


def _host_is_public(host: str) -> bool:
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        return literal.is_global

    try:
        addresses = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise SourceResolutionError(f"could not resolve paper host: {host}") from exc
    if not addresses:
        raise SourceResolutionError(f"paper host resolved to no addresses: {host}")
    found = False
    for entry in addresses:
        raw = entry[4][0]
        try:
            address = ipaddress.ip_address(raw)
        except ValueError:
            continue
        found = True
        if not address.is_global:
            return False
    if not found:
        raise SourceResolutionError(f"paper host resolved to no usable IP addresses: {host}")
    return True


def _validate_pdf_url(url: str, *, resolve_dns: bool = True) -> None:
    parsed = urlparse(url)
    allow_http = os.getenv("VERIREPRO_ALLOW_INSECURE_HTTP", "").strip() == "1"
    schemes = {"https", "http"} if allow_http else {"https"}
    if parsed.scheme not in schemes:
        raise SourceResolutionError("paper downloads require HTTPS")
    if not parsed.hostname:
        raise SourceResolutionError("paper URL has no hostname")
    if parsed.username or parsed.password:
        raise SourceResolutionError("paper URLs with embedded credentials are not allowed")
    if resolve_dns and not _host_is_public(parsed.hostname):
        raise SourceResolutionError(f"paper host is not publicly routable: {parsed.hostname}")


def _safe_pdf_response(url: str, *, timeout: int):
    current = url
    for _ in range(6):
        _validate_pdf_url(current)
        response = requests.get(
            current,
            stream=True,
            timeout=timeout,
            headers={"User-Agent": _USER_AGENT},
            allow_redirects=False,
        )
        if response.status_code not in _REDIRECT_CODES:
            return response
        location = response.headers.get("Location")
        response.close()
        if not location:
            raise SourceResolutionError("paper redirect did not include a Location header")
        current = urljoin(current, location)
    raise SourceResolutionError("paper download exceeded the redirect limit")


def parse_reference(raw: str) -> PaperReference:
    value = raw.strip()
    if not value:
        raise ValueError("paper reference must not be empty")

    path = Path(value).expanduser()
    if path.is_file() and path.suffix.lower() == ".pdf":
        return PaperReference(raw=value, kind="local-pdf", identifier=str(path.resolve()))

    arxiv_match = _ARXIV_ID.fullmatch(value)
    if arxiv_match:
        return PaperReference(raw=value, kind="arxiv", identifier=arxiv_match.group("id"))

    doi_match = _DOI.fullmatch(value)
    if doi_match:
        return PaperReference(raw=value, kind="doi", identifier=doi_match.group("doi"))

    if value.startswith("http://") or value.startswith("https://"):
        parsed = urlparse(value)
        host = parsed.netloc.lower()
        if host in {"arxiv.org", "www.arxiv.org"}:
            candidate = parsed.path.removeprefix("/abs/").removeprefix("/pdf/")
            candidate = candidate.removesuffix(".pdf").strip("/")
            if _ARXIV_ID.fullmatch(candidate):
                return PaperReference(raw=value, kind="arxiv", identifier=candidate)
        if host in {"doi.org", "dx.doi.org"}:
            candidate = parsed.path.lstrip("/")
            if _DOI.fullmatch(candidate):
                return PaperReference(raw=value, kind="doi", identifier=candidate)
        if parsed.path.lower().endswith(".pdf"):
            return PaperReference(raw=value, kind="pdf-url", identifier=value)

    raise ValueError(
        "unsupported paper reference; use an arXiv ID/URL, DOI/doi.org URL, PDF URL, or local PDF"
    )


def _download(url: str, destination: Path, timeout: int = 60) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.part")
    temporary.unlink(missing_ok=True)
    response = None
    total = 0
    limit = _max_pdf_bytes()
    try:
        response = _safe_pdf_response(url, timeout=timeout)
        response.raise_for_status()
        content_type = response.headers.get("content-type", "").lower()
        if "html" in content_type and destination.suffix.lower() == ".pdf":
            raise SourceResolutionError(f"expected a PDF but received {content_type or 'HTML'}")
        content_length = response.headers.get("Content-Length")
        if content_length:
            try:
                declared = int(content_length)
            except ValueError:
                declared = 0
            if declared > limit:
                raise SourceResolutionError(
                    f"paper PDF exceeds VERIREPRO_MAX_PDF_BYTES before download ({declared} > {limit})"
                )
        with temporary.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if not chunk:
                    continue
                total += len(chunk)
                if total > limit:
                    raise SourceResolutionError(
                        f"paper PDF exceeded VERIREPRO_MAX_PDF_BYTES while downloading ({total} > {limit})"
                    )
                handle.write(chunk)
        temporary.replace(destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    finally:
        if response is not None:
            response.close()
    return destination


def _resolve_doi_pdf(doi: str) -> tuple[str, dict[str, object]]:
    endpoint = f"https://api.crossref.org/works/{quote(doi, safe='')}"
    response = requests.get(endpoint, timeout=30, headers={"User-Agent": _USER_AGENT})
    response.raise_for_status()
    message = response.json().get("message", {})
    metadata = {
        "doi": doi,
        "title": (message.get("title") or [None])[0],
        "publisher": message.get("publisher"),
        "url": message.get("URL"),
    }
    for link in message.get("link", []) or []:
        url = link.get("URL")
        content_type = str(link.get("content-type", "")).lower()
        if url and ("pdf" in content_type or str(url).lower().endswith(".pdf")):
            candidate = str(url)
            _validate_pdf_url(candidate, resolve_dns=False)
            return candidate, metadata
    raise SourceResolutionError(
        "DOI metadata resolved, but Crossref did not expose a public PDF. "
        "Download the paper and pass the local PDF path instead."
    )


def _extract_pdf_annotation_links(reader: PdfReader) -> list[dict[str, object]]:
    """Return bounded HTTP(S) URI annotations embedded in the supplied PDF."""
    results: list[dict[str, object]] = []
    seen: set[tuple[int, str]] = set()
    for page_number, page in enumerate(reader.pages, start=1):
        annotations = page.get("/Annots") or []
        for reference in annotations:
            if len(results) >= _MAX_PDF_ANNOTATION_LINKS:
                return results
            try:
                annotation = reference.get_object() if hasattr(reference, "get_object") else reference
                action = annotation.get("/A") if hasattr(annotation, "get") else None
                if hasattr(action, "get_object"):
                    action = action.get_object()
                uri = action.get("/URI") if hasattr(action, "get") else None
            except Exception:
                continue
            if uri is None:
                continue
            url = str(uri).strip()
            if not url or len(url) > _MAX_PDF_ANNOTATION_URL_LENGTH:
                continue
            parsed = urlparse(url)
            if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
                continue
            key = (page_number, url)
            if key in seen:
                continue
            seen.add(key)
            results.append({"url": url, "page": page_number})
    return results


def _searchable_pdf_text(pages: list[str], annotation_links: list[dict[str, object]]) -> str:
    """Add only URI annotations that the page's extracted text omitted.

    ``metadata['pages']`` remains untouched and is the authority for page/quote
    evidence. ``PaperDocument.text`` is the broader deterministic search surface
    used for repository/dataset discovery, so it may include an embedded PDF URI
    that text extraction failed to render.
    """
    links_by_page: dict[int, list[str]] = {}
    for item in annotation_links:
        url = item.get("url")
        page = item.get("page")
        if not isinstance(url, str):
            continue
        try:
            page_number = int(page)
        except (TypeError, ValueError):
            continue
        if not 1 <= page_number <= len(pages):
            continue
        links_by_page.setdefault(page_number, []).append(url)

    searchable_pages: list[str] = []
    for page_number, page_text in enumerate(pages, start=1):
        additions = [
            url
            for url in links_by_page.get(page_number, [])
            if url.lower() not in page_text.lower()
        ]
        if additions:
            searchable_pages.append(page_text + "\n" + "\n".join(dict.fromkeys(additions)))
        else:
            searchable_pages.append(page_text)
    return "\n".join(searchable_pages)


def resolve_paper(raw: str, workspace: Path) -> PaperDocument:
    reference = parse_reference(raw)
    workspace.mkdir(parents=True, exist_ok=True)
    pdf_path = workspace / "paper.pdf"
    metadata: dict[str, object] = {}

    if reference.kind == "local-pdf":
        source = Path(reference.identifier)
        if source.resolve() != pdf_path.resolve():
            shutil.copy2(source, pdf_path)
    elif reference.kind == "arxiv":
        metadata["arxiv_id"] = reference.identifier
        _download(f"https://arxiv.org/pdf/{reference.identifier}", pdf_path)
    elif reference.kind == "pdf-url":
        _download(reference.identifier, pdf_path)
    elif reference.kind == "doi":
        pdf_url, doi_metadata = _resolve_doi_pdf(reference.identifier)
        metadata.update(doi_metadata)
        _download(pdf_url, pdf_path)
    else:
        raise SourceResolutionError(f"unsupported reference kind: {reference.kind}")

    reader = PdfReader(str(pdf_path))
    pages = [(page.extract_text() or "") for page in reader.pages]
    annotation_links = _extract_pdf_annotation_links(reader)
    text = _searchable_pdf_text(pages, annotation_links)
    if not "\n".join(pages).strip():
        raise SourceResolutionError("the PDF contains no extractable text")
    metadata["pages"] = pages
    metadata["page_count"] = len(pages)
    metadata["annotation_links"] = annotation_links
    return PaperDocument(reference=reference, pdf_path=pdf_path, text=text, metadata=metadata)
