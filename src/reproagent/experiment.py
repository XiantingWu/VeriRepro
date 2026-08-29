from __future__ import annotations

import os
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import BinaryIO

from .models import ExperimentResult

_DEFAULT_MAX_EXPERIMENT_LOG_BYTES = 8 * 1024 * 1024
_STREAM_CHUNK_BYTES = 64 * 1024
_CONTAINER_CLEANUP_TIMEOUT_SECONDS = 30
_CLIENT_CLEANUP_TIMEOUT_SECONDS = 10
_FALLBACK_RUNTIME_UID = 65532
_DEFAULT_RUNTIME_WORKSPACE_TMPFS_BYTES = 4 * 1024 * 1024 * 1024
_DEFAULT_RUNTIME_TMP_TMPFS_BYTES = 1024 * 1024 * 1024
_DEFAULT_RUNTIME_OUTPUT_TMPFS_BYTES = 1024 * 1024 * 1024


class ExperimentTimeoutError(RuntimeError):
    """Raised after a timed-out Docker experiment receives bounded cleanup."""


def _positive_env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer") from exc
    if value <= 0:
        raise RuntimeError(f"{name} must be positive")
    return value


def _max_experiment_log_bytes() -> int:
    return _positive_env_int(
        "VERIREPRO_MAX_EXPERIMENT_LOG_BYTES",
        _DEFAULT_MAX_EXPERIMENT_LOG_BYTES,
    )


def _runtime_tmpfs_bytes(name: str, default: int) -> int:
    return _positive_env_int(name, default)


def _runtime_identity(output_dir: Path) -> str:
    """Return an explicit non-root Docker UID:GID and prepare root-host output safely."""
    getuid = getattr(os, "getuid", None)
    getgid = getattr(os, "getgid", None)
    uid = int(getuid()) if callable(getuid) else _FALLBACK_RUNTIME_UID
    gid = int(getgid()) if callable(getgid) else _FALLBACK_RUNTIME_UID
    if uid < 0 or gid < 0:
        raise RuntimeError("host runtime UID/GID must be non-negative")

    if uid == 0:
        uid = _FALLBACK_RUNTIME_UID
        gid = _FALLBACK_RUNTIME_UID
        chown = getattr(os, "chown", None)
        if not callable(chown):
            raise RuntimeError(
                "VeriRepro refuses container UID 0 and cannot remap the run-scoped output directory on this host"
            )
        try:
            chown(output_dir, uid, gid)
        except OSError as exc:
            raise RuntimeError(
                "VeriRepro refuses container UID 0 and could not prepare the run-scoped output directory for an unprivileged UID"
            ) from exc
    elif gid == 0:
        # A non-root UID does not need root-group membership merely to write its
        # own run-scoped bind mount. Avoid carrying host group 0 into Docker.
        gid = uid

    if uid == 0 or gid == 0:
        raise RuntimeError("VeriRepro runtime identity must be fully non-root")
    return f"{uid}:{gid}"


def _tmpfs_spec(path: str, runtime_user: str, size_bytes: int) -> str:
    try:
        uid_text, gid_text = runtime_user.split(":", 1)
        uid = int(uid_text)
        gid = int(gid_text)
    except (ValueError, AttributeError) as exc:
        raise RuntimeError("invalid runtime UID:GID for tmpfs ownership") from exc
    if uid <= 0 or gid <= 0:
        raise RuntimeError("runtime tmpfs ownership must be fully non-root")
    return f"{path}:rw,nosuid,nodev,exec,size={size_bytes},mode=0700,uid={uid},gid={gid}"


_RUNTIME_BOOTSTRAP = (
    "set -eu; "
    "cp -R /opt/verirepro-repository/. /workspace/; "
    "chmod -R u+rwX /workspace; "
    "cd /workspace; "
    'exec sh -lc "$1"'
)


