from __future__ import annotations

import shutil
import socket
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests
from pypdf import PdfReader, PdfWriter
from pypdf.annotations import Link
from pypdf.errors import PdfReadError
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from reproagent import sources


class FakeResponse:
    def __init__(
        self,
        *,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
        chunks: tuple[bytes, ...] = (),
        body: object = None,
    ) -> None:
        self.status_code = status_code
        self.headers = headers or {}
        self._chunks = chunks
        self._body = body
        self.closed = False

    def close(self) -> None:
        self.closed = True

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code} error")

    def json(self) -> object:
        if self._body is None:
            raise ValueError("no JSON body configured")
        return self._body

    def iter_content(self, chunk_size: int):
        del chunk_size
        yield from self._chunks


def _build_pdf(path: Path, *, text: str | None = None, urls: tuple[str, ...] = ()) -> Path:
    writer = PdfWriter()
    page = writer.add_blank_page(width=300, height=300)
    if text is not None:
        escaped = text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
        font = DictionaryObject()
        font[NameObject("/Type")] = NameObject("/Font")
        font[NameObject("/Subtype")] = NameObject("/Type1")
        font[NameObject("/BaseFont")] = NameObject("/Helvetica")
        font_ref = writer._add_object(font)
        contents = DecodedStreamObject()
        contents.set_data(f"BT /F1 12 Tf 24 240 Td ({escaped}) Tj ET".encode("latin-1"))
        contents_ref = writer._add_object(contents)
        page[NameObject("/Contents")] = contents_ref
        fonts = DictionaryObject({NameObject("/F1"): font_ref})
        resources = DictionaryObject({NameObject("/Font"): fonts})
        page[NameObject("/Resources")] = resources
    for url in urls:
        writer.add_annotation(page_number=0, annotation=Link(rect=(10, 10, 200, 40), url=url))
    with path.open("wb") as handle:
        writer.write(handle)
    return path


class _RaisingAnnot:
    def get_object(self) -> object:
        raise ValueError("malformed annotation object")


def _fake_reader(pages: list[list[object]]) -> SimpleNamespace:
    def page_get(annots):
        def get(key: str) -> object:
            if key == "/Annots":
                return annots
            return None

        return get

    return SimpleNamespace(pages=[SimpleNamespace(get=page_get(annots)) for annots in pages])


def test_parse_reference_rejects_empty_input() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        sources.parse_reference("   ")


def test_parse_reference_error_names_accepted_forms() -> None:
    with pytest.raises(ValueError, match="unsupported paper reference") as exc_info:
        sources.parse_reference("definitely-not-a-paper")
    message = str(exc_info.value)
    assert "arXiv" in message
    assert "DOI" in message
    assert "PDF" in message


@pytest.mark.parametrize(
    "raw",
    ["2310.12345", "  2310.12345  ", "2401.00001v2"],
)
def test_parse_reference_accepts_arxiv_ids(raw: str) -> None:
    reference = sources.parse_reference(raw)
    assert reference.kind == "arxiv"
    assert reference.identifier == raw.strip()


@pytest.mark.parametrize(
    "raw",
    ["2310.123456", "2310.123", "2310_12345", "not-an-arxiv-id"],
)
def test_parse_reference_rejects_malformed_arxiv_ids(raw: str) -> None:
    with pytest.raises(ValueError, match="unsupported paper reference"):
        sources.parse_reference(raw)


@pytest.mark.parametrize(
    ("raw", "identifier"),
    [
        ("https://arxiv.org/abs/2310.12345", "2310.12345"),
        ("https://arxiv.org/pdf/2310.12345", "2310.12345"),
        ("https://arxiv.org/pdf/2310.12345v1.pdf", "2310.12345v1"),
        ("https://www.arxiv.org/abs/2401.00001v3", "2401.00001v3"),
    ],
)
def test_parse_reference_accepts_arxiv_urls(raw: str, identifier: str) -> None:
    reference = sources.parse_reference(raw)
    assert reference.kind == "arxiv"
    assert reference.identifier == identifier


def test_parse_reference_arxiv_url_with_invalid_id_is_rejected() -> None:
    with pytest.raises(ValueError, match="unsupported paper reference"):
        sources.parse_reference("https://arxiv.org/abs/not-an-id")


