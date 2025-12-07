import pytest

from fluidpath import Path


def test_temp_file_creation(mock_fs: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(mock_fs)

    with Path.temporary_file() as f:
        assert f.exists()
        assert f.is_file()
        assert not f.is_directory()


def test_temp_dir_creation(mock_fs: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(mock_fs)

    with Path.temporary_directory() as d:
        assert d.exists()
        assert d.is_directory()
        assert not d.is_file()


def test_temp_file_with_prefix(mock_fs: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(mock_fs)

    with Path.temporary_file(prefix="prefix") as f:
        assert f.name.startswith("prefix")


def test_temp_file_with_suffix(mock_fs: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(mock_fs)

    with Path.temporary_file(suffix="suffix") as f:
        assert f.name.endswith("suffix")


def test_temp_file_with_dir(mock_fs: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(mock_fs)

    with Path.temporary_file(parent=mock_fs / "a/") as f:
        assert f.parent.name == "a"


def test_temp_file_delete_after_with(mock_fs: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(mock_fs)

    with Path.temporary_file() as f:
        pass

    assert not f.exists()


def test_temp_file_delete_false_after_with(mock_fs: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(mock_fs)

    with Path.temporary_file(delete=False) as f:
        pass

    assert f.exists()


def test_temp_file_write_text(mock_fs: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(mock_fs)

    with Path.temporary_file(delete=False) as f:
        f.write_text("foo")

    assert f.read_text() == "foo"


def test_temp_directory_and_file(mock_fs: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(mock_fs)

    with Path.temporary_directory() as d:
        with Path.temporary_file(parent=d) as f:
            assert f.parent == d


def test_temp_directory_delete_after_with(mock_fs: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(mock_fs)

    with Path.temporary_directory() as d:
        pass

    assert not d.exists()


def test_temp_directory_delete_false_after_with(mock_fs: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(mock_fs)

    with Path.temporary_directory(delete=False) as d:
        pass

    assert d.exists()


def test_temp_directory_with_suffix(mock_fs: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(mock_fs)

    with Path.temporary_directory(suffix="suffix") as d:
        assert d.name.endswith("suffix")


def test_temp_directory_with_prefix(mock_fs: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(mock_fs)

    with Path.temporary_directory(prefix="prefix") as d:
        assert d.name.startswith("prefix")


def test_temp_directory_with_parent(mock_fs: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(mock_fs)

    with Path.temporary_directory(parent=mock_fs / "a/") as d:
        assert d.parent.name == "a"


def test_temp_directory_rmtree(mock_fs: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(mock_fs)

    with Path.temporary_directory() as d:
        files = [d / f"file-{i}" for i in range(30)]
        for f in files:
            f.write_text("foo")

    assert not d.exists()

    for f in files:
        assert not f.exists()
