from __future__ import annotations

from pathlib import Path

import pytest

from reproagent import sources


class FakeResponse:
    def __init__(
        self,
        *,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
        chunks: tuple[bytes, ...] = (),
    ) -> None:
        self.status_code = status_code
        self.headers = headers or {}
        self._chunks = chunks
        self.closed = False

    def close(self) -> None:
        self.closed = True

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def iter_content(self, chunk_size: int):
        del chunk_size
        yield from self._chunks


def test_paper_download_rejects_private_literal() -> None:
    with pytest.raises(sources.SourceResolutionError, match="not publicly routable"):
        sources._validate_pdf_url("https://127.0.0.1/paper.pdf")


def test_paper_download_requires_https(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VERIREPRO_ALLOW_INSECURE_HTTP", raising=False)
    with pytest.raises(sources.SourceResolutionError, match="require HTTPS"):
        sources._validate_pdf_url("http://example.org/paper.pdf", resolve_dns=False)


def test_redirect_to_private_address_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    first = FakeResponse(
        status_code=302,
        headers={"Location": "https://127.0.0.1/internal.pdf"},
    )
    calls = 0

    def fake_get(*args, **kwargs):
        nonlocal calls
        del args, kwargs
        calls += 1
        return first

    monkeypatch.setattr(sources, "_host_is_public", lambda host: host == "public.example")
    monkeypatch.setattr(sources.requests, "get", fake_get)

    with pytest.raises(sources.SourceResolutionError, match="not publicly routable"):
        sources._safe_pdf_response("https://public.example/paper.pdf", timeout=1)
    assert calls == 1
    assert first.closed is True


def test_pdf_size_limit_is_enforced_before_write(
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
    with pytest.raises(sources.SourceResolutionError, match="exceeds VERIREPRO_MAX_PDF_BYTES"):
        sources._download("https://example.org/paper.pdf", destination)

    assert not destination.exists()
    assert not (tmp_path / ".paper.pdf.part").exists()
    assert response.closed is True


def test_pdf_download_uses_atomic_partial_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = b"%PDF-1.7\nexample"
    response = FakeResponse(
        headers={"content-type": "application/pdf"},
        chunks=(payload[:5], payload[5:]),
    )
    monkeypatch.setattr(sources, "_safe_pdf_response", lambda *args, **kwargs: response)
    monkeypatch.setattr(sources, "_max_pdf_bytes", lambda: 1024)

    destination = tmp_path / "paper.pdf"
    assert sources._download("https://example.org/paper.pdf", destination) == destination
    assert destination.read_bytes() == payload
    assert not (tmp_path / ".paper.pdf.part").exists()
    assert response.closed is True
