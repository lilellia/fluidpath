import pytest

from fluidpath import Path


def test_is_directory_exists(mock_fs: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(mock_fs)

    p = mock_fs / "a" / "b"
    assert p.is_directory()


def test_is_directory_exists_via_symlink(mock_fs: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(mock_fs)

    p = mock_fs / "symlink-to-dir"
    assert p.is_directory()


def test_is_directory_exists_via_symlink_without_following(mock_fs: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(mock_fs)

    p = mock_fs / "symlink-to-dir"
    assert not p.is_directory(follow_symlinks=False)


def test_is_directory_does_not_exist_must_exist_true(mock_fs: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(mock_fs)

    p = mock_fs / "does-not-exist/"
    assert not p.is_directory(must_exist=True)


def test_is_directory_does_not_exist_must_exist_false(mock_fs: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(mock_fs)

    p = mock_fs.join_path("does-not-exist/")
    assert p.is_directory(must_exist=False)