@pytest.mark.parametrize(
    ("raw", "identifier"),
    [
        ("10.1234/some.journal.2024", "10.1234/some.journal.2024"),
        ("https://doi.org/10.1234/some.journal.2024", "10.1234/some.journal.2024"),
        ("https://dx.doi.org/10.5555/ABC-def", "10.5555/ABC-def"),
    ],
)
def test_parse_reference_accepts_doi_forms(raw: str, identifier: str) -> None:
    reference = sources.parse_reference(raw)
    assert reference.kind == "doi"
    assert reference.identifier == identifier


def test_parse_reference_accepts_generic_pdf_url() -> None:
    reference = sources.parse_reference("https://papers.example.org/deep/model.pdf")
    assert reference.kind == "pdf-url"
    assert reference.identifier == "https://papers.example.org/deep/model.pdf"


def test_parse_reference_rejects_non_pdf_http_url() -> None:
    with pytest.raises(ValueError, match="unsupported paper reference"):
        sources.parse_reference("https://papers.example.org/page.html")


def test_parse_reference_detects_local_pdf_file(tmp_path: Path) -> None:
    pdf_path = _build_pdf(tmp_path / "local.pdf")
    reference = sources.parse_reference(str(pdf_path))
    assert reference.kind == "local-pdf"
    assert reference.identifier == str(pdf_path.resolve())


@pytest.mark.parametrize(
    ("env_value", "expected"),
    [
        (None, sources._DEFAULT_MAX_PDF_BYTES),
        ("42", 42),
        ("junk", None),
        ("0", None),
        ("-3", None),
    ],
)
def test_max_pdf_bytes_env_parsing(
    monkeypatch: pytest.MonkeyPatch,
    env_value: str | None,
    expected: int | None,
) -> None:
    if env_value is None:
        monkeypatch.delenv("VERIREPRO_MAX_PDF_BYTES", raising=False)
    else:
        monkeypatch.setenv("VERIREPRO_MAX_PDF_BYTES", env_value)
    if env_value in {"junk", "0", "-3"}:
        fragment = "must be positive" if env_value in {"0", "-3"} else "must be an integer"
        with pytest.raises(sources.SourceResolutionError, match=fragment):
            sources._max_pdf_bytes()
    else:
        assert sources._max_pdf_bytes() == expected


@pytest.mark.parametrize("url", ["ftp://example.org/a.pdf", "file:///tmp/a.pdf"])
def test_validate_pdf_url_requires_https_scheme(url: str) -> None:
    with pytest.raises(sources.SourceResolutionError, match="require HTTPS"):
        sources._validate_pdf_url(url, resolve_dns=False)


def test_validate_pdf_url_allows_http_only_when_opted_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("VERIREPRO_ALLOW_INSECURE_HTTP", raising=False)
    with pytest.raises(sources.SourceResolutionError, match="require HTTPS"):
        sources._validate_pdf_url("http://example.org/a.pdf", resolve_dns=False)
    monkeypatch.setenv("VERIREPRO_ALLOW_INSECURE_HTTP", "1")
    sources._validate_pdf_url("http://example.org/a.pdf", resolve_dns=False)


@pytest.mark.parametrize(
    "url", ["https:///missing-host/a.pdf", "https://user:pw@example.org/a.pdf"]
)
def test_validate_pdf_url_rejects_missing_host_and_credentials(url: str) -> None:
    fragment = "embedded credentials" if "@" in url else "no hostname"
    with pytest.raises(sources.SourceResolutionError, match=fragment):
        sources._validate_pdf_url(url, resolve_dns=False)


@pytest.mark.parametrize(
    "url",
    ["https://127.0.0.1/a.pdf", "https://[::1]/a.pdf", "https://10.0.0.9/a.pdf"],
)
def test_validate_pdf_url_rejects_private_ip_literals(url: str) -> None:
    with pytest.raises(sources.SourceResolutionError, match="not publicly routable"):
        sources._validate_pdf_url(url)


def test_validate_pdf_url_reports_dns_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_getaddrinfo(host: object, *args: object, **kwargs: object) -> list[object]:
        del args, kwargs
        raise socket.gaierror(-2, "name resolution failed")

    monkeypatch.setattr(sources.socket, "getaddrinfo", fail_getaddrinfo)
    with pytest.raises(sources.SourceResolutionError, match="could not resolve paper host"):
        sources._validate_pdf_url("https://unresolvable.example/a.pdf")


