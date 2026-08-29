import io

import pytest

from reproagent.experiment import _decode_capture, _drain_bounded, _positive_env_int, _tmpfs_spec


def test_drain_bounded_retains_tail_and_marks_truncation():
    source = io.BytesIO(b"0123456789")
    sink: list[bytes] = []
    _drain_bounded(source, 4, sink)
    assert sink
    assert b"log truncated" in sink[0]
    assert sink[0].endswith(b"6789")


def test_tmpfs_spec_requires_non_root_identity():
    with pytest.raises(RuntimeError, match="fully non-root"):
        _tmpfs_spec("/tmp", "0:1000", 1024)
    assert "uid=1000,gid=1001" in _tmpfs_spec("/tmp", "1000:1001", 1024)


def test_positive_env_int_rejects_invalid_values(monkeypatch):
    monkeypatch.setenv("VERIREPRO_TEST_LIMIT", "0")
    with pytest.raises(RuntimeError, match="must be positive"):
        _positive_env_int("VERIREPRO_TEST_LIMIT", 1)


def test_decode_capture_is_lossy_safe_for_invalid_utf8():
    assert "replacement" not in _decode_capture([b"ok\xff"]).lower()
    assert _decode_capture([]) == ""
