import os
import socket
import sys

import pytest

from fluidpath import Path, PathType


def test_pathtype_regular_file(mock_fs: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(mock_fs)

    p = mock_fs / "a" / "b" / "file.txt"
    assert p.type == PathType.REGULAR_FILE


def test_pathtype_directory(mock_fs: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(mock_fs)

    p = mock_fs / "a" / "b"
    assert p.type == PathType.DIRECTORY


def test_pathtype_symlink(mock_fs: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(mock_fs)

    p = mock_fs / "symlink-to-file"
    assert p.type == PathType.SYMLINK


@pytest.mark.skipif(sys.platform == "win32", reason="Requires POSIX (os.mkfifo)")
def test_pathtype_pipe(mock_fs: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(mock_fs)

    p = mock_fs / "pipe"

    os.mkfifo(str(p))

    assert p.type == PathType.PIPE


@pytest.mark.skipif(sys.platform == "win32", reason="Requires POSIX")
def test_pathtype_char_device_dev_null() -> None:
    p = Path("/dev/null")
    assert p.type == PathType.CHAR_DEVICE


def test_pathtype_socket(mock_fs: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(mock_fs)

    p = mock_fs / "socket"
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.bind(str(p))

    assert p.type == PathType.SOCKET


def test_pathtype_does_not_exist(mock_fs: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(mock_fs)

    p = mock_fs / "does-not-exist"
    assert p.type == PathType.DOES_NOT_EXIST