def test_validate_pdf_url_rejects_hosts_without_addresses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sources.socket, "getaddrinfo", lambda host, *a, **k: [])
    with pytest.raises(sources.SourceResolutionError, match="resolved to no addresses"):
        sources._validate_pdf_url("https://empty.example/a.pdf")


def test_validate_pdf_url_rejects_hosts_without_usable_ips(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bogus = [(2, 1, 6, "", ("not-an-ip", 0))]
    monkeypatch.setattr(sources.socket, "getaddrinfo", lambda host, *a, **k: bogus)
    with pytest.raises(sources.SourceResolutionError, match="no usable IP addresses"):
        sources._validate_pdf_url("https://weird.example/a.pdf")


def test_validate_pdf_url_private_dns_answer_wins_over_public(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    answers = [(2, 1, 6, "", ("8.8.8.8", 0)), (2, 1, 6, "", ("192.168.1.5", 0))]
    monkeypatch.setattr(sources.socket, "getaddrinfo", lambda host, *a, **k: answers)
    with pytest.raises(sources.SourceResolutionError, match="not publicly routable"):
        sources._validate_pdf_url("https://mixed.example/a.pdf")


def test_validate_pdf_url_accepts_public_dns_answers(monkeypatch: pytest.MonkeyPatch) -> None:
    answers = [(2, 1, 6, "", ("93.184.216.34", 0)), (2, 1, 6, "", ("2606:2800::1", 0))]
    monkeypatch.setattr(sources.socket, "getaddrinfo", lambda host, *a, **k: answers)
    sources._validate_pdf_url("https://public.example/a.pdf")


class RedirectServer:
    def __init__(self, hops: list[tuple[int, str | None]]) -> None:
        self.hops = hops
        self.calls: list[str] = []
        self.closed: list[FakeResponse] = []

    def __call__(self, url: str, **kwargs: object) -> FakeResponse:
        del kwargs
        index = min(len(self.calls), len(self.hops) - 1)
        status, location = self.hops[index]
        self.calls.append(url)
        headers = {"Location": location} if location else {}
        response = FakeResponse(status_code=status, headers=headers)
        self.closed.append(response)
        return response

    @property
    def final(self) -> FakeResponse:
        return self.closed[-1]


def _public_hosts(host: str) -> bool:
    return host.endswith(".example")


def test_safe_pdf_response_resolves_relative_redirects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = RedirectServer([(302, "/papers/final.pdf"), (200, None)])
    monkeypatch.setattr(sources, "_host_is_public", _public_hosts)
    monkeypatch.setattr(sources.requests, "get", server)

    response = sources._safe_pdf_response("https://cdn.example/a.pdf", timeout=5)

    assert response is server.final
    assert server.calls == [
        "https://cdn.example/a.pdf",
        "https://cdn.example/papers/final.pdf",
    ]
    assert response.status_code == 200


def test_safe_pdf_response_rejects_redirect_without_location(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = RedirectServer([(302, None)])
    monkeypatch.setattr(sources, "_host_is_public", _public_hosts)
    monkeypatch.setattr(sources.requests, "get", server)

    with pytest.raises(
        sources.SourceResolutionError,
        match="redirect did not include a Location header",
    ):
        sources._safe_pdf_response("https://cdn.example/a.pdf", timeout=5)
    assert server.final.closed is True


def test_safe_pdf_response_enforces_redirect_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    server = RedirectServer([(302, "https://loop.example/next.pdf")])
    monkeypatch.setattr(sources, "_host_is_public", _public_hosts)
    monkeypatch.setattr(sources.requests, "get", server)

    with pytest.raises(sources.SourceResolutionError, match="exceeded the redirect limit"):
        sources._safe_pdf_response("https://loop.example/start.pdf", timeout=5)
    assert len(server.calls) == 6
    assert all(response.closed for response in server.closed)


def test_download_http_error_status_keeps_workspace_clean(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = FakeResponse(status_code=403, headers={"content-type": "application/pdf"})
    monkeypatch.setattr(sources, "_safe_pdf_response", lambda *args, **kwargs: response)

    destination = tmp_path / "paper.pdf"
    with pytest.raises(requests.HTTPError, match="HTTP 403"):
        sources._download("https://example.org/paper.pdf", destination)

    assert not destination.exists()
    assert not (tmp_path / ".paper.pdf.part").exists()
    assert response.closed is True


def test_download_connection_error_cleans_partial_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*args: object, **kwargs: object) -> object:
        raise requests.ConnectionError("peer reset")

    monkeypatch.setattr(sources, "_safe_pdf_response", fail)

    destination = tmp_path / "paper.pdf"
    with pytest.raises(requests.ConnectionError):
        sources._download("https://example.org/paper.pdf", destination)

    assert not destination.exists()
    assert not (tmp_path / ".paper.pdf.part").exists()


def test_download_rejects_html_payload(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    response = FakeResponse(
        headers={"content-type": "text/html; charset=utf-8"},
        chunks=(b"<html>captcha</html>",),
    )
    monkeypatch.setattr(sources, "_safe_pdf_response", lambda *args, **kwargs: response)

    destination = tmp_path / "paper.pdf"
    with pytest.raises(sources.SourceResolutionError, match="expected a PDF but received"):
        sources._download("https://example.org/paper.pdf", destination)

    assert not destination.exists()
    assert response.closed is True


def test_download_enforces_size_limit_while_streaming(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = FakeResponse(
        headers={"content-type": "application/pdf"},
        chunks=(b"a" * 700_000, b"b" * 700_000),
    )
    monkeypatch.setattr(sources, "_safe_pdf_response", lambda *args, **kwargs: response)
    monkeypatch.setattr(sources, "_max_pdf_bytes", lambda: 1_000_000)

    destination = tmp_path / "paper.pdf"
    with pytest.raises(
        sources.SourceResolutionError,
        match="exceeded VERIREPRO_MAX_PDF_BYTES while downloading",
    ):
        sources._download("https://example.org/paper.pdf", destination)

    assert not destination.exists()
    assert not (tmp_path / ".paper.pdf.part").exists()


def test_download_tolerates_garbage_content_length(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = b"%PDF-1.4 tiny"
    response = FakeResponse(
        headers={"content-type": "application/pdf", "Content-Length": "not-a-number"},
        chunks=(b"", payload[:6], payload[6:]),
    )
    monkeypatch.setattr(sources, "_safe_pdf_response", lambda *args, **kwargs: response)

    destination = tmp_path / "paper.pdf"
    assert sources._download("https://example.org/paper.pdf", destination) == destination
    assert destination.read_bytes() == payload
    assert response.closed is True


def _crossref_response(links: list[dict[str, object]]) -> FakeResponse:
    return FakeResponse(
        body={
            "message": {
                "title": ["A Reproducible Paper"],
                "publisher": "Open Press",
                "URL": "https://doi.example/landing",
                "link": links,
            }
        }
    )


def test_resolve_doi_pdf_selects_pdf_link_and_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = _crossref_response(
        [
            {"URL": "https://publisher.example/read-online", "content-type": "text/html"},
            {
                "URL": "https://publisher.example/downloads/paper.pdf",
                "content-type": "application/pdf",
            },
        ]
    )
    seen: dict[str, object] = {}

    def fake_get(url: str, **kwargs: object) -> FakeResponse:
        seen["url"] = url
        seen["timeout"] = kwargs.get("timeout")
        return response

    monkeypatch.setattr(sources.requests, "get", fake_get)

    pdf_url, metadata = sources._resolve_doi_pdf("10.1234/demo.paper")

    assert pdf_url == "https://publisher.example/downloads/paper.pdf"
    assert seen["url"] == "https://api.crossref.org/works/10.1234%2Fdemo.paper"
    assert seen["timeout"] == 30
    assert metadata["doi"] == "10.1234/demo.paper"
    assert metadata["title"] == "A Reproducible Paper"
    assert metadata["publisher"] == "Open Press"
    assert metadata["url"] == "https://doi.example/landing"


def test_resolve_doi_pdf_accepts_pdf_suffix_without_content_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = _crossref_response([{"URL": "https://publisher.example/paper.PDF"}])
    monkeypatch.setattr(sources.requests, "get", lambda url, **kwargs: response)

    pdf_url, _metadata = sources._resolve_doi_pdf("10.1234/demo.paper")
    assert pdf_url == "https://publisher.example/paper.PDF"


def test_resolve_doi_pdf_errors_without_public_pdf(monkeypatch: pytest.MonkeyPatch) -> None:
    response = _crossref_response([{"URL": "https://publisher.example/landing"}])
    monkeypatch.setattr(sources.requests, "get", lambda url, **kwargs: response)

    with pytest.raises(sources.SourceResolutionError, match="did not expose a public PDF"):
        sources._resolve_doi_pdf("10.1234/demo.paper")


def test_resolve_doi_pdf_surfaces_crossref_http_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        sources.requests,
        "get",
        lambda url, **kwargs: FakeResponse(status_code=502),
    )

    with pytest.raises(requests.HTTPError, match="HTTP 502"):
        sources._resolve_doi_pdf("10.1234/demo.paper")


def test_resolve_doi_pdf_validates_candidate_scheme(monkeypatch: pytest.MonkeyPatch) -> None:
    response = _crossref_response([{"URL": "http://insecure.example/paper.pdf"}])
    monkeypatch.setattr(sources.requests, "get", lambda url, **kwargs: response)

    with pytest.raises(sources.SourceResolutionError, match="require HTTPS"):
        sources._resolve_doi_pdf("10.1234/demo.paper")


def test_extract_pdf_annotation_links_from_real_pdf(tmp_path: Path) -> None:
    pdf_path = _build_pdf(
        tmp_path / "linked.pdf",
        urls=(
            "https://github.com/example/repro",
            "https://github.com/example/repro",
            "https://data.example/dataset.zip",
        ),
    )
    links = sources._extract_pdf_annotation_links(PdfReader(str(pdf_path)))

    assert links == [
        {"url": "https://github.com/example/repro", "page": 1},
        {"url": "https://data.example/dataset.zip", "page": 1},
    ]


def test_extract_pdf_annotation_links_filters_unusable_entries() -> None:
    oversized = "https://big.example/" + "a" * 5000
    reader = _fake_reader(
        [
            [
                _RaisingAnnot(),
                {"/A": {"/URI": "javascript:alert(1)"}},
                {"/A": {"/URI": "mailto:author@example.org"}},
                {"/A": {"/URI": "https://"}},
                {"/A": {"/URI": oversized}},
                {"/A": {"/URI": "ftp://files.example/a.zip"}},
                {"/B": {"/URI": "https://ignored.example/no-action-uri"}},
                {"/A": {"/URI": "https://good.example/repo"}},
                {"/A": {"/URI": "https://good.example/repo"}},
            ],
            [{"/A": {"/URI": "https://good.example/repo"}}],
        ]
    )

    links = sources._extract_pdf_annotation_links(reader)

    assert links == [
        {"url": "https://good.example/repo", "page": 1},
        {"url": "https://good.example/repo", "page": 2},
    ]


def test_extract_pdf_annotation_links_are_bounded() -> None:
    cap = sources._MAX_PDF_ANNOTATION_LINKS
    flood = [{"/A": {"/URI": f"https://h{n}.example/{n}"}} for n in range(cap + 64)]
    links = sources._extract_pdf_annotation_links(_fake_reader([flood]))
    assert len(links) == cap


def test_searchable_pdf_text_merges_only_missing_links() -> None:
    pages = ["intro text", "see HTTPS://DUP.EXAMPLE/ here", "outro"]
    links = [
        {"url": "https://a.example/x", "page": 1},
        {"url": "https://dup.example/", "page": 2},
        {"url": "https://late.example/y", "page": 2},
        {"url": "https://oob.example/z", "page": 99},
        {"url": "https://bad.example/w", "page": "abc"},
        {"url": "https://none.example/v", "page": None},
        {"url": 123, "page": 1},
        {"url": "https://a.example/x", "page": 1},
    ]

    merged = sources._searchable_pdf_text(pages, links)
    assert merged == (
        "intro text\nhttps://a.example/x\n"
        "see HTTPS://DUP.EXAMPLE/ here\nhttps://late.example/y\n"
        "outro"
    )


def test_resolve_paper_success_with_real_text_pdf(tmp_path: Path) -> None:
    pdf_path = _build_pdf(
        tmp_path / "source.pdf",
        text="Gradient descent converges linearly",
        urls=("https://github.com/example/repro",),
    )

    document = sources.resolve_paper(str(pdf_path), tmp_path / "ws")

    assert document.reference.kind == "local-pdf"
    assert document.pdf_path == tmp_path / "ws" / "paper.pdf"
    assert document.pdf_path.read_bytes() == pdf_path.read_bytes()
    assert "Gradient descent converges linearly" in document.text
    assert "https://github.com/example/repro" in document.text
    assert document.metadata["page_count"] == 1
    assert document.metadata["pages"] == ["Gradient descent converges linearly"]
    assert document.metadata["annotation_links"] == [
        {"url": "https://github.com/example/repro", "page": 1}
    ]


def test_resolve_paper_accepts_pdf_already_in_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    pdf_path = _build_pdf(workspace / "paper.pdf", text="Already in place")

    document = sources.resolve_paper(str(pdf_path), workspace)

    assert document.pdf_path == pdf_path
    assert "Already in place" in document.text


def test_resolve_paper_blank_pdf_is_typed_failure(tmp_path: Path) -> None:
    pdf_path = _build_pdf(tmp_path / "blank.pdf")

    with pytest.raises(sources.SourceResolutionError, match="no extractable text"):
        sources.resolve_paper(str(pdf_path), tmp_path / "ws")


def test_resolve_paper_corrupt_bytes_raise_typed_pypdf_error(tmp_path: Path) -> None:
    pdf_path = tmp_path / "corrupt.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 this is truncated garbage \x00\x01\xff")

    with pytest.raises(PdfReadError):
        sources.resolve_paper(str(pdf_path), tmp_path / "ws")


def test_resolve_paper_rejects_declared_size_before_downloading(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = FakeResponse(
        headers={"content-type": "application/pdf", "Content-Length": "11"},
        chunks=(b"01234567890",),
    )
    monkeypatch.setattr(sources, "_safe_pdf_response", lambda *args, **kwargs: response)
    monkeypatch.setattr(sources, "_max_pdf_bytes", lambda: 10)

    destination = tmp_path / "paper.pdf"
    with pytest.raises(
        sources.SourceResolutionError,
        match="exceeds VERIREPRO_MAX_PDF_BYTES before download",
    ):
        sources._download("https://example.org/paper.pdf", destination)

    assert not destination.exists()
    assert response.closed is True


def test_resolve_paper_pdf_url_kind_downloads_given_url(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_pdf = _build_pdf(tmp_path / "real.pdf", text="Direct PDF content")
    downloads: list[str] = []

    def fake_download(url: str, destination: Path, timeout: int = 60) -> Path:
        del timeout
        downloads.append(url)
        shutil.copyfile(real_pdf, destination)
        return destination

    monkeypatch.setattr(sources, "_download", fake_download)

    document = sources.resolve_paper("https://papers.example.org/deep/model.pdf", tmp_path / "ws")

    assert downloads == ["https://papers.example.org/deep/model.pdf"]
    assert document.reference.kind == "pdf-url"
    assert "Direct PDF content" in document.text


def test_resolve_paper_doi_kind_merges_crossref_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_pdf = _build_pdf(tmp_path / "real.pdf", text="DOI resolved content")
    monkeypatch.setattr(
        sources,
        "_resolve_doi_pdf",
        lambda doi: (
            "https://publisher.example/downloads/paper.pdf",
            {"doi": doi, "title": "Resolved Title"},
        ),
    )

    def fake_download(url: str, destination: Path, timeout: int = 60) -> Path:
        del url, timeout
        shutil.copyfile(real_pdf, destination)
        return destination

    monkeypatch.setattr(sources, "_download", fake_download)

    document = sources.resolve_paper("10.1234/demo.paper", tmp_path / "ws")

    assert document.reference.kind == "doi"
    assert document.metadata["doi"] == "10.1234/demo.paper"
    assert document.metadata["title"] == "Resolved Title"
    assert "DOI resolved content" in document.text


def test_resolve_paper_arxiv_kind_downloads_canonical_url(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_pdf = _build_pdf(tmp_path / "real.pdf", text="Arxiv mirror content")
    downloads: list[str] = []

    def fake_download(url: str, destination: Path, timeout: int = 60) -> Path:
        del timeout
        downloads.append(url)
        shutil.copyfile(real_pdf, destination)
        return destination

    monkeypatch.setattr(sources, "_download", fake_download)

    document = sources.resolve_paper("2401.12345", tmp_path / "ws")

    assert downloads == ["https://arxiv.org/pdf/2401.12345"]
    assert document.reference.kind == "arxiv"
    assert document.metadata["arxiv_id"] == "2401.12345"
    assert "Arxiv mirror content" in document.text