def _drain_bounded(stream: BinaryIO, limit: int, sink: list[bytes]) -> None:
    """Drain a child stream fully while retaining only a bounded final tail on the host.

    Scientific result markers are commonly emitted at the end of an experiment.
    Retaining the final bytes preserves those markers even when verbose training
    logs exceed the host capture limit, while still bounding Python memory.
    """
    retained = bytearray()
    total = 0
    try:
        while True:
            chunk = stream.read(_STREAM_CHUNK_BYTES)
            if not chunk:
                break
            total += len(chunk)
            retained.extend(chunk)
            if len(retained) > limit:
                del retained[: len(retained) - limit]
    finally:
        try:
            stream.close()
        except OSError:
            pass

    if total > limit:
        marker = (
            f"[VeriRepro log truncated: retained final {limit} of {total} bytes; "
            "raise VERIREPRO_MAX_EXPERIMENT_LOG_BYTES explicitly if needed]\n"
        ).encode()
        retained = bytearray(marker) + retained
    sink.append(bytes(retained))


def _force_remove_container(name: str) -> bool:
    try:
        cleanup = subprocess.run(
            ["docker", "rm", "-f", name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=_CONTAINER_CLEANUP_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return cleanup.returncode == 0


def _stop_client(process: subprocess.Popen[bytes]) -> None:
    try:
        process.wait(timeout=_CLIENT_CLEANUP_TIMEOUT_SECONDS)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        process.kill()
    except OSError:
        return
    try:
        process.wait(timeout=_CLIENT_CLEANUP_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        return


def _decode_capture(chunks: list[bytes]) -> str:
    if not chunks:
        return ""
    return chunks[0].decode("utf-8", errors="replace")


def run_in_docker(
    image: str,
    command: str,
    output_dir: Path,
    dataset_dir: Path,
    model_dir: Path | None = None,
    *,
    output_backend: str = "persistent",
    network: bool = False,
    gpu: bool = False,
    timeout: int = 1800,
) -> ExperimentResult:
    if timeout <= 0:
        raise ValueError("experiment timeout must be positive")
    if output_backend not in {"persistent", "ephemeral"}:
        raise ValueError("output_backend must be 'persistent' or 'ephemeral'")
    log_limit = _max_experiment_log_bytes()
    workspace_tmpfs_bytes = _runtime_tmpfs_bytes(
        "VERIREPRO_RUNTIME_WORKSPACE_TMPFS_BYTES",
        _DEFAULT_RUNTIME_WORKSPACE_TMPFS_BYTES,
    )
    tmp_tmpfs_bytes = _runtime_tmpfs_bytes(
        "VERIREPRO_RUNTIME_TMP_TMPFS_BYTES",
        _DEFAULT_RUNTIME_TMP_TMPFS_BYTES,
    )
    output_tmpfs_bytes = (
        _runtime_tmpfs_bytes(
            "VERIREPRO_RUNTIME_OUTPUT_TMPFS_BYTES",
            _DEFAULT_RUNTIME_OUTPUT_TMPFS_BYTES,
        )
        if output_backend == "ephemeral"
        else None
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    dataset_dir.mkdir(parents=True, exist_ok=True)
    if model_dir is not None:
        model_dir.mkdir(parents=True, exist_ok=True)
    runtime_user = _runtime_identity(output_dir)
    workspace_tmpfs = _tmpfs_spec("/workspace", runtime_user, workspace_tmpfs_bytes)
    tmp_tmpfs = _tmpfs_spec("/tmp", runtime_user, tmp_tmpfs_bytes)
    output_tmpfs = (
        _tmpfs_spec("/repro-output", runtime_user, output_tmpfs_bytes)
        if output_tmpfs_bytes is not None
        else None
    )
    container_name = f"verirepro-run-{uuid.uuid4().hex[:16]}"
    docker_command = [
        "docker",
        "run",
        "--rm",
        "--name",
        container_name,
        "--init",
        "--user",
        runtime_user,
        "--read-only",
        "--tmpfs",
        workspace_tmpfs,
        "--tmpfs",
        tmp_tmpfs,
        "--memory",
        "8g",
        "--cpus",
        "4",
        "--pids-limit",
        "512",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--shm-size",
        "1g",
        "-e",
        "HOME=/tmp",
        "-e",
        "TMPDIR=/tmp",
        "-e",
        "XDG_CACHE_HOME=/tmp/.cache",
        "-e",
        "MPLCONFIGDIR=/tmp/matplotlib",
        "-e",
        "VERIREPRO_OUTPUT_DIR=/repro-output",
        "-e",
        "VERIREPRO_DATASET_DIR=/datasets",
        "-e",
        "REPROAGENT_OUTPUT_DIR=/repro-output",
        "-e",
        "REPROAGENT_DATASET_DIR=/datasets",
        "-e",
        f"VERIREPRO_OUTPUT_PERSISTENCE={output_backend}",
        "-e",
        f"REPROAGENT_OUTPUT_PERSISTENCE={output_backend}",
    ]
    if output_backend == "persistent":
        docker_command.extend(["-v", f"{output_dir.resolve()}:/repro-output"])
    else:
        assert output_tmpfs is not None
        docker_command.extend(["--tmpfs", output_tmpfs])
    docker_command.extend(["-v", f"{dataset_dir.resolve()}:/datasets:ro"])
    if model_dir is not None:
        docker_command.extend(
            [
                "-e",
                "VERIREPRO_MODEL_DIR=/models",
                "-e",
                "REPROAGENT_MODEL_DIR=/models",
                "-v",
                f"{model_dir.resolve()}:/models:ro",
            ]
        )
    if not network:
        docker_command.extend(["--network", "none"])
    if gpu:
        docker_command.extend(["--gpus", "all"])
    docker_command.extend([image, "sh", "-lc", _RUNTIME_BOOTSTRAP, "verirepro-runtime", command])

    started = time.monotonic()
    process = subprocess.Popen(
        docker_command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=False,
    )
    assert process.stdout is not None
    assert process.stderr is not None

    stdout_capture: list[bytes] = []
    stderr_capture: list[bytes] = []
    stdout_thread = threading.Thread(
        target=_drain_bounded,
        args=(process.stdout, log_limit, stdout_capture),
        name=f"{container_name}-stdout",
        daemon=True,
    )
    stderr_thread = threading.Thread(
        target=_drain_bounded,
        args=(process.stderr, log_limit, stderr_capture),
        name=f"{container_name}-stderr",
        daemon=True,
    )
    stdout_thread.start()
    stderr_thread.start()

    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        cleaned = _force_remove_container(container_name)
        _stop_client(process)
        if not cleaned:
            cleaned = _force_remove_container(container_name)
        stdout_thread.join(timeout=_CLIENT_CLEANUP_TIMEOUT_SECONDS)
        stderr_thread.join(timeout=_CLIENT_CLEANUP_TIMEOUT_SECONDS)
        cleanup_detail = (
            "container force-cleaned"
            if cleaned
            else "container cleanup could not be confirmed; inspect the Docker daemon before continuing"
        )
        raise ExperimentTimeoutError(
            f"experiment timed out after {timeout} seconds; {cleanup_detail} ({container_name})"
        ) from exc

    stdout_thread.join(timeout=_CLIENT_CLEANUP_TIMEOUT_SECONDS)
    stderr_thread.join(timeout=_CLIENT_CLEANUP_TIMEOUT_SECONDS)
    if stdout_thread.is_alive() or stderr_thread.is_alive():
        cleaned = _force_remove_container(container_name)
        _stop_client(process)
        detail = (
            "container force-cleaned" if cleaned else "container cleanup could not be confirmed"
        )
        raise RuntimeError(f"experiment log capture did not terminate cleanly; {detail}")

    return ExperimentResult(
        command=command,
        exit_code=int(process.returncode or 0),
        stdout=_decode_capture(stdout_capture),
        stderr=_decode_capture(stderr_capture),
        duration_seconds=time.monotonic() - started,
    )
